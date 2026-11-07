#!/usr/bin/env python3
"""Build data/shows.json for Keller Auditorium (venue adapter).

Input: cache/shows.json — fetch.py output, one record per EVENT PAGE.
Keller is a true multiplex (concerts, comedy, Broadway runs, ballet,
lectures), and this is the one venue feed where the event_type enum does
heavy lifting:

  comedy   — tight regex over title+bio (stand-up|comedian|comedy
             tour/show/special|roast|live podcast). "Comedy Central"
             bio-mention rule still applies (never classify on it).
  other    — theater/dance/lecture: musical|broadway|ballet|nutcracker|
             cirque|dance (company|theatre|hol|arts)|\\bplay\\b|opera|
             physici?st|lecture. Broadway runs dominate Keller attendance.
  music    — default (concerts, Oregon Symphony collaborations, tours).
             Apple Music/Spotify matching matters only here.

A run event page (performances[]) explodes into ONE ROW PER PERFORMANCE —
dates "Nov 27" carry no year: year = the run's header year, bumped +1 when
the perf month precedes the run start (cross-year runs), then rows older
than the header start are refused. Standalone events take the header date.

Doors: literal clock times normalize ("6:00 PM"->"6pm"); the venue's
relative phrasing ("1 hour prior to start") passes through VERBATIM —
it's true schedule info, and inventing a time would be worse.
Age: "All ages welcome" normalizes to "All Ages"; everything else verbatim.
"""
import os, re, sys, json, datetime
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music, bill
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")

VENUE = "Keller Auditorium"
VENUE_ID = "keller"
VENUE_URL = "https://www.portland.gov/arts/keller"
SOURCE_URL = "https://www.portland5.com/events"

MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec".split()), 1)}

COMEDY_RE = re.compile(
    r"stand-?up|(?<!central )comedian|comediante|comedia\b|comedy (?:tour|show|special|live|bandit|camp)|"
    r"\broast\b|live podcast", re.I)
THEATER_RE = re.compile(
    r"\bmusical\b|broadway|ballet|\bnutcracker\b|cirque|\bdance\b|dance (?:company|theatre|"
    r"theater|hol|arts|season)|\bplay\b|\bopera\b|illusion|magic show",
    re.I)
TITLE_THEATER_RE = re.compile(
    r"\bmusical\b|broadway|ballet|\bnutcracker\b|\bcirque\b|\bopera\b", re.I)
LECTURE_RE = re.compile(r"physicist|\bscientist\b|\bscience\b|\blecture\b|planetarium", re.I)
# "Comedy Central" bios must not trip comedy (Fox Oakland rule)
_CC_RE = re.compile(r"comedy central", re.I)


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def classify(title, bio, nperf):
    """Taxonomy pass. Comedy scans title+bio (words like comedian/stand-up
    never appear in concert bios). THEATER nouns (musical|broadway|dance
    company…) fire only on RUNS (>=2 performances) or on the TITLE —
    concert bios say 'musical genius' adjectivally and would otherwise
    false-fire on single-night concerts. Lecture/planetarium words are
    safe anywhere."""
    text = f"{title}\n{bio}"
    if COMEDY_RE.search(_CC_RE.sub("", text)):
        return "comedy"
    if TITLE_THEATER_RE.search(title) or LECTURE_RE.search(text):
        return "other"
    if nperf >= 2 and THEATER_RE.search(text):
        return "other"
    return "music"


def norm_time(t):
    if not t:
        return None
    m = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\.?\s*$", t.strip())
    if not m:
        return t.strip()          # venue phrasing passes through verbatim
    h = int(m.group(1))
    mm = m.group(2)
    if mm == "00":
        mm = ""
    return f"{h}{(':'+mm) if mm else ''}{m.group(3).lower()}m"


def norm_age(a):
    if not a:
        return None
    a = a.strip()
    if re.match(r"(?i)^all ages", a):
        return "All Ages"
    return a


def perf_date(date_text, run_start, today):
    """'Nov 27' + run header context -> ISO. Year from run start, bumped
    for cross-year runs; refuse dates before the run start."""
    m = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})", date_text or "")
    if not m or m.group(1).lower()[:3] not in MONTHS or not run_start:
        return None
    mo, day = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
    y = int(run_start[:4])
    if mo < int(run_start[5:7]):
        y += 1
    iso = f"{y}-{mo:02d}-{day:02d}"
    if iso < run_start:
        return None
    return iso


