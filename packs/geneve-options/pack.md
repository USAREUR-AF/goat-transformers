# Pack: geneve-options

The Geneve header (RFC 8926 section 3.4) with its options read as type-length-value records (section
3.5). The message is the base header and the options, the payload excluded. Wire `bits`, `layout
sequential`, most significant bit first. No kind. Input and output are hex. Written by
`tools/gen/tunnels-pack.py`.

`geneve-header` (on main) reads the options as raw 4-octet words counted by the option length; this
pack reads each option.

## What is mapped

The base header: version, option length, O and C bits, reserved bits, protocol type, VNI and the last
reserved octet. Then the options to the end of the message: option class, type (its high bit is the
critical bit), three reserved bits, length in 4-octet words, and the data as hex (0 to 124 octets).

## Shared keys

None of `core` or `track`. The base header fields other than the option length are the `inet` keys
of `geneve-header`, so the two convert. The option length is `geneve.opt_len`, not
`inet.geneve_opt_len`: `geneve-header` writes that key from its word list, and here it is a plain
field, so a shared key would let a conversion write a length that its options do not have. A
conversion either way writes option length 0 and no options.

## Not mapped

- **The payload.** The option length counts 4-octet words, and a `length` block counts octets or
  bits; the options cannot be bounded by it. So the options are a list to the end of the message,
  and the option length is carried as written, not computed. The caller passes the header and
  options without the payload. Needed: a length in n-octet units.
- The meaning of each option class and type.

## Vectors

`tools/gen/tunnels-vectors.py`, without an engine: two options (one critical with data, one empty);
a control message with no options; one option of 124 octets; to `geneve-header`; an option cut
inside its data (`malformed-wire`).
