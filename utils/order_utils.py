import json
import os
from datetime import datetime

PRICE_FILE = os.path.join("data", "Final price list .json")
FAILED_LOG_FILE = os.path.join("logs", "failed_orders.log")

def load_price_data():
    if not os.path.exists(PRICE_FILE):
        raise FileNotFoundError("Price list file not found.")
    with open(PRICE_FILE, "r") as f:
        try:
            return json.load(f)["categories"]
        except Exception as e:
            raise ValueError(f"Failed to parse price list: {e}")

def log_failed_order(line_num, line, error):
    os.makedirs("logs", exist_ok=True)
    with open(FAILED_LOG_FILE, "a") as log_file:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file.write(f"[{timestamp}] Line {line_num}: '{line}' — {error}\n")

def parse_order_lines(order_text, mode="buy"):
    data = load_price_data()
    order_lines = order_text.strip().splitlines()
    parsed_items = []
    total = 0
    line_num = 0

    if not order_lines:
        return None, "No items provided in the order."

    for line in order_lines:
        line_num += 1
        try:
            if " x" not in line:
                raise ValueError("Missing 'x' quantity format")

            left, quantity_str = line.rsplit(" x", 1)
            category, item, variant = map(str.strip, left.split(":"))
            quantity = int(quantity_str.strip())

            if category not in data:
                raise ValueError(f"Unknown category '{category}'")
            if item not in data[category]:
                raise ValueError(f"Unknown item '{item}' in category '{category}'")

            # Handle variants case-insensitively
            if isinstance(data[category][item], dict):
                variant_options = [v.lower() for v in data[category][item].keys()]
                if variant.lower() not in variant_options:
                    raise ValueError(f"Unknown variant '{variant}' for item '{item}'")
                # Match correct case variant
                matched_variant = next(v for v in data[category][item].keys() if v.lower() == variant.lower())
                base_price = data[category][item][matched_variant]
                variant = matched_variant  # Normalize variant case
            else:
                if variant.lower() != "default":
                    raise ValueError(f"Item '{item}' does not support variants")
                base_price = data[category][item]

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
            log_failed_order(line_num, line, str(e))
            return None, f"Error on line {line_num}: '{line}' — {str(e)}"

    return {"items": parsed_items, "total": total}, None
