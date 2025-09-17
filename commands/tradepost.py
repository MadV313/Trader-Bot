# commands/tradepost.py
import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import time
import asyncio
from typing import Dict, Any, Optional, List, Tuple

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
ADMIN_ROLE_IDS: List[int] = [int(x) for x in CONFIG.get("admin_role_ids", [])]  # optional
TRADER_ROLE_ID: Optional[int] = int(CONFIG.get("trader_role_id", 0)) or None

# Accept both keys and include your hard-coded fallback for tradepost orders
def _resolve_tradepost_channel_id(cfg: Dict[str, Any]) -> int:
    cand = cfg.get("tradepost_orders_channel_id")
    if not cand:
        cand = cfg.get("tradepost_order_channel_id")  # legacy key in your config.json
    try:
        return int(cand)
    except Exception:
        return 1417541688133419118  # fallback as requested

TRADEPOST_ORDERS_CHANNEL_ID: int = _resolve_tradepost_channel_id(CONFIG)

# Payouts channel for SELL flow (falls back to orders channel if not provided)
PAYOUTS_CHANNEL_ID: int = int(CONFIG.get("payouts_channel_id", TRADEPOST_ORDERS_CHANNEL_ID))

TRADEPOST_CATALOG_PATH = CONFIG.get("tradepost_catalog_path", "data/tradepost_catalog.json")
SESSION_TIMEOUT_SECONDS = int(CONFIG.get("session_timeout_minutes", 15)) * 60

IRONFANG_GIF = ("https://cdn.discordapp.com/attachments/1351365150287855739/"
                "1417598686728421547/Ironfang.gif?ex=68cb1128&is=68c9bfa8&"
                "hm=b0ee86a58198b29c6cd8de30bbf18c1b7be6b2fd881cbb4039514848ad26eedb&")

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

# --- Helpers operating on catalog dict ---
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

