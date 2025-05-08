import discord
from discord.ext import commands
import json
import os

ORDERS_FILE = "data/orders.json"
ADMIN_ROLE_IDS = [
    "1173052585830264832",  # Founder
    "1173049392371085392",  # Admin
    "1184921037830373468",  # Trial Admin
    "1370152166366642297"   # Trader
]

class ClearOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="clearorders")
    async def clearorders(self, ctx):
        if not any(role.id in ADMIN_ROLE_IDS for role in ctx.author.roles):
            await ctx.send("You don’t have permission to use this.")
            return

        if not os.path.exists(ORDERS_FILE):
            await ctx.send("No orders to clear.")
            return

        with open(ORDERS_FILE, "w") as f:
            json.dump({}, f)

        await ctx.send("All orders cleared.")

async def setup(bot):
    await bot.add_cog(ClearOrders(bot))
