#!/usr/bin/env python3
"""Build the Frost Amphitheater (Stanford) schedule into the shared shows.json.

Maps cache/events.json (captured by fetch.py from the Stanford Live events
API + its server-rendered detail pages) into the common show shape.

Frost is a summer amphitheater promoted by Stanford Live. In the off-season
the feed carries no Frost shows, so this build may legitimately emit ZERO
shows — an honest empty calendar, not a failure.

Field mapping:
    headliner   = the API Title (one billed act per show).
    show_title  = the tour/series: the API Suffix, else the detail-page tour
                  line (e.g. "Stay in Bloom 3").
    presenters  = the API Prefix, "Stanford Live and Goldenvoice Present"
                  style -> ["Stanford Live", "Goldenvoice"].
    support     = the detail page's per-date "Featured Artists:" lists.
    date        = the first (earliest) performance's date.
    show_time   = the first performance's wall-clock time.
    doors       = the detail page's "Gates open at …" line.
    ticket_link = the performance's TicketLink (AXS / Stanford Live).
    ticket_status = the detail page's own sold-out / on-sale buttons.
    age_rating  = the "This event is 18+ …" line.
    description = the artist bio (boilerplate dropped).

Multi-night shows (Dabin: May 1 + May 2) are ONE show in the shared shape:
the first date is `date`; the other dates are folded into `note`
("Also: …") so the reviewer can see the full run without a second record.

Single room (the Frost Amphitheater) -> `room` stays None.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music, spotify

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "data", "shows.json")

VENUE = "Frost Amphitheater"
VENUE_ID = "frost"
VENUE_URL = "https://live.stanford.edu"
SOURCE_URL = "https://live.stanford.edu/api/events/Live"

PRESENTER_RE = re.compile(r"^(?:presented by\s+)?(.*?)(?:\s+present(?:s|ing)?)?\s*$", re.I)


def split_presenters(prefix):
    """'Stanford Live and Goldenvoice Present' -> ['Stanford Live', 'Goldenvoice'].
    'Presented by Stanford Live' -> ['Stanford Live']. None -> []."""
    if not prefix:
        return []
    t = re.sub(r"^\s*presented by\s+", "", prefix, flags=re.I)
    t = re.sub(r"\s+present(?:s|ing)?\s*$", "", t, flags=re.I)
    parts = re.split(r"\s+and\s+|\s*,&?\s*", t)
    out = []
    for p in parts:
        p = re.sub(r"^\s*[,&]\s*|\s*,&?\s*$", "", p).strip()
        if p and len(p) < 60:
            out.append(p)
    return out


def _split_compound(name):
    """'A and B' / 'A & B' / 'A x B' -> [A, B] (None if not a compound).
    '&' inside a single name (Iron & Wine) is NOT a compound — the shared
    engine does the same check via apple_music._split_compound; we mirror it
    only for the multi_artist flag."""
    parts = re.split(r"\s+and\s+|\s*&\s+|\s+x\s+", name, flags=re.I)
    if len(parts) >= 2 and all(len(p.strip()) >= 2 for p in parts):
        return [p.strip() for p in parts]
    return None


def iso_date(date_str):
    """'2026-04-16 20:00:00' or '2026-04-16' -> '2026-04-16'."""
    if not date_str:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(date_str))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def split_support(support_raw, lookup):
    """The detail page returns support as a flat list of acts (already
    <br>-split by the fetch). Each is one act as billed; a part may still
    hold a compound — keep it whole, the engine handles compounding."""
    if not support_raw:
        return []
    if isinstance(support_raw, str):
        support_raw = [support_raw]
    acts = []
    for a in support_raw:
        a = re.sub(r"^(?:with|and|featuring|plus|ft\.?)\s+", "", a, flags=re.I).strip(" ,&.")
        if a and len(a) > 1:
            acts.append(a)
    seen, out = set(), []
    for a in acts:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        out.append(a)
    return [apple_music.artist_obj(a, lookup) for a in out]


def main():
    cache = json.load(open(os.path.join(CACHE, "events.json")))
    lookup = apple_music.load_lookup_cache(os.path.join(CACHE, "lookup.json"))

    shows = []
    for r in cache:
        head_name = r.get("title")
        if not head_name:
            continue
        head = apple_music.artist_obj(head_name, lookup)
        support = split_support(r.get("support"), lookup)

        # tour / series: prefer the API Suffix, fall back to the detail page
        tour = r.get("suffix") or r.get("tour")
        tour = (re.sub(r"\s+", " ", tour).strip() or None) if tour else None

        # multi-night: fold the other dates into a note
        dates = r.get("dates") or []
        others = [d for d in dates if d and d != r.get("date")]
        note = None
        if others:
            note = "Also: " + ", ".join(others)
        if r.get("date") and len(dates) > 1:
            note = (f"({len(dates)} dates) " + (note or "")).strip()

        # show title: the billed act when no tour is given (so the list view
        # reads "Dabin" for a bare show, "Dabin — Stay in Bloom 3" otherwise)
        show_title = tour if tour else None

        desc = r.get("description")
        shows.append(build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[head],
            support_artists=support,
            multi_artist=bool(support) or bool(_split_compound(head_name)),
            show_title=show_title,
            presenters=split_presenters(r.get("prefix")),
            date=iso_date(r.get("date")) or (iso_date(dates[0]) if dates else None),
            doors=r.get("doors"),
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("event_page"),
            age_rating=r.get("age"),
            note=note,
            description=(desc[:1200] or None) if desc else None,
        ))

    stats = {
        "event_types": {
            "music": sum(1 for s in shows if s["event_type"] == "music"),
        },
        "apple_music": apple_music.apple_music_stats(shows),
    }
    build.apply_spotify_lookup(shows, os.path.join(CACHE, "spotify_lookup.json"))

    stats["spotify"] = spotify.stats(shows)
    path = build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    am = stats["apple_music"]
    print(f"built {len(shows)} shows -> {path}"
          + ("  (off-season: no Frost shows scheduled — expected)" if not shows else ""))
    if shows:
        print(f"  event_types: {stats['event_types']}")
        print(f"  apple_music: {am}")
    for s in shows:
        h = " / ".join(a["name"] for a in s["headline_artists"])[:30]
        sup = " / ".join(a["name"] for a in s["support_artists"])[:24]
        print(f"  {str(s.get('date') or '?'):12} {h:30} {str(s.get('show_time') or ''):9} "
              f"{str(s.get('ticket_status') or ''):9} {sup}")


if __name__ == "__main__":
    main()
