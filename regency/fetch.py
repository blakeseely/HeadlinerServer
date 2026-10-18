#!/usr/bin/env python3
"""Fetch The Regency Ballroom schedule into cache/events.json.

Source: the venue's website (theregencyballroom.com, an AEG/AXS template)
renders its event list client-side from a public Azure-blob JSON published by
AEG — the exact URL is embedded in the homepage HTML, so we discover it there
each run rather than hardcoding the id. The /events page path itself 403s
(nginx + JS app) and the See Tickets widget is lazy-loaded, but the A/B blob
needs no auth: a plain GET returns the FULL calendar in one request.

Each event record (40 rows, ~564KB) is pre-structured and covers everything
the build needs:
  title.headlinersText / title.supportingText / title.presentedByText /
  title.tour
  eventDateTimeISO, doorDateTimeISO, age
  ticketing.status / ticketing.url / ticketPriceLow
  eventId (for a canonical event page)

cache/events.json    list of raw event objects (kept verbatim for inspection)
                     (a `events.json.fetched_at` freshness stamp is written by
                     the root update_all runner, not by this script)
"""
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME_URL = "https://theregencyballroom.com/"
# Fallback if the homepage stops embedding the A/B url (it's been stable):
DEFAULT_BLOB = "https://aegwebprod.blob.core.windows.net/json/events/9/events.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
BLOB_RE = re.compile(r"https://aegwebprod\.blob\.core\.windows\.net/json/events/\d+/events\.json")


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def discover_blob_url():
    home = get(HOME_URL)
    m = BLOB_RE.search(home)
    if m:
        return m.group(0)
    print(f"  A/B blob url not found on {HOME_URL} — using known default",
          file=sys.stderr)
    return DEFAULT_BLOB


def slim(e):
    """Drop the heavy bits the build doesn't use (artist bios, media blobs,
    keyword noise) so the cache stays small; keep every field build.py reads."""
    e = {k: v for k, v in e.items()
         if k not in ("bio", "media", "relatedMedia", "olympics")}
    v = e.get("venue")
    if isinstance(v, dict):
        # same venue on every event; keep just the identity, drop the address
        e["venue"] = {"title": v.get("title"), "city": v.get("city")}
    a = e.get("associations")
    if isinstance(a, dict):
        for k in ("headliners", "supportingActs", "additionalPerformers"):
            for rec in a.get(k) or []:
                for heavy in ("bio", "media", "keywords"):
                    rec.pop(heavy, None)
    return e


def main():
    blob = discover_blob_url()
    raw = get(blob)
    data = json.loads(raw)
    events = [slim(e) for e in (data.get("events") or [])]
    if not events:
        raise SystemExit(f"empty event list from {blob}")
    # newest-first, as published; keep that order
    os.makedirs(os.path.join(HERE, "cache"), exist_ok=True)
    with open(os.path.join(HERE, "cache", "events.json"), "w") as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
    print(f"events: {len(events)}  (first {events[0].get('eventDateTimeISO')}, "
          f"last {events[-1].get('eventDateTimeISO')})")


if __name__ == "__main__":
    main()
