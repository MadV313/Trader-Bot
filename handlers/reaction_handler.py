import discord
import json
import asyncio

with open("config.json") as f:
    config = json.load(f)

TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]
ECONOMY_CHANNEL_ID = config["economy_channel_id"]
ADMIN_ROLE_IDS = config["admin_role_ids"]

def setup_reaction_handler(bot):
    @bot.event
    async def on_raw_reaction_add(payload):
        if payload.channel_id != TRADER_ORDERS_CHANNEL_ID:
            return
        if str(payload.emoji.name) != "✅":
            return

        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member or not any(role.id in ADMIN_ROLE_IDS for role in member.roles):
            return  # Not an admin

        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Check if already confirmed
        if "✅ Confirmed by" in message.content or "✅ Payment confirmed by" in message.content:
            return

        # Remove 🔴, add ✅
        await message.remove_reaction("🔴", bot.user)
        await message.add_reaction("✅")

        # Detect if this is an order or a payment message
        if message.content.startswith("Order for"):
            # Extract player from message
            player_mention = message.content.splitlines()[0].split("Order for ")[1].rstrip(":")
            total_line = [line for line in message.content.splitlines() if "Total:" in line][0]
            total_value = total_line.replace("**Total: $", "").replace("**", "").replace(",", "").strip()

            # Edit message to confirm
            new_content = message.content.replace(
                "Order for", f"✅ Confirmed by {member.mention} — Order is ready for trader.\nOrder for"
            )
            await message.edit(content=new_content)

            # Notify player in economy channel
            economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
            await economy_channel.send(
                f"{player_mention} your trader is ready for pick up! Please pay the trader {member.mention} (${int(total_value):,}) to complete the order!"
            )
