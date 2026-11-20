# Pack: netflow5

A NetFlow version 5 export packet: a 24-byte header and up to 30 flow records of 48 bytes, as
Cisco documents them. Wire `bits`, `layout sequential`, most significant bit first, big-endian.
One kind, `packet`. **The source states no licence**; the pack is labelled `LicenseRef-unstated`
(PROVENANCE.md).

## What is mapped

The header: version 5 (the kind's `when`); the flow count (a `count` line: the number of items of
`ipfix.records`, written from the list on encode); system uptime; `unix_secs` and `unix_nsecs`;
the flow sequence; engine type and engine ID; the sampling field as its 2-bit mode and 14-bit
interval. All are keys of the `netflow5` module.

Each flow record is an item of `ipfix.records`. Its fields are bound to the IPFIX elements that
name the same quantity:

| Bytes | Field | Key (`ipfix.`) |
|---|---|---|
| 0-3 | srcaddr | `source_ipv4_address` (IE 8) |
| 4-7 | dstaddr | `destination_ipv4_address` (IE 12) |
| 8-11 | nexthop | `ip_next_hop_ipv4_address` (IE 15) |
| 12-13 | input | `ingress_interface` (IE 10) |
| 14-15 | output | `egress_interface` (IE 14) |
| 16-19 | dPkts | `packet_delta_count` (IE 2) |
| 20-23 | dOctets | `octet_delta_count` (IE 1) |
| 24-27 | First | `flow_start_sys_up_time` (IE 22) |
| 28-31 | Last | `flow_end_sys_up_time` (IE 21) |
| 32-33 | srcport | `source_transport_port` (IE 7) |
| 34-35 | dstport | `destination_transport_port` (IE 11) |
| 36 | pad1 | not mapped, written as zero |
| 37 | tcp_flags | `tcp_control_bits` (IE 6) |
| 38 | prot | `protocol_identifier` (IE 4) |
| 39 | tos | `ip_class_of_service` (IE 5) |
| 40-41 | src_as | `bgp_source_as_number` (IE 16) |
| 42-43 | dst_as | `bgp_destination_as_number` (IE 17) |
| 44 | src_mask | `source_ipv4_prefix_length` (IE 9) |
| 45 | dst_mask | `destination_ipv4_prefix_length` (IE 13) |
| 46-47 | pad2 | not mapped, written as zero |

Evidence: version 9 took these fields over with the same meaning (RFC 3954 section 8 gives each
its type number), and the IPFIX elements 1 to 127 are those type numbers (RFC 7012 section 4).
The sizes differ (dPkts is 4 bytes here, packetDeltaCount 8 in the IPFIX template); a value
carries as long as it fits the narrower field, else encode fails (`transform-encode`).

## Shared keys

| Field | Key | Evidence |
|---|---|---|
| unix_secs, unix_nsecs | `time_ms` | Cisco's page: the current count of seconds since 0000 UTC 1970 and the residual nanoseconds, at export. The packet is the report. The module `netflow5` derives `time_ms` from the two (`ms_of`) and the two from `time_ms` (`sec_of`, `nsec_of`), so the time converts both ways; the wire keeps nanoseconds, the model milliseconds. |

## Not mapped

- **pad1 and pad2** are written as zero.
- The page states that a packet holds 1 to 30 records; the pack reads the count as stated and
  does not refuse a count above 30.

## Vectors

`tools/gen/flows-vectors.py`, without an engine: two records (round trip); the same packet to
`ipfix-ipv4-flow` (`time_ms` from `ms_of`, then the IPFIX export time); a header with no record;
a packet whose count runs past the input (`malformed-wire`).
