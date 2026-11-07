#!/usr/bin/env python3
"""Build data/shows.json for The Moore (Seattle Theatre Group adapter).

Source grammar + classification live in ../common/stg.py (Paramount/Moore/
Neptune share one MEC calendar). One feed row PER PERFORMANCE (Broadway runs
explode; mec-start-time per occurrence carries the true curtain time — the
MEC JSON-LD clock is timezone-corrupt, only its date half is trusted).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill, spotify  # noqa: E402
from common import build as common_build  # noqa: E402
from common import stg  # noqa: E402

VENUE = "The Moore"
VENUE_ID = "moore"
VENUE_URL = "https://www.stgpresents.org/stg-venues/moore-theatre/"
SOURCE_URL = "https://www.stgpresents.org/calendar/"

if __name__ == "__main__":
    data = json.load(open(os.path.join(HERE, "cache", "stg.json")))
    shows, stats, dropped = stg.build_shows(
        data, VENUE_ID, common_build, apple_music, bill, spotify,
        os.path.join(HERE, "cache", "lookup.json"),
        os.path.join(HERE, "cache", "spotify_lookup.json"))
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    print(f"built {len(shows)} shows from {len(data['occurrences'])} occurrences")
    print("types:", stats["event_types"])
    print("with doors:", sum(1 for s in shows if s.get("doors")),
          "| with age:", sum(1 for s in shows if s.get("age_rating")),
          "| with support:", sum(1 for s in shows if s["support_artists"]))
    for d in dropped:
        print("  drop:", d)
    for et in ("music", "comedy", "other"):
        ex = [f"{s['date']} {[a['name'] for a in s['headline_artists']][:1]}"
              for s in shows if s["event_type"] == et][:3]
        print(f"  {et}: {ex}")
