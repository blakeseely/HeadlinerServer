#!/usr/bin/env bash
# publish-data.sh — stage + publish scraped JSON to the separate data repo.
#
# Layout inside the data repo:
#   manifest.json            <- what the iOS app fetches first (venue index)
#   <venue>/shows.json       <- one file per venue, app downloads on launch
#
# The data repo is a shallow clone kept at data-repo/. Its only remote is
# the data repo, NEVER HeadlinerServer.
#
# Usage: ./publish-data.sh
#   - clones data-repo origin if missing (shallow)
#   - copies every <venue>/data/shows.json into data-repo/<venue>/shows.json
#   - regenerates manifest.json (venue, url, updated_at, sha256, show count)
#   - commits + pushes (git push is authenticated; if auth fails the script
#     fails loudly and the stale published copy remains valid)

set -euo pipefail
cd "$(dirname "$0")"

# load config (data repo URL) from .env if present
[ -f .env ] && set -a && . ./.env && set +a

ROOT="$(pwd)"
DATA_DIR="$ROOT/data-repo"
ORIGIN_URL="${HEADLINERS_DATA_ORIGIN:?set HEADLINERS_DATA_ORIGIN in .env to the data repo URL (e.g. https://github.com/blakeseely/headliners-data.git)}"

if [ ! -d "$DATA_DIR/.git" ]; then
  if [ -e "$DATA_DIR" ]; then rm -rf "$DATA_DIR"; fi
  git init -q "$DATA_DIR"
fi
cd "$DATA_DIR"
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$ORIGIN_URL"

if [ ! -f .git/HEAD ]; then
  git init -q
fi

# fetch remote tip (if a remote exists and is reachable); else work on empty
git fetch -q origin main 2>/dev/null || true
git checkout -q main 2>/dev/null || git checkout -q -b main 2>/dev/null || git checkout --orphan main
git reset -q --hard origin/main 2>/dev/null || git reset -q --hard 2>/dev/null || true

VENUES=$(python3 - <<'PY'
import os, json, hashlib, datetime
root = os.environ["ROOT"]
lines = []
manifest = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "venues": []}
for venue in sorted(os.listdir(root)):
    src = os.path.join(root, venue, "data", "shows.json")
    if not (os.path.isdir(venue) and os.path.isfile(src)):
        continue
    dst_dir = os.path.join(root, "data-repo", venue)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, "shows.json")
    with open(src) as f:
        raw = f.read()
    with open(dst, "w") as f:
        f.write(raw)
    try:
        doc = json.loads(raw)
        shows = doc.get("shows", [])
        updated = (shows[0].get("date") if shows else None) or doc.get("generated_at") or doc.get("scraped_at")
    except Exception:
        shows, updated = [], None
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    manifest["venues"].append({
        "venue": venue,
        "file": f"{venue}/shows.json",
        "updated_at": updated,
        "show_count": len(shows),
        "sha256_16": digest,
    })
    lines.append(venue)
with open(os.path.join(root, "data-repo", "manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
print(" ".join(lines))
PY
)

echo "staged venues: $VENUES"

if git -C "$DATA_DIR" status --porcelain | grep -q .; then
  git -C "$DATA_DIR" add -A
  git -C "$DATA_DIR" -c user.name="headliners-bot" -c user.email="headliners-bot@localhost" \
    commit -q -m "Nightly data refresh (auto)"
  git -C "$DATA_DIR" push -u origin main 2>&1 | tail -2
  echo "published: $(git -C "$DATA_DIR" rev-parse --short HEAD)"
else
  echo "no changes — published data is current"
fi
