# Pack: ccsds-sdls-security-header

The CCSDS Space Data Link Security header (355.0-B-2 section 4.1.1): the SPI, then the rest of the
protected part of the frame as octets. The message begins where the security header begins in a TM,
TC, AOS or USLP frame (after the primary header and any insert zone) and runs to the end of what the
caller passes. Wire `bits`, `layout sequential`. No kind. Input and output are hex. Written by
`tools/gen/space-more-pack.py`.

## What is mapped

The security parameter index (16 bits), then the octets that follow it.

## Shared keys

None.

## Not mapped

- **The initialization vector, sequence number and pad length** follow the SPI, but each one's
  length is a managed parameter of the security association (fixed for the association, never sent
  in the frame), and so is the MAC length of the trailer. A pack reads one message, without the
  association's database, so these fields are in the octets. A mission profile with fixed lengths
  could be a pack of its own.
- **Where the header starts** depends on the frame's own managed parameters (insert zone, the
  position of the frame data field), which is why the message starts at the SPI.
- **The security trailer** (the MAC) is a trailer after the frame data: in the octets.
- The extended procedures of CCSDS 355.1 (key and SA management PDUs) are not built.

## Vectors

`tools/gen/space-more-vectors.py`, without an engine: an SPI with protected data; a cut SPI
(`malformed-wire`).
