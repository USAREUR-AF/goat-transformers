# Pack: hsrp

A Cisco Hot Standby Router Protocol message, version 0 (RFC 2281 section 5.1, Informational): the
20 octets of the UDP payload. Wire `bits`, fixed layout, `word_bytes 1`, most significant bit
first. Input and output are hex.

## What is mapped

Version, op code (hello, coup, resign), state, hellotime and holdtime in seconds, priority, group,
the reserved octet, the authentication data (8 octets as text, `ascii`: trailing zero octets are
removed and written back), and the virtual IP address.

## Shared keys

None.

## Not mapped

- Authentication data that is not printable ASCII fails to decode (`transform-decode`): RFC 2281
  states a clear-text password, and the `ascii` transform refuses other octets.
- HSRP version 2, which Cisco documents outside the RFC series, has another layout and is not this
  pack.

## Vectors

`tools/gen/ietf-more-vectors.py`, without an engine: a hello of the active router with the default
authentication data, a coup with eight characters of authentication data, and a message one octet
short (`malformed-wire`).
