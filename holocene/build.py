#!/usr/bin/env python3
"""Build data/shows.json for Holocene (venue adapter).

Input: cache/shows.json — fetch.py output: calendar row joined with the
event-page billing ({date, cal_title, event_page, when, price, buy_class,
ticket_link, ev_presenter, ev_title, ev_sub, ev_with, doors, ages, show,
event_status, offers_url, availability, performers, description}).

The venue hands billing on a plate — h1 ev_title IS the headliner, ev_sub
IS the tour, ev_with IS the support clause — so titles are NOT run through
parse_bill (the calendar title "Emo Nite at Holocene presented by Emo Nite
LA" would butcher into headliner 'by Emo Nite LA'). ev_with is split with
a local with-clause stripper (with/w/featuring prefix, then , & /). A
'with'/'&' inside ev_title itself stays verbatim (venue bill as written).

event_type: music room (DJ/rave nights are music — the Club Darc rule);
TIGHT comedy regex (Fox Oakland lesson); the venue's occasional non-music
programming (children's arts assemblies) -> other.

Status: buy_class disabled->sold out, at-door->at the door, plain->on sale
(link present); LD availability SoldOut also maps to sold out; LD
eventStatus EventCancelled -> ticket_status cancelled (+note),
Postponed/Rescheduled -> note + needs_review. doors/ages/show_time verbatim
(the venues' 'Doors' dl wins; show_time from LD startDate — verified the
SHOW start: Emo Nite shows "9PM" in the calendar and startDate T21:00).
"""
import os, re, sys, json
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from common import apple_music
from common import build as common_build
from common import spotify

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")

VENUE = "Holocene"
VENUE_ID = "holocene"
VENUE_URL = "https://www.holocene.org/"
SOURCE_URL = "https://www.holocene.org/events"

COMEDY_RE = re.compile(
    r"comedy|comedian|stand.?up|one.?man show|roast|comedy special|"
    r"comedy tour|joke festival", re.I)
OTHER_RE = re.compile(r"(?i)arts for learning|school assembly|children|kids show")
_WITH_PREFIX_RE = re.compile(r"(?i)^(?:w/?|with(?:\s+(?:special|surprise|musical)\s+guests?)?|featuring|feat\.?)\s+")
_SKIP_SUP = re.compile(r"(?i)^(special guests?|tba|more tba|to be announced)\b")

_BUY_STATUS = {"disabled": "sold out", "at-door": "at the door",
               "plain": "on sale", "crow-buy-none": None}


def _clean(name):
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip(" -–—,.|:;")
    return n or None


def split_with(ev_with):
    if not ev_with:
        return []
    s = _WITH_PREFIX_RE.sub("", ev_with.strip())
    parts = re.split(r",|&|\bwith\b|\band\b| / ", s)
    out = []
    for p in parts:
        p = _clean(p)
        if p and not _SKIP_SUP.match(p):
            out.append(p)
    return out


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        head = _clean(r.get("ev_title")) or _clean(r.get("cal_title"))
        if not head:
            continue
        heads = [head]
        support = split_with(r.get("ev_with"))
        head_l = {h.lower() for h in heads}
        support = [s for s in support if s.lower() not in head_l]
        tour = _clean(r.get("ev_sub"))

        status = _BUY_STATUS.get(r.get("buy_class") or "plain")
        if not r.get("ticket_link") and r.get("offers_url"):
            r["ticket_link"] = r["offers_url"]
        if not status and r.get("ticket_link"):
            status = "on sale"
        if (r.get("availability") or "").lower() == "soldout":
            status = "sold out"

        note_parts, needs = [], False
        st = r.get("event_status")
        if st == "EventCancelled":
            status = "cancelled"
            note_parts.append("venue JSON-LD eventStatus: EventCancelled")
            needs = True
        elif st in ("EventPostponed", "EventRescheduled", "EventCancelledMoved"):
            note_parts.append(f"venue JSON-LD eventStatus: {st}")
            needs = True

        blob = " ".join(filter(None, [head, tour, " ".join(support),
                                      r.get("cal_title"), r.get("description")]))
        if OTHER_RE.search(blob):
            event_type = "other"
        elif COMEDY_RE.search(blob):
            event_type = "comedy"
        else:
            event_type = "music"

        when = _clean(r.get("when"))          # "9PM · 21+" fallback
        age = _clean(r.get("ages"))
        if not age and when and "·" in when:
            age = when.split("·")[-1].strip() or None

        rec = common_build.show(
            event_type=event_type,
            needs_review=needs,
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=tour,
            presenters=[_clean(r.get("ev_presenter"))] if _clean(r.get("ev_presenter")) else None,
            date=r.get("date"),
            doors=_clean(r.get("doors")),
            show_time=_clean(r.get("show")),
            ticket_link=r.get("ticket_link"),
            ticket_status=status,
            event_page=r.get("event_page"),
            room=None,
            age_rating=age,
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
    print("statuses:", dict(Counter(s.get("ticket_status") or "-" for s in shows)))
    review = [s for s in shows if s.get("needs_review")]
    if review:
        print(f"needs_review: {len(review)}")
        for s in review:
            print("    ", s.get("date"), [a["name"] for a in s["headline_artists"]], "|", s.get("note"))


if __name__ == "__main__":
    main()
