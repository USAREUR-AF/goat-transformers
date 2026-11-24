#!/usr/bin/env python3
"""Write the printing packs and their modules:

- ipp-message: the IPP/1.1 binary encoding (RFC 8010 section 3): version, operation-id or
  status-code, request-id, then the delimiter tags and attributes in order, each attribute a
  value tag, a name-length and name, a value-length and value; the value read by its tag where
  the encoding fixes its layout (integer, enum, boolean, resolution, rangeOfInteger,
  textWithLanguage, nameWithLanguage); the document data after the end-of-attributes tag.
- lpd-command: the LPD daemon commands (RFC 1179 section 5), a binary code octet and LF-ended text.
- lpd-subcommand: the receive-job subcommands (RFC 1179 section 6).
- lpd-control-file: an LPD control file (RFC 1179 section 7), its LF-ended lines as a list. Binary
  like the others: a text-wire column pads its value on encode, which a line of free length cannot have.

The vectors are not written here: tools/gen/printing-vectors.py derives them with an encoder of
its own.

Usage: python3 -I tools/gen/printing-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SRC = {
    "ipp": ('source        "IETF RFC 8010, Internet Printing Protocol/1.1: Encoding and Transport, January 2017, sections 3.1-3.10, '
            'https://www.rfc-editor.org/rfc/rfc8010.txt; RFC 8011 section 5.1.16 for the resolution units, https://www.rfc-editor.org/rfc/rfc8011.txt; layout restated"'),
    "lpd": ('source        "IETF RFC 1179, Line Printer Daemon Protocol, August 1990, sections 3.1 and 5-7, '
            'https://www.rfc-editor.org/rfc/rfc1179.txt; layout restated"'),
}


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def sw(key, cases, other=None):
    L = ["switch  %s" % key]
    for vals, lines in cases:
        L.append("  case  %s" % vals)
        L += ind(2, lines)
    if other is not None:
        L.append("  else")
        L += ind(2, other)
    L.append("end")
    return L


def F(k, b, tr="uint"):
    return "field  %s  %d  %s" % (k, b, tr)


def octets(lst, octet="ipp.octet"):
    return ["group  %s  rest" % lst, "  " + F(octet, 8), "end"]


def bits_head(name, comment, src, uses):
    return (["# %s" % c for c in comment] +
            ["format        %s" % name, "version       0.1.0", "distribution  public", SRC[src]] +
            ["uses          %s" % u for u in uses] + ["wire          bits", "layout        sequential", "bit_order     msb", ""])


def module(name, header, src, keys):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", SRC[src]]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], k[0], k[2]))
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- IPP

DELIMS = ",".join(str(t) for t in range(16) if t != 3)


def ipp_value():
    """The value, read by the attribute's value tag."""
    lw = ["length  16  bytes"] + ind(1, octets("ipp.language")) + ["end",
          "length  16  bytes"] + ind(1, octets("ipp.text")) + ["end"]
    return sw("ipp.tag", [
        ("33,35", [F("ipp.integer", 32, "twos")]),
        ("34", [F("ipp.boolean", 8)]),
        ("50", [F("ipp.cross_feed_resolution", 32, "twos"), F("ipp.feed_resolution", 32, "twos"), F("ipp.resolution_units", 8, "twos")]),
        ("51", [F("ipp.range_lower", 32, "twos"), F("ipp.range_upper", 32, "twos")]),
        ("53,54", lw)],
        octets("ipp.value"))


def ipp_pack():
    L = bits_head("ipp-message", ["IPP/1.1 request or response in the binary encoding of RFC 8010: the header, then each delimiter tag and",
                                  "attribute in order, then the document data. Written by tools/gen/printing-pack.py; do not edit by hand."],
                  "ipp", ["ipp"])
    L += [F("ipp.version_major", 8), F("ipp.version_minor", 8), F("ipp.operation_or_status", 16, "twos"), F("ipp.request_id", 32, "twos"),
          "group  ipp.items  rest"]
    item = [F("ipp.tag", 8)] + sw("ipp.tag", [
        ("3", octets("ipp.data")),
        (DELIMS, [])],
        ["length  16  bytes"] + ind(1, octets("ipp.name")) + ["end", "length  16  bytes"] + ind(1, ipp_value()) + ["end"])
    L += ind(1, item) + ["end"]
    return "\n".join(L) + "\n"


