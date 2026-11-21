# Pack: ssh-message

An SSH message, the payload of an SSH packet: the message number and the fields of the transport (RFC 4253,
RFC 8308), user authentication (RFC 4252) and connection (RFC 4254) messages. Wire `bits`, `layout
sequential`, big-endian. No kind: a `switch` on the message number chooses the fields. Written by
`tools/gen/remote-pack.py`.

## What is mapped

Strings and name-lists are a 32-bit length and their octets (a `length 32 bytes` block); booleans and
uint32s are fields.

| Number | Message | Fields |
|---|---|---|
| 1 | DISCONNECT | reason code, description, language tag |
| 2 | IGNORE | data |
| 3 | UNIMPLEMENTED | rejected sequence number |
| 4 | DEBUG | always display, message, language tag |
| 5, 6 | SERVICE_REQUEST, SERVICE_ACCEPT | service name |
| 7 | EXT_INFO | the extensions (counted), each name and value |
| 20 | KEXINIT | cookie, the ten name-lists, first-kex-packet-follows, reserved |
| 21, 52, 81, 82 | NEWKEYS, USERAUTH_SUCCESS, REQUEST_SUCCESS, REQUEST_FAILURE | none (REQUEST_SUCCESS's response data is not laid out) |
| 50 | USERAUTH_REQUEST | user name, service name, method name, then the method's fields as octets |
| 51 | USERAUTH_FAILURE | authentications that can continue, partial success |
| 53 | USERAUTH_BANNER | message, language tag |
| 80 | GLOBAL_REQUEST | request name, want reply, request data |
| 90, 91, 92 | CHANNEL_OPEN, OPEN_CONFIRMATION, OPEN_FAILURE | channel type and numbers, window, packet size; reason code and texts |
| 93-100 | WINDOW_ADJUST, DATA, EXTENDED_DATA, EOF, CLOSE, REQUEST, SUCCESS, FAILURE | recipient channel and each message's fields |
| any other (30-49 key exchange methods, 60-79 authentication methods) | | the fields as octets |

## Shared keys

None.

## Not mapped

- **Name-lists as lists**: a name-list is comma-separated text; it is its octets. Needed: text of a
  length a field gives, and splitting at a character.
- **Method- and type-specific fields** (USERAUTH_REQUEST by method, CHANNEL_OPEN by channel type,
  CHANNEL_REQUEST by request, the key exchange method messages) are octets.
- **REQUEST_SUCCESS's optional data** after the number is not read.

## Vectors

`tools/gen/remote-vectors.py`, without an engine: KEXINIT; DISCONNECT; IGNORE; NEWKEYS; SERVICE_ACCEPT;
EXT_INFO; a password USERAUTH_REQUEST; USERAUTH_FAILURE; CHANNEL_OPEN; CHANNEL_DATA; an exec CHANNEL_REQUEST;
a key exchange method message as octets; a cut name-list (`malformed-wire`).
