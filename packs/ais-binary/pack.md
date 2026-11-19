# Pack: ais-binary

AIS binary application messages: payloads of message types 6 (binary
addressed) and 8 (binary broadcast) whose application data, chosen by the
designated area code (DAC) and the function identifier (FI), has a fixed
layout. Public. Written from the gpsd document "AIVDM/AIVDO protocol decoding"
v1.58, the source of pack `ais`; the layouts are restated in this project's
words. I/O is the six-bit armored text (`spec/engine-spec.md`, Version 0.14).

Uses the modules `core`, `ais` (`model/ais.def`, of pack `ais`) and `aisbin`
(`model/aisbin.def`).

Pack `ais` reads every other message type and leaves types 6 and 8 out,
because their data runs to the end of the message. This pack reads the
subtypes whose data has a fixed length, one kind each.

## Message convention

As in pack `ais`: a message is one whole payload, the armored text of an
`AIVDM` or `AIVDO` sentence with a payload split over several sentences
already joined. The sentence, the fill-bit count and the joining of fragments
are not part of the pack (ruling 1 of 0.14). `word_bytes 1`, `bit_order msb`,
`armor sixbit`: `0:<bit>:<len>` counts from the first bit of the payload, the
numbering the source uses.

Every bit of each layout is mapped, spare bits included, so a payload of the
layout's length comes back exactly. Integers are the wire value; six-bit text
is read with `sixbit`, which removes trailing `@` only.

## Kinds

Bits 0-37 (type, repeat indicator, MMSI) are common. Each kind has three
`when` lines, the type, the DAC and the FI; the two weather observation kinds
add bit 56. In type 6 the DAC is bits 72-81 and the FI bits 82-87, after the
sequence number, the destination MMSI and the retransmit flag; in type 8 they
are bits 40-49 and 50-55.

| Kind | Type | DAC | FI | Bits | Position bound |
|---|---|---|---|---|---|
| `dangerous-cargo-imo236` | 6 | 1 | 12 | 360 | |
| `persons-on-board-imo289` | 6 | 1 | 16 | 136 | |
| `clearance-time` | 6 | 1 | 18 | 360 | the port and berth |
| `berthing-data` | 6 | 1 | 20 | 360 | the berth |
| `inland-eta` | 6 | 200 | 21 | 248 | |
| `inland-rta` | 6 | 200 | 22 | 232 | |
| `inland-persons-on-board` | 6 | 200 | 55 | 168 | |
| `aton-monitoring-uk` | 6 | 235 | 10 | 136 | |
| `aton-monitoring-roi` | 6 | 250 | 10 | 136 | |
| `met-hydro-imo236` | 8 | 1 | 11 | 352 | the station |
| `fairway-closed` | 8 | 1 | 13 | 472 | |
| `extended-static-imo236` | 8 | 1 | 15 | 72 | |
| `traffic-signal` | 8 | 1 | 19 | 360 | the signal station |
| `weather-observation` | 8 | 1 | 21, bit 56 = 0 | 360 | the observing ship |
| `weather-observation-wmo` | 8 | 1 | 21, bit 56 = 1 | 360 | |
| `extended-static-imo289` | 8 | 1 | 24 | 360 | |
| `met-hydro-imo289` | 8 | 1 | 31 | 360 | the station |
| `inland-static-voyage` | 8 | 200 | 10 | 168 | |
| `emma-warning` | 8 | 200 | 23 | 256 | |
| `water-levels` | 8 | 200 | 24 | 168 | |
| `signal-status` | 8 | 200 | 40 | 168 | the signal |

The two AtoN kinds share one layout and one set of keys; they differ in the
DAC only, so that a round trip keeps it. A DAC and FI pair with no kind here
is `no-kind`.

The keys of a kind are `aisbin.<prefix>_<field>`, the field name the source
uses after a prefix for the kind (`dc236`, `pob289`, `clr`, `berth`, `ieta`,
`irta`, `ipob`, `aton`, `mh236`, `fwc`, `ess236`, `sig`, `wx`, `wxw`, `ess289`,
`mh289`, `ist`, `emma`, `wl`, `isig`). The keys every kind shares are
`aisbin.seqno`, `aisbin.retransmit` (type 6), `aisbin.dac`, `aisbin.fid`,
`aisbin.linkage` and `aisbin.wmo`. Each kind requires `ais.mmsi` and its first
field of its own, so an entity from another format, which holds none of these,
is not encoded as any of them.

## Keys of pack `ais`, reused

