## Evidence for the shared keys

- `uid` (`id`: the identifier of the operational intent, assigned at creation and kept for its life.)

## Not bound

The 4D volumes (polygons or circles with altitude bounds and a time window) are lists of
vertices and stay raw: a volume is an area, not one position. Start and end times bound the
volume; neither is the time of a report.

## Licence and source

The source of record is InterUSS's Apache-2.0 api.py module for this interface in
interuss/uas_standards; the OpenAPI file, which states no licence, is read for convenience and
agrees with api.py (tools/gen/utm-crosscheck.py). The ASTM standards (paid documents) were not
used. PROVENANCE.md has the details.
