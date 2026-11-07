#!/usr/bin/env python3
"""Build data/shows.json for El Corazón from the shared El Corazon/Funhouse
calendar (common/ecfun.py; venue field splits the two feeds)."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill, spotify, build as common_build, ecfun

VENUE = "El Corazón"
VENUE_ID = "elcorazon"
VENUE_URL = "https://www.elcorazonseattle.com"
SOURCE_URL = ecfun.BASE + "/calendar"
NEEDLE = "corazon"
CANONICAL = {"el corazon", "the el corazon"}

if __name__ == "__main__":
    data = json.load(open(os.path.join(HERE, "cache", "ec.json")))
    shows, stats = ecfun.build_shows(
        data["cards"], NEEDLE, common_build, apple_music, bill, spotify,
        os.path.join(HERE, "cache", "lookup.json"),
        os.path.join(HERE, "cache", "spotify_lookup.json"), canonical=CANONICAL)
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    print(f"built {len(shows)} shows")
    print("doors:", sum(1 for s in shows if s.get("doors")), "| show_time:", sum(1 for s in shows if s.get("show_time")), "| support:", sum(1 for s in shows if s["support_artists"]), "| multi:", sum(1 for s in shows if s.get("multi_artist")))
