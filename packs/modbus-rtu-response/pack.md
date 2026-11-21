# Pack: modbus-rtu-response

A Modbus RTU response: the server address, the PDU, then the CRC-16 (a 16-bit field with `swap`: the CRC is sent low octet first); the CRC is carried as it is, not computed or checked. Wire `bits`, `layout sequential`, most significant bit first, big-endian.
No kind: the function code is a field and a `switch` on it lays out the PDU. Input and output are
hex. Written by `tools/gen/modbus-pack.py`.

A request and its response have different layouts for most function codes and nothing on the wire
says which a frame is, so requests and responses are separate packs (`modbus-rtu-request`,
`modbus-rtu-response`). Choose the pack by the direction: a client sends requests and a server responses.

**Licence.** The Modbus Organization publishes the specifications free of charge; they state no
licence, and the organization's website reserves all rights in its content. The pack is labelled
`LicenseRef-unstated` (packs/modbus-rtu-response/REUSE.toml), which keeps it out of the `open` profile until a
person resolves it. MODBUS is a registered trademark of Schneider Automation Inc.; the name is used to
name the protocol.

## What is mapped

| Code | Function | Request | Response |
|---|---|---|---|
| 1, 2 | read coils, read discrete inputs | start address, quantity | byte count (a `length` block), the coil octets |
| 3, 4 | read holding, input registers | start address, quantity | byte count, the registers |
| 5 | write single coil | output address, value | the echo |
| 6 | write single register | register address, value | the echo |
| 7 | read exception status (serial) | nothing | the status octet |
| 8 | diagnostics (serial) | sub-function, one data word | sub-function, one data word |
| 11 | get comm event counter (serial) | nothing | status, event count |
| 12 | get comm event log (serial) | nothing | byte count, status, event count, message count, the event octets |
| 15 | write multiple coils | start, quantity, byte count, coil octets | start, quantity |
| 16 | write multiple registers | start, quantity, byte count, registers | start, quantity |
| 17 | report server id (serial) | nothing | byte count, the identification octets |
| 20 | read file record | byte count, sub-requests (reference type, file, record, length) | byte count, sub-responses (their own length, reference type, the registers) |
| 21 | write file record | byte count, sub-requests with their registers (the record length is a `count` line, written from the list) | the echo |
| 22 | mask write register | address, AND mask, OR mask | the echo |
| 23 | read/write multiple registers | read start and quantity, write start and quantity, byte count, the registers to write | byte count, the registers read |
| 24 | read FIFO queue | FIFO pointer address | byte count (2 octets), FIFO count, the registers |
| 43 | encapsulated interface transport, MEI type 14 read device identification | MEI type, read device ID code, object ID | MEI type, code, conformity level, more follows, next object ID, the objects (ID, length, value octets) |

An exception response is the function code with its high bit set (129 to 171 for the codes above) and the exception code.

Any other function code is `no-kind`: an RTU frame states no length, so the data of a function code the pack does not lay out cannot be told from the CRC after it.

## Shared keys

None: Modbus carries register and coil values whose meaning is the device's.

## Not mapped

- **Diagnostics** (8) is read with one data word; sub-function 0 (return query data) may echo more
  words than one; in RTU such a frame then fails, in TCP the extra words fail too.
- **MEI type 13** (CANopen general reference) and the other MEI types are not laid out; such a frame is `no-kind`.
- Register values are raw 16-bit words; their meaning, scale and byte order within larger values are
  the device's.
- The ASCII serial mode is not this pack.

## Vectors

`tools/gen/modbus-vectors.py` builds each frame from its own restatement of the specifications
and derives `expect` without an engine; the CRC of each RTU frame is computed there.
