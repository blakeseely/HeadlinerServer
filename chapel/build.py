#!/usr/bin/env python3
"""Build The Chapel schedule (cache/events.json) into the shared shows.json.

The Chapel is a single-room live-music venue; every card here is a music show
(event_type = "music" — the calendar is its music calendar, and the venue has
no comedy listing). The See-Tickets cards give the headliner, support, doors /
show time and the ticket link; the date is reconstructed by the fetcher from
the month-table header + the cell's day number.

Apple Music links are matched as usual (the mandate). Spotify is honest-null:
the Chapel's own site publishes no per-artist Spotify links and the ticket
pages (wl.seetickets.us) are bot-walled, so we never scrape for them.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music, spotify

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "data", "shows.json")

VENUE = "The Chapel"
VENUE_ID = "chapel"
VENUE_URL = "https://thechapelsf.com"
SOURCE_URL = "https://thechapelsf.com/calendar/"

# Support arrives as one line like "Supporting Talent: Two Runner" or
# "Supporting Talent: A, B". Strip the label, then split on comma — but act
# names contain "&"/"and" INSIDE them, so a comma-only split is safe here
# (the Chapel bills support comma-separated, not with &/and joins).
NON_ACT = re.compile(
    r"^(?:supporting\s+talent|with|featuring|plus|and|to|of|for|at|in|by)\s*$", re.I)


def split_support(raw, lookup):
    if not raw:
        return []
    line = re.sub(r"^\s*supporting\s+talent\s*[:\-]?\s*", "", raw, flags=re.I)
    acts = []
    for part in re.split(r"[,;]", line):
        a = re.sub(r"\s+", " ", part).strip(" -—&.")
        a = re.sub(r"^(?:with|featuring|plus|and)\s+", "", a, flags=re.I).strip()
        if a and len(a) > 1 and not NON_ACT.match(a):
            acts.append(a)
    seen, out = set(), []
    for a in acts:
        if a.lower() in seen:
            continue
        seen.add(a.lower())
        out.append(a)
    return [apple_music.artist_obj(a, lookup) for a in out]


def main():
    rows = json.load(open(os.path.join(CACHE, "events.json")))
    lookup = apple_music.load_lookup_cache(os.path.join(CACHE, "lookup.json"))

    shows = []
    for r in rows:
        raw_head = r.get("title")
        if not raw_head:
            continue
        # A headliner billed "Name — Tour" / "Name: Tour" keeps the tour as
        # show_title so the real act resolves in Apple Music.
        head_name, tail = _split_headliner(raw_head)
        tour = tail
        # A status-word headliner (POSTPONED / CANCELED) is a marker, not an
        # artist — the real act is the tour-tail. Re-key BEFORE the lookup.
        head_name, tour, status_note = build.rekey_status_headliner(head_name, tour)
        head = apple_music.artist_obj(head_name, lookup)
        support = split_support(r.get("support"), lookup)

        shows.append(build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[head],
            support_artists=support,
            multi_artist=bool(support) or "&" in (head_name or ""),
            show_title=tour,
            note=status_note,
            date=r.get("date"),
            doors=r.get("doors"),
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("url"),
            age_rating=r.get("age"),
        ))

    stats = {
        "event_types": {"music": len(shows)},
        "apple_music": apple_music.apple_music_stats(shows),
    }
    build.apply_spotify_lookup(shows, os.path.join(CACHE, "spotify_lookup.json"))

    stats["spotify"] = spotify.stats(shows)
    path = build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    am = stats["apple_music"]
    print(f"built {len(shows)} shows -> {path}")
    print(f"  event_types: {stats['event_types']}")
    print(f"  apple_music: {am}")


def _split_headliner(name):
    """'Name — Tour' / 'Name: Tour' -> ('Name', 'Tour'). Only a short,
    tour-shaped tail is treated as a tour (mirrors the Greek/Independent
    colon-tail handling)."""
    if not name:
        return None, None
    m = re.search(r"[:—–-]\s+([^.!?]{3,48})\s*$", name)
    if m:
        tail = m.group(1).strip()
        head = name[:m.start()].strip(" -—–:").strip()
        if head and len(head) >= 2 and len(head) < len(name):
            return head, tail
    return name, None


if __name__ == "__main__":
    main()
