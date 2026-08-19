import os
import uuid
import json
import base64
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient, TableClient, UpdateMode
from azure.storage.queue import QueueClient
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError

CONN_STR = os.environ["STORAGE_CONNECTION_STRING"]

PLANTS_TABLE = "plants"
SUBSCRIPTIONS_TABLE = "subscriptions"
WATERING_QUEUE = "watering-notifications"

PLANTS_PK = "plants"
SUBSCRIPTIONS_PK = "subscriptions"

_storage_ready = False


def _ensure_initialized():
    global _storage_ready
    if not _storage_ready:
        _storage_ready = True  # set first to prevent any re-entrant calls
        ensure_tables_and_queues()


def _table_client(table_name: str) -> TableClient:
    _ensure_initialized()
    svc = TableServiceClient.from_connection_string(CONN_STR)
    return svc.get_table_client(table_name)


def ensure_tables_and_queues():
    svc = TableServiceClient.from_connection_string(CONN_STR)
    for name in (PLANTS_TABLE, SUBSCRIPTIONS_TABLE):
        try:
            svc.create_table(name)
        except ResourceExistsError:
            pass

    q = QueueClient.from_connection_string(CONN_STR, WATERING_QUEUE)
    try:
        q.create_queue()
    except ResourceExistsError:
        pass


# --- Plants ---

def get_all_plants() -> list:
    client = _table_client(PLANTS_TABLE)
    return [
        _deserialize_plant(e)
        for e in client.query_entities(f"PartitionKey eq '{PLANTS_PK}'")
    ]


def get_plant(plant_id: str) -> "dict | None":
    client = _table_client(PLANTS_TABLE)
    try:
        entity = client.get_entity(PLANTS_PK, plant_id)
        return _deserialize_plant(entity)
    except ResourceNotFoundError:
        return None


def create_plant(plant_id: str, data: dict) -> dict:
    client = _table_client(PLANTS_TABLE)
    entity = {
        "PartitionKey": PLANTS_PK,
        "RowKey": plant_id,
        "name": data["name"],
        "room": data["room"],
        "plant_type": data.get("plant_type", ""),
        "watering_interval_days": float(data["watering_interval_days"]),
        "last_watered": "",
        "last_notification_sent": "",
    }
    client.create_entity(entity)
    return _deserialize_plant(entity)


def update_plant(plant_id: str, data: dict) -> "dict | None":
    client = _table_client(PLANTS_TABLE)
    try:
        entity = client.get_entity(PLANTS_PK, plant_id)
    except ResourceNotFoundError:
        return None
    for field in ("name", "room", "plant_type", "watering_interval_days"):
        if field in data:
            entity[field] = float(data[field]) if field == "watering_interval_days" else data[field]
    client.update_entity(entity, mode=UpdateMode.MERGE)
    return _deserialize_plant(entity)


def mark_plant_watered(plant_id: str) -> "dict | None":
    client = _table_client(PLANTS_TABLE)
    try:
        entity = client.get_entity(PLANTS_PK, plant_id)
    except ResourceNotFoundError:
        return None
    entity["last_watered"] = datetime.now(timezone.utc).isoformat()
    client.update_entity(entity, mode=UpdateMode.MERGE)
    return _deserialize_plant(entity)


def update_plant_notification_sent(plant_id: str):
    client = _table_client(PLANTS_TABLE)
    try:
        entity = client.get_entity(PLANTS_PK, plant_id)
    except ResourceNotFoundError:
        return
    entity["last_notification_sent"] = datetime.now(timezone.utc).isoformat()
    client.update_entity(entity, mode=UpdateMode.MERGE)


def delete_plant(plant_id: str) -> bool:
    client = _table_client(PLANTS_TABLE)
    try:
        client.delete_entity(PLANTS_PK, plant_id)
        return True
    except ResourceNotFoundError:
        return False


# --- Subscriptions ---

def get_all_subscriptions() -> list:
    client = _table_client(SUBSCRIPTIONS_TABLE)
    return [
        _deserialize_subscription(e)
        for e in client.query_entities(f"PartitionKey eq '{SUBSCRIPTIONS_PK}'")
    ]


def get_subscription(row_key: str) -> "dict | None":
    client = _table_client(SUBSCRIPTIONS_TABLE)
    try:
        entity = client.get_entity(SUBSCRIPTIONS_PK, row_key)
        return _deserialize_subscription(entity)
    except ResourceNotFoundError:
        return None


def save_subscription(endpoint: str, p256dh: str, auth: str, label: str = "") -> str:
    client = _table_client(SUBSCRIPTIONS_TABLE)
    existing = list(client.query_entities(
        f"PartitionKey eq '{SUBSCRIPTIONS_PK}'",
        select=["RowKey", "endpoint"],
    ))
    for e in existing:
        if e.get("endpoint") == endpoint:
            return e["RowKey"]
    row_key = str(uuid.uuid4())
    entity = {
        "PartitionKey": SUBSCRIPTIONS_PK,
        "RowKey": row_key,
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "label": label,
    }
    client.create_entity(entity)
    return row_key


def delete_subscription(row_key: str):
    client = _table_client(SUBSCRIPTIONS_TABLE)
    try:
        client.delete_entity(SUBSCRIPTIONS_PK, row_key)
    except ResourceNotFoundError:
        pass


# --- Queue ---

def enqueue_watering_event(plant_id: str, plant_name: str, room: str):
    _ensure_initialized()
    q = QueueClient.from_connection_string(CONN_STR, WATERING_QUEUE)
    message = json.dumps({
        "plant_id": plant_id,
        "plant_name": plant_name,
        "room": room,
    })
    q.send_message(base64.b64encode(message.encode()).decode())


# --- Deserializers ---

def _deserialize_plant(entity: dict) -> dict:
    return {
        "plant_id": entity["RowKey"],
        "name": entity.get("name", ""),
        "room": entity.get("room", ""),
        "plant_type": entity.get("plant_type", ""),
        "watering_interval_days": float(entity.get("watering_interval_days", 7)),
        "last_watered": entity.get("last_watered") or None,
        "last_notification_sent": entity.get("last_notification_sent") or None,
    }


def _deserialize_subscription(entity: dict) -> dict:
    return {
        "row_key": entity["RowKey"],
        "endpoint": entity.get("endpoint", ""),
        "p256dh": entity.get("p256dh", ""),
        "auth": entity.get("auth", ""),
        "label": entity.get("label", ""),
    }
