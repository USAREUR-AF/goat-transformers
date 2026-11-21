# Pack: ofx-stmttrn

One OFX 2 statement transaction, the `<STMTTRN>` element of a bank or credit card statement (XML, no
namespace). Wire `xml`, root `STMTTRN`. Written by `tools/gen/finance-pack.py`.

## What is mapped

TRNTYPE, DTPOSTED, DTUSER, TRNAMT, FITID, CHECKNUM, NAME and MEMO, each its element text, in that order
(the order the source's sample statements use).

## Shared keys

None. DTPOSTED is OFX date-time text (YYYYMMDDHHMMSS with optional fraction and time zone in brackets),
not ISO 8601, so it is not bound to `time_ms`.

## Not mapped

- **The rest of the OFX document** (signon, statement response, balances, the transaction list around
  this element): one message is one transaction.
- **OFX 1.x SGML** (elements without end tags): not XML; the xml wire refuses it.
- **Other STMTTRN elements** (SIC, PAYEEID, REFNUM, SRVRTID, CURRENCY, PAYEE, BANKACCTTO ...): the source
  does not give their place in the order; they are residue of the xml wire.
- Values typed (amounts and dates are text).

## Message convention

`input` and `expect` are the element as XML text.

## Vectors

`tools/gen/finance-vectors.py`, without an engine: a debit; a check with the user date and check number; a
minimal credit.
