#!/usr/bin/env python3
"""Write the vectors of spec 0.21, sequential extents and counts: the packs
`conformance-extents-*` and the load vectors from 900.

Every expected value here is worked out by hand from the spec text (Version
0.21 and its rulings 1 to 28, and the sections they refer to: 0.5 kinds and
canonical json output; 0.7 groups and the json group rules; 0.8 sequential
lines, presence, `opt`, `length` and rulings 5 to 9, 12, 14, 21, 22, 25 and
34) and the pack layouts. The hand working is the comment above each vector,
bits written most significant first, and the value is written out literally.
It is checked against a second computation: the small codecs below read the
committed pack.def files and model/probe.def with their own parser and apply
the rules to the input. They cover only the lines these packs use. Load
vectors are checked against tools/gen/gtcheck.py. Nothing here imports or
calls an engine.

Readings of the text these vectors rest on: those first reported with them
are now rulings 21 to 26 and 29 to 34 of 0.21. Still a reading: "at least 8 bits when the
extent is counted in bytes" counts to the end of the input at message level,
or to the stated length after `length ... whole`. Ruling 10 as amended: with
item kinds only the kinds that end in the inner `rest` count.

Inputs: the pack.def files of the `conformance-extents-*` packs and
model/probe.def. Writes, under --out, the vector files named above. With
--check nothing is written and the exit status is 1 when a committed file
differs from what this script writes.

Usage: python3 -I tools/gen/conformance-extents-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PREFIX = "conformance-extents-"


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


def parse_pack(text):
    pack = {"wire": None, "common": [], "kinds": []}
    stack = []

    def into():
        if stack:
            top = stack[-1]
            return top.kinds[-1]["lines"] if top.d == "group" and top.kinds else top.body
        return pack["kinds"][-1]["lines"] if pack["kinds"] else pack["common"]

    for raw in text.splitlines():
        toks = tokens_of(raw)
        if not toks or toks[0] in ("format", "version", "distribution", "source", "uses", "layout"):
            continue
        d, a = toks[0], toks[1:]
        if d == "wire":
            pack["wire"] = a[0]
        elif d == "bit_order":
            assert a[0] == "msb"
        elif d == "end":
            stack.pop()
        elif d == "kind":
            # the message's kinds, or the item kinds of a group body (0.8)
            (stack[-1].kinds if stack else pack["kinds"]).append({"name": a[0], "requires": [], "lines": []})
        elif d == "requires":
            (stack[-1].kinds if stack else pack["kinds"])[-1]["requires"] += a
        else:
            x = N(d, args=a)
            if d == "field":
                x.key, x.loc, x.tr = a[0], a[1], a[2]
                assert len(a) == 3
                if pack["wire"] == "bits":
                    x.n = int(a[1])
            elif d == "when":
                x.n, x.value = int(a[0]), int(a[1])
            elif d in ("pad", "align"):
                x.n = int(a[0])
            elif d == "presence":
                x.name, x.size = a[0], int(a[1])
            elif d == "if":
                x.conds = [(c.split(".")[0], int(c.split(".")[1])) for c in a]
            elif d == "count":
                x.name, x.n = a[0], int(a[1])
                x.plus = int(a[3]) if len(a) > 2 else 0
            elif d == "length":
                x.n, x.unit, x.plus, x.whole = int(a[0]), "bytes", 0, False
                i = 1
                while i < len(a):
                    if a[i] in ("bytes", "bits"):
                        x.unit = a[i]
                    elif a[i] == "plus":
                        x.plus = int(a[i + 1])
                        i += 1
                    elif a[i] == "whole":
                        x.whole = True
                    i += 1
            elif d == "group":
                x.key, x.kinds = a[0], []
                if pack["wire"] == "bits":
                    x.mode = a[1]
                    if a[1] == "count" and a[2].startswith("@"):
                        x.mode, x.ref = "ref", a[2][1:]
                    elif a[1] == "count":
                        x.n = int(a[2])
                else:
                    x.loc = a[1]
            into().append(x)
            if d in ("if", "opt", "group") or (d == "length" and not x.whole):
                x.body = []
                stack.append(x)
    return pack


# ------------------------------------------------------------------------------
# the model
# ------------------------------------------------------------------------------
KEY_TYPES = {}      # key -> string | int | float | list


def entity():
    return {"keys": {}, "lists": {}, "kind": None}


def model_of(ent, prefix=""):
    m = {prefix + k: str(v) for k, v in ent["keys"].items()}
    if ent.get("kind"):
        m[prefix + "@kind"] = ent["kind"][1]
    for name, items in ent["lists"].items():
        m[prefix + name + ".#"] = str(len(items))
        for i, item in enumerate(items):
            m.update(model_of(item, "%s%s[%d]." % (prefix, name, i)))
    return m


def choose_kind(kinds, ent, fmt):
    """0.5 Encode steps 1 and 2."""
    if ent.get("kind") and ent["kind"][0] == fmt:
        return next(k for k in kinds if k["name"] == ent["kind"][1])
    for k in kinds:
        if all(t in ent["keys"] or ent["lists"].get(t) for t in k["requires"]):
            return k
    raise Fail("no-kind", "no kind qualifies")


# ------------------------------------------------------------------------------
# bits, sequential, most significant bit first
# ------------------------------------------------------------------------------
def to_bits(hx):
    out = []
    for byte in bytes.fromhex(hx):
        out += [(byte >> (7 - i)) & 1 for i in range(8)]
    return out


def to_hex(bits):
    bits = bits + [0] * (-len(bits) % 8)
    return bytes(sum(b << (7 - k) for k, b in enumerate(bits[i:i + 8])) for i in range(0, len(bits), 8)).hex()


def vbits(v, n):
    if not 0 <= v < (1 << n):
        raise Fail("transform-encode", "%d does not fit %d bits" % (v, n))
    return [(v >> (n - 1 - k)) & 1 for k in range(n)]


def rbits(bits):
    return sum(b << (len(bits) - 1 - k) for k, b in enumerate(bits))


class Extent:
    """The message (length False) or a `length` block: where it ends and the
    bits an item of a `rest` group needs to start (8 for bytes, 1 for bits)."""

    def __init__(self, end, unit, length):
        self.end, self.unit, self.length = end, unit, length


PAST = object()     # a count line that lay at or past the end of a length extent


class Dec:
    def __init__(self, pack, hx):
        self.pack = pack
        self.bits = to_bits(hx)
        self.at = 0
        self.ext = [Extent(len(self.bits), 8, False)]

    def take(self, n):
        # past the input, past a whole length, or straddling an extent's end
        if self.at + n > self.ext[-1].end:
            raise Fail("malformed-wire", "a line runs past the end at bit %d" % self.at)
        self.at += n
        return rbits(self.bits[self.at - n:self.at])

    def at_end(self):
        """Rulings 7 and 21 of 0.8 with ruling 5 of 0.21: a line that starts at
        or after the end of a length extent reads as absent."""
        e = self.ext[-1]
        return e.length and self.at >= e.end

    def scope(self, common, kinds, sc, pres=None):
        pres, counts = dict(pres or {}), {}   # a kind continues the block of the common lines
        self.lines(common, sc, pres, counts)
        if kinds:
            start = self.at
            for kind in kinds:
                self.at = start
                whens = [w for w in kind["lines"] if w.d == "when"]
                if all(self.take(w.n) == w.value for w in whens):
                    sc["kind"] = (self.pack["name"], kind["name"])
                    self.lines([x for x in kind["lines"] if x.d != "when"], sc, pres, counts)
                    return
            raise Fail("no-kind", "no kind holds")

    def item(self, x, sc_list, pres):
        item = entity()
        self.scope(x.body, x.kinds, item, pres)
        sc_list.append(item)

    def lines(self, nodes, sc, pres, counts):
        """`pres` and `counts` are the names of the block, which this call
        extends; a nested block reads a copy."""
        for x in nodes:
            d = x.d
            if d == "field":
                if not self.at_end():
                    sc["keys"].setdefault(x.key, self.take(x.n))
            elif d == "pad":
                if not self.at_end():
                    self.take(x.n)
            elif d == "align":
                self.at = min(self.ext[-1].end, -(-self.at // x.n) * x.n)
            elif d == "presence":
                v = 0 if self.at_end() else self.take(x.size)
                pres[x.name] = {k + 1 for k in range(x.size) if (v >> (x.size - 1 - k)) & 1}
            elif d == "if":
                if all(bit in pres[name] for name, bit in x.conds):
                    self.lines(x.body, sc, dict(pres), dict(counts))
            elif d == "opt":
                if not self.at_end() and self.take(1):
                    self.lines(x.body, sc, dict(pres), dict(counts))
            elif d == "count":
                if self.at_end():
                    counts[x.name] = PAST
                else:
                    v = self.take(x.n)
                    if v < x.plus:
                        raise Fail("malformed-wire", "count %s: %d is below plus %d" % (x.name, v, x.plus))
                    counts[x.name] = v - x.plus
            elif d == "length":
                if self.at_end():
                    continue
                v = self.take(x.n) - x.plus
                if x.whole:
                    # ruling 8 of 0.8 and ruling 14 of 0.21
                    if 8 * v < self.at or 8 * v > len(self.bits):
                        raise Fail("malformed-wire", "whole length %d" % v)
                    self.ext[0].end = 8 * v
                    continue
                end = self.at + (8 * v if x.unit == "bytes" else v)
                if v < 0 or end > self.ext[-1].end:
                    raise Fail("malformed-wire", "the extent runs past its end")
                self.ext.append(Extent(end, 8 if x.unit == "bytes" else 1, True))
                self.lines(x.body, sc, dict(pres), dict(counts))
                self.ext.pop()
                self.at = end
            elif d == "group":
                items = []
                if x.mode == "rest":
                    # ruling 3: at the end of a length extent, present and empty
                    while self.ext[-1].end - self.at >= self.ext[-1].unit:
                        start = self.at
                        self.item(x, items, pres)
                        if self.at == start:
                            raise Fail("malformed-wire", "ruling 1: an item that reads no bits")
                elif self.at_end():
                    continue                    # ruling 7 of 0.8: absent
                elif x.mode == "ref":
                    n = counts[x.ref]
                    if n is PAST:
                        continue                # absent
                    if n > self.ext[-1].end - self.at:
                        raise Fail("malformed-wire", "ruling 20: count %d above the bits left" % n)
                    for _ in range(n):
                        self.item(x, items, pres)
                elif x.mode == "count":
                    n = self.take(x.n)
                    if n > self.ext[-1].end - self.at:
                        raise Fail("malformed-wire", "count above the bits left")
                    for _ in range(n):
                        self.item(x, items, pres)
                elif x.mode == "last":
                    while True:
                        flag = self.take(1)     # ruling 13: after the first, at the end, malformed
                        self.item(x, items, pres)
                        if flag:
                            break
                else:
                    raise ValueError(x.mode)
                sc["lists"][x.key] = items
            else:
                raise ValueError(d)


class Enc:
    """One layout of an entity. `self.out` is the buffer of the innermost
    extent; `self.starts` the start of each `rest` item written in it."""

    def __init__(self, pack):
        self.pack = pack
        self.out, self.starts = [], []
        self.live = {}              # count name -> [node, buffer, place, items written]
        self.wrote_rest = False     # a rest group written since the item began (rulings 10 and 35)

    def content(self, nodes, sc):
        """Ruling 22 of 0.8: a present key or a non-empty list at any depth of
        nested blocks. A count line is never content (ruling 18)."""
        for x in nodes:
            if x.d == "field" and x.key in sc["keys"]:
                return True
            if x.d == "group" and sc["lists"].get(x.key):
                return True
            if x.d in ("if", "opt", "length") and x.body and self.content(x.body, sc):
                return True
        return False

    def named(self, nodes, name, sc, on):
        """The bits of presence `name` whose `if` blocks have content; a
        message presence named in a group item is set by any item (ruling 12
        of 0.8)."""
        for x in nodes:
            if x.d == "if":
                if self.content(x.body, sc):
                    on.update(bit for n, bit in x.conds if n == name)
                self.named(x.body, name, sc, on)
            elif x.d in ("opt", "length") and x.body:
                self.named(x.body, name, sc, on)
            elif x.d == "group":
                for item in sc["lists"].get(x.key) or []:
                    self.named(x.body, name, item, on)

    def scope(self, common, kinds, sc):
        lines = list(common)
        kind = None
        if kinds:
            kind = choose_kind(kinds, sc, self.pack["name"])
            lines += kind["lines"]
        self.lines(lines, sc, {})

    def padded_check(self, end, unit):
        """Ruling 4: no `rest` item starts with fewer than `unit` bits left
        before the padded end of its extent."""
        for s in self.starts:
            if end - s < unit:
                raise Fail("transform-encode", "ruling 4: an item starts %d bits before the end" % (end - s))

    def item(self, x, item, pres):
        lines = list(x.body)
        if x.kinds:
            lines += choose_kind(x.kinds, item, self.pack["name"])["lines"]
        self.lines(lines, item, pres)

    def lines(self, nodes, sc, pres):
        pres = dict(pres)
        live = dict(self.live)      # ruling 24: a name declared here hides an outer one to the block's end
        mine = []                   # the counts this block declares
        for i, x in enumerate(nodes):
            d = x.d
            if d == "field":
                self.out += vbits(sc["keys"].get(x.key, 0), x.n)
            elif d == "when":
                self.out += vbits(x.value, x.n)
            elif d == "pad":
                self.out += [0] * x.n
            elif d == "align":
                self.out += [0] * (-len(self.out) % x.n)
            elif d == "presence":
                on = set()
                self.named(nodes[i + 1:], x.name, sc, on)
                self.out += [1 if k + 1 in on else 0 for k in range(x.size)]
                pres[x.name] = on
            elif d == "if":
                if all(bit in pres[name] for name, bit in x.conds):
                    self.lines(x.body, sc, pres)
            elif d == "opt":
                bit = self.content(x.body, sc)
                self.out.append(int(bit))
                if bit:
                    self.lines(x.body, sc, pres)
            elif d == "count":
                self.live[x.name] = entry = [x, self.out, len(self.out), None]
                mine.append(entry)
                self.out += [0] * x.n
            elif d == "length" and x.whole:
                self.whole = (x, len(self.out))
                self.out += [0] * x.n
            elif d == "length":
                outer, outer_starts, outer_wrote = self.out, self.starts, self.wrote_rest
                self.out, self.starts = [], []
                self.lines(x.body, sc, pres)
                if x.unit == "bytes":
                    self.out += [0] * (-len(self.out) % 8)
                    self.padded_check(len(self.out), 8)
                    v = len(self.out) // 8
                else:
                    self.padded_check(len(self.out), 1)
                    v = len(self.out)
                block = self.out
                self.out, self.starts, self.wrote_rest = outer, outer_starts, outer_wrote
                self.out += vbits(v + x.plus, x.n) + block
            elif d == "group":
                items = sc["lists"].get(x.key)
                if x.mode == "rest":
                    # rulings 10 and 35: no item before the last writes an
                    # inner rest group (outside a length block of the item)
                    for j, item in enumerate(items or []):
                        self.starts.append(len(self.out))
                        self.wrote_rest = False
                        self.item(x, item, pres)
                        if len(self.out) == self.starts[-1]:
                            raise Fail("transform-encode", "ruling 29: a rest item that writes no bits")
                        if self.wrote_rest and j < len(items) - 1:
                            raise Fail("transform-encode", "ruling 10: an item before the last writes the inner rest")
                    self.wrote_rest = True      # this group, for the item that holds it
                elif x.mode == "ref":
                    for item in items or []:
                        self.item(x, item, pres)
                    self.live[x.ref][3] = len(items or [])
                elif x.mode == "count":
                    self.out += vbits(len(items or []), x.n)
                    for item in items or []:
                        self.item(x, item, pres)
                elif x.mode == "last":
                    if not items:
                        raise Fail("transform-encode", "a `last` group with an absent or empty list")
                    for j, item in enumerate(items):
                        self.out.append(int(j == len(items) - 1))
                        self.item(x, item, pres)
                else:
                    raise ValueError(x.mode)
            else:
                raise ValueError(d)
        # counts declared in this block: items + n; an absent list or a group
        # not written, n (0.21, A count before other fields)
        for node, buf, at, items in mine:
            buf[at:at + node.n] = vbits((items or 0) + node.plus, node.n)
        self.live = live


def seq_decode(pack, hx):
    dec = Dec(pack, hx)
    ent = entity()
    dec.scope(pack["common"], pack["kinds"], ent)
    return ent


def seq_encode(pack, ent):
    enc = Enc(pack)
    enc.whole = None
    enc.scope(pack["common"], pack["kinds"], ent)
    out = enc.out + [0] * (-len(enc.out) % 8)
    enc.padded_check(len(out), 8)
    if enc.whole:
        x, at = enc.whole
        out[at:at + x.n] = vbits(len(out) // 8 + x.plus, x.n)
    return to_hex(out)


# ------------------------------------------------------------------------------
# json: members of the pack's lines, groups of objects or scalars
# ------------------------------------------------------------------------------
def json_scope(lines, obj, sc):
    for x in lines:
        if x.d == "field":
            v = obj if x.loc == "." else obj.get(x.loc) if isinstance(obj, dict) else None
            if v is not None:
                sc["keys"].setdefault(x.key, v)
        elif x.d == "group" and isinstance(obj, dict) and isinstance(obj.get(x.loc), list):
            items = []
            for el in obj[x.loc]:
                item = entity()
                json_scope(x.body, el, item)
                items.append(item)
            sc["lists"][x.key] = items


def json_decode(pack, text):
    ent = entity()
    json_scope(pack["common"], json.loads(text), ent)
    return ent


def json_value(x, v):
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
    return json_decode(pack, inp) if pack["wire"] == "json" else seq_decode(pack, inp)


def encode(pack, ent):
    return json_object(pack["common"], ent) if pack["wire"] == "json" else seq_encode(pack, ent)


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
        """`owner`, `frm`, `to`: pack names without `conformance-extents-`.
        The second computation runs and must agree."""
        owner, frm, to = PREFIX + owner, PREFIX + frm, PREFIX + to
        try:
            ent = decode(pack(frm), inp)
        except Fail as e:
            assert error == e.kind, (name, e.kind, e.why)
            ent = None
        if ent is not None:
            # 0.5: convert clears Entity.kind unless from == to. No context; no
            # derive line of probe reads or sets a key these packs map.
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
                elif v == "absent" and k.endswith(".#"):
                    assert k not in have, (name, k, have)
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
    R = "spec 0.21, A list to the end of its extent; "
    # ==========================================================================
    # conformance-extents-rest: z 8 | recs rest { x 8, y 8 }
    # ==========================================================================
    # 09 | 01 02 | 03 04: 32 bits after z, 16 and then 16 >= 8 left: two items;
    # then 0 left: the list ends.
    vec("rest", "two-items-to-the-end", "rest", "rest", "0901020304", "0901020304",
        model={"probe.z": "9", "probe.recs.#": "2", "probe.recs[0].probe.x": "1", "probe.recs[0].probe.y": "2",
               "probe.recs[1].probe.x": "3", "probe.recs[1].probe.y": "4"},
        ref=R + "items are read one after another while at least 8 bits remain in the message")
    vec("rest", "no-items-present-and-empty", "rest", "rest", "09", "09", model={"probe.recs.#": "0"},
        ref=R + "after z no bits remain: a list of no items is present and empty; encode writes nothing")
    # 09 | 01 02 | 03 ..: 8 bits left, a second item starts; x = 3 and y runs past the input
    vec("rest", "ruling-05-line-past-the-input-at-message-level", "rest", "rest", "09010203",
        error="malformed-wire",
        ref="spec 0.21 ruling 5: at message level, reading past the input stays malformed-wire (item 1's y)")
    vec("rest", "to-json-two-items", "rest", J, "0901020304", '{"z":9,"recs":[{"x":1,"y":2},{"x":3,"y":4}]}',
        ref=R + "the json pack writes z, then recs, in its line order")
    vec("rest", "to-json-empty", "rest", J, "09", '{"z":9,"recs":[]}', ref=R + "present and empty: []")
    vec(J, "to-rest-one-item", J, "rest", '{"z":9,"recs":[{"x":1,"y":2}]}', "090102",
        ref=R + "encode: the items back to back")
    vec(J, "to-rest-absent-list-writes-nothing", J, "rest", '{"z":9}', "09",
        ref=R + "an empty or absent list writes nothing")
    vec(J, "to-rest-item-without-y", J, "rest", '{"z":9,"recs":[{"x":1}]}', "090100",
        ref=R + "y absent in the item writes zero bits (0.8 Lines)")

    # ==========================================================================
    # conformance-extents-sub: x 5 | nums rest { val 4 }
    # ==========================================================================
    S = "spec 0.21 ruling 4 and A list to the end of its extent; "
    # 00 91 a0 = 00000 0001 0010 0011 0100000. x = 0; at bit 5, 19 left: val 1;
    # at 9, 15 left: 2; at 13, 11 left: 3; at 17, 7 left (< 8): padding
    # 0100000, skipped whatever its value. Encode: 5 + 12 = 17 bits, zero
    # padded to 24: 00000 0001 0010 0011 0000000 = 00 91 80.
    vec("sub", "ruling-04-sub-byte-items-and-ruling-17-padding", "sub", "sub", "0091a0", "009180",
        model={"probe.x": "0", "probe.nums.#": "3", "probe.nums[0].probe.val": "1",
               "probe.nums[1].probe.val": "2", "probe.nums[2].probe.val": "3"},
        ref=S + "the message is counted in bytes: an item is read while at least 8 bits remain; the 7 bits "
                "left are padding, ignored though not zero (ruling 17); encode writes them 0")
    # 00 91: at 5, 11 left: val 1; at 9, 7 left: padding. Encode 5 + 4 = 9 bits
    # -> 16: 00000 0001 0000000 = 00 80.
    vec("sub", "one-item-then-padding", "sub", "sub", "0091", "0080",
        model={"probe.nums.#": "1", "probe.nums[0].probe.val": "1"},
        ref=S + "after one item 7 bits remain: padding (ruling 17)")
    # f8 = 11111 000: x = 31, 3 bits left: no item
    vec("sub", "three-bits-left-no-item", "sub", "sub", "f8", "f8", model={"probe.x": "31", "probe.nums.#": "0"},
        ref=S + "3 bits after x are fewer than 8: present and empty")
    vec(J, "to-sub-three-items", J, "sub", '{"x":0,"nums":[1,2,3]}', "009180",
        ref=S + "items start at bits 5, 9 and 13 of 24: 19, 15 and 11 bits left")
    # 5 + 16 = 21 bits -> 24; item 3 starts at bit 17 with 7 bits left
    vec(J, "to-sub-ruling-04-four-items", J, "sub", '{"x":0,"nums":[1,2,3,4]}', error="transform-encode",
        ref=S + "the fourth item would start at bit 17 of 24, 7 bits before the byte-padded end: the "
                "output would decode three items")
    # 5 + 8 = 13 bits -> 16; item 1 starts at bit 9 with 7 bits left
    vec(J, "to-sub-ruling-04-two-items", J, "sub", '{"x":0,"nums":[1,2]}', error="transform-encode",
        ref=S + "the second item would start at bit 9 of 16, 7 bits before the byte-padded end")
    vec("sub", "to-json", "sub", J, "0091a0", '{"x":0,"nums":[1,2,3]}', ref=S + "three items")

    # ==========================================================================
    # conformance-extents-length: length 8 { recs rest { x 8, y 8 } } | z 8
    # ==========================================================================
    L = "spec 0.21 rulings 3 and 5; "
    vec("length", "two-items-in-the-block", "length", "length", "040102030409", "040102030409",
        model={"probe.recs.#": "2", "probe.recs[1].probe.y": "4", "probe.z": "9"},
        ref=L + "a block of 4 bytes holds two items; z follows the block")
    # length 3: block bits 8..32. item 0 at 8 (24 left): 1, 2; item 1 at 24
    # (8 left): x = 3, y starts at 32, the end: absent. Encode writes y as
    # zero bits: block 01 02 03 00, length 4.
    vec("length", "ruling-05-line-at-the-extent-end-absent", "length", "length", "0301020309", "040102030009",
        model={"probe.recs.#": "2", "probe.recs[1].probe.x": "3", "@absent": ["probe.recs[1].probe.y"],
               "probe.z": "9"},
        ref=L + "a line of an item that starts at the extent's end reads as absent; encode writes every line")
    vec("length", "ruling-03-empty-rest-at-the-end-of-a-length", "length", "length", "0009", "0009",
        model={"probe.recs.#": "0", "probe.z": "9"},
        ref=L + "ruling 3: a rest group at the end of a length extent is present and empty (amends ruling 7 "
                "of 0.8)")
    vec("length", "line-past-the-input-after-the-block", "length", "length", "020102", error="malformed-wire",
        ref=L + "z is a message-level line past the input (ruling 5, last sentence)")
    vec("length", "to-json-item-without-y", "length", J, "0301020309", '{"z":9,"recs":[{"x":1,"y":2},{"x":3}]}',
        ref=L + "y of item 1 is absent")
    vec(J, "to-length-absent-list", J, "length", '{"z":9}', "0009",
        ref=L + "an absent list writes nothing; the length counts 0 bytes")

    # ==========================================================================
    # conformance-extents-bits: length 8 bits { recs rest { x 4, y 4 } }
    # ==========================================================================
    B = "spec 0.21 ruling 5 and A list to the end of its extent (an extent counted in bits); "
    vec("bits", "two-items-in-16-bits", "bits", "bits", "101234", "101234",
        model={"probe.recs.#": "2", "probe.recs[0].probe.x": "1", "probe.recs[1].probe.y": "4"},
        ref=B + "16 bits: two items of 8")
    # length 12: block bits 8..20. item 0: 1, 2; at 16, 4 left (>= 1): item 1,
    # x = 3 (bits 16..19); y starts at 20, the end: absent. Encode: y as 4
    # zero bits, block 16 bits: 10 12 30.
    vec("bits", "ruling-05-y-at-the-end-absent", "bits", "bits", "0c1230", "101230",
        model={"probe.recs.#": "2", "probe.recs[1].probe.x": "3", "@absent": ["probe.recs[1].probe.y"]},
        ref=B + "a line starting at the extent's end reads as absent")
    # length 10: block bits 8..18; item 1 starts at 16 with 2 bits; x needs 4
    vec("bits", "ruling-05-x-straddles-the-end", "bits", "bits", "0a1230", error="malformed-wire",
        ref=B + "at least 1 bit remains, so item 1 is read; its x straddles the end")
    # length 14: block bits 8..22; item 1: x = 3 (16..19); y starts at 20 with 2 bits
    vec("bits", "ruling-05-y-straddles-the-end", "bits", "bits", "0e1230", error="malformed-wire",
        ref=B + "item 1's y starts 2 bits before the end and needs 4")
    # length 4: x = 1, y at the end; encode 8 bits: 08 10
    vec("bits", "one-x-then-the-end", "bits", "bits", "0410", "0810",
        model={"probe.recs.#": "1", "probe.recs[0].probe.x": "1", "@absent": ["probe.recs[0].probe.y"]},
        ref=B + "y starts at the end: absent; encode writes it as zero bits")
    vec("bits", "ruling-03-empty", "bits", "bits", "00", "00", model={"probe.recs.#": "0"},
        ref=B + "ruling 3: present and empty")
    vec(J, "to-bits-one-item", J, "bits", '{"recs":[{"x":1,"y":2}]}', "0812", ref=B + "8 bits")

    # ==========================================================================
    # conformance-extents-zero: presence p 1 | pad 7 | nums rest { if p.1 { val 8 } }
    # ==========================================================================
    Z = "spec 0.21 ruling 1; "
    vec("zero", "items-of-a-byte", "zero", "zero", "800506", "800506",
        model={"probe.nums.#": "2", "probe.nums[1].probe.val": "6"},
        ref=Z + "p.1 = 1: each item is val in 8 bits; encode sets p.1 from the items (ruling 12 of 0.8)")
    vec("zero", "ruling-01-an-item-that-reads-no-bits", "zero", "zero", "0005", error="malformed-wire",
        ref=Z + "p.1 = 0 and 8 bits remain: the item reads no bits")
    vec("zero", "no-bits-left-empty", "zero", "zero", "00", "00", model={"probe.nums.#": "0"},
        ref=Z + "no bits remain after the pad: no item is read, so none reads no bits")
    vec("zero", "presence-set-and-no-items", "zero", "zero", "80", "00", model={"probe.nums.#": "0"},
        ref=Z + "p.1 = 1 and no bits remain: present and empty; encode: no item has content, p.1 = 0")
    vec(J, "to-zero-one-item", J, "zero", '{"nums":[5]}', "8005", ref=Z + "val sets p.1")
    # [null]: one item with no keys (ruling 11 of 0.7). p.1 = 0; the item writes
    # nothing and starts at bit 8, the byte-padded end of the 8-bit message
    vec(J, "to-zero-ruling-04-item-with-no-bits", J, "zero", '{"nums":[null]}', error="transform-encode",
        ref="spec 0.21 ruling 4: the item would start with 0 bits left before the byte-padded end; the "
            "output would decode as an empty list")

    # ==========================================================================
    # conformance-extents-nested: items count 8 { length 8 { subs rest { val 8 } } qty 8 }
    # ==========================================================================
    T = "spec 0.21 ruling 10 (`rest` within a `length` block of the item's body) and ruling 3; "
    # 02 | 02 05 06 09 | 00 03: item 0: block of 2 bytes, subs 5, 6; qty 9.
    # item 1: block of 0 bytes, subs present and empty; qty 3
    vec("nested", "rest-in-a-length-of-each-item", "nested", "nested", "02020506090003", "02020506090003",
        model={"probe.items.#": "2", "probe.items[0].probe.subs.#": "2", "probe.items[0].probe.subs[1].probe.val": "6",
               "probe.items[0].probe.qty": "9", "probe.items[1].probe.subs.#": "0", "probe.items[1].probe.qty": "3"},
        ref=T + "the line after the block is not in the rest group's extent")
    vec("nested", "to-json", "nested", J, "02020506090003",
        '{"items":[{"qty":9,"subs":[{"val":5},{"val":6}]},{"qty":3,"subs":[]}]}', ref=T + "item 1's subs: []")
    vec(J, "to-nested-absent-subs", J, "nested", '{"items":[{"qty":3}]}', "010003",
        ref=T + "an absent list writes nothing; the length is 0")

    # ==========================================================================
    # conformance-extents-outer: items rest { qty 8, subs rest { val 8 } }
    # ==========================================================================
    O = "spec 0.21 ruling 10 (`rest` as the last line of an outer `rest` item); "
    vec("outer", "one-item-takes-the-message", "outer", "outer", "090506", "090506",
        model={"probe.items.#": "1", "probe.items[0].probe.qty": "9", "probe.items[0].probe.subs.#": "2"},
        ref=O + "the inner list runs to the end of the message, so the outer list has one item")
    vec("outer", "one-item-no-subs", "outer", "outer", "09", "09",
        model={"probe.items.#": "1", "probe.items[0].probe.subs.#": "0"}, ref=O + "subs present and empty")
    vec(J, "to-outer-ruling-10-two-items", J, "outer", '{"items":[{"qty":9},{"qty":3}]}', error="transform-encode",
        ref=O + "encoding an outer list of more than one item is transform-encode")
    vec(J, "to-outer-one-item", J, "outer", '{"items":[{"qty":9,"subs":[{"val":5}]}]}', "0905", ref=O + "one item")

    # ==========================================================================
    # conformance-extents-count: count n 2 | x 6 | nums count @n { val 8 } | y 8
    # ==========================================================================
    C = "spec 0.21, A count before other fields; "
    # 87 = 10 000111: n = 2, x = 7; nums 5, 6; y = 9
    vec("count", "count-then-a-field-then-the-list", "count", "count", "87050609", "87050609",
        model={"probe.x": "7", "probe.nums.#": "2", "probe.nums[0].probe.val": "5", "probe.y": "9"},
        ref=C + "the count is read at its line, the items when the group is reached")
    vec("count", "count-zero-present-and-empty", "count", "count", "0709", "0709",
        model={"probe.nums.#": "0", "probe.y": "9"}, ref=C + "n = 0: no items")
    vec(J, "to-count-absent-list-writes-n", J, "count", '{"x":7,"y":9}', "0709",
        ref=C + "an absent list writes n, here 0")
    # n = 3: 11 000111 = c7
    vec(J, "to-count-three-items", J, "count", '{"x":7,"nums":[1,2,3],"y":9}', "c701020309",
        ref=C + "the engine writes the count after the group is laid out, at the count's own place")
    vec(J, "to-count-four-items-do-not-fit", J, "count", '{"x":7,"nums":[1,2,3,4],"y":9}', error="transform-encode",
        ref=C + "4 is outside 0 ... 2^2 - 1")
    vec("count", "to-json", "count", J, "87050609", '{"x":7,"y":9,"nums":[5,6]}', ref=C + "json line order")

    # ==========================================================================
    # conformance-extents-plus: count n 8 plus -1 | x 8 | nums count @n { val 8 }
    # ==========================================================================
    P = "spec 0.21 ruling 7; "
    vec("plus", "plus-minus-one-two-items", "plus", "plus", "01aa0506", "01aa0506",
        model={"probe.x": "170", "probe.nums.#": "2", "probe.nums[0].probe.val": "5", "probe.nums[1].probe.val": "6"},
        ref=P + "the field is items + n with n = -1: 1 - (-1) = 2 items")
    vec("plus", "plus-minus-one-zero-is-one-item", "plus", "plus", "00aa05", "00aa05",
        model={"probe.nums.#": "1"}, ref=P + "0 - (-1) = 1 item")
    vec(J, "to-plus-empty-list", J, "plus", '{"x":170,"nums":[]}', error="transform-encode",
        ref=P + "0 items + (-1) = -1 is outside 0 ... 255 (absent and empty lists included)")
    vec(J, "to-plus-absent-list", J, "plus", '{"x":170}', error="transform-encode",
        ref=P + "an absent list writes n = -1: outside 0 ... 255")
    vec(J, "to-plus-three-items", J, "plus", '{"x":170,"nums":[5,6,7]}', "02aa050607", ref=P + "3 - 1 = 2")
    vec("plus", "to-json", "plus", J, "01aa0506", '{"x":170,"nums":[5,6]}', ref=P + "two items")

    # ==========================================================================
    # conformance-extents-plus1: count n 8 plus 1 | x 8 | nums count @n { val 8 }
    # ==========================================================================
    vec("plus1", "value-below-plus", "plus1", "plus1", "0007", error="malformed-wire",
        ref=C + "a value below n is malformed-wire, checked at the count line")
    vec("plus1", "value-equal-to-plus-empty", "plus1", "plus1", "0107", "0107", model={"probe.nums.#": "0"},
        ref=C + "1 - 1 = 0 items: present and empty")
    vec("plus1", "two-items", "plus1", "plus1", "03070506", "03070506", model={"probe.nums.#": "2"},
        ref=C + "3 - 1 = 2")
    vec(J, "to-plus1-absent-list", J, "plus1", '{"x":7}', "0107", ref=C + "an absent list writes n = 1")
    vec(J, "to-plus1-two-items", J, "plus1", '{"x":7,"nums":[5,6]}', "03070506", ref=C + "2 + 1 = 3")

    # ==========================================================================
    # conformance-extents-unreached: count n 8 plus 1 | opt { pad 7, nums count @n { val 8 } }
    # ==========================================================================
    U = "spec 0.21 ruling 6; "
    vec("unreached", "ruling-06-group-in-an-opt-not-read", "unreached", "unreached", "0500", "0100",
        model={"probe.nums.#": "absent"},
        ref=U + "n = 5 is read and the opt bit is 0: the list is absent and the count ignored; encode writes n = 1")
    vec("unreached", "ruling-06-below-plus-checked-first", "unreached", "unreached", "0000", error="malformed-wire",
        ref=U + "the value is ignored after the below-n check: 0 < 1")
    vec("unreached", "group-in-an-opt-read", "unreached", "unreached", "03800506", "03800506",
        model={"probe.nums.#": "2"}, ref=U + "opt bit 1: 3 - 1 = 2 items")
    # opt 1, n = 0: present and empty. Encode: an empty list is no content (ruling 18 with ruling 5 of 0.8),
    # the opt bit is 0; the count holds 0 + 1
    vec("unreached", "ruling-18-empty-list-in-an-opt", "unreached", "unreached", "0180", "0100",
        model={"probe.nums.#": "0"},
        ref="spec 0.21 ruling 18: ruling 5 of 0.8 extends to `count @`: a present, empty list does not set the "
            "opt bit and decodes back as absent")
    vec(J, "to-unreached-two-items", J, "unreached", '{"nums":[5,6]}', "03800506", ref=U + "the list sets the opt bit")
    vec(J, "to-unreached-absent", J, "unreached", "{}", "0100", ref=U + "encode writes n")

    # ==========================================================================
    # conformance-extents-past: length 8 { count n 8, x 8, nums count @n { val 8 } } | y 8
    # ==========================================================================
    X = "spec 0.21 ruling 6 and A count before other fields (Decode); "
    # length 2: n = 1, x = 7; the group starts at the end: absent. Encode
    # writes every line: n = 0 (absent list), x = 7; block 2 bytes.
    vec("past", "ruling-06-group-past-the-extent-end", "past", "past", "02010709", "02000709",
        model={"probe.x": "7", "probe.nums.#": "absent", "probe.y": "9"},
        ref=X + "the group lies at the end of the length extent: the list is absent, the count ignored; "
                "encode writes n for the absent list")
    # length 1: n = 5; x starts at the end: absent; group absent. Encode: n = 0, x zero bits
    vec("past", "field-and-group-past-the-extent-end", "past", "past", "010509", "02000009",
        model={"probe.nums.#": "absent", "@absent": ["probe.x"], "probe.y": "9"},
        ref=X + "a count of 5 whose group is not reached is not compared with the bits left (ruling 20)")
    vec("past", "count-line-at-the-extent-end", "past", "past", "0009", "02000009",
        model={"probe.nums.#": "absent", "probe.y": "9"},
        ref=X + "if the count line lay at or past the end of a length extent, the group is absent")
    vec("past", "group-in-the-extent", "past", "past", "0301070509", "0301070509",
        model={"probe.nums.#": "1", "probe.y": "9"}, ref=X + "n = 1 within the block")
    vec("past", "to-json-absent-list", "past", J, "02010709", '{"x":7,"y":9}', ref=X + "the list is absent")

    # ==========================================================================
    # conformance-extents-bitsleft: count n 8 | presence p 1 | pad 7 | x 8 | nums count @n { if p.1 { val 8 } }
    # ==========================================================================
    W = "spec 0.21 ruling 20 with ruling 14 of 0.8; "
    vec("bitsleft", "ruling-20-count-above-the-bits-left-at-the-group", "bitsleft", "bitsleft", "010007",
        error="malformed-wire",
        ref=W + "16 bits remain at the count line, none at the group: a count of 1 is larger than the bits left")
    # at the group 8 bits are left (the byte 00 after x): 1 <= 8; the item
    # reads nothing (p.1 = 0); the last byte is input beyond the last line.
    # Encode: one item, p.1 = 0
    vec("bitsleft", "ruling-20-count-within-the-bits-left-at-the-group", "bitsleft", "bitsleft", "01000700",
        "010007", model={"probe.nums.#": "1", "@absent": ["probe.nums[0].probe.val"]},
        ref=W + "8 bits remain at the group; an item of a count group may read no bits (ruling 1 is about "
                "rest); input beyond the last line is ignored (ruling 9 of 0.8)")
    vec("bitsleft", "count-zero", "bitsleft", "bitsleft", "000007", "000007", model={"probe.nums.#": "0"},
        ref=W + "no item")
    vec("bitsleft", "two-items", "bitsleft", "bitsleft", "0280070506", "0280070506",
        model={"probe.nums.#": "2", "probe.nums[1].probe.val": "6"}, ref=W + "16 bits left at the group")

    # ==========================================================================
    # conformance-extents-kinds: count n 8 | kind b when 2: x 8, nums @n | kind a when 1: nums @n
    # ==========================================================================
    K = "spec 0.21 ruling 2; "
    vec("kinds", "ruling-02-header-count-kind-a", "kinds", "kinds", "02010506", "02010506",
        model={"@kind": "a", "probe.nums.#": "2", "probe.nums[1].probe.val": "6"},
        ref=K + "a header count in common lines may be referenced by the list in every kind; when 1: a")
    vec("kinds", "ruling-02-header-count-kind-b", "kinds", "kinds", "0102aa07", "0102aa07",
        model={"@kind": "b", "probe.x": "170", "probe.nums.#": "1", "probe.nums[0].probe.val": "7"},
        ref=K + "when 2: b; x lies between the count and the list")
    vec(J, "to-kinds-b-by-requires", J, "kinds", '{"x":170,"nums":[7]}', "0102aa07",
        ref=K + "requires probe.x: b, the first kind in pack order that qualifies")
    vec(J, "to-kinds-a", J, "kinds", '{"nums":[5,6]}', "02010506", ref=K + "no x: a, which has no requires")
    vec("kinds", "to-json", "kinds", J, "0102aa07", '{"x":170,"nums":[7]}', ref=K + "kind b")

    # ==========================================================================
    # conformance-extents-item: items count 8 { count n 4, qty 4, subs count @n { val 8 } }
    # ==========================================================================
    I = "spec 0.21 ruling 9; "
    # 02 | 29 = 0010 1001: n = 2, qty = 9; 05 06 | 03 = 0000 0011: n = 0, qty = 3
    vec("item", "ruling-09-count-in-an-item-body", "item", "item", "0229050603", "0229050603",
        model={"probe.items.#": "2", "probe.items[0].probe.qty": "9", "probe.items[0].probe.subs.#": "2",
               "probe.items[0].probe.subs[1].probe.val": "6", "probe.items[1].probe.qty": "3",
               "probe.items[1].probe.subs.#": "0"},
        ref=I + "a count line and its reference in one group body")
    vec(J, "to-item", J, "item", '{"items":[{"qty":9,"subs":[{"val":5},{"val":6}]},{"qty":3}]}', "0229050603",
        ref=I + "item 1's subs is absent: n = 0")
    vec(J, "to-item-sixteen-subs-do-not-fit", J, "item",
        '{"items":[{"qty":1,"subs":[%s]}]}' % ",".join(['{"val":0}'] * 16), error="transform-encode",
        ref=I + "16 is outside 0 ... 2^4 - 1")

    # ==========================================================================
    # conformance-extents-last: nums last { val 7 }
    # ==========================================================================
    A = "spec 0.21, The last-item flag; "
    # 05 = 0 0000101: not last, 5; 86 = 1 0000110: last, 6
    vec("last", "two-items", "last", "last", "0586", "0586",
        model={"probe.nums.#": "2", "probe.nums[0].probe.val": "5", "probe.nums[1].probe.val": "6"},
        ref=A + "the bit before each item is 1 for the last item and 0 for the others")
    vec("last", "one-item", "last", "last", "85", "85", model={"probe.nums.#": "1"}, ref=A + "1 0000101")
    vec("last", "no-last-item-before-the-input-ends", "last", "last", "05", error="malformed-wire",
        ref=A + "the bit before a second item lies past the input")
    vec("last", "input-after-the-last-item-ignored", "last", "last", "058607", "0586",
        model={"probe.nums.#": "2"}, ref=A + "input beyond the last line is ignored (ruling 9 of 0.8)")
    vec(J, "to-last-three-items", J, "last", '{"nums":[5,6,7]}', "050687", ref=A + "0 0000101 0 0000110 1 0000111")
    vec(J, "to-last-empty-list", J, "last", '{"nums":[]}', error="transform-encode",
        ref=A + "a list has at least one item on the wire; an empty list outside an if or opt block")
    vec(J, "to-last-absent-list", J, "last", "{}", error="transform-encode", ref=A + "an absent list")
    vec("last", "to-json", "last", J, "0586", '{"nums":[5,6]}', ref=A + "two items")

    # ==========================================================================
    # conformance-extents-last-length: length 8 { nums last { val 7 } } | x 8
    # ==========================================================================
    E = "spec 0.21 ruling 13; "
    vec("last-length", "two-items-in-the-block", "last-length", "last-length", "02058609", "02058609",
        model={"probe.nums.#": "2", "probe.x": "9"}, ref=E + "the last item ends the list at the block's end")
    vec("last-length", "ruling-13-later-indicator-at-the-extent-end", "last-length", "last-length", "010509",
        error="malformed-wire", ref=E + "item 0 says another follows; that item's bit starts at the extent end")
    vec("last-length", "ruling-13-first-indicator-at-the-extent-end", "last-length", J, "0009", '{"x":9}',
        model={"probe.nums.#": "absent", "probe.x": "9"},
        ref=E + "the first indicator at the extent end: ruling 34 of 0.8, an absent list")
    vec("last-length", "absent-list-does-not-encode", "last-length", "last-length", "0009",
        error="transform-encode", model={"probe.nums.#": "absent"},
        ref=E + "decode gives an absent list, which a `last` group outside an if or opt block cannot write")
    vec("last-length", "one-item", "last-length", "last-length", "018509", "018509", model={"probe.nums.#": "1"},
        ref=E + "one item, last bit 1")

    # ==========================================================================
    # conformance-extents-last-opt: opt { pad 7, nums last { val 7 } }
    # ==========================================================================
    vec("last-opt", "two-items", "last-opt", "last-opt", "800586", "800586", model={"probe.nums.#": "2"},
        ref=A + "the opt bit is 1")
    vec("last-opt", "absent", "last-opt", "last-opt", "00", "00", model={"probe.nums.#": "absent"},
        ref=A + "the opt bit is 0")
    vec(J, "to-last-opt-empty-list", J, "last-opt", '{"nums":[]}', "00",
        ref=A + "an empty list in an opt block: the block is not written (as for more, 0.8)")
    vec(J, "to-last-opt-one-item", J, "last-opt", '{"nums":[5]}', "8085", ref=A + "1 0000000 1 0000101")

    # ==========================================================================
    # conformance-extents-whole: length 8 whole | nums rest { val 8 }
    # ==========================================================================
    H = "spec 0.21 ruling 14; "
    vec("whole", "ruling-14-whole-length-ends-the-message-extent", "whole", "whole", "0305060708", "030506",
        model={"probe.nums.#": "2", "probe.nums[1].probe.val": "6"},
        ref=H + "the stated 3 bytes end the extent: items 05 06; 07 08 lie beyond and are ignored")
    vec("whole", "whole-length-one-byte-empty", "whole", "whole", "01", "01", model={"probe.nums.#": "0"},
        ref=H + "no bits after the length byte")
    vec("whole", "input-shorter-than-the-whole-length", "whole", "whole", "040506", error="malformed-wire",
        ref=H + "input shorter than it is malformed-wire (0.8 Lengths)")
    vec("whole", "whole-length-shorter-than-what-was-read", "whole", "whole", "0005", error="malformed-wire",
        ref=H + "a stated whole length shorter than what was already read (ruling 8 of 0.8)")
    vec(J, "to-whole-three-items", J, "whole", '{"nums":[5,6,7]}', "04050607", ref=H + "1 + 3 bytes")
    vec(J, "to-whole-absent", J, "whole", "{}", "01", ref=H + "an absent list writes nothing")

    # ==========================================================================
    # conformance-extents-if: presence p 1 | if p.1 { pad 7, nums rest { val 8 } }
    # ==========================================================================
    F = "spec 0.21 ruling 18 with ruling 5 of 0.8; "
    vec("if", "items-in-the-if", "if", "if", "800506", "800506", model={"probe.nums.#": "2"}, ref=F + "p.1 = 1")
    vec("if", "ruling-18-empty-rest-in-an-if-writes-bit-0", "if", "if", "80", "00", model={"probe.nums.#": "0"},
        ref=F + "p.1 = 1 and no bits remain: present and empty; a present, empty list does not set the bit")
    vec("if", "if-not-read-absent", "if", "if", "00", "00", model={"probe.nums.#": "absent"},
        ref=F + "ruling 3: a rest group whose block is not read stays absent")
    vec(J, "to-if-empty-list", J, "if", '{"nums":[]}', "00", ref=F + "the bit is 0")
    vec(J, "to-if-one-item", J, "if", '{"nums":[5]}', "8005", ref=F + "1 0000000 00000101")

    # ==========================================================================
    # conformance-extents-optcount: opt { count n 8, nums count @n { val 8 } }
    # ==========================================================================
    Q = "spec 0.21 ruling 18; "
    vec(J, "to-optcount-absent", J, "optcount", "{}", "00", ref=Q + "a count line is never content: the opt bit is 0")
    vec(J, "to-optcount-empty", J, "optcount", '{"nums":[]}', "00",
        ref=Q + "ruling 5 of 0.8 extends to count @: an empty list does not set the bit")
    # 1 | 00000001 | 00000101 | 0000000 = 80 82 80
    vec(J, "to-optcount-one-item", J, "optcount", '{"nums":[5]}', "808280", ref=Q + "the list sets the bit")
    vec("optcount", "one-item", "optcount", "optcount", "808280", "808280", model={"probe.nums.#": "1"},
        ref=Q + "opt 1, n = 1, val 5")
    vec("optcount", "absent", "optcount", "optcount", "00", "00", model={"probe.nums.#": "absent"},
        ref=Q + "opt 0")

    # ==========================================================================
    # conformance-extents-json-locators: nums at `rest`, names at `last`
    # ==========================================================================
    G = "spec 0.21 ruling 8: on json, `rest` and `last` after a list name are the group locator; "
    vec("json-locators", "ruling-08-rest-and-last-are-members", "json-locators", "json-locators",
        '{"rest":[1,2],"last":["a"]}', '{"rest":[1,2],"last":["a"]}',
        model={"probe.nums.#": "2", "probe.nums[1].probe.val": "2", "probe.names[0].probe.tag": "a"},
        ref=G + "the arrays at the members rest and last")
    vec("json-locators", "ruling-08-member-order-of-the-pack", "json-locators", "json-locators",
        '{"last":[],"rest":[3]}', '{"rest":[3],"last":[]}', model={"probe.names.#": "0"},
        ref=G + "canonical output in line order; an empty list writes []")

    # ==========================================================================
    # rulings 21 to 28
    # ==========================================================================
    # conformance-extents-hide: count n 8 | opt { count n 4, pad 3, recs count @n { x 8 } } | align 8 |
    # nums count @n { val 8 }
    V = "spec 0.21 ruling 24; "
    # 02 | 88 = 1 0001 000: opt 1, inner n = 1 | 0a | (align: at bit 24) | 05 06
    vec("hide", "ruling-24-inner-count-names-the-inner-list", "hide", "hide", "02880a0506", "02880a0506",
        model={"probe.recs.#": "1", "probe.recs[0].probe.x": "10", "probe.nums.#": "2", "probe.nums[1].probe.val": "6"},
        ref=V + "the n declared in the opt block hides the outer n there: recs takes 1 item, nums after the "
                "block takes the outer 2")
    vec("hide", "opt-not-read", "hide", "hide", "02000506", "02000506",
        model={"probe.recs.#": "absent", "probe.nums.#": "2"}, ref=V + "opt 0, align to bit 16, nums 5 6")
    vec(J, "to-hide-both-lists", J, "hide", '{"recs":[{"x":10}],"nums":[5,6]}', "02880a0506",
        ref=V + "each count holds the items of the list that references it")
    # outer n = 0 (nums absent) | 90 = 1 0010 000 | 0a 0b
    vec(J, "to-hide-recs-only", J, "hide", '{"recs":[{"x":10},{"x":11}]}', "00900a0b",
        ref=V + "the inner n = 2, the outer n = 0 for an absent list")
    vec(J, "to-hide-nums-only", J, "hide", '{"nums":[5]}', "010005", ref=V + "opt 0, then align, then nums")

    # conformance-extents-kindcounts: kind a when 1 requires x: x 8, count n 8, nums @n |
    # kind b when 2: count n 4, pad 4, nums @n
    Y = "spec 0.21 ruling 25; "
    vec("kindcounts", "ruling-25-kind-a", "kindcounts", "kindcounts", "01030105", "01030105",
        model={"@kind": "a", "probe.x": "3", "probe.nums.#": "1", "probe.nums[0].probe.val": "5"},
        ref=Y + "each kind is its own block for count names; a's n is 8 bits")
    # 02 | 10 = 0001 0000: n = 1 | 07
    vec("kindcounts", "ruling-25-kind-b", "kindcounts", "kindcounts", "021007", "021007",
        model={"@kind": "b", "probe.nums.#": "1", "probe.nums[0].probe.val": "7"}, ref=Y + "b's n is 4 bits")
    vec(J, "to-kindcounts-a", J, "kindcounts", '{"x":3,"nums":[5]}', "01030105", ref=Y + "requires x: a")
    vec(J, "to-kindcounts-b", J, "kindcounts", '{"nums":[7]}', "021007", ref=Y + "no x: b")

    # conformance-extents-itemkind: items count 8 { kind a when 1: length 8 { subs rest { val 8 } }, qty 8 |
    # kind b when 2: qty 8 }
    D = "spec 0.21 ruling 27; "
    # 02 | 01 02 05 06 09 | 02 03
    vec("itemkind", "ruling-27-rest-in-an-item-kind", "itemkind", "itemkind", "0201020506090203",
        "0201020506090203",
        model={"probe.items.#": "2", "probe.items[0].@kind": "a", "probe.items[0].probe.subs.#": "2",
               "probe.items[0].probe.qty": "9", "probe.items[1].@kind": "b", "probe.items[1].probe.qty": "3",
               "probe.items[1].probe.subs.#": "absent"},
        ref=D + "the rest group is the last line of the length block of kind a's body (ruling 10)")
    vec("itemkind", "ruling-27-empty-rest-in-an-item-kind", "itemkind", "itemkind", "01010009", "01010009",
        model={"probe.items[0].@kind": "a", "probe.items[0].probe.subs.#": "0"}, ref=D + "ruling 3 in the item kind")
    vec("itemkind", "to-json", "itemkind", J, "0201020506090203",
        '{"items":[{"qty":9,"subs":[{"val":5},{"val":6}]},{"qty":3}]}', ref=D + "item b has no subs")
    vec(J, "to-itemkind-a", J, "itemkind", '{"items":[{"qty":9,"subs":[{"val":5}]}]}', "0101010509",
        ref=D + "no requires: the first item kind, a")
    vec("itemkind", "item-of-no-kind", "itemkind", "itemkind", "0103", error="no-kind",
        ref=D + "an item that is no-kind fails the whole decode (ruling 11 of 0.20)")

    # conformance-extents-last-if: presence p 1 | if p.1 { x 7, nums last { val 7 } }
    M = "spec 0.21 ruling 28; "
    vec(J, "to-last-if-ruling-28-empty-list-in-a-written-if", J, "last-if", '{"x":3,"nums":[]}',
        error="transform-encode", ref=M + "x sets p.1, so the block is written; its last group has no item")
    vec(J, "to-last-if-absent-list-in-a-written-if", J, "last-if", '{"x":3}', error="transform-encode",
        ref=M + "with ruling 6 of 0.8: an absent list in a block written for another reason")
    # 1 0000011 | 1 0000101
    vec(J, "to-last-if-one-item", J, "last-if", '{"x":3,"nums":[5]}', "8385", ref=M + "p.1, x = 3, last item 5")
    vec(J, "to-last-if-empty-list-block-not-written", J, "last-if", '{"nums":[]}', "00",
        ref=M + "no content: p.1 = 0 and the block is not written")
    vec("last-if", "one-item", "last-if", "last-if", "8385", "8385", model={"probe.x": "3", "probe.nums.#": "1"},
        ref=M + "p.1 = 1")
    vec("last-if", "block-not-read", "last-if", "last-if", "00", "00", model={"probe.nums.#": "absent"},
        ref=M + "p.1 = 0")
    vec("last-if", "first-indicator-past-the-input", "last-if", "last-if", "83", error="malformed-wire",
        ref=M + "at message level the first last-item bit lies past the input (ruling 5)")

    # conformance-extents-bits-zero: presence p 1 | pad 7 | length 8 bits { nums rest { if p.1 { val 8 } } }
    Bz = "spec 0.21 ruling 21 in an extent counted in bits; "
    vec(J, "to-bits-zero-ruling-21-item-with-no-bits", J, "bits-zero", '{"nums":[null]}', error="transform-encode",
        ref=Bz + "p.1 = 0; the item writes no bits and starts at the end of the 0-bit block: 0 bits left, "
                 "fewer than the 1 an item of a bits extent needs")
    vec(J, "to-bits-zero-one-item", J, "bits-zero", '{"nums":[5]}', "800805", ref=Bz + "8 bits")
    vec(J, "to-bits-zero-empty", J, "bits-zero", '{"nums":[]}', "0000", ref=Bz + "an empty list writes nothing")
    vec("bits-zero", "one-item", "bits-zero", "bits-zero", "800805", "800805", model={"probe.nums.#": "1"},
        ref=Bz + "p.1 = 1")
    vec("bits-zero", "ruling-01-in-a-bits-extent", "bits-zero", "bits-zero", "0001", error="malformed-wire",
        ref=Bz + "1 bit remains, so an item is read; with p.1 = 0 it reads no bits (ruling 1)")
    vec("bits-zero", "empty-block", "bits-zero", "bits-zero", "0000", "0000", model={"probe.nums.#": "0"},
        ref=Bz + "ruling 3")

    # ==========================================================================
    # rulings 29 to 34
    # ==========================================================================
    # conformance-extents-walk: presence p 1 | pad 7 | length 8 { x 8, if p.1 { nums rest { val 8 } } } |
    # length 8 { y 8, opt { pad 7, recs rest { x 8 } } }
    Wk = "spec 0.21 ruling 31; "
    # 80 | 01 07 | 01 09: block 1 ends after x; the if is walked, p.1 holds:
    # nums present and empty. Block 2 ends after y; the opt there reads as
    # absent: recs absent. Encode: an empty list is no content, p.1 = 0;
    # block 2 = y and the opt bit 0, 9 bits padded to 2 bytes
    vec("walk", "ruling-31-if-walked-and-opt-absent-at-the-extent-end", "walk", "walk", "8001070109",
        "000107020900", model={"probe.x": "7", "probe.nums.#": "0", "probe.y": "9", "probe.recs.#": "absent"},
        ref=Wk + "an if at the end of a length extent is still walked, so the rest inside it is present and "
                 "empty; an opt there reads as absent and its block is not read")
    vec("walk", "if-not-read-and-opt-bit-0", "walk", "walk", "000107020900", "000107020900",
        model={"probe.nums.#": "absent", "probe.recs.#": "absent"}, ref=Wk + "p.1 = 0; opt bit 0")
    # block 2 of 2 bytes: y, opt 1, pad 7, then the end: recs present and empty (ruling 3)
    vec("walk", "opt-read-rest-at-the-end", "walk", "walk", "80020705020980", "80020705020900",
        model={"probe.nums.#": "1", "probe.recs.#": "0"},
        ref=Wk + "the opt bit lies inside the extent: its rest is at the end, present and empty; encode: the "
                 "empty list does not set the opt bit")
    vec(J, "to-walk-both-lists", J, "walk", '{"x":7,"y":9,"nums":[5],"recs":[{"x":3}]}', "8002070503098003",
        ref=Wk + "block 2: y, opt 1, pad 7, x = 3: 3 bytes")

    # conformance-extents-offset: x 2 | length 4 { nums rest { val 6 } }
    Of = "spec 0.21 ruling 34; "
    # 00 | 0011 | 000001 000010 000011 | 000000 (the block padded to 3 bytes
    # from its first bit, bit 6) | 00 (the message padded) = 0c 10 83 00.
    # Item 2 starts 12 bits before the block's padded end (bit 30); measured
    # from the message start the padded end would be bit 24 and leave 6.
    vec(J, "to-offset-ruling-34-padded-end-from-the-block-start", J, "offset", '{"x":0,"nums":[1,2,3]}', "0c108300",
        ref=Of + "the byte-padded end is measured from the first bit of the block")
    vec("offset", "three-items-in-a-block-at-bit-6", "offset", "offset", "0c108300", "0c108300",
        model={"probe.x": "0", "probe.nums.#": "3", "probe.nums[2].probe.val": "3"},
        ref=Of + "block bits 6..30: items at 6, 12 and 18; at 24, 6 bits remain: padding")
    vec(J, "to-offset-four-items", J, "offset", '{"x":0,"nums":[1,2,3,4]}', error="transform-encode",
        ref=Of + "24 bits of items, block padded end 24 bits from its start; item 3 starts 6 bits before it")

    # conformance-extents-unreached-minus: count n 8 plus -1 | opt { pad 7, nums count @n { val 8 } }
    Um = "spec 0.21 ruling 30; "
    vec(J, "to-unreached-minus-absent", J, "unreached-minus", "{}", error="transform-encode",
        ref=Um + "the group is never reached: the count holds n = -1, which does not fit")
    vec(J, "to-unreached-minus-empty", J, "unreached-minus", '{"nums":[]}', error="transform-encode",
        ref=Um + "an empty list does not set the opt bit; 0 + (-1) does not fit")
    vec(J, "to-unreached-minus-one-item", J, "unreached-minus", '{"nums":[5]}', "008005", ref=Um + "1 - 1 = 0")
    vec("unreached-minus", "one-item", "unreached-minus", "unreached-minus", "008005", "008005",
        model={"probe.nums.#": "1"}, ref=Um + "0 - (-1) = 1 item")
    vec("unreached-minus", "absent-list-does-not-encode", "unreached-minus", "unreached-minus", "0000",
        error="transform-encode", model={"probe.nums.#": "absent"},
        ref=Um + "decode: opt 0, the list is absent; encode: the count holds -1")

    # conformance-extents-outerkind: items rest { kind a when 1 requires qty: qty 8 |
    # kind b when 2: subs rest { val 8 } }
    Ok = "spec 0.21 ruling 10 with ruling 27; "
    # 01 09 | 01 03 | 02 05 06: a, a, then b, whose subs run to the end
    vec("outerkind", "ruling-10-a-a-b-round-trip", "outerkind", "outerkind", "01090103020506", "01090103020506",
        model={"probe.items.#": "3", "probe.items[0].@kind": "a", "probe.items[0].probe.qty": "9",
               "probe.items[1].@kind": "a", "probe.items[1].probe.qty": "3", "probe.items[2].@kind": "b",
               "probe.items[2].probe.subs.#": "2", "probe.items[2].probe.subs[1].probe.val": "6"},
        ref=Ok + "only the last item is of the kind that ends in the inner rest")
    # 02 05 01 09: b's subs take 05 01 09; one item
    vec("outerkind", "b-first-takes-the-rest", "outerkind", "outerkind", "02050109", "02050109",
        model={"probe.items.#": "1", "probe.items[0].@kind": "b", "probe.items[0].probe.subs.#": "3"},
        ref=Ok + "an item of kind b reads to the end of the message")
    vec(J, "to-outerkind-a-a-b", J, "outerkind", '{"items":[{"qty":9},{"qty":3},{"subs":[{"val":5}]}]}',
        "010901030205", ref=Ok + "items with qty select a (requires), the last has none and selects b")
    vec(J, "to-outerkind-ruling-10-b-then-a", J, "outerkind", '{"items":[{"subs":[{"val":5}]},{"qty":9}]}',
        error="transform-encode", ref=Ok + "an item before the last is of kind b, which ends in the inner rest")
    vec(J, "to-outerkind-b-alone-empty", J, "outerkind", '{"items":[{}]}', "02",
        ref=Ok + "no qty: b; an absent subs writes nothing")

    # conformance-extents-outerif: items rest { presence p 1, pad 7, if p.1 { subs rest { val 8 } } }
    Oi = "spec 0.21 rulings 35 and 39; "
    # 00 | 80 05 06: item 0 has p.1 = 0 and is one byte; item 1 has p.1 = 1 and subs 5 6 to the end
    vec("outerif", "ruling-35-item-without-the-inner-rest-then-another", "outerif", "outerif", "00800506", "00800506",
        model={"probe.items.#": "2", "probe.items[0].probe.subs.#": "absent", "probe.items[1].probe.subs.#": "2",
               "probe.items[1].probe.subs[0].probe.val": "5"},
        ref=Oi + "item 0 does not write the inner rest (its if is not written), so it may precede another item")
    vec(J, "to-outerif-ruling-35-first-item-without-subs", J, "outerif", '{"items":[{},{"subs":[{"val":5}]}]}',
        "008005", ref=Oi + "item 0: p.1 = 0; item 1: p.1 = 1, subs 5")
    vec(J, "to-outerif-ruling-35-first-item-with-subs", J, "outerif", '{"items":[{"subs":[{"val":5}]},{}]}',
        error="transform-encode", ref=Oi + "item 0 writes the inner rest and another item follows it")
    # an empty subs is no content: p.1 = 0, the if and its rest are not written
    vec(J, "to-outerif-ruling-35-empty-subs-not-written", J, "outerif", '{"items":[{"subs":[]},{}]}', "0000",
        ref=Oi + "an empty list does not set p.1, so item 0 does not write the inner rest")
    vec("outerif", "ruling-39-rest-last-in-an-if-of-the-item", "outerif", "outerif", "800506", "800506",
        model={"probe.items.#": "1", "probe.items[0].probe.subs.#": "2"},
        ref=Oi + "a rest nested in an if of an outer rest item, with no wire line after it in the item")

    # ==========================================================================
    # load vectors from 900
    # ==========================================================================
    core = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key time_ms int ms\n")
    probe = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey x int -\nkey y int -\n"
             "key z int -\nkey val int -\nkey qty int -\nlist nums \"a list\"\nlist recs \"a list\"\n"
             "list items \"a list\"\nlist subs \"a list\"\n")
    head = 'format probe\nversion 0.21.0\ndistribution public\nsource "probe"\nuses probe\n'
    js, xm, pb = head + "wire json\n", head + "wire xml\nroot msg\n", head + "wire protobuf\n"
    fixed = head + "wire bits\nword_bytes 1\n"
    seq = head + "wire bits\nlayout sequential\n"
    lnum = [899]

    def load(name, text, error="bad-directive", gtcheck_kind=None):
        # gtcheck_kind: what gtcheck gives where it does not yet name the
        # 0.11 load errors (`bad-locator`); the vector states the spec's error
        lnum[0] += 1
        full = "%d-extents-%s" % (lnum[0], name)
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

    nv = "  field probe.val 8 uint\nend\n"            # the rest of a group of nums
    nv2 = "    field probe.val 8 uint\n  end\n"       # the same, one block deeper
    nref = "group probe.nums count @n\n" + nv
    # the forms by wire and layout
    load("count-line-on-json", js + "count n 8\n")
    load("count-line-on-a-fixed-layout", fixed + "count n 8\n")
    load("rest-on-a-fixed-layout", fixed + "group probe.nums rest\n  field probe.val 0:0:8 uint\nend\n")
    load("last-on-a-fixed-layout", fixed + "group probe.nums last\n  field probe.val 0:0:8 uint\nend\n")
    load("ruling-08-rest-and-last-are-json-locators-load", js + "group probe.nums rest\n  field probe.val . int\n"
         "end\ngroup probe.recs last\n  field probe.x x int\nend\n", None)
    load("ruling-08-rest-is-an-xml-locator-loads", xm + "group probe.recs rest\n  field probe.x @x int\nend\n", None)
    load("ruling-08-rest-is-not-a-protobuf-path", pb + "group probe.nums rest\n  field probe.val . pvarint\nend\n")
    load("count-reference-on-json", js + "group probe.nums count @n\n  field probe.val . int\nend\n")
    # rest: the last line of its extent (ruling 11)
    sr = seq + "field probe.x 8 uint\ngroup probe.nums rest\n" + nv
    load("rest-as-the-last-line-loads", sr, None)
    load("ruling-11-field-after-rest", sr + "field probe.y 8 uint\n")
    load("ruling-11-pad-after-rest", sr + "pad 8\n")
    load("ruling-11-align-after-rest", sr + "align 8\n")
    load("ruling-11-const-after-rest", sr + "const 8 1\n")
    load("ruling-11-opt-after-rest", sr + "opt\n  field probe.y 8 uint\nend\n")
    load("ruling-11-default-after-rest-loads", sr + "default probe.y 1\n", None)
    load("ruling-11-requires-after-rest-in-a-kind-loads", seq + "field probe.x 8 uint\nkind a\nwhen 8 1\n"
         "group probe.nums rest\n" + nv + "requires probe.x\n", None)
    load("ruling-11-rest-at-the-end-of-a-kind-then-another-kind-loads", seq + "kind a\nwhen 8 1\n"
         "group probe.nums rest\n" + nv + "kind b\nwhen 8 2\nfield probe.x 8 uint\n", None)
    load("ruling-11-rest-in-common-lines-then-a-kind-line", seq + "group probe.nums rest\n" + nv +
         "kind a\nfield probe.x 8 uint\n")
    load("ruling-11-rest-in-an-if-then-a-line-after-it", seq + "presence p 1\nif p.1\n  group probe.nums rest\n" +
         nv2 + "end\nfield probe.x 8 uint\n")
    sw = (seq + "field probe.x 8 uint\nswitch probe.x\n  case 1\n    group probe.nums rest\n"
          "      field probe.val 8 uint\n    end\n  case 2\n    field probe.y 8 uint\nend\n")
    load("ruling-11-rest-in-one-case-and-lines-in-another-load", sw, None)
    load("ruling-11-rest-in-a-case-then-a-line-after-the-switch", sw + "field probe.z 8 uint\n")
    load("rest-in-a-length-then-a-line-in-the-length", seq + "length 8\n  group probe.nums rest\n" + nv2 +
         "  field probe.x 8 uint\nend\n")
    load("rest-in-a-length-then-a-line-after-the-length-loads", seq + "length 8\n  group probe.nums rest\n" + nv2 +
         "end\nfield probe.x 8 uint\n", None)
    load("rest-after-a-whole-length-loads", seq + "length 8 whole\ngroup probe.nums rest\n" + nv, None)
    # rest inside an item (ruling 10)
    it = "  field probe.qty 8 uint\n  group probe.subs rest\n" + nv2 + "end\n"
    load("ruling-10-rest-in-a-counted-item", seq + "group probe.items count 8\n" + it)
    load("ruling-10-rest-in-a-while-item", seq + "group probe.items while\n" + it)
    load("ruling-10-rest-in-an-if-of-a-counted-item", seq + "group probe.items count 8\n  presence p 1\n"
         "  if p.1\n    group probe.subs rest\n      field probe.val 8 uint\n    end\n  end\nend\n")
    load("ruling-10-rest-in-a-length-of-a-counted-item-loads", seq + "group probe.items count 8\n  length 8\n"
         "    group probe.subs rest\n      field probe.val 8 uint\n    end\n  end\n  field probe.qty 8 uint\nend\n", None)
    load("ruling-10-rest-last-in-an-item-of-a-rest-group-loads", seq + "group probe.items rest\n" + it, None)
    load("ruling-10-rest-not-last-in-an-item-of-a-rest-group", seq + "group probe.items rest\n"
         "  group probe.subs rest\n" + nv2 + "  field probe.qty 8 uint\nend\n")
    # two modes on one group, and the form of a reference
    load("two-modes-rest-last", seq + "group probe.nums rest last\n" + nv)
    load("two-modes-last-rest", seq + "group probe.nums last rest\n" + nv)
    load("two-modes-count-reference-and-rest", seq + "count n 8\ngroup probe.nums count @n rest\n" + nv)
    load("two-modes-count-length-and-rest", seq + "group probe.nums count 8 rest\n" + nv)
    load("two-modes-while-and-last", seq + "group probe.nums while last\n" + nv)
    load("count-reference-with-no-name", seq + "count n 8\ngroup probe.nums count @\n" + nv)
    # the count line
    load("count-length-zero", seq + "count n 0\n" + nref)
    load("count-length-65", seq + "count n 65\n" + nref)
    load("count-lengths-1-and-64-load", seq + "count n 1\ncount m 64\n" + nref +
         "group probe.recs count @m\n  field probe.x 8 uint\nend\n", None)
    load("count-without-a-length", seq + "count n\n" + nref)
    load("ruling-16-plus-with-a-plus-sign", seq + "count n 8 plus +2\n" + nref)
    load("ruling-16-plus-with-leading-zeros-loads", seq + "count n 8 plus 007\n" + nref, None)
    load("ruling-16-plus-at-the-ends-of-signed-64-bits-loads", seq + "count n 8 plus 9223372036854775807\n"
         "count m 8 plus -9223372036854775808\n" + nref + "group probe.recs count @m\n  field probe.x 8 uint\nend\n",
         None)
    load("ruling-16-plus-above-signed-64-bits", seq + "count n 8 plus 9223372036854775808\n" + nref)
    load("ruling-16-plus-below-signed-64-bits", seq + "count n 8 plus -9223372036854775809\n" + nref)
    load("plus-without-a-value", seq + "count n 8 plus\n" + nref)
    load("plus-twice", seq + "count n 8 plus 1 plus 2\n" + nref)
    load("plus-with-a-fraction", seq + "count n 8 plus 1.5\n" + nref)
    load("plus-in-hex", seq + "count n 8 plus 0x2\n" + nref)
    load("count-line-with-via", seq + "map t 1 2\ncount n 8 via t\n" + nref)
    load("count-line-with-swap", seq + "count n 8 swap\n" + nref)
    load("count-line-with-bytes", seq + "count n 8 bytes\n" + nref)
    load("count-line-with-an-option-after-plus", seq + "count n 8 plus 1 swap\n" + nref)
    # names (rulings 2, 9, 12 and 15)
    load("count-named-twice-in-one-block", seq + "count n 8\ncount n 8\n" + nref)
    load("ruling-15-presence-and-count-of-one-name", seq + "presence n 1\ncount n 8\n" + nref)
    load("ruling-15-count-reference-naming-a-presence", seq + "presence p 8\ngroup probe.nums count @p\n" + nv)
    load("ruling-15-if-naming-a-count", seq + "count n 8\n" + nref + "if n.1\n  field probe.x 8 uint\nend\n")
    load("count-reference-to-no-count", seq + nref)
    load("count-reference-before-its-count-line", seq + nref + "count n 8\n")
    load("count-with-no-reference", seq + "count n 8\nfield probe.x 8 uint\n")
    load("ruling-02-two-references-in-one-path", seq + "count n 8\n" + nref +
         "group probe.recs count @n\n  field probe.x 8 uint\nend\n")
    load("ruling-02-two-references-in-separate-ifs", seq + "count n 8\npresence p 2\nif p.1\n"
         "  group probe.nums count @n\n" + nv2 + "end\nif p.2\n  group probe.nums count @n\n" + nv2 + "end\n")
    load("ruling-02-header-count-referenced-in-each-kind-loads", seq + "count n 8\nkind a\nwhen 8 1\n" + nref +
         "kind b\nwhen 8 2\nfield probe.x 8 uint\n" + nref, None)
    load("ruling-02-header-count-not-referenced-in-one-kind", seq + "count n 8\nkind a\nwhen 8 1\n" + nref +
         "kind b\nwhen 8 2\nfield probe.x 8 uint\n")
    cs = (seq + "field probe.x 8 uint\ncount n 8\nswitch probe.x\n  case 1\n    group probe.nums count @n\n"
          "      field probe.val 8 uint\n    end\n  case 2\n")
    load("ruling-02-count-referenced-in-every-case-loads", cs + "    group probe.recs count @n\n"
         "      field probe.x 8 uint\n    end\nend\n", None)
    load("ruling-02-count-not-referenced-in-the-else", cs + "    group probe.recs count @n\n"
         "      field probe.x 8 uint\n    end\n  else\nend\n")
    load("ruling-02-count-not-referenced-in-one-case", cs + "    field probe.y 8 uint\nend\n")
    load("ruling-09-reference-inside-a-group-body", seq + "count n 8\ngroup probe.items count 8\n"
         "  group probe.subs count @n\n" + nv2 + "end\n")
    load("ruling-09-count-and-reference-in-one-item-body-load", seq + "group probe.items count 8\n  count n 4\n"
         "  field probe.qty 4 uint\n  group probe.subs count @n\n" + nv2 + "end\n", None)
    load("ruling-09-count-in-an-item-reference-in-a-nested-item", seq + "group probe.items count 8\n  count n 8\n"
         "  group probe.subs count 8\n    group probe.nums count @n\n      field probe.val 8 uint\n    end\n"
         "  end\nend\n")
    load("ruling-09-reference-in-nested-blocks-of-the-body-loads", seq + "count n 8\nopt\n  length 8\n"
         "    group probe.nums count @n\n      field probe.val 8 uint\n    end\n  end\nend\n", None)
    load("ruling-09-reference-in-a-case-of-the-body-loads", seq + "field probe.x 8 uint\ncount n 8\n"
         "switch probe.x\n  case 1\n    group probe.nums count @n\n      field probe.val 8 uint\n    end\nend\n", None)
    load("ruling-12-count-in-an-if-not-visible-after-it", seq + "presence p 1\nif p.1\n  count n 8\nend\n" + nref)
    load("ruling-12-count-in-a-length-not-visible-after-it", seq + "length 8\n  count n 8\nend\n" + nref)
    load("ruling-12-count-and-reference-in-one-if-load", seq + "presence p 1\nif p.1\n  count n 8\n"
         "  group probe.nums count @n\n" + nv2 + "end\n", None)
    load("count-of-one-kind-not-visible-in-another", seq + "kind a\nwhen 8 1\ncount n 8\nfield probe.x 8 uint\n"
         "kind b\nwhen 8 2\n" + nref)
    load("count-and-reference-in-one-case-load", seq + "field probe.x 8 uint\nswitch probe.x\n  case 1\n"
         "    count n 8\n    group probe.nums count @n\n      field probe.val 8 uint\n    end\nend\n", None)
    # rulings 24 to 27, from 729
    hide = (seq + "count n 8\nopt\n  count n 4\n  group probe.recs count @n\n    field probe.x 8 uint\n  end\nend\n")
    load("ruling-24-nested-count-hides-the-outer-loads", hide + nref, None)
    load("ruling-24-outer-count-referenced-only-where-it-is-hidden", hide)
    load("ruling-24-count-name-with-a-dot", seq + "count n.a 8\ngroup probe.nums count @n.a\n" + nv)
    load("ruling-24-count-name-with-a-bang", seq + "count !n 8\ngroup probe.nums count @!n\n" + nv)
    load("ruling-24-count-name-with-an-at", seq + "count @n 8\ngroup probe.nums count @@n\n" + nv)
    load("ruling-25-two-kinds-declare-one-count-name-load", seq + "kind a\nwhen 8 1\ncount n 8\n" + nref +
         "kind b\nwhen 8 2\ncount n 4\npad 4\n" + nref, None)
    pr = seq + "presence p 1\npad 7\nfield probe.x 8 uint\ngroup probe.nums rest\n" + nv
    load("ruling-26-empty-if-after-rest-loads", pr + "if p.1\nend\n", None)
    load("ruling-26-if-with-only-a-default-after-rest-loads", pr + "if p.1\n  default probe.y 1\nend\n", None)
    load("ruling-26-switch-with-empty-cases-after-rest-loads", pr + "switch probe.x\n  case 1\n  else\nend\n", None)
    load("ruling-26-if-with-a-field-after-rest", pr + "if p.1\n  field probe.y 8 uint\nend\n")
    load("ruling-27-rest-in-an-item-kind-without-a-length", seq + "group probe.items count 8\n  kind a\n"
         "  when 8 1\n  group probe.subs rest\n" + nv2 + "  kind b\n  when 8 2\nend\n")
    load("ruling-27-rest-in-a-length-of-an-item-kind-loads", seq + "group probe.items count 8\n  kind a\n"
         "  when 8 1\n  length 8\n    group probe.subs rest\n      field probe.val 8 uint\n    end\n  end\n"
         "  field probe.qty 8 uint\n  kind b\n  when 8 2\n  field probe.qty 8 uint\nend\n", None)
    load("ruling-27-rest-last-in-an-item-kind-of-a-rest-group-loads", seq + "group probe.items rest\n  kind a\n"
         "  when 8 1\n  field probe.qty 8 uint\n  kind b\n  when 8 2\n  group probe.subs rest\n" + nv2 + "end\n", None)
    load("ruling-27-line-after-rest-in-an-item-kind", seq + "group probe.items rest\n  kind a\n  when 8 1\n"
         "  group probe.subs rest\n" + nv2 + "  field probe.qty 8 uint\n  kind b\n  when 8 2\nend\n")
    # rulings 32 and 33, from 743
    load("ruling-32-rest-in-common-lines-then-a-kind-with-only-when", seq + "group probe.nums rest\n" + nv +
         "kind a\nwhen 8 1\n")
    load("ruling-32-empty-chain-after-rest-loads", sr + "chain\nend\n", None)
    load("ruling-32-presence-after-rest", sr + "presence q 1\n")
    load("ruling-33-references-in-an-if-and-an-opt-are-two", seq + "count n 8\npresence p 1\nif p.1\n"
         "  group probe.nums count @n\n" + nv2 + "end\nopt\n  group probe.recs count @n\n"
         "    field probe.x 8 uint\n  end\nend\n")
    # rulings 36 to 39, from 747
    load("ruling-36-common-count-and-a-count-of-one-name-in-a-kind", seq + "count n 8\nkind a\nwhen 8 1\n"
         "count n 8\n" + nref)
    load("ruling-36-common-count-and-a-presence-of-one-name-in-a-kind", seq + "count n 8\nkind a\nwhen 8 1\n"
         "presence n 1\n" + nref)
    load("ruling-37-xml-group-locator-an-attribute", xm + "group probe.recs @a\n  field probe.x @x int\nend\n")
    load("ruling-38-rest-in-a-chain-part-then-fx", seq + "chain\n  field probe.x 7 uint\n  group probe.nums rest\n"
         "    field probe.val 8 uint\n  end\n  fx\n  field probe.y 8 uint\nend\n")
    load("ruling-39-rest-in-the-last-chain-part-loads", seq + "chain\n  field probe.x 7 uint\n  fx\n"
         "  group probe.nums rest\n    field probe.val 8 uint\n  end\nend\n", None)
    load("ruling-39-rest-last-in-an-if-of-an-outer-rest-item-loads", seq + "group probe.items rest\n"
         "  presence p 1\n  pad 7\n  if p.1\n    group probe.subs rest\n      field probe.val 8 uint\n    end\n"
         "  end\nend\n", None)
    load("ruling-39-rest-last-in-an-opt-of-an-outer-rest-item-loads", seq + "group probe.items rest\n"
         "  field probe.qty 7 uint\n  opt\n    group probe.subs rest\n      field probe.val 8 uint\n    end\n"
         "  end\nend\n", None)
    load("ruling-39-rest-in-an-if-of-an-outer-rest-item-then-a-line", seq + "group probe.items rest\n"
         "  presence p 1\n  if p.1\n    group probe.subs rest\n      field probe.val 8 uint\n    end\n"
         "  end\n  field probe.qty 7 uint\nend\n")
    # ruling 44: on protobuf only `rest` and `last` take ruling 37; another
    # step that is not digits stays bad-locator (0.11 5a)
    load("ruling-44-a-protobuf-group-step-not-digits-is-bad-locator",
         pb + "group probe.nums abc\n  field probe.val . pvarint\nend\n", "bad-locator",
         gtcheck_kind="bad-directive")
    load("ruling-44-protobuf-rest-is-checked-after-the-file",
         pb + "group probe.nums rest\n  field probe.val . pvarint\nend\nbogus\n", "unknown-directive",
         gtcheck_kind="bad-directive")
    return written


def main(argv=None):
    return genio.vector_main("conformance-extents-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
