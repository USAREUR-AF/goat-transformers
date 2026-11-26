## Evidence for the shared keys

- `lat`, `lon` (`Message.PositionReport.Latitude`, `.Longitude`): the schema types them
  as numbers and states no unit; the aisstream.io documentation (read 2026-11-20) gives
  both in decimal degrees for the position report. They are the position of AIS message
  types 1 to 3 decoded, and AIS positions are WGS 84 by the protocol (ITU-R M.1371), as
  `packs/ais` states. The documentation does not repeat the datum.

Not bound, and why:

- The position members of the other types (class B reports, base station, aid to
  navigation, search and rescue aircraft, long-range broadcast) have the same names, but
  the documentation states the unit for the position report only.
- `UserID` is the MMSI, an integer; `uid` is a string, and the json wire has no transform
  from a number to text.
- `Sog`, `Cog` and `TrueHeading` carry no unit in the schema or the documentation.
- `MetaData` is an object with no stated members; what it holds is residue, carried back
  as it was.

## Kinds

Each kind is selected by `MessageType`, whose value is the name of the member of `Message`
that holds the report. `DataLinkManagementMessageData` is listed among the types, but the
document has no schema of that name, so it is not a kind. Encode from another format takes
the first kind, `PositionReport`.

## The wrapper schema

`tools/gen/aisstream-run.sh` writes a small schema of its own, one envelope per message
type that refers to that type's schema in `type-definition.yaml`, so that a kind holds only
its own report. It adds no member that the document does not state.

## Validity flag not applied

PositionReport `Valid`: the documentation says whether the decoded value passed validation. The pack keeps the flag as a raw key and binds the position whatever it says: a message whose
flag says there is no fix converts with the coordinates it carries (often 0, 0), as if they were a
position. The pack language has no gate for a JSON or protobuf member yet (asked of gt-lang); until
it has, a consumer must read the flag. Bit-level packs of the same messages (PX4) read the shared
keys only when the flag says so.
