#!/usr/bin/env python3
"""Write the amateur and paging radio packs and their modules: the AX.25 v2.2 frame, the KISS TNC
frame (unescaped), and the POCSAG batch.

AX.25 shifts each callsign character one bit left, so a callsign is six 7-bit characters each
followed by one bit; each character is its own field. The address field ends at the first address
whose extension bit is 1, so the repeaters are nested `switch` blocks, one per repeater, up to eight.
The control field's type is in its low bits, so the layout after it is a `switch` on the whole
octet's value. This script writes those blocks.
The vectors are not written here: tools/gen/radio-vectors.py derives them with an encoder of its own.

Usage: python3 -I tools/gen/radio-pack.py [--out DIR] [--check]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SHA = {
    "ax25": "af2070954468ef6498143ababf9beaf5d72b683ef82491dd7eb8e3670b29475c",
    "kiss": "a6a1627dbf1e64539a287d7cdb59dc3de618d15653e2df7fac2279ef1decd8ab",
    "m584": "3f9fb2fd0324ec9ecb37a4645ee24fc75d7d61424dbd6a8826df415bad955301",
}
SRC = {
    "ax25": 'source        "TAPR, AX.25 Link Access Protocol for Amateur Packet Radio, Version 2.2, Revision July 1998, sections 3 and 4, http://www.tapr.org/pdf/AX25.2.2.pdf as archived 2025-02-23 (sha256 %s), Copyright TAPR and ARRL, no licence stated; layout restated"' % SHA["ax25"],
    "kiss": 'source        "M. Chepponis and P. Karn, The KISS TNC: A simple Host-to-TNC communications protocol, ARRL 6th Computer Networking Conference 1987, HTML by KA9Q 1997, http://www.ka9q.net/papers/kiss.html (sha256 %s), no licence stated; layout restated"' % SHA["kiss"],
    "m584": 'source        "Recommendation ITU-R M.584-2 (11/1997), Codes and formats for radio paging, Annex 1 (radio-paging code No. 1, POCSAG), https://www.itu.int/dms_pubrec/itu-r/rec/m/R-REC-M.584-2-199711-I!!PDF-E.pdf (sha256 %s), ITU, no licence stated; layout restated"' % SHA["m584"],
}
A = "ax25"
K = "kiss"
P = "pocsag"
MAX_RPT = 8


def ind(n, lines):
    return ["  " * n + x if x else x for x in lines]


def F(mod, k, b, tr="uint"):
    return "field  %s.%s  %d  %s" % (mod, k, b, tr)


def octets(mod, lst):
    return ["group  %s.%s  rest" % (mod, lst), "  " + F(mod, "octet", 8), "end"]


def head(name, comment, sources, uses):
    L = ["# %s" % c for c in comment] + ["format        %s" % name, "version       0.1.0", "distribution  public"]
    L += [SRC[s] for s in sources]
    L += ["uses          %s" % u for u in uses]
    return L + ["wire          bits", "layout        sequential", "bit_order     msb", ""]


def text(L):
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- AX.25

def address(role, chbit):
    L = []
    for i in range(1, 7):
        L += [F(A, "%s_call_%d" % (role, i), 7, "chars:ascii7"), "pad  1"]
    return L + [F(A, "%s_%s" % (role, chbit), 1), F(A, "%s_reserved" % role, 2), F(A, "%s_ssid" % role, 4),
                F(A, "%s_ext" % role, 1)]


I_FRAMES = list(range(0, 256, 2))
UI = [0x03, 0x13]
INFO_ONLY = [0xAF, 0xBF, 0xE3, 0xF3, 0x87, 0x97]   # XID, TEST, FRMR


def after_address():
    def vals(v):
        return ",".join(str(x) for x in v)
    return ([F(A, "control", 8), "switch  ax25.control",
             "  case  %s" % vals(I_FRAMES + UI)] + ind(2, [F(A, "pid", 8)] + octets(A, "info")) +
            ["  case  %s" % vals(INFO_ONLY)] + ind(2, octets(A, "info")) + ["  else", "end"])


def repeaters(n):
    """Repeater n's address, then by its extension bit the next repeater or the rest of the frame."""
    role = "rpt%d" % n
    if n < MAX_RPT:
        return address(role, "h") + (["switch  ax25.%s_ext" % role, "  case  0"] + ind(2, repeaters(n + 1)) +
                                     ["  else"] + ind(2, after_address()) + ["end"])
    return address(role, "h") + ["switch  ax25.%s_ext" % role, "  case  1"] + ind(2, after_address()) + ["end"]


def ax25_pack():
    L = head("ax25-frame", ["AX.25 v2.2 frame (TAPR, sections 3 and 4): the address field (destination, source, up to eight",
                            "repeaters), the control field (modulo 8), the PID and the information field. The message is the frame",
                            "between the flags, without the frame-check sequence. Written by tools/gen/radio-pack.py."],
             ["ax25"], [A])
    L += address("dest", "c") + address("src", "c")
    L += ["switch  ax25.src_ext", "  case  0"] + ind(2, repeaters(1)) + ["  else"] + ind(2, after_address()) + ["end"]
    return text(L)


