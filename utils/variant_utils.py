# utils/variant_utils.py

def get_variants(item_data):
    """
    Returns all variant keys if present, otherwise returns ['Default'].
    :param item_data: dict or None
    :return: list of variant keys or ['Default']
    """
    if isinstance(item_data, dict):
        return list(item_data.keys())
    return ["Default"]

def variant_exists(variants, user_choice):
    """
    Checks if a user-specified variant exists in the list of variants (case-insensitive).
    :param variants: list of variant strings
    :param user_choice: string provided by user
    :return: True if variant exists, False otherwise
    """
    if not user_choice:
        return False
    choice = user_choice.lower()
    return any(v.lower() == choice for v in variants)

def normalize_variant(variant):
    """
    Normalizes a variant string to lowercase for consistent comparison.
    :param variant: string
    :return: normalized string
    """
    if not variant:
        return "default"
    return variant.strip().lower()

def get_variant_price(item_data, selected_variant):
    """
    Retrieves the price for a selected variant. Falls back to 'Default' if the specific variant is not found.
    :param item_data: dict
    :param selected_variant: str
    :return: price or None
    """
    if not isinstance(item_data, dict):
        return None

    normalized_variant = normalize_variant(selected_variant)
    for variant_key in item_data.keys():
        if normalize_variant(variant_key) == normalized_variant:
            return item_data.get(variant_key)
    
    return item_data.get("Default")
