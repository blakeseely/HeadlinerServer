#!/usr/bin/env python3
"""Build data/shows.json for The Castro Theatre (venue adapter, thecastro.com).

Venue-specific part of the shared pipeline. Inputs (cache/):
  calendar.json  fetch_calendar.py output — one record per calendar card
                 (title, start, doors/show times, topline/bottomline,
                 ticket link + status).
  details.json   per detail page: desc (venue boilerplate + ratings) and
                 bio (the artist/film description).

Nothing on the site labels a card with a category, so classify() derives
one from the text. The one clean invariant discovered in the data:

  * Movie screenings carry a VENUE stamp in the desc field ("Film format
    subject to change." / "This event is Rated R.**" + the R-rated ID
    disclaimer) and/or a festival credit in the topline (SFFILM, Frameline,
    Janus/Criterion, Arab Film Festival).
  * Music and comedy events' desc is the all-ages stub; their real body text
    is the bio.

So the cascade is (first hit wins):
  1. DJ-prefixed title                    -> music
  2. venue film stamp in desc/topline     -> film
  3. music evidence in bio/topline        -> music   (bios win over the
                                                      "directed by"/"screening"
                                                      words that movie-adjacent
                                                      bios sometimes use)
  4. comedy evidence in title/bio         -> comedy
  5. soft film words in desc/topline/bio  -> film
  6. spoken-word / awards in title/bio    -> other
  7. default                              -> music; needs_review when the
                                             body is only the generic stub.

No Apple Music matching for film: a film's billed name is the movie (or its
director), which Apple Music's artist catalog does not cover. Music and
comedy performers ARE matched via the shared engine (common/lookup.py
populates cache/lookup.json; common.apple_music.artist_obj renders it).
The show shape, stats blocks, sort, and JSON writer come from common.build.
"""
import os, re, sys, json, datetime
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build

