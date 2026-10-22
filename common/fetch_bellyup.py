#!/usr/bin/env python3
"""Fetch the Belly Up Presents shared calendar and keep only THIS venue's rows.

Run from a bellyup-group venue directory (bellyup/ thesound/ thecasbah/
theobservatory/ musicbox/ humphreys/). One GET of bellyup.com/calendar
returns the whole multi-venue season (the promoter runs all six San Diego
rooms from one TicketWeb calendar): a `events:[…]` JS array (id/start/
title/venue/doors/displayTime) + one hidden popup per event (canonical name,
description, ticket-button sale state, detail URL). The shared parser lives
in common/bellyup.py.

The venue is identified from the registry entry under the current directory
(`bellyup_venue` = the venue cell text on bellyup.com's calendar + alias
fallbacks).

Output: cache/events.json (this venue's rows only). Do NOT write a
freshness stamp — update_all.py stamps cache/events.json.fetched_at.
"""
import os
import re
import sys
import json
import time
import urllib.request

# The venue directory is the CWD (update_all.py / manual runs both cd there).
HERE = os.path.abspath(os.getcwd())
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from common import bellyup  # noqa: E402
from common import venues as registry  # noqa: E402

URL = "https://bellyup.com/calendar"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(CACHE, "events.json")


def fetch(url, retries=3):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(2.0)
    print(f"  ! fetch failed {url}: {last!r}")
    return None


def _venue_names():
    """(primary, aliases) from the registry entry for the current directory."""
    for v in registry.VENUES.values():
        if os.path.abspath(v["dir"]) == HERE:
            return v.get("bellyup_venue"), v.get("bellyup_venue_aliases") or []
    raise SystemExit("no registry entry for this directory — add bellyup_venue")


def is_mine(venue_text, names):
    if not venue_text:
        return False
    v = re.sub(r"\s+", " ", venue_text).strip().lower()
    for n in names:
        if n and (n.lower() == v or n.lower() in v or v in n.lower()):
            return True
    return False


def run():
    primary, aliases = _venue_names()
    names = [primary] + list(aliases)
    h = fetch(URL)
    if h is None:
        print("ABORT: calendar fetch failed")
        return 1
    events = bellyup.extract_events(h)
    pops = bellyup.extract_popups(h)
    mine = []
    for e in events:
        if not is_mine(e.get("venue"), names):
            continue
        p = pops.get(e["id"]) or {}
        mine.append({
            **e,
            "canonical_name": p.get("name"),
            "description": p.get("description"),
            "prefix_text": p.get("prefix_text"),
            "ticket_class": p.get("ticket_class"),
            "ticket_link": p.get("ticket_link"),
            "event_page": p.get("event_page"),
        })
    os.makedirs(CACHE, exist_ok=True)
    json.dump(mine, open(OUT, "w"), indent=2, ensure_ascii=False)
    print(f"{primary}: {len(mine)} shows -> cache/events.json")
    return 0


if __name__ == "__main__":
    sys.exit(run())
