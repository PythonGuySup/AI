import redis
import json
import os

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=0,
    decode_responses=True
)

def get_tasks_cache_key() -> str:
    return "tasks:all"

def get_task_cache_key(task_id: str) -> str:
    return f"task:{task_id}"

def clear_tasks_cache():
    redis_client.delete(get_tasks_cache_key())
    keys = redis_client.keys("task:*")
    if keys:
        redis_client.delete(*keys)