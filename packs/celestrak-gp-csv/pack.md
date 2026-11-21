# Pack: celestrak-gp-csv

One data row of CelesTrak's GP data in CSV form (`gp.php?...&FORMAT=CSV`): the SGP4 mean
elements of one object. Public. Hand-written on the `text` wire (engine-spec 0.10).
Uses the modules `core`, `ckgp` (the keys of `celestrak-gp-json`, generated from this
project's restatement) and `ckgpcsv` (`model/ckgpcsv.def`, three text keys of this form).

## Message convention

A message is one data row, without its line break: 17 values separated by `,`. The pack
has no start text, no checksum and no kinds.

### Column order

CelesTrak's documentation says the CSV form carries the OMM keywords, and the first line of
a response names the columns; it does not fix their order in prose. A pack of the `text`
wire addresses a field by its position. **Convention:** the columns are those of the header
CelesTrak sent on 2026-11-21, in that order:

    OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,RA_OF_ASC_NODE,ARG_OF_PERICENTER,MEAN_ANOMALY,EPHEMERIS_TYPE,CLASSIFICATION_TYPE,NORAD_CAT_ID,ELEMENT_SET_NO,REV_AT_EPOCH,BSTAR,MEAN_MOTION_DOT,MEAN_MOTION_DDOT

A row under a header with another order does not decode correctly; the caller reorders it.
The header row itself is not a message: its numeric columns fail with `transform-decode`.
Missing addition (as for the GTFS packs): **a header-defined column order** on the `text`
wire.

### Numbers

The angle, mean-motion and eccentricity columns are decimals, sometimes with no digit
before the point (`.0007409`); the `text` wire's `float` reads them and writes them in its
canonical form (`0.0007409`; a trailing zero such as `172.9450` is written `172.945`). The
`BSTAR`, `MEAN_MOTION_DOT` and `MEAN_MOTION_DDOT` columns are written in exponent notation
(`.17778E-3`), which `float` on the `text` wire refuses; they are kept as text in the three
`ckgpcsv` keys. The same three values are floats in `celestrak-gp-json` (module `ckgp`), so
a conversion between the two forms leaves them out. Missing addition: **exponent notation
for `float` on the `text` wire**; with it these columns would take the `ckgp` keys.

### Quoted values and characters

The `text` wire has no quoting and accepts characters 0x20 to 0x7E only. A name holding a
comma, if CelesTrak quoted it, would shift the later columns; a name with any other
character is `malformed-wire`. No row of the samples read had either.

## Shared keys

| Column | Key | Evidence |
|---|---|---|
| `OBJECT_ID` | `uid` (string, no unit) | CCSDS 502.0-B-3 (table 4-2) gives OBJECT_ID as the identifier of the object, recommending the international designator that stays with the object for its life; CelesTrak's documentation says the CSV form uses the OMM keywords with their OMM definitions. The same binding as `celestrak-gp-json`, `sds-omm` and `ccsds-ndm-xml`. An object of the analyst range has no designator: the column is empty and `uid` is absent. |

## Not mapped, and why

- `EPOCH` is UTC but written without a zone designator and with six fraction digits;
  `iso8601_ms` requires a designator, so `time_ms` is not bound and `EPOCH` is a raw string.
- No position: the elements describe a mean orbit, and a position needs an SGP4
  propagation, which no transform performs.
- Units (from the OMM Blue Book, not repeated in the row): mean motion in revolutions per
  day, the four angles in degrees, BSTAR in inverse Earth radii, the first and second
  derivatives of the mean motion in revolutions per day squared and cubed.

## Vectors

`tools/gen/space-text-vectors.py` writes them (no engine is run): a round trip, a row with
no designator, the header row (an error), a conversion to `celestrak-gp-json` and one from
it (in `packs/celestrak-gp-json/vectors/to-celestrak-gp-csv-*`), a quoted comma (an error)
and a non-ASCII name (an error). Every input is constructed.
