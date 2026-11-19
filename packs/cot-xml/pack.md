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
| `@time`, `@stale` as written | `time_text`, `stale_text` | the sender's text, unparsed, for a target that keeps it (`geo-track-v1`). Encode writes `time_ms` and `stale_ms` first, so the text is written only when the instant is absent |
| `detail/uid/@Droid` | `display_name` | the name the sender shows for the entity |

Written when the entity has no value: `type` `a-u-X`, and `hae`, `ce`, `le`
`9999999`. On decode, `9999999` and `9999999.0` in `hae`, `ce` or `le` mean "not known" and leave the key absent (`absent`, spec 0.9), so a target format gets no value rather than the number; a round trip writes `9999999` again. `how` and `stale` are written only when the entity has them.

A `start` that differs from `time` does not survive a round trip: both leave
with the value of `time`. Unmapped attributes of `<event>` round-trip through
residue; unmapped child elements are not carried.
