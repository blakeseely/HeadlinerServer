#!/usr/bin/env python3
"""Fetch the Crystal Ballroom schedule (venue adapter capture step).

Source: crystalballroompdx.com (McMenamins / Edgefield Concerts, WordPress +
"The Events Calendar" plugin). TWO open endpoints, no bot wall, combined by
event URL:

  1. TEC REST API  GET /wp-json/tribe/events/v1/events?per_page=50&page=N
     — one unauthenticated JSON GET per page, the FULL upcoming window
     (~71 rows over ~2 years). Provides the ISO start/end date + times, the
     description, cost, and the canonical event URL. It does NOT carry
     ticket links, promoter, or the billed lineup.

  2. The "tour schedule" card grid — the homepage + /events/page/2../N
     (TEC-style pagination, 12 cards/page, stops with a 404). Each
     <div class="wm-tour-schedule-wrap"> card carries what the REST API
     lacks, as FIELDS (no title grammar on the card itself):

         promoter    <div class="event-list-promoter">Monqui Presents</div>
         special     <div class="event-list-special-billing">…</div>
         head billed <h1 class="hundred display-in-title">Sienna Spiro: My House Tour</h1>
         support     <h2 class="eighty hidden-card-title">with special guest Summer Joy</h2>
         date badge  <time class="icon"><strong>November</strong> <span>7</span></time>
         page link   <a class="details-button" href="/events/<id>-<slug>/">Details</a>
         ticket btn  <a class="buy-button" href="https://www.etix.com/ticket/p/…">Tickets</a>

     Sold-out is NOT encoded on the buttons (only buy/details variants exist
     today) — status maps from button presence and keeps any future button
     text verbatim.

BACKBONE = the card grid for BILLING FIELDS, but the REST rows are the
UNIVERSE: every REST row joins in unless it matches RECURRING_PROGRAM
(the venue's museum tour / market — genuine non-shows). A real show can
appear in REST but be card-less: Trampled by Turtles 2027-02-19 (found by
the nightly validator 2026-11-06) — those rows come in with billing from
their detail page and ticket link from the etix anchor there.

Doors/show semantics: TEC start_date is the SHOW start (Sienna Spiro:
start_date 20:00 = "8pm show"), so show_time falls back to start_date. The
detail pages carry a server-rendered `event-singular-time-details` html
module with the venue's own line — "6:30pm doors, 8pm show" + the age note
("All ages welcome") — captured per-URL incrementally (the cfdunord
details.json pattern). Age has no other source.

Output (cache/):
  events.json   dict url -> {start,end,all_day,description,cost,title}
  details.json  dict event_page url -> {doors, show, age}  (incremental)
  shows.json    list of per-show records (card x REST x detail join)

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/shows.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
BASE = "https://www.crystalballroompdx.com"
REST = BASE + "/wp-json/tribe/events/v1/events?per_page=50&page={page}"
CARD_PAGES = [BASE + "/"] + [BASE + f"/events/page/{n}/" for n in range(2, 13)]
REST_MAX_PAGES = 10
DETAIL_MAX = 160
# the venue's recurring non-show programming (museum tour, monthly market) —
# deliberately NOT in the feed; mirror: validator SOURCES['crystalball'].exclude_re
RECURRING_PROGRAM = re.compile(r"(?i)history\s*(?:&|and|–|-)\s*art\s*tour|first\s+thursday")


def fetch(url, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5)
    print(f"  ! fetch failed {url}: {last!r}")
    return None


def _text(fragment):
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def fetch_rest():
    """Walk the TEC REST pages -> dict url -> slim event record."""
    out = {}
    for page in range(1, REST_MAX_PAGES + 1):
        src = fetch(REST.format(page=page))
        if src is None:
            break
        try:
            d = json.loads(src, strict=False)
        except ValueError as e:
            print(f"  ! REST page {page} unparsable: {e}")
            break
        evs = d.get("events") or []
        for e in evs:
            url = e.get("url")
            if not url:
                continue
            out[url] = {
                "title": _text(e.get("title")),
                "start": e.get("start_date"),
                "end": e.get("end_date"),
                "all_day": bool(e.get("all_day")),
                "cost": (e.get("cost") or "").strip() or None,
                "description": _text(e.get("description") or "") or None,
            }
        if not d.get("next_rest_url"):
            break
        time.sleep(0.3)
    return out


def _title_frag(frag):
    """h2/h1 text with a hard span cap: on cards that lack the h2 element the
    lazy (.*?)</h2> can span to a RELATED card's header and swallow page
    boilerplate. Reject fragments that clearly ran past the element."""
    t = _text(frag)
    if not t or len(t) > 200 or re.search(r"Tickets|Add To Calendar|Share Event|Venue Info", t):
        return None
    return t


def parse_cards(src):
    """Every wm-tour-schedule-wrap card -> record keyed by event_page."""
    cards = []
    starts = [m.start() for m in re.finditer(r'class="wm-tour-schedule-wrap"', src)]
    for i, s in enumerate(starts):
        block = src[s: starts[i + 1] if i + 1 < len(starts) else s + 20000]

        def field(pat):
            m = re.search(pat, block, re.S)
            return _title_frag(m.group(1)) if m else None

        page_m = re.search(r'class="details-button"\s+href="([^"]+)"', block)
        # Two card flavors: the homepage tour-schedule widget bills as
        # display-in-title(h1)+hidden-card-title(h2); the deeper /events/
        # page-N grid cards bill as a plain <div class="title"
        # id="crystal-card-title"> with no support field (the detail page
        # then carries h1/h2 — fetch_details recovers them for every show).
        head = field(r'display-in-title[^>]*>(.*?)</h1>') or \
            field(r'class="title"\s+id="crystal-card-title"[^>]*>(.*?)</div>')
        if not page_m or not head:
            continue
        # buy button: iterate whole <a> tags and pull href from INSIDE the
        # tag (the APE attribute-order lesson: href may sit before class).
        buy_href = buy_text = None
        for tagm in re.finditer(r"<a\b[^>]*>", block):
            if re.search(r"""class=["']buy-button\b""", tagm.group(0)):
                hm = re.search(r"""href=["']([^"']+)""", tagm.group(0))
                if hm:
                    buy_href = html.unescape(hm.group(1))
                    end = block.find("</a>", tagm.end())
                    buy_text = _text(block[tagm.end():end if end > 0 else None])
                break
        badge = re.search(r'<time class="icon"[^>]*>(.*?)</time>', block, re.S)
        cards.append({
            "event_page": html.unescape(page_m.group(1)),
            "promoter": field(r'event-list-promoter[^>]*>(.*?)</div>'),
            "special_billing": field(r'event-list-special-billing[^>]*>(.*?)</div>'),
            "head_billed": head,
            "support_billed": field(r'hidden-card-title[^>]*>(.*?)</h2>'),
            "badge": _text(badge.group(1)) if badge else None,
            "ticket_text": buy_text,
            "ticket_link": buy_href,
        })
    return cards


