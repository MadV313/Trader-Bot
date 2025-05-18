import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio
from utils import session_manager, variant_utils

# Load config from environment or fallback to file
try:
    config = json.loads(os.environ.get("CONFIG_JSON"))
except:
    with open("config.json") as f:
        config = json.load(f)

PRICE_FILE = os.path.join("data", "Final price list.json")
with open(PRICE_FILE, "r") as f:
    PRICE_DATA = json.load(f)["categories"]

# Helper Functions for navigating PRICE_DATA (same as trader.py)
def extract_label_and_emoji(text):
    import re
    match = re.search(r'(<:.*?:\d+>)', text)
    if match:
        emoji = match.group(1)
        label = text.split(' <')[0].strip()
        return label, emoji
    return text, None

# ... all helper functions: get_categories(), get_subcategories(), get_items_in_subcategory(), get_variants(), get_price() ...
# These will be the exact same from trader.py and included here for consistency

# Reuse TraderView, QuantityModal, BackButton, DynamicDropdown from trader.py without modification
# The only major difference is the flow in submit_order()

class SellTraderView(ui.View):
    def __init__(self, bot, user_id):
        super().__init__(timeout=600)
        self.bot = bot
        self.user_id = user_id
        self.cart_message = None
        self.ui_message = None

    # handle_add_item, remove_last_item, cancel_order - same as trader.py

    @discord.ui.button(label="Submit Sell Order", style=discord.ButtonStyle.success)
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

        # Message to trader channel
        submission = await trader_channel.send(
            f"<@&{config['trader_role_id']}> {interaction.user.mention} has submitted an order to **sell** items.\n"
            f"Please process payment and confirm using the button below.\n\n{summary}"
        )

        class ConfirmSellButton(ui.View):
            @ui.button(label="✅ Confirm Payout", style=discord.ButtonStyle.success)
            async def confirm_payout(self, i: discord.Interaction, b: discord.ui.Button):
                if not i.user.guild_permissions.manage_messages:
                    return await i.response.send_message("You do not have permission to confirm payouts.", ephemeral=True)
                await submission.edit(content=submission.content + f"\n\n✅ Confirmed by {i.user.mention}", view=None)
                await interaction.user.send(
                    "https://cdn.discordapp.com/attachments/1351365150287855739/1373723922809491476/Trader2-ezgif.com-video-to-gif-converter.gif\n\n"
                    "✅ **Thanks for using Trader! Stay frosty out there, survivor!**"
                )
                await i.response.send_message("✅ Payout confirmed.", ephemeral=True)

        await submission.edit(view=ConfirmSellButton())
        await interaction.response.send_message("✅ Sell order sent to trader channel.")
        try:
            await interaction.message.delete()
        except:
            pass

        session_manager.clear_session(interaction.user.id)
        session_manager.end_session(self.user_id)

        try:
            if self.ui_message:
                await self.ui_message.edit(view=None)
        except Exception as e:
            print(f"[UI Cleanup - Sell Submit] {e}")

class SellTraderCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="selltrader", description="Start a selling session with the trader.")
    async def selltrader(self, interaction: discord.Interaction):
        if interaction.channel.id != config["economy_channel_id"]:
            return await interaction.response.send_message("You must use this command in the #economy channel.")

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
            session = session_manager.get_session(interaction.user.id)
            session["cart_messages"] = [gif_msg.id, start_msg.id, ui_msg.id]
            session["start_msg_id"] = start_msg.id

            await interaction.response.send_message("Trader session moved to your DMs.")
        except Exception as e:
            print(f"[SellTrader DM Start Error] {e}")
            await interaction.response.send_message("Trader session moved to your DMs.")

async def setup(bot):
    await bot.add_cog(SellTraderCommand(bot))