def ax25_keys():
    keys = []
    roles = [("dest", "destination", "c"), ("src", "source", "c")] + [("rpt%d" % n, "repeater %d" % n, "h") for n in range(1, MAX_RPT + 1)]
    for role, what, chbit in roles:
        for i in range(1, 7):
            keys.append(("key", "%s_call_%d" % (role, i), "%s callsign: character %d (space when the callsign is shorter)" % (what, i)))
        if chbit == "c":
            keys.append(("key", "%s_c" % role, "%s SSID octet: the C bit (with the other address's, command or response)" % what))
        else:
            keys.append(("key", "%s_h" % role, "%s SSID octet: the H bit, 1 when the frame has been repeated through it" % what))
        keys += [("key", "%s_reserved" % role, "%s SSID octet: the two reserved bits (1 1 when not used)" % what),
                 ("key", "%s_ssid" % role, "%s secondary station identifier, 0 to 15" % what),
                 ("key", "%s_ext" % role, "%s SSID octet: the extension bit, 1 for the last address of the field" % what)]
    keys += [("key", "control", "control field, modulo 8: I frame (bit 0 is 0), S frame (bits 1-0 are 01), U frame (bits 1-0 are 11); the whole octet"),
             ("key", "pid", "protocol identifier (I and UI frames): 0xF0 no layer 3, 0xCC IP, 0xCF NET/ROM ..."),
             ("list", "info", "the information field, as octets"),
             ("key", "octet", "one octet")]
    return keys


# ---------------------------------------------------------------- KISS

def kiss_pack():
    L = head("kiss-frame", ["KISS TNC frame (Chepponis and Karn, 1987): the type octet (port and command) and its data. The",
                            "message is the content between two FEND octets after FESC escapes are undone. Written by",
                            "tools/gen/radio-pack.py."], ["kiss"], [K])
    L += [F(K, "port", 4), F(K, "command", 4), "switch  kiss.command",
          "  case  0"] + ind(2, octets(K, "data")) + \
         ["  case  1,2,3,4,5", "    " + F(K, "value", 8), "  case  15", "  else"] + ind(2, octets(K, "data")) + ["end"]
    return text(L)


KISS_KEYS = [
    ("key", "port", "the HDLC port, 0 to 15 (the high nibble of the type octet)"),
    ("key", "command", "the command (the low nibble): 0 data frame, 1 TXDELAY, 2 persistence, 3 slot time, 4 TX tail, 5 full duplex, 6 set hardware; 15 with port 15 is Return"),
    ("key", "value", "commands 1 to 5: the parameter octet (10 ms units for 1, 3, 4; persistence P for 2; 0 half duplex for 5)"),
    ("list", "data", "a data frame (an AX.25 frame without flags and FCS), or a set hardware command's octets, or another command's octets"),
    ("key", "octet", "one octet"),
]


# ---------------------------------------------------------------- POCSAG

def pocsag_pack():
    L = head("pocsag-batch", ["POCSAG batch (Rec. ITU-R M.584-2 Annex 1, radio-paging code No. 1): the synchronization codeword",
                              "and the codewords that follow it (16 in a batch), each an address or a message codeword. Written",
                              "by tools/gen/radio-pack.py."], ["m584"], [P])
    L += ["kind    batch", "when    32  %d                # the synchronization codeword 0x7CD215D8" % 0x7CD215D8,
          "group  pocsag.codewords  rest",
          "  " + F(P, "flag", 1), "  switch  pocsag.flag",
          "    case  0", "      " + F(P, "address", 18), "      " + F(P, "function", 2),
          "    case  1", "      " + F(P, "message_bits", 20, "hex"),
          "  end", "  " + F(P, "bch", 10), "  " + F(P, "parity", 1), "end"]
    return text(L)


POCSAG_KEYS = [
    ("list", "codewords", "the codewords after the synchronization codeword, in order (16 in a whole batch: 8 frames of 2)"),
    ("key", "flag", "codeword flag: 0 address codeword (the idle codeword is one), 1 message codeword"),
    ("key", "address", "address codeword: the 18 most significant bits of the pager's 21-bit identity (the 3 others are the frame number)"),
    ("key", "function", "address codeword: the two function bits, choosing one of the pager's four addresses"),
    ("key", "message_bits", "message codeword: the 20 message bits, as hexadecimal digits (5 digits)"),
    ("key", "bch", "the 10 BCH(31,21) check bits, as on the wire (not verified)"),
    ("key", "parity", "the even parity bit, as on the wire (not verified)"),
]


def module(name, header, src, keys, strings=()):
    w = max(len(k[1]) for k in keys)
    L = header + ["module        %s" % name, "version       0.1.0", "distribution  public", src]
    for k in keys:
        if k[0] == "list":
            L.append('list  %-*s  "%s"' % (w, k[1], k[2]))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k[1], "string" if k[1] in strings else "int", k[2]))
    return "\n".join(L) + "\n"


def build(out):
    out.write("packs/ax25-frame/pack.def", ax25_pack())
    out.write("packs/kiss-frame/pack.def", kiss_pack())
    out.write("packs/pocsag-batch/pack.def", pocsag_pack())
    ak = ax25_keys()
    out.write("model/ax25.def", module("ax25", ["# The ax25 module: the fields of AX.25 v2.2 frames (TAPR). Written by tools/gen/radio-pack.py."],
                                       'source        "TAPR AX.25 v2.2 (1998); restated by goat-transformers"', ak,
                                       [k[1] for k in ak if "_call_" in k[1]]))
    out.write("model/kiss.def", module("kiss", ["# The kiss module: the fields of KISS TNC frames. Written by tools/gen/radio-pack.py."],
                                       'source        "Chepponis and Karn, The KISS TNC (1987); restated by goat-transformers"', KISS_KEYS))
    out.write("model/pocsag.def", module("pocsag", ["# The pocsag module: POCSAG codewords (Rec. ITU-R M.584-2 Annex 1). Written by tools/gen/radio-pack.py."],
                                         'source        "Rec. ITU-R M.584-2 Annex 1; restated by goat-transformers"', POCSAG_KEYS, ["message_bits"]))
    return {"radio": 6}


def main(argv=None):
    return genio.vector_main("radio-pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
