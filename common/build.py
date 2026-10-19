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
from . import apple_music
from .apple_music import date_label

# --------------------------------------------------------------------------
# The shared show record shape (superset; null where a venue has no field)
# --------------------------------------------------------------------------
SHOULD_FIELDS = [
    "event_type",       # str|null: music | film | comedy | other
    "needs_review",     # bool: venue-flagged for human review
    "headline_artists", # [{name, apple_music, found, confidence, matched, match_label}]
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


def show(event_type=None, needs_review=False,
         headline_artists=None, support_artists=None, multi_artist=False,
         show_title=None, presenters=None, set_format=None,
         date=None, date_label=None, doors=None, show_time=None,
         ticket_link=None, ticket_status=None, event_page=None,
         room=None, age_rating=None, note=None, description=None):
    """Build one show record in the shared shape (missing values -> None)."""
    import datetime as _dt
    return {
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


def normalize(shows):
    """Ensure every show record carries the full shared field set
    (unknown extra fields are kept; missing ones are added as None/False)."""
    for s in shows:
        for f in SHOULD_FIELDS:
            if f == "needs_review":
                s.setdefault("needs_review", False)
            elif f == "presenters":
                s.setdefault("presenters", [])
            elif f in ("headline_artists", "support_artists"):
                s.setdefault(f, [])
            elif f == "multi_artist":
                s.setdefault("multi_artist", False)
            else:
                s.setdefault(f, None)
        if s.get("date") and not s.get("date_label"):
            s["date_label"] = date_label(s["date"])
    return shows


def run_build(venue, venue_id, venue_url, source_url, shows, stats):
    """Sort, assemble the shared top-level document, write data/shows.json.

    Venue adapters call this at the end of their build. Returns the path.
    """
    shows = normalize(list(shows))
    shows.sort(key=lambda s: (s.get("date") or "9999", s.get("doors") or ""))
    import datetime as _dt
    import json
    doc = {
        "venue": venue,
        "venue_id": venue_id,
        "venue_url": venue_url,
        "source_url": source_url,
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
