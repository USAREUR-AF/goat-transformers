#!/usr/bin/env python3
"""Write the vectors of spec 0.46, character-coded identifiers (`charset`,
`code`, `codestr`, `codenum`): the vectors of the packs named in PACKS below
(`conformance-charset-*`) and the load vectors from 4600.

Every expected value here is worked out by hand from the spec text (Version
0.46: Grammar, On `bits`, On text wires, Where the rules apply, Load errors,
rulings 1 to 14; and the sections they refer to: 0.2 and 0.5 bit order, 0.6
absent keys on a fixed layout, 0.10 the `text` wire and its columns, 0.15
`chars`, 0.9 `absent`, 0.14 `armor sixbit`, 0.22 `msb-lsb`, 0.11 ruling 5b)
and the pack layouts. The hand working, bit by bit, is the comment above each vector;
the value is written out literally.

It is checked against a second computation: the small codecs below read the
committed pack.def files with their own parser and apply the rules to the
input (a bits reader and writer, fixed and sequential, in the three bit
orders, a text record reader and writer, and json and xml for the lines
these packs use). Load vectors and the packs are checked against
tools/gen/gtcheck.py. Nothing here imports or calls an engine.

Derivations: no key these packs map is the target of a `derive` line of
core or probe (checked below).

Inputs: the pack.def files of PACKS, model/core.def and model/probe.def.
Writes, under --out, the vector files named above. With --check nothing is
written and the exit status is 1 when a committed file differs from what
this script writes.

Usage: python3 -I tools/gen/conformance-charset-vectors.py [--out DIR] [--check]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PACKS = ("src", "bits", "lsb", "one", "swapopt", "msb-lsb", "five-msb", "five-lsb", "five-seq-msb", "five-seq-lsb",
         "items", "absent", "wide", "armor", "json", "absent-json", "text", "xml",
         "order-a", "order-b", "via", "absent-number", "absent-text")
PREFIX = "conformance-charset-"
TD, TE = "transform-decode", "transform-encode"
SOURCE = "constructed"
KEY_TYPES = {}


class Fail(Exception):
    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


def tokens(line):
    out, i = [], 0
    while i < len(line):
        c = line[i]
        if c in " \t":
            i += 1
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        elif c == '"':
            j = line.index('"', i + 1)
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(line) and line[j] not in " \t":
                j += 1
            out.append(line[i:j])
            i = j
    return out


def parse_pack(text, name):
    pack = {"name": name, "wire": None, "bit_order": "lsb", "root": None, "charsets": {}, "lines": [], "maps": {},
            "layout": "fixed", "armor": "hex"}
    body = pack["lines"]
    for raw in text.splitlines():
        t = tokens(raw)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in ("format", "version", "distribution", "source", "uses", "word_bytes"):
            continue
        if d in ("wire", "bit_order", "root", "layout", "armor"):
            pack[d] = a[0]
        elif d == "charset":
            pack["charsets"][a[0]] = a[1:]               # characters, and the width if given
        elif d == "map":
            pack["maps"].setdefault(a[0], []).append((a[1], a[2]))
        elif d == "field":
            tr, _, sets = a[2].partition(":")
            body.append({"d": "field", "key": a[0], "loc": a[1], "tr": tr, "sets": sets.split(",") if sets else None,
                         "swap": "swap" in a[3:], "via": a[a.index("via") + 1] if "via" in a else None, "absent": a[a.index("absent") + 1] if "absent" in a else None})
        elif d == "pad":
            body.append({"d": "pad", "len": int(a[0])})
        elif d == "group":
            assert a[1] == "count"
            pack["lines"].append({"d": "group", "key": a[0], "len": int(a[2]), "body": []})
            body = pack["lines"][-1]["body"]
        elif d == "end":
            body = pack["lines"]
        else:
            raise AssertionError("line not read here: %r" % raw)
    pack["fields"] = [x for x in pack["lines"] if x["d"] == "field"]
    return pack


def positions(pack, node):
    """[(characters, width)] of each position; width only on bits."""
    out = []
    for s in node["sets"]:
        spec = pack["charsets"][s]
        chars = spec[0]
        width = None
        if pack["wire"] == "bits":
            width = int(spec[1]) if len(spec) > 1 else max(1, (len(chars) - 1).bit_length())
        out.append((chars, width))
    return out


# ------------------------------------------------------------------------------
# codes, text and numbers (0.46)
# ------------------------------------------------------------------------------
def codes_to_text(pos, codes, fail):
    out = ""
    for (chars, _), c in zip(pos, codes):
        if c >= len(chars):
            raise Fail(fail, "code %d at or beyond the set" % c)
        out += chars[c]
    return out


def text_to_codes(pos, text, fail):
    if len(text) != len(pos):
        raise Fail(fail, "%r: not one character per position" % text)
    codes = []
    for (chars, _), ch in zip(pos, text):
        if ch not in chars:
            raise Fail(fail, "%r is not in its position's set" % ch)
        codes.append(chars.index(ch))
    return codes


def codes_to_number(pos, codes, fail):
    v = 0
    for (chars, _), c in zip(pos, codes):
        if c >= len(chars):
            raise Fail(fail, "code %d at or beyond the set" % c)
        v = v * len(chars) + c                             # first position most significant
    return v


def number_to_codes(pos, x):
    product = 1
    for chars, _ in pos:
        product *= len(chars)
    if not 0 <= x < product:
        raise Fail(TE, "%d outside 0 to %d" % (x, product - 1))
    codes = []
    for chars, _ in reversed(pos):                         # last position first
        codes.append(x % len(chars))
        x //= len(chars)
    return codes[::-1]


# ------------------------------------------------------------------------------
# bits: one integer as `uint` reads it (0.2, 0.5, 0.22), then the positions
# from its most significant end (0.46)
# ------------------------------------------------------------------------------
def order_of(pack, n):
    """The weight of the k-th wire bit of an n-bit number."""
    return [n - 1 - k if pack["bit_order"] == "msb" else k for k in range(n)]


def wire_bit(pack, i):
    """(byte, shift) of message bit i: msb and msb-lsb count from the high end."""
    return i // 8, i % 8 if pack["bit_order"] == "lsb" else 7 - i % 8


def read_uint(pack, data, start, n):
    v = 0
    for k, weight in enumerate(order_of(pack, n)):
        byte, shift = wire_bit(pack, start + k)
        v |= ((data[byte] >> shift) & 1) << weight
    return v


def write_uint(pack, buf, start, n, v):
    for k, weight in enumerate(order_of(pack, n)):
        byte, shift = wire_bit(pack, start + k)
        while len(buf) <= byte:
            buf.append(0)
        buf[byte] = buf[byte] & ~(1 << shift) | ((v >> weight) & 1) << shift


def reverse_bytes(v, ln):
    return int.from_bytes(v.to_bytes(ln // 8, "big")[::-1], "big")


def value_of(pack, f, raw, ln):
    if f["swap"]:
        raw = reverse_bytes(raw, ln)
    if f["absent"] is not None and raw == int(f["absent"]):
        return None
    if f["tr"] == "uint":
        return raw
    pos = positions(pack, f)
    assert sum(w for _, w in pos) == ln
    codes = []
    for _, w in reversed(pos):                             # the last position is the least significant
        codes.append(raw & ((1 << w) - 1))
        raw >>= w
    codes.reverse()
    v = codes_to_text(pos, codes, TD) if f["tr"] == "code" else codes_to_number(pos, codes, TD)
    if f["via"]:                                           # 0.6: the tables here yield strings
        for native, model in pack["maps"][f["via"]]:
            if native == str(v):
                return model
        if f["tr"] == "codenum":
            raise Fail(TD, "no entry, and the types differ")
    return v


def raw_of(pack, f, v, ln):
    if v is None:
        raw = int(f["absent"] or 0)
    elif f["tr"] == "uint":
        raw = v
    else:
        pos = positions(pack, f)
        if f["via"]:
            native = [n for n, m in pack["maps"][f["via"]] if m == v]
            if native:
                v = int(native[0]) if f["tr"] == "codenum" else native[0]
            elif f["tr"] == "codenum":
                raise Fail(TE, "no entry, and the types differ")
        codes = text_to_codes(pos, v, TE) if f["tr"] == "code" else number_to_codes(pos, v)
        raw = 0
        for (_, w), c in zip(pos, codes):
            raw = raw << w | c
    return reverse_bytes(raw, ln) if f["swap"] else raw


def unarmor(text):
    """0.14: each character is six bits, high bit first."""
    bits = ""
    for ch in text:
        v = ord(ch) - 48
        bits += format(v - 8 if v > 40 else v, "06b")
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


def armor(buf):
    assert len(buf) % 3 == 0
    bits = "".join(format(b, "08b") for b in buf)
    vals = [int(bits[i:i + 6], 2) for i in range(0, len(bits), 6)]
    return "".join(chr(v + 48 if v < 40 else v + 56) for v in vals)


def place(pack, f, cursor):
    """(start, length, the cursor after) of a field."""
    if pack["layout"] == "sequential":
        return cursor, int(f["loc"]), cursor + int(f["loc"])
    word, pos, ln = (int(x) for x in f["loc"].split(":"))
    return word * 8 + pos, ln, cursor


def bits_decode(pack, text):
    data = unarmor(text) if pack["armor"] == "sixbit" else bytes.fromhex(text)

    def number(start, n):
        if start + n > 8 * len(data):
            raise Fail("malformed-wire", "short")
        return read_uint(pack, data, start, n)

    def scope(lines, keys, cur):
        for ln in lines:
            if ln["d"] == "pad":
                cur += ln["len"]
            elif ln["d"] == "group":
                count = number(cur, ln["len"])
                cur += ln["len"]
                keys[ln["key"]] = []
                for _ in range(count):
                    item = {}
                    cur = scope(ln["body"], item, cur)
                    keys[ln["key"]].append(item)
            else:
                start, n, cur = place(pack, ln, cur)
                v = value_of(pack, ln, number(start, n), n)
                if v is not None:
                    keys[ln["key"]] = v
        return cur

    keys = {}
    scope(pack["lines"], keys, 0)
    return {"keys": keys}


def bits_encode(pack, ent):
    buf = bytearray()

    def scope(lines, keys, cur):
        todo = []
        for ln in lines:
            if ln["d"] == "pad":
                write_uint(pack, buf, cur, ln["len"], 0)
                cur += ln["len"]
            elif ln["d"] == "group":
                items = keys.get(ln["key"], [])
                write_uint(pack, buf, cur, ln["len"], len(items))
                cur += ln["len"]
                for item in items:
                    cur = scope(ln["body"], item, cur)
            else:
                start, n, cur = place(pack, ln, cur)
                todo.append((start, n, ln, keys.get(ln["key"])))
        # 0.5 ruling 5: where two present fields cover the same bits the
        # earlier line's value stands, so absent lines go first, then the
        # present ones from the last line to the first
        for start, n, ln, v in [x for x in todo if x[3] is None] + [x for x in todo if x[3] is not None][::-1]:
            write_uint(pack, buf, start, n, raw_of(pack, ln, v, n))
        return cur

    scope(pack["lines"], ent["keys"], 0)
    return armor(buf) if pack["armor"] == "sixbit" else bytes(buf).hex()


# ------------------------------------------------------------------------------
# text, json and xml (the lines these packs use)
# ------------------------------------------------------------------------------
def text_value(pack, f, text, fail):
    pos = positions(pack, f)
    codes = text_to_codes(pos, text, fail)
    return text if f["tr"] == "codestr" else codes_to_number(pos, codes, fail)


def text_form(pack, f, v):
    if f["tr"] not in ("codestr", "codenum"):
        return v
    pos = positions(pack, f)
    if f["tr"] == "codestr":
        text_to_codes(pos, v, TE)
        return v
    if f["tr"] == "codenum":
        return codes_to_text(pos, number_to_codes(pos, v), TE)
    return v


def record_decode(pack, text):
    fields = text.split(",")
    keys = {}
    for f in pack["fields"]:
        parts = f["loc"].split(":")
        i = int(parts[0])
        if i >= len(fields) or fields[i] == "":
            continue
        t = fields[i]
        if len(parts) == 3:
            frm, ln = int(parts[1]), int(parts[2])
            if len(t) <= frm:
                continue
            t = t[frm:frm + ln].rstrip(" ")               # trailing spaces removed; leading kept (ruling 14)
            if t == "":
                continue
        if f["tr"] == "int":
            if not re.fullmatch(r"[+-]?[0-9]+", t):
                raise Fail(TD, "int")
            keys[f["key"]] = int(t)
        else:
            keys[f["key"]] = text_value(pack, f, t, TD)
    return {"keys": keys}


def record_encode(pack, ent):
    keys = ent["keys"]
    width = 1 + max(int(f["loc"].split(":")[0]) for f in pack["fields"])
    fields = [""] * width
    for f in pack["fields"]:
        if f["key"] not in keys:
            continue
        t = str(keys[f["key"]]) if f["tr"] == "int" else text_form(pack, f, keys[f["key"]])
        parts = f["loc"].split(":")
        if len(parts) == 3:
            ln = int(parts[2])
            t = t + " " * (ln - len(t))                    # padded with spaces on the right (ruling 14)
        fields[int(parts[0])] = t
    return ",".join(fields)


def json_sentinel(f):
    """The member value an absent key writes (0.9 rulings 9 and 12): number text
    is the number, a leading `=` forces the text. Decode compares texts."""
    a = f["absent"]
    if a.startswith("="):
        return a[1:]
    return int(a) if re.fullmatch(r"-?(0|[1-9][0-9]*)", a) else a


def json_decode(pack, text):
    obj = json.loads(text)
    keys = {}
    for f in pack["fields"]:
        v = obj.get(f["loc"])
        if v is None:
            continue
        if f["absent"] is not None and str(v) == str(json_sentinel(f)):
            continue                                       # 0.9: the text, before any lookup
        if f["tr"] in ("codestr", "codenum"):
            if not isinstance(v, str):
                raise Fail(TD, "not a string (ruling 11)")
            keys[f["key"]] = text_value(pack, f, v, TD)
        else:
            keys[f["key"]] = v
    return {"keys": keys}


def json_encode(pack, ent):
    out = []
    for f in pack["fields"]:
        if f["key"] in ent["keys"]:
            out.append("%s:%s" % (json.dumps(f["loc"]), json.dumps(text_form(pack, f, ent["keys"][f["key"]]))))
        elif f["absent"] is not None:
            out.append("%s:%s" % (json.dumps(f["loc"]), json.dumps(json_sentinel(f))))
    return "{" + ",".join(out) + "}"


def xml_decode(pack, text):
    m = re.fullmatch(r"<R((?: [a-z]+=\"[^\"]*\")*)(?:/>|>(?:<call>([^<]*)</call>)?</R>)", text)
    assert m, text
    attrs = dict(re.findall(r' ([a-z]+)="([^"]*)"', m.group(1)))
    keys = {}
    for f in pack["fields"]:
        v = attrs.get(f["loc"][1:]) if f["loc"].startswith("@") else m.group(2)
        if v is not None:
            keys[f["key"]] = text_value(pack, f, v, TD)
    return {"keys": keys}


def xml_encode(pack, ent):
    attrs, inner = "", ""
    for f in pack["fields"]:
        if f["key"] not in ent["keys"]:
            continue
        t = text_form(pack, f, ent["keys"][f["key"]])
        if f["loc"].startswith("@"):
            attrs += ' %s="%s"' % (f["loc"][1:], t)
        else:
            inner += "<call>%s</call>" % t
    return "<R%s/>" % attrs if not inner else "<R%s>%s</R>" % (attrs, inner)


CODECS = {"bits": (bits_decode, bits_encode), "text": (record_decode, record_encode),
          "json": (json_decode, json_encode), "xml": (xml_decode, xml_encode)}


# ------------------------------------------------------------------------------
# the vectors
# ------------------------------------------------------------------------------
def build(sink):
    written, counters = {}, {}
    model = gtcheck.Model()
    texts, targets = {}, set()
    for module in ("core", "probe"):
        texts[module] = sink.read("model/%s.def" % module)
        model.add(texts[module])
        for raw in texts[module].splitlines():
            t = tokens(raw)
            if t and t[0] == "key":
                KEY_TYPES[t[1] if module == "core" else module + "." + t[1]] = t[2]
            if t and t[0] == "derive":
                targets.add(t[1])
    # the load vectors carry small modules, so an edit of model/ leaves them alone
    core = 'module core\nversion 0.1.0\ndistribution public\nsource "probe"\nkey uid string -\nkey time_ms int ms\n'
    probe = ('module probe\nversion 0.1.0\ndistribution public\nsource "probe"\nkey s1 string -\nkey n int -\n'
             'key x int -\nkey label string -\nlist items "a list"\n')
    packs = {}
    for name in PACKS:
        text = sink.read("packs/%s%s/pack.def" % (PREFIX, name))
        gtcheck.load_pack(text, model)
        packs[name] = parse_pack(text, PREFIX + name)
        assert not targets & set(text.split()), name

    def emit(owner, d):
        counters[owner] = counters.get(owner, 0) + 1
        sink.write("packs/%s/vectors/%02d-%s.json" % (owner, counters[owner], d["name"]),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[owner] = written.get(owner, 0) + 1

    def vec(frm, to, name, inp, expect=None, error=None, model_=None, ref=""):
        f, t = packs[frm], packs[to]
        got = failed = e0 = None
        try:
            e0 = CODECS[f["wire"]][0](f, inp)
            got = CODECS[t["wire"]][1](t, e0)
        except Fail as e:
            failed = e
        if error:
            assert failed is not None and failed.kind == error, (name, failed, got)
        else:
            assert failed is None, (name, failed and failed.why)
            assert got == expect, (name, expect, got)
        if model_:
            for k, v in model_.items():
                if k == "@absent":
                    assert not set(v) & set(e0["keys"]), (name, v)
                else:
                    have = e0["keys"]
                    for part in re.findall(r"\[(\d+)\]|([a-z0-9_]+\.(?:[a-z0-9_]+|#))", k):
                        have = have[int(part[0])] if part[0] else len(have[k[:-2]]) if k.endswith(".#") \
                            else have.get(part[1])
                    assert str(have) == v, (name, k, v, have)
        d = {"name": name, "from": f["name"], "to": t["name"], "input": inp}
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model_:
            d["model"] = model_
        d["source"] = SOURCE
        d["reference"] = ref
        emit(f["name"], d)

    # ==========================================================================
    # conformance-charset-bits (msb). L: A-H 0-7, J 8, K 9, L 10, M 11, N 12,
    # P 13, Q 14, R 15, S 16, T 17, U 18, V 19, W 20, X 21, Y 22, Z 23, in 6
    # bits; D: 0-9 in 4 bits. Bytes 0-2 code:L,L,D,D,D, bytes 3-5 codenum.
    # AB123: 000000 000001 0001 0010 0011 = 0000 0000 0001 0001 0010 0011 = 00 11 23
    # ZY987: 010111 010110 1001 1000 0111 = 5d 69 87; as a number
    #   23, 23*24+22 = 574, 5749, 57498, 574987
    # ==========================================================================
    BI = "spec 0.46, On bits; "
    vec("bits", "bits", "decode-encode-round-trip", "0011235d6987", "0011235d6987",
        model_={"probe.s1": "AB123", "probe.n": "574987"}, ref=BI + "code gives AB123; codenum gives 574987")
    vec("bits", "src", "to-json", "0011235d6987", '{"s1":"AB123","n":574987}', ref=BI + "the values")
    vec("bits", "bits", "ruling-03-code-0-characters-are-written", "000000000000", "000000000000",
        model_={"probe.s1": "AA000", "probe.n": "0"}, ref=BI + "ruling 3: every code 0 is a character; the number is 0")
    # 575999 = 576000 - 1, 576000 = 24*24*10*10*10: codes 23 23 9 9 9 = ZZ999:
    # 010111 010111 1001 1001 1001 = 5d 79 99
    vec("bits", "bits", "codenum-largest", "0011235d7999", "0011235d7999", model_={"probe.n": "575999"},
        ref=BI + "the product of the sizes less 1")
    vec("src", "bits", "codenum-one-past-the-largest", '{"n":576000}', error=TE, ref=BI + "x at the product")
    vec("src", "bits", "codenum-below-0", '{"n":-1}', error=TE, ref=BI + "x below 0")
    # code 24 in the first position: 011000 000001 0001 0010 0011 = 60 11 23
    vec("bits", "bits", "ruling-02-unused-letter-code", "601123000000", error=TD,
        ref=BI + "ruling 2: code 24 is beyond L's 24 characters")
    # code 10 in the third position: 000000 000001 1010 0010 0011 = 00 1a 23
    vec("bits", "bits", "ruling-02-unused-digit-code", "001a23000000", error=TD, ref=BI + "code 10 is beyond D")
    vec("bits", "bits", "ruling-02-unused-code-in-codenum", "001123001a23", error=TD,
        ref=BI + "codenum refuses an unused code too")
    vec("src", "bits", "encode-code-and-codenum", '{"s1":"AB123","n":1123}', "001123001123",
        ref=BI + "1123 = ((((0*24+1)*10+1)*10+2)*10+3): codes 0 1 1 2 3, the bits of AB123")
    vec("src", "bits", "encode-character-outside-its-set", '{"s1":"AI123"}', error=TE,
        ref=BI + "I is not in L")
    vec("src", "bits", "ruling-04-lowercase-letter", '{"s1":"ab123"}', error=TE, ref=BI + "ruling 4: case is exact")
    vec("src", "bits", "encode-four-characters", '{"s1":"AB12"}', error=TE, ref=BI + "one character per position")

    # lsb: AB123 is the number 001123 (ruling 6); the 24 bits read low bit first
    # are the bytes of that number, least significant first: 23 11 00
    vec("lsb", "lsb", "ruling-06-first-position-at-the-most-significant-end", "231100", "231100",
        model_={"probe.s1": "AB123"}, ref=BI + "ruling 6: the positions run from the top of the number uint reads")
    vec("bits", "lsb", "ruling-06-the-same-number-to-lsb", "0011235d6987", "231100",
        ref=BI + "ruling 6: the number 0x001123 in either bit order")

    ON = "spec 0.46 ruling 8; "
    vec("one", "one", "finding-41-2-bits-00", "00", "00", model_={"probe.s1": "00"},
        ref=ON + "a one-character set takes 1 bit: 0 0 is 00")
    for name, inp in (("01", "40"), ("10", "80"), ("11", "c0")):
        vec("one", "one", "finding-41-2-bits-%s" % name, inp, error=TD, ref=ON + "code 1 is unused")

    # ==========================================================================
    # five positions, 5+5+3+3+3 = 19 bits, every set full. L: A-Z 0-25, 2-7
    # 26-31; E: 0-7. BC357: 00001 00010 011 101 111 = 0x44ef = 17647.
    # 7A012: 11111 00000 000 001 010 = 0x7c00a. y = 21 (10101), z = 10 (01010).
    # msb: 00001000 10011101 11110101 | 01010111 11000000 00001010 = 08 9d f5 57 c0 0a
    # lsb: 0x44ef + 21 * 2^19 = 0xa844ef: ef 44 a8; 10 + 0x7c00a * 32 = 0xf8014a: 4a 01 f8
    # ==========================================================================
    FV = "spec 0.46 ruling 6; "
    five = {"probe.s1": "BC357", "probe.n": "17647", "probe.x": "17647", "probe.y": "21", "probe.z": "10",
            "probe.s2": "7A012"}
    both = "the same characters from the same number under both bit orders; full sets: codenum equals uint"
    vec("five-msb", "five-msb", "nineteen-bits-msb", "089df557c00a", "089df557c00a", model_=five, ref=FV + both)
    vec("five-lsb", "five-lsb", "nineteen-bits-lsb", "ef44a84a01f8", "ef44a84a01f8", model_=five, ref=FV + both)
    vec("five-msb", "five-lsb", "msb-to-lsb", "089df557c00a", "ef44a84a01f8", model_=five, ref=FV + both)
    vec("five-lsb", "five-msb", "lsb-to-msb", "ef44a84a01f8", "089df557c00a", model_=five, ref=FV + both)
    # 19 ones: 31 31 7 7 7 = 77777; 2^19 - 1 = 524287. msb ff ff e0; lsb ff ff 07
    top = {"probe.s1": "77777", "probe.n": "524287", "probe.x": "524287", "probe.y": "0", "probe.s2": "AA000"}
    vec("five-msb", "five-msb", "full-sets-largest-number", "ffffe0000000", "ffffe0000000", model_=top, ref=FV + both)
    vec("five-lsb", "five-lsb", "full-sets-largest-number", "ffff07000000", "ffff07000000", model_=top, ref=FV + both)
    # sequential: s1 (19), y (5), n (19), z (5).
    # msb: 08 9d f5 | 00001000 10011101 111 01010 = 08 9d ea
    # lsb: ef 44 a8 | 0x44ef + 10 * 2^19 = 0x5044ef: ef 44 50
    seq = {k: five[k] for k in ("probe.s1", "probe.y", "probe.n", "probe.z")}
    vec("five-seq-msb", "five-seq-msb", "nineteen-bits-sequential-msb", "089df5089dea", "089df5089dea", model_=seq,
        ref=FV + "sequential; " + both)
    vec("five-seq-lsb", "five-seq-lsb", "nineteen-bits-sequential-lsb", "ef44a8ef4450", "ef44a8ef4450", model_=seq,
        ref=FV + "sequential; " + both)
    vec("five-msb", "five-seq-lsb", "fixed-msb-to-sequential-lsb", "089df557c00a", "ef44a8ef4450", ref=FV + both)
    vec("five-seq-lsb", "five-seq-msb", "sequential-lsb-to-msb", "ef44a8ef4450", "089df5089dea", ref=FV + both)

    # swap: AB123 001123 reversed 23 11 00; ZY987 5d6987 reversed 87 69 5d
    SW = "spec 0.46, Where the rules apply (`swap`); "
    vec("swapopt", "swapopt", "swap-before-the-positions", "23110087695d", "23110087695d",
        model_={"probe.s1": "AB123", "probe.n": "574987"}, ref=SW + "the bytes are reversed, then the number is read")
    vec("bits", "swapopt", "to-swap", "0011235d6987", "23110087695d", ref=SW + "encode reverses the bytes after")

    # msb-lsb: BC35 = 00001 00010 011 101 = 0x089d = 2205; the first wire bit is
    # its bit 0: 10111001 00010000 = b9 10
    vec("msb-lsb", "msb-lsb", "sixteen-bits-msb-lsb", "b910", "b910", model_={"probe.s1": "BC35", "probe.x": "2205"},
        ref="spec 0.46, Where the rules apply (bit orders); ruling 6: the first position is at the top of the number")

    # items: label (19), qty (6), pad (7). BC357 and 5*8+3 = 43 = 101011:
    # 00001000 10011101 11110101 10000000; 7A012 and 0: 11111000 00000001 01000000 00
    vec("items", "items", "code-in-a-sequential-group-item", "02089df580f8014000", "02089df580f8014000",
        model_={"probe.items.#": "2", "probe.items[0].probe.label": "BC357", "probe.items[0].probe.qty": "43",
                "probe.items[1].probe.label": "7A012", "probe.items[1].probe.qty": "0"},
        ref="spec 0.46, Where the rules apply (groups)")

    AB = "spec 0.46, Where the rules apply (`absent`, 0.9); "
    vec("absent", "absent", "sentinels-of-the-raw-number", "ffffff001122", "ffffff001122",
        model_={"@absent": ["probe.s1", "probe.n"]},
        ref=AB + "16777215 is compared before any lookup (its codes are unused), and so is 4386 = 0x1122, the raw "
                 "number, not 1122, the codenum")
    vec("absent", "absent", "other-values-decode", "001123001123", "001123001123",
        model_={"probe.s1": "AB123", "probe.n": "1123"}, ref=AB + "neither raw number is a sentinel")
    vec("absent", "absent", "unused-codes-that-are-not-the-sentinel", "fffffe001123", error=TD, ref=AB + "ruling 2")
    vec("src", "absent", "absent-key-writes-the-sentinel", '{"n":1122}', "ffffff001122",
        ref=AB + "s1 is absent; n = 1122 is written though its raw number is the sentinel")

    # 15 sets of 16 and one of 8: 2^63, the largest number 63 ones, then one unmapped bit
    vec("wide", "wide", "sixty-four-bits-and-ruling-20", "9876543210987654fffffffffffffffe",
        "9876543210987654fffffffffffffffe",
        model_={"probe.s1": "9876543210987654", "probe.big": "9223372036854775807"},
        ref=BI + "len 64; ruling 20: 16 positions whose product is exactly 2^63, at its largest number")
    vec("wide", "wide", "unused-code-at-the-top", "a8765432109876540000000000000000", error=TD, ref=BI + "ruling 2")

    # ABCD: a 00 01 10 11 = 1b; b (DCBA) 11 10 01 00 = e4
    R1 = "spec 0.46 ruling 1; code order is the pack's: both packs read the text ABCD"
    vec("order-a", "order-b", "one-text-other-codes", "1b", "e4", model_={"probe.s1": "ABCD"}, ref=R1)
    vec("order-b", "order-a", "one-text-other-codes", "e4", "1b", model_={"probe.s1": "ABCD"}, ref=R1)
    VI = "spec 0.46, Where the rules apply (`via`, 0.6); "
    vec("via", "via", "via-after-the-transform", "0107", "0107", model_={"probe.s1": "alpha", "probe.s2": "seven"},
        ref=VI + "the string 01 and the integer 7 (not the text 07) are looked up")
    vec("via", "via", "no-entry-of-one-type-passes", "0307", "0307", model_={"probe.s1": "03"}, ref=VI + "string to string")
    vec("via", "via", "no-entry-of-two-types", "0108", error=TD, ref=VI + "8 has no entry and the types differ")
    # s2 is absent: zero bits
    vec("src", "via", "via-encode", '{"s1":"beta"}', "0200", ref=VI + "beta is 02")

    # armor: 000000 000001 000100 100011 = 0 1 4 35: 0 1 4 S
    vec("armor", "armor", "armor-sixbit", "014S", "014S", model_={"probe.s1": "AB123"},
        ref="spec 0.46, Where the rules apply (`armor sixbit`)")

    # ==========================================================================
    # text wires
    # ==========================================================================
    JS = "spec 0.46, On text wires (json); "
    full = '{"call":"AB123","id":"01234","num":"00042"}'
    vec("json", "json", "codestr-and-codenum", full, full,
        model_={"probe.s1": "AB123", "probe.s2": "01234", "probe.x": "42"},
        ref=JS + "codenum 00042 is 42 and is written back with its code-0 characters")
    vec("json", "json", "finding-41-5-number-member-under-codestr", '{"id":12345}', error=TD,
        ref=JS + "ruling 11: the member must be a string")
    vec("json", "json", "number-member-under-codenum", '{"num":42}', error=TD, ref=JS + "ruling 11")
    vec("json", "json", "four-characters", '{"call":"AB12"}', error=TD, ref=JS + "ruling 3: a shorter text")
    vec("json", "json", "ruling-04-lowercase-letter", '{"call":"ab123"}', error=TD, ref=JS + "ruling 4")
    vec("json", "json", "no-trimming", '{"call":"AB123 "}', error=TD, ref=JS + "no character is trimmed")
    vec("src", "json", "finding-41-5-codenum-writes-a-string", '{"x":12345}', '{"num":"12345"}',
        ref=JS + "ruling 11: codenum encode writes a string")
    vec("src", "json", "codenum-writes-every-position", '{"x":7}', '{"num":"00007"}', ref=JS + "ruling 3")
    vec("src", "json", "codenum-out-of-range", '{"x":100000}', error=TE, ref=JS + "10^5 is the product")
    vec("src", "json", "codestr-character-outside-its-set", '{"s1":"AI123"}', error=TE, ref=JS + "I is not in L")

    vec("absent-json", "absent-json", "sentinel-texts", '{"call":"NONE","num":"NA"}', '{"call":"NONE","num":"NA"}',
        model_={"@absent": ["probe.s1", "probe.x"]}, ref=AB + "on json the text, before any lookup")
    vec("absent-json", "absent-json", "other-texts-decode", '{"call":"AB123","num":"07"}', '{"call":"AB123","num":"07"}',
        model_={"probe.s1": "AB123", "probe.x": "7"}, ref=AB + "neither text is a sentinel")
    vec("absent-json", "absent-json", "text-that-is-not-the-sentinel", '{"num":"NB"}', error=TD, ref=AB + "ruling 3")

    R22 = "spec 0.46 ruling 22 (0.9 unchanged); "
    both = "the sentinel is compared as text before ruling 11's check; "
    vec("absent-number", "absent-number", "string-member-matches", '{"a":"5"}', '{"a":5}',
        model_={"@absent": ["probe.s1"]}, ref=R22 + both + "`absent 5` writes the number 5")
    vec("absent-number", "absent-number", "number-member-matches", '{"a":5}', '{"a":5}',
        model_={"@absent": ["probe.s1"]}, ref=R22 + both + "`absent 5` writes the number 5")
    vec("absent-text", "absent-text", "string-member-matches", '{"a":"5"}', '{"a":"5"}',
        model_={"@absent": ["probe.s1"]}, ref=R22 + both + "`absent =5` writes the text 5")
    vec("absent-text", "absent-text", "number-member-matches", '{"a":5}', '{"a":"5"}',
        model_={"@absent": ["probe.s1"]}, ref=R22 + both + "`absent =5` writes the text 5")
    vec("absent-text", "absent-text", "number-that-is-not-the-sentinel", '{"a":6}', error=TD,
        ref=R22 + "6 is no sentinel; ruling 11: the member must be a string")

    TX = "spec 0.46, On text wires (text); "
    rec = "AB123,00042 ,7"
    vec("text", "text", "codestr-and-codenum-column", rec, rec, model_={"probe.s1": "AB123", "probe.x": "42", "probe.n": "7"},
        ref=TX + "the column's trailing space is removed, and written back (ruling 14)")
    vec("text", "text", "ruling-14-column-padded-on-the-right", "AB123,00042,7", rec, model_={"probe.x": "42"},
        ref=TX + "the field ends inside the column; encode pads with a space on the right")
    vec("text", "text", "ruling-14-leading-space-refused", "AB123, 0042 ,7", error=TD,
        ref=TX + "ruling 14: codenum keeps the leading space, which is not in D")
    vec("text", "text", "four-characters", "AB12,00042 ,7", error=TD, ref=TX + "ruling 3")
    vec("text", "text", "column-absent", "AB123,,7", "AB123,,7", model_={"@absent": ["probe.x"]},
        ref=TX + "an empty field: the key is absent")
    # n = 7: codes 0 0 0 0 7 = 000000 000000 0000 0000 0111 = 00 00 07
    vec("text", "bits", "text-to-bits", rec, "001123000007", ref=TX + "the identifier keeps its code-0 characters")
    vec("bits", "text", "bits-to-text", "0011235d6987", "AB123,,574987",
        ref=TX + "three fields: the lines address 0 to 2; field 1 is empty")
    vec("src", "text", "codenum-column-from-json", '{"x":42}', ",00042 ,", ref=TX + "the column of 6 holds 00042 and a space")

    XM = "spec 0.46, On text wires (xml); "
    xin = '<R num="00042"><call>AB123</call></R>'
    vec("xml", "xml", "codenum-on-an-attribute", xin, xin, model_={"probe.x": "42", "probe.s1": "AB123"},
        ref=XM + "codenum 00042 is 42; the width 99 of D is ignored off bits (ruling 14)")
    vec("xml", "xml", "codenum-short-text", '<R num="42"/>', error=TD, ref=XM + "ruling 3")
    vec("xml", "xml", "ruling-04-lowercase-letter", "<R><call>ab123</call></R>", error=TD, ref=XM + "ruling 4")
    vec("src", "xml", "codenum-encode", '{"x":12345}', '<R num="12345"/>', ref=XM + "the five characters")

    # ==========================================================================
    # load vectors from 4600
    # ==========================================================================
    head = 'format probe\nversion 0.46.0\ndistribution public\nsource "probe"\nuses probe\n'
    bits = head + "wire bits\nword_bytes 1\n"
    js, xm, tx, pb, tlv = (head + "wire json\n", head + "wire xml\nroot R\n", head + "wire text\n",
                           head + "wire protobuf\n", head + "wire tlv\n")
    LD = "charset L ABCDEFGHJKLMNPQRSTUVWXYZ\ncharset D 0123456789\n"     # widths 5 and 4
    lnum = [4599]

    def load(name, text, error="bad-directive", models=None, gtcheck_kind=None):
        lnum[0] += 1
        full = "%d-charset-%s" % (lnum[0], name)
        mods = models or [core, probe]
        got = None
        try:
            m = gtcheck.Model()
            for t in mods:
                m.add(t)
            gtcheck.load_pack(text, m)
        except gtcheck.CheckError as e:
            got = e.kind
        assert got == (gtcheck_kind or error), (full, error, got)
        d = {"name": full, "models": mods, "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    bogus = "bogus\n"
    # L 5 bits x2 + D 4 bits x3 = 22
    load("code-and-codenum-load", bits + LD + "field probe.s1 0:0:22 code:L,L,D,D,D\n"
         "field probe.n 0:22:22 codenum:L,L,D,D,D\n", None)
    load("with-one-argument", bits + "charset L\n")
    load("with-four-arguments", bits + "charset L ABC 2 x\n")
    load("with-four-arguments-then-bogus", bits + "charset L ABC 2 x\n" + bogus)
    load("finding-41-1-name-with-a-comma", bits + "charset A,B 0123\n")
    load("name-with-a-dot", bits + "charset a.b 0123\n")
    load("name-of-underscore-and-hyphen-loads", bits + "charset a_B-9 01\nfield probe.s1 0:0:1 code:a_B-9\n", None)
    load("finding-41-3-hash-inside-the-token-loads", bits + "charset S AB#C\nfield probe.s1 0:0:2 code:S\n", None)
    lnum[0] += 1        # 4608 (`charset Q A"B`) is withdrawn: 0.11 leaves a quote inside a token unruled
    load("repeated-character", bits + "charset R AAB\n")
    load("character-outside-the-range", bits + 'charset R "A B"\n')
    load("width-below-the-default", bits + "charset D 0123456789 3\n")
    load("width-above-8", bits + "charset D 0123456789 9\n")
    load("width-of-8-loads", bits + "charset D 0123456789 8\nfield probe.s1 0:0:8 code:D\n", None)
    load("second-charset-of-one-name", bits + "charset D 0123456789\ncharset D ABC\n")
    load("charset-after-the-first-kind", bits + "field probe.x 0:0:8 uint\nkind k\n  when 0:0:8 1\n"
         "charset D 0123456789\n")
    load("ruling-14-charset-before-the-wire-line-loads", head + LD + "wire json\nfield probe.s1 a codestr:L,D\n", None)
    load("ruling-14-width-ignored-off-bits-loads", js + "charset D 0123456789 99\nfield probe.s1 a codestr:D\n", None)
    load("finding-41-6-set-holds-the-delimiter", tx + "charset P A,B\nfield probe.s1 0 codestr:P\n")
    load("set-with-the-delimiter-unused-loads", tx + "charset P A,B\ncharset D 0123456789\nfield probe.s1 0 codestr:D\n",
         None)
    load("set-holds-star-under-nmea", tx + "checksum nmea\ncharset P A*B\nfield probe.s1 0 codestr:P\n")
    load("finding-41-4-absent-on-text", tx + "charset L AB\nfield probe.s1 1 codestr:L,L absent AA\n")
    load("undeclared-set", bits + LD + "field probe.s1 0:0:9 code:L,Q\n")
    load("ruling-13-empty-set-name", bits + LD + "field probe.s1 0:0:14 code:L,,D\n")
    load("no-position", bits + LD + "field probe.s1 0:0:5 code:\n")
    load("seventeen-positions", bits + LD + "field probe.s1 0:0:68 code:%s\n" % ",".join(["D"] * 17))
    load("sixteen-positions-load", bits + LD + "field probe.s1 0:0:64 code:%s\n" % ",".join(["D"] * 16), None)
    load("length-not-the-sum-of-the-widths", bits + LD + "field probe.s1 0:0:10 code:L,D\n")
    # 94^10 is about 5.4e19, above 2^63 (about 9.2e18)
    load("codenum-product-above-2-63", js + "charset A %s\nfield probe.n a codenum:%s\n"
         % ("".join(chr(c) for c in range(0x21, 0x7F) if chr(c) != '"'), ",".join(["A"] * 10)))
    load("code-on-json", js + LD + "field probe.s1 a code:L,D\n")
    load("codestr-on-bits", bits + LD + "field probe.s1 0:0:9 codestr:L,D\n")
    load("codenum-on-protobuf", pb + LD + "field probe.n 1 codenum:L,D\n")
    load("codestr-on-tlv", tlv + LD + "field probe.s1 1 codestr:L,D\n")
    load("code-on-json-then-bogus", js + LD + "field probe.s1 a code:L,D\n" + bogus, "unknown-directive",
         gtcheck_kind="bad-directive")
    load("code-on-an-int-key", bits + LD + "field probe.n 0:0:9 code:L,D\n", "key-type-mismatch")
    load("codenum-on-a-string-key", js + LD + "field probe.s1 a codenum:L,D\n", "key-type-mismatch")
    load("code-in-a-sequential-pack-loads", head + "wire bits\nlayout sequential\n" + LD
         + "field probe.s1 22 code:L,L,D,D,D\n", None)
    load("in-a-module", js + "field probe.s1 a string\n", "unknown-directive",
         models=[core, probe + "charset D 0123456789\n"], gtcheck_kind="bad-directive")
    load("codestr-and-codenum-on-geojson-load", head + "wire geojson\n" + LD
         + "field probe.s1 properties.a codestr:L,D\nfield probe.n properties.b codenum:L,D\n", None)
    sq = head + "wire bits\nlayout sequential\n"
    up = sq + "bit_order msb\nencoding uper\n"
    wide = LD + "charset X 0123456789abcdef\ncharset E 01234567\n"
    xs = lambda n: ",".join(["X"] * n)                     # noqa: E731
    # 15 positions of 4 bits and one of 5: 65 bits, the sum of the widths
    sixty5 = "code:%s,L\n" % ",".join(["D"] * 15)
    load("length-65", bits + LD + "field probe.s1 0:0:65 " + sixty5)
    load("length-65-sequential", sq + LD + "field probe.s1 65 " + sixty5)
    load("seventeen-positions-on-json", js + LD + "field probe.s1 a codestr:%s\n" % ",".join(["D"] * 17))
    load("ruling-20-codenum-product-2-63-loads", bits + wide + "field probe.n 0:0:63 codenum:E,%s\n" % xs(15), None)
    load("codenum-product-2-64", bits + wide + "field probe.n 0:0:64 codenum:%s\n" % xs(16))
    load("code-in-a-sequential-group-item-loads", sq + LD + "group probe.items count 8\n"
         "  field probe.label 22 code:L,L,D,D,D\nend\n", None)
    load("absent-on-code-and-codenum-loads", bits + LD + "field probe.s1 0:0:9 code:L,D absent 511\n"
         "field probe.n 0:9:9 codenum:L,D absent 0,511\n", None)
    load("absent-value-does-not-fit", bits + LD + "field probe.s1 0:0:9 code:L,D absent 512\n")
    load("swap-on-code-loads", bits + LD + "field probe.s1 0:0:8 code:D,D swap\n", None)
    load("swap-on-a-length-not-of-whole-bytes", bits + LD + "field probe.s1 0:0:9 code:L,D swap\n")
    load("trim-on-code", bits + LD + "field probe.s1 0:0:8 code:D,D trim\n")
    load("ruling-21-msb-lsb-not-a-multiple-of-8-loads", bits + "bit_order msb-lsb\n" + LD
         + "field probe.s1 0:0:9 code:L,D\n", None)
    load("bit-length-in-a-uper-pack-loads", up + LD + "field probe.s1 9 code:L,D\n", None)
    load("codenum-on-a-uper-locator", up + LD + "field probe.n int:0:255 codenum:D,D\n")
    load("code-on-xml", xm + LD + "field probe.s1 @a code:L,D\n")
    load("code-on-text", tx + LD + "field probe.s1 0 code:L,D\n")
    # after the file: a later line's error comes first
    for name, body in (("charset-name", "charset A,B 0123\n"),
                       ("repeated-character", "charset R AAB\n"),
                       ("undeclared-set", "field probe.s1 0:0:9 code:L,Q\n"),
                       ("no-position", "field probe.s1 0:0:5 code:\n"),
                       ("length", "field probe.s1 0:0:10 code:L,D\n")):
        load("%s-then-bogus" % name, bits + LD + body + bogus, "unknown-directive", gtcheck_kind="bad-directive")
    load("charset-error-before-missing-distribution", bits.replace("distribution public\n", "") + "charset R AAB\n")
    load("charset-before-missing-wire-is-an-argument-count", head + "charset L\n")
    in_group = sq + "group probe.items count 8\n  charset D 0123456789\n  field probe.x 8 uint\nend\n"
    load("ruling-16-charset-in-a-group-body", in_group)
    load("ruling-16-charset-in-a-group-body-then-bogus", in_group + bogus, "unknown-directive",
         gtcheck_kind="bad-directive")
    load("ruling-15-second-colon-then-bogus", bits + LD + "field probe.s1 0:0:4 code:D:x\n" + bogus,
         "unknown-directive", gtcheck_kind="bad-directive")
    load("ruling-15-second-colon", bits + LD + "field probe.s1 0:0:4 code:D:x\n")
    load("ruling-17-width-with-a-plus-sign", bits + "charset D 0123456789 +4\n")
    load("ruling-18-code-on-cbor", head + "wire cbor\n" + LD + "field probe.s1 1 code:L,D\n")
    # rulings 21, 23 and 24, from 4668
    gj = head + "wire geojson\n" + LD
    bare = bits + LD + "field probe.s1 0:0:8 code\n"
    bare_text = tx + LD + "field probe.s1 0 codestr\n"
    load("ruling-21-bare-code", bare)
    load("ruling-21-bare-code-then-bogus", bare + bogus, "unknown-directive", gtcheck_kind="bad-directive")
    load("ruling-21-bare-codestr-on-text", bare_text)
    load("ruling-21-bare-codestr-on-text-then-bogus", bare_text + bogus, "unknown-directive",
         gtcheck_kind="bad-directive")
    load("ruling-23-codestr-on-a-geojson-coordinate", gj + "field probe.s1 geometry.lat codestr:L,D\n")
    load("ruling-23-codestr-on-a-geojson-coordinate-then-bogus", gj + "field probe.s1 geometry.lat codestr:L,D\n"
         + bogus, "unknown-directive", gtcheck_kind="bad-directive")
    load("ruling-23-codenum-on-a-geojson-coordinate", gj + "field probe.n geometry.lat codenum:L,D\n")
    load("ruling-23-geometry-path-in-a-group-body-loads", gj + "group probe.items properties.items\n"
         "  field probe.label geometry.lat codestr:L,D\n  field probe.n geometry.lon codenum:L,D\nend\n", None)
    load("ruling-24-width-with-a-leading-zero-loads", bits + "charset D 0123456789 08\nfield probe.s1 0:0:8 code:D\n",
         None)
    load("ruling-24-more-characters-than-2-width-off-bits-loads", js + "charset D 0123456789 2\n"
         "field probe.s1 a codestr:D\n", None)
    load("ruling-24-charset-after-a-group-with-item-kinds-loads", sq + "group probe.items count 8\n  kind a\n"
         "  when 8 1\n  field probe.n 8 uint\nend\ncharset D 0123456789\nfield probe.s1 8 code:D,D\n"
         "kind m\nwhen 8 1\n", None)
    load("ruling-17-third-token-ignored-off-bits-loads", js + "charset D 01 +4\nfield probe.s1 a codestr:D\n", None)
    # ruling 15: the values of `absent` stay a line check (0.11 5b, step 10), so
    # they come before a later `bogus`
    load("ruling-15-absent-value-does-not-fit-then-bogus", bits + LD
         + "field probe.s1 0:0:9 code:L,D absent 512\n" + bogus)
    load("ruling-15-absent-null-on-json-then-bogus", js + LD + "field probe.s1 a codestr:L,D absent null\n" + bogus)
    rel = "packs/conformance/load-vectors"
    for f in sink.listdir(rel):
        if f[:2] == "46" and f[4:13] == "-charset-" and rel + "/" + f not in sink.written:
            sink.remove(rel + "/" + f)
    # what an earlier run wrote and this one did not goes
    for name in PACKS:
        rel = "packs/%s%s/vectors" % (PREFIX, name)
        for f in sink.listdir(rel):
            if rel + "/" + f not in sink.written:
                sink.remove(rel + "/" + f)
    return written


def main(argv=None):
    return genio.vector_main("conformance-charset-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
