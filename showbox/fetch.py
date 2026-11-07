"""Fetch the AEG/AXS calendar for The Showbox and keep The Showbox rows.
Shared mechanics in ../common/aeg.py (offset-walked events_ajax whose bodies
are JSON-encoded HTML; no custom UA — neumos 406s Chrome UAs)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import aeg

BASE = "https://www.showboxpresents.com"
LABEL = 'The Showbox'
TICKET_SRC = "https://www.showboxpresents.com/events/"

if __name__ == "__main__":
    cards = aeg.fetch_calendar(BASE)
    mine = [c for c in cards if (LABEL is None or (c.get("venue") or "").strip() == LABEL)]
    cache = os.path.join(HERE, "cache"); os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, "aeg.json")
    prev = {}
    if os.path.exists(path):
        prev = json.load(open(path)).get("details", {})
    details = {}
    todo = []
    for c in mine:
        u = c.get("detail")
        if not u:
            continue
        if u in prev:
            details[u] = prev[u]
        else:
            todo.append(u)
    for u in todo:
        details[u] = aeg.fetch_detail(u)
    json.dump({"cards": mine, "details": details}, open(path, "w"))
    other = sorted({ (c.get('venue') or '-').strip() for c in cards } - {LABEL or '-'})
    print(f"cards: {len(cards)} -> {LABEL or 'all'}: {len(mine)}  details: {len(details)} ({len(todo)} new)")
    if other:
        print("  other venues in this calendar (not this feed):", other[:8])
