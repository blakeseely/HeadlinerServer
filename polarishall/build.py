#!/usr/bin/env python3
"""Build data/shows.json for Polaris Hall (venue adapter).

Input: cache/shows.json — fetch.py output, one record per card:
{date, date_text, presenter, title, support_billed, doors, show_time,
ticket_link, cta_text}

Bill grammar is the shared one (parse_bill handles the "X - … Tour" dash
tails; "An Evening With X" stays one headliner). The venue's constant
"Polaris Hall Presents" presenter line is skipped (venue self-presenting,
no information content). Doors/show normalize "7:30PM"->"7:30pm".
Get Tickets -> on sale, Sold Out -> sold out; unexpected CTA text passes
through verbatim (status fallthrough lesson). Past cards (the stale
yesterday card) drop. Music room — tight comedy regex on the title only.
age_rating: null — the site carries no age data (etix-only, bot-walled).
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")

VENUE = "Polaris Hall"
VENUE_ID = "polarishall"
VENUE_URL = "https://polarishall.com/"
SOURCE_URL = "https://polarishall.com/"

_EVENING_RE = re.compile(r"(?i)^an?\s+(?:evening|night)\s+(?:with|at|with:)\b")
_COLON_PRESENTER_RE = re.compile(r"^(.{2,45}?)\s+presen(?:ts|t)\s*[:&]\s*(?=\S)", re.I)
COMEDY_RE = re.compile(
    r"comedy|comedian|stand.?up|one.?man show|roast|comedy special|"
    r"comedy tour|joke festival", re.I)


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def norm_time(t):
    if not t:
        return None
    m = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*a\.?\s*m\.?$", t.strip()) \
        or re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*p\.?\s*m\.?$", t.strip())
    if not m:
        return t.strip()
    h, mm = int(m.group(1)), m.group(2)
    ap = "am" if re.search(r"(?i)a\.?\s*m\.?\s*$", t) else "pm"
    if mm == "00":
        mm = None
    return f"{h}{(':'+mm) if mm else ''}{ap}"


def main():
    rows = json.load(open(CAL))
    today = __import__("datetime").date.today().isoformat()
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows, dropped_past = [], 0
    for r in rows:
        raw = _clean(r.get("title"))
        if not raw:
            continue
        if r.get("date") and r["date"] < today:
            dropped_past += 1
            continue

        presenters = []
        p = _clean(r.get("presenter"))
        if p and VENUE.split()[0].lower() not in p.lower():
            presenters.append(p)
        m = _COLON_PRESENTER_RE.match(raw)
        if m:
            presenters.append(m.group(1).strip(" -–—,.|:;"))
            raw = raw[m.end():]

        parsed = bill.parse_bill(raw) if not _EVENING_RE.match(raw) else \
            {"heads": [raw], "support": [], "needs_review": False, "tour": None}
        tour = _clean(parsed.get("tour"))
        heads = [_clean(h) for h in parsed["heads"]]
        heads = [h for h in heads if h] or [raw]
        support = [_clean(s) for s in parsed["support"]]
        support = [s for s in support if s and s.lower() not in {h.lower() for h in heads}]
        sb = _clean(r.get("support_billed"))
        if sb:
            for s in re.split(r",|\band\b", sb):
                s = _clean(re.sub(r"(?i)^(?:w/?|with(?:\s+(?:special|musical)\s+guests?)?|featuring|feat\.?)\s+", "", s.strip()))
                if s and s.lower() not in {h.lower() for h in heads} and \
                   s.lower() not in {x.lower() for x in support}:
                    support.append(s)

        cta = r.get("cta_text")
        status = {"get tickets": "on sale", "sold out": "sold out"}.get(
            (cta or "").lower(), cta or None)

        event_type = "comedy" if COMEDY_RE.search(raw) else "music"

        rec = common_build.show(
            event_type=event_type,
            needs_review=bool(parsed.get("needs_review")),
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=tour,
            presenters=presenters or None,
            date=r.get("date"),
            doors=norm_time(r.get("doors")),
            show_time=norm_time(r.get("show_time")),
            ticket_link=r.get("ticket_link"),
            ticket_status=status,
            event_page=None,
            room=None,
            age_rating=None,
        )
        shows.append(rec)

    lookup_stats = apple_music.apple_music_stats(shows)
    common_build.apply_spotify_lookup(
        shows, os.path.join(ROOT, "cache", "spotify_lookup.json"))
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": lookup_stats,
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)

    print(f"built {len(shows)} shows (dropped past cards: {dropped_past})")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]),
          "| with doors:", sum(1 for s in shows if s.get("doors")),
          "| with support:", sum(1 for s in shows if s["support_artists"]))
    review = [s for s in shows if s.get("needs_review")]
    if review:
        print(f"needs_review: {len(review)}")
        for s in review[:6]:
            print("    ", s.get("date"), [a["name"] for a in s["headline_artists"]])


if __name__ == "__main__":
    main()
