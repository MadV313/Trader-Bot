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

class TraderView(discord.ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=180)
        self.bot = bot
        self.user_id = user_id
        self.dropdown_message_id = None
        self.dropdown_channel_id = None

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn’t your cart session.", ephemeral=True)

        class DynamicDropdown(discord.ui.Select):
            def __init__(self, bot, user_id, stage, selected=None, dropdown_owner_view=None):
                self.bot = bot
                self.user_id = user_id
                self.stage = stage
                self.selected = selected or {}
                self.dropdown_owner_view = dropdown_owner_view
                placeholder = "Select a category" if stage == "category" else \
                              "Select a subcategory" if stage == "subcategory" else \
                              "Select an item" if stage == "item" else "Select a variant"
                options = self.get_options()
                super().__init__(placeholder=placeholder, options=options)

            def get_options(self):
                if self.stage == "category":
                    return [discord.SelectOption(label=c, value=c) for c in get_categories()[:25]]
                if self.stage == "subcategory":
                    return [discord.SelectOption(label=s, value=s) for s in get_subcategories(self.selected["category"])[:25]]
                if self.stage == "item":
                    items = get_items_in_subcategory(self.selected["category"], self.selected.get("subcategory"))
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
                    variants = get_variants(self.selected["category"], self.selected.get("subcategory"), self.selected["item"])
                    return [discord.SelectOption(label=f"{v} (${get_price(self.selected['category'], self.selected.get('subcategory'), self.selected['item'], v) or 0:,})", value=v) for v in variants[:25]]

            async def callback(self, select_interaction: discord.Interaction):
                if select_interaction.user.id != self.user_id:
                    return await select_interaction.response.send_message("Not your session.", ephemeral=True)

                value = self.values[0]
                dropdown = None

                try:
                    if self.stage == "category":
                        if value in ["Clothes", "Weapons"]:
                            dropdown = DynamicDropdown(self.bot, self.user_id, "subcategory", {"category": value}, self.dropdown_owner_view)
                        else:
                            dropdown = DynamicDropdown(self.bot, self.user_id, "item", {"category": value}, self.dropdown_owner_view)

                    elif self.stage == "subcategory":
                        new_selection = self.selected.copy()
                        new_selection["subcategory"] = value
                        dropdown = DynamicDropdown(self.bot, self.user_id, "item", new_selection, self.dropdown_owner_view)

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
                                    "Default",
                                    dropdown_info={
                                        "channel_id": self.dropdown_owner_view.dropdown_channel_id,
                                        "message_id": self.dropdown_owner_view.dropdown_message_id
                                    }
                                )
                            )
                            try:
                                await select_interaction.message.delete()
                            except:
                                pass
                            return
                        else:
                            dropdown = DynamicDropdown(self.bot, self.user_id, "variant", new_selection, self.dropdown_owner_view)

                    elif self.stage == "variant":
                        new_selection = self.selected.copy()
                        new_selection["variant"] = value
                        await select_interaction.response.send_modal(
                            QuantityModal(
                                self.bot, self.user_id,
                                new_selection["category"],
                                new_selection.get("subcategory"),
                                new_selection["item"],
                                new_selection["variant"],
                                dropdown_info={
                                    "channel_id": self.dropdown_owner_view.dropdown_channel_id,
                                    "message_id": self.dropdown_owner_view.dropdown_message_id
                                }
                            )
                        )
                        try:
                            await select_interaction.message.delete()
                        except:
                            pass
                        return

                    if dropdown:
                        new_view = discord.ui.View(timeout=180)
                        dropdown.dropdown_owner_view = self.dropdown_owner_view
                        new_view.add_item(dropdown)
                        await select_interaction.response.edit_message(content="Select an option:", view=new_view)
                except Exception as e:
                    print(f"[Dropdown Callback Error] {type(e).__name__}: {e}")

        view = discord.ui.View(timeout=180)
        dropdown = DynamicDropdown(self.bot, self.user_id, "category", dropdown_owner_view=self)
        view.add_item(dropdown)
        await interaction.response.send_message("Select a category:", view=view, ephemeral=True)

        try:
            msg = await interaction.original_response()
            self.dropdown_channel_id = msg.channel.id
            self.dropdown_message_id = msg.id
        except:
            pass

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ...unchanged logic
        pass

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ...unchanged logic
        pass

class QuantityModal(discord.ui.Modal, title="Enter Quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=4)

    def __init__(self, bot, user_id, category, subcategory, item, variant, dropdown_info=None):  # <<<<<< FIXED
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant
        self.dropdown_info = dropdown_info  # <<<<<< FIXED

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
            economy_channel = self.bot.get_channel(config["economy_channel_id"])
            await economy_channel.send(f"{self.player.mention} thanks for your purchase at trader! Stay frosty out there survivor!")
            return await interaction.response.edit_message(content="Skipped. Public message sent.", view=None)

        await interaction.response.send_modal(ComboInputModal(self.bot, self.player, self.admin, choice))

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
            economy_channel = self.bot.get_channel(config["economy_channel_id"])
            await economy_channel.send(f"{self.player.mention} thanks for your purchase at trader! Stay frosty out there survivor!")
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
                        economy_channel = self.bot.get_channel(config["economy_channel_id"])
                        payment_msg = await economy_channel.send(
                            f"{player.mention} your order is ready for pick up.\n"
                            f"Please make a payment of ${total} to {admin_mention} and confirm this message with a ✅ once you’ve sent your payment!"
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

        elif message.id in self.awaiting_payment and str(reaction.emoji) == "✅":
            payment_data = self.awaiting_payment[message.id]
            if user.id != payment_data["player_id"]:
                await message.channel.send("mind your own orders!")
                return
            try:
                await message.clear_reaction("🔴")
                await message.edit(content=f"payment sent by {user.mention}")
                await message.add_reaction("✅")

                trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
                final_msg = await trader_channel.send(
                    f"{payment_data['admin_mention']}, {payment_data['player_mention']} sent their payment of ${payment_data['total']} "
                    f"for their order. Please confirm here with a ✅ to complete checkout/storage info!"
                )
                await final_msg.add_reaction("🔴")
                self.awaiting_final_confirmation[final_msg.id] = {
                    "player": self.bot.get_user(payment_data["player_id"]),
                    "admin": payment_data["admin"],
                    "total": payment_data["total"]
                }
                del self.awaiting_payment[message.id]
            except Exception as e:
                print(f"Error in player confirm: {e}")

        elif message.id in self.awaiting_final_confirmation and str(reaction.emoji) == "✅":
            try:
                await message.clear_reaction("🔴")
                await message.add_reaction("✅")
                await message.edit(content=f"{message.content}\n\npayment confirmed by {user.mention}")
                data = self.awaiting_final_confirmation[message.id]
                view = ui.View(timeout=20)
                view.add_item(StorageSelect(self.bot, data["player"], data["admin"], data["total"]))
                await message.channel.send("Select a storage unit or skip:", view=view)
                del self.awaiting_final_confirmation[message.id]
            except Exception as e:
                print(f"Error in storage confirmation: {e}")

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        session_manager.start_session(interaction.user.id)
        view = TraderView(self.bot, interaction.user.id)
        await interaction.response.send_message(
            "Buying session started! Use the buttons below to add items, submit, or cancel your order.",
            view=view,
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))

