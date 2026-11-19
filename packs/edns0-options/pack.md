# Pack: edns0-options

The options of an EDNS(0) OPT pseudo-RR: its RDATA (RFC 6891 section 6.1.2).
Public. Maintained by hand. Wire `tlv` with `tag 2` and `length 2`: each
option is a 2-octet OPTION-CODE, a 2-octet OPTION-LENGTH and that many octets
of OPTION-DATA. Needs engine version 0.13.

Uses the modules `core` and `edns0` (`model/edns0.def`).

## Message convention

A message is the **RDATA of the OPT RR only**: the octets after its RDLEN. The
fixed part of the OPT RR (NAME, TYPE, CLASS, TTL, RDLEN) and the rest of the
DNS message are not part of it.

## Mapped

One line per registered option code (27 codes from the IANA "DNS EDNS0 Option
Codes (OPT)" registry, every code that is not Reserved), key
`edns0.opt<code>_<registry name>`, in ascending code order, each holding the
OPTION-DATA as lowercase hex. An option with no data (an NSID request) decodes
to the empty string and is written back with length 0. No option is read as an
integer: the sizes of the option values are set by the RFC of each option,
which were not read for this pack.

## Not mapped, and why

| Part | Why |
|---|---|
| The structure of each option's data (the client-subnet family and prefix, the cookie halves, the extended error's info-code and text) | kept as hex; the RFC of each option was not read |
| A second or later option with the same code | only the first occurrence is read (engine-spec 0.13, Locators); later ones are not written back |
| Option order | encode writes the mapped options in code order, then the residue in input order |
| Codes outside the registry snapshot | residue, kept as hex and written back after the mapped options |

## Shared keys

None.

## Vectors

4 vectors under `vectors/`, written by `tools/gen/ietf-options-vectors.py`:
a query (NSID request, client cookie), a response (NSID, full cookie,
padding, extended error), an unregistered code kept as residue, and an option
longer than the RDATA (`malformed-wire`).
