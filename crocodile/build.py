#!/usr/bin/env python3
"""Build data/shows.json for The Crocodile from the TicketWeb venue-page
JSON-LD window (see ../common/ticketweb.py for source + header lessons).
Billed names come as comma lists in the LD name field — proven parse_bill
grammar; TheaterEvent entries (non-concert bookings) get event_type other."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill, spotify, build as common_build, ticketweb

VENUE = "The Crocodile"
VENUE_ID = "crocodile"
VENUE_URL = "https://www.thecrocodile.com/"
SOURCE_URL = ticketweb.VENUE_URL


def _norm_clock(dt):
    # "2026-11-10T20:00" (correct local clock, verified 2026-11-07)
    t = (dt or "")[11:16]
    if not re.match(r"^\d{2}:\d{2}$", t):
        return None
    hh, mm = int(t[:2]), t[3:]
    suf = "am" if hh < 12 else "pm"
    h12 = hh % 12 or 12
    return f"{h12}{':'+mm if mm!='00' else ''}{suf}"


import re
if __name__ == "__main__":
    import datetime
    data = json.load(open(os.path.join(HERE, "cache", "ticketweb.json")))
    lookup = apple_music.load_lookup_cache(os.path.join(HERE, "cache", "lookup.json"))
    today = datetime.date.today().isoformat()
    shows = []
    for e in data["events"]:
        name = re.sub(r"\s+", " ", (e.get("name") or "").strip())
        date = (e.get("startDate") or "")[:10]
        if not name or not date or date < today:
            continue
        etype = "music" if "Music" in str(e.get("@type")) else "other"
        parsed = bill.parse_bill(name) if etype == "music" else {"heads": [name], "support": [], "tour": None}
        heads = [h.strip(" -–—,.|:;") for h in parsed["heads"] if h.strip()] or [name]
        support = [s.strip(" -–—,.|:;") for s in parsed["support"] if s.strip()]
        offers = e.get("offers") or {}
        rec = common_build.show(
            event_type=etype,
            needs_review=False,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=None,
            date=date,
            doors=None,
            show_time=_norm_clock(e.get("startDate")),
            ticket_link=offers.get("url") or e.get("url"),
            ticket_status=ticketweb.map_status(e) or "on sale",
            event_page=e.get("url"),
            room=None,
            age_rating=None,
            note=None,
        )
        shows.append(rec)
    shows.sort(key=lambda s: (s.get("date") or "9999"))
    common_build.apply_spotify_lookup(shows, os.path.join(HERE, "cache", "spotify_lookup.json"))
    from collections import Counter
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    print(f"built {len(shows)} shows from {len(data['events'])} LD events")
    print("status:", Counter(s["ticket_status"] for s in shows))
    print("support:", sum(1 for s in shows if s["support_artists"]),
          "| show_time:", sum(1 for s in shows if s.get("show_time")))
