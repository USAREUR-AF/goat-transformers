## The message

CelesTrak's GP query (`https://celestrak.org/NORAD/elements/gp.php?<QUERY>=<value>&FORMAT=JSON`)
answers with a JSON array; one message of this pack is one element of it, the general
perturbations (SGP4) mean elements of one object. The members are OMM keywords of CCSDS
502.0-B-3 in one flat object. CelesTrak leaves out the OMM members that are always the same
for these data (the centre is the Earth, the frame TEME, the time system UTC, the theory
SGP4) and members it has no value for. `FORMAT=JSON-PRETTY` is the same data with white
space; the `celestrak-gp-csv` pack reads the CSV form.

The OMM Blue Book gives the units, which the JSON form does not repeat: `MEAN_MOTION` in
revolutions per day; `INCLINATION`, `RA_OF_ASC_NODE`, `ARG_OF_PERICENTER` and
`MEAN_ANOMALY` in degrees; `ECCENTRICITY` without unit; `BSTAR` in inverse Earth radii;
`MEAN_MOTION_DOT` in revolutions per day squared and `MEAN_MOTION_DDOT` in revolutions per
day cubed. `NORAD_CAT_ID` is the catalogue number, which CelesTrak's JSON form carries
beyond five digits.

## Not bound

- `EPOCH` is UTC (the time system CelesTrak leaves out as fixed) but is written without a
  zone designator and with six fraction digits (`2026-11-20T11:52:34.208832`);
  `iso8601_ms` requires a designator, so `time_ms` is not bound and `EPOCH` is a raw string.
- The elements describe a mean orbit, not a position: nothing is bound to `lat`, `lon`,
  `hae`, `course` or `speed_ms`. A position needs an SGP4 propagation, which is not a
  transform of the pack language.
- `NORAD_CAT_ID` identifies the object too; `uid` takes `OBJECT_ID`, as `sds-omm` and
  `ccsds-ndm-xml` do, so the three packs give `uid` the same value for one object.
