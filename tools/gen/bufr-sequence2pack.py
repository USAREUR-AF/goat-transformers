#!/usr/bin/env python3
"""bufr-sequence2pack: expand one BUFR Table D sequence into a pack for BUFR edition 4 messages.

A BUFR message whose section 3 holds a single Table D sequence descriptor, one subset and no
compression has a section 4 of fixed layout once the sequence is expanded: each element
descriptor (F=0) is a field of the width, scale and reference value Table B gives it, a sequence
descriptor (F=3) expands into its Table D entries, a fixed replication (F=1, Y>0) repeats the
next X descriptors Y times, and a delayed replication (F=1, Y=0) is a count of the width its
replication factor descriptor (0 31 000, 0 31 001, 0 31 002) gives, followed by that many items:
a `count` group. Of the operators (F=2) only 2 08 YYY (the width of CCITT IA5 elements) is
expanded; any other refuses the sequence. This script expands the sequence from the WMO BUFR
edition 4 tables as CSV (wmo-im/BUFR4) and writes:

  model/<module>.def, packs/<format>/pack.def, pack.md, vectors/*.json

The pack reads sections 0 to 5 like a BUFR edition 4 message; section 4 is read through the
expansion only when section 3's descriptor is the sequence, the message has one subset and is
not compressed (a `switch` on each); otherwise section 4 is kept as octets.

The vectors are built by a writer of this script that turns chosen raw values into bits by walking
the same expansion, independent of the pack text; the model values follow from Table B (value =
(raw + reference) x 10^-scale). No engine is run.

Usage: python3 -I tools/gen/bufr-sequence2pack.py --tables <BUFR4 checkout> --sequence 307080
         --format <pack> --module <module> [--out DIR] [--check]
"""
import argparse
import csv
import glob
import json
import os
import re
import sys
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

SOURCE_NOTE = "derived by tools/gen/bufr-sequence2pack.py from raw values written for it and WMO BUFR Table B; no engine run"


class GenError(Exception):
    pass


