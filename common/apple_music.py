"""Apple Music matching — shared confidence engine + record shaping.

Moved from independent/ (was itunes_lookup.py + the artist_obj block in
build.py). Venue-agnostic: venues with Apple Music matching load their
lookup cache and call artist_obj(); the confidence engine and the LINK_FLOOR
safety rule live here exactly once, for every venue.

Cache format (venue cache/lookup.json):
    { "<normalized artist name>": {link, matched, confidence, status} }
    status: exact | likely | maybe | no_exact | error
"""
import json, os, re, unicodedata
from difflib import SequenceMatcher

# Only auto-link a fuzzy (non-exact) match at this confidence. Below the
# floor the catalog entry is a similarly-named DIFFERENT act
# (e.g. "DJ Harry Duncan" -> "Henry Lowther, Harry Beckett, Peter Duncan"):
# unlink, but keep the near-miss name + score so a human can eyeball it.
LINK_FLOOR = 0.80


# --------------------------------------------------------------------------
# Normalization helpers
# --------------------------------------------------------------------------
def norm(s):
    s = re.sub(r"\s+", " ", s or "").strip().lower()
    s = s.replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    if s.startswith("@"):
        s = s[1:]
    return s


def norm_accentless(s):
    """norm() plus accent stripping, so 'Annie-Claude Deschênes' == 'deschennes'."""
    s = norm(s)
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def strip_paren(s):
    return re.sub(r"\([^()]*\)", " ", s)


def cache_key(name):
    """Cache key for a billed name: normalized + accentless."""
    return norm_accentless(name)


# --------------------------------------------------------------------------
# Confidence engine (moved verbatim from independent's itunes_lookup.py)
# --------------------------------------------------------------------------
TAIL_RE = re.compile(r"\s*(?:&|and)\s+[^&]+$")

def split_tail(name):
    """Billed 'X & the Band' -> lead 'x', tail 'the band'. No tail -> ('', '')."""
    s = norm(strip_paren(name))
    m = TAIL_RE.search(s)
    if m and m.start() > 0:
        return s[:m.start()].strip(), s[m.start():].strip()
    return s, ""


def lead_name(name):
    """The billed name with parentheticals and 'and/& his/the ...' tails removed."""
    lead, _ = split_tail(name)
    return strip_paren(name) if not lead else lead


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", strip_paren(s).lower()))


STOPWORDS = {"the", "a", "an", "and", "&"}
EXTRA_OK = {"live", "dj", "solo", "acoustic", "band"}
DESCRIPTIVE = {"band", "group", "crew", "rock", "soul", "jazz", "funk", "steady"}


def _is_descriptive(tail):
    """True when a '& tail' / 'and ...' tail is a band descriptor, not a
    second person's name — i.e. it's safe to search just the lead.
    'his band' / 'the steady rock band' -> True;  'paul' -> False."""
    t = tokens(tail)
    if not t:
        return False
    POSSESS = {"his", "her", "their"}
    if t & POSSESS and t & DESCRIPTIVE:
        return True
    return bool(t & DESCRIPTIVE)