def main():
    events = json.load(open(CAL))
    today = datetime.date.today().isoformat()
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for d in events:
        title = (d.get("title") or "").strip()
        if not title:
            continue
        etype = classify(title, d.get("bio") or "", len(d.get("performances") or []))
        note_parts = []
        forced_status, needs = None, False
        chg = d.get("change_note")
        if chg:
            note_parts.append(chg)
            needs = True
            if re.search(r"(?i)cancel", chg):
                forced_status = "cancelled"
            elif re.search(r"(?i)postpon|reschedul", chg):
                forced_status = "postponed"
        if d.get("card_only"):
            # run card visible but its detail alias is unpublished/redirected
            # (multi-season repeat mid-swap): bill the run's first day with
            # needs_review; self-heals to real per-performance rows nightly
            note_parts.append(f"calendar card only: '{d.get('header_date')}' — "
                              "performance details page not published yet")
            needs = True
        age = norm_age(d.get("age"))
        doors_raw = d.get("doors")
        doors = norm_time(doors_raw) if doors_raw and ":" in doors_raw else (doors_raw or None)
        default_ticket = d.get("cta_href")
        status = forced_status or ("on sale" if (default_ticket or d.get("performances")) else None)
        if (d.get("cta_text") or "").lower().startswith("sold"):
            status = forced_status or "sold out"

        parsed = bill.parse_bill(title)
        tour = _clean(parsed.get("tour"))
        heads = [_clean(h) for h in parsed["heads"]]
        heads = [h for h in heads if h] or [title]
        support = [_clean(s) for s in parsed["support"]]
        support = [s for s in support if s and s.lower() not in {h.lower() for h in heads}]
        for s in d.get("support_billed") or []:
            s = _clean(re.sub(r"\s*\((?:special )?guest\)?\s*$", "", s))
            if s and s.lower() not in {x.lower() for x in heads + support}:
                support.append(s)

        # rows: performances[] or the single header date
        rows = []
        if d.get("performances"):
            for p in d["performances"]:
                iso = perf_date(p.get("date_text"), d.get("date_start"), today)
                if not iso:
                    continue
                pt = norm_time(re.sub(r"(?i)^(mon|tues|tue|wed|thur|thu|fri|sat|sun)day?,?\s*",
                                      "", p.get("time_text") or "")) or None
                rows.append((iso, pt, p.get("ticket") or default_ticket,
                             p.get("perf_note")))
        elif d.get("date_start"):
            rows.append((d["date_start"], norm_time(d.get("show_time")),
                         default_ticket, None))
        if not rows:
            print(f"  drop (no future/parseable date): {title} | {d.get('header_date')}")
            continue

        for iso, show_t, link, pnote in rows:
            if iso < today:
                continue
            note = "; ".join(x for x in note_parts + ([pnote] if pnote else []) if x) or None
            rec = common_build.show(
                event_type=etype,
                needs_review=needs,
                headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
                support_artists=[apple_music.artist_obj(s, lookup) for s in support],
                show_title=tour,
                date=iso,
                doors=doors,
                show_time=show_t,
                ticket_link=link,
                ticket_status=status,
                event_page=d.get("event_page"),
                room=None,
                age_rating=age,
                note=note,
            )
            shows.append(rec)

    shows.sort(key=lambda s: (s.get("date") or "9999"))
    lookup_stats = apple_music.apple_music_stats(shows)
    common_build.apply_spotify_lookup(
        shows, os.path.join(ROOT, "cache", "spotify_lookup.json"))
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": lookup_stats,
        "spotify": spotify.stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)

    print(f"built {len(shows)} shows from {len(events)} event pages")
    print("types:", stats["event_types"])
    print("no doors:", sum(1 for s in shows if not s.get("doors")),
          "| with age:", sum(1 for s in shows if s.get("age_rating")),
          "| with support:", sum(1 for s in shows if s["support_artists"]))
    review = [s for s in shows if s.get("needs_review")]
    if review:
        print(f"needs_review: {len(review)}")
        for s in review[:6]:
            print("    ", s.get("date"), [a["name"] for a in s["headline_artists"]], "|", (s.get("note") or "")[:70])
    for et in ("music", "comedy", "other"):
        ex = [f"{s['date']} {[a['name'] for a in s['headline_artists']][:1]}" for s in shows if s["event_type"] == et][:3]
        print(f"  {et}: {ex}")


if __name__ == "__main__":
    main()
