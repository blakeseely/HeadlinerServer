#!/usr/bin/env python3
"""Build data/shows.json for Brick & Mortar Music Hall (venue adapter).

Input: cache/events.json — fetch.py output, one record per show:
{url, title, date ("October 20, 2026"), doors, show_time, age,
 ticket_status, ticket_link, description}.

Title grammar seen in the wild (all live music, a small 250-cap venue):
  "Tōth + Sean Nicholas Savage"                       (+ bill)
  "Yana — The Feelings Are Forever Tour"              (name — tour)
  "REZN + lowheaven + Mountaineer"                    (+ bill)
  "natalie jinju, Chiabiee"                          (name, support)
  "jackzebra — Zhuang Zhuang 2026 Tour"              (name — tour)
  "MISSIO: Love & Heartbreak Tour w/ Fifteenoeight, Kent Osborne"
                                                     (name: tour w/ support)
  "Blue Light with Sassy 009, Swordes, & Tricky FM"  (name w/ support, & tail)

Bill parsing: support is the trailing ", …" / "w/ …" / "with …" tail after the
headliner; a leading "Name: Tour" / "Name — Tour" splits the tour off. `+`
bills are multi-headline (each part is a headliner). Act names may themselves
contain "&"/"and" INSIDE them, so the &-tail is treated as support only, and
comma/`&` split support into separate acts.
"""
import os, re, sys, json, datetime
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

VENUE = "Brick & Mortar Music Hall"
VENUE_ID = "brickandmortar"
VENUE_URL = "https://www.brickandmortarmusic.com/"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}
MONTHS_ABBR = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_date(s):
    """'October 20, 2026' -> '2026-10-20'."""
    if not s:
        return None
    m = re.search(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if not m:
        return None
    mon = MONTHS.get(m.group(1).capitalize()) or MONTHS_ABBR.get(
        m.group(1)[:3].capitalize())
    if not mon:
        return None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


TOUR_WORDS = re.compile(
    r"\b(?:tour|world tour|hype|live|festival|show|season|touring|"
    r"anniversary|celebrat\w*|evening|night|retrospect|debut|album|"
    r"release|new album|new music)\b", re.I)


def _looks_like_tour(s):
    """A short tail that contains a tour-ish word — tour titles put the word
    anywhere ('Zhuang Zhuang 2026 Tour', 'Love & Heartbreak Tour'), and band
    names almost never contain them. Long tails are treated as names, not tours."""
    s = (s or "").strip()
    if len(s) > 34:
        return False
    return bool(TOUR_WORDS.search(s))


def split_support(s):
    """Split a support string into acts. Split on commas and on a leading or
    'and'-/`&`-joined trailing act; act names may keep an internal '&'. Drop
    descriptor words. `&`/`and` inside a name are kept (split on a space
    around them, which turns them into separate acts — the usual intent)."""
    if not s:
        return []
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*[,&]\s*(?=[A-Z])", ",", s)      # ", & X" / ", X" -> ", X"
    s = re.sub(r"\s+and\s+(?=[A-Z])", ",", s)      # " and X" -> ", X"
    parts = [clean(p) for p in re.split(r",+", s)]
    return [p for p in parts if p]


def split_title(title):
    """-> (headline_artists[], support[], tour|None)

    `+` = multi-headline bill (keep them ALL as headliners).
    `:` / `—` / `-` tail = a tour ONLY when it reads as one.
    `w/` / `with` / trailing `… , …` = support.
    """
    t = re.sub(r"\s+", " ", (title or "")).strip()

    heads = [clean(h) for h in re.split(r"\s*\+\s*", t)]
    heads = [h for h in heads if h]
    if not heads:
        return [], [], None

    tour = None
    last = heads[-1]

    # Support is the "w/ …" / "with …" / trailing "… , …" tail of the last
    # billed act. Split it OFF FIRST, so a tour tail after a support marker
    # ("MISSIO: … Tour w/ X, Y") is judged on the tour alone, not the bill.
    support = []
    m = re.search(r"\s*(?:w/|with)\s+", last or "", re.I)
    if m:
        support = split_support((last or "")[m.end():])
        last = (last or "")[:m.start()].strip()
    else:
        m = re.search(r",", last or "")
        if m:
            support = split_support((last or "")[m.end():])
            last = (last or "")[:m.start()].strip()
    if last:
        heads = heads[:-1] + [clean(last)] or heads

    # Now the tour tail: "Name: Tour" / "Name — Tour" (single billed act, or a
    # colon-tail that no longer contains support).
    if last and ":" in last:
        a, b = last.split(":", 1)
        a, b = a.strip(), b.strip()
        if len(a) >= 2 and len(b) >= 2 and _looks_like_tour(b):
            tour = b
            last = a
        elif len(a) >= 2 and len(b) >= 2 and not _looks_like_tour(b):
            # not a tour: the tail is a second act
            last = f"{a}, {b}"
        else:
            last = a
    if len(heads) == 1 and last:
        m = re.match(r"^(.{2,40}?)\s*[–—-]\s+(.{3,40})$", last)
        if m and _looks_like_tour(m.group(2)) and not _looks_like_tour(m.group(1)):
            tour = m.group(2)
            last = m.group(1)
    if last:
        heads = heads[:-1] + [clean(last)] or heads

    heads = [h for h in heads if h]
    support = [s for s in support if s
               and not any(s.lower() == h.lower() for h in heads if h)]
    return heads, support, tour


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        heads, support, tour = split_title(r.get("title"))
        if not heads or not any(heads):
            continue

        heads = [h for h in heads if h]
        doors = clean(re.sub(r"^\s*(Doors|Show)\s*:\s*", "", r.get("doors") or ""))

        note = None
        rec = common_build.show(
            event_type="music",
            needs_review=False,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(heads) > 1,
            show_title=tour,
            description=r.get("description"),
            date=parse_date(r.get("date")),
            doors=doors or None,
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("url"),
            age_rating=r.get("age") or None,
            note=note,
        )
        shows.append(rec)

    spotify.merge_shows(shows, spotify.from_captures(rows, url_key="url"))
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, VENUE_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in shows:
        h = " + ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        print(f"  {s['date'] or '?'}  {h[:40]:40} {('+' + sup)[:28]:28} "
              f"{s.get('ticket_status') or ''}")
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found "
          f"({st['exact']} exact, {st['close']} close, {st['flagged']} flagged), "
          f"{st['not_found']} not found")
    for s in shows:
        for a in s["headline_artists"] + s["support_artists"]:
            if not a["found"] and a.get("confidence") is not None:
                print(f"  not-found: {a['name']} (closest {a['matched']} @ {a['confidence']})")


if __name__ == "__main__":
    main()