def _search_variants(name):
    """Search terms to send to the API: the billed name, its lead (when the
    tail is a band descriptor), the lead minus a DJ prefix, and — when the
    name carries a parenthetical — the name with the parens stripped, since
    the API often returns nothing for 'Name (of Band)'.
    """
    vs = [name]
    lead, tail = split_tail(name)
    if lead and _is_descriptive(tail):
        vs.append(lead)
    bare = re.sub(r"^\s*(dj)\s+", "", norm(lead or name))
    if bare and bare != norm(lead or name):
        vs.append(bare)
    # "Chris Fleming Live" -> "Chris Fleming": a bare performance descriptor
    # at the end of a name is not part of the artist name.
    m = re.search(r"^(.*?)\s+(?:live|dj|solo|acoustic)$", norm(lead or name))
    if m and m.group(1):
        vs.append(m.group(1))
    if "(" in name:
        vs.append(re.sub(r"\s+", " ", strip_paren(name)).strip())
    seen, out = set(), []
    for v in vs:
        k = norm_accentless(v)
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _score_bases(name):
    """Name forms to score a candidate against.

    * A parenthetical is descriptive ('of Moon Hooch'), so the stripped core
      ('Michael Wilbur') is a valid comparison basis that can reach 1.0 when
      the catalog entry is the core.
    * A billed title's HEAD can be a scoring basis when it is a prefix of the
      whole bill ('Cameron Winter' in 'Cameron Winter at Carnegie Hall',
      'Nora Brown' in 'Nora Brown with Stephanie Coleman'): the catalog entry
      is the core act and the rest is a venue/companion descriptor.
    """
    bases = [name]
    if "(" in name:
        bases.append(re.sub(r"\s+", " ", strip_paren(name)).strip())
    head = _prefix_head(name)
    if head and head.lower() != name.lower():
        bases.append(head)
    seen, out = set(), []
    for v in bases:
        k = norm_accentless(v)
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _prefix_head(name):
    """The leading words of a billed name that are followed by a descriptor
    ('at <venue>', 'with <person>', 'x <person>', '+ <person>') — the core
    act. Returns None when the name carries no such trailing descriptor.
    ('Cameron Winter at Carnegie Hall' -> 'Cameron Winter'.)"""
    t = re.sub(r"\s+", " ", name).strip()
    m = re.search(r"\s+(?:at|with|x|\+)\s+", t, re.IGNORECASE)
    if m:
        head = t[:m.start()].strip(" .")
        if len(head.split()) >= 1 and len(head) >= 3:
            return head
    return None





