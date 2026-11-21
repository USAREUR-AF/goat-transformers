# Pack: mpls-label-stack

The MPLS label stack (RFC 3032 section 2.1, the TC field named by RFC 5462): the top entry, then the
entries below it. RFC 7510 carries the same stack, followed by the packet, as a UDP payload (port
6635). The message is the stack alone. Wire `bits`, `layout sequential`, most significant bit first.
No kind. Input and output are hex. Written by `tools/gen/tunnels-pack.py`.

## What is mapped

The top entry: label, traffic class, bottom-of-stack bit, TTL. When its bottom-of-stack bit is 0,
the entries below it as a list to the end of the message, each the same four fields.

## Shared keys

None of `core` or `track`. The top entry is on the `inet` keys of `mpls-label-entry`, so the two
convert: to `mpls-label-entry` keeps the top entry; from it gives a stack of one.

## Not mapped

- **The packet after the stack.** The stack ends at the entry whose bottom-of-stack bit is 1, the
  24th bit of a 32-bit entry; a list can end by a count, by a bit before each item, by the end of its
  extent, but not by a field inside an item. So the list runs to the end of the message, and the
  caller passes the stack alone. The bottom-of-stack bits are carried as written. Needed: a list that
  ends after an item whose field has a given value.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: three entries; one entry; to `mpls-label-entry`;
`mpls-label-entry` to the stack (in `packs/mpls-label-entry/vectors/`); a second entry cut in half
(`malformed-wire`).
