"""Spotify Web API — client-credentials artist lookup.

The counterpart to common/apple_music.py: a catalog SEARCH, not a scrape.
Used only for venues whose sites don't publish per-artist Spotify links;
a venue-published link ALWAYS wins over a searched one (the merge rule
lives in merge_lookup / each venue build).

Credentials: SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET from .env (gitignored)
at the repo root. With no keys, every public function returns a
graceful "not configured" result and the whole feature is a no-op — the
project still runs, links simply stay null.

Rate limits: the token is cached until ~60s before expiry; searches pace
at 0.15s between calls and retry 429/5xx with backoff (the token is
refreshed on 401).

Cache format (venue cache/spotify_lookup.json, driven by spotify_lookup.py):
    { "<display name>": {link, matched, confidence, status} }
    status: exact | likely | maybe | no_exact | error   (same ladder as Apple)
"""
import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import apple_music

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Only auto-link a fuzzy (non-exact) match at this confidence. Below the
# floor the artist is a similarly-named DIFFERENT act: unlink, keep the
# near-miss name + score so a human can eyeball it (same rule as Apple).
LINK_FLOOR = 0.80

_token_lock = threading.Lock()
_token = None          # current access token
_token_expires = 0.0   # epoch seconds
# Daily quota exhausted (429 with retry-after > 60min): stop issuing
# searches for the rest of this process so a --full run fails FAST instead
# of burning an hour of wall time (and rate-limit backoff sleeps) on 429s.
_quota_dead_until = 0.0


def load_credentials():
    """Read SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET from the repo .env."""
    vals = {}
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            m = re.match(r"^(SPOTIFY_CLIENT_ID|SPOTIFY_CLIENT_SECRET)=(.*)$", line.strip())
            if m:
                vals[m.group(1)] = m.group(2).strip()
    # the real environment wins if it carries the keys
    for k in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"):
        if os.environ.get(k):
            vals[k] = os.environ[k].strip()
    return vals.get("SPOTIFY_CLIENT_ID"), vals.get("SPOTIFY_CLIENT_SECRET")


