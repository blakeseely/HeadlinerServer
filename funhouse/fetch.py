"""Fetch the shared El Corazon / Funhouse Webflow calendar (common/ecfun.py)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import ecfun

TICKET_SRC = ecfun.BASE + "/calendar"

if __name__ == "__main__":
    cards = ecfun.fetch_calendar()
    cache = os.path.join(HERE, "cache"); os.makedirs(cache, exist_ok=True)
    json.dump({"cards": cards}, open(os.path.join(cache, "ec.json"), "w"))
    print(f"cards: {len(cards)}  span: {min(c['date'] for c in cards if c['date'])} -> {max(c['date'] for c in cards if c['date'])}")
