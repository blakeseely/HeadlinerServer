# Cafe du Nord

Source: **cafedunord.com** — a WordPress site. Its `/shows` listing is **fully
server-rendered** (one plain GET, browser user-agent, no Cloudflare, no JS
app): every upcoming show across **both rooms** appears as a clean
`<li class="show-row">` card. There are two rooms — the eponymous **Cafe du
Nord** (downstairs, the main room) and **Swedish American Hall** (upstairs).
The venue bills **live music only** (indie / rock / alt / hip-hop / R&B /
country tours), so every show is `music` and every act is matched to Apple
Music.

## The listing is the backbone

Each `show-row` card carries the whole bill as structured fields (no title
grammar to parse — far cleaner than August Hall's single string):

| field | source | example |
|---|---|---|
| date | `data-date` (ISO) | 2026-11-06 |
| room | `data-room` = `cdn` / `sah` | cdn |
| ticket status | `data-status` = `on-sale` / `waitlist` | on sale |
| age | `data-age` = `all-ages` / `21+` | All ages |
| presenter | `<p class="show-row__presenter">` | Live Nation presents |
| headliner | `<h3 class="show-row__headliner">` | IAN SWEET |
| support | `<span class="act">…</span>` (one per act) | with Luella |
| doors / show time | `<span class="show-times__doors\|__show"><time>` | 7 PM / 8 PM |
| tickets | `<a class="btn … show-row__btn">` href → TicketWeb | on sale |

One GET = the whole schedule (not paginated, so no pagination to follow).
Detail pages (`/shows/<slug>/`) each carry a full schema.org
`MusicEvent` JSON-LD (performer, ISO `doorTime`/`startDate`, `description`,
`offers`). We fetch those for the **one thing the listing lacks — the show
description** — with a small thread pool, cached incrementally by URL so a
reschedule/refresh only re-fetches new slugs. (Nothing else comes from the
detail page; the listing is authoritative.)

## Bill handling

`build.py` is mostly a 1:1 map. The one field with a real rule is **support**:

- The venue lists support as a **comma-separated** run of acts, and each act
  name may itself contain `&` or "and" — `Jesse Sykes & The Sweet Hereafter
  (duo)` is *one* band, `Conspiracy of Beards, Daniel Kahn and Jake
  Shulman-Ment` is *two* acts. So support splits on **comma only**, never on
  `&`/`and` (which live *inside* a single act name).
- A trailing **set-format parenthetical** — `Rex DeTiger (DJ Set)`,
  `(duo)` — is a note, not part of the act name, and is stripped before the
  Apple Music lookup.

The **headliner is always one act** (a band, the compound name `Dave Hause &
The Mermaid`, or a billed event like `San Francisco Leonard Cohen
Festival`). We never split it — the Apple Music engine decides whether a
compound/odd name resolves and flags the honest cases for review.

## Rooms

The two rooms are the only multi-room venue in the app, so the build surfaces
the **upstairs** room (`Swedish American Hall (upstairs)`) via the shared
`room` field. Downstairs (the eponymous room) is left unlabeled to keep the
common case uncluttered. This makes a same-date double header unambiguous —
e.g. Fri Nov 6 has the Cohen Festival *upstairs* and IAN SWEET *downstairs*.
The reviewer shows the room as a chip in the list and a row in the detail
pane.

## Apple Music

69/71 unique artists found (66 exact, 1 close, 2 flagged). The two not-founds
are honest: **Rex DeTiger** (Apple's catalog returns nothing for it) and the
**San Francisco Leonard Cohen Festival** (a billed event, not a catalog
artist — the engine searches it, finds nothing, and leaves it unlinked). The
flagged matches are reasonable (e.g. `Salem Ilise` → Apple's `salem ilese`;
`Dave Hause & The Mermaid` → `Dave Hause`, noted as linking the frontman
only).
