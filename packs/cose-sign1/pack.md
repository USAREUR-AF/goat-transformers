# Pack: cose-sign1

COSE_Sign1, the single-signer signed message of CBOR Object Signing and
Encryption (RFC 9052, STD 96, section 4.2). Public. Written from the RFC only
(PROVENANCE.md). I/O is hex text (`spec/engine-spec.md`, Version 0.28, the
`cbor` wire). Needs engine version 0.28.

Uses the module `cose` (`model/cose.def`). No key of `core` or `track` is
bound (see "Shared keys").

## Message convention

A message of this pack is one tagged COSE_Sign1 data item:

1. the head of CBOR tag 18 (`tag 18`), the tag RFC 9052 assigns to COSE_Sign1;
2. an array of four elements, in this order:
   - `[0]` protected bucket: a byte string. Its content is the encoded header
     map, or nothing when the bucket is empty;
   - `[1]` unprotected bucket: a map whose labels are integers or text strings;
   - `[2]` payload: a byte string, or `nil` when the content is detached and
     travels separately;
   - `[3]` signature: a byte string.

An untagged COSE_Sign1 (the bare array, which RFC 9052 allows when the
context identifies the message type), a message under another tag (COSE_Sign
98, COSE_Mac0 17, COSE_Encrypt0 16 and the others), and a top item that is
not an array are `malformed-wire`.

Encode writes tag 18 and then the array with the core deterministic encoding
of RFC 8949 4.2.1 (shortest heads, definite lengths, map members in bytewise
order of their encoded labels). RFC 9052 section 9 asks for that encoding only
for the structures that are signed or MACed (Sig_structure and others), and
those are built from the byte strings this pack keeps byte for byte, so a
re-encoded message still verifies: the protected bucket, the payload and the
signature are written back as the exact bytes that were read. The outer
array and the unprotected map may change bytes (an indefinite length becomes
definite, a long head becomes short); they are not covered by the signature.

## Mapping

### Shared keys

None. No field of COSE_Sign1 has the meaning of a key of `core` or `track`.
The candidate that was checked:

| Wire field | Model key considered | Why it is not bound |
|---|---|---|
| unprotected label 4, `kid` | `uid` | RFC 9052 section 3.1 describes `kid` as data that helps find the cryptographic key, says applications must not assume `kid` values are unique, that several keys may share one, and that its internal structure is not defined. `core.uid` names an entity of the model. A key identifier names a key, not the reported entity, and is not unique, so it is a raw key. |

Nothing in the four parts or the common header parameters is a position, a
time, a speed or a name of an entity, so the capability report shows `NONE`
toward `geojson` and back: a COSE_Sign1 converts only to itself.

### Raw keys of `cose`

| Path | Key | Transform | Evidence in RFC 9052 |
|---|---|---|---|
| `[0]` | `cose.protected` | `bytes` | Sections 3 and 4.2: element 0 is the protected bucket, the encoded header map wrapped in a byte string; an empty bucket is preferably a zero-length byte string, which decodes to the empty string. |
| `[1].1` | `cose.alg` | `int` | Section 3.1, Table 3 of common header parameters: label 1, alg, an int or a text string, from the COSE Algorithms registry. The pack reads the integer form (see below). |
| `[1].3` | `cose.content_format` | `uint` | Section 3.1: label 3, content type, a text string or an unsigned integer; the integer is a CoAP Content-Format number. The pack reads the unsigned integer form (see below). |
| `[1].4` | `cose.kid` | `bytes` | Section 3.1: label 4, kid, a byte string. |
| `[1].5` | `cose.iv` | `bytes` | Section 3.1: label 5, IV, a byte string. |
| `[1].6` | `cose.partial_iv` | `bytes` | Section 3.1: label 6, Partial IV, a byte string. |
| `[2]` | `cose.payload` | `bytes` | Sections 2, 4.1 and 4.2: the content, a byte string when present and `nil` when detached. `nil` is absent on this wire (ruling 6 of 0.28), and encode writes `f6` at `[2]` when the payload is absent and the signature is present (step 3 of "Writing a message"). |
| `[3]` | `cose.signature` | `bytes` | Section 4.2: element 3 is the signature value, a byte string. |

