import hashlib
import hmac
import json
import logging
import pathlib
import re
import os
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import azure.functions as func
from lib import storage
from lib import webpush as wp
from lib import whatsapp

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.environ["VAPID_PUBLIC_KEY"]
DEVICE_TOKEN_SECRET = os.environ["DEVICE_TOKEN_SECRET"]
STATIC_DIR = pathlib.Path(__file__).parent / "static"

_allowed_ips_raw = os.environ.get("ALLOWED_SUBSCRIBE_IPS", "")
ALLOWED_SUBSCRIBE_IPS = {ip.strip() for ip in _allowed_ips_raw.split(",") if ip.strip()}

DEVICE_COOKIE_NAME = "device_token"
DEVICE_COOKIE_MAX_AGE = 315360000  # ~10 years

NFC_SCAN_COOLDOWN = timedelta(minutes=2)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text)


def _json(data, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        body=json.dumps(data),
        status_code=status,
        mimetype="application/json",
        headers={"Access-Control-Allow-Origin": "*"},
    )


def _error(message: str, status: int = 400) -> func.HttpResponse:
    return _json({"error": message}, status)


def _get_client_ip(req: func.HttpRequest) -> str:
    # Azure's load balancer forwards the real client IP here, as "ip:port"
    xff = req.headers.get("X-Forwarded-For", "")
    if not xff:
        return "127.0.0.1"  # local dev fallback
    ip = xff.split(",")[0].strip()
    if ip.count(":") == 1:  # IPv4 with port suffix
        ip = ip.split(":")[0]
    return ip


def _sign_device_token(row_key: str) -> str:
    sig = hmac.new(DEVICE_TOKEN_SECRET.encode(), row_key.encode(), hashlib.sha256).hexdigest()
    return f"{row_key}.{sig}"


