#!/usr/bin/env python3
"""Build data/shows.json for Cafe du Nord (venue adapter).

Input: cache/shows.json — fetch.py output, one record per show across both
rooms: {date, room, room_name, presenter, headliner, support_raw, doors,
doors_iso, show_time, show_iso, age, ticket_status, ticket_link, event_page,
description}.

The listing is already cleanly structured, so this adapter is mostly a 1:1
map. The one field with a real rule is the support line:

  * The venue bills support as a comma-separated list of acts, and each act
    name may itself contain "&" or "and" — "Jesse Sykes & The Sweet Hereafter
    (duo)" is ONE band, "Conspiracy of Beards, Daniel Kahn and Jake Shulman-
    Ment" is TWO acts (the comma is the separator; the "&"/"and" live inside
    a single act). So support splits on COMMA ONLY, never on &/and.
  * A leading "with" is already stripped by fetch; a trailing parenthetical
    like "(DJ Set)" / "(duo)" is a set-format note, not part of the act name,
    so it is stripped before the Apple Music lookup.

The headliner is always treated as ONE act (a band or a billed event like
"San Francisco Leonard Cohen Festival" or the compound name "Dave Hause &
The Mermaid") — the Apple Music engine decides whether a compound/odd name
resolves; we never split the headliner line.

The room is surfaced via the shared `room` field (Swedish American Hall is
the upstairs room; the eponymous Cafe du Nord is downstairs) so a Nov-6
double-header (festival upstairs, IAN SWEET downstairs) is unambiguous.
Cafe du Nord bills live music only, so every show is `music` and every act is
matched to Apple Music.
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "Cafe du Nord"
VENUE_ID = "cafedunord"
VENUE_URL = "https://cafedunord.com/"
SOURCE_URL = "https://cafedunord.com/shows"

# A parenthetical after an act name that describes the SET, not the act —
# "(DJ Set)", "(duo)", "(live)", "(acoustic)"… stripped before the lookup.
SET_NOTE_RE = re.compile(
    r"\s*\((?:dj[\s-]?set|set|live|live[\s-]?set|duo|trio|acoustic|"
    r"one[\s-]?man[\s-]?show|solo|band|w/|with[\s-]?[a-z]+)\)", re.I)


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def _strip_set_note(name):
    """'Rex DeTiger (DJ Set)' -> 'Rex DeTiger'; '… (duo)' -> '…'."""
    prev = None
    while prev != name and name:
        prev = name
        name = SET_NOTE_RE.sub("", name).strip()
    return _clean(name)


def split_support(raw):
    """A support line -> [names...]. Splits on COMMA ONLY (see module
    docstring): '&' and 'and' are part of single act names, never separators."""
    if not raw:
        return []
    parts = [_strip_set_note(p) for p in re.split(r",", raw)]
    return [p for p in parts if p and len(p) >= 2]


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        head = _clean(r.get("headliner"))
        if not head:
            continue
        support = split_support(r.get("support_raw"))

        # De-dupe a support act that duplicates the headliner (some bills do).
        head_l = head.lower()
        support = [s for s in support if s.lower() != head_l]

        presenter = _clean(r.get("presenter"))
        presenters = ([presenter] if presenter else None)

        # Surface the room only for the NON-eponymous (upstairs) room, so the
        # main-room rows stay uncluttered but a same-date double header is
        # still told apart.
        room = None
        if (r.get("room") or "") != "cdn":
            room = r.get("room_name")

        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(head, lookup)],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(support) > 1,
            show_title=None,
            presenters=presenters,
            date=r.get("date"),
            doors=_clean(r.get("doors")),
            show_time=_clean(r.get("show_time")),
            ticket_link=r.get("ticket_link"),
            ticket_status=_clean(r.get("ticket_status")),
            event_page=r.get("event_page"),
            room=room,
            age_rating=_clean(r.get("age")),
            description=r.get("description"),
        )
        shows.append(rec)

    spotify.merge_shows(shows, spotify.from_captures(rows, url_key="event_page"))
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("roomed (upstairs):", sum(1 for s in shows if s.get("room")))
    print("\n--- full list ---")
    for s in sorted(shows, key=lambda x: x.get("date") or ""):
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        print(f"  {s['date'] or '?'}  {h[:30]:30} {s.get('room') or 'cdn':28} "
              f"{('+' + sup)[:30]:30} {s.get('ticket_status') or ''}")
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
