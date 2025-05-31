import discord
import json
import asyncio
import os
from datetime import datetime
from discord.ui import View, Button

# Load config
config = json.loads(os.environ.get("CONFIG_JSON"))

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
ADMIN_ROLE_IDS = config["admin_role_ids"]
ORDERS_FILE = "data/orders.json"
LOG_DIR = "data/logs"
LOG_FILE = os.path.join(LOG_DIR, "order_events.log")
EXPLOSIVE_ALERT_CHANNEL_ID = 1172556655150506075  # 💥 Public alert channel


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_event(event):
    ensure_log_dir()
    with open(LOG_FILE, "a") as log:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log.write(f"[{timestamp}] {event}\n")


def load_orders():
    try:
        with open(ORDERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}


def save_orders(data):
    with open(ORDERS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def setup_reaction_handler(bot):
    @bot.event
    async def on_raw_reaction_add(payload):
        if payload.channel_id != TRADER_ORDERS_CHANNEL_ID or str(payload.emoji.name) != "✅":
            return

        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member or not any(role.id in ADMIN_ROLE_IDS for role in member.roles):
            return

        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        if payload.user_id == bot.user.id:
            return  # Ignore bot reactions

        if "✅ Confirmed by" in message.content or "✅ Payment confirmed by" in message.content:
            return  # Already confirmed

        await message.remove_reaction("🔴", bot.user)
        await message.add_reaction("✅")

        if message.content.startswith("Order for"):
            await handle_order_confirmation(bot, message, member)
        elif message.content.startswith("<@") and "would like to sell" in message.content:
            await handle_sell_confirmation(bot, message, member)
        elif "payment has been sent from" in message.content:
            await handle_payment_confirmation(bot, message, member)


# --- ORDER CONFIRMATION ---
async def handle_order_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[0]
    user_id = str(player.id)

    total_line = next((line for line in message.content.splitlines() if "Total:" in line), None)
    total_value = int(total_line.replace("**Total: $", "").replace("**", "").replace(",", "").strip())

    new_content = message.content.replace(
        "Order for", f"✅ Confirmed by {admin_member.mention} — Order is ready for trader.\nOrder for"
    )
    await message.edit(content=new_content)

    economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
    await economy_channel.send(
        f"{player.mention}, your order is ready! Please pay {admin_member.mention} ${total_value:,} to complete it."
    )

    order_entry = {
        "type": "buy",
        "order_id": f"msg_{message.id}",
        "confirmed": True,
        "paid": False,
        "confirmed_by": admin_member.id,
        "total": total_value,
        "order_message_id": message.id,
        "payment_message_id": None,
        "items": []
    }

    orders.setdefault(user_id, []).append(order_entry)
    save_orders(orders)

    log_event(f"[ORDER CONFIRMED] Admin: {admin_member.id}, Player: {player.id}, Amount: {total_value}")


# --- SELL CONFIRMATION ---
async def handle_sell_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[0]
    user_id = str(player.id)

    total_line = next((line for line in message.content.splitlines() if "Total Owed:" in line), None)
    total_value = int(total_line.replace("**Total Owed: $", "").replace("**", "").replace(",", "").strip())

    new_content = message.content + f"\n✅ Confirmed by {admin_member.mention} — Sale payout complete."
    await message.edit(content=new_content)

    economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
    await economy_channel.send(f"{player.mention}, thanks for selling your gear!")

    order_entry = {
        "type": "sell",
        "order_id": f"msg_{message.id}",
        "confirmed": True,
        "paid": True,
        "confirmed_by": admin_member.id,
        "total": total_value,
        "order_message_id": message.id,
        "payment_message_id": None,
        "items": []
    }

    orders.setdefault(user_id, []).append(order_entry)
    save_orders(orders)

    log_event(f"[SELL CONFIRMED] Admin: {admin_member.id}, Player: {player.id}, Amount: {total_value}")


# --- PAYMENT CONFIRMATION ---
async def handle_payment_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[1]
    user_id = str(player.id)

    await message.edit(content=message.content + f"\n✅ Payment confirmed by {admin_member.mention}.")

    user_orders = orders.get(user_id, [])
    latest_unpaid = next((o for o in reversed(user_orders) if o["confirmed"] and not o["paid"]), None)
    if latest_unpaid:
        latest_unpaid["paid"] = True
        latest_unpaid["payment_message_id"] = message.id
        save_orders(orders)
        log_event(f"[PAYMENT CONFIRMED] Admin: {admin_member.id}, Player: {player.id}, Amount: {latest_unpaid['total']}")

    view = View(timeout=120)
    for i in range(1, 7):
        view.add_item(Button(label=f"Container {i}", style=discord.ButtonStyle.primary, custom_id=f"container_{i}"))
    for i in range(1, 5):
        view.add_item(Button(label=f"Shed {i}", style=discord.ButtonStyle.secondary, custom_id=f"shed_{i}"))
    view.add_item(Button(label="Skip", style=discord.ButtonStyle.danger, custom_id="skip_delivery"))

    await message.reply(f"{admin_member.mention}, choose where the order is stored:", view=view)

    async def on_button_click(interaction: discord.Interaction):
        if interaction.user.id != admin_member.id:
            await interaction.response.send_message("You aren’t authorized to complete this delivery.", ephemeral=True)
            return

        choice = interaction.data["custom_id"]
        if choice.startswith("container_") or choice.startswith("shed_"):
            location = choice.replace("_", " ").capitalize()
            await interaction.response.send_message(f"Enter the 4-digit code for **{location}**:", ephemeral=True)

            def check_code(msg):
                return (
                    msg.author == admin_member and
                    msg.channel == interaction.channel and
                    msg.content.isdigit() and
                    len(msg.content) == 4
                )

            try:
                msg = await bot.wait_for("message", timeout=60.0, check=check_code)
                code = msg.content
                try:
                    order_items = latest_unpaid.get("items", [])
                    item_details = "\n".join(
                        f"- {i['quantity']}x {i['item']} ({i['variant']})" for i in order_items
                    ) if order_items else "No item details available."

                    await player.send(
                        f"{player.mention}, your order is stored at **{location}**.\n\n"
                        f"**Items:**\n{item_details}\n\n"
                        f"Use code `{code}` to access it.\nPlease relock with the same code after collecting your gear."
                    )
                    await interaction.followup.send("Code and order details sent to player via DM.", ephemeral=True)
                except:
                    await interaction.followup.send("Failed to DM the player.", ephemeral=True)
            except asyncio.TimeoutError:
                await interaction.followup.send("Timed out waiting for code input.", ephemeral=True)

        elif choice == "skip_delivery":
        try:
            order_items = latest_unpaid.get("items", [])
            item_details = "\n".join(
                f"- {i['quantity']}x {i['item']} ({i['variant']})" for i in order_items
            ) if order_items else "No item details available."

            await player.send(
                f"{player.mention}, your order is ready for pickup!\n\n"
                f"**Items:**\n{item_details}\n\n"
                f"No storage unit was assigned. Please meet a trader to collect."
            )

            if not interaction.response.is_done():
                await interaction.response.send_message("✅ Skip acknowledged. Player notified via DM.", ephemeral=True)
            else:
                await interaction.followup.send("✅ Skip acknowledged. Player notified via DM.", ephemeral=True)

        except:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Skip acknowledged, but failed to DM the player.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Skip acknowledged, but failed to DM the player.", ephemeral=True)
        # 🔥 EXPLOSIVE ALERT — after delivery choice
        explosive_keywords = ["40mm Explosive Grenade", "M79", "Plastic Explosives", "Landmines", "Claymores"]
        explosive_count = 0
        for line in message.content.lower().splitlines():
            if any(keyword.lower() in line for keyword in explosive_keywords):
                if "x" in line:
                    try:
                        qty = int(line.split("x")[0].strip().replace("-", "").replace("*", ""))
                        explosive_count += qty
                    except:
                        explosive_count += 1  # fallback count
        if explosive_count >= 3:
            alert_channel = bot.get_channel(EXPLOSIVE_ALERT_CHANNEL_ID)
            if alert_channel:
                await alert_channel.send(
                    f"@everyone stay frosty! {player.mention} has just bought enough boom to waltz through your front door! 💥"
                )

    bot.add_listener(on_button_click, "on_interaction")
