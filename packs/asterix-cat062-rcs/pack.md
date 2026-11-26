# Pack: asterix-cat062-rcs

ASTERIX Category 062 with the radar cross section in the Special Purpose field.
Public. It is the pack `asterix-cat062`, line for line, plus the content of
I062/SP (FRN 35). Everything `packs/asterix-cat062/pack.md` says holds here.

**Choosing this format is the opt-in.** `asterix-cat062` reads an I062/SP item
and never writes one. This pack writes one when the entity has `radar.rcs_m2`,
and writes none when it does not.

## The Special Purpose field

Category 062 has no item for a radar cross section. The category leaves the
content of I062/SP to the users of a link, so the sender and the receiver must
both use this layout:

| Octet | Content |
|---|---|
| 1 | LEN = 5: the length of the item in octets, this octet included |
| 2 to 5 | the radar cross section in square metres, an IEEE-754 single, most significant octet first |

| Item | Model key |
|---|---|
| I062/SP octets 2 to 5 | `radar.rcs_m2` |

A receiver that does not know the layout skips the item by its length octet.
A system track built from several radars has no single radar cross section
(`spec/shared-model.md`, "The radar module"): the value written is the one the
entity carries, which is the value of the source that made the report.

When a receiver names a different place for the value, that is a new pack or a
new version of this one. `asterix-cat062` does not change.

## Height

As in `asterix-cat062`: I062/130 is the geometric altitude, a height above the
WGS-84 ellipsoid in steps of 6.25 ft, and it is bound to `hae` in metres.
