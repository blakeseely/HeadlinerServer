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
    "regency": {
        "key": "regency",
        "name": "The Regency Ballroom",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "regency"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "augusthall": {
        "key": "augusthall",
        "name": "August Hall",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "augusthall"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "warfield": {
        "key": "warfield",
        "name": "The Warfield Theatre",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "warfield"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "cafedunord": {
        "key": "cafedunord",
        "name": "Cafe du Nord",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "cafedunord"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "foxoakland": {
        "key": "foxoakland",
        "name": "Fox Theater (Oakland)",
        "city": "Oakland, CA",
        "dir": os.path.join(ROOT, "foxoakland"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "greek": {
        "key": "greek",
        "name": "Greek Theatre",
        "city": "Berkeley, CA",
        "dir": os.path.join(ROOT, "greek"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "brickandmortar": {
        "key": "brickandmortar",
        "name": "Brick & Mortar Music Hall",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "brickandmortar"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "frost": {
        "key": "frost",
        "name": "Frost Amphitheater",
        "city": "Stanford, CA",
        "dir": os.path.join(ROOT, "frost"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "chapel": {
        "key": "chapel",
        "name": "The Chapel",
        "city": "San Francisco, CA",
        "dir": os.path.join(ROOT, "chapel"),
        # Single-room live-music venue (Mission District). Calendar is the
        # full season (12 server-rendered month tables). Spotify is honest
        # null: the venue's site publishes no per-artist links and the
        # Seetickets ticket pages are bot-walled.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
}


def get_venue(key):
    if key not in VENUES:
        raise KeyError(f"unknown venue '{key}' (known: {', '.join(VENUES)})")
    return VENUES[key]
