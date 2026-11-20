## What a message is

One FHIR R4 resource in its JSON form (https://hl7.org/fhir/R4/json.html): a JSON object
whose `resourceType` names the resource. Each resource type is its own pack with one kind,
selected by `resourceType`. A Bundle is a pack of its own (`fhir-r4-bundle`); the resources
inside its entries are not mapped there (see the limits below).

## Evidence for the shared keys

- `uid` (`id`): the logical id of the resource on its server; FHIR states it never changes
  once assigned.
- `time_ms` (`meta.lastUpdated`): when the resource last changed, a FHIR `instant` (date, time
  to the second and a time zone, optional fraction). `iso8601_ms` reads it in UTC and writes
  it with milliseconds and `Z`; the raw key keeps the text as written, and digits of the
  fraction past the third are dropped by the transform.
- Location only: `lat` and `lon` (`position.latitude`, `position.longitude`): FHIR states the
  position in the WGS 84 datum, with the value domain of KML's latitude and longitude:
  decimal degrees. `position.altitude` is not bound to `hae`: FHIR gives it the meaning of
  KML's altitude, metres measured from sea level or from the ground (KML's altitudeMode,
  which FHIR does not carry), never from the WGS 84 ellipsoid; it is a raw key.

## Choice types and extensions

- **Choice types** (`value[x]`, `effective[x]`, ...): the schema lists each choice as its own
  member (`valueQuantity`, `valueString`, ...), so each is mapped as a member like any other,
  within the depth limit. Nothing ties the alternatives together; a message holds one of
  them.
- **Extensions** (`extension`, `modifierExtension`) and the `_<name>` siblings that carry a
  primitive's id and extensions are not mapped (see the limits below): an extension's value
  is any FHIR datatype, chosen by `url`, which a `json` line cannot select.
- **`contained`** resources are not mapped: each is a whole resource of any type.

## Licence

FHIR is CC0 (https://hl7.org/fhir/R4/license.html). HL7, FHIR and the FHIR flame design
are registered trademarks of Health Level Seven International; their use here does not
constitute endorsement by HL7. `PROVENANCE.md` quotes the license page.
