# Pack: qif-record

One QIF (Quicken Interchange Format) record of a bank, cash or credit card account, or a header line
before it: lines of a code character and a value, each ended by LF, the record ended by the `^` line.
Wire `bits`, `layout sequential`: a `rest` list of lines, each the code (its ASCII value) and the value up
to LF (`until:10 chars:ascii8`), the value's key chosen by the code. Written by `tools/gen/finance-pack.py`.

## What is mapped

D date, T and U amount, M memo, C cleared, P payee, A address line, L category or transfer account, N
number, S split category, E split memo, $ split amount, % split percent, F reimbursable flag, 1 to 7 the
loan fields, X invoice, `!` header, `^` end; any other code to `other`.

## Shared keys

None.

## Not mapped

- **Values typed**: dates (whose format varies by exporter), amounts and numbers are text as written.
- **Splits grouped**: each S, E, $ and % line is an item in order; which split a line belongs to follows
  from the order.
- **CR LF line endings** (the CR is outside `ascii8`): only LF is read; a file with CR LF needs the CR
  removed first.
- **Non-ASCII payees and memos** (Windows code pages): refused by `ascii8`.
- **Investment, category, class, memorized and security lists**: their records use the same line form
  with other meanings for some codes; they decode, but the keys are named for bank transactions.

## Message convention

`input` and `expect` are lowercase hexadecimal text of the record's octets.

## Vectors

`tools/gen/finance-vectors.py`, without an engine: a bank transaction; a header and a split transaction; a
transfer; a last line without LF (`malformed-wire`).
