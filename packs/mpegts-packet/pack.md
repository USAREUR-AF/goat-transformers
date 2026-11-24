# Pack: mpegts-packet

One MPEG-2 transport stream packet of 188 octets: the header, the adaptation field and the payload.
Wire `bits`, `layout sequential`, most significant bit first. One kind, `packet`: the sync byte 0x47
is its `when`. Input and output are hex; one message is one packet. Written by
`tools/gen/media-pack.py`. The layout is restated from FFmpeg and GStreamer (PROVENANCE.md).

## What is mapped

The header: transport error indicator, payload unit start indicator, transport priority, PID (13
bits), scrambling control, adaptation field control and continuity counter.

When the adaptation field control is 2 or 3, the adaptation field (a `length 8 bytes` block): the
eight flags (discontinuity, random access, elementary stream priority, PCR, OPCR, splicing point,
transport private data, extension), then by the flags the PCR (33-bit base, 6 reserved bits, 9-bit
extension), the OPCR, the splice countdown (signed), the private data and the adaptation field
extension (each a length and octets), and the stuffing octets. When the control is 1 or 3, the
payload as octets.

## Shared keys

None. The PCR is a clock of the stream (27 MHz), not a date.

## Not mapped

- **PSI tables (PAT, PMT and the others)** are in the payload and are not laid out. A section ends
  with a 32-bit CRC after its loop of programs or streams, and its length counts that CRC: a `rest`
  list cannot stop four octets before the end of its extent. Needed: a trailer after a `rest` list
  (or a `rest` that leaves n octets).
- **PES headers** in the payload are not laid out.
- The adaptation field extension's fields (legal time window, piecewise rate, seamless splice) are
  octets.
- **An adaptation field of length 0** comes back with length 1 and a zero flags octet: on encode a
  `length` block writes every line (ruling 7 of engine-spec 0.8).
- Several packets in one message are not split: the payload of the first runs to the end of the input.

## Vectors

`tools/gen/media-vectors.py`, without an engine: payload only; a PCR with random access; an
adaptation field of stuffing only; OPCR, splice countdown, private data and extension; a missing
sync byte (`no-kind`); a cut adaptation field (`malformed-wire`). One vector (an adaptation field of
length 0) was dropped: its expectation did not follow ruling 7 (see the script).
