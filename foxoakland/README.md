# Fox Theater (Oakland)

Source: **thefoxoakland.com** — run by **Another Planet Entertainment**
(TicketWeb/WordPress shop, like August Hall). It is **not** an AEG/AXS property
(those were the Regency/Warfield), and the venue's `/listing/` page is **fully
server-rendered**: one plain GET (browser user-agent, no Cloudflare, no JS app)
returns **every upcoming show** as a `<div class="mix detail-information">`
card — **not paginated** (32 cards ≈ the whole current calendar; past shows fall
off). It bills **live music AND comedy** (Ali Siddiq, Fortune Feimster, ALOK, …)
in a single room.

## The listing is the backbone

Each card carries the whole bill as separate fields (no title grammar):

| field | source |
|---|---|
| date | `<div class="single-date-show" itemprop="startDate" content="October 18, 2026 7:30 pm">` |
| tour | `<div class="topline">…</div>` (may stack a banner line: "Two Nights!" / "An Evening With" + the tour name) |
| headliner | `<h2 class="show-title">…</h2>` |
| support | `<div class="support">Act<br>Act</div>` (`<br>`-separated; absent for solo shows) |
| doors / show | `<span class="event__doors-open">` + `<span class="event__start-time">` |
| tickets | `<a class="button[ ghost][ soldout]">` (class encodes sold out) |
| page | `<a href="/events/<slug>">` |

Detail pages (`/events/<slug>/`) add the two things the listing lacks, fetched
**incrementally by event_page** (thread pool, cached in `cache/details.json` so
a refresh only re-fetches new slugs):

- **age** — the `<div class="more-information">` block is a *fixed 4-paragraph*
  set (Telegraph Room / The Den / doors note are **constant venue boilerplate**);
  the only variable paragraph is the age line ("This event is **all ages**." /
  "**18 and over**" / "recommended **16 and over**."). We extract just that.
- **description** — the `<div class="bio">` block is a real per-artist bio
  (a couple of shows append a venue-move notice instead, which we keep as `note`).

## Bill + type handling

- **Support** splits on the venue's **own line breaks** (`<br>` → newline) and
  commas — one act per line as billed. Unlike Cafe du Nord, these lines are plain
  (no `&`/`and` inside an act name), so we do NOT split on `&`/`and`. The
  Shpongle visual-credit line ("ft. Visuals by … & … floral art by …") is a
  production credit, not a musical act, so it stays one honest entry that the
  Apple Music engine can't resolve — by design, not a bug.
- **Headliner** is always one billed act. Some shows bill the tour *tacked onto
  the name* ("Ali Siddiq: The Custom Fit Tour"); we strip the `: <tour>` tail so
  the real artist resolves and the tail becomes the tour.
- **event_type** (music | comedy) — the venue has **no genre taxonomy**, so we
  derive it from its own copy: the bio/topline/title calling a show a
  comedy/stand-up/comedy special. Kept tight (no bare "laugh" — that hit a
  musician's bio and mis-flagged Thundercat as comedy). This is the honest,
  low-effort path; a handful of mislabels is the kind of thing the reviewer's
  "flag anything mislabeled" note is for, not something to hand-code around.
- **Single room** → `room` stays null.

## Apple Music

36/37 unique artists found (36 exact, 1 not-found). The one not-found is the
Shpongle visual-credit line above — a production credit, not a catalog artist,
so leaving it unlinked is the correct outcome.
