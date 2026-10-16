#!/usr/bin/env python3
"""Apple Music lookup for every artist in data/shows.json.

For each unique (non-placeholder) artist name, queries the iTunes Search API
(entity=musicArtist) and scores the returned candidates:

  * exact     -- catalog artistName == billed name (case/accent/@/paren
                 normalized) -> confidence 1.0
  * likely    -- no exact, but the best candidate is a close variant
                 ("The Westones" vs "Westones", "Nick Cheo" vs "@NICKCHEO",
                 a '& the Band' tail, an '(of X)' qualifier, a surname
                 extension like "Ray and Paul" -> "Ray and Paul Holmberg").
                 Confidence is a 0..1 fuzzy score.
  * no_exact  -- nothing plausibly close -> link None (not found).

Results are checkpointed to the output JSON after every artist so a rerun
resumes where it left off.
"""
import json, time, urllib.request, urllib.parse, re, os, sys, unicodedata
from difflib import SequenceMatcher

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "shows.json")
OUT = os.path.join(ROOT, "cache", "itunes.json")


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
    """Name forms to score a candidate against. A parenthetical is descriptive
    ('of Moon Hooch'), so the stripped core ('Michael Wilbur') is a valid
    comparison basis that can reach 1.0 when the catalog entry is the core."""
    bases = [name]
    if "(" in name:
        bases.append(re.sub(r"\s+", " ", strip_paren(name)).strip())
    seen, out = set(), []
    for v in bases:
        k = norm_accentless(v)
        if k and k not in seen:
            seen.add(k)
            out.append(v)
    return out


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


def tokens(s):
    return set(re.findall(r"[a-z0-9]+", strip_paren(s).lower()))


STOPWORDS = {"the", "a", "an", "and", "&"}
EXTRA_OK = {"live", "dj", "solo", "acoustic", "band"}
DESCRIPTIVE = {"band", "group", "crew", "rock", "soul", "jazz", "funk", "steady"}


def score_pair(query, cand):
    """Score one billed variant against one catalog candidate. Returns 0..1."""
    q = norm_accentless(query)
    c = norm_accentless(cand)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
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


def search(term):
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "media": "music", "entity": "musicArtist", "limit": 15})
    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.loads(r.read().decode())
            break
        except Exception as e:
            if attempt == 2:
                return None
            time.sleep(2.0)
    return data.get("results", []) if data is not None else None


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
    for v in _search_variants(artist):
        r = search(v)
        if r is None:
            return {"link": None, "matched": None, "confidence": 0.0,
                    "status": "error"}
        results.extend(r)

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
    return {"link": link, "matched": bestc, "confidence": best, "status": status}


def main():
    force = "--full" in sys.argv
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

    done = lambda a: (a in out and out[a].get("status") in ("exact", "likely", "maybe", "no_exact"))
    todo = [a for a in real if (force or not done(a))]
    if force:
        out = {}  # full re-run: start the cache clean
    print(f"total {len(real)} real artists, {len(real)-len(todo)} cached, {len(todo)} to fetch", flush=True)

    import concurrent.futures
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(lookup, a): a for a in todo}
        for fut in concurrent.futures.as_completed(futs):
            results[futs[fut]] = fut.result()

    for i, a in enumerate(todo):
        out[a] = results[a]
        if (i + 1) % 10 == 0 or i + 1 == len(todo):
            json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)
    json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)

    from collections import Counter
    print("DONE:", dict(Counter(out[a]["status"] for a in real)))


if __name__ == "__main__":
    main()