IPP_KEYS = [
    ("int", "version_major", "major version number (1 for IPP/1.1)"),
    ("int", "version_minor", "minor version number"),
    ("int", "operation_or_status", "a request's operation-id or a response's status-code (the encoding does not say which; the transport does)"),
    ("int", "request_id", "request-id, chosen by the client and echoed in the response"),
    ("list", "items", "the delimiter tags and attributes in message order"),
    ("int", "tag", "the item's first octet: 0x00-0x0f a delimiter tag (1 operation, 2 job, 3 end of attributes, 4 printer, 5 unsupported attributes), 0x10-0xff an attribute's value tag"),
    ("list", "name", "the attribute name, as octets (empty for an additional value of the attribute before it)"),
    ("int", "integer", "value of an integer (0x21) or enum (0x23) attribute"),
    ("int", "boolean", "value of a boolean attribute (0x22): 0 false, 1 true"),
    ("int", "cross_feed_resolution", "resolution (0x32): cross-feed direction resolution"),
    ("int", "feed_resolution", "resolution (0x32): feed direction resolution"),
    ("int", "resolution_units", "resolution (0x32): the units value (3 dots per inch, 4 dots per centimetre, RFC 8011 section 5.1.16)"),
    ("int", "range_lower", "rangeOfInteger (0x33): lower bound"),
    ("int", "range_upper", "rangeOfInteger (0x33): upper bound"),
    ("list", "language", "textWithLanguage or nameWithLanguage (0x35, 0x36): the natural language, as octets"),
    ("list", "text", "textWithLanguage or nameWithLanguage (0x35, 0x36): the text or name, as octets"),
    ("list", "value", "any other attribute value (strings, keyword, uri, charset, octetString, dateTime, collection delimiters, out-of-band tags), as octets"),
    ("list", "data", "the document data after the end-of-attributes tag, as octets"),
    ("int", "octet", "one octet"),
]


# ---------------------------------------------------------------- LPD

def until(k, code=10):
    return "field  %s  until:%d  chars:ascii8" % (k, code)


DAEMON = [
    ("print-waiting-jobs", 1, [until("lpd.queue")]),
    ("receive-job", 2, [until("lpd.queue")]),
    ("send-queue-state-short", 3, [until("lpd.operands")]),
    ("send-queue-state-long", 4, [until("lpd.operands")]),
    ("remove-jobs", 5, [until("lpd.operands")]),
]

SUB = [
    ("abort-job", 1, ["const  8  10"]),
    ("receive-control-file", 2, [until("lpd.byte_count", 32), until("lpd.file_name")]),
    ("receive-data-file", 3, [until("lpd.byte_count", 32), until("lpd.file_name")]),
]


def lpd_bits_pack(name, comment, kinds, code_key):
    L = bits_head(name, comment, "lpd", ["lpd"])
    for kname, code, lines in kinds:
        L += ["kind  %s" % kname, "when  8  %d  as  %s" % (code, code_key)]
        needs = [x.split()[1] for x in lines if x.startswith("field")]
        L += (["requires  " + "  ".join(needs)] if needs else []) + lines + [""]
    return "\n".join(L).rstrip("\n") + "\n"


# command character, key of its operand
CONTROL = [("C", "banner_class"), ("H", "host"), ("I", "indent"), ("J", "job_name"), ("L", "banner_user"), ("M", "mail_user"),
           ("N", "source_file_name"), ("P", "user"), ("S", "symlink_data"), ("T", "title"), ("U", "unlink_file"), ("W", "width")]
FONTS = "1234"
PRINTS = "cdfglnoprtv"


