# commands/tradepost.py
import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import time
from typing import Dict, Any, Optional, List

from utils import session_manager

# --- Config (ENV first, then file) ---
def _load_config() -> Dict[str, Any]:
    try:
        raw = os.environ.get("CONFIG_JSON")
        if raw:
            return json.loads(raw)
    except Exception as e:
        print(f"[tradepost] CONFIG_JSON parse error: {e}")
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)

CONFIG = _load_config()

ECONOMY_CHANNEL_ID = int(CONFIG["economy_channel_id"])

# Accept both keys and include your hard-coded fallback
def _resolve_tradepost_channel_id(cfg: Dict[str, Any]) -> int:
    cand = cfg.get("tradepost_orders_channel_id")
    if not cand:
        cand = cfg.get("tradepost_order_channel_id")  # your config.json key
    try:
        return int(cand)
    except Exception:
        return 1417541688133419118  # <-- fallback hard-coded as requested

TRADEPOST_ORDERS_CHANNEL_ID: int = _resolve_tradepost_channel_id(CONFIG)

TRADEPOST_CATALOG_PATH = CONFIG.get("tradepost_catalog_path", "data/tradepost_catalog.json")
SESSION_TIMEOUT_SECONDS = int(CONFIG.get("session_timeout_minutes", 15)) * 60

# --- Catalog lazy loader ---
_CATALOG_CACHE: Optional[Dict[str, Any]] = None  # {"categories": {...}}

