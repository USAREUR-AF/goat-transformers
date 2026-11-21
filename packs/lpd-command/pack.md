# Pack: lpd-command

An LPD daemon command (RFC 1179 section 5): one binary code octet, then the queue name and any operands,
ended by LF. Wire `bits`, `layout sequential`; the text is `until:10 chars:ascii8`. Kinds by the code: 1
`print-waiting-jobs`, 2 `receive-job`, 3 `send-queue-state-short`, 4 `send-queue-state-long`, 5
`remove-jobs`. One message is one command line. Written by `tools/gen/printing-pack.py`.

## What is mapped

- Codes 1 and 2: the queue name (`lpd.queue`).
- Codes 3, 4 and 5: the queue name and the other operands as one text (`lpd.operands`), as sent.

## Shared keys

None.

## Not mapped

- **The operands of 3, 4 and 5 one by one.** For 3 and 4 the list after the queue is optional, so the
  queue ends at a space or at the LF; a text field that ends at either of two codes is not in the pack
  language. The operands are kept whole. RFC 1179 allows horizontal tab, vertical tab and form feed as
  white space too; those are outside `ascii8` and fail to decode.
- **The acknowledgement octet** and the queue state reply (a free text stream until the connection
  closes).
- The receive-job subcommands are `lpd-subcommand`, since they reuse codes 1 to 3 with other meanings.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the command's octets, LF included.

## Vectors

`tools/gen/printing-vectors.py`, without an engine: each of the five commands (3 with a list, 4 without);
code 6 (`no-kind`); a command without its LF (`malformed-wire`).
