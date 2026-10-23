"""Shared build pipeline — the common part every venue goes through.

A venue adapter (independent/build.py, castro/build.py, or any future
theater) does ONE thing: map its venue's raw capture into a list of show
records in the shared shape below, then call run_build() with:

  run_build(venue, venue_id, venue_url, source_url, shows, stats)

which sorts, stamps the shared top-level document (venue, venue_id,
scraped_at, count, shows, stats), and writes data/shows.json.

Adding a new theater:
  1. write <new>/fetch*.py to capture the schedule into <new>/cache/
  2. write <new>/build.py that maps the cache into the show shape
  3. register <new> in common/venues.py
  4. if it should get Apple Music links: run common/lookup.py from <new>/
     and shape artists with apple_music.artist_obj()

Everything else — record shape, stats, JSON writer, viewer, picker —
is shared and already there.
"""
import os
import re
from collections import Counter
from . import apple_music
from .apple_music import date_label, relabel
from . import venues
from . import spotify_api


def canonical_time(t):
    """Light-touch time canonicalization ONLY: '7 PM' / '8:00PM' / '7:00 PM'
    -> 'H:MM pm' (the feed's canonical form). Unparseable values pass through
    unchanged — doors/show_time stay free strings (the venue's own text wins);
    we only collapse case/case-space variants of the same moment."""
    if not t or not isinstance(t, str):
        return t
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?", t.strip(), re.I)
    if not m:
        return t
    h, mi, ampm = int(m.group(1)), m.group(2) or "00", m.group(3).lower()
    if not (1 <= h <= 12):
        return t
    return f"{h}:{mi} {ampm}m"


# Pure case/separator duplicates of the real ticket states, folded to one
# form. Only the duplicates the data actually shows; new raw values (a new
# state the venue starts publishing) pass through un-mangled.
_STATUS_CANON = {
    "on sale": "on sale",
    "on sale soon": "on sale soon",
    "not on sale": "not on sale",
    "sold out": "sold out",
    "coming soon": "coming soon",
    "presale": "presale",
    "cancelled": "cancelled",
    "waitlist": "waitlist",
}


def canonical_status(t):
    """Collapse pure case/separator duplicates of ticket_status to one form;
    every other value passes through verbatim (free string — the venue's own
    wording is preserved, so 'PRESALE 10/22|29' stays as-is). This kills the
    12-variant domain down to the real states while keeping raw wording
    (H3/M-light)."""
    if not t or not isinstance(t, str):
        return t
    norm = re.sub(r"[\s\-]+", " ", t.strip().lower())
    return _STATUS_CANON.get(norm, t)


def canonical_presenters(p):
    """Strip stray trailing/leading dashes and collapse spaces in presenter
    strings (L3: 'Young the Giant -' from a '<name> -' capture)."""
    return [re.sub(r"[\s\-–—]+$", "", re.sub(r"^\s*[\-–—\s]+", "", re.sub(r"\s+", " ", p))).strip()
            for p in (p or []) if isinstance(p, str) and re.sub(r"[\s\-–—]+", "", p)]

# --------------------------------------------------------------------------
# The shared show record shape (superset; null where a venue has no field)
# --------------------------------------------------------------------------
SHOULD_FIELDS = [
    "event_type",       # str|null: music | film | comedy | other
    "needs_review",     # bool: venue-flagged for human review
    "headline_artists", # [{name, apple_music, spotify, found, confidence, matched, match_label}]
    "support_artists",  # same shape
    "multi_artist",     # bool
    "show_title",       # str|null: tour/show title when billed separately
    "presenters",       # [str]: "X PRESENTS"
    "set_format",       # str|null: "Live + DJ" style
    "date",             # YYYY-MM-DD|null
    "date_label",       # "Fri 2026-10-16"|null
    "doors",            # str|null
    "show_time",        # str|null
    "ticket_link",      # str|null
    "ticket_status",    # str|null: on sale | sold out | ...
    "event_page",       # str: the venue's own page for this event
    "room",             # str|null: room/stage name for multi-room venues (e.g. "Swedish American Hall (upstairs)")
    "age_rating",       # str|null
    "note",             # str|null
    "description",      # str|null
]

# Fields whose absence is a problem in the reviewer (drives status flags):
MISSING_BAD = ("date", "headline_artists")


def _name_key(n):
    import re as _re
    return _re.sub(r"[^a-z0-9@ ]", "", (n or "").lower()).strip()


STATUS_WORDS = {"POSTPONED", "CANCELED", "CANCELLED"}


