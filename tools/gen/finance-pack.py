#!/usr/bin/env python3
"""Write the finance message packs and their modules:

- fix-message: a FIX tag=value message: BeginString (8), BodyLength (9) and MsgType (35) by name, then
  every other field as a tag and its value, each field ended by SOH (0x01), the CheckSum (10) last
  among them. Layout restated from simplefix (simplefix/parser.py, message.py, constants.py).
- qif-record: one QIF record (a transaction of a bank or cash account, or a header line): its lines,
  each a one-character code and its value up to LF, the record ended by the '^' line; the value's key
  by the code. Codes restated from quiffen (quiffen/core/transaction.py, qif.py).
- ofx-stmttrn: one OFX 2 <STMTTRN> statement transaction element (XML, no namespace): TRNTYPE,
  DTPOSTED, TRNAMT, FITID, CHECKNUM, NAME, MEMO. Element names and order restated from
  ofxparse (ofxparse/ofxparse.py and its test fixtures).

The vectors are not written here: tools/gen/finance-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/finance-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SF = "007e3d7ffe904bcb2cfbfcb7ee8a4c13c5f3ea0a"
OP = "25aa80072be71da9f4ea0924ae1d1aaea2d5820c"
QF = "29658502eb3823f2a50a3365e95bf809a4841bb4"
SRC = {
    "fix": ('source        "simplefix, https://github.com/da4089/simplefix at commit %s, simplefix/parser.py, message.py and '
            'constants.py (MIT License); layout restated, no code copied; the FIX Trading Community specification not used"' % SF),
    "qif": ('source        "quiffen, https://github.com/isaacharrisholt/quiffen at commit %s, quiffen/core/transaction.py and qif.py '
            '(MIT License, Copyright (c) 2023 Isaac Harris-Holt); codes restated, no code copied"' % QF),
    "ofx": ('source        "ofxparse, https://github.com/jseutter/ofxparse at commit %s, ofxparse/ofxparse.py and tests/fixtures/*.ofx '
            '(MIT License, Copyright (c) 2009 Jerry Seutter); element names and order restated, no code copied; the OFX specification '
            'not used"' % OP),
}


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for t, k, d in keys:
        L.append('list  %-*s  "%s"' % (w, k, d) if t == "list" else 'key   %-*s  %-6s  -  "%s"' % (w, k, t, d))
    return "\n".join(L) + "\n"


def bits_head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", src] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


# ---------------------------------------------------------------- FIX

def fix_pack():
    L = bits_head("fix-message", ["FIX tag=value message: BeginString, BodyLength, MsgType, then every field as tag and value, SOH-separated.",
                                  "Written by tools/gen/finance-pack.py; do not edit by hand."], SRC["fix"], ["fix"])
    L += ["kind  fix", "when  16  14397", "field  fix.begin_string  until:1  chars:ascii8", "const  16  14653",
          "field  fix.body_length  until:1  chars:ascii8", "const  24  3355965", "field  fix.msg_type  until:1  chars:ascii8",
          "group  fix.fields  rest", "  field  fix.tag  until:61  chars:ascii8", "  field  fix.value  until:1  chars:ascii8", "end"]
    return "\n".join(L) + "\n"


FIX_KEYS = [
    ("string", "begin_string", "tag 8, BeginString: the protocol version (FIX.4.2, FIX.4.4, FIXT.1.1 ...)"),
    ("string", "body_length", "tag 9, BodyLength: the octets from after this field to before the CheckSum, as the digits sent (not computed)"),
    ("string", "msg_type", "tag 35, MsgType (0 heartbeat, A logon, D new order single, 8 execution report ...)"),
    ("list", "fields", "every field after MsgType, in order, the CheckSum (tag 10) last"),
    ("string", "tag", "a field's tag number, as the digits sent"),
    ("string", "value", "a field's value, as sent"),
]


# ---------------------------------------------------------------- QIF

QIF_CODES = [("D", "date"), ("T", "amount"), ("U", "amount_u"), ("M", "memo"), ("C", "cleared"), ("P", "payee"), ("A", "payee_address"),
             ("L", "category"), ("N", "number"), ("S", "split_category"), ("E", "split_memo"), ("$", "split_amount"),
             ("%", "split_percent"), ("F", "reimbursable"), ("1", "first_payment_date"), ("2", "loan_length"), ("3", "num_payments"),
             ("4", "periods_per_annum"), ("5", "interest_rate"), ("6", "current_loan_balance"), ("7", "original_loan_amount"),
             ("X", "invoice"), ("!", "header"), ("^", "end")]


def qif_pack():
    L = bits_head("qif-record", ["QIF record: its lines, each a code character and the value up to LF, ended by the '^' line. Written by",
                                 "tools/gen/finance-pack.py; do not edit by hand."], SRC["qif"], ["qif"])
    L += ["group  qif.lines  rest", "  field  qif.code  8  uint", "  switch  qif.code"]
    for ch, key in QIF_CODES:
        L += ["    case  %d" % ord(ch), "      field  qif.%s  until:10  chars:ascii8" % key]
    L += ["    else", "      field  qif.other  until:10  chars:ascii8", "  end", "end"]
    return "\n".join(L) + "\n"


QIF_DESC = {
    "date": "D: the date, as written (formats vary: 01/31/2025, 31/01'25 ...)",
    "amount": "T: the amount, as written", "amount_u": "U: the amount (a second form some exporters write), as written",
    "memo": "M: the memo", "cleared": "C: the cleared status (*, c, X, R or empty)", "payee": "P: the payee",
    "payee_address": "A: a line of the payee's address", "category": "L: the category, or [account] for a transfer",
    "number": "N: the check number or reference", "split_category": "S: a split's category or [account]",
    "split_memo": "E: a split's memo", "split_amount": "$: a split's amount", "split_percent": "%: a split's percentage",
    "reimbursable": "F: reimbursable business expense flag", "first_payment_date": "1: loan first payment date",
    "loan_length": "2: loan length", "num_payments": "3: number of payments", "periods_per_annum": "4: periods per annum",
    "interest_rate": "5: interest rate", "current_loan_balance": "6: current loan balance", "original_loan_amount": "7: original loan amount",
    "invoice": "X: an invoice line (Quicken business versions)", "header": "!: a header line (Type:Bank, Type:Cash, Account ...), after the '!'",
    "end": "^: the end of the record (normally empty after the '^')",
}
QIF_KEYS = ([("list", "lines", "the record's lines, in order"), ("int", "code", "a line's code character, its ASCII code (68 D, 84 T, 94 ^ ...)")] +
            [("string", key, QIF_DESC[key]) for _, key in QIF_CODES] + [("string", "other", "a line with another code: its value")])


# ---------------------------------------------------------------- OFX

OFX = [("TRNTYPE", "trntype", "transaction type (CREDIT, DEBIT, CHECK, INT, DIV, FEE, SRVCHG, DEP, ATM, POS, XFER, PAYMENT, CASH, DIRECTDEP, DIRECTDEBIT, REPEATPMT, OTHER)"),
       ("DTPOSTED", "dtposted", "date posted, OFX date-time text (YYYYMMDDHHMMSS.XXX[gmt offset:tz])"),
       ("DTUSER", "dtuser", "date the user initiated the transaction, OFX date-time text"),
       ("TRNAMT", "trnamt", "amount, decimal text (negative for debits)"),
       ("FITID", "fitid", "financial institution transaction ID"),
       ("CHECKNUM", "checknum", "check number"), ("NAME", "name", "payee name"), ("MEMO", "memo", "memo")]


# The key stays (a merged key is never removed); no XML source read gives the element's place, so it is not mapped.
OFX_UNPLACED = {"DTUSER"}


def ofx_pack():
    L = ["# One OFX 2 statement transaction element <STMTTRN> (XML). Written by tools/gen/finance-pack.py; do not edit by hand.",
         "format        ofx-stmttrn", "version       0.1.0", "distribution  public", SRC["ofx"], "uses          ofx", "wire          xml",
         "root          STMTTRN", ""]
    L += ["field  ofx.%s  %s/#text  string" % (key, el) for el, key, _ in OFX if el not in OFX_UNPLACED]
    return "\n".join(L) + "\n"


OFX_KEYS = [("string", key, "%s: %s" % (el, desc)) for el, key, desc in OFX]


def build(out):
    out.write("packs/fix-message/pack.def", fix_pack())
    out.write("packs/qif-record/pack.def", qif_pack())
    out.write("packs/ofx-stmttrn/pack.def", ofx_pack())
    out.write("model/fix.def", module("fix", ["# The fix module: FIX tag=value message fields. Written by tools/gen/finance-pack.py."], SRC["fix"], FIX_KEYS))
    out.write("model/qif.def", module("qif", ["# The qif module: QIF record lines. Written by tools/gen/finance-pack.py."], SRC["qif"], QIF_KEYS))
    out.write("model/ofx.def", module("ofx", ["# The ofx module: OFX STMTTRN elements. Written by tools/gen/finance-pack.py."], SRC["ofx"], OFX_KEYS))
    return {"finance": 6}


def main(argv=None):
    return genio.vector_main("finance-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
