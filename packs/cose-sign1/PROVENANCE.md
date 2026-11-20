# Provenance: cose-sign1 pack

Read on 2026-11-20. No source file is copied into this tree. The pack and the
module `cose` hold facts of the format: the CBOR tag of COSE_Sign1, the order
and CBOR types of its four elements, and the labels and value types of the
common header parameters, stated in this project's own words. No text, table,
CDDL fragment or example message of the RFCs is reproduced, and no vector
uses a message from their appendices.

## RFC 9052

| | |
|---|---|
| Source | RFC 9052, "CBOR Object Signing and Encryption (COSE): Structures and Process", STD 96, J. Schaad, August 2022; obsoletes RFC 8152 |
| Download | https://www.rfc-editor.org/rfc/rfc9052.txt |
| File | `rfc9052.txt`, 149835 bytes |
| SHA-256 | `01eecd7f646537600e7aad665b1fa581ce6ec33dae4ef4add0997aaf38cd0a45` |
| Sections read | 1.5 (labels are integers or text strings), 2 (the common array layout, tags of the message types), 3 (the two buckets, the protected bucket wrapped in a byte string, duplicate labels), 3.1 (common header parameters: labels 1 to 6 and their types), 4.1 (payload, detached content), 4.2 (COSE_Sign1 and tag 18), 9 (encoding restrictions) |

## RFC 9053

| | |
|---|---|
| Source | RFC 9053, "CBOR Object Signing and Encryption (COSE): Initial Algorithms", J. Schaad, August 2022 |
| Download | https://www.rfc-editor.org/rfc/rfc9053.txt |
| File | `rfc9053.txt`, 120315 bytes |
| SHA-256 | `3d470615875620375f8453ba25b8dce7e4d0271e76b0b79a46df34ccb2d56ab0` |
| Used | only to confirm that the algorithms it registers have integer identifiers (pack.md, "alg and content type"), and for the integer values -7 and -8 chosen in vectors |

## Terms

Both RFCs carry the notice:

> This document is subject to BCP 78 and the IETF Trust's Legal
> Provisions Relating to IETF Documents
> (https://trustee.ietf.org/license-info) in effect on the date of
> publication of this document.

The Legal Provisions in effect (effective date March 25, 2015, corrected
September 21, 2021) were read from
https://trustee.ietf.org/wp-content/uploads/Corrected-TLP-5.0-legal-provsions.pdf
(SHA-256 `b5cbd993d1dae273d7b251db4efc397b4de13451b2156b94d5a901c83c0fb48a`).
Section 3.c grants to anyone the right to copy and distribute IETF Documents
in full and without modification, and unmodified portions with attribution;
section 3.d.i grants no license to modify them outside the IETF Standards
Process. Section 3.b states:

> In addition, the IETF Trust interprets the IETF Standards Process to
> include the archiving of IETF Documents in perpetuity for reference in
> support of IETF activities and the implementation of IETF standards and
> specifications.

The Provisions license the text of the documents. This pack relies on the
facts the RFC defines for implementers (a tag number, element order, label
numbers, value types) and restates them; it copies and modifies no text of
the RFCs, so it uses none of the rights the Provisions grant or withhold.
The documents carry no distribution, handling, export-control or
proprietary marking.
