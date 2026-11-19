# Provenance: dhcpv6-options pack

Read on 2026-11-19. No source file is copied into this tree. The pack holds the
option format, the option codes and names, and the sizes of six integer
options, restated; the vectors hold options areas written for this pack by
`tools/gen/ietf-options-vectors.py`.

## RFC 9915

| | |
|---|---|
| Source | RFC 9915, Dynamic Host Configuration Protocol for IPv6 (DHCPv6), STD 102, which obsoletes RFC 8415 |
| Download | https://www.rfc-editor.org/rfc/rfc9915.txt |
| SHA-256 | `66eea827cd89f41663c2d33738f154b0067781675b3072c3393d8c9c43f5412f` |
| Sections read | 21.1 (format of DHCP options), 21.2 to 21.25 (the options it defines; the sizes of 21.8, 21.9, 21.19, 21.23, 21.24, 21.25) |

The RFC's notice:

> Copyright (c) 2026 IETF Trust and the persons identified as the
> document authors.  All rights reserved.
>
> This document is subject to BCP 78 and the IETF Trust's Legal
> Provisions Relating to IETF Documents
> (https://trustee.ietf.org/license-info) in effect on the date of
> publication of this document.

The brief named RFC 8415 section 21; RFC 9915 replaces it with the same option
format, and the registry now cites RFC 9915. RFC 8415 (sha256
`3a3540c90ef2da48caa5cba627455025ef8cff6d1f988c6d0a83305485e4aa0a`) was compared for sections 21.1, 21.8,
21.9, 21.19, 21.23 to 21.25 and agrees.

## IANA registry

| | |
|---|---|
| Source | Dynamic Host Configuration Protocol for IPv6 (DHCPv6), "Option Codes" |
| Download | https://www.iana.org/assignments/dhcpv6-parameters/dhcpv6-parameters-2.csv |
| SHA-256 | `08c218d37a098d70d91cb29a0150e683800c15aacc2bbbeebd6895fff8401719` (read 2026-11-19) |
| Used | every numeric code that is not Reserved or Unassigned: 148 codes, their names |

The registries are covered by the "Joint Statement of IANA and IETF Concerning Copyright Rights in the Protocol Registries" of 10 November 2021 (https://www.iana.org/help/licensing-terms, read 2026-11-19):

> IANA and IETF intend that the Protocol Registries may be freely used by any
> party for any purpose.

> both IANA and IETF affirm that any applicable rights that they may have in
> the Protocol Registries are subject to the Creative Commons CC0 1.0
> dedication found at https://creativecommons.org/publicdomain/zero/1.0/legalcode
