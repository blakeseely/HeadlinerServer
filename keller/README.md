# Keller Auditorium (Portland, OR)

City-owned, Metro-operated Portland'5 house (~2,700 cap) — Broadway runs,
concerts, comedy, ballet, lectures. Feed: `data/shows.json` (metro
`Portland`, 71 rows).

## Source — the schedule only exists inside the Portland'5 calendar

- `kellerauditorium.portlandoregon.gov` = **DNS dead** (city moved to
  portland.gov); `kellerauditorium.org` = domain-squat spam. The real
  calendar is `https://www.portland5.com/events` (Drupal, fully
  server-rendered) covering all five Portland'5 theaters — the feed keeps
  only cards whose `teaser__venue-name` is "Keller Auditorium".
- `?page=N` paginates ~10 cards/page, ~12 pages (walked until a page adds
  no new event links).

## Per-performance rows (the feed's one run-exploding venue)

Broadway runs are ONE event page for a week+ of performances. Detail pages
carry an `event-performance-list` of `__date "Nov 27" + __time "Friday,
7:30 PM" + per-performance evue link` — build explodes each into a feed
row (year inferred from the run header, bumped for cross-year runs).
Single-date events bill from the header. `update_all.show_key` gained
`date::show_time` for event-page-keyed venues so runs don't collapse.

## Multi-season alias collisions (Clue pattern)

A repeated show (Nov run + Mar run) shares ONE Drupal alias: two teaser
cards with the same `/event/clue` href, one of which REDIRECTS to /events
while its detail is unpublished. The fetch dedupes cards by
(URL, teaser-body), refuses redirected detail bodies, and falls back to a
**card-only row** — run's first day, `needs_review` + note "performance
details page not published yet". Self-heals to real per-performance rows
the night the venue publishes the detail page.

## Classification — where the event_type enum does real work

- comedy: title+bio regex (stand-up/comedian/comediante/comedy
  X/roast/live podcast; Comedy Central rule intact),
- other: theater nouns (musical|broadway|ballet|dance|opera…) **only fire
  on runs (>=2 perfs) or on the TITLE** — concert bios say "musical
  genius" adjectivally and false-fired when body-scanned unconditionally;
  lecture words (physicist|scientist|science) anywhere,
- music: default.

Doors literal times normalize; venue-relative phrasing ("1 hour prior to
start") passes verbatim. Age "All ages welcome" → "All Ages", else
verbatim. Reschedule/cancel sentences written into bios → note +
needs_review/cancelled.

## Validation

`SOURCES["keller"]` = `parse_keller` + `pager` pagination (new validator
capability: open-ended page walk). Run events emit `date..date_end` and
the comparator indexes source events across every night of a range —
per-performance feed rows confirm against the run. Detail-page support
("With X (support)") is out of validator scope (`support_mode="none"`).
First clean run: 71/71 dates, 71/71 heads, 0 findings.
