import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio
from utils import session_manager, variant_utils

import re

# Load config
try:
    config = json.loads(os.environ.get("CONFIG_JSON"))
except:
    with open("config.json") as f:
        config = json.load(f)

PRICE_FILE = os.path.join("data", "Final price list.json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

# --- Helper Functions ---
def extract_label_and_emoji(text):
    match = re.search(r'(<:.*?:\d+>)', text)
    if match:
        emoji = match.group(1)
        label = text.split(' <')[0].strip()
        return label, emoji
    return text, None

def get_categories():
    return list(PRICE_DATA.keys())

def get_subcategories(category):
    sub_data = PRICE_DATA.get(category, {})
    return [key for key, val in sub_data.items() if isinstance(val, dict)]

def get_items_in_subcategory(category, subcategory):
    if subcategory:
        sub_data = PRICE_DATA.get(category, {}).get(subcategory, {})
    else:
        sub_data = PRICE_DATA.get(category, {})

    item_list = []
    for key, val in sub_data.items():
        if isinstance(val, dict):
            if all(isinstance(v, (int, float)) for v in val.values()):
                item_list.append(key)
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
            return [k for k, v in entry[item].items() if isinstance(v, (int, float))]
        else:
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

    async def on_submit(self, interaction: discord.Interaction):
        try:
            quantity = int(self.quantity.value)
            if quantity <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Invalid quantity.", ephemeral=True)

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

        items = session_manager.get_session_items(self.user_id)
        cart_total = sum(item["subtotal"] for item in items)
        lines = [f"• {item['item']} ({item['variant']}) x{item['quantity']} = ${item['subtotal']:,}" for item in items]
        summary = "\n".join(lines) + f"\n\n🛒 Cart Total: ${cart_total:,}"

        await interaction.response.defer()

        # Close any old dropdowns
        if self.view_ref.ui_message:
            try:
                await self.view_ref.ui_message.edit(view=None)
            except Exception as e:
                print(f"[Dropdown Cleanup Error] {e}")

        # Clean up previous dropdown message
        if hasattr(self.view_ref, "dropdown_message") and self.view_ref.dropdown_message:
            try:
                await self.view_ref.dropdown_message.delete()
                self.view_ref.dropdown_message = None
            except Exception as e:
                print(f"[Dropdown Cleanup Error] {e}")

        # Send or update cart message
        try:
            if self.view_ref.cart_message:
                await self.view_ref.cart_message.edit(content=summary)
            else:
                self.view_ref.cart_message = await interaction.followup.send(content=summary)
        except Exception as e:
            print(f"[Cart Display Error] {e}")
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
        view = discord.ui.View(timeout=600)
        view.add_item(dropdown)

        if prev_stage != "category":
            view.add_item(BackButton(self.bot, self.user_id, prev_stage, self.selected, self.view_ref))

        await interaction.response.edit_message(content="Back to previous selection:", view=view)

class DynamicDropdown(ui.Select):
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
            return [discord.SelectOption(label=extract_label_and_emoji(c)[0], value=c, emoji=extract_label_and_emoji(c)[1]) for c in get_categories()[:25]]
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

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        value = self.values[0]
        if self.stage == "category":
            category_name = value.lower()
            next_stage = "subcategory" if "clothes" in category_name else "item"
            dropdown = DynamicDropdown(self.bot, self.user_id, next_stage, {"category": value}, self.view_ref)
        elif self.stage == "subcategory":
            new_selection = self.selected.copy()
            new_selection["subcategory"] = value
            dropdown = DynamicDropdown(self.bot, self.user_id, "item", new_selection, self.view_ref)
        elif self.stage == "item":
            new_selection = self.selected.copy()
            item_data = json.loads(value)
            new_selection["item"] = item_data["item"]
            if item_data["variant"] == "Default":
                return await interaction.response.send_modal(
                    QuantityModal(self.bot, self.user_id, new_selection["category"], new_selection.get("subcategory"), new_selection["item"], "Default", self.view_ref)
                )
            dropdown = DynamicDropdown(self.bot, self.user_id, "variant", new_selection, self.view_ref)
        elif self.stage == "variant":
            new_selection = self.selected.copy()
            new_selection["variant"] = value
            return await interaction.response.send_modal(
                QuantityModal(self.bot, self.user_id, new_selection["category"], new_selection.get("subcategory"), new_selection["item"], new_selection["variant"], self.view_ref)
            )

        view = discord.ui.View(timeout=600)
        view.add_item(dropdown)
        if dropdown.stage != "category":
            view.add_item(BackButton(self.bot, self.user_id, dropdown.stage, self.selected, self.view_ref))

        await interaction.response.edit_message(content="Select an option:", view=view)
        try:
            self.view_ref.dropdown_message = await interaction.original_response()
        except Exception as e:
            print(f"[Dropdown Tracking Error] {e}")

class SellTraderView(ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = user_id
        self.cart_message = None
        self.ui_message = None

    @ui.button(label="Add Item", style=discord.ButtonStyle.primary)
    async def add_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Mind your own order!", ephemeral=True)
        view = ui.View(timeout=600)
        view.add_item(DynamicDropdown(self.bot, self.user_id, "category", view_ref=self))
        dropdown_msg = await interaction.response.send_message("Select a category:", view=view)
        self.dropdown_message = dropdown_msg

    @ui.button(label="Remove Last Item", style=discord.ButtonStyle.secondary)
    async def remove_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is already empty.", ephemeral=True)
        removed = items.pop()
        session_manager.set_session_items(self.user_id, items)
        summary = "\n".join([f"• {i['item']} ({i['variant']}) x{i['quantity']} = ${i['subtotal']:,}" for i in items])
        total = sum(i["subtotal"] for i in items)
        summary += f"\n\n🛒 Cart Total: ${total:,}" if items else "\n🛒 Cart is now empty."
        await interaction.response.send_message(f"🗑️ Removed {removed['item']}.", ephemeral=True)
        if self.cart_message:
            await self.cart_message.edit(content=summary)

    @ui.button(label="Cancel Order", style=discord.ButtonStyle.danger)
    async def cancel_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        session_manager.end_session(self.user_id)
        await interaction.response.send_message("❌ Order cancelled.", ephemeral=True)
        if self.ui_message:
            await self.ui_message.edit(content="Session closed.", view=None)

    @ui.button(label="Submit Order", style=discord.ButtonStyle.success)
    async def submit_order(self, interaction: discord.Interaction, button: discord.ui.Button):
        from discord.utils import escape_markdown
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        total = sum(i["subtotal"] for i in items)
        summary = "\n".join([f"• {i['item']} ({i['variant']}) x{i['quantity']} = ${i['subtotal']:,}" for i in items])
        summary += f"\n\n💰 **Total Payout: ${total:,}**"

        trader_channel = self.bot.get_channel(config["trader_orders_channel_id"])
        if not trader_channel:
            return await interaction.response.send_message("Trader channel not found.")

        alert_msg = await trader_channel.send(
            f"<@&{config['trader_role_id']}> {interaction.user.mention} has submitted an order to approve for sale!\n"
            f"Please send payment and confirm here once done!"
        )

        class ConfirmSellView(ui.View):
            def __init__(self, buyer, alert_msg):
                super().__init__(timeout=None)
                self.buyer = buyer
                self.alert_msg = alert_msg

            @ui.button(label="✅ Confirm Payout", style=discord.ButtonStyle.success)
            async def confirm(self, i: discord.Interaction, button: discord.ui.Button):
                if not i.user.guild_permissions.manage_messages:
                    return await i.response.send_message("You do not have permission.", ephemeral=True)

                await self.alert_msg.edit(content=self.alert_msg.content + f"\n\n✅ Confirmed by {i.user.mention}")

                # ✅ Log trader confirmation
                from utils import trader_logger  # ensure this import is at the top of your file
                log_data = trader_logger.load_reaction_log()
                admin_id = str(i.user.id)
                log_data[admin_id] = log_data.get(admin_id, 0) + 1
                trader_logger.save_reaction_log(log_data)

                try:
                    await self.buyer.send(
                        "https://cdn.discordapp.com/attachments/1351365150287855739/1373723922809491476/Trader2-ezgif.com-video-to-gif-converter.gif\n\n"
                        "✅ **The payment for your used wears has been sent!**"
                    )
                except:
                    pass

                await i.response.send_message("✅ Payout confirmed.", ephemeral=True)

        await trader_channel.send(summary, view=ConfirmSellView(interaction.user, alert_msg))
        await interaction.response.send_message("✅ Sell order submitted and sent to trader channel.", ephemeral=True)
        session_manager.end_session(self.user_id)
        if self.ui_message:
            await self.ui_message.edit(view=None)

class SellTraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dropdown_message = None
        
    @app_commands.command(name="selltrader", description="Start a selling session with the trader.")
    async def selltrader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("This command must be used in the economy channel.", ephemeral=True)
        try:
            gif_msg = await interaction.user.send("https://cdn.discordapp.com/attachments/1371698983604326440/1373359533304582237/ezgif.com-optimize.gif")
            start_msg = await interaction.user.send(
                "┏━━━━━━━━━━━━━━━━━━━━━━━┓\n"
                "💰 **SELLING SESSION STARTED!**\n"
                "┗━━━━━━━━━━━━━━━━━━━━━━━┛\n"
                "Use the buttons below to add/remove items,\nsubmit, or cancel your sell order."
            )
            view = SellTraderView(self.bot, interaction.user.id)
            ui_msg = await interaction.user.send(view=view)
            view.ui_message = ui_msg
            view.start_message = start_msg
            session_manager.start_session(interaction.user.id)
            await interaction.response.send_message("✅ Sell session moved to your DMs.", ephemeral=True)
        except Exception as e:
            print(f"[SellTrader DM Error] {e}")
            await interaction.response.send_message("❌ Failed to start sell session in DMs.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(SellTraderCommand(bot))
                                                        
