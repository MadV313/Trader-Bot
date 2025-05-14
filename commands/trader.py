import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
from utils import session_manager, variant_utils

config = json.loads(os.environ.get("CONFIG_JSON"))

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
            variants = [k for k, v in entry.items() if isinstance(v, (int, float))]
            return variants if len(variants) > 1 else []
        return []
    except (KeyError, TypeError):
        return []

def get_price(category, subcategory, item, variant):
    try:
        entry = PRICE_DATA[category]
        if subcategory:
            entry = entry[subcategory]
        entry = entry.get(item, {})
        if isinstance(entry, dict):
            return entry.get(variant)
        return None
    except (KeyError, TypeError):
        return None

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.cart_message = None

    async def update_cart_message(self, interaction):
        items = session_manager.get_session_items(self.user_id)
        if not items:
            text = "Your cart is currently empty."
        else:
            total = sum(item['subtotal'] for item in items)
            lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
            summary = "\n".join(lines)
            summary += f"\n\nTotal: ${total:,}"
            text = summary

        if self.cart_message:
            await self.cart_message.edit(content=text)
        else:
            self.cart_message = await interaction.followup.send(content=text)

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def handle_add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!")

        class DynamicDropdown(discord.ui.Select):
            def __init__(self, bot, user_id, stage, selected=None, view_ref=None):
                self.bot = bot
                self.user_id = user_id
                self.stage = stage
                self.selected = selected or {}
                self.view_ref = view_ref
                placeholder = "Select a category" if stage == "category" else \
                              "Select a subcategory" if stage == "subcategory" else \
                              "Select an item" if stage == "item" else "Select a variant"
                options = self.get_options()
                super().__init__(placeholder=placeholder, options=options)

            def get_options(self):
                if self.stage == "category":
                    return [discord.SelectOption(label=c, value=c) for c in get_categories()[:25]]
                elif self.stage == "subcategory":
                    category = self.selected.get("category")
                    return [discord.SelectOption(label=s, value=s) for s in get_subcategories(category)[:25]]
                elif self.stage == "item":
                    category = self.selected.get("category")
                    subcategory = self.selected.get("subcategory")
                    return [discord.SelectOption(label=i, value=i) for i in get_items_in_subcategory(category, subcategory)[:25]]
                elif self.stage == "variant":
                    category = self.selected.get("category")
                    subcategory = self.selected.get("subcategory")
                    item = self.selected.get("item")
                    return [discord.SelectOption(label=v, value=v) for v in get_variants(category, subcategory, item)[:25]]

    async def callback(self, interaction: discord.Interaction):
    self.selected[self.stage] = self.values[0]

    category = self.selected.get("category")
    subcategory = self.selected.get("subcategory")
    item = self.selected.get("item")

    next_stage = None

    if self.stage == "category":
        if get_subcategories(self.values[0]):
            next_stage = "subcategory"
        else:
            next_stage = "item"

    elif self.stage == "subcategory":
        next_stage = "item"

    elif self.stage == "item":
        # Check how many variants exist
        variants = get_variants(category, subcategory, item)
        if not variants:
            return await interaction.response.send_message("This item has no valid variants.")

        if len(variants) == 1:
            # Auto-select the only variant (e.g. Default), skip dropdown
            self.selected["variant"] = variants[0]
            price = get_price(category, subcategory, item, variants[0])
            if price is None:
                return await interaction.response.send_message("No price found for this item.")

            class QuantityModal(ui.Modal, title="Enter Quantity"):
                quantity = ui.TextInput(label="Quantity", placeholder="e.g. 2", max_length=3)

                def __init__(self, bot, user_id, selected, price):
                    super().__init__()
                    self.bot = bot
                    self.user_id = user_id
                    self.selected = selected
                    self.price = price

                async def on_submit(self, interaction: discord.Interaction):
                    try:
                        quantity = int(self.quantity.value)
                        if quantity <= 0:
                            raise ValueError
                    except ValueError:
                        return await interaction.response.send_message("Invalid quantity.")

                    subtotal = self.price * quantity
                    item_data = {
                        "category": self.selected["category"],
                        "subcategory": self.selected.get("subcategory"),
                        "item": self.selected["item"],
                        "variant": self.selected["variant"],
                        "quantity": quantity,
                        "subtotal": subtotal
                    }

                    session_manager.add_to_cart(self.user_id, item_data)
                    await interaction.response.send_message(
                        f"✅ Added {quantity}x {item_data['item']} to your cart.")
                    await self.bot.get_cog("TraderCommand").views[self.user_id].update_cart_message(interaction)

            return await interaction.response.send_modal(QuantityModal(self.bot, self.user_id, self.selected, price))

        # Multiple variants exist, proceed to variant dropdown
        next_stage = "variant"

    elif self.stage == "variant":
        variant = self.values[0]
        self.selected["variant"] = variant
        price = get_price(category, subcategory, item, variant)
        if price is None:
            return await interaction.response.send_message("No price available for this variant.")

        return await interaction.response.send_modal(QuantityModal(self.bot, self.user_id, self.selected, price))

    # If dropdown stage continues (category → sub → item → variant)
    view = self.view_ref
    for item in view.children.copy():
        if isinstance(item, discord.ui.Select):
            view.remove_item(item)

    view.add_item(DynamicDropdown(self.bot, self.user_id, next_stage, selected=self.selected, view_ref=view))
    await interaction.response.edit_message(view=view)

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!")

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.")

        total = sum(item["subtotal"] for item in items)
        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        summary = "\n".join(lines)
        summary += f"\n\nTotal: ${total:,}"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        if not trader_channel:
            return await interaction.response.send_message("Trader channel not found.")

        msg = await trader_channel.send(
            f"{interaction.user.mention} has submitted a new order:\n\n{summary}\n\n🔴 Please confirm this message with a ✅ when the order is ready"
        )
        await msg.add_reaction("🔴")
        await interaction.response.send_message("✅ Order submitted to trader channel.")
        session_manager.end_session(self.user_id)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!")

        session_manager.end_session(self.user_id)
        await interaction.response.send_message("❌ Order canceled.")

