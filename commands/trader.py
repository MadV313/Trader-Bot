
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
    return list(PRICE_DATA.get(category, {}).keys())

def get_items_in_subcategory(category, subcategory):
    sub_data = PRICE_DATA.get(category, {}).get(subcategory, {})
    if isinstance(sub_data, dict):
        return list(sub_data.keys())
    return []

def get_variants(category, subcategory, item):
    item_entry = PRICE_DATA.get(category, {}).get(subcategory, {}).get(item)
    if isinstance(item_entry, dict):
        return list(item_entry.keys())
    return ["Default"]

def get_price(category, subcategory, item, variant):
    entry = PRICE_DATA[category][subcategory][item]
    if isinstance(entry, dict):
        return entry.get(variant)
    return entry if variant.lower() == "default" else None

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new order.", ephemeral=True)

        categories = get_categories()
        options = [discord.SelectOption(label=c, value=c) for c in categories[:25]]

        class CategorySelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Choose a category...", options=options)

            async def callback(self, select_interaction: discord.Interaction):
                selected_category = self.values[0]
                subcategories = get_subcategories(selected_category)
                if not subcategories:
                    return await select_interaction.response.send_message(
                        "No subcategories found for this category.", ephemeral=True
                    )
                sub_options = [discord.SelectOption(label=s, value=s) for s in subcategories[:25]]

                class SubcategorySelect(discord.ui.Select):
                    def __init__(self):
                        super().__init__(placeholder="Choose a subcategory...", options=sub_options)

                    async def callback(self, sub_select_interaction: discord.Interaction):
                        selected_subcategory = self.values[0]
                        items = get_items_in_subcategory(selected_category, selected_subcategory)
                        if not items:
                            return await sub_select_interaction.response.send_message(
                                "No items found for this subcategory.", ephemeral=True
                            )
                        item_options = [discord.SelectOption(label=i, value=i) for i in items[:25]]

                        class ItemSelect(discord.ui.Select):
                            def __init__(self):
                                super().__init__(placeholder="Choose an item...", options=item_options)

                            async def callback(self, item_interaction: discord.Interaction):
                                selected_item = self.values[0]
                                variants = get_variants(selected_category, selected_subcategory, selected_item)
                                variant_options = [discord.SelectOption(label=v, value=v) for v in variants[:25]]

                                if variants == ["Default"]:
                                    await item_interaction.response.send_modal(
                                        QuantityModal(self.bot, self.user_id, selected_category, selected_subcategory, selected_item, "Default")
                                    )
                                    return

                                class VariantSelect(discord.ui.Select):
                                    def __init__(self, bot, user_id):
                                        super().__init__(placeholder="Choose a variant...", options=variant_options)
                                        self.bot = bot
                                        self.user_id = user_id

                                    async def callback(self, variant_interaction: discord.Interaction):
                                        selected_variant = self.values[0]
                                        await variant_interaction.response.send_modal(
                                            QuantityModal(self.bot, self.user_id, selected_category, selected_subcategory, selected_item, selected_variant)
                                        )

                                variant_view = discord.ui.View()
                                variant_view.add_item(VariantSelect(self.bot, self.user_id))
                                await item_interaction.response.send_message(
                                    "Select a variant:", view=variant_view, ephemeral=True
                                )

                        item_view = discord.ui.View()
                        item_view.add_item(ItemSelect())
                        await sub_select_interaction.response.send_message(
                            "Select an item:", view=item_view, ephemeral=True
                        )

                subcategory_view = discord.ui.View()
                subcategory_view.add_item(SubcategorySelect())
                await select_interaction.response.send_message(
                    "Select a subcategory:", view=subcategory_view, ephemeral=True
                )

        category_view = discord.ui.View()
        category_view.add_item(CategorySelect())
        await interaction.response.send_message(
            "Select a category:", view=category_view, ephemeral=True
        )

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new order.", ephemeral=True)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty!", ephemeral=True)

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} wants to purchase:\n"
        for item in items:
            summary += f"- {item['item']} ({item['variant']}) x{item['quantity']} = ${{item['subtotal']:,}}\n"
        summary += f"**Total: ${{total:,}}**"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}")
        await msg.add_reaction("â")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been submitted!", ephemeral=True)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn't your session.", ephemeral=True)
        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your order has been canceled.", ephemeral=True)

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
            return await interaction.response.send_message("Your session expired. Start a new order.", ephemeral=True)

        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than 0.")

            price = get_price(self.category, self.subcategory, self.item, self.variant)
            if price is None or not isinstance(price, (int, float)):
                raise ValueError("Invalid item or variant selected.")

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

            await interaction.response.send_message(
                f"Added {self.item} ({self.variant}) x{quantity} to your order.", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True)

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        if interaction.channel.id != ECONOMY_CHANNEL_ID:
            return await interaction.response.send_message(
                "This command can only be used in the #economy channel.", ephemeral=True
            )

        session_manager.start_session(interaction.user.id)
        await interaction.response.send_message(
            "Buying session started! Use the buttons below to add items, submit, or cancel your order.",
            view=TraderView(self.bot, interaction.user.id),
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
