# cef

One ArcSight Common Event Format (CEF) record without its syslog prefix:
`CEF:Version|Device Vendor|Device Product|Device Version|Device Event Class ID|Name|Severity|Extension`.
Wire `text`, `start "CEF:"`, `delimiter "|"`, no kinds. Written by hand from the format guide;
vectors by `tools/gen/logs-vectors.py`. Licence: `LicenseRef-unstated` (PROVENANCE.md).

| Field | Line | Key |
|---|---|---|
| 0 | `int` | `cef.version` (0 for CEF 0.1, 1 for CEF 1.x) |
| 1 to 5 | `string` | `cef.device_vendor`, `cef.device_product`, `cef.device_version`, `cef.device_event_class_id`, `cef.name` |
| 6 | `string` | `cef.severity`: an integer 0 to 10 or a word, so text |
| 7 on | `group cef.extension 7 item 1` | the extension as text, an item per part between pipes |

The extension may hold pipes without an escape, so it is read as the parts between pipes and
written back joined by pipes: a record comes back unchanged.

## Shared-model keys: none, and why

The extension holds the event's time (`rt`, `start`, `end`), addresses and a position
(`deviceGeoLatitude`, `deviceGeoLongitude` and others in the extension dictionary) as key=value
pairs in any order, separated by spaces, where a value may itself hold spaces. The text wire
reads fields by their place between delimiters; it has no locator for "the value after `rt=`"
and does not split at a space (its delimiter is one character from 0x21 to 0x7E). So the
extension stays text, and none of its keys is bound. The header holds no time or position.

## Not mapped

- The extension's keys: see above. A pack language addition is needed: a field located by a
  key in a key=value list (with the CEF escapes `\=` and `\\`).
- A header field holding an escaped pipe (`\|`): the text wire splits at it, so the fields after
  it are read one place later (vector 03). The record still comes back unchanged.
- The syslog prefix (`Jan 18 11:07:53 host `) that CEF over syslog puts first: a record must
  begin with `CEF:` (vector 05). Syslog itself is not built: its fields are separated by spaces.
- Characters outside 0x20 to 0x7E (CEF is UTF-8; a newline in a value is written `\n`):
  `malformed-wire`.

## Vectors

| File | Shows |
|---|---|
| `01-event-roundtrip.json` | a CEF 0 record with an extension |
| `02-pipe-in-the-extension-roundtrip.json` | a pipe inside the extension: two items, joined again |
| `03-escaped-pipe-in-the-header.json` | `\|` in the name shifts the later fields; the record comes back unchanged |
| `04-version-not-a-number.json` | `CEF:x`: `transform-decode` |
| `05-syslog-prefix-is-not-read.json` | a record that begins with a syslog prefix: `malformed-wire` |
