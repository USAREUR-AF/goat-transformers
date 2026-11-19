# Pack: nitf-file-header

The fixed part of the NITF 2.1 (and NSIF 1.0) file header, from FHDR through
NUMI: 363 characters. Public. Maintained by hand from MIL-STD-2500C appendix A,
table A-1. Wire `text`, `delimiter none`: the header is one field and each
header field a column `0:<offset>:<size>`. Needs engine version 0.10.

Uses the modules `core` and `nitf` (`model/nitf.def`, keys `fh_<field>`).

## Message convention

A message is the first bytes of a NITF file. The pack reads FHDR through NUMI
and ignores what follows; encode writes those 363 characters. Kinds select on
FHDR and FVER together (`0:0:9`): `nitf-2-1` for `NITF02.10`, `nsif-1-0` for
`NSIF01.00`, which has the same layout. Anything else is `no-kind`.

Fields: BCS-N integer fields (CLEVEL, FSCOP, FSCPYS, ENCRYP, FL, HL, NUMI) are
`int` and are written zero-padded to their size; every other field is the text
as written, trailing spaces removed, and blank fields are absent.

## Shared keys

None. The file header has no position. FDT (file date and time) is
`CCYYMMDDhhmmss` UTC in one 14-digit field; no text transform reads that form
into `time_ms` (`hms_dmy` reads a time `hhmmss` and a date `ddmmyy` in two
fields), so it stays the raw text `nitf.fh_fdt`.

## Not mapped, and the constructs it needs

| Part | Why | Construct needed |
|---|---|---|
| FBKGC (file background colour) | three unsigned binary bytes; the `text` wire accepts characters 0x20 to 0x7E only, so a header whose colour bytes are not printable (black 0x000000, white 0xFFFFFF: most files) is `malformed-wire`. The pack maps the field as text for the headers it can read | a binary field inside a text record (byte columns read as an unsigned integer) |
| Everything after NUMI: the NUMI pairs of image subheader length (LISH, 6) and image length (LI, 10), then NUMS, NUMX, NUMT, NUMDES, NUMRES with their own pairs, UDHDL/UDHOFL/UDHD, XHDL/XHDLOFL/XHD | each count is an ASCII-decimal field, and what it counts follows it | a group whose count is an ASCII-decimal text field read earlier |
| UDHD, XHD (the extension areas that hold TREs) | their length is an ASCII-decimal field (UDHDL, XHDL), and inside them each TRE is a 6-character tag, a 5-digit length and that many characters | a length from an ASCII-decimal field; and a group of items each selected by a text tag and sized by a decimal length field |
| Locating the segments | FL, HL, LISH and LI give byte lengths of the parts of the file | layered framing: a payload located by lengths read from the header |
| ECS-A text | the extended character set allows bytes above 0x7E in FTITLE and the security fields | UTF-8 or 8-bit text on the `text` wire |

The single TREs are read by the packs `nitf-tre-<tre>`, given their CEDATA.

## Vectors

6 vectors under `vectors/`, written by `tools/gen/nitf-header-vectors.py`
(standard library only; no pack read, no engine run; `--check`): NITF 2.1 and
NSIF 1.0 round trips, a header followed by more of the file (only the header
is written back), FVER 02.00 (`no-kind`), a binary background colour
(`malformed-wire`) and a header cut at 200 characters.
