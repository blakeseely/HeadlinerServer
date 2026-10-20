#!/usr/bin/env python3
"""Build data/shows.json for The Regency Ballroom (venue adapter).

Input: cache/events.json — the raw AEG/AxS A|B blob event objects
captured by fetch.py (one per show, newest-first, pre-structured).

The A|B feed is clean and self-describing, so the mapping is short:
  * title.headlinersText  -> headline_artists (single act each here)
  * title.supportingText  -> support_artists (split on ", "&)
  * title.presentedByText -> presenters
  * title.tour            -> show_title (when it reads as a show/tour name)
  * eventDateTimeISO/doorDateTime -> date, show_time, doors
  * ticketing.status/url  -> ticket_status / ticket_link
  * age / eventId         -> age_rating / event_page

Everything at the Regency is live music, so every bill is event_type
"music". The one quirk: an "An Evening With <Artist>" headline is a
set-format note, not part of the artist name — we split it so the lookup
keys off the real act.

Apple Music matching is the shared engine: common/lookup.py populates
cache/lookup.json over the billed names, common.apple_music.artist_obj
renders the records, apple_music_stats() feeds the ♪ stats block.
"""
import os, re, sys, json, datetime, unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "events.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "The Regency Ballroom"
VENUE_ID = "regency"
VENUE_URL = "https://theregencyballroom.com/"
BLOB_URL = ("https://aegwebprod.blob.core.windows.net/json/events/9/events.json")

# AxS status -> the shared vocabulary the reviewer/other venues use.
TICKET_STATUS = {"Buy Tickets": "on sale", "Coming Soon": "coming soon",
                 "Sold Out": "sold out"}

# Boilerplate that AxS stamps on every event; not a real per-show blurb.
BOILERPLATE = re.compile(
    r"if tickets in the accessible section|ticket prices may fluctuate|"
    r"orders in violation of the published ticket limit", re.I)


def _accentless(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def eq(a, b):
    return _accentless((a or "").lower()) == _accentless((b or "").lower())


def clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.")
    return n or None


def strip_evening_prefix(name):
    """'An Evening With Band of Horses' -> ('Band of Horses', 'An Evening With').
    An "An Evening With <X>" bill is a set-format descriptor, not part of the
    artist name, so the Apple Music lookup keys off the real act."""
    m = re.match(r"^[Aa][Nn] Evening [Ww]ith\s+(.+)$", name or "")
    if m:
        return m.group(1).strip(), "An Evening With"
    return name, None


def split_support(text):
    """'with Rosegarden Funeral Party' / 'with A, B' -> [names].
    Strips a leading 'with'/'&'/'and', splits on , / & / ' and '."""
    if not text:
        return []
    t = re.sub(r"^\s*(with|&|and)\s+", "", text.strip(), flags=re.I)
    t = re.sub(r"\s+and\s+", ", ", t)
    t = re.sub(r"\s*&\s*", ", ", t)
    parts = [p.strip(" .-–—,") for p in t.split(",")]
    out = []
    for p in parts:
        p = clean(p)
        if p and 1 < len(p) <= 50 and p not in out:
            out.append(p)
    return out


def fmt_time(iso):
    """'2026-10-18T20:00:00-07:00' -> '8:00 PM' (venue-style). None if bad."""
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(iso)
    except ValueError:
        return None
    h = dt.hour
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{dt.minute:02d} {ap}"


def date_only(iso):
    if not iso:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", iso)
    return m.group(1) if m else None


def desc_of(e):
    d = e.get("description") or ""
    d = re.sub(r"<[^>]+>", " ", d)
    d = re.sub(r"&[a-z]+;|&#\d+;", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    # AxS stamps the same accessibility/price-fluctuation boilerplate on every
    # event; it is not a per-show blurb.
    if BOILERPLATE.search(d):
        return None
    d = d.strip(" .-–—")
    return d or None


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for e in rows:
        t = e.get("title") or {}
        hl = clean(t.get("headlinersText"))
        if not hl:
            continue
        head, set_format = strip_evening_prefix(hl)

        heads = [head]
        support = split_support(t.get("supportingText"))
        # never let a "support" name duplicate the headliner
        support = [s for s in support
                   if not any(eq(s, h) for h in heads)]

        tour = clean(t.get("tour"))
        shown = clean(t.get("eventTitleText")) or hl
        show_title = None
        # only surface a distinct show/tour title when it differs from the act
        if tour and not eq(tour, head):
            show_title = tour

        status = (e.get("ticketing") or {}).get("status")
        if status is not None:
            status = str(status)
        tlink = (e.get("ticketing") or {}).get("ticketURL") \
            or (e.get("ticketing") or {}).get("url")

        note = None
        lo = clean(e.get("ticketPriceLow"))
        hi = clean(e.get("ticketPriceHigh"))
        if lo and hi and lo != "$0" and lo != hi:
            note = f"{lo}–{hi}"
        elif lo and lo != "$0":
            note = f"From {lo}"

        # The feed's doorDateTime is naive (no tz); the ISO event time has the
        # venue tz, so derive the door time from both when the naive one is present.
        doors = None
        if e.get("doorDateTime") and e.get("eventDateTimeISO"):
            try:
                dt = datetime.datetime.fromisoformat(e["eventDateTimeISO"])
                dr = datetime.datetime.fromisoformat(e["doorDateTime"])
                dt2 = dt.replace(hour=dr.hour, minute=dr.minute, second=0,
                                 microsecond=0)
                if dt2 < dt:  # doors before show same day (always, in practice)
                    doors = fmt_time(dt2.isoformat())
            except ValueError:
                doors = None

        rec = common_build.show(
            event_type="music",
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(heads) > 1,
            show_title=show_title,
            presenters=[t["presentedByText"]] if t.get("presentedByText") else None,
            set_format=set_format,
            date=date_only(e.get("eventDateTimeISO")),
            doors=doors,
            show_time=fmt_time(e.get("eventDateTimeISO")),
            ticket_link=tlink,
            ticket_status=TICKET_STATUS.get(status, status) if status is not None else None,
            event_page=f"https://theregencyballroom.com/events/detail?event_id={e.get('eventId')}"
                       if e.get("eventId") else None,
            age_rating=e.get("age") or None,
            note=note,
            description=desc_of(e),
        )
        # Spotify: the AEG blob's association records carry only a performerId
        # (no name), so we zip them against the text-derived bill in order and
        # assign only where the counts line up — never a guess.
        a = e.get("associations") or {}
        hl_recs = a.get("headliners") or []
        sup_recs = a.get("supportingActs") or []
        for arr, recs in ((rec["headline_artists"], hl_recs),
                          (rec["support_artists"], sup_recs)):
            if len(arr) == len(recs):
                for artist, r in zip(arr, recs):
                    if isinstance(artist, dict):
                        artist["spotify"] = (spotify.spotify_links_json(r) or [None])[0]
        shows.append(rec)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, BLOB_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in shows:
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        flag = " \u26a0" if s["needs_review"] else ""
        print(f"  {s['date'] or '?'}  {h[:40]:40} "
              f"{('+' + sup)[:30]:30} {s.get('ticket_status') or ''}{flag}")
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found "
          f"({st['exact']} exact, {st['close']} close, {st['needs_review']} flagged), "
          f"{st['not_found']} not found")
    for s in shows:
        for a in s["headline_artists"] + s["support_artists"]:
            if not a["found"] and a["confidence"] is not None:
                print(f"  not-found: {a['name']} (closest {a['matched']} @ {a['confidence']})")


if __name__ == "__main__":
    main()
