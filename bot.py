import discord
from discord.ext import commands
import os
import json
import asyncio

# Load config from Railway environment variable
config = json.loads(os.environ.get("CONFIG_JSON"))

TOKEN = config["token"]
PREFIX = "/"

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.reactions = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
extensions_loaded = False  # Prevent reloading on reconnect

# Load handler (reaction listeners)
from handlers.reaction_handler import setup_reaction_handler
setup_reaction_handler(bot)

# Load background task
from tasks.reminder_task import start_reminder_task

@bot.event
async def on_ready():
    global extensions_loaded

    print(f"[TraderBot] Logged in as {bot.user}")

    if not extensions_loaded:
        for file in os.listdir("./commands"):
            if file.endswith(".py"):
                await bot.load_extension(f"commands.{file[:-3]}")
        extensions_loaded = True
        print("[TraderBot] All command modules loaded.")

    try:
        synced = await bot.tree.sync()
        print(f"[TraderBot] Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"[TraderBot] Slash command sync failed: {e}")

    start_reminder_task(bot)

# Run bot
if __name__ == "__main__":
    bot.run(TOKEN)
