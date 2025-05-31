# explosives_scanner.py

import json
import os
import asyncio
from discord.ext import tasks
from utils.storageClient import load_file, save_file

# Constants
ORDER_FILE = "sv-persistent-data/data/trader_orders.json"
TRACKER_FILE = "sv-persistent-data/data/explosive_alert_tracker.json"
ALERT_CHANNEL_ID = 1172556655150506075

EXPLOSIVE_KEYWORDS = [
    "40mm Explosive Grenade",
    "M79",
    "Plastic Explosives",
    "Landmines",
    "Claymores"
]

# Helper to safely load the tracker
def load_tracker():
    if not os.path.exists(TRACKER_FILE):
        return []
    with open(TRACKER_FILE, "r") as f:
        return json.load(f)

def save_tracker(tracker):
    with open(TRACKER_FILE, "w") as f:
        json.dump(tracker, f, indent=2)

def extract_explosive_count(items):
    total = 0
    for entry in items:
        name = entry.get("item", "").lower()
        quantity = int(entry.get("quantity", 0))
        if any(keyword.lower() in name for keyword in EXPLOSIVE_KEYWORDS):
            total += quantity
    return total

def get_player_mention(user_id):
    return f"<@{user_id}>"

# Task loop setup
def setup_explosive_scanner(bot):
    @tasks.loop(minutes=5)
    async def check_explosive_orders():
        try:
            orders_data = load_file(ORDER_FILE)
            alerted_ids = load_tracker()

            alert_channel = bot.get_channel(ALERT_CHANNEL_ID)
            if not alert_channel:
                print("[Explosive Scanner] ❌ Alert channel not found.")
                return

            for user_id, orders in orders_data.items():
                for order in orders:
                    order_id = order.get("order_id")
                    if not order_id or order_id in alerted_ids:
                        continue

                    if not order.get("confirmed") or not order.get("paid"):
                        continue

                    explosive_total = extract_explosive_count(order.get("items", []))
                    if explosive_total >= 3:
                        mention = get_player_mention(user_id)
                        await alert_channel.send(
                            f"@everyone stay frosty! {mention} has just bought enough boom to waltz through your front door! 💥"
                        )
                        alerted_ids.append(order_id)

            save_tracker(alerted_ids)
        except Exception as e:
            print(f"[Explosive Scanner] ❌ Error: {e}")

    check_explosive_orders.start()