def control_pack():
    cases = [(str(ord(c)), [until("lpd." + k)]) for c, k in CONTROL]
    cases.append((",".join(str(ord(c)) for c in FONTS), [until("lpd.font_file")]))
    cases.append((",".join(str(ord(c)) for c in PRINTS), [until("lpd.print_file")]))
    L = bits_head("lpd-control-file", ["An LPD control file (RFC 1179 section 7): its lines in order, each a command character, its operand and LF.",
                                       "Written by tools/gen/printing-pack.py; do not edit by hand."], "lpd", ["lpd"])
    L += ["group  lpd.lines  rest"] + ind(1, [F("lpd.command", 8)] + sw("lpd.command", cases, [until("lpd.operand")])) + ["end"]
    return "\n".join(L) + "\n"


LPD_KEYS = [
    ("int", "command_code", "daemon command: the code octet, 1 to 5"),
    ("int", "subcommand_code", "receive job subcommand: the code octet, 1 to 3"),
    ("string", "queue", "daemon commands 1 and 2: the printer queue name"),
    ("string", "operands", "daemon commands 3, 4 and 5: the queue name and the other operands (agent, user names, job numbers) as sent, separated by white space"),
    ("string", "byte_count", "receive control file or data file: the number of octets of the file, as the decimal digits sent"),
    ("string", "file_name", "receive control file or data file: the file name (cfA or dfA, a three-digit job number, the host name)"),
    ("string", "banner_class", "control line C: class name for the banner page"),
    ("string", "host", "control line H: the host to treat as the source of the job"),
    ("list", "lines", "the lines of the control file, in order"),
    ("int", "command", "control line: the command character's code (for example 72 H, 80 P, 102 f)"),
    ("string", "operand", "control line with another command character (k and z are reserved, others are not in RFC 1179): the operand"),
    ("string", "indent", "control line I: indenting count in columns, as the decimal digits sent"),
    ("string", "job_name", "control line J: job name for the banner page"),
    ("string", "banner_user", "control line L: print the banner page, with this user name"),
    ("string", "mail_user", "control line M: the user to mail when printing ends"),
    ("string", "source_file_name", "control line N: the name of the file the data file was made from"),
    ("string", "user", "control line P: the user identification of the requester"),
    ("string", "symlink_data", "control line S: device number and inode number, as sent"),
    ("string", "title", "control line T: title for pr"),
    ("string", "unlink_file", "control line U: a data file no longer needed"),
    ("string", "width", "control line W: width of output in columns, as the decimal digits sent"),
    ("string", "font_file", "control lines 1 to 4: the troff R, I, B or S font file (the kind says which)"),
    ("string", "print_file", "control lines in lower case: the data file to print or plot (the kind says how)"),
]


def build(out):
    out.write("packs/ipp-message/pack.def", ipp_pack())
    out.write("packs/lpd-command/pack.def", lpd_bits_pack("lpd-command", [
        "LPD daemon command (RFC 1179 section 5): a binary command code, the queue name and any operands, LF. Written by",
        "tools/gen/printing-pack.py; do not edit by hand."], DAEMON, "lpd.command_code"))
    out.write("packs/lpd-subcommand/pack.def", lpd_bits_pack("lpd-subcommand", [
        "LPD receive-job subcommand (RFC 1179 section 6): a binary code, the byte count and file name, LF. Written by",
        "tools/gen/printing-pack.py; do not edit by hand."], SUB, "lpd.subcommand_code"))
    out.write("packs/lpd-control-file/pack.def", control_pack())
    out.write("model/ipp.def", module("ipp", ["# The ipp module: IPP/1.1 binary encoding fields (RFC 8010). Written by tools/gen/printing-pack.py."], "ipp", IPP_KEYS))
    out.write("model/lpd.def", module("lpd", ["# The lpd module: Line Printer Daemon protocol fields (RFC 1179). Written by tools/gen/printing-pack.py."], "lpd", LPD_KEYS))
    return {"printing": 6}


def main(argv=None):
    return genio.vector_main("printing-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
