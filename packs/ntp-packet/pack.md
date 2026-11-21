# Pack: ntp-packet

An NTP packet (RFC 5905 section 7.3) with its extension fields (RFC 7822), the NTS extension fields of
RFC 8915 section 5 laid out. Wire `bits`, `layout sequential`, most significant bit first. No kind. One
message is one UDP payload. Written by `tools/gen/gnss-time-pack.py`.

`ntp-header` (on main) reads the 48-octet header and passes over what follows; this pack reads the
extension fields too.

## What is mapped

- **The header** on the `inet` keys of `ntp-header`: leap, version, mode, stratum, poll, precision,
  root delay and dispersion (seconds, from the 16.16 fixed point), the reference ID by the stratum
  (kiss code at 0, reference clock at 1, an address or hash from 2), and the four timestamps (seconds
  and fraction).
- **The extension fields** to the end of the packet: field type, and the body in the extent of the
  length (which counts the 4-octet header): unique identifier (0x0104), NTS cookie (0x0204) and cookie
  placeholder (0x0304) as octets; NTS authenticator (0x0404) as the nonce and ciphertext lengths and
  then the nonce, ciphertext and padding as octets; any other type as octets.

## Shared keys

None of `core` or `track`. The header uses the `inet` keys of `ntp-header`. `ntp-header` also binds the
transmit timestamp to `time_ms`; this pack does not, because a sequential line cannot hold two keys of
different transforms over the same bits.

## Not mapped

- **The legacy MAC** (key identifier and digest, RFC 5905 section 7.3) after the extension fields: it
  has no type or length, and a list to the end cannot stop before it. A packet that carries one reads its
  MAC as an extension field, wrongly or as `malformed-wire`. NTS packets carry none.
- **The NTS authenticator's parts**: the nonce and ciphertext are each padded to a 4-octet boundary,
  which a count cannot express, so they stay together as octets; the encrypted extension fields inside
  the ciphertext are not decrypted.

## Vectors

`tools/gen/gnss-time-vectors.py`, without an engine: an NTS server response; a client request with a cookie
placeholder; a stratum 1 response with no extensions; a kiss-o'-death; an unknown extension type; a cut
extension field (`malformed-wire`).
