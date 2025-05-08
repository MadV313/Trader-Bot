import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# Load config
with open("config.json") as f:
    config = json.load(f)

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
ADMIN_ROLE_IDS = config["admin_role_ids"]

# Track confirmed orders (basic version)
ORDERS_FILE = os.path.join("data", "orders.json")

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
            await interaction.response.send_message("You can only use this command in the #economy channel.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        orders = load_orders()
        if user_id not in orders or not orders[user_id]["confirmed"] or orders[user_id]["paid"]:
            await interaction.response.send_message("No confirmed unpaid order found for you.", ephemeral=True)
            return

        admin_id = orders[user_id]["confirmed_by"]
        total = orders[user_id]["total"]
        player_mention = interaction.user.mention

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        admin_mention = f"<@{admin_id}>"

        msg = await trader_channel.send(
            f"{admin_mention} payment has been sent from {player_mention} for their trader order."
        )
        await msg.add_reaction("🔴")

        orders[user_id]["paid"] = True
        orders[user_id]["payment_message_id"] = msg.id
        save_orders(orders)

        await interaction.response.send_message("Payment sent and awaiting admin confirmation.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(PayTrader(bot))
