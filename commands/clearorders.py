import discord
from discord.ext import commands
import json
import os

# Load config from Railway environment
config = json.loads(os.environ.get("CONFIG_JSON"))

ORDERS_FILE = "data/orders.json"
ADMIN_ROLE_IDS = [str(role_id) for role_id in config["admin_role_ids"]]

class ClearOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clearorders")
    async def clearorders(self, ctx):
        # Permission Check
        if not any(str(role.id) in ADMIN_ROLE_IDS for role in ctx.author.roles):
            await ctx.send("❌ You don’t have permission to use this command.")
            return

        if not os.path.exists(ORDERS_FILE):
            await ctx.send("📦 No pending orders to clear.")
            return

        with open(ORDERS_FILE, "w") as f:
            json.dump({}, f)

        await ctx.send("✅ All pending trader orders have been cleared.")

async def setup(bot):
    await bot.add_cog(ClearOrders(bot))
