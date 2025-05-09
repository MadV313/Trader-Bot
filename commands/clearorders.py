import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# Load config from Railway environment
config = json.loads(os.environ.get("CONFIG_JSON"))

ORDERS_FILE = "data/orders.json"
ADMIN_ROLE_IDS = config["admin_role_ids"]

class ClearOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clearorders", description="Clear all trader orders. Admins only.")
    async def clearorders(self, interaction: discord.Interaction):
        # Check if user has admin roles
        user_roles = [role.id for role in interaction.user.roles]
        if not any(role_id in ADMIN_ROLE_IDS for role_id in user_roles):
            await interaction.response.send_message("You don’t have permission to use this command.", ephemeral=True)
            return

        if not os.path.exists(ORDERS_FILE):
            await interaction.response.send_message("No orders to clear.", ephemeral=True)
            return

        with open(ORDERS_FILE, "w") as f:
            json.dump({}, f)

        await interaction.response.send_message("All orders have been cleared.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(ClearOrders(bot))
