# The Showbox (`showbox`) - Seattle

Source: showboxpresents.com (AEG Carbonhouse/AXS). One calendar serves the
whole "Showbox Presents" family (Showbox, Showbox SoDo, Crystal Ballroom,
wonderball, Moda, ...) - THIS feed keeps cards whose `.venue` label is
"The Showbox"; the sibling feed `showboxsodo` keeps "Showbox SoDo".

Fetch: `common/aeg.py` walks `GET /events/events_ajax/<offset>` after the
SSR `/events/` page. Gotchas:
 - bodies are JSON-ENCODED HTML strings - `json.loads` first (raw grep finds
   nothing and looks like the calendar ended);
 - the ajax window equals the first-page card count (20 here) - a step that
   mismatches the window silently truncates (Neumos ships 12/page);
 - past the last page the server re-serves the same tail - stop on a
   repeated page;
 - button vocabulary: codes 1/2/6 (Buy/Cancelled/Get Tickets) + flavor-B
   `onsalenow` class + `data-canceled`/`data-nonbuy` attrs.

Showbox detail pages carry doors ("Doors" text) - show_time from there when
present. Maintenance: `cd showbox && python3 fetch.py && python3 build.py`;
validate with the headlinerlistings-audit skill.
