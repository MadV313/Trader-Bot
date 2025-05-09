import json
import os

PRICE_FILE = os.path.join("data", "Final price list .json")

def load_price_data():
    with open(PRICE_FILE, "r") as f:
        return json.load(f)["categories"]

def parse_order_lines(order_text, mode="buy"):
    data = load_price_data()
    order_lines = order_text.strip().splitlines()
    parsed_items = []
    total = 0
    line_num = 0

    for line in order_lines:
        line_num += 1
        try:
            # Format: Category:Item:Variant xQuantity
            if " x" not in line:
                raise ValueError("Missing 'x' quantity format")

            left, quantity_str = line.rsplit(" x", 1)
            category, item, variant = map(str.strip, left.split(":"))
            quantity = int(quantity_str.strip())

            # Validate structure
            if category not in data:
                raise ValueError(f"Unknown category '{category}'")
            if item not in data[category]:
                raise ValueError(f"Unknown item '{item}' in category '{category}'")

            # Handle variant or default
            if isinstance(data[category][item], dict):
                if variant not in data[category][item]:
                    raise ValueError(f"Unknown variant '{variant}' for item '{item}'")
                base_price = data[category][item][variant]
            else:
                if variant.lower() != "default":
                    raise ValueError(f"Item '{item}' does not support variants")
                base_price = data[category][item]

            # Adjust price if selling
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
