# Brick & Mortar Music Hall (SF)

Source: **brickandmortarmusic.com** — the official site of **Brick & Mortar
Music Hall** (1710 Mission St, the Mission; a ~250-cap pocket venue). It is a
**TicketWeb WordPress** site — the same platform family as August Hall
(`/tm-event/` detail URLs, `ticketweb.com/…?REFID=clientsitewp` ticket links)
— so plain GETs work with curl; there is **no JSON-LD Event node** (the `ld+json`
is only Yoast's WebPage/Website graph), so the HTML `tw-*` classes are the
backbone.

## The listing is the backbone (and is NOT paginated)

`/shows` is fully server-rendered. **The "Next" is fake** — `/shows/page/2/`
and `/page/3/` return the *identical* 21 shows (a thickbox-style link, not real
pagination; the only real `page/` links are the site's homepage). So one GET =
the whole schedule. The fetch still pages up to 6 and **dedupes by URL**,
stopping on the first non-growing page, which is safe either way.

Each show card (`<div class="tw-image">` … `<div class="tw-event-name-container">`
… button container) carries:

| field | source |
|---|---|
| billed title | `<div class="tw-name"><a>…` (the full bill: `Tōth + Sean Nicholas Savage`) |
| doors / show | `<span class="tw-event-door-time">` / `tw-event-time` (uppercase `7:00PM`) |
| age | `<div class="tw-age-restriction">` (mostly "All Ages") |
| date | a compact **`MM.DD`** span — **year-less**, so the detail page is needed |
| ticket status | the buy-button class: `tw_ticketssold` = on sale, `tw_soldout` = sold out |
| detail URL | `<a href="/tm-event/…">` |

Detail pages (`/tm-event/…/`) add the two things the listing truly lacks,
fetched incrementally (thread pool):
- **full date** — the `<span class="tw-event-date">` block (e.g. `October 20, 2026`);
- **description** — the first real content `<p>` (the per-artist bio). The
  cookie-consent / Instagram / CSS-JS paragraphs are filtered out by a keyword
  guard + a length floor (no dedicated class to anchor on).

## Bill handling

Brick & Mortar is a small venue, so the title grammar is where the work is.
`split_title` (in `build.py`) handles the shapes actually seen:
- **`+` = a multi-headline bill** — `REZN + lowheaven + Mountaineer` keeps all
  three as headliners (`multi_artist=True`).
- **`Name — Tour` / `Name - Tour` / `Name: Tour`** → the tail is the tour,
  **but only when it reads as a tour** (`_looks_like_tour`: a short tail
  containing tour-ish words). This keeps `Yana — The Feelings Are Forever Tour`
  clean while never mis-splitting an act whose name happens to contain a dash.
  Support is split off *first*, so `MISSIO: Love & Heartbreak Tour w/ X, Y`
  yields headliner `MISSIO` + tour `Love & Heartbreak Tour` + support.
- **`w/` / `with` / trailing comma** = support, split into acts on commas and
  `&`/`and` (act names may contain an internal `&`, which splits into its own
  act — the usual intent).
- Single room → `room` stays null. `event_type` = `music` (all bills).

## Apple Music

A small-venue calendar skews to **niche / unsigned / regional acts**, so this
is the venue most likely to have artists with no Apple Music catalog entry —
higher honest not-found rates are expected and fine (no chasing 100%, no
hand-coded special cases). Current run: **39/40** unique artists found (37
exact, 2 flagged for review); the one honest not-found is a compound/unsigned
act (e.g. `Hot Goth GF`).
