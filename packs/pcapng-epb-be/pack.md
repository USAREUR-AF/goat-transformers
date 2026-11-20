# Pack: pcapng-epb-be

The fixed part of a pcapng Enhanced Packet Block in a big-endian section, as
the IETF Internet-Draft draft-ietf-opsawg-pcapng-06 section 4.3 lays it out:
28 octets. Public. Written by hand from the draft; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `pcap` (`model/pcap.def`).

## Message convention

A message is one enhanced packet block. The pack reads its first 28 octets;
the packet data, padding, options and the trailing block total length are read
over and not written (vector 01). A block does not state its byte order: its
section header block does (`pcapng-section-header`), and the caller picks this
pack for a big-endian section and `pcapng-epb-le` for the other.

| Octets | Field | Key |
|---|---|---|
| 0-3 | block type, 6 | common `when`; kind `enhanced-packet` |
| 4-7 | block total length | `pcap.pcapng_block_total_length` |
| 8-11 | interface ID | `pcap.pcapng_interface_id` |
| 12-15 | timestamp, upper 32 bits | `pcap.pcapng_ts_high` |
| 16-19 | timestamp, lower 32 bits | `pcap.pcapng_ts_low` |
| 20-23 | captured packet length | `pcap.pcap_caplen` |
| 24-27 | original packet length | `pcap.pcap_origlen` |

The fields are big-endian.

## Shared keys

None. The timestamp is not bound to `time_ms`: its unit is set by the
interface description block's options (microseconds when none is given), which
this block does not carry.

## Not mapped, and why

- Packet data (padded to 32 bits), options, and the trailing block total
  length: the data runs `caplen` octets and the options to the block end.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a block with its
data and trailer, block type 1 (`no-kind`), and 27 octets (`malformed-wire`).
