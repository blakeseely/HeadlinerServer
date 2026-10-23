#!/usr/bin/env bash
# publish-data.sh — copy scraped JSON into the separate DATA repo and push it.
#
# Data-repo layout (what the iOS app downloads):
#   manifest.json            <- app fetches this first; lists venues + versions
#   <venue>/shows.json       <- one file per venue
#
# The data repo is a SHALLOW clone kept at data-repo/ (gitignored). Data
# refreshes are append-only (never history rewrites), so a shallow clone is
# safe and stays tiny. If the origin is unset or unreachable, the script
# exits cleanly with a "not configured" notice and the stale published copy
# stays valid — a data-publish hiccup must never break the main refresh.
#
# Needs HEADLINERS_DATA_ORIGIN in .env (the data-repo https URL).

set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

ROOT="$(pwd)"
DATA_DIR="$ROOT/data-repo"
ORIGIN="${HEADLINERS_DATA_ORIGIN:-}"

if [ -z "$ORIGIN" ]; then
  echo "SKIP: HEADLINERS_DATA_ORIGIN not set in .env — data publish not configured yet."
  exit 0
fi

# --- ensure the shallow clone exists ---
if [ ! -d "$DATA_DIR/.git" ]; then
  rm -rf "$DATA_DIR"
  git clone -q --depth 1 "file://$ORIGIN" "$DATA_DIR" 2>/dev/null || git clone -q --depth 1 "$ORIGIN" "$DATA_DIR"
fi
cd "$DATA_DIR"
git remote set-url origin "$ORIGIN"
git fetch -q origin
# data branch: prefer the remote default; fall back to main/master/HEAD
BRANCH="$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p' | head -1)"
if [ -z "$BRANCH" ]; then
  for b in main master; do
    if git ls-remote --exit-code --heads origin "$b" >/dev/null 2>&1; then
      BRANCH="$b"
      break
    fi
  done
fi
BRANCH="${BRANCH:-main}"
git checkout -q "$BRANCH" 2>/dev/null || git checkout -q -b "$BRANCH"
# fresh empty repo (no commits yet): there is nothing to sync
if git rev-parse --verify -q origin/"$BRANCH" >/dev/null 2>&1; then
  git reset -q --hard "origin/$BRANCH"
fi

# --- stage the venue JSON + manifest (stays here, no cd) ---
export ROOT
python3 - <<'PY'
import os, json, hashlib, datetime
root = os.environ["ROOT"]
data = os.path.join(root, "data-repo")
manifest = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "venues": []}
for venue in sorted(os.listdir(root)):
    if not os.path.isdir(os.path.join(root, venue)):
        continue
    src = os.path.join(root, venue, "data", "shows.json")
    if not os.path.isfile(src):
        continue
    dst_dir = os.path.join(data, venue)
    os.makedirs(dst_dir, exist_ok=True)
    raw = open(src).read()
    open(os.path.join(dst_dir, "shows.json"), "w").write(raw)
    shows = updated = city = metro = None
    domains = {"event_type": [], "ticket_status": []}
    sources = []
    try:
        doc = json.loads(raw)
        shows = doc.get("shows", [])
        # `updated_at` = when this venue's data was actually refreshed (the
        # scrape date); `oldest_show_date` = the oldest show on the schedule
        # (the pre-rename meaning of `updated_at`, kept for old clients).
        updated = doc.get("scraped_at")
        city = doc.get("city")
        metro = doc.get("metro")
        for s in shows:
            if s.get("event_type") and s["event_type"] not in domains["event_type"]:
                domains["event_type"].append(s["event_type"])
            if s.get("ticket_status") and s["ticket_status"] not in domains["ticket_status"]:
                domains["ticket_status"].append(s["ticket_status"])
            for ar in (s.get("headline_artists") or []) + (s.get("support_artists") or []):
                if isinstance(ar, dict) and ar.get("spotify_source") and \
                   ar["spotify_source"] not in sources:
                    sources.append(ar["spotify_source"])
        domains["spotify_source"] = sources
    except Exception:
        pass
    manifest["venues"].append({
        "venue_id": venue, "file": f"{venue}/shows.json",
        "city": city, "metro": metro,
        "updated_at": updated,
        "oldest_show_date": shows[0].get("date") if shows else None,
        "value_domains": domains,
        "show_count": len(shows or []),
        "sha256_16": hashlib.sha256(raw.encode()).hexdigest()[:16],
    })
with open(os.path.join(data, "manifest.json"), "w") as f:
    f.write(json.dumps(manifest, indent=2) + "\n")
print("staged", len(manifest["venues"]), "venues")
PY

# --- commit + push (only if something changed) ---
if git status --porcelain | grep -q .; then
  git add -A
  git -c user.name="headliners-bot" -c user.email="headliners-bot@localhost" \
    commit -q -m "Nightly data refresh (auto)"
  git push -q origin "$BRANCH"
  echo "PUBLISHED $(git rev-parse --short HEAD) -> $ORIGIN"
else
  echo "no data changes — published copy already current"
fi