def score_pair(query, cand):
    """Score one billed variant against one catalog candidate. Returns 0..1."""
    q = norm_accentless(query)
    c = norm_accentless(cand)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    # Single-token vs single-token, edit distance exactly 1 (one char
    # inserted/deleted/substituted: "Abhora" vs "Ahora"): two near-identical
    # words are almost always DIFFERENT acts — one letter off is the classic
    # auto-link trap. The raw SequenceMatcher ratio (0.909) would clear the
    # link floor; treat it as a non-match instead. Multi-token names are
    # unaffected (their legit "lead" partial matches keep scoring normally).
    qts, cts = tokens(q), tokens(c)
    if len(qts) == 1 and len(cts) == 1:
        t, u = next(iter(qts)), next(iter(cts))
        # Insertion/deletion (one is one char longer): near-identical words
        # one letter off ("Abhora" vs "Ahora") are different acts -> no match.
        if abs(len(t) - len(u)) == 1:
            return 0.0
        # Same length: a letter->letter substitution one position off is
        # likewise a different act; a letter<->DIGIT substitution is a
        # rendering variant of the SAME act ("Fifteenoeight" vs
        # "Fifteen0eight") — let that fall through to the normal rules.
        if len(t) == len(u):
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(t, u)) if x != y]
            if len(diff) == 1 and diff[0][1].isalpha() and diff[0][2].isalpha():
                return 0.0
    # A solo DJ is a one-act billing; a multi-person band entry sharing a
    # first name ("harry" in "Henry Lowther, Harry Beckett, Peter Duncan")
    # is a DIFFERENT act. Never link a "DJ X" bill to a band.
    if re.match(r"^dj\b", q):
        ct = tokens(c)
        if len(ct) > 1 and "dj" not in ct:
            return 0.0
    qlead, _ = split_tail(query)
    ql = norm_accentless(qlead)
    _is_bill = "and" in q or "&" in q
    # The lead being a substring of the catalog name is a strong signal ONLY
    # for non-bill names. For a bill the bare lead is a fragment, so skip it.
    if ql and ql != q and ql in c and not _is_bill:
        return 0.95
    qt = {t for t in tokens(query) if t not in STOPWORDS}
    ct = {t for t in tokens(cand) if t not in STOPWORDS}
    _c_bill = "and" in c or "&" in c
    if len(qt) == 1:
        t = list(qt)[0]
        if len(t) >= 5 and t in c.replace(" ", "") and not (_is_bill and not _c_bill):
            # The token must sit at the START of the candidate (word-boundary
            # aware) or exactly BE it: a mid-name substring is a different
            # act, not the same one ("Abhora" inside "8D Ahora" must not link,
            # while "Ahora Mazda" contains "Ahora" as a real prefix — that
            # pair is still flagged as a near-miss by the floor, and the
            # reviewer sees it).
            i = c.replace(" ", "").find(t)
            if i == 0 and (len(c.replace(" ", "")) == len(t)
                            or not c.replace(" ", "")[len(t)].isalnum()):
                return 0.95
    # A single-token catalog candidate can only be a confident match when the
    # billed name is itself one token (or it exactly equals the full lead).
    # Otherwise it is a fragment of a longer bill -> fall through (low score).
    if len(ct) == 1 and len(qt) > 1 and not (len(ct) == 1 and list(ct)[0] == ql):
        return round(SequenceMatcher(None, q, c).ratio(), 3)
    cflat = c.replace(" ", "")
    # A single-token lead that appears at the start of the catalog name.
    # For a bill (and/&) this rule is skipped: it's the source of "Ray and
    # Paul" -> "...Holmberg" false positives; the token-set rule below picks
    # the real bill instead.
    if ql and len(ql.split()) == 1 and ql in cflat and not _is_bill and not (_is_bill and not _c_bill):
        i = c.find(ql)
        if i == 0:
            nxt = c[len(ql)] if len(c) > len(ql) else ""
            if nxt == "" or not nxt.isalnum():
                _, qtail = split_tail(query)
                if qtail:
                    tset = tokens(qtail) - DESCRIPTIVE
                    if tset and not tset <= ct:
                        return round(SequenceMatcher(None, q, c).ratio(), 3)
                return 0.95
        # else: lead is a fragment of a longer name -> fall through
    if qt and ct:
        if qt == ct:
            if _is_bill and not _c_bill and len(ct) == 1:
                return round(SequenceMatcher(None, q, c).ratio(), 3)
            return 0.9
        if ct <= qt:
            extras = qt - ct
            if len(extras) == 1:
                return 0.8
            if len(extras) <= 2 and extras <= EXTRA_OK:
                return 0.75
        if qt <= ct and len(ct - qt) == 1:
            return 0.8
    # normalized lead equals the candidate (dropped stage-descriptor words)
    if ql and norm(qlead) == norm(cand):
        return 0.95
    if len(qt) >= 2 and len(ct) >= 2:
        small = min(len(qt), len(ct))
        inter2 = qt & ct
        if len(inter2) >= 2 and len(inter2) / max(1, small) >= 0.6:
            return 0.7
    return round(SequenceMatcher(None, q, c).ratio(), 3)


def confidence(query, cand):
    """Best score across all scoring-bases of the billed name vs the candidate."""
    q = norm_accentless(query)
    c = norm_accentless(cand)
    # A solo DJ is a one-act billing; a multi-person band entry sharing a
    # first name ("harry" in "Henry Lowther, Harry Beckett, Peter Duncan")
    # is a DIFFERENT act. Keyed on the original billed name so the DJ-stripped
    # variant ("harry duncan") can't slip past it.
    if re.match(r"^dj\b", q):
        ct = tokens(c)
        if len(ct) > 1 and "dj" not in ct:
            return 0.0
    return max(score_pair(b, cand) for b in _score_bases(query))


# --------------------------------------------------------------------------
# API lookup (driver helpers; main() in lookup.py uses these)
# --------------------------------------------------------------------------
def _split_compound(name):
    """'A and B' / 'A x B' -> ['A', 'B']. Empty when the name is a single
    (uncompounded) act. The parts are the search targets, never billed names."""
    s = norm(strip_paren(name))
    parts = re.split(r"\s+and\s+|\s*x\s+|\s*\+\s*", s)
    parts = [p.strip() for p in parts if len(p.strip()) >= 3]
    if len(parts) < 2:
        return []
    return parts


