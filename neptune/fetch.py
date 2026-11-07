"""Fetch the STG calendar (shared source for Paramount/Moore/Neptune) and
keep The Neptune Theatre occurrences. See ../../../common/stg.py."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import stg  # noqa: E402

VENUE = "The Neptune Theatre"

if __name__ == "__main__":
    cards = stg.fetch_occurrences()
    mine = [c for c in cards if c["venue"] == VENUE]
    dropped = sorted({c["venue"] for c in cards} - {VENUE})
    details = stg.details_for([c["slug"] for c in mine])
    out = {"venue": "neptune", "occurrences": mine, "details": details}
    cache = os.path.join(HERE, "cache")
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, "stg.json"), "w") as f:
        json.dump(out, f)
    print(f"cards all-venues: {len(cards)}  neptune: {len(mine)}  "
          f"details: {len(details)}/{len(set(c['slug'] for c in mine))}")
    if dropped:
        print("other locations present (not this feed):", dropped)