def rekey_status_headliner(name, show_title):
    """A status word in the headliner slot is a marker, never an artist.

    "POSTPONED - Sawyer Hill" / "POSTPONED: Dogma" => the real headliner is
    the show title. Returns (name, show_title, note_fragment); the re-key
    belongs in the venue's build, BEFORE the Apple Music / Spotify lookup
    (which keys off the billed name) — so the real act is what gets looked
    up, not the literal word (a real Apple Music artist named "Postponed"
    exists and used to be happily linked). show() also applies
    _promote_status_headliner() as a safety net for builds that re-key
    later. Idempotent.
    """
    if not name or not show_title:
        return name, show_title, None
    n0 = str(name).strip()
    s0 = str(show_title).strip()
    if n0.upper() in STATUS_WORDS and _name_key(s0) != _name_key(n0):
        return s0, None, n0.upper().capitalize()
    return name, show_title, None


def _promote_status_headliner(rec):
    """Safety net for builds that shape the artist before re-keying:
    re-key a status-word headliner to the show title and reset the bogus
    lookup fields (a real Apple artist named "Postponed" exists)."""
    heads = rec.get("headline_artists") or []
    st = (rec.get("show_title") or "").strip()
    if not st or len(heads) != 1 or not isinstance(heads[0], dict):
        return
    nm, st2, note = rekey_status_headliner(heads[0].get("name"), st)
    if nm == heads[0].get("name"):
        return
    a = heads[0]
    a["name"] = nm
    for k in ("apple_music", "spotify"):
        a[k] = None
    a["found"] = False
    a["confidence"] = None
    a["matched"] = None
    a["match_label"] = None
    rec["show_title"] = st2
    if note and not rec.get("note"):
        rec["note"] = note


def show(event_type=None, needs_review=False,
         headline_artists=None, support_artists=None, multi_artist=False,
         show_title=None, presenters=None, set_format=None,
         date=None, date_label=None, doors=None, show_time=None,
         ticket_link=None, ticket_status=None, event_page=None,
         room=None, age_rating=None, note=None, description=None):
    """Build one show record in the shared shape (missing values -> None)."""
    import datetime as _dt
    rec = {
        "event_type": event_type,
        "needs_review": bool(needs_review),
        "headline_artists": list(headline_artists or []),
        "support_artists": list(support_artists or []),
        "multi_artist": bool(multi_artist),
        "show_title": show_title,
        "presenters": list(presenters or []),
        "set_format": set_format,
        "date": date,
        "date_label": date_label,
        "doors": doors,
        "show_time": show_time,
        "ticket_link": ticket_link,
        "ticket_status": ticket_status,
        "event_page": event_page,
        "room": room,
        "age_rating": age_rating,
        "note": note,
        "description": description,
    }
    _promote_status_headliner(rec)
    return rec


# --------------------------------------------------------------------------
# Schema uniformity (enforced in ONE place — run_build/normalize — so every
# venue's shows.json has the exact same shapes regardless of its adapter)
# --------------------------------------------------------------------------
# event_types is a CONTROLLED 4-value enum, reported in every file with all
# four keys present (zeros included) so clients switch on a fixed key set.
EVENT_TYPES = ("music", "comedy", "film", "other")


def event_type_stats(shows):
    """Uniform stats.event_types block: all four enum keys, zeros included."""
    c = Counter()
    for s in shows:
        et = s.get("event_type")
        if et in EVENT_TYPES:
            c[et] += 1
    return {k: c.get(k, 0) for k in EVENT_TYPES}


def field_hints():
    """Per-field schema hints for clients (the controlled-vs-raw contract).

    controlled   — the value comes from a fixed vocabulary; safe to
                   `switch`/filter on without normalization.
    free_string  — text pulled from the venue's own page; it keeps the
                   venue's spelling (we only collapse case/separator
                   duplicates and strip capture artifacts). Clients that
                   need a fixed vocabulary should normalize client-side.
    """
    return {
        "event_type": "controlled",       # music | comedy | film | other
        "needs_review": "bool",
        "show_title": "free_string",
        "set_format": "free_string",
        "date": "date",                   # YYYY-MM-DD (or null)
        "date_label": "date_label",       # 'Fri 2026-10-16' (display convenience)
        "doors": "free_string",           # canonicalized to 'H:MM pm' when parseable
        "show_time": "free_string",       # canonicalized to 'H:MM pm' when parseable
        "ticket_link": "free_string",     # URL, or the venue's button text
        "ticket_status": "free_string",   # case-folded, raw vocabulary otherwise
        "room": "free_string",
        "age_rating": "free_string",
        "note": "free_string",
        "description": "free_string",
        "artist.apple_music": "url",
        "artist.spotify": "url",
        "artist.found": "bool",           # Apple Music match found
        "artist.confidence": "float",     # null=not attempted, 0.0=no match, else 0-1
        "artist.matched": "free_string",  # catalog artist name the link resolves to
        "artist.apple_label": "free_string",
        "artist.spotify_label": "free_string",
        "artist.match_label": "free_string",  # = apple_label + ' | ' + spotify_label
        "artist.spotify_source": "controlled",  # venue | api | feed | null
    }


