# Pack: drip

The DRIP authentication formats of IETF RFC 9575 section 4, as they travel in an
ASTM F3411 Broadcast Remote ID Authentication Message (Authentication Type 5,
Specific Authentication Method): the DRIP Link, which carries a Broadcast
Endorsement, the DRIP Wrapper and the DRIP Manifest. Public. Written by hand from
the RFC; the layouts are stated here in this repository's words. I/O is hex text.
Needs engine version 0.7 (kinds, fixed-count groups and nested groups on the
`bits` wire).

Uses the modules `core`, `rid` (`model/rid.def`, of pack `remote-id`) and `drip`
(`model/drip.def`).

## Message convention

An Authentication Message is sent as pages of 25 octets: the message type and
version octet, the page header octet (Authentication Type, page number), then 23
payload octets. A message of this pack is the Authentication Payload of RFC 9575
section 3.2.2: the 23 payload octets of every page, page 0 first, joined. Joining
the pages is the receiver's work; the pack does not read page framing (layered
framing is designed, not built).

| Octets | Content | Lines |
|---|---|---|
| 0 | last page index | `rid.auth_last_page_index`, common |
| 1 | Length: the octets of authentication data | `when` of every kind |
| 2-5 | timestamp, least significant octet first | `rid.auth_timestamp`, common |
| 6 | SAM Type: 1 Link, 2 Wrapper, 3 Manifest, 4 Frame | `when` of every kind |
| 7-10, 11-14 | VNB and VNA timestamps, least significant octet first (F3411 timestamp: seconds since 2019-01-01T00:00:00Z) | `drip.vnb`, `drip.vna` |
| 15 on | the rest of the format, below | |

After the authentication data come the ADL octet, the FEC octets and null
padding (RFC 9575 sections 3.2.2 and 5). Decode reads over them; encode writes
the 6 header octets and the Length octets of data only, so a round trip of a
message with FEC returns it without the FEC.

`wire bits`, `word_bytes 1`, `bit_order lsb`: F3411 holds integers least
significant octet first, and the Location fields are those of pack `remote-id`,
which reads them the same way. A locator is `0:<bit offset>:<len>`; octet *n*
starts at bit 8 *n*.

## Kinds

The authentication data has no count of its parts; RFC 9575 derives the number
of wrapped messages and of hashes from its length. The pack does the same with
one kind per length: each kind has `when` on the Length octet and on the SAM
Type octet.

| Kind | Length | Content after VNA |
|---|---|---|
| `link` | 137 | child DET (16 octets), child host identity (32), parent DET (16), parent signature (64) |
| `wrapper-<n>-location-<i>` | 89 + 25 *n*, *n* 1 to 4 | *n* F3411 messages of 25 octets (no message counter); the message in place *i* has message type 1 (Location), read by `when` on its type nibble; then the UA DET (16) and UA signature (64) |
| `wrapper-<n>` | 89 + 25 *n*, *n* 0 to 4 | the same with no Location message read; *n* = 0 is the form for extended transports, whose signature covers the Message Pack it travels in |
| `manifest-<n>` | 113 + 8 *n*, *n* 0 to 11 | previous, current and Link hashes (8 octets each), *n* message hashes (8 octets each), UA DET (16), UA signature (64) |

28 kinds. A Wrapper with a Location message in place *i* selects
`wrapper-<n>-location-<i>`, which stands before `wrapper-<n>`. The wrapped
messages before the Location message are the list `drip.wrapped`, those after it
`drip.wrapped_after`; in `wrapper-<n>` every wrapped message is in `drip.wrapped`.
A wrapped message item holds `rid.proto_version`, `rid.msg_type` and the list
`drip.message_data` of its 24 further octets. A length that fits no kind
(a Wrapper of 100 octets) is `no-kind`.

DETs, host identities, signatures and hashes are opaque octet strings: each is
a list of octets (`drip.octet`, 0 to 255) in wire order.

