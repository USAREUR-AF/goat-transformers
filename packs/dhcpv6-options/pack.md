# Pack: dhcpv6-options

The options area of a DHCPv6 message (RFC 9915 section 21; RFC 8415, which it
replaces, has the same format). Public. Maintained by hand. Wire `tlv` with
`tag 2` and `length 2`: each option is a 2-octet code, a 2-octet length and
that many octets of data. Needs engine version 0.13.

Uses the modules `core` and `dhcpv6` (`model/dhcpv6.def`).

## Message convention

A message is the **options area only**: the octets after the 4-octet header
of a client/server message (msg-type and transaction-id), or after the
34-octet header of a relay message (msg-type, hop-count, link-address,
peer-address). The header is not part of the message; the caller removes it.

## Mapped

One line per registered option code (148 codes from the IANA "Option Codes"
registry, every code that is not Reserved or Unassigned), key
`dhcpv6.opt<code>_<registry name>`, in ascending code order. The option-data
is held as lowercase hex, except six options whose size and meaning RFC 9915
fixes as one unsigned integer:

| Code | Key | Size | Meaning (RFC 9915) |
|---|---|---|---|
| 7 | `opt7_preference` | 1 | server preference (21.8) |
| 8 | `opt8_elapsed_time` | 2 | time since the client began the exchange, hundredths of a second (21.9) |
| 19 | `opt19_reconf_msg` | 1 | the message type the client is to send (21.19) |
| 32 | `opt32_information_refresh_time` | 4 | seconds (21.23) |
| 82 | `opt82_sol_max_rt` | 4 | seconds (21.24) |
| 83 | `opt83_inf_max_rt` | 4 | seconds (21.25) |

Options with no data (Rapid Commit, Reconfigure Accept) decode to the empty
string and are written back with length 0.

## Not mapped, and why

| Part | Why |
|---|---|
| The options inside IA_NA (3), IA_TA (4), IA_PD (25), IA Address (5), IA Prefix (26) and the other options that carry options | IA_NA, IA_TA and IA_PD begin with fixed octets (IAID, T1, T2: 12 for IA_NA and IA_PD, 4 for IA_TA) and then hold options. A `tlv` path walks into a value only when the whole value is a set, so these options are kept whole as hex, nested options included |
| A second or later option with the same code | the wire reads the first occurrence of a code a line names; later ones are neither mapped nor residue and are not written back (engine-spec 0.13, Locators). A message with two IA_NA options keeps only the first |
| Option order | encode writes the mapped options in code order, then the residue in input order; a message in another order converts to the same options in that order |
| Codes outside the registry snapshot | residue: kept as hex and written back after the mapped options |
| The message header | not part of the message (above) |

## Shared keys

None. No option of the area has the meaning of a `core` or `track` key with
evidence in the sources read. The geolocation options (for example
OPTION_GEOCONF_CIVIC, 36) hold structured data the pack keeps as hex.

## Vectors

7 vectors under `vectors/`, written by `tools/gen/ietf-options-vectors.py`
(standard library only; no pack read; no engine run; `--check`): solicit
options, reply options with the integer options, options out of code order,
two IA_NA options, an unregistered code kept as residue, an option longer than
the area (`malformed-wire`), and an empty area.
