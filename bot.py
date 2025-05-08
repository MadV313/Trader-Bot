import discord
from discord.ext import commands
import os
import json

# Load config
with open('config.json') as f:
    config = json.load(f)

TOKEN = config["token"]
PREFIX = "/"

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.reactions = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)

@bot.event
async def on_ready():
    print(f"[TraderBot] Logged in as {bot.user}")
    from tasks.reminder_task import start_reminder_task
    start_reminder_task(bot)

    # Sync application (slash) commands
    try:
        synced = await bot.tree.sync()
        print(f"[TraderBot] Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"[TraderBot] Slash command sync failed: {e}")

# Load slash command cogs
async def load_all_extensions():
    for file in os.listdir("./commands"):
        if file.endswith(".py"):
            await bot.load_extension(f"commands.{file[:-3]}")

# Load handler (reaction)
from handlers.reaction_handler import setup_reaction_handler
setup_reaction_handler(bot)

# Start bot
if __name__ == "__main__":
    import asyncio
    asyncio.run(load_all_extensions())
    bot.run(TOKEN)
