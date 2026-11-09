#!/usr/bin/env python3
"""Build data/shows.json for the SFJAZZ Center (venue adapter).

Input: cache/shows.json — fetch.py output, one record per PERFORMANCE
{date, show_time, headliner, ticket_link, event_page}. The source
(sfshows.app, a curl-able third-party calendar) carries only the billed
artist, the show date, and the show time — no room, age, price, support
line, bios, or Spotify links (those live on the official sfjazz.org detail
pages, which are Cloudflare-walled). So this adapter is a 1:1 map:

  * The billed name is ONE act (the Apple Music engine decides whether a
    compound/odd name resolves; we never split the headliner line).
  * Every show is live music (event_type="music").
  * The official /tickets/... deep link is kept as both event_page and
    ticket_link (genuinely useful; it 403s for us but is the real page).
  * ticket_status is null (the third-party feed publishes no sale state).
  * description / room / age_rating / support are all honestly null.

Spotify: the venue publishes no per-artist links, so the API lookup
(common/spotify_lookup.py, driven by update_all.py via has_spotify_lookup)
is the only Spotify source — apply_spotify_lookup fills artists it can
resolve; obscure/unsigned acts stay null (honest).
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "SFJAZZ Center"
VENUE_ID = "sfjazz"
VENUE_URL = "https://www.sfjazz.org/"
SOURCE_URL = "https://sfshows.app/venues/sfJazz"


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        head = _clean(r.get("headliner"))
        if not head:
            continue
        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(head, lookup)],
            support_artists=[],
            show_title=None,
            presenters=None,
            date=r.get("date"),
            doors=None,
            show_time=_clean(r.get("show_time")),
            ticket_link=r.get("ticket_link"),
            ticket_status=None,
            event_page=r.get("event_page"),
            room=None,
            age_rating=None,
            description=None,
        )
        shows.append(rec)

    # Spotify API backfill (the venue publishes no venue-published links).
    common_build.apply_spotify_lookup(
        shows, os.path.join(HERE, "cache", "spotify_lookup.json"))

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    st = stats["apple_music"]
    print(f"Apple Music: {st['found']}/{st['unique_artists']} unique artists "
          f"found ({st['exact']} exact, {st['close']} close, "
          f"{st['flagged']} flagged), {st['not_found']} not found")
    for s in shows:
        for a in s["headline_artists"]:
            if not a.get("apple_music") and a["confidence"] is not None:
                print(f"  not-found: {a['name']} (closest {a['matched']} "
                      f"@ {a['confidence']})")


if __name__ == "__main__":
    main()
