"""Venue registry — the ONE place to add a new theater.

Adding a venue:
  1. create a `<key>/` directory with a `build.py` adapter (see independent/
     and castro/ for the pattern) and its `viewer/` is served from common/.
  2. add one entry here. `serve.py` discovers it and renders the picker card.

Each entry:
  key      registry key + URL path segment (== directory name)
  name     display name (picker card + reviewer header)
  city     display subtitle
  dir      path of the venue directory (absolute, resolved once)
  has_apple_music  run the Apple Music lookup for this venue
  fetch_cmd  the venue's schedule-capture command (run from its dir) —
             used by the root update_all.py runner
  cache    the capture file the fetch writes (cache/<name>); the runner
             stamps cache/<name>.fetched_at and skips re-fetching when fresh
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VENUES = {
    "independent": {
        "key": "independent",
        "name": "The Independent",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "independent"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "vfinal.json",
    },
    "castro": {
        "key": "castro",
        "name": "The Castro Theatre",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "castro"),
        # Apple Music matching applies to its music + comedy performers
        # (film "artists" — directors, screenwriters — are not linked).
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch_calendar.py",
        "cache": "calendar.json",
    },
    "fillmore": {
        "key": "fillmore",
        "name": "The Fillmore",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "fillmore"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch_calendar.py",
        "cache": "calendar.json",
    },
    "gamh": {
        "key": "gamh",
        "name": "Great American Music Hall",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "gamh"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
}


def get_venue(key):
    if key not in VENUES:
        raise KeyError(f"unknown venue '{key}' (known: {', '.join(VENUES)})")
    return VENUES[key]
