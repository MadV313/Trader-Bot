import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio
from utils import session_manager, variant_utils

import re

def extract_label_and_emoji(text):
    match = re.search(r'(<:.*?:\d+>)', text)
    if match:
        emoji = match.group(1)
        label = text.split(' <')[0].strip()
        return label, emoji
    return text, None
    
config = json.loads(os.environ.get("CONFIG_JSON"))

PRICE_FILE = os.path.join("data", "Final price list.json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

def get_categories():
    return list(PRICE_DATA.keys())

def get_subcategories(category):
    """
    Returns first-level subcategories under a category.
    Handles nested structures like Clothes > Backpacks > Assault Bag.
    """
    sub_data = PRICE_DATA.get(category, {})
    return [key for key, val in sub_data.items() if isinstance(val, dict)]

def get_items_in_subcategory(category, subcategory):
    """
    Returns a list of actual item names from a subcategory.
    Handles deeply nested structures (e.g. Clothes > Backpacks > Assault Bag).
    """
    if subcategory:
        sub_data = PRICE_DATA.get(category, {}).get(subcategory, {})
    else:
        sub_data = PRICE_DATA.get(category, {})

    item_list = []
    for key, val in sub_data.items():
        if isinstance(val, dict):
            # Direct item with prices
            if all(isinstance(v, (int, float)) for v in val.values()):
                item_list.append(key)
            # Nested items (e.g., variants)
            else:
                for nested_key, nested_val in val.items():
                    if isinstance(nested_val, dict) and all(isinstance(v, (int, float)) for v in nested_val.values()):
                        item_list.append(nested_key)
    return item_list

def get_variants(category, subcategory, item):
    try:
        entry = PRICE_DATA[category]
        if subcategory:
            entry = entry[subcategory]
        if item in entry:
            # Direct variant dict (e.g., {"Default": 500})
            return [k for k, v in entry[item].items() if isinstance(v, (int, float))]
        else:
            # Handle nested dict (e.g., Clothes > Backpacks > Assault Bag > Black)
            for parent_key, val in entry.items():
                if isinstance(val, dict) and item in val:
                    return [k for k, v in val[item].items() if isinstance(v, (int, float))]
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

class QuantityModal(ui.Modal, title="Enter Quantity"):
    quantity = ui.TextInput(label="Quantity", placeholder="e.g. 2", max_length=3)

    def __init__(self, bot, user_id, category, subcategory, item, variant, view_ref):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant
        self.view_ref = view_ref
        self.price = get_price(category, subcategory, item, variant)

class QuantityModal(ui.Modal, title="Enter Quantity"):
    quantity = ui.TextInput(label="Quantity", placeholder="e.g. 2", max_length=3)

    def __init__(self, bot, user_id, category, subcategory, item, variant, view_ref):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant
        self.view_ref = view_ref
        self.price = get_price(category, subcategory, item, variant)

    async def on_submit(self, interaction: discord.Interaction):  # ← THIS MUST BE INDENTED INSIDE
        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Invalid quantity.")

        subtotal = self.price * quantity
        item_data = {
            "category": self.category,
            "subcategory": self.subcategory,
            "item": self.item,
            "variant": self.variant,
            "quantity": quantity,
            "subtotal": subtotal
        }

        session_manager.add_item(self.user_id, item_data)

        try:
            await interaction.message.delete()
        except Exception:
            pass

        await interaction.response.defer()

        items = session_manager.get_session_items(self.user_id)
        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        cart_total = sum(item["subtotal"] for item in items)
        summary = "\n".join(lines)
        summary += f"\n\n🛒 Cart Total: ${cart_total:,}"

        try:
            if self.view_ref and self.view_ref.cart_message:
                await self.view_ref.cart_message.edit(content=summary)
            else:
                self.view_ref.cart_message = await interaction.followup.send(content=summary)
        except Exception:
            self.view_ref.cart_message = await interaction.followup.send(content=summary)

class BackButton(discord.ui.Button):
    def __init__(self, bot, user_id, current_stage, selected, view_ref):
        super().__init__(label="Back", style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.user_id = user_id
        self.current_stage = current_stage
        self.selected = selected
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        if self.current_stage == "variant":
            prev_stage = "item"
        elif self.current_stage == "item":
            prev_stage = "subcategory" if "subcategory" in self.selected else "category"
        elif self.current_stage == "subcategory":
            prev_stage = "category"
        else:
            return

        dropdown = DynamicDropdown(self.bot, self.user_id, prev_stage, self.selected, self.view_ref)
        view = discord.ui.View(timeout=180)
        view.add_item(dropdown)

        if prev_stage != "category":
            view.add_item(BackButton(self.bot, self.user_id, prev_stage, self.selected, self.view_ref))

        await interaction.response.edit_message(content="Back to previous selection:", view=view)

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
                    options = []
                    for c in get_categories()[:25]:
                        label, emoji = extract_label_and_emoji(c)
                        options.append(discord.SelectOption(label=label, value=c, emoji=emoji))
                    return options
                if self.stage == "subcategory":
                    subcats = get_subcategories(self.selected["category"])
                    return [discord.SelectOption(label=s, value=s) for s in subcats[:25]]
                if self.stage == "item":
                    items = get_items_in_subcategory(self.selected["category"], self.selected.get("subcategory"))
                    options = []
                    for i in items[:25]:
                        variants = get_variants(self.selected["category"], self.selected.get("subcategory"), i)
                        if len(variants) == 1 and variants[0] == "Default":
                            price = get_price(self.selected["category"], self.selected.get("subcategory"), i, "Default") or 0
                            label = f"{i} (${price:,})"
                            options.append(discord.SelectOption(label=label, value=json.dumps({"item": i, "variant": "Default"})))
                        else:
                            options.append(discord.SelectOption(label=f"{i} (select variant...)", value=json.dumps({"item": i, "variant": None})))
                    return options
                if self.stage == "variant":
                    variants = get_variants(self.selected["category"], self.selected.get("subcategory"), self.selected["item"])
                    options = []
                    for v in variants[:25]:
                        price = get_price(self.selected['category'], self.selected.get('subcategory'), self.selected['item'], v) or 0
                        label_text = v.split("<")[0].strip()
                        emoji = None
                        if "<" in v and ">" in v:
                            try:
                                emoji_str = v[v.find("<"):v.find(">")+1]
                                emoji = discord.PartialEmoji.from_str(emoji_str)
                            except:
                                emoji = None
                        options.append(discord.SelectOption(label=f"{label_text} (${price:,})", value=v, emoji=emoji))
                    return options

            async def callback(self, select_interaction: discord.Interaction):
                if select_interaction.user.id != self.user_id:
                    return await select_interaction.response.send_message("Not your session.", ephemeral=True)
                value = self.values[0]
                if self.stage == "category":
                    category_name = value.lower()
                    if "clothes" in category_name:
                        next_stage = "subcategory"
                    else:
                        next_stage = "item"

                    dropdown = DynamicDropdown(
                        self.bot,
                        self.user_id,
                        next_stage,
                        {"category": value},
                        self.view_ref
                    )
                elif self.stage == "subcategory":
                    new_selection = self.selected.copy()
                    new_selection["subcategory"] = value
                    dropdown = DynamicDropdown(self.bot, self.user_id, "item", new_selection, self.view_ref)
                elif self.stage == "item":
                    new_selection = self.selected.copy()
                    item_data = json.loads(value)
                    new_selection["item"] = item_data["item"]
                    if item_data["variant"] == "Default":
                        return await select_interaction.response.send_modal(
                            QuantityModal(self.bot, self.user_id, new_selection["category"], new_selection.get("subcategory"), new_selection["item"], "Default", self.view_ref)
                        )
                    dropdown = DynamicDropdown(self.bot, self.user_id, "variant", new_selection, self.view_ref)
                elif self.stage == "variant":
                    new_selection = self.selected.copy()
                    new_selection["variant"] = value
                    return await select_interaction.response.send_modal(
                        QuantityModal(self.bot, self.user_id, new_selection["category"], new_selection.get("subcategory"), new_selection["item"], new_selection["variant"], self.view_ref)
                    )
                new_view = discord.ui.View(timeout=180)
                new_view.add_item(dropdown)
                if dropdown.stage != "category":
                    new_view.add_item(BackButton(self.bot, self.user_id, dropdown.stage, self.selected, self.view_ref))
                await select_interaction.response.edit_message(content="Select an option:", view=new_view)

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.cart_message = None
        self.ui_message = None

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

        view = discord.ui.View(timeout=180)
        view.add_item(DynamicDropdown(self.bot, self.user_id, "category", view_ref=self))
        await interaction.response.send_message("Select a category:", view=view)

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!")

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.")

        total = sum(item["subtotal"] for item in items)
        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        summary = "\n".join(lines) + f"\n\nTotal: ${total:,}"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        if not trader_channel:
            return await interaction.response.send_message("Trader channel not found.")

        order_message = await trader_channel.send(
            f"<@&{config['trader_role_id']}> a new order is ready to be processed!\n\n"
            f"{interaction.user.mention} has submitted a new order:\n\n"
            f"{summary}\n\n"
            f"Please confirm this message with a ✅ when the order is ready"
        )
        await order_message.add_reaction("🔴")

        await interaction.response.send_message("✅ Order submitted to trader channel.")

        try:
            await interaction.message.delete()
        except:
            pass
        session = session_manager.sessions.get(interaction.user.id, {})
        for msg_id in session.get("cart_messages", []):
            try:
                msg = await interaction.channel.fetch_message(msg_id)
                await msg.delete()
            except:
                continue
        session_manager.clear_session(interaction.user.id)
        session_manager.end_session(self.user_id)

        try:
            if self.ui_message:
                await self.ui_message.edit(view=None)
        except Exception as e:
            print(f"[UI Cleanup - Submit] {e}")

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!")

        session_manager.end_session(self.user_id)
        await interaction.response.send_message("❌ Order canceled.")

        try:
            await interaction.message.delete()
        except:
            pass

        session = session_manager.sessions.get(interaction.user.id, {})
        for msg_id in session.get("cart_messages", []):
            try:
                msg = await interaction.channel.fetch_message(msg_id)
                await msg.delete()
            except:
                pass

        session_manager.clear_session(interaction.user.id)

        try:
            if self.ui_message:
                await self.ui_message.edit(view=None)
        except Exception as e:
            print(f"[UI Cleanup - Cancel] {e}")

    # Wait and try to delete UI message (DM)
        await asyncio.sleep(10)
        try:
            if self.ui_message:
                await self.ui_message.delete()
        except:
            pass

    @discord.ui.button(label="Remove Last Item", style=discord.ButtonStyle.secondary)
    async def remove_last_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.")

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Cart is already empty.", ephemeral=True)

        removed_item = items.pop()
        session_manager.set_session_items(self.user_id, items)  # update the session

        if not items:
            if self.cart_message:
                try:
                    await self.cart_message.delete()
                    self.cart_message = None
                except:
                    pass
            return await interaction.response.send_message("🗑️ Removed last item. Cart is now empty.")

        # Update cart display
        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        cart_total = sum(item["subtotal"] for item in items)
        summary = "\n".join(lines) + f"\n\n🛒 Cart Total: ${cart_total:,}"

        try:
            if self.cart_message:
                await self.cart_message.edit(content=summary)
            else:
                self.cart_message = await interaction.followup.send(content=summary)
        except:
            self.cart_message = await interaction.followup.send(content=summary)

        await interaction.response.send_message(f"🗑️ Removed {removed_item['item']}.", ephemeral=True)
