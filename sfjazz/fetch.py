#!/usr/bin/env python3
"""Fetch the SFJAZZ Center schedule (venue adapter capture step).

Source: https://sfshows.app/venues/sfJazz — a fully server-rendered,
curl-able third-party calendar that mirrors the SFJAZZ 2026-27 season
(per-performance cards, no pagination). The official site (sfjazz.org) is
site-wide Cloudflare-walled to both curl AND a real browser (verified
2026-11-09: /calendar, the WP REST API, and even the homepage all 403
"Performing security verification"), so it is NOT a viable recurring
source — this calendar is. Each card is a clean <li class="event-card">:

    <li class="event-card">
      <a class="event-card-link" href="https://www.sfjazz.org/tickets/
         productions/26-27/<slug>/"></a>
      <div class="event-media"><img .../></div>
      <div class="event-content">
        <h3>Artist Name</h3>
        <p class="event-details">
          <time class="event-time" dateTime="2026-11-13T03:30:00.000Z">
            Nov 12, 2026, 7:30 PM</time>
        </p>
      </div>
    </li>

The `dateTime` is the performance start in UTC (SF is UTC-8, so 03:30Z =
7:30 PM local). We store the UTC instant and the local date; the show_time
is derived from the local (America/Los_Angeles) wall clock so the display
matches what a ticket buyer sees. The card carries NO room, age, price, or
support line — those live on the official detail page, which is behind the
Cloudflare wall, so they are honestly null here (the third-party feed has no
Spotify/description/bios either). The official /tickets/... link is kept as
the event_page + ticket_link (a real, useful deep link even if it 403s for
us).

Output (cache/):
  shows.json    list of per-show records (date, show_time, ticket_link,
                event_page) — one record per performance.

Do NOT write a freshness stamp — the root update_all.py runner writes
cache/shows.json.fetched_at and skips the re-crawl when it is < 24h old.
"""
import os, re, html, json, time, urllib.request, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
OUT = os.path.join(CACHE, "shows.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SHOWS_URL = "https://sfshows.app/venues/sfJazz"


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
    """Tags -> whitespace-collapsed text, entities unescaped."""
    if not fragment:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _li(src, start):
    """The <li> that OPENS at `start`, via a balanced <li> depth counter."""
    depth = 0
    for m in re.finditer(r"<li\b|</li>", src[start:]):
        if m.group() == "<li":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return src[start:start + m.end()]
    return src[start:]


def parse_shows(src):
    """Every <li class="event-card"> -> a per-performance record (dedup)."""
    rows, seen = [], set()
    for m in re.finditer(r'<li class="event-card"', src):
        card = _li(src, m.start())
        name_m = re.search(r"<h3>(.*?)</h3>", card, re.S)
        time_m = re.search(r'<time[^>]*dateTime="([^"]+)"[^>]*>(.*?)</time>',
                           card, re.S)
        href_m = re.search(r'<a[^>]*class="event-card-link"[^>]*href="([^"]+)"',
                           card)
        head = _text(name_m.group(1)) if name_m else None
        iso = time_m.group(1) if time_m else None
        if not head or not iso:
            continue
        # UTC instant -> America/Los_Angeles local wall clock.
        try:
            utc = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        try:
            import zoneinfo
            loc = utc.astimezone(zoneinfo.ZoneInfo("America/Los_Angeles"))
        except Exception:
            loc = utc  # fallback: use UTC if tz data is missing
        date = loc.strftime("%Y-%m-%d")
        show_time = loc.strftime("%I:%M %p").lstrip("0")
        key = (date, head.lower())
        if key in seen:
            continue
        seen.add(key)
        link = html.unescape(href_m.group(1)) if href_m else None
        rows.append({
            "date": date,
            "show_time": show_time,
            "headliner": head,
            "ticket_link": link,
            "event_page": link,
        })
    rows.sort(key=lambda r: (r["date"], r.get("show_time") or ""))
    return rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    src = fetch(SHOWS_URL)
    if src is None:
        raise SystemExit("could not fetch the sfshows.app SFJAZZ calendar")
    open(os.path.join(CACHE, "shows_raw.html"), "w").write(src)
    rows = parse_shows(src)
    json.dump(rows, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"shows: {len(rows)} (per-performance)")
    if rows:
        print(f"first: {rows[0]['date']}  {rows[0]['headliner']}")
        print(f"last:  {rows[-1]['date']}  {rows[-1]['headliner']}")
    for r in rows[:12]:
        print(f"  {r['date']}  {r['headliner'][:34]:34} {r.get('show_time') or ''}")


if __name__ == "__main__":
    main()
