# sml-message

One SML message (Smart Message Language 1.04), the binary encoding German smart meters use on
their optical and LMN interfaces. Licence `LicenseRef-unstated` (PROVENANCE.md).

## Message convention

One SML_Message: transactionId, groupNo, abortOnError, the messageBody (a choice tag and the body),
crc16 and the end byte 0x00. The SML transport (the escape sequences around an SML file) and the
other messages of a file are outside the pack.

## Layout

`bits`, `layout sequential`, `bit_order msb`. Every element starts with a TL field: a bit saying a
further TL byte follows, the type in three bits and the length (or, for a list, the element count)
in four. The pack reads each element as those fields and a `switch` on the type: an octet string's
bytes are a group counted by the length less one (`count … plus 1`), an integer's value has the
width the length gives (a `switch` on the length: one to eight bytes, as SML drops leading bytes),
an absent optional element (0x01) is the empty octet string, a list of entries is a group counted
by the TL length. The messageBody tag selects the body by a `switch`: SML_PublicOpen.Req (0x0100)
and .Res (0x0101), SML_PublicClose.Req (0x0200) and .Res (0x0201), SML_GetList.Res (0x0701).

## Shared keys

| Element | Key | Evidence |
|---|---|---|
| refTime of PublicOpen.Res and actSensorTime of GetList.Res, when the time is a timestamp (choice 2) | `time_ms` | the document states a timestamp as seconds since 1970-01-01 00:00:00 UTC; `uiscale:1000` |

## Not mapped

- TL fields of more than one byte: an element whose length does not fit four bits (an octet string
  longer than 14 bytes, a list of more than 15 elements) continues its length in the low four bits
  of the next TL byte. The two halves of the length are split by four other bits, so no `length`
  or `count` reads them; only the first TL bit is carried and such an element is not read
  correctly. Missing: a length made of the low nibbles of a chain of bytes.
- The other bodies (profile packs, process parameters, COSEM services, attention) are `no-kind`.
- An SML_Value that is itself a list, and an SML_Status by its width, are read by type only.
- crc16 is a raw key and not checked.
