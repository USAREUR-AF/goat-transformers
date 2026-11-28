#!/usr/bin/env python3
"""Write the vectors of spec 0.22, long and terminated fields: the packs
`conformance-long-*` and the load vectors from 1010.

Every expected value here is worked out by hand from the spec text (Version
0.22 and its rulings 1 to 21, and the sections they refer to: 0.2 and 0.5 for
`bits` addressing, bit orders, `ascii`, `f32` and `swap`; 0.6 for defaults;
0.8 for sequential lines, presence, `length` and group counts; 0.9 for
`absent`; 0.15 for `chars`, `smag` and their rulings; 0.21 for `rest` groups
and count lines; 0.5 for canonical json output). The hand working is the
comment above each vector. Bits are written in reading order, the order of
their positions in the message: under `msb` and `msb-lsb` position 0 is the
high bit of byte 0, under `lsb` its low bit. A paper value written as a bit
string goes through `B(order, bits)`, which only packs the written bits into
bytes; the value itself is stated literally.

The paper values are checked against a second computation: the small codecs
below read the committed pack.def files with their own parser and apply the
rules to the input. They cover only the lines these packs use, and stop with
an assertion on a case the spec leaves open (see `Open`). Load vectors are
checked against tools/gen/gtcheck.py. Nothing here imports or calls an
engine.

Readings of the text these vectors rest on, reported with them:
- `ascii8` with neither `stop` nor `until:`: the 0.15 rule "with `ascii7` a
  NUL followed by a character that is not NUL is `transform-decode`" and
  ruling 17 of 0.15 ("NUL in `ascii7` text is `transform-encode`") name
  `ascii7` only; whether they hold for `ascii8` is not decided, and no vector
  here depends on it.
- `stop` with a code the set gives no character (`icao6 stop 0`): the codes
  are compared before the set's validity check, as ruling 9 states for
  `until:`.
- `until:<code>` takes `via`: "takes no `absent`, `swap` or `trim`; anything
  else is `bad-directive`" is read as naming the uses above it, so `via`
  loads. `until:00` is plain digits and loads.
- `stop <code>` with a code that is not plain digits is `bad-directive`, as
  for `until:`; the text states only the bound for `stop`.
- Ruling 25 ("writes the terminator alone, as an absent key does (ruling
  10)") with a `default` on the line: ruling 1 of 0.18 gives a suppressed
  line "neither a `default` nor a sentinel", so the terminator alone is
  written, not the default; ruling 10 applies when the line is not
  suppressed. The `int:<lb>:<ub>` locator of 0.19 (the only UPER form here)
  is `uint` under `msb`: the value minus `lb` in the fewest bits that hold
  `ub - lb`.

Inputs: the pack.def files of the `conformance-long-*` packs and
model/probe.def. Writes, under --out, the vector files named above. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-long-vectors.py [--out DIR] [--check]
"""
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PREFIX = "conformance-long-"
MW, TD, TE = "malformed-wire", "transform-decode", "transform-encode"


class Fail(Exception):
    """A conversion that fails with an error kind of the spec."""

    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


class Open(AssertionError):
    """A case the spec text does not decide: no vector may reach it."""


# ------------------------------------------------------------------------------
# bits in reading order, and values in the three bit orders
# ------------------------------------------------------------------------------
def stream(hx, order):
    """The input's bits by position: under lsb position i is bit i mod 8 of
    byte i div 8 (0.2), under msb and msb-lsb bit 7 - (i mod 8) (0.5, 0.22)."""
    out = []
    for byte in bytes.fromhex(hx):
        out += [(byte >> (i if order == "lsb" else 7 - i)) & 1 for i in range(8)]
    return out


def unstream(bits, order):
    bits = bits + [0] * (-len(bits) % 8)
    return bytes(sum(b << (k if order == "lsb" else 7 - k) for k, b in enumerate(bits[i:i + 8]))
                 for i in range(0, len(bits), 8)).hex()


def B(order, text):
    """A paper value: bits written in reading order (spaces ignored), as hex."""
    return unstream([int(c) for c in text if c in "01"], order)


def value(bits, order):
    """A field's value: msb takes the first bit most significant; lsb and
    msb-lsb take it least significant."""
    if order == "msb":
        return sum(b << (len(bits) - 1 - k) for k, b in enumerate(bits))
    return sum(b << k for k, b in enumerate(bits))


def place(v, n, order):
    if not 0 <= v < (1 << n):
        raise Fail(TE, "%d does not fit %d bits" % (v, n))
    if order == "msb":
        return [(v >> (n - 1 - k)) & 1 for k in range(n)]
    return [(v >> k) & 1 for k in range(n)]


def swapped(bits):
    """Ruling 13: 8-bit chunks of the field from its first bit, in reverse order."""
    chunks = [bits[i:i + 8] for i in range(0, len(bits), 8)]
    return [b for c in reversed(chunks) for b in c]


# ------------------------------------------------------------------------------
# character sets (0.15, and ascii8 of 0.22)
# ------------------------------------------------------------------------------
WIDTH = {"icao6": 6, "ais6": 6, "ascii7": 7, "ascii8": 8}
PAD = {"icao6": 32, "ais6": 0, "ascii7": 0, "ascii8": 0}


def char_of(cs, c, kind=TD):
    if cs == "icao6":
        if 1 <= c <= 26:
            return chr(64 + c)
        if c == 32 or 48 <= c <= 57:
            return chr(c)
    elif cs == "ais6":
        return chr(c + 64) if c < 32 else chr(c)
    elif c == 0 or 32 <= c <= 126:     # ascii7 and ascii8
        return chr(c)
    raise Fail(kind, "code %d is not a character of %s" % (c, cs))


def code_of(cs, ch):
    for c in range(1 << WIDTH[cs]):
        try:
            if char_of(cs, c) == ch:
                return c
        except Fail:
            pass
    raise Fail(TE, "%r is not a character of %s" % (ch, cs))


def chars_decode(cs, codes, stop):
    if stop is not None and stop in codes:
        # 0.22: the text ends at the first character whose code is `stop`;
        # the rest of the field is ignored. Ruling 18: nothing is removed;
        # rulings 20 and 21: NUL is an ordinary character
        return "".join(char_of(cs, c) for c in codes[:codes.index(stop)])
    # ruling 19: a stop field with no terminator decodes as without stop
    text = "".join(char_of(cs, c) for c in codes)
    pad = char_of(cs, PAD[cs])
    if cs in ("ascii7", "ascii8"):
        body = text.rstrip(pad)
        if "\0" in body:
            if cs == "ascii8":
                raise Open("NUL before a character in ascii8 without stop")
            raise Fail(TD, "ascii7: NUL followed by a character")
        return body
    return text.rstrip(" " + pad)          # icao6, ais6: padding and spaces


def chars_encode(cs, text, count, stop):
    codes = [code_of(cs, ch) for ch in text]
    if stop is not None:
        if stop in codes or len(codes) + 1 > count:
            raise Fail(TE, "stop: no room for the terminator, or the text holds it")
        codes.append(stop)
    else:
        if "\0" in text:
            if cs == "ascii8":
                raise Open("NUL in ascii8 text without stop")
            raise Fail(TE, "0.15 ruling 17: NUL in ascii7 text")
        if len(codes) > count:
            raise Fail(TE, "text longer than the field")
    return codes + [PAD[cs]] * (count - len(codes))