def _get_token():
    """A valid client-credentials access token (hourly, cached). None when
    unconfigured or unobtainable."""
    global _token, _token_expires
    with _token_lock:
        if _token and time.time() < _token_expires - 60:
            return _token
        cid, csec = load_credentials()
        if not cid or not csec:
            return None
        auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
        req = urllib.request.Request(
            "https://accounts.spotify.com/api/token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + auth,
                     "Content-Type": "application/x-www-form-urlencoded"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    d = json.loads(r.read().decode())
                _token = d.get("access_token")
                _token_expires = time.time() + int(d.get("expires_in", 3600))
                return _token
            except Exception:
                time.sleep(2.0)
        return None


def search(term):
    """Search Spotify artists. Returns a list of {name, url} hits, or None
    when the search FAILED (retry later). An empty list means the catalog
    genuinely has nothing for this term — honest, terminal, not a failure.
    Returns [] (never None, never an error) when unconfigured: the feature
    is off and the venue simply has no API links.

    Note: the artist search endpoint caps `limit` at 5 (unlike iTunes' 15),
    so a miss on the full name is covered by lookup() searching the
    variants (lead name, DJ-stripped, paren-stripped) and the compound
    parts — each adding up to 5 more candidates to score."""
    global _quota_dead_until
    if time.time() < _quota_dead_until:
        return None  # daily quota known-dead: fail fast, let callers retry next run
    tok = _get_token()
    if not tok:
        return []
    url = "https://api.spotify.com/v1/search?" + urllib.parse.urlencode(
        {"q": term, "type": "artist", "limit": 5})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            return [{"name": a.get("name"),
                     "url": f"https://open.spotify.com/artist/{a['id']}"}
                    for a in d.get("artists", {}).get("items", []) if a.get("id")]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                ra = e.headers.get("Retry-After")
                if e.code == 429 and ra and int(ra) > 3600:
                    # daily quota exhausted (hour-scale retry): stop now —
                    # every further search will 429 until the reset
                    _quota_dead_until = time.time() + int(ra)
                    print(f"  ! spotify daily quota exhausted "
                          f"(retry-after {ra}s): stopping searches", flush=True)
                    return None
                time.sleep(2.0 * (attempt + 1))
                continue
            if e.code == 401:  # token died mid-run: refresh once, retry
                _get_token()
                continue
            break
        except Exception:
            time.sleep(1.5)
    return None


def lookup(artist):
    """Look up one billed artist name, scoring every variant x candidate
    with the SAME confidence engine as Apple Music (shared, one copy).

    Result: {link, matched, confidence, status}
      exact    -- confidence 1.0
      likely   -- confidence >= LINK_FLOOR (0.80)
      maybe    -- 0.70 <= confidence < 0.80 (plausible but ambiguous)
      no_exact -- best candidate below 0.70
      error    -- search failure (retried on the next run)
    Unconfigured (no keys): no_exact with a `configured: False` marker, so
    resume mode stops asking about the artist.
    """
    results = []
    searched = 0
    for v in apple_music._search_variants(artist):
        r = search(v)
        if r is None:
            continue  # failed search: other variants may still resolve it
        searched += 1
        results.extend(r)
    if not results:
        # Compound bill: "A and B" / "A x B" — try the parts.
        for part in apple_music._split_compound(artist):
            for v in apple_music._search_variants(part):
                r = search(v)
                if r is None:
                    continue
                searched += 1
                results.extend(r)
            if results:
                break
    if not results:
        unconfigured = not load_credentials()[0]
        if searched or unconfigured:
            res = {"link": None, "matched": None, "confidence": 0.0,
                   "status": "no_exact"}
            if unconfigured:
                res["configured"] = False
            return res
        return {"link": None, "matched": None, "confidence": 0.0,
                "status": "error"}

    best, bestc, bestres = 0.0, None, None
    seen = set()
    for res in results:
        an = res.get("name") or ""
        if apple_music.norm_accentless(an) in seen:
            continue
        seen.add(apple_music.norm_accentless(an))
        sc = apple_music.confidence(artist, an)
        if sc > best:
            best, bestc, bestres = sc, an, res

    link = bestres["url"] if bestres and bestres.get("url") else None
    if best >= 1.0:
        status = "exact"
    elif best >= LINK_FLOOR:
        status = "likely"
    elif best >= 0.70:
        status = "maybe"
    else:
        status = "no_exact"
    if link is None and best > 0:
        status = "no_exact"
    # A link exists: treat "maybe" as found-but-flagged for review, like Apple.
    if status == "maybe" and link:
        status = "likely"
    return {"link": link, "matched": bestc, "confidence": best,
            "status": status}


def merge_lookup(shows, cache):
    """Attach API-looked-up Spotify links onto artists that have none.

    cache: {cache_key(name): {link, matched, confidence, status}} as loaded
    by load_lookup_cache() (accentless-normalized keys). Rules:
      * an artist that ALREADY carries a venue-published link keeps it —
        the venue's own link always wins over a searched one;
      * links below LINK_FLOOR are not applied (honest null + label kept
        for the reviewer);
      * applied links are marked spotify_source="api" (scraped venue links
        stay source="venue"/unmarked) so the viewer can tell them apart.
    Returns the number of links applied.
    """
    applied = 0
    for s in shows:
        if not isinstance(s, dict):
            continue
        for a in (s.get("headline_artists") or []) + (s.get("support_artists") or []):
            if not isinstance(a, dict) or not a.get("name"):
                continue
            if a.get("spotify"):
                a["spotify_source"] = "venue"
                continue
            r = cache.get(apple_music.cache_key(a["name"]))
            if not r or not r.get("link"):
                continue
            if r.get("status") == "error":
                continue
            conf = r.get("confidence") or 0
            if conf < LINK_FLOOR:
                a["spotify"] = None
                if r.get("matched"):
                    a["match_label"] = (
                        (a.get("match_label") + "; " if a.get("match_label") else "")
                        + f"Spotify: no confident match (closest: {r['matched']} @ {round(conf*100)}%)")
                continue
            a["spotify"] = r["link"]
            a["spotify_source"] = "api"
            if a.get("match_label"):
                a["match_label"] = a["match_label"] + f"; Spotify: {r['matched']}"
            else:
                m = (r.get("matched") or "").strip()
                if m and m.lower() != a["name"].lower():
                    a["match_label"] = f"Spotify: close match ({m})" \
                        if conf < 0.95 else None
            applied += 1
    return applied
