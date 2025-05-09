import discord
from discord.ext import commands
from discord import app_commands
import json
import os

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

# Load item data
PRICE_FILE = os.path.join("data", "Final price list .json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

def get_categories():
    return list(PRICE_DATA.keys())

def get_items_in_category(category):
    return list(PRICE_DATA.get(category, {}).keys())

def get_variants(category, item):
    entry = PRICE_DATA.get(category, {}).get(item)
    if isinstance(entry, dict):
        return list(entry.keys())
    return ["Default"]

def get_price(category, item, variant):
    entry = PRICE_DATA[category][item]
    if isinstance(entry, dict):
        return entry.get(variant)
    return entry if variant.lower() == "default" else None

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="trader", description="Submit a single item order to the trader.")
    @app_commands.choices(
        category=[app_commands.Choice(name=c, value=c) for c in get_categories()]
    )
    async def trader(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        item: str,
        variant: str,
        quantity: int,
    ):
        if interaction.channel.id != ECONOMY_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the #economy channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Validation
        selected_category = category.value
        if item not in get_items_in_category(selected_category):
            await interaction.followup.send(f"Item `{item}` is not valid for category `{selected_category}`.", ephemeral=True)
            return

        if variant not in get_variants(selected_category, item):
            await interaction.followup.send(f"Variant `{variant}` is not valid for item `{item}`.", ephemeral=True)
            return

        price = get_price(selected_category, item, variant)
        if price is None:
            await interaction.followup.send("Invalid item/variant combo.", ephemeral=True)
            return

        subtotal = price * quantity

        summary = (
            f"Order for {interaction.user.mention}:\n"
            f"- {item} ({variant}) x{quantity} = ${subtotal:,}\n"
            f"**Total: ${subtotal:,}**"
        )

        # Send to trader orders channel
        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        if not trader_channel:
            await interaction.followup.send("Trader channel not found.", ephemeral=True)
            return

        message = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES} — an order is ready for trader!")
        await message.add_reaction("🔴")

        await interaction.followup.send("Your order has been submitted to the trader!", ephemeral=True)

    # Autocomplete: Item
    @trader.autocomplete("item")
    async def item_autocomplete(self, interaction: discord.Interaction, current: str):
        category = interaction.namespace.category.value
        suggestions = get_items_in_category(category)
        matches = [i for i in suggestions if current.lower() in i.lower()]
        return [app_commands.Choice(name=i, value=i) for i in matches[:20]]

    # Autocomplete: Variant
    @trader.autocomplete("variant")
    async def variant_autocomplete(self, interaction: discord.Interaction, current: str):
        category = interaction.namespace.category.value
        item = interaction.namespace.item
        variants = get_variants(category, item)
        matches = [v for v in variants if current.lower() in v.lower()]
        return [app_commands.Choice(name=v, value=v) for v in matches[:20]]

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
