# leef

One IBM QRadar Log Event Extended Format (LEEF) record without its syslog prefix:
`LEEF:1.0|Vendor|Product|Version|EventID|attributes`, or `LEEF:2.0|...|EventID|Delimiter|attributes`.
Wire `text`, `start "LEEF:"`, `delimiter "|"`. Written by hand from IBM's documentation;
vectors by `tools/gen/logs-vectors.py`. Licence: `LicenseRef-unstated` (PROVENANCE.md).

| Kind | Holds when | Fields |
|---|---|---|
| `leef-2` | field 0 is `2.0` | vendor, product, version, event ID, the attribute delimiter (field 5, as written: a character such as `^`, or `x` / `0x` and hex digits), attributes from field 6 |
| `leef-1` | field 0 is `1.0` | vendor, product, version, event ID, attributes from field 5 |

The attributes are text, an item per part between pipes (`group … item 1`), so a pipe inside
them comes back. On encode from another format `leef-2` is chosen when the entity has a
delimiter (`requires leef.attribute_delimiter`), else `leef-1`.

## Shared-model keys: none, and why

The attributes hold the event's time (`devTime` with its format in `devTimeFormat`), addresses
and other values as key=value pairs, separated by the delimiter, in any order. The text wire
cannot split at a delimiter that the record itself names, and has no locator for "the value of
the key `devTime`", so the attributes stay text. The header holds no time or position.

## Not mapped

- Attributes separated by a tab: LEEF 1.0 always uses a tab, and LEEF 2.0 uses one when it
  names `x09` or `0x09`. The text wire reads only characters 0x20 to 0x7E, so such a record is
  `malformed-wire` (vector 04). A LEEF 1.0 record with a single attribute reads.
- The attributes' keys: a key=value locator, and a split at a delimiter named by the record,
  are needed.
- The syslog prefix that LEEF over syslog puts first.

## Vectors

| File | Shows |
|---|---|
| `01-leef-2-roundtrip.json` | LEEF 2.0 with `^` between attributes |
| `02-leef-2-hex-delimiter-roundtrip.json` | the delimiter written `x5E` is kept as written |
| `03-leef-1-one-attribute-roundtrip.json` | LEEF 1.0 with one attribute |
| `04-leef-1-tab-is-not-text.json` | LEEF 1.0 with a tab between attributes: `malformed-wire` |
| `05-unknown-version.json` | `LEEF:3.0`: `no-kind` |
