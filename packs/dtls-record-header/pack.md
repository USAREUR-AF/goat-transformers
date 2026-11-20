# Pack: dtls-record-header

The DTLS 1.3 record headers, as IETF RFC 9147 section 4 lays them out: the
13-octet header of a plaintext record, and the unified header of a protected
record. Public. Written by hand from the RFC; the layout is stated in this
repository's words. I/O is hex text. Needs engine version 0.17 (gate blocks).

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one DTLS record, from the start of the record. The pack reads its
header; the record body is read over and not written.

| Kind | `when` | Layout |
|---|---|---|
| `ciphertext` | octet 0 bits 0-2 = 001, bit 3 (C) = 0 | unified header without a connection ID |
| `ciphertext-with-cid` | octet 0 bits 0-2 = 001, bit 3 (C) = 1 | octet 0 only |
| `plaintext` | none | 13-octet plaintext header |

A first octet 001xxxxx (32-63) is a unified header; content types are below 32,
so every other first octet is a plaintext record.

Plaintext record:

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | content type | `inet.tls_content_type` | `uint` |
| 1-2 | legacy record version | `inet.tls_legacy_version` | `uint` |
| 3-4 | epoch, low 16 bits | `inet.dtls_epoch` | `uint` |
| 5-10 | sequence number, low 48 bits | `inet.dtls_sequence` | `uint` |
| 11-12 | length | `inet.tls_record_length` | `uint` |

Unified header (kind `ciphertext`):

| Bits | Field | Key | Line |
|---|---|---|---|
| 0, bit 4 | S, sequence number is 16 bits | `inet.dtls_seq_16bit` | `uint` |
| 0, bit 5 | L, length present | `inet.dtls_length_present` | `uint` |
| 0, bits 6-7 | epoch, low 2 bits | `inet.dtls_epoch_low` | `uint` |
| 1 (S = 0) or 1-2 (S = 1) | sequence number, low bits | `inet.dtls_seq_low` | `if 0:4:1 0` / `if 0:4:1 1` |
| next 2 octets, when L = 1 | length | `inet.tls_record_length` | nested `if 0:5:1 1` |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. The position of the
sequence number and of the length depend on the S and L bits, which come
before them: gate blocks (engine-spec 0.17). Because S and L are also plain
fields, encode writes them first and the blocks follow them (0.17, Encode,
step 2): the round trip keeps the choice (vectors 03-06).

A unified header with a connection ID (C = 1): the length of the ID is agreed
between the peers and is not on the wire, so nothing after octet 0 can be
placed. The kind reads octet 0 (vector 07).

## Shared keys

`inet.tls_content_type`, `inet.tls_legacy_version` and
`inet.tls_record_length`, with `tls-record-header`; the evidence is in that
pack's pack.md (RFC 9147 section 4).

## Not mapped, and why

- The record body: encrypted, or the fragment of a plaintext record.
- The connection ID and what follows it (see above).
- The DTLS 1.2 record header with a connection ID (content type 25, RFC 9146):
  not in RFC 9147.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there: a plaintext
handshake header, a plaintext ack at the largest values, unified headers for
the four combinations of S and L, a unified header with C set, a unified
header cut inside its length and a plaintext header of 12 octets (both
`malformed-wire`).
