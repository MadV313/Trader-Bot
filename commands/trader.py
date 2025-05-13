import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from utils import session_manager, variant_utils

config = json.loads(os.environ.get("CONFIG_JSON"))
TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

PRICE_FILE = os.path.join("data", "Final price list.json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

def get_categories():
    return list(PRICE_DATA.keys())

def get_subcategories(category):
    sub_data = PRICE_DATA.get(category, {})
    if any(isinstance(v, dict) for v in sub_data.values()):
        return list(sub_data.keys())
    return []

def get_items_in_subcategory(category, subcategory):
    if subcategory:
        sub_data = PRICE_DATA.get(category, {}).get(subcategory, {})
    else:
        sub_data = PRICE_DATA.get(category, {})
    if isinstance(sub_data, dict):
        return list(sub_data.keys())
    return []

def get_variants(category, subcategory, item):
    try:
        entry = PRICE_DATA[category]
        if subcategory:
            entry = entry[subcategory]
        entry = entry[item]
        if isinstance(entry, dict):
            return list(entry.keys())
        return ["Default"]
    except (KeyError, TypeError):
        return ["Default"]

def get_price(category, subcategory, item, variant):
    try:
        entry = PRICE_DATA[category]
        if subcategory:
            entry = entry[subcategory]
        entry = entry.get(item, entry)
        if isinstance(entry, dict):
            return entry.get(variant, entry.get("Default"))
        return entry
    except (KeyError, TypeError):
        return None

class QuantityModal(discord.ui.Modal, title="Enter Quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=4)

    def __init__(self, bot, user_id, category, subcategory, item, variant):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant

    async def on_submit(self, interaction: discord.Interaction):
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Session expired. Start a new order.", ephemeral=True, delete_after=10)

        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than 0.")

            price = get_price(self.category, self.subcategory, self.item, self.variant) or 0
            subtotal = price * quantity

            session_manager.add_item(self.user_id, {
                "category": self.category,
                "subcategory": self.subcategory,
                "item": self.item,
                "variant": self.variant,
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal
            })

            await interaction.response.send_message(f"Added {self.item} ({self.variant}) x{quantity} to your order.", ephemeral=True, delete_after=10)
        except ValueError:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True, delete_after=10)

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True, delete_after=10)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Session expired. Start a new order.", ephemeral=True, delete_after=10)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty!", ephemeral=True, delete_after=10)

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} wants to purchase:\n"
        for item in items:
            item_name = item.get('item', 'Unknown')
            variant_name = item.get('variant', 'Default')
            summary += f"- {item_name} ({variant_name}) x{item['quantity']} = ${item['subtotal']:,}\n"
        summary += f"**Total: ${total:,}**"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}\n\nPlease confirm this message with a ✅ when the order is ready.")
        await msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been submitted!", ephemeral=True, delete_after=10)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True, delete_after=10)
        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been canceled.", ephemeral=True, delete_after=10)

class QuantityModal(discord.ui.Modal, title="Enter Quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=4)

    def __init__(self, bot, user_id, category, subcategory, item, variant):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant

    async def on_submit(self, interaction: discord.Interaction):
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Session expired. Start a new order.", ephemeral=True, delete_after=10)

        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than 0.")

            price = get_price(self.category, self.subcategory, self.item, self.variant) or 0
            subtotal = price * quantity

            session_manager.add_item(self.user_id, {
                "category": self.category,
                "subcategory": self.subcategory,
                "item": self.item,
                "variant": self.variant,
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal
            })

            await interaction.response.send_message(f"Added {self.item} ({self.variant}) x{quantity} to your order.", ephemeral=True, delete_after=10)
        except ValueError:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True, delete_after=10)

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True, delete_after=10)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Session expired. Start a new order.", ephemeral=True, delete_after=10)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty!", ephemeral=True, delete_after=10)

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} wants to purchase:\n"
        for item in items:
            item_name = item.get('item', 'Unknown')
            variant_name = item.get('variant', 'Default')
            summary += f"- {item_name} ({variant_name}) x{item['quantity']} = ${item['subtotal']:,}\n"
        summary += f"**Total: ${total:,}**"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}\n\nPlease confirm this message with a ✅ when the order is ready.")
        await msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been submitted!", ephemeral=True, delete_after=10)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True, delete_after=10)
        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been canceled.", ephemeral=True, delete_after=10)
