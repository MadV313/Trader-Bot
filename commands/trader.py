
import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from utils import session_manager
from utils.variant_utils import get_variants, variant_exists

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

PRICE_FILE = os.path.join("data", "Final price list .json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]


def get_categories():
    return list(PRICE_DATA.keys())


def get_items_in_category(category):
    return list(PRICE_DATA.get(category, {}).keys())


def get_price(category, item, variant):
    entry = PRICE_DATA[category][item]
    if isinstance(entry, dict):
        return entry.get(variant)
    return entry if variant.lower() == "default" else None


class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Add Item to Cart", style=discord.ButtonStyle.success)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnât your buy session.", ephemeral=True)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new buy order.", ephemeral=True)

        categories = get_categories()
        options = [discord.SelectOption(label=c, value=c) for c in categories]

        class CategorySelect(discord.ui.Select):
            def __init__(self):
                super().__init__(placeholder="Choose a category...", options=options)

            async def callback(self, select_interaction: discord.Interaction):
                selected_category = self.values[0]
                items = get_items_in_category(selected_category)
                item_options = [discord.SelectOption(label=i, value=i) for i in items]

                class ItemSelect(discord.ui.Select):
                    def __init__(self):
                        super().__init__(placeholder="Choose an item...", options=item_options)

                    async def callback(self, item_interaction: discord.Interaction):
                        selected_item = self.values[0]
                        item_entry = PRICE_DATA.get(selected_category, {}).get(selected_item)
                        variants = get_variants(item_entry)
                        variant_options = [discord.SelectOption(label=v, value=v) for v in variants]

                        class VariantSelect(discord.ui.Select):
                            def __init__(self):
                                super().__init__(placeholder="Choose a variant...", options=variant_options)

                            async def callback(self, variant_interaction: discord.Interaction):
                                selected_variant = self.values[0]
                                price = get_price(selected_category, selected_item, selected_variant)

                                if price is None:
                                    return await variant_interaction.response.send_message("Invalid variant selected.", ephemeral=True)

                                session_manager.add_item(
                                    self.user_id, selected_category, selected_item, selected_variant, price
                                )
                                await variant_interaction.response.send_message(
                                    f"Added **{selected_item}** (*{selected_variant}*) to your cart for **{price} coins**.", ephemeral=True
                                )

                        await item_interaction.response.send_message(
                            "Select a variant:", 
                            view=discord.ui.View().add_item(VariantSelect()), ephemeral=True
                        )

                await select_interaction.response.send_message(
                    "Select an item:", 
                    view=discord.ui.View().add_item(ItemSelect()), ephemeral=True
                )

        await interaction.response.send_message(
            "Select a category:", 
            view=discord.ui.View().add_item(CategorySelect()), ephemeral=True
        )

    @discord.ui.button(label="View Cart", style=discord.ButtonStyle.secondary)
    async def view_cart(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnât your buy session.", ephemeral=True)

        cart = session_manager.get_cart(self.user_id)
        if not cart:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        cart_details = "\n".join(
            [f"{item['quantity']}x {item['item']} ({item['variant']}) - {item['price']} coins each" for item in cart]
        )
        total_cost = sum(item['quantity'] * item['price'] for item in cart)

        await interaction.response.send_message(
            f"**Your Cart:**\n{cart_details}\n\n**Total: {total_cost} coins**", ephemeral=True
        )

    @discord.ui.button(label="Confirm Purchase", style=discord.ButtonStyle.success)
    async def confirm_purchase(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnât your buy session.", ephemeral=True)

        cart = session_manager.get_cart(self.user_id)
        if not cart:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        total_cost = sum(item['quantity'] * item['price'] for item in cart)

        # Here you can add economy balance checking and deduct coins
        # Example: if not economy.has_funds(user_id, total_cost): return not enough funds message

        # Post order to trader orders channel
        trader_orders_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        cart_summary = "\n".join(
            [f"{item['quantity']}x {item['item']} ({item['variant']}) - {item['price']} coins each" for item in cart]
        )

        await trader_orders_channel.send(
            f"**New Purchase Order from <@{self.user_id}>:**\n{cart_summary}\n\n**Total: {total_cost} coins**"
        )

        session_manager.clear_session(self.user_id)

        await interaction.response.send_message("Purchase confirmed and order submitted!", ephemeral=True)
