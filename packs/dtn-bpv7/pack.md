# Pack: dtn-bpv7

A bundle of the Delay-Tolerant Networking Bundle Protocol, version 7 (IETF RFC
9171). Public. Written from the RFC only (PROVENANCE.md). Input and output are
hex text (`spec/engine-spec.md`, Version 0.28, the `cbor` wire). The pack
needs engine version 0.28.

Uses the module `bpv7` (`model/bpv7.def`). It binds no key of `core` or
`track` (see "Shared keys").

## Message convention

A message of this pack is one bundle, exactly as RFC 9171 section 4.1 states
it:

1. a CBOR array of blocks. The RFC requires the array to be of indefinite
   length (head `9f`, closed by the break `ff`); the pack also reads a
   definite-length array;
2. element 0, the primary block: an array of 8, 9, 10 or 11 elements
   (section 4.3.1);
3. elements 1 and on, the canonical blocks: each an array of 5 elements, or 6
   with a CRC (section 4.3.2). The last one is the payload block (block type
   1).

No byte comes before or after the bundle: no convergence-layer framing and no
tag. A tag on the bundle, such as the self-described CBOR tag 55799, is passed
over on decode and not written (0.28, "Tags").

**Output.** The `cbor` wire writes the core deterministic encoding of RFC 8949
section 4.2.1, every length definite (0.28, "Writing a message", step 1). So
the outer array comes out with a definite-length head (`82`, `83`, ...) and no
break, even when the input used `9f ... ff`. The output is not a conforming
bundle: RFC 9171 section 4.1 requires the indefinite-length array. That
section allows a receiver to accept and convert a fixed-length array, but does
not require it. A consumer that sends the output on to a bundle agent rewrites
the outer head as `9f` and appends `ff`. Each block inside the array is
written back byte for byte when its input was in the core deterministic
encoding, so the block CRCs computed over those bytes stay valid. This holds
for the primary block (mapped fields) and for the canonical blocks (residue).
When an input block used longer heads or indefinite lengths, its re-encoded
bytes differ and its CRC no longer matches (0.28, ruling 1).

## Kinds

What lies at some positions of the primary block depends on two things that a
`when` line can test:

- **Fragment or not.** Element 8 is the fragment offset in a fragment and the
  CRC otherwise. Element 9 (total application data unit length) exists only
  in a fragment, so `when [0].[9] present` tells a fragment apart.
- **The scheme of each endpoint ID.** An endpoint ID is a 2-element array:
  the URI scheme code, then the scheme-specific part (SSP), whose type depends
  on the scheme (see "Endpoint IDs").

The four kinds, in pack order (decode takes the first that holds):

| Kind | `when` | Primary block elements mapped by the kind |
|---|---|---|
| `fragment-ipn` | `[0].[9] present`; scheme code 2 at `[0].[3].[0]`, `[0].[4].[0]`, `[0].[5].[0]` | the node and service numbers of all three endpoint IDs; 8 fragment offset; 9 total length; 10 CRC |
| `fragment` | `[0].[9] present` | 8 fragment offset; 9 total length; 10 CRC |
| `ipn` | scheme code 2 at all three endpoint IDs | the node and service numbers; 8 CRC |
| `whole` | none | 8 CRC |

Each kind also has the common lines. On encode, an entity that carries no kind
of this format gets the first kind whose `requires` keys it has.
`fragment-ipn` and `fragment` require `bpv7.total_adu_length`, which is mapped
at the path that `when [0].[9] present` tests (ruling 27 of 0.5). The `ipn`
kinds require the six node and service keys. A common `when [0].[0] 7`
rejects any other version with `no-kind`, and writes 7 on encode.

## Mapping

Every key is a raw key of `bpv7`. Positions are counted from 0. `[0].[i]` is
element `i` of the primary block. The transform is `uint` (an unsigned CBOR
integer) unless the table says otherwise.

