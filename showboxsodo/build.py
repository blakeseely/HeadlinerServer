#!/usr/bin/env python3
"""Build data/shows.json for Showbox SoDo (AEG/AXS adapter, shared grammar in
../common/aeg.py). Music-only house: every card is a concert; support bills
come from the card h4/tagline through the proven parse_bill grammar."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill, spotify, build as common_build, aeg

VENUE = "Showbox SoDo"
VENUE_ID = "showboxsodo"
VENUE_URL = "https://www.showboxpresents.com"
SOURCE_URL = "https://www.showboxpresents.com/events/"
LABEL = 'Showbox SoDo'

if __name__ == "__main__":
    data = json.load(open(os.path.join(HERE, "cache", "aeg.json")))
    shows, stats = aeg.build_shows(
        data["cards"], data.get("details", {}), LABEL,
        common_build, apple_music, bill, spotify,
        os.path.join(HERE, "cache", "lookup.json"),
        os.path.join(HERE, "cache", "spotify_lookup.json"))
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    print(f"built {len(shows)} shows from {len(data['cards'])} cards")
    print("doors:", sum(1 for s in shows if s.get("doors")),
          "| show_time:", sum(1 for s in shows if s.get("show_time")),
          "| age:", sum(1 for s in shows if s.get("age_rating")),
          "| support:", sum(1 for s in shows if s["support_artists"]))
    import collections
    print("status:", collections.Counter(s["ticket_status"] for s in shows))
    for s in shows[:5]:
        print("  ", s["date"], [a["name"] for a in s["headline_artists"]][:1], "+", len(s["support_artists"]), "sup")
