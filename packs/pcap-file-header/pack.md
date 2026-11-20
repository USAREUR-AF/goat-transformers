# Pack: pcap-file-header

The 24-octet header at the start of a pcap capture file, as the IETF
Internet-Draft draft-ietf-opsawg-pcap-09 section 4 lays it out. Public. Written
by hand from the draft; the layout is stated in this repository's words. I/O is
hex text. Needs engine version 0.5 (`swap`).

Uses the modules `core` and `pcap` (`model/pcap.def`).

## Message convention

A message is the file header, the first 24 octets of the file. The packet
records after it are the packs `pcap-record-be` and `pcap-record-le`.

The writer stores every field in its own byte order; the magic number shows
which, and whether timestamps are in microseconds or nanoseconds:

| Kind | Magic octets | Order | Timestamp fraction |
|---|---|---|---|
| `big-endian-microseconds` | a1 b2 c3 d4 | big-endian | microseconds |
| `big-endian-nanoseconds` | a1 b2 3c 4d | big-endian | nanoseconds |
| `little-endian-microseconds` | d4 c3 b2 a1 | little-endian | microseconds |
| `little-endian-nanoseconds` | 4d 3c b2 a1 | little-endian | nanoseconds |

| Octets | Field | Key |
|---|---|---|
| 4-5 | major version | `pcap.pcap_version_major` |
| 6-7 | minor version | `pcap.pcap_version_minor` |
| 8-11 | reserved 1 | `pcap.pcap_reserved1` |
| 12-15 | reserved 2 | `pcap.pcap_reserved2` |
| 16-19 | snapshot length | `pcap.pcap_snaplen` |
| 20-23 | FCS length (4 bits), R, P, reserved (10 bits), link type (16 bits) | `pcap.pcap_fcs_len`, `pcap.pcap_r_bit`, `pcap.pcap_p_bit`, `pcap.pcap_linktype` |

`word_bytes 1`, `bit_order msb`. In the little-endian kinds every multi-octet
field has the option `swap`. The last word's fields are numbered in the
writer's order: in a little-endian file the link type is octets 20-21
(swapped) and the FCS length, R and P are the top bits of octet 23. The 10
reserved bits are not mapped: the draft has writers set them to 0. Reserved 1
and 2 are carried, since older writers stored values there (vector 05).

## Shared keys

None.

## Not mapped, and why

- The 10 reserved bits of the link-type word (see above).
- The packet records: their byte order and timestamp unit come from this
  header, which a record does not repeat; a message of this pack is one
  header.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: the four magic
numbers with an Ethernet header, a little-endian header with an FCS length and
an old reserved value, a pcapng block type (`no-kind`), and 23 octets
(`malformed-wire`).
