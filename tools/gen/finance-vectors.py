#!/usr/bin/env python3
"""finance-vectors: write the vectors of fix-message, qif-record and ofx-stmttrn.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are this
program's own restatement of:
- simplefix: a FIX message is fields "tag=value" each ended by SOH (0x01); BeginString (8) first,
  BodyLength (9) second, MsgType (35) third, CheckSum (10) last; the body length counts the octets
  after the BodyLength field up to the CheckSum field, and the checksum is the sum of every octet
  before the CheckSum field modulo 256, three digits;
- quiffen: a QIF record is lines of a code character and a value, ended by a line '^'; the codes D, T,
  U, M, C, P, A, L, N, S, E, $, %, F, 1-7 and X; header lines begin with '!';
- ofxparse and its fixtures: a statement transaction <STMTTRN> holds TRNTYPE, DTPOSTED, TRNAMT,
  FITID, CHECKNUM, NAME and MEMO, in that order.

Inputs: values chosen here; no message is taken from a document or a capture. The FIX body length and
checksum are computed here. Names and amounts are invented. `expect` of a round trip is the input.
`model` holds values that were packed.

Usage: python3 -I tools/gen/finance-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/finance-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_F = "simplefix parser.py and message.py"
R_Q = "quiffen core/transaction.py and qif.py"
R_O = "ofxparse ofxparse.py and its test fixtures"


def vec(pack, name, inp, model=None, error=None, ref="", note="", text=False):
    v = {"name": name, "from": pack, "to": pack, "input": inp if text else inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = inp if text else inp.hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


SOH = b"\x01"


def fix(begin, msgtype, fields):
    body = b"35=" + msgtype.encode() + SOH + b"".join(("%d=%s" % (t, v)).encode() + SOH for t, v in fields)
    head = b"8=" + begin.encode() + SOH + b"9=" + str(len(body)).encode() + SOH
    msg = head + body
    return msg + b"10=" + ("%03d" % (sum(msg) % 256)).encode() + SOH


def fix_vectors():
    P = "fix-message"
    out = []
    a = fix("FIX.4.4", "A", [(49, "CLIENT"), (56, "BROKER"), (34, "1"), (52, "20250115-12:30:00.000"), (98, "0"), (108, "30")])
    out.append(("01-logon-roundtrip.json", vec(P, "logon-roundtrip", a,
                {"@kind": "fix", "fix.begin_string": "FIX.4.4", "fix.msg_type": "A", "fix.fields.#": "7",
                 "fix.fields[0].fix.tag": "49", "fix.fields[0].fix.value": "CLIENT", "fix.fields[6].fix.tag": "10"},
                ref=R_F, note="a logon with heartbeat interval 30; body length and checksum computed")))
    b = fix("FIX.4.4", "D", [(49, "CLIENT"), (56, "BROKER"), (34, "2"), (52, "20250115-12:30:01.000"), (11, "ORD0001"), (55, "XYZ"),
                             (54, "1"), (60, "20250115-12:30:01.000"), (38, "100"), (40, "2"), (44, "10.25")])
    out.append(("02-new-order-single-roundtrip.json", vec(P, "new-order-single-roundtrip", b,
                {"fix.msg_type": "D", "fix.fields.#": "12", "fix.fields[4].fix.tag": "11", "fix.fields[4].fix.value": "ORD0001"},
                ref=R_F, note="a limit order to buy 100 of an invented symbol at 10.25")))
    c = fix("FIX.4.2", "0", [(49, "A"), (56, "B"), (34, "3"), (52, "20250115-12:31:00")])
    out.append(("03-heartbeat-fix42-roundtrip.json", vec(P, "heartbeat-fix42-roundtrip", c, {"fix.begin_string": "FIX.4.2", "fix.msg_type": "0"},
                ref=R_F, note="a FIX 4.2 heartbeat")))
    out.append(("04-not-begin-string-is-no-kind.json", vec(P, "not-begin-string-is-no-kind", b"9=5" + SOH + b"35=0" + SOH, error="no-kind",
                ref=R_F, note="the message does not begin with tag 8")))
    out.append(("05-field-without-soh-is-malformed.json", vec(P, "field-without-soh-is-malformed", a[:-1], error="malformed-wire",
                ref=R_F, note="the CheckSum field is not ended by SOH")))
    return P, out


def qif(lines):
    return "".join(l + "\n" for l in lines).encode("ascii")


def qif_vectors():
    P = "qif-record"
    out = []
    a = qif(["D01/31/2025", "T-45.67", "CX", "N1042", "PCorner Grocery", "MWeekly shop", "LFood:Groceries", "^"])
    out.append(("01-bank-transaction-roundtrip.json", vec(P, "bank-transaction-roundtrip", a,
                {"qif.lines.#": "8", "qif.lines[0].qif.code": "68", "qif.lines[0].qif.date": "01/31/2025", "qif.lines[1].qif.amount": "-45.67",
                 "qif.lines[2].qif.cleared": "X", "qif.lines[4].qif.payee": "Corner Grocery", "qif.lines[6].qif.category": "Food:Groceries",
                 "qif.lines[7].qif.code": "94"}, ref=R_Q, note="a cleared bank transaction with a category")))
    b = qif(["!Type:Bank", "D02/01/2025", "T-100.00", "PUtility Co", "SHousehold:Electric", "$-60.00", "EPower", "SHousehold:Gas", "$-40.00", "^"])
    out.append(("02-header-and-splits-roundtrip.json", vec(P, "header-and-splits-roundtrip", b,
                {"qif.lines[0].qif.header": "Type:Bank", "qif.lines[4].qif.split_category": "Household:Electric",
                 "qif.lines[5].qif.split_amount": "-60.00", "qif.lines[6].qif.split_memo": "Power"},
                ref=R_Q, note="a header line, then a transaction split in two")))
    c = qif(["D03/01/2025", "T500.00", "L[Savings]", "^"])
    out.append(("03-transfer-roundtrip.json", vec(P, "transfer-roundtrip", c, {"qif.lines[2].qif.category": "[Savings]"},
                ref=R_Q, note="a transfer to another account")))
    out.append(("04-line-without-lf-is-malformed.json", vec(P, "line-without-lf-is-malformed", b"D01/31/2025\nT-1.00", error="malformed-wire",
                ref=R_Q, note="the last line has no LF")))
    return P, out


def stmttrn(**kw):
    order = ["TRNTYPE", "DTPOSTED", "TRNAMT", "FITID", "CHECKNUM", "NAME", "MEMO"]
    return "<STMTTRN>" + "".join("<%s>%s</%s>" % (k, kw[k], k) for k in order if k in kw) + "</STMTTRN>"


def ofx_vectors():
    P = "ofx-stmttrn"
    out = []
    a = stmttrn(TRNTYPE="DEBIT", DTPOSTED="20250115120000.000", TRNAMT="-34.51", FITID="0000487", NAME="ELECTRIC CO", MEMO="Monthly bill")
    out.append(("01-debit-roundtrip.json", vec(P, "debit-roundtrip", a,
                {"ofx.trntype": "DEBIT", "ofx.dtposted": "20250115120000.000", "ofx.trnamt": "-34.51", "ofx.fitid": "0000487",
                 "ofx.name": "ELECTRIC CO", "ofx.memo": "Monthly bill"}, ref=R_O, note="a debit with name and memo", text=True)))
    b = stmttrn(TRNTYPE="CHECK", DTPOSTED="20250120", TRNAMT="-25.00", FITID="0000488", CHECKNUM="319", NAME="Check 319")
    out.append(("02-check-roundtrip.json", vec(P, "check-roundtrip", b,
                {"ofx.trntype": "CHECK", "ofx.checknum": "319"}, ref=R_O,
                note="a check with the check number", text=True)))
    c = stmttrn(TRNTYPE="CREDIT", DTPOSTED="20250131", TRNAMT="0.01", FITID="0000489")
    out.append(("03-minimal-credit-roundtrip.json", vec(P, "minimal-credit-roundtrip", c, {"ofx.trnamt": "0.01"}, ref=R_O,
                note="the required elements only", text=True)))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (fix_vectors(), qif_vectors(), ofx_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("finance-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
