#!/usr/bin/env python3
"""Build data/shows.json for Roseland Theater (venue adapter).

Input: cache/shows.json — fetch.py output, one record per card:
{date, date_text, head_billed, support_billed, promoter, doors, show_time,
age, note, cost, cta_class, ticket_link, event_page}

Bill grammar = the Wonder Ballroom rules (same plugin family): venue status
prefixes written INTO titles (*CANCELLED* kept as cancelled; *Postponed*
kept with note+needs_review; *MOVED TO <other venue>* dropped), "X
PRESENTS:" glued promoters split off, EN-dash bill separator mapped to the
em dash the shared grammar understands, clause-less support joined as ' x '
co-headline. Live Nation passes through as a presenter like any promoter.

Roseland extra: the notes box (rhp-event-notes-box) splits into age_rating
(leading age phrase) + note (the rest, verbatim) in fetch.py.

CTA classes on-sale/sold-out map to vocabulary; new classes pass through
verbatim (status fallthrough lesson). Large room (AEG-adjacent tours):
music room, comedy bills would arrive via the promoter taxonomy — none seen
2026-11-06, so event_type stays 'music' with a TIGHT comedy regex on the
title only (Live Nation bios always mention comedians… they don't, but the
Fox Oakland lesson says keep it tight and title-only here).
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

VENUE = "Roseland Theater"
VENUE_ID = "roseland"
VENUE_URL = "https://roselandpdx.com/"
SOURCE_URL = "https://roselandpdx.com/events/"

_STATUS_MAP = {"on-sale": "on sale", "sold-out": "sold out", "off-sale": "off sale"}

_WITH_CLAUSE_RE = re.compile(r"^\s*(?:w/?|with|featuring|feat\.?|&|\+|x)\b", re.I)
_TOUR_CLAUSE_RE = re.compile(r"^\s*(?:presents?\b)|\btour\b[\s\d]*$", re.I)
_EVENING_RE = re.compile(r"(?i)^an?\s+(?:evening|night)\s+(?:with|at|with:)\b")
_STATUS_PREFIX_RE = re.compile(r"^\s*\*{1,3}\s*([^*]+?)\s*\*{1,3}\s*")
_COLON_PRESENTER_RE = re.compile(r"^(.{2,45}?)\s+presen(?:ts|t)\s*[:&]\s*(?=\S)", re.I)
_MOVED_RE = re.compile(r"(?i)moved\s+to\s+(\S.*)")
COMEDY_RE = re.compile(
    r"comedy|comedian|stand.?up|one.?man show|roast|comedy special|"
    r"comedy tour|joke festival", re.I)


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def billed_title(r):
    head = _clean(r.get("head_billed")) or ""
    sup = _clean(r.get("support_billed")) or ""
    title = head
    if sup:
        if _TOUR_CLAUSE_RE.match(sup):
            tail = re.sub(r"(?i)^presents?\s+", "", sup).strip()
            title += " — " + (tail or sup)
        elif _WITH_CLAUSE_RE.match(sup):
            title += " " + sup
        else:
            title += " x " + sup
    return title


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows, moved = [], []
    for r in rows:
        raw = billed_title(r)
        if not raw:
            continue

        note_parts, forced_status, needs = [], None, False
        if r.get("note"):
            note_parts.append(r["note"])
        m = _STATUS_PREFIX_RE.match(raw)
        if m:
            tag = m.group(1).strip()
            raw = raw[m.end():].strip()
            mm = _MOVED_RE.search(tag)
            if mm:
                moved.append(f"{r.get('date')}  {tag}  ({r.get('head_billed')[:60]})")
                continue
            note_parts.append(f"venue bills it as *{tag}*")
            needs = True
            if "cancel" in tag.lower():
                forced_status = "cancelled"

        presenters = [_clean(r.get("promoter"))] if _clean(r.get("promoter")) else []
        m = _COLON_PRESENTER_RE.match(raw)
        if m:
            presenters.append(m.group(1).strip(" -–—,.|:;"))
            raw = raw[m.end():]

        raw = re.sub(r"\s+\u2013\s+", " \u2014 ", raw)

        parsed = bill.parse_bill(raw) if not _EVENING_RE.match(raw) else \
            {"heads": [raw], "support": [], "needs_review": False, "tour": None}
        tour = _clean(parsed.get("tour"))
        heads = [_clean(h) for h in parsed["heads"]]
        heads = [h for h in heads if h]
        if not heads:
            heads = [_clean(raw)]
        support = [_clean(s) for s in parsed["support"]]
        support = [s for s in support if s]
        head_l = {h.lower() for h in heads}
        support = [s for s in support if s.lower() not in head_l]

        st_raw = r.get("cta_class")
        status = forced_status or (_STATUS_MAP.get(st_raw, st_raw) if st_raw else None)

        event_type = "comedy" if COMEDY_RE.search(raw) else "music"

        rec = common_build.show(
            event_type=event_type,
            needs_review=bool(parsed.get("needs_review")) or needs,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=tour,
            presenters=presenters or None,
            date=r.get("date"),
            doors=_clean(r.get("doors")),
            show_time=_clean(r.get("show_time")),
            ticket_link=r.get("ticket_link"),
            ticket_status=status,
            event_page=r.get("event_page"),
            room=None,
            age_rating=_clean(r.get("age")),
            note="; ".join(note_parts) or None,
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
          "| with age:", sum(1 for s in shows if s.get("age_rating")),
          "| with support:", sum(1 for s in shows if s["support_artists"]))
    if moved:
        print("DROPPED — billed as moved to another venue:")
        for line in moved:
            print("    ", line)
    review = [s for s in shows if s.get("needs_review")]
    if review:
        print(f"needs_review: {len(review)}")
        for s in review:
            print("    ", s.get("date"), [a["name"] for a in s["headline_artists"]], "|", s.get("note"))


if __name__ == "__main__":
    main()
