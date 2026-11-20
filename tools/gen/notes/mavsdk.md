## What the message is

MAVSDK's `mavsdk_server` offers each plugin of the SDK as a gRPC service. A
plugin's `Subscribe…` call answers with a stream of one response message, each
holding the plugin's current state or the next event. The pack's message is one
such response in its protobuf encoding: the bytes of one message of that stream,
without the five-byte gRPC length prefix.

Each pack holds one response type, not one plugin. A protobuf message does not
name its own type, and every subscription response of a plugin puts its payload
at field 1, so the responses of one plugin cannot be told apart by their bytes
and cannot be kinds of one pack; the gRPC method (the stream it arrived on) is
what names the type.

The schema files were read for names, field numbers and types only
(`--no-comments`); these notes are this repository's own words. The custom field
options of `mavsdk_options.proto` (a default value and a comparison tolerance
for the SDK's language bindings) do not change the bytes on the wire and are not
carried.

## Licence

The MAVSDK-Proto repository states no licence: it has no licence file, the
schema files carry no licence line, and the repository's metadata names none.
The packs are labelled `LicenseRef-unstated` (PROVENANCE.md).

## Raw by default

A field is a raw key of the pack's own module unless the notes below bind it.
`fixed32`, `fixed64` and `bytes` fields have no transform on this wire and are
not carried. Messages inside the response are carried as `group` blocks where
they repeat.
