import os
import json
import logging
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)

VAPID_PRIVATE_KEY = os.environ["VAPID_PRIVATE_KEY"]
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "admin@example.com")


def send_push_notification(subscription: dict, title: str, body: str) -> bool:
    """
    Send a Web Push notification to a single subscription.
    Returns False if the subscription is expired/invalid (caller should remove it).
    Raises on unexpected errors.
    """
    payload = json.dumps({"title": title, "body": body})
    subscription_info = {
        "endpoint": subscription["endpoint"],
        "keys": {
            "p256dh": subscription["p256dh"],
            "auth": subscription["auth"],
        },
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
        )
        return True
    except WebPushException as ex:
        response = ex.response
        if response is not None and response.status_code in (404, 410):
            logger.warning(
                "Subscription %s expired (HTTP %s), will remove.",
                subscription.get("row_key", "?"),
                response.status_code,
            )
            return False
        logger.error("WebPushException for sub %s: %s", subscription.get("row_key", "?"), ex)
        raise
