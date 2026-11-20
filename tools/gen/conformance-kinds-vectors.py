#!/usr/bin/env python3
"""Write the vectors of spec 0.20, kind selection: the packs
`conformance-kinds-*` and the load vectors from 750.

Every expected value here is worked out by hand from the spec text (Version
0.20 and its rulings 1 to 14, and the sections they refer to: 0.5 kinds,
`when` and `requires`, canonical json output and ruling 11; 0.6 defaults,
tables and several lines for one key; 0.7 groups; 0.8 sequential lines,
presence, `opt`, chains, lengths, items by kind and rulings 1, 7, 12, 17, 22
and 23; 0.9 sentinels; 0.18 `with`) and the pack layouts. The hand working is
the comment above each vector and the value is written out literally. It is
checked against a second computation: the small codecs below read the
committed pack.def files and model/*.def with their own parser and apply the
rules to the input. They cover only the lines these packs use. Load vectors
are checked against tools/gen/gtcheck.py. Nothing here imports or calls an
engine.

Readings of the text these vectors rest on (quoted in the report that came
with them):
  - Encode of a `switch` is the fixed point of "the case is the one decode
    would select from the bits the key's line wrote": the script lays the
    message out with a guess of each case, reads the key back from the bits
    written, and lays it out again until the cases agree. Presence bits,
    `opt` bits and `fx` bits count the lines of the selected case only.
  - "a bit that is 1 and that no `if` of the lines read names": the `if`
    lines of the selected cases and of the blocks around them. No vector here
    depends on an `if` inside a block that was not read.
  - A `default` inside a case is the case's (ruling 7); every other default
    belongs to the message or the group body (ruling 19 of 0.8).
  - Encode of a nested switch whose value no case holds and that has no
    `else` fails as decode would: `no-kind`.

Inputs: the pack.def files of the `conformance-kinds-*` packs, model/core.def
and model/probe.def. Writes, under --out, the vector files named above. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-kinds-vectors.py [--out DIR] [--check]
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PREFIX = "conformance-kinds-"


class Fail(Exception):
    """A conversion that fails with an error kind of the spec."""

    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


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
    """One line of a pack: `d` the directive, and what the line holds."""

    def __init__(self, d, **kw):
        self.d = d
        self.body = None
        self.__dict__.update(kw)


def ranges_of(text):
    """The (lo, hi) pairs of a `when` list on bits or protobuf."""
    out = []
    for v in text.split(","):
        lo, _, hi = v.partition("..")
        out.append((int(lo), int(hi or lo)))
    return out


def parse_pack(text):
    pack = {"wire": None, "root": None, "seq": False, "msb": False, "wb": 1, "tables": {},
            "common": [], "kinds": []}
    stack = []                       # open blocks: N nodes
    kinds_of = {None: pack["kinds"]}  # the kinds of the message, or of a group body

    def into():
        if stack:
            top = stack[-1]
            if top.d == "switch":
                return top.arms[-1].body
            if top.d == "group" and top.kinds:
                return top.kinds[-1]["lines"]
            return top.body
        return pack["kinds"][-1]["lines"] if pack["kinds"] else pack["common"]

    for raw in text.splitlines():
        toks = tokens_of(raw)
        if not toks or toks[0] in ("format", "version", "distribution", "source", "uses"):
            continue
        d, a = toks[0], toks[1:]
        if d == "wire":
            pack["wire"] = a[0]
        elif d == "root":
            pack["root"] = a[0]
        elif d == "layout":
            pack["seq"] = a[0] == "sequential"
        elif d == "bit_order":
            pack["msb"] = a[0] == "msb"
        elif d == "word_bytes":
            pack["wb"] = int(a[0])
        elif d == "delimiter":
            pack["delimiter"] = a[0]
        elif d == "map":
            pack["tables"].setdefault(a[0], []).append((a[1], a[2]))
        elif d == "end":
            stack.pop()
        elif d == "kind":
            kind = {"name": a[0], "requires": [], "lines": []}
            (stack[-1].kinds if stack else pack["kinds"]).append(kind)
        elif d == "requires":
            (stack[-1].kinds if stack else pack["kinds"])[-1]["requires"] += a
        elif d in ("case", "else"):
            stack[-1].arms.append(N(d, values=a[0].split(",") if a else None, body=[]))
        else:
            line = N(d, args=a)
            if d == "field":
                line.key, line.loc, line.tr = a[0], a[1], a[2]
                line.via = line.absent = line.with_ = None
                line.also = []
                i = 3
                while i < len(a):
                    setattr(line, {"via": "via", "absent": "absent", "with": "with_"}[a[i]], a[i + 1])
                    i += 2
                if pack["wire"] == "bits" and not pack["seq"]:
                    w, p, n = (int(x) for x in a[1].split(":"))
                    line.start, line.n = w * pack["wb"] * 8 + p, n
                elif pack["wire"] == "bits":
                    line.n = int(a[1])
            elif d == "also":
                into()[-1].also.append(a[0])
                continue
            elif d == "default":
                line.key, line.value = a[0], a[1]
            elif d == "const":
                line.loc, line.value = a[0], a[1]
            elif d == "when":
                line.loc, line.value = a[0], a[1]
                if pack["wire"] == "bits" and not pack["seq"]:
                    w, p, n = (int(x) for x in a[0].split(":"))
                    line.start, line.n = w * pack["wb"] * 8 + p, n
                elif pack["wire"] == "bits":
                    line.n = int(a[0])
            elif d == "presence":
                line.name, line.size = a[0], a[1]
            elif d == "if":
                line.conds = [(c.split(".")[0], int(c.split(".")[1])) for c in a]
            elif d == "length":
                line.n = int(a[0])
            elif d == "group":
                line.key, line.kinds = a[0], []
                if pack["seq"]:
                    line.count = int(a[2])
                else:
                    line.loc_ = a[1]
            elif d == "switch":
                line.key, line.arms = a[0], []
            into().append(line)
            if d in ("if", "opt", "chain", "length", "group", "switch"):
                line.body = []
                stack.append(line)
    return pack


# ------------------------------------------------------------------------------
# the model: key types
# ------------------------------------------------------------------------------
KEY_TYPES = {}      # key -> string | int | float | list
DERIVE_TARGETS = set()


def typed(text, key):
    t = KEY_TYPES[key]
    return int(text) if t == "int" else float(text) if t == "float" else text


def text_of(v):
    """Canonical text: decimal digits; a float as the shortest round trip,
    no point when integral (ruling 3 of 0.1.1)."""
    if isinstance(v, float):
        r = repr(v)
        if "e" in r or "E" in r:
            raise ValueError(r)
        return r[:-2] if r.endswith(".0") else r
    return str(v)


def entity():
    return {"keys": {}, "lists": {}, "kind": None}


def holds_term(scope, term):
    """A `requires` term: a plain key is held when present (a list when it has
    an item); `<key>=<values>` when present and its canonical value is listed."""
    key, eq, values = term.partition("=")
    if not eq:
        return key in scope["keys"] or bool(scope["lists"].get(key))
    if key not in scope["keys"]:
        return False
    return any(typed(v, key) == scope["keys"][key] for v in values.split(","))


def choose_kind(kinds, scope, fmt):
    """0.5 Encode steps 1 and 2 (Item.kind as ruling 26 of 0.8)."""
    if scope.get("kind") and scope["kind"][0] == fmt:
        found = [k for k in kinds if k["name"] == scope["kind"][1]]
        if found:
            return found[0]
    for k in kinds:
        if all(holds_term(scope, t) for t in k["requires"]):
            return k
    raise Fail("no-kind", "no kind qualifies")


# ------------------------------------------------------------------------------
# bits
# ------------------------------------------------------------------------------
def to_bits(hx, msb):
    out = []
    for byte in bytes.fromhex(hx):
        out += [(byte >> (7 - i)) & 1 if msb else (byte >> i) & 1 for i in range(8)]
    return out


def to_hex(bits, msb):
    bits = bits + [0] * (-len(bits) % 8)
    out = bytearray()
    for i in range(0, len(bits), 8):
        out.append(sum(b << (7 - k) if msb else b << k for k, b in enumerate(bits[i:i + 8])))
    return out.hex()


def vbits(v, n, msb):
    return [(v >> (n - 1 - k)) & 1 if msb else (v >> k) & 1 for k in range(n)]


def rbits(bits, msb):
    n = len(bits)
    return sum(b << (n - 1 - k) if msb else b << k for k, b in enumerate(bits))


def in_ranges(v, text):
    return any(lo <= v <= hi for lo, hi in ranges_of(text))


def first_value(text):
    return ranges_of(text)[0][0]


def bits_value(pack, line, raw):
    """The decoded value of a field's raw integer, or None for a sentinel
    (0.9: before via and the transform)."""
    if line.absent is not None and raw in [int(v) for v in line.absent.split(",")]:
        return None
    name, _, arg = line.tr.partition(":")
    if name == "uint":
        v = raw
    elif name == "ascii":
        v = raw.to_bytes(line.n // 8, "big").rstrip(b"\0").decode("ascii")
    elif name == "uscale":
        num, den = (int(x) for x in arg.split("/"))
        v = raw * num / den
    else:
        raise ValueError(name)
    if line.via:
        hit = [m for nat, m in pack["tables"][line.via] if nat == text_of(v)]
        if not hit:
            raise Fail("transform-decode", "no table entry")
        v = typed(hit[0], line.key)
    return v


def bits_raw(pack, line, v):
    """A model value to the field's raw integer."""
    if line.via:
        hit = [nat for nat, m in pack["tables"][line.via] if typed(m, line.key) == v]
        if not hit:
            raise Fail("transform-encode", "no table entry")
        v = int(hit[0])
    name, _, arg = line.tr.partition(":")
    if name == "uint":
        return v & ((1 << line.n) - 1)
    if name == "ascii":
        return int.from_bytes(v.encode("ascii").ljust(line.n // 8, b"\0"), "big")
    if name == "uscale":
        num, den = (int(x) for x in arg.split("/"))
        q = v * den / num
        r = int(abs(q) + 0.5) * (1 if q >= 0 else -1)      # half away from zero
        if not 0 <= r < (1 << line.n):
            raise Fail("transform-encode", "out of range")
        return r
    raise ValueError(name)


# -- the fixed layout with kinds (0.5) ------------------------------------------
def fixed_decode(pack, hx):
    bits, msb = to_bits(hx, pack["msb"]), pack["msb"]

    def val(x):
        if x.start + x.n > len(bits):
            raise Fail("malformed-wire", "short")
        return rbits(bits[x.start:x.start + x.n], msb)

    kind = next((k for k in pack["kinds"] if all(
        w.start + w.n <= len(bits) and in_ranges(val(w), w.value)
        for w in k["lines"] if w.d == "when")), None)
    if kind is None:
        raise Fail("no-kind", "no kind holds")
    ent = entity()
    ent["kind"] = (pack["name"], kind["name"])
    for x in pack["common"] + kind["lines"]:
        if x.d == "field":
            ent["keys"].setdefault(x.key, bits_value(pack, x, val(x)))
    return ent


def fixed_encode(pack, ent):
    msb = pack["msb"]
    kind = choose_kind(pack["kinds"], ent, pack["name"])
    lines = pack["common"] + kind["lines"]
    length = max(x.start + x.n for x in lines if x.d in ("field", "when"))
    out, claimed = [0] * (-(-length // 8) * 8), set()
    for x in lines:
        if x.d == "field" and x.key in ent["keys"]:
            for k, b in enumerate(vbits(bits_raw(pack, x, ent["keys"][x.key]), x.n, msb)):
                if x.start + k not in claimed:
                    out[x.start + k] = b
                    claimed.add(x.start + k)
    for w in lines:
        if w.d != "when":
            continue
        # ruling 3: a field line with a present key on exactly these bits
        # whose value matches keeps its value; else the first value
        exact = [x for x in lines if x.d == "field" and x.key in ent["keys"]
                 and (x.start, x.n) == (w.start, w.n)]
        v = first_value(w.value)
        if exact and in_ranges(bits_raw(pack, exact[0], ent["keys"][exact[0].key]), w.value):
            v = bits_raw(pack, exact[0], ent["keys"][exact[0].key])
        for k, b in enumerate(vbits(v, w.n, msb)):
            out[w.start + k] = b
    return to_hex(out, msb)


# -- the sequential layout (0.8) with switch (0.20) ----------------------------
def scope_defaults(lines, outer=None):
    """The defaults of a body: its own lines and those of its if, opt, chain
    and length blocks; not of a group body and not of a case (ruling 7)."""
    out = dict(outer or {})
    mine = {}

    def visit(nodes):
        for x in nodes:
            if x.d == "default":
                mine.setdefault(x.key, x.value)
            elif x.d in ("if", "opt", "chain", "length"):
                visit(x.body)
    visit(lines)
    out.update({k: typed(v, k) for k, v in mine.items()})
    return out


def arm_for(sw, value):
    """The arm decode selects for the key's value (None: absent), or None."""
    if value is not None:
        for arm in sw.arms:
            if arm.d == "case" and any(typed(v, sw.key) == value for v in arm.values):
                return arm
    return next((arm for arm in sw.arms if arm.d == "else"), None)


class SeqDecoder:
    def __init__(self, pack, hx):
        self.pack, self.msb = pack, pack["msb"]
        self.bits = to_bits(hx, self.msb)
        self.at = 0
        self.limit = [len(self.bits)]       # the end of the innermost extent
        self.seen = {}                      # (switch id, item path) -> arm
        self.counts = {}                    # (group id, item path) -> items read

    def take(self, n):
        if self.at + n > self.limit[-1]:
            raise Fail("malformed-wire", "short")
        self.at += n
        return self.bits[self.at - n:self.at]

    def past_extent(self):
        return len(self.limit) > 1 and self.at >= self.limit[-1]

    def scope(self, common, kinds, sc, path, pres=None):
        pres = pres or {}
        self.lines(common, sc, pres, path)
        if kinds:
            start = self.at
            for kind in kinds:
                self.at = start
                whens = [w for w in kind["lines"] if w.d == "when"]
                if all(in_ranges(rbits(self.take(w.n), self.msb), w.value) for w in whens):
                    sc["kind"] = (self.pack["name"], kind["name"])
                    self.lines([x for x in kind["lines"] if x.d != "when"], sc, pres, path)
                    return
            raise Fail("no-kind", "no kind holds")

    def lines(self, nodes, sc, pres, path):
        pres = dict(pres)
        mine = []
        for x in nodes:
            d = x.d
            if d == "field":
                if self.past_extent():
                    continue                # ruling 7 of 0.8: reads as absent
                v = bits_value(self.pack, x, rbits(self.take(x.n), self.msb))
                if v is not None:
                    for k in [x.key] + x.also:
                        sc["keys"].setdefault(k, v)
            elif d == "presence":
                if x.size == "fx":
                    on, o = set(), 0
                    while True:
                        octet = self.take(8)
                        on.update(7 * o + k + 1 for k in range(7) if octet[k])
                        o += 1
                        if not octet[7]:
                            break
                else:
                    on = {k + 1 for k, b in enumerate(self.take(int(x.size))) if b}
                rec = {"on": on, "named": set()}
                pres[x.name] = rec
                mine.append((rec, x, nodes[nodes.index(x) + 1:]))
            elif d == "if":
                if all(bit in pres[name]["on"] for name, bit in x.conds):
                    self.lines(x.body, sc, pres, path)
            elif d == "opt":
                if self.take(1)[0]:
                    self.lines(x.body, sc, pres, path)
            elif d == "chain":
                parts = [[]]
                for y in x.body:
                    if y.d == "fx":
                        parts.append([])
                    else:
                        parts[-1].append(y)
                self.lines(parts[0], sc, pres, path)
                for k, p in enumerate(parts[1:], 1):
                    if not self.take(1)[0]:
                        break
                    if k == len(parts) - 1 and not p:
                        raise Fail("malformed-wire", "ruling 3 of 0.8: the chain's last fx bit is 1")
                    self.lines(p, sc, pres, path)
            elif d == "length":
                n = rbits(self.take(x.n), self.msb)
                end = self.at + 8 * n
                if end > self.limit[-1]:
                    raise Fail("malformed-wire", "extent")
                self.limit.append(end)
                self.lines(x.body, sc, pres, path)
                self.limit.pop()
                self.at = end
            elif d == "group":
                count = rbits(self.take(x.count), self.msb)
                items = []
                for i in range(count):
                    item = entity()
                    common = x.body
                    self.scope(common, x.kinds, item, path + ((id(x), i),), pres)
                    items.append(item)
                self.counts[id(x), path] = count
                sc["lists"][x.key] = items
            elif d == "switch":
                arm = arm_for(x, sc["keys"].get(x.key))
                self.seen[(id(x), path)] = arm
                if arm is None:
                    raise Fail("no-kind", "switch %s: no case and no else" % x.key)
                self.lines(arm.body, sc, pres, path)
            elif d in ("default",):
                pass
            else:
                raise ValueError(d)
        for rec, decl, after in mine:       # ruling 1 of 0.8 with ruling 21 of 0.20
            named = set()
            self.naming(after, decl.name, path, named)
            if rec["on"] - named:
                raise Fail("malformed-wire", "a presence bit no if names")

    def naming(self, nodes, name, path, named):
        """The bits of `name` that `if` lines name (ruling 17 of 0.8): in every
        block, read or not, except a case that was not the one read (ruling 21)."""
        for x in nodes:
            if x.d == "presence" and x.name == name:
                return
            if x.d == "if":
                named.update(bit for n, bit in x.conds if n == name)
            if x.d in ("if", "opt", "chain", "length"):
                self.naming(x.body, name, path, named)
            elif x.d == "switch":
                arm = self.seen.get((id(x), path))
                if arm is not None:
                    self.naming(arm.body, name, path, named)
            elif x.d == "group":
                # ruling 36: the cases read in every item, a later item included
                for i in range(self.counts.get((id(x), path), 0)):
                    self.naming(x.body + [y for k in x.kinds for y in k["lines"]], name,
                                path + ((id(x), i),), named)


def seq_decode(pack, hx):
    dec = SeqDecoder(pack, hx)
    ent = entity()
    dec.scope(pack["common"], pack["kinds"], ent, ())
    return ent


class SeqEncoder:
    """One layout pass with guesses `sel` of the arms of switches not yet
    reached (for presence, opt and fx bits); `used` records the arms selected
    from the bits written."""

    def __init__(self, pack, sel):
        self.pack, self.msb, self.sel = pack, pack["msb"], sel
        self.used, self.guessed = {}, {}
        self.out = []

    # what a line would write, and whether it is content
    def suppressed(self, x, sc):
        return x.with_ is not None and not (x.with_ in sc["keys"] or sc["lists"].get(x.with_))

    def field_value(self, x, sc, dfl):
        """(raw integer written, by a present key or default)."""
        cands = ([] if self.suppressed(x, sc) else [x.key]) + x.also
        for k in cands:
            if k in sc["keys"]:
                return bits_raw(self.pack, x, sc["keys"][k]), True
        for k in cands:
            if k in dfl:
                return bits_raw(self.pack, x, dfl[k]), True
        if x.absent is not None and not self.suppressed(x, sc):
            return int(x.absent.split(",")[0]), False
        return 0, False

    def arm_guess(self, sw, sc, dfl, path):
        key = (id(sw), path)
        if key in self.sel:
            arm = self.sel[key]
        else:
            v = sc["keys"].get(sw.key, dfl.get(sw.key))
            arm = arm_for(sw, v)
        self.guessed[key] = arm
        return arm

    def content(self, nodes, sc, dfl, path):
        for x in nodes:
            if x.d == "field":
                if any(k in sc["keys"] or k in dfl for k in
                       ([] if self.suppressed(x, sc) else [x.key]) + x.also):
                    return True
            elif x.d == "group":
                if sc["lists"].get(x.key):
                    return True
            elif x.d in ("if", "opt", "chain", "length"):
                if self.content(x.body, sc, dfl, path):
                    return True
            elif x.d == "switch":
                arm = self.arm_guess(x, sc, dfl, path)
                if arm is not None and self.content(arm.body, sc, scope_defaults(arm.body, dfl), path):
                    return True
        return False

    def named(self, nodes, name, sc, dfl, path, on):
        """Set in `on` the bits of `name` whose `if` blocks have content."""
        for x in nodes:
            if x.d == "presence" and x.name == name:
                return                      # hidden from here on (ruling 12)
            if x.d == "if":
                if self.content(x.body, sc, dfl, path):
                    on.update(bit for n, bit in x.conds if n == name)
                self.named(x.body, name, sc, dfl, path, on)
            elif x.d in ("opt", "chain", "length"):
                self.named(x.body, name, sc, dfl, path, on)
            elif x.d == "switch":
                arm = self.arm_guess(x, sc, dfl, path)
                if arm is not None:
                    self.named(arm.body, name, sc, scope_defaults(arm.body, dfl), path, on)
            elif x.d == "group" and not x.kinds:
                # ruling 12 of 0.8: any item with the content sets the bit
                for j, item in enumerate(sc["lists"].get(x.key) or []):
                    self.named(x.body, name, item, scope_defaults(x.body), path + ((id(x), j),), on)

    def scope(self, common, kinds, sc, path, pres=None):
        lines = list(common)
        if kinds:
            kind = choose_kind(kinds, sc, self.pack["name"])
            lines += kind["lines"]
        dfl = scope_defaults(lines)
        rb = {}                             # keys as decode would read them back
        self.lines(lines, sc, dfl, pres or {}, path, rb)

    def lines(self, nodes, sc, dfl, pres, path, rb):
        pres = dict(pres)
        for i, x in enumerate(nodes):
            d = x.d
            if d == "field":
                raw, _ = self.field_value(x, sc, dfl)
                self.out += vbits(raw, x.n, self.msb)
                try:
                    v = bits_value(self.pack, x, raw)
                except Fail:
                    v = None                # ruling 31: does not read back
                    for k in [x.key] + x.also:
                        rb.setdefault(k, Fail)
                if v is not None:
                    for k in [x.key] + x.also:
                        rb.setdefault(k, v)
            elif d == "when":
                self.out += vbits(first_value(x.value), x.n, self.msb)
            elif d == "presence":
                on = set()
                self.named(nodes[i + 1:], x.name, sc, dfl, path, on)
                if x.size == "fx":
                    octets = max([1] + [-(-b // 7) for b in on])
                    for o in range(octets):
                        self.out += [1 if 7 * o + k + 1 in on else 0 for k in range(7)] + [int(o + 1 < octets)]
                else:
                    self.out += [1 if k + 1 in on else 0 for k in range(int(x.size))]
                pres[x.name] = on
            elif d == "if":
                if all(bit in pres[name] for name, bit in x.conds):
                    self.lines(x.body, sc, dfl, pres, path, rb)
            elif d == "opt":
                bit = self.content(x.body, sc, dfl, path)
                self.out.append(int(bit))
                if bit:
                    self.lines(x.body, sc, dfl, pres, path, rb)
            elif d == "chain":
                parts = [[]]
                for y in x.body:
                    if y.d == "fx":
                        parts.append([])
                    else:
                        parts[-1].append(y)
                self.lines(parts[0], sc, dfl, pres, path, rb)
                for k in range(1, len(parts)):
                    bit = any(self.content(p, sc, dfl, path) for p in parts[k:])
                    self.out.append(int(bit))
                    if not bit:
                        break
                    self.lines(parts[k], sc, dfl, pres, path, rb)
            elif d == "length":
                outer, self.out = self.out, []
                self.lines(x.body, sc, dfl, pres, path, rb)
                block = self.out + [0] * (-len(self.out) % 8)
                self.out = outer + vbits(len(block) // 8, x.n, self.msb) + block
            elif d == "group":
                items = sc["lists"].get(x.key) or []
                self.out += vbits(len(items), x.count, self.msb)
                for j, item in enumerate(items):
                    self.scope(x.body, x.kinds, item, path + ((id(x), j),), pres)
            elif d == "switch":
                if rb.get(x.key) is Fail:
                    raise Fail("transform-encode", "ruling 31: switch %s: the key does not read back" % x.key)
                arm = arm_for(x, rb.get(x.key))
                self.used[(id(x), path)] = arm
                if arm is None:
                    raise Fail("no-kind", "switch %s: no case and no else" % x.key)
                self.lines(arm.body, sc, scope_defaults(arm.body, dfl), pres, path, rb)
            elif d == "default":
                pass
            else:
                raise ValueError(d)


def seq_encode(pack, ent):
    sel = {}
    for _ in range(8):
        enc = SeqEncoder(pack, sel)
        enc.scope(pack["common"], pack["kinds"], ent, ())
        if all(enc.used.get(k, arm) is arm for k, arm in enc.guessed.items()):
            return to_hex(enc.out, pack["msb"])
        sel = dict(enc.used)
    raise AssertionError("the cases of the encoder do not settle")


# ------------------------------------------------------------------------------
# protobuf: top-level varint fields
# ------------------------------------------------------------------------------
def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def pb_decode(pack, hx):
    data, i, fields = bytes.fromhex(hx), 0, {}

    def uvarint():
        nonlocal i
        v, s = 0, 0
        while True:
            b = data[i]
            i += 1
            v |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                return v
    while i < len(data):
        tag = uvarint()
        assert tag & 7 == 0
        fields[tag >> 3] = uvarint()

    def value(x, raw):
        return (raw >> 1) ^ -(raw & 1) if x.tr == "psint" else raw
    kind = next((k for k in pack["kinds"] if all(
        int(w.loc) in fields and in_ranges(fields[int(w.loc)], w.value)
        for w in k["lines"] if w.d == "when")), None)
    if kind is None:
        raise Fail("no-kind", "no kind holds")
    ent = entity()
    ent["kind"] = (pack["name"], kind["name"])
    for x in pack["common"] + kind["lines"]:
        if x.d == "field" and int(x.loc) in fields:
            ent["keys"][x.key] = value(x, fields[int(x.loc)])
    return ent


def pb_encode(pack, ent):
    kind = choose_kind(pack["kinds"], ent, pack["name"])
    out, held = {}, {}
    lines = pack["common"] + kind["lines"]
    dfl = {x.key: int(x.value) for x in lines if x.d == "default"}

    def raw(x, v):
        return ((v << 1) ^ (v >> 63)) & ((1 << 64) - 1) if x.tr == "psint" else v
    for x in lines:
        if x.d == "field" and x.key in ent["keys"]:
            out[int(x.loc)] = held[int(x.loc)] = raw(x, ent["keys"][x.key])
        elif x.d == "field" and x.key in dfl:
            out[int(x.loc)] = raw(x, dfl[x.key])    # written; never compared (ruling 29)
    for x in pack["common"] + kind["lines"]:
        if x.d == "when":
            # rulings 3 and 15: a field on the same path whose key the entity
            # holds keeps its value when the value matches
            v = held.get(int(x.loc))
            out[int(x.loc)] = v if v is not None and in_ranges(v, x.value) else first_value(x.value)
    return b"".join(varint(n << 3) + varint(v) for n, v in sorted(out.items())).hex()


# ------------------------------------------------------------------------------
# json and xml: flat members, and on json the groups of the source pack
# ------------------------------------------------------------------------------
def json_text(v):
    """A member's canonical text for `when` (0.5): a string as is, a number
    through a double."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return text_of(float(v))
    return v


def json_read(line, v):
    t = line.tr
    if t == "int":
        return int(v)
    if t == "float":
        return float(v)
    return v


def json_scope(lines, obj, sc):
    for x in lines:
        if x.d == "field" and x.loc in obj and obj[x.loc] is not None:
            sc["keys"].setdefault(x.key, json_read(x, obj[x.loc]))
        elif x.d == "group" and isinstance(obj.get(x.loc_), list):
            items = []
            for el in obj[x.loc_]:
                item = entity()
                json_scope(x.body, el, item)
                items.append(item)
            sc["lists"][x.key] = items


def json_decode(pack, text):
    obj = json.loads(text)
    kind = None
    if pack["kinds"]:
        def holds(w):
            v = obj.get(w.loc)
            items = [t[1:] if t.startswith("=") else t for t in (w.value.split(",") if w.value else [""])]
            return v is not None and json_text(v) in items          # ruling 32
        kind = next((k for k in pack["kinds"] if all(holds(w) for w in k["lines"] if w.d == "when")), None)
        if kind is None:
            raise Fail("no-kind", "no kind holds")
    ent = entity()
    if kind:
        ent["kind"] = (pack["name"], kind["name"])
    json_scope(pack["common"] + (kind["lines"] if kind else []), obj, ent)
    return ent


def json_value(v):
    if isinstance(v, float):
        return text_of(v)
    if isinstance(v, int):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def json_when(text):
    """Ruling 11 of 0.5: canonical number text is a number, else a string;
    a leading `=` forces a string (ruling 32: of the first item)."""
    if text.startswith("="):
        return json.dumps(text[1:], ensure_ascii=False)
    if re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", text) and text_of(float(text)) == text:
        return text
    return json.dumps(text, ensure_ascii=False)


def json_encode(pack, ent):
    kind = choose_kind(pack["kinds"], ent, pack["name"]) if pack["kinds"] else None
    lines = pack["common"] + (kind["lines"] if kind else [])
    whens = {x.loc: x for x in lines if x.d == "when"}
    members = {}            # locator -> text, at the first line naming it
    for x in lines:
        if x.d == "when":
            # ruling 15: a text wire writes the first value, at the position
            # of the first line naming the locator (ruling 26 of 0.5)
            members[x.loc] = json_when(x.value.split(",")[0] if x.value else "")
        elif x.d == "const":
            members[x.loc] = json_when(x.value)      # ruling 28: one literal value
        elif x.d == "field" and x.loc not in whens and x.key in ent["keys"]:
            members.setdefault(x.loc, json_value(ent["keys"][x.key]))
        elif x.d == "field" and x.loc in whens:
            members.setdefault(x.loc, None)
    return "{" + ",".join('"%s":%s' % (k, v if v is not None else
                                         json_when(whens[k].value.split(",")[0] if whens[k].value else ""))
                          for k, v in members.items()) + "}"


def xml_decode(pack, text):
    root = ET.fromstring(text)
    kind = next((k for k in pack["kinds"] if all(
        root.get(w.loc[1:]) is not None and root.get(w.loc[1:]) in w.value.split(",")
        for w in k["lines"] if w.d == "when")), None)
    if kind is None:
        raise Fail("no-kind", "no kind holds")
    ent = entity()
    ent["kind"] = (pack["name"], kind["name"])
    for x in pack["common"] + kind["lines"]:
        if x.d == "field" and root.get(x.loc[1:]) is not None:
            ent["keys"][x.key] = int(root.get(x.loc[1:]))
    return ent


def xml_encode(pack, ent):
    kind = choose_kind(pack["kinds"], ent, pack["name"])
    attrs = []
    for x in pack["common"] + kind["lines"]:
        if x.d == "field" and x.key in ent["keys"]:
            attrs.append('%s="%s"' % (x.loc[1:], ent["keys"][x.key]))
        elif x.d == "when":
            attrs.append('%s="%s"' % (x.loc[1:], x.value.split(",")[0]))
    return "<%s%s/>" % (pack["root"], "".join(" " + a for a in attrs))


# ------------------------------------------------------------------------------
# text (0.10): whole-field locators, `string`, kinds by `when <i> <value>`.
# Ruling 38 of 0.20: on `text` a `when` value is one literal value, a comma
# included; it is never split into a list.
# ------------------------------------------------------------------------------
def text_decode(pack, text):
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if any(not 0x20 <= ord(c) <= 0x7E for c in text):
        raise Fail("malformed-wire", "character")
    parts = text.split(pack.get("delimiter", ","))

    def held(w):                    # compared with the field's whole text
        return int(w.loc) < len(parts) and parts[int(w.loc)] == w.value

    kind = next((k for k in pack["kinds"] if all(held(w) for w in k["lines"] if w.d == "when")), None)
    if kind is None:
        raise Fail("no-kind", "no kind holds")
    ent = entity()
    ent["kind"] = (pack["name"], kind["name"])
    for x in pack["common"] + kind["lines"]:
        if x.d == "field" and int(x.loc) < len(parts) and parts[int(x.loc)] != "":
            assert x.tr == "string"
            ent["keys"].setdefault(x.key, parts[int(x.loc)])
    return ent


def text_encode(pack, ent):
    kind = choose_kind(pack["kinds"], ent, pack["name"])
    lines = pack["common"] + kind["lines"]
    out = [""] * (1 + max(int(x.loc) for x in lines if x.d in ("field", "when")))
    for x in lines:
        if x.d == "field" and x.key in ent["keys"] and out[int(x.loc)] == "":
            out[int(x.loc)] = ent["keys"][x.key]
    for x in lines:                 # `when` written last, over any field (step 1 of 0.10)
        if x.d == "when":
            out[int(x.loc)] = x.value
    return pack.get("delimiter", ",").join(out)


# ------------------------------------------------------------------------------
# convert
# ------------------------------------------------------------------------------
def decode(pack, inp):
    w = pack["wire"]
    if w == "text":
        return text_decode(pack, inp)
    if w == "json":
        return json_decode(pack, inp)
    if w == "xml":
        return xml_decode(pack, inp)
    if w == "protobuf":
        return pb_decode(pack, inp)
    return seq_decode(pack, inp) if pack["seq"] else fixed_decode(pack, inp)


def encode(pack, ent):
    w = pack["wire"]
    if w == "text":
        return text_encode(pack, ent)
    if w == "json":
        return json_encode(pack, ent)
    if w == "xml":
        return xml_encode(pack, ent)
    if w == "protobuf":
        return pb_encode(pack, ent)
    return seq_encode(pack, ent) if pack["seq"] else fixed_encode(pack, ent)


def model_of(ent, prefix=""):
    m = {prefix + k: text_of(v) for k, v in ent["keys"].items()}
    if ent.get("kind"):
        m[prefix + "@kind"] = ent["kind"][1]
    for name, items in ent["lists"].items():
        m[prefix + name + ".#"] = str(len(items))
        for i, item in enumerate(items):
            m.update(model_of(item, "%s%s[%d]." % (prefix, name, i)))
    return m


SOURCE = "constructed"


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written, counters, packs = {}, {}, {}
    for module in ("core", "probe"):
        for raw in sink.read("model/%s.def" % module).splitlines():
            toks = tokens_of(raw)
            if toks and toks[0] in ("key", "list"):
                name = toks[1] if module == "core" else "probe." + toks[1]
                KEY_TYPES[name] = toks[2] if toks[0] == "key" else "list"
            elif toks and toks[0] == "derive":
                DERIVE_TARGETS.add(toks[1])

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
        """`owner`, `frm`, `to`: pack names without `conformance-kinds-`. The
        second computation runs and must agree."""
        owner, frm, to = PREFIX + owner, PREFIX + frm, PREFIX + to
        try:
            ent = decode(pack(frm), inp)
        except Fail as e:
            assert error == e.kind, (name, e.kind, e.why)
            ent = None
        got, failed = None, None
        if ent is not None:
            # 0.5: convert clears Entity.kind unless from == to; an Item.kind
            # names its format, so it is ignored by another format (ruling 26
            # of 0.8). No context; derivations change no key these targets map
            # or require (checked below).
            enc = dict(ent, kind=ent["kind"] if frm == to else None)
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
                        assert gone not in have and gone + ".#" not in have, (name, gone, have)
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
    # targets is a key these packs map or name in `requires`
    for name in os.listdir(sink.path("packs")):
        if name.startswith(PREFIX):
            text = sink.read("packs/%s/pack.def" % name)
            assert not any(t in text.split() for t in DERIVE_TARGETS), name

    # ==========================================================================
    # conformance-kinds-bits (fixed, lsb, word_bytes 1): byte 0 is x and the
    # bits of every `when`; byte 1 by kind. lo: 1,3..5 y; hi: 4..9,20 z;
    # dup: 30,30 w.
    # ==========================================================================
    R = "spec 0.20, Lists and ranges in `when`; "
    vec("bits", "list-first-value", "bits", "bits", "0102", "0102",
        model={"@kind": "lo", "probe.x": "1", "probe.y": "2"},
        ref=R + "1 is listed: lo; x = 1 matches lo's list and is written (ruling 3)")
    vec("bits", "range-low-end", "bits", "bits", "0302", "0302", model={"@kind": "lo", "probe.y": "2"},
        ref=R + "both ends included: 3")
    vec("bits", "range-high-end", "bits", "bits", "0502", "0502", model={"@kind": "lo", "probe.y": "2"},
        ref=R + "both ends included: 5")
    vec("bits", "ruling-02-overlap-first-kind-wins", "bits", "bits", "0402", "0402",
        model={"@kind": "lo", "probe.x": "4", "probe.y": "2", "@absent": ["probe.z"]},
        ref=R + "ruling 2: 4 is in lo's 3..5 and hi's 4..9; lo is first in pack order")
    vec("bits", "second-kind-range", "bits", "bits", "0602", "0602", model={"@kind": "hi", "probe.z": "2"},
        ref=R + "6 lies only in hi's 4..9")
    vec("bits", "second-kind-range-high-end", "bits", "bits", "0902", "0902", model={"@kind": "hi", "probe.x": "9"},
        ref=R + "9: hi; x = 9 matches hi and is written (ruling 3)")
    vec("bits", "value-after-a-range", "bits", "bits", "1402", "1402", model={"@kind": "hi", "probe.x": "20"},
        ref=R + "20 is the value listed after hi's range")
    vec("bits", "value-in-no-list", "bits", "bits", "0202", error="no-kind",
        ref=R + "2 is in no kind's list: no-kind (0.5 Decode step 2)")
    vec("bits", "between-two-ranges", "bits", "bits", "0a02", error="no-kind",
        ref=R + "10 lies after hi's 4..9 and before 20")
    vec("bits", "past-every-range", "bits", "bits", "1502", error="no-kind", ref=R + "21")
    vec("bits", "ruling-02-repeated-value-loads", "bits", "bits", "1e02", "1e02", model={"@kind": "dup", "probe.w": "2"},
        ref=R + "ruling 2: a value repeated in one `when` list loads; 30 selects dup")
    vec("bits", "kind-holds-field-short", "bits", "bits", "01", error="malformed-wire",
        ref=R + "lo holds on byte 0; y on byte 1 is beyond the input (ruling 21 of 0.5)")
    E = "spec 0.20 ruling 3, Encode of a `when` with a list or a range; "
    vec("src", "bits-ruling-03-field-value-in-the-list-written", "src", "bits", '{"x":4,"y":2}', "0402",
        ref=E + "requires y: lo; x = 4 covers exactly the when's bits and matches lo's list, so 4 is written")
    vec("src", "bits-ruling-03-field-value-not-in-the-list-first-value", "src", "bits", '{"x":9,"y":2}', "0102",
        ref=E + "lo; x = 9 is not in 1,3..5: the first value, 1, is written over the field")
    vec("src", "bits-ruling-15-default-does-not-count-first-value", "src", "bits", '{"y":2}', "0102",
        ref=E + "lo; the entity does not hold x. Its default 4 is in lo's list, but a default does not count "
                "(ruling 15): the first value 1 is written over the field")
    vec("src", "bits-range-listed-first-writes-its-lo", "src", "bits", '{"z":7}', "0407",
        ref=E + "requires z: hi; x absent: hi's first listed is the range 4..9, so its lo, 4. (4 is also in lo's list; decode would select lo, the first kind, ruling 2)")
    vec("src", "bits-ruling-03-value-after-the-range-written", "src", "bits", '{"x":20,"z":7}', "1407",
        ref=E + "hi; x = 20 matches the value listed after the range")
    vec("src", "bits-ruling-03-value-of-another-kind-not-written", "src", "bits", '{"x":3,"z":7}', "0407",
        ref=E + "hi; x = 3 is lo's, not in hi's 4..9,20: hi's first value 4")
    vec("src", "bits-repeated-value-written-once", "src", "bits", '{"w":1}', "1e01", ref=E + "dup: 30")
    vec("src", "bits-no-kind-qualifies", "src", "bits", '{"x":1}', error="no-kind",
        ref="spec 0.5 Encode step 2: no kind's `requires` is held")

    # ==========================================================================
    # conformance-kinds-protobuf: field 1 selects (a: 1,3..5; b: 200..300),
    # field 2 is y (a) or z (b). No field maps field 1: encode writes the
    # first value. 200 = c8 01, 300 = ac 02, 301 = ad 02.
    # ==========================================================================
    P = "spec 0.20, Lists and ranges in `when`, on an integer protobuf `when`; "
    vec("protobuf", "list-first-value-roundtrip", "protobuf", "protobuf", "08011002", "08011002",
        model={"@kind": "a", "probe.y": "2"}, ref=P + "1: a")
    vec("protobuf", "range-value-writes-the-first-value", "protobuf", "protobuf", "08041002", "08011002",
        model={"@kind": "a", "probe.y": "2"},
        ref=P + "4 is in 3..5: a. No field line maps field 1, so encode writes a's first value, 1 (0.5 Encode step 4)")
    vec("protobuf", "range-of-two-byte-varints-low-end", "protobuf", "protobuf", "08c8011005", "08c8011005",
        model={"@kind": "b", "probe.z": "5"}, ref=P + "200 = c8 01: b")
    vec("protobuf", "range-high-end-writes-its-lo", "protobuf", "protobuf", "08ac021005", "08c8011005",
        model={"@kind": "b", "probe.z": "5"}, ref=P + "300 = ac 02 is the high end: b; re-encode writes 200, the range's lo")
    vec("protobuf", "value-in-no-list", "protobuf", "protobuf", "08021002", error="no-kind", ref=P + "2")
    vec("protobuf", "past-the-range", "protobuf", "protobuf", "08ad021002", error="no-kind", ref=P + "301 = ad 02")
    vec("protobuf", "field-absent-no-kind", "protobuf", "protobuf", "1002", error="no-kind",
        ref=P + "an integer `when` holds only when the field is a varint equal to a value (0.5)")
    vec("src", "protobuf-list-first-value", "src", "protobuf", '{"y":7}', "08011007", ref=P + "requires y: a; writes 1")
    vec("src", "protobuf-range-lo", "src", "protobuf", '{"z":7}', "08c8011007", ref=P + "requires z: b; writes 200")
    P15 = "spec 0.20 rulings 3 and 15, a field on the `when`'s protobuf path; "
    vec("protobuf", "ruling-15-field-on-the-path-roundtrip", "protobuf", "protobuf", "1808", "1808",
        model={"@kind": "c", "probe.w": "8"}, ref=P15 + "8 is in 7..9: c; w = 8 matches and is written")
    vec("protobuf", "ruling-15-field-on-the-path-outside-the-range", "protobuf", "protobuf", "1806", error="no-kind",
        ref=P15 + "6 is not in 7..9; field 1 is absent, so a and b do not hold")
    vec("src", "protobuf-ruling-15-field-value-not-in-the-range", "src", "protobuf", '{"w":5}', "1807",
        ref=P15 + "requires w: c; w = 5 does not match: the first value 7 is written")
    P29 = "spec 0.20 ruling 29: on protobuf the raw varint the field wrote is compared, with no zig-zag; a default never counts; "
    vec("protobuf", "ruling-29-psint-raw-varint-listed", "protobuf", "protobuf", "18012005", "18012005",
        model={"@kind": "d", "probe.c2": "-1", "probe.n": "5"},
        ref=P29 + "field 3 = 1 is in d's 2,1 (not in c's 7..9): d; psint 1 is -1. Re-encode: -1 writes the raw 1, listed, so it is kept")
    vec("protobuf", "ruling-29-psint-raw-varint-2", "protobuf", "protobuf", "18022005", "18022005",
        model={"@kind": "d", "probe.c2": "1"}, ref=P29 + "raw 2 is psint 1; it writes raw 2 again, listed")
    vec("src", "protobuf-ruling-29-negative-value-raw-varint-listed", "src", "protobuf", '{"n":5,"c2":-1}', "18012005",
        ref=P29 + "requires n: d; c2 = -1 writes the raw varint 1, which is listed: kept (the model value -1 is not)")
    vec("src", "protobuf-ruling-29-default-only-first-value", "src", "protobuf", '{"n":5}', "18022005",
        ref=P29 + "c2 has only its default -1, whose raw 1 is listed; a default does not count: the first value 2")
    vec("src", "protobuf-ruling-29-raw-varint-not-listed", "src", "protobuf", '{"n":5,"c2":2}', "18022005",
        ref=P29 + "c2 = 2 writes the raw 4, not listed: the first value 2 (which reads back as 1)")
    vec("src", "protobuf-ruling-15-field-value-in-the-range", "src", "protobuf", '{"w":9}', "1809",
        ref=P15 + "w = 9 matches 7..9 and is written")

    # ==========================================================================
    # conformance-kinds-json: member s (common) then t (each kind's `when`)
    # then the kind's member. ab: a,b; dots: 1..3 literal; empty: ""; lead: 01.
    # ==========================================================================
    T = "spec 0.20, Lists and ranges in `when`, on text wires; "
    vec("json", "list-first-text", "json", "json", '{"t":"a","x":1}', '{"t":"a","x":1}',
        model={"@kind": "ab", "probe.x": "1"}, ref=T + "a is listed")
    vec("json", "list-second-text-writes-the-first", "json", "json", '{"s":"q","t":"b","x":1}', '{"s":"q","t":"a","x":1}',
        model={"@kind": "ab", "probe.s1": "q"}, ref=T + "b is listed: ab; on encode the first listed value, a, is written")
    vec("json", "comma-separates-values", "json", "json", '{"t":"a,b","x":1}', error="no-kind",
        ref=T + "a comma separates values: the text a,b is in no list")
    vec("json", "dots-are-literal-text", "json", "json", '{"t":"1..3","y":2}', '{"t":"1..3","y":2}',
        model={"@kind": "dots", "probe.y": "2"}, ref=T + "on text wires `..` has no meaning and the text is literal")
    vec("json", "dots-are-not-a-range-text", "json", "json", '{"t":"2","y":2}', error="no-kind",
        ref=T + "the text 2 is not the text 1..3")
    vec("json", "dots-are-not-a-range-number", "json", "json", '{"t":2,"y":2}', error="no-kind",
        ref=T + "the number 2, canonical text 2, is not the text 1..3")
    vec("json", "empty-text-alone", "json", "json", '{"t":"","z":3}', '{"t":"","z":3}',
        model={"@kind": "empty", "probe.z": "3"}, ref=T + '`""` alone is the empty text (ruling 11 of 0.9)')
    vec("json", "ruling-01-leading-zero-text-matches-as-written", "json", "json", '{"t":"01","w":4}', '{"t":"01","w":4}',
        model={"@kind": "lead", "probe.w": "4"},
        ref=T + "ruling 1: `when` values compare as 0.5 states, text as written on text wires; 01 is not canonical number text, so it is written as a string (ruling 11 of 0.5)")
    vec("json", "ruling-01-number-1-is-not-the-text-01", "json", "json", '{"t":1,"w":4}', error="no-kind",
        ref=T + "ruling 1: canonical 01 = 1 holds for case and requires, not for a text-wire `when`: the canonical text of 1 is 1")
    vec("src", "json-list-first-text", "src", "json", '{"x":5}', '{"t":"a","x":5}', ref=T + "requires x: ab")
    T15 = "spec 0.20 ruling 15: on text wires a `when` with a list writes its first value; "
    vec("json", "ruling-15-field-on-the-member-writes-the-first-value", "json", "json", '{"u":"q"}', '{"u":"p"}',
        model={"@kind": "lbl", "probe.label": "q"},
        ref=T15 + "label = q is listed, yet the member is written once, with p (ruling 26 of 0.5)")
    vec("src", "json-ruling-15-field-value-in-the-list-not-written", "src", "json", '{"label":"q"}', '{"u":"p"}',
        ref=T15 + "requires label: lbl; ruling 3 does not apply on text wires")
    T32 = "spec 0.20 ruling 32: a leading `=` is stripped from each item of a text-wire `when` list; "
    vec("json", "ruling-32-second-item-stripped", "json", "json", '{"v":"x","c":1}', '{"v":"5","c":1}',
        model={"@kind": "eqv", "probe.c1": "1"},
        ref=T32 + "=x is the text x; encode writes the first item, =5, as the string 5")
    vec("json", "ruling-32-first-item-matches-a-number", "json", "json", '{"v":5,"c":1}', '{"v":"5","c":1}',
        model={"@kind": "eqv"}, ref=T32 + "the number 5, canonical text 5, is the first item; written as the string 5")
    vec("json", "ruling-32-one-equals-stripped", "json", "json", '{"v":"=x","c":1}', error="no-kind",
        ref=T32 + "the text =x is not x")
    vec("src", "json-ruling-32-first-item-forces-a-string", "src", "json", '{"c1":2}', '{"v":"5","c":2}',
        ref=T32 + "requires c1: eqv; the first item's `=` decides that json writes a string")
    vec("src", "json-ruling-15-field-value-not-in-the-list", "src", "json", '{"label":"z"}', '{"u":"p"}', ref=T15)
    vec("src", "json-dots-text", "src", "json", '{"y":5}', '{"t":"1..3","y":5}', ref=T + "requires y: dots")
    vec("src", "json-empty-text", "src", "json", '{"z":5}', '{"t":"","z":5}', ref=T + 'requires z: empty; `""` writes ""')
    vec("src", "json-leading-zero-text", "src", "json", '{"s1":"q","w":5}', '{"s":"q","t":"01","w":5}',
        ref=T + "requires w: lead; 01 is written as the string 01 (ruling 11 of 0.5)")

    # ==========================================================================
    # conformance-kinds-xml: r: @t a..b; l: @t c,d.
    # ==========================================================================
    vec("xml", "dots-are-literal-text", "xml", "xml", '<msg t="a..b" x="1"/>', '<msg t="a..b" x="1"/>',
        model={"@kind": "r", "probe.x": "1"}, ref=T + "`when @t a..b` matches the literal text a..b")
    vec("xml", "dots-are-not-a-range", "xml", "xml", '<msg t="a" x="1"/>', error="no-kind",
        ref=T + "a is not the text a..b")
    vec("xml", "list-second-text-writes-the-first", "xml", "xml", '<msg t="d" y="2"/>', '<msg t="c" y="2"/>',
        model={"@kind": "l", "probe.y": "2"}, ref=T + "d is listed: l; encode writes the first value, c")
    vec("xml", "comma-separates-values", "xml", "xml", '<msg t="c,d" y="2"/>', error="no-kind",
        ref=T + "a comma separates values: the text c,d is in no list")
    vec("src", "xml-dots-text", "src", "xml", '{"x":1}', '<msg t="a..b" x="1"/>', ref=T + "requires x: r")
    vec("src", "xml-list-first-text", "src", "xml", '{"y":2}', '<msg t="c" y="2"/>', ref=T + "requires y: l")

    # ==========================================================================
    # conformance-kinds-env (json): n x s a common; k is each kind's `when`.
    # one: n=01 and x; two: n=2,3; both: n=4 and n=5; eq: s1==x; fl: a=2.50;
    # other: nothing required.
    # ==========================================================================
    Q = "spec 0.20, Encode kind by value; "
    vec("src", "env-ruling-01-requires-01-is-the-integer-1", "src", "env", '{"n":1,"x":0}', '{"n":1,"x":0,"k":"one"}',
        ref=Q + "ruling 1: `requires probe.n=01` holds for n = 1; x is held (0 holds): one")
    vec("src", "env-ruling-04-every-term-must-hold", "src", "env", '{"n":1}', '{"n":1,"k":"other"}',
        ref=Q + "ruling 4: one's second line `requires probe.x` fails; n = 1 is not 2 or 3, 4, ...: other")
    vec("src", "env-value-list", "src", "env", '{"n":3}', '{"n":3,"k":"two"}', ref=Q + "3 is listed by two")
    vec("src", "env-value-list-first", "src", "env", '{"n":2,"x":0}', '{"n":2,"x":0,"k":"two"}',
        ref=Q + "one needs n = 1; two lists 2")
    vec("src", "env-ruling-04-two-lines-on-one-key-never-both", "src", "env", '{"n":4}', '{"n":4,"k":"other"}',
        ref=Q + "ruling 4: `requires probe.n=4` and `requires probe.n=5` never both hold")
    vec("src", "env-key-absent-does-not-hold", "src", "env", '{"x":0}', '{"x":0,"k":"other"}',
        ref=Q + "the kind qualifies only when the entity holds the key")
    vec("src", "env-ruling-04-split-at-the-first-equals", "src", "env", '{"s1":"=x"}', '{"s":"=x","k":"eq"}',
        ref=Q + "ruling 4: `probe.s1==x` is split at the first `=`; the value is the text =x, no `=` stripped")
    vec("src", "env-ruling-04-no-equals-stripped", "src", "env", '{"s1":"x"}', '{"s":"x","k":"other"}',
        ref=Q + "ruling 4: the text x is not =x")
    vec("src", "env-ruling-01-float-value-canonical", "src", "env", '{"a":2.5}', '{"a":2.5,"k":"fl"}',
        ref=Q + "ruling 1: 2.50 and 2.5 are one float value")
    vec("src", "env-ruling-24-float-value-with-an-exponent", "src", "env", '{"a":1}', '{"a":1,"k":"f1"}',
        ref=Q + "ruling 24: `requires probe.a=1e0` is the float 1; the json number 1 on a float key is 1.0")
    vec("src", "env-ruling-24-integer-value-on-a-float-key", "src", "env", '{"a":2}', '{"a":2,"k":"f2"}',
        ref=Q + "ruling 24: on a float key the integer value 2 compares as the float 2.0")
    vec("src", "env-float-value-other", "src", "env", '{"a":2.25}', '{"a":2.25,"k":"other"}', ref=Q + "2.25 is not 2.5")
    vec("env", "ruling-04-entity-kind-used-without-checking-values", "env", "env", '{"n":9,"k":"two"}', '{"n":9,"k":"two"}',
        model={"@kind": "two", "probe.n": "9"},
        ref=Q + "ruling 4: a kind recorded on the entity (same format) is used; `=` is checked only when the kind is chosen by requires")
    vec("env", "ruling-04-entity-kind-that-requires-never-chooses", "env", "env", '{"n":1,"k":"both"}', '{"n":1,"k":"both"}',
        model={"@kind": "both"}, ref=Q + "ruling 4: both is never chosen by requires, but the recorded kind is used")
    vec("env", "decode-ignores-requires", "env", "env", '{"x":0,"k":"one"}', '{"x":0,"k":"one"}',
        model={"@kind": "one", "@absent": ["probe.n"]},
        ref="spec 0.5 Decode: kinds are selected by `when`; `requires` is for encode")

    # ==========================================================================
    # conformance-kinds-switch (msb): x : 8; 0 c2 : 8 | 01 y : 8 | 2,3 z : 16 |
    # 4 nothing | else w : 8; then c1 : 8.
    # ==========================================================================
    S = "spec 0.20, A switch on a decoded value; "
    vec("switch", "case-0", "switch", "switch", "000907", "000907",
        model={"probe.x": "0", "probe.c2": "9", "probe.c1": "7", "@absent": ["probe.y", "probe.z", "probe.w"]},
        ref=S + "x = 0 selects case 0: c2; the cursor goes on after `end`: c1")
    vec("switch", "ruling-01-case-01-is-the-integer-1", "switch", "switch", "010507", "010507",
        model={"probe.x": "1", "probe.y": "5", "probe.c1": "7", "@absent": ["probe.c2", "probe.z", "probe.w"]},
        ref=S + "ruling 1: `case 01` holds the integer 1")
    vec("switch", "case-list-first", "switch", "switch", "02000507", "02000507", model={"probe.z": "5", "probe.c1": "7"},
        ref=S + "2 is in the list 2,3: z : 16 = 0x0005")
    vec("switch", "case-list-second", "switch", "switch", "03010207", "03010207", model={"probe.z": "258"},
        ref=S + "3 is in the list 2,3: z = 0x0102 = 258")
    vec("switch", "ruling-06-empty-case-reads-nothing", "switch", "switch", "0407", "0407",
        model={"probe.x": "4", "probe.c1": "7", "@absent": ["probe.c2", "probe.y", "probe.z", "probe.w"]},
        ref=S + "ruling 6: an empty case reads and writes nothing; there is no fall-through into else")
    vec("switch", "else", "switch", "switch", "090507", "090507", model={"probe.x": "9", "probe.w": "5", "probe.c1": "7"},
        ref=S + "no case holds 9: the else lines")
    vec("switch", "case-lines-past-the-input", "switch", "switch", "0105", error="malformed-wire",
        ref=S + "case 01 reads y = 5; c1 is past the input (0.8 Errors)")
    vec("src", "switch-absent-key-zero-bits-select-case-0", "src", "switch", '{"c2":9,"c1":7}', "000907",
        ref=S + "Encode: the zero bits of an absent key select as decode would: case 0")
    vec("src", "switch-case-01", "src", "switch", '{"x":1,"y":5,"c1":7}', "010507", ref=S + "Encode: x = 1: case 01")
    vec("src", "switch-case-list", "src", "switch", '{"x":3,"z":258}', "03010200", ref=S + "Encode: case 2,3; c1 absent: zero bits")
    vec("src", "switch-ruling-06-empty-case-writes-nothing", "src", "switch", '{"x":4,"y":5,"z":6,"w":7}', "0400",
        ref=S + "ruling 6: case 4 writes nothing; y, z and w belong to other cases")
    vec("src", "switch-else", "src", "switch", '{"x":200,"w":1,"y":2}', "c80100", ref=S + "Encode: 200 is in no case: else, w")
    vec("src", "switch-key-of-another-case-dropped", "src", "switch", '{"y":5}', "000000",
        ref=S + "Encode: x absent writes zero bits: case 0; y belongs to case 01 and is not written")

    # ==========================================================================
    # conformance-kinds-enc (msb): x default 1 / switch 1 c1, else c2; y absent
    # 255 / switch 255 v1, else v2; z with n / switch 0 v3, else -; w also qty /
    # switch 7 v4, else -.
    # ==========================================================================
    C = S + "Encode: the case is the one decode would select from the bits the key's line wrote; "
    vec("src", "enc-default-sentinel-and-suppressed-select-as-decode", "src", "enc", "{}", "0100ff00000000",
        ref=C + "x: its default 1, case 1, c1 zero bits; y: the sentinel 255 reads back absent, else, v2 zero; "
                "z: suppressed (n not held), zero bits, case 0, v3 zero; w: zero bits, 0, else (empty)")
    vec("src", "enc-sentinel-value-and-also-select-as-decode", "src", "enc",
        '{"x":3,"c2":5,"y":255,"v1":6,"z":4,"n":1,"qty":7,"v4":9}', "0305ff00040709",
        ref=C + "x = 3: else, c2; y = 255 is written (0.9 Encode) and reads back absent: else, v2 zero, v1 not written; "
                "z = 4 with n held: else; w absent: the line writes qty's 7 (`also`), read back w = 7: case 7, v4")
    vec("src", "enc-with-suppressed-line-selects-case-0", "src", "enc", '{"z":4,"v3":2}', "0100ff00000200",
        ref=C + "z = 4 but n is not held: the line writes zero bits (0.18), so case 0 and v3 = 2")
    vec("src", "enc-plain-value", "src", "enc", '{"y":2,"v2":3,"v1":4}', "01000203000000",
        ref=C + "y = 2: else, v2 = 3; v1 belongs to case 255")
    vec("src", "enc-present-key-not-its-default", "src", "enc", '{"x":0,"c2":5}', "0005ff00000000",
        ref=C + "x = 0 is present: written, not the default 1: else, c2")
    vec("enc", "sentinel-decodes-absent-and-reads-else", "enc", "enc", "0100ff06000000", "0100ff06000000",
        model={"probe.x": "1", "probe.c1": "0", "probe.v2": "6", "probe.z": "0", "probe.v3": "0", "probe.w": "0",
               "probe.qty": "0", "@absent": ["probe.y", "probe.v1"]},
        ref=S + "Decode: y holds its sentinel, so the key is absent and the else lines are read: v2 = 6, not case "
                "255's v1. Then z = 0: case 0, v3 = 0; w = 0: else")
    vec("enc", "ruling-06-of-0-18-companion-missing-reselects", "enc", "enc", "0305ff00040709", "0305ff0000000709",
        model={"probe.x": "3", "probe.c2": "5", "probe.v2": "0", "probe.z": "4", "probe.w": "7", "probe.qty": "7",
               "probe.v4": "9", "@absent": ["probe.y", "probe.c1", "probe.v1", "probe.v3"]},
        ref=C + "decode: z = 4, else (empty). Re-encode: n is not held, so z's line writes zero bits and selects "
                "case 0, which writes v3 (absent: zero bits); the message gains a byte")

    # ==========================================================================
    # conformance-kinds-record (msb): FSPEC p fx; p.1 chain [y:1][x:6] fx
    # [c1:7] fx; switch y: 0 (p.2 z:8, p.3 w:16, p.4 qty:8), 1 (p.2 c2:16,
    # p.3 n:8), else (p.2 val:8).
    # ==========================================================================
    A = S + "a switch key read inside an earlier `if` and chain block; "
    vec("record", "type-0-layout", "record", "record", "e00a112233", "e00a112233",
        model={"probe.y": "0", "probe.x": "5", "probe.z": "17", "probe.w": "8755", "@absent": ["probe.c2", "probe.n"]},
        ref=A + "FSPEC e0: p.1 p.2 p.3; 0a = y 0, x 000101, fx 0; y = 0: p.2 z = 0x11, p.3 w = 0x2233")
    vec("record", "type-1-layout-same-presence-bits", "record", "record", "e08a112233", "e08a112233",
        model={"probe.y": "1", "probe.x": "5", "probe.c2": "4386", "probe.n": "51", "@absent": ["probe.z", "probe.w"]},
        ref=A + "8a = y 1, x 5: the same p.2 and p.3 read c2 = 0x1122 and n = 0x33")
    vec("record", "key-in-a-block-not-read-reads-else", "record", "record", "4033", "4033",
        model={"probe.val": "51", "@absent": ["probe.y", "probe.x"]},
        ref=A + "FSPEC 40: p.1 is 0, so y's line is not read: the key is absent, the else lines are read: p.2 val")
    vec("record", "rulings-01-17-bit-named-only-by-another-case", "record", "record", "f08a11223344",
        error="malformed-wire",
        ref=A + "rulings 1 and 17 of 0.8 count only the selected case: p.4 is 1 and no `if` of case 1 or of the lines "
                "around the switch names it")
    vec("record", "rulings-01-17-bit-of-type-0", "record", "record", "f00a11223344", "f00a11223344",
        model={"probe.y": "0", "probe.qty": "68"}, ref=A + "y = 0: case 0 names p.4: qty = 0x44")
    vec("record", "rulings-01-17-bit-not-named-by-else", "record", "record", "603344", error="malformed-wire",
        ref=A + "FSPEC 60: p.2 and p.3; y absent: else names p.2 only")
    vec("record", "chain-second-part", "record", "record", "e00b04112233", "e00b04112233",
        model={"probe.y": "0", "probe.x": "5", "probe.c1": "2", "probe.z": "17"},
        ref=A + "0b: fx 1; 04 = c1 0000010, the last fx 0 (ruling 3 of 0.8)")
    vec("src", "record-absent-type-bit-written-zero-selects-case-0", "src", "record", '{"x":5,"z":17,"w":8755}',
        "e00a112233",
        ref=A + "x is content for p.1, so the chain is written and y's line writes a zero bit; decode would read y = 0: "
                "case 0, whose p.2 and p.3 hold z and w")
    vec("src", "record-key-of-an-unselected-case-sets-no-bit", "src", "record",
        '{"x":5,"y":1,"c2":4386,"w":8755,"qty":68}', "c08a1122",
        ref=A + "y = 1: case 1; p.2 from c2; w and qty are keys of case 0: they set no bit (p.3 has no content in case 1, "
                "p.4 is named by no `if` of case 1) and are not written. FSPEC c0")
    vec("src", "record-type-0-with-a-bit-only-it-names", "src", "record", '{"y":0,"qty":68}', "900044",
        ref=A + "y = 0 is content for p.1 (x absent: zero bits); case 0: p.4 from qty. FSPEC 90")
    vec("src", "record-type-bit-not-written-selects-else", "src", "record", '{"val":51,"z":17}', "4033",
        ref=A + "y, x and c1 absent: p.1 is 0 and y's line writes nothing: the key is absent, else; z is case 0's")
    vec("src", "record-chain-written-for-another-key-selects-case-0", "src", "record", '{"val":51,"x":1}', "8002",
        ref=A + "x is content: the chain is written, y writes a zero bit and selects case 0, so val (else) is not "
                "written and p.2 is 0. FSPEC 80; 02 = y 0, x 000001, fx 0")

    # ==========================================================================
    # conformance-kinds-nest (msb): x:7, opt[y:8, switch y 1 (z:8, switch z
    # 2 w:8, 3 -), else -]; chain[c1:7, fx, switch c1 1 c2:8, else v1:8];
    # v2:8, opt[switch v2 1 v3:8, else v4:8]. Tail with nothing: 00 00 00.
    # ==========================================================================
    M = S + "switch blocks inside other blocks; "
    vec("nest", "nested-switch", "nest", "nest", "0b010209000000", "0b010209000000",
        model={"probe.x": "5", "probe.y": "1", "probe.z": "2", "probe.w": "9", "probe.c1": "0", "probe.v2": "0"},
        ref=M + "ruling 5: each switch is read where the cursor is; 0b = x 0000101, opt 1")
    vec("nest", "ruling-06-nested-empty-case", "nest", "nest", "0b0103000000", "0b0103000000",
        model={"probe.z": "3", "@absent": ["probe.w"]}, ref=M + "ruling 6")
    vec("nest", "nested-switch-no-case-no-else", "nest", "nest", "0b0104000000", error="no-kind",
        ref=M + "z = 4: no case holds it and there is no else: the message is no-kind")
    vec("nest", "ruling-06-empty-else", "nest", "nest", "0b02000000", "0b02000000",
        model={"probe.y": "2", "@absent": ["probe.z"]}, ref=M + "ruling 6: an empty else reads nothing")
    vec("nest", "switch-in-an-opt-not-read", "nest", "nest", "0a000000", "0a000000",
        model={"probe.x": "5", "@absent": ["probe.y", "probe.z"]}, ref=M + "the opt bit is 0: the block and its switch are not read")
    vec("nest", "switch-in-a-chain-part", "nest", "nest", "0a03050000", "0a03050000",
        model={"probe.c1": "1", "probe.c2": "5", "@absent": ["probe.v1"]}, ref=M + "03 = c1 0000001, fx 1: c1 = 1, c2")
    vec("nest", "chain-part-not-read", "nest", "nest", "0a020000", "0a020000",
        model={"probe.c1": "1", "@absent": ["probe.c2", "probe.v1"]},
        ref=M + "fx 0: the part with the switch is not read; re-encode: case 1's c2 is absent, so the fx bit is 0")
    vec("nest", "switch-in-a-chain-part-else", "nest", "nest", "0a05070000", "0a05070000",
        model={"probe.c1": "2", "probe.v1": "7"}, ref=M + "05 = c1 2, fx 1: else, v1")
    vec("nest", "switch-alone-in-an-opt", "nest", "nest", "0a00018280", "0a00018280",
        model={"probe.v2": "1", "probe.v3": "5"}, ref=M + "v2 = 1, opt 1, v3 = 5: bits 1 00000101 then zero bits: 82 80")
    vec("src", "nest-encode-nested-no-case-no-else", "src", "nest", '{"x":5,"y":1,"z":4}', error="no-kind",
        ref=M + "Encode: z's line writes 4; decode would find no case and no else: no-kind")
    vec("src", "nest-ruling-22-fx-counts-the-selected-case", "src", "nest", '{"x":5,"c1":1,"v1":7}', "0a020000",
        ref=M + "rulings 22 of 0.8 counts the selected case only: c1 = 1 selects case 1; v1 is else's, so it is not "
                "content and the fx bit is 0")
    vec("src", "nest-fx-set-by-the-selected-else", "src", "nest", '{"x":5,"c1":2,"v1":7}', "0a05070000",
        ref=M + "c1 = 2: else holds v1: fx 1")
    vec("src", "nest-ruling-22-opt-counts-the-selected-case", "src", "nest", '{"v2":1,"v4":5}', "00000100",
        ref=M + "v2 = 1 selects case 1: v4 is not content, the opt bit is 0 and v4 is not written")
    vec("src", "nest-opt-set-by-the-selected-else", "src", "nest", '{"v2":2,"v4":5}', "0000028280",
        ref=M + "v2 = 2: else holds v4: opt 1, then v4 = 5")

    # ==========================================================================
    # conformance-kinds-again (msb): length 8 [x:8]; switch x 1 y:8, else z:8;
    # c1:8 absent 255; switch c1 1 c2:8, else (c1:8, v1:8).
    # ==========================================================================
    G = S + "rulings 9 and 14; "
    vec("again", "ruling-14-key-past-an-extent-reads-else", "again", "again", "0005ff0107", "0100050100",
        model={"probe.z": "5", "probe.c1": "1", "probe.v1": "7", "@absent": ["probe.x", "probe.y", "probe.c2"]},
        ref=G + "ruling 14: the extent is 0 bytes, x's line lies past it and x is absent: else, z. Ruling 9: c1 holds "
                "the sentinel, else; the else's c1 line reads 1 and does not reselect case 1. Re-encode writes every "
                "line of the extent (ruling 7 of 0.8): x zero bits, length 1, else; c1 = 1 now selects case 1, c2 absent")
    vec("again", "extent-holds-the-key", "again", "again", "0101050107", "0101050107",
        model={"probe.x": "1", "probe.y": "5", "probe.c1": "1", "probe.c2": "7"}, ref=G + "length 1: x = 1, case 1")
    vec("again", "extent-content-not-read-is-skipped", "again", "again", "0201aa050107", "0101050107",
        model={"probe.x": "1", "probe.y": "5"},
        ref=G + "length 2: x = 1 and a byte no line reads, skipped (0.8 Lengths)")
    vec("src", "again-zero-bits-in-the-extent-select-as-decode", "src", "again", '{"z":5,"c1":3,"v1":4}', "010005030304",
        ref=G + "x absent: zero bits inside the extent, length 1, read back 0: else, z; c1 = 3: else, c1 again and v1")
    vec("src", "again-sentinel-value-selects-else", "src", "again", '{"x":1,"y":5,"c1":255,"c2":7}', "010105ffff00",
        ref=G + "c1 = 255 is written and reads back absent: else; the else's c1 line writes 255 again, v1 zero bits")

    # ==========================================================================
    # conformance-kinds-items (msb): x:8 and its switch; recs count 8 (small
    # when 1..3 y:8, big when 10..20,2 z:16); items count 8 (qty:8, switch qty
    # 1 val:8, 2 label:16 ascii, no else). Tail with nothing: 00 00.
    # ==========================================================================
    I = S + "groups, presence and defaults in cases; "
    vec("items", "group-in-case-1", "items", "items", "010205060000", "010205060000",
        model={"probe.nums.#": "2", "probe.nums[0].probe.val": "5", "probe.nums[1].probe.val": "6",
               "probe.recs.#": "0", "probe.items.#": "0"}, ref=I + "x = 1: nums with 8-bit items")
    vec("items", "ruling-10-same-list-grouped-in-another-case", "items", "items", "020100050000", "020100050000",
        model={"probe.nums.#": "1", "probe.nums[0].probe.val": "5"},
        ref=I + "ruling 10: x = 2: the same list with 16-bit items, grouped in another case")
    vec("items", "presence-in-a-case", "items", "items", "036007080000", "036007080000",
        model={"probe.c1": "7", "probe.c2": "8"}, ref=I + "x = 3: q = 0110 0000: q.2 c1, q.3 c2")
    vec("items", "presence-bit-of-a-case-named-by-no-if", "items", "items", "03e007080000", error="malformed-wire",
        ref=I + "q.1 is 1 and no `if` names it (ruling 1 of 0.8)")
    vec("items", "ruling-08-same-presence-name-in-another-case", "items", "items", "0440080000", "0440080000",
        model={"probe.c2": "8", "@absent": ["probe.c1"]}, ref=I + "ruling 8: case 4 declares q again: q.2 is c2 there")
    vec("items", "ruling-07-default-in-its-case", "items", "items", "0580030000", "0580030000",
        model={"probe.c1": "3"}, ref=I + "x = 5: d.1, c1 = 3")
    vec("items", "ruling-07-default-in-its-case-is-content", "items", "items", "05000000", "0580090000",
        model={"probe.x": "5", "@absent": ["probe.c1"]},
        ref=I + "ruling 7: decode: d is 0, c1 absent. Re-encode: case 5's default 9 is content for d.1 and is written")
    vec("items", "ruling-07-default-not-in-another-case", "items", "items", "06000000", "06000000",
        model={"probe.x": "6", "@absent": ["probe.c1"]}, ref=I + "ruling 7: case 6 has no default: d stays 0")
    vec("items", "ruling-06-empty-else", "items", "items", "000000", "000000",
        model={"probe.x": "0", "probe.recs.#": "0", "probe.items.#": "0", "@absent": ["probe.nums"]},
        ref=I + "x = 0: the empty else; nums absent")
    vec("items", "item-kinds-by-range-and-list", "items", "items", "000201050c010200", "000201050a010200",
        model={"probe.recs.#": "2", "probe.recs[0].@kind": "small", "probe.recs[0].probe.y": "5",
               "probe.recs[1].@kind": "big", "probe.recs[1].probe.z": "258"},
        ref=S.replace("A switch on a decoded value", "Lists and ranges in `when`") +
        "item kinds (0.8): 01 is in 1..3, small; 0c = 12 is in 10..20, big. Re-encode keeps Item.kind and writes "
        "big's first listed value, the range's lo 10 (0a)")
    vec("items", "ruling-02-item-kind-overlap-first-wins", "items", "items", "0001020700", "0001010700",
        model={"probe.recs[0].@kind": "small", "probe.recs[0].probe.y": "7"},
        ref="spec 0.20 ruling 2: 2 is in small's 1..3 and big's list; small is first. Re-encode writes small's 1")
    vec("items", "item-kind-value-in-no-list", "items", "items", "0001040700", error="no-kind",
        ref="spec 0.20 ruling 11 and 0.8 Items by kind: 4 is in no item kind's list; the item is no-kind and fails the decode")
    vec("items", "switch-in-a-group-body", "items", "items", "0000020105024142", "0000020105024142",
        model={"probe.items.#": "2", "probe.items[0].probe.val": "5", "probe.items[1].probe.label": "AB"},
        ref=I + "each item: qty, then the switch on the item's qty")
    vec("items", "ruling-11-no-kind-item-fails-the-decode", "items", "items", "000002010503", error="no-kind",
        ref=I + "ruling 11: item 1 has qty = 3, no case and no else: the item is no-kind and the whole decode fails")
    vec("src", "items-group-in-case-1", "src", "items", '{"x":1,"nums":[{"val":5},{"val":6}]}', "010205060000",
        ref=I + "case 1's group; recs and items absent: count 0 (ruling 14 of 0.7)")
    vec("src", "items-ruling-10-group-in-case-2", "src", "items", '{"x":2,"nums":[{"val":5}]}', "020100050000",
        ref=I + "case 2's group of the same list")
    vec("src", "items-ruling-07-default-in-its-case", "src", "items", '{"x":5}', "0580090000",
        ref=I + "ruling 7: case 5's default 9 is content for d.1")
    vec("src", "items-ruling-07-no-default-in-another-case", "src", "items", '{"x":6}', "06000000",
        ref=I + "ruling 7: the default of case 5 does not apply in case 6")
    vec("src", "items-presence-in-a-case", "src", "items", '{"x":3,"c1":1}', "0340010000", ref=I + "q.2 from c1: q = 40")
    vec("src", "items-ruling-08-key-of-another-case-sets-no-bit", "src", "items", '{"x":4,"c1":1,"c2":2}', "0440020000",
        ref=I + "case 4 maps c2 at q.2; c1 is mapped by cases 3, 5 and 6 only and is not written")
    vec("src", "items-item-kinds-by-requires", "src", "items", '{"recs":[{"y":5},{"z":258},{"y":1,"z":2}]}',
        "000301050a0102010100",
        ref=S.replace("A switch on a decoded value", "Lists and ranges in `when`") +
        "items choose their kind by requires (0.8): small writes 1, big writes 10 (the lo of its first range); "
        "an item with y and z is small, the first kind whose requires it holds")
    vec("src", "items-switch-in-a-group-body", "src", "items",
        '{"items":[{"qty":1,"val":5},{"qty":2,"label":"AB"}]}', "0000020105024142", ref=I + "per item")
    vec("src", "items-ruling-11-encode-item-no-case", "src", "items", '{"items":[{"qty":3}]}', error="no-kind",
        ref=I + "the item's qty line writes 3: no case, no else: no-kind")
    vec("src", "items-absent-item-key-zero-bits-no-case-0", "src", "items", '{"items":[{"val":5}]}', error="no-kind",
        ref=I + "the item lacks qty: zero bits, read back 0; no case 0 and no else: no-kind")

    # ==========================================================================
    # conformance-kinds-seq (msb): x:8; a: when 0..9, y:8, switch x 1 z:8,
    # else -; b: when 12..14,10, w:8.
    # ==========================================================================
    W = "spec 0.20, Lists and ranges in `when` on a sequential layout; "
    vec("seq", "range-kind-and-switch-on-a-common-key", "seq", "seq", "01050709", "01000709",
        model={"@kind": "a", "probe.x": "1", "probe.y": "7", "probe.z": "9"},
        ref=W + "05 is in 0..9: a; the switch in a reads x from the common lines: z. Re-encode writes a's first value, the lo 0")
    vec("seq", "switch-in-a-kind-else", "seq", "seq", "020907", "020007",
        model={"@kind": "a", "probe.x": "2", "probe.y": "7", "@absent": ["probe.z"]}, ref=W + "x = 2: the empty else")
    vec("seq", "range-listed-first-writes-its-lo", "seq", "seq", "010d07", "010c07",
        model={"@kind": "b", "probe.w": "7"}, ref=W + "13 is in 12..14: b; encode writes 12, the lo of the range listed first")
    vec("seq", "value-after-the-range", "seq", "seq", "010a07", "010c07", model={"@kind": "b"}, ref=W + "10: b")
    vec("seq", "between-the-lists", "seq", "seq", "010b07", error="no-kind", ref=W + "11 is in no list")
    vec("seq", "past-the-range", "seq", "seq", "010f07", error="no-kind", ref=W + "15")
    vec("src", "seq-range-kind-by-requires", "src", "seq", '{"x":1,"y":7,"z":9}', "01000709", ref=W + "requires y: a, when 0")
    vec("src", "seq-range-lo", "src", "seq", '{"w":7}', "000c07", ref=W + "requires w: b, when 12")

    # ==========================================================================
    # conformance-kinds-typed (msb): label:8 via tbl (1 alpha, 2 beta) / switch
    # alpha x:8, beta,gamma y:8, else -; a:8 uscale:1/2 / switch 2.50 z:8,
    # 0 w:8, else -; s1:16 ascii / switch AB c1:8, else -.
    # ==========================================================================
    Y = S + "the key's decoded value (after `via` and `typemap`), as canonical text; "
    vec("typed", "via-float-and-text-keys", "typed", "typed", "01070509414203", "01070509414203",
        model={"probe.label": "alpha", "probe.x": "7", "probe.a": "2.5", "probe.z": "9", "probe.s1": "AB", "probe.c1": "3"},
        ref=Y + "1 via tbl is alpha; 5 * 1/2 = 2.5 is case 2.50 (ruling 1); AB")
    vec("typed", "second-table-value-float-0-short-text", "typed", "typed", "020800064100", "020800064100",
        model={"probe.label": "beta", "probe.y": "8", "probe.a": "0", "probe.w": "6", "probe.s1": "A", "@absent": ["probe.c1"]},
        ref=Y + "beta is in beta,gamma; 0 is case 0; the text A is not AB: else")
    vec("typed", "float-in-no-case", "typed", "typed", "010703414203", "010703414203",
        model={"probe.a": "1.5", "@absent": ["probe.z", "probe.w"]}, ref=Y + "1.5: else")
    vec("src", "typed-value-read-back-through-the-transform", "src", "typed",
        '{"label":"beta","y":4,"a":2.4,"z":9,"s1":"AB","c1":3}', "02040509414203",
        ref=S + "Encode: a = 2.4 writes round(4.8) = 5, which reads back as 2.5: case 2.50, z")
    vec("src", "typed-value-read-back-rounds-to-0", "src", "typed", '{"label":"alpha","x":1,"a":0.2,"w":6,"s1":"B"}',
        "010100064200", ref=S + "Encode: a = 0.2 writes round(0.4) = 0, read back 0: case 0, w; B is not AB")
    vec("src", "typed-absent-keys-zero-bits", "src", "typed", '{"label":"alpha","x":1}', "010100000000",
        ref=S + "Encode: a absent writes 0, case 0, w zero bits; s1 absent writes NUL bytes, read back the empty text: else")

    # ==========================================================================
    # conformance-kinds-pres (msb): p : 8; x : 8; switch x 1 [if p.1 y], 2
    # [opt [if p.2 z]], else; opt [if p.3 w].
    # ==========================================================================
    H = "spec 0.20 ruling 21: an `if` naming a presence counts only when the innermost case it sits in is read; "
    vec("pres", "ruling-21-if-in-no-case-counts-in-a-block-not-read", "pres", "pres", "200200", "000200",
        model={"probe.x": "2", "@absent": ["probe.w"]},
        ref=H + "p.3 is named by an `if` in no case, inside the last opt, whose bit is 0: it counts as before "
                "(ruling 17 of 0.8), so the message is not malformed. Re-encode: w absent, p.3 is 0")
    vec("pres", "ruling-21-if-in-a-case-not-read", "pres", "pres", "800200", error="malformed-wire",
        ref=H + "p.1 is named only inside case 1; x = 2 reads case 2")
    vec("pres", "ruling-21-if-in-the-case-read-inside-a-block-not-read", "pres", "pres", "400200", "000200",
        model={"probe.x": "2", "@absent": ["probe.z"]},
        ref=H + "p.2's `if` sits in case 2, the case read, inside an opt whose bit is 0: it counts")
    vec("pres", "ruling-21-if-in-another-case", "pres", "pres", "400100", error="malformed-wire",
        ref=H + "x = 1: p.2 is named only inside case 2")
    vec("pres", "ruling-21-bit-of-the-case-read", "pres", "pres", "80010500", "80010500",
        model={"probe.y": "5"}, ref=H + "x = 1: p.1, y")
    vec("src", "pres-bits-of-the-selected-case-and-outside", "src", "pres", '{"x":2,"z":5,"y":3,"w":4}', "600282c100",
        ref=H + "case 2: p.2 from z, p.3 from w; y is case 1's: p.1 is 0. Then 1 00000101 1 00000100: 82 c1 00")
    vec("src", "pres-key-of-a-case-not-selected-sets-no-bit", "src", "pres", '{"x":1,"z":5}', "000100",
        ref=H + "x = 1: z is case 2's: p.2 is 0 and the last opt is 0")

    # ==========================================================================
    # conformance-kinds-deflt (msb): n : 8; switch n 1 [defaults v1 5, v2 6;
    # c1 : 8; switch c1 0 [default v2 7; v1, v2], else [v2]], else [v2].
    # ==========================================================================
    D = "spec 0.20 ruling 22: defaults in nested cases apply inside the cases nested in their case; the innermost wins; "
    vec("src", "deflt-ruling-22-outer-and-innermost-defaults", "src", "deflt", '{"n":1}', "01000507",
        ref=D + "c1 absent: zero bits, case 0: v1 takes case 1's 5, v2 case 0's 7")
    vec("src", "deflt-ruling-22-outer-default-in-a-nested-else", "src", "deflt", '{"n":1,"c1":2}', "010206",
        ref=D + "c1 = 2: the nested else; v2 takes case 1's 6")
    vec("src", "deflt-ruling-07-default-not-outside-its-case", "src", "deflt", '{"n":3}', "0300",
        ref=D + "n = 3: else; case 1's defaults do not apply (ruling 7): v2 zero bits")
    vec("src", "deflt-present-key-not-the-default", "src", "deflt", '{"n":1,"v2":9}', "01000509",
        ref=D + "v2 is held: 9; v1 its default 5")
    vec("deflt", "nested-roundtrip", "deflt", "deflt", "01000102", "01000102",
        model={"probe.n": "1", "probe.c1": "0", "probe.v1": "1", "probe.v2": "2"}, ref=D + "values on the wire")

    # ==========================================================================
    # conformance-kinds-const (json): x, const c a,b, const d 1..3.
    # ==========================================================================
    K = "spec 0.20 ruling 28: a `const` value is one literal value; a comma in it is text; "
    vec("src", "const-ruling-28-comma-is-text", "src", "const", '{"x":1}', '{"x":1,"c":"a,b","d":"1..3"}',
        ref=K + "written as a string, as a `when` value is (ruling 11 of 0.5)")
    vec("src", "const-ruling-28-written-without-keys", "src", "const", "{}", '{"c":"a,b","d":"1..3"}', ref=K)
    vec("const", "ruling-28-not-checked-on-decode", "const", "const", '{"x":1,"c":"zz"}', '{"x":1,"c":"a,b","d":"1..3"}',
        model={"probe.x": "1"}, ref=K + "on decode a `const` is not checked (0.6)")

    # ==========================================================================
    # conformance-kinds-presnest (msb): x : 8; case 1: presence q 8, y : 8,
    # switch y 1 [if q.1 c1], 2 [if q.2 c2], else; else.
    # ==========================================================================
    Z = "spec 0.20 ruling 30: an `if` counts when the innermost case that holds the `if` and not the presence is read; "
    vec("presnest", "ruling-30-bit-of-the-nested-case-read", "presnest", "presnest", "01800107", "01800107",
        model={"probe.y": "1", "probe.c1": "7"}, ref=Z + "y = 1: q.1, c1")
    vec("presnest", "ruling-30-other-nested-case", "presnest", "presnest", "01400208", "01400208",
        model={"probe.y": "2", "probe.c2": "8"}, ref=Z + "y = 2: q.2, c2")
    vec("presnest", "ruling-30-bit-named-only-in-another-nested-case", "presnest", "presnest", "014001",
        error="malformed-wire", ref=Z + "q.2 is 1; its `if` is in the nested case 2, and y = 1 reads case 1")
    vec("presnest", "ruling-30-bit-of-case-1-with-case-2-read", "presnest", "presnest", "018002",
        error="malformed-wire", ref=Z + "q.1 is 1; y = 2 reads the nested case 2")
    vec("presnest", "outer-else", "presnest", "presnest", "00", "00", model={"probe.x": "0"}, ref=Z + "x = 0: else")
    vec("src", "presnest-ruling-30-bit-from-the-nested-case-selected", "src", "presnest",
        '{"x":1,"y":2,"c1":5,"c2":8}', "01400208", ref=Z + "y = 2: only q.2 is set; c1 is case 1's")
    vec("src", "presnest-nested-else-sets-no-bit", "src", "presnest", '{"x":1,"y":3,"c1":5}', "010003",
        ref=Z + "y = 3: the nested else; q is all zero")

    # ==========================================================================
    # conformance-kinds-readback (msb): label : 8 via tbl (1 alpha, 256 big);
    # switch big x, alpha y, else z.
    # ==========================================================================
    B = "spec 0.20 ruling 31: a switch key that does not read back on encode is transform-encode: the output would not decode; "
    vec("src", "readback-ruling-31-key-that-does-not-read-back", "src", "readback",
        '{"label":"big","x":1,"z":3}', error="transform-encode",
        ref=B + "big is 256 via tbl; uint writes its low 8 bits, 0 (0.2); 0 has no table entry and the types differ, "
                "so reading it back fails (ruling 4 of 0.6)")
    vec("src", "readback-key-that-reads-back", "src", "readback", '{"label":"alpha","y":2}', "0102", ref=B + "alpha: 1")
    vec("readback", "table-without-an-entry-fails-the-decode", "readback", "readback", "0003", error="transform-decode",
        ref="spec 0.6 Value tables and ruling 4: 0 has no entry and uint yields int, the key a string")
    vec("readback", "table-entry", "readback", "readback", "0102", "0102", model={"probe.label": "alpha", "probe.y": "2"},
        ref=B + "1 is alpha")

    # ==========================================================================
    # conformance-kinds-fail (msb): label : 8 via tbl (1 alpha); switch alpha
    # x : 8, no else.
    # ==========================================================================
    F = "spec 0.20 ruling 35: a switch key whose line fails its transform fails the decode with transform-decode; "
    vec("fail", "ruling-35-key-line-fails-not-no-kind", "fail", "fail", "0207", error="transform-decode",
        ref=F + "2 has no entry in tbl and uint yields int, the key a string (ruling 4 of 0.6): the decode fails, "
                "whatever the switch (which has no else) would read")
    vec("fail", "key-line-reads", "fail", "fail", "0107", "0107", model={"probe.label": "alpha", "probe.x": "7"},
        ref=F + "1 is alpha")
    vec("src", "fail-encode", "src", "fail", '{"label":"alpha","x":7}', "0107", ref=F + "alpha writes 1")

    # ==========================================================================
    # conformance-kinds-across (msb): presence p 8; recs count 8, each x : 8
    # and switch x 1 [if p.1 y : 8], 2 [if p.2 z : 8], else.
    # ==========================================================================
    X = "spec 0.20 ruling 36: a bit named only inside cases is satisfied by such a case read anywhere later in the decode, a later item included; "
    vec("across", "ruling-36-bit-satisfied-by-a-later-item", "across", "across", "c00201050207", "c00201050207",
        model={"probe.recs.#": "2", "probe.recs[0].probe.x": "1", "probe.recs[0].probe.y": "5",
               "probe.recs[1].probe.x": "2", "probe.recs[1].probe.z": "7"},
        ref=X + "p = c0: p.1 and p.2. Item 0 reads case 1 (y); p.2 is named only in case 2, which item 1 reads (z)")
    vec("across", "ruling-36-first-item-without-its-case", "across", "across", "4002010207", "4002010207",
        model={"probe.recs[0].probe.x": "1", "probe.recs[1].probe.z": "7", "@absent": ["probe.recs[0].probe.y"]},
        ref=X + "p = 40: p.2 only. Item 0 reads case 1 and p.1 is 0; item 1 reads case 2, which names p.2")
    vec("across", "ruling-36-no-later-case-names-the-bit", "across", "across", "c0010105", error="malformed-wire",
        ref=X + "p.2 is 1 and no item reads case 2 (ruling 1 of 0.8)")
    vec("src", "across-bits-from-any-item", "src", "across", '{"recs":[{"x":1,"y":5},{"x":2,"z":7}]}', "c00201050207",
        ref=X + "encode: item 0's y sets p.1, item 1's z sets p.2 (ruling 12 of 0.8)")

    # ==========================================================================
    # conformance-kinds-text (delimiter ";"): a when 0 A,B, s1 at 1; b when 0
    # B, s2 at 1. Kinds are checked in pack order; a `when` holds when field
    # 0's whole text equals its value.
    # ==========================================================================
    T = ("spec 0.20 ruling 38: on the 0.10 `text` wire a `when` value stays one literal value, "
         "a comma included; ")
    # field 0 is "A,B", equal to a's value: a. s1 = x. Re-encode (from == to
    # keeps the kind): a's when writes A,B at field 0, s1 x at 1.
    vec("text", "ruling-38-comma-value-selects-a", "text", "text", "A,B;x", "A,B;x",
        model={"@kind": "a", "probe.s1": "x"}, ref=T + "field 0 is the text A,B, equal to a's value")
    # field 0 is "B": not equal to "A,B" (were A,B a list, B would select a,
    # the first kind); equal to b's value: b. s2 = y.
    vec("text", "ruling-38-listed-text-does-not-select-a", "text", "text", "B;y", "B;y",
        model={"@kind": "b", "probe.s2": "y", "@absent": ["probe.s1"]},
        ref=T + "B is not the value A,B, so a does not hold; b's value is B")
    # field 0 is "A": neither "A,B" nor "B": no kind holds.
    vec("text", "ruling-38-part-of-the-value-is-no-kind", "text", "text", "A;z", error="no-kind",
        ref=T + "A is neither A,B nor B: no kind holds (0.5 Decode step 2)")

    # ==========================================================================
    # load vectors from 750
    # ==========================================================================
    core = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key time_ms int ms\n")
    probe = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey x int -\nkey y int -\n"
             "key z int -\nkey a float -\nkey s string -\nkey label string -\nlist items \"a list\"\n")
    head = 'format probe\nversion 0.20.0\ndistribution public\nsource "probe"\nuses probe\n'
    js, xm = head + "wire json\n", head + "wire xml\nroot msg\n"
    pb, fixed = head + "wire protobuf\n", head + "wire bits\nword_bytes 1\n"
    seq = head + "wire bits\nlayout sequential\n"
    lnum = [749]

    def load(name, text, error="bad-directive"):
        lnum[0] += 1
        full = "%d-kinds-%s" % (lnum[0], name)
        got = None
        try:
            m = gtcheck.Model()
            for t in (core, probe):
                m.add(t)
            gtcheck.load_pack(text, m)
        except gtcheck.CheckError as e:
            got = e.kind
        assert got == error, (full, error, got)
        d = {"name": full, "models": [core, probe], "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    # `when` lists and ranges
    fk = fixed + "field probe.x 0:0:8 uint\nkind a\n"
    load("when-list-and-ranges-on-a-fixed-layout-loads", fk + "when 0:0:8 1,3..5,4\nkind b\nwhen 0:0:8 0..255\n", None)
    load("when-ranges-on-a-sequential-layout-loads", seq + "field probe.x 8 uint\nkind a\nwhen 8 1..3\n"
         "kind b\nwhen 4 0..15,3\n", None)
    load("when-ranges-in-item-kinds-loads", seq + "group probe.items count 8\n  kind a\n  when 8 1..3,7\n"
         "  field probe.x 8 uint\n  kind b\n  when 8 2..9\nend\n", None)
    load("when-ranges-on-protobuf-loads", pb + "kind a\nwhen 1 1..5,7\nfield probe.x 2 pvarint\n"
         "kind b\nwhen 3 0..18446744073709551615\n", None)
    load("when-list-on-xml-with-dots-loads", xm + "kind a\nwhen @t a..b,c\nkind b\nwhen @t 5..\n", None)
    load("when-empty-text-alone-on-json-loads", js + 'kind a\nwhen t ""\n', None)
    load("when-list-with-a-space-is-a-third-token", fk + "when 0:0:8 1, 2\n")
    load("when-range-with-no-high-end", fk + "when 0:0:8 5..\n")
    load("when-range-with-no-low-end", fk + "when 0:0:8 ..5\n")
    load("when-range-of-three-ends", fk + "when 0:0:8 1..2..3\n")
    load("when-hex-value", fk + "when 0:0:8 0x10\n")
    load("when-range-low-above-high", fk + "when 0:0:8 5..3\n")
    load("when-range-end-does-not-fit", fk + "when 0:0:8 0..256\n")
    load("when-list-value-does-not-fit", fk + "when 0:0:8 1,256\n")
    load("when-empty-value-in-a-list", fk + "when 0:0:8 1,,2\n")
    load("when-list-ends-with-a-comma", fk + "when 0:0:8 1,\n")
    load("when-signed-value", fk + "when 0:0:8 -1..2\n")
    load("when-sequential-range-end-does-not-fit", seq + "field probe.x 8 uint\nkind a\nwhen 4 0..16\n")
    load("when-sequential-range-low-above-high", seq + "field probe.x 8 uint\nkind a\nwhen 4 9..2\n")
    load("when-item-kind-range-of-three-ends", seq + "group probe.items count 8\n  kind a\n  when 8 1..2..3\nend\n")
    load("when-protobuf-present-with-a-value", pb + "kind a\nwhen 1 present,1\n")
    load("when-protobuf-range-low-above-high", pb + "kind a\nwhen 1 5..3\n")
    load("when-protobuf-range-end-does-not-fit", pb + "kind a\nwhen 1 0..18446744073709551616\n")
    load("when-protobuf-hex-value", pb + "kind a\nwhen 1 0x10\n")
    load("when-json-present-with-a-value", js + "kind a\nwhen t present,a\n")
    # `requires <key>=<value>[,<value>...]`
    rq = js + "field probe.x x int\nfield probe.s s string\nfield probe.a a float\nkind a\n"
    load("requires-values-load", rq + "requires probe.x=1,02 probe.s=a,b probe.a=2.50,-1\nrequires probe.x=-3 uid\n", None)
    load("ruling-04-requires-split-at-the-first-equals-loads", rq + "requires probe.s==x\n", None)
    load("ruling-04-requires-a-key-the-kind-does-not-map-loads", rq + "requires probe.y=4 probe.label=x\n", None)
    load("ruling-04-requires-equals-with-no-value", rq + "requires probe.x=\n")
    load("requires-equals-with-no-key", rq + "requires =1\n")
    load("requires-list-key-with-equals", rq + "requires probe.items=1\n")
    load("requires-int-value-not-an-integer", rq + "requires probe.x=abc\n", "key-type-mismatch")
    load("requires-int-value-in-a-list-not-an-integer", rq + "requires probe.x=1,b\n", "key-type-mismatch")
    load("requires-float-value-not-a-number", rq + "requires probe.a=x\n", "key-type-mismatch")
    load("requires-undeclared-key-with-equals", rq + "requires probe.nosuch=1\n", "undeclared-key")
    load("requires-key-of-a-module-not-used-with-equals", rq + "requires track.speed=1\n", "module-not-used")
    load("ruling-04-list-key-before-key-type-mismatch", rq + "requires probe.items=abc\n")
    load("ruling-04-undeclared-key-before-key-type-mismatch", rq + "requires probe.nosuch=abc\n", "undeclared-key")
    # `switch`
    sx = seq + "field probe.x 8 uint\n"
    load("switch-loads", sx + "presence p 2\nswitch probe.x\n  case 1,2\n    if p.1\n      field probe.y 8 uint\n    end\n"
         "  case 3\n  case 4\n    switch probe.x\n      case 4\n        field probe.z 8 uint\n    end\n"
         "  else\n    field probe.y 4 uint\nend\nfield probe.z 8 uint\n", None)
    load("switch-in-a-kind-on-a-common-key-loads", sx + "kind a\nwhen 8 1\nswitch probe.x\n  case 1\n"
         "    field probe.y 8 uint\nend\nkind b\nfield probe.y 8 uint\nswitch probe.y\n  case 1\nend\n", None)
    load("switch-in-a-group-body-and-an-item-kind-loads", seq + "group probe.items count 8\n  field probe.x 8 uint\n"
         "  switch probe.x\n    case 1\n      field probe.y 8 uint\n  end\n  kind a\n  when 8 1\n  switch probe.x\n"
         "    case 2\n  end\nend\n", None)
    load("switch-in-if-opt-chain-and-length-blocks-loads", sx + "presence p 1\nif p.1\n  switch probe.x\n    case 1\n"
         "  end\nend\nopt\n  switch probe.x\n    case 1\n  end\nend\nchain\n  field probe.y 7 uint\n  fx\n"
         "  switch probe.y\n    case 1\n      chain\n        field probe.z 7 uint\n        fx\n      end\n  end\nend\n"
         "length 8\n  switch probe.x\n    case 1\n  end\nend\n", None)
    load("switch-key-mapped-by-also-loads", seq + "field probe.x 8 uint\nalso probe.y\nswitch probe.y\n  case 1\nend\n", None)
    load("switch-key-mapped-inside-an-earlier-block-loads", seq + "opt\n  field probe.x 8 uint\nend\n"
         "switch probe.x\n  case 1\nend\n", None)
    load("switch-key-mapped-in-a-case-of-an-earlier-switch-loads", sx + "switch probe.x\n  case 1\n"
         "    field probe.y 8 uint\nend\nswitch probe.y\n  case 1\nend\n", None)
    load("switch-on-float-and-string-keys-loads", seq + "field probe.a 8 uscale:1/2\nfield probe.s 16 ascii\n"
         "switch probe.a\n  case 2.50,0,-1\nend\nswitch probe.s\n  case AB,1.0\n  case 01\nend\n", None)
    load("ruling-10-one-list-grouped-in-two-cases-loads", sx + "switch probe.x\n  case 1\n    group probe.items count 8\n"
         "      field probe.y 8 uint\n    end\n  case 2\n    group probe.items count 8\n      field probe.y 16 uint\n"
         "    end\n  else\n    group probe.items while\n      field probe.y 4 uint\n    end\nend\n", None)
    load("ruling-08-same-presence-name-in-two-cases-loads", sx + "switch probe.x\n  case 1\n    presence q 1\n"
         "    if q.1\n      field probe.y 8 uint\n    end\n  case 2\n    presence q 2\n    if q.2\n"
         "      field probe.y 8 uint\n    end\nend\n", None)
    load("switch-on-a-fixed-layout", fixed + "field probe.x 0:0:8 uint\nswitch probe.x\n  case 1\nend\n")
    load("switch-on-json", js + "field probe.x x int\nswitch probe.x\n  case 1\nend\n")
    load("switch-key-not-mapped", sx + "switch probe.y\n  case 1\nend\n")
    load("switch-key-mapped-after-the-switch", sx + "switch probe.y\n  case 1\nend\nfield probe.y 8 uint\n")
    load("switch-key-mapped-only-inside-its-own-case", sx + "switch probe.y\n  case 1\n    field probe.y 8 uint\nend\n")
    load("switch-key-mapped-by-a-kind-switch-in-common", seq + "switch probe.x\n  case 1\nend\nkind a\n"
         "field probe.x 8 uint\n")
    load("switch-key-mapped-in-another-kind", seq + "kind a\nfield probe.x 8 uint\nkind b\nswitch probe.x\n"
         "  case 1\nend\n")
    load("switch-message-key-in-a-group-body", sx + "group probe.items count 8\n  switch probe.x\n    case 1\n"
         "  end\nend\n")
    load("switch-group-key-after-the-group", seq + "group probe.items count 8\n  field probe.x 8 uint\nend\n"
         "switch probe.x\n  case 1\nend\n")
    load("switch-on-a-list", sx + "group probe.items count 8\n  field probe.y 8 uint\nend\nswitch probe.items\n"
         "  case 1\nend\n")
    load("switch-without-a-key", sx + "switch\n  case 1\nend\n")
    load("switch-with-two-keys", sx + "switch probe.x probe.x\n  case 1\nend\n")
    load("case-outside-a-switch", sx + "case 1\n")
    load("else-outside-a-switch", sx + "else\n")
    load("case-inside-an-if-of-a-case", sx + "presence p 1\nswitch probe.x\n  case 1\n    if p.1\n  case 2\n"
         "    end\nend\n")
    load("switch-with-no-case", sx + "switch probe.x\n  else\nend\n")
    load("switch-empty", sx + "switch probe.x\nend\n")
    load("switch-with-two-else", sx + "switch probe.x\n  case 1\n  else\n  else\nend\n")
    load("switch-else-before-a-case", sx + "switch probe.x\n  else\n  case 1\nend\n")
    load("switch-value-in-two-cases", sx + "switch probe.x\n  case 1,2\n  case 2\nend\n")
    load("switch-value-twice-in-one-case", sx + "switch probe.x\n  case 1,1\nend\n")
    load("ruling-01-case-01-and-1-in-two-cases", sx + "switch probe.x\n  case 1\n  case 01\nend\n")
    load("ruling-01-case-2-5-and-2-50-in-two-cases", seq + "field probe.a 8 uscale:1/2\nswitch probe.a\n"
         "  case 2.5\n  case 2.50\nend\n")
    load("switch-without-end", sx + "switch probe.x\n  case 1\n    field probe.y 8 uint\n")
    load("kind-in-a-case", sx + "switch probe.x\n  case 1\nkind a\nend\n")
    load("when-in-a-case", sx + "kind a\nswitch probe.x\n  case 1\n    when 8 1\nend\n")
    load("requires-in-a-case", sx + "kind a\nswitch probe.x\n  case 1\n    requires probe.y\nend\n")
    load("fx-directly-in-a-case", sx + "chain\n  field probe.y 7 uint\n  switch probe.x\n    case 1\n      fx\n"
         "      field probe.z 8 uint\n  end\nend\n")
    load("fx-directly-in-an-else", sx + "chain\n  field probe.y 7 uint\n  switch probe.x\n    case 1\n    else\n      fx\n"
         "  end\nend\n")
    load("header-directive-in-a-case", sx + "switch probe.x\n  case 1\n    bit_order msb\nend\n")
    load("table-directive-in-a-case", sx + "switch probe.x\n  case 1\n    map t 1 a\nend\n")
    load("case-int-value-with-a-fraction", sx + "switch probe.x\n  case 1.0\nend\n", "key-type-mismatch")
    load("case-int-value-with-a-plus-sign", sx + "switch probe.x\n  case +1\nend\n", "key-type-mismatch")
    load("case-int-value-in-a-list-not-an-integer", sx + "switch probe.x\n  case 1,a\nend\n", "key-type-mismatch")
    load("case-float-value-not-a-number", seq + "field probe.a 8 uscale:1/2\nswitch probe.a\n  case x\nend\n",
         "key-type-mismatch")
    load("ruling-08-presence-of-a-case-not-visible-after-end", sx + "switch probe.x\n  case 1\n    presence q 1\n"
         "end\nif q.1\n  field probe.y 8 uint\nend\n")
    load("ruling-08-presence-of-a-case-not-visible-in-another-case", sx + "switch probe.x\n  case 1\n    presence q 1\n"
         "  case 2\n    if q.1\n      field probe.y 8 uint\n    end\nend\n")
    load("presence-declared-twice-in-one-case", sx + "switch probe.x\n  case 1\n    presence q 1\n    presence q 1\nend\n")
    load("ruling-10-one-list-grouped-twice-in-one-case", sx + "switch probe.x\n  case 1\n    group probe.items count 8\n"
         "      field probe.y 8 uint\n    end\n    group probe.items count 8\n      field probe.y 8 uint\n    end\nend\n")
    load("ruling-10-one-list-grouped-in-a-case-and-outside", sx + "group probe.items count 8\n  field probe.y 8 uint\n"
         "end\nswitch probe.x\n  case 1\n    group probe.items count 8\n      field probe.y 8 uint\n    end\nend\n")
    # rulings 15 to 22, from 615
    load("ruling-16-empty-item-in-a-json-when", js + "kind a\nwhen t a,,b\n")
    load("ruling-16-xml-when-ends-with-a-comma", xm + "kind a\nwhen @t a,\n")
    load("ruling-16-empty-item-in-a-case", sx + "switch probe.x\n  case 1,,2\nend\n")
    load("ruling-16-empty-item-in-a-requires-string-list", rq + "requires probe.s=a,,b\n")
    load("ruling-16-requires-list-ends-with-a-comma", rq + "requires probe.x=1,\n")
    load("ruling-17-requires-plus-sign", rq + "requires probe.x=+1\n", "key-type-mismatch")
    load("ruling-19-list-key-with-equals-before-a-field-type-check", js + "field probe.s s int\nkind a\n"
         "requires probe.items=1\n")
    load("ruling-19-field-type-check-before-a-case-duplicate", sx + "switch probe.x\n  case 1\n  case 01\nend\n"
         "field probe.s 8 uint\n", "key-type-mismatch")
    load("ruling-19-requires-value-before-a-later-case-duplicate", sx + "kind a\nrequires probe.x=abc\n"
         "switch probe.x\n  case 1\n  case 1\nend\n", "key-type-mismatch")
    load("ruling-19-case-duplicate-before-a-later-requires-value", sx + "switch probe.x\n  case 1\n  case 01\nend\n"
         "kind a\nrequires probe.x=abc\n")
    load("ruling-19-undeclared-key-before-a-list-key-with-equals", js + "kind a\nrequires probe.items=1\n"
         "field probe.nosuch x int\n", "undeclared-key")
    load("ruling-19-undeclared-key-before-a-repeated-case-value", sx + "switch probe.x\n  case 1,1\nend\n"
         "field probe.nosuch 8 uint\n", "undeclared-key")
    load("ruling-19-type-before-duplicates-in-one-case", sx + "switch probe.x\n  case 1\n  case 01,a\nend\n",
         "key-type-mismatch")
    load("ruling-20-line-between-switch-and-its-first-case", sx + "switch probe.x\n  field probe.y 8 uint\n"
         "  case 1\nend\n")
    load("ruling-20-presence-between-switch-and-its-first-case", sx + "switch probe.x\n  presence q 1\n  case 1\nend\n")
    load("ruling-20-key-of-an-earlier-case-of-the-same-switch-loads", sx + "switch probe.x\n  case 1\n"
         "    field probe.y 8 uint\n  case 2\n    switch probe.y\n      case 1\n    end\nend\n", None)
    load("ruling-22-defaults-in-nested-cases-load", sx + "switch probe.x\n  case 1\n    default probe.y 1\n"
         "    switch probe.x\n      case 1\n        default probe.y 2\n        field probe.y 8 uint\n    end\nend\n", None)
    # rulings 23 to 32, from 632
    load("ruling-23-third-token-on-an-xml-when", xm + "kind a\nwhen @t a, b\n")
    load("ruling-23-third-token-on-a-json-when", js + "kind a\nwhen t a, b\n")
    load("ruling-24-requires-float-with-a-plus-sign", rq + "requires probe.a=+1.5\n", "key-type-mismatch")
    load("ruling-24-requires-float-forms-load", rq + "requires probe.a=1e0,2,-0.5,1.5E-3,10e+2\n", None)
    load("ruling-24-requires-float-with-a-bare-point", rq + "requires probe.a=.5\n", "key-type-mismatch")
    load("ruling-24-requires-float-with-a-trailing-point", rq + "requires probe.a=1.\n", "key-type-mismatch")
    fa = seq + "field probe.a 8 uscale:1/2\nswitch probe.a\n"
    load("ruling-24-case-float-with-a-plus-sign", fa + "  case +1.5\nend\n", "key-type-mismatch")
    load("ruling-24-case-float-forms-load", fa + "  case 1e0,2,-0.5\nend\n", None)
    load("ruling-24-case-1e0-and-1-are-one-float", fa + "  case 1e0\n  case 1\nend\n")
    load("ruling-25-present-in-a-json-list", js + "kind a\nwhen t present,1\n")
    load("ruling-25-present-last-in-a-protobuf-list", pb + "kind a\nwhen 1 1,present\n")
    load("ruling-26-repeated-value-in-a-requires-list-loads", rq + "requires probe.x=1,1,01\n", None)
    load("ruling-27-case-after-else", sx + "switch probe.x\n  case 1\n  else\n  case 2\nend\n")
    load("ruling-27-case-with-no-value", sx + "switch probe.x\n  case\nend\n")
    load("ruling-27-case-with-two-tokens", sx + "switch probe.x\n  case 1 2\nend\n")
    load("ruling-27-else-with-an-argument", sx + "switch probe.x\n  case 1\n  else 3\nend\n")
    load("ruling-28-json-const-with-a-comma-loads", js + "const c a,b\nconst d 1..3\n", None)
    load("ruling-28-bits-const-with-a-comma", sx + "const 8 1,2\n")
    load("ruling-28-bits-const-with-a-range", sx + "const 8 1..2\n")
    load("ruling-32-when-items-with-equals-load", js + "kind a\nwhen t =5,=x,==\n", None)
    load("ruling-39-else-argument-count-is-a-line-check",
         sx + "switch probe.x\n  case 1\n    field probe.y 8 uint\n  else x\nend\nbogus\n")
    load("ruling-38-tlv-when-list", head + "wire tlv\nkind a\nwhen 5:1 1,2\nfield probe.x 6:1 uint\n")
    load("ruling-38-text-wire-when-with-a-comma-is-one-value-loads",
         head + "wire text\ndelimiter \";\"\nkind a\nwhen 0 A,B\nfield probe.label 1 string\n", None)
    return written


def main(argv=None):
    return genio.vector_main("conformance-kinds-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