def _amc_search(term):
    """Catalog search via the user's `amc` Apple Music CLI — the PRIMARY path.

    `amc` drives the Apple Music app's own catalog API, which is not
    bot-walled (the web iTunes /search endpoint gets intermittently
    403-blocked by Apple's bot layer, and can 403 ALL terms at once). Returns
    the same result-shape as the web API — one record per hit with the fields
    url_of()/confidence() need — or None if amc is unavailable/errored.
    """
    import shutil, subprocess
    if not shutil.which("amc"):
        return None
    try:
        out = subprocess.run(
            ["amc", "catalog-search", term, "--type", "artist", "--limit", "15"],
            capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    try:
        doc = json.loads(out.stdout[out.stdout.find("{"):])
    except Exception:
        return None
    res = []
    for a in doc.get("artists", [])[:15]:
        aid = a.get("id")
        res.append({
            "artistName": a.get("name"),
            "artistId": aid,
            # id-only URL as the last resort (canonicalized below when the
            # lookup API responds)
            "artistLinkUrl": f"https://music.apple.com/us/artist/{aid}" if aid else None,
        })
    if not res:
        return res
    return _canonicalize_ids(res)


def _canonicalize_ids(res):
    """Upgrade amc-fallback hits (id-only URLs, no slug) to canonical
    music.apple.com/artist/<slug>/<id> links via the iTunes /lookup API,
    which is keyed by catalog id and NOT bot-walled like /search.

    Batches up to 20 ids per request. Any hit the lookup can't resolve
    keeps its id-only URL (still a working, unambiguous deep link).
    """
    import time, urllib.parse, urllib.request
    wanted = [r.get("artistId") for r in res if r.get("artistId")]
    if not wanted:
        return res
    by_id = {}
    for i in range(0, len(wanted), 20):
        chunk = ",".join(str(x) for x in wanted[i:i + 20])
        url = "https://itunes.apple.com/lookup?" + urllib.parse.urlencode({"id": chunk})
        data = None
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/125.0 Safari/537.36",
                    "Accept-Language": "en-US,en;q=0.9"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read().decode())
                break
            except Exception:
                if attempt == 1:
                    break
                time.sleep(1.0)
        if not data:
            continue
        for r0 in data.get("results", []):
            aid = r0.get("artistId")
            if aid and r0.get("artistName"):
                by_id[str(aid)] = r0
    for r in res:
        m = by_id.get(str(r.get("artistId")))
        if m:
            u = url_of(m)
            if u and u.count("/") >= 5:  # has the slug, not just the id
                r["artistName"] = m.get("artistName") or r.get("artistName")
                r["artistLinkUrl"] = u
    return res


def search(term):
    """Search the artist catalog. Returns a list of hits, or None when the
    search FAILED (both the amc catalog and the web API failed) — a search
    that succeeded but found nothing returns an empty list, so callers can
    tell "not in the catalog" (honest, terminal) from "retry later".

    Order: the `amc` Apple Music CLI first (the app's own catalog API — not
    bot-walled, so it won't hit the /search 403s). If amc is unavailable,
    or it searches successfully but comes up EMPTY, the web iTunes /search
    runs as the secondary source — an empty amc result must not be treated
    as authoritative "not in the catalog" when the web catalog disagrees
    (the app catalog has occasional blind spots; a web hit means the
    artist exists in Apple's ecosystem and is linkable).
    """
    main = _amc_search(term)
    if main:
        return main
    if main is not None:
        # amc searched fine but found nothing: cross-check the web; only a
        # web hit overrides the empty amc result.
        web = _web_search(term)
        if web:
            return web
        return main  # both agree: genuinely absent — honest, terminal
    return _web_search(term)


