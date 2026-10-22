#!/usr/bin/env python3
"""Build data/shows.json for The Independent SF (venue adapter).

Venue-specific part of the shared pipeline: reads the raw per-event capture
(cache/vfinal.json: <title> tag + event-column lines + doors/show/buy/ticket
link) and maps each event into the shared show shape, then hands the batch to
common.build.run_build().

Heuristics (see parse_title):
  * The venue's <title> tag is the canonical, properly-cased source.
  * "Artist - ShowTitle"  -> split on the first dash.
  * "Artist with/+ Act"   -> first is the headliner, the rest are support.
  * "Artist b2b Act"      -> co-headliners.
  * "Name (Live + DJ)"    -> parenthetical is a set format, not the name.
  * Trailing "Live"/"DJ"  -> set-format tokens, stripped from the name.
  * "& the ... Band" / "and his Band" -> kept whole (it's the artist's own band).
  * Lines above the bill on the page -> presenter ("X PRESENTS") or tour name.

Genuinely ambiguous titles (artist + undelimited tour name, or a multi-artist
variety show) are pinned in OVERRIDES below — this is intentional, since a
pure heuristic cannot reliably recover "Swervedriver" from "Swervedriver
Raise at 35".

Shared parts (one copy, in common/):
  * apple_music.artist_obj()  — the Apple Music confidence-tiered records
  * apple_music_stats()       — the ♪ stats block (lives in stats.apple_music)
  * build.show()/run_build()  — record shape, sort, JSON writer

Apple Music cache: cache/lookup.json, produced by running
  python3 ../../common/lookup.py [--full]        (from this directory)
from a previous run it may still be named itunes.json — build() falls back
to that name if lookup.json is absent.
"""
import os, re, sys, json, datetime
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root -> `import common`
from common import apple_music
from common import build as common_build
from common import spotify

ROOT = HERE
SRC = os.path.join(ROOT, "cache", "vfinal.json")
DST = os.path.join(ROOT, "data", "shows.json")
LOOKUP_CACHE = os.path.join(ROOT, "cache", "lookup.json")
LEGACY_CACHE = os.path.join(ROOT, "cache", "itunes.json")  # pre-refactor name

VENUE = "The Independent"
VENUE_ID = "independent"
SRC_URL = "https://www.theindependentsf.com/"
MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

ANNOUNCE = re.compile(
    r"(ADDED BY POPULAR DEMAND|RESCHEDULED FROM|SECOND NIGHT)", re.I)
SET_TOKEN = re.compile(r"^(live|dj|solo|acoustic)$", re.I)


def load_lookup():
    """Load the Apple Music lookup cache (common format) keyed for artist_obj."""
    path = LOOKUP_CACHE if os.path.exists(LOOKUP_CACHE) else LEGACY_CACHE
    if not os.path.exists(path):
        return {}
    try:
        raw = json.load(open(path))
    except Exception:
        return {}
    return {apple_music.cache_key(k): v for k, v in raw.items()}


def key(s):
    """Normalize a title for OVERRIDES lookup."""
    return re.sub(r"[^a-z0-9@ ]", "", s.lower()).strip()


OVERRIDES = {
    key("The Emo Night Tour"): dict(
        headline=["(Multiple Artists)"], multi_artist=True,
        show_title="The Emo Night Tour",
        note="Various-artist night (a theme show); the lineup is not named on the venue page."),
    key("@NICKCHEO the *TOUR* the *MOVIE*"): dict(
        headline=["@NICKCHEO"], show_title="The *TOUR* The *MOVIE*"),
    key("Swervedriver raise at 35"): dict(
        headline=["Swervedriver"], show_title="Raise at 35"),
}


def clean_tag(tag):
    return (tag or "").replace("\U0001f434", "").replace(" | The Independent SF", "").strip()


def split_bill(s):
    """Split on with/+/b2b at paren-depth 0 (never on 'and')."""
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    parts, buf, depth, i, n = [], "", 0, 0, len(s)
    while i < n:
        c = s[i]
        if c == "(":
            depth += 1; buf += c
        elif c == ")":
            depth -= 1; buf += c
        elif depth == 0 and c == "+":
            parts.append(buf); buf = ""; i += 1; continue
        elif depth == 0 and s[i:i+3].lower() == "b2b" and (i == 0 or not s[i-1].isalpha()) and (i+3 >= n or not s[i+3].isalpha()):
            parts.append(buf); buf = ""; i += 3; continue
        elif depth == 0 and s[i:i+4].lower() == "with" and (i == 0 or not s[i-1].isalpha()) and (i+4 >= n or not s[i+4].isalpha()):
            parts.append(buf); buf = ""; i += 4; continue
        else:
            buf += c
        i += 1
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def valid_name(p):
    p = p.strip()
    if not p or len(p) < 2:
        return False
    if p.lower() in {"live", "dj", "tour", "band", "set", "gig", "show"}:
        return False
    return True


