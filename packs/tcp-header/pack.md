# Pack: tcp-header

The fixed part of the TCP header, the first 20 octets of a segment, as IETF
RFC 9293 section 3.1 lays it out. Public. Written by hand from the RFC; the
layout is stated in this repository's words. I/O is hex text. Needs engine
version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is a TCP segment from its first octet. The pack reads octets 0-19.
Options (present when the data offset is more than 5) and the data are read over
on decode and not written on encode (vector 03). The checksum is carried as a
value; the pack does not compute or check it.

| Bits | Field | Key |
|---|---|---|
| 0-15 | source port | `inet.src_port` |
| 16-31 | destination port | `inet.dst_port` |
| 32-63 | sequence number | `inet.tcp_seq` |
| 64-95 | acknowledgment number | `inet.tcp_ack` |
| 96-99 | data offset (32-bit words) | `inet.tcp_data_offset` |
| 100-103 | reserved | `inet.tcp_reserved` |
| 104-111 | control bits CWR, ECE, URG, ACK, PSH, RST, SYN, FIN | `inet.tcp_cwr` … `inet.tcp_fin` (the ACK bit is `inet.tcp_ack_flag`) |
| 112-127 | window | `inet.tcp_window` |
| 128-143 | checksum | `inet.tcp_checksum` |
| 144-159 | urgent pointer | `inet.tcp_urgent_pointer` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian.

## Shared keys, with evidence

No field is bound to `core` or `track`.

| Key | Also in | Evidence |
|---|---|---|
| `inet.src_port`, `inet.dst_port` | `udp-header` | RFC 9293 section 3.1 gives the source and destination port numbers as 16-bit fields; RFC 768 gives UDP's the same meaning; both draw on the one IANA port number registry. |

## Not mapped, and why

- Options (maximum segment size, window scale, timestamps and the rest): their
  number varies with the data offset.
- The data.

## Vectors

`tools/gen/ietf-headers-vectors.py`, from values chosen there: a SYN round trip
with a checksum computed over an IPv4 pseudo header, every bit set, a SYN with a
maximum segment size option, a conversion to `udp-header`, and 19 octets
(`malformed-wire`).
