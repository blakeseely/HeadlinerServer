"""Shared parser for the TicketWeb *title grammar* (the bellyup.com
multi-venue calendar — reusable for any site that bills shows the TicketWeb
way).

Grammar, applied in order:

    <presenters> Present  <HEADS>  [-]  <tail>   w/ <support>

  1. PRESENTERS — 'X Presents' / 'X and Y Present' prefix.
  2. TAIL — the FIRST dash / colon whose right side reads as a tour/album/
     show title (a short ≤ 6-word run, or a tour-ish word run). Everything
     to its right is kept RAW (nested ':' / '-' stay in the title, e.g.
     'ACT TWO: THE TOUR'), so a single split avoids re-assembly order bugs.
  3. SUPPORT — a 'w/' / 'with' / 'featuring' clause, split in the head AND
     in the tail (both regions may carry one). Support parts split on COMMA
     only — act names contain '&' / 'and' inside them.
  4. Re-step 2 on the support-stripped head (catches 'Name - Album w/ X').
  5. HEADS — '+' / ' x ' = co-headline bill; ', ' = further billed name.
     '&' / 'and' inside a name are part of the name, never a separator.

Co-bills on this feed use '+' / ' x ' / comma — a dash is a tour separator,
so treating a dash tail as the title is safe here.
"""
import re

TOUR_WORDS = {
    "tour", "tours", "world", "album", "albums", "anniversary", "farewell",
    "celebrating", "celebration", "celebrates", "celebrate", "revue",
    "specials", "show", "night", "nights", "evening", "sessions", "session",
    "run", "legs", "leg", "road", "touring", "live", "2day", "two-day",
    "days", "final", "last", "only", "big", "cozy", "fall", "winter",
    "summer", "spring", "stadium", "arenas", "in", "at", "to", "from",
    "for", "with", "feat", "featuring", "ft", "x", "by", "of", "the", "a",
    "an", "and", "de", "la", "el", "y", "y2k", "north", "america",
    "europe", "canada", "usa", "west", "coast", "side", "rock", "roll",
    "christmas", "halloween",
}

_SEPARATORS = re.compile(r"[-—:]")
_SUPPORT_RE = re.compile(
    r"\s+(?:w/|with\s+special\s+guests?\b|with|featuring|feat\.?\b)(?=[\s(]|$)",
    re.I)
_SPECIAL_GUEST_RE = re.compile(r"^(?:special\s+guests?|guest)\s+", re.I)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def presenters_of(title):
    """'X Presents Y' / 'X and Y Present Z' -> ([names], rest)."""
    m = re.match(r"^(.*?)\s+(?:presents?|present(?:ing|ed)?)\s+(.+)$",
                 title, re.I)
    if m and 2 <= len(_clean(m.group(1))) <= 40:
        who = m.group(1).strip()
        parts = [p.strip() for p in re.split(r"\band\b|\,", who, flags=re.I)
                 if p.strip()]
        return parts, m.group(2).strip()
    return None, title


def _tourish(t):
    toks = [x.strip(".,'\"()!?:-/") for w in t.lower().split()
            for x in re.split(r"[-/]", w)]
    toks = [x for x in toks if x]
    if not toks:
        return False
    if any(re.match(r"^\d", w) for w in toks):
        return True
    hits = sum(1 for w in toks if w in TOUR_WORDS)
    return hits >= max(1, len(toks) // 3)


def is_tour_tail(tail):
    """Does a dash/colon right-side read as a tour/album/show title? A short
    run (≤ 6 words) is a title; otherwise it must hit tour-ish words."""
    t = _clean(tail)
    if not t:
        return False
    if _tourish(t):
        return True
    return len(t.split()) <= 6


def split_once(part):
    """Split at the FIRST dash/colon when the right side is a tour tail.
    Returns (left, tail) or (part, None)."""
    m = _SEPARATORS.search(part)
    if not m:
        return part, None
    left, tail = _clean(part[:m.start()]), _clean(part[m.end():])
    if left and is_tour_tail(tail):
        return left, tail
    return part, None


def split_support(part):
    """The FIRST 'w/' / 'with' / 'featuring' clause off (head attaches to it).
    'with' at a dead tail ('An Evening with') is NOT support (nothing follows
    a real name), so a clause whose remainder is empty is ignored."""
    for m in _SUPPORT_RE.finditer(part):
        head = _clean(part[:m.start()])
        sup = _clean(part[m.end():])
        if not head:
            continue
        if sup:
            return head, sup
    return _clean(part), None


def _split_heads(part):
    """Co-headline separators: '+' / ' x ' = co-heads; ', ' = further billed
    names. '&' / 'and' inside a name never split. Commas NOT followed by a
    space (10,000) are thousands separators, not separators."""
    part = re.sub(r"\s*\+\s*", " x ", part)
    parts = [p.strip(" -–—") for p in re.split(r"\s+x\s+", part, flags=re.I)]
    out = []
    for p in parts:
        p = _clean(p)
        if not p:
            continue
        if ", " in p:
            pieces = [s.strip(" -–—") for s in p.split(", ") if s.strip()]
            out.extend(pieces or [p])
        else:
            out.append(p)
    return out


def _clean_support(part):
    """Support clause -> [names]: split on comma, drop 'special guest'."""
    names = []
    for s in part.split(","):
        s = _clean(_SPECIAL_GUEST_RE.sub("", s.strip(" -–—")))
        if s:
            names.append(s)
    return names


def parse_bill(title):
    """Parse a TicketWeb billed title -> dict(heads, support, presenters,
    tour, needs_review, raw)."""
    raw = _clean(title)
    presenters, body = presenters_of(raw)

    head, tour = split_once(body)
    head, sup_h = split_support(head)
    sup_t = None
    if tour:
        tour, sup_t = split_support(tour)

    # a short title tail that only becomes visible once support is stripped
    head2, tour2 = split_once(head)
    if tour2:
        head = head2
        tour = f"{tour2}: {tour}" if tour else tour2

    heads = _split_heads(head)
    sup = sup_t or sup_h
    supports = _clean_support(sup) if sup else []

    review = False
    if not heads:
        heads = [raw]
        tour = None
        review = True
    if len(heads) >= 3:
        review = True

    return {
        "heads": heads,
        "support": supports,
        "presenters": presenters or [],
        "tour": tour,
        "needs_review": review,
        "raw": raw,
    }
