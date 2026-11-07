"""Shared scraper for Seattle Theatre Group (stgpresents.org).

STG runs The Paramount, The Moore, and The Neptune from ONE WordPress site on
the Modern Events Calendar (MEC) plugin. The public admin-ajax endpoint
`action=mec_list_load_more` (no nonce — discovered 2026-11-07 by hooking the
site's own Load-More XHR) returns ONE OCCURRENCE PER CARD with the real local
curtain time in `<span class="mec-start-time">` (the JSON-LD startDate carries
MEC's well-known timezone corruption: wall time mangled to a fake UTC offset —
trust only its DATE half, and take the time from mec-start-time).

Cards come 12 per page, one month per walk: offset++ with start_date = the
previous page's `end_date`; when a month is exhausted (has_more_event 0) move
to the next calendar month with offset 1. Empty far-future months return
count 0 (has_more_event still says 1 — do not trust it as a stop signal).

Categories (wp/v2/mec_category): 21 = Paramount, 18 = Moore, 19 = Neptune.
The rest (Kerry Hall education, 5th Avenue, Remlinger Farms…) are excluded
server-side by the category filter.

Titles/descriptions come from the public wp/v2/mec-events REST list (only
`publish`-status posts = future events; MEC flips past events to mec-expired).
"""
import json
import re
import subprocess
import time
import urllib.parse

