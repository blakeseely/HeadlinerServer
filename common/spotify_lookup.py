#!/usr/bin/env python3
"""Spotify lookup driver — run per venue whose site publishes NO links.

Usage (from a venue directory):
    python3 ../../common/spotify_lookup.py          # resume (skips cached)
    python3 ../../common/spotify_lookup.py --full   # re-lookup everything

Reads every artist name from <venue>/data/shows.json, queries the Spotify
Web API (client-credentials + /v1/search), and writes a checkpointed cache
at <venue>/cache/spotify_lookup.json — one entry per billed name:

    { "iron & wine": {link, matched, confidence, status}, ... }

Statuses (same ladder as the Apple Music engine, same confidence function):
  exact     -- catalog artist name == billed name (normalized) -> 1.0
  likely    -- close variant (>= 0.80)
  maybe     -- plausible but ambiguous (0.70-0.79)
  no_exact  -- nothing plausibly close -> not found (honest null)
  error     -- network failure (retried on the next run)

Resume: an artist with a terminal status (exact/likely/maybe/no_exact) is
skipped; a `configured: False` entry means the keys were absent when it was
checked — it is re-queried as soon as credentials appear. Paced at 2
workers (Spotify's rate budget is far tighter than iTunes').
"""
import json
import os
import sys
import concurrent.futures
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root
from common import apple_music
from common import spotify_api

VENUE_DIR = os.getcwd()  # run from the venue directory


def main():
    force = "--full" in sys.argv
    SRC = os.path.join(VENUE_DIR, "data", "shows.json")
    OUT = os.path.join(VENUE_DIR, "cache", "spotify_lookup.json")

    if not spotify_api.load_credentials()[0]:
        print("SKIP: no SPOTIFY_CLIENT_ID/SECRET in .env — nothing to do.",
              flush=True)
        return

    d = json.load(open(SRC))
    names = []
    for s in d["shows"]:
        for a in s.get("headline_artists", []) + s.get("support_artists", []):
            names.append(a["name"] if isinstance(a, dict) else str(a))
    uniq = list(dict.fromkeys(names))
    real = [n for n in uniq if not n.startswith("(")]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = {}
    prior = {}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            out = {}
        prior = dict(out)  # keep the pre-run cache so a failed re-lookup
                            # (daily quota) can't clobber a good link

    done = lambda a: (a in out
                      and out[a].get("status") in
                      ("exact", "likely", "maybe", "no_exact")
                      and not out[a].get("configured") is False)
    todo = [a for a in real if (force or not done(a))]
    if force:
        out = {}
    print(f"total {len(real)} real artists, {len(real)-len(todo)} cached, "
          f"{len(todo)} to fetch", flush=True)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        futs = {ex.submit(spotify_api.lookup, a): a for a in todo}
        for n, fut in enumerate(concurrent.futures.as_completed(futs), 1):
            a = futs[fut]
            results[a] = fut.result()
            if n % 25 == 0:
                print(f"  {n}/{len(todo)} done", flush=True)

    for a in todo:
        r = results[a]
        if (r.get("status") == "error" and prior.get(a, {}).get("link")
                and prior[a].get("status") in ("exact", "likely")):
            r = dict(prior[a])  # re-lookup failed (e.g. daily quota):
                                # keep the old good link, don't clobber it
        out[a] = r
        json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)

    print("DONE:", dict(Counter(out[a]["status"] for a in real if a in out)))


if __name__ == "__main__":
    main()