def parse_time_block(src, page_url=None):
    """Detail page -> {head, support_raw, doors, show, age, ticket_link}. Every event's
    detail page bills h1 `display-in-title` + h2 `hidden-card-title` (the
    list card flavors only sometimes carry them) and carries a
    server-rendered `event-singular-time-details` html module ("5:30pm
    doors, 7pm show" + the age note). Honest nulls; venue wording verbatim."""
    out = {"head": None, "support_raw": None,
           "doors": None, "show": None, "age": None, "ticket_link": None}
    if not src:
        return out
    m = (re.search(r"display-in-title[^>]*>(.*?)</h1>", src, re.S)
         or re.search(r'class="title"\s+id="crystal-card-title"[^>]*>(.*?)</div>',
                      src, re.S))
    if m:
        out["head"] = _title_frag(m.group(1))
    m = re.search(r"hidden-card-title[^>]*>(.*?)</h2>", src, re.S)
    if m:
        out["support_raw"] = _title_frag(m.group(1))
    # ticket link: buy-button anchor if present, else the venue's etix/tix
    # anchor anywhere on the page (card-less shows bill only here; the APE
    # attribute-order rule: pull href from inside the whole <a> tag).
    for tagm in re.finditer(r"<a\b[^>]*>", src):
        tag = tagm.group(0)
        if re.search(r"""class=["']buy-button\b""", tag):
            hm = re.search(r"""href=["']([^"']+)""", tag)
            if hm:
                out["ticket_link"] = html.unescape(hm.group(1))
                break
    if not out["ticket_link"]:
        cands = [html.unescape(h) for h in re.findall(
            r"""href=["']([^"']*(?:etix\.com|ticketmaster\.com|ticketweb)[^"']*)""", src)]
        if cands:
            # detail pages can list related events with their own buy links:
            # prefer the candidate whose URL words overlap THIS event's slug
            slug_words = set(re.findall(r"[a-z0-9]{4,}", (page_url or "").lower()))
            def score(u):
                return len(slug_words & set(re.findall(r"[a-z0-9]{4,}", u.lower())))
            out["ticket_link"] = max(cands, key=score) if len(cands) > 1 else cands[0]
    i = src.find("event-singular-time-details")
    if i >= 0:
        # module text up to the next fl-module (or a generous window)
        j = src.find("fl-module ", i)
        block = src[i: j if 0 < j - i < 3000 else i + 3000]
        text = _text(block) or ""
        m = re.search(r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s*doors?", text, re.I)
        if m:
            out["doors"] = re.sub(r"\s+", "", m.group(1)).lower()
        m = re.search(r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s*(?:show|music|performance)",
                      text, re.I)
        if m:
            out["show"] = re.sub(r"\s+", "", m.group(1)).lower()
        m = re.search(r"(?i)(all ages(?:\s+welcome)?|"
                      r"\d{1,2}\+\s*(?:and over|or older|only|kids? only)?|"
                      r"\d{1,2}\s*(?:and (?:up|over)|years and up|yo and up))", text)
        if m:
            out["age"] = re.sub(r"\s+", " ", m.group(1)).strip()
    return out


def fetch_details(urls):
    """event_page -> time-block fields, incremental by URL (a key that
    exists with all-None values means 'crawled, venue published nothing')."""
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    todo = [u for u in urls if u not in have][:DETAIL_MAX]
    if todo:
        def work(u):
            return u, parse_time_block(fetch(u), u)
        with ThreadPoolExecutor(max_workers=3) as ex:
            for u, fields in ex.map(work, todo):
                have[u] = fields
                time.sleep(0.2)
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)

    rest = fetch_rest()
    json.dump(rest, open(os.path.join(CACHE, "events.json"), "w"),
              indent=1, ensure_ascii=False)

    # Card pages: fetch until a page yields no cards (404 -> no cards).
    seen, cards = set(), []
    for url in CARD_PAGES:
        src = fetch(url)
        if src is None:
            break
        found = parse_cards(src)
        fresh = [c for c in found if c["event_page"] not in seen]
        if not fresh:
            break
        for c in fresh:
            seen.add(c["event_page"])
        cards.extend(fresh)
        time.sleep(0.3)
    cards.sort(key=lambda c: c["event_page"])

    rows, dropped = [], []
    for c in cards:
        e = rest.get(c["event_page"])
        if not e:
            dropped.append(f"(no REST row) {c['event_page']}")
            continue
        rows.append({
            "date": (e.get("start") or "")[:10] or None,
            "start_iso": e.get("start"),
            "end_iso": e.get("end"),
            "all_day": e.get("all_day"),
            "head_billed": c["head_billed"],
            "support_billed": c["support_billed"],
            "special_billing": c["special_billing"],
            "promoter": c["promoter"],
            "ticket_status_raw": c["ticket_text"],
            "ticket_link": c["ticket_link"],
            "event_page": c["event_page"],
            "rest_title": e.get("title"),
            "cost": e.get("cost"),
            "description": (e.get("description") or "")[:1500] or None,
        })
    rows.sort(key=lambda r: (r.get("start_iso") or r.get("date") or ""))

    # Card-less REST rows: real shows the tour-schedule widget omits come in
    # too (Trampled by Turtles 2027-02-19 was exactly this); only the venue's
    # recurring non-show programming is refused.
    cardless, skipped = [], []
    used = {r["event_page"] for r in rows}
    for u, e in rest.items():
        if u in used:
            continue
        if RECURRING_PROGRAM.search(e.get("title") or ""):
            skipped.append((e.get("start") or "")[:10] + "  " + (e.get("title") or "?"))
            continue
        cardless.append({
            "date": (e.get("start") or "")[:10] or None,
            "start_iso": e.get("start"),
            "end_iso": e.get("end"),
            "all_day": e.get("all_day"),
            "head_billed": None, "support_billed": None, "special_billing": None,
            "promoter": None, "ticket_status_raw": None, "ticket_link": None,
            "event_page": u, "rest_title": e.get("title"),
            "cost": e.get("cost"),
            "description": (e.get("description") or "")[:1500] or None,
        })
    rows.extend(cardless)
    rows.sort(key=lambda r: (r.get("start_iso") or r.get("date") or ""))

    details = fetch_details([r["event_page"] for r in rows])
    for r in rows:
        d = details.get(r["event_page"]) or {}
        # The detail page bills every show identically (h1+h2) — authoritative
        # over the two different list-card flavors.
        r["head_billed"] = d.get("head") or r["head_billed"]
        if d.get("support_raw"):
            r["support_billed"] = d["support_raw"]
        r["doors"] = d.get("doors")
        r["show_time"] = d.get("show")
        r["age"] = d.get("age")
        if not r.get("ticket_link") and d.get("ticket_link"):
            r["ticket_link"] = d["ticket_link"]
            r["ticket_status_raw"] = r["ticket_status_raw"] or "Tickets"

    json.dump(rows, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)

    print(f"rest rows: {len(rest)}  cards: {len(rows) - len(cardless)}  card-less shows added: {len(cardless)}")
    for r in cardless:
        print(f"    CARDLESS {r['date']}  {r['rest_title']}")
    print(f"recurring non-show programming skipped: {len(skipped)}")
    for line in skipped[:10]:
        print(f"    {line}")
    if len(skipped) > 10:
        print(f"    ... +{len(skipped) - 10} more")
    if dropped:
        print(f"WARNING cards without a REST row (skipped): {len(dropped)}")
        for line in dropped[:10]:
            print(f"    {line}")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['head_billed']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['head_billed']}")


if __name__ == "__main__":
    main()