def _load_catalog() -> Optional[Dict[str, Any]]:
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE
    try:
        with open(TRADEPOST_CATALOG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "categories" not in data:
                print("[tradepost] Catalog missing 'categories' root")
                return None
            _CATALOG_CACHE = data
            return _CATALOG_CACHE
    except FileNotFoundError:
        print(f"[tradepost] Catalog file not found: {TRADEPOST_CATALOG_PATH}")
        return None
    except json.JSONDecodeError as e:
        print(f"[tradepost] Catalog JSON error: {e}")
        return None
    except Exception as e:
        print(f"[tradepost] Catalog load error: {e}")
        return None

# --- Helpers that read from a provided catalog dict (no top-level file IO) ---
def tp_get_categories(cat: Dict[str, Any]) -> List[str]:
    return list(cat.get("categories", {}).keys())

def tp_get_items(cat: Dict[str, Any], category: str) -> List[str]:
    sub = cat.get("categories", {}).get(category, {})
    return [k for k, v in sub.items() if isinstance(v, dict)]

def tp_get_item_data(cat: Dict[str, Any], category: str, item: str) -> Dict[str, Any]:
    return cat.get("categories", {}).get(category, {}).get(item, {}) or {}

def tp_get_price_for_mode(item_data: dict, mode: str) -> Optional[int]:
    # item_data like {"Buy": 100, "Sell": 50} or {"Default": 200}
    if not isinstance(item_data, dict):
        return None
    if mode in item_data:
        return int(item_data[mode])
    if "Default" in item_data:
        return int(item_data["Default"])
    return None

def _fmt_price(n: int) -> str:
    return f"{n:,}"

def fmt_cart(items, mode: str):
    """
    items: list of dicts {category,item,qty,unit,total}
    mode: "Buy" or "Sell"
    """
    lines = [f"**Mode:** {mode}"]
    total = 0
    for it in items:
        # Show unit price too
        lines.append(f"• {it['item']} x{it['qty']} — { _fmt_price(it['total']) } (unit {_fmt_price(it['unit'])})")
        total += it['total']
    lines.append(f"\n**Cart Total:** {_fmt_price(total)}")
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

        # Update cart + then ack
        await interaction.response.defer()
        await self.view_ref.add_current_selection(q)
        await interaction.followup.send("Item added to cart", wait=True)

class DynamicDropdown(ui.Select):
    """
    level: "mode" | "category" | "item"
    """
    def __init__(self, bot, user_id: int, level: str, view_ref: "TradePostView"):
        self.bot = bot
        self.user_id = user_id
        self.level = level
        self.view_ref = view_ref

        cat = self.view_ref.catalog  # guaranteed present

        if level == "mode":
            opts = [discord.SelectOption(label="Buy"), discord.SelectOption(label="Sell")]
            ph = "Choose Buy or Sell"
        elif level == "category":
            opts = [discord.SelectOption(label=c) for c in tp_get_categories(cat)]
            ph = "Choose a category"
        else:
            # item — show price for the selected mode in the option description
            opts = []
            ph = "Choose an item"
            mode = self.view_ref.state.get("mode", "Buy")
            category = self.view_ref.state.get("category")
            if category:
                for item in tp_get_items(cat, category):
                    item_data = tp_get_item_data(cat, category, item)
                    price = tp_get_price_for_mode(item_data, mode)
                    if price is not None:
                        opts.append(
                            discord.SelectOption(
                                label=item,
                                description=f"{mode} price: {_fmt_price(price)}"
                            )
                        )
                    else:
                        opts.append(discord.SelectOption(label=item))
        super().__init__(placeholder=ph, options=opts, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)

        choice = self.values[0]

        if self.level == "item":
            # Open modal immediately (can't open a modal after deferring)
            self.view_ref.state["item"] = choice
            return await interaction.response.send_modal(QuantityModal(self.user_id, self.view_ref))

        # Other levels can defer and then refresh
        await interaction.response.defer()

        if self.level == "mode":
            self.view_ref.state = {"mode": choice}
            await self.view_ref.refresh(next_level="category")
        elif self.level == "category":
            self.view_ref.state["category"] = choice
            await self.view_ref.refresh(next_level="item")

class TradePostView(ui.View):
    def __init__(self, bot, user_id: int, catalog: Dict[str, Any]):
        super().__init__(timeout=SESSION_TIMEOUT_SECONDS)
        self.bot = bot
        self.user_id = user_id
        self.catalog = catalog
        self.state = {}  # keys: mode, category, item
        self.start_ts = time.time()
        self.msg: Optional[discord.Message] = None  # DM message we keep editing

        # Start at mode selection
        self.add_item(DynamicDropdown(self.bot, self.user_id, "mode", self))

    def attach_message(self, msg: discord.Message):
        self.msg = msg

    async def add_current_selection(self, qty: int):
        mode = self.state.get("mode")            # "Buy" / "Sell"
        c = self.state.get("category")
        i = self.state.get("item")
        item_data = tp_get_item_data(self.catalog, c, i)
        unit = tp_get_price_for_mode(item_data, mode or "Buy")
        if unit is None:
            # If somehow missing, just refresh view
            await self.refresh(next_level="item")
            return
        total = unit * qty

        # persist item into session cart
        session_manager.start_session(self.user_id)
        items = session_manager.get_session_items(self.user_id)
        items.append({"category": c, "item": i, "qty": qty, "unit": unit, "total": total})
        session_manager.set_session_items(self.user_id, items)

        # After add, jump back to item pick (keep same category)
        await self.refresh(next_level="item")

    async def refresh(self, next_level: str):
        # Remove only existing selects; keep the buttons (defined via @ui.button)
        for c in list(self.children):
            if isinstance(c, discord.ui.Select):
                self.remove_item(c)

        # progress: mode -> category -> item (re-add the single Select)
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
            body, _ = fmt_cart(items, mode)
            embed.description = body
            embed.set_footer(text=f"Items: {len(items)} | Type: tradepost")
        else:
            embed.description = "Use the dropdowns to add items."

        # Edit the persistent DM message
        if self.msg:
            try:
                await self.msg.edit(embed=embed, view=self)
            except Exception as e:
                print(f"[tradepost] Failed to edit DM message: {e}")

    # ----- Buttons (defined ONCE; do not add in refresh) -----

    @ui.button(label="◀️ Back to Category", style=discord.ButtonStyle.secondary, custom_id="tp_back_category", row=2)
    async def _back_category(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        await interaction.response.defer()
        mode = self.state.get("mode")
        self.state = {"mode": mode} if mode else {}
        await self.refresh(next_level="category")

    @ui.button(label="Submit Order", style=discord.ButtonStyle.success, custom_id="tp_submit", row=3)
    async def _submit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        await interaction.response.defer()

        items = session_manager.get_session_items(self.user_id)
        if not items:
            return await interaction.followup.send("Your cart is empty.")

        mode = self.state.get("mode", "Buy")
        body, total = fmt_cart(items, mode)
        order_text = (
            f"**Trade Post Order — {mode}**\n"
            f"**Customer:** {interaction.user.mention}\n\n"
            f"{body}\n\n"
            f"_please confirm this message with a ✅ when the order is ready_"
        )

        ch = interaction.client.get_channel(TRADEPOST_ORDERS_CHANNEL_ID)
        if not ch:
            return await interaction.followup.send("Trade Post orders channel not found.")

        msg = await ch.send(order_text)
        await msg.add_reaction("🔴")  # baseline behavior

        session_manager.log(f"[TradePost] mode={mode} user={interaction.user.id} total={total}")
        session_manager.end_session(self.user_id)

        await interaction.followup.send("📦 Your Trade Post order has been placed!")
        self.stop()

    @ui.button(label="Remove Last Item", style=discord.ButtonStyle.secondary, custom_id="tp_remove", row=3)
    async def _remove(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        await interaction.response.defer()

        items = session_manager.get_session_items(self.user_id)
        if not items:
            await interaction.followup.send("Cart is already empty.")
            return

        items.pop()
        session_manager.set_session_items(self.user_id, items)
        await self.refresh(next_level="item" if self.state.get("category") else "category")
        await interaction.followup.send("Item removed from cart")

    @ui.button(label="Cancel", style=discord.ButtonStyle.danger, custom_id="tp_cancel", row=3)
    async def _cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.user_id:
            return await interaction.response.send_message("Not your session.", ephemeral=True)
        await interaction.response.defer()
        session_manager.end_session(self.user_id)
        await interaction.followup.send("❌ Trade Post session canceled.")
        self.stop()

class TradePostCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tradepost", description="Open the Trade Post menu (economy channel only).")
    async def tradepost(self, interaction: discord.Interaction):
        # Restrict to economy channel
        if interaction.channel_id != ECONOMY_CHANNEL_ID:
            return await interaction.response.send_message(
                f"Use this in <#{ECONOMY_CHANNEL_ID}>.", ephemeral=True
            )

        # Load catalog lazily & safely
        catalog = _load_catalog()
        if not catalog:
            print("[tradepost] Cannot open UI — catalog failed to load.")
            return await interaction.response.send_message(
                "Trade Post catalog is unavailable right now. Please try again later.", ephemeral=True
            )

        # 1) Tell the channel we're moving to DMs
        await interaction.response.send_message(
            f"{interaction.user.mention} your Trade Post session has been moved to your DMs."
        )

        # 2) Open the DM session with interactive view
        try:
            view = TradePostView(self.bot, interaction.user.id, catalog)
            embed = discord.Embed(
                title="Trade Post",
                description="Select **Buy** or **Sell** to begin.",
                color=0x70a0f0
            )
            dm_msg = await interaction.user.send(embed=embed, view=view)
            view.attach_message(dm_msg)
        except discord.Forbidden:
            # DMs closed
            await interaction.followup.send(
                "I couldn’t DM you. Please enable DMs from server members and try again.", ephemeral=True
            )
        except Exception as e:
            print(f"[tradepost] Failed to open DM session: {e}")
            await interaction.followup.send(
                "Something went wrong opening your DM session.", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(TradePostCommand(bot))
    print("[tradepost] Cog loaded and command registered")
