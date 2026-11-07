#!/usr/bin/env python3
"""Fetch the Holocene schedule (venue adapter capture step).

Source: holocene.org (NEW domain — the old holocenepdx.com is NXDOMAIN
since the venue rebuilt). No bot wall. The calendar /events/ is
SERVER-RENDERED (an SSR list that hydrates client-side; the HTML comments
say so) — all ~49 upcoming shows in one GET:

    <article class="crow" data-id="42334018">            <- etix performance id
      <div class="crow-date"><i…early</i>SAT<b>NOV 07</b></div>
      <h3 class="crow-title"><a href="/events/2026-11-07-<slug>">TITLE</a></h3>
      <div class="crow-meta"><span class="crow-when">5PM · 21+</span><b>Free – $9.97</b></div>
      <a class="spec-buy" href="https://www.etix.com/…">Tickets ↗</a>
    </article>

  buy variants:   ""            -> Tickets (on sale)
                  " disabled"   -> Sold out (still keeps its etix href)
                  " at-door"    -> At the door
                  " crow-buy-none" — no real status; detail page decides
  ISO date lives in the event href (never parse the badge), support is
  sometimes only in the slug ("-w-alix-page"), so per-show detail pages are
  fetched (incrementally, details.json cache) — they are honest-to-goodness
  structured:

    <p class="ev-presenter">Holocene Presents</p>
    <h1 class="ev-title">Jake Minch</h1>       <p class="ev-sub">Getting Big Tour</p>
    <p class="ev-with">with Alix Page</p>
    <dl class="ev-spec"> Doors 7PM / Ages All Ages / Price … / Venue …
    JSON-LD MusicEvent: performer[], startDate (SHOW start, -08:00),
    doorTime, eventStatus (EventScheduled/Cancelled/Postponed/Rescheduled),
    offers{url, availability InStock|SoldOut, price}, organizer, description.

The JSON-LD doubles as the audit validator's independent source.

Output (cache/): events.json (calendar rows), details.json (per-event-page
parsed billing, incremental), shows.json (calendar x detail join). Do NOT
write a freshness stamp — update_all.py owns cache/shows.json.fetched_at.
"""
import os, re, html, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
DETAILS = os.path.join(CACHE, "details.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
BASE = "https://www.holocene.org"
LIST = BASE + "/events"
DETAIL_MAX = 120


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


def parse_calendar(src):
    """article.crow rows -> {date, title, event_page, when, price,
    buy_class, ticket_link} (date = ISO from the href, never the badge)."""
    rows = []
    for m in re.finditer(r'<article class="crow"[\s\S]*?</article>', src):
        blk = m.group(0)
        hm = re.search(r'href="(/events/(\d{4}-\d{2}-\d{2})-[^"]+)"[^>]*>([^<]+)<', blk)
        if not hm:
            continue
        when = re.search(r'class="crow-when">([^<]+)<', blk)
        price = re.search(r'class="crow-meta".*?<b>([^<]+)</b>', blk, re.S)
        buy_tag = re.search(r"<(?:a|span)\s+class=\"spec-buy([^\"]*)\"[^>]*>", blk)
        buy_href = None
        if buy_tag:
            hm2 = re.search(r'href="([^"]+)"', buy_tag.group(0))
            buy_href = html.unescape(hm2.group(1)) if hm2 else None
        rows.append({
            "date": hm.group(2),
            "cal_title": _text(hm.group(3)),
            "event_page": BASE + hm.group(1),
            "when": _text(when.group(1)) if when else None,
            "price": _text(price.group(1)) if price else None,
            "buy_class": (buy_tag.group(1).strip() if buy_tag else "missing"),
            "ticket_link": buy_href,
        })
    # keep order; the calendar is one list, dedupe by URL defensively
    seen, out = set(), []
    for r in rows:
        if r["event_page"] not in seen:
            seen.add(r["event_page"])
            out.append(r)
    return out


def parse_detail(src):
    """event page -> LD billing + ev-* billing block + Ages."""
    out = {"ev_presenter": None, "ev_title": None, "ev_sub": None, "ev_with": None,
           "doors": None, "ages": None, "show": None, "event_status": None,
           "offers_url": None, "availability": None, "performers": None,
           "description": None}
    if not src:
        return out
    for mm in re.finditer(r'<script type="application/ld\+json">([\s\S]*?)</script>', src):
        try:
            d = json.loads(mm.group(1))
        except ValueError:
            continue
        if d.get("@type") != "MusicEvent":
            continue
        st = str(d.get("eventStatus") or "")
        out["event_status"] = (st.rsplit("/", 1)[-1] or None)
        sd = d.get("startDate") or ""
        m = re.match(r"\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2})", sd)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            out["show"] = f"{h % 12 or 12}:{mi:02d} {'am' if h < 12 else 'pm'}"
        out["doors"] = d.get("doorTime") or None
        perf = d.get("performer")
        if isinstance(perf, dict):
            perf = [perf]
        if isinstance(perf, list):
            out["performers"] = [p.get("name") for p in perf if p.get("name")]
        off = d.get("offers") or {}
        out["offers_url"] = off.get("url")
        av = str(off.get("availability") or "")
        out["availability"] = av.rsplit("/", 1)[-1] or None
        desc = d.get("description")
        if desc:
            out["description"] = re.sub(r"\s+", " ", html.unescape(desc)).strip()[:1500]
    def field(pat):
        m = re.search(pat, src, re.S)
        return _text(m.group(1)) if m else None
    out["ev_presenter"] = field(r'class="ev-presenter"[^>]*>(.*?)</p>')
    out["ev_title"] = field(r'class="ev-title"[^>]*>(.*?)</h1>')
    out["ev_sub"] = field(r'class="ev-sub"[^>]*>(.*?)</p>')
    out["ev_with"] = field(r'class="ev-with"[^>]*>(.*?)</p>')
    out["ages"] = field(r"<dt>Ages</dt>\s*<dd>(.*?)</dd>")
    dm = re.search(r"<dt>Doors</dt>\s*<dd>(.*?)</dd>", src)
    if dm:
        out["doors"] = _text(dm.group(1)) or out["doors"]
    return out


def fetch_details(urls):
    have = {}
    if os.path.exists(DETAILS):
        try:
            have = json.load(open(DETAILS))
        except ValueError:
            have = {}
    todo = [u for u in urls if u not in have][:DETAIL_MAX]
    if todo:
        def work(u):
            return u, parse_detail(fetch(u))
        with ThreadPoolExecutor(max_workers=3) as ex:
            for u, fields in ex.map(work, todo):
                have[u] = fields
                time.sleep(0.2)
    json.dump(have, open(DETAILS, "w"), indent=1, ensure_ascii=False)
    return have


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(LIST)
    if src is None:
        raise SystemExit("FATAL: /events unreachable")
    rows = parse_calendar(src)
    json.dump(rows, open(os.path.join(CACHE, "events.json"), "w"),
              indent=1, ensure_ascii=False)

    details = fetch_details([r["event_page"] for r in rows])
    for r in rows:
        r.update(details.get(r["event_page"]) or {})
    rows.sort(key=lambda r: (r["date"], r["event_page"]))
    json.dump(rows, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)

    print(f"calendar rows: {len(rows)}")
    nostatus = [r for r in rows if not r.get("event_status")]
    if nostatus:
        print(f"WARNING rows without LD event_status: {len(nostatus)}")
        for r in nostatus[:8]:
            print("    ", r["date"], r["cal_title"][:60])
    bad = [r for r in rows if not r.get("ev_title")]
    if bad:
        print(f"rows without ev_title (LD/calendar fallback needed): {len(bad)}")
        for r in bad[:8]:
            print("    ", r["date"], r["cal_title"][:60])
    from collections import Counter
    print("event_status:", dict(Counter(r.get("event_status") or "-" for r in rows)))
    print("buy_class:", dict(Counter(r["buy_class"] or "plain" for r in rows)))
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['cal_title'][:60]}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['cal_title'][:60]}")


if __name__ == "__main__":
    main()
