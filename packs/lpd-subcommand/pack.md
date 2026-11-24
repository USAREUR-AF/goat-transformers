# Pack: lpd-subcommand

An LPD receive-job subcommand (RFC 1179 section 6), sent after the daemon command 2: a binary code octet,
the operands, LF. Wire `bits`, `layout sequential`. Kinds by the code: 1 `abort-job` (code and LF only), 2
`receive-control-file`, 3 `receive-data-file`. Written by `tools/gen/printing-pack.py`.

## What is mapped

- Codes 2 and 3: the byte count (up to the space, as the digits sent, `lpd.byte_count`) and the file name
  (up to the LF, `lpd.file_name`).

## Shared keys

None.

## Not mapped

- **The byte count as a number**: the pack reads text up to a terminator, and a decimal text to integer
  transform exists on the `text` wire only; the count is the digits as text.
- **The file contents** that follow the subcommand, the zero octet after them and the acknowledgements:
  the control file is `lpd-control-file`; the data file is any octets.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the subcommand's octets, LF included.

## Vectors

`tools/gen/printing-vectors.py`, without an engine: abort; receive control file; receive data file with a
zero count; code 4 (`no-kind`); a control file subcommand without its name (`malformed-wire`).

## Kind on encode from another format

The kind is the one whose value `lpd.subcommand_code` holds (the code octet, `when ... as`), and
its `requires` line names the fields that kind always has.
An entity that fits no kind is `no-kind`.
