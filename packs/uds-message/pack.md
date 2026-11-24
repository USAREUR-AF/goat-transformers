# Pack: uds-message

One UDS (ISO 14229-1) message, as carried by ISO-TP or in a DoIP diagnostic message. Wire `bits`,
`layout sequential`, `bit_order msb`. No kinds: the service identifier chooses the layout. Written by
`tools/gen/vehnet-pack.py`.

## What is mapped

- **Requests with a subfunction** (0x10 session control, 0x11 ECU reset, 0x27 security access, 0x31
  routine control, 0x3E tester present): the suppress-positive-response bit and the 7-bit subfunction;
  security access then the key as octets; routine control the routine identifier and the option record.
- **0x22 read data by identifier**: the identifiers. **0x2E write**: the identifier and the record.
- **Positive responses**: 0x50 the session echoed and the session parameter record; 0x51 the reset type
  echoed and the rest; 0x62 the identifier and the record; 0x67 the level echoed and the seed; 0x6E the
  identifier; 0x71 the control type echoed, the routine identifier and the status record; 0x7E the
  subfunction echoed.
- **0x7F negative response**: the rejected service identifier and the code.
- Any other service identifier: the octets after it.

## Shared keys

None.

## Not mapped

- **P2 and P2\* as numbers**: the session parameter record is octets, because the source reads
  the timings only for the 2013 edition and later, and a field there would re-encode as zeros in a message
  without them.
- **Several identifiers in one read response**: the length of each value comes from the data
  identifier definitions, which are not part of the message; the first identifier is read and the rest
  is the data record.
- **The other services**: octets.
- **Request or response**: decided by the identifier, as on the wire; there is no direction key.

## Message convention

`input` and `expect` are lowercase hexadecimal text of one UDS message.

## Vectors

`tools/gen/vehnet-vectors.py`, without an engine: session control request and response; a suppressed
tester present; read data by identifier request (two identifiers) and response; write request; a
security access seed; routine control request and response; a negative response; a suppressed ECU
reset; a session response without the parameter record; another service as octets; a cut routine
request (`malformed-wire`).
