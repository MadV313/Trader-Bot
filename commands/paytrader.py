import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from datetime import datetime

# Load config from Railway environment
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
ORDERS_FILE = os.path.join("data", "orders.json")
LOG_FILE = "logs/payment_submissions.log"


def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)


def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


class PayTrader(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="paytrader", description="Confirm that you paid the trader.")
    async def paytrader(self, interaction: discord.Interaction):
        if interaction.channel.id != ECONOMY_CHANNEL_ID:
            return await interaction.response.send_message(
                "❌ You can only use this command in the #economy channel.", ephemeral=True
            )

        user_id = str(interaction.user.id)
        orders = load_orders()
        user_orders = orders.get(user_id, [])

        latest_unpaid = next((o for o in reversed(user_orders) if o["confirmed"] and not o["paid"]), None)

        if not latest_unpaid:
            return await interaction.response.send_message(
                "❌ No confirmed unpaid order found for you.", ephemeral=True
            )

        admin_id = latest_unpaid["confirmed_by"]
        total = latest_unpaid["total"]
        player_mention = interaction.user.mention
        admin_mention = f"<@{admin_id}>"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        if not trader_channel:
            return await interaction.response.send_message(
                "❌ Failed to locate the trader orders channel.", ephemeral=True
            )

        msg = await trader_channel.send(
            f"{admin_mention}, payment has been sent from {player_mention} for their trader order totaling ${total:,}."
        )
        await msg.add_reaction("🔴")

        # Update order status
        latest_unpaid["paid"] = True
        latest_unpaid["payment_message_id"] = msg.id
        save_orders(orders)

        # Log payment submission
        os.makedirs("logs", exist_ok=True)
        with open(LOG_FILE, "a") as log_file:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_file.write(f"[{timestamp}] Payment submitted by {user_id} for ${total}\n")

        # Confirm to the user
        await interaction.response.send_message("✅ Payment submitted! Awaiting admin confirmation.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(PayTrader(bot))
