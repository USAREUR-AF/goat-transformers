SPDX licence: Apache-2.0

# Provenance: homeassistant-ws-state-changed

Written by hand from the source of Home Assistant core. No source file is copied into this tree.

| | |
|---|---|
| Repository | https://github.com/home-assistant/core |
| Tag | `2026.11.2`, commit `ff5d56b825a0fb66b03d01bc297d49e206cdaba3` (committed 2026-11-16T21:02:58+01:00), the latest release when read |
| Files read | `homeassistant/core.py` (the dictionary forms of State, Event and Context), `homeassistant/components/websocket_api/messages.py` (the event message), `homeassistant/const.py` (the attribute names), `homeassistant/util/location.py` (the ellipsoid its distances use) |
| Date read | 2026-11-20 |
| Not used | the developer documentation site (repository home-assistant/developers.home-assistant), whose licence GitHub does not identify |

## Licence

`LICENSE.md` at the tag is the Apache License, Version 2.0. GitHub reports the repository as
`Apache-2.0`.

## What this repository takes

The member names and nesting of the state object and of the websocket event message, the
attribute names `latitude`, `longitude`, `gps_accuracy`, `radius` and `friendly_name`, and the
text form of the times (Python's `isoformat()`). pack.md states them in this repository's words.

## SHA-256

```
5671149ec3405c4ec81eed05f58e3c392dafe0af141ec6ac7ea1a2b4b658d038  homeassistant/core.py
81403e3f9b09dcc75e1f4d9a428c30acbfa21beb00970abf18a8ecce86b0ac56  homeassistant/const.py
525d060ffc2aa2ab8f76a075d036c1ebb5cf243e5391f5ef11c73f7be1a5c7ed  homeassistant/components/websocket_api/messages.py
28a08e718b9438c06e8d7f0b7da4da2ef0ceee38b7f1ff50be06bcab04f953a5  homeassistant/util/location.py
c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4  LICENSE.md
```
