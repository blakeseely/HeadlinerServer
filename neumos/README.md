# Neumos (`neumos`) - Seattle

Source: neumos.com (same AEG/AXS Carbonhouse platform, flavor-B cards:
`<div class="eventItem entry ... clearfix">` + `onsalenow` buttons).
`common/aeg.py` walks `/events/events_ajax/<offset>`; Neumos pages 12 cards
per window - the step MUST equal the first-page card count (a fixed step of
20 shipped half the calendar; caught by the cleanroom validator 2026-11-07).

Gotchas:
 - neumos.com 406s a full Chrome UA (TLS-fingerprint mismatch) - send plain
   curl defaults (inverse of the BGC lesson);
 - detail pages are DOORS-ONLY (keller precedent): `show_time` honestly null;
 - detail links are ABSOLUTE hrefs here (`https://www.neumos.com/events/...`).

Maintenance: `cd neumos && python3 fetch.py && python3 build.py`; validate
with the headlinerlistings-audit skill.
