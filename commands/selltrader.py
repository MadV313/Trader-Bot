import discord
from discord.ext import commands
from discord import app_commands
import json
import os
from utils import session_manager
from utils.variant_utils import get_variants, variant_exists  # Corrected import

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

PRICE_FILE = os.path.join("data", "Final price list.json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

def get_categories():
    return list(PRICE_DATA.keys())

def get_items_in_category(category):
    return list(PRICE_DATA.get(category, {}).keys())

def get_price(category, item, variant):
    entry = PRICE_DATA[category][item]
    if isinstance(entry, dict):
        return round(entry.get(variant) / 3, 2) if entry.get(variant) else None
    return round(entry / 3, 2) if variant.lower() == "default" else None

class SellTraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnÃ¢ÂÂt your sell session.", ephemeral=True)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new sell order.", ephemeral=True)

        categories = get_categories()
        options = [discord.SelectOption(label=c, value=c) for c in categories]

        class CategorySelect(discord.ui.Select):
            def __init__(self, bot, user_id):
                super().__init__(placeholder="Choose a category...", options=options)
                self.bot = bot
                self.user_id = user_id

            async def callback(self, select_interaction: discord.Interaction):
                selected_category = self.values[0]
                items = get_items_in_category(selected_category)
                item_options = [discord.SelectOption(label=i, value=i) for i in items]

                class ItemSelect(discord.ui.Select):
                    def __init__(self, bot, user_id):
                        super().__init__(placeholder="Choose an item...", options=item_options)
                        self.bot = bot
                        self.user_id = user_id

                    async def callback(self, item_interaction: discord.Interaction):
                        selected_item = self.values[0]
                        item_entry = PRICE_DATA.get(selected_category, {}).get(selected_item)
                        variants = get_variants(item_entry)
                        variant_options = [discord.SelectOption(label=v, value=v) for v in variants]

                        if variants == ["Default"]:
                            await item_interaction.response.send_modal(
                                SellQuantityModal(self.bot, self.user_id, selected_category, selected_item, "Default")
                            )
                        else:
                            class VariantSelect(discord.ui.Select):
                                def __init__(self, bot, user_id):
                                    super().__init__(placeholder="Choose a variant...", options=variant_options)
                                    self.bot = bot
                                    self.user_id = user_id

                                async def callback(self, variant_interaction: discord.Interaction):
                                    selected_variant = self.values[0]
                                    await variant_interaction.response.send_modal(
                                        SellQuantityModal(
                                            self.bot,
                                            self.user_id,
                                            selected_category,
                                            selected_item,
                                            selected_variant
                                        )
                                    )

                            variant_view = discord.ui.View()
                            variant_view.add_item(VariantSelect(self.bot, self.user_id))
                            await item_interaction.response.send_message(
                                "Select a variant:", view=variant_view, ephemeral=True
                            )

                item_view = discord.ui.View()
                item_view.add_item(ItemSelect(self.bot, self.user_id))
                await select_interaction.response.send_message(
                    "Select an item:", view=item_view, ephemeral=True
                )

        category_view = discord.ui.View()
        category_view.add_item(CategorySelect(self.bot, self.user_id))
        await interaction.response.send_message(
            "Select a category:", view=category_view, ephemeral=True
        )

    @discord.ui.button(label="Submit Sell Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnÃ¢ÂÂt your sell session.", ephemeral=True)
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new sell order.", ephemeral=True)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your sell cart is empty!", ephemeral=True)

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} would like to sell the following items:\n"
        for item in items:
            summary += f"- {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}\n"
        summary += f"**Total Owed: ${total:,}**"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}")
        await msg.add_reaction("Ã°ÂÂÂ´")

        await trader_channel.send(f"give user:{interaction.user.id} amount:{total} account:cash")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your sell order has been submitted!", ephemeral=True)

    @discord.ui.button(label="Cancel Sell Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isnÃ¢ÂÂt your sell session.", ephemeral=True)
        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your sell order has been canceled.", ephemeral=True)


class SellQuantityModal(discord.ui.Modal, title="Enter Quantity to Sell"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=4)

    def __init__(self, bot, user_id, category, item, variant):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.item = item
        self.variant = variant

    async def on_submit(self, interaction: discord.Interaction):
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            return await interaction.response.send_message("Your session expired. Start a new sell order.", ephemeral=True)

        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError("Quantity must be greater than 0.")

            item_entry = PRICE_DATA.get(self.category, {}).get(self.item)
            variants = get_variants(item_entry)
            matched_variant = next(
                (v for v in variants if v.lower() == self.variant.lower()), self.variant
            )
            base_price = get_price(self.category, self.item, matched_variant)
            if base_price is None:
                raise ValueError("Invalid item or variant selected.")

            sell_price = round(base_price / 3)
            subtotal = sell_price * quantity
            self.variant = matched_variant

            session_manager.add_item(self.user_id, {
                "category": self.category,
                "item": self.item,
                "variant": self.variant,
                "quantity": quantity,
                "price": sell_price,
                "subtotal": subtotal
            })

            await interaction.response.send_message(
                f"Added {self.item} ({self.variant}) x{quantity} to your sell order.", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True)


class SellTraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="selltrader", description="Start a sell session with the trader.")
    async def selltrader(self, interaction: discord.Interaction):
        if interaction.channel.id != ECONOMY_CHANNEL_ID:
            return await interaction.response.send_message(
                "This command can only be used in the #economy channel.", ephemeral=True
            )

        session_manager.start_session(interaction.user.id)
        await interaction.response.send_message(
            "Sell session started! Use the buttons below to add items, submit, or cancel your order.",
            view=SellTraderView(self.bot, interaction.user.id),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(SellTraderCommand(bot))