def _verify_device_token(token: str) -> "str | None":
    row_key, sep, sig = token.partition(".")
    if not sep:
        return None
    expected = hmac.new(DEVICE_TOKEN_SECRET.encode(), row_key.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    return row_key


def _get_device_row_key(req: func.HttpRequest) -> "str | None":
    cookie_header = req.headers.get("Cookie", "")
    if not cookie_header:
        return None
    jar = SimpleCookie()
    jar.load(cookie_header)
    morsel = jar.get(DEVICE_COOKIE_NAME)
    if morsel is None:
        return None
    return _verify_device_token(morsel.value)


def _is_subscribed_device(req: func.HttpRequest) -> bool:
    row_key = _get_device_row_key(req)
    if not row_key:
        return False
    return storage.get_subscription(row_key) is not None


# ---------------------------------------------------------------------------
# NFC scan — phone browser opens this URL when sticker is scanned
# ---------------------------------------------------------------------------

@app.route(route="nfc/{plant_id}", methods=["GET"])
def nfc_scan(req: func.HttpRequest) -> func.HttpResponse:
    if not _is_subscribed_device(req):
        return func.HttpResponse(
            "<html><body><h2>This device isn't registered.</h2>"
            "<p>Open <a href=\"/subscribe\">/subscribe</a> from home wifi "
            "and enable notifications first, then come back and tap the sticker again.</p>"
            "</body></html>",
            status_code=403,
            mimetype="text/html",
        )

    plant_id = req.route_params.get("plant_id", "").strip()
    plant = storage.get_plant(plant_id)
    if plant is None:
        return func.HttpResponse(
            "<html><body><h2>Plant not found.</h2></body></html>",
            status_code=404,
            mimetype="text/html",
        )

    last_watered_str = plant.get("last_watered")
    already_watered_at = None
    if last_watered_str:
        last_watered = datetime.fromisoformat(last_watered_str)
        if last_watered.tzinfo is None:
            last_watered = last_watered.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - last_watered < NFC_SCAN_COOLDOWN:
            already_watered_at = last_watered

    if already_watered_at is not None:
        # Same scan re-hitting the endpoint (page refresh, double-tap) within the
        # cooldown — re-show the confirmation without re-notifying or re-logging.
        now_str = already_watered_at.strftime("%H:%M UTC")
    else:
        plant = storage.mark_plant_watered(plant_id)
        storage.enqueue_watering_event(plant_id, plant["name"], plant["room"])
        storage.record_watering_event(plant_id, plant["name"], plant["room"])
        now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Plant Watered</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      display: flex; flex-direction: column; align-items: center;
      justify-content: center; min-height: 100vh; margin: 0;
      background: #f0f9f0; color: #2d6a2d;
    }}
    .card {{
      background: white; border-radius: 16px; padding: 2rem 3rem;
      box-shadow: 0 4px 24px rgba(0,0,0,0.08); text-align: center;
    }}
    .tick {{ font-size: 4rem; margin-bottom: 0.5rem; }}
    h1 {{ margin: 0 0 0.5rem; font-size: 1.6rem; }}
    p {{ margin: 0; color: #666; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="tick">&#x2705;</div>
    <h1>{plant['name']} watered!</h1>
    <p>{plant['room']} &bull; {now_str}</p>
  </div>
</body>
</html>"""
    return func.HttpResponse(html, status_code=200, mimetype="text/html")


# ---------------------------------------------------------------------------
# Queue trigger — fan-out Web Push to all subscribers
# ---------------------------------------------------------------------------

@app.queue_trigger(
    arg_name="msg",
    queue_name="watering-notifications",
    connection="AzureWebJobsStorage",
)
def process_notification(msg: func.QueueMessage) -> None:
    try:
        data = json.loads(msg.get_body().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as ex:
        logger.error("Bad queue message: %s", ex)
        return

    plant_name = data.get("plant_name", "Unknown Plant")
    room = data.get("room", "")

    whatsapp.send_plant_watered(plant_name, room)

    title = f"\U0001f33f {plant_name} watered!"
    body = f"{plant_name} in {room} was just watered by a flatmate."
    subscriptions = storage.get_all_subscriptions()
    logger.info("Sending watered notification to %d subscribers.", len(subscriptions))
    for sub in subscriptions:
        try:
            success = wp.send_push_notification(sub, title, body)
            if not success:
                storage.delete_subscription(sub["row_key"])
        except Exception as ex:
            logger.error("Notification error for sub %s: %s", sub.get("row_key"), ex)


# ---------------------------------------------------------------------------
# Timer trigger — check for overdue plants every 6 hours
# ---------------------------------------------------------------------------

@app.timer_trigger(
    arg_name="timer",
    schedule="0 0 */6 * * *",
    run_on_startup=False,
)
def watering_check(timer: func.TimerRequest) -> None:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    plants = storage.get_all_plants()
    subscriptions = storage.get_all_subscriptions()
    if not subscriptions:
        logger.info("No subscribers — skipping watering check.")
        return

    for plant in plants:
        last_watered_str = plant.get("last_watered")
        if not last_watered_str:
            days_since = float("inf")
        else:
            last_watered = datetime.fromisoformat(last_watered_str)
            if last_watered.tzinfo is None:
                last_watered = last_watered.replace(tzinfo=timezone.utc)
            days_since = (now - last_watered).total_seconds() / 86400

        if days_since <= plant["watering_interval_days"]:
            continue

        last_notif_str = plant.get("last_notification_sent")
        if last_notif_str:
            last_notif = datetime.fromisoformat(last_notif_str)
            if last_notif.tzinfo is None:
                last_notif = last_notif.replace(tzinfo=timezone.utc)
            if last_notif.date().isoformat() == today:
                logger.info("Already notified about %s today.", plant["name"])
                continue

        title = f"\U0001f4a7 {plant['name']} needs watering!"
        if days_since == float("inf"):
            body = f"{plant['name']} in {plant['room']} hasn't been watered yet!"
            whatsapp.send_plant_overdue(plant["name"], plant["room"], 0)
        else:
            body = (
                f"{plant['name']} in {plant['room']} needs watering — "
                f"last watered {days_since:.1f} days ago."
            )
            whatsapp.send_plant_overdue(plant["name"], plant["room"], days_since)

        for sub in subscriptions:
            try:
                success = wp.send_push_notification(sub, title, body)
                if not success:
                    storage.delete_subscription(sub["row_key"])
            except Exception as ex:
                logger.error("Notification error for sub %s: %s", sub.get("row_key"), ex)

        storage.update_plant_notification_sent(plant["plant_id"])
        logger.info("Sent overdue notification for %s.", plant["name"])


# ---------------------------------------------------------------------------
# Subscribe page + service worker
# ---------------------------------------------------------------------------

def _redirect(location: str) -> func.HttpResponse:
    return func.HttpResponse(status_code=302, headers={"Location": location})


def _subscribe_html_response() -> func.HttpResponse:
    try:
        html = (STATIC_DIR / "subscribe.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse("subscribe.html not found", status_code=500)
    return func.HttpResponse(html, status_code=200, mimetype="text/html")


@app.route(route="/", methods=["GET"])
def root_page(req: func.HttpRequest) -> func.HttpResponse:
    return _redirect("/home" if _is_subscribed_device(req) else "/subscribe")


@app.route(route="subscribe", methods=["GET"])
def subscribe_page(req: func.HttpRequest) -> func.HttpResponse:
    if _is_subscribed_device(req):
        return _redirect("/home")
    return _subscribe_html_response()


@app.route(route="home", methods=["GET"])
def home_page(req: func.HttpRequest) -> func.HttpResponse:
    if not _is_subscribed_device(req):
        return _redirect("/subscribe")
    return _subscribe_html_response()


@app.route(route="dashboard", methods=["GET"])
def dashboard_page(req: func.HttpRequest) -> func.HttpResponse:
    try:
        html = (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse("dashboard.html not found", status_code=500)
    return func.HttpResponse(html, status_code=200, mimetype="text/html")

@app.route(route="manifest.json", methods=["GET"])
def manifest(req: func.HttpRequest) -> func.HttpResponse:
    try:
        manifest_json = (STATIC_DIR / "manifest.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse("manifest.json not found", status_code=500)
    return func.HttpResponse(manifest_json, status_code=200, mimetype="application/manifest+json")


@app.route(route="favicon.ico", methods=["GET"])
def favicon(req: func.HttpRequest) -> func.HttpResponse:
    try:
        svg = (STATIC_DIR / "favicon.svg").read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse("favicon.svg not found", status_code=500)
    return func.HttpResponse(svg, status_code=200, mimetype="image/svg+xml")


@app.route(route="sw.js", methods=["GET"])
def service_worker(req: func.HttpRequest) -> func.HttpResponse:
    try:
        js = (STATIC_DIR / "sw.js").read_text(encoding="utf-8")
    except FileNotFoundError:
        return func.HttpResponse("sw.js not found", status_code=500)
    return func.HttpResponse(
        js,
        status_code=200,
        mimetype="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.route(route="subscribe", methods=["POST"])
def save_subscription(req: func.HttpRequest) -> func.HttpResponse:
    if ALLOWED_SUBSCRIBE_IPS:
        client_ip = _get_client_ip(req)
        if client_ip not in ALLOWED_SUBSCRIBE_IPS:
            logger.warning("Subscription attempt from non-whitelisted IP: %s", client_ip)
            return _error("Access denied.", 403)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON body.")

    endpoint = (body.get("endpoint") or "").strip()
    p256dh = (body.get("p256dh") or "").strip()
    auth = (body.get("auth") or "").strip()
    label = (body.get("label") or "").strip()

    if not endpoint or not p256dh or not auth:
        return _error("Missing endpoint, p256dh, or auth.")

    row_key = storage.save_subscription(endpoint, p256dh, auth, label)
    response = _json({"id": row_key, "status": "subscribed"}, 201)
    secure_attr = "; Secure" if req.url.startswith("https://") else ""
    response.headers["Set-Cookie"] = (
        f"{DEVICE_COOKIE_NAME}={_sign_device_token(row_key)}; "
        f"Max-Age={DEVICE_COOKIE_MAX_AGE}; Path=/; HttpOnly{secure_attr}; SameSite=Lax"
    )
    return response


@app.route(route="subscribe", methods=["DELETE"])
def delete_subscription_route(req: func.HttpRequest) -> func.HttpResponse:
    row_key = _get_device_row_key(req)
    if row_key:
        storage.delete_subscription(row_key)

    response = _json({"status": "unsubscribed"})
    response.headers["Set-Cookie"] = f"{DEVICE_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
    return response


@app.route(route="vapid-public-key", methods=["GET"])
def vapid_public_key(req: func.HttpRequest) -> func.HttpResponse:
    return _json({"publicKey": VAPID_PUBLIC_KEY})


# ---------------------------------------------------------------------------
# Watering history
# ---------------------------------------------------------------------------

@app.route(route="watering-history", methods=["GET"])
def watering_history(req: func.HttpRequest) -> func.HttpResponse:
    try:
        days = int(req.params.get("days", "30"))
    except ValueError:
        return _error("days must be an integer.")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return _json(storage.get_watering_events_since(cutoff))


# ---------------------------------------------------------------------------
# Plants CRUD
# ---------------------------------------------------------------------------

@app.route(route="plants", methods=["GET"])
def list_plants(req: func.HttpRequest) -> func.HttpResponse:
    return _json(storage.get_all_plants())


@app.route(route="plants", methods=["POST"])
def create_plant(req: func.HttpRequest) -> func.HttpResponse:
    if not _is_subscribed_device(req):
        return _error("Device not registered. Subscribe from home wifi first.", 403)

    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON body.")

    name = (body.get("name") or "").strip()
    room = (body.get("room") or "").strip()
    if not name or not room:
        return _error("name and room are required.")
    if "watering_interval_days" not in body:
        return _error("watering_interval_days is required.")

    plant_id = _slugify(f"{room}-{name}")
    if storage.get_plant(plant_id):
        return _error(f"Plant '{plant_id}' already exists.", 409)

    plant = storage.create_plant(plant_id, body)
    return _json(plant, 201)


@app.route(route="plants/{plant_id}", methods=["PUT"])
def update_plant(req: func.HttpRequest) -> func.HttpResponse:
    if not _is_subscribed_device(req):
        return _error("Device not registered. Subscribe from home wifi first.", 403)

    plant_id = req.route_params.get("plant_id", "")
    try:
        body = req.get_json()
    except ValueError:
        return _error("Invalid JSON body.")

    plant = storage.update_plant(plant_id, body)
    if plant is None:
        return _error("Plant not found.", 404)
    return _json(plant)


@app.route(route="plants/{plant_id}", methods=["DELETE"])
def delete_plant(req: func.HttpRequest) -> func.HttpResponse:
    if not _is_subscribed_device(req):
        return _error("Device not registered. Subscribe from home wifi first.", 403)

    plant_id = req.route_params.get("plant_id", "")
    if not storage.delete_plant(plant_id):
        return _error("Plant not found.", 404)
    return func.HttpResponse(status_code=204)