| Key | Bits | Evidence |
|---|---|---|
| `ais.msg_type`, `ais.repeat`, `ais.mmsi` | 0-5, 6-7, 8-37 | Every subtype table repeats the type, the repeat indicator "as in Common Navigation Block" and the 30-bit source MMSI, as in every other type; `uid` derives from `ais.mmsi` by `model/ais.def` |
| `ais.dest_mmsi` | type 6, 40-69 | The type 6 table: the MMSI of the destination station, the meaning `model/ais.def` gives the key |
| `ais.spare`, `ais.spare2`, `ais.spare3` | the spare ranges, in order | "first, second, third spare range of the message, as on the wire"; a spare range longer than 64 bits is two of them |
| `ais.accuracy` | DAC 1 FI 31, bit 105 | The FI 31 table gives the fix quality "as in Common Navigation Block", the position accuracy flag of `ais.accuracy` |

## Shared keys, with evidence

| Wire field | Model key | Transform | Evidence |
|---|---|---|---|
| Longitude and latitude, DAC 1 FI 11, 18, 19, 20, 21 (bit 56 = 0) and 31 | `lon`, `lat` | `sscale:1/60000` | Each table gives the position as a signed integer in units of one thousandth of a minute (FI 11, 18, 19, 20, 21, 31), east and north positive. A thousandth of a minute is 1/60000 degree. |
| Longitude and latitude, DAC 200 FI 40 | `lon`, `lat` | `sscale:1/600000` | The FI 40 table gives the signal position in ten-thousandths of a minute, "as in CNB", the unit of the position reports that pack `ais` binds with the same factor. |

What the evidence does not show, as for pack `ais`:

- **Datum.** The source names no datum. `core.lat` and `core.lon` are WGS 84;
  the binding assumes AIS positions are WGS 84, the assumption pack `ais`
  makes and states.
- **Whose position.** The position is of the entity the message describes,
  which is not always the sending ship: the port and berth (FI 18), the berth
  (FI 20), the meteorological station (FI 11, 31), the signal station or signal
  (FI 19, DAC 200 FI 40). The MMSI is still the sender's, and gives `uid`.
- **Not-available positions.** The source codes an unknown longitude and
  latitude as 181 and 91 degrees in the field's unit (FI 11 as the field's
  largest value). They decode as those numbers, as in pack `ais`; no sentinel
  turns them into an absent key.

## Not mapped, and why

| What | Why |
|---|---|
| Type 6 DAC 1 FI 14 and 32 (tidal window), DAC 1 FI 25 (dangerous cargo, IMO289), FI 28 and 30 (route, text, addressed); type 8 DAC 1 FI 22 and type 6 FI 23 (area notice), FI 17 (VTS-generated targets), FI 26 (environmental), FI 27 (route), FI 29 (text) | Their data repeats a record or runs as text to the end of the message, and the source gives each a range of lengths. The fixed layout cannot read a field whose length is the rest of the input (pack `ais`, "Not mapped", types 6 and 8); a kind for the fixed part only would drop the rest without notice. They are `no-kind`. |
| Type 6 DAC 1 FI 16 in its older 72-bit form | The source describes two layouts for this pair, told apart only by the message length: the older one has no destination MMSI. A `when` cannot test the length; the 136-bit form is the kind. A 72-bit payload is `no-kind`: it ends before bits 72-81, where a type 6 DAC stands. |
| The units of the integers | Wind speed, temperatures, water level, visibility and the rest are the wire integer in the field's step, which each key's description gives where the source gives one. Several fields carry offsets or not-available codes the source states per field, and some of its statements disagree (a signed temperature whose not-available code is positive, a 16-bit field whose not-available code is 65536). The pack does not scale them, so it states nothing the source does not settle. |
| Times | Each subtype gives day, hour and minute (some a month or a year since 2000) and no full date; no derive function builds an instant from them. |
| The WMO variant position (FI 21, bit 56 = 1) | Unsigned, in hundredths with an offset, by the source's formula; the table also calls the unit hundredths of a minute. The two readings differ, so the fields are raw keys `aisbin.wxw_lon` and `aisbin.wxw_lat`. |
| EMMA warning positions (DAC 200 FI 23) | Two positions, the start and end of the warning area, not one entity's; raw keys in ten-thousandths of a minute. |
| Water levels (DAC 200 FI 24) | The source gives an array of gauges; at 168 bits it holds four of 25 bits, mapped as `wl_gauge1` to `wl_gauge4`. |

Two places where the source's table and its bit ranges disagree, and the bit
ranges are taken:

- DAC 1 FI 15 gives the air draught as bits 55-66 with 11 bits, which would
  overlap the FI; it is bits 56-66.
- DAC 1 FI 31 gives the visibility flag a length of 7 and the visibility a
  length of 8 at bits 193 and 194-200; the ranges, 1 and 7 bits, add up to the
  stated 360.

## Vectors

`tools/gen/ais-binary-vectors.py` builds every payload from values it chooses
and armors it itself: a round trip of each of the 21 kinds, spare bits that
carry, signed edge values, full and empty text, conversions to `geojson` with
and without a position, and the errors: a DAC and FI with no kind (environmental),
a type 1 message, an AtoN layout with another FI, a payload one character short
and a character outside the armor.
