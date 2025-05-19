import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio
from utils import session_manager, variant_utils
from utils import trader_logger

import re

def extract_label_and_emoji(text):
    match = re.search(r'(<:.*?:\d+>)', text)
    if match:
        emoji = match.group(1)
        label = text.split(' <')[0].strip()
        return label, emoji
    return text, None
    
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_TIMEOUT_SECONDS = 259200  # 3 days

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

        # 📦 Send item added confirmation
        confirm_msg = await interaction.followup.send(
            content=f"📦 Added: **{self.item} ({self.variant})** x{quantity}",
            ephemeral=False
        )
        
        # 🧹 Clean up message after 5 seconds
        async def cleanup():
            await asyncio.sleep(5)
            try:
                await confirm_msg.delete()
            except Exception as e:
                print(f"[Add Confirmation Cleanup Error] {e}")
        
        asyncio.create_task(cleanup())

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
            return await interaction.response.send_message("Not your session.")

        if self.current_stage == "variant":
            prev_stage = "item"
        elif self.current_stage == "item":
            prev_stage = "subcategory" if "subcategory" in self.selected else "category"
        elif self.current_stage == "subcategory":
            prev_stage = "category"
        else:
            return

        dropdown = DynamicDropdown(self.bot, self.user_id, prev_stage, self.selected, self.view_ref)
        view = discord.ui.View(timeout=TRADER_TIMEOUT_SECONDS)
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
                    return await select_interaction.response.send_message("Not your session.")
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
                new_view = discord.ui.View(timeout=TRADER_TIMEOUT_SECONDS)
                new_view.add_item(dropdown)
                if dropdown.stage != "category":
                    new_view.add_item(BackButton(self.bot, self.user_id, dropdown.stage, self.selected, self.view_ref))
                await select_interaction.response.edit_message(content="Select an option:", view=new_view)

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=TRADER_TIMEOUT_SECONDS)
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

        view = discord.ui.View(timeout=TRADER_TIMEOUT_SECONDS)
        view.add_item(DynamicDropdown(self.bot, self.user_id, "category", view_ref=self))
        await interaction.response.send_message("Select a category:", view=view)

    @discord.ui.button(label="Remove Last Item", style=discord.ButtonStyle.secondary)
    async def remove_last_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.")

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Cart is already empty.")

        removed_item = items.pop()
        session_manager.set_session_items(self.user_id, items)  # update the session

        # Update cart display
        if not items:
            message = "🗑️ Your cart is now empty."
            try:
                if self.cart_message:
                    await self.cart_message.edit(content=message)
                else:
                    self.cart_message = await interaction.followup.send(content=message)
            except:
                self.cart_message = await interaction.followup.send(content=message)

            await interaction.response.send_message(f"🗑️ Removed {removed_item['item']}.")
            try:
                await asyncio.sleep(5)
                deletion_target = await interaction.original_response()
                await deletion_target.delete()
            except Exception as e:
                print(f"[Remove Empty Cart Msg Cleanup Fail] {e}")
            return

        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        cart_total = sum(item["subtotal"] for item in items)
        summary = "\n".join(lines) + f"\n\n🛒 Cart Total: ${cart_total:,}"

        await interaction.response.send_message(f"🗑️ Removed {removed_item['item']}.")  # respond ONCE

        try:
            if self.cart_message:
                await self.cart_message.edit(content=summary)
            else:
                self.cart_message = await interaction.followup.send(content=summary)
        except:
            self.cart_message = await interaction.followup.send(content=summary)

        # Schedule delete of removal notice (the response message)
        try:
            await asyncio.sleep(6)
            deletion_target = await interaction.original_response()
            await deletion_target.delete()
        except Exception as e:
            print(f"[Remove Item Msg Cleanup Fail] {e}")

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
            f"<@&{config['trader_role_id']}> **a new order is ready to be processed!**\n\n"
            f"{interaction.user.mention} has submitted a new order:\n\n"
            f"{summary}\n\n"
            f"Please confirm this message with a ✅ when the order is ready"
        )
        await order_message.add_reaction("🔴")

        await interaction.response.send_message("✅ **Your order has been submitted to the trader channel. Please stand by...**")

        try:
            await interaction.message.delete()
        except:
            pass
        session = session_manager.get_session(interaction.user.id)
        for msg_id in session.get("cart_messages", [])[1:]:
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
        await interaction.response.send_message("❌ Order canceled. This session will auto-close in 10 seconds...")

        # ⏳ Wait before cleanup
        await asyncio.sleep(10)

        # ✅ Wipe all bot messages in DM
        try:
            user_dm = await interaction.user.create_dm()
            async for msg in user_dm.history(limit=100):
                if msg.author == self.bot.user:
                    try:
                        await msg.delete()
                    except:
                        pass
        except Exception as e:
            print(f"[Full DM Wipe Error - Cancel Order] {e}")

        session_manager.clear_session(interaction.user.id)

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.awaiting_payment = {}
        self.awaiting_storage = {}
        self.awaiting_pickup = {}

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        print(f"[Reaction Detected] emoji={reaction.emoji} message_id={reaction.message.id} user={user}")

        if user.bot or not reaction.message:
            return

        message = reaction.message
        emoji = str(reaction.emoji)

        # Phase 1: Admin confirms order
        if message.channel.id == config["trader_orders_channel_id"] and emoji == "✅":
            if "Please confirm this message with a ✅ when the order is ready" in message.content and message.id not in self.awaiting_payment:
                await message.clear_reaction("🔴")
                await message.add_reaction("✅")
                new_content = f"{message.content}\n\nOrder confirmed by {user.mention}"
                await message.edit(content=new_content)

                mentioned_users = message.mentions
                total = None
                for line in message.content.splitlines():
                    if "Total:" in line:
                        total = line.split("$")[-1].replace(",", "")
                        break

                if mentioned_users:
                    player = mentioned_users[0]
                    dm = await player.send(
                        f"📦 **Your order has been processed!**\n\n"
                        f"💰 Please make a payment to {user.mention} for **${total}**.\n"
                        f"📍 Make sure to send payment in <#{config['economy_channel_id']}> (use /pay + copy/paste command below).\n\n"
                        f"**Once paid, react to this message with a** ✅ **to confirm.**"
                    )
                    await dm.add_reaction("⚠️")
                    self.awaiting_payment[dm.id] = {
                        "player": player,
                        "admin": user,
                        "total": total,
                        "original_message": message
                    }

                    await user.send(
                        f"user:{user.id} amount:{total}"
                    )
                    # ✅ Log payout confirmer
                    log_data = trader_logger.load_reaction_log()
                    admin_id = str(user.id)
                    log_data[admin_id] = log_data.get(admin_id, 0) + 1
                    trader_logger.save_reaction_log(log_data)

        # Phase 2: Player confirms payment
        elif emoji == "✅" and reaction.message.id in self.awaiting_payment:
            print(f"[✅ Payment Reaction] Player {user} reacted to message {reaction.message.id}")
            data = self.awaiting_payment.pop(reaction.message.id)
        
            try:
                if not isinstance(reaction.message.channel, discord.DMChannel):
                    await reaction.message.clear_reaction("🔴")
            except discord.Forbidden:
                pass
        
            await reaction.message.add_reaction("✅")
            await reaction.message.edit(content=reaction.message.content + "\n\n✅ Payment confirmed! Please stand by.")
        
            trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
            payment_notice = await trader_channel.send(
                content=(
                    "https://cdn.discordapp.com/attachments/1370152442183946311/1374096506055032943/ezgifcom-resize-2.mp4\n\n"
                    f"{data['player'].mention} **has confirmed payment.** 💵\n"
                    "**Please select a storage unit below:**"
                )
            )
            
            # ⏳ Auto-delete after 10 seconds
            async def auto_delete_payment_notice():
                await asyncio.sleep(10)
                try:
                    await payment_notice.delete()
                except Exception as e:
                    print(f"[Auto Delete Payment Message Error] {e}")
            
            asyncio.create_task(auto_delete_payment_notice())

            print(f"[PHASE 2] Posted payment confirmation message with ID: {payment_notice.id}")
        
            class StorageSelect(ui.Select):
                def __init__(self, bot, player, confirm_message):
                    options = [discord.SelectOption(label=f"Shed {i}", value=f"shed{i}") for i in range(1, 5)] + \
                              [discord.SelectOption(label=f"Container {i}", value=f"container{i}") for i in range(1, 7)] + \
                              [discord.SelectOption(label="Skip", value="skip")]
                    super().__init__(placeholder="Select a storage unit or skip", options=options)
                    self.bot = bot
                    self.player = player
                    self.confirm_message = confirm_message
        
                async def callback(self, interaction: discord.Interaction):
                    choice = self.values[0]
                    print(f"[PHASE 2/3] Storage option selected: {choice}")
        
                    try:
                        await self.confirm_message.edit(
                            content=self.confirm_message.content + f"\n\n✅ Payment confirmed by {interaction.user.mention}",
                            view=None
                        )
                    except Exception as e:
                        print(f"[PHASE 2/3] Could not update confirmation message: {e}")
        
                    if choice == "skip":
                        try:
                            msg = await self.player.send(
                                content=(
                                    "https://cdn.discordapp.com/attachments/1351365150287855739/1373723922809491476/"
                                    "Trader2-ezgif.com-video-to-gif-converter.gif\n\n"
                                    "📦 **Your order has been completed — no storage was assigned this time.**\n"
                                    "**Thanks for using Trader! Stay Frosty out survivor!**❄️"
                                )
                            )
                            await asyncio.sleep(60)
                            async for m in self.player.dm_channel.history(limit=100):
                                if m.author == self.bot.user:
                                    await m.delete()
                        except Exception as e:
                            print(f"[PHASE 2/3] Skip DM Cleanup Error: {e}")
                        return await interaction.response.send_message("✅ Skip acknowledged.", ephemeral=True)
        
                    await interaction.response.send_modal(ComboInputModal(self.bot, self.player, choice))
        
            class ComboInputModal(ui.Modal, title="Enter 4-digit Combo"):
                combo = ui.TextInput(label="4-digit combo", placeholder="e.g. 1234", max_length=4, min_length=4)
        
                def __init__(self, bot, player, unit):
                    super().__init__()
                    self.bot = bot
                    self.player = player
                    self.unit = unit
        
                async def on_submit(self, interaction: discord.Interaction):
                    try:
                        dm = await self.player.send(
                            f"{self.player.mention}, 📦**your order is ready for pick up!**\n"
                            f"Please proceed to **{self.unit.upper()}** and use code **{self.combo.value}** to unlock.\n"
                            f"**Please leave the lock with the same code when done!**🔐\n"
                        )
                        view = PickupConfirmView(self.bot, self.player, self.unit, dm)
                        await dm.edit(view=view)
                        self.bot.get_cog("TraderCommand").awaiting_pickup[dm.id] = {
                            "player": self.player,
                            "unit": self.unit
                        }
                        await interaction.response.send_message("✅ **Combo submitted. Player has been notified.**🔒")
                    except Exception as e:
                        print(f"[PHASE 2/3] Combo DM Error: {e}")
                        await interaction.response.send_message("❌ Failed to notify player.", ephemeral=True)
        
            try:
                dropdown = StorageSelect(self.bot, data["player"], payment_notice)
                view = ui.View(timeout=TRADER_TIMEOUT_SECONDS)
                view.add_item(dropdown)
                await payment_notice.edit(view=view)
                print(f"[PHASE 2/3] Dropdown view attached to message ID: {payment_notice.id}")
            except Exception as e:
                print("[PHASE 2/3 DROPDOWN ERROR]")
                import traceback
                traceback.print_exc()
        
        # Phase 4: Player confirms pickup complete (now using button instead of reaction)
        class PickupConfirmView(ui.View):
            def __init__(self, bot, player, unit, message_to_cleanup):
                super().__init__(timeout=TRADER_TIMEOUT_SECONDS)
                self.bot = bot
                self.player = player
                self.unit = unit
                self.message_to_cleanup = message_to_cleanup
        
            @ui.button(label="✅ Confirm Pickup", style=discord.ButtonStyle.success)
            async def confirm_pickup(self, interaction: discord.Interaction, button: discord.ui.Button):
                if interaction.user.id != self.player.id:
                    return await interaction.response.send_message("You're not the assigned player.", ephemeral=True)
            
                # ✅ Edit the original DM message to show confirmation with GIF
                try:
                    await self.message_to_cleanup.edit(
                        content=(
                            "https://cdn.discordapp.com/attachments/1351365150287855739/1373723922809491476/"
                            "Trader2-ezgif.com-video-to-gif-converter.gif\n\n"
                            "✅ All set, see ya next time!"
                        ),
                        view=None
                    )
                except Exception as e:
                    print(f"[PHASE 4] Failed to edit message: {e}")
            
                # ✅ Send message to trader_orders_channel_id (NOT payout)
                try:
                    orders_channel = self.bot.get_channel(config["trader_orders_channel_id"])
                    if orders_channel is None:
                        print("[PHASE 4] get_channel returned None, trying fetch_channel...")
                        orders_channel = await self.bot.fetch_channel(config["trader_orders_channel_id"])
            
                    await orders_channel.send(
                        f"<@&{config['trader_role_id']}> {self.player.mention} cleared **{self.unit.upper()}**!🔓"
                    )
                    print(f"[PHASE 4] ✅ Trader Orders message sent.")
                except Exception as e:
                    print(f"[PHASE 4] Failed to notify trader orders channel: {e}")
            
                # ✅ Acknowledge to user
                await interaction.response.send_message("✅ **Thanks! Your pickup has been confirmed.**")
            
                # ⏳ Delay cleanup to ensure visibility
                await asyncio.sleep(10)
                try:
                    async for m in self.player.dm_channel.history(limit=100):
                        if m.author == self.bot.user:
                            await m.delete()
                    print(f"[PHASE 4] Cleaned up bot DMs.")
                except Exception as e:
                    print(f"[PHASE 4] DM Cleanup Error: {e}")

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("You must use this command in the #economy channel.")

        try:
            # Step 1: Send the animated GIF
            gif_msg = await interaction.user.send("https://cdn.discordapp.com/attachments/1371698983604326440/1373359533304582237/ezgif.com-optimize.gif")

            # Step 2: Send boxed session start message
            start_msg = await interaction.user.send(
                "┏━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "🛒 **BUYING SESSION STARTED!**\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                "**Use the buttons below to add/remove items,\nsubmit, or cancel your order.**"
            )

            # Step 3: Send the interactive UI
            view = TraderView(self.bot, interaction.user.id)
            ui_msg = await interaction.user.send(view=view)
            view.ui_message = ui_msg
            view.start_message = start_msg  # Optional if still used in cleanup

            # Step 4: Track all messages for cleanup
            session_manager.start_session(interaction.user.id)
            session = session_manager.get_session(interaction.user.id)
            session["cart_messages"] = [gif_msg.id, start_msg.id, ui_msg.id]
            session["start_msg_id"] = start_msg.id

            await interaction.response.send_message("📬Trader session moved to your DMs.")
        except Exception as e:
            print(f"[Trader DM Start Error] {e}")
            await interaction.response.send_message("📬Trader session moved to your DMs.")

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
