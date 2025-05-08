import discord
from discord.ext import commands
from discord import app_commands
import json
import os

from utils.order_utils import parse_order_lines

# Load config
with open("config.json") as f:
    config = json.load(f)

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="trader", description="Submit an order to the trader.")
    @app_commands.describe(order="Enter each item on a new line in this format:\nCategory:Item:Variant xQuantity")
    async def trader(self, interaction: discord.Interaction, order: str):
        # Channel restriction
        if interaction.channel.id != config["economy_channel_id"]:
            await interaction.response.send_message("This command can only be used in the #economy channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        parsed, error = parse_order_lines(order)

        if error:
            await interaction.followup.send(f"Error in your order:\n```{error}```", ephemeral=True)
            return

        # Format summary
        summary_lines = [f"Order for {interaction.user.mention}:"]
        for item in parsed["items"]:
            line = f"- {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}"
            summary_lines.append(line)
        summary_lines.append(f"**Total: ${parsed['total']:,}**")
        summary_text = "\n".join(summary_lines)

        # Send to #trader-orders
        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        if not trader_channel:
            await interaction.followup.send("Failed to find the trader orders channel.", ephemeral=True)
            return

        message = await trader_channel.send(f"{summary_text}\n\n{MENTION_ROLES} — an order is ready for trader!")
        await message.add_reaction("🔴")

        # Confirm to user
        await interaction.followup.send("Your order has been submitted to the trader!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
