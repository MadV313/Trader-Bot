import discord
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
import json
import os

# Load config from Railway environment variable
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])
ORDER_REMINDER_HOURS = config.get("order_reminder_hours", 12)  # Fallback to 12 hours if not set
REMINDER_LOG_FILE = "logs/reminder_events.log"


def log_reminder_event(message):
    os.makedirs("logs", exist_ok=True)
    with open(REMINDER_LOG_FILE, "a") as log_file:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"[{timestamp}] {message}\n")


def start_reminder_task(bot):
    @tasks.loop(hours=1)
    async def scan_for_incomplete_orders():
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [TraderBot] Scanning for unconfirmed orders...")

        channel = bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        if not channel:
            print("[TraderBot] Trader orders channel not found.")
            log_reminder_event("Trader orders channel not found during reminder scan.")
            return

        try:
            async for message in channel.history(limit=100):
                if any(reaction.emoji == "🔴" and reaction.me for reaction in message.reactions):
                    message_age = datetime.now(timezone.utc) - message.created_at
                    if message_age > timedelta(hours=ORDER_REMINDER_HOURS):
                        await channel.send(
                            f"{MENTION_ROLES}\nPlease check for any incomplete trader orders!"
                        )
                        log_reminder_event("Reminder sent for incomplete trader orders.")
                        break  # Send only one reminder per scan
        except Exception as e:
            error_message = f"Reminder scan failed: {e}"
            print(f"[TraderBot] {error_message}")
            log_reminder_event(error_message)

    if not scan_for_incomplete_orders.is_running():
        scan_for_incomplete_orders.start()
