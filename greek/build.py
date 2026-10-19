#!/usr/bin/env python3
"""Build the Greek Theatre (Berkeley) schedule into the shared shows.json.

Maps cache/shows.json (captured by fetch.py from thegreekberkeley.com — the
official UC Berkeley Greek Theatre site, APE's exclusive-promoter concert
listing) into the common show shape.

The source is APE's *music* concerts only (the full Greek season — theater /
film — lives on thegreek.com, which is Cloudflare-walled and unreachable), so
every show here is billed as a concert: event_type = "music". (The venue's own
copy is the source of truth if APE ever lists a comedy show; we still classify
from the bio/topline rather than hardcoding, for the same reason as the Fox.)

Everything else is a near 1:1 map (same TicketWeb platform as the Fox Oakland):
    show_title  = the tour (topline), stripped of banner lines.
    headliner   = the show-title (one billed act; a colon-tail is split off).
    support     = the <br>-separated support block, split on line breaks + commas.
    age_rating  = the variable line from the detail's more-information block.
    note        = a venue-move / rebooking notice (rare) — kept for review.
    description = the per-artist bio (boilerplate dropped).
    ticket_status = "sold out" / "on sale" (from the listing button).

Single room (the Greek amphitheater) → `room` stays None.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "data", "shows.json")

VENUE = "Greek Theatre"
VENUE_ID = "greek"
VENUE_URL = "https://thegreekberkeley.com"
SOURCE_URL = "https://thegreekberkeley.com/event-listing/"

# Venue banner lines that are NOT part of the tour name.
BANNERS = re.compile(
    r"^(?:an evening with|two nights!|three nights!|2nd show added by popular demand!|"
    r"first show sold out!|###|##)\s*[:\-]?\s*", re.I)
# Comedy signal in the venue's own copy (bio / topline / title). Kept tight:
# NO bare "laugh" — that hit a musician's bio ("laughter") and mis-flagged
# Thundercat. The Fox calls a comedy show a comedy in these terms.
COMEDY = re.compile(
    r"comedy|comedian|stand.?up|one.?man show|one.?woman show|roast|"
    r"comedy special|comedy tour|joke festival", re.I)


def iso_date(date_str):
    """'October 18, 2026 7:30 pm' -> '2026-10-18' (None if unparseable)."""
    if not date_str:
        return None
    m = re.match(r"([A-Za-z]+) (\d{1,2}), (\d{4})", date_str)
    if not m:
        return None
    months = {n: i + 1 for i, n in enumerate(
        ["January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"])}
    mon = months.get(m.group(1))
    if not mon:
        return None
    return f"{m.group(3)}-{mon:02d}-{int(m.group(2)):02d}"


def split_headliner(name):
    """'Ali Siddiq: The Custom Fit Tour' -> ('Ali Siddiq', 'The Custom Fit Tour').

    The Fox bills some shows with the tour TACKED ON to the headliner name
    (a colon + tour title). We split it so the real artist resolves in Apple
    Music and the tour becomes show_title. Only strips a short, tour-shaped
    tail (no bare names like 'Jessie Reyez: X' with a 1-word non-tour tail)."""
    if not name:
        return None, None
    m = re.search(r":\s+([^.!?]{3,48})\s*$", name)
    if m:
        tail = m.group(1).strip()
        head = name[:m.start()].strip()
        if head and len(head) >= 2 and len(head) < len(name):
            return head, tail
    return name, None


def clean_title(t):
    """Collapse the tour into a clean title: drop banner lines, dedupe the
    headliner if it is repeated after a ## marker, tidy whitespace."""
    if not t:
        return None
    # The topline can stack lines: "Two Nights!\nGetting Killed Again Tour".
    # We keep every line EXCEPT pure banners; join the rest with " — ".
    lines = [ ln.strip() for ln in re.split(r"[#\n]+|##", t) if ln.strip() ]
    kept = []
    for ln in lines:
        ln = re.sub(r"[##]+", "", ln).strip()
        if not ln:
            continue
        # pure banner / reschedule-notice line -> drop (keep the real tour)
        if re.fullmatch(
                r"an evening with|two nights!|three nights!|"
                r"2nd show added by popular demand!|first show sold out!|###|##|"
                r"presenting.*|show rescheduled.*|rescheduled from.*|"
                r"show moved.*|newly added.*|added by popular demand.*",
                ln, re.I):
            continue
        kept.append(ln)
    kept = [k for k in kept if k]
    if not kept:
        return None
    # de-dup consecutive repeats (a tour sometimes restates the headliner)
    out, prev = [], None
    for k in kept:
        if k == prev:
            continue
        out.append(k)
        prev = k
    return " — ".join(out).strip() or None


