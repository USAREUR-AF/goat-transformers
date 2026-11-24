#!/usr/bin/env python3
"""Write the vectors of spec 0.42, character-coded identifiers (`charset`,
`code`, `codestr`, `codenum`): the vectors of the packs named in PACKS below
(`conformance-charset-*`) and the load vectors from 1514.

Every expected value here is worked out by hand from the spec text (Version
0.42: Grammar, On `bits`, On text wires, Where the rules apply, Load errors,
rulings 1 to 14; and the sections they refer to: 0.2 and 0.5 bit order, 0.6
absent keys on a fixed layout, 0.10 the `text` wire and its columns, 0.15
`chars`, 0.37 byte order chosen per message, 0.11 ruling 5b) and the pack
layouts. The hand working, bit by bit, is the comment above each vector;
the value is written out literally.

It is checked against a second computation: the small codecs below read the
committed pack.def files with their own parser and apply the rules to the
input (a fixed-layout bits reader and writer in either bit order with the
order line of 0.37, a text record reader and writer, and json and xml for
the lines these packs use). Load vectors and the packs are checked against
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

PACKS = ("src", "bits", "lsb", "one", "swap", "json", "text", "xml")
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
    pack = {"name": name, "wire": None, "bit_order": "lsb", "root": None, "charsets": {}, "fields": [],
            "swap_when": None}
    for raw in text.splitlines():
        t = tokens(raw)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in ("format", "version", "distribution", "source", "uses", "word_bytes"):
            continue
        if d in ("wire", "bit_order", "root"):
            pack[d] = a[0]
        elif d == "charset":
            pack["charsets"][a[0]] = a[1:]               # characters, and the width if given
        elif d == "swap_when":
            pack["swap_when"] = (a[0], [int(v) for v in a[1].split(",")])
        elif d == "field":
            tr, _, sets = a[2].partition(":")
            pack["fields"].append({"key": a[0], "loc": a[1], "tr": tr, "sets": sets.split(",") if sets else None})
        else:
            raise AssertionError("line not read here: %r" % raw)
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
# codes, text and numbers (0.42)
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
# bits, fixed layout, word_bytes 1 (0.2, 0.5), with the order line of 0.37
# ------------------------------------------------------------------------------
def bit_index(pack, i):
    """(byte, bit within the byte) of message bit i."""
    return i // 8, (7 - i % 8) if pack["bit_order"] == "msb" else i % 8


def read_uint(pack, data, start, width):
    v = 0
    for k in range(width):
        byte, bit = bit_index(pack, start + k)
        b = (data[byte] >> bit) & 1
        if pack["bit_order"] == "msb":
            v = v << 1 | b                                 # first bit most significant
        else:
            v |= b << k                                    # low bit first
    return v


def write_uint(pack, buf, start, width, v):
    for k in range(width):
        b = (v >> (width - 1 - k)) & 1 if pack["bit_order"] == "msb" else (v >> k) & 1
        byte, bit = bit_index(pack, start + k)
        buf[byte] = buf[byte] & ~(1 << bit) | b << bit


def loc(node):
    word, pos, ln = (int(x) for x in node["loc"].split(":"))
    return word * 8 + pos, ln


def reverse_bytes(v, ln):
    return int.from_bytes(v.to_bytes(ln // 8, "big")[::-1], "big")


def bits_decode(pack, text):
    data = bytes.fromhex(text)
    need = max(sum(loc(f)) for f in pack["fields"])
    if len(data) * 8 < need:
        raise Fail("malformed-wire", "short")
    keys = {}
    swapped = False
    if pack["swap_when"]:
        order = next(f for f in pack["fields"] if f["key"] == pack["swap_when"][0])
        swapped = read_uint(pack, data, *loc(order)) in pack["swap_when"][1]
    for f in pack["fields"]:
        start, ln = loc(f)
        if f["tr"] == "uint":
            v = read_uint(pack, data, start, ln)
            if swapped and f is not order and ln >= 16:
                v = reverse_bytes(v, ln)                   # 0.37: a value read as one number
            keys[f["key"]] = v
            continue
        pos = positions(pack, f)
        codes, at = [], start
        for _, w in pos:                                   # each position as `uint` reads it, never reversed
            codes.append(read_uint(pack, data, at, w))
            at += w
        keys[f["key"]] = codes_to_text(pos, codes, TD) if f["tr"] == "code" else codes_to_number(pos, codes, TD)
    return {"keys": keys}


def bits_encode(pack, ent):
    keys = ent["keys"]
    need = max(sum(loc(f)) for f in pack["fields"])
    buf = bytearray((need + 7) // 8)
    swapped = False
    if pack["swap_when"]:
        swapped = keys.get(pack["swap_when"][0]) in pack["swap_when"][1]
    for f in pack["fields"]:
        start, ln = loc(f)
        v = keys.get(f["key"])
        if v is None:
            continue                                       # an absent key writes zero bits
        if f["tr"] == "uint":
            if swapped and f["key"] != pack["swap_when"][0] and ln >= 16:
                v = reverse_bytes(v, ln)
            write_uint(pack, buf, start, ln, v)
            continue
        pos = positions(pack, f)
        codes = text_to_codes(pos, v, TE) if f["tr"] == "code" else number_to_codes(pos, v)
        at = start
        for (_, w), c in zip(pos, codes):
            write_uint(pack, buf, at, w, c)
            at += w
    return bytes(buf).hex()


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


def json_decode(pack, text):
    obj = json.loads(text)
    keys = {}
    for f in pack["fields"]:
        v = obj.get(f["loc"])
        if v is None:
            continue
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
    core, probe = texts["core"], texts["probe"]
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
                    assert str(e0["keys"].get(k)) == v, (name, k, v, e0["keys"].get(k))
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
    BI = "spec 0.42, On bits; "
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

    # lsb: positions at bits 0-5, 6-11, 12-15, 16-19, 20-23, each low bit first.
    # AB123: B (1) sets bit 6 = byte 0 bit 6 (40); 1 sets bit 12 = byte 1 bit 4
    # (10); 2 sets bit 17 = byte 2 bit 1, 3 sets bits 20 and 21 = byte 2 bits
    # 4 and 5: 02 | 30 = 32
    vec("lsb", "lsb", "positions-in-the-pack-bit-order", "401032", "401032", model_={"probe.s1": "AB123"},
        ref=BI + "each position is read as uint reads its own bits, low bit first")

    ON = "spec 0.42 ruling 8; "
    vec("one", "one", "finding-41-2-bits-00", "00", "00", model_={"probe.s1": "00"},
        ref=ON + "a one-character set takes 1 bit: 0 0 is 00")
    for name, inp in (("01", "40"), ("10", "80"), ("11", "c0")):
        vec("one", "one", "finding-41-2-bits-%s" % name, inp, error=TD, ref=ON + "code 1 is unused")

    SW = "spec 0.42 ruling 6 with 0.37; "
    # swapped (x = 1): codenum bytes 02 05 read in order: 2*10+5 = 25; the
    # uint bytes 01 00 are reversed: 00 01 = 1
    vec("swap", "swap", "finding-41-7-codenum-not-reversed", "0102050100", "0102050100",
        model_={"probe.x": "1", "probe.n": "25", "probe.y": "1"},
        ref=SW + "finding 41-7: the characters are never reversed; the uint is")
    vec("swap", "swap", "not-swapped", "0002050001", "0002050001", model_={"probe.x": "0", "probe.n": "25", "probe.y": "1"},
        ref=SW + "the same values in the pack's order")
    vec("src", "swap", "encode-swapped", '{"x":1,"n":25,"y":1}', "0102050100", ref=SW + "encode in the message's order")

    # ==========================================================================
    # text wires
    # ==========================================================================
    JS = "spec 0.42, On text wires (json); "
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

    TX = "spec 0.42, On text wires (text); "
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

    XM = "spec 0.42, On text wires (xml); "
    xin = '<R num="00042"><call>AB123</call></R>'
    vec("xml", "xml", "codenum-on-an-attribute", xin, xin, model_={"probe.x": "42", "probe.s1": "AB123"},
        ref=XM + "codenum 00042 is 42; the width 99 of D is ignored off bits (ruling 14)")
    vec("xml", "xml", "codenum-short-text", '<R num="42"/>', error=TD, ref=XM + "ruling 3")
    vec("xml", "xml", "ruling-04-lowercase-letter", "<R><call>ab123</call></R>", error=TD, ref=XM + "ruling 4")
    vec("src", "xml", "codenum-encode", '{"x":12345}', '<R num="12345"/>', ref=XM + "the five characters")

    # ==========================================================================
    # load vectors from 1514
    # ==========================================================================
    head = 'format probe\nversion 0.42.0\ndistribution public\nsource "probe"\nuses probe\n'
    bits = head + "wire bits\nword_bytes 1\n"
    js, xm, tx, pb, tlv = (head + "wire json\n", head + "wire xml\nroot R\n", head + "wire text\n",
                           head + "wire protobuf\n", head + "wire tlv\n")
    LD = "charset L ABCDEFGHJKLMNPQRSTUVWXYZ\ncharset D 0123456789\n"     # widths 5 and 4
    lnum = [1513]

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
    load("finding-41-3-double-quote", bits + 'charset Q A"B\n')
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
    return written


def main(argv=None):
    return genio.vector_main("conformance-charset-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
