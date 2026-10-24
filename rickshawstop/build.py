#!/usr/bin/env python3
"""Build the Rickshaw Stop schedule (cache/events.json) into the shared
shows.json.

Rickshaw Stop (155 Fell St, Mission/Civic Center) is an eclectic room — indie
rock, electronic, dance, and the occasional comedy set all share its calendar.
Its site is Cloudflare-walled for the HTML routes, so fetch.py reads the
calendar page through the WordPress REST API and merges the 12 month-tables
(the full season backbone) with the 10 nearest list-view cards (which carry
the clean headliner name, support, genre and ages).

event_type: derived from the venue's own GENRE field where present — a
comedy-ish genre (stand-up) -> "comedy", every other performance genre ->
"music". Shows whose genre is unknown (the older, table-only shows) default
to "music": the room is a live-music venue, and a handful of mislabeled
dance-party shows is acceptable (the reviewer's note is for them). No
per-artist genre list.

Apple Music links are matched as usual (the mandate) for both headliners and
support. Spotify: the venue site publishes no per-artist links and the
seetickets/eventim ticket pages are bot-walled, so the registry turns on the
Spotify API lookup (common/spotify_api) instead — applied below.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music, spotify

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")

VENUE = "Rickshaw Stop"
VENUE_ID = "rickshawstop"
VENUE_URL = "https://rickshawstop.com"
SOURCE_URL = "https://rickshawstop.com/calendar/"

# comedy-ish genre -> comedy; everything else (and the unknown genre default)
# -> music. The genre strings the venue actually uses: Indie, Alternative,
# DJ/Dance, World, Stand-Up, Latin, Emo, Metal, ...
COMEDY_GENRE = re.compile(r"stand.?up|comedy|comedian|roast|one.?man", re.I)

# A status word billed in the title ("… CANCELLED") is a marker, not an act.
STATUS_WORDS = {"CANCELLED", "CANCELED", "POSTPONED"}

# Descriptor words that are never an act name (support-line prose guard):
NON_ACT = re.compile(
    r"^(?:supporting\s+talent|with|featuring|plus|and|to|of|for|at|in|by|"
    r"presents|presented|support\s+tba)\s*$", re.I)


def _clean_name(n):
    if not n:
        return None
    n = re.sub(r"\s+", " ", n).strip(" -—&.:,")
    return n or None


def split_support(raw, lookup):
    """The list-card support line, e.g. "Supporting Talent: A, B". Split on
    COMMA ONLY — act names contain "&"/"and" inside them (the Cafe du Nord /
    chapel rule)."""
    if not raw:
        return []
    line = re.sub(r"^\s*supporting\s+talent\s*[:\-]?\s*", "", raw, flags=re.I)
    seen, acts = set(), []
    for part in re.split(r"[,;]", line):
        a = re.sub(r"\s+", " ", part).strip(" -—&.")
        a = re.sub(r"^(?:with|featuring|plus|and)\s+", "", a, flags=re.I).strip()
        a = _clean_name(a)
        if a and len(a) > 1 and not NON_ACT.match(a) and a.lower() not in seen:
            seen.add(a.lower())
            acts.append(a)
    return [apple_music.artist_obj(a, lookup) for a in acts]


def _strip_paren(n):
    """Drop parenthetical billing notes like "(co-headline)" anywhere in a
    name — they are not part of the act."""
    if not n:
        return None
    n = re.sub(r"\s*\([^)]*\)", "", n)
    n = re.sub(r"\s+", " ", n).strip(" -—&.:,")
    return n or None


# A tail after a dash/colon is a TOUR name only when it reads as one — a bare
# "HALLOWEEN DANCE PARTY" tail is part of the show name, not a tour, so party
# titles ('HAUS PARTY - HALLOWEEN DANCE PARTY') stay verbatim as the headliner.
TAIL_TOUR_RE = re.compile(
    r"\b(?:tour|world tour|album|special|show|nights?|sessions?|"
    r"live|acoustic|one.?man|retro|tribute|festival)\b", re.I)


def split_tail(name):
    """'Name - Tour' / 'Name: Tour' / 'Name — Tour' -> (Name, Tail). The tail
    must read as a tour (TAIL_TOUR_RE) to be split off; otherwise the whole
    string is the headliner. Only the first separator is considered (a lazy
    head), and a colon splits only when the tail looks tour-ish, so a dance
    night billed 'DANCE 4 U: SLAYYYTER' keeps its full name."""
    if not name:
        return None, None
    name = _strip_paren(name) or name
    m = re.match(r"^(.*?)\s+[-—:]\s+([^-—:]+)$", name)
    if m:
        head, tail = m.group(1).strip(" -—:").strip(), m.group(2).strip()
        if 2 <= len(head) and len(tail) <= 48 and TAIL_TOUR_RE.search(tail):
            return head, tail
    return name, None


def classify_event(genre, title):
    """event_type from the venue's own genre (comedy-ish -> comedy, else
    music); the title is a fallback for the rare genre-less comedy."""
    if genre and COMEDY_GENRE.search(genre):
        return "comedy"
    if title and COMEDY_GENRE.search(title):
        return "comedy"
    return "music"


def main():
    rows = json.load(open(os.path.join(CACHE, "events.json")))
    lookup = apple_music.load_lookup_cache(os.path.join(CACHE, "lookup.json"))

    shows = []
    for r in rows:
        title = r.get("title")
        if not title:
            continue

        # Headliner: prefer the venue's clean list-card name; else derive from
        # the billed title. Re-key a status word so the real act is matched.
        name = r.get("headliner") or title
        tail = None
        # a tour/event tail is judged on the TAIL alone, not the whole title
        name_part, tail = split_tail(name)
        name_part, tail, status_note = build.rekey_status_headliner(
            name_part or name, tail)
        head_name = _clean_name(name_part or name)
        if not head_name:
            continue
        # a trailing status word in the billed name ("… CANCELLED") is a
        # marker, not an act — strip it so the real name matches, and note it.
        for w in STATUS_WORDS:
            if re.search(r"\s+" + w + r"$", head_name, re.I):
                head_name = _clean_name(re.sub(
                    r"\s+" + w + r"$", "", head_name, flags=re.I))
                status_note = w.capitalize()
                break
        head = apple_music.artist_obj(head_name, lookup)
        support = split_support(r.get("support"), lookup)

        # co-headline bills ("A / B" or "A x B") -> two acts (parts are
        # individually paren-stripped so "(co-headline)" never leaks through).
        heads = [head]
        if head_name and ("/" in head_name or re.search(
                r"\s+[xX]\s+", head_name)):
            parts = [_strip_paren(p) for p in
                     re.split(r"\s*/\s*|\s+[xX]\s+", head_name)]
            parts = [p for p in parts if p and len(p) > 1]
            if parts:
                heads = [apple_music.artist_obj(p, lookup) for p in parts]

        note = status_note
        multi = len(heads) > 1 or bool(support) or "&" in (head_name or "")

        shows.append(build.show(
            event_type=classify_event(r.get("genre"), title),
            needs_review=False,
            headline_artists=heads,
            support_artists=support,
            multi_artist=multi,
            show_title=tail,
            presenters=r.get("presenters") or [],
            date=r.get("date"),
            doors=r.get("doors"),
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("event_page"),
            age_rating=r.get("age"),
            note=note,
        ))

    stats = {
        "event_types": {"music": len(shows)},
        "apple_music": apple_music.apple_music_stats(shows),
    }
    build.apply_spotify_lookup(shows, os.path.join(CACHE, "spotify_lookup.json"))
    stats["spotify"] = spotify.stats(shows)
    path = build.run_build(VENUE, VENUE_ID, VENUE_URL, SOURCE_URL, shows, stats)
    am = stats["apple_music"]
    print(f"built {len(shows)} shows -> {path}")
    print(f"  event_types: {stats['event_types']}")
    print(f"  apple_music: {am}")
    print(f"  spotify: {stats['spotify']}")


if __name__ == "__main__":
    main()