| Path | Key | Kinds | RFC 9171 |
|---|---|---|---|
| `[0].[0]` | `bpv7.version` | all | 4.3.1 Version: an unsigned integer; 7 for this document (9.2) |
| `[0].[1]` | `bpv7.bundle_flags` | all | 4.2.3: an unsigned integer used as a bit field, bit 0 the low-order bit |
| `[0].[2]` | `bpv7.primary_crc_type` | all | 4.2.1: 0 none, 1 CRC-16 (X.25), 2 CRC-32C |
| `[0].[3].[0]` | `bpv7.dst_scheme` | all | 4.2.5.1: an endpoint ID is a 2-element array, the first element the URI scheme code (9.6: 1 dtn, 2 ipn) |
| `[0].[4].[0]` | `bpv7.src_scheme` | all | as above, for the source node ID (4.2.5.2: a node ID is an endpoint ID) |
| `[0].[5].[0]` | `bpv7.rpt_scheme` | all | as above, for the report-to endpoint ID |
| `[0].[3].[1].[0]`, `[0].[3].[1].[1]` | `bpv7.dst_ipn_node`, `bpv7.dst_ipn_service` | `fragment-ipn`, `ipn` | 4.2.5.1.2: the SSP of the ipn scheme is a 2-element array of unsigned integers, the node number then the service number |
| `[0].[4].[1].[0]`, `[0].[4].[1].[1]` | `bpv7.src_ipn_node`, `bpv7.src_ipn_service` | `fragment-ipn`, `ipn` | as above |
| `[0].[5].[1].[0]`, `[0].[5].[1].[1]` | `bpv7.rpt_ipn_node`, `bpv7.rpt_ipn_service` | `fragment-ipn`, `ipn` | as above |
| `[0].[6].[0]` | `bpv7.creation_time_dtn_ms` | all | 4.2.7 and 4.2.6: the first element of the creation timestamp is a DTN time, milliseconds since 2000-01-01 00:00:00 UTC; 0 means unknown |
| `[0].[6].[1]` | `bpv7.creation_seq` | all | 4.2.7: the second element, a sequence number |
| `[0].[7]` | `bpv7.lifetime_ms` | all | 4.3.1 Lifetime: milliseconds past the creation time |
| `[0].[8]` | `bpv7.fragment_offset` | `fragment-ipn`, `fragment` | 4.3.1: present if and only if the fragment flag is set |
| `[0].[9]` | `bpv7.total_adu_length` | `fragment-ipn`, `fragment` | 4.3.1: present if and only if the fragment flag is set |
| `[0].[8]` (`bytes`) | `bpv7.primary_crc` | `ipn`, `whole` | 4.3.1 and 4.2.2: the last element when the CRC type is not 0; a byte string of 2 or 4 bytes |
| `[0].[10]` (`bytes`) | `bpv7.primary_crc` | `fragment-ipn`, `fragment` | as above, after the two fragment elements |

A primary block with CRC type 0 has no CRC element. Then `bpv7.primary_crc`
is absent, and encode writes 8 elements (10 in a fragment).

### Shared keys

None is bound. The candidates, and why each is left raw:

| Wire field | Model key considered | Reason not bound |
|---|---|---|
| creation time (`[0].[6].[0]`) | `time_ms` | `time_ms` counts from 1970-01-01, and DTN time from 2000-01-01 (4.2.6). The `cbor` wire has no transform that adds the 946684800000 ms between the two epochs (`epoch_s` takes seconds since 1970). A `derive` in the module would assert a meaning that the RFC leaves open: 4.2.6 says that DTN time "is not affected by leap seconds", which can be read as an elapsed count, differing from a 1970-based civil count by the leap seconds since 2000. Also, 0 means "unknown" and would derive a false instant. |
| lifetime (`[0].[7]`) | `stale_ms` | `stale_ms` is an instant; the lifetime is a duration after the creation time, so `stale_ms` would need the creation time converted first (above). |
| source node ID with the creation timestamp | `uid` | 4.2.7: a bundle is identified by the source node ID together with the creation timestamp, and in a fragment also by the offset and length. No single field is the identifier, and `join` would need text forms of the endpoint IDs that the wire does not hold. |
| a dtn endpoint name | `callsign` | it names an endpoint of the network, not the reported entity, and the dtn SSP is not mapped (below). |

So a conversion to another format carries nothing. `dtn-bpv7` to `geojson`
gives a Feature with no geometry and no properties. From another format, an
entity has no `bpv7` key, so the `whole` kind is chosen and only the common
`when` is written: the array `[[7]]`, which is not a bundle. The pack exists
for decoding, inspecting and round-tripping bundles under the same model as
the other formats, and to show what 0.28 can and cannot state about a
deployed CBOR protocol.

## Not mapped

All of the following is residue: keyed by its path, kept as the hex of its
item, and written back on a same-format round trip (0.28, "Residue").

