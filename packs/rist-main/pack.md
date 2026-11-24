# Pack: rist-main

A RIST main profile tunnel packet (VSF TR-06-2:2024): the GRE header with the RIST version, the VSF
protocol header, and the reduced overhead data, keep-alive and full datagram payloads. Wire `bits`,
`layout sequential`, most significant bit first. No kind. Input and output are hex; one message is
one UDP payload of the tunnel. Written by `tools/gen/media-pack.py`.

## What is mapped

**The GRE header** (RFC 2784 and RFC 2890) on the `inet` keys of `gre-header`, so the two convert:
the C bit and the K and S bits (`presence` bits), the reserved bits that RIST divides into five
reserved bits, the AES key length flag H and the RIST version RV (`rist.reserved0_high`, `rist.h`,
`rist.rv`), the GRE version, the protocol type, and the checksum, key (the pre-shared key nonce) and
sequence number when their bits are set.

**The payload by protocol type**:

| Protocol type | Read as |
|---|---|
| 0xCCE0, the VSF EtherType | VSF protocol type and subtype; subtype 0: the reduced UDP header (source and destination port) and the payload; subtype 0x8000: the keep-alive (below); other subtypes as octets |
| 0x88B6 (legacy reduced overhead) | the reduced UDP header and the payload |
| 0x88B5 (legacy keep-alive) | the keep-alive |
| any other (0x0800: a full IPv4 datagram) | the datagram as octets |

**The keep-alive**: the sender's MAC address (`hex`), the capability flags X, R, B, A, P, E, L, N,
the disconnect and reconnect flags D and T, the capabilities V, J, F, three reserved bits, and the
JSON payload as octets.

## Shared keys

None.

## Not mapped

- **The payload** of a reduced overhead packet and of a full
  datagram is octets; with a pre-shared key it is ciphertext.
- **The JSON keep-alive payload** is octets: the `bits` wire has no text transform whose length the
  end of the packet gives.
- DTLS-protected tunnels (TR-06-2 section 6) carry DTLS records, not this layout.
- The future nonce announcement (subtype 0x8001) is octets.

## Vectors

`tools/gen/media-vectors.py`, without an engine: reduced overhead with a sequence number; a
keep-alive with capabilities and JSON; the legacy reduced overhead and keep-alive encapsulations; a
full datagram with key and sequence; a cut GRE header (`malformed-wire`).
