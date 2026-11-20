## Shared keys

None is bound. Every response holds its records in the `results` list, so a location's
coordinates, a measurement's time and a sensor's identifier are members of list items,
not of one entity; the pack maps them to list keys of the format's own module. The
coordinates also carry no stated unit or datum in the document. No conversion vector to
geojson or cot-xml is written.

## Terms

The OpenAQ terms of use apply to the hosted API and require attribution to OpenAQ for
data obtained through it; see PROVENANCE.md.
