## NeTEx in this pack

One message is one `PublicationDelivery` document in the NeTEx default namespace
`http://www.netex.org.uk/netex`. This pack reads the one frame type it is named after, as
NeTEx profiles in use carry it: inside a `CompositeFrame`, under
`dataObjects/CompositeFrame/frames`. A frame of that type placed directly under
`dataObjects`, the other frame types, and `PublicationRequest` (the request a delivery
echoes) are left out of this pack (see "Left out of this pack"); a document that holds
them decodes, and what lies under them is dropped. Four packs are generated from the same
schema set, one per frame type: `netex-service-frame`, `netex-site-frame`,
`netex-timetable-frame` and `netex-service-calendar-frame` (`tools/gen/netex-run.sh`).

Entities of a frame are lists (`<entities>/<Entity>` inside the frame item), and an
entity's own lists (alternative texts, key lists, validity conditions) are below the
group nesting limit of three, so they are not mapped.

**Positions are not bound to `lat` and `lon`.** The schema's `LocationStructure` states
that `Longitude` and `Latitude` are WGS 84 decimal degrees (longitude from Greenwich,
-180 to 180; latitude from the equator, -90 to 90), and `Altitude` is metres above sea
level, so it would not be `hae`. But every `Location` of these packs lies in a list item
(a stop point, a stop place, a quay), and a shared key is bound only outside lists: the
model's `lat` and `lon` are one position per message, and a delivery holds many. They are
the raw keys `*_location_longitude` and `*_location_latitude` of each item, in degrees.
A `gml:pos` alternative to them, and every other GML geometry, is in a declined namespace.

**Times are not bound to `time_ms`.** `PublicationTimestamp` and the other date-times are
`xs:dateTime` with no restriction to UTC, so they are kept as text.

Lists of different element names that a NeTEx document may interleave (the members of a
substitution group, or of a repeated choice) are read name by name; an encoder writes
all items of one name, then the next. NeTEx does not give that order a meaning, but a
round trip of a document that interleaves them is not byte for byte.