A byte string is held as lowercase hex in a `string` key (the `bytes`
transform of the `cbor` wire).

**alg and content type: one form each.** RFC 9052 allows two types for label
1 (int or text) and for label 3 (text or unsigned integer). A `cbor` field has
one transform, and 0.28 has no way to choose a transform by the type of the
item (a `when` tests a value, not a type). The pack reads the integer form of
both: section 1.5 of RFC 9052 gives integers as the compact form COSE prefers,
and every algorithm RFC 9053 registers has an integer value. A message whose
unprotected alg is text, or whose unprotected content type is text, fails to
decode with `transform-decode`; it is not passed through as residue. The text
forms are left for keys of their own (`cose.alg_name`, `cose.content_type`)
when the language can select by type; the integer keys are not retyped
(model rule: a key never changes type).

The header parameters are read from the unprotected bucket only. RFC 9052
section 3 says a parameter is taken from the protected bucket first and from
the unprotected bucket only when the protected bucket lacks it; this pack
cannot see into the protected bucket (below), so a consumer that needs the
effective value of `alg` must decode `cose.protected` itself.

## Not mapped, and why

- **The protected header map.** Element 0 is a byte string whose content is
  itself encoded CBOR (a header map, typically holding `alg`). Version 0.28
  reads a byte string only as opaque bytes: no path step enters it and no
  transform decodes it. The bucket is therefore kept whole as
  `cose.protected`, hex of the exact bytes, which is also what a verifier
  needs, since the signature covers those bytes and not a re-encoding of
  them. Reading `alg`, `crit` or `kid` from it needs a language addition: a
  `cbor` path step that enters a byte string and continues in the item it
  holds (for example `[0].<cbor>.1`), or a transform `cbor-in-bytes` that
  decodes the bytes as one CBOR item for a group or a nested scope. Either
  needs a rule for encode, since rewriting the inner map would change the
  signed bytes; the simplest is "read only, written back from the raw
  bytes".
- **crit (label 2) in the unprotected bucket.** RFC 9052 section 3.1 requires
  crit to be in the protected bucket. Its value is an array of labels, each an
  integer or a text string; a group of scalar items would fail on a text label
  and carries no residue (0.7). Left to residue: it round-trips in its own
  format, keyed `[1].2`.
- **Other labels of the unprotected bucket.** Every label outside 1, 3, 4, 5
  and 6 (counter signatures, x5chain and other registered parameters,
  algorithm-specific negative labels, private and text labels) is residue,
  keyed by its path (`[1].-70000`, `[1].x-app`), and is written back only into
  this format.
- **An empty unprotected bucket.** RFC 9052 section 3 requires both buckets to
  be present, and a message with no unprotected parameters carries an empty
  map `a0` at `[1]`. Ruling 23 of 0.28 writes a gap position that the pack's
  lines walk into as a map as `a0`, so such a message round-trips with `a0`
  at `[1]` (vector 08). A detached payload at `[2]` is written `f6`.
- **The untagged form and the other COSE messages.** COSE_Sign (98),
  COSE_Mac0 (17), COSE_Mac (97), COSE_Encrypt0 (16) and COSE_Encrypt (96) are
  other packs; the untagged COSE_Sign1 needs a pack without `tag 18`.
- **Tags on inner items.** A tag on the payload or another inner item is
  passed over on decode and not written on encode (ruling 2 of 0.28).
- **Signature verification, Sig_structure, external AAD, key lookup.** These
  are processing, not message fields; out of scope for a conversion pack.
- **IV and Partial IV together.** RFC 9052 forbids both in one layer. The pack
  does not check it; a message with both decodes both.
