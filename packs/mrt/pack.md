# mrt

One BGP MRT record (RFC 6396), as a route collector writes it in a table dump or an update
file: the common header and the message, for the types TABLE_DUMP_V2 (13), BGP4MP (16) and
BGP4MP_ET (17), with the additional-path subtypes of RFC 8050. Wire `bits`, `layout
sequential`, `bit_order msb`; I/O is hex text. The pack and `model/mrt.def` are written by
`tools/gen/mrt-pack.py` from one statement of each layout; the vectors by
`tools/gen/logs-vectors.py`, with an MRT encoder of its own. Licence: Apache-2.0 (the RFCs are
restated; PROVENANCE.md).

## Kinds

Every kind starts with `when 16 <type>` and `when 16 <subtype>`; then `length 32 bytes` holds
the message.

| Type | Subtypes (kind names) | Message |
|---|---|---|
| 13 TABLE_DUMP_V2 | 1 `peer-index-table` | collector BGP ID, view name (octets), peers: type, BGP ID, IPv4 or IPv6 address, AS of 2 or 4 octets, chosen by the peer type (`switch`) |
| 13 | 2, 3, 4, 5 `rib-ipv4-unicast`, `-multicast`, `rib-ipv6-unicast`, `-multicast`; 8 to 11 the same with `-addpath` | sequence number, prefix, RIB entries: peer index, originated time, path identifier (add-path only), path attributes |
| 16 BGP4MP, 17 BGP4MP_ET | 0 `state-change`, 5 `state-change-as4` | peer and local AS (2 or 4 octets), interface index, address family, the two addresses (IPv4 or IPv6, `switch`), old and new state |
| 16, 17 | 1 `message`, 4 `-as4`, 6 `-local`, 7 `-as4-local`, 8 to 11 the same with `-addpath` | the same header, then the BGP message: marker, length, type; OPEN, UPDATE, NOTIFICATION and KEEPALIVE are read, another type is kept as octets |

Kind names carry the type: `table-dump-v2-…`, `bgp4mp-…`, `bgp4mp-et-…`. BGP4MP_ET adds the
microseconds before the rest of the message.

## How the variable parts are read

- **A prefix** (RIB records, withdrawn routes and NLRI of an UPDATE) is its length in bits and
  as many whole octets as that length needs. `switch mrt.prefix_length` has a case per octet
  count (0 to 16), each reading that many `mrt.prefix_octet_<n>` keys.
- **Path attributes**: flags (four one-bit keys and the four unused bits), type code, then a
  length of one octet, or two when the extended-length flag is set (`switch`), and a `length`
  block holding the value. ORIGIN, AS_PATH (segments, each a type and a counted list of AS
  numbers), NEXT_HOP, MULTI_EXIT_DISC and LOCAL_PREF are read; any other attribute
  (COMMUNITIES, MP_REACH_NLRI, ...) is a list of octets.
- **AS number size** follows RFC 6396: 4 octets in TABLE_DUMP_V2 and in the `-as4` subtypes,
  2 octets in BGP4MP_MESSAGE and its `-local` and `-addpath` forms.
- **Lists to the end of their extent** (`rest`, spec 0.21): the view name, attributes, AS path
  segments, withdrawn routes, NLRI and kept octets. Counted lists (peers, RIB entries, AS
  numbers) use the count before them.
- **Addresses** are unsigned integers: an IPv4 address in one key, an IPv6 address in two keys of
  64 bits (`uint` at 64 bits reads a set top bit as a negative integer, ruling 2 of 0.5).

## Shared-model keys

| Key | Field | Evidence |
|---|---|---|
| `time_ms` | Timestamp of the common header, `uiscale:1000` | RFC 6396 section 2: the timestamp is the number of seconds, leap seconds excluded, since midnight UTC at the start of 1970 ("UNIX time"); the RFC does not say which event it marks. Seconds times 1000 are `time_ms` |

`time_ms` holds whole seconds. In BGP4MP_ET records the microseconds after them are the raw key
`mrt.microseconds`: `time_ms` is bound on the header line, before the kind is known, and no
`derive` adds a key into one already decoded, so the sub-second part is not added. On encode
from another format, `time_ms` is divided by 1000 and rounded half away from zero.

Nothing else is bound: no MRT record holds a position, and addresses, AS numbers and prefixes
have no shared key.

## Not mapped

- TABLE_DUMP (12) and the other deprecated types, RIB_GENERIC (6, 12), and the ISIS and OSPF
  types: `no-kind`.
- The value of path attributes other than the five above, the OPEN optional parameters and
  the NOTIFICATION data: kept as octets.
- IPv6 and other multiprotocol routes inside MP_REACH_NLRI and MP_UNREACH_NLRI: kept as octets.
- A file of records: one vector is one record. The records of a file follow one another, each
  with its own length.

## Vectors

| File | Shows |
|---|---|
| `01-peer-index-table-roundtrip.json` | a peer index table with two peers, IPv4 with a 2-octet AS and IPv6 with a 4-octet AS |
| `02-rib-ipv4-unicast-roundtrip.json` | a RIB record with the five read attributes, one with the extended-length flag, and COMMUNITIES as octets |
| `03-rib-ipv6-unicast-roundtrip.json` | two RIB entries, an AS_SET segment, MP_REACH_NLRI as octets |
| `04-rib-ipv4-unicast-addpath-roundtrip.json` | two paths of one prefix told apart by their path identifiers |
| `05-state-change-as4-roundtrip.json` | a session that reaches Established |
| `06-et-message-as4-update-roundtrip.json` | BGP4MP_ET: microseconds, an UPDATE with withdrawn routes, attributes and three announced prefixes |
| `07-message-open-roundtrip.json` | an OPEN |
| `08-message-as4-addpath-roundtrip.json` | path identifiers before each withdrawn and announced prefix |
| `09-message-2-octet-as-path-roundtrip.json` | an AS_PATH of 2-octet AS numbers |
| `10-message-keepalive-roundtrip.json`, `11-message-notification-roundtrip.json` | a KEEPALIVE and a NOTIFICATION |
| `12-state-change-to-geojson.json` | the record time reaches a GeoJSON Feature as `time_ms` |
| `13-table-dump-v1-is-no-kind.json` | type 12: `no-kind` |
| `14-input-shorter-than-its-length.json` | the input ends before the stated length: `malformed-wire` |
