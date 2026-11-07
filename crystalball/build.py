#!/usr/bin/env python3
"""Build data/shows.json for Crystal Ballroom (venue adapter).

Input: cache/shows.json — fetch.py output, one record per CARD show:
{date, start_iso, end_iso, all_day, head_billed, support_billed,
special_billing, promoter, ticket_status_raw, ticket_link, event_page,
rest_title, cost, description, doors, show_time, age}

Bill grammar: the card's h1 is the billed head (may carry a tour tail,
"Sienna Spiro: My House Tour") and the h2 is the support clause ("with
special guest Summer Joy"). The two fields are joined with a space and run
through common.bill.parse_bill — the shared TicketWeb grammar — which
handles the colon/dash tour tail, the "with / with special guest / w/"
clause (dropping the 'special guest' boilerplate), and '+' / ' x '
co-headline bills. A support field that carries NO with-clause is joined as
" x " so it parses as a co-headline, never fused into the head name.

show_time: the venue's detail-page line ("8pm show") wins; otherwise the TEC
start_date (verified to be the SHOW start, not doors). doors: only the
detail-page line (the venue does not publish doors elsewhere). age_rating:
the detail-page age note (the venue's only age source).

Crystal Ballroom is a music room with occasional comedy bills and no venue
taxonomy — event_type is derived from the venue's OWN title/description copy
with a TIGHT comedy regex (the Fox Oakland lesson: never include loose words
like "laugh"). No per-room, no venue-published Spotify links: Spotify comes
from the API lookup (registry has_spotify_lookup).
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music, bill
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")

VENUE = "Crystal Ballroom"
VENUE_ID = "crystalball"
VENUE_URL = "https://www.crystalballroompdx.com/"
SOURCE_URL = "https://www.crystalballroompdx.com/wp-json/tribe/events/v1/events"

# TIGHT comedy regex (the Fox Oakland rule: no bare 'laugh'). 'Comedy
# Central' — the TV channel in a bio — must not count as a comedy bill
# (the Super Diamond Neil Diamond tribute misfire, 2026-11).
COMEDY_BLOB_PREP = re.compile(r"(?i)comedy\s+central")
COMEDY_RE = re.compile(
    r"comedy|comedian|stand.?up|one.?man show|roast|comedy special|"
    r"comedy tour|joke festival", re.I)

# Button domain observed so far: only "Tickets" (the buy-button). Any NEW
# button text keeps the venue wording verbatim (status fallthrough lesson).
_STATUS_MAP = {"tickets": "on sale"}

_WITH_CLAUSE_RE = re.compile(r"^\s*(?:w/?|with|featuring|feat\.?|&|\+|x)\b", re.I)
# the h2 subtitle sometimes bills the headliner's own TOUR, not support
# ("Presents Still Searching" on Senses Fail, "Distracted AF Tour" on
# Thundercat) — join it as a dash tail so common.bill keeps it as the show
# title instead of inventing a co-headliner.
_TOUR_CLAUSE_RE = re.compile(r"^\s*(?:presents?\b)|\btour\b[\s\d]*$", re.I)
# 'An evening with X' bills the FRAMED SHOW as the headliner (the chapel/
# pappy precedent: keep the whole title as one name — the Apple engine
# resolves X via compound-part search). Never let split_support make
# 'An evening' the headliner.
_EVENING_RE = re.compile(r"(?i)^an?\s+(?:evening|night)\s+(?:with|at|with:)\b")


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def billed_title(r):
    """Re-assemble the full billed title so common.bill can parse it."""
    head = _clean(r.get("head_billed")) or ""
    sup = _clean(r.get("support_billed")) or ""
    sp = _clean(r.get("special_billing")) or ""
    title = head
    for extra in (sup, sp):
        if not extra:
            continue
        if _TOUR_CLAUSE_RE.match(extra):
            title += " — " + extra
        elif _WITH_CLAUSE_RE.match(extra):
            title += " " + extra
        else:
            title += " x " + extra
    return title


def fmt_start(iso):
    """'2026-11-07 20:00:00' -> '8:00 pm' (None if no real time)."""
    m = re.match(r"\d{4}-\d{2}-\d{2} (\d{2}):(\d{2}):\d{2}", iso or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h == 0 and mi == 0:
        return None
    ampm = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {ampm}"


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        raw = billed_title(r)
        if not raw:
            continue
        parsed = bill.parse_bill(raw) if not _EVENING_RE.match(raw) else \
            {"heads": [raw], "support": [], "needs_review": False, "tour": None}
        tour = _clean(parsed.get("tour"))
        if tour:
            tour = re.sub(r"(?i)^presents?\s+", "", tour).strip() or None
        heads = [_clean(h) for h in parsed["heads"]]
        heads = [h for h in heads if h]
        if not heads:
            heads = [_clean(raw)]
        support = [_clean(s) for s in parsed["support"]]
        support = [s for s in support if s]

        head_l = {h.lower() for h in heads}
        support = [s for s in support if s.lower() not in head_l]

        blob = " ".join(filter(None, [raw, r.get("description")]))
        blob = COMEDY_BLOB_PREP.sub(" ", blob)
        if re.search(r"(?i)\b(?:bazaar|brewfest|craft market|holiday market|art ?tour)\b", raw):
            event_type = "other"   # the venue's recurring non-show programming (Brewfest class)
        elif COMEDY_RE.search(blob):
            event_type = "comedy"
        else:
            event_type = "music"

        st_raw = _clean(r.get("ticket_status_raw"))
        status = (_STATUS_MAP.get(st_raw.lower(), st_raw) if st_raw
                  else None)

        presenters = [_clean(r.get("promoter"))] if _clean(r.get("promoter")) else None

        rec = common_build.show(
            event_type=event_type,
            needs_review=bool(parsed.get("needs_review")),
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=tour,
            presenters=presenters,
            date=r.get("date"),
            doors=_clean(r.get("doors")),
            show_time=_clean(r.get("show_time")) or fmt_start(r.get("start_iso")),
            ticket_link=r.get("ticket_link"),
            ticket_status=status,
            event_page=r.get("event_page"),
            room=None,
            age_rating=_clean(r.get("age")),
            description=r.get("description"),
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

    print(f"built {len(shows)} shows")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("with doors:", sum(1 for s in shows if s.get("doors")),
          "| with age:", sum(1 for s in shows if s.get("age_rating")))
    review = [s for s in shows if s.get("needs_review")]
    if review:
        print(f"needs_review: {len(review)}")
        for s in review:
            print("    ", s.get("date"),
                  [a["name"] for a in s["headline_artists"]])
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found "
          f"({st['exact']} exact, {st['close']} close, {st['flagged']} flagged), "
          f"{st['not_found']} not found")
    print("spotify:", stats["spotify"])
    for s in shows:
        for a in s["headline_artists"] + s["support_artists"]:
            if not a.get("apple_music") and a["confidence"] is not None:
                print(f"  not-found: {a['name']} "
                      f"(closest {a['matched']} @ {a['confidence']})")


if __name__ == "__main__":
    main()