def split_support_part(s):
    """Split a (non-headliner) bill part on 'and'/'&' into individual acts,
    but keep 'and his/the <Band>' glued to the name (artist's own band)."""
    s = s.strip()
    if re.search(r"(and|&)\s+(his|their|the)", s, re.I):
        return [s]  # "Jack Kays and his Band", "Sister Nancy & the Steady Rock Band"
    parts = re.split(r"\s+and\s+|\s*&\s*", s)
    return [p.strip() for p in parts if p.strip()]


def strip_set_format(name):
    """'Oden & Fatzo Live' -> ('Oden & Fatzo', 'Live'); 'Romare (Live + DJ)' -> ('Romare','Live + DJ')."""
    m = re.search(r"\s*\(([^()]*)\)", name)
    if m:
        inner = m.group(1)
        toks = [t.strip() for t in re.split(r"[+|,]", inner) if t.strip()]
        fmt = None
        if toks and all(SET_TOKEN.match(t) for t in toks):
            fmt = " + ".join(toks)
            name = re.sub(r"\s*\([^()]*\)", "", name).strip(" -\u2013\u2014")
            return name, fmt
    # trailing bare token
    words = name.split()
    if len(words) > 1 and SET_TOKEN.match(words[-1]):
        fmt = " + ".join(w for w in words[1:] if SET_TOKEN.match(w))
        name = " ".join(words[:-1]).strip(" -\u2013\u2014")
        return name, fmt
    return name.strip(), None


def _name_key(n):
    """Loose name identity (alnum + space, lower) for equality tests."""
    return re.sub(r"[^a-z0-9@ ]", "", (n or "").lower()).strip()


STATUS_WORDS = {"POSTPONED", "CANCELED", "CANCELLED"}


def rekey_status_headliner(headline, show_title):
    """A status word in the headliner slot is a marker, never an artist.

    "POSTPONED - Sawyer Hill" / "POSTPONED: Dogma" => the real act is the
    show title. Returns (headline, show_title, note_fragment); the re-key
    happens here, inside parse_title, BEFORE the Apple Music / Spotify
    lookups so the real act is what gets looked up (a real Apple Music
    artist named "Postponed" exists and used to be happily linked).
    """
    note = None
    if (headline or []) and show_title:
        h0 = re.sub(r"\s+", " ", headline[0]).strip().upper()
        s0 = re.sub(r"\s+", " ", show_title).strip()
        if h0 in STATUS_WORDS and _name_key(s0) != _name_key(h0):
            note = h0.capitalize()
            return [s0], None, note
    return headline, show_title, None


def parse_title(tag, list_name):
    out = {"multi_artist": False, "show_title": None, "set_format": None,
           "note": None, "headline": [], "support": [], "presenters": []}
    t = clean_tag(tag) or (list_name or "").strip()
    if not t:
        out["headline"] = [list_name or ""]
        return out

    ov = OVERRIDES.get(key(t))
    if ov:
        out["headline"] = ov["headline"]
        out["multi_artist"] = ov.get("multi_artist", False)
        out["show_title"] = ov.get("show_title")
        out["note"] = ov.get("note")
        return out

    name, fmt = strip_set_format(t)
    out["set_format"] = fmt

    # 1) dash => artist | show title
    m = re.match(r"^(.*?)\s*[\u2013\u2014-]\s+(.+)$", name)
    if m:
        artist, rest = m.group(1).strip(), m.group(2).strip()
        if valid_name(artist):
            out["headline"] = [artist]
            if re.search(r"MOVED TO|POSTPONED|CANCELED|CANCELLED", rest, re.I):
                out["note"] = rest
            else:
                out["show_title"] = rest.rstrip("!").strip() or None
            return _fin(out)

    # 1b) colon => "ARTIST: SHOW TITLE"  (independent bills tour shows this
    #     way, e.g. "POSTPONED: Dogma"). A "Presents" lead becomes the
    #     presenter, not the artist.
    m = re.match(r"^(.*?)\s*:\s*(.+)$", name)
    if m:
        artist, rest = m.group(1).strip(), m.group(2).strip()
        if valid_name(artist):
            pres = None
            if re.search(r"\bPRESENTS?\b", artist, re.I):
                pres = artist.rstrip(":").strip()
                artist = re.sub(r"\s*PRESENTS?\s*:\s*", " ", artist, flags=re.I).strip()
                if not valid_name(artist):
                    pres = None
                    artist = m.group(1).strip()
            out["headline"] = [artist]
            out["presenters"] = [pres] if pres else []
            out["show_title"] = rest.rstrip("!").strip() or None
            return _fin(out)

    # 2) multi-act bill (with/+)
    bill = split_bill(name)
    if len(bill) > 1:
        out["headline"] = [bill[0]]
        rest = bill[1:]
        # b2b already handled by split_bill producing both; treat as co-headliners
        if "b2b" in t.lower() and len(bill) == 2:
            out["headline"] = bill
            rest = []
        for part in rest:
            out["support"].extend(p for p in split_support_part(part) if valid_name(p))
        return _fin(out)

    if bill and bill[0]:
        out["headline"] = [bill[0]]
    else:
        out["headline"] = [name]
    return _fin(out)


