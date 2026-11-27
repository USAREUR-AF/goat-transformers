# Pack: pcap-record-le

The 16-octet header of a pcap packet record in a little-endian file, as the IETF
Internet-Draft draft-ietf-opsawg-pcap-09 section 5 lays it out. Public. Written
by hand from the draft; the layout is stated in this repository's words. I/O is
hex text. Needs engine version 0.5 (`swap`).

Uses the modules `core` and `pcap` (`model/pcap.def`).

## Message convention

A message is one packet record: the header and the packet data. The pack reads
the header; the data is read over and not written (vector 01). A record does
not state its byte order or timestamp unit: the file header does
(`pcap-file-header`), and the caller picks this pack for a little-endian file and
`pcap-record-be` for the other.

| Octets | Field | Key |
|---|---|---|
| 0-3 | timestamp, seconds | `pcap.pcap_ts_sec` |
| 4-7 | timestamp, microseconds or nanoseconds | `pcap.pcap_ts_frac` |
| 8-11 | captured packet length | `pcap.pcap_caplen` |
| 12-15 | original packet length | `pcap.pcap_origlen` |

Each field has the option `swap`.

## Shared keys

None. The timestamp is not bound to `time_ms`: the fraction is microseconds
or nanoseconds as the file header's magic number says, which the record does
not carry. The seconds are since 1970-01-01 00:00:00 UTC (draft section 5). `pcap.pcap_caplen` and `pcap.pcap_origlen` are also the keys of the
pcapng enhanced packet block packs, with the same meaning.

## Not mapped, and why

- The packet data, `caplen` octets.

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a record with
its data, a record with a nanosecond fraction and a captured length larger than
the original, and 15 octets (`malformed-wire`).