BASE = "https://www.stgpresents.org"
AJAX = BASE + "/wp-admin/admin-ajax.php"
CATS = {"paramount": "21", "moore": "18", "neptune": "19"}
CAT_ALL = "21,18,19"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def _post(body):
    data = urllib.parse.urlencode(body)
    r = subprocess.run(
        ["curl", "-s", "--max-time", "30", "-A", UA, AJAX, "--data", data],
        capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def _cards(html):
    """Pair each JSON-LD Event block with its card fragment (everything from
    the LD script tag until the next one). Returns occurrence dicts."""
    out = []
    parts = re.split(r'(<script type="application/ld\+json"[^>]*>)', html)
    # parts: [pre, tag, json</script>+card, tag, json…+card, …]
    for i in range(1, len(parts) - 1, 2):
        frag = parts[i] + parts[i + 1]
        m = re.search(r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
                      frag, re.S)
        if not m:
            continue
        try:
            ev = json.loads(m.group(1))
        except Exception:
            continue
        if "Event" not in str(ev.get("@type", "")):
            continue
        card = frag[m.end():]
        tm = re.search(r'<span class="mec-start-time">([^<]+)</span>', card)
        status = str(ev.get("eventStatus", ""))
        st = "on_sale"
        if "Cancelled" in status:
            st = "cancelled"
        elif "Postponed" in status or re.search(r"POSTPONED|Postponed", card):
            st = "needs_review"
        sold = bool(re.search(r"mec-sold-?out|SOLD OUT", card, re.I))
        offers = ev.get("offers") or {}
        url = offers.get("url") or ""
        loc = (ev.get("location") or {}).get("name") or ""
        out.append({
            "name": ev.get("name", ""),
            "date": str(ev.get("startDate", ""))[:10],
            "start_time": (tm.group(1).strip() if tm else None),
            "venue": loc,
            "url": url,
            "slug": (url.rstrip("/").rsplit("/", 1)[-1] if url else ""),
            "status": st,
            "sold_out": sold,
            "desc_ld": ev.get("description", ""),
        })
    return out


def fetch_occurrences(months_ahead=13):
    """Walk mec_list_load_more month by month. Returns all cards for the three
    STG venues (plus incidental STG locations like the Tower — filter later)."""
    now = time.gmtime()
    y, mo = now.tm_year, now.tm_mon
    today = time.strftime("%Y-%m-%d", now)
    cards, empty_streak = [], 0
    for _ in range(months_ahead + 2):
        maxd = f"{y:04d}-{mo:02d}-{'28' if mo == 2 else '31'}"
        # PAGINATION SEMANTICS (fully probed 2026-11-07 against live):
        #  * rows are always filtered to >= max(start_date, TODAY) — a
        #    start_date in the past silently re-anchors to today;
        #  * mec_offset pages ONLY when start_date >= today; with a past
        #    start_date the offset is FORCED to 0 (page 1 re-served with
        #    count>0 forever). So a month-1st anchor + offset walk sees at
        #    most 12 rows per month (the bug that shrank neptune 105->40);
        #  * past the last page MEC CLAMPS (same tail, count>0,
        #    has_more_event=1) — stop on a repeated page, never on flags.
        # Correct walk = DATE CURSOR: start at the month anchor (today in
        # the first month), then jump start to the page's end_date each
        # turn (same-day rows re-appear and dedup at the end); a day with
        # more than one page uses offset (safe: cursor >= today).
        start = today if (y, mo) == (now.tm_year, now.tm_mon) else f"{y:04d}-{mo:02d}-01"
        offset, got, prev_sig = 0, 0, None
        while start <= maxd:
            d = _post({"action": "mec_list_load_more", "mec_year": y,
                       "mec_month": mo, "mec_maximum_date": maxd,
                       "mec_start_date": start, "mec_offset": offset,
                       "atts[category]": CAT_ALL, "atts[limit]": "12",
                       "atts[order]": "ASC", "atts[skin]": "list",
                       "atts[style]": "standard"})
            if d.get("count", 0) < 1:
                break
            page = _cards(d.get("html", ""))
            if not page:
                break
            sig = frozenset((c["date"], c["url"], c["start_time"]) for c in page)
            if sig == prev_sig:
                break  # clamped tail
            cards.extend(page)
            got += len(page)
            prev_sig = sig
            end = (d.get("end_date") or "")[:10]
            if end > start:
                start, offset = end, 0  # date cursor advances
            else:
                offset += 1  # busier than one page in a single day
                if offset > 10:
                    break
        empty_streak = 0 if got else empty_streak + 1
        if empty_streak >= 4:  # sparse months are real (no-show Feb exists)
            break
        mo += 1
        if mo > 12:
            mo, y = 1, y + 1
    # dedup identical (date,url) pairs
    seen, out = set(), []
    for c in cards:
        k = (c["date"], c["url"], c["start_time"])
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def details_for(slugs):
    """wp/v2/mec-events?slug=a,b,c — content.rendered + title per event post.
    Chunked at 12 slugs/request. Returns {slug: {title, content}}."""
    out = {}
    slugs = sorted(set(s for s in slugs if s))
    for i in range(0, len(slugs), 12):
        q = urllib.parse.urlencode({"slug": ",".join(slugs[i:i + 12]),
                                    "per_page": 12, "_fields": "slug,title,content"})
        r = subprocess.run(
            ["curl", "-s", "--max-time", "30", "-A", UA,
             f"{BASE}/wp-json/wp/v2/mec-events?{q}"],
            capture_output=True, text=True)
        try:
            for it in json.loads(r.stdout):
                out[it["slug"]] = {
                    "title": it.get("title", {}).get("rendered", ""),
                    "content": it.get("content", {}).get("rendered", ""),
                }
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- build side

COMEDY_RE = re.compile(
    r"stand-?up|(?<!central )comedian|comedy (?:tour|show|special|live|camp)|"
    r"\broast\b|live podcast", re.I)
THEATER_RE = re.compile(
    r"\bmusical\b|broadway|ballet|\bnutcracker\b|cirque|\bdance\b|dance (?:company|"
    r"theatre|theater|hol|arts)|\bplay\b|\bopera\b|illusion|magic show", re.I)
TITLE_THEATER_RE = re.compile(
    r"\bmusical\b|broadway|ballet|\bnutcracker\b|\bcirque\b|\bopera\b", re.I)
LECTURE_RE = re.compile(r"physicist|\bscientist\b|\bscience\b|\blecture\b", re.I)
_CC_RE = re.compile(r"comedy central", re.I)
# recurring non-show programming (museum-style tours) — Crystal Ballroom rule
RECURRING_RE = re.compile(r"(?i)^free .*tour$|first (?:thursday|saturday)")
_PRESENTER_RE = re.compile(r"(?i)^stg\b.*(present|welcome)")
_GUEST_RE = re.compile(r"(?i)^special guests?:?\s*$")
_DATE_LINE_RE = re.compile(r"(?i)^(mon|tues|tue|wed|thur|thu|fri|sat|sun)[a-z]*,?\s+\w+\.?\s+\d")
_SPECIAL_GUEST_RE = re.compile(r"(?i)^special guests?:\s*(.+)$")


def _lines(content):
    txt = re.sub(r"<[^>]+>", "\n", content or "")
    return [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n") if l.strip()]


def _hero(content):
    """Extract (tour, [guest names]) from the STG hero template:
    presenter line / headliner / [tour line] / [Special Guests: + names line]
    / date line. Guest names split on COMMA only (names contain &/and)."""
    lines = _lines(content)
    tour, guests = None, []
    for i, ln in enumerate(lines):
        if _PRESENTER_RE.match(ln):
            # headliner is lines[i+1]; tour, if present, lines[i+2] unless it
            # is the guests header, a date line, or a venue/seating line
            nxt = lines[i + 2] if i + 2 < len(lines) else ""
            if (nxt and not _GUEST_RE.match(nxt) and not _SPECIAL_GUEST_RE.match(nxt)
                    and not _DATE_LINE_RE.match(nxt)
                    and not re.match(r"(?i)the (paramount|moore|neptune) theatre", nxt)
                    and len(nxt) < 120):
                tour = nxt
            break
    for ln in lines:
        m = _SPECIAL_GUEST_RE.match(ln)
        if m:
            raw = m.group(1)
        elif _GUEST_RE.match(ln) and lines.index(ln) + 1 < len(lines):
            j = lines.index(ln) + 1
            raw = lines[j] if not _DATE_LINE_RE.match(lines[j]) else ""
        else:
            continue
        for part in raw.split(","):
            p = re.sub(r"^(and|&|with)\s+", "", part.strip()).strip(" &")
            if p and p.lower() not in ("and",):
                guests.append(p)
        break
    return tour, guests


def _age(content):
    t = re.sub(r"<[^>]+>", " ", content or "")
    m = re.search(r"\b(1[3689]|21)\+", t)
    if m:
        return m.group(1) + "+"
    if re.search(r"\ball[- ]ages\b", t, re.I):
        return "All Ages"
    return None


def _doors(content):
    """'Doors at 7pm' / 'Doors at 5:30pm' literal; 'Doors open one hour prior'
    passes through verbatim (relative truth beats an invented clock)."""
    t = re.sub(r"<[^>]+>", " ", content or "")
    m = re.search(r"(?i)doors at\s+(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))", t)
    if m:
        return m.group(1)
    m = re.search(r"(?i)doors open\s+([^.<;]{2,40})", t)
    return m.group(1).strip() if m else None


def _norm_time(t):
    if not t:
        return None
    m = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\.?\s*$", t.strip())
    if not m:
        return t.strip()
    mm = m.group(2)
    mm = "" if mm == "00" else mm
    return f"{int(m.group(1))}{(':'+mm) if mm else ''}{m.group(3).lower()}m"


def classify(title, bio, nperf):
    """Keller taxonomy: comedy regex over title+bio; theater nouns only fire
    on runs (nperf>=2) or the TITLE ('musical' is adjectival in concert
    bios); STG is a theater house so runs are 'other'."""
    text = f"{title}\n{bio}"
    if COMEDY_RE.search(_CC_RE.sub("", text)):
        return "comedy"
    if TITLE_THEATER_RE.search(title) or LECTURE_RE.search(text):
        return "other"
    if nperf >= 2 and THEATER_RE.search(text):
        return "other"
    return "music"


def build_shows(data, venue_key, common_build, apple_music, bill, spotify,
                lookup_cache, spotify_cache):
    """Turn {occurrences, details} into feed show records for one venue."""
    import html as _html
    import datetime
    from collections import Counter
    occ = data["occurrences"]
    det = data.get("details", {})
    today = datetime.date.today().isoformat()
    lookup = apple_music.load_lookup_cache(lookup_cache)
    nperfs = Counter(o["slug"] for o in occ)

    shows, dropped = [], []
    for o in occ:
        title = _html.unescape(re.sub(r"\s+", " ", o["name"])).strip()
        # STG writes cancellations INTO the title: "Prateek Kuhad – CANCELED".
        # The marker is a status, never part of the billed name (2026-11-07).
        title_status = None
        ms = re.search(r"(?i)[\s\u2013\u2014]*(?:[\(\[]\s*)?\b(CANCELED|CANCELLED|POSTPONED|POSTPON|RESCHEDULED)\s*(?:[\)\]]\s*)?$", title)
        if ms:
            word = ms.group(1).upper()
            title_status = "cancelled" if word.startswith("CANCEL") else "postponed"
            title = title[:ms.start()].strip()
        if not title or o["date"] < today:
            continue
        if RECURRING_RE.search(title):
            dropped.append(f"{o['date']} {title} (recurring program)")
            continue
        d = det.get(o["slug"], {})
        content = d.get("content", "")
        bio_txt = re.sub(r"<[^>]+>", " ", content)
        etype = classify(title, bio_txt, nperfs[o["slug"]])
        # Theater/comedy titles are SHOW names ("Oh, Mary!", "The Bald and
        # the Beautiful") — parse_bill would comma/"and"-split them into
        # fake multi-artist bills. Only music titles get bill grammar.
        if etype == "music":
            tour_from_hero, hero_guests = _hero(content)
            parsed = bill.parse_bill(title)
            tour = parsed.get("tour") or tour_from_hero
            heads = [h.strip(" -–—,.|:;") for h in parsed["heads"] if h.strip()] or [title]
            support = [s.strip(" -–—,.|:;") for s in parsed["support"] if s.strip()]
            low = {h.lower() for h in heads}
            for g in hero_guests:
                if g.lower() not in low and g.lower() not in {s.lower() for s in support}:
                    support.append(g)
        else:
            tour, heads, support = None, [title], []
        status = o["status"] if o["status"] != "on_sale" else "on sale"
        if o.get("sold_out") and status == "on sale":
            status = "sold out"
        if title_status:
            status = title_status
        note = None
        if o["status"] == "needs_review":
            note = "listed Postponed on STG calendar"
        rec = common_build.show(
            event_type=etype,
            needs_review=(o["status"] == "needs_review"),
            headline_artists=[apple_music.artist_obj(h, lookup) for h in heads],
            support_artists=[apple_music.artist_obj(s, lookup) for s in support],
            show_title=(tour.strip(" -–—,.|:;") or None) if tour else None,
            date=o["date"],
            doors=_doors(content),
            show_time=_norm_time(o["start_time"]),
            ticket_link=o["url"] or None,
            ticket_status=status,
            event_page=o["url"] or None,
            room=None,
            age_rating=_age(content),
            note=note,
        )
        shows.append(rec)
    shows.sort(key=lambda s: (s.get("date") or "9999"))
    common_build.apply_spotify_lookup(shows, spotify_cache)
    stats = {
        "event_types": dict(Counter(s["event_type"] for s in shows)),
        "apple_music": apple_music.apple_music_stats(shows),
        "spotify": spotify.stats(shows),
    }
    return shows, stats, dropped
