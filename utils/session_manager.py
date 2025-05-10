import json
import os
import time

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))
SESSION_TIMEOUT = config.get("session_timeout_minutes", 15) * 60  # Default to 15 minutes

ORDERS_FILE = "data/orders.json"
LOG_DIR = "data/logs"
LOG_FILE = os.path.join(LOG_DIR, "session_activity.log")
SESSION_CACHE = {}


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log(message):
    ensure_log_dir()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    full_message = f"[SessionManager] [{timestamp}] {message}"
    print(full_message)
    with open(LOG_FILE, "a") as log_file:
        log_file.write(full_message + "\n")


def start_session(user_id):
    SESSION_CACHE[user_id] = {
        "items": [],
        "last_active": time.time()
    }
    log(f"Session started for user {user_id}.")


def add_item(user_id, item):
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    SESSION_CACHE[user_id]["items"].append(item)
    SESSION_CACHE[user_id]["last_active"] = time.time()
    log(f"Added item to session for user {user_id}: {item}.")


def get_session_items(user_id):
    session = SESSION_CACHE.get(user_id)
    if not session or not is_session_active(user_id):
        clear_session(user_id)
        return []
    return session["items"]


def clear_session(user_id):
    if user_id in SESSION_CACHE:
        log(f"Session cleared for user {user_id}.")
    SESSION_CACHE.pop(user_id, None)


def is_session_active(user_id):
    session = SESSION_CACHE.get(user_id)
    if not session:
        return False
    if (time.time() - session["last_active"]) >= SESSION_TIMEOUT:
        log(f"Session for user {user_id} timed out.")
        return False
    return True


def remove_item(user_id, item_index):
    if user_id in SESSION_CACHE and 0 <= item_index < len(SESSION_CACHE[user_id]["items"]):
        removed_item = SESSION_CACHE[user_id]["items"].pop(item_index)
        SESSION_CACHE[user_id]["last_active"] = time.time()
        log(f"Removed item from session for user {user_id}: {removed_item}.")


def load_orders():
    if not os.path.exists(ORDERS_FILE):
        log("Orders file not found. Returning empty orders.")
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)


def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log("Orders file saved successfully.")


def validate_session(user_id):
    """Ensure the session is active and reset timeout."""
    current_time = time.time()
    session = SESSION_CACHE.get(user_id)
    if session and (current_time - session['last_active'] < SESSION_TIMEOUT):
        SESSION_CACHE[user_id]['last_active'] = current_time
        return True
    else:
        end_session(user_id)
        return False

def end_session(user_id):
    """End the user's session and remove from cache."""
    if user_id in SESSION_CACHE:
        log(f"Session ended for user {user_id}.")
        del SESSION_CACHE[user_id]

def cleanup_inactive_sessions():
    """Optionally call this periodically to remove expired sessions."""
    current_time = time.time()
    expired_users = [user_id for user_id, session in SESSION_CACHE.items()
                     if current_time - session['last_active'] >= SESSION_TIMEOUT]
    for user_id in expired_users:
        end_session(user_id)
