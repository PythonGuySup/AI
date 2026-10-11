from fastapi import FastAPI
from kafka_producer import send_event
from mongodb_client import events_collection
import datetime
import logging

app = FastAPI()
logger = logging.getLogger(__name__)


@app.post("/event")
def handle_event(event: dict):
    logger.info(f"Event received: {event}")

    if not isinstance(event, dict):
        return {"error": "Invalid event format"}

    event_record = {
        "event": event,
        "received_at": datetime.datetime.now(datetime.timezone.utc),
        "source": "task-service"
    }

    mongo_ok = True
    kafka_ok = True

    # MongoDB
    try:
        events_collection.insert_one(event_record)
    except Exception as e:
        mongo_ok = False
        logger.error(f"MongoDB error: {e}")

    # Kafka
    try:
        send_event(event)
    except Exception as e:
        kafka_ok = False
        logger.error(f"Kafka error: {e}")

    return {
        "status": "processed",
        "mongo": mongo_ok,
        "kafka": kafka_ok
    }