def _web_search(term):
    """The bot-walled web iTunes /search API (secondary source). Returns a
    list of hits (possibly empty), or None when the search failed after
    retries (403/bot wall/down) — an empty list means the web catalog
    genuinely found nothing for the term."""
    import time, urllib.parse, urllib.request
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "media": "music", "entity": "musicArtist", "limit": 15})
    data = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/125.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            break
        except Exception:
            if attempt == 2:
                break
            time.sleep(2.0)
    if data is None:
        return None
    return data.get("results", [])


def url_of(res):
    u = (res.get("artistLinkUrl") or res.get("artistViewUrl") or res.get("collectionViewUrl"))
    if u:
        u = re.sub(r"\?uo=\d+$", "", u)
    return u


def lookup(artist):
    """Look up one billed artist name, scoring every variant x candidate.

    Result: {link, matched, confidence, status}
      status exact    -- confidence 1.0
      status likely   -- confidence >= 0.80 (near miss: 'The X' vs 'X',
                          surname extension, lead of 'X & the Band')
      status maybe    -- confidence >= 0.70 (plausible but ambiguous)
      status no_exact -- best candidate below 0.70
      status error    -- network failure
    """
    results = []
    searched = 0
    for v in _search_variants(artist):
        r = search(v)
        if r is None:
            # A failed search (blocked/down) is treated as "no results for
            # this variant", not a hard error — the other variants may
            # still resolve the name (see the amc fallback in search()).
            continue
        searched += 1
        results.extend(r)
    if not results:
        # Compound bill: "A and B", "A x B" — no catalog artist matches the
        # whole string, but the parts resolve individually. Link the better
        # part, flag as compound for human review.
        for part in _split_compound(artist):
            for v in _search_variants(part):
                r = search(v)
                if r is None:
                    continue
                searched += 1
                results.extend(r)
            if results:
                break
    if not results:
        if searched:
            # The searches succeeded and the catalog genuinely has nothing
            # for this name: an honest "not found", not a failure. Marking
            # it error would make resume mode re-query Apple Music for it
            # on every single run.
            return {"link": None, "matched": None, "confidence": 0.0,
                    "status": "no_exact"}
        # Every search call failed (network/bot wall): keep the retry.
        return {"link": None, "matched": None, "confidence": 0.0,
                "status": "error"}

    best, bestc, bestres = 0.0, None, None
    seen = set()
    for res in results:
        an = res.get("artistName", "")
        if norm_accentless(an) in seen:
            continue
        seen.add(norm_accentless(an))
        sc = confidence(artist, an)
        if sc > best:
            best, bestc, bestres = sc, an, res

    link = url_of(bestres) if bestres else None
    # Compound-bill flag: the billed name is a multi-act bill ('A and B',
    # 'A x B') AND the catalog match is one act of it. A match spelled 'A
    # & B' for the bill 'A and B' is the WHOLE act (one artist) — not
    # compound — even though the tokens line up.
    compound = False
    parts = _split_compound(artist)
    if parts and bestc:
        q = norm_accentless(strip_paren(artist))
        c = norm_accentless(strip_paren(bestc))
        # Whole-act matches are NOT compound: 'A and B' matched to 'A & B'
        # (one act with an ampersand), or to a name carrying a band
        # descriptor ('Jack Kays and his Band' -> 'Jack Kays & his Band').
        whole_spelling = c.replace("-", " ") == q.replace("-", " ").replace(" and ", " & ")
        descriptor_tail = bool(re.search(
            r"(band|group|crew|ensemble|orchestra|choir|allstars|all stars)$", c))
        if c in q and c != q and "&" not in c and not whole_spelling \
                and not descriptor_tail:
            compound = True
    if best >= 1.0:
        status = "exact"
    elif best >= 0.80:
        status = "likely"
    elif best >= 0.70:
        status = "maybe"
    else:
        status = "no_exact"
    if link is None:
        # scored something but it had no URL: treat as not found, keep the name
        if best > 0:
            status = "no_exact"
    if status == "maybe" and link:
        status = "likely"  # a link exists: treat as found-but-flagged, not not-found
    return {"link": link, "matched": bestc, "confidence": best,
            "status": status, "compound": compound}