def _similar(a, b):
    """Loose near-identity: are two strings the same tour phrased slightly
    differently? (e.g. '…Fugees' The Score' vs '…The Score'.) Used to drop a
    colon-tail that just restates the topline tour."""
    if not a or not b:
        return False
    import difflib
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.75


def classify(headliner, tour, bio):
    """music | comedy from the venue's own copy."""
    blob = " ".join(x for x in (headliner, tour, bio) if x)
    if COMEDY.search(blob):
        return "comedy"
    return "music"


def split_support(support_raw, lookup):
    """Support arrives as a LIST (the venue <br>-separates each act). Each
    line is one act as billed; a line can still hold a compound like 'Cosmic
    Trigger ft. Visuals by …' — we keep each line as-is but split a line on
    ',' in case two acts share a line. Leading 'with'/'featuring' stripped."""
    if not support_raw:
        return []
    if isinstance(support_raw, str):
        support_raw = [support_raw]
    acts = []
    for line in support_raw:
        # each line may itself be multi-act (via <br> -> newline); split on both.
        for line in re.split(r"[\n,]", line):
            line = re.sub(r"^(?:with|and|featuring|plus)\s+", "", line, flags=re.I).strip()
            a = re.sub(r"\s+", " ", line).strip(" ,&.")
            if a and len(a) > 1:
                acts.append(a)
    # de-dup, keep order
    seen, out = set(), []
    for a in acts:
        if a.lower() in seen:
            continue
        seen.add(a.lower()); out.append(a)
    return [apple_music.artist_obj(a, lookup) for a in out]


def main():
    cache = json.load(open(os.path.join(CACHE, "shows.json")))
    lookup = apple_music.load_lookup_cache(os.path.join(CACHE, "lookup.json"))

    shows = []
    for r in cache:
        raw_head = r.get("headliner")
        if not raw_head:
            continue
        head_name, tail = split_headliner(raw_head)
        # A colon-tail ("…: The Custom Fit Tour") is a tour → merge into show_title.
        tour = clean_title(r.get("tour"))
        if tail and tour and _similar(tail, tour):
            pass  # topline already carries the tour; the tail is a restatement
        elif tail:
            tour = f"{tail} — {tour}" if tour else tail
        bio = r.get("bio")
        etype = classify(head_name, tour, bio)

        head = apple_music.artist_obj(head_name, lookup)
        support = split_support(r.get("support"), lookup)

        head_name = head_name or raw_head
        age = r.get("age")
        desc = bio
        note = r.get("notice")

        shows.append(build.show(
            event_type=etype,
            needs_review=False,
            headline_artists=[head],
            support_artists=support,
            multi_artist=len(support) > 0 or "&" in (head_name or ""),
            show_title=tour,
            date=iso_date(r.get("date")),
            doors=(r.get("doors") or None),
            show_time=(r.get("show_time") or None),
            ticket_status=r.get("ticket_status"),
            ticket_link=r.get("ticket_link"),
            event_page=r.get("event_page"),
            age_rating=(age or None),
            note=(note or None),
            description=(desc[:1000] or None) if desc else None,
        ))

    stats = {
        "event_types": {
            "music": sum(1 for s in shows if s["event_type"] == "music"),
            "comedy": sum(1 for s in shows if s["event_type"] == "comedy"),
        },
        "apple_music": apple_music.apple_music_stats(shows),
    }
    path = build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    am = stats["apple_music"]
    print(f"built {len(shows)} shows -> {path}")
    print(f"  event_types: {stats['event_types']}")
    print(f"  apple_music: {am}")


if __name__ == "__main__":
    main()