def load_tables(root):
    B, D = {}, {}
    for f in sorted(glob.glob(os.path.join(root, "BUFRCREX_TableB_en_*.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            B[r["FXY"]] = r
    for f in sorted(glob.glob(os.path.join(root, "BUFR_TableD_en_*.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8-sig")):
            D.setdefault(r["FXY1"], []).append(r["FXY2"])
    if not B or not D:
        raise GenError("no Table B or Table D CSV under %s" % root)
    return B, D


# -- expansion -------------------------------------------------------------------------------------
# A node is ("e", fxy, path) for an element, ("g", fxy_repl, count_fxy, [nodes]) for a delayed
# replication; fixed replications are unrolled.

def expand(seq, D, state=None):
    """Nodes of a descriptor list. `state` carries the one operator applied, 2 08 YYY (the width of
    CCITT IA5 elements becomes YYY characters until 2 08 000), across the list in reading order."""
    state = state if state is not None else {"ia5": None}
    out = []
    i = 0
    while i < len(seq):
        d = seq[i]
        f, x, y = int(d[0]), int(d[1:3]), int(d[3:])
        if f == 0:
            out.append(("e", d, state["ia5"]))
            i += 1
        elif f == 3:
            if d not in D:
                raise GenError("sequence %s is not in Table D" % d)
            out += expand(D[d], D, state)
            i += 1
        elif f == 1:
            if y == 0:
                count = seq[i + 1]
                if count not in ("031000", "031001", "031002"):
                    raise GenError("delayed replication %s is not followed by a replication factor (%s)" % (d, count))
                body = expand(seq[i + 2:i + 2 + x], D, state)
                out.append(("g", d, count, body))
                i += 2 + x
            else:
                body = seq[i + 1:i + 1 + x]
                for _ in range(y):
                    out += expand(body, D, state)
                i += 1 + x
        elif f == 2 and x == 8:
            state["ia5"] = y * 8 if y else None
            i += 1
        else:
            raise GenError("operator %s: only 2 08 YYY (CCITT IA5 width) is expanded" % d)
    return out


def slug(text):
    s = re.sub(r"\(.*?\)", "", text.lower())
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = s[:40].rstrip("_")
    return "e" + s if s[:1].isdigit() else s


class Element:
    def __init__(self, fxy, row, key, ia5_width=None):
        self.fxy, self.row, self.key = fxy, row, key
        self.width = int(row["BUFR_DataWidth_Bits"])
        if ia5_width and row["BUFR_Unit"] == "CCITT IA5":
            self.width = ia5_width
        self.scale = int(row["BUFR_Scale"])
        self.ref = int(row["BUFR_ReferenceValue"])
        self.unit = row["BUFR_Unit"]
        self.name = row["ElementName_en"]
        if self.unit == "CCITT IA5":
            self.kind = "ascii"
        elif self.scale == 0:
            self.kind = "int"
        else:
            self.kind = "float"

    def transform(self):
        if self.kind == "ascii":
            return "ascii"
        missing = (1 << self.width) - 1
        if self.kind == "int":
            tr = "uint" if self.ref == 0 else "uiscale:1:%d" % self.ref
        else:
            factor = Fraction(1, 10 ** self.scale) if self.scale > 0 else Fraction(10 ** -self.scale)
            offset = Fraction(self.ref) * factor
            tr = "uscale:%s:%s" % (frac(factor), dec(offset))
        return "%s  absent %d" % (tr, missing)

    def value(self, raw):
        """The model value of a raw value, as an engine computes it (ruling 1 of 0.5 for uscale,
        exact for uiscale)."""
        if self.kind == "int":
            return raw + self.ref
        factor = Fraction(1, 10 ** self.scale) if self.scale > 0 else Fraction(10 ** -self.scale)
        offset = float(Fraction(self.ref) * factor) if self.ref else 0.0
        if factor.denominator != 1:
            v = float(raw) * float(factor.numerator) / float(factor.denominator)
        else:
            v = float(raw) * float(factor.numerator)
        return v + offset

    def meaning(self, path):
        unit = self.unit
        return "%s, %s (Table B %s %s %s, width %d, scale %d, reference %d)%s" % (
            self.name, unit, self.fxy[0], self.fxy[1:3], self.fxy[3:], self.width, self.scale, self.ref,
            "; " + path if path else "")


def frac(f):
    return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)


def dec(f):
    """An exact decimal text of a fraction whose denominator divides a power of ten."""
    if f.denominator == 1:
        return str(f.numerator)
    places = 0
    while (f * 10 ** places).denominator != 1:
        places += 1
        if places > 18:
            raise GenError("offset %s is not a decimal" % f)
    n = (f * 10 ** places).numerator
    sign = "-" if n < 0 else ""
    s = str(abs(n)).rjust(places + 1, "0")
    return sign + s[:-places] + "." + s[-places:]


def build_tree(nodes, B, names, path, lists, keys, list_prefix=""):
    """Element objects and groups, with unique key names."""
    tree = []
    for n in nodes:
        if n[0] == "e":
            row = B.get(n[1])
            if row is None:
                raise GenError("element %s is not in Table B" % n[1])
            base = (list_prefix + "_" if list_prefix else "") + slug(row["ElementName_en"])
            k = base
            i = 2
            while k in names:
                k = "%s_%d" % (base, i)
                i += 1
            names.add(k)
            e = Element(n[1], row, k, n[2])
            keys[k] = e
            tree.append(e)
        else:
            _, repl, count, body = n
            first = body[0] if body else None
            base = "repl_" + (slug(B[first[1]]["ElementName_en"]) if first and first[0] == "e" else "items")
            name = base
            i = 2
            while name in names:
                name = "%s_%d" % (base, i)
                i += 1
            names.add(name)
            width = int(B[count]["BUFR_DataWidth_Bits"])
            lists[name] = (repl, count)
            tree.append(("g", name, width, build_tree(body, B, names, path, lists, keys, name)))
    return tree


# -- the pack ---------------------------------------------------------------------------------------

def emit_tree(tree, module, ind, L):
    pad = "  " * ind
    for t in tree:
        if isinstance(t, Element):
            L.append("%sfield  %s.%s  %d  %s" % (pad, module, t.key, t.width, t.transform()))
        else:
            _, name, width, body = t
            L.append("%sgroup  %s.%s  count %d" % (pad, module, name, width))
            emit_tree(body, module, ind + 1, L)
            L.append(pad + "end")


def fxy_int(fxy):
    return (int(fxy[0]) << 14) | (int(fxy[1:3]) << 8) | int(fxy[3:])


def pack_text(a, tree, sources):
    m = a.module
    L = ["# BUFR edition 4 message whose section 3 holds the single Table D sequence %s %s %s, one" % (a.sequence[0], a.sequence[1:3], a.sequence[3:]),
         "# subset, uncompressed: section 4 read through the expanded sequence. Any other message reads with",
         "# section 4 as octets. Public. Generated by tools/gen/bufr-sequence2pack.py from the WMO BUFR edition 4",
         "# tables (wmo-im/BUFR4, MIT); do not edit by hand. I/O is hex text. See pack.md.",
         "format     %s" % a.format, "version    0.1.0", "distribution public"]
    L += ['source     "%s"' % s for s in sources]
    L += ["uses       %s" % m, "wire       bits", "layout     sequential", "bit_order  msb", "",
          "# Section 0, as common lines (ruling 10 of 0.8).",
          "when    32  1112884818                     # BUFR",
          "length  24 whole",
          "when    8  4                               # edition 4", "",
          "kind    message",
          "length 24 bytes plus 3                     # section 1"]
    for k, w in S1:
        L.append("  field  %s.%s  %d  uint" % (m, k, w))
    L += ["  group  %s.section1_local  rest" % m, "    field  %s.section1_local_octet  8  uint" % m, "  end", "end",
          "switch %s.optional_section" % m, "  case 1",
          "    length 24 bytes plus 3                 # section 2",
          "      field  %s.section2_reserved  8  uint" % m,
          "      group  %s.section2_data  rest" % m, "        field  %s.section2_octet  8  uint" % m, "      end",
          "    end", "  else", "end",
          "length 24 bytes plus 3                     # section 3",
          "  field  %s.section3_reserved   8  uint" % m,
          "  field  %s.number_of_subsets  16  uint" % m,
          "  field  %s.observed_data       1  uint" % m,
          "  field  %s.compressed_data     1  uint" % m,
          "  field  %s.section3_flags_low  6  uint" % m,
          "  field  %s.descriptor         16  uint" % m,
          "  group  %s.more_descriptors  rest" % m, "    field  %s.more_descriptor  16  uint" % m, "  end", "end",
          "length 24 bytes plus 3                     # section 4",
          "  field  %s.section4_reserved  8  uint" % m,
          "  switch %s.descriptor" % m,
          "    case %d                              # %s %s %s" % (fxy_int(a.sequence), a.sequence[0], a.sequence[1:3], a.sequence[3:]),
          "      switch %s.number_of_subsets" % m, "        case 1",
          "          switch %s.compressed_data" % m, "            case 0"]
    body = []
    emit_tree(tree, m, 8, body)
    L += body
    octets = ["group  %s.data  rest" % m, "  field  %s.data_octet  8  uint" % m, "end"]
    L += ["            else"] + ["              " + x for x in octets] + ["          end",
          "        else"] + ["          " + x for x in octets] + ["      end", "    else"] + ["      " + x for x in octets] + \
         ["  end", "end", "const   32  926365495                      # section 5: 7777, written on encode, not checked on decode"]
    return "\n".join(L) + "\n"


S1 = [("master_table", 8), ("centre", 16), ("sub_centre", 16), ("update_sequence_number", 8), ("optional_section", 1),
      ("section1_flags_low", 7), ("data_category", 8), ("international_sub_category", 8), ("local_sub_category", 8),
      ("master_table_version", 8), ("local_table_version", 8), ("year", 16), ("month", 8), ("day", 8), ("hour", 8),
      ("minute", 8), ("second", 8)]

FIXED_KEYS = [
    ("key", "master_table", "int", "section 1: BUFR master table (0 meteorology)"),
    ("key", "centre", "int", "section 1: originating centre (common code table C-11)"),
    ("key", "sub_centre", "int", "section 1: originating sub-centre"),
    ("key", "update_sequence_number", "int", "section 1: update sequence number"),
    ("key", "optional_section", "int", "section 1: 1 when section 2 is present"),
    ("key", "section1_flags_low", "int", "section 1: the other seven flag bits"),
    ("key", "data_category", "int", "section 1: data category (Table A)"),
    ("key", "international_sub_category", "int", "section 1: international data sub-category (common code table C-13)"),
    ("key", "local_sub_category", "int", "section 1: local data sub-category"),
    ("key", "master_table_version", "int", "section 1: version of the master table"),
    ("key", "local_table_version", "int", "section 1: version of the local tables"),
    ("key", "year", "int", "section 1: typical time, year"), ("key", "month", "int", "section 1: typical time, month"),
    ("key", "day", "int", "section 1: typical time, day"), ("key", "hour", "int", "section 1: typical time, hour"),
    ("key", "minute", "int", "section 1: typical time, minute"), ("key", "second", "int", "section 1: typical time, second"),
    ("list", "section1_local", None, "section 1: local octets after the second"),
    ("key", "section1_local_octet", "int", "one of those octets"),
    ("key", "section2_reserved", "int", "section 2: reserved octet"),
    ("list", "section2_data", None, "section 2: local data, as octets"), ("key", "section2_octet", "int", "one octet of section 2"),
    ("key", "section3_reserved", "int", "section 3: reserved octet"),
    ("key", "number_of_subsets", "int", "section 3: number of data subsets"),
    ("key", "observed_data", "int", "section 3: 1 for observed data"), ("key", "compressed_data", "int", "section 3: 1 for compressed data"),
    ("key", "section3_flags_low", "int", "section 3: the other six flag bits"),
    ("key", "descriptor", "int", "section 3: the first descriptor, as F (2 bits), X (6), Y (8) in 16 bits"),
    ("list", "more_descriptors", None, "section 3: descriptors after the first; a message the expansion reads has none"),
    ("key", "more_descriptor", "int", "one further descriptor"),
    ("key", "section4_reserved", "int", "section 4: reserved octet"),
    ("list", "data", None, "section 4 as octets, when the message is not the expanded sequence"),
    ("key", "data_octet", "int", "one octet of section 4"),
]


def module_text(a, keys, lists, sources):
    L = ["# The %s module: a BUFR edition 4 message of the Table D sequence %s, its sections and the" % (a.module, a.sequence),
         "# elements of the expanded sequence. Generated by tools/gen/bufr-sequence2pack.py; do not edit by hand.",
         "module        %s" % a.module, "version       0.1.0", "distribution  public",
         'source        "%s; restated by goat-transformers"' % sources[0]]
    rows = [(k, kind, vt, m) for kind, k, vt, m in FIXED_KEYS]
    for name, (repl, count) in lists.items():
        rows.append((name, "list", None, "items of the delayed replication %s %s %s, counted by %s %s %s" % (
            repl[0], repl[1:3], repl[3:], count[0], count[1:3], count[3:])))
    for k, e in keys.items():
        rows.append((k, "key", {"ascii": "string", "int": "int", "float": "float"}[e.kind], e.meaning("")))
    w = max(len(r[0]) for r in rows)
    for k, kind, vt, m in rows:
        m = m.replace('"', "'")
        if kind == "list":
            L.append('list  %-*s  "%s"' % (w, k, m))
        else:
            L.append('key   %-*s  %-6s  -  "%s"' % (w, k, vt, m))
    return "\n".join(L) + "\n"


# -- the raw writer and the vectors ------------------------------------------------------------------

class Bits:
    def __init__(self):
        self.s = ""

    def put(self, v, n):
        self.s += format(v, "0%db" % n) if n else ""

    def bytes(self):
        s = self.s + "0" * (-len(self.s) % 8)
        return int(s, 2).to_bytes(len(s) // 8, "big") if s else b""


def write_tree(tree, values, bits, model, module, prefix=""):
    """Write the raw values of a tree; values maps a key to a raw int or text, or a list name to a
    list of value maps. Model gets the decoded values."""
    for t in tree:
        if isinstance(t, Element):
            raw = values.get(t.key)
            if t.kind == "ascii":
                text = raw if raw is not None else ""
                if len(text) > t.width // 8:
                    raise GenError("%s: %r is longer than %d characters" % (t.key, text, t.width // 8))
                b = text.encode("ascii").ljust(t.width // 8, b" ")
                bits.put(int.from_bytes(b, "big"), t.width)
                model[prefix + module + "." + t.key] = b.rstrip(b"\0").decode("ascii")
            else:
                if raw is None:
                    bits.put((1 << t.width) - 1, t.width)
                else:
                    if not 0 <= raw < (1 << t.width) - 1:
                        raise GenError("%s: raw value %d does not fit %d bits below the missing value" % (t.key, raw, t.width))
                    bits.put(raw, t.width)
                    model[prefix + module + "." + t.key] = t.value(raw)
        else:
            _, name, width, body = t
            items = values.get(name, [])
            bits.put(len(items), width)
            model[prefix + module + "." + name + ".#"] = len(items)
            for i, it in enumerate(items):
                write_tree(body, it, bits, model, module, "%s%s.%s[%d]." % (prefix, module, name, i))


def pick(tree, seed, chosen):
    """Raw values for every element of a tree: chosen ones, else a deterministic value that is not
    the missing value; two items in every delayed replication."""
    out = {}
    for t in tree:
        if isinstance(t, Element):
            if t.key in chosen:
                out[t.key] = chosen[t.key]
            elif t.kind == "ascii":
                out[t.key] = "X" * min(3, t.width // 8)
            else:
                seed[0] = (seed[0] * 1103515245 + 12345) & 0x7FFFFFFF
                out[t.key] = seed[0] % ((1 << t.width) - 1)
        else:
            _, name, width, body = t
            out[name] = [pick(body, seed, chosen) for _ in range(chosen.get(name + "#", min(2, (1 << width) - 1)))]
    return out


def message(a, section4, subsets=1, compressed=0, descriptor=None):
    def sec(body):
        return (3 + len(body)).to_bytes(3, "big") + body
    s1 = sec(bytes([0]) + (98).to_bytes(2, "big") + (0).to_bytes(2, "big") + bytes([0, 0, 0, 0, 255, 38, 0]) +
             (2026).to_bytes(2, "big") + bytes([11, 20, 6, 0, 0]))
    d = fxy_int(descriptor or a.sequence).to_bytes(2, "big")
    s3 = sec(bytes([0]) + subsets.to_bytes(2, "big") + bytes([0x80 | (0x40 if compressed else 0)]) + d)
    s4 = sec(bytes([0]) + section4)
    body = s1 + s3 + s4 + b"7777"
    return b"BUFR" + (8 + len(body)).to_bytes(3, "big") + bytes([4]) + body


def model_text(model):
    out = {}
    for k, v in model.items():
        if isinstance(v, float):
            r = repr(v)
            out[k] = r[:-2] if r.endswith(".0") else r
        else:
            out[k] = str(v)
    return out


def vectors(a, tree, keys, chosen):
    V = []
    m = a.module
    vals = pick(tree, [7], chosen)
    bits = Bits()
    model = {}
    write_tree(tree, vals, bits, model, m)
    msg = message(a, bits.bytes())
    mm = {"@kind": "message", m + ".descriptor": fxy_int(a.sequence), m + ".number_of_subsets": 1}
    wanted = [k for k in model if not k.endswith(".#")][:12] + [k for k in model if k.endswith(".#")]
    mm.update({k: model[k] for k in wanted})
    V.append(("%s-roundtrip" % a.sequence, {"input": msg.hex(), "expect": msg.hex(), "model": model_text(mm),
              "note": "every element present: the chosen station values and deterministic values elsewhere, two items in "
                      "every delayed replication (one where its count is a single bit)"}))
    miss = {k: v for k, v in chosen.items() if not k.endswith("#")}
    vals2 = pick(tree, [11], chosen)
    for k, e in keys.items():
        if e.kind != "ascii" and k not in miss:
            vals2[k] = None
    for t in tree:
        if not isinstance(t, Element):
            vals2[t[1]] = []
    bits = Bits()
    model2 = {}
    write_tree(tree, vals2, bits, model2, m)
    msg = message(a, bits.bytes())
    mm = {k: model2[k] for k in list(model2)[:8]}
    V.append(("%s-missing-values-roundtrip" % a.sequence, {"input": msg.hex(), "expect": msg.hex(), "model": model_text(mm),
              "note": "every numeric element other than the station's position, time and identity missing (all bits set): "
                      "the keys are absent (absent sentinel) and the missing value is written back; every delayed "
                      "replication empty"}))
    other = message(a, bytes([1, 2, 3, 4]), descriptor="307091")
    V.append(("other-sequence-is-octets-roundtrip", {"input": other.hex(), "expect": other.hex(),
              "model": {m + ".descriptor": str(fxy_int("307091")), m + ".data.#": "4"},
              "note": "a message of another sequence: section 4 is kept as octets"}))
    two = message(a, bytes([9, 9]), subsets=2)
    V.append(("two-subsets-is-octets-roundtrip", {"input": two.hex(), "expect": two.hex(),
              "model": {m + ".number_of_subsets": "2", m + ".data.#": "2"},
              "note": "two subsets: the layout differs, so section 4 is kept as octets"}))
    return V


def md_text(a, tree, keys, lists, made, sources):
    n_el = len(keys)
    L = ["# %s" % a.format, "",
         "A BUFR edition 4 message whose section 3 holds the single Table D sequence %s %s %s, with one subset and "
         "no compression. Wire `bits`, `layout sequential`, `bit_order msb`; I/O is hex text. Generated by "
         "`tools/gen/bufr-sequence2pack.py` from the WMO BUFR edition 4 tables (wmo-im/BUFR4, MIT). Licence: "
         "Apache-2.0 (PROVENANCE.md)." % (a.sequence[0], a.sequence[1:3], a.sequence[3:]), "",
         "## Layout", "",
         "Sections 0 to 3 and 5 are read as a BUFR edition 4 message: section 0 as common lines, section 1 field by field "
         "(with the typical time), section 2 when the flag of section 1 says so, section 3 with its first descriptor and "
         "any further ones. Section 4 is read through the expansion when the first descriptor is the sequence, the "
         "message has one subset and is not compressed (`switch` on each); otherwise it is kept as octets.", "",
         "The expansion: %d element fields and %d delayed replications (`group … count <width>`, the count being the "
         "replication factor that precedes its items); fixed replications are written out, their keys numbered. "
         "The one operator expanded is 2 08 YYY, which sets the width of the CCITT IA5 elements after it; any other "
         "operator refuses the sequence." % (n_el, len(lists)), "",
         "| Element type | Line |", "|---|---|",
         "| CCITT IA5 text | `ascii` of the element's width |",
         "| scale 0, reference 0 | `uint` |",
         "| scale 0, another reference | `uiscale:1:<reference>` |",
         "| scale s | `uscale:<10^-s>:<reference x 10^-s>` (value = (raw + reference) x 10^-s), a float |",
         "| every numeric element | `absent <all bits set>`: the missing value leaves the key absent and is written back |",
         "", "The meaning, unit, width, scale and reference of every key are in `model/%s.def`." % a.module, "",
         "## Shared-model keys: none, and why", "",
         "- The latitude and longitude elements (class 05 and 06 of Table B) are degrees, read exactly, but Table B states "
         "no datum for them and the tables give no default; `lat` and `lon` mean WGS 84, so they stay raw keys.",
         "- The observation time is the year, month, day, hour and minute elements (3 01 011, 3 01 012), and no `derive` "
         "composes a date from its parts into `time_ms`.", "",
         "## Not mapped", "",
         "- A message whose section 3 holds the sequence followed by further descriptors: section 4 is read through the "
         "sequence only, and data after it is skipped on decode and not written back.",
         "- Several subsets and compressed data (another layout of section 4): kept as octets.",
         "- A missing station name (all bits set): `ascii` reads only characters 0x20 to 0x7E, so the message is "
         "`transform-decode`.", "",
         "## Vectors", "", "| File | Shows |", "|---|---|"]
    L += ["| `%s` | %s |" % (fn, v["note"]) for fn, v in made]
    return "\n".join(L) + "\n"


def run(a, out):
    B, D = load_tables(a.tables)
    seq = D.get(a.sequence)
    if seq is None:
        raise GenError("sequence %s is not in Table D" % a.sequence)
    nodes = expand([a.sequence], D)
    names = {k for _, k, _, _ in FIXED_KEYS}
    lists, keys = {}, {}
    tree = build_tree(nodes, B, names, "", lists, keys)
    sources = ["WMO BUFR edition 4 tables, https://github.com/wmo-im/BUFR4 commit %s, Table B and Table D CSV (MIT)" % a.commit]
    chosen = json.loads(a.values) if a.values else {}
    made = []
    for i, (name, v) in enumerate(vectors(a, tree, keys, chosen)):
        fn = "%02d-%s.json" % (i + 1, name)
        body = {"name": name, "from": a.format, "to": a.format, "input": v["input"], "expect": v["expect"],
                "model": v["model"], "source": SOURCE_NOTE, "reference": "WMO BUFR edition 4 Table D %s and Table B; %s" % (a.sequence, v["note"])}
        made.append((fn, dict(v, note=v["note"])))
        out.write("packs/%s/vectors/%s" % (a.format, fn), json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    out.write("packs/%s/pack.def" % a.format, pack_text(a, tree, sources))
    out.write("model/%s.def" % a.module, module_text(a, keys, lists, sources))
    out.write("packs/%s/pack.md" % a.format, md_text(a, tree, keys, lists, made, sources))
    return {a.format: len(made)}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bufr-sequence2pack.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    genio.add_arguments(ap, default_out=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    ap.add_argument("--tables", required=True, help="a checkout of wmo-im/BUFR4")
    ap.add_argument("--commit", required=True, help="its commit, for the source lines")
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--format", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--values", help="JSON: raw values for chosen keys, and <list>#: item counts")
    a = ap.parse_args(argv)
    out = genio.Output(a.out, check=a.check)
    try:
        written = run(a, out)
    except GenError as x:
        print("bufr-sequence2pack: %s" % x, file=sys.stderr)
        return 1
    if not a.check:
        for k, v in written.items():
            print(k, v)
    return out.report("bufr-sequence2pack.py")


if __name__ == "__main__":
    sys.exit(main())
