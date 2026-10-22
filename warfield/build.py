#!/usr/bin/env python3
"""Build data/shows.json for The Warfield Theatre (venue adapter).

Input: cache/events.json — fetch.py output, one record per show:
{detail_id, event_page, presenter, tour, headliner, support, date (short),
 date_full, show_time, doors, age, ticket_status, ticket_link, description}.

The listing is the Warfield's cleanly-structured backbone: presenter, tour,
headliner, and support are SEPARATE lines, so (unlike August Hall) there is
no single billed string to grammar-parse. The only bill cases to handle:

  * "ft." / "feat." / "with" embedded in the HEADLINER line (a compound bill
    or a support act) — "Cookies Christmas 2026 ft. Berner, Paul Wall, &
    Baby Bash" splits into a headliner + support, each looked up.
  * a bare support line that is a comma/& list — "Sippy, Machaki" -> two
    support artists (vs "with X" -> one).

Everything else maps 1:1: the tour line -> show_title, the presenter line ->
presenters, date_full -> date, doors/age -> the matching shared fields.

The Warfield bills live music only (rock / alt / K-pop / electronic /
theater-musical tours), so every show is `music` and every act is matched to
Apple Music.
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "events.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "The Warfield Theatre"
VENUE_ID = "warfield"
VENUE_URL = "https://www.thewarfieldtheatre.com/"
SOURCE_URL = "https://www.thewarfieldtheatre.com/events/all"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}
SHORT = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_date(s):
    """'Wed, Oct 21, 2026' or 'Wed, October 21, 2026' -> '2026-10-21'."""
    if not s:
        return None
    m = re.match(
        r"[A-Za-z]{3,},\s*([A-Za-z]{3,})\s+(\d{1,2}),\s*(\d{4})", s)
    if not m:
        return None
    mon = MONTHS.get(m.group(1)) or SHORT.get(m.group(1)[:3])
    if not mon:
        return None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


# "Cookies Christmas 2026 ft. Berner, Paul Wall, & Baby Bash" — an "ft./feat./
# with" separator joins a lead to its support within a single billed line.
FT_RE = re.compile(r"\s+(?:ft\.?|feat\.?|with)\s+(?=[A-Z0-9])", re.I)


# "Cookies Christmas 2026 ft. ..." bills a HOST + an EVENT + a YEAR in the
# headliner line. Strip the trailing event-name tail so the real lead act is
# found (and the tail becomes the show_title).
EVENT_TAIL_RE = re.compile(
    r"^(.+?)\s+((?:Christmas|Halloween|Thanksgiving|New\s*Year(?:'s)?|NYE)\s+\d{4})$",
    re.I)


def split_event_tail(name):
    """'Cookies Christmas 2026' -> ('Cookies', 'Christmas 2026').

    Only fires on a trailing season/event word + 4-digit year whose remainder
    still reads as an act; otherwise returns the line untouched. (Fixes the
    'Cookies Christmas 2026' bill, where the host is 'Cookies'.)"""
    m = EVENT_TAIL_RE.match(name or "")
    if not m:
        return name, None
    head, tail = _clean(m.group(1)), m.group(2).strip()
    if head and len(head) >= 2:
        return head, tail
    return name, None


def split_bill(name):
    """A single billed line -> (headliner, [support...]).

    Splits on an "ft./feat./with" marker; the part before is the headliner,
    the part after is a comma/&/and list of support acts. No marker -> the
    whole line is the headliner. Returns (headliner, support, event_tail),
    where event_tail is a trailing 'Christmas 2026' style event name stripped
    from the headliner (becomes the show_title)."""
    n = _clean(name)
    if not n:
        return None, [], None
    m = FT_RE.search(n)
    if not m:
        # no support marker: the whole line is the headliner (but it may still
        # carry a trailing event name, e.g. a solo "Cookies Christmas 2026")
        head, event_tail = split_event_tail(n)
        return head, [], event_tail
    head = _clean(n[:m.start()])
    tail = n[m.end():].strip()
    parts = [_clean(p) for p in re.split(r",|\s*&\s*|\band\b", tail)]
    parts = [p for p in parts if p and len(p) >= 2]
    # the head itself may carry a trailing event name ('Cookies Christmas 2026')
    head, event_tail = split_event_tail(head)
    return head, parts, event_tail


def split_support_line(line):
    """A support line -> [names...]. 'with X' -> [X]; 'A, B' -> [A, B]."""
    if not line:
        return []
    s = re.sub(r"^(?:with|and)\s+", "", line.strip(), flags=re.I)
    parts = [_clean(p) for p in re.split(r",|\s*&\s*|\band\b", s)]
    return [p for p in parts if p and len(p) >= 2]


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        head, ft_support, event_tail = split_bill(r.get("headliner"))
        support = split_support_line(r.get("support"))
        support = ft_support + support

        if not head and not support:
            continue
        heads = [head] if head else []

        # De-dupe support against the headliner (a bill sometimes names the
        # headliner again in the support line).
        heads_l = [h.lower() for h in heads]
        support = [s for s in support if s.lower() not in heads_l]

        tour = _clean(r.get("tour"))
        show_title = tour or event_tail
        presenter = _clean(r.get("presenter"))
        presenters = ([presenter] if presenter and "present" in presenter.lower()
                      else None)

        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(heads) > 1 or len(support) > 1,
            show_title=show_title,
            presenters=presenters,
            date=parse_date(r.get("date_full") or r.get("date")),
            doors=_clean(r.get("doors")),
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("event_page"),
            age_rating=_clean(r.get("age")),
            description=r.get("description"),
        )
        shows.append(rec)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
    }
    common_build.apply_spotify_lookup(shows, os.path.join(ROOT, "cache", "spotify_lookup.json"))
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in sorted(shows, key=lambda x: x.get("date") or ""):
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        print(f"  {s['date'] or '?'}  {h[:42]:42} "
              f"{('+' + sup)[:32]:32} {s.get('ticket_status') or ''}  {s.get('doors') or ''}")
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
