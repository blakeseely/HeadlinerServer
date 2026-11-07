# Wonder Ballroom (Portland, OR)

Music room (~800 cap) on NE Broadway; owned with Roseland Theater by Music
Venue Properties. Feed: `data/shows.json` (metro `Portland`).

## Source

`https://wonderballroom.com/events/` — WordPress + the group's own
**rhp-events** plugin. No bot wall; the TEC REST API 404s (they don't run
TEC). The page is fully server-rendered: every upcoming show in ONE GET,
and every field lives on the card — head (h2), support (h4 `evSubHead`),
promoter (`eventTagLine`), doors/show line, age, cost, CTA status class,
etix link, full `Fri, Nov 06, 2026` date. `fetch.py` therefore needs no
detail crawl; it dedupes the mobile-view card repeat by event URL.

## Venue quirks encoded in build.py

- **Status prefixes are written INTO the bill title**: `*CANCELLED* The
  Residents`, `*Postponed* SiM` (kept, `needs_review`, note keeps the
  venue's wording — the date shown is the ORIGINAL one), and
  `**MOVED TO ROSELAND THEATER** FROST CHILDREN` (dropped — the show
  belongs to the Roseland feed).
- **Promoter glued into titles with a colon** ("NSQK PRESENTS: MOSCA") —
  split off before parse_bill, else the promoter becomes the headliner.
- The venue separates head from tour with an **en dash** (" – ") — mapped
  to the em dash the shared grammar understands.
- CTA classes `on-sale | sold-out | off-sale` map to vocabulary; any NEW
  class passes through verbatim (status fallthrough lesson).
- Two age-div flavors (`eventAgeRestriction …` and
  `rhp-event__age-restriction--list …`); the `cust_age` SPAN is a comma
  decoy — anchor the regex on `<div class="eventAgeRestriction`.

## Validation

Audit skill `SOURCES["wonderball"]` = same page via `parse_rhp`
(support_mode `explicit`). `parse_rhp` is written to be reusable for
Roseland Theater (same plugin).
