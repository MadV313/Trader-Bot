import json
import os

PRICE_FILE = os.path.join("data", "Final price list .json")

def load_price_data():
    with open(PRICE_FILE, "r") as f:
        return json.load(f)["categories"]

def parse_order_lines(order_text):
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

            # Validate
            if category not in data:
                raise ValueError(f"Unknown category '{category}'")
            if item not in data[category]:
                raise ValueError(f"Unknown item '{item}' in category '{category}'")
            if isinstance(data[category][item], dict):
                if variant not in data[category][item]:
                    raise ValueError(f"Unknown variant '{variant}' for item '{item}'")
                price = data[category][item][variant]
            else:
                # Some entries like "BLAZE": 50000 have no variants
                if variant.lower() != "default":
                    raise ValueError(f"Item '{item}' does not support variants")
                price = data[category][item]

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
