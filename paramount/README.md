# The Paramount Theatre (`paramount`) - Seattle

Source: The Paramount Theatre runs on STG Presents' ONE WordPress site (`stgpresents.org`, MEC
plugin) — three feeds (paramount/moore/neptune) from one shared parser,
`common/stg.py`, filtered by the card's `location.name`. MEC category filter
21=Paramount, 18=Moore, 19=Neptune server-side.

Fetch: `POST /wp-admin/admin-ajax.php action=mec_list_load_more` (no nonce).
PROTOCOL (probed from live 2026-11-07, changes here need the same care):
 - rows are always filtered to >= max(start_date, TODAY);
 - `mec_offset` pages ONLY when start_date >= today — a past start forces
   offset 0 and re-serves page 1 forever (count>0, has_more_event=1);
 - past the last page MEC CLAMPS (identical tail repeats forever);
 - walk = DATE CURSOR: month anchor (today for the first month), start jumps
   to each page's `end_date`, offset only within a day busier than a page,
   stop on a repeated page.

Data notes:
 - JSON-LD `startDate` carries a timezone-CORRUPT clock — trust its DATE
   half only; the true curtain comes from `<span class="mec-start-time">`.
 - Theater/comedy titles must NOT run through parse_bill (comma/"and" grammar
   would split show names like "Oh, Mary!"); only `event_type=="music"` bills.
 - STG writes cancellations into titles ("X - CANCELED") - the marker is
   stripped and mapped to ticket_status, never billed as part of the name.
 - The recurring "Free Paramount Tour" programming is intentionally NOT a show
   (validator excludes it too).

Maintenance: `cd paramount && python3 fetch.py && python3 build.py` (lookup via
`python3 ../common/lookup.py --venue paramount`). Validate with the
headlinerlistings-audit skill (`--only paramount --live DIR --refresh`).
