# Pack: tls-record

A TLS 1.3 record (RFC 8446 section 5.1) with the handshake messages it carries (section 4). Wire `bits`,
`layout sequential`. No kind: a `switch` on the content type chooses the body. One message is one record.
Written by `tools/gen/webframes-pack.py`.

`tls-record-header` (on main) reads the 5-octet header and the first octets of the body; this pack reads
the whole record.

## What is mapped

- **Record header** on the `inet` keys of `tls-record-header` (content type, legacy version); the record
  length is a `length` block, written on encode.
- **Handshake records** (22): the handshake messages to the end, each type and a 24-bit length block:
  ClientHello (legacy version, random as hex, legacy session ID, cipher suites, compression methods,
  extensions), ServerHello (legacy version, random, session ID echo, cipher suite, compression method,
  extensions); other handshake types as octets.
- **Extensions**: type and a length block: in a ClientHello, server_name (the names, each type and host
  name octets) and supported_versions (the versions); in a ServerHello, supported_versions (the selected
  version); every other extension as octets.
- **Alert** (21) and **change_cipher_spec** (20) on the `inet` keys of `tls-record-header`; any other
  content type (application data, encrypted records) as octets.

## Shared keys

None of `core` or `track`. The record header, alert and change_cipher_spec fields are the `inet` keys of
`tls-record-header`; its `inet.tls_record_length` and `inet.tls_handshake_*` keys are lengths and types this
pack writes from its blocks, so they are not mapped here.

## Not mapped

- **A handshake message split across records**: each record is one message here; a fragment that ends
  inside a handshake message is `malformed-wire`.
- Encrypted handshake messages (after ServerHello) and the other extensions (key_share,
  signature_algorithms, ALPN ...) are octets; HelloRetryRequest is a ServerHello with a fixed random and
  reads as one.
- DTLS (see `dtls-record-header`).

## Vectors

`tools/gen/webframes-vectors.py`, without an engine: a ClientHello with server_name, supported_versions and
key_share; a ServerHello; a record of two handshake messages; an alert; change_cipher_spec; application
data; a cut handshake (`malformed-wire`).
