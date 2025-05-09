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
