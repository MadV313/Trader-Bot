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

user_cart_messages = {}  # Tracks DM cart subtotal messages per user

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
            return await interaction.response.send_message("Session expired.", ephemeral=True)
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

            cart_items = session_manager.get_session_items(self.user_id)
            running_total = sum(item['subtotal'] for item in cart_items)

            subtotal_msg = f"Cart subtotal: ${running_total:,}\n"
            for item in cart_items:
                subtotal_msg += f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}\n"

            user = self.bot.get_user(self.user_id)
            if user:
                if self.user_id in user_cart_messages:
                    try:
                        await user_cart_messages[self.user_id].edit(content=subtotal_msg)
                    except:
                        user_cart_messages[self.user_id] = await user.send(subtotal_msg)
                else:
                    user_cart_messages[self.user_id] = await user.send(subtotal_msg)

            await interaction.response.send_message("Item added to cart.", ephemeral=True)
            try:
                await interaction.message.delete()
            except:
                pass
        except Exception:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True)

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!", ephemeral=True)

        class DynamicDropdown(discord.ui.Select):
            def __init__(self, bot, user_id, stage, selected=None):
                self.bot = bot
                self.user_id = user_id
                self.stage = stage
                self.selected = selected or {}
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
                    items = get_items_in_subcategory(
                        self.selected["category"],
                        self.selected.get("subcategory")
                    )
                    options = []
                    for i in items[:25]:
                        variants = get_variants(self.selected["category"], self.selected.get("subcategory"), i)
                        if len(variants) == 1 and variants[0] == "Default":
                            price = get_price(self.selected["category"], self.selected.get("subcategory"), i, "Default") or 0
                            label = f"{i} (${price:,})"
                            options.append(discord.SelectOption(label=label, value=json.dumps({
                                "item": i, "variant": "Default"
                            })))
                        else:
                            options.append(discord.SelectOption(label=f"{i} (select variant...)", value=json.dumps({
                                "item": i, "variant": None
                            })))
                    return options

                if self.stage == "variant":
                    variants = get_variants(
                        self.selected["category"],
                        self.selected.get("subcategory"),
                        self.selected["item"]
                    )
                    options = []
                    for v in variants[:25]:
                        price = get_price(self.selected['category'], self.selected.get('subcategory'), self.selected['item'], v) or 0
                        label_text = v.split("<")[0].strip()
                        emoji = None

                        if "<" in v and ">" in v:
                            try:
                                emoji_str = v[v.find("<"):v.find(">")+1]
                                emoji = discord.PartialEmoji.from_str(emoji_str)
                            except Exception:
                                emoji = None

                        options.append(discord.SelectOption(
                            label=f"{label_text} (${price:,})",
                            value=v,
                            emoji=emoji
                        ))
                    return options

            async def callback(self, select_interaction: discord.Interaction):
                if select_interaction.user.id != self.user_id:
                    return await select_interaction.response.send_message("Not your session.", ephemeral=True)

                value = self.values[0]

                if self.stage == "category":
                    if self.values[0] in ["Clothes", "Weapons"]:
                        dropdown = DynamicDropdown(self.bot, self.user_id, "subcategory", {"category": value})
                    else:
                        dropdown = DynamicDropdown(self.bot, self.user_id, "item", {"category": value})

                elif self.stage == "subcategory":
                    new_selection = self.selected.copy()
                    new_selection["subcategory"] = value
                    dropdown = DynamicDropdown(self.bot, self.user_id, "item", new_selection)

                elif self.stage == "item":
                    new_selection = self.selected.copy()
                    item_data = json.loads(value)
                    new_selection["item"] = item_data["item"]

                    if item_data["variant"] == "Default":
                        await select_interaction.response.send_modal(
                            QuantityModal(
                                self.bot, self.user_id,
                                new_selection["category"],
                                new_selection.get("subcategory"),
                                new_selection["item"],
                                "Default"
                            )
                        )
                        try:
                            await select_interaction.message.delete()
                        except:
                            pass
                        return
                    else:
                        dropdown = DynamicDropdown(self.bot, self.user_id, "variant", new_selection)

                elif self.stage == "variant":
                    new_selection = self.selected.copy()
                    new_selection["variant"] = value
                    await select_interaction.response.send_modal(
                        QuantityModal(
                            self.bot, self.user_id,
                            new_selection["category"],
                            new_selection.get("subcategory"),
                            new_selection["item"],
                            new_selection["variant"]
                        )
                    )
                    try:
                        await select_interaction.message.delete()
                    except:
                        pass
                    return
                else:
                    return

                new_view = discord.ui.View(timeout=180)
                new_view.add_item(dropdown)
                await select_interaction.response.edit_message(content="Select an option:", view=new_view)

        view = discord.ui.View(timeout=180)
        view.add_item(DynamicDropdown(self.bot, self.user_id, "category"))
        user = self.bot.get_user(self.user_id)
        if user:
            await user.send("Select a category:", view=view)

        summary += "please confirm this message with a ✅ when the order is ready"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        order_msg = await trader_channel.send(summary)
        await order_msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Order submitted for admin approval!", ephemeral=True)
        if self.cart_message and not self.cart_message._state.is_closed():
            try:
                await self.cart_message.delete()
            except:
                pass

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return

        session_manager.clear_session(self.user_id)

        if self.cart_message and not self.cart_message._state.is_closed():
            try:
                await self.cart_message.delete()
            except:
                pass

        await interaction.response.send_message("Order canceled.", ephemeral=True)

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
            return await interaction.response.send_message("Session expired.", ephemeral=True)

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

            cart_items = session_manager.get_session_items(self.user_id)
            running_total = sum(item['subtotal'] for item in cart_items)
            updated_text = "\n".join([
                f"{item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}"
                for item in cart_items
            ])
            updated_text += f"\n\nTotal: ${running_total:,}"

            user = self.bot.get_user(self.user_id)
            dm_channel = user.dm_channel or await user.create_dm()

            # Edit previous cart message
            if self.bot.cart_messages.get(self.user_id):
                try:
                    await self.bot.cart_messages[self.user_id].edit(content=updated_text)
                except:
                    pass
            else:
                self.bot.cart_messages[self.user_id] = await dm_channel.send(content=updated_text)

            await interaction.response.send_message(
                f"{self.item} ({self.variant}) x{quantity} added to cart.",
                ephemeral=True
            )
            try:
                await interaction.message.delete()
            except:
                pass

        except Exception:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True)

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
            return await interaction.response.send_message("You are not authorized to select for this order.", ephemeral=True)

        choice = self.values[0]
        if choice == "skip":
            await self.player.send("Thanks for your purchase at trader! Stay frosty out there survivor!")
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
            await interaction.response.send_message("DM sent to player.", ephemeral=True)
        except:
            await interaction.response.send_message("Failed to DM player.", ephemeral=True)

class TraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.confirmed_messages = set()
        self.awaiting_payment = {}
        self.awaiting_final_confirmation = {}
        self.cart_messages = {}

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot:
            return
        message = reaction.message

        # PHASE 1 — Admin confirms order
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
                        payment_msg = await player.send(
                            f"Your order is ready for pick up.\n"
                            f"Please make a payment of ${total} to {admin_mention} and react with ✅ once you’ve sent your payment!"
                        )
                        await payment_msg.add_reaction("🔴")
                        self.awaiting_payment[payment_msg.id] = {
                            "player_id": player.id,
                            "player_mention": player.mention,
                            "admin_mention": admin_mention,
                            "admin": user,
                            "total": total
                        }
                except Exception as e:
                    print(f"Error in admin confirm: {e}")

        # PHASE 2 — Player confirms payment
        elif message.id in self.awaiting_payment and str(reaction.emoji) == "✅":
            payment_data = self.awaiting_payment[message.id]
            if user.id != payment_data["player_id"]:
                return await message.channel.send("Mind your own orders!")
            try:
                await message.clear_reaction("🔴")
                await message.edit(content=f"✅ Payment sent by {user.mention}")
                await message.add_reaction("✅")

                admin_user = payment_data["admin"]
                player_user = self.bot.get_user(payment_data["player_id"])
                final_msg = await admin_user.send(
                    f"{payment_data['player_mention']} sent their payment of ${payment_data['total']} "
                    f"for their order. Please confirm with ✅ to complete checkout/storage info!"
                )
                await final_msg.add_reaction("🔴")
                self.awaiting_final_confirmation[final_msg.id] = {
                    "player": player_user,
                    "admin": admin_user,
                    "total": payment_data["total"]
                }
                del self.awaiting_payment[message.id]
            except Exception as e:
                print(f"Error in player confirm: {e}")

        # PHASE 3 — Admin confirms payment and selects storage
        elif message.id in self.awaiting_final_confirmation and str(reaction.emoji) == "✅":
            try:
                await message.clear_reaction("🔴")
                await message.add_reaction("✅")
                await message.edit(content=f"{message.content}\n\n✅ Payment confirmed by {user.mention}")
                data = self.awaiting_final_confirmation[message.id]
                view = ui.View(timeout=20)
                view.add_item(StorageSelect(self.bot, data["player"], data["admin"], data["total"]))
                await message.channel.send("Select a storage unit or skip:", view=view)
                del self.awaiting_final_confirmation[message.id]
            except Exception as e:
                print(f"Error in storage confirmation: {e}")

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("You can only use this command in the economy channel.", ephemeral=True)

        try:
            dm_channel = await interaction.user.create_dm()
            session_manager.start_session(interaction.user.id)
            view = TraderView(self.bot, interaction.user.id)
            await dm_channel.send("Buying session started! Use the buttons below to add items, submit, or cancel your order.", view=view)
            await interaction.response.send_message("Trader session started in DMs!", ephemeral=True)
        except:
            await interaction.response.send_message("Failed to send DM. Make sure your DMs are enabled.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