def normalize(shows):
    """Ensure every show record carries the full shared field set and the
    controlled-value contracts (unknown extra fields are kept; missing ones
    are added as None/False). Also canonicalizes doors/show_time/ticket_status
    and trims presenter artifacts, and reshapes artist dicts to the uniform
    key set (10 keys always present; combined match_label recomputed)."""
    for s in shows:
        for f in SHOULD_FIELDS:
            if f == "needs_review":
                s.setdefault("needs_review", False)
            elif f == "presenters":
                s.setdefault("presenters", [])
                s["presenters"] = canonical_presenters(s["presenters"])
            elif f in ("headline_artists", "support_artists"):
                s.setdefault(f, [])
                for a in s[f]:
                    if isinstance(a, dict):
                        a.setdefault("spotify", None)
                        a.setdefault("spotify_source", None)
                        a.setdefault("apple_label", None)
                        a.setdefault("spotify_label", None)
                        a.setdefault("found", False)
                        a.setdefault("confidence", None)
                        a.setdefault("matched", None)
                        a.setdefault("apple_music", None)
                        a.setdefault("name", None)
                        relabel(a)  # recompute combined match_label
            elif f == "multi_artist":
                s.setdefault("multi_artist", False)
            elif f == "doors":
                s.setdefault(f, None)
                if s.get(f):
                    s[f] = canonical_time(s[f])
            elif f == "show_time":
                s.setdefault(f, None)
                if s.get(f):
                    s[f] = canonical_time(s[f])
            elif f == "ticket_status":
                s.setdefault(f, None)
                if s.get(f):
                    s[f] = canonical_status(s[f])
            else:
                s.setdefault(f, None)
        if s.get("date") and not s.get("date_label"):
            s["date_label"] = date_label(s["date"])
    return shows


def run_build(venue, venue_id, venue_url, source_url, shows, stats):
    """Sort, assemble the shared top-level document, write data/shows.json.

    Venue adapters call this at the end of their build. Returns the path.

    Uniform top-level contract (same keys in every file, every release):
      venue, venue_id, venue_url, source_url, city, metro, neighborhood,
      schema, field_hints, scraped_at, count, shows, stats
    `stats` is always exactly {event_types, apple_music, spotify} (missing
    blocks are added zeroed), so a consumer never has to special-case a
    file whose adapter skipped a block.
    """
    shows = normalize(list(shows))
    shows.sort(key=lambda s: (s.get("date") or "9999", s.get("doors") or ""))
    import datetime as _dt
    import json
    # Geo tags for the iOS app: specific city + metro market (+ neighborhood
    # when useful). Comes from the registry; safe against a missing key.
    try:
        g = venues.geo(venue_id)
    except Exception:
        g = {"city": None, "metro": None, "neighborhood": None}
    stats = dict(stats or {})
    stats["event_types"] = event_type_stats(shows)  # overwrite: uniform block
    stats.setdefault(
        "apple_music", {"unique_artists": 0, "found": 0, "exact": 0,
                        "close": 0, "flagged": 0, "not_found": 0})
    stats.setdefault(
        "spotify", {"unique_artists": 0, "linked": 0, "venue": 0, "api": 0,
                    "feed": 0, "shows_with_link": 0})
    # fixed key order so the document is stable for readers/diffs
    stats = {k: stats[k] for k in ("event_types", "apple_music", "spotify")}
    doc = {
        "venue": venue,
        "venue_id": venue_id,
        "venue_url": venue_url,
        "source_url": source_url,
        "city": g.get("city"),
        "metro": g.get("metro"),
        "neighborhood": g.get("neighborhood"),
        "schema": 2,  # incremented on any schema change; clients gate on it
        "field_hints": field_hints(),
        "scraped_at": _dt.date.today().isoformat(),
        "count": len(shows),
        "shows": shows,
        "stats": stats,
    }
    path = os.path.join(os.getcwd(), "data", "shows.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return path


def apply_spotify_lookup(shows, cache_path):
    """Attach Spotify API-lookup links (from <venue>/cache/spotify_lookup.json)
    to artists that carry no venue-published link. Called by the builds of
    venues whose sites publish nothing (registry `has_spotify_lookup`).

    Venue-published links ALWAYS win over a searched one: merge_lookup()
    skips any artist that already has a link. Below-floor API matches are
    not applied (honest null; the reviewer gets the near-miss label).
    Returns the number of links applied (0 when the cache is absent).
    """
    cache = apple_music.load_lookup_cache(cache_path)
    return spotify_api.merge_lookup(shows, cache)
