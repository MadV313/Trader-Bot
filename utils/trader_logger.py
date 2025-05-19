import os
import json

REACTION_LOG_PATH = os.path.join("data", "trader_reaction_log.json")

def load_reaction_log():
    if not os.path.exists(REACTION_LOG_PATH):
        return {}
    with open(REACTION_LOG_PATH, "r") as f:
        return json.load(f)

def save_reaction_log(data):
    with open(REACTION_LOG_PATH, "w") as f:
        json.dump(data, f, indent=2)
