#!/usr/bin/env python3
"""Build data/shows.json for the Great American Music Hall (venue adapter).

Input: cache/events.json (fetch.py output) — one record per show from the
greatmusichall.com/events/ JSON-LD block: name, performer, start, date, url,
ticket link/status, price, description. Plus cache/details.json — the
"with support from …" line fetched from each show's detail page.

Everything at the GAMH is live music, so the only classification is
non-music bills (a festival, an awards/poetry night, a Christmas variety
show) -> "other". The booked name is the headliner; the detail page's
support line fills support_artists. Multi-artist names ("Nile & Coroner")
are split into co-headliners; "/" bills likewise.

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

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "events.json")
DET = os.path.join(ROOT, "cache", "details.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "Great American Music Hall"
VENUE_ID = "gamh"
SRC_URL = "https://www.greatmusichall.com/events/"


def _accentless(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if not unicodedata.combining(c))


def eq(a, b):
    return _accentless((a or "").lower()) == _accentless((b or "").lower())


OTHER_RE = re.compile(
    r"\b(festival|christmas|poetry|awards|anniversary night|night of)\b", re.I)

# "(DJ Set)" / "(solo)" style parentheticals are set-format notes, not the
# artist name. Kept out of the display + lookup key.
PAREN_RE = re.compile(r"\s*\((?:dj\s*set|solo|live|acoustic)\)", re.I)


def clean_name(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip()
    n = PAREN_RE.sub("", n).strip(" -\u2013\u2014,.")
    return n or None


def split_name_title(title):
    """'Artist - ShowTitle' / 'Artist: ShowTitle' -> (name, title).
    The GAMH JSON-LD names are almost never split; the '/' and '&' cases
    are co-headliner bills and are handled separately."""
    t = re.sub(r"\s+ ", " ", (title or "")).strip()
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None, None
    m = re.match(r"^(.*?)\s*[-\u2013\u2014:]\s+(.+)$", t)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
        if head and len(head) <= 48 and not re.search(r"\b(presents?|festival)\b", head, re.I):
            return head, re.sub(r"[!\.\s]+$", "", rest) or None
    return t, None


def split_headlines(title):
    """Co-headliner bills: 'Nile & Coroner' -> ['Nile', 'Coroner'];
    'A / B' likewise. A single name -> [name]. The '&' keeps the pair only
    when it reads as a single act (both words lowercase / no comma)."""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    if not t:
        return []
    if "/" in t:
        parts = [p.strip() for p in t.split("/")]
        parts = [p for p in parts if 2 <= len(p) <= 50]
        return parts or [t]
    m = re.search(r"\s*&\s*", t)
    if m:
        a, b = t[:m.start()].strip(), t[m.end():].strip()
        if 2 <= len(a) <= 50 and 2 <= len(b) <= 50:
            return [a, b]
    return [t]


def main():
    rows = json.load(open(CAL))
    details = json.load(open(DET)) if os.path.exists(DET) else {}
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        name = clean_name(r.get("name"))
        if not name:
            continue

        other = bool(OTHER_RE.search(name))
        head_names = split_headlines(name)
        # The JSON-LD 'performer' is authoritative when it's a single name
        # (the venue's own spelling beats the title's casing).
        perf = clean_name(r.get("performer"))
        if perf and len(head_names) == 1 and eq(perf, head_names[0]):
            head_names[0] = perf

        _, show_title = split_name_title(name)

        # Support from the detail page's "with support from …" line.
        support = []
        for s in (details.get(r.get("url"), {}).get("support") or []):
            if any(eq(s, h) for h in head_names):
                continue
            if any(eq(s, x) for x in support):
                continue
            support.append(s)

        doors = show_time = None  # the JSON-LD block carries no times
        rec = common_build.show(
            event_type="other" if other else "music",
            headline_artists=[apple_music.artist_obj(h, lookup) for h in head_names],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            multi_artist=len(head_names) > 1,
            show_title=show_title,
            date=r.get("date"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("event_page"),
            description=r.get("description"),
        )
        if r.get("price"):
            rec["note"] = f"From {r['price']}"
        shows.append(rec)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, SRC_URL, SRC_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in shows:
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        flag = " \u26a0" if s["needs_review"] else ""
        print(f"  {s['event_type']:6} {s['date'] or '?'} {h[:46]:46} "
              f"{('+' + sup)[:34]:34} {s.get('ticket_status') or ''}{flag}")
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
