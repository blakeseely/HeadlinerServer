"""Shared build for the Belly Up Presents San Diego venues.

Run from a bellyup-group venue directory (bellyup/ thesound/ thecasbah/
theobservatory/ musicbox/ humphreys/). Maps cache/events.json (written by
common/fetch_bellyup.py — the promoter's shared calendar, one venue's rows)
into the shared shows.json shape.

Field mapping:
    headline_artists  = the bill's head/co-head names (comma/+/'x' split)
    support_artists   = the trailing 'w/ with featuring' clause (comma split)
    multi_artist      = True when 2+ head names are billed
    show_title        = the tour/series tail (judged by common/bill)
    presenters        = the 'X Presents' prefix
    date / show_time  = the calendar's MySQL datetime + displayTime
    doors             = the calendar's doors string (when present)
    ticket_status     = the popup ticket button's sale state
    ticket_link       = the popup's ticket URL (ticketweb)
    event_page        = the venue's own detail page (from the popup)
    description       = None — the popup text is ticket-boilerplate, not a
                        bio (the real bios live on the client-rendered
                        detail page); the viewer renders no description row
    age_rating        = the 'Seated Show' / age prefix text, when present

Apple Music: every billed name goes through the venue's own lookup cache
(artist_obj). Spotify: the promoter publishes no per-artist links, so the
registry flag has_spotify_lookup=True + apply_spotify_lookup in each build.
"""
import os
import re
import sys
from collections import Counter

HERE = os.path.abspath(os.getcwd())
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import json  # noqa: E402
from common import build, apple_music, spotify, bill, bellyup, venues as registry  # noqa: E402

CACHE = os.path.join(HERE, "cache")
EVENTS = os.path.join(CACHE, "events.json")
OUT = os.path.join(HERE, "data", "shows.json")
SPOTIFY_CACHE = os.path.join(CACHE, "spotify_lookup.json")


def _venue_entry():
    for v in registry.VENUES.values():
        if os.path.abspath(v["dir"]) == HERE:
            return v
    raise SystemExit("no registry entry for this directory")


def _pt(start):
    """'2026-10-01 20:00:00' -> (iso_date, '8:00 pm')."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})", start or "")
    if not m:
        return None, None
    iso = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    h, mi = int(m.group(4)), int(m.group(5))
    ampm = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return iso, f"{h12}:{mi:02d} {ampm}"


def _show_time(display_time):
    """'Show: 7:30PM' -> '7:30 pm' (None when the cell is empty)."""
    if not display_time:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", display_time, re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    ampm = (m.group(3) or ("am" if h < 12 else "pm")).lower()
    h12 = h % 12 or 12
    return f"{h12}:{mi:02d} {ampm}"


COMEDY_RE = re.compile(
    r"\bcomedy|comedian|stand.?up|roast|joke festival\b", re.I)


def _event_type(title, description):
    text = f"{title or ''} {description or ''}"
    return "comedy" if COMEDY_RE.search(text) else "music"


def _age_from_prefix(prefix_text):
    """The popup's prefix cell ('Seated Show', '18+', …) — keep only age-ish
    values; a seating note is not an age rating."""
    if not prefix_text:
        return None
    if re.match(r"^\d{1,3}\+", prefix_text):
        return prefix_text
    return None


_BOILER_SENT_RE = re.compile(
    r"delivery delay|tickets? will be delivered|ticket (?:price|package|sales?|available)|"
    r"advance\b|day of show|no refund|refunds? or exchanges|subject to change|parking|"
    r"seated show|reserved (?:seat|loft)|loft seating|gold circle|general admission|"
    r"standing room|box office|convenience service charges|e-?mail list|presale|presales|"
    r"vip (?:and|&|package)|belly up presents at|this show is not at|service charges?|"
    r"purchase(d)? online|on sale|sold out|not on the e-mail|sign up|"
    r"shelter island|kettner|cedros|coast highway|university ave|fairgrounds|del mar, san diego|"
    r"magnified vip|soundcheck|all times|once purchased|available online only|"
    r"loft, ga|seating chart|virtual venue tour|our vision|miracle babies|envisions|"
    r"charity|donation|fundraiser\b|supporting [A-Za-z]+ (?:cause|hospital|foundation)|"
    r"m&?g\b|wristband|quantity is limited|pink awareness|ladiez|photo and signing|laminate|"
    r"lapel pin|tote bag|vip upgrade|persons under the age|years shall be permitted|"
    r"designated entertainment|exclusive (?:location|lapel|access)|early entry|hang with the band", re.I)


def _clean_desc(d):
    """Keep only artist-meaningful sentences; the popup body is ticket
    boilerplate (delivery delays, prices, seating, addresses, charity copy).
    A sentence is boilerplate when it hits any ticket-speak keyword. If less
    than ~25 characters of real content survives, None (no description row).
    The honest end state for most rows is None — the real bios live on the
    client-rendered detail page, which a plain GET cannot read."""
    if not d:
        return None
    d = re.sub(r"\s+", " ", d).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", d) if s.strip()]
    # sentence 1 is always the lead line: '<Name>, <date> at <Venue> in <City>, CA'
    if sentences:
        if re.search(r"\b(?:at|in)\s+[A-Z][A-Za-z .']+?(?:,?\s*CA\b|$)", sentences[0]) \
           or re.search(r"(?:January|February|March|April|May|June|July|August|"
                        r"September|October|November|December|\d{4})", sentences[0]):
            sentences = sentences[1:]
    kept = [s for s in sentences
            if not _BOILER_SENT_RE.search(s) and len(s) >= 20]
    out = " ".join(kept)
    if len(out) < 25:
        return None
    return out


def build_show(e, lookup):
    raw_title = e.get("canonical_name") or e.get("title") or ""
    parsed = bill.parse_bill(raw_title)
    heads = parsed["heads"] or ([raw_title] if raw_title else [])
    supports = parsed["support"]
    multi = len(heads) >= 2

    heads_r = [apple_music.artist_obj(n, lookup) for n in heads]
    sups_r = [apple_music.artist_obj(n, lookup) for n in supports]

    date, _ = _pt(e.get("start") or "")
    show = build.show(
        event_type=_event_type(raw_title, e.get("description")),
        needs_review=multi and len(heads) >= 3,
        headline_artists=heads_r,
        support_artists=sups_r,
        multi_artist=multi,
        show_title=parsed["tour"],
        presenters=parsed["presenters"],
        date=date,
        show_time=_show_time(e.get("display_time")),
        doors=e.get("doors") or None,
        ticket_link=e.get("ticket_link"),
        ticket_status=bellyup_sale(e.get("ticket_class")),
        event_page=e.get("event_page"),
        age_rating=_age_from_prefix(e.get("prefix_text")),
        description=_clean_desc(e.get("description")),
    )
    return show


def bellyup_sale(cls):
    return bellyup.sale_state(cls)


def run_build():
    v = _venue_entry()
    rows = json.load(open(EVENTS))
    lookup = apple_music.load_lookup_cache(os.path.join(CACHE, "lookup.json"))
    shows = [build_show(e, lookup) for e in rows]

    import common.build as cb
    cb.apply_spotify_lookup(shows, SPOTIFY_CACHE)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    path = build.run_build(v["name"], v["key"], "https://bellyup.com",
                           "https://bellyup.com/calendar", shows, stats)
    print(f"{v['name']}: {len(shows)} shows -> {os.path.relpath(path, HERE)}")
    return path


if __name__ == "__main__":
    run_build()
