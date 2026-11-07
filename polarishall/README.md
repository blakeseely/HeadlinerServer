# Polaris Hall (Portland, OR)

 Mississippi Studios' little sister room (~300 cap), restored Masonic
 temple in St. Johns. Feed: `data/shows.json` (metro `Portland`, 56 rows).

## Source — one page, whole calendar, zero JS needed

`polarishall.com` is a custom-CMS one-pager (NOT WordPress). The entire
upcoming calendar (~58 cards, ~6-month horizon) server-renders inside
`#shows` as `events__grid-event > .event` blocks:

- `event__title` (billing) · `event__performers` (support) ·
  `event__time--doors/--show` · `event__action` (etix link, CTA text IS
  the status vocabulary: "Get Tickets" | "Sold Out")
- `event__date` carries **no year** ("Friday, Nov 6") — month-vs-today
  inference; the chronological walk asserts monotonic ordering and warns
  on drift; a stale yesterday card stays listed and drops in build.
- `event__presenter` is the constant "Polaris Hall Presents" — skipped.

## Build

Shared grammar (parse_bill dash tails; "An Evening With" bypass) plus the
wonderball colon-presenter rule ("Olivia O'Brien Presents: The PIXIE
Tour" caught it as a true positive on day one). Multi-night runs bill as
"(Night 1)/(Night 2)" suffixed rows (fillmore precedent). Real comedy
nights (teacher-standup nights, a comedy taping) — the tight
title comedy regex classifies them. "MOVED TO ALADDIN THEATER: …" written
into a title drops the row (wonderball precedent — it is no longer this
venue's show; Aladdin is not a tracked feed).

**age_rating is null by design**: the site carries no age data; limits
live only on etix product pages, which answer 202/empty to non-browser
clients.

## Validation

`SOURCES["polarishall"]` = `parse_polarishall` (independent parse of the
same page, explicit support). First run: 57/57 dates, 57/57 heads,
31/31 support, 0 findings.
