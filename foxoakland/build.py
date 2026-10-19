#!/usr/bin/env python3
"""Build the Fox Theater (Oakland) schedule into the shared shows.json.

Maps cache/shows.json (captured by fetch.py from thefoxoakland.com) into the
common show shape. The Fox bills live music AND comedy (Ali Siddiq, Fortune
Feimster, ALOK, …), so the adapter classifies each show's event_type:

    event_type = "comedy" when the venue signals it — from the tour/topline
        (a "…Comedy Tour" banner), the show title (": …Comedy…"), or the
        artist bio (the <div class="bio"> text calls out comedian/comedy
        special/stand-up). Otherwise "music". This is the venue's own
        copy, not a guess: a music act's bio (Brandi, Mastodon, Epik High)
        never uses those words.

Everything else is a near 1:1 map:
    show_title  = the tour (topline), stripped of the venue's banner lines
        ("An Evening With", "##", "###") and "Two Nights!"-style tags.
    headliner   = the show-title (always one billed act, per the Fox's own
        field — never split; the Apple Music engine resolves compounds).
    support     = the <br>-separated support block, split on COMMA/&/and.
        (Unlike Cafe du Nord, the Fox support block is plain prose, so a
        normal act split is correct — "Mindex, Cosmic Trigger ft. …").
    age_rating  = the variable line from the detail's more-information block.
    note        = a venue-move / rebooking notice (rare) — kept for review.
    description = the bio (real per-artist text; the Telegraph-Room / The-Den
        boilerplate is venue-constant and dropped).
    ticket_status = "sold out" / "on sale" (from the listing button).

The Fox has a single room, so `room` stays None.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "data", "shows.json")

VENUE = "Fox Theater"
VENUE_ID = "foxoakland"
VENUE_URL = "https://thefoxoakland.com"
SOURCE_URL = "https://thefoxoakland.com/listing/"

# Venue banner lines that are NOT part of the tour name.
BANNERS = re.compile(
    r"^(?:an evening with|two nights!|2nd show added by popular demand!|"
    r"first show sold out!|getting killed again|getting killed again tour|"
    r"###|##)\s*[:\-]?\s*", re.I)
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
        # pure banner -> drop
        if re.fullmatch(
                r"an evening with|two nights!|2nd show added by popular demand!|"
                r"first show sold out!|###|##|presenting.*", ln, re.I):
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
        if tail:
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
