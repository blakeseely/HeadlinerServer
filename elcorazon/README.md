# El Corazon (`elcorazon`) - Seattle

Source: elcorazonseattle.com `/calendar` (Webflow CMS, fully SSR).
One site serves BOTH this feed and `funhouse`; the card's venue field
(accent-folded NFD) splits them. No pagination - the whole upcoming calendar
is one page.

Fields per card (`ec-col-item w-dyn-item`): calendar-headliners,
calendar-supports, start-date, doors-cal, show-time-cal, venue,
webflow-link. Notes:
 - "Mammoth NW Presents - El Corazon" = a third-party promoter booking AT
   this venue - those rows belong here and carry a note (canonical labels
   get no note);
 - the Funhouse label is a different act-space in the same building complex
   -> separate feed.

Maintenance: `cd elcorazon && python3 fetch.py && python3 build.py`; validate
with the headlinerlistings-audit skill.
