import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio
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
            return [k for k, v in entry.items() if isinstance(v, (int, float))]
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

    async def on_submit(self, interaction: discord.Interaction):
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

        latest_summary = f"✅ Added {quantity}x {self.item} to your cart.\n"
        items = session_manager.get_session_items(self.user_id)
        cart_total = sum(item["subtotal"] for item in items)
        latest_summary += f"🛒 Cart Total: ${cart_total:,}"

        try:
            if self.view_ref and self.view_ref.cart_message:
                await self.view_ref.cart_message.edit(content=latest_summary)
            else:
                self.view_ref.cart_message = await interaction.followup.send(content=latest_summary)
        except Exception:
            self.view_ref.cart_message = await interaction.followup.send(content=latest_summary)

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
                    dropdown = DynamicDropdown(self.bot, self.user_id, "subcategory" if value in ["Clothes", "Weapons"] else "item", {"category": value}, self.view_ref)
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
                await select_interaction.response.edit_message(content="Select an option:", view=new_view)

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

        session_manager.store_order_tracking(order_message.id, {
            "player_id": interaction.user.id,
            "player_mention": interaction.user.mention,
            "summary": summary,
            "total": total,
            "status": "awaiting_admin_confirm"
        })

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
                continue
        session_manager.clear_session(interaction.user.id)

        try:
            if self.ui_message:
                await self.ui_message.edit(view=None)
        except Exception as e:
            print(f"[UI Cleanup - Cancel] {e}")

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return

        message = reaction.message
        order_data = session_manager.get_order_by_message_id(message.id)

        if not order_data:
            return

        # Admin confirms initial order
        if order_data["status"] == "awaiting_admin_confirm" and str(reaction.emoji) == "✅":
            await message.clear_reaction("🔴")
            await message.add_reaction("✅")

            order_data["status"] = "awaiting_payment"
            order_data["admin_id"] = user.id
            order_data["admin_mention"] = user.mention
            session_manager.update_order(message.id, order_data)

            updated = message.content + f"\n\nOrder confirmed by {user.mention}"
            await message.edit(content=updated)

            player = await self.bot.fetch_user(order_data["player_id"])
            dm_msg = await player.send(
                f"{order_data['player_mention']} your order is ready for pick up!\n"
                f"Please make a payment to {user.mention} in the amount of ${order_data['total']:,} and react with ✅ to confirm your payment."
            )
            await dm_msg.add_reaction("🔴")

            session_manager.track_payment_message(dm_msg.id, {
                "player_id": player.id,
                "admin_id": user.id,
                "admin_mention": user.mention,
                "order_id": message.id,
                "total": order_data["total"],
                "status": "awaiting_payment_confirmation"
            })

        # Player confirms payment
        elif message.id in session_manager.payment_confirm_map and str(reaction.emoji) == "✅":
            payment_data = session_manager.payment_confirm_map[message.id]
            if user.id != payment_data["player_id"]:
                return

            await message.clear_reaction("🔴")
            await message.add_reaction("✅")

            updated = message.content + "\n\nPayment confirmed! Please stand by!"
            await message.edit(content=updated)

            trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
            pay_alert = await trader_channel.send(
                f"<@&{config['trader_role_id']}> {user.mention} sent their payment for their order. Please confirm here with a ✅ to proceed!"
            )
            await pay_alert.add_reaction("🔴")

            session_manager.track_final_confirm(pay_alert.id, {
                "player_id": payment_data["player_id"],
                "admin_id": payment_data["admin_id"],
                "order_id": payment_data["order_id"],
                "status": "awaiting_final_confirmation"
            })

            # Admin final confirmation
        elif message.id in session_manager.final_confirm_map and str(reaction.emoji) == "✅":
            final_data = session_manager.final_confirm_map[message.id]
            if user.id != final_data["admin_id"]:
                return

            await message.clear_reaction("🔴")
            await message.add_reaction("✅")

            updated = message.content + f"\n\nPayment confirmed by {user.mention}"
            await message.edit(content=updated)

            player = await self.bot.fetch_user(final_data["player_id"])
            view = StorageSelect(self.bot, player, user)
            await user.send("Select a storage unit or skip:", view=view)

class StorageSelect(ui.Select):
    def __init__(self, bot, player, admin):
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

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.admin.id:
            return await interaction.response.send_message("You are not authorized to select for this order.", ephemeral=True)

        choice = self.values[0]
        if choice == "skip":
            msg = await self.player.send("Thanks for shopping with us, see ya next time! Stay frosty survivor!")
            await msg.add_reaction("🔴")
            await asyncio.sleep(20)
            await msg.delete()
            return await interaction.response.send_message("Skip acknowledged.")

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
        msg = await self.player.send(
            f"{self.player.mention} your order is ready for pick up!\n"
            f"Please proceed to **{self.unit.upper()}** and use the code **{self.combo.value}** to retrieve your order.\n"
            f"Please leave the lock with the same combo on the door when you're finished!\n"
            f"Thanks for your purchase and stay frosty out there survivor!"
        )
        await msg.add_reaction("🔴")

        session_manager.track_unit_clearance(msg.id, {
            "player_id": self.player.id
        })

        await interaction.response.send_message("Combo sent to player.")

        elif message.id in session_manager.unit_clearance_map and str(reaction.emoji) == "✅":
            if user.id != session_manager.unit_clearance_map[message.id]["player_id"]:
                return

            await message.clear_reaction("🔴")
            await message.add_reaction("✅")
            await message.edit(content="All set! See ya next time!")

            await asyncio.sleep(20)
            try:
                await message.delete()
            except:
                pass

            trader_notify = self.bot.get_channel(config["trader_payout_channel_id"])
            if trader_notify:
                await trader_notify.send(f"<@&{config['trader_role_id']}> {user.mention} cleared their unit!")    
    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("You must use this command in the #economy channel.")

        try:
            await interaction.user.send("🛒 Buying session started! Use the buttons below to add items, submit, or cancel your order.")
            view = TraderView(self.bot, interaction.user.id)
            ui_msg = await interaction.user.send(view=view)
            view.ui_message = ui_msg
            session_manager.start_session(interaction.user.id)
            session = session_manager.get_session(interaction.user.id)
            session["cart_messages"] = [ui_msg.id]
            await interaction.response.send_message("Trader session moved to your DMs.")
        except:
            await interaction.response.send_message("Trader session moved to your DMs.")

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
    await bot.tree.sync()
