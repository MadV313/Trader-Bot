import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import os

config = json.loads(os.environ.get("CONFIG_JSON"))
TRADER_ORDERS_CHANNEL_ID = config["trader_orders_channel_id"]


class ClearChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="clear", description="Clears this DM or trader-orders channel.")
    async def clear(self, interaction: discord.Interaction):
        channel = interaction.channel
        user = interaction.user

        class ConfirmClearView(ui.View):
            def __init__(self):
                super().__init__(timeout=30)

            @ui.button(label="✅ Confirm Clear", style=discord.ButtonStyle.danger)
            async def confirm(self, interaction2: discord.Interaction, button: discord.ui.Button):
                if interaction2.user.id != user.id:
                    return await interaction2.response.send_message("This button isn’t for you.", ephemeral=True)

                await interaction2.response.edit_message(content="🧹 Clearing...", view=None)

                try:
                    if isinstance(channel, discord.DMChannel):
                        # Use larger history scope to catch ALL bot messages
                        await asyncio.sleep(1)  # Let the message register

                        async for msg in channel.history(limit=200):
                            if msg.author == self.bot.user:
                                await msg.delete()
                        print("[CLEAR] DM wiped.")
                    elif channel.id == TRADER_ORDERS_CHANNEL_ID:
                        await channel.purge(limit=200, check=lambda m: True)
                        print("[CLEAR] trader-orders channel wiped.")
                except Exception as e:
                    print(f"[CLEAR ERROR] {e}")

        # DM or correct channel — show confirmation
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


async def setup(bot):
    await bot.add_cog(ClearChat(bot))
