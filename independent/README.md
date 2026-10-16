# The Independent SF — Show Extraction

Extracts all upcoming shows from the venue website into a JSON file and provides a
web page to review the extraction side-by-side against the live site.

## Files
- `data/shows.json`   — the extracted shows (source of truth)
- `viewer/index.html`  — the review/comparison UI
- `serve.py`           — local server that injects the JSON into the page

## Run the review page
```
python3 serve.py            # -> http://127.0.0.1:8050  (opens in browser)
python3 serve.py 9000       # custom port
```
The JSON is re-read on every request, so re-running the scraper and refreshing is enough.

## JSON schema
Top level: `venue`, `venue_url`, `source_url`, `scraped_at`, `count`, `shows[]`.
Each show:
- `headline_artists`  — array; the featured act(s). For a multi-act billing the first is the headliner.
- `support_artists`   — array; the opening/support acts (empty if none listed).
- `tour_or_presents`  — optional tour name / presenter line shown above the bill.
- `date`              — ISO `YYYY-MM-DD`.
- `doors`             — doors-open time as displayed, e.g. `"8:30 pm"`.
- `show_time`         — start time as displayed, e.g. `"9:00 pm"`.
- `ticket_link`       — the venue's ticket purchase link (Ticketweb).
- `event_page`        — the venue's own event page (for verification).

## Re-extract / re-scrape
The scraper visits the home-page UPCOMING SHOWS list, then each event detail page
(85 shows as of the initial run). To refresh, re-run the browser extraction that
produces `data/shows.json`. Year logic: shows captured in Oct 2026 with months
Oct–Dec → 2026; Jan–Sep → 2027 (i.e. the next calendar year, which are all in the past
from the capture date).