ROOT = HERE
CAL = os.path.join(ROOT, "cache", "calendar.json")
DET = os.path.join(ROOT, "cache", "details.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
DST = os.path.join(ROOT, "data", "shows.json")

VENUE = "The Castro Theatre"
VENUE_ID = "castro"
SRC_URL = "https://thecastro.com/calendar/"

# Venue stamps that appear ONLY on movie screenings (desc or topline).
FILM_STAMP_RE = re.compile(
    r"film format|rated [rpg]\b|in 35mm|in 70mm|4k restoration|"
    r"sffilm|frameline|criterion|janus films|film festival", re.I)
# Words that mark a film but also show up in music/comedy bios, so they only
# vote AFTER the music and comedy evidence has been checked.
FILM_SOFT_RE = re.compile(
    r"screening|late screening|early screening|directed by|film\b", re.I)
MUSIC_RE = re.compile(
    r"\b(dj\b|band|artist|album|record|records|songs?|songwriter|producer|"
    r"musician|live show|acoustic|dj set)\b", re.I)
COMEDY_RE = re.compile(r"comedian|stand-?up|comedy", re.I)
# Non-music, non-film, non-comedy bookings (spoken word, awards).
OTHER_RE = re.compile(r"story[ ]?slam|grand[ ]?slam|legends[ ]?awards", re.I)


def classify(title, desc, bio, topline, bottomline):
    """(category, needs_review) — see module docstring for the cascade.
    Title signals are checked BEFORE bio signals: the billed name is the
    strongest evidence ("Fred Armisen: Comedy for Musicians…" is comedy, even
    though his bio says "musician")."""
    t = re.sub(r"\s+", " ", (title or "")).strip()
    b = re.sub(r"\s+", " ", (bio or "")).strip()
    d = re.sub(r"\s+", " ", (desc or "")).strip()
    tl = re.sub(r"\s+", " ", (topline or "")).strip()

    if re.match(r"^dj\b", t, re.I):
        return "music", False
    if FILM_STAMP_RE.search(d) or FILM_STAMP_RE.search(tl):
        return "film", False
    if COMEDY_RE.search(t):
        return "comedy", False
    if MUSIC_RE.search(t) or MUSIC_RE.search(b) or MUSIC_RE.search(tl):
        return "music", False
    if COMEDY_RE.search(b):
        return "comedy", False
    if FILM_SOFT_RE.search(d) or FILM_SOFT_RE.search(tl) or FILM_SOFT_RE.search(b):
        return "film", False
    if OTHER_RE.search(t) or OTHER_RE.search(b):
        return "other", False
    needs_review = len(b) <= 80
    return "music", needs_review


# Titles where the naive "Artist: ShowTitle" split is wrong — the colon is
# part of the work's own name. Pinned like the Independent's OVERRIDES.
NAME_OVERRIDES = {
    "2001: A Space Odyssey": ("2001: A Space Odyssey", None),
    "Sleepaway Camp: The Midnight Mass Experience":
        ("Sleepaway Camp", "The Midnight Mass Experience"),
}


def split_name_title(title):
    """'Artist: ShowTitle' -> (name, title); else (title, None).

    Rules of thumb:
      * no colon                      -> the whole string is the name
      * ':' inside the LEAD part
        ('2001: A Space Odyssey')     -> the whole string is the name
      * ':' with a 'presents'-style
        lead ('DJ Mandy Presents:')   -> the whole string is the name
      * a normal 'Artist: ...' split  -> name, show_title
    """
    t = re.sub(r"\s+", " ", (title or "")).strip()
    if t in NAME_OVERRIDES:
        return NAME_OVERRIDES[t]
    if ":" not in t:
        return t, None
    lead, rest = t.split(":", 1)
    lead, rest = lead.strip(), rest.strip()
    if not lead or not rest or len(lead) > 48:
        return t, None
    if re.search(r"presents?\b", lead, re.I):
        return t, None
    return lead, rest.rstrip("!. ") or None


SUPPORT_PREFIX_RE = re.compile(
    r"^(in|a|an|the|hosted|featuring|ft\.?\b|by|directed)\b", re.I)


def split_support(bottomline):
    """Support acts from the calendar bottom line.
       'with special guest X' / 'featuring X' / 'X and Y' (duo stays whole)
       / '+X'. Descriptive lines ('in 35mm', 'Hosted by …', 'Holiday
       Spectacular: …') are not support acts."""
    if not bottomline:
        return []
    b = re.sub(r"\s+", " ", bottomline).strip()
    if ":" in b:
        return []  # show title / format line, not a bill
    m = re.search(r"(?:with special guest|featuring|ft\.?|with)\s+(.*)$", b, re.I)
    if m:
        b = m.group(1).strip()
    if not b or SUPPORT_PREFIX_RE.match(b):
        return []
    # Drop leading credit honorifics ("Director Malcolm Ingram") — those are
    # production credits, not billed performers.
    HONORIFIC = re.compile(r"^(?:director|hosted by|presented by)\s+", re.I)
    acts = []
    for part in re.split(r"\s*\+\s*", b):
        part = part.strip(" -\u2013\u2014,")
        part = HONORIFIC.sub("", part).strip()
        if not part:
            continue
        if re.search(r"\s+and\s+", part):
            acts.append(part)  # group billing stays whole
        else:
            acts.append(part)
    return [a for a in acts if 3 <= len(a) <= 60 and not SUPPORT_PREFIX_RE.match(a)]


def age_rating(desc, bio):
    text = " ".join(x for x in (desc, bio) if x)
    if re.search(r"18 and over", text, re.I):
        return "18+"
    if re.search(r"16 and over", text, re.I):
        return "16+"
    if re.search(r"\brated r\b", text, re.I):
        return "R"
    if re.search(r"all ages", text, re.I):
        return "all ages"
    return None


def parse_date(start):
    if not start:
        return None, None
    try:
        dt = datetime.datetime.strptime(start[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None, None
    return dt.date().isoformat(), None


def clean_note(s):
    if not s:
        return None
    s = re.sub(r"this event is\s*\*?\s*(18 and over|recommended \d+ and over)\.?", "", s, flags=re.I)
    s = re.sub(r"all ages\*?\s*(\..*)?", "", s, flags=re.I)
    s = re.sub(r"all doors &? show times are? subject to change\.", "", s, flags=re.I)
    s = re.sub(r"all doors &? show times subject to change\.", "", s, flags=re.I)
    s = re.sub(r"doors &? show times subject to change\.", "", s, flags=re.I)
    s = re.sub(r"subject to change\.", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" .\n*")
    return s or None


def main():
    rows = json.load(open(CAL))
    details = json.load(open(DET))
    det_by_url = {v["url"]: v for v in details.values()}
    lookup = apple_music.load_lookup_cache(LOOKUP_CACHE)

    shows = []
    for r in rows:
        d = det_by_url.get(r["url"], {})
        desc, bio = d.get("desc"), d.get("bio")
        cat, review = classify(r.get("title"), desc, bio,
                               r.get("topline"), r.get("bottomline"))

        name, show_title = split_name_title(r.get("title") or "")
        head = [name] if name else []
        # Support is a music concept; a film's bottom line is format/credits.
        support = split_support(r.get("bottomline")) if cat == "music" else []
        support = [s for s in support if s.lower() != name.lower()]

        iso, _ = parse_date(r.get("start"))

        rec = common_build.show(
            event_type=cat,
            needs_review=bool(review),
            # Film: the billed name is a movie/director — plain, never linked.
            # Music + comedy: Apple Music-matched artist records (shared engine).
            headline_artists=(
                [apple_music.plain_artist(h) for h in head]
                if cat == "film" else
                [apple_music.artist_obj(h, lookup) for h in head]),
            support_artists=(
                [apple_music.plain_artist(s) for s in support]
                if cat == "film" else
                [apple_music.artist_obj(s, lookup) for s in support]),
            show_title=show_title,
            date=iso,
            doors=r.get("doors"),
            show_time=(r.get("show_time") or "").replace("Show:", "").strip() or None,
            ticket_link=r.get("ticket_link"),
            ticket_status=r.get("ticket_status"),
            event_page=r.get("url"),
        )
        ar = age_rating(desc, bio)
        if ar:
            rec["age_rating"] = ar
        # note = the calendar's banner lines (tour name / festival credit)
        note = None
        if r.get("topline"):
            note = re.sub(r"\s+", " ", r["topline"]).strip()
        elif r.get("bottomline") and not support:
            note = re.sub(r"\s+", " ", r["bottomline"]).strip()
        if note:
            rec["note"] = note
        # keep the source body text for the reviewer (the bio is the real
        # description; the desc field is mostly the rating/ages stub).
        body = clean_note(bio) or clean_note(desc)
        if body:
            rec["description"] = body[:1200]
        shows.append(rec)

    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
    }
    common_build.run_build(VENUE, VENUE_ID, SRC_URL, SRC_URL, shows, stats)

    by_type = stats["event_types"]
    print(f"built {len(shows)} shows -> {DST}")
    print("types:", by_type, "| needs_review:", sum(1 for s in shows if s["needs_review"]))
    print("no date:", sum(1 for s in shows if not s.get("date")),
          "| no headliner:", sum(1 for s in shows if not s["headline_artists"]))
    print("\n--- full list ---")
    for s in shows:
        h = " / ".join(a["name"] for a in s["headline_artists"])
        sup = " + ".join(a["name"] for a in s["support_artists"])
        flag = " ⚠" if s["needs_review"] else ""
        print(f"  {s['event_type']:6} {s.get('date','?')} {h[:52]:52} "
              f"{('+' + sup)[:40] if sup else '':40} "
              f"{('NOTE: ' + s['note'][:44]) if s.get('note') else ''}{flag}")


if __name__ == "__main__":
    main()
