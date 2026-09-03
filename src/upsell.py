"""Upsell suggestion logic based on catalog mappings."""
import json
import os

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "catalog.json")

def get_upsell_suggestion(item_description: str) -> dict | None:
    if not os.path.exists(CATALOG_PATH):
        return None
    with open(CATALOG_PATH, "r") as f:
        catalog = json.load(f)
    
    item_description_lower = item_description.lower()
    for key, suggestion in catalog.items():
        if key.lower() in item_description_lower:
            return suggestion
    return None
