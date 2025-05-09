import json
import os
from datetime import datetime
from utils import variant_utils

PRICE_FILE = os.path.join("data", "Final price list .json")
LOG_DIR = os.path.join("data", "logs")
FAILED_LOG_FILE = os.path.join(LOG_DIR, "failed_orders.log")
SUCCESS_LOG_FILE = os.path.join(LOG_DIR, "successful_orders.log")


def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_event(log_file, message):
    ensure_log_dir()
    with open(log_file, "a") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] {message}\n")


def load_price_data():
    if not os.path.exists(PRICE_FILE):
        raise FileNotFoundError("Price list file not found.")
    with open(PRICE_FILE, "r") as f:
        return json.load(f)["categories"]


def parse_order_lines(order_text, mode="buy"):
    data = load_price_data()
    parsed_items = []
    total = 0

    if not order_text.strip():
        return None, "No items provided in the order."

    for line_num, line in enumerate(order_text.strip().splitlines(), start=1):
        try:
            if " x" not in line:
                raise ValueError("Missing 'x' quantity format. Use 'item:variant xQuantity'.")

            left, quantity_str = line.rsplit(" x", 1)
            category, item, variant = map(str.strip, left.split(":"))
            quantity = int(quantity_str.strip())

            variant = variant or "Default"

            if category not in data:
                raise ValueError(f"Unknown category '{category}'.")

            if item not in data[category]:
                raise ValueError(f"Unknown item '{item}' in category '{category}'.")

            item_data = data[category][item]

            if isinstance(item_data, dict):
                variants = variant_utils.get_variants(item_data)
                if not variant_utils.variant_exists(variants, variant):
                    raise ValueError(f"Unknown variant '{variant}' for item '{item}'.")
                variant = next(v for v in variants if v.lower() == variant.lower())
                base_price = item_data[variant]
            else:
                if variant.lower() != "default":
                    raise ValueError(f"Item '{item}' does not support variants.")
                base_price = item_data

            price = round(base_price / 3) if mode == "sell" else base_price
            subtotal = price * quantity

            parsed_items.append({
                "category": category,
                "item": item,
                "variant": variant,
                "quantity": quantity,
                "price": price,
                "subtotal": subtotal
            })
            total += subtotal

        except Exception as e:
            log_event(FAILED_LOG_FILE, f"Line {line_num}: '{line}' — {type(e).__name__}: {e}")
            return None, f"Error on line {line_num}: '{line}' — {e}"

    items_summary = ", ".join(f"{i['quantity']}x {i['item']} ({i['variant']})" for i in parsed_items)
    log_event(SUCCESS_LOG_FILE, f"Order Parsed - Total: ${total:,} | Items: {items_summary}")

    return {"items": parsed_items, "total": total}, None
