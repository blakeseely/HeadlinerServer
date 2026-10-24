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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": False,
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
        "has_spotify_lookup": True,
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
        "has_spotify_lookup": True,
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
    "rickshawstop": {
        "key": "rickshawstop",
        "name": "Rickshaw Stop",
        "has_spotify_lookup": True,
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Civic Center",
        "dir": os.path.join(ROOT, "rickshawstop"),
        # Eclectic Mission/Civic-Center room (155 Fell St): indie,
        # electronic, dance + the occasional comedy set. The HTML routes are
        # Cloudflare-walled, so fetch.py reads the calendar through the
        # WordPress REST API (12 month tables + 10 nearest list cards,
        # merged). Spotify is honest-null (site publishes no per-artist
        # links; the Seetickets/Eventim ticket pages are bot-walled) — the
        # API lookup fills what it can.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    # ------------------------------------------------------------------
    # San Diego metro — the Belly Up Presents group promotes all six rooms
    # from ONE shared calendar (bellyup.com/calendar); each dir is a thin
    # wrapper over common/fetch_bellyup.py + common/build_bellyup.py and
    # keeps only its own venue's rows. `bellyup_venue` is the venue cell
    # text on that calendar (+ alias fallbacks).
    # ------------------------------------------------------------------
    "bellyup": {
        "key": "bellyup",
        "name": "Belly Up",
        "has_spotify_lookup": True,
        "city": "Solana Beach, CA",
        "metro": "San Diego",
        "neighborhood": "Solana Beach",
        "dir": os.path.join(ROOT, "bellyup"),
        "has_apple_music": True,
        "bellyup_venue": "Belly Up",
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "thesound": {
        "key": "thesound",
        "name": "The Sound",
        "has_spotify_lookup": True,
        "city": "Del Mar, CA",
        "metro": "San Diego",
        "neighborhood": "Del Mar Fairgrounds",
        "dir": os.path.join(ROOT, "thesound"),
        "has_apple_music": True,
        "bellyup_venue": "The Sound",
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "thecasbah": {
        "key": "thecasbah",
        "name": "The Casbah",
        "has_spotify_lookup": True,
        "city": "San Diego, CA",
        "metro": "San Diego",
        "neighborhood": "Downtown",
        "dir": os.path.join(ROOT, "thecasbah"),
        "has_apple_music": True,
        "bellyup_venue": "Casbah",
        "bellyup_venue_aliases": ["The Casbah"],
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "theobservatory": {
        "key": "theobservatory",
        "name": "The Observatory North Park",
        "has_spotify_lookup": True,
        "city": "San Diego, CA",
        "metro": "San Diego",
        "neighborhood": "North Park",
        "dir": os.path.join(ROOT, "theobservatory"),
        "has_apple_music": True,
        "bellyup_venue": "The Observatory North Park",
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "musicbox": {
        "key": "musicbox",
        "name": "Music Box SD",
        "has_spotify_lookup": True,
        "city": "San Diego, CA",
        "metro": "San Diego",
        "neighborhood": "Little Italy",
        "dir": os.path.join(ROOT, "musicbox"),
        "has_apple_music": True,
        "bellyup_venue": "Music Box",
        "bellyup_venue_aliases": ["Music Box SD"],
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "humphreys": {
        "key": "humphreys",
        "name": "Humphreys Concerts by the Bay",
        "has_spotify_lookup": True,
        "city": "San Diego, CA",
        "metro": "San Diego",
        "neighborhood": "Shelter Island",
        "dir": os.path.join(ROOT, "humphreys"),
        "has_apple_music": True,
        "bellyup_venue": "Humphreys Concerts By the Bay",
        "bellyup_venue_aliases": ["Humphreys"],
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    # ------------------------------------------------------------------
    # Los Angeles metro — Pappy & Harriet's (Pioneertown) is ~90 mi east of
    # LA; the owner groups it with the LA market on purpose.
    # ------------------------------------------------------------------
    "pappy": {
        "key": "pappy",
        "name": "Pappy & Harriet's",
        "has_spotify_lookup": True,
        "city": "Pioneertown, CA",
        "metro": "Los Angeles",
        "neighborhood": None,
        "dir": os.path.join(ROOT, "pappy"),
        # Pioneertown desert saloon (53688 Pioneertown Rd): country/rock/
        # roots, EST. 1982. The HTML routes are bot-walled (403 curl AND a
        # real browser), so fetch.py reads the /calendar page through the
        # WordPress REST API (12 month tables + the nearest ~38 list cards,
        # merged). Spotify is honest-null (site publishes no per-artist links;
        # the Seetickets event pages are bot-walled) — the API lookup fills
        # what it can.
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