def fmt_cart(items: List[dict], mode: str) -> Tuple[str, int]:
    """
    Accepts either Trader-style items:
      {"item","variant","quantity","subtotal", ...}
    or TradePost-style items:
      {"item","qty","unit","total", ...}
    """
    lines = [f"**Mode:** {mode}"]
    total = 0

    for it in items:
        if "subtotal" in it:  # trader schema
            qty = it.get("quantity", 1)
            unit = int(it["subtotal"]) // max(qty, 1)
            lines.append(f"• {it['item']} x{qty} — ${_fmt_price(it['subtotal'])} (unit ${_fmt_price(unit)})")
            total += int(it["subtotal"])
        else:  # legacy tradepost schema
            qty = it.get("qty", 1)
            unit = it.get("unit", 0)
            tot = it.get("total", unit * qty)
            lines.append(f"• {it['item']} x{qty} — ${_fmt_price(tot)} (unit ${_fmt_price(unit)})")
            total += int(tot)

    lines.append(f"\n**Cart Total:** ${_fmt_price(total)}")
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

        # Update cart + then ack (DMs don't support ephemerals; delete after 5s)
        await interaction.response.defer()
        await self.view_ref.add_current_selection(q)
        msg = await interaction.followup.send("Item added to cart", wait=True)
        async def _cleanup():
            await asyncio.sleep(5)
            try:
                await msg.delete()
            except Exception:
                pass
        asyncio.create_task(_cleanup())

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
                        opts.append(discord.SelectOption(label=item, description=f"{mode}: ${_fmt_price(price)}"))
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
            await self.refresh(next_level="item")
            return

        # Use Trader-style schema for compatibility with your session_manager helpers
        subtotal = unit * qty
        item_payload = {
            "category": c,
            "subcategory": None,      # tradepost doesn't use it, keep key for parity
            "item": i,
            "variant": "Default",
            "quantity": qty,
            "subtotal": subtotal,
        }

        session_manager.add_item(self.user_id, item_payload)  # do not restart session here
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

        # Cart summary (no session restart here)
        items = session_manager.get_session_items(self.user_id) or []
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

        items = session_manager.get_session_items(self.user_id) or []
        if not items:
            return await interaction.followup.send("Your cart is empty.")

        mode = self.state.get("mode", "Buy")
        body, total = fmt_cart(items, mode)

        if mode.lower() == "sell":
            # SELL -> post to payouts channel with staff confirmation instructions
            order_text = (
                f"**Trade Post Order — Sell**\n"
                f"**Customer:** {interaction.user.mention}\n\n"
                f"{body}\n\n"
                f"Please use the **/pay** command in <#{ECONOMY_CHANNEL_ID}> "
                f"and **staff should confirm here with a ✅ when the payout is complete**."
            )
            ch_id = PAYOUTS_CHANNEL_ID
        else:
            # BUY -> normal orders channel + staff confirm flow
            order_text = (
                f"**Trade Post Order — {mode}**\n"
                f"**Customer:** {interaction.user.mention}\n\n"
                f"{body}\n\n"
                f"_please confirm this message with a ✅ when the order is ready_"
            )
            ch_id = TRADEPOST_ORDERS_CHANNEL_ID

        ch = interaction.client.get_channel(ch_id)
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

        items = session_manager.get_session_items(self.user_id) or []
        if not items:
            msg = await interaction.followup.send("Your cart is empty.")
            async def _cleanup():
                await asyncio.sleep(5)
                try:
                    await msg.delete()
                except Exception:
                    pass
            asyncio.create_task(_cleanup())
            return

        items.pop()
        session_manager.set_session_items(self.user_id, items)
        await self.refresh(next_level="item" if self.state.get("category") else "category")

        msg = await interaction.followup.send("Item removed from cart")
        async def _cleanup():
            await asyncio.sleep(5)
            try:
                await msg.delete()
            except Exception:
                pass
        asyncio.create_task(_cleanup())

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
        # map: dm_payment_message_id -> {"player": Member/User, "admin_id": int}
        self.awaiting_payment: Dict[int, Dict[str, Any]] = {}
        # track completion messages in orders channel that still need staff ✅
        self.awaiting_final_confirm: Dict[int, Dict[str, Any]] = {}
        # simple dedupe
        self._handled_messages: set[int] = set()

    # ✅ Reaction handler (orders + payouts + DM confirms)
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        try:
            # -------------------------
            # Case A: staff reacts ✅ in orders channel to confirm a BUY order
            # -------------------------
            if payload.guild_id and payload.channel_id == TRADEPOST_ORDERS_CHANNEL_ID and str(payload.emoji.name) == "✅":
                guild = self.bot.get_guild(payload.guild_id)
                if not guild:
                    return
                member = guild.get_member(payload.user_id)
                if not member or member.bot:
                    return
                if ADMIN_ROLE_IDS and not any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                    return

                channel = self.bot.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                content_lower = message.content.lower()

                # A1: first confirm on the original order post (BUY)
                if "trade post order — buy" in content_lower and "please confirm this message with a ✅" in content_lower and "order confirmed by" not in content_lower:
                    try:
                        await message.clear_reaction("🔴")
                    except Exception:
                        pass
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass

                    new_text = f"{message.content}\n\nOrder confirmed by {member.mention}"
                    await message.edit(content=new_text)

                    # DM the customer requesting payment
                    if message.mentions:
                        player = message.mentions[0]
                        total_line = None
                        for line in message.content.splitlines():
                            if "cart total:" in line.lower():
                                total_line = line
                                break
                        total_amount = None
                        if total_line:
                            total_amount = total_line.split(":")[-1].strip().lstrip("$")

                        try:
                            dm = await player.send(
                                "📦 **Your Trade Post order is ready!**\n\n"
                                f"Please make a payment to {member.mention} for **${total_amount or 'the total'}**.\n"
                                f"Make sure to send payment in <#{ECONOMY_CHANNEL_ID}> (use /pay command and enter the amount total).\n\n"
                                "**Once paid, react to this message with a ✅ to confirm.**"
                            )
                            await dm.add_reaction("⚠️")
                            self.awaiting_payment[dm.id] = {
                                "player": player,
                                "admin_id": member.id
                            }
                        except Exception as e:
                            print(f"[tradepost] Failed to DM player payment prompt: {e}")
                    return

                # A2: staff reacts on the "payment confirmed" follow-up to finalize BUY
                if payload.message_id in self.awaiting_final_confirm and "✅" == str(payload.emoji.name):
                    if payload.message_id in self._handled_messages:
                        return
                    self._handled_messages.add(payload.message_id)

                    data = self.awaiting_final_confirm.pop(payload.message_id)
                    follow_msg = await channel.fetch_message(payload.message_id)
                    try:
                        await follow_msg.clear_reaction("🔴")
                    except Exception:
                        pass
                    try:
                        await follow_msg.add_reaction("✅")
                    except Exception:
                        pass

                    player = data.get("player")
                    # Final DM to customer with pickup coordinates + GIF
                    try:
                        embed = discord.Embed(
                            description=(
                                "✅ **Your order is ready for pick up!**\n"
                                "Location: 📍 **(0.24, 0.36)**\n\n"
                                "Ironfang thanks you for your business!"
                            ),
                            color=0x70a0f0
                        )
                        embed.set_image(url=IRONFANG_GIF)
                        await player.send(embed=embed)
                    except Exception as e:
                        print(f"[tradepost] Final DM failed: {e}")
                    return

            # -------------------------
            # Case B: **staff** reacts ✅ in PAYOUTS channel to confirm the SELL payout
            # -------------------------
            if payload.guild_id and payload.channel_id == PAYOUTS_CHANNEL_ID and str(payload.emoji.name) == "✅":
                guild = self.bot.get_guild(payload.guild_id)
                if not guild:
                    return
                member = guild.get_member(payload.user_id)
                if not member or member.bot:
                    return
                if ADMIN_ROLE_IDS and not any(r.id in ADMIN_ROLE_IDS for r in member.roles):
                    return

                channel = self.bot.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                content_lower = message.content.lower()

                # Only act on our SELL posts in payouts
                if "trade post order — sell" in content_lower and "confirm here" in content_lower:
                    try:
                        await message.clear_reaction("🔴")
                    except Exception:
                        pass
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass
                    try:
                        await message.edit(content=message.content + f"\n\nPayout confirmed by {member.mention}")
                    except Exception:
                        pass

                    # Final DM to seller confirming payout with GIF
                    try:
                        if message.mentions:
                            player = message.mentions[0]
                            embed = discord.Embed(
                                description=(
                                    "✅ **You have been properly paid for your wares!**\n"
                                    "Ironfang thanks you for your business!"
                                ),
                                color=0x70a0f0
                            )
                            embed.set_image(url=IRONFANG_GIF)
                            await player.send(embed=embed)
                    except Exception as e:
                        print(f"[tradepost] Sell final DM failed: {e}")
                    return

            # -------------------------
            # Case C: customer reacts ✅ in DM to the BUY payment prompt
            # -------------------------
            if payload.guild_id is None and str(payload.emoji.name) == "✅":
                # fetch the DM message
                channel = await self.bot.fetch_channel(payload.channel_id)
                if not isinstance(channel, (discord.DMChannel, discord.PartialMessageable)):
                    return
                try:
                    msg = await channel.fetch_message(payload.message_id)
                except Exception:
                    return
                if msg.author.id != self.bot.user.id:
                    return  # only handle our own payment prompt msgs
                if payload.message_id not in self.awaiting_payment:
                    return

                data = self.awaiting_payment.pop(payload.message_id)
                player = data["player"]

                # acknowledge in the DM thread
                try:
                    await msg.add_reaction("✅")
                    await msg.edit(content=msg.content + "\n\n✅ Payment confirmed! Please stand by.")
                except Exception:
                    pass

                # notify orders channel for final staff confirm (BUY)
                orders_ch = self.bot.get_channel(TRADEPOST_ORDERS_CHANNEL_ID)
                if orders_ch is None:
                    try:
                        orders_ch = await self.bot.fetch_channel(TRADEPOST_ORDERS_CHANNEL_ID)
                    except Exception:
                        orders_ch = None

                if orders_ch:
                    mention_role = f"<@&{TRADER_ROLE_ID}>" if TRADER_ROLE_ID else ""
                    notice = await orders_ch.send(
                        f"{mention_role} {player.mention} **has confirmed payment.** 💵\n"
                        "React with ✅ to complete the order and notify the customer."
                    )
                    await notice.add_reaction("🔴")
                    self.awaiting_final_confirm[notice.id] = {"player": player}
            # done
        except Exception as e:
            print(f"[tradepost] on_raw_reaction_add error: {e}")

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
            # Start the session ONCE here (do not restart it inside the view)
            session_manager.start_session(interaction.user.id)

            view = TradePostView(self.bot, interaction.user.id, catalog)
            embed = discord.Embed(
                title="Ironfang Trade Post",
                description=(
                    "Ironfang does not give for free. All trades must be fair:\n\n"
                    "• Food & Hides → exchanged for ammo, meds, or construction supplies.\n"
                    "• Crates → traded crate-for-crate.\n"
                    "• Special Items → bartered at agreed value.\n"
                    "• Coin is always welcome, no trade necessary."
                ),
                color=0x70a0f0
            )
            embed.set_image(url=IRONFANG_GIF)
            embed.set_footer(text="Select Buy or Sell to begin.")
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
