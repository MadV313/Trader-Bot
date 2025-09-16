# commands/tradepost.py
import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import time

from utils import session_manager

# --- Config ---
try:
    CONFIG = json.loads(os.environ.get("CONFIG_JSON"))
except (TypeError, json.JSONDecodeError):
    with open("config.json") as f:
        CONFIG = json.load(f)

ECONOMY_CHANNEL_ID = CONFIG["economy_channel_id"]
TRADEPOST_ORDERS_CHANNEL_ID = CONFIG["tradepost_orders_channel_id"]
TRADEPOST_CATALOG_PATH = CONFIG.get("tradepost_catalog_path", "data/tradepost_catalog.json")
SESSION_TIMEOUT_SECONDS = CONFIG.get("session_timeout_minutes", 15) * 60

# --- Catalog ---
with open(TRADEPOST_CATALOG_PATH, "r") as f:
    TRADEPOST_DATA = json.load(f)["categories"]

def tp_get_categories():
    return list(TRADEPOST_DATA.keys())

def tp_get_items(category):
    sub = TRADEPOST_DATA.get(category, {})
    return [k for k, v in sub.items() if isinstance(v, dict)]

def tp_get_item_data(category, item):
    return TRADEPOST_DATA.get(category, {}).get(item, {})

def tp_get_price_for_mode(item_data: dict, mode: str):
    # item_data like {"Buy": 100, "Sell": 50} or {"Default": 200}
    if not isinstance(item_data, dict):
        return None
    if mode in item_data:
        return item_data[mode]
    if "Default" in item_data:
        return item_data["Default"]
    return None

def fmt_cart(items, mode: str):
    """
    items: list of dicts {category,item,qty,unit,total}
    mode: "Buy" or "Sell"
    """
    lines = [f"**Mode:** {mode}"]
    total = 0
    for it in items:
        lines.append(f"• {it['item']} x{it['qty']} — {it['total']}")
        total += it['total']
    lines.append(f"\n**Cart Total:** {total}")
    return "\n".join(lines), total

# ---------- UI ----------
class QuantityModal(ui.Modal, title="Quantity"):
    qty = ui.TextInput(label="Enter quantity", placeholder="e.g. 1", min_length=1, max_length=6)

    def __init__(self, user_id: int, view_ref: "TradePostView"):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        try:
            q = int(str(self.qty).strip())
            if q <= 0:
                raise ValueError
        except Exception:
            return await interaction.response.send_message("Enter a valid positive number.", ephemeral=True)

        await self.view_ref.add_current_selection(q, interaction)

