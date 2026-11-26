# Pack: cot-xml-radar

Cursor on Target with the radar cross section in a detail element. Public. It
is the pack `cot-xml`, line for line, plus one line. Everything
`packs/cot-xml/pack.md` says holds here.

**Choosing this format is the opt-in.** `cot-xml` neither reads nor writes the
element.

| XML | Model key | Note |
|---|---|---|
| `detail/__radar/@rcs_m2` | `radar.rcs_m2` | the radar cross section in square metres, as the reporting radar measured it |

The event schema defines no element for a radar cross section. `detail` is
open content, and tools name their own detail elements with two leading
underscores, so the value is the attribute `rcs_m2` of an element `__radar`,
written after `detail/remarks`. A reader that does not know the element
ignores it. The element is written only when the entity has `radar.rcs_m2`.

A track built from several radars has no single radar cross section
(`spec/shared-model.md`, "The radar module"): the value is the one the entity
carries, which is the value of the source that made the report.

## Height

As in `cot-xml`: `point/@hae` is the height above the WGS-84 ellipsoid in
metres, bound to `hae`.
