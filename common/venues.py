"""Venue registry — the ONE place to add a new theater.

Adding a venue:
  1. create a `<key>/` directory with a `build.py` adapter (see independent/
     and castro/ for the pattern) and its `viewer/` is served from common/.
  2. add one entry here. `serve.py` discovers it and renders the picker card.

Each entry:
  key            registry key + URL path segment (== directory name)
  name           display name (picker card + reviewer header)
  city           display subtitle — specific city + state
  metro          the metro market this venue belongs to (picker grouping +
                 the "metro" tag the iOS app gets in shows.json). One
                 market per metro value, e.g. "San Francisco".
  neighborhood   optional district within the city (iOS app disambiguates
                 venues that share a city, e.g. 8 venues all in SF).
  dir            path of the venue directory (absolute, resolved once)
  has_apple_music  run the Apple Music lookup for this venue
  fetch_cmd      the venue's schedule-capture command (run from its dir) —
                 used by the root update_all.py runner
  cache          the capture file the fetch writes (cache/<name>); the runner
                 stamps cache/<name>.fetched_at and skips re-fetching when fresh
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The SF-metro market: every venue below lives inside it. New metros get a
# new value here + a new picker group (see serve.py / common/viewer).
SF_Metro = "San Francisco"

VENUES = {
    "independent": {
        "key": "independent",
        "name": "The Independent",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Mission District",
        "dir": os.path.join(ROOT, "independent"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "vfinal.json",
    },
    "castro": {
        "key": "castro",
        "name": "The Castro Theatre",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Castro",
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
        "metro": SF_Metro,
        "neighborhood": "Fillmore",
        "dir": os.path.join(ROOT, "fillmore"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch_calendar.py",
        "cache": "calendar.json",
    },
    "gamh": {
        "key": "gamh",
        "name": "Great American Music Hall",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "SoMa",
        "dir": os.path.join(ROOT, "gamh"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "regency": {
        "key": "regency",
        "name": "The Regency Ballroom",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Castro",
        "dir": os.path.join(ROOT, "regency"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "augusthall": {
        "key": "augusthall",
        "name": "August Hall",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "South Beach",
        "dir": os.path.join(ROOT, "augusthall"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "warfield": {
        "key": "warfield",
        "name": "The Warfield Theatre",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "SoMa",
        "dir": os.path.join(ROOT, "warfield"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "cafedunord": {
        "key": "cafedunord",
        "name": "Cafe du Nord",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Presidio Heights",
        "dir": os.path.join(ROOT, "cafedunord"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "foxoakland": {
        "key": "foxoakland",
        "name": "Fox Theater (Oakland)",
        "city": "Oakland, CA",
        "metro": SF_Metro,
        "neighborhood": "West Oakland",
        "dir": os.path.join(ROOT, "foxoakland"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "greek": {
        "key": "greek",
        "name": "Greek Theatre",
        "city": "Berkeley, CA",
        "metro": SF_Metro,
        "neighborhood": None,
        "dir": os.path.join(ROOT, "greek"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "brickandmortar": {
        "key": "brickandmortar",
        "name": "Brick & Mortar Music Hall",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Mission District",
        "dir": os.path.join(ROOT, "brickandmortar"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "frost": {
        "key": "frost",
        "name": "Frost Amphitheater",
        "city": "Palo Alto, CA",
        "metro": SF_Metro,
        "neighborhood": None,
        "dir": os.path.join(ROOT, "frost"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "chapel": {
        "key": "chapel",
        "name": "The Chapel",
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Mission District",
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


def geo(venue_id):
    """The geo tags for a venue: {city, metro, neighborhood|None}.

    Consumed by common/build.py (stamped into shows.json for the iOS app)
    and by the data manifest builder.
    """
    v = get_venue(venue_id)
    return {
        "city": v["city"],
        "metro": v["metro"],
        "neighborhood": v.get("neighborhood"),
    }
