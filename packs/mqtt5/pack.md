# Pack: mqtt5

An MQTT 5.0 control packet (OASIS standard): the fixed header, every packet type and their
properties. Wire `bits`, `layout sequential`, most significant bit first, big-endian. One kind per
packet type, chosen by the high four bits of the first octet. Input and output are hex. Licensed
under the OASIS notice (PROVENANCE.md). Written by `tools/gen/messaging-pack.py`.

## What is mapped

The packets of MQTT 3.1.1 (see `mqtt311`) with the changes of 5.0: protocol level 5, clean start,
the subscription options of SUBSCRIBE (retain handling, retain as published, no local, QoS),
reason codes, the AUTH packet (15), and properties.

**Properties.** A property list is its length (a Variable Byte Integer) and the properties: each an
identifier and a value of the type 5.0 gives it: one octet (identifiers 1, 23, 25, 36, 37, 40, 41,
42), two (19, 33, 34, 35), four (2, 17, 24, 39), a Variable Byte Integer (11, the subscription
identifier, as its parts), a UTF-8 string (3, 8, 18, 21, 26, 28, 31), binary data (9, 22) or a string
pair (38, the user property). An identifier 5.0 does not define ends the reading of the list; it and
the rest are kept as octets. When the list's length is one octet (lists of up to 127 octets) its 7
bits are a `length 7 bytes` block. **A longer list cannot be bounded**: its length is a Variable
Byte Integer of two or more octets, whose value no `length` line can take; the pack then keeps the
rest of the packet, from the length's second octet, as octets (`mqtt.packet_rest`), so the packet
round-trips without its properties and payload laid out.

**Optional parts.** PUBACK, PUBREC, PUBREL and PUBCOMP omit the reason code at Remaining Length 2
and the properties below 4; DISCONNECT and AUTH omit both at Remaining Length 0 and the properties
at 1. The pack chooses by the Remaining Length when that takes one octet (a `switch` on
`remaining_length_v0`).

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

None.

## Not mapped

- Property lists of more than 127 octets and what follows them (above).
- The payload and every string, as octets.

## Vectors

`tools/gen/messaging-vectors.py` builds each packet from its own restatement of the standard and
derives `expect` without an engine: CONNECT with properties, a will with will properties and a user
name; CONNACK with four properties; PUBLISH with a topic alias, a two-octet subscription identifier
and correlation data; the three forms of PUBACK and PUBREC; SUBSCRIBE with every option; SUBACK,
UNSUBSCRIBE, UNSUBACK; the three forms of DISCONNECT; AUTH; a PUBLISH whose properties take 156
octets (kept as octets); PINGRESP.

## Kind on encode from another format

The kind is the one whose value `mqtt.packet_type` holds (the packet type, `when ... as`), and
its `requires` line names the fields that kind always has.
An entity that fits no kind is `no-kind`.
