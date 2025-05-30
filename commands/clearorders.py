import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os
import asyncio

config = json.loads(os.environ.get("CONFIG_JSON"))
TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]

class ClearChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clear", description="Clears this DM or trader-orders channel.")
    async def clear(self, interaction: discord.Interaction):
        user = interaction.user
        channel = interaction.channel

        class ConfirmClearView(ui.View):
            def __init__(self):
                super().__init__(timeout=30)

            @ui.button(label="✅ Confirm Clear", style=discord.ButtonStyle.danger)
            async def confirm(self, i: discord.Interaction, button: discord.ui.Button):
                if i.user.id != user.id:
                    return await i.response.send_message("This button isn’t for you.", ephemeral=True)

                await i.response.edit_message(content="🧹 Clearing...", view=None)

                try:
                    if isinstance(channel, discord.DMChannel):
                        # Proven working logic
                        await asyncio.sleep(1)
                        dm_channel = i.user.dm_channel or await i.user.create_dm()
                        async for msg in dm_channel.history(limit=100):
                            if msg.author == i.client.user:
                                try:
                                    await msg.delete()
                                except:
                                    pass
                        print("[CLEAR] Bot messages cleared from DM.")
                    elif channel.id == TRADER_ORDERS_CHANNEL_ID:
                        await channel.purge(limit=200, check=lambda m: True)
                        print("[CLEAR] trader-orders channel wiped.")
                except Exception as e:
                    print(f"[CLEAR ERROR] {e}")

        # Trigger confirm prompt only if valid channel
        if isinstance(channel, discord.DMChannel) or channel.id == TRADER_ORDERS_CHANNEL_ID:
            await interaction.response.send_message(
                "⚠️ Are you sure you want to clear this?",
                view=ConfirmClearView(),
                ephemeral=False
            )
        else:
            await interaction.response.send_message(
                "❌ This command can only be used in a DM or the trader-orders channel.",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(ClearChat(bot))
