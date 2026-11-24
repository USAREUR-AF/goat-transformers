# Pack: rtp-header-extension

An RTP header extension in the forms of RFC 8285: the profile, the length, and the extension
elements. The message is the extension alone, from its profile to its end, as `rtp-packet` keeps it
in `rtpx.profile`, `rtpx.ext_length` and `rtpx.ext_data`. Wire `bits`, `layout sequential`, most
significant bit first. No kind. Written by `tools/gen/media-pack.py`.

## What is mapped

By the profile:

| Profile | Read as |
|---|---|
| 0xBEDE, the one-byte form | elements to the end: the ID (4 bits) and, for an ID other than 0, the length minus one (4 bits) and the data (1 to 16 octets, `hex`); an ID of 0 is a padding octet |
| 0x1000 to 0x100F, the two-byte form (the low 4 bits are application bits) | elements to the end: the ID (8 bits) and, for an ID other than 0, the length (a `length 8 bytes` block) and the data as octets; an ID of 0 is a padding octet |
| any other | the data as octets |

## Shared keys

None.

## Not mapped

- The meaning of each element is negotiated per session by its ID; the elements are kept as ID and data.
- The length field is carried, not computed from the elements.
- ID 15 in the one-byte form (reserved: stop reading) is read as an element.

## Vectors

`tools/gen/media-vectors.py`, without an engine: the one-byte form with three elements and padding,
the two-byte form with application bits, an empty element and padding, and another profile.
