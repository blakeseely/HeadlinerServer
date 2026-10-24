#!/usr/bin/env python3
"""Build the Pappy & Harriet's schedule (cache/events.json) into the shared
shows.json.

Pappy & Harriet's (53688 Pioneertown Rd, Pioneertown CA — a Pioneertown
desert saloon; grouped with the LA market in the app) bills country/rock/
roots acts, mostly single headliners with an occasional support act. The
site is bot-walled for the HTML routes, so fetch.py reads the /calendar page
through the WordPress REST API and merges the 12 month-tables (the full
season backbone) with the nearest ~38 list-view cards (which carry the clean
headliner name, support, genre, ages and price).

Headliner/support derivation from the billed title (the work is here):
  * 'Name ft: X', 'Name w/ X' / 'Name w: X' / 'Name with X' -> support.
  * '//' = co-headline bill (keep every part; '&'/'and' inside a name never
    split — 'Durand Jones & The Indications').
  * a '-'/':' tail that reads as a tour ('Record Release',
    'The Universal Bubba Tour') -> the show title.
  * bracketed notes ('(from Little Feat)', '[Night 1]') stay — they identify
    the billing; the name is looked up with them stripped where possible.
Support from the list card's "Supporting Talent: …" wins over a title clause
and splits on COMMA ONLY (names contain '&'/'and' inside them).

event_type: the venue's published GENRE (Rock, Country, Jazz, Hip Hop/Rap) is
always a music genre here — the room plays live music; a comedy-ish genre or
title is the only other branch.

Spotify: the venue site publishes no per-artist links and its Seetickets
event pages are bot-walled, so per-artist Spotify is an honest null — the
registry turns on the Spotify API lookup (common/spotify_api) instead.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from common import build, apple_music, spotify, bill

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache")

VENUE = "Pappy & Harriet's"
VENUE_ID = "pappy"
VENUE_URL = "https://pappyandharriets.com"
SOURCE_URL = "https://pappyandharriets.com/calendar/"

# A status word billed in the title is a marker, not an act.
STATUS_WORDS = {"CANCELLED", "CANCELED", "POSTPONED"}

# Descriptor/prose words that are never an act name (support-line guard).
NON_ACT = re.compile(
    r"^(?:supporting\s+talent|with|featuring|featuring\s+the|plus|and|to|of|"
    r"for|at|in|by|presents|presented|support\s+tba|special\s+guest)\s*$",
    re.I)

# A tail after '-' / ':' is a TOUR name only when it reads as one (short or
# tour-ish); 'NYE - Black Crystal Wolf Kids // Well Well Well' is NOT — the
# whole thing stays the headliner bill.
TAIL_TOUR_RE = re.compile(
    r"\b(?:tour|world tour|album|special|release|session|night|nights|"
    r"live|acoustic|one.?man|retro|tribute|farewell|anniversary)\b", re.I)

# 'ft:' / 'w/' / 'w:' / 'with' / 'featuring' clauses.
_SUPPORT_RE = re.compile(
    r"\s+(?:ft\.?\s*:|w/|w:|w\.|with|featuring|feat\.?)(?=[\s(]|$)", re.I)


def _clean_name(n):
    if not n:
        return None
    n = re.sub(r"\s+", " ", n).strip(" -—&.:,")
    return n or None


def _strip_paren(n):
    """Drop parenthetical notes like '(from Little Feat)'; keep the rest."""
    if not n:
        return None
    n = re.sub(r"\s*\([^)]*\)", "", n)
    n = re.sub(r"\s+", " ", n).strip(" -—&.:,")
    return n or None


def split_support_clause(line):
    """'Supporting Talent: A, B' / a 'w/ X, Y' clause -> [names].
    COMMA ONLY — act names contain '&'/'and' inside them."""
    if not line:
        return []
    seen, acts = set(), []
    for part in re.split(r"[,;]", line):
        a = re.sub(r"\s+", " ", part).strip(" -—&.")
        a = re.sub(r"^(?:with|featuring|plus|and|ft\.?\s*:|w/|w:)\s+", "",
                   a, flags=re.I).strip()
        a = _clean_name(a)
        if a and len(a) > 1 and not NON_ACT.match(a) and a.lower() not in seen:
            seen.add(a.lower())
            acts.append(a)
    return acts


def split_title_parts(title):
    """Co-headline parts: '//' and ' x ' split; ',' splits only between two
    capitalized-ish name parts. '&' / 'and' inside a name never split."""
    parts = re.split(r"\s+//\s+|\s+[xX]\s+(?=[A-Z])", title)
    out = []
    for p in parts:
        if ", " in p:
            # a comma bill: split, but re-join a piece that restarts with a
            # lowercase connector inside a name ('and the tax evaders')
            pieces = [s.strip(" -—") for s in p.split(", ")]
            merged = []
            for s in pieces:
                if merged and re.match(r"^(?:and|the)\b", s, re.I) \
                        and not re.match(r"^(?:the\b|and\b)\s+[A-Z]", s):
                    merged[-1] = f"{merged[-1]} {s}"
                else:
                    merged.append(s)
            out.extend(merged)
        else:
            out.append(p.strip(" -—"))
    return [s for s in out if s]


def derive_bill(r, lookup):
    """(head_artists, support_artists, show_title, multi, review, note).

    The card's STRUCTURED fields win (the venue's own split): the list card's
    'headliners' string is the clean headliner bill and 'supporting-talent'
    the support. The raw TITLE runs the full title grammar only as a fallback
    (table-only shows, or a rare empty headliners field)."""
    name = r.get("headliner") or r.get("title") or ""
    name = re.sub(r"\s+", " ", name).strip()
    # a structured card carries its OWN split: support comes from the card's
    # supporting-talent field, so the title grammar never re-derives support
    # from the title (which would double-list acts the card put in support).
    use_grammar = not r.get("headliner")
    review = False
    status_note = None
    card_sup = None
    support = None

    # a status word leading the name re-keys the real act from the tail
    for w in sorted(STATUS_WORDS, key=len, reverse=True):
        m = re.match(rf"^{w}\b[:\-–—]?\s*(.+)$", name, re.I)
        if m:
            name = m.group(1).strip()
            status_note = w.capitalize()
            break

    # support clause first (so a tour tail is judged on the tour alone)
    support = None
    if use_grammar:
        # a lowercase 'with' / 'w' before a lowercase/descriptor run is prose,
        # not a support clause — require a capitalized name or 'special guest'
        # after.
        sm = None
        for m in _SUPPORT_RE.finditer(name):
            if m.start() > 0:
                sm = m
                break
        if sm and re.search(r"[A-Z(]", name[sm.end():sm.end() + 3]):
            head_part = name[:sm.start()].strip()
            support = name[sm.end():].strip() or None
            name = head_part

    # tour tail: 'Name: Tour' / 'Name - Tour' only when the tail reads
    # tourish. Split at the LAST separator when several exist, so an internal
    # ':' inside a name never breaks the head; a tail longer than 48 chars
    # (or one carrying another separator) is NOT a tour — keep the whole
    # title. (Only for the raw title; a card's clean headliner bill has no
    # tour to peel off.)
    show_title = None
    if use_grammar:
        seps = [m.end() for m in re.finditer(r"[-—:]", name)]
        for pos in reversed(seps):
            head = name[:pos].strip(" -—:")
            tail = name[pos:].lstrip(" -—:").strip()
            if 2 <= len(head) and 0 < len(tail) <= 48 and not re.search(
                    r"[-—:]", tail) and TAIL_TOUR_RE.search(tail):
                name, show_title = head, tail
                break

    # co-heads from the remaining name
    heads = split_title_parts(name)
    heads = [_strip_paren(h) or h for h in heads if h]
    heads = [h for h in heads if len(h) > 1]
    if not heads:
        heads = [name]
        review = True
    if len(heads) >= 4:
        review = True
    # the card's 'headliners' field can repeat an act (its own duplication)
    # — dedupe case-insensitively, keeping the first spelling.
    seen = set()
    deduped = []
    for h in heads:
        if h.lower() not in seen:
            seen.add(h.lower())
            deduped.append(h)
    heads = deduped
    # a bracketed night/pack tag ('[Night 1]') is a billing note: the head is
    # looked up clean, the bracket becomes the show title.
    if len(heads) == 1 and not show_title:
        m = re.match(r"^(.*?)\s*(\[[^\]]*\])$", heads[0])
        if m and len(m.group(1)) > 1:
            show_title = m.group(2)
            heads[0] = m.group(1).strip()

    # the card's "Supporting Talent:" line (structured) wins over a title
    # clause; a title clause is only a fallback for the field being empty.
    if r.get("support"):
        card_sup = re.sub(r"^\s*supporting\s+talent\s*[:\-]?\s*", "",
                          r["support"], flags=re.I)
    else:
        card_sup = support
    support_names = split_support_clause(card_sup)

    # dedupe support against the headliner(s) — case-insensitive (an act the
    # card listed in BOTH headliners and support counts as the headliner)
    headset = {h.lower() for h in heads}
    support_names = [n for n in support_names if n.lower() not in headset]

    head_artists = [apple_music.artist_obj(h, lookup) for h in heads]
    support_artists = [apple_music.artist_obj(s, lookup)
                       for s in support_names]
    multi = len(heads) > 1 or bool(support_artists) or "&" in (heads[0] or "")
    return head_artists, support_artists, show_title, multi, review, status_note


def classify_event(genre, title):
    """The published genre is a music genre here; a comedy-ish genre or title
    is the only other branch."""
    if genre and re.search(r"stand.?up|comedy|comedian|roast", genre, re.I):
        return "comedy"
    if title and re.search(r"stand.?up|comedy|comedian|roast", title, re.I):
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
        (heads, support, st, multi, review, status_note) = derive_bill(r, lookup)
        if not heads or not heads[0].get("name"):
            continue
        shows.append(build.show(
            event_type=classify_event(r.get("genre"), title),
            needs_review=review,
            headline_artists=heads,
            support_artists=support,
            multi_artist=multi,
            show_title=st,
            presenters=r.get("presenters") or [],
            date=r.get("date"),
            doors=r.get("doors"),
            show_time=r.get("show_time"),
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("event_page"),
            age_rating=r.get("age"),
            note=status_note,
        ))

    stats = {
        "event_types": build.event_type_stats(shows),
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
    flagged = [s for s in shows if s.get("needs_review")]
    if flagged:
        print(f"  needs_review: {len(flagged)}")
        for s in flagged[:8]:
            print("    ", s.get("date"), s.get("headline_artists"))


if __name__ == "__main__":
    main()
