from discord.ext import commands
from discord import app_commands
from discord import ui
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
        self.cart_message = None

    async def update_cart_message(self, interaction: discord.Interaction):
        cart_items = session_manager.get_session_items(self.user_id)
        if not cart_items:
            return

        summary_lines = [
            f"{item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}"
            for item in cart_items
        ]
        total = sum(item['subtotal'] for item in cart_items)
        summary = "\n".join(summary_lines) + f"\n\nTotal: ${total:,}"

        if self.cart_message:
            await self.cart_message.edit(content=summary)
        else:
            self.cart_message = await interaction.user.send(summary)

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!", ephemeral=True)

        class DynamicDropdown(discord.ui.Select):
            def __init__(self, bot, user_id, view, stage, selected=None):
                self.bot = bot
                self.user_id = user_id
                self.view = view
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
                        dropdown = DynamicDropdown(self.bot, self.user_id, self.view, "subcategory", {"category": value})
                    else:
                        dropdown = DynamicDropdown(self.bot, self.user_id, self.view, "item", {"category": value})

                elif self.stage == "subcategory":
                    new_selection = self.selected.copy()
                    new_selection["subcategory"] = value
                    dropdown = DynamicDropdown(self.bot, self.user_id, self.view, "item", new_selection)

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
                                self.view
                            )
                        )
                        return
                    else:
                        dropdown = DynamicDropdown(self.bot, self.user_id, self.view, "variant", new_selection)

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
                            self.view
                        )
                    )
                    return
                else:
                    return

                new_view = discord.ui.View(timeout=180)
                new_view.add_item(dropdown)
                await select_interaction.response.edit_message(content="Select an option:", view=new_view)

        view = discord.ui.View(timeout=180)
        view.add_item(DynamicDropdown(self.bot, self.user_id, self, "category"))
        await interaction.response.send_message("Select a category:", view=view)

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        total = sum(item['subtotal'] for item in items)

        summary = (
            f"<@&{config['trader_role_id']}> a new order is ready to be processed!\n"
            f"{interaction.user.mention} wants to purchase:\n"
        )
        for item in items:
            name = item.get('item', 'Unknown')
            variant = item.get('variant', 'Default')
            quantity = item.get('quantity', 1)
            subtotal = item.get('subtotal', 0)
            summary += f"• {name} ({variant}) x{quantity} = ${subtotal:,}\n"
        summary += f"Total: ${total:,}\n\n"
        summary += "please confirm this message with a ✅ when the order is ready"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        order_msg = await trader_channel.send(summary)
        await order_msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Order submitted for admin approval!", ephemeral=True)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return
        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Order canceled.", ephemeral=True)

class QuantityModal(discord.ui.Modal, title="Enter Quantity"):
    quantity = discord.ui.TextInput(label="Quantity", placeholder="Enter a number", min_length=1, max_length=4)

    def __init__(self, bot, user_id, category, subcategory, item, variant, view):
        super().__init__()
        self.bot = bot
        self.user_id = user_id
        self.category = category
        self.subcategory = subcategory
        self.item = item
        self.variant = variant
        self.view = view

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

            await self.view.update_cart_message(interaction)
        except Exception:
            await interaction.response.send_message("Invalid quantity entered.", ephemeral=True)

@app_commands.command(name="trader", description="Start a buying session with the trader.")
async def trader(interaction: discord.Interaction):
    if interaction.channel.id != config["economy_channel_id"]:
        return await interaction.response.send_message("This command can only be used in the economy channel.", ephemeral=True)
    session_manager.start_session(interaction.user.id)
    view = TraderView(interaction.client, interaction.user.id)
    await interaction.user.send("Buying session started! Use the buttons below to add items, submit, or cancel your order.", view=view)
    await interaction.response.send_message("Trader session moved to your DMs.", ephemeral=True)

async def setup(bot):
    bot.tree.add_command(trader)
    
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
            trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
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
