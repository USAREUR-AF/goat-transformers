# Pack: sflow5-datagram

An sFlow® version 5 datagram, as the sFlow® Version 5 specification of sflow.org states it
(`sflow_version_5.txt`, July 2004): the UDP payload an sFlow® agent sends to a collector. Wire
`bits`, `layout sequential`, most significant bit first. The datagram is XDR (RFC 4506): big-endian
32-bit units, and opaque data padded with zero octets to a multiple of 4 (an `align 32` line after
each opaque block). One kind, `datagram`. Input and output are hex.

**Licence.** The specification is used under the sFlow® License Agreement of InMon Corp.
(`LICENSES/LicenseRef-sFlow-License.txt`, label `LicenseRef-sFlow-License`). Section 2.3 of the
agreement binds a licensee's products that implement the specification: they must adhere to it
fully and identify themselves with the sFlow® mark. **This pack is not a complete
implementation**; the tables below say which structures it lays out and which it does not. A
product built on it is the licensee's to bring into line with the agreement.

## What the pack implements

| Structure (specification name) | Data format | Read as |
|---|---|---|
| `sample_datagram_v5` header | version 5 | the kind's `when`; agent address (type, then IPv4 or IPv6 by a `switch`; type 0 has no address), sub-agent ID, sequence number, uptime, the samples (a count of 32 bits) |
| `sample_record` | any | the data format (`sflow.sample_type`: enterprise × 4096 + format), then the opaque sample data (a `length 32 bytes` block and `align 32`), laid out by a `switch` on the format |
| `flow_sample` | 0:1 | sequence number, source (8-bit type, 24-bit index), sampling rate, sample pool, drops, input and output interface (2-bit format, 30-bit value), the flow records |
| `counters_sample` | 0:2 | sequence number, source, the counter records |
| `flow_sample_expanded` | 0:3 | as `flow_sample`, with a 32-bit source type and index and 32-bit interface format and value |
| `counters_sample_expanded` | 0:4 | as `counters_sample`, with a 32-bit source type and index |
| `flow_record` | any | the data format (`sflow.flow_format`), then the opaque record, laid out by a `switch` |
| `sampled_header` (raw packet header) | 0:1 | header protocol, frame length, octets stripped, the header octets (one item of `sflow.header_octets` per octet) |
| `sampled_ipv4` | 0:3 | IP length, protocol, source and destination address, ports, TCP flags, type of service |
| `sampled_ipv6` | 0:4 | as IPv4, with 128-bit addresses (eight 16-bit groups each) and the priority |
| `counter_record` | any | the data format (`sflow.counter_format`), then the opaque record, laid out by a `switch` |
| `if_counters` (generic interface counters) | 0:1 | all nineteen counters, the 64-bit ones (speed, octets in and out) included |
| `ethernet_counters` | 0:2 | all thirteen counters |

## What it does not implement

- **Every other sample format**, among them every vendor's (enterprise other than 0): the sample
  data is kept octet by octet as items of `sflow.sample_octets`, so a datagram still round-trips,
  but nothing in it is laid out.
- **Every other flow record**: the sampled Ethernet frame data (0:2), and the extended records
  (0:1001 switch, 0:1002 router, 0:1003 gateway with its AS path, 0:1004 user, 0:1005 URL, 0:1006
  MPLS, 0:1007 NAT, 0:1008 MPLS tunnel, 0:1009 MPLS VC, 0:1010 MPLS FEC, 0:1011 MPLS LVP FEC,
  0:1012 VLAN tunnel): kept as octets (`sflow.record_octets`).
- **Every other counter record**: Token Ring (0:3), 100BaseVG (0:4), VLAN (0:5) and processor
  (0:1001) counters, and every vendor's: kept as octets.
- **The structures defined by the later sFlow® extension documents** (host, application,
  tunnel and other structures published on sflow.org after version 5): kept as octets where they
  appear as records.
- **The meaning of values**: the interface format and value, the data source type, the header
  protocol and the interface status bits are kept as the integers on the wire.
- **Agent behaviour**: sampling, counter polling, the sFlow® MIB and the datagram transport
  (UDP port 6343) are outside a message pack.

## Shared keys

None. The datagram carries the agent's uptime in milliseconds, not a date, so there is no
`time_ms`; the agent address identifies a device, but the specification gives it no meaning as
a stable identity apart from the sub-agent, so `uid` is not bound. The sampled IPv4 and IPv6 data
are items of nested lists (samples, then flow records) and stay keys of the `sflow` module.

## Not mapped

- **Opaque bytes** (the raw packet header, and every structure above that the pack does not lay
  out) are a list of 8-bit items: the pack language has no transform for a run of bytes on the
  `bits` wire. Needed: an opaque or hex transform whose length comes from a `length` field.

## Vectors

`tools/gen/flows-vectors.py` builds each datagram from its own restatement of the XDR in section
5 of the specification and derives `expect` without an engine: an IPv4 agent with a flow sample
(raw header of 18 octets padded to 20, IPv4 data, and an extended switch record kept as octets),
a counter sample (generic and Ethernet counters) and a vendor sample kept as octets; an IPv6
agent with an expanded flow sample (IPv6 data, a discarded packet) and an expanded counter
sample; version 4 in place of 5 (`no-kind`); a truncated datagram (`malformed-wire`).
