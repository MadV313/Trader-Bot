import discord
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

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("This isn’t your cart session.", ephemeral=True)

        categories = get_categories()
        options = [discord.SelectOption(label=c, value=c) for c in categories[:25]]

        class CategorySelect(discord.ui.Select):
            def __init__(self, bot, user_id):
                super().__init__(placeholder="Choose a category...", options=options)
                self.bot = bot
                self.user_id = user_id

            async def callback(self, select_interaction: discord.Interaction):
                selected_category = self.values[0]

                if selected_category in ["Weapons", "Clothes"]:
                    subcategories = get_subcategories(selected_category)
                    if not subcategories:
                        return await select_interaction.response.send_message("No subcategories found.", ephemeral=True)

                    sub_options = [discord.SelectOption(label=s, value=s) for s in subcategories[:25]]

                    class SubcategorySelect(discord.ui.Select):
                        def __init__(self, bot, user_id):
                            super().__init__(placeholder="Choose a subcategory...", options=sub_options)
                            self.bot = bot
                            self.user_id = user_id

                        async def callback(self, sub_select_interaction: discord.Interaction):
                            selected_subcategory = self.values[0]
                            items = get_items_in_subcategory(selected_category, selected_subcategory)
                            if not items:
                                return await sub_select_interaction.response.send_message("No items found for this subcategory.", ephemeral=True)

                            item_options = [
                                discord.SelectOption(
                                    label=f"{i} (${get_price(selected_category, selected_subcategory, i, 'Default') or 0:,})",
                                    value=i
                                ) for i in items[:25]
                            ]

                            class ItemSelect(discord.ui.Select):
                                def __init__(self, bot, user_id):
                                    super().__init__(placeholder="Choose an item...", options=item_options)
                                    self.bot = bot
                                    self.user_id = user_id

                                async def callback(self, item_interaction: discord.Interaction):
                                    selected_item = self.values[0]
                                    variants = get_variants(selected_category, selected_subcategory, selected_item)

                                    if len(variants) == 1 and variants[0] == "Default":
                                        await item_interaction.response.send_modal(
                                            QuantityModal(
                                                self.bot, self.user_id,
                                                selected_category, selected_subcategory,
                                                selected_item, "Default"
                                            )
                                        )
                                        return

                                    variant_options = [
                                        discord.SelectOption(
                                            label=f"{v} (${get_price(selected_category, selected_subcategory, selected_item, v) or 0:,})",
                                            value=v
                                        ) for v in variants[:25]
                                    ]

                                    class VariantSelect(discord.ui.Select):
                                        def __init__(self, bot, user_id):
                                            super().__init__(placeholder="Choose a variant...", options=variant_options)
                                            self.bot = bot
                                            self.user_id = user_id

                                        async def callback(self, variant_interaction: discord.Interaction):
                                            selected_variant = self.values[0]
                                            await variant_interaction.response.send_modal(
                                                QuantityModal(
                                                    self.bot, self.user_id,
                                                    selected_category, selected_subcategory,
                                                    selected_item, selected_variant
                                                )
                                            )

                                    variant_view = discord.ui.View(timeout=180)
                                    variant_view.add_item(VariantSelect(self.bot, self.user_id))
                                    await item_interaction.response.send_message("Select a variant:", view=variant_view, ephemeral=True)

                            item_view = discord.ui.View(timeout=180)
                            item_view.add_item(ItemSelect(self.bot, self.user_id))
                            await sub_select_interaction.response.send_message("Select an item:", view=item_view, ephemeral=True)

                    subcategory_view = discord.ui.View(timeout=180)
                    subcategory_view.add_item(SubcategorySelect(self.bot, self.user_id))
                    await select_interaction.response.send_message("Select a subcategory:", view=subcategory_view, ephemeral=True)

                else:
                    items = get_items_in_subcategory(selected_category, None)
                    if not items:
                        return await select_interaction.response.send_message("No items found for this category.", ephemeral=True)

                    item_options = [
                        discord.SelectOption(
                            label=f"{i} (${get_price(selected_category, None, i, 'Default') or 0:,})",
                            value=i
                        ) for i in items[:25]
                    ]

                    class ItemSelect(discord.ui.Select):
                        def __init__(self, bot, user_id):
                            super().__init__(placeholder="Choose an item...", options=item_options)
                            self.bot = bot
                            self.user_id = user_id

                        async def callback(self, item_interaction: discord.Interaction):
                            selected_item = self.values[0]
                            variants = get_variants(selected_category, None, selected_item)

                            if len(variants) == 1 and variants[0] == "Default":
                                await item_interaction.response.send_modal(
                                    QuantityModal(
                                        self.bot, self.user_id,
                                        selected_category, None,
                                        selected_item, "Default"
                                    )
                                )
                                return

                            variant_options = [
                                discord.SelectOption(
                                    label=f"{v} (${get_price(selected_category, None, selected_item, v) or 0:,})",
                                    value=v
                                ) for v in variants[:25]
                            ]

                            class VariantSelect(discord.ui.Select):
                                def __init__(self, bot, user_id):
                                    super().__init__(placeholder="Choose a variant...", options=variant_options)
                                    self.bot = bot
                                    self.user_id = user_id

                                async def callback(self, variant_interaction: discord.Interaction):
                                    selected_variant = self.values[0]
                                    await variant_interaction.response.send_modal(
                                        QuantityModal(
                                            self.bot, self.user_id,
                                            selected_category, None,
                                            selected_item, selected_variant
                                        )
                                    )

                            variant_view = discord.ui.View(timeout=180)
                            variant_view.add_item(VariantSelect(self.bot, self.user_id))
                            await item_interaction.response.send_message("Select a variant:", view=variant_view, ephemeral=True)

                    item_view = discord.ui.View(timeout=180)
                    item_view.add_item(ItemSelect(self.bot, self.user_id))
                    await select_interaction.response.send_message("Select an item:", view=item_view, ephemeral=True)

        category_view = discord.ui.View(timeout=180)
        category_view.add_item(CategorySelect(self.bot, self.user_id))
        await interaction.response.send_message("Select a category:", view=category_view, ephemeral=True)

    @discord.ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        total = sum(item['subtotal'] for item in items)
        summary = f"{interaction.user.mention} wants to purchase:\n"
        for item in items:
            item_name = item.get('item', 'Unknown')
            variant_name = item.get('variant', 'Default')
            summary += f"- {item_name} ({variant_name}) x{item['quantity']} = ${item['subtotal']:,}\n"
        summary += f"**Total: ${total:,}**\n\nplease confirm this message with a ✅ when the order is ready"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        order_msg = await trader_channel.send(summary)
        await order_msg.add_reaction("🔴")

        session_manager.clear_session(self.user_id)
        await interaction.response.send_message("Order submitted for admin approval!", ephemeral=True)
        try:
            await interaction.message.delete()
        except:
            pass

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return
        session_manager.clear_session(self.user_id)
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

            await interaction.response.send_message("Item added to cart.", ephemeral=True)
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

        # PHASE 2 — Player confirms payment
        elif message.id in self.awaiting_payment and str(reaction.emoji) == "✅":
            payment_data = self.awaiting_payment[message.id]
            if user.id != payment_data["player_id"]:
                await message.channel.send("mind your own orders!")
                return
            try:
                await message.clear_reaction("🔴")
                await message.edit(content=f"payment sent by {user.mention}")
                await message.add_reaction("✅")  # Moved after edit to ensure it sticks

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

        # PHASE 3 — Admin confirms payment and selects storage
        elif message.id in self.awaiting_final_confirmation and str(reaction.emoji) == "✅":
            try:
                await message.clear_reaction("🔴")
                await message.add_reaction("✅")
                await message.edit(content=f"{message.content}\n\npayment confirmed by {user.mention}")
                data = self.awaiting_final_confirmation[message.id]
                view = ui.View(timeout=180)
                view.add_item(StorageSelect(self.bot, data["player"], data["admin"], data["total"]))
                await message.channel.send("Select a storage unit or skip:", view=view)
                del self.awaiting_final_confirmation[message.id]
            except Exception as e:
                print(f"Error in storage confirmation: {e}")

    @app_commands.command(name="trader", description="Start a buying session with the trader.")
    async def trader(self, interaction: discord.Interaction):
        session_manager.start_session(interaction.user.id)
        await interaction.response.send_message(
            "Buying session started! Use the buttons below to add items, submit, or cancel your order.",
            view=TraderView(self.bot, interaction.user.id),
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(TraderCommand(bot))
    
