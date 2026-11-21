# Pack: smb2-message

An SMB2/3 message ([MS-SMB2]): the 64-octet header and the fixed part of the main session-setup commands,
or the SMB3 transform and compression transform headers. Wire `bits`, `layout sequential`, `bit_order lsb`
(SMB2 is little-endian). Kinds by the protocol identifier: `smb2` (0xFE 'SMB'), `transform` (0xFD 'SMB'),
`compression-transform` (0xFC 'SMB'). One message is one SMB2 message without the 4-octet direct TCP
(NetBIOS session) prefix. Written by `tools/gen/remote-pack.py`. Labelled `LicenseRef-MS-OpenSpec`
(PROVENANCE.md).

## What is mapped

- **Header**: structure size, credit charge, status (or channel sequence in a request), command, credits,
  the flag bits one by one (response, async, related, signed, priority, DFS, replay), next command, message
  ID; by the async flag, the async ID or the reserved field and tree ID; session ID; signature.
- **Commands**, by the response flag and, for a response, the status (0 and STATUS_MORE_PROCESSING_REQUIRED
  lay out the command's response; any other status is the error response):
  - NEGOTIATE request (dialects counted) and response;
  - SESSION_SETUP request and response;
  - LOGOFF and TREE_DISCONNECT;
  - TREE_CONNECT request and response;
  - CREATE request and response;
  - the error response;
  - other commands as octets.
- **The variable part** of each command (security buffer, path, name, negotiate and create contexts, error
  data) as octets after the fixed part.
- **Transform header** (signature, nonce, original size, flags, session ID, the encrypted message) and
  **compression transform header** (original size, algorithm, flags, offset or length, the data).

GUIDs, the signature and the nonce are `hex`; under `bit_order lsb` the `hex` transform gives each octet's
low nibble first, so the text is not the octets' usual hex (it round-trips exactly).

## Shared keys

None.

## Not mapped

- **Buffers by offset**: the variable parts are named by offsets from the header; they normally follow the
  fixed part, and the pack reads them as the octets that do. Needed: a reference to an offset of the
  message.
- **Compounded messages**: the next command's header, at the next-command offset, is in the octets.
- **Negotiate contexts, create contexts, the security blobs (SPNEGO), file names** (UTF-16LE): octets.
- The other commands (CLOSE, READ, WRITE, IOCTL, QUERY_INFO ...); SMB1.

## Vectors

`tools/gen/remote-vectors.py`, without an engine: NEGOTIATE request and response; SESSION_SETUP response with
more processing required; TREE_CONNECT request and response; CREATE request and response; an error response;
an async pending response; a signed LOGOFF; a READ as octets; a transform header; SMB1 (`no-kind`); a cut
header (`malformed-wire`).