def _fin(out):
    """Apply the status-word re-key on every return path: a POSTPONED/
    CANCELED headliner is a marker — the real act is the show title — and
    must be re-keyed HERE (before the Apple Music / Spotify lookups, which
    key off `headline`)."""
    hl, st, note = rekey_status_headliner(out.get("headline"), out.get("show_title"))
    if hl != out.get("headline") or st != out.get("show_title"):
        out["headline"] = hl
        out["show_title"] = st
        if note:
            out["note"] = note
    return out


def classify_tour_line(line):
    """Return (presenter, tour) from a line above the bill on the page."""
    l = (line or "").strip()
    if not l:
        return None, None
    up = l.upper()
    if re.search(r"\b(IN THE ROUND|RESCHEDULED FROM|MOVED TO|ADDED BY POPULAR DEMAND)\b", up):
        return None, None
    m = re.search(r"^(.*?)\s+(?:x\s+)?[A-Z&'.\s\w]+?\s+PRESENTS?\s*:?\s*(.*)$", l)
    pres = None
    tour = None
    if re.search(r"PRESENTS", up):
        pres = re.sub(r"\s*PRESENTS?[:\s]*$", "", l).strip() or None
        after = re.split(r"PRESENTS", l, flags=re.I)[1].strip().lstrip(": ").rstrip("!.")
        tour = after or None
        if not pres or len(pres) < 2:
            pres = None
    elif re.search(r"\b(TOUR|ALBUM|ANNIVERSARY|RAISE AT|NIGHTS|SPELL)\b", up):
        tour = l.rstrip("!.")
    return pres, tour


