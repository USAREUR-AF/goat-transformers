## What the message is

Parrot's newer drone features are defined in protobuf rather than in the ARSDK
XML of the `arsdk-*` packs. Each feature's schema file has an `Event` message
whose `oneof` holds every event the drone sends for that feature, and a
`Command` message for what the controller sends. The pack's message is one
serialized `Event` of the feature named above. On the ARSDK link that payload
travels inside the generic custom event of the XML feature `generic` (a service
id, a message number and the payload as binary); that framing is the `arsdk-*`
packs' concern, not this pack's.

Each member of the `oneof` is a kind of the pack, except where the run makes the
envelope one layout (below). The `Command` messages are not built here.

The schema files were read for names, field numbers and types only
(`--no-comments`); these notes are this repository's own words. The custom
options of the schemas (documentation strings, the firmware versions that
support a message, the event a command triggers) do not change the bytes on the
wire and are not carried; the file that declares them is not public, and the run
gives the generator an empty stand-in for it.

## Licence

The protobuf schema files of `arsdk-xml` carry no licence or copyright line, and
the repository has no licence file. The XML files of the same repository carry a
BSD-3-Clause header, but that header is in each XML file and does not reach the
protobuf files. The packs are labelled `LicenseRef-unstated` (PROVENANCE.md).

## Raw by default

No field is bound to a shared key. The positions in these schemas (the backup
link's telemetry, a geofence centre, a point-and-fly target, a navigation
location) give degrees and metres but no datum and no height reference, and a
reserved value such as 500 for an unknown latitude has no transform on this
wire, so every field is a raw key of the pack's own module and the packs convert
to no other format.

- Wrapper types (`google.protobuf.FloatValue` and the like) are carried as their
  one inner field, one level deeper in the path.
- `map` fields, `fixed32`, `fixed64` and `bytes` fields have no form on this
  wire and are not carried.
- A member that is an empty message (`google.protobuf.Empty`) holds no value and
  has no line: its presence is not carried.
