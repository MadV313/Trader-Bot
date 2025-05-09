import json
import os

PRICE_FILE = os.path.join("data", "Final price list .json")

def load_price_data():
    if not os.path.exists(PRICE_FILE):
        raise FileNotFoundError("Price list file not found.")
    with open(PRICE_FILE, "r") as f:
        try:
            return json.load(f)["categories"]
        except Exception as e:
            raise ValueError(f"Failed to parse price list: {e}")

def parse_order_lines(order_text, mode="buy"):
    data = load_price_data()
    order_lines = order_text.strip().splitlines()
    parsed_items = []
    total = 0
    line_num = 0

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

            if isinstance(data[category][item], dict):
                if variant not in data[category][item]:
                    raise ValueError(f"Unknown variant '{variant}' for item '{item}'")
                base_price = data[category][item][variant]
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
            return None, f"Error on line {line_num}: '{line}' — {str(e)}"

    return {"items": parsed_items, "total": total}, None