# --------------------------------------------------------------------------
# Record shaping + stats (shared by every venue build)
# --------------------------------------------------------------------------
def _tail(name):
    """Billed 'X & the Band' -> 'x' (lead, paren/tail stripped); '' if no tail."""
    s = re.sub(r"\([^()]*\)", " ", name)
    s = re.sub(r"\s+", " ", s).strip().lower().replace("\u2019", "'")
    m = re.search(r"\s*(?:&|and)\s+[^&]+$", s)
    if m and m.start() > 0:
        return s[:m.start()].strip()
    return s


ARTIST_KEYS = ("name", "apple_music", "spotify", "found", "confidence",
               "matched", "apple_label", "spotify_label", "match_label",
               "spotify_source")


def _artist_record(name, apple_link, spotify_link, found, conf, matched,
                   apple_label, spotify_label, spotify_source):
    """The UNIFORM artist record shape — every key always present (null where
    n/a), so clients never face two object shapes. `match_label` is kept as a
    combined convenience (legacy); the structured split is `apple_label` +
    `spotify_label` (one style each, no free-prose mixing).
    """
    parts = [x for x in (apple_label, spotify_label) if x]
    return {
        "name": name,
        "apple_music": apple_link,
        "spotify": spotify_link,
        "found": found,
        "confidence": conf,
        "matched": matched,
        "apple_label": apple_label,
        "spotify_label": spotify_label,
        "match_label": " | ".join(parts) if parts else None,
        "spotify_source": spotify_source,
    }


def relabel(a):
    """Recompute a record's combined `match_label` from its split labels.
    Called after a venue/lookup pass mutates `apple_label` / `spotify_label`."""
    if not isinstance(a, dict):
        return
    parts = [a.get("apple_label"), a.get("spotify_label")]
    a["match_label"] = " | ".join(p for p in parts if p) or None


def artist_obj(name, cache):
    """An artist as a structured record: name + Apple Music link + confidence.

    cache maps cache_key(name) -> {link, matched, confidence, status}:
      exact   -> found, confidence 1.0
      likely  -> found, close match (0.8-0.99); matched names the catalog artist
      maybe   -> found, plausible but ambiguous (0.7-0.79); needs_review
      no_exact-> not found (link None)
    Placeholder names (starting with '(') are never looked up.

    `found`/`apple_music`/`confidence`/`apple_label` track the Apple Music
    match only. The Spotify side (if a venue attaches one) fills `spotify` /
    `spotify_label` / `spotify_source`.
    """
    if name.startswith("("):  # placeholder like (Multiple Artists)
        return _artist_record(name, None, None, False, None, None,
                              None, None, None)
    r = cache.get(cache_key(name)) or {}
    link = r.get("link")
    found = bool(link)
    conf = r.get("confidence")
    matched = r.get("matched")
    label = None
    if found and conf is not None and conf < LINK_FLOOR:
        found = False
        link = None
        label = f"no confident match (closest: {matched} @ {round(conf*100)}%)"
    elif found and matched:
        m = re.sub(r"\s+", " ", matched).strip().lower()
        n = re.sub(r"\s+", " ", name).strip().lower()
        if m != n:
            # Compound flag: prefer the one stored by lookup(); recompute for
            # legacy cache entries that predate the field.
            if "compound" in r:
                compound = bool(r.get("compound"))
            else:
                parts = _split_compound(name)
                q = norm_accentless(strip_paren(name))
                cm = norm_accentless(strip_paren(matched))
                whole_spelling = cm.replace("-", " ") == q.replace("-", " ").replace(" and ", " & ")
                descriptor_tail = bool(re.search(
                    r"(band|group|crew|ensemble|orchestra|choir|allstars|all stars)$", cm))
                compound = bool(parts) and cm in q and cm != q and "&" not in cm \
                    and not whole_spelling and not descriptor_tail
            if compound:
                # billed 'A and B' matched to 'A': a link is right, but it
                # covers only part of the bill — flag for review.
                label = f"compound bill — links to {matched} only"
            else:
                ql = _tail(name).lower() or None
                if conf == 1.0 or m == (ql or "").lower():
                    label = None  # catalog entry is the billed lead name: clean
                elif isinstance(conf, (int, float)) and conf >= 0.95:
                    label = None  # high-confidence variant spelling; link verified
                else:
                    label = "close match: " + matched
    return _artist_record(name, link if found else None, None, found,
                          conf, matched if found else None,
                          label, None, None)


