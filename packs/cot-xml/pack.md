# Pack: cot-xml

Cursor on Target event XML, the `<event>` document with a `<point>` and
`<detail>`. Public. Fields map to the shared model (`spec/shared-model.md`).

| Wire | Model key | Note |
|---|---|---|
| `@version` | none | constant `2.0`, written on every encode |
| `@uid`, `@type`, `@how` | `uid`, `type`, `how` | |
| `@access` | `access` | text as the sender or the caller gives it; no default, so a conversion never chooses one. The base-event schema of atak-civ (`takcot/mitre`) requires it; a caller that must validate against that schema supplies it as context |
| `@time`, `@start` | `time_ms` | ISO 8601; both are written from the one key. Decode reads `time`, and `start` only when `time` is absent |
| `@stale` | `stale_ms` | supplied by the caller: `convert` context, CLI `--set stale_ms=<epoch ms>` |
| `point/@lat`, `@lon`, `@hae`, `@ce`, `@le` | `lat`, `lon`, `hae`, `ce`, `le` | |
| `detail/contact/@callsign` | `callsign` | |
| `detail/track/@course`, `@speed` | `course`, `speed_ms` | degrees true, metres per second |
| `@opex` | `track.opex` | `s` for a simulated track: derived from the track flags (`model/track.def`, `text_if`, spec 0.18) when the entity has none; `e` and `o` decode as written |
| `detail/remarks` text | `track.status_text` | the track's status flags as comma-separated tokens (`test-data`, `simulated`, `tentative`, `coasting`, `final-update`), derived when the entity has none (`tokens`, spec 0.18), as the open-billie translator writes it; a sender's free-text remarks decode as they are |
| `@time`, `@stale` as written | `time_text`, `stale_text` | the sender's text, unparsed, for a target that keeps it (`geo-track-v1`). Encode writes `time_ms` and `stale_ms` first, so the text is written only when the instant is absent |
| `detail/uid/@Droid` | `display_name` | the name the sender shows for the entity |

`<detail>` is written on every encode, empty when nothing inside it is (`element detail`, spec 0.18).

Written when the entity has no value: `type` `a-u-X`, and `hae`, `ce`, `le`
`9999999`. On decode, `9999999` and `9999999.0` in `hae`, `ce` or `le` mean "not known" and leave the key absent (`absent`, spec 0.9), so a target format gets no value rather than the number; a round trip writes `9999999` again. `how` and `stale` are written only when the entity has them.

`detail/track/@speed` is bound to `speed_ms`, the ground speed of the shared model. The MITRE Track schema defines it
otherwise: the magnitude of the velocity in three dimensions, which the schema's own example gives a vertical climb with
no ground speed. The two differ while the object climbs or descends; a conversion does not correct for it.

`ce` and `le`: the MITRE Base-Event schema says each may describe an area or a height range that is not an error, and
that when it is an error the value is the one-sigma point of a zero-mean normal distribution. `ce` and `le` of the
shared model state no sigma, and a conversion carries the number as it is.

Read 2026-11-24, public release, in the repository deptofdefense/AndroidTacticalAssaultKit-CIV at
889eee292c43d3d2eafdd1f2fbf378ad5cd89ecc, `takcot/mitre`: Base-Event schema (sha256
`08da89898d4f37498faf82d03adb7f6fcae6f0d59128f80553c63bfe21000f14`) and Track schema (sha256
`0b53a2eecb5165cccaa2c7e10291902607d71139a0163c9816a414a7167bd078`).

A `start` that differs from `time` does not survive a round trip: both leave
with the value of `time`. Unmapped attributes of `<event>` round-trip through
residue; unmapped child elements are not carried.

## Golden vectors

5 vectors `golden-xml-<n>.json`, written by `tools/gen/golden-takproto.py` from takproto 3.0.1
(MIT; run, not copied; its pin, hashes and licence are in `packs/cot-protobuf/PROVENANCE.md`), a
reference codec of TAK Protocol Version 1. Each is a CoT XML event converted to `cot-protobuf`: the
expected output is the TakMessage takproto writes for the event, in canonical form, and the model
values are what takproto read from it. Only events that hold nothing but what both packs bind are
used (the rule in the script): `<event>` attributes `uid`, `type`, `time` and `start` (equal),
`stale` and `how`; all five point values; `contact/@callsign` and `track`; no point or track value
0, since this pack decodes a 0 and `cot-protobuf` writes it, where a proto3 writer such as
takproto's leaves it out. A `hae`, `ce` or `le` of `9999999` is an absent key.
