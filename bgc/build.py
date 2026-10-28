#!/usr/bin/env python3
"""Build data/shows.json for the Bill Graham Civic Auditorium (venue adapter).

Input: cache/events.json — fetch.py output, one record per show:
{date, doors, show_time, headliner, support_raw, age, ticket_status,
 ticket_link, event_page, description, spotify}.

The /calendar listing is already cleanly structured, so this is mostly a 1:1
map. The one field with a real rule is the support line:

  * The venue bills support as <br>-separated entries, and an entry can be a
    comma-separated run of acts ("feat. Warren Haynes, Neal Francis, John
    Molo, ..."). Act names may themselves contain "&" / "and" ("Grahame
    Lesh & Friends" is ONE band), so support splits on COMMA and NEWLINE
    only — never on &/and.
  * A leading "feat. / featuring / with" is a credit, not an act: strip it.
  * A set-format parenthetical ("(DJ Set)", "(duo)") is stripped before the
    Apple Music lookup.

The headliner is always treated as ONE act (the Apple Music engine decides
whether a compound/odd name resolves). BGC bills live music only, so every
show is `music` and every act gets an Apple Music match; the venue's detail
pages publish per-artist Spotify links (extracted in fetch), so this is a
venue-published Spotify venue.

The Auditorium is single-room: `room` stays None (the Theater at BGC is a
separate ticketed space that shares the calendar but is a different venue).
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "events.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
SPOTIFY_CACHE = os.path.join(ROOT, "cache", "spotify_lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "Bill Graham Civic Auditorium"
VENUE_ID = "bgc"
VENUE_URL = "https://billgrahamcivic.com/"
SOURCE_URL = "https://billgrahamcivic.com/calendar"

# A parenthetical after an act name that describes the SET, not the act —
# "(DJ Set)", "(duo)", "(live)"… stripped before the lookup.
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
    """A support block -> [names...]. Splits on NEWLINE (the venue's <br>
    breaks) and COMMA (an entry can be a comma run of acts) ONLY — '&' and
    'and' live inside single act names, never separators."""
    if not raw:
        return []
    parts = []
    for line in raw.split("\n"):
        parts.extend(p for p in line.split(",") if p)
    out = []
    for p in parts:
        p = _strip_set_note(p)
        if not p:
            continue
        # "feat. Warren Haynes, Neal Francis" — the credit applies to the
        # whole entry; strip it off the first part only.
        m = re.match(r"^(?:featuring|feat\.?|w/|with)\s+(.*)$", p, re.I | re.S)
        if m:
            p = m.group(1)
            p = _strip_set_note(p)
        if p and len(p) >= 2 and p.lower() not in {"live", "plus", "and", "the"}:
            if out and out[-1].lower() == p.lower():
                continue
            out.append(p)
    return out


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

        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(head, lookup)],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(support) > 1,
            show_title=None,
            presenters=None,
            date=r.get("date"),
            doors=_clean(r.get("doors")),
            show_time=_clean(r.get("show_time")),
            ticket_link=r.get("ticket_link"),
            ticket_status=_clean(r.get("ticket_status")),
            event_page=r.get("event_page"),
            room=None,  # single-room (the Theater at BGC is a different venue)
            age_rating=_clean(r.get("age")),
            description=r.get("description"),
        )
        shows.append(rec)

    # Venue-published Spotify links win over any searched one.
    spotify.merge_shows(shows, spotify.from_captures(rows, url_key="event_page"))
    # API lookup fills artists the venue published no link for.
    common_build.apply_spotify_lookup(shows, SPOTIFY_CACHE)

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
    print("\n--- full list ---")
    for s in sorted(shows, key=lambda x: x.get("date") or ""):
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        print(f"  {s['date'] or '?'}  {h[:30]:30} "
              f"{('+' + sup)[:34]:34} {s.get('age_rating') or '':6} {s.get('ticket_status') or ''}")
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found "
          f"({st['exact']} exact, {st['close']} close, {st['flagged']} flagged), "
          f"{st['not_found']} not found")
    for s in shows:
        for a in s["headline_artists"] + s["support_artists"]:
            if not a.get("apple_music") and a["confidence"] is not None:
                print(f"  not-found: {a['name']} (closest {a['matched']} @ {a['confidence']})")


if __name__ == "__main__":
    main()