def plain_artist(name):
    """Artist record for venues WITHOUT Apple Music matching: plain name only
    (same uniform shape, all match fields null; confidence null = not attempted)."""
    return _artist_record(name, None, None, False, None, None,
                          None, None, None)


def load_lookup_cache(path):
    """Load a venue's cache/lookup.json keyed by cache_key(name)."""
    if not os.path.exists(path):
        return {}
    try:
        raw = json.load(open(path))
    except Exception:
        return {}
    return {cache_key(k): v for k, v in raw.items()}


def _occ_rank(a):
    """Rank an artist occurrence as a stats representative: most-linked first.
    (Spotify link > Apple link > confidence > attempted) so the representative
    of a repeated name is the occurrence that actually carries the links."""
    conf = a.get("confidence")
    return (
        bool(a.get("spotify")),
        bool(a.get("found")),
        conf if isinstance(conf, (int, float)) else -1.0,
        a.get("confidence") is not None,
    )


def apple_music_stats(shows):
    """Shared stats block over shows with Apple Music-matched artist records.

    Artists are deduped by the case-insensitive, accentless-normalized name
    (L4: 'Fred Armisen' x3 = 1 act). For each unique name the stats use ONE
    representative — the most-linked occurrence (the one a client would see
    resolve to). Buckets partition `found` exactly (clients may sum them):
      found == exact + close + flagged
        exact   — confidence 1.0 (clean link; the label code never fires at 1.0)
        close   — confidence < 1.0, no apple_label (verified variant spelling
                  >= 0.95 or a confident near-match)
        flagged — carries an `apple_label` (human should eyeball: 'close
                  match: X', 'compound bill — links to A only', …)
    `flagged` is match-quality only; it is independent of the show-level
    `needs_review` flag (bill-level, e.g. 3+ co-headliners) — different
    meaning, hence a different name (M5).
    """
    occ = {}
    for s in shows:
        for a in s.get("headline_artists", []) + s.get("support_artists", []):
            if isinstance(a, dict) and a.get("name"):
                k = norm(a["name"])
                if k not in occ or _occ_rank(a) > _occ_rank(occ[k]):
                    occ[k] = a
    st = {
        "unique_artists": len(occ),
        "found": 0, "exact": 0, "close": 0, "flagged": 0, "not_found": 0,
    }
    for a in occ.values():
        if a.get("found"):
            st["found"] += 1
            if a.get("apple_label"):
                st["flagged"] += 1
            elif a.get("confidence") == 1.0:
                st["exact"] += 1
            else:
                st["close"] += 1
        else:
            st["not_found"] += 1
    return st


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def date_label(iso):
    """'Fri 2026-10-16' style label for the reviewer; None without a date."""
    if not iso:
        return None
    import datetime
    return f"{WEEKDAYS[datetime.date.fromisoformat(iso).weekday()]} {iso}"


def shows_json(venue, venue_id, venue_url, source_url, shows, stats):
    """The shared top-level JSON document for every venue's data/shows.json."""
    import datetime
    return {"venue": venue, "venue_id": venue_id, "venue_url": venue_url,
            "source_url": source_url,
            "scraped_at": datetime.date.today().isoformat(),
            "count": len(shows), "shows": shows, "stats": stats}


def write_shows(path, doc):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
