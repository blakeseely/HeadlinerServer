# The Crocodile (`crocodile`) - Seattle

The venue's own Squarespace calendar is DEAD (placeholder "Event Five",
`upcoming: []`) - the live primary-ticket source is TicketWeb venue page
10352 (`common/ticketweb.py`).

Gotchas:
 - TicketWeb edge bot-walls bare curl (502) AND headless browsers from a
   flagged IP (403), but passes curl WITH the full browser header set - no
   JS needed;
 - the LD+JSON window carries ~10 upcoming events; the longer list is a
   lazily-loaded Angular XHR whose endpoint could not be pinned - so the
   feed horizon is legitimately short (validator treats beyond-horizon rows
   as info, not findings);
 - LD entries often omit `eventStatus` entirely -> default "on sale"
   (sold-out still flagged);
 - venue moved: the Crocodile now plays at 2505 1st Ave, Belltown (its own
   TicketWeb LD address confirms it - registry lat/lon pinned there).

Comma bills ("A, B, C") are flat co-bills by design (no "with" separator =
every act co-headlines per parse_bill grammar).

Maintenance: `cd crocodile && python3 fetch.py && python3 build.py`; validate
with the headlinerlistings-audit skill.
