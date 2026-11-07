#!/usr/bin/env python3
"""Fetch the Polaris Hall calendar (venue adapter capture step).

Source: polarishall.com — a one-page SSR site (custom CMS, NOT WordPress);
the whole upcoming calendar renders server-side inside #shows:
events__grid-event > .event blocks, ~58 cards in ONE GET:

  event__date          "Friday, Nov 6"   — NO YEAR; cards are chronological
                                          (one stale yesterday-card allowed)
  event__presenter     "Polaris Hall Presents" — constant, skipped
  event__title         "Murray Hill - Showbiz! The Tour"
  event__performers    support line (absent on some shows)
  event__time--doors/show   "7PM" / "7:30PM"
  event__action        etix link; CTA text "Get Tickets" | "Sold Out"

Year inference: month >= current month -> this year, else next year
(the walk spans Nov 2026 -> May 2027; a genuinely past show just drops in
build). Monotonic ordering is asserted and warned on drift.

Age limits are NOT on the site (only via etix product pages, which are
bot-walled at 202) — age_rating stays null; documented limitation.
Poster images come from cdn.etix.com (venue feeds etix itself).

Output cache/shows.json (list). No freshness stamp (update_all owns it).
"""
import os, re, html, json, time, datetime, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
URL = "https://polarishall.com/"
MONTHS = {m: i for i, m in enumerate(
    ("jan feb mar apr may jun jul aug sep oct nov dec".split()), 1)}


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


def parse_cards(src):
    at = [m.start() for m in re.finditer(r'class="events__grid-event"', src)]
    today = datetime.date.today()
    rows, prev = [], None
    for k, s in enumerate(at):
        b = src[s: at[k + 1] if k + 1 < len(at) else s + 6000]

        def field(pat):
            m = re.search(pat, b, re.S)
            return _text(m.group(1)) if m else None
        dtext = field(r'event__date">([^<]+)<')
        md = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})", dtext or "")
        date = None
        if md and md.group(1).lower()[:3] in MONTHS:
            mo, day = MONTHS[md.group(1).lower()[:3]], int(md.group(2))
            yr = today.year if mo >= today.month else today.year + 1
            date = f"{yr}-{mo:02d}-{day:02d}"
        cta = re.search(r'class="event__action"[^>]*href="([^"]+)"[^>]*>(?:\s*<[^>]+>)*\s*([^<]{3,30}?)\s*<', b, re.S)
        poster = re.search(r'alt="Show poster for [“"]([^”"]+)[”"]"', b)
        row = {
            "date": date, "date_text": dtext,
            "presenter": field(r'event__presenter">([^<]+)<'),
            "title": field(r'event__title">([^<]+)<'),
            "poster_title": _text(poster.group(1)) if poster else None,
            "support_billed": field(r'event__performers">([^<]+)<'),
            "doors": field(r'event__time--doors[^>]*>.*?event__time-value">([^<]+)<'),
            "show_time": field(r'event__time--show[^>]*>.*?event__time-value">([^<]+)<'),
            "ticket_link": html.unescape(cta.group(1)) if cta else None,
            "cta_text": _text(cta.group(2)) if cta else None,
        }
        if date and prev and date < prev:
            print(f"  WARN non-chronological card: {row['date_text']} ({date}) after {prev}")
        if date:
            prev = date
        rows.append(row)
    return rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(URL)
    if src is None:
        raise SystemExit("homepage fetch failed")
    with open(os.path.join(CACHE, "events.html"), "w", encoding="utf-8") as f:
        f.write(src)
    rows = parse_cards(src)
    json.dump(rows, open(os.path.join(CACHE, "shows.json"), "w"),
              indent=1, ensure_ascii=False)
    today = datetime.date.today().isoformat()
    print(f"cards: {len(rows)} | undated: {sum(1 for r in rows if not r['date'])} "
          f"| past (build drops): {sum(1 for r in rows if r['date'] and r['date'] < today)}")
    from collections import Counter
    print("CTA texts:", dict(Counter(r["cta_text"] or "-" for r in rows)))
    mism = [r for r in rows if r["title"] and r["poster_title"] and r["title"] != r["poster_title"]]
    if mism:
        print(f"note: poster title differs from billed title on {len(mism)} cards "
              f"(poster alt is a venue echo, not authoritative)")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['title'][:60]}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['title'][:60]}")


if __name__ == "__main__":
    main()
