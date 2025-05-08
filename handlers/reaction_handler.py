import discord
import json
import asyncio

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
        if payload.channel_id != TRADER_ORDERS_CHANNEL_ID:
            return
        if str(payload.emoji.name) != "✅":
            return

        guild = bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)
        if not member or not any(role.id in ADMIN_ROLE_IDS for role in member.roles):
            return

        channel = bot.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)

        # Ignore bot reacting to itself
        if payload.user_id == bot.user.id:
            return

        # Already confirmed?
        if "✅ Confirmed by" in message.content or "✅ Payment confirmed by" in message.content:
            return

        await message.remove_reaction("🔴", bot.user)
        await message.add_reaction("✅")

        orders = load_orders()

        # HANDLE ORDER CONFIRMATION
        if message.content.startswith("Order for"):
            player_mention = message.content.splitlines()[0].split("Order for ")[1].rstrip(":")
            total_line = [line for line in message.content.splitlines() if "Total:" in line][0]
            total_value = total_line.replace("**Total: $", "").replace("**", "").replace(",", "").strip()

            # Edit message
            new_content = message.content.replace(
                "Order for", f"✅ Confirmed by {member.mention} — Order is ready for trader.\nOrder for"
            )
            await message.edit(content=new_content)

            # Notify player
            economy_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
            await economy_channel.send(
                f"{player_mention} your trader is ready for pick up! Please pay the trader {member.mention} (${int(total_value):,}) to complete the order!"
            )

            # Save to orders.json
            user_id = message.mentions[0].id
            orders[str(user_id)] = {
                "confirmed": True,
                "paid": False,
                "confirmed_by": member.id,
                "total": int(total_value),
                "order_message_id": message.id
            }
            save_orders(orders)
            return

        # HANDLE PAYMENT CONFIRMATION
        if "payment has been sent from" in message.content:
            player_mention = message.mentions[1]
            admin_mention = message.mentions[0]

            # Edit message to confirm
            new_content = message.content + f"\n✅ Payment confirmed by {member.mention}."
            await message.edit(content=new_content)

            # Prompt with buttons
            view = discord.ui.View(timeout=120)

            for i in range(1, 7):
                view.add_item(discord.ui.Button(label=f"Container {i}", style=discord.ButtonStyle.primary, custom_id=f"container_{i}"))
            for i in range(1, 5):
                view.add_item(discord.ui.Button(label=f"Shed {i}", style=discord.ButtonStyle.secondary, custom_id=f"shed_{i}"))
            view.add_item(discord.ui.Button(label="Skip", style=discord.ButtonStyle.danger, custom_id="skip_delivery"))

            await message.reply(f"{member.mention} please choose where the order is stored:", view=view)

            async def interaction_check(interaction: discord.Interaction) -> bool:
                return interaction.user.id == member.id

            @bot.event
            async def on_interaction(interaction: discord.Interaction):
                if not interaction_check(interaction):
                    await interaction.response.send_message("You aren't authorized to respond to this.", ephemeral=True)
                    return

                choice = interaction.data["custom_id"]
                user_id = str(player_mention.id)
                if choice.startswith("container_") or choice.startswith("shed_"):
                    location = choice.replace("_", " ").capitalize()

                    await interaction.response.send_message(f"Enter the 4-digit code for {location}:", ephemeral=True)

                    def check(msg):
                        return msg.author == member and msg.channel == interaction.channel and msg.content.isdigit() and len(msg.content) == 4

                    try:
                        msg = await bot.wait_for("message", timeout=60.0, check=check)
                        code = msg.content

                        # Send DM to player
                        try:
                            await player_mention.send(
                                f"{player_mention.mention} thanks for your purchase!\n"
                                f"Your order is available at the trader **({location})**.\n"
                                f"Use code `{code}` to access your order.\n\n"
                                f"Please leave the lock with the same code when you're done.\nSee ya next time!"
                            )
                            await interaction.followup.send("DM sent to player.", ephemeral=True)
                        except:
                            await interaction.followup.send("Could not DM the player.", ephemeral=True)

                    except asyncio.TimeoutError:
                        await interaction.followup.send("Timed out waiting for code input.", ephemeral=True)

                elif choice == "skip_delivery":
                    eco_channel = bot.get_channel(ECONOMY_CHANNEL_ID)
                    await eco_channel.send(f"{player_mention.mention} thanks for your purchase! See ya next time!")
                    await interaction.response.send_message("Player notified in economy channel.", ephemeral=True)
