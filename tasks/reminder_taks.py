import discord
from discord.ext import tasks
from datetime import datetime, timezone, timedelta
import json

with open("config.json") as f:
    config = json.load(f)

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

def start_reminder_task(bot):
    @tasks.loop(hours=1)
    async def scan_for_incomplete_orders():
        print("[TraderBot] Scanning for unconfirmed orders...")

        channel = bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        if not channel:
            print("[TraderBot] Trader orders channel not found.")
            return

        try:
            async for message in channel.history(limit=100):
                if any(reaction.emoji == "🔴" and reaction.me for reaction in message.reactions):
                    message_age = datetime.now(timezone.utc) - message.created_at
                    if message_age > timedelta(hours=12):
                        await channel.send(
                            f"{MENTION_ROLES}\nPlease check for any incomplete trader orders!"
                        )
                        break  # only send 1 reminder per scan
        except Exception as e:
            print(f"[TraderBot] Reminder scan failed: {e}")

    scan_for_incomplete_orders.start()
