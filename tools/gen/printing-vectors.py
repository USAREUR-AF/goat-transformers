#!/usr/bin/env python3
"""printing-vectors: write the vectors of ipp-message, lpd-command, lpd-subcommand and lpd-control-file.

Python 3 standard library only; imports no engine and reads no pack.def. The layouts below are
this program's own restatement of RFC 8010 section 3 (IPP: two version octets, a 16-bit
operation-id or status-code, a 32-bit request-id, then delimiter tags 0x00-0x0f and attributes,
each a value tag, a 16-bit name length and the name, a 16-bit value length and the value; the
end-of-attributes tag 0x03 and the document data after it; every integer big-endian and signed)
and RFC 1179 sections 5-7 (LPD: a binary command code octet, operands, LF; a control file of
lines, each a command character, its operand and LF).

Inputs: messages built here field by field from values chosen here; no message is taken from a
document or a capture. Host names are under example.com (RFC 2606), users and files invented.

`expect` of a round trip is this program's packing of the decoded values, which for these
messages is the input, except vector 06 of ipp-message: an integer attribute whose value is
empty is written back with the four octets an integer has, as zeros, because encode writes every
line of a length block and an absent line as zero bits (ruling 7 of 0.8 of the specification).
`model` holds values that were packed.

Usage: python3 -I tools/gen/printing-vectors.py [--out DIR] [--check]
With --check nothing is written and the exit status is 1 when a committed file differs.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE = "built by tools/gen/printing-vectors.py from values chosen there; layout restated from %s; expect derived there, no engine run"
R_IPP = "RFC 8010 section 3"
R_LPD = "RFC 1179 sections 3.1 and 5"
R_SUB = "RFC 1179 section 6"
R_CF = "RFC 1179 section 7"


def vec(pack, name, inp, model=None, error=None, ref="", expect=None, note=""):
    v = {"name": name, "from": pack, "to": pack, "input": inp.hex()}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = (expect if expect is not None else inp).hex()
    if model:
        v["model"] = model
    v["source"] = SOURCE % (ref + ("; " + note if note else ""))
    return v


# ---------------------------------------------------------------- IPP

def ipp(op_or_status, request_id, body, major=1, minor=1):
    return bytes([major, minor]) + struct.pack(">hi", op_or_status, request_id) + body


def attr(tag, name, value):
    return bytes([tag]) + struct.pack(">H", len(name)) + name + struct.pack(">H", len(value)) + value


def i32(v):
    return struct.pack(">i", v)


def with_lang(lang, text):
    return struct.pack(">H", len(lang)) + lang + struct.pack(">H", len(text)) + text


URI = b"ipp://printer.example.com/ipp/print"
OPS = (attr(0x47, b"attributes-charset", b"utf-8") + attr(0x48, b"attributes-natural-language", b"en") +
       attr(0x45, b"printer-uri", URI))


def ipp_vectors():
    P = "ipp-message"
    out = []
    a = ipp(0x000B, 1, b"\x01" + OPS + attr(0x44, b"requested-attributes", b"printer-state") + attr(0x44, b"", b"printer-name") + b"\x03")
    out.append(("01-get-printer-attributes-request-roundtrip.json", vec(P, "get-printer-attributes-request-roundtrip", a,
                {"ipp.version_major": "1", "ipp.version_minor": "1", "ipp.operation_or_status": "11", "ipp.request_id": "1",
                 "ipp.items.#": "7", "ipp.items[0].ipp.tag": "1", "ipp.items[1].ipp.tag": "71", "ipp.items[5].ipp.name.#": "0",
                 "ipp.items[6].ipp.tag": "3"},
                ref=R_IPP, note="operation 0x000B with the operation attributes group, a keyword with an additional value, the end tag and no data")))
    b = ipp(0, 1, b"\x01" + attr(0x47, b"attributes-charset", b"utf-8") + attr(0x48, b"attributes-natural-language", b"en") + b"\x04" +
            attr(0x23, b"printer-state", i32(3)) + attr(0x22, b"printer-is-accepting-jobs", b"\x01") +
            attr(0x21, b"queued-job-count", i32(-1)) + attr(0x32, b"printer-resolution-default", i32(600) + i32(1200) + b"\x03") +
            attr(0x33, b"copies-supported", i32(1) + i32(999)) + b"\x05" + attr(0x10, b"media-col", b"") + b"\x03")
    out.append(("02-printer-attributes-response-roundtrip.json", vec(P, "printer-attributes-response-roundtrip", b,
                {"ipp.operation_or_status": "0", "ipp.items[4].ipp.integer": "3", "ipp.items[5].ipp.boolean": "1",
                 "ipp.items[6].ipp.integer": "-1", "ipp.items[7].ipp.cross_feed_resolution": "600", "ipp.items[7].ipp.feed_resolution": "1200",
                 "ipp.items[7].ipp.resolution_units": "3", "ipp.items[8].ipp.range_lower": "1", "ipp.items[8].ipp.range_upper": "999",
                 "ipp.items[10].ipp.tag": "16", "ipp.items[10].ipp.value.#": "0"},
                ref=R_IPP, note="status 0 with enum, boolean, a negative integer, resolution, rangeOfInteger and an out-of-band unsupported value")))
    data = b"%!PS-Adobe-3.0\n"
    c = ipp(0x0002, 7, b"\x01" + OPS + attr(0x36, b"job-name", with_lang(b"fr", b"rapport")) + attr(0x49, b"document-format", b"application/postscript") +
            b"\x03" + data)
    out.append(("03-print-job-with-data-roundtrip.json", vec(P, "print-job-with-data-roundtrip", c,
                {"ipp.operation_or_status": "2", "ipp.request_id": "7", "ipp.items[4].ipp.language.#": "2", "ipp.items[4].ipp.text.#": "7",
                 "ipp.items[6].ipp.tag": "3", "ipp.items[6].ipp.data.#": str(len(data))},
                ref=R_IPP, note="Print-Job with a nameWithLanguage and document data after the end tag")))
    d = ipp(0, 2, b"\x01\x04\x03")
    out.append(("04-empty-groups-roundtrip.json", vec(P, "empty-groups-roundtrip", d, {"ipp.items.#": "3"},
                ref=R_IPP, note="two groups with no attributes, as section 3.3 allows")))
    e = ipp(0, 3, b"\x02" + attr(0x34, b"media-col", b"") + attr(0x4A, b"", b"media-size-name") + attr(0x44, b"", b"iso_a4_210x297mm") +
            attr(0x37, b"", b"") + b"\x03")
    out.append(("05-collection-as-flat-items-roundtrip.json", vec(P, "collection-as-flat-items-roundtrip", e,
                {"ipp.items[1].ipp.tag": "52", "ipp.items[2].ipp.tag": "74", "ipp.items[4].ipp.tag": "55"},
                ref=R_IPP + ".1.6", note="a collection: begCollection, a member name and value, endCollection, each one item")))
    f = ipp(0x000B, 4, b"\x01" + attr(0x21, b"a", b"") + b"\x03")
    out.append(("06-integer-without-value-gains-four-zero-octets.json", vec(P, "integer-without-value-gains-four-zero-octets", f,
                expect=ipp(0x000B, 4, b"\x01" + attr(0x21, b"a", i32(0)) + b"\x03"),
                ref=R_IPP, note="an integer tag with value length 0 (the encoding requires 4): the absent value is written as four zero octets (ruling 7 of 0.8)")))
    g = ipp(0x000B, 5, b"\x01" + attr(0x47, b"attributes-charset", b"utf-8"))[:-10]
    out.append(("07-cut-attribute-is-malformed.json", vec(P, "cut-attribute-is-malformed", g, error="malformed-wire",
                ref=R_IPP, note="the name length states 18 octets and fewer follow")))
    out.append(("08-short-header-is-malformed.json", vec(P, "short-header-is-malformed", b"\x01\x01\x00", error="malformed-wire",
                ref=R_IPP, note="three octets, the header has eight")))
    return P, out


# ---------------------------------------------------------------- LPD

def lpd_vectors():
    P = "lpd-command"
    out = []
    a = b"\x01lp\n"
    out.append(("01-print-waiting-jobs-roundtrip.json", vec(P, "print-waiting-jobs-roundtrip", a, {"lpd.queue": "lp"}, ref=R_LPD)))
    b = b"\x02draft-queue\n"
    out.append(("02-receive-job-roundtrip.json", vec(P, "receive-job-roundtrip", b, {"lpd.queue": "draft-queue"}, ref=R_LPD)))
    c = b"\x03lp alice 12 bob\n"
    out.append(("03-queue-state-short-with-list-roundtrip.json", vec(P, "queue-state-short-with-list-roundtrip", c,
                {"lpd.operands": "lp alice 12 bob"}, ref=R_LPD, note="the queue, then user names and a job number")))
    d = b"\x04lp\n"
    out.append(("04-queue-state-long-without-list-roundtrip.json", vec(P, "queue-state-long-without-list-roundtrip", d,
                {"lpd.operands": "lp"}, ref=R_LPD, note="the queue alone")))
    e = b"\x05lp root 31 alice\n"
    out.append(("05-remove-jobs-roundtrip.json", vec(P, "remove-jobs-roundtrip", e, {"lpd.operands": "lp root 31 alice"},
                ref=R_LPD, note="queue, agent, then a job number and a user name")))
    out.append(("06-unknown-code-is-no-kind.json", vec(P, "unknown-code-is-no-kind", b"\x06lp\n", error="no-kind",
                ref=R_LPD, note="code 6 is not a daemon command")))
    out.append(("07-command-without-lf-is-malformed.json", vec(P, "command-without-lf-is-malformed", b"\x02lp", error="malformed-wire",
                ref=R_LPD, note="the line feed that ends a command is missing")))
    return P, out


def sub_vectors():
    P = "lpd-subcommand"
    out = []
    out.append(("01-abort-job-roundtrip.json", vec(P, "abort-job-roundtrip", b"\x01\n", ref=R_SUB)))
    b = b"\x0247 cfA012host.example.com\n"
    out.append(("02-receive-control-file-roundtrip.json", vec(P, "receive-control-file-roundtrip", b,
                {"lpd.byte_count": "47", "lpd.file_name": "cfA012host.example.com"}, ref=R_SUB)))
    c = b"\x030 dfA012host.example.com\n"
    out.append(("03-receive-data-file-zero-count-roundtrip.json", vec(P, "receive-data-file-zero-count-roundtrip", c,
                {"lpd.byte_count": "0", "lpd.file_name": "dfA012host.example.com"}, ref=R_SUB, note="the count cleared to 0")))
    out.append(("04-unknown-code-is-no-kind.json", vec(P, "unknown-code-is-no-kind", b"\x04x\n", error="no-kind",
                ref=R_SUB, note="code 4 is not a subcommand")))
    out.append(("05-control-file-without-name-is-malformed.json", vec(P, "control-file-without-name-is-malformed", b"\x0247\n",
                error="malformed-wire", ref=R_SUB, note="the count is not followed by a space and a name")))
    return P, out


def cf_vectors():
    P = "lpd-control-file"
    out = []
    a = b"Hhost.example.com\nPalice\nJreport.txt\nCA\nLalice\nldfA012host.example.com\nUdfA012host.example.com\nNreport.txt\n"
    out.append(("01-print-job-roundtrip.json", vec(P, "print-job-roundtrip", a,
                {"lpd.lines.#": "8", "lpd.lines[0].lpd.command": "72", "lpd.lines[0].lpd.host": "host.example.com",
                 "lpd.lines[1].lpd.user": "alice", "lpd.lines[5].lpd.command": "108", "lpd.lines[5].lpd.print_file": "dfA012host.example.com"},
                ref=R_CF, note="host, user, banner lines, one file printed with control characters, unlink and source name")))
    b = b"Hh\nPp\nI8\nW132\nTQuarterly figures\nMalice\nS 2049 131074\nofile.ps\n"
    out.append(("02-parameters-roundtrip.json", vec(P, "parameters-roundtrip", b,
                {"lpd.lines[2].lpd.indent": "8", "lpd.lines[3].lpd.width": "132", "lpd.lines[4].lpd.title": "Quarterly figures",
                 "lpd.lines[6].lpd.symlink_data": " 2049 131074"},
                ref=R_CF, note="indent, width, title with a space, mail, symbolic link data, a PostScript file")))
    c = b"1times.r\n2times.i\n3times.b\n4special\ntdfA001h\nkticket\nzx\nXother\n"
    out.append(("03-fonts-reserved-and-other-roundtrip.json", vec(P, "fonts-reserved-and-other-roundtrip", c,
                {"lpd.lines[0].lpd.font_file": "times.r", "lpd.lines[4].lpd.print_file": "dfA001h", "lpd.lines[5].lpd.operand": "ticket",
                 "lpd.lines[7].lpd.command": "88", "lpd.lines[7].lpd.operand": "other"},
                ref=R_CF, note="the four troff font lines, a troff file, the reserved k and z, and a character the RFC does not define")))
    d = b"Hh\nPp\nC\nJ\nL\n"
    out.append(("04-empty-operands-roundtrip.json", vec(P, "empty-operands-roundtrip", d, {"lpd.lines.#": "5"},
                ref=R_CF, note="class, job name and banner user omitted, which section 7 allows")))
    out.append(("05-line-without-lf-is-malformed.json", vec(P, "line-without-lf-is-malformed", b"Hh\nPalice", error="malformed-wire",
                ref=R_CF, note="the last line has no line feed")))
    out.append(("06-tab-in-operand-is-transform-decode.json", vec(P, "tab-in-operand-is-transform-decode", b"Ta\tb\n",
                error="transform-decode", ref=R_CF, note="a horizontal tab in a title: the operand's character set is codes 32 to 126")))
    return P, out


def build(out):
    counts = {}
    for pack, vs in (ipp_vectors(), lpd_vectors(), sub_vectors(), cf_vectors()):
        for fname, v in vs:
            out.write("packs/%s/vectors/%s" % (pack, fname), json.dumps(v, indent=2) + "\n")
        counts[pack] = len(vs)
    return counts


def main(argv=None):
    return genio.vector_main("printing-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
