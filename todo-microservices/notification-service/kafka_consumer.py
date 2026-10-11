from kafka import KafkaConsumer
import json
import os
import time

KAFKA_HOST = os.getenv("KAFKA_HOST", "kafka")


def safe_deserialize(x):
    try:
        return json.loads(x.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print(f"Skipping invalid JSON message: {x}")
        return None


def create_consumer():
    while True:
        try:
            print("Connecting to Kafka...")
            consumer = KafkaConsumer(
                'tasks',
                bootstrap_servers=f'{KAFKA_HOST}:9092',
                value_deserializer=safe_deserialize,
                auto_offset_reset='earliest',
                group_id='notification-group'
            )
            print("Connected to Kafka ✅")
            return consumer
        except Exception as e:
            print(f"Kafka not ready ({e}), retrying in 5 sec...")
            time.sleep(5)


def start_consumer():
    consumer = create_consumer()

    print("Kafka consumer started...")
    for message in consumer:
        event = message.value
        if event is not None:
            print("Received event from Kafka:", event)
        else:
            print("Skipped invalid message")