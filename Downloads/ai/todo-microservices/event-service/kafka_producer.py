import json
import os
import logging
from kafka import KafkaProducer

KAFKA_HOST = os.getenv("KAFKA_HOST", "kafka")

logger = logging.getLogger(__name__)

producer = None

def get_producer():
    global producer
    if producer is None:
        producer = KafkaProducer(
            bootstrap_servers=f'{KAFKA_HOST}:9092',
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            retries=5,
            request_timeout_ms=10000
        )
    return producer

def send_event(event):
    try:
        logger.info(f"Sending event to Kafka: {event}")
        p = get_producer()
        future = p.send("tasks", value=event)
        future.get(timeout=10)
        p.flush()
    except Exception as e:
        logger.error(f"Kafka send error: {e}")