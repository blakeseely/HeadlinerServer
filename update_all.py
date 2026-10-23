#!/usr/bin/env python3
"""update_all.py — one command to refresh every venue's data/shows.json.

For each venue in common/venues.py, in order:

  1. fetch   the venue's capture script (re-pull the site — always runs)
  2. build   data/shows.json from the fresh cache
  3. lookup  Apple Music for the billed artists (common/lookup.py)
  4. build   again, so the JSON carries the fresh links

Incremental (default): lookup.py's resume mode skips every artist that
already has a terminal status in <venue>/cache/lookup.json, so a typical
run spends its Apple Music time only on NEW or previously-failed artists.
The site is re-crawled only when the venue's cache is > 24h old (a
`.fetched_at` stamp is written after each fetch); `--refresh` forces a
re-crawl, and `--full` implies it and also clears each venue's lookup
cache for a complete Apple Music re-match.

  python3 update_all.py                   # all venues, incremental
  python3 update_all.py --full            # complete Apple Music re-match
  python3 update_all.py --refresh         # force the site re-crawl
  python3 update_all.py --venues a,b      # restrict the run

A venue whose fetch fails is skipped (with a warning) rather than blocking
the rest; the exit code is 1 when any venue failed.

At the end of each venue it prints a diff vs the pre-run shows.json:
  added / removed / schedule-changed / link-only, so a "nothing changed" week
is visible at a glance (and a future cron job can digest it).
"""
import os, sys, json, shutil, subprocess, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from common import venues as registry

# record fields whose change is a real schedule change (everything else —
# the apple_music fields inside artist dicts, description, needs_review —
# is "link-only / cosmetic" for diff purposes)
SCHEDULE_FIELDS = ("event_type", "headline_artists", "support_artists",
                   "multi_artist", "show_title", "date", "doors", "show_time",
                   "ticket_link", "ticket_status", "age_rating", "note")
ARTIST_IDENTITY = ("name",)          # only the billed NAME defines a show


def show_key(s):
    if s.get("event_page"):
        return s["event_page"]
    h = " / ".join(a["name"] for a in s.get("headline_artists", [])
                   if isinstance(a, dict))
    return f"{s.get('date')}::{h}"


def load_shows(path):
    try:
        return {show_key(s): s for s in json.load(open(path))["shows"]}
    except Exception:
        return {}


def schedule_of(s):
    return {f: s.get(f) for f in SCHEDULE_FIELDS}


def artist_links(s):
    out = []
    for f in ("headline_artists", "support_artists"):
        for a in s.get(f, []):
            if isinstance(a, dict):
                out.append({k: a.get(k) for k in
                            ("name", "apple_music", "confidence")})
    return out


def run(cmd, cwd, timeout=600):
    print(f"      $ {cmd}", flush=True)
    p = subprocess.run(cmd, shell=True, cwd=cwd,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout, text=True)
    out = p.stdout.strip()
    # echo the interesting lines (first/last few), indented
    lines = out.splitlines() if out else []
    for ln in lines[:4]:
        print(f"       {ln}", flush=True)
    if len(lines) > 4:
        for ln in lines[-3:]:
            print(f"       {ln}", flush=True)
        print(f"       … {len(lines)} lines total", flush=True)
    return p.returncode, out


def stamp_fetched(cache_path):
    """Record when a capture file was pulled, so the runner can skip a
    redundant site crawl. A sibling `.fetched_at` text file works for both
    list- and dict-shaped captures."""
    if not os.path.exists(cache_path):
        return
    with open(cache_path + ".fetched_at", "w") as f:
        f.write(datetime.datetime.now().isoformat(timespec="seconds"))


def cache_age_ok(cache_path, max_age_h=24):
    """True when the capture should be reused: the file is missing (the build
    will fail loudly and tell us), or it was fetched within max_age_h."""
    stamp = cache_path + ".fetched_at"
    if not os.path.exists(stamp):
        return True      # pre-stamp capture: assume fresh
    try:
        t = datetime.datetime.fromisoformat(open(stamp).read().strip())
    except Exception:
        return True
    age_h = (datetime.datetime.now() - t).total_seconds() / 3600
    return age_h <= max_age_h


def diff_shows(old, new):
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    sched, links = [], []
    for k in new.keys() & old.keys():
        if schedule_of(new[k]) != schedule_of(old[k]):
            sched.append(k)
        elif artist_links(new[k]) != artist_links(old[k]):
            links.append(k)
    return added, removed, sched, links