def main():
    events = json.load(open(SRC))
    lookup = load_lookup()
    today = datetime.date.today().isoformat()
    base_year = datetime.date.today().year
    shows = []
    for ev in events:
        lines = [l.strip() for l in (ev.get("lines") or [])]
        di = None
        for j, l in enumerate(lines):
            if re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,\s+\w+ \d+", l) or re.search(r"Doors:", l):
                di = j
                break
        cands = [c for c in (lines[:di] if di is not None else lines[:4])
                 if not (ANNOUNCE.search(c) and "TOUR" not in c.upper())]
        # canonical bill (from the <title>) — the reliable headliner identity.
        # Computed here (not after the slot) so the headliner line can be
        # matched against the pre-date lines to open the support slot.
        pt = parse_title(ev.get("title_tag"), ev.get("name"))

        # Headliner line = the pre-date line that IS the canonical headliner.
        # (The old all-caps-only test fails on names like "Fink", so the bare
        # last-line fallback would wrongly pick the *support act* as headliner
        # and the support slot — and with it the act — would come out empty.)
        head = None
        for h in pt["headline"]:
            hl = re.sub(r"\s+", " ", h).strip().lower()
            if not hl:
                continue
            for c in cands:
                if re.sub(r"\s+", " ", c).strip().lower() == hl:
                    head = c
                    break
            # a status-word form keeps the name as a prefix of the page line
            # (head "POSTPONED" matches the line "POSTPONED - Sawyer Hill")
            if not head:
                for c in cands:
                    cc = re.sub(r"\s+", " ", c).strip().lower()
                    if len(cc) > len(hl) and cc.startswith(hl):
                        head = c
                        break
            # the re-keyed act sits INSIDE the statused page line
            # (head "Dogma" matches the line "POSTPONED: Dogma")
            if not head and len(hl) >= 4:
                for c in cands:
                    cc = re.sub(r"\s+", " ", c).strip().lower()
                    if hl in cc:
                        head = c
                        break
            if head:
                break
        if head is None:  # fall back to the old heuristics
            for c in reversed(cands):
                if c and any(ch.isalpha() for ch in c) and all(not ch.isalpha() or ch.isupper() for ch in c):
                    head = c
                    break
            if head is None and cands:
                head = cands[-1]
        hi = lines.index(head) if head in lines else None

        # ---- support acts: the page's support slot (lines strictly between head and date) ----
        slot = []
        if hi is not None and di is not None and di > hi:
            for seg in lines[hi + 1:di]:
                for part in re.split(r",|\s*&\s*|\s+and\s+", seg):
                    p = part.strip(" -\u2013\u2014")
                    if not valid_name(p):
                        continue
                    if p.lower() == (head or "").lower():
                        continue
                    if len(p) > 3 and p.lower() in (head or "").lower():
                        continue
                    slot.append(p)
        # drop compound (nested-span) lines in favour of their parts
        def norm(s):
            return re.sub(r"\s+", " ", s).strip()
        deduped = []
        for s in slot:
            sn = norm(s).lower()
            if any(norm(o).lower() in sn and norm(o).lower() != sn for o in slot):
                continue
            deduped.append(s)
        slot = deduped

        # ---- support = union of page slot + bill-derived, de-duped ----
        # (pt was already computed above to anchor the headliner line.)
        seen = set()
        support = []
        heads_l = [re.sub(r"\s+", " ", h).strip().lower() for h in pt["headline"]]
        for p in slot + pt["support"]:
            k = re.sub(r"\s+", " ", p).strip().lower()
            if k in seen:
                continue
            if any(len(k) > 3 and k in h for h in heads_l):
                continue
            # drop a slot line that is just the headline acts concatenated
            if heads_l and all(h in k for h in heads_l):
                continue
            seen.add(k)
            support.append(p)
        # ---- tour / presenter: lines strictly ABOVE the headliner line ----
        presenter, tour = None, None
        if hi is not None and hi > 0:
            for a in lines[:hi]:
                p, t = classify_tour_line(a)
                if p or t:
                    if t and t.lower() == head.lower():
                        continue  # it's the headliner line, not a tour
                    presenter, tour = p, t
                    break

        # ---- date + year ----
        raw = ev.get("date_raw") or ""
        m = re.match(r"(\w+),\s+(\w+) (\d+)", raw)
        iso = None
        if m:
            mon = MONTHS.get(m.group(2)[:3]); day = int(m.group(3))
            if mon:
                year = base_year if mon >= 10 else base_year + 1
                iso = f"{year}-{mon:02d}-{day:02d}"

        rec = common_build.show(
            headline_artists=[apple_music.artist_obj(h, lookup) for h in pt["headline"]],
            support_artists=[apple_music.artist_obj(p, lookup) for p in support],
            multi_artist=pt["multi_artist"],
            show_title=pt["show_title"] or tour,
            presenters=([presenter] if presenter else pt.get("presenters", [])),
            set_format=pt["set_format"],
            date=iso,
            doors=ev.get("doors_raw"),
            show_time=ev.get("show_raw"),
            ticket_link=ev.get("buy_url"),
            event_page=ev["href"],
        )
        if pt["note"]:
            rec["note"] = pt["note"]
        shows.append(rec)

    spotify.merge_shows(shows, spotify.from_captures(events, url_key="href"))
    stats = {"apple_music": apple_music.apple_music_stats(shows),
             "spotify": spotify.stats(shows)}
    common_build.run_build(VENUE, VENUE_ID, SRC_URL, SRC_URL, shows, stats)

    print(f"built {len(shows)} shows -> {DST}")
    print("years:", dict(Counter(s["date"][:4] for s in shows if s["date"])))
    print("no-date:", sum(1 for s in shows if not s["date"]),
          "| no-head:", sum(1 for s in shows if not s["headline_artists"]),
          "| no-ticket:", sum(1 for s in shows if not s["ticket_link"]))
    spec = ("frankie", "emo night", "nickcheo", "romare", "oden", "labiahead",
            "live on the stoop", "truise", "strongboi", "swervedriver", "dogma",
            "jack kays", "dan and peggy", "sister nancy", "weston")
    print("\n--- special-case results ---")
    for s in shows:
        h = " ".join(a["name"] for a in s["headline_artists"]).lower()
        if any(x in h for x in spec):
            print(f"  {[a['name'] for a in s['headline_artists']]} | "
                  f"sup:{[a['name'] for a in s['support_artists']]} | "
                  f"title:{s['show_title']} | fmt:{s['set_format']} | "
                  f"pres:{s['presenters']} | note:{s.get('note')} | multi:{s['multi_artist']} | {s['date']}")
    st = stats["apple_music"]
    print(f"\nApple Music: {st['found']}/{st['unique_artists']} unique artists found, "
          f"{st['not_found']} not found (placeholder + no exact match)")


if __name__ == "__main__":
    main()
