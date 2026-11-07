# Showbox SoDo (`showboxsodo`) - Seattle

Sibling of `showbox`: SAME source (showboxpresents.com AEG/AXS calendar,
`common/aeg.py`), different `.venue` label ("Showbox SoDo"). There is no
showboxsodo.com site - SoDo shows only appear on the Presents calendar.
All pagination gotchas (JSON-encoded bodies, window==page-size, clamped
tail) live in `common/aeg.py` and `showbox/README.md`.

Maintenance: `cd showboxsodo && python3 fetch.py && python3 build.py`;
validate with the headlinerlistings-audit skill.
