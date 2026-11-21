# Pack: mqtt311

An MQTT 3.1.1 control packet (OASIS standard): the fixed header and every packet type. Wire
`bits`, `layout sequential`, most significant bit first, big-endian. One kind per packet type,
chosen by the high four bits of the first octet. Input and output are hex; over TCP one message is
one packet. Licensed under the OASIS notice (PROVENANCE.md). Written by
`tools/gen/messaging-pack.py`.

## What is mapped

| Kind | Type | Read as |
|---|---|---|
| `connect` | 1 | protocol name, level, the connect flags (user name, password, will retain, will QoS, will, clean session, reserved), keep alive; the payload: client identifier, then by the flags the will topic and message, the user name, the password |
| `connack` | 2 | session present, return code |
| `publish` | 3 | the flags DUP, QoS and RETAIN, topic name, the packet identifier when QoS is above 0, the payload as octets |
| `puback`, `pubrec`, `pubrel`, `pubcomp` | 4-7 | packet identifier |
| `subscribe` | 8 | packet identifier, each topic filter with its requested QoS |
| `suback` | 9 | packet identifier, the return codes |
| `unsubscribe` | 10 | packet identifier, the topic filters |
| `unsuback` | 11 | packet identifier |
| `pingreq`, `pingresp`, `disconnect` | 12-14 | nothing after the fixed header |

The four flag bits of the fixed header are a field (`mqtt.flags`, 0 or 2 by type), except in
PUBLISH, where they are DUP, QoS and RETAIN.

**Variable Byte Integers.** The Remaining Length (and, in MQTT 5, the subscription identifier
property) is a Variable Byte Integer: one to four octets, each a continuation bit and 7 value bits,
the low group first. The `bits` wire has no transform that reads it as one integer, so the pack
states its parts: `remaining_length_c1` and `remaining_length_v0` for the first octet, and a
`switch` on each continuation bit reads the next octet (`c2`, `v1`, ...). The length is v0 + 128 v1
+ 16384 v2 + 2097152 v3. A message round-trips; but the parts are written as the entity holds them,
not computed from the packet, so an entity from another format writes a Remaining Length of 0, and
an MQTT packet edited in the model keeps its old length. The packet's end is the end of the input:
the pack does not use the Remaining Length to bound it. Needed: a Variable Byte Integer transform,
and a `length` whose field is one.

**Strings** (UTF-8 strings and binary data, each a 2-octet length and its octets) are `length 16
bytes` blocks holding a list of octets: the `bits` wire has no text transform whose length a field
gives.

## Shared keys

None: MQTT carries application messages whose content the protocol does not define.

## Not mapped

- The payload of a PUBLISH and every string, as octets (above).
- Packet type 0 and 15 are reserved in 3.1.1 (`no-kind`).

## Vectors

`tools/gen/messaging-vectors.py` builds each packet from its own restatement of the standard and
derives `expect` without an engine: one round trip per packet type (CONNECT with a will, user name
and password; PUBLISH at QoS 1 and at QoS 0 with a two-octet Remaining Length; ...), packet type 0
(`no-kind`) and a truncated PUBACK (`malformed-wire`).
