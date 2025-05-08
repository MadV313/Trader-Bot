import discord
from discord.ext import commands, tasks
import os
import json

# Load config
with open('config.json') as f:
    config = json.load(f)

TOKEN = config["token"]
PREFIX = "/"
INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.reactions = True
INTENTS.guilds = True
INTENTS.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=INTENTS)

# Load commands
@bot.event
async def on_ready():
    print(f"TraderBot is online as {bot.user}")
    from tasks.reminder_task import start_reminder_task
    start_reminder_task(bot)  # Start the hourly 12h scan

# Auto-load command files from /commands
for filename in os.listdir('./commands'):
    if filename.endswith('.py'):
        bot.load_extension(f'commands.{filename[:-3]}')

# Load reaction handler
from handlers.reaction_handler import setup_reaction_handler
setup_reaction_handler(bot)

bot.run(TOKEN)
