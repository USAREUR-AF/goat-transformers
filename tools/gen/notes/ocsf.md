## The form

One message is one OCSF event of one class, in its JSON form: an object with the class's
attributes as members, objects nested as JSON objects and arrays as JSON arrays. The
common `when class_uid <n>` checks the class on decode and writes it on encode
(`class_uid` is the category's number times 1000 plus the class's number).

OCSF does not publish a JSON Schema in the repository. `tools/gen/ocsf2pack.py` resolves
the class from `events/`, `objects/`, `dictionary.json` and `categories.json` (following
`extends`, merging attribute entries, and taking each attribute's type from the
dictionary) into a JSON Schema of structure only, which is the "Sources" file above; the
files it read are listed in `PROVENANCE.md`.

## What is out of scope

- **Profiles.** An attribute that a profile adds (by `$include` of `profiles/<name>.json`,
  or marked with `profile` in the class) is not part of the class unless a producer
  applies the profile, so it is left out. The list for this class is below. A producer
  that applies a profile writes members this pack does not map; scalar ones outside arrays
  are residue and come back on a round trip.
- **Extensions** (`extensions/linux`, `macos`, `windows`): their classes and attributes are
  not read.
- **The `datetime` profile's `*_dt` siblings**, which are RFC 3339 strings beside each
  timestamp: part of a profile, so left out.
- **Enumerations.** An `*_id` member is an integer and its `*_name` sibling a string; the
  captions of the values are not carried.

## Evidence for the shared keys

- `time_ms` (`time`): the dictionary types `time` as `timestamp_t`, which it defines as an
  integer count of milliseconds since 1970-01-01 00:00:00 UTC; the base event makes `time`
  the time the event occurred. Same unit, so a plain `int`.
- `uid` (`metadata.uid`): the metadata object describes it as the identifier given to the
  OCSF event itself, distinct from the identifier of the original event in the source.
- `lat`, `lon` (`device.location.lat`, `device.location.long`): only in classes that have
  `device` as an attribute of their own (not through the host profile). The location
  object and the dictionary give them in decimal degrees. They name no datum; the pack
  takes them as the geographic degrees of `lat` and `lon`.

Not bound: `start_time` and `end_time` (an aggregation window), `metadata.logged_time`,
`metadata.processed_time` and the other times of the record's handling, the many `uid`
members of nested objects (each names its own object), and the locations of other
objects (`src_endpoint.location` and others), which are not the event's own place.
