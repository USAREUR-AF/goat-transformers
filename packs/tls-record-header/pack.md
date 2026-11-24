# Pack: tls-record-header

The TLS record header, as IETF RFC 8446 section 5.1 lays it out, with the first
octets of a plaintext change cipher spec, alert or handshake record. Public.
Written by hand from the RFC; the layout is stated in this repository's words.
I/O is hex text. Needs engine version 0.5.

Uses the modules `core` and `inet` (`model/inet.def`).

## Message convention

A message is one TLS record, from the start of the record. The pack reads the
5-octet header and, by kind, the first octets of the fragment; the rest of the
fragment is read over and not written (vector 01).

| Octets | Field | Key | Transform |
|---|---|---|---|
| 0 | content type | `inet.tls_content_type`; also the `when` of the kinds | `uint` |
| 1-2 | legacy record version | `inet.tls_legacy_version` | `uint` |
| 3-4 | length of the fragment | `inet.tls_record_length` | `uint` |

| Kind | `when` | Octets 5 on | Keys |
|---|---|---|---|
| `change-cipher-spec` | type 20 | 5 the value | `inet.tls_ccs_value` |
| `alert` | type 21 | 5 level, 6 description | `inet.tls_alert_level`, `inet.tls_alert_description` |
| `handshake` | type 22 | 5 message type, 6-8 message length | `inet.tls_handshake_type`, `inet.tls_handshake_length` |
| `application-data` | type 23 | none | |
| `other` | none | none | |

`word_bytes 1`, `bit_order msb`; the fields are big-endian. As in the
`icmp-header` pack, the content type is a common field and the `when` of each
kind; on encode the kind's `when` value is written last. The pack does not
check the legacy version or the 2^14 limit on the length (vector 06).

What the kinds read is the plaintext a record carries before keys are in use:
the initial handshake, a change cipher spec, an alert sent in the clear. Once
records are protected (TLS 1.3 section 5.2), every record has the outer type
23 and is kind `application-data`. A handshake record may hold several
handshake messages, or part of one; the pack reads the header of the first.

On encode from another format, the first kind whose `requires` holds is
written: change cipher spec, alert or handshake by their keys, application
data by content type 23, else `other`. The last two need the content type,
version and length; an entity without them is `no-kind`.

## Shared keys

`inet.tls_content_type`, `inet.tls_legacy_version` and
`inet.tls_record_length` are also the keys of the `dtls-record-header` pack:
RFC 9147 section 4 keeps the meaning of the TLS record fields unless it says
otherwise, and gives the length of the unified header as identical to the
TLS 1.3 length. Vector 09 carries a client hello record to a DTLS plaintext
header. No core key is bound.

## Not mapped, and why

- The rest of the fragment: handshake message bodies, application data.
- Protected records: their content is encrypted.
- SSL 2.0 compatible hello records: another layout.

## Vectors

`tools/gen/ietf-headers-4-vectors.py`, from values chosen there: a client hello
record, a fatal alert, a change cipher spec, an application data record, an
undefined content type (kind `other`), the header at its largest values, an
alert cut short and 4 octets (both `malformed-wire`), and the client hello to
`dtls-record-header`.
