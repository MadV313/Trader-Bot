import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from utils.order_utils import parse_order_lines

# Load config from Railway environment
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])
ORDERS_FILE = "data/orders.json"

def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r") as f:
        return json.load(f)

def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

class SellTrader(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="selltrader", description="Sell items to the trader.")
    @app_commands.describe(order="Enter each item on a new line like:\nCategory:Item:Variant xQuantity")
    async def selltrader(self, interaction: discord.Interaction, order: str):
        if interaction.channel.id != ECONOMY_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the #economy channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        parsed, error = parse_order_lines(order)

        if error:
            await interaction.followup.send(f"Error in your sell order:\n```{error}```", ephemeral=True)
            return

        # Calculate sell value (1/3 of price)
        summary_lines = [f"{interaction.user.mention} would like to sell the following items:"]
        total_owed = 0
        for item in parsed["items"]:
            sell_price = round(item["price"] / 3)
            subtotal = sell_price * item["quantity"]
            summary_lines.append(f"- {item['item']} ({item['variant']}) x{item['quantity']} = ${subtotal:,}")
            item["sell_price"] = sell_price
            item["subtotal"] = subtotal
            total_owed += subtotal

        summary_lines.append(f"**Total Owed: ${total_owed:,}**")
        summary = "\n".join(summary_lines)

        # Post to trader-orders
        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}")
        await msg.add_reaction("🔴")

        # Save to orders.json
        user_id = str(interaction.user.id)
        orders = load_orders()
        orders.setdefault(user_id, [])
        orders[user_id].append({
            "type": "sell",
            "order_id": f"msg_{msg.id}",
            "confirmed": False,
            "paid": False,
            "confirmed_by": None,
            "total": total_owed,
            "order_message_id": msg.id,
            "payment_message_id": None
        })
        save_orders(orders)

        await interaction.followup.send("Your sell order has been submitted to the trader!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SellTrader(bot))
