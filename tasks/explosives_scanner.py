# tasks/explosives_scanner.py

import discord
import json
import asyncio
from discord.ext import tasks
from utils.clientStorage import load_file
import os

EXPLOSIVE_ALERT_CHANNEL_ID = 1172556655150506075
EXPLOSIVE_KEYWORDS = ["40mm Explosive Grenade", "M79", "Plastic Explosives", "Landmines", "Claymores"]
TRADER_ORDER_FILE = "sv-persistent-data/data/trader_orders.json"

class ExplosiveScanner:
    def __init__(self, bot):
        self.bot = bot
        self.already_alerted = set()  # track message_ids already alerted
        self.task = self.scan_explosives.start()

    def cog_unload(self):
        self.task.cancel()

    @tasks.loop(minutes=5)
    async def scan_explosives(self):
        if not os.path.exists(TRADER_ORDER_FILE):
            return

        try:
            data = load_file(TRADER_ORDER_FILE)
        except Exception as e:
            print(f"[ExplosiveScanner] Error loading trader_orders.json: {e}")
            return

        channel = self.bot.get_channel(EXPLOSIVE_ALERT_CHANNEL_ID)
        if not channel:
            print(f"[ExplosiveScanner] Alert channel {EXPLOSIVE_ALERT_CHANNEL_ID} not found.")
            return

        for user_id, orders in data.items():
            for order in orders:
                if order.get("order_id") in self.already_alerted:
                    continue
                if not order.get("confirmed") or not order.get("paid"):
                    continue

                count = 0
                for item in order.get("items", []):
                    name = item.get("item", "").lower()
                    qty = int(item.get("quantity", 1))
                    if any(keyword.lower() in name for keyword in EXPLOSIVE_KEYWORDS):
                        count += qty

                if count >= 3:
                    user = await self.bot.fetch_user(int(user_id))
                    await channel.send(f"@everyone stay frosty! {user.mention} has just bought enough boom to waltz through your front door! 💥")
                    self.already_alerted.add(order.get("order_id"))

    @scan_explosives.before_loop
    async def before_scan(self):
        await self.bot.wait_until_ready()
