import discord
from discord.ext import commands
import os
import json
import asyncio

# Load config from environment variable or fallback to local file
try:
    config = json.loads(os.environ.get("CONFIG_JSON"))
except (TypeError, json.JSONDecodeError):
    with open("config.json") as f:
        config = json.load(f)

TOKEN = config["token"]
PREFIX = "/"

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.reactions = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
extensions_loaded = False  # Prevent reloading on reconnect

# Load reaction handlers
from handlers.reaction_handler import setup_reaction_handler
setup_reaction_handler(bot)

# Load background reminder tasks
from tasks.reminder_task import start_reminder_task

@bot.event
async def on_ready():
    global extensions_loaded

    print(f"[TraderBot] Logged in as {bot.user} (ID: {bot.user.id})")

    if not extensions_loaded:
        for file in os.listdir("./commands"):
            if file.endswith(".py"):
                try:
                    await bot.load_extension(f"commands.{file[:-3]}")
                    print(f"[TraderBot] Loaded extension: {file}")
                except Exception as e:
                    print(f"[TraderBot] Failed to load {file}: {e}")
        extensions_loaded = True
        print("[TraderBot] All command modules loaded.")

    try:
        synced = await bot.tree.sync()
        print(f"[TraderBot] Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"[TraderBot] Slash command sync failed: {e}")

    start_reminder_task(bot)

@bot.event
async def on_disconnect():
    print("[TraderBot] Disconnected. Attempting automatic reconnect...")

@bot.event
async def on_resumed():
    print("[TraderBot] Successfully resumed session.")

if __name__ == "__main__":
    try:
        print("[TraderBot] Starting up...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("[TraderBot] Shutdown requested by user. Exiting gracefully.")
    except Exception as e:
        print(f"[TraderBot] Unexpected error: {e}")