class StorageSelect(ui.Select):
    def __init__(self, bot, player, admin, total):
        options = [
            discord.SelectOption(label=f"Shed {i}", value=f"shed{i}") for i in range(1, 5)
        ] + [
            discord.SelectOption(label=f"Container {i}", value=f"container{i}") for i in range(1, 7)
        ] + [
            discord.SelectOption(label="Skip", value="skip")
        ]
        super().__init__(placeholder="Select a storage unit or skip", options=options)
        self.bot = bot
        self.player = player
        self.admin = admin
        self.total = total

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.admin.id:
            return await interaction.response.send_message("You are not authorized to select for this order.")

        choice = self.values[0]
        if choice == "skip":
            trader_channel = self.bot.get_channel(config["economy_channel_id"])
            await trader_channel.send(f"{self.player.mention} thanks for your purchase at trader! Stay frosty out there survivor!")
            return await interaction.response.edit_message(content="Skipped. Public message sent.", view=None)

        await interaction.response.send_modal(ComboInputModal(self.bot, self.player, self.admin, choice))

class ComboInputModal(ui.Modal, title="Enter Storage Combo"):
    combo = ui.TextInput(label="4-digit combo", placeholder="e.g. 4582", max_length=4, min_length=4)

    def __init__(self, bot, player, admin, unit):
        super().__init__()
        self.bot = bot
        self.player = player
        self.admin = admin
        self.unit = unit

    async def on_submit(self, interaction: discord.Interaction):
        msg = (
            f"{self.player.mention} your order is complete!\n"
            f"Please proceed to **{self.unit.upper()}** and use the code **{self.combo.value}** to retrieve your order.\n"
            f"Please leave the lock with the same combo on the door when you're finished!\n"
            f"Thanks for your purchase and stay frosty out there survivor!"
        )
        try:
            await self.player.send(msg)
            await interaction.response.send_message("DM sent to player.")
        except:
            await interaction.response.send_message("Failed to DM player.")

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.confirmed_messages = set()
        self.awaiting_payment = {}
        self.awaiting_final_confirmation = {}

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        message = reaction.message

        if message.channel.id == config["trader_orders_channel_id"] and "please confirm this message with a ✅ when the order is ready" in message.content:
            if str(reaction.emoji) == "✅" and message.id not in self.confirmed_messages:
                self.confirmed_messages.add(message.id)
                try:
                    await message.clear_reaction("🔴")
                    await message.add_reaction("✅")
                    admin_mention = user.mention
                    new_content = f"{message.content}\n\nOrder confirmed by admin: {admin_mention}"
                    await message.edit(content=new_content)

                    mentions = message.mentions
                    total = None
                    for line in message.content.splitlines():
                        if "Total:" in line:
                            total = line.split("$")[-1].replace(",", "")
                            break
                    if mentions:
                        player = mentions[0]
                        await user.send(
                            f"{player.mention} your order is ready for pick up.\n"
                            f"Please collect **${total}** from them and confirm this DM with a ✅ once payment is received."
                        )
                        self.awaiting_payment[user.id] = {
                            "player": player,
                            "admin": user,
                            "total": total
                        }
                except Exception as e:
                    print(f"Error confirming order: {e}")

        elif user.id in self.awaiting_payment and str(reaction.emoji) == "✅":
            payment = self.awaiting_payment[user.id]
            try:
                await user.send("Payment confirmed ✅")
                view = ui.View(timeout=30)
                view.add_item(StorageSelect(self.bot, payment["player"], payment["admin"], payment["total"]))
                await user.send("Select storage unit or skip:", view=view)
                del self.awaiting_payment[user.id]
            except Exception as e:
                print(f"Error finishing payment: {e}")

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("You must use this command in the #economy channel.")

        try:
            await interaction.user.send(
                "Buying session started! Use the buttons below to add items, submit, or cancel your order."
            )
            view = TraderView(self.bot, interaction.user.id)
            await interaction.user.send(view=view)
            session_manager.start_session(interaction.user.id)
            await interaction.response.send_message("Trader session moved to your DMs.")
        except:
            await interaction.response.send_message("Could not DM you. Please allow DMs from server members.")

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
