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
  lat / lon        flat WGS84 decimal coordinates for the venue building,
                 geocoded ONCE when the venue is added (confirm the venue's
                 own address first — its site footer/contact/GCal link —
                 then take a name-tagged OSM POI / exact-address match via
                 Nominatim or Photon and cross-check a second source).
                 publish-data.sh stamps them into the data manifest for the
                 iOS client; they must never be re-derived per build.
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
        "lat": 37.7719,  # 628 Haight St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.433,
        "name": "The Independent",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.762,  # 429 Castro St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4348,
        "name": "The Castro Theatre",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.7841,  # 1805 Geary Blvd — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4332,
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
        "lat": 37.7848,  # 859 O'Farrell St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4188,
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
        "lat": 37.7878,  # 1300 Van Ness Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4216,
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
        "lat": 37.7876,  # 420 Mason St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4098,
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
        "lat": 37.7826,  # 982 Market St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4103,
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
        "lat": 37.7667,  # 2170 Market St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4305,
        "name": "Cafe du Nord",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.808,  # 1807 Telegraph Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.2702,
        "name": "Fox Theater (Oakland)",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.8737,  # 2001 Gayley Rd — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.2542,
        "name": "Greek Theatre",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.7697,  # 1710 Mission St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4203,
        "name": "Brick & Mortar Music Hall",
        # Venue-publishing venue: scraped links win; the API fills the gap
        # (2026-11-08 Spotify coverage parity)
        "has_spotify_lookup": True,
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
        "lat": 37.4307,  # Stanford, Lasuen Way — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.166,
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
        "lat": 37.7605,  # 1854 Market St (777 Valencia side) — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4212,
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
    "bgc": {
        "key": "bgc",
        "lat": 37.7781,  # 99 Grove St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4173,
        "name": "Bill Graham Civic Auditorium",
        "has_spotify_lookup": True,
        "city": "San Francisco, CA",
        "metro": SF_Metro,
        "neighborhood": "Civic Center",
        "dir": os.path.join(ROOT, "bgc"),
        # Large Civic Center auditorium (99 Grove St, Another Planet
        # Entertainment, wpengine WordPress): the /calendar listing is fully
        # server-rendered (one GET = the whole season, no pagination) with
        # clean headliner/support/date/times/button fields; detail pages add
        # the age rating + per-artist Spotify links (the venue publishes
        # them) + a headliner bio. Music only.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "events.json",
    },
    "rickshawstop": {
        "key": "rickshawstop",
        "lat": 37.776,  # 155 Fell St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.4205,
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
        "lat": 32.991,  # 143 S Cedros Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.2707,
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
        "lat": 32.9758,  # 2260 Jimmy Durante Blvd (SD Fairgrounds) — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.2617,
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
        "lat": 32.7303,  # 2501 Kettner Blvd — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.1718,
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
        "lat": 32.748,  # 2891 University Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.1313,
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
        "lat": 32.7194,  # 1337 India St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.1681,
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
        "lat": 32.7169,  # 2241 Shelter Island Dr — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -117.224,
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
        "lat": 34.1564,  # 53688 Pioneertown Rd — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -116.493,
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
    # ------------------------------------------------------------------
    # Portland metro — the Crystal Ballroom (McMenamins / Edgefield
    # Concerts) opens the fourth market.
    # ------------------------------------------------------------------
    "crystalball": {
        "key": "crystalball",
        "lat": 45.5227,  # 1332 W Burnside (406 SW 14th Ave) — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6848,
        "name": "Crystal Ballroom",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "West End",
        "dir": os.path.join(ROOT, "crystalball"),
        # WordPress + The Events Calendar: the TEC REST API (ISO dates +
        # description) joined with the tour-schedule CARD grid (buy buttons,
        # promoter, billed h1/h2) by event URL; per-show detail pages add
        # the doors/show line + age note. The 17 REST-only rows are
        # recurring non-show programming (History & Art Tour, markets) —
        # the fetch skips them with a printed warning. Site publishes no
        # per-artist links, so the Spotify API lookup fills what it can.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "holocene": {
        "key": "holocene",
        "lat": 45.5174,  # 1001 SE Morrison St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6554,
        "name": "Holocene",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "Buckman",
        "dir": os.path.join(ROOT, "holocene"),
        # Rebuilt venue site (holocene.org — the old holocenepdx.com is
        # NXDOMAIN): SSR calendar /events in ONE GET (etix-backed rows, ISO
        # date in the href) + per-show event pages that bill PRE-PARSED
        # (ev-title/ev-sub/ev-with + Doors/Ages dl + schema.org MusicEvent
        # JSON-LD with performer[], doorTime, eventStatus, offers). The
        # JSON-LD doubles as the audit validator's independent source.
        # DJ/rave nights are music (Club Darc rule); 'presented by' phrases
        # in calendar titles must NOT go through parse_bill (detail h1 wins).
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "keller": {
        "key": "keller",
        "lat": 45.5124,  # 222 SW Clay St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6782,
        "name": "Keller Auditorium",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "Grand Ave / Cultural District",
        "dir": os.path.join(ROOT, "keller"),
        # City-owned, Metro-operated Portland'5 house — its schedule ONLY
        # exists in the portland5.com calendar (old kellerauditorium.
        # portlandoregon.gov DNS is dead; kellerauditorium.org is spam
        # squat). One feed row PER PERFORMANCE: Broadway runs explode from
        # event pages. This is the multiplex venue — event_type taxonomy
        # (music/comedy/other) does real classification work here. Spotify
        # API lookup feeds the music rows; theater rows keep the names.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "polarishall": {
        "key": "polarishall",
        "lat": 45.5621,  # 635 N Killingsworth Ct — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6738,
        "name": "Polaris Hall",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "St. Johns",
        "dir": os.path.join(ROOT, "polarishall"),
        # Mississippi Studios' little sister room (~300 cap) in a restored
        # Masonic temple. One-page SSR site (custom CMS, not WordPress):
        # the WHOLE calendar (~58 cards, horizon ~6 months) renders in a
        # single GET inside #shows. Card dates carry NO YEAR — month-vs-
        # today inference (chronological walk Nov->May asserts monotonic).
        # etix CTA text is the status vocabulary (Get Tickets/Sold Out).
        # Age limits exist only behind bot-walled etix product pages:
        # age_rating is null by design.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "roseland": {
        "key": "roseland",
        "lat": 45.5234,  # 8 NW 6th Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6761,
        "name": "Roseland Theater",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "Old Town / Chinatown",
        "dir": os.path.join(ROOT, "roseland"),
        # Same rhp-events plugin family as Wonder Ballroom but the template
        # DRIFTED: wrapper class carries suffixes, eventDate has NO year
        # (the month separators carry "November 2026" style year context),
        # age lives in the notes box not eventAgeRestriction, doors line
        # without comma. /events/page/2/ is a client-side mirror of page 1
        # — the fetch walks pages until none are fresh. Receives moved
        # shows from Wonder Ballroom (Frost Children). Spotify API lookup.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "wonderball": {
        "key": "wonderball",
        "lat": 45.5407,  # 123 NE Russell St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.6635,
        "name": "Wonder Ballroom",
        "has_spotify_lookup": True,
        "city": "Portland, OR",
        "metro": "Portland",
        "neighborhood": "Sullivan's Gulch",
        "dir": os.path.join(ROOT, "wonderball"),
        # WordPress + the venue group's own rhp-events plugin (same shop as
        # Roseland): /events/ is fully server-rendered — head, support h4,
        # promoter, doors/show line, age, cost, CTA status class, etix link,
        # all on the card in ONE GET. No TEC REST (404), no pagination, no
        # detail crawl. Title status prefixes (*CANCELLED* / *Postponed* /
        # MOVED TO …) are interpreted by the build. Site publishes no
        # per-artist links, so the Spotify API lookup fills what it can.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "shows.json",
    },
    "paramount": {
        "key": "paramount",
        "lat": 47.6132,  # 911 Pine St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.3314,
        "name": "The Paramount",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "Downtown",
        "dir": os.path.join(ROOT, "paramount"),
        # Seattle Theatre Group house (Paramount/Moore/Neptune share ONE
        # MEC calendar on stgpresents.org). Feed rows are PER PERFORMANCE
        # via the public admin-ajax mec_list_load_more (no nonce): each
        # card carries the true curtain time in mec-start-time — the MEC
        # JSON-LD clock is timezone-corrupt, only its DATE half is trusted.
        # Broadway runs dominate; event_type does classification work.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "stg.json",
    },
    "moore": {
        "key": "moore",
        "lat": 47.6117,  # 1932 2nd Ave — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.3414,
        "name": "The Moore",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "Downtown",
        "dir": os.path.join(ROOT, "moore"),
        # STG shared MEC source — see paramount entry.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "stg.json",
    },
    "neptune": {
        "key": "neptune",
        "lat": 47.6611,  # 1312 NE 41st St — geocoded once 2026-11-07 (OSM/Wikidata-verified)
        "lon": -122.314,
        "name": "The Neptune",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "University District",
        "dir": os.path.join(ROOT, "neptune"),
        # STG shared MEC source — see paramount entry.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "stg.json",
    },
    # --- Seattle AEG/AXS family: showboxpresents.com is ONE aggregate
    # calendar for both rooms (card venue label splits); neumos.com is its
    # own Carbonhouse skin. Shared mechanics: common/aeg.py. ---
    "showbox": {
        "key": "showbox",
        "lat": 47.6085,
        "lon": -122.3395,
        "name": "The Showbox",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "Downtown",
        "dir": os.path.join(ROOT, "showbox"),
        # AEG/AXS aggregate calendar — see showboxpresents note above.
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "aeg.json",
    },
    "showboxsodo": {
        "key": "showboxsodo",
        "lat": 47.5880,
        "lon": -122.3339,
        "name": "Showbox SoDo",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "SoDo",
        "dir": os.path.join(ROOT, "showboxsodo"),
        # Same aggregate calendar as showbox; venue label "Showbox SoDo".
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "aeg.json",
    },
    "neumos": {
        "key": "neumos",
        "lat": 47.6140,
        "lon": -122.3196,
        "name": "Neumos",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "Capitol Hill",
        "dir": os.path.join(ROOT, "neumos"),
        # Own AEG/AXS Carbonhouse site; 406s Chrome UAs (common/aeg.py).
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "aeg.json",
    },
    # --- El Corazón + Funhouse: one org, one Webflow site, one calendar;
    # the venue field splits the two feeds (common/ecfun.py). ---
    "elcorazon": {
        "key": "elcorazon",
        "lat": 47.6187,
        "lon": -122.3293,
        "name": "El Corazón",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "South Lake Union",
        "dir": os.path.join(ROOT, "elcorazon"),
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "ec.json",
    },
    "funhouse": {
        "key": "funhouse",
        "lat": 47.6189,
        "lon": -122.3293,
        "name": "Funhouse",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "South Lake Union",
        "dir": os.path.join(ROOT, "funhouse"),
        # Same site/calendar as elcorazon (they share the 109 E Eastlake
        # building); venue field "The Funhouse".
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "ec.json",
    },
    "crocodile": {
        "key": "crocodile",
        "lat": 47.6146,
        "lon": -122.3491,
        "name": "The Crocodile",
        "has_spotify_lookup": True,
        "city": "Seattle, WA",
        "metro": "Seattle",
        "neighborhood": "Belltown",
        "dir": os.path.join(ROOT, "crocodile"),
        # Own Squarespace calendar is DEAD (placeholder events) — primary
        # tickets live on TicketWeb venue page 10352 (see crocodile/).
        "has_apple_music": True,
        "fetch_cmd": "python3 fetch.py",
        "cache": "ticketweb.json",
    },
}


def get_venue(key):
    if key not in VENUES:
        raise KeyError(f"unknown venue '{key}' (known: {', '.join(VENUES)})")
    return VENUES[key]


def geo(venue_id):
    """The geo tags for a venue: {city, metro, neighborhood|None, lat, lon}.

    Consumed by common/build.py (which stamps city/metro/neighborhood into
    shows.json — lat/lon deliberately do NOT go into the feed files) and by
    the data manifest builder in publish-data.sh (which publishes lat/lon
    into manifest.json for the iOS client).
    """
    v = get_venue(venue_id)
    return {
        "city": v["city"],
        "metro": v["metro"],
        "neighborhood": v.get("neighborhood"),
        "lat": v.get("lat"),
        "lon": v.get("lon"),
    }
