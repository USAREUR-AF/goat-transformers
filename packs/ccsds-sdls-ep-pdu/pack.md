# Pack: ccsds-sdls-ep-pdu

A CCSDS SDLS Extended Procedures PDU (355.1-B-1 section 5): the commands and replies of key
management, security association management and security monitoring and control. Wire `bits`,
`layout sequential`, most significant bit first. No kind: the layout is chosen by nested `switch`
blocks on the tag. Input and output are hex; one message is one PDU. Written by
`tools/gen/sdls-ep-pack.py`.

## What is mapped

The tag (procedure type, user flag, service group, procedure identification) and the data field
length, which counts **bits** (a `length 16 bits` block, written on encode). Then the data field:

| Service group, procedure | Data field |
|---|---|
| SA management (1 or 2): Start SA (11) | SPI, then the global VC or MAP identifiers (32 bits each, 5.5.1.2.2.2 b; their encoding is mission-specific) to the end |
| Stop (14), Expire (9), Delete SA (4); Read ARSN command (0); SA Status Request command (15) | SPI |
| SA Status Request reply (15) | SPI, the last state transition directive |
| Create SA (1) | SPI, encryption and authentication flags, the IV, SN and PL field lengths, the MAC field length, then the rest as octets |
| Rekey SA (6), Set ARSN (10), Set ARSN window (5) | SPI, then the rest as octets |
| Key management (0): Key Inventory reply (7) | the number of key IDs, then the pairs as octets |
| Monitoring and control (3): Ping (1), Alarm Flag Reset (7) | none |
| Self-Test reply (5) | the result bit and the 7 implementer bits |
| any other, and every user-defined procedure | octets |

## Shared keys

None.

## Not mapped

- **Fields of managed length**: key IDs, challenges and responses (key management), the rekey and
  ARSN values (SA management), the log counters and events (monitoring and control). Their lengths
  are managed parameters, never sent; they are octets after the fields of fixed length. Needed:
  field sizes from a profile parameter.
- **Create SA after the MAC field length**: each of the cipher suite, IV, bit mask, ARSN and ARSN
  window values is preceded by an 8-bit length, but the document does not say whether that length
  counts bits or octets, so they are octets. (A length in octets could be a `length 8 bytes` block;
  in bits, `length 8 bits`.)
- **The Read ARSN reply**: its text lists the ARSN value alone while its figure shows the SPI before
  it; the data is octets.
- How a PDU is carried (a space packet on a dedicated APID, or a frame on a dedicated VC) is outside
  this message.

## Vectors

`tools/gen/sdls-ep-vectors.py`, without an engine: Start SA; Stop SA; Create SA; SA Status reply; Key
Inventory reply; Ping; a failed Self-Test reply; a user-defined procedure; OTAR; Read ARSN command; a
cut data field (`malformed-wire`).