def update_venue(v, full, refresh):
    key, d = v["key"], v["dir"]
    print(f"\n=== {v['name']} ({key}) — {'FULL' if full else 'incremental'}"
          f"{' + REFRESH' if refresh else ''} ===")
    shows_path = os.path.join(d, "data", "shows.json")
    old = load_shows(shows_path) if os.path.exists(shows_path) else {}
    t_venue = datetime.datetime.now()

    # 1. fetch the schedule — skip when the cache is fresh (this is the
    #    expensive site-crawl part; --refresh forces a re-crawl)
    if v.get("fetch_cmd"):
        cache = os.path.join(d, "cache", v.get("cache", "vfinal.json"))
        if not refresh and cache_age_ok(cache):
            print("      (fetch: cache < 24h old — skipping site crawl; "
                  "use --refresh to force)")
        else:
            rc, _ = run(v["fetch_cmd"], d)
            if rc != 0:
                print(f"  !! {key}: fetch FAILED — skipping venue", file=sys.stderr)
                return False
            stamp_fetched(cache)
    else:
        print("  (no fetch step; relying on committed cache)")

    # 2. build (first pass: render what we have, incl. stale/missing links)
    rc, _ = run("python3 build.py", d)
    if rc != 0:
        print(f"  !! {key}: build FAILED — skipping venue", file=sys.stderr)
        return False

    # 3. Apple Music lookup (resume by default; --full re-queries all)
    if v.get("has_apple_music"):
        rc, out = run(f"python3 ../common/lookup.py {'--full' if full else ''}", d)
        if rc != 0:
            print("  !! lookup FAILED — continuing with cached links",
                  file=sys.stderr)
        for ln in out.splitlines():
            if ln.startswith("total"):
                print(f"       ♪ {ln.strip()}")
    else:
        print("      (no Apple Music matching for this venue)")

    # 3b. Spotify API lookup — venues whose own site publishes NO links.
    # Resume by default (cache/spotify_lookup.json); --full re-queries all.
    # Venue-published links always win over a searched one (merge rule in
    # the build). No keys in .env = graceful SKIP, never a failure.
    if v.get("has_spotify_lookup"):
        rc, out = run(f"python3 ../common/spotify_lookup.py {'--full' if full else ''}", d)
        if rc != 0:
            print("  !! spotify lookup FAILED — continuing with cached links",
                  file=sys.stderr)
        for ln in out.splitlines():
            if ln.startswith(("total", "SKIP")):
                print(f"       🎧 {ln.strip()}")
    else:
        print("      (site-published Spotify links — no API lookup)")

    # 4. rebuild so the JSON carries the latest links
    rc, _ = run("python3 build.py", d)
    if rc != 0:
        print(f"  !! {key}: rebuild FAILED", file=sys.stderr)
        return False

    # 5. diff vs the pre-run JSON
    new = load_shows(shows_path)
    added, removed, sched, links = diff_shows(old, new)
    h = lambda k: (new.get(k) or old.get(k) or {}).get("date") or "?"
    print(f"  diff vs last run: {len(new)} shows — "
          f"added {len(added)}, removed {len(removed)}, "
          f"schedule-changed {len(sched)}, link-only {len(links)}")
    dt_v = (datetime.datetime.now() - t_venue).total_seconds()
    print(f"  venue time: {dt_v:.0f}s")
    for k in added[:6]:
        s = new[k]
        print(f"    + {h(k)}  {' / '.join(a['name'] for a in s.get('headline_artists', []))[:60]}")
    for k in removed[:6]:
        s = old[k]
        print(f"    - {h(k)}  {' / '.join(a['name'] for a in s.get('headline_artists', []))[:60]}")
    for k in sched[:6]:
        print(f"    ~ {h(k)}  {' / '.join(a['name'] for a in new[k].get('headline_artists', []))[:60]}")
    if not (added or removed or sched or links) and not full:
        print("    (nothing changed since last run)")
    return True


def main():
    full = "--full" in sys.argv
    refresh = "--refresh" in sys.argv or full
    sel = None
    if "--venues" in sys.argv:
        sel = [s.strip() for s in sys.argv[sys.argv.index("--venues") + 1].split(",")
               if s.strip()]
    items = [v for k, v in registry.VENUES.items()
             if sel is None or k in sel]
    if sel:
        missing = [s for s in sel if s not in registry.VENUES]
        if missing:
            sys.exit(f"unknown venue(s): {', '.join(missing)} "
                     f"(known: {', '.join(registry.VENUES)})")

    print(f"update_all: {len(items)} venue(s), "
          f"Apple Music {'FULL re-match' if full else 'incremental (resume)'}"
          + (", site REFRESH" if refresh else ""))
    ok = {v["key"]: False for v in items}
    t0 = datetime.datetime.now()
    for v in items:
        try:
            ok[v["key"]] = update_venue(v, full, refresh)
        except Exception as e:
            print(f"  !! {v['key']}: {e!r} — skipping venue", file=sys.stderr)
    dt = (datetime.datetime.now() - t0).total_seconds() / 60
    failed = [k for k, okk in ok.items() if not okk]
    print(f"\nDone in {dt:.1f} min — "
          f"{len(ok) - len(failed)}/{len(ok)} venues updated"
          + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
