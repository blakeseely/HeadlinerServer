#!/usr/bin/env python3
"""Build data/shows.json for August Hall (venue adapter).

Input: cache/events.json — fetch.py output, one record per show:
{url, title, date ("Friday, October 16, 2026"), doors, show_time, age,
 ticket_status, ticket_link} — title comes from the /tm-event/ detail
page's canonical spelling.

Title grammar seen in the wild (all live music):
  "Actress"
  "Ax and the Hatchetmen: The Late Checkout Tour 2026"   (name: tour)
  "Introducing The Aces with special guest Gatlin"       (name + support)
  "Lil Pete: Real Is Back Tour"                          (name: tour)
  "NICE AS F*#K – BACK AS F**K NICE AS EVER"             (censored name: tour)
  "The Pre-Show Speakeasy with Hazlett"                  (pre-show event)

Mapping:  "name: tour" / "name – tour" split on the colon / en-dash where the
left side reads as an act; "with / with special guest" -> support; "Introducing
X" -> X. Censored names (asterisk runs) that don't match the catalog are
flagged for review rather than guessed at.
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

VENUE = "August Hall"
VENUE_ID = "augusthall"
VENUE_URL = "https://www.augusthallsf.com/"

DATE_RE = re.compile(
    r"([A-Z][a-z]+),\s*([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"], 1)}


def parse_date(s):
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m:
        return None
    mon = MONTHS.get(m.group(2))
    if not mon:
        return None
    return f"{m.group(4)}-{mon:02d}-{int(m.group(3)):02d}"


def strip_prefix(s, *prefixes):
    for p in prefixes:
        if s.lower().startswith(p.lower()):
            s = s[len(p):].strip()
    return s


def clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


TOUR_TAIL_RE = re.compile(
    r"\s+[Tt]our(?:\s+(?:[IiVX]+|USA|\d+(?:\.\d+)?))?\s*$"
    r"|\s+(?:HYPE|WORLD)\s+TOUR\b.*$", re.I)
# head parts that are NOT a plausible act name on their own
BAD_HEAD_RE = re.compile(
    r"^(the|a|an)?\s*(tour|tours|world|usa|live|ii+|iv+|v+|\d+(?:\.\d+)?)$", re.I)


def _plausible_head(head):
    head = (head or "").strip(" -–—:,.!|")
    if len(head) < 2:
        return None
    if BAD_HEAD_RE.match(head):
        return None
    return head or None


# tail halves that are dangling fragments of a longer phrase ("An Evening With"
# with the rest cut off) — not a real tour title; keep the whole string
DANGLE_RE = re.compile(
    r"^(the\s+)?(an?|a|the)?\s*(evening with|night of|tribute to|celebration of)\s*$",
    re.I)


def _real_tour(tail):
    tail = re.sub(r"[!.\s]+$", "", tail or "").strip()
    if len(tail) < 3 or DANGLE_RE.match(tail):
        return None
    return tail


def split_title(title):
    """-> (headliner_name, [support...], tour_title|None)"""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    support, tour = [], None
    set_format = None

    # "Introducing The Aces with special guest Gatlin"
    t = strip_prefix(t, "Introducing")

    # support: "with special guest X" / "with X" (only once, at end)
    m = re.search(r"\s+with(?:\s+special\s+guest)?\s+(?=[A-Z])", t)
    if m:
        head, sup = t[:m.start()].strip(), t[m.end():].strip()
        if 2 <= len(sup) <= 40 and sup not in ("and", "the"):
            support = [clean(sup)] if clean(sup) else []
            t = head

    # "Name: Tour" / "Name – Tour"
    m = re.match(r"^(.{2,50}?)\s*[:\-–—]\s+(.{2,60})$", t)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        a = _plausible_head(a)
        if a and not re.search(r"\b(presents?|festival)\b", a, re.I) and len(a) <= 45:
            tour = _real_tour(b)
            t = a
    else:
        # "DJ Raphi HYPE TOUR USA 2.0" / "Begging For Sax Tour II" — a bare
        # tour name glued onto the act with no separator
        m = re.search(TOUR_TAIL_RE, t)
        if m:
            a, b = t[:m.start()].strip(), t[m.start():].strip()
            a = _plausible_head(a)
            if a:
                tour = _real_tour(b)
                t = a

    # "Live!" / "Live" is a set-format marker, not part of the act name
    m = re.search(r"\s+[Ll]ive!?\s*$", t)
    if m:
        a = _plausible_head(t[:m.start()])
        if a:
            set_format = "Live"
            t = a

    name = clean(t)
    return name, [s for s in support if s], tour, set_format


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        name, support, tour, set_format = split_title(r.get("title"))
        if not name:
            continue

        censored = re.search(r"\*{2,}", name) is not None
        if censored:
            # keep the billed (censored) name verbatim; the venue obscures the
            # real act, so there is no honest variant to look up
            support = [clean(s.replace("*", "")) for s in support]
            support = [s for s in support if s and len(s) >= 2]

        if name.lower().startswith("the pre-show speakeasy"):
            # the pre-show event is billed as its own "with Hazlett"
            support = (support or [])
            if not support:
                m = re.search(r"with\s+(?=[A-Z])", r.get("title") or "")
                if m:
                    support = [clean(r["title"][m.end():])] or []

        heads = [name]
        support = [s for s in support if s
                   and not any(s.lower() == h.lower() for h in heads)]

        doors = clean(strip_prefix(r.get("doors") or "", "Doors:"))
        age = strip_prefix(r.get("age") or "", "Age Restriction:")

        note = None
        if censored:
            note = "billed name is censored by the venue"

        needs_review = bool(censored)

        rec = common_build.show(
            event_type="music",
            needs_review=needs_review,
            headline_artists=[apple_music.artist_obj(h, lookup)
                              for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup)
                             for s in support],
            multi_artist=len(heads) > 1,
            show_title=tour,
            set_format=set_format,
            date=parse_date(r.get("date")),
            doors=doors or None,
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("url"),
            age_rating=age or None,
            note=note,
        )
        shows.append(rec)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
    }
    common_build.apply_spotify_lookup(shows, os.path.join(ROOT, "cache", "spotify_lookup.json"))

    stats["spotify"] = spotify.stats(shows)
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, VENUE_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("types:", stats["event_types"])
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in shows:
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        flag = " \u26a0" if s["needs_review"] else ""
        print(f"  {s['date'] or '?'}  {h[:44]:44} "
              f"{('+' + sup)[:30]:30} {s.get('ticket_status') or ''}{flag}")
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found "
          f"({st['exact']} exact, {st['close']} close, {st['flagged']} flagged), "
          f"{st['not_found']} not found")
    for s in shows:
        for a in s["headline_artists"] + s["support_artists"]:
            if not a["found"] and a["confidence"] is not None:
                print(f"  not-found: {a['name']} (closest {a['matched']} @ {a['confidence']})")


if __name__ == "__main__":
    main()