- **The scheme-specific part of an endpoint ID in the `fragment` and `whole`
  kinds** (`[0].[3].[1]`, `[0].[4].[1]`, `[0].[5].[1]`). Its type depends on
  the scheme code beside it. For the dtn scheme (4.2.5.1.1) it is a text
  string, or the unsigned integer 0 for `dtn:none`. For the ipn scheme
  (4.2.5.1.2) it is an array of two unsigned integers. For any other scheme
  it is whatever that scheme defines. A `text` line on a `dtn:none` SSP fails
  the decode (`transform-decode`), and a position step through a text SSP is
  `malformed-wire` (0.28, step 8), so the line must sit in a kind that is
  chosen only when the item has the right type. A `when` can test the scheme
  code, and can test for the integer 0, but it cannot test that an item is a
  text string. And the three endpoint IDs vary independently. Mapping the dtn
  SSPs safely needs a kind for each combination, with `dtn:none` caught before
  the text kinds: 6 kinds for each fragment state, 12 in all. The pack maps
  the one combination that needs no such guard: all three endpoint IDs ipn.
  Every other bundle keeps its SSPs byte-exact as residue. An ipn endpoint ID
  in a bundle whose other endpoint IDs are not all ipn is residue too.
- **The canonical blocks and the payload block** (`[1]`, `[2]`, ...). Each is
  residue whole, re-encoded under the core deterministic encoding. A 0.28
  `group` cannot list them:
  - `group <list> .` takes every element of the top array, the primary block
    included (0.28, "Paths"; 0.7). A body for the canonical layout (`[0]`
    type, `[1]` number, `[2]` flags, `[3]` CRC type, `[4]` data, `[5]` CRC)
    read against the primary block finds an endpoint-ID array at `[3]`, and
    `uint` refuses it (`transform-decode`).
  - In the same scope, every `[0].[i]` line is "at or under" the group's path
    `.` and is `bad-directive` (0.28, "Types", and ruling 13). The group and
    the primary-block fields exclude each other.
  - Lines at fixed positions (`[1].[0]`, `[2].[0]`, ...) would name a block
    by its place in the bundle. The RFC fixes no place except "payload last"
    (4.1), and 0.28 has no step for the last element.
- **Block-type-specific data.** In a canonical block this is a byte string
  (4.3.2). For the extension blocks of 4.4 (previous node, bundle age, hop
  count) the bytes hold a further CBOR item. The `cbor` wire reads a byte
  string only as hex (`bytes`) and has no step into an encoded item inside
  one.
- **The bits of the bundle processing control flags.** They are carried as
  one integer. The `cbor` wire has no transform that takes a bit range of an
  integer.

### Limitations

- **CRCs are carried, not checked or computed.** The CRC-16 (X.25) and
  CRC-32C of a primary or canonical block (4.2.1, 4.2.2) cover the encoded
  block with the CRC bytes set to zero. The `cbor` wire has no checksum
  directive, so a bundle with a wrong CRC decodes without error. An entity
  whose primary-block fields are changed and then encoded keeps the old
  `bpv7.primary_crc`, which no longer matches.
- **Unsigned integers above 2^63-1.** RFC 9171 allows any CBOR unsigned
  integer for node numbers, service numbers, DTN times and flags. `uint`
  yields a signed 64-bit model integer and refuses a larger item with
  `transform-decode` (0.28, "Transforms").
- **Semantic rules are not checked.** For example: the fragment flag (bit 0)
  agreeing with the block length; status-report flags being 0 for an
  anonymous source or an administrative record (4.2.3); a primary CRC type of
  0 only alongside a Block Integrity Block (4.3.1); a bundle age block when
  the creation time is 0 (4.4.2); exactly one payload block, and it last
  (4.1). A pack states layouts, not these rules.
- **Version check only.** A version other than 7 is `no-kind`. A bundle
  whose top item is not an array is `malformed-wire` (0.28, step 6).

### Language additions that would close the gaps

Candidates for the pack language, not proposals made here:

1. **A group from a position**, for example `group <list> . from [1]`: the
   elements of an array from position `i` on. With it, the canonical blocks
   would be one list, and the primary-block lines would no longer conflict
   with the group under ruling 13.
2. **A `when` on the type of an item** (text, unsigned, array) or a
   conditional block scoped to one sub-path. Either would choose the SSP
   layout of each endpoint ID on its own, without kinds for every
   combination.
3. **A step into embedded CBOR**: a byte string read as an encoded item. With
   kinds inside group items (not in 0.7), this would decode the
   block-type-specific data by block type.
4. **A checksum over an array element**: CRC-16 X.25 or CRC-32C over the
   encoded element, with the CRC element zeroed, for each block.
5. **An indefinite-length output** for one named array (the bundle), so that
   the output conforms to section 4.1.
