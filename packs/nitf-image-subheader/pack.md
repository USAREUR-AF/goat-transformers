# Pack: nitf-image-subheader

The fixed part of a NITF 2.1 image subheader: IM through ICORDS (372
characters), IGEOLO (60 characters) when ICORDS is not a space, and NICOM.
Public. Maintained by hand from MIL-STD-2500C appendix A, table A-3. Wire
`text`, `delimiter none`, column locators. Needs engine version 0.10.

Uses the modules `core` and `nitf` (`model/nitf.def`, keys `is_<field>`).

## Message convention

A message is the first bytes of an image subheader (it begins with `IM`, a
common `when`). The pack reads up to NICOM and ignores what follows; encode
writes up to NICOM. IGEOLO is omitted when ICORDS is a space, so NICOM moves;
three kinds follow ICORDS:

| Kind | ICORDS | IGEOLO | NICOM |
|---|---|---|---|
| `geo-decimal-degrees` | `D` | 372-431, text, and the first corner as `lat`/`lon` | 432 |
| `geo-other` | any other non-space code (`G`, `U`, `N`, `S`) | 372-431, text | 432 |
| `no-location` | a space | absent | 372 |

## Shared keys, with evidence

| Field | Key | Evidence |
|---|---|---|
| IGEOLO characters 0-6 when ICORDS is `D` | `lat` (`float`) | table A-3: with ICORDS `D` the corners are `+-dd.ddd+-ddd.ddd` four times, latitude first (+ north); the corners are in image coordinate order, the first being (0,0); ICORDS: "The default Geodetic reference system is WGS84" |
| IGEOLO characters 7-14 when ICORDS is `D` | `lon` (`float`) | the same; + east |

Only the first corner is bound: the model has one position, and (0,0) is the
first pixel of the image. The other three corners stay in the raw text
`nitf.is_igeolo`. The text transforms read no degrees-minutes-seconds form
(`G`), and UTM and MGRS (`U`, `N`, `S`) are not geographic, so those kinds bind
nothing. Digits beyond the known precision are spaces (table A-3); the
column's spaces are removed before the number is read.

The `lat` and `lon` lines are for decode. The raw IGEOLO line comes first, so a
same-format round trip writes the field's own text; and every kind requires a
raw key, so an entity from another format selects no kind (`no-kind`): the
text transforms write no `+` sign and could not write IGEOLO's form.

IDATIM (`CCYYMMDDhhmmss` UTC) stays the raw text `nitf.is_idatim`, for the
reason given for FDT in `nitf-file-header/pack.md`.

## Not mapped, and the constructs it needs

| Part | Why | Construct needed |
|---|---|---|
| ICOM (NICOM comments of 80 characters), IC, COMRAT, NBANDS / XBANDS and the per-band fields, ISYNC, IMODE, NBPR, NBPC, NPPBH, NPPBV, NBPP, IDLVL, IALVL, ILOC, IMAG, UDIDL/UDOFL/UDID, IXSHDL/IXSOFL/IXSHD | NICOM, NBANDS (or XBANDS) and LUTD counts are ASCII-decimal fields; COMRAT is present by the value of IC | a group whose count is an ASCII-decimal text field read earlier; a part present by an earlier field's value |
| UDID, IXSHD (TRE areas) | lengths from UDIDL, IXSHDL | a length from an ASCII-decimal field, and TRE items selected by tag |
| ECS-A text | IID2, ISORCE and the security fields may hold bytes above 0x7E | 8-bit text on the `text` wire |

## Vectors

8 vectors (7 under `vectors/`, one under `packs/geojson/vectors/`), written by
`tools/gen/nitf-header-vectors.py`: decimal-degree round trip, to GeoJSON and
to CoT, blank precision digits, the degrees-minutes-seconds form (text only),
no coordinates, GeoJSON into the subheader (`no-kind`), and a graphic
subheader (`no-kind`).
