import json
import os
import time

# Load config from environment variable
config = json.loads(os.environ.get("CONFIG_JSON"))
SESSION_TIMEOUT = config.get("session_timeout_minutes", 15) * 60  # Default to 15 minutes if not set

ORDERS_FILE = "data/orders.json"
SESSION_CACHE = {}

def start_session(user_id):
    SESSION_CACHE[user_id] = {
        "items": [],
        "last_active": time.time()
    }

def add_item(user_id, item):
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    SESSION_CACHE[user_id]["items"].append(item)
    SESSION_CACHE[user_id]["last_active"] = time.time()

def get_session_items(user_id):
    session = SESSION_CACHE.get(user_id)
    if not session or not is_session_active(user_id):
        clear_session(user_id)
        return []
    return session["items"]

def clear_session(user_id):
    SESSION_CACHE.pop(user_id, None)

def is_session_active(user_id):
    session = SESSION_CACHE.get(user_id)
    if not session:
        return False
    return (time.time() - session["last_active"]) < SESSION_TIMEOUT

def remove_item(user_id, item_index):
    if user_id in SESSION_CACHE and 0 <= item_index < len(SESSION_CACHE[user_id]["items"]):
        SESSION_CACHE[user_id]["items"].pop(item_index)
        SESSION_CACHE[user_id]["last_active"] = time.time()

def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)

def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
