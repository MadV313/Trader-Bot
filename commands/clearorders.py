import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

# Load config from Railway environment
config = json.loads(os.environ.get("CONFIG_JSON"))

ORDERS_FILE = "data/orders.json"
LOG_FILE = "logs/order_clear.log"
ADMIN_ROLE_IDS = config["admin_role_ids"]


class ClearOrders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clearorders", description="Clear all trader orders. Admins only.")
    async def clearorders(self, interaction: discord.Interaction):
        user_roles = [role.id for role in interaction.user.roles]
        if not any(role_id in ADMIN_ROLE_IDS for role_id in user_roles):
            await interaction.response.send_message("You don’t have permission to use this command.", ephemeral=True)
            return

        if not os.path.exists(ORDERS_FILE):
            await interaction.response.send_message("No orders to clear.", ephemeral=True)
            return

        # Clear the orders file
        with open(ORDERS_FILE, "w") as f:
            json.dump({}, f)

        # Log the action
        os.makedirs("logs", exist_ok=True)
        with open(LOG_FILE, "a") as log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{timestamp}] Orders cleared by Admin: {interaction.user.id}\n")

        # Add reaction confirmation if possible
        try:
            await interaction.response.send_message("All orders have been cleared.", ephemeral=True)
            if interaction.message:
                await interaction.message.add_reaction("✅")
        except Exception:
            # If reaction fails (e.g., ephemeral interaction), ignore
            pass


async def setup(bot):
    await bot.add_cog(ClearOrders(bot))