# ------------------------------------------------------------------------------
# a parser of the pack lines these packs use
# ------------------------------------------------------------------------------
def tokens_of(raw):
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c in " \t":
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = raw.index('"', i + 1)
            out.append(raw[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(raw) and raw[j] not in " \t":
                j += 1
            out.append(raw[i:j])
            i = j
    return out


class N:
    def __init__(self, d, **kw):
        self.d = d
        self.body = None
        self.__dict__.update(kw)


def parse_pack(text):
    pack = {"wire": None, "layout": "fixed", "order": "lsb", "common": [], "kinds": [], "defaults": {}}
    stack = []

    def into():
        if stack:
            return stack[-1].body
        return pack["kinds"][-1]["lines"] if pack["kinds"] else pack["common"]

    for raw in text.splitlines():
        toks = tokens_of(raw)
        if not toks or toks[0] in ("format", "version", "distribution", "source", "uses", "word_bytes"):
            if toks and toks[0] == "word_bytes":
                assert toks[1] == "1"
            continue
        d, a = toks[0], toks[1:]
        if d == "wire":
            pack["wire"] = a[0]
        elif d == "layout":
            pack["layout"] = a[0]
        elif d == "bit_order":
            pack["order"] = a[0]
        elif d == "encoding":
            pack["encoding"] = a[0]
        elif d == "end":
            stack.pop()
        elif d == "kind":
            pack["kinds"].append({"name": a[0], "requires": [], "lines": []})
        elif d == "requires":
            pack["kinds"][-1]["requires"] += a
        elif d == "default":
            pack["defaults"][a[0]] = a[1]
        else:
            x = N(d, args=a)
            if d == "field":
                x.key, x.loc = a[0], a[1]
                name, _, arg = a[2].partition(":")
                x.tr, x.cs = name, arg or None
                x.swap, x.absent, x.stop, x.until = False, None, None, None
                x.with_, x.lb = None, None
                i = 3
                while i < len(a):
                    if a[i] == "swap":
                        x.swap = True
                    elif a[i] == "absent":
                        x.absent = [int(v) for v in a[i + 1].split(",")]
                        i += 1
                    elif a[i] == "stop":
                        x.stop = int(a[i + 1])
                        i += 1
                    elif a[i] == "with":
                        x.with_ = a[i + 1]
                        i += 1
                    else:
                        raise ValueError(a[i])
                    i += 1
                if pack["wire"] == "bits":
                    if a[1].startswith("until:"):
                        x.until, x.n = int(a[1][6:]), None
                    elif a[1].startswith("int:"):
                        # 0.19: a constrained whole number in lb..ub, the
                        # fewest bits that hold ub - lb
                        assert pack.get("encoding") == "uper"
                        lb, ub = (int(t) for t in a[1][4:].split(":"))
                        x.lb, x.ub, x.n = lb, ub, (ub - lb).bit_length()
                    elif pack["layout"] == "sequential":
                        x.n = int(a[1])
                    else:
                        w, p, n = (int(t) for t in a[1].split(":"))
                        x.start, x.n = w * 8 + p, n
            elif d in ("when", "const"):
                x.n, x.value = int(a[0]), int(a[1])
            elif d == "pad":
                x.n = int(a[0])
            elif d == "presence":
                x.name, x.size = a[0], int(a[1])
            elif d == "if":
                x.conds = [(c.split(".")[0], int(c.split(".")[1])) for c in a]
            elif d == "count":
                x.name, x.n = a[0], int(a[1])
            elif d == "length":
                assert len(a) == 1
                x.n = int(a[0])
            elif d == "group":
                x.key = a[0]
                if pack["wire"] == "bits":
                    x.mode = a[1]
                    if a[1] == "count" and a[2].startswith("@"):
                        x.mode, x.ref = "ref", a[2][1:]
                    elif a[1] == "count":
                        x.n = int(a[2])
                else:
                    x.loc = a[1]
            into().append(x)
            if d in ("if", "group", "length"):
                x.body = []
                stack.append(x)
    return pack


# ------------------------------------------------------------------------------
# the model
# ------------------------------------------------------------------------------
KEY_TYPES = {}


def entity():
    return {"keys": {}, "lists": {}, "kind": None}


def text_of(v):
    if isinstance(v, float):
        return json_number(v)
    return str(v)


def model_of(ent, prefix=""):
    m = {prefix + k: text_of(v) for k, v in ent["keys"].items()}
    if ent.get("kind"):
        m[prefix + "@kind"] = ent["kind"][1]
    for name, items in ent["lists"].items():
        m[prefix + name + ".#"] = str(len(items))
        for i, item in enumerate(items):
            m.update(model_of(item, "%s%s[%d]." % (prefix, name, i)))
    return m


def json_number(x):
    """Ruling 3 of 0.1.1 for the values used here: no exponent, `1.0` is `1`."""
    if x == int(x):
        return str(int(x))
    t = repr(x)
    assert "e" not in t
    return t


# ------------------------------------------------------------------------------
# transforms of a field's bits (in reading order, after swap)
# ------------------------------------------------------------------------------
def tdec(x, bits, order):
    n, tr = len(bits), x.tr
    if tr == "uint":
        return value(bits, order)
    if tr == "twos":
        v = value(bits, order)
        return v - (1 << n) if v >> (n - 1) else v
    if tr == "smag":
        # 0.15: the most significant bit of the value as uint reads it is the sign
        v = value(bits, order)
        mag = v & ((1 << (n - 1)) - 1)
        return -mag if v >> (n - 1) else mag
    if tr == "f32":
        f = struct.unpack(">f", value(bits, order).to_bytes(4, "big"))[0]
        if math.isnan(f) or f in (float("inf"), float("-inf")):
            raise Fail(TD, "not finite")
        return f
    if tr == "ascii":
        raw = bytes(value(bits[i:i + 8], order) for i in range(0, n, 8)).rstrip(b"\0")
        if any(not 0x20 <= c <= 0x7e for c in raw):
            raise Fail(TD, "ascii byte outside 0x20-0x7e")
        return raw.decode("ascii")
    if tr == "hex":
        # 0.22: digit k is the 4-bit field at bit 4k, read as uint reads it
        return "".join("%x" % value(bits[i:i + 4], order) for i in range(0, n, 4))
    if tr == "chars":
        w = WIDTH[x.cs]
        return chars_decode(x.cs, [value(bits[i:i + w], order) for i in range(0, n, w)], x.stop)
    raise ValueError(tr)


def tenc(x, v, n, order):
    tr = x.tr
    if tr == "uint":
        return place(v & ((1 << n) - 1), n, order)
    if tr == "twos":
        return place(v & ((1 << n) - 1), n, order)
    if tr == "smag":
        if abs(v) >= 1 << (n - 1):
            raise Fail(TE, "magnitude")
        return place(((1 << (n - 1)) if v < 0 else 0) | abs(v), n, order)
    if tr == "f32":
        return place(int.from_bytes(struct.pack(">f", v), "big"), 32, order)
    if tr == "ascii":
        raw = v.encode("utf-8")
        if len(raw) > n // 8 or any(not 0x20 <= c <= 0x7e for c in raw):
            raise Fail(TE, "ascii text")
        raw += b"\0" * (n // 8 - len(raw))
        return [b for c in raw for b in place(c, 8, order)]
    if tr == "hex":
        if len(v) != n // 4 or any(c not in "0123456789abcdefABCDEF" for c in v):
            raise Fail(TE, "hex text of another length or not hex digits")
        return [b for c in v for b in place(int(c, 16), 4, order)]
    if tr == "chars":
        w = WIDTH[x.cs]
        return [b for c in chars_encode(x.cs, v, n // w, x.stop) for b in place(c, w, order)]
    raise ValueError(tr)


def until_encode(x, v, order):
    """0.22: the characters, then the terminator; an absent key the terminator alone."""
    w = WIDTH[x.cs]
    codes = [] if v is None else [code_of(x.cs, ch) for ch in v]
    if x.until in codes or len(codes) > 2040 // w:
        raise Fail(TE, "until: the text holds the terminator, or is longer than 2040 / w")
    return [b for c in codes + [x.until] for b in place(c, w, order)]


def typed(x, raw, pack):
    """A `default` value read as the key's type."""
    return raw if KEY_TYPES[x.key] == "string" else int(raw)


# ------------------------------------------------------------------------------
# fixed layouts (0.2, 0.5), word_bytes 1
# ------------------------------------------------------------------------------
def fixed_decode(pack, hx):
    order, ent, failed = pack["order"], entity(), []
    bits = stream(hx, order)
    need = -(-max(x.start + x.n for x in pack["common"]) // 8) * 8
    if len(bits) < need:
        raise Fail(MW, "input shorter than the message")
    for x in pack["common"]:
        b = bits[x.start:x.start + x.n]
        if x.swap:
            b = swapped(b)
        if x.absent and value(b, order) in x.absent:
            continue                    # 0.9: the raw value is a sentinel
        try:
            ent["keys"].setdefault(x.key, tdec(x, b, order))
        except Fail as e:
            failed.append(e)
    if failed:
        raise failed[0]
    return ent


def fixed_encode(pack, ent):
    order = pack["order"]
    need = -(-max(x.start + x.n for x in pack["common"]) // 8) * 8
    out, written = [0] * need, set()
    for x in pack["common"]:
        v = ent["keys"].get(x.key)
        if v is None and x.key in pack["defaults"]:
            v = typed(x, pack["defaults"][x.key], pack)
        if v is not None:
            b = tenc(x, v, x.n, order)
        elif x.absent:
            b = place(x.absent[0], x.n, order)
        else:
            continue                    # an absent key writes zero bits
        if x.swap:
            b = swapped(b)
        for k, bit in enumerate(b):
            if x.start + k not in written:
                out[x.start + k] = bit
                written.add(x.start + k)
    return unstream(out, order)


# ------------------------------------------------------------------------------
# sequential layouts (0.8, 0.21, 0.22)
# ------------------------------------------------------------------------------
class Dec:
    def __init__(self, pack, hx):
        self.pack, self.order = pack, pack["order"]
        self.bits = stream(hx, self.order)
        self.at = 0
        self.ext = [(len(self.bits), False)]       # (end, a length extent)
        self.failed = []

    def take(self, n):
        if self.at + n > self.ext[-1][0]:
            raise Fail(MW, "a line runs past the end at bit %d" % self.at)
        self.at += n
        return self.bits[self.at - n:self.at]

    def at_end(self):
        end, length = self.ext[-1]
        return length and self.at >= end

    def until(self, x):
        """Rulings 5 and 8: the terminator is found from the codes alone; at
        most floor(2040 / w) codes before it; then the characters decode."""
        w, codes = WIDTH[x.cs], []
        while True:
            c = value(self.take(w), self.order)
            if c == x.until:
                break
            codes.append(c)
            if len(codes) > 2040 // w:
                raise Fail(MW, "more than 2040 bits of characters")
        # ruling 6: the ascii7 NUL rules do not apply; ruling 7: nothing removed
        return "".join(char_of(x.cs, c) for c in codes)

    def scope(self, common, kinds, sc):
        pres = {}
        self.lines(common, sc, pres)
        if kinds:
            start = self.at
            for kind in kinds:
                self.at = start
                whens = [w for w in kind["lines"] if w.d == "when"]
                if all(value(self.take(w.n), self.order) == w.value for w in whens):
                    sc["kind"] = (self.pack["name"], kind["name"])
                    self.lines([x for x in kind["lines"] if x.d != "when"], sc, pres)
                    return
            raise Fail("no-kind", "no kind holds")

    def lines(self, nodes, sc, pres):
        pres, counts = dict(pres), {}
        for x in nodes:
            d = x.d
            if d == "field":
                if self.at_end():
                    continue                # ruling 4: absent
                try:
                    if x.until is not None:
                        v = self.until(x)
                    else:
                        b = self.take(x.n)
                        v = tdec(x, swapped(b) if x.swap else b, self.order)
                        if x.lb is not None:
                            assert x.tr == "uint" and self.order == "msb"
                            v += x.lb
                    sc["keys"].setdefault(x.key, v)
                except Fail as e:
                    if e.kind == MW:
                        raise
                    self.failed.append(e)   # ruling 5: the cursor is after the terminator
            elif d == "const":
                if not self.at_end():
                    self.take(x.n)
            elif d == "pad":
                if not self.at_end():
                    self.take(x.n)
            elif d == "presence":
                # ruling 2: presence bits keep their reading-order numbering
                b = [0] * x.size if self.at_end() else self.take(x.size)
                pres[x.name] = {k + 1 for k in range(x.size) if b[k]}
            elif d == "if":
                if all(bit in pres[name] for name, bit in x.conds):
                    self.lines(x.body, sc, pres)
            elif d == "count":
                counts[x.name] = value(self.take(x.n), self.order)
            elif d == "length":
                if self.at_end():
                    continue
                v = value(self.take(x.n), self.order)
                end = self.at + 8 * v
                if end > self.ext[-1][0]:
                    raise Fail(MW, "the extent runs past its end")
                self.ext.append((end, True))
                self.lines(x.body, sc, pres)
                self.ext.pop()
                self.at = end
            elif d == "group":
                items = []
                if x.mode == "rest":
                    while self.ext[-1][0] - self.at >= 8:
                        item = entity()
                        self.lines(x.body, item, pres)
                        items.append(item)
                else:
                    n = counts[x.ref] if x.mode == "ref" else value(self.take(x.n), self.order)
                    if n > self.ext[-1][0] - self.at:
                        raise Fail(MW, "count above the bits left")
                    for _ in range(n):
                        item = entity()
                        self.lines(x.body, item, pres)
                        items.append(item)
                sc["lists"][x.key] = items
            else:
                raise ValueError(d)


class Enc:
    def __init__(self, pack):
        self.pack, self.order = pack, pack["order"]
        self.out, self.starts = [], []

    def val(self, x, sc):
        if x.d == "field" and x.with_ is not None and not (
                x.with_ in sc["keys"] or sc["lists"].get(x.with_)):
            return None     # 0.18 ruling 1: suppressed, neither its value nor a default
        v = sc["keys"].get(x.key)
        if v is None and x.key in self.pack["defaults"]:
            v = typed(x, self.pack["defaults"][x.key], self.pack)    # ruling 10
        return v

    def content(self, nodes, sc):
        for x in nodes:
            if x.d == "field" and self.val(x, sc) is not None:
                return True
            if x.d == "group" and sc["lists"].get(x.key):
                return True
            if x.d in ("if", "length") and self.content(x.body, sc):
                return True
        return False

    def lines(self, nodes, sc, pres):
        pres, live = dict(pres), {}
        for i, x in enumerate(nodes):
            d = x.d
            if d == "field":
                v = self.val(x, sc)
                if x.until is not None:
                    # ruling 25: suppressed, the terminator alone (v is None)
                    self.out += until_encode(x, v, self.order)
                elif x.lb is not None:
                    # 0.19: v - lb in n bits; ruling 1 of 0.19: absent writes lb
                    v = x.lb if v is None else v
                    if not x.lb <= v <= x.ub:
                        raise Fail(TE, "outside the constraint")
                    self.out += place(v - x.lb, x.n, self.order)
                elif v is not None:
                    b = tenc(x, v, x.n, self.order)
                    self.out += swapped(b) if x.swap else b
                elif x.absent:
                    self.out += place(x.absent[0], x.n, self.order)
                else:
                    self.out += [0] * x.n
            elif d in ("const", "when"):
                self.out += place(x.value, x.n, self.order)
            elif d == "pad":
                self.out += [0] * x.n
            elif d == "presence":
                on = set()
                for y in nodes[i + 1:]:
                    if y.d == "if" and self.content(y.body, sc):
                        on.update(bit for name, bit in y.conds if name == x.name)
                self.out += [1 if k + 1 in on else 0 for k in range(x.size)]
                pres[x.name] = on
            elif d == "if":
                if all(bit in pres[name] for name, bit in x.conds):
                    self.lines(x.body, sc, pres)
            elif d == "count":
                live[x.name] = (x, len(self.out))
                self.out += [0] * x.n
            elif d == "length":
                outer, outer_starts = self.out, self.starts
                self.out, self.starts = [], []
                self.lines(x.body, sc, pres)
                self.out += [0] * (-len(self.out) % 8)
                block = self.out
                self.out, self.starts = outer, outer_starts
                self.out += place(len(block) // 8, x.n, self.order) + block
            elif d == "group":
                items = sc["lists"].get(x.key) or []
                if x.mode == "rest":
                    for item in items:
                        self.starts.append(len(self.out))
                        self.lines(x.body, item, pres)
                elif x.mode == "ref":
                    node, at = live[x.ref]
                    self.out[at:at + node.n] = place(len(items), node.n, self.order)
                    for item in items:
                        self.lines(x.body, item, pres)
                else:
                    self.out += place(len(items), x.n, self.order)
                    for item in items:
                        self.lines(x.body, item, pres)
            else:
                raise ValueError(d)


def choose_kind(kinds, ent, fmt):
    if ent.get("kind") and ent["kind"][0] == fmt:
        return next(k for k in kinds if k["name"] == ent["kind"][1])
    for k in kinds:
        if all(t in ent["keys"] for t in k["requires"]):
            return k
    raise Fail("no-kind", "no kind qualifies")


def seq_decode(pack, hx):
    dec = Dec(pack, hx)
    ent = entity()
    dec.scope(pack["common"], pack["kinds"], ent)
    if dec.failed:
        raise dec.failed[0]
    return ent


def seq_encode(pack, ent):
    enc = Enc(pack)
    lines = list(pack["common"])
    if pack["kinds"]:
        lines += choose_kind(pack["kinds"], ent, pack["name"])["lines"]
    enc.lines(lines, ent, {})
    end = len(enc.out) + (-len(enc.out) % 8)
    for s in enc.starts:            # 0.21 ruling 4, at message level
        if end - s < 8:
            raise Fail(TE, "a rest item starts %d bits before the end" % (end - s))
    return unstream(enc.out, enc.order)


# ------------------------------------------------------------------------------
# json: members of the pack's lines, groups of objects or scalars
# ------------------------------------------------------------------------------
def json_read(x, v):
    if x.tr == "string":
        if not isinstance(v, str):
            raise Fail(TD, "not a string")
        return v
    if x.tr == "int":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
            raise Fail(TD, "not an integer")
        return int(v)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Fail(TD, "not a number")
    return float(v)


def json_scope(lines, obj, sc):
    for x in lines:
        if x.d == "field":
            v = obj if x.loc == "." else obj.get(x.loc) if isinstance(obj, dict) else None
            if v is not None:
                sc["keys"].setdefault(x.key, json_read(x, v))
        elif x.d == "group" and isinstance(obj, dict) and isinstance(obj.get(x.loc), list):
            items = []
            for el in obj[x.loc]:
                item = entity()
                json_scope(x.body, el, item)
                items.append(item)
            sc["lists"][x.key] = items


def json_value(x, v):
    if x.tr == "float":
        return json_number(v)
    assert isinstance(v, int) if x.tr == "int" else isinstance(v, str)
    return json.dumps(v, ensure_ascii=False)


def json_object(lines, sc):
    if len(lines) == 1 and lines[0].d == "field" and lines[0].loc == ".":
        x = lines[0]
        return json_value(x, sc["keys"][x.key]) if x.key in sc["keys"] else "null"
    members = []
    for x in lines:
        if x.d == "field" and x.key in sc["keys"]:
            members.append('"%s":%s' % (x.loc, json_value(x, sc["keys"][x.key])))
        elif x.d == "group" and x.key in sc["lists"]:
            members.append('"%s":[%s]' % (x.loc, ",".join(json_object(x.body, it) for it in sc["lists"][x.key])))
    return "{" + ",".join(members) + "}"


def decode(pack, inp):
    if pack["wire"] == "json":
        ent = entity()
        json_scope(pack["common"], json.loads(inp), ent)
        return ent
    return seq_decode(pack, inp) if pack["layout"] == "sequential" else fixed_decode(pack, inp)


def encode(pack, ent):
    if pack["wire"] == "json":
        return json_object(pack["common"], ent)
    return seq_encode(pack, ent) if pack["layout"] == "sequential" else fixed_encode(pack, ent)


SOURCE = "constructed"


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written, counters, packs = {}, {}, {}
    for raw in sink.read("model/probe.def").splitlines():
        toks = tokens_of(raw)
        if toks and toks[0] in ("key", "list"):
            KEY_TYPES["probe." + toks[1]] = toks[2] if toks[0] == "key" else "list"

    def pack(name):
        if name not in packs:
            packs[name] = parse_pack(sink.read("packs/%s/pack.def" % name))
            packs[name]["name"] = name
        return packs[name]

    def emit(owner, d):
        counters[owner] = counters.get(owner, 0) + 1
        sink.write("packs/%s/vectors/%02d-%s.json" % (owner, counters[owner], d["name"]),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[owner] = written.get(owner, 0) + 1

    def vec(owner, name, frm, to, inp, expect=None, error=None, model=None, ref=""):
        """`owner`, `frm`, `to`: pack names without `conformance-long-`. The
        second computation runs and must agree with the paper value."""
        owner, frm, to = PREFIX + owner, PREFIX + frm, PREFIX + to
        try:
            ent = decode(pack(frm), inp)
        except Fail as e:
            assert error == e.kind, (name, e.kind, e.why)
            assert not model, name
            ent = None
        if ent is not None:
            # 0.5: convert clears Entity.kind unless from == to. No context; no
            # derive line of probe sets a key these packs map (checked below).
            enc = dict(ent, kind=ent["kind"] if frm == to else None)
            got = failed = None
            try:
                got = encode(pack(to), enc)
            except Fail as e:
                failed = e
            if error:
                assert failed is not None and failed.kind == error, (name, failed, got)
            else:
                assert failed is None, (name, failed and failed.why)
                assert got == expect, (name, expect, got)
        if model:
            have = model_of(ent)
            for k, v in model.items():
                if k == "@absent":
                    for gone in v:
                        assert gone not in have, (name, gone, have)
                else:
                    assert have.get(k) == v, (name, k, v, have.get(k))
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model:
            d["model"] = model
        d["source"] = SOURCE
        d["reference"] = ref
        emit(owner, d)

    # derivations run on every conversion between two formats; none of their
    # targets is a key these packs map
    derive_keys = set()
    for raw in sink.read("model/probe.def").splitlines():
        toks = tokens_of(raw)
        if toks and toks[0] == "derive":
            derive_keys.add(toks[1])
    for name in os.listdir(sink.path("packs")):
        if name.startswith(PREFIX):
            assert not derive_keys & set(sink.read("packs/%s/pack.def" % name).split()), name

    J = "json"
    LSB, MSB, MLSB = "lsb", "msb", "msb-lsb"
    H = "spec 0.22, Fields longer than 64 bits; "
    # ==========================================================================
    # conformance-long-hex-{lsb,msb,mlsb}: label 0:0:16 hex | tag 0:18:8 hex
    # ==========================================================================
    # Input 01 02 12 34 in each order.
    # lsb (positions are bit i mod 8 of each byte, values low bit first):
    #   label: digit 0 = bits 0..3 = low nibble of 01 = 1; digit 1 = high
    #   nibble 0; digit 2 = low nibble of 02 = 2; digit 3 = 0: "1020".
    #   tag: bits 18..21 are bits 2..5 of 12 (00010010: bit1, bit4 set) =
    #   0,0,1,0 -> 4; bits 22..25 are bits 6,7 of 12 and bits 0,1 of 34
    #   (00110100) = 0,0,0,0 -> 0: "40".
    #   Encode writes only these bits: 01 02, digit 4 at bits 18..21 sets bit
    #   20 (bit 4 of byte 2): 10, then 00. Bit 1 of byte 2 and the bits of 34
    #   are mapped by no line and are zero.
    # msb (first bit most significant): label "0102". Reading order of 12 34:
    #   00010010 00110100; bits 18..21 = 0100 = 4, bits 22..25 = 10 00 = 8:
    #   "48". Encode: 0100 at 18..21, 1000 at 22..25: 00 0100 10 | 00 000000
    #   = 12 00.
    # msb-lsb (msb positions, first bit least significant): 01 = 00000001:
    #   digit 0 = 0000 = 0, digit 1 = 0001 read from bit 0 up = 8; 02 =
    #   00000010: digit 2 = 0, digit 3 = 0010 = 4: "0804". tag: bits 18..21
    #   = 0100 = 2, bits 22..25 = 1000 = 1: "21". Encode: 2 is 0100 and 1 is
    #   1000 in reading order, the same bits as under msb: 12 00.
    for nm, order, lab, tag, out in (("hex-lsb", LSB, "1020", "40", "01021000"),
                                     ("hex-msb", MSB, "0102", "48", "01021200"),
                                     ("hex-mlsb", MLSB, "0804", "21", "01021200")):
        vec(nm, "digits-of-0102-and-an-odd-offset", nm, J, "01021234", '{"label":"%s","tag":"%s"}' % (lab, tag),
            model={"probe.label": lab, "probe.tag": tag},
            ref=H + "digit k is the 4-bit field at bit 4k of the field, read as uint reads a 4-bit field there "
                    "in the pack's bit order (%s); under lsb and msb-lsb the digits are not the wire's hex" % order)
        vec(nm, "round-trip-keeps-the-mapped-bits", nm, nm, "01021234", out,
            ref=H + "hex keeps bits through a round trip; bits no line maps are written zero (0.2)")
    # json -> bits: "ABCD" (either case) and tag "5e".
    # lsb: digit a at bits 0..3 (low nibble), b at 4..7: byte ba; c, d: dc.
    #   tag: 5 = 0101 at 18..21 -> bits 2..5 of byte 2 = 1,0,1,0; e = 1110 at
    #   22..25 -> bits 6,7 of byte 2 = 0,1 and bits 0,1 of byte 3 = 1,1.
    #   byte 2 bits 0..7 = 0,0,1,0,1,0,0,1 = 94; byte 3 = 1,1,0,0,0,0,0,0 = 03.
    # msb: ab cd; tag 0101 at 18..21, 1110 at 22..25: 00 0101 11 | 10 000000
    #   = 17 80.
    # msb-lsb: a = 1010 written from bit 0 up is 0101, b = 1101: 0101 1101 =
    #   5d; c = 0011, d = 1011: 3b. tag: 5 -> 1010, e -> 0111: 00 1010 01 |
    #   11 000000 = 29 c0.
    for nm, out in (("hex-lsb", "badc9403"), ("hex-msb", "abcd1780"), ("hex-mlsb", "5d3b29c0")):
        vec(J, "to-%s-upper-case-digits" % nm, J, nm, '{"label":"ABCD","tag":"5e"}', out,
            ref=H + "encode writes each digit (either case) as uint writes a 4-bit field at its place")
    vec("hex-msb", "to-json-leading-zeros-kept", "hex-msb", J, "00ff0000", '{"label":"00ff","tag":"00"}',
        ref="spec 0.22 ruling 14: on json hex is a string of len / 4 digits, leading zeros kept")
    vec(J, "to-hex-msb-and-back-lower-case", J, "hex-msb", '{"label":"ABCD"}', "abcd0000",
        ref="spec 0.22 ruling 14: packs write lowercase; the model text ABCD is the bits abcd")
    vec("hex-msb", "abcd-to-json-lower-case", "hex-msb", J, "abcd0000", '{"label":"abcd","tag":"00"}',
        ref="spec 0.22 ruling 14: decode writes lowercase digits")
    vec(J, "to-hex-msb-three-digits", J, "hex-msb", '{"label":"abc"}', error=TE,
        ref=H + "text of another length is transform-encode")
    vec(J, "to-hex-msb-five-digits", J, "hex-msb", '{"label":"abcde"}', error=TE,
        ref=H + "text of another length is transform-encode")
    vec(J, "to-hex-msb-not-a-hex-digit", J, "hex-msb", '{"label":"abcg"}', error=TE,
        ref=H + "a character that is not a hex digit is transform-encode")
    vec(J, "to-hex-msb-a-sign", J, "hex-msb", '{"label":"-abc"}', error=TE,
        ref=H + "a character that is not a hex digit is transform-encode")

    # ==========================================================================
    # conformance-long-hex-wide: x 0:0:8 uint | label 0:8:72 hex (msb)
    # ==========================================================================
    W = "spec 0.22 ruling 1 and Fields longer than 64 bits; "
    vec("hex-wide", "round-trip-72-bits", "hex-wide", "hex-wide", "070123456789abcdef01", "070123456789abcdef01",
        model={"probe.x": "7", "probe.label": "0123456789abcdef01"},
        ref=W + "a field of 72 bits maps its bits: 18 digits, each 4 bits in msb order, kept through a round trip")
    vec("hex-wide", "to-json", "hex-wide", J, "07fedcba9876543210ff", '{"label":"fedcba9876543210ff","x":7}',
        ref=W + "json writes the members in the json pack's line order: label, then x")
    vec(J, "to-hex-wide", J, "hex-wide", '{"x":7,"label":"0123456789ABCDEF01"}', "070123456789abcdef01",
        ref=W + "either case encodes")
    vec(J, "to-hex-wide-absent-writes-zero-bits", J, "hex-wide", '{"x":7}', "07000000000000000000",
        ref=W + "an absent key writes zero bits (0.2: bits covered by no written field are zero)")

    # ==========================================================================
    # conformance-long-hex-max: label 0:0:2040 hex (msb)
    # ==========================================================================
    big = "".join("%02x" % i for i in range(255))       # bytes 00 01 ... fe
    vec("hex-max", "round-trip-2040-bits", "hex-max", "hex-max", big, big, model={"probe.label": big},
        ref=H + "len is a multiple of 4 from 4 to 2040: 510 digits, msb, the wire's hex")
    vec(J, "to-hex-max-509-digits", J, "hex-max", json.dumps({"label": big[:-1]}), error=TE,
        ref=H + "text of another length is transform-encode")

    # ==========================================================================
    # conformance-long-hex-absent: label 0:0:8 hex absent 15 (lsb)
    # ==========================================================================
    A = "spec 0.22: on a shorter one the sentinel is the field's uint raw value, not its hex text; "
    # wire 0f: lsb raw value 15 -> absent. Its hex text would be digit 0 = low
    # nibble f, digit 1 = 0: "f0".
    vec("hex-absent", "raw-value-15-is-absent", "hex-absent", J, "0f", "{}", model={"@absent": ["probe.label"]},
        ref=A + "wire 0f is the raw value 15")
    vec("hex-absent", "round-trip-absent-writes-the-sentinel", "hex-absent", "hex-absent", "0f", "0f",
        ref=A + "an absent key writes its first sentinel (0.9)")
    # wire f0: raw value 240; digit 0 = low nibble 0, digit 1 = high nibble f: "0f"
    vec("hex-absent", "raw-value-240-is-the-text-0f", "hex-absent", J, "f0", '{"label":"0f"}',
        model={"probe.label": "0f"}, ref=A + "the text 0f is not the sentinel; the raw value 240 is not 15")
    # text "f0": digit f at bits 0..3 (low nibble), 0 at 4..7: byte 0f
    vec(J, "to-hex-absent-text-f0-writes-the-sentinel-bits", J, "hex-absent", '{"label":"f0"}', "0f",
        ref=A + "a present value is written as before, even when the result equals a sentinel (0.9)")
    vec(J, "to-hex-absent-absent-key", J, "hex-absent", "{}", "0f", ref=A + "the sentinel 15 under lsb is 0f")

    # ==========================================================================
    # conformance-long-hex-seq: label 12 hex (sequential, msb)
    # ==========================================================================
    Q = "spec 0.22: hex is valid in fixed and sequential layouts; "
    vec("hex-seq", "three-digits", "hex-seq", J, "abc0", '{"label":"abc"}', model={"probe.label": "abc"},
        ref=Q + "12 bits are three digits; the last 4 bits of the byte are ignored (0.8)")
    vec("hex-seq", "round-trip", "hex-seq", "hex-seq", "abc0", "abc0", ref=Q + "12 bits, then 4 zero bits")
    vec("hex-seq", "padding-not-kept", "hex-seq", "hex-seq", "abcf", "abc0",
        ref=Q + "the bits after the last line are ignored and written as zero (0.8)")
    vec(J, "to-hex-seq", J, "hex-seq", '{"label":"ABC"}', "abc0", ref=Q + "either case")
    vec(J, "to-hex-seq-two-digits", J, "hex-seq", '{"label":"ab"}', error=TE,
        ref=Q + "text of another length is transform-encode")

    # ==========================================================================
    # conformance-long-hex-seq-mlsb: x 3 uint | label 8 hex (sequential, msb-lsb)
    # ==========================================================================
    # x = 5 from bit 0 up: 1,0,1. label "a3": a = 1010 from bit 0 up: 0,1,0,1;
    # 3 = 0011: 1,1,0,0. 101 0101 1100 00000 = 10101011 10000000 = ab 80
    vec("hex-seq-mlsb", "digits-at-bit-3", "hex-seq-mlsb", J, B(MLSB, "101 0101 1100 00000"),
        '{"label":"a3","x":5}', model={"probe.x": "5", "probe.label": "a3"},
        ref=Q + "under msb-lsb each digit is read as uint reads 4 bits at bit 3 + 4k, from its first bit up")
    vec("hex-seq-mlsb", "round-trip", "hex-seq-mlsb", "hex-seq-mlsb", "ab80", "ab80", ref=Q + "the same bits")
    vec(J, "to-hex-seq-mlsb", J, "hex-seq-mlsb", '{"x":5,"label":"A3"}', "ab80", ref=Q + "either case")

    # ==========================================================================
    # conformance-long-until-icao6: label until:0 chars:icao6 | y 8 uint
    # ==========================================================================
    U = "spec 0.22, Character fields that end at a code; "
    # A = 1, B = 2, terminator 0, y = 9:
    # 000001 000010 000000 00001001 000000 = 04 20 02 40
    ab = B(MSB, "000001 000010 000000 00001001 000000")
    vec("until-icao6", "two-characters-then-the-terminator", "until-icao6", "until-icao6", ab, "04200240",
        model={"probe.label": "AB", "probe.y": "9"},
        ref=U + "characters are read until the code 0; the terminator is consumed and is not part of the text")
    vec("until-icao6", "to-json", "until-icao6", J, "04200240", '{"label":"AB","y":9}', ref=U + "the text before it")
    # 000000 00001001 00 = 00 24
    vec("until-icao6", "ruling-11-immediate-terminator-is-empty", "until-icao6", J, B(MSB, "000000 00001001 00"),
        '{"label":"","y":9}', model={"probe.label": "", "probe.y": "9"},
        ref="spec 0.22 ruling 11: an immediate terminator decodes as \"\", present")
    vec(J, "to-until-icao6-absent-writes-the-terminator", J, "until-icao6", '{"y":9}', "0024",
        ref=U + "an absent key writes the terminator alone; ruling 11: it comes back as \"\"")
    vec(J, "to-until-icao6-empty-text", J, "until-icao6", '{"label":"","y":9}', "0024",
        ref=U + "the empty text writes the terminator alone")
    # A = 1, space = 32: 000001 100000 000000 00001001 000000 = 06 00 02 40
    vec("until-icao6", "ruling-07-trailing-space-kept", "until-icao6", J, B(MSB, "000001 100000 000000 00001001 000000"),
        '{"label":"A ","y":9}', model={"probe.label": "A "},
        ref="spec 0.22 ruling 7: nothing is removed under until:, neither padding nor trailing spaces")
    # fc = 111111 00: code 63, then 6 bits are needed and 2 remain
    vec("until-icao6", "ruling-05-missing-terminator-wins", "until-icao6", "until-icao6", "fc", error=MW,
        ref="spec 0.22 ruling 5: the terminator is found first, from the codes alone; none is malformed-wire, "
            "and that wins over the code 63, which icao6 gives no character")
    # 27 = 011011, a code icao6 gives no character, then 0, then y = 9:
    # 011011 000000 00001001 0000 = 6c 00 90
    vec("until-icao6", "ruling-05-bad-character-before-the-terminator", "until-icao6", "until-icao6",
        B(MSB, "011011 000000 00001001 0000"), error=TD,
        ref="spec 0.22 ruling 5: a bad character is transform-decode and the cursor resumes after the terminator, "
            "so y still decodes and the input is not malformed")
    vec(J, "to-until-icao6-character-the-set-cannot-hold", J, "until-icao6", '{"label":"A@","y":9}', error=TE,
        ref=U + "a character the set cannot hold is transform-encode")

    # ==========================================================================
    # conformance-long-until-ais6: label until:63 chars:ais6
    # ==========================================================================
    # A = 1, B = 2, space = 32, terminator 63: 000001 000010 100000 111111 = 04 28 3f
    vec("until-ais6", "trailing-space-kept", "until-ais6", "until-ais6", B(MSB, "000001 000010 100000 111111"),
        "04283f", model={"probe.label": "AB "},
        ref="spec 0.22 ruling 7: the trailing space is part of the text")
    vec("until-ais6", "to-json", "until-ais6", J, "04283f", '{"label":"AB "}', ref=U + "AB and a space")
    # A = 1, @ = 0, terminator: 000001 000000 111111 000000 = 04 0f c0
    vec("until-ais6", "ruling-07-padding-character-kept", "until-ais6", J, B(MSB, "000001 000000 111111 000000"),
        '{"label":"A@"}', model={"probe.label": "A@"},
        ref="spec 0.22 ruling 7: the padding @ is not removed (the field has no fixed length to pad)")
    vec(J, "to-until-ais6-text-holding-the-terminator", J, "until-ais6", '{"label":"A?"}', error=TE,
        ref=U + "a character whose code equals <code> (? is 63) is transform-encode")
    # 340 A: 4 codes 000001 are 24 bits, 04 10 41; 85 times, then 111111 00 = fc
    a340 = "041041" * 85 + "fc"
    assert a340 == B(MSB, "000001" * 340 + "111111")
    vec("until-ais6", "ruling-08-340-characters", "until-ais6", "until-ais6", a340, a340,
        model={"probe.label": "A" * 340},
        ref="spec 0.22 ruling 8: floor(2040 / 6) = 340 characters before the terminator are read")
    # 341 A: the 340 as above, then 000001 111111 0000 = 07 f0
    a341 = "041041" * 85 + "07f0"
    assert a341 == B(MSB, "000001" * 341 + "111111")
    vec("until-ais6", "ruling-08-341-characters", "until-ais6", "until-ais6", a341, error=MW,
        ref="spec 0.22: at most 2040 bits of characters are read before the terminator; more is malformed-wire")
    vec(J, "to-until-ais6-340-characters", J, "until-ais6", json.dumps({"label": "A" * 340}), a340,
        ref="spec 0.22 ruling 8: 340 characters, then the terminator")
    vec(J, "to-until-ais6-341-characters", J, "until-ais6", json.dumps({"label": "A" * 341}), error=TE,
        ref=U + "text longer than 2040 / w characters is transform-encode")

    # ==========================================================================
    # conformance-long-until-ascii7: label until:3 chars:ascii7
    # ==========================================================================
    # A = 1000001, NUL = 0000000, B = 1000010, 3 = 0000011, 0000:
    # 10000010 00000010 00010000 00110000 = 82 02 10 30
    vec("until-ascii7", "ruling-06-nul-inside-the-text", "until-ascii7", "until-ascii7",
        B(MSB, "1000001 0000000 1000010 0000011 0000"), "82021030", model={"probe.label": "A\u0000B"},
        ref="spec 0.22 ruling 6: the ascii7 NUL rules of 0.15 do not apply unless NUL is the terminator")
    vec("until-ascii7", "to-json-nul-escaped", "until-ascii7", J, "82021030", '{"label":"A\\u0000B"}',
        ref="spec 0.22 ruling 6, and 0.5 Canonical output: control characters as \\u00XX, lowercase hex")
    vec(J, "to-until-ascii7-nul-inside-the-text", J, "until-ascii7", '{"label":"A\\u0000B"}', "82021030",
        ref="spec 0.22 ruling 6: ruling 17 of 0.15 does not apply under until:3")
    # 291 A: 291 x 7 + 7 = 2044 bits, 256 bytes
    vec(J, "to-until-ascii7-291-characters", J, "until-ascii7", json.dumps({"label": "A" * 291}),
        B(MSB, "1000001" * 291 + "0000011"),
        ref="spec 0.22 ruling 8: floor(2040 / 7) = 291 characters")
    vec(J, "to-until-ascii7-292-characters", J, "until-ascii7", json.dumps({"label": "A" * 292}), error=TE,
        ref="spec 0.22 ruling 8: 292 characters are more than floor(2040 / 7)")

    # ==========================================================================
    # conformance-long-until-del: label until:127 chars:ascii7
    # ==========================================================================
    # A = 1000001, 127 = 1111111, 00: 10000011 11111100 = 83 fc
    vec("until-del", "ruling-09-terminator-without-a-character", "until-del", "until-del",
        B(MSB, "1000001 1111111 00"), "83fc", model={"probe.label": "A"},
        ref="spec 0.22 ruling 9: the terminator 127 is a code the set gives no character; it is compared first")
    # 1111111 0 = fe
    vec("until-del", "immediate-terminator", "until-del", J, "fe", '{"label":""}', model={"probe.label": ""},
        ref="spec 0.22 ruling 11")
    vec(J, "to-until-del", J, "until-del", '{"label":"A"}', "83fc", ref=U + "A, then 127")

    # ==========================================================================
    # conformance-long-until-ascii8: label until:0 ascii8 | tag until:0 ascii8 | default tag zz
    # ==========================================================================
    C8 = "spec 0.22: an 8-bit text that ends at NUL is until:0 chars:ascii8; "
    vec("until-ascii8", "two-c-strings", "until-ascii8", "until-ascii8", "4142004300", "4142004300",
        model={"probe.label": "AB", "probe.tag": "C"}, ref=C8 + "41 42 00, then 43 00")
    vec("until-ascii8", "to-json", "until-ascii8", J, "4142004300", '{"label":"AB","tag":"C"}', ref=C8 + "AB and C")
    vec(J, "to-until-ascii8-ruling-10-default", J, "until-ascii8", '{"label":"AB"}', "4142007a7a00",
        ref="spec 0.22 ruling 10: default applies to an absent key first (zz = 7a 7a, then NUL)")
    vec(J, "to-until-ascii8-absent-label", J, "until-ascii8", '{"tag":"C"}', "004300",
        ref=U + "an absent key with no default writes the terminator alone")
    vec(J, "to-until-ascii8-both-absent", J, "until-ascii8", "{}", "007a7a00",
        ref="spec 0.22 ruling 10: the terminator alone only when no default applies")
    vec("until-ascii8", "ruling-04-starts-at-the-end-of-the-input", "until-ascii8", "until-ascii8", "414200",
        error=MW, ref="spec 0.22 ruling 4: at message level, starting at the end of the input is malformed-wire")
    # 41, then ff (not a character of ascii8), then 00; tag: 00
    vec("until-ascii8", "ruling-05-bad-character", "until-ascii8", "until-ascii8", "41ff0000", error=TD,
        ref="spec 0.22, ascii8: every other code is transform-decode; ruling 5: tag still decodes")
    vec(J, "to-until-ascii8-text-holding-nul", J, "until-ascii8", '{"label":"A\\u0000"}', error=TE,
        ref=U + "a character whose code equals <code> is transform-encode")
    vec(J, "to-until-ascii8-character-the-set-cannot-hold", J, "until-ascii8", '{"label":"é"}', error=TE,
        ref=U + "a character the set cannot hold is transform-encode")

    # ==========================================================================
    # conformance-long-until-length: length 8 { x 8, label until:0 ascii8 } | y 8
    # ==========================================================================
    E = "spec 0.22 rulings 4 and 12; "
    # length 1: the block is byte 1 (x = 5); label starts at bit 16, the end
    vec("until-length", "ruling-04-starts-at-the-extent-end-absent", "until-length", J, "010509", '{"x":5,"y":9}',
        model={"probe.x": "5", "@absent": ["probe.label"], "probe.y": "9"},
        ref=E + "a field starting at or after the end of a length extent is absent (ruling 7 of 0.8)")
    # encode writes every line: x 05, the terminator 00; the block is 2 bytes
    vec("until-length", "ruling-11-absent-comes-back-as-a-terminator", "until-length", "until-length", "010509",
        "02050009", ref=E + "encode writes the terminator alone for the absent key; the length counts it")
    # length 3: block 05 41 00; y = 09
    vec("until-length", "terminator-inside-the-block", "until-length", "until-length", "0305410009", "0305410009",
        model={"probe.x": "5", "probe.label": "A", "probe.y": "9"}, ref=E + "the innermost length block is the extent")
    # length 2: block 05 41; the 00 after it lies outside the extent
    vec("until-length", "ruling-04-no-terminator-in-the-extent", "until-length", "until-length", "02054100",
        error=MW, ref=E + "one that starts before the end and finds no terminator is malformed-wire")

    # ==========================================================================
    # conformance-long-until-rest: names rest { tag until:0 chars:ascii7 }
    # ==========================================================================
    R = "spec 0.22 ruling 15, with 0.21 A list to the end of its extent; "
    # A = 1000001, 0000000, then 2 bits: 2 < 8, padding. 10000010 00000000
    vec("until-rest", "one-item", "until-rest", "until-rest", B(MSB, "1000001 0000000 00"), "8200",
        model={"probe.names.#": "1", "probe.names[0].probe.tag": "A"},
        ref=R + "after the item 2 bits remain: padding")
    # 82 00 00: after the first item 10 bits remain: a second item reads the
    # code 0 at once, "" (ruling 11); then 3 bits of padding
    vec("until-rest", "stray-nul-byte-is-an-empty-item", "until-rest", J, "820000", '{"names":["A",""]}',
        model={"probe.names.#": "2", "probe.names[0].probe.tag": "A", "probe.names[1].probe.tag": ""},
        ref=R + "10 bits remain after item 0, so item 1 is read: an immediate terminator, \"\" present")
    vec("until-rest", "stray-nul-byte-round-trip", "until-rest", "until-rest", "820000", "820000",
        ref=R + "A, NUL, NUL: 21 bits, padded to 24")
    # 7 bytes of zeros: items at bits 0, 7, ... 42 (14 bits left); at 49, 7 left
    vec("until-rest", "seven-empty-items-in-seven-bytes", "until-rest", "until-rest", "00000000000000",
        "00000000000000", model={"probe.names.#": "7", "probe.names[6].probe.tag": ""},
        ref=R + "an item is read while at least 8 bits remain: 7 items, then 7 bits of padding")
    # A, "", B: 1000001 0000000 | 0000000 | 1000010 0000000 | 00000
    vec(J, "to-until-rest-three-items", J, "until-rest", '{"names":["A","","B"]}',
        B(MSB, "1000001 0000000 0000000 1000010 0000000 00000"), ref=R + "the items back to back")
    vec(J, "to-until-rest-ruling-04-eight-empty-items", J, "until-rest", json.dumps({"names": [""] * 8}), error=TE,
        ref=R + "eight items of 7 bits: the last starts at bit 49 of 56, 7 bits before the end (0.21 ruling 4)")
    # 83 = 1000001 1: A, then the next code needs 7 bits and 1 remains
    vec("until-rest", "item-without-a-terminator", "until-rest", "until-rest", "83", error=MW,
        ref=R + "reading past the end of the enclosing extent before the terminator is malformed-wire")

    # ==========================================================================
    # conformance-long-stop: label 0:0:64 chars:ascii8 stop 0 (msb)
    # ==========================================================================
    P = "spec 0.22, the field option stop <code>; "
    vec("stop", "text-ends-at-nul-rest-ignored", "stop", J, "414200ff017a7a7a", '{"label":"AB"}',
        model={"probe.label": "AB"},
        ref=P + "decode yields the characters before the first NUL and ignores the rest of the field (ff included)")
    vec("stop", "round-trip-nul-padding", "stop", "stop", "414200ff017a7a7a", "4142000000000000",
        ref=P + "encode writes the text, the terminator, then padding (NUL) to the field's size")
    vec(J, "to-stop-seven-characters", J, "stop", '{"label":"ABCDEFG"}', "4142434445464700",
        ref=P + "7 characters leave room for the terminator")
    vec(J, "to-stop-eight-characters", J, "stop", '{"label":"ABCDEFGH"}', error=TE,
        ref=P + "a text that does not leave room for the terminator is transform-encode")
    vec(J, "to-stop-text-holding-the-terminator", J, "stop", '{"label":"A\\u0000B"}', error=TE,
        ref=P + "a text that holds the terminator's character is transform-encode")
    vec(J, "to-stop-empty-text", J, "stop", '{"label":""}', "0000000000000000",
        ref=P + "the terminator, then padding")
    vec("stop", "terminator-first-is-empty", "stop", J, "00ff000000000000", '{"label":""}', model={"probe.label": ""},
        ref=P + "no characters before the first NUL: the empty text, present")
    vec("stop", "bad-character-before-the-terminator", "stop", "stop", "41ff000000000000", error=TD,
        ref=P + "the characters before it are decoded; ff is not a character of ascii8 (transform-decode)")

    # ==========================================================================
    # conformance-long-stop-seq: label 24 chars:ais6 stop 0 | y 8 (sequential, msb)
    # ==========================================================================
    # A B @ @ = 000001 000010 000000 000000, y = 00001001: 04 20 00 09
    vec("stop-seq", "round-trip", "stop-seq", "stop-seq", B(MSB, "000001 000010 000000 000000 00001001"),
        "04200009", model={"probe.label": "AB", "probe.y": "9"},
        ref=P + "either layout: ais6 code 0 (@) ends the text")
    # A @ ? * = 000001 000000 111111 101010: the codes after the first @ are ignored
    vec("stop-seq", "rest-of-the-field-ignored", "stop-seq", "stop-seq",
        B(MSB, "000001 000000 111111 101010 00001001"), "04000009", model={"probe.label": "A", "probe.y": "9"},
        ref=P + "decode ignores the rest of the field; encode writes A, @, then @ padding")
    vec(J, "to-stop-seq-three-characters", J, "stop-seq", '{"label":"ABC","y":9}',
        B(MSB, "000001 000010 000011 000000 00001001"), ref=P + "3 characters and the terminator fill 24 bits")
    vec(J, "to-stop-seq-four-characters", J, "stop-seq", '{"label":"ABCD","y":9}', error=TE,
        ref=P + "4 characters leave no room for the terminator")
    vec(J, "to-stop-seq-text-holding-at", J, "stop-seq", '{"label":"A@","y":9}', error=TE,
        ref=P + "@ is the terminator's character")

    # stop: label 0:0:64 chars:ascii8 stop 0, filled with no NUL
    vec("stop", "ruling-19-no-terminator-decodes-as-without-stop", "stop", J, "4142434445464748",
        '{"label":"ABCDEFGH"}', model={"probe.label": "ABCDEFGH"},
        ref="spec 0.22 ruling 19: a stop field with no terminator decodes as the field without stop would")
    vec("stop", "ruling-19-no-terminator-does-not-re-encode", "stop", "stop", "4142434445464748", error=TE,
        ref="spec 0.22 ruling 19 and stop: 8 characters leave no room for the terminator on encode")

    # ==========================================================================
    # conformance-long-stop-icao6: label 0:0:36 chars:icao6 stop 0 (msb)
    # ==========================================================================
    # A B sp sp 0 sp = 000001 000010 100000 100000 000000 100000, then 4 bits
    # no line maps: 0000. 00000100 00101000 00100000 00000010 00000000 = 04 28 20 02 00
    sp = B(MSB, "000001 000010 100000 100000 000000 100000 0000")
    vec("stop-icao6", "ruling-18-spaces-before-the-terminator-kept", "stop-icao6", J, sp, '{"label":"AB  "}',
        model={"probe.label": "AB  "},
        ref="spec 0.22 ruling 18: decode yields exactly the characters before the terminator; the 0.15 removal "
            "of padding and spaces does not apply")
    vec("stop-icao6", "ruling-18-round-trip", "stop-icao6", "stop-icao6", sp, "0428200200",
        ref="spec 0.22 ruling 18: AB, two spaces, the code 0, then space padding")
    # A B sp sp sp sp: no code 0, so the 0.15 rules: trailing spaces removed
    nt = B(MSB, "000001 000010 100000 100000 100000 100000 0000")
    vec("stop-icao6", "ruling-19-no-terminator-trailing-spaces-removed", "stop-icao6", J, nt, '{"label":"AB"}',
        model={"probe.label": "AB"},
        ref="spec 0.22 ruling 19: with no code 0 the field decodes as without stop: icao6 removes trailing spaces")
    # re-encode "AB": A B 0 sp sp sp
    vec("stop-icao6", "ruling-19-re-encode-writes-the-terminator", "stop-icao6", "stop-icao6", nt,
        B(MSB, "000001 000010 000000 100000 100000 100000 0000"),
        ref="spec 0.22 ruling 19 and stop: encode writes the text, the terminator, then padding")
    vec(J, "to-stop-icao6-ruling-18-trailing-spaces", J, "stop-icao6", '{"label":"AB  "}', "0428200200",
        ref="spec 0.22 ruling 18: the text is written as it is, spaces included, then the code 0 and padding")

    # ==========================================================================
    # conformance-long-until-semicolon: label until:59 chars:ascii8
    # ==========================================================================
    N20 = "spec 0.22 ruling 20: NUL under until:N with N not 0 is an ordinary character on decode and on encode; "
    vec("until-semicolon", "ruling-20-nul-inside", "until-semicolon", "until-semicolon", "4100423b", "4100423b",
        model={"probe.label": "A\u0000B"}, ref=N20 + "41 00 42, then ; (3b)")
    vec("until-semicolon", "ruling-20-trailing-nul-kept", "until-semicolon", J, "41003b", '{"label":"A\\u0000"}',
        model={"probe.label": "A\u0000"}, ref=N20 + "and ruling 7: nothing is removed under until:")
    vec(J, "to-until-semicolon-ruling-20", J, "until-semicolon", '{"label":"A\\u0000B"}', "4100423b",
        ref=N20 + "0.15 ruling 17 does not apply")

    # ==========================================================================
    # conformance-long-stop-semicolon: label 0:0:48 chars:ascii8 stop 59
    # ==========================================================================
    N21 = "spec 0.22 ruling 21: with a terminator other than 0, NUL in a stop field is an ordinary character; "
    vec("stop-semicolon", "ruling-21-nul-before-the-terminator", "stop-semicolon", J, "4100423b0000",
        '{"label":"A\\u0000B"}', model={"probe.label": "A\u0000B"}, ref=N21 + "41 00 42, then ; and NUL padding")
    vec("stop-semicolon", "ruling-21-round-trip", "stop-semicolon", "stop-semicolon", "4100423b7a7a", "4100423b0000",
        ref=N21 + "the bytes after ; are ignored; encode pads with NUL")
    vec("stop-semicolon", "ruling-18-trailing-nul-kept", "stop-semicolon", J, "41003b000000", '{"label":"A\\u0000"}',
        model={"probe.label": "A\u0000"}, ref="spec 0.22 rulings 18 and 21: the NUL before ; is part of the text")
    vec(J, "to-stop-semicolon-ruling-21", J, "stop-semicolon", '{"label":"A\\u0000"}', "41003b000000",
        ref=N21 + "A, NUL, ;, then NUL padding")

    # ==========================================================================
    # msb-lsb
    # ==========================================================================
    O = "spec 0.22, A bit order with high-bit-first positions and low-bit-first values; "
    # mlsb-uint: x 0:0:4 | y 0:4:4 | z 0:8:8. 8f 01 = 1000 1111 | 00000001:
    # x = 1,0,0,0 from bit 0 up = 1; y = 15; z = bit 7 set = 128
    vec("mlsb-uint", "high-nibble-low-bit-first", "mlsb-uint", J, "8f01", '{"x":1,"y":15,"z":128}',
        model={"probe.x": "1", "probe.y": "15", "probe.z": "128"},
        ref=O + "0:0:4 is the high four bits of the first byte read with the highest of them as the value's bit 0")
    vec("mlsb-uint", "round-trip", "mlsb-uint", "mlsb-uint", "8f01", "8f01", ref=O + "the same bits")
    # x = 3: 1,1,0,0; y = 4: 0,0,1,0; z = 1: 1,0,0,0,0,0,0,0 -> 1100 0010 | 10000000
    vec(J, "to-mlsb-uint", J, "mlsb-uint", '{"x":3,"y":4,"z":1}', B(MLSB, "1100 0010 10000000"),
        ref=O + "each value written from its bit 0 at the field's first position")
    # mlsb-signed: z 0:0:8 twos | w 0:8:8 smag
    S3 = "spec 0.22 ruling 3: under msb-lsb the sign of twos and smag is the last bit read; "
    # 01: the last bit read is 1 -> value 128 -> twos -128. 81: bits 1 and 8
    # read -> value 129 -> sign 1, magnitude 1 -> -1
    vec("mlsb-signed", "last-bit-is-the-sign", "mlsb-signed", J, "0181", '{"z":-128,"w":-1}',
        model={"probe.z": "-128", "probe.w": "-1"}, ref=S3 + "01 is -128 in twos; 81 is -1 in smag")
    vec("mlsb-signed", "first-bit-is-one", "mlsb-signed", J, "8080", '{"z":1,"w":1}',
        model={"probe.z": "1", "probe.w": "1"}, ref=S3 + "80 is the value 1")
    # 01 in smag: value 128 = sign 1, magnitude 0 -> 0; encode 0 with sign 0
    vec("mlsb-signed", "negative-zero-smag", "mlsb-signed", "mlsb-signed", "0001", "0000",
        model={"probe.z": "0", "probe.w": "0"},
        ref=S3 + "sign 1 with magnitude 0 decodes as 0; 0 encodes with sign 0 (0.15)")
    # z = -1: 255 = ff. w = -2: sign 1, magnitude 2 = value 130 = bits 1 and 7:
    # from bit 0 up 0,1,0,0,0,0,0,1 = 41
    vec(J, "to-mlsb-signed", J, "mlsb-signed", '{"z":-1,"w":-2}', B(MLSB, "11111111 01000001"),
        ref=S3 + "the sign is written last")
    # mlsb-text: label 0:0:16 ascii | tag 0:16:7 chars:ascii7.
    # A = 01000001 from bit 0 up: 10000010 = 82; C = 01000011: 11000010 = c2;
    # tag C = 1000011 from bit 0 up: 1100001, then bit 23 unmapped
    vec("mlsb-text", "ascii-and-chars", "mlsb-text", J, "82c2c2", '{"label":"AC","tag":"C"}',
        model={"probe.label": "AC", "probe.tag": "C"},
        ref="spec 0.22 ruling 3: each byte of ascii and each character of chars is read as uint reads a field "
            "of that width at its place: ascii A is 82, ascii7 C is 1100001")
    vec("mlsb-text", "round-trip", "mlsb-text", "mlsb-text", "82c2c2", "82c2c2", ref="spec 0.22 ruling 3")
    vec(J, "to-mlsb-text-nul-padding", J, "mlsb-text", '{"label":"A"}', "820000",
        ref="spec 0.22 ruling 3; ascii pads with NUL (0.5) and an absent chars key writes zero bits (0.15)")
    # mlsb-float: 1.0 = 3f800000; bit 23 and bits 24..29 set. Bytes from bit 0
    # up: bits 0..7 = 00, 8..15 = 00, 16..23 = 00000001, 24..31 = 11111100
    vec("mlsb-float", "one", "mlsb-float", J, "000001fc", '{"a":1}', model={"probe.a": "1"},
        ref="spec 0.22 ruling 3: the bit pattern of a float is read as uint reads 32 bits: f32 1.0 is 000001fc")
    vec("mlsb-float", "round-trip", "mlsb-float", "mlsb-float", "000001fc", "000001fc", ref="spec 0.22 ruling 3")
    # -2.5 = c0200000: bits 16..23 = 0x20 (bit 21) -> 00000100; bits 24..31 =
    # 0xc0 (bits 30, 31) -> 00000011
    vec(J, "to-mlsb-float", J, "mlsb-float", '{"a":-2.5}', "00000403",
        ref="spec 0.22 ruling 3: f32 -2.5 is c0200000, written from bit 0 up")
    # mlsb-absent: x 0:0:8 uint absent 1
    S2 = "spec 0.22 ruling 2: the raw values sentinels compare use the pack's bit order; "
    vec("mlsb-absent", "raw-value-1-is-80", "mlsb-absent", J, "80", "{}", model={"@absent": ["probe.x"]},
        ref=S2 + "80 is the raw value 1")
    vec("mlsb-absent", "01-is-128", "mlsb-absent", J, "01", '{"x":128}', model={"probe.x": "128"},
        ref=S2 + "01 is 128, not the sentinel")
    vec(J, "to-mlsb-absent-writes-80", J, "mlsb-absent", "{}", "80", ref=S2 + "the sentinel 1 is written as 80")
    # mlsb-swap: x 0:0:16 uint swap. 01 02: chunks 01 | 02 reversed: 02 01 =
    # 00000010 00000001: bit 6 and bit 15 from bit 0 up: 64 + 32768 = 32832
    S13 = "spec 0.22 ruling 13: swap reverses 8-bit chunks of the field taken from its first bit; "
    vec("mlsb-swap", "bytes-reversed-then-low-bit-first", "mlsb-swap", J, "0102", '{"x":32832}',
        model={"probe.x": "32832"}, ref=S13 + "02 01 read from bit 0 up")
    vec("mlsb-swap", "round-trip", "mlsb-swap", "mlsb-swap", "0102", "0102", ref=S13 + "the same bits")
    # x = 1: 10000000 00000000, chunks reversed: 00000000 10000000
    vec(J, "to-mlsb-swap", J, "mlsb-swap", '{"x":1}', "0080", ref=S13 + "the value 1, then the chunks reversed")
    # swap-offset (msb, 0:4:16): 01 23 40 = 0000 | 0001 0010 | 0011 0100 | 0000;
    # chunks 12, 34 reversed: 34 12 = 13330
    vec("swap-offset", "chunks-from-bit-4", "swap-offset", J, "012340", '{"x":13330}', model={"probe.x": "13330"},
        ref=S13 + "whatever its alignment: the chunks are bits 4..11 (12) and 12..19 (34)")
    vec("swap-offset", "round-trip", "swap-offset", "swap-offset", "012340", "012340", ref=S13 + "the same bits")
    # x = 1: 00000000 00000001 -> 00000001 00000000 at bits 4..19:
    # 0000 0000 | 0001 0000 | 0000 0000
    vec(J, "to-swap-offset", J, "swap-offset", '{"x":1}', B(MSB, "0000 00000001 00000000 0000"),
        ref=S13 + "for a field that is not aligned the chunks are not its bytes")
    # swap-offset-lsb (lsb, 0:4:16): a0 cb 0d. Bits 4..11 are the high nibble
    # of a0 (a) and the low nibble of cb (b): chunk value ba; bits 12..19 the
    # high nibble of cb (c) and the low nibble of 0d (d): dc. Unswapped the
    # value would be dcba; reversed it is badc = 47836
    vec("swap-offset-lsb", "chunks-from-bit-4", "swap-offset-lsb", J, "a0cb0d", '{"x":47836}',
        model={"probe.x": "47836"}, ref=S13 + "under lsb, chunks of the field's bits 4..11 and 12..19")
    vec("swap-offset-lsb", "round-trip", "swap-offset-lsb", "swap-offset-lsb", "a0cb0d", "a0cb0d",
        ref=S13 + "the same bits")
    # mlsb-length: length 8 { x 8 }
    vec("mlsb-length", "length-one-is-80", "mlsb-length", "mlsb-length", "80ff", "80ff", model={"probe.x": "255"},
        ref="spec 0.22 ruling 2: a length value uses the pack's bit order; 80 is a length of 1 byte")
    vec("mlsb-length", "to-json", "mlsb-length", J, "80ff", '{"x":255}', ref="spec 0.22 ruling 2")
    # 01 from bit 0 up is 128 bytes: the block runs past the input
    vec("mlsb-length", "01-is-128-bytes", "mlsb-length", "mlsb-length", "01ff", error=MW,
        ref="spec 0.22 ruling 2: 01 is a length of 128 bytes, past the input")
    vec(J, "to-mlsb-length", J, "mlsb-length", '{"x":1}', "8080", ref="spec 0.22 ruling 2: length 1 and x 1")
    # mlsb-count: count n 4 | x 4 | nums count @n { val 8 } | recs count 4 { y 4 }
    # n = 2: 0100; x = 3: 1100; 5: 10100000; 6: 01100000; recs 1: 1000; y 1: 1000
    cnt = B(MLSB, "0100 1100 10100000 01100000 1000 1000")
    vec("mlsb-count", "counts-low-bit-first", "mlsb-count", "mlsb-count", cnt, "4ca06088",
        model={"probe.x": "3", "probe.nums.#": "2", "probe.nums[0].probe.val": "5", "probe.nums[1].probe.val": "6",
               "probe.recs.#": "1", "probe.recs[0].probe.y": "1"},
        ref="spec 0.22 ruling 2: 0.21 count lines and 0.8 group counts read in the pack's bit order")
    vec("mlsb-count", "to-json", "mlsb-count", J, "4ca06088", '{"x":3,"nums":[5,6],"recs":[{"y":1}]}',
        ref="spec 0.22 ruling 2")
    # n = 0 (an absent list writes n, 0), x = 3, recs count 0
    vec(J, "to-mlsb-count-absent-lists", J, "mlsb-count", '{"x":3}', B(MLSB, "0000 1100 0000 0000"),
        ref="spec 0.22 ruling 2 and 0.21: an absent list writes the count 0")
    # mlsb-presence: presence p 2 | if p.1 { x 6 } | if p.2 { y 8 }
    PR = "spec 0.22 ruling 2: presence bits keep their reading-order numbering; "
    vec("mlsb-presence", "first-bit-is-p1", "mlsb-presence", "mlsb-presence", "80", "80",
        model={"probe.x": "0", "@absent": ["probe.y"]}, ref=PR + "80: the first bit read is p.1; x is 0")
    # 1 0 | 101000 (x = 5 from bit 0 up)
    vec("mlsb-presence", "p1-and-x", "mlsb-presence", J, B(MLSB, "10 101000"), '{"x":5}', model={"probe.x": "5"},
        ref=PR + "p.1 = 1, p.2 = 0; x is 6 bits from bit 0 up")
    # 0 1 | 10010000 (y = 9) | 000000
    vec("mlsb-presence", "p2-and-y", "mlsb-presence", J, B(MLSB, "01 10010000 000000"), '{"y":9}',
        model={"probe.y": "9", "@absent": ["probe.x"]}, ref=PR + "p.2 is the second bit read")
    vec(J, "to-mlsb-presence", J, "mlsb-presence", '{"x":5,"y":9}', B(MLSB, "11 101000 10010000"),
        ref=PR + "both bits set, then x and y")
    # mlsb-kinds: const 4 1 | kind a: when 4 1, x 8 | kind b: when 4 2, y 8
    K = "spec 0.22 ruling 2: when and const read and write in the pack's bit order; "
    # const 1 = 1000, when 1 = 1000, x = 3 = 11000000
    vec("mlsb-kinds", "kind-a", "mlsb-kinds", "mlsb-kinds", B(MLSB, "1000 1000 11000000"), "88c0",
        model={"@kind": "a", "probe.x": "3"}, ref=K + "when 4 1 is 1000")
    # when 2 = 0100
    vec("mlsb-kinds", "kind-b", "mlsb-kinds", "mlsb-kinds", B(MLSB, "1000 0100 11000000"), "84c0",
        model={"@kind": "b", "probe.y": "3"}, ref=K + "when 4 2 is 0100")
    # when bits 0001 = 8 from bit 0 up: no kind holds
    vec("mlsb-kinds", "when-0001-is-8", "mlsb-kinds", "mlsb-kinds", "81c0", error="no-kind",
        ref=K + "0001 is 8, neither 1 nor 2")
    vec("mlsb-kinds", "const-not-checked", "mlsb-kinds", "mlsb-kinds", "08c0", "88c0", model={"@kind": "a"},
        ref=K + "a const is not checked on decode and is written as 1000 (0.6)")
    vec(J, "to-mlsb-kinds-b", J, "mlsb-kinds", '{"y":3}', "84c0", ref=K + "requires y selects kind b")
    # mlsb-until: label until:3 chars:ascii7. C = 1000011 from bit 0 up:
    # 1100001; 3 = 0000011: 1100000; 00
    vec("mlsb-until", "terminator-low-bit-first", "mlsb-until", "mlsb-until", B(MLSB, "1100001 1100000 00"), "c380",
        model={"probe.label": "C"}, ref=O + "each code, the terminator included, is read as uint reads 7 bits")
    vec(J, "to-mlsb-until", J, "mlsb-until", '{"label":"C"}', "c380", ref=O + "C, then the code 3")

    # ==========================================================================
    # conformance-long-until-with (msb): s1 until:0 chars:ascii8 with x,
    # default zz | y 8 uint. A = 41, B = 42, z = 7a, NUL = 00, 9 = 09.
    # ==========================================================================
    W = "spec 0.22 ruling 25: a suppressed until: line writes the terminator alone, as an absent key does; "
    # x held: s1 written: 41 42, then 00; y 09.
    vec(J, "to-until-with-companion-held", J, "until-with", '{"s1":"AB","x":1,"y":9}', "41420009",
        ref=W + "x held: the characters, then the terminator (0.22)")
    # x not held: the line is suppressed: 00 alone; y 09.
    vec(J, "to-until-with-ruling-25-suppressed-terminator-alone", J, "until-with", '{"s1":"AB","y":9}', "0009",
        ref=W + "x not held: the terminator alone, then y at the next bit")
    # x held, s1 absent: the default zz (ruling 10): 7a 7a, then 00; y 09.
    vec(J, "to-until-with-companion-held-default", J, "until-with", '{"x":1,"y":9}', "7a7a0009",
        ref=W + "x held and s1 absent: the default applies first (ruling 10)")
    # x not held, s1 absent: suppressed, so not even the default: 00; y 09.
    vec(J, "to-until-with-ruling-25-suppressed-no-default", J, "until-with", '{"y":9}', "0009",
        ref=W + "a suppressed line has neither a default nor a sentinel (ruling 1 of 0.18): the terminator alone, not zz")
    # decode: s1 = AB, y = 9 (decode unchanged); x is mapped by no line: on
    # re-encode the line is suppressed (ruling 6 of 0.18): 00 09.
    vec("until-with", "ruling-25-roundtrip-drops-the-text", "until-with", "until-with", "41420009", "0009",
        model={"probe.s1": "AB", "probe.y": "9"},
        ref=W + "ruling 6 of 0.18: decode is unchanged; x is mapped by no line, so s1 is written as the terminator alone")

    # ==========================================================================
    # conformance-long-uper (msb, encoding uper): x int:0:5 (3 bits) | label
    # until:0 chars:ascii8 | y int:10:13 (2 bits, value - 10). The message is
    # padded with zero bits to a whole octet (0.19).
    # ==========================================================================
    UP = "spec 0.22 ruling 26: until: in a uper pack is read at the cursor with no alignment; "
    # x 5 = 101; A = 01000001; NUL = 00000000; y 12 - 10 = 2 = 10; 3 zero
    # bits to 24: 10101000 00100000 00010000 = a8 20 10.
    vec("uper", "ruling-26-text-at-the-cursor", "uper", "uper", B(MSB, "101 01000001 00000000 10 000"), "a82010",
        model={"probe.x": "5", "probe.label": "A", "probe.y": "12"},
        ref=UP + "the characters start at bit 3, after a 3-bit constrained whole number; y follows the terminator at bit 19")
    vec("uper", "ruling-26-to-json", "uper", J, "a82010", '{"label":"A","x":5,"y":12}', ref=UP + "decode")
    vec(J, "to-uper-ruling-26", J, "uper", '{"x":5,"label":"A","y":12}', "a82010",
        ref=UP + "encode: 101, A and NUL, 10, then zero bits to a whole octet (0.19)")
    # x 1 = 001; label absent: NUL alone, 00000000; y 13 - 10 = 3 = 11; 3
    # zero bits: 00100000 00011000 = 20 18.
    vec(J, "to-uper-ruling-26-absent-text-terminator-alone", J, "uper", '{"x":1,"y":13}', "2018",
        ref=UP + "an absent key writes the terminator alone (0.22), at bit 3")

    # ==========================================================================
    # load vectors from 1010
    # ==========================================================================
    core = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key time_ms int ms\n")
    probe = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey label string -\n"
             "key tag string -\nkey x int -\nkey y int -\nlist names \"a list\"\n")
    head = 'format probe\nversion 0.22.0\ndistribution public\nsource "probe"\nuses probe\n'
    js = head + "wire json\n"
    fixed = head + "wire bits\nword_bytes 1\n"
    seq = head + "wire bits\nlayout sequential\n"
    lnum = [1009]

    def load(name, text, error="bad-directive", gtcheck_kind=None):
        """`gtcheck_kind`: what gtcheck reports where it checks a line early
        (it has no after-file pass for `stop`); the vector states `error`."""
        lnum[0] += 1
        full = "%d-long-%s" % (lnum[0], name)
        got = None
        try:
            m = gtcheck.Model()
            for t in (core, probe):
                m.add(t)
            gtcheck.load_pack(text, m)
        except gtcheck.CheckError as e:
            got = e.kind
        assert got == (gtcheck_kind or error), (full, error, got)
        d = {"name": full, "models": [core, probe], "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    f = "field probe.label "
    # hex
    load("hex-4-bits-loads", fixed + f + "0:0:4 hex\n", None)
    load("hex-2040-bits-loads", fixed + f + "0:0:2040 hex\n", None)
    load("hex-2044-bits", fixed + f + "0:0:2044 hex\n")
    load("hex-6-bits", fixed + f + "0:0:6 hex\n")
    load("hex-2-bits", fixed + f + "0:0:2 hex\n")
    load("hex-sequential-12-bits-loads", seq + f + "12 hex\n", None)
    load("hex-sequential-2044-bits", seq + f + "2044 hex\n")
    load("hex-with-swap", fixed + f + "0:0:16 hex swap\n")
    load("hex-with-trim", fixed + f + "0:0:16 hex trim\n")
    load("hex-with-an-argument", fixed + f + "0:0:16 hex:4\n")
    load("hex-on-json", js + f + "label hex\n")
    load("hex-absent-on-72-bits", fixed + f + "0:0:72 hex absent 0\n")
    load("hex-absent-on-64-bits-loads", fixed + f + "0:0:64 hex absent 0\n", None)
    load("hex-absent-value-above-the-raw-width", fixed + f + "0:0:8 hex absent 256\n")
    load("hex-on-an-int-key", fixed + "field probe.x 0:0:8 hex\n", "key-type-mismatch")
    load("hex-in-a-kind-and-a-group-loads", seq + "kind a\nwhen 8 1\n" + f + "8 hex\ngroup probe.names count 8\n"
         "  field probe.tag 16 hex\nend\n", None)
    # bit_order msb-lsb
    load("msb-lsb-on-a-fixed-layout-loads", fixed + "bit_order msb-lsb\n" + f + "0:0:16 hex\n", None)
    load("msb-lsb-on-a-sequential-layout-loads", seq + "bit_order msb-lsb\nfield probe.x 3 uint\n", None)
    load("msb-lsb-with-swap-loads", fixed + "bit_order msb-lsb\nfield probe.x 0:4:16 uint swap\n", None)
    load("msb-lsb-on-json", js + "bit_order msb-lsb\n" + f + "label string\n")
    load("bit-order-lsb-msb", fixed + "bit_order lsb-msb\n" + f + "0:0:16 hex\n")
    # ascii8
    load("ascii8-8-bits-loads", fixed + f + "0:0:8 chars:ascii8\n", None)
    load("ascii8-2040-bits-loads", fixed + f + "0:0:2040 chars:ascii8\n", None)
    load("ascii8-12-bits", fixed + f + "0:0:12 chars:ascii8\n")
    load("ascii8-2048-bits", fixed + f + "0:0:2048 chars:ascii8\n")
    load("ascii8-with-swap", fixed + f + "0:0:16 chars:ascii8 swap\n")
    # until:
    load("until-ascii8-loads", seq + f + "until:0 chars:ascii8\n", None)
    load("until-63-icao6-loads", seq + f + "until:63 chars:icao6\n", None)
    load("until-64-icao6", seq + f + "until:64 chars:icao6\n")
    load("until-127-ascii7-loads", seq + f + "until:127 chars:ascii7\n", None)
    load("until-128-ascii7", seq + f + "until:128 chars:ascii7\n")
    load("until-255-ascii8-loads", seq + f + "until:255 chars:ascii8\n", None)
    load("until-256-ascii8", seq + f + "until:256 chars:ascii8\n")
    load("until-on-a-fixed-layout", fixed + f + "until:0 chars:ascii8\n")
    load("until-with-uint", seq + "field probe.x until:0 uint\n")
    load("until-with-ascii", seq + f + "until:0 ascii\n")
    load("until-with-hex", seq + f + "until:0 hex\n")
    load("until-with-octal", seq + f + "until:0 octal\n")
    load("until-with-absent", seq + f + "until:1 chars:ascii8 absent 0\n")
    load("until-with-swap", seq + f + "until:0 chars:ascii8 swap\n")
    load("until-with-trim", seq + f + "until:0 chars:ascii8 trim\n")
    load("until-code-not-digits", seq + f + "until:x chars:ascii8\n")
    load("until-code-negative", seq + f + "until:-1 chars:ascii8\n")
    load("until-code-with-a-plus", seq + f + "until:+1 chars:ascii8\n")
    load("until-code-empty", seq + f + "until: chars:ascii8\n")
    load("until-code-in-hex", seq + f + "until:0x1 chars:ascii8\n")
    load("until-code-with-a-fraction", seq + f + "until:1.0 chars:ascii8\n")
    load("until-code-leading-zero-loads", seq + f + "until:00 chars:ascii8\n", None)
    load("until-with-via-loads", seq + "map t A B\n" + f + "until:0 chars:ascii8 via t\n", None)
    load("ruling-15-until-in-a-group-and-a-kind-loads", seq + "kind a\nwhen 8 1\n" + f + "until:0 chars:ascii8\n"
         "group probe.names rest\n  field probe.tag until:0 chars:ascii7\nend\n", None)
    load("ruling-16-until-and-stop", seq + f + "until:0 chars:ascii8 stop 0\n")
    # stop
    load("stop-fixed-loads", fixed + f + "0:0:64 chars:ascii8 stop 0\n", None)
    load("stop-sequential-loads", seq + f + "24 chars:ais6 stop 0\n", None)
    load("stop-255-ascii8-loads", fixed + f + "0:0:64 chars:ascii8 stop 255\n", None)
    load("ruling-16-stop-256-ascii8", fixed + f + "0:0:64 chars:ascii8 stop 256\n")
    load("stop-63-icao6-loads", fixed + f + "0:0:24 chars:icao6 stop 63\n", None)
    load("ruling-16-stop-64-icao6", fixed + f + "0:0:24 chars:icao6 stop 64\n")
    load("ruling-16-stop-128-ascii7", fixed + f + "0:0:21 chars:ascii7 stop 128\n")
    load("stop-on-ascii", fixed + f + "0:0:64 ascii stop 0\n")
    load("stop-on-hex", fixed + f + "0:0:64 hex stop 0\n")
    load("stop-on-uint", fixed + "field probe.x 0:0:8 uint stop 0\n")
    load("stop-without-a-code", fixed + f + "0:0:64 chars:ascii8 stop\n")
    load("stop-twice", fixed + f + "0:0:64 chars:ascii8 stop 0 stop 0\n")
    load("stop-code-not-digits", fixed + f + "0:0:64 chars:ascii8 stop x\n")
    # ruling 24: armor sixbit (0.14) and encoding uper (0.19) need bit_order msb; msb-lsb is not msb
    load("ruling-24-armor-with-msb-lsb", fixed + "bit_order msb-lsb\narmor sixbit\nfield probe.x 0:0:8 uint\n")
    load("ruling-24-uper-with-msb-lsb", seq + "bit_order msb-lsb\nencoding uper\nfield probe.x int:0:3 uint\n")
    load("ruling-27-ascii-with-a-parameter", fixed + f + "0:0:64 ascii:8\n")
    # ruling 28: stop's syntax is a line check; its fit and its code are after the file
    BOGUS = "bogus\n"
    load("ruling-28-stop-on-uint-then-bogus", fixed + "field probe.x 0:0:8 uint stop 0\n" + BOGUS, "unknown-directive", "bad-directive")
    load("ruling-28-stop-code-not-digits-then-bogus", fixed + f + "0:0:64 chars:ascii8 stop x\n" + BOGUS, "unknown-directive", "bad-directive")
    load("ruling-28-stop-code-too-large-then-bogus", fixed + f + "0:0:64 chars:ascii8 stop 256\n" + BOGUS, "unknown-directive", "bad-directive")
    load("ruling-28-stop-without-a-code-then-bogus", fixed + f + "0:0:64 chars:ascii8 stop\n" + BOGUS)
    return written


def main(argv=None):
    return genio.vector_main("conformance-long-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
