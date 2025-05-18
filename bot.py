import discord
from discord.ext import commands
import os
import json
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Load config
try:
    config = json.loads(os.environ.get("CONFIG_JSON"))
except (TypeError, json.JSONDecodeError):
    with open("config.json") as f:
        config = json.load(f)

TOKEN = config["token"]
PREFIX = "/"
GUILD_ID = 1166441420643639348

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.guilds = True
INTENTS.members = True
INTENTS.reactions = True
INTENTS.messages = True
INTENTS.dm_messages = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)
extensions_loaded = False

from handlers.reaction_handler import setup_reaction_handler
from tasks.reminder_task import start_reminder_task
setup_reaction_handler(bot)

TRADER_STATS_FILE = os.path.join("data", "trader_stats.json")

# ✅ Trader of the Week Announcer
async def announce_trader_of_the_week():
    try:
        if not os.path.exists(TRADER_STATS_FILE):
            return

        with open(TRADER_STATS_FILE, "r") as f:
            stats = json.load(f)

        if not stats:
            return

        top_admin_id = max(stats, key=stats.get)
        count = stats[top_admin_id]
        top_admin = await bot.fetch_user(int(top_admin_id))

        # Reset stats
        with open(TRADER_STATS_FILE, "w") as f:
            json.dump({}, f)

        channel_id = int(config["trader_of_the_week_channel_id"])
        channel = bot.get_channel(channel_id)
        if channel:
            await channel.send(
                f"🏆 {top_admin.mention} was **Trader of the Week** with {count} confirmed orders!\n"
                "Be sure to thank them for supplying all your needs!"
            )
        print(f"[TOTW] Announced {top_admin} with {count} orders.")
    except Exception as e:
        print(f"[TOTW Error] {e}")

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
        synced = await bot.tree.sync()
        print(f"[TraderBot] Synced {len(synced)} global slash command(s).")
        guild = discord.Object(id=GUILD_ID)
        guild_synced = await bot.tree.sync(guild=guild)
        print(f"[TraderBot] Synced {len(guild_synced)} guild slash command(s).")
    except Exception as e:
        print(f"[TraderBot] Slash command sync failed: {type(e).__name__} - {e}")

    start_reminder_task(bot)

    # ✅ Trader of the Week Scheduler (every Sunday at 12 PM EST)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.create_task(announce_trader_of_the_week()),
        CronTrigger(day_of_week="sun", hour=12, minute=0, timezone="America/New_York")
    )
    scheduler.start()
    print("[TOTW] Scheduler started for every Sunday at 12 PM EST.")

@bot.event
async def on_disconnect():
    print("[TraderBot] Disconnected. Attempting automatic reconnect...")

@bot.event
async def on_resumed():
    print("[TraderBot] Successfully resumed session.")

@bot.command()
async def forcesync(ctx):
    try:
        synced = await bot.tree.sync()
        guild = discord.Object(id=GUILD_ID)
        guild_synced = await bot.tree.sync(guild=guild)
        await ctx.send(f"Slash commands synced! {len(synced)} global, {len(guild_synced)} guild.")
    except Exception as e:
        await ctx.send(f"Failed to sync: {type(e).__name__} - {e}")

if __name__ == "__main__":
    try:
        print("[TraderBot] Starting up...")
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("[TraderBot] Shutdown requested by user.")
    except Exception as e:
        print(f"[TraderBot] Unexpected error: {type(e).__name__} - {e}")
