
# SV13 TraderBot

A custom Discord bot for managing player orders, payments, and trader interactions in DayZ-style trading systems.

---

## Features

- `/trader`: Interactive multi-item order system with dynamic category, item, and variant selections.
- `/selltrader`: Players sell multiple items directly to the trader.
- Posts orders to `#trader-orders` with 🔴 and admin pings.
- Admins confirm orders with ✅, triggering player payment instructions.
- `/paytrader`: Players confirm payment manually in `#economy`.
- Payment confirmation triggers container/shed selection + DM with access code.
- **Configurable** session timeouts and order reminders via `config.json`.
- 12-hour reminder system for incomplete orders (adjustable).
- Multi-order support per user with cart/session management.
- Admin `/clearorders` command to reset all tracked orders.
- Fully integrated with Discord Buttons, Selects, and Modals for seamless user experience.
- Hosted on Railway with dynamic environment configuration support.

---

## Example `/trader` Input (Manual Entry)

```
Clothes:Hunting Jacket:Autumn x2
Weapons:M70 TUNDRA:Black x1
Ammo:7.62x54:Default x3
```

> **Note:** Using the interactive UI is preferred. Manual text input is also supported.

---

## Configuration (`config.json` or Railway ENV)

```
{
  "token": "YOUR_BOT_TOKEN_HERE",
  "trader_orders_channel_id": 1370152442183946311,
  "economy_channel_id": 1173028001085145198,
  "admin_role_ids": [
    "1173052585830264832",
    "1173049392371085392",
    "1184921037830373468",
    "1370152166366642297"
  ],
  "mention_roles": [
    "<@&1173052585830264832>",
    "<@&1173049392371085392>",
    "<@&1184921037830373468>",
    "<@&1370152166366642297>"
  ],
  "session_timeout_minutes": 15,
  "order_reminder_hours": 12
}
```

---

## Bot Commands

| Command        | Description                          | Access      |
|----------------|--------------------------------------|-------------|
| `/trader`      | Start a new purchase order           | Player      |
| `/selltrader`  | Start a sell order                   | Player      |
| `/paytrader`   | Confirm payment to trader            | Player      |
| `/clearorders` | Clear all pending orders             | Admin Only  |

---

## Setup Instructions

1. Clone the repository and set up a virtual environment.
2. Add your bot token and other settings to `config.json` or set as `CONFIG_JSON` in Railway.
3. Install dependencies:

```
pip install -r requirements.txt
```

4. Run the bot:

```
python bot.py
```

---

## Hosting on Railway

1. Create a new Railway Project.
2. Add `CONFIG_JSON` as an environment variable with your full JSON configuration.
3. Set your start command to:

```
python bot.py
```

4. Deploy and enjoy automated hosting!
