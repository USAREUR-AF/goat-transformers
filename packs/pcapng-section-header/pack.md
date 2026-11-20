# Pack: pcapng-section-header

The fixed part of a pcapng Section Header Block, as the IETF Internet-Draft
draft-ietf-opsawg-pcapng-06 section 4.1 lays it out: the 24 octets before its
options. Public. Written by hand from the draft; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.5 (`swap`).

Uses the modules `core` and `pcap` (`model/pcap.def`).

## Message convention

A message is the section header block. The pack reads octets 0-23; options and
the trailing block total length are read over and not written (vector 01).

| Octets | Field | Key | Note |
|---|---|---|---|
| 0-3 | block type 0x0A0D0D0A | common `when` | the same octets in both byte orders |
| 4-7 | block total length | `pcap.pcapng_block_total_length` | |
| 8-11 | byte-order magic 0x1A2B3C4D | the kind | |
| 12-13 | major version | `pcap.pcapng_version_major` | |
| 14-15 | minor version | `pcap.pcapng_version_minor` | |
| 16-23 | section length | `pcap.pcapng_section_length` | `twos`, 64 bits: -1 when not stated |

## Kinds

| Kind | Byte-order magic octets | Fields |
|---|---|---|
| `big-endian` | 1a 2b 3c 4d | big-endian |
| `little-endian` | 4d 3c 2b 1a | the option `swap` |

`word_bytes 1`, `bit_order msb`. The byte-order magic sets the order of every
block of the section (draft section 3.6.1).

## Shared keys

None.

## Not mapped, and why

- Options: a list of type, length and value padded to 32 bits, to the block
  end; a `bits` group needs a count.
- The trailing block total length (it repeats octets 4-7, after the options).

## Vectors

`tools/gen/link-headers-vectors.py`, from values chosen there: a little-endian
and a big-endian block with an unstated section length and their trailers, a
little-endian block at its largest values, an unknown byte-order magic
(`no-kind`), and 23 octets (`malformed-wire`).
