#!/usr/bin/env python3
"""Apple Music lookup driver — run per venue that matches Apple Music.

Usage (from a venue directory):
    python3 ../../common/lookup.py          # resume (skips cached artists)
    python3 ../../common/lookup.py --full   # re-lookup everything

Reads every artist name from <venue>/data/shows.json, queries the iTunes
Search API (entity=musicArtist), and writes a checkpointed cache at
<venue>/cache/lookup.json — one entry per billed name:

    { "iron & wine": {link, matched, confidence, status}, ... }

Statuses:
  exact     -- catalog artistName == billed name (normalized) -> 1.0
  likely    -- close variant (0.8-0.99): 'The X' vs 'X', '& the Band' lead,
               surname extension, paren-stripped core
  maybe     -- plausible but ambiguous (0.7-0.79)
  no_exact  -- nothing plausibly close -> not found
  error     -- network failure (will retry on next run)

The confidence engine + LINK_FLOOR safety rule live in common/apple_music.py
(single copy for all venues); this script only drives the API + the
checkpoint cache, which is checkpointed after every artist so a rerun
resumes where it left off.
"""
import os, sys, json, concurrent.futures
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repo root
from common import apple_music

VENUE_DIR = os.getcwd()  # run from the venue directory


def main():
    force = "--full" in sys.argv
    SRC = os.path.join(VENUE_DIR, "data", "shows.json")
    OUT = os.path.join(VENUE_DIR, "cache", "lookup.json")

    d = json.load(open(SRC))
    names = []
    for s in d["shows"]:
        for a in s.get("headline_artists", []) + s.get("support_artists", []):
            names.append(a["name"] if isinstance(a, dict) else str(a))
    uniq = list(dict.fromkeys(names))
    real = [n for n in uniq if not n.startswith("(")]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = {}
    if os.path.exists(OUT):
        try:
            out = json.load(open(OUT))
        except Exception:
            out = {}

    done = lambda a: (a in out and out[a].get("status") in
                      ("exact", "likely", "maybe", "no_exact"))
    todo = [a for a in real if (force or not done(a))]
    if force:
        out = {}  # full re-run: start the cache clean
    print(f"total {len(real)} real artists, {len(real)-len(todo)} cached, "
          f"{len(todo)} to fetch", flush=True)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(apple_music.lookup, a): a for a in todo}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()

    for i, a in enumerate(todo):
        out[a] = results[a]
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)
    json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)

    print("DONE:", dict(Counter(out[a]["status"] for a in real if a in out)))


if __name__ == "__main__":
    main()
