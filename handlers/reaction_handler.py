import discord
import json
import asyncio
from discord.ui import View, Button

# Load config
with open("config.json") as f:
    config = json.load(f)

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
ADMIN_ROLE_IDS = config["admin_role_ids"]
ORDERS_FILE = "data/orders.json"

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

# --------- ORDER CONFIRMATION --------- #
async def handle_order_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[0]
    user_id = str(player.id)

    total_line = next((line for line in message.content.splitlines() if "Total:" in line), None)
    total_value = int(total_line.replace("**Total: $", "").replace("**", "").replace(",", "").strip())

    # Edit message
    new_content = message.content.replace(
        "Order for", f"✅ Confirmed by {admin_member.mention} — Order is ready for trader.\nOrder for"
    )
    await message.edit(content=new_content)

    # Notify player
    economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
    await economy_channel.send(
        f"{player.mention} your trader is ready for pick up! Please pay the trader {admin_member.mention} (${total_value:,}) to complete the order!"
    )

    # Store multi-order entry
    order_entry = {
        "type": "buy",
        "order_id": f"msg_{message.id}",
        "confirmed": True,
        "paid": False,
        "confirmed_by": admin_member.id,
        "total": total_value,
        "order_message_id": message.id,
        "payment_message_id": None
    }

    orders.setdefault(user_id, [])
    orders[user_id].append(order_entry)
    save_orders(orders)

# --------- SELL CONFIRMATION (New) --------- #
async def handle_sell_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[0]
    user_id = str(player.id)

    total_line = next((line for line in message.content.splitlines() if "Total Owed:" in line), None)
    total_value = int(total_line.replace("**Total Owed: $", "").replace("**", "").replace(",", "").strip())

    # Edit message
    new_content = message.content + f"\n✅ Confirmed by {admin_member.mention} — Sale payout complete."
    await message.edit(content=new_content)

    # Notify player
    economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
    await economy_channel.send(f"{player.mention} thanks for recycling your goods!")

    # Store order entry if needed
    order_entry = {
        "type": "sell",
        "order_id": f"msg_{message.id}",
        "confirmed": True,
        "paid": True,
        "confirmed_by": admin_member.id,
        "total": total_value,
        "order_message_id": message.id,
        "payment_message_id": None
    }

    orders.setdefault(user_id, [])
    orders[user_id].append(order_entry)
    save_orders(orders)

# --------- PAYMENT CONFIRMATION --------- #
async def handle_payment_confirmation(bot, message, admin_member):
    orders = load_orders()
    player = message.mentions[1]  # Second mention is player
    user_id = str(player.id)

    await message.edit(content=message.content + f"\n✅ Payment confirmed by {admin_member.mention}.")

    user_orders = orders.get(user_id, [])
    latest_unpaid = next((o for o in reversed(user_orders) if o["confirmed"] and not o["paid"]), None)
    if latest_unpaid:
        latest_unpaid["paid"] = True
        latest_unpaid["payment_message_id"] = message.id
        save_orders(orders)

    view = View(timeout=120)
    for i in range(1, 7):
        view.add_item(Button(label=f"Container {i}", style=discord.ButtonStyle.primary, custom_id=f"container_{i}"))
    for i in range(1, 5):
        view.add_item(Button(label=f"Shed {i}", style=discord.ButtonStyle.secondary, custom_id=f"shed_{i}"))
    view.add_item(Button(label="Skip", style=discord.ButtonStyle.danger, custom_id="skip_delivery"))

    await message.reply(f"{admin_member.mention} please choose where the order is stored:", view=view)

    async def on_button_click(interaction: discord.Interaction):
        if interaction.user.id != admin_member.id:
            await interaction.response.send_message("You aren’t authorized to complete this delivery.", ephemeral=True)
            return

        choice = interaction.data["custom_id"]
        if choice.startswith("container_") or choice.startswith("shed_"):
            location = choice.replace("_", " ").capitalize()
            await interaction.response.send_message(f"Please enter the 4-digit code for **{location}**:", ephemeral=True)

            def check_code(msg):
                return msg.author == admin_member and msg.channel == interaction.channel and msg.content.isdigit() and len(msg.content) == 4

            try:
                msg = await bot.wait_for("message", timeout=60.0, check=check_code)
                code = msg.content
                try:
                    await player.send(
                        f"{player.mention} thanks for your purchase!\nYour order is available at the trader **({location})**.\n"
                        f"Use code `{code}` to access your order.\n\n"
                        f"Please leave the lock with the same code when you're done.\nSee ya next time!"
                    )
                    await interaction.followup.send("DM sent to player.", ephemeral=True)
                except:
                    await interaction.followup.send("Failed to DM the player.", ephemeral=True)

            except asyncio.TimeoutError:
                await interaction.followup.send("Timed out waiting for code input.", ephemeral=True)

        elif choice == "skip_delivery":
            eco_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
            await eco_channel.send(f"{player.mention} thanks for your purchase! See ya next time!")
            await interaction.response.send_message("Player notified in economy channel.", ephemeral=True)

    bot.add_listener(on_button_click, "on_interaction")
