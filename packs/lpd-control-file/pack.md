# Pack: lpd-control-file

An LPD control file (RFC 1179 section 7): its lines in order, each a single command character, the operand
and LF. Wire `bits`, `layout sequential`: a `rest` list of lines, each the command character (`lpd.command`,
its code) and the operand up to LF (`until:10 chars:ascii8`), the operand's key chosen by the command. One
message is one whole control file. Written by `tools/gen/printing-pack.py`.

## What is mapped

- C banner class, H host, I indent, J job name, L banner user, M mail user, N source file name, P user,
  S symbolic link data, T title, U unlink file, W width: each its own key.
- 1 to 4, the troff R, I, B and S fonts: `lpd.font_file` (the command says which).
- c, d, f, g, l, n, o, p, r, t, v, the print and plot commands: `lpd.print_file` (the command says how).
- Any other character, the reserved k and z included: `lpd.operand`.
- An omitted operand (C, J and L may be empty) is an empty line after the character; it decodes as absent
  and writes back as the character and LF.

## Shared keys

None.

## Not mapped

- **One line on the `text` wire.** A text-wire column pads its value to the column width on encode, so a
  line of free length would not write back as read; the control file is read as octets instead.
- **I and W as numbers**: the digits as text (see `lpd-subcommand`).
- **S split into device and inode**: one text.
- **Lengths** (31 octets for host and user, 99 for the job name, 131 for the source file name, 79 for the
  title): not checked.
- **Rules across lines** (H and P required, at least one print command): not checked.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the file's octets.

## Vectors

`tools/gen/printing-vectors.py`, without an engine: a print job; the parameter lines; the font lines, a
troff file, the reserved k and z and an undefined character; omitted operands; a last line without LF
(`malformed-wire`); a tab in an operand (`transform-decode`).
