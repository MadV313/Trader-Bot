import json
import os

ORDERS_FILE = "data/orders.json"
SESSION_CACHE = {}

def start_session(user_id):
    SESSION_CACHE[user_id] = []

def add_item(user_id, item):
    SESSION_CACHE.setdefault(user_id, []).append(item)

def get_session_items(user_id):
    return SESSION_CACHE.get(user_id, [])

def clear_session(user_id):
    SESSION_CACHE.pop(user_id, None)

def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)

def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
