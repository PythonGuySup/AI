from fastapi import FastAPI
import threading
from kafka_consumer import start_consumer

app = FastAPI()


@app.on_event("startup")
def run_kafka():
    thread = threading.Thread(target=start_consumer)
    thread.daemon = True
    thread.start()