class DynamicDropdown(ui.Select):
    """
    level: "mode" | "category" | "item"
    """
    def __init__(self, bot, user_id: int, level: str, view_ref: "TradePostView"):
        self.bot = bot
        self.user_id = user_id
        self.level = level
        self.view_ref = view_ref

        if level == "mode":
            opts = [discord.SelectOption(label="Buy"), discord.SelectOption(label="Sell")]
            ph = "Choose Buy or Sell"
        elif level == "category":
            opts = [discord.SelectOption(label=c) for c in tp_get_categories()]
            ph = "Choose a category"
        else:
            # item
            if not self.view_ref.state.get("category"):
                opts = []
            else:
                items = tp_get_items(self.view_ref.state["category"])
                opts = [discord.SelectOption(label=i) for i in items]
            ph = "Choose an item"

        super().__init__(placeholder=ph, options=opts, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        choice = self.values[0]
        if self.level == "mode":
            # Lock mode first
            self.view_ref.state = {"mode": choice}
            await self.view_ref.refresh(interaction, next_level="category")

        elif self.level == "category":
            self.view_ref.state["category"] = choice
            await self.view_ref.refresh(interaction, next_level="item")

        else:  # item
            self.view_ref.state["item"] = choice
            # ask qty immediately (no variant step; mode determines price)
            await interaction.response.send_modal(QuantityModal(self.user_id, self.view_ref))

class TradePostView(ui.View):
    def __init__(self, bot, user_id: int):
        super().__init__(timeout=SESSION_TIMEOUT_SECONDS)
        self.bot = bot
        self.user_id = user_id
        # state keys: mode, category, item
        self.state = {}
        self.start_ts = time.time()

        # Start at mode selection
        self.add_item(DynamicDropdown(self.bot, self.user_id, "mode", self))

    async def add_current_selection(self, qty: int, interaction: discord.Interaction):
        mode = self.state.get("mode")            # "Buy" / "Sell"
        c = self.state.get("category")
        i = self.state.get("item")
        item_data = tp_get_item_data(c, i)
        unit = tp_get_price_for_mode(item_data, mode or "Buy")
        if unit is None:
            return await interaction.response.send_message("No price found for that selection.", ephemeral=True)
        total = unit * qty

        # persist item into session cart
        session_manager.start_session(self.user_id)
        items = session_manager.get_session_items(self.user_id)
        items.append({"category": c, "item": i, "qty": qty, "unit": unit, "total": total})
        session_manager.set_session_items(self.user_id, items)

        # After add, jump back to item pick (keep same category). If you prefer jump to category, set next_level="category"
        await self.refresh(interaction, next_level="item", just_added=True)

    async def refresh(self, interaction: discord.Interaction, next_level: str, just_added: bool=False):
        # rebuild components
        for c in list(self.children):
            self.remove_item(c)

        # progress: mode -> category -> item
        if not self.state.get("mode"):
            self.add_item(DynamicDropdown(self.bot, self.user_id, "mode", self))
        elif not self.state.get("category"):
            self.add_item(DynamicDropdown(self.bot, self.user_id, "category", self))
        else:
            self.add_item(DynamicDropdown(self.bot, self.user_id, next_level, self))

        # Cart summary
        session_manager.start_session(self.user_id)
        items = session_manager.get_session_items(self.user_id)
        mode = self.state.get("mode", "Buy")

        title = f"Trade Post — {mode}"
        embed = discord.Embed(title=title, color=0x70a0f0)
        if items:
            body, total = fmt_cart(items, mode)
            embed.description = body
            embed.set_footer(text=f"Items: {len(items)} | Type: tradepost")
        else:
            embed.description = "Use the dropdowns to add items."

        # Controls
        self.add_item(discord.ui.Button(label="Submit Order", style=discord.ButtonStyle.success, custom_id="tp_submit"))
        self.add_item(discord.ui.Button(label="Remove Last Item", style=discord.ButtonStyle.secondary, custom_id="tp_remove"))
        self.add_item(discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="tp_cancel"))

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=self, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Submit Order", style=discord.ButtonStyle.success, custom_id="tp_submit", row=1)
    async def _submit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Your cart is empty.", ephemeral=True)

        mode = self.state.get("mode", "Buy")
        body, total = fmt_cart(items, mode)
        order_text = (
            f"**Trade Post Order — {mode}**\n"
            f"**Customer:** {interaction.user.mention}\n\n"
            f"{body}\n\n"
            f"_please confirm this message with a ✅ when the order is ready_"
        )

        # Post to Trade Post Orders channel
        ch = interaction.client.get_channel(TRADEPOST_ORDERS_CHANNEL_ID)
        if not ch:
            return await interaction.response.send_message("Trade Post orders channel not found.", ephemeral=True)

        msg = await ch.send(order_text)
        await msg.add_reaction("🔴")  # baseline behavior

        # minimal persistence / cleanup
        session_manager.log(f"[TradePost] mode={mode} user={interaction.user.id} total={total}")
        session_manager.end_session(self.user_id)

        await interaction.response.send_message("📦 Your Trade Post order has been placed!", ephemeral=True)
        self.stop()

    @ui.button(label="Remove Last Item", style=discord.ButtonStyle.secondary, custom_id="tp_remove", row=1)
    async def _remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.response.send_message("Cart is already empty.", ephemeral=True)
        removed = items.pop()
        session_manager.set_session_items(self.user_id, items)
        await interaction.response.send_message(f"Removed: {removed['item']}", ephemeral=True)
        # After removal, keep current category if set; otherwise rebuild from mode/category
        next_level = "item" if self.state.get("category") else ("category" if self.state.get("mode") else "mode")
        await self.refresh(interaction, next_level=next_level)

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="tp_cancel", row=1)
    async def _cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        session_manager.end_session(self.user_id)
        await interaction.response.send_message("❌ Trade Post session canceled.", ephemeral=True)
        self.stop()

class TradePostCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tradepost", description="Open the Trade Post menu (economy channel only).")
    async def tradepost(self, interaction: discord.Interaction):
        # Restrict to economy channel like existing flows
        if interaction.channel_id != ECONOMY_CHANNEL_ID:
            return await interaction.response.send_message(
                f"Use this in <#{ECONOMY_CHANNEL_ID}>.", ephemeral=True
            )

        # Start ephemeral UI in-channel
        session_manager.start_session(interaction.user.id)
        view = TradePostView(self.bot, interaction.user.id)
        embed = discord.Embed(
            title="Trade Post",
            description="Select **Buy** or **Sell** to begin.",
            color=0x70a0f0
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(TradePostCommand(bot))
