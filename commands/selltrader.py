import discord
from discord.ext import commands
import json
import os
from utils import session_manager

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
MENTION_ROLES = " ".join(config["mention_roles"])

# Load price data
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

class SellTraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=300)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn’t your sell session.", ephemeral=True)
            return
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            await interaction.response.send_message("Your session has expired. Please start a new sell order.", ephemeral=True)
            return

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
                        variants = get_variants(selected_category, selected_item)
                        variant_options = [discord.SelectOption(label=v, value=v) for v in variants]

                        class VariantSelect(discord.ui.Select):
                            def __init__(self):
                                super().__init__(placeholder="Choose a variant...", options=variant_options)

                            async def callback(self, variant_interaction: discord.Interaction):
                                selected_variant = self.values[0]
                                await variant_interaction.response.send_modal(SellQuantityModal(
                                    self.bot, self.user_id, selected_category, selected_item, selected_variant
                                ))

                        variant_view = discord.ui.View()
                        variant_view.add_item(VariantSelect())
                        await item_interaction.response.send_message("Select a variant:", view=variant_view, ephemeral=True)

                item_view = discord.ui.View()
                item_view.add_item(ItemSelect())
                await select_interaction.response.send_message("Select an item:", view=item_view, ephemeral=True)

        category_view = discord.ui.View()
        category_view.add_item(CategorySelect())
        await interaction.response.send_message("Select a category:", view=category_view, ephemeral=True)

    @discord.ui.button(label="Submit Sell Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn’t your sell session.", ephemeral=True)
            return
        if not session_manager.is_session_active(self.user_id):
            session_manager.clear_session(self.user_id)
            await interaction.response.send_message("Your session has expired. Please start a new sell order.", ephemeral=True)
            return

        items = session_manager.get_session_items(self.user_id)
        if not items:
            await interaction.response.send_message("Your sell cart is empty!", ephemeral=True)
            return

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} would like to sell the following items:\n"
        for item in items:
            summary += f"- {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}\n"
        summary += f"**Total Owed: ${total:,}**"

        trader_channel = self.bot.get_channel(TRADER_ORDERS_CHANNEL_ID)
        msg = await trader_channel.send(f"{summary}\n\n{MENTION_ROLES}")
        await msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your sell order has been submitted!", ephemeral=True)

    @discord.ui.button(label="Cancel Sell Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This isn’t your sell session.", ephemeral=True)
            return

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Your sell order has been canceled.", ephemeral=True)

class SellQuantityModal(discord.ui.Modal, title="Enter Quantity to Sell"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=3)

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
            await interaction.response.send_message("Your session has expired. Please start a new sell order.", ephemeral=True)
            return

        try:
            quantity = int(self.quantity.value)
            base_price = get_price(self.category, self.item, self.variant)
            sell_price = round(base_price / 3)
            subtotal = sell_price * quantity

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

    @commands.command(name="selltrader")
    async def start_sell_session(self, ctx):
        if ctx.channel.id != ECONOMY_CHANNEL_ID:
            await ctx.send("This command can only be used in the #economy channel.", ephemeral=True)
            return

        session_manager.start_session(ctx.author.id)
        await ctx.send(
            "Sell session started! Use the buttons below to add items, submit, or cancel your order.",
            view=SellTraderView(self.bot, ctx.author.id)
        )

async def setup(bot):
    await bot.add_cog(SellTraderCommand(bot))
