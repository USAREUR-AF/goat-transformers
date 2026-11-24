# Pack: semtech-udp-forwarder

One datagram of the Semtech UDP packet forwarder protocol (gateway and server). Wire `bits`, `layout sequential`, `bit_order msb`. No kinds: the identifier chooses the
layout. Written by `tools/gen/lpwan2-pack.py`.

## What is mapped

- **Header**: protocol version, token, identifier.
- **PUSH_DATA** (0) and **TX_ACK** (5): the gateway identifier, then the JSON object (optional in
  TX_ACK).
- **PULL_DATA** (2): the gateway identifier.
- **PULL_RESP** (3): the JSON object.
- **PUSH_ACK** (1) and **PULL_ACK** (4): nothing more.

## Shared keys

None.

## Not mapped

- **The JSON object as text or as fields** (`rxpk`, `stat`, `txpk`, `txpk_ack`): its octets, because a
  character field that runs to the end of the message is not in the pack language; the members (and the
  base64 LoRaWAN PHYPayload in `data`) would need a second pass with a JSON pack.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one UDP payload.

## Vectors

`tools/gen/lpwan2-vectors.py`, without an engine: PUSH_DATA with a stat object; PUSH_ACK; PULL_DATA;
PULL_RESP with a txpk object; PULL_ACK; TX_ACK without JSON; a cut gateway identifier
(`malformed-wire`).
