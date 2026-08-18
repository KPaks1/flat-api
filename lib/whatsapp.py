import os
import logging
import requests

logger = logging.getLogger(__name__)

_TOKEN = os.environ["WHATSAPP_TOKEN"]
_PHONE_NUMBER_ID = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
_RECIPIENTS = [r.strip() for r in os.environ.get("WHATSAPP_RECIPIENTS", "").split(",") if r.strip()]
_API_URL = f"https://graph.facebook.com/v19.0/{_PHONE_NUMBER_ID}/messages"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}", "Content-Type": "application/json"}


def send_plant_watered(plant_name: str, room: str):
    for number in _RECIPIENTS:
        _send_template("plant_watered", number, [plant_name, room])


def send_plant_overdue(plant_name: str, room: str, days_since: float):
    for number in _RECIPIENTS:
        _send_template("plant_needs_watering", number, [plant_name, room, f"{days_since:.1f}"])


def _send_template(template: str, to: str, params: list[str]):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }
            ],
        },
    }
    resp = requests.post(_API_URL, json=payload, headers=_HEADERS, timeout=10)
    if not resp.ok:
        logger.error("WhatsApp API error for %s: %s %s", to, resp.status_code, resp.text)
    else:
        logger.info("WhatsApp notification sent to %s (template: %s)", to, template)
