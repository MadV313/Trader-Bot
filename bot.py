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
GUILD_ID = 1166441420643639348  # Your Discord Server ID

# ✅ Full intents for DM reactions and message handling
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.reactions = True
INTENTS.messages = True         # ✅ ensure bot can track messages
INTENTS.dm_messages = True      # ✅ crucial for DM reaction triggers

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
extensions_loaded = False

# Load reaction handler and reminder task
from handlers.reaction_handler import setup_reaction_handler
from tasks.reminder_task import start_reminder_task

setup_reaction_handler(bot)


@bot.event
async def on_ready():
    global extensions_loaded

    print(f"[TraderBot] Logged in as {bot.user} (ID: {bot.user.id})")

    if not extensions_loaded:
        for file in os.listdir("./commands"):
            if file.endswith(".py"):
                print(f"[TraderBot] Attempting to load: {file}")
                try:
                    await bot.load_extension(f"commands.{file[:-3]}")
                    print(f"[TraderBot] Loaded extension: {file}")
                except Exception as e:
                    print(f"[TraderBot] Failed to load {file}: {type(e).__name__} - {e}")
        extensions_loaded = True
        print("[TraderBot] All command modules loaded.")

    try:
        # Global Command Sync
        synced = await bot.tree.sync()
        print(f"[TraderBot] Synced {len(synced)} global slash command(s).")
        print(f"[TraderBot] Global Synced Commands: {[cmd.name for cmd in synced]}")

        # Force Guild Sync for Immediate Availability
        guild = discord.Object(id=GUILD_ID)
        guild_synced = await bot.tree.sync(guild=guild)
        print(f"[TraderBot] Synced {len(guild_synced)} guild slash command(s).")
        print(f"[TraderBot] Guild Synced Commands: {[cmd.name for cmd in guild_synced]}")

    except Exception as e:
        print(f"[TraderBot] Slash command sync failed: {type(e).__name__} - {e}")

    start_reminder_task(bot)


@bot.event
async def on_disconnect():
    print("[TraderBot] Disconnected. Attempting automatic reconnect...")


@bot.event
async def on_resumed():
    print("[TraderBot] Successfully resumed session.")


# Diagnostic Command: Force Slash Command Sync at Runtime
@bot.command()
async def forcesync(ctx):
    try:
        synced = await bot.tree.sync()
        guild = discord.Object(id=GUILD_ID)
        guild_synced = await bot.tree.sync(guild=guild)
        await ctx.send(f"Slash commands synced globally and to guild! {len(synced)} global, {len(guild_synced)} guild commands.")
        print(f"[TraderBot] Forced sync completed. {len(synced)} global, {len(guild_synced)} guild commands registered.")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {type(e).__name__} - {e}")
        print(f"[TraderBot] Forced sync failed: {type(e).__name__} - {e}")


if __name__ == "__main__":
    try:
        print("[TraderBot] Starting up...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("[TraderBot] Shutdown requested by user. Exiting gracefully.")
    except Exception as e:
        print(f"[TraderBot] Unexpected error: {type(e).__name__} - {e}")
