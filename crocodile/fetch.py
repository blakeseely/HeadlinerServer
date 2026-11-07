"""Fetch The Crocodile's upcoming shows from TicketWeb (venue 10352) — the
venue's primary-ticket platform; its own Squarespace calendar is dead.
Shared mechanics + the header lesson live in ../common/ticketweb.py."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import ticketweb

TICKET_SRC = ticketweb.VENUE_URL

if __name__ == "__main__":
    try:
        evs = ticketweb.fetch_events()
    except ticketweb.TicketWebBlocked as e:
        print(f"WALLED: {e}", file=sys.stderr)
        sys.exit(2)   # update_all keeps the previous data; audit reports it
    cache = os.path.join(HERE, "cache"); os.makedirs(cache, exist_ok=True)
    json.dump({"events": evs}, open(os.path.join(cache, "ticketweb.json"), "w"))
    import collections
    dates = sorted(e["startDate"][:10] for e in evs)
    print(f"events: {len(evs)}  span: {dates[0]} -> {dates[-1]}")
    print("types:", collections.Counter(e.get('@type') for e in evs))
    print("status:", collections.Counter(ticketweb.map_status(e) for e in evs))
    print("performer shape:", type((evs[0].get('performer'))).__name__)
