# Pack: rtp-packet

An RTP packet (RFC 3550): the fixed header, the CSRC list, the header extension and the payload.
Wire `bits`, `layout sequential`, most significant bit first. No kind. Input and output are hex.
Written by `tools/gen/media-pack.py`.

## What is mapped

The fixed header on the `inet` keys of `rtp-header` (version, padding, extension, marker, payload
type, sequence number, timestamp, SSRC), so the two convert; the CSRC count is a `count` line, so the
CSRC list (`inet.rtp_csrcs`, the same list as in `rtp-header`) writes it. When the extension bit is
1, the header extension: its profile, its length in 32-bit words, and its data as hex (lengths 0 to
63 words). Then the payload as octets.

## Shared keys

None of `core` or `track`. The `inet` keys are shared with `rtp-header`.

## Not mapped

- **The extension elements** are not laid out here: the extension length counts 32-bit words, so the
  data's size is chosen by a `switch` and kept as hex. The `rtp-header-extension` pack reads the
  elements of an extension on its own.
- **Padding**: when the padding bit is 1 the last octet counts the padding octets at the end; the
  pack keeps them in the payload.

## Vectors

`tools/gen/media-vectors.py`, without an engine: a packet with two CSRCs; a packet with an extension
and padding; a cut CSRC list (`malformed-wire`).
