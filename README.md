# SV13 TraderBot

A custom Discord bot for managing player orders, payments, and container/code deliveries in DayZ-style trader systems.

---

## Features

- `/trader`: Players submit a multi-line list of items
- Posts order to `#trader-orders` with 🔴 and admin pings
- Admins confirm orders with ✅, prompting player payment
- `/paytrader`: Player confirms payment manually
- Second ✅ triggers container/shed selection + DM with code
- 12-hour reminder system for incomplete orders
- Multi-order support per user
- Admin `/clearorders` command to reset all tracked orders

---

## Example `/trader` Input

```text
Clothes:Hunting Jacket:Autumn x2
Weapons:M70 TUNDRA:Black x1
Ammo:7.62x54:Default x3
