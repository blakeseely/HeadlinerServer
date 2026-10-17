#!/usr/bin/env python3
"""Build data/shows.json for The Fillmore, San Francisco (venue adapter).

Input: cache/calendar.json (fetch_calendar.py output) — the venue's own RSC
payload: one record per event with the FULL billed artist lineup, so the
build only has to split headliner(s) from support, never parse a bill string.

Name/headliner rules (billed event name reconciled against the venue's own
artists list — the list is the authoritative lineup, the name is display):
  * "Artist - ShowTitle" / "Artist: ShowTitle" -> lead | show_title; the lead
    equals artists[0] case/accent-insensitively -> venue's canonical casing
    ("José Madero"); otherwise the billed lead stands ("The Big Star Quintet").
  * a tour-NAMED lead is not an artist -> artists[0] headlines, the whole
    billed name becomes the show title.
  * no dash/colon -> artists[0] when it is the same name, else the name.
  * multi-night pass placeholders (00:00:01 starts) are dropped.

Support = billed artists minus the headliner (deduped against the headliner's
catalog spelling and against each other), plus "Feat. X and Y" acts from the
title part (solo billings where support is absent from the artists list).

All events at The Fillmore are live music (the venue's "Arts & Theatre"
segment is comedy/variety bills — e.g. Pattie Gonia, Matt Rogers — so it maps
to "other", never "film").

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
CAL = os.path.join(ROOT, "cache", "calendar.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "The Fillmore"
VENUE_ID = "fillmore"
SRC_URL = "https://www.thefillmore.com/shows"


def _accentless(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def eq(a, b):
    """Case- + accent-insensitive name comparison (THE DAMNED == The Damned)."""
    return _accentless((a or "").lower()) == _accentless((b or "").lower())


SEGMENT_TYPE = {"Music": "music", "Arts & Theatre": "other"}


def split_name_title(title):
    """'Artist - ShowTitle' / 'Artist: ShowTitle' -> (name, title)."""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    m = re.match(r"^(.*?)\s*[-\u2013\u2014:]\s+(.+)$", t)
    if m:
        head, rest = m.group(1).strip(), m.group(2).strip()
        if head and len(head) <= 48:
            return head, re.sub(r"[!.\s]+$", "", rest) or None
    return t or None, None


def feat_support(title):
    """'Pattie Gonia: SAVE HER! Feat. Sequoia and VERA!' ->
    (['Sequoia', 'VERA!'], 'SAVE HER!').

    A 'Feat.'/'featuring' clause inside the title names support acts that are
    absent from the billed artists list (a solo-artist billing). Returns the
    acts plus the title with the clause (and any punctuation attached to it)
    removed — returns the title unchanged when there is no clause."""
    if not title:
        return [], None
    m = re.search(r"\s*(?:feat\.?|featuring)\s+(.+)$", title, re.I)
    if not m:
        return [], None
    acts = [p.strip() for p in re.split(r"\s+and\s+|\s*[,/]\s*", m.group(1))]
    acts = [a for a in acts if 2 <= len(a) <= 40]
    keep = title[:m.start()].rstrip()
    return acts, keep


def split_time(ii):
    """(doors, show_time) from 'Doors 7:00pm / Show 8:00pm …' text."""
    doors = show = None
    if ii:
        m = re.search(r"Doors\s+([\d:apm\s]+?)(?=\s*/|\s+Support|\s*$)", ii, re.I)
        if m:
            doors = "Doors " + re.sub(r"\s+", " ", m.group(1)).strip()
        m = re.search(r"Show\s+([\d:apm\s]+?)(?=\s+Support|\s*$)", ii, re.I)
        if m:
            show = re.sub(r"\s+", " ", m.group(1)).strip()
    return doors, show


def clean_desc(ii):
    if not ii:
        return None
    s = re.sub(r"OPEN DANCE FLOOR / STANDING ROOM ONLY", "", ii, flags=re.I)
    s = re.sub(r"STANDING ROOM ONLY", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" /.")
    return s or None


def parse_start(start):
    if not start:
        return None
    try:
        return datetime.datetime.strptime(start[:16], "%Y-%m-%d %H:%M").date().isoformat()
    except ValueError:
        return None


def main():
    rows = json.load(open(CAL))
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        arts = [a["name"] for a in r.get("artists") or []]
        name, show_title = split_name_title(r.get("name"))

        # Multi-night pass placeholder (00:00:01 start, e.g. the Mountain
        # Goats "SIX (6) Show Ticket"): the individual nights are each their
        # own event — don't render the pass as a show.
        if r.get("start") and "00:00:01" in r["start"]:
            continue

        # Headliner display name — reconcile the billed title with the venue's
        # own artists list:
        #  * split titles ("Artist - Tour"): when the title's lead equals the
        #    first billed artist (case/accent-insensitive) show the venue's
        #    canonical casing (accented José, "The Damned"); otherwise the
        #    lead is the billed name ("The Big Star Quintet" — the artists
        #    list only carries the catalog spelling "Big Star").
        #  * a tour-NAMED lead ("Sanctuary Park Tour: Celebrating 40 Years of
        #    The Jayhawks") is not an artist: the primary billed artist
        #    headlines and the WHOLE billed name becomes the show title.
        #  * undashed titles: arts[0] when it is the same name, else the
        #    billed title itself.
        lead, title_part = (None, None)
        if name and show_title:
            lead = name
            title_part = show_title
            if arts and eq(lead, arts[0]):
                lead = arts[0]
        elif name:
            lead = arts[0] if (arts and eq(name, arts[0])) else name
        else:
            lead = arts[0] if arts else None
        tour_remapped = False
        if lead and arts and not eq(lead, arts[0]) \
                and re.search(r"\b(tour|festival|anniversary|celebrating|night|weekend)\b", lead, re.I):
            lead = arts[0]
            title_part = name  # keep the whole billed name as the tour title
            tour_remapped = True
        head = [lead] if lead else []

        # Support = billed artists minus the headliner (its own catalog
        # spelling may differ: "The Damned" vs "THE DAMNED"), plus any
        # 'Feat. X and Y' named in the title part (solo billings where the
        # support is absent from the billed artists list).
        matched_head = None
        for h in head:
            rec = lookup.get(apple_music.cache_key(h)) or {}
            if rec.get("matched"):
                matched_head = rec["matched"]
                break
        feats, feat_title = feat_support(title_part)
        support = []
        for a in arts[1:] + feats:
            if any(eq(a, h) for h in head):
                continue
            if matched_head and eq(a, matched_head):
                continue
            if any(eq(a, s) for s in support):
                continue
            support.append(a)
        # 'Feat. X and Y' is redundant once the acts are in the support list;
        # a tour-remapped title has no feat clause, so only the split title
        # part can be clipped.
        if feat_title is not None and feats and not tour_remapped:
            rest = feat_title.strip(" :-.")
            show_title = None if (not rest or eq(rest, lead)) else rest

        # The billed event name can differ from the artists list in casing
        # only; trust the venue's own artist name for display.
        heads = [apple_music.artist_obj(h, lookup) for h in head]
        sups = [apple_music.artist_obj(s, lookup) for s in support]

        doors, show_time = split_time(r.get("important_info"))
        # 00:00:01 starts are multi-night pass placeholders (e.g. the
        # Mountain Goats "SIX (6) Show Ticket"): no doors/show time of their own.
        if r.get("start") and "00:00:0" in r["start"]:
            doors = None
            show_time = None

        rec = common_build.show(
            event_type=SEGMENT_TYPE.get(r.get("segment"), "music"),
            headline_artists=heads,
            support_artists=sups,
            multi_artist=len(head) > 1,
            show_title=show_title,
            date=parse_start(r.get("start")),
            doors=doors,
            show_time=show_time,
            ticket_link=r.get("url"),
            ticket_status={"onsale": "on sale", "soldout": "sold out"}.get(r.get("status_code")),
            event_page=r.get("url"),
            description=clean_desc(r.get("important_info")),
        )
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
        print(f"  {s['date'] or '?'} {h[:40]:40} {('+' + sup)[:38]:38} "
              f"{s.get('doors') or '':14} {s.get('ticket_status') or ''}")
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