`requires`: `link` the parent signature; a Wrapper the UA signature (and `lat`,
`lon` in a Location kind; `drip.wrapped` in `wrapper-<n>`, *n* > 0); a Manifest
the UA signature and the Link hash. An entity from another format holds none of
them: nothing can be signed by a conversion, so no other format encodes to this
pack.

## Shared keys

| Key | Where | Evidence |
|---|---|---|
| `lat`, `lon` | the wrapped Location message, `sscale:1/10000000` | as in pack `remote-id`: the F3411 Location message holds latitude and longitude as 32-bit integers of 10^-7 degree (`pack.md` of `remote-id`, "Encodings"); RFC 9575 section 4.3 wraps whole F3411 messages unchanged |
| `hae` | the wrapped Location message, `uscale:1/2:-1000`, `absent 0` | as in pack `remote-id`: geodetic altitude, the height above the WGS84 ellipsoid, (meters + 1000) x 2; raw 0 (-1000 m) is unknown, so absent, as for `rid.alt_baro` and `rid.height` |

The other Location fields go to the `rid` keys pack `remote-id` uses for them.
A Location message that is wrapped is the same message an aircraft also sends on
its own (RFC 9575 section 4.3.3): the position is the reported aircraft's.

## Not mapped

| What | Why, and what would state it |
|---|---|
| DRIP Frame (SAM Type 4) | its evidence is a Frame Type octet and 0 to 111 octets whose length only the Length octet gives, followed by fixed parts. One kind per length would be 112 kinds; a field whose length is the Length octet less the fixed parts would state it in one. RFC 9575 defines no Frame Type |
| ADL, FEC and padding | read over; FEC is redundancy over the pages, not message content. A layered pack for the page framing (designed) would hold them |
| Page framing (message type octet, page header octet per page) | the message of this pack is the joined payload; layered framing is designed, not built |
| A Wrapper with two Location messages | the first one is read; F3411 messages in a Wrapper are in type order, and a second Location message is in `drip.wrapped_after` as octets |
| Wrapped messages other than Location | carried as octets; reading each by its type needs a group whose items are decoded by kind on a fixed layout (sequential layouts have it, but the Wrapper's count comes from its length) |
| DET as an IPv6 address text (RFC 9374), timestamps as `time_ms` | no transform writes 16 octets as an address, and a scale that yields an integer (to add the 2019 epoch in milliseconds) is designed, not built |
| Signature and hash verification | not a conversion: the pack carries the octets |

## The RFC's Link example

The Link in the raw example of RFC 9575 Appendix B.2.1 carries the SAM Type
value 4, which table 1 assigns to DRIP Frame, while section 4.2 and table 1 give
DRIP Link the value 1; its Length (137) and its layout are those of a Link. Read
by this pack as published, it would select no kind. No erratum was recorded for
RFC 9575 on 2026-11-19. The vectors do not use the RFC's examples.

## Vectors

`tools/gen/drip-vectors.py` writes them (standard library only, no engine, no
pack file read; `--check` compares with the tree). Every input is a message the
program builds field by field; none is taken from a document.

| File | Shows |
|---|---|
| `01-link-roundtrip` | a Link with null padding to whole pages: every list; the padding is not written back |
| `02-link-cut-short-is-malformed` | input shorter than the Length octet states: `malformed-wire` |
| `03`, `04` | a Wrapper of a Basic ID and a Location message at 47.5 N 122.25 W, 1524 m (`wrapper-2-location-2`): round trip, and to `geojson` with the expected text written by hand |
| `05` | a Wrapper of four messages and no Location message (`wrapper-4`) |
| `06` | a Wrapper with no message, for extended transports (`wrapper-0`) |
| `07`, `08` | Manifests with no and with three message hashes (`manifest-0`, `manifest-3`) |
| `09` | a Wrapper of a Location message in place 1 and a System message, null padded (`wrapper-2-location-1`) |
| `10` | SAM Type 2 with 100 octets of data, no whole count of messages: `no-kind` |
