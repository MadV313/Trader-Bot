# SV13 Trader Bot

A fully automated Discord bot designed to manage trader transactions in a DayZ community. This bot supports structured buying/selling flows, admin approvals, payout confirmations, order reminders, trader statistics, and weekly reward tracking.

---

## 💼 Features

- **`/selltrader`**: Players initiate a sell session with full cart management (add, remove, cancel, submit).
- **Admin Payouts**: Admins confirm payments via buttons and reaction-based flows.
- **Ka-Ching! Feedback**: Celebratory GIFs are sent in DMs to confirm successful payouts.
- **Order Monitoring**: Bot scans and reminds traders about unconfirmed orders every 6 hours.
- **Trader of the Week**: Tracks and announces the top confirming trader weekly.
- **`/clear`**: Users or admins can clear bot messages from DMs or the trader-orders channel.
- **Full DM Cleanup**: All bot messages are auto-deleted 60 seconds after confirmation or 10 seconds after cancellation.

---

## 📦 Folder Structure

```
SV13 Trader Bot/
│
├── commands/
│   ├── selltrader.py               # Main selling flow and buttons
│   └── clear.py                    # Cleanup command for DMs or channel
│
├── handlers/
│   └── reaction_handler.py         # Handles reactions (e.g., payout confirmation)
│
├── tasks/
│   └── reminder_task.py            # Reminder task for unconfirmed orders
│
├── utils/
│   ├── session_manager.py          # Manages user cart sessions
│   ├── trader_logger.py            # Logs trader confirmations
│   └── variant_utils.py            # Handles variant formatting
│
├── data/
│   ├── trader_stats.json           # Tracks admin payout counts
│   ├── Final price list.json       # Contains all item prices
│   └── logs/
│       ├── reminder_events.log
│       └── session_activity.log
│
├── local-assets/                   # 📂 Local storage only (GIFs & emojis)
│   ├── ka-ching-money.gif
│   └── other emoji GIFs...
│
├── config.json                     # Bot configuration
└── bot.py                          # Main bot runner and startup logic
```

---

## ⚙️ Setup

### 1. Install Requirements

```bash
pip install -r requirements.txt
```

### 2. Create a `config.json` file (if not using an environment variable)

```json
{
  "token": "YOUR_BOT_TOKEN",
  "trader_orders_channel_id": 123456789012345678,
  "economy_channel_id": 123456789012345678,
  "mention_roles": ["<@&1234567890>", "<@&9876543210>"],
  "order_reminder_hours": 6,
  "trader_role_id": "1234567890",
  "trader_of_the_week_channel_id": 123456789012345678
}
```

---

## ❗ Manual Uploads Required

The bot uses animated GIFs and custom emoji links such as:

- `ka-ching-money.gif`
- `Trader2-ezgif.com-video-to-gif-converter.gif`

These **must be uploaded manually** to a private Discord channel, and their **CDN links** must be copied into the bot's command files where needed.

> ✅ The `local-assets/` folder is only for backup/local storage — the bot never loads files from there directly.

---

## 🕒 Scheduled Tasks

- **🔁 Unconfirmed Order Reminders**: `reminder_task.py` scans every `order_reminder_hours` (default 6) for any messages with a 🔴 emoji and sends a reminder ping if found.
- **🏆 Trader of the Week**: Runs every **Sunday at 12PM EST** and announces the top confirming trader.

---

## ✅ Slash Commands

| Command      | Description                                       |
|--------------|---------------------------------------------------|
| `/selltrader`| Start a sell session with buttons in your DMs.    |
| `/clear`     | Clears bot messages in DMs or trader-orders.      |

---

## 🔐 Required Permissions

- `Manage Messages` – for cleanup and confirmations  
- `Read Message History` – to scan for unconfirmed orders  
- `Send Messages` – for DMs and trader channels  
- `Add Reactions` – for reaction-based confirmations

---

## 🧹 DM Cleanup Behavior

- **60 seconds** after payout confirmation, all bot messages in DMs are deleted.
- **10 seconds** after cancellation, DM cleanup begins.

---

## 🏁 Launch Instructions

```bash
python bot.py
```

This will:

- Load all command modules  
- Sync slash commands globally and to your server  
- Start the unconfirmed order reminder loop  
- Launch the Trader of the Week scheduler  

---

## 📬 Support

Need help or want to use this bot on your server?  
Reach out via the **SV13 community Discord** for guidance or deployment inquiries.