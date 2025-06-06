import json
import os
import time

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))
SESSION_TIMEOUT = config.get("session_timeout_minutes", 15) * 60  # Defaults to 15 minutes

ORDERS_FILE = "data/orders.json"
LOG_DIR = "data/logs"
LOG_FILE = os.path.join(LOG_DIR, "session_activity.log")
SESSION_CACHE = {}

def ensure_log_dir():
    """Ensure that the log directory exists."""
    os.makedirs(LOG_DIR, exist_ok=True)

def log(message):
    """Write a timestamped log entry to the session log file."""
    ensure_log_dir()
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    full_message = f"[SessionManager] [{timestamp}] {message}"
    print(full_message)
    with open(LOG_FILE, "a") as log_file:
        log_file.write(full_message + "\n")

def start_session(user_id):
    """Start a new session for a user."""
    SESSION_CACHE[user_id] = {
        "items": [],
        "last_active": time.time()
    }
    log(f"Session started for user {user_id}.")

def get_session(user_id):
    """Get the full session dictionary for a user, creating one if missing."""
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    return SESSION_CACHE[user_id]

def add_item(user_id, item):
    """Add an item to the user's session."""
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    SESSION_CACHE[user_id]["items"].append(item)
    SESSION_CACHE[user_id]["last_active"] = time.time()
    log(f"Added item to session for user {user_id}: {item}.")

def get_session_items(user_id):
    """Get the list of items in the user's session, clearing expired sessions."""
    session = SESSION_CACHE.get(user_id)
    if not session or not is_session_active(user_id):
        clear_session(user_id)
        return []
    return session["items"]

def set_session_items(user_id, items):
    """Replace the list of items in a user's session."""
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    SESSION_CACHE[user_id]["items"] = items
    SESSION_CACHE[user_id]["last_active"] = time.time()
    log(f"Session items replaced for user {user_id}.")

def update_session(user_id, updates: dict):
    """Update arbitrary keys in the user's session (e.g., start_msg_id, cart_messages)."""
    if user_id not in SESSION_CACHE:
        start_session(user_id)
    SESSION_CACHE[user_id].update(updates)
    SESSION_CACHE[user_id]["last_active"] = time.time()
    log(f"Session for user {user_id} updated with: {updates}")

def clear_session(user_id, force_clear=False):
    """Clear a user's session, with optional force override."""
    if user_id in SESSION_CACHE or force_clear:
        log(f"Session cleared for user {user_id}.")
    SESSION_CACHE.pop(user_id, None)

def end_session(user_id):
    """End the user's session and remove from cache."""
    if user_id in SESSION_CACHE:
        log(f"Session ended for user {user_id}.")
        del SESSION_CACHE[user_id]

def is_session_active(user_id):
    """Check if a session is active and hasn't timed out."""
    session = SESSION_CACHE.get(user_id)
    if not session:
        return False
    if (time.time() - session["last_active"]) >= SESSION_TIMEOUT:
        log(f"Session for user {user_id} timed out.")
        return False
    return True

def remove_item(user_id, item_index):
    """Remove an item from a user's session by its index."""
    if user_id in SESSION_CACHE and 0 <= item_index < len(SESSION_CACHE[user_id]["items"]):
        removed_item = SESSION_CACHE[user_id]["items"].pop(item_index)
        SESSION_CACHE[user_id]["last_active"] = time.time()
        log(f"Removed item from session for user {user_id}: {removed_item}.")

def load_orders():
    """Load existing orders from the orders file."""
    if not os.path.exists(ORDERS_FILE):
        log("Orders file not found. Returning empty orders.")
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)

def save_orders(data):
    """Save current orders to the orders file."""
    ensure_log_dir()
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log("Orders file saved successfully.")

def validate_session(user_id):
    """Ensure the session is active and reset timeout if still valid."""
    current_time = time.time()
    session = SESSION_CACHE.get(user_id)
    if session and (current_time - session["last_active"] < SESSION_TIMEOUT):
        SESSION_CACHE[user_id]["last_active"] = current_time
        return True
    end_session(user_id)
    return False

def cleanup_inactive_sessions():
    """Periodically call this to clean up expired sessions."""
    current_time = time.time()
    expired_users = [user_id for user_id, session in SESSION_CACHE.items()
                     if current_time - session["last_active"] >= SESSION_TIMEOUT]
    for user_id in expired_users:
        end_session(user_id)
