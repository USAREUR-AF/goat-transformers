# Pack: lowpan-frame

A 6LoWPAN frame: the MAC payload of an IEEE 802.15.4 frame, with the dispatch, mesh, broadcast and
fragmentation headers of RFC 4944, the IPHC header and the NHC headers of RFC 6282, and the GHC NHC
bytes of RFC 7400. Wire `bits`, `layout sequential`, most significant bit first. No kind. Input and
output are hex. Written by `tools/gen/mesh-pack.py`.

## How the pack reads a frame

A 6LoWPAN header is named by a bit pattern at the start of an octet, and the patterns have different
widths (`00`, `01000001`, `011`, `10`, `11000`, `11100` and so on). The pack reads the pattern a bit
group at a time and chooses by nested `switch` blocks: 2 bits (`s<n>_a`), then 1 bit (`s<n>_b`, IPHC
when 1), 5 bits (`s<n>_c`, the rest of a 6-bit dispatch) or 3 bits (`s<n>_d`, the fragment headers).
The headers stack in a fixed order, so the pack has one stage per place: stage 0 (any header), stage
1 after a mesh header (broadcast, fragment or IPv6), stage 2 after LOWPAN_BC0 (fragment or IPv6),
stage 3 after a first fragment header (IPv6 only). Each stage has its own selector keys. Every branch
reads to the end of its octet before any octet list, so an encode writes back the bits it read.

## What is mapped

- **Mesh header**: V and F, hops left, the deep hops left octet when hops left is 15, the originator
  and final addresses (16 or 64 bits by V and F, `hex`).
- **LOWPAN_BC0**: the sequence number.
- **FRAG1 and FRAGN**: datagram size, tag, and (FRAGN) the offset; FRAGN's octets.
- **Dispatch 0x41**: the uncompressed IPv6 packet as octets.
- **IPHC**: TF, NH, HLIM, CID, SAC, SAM, M, DAC, DAM; the context octet (SCI, DCI); by TF the ECN,
  DSCP, pad and flow label; the next header when NH is 0; the hop limit when HLIM is 0; the source
  address bits carried inline by SAC and SAM (128, 64, 16 or none) and the destination's by M, DAC
  and DAM (128, 64, 48, 32, 16, 8 or none), each as `hex`. Then, when NH is 0, the IPv6 payload as
  octets; when NH is 1, the NHC header.
- **NHC**: UDP (11110CPP): C and P, the ports by P (16 or 8 or 4 bits each), the checksum when C is
  0, the payload as octets. Extension header (1110EEEN): EID and NH, the next header when NH is 0,
  the header's octets in the extent of its length (which counts octets after it), then the rest as
  octets; EID 7 (an IPv6 header) gives the inner packet as octets. GHC UDP (11010CPP): as UDP, with
  the compressed payload as octets. GHC ICMPv6 (11011111) and GHC extension header (10110EEN): the
  compressed data as octets.

## Shared keys

None. The `inet` keys of `ipv6-header` name the fields of an uncompressed header; IPHC fields hold
only the bits carried inline and the modes that say how to rebuild the rest, so binding them would
claim a meaning (a whole address, a hop limit always present) the frame does not carry.

## Not mapped

- **Rebuilding the IPv6 header.** The elided bits come from the 802.15.4 addresses, the shared
  contexts, and the lengths of the lower layer; a pack reads one message and has neither.
- **A second NHC after an extension header** is in `lowpan.after_ext` as octets: following NHC
  headers each again by pattern would need a list of differently laid out records chosen by a bit of
  the previous one (the NH bit). Needed: a switch on a value of the previous item.
- **GHC bytecodes** (RFC 7400 section 2) are a compression program; the compressed data is octets.
- **LOWPAN_HC1** (RFC 4944, deprecated by RFC 6282), the ESC dispatch, the page switch of RFC 8025,
  and RFC 8138 (6LoRH) are octets after their pattern.
- The ICMPv6 message in an IPHC payload is octets; `rpl-control` reads RPL messages on their own.

## Vectors

`tools/gen/mesh-vectors.py`, without an engine: IPHC with UDP NHC; IPHC with every inline field and the
context octet; context-based source with a prefix-based multicast destination; the unspecified
source; mesh, FRAG1 and IPHC; deep hops, BC0 and an extension header NHC; FRAGN; dispatch 0x41;
NALP; GHC ICMPv6; GHC UDP; a cut IPHC and a cut FRAGN header (`malformed-wire`).
