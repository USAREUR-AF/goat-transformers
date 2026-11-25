#!/usr/bin/env python3
"""Write the vectors of spec 0.17, gated fields on a fixed layout: the packs
`conformance-gates-*` and the load vectors from 640.

Every expected value here is worked out by hand from the spec text (Version
0.17 and the sections it refers to: 0.5 kinds and bit order, 0.6 defaults and
several lines for one key, 0.7 groups, 0.9 sentinels, 0.14 six-bit armor) and
the pack layouts;
the hand working is the comment above each vector. It is checked against a
second computation: `Gates` below reads the committed pack.def files with its
own small parser and applies the 0.17 rules (Decode, and Encode steps 1 to 6)
to the bits. It imports nothing from an engine and nothing calls an engine.

Two rules of the text as ruled after the first draft of these vectors:
  - Encode step 4: gates read the bits of steps 2 and 3 and the bits an
    outside default or sentinel wrote where no gate value replaced them;
    bits nothing wrote read 0 wherever they lie, so a block that is not open
    but whose gate holds on those bits is held, written with its sentinels
    and defaults, and counts toward the length.
  - Ruling 7: on one bit, const, when and counts win over field lines,
    between which the earlier line wins (a line written from a default
    included); a gate value is written over a bit only a default or a
    sentinel wrote, and not on a bit a line with a present key covers, even
    when an earlier default line won it; a sentinel is last.
  - Ruling 10: a line of a block that is not held raises no encode error.

Inputs: the pack.def files of the `conformance-gates-*` packs. Writes, under
--out, the vector files named above. With --check nothing is written and the
exit status is 1 when a committed file differs from what this script writes.

Usage: python3 -I tools/gen/conformance-gates-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402


class Fail(Exception):
    """A conversion that fails with an error kind of the spec; `why` says which
    rule, so a vector that expects an error is checked for its reason too."""

    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


# ------------------------------------------------------------------------------
# a parser of the pack lines these packs use
# ------------------------------------------------------------------------------
def parse_pack(text):
    pack = {"msb": False, "wb": 1, "wire": None, "armor": "hex", "common": [], "kinds": []}
    stack = []
    for raw in text.splitlines():
        toks = []
        for t in raw.split():
            if t.startswith("#"):
                break
            toks.append(t)
        if not toks or toks[0] in ("format", "version", "distribution", "source", "uses"):
            continue
        d, a = toks[0], toks[1:]
        if d == "wire":
            pack["wire"] = a[0]
            continue
        if d == "bit_order":
            pack["msb"] = a[0] == "msb"
            continue
        if d == "armor":
            pack["armor"] = a[0]
            continue
        if d == "word_bytes":
            pack["wb"] = int(a[0])
            continue
        if d == "kind":
            pack["kinds"].append({"name": a[0], "requires": [], "lines": []})
            continue
        if d == "requires":
            pack["kinds"][-1]["requires"] += a
            continue
        if d == "end":
            stack.pop()
            continue
        into = stack[-1]["body"] if stack else (pack["kinds"][-1]["lines"] if pack["kinds"] else pack["common"])

        def bits_loc(text):
            w, p, n = (int(x) for x in text.split(":"))
            return w * pack["wb"] * 8 + p, n

        if d == "field":
            line = {"d": "field", "key": a[0], "absent": None, "optional": False}
            if pack["wire"] == "bits":
                line["start"], line["n"] = bits_loc(a[1])
            else:
                line["member"] = a[1]
            name, *arg = a[2].split(":")
            line["tr"], line["factor"] = name, (float(arg[0]) if arg else None)
            i = 3
            while i < len(a):
                if a[i] == "absent":
                    line["absent"] = [int(v) for v in a[i + 1].split(",")]
                    i += 1
                elif a[i] == "optional":
                    line["optional"] = True
                else:
                    raise ValueError("option %s" % a[i])
                i += 1
            into.append(line)
        elif d == "default":
            into.append({"d": "default", "key": a[0], "value": int(a[1])})
        elif d in ("when", "const"):
            start, n = bits_loc(a[0])
            into.append({"d": d, "start": start, "n": n, "value": int(a[1])})
        elif d == "if":
            neg = a[0].startswith("!")
            start, n = bits_loc(a[0].lstrip("!"))
            block = {"d": "gate", "neg": neg, "start": start, "n": n,
                     "values": [int(v) for v in a[1].split(",")], "body": []}
            into.append(block)
            stack.append(block)
        elif d == "group":
            block = {"d": "group", "list": a[0], "body": []}
            if pack["wire"] == "bits":
                w, p = (int(x) for x in a[1].split(":"))
                block["start"], block["item"] = w * pack["wb"] * 8 + p, int(a[3])
                block["count"] = bits_loc(a[5])
            else:
                block["member"] = a[1]
            into.append(block)
            stack.append(block)
        else:
            raise ValueError("directive %s" % d)
    return pack


# ------------------------------------------------------------------------------
# bits: message bit i is bit i mod 8 of byte i div 8 (lsb) or bit 7 - i mod 8
# (msb); a value's first bit is its lowest (lsb) or its highest (msb)
# ------------------------------------------------------------------------------
def to_bits(hx, msb):
    out = []
    for byte in bytes.fromhex(hx):
        out += [(byte >> (7 - i)) & 1 if msb else (byte >> i) & 1 for i in range(8)]
    return out


def to_hex(bits, msb):
    out = bytearray()
    for i in range(0, len(bits), 8):
        out.append(sum(b << (7 - k) if msb else b << k for k, b in enumerate(bits[i:i + 8])))
    return out.hex()


# six-bit armor (0.14): each character six bits, most significant first; `0`
# (0x30) to `W` (0x57) stand for c - 0x30, `` ` `` (0x60) to `w` (0x77) for
# c - 0x38. Encode pads the L bits with zeros to a multiple of 6.
def armor_to_bits(text):
    out = []
    for c in text:
        o = ord(c)
        if 0x30 <= o <= 0x57:
            v = o - 0x30
        elif 0x60 <= o <= 0x77:
            v = o - 0x38
        else:
            raise Fail("malformed-wire", "character %r is not six-bit armor" % c)
        out += [(v >> (5 - k)) & 1 for k in range(6)]
    return out


def bits_to_armor(bits):
    bits = bits + [0] * (-len(bits) % 6)
    out = []
    for i in range(0, len(bits), 6):
        v = sum(b << (5 - k) for k, b in enumerate(bits[i:i + 6]))
        out.append(chr(0x30 + v if v < 40 else 0x38 + v))
    return "".join(out)


def value_bits(v, n, msb):
    return [(v >> (n - 1 - k)) & 1 if msb else (v >> k) & 1 for k in range(n)]


def read(bits, start, n, msb):
    return sum(b << (n - 1 - k) if msb else b << k for k, b in enumerate(bits[start:start + n]))


def text_of(v):
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v)


def round_away(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def end(line):
    return line["start"] + line["n"]


def gates_in(lines):
    """Every gate block of `lines`, outer blocks before the blocks nested in
    them, in line order."""
    for line in lines:
        if line["d"] == "gate":
            yield line
            yield from gates_in(line["body"])


def matches(gate, v):
    listed = v in gate["values"]
    return not listed if gate["neg"] else listed


# ------------------------------------------------------------------------------
# the 0.17 rules on one scope of a fixed layout: the message, or one item
# ------------------------------------------------------------------------------
class Gates:
    def __init__(self, pack):
        self.pack, self.msb = pack, pack["msb"]
        self.armor = pack["armor"] == "sixbit"

    # -- decode ----------------------------------------------------------------
    def held_on(self, lines, bits, limit, base=0):
        """{id(gate): holds} by the Decode rule: a gate any of whose bits lies
        beyond `limit` does not hold, nor does its `!` form; a nested gate is
        evaluated only when its outer block holds."""
        held = {}

        def visit(nodes, outer):
            for line in nodes:
                if line["d"] != "gate":
                    continue
                h = outer and base + end(line) <= limit and matches(
                    line, read(bits, base + line["start"], line["n"], self.msb))
                held[id(line)] = h
                visit(line["body"], h)
        visit(lines, True)
        return held

    def flat(self, lines, held, chain=()):
        """(line, is the line outside blocks or in held blocks, enclosing
        gates) for every field, default, when and const, in line order."""
        for line in lines:
            if line["d"] == "gate":
                yield from self.flat(line["body"], held, chain + (line,))
            elif line["d"] != "group":
                yield line, all(held[id(g)] for g in chain), chain

    def decode_scope(self, lines, bits, base, limit):
        held = self.held_on(lines, bits, limit, base)
        need = 0
        for line, active, _ in self.flat(lines, held):
            if active and line["d"] != "default" and not line.get("optional"):
                need = max(need, base + end(line))
        for g in [x for x in lines if x["d"] == "group"]:
            need = max(need, end({"start": g["count"][0], "n": g["count"][1]}))
        if limit < need:
            raise Fail("malformed-wire", "the input is shorter than the message")
        keys, lists = {}, {}
        for line, active, _ in self.flat(lines, held):
            if line["d"] != "field" or not active or line["key"] in keys:
                continue
            if base + end(line) > limit:            # optional, beyond the input
                continue
            raw = read(bits, base + line["start"], line["n"], self.msb)
            if line["absent"] and raw in line["absent"]:
                continue
            keys[line["key"]] = raw * line["factor"] if line["tr"] == "uscale" else raw
        for g in [x for x in lines if x["d"] == "group"]:
            count = read(bits, g["count"][0], g["count"][1], self.msb)
            if g["start"] + count * g["item"] > limit:
                raise Fail("malformed-wire", "the items run past the input")
            items = []
            for i in range(count):
                at = g["start"] + i * g["item"]
                item, _, _ = self.decode_scope(g["body"], bits, at, at + g["item"])
                items.append(item)
            lists[g["list"]] = items
        return keys, lists, held

    def decode(self, hx):
        bits = armor_to_bits(hx) if self.armor else to_bits(hx, self.msb)
        lines, kind = self.pack["common"], None
        if self.pack["kinds"]:
            for k in self.pack["kinds"]:
                if all(end(w) <= len(bits) and read(bits, w["start"], w["n"], self.msb) == w["value"]
                       for w in k["lines"] if w["d"] == "when"):
                    kind = k
                    break
            if kind is None:
                raise Fail("no-kind", "no kind holds")
            lines = lines + kind["lines"]
        keys, lists, _ = self.decode_scope(lines, bits, 0, len(bits))
        return keys, lists, kind and kind["name"]

    # -- encode ----------------------------------------------------------------
    def encode_raw(self, line, x):
        if line["tr"] == "uscale":
            v = round_away(x / line["factor"])
            if not 0 <= v < 1 << line["n"]:
                raise Fail("transform-encode", "uscale out of range")
            return v
        return x & ((1 << line["n"]) - 1)

    def encode_scope(self, lines, ent, lists, item_bits=None):
        msb = self.msb
        gates = list(gates_in(lines))
        outside = [x for x in lines if x["d"] not in ("gate", "group")]
        groups = [x for x in lines if x["d"] == "group"]

        def is_open(g):                                          # step 1
            return any(x["d"] == "field" and x["key"] in ent for x in g["body"]) or \
                any(is_open(x) for x in g["body"] if x["d"] == "gate")

        # step 2: lines outside any block; a present key, const, when, count
        written = {}
        for x in outside:
            if x["d"] == "field" and x["key"] in ent:
                for k, b in enumerate(value_bits(self.encode_raw(x, ent[x["key"]]), x["n"], msb)):
                    written.setdefault(x["start"] + k, b)         # the earlier line wins
        for x in outside:
            if x["d"] in ("const", "when"):
                for k, b in enumerate(value_bits(x["value"], x["n"], msb)):
                    written[x["start"] + k] = b
        for g in groups:
            c = len(lists.get(g["list"], []))
            for k, b in enumerate(value_bits(c, g["count"][1], msb)):
                written[g["count"][0] + k] = b

        # step 3: gate values, outer blocks first
        given = {}
        for g in gates:
            if not is_open(g) or any(g["start"] + k in written for k in range(g["n"])):
                continue
            if g["neg"]:
                v = next((v for v in range(len(g["values"]) + 1) if v not in g["values"]), None)
                if v is not None and v >> g["n"]:
                    v = None
            else:
                v = g["values"][0]
            if v is not None:
                given[id(g)] = v
                for k, b in enumerate(value_bits(v, g["n"], msb)):
                    written[g["start"] + k] = b

        # step 4: held blocks, on the bits of steps 2 and 3, and the bits an
        # outside default or sentinel wrote where no gate value replaced them
        common_defaults = {x["key"]: x["value"] for x in lines if x["d"] == "default"}
        seen = dict(written)
        soft = set()
        for x in outside:
            if x["d"] != "field" or x["key"] in ent:
                continue
            v = common_defaults.get(x["key"])
            raw = self.encode_raw(x, v) if v is not None else (x["absent"][0] if x["absent"] else None)
            if raw is None:
                continue
            for k, b in enumerate(value_bits(raw, x["n"], msb)):
                if x["start"] + k not in written and x["start"] + k not in soft:
                    seen[x["start"] + k] = b
                    soft.add(x["start"] + k)
        limit0 = max([end(x) for x in outside if x["d"] != "default"]
                     + [end({"start": g["count"][0], "n": g["count"][1]}) for g in groups] + [0])
        held = {}

        def visit(nodes, outer, limit):
            for g in nodes:
                if g["d"] != "gate":
                    continue
                if not outer:
                    h = False
                else:
                    v = sum(seen.get(g["start"] + k, 0) << (g["n"] - 1 - k if msb else k)
                            for k in range(g["n"]))
                    h = matches(g, v)
                held[id(g)] = h
                inner = max([limit] + [end(x) for x in g["body"] if x["d"] in ("field", "const")])
                visit(g["body"], h, inner)
        visit(lines, True, limit0)

        # step 5: the output
        def default_of(line, chain):
            for g in reversed(chain):                        # ruling 5: innermost wins
                for x in g["body"]:
                    if x["d"] == "default" and x["key"] == line["key"]:
                        return x["value"]
            return common_defaults.get(line["key"])

        active = [(x, chain) for x, a, chain in self.flat(lines, held) if a]
        length = max([end(x) for x, _ in active if x["d"] != "default"]
                     + [end(g) for g in gates if held[id(g)]]
                     + [g["start"] + len(lists.get(g["list"], [])) * g["item"] for g in groups]
                     + [limit0, 0])
        if item_bits is not None:
            length = item_bits
        elif self.armor:
            # 0.14 and ruling 14 of 0.17: L, not rounded to a word, counts an
            # optional field only when it is written (its key, a default or
            # a sentinel); the output is read back padded to six bits
            length = max([end(x) for x, chain in active if x["d"] in ("const", "when") or (
                x["d"] == "field" and (not x["optional"] or x["key"] in ent or x["absent"]
                                       or default_of(x, chain) is not None))]
                         + [end(g) for g in gates if held[id(g)]]
                         + [g["start"] + len(lists.get(g["list"], [])) * g["item"] for g in groups]
                         + [end({"start": g["count"][0], "n": g["count"][1]}) for g in groups] + [0])
            length += -length % 6
        else:
            word = self.pack["wb"] * 8
            length = -(-length // word) * word
        out, claimed = [0] * length, set()

        def put(start, n, v, over):
            for k, b in enumerate(value_bits(v, n, msb)):
                if over or start + k not in claimed:
                    out[start + k] = b
                    claimed.add(start + k)

        # ruling 7: field lines, a present key or a default, the earlier line
        # winning; a gate value over the bits that only a default wrote; a
        # sentinel; const, when and counts over everything
        by_present = set()
        for x, chain in active:
            if x["d"] != "field":
                continue
            v = ent.get(x["key"], default_of(x, chain))
            if v is None:
                continue
            raw = self.encode_raw(x, v)
            if x["key"] in ent:                  # a present line's bits keep the field value
                by_present.update(range(x["start"], end(x)))
            for k, b in enumerate(value_bits(raw, x["n"], msb)):
                if x["start"] + k not in claimed:
                    out[x["start"] + k] = b
                    claimed.add(x["start"] + k)
        for g in gates:
            if held[id(g)] and id(g) in given:
                for k, b in enumerate(value_bits(given[id(g)], g["n"], msb)):
                    if g["start"] + k not in by_present:
                        out[g["start"] + k] = b
                        claimed.add(g["start"] + k)
        for x, chain in active:
            if x["d"] == "field" and x["absent"] and x["key"] not in ent and default_of(x, chain) is None:
                put(x["start"], x["n"], x["absent"][0], over=False)
        for x, _ in active:                                 # const and when
            if x["d"] in ("const", "when"):
                put(x["start"], x["n"], x["value"], over=True)
        for g in groups:                                    # items, then counts
            items = lists.get(g["list"], [])
            for i, item in enumerate(items):
                ib = self.encode_scope(g["body"], item, {}, item_bits=g["item"])
                out[g["start"] + i * g["item"]:g["start"] + (i + 1) * g["item"]] = ib
            put(g["count"][0], g["count"][1], len(items), over=True)

        # step 6: the same choice on the output, and no key left without a line
        fields = [(x, a) for x, a, _ in self.flat(lines, held) if x["d"] == "field"]
        for key in ent:
            mine = [a for x, a in fields if x["key"] == key]
            if mine and not any(mine):
                raise Fail("transform-encode", "key %s is mapped only in blocks not held" % key)
        again = self.held_on(lines, out, len(out))
        if again != held:
            raise Fail("transform-encode", "the output decodes to another choice of blocks")
        return out

    def encode(self, ent, lists, kind=None):
        lines = self.pack["common"]
        if self.pack["kinds"]:
            pick = None
            for k in self.pack["kinds"]:
                if (kind is not None and k["name"] == kind) or (kind is None and all(
                        r in ent for r in k["requires"])):
                    pick = k
                    break
            if pick is None:
                raise Fail("no-kind", "no kind qualifies")
            lines = lines + pick["lines"]
        out = self.encode_scope(lines, ent, lists)
        return bits_to_armor(out) if self.armor else to_hex(out, self.msb)


# ------------------------------------------------------------------------------
# the json pack: one member per key, one group
# ------------------------------------------------------------------------------
def json_decode(pack, text):
    obj = json.loads(text)
    keys, lists = {}, {}
    for line in pack["common"]:
        if line["d"] == "field" and line["member"] in obj:
            keys[line["key"]] = obj[line["member"]]
        elif line["d"] == "group" and line["member"] in obj:
            lists[line["list"]] = [{x["key"]: e[x["member"]] for x in line["body"] if x["member"] in e}
                                   for e in obj[line["member"]]]
    return keys, lists, None


def json_encode(pack, ent):
    parts = []
    for line in pack["common"]:
        if line["d"] == "field" and line["key"] in ent:
            parts.append('"%s":%s' % (line["member"], text_of(ent[line["key"]])))
    return "{" + ",".join(parts) + "}"


def model_of(keys, lists, kind):
    """The decoded entity as the strings of a vector's `model`."""
    m = {k: text_of(v) for k, v in keys.items()}
    if kind:
        m["@kind"] = kind
    for name, items in lists.items():
        m[name + ".#"] = str(len(items))
        for i, item in enumerate(items):
            for k, v in item.items():
                m["%s[%d].%s" % (name, i, k)] = text_of(v)
    return m


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written, counters, packs = {}, {}, {}

    def pack(name):
        if name not in packs:
            packs[name] = parse_pack(sink.read("packs/%s/pack.def" % name))
        return packs[name]

    def convert(frm, to, inp):
        """decode, then encode: the second computation of a vector."""
        src = pack(frm)
        keys, lists, kind = json_decode(src, inp) if src["wire"] == "json" else Gates(src).decode(inp)
        dst = pack(to)
        if dst["wire"] == "json":
            return json_encode(dst, keys), (keys, lists, kind)
        return Gates(dst).encode(keys, lists, kind if frm == to else None), (keys, lists, kind)

    def vec(owner, name, frm, to, inp, expect=None, error=None, model=None, why=None, ref=None):
        frm, to = "conformance-gates-" + frm, "conformance-gates-" + to
        owner = "conformance-gates-" + owner
        try:
            got, decoded = convert(frm, to, inp)
            failed = None
        except Fail as e:
            failed, got, decoded = e, None, None
        if error:
            assert failed is not None and failed.kind == error, (name, failed, got)
            assert why is None or why in failed.why, (name, failed.why)
        else:
            assert failed is None, (name, failed and failed.why)
            assert got == expect.replace(" ", ""), (name, expect, got)
        if model:
            if decoded is None:
                src = pack(frm)
                decoded = json_decode(src, inp) if src["wire"] == "json" else Gates(src).decode(inp)
            have = model_of(*decoded)
            for k, v in model.items():
                if k == "@absent":
                    for gone in v:
                        assert gone not in have, (name, gone, have)
                else:
                    assert have.get(k) == v, (name, k, v, have.get(k))
        counters[owner] = counters.get(owner, 0) + 1
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect.replace(" ", "")
        if model:
            d["model"] = model
        if ref:
            d["source"] = "constructed"
            d["reference"] = ref
        sink.write("packs/%s/vectors/%02d-%s.json" % (owner, counters[owner], name),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[owner] = written.get(owner, 0) + 1

    # ==========================================================================
    # conformance-gates-bits (lsb). Byte 1: bit 8 x valid, bits 9-10 the mode
    # (bit 9 is the low bit), bit 11 the gate of c2, bits 12-15 n.
    # ==========================================================================
    # 01 01 07: bit 8 = 1, x = 7; mode 0: z (1,2) and c1 (!0,1) do not hold;
    # y's gate (bit 56) lies beyond the 24-bit input. Encode: x is open, its
    # gate gets 1; length = max(16 outside, 24 x, 9 gate) = 3 bytes.
    vec("bits", "validity-bit-before-its-field-roundtrip", "bits", "bits", "010107", "01 01 07",
        model={"probe.w": "1", "probe.n": "0", "probe.x": "7",
               "@absent": ["probe.y", "probe.z", "probe.c1", "probe.c2"]})
    # y at byte 6, its gate bit 56 in byte 7: the gate locator is the furthest
    # bit of the output, so the output is 8 bytes.
    vec("bits", "validity-bit-after-its-field-extends-the-output", "bits", "bits",
        "0200000000000501", "02 00 00 00 00 00 05 01",
        model={"probe.w": "2", "probe.y": "5", "@absent": ["probe.x", "probe.z", "probe.c1"]})
    # 7 bytes: y lies inside the input, its gate bit 56 does not: y is absent.
    # Encode: nothing is open; the output is the 16 bits outside blocks.
    vec("bits", "gate-beyond-the-input-leaves-its-field-absent", "bits", "bits",
        "02000000000005", "02 00",
        model={"probe.w": "2", "probe.n": "0", "@absent": ["probe.y"]})
    # byte 1 = 0x52: bit 9 = 1, bit 10 = 0: mode 1, n = 5. z = 9 holds; c1's
    # byte 4 is beyond the input and does not count, its block does not hold.
    # Encode: z open, gate gets 1 (the first listed value).
    vec("bits", "mode-from-a-list-roundtrip", "bits", "bits", "03520009", "03 52 00 09",
        model={"probe.w": "3", "probe.n": "5", "probe.z": "9", "@absent": ["probe.x", "probe.c1", "probe.y"]})
    # byte 1 = 0x04: mode 2 holds both z (1,2) and c1 (!0,1). Encode: both
    # open; z comes first and gets 1; c1's gate is then written, mode 1 is
    # listed, c1's block does not hold and c1 has no other line (step 6).
    vec("bits", "mode-two-holds-both-blocks-reencode-fails", "bits", "bits", "030400090a",
        error="transform-encode", why="probe.c1", model={"probe.z": "9", "probe.c1": "10"})
    # byte 1 = 0x06: mode 3: z does not hold, c1 does. Encode: c1 open, its
    # gate gets the smallest value not in 0,1: 2 (byte 1 = 0x04). z is not
    # open, its gate lies inside the 16 bits outside blocks and reads 2: it is
    # held and writes nothing. Length max(16, 32, 40) = 5 bytes.
    vec("bits", "not-gate-gets-the-smallest-value-not-listed", "bits", "bits", "030600000a",
        "03 04 00 00 0a", model={"probe.w": "3", "probe.c1": "10", "@absent": ["probe.z"]})
    vec("bits", "to-json", "bits", "json", "03520009", '{"w":3,"z":9,"n":5}',
        model={"probe.w": "3", "probe.z": "9", "probe.n": "5"})

    # ==========================================================================
    # conformance-gates-select-bare (msb, no line outside blocks)
    # ==========================================================================
    # 01 04: bit 7 (mask 0x01 in msb order) = 1: the second meaning, hae =
    # 4 * 100 = 400. x and y: bits 20-21 beyond the input. Encode: hae opens
    # both blocks; the first gets its gate 0 and holds; hae = 400 / 25 = 16.
    vec("select-bare", "second-meaning-reencodes-in-the-first", "select-bare", "select-bare",
        "0104", "00 10", model={"hae": "400", "@absent": ["probe.x", "probe.y"]})
    vec("select-bare", "first-meaning-roundtrip", "select-bare", "select-bare", "0010", "00 10",
        model={"hae": "400"})
    # byte 2 = 0x08: bit 20 (mask 0x08) = 1, bit 21 (0x04) = 0: in msb order
    # the gate reads 0b10 = 2, so y = 0x2a. hae = 0 is present, its first
    # block holds. Encode: y gets 2; x's gate reads 2 and does not hold.
    # hae opens both its blocks: the first gets gate 0 and holds.
    vec("select-bare", "two-bit-gate-read-msb-first-y", "select-bare", "select-bare",
        "0000082a", "00 00 08 2a", model={"hae": "0", "probe.y": "42", "@absent": ["probe.x"]})
    vec("select-bare", "two-bit-gate-read-msb-first-x", "select-bare", "select-bare",
        "0000042a", "00 00 04 2a", model={"hae": "0", "probe.x": "42", "@absent": ["probe.y"]})
    vec("select-bare", "to-json", "select-bare", "json", "0104", '{"alt":400}', model={"hae": "400"})

    # ==========================================================================
    # conformance-gates-const (lsb): a const inside a block
    # ==========================================================================
    # 01 01 07 ff: the block holds, y = 7; a const is not checked on decode.
    # Encode: y open, gate 1; the held block's const writes 0xaa at byte 3.
    vec("const", "const-of-a-held-block-is-written", "const", "const", "010107ff", "01 01 07 aa",
        model={"probe.x": "1", "probe.y": "7"})
    # 02 00: the block does not hold. Encode: not open, gate reads 0: not
    # held, so neither its const nor its lines are written or counted: 1 byte.
    vec("const", "const-of-a-block-not-held-is-not-written", "const", "const", "0200", "02",
        model={"probe.x": "2", "@absent": ["probe.y"]})
    # 01 01 07: the block holds and y = 7 lies inside the input, but the
    # block's const (byte 3) does not: a held block's const lines count
    # toward the length decode requires.
    vec("const", "const-of-a-held-block-beyond-the-input", "const", "const", "010107",
        error="malformed-wire")

    # ==========================================================================
    # conformance-gates-select (msb, raw key c1 on the selector)
    # ==========================================================================
    # c1 = 1 is written in step 2: no gate gets a value, the second block
    # holds on the bits as written, hae = 400 / 100 = 4.
    vec("select", "raw-key-keeps-the-second-meaning", "select", "select", "0104", "01 04",
        model={"probe.c1": "1", "hae": "400"})
    vec("select", "first-meaning-roundtrip", "select", "select", "0010", "00 10",
        model={"probe.c1": "0", "hae": "400"})

    # ==========================================================================
    # conformance-gates-edge (lsb)
    # ==========================================================================
    # 05: the gate of y and z (byte 1) and the `!` gate of w (byte 4) lie
    # beyond the input; neither form holds, so w (not optional) is not read.
    # Encode: no block is open. Byte 1 is not written and reads 0 (step 4,
    # wherever it lies): the first block is held, y writes its sentinel 255,
    # and its lines count toward the length: max(8, 16 gate, 24 y, 32 z) = 4
    # bytes. Byte 4 reads 0: the `!0` block does not hold.
    vec("edge", "gate-and-its-not-form-beyond-the-input-do-not-hold", "edge", "edge", "05", "05 00 ff 00",
        model={"probe.x": "5", "@absent": ["probe.y", "probe.z", "probe.w"]})
    # 05 00 ff: byte 1 = 0 holds, y = 255 is its sentinel; z (optional)
    # beyond the input. Encode as for 05: the block holds on zero bits.
    vec("edge", "zero-gate-holds-on-zero-bits-and-writes-the-sentinel", "edge", "edge",
        "0500ff", "05 00 ff 00", model={"probe.x": "5", "@absent": ["probe.y", "probe.z", "probe.w"]})
    vec("edge", "field-of-a-held-block-beyond-the-input", "edge", "edge", "0500",
        error="malformed-wire")
    # byte 1 = 1: the block does not hold and needs no input. Encode: as 05.
    vec("edge", "block-that-does-not-hold-needs-no-input", "edge", "edge", "0501", "05 00 ff 00",
        model={"probe.x": "5", "@absent": ["probe.y", "probe.z"]})
    # 05 00 07: y = 7, z beyond the input (optional). Encode: y's block is
    # held; its optional line z counts toward the length: 4 bytes.
    vec("edge", "optional-line-of-a-held-block-counts-toward-the-length", "edge", "edge",
        "050007", "05 00 07 00", model={"probe.x": "5", "probe.y": "7", "@absent": ["probe.z", "probe.w"]})
    # byte 4 = 3 holds the `!0` block, w = 6. Encode: its gate gets the
    # smallest value not listed, 1.
    vec("edge", "not-gate-holds-and-gets-the-smallest-value-not-listed", "edge", "edge",
        "050007000306", "05 00 07 00 01 06",
        model={"probe.x": "5", "probe.y": "7", "probe.z": "0", "probe.w": "6"})

    # ==========================================================================
    # conformance-gates-absent (lsb)
    # ==========================================================================
    # 00 05 01 ff 01 ff: y = 5 (bit 0 = 0); c1 = 1; z and w hold their
    # sentinel. Encode: y open, gate 0. z and w are not open (a sentinel does
    # not open a block). z's gate bit 16 is written by c1 = 1: held, writes
    # the sentinel. w's gate bit 32 is not written and reads 0: not held,
    # dropped (ruling 6). Length 32 bits.
    vec("absent", "sentinel-keeps-its-gate-with-a-raw-key-and-loses-it-without", "absent", "absent",
        "000501ff01ff", "00 05 01 ff",
        model={"probe.x": "0", "probe.y": "5", "probe.c1": "1", "@absent": ["probe.z", "probe.w"]})
    # bit 0 = 1: y is not valid. Encode: y is not open; its gate of value 0
    # lies inside the lines outside blocks and reads 0: held, so y writes its
    # sentinel. Length 17 bits = 3 bytes.
    vec("absent", "invalid-flag-reencodes-as-the-sentinel", "absent", "absent", "010700", "00 ff 00",
        model={"probe.x": "0", "probe.c1": "0", "@absent": ["probe.y", "probe.z"]})
    vec("absent", "zero-gate-holding-the-sentinel-roundtrip", "absent", "absent", "00ff00", "00 ff 00",
        model={"probe.x": "0", "probe.c1": "0", "@absent": ["probe.y", "probe.z", "probe.w"]})

    # ==========================================================================
    # conformance-gates-default, -partial, -lines (lsb)
    # ==========================================================================
    vec("default", "raw-key-on-the-gate-roundtrip", "default", "default", "0105", "01 05",
        model={"probe.c2": "1", "probe.val": "5"})
    # c2 = 0: the block does not hold; val is not read. Encode: c2 = 0.
    vec("default", "block-that-does-not-hold-leaves-the-raw-key", "default", "default", "0005", "00",
        model={"probe.c2": "0", "@absent": ["probe.val"]})
    # 03 07: c1 = 1 and the gate reads 3. Encode: c1 = 1 writes bit 0, so the
    # gate is partly written and gets no value; bit 1 reads 0, the gate is 1,
    # the block does not hold and qty has no other line.
    vec("partial", "partly-written-gate-gets-no-value", "partial", "partial", "0307",
        error="transform-encode", why="probe.qty", model={"probe.c1": "1", "probe.qty": "7"})
    # bit 0 = 0: the block's line of x counts as absent, x = 9 from byte 2.
    # Encode: x opens the block, its gate gets 1, x is written at both lines.
    vec("lines", "line-in-a-block-that-does-not-hold-is-skipped", "lines", "lines", "000509", "01 09 09",
        model={"probe.x": "9"})
    vec("lines", "line-in-a-held-block-comes-first", "lines", "lines", "010509", "01 05 05",
        model={"probe.x": "5"})

    # ==========================================================================
    # conformance-gates-nested (lsb). byte 0: bit 0 outer gate and c1, bit 1
    # nested gate; byte 2: z low nibble, y (nested) high; byte 3: y (outer)
    # low, y (outside) high.
    # ==========================================================================
    # 03 0a 45 32: both hold; y = 4 from the nested line, the earliest that
    # holds (outer 2 and outside 3 are later lines). Encode: y = 4 at all
    # three lines; c1 wrote the outer gate, the nested gate gets 1.
    vec("nested", "nested-blocks-earliest-held-line-gives-the-key", "nested", "nested",
        "030a4532", "03 0a 45 44",
        model={"probe.c1": "1", "probe.x": "10", "probe.z": "5", "probe.y": "4"})
    # 00 00 00 70: c1 = 0, the outer block does not hold, the nested block is
    # not evaluated; y = 7 from the line outside. Encode: y opens both blocks;
    # c1 = 0 wrote the outer gate; the nested gate gets 1 in step 3 but its
    # block is not held, so the bit stays 0 (step 5).
    vec("nested", "nested-gate-of-an-outer-block-that-does-not-hold-is-not-written", "nested", "nested",
        "00000070", "00 00 00 70", model={"probe.c1": "0", "probe.y": "7", "@absent": ["probe.x", "probe.z"]})
    # 01 0a 00 62: outer holds, nested does not; y = 2 from the outer line.
    # Encode: y also opens the nested block, which gets its gate 1 and y = 2.
    vec("nested", "key-of-the-outer-block-opens-the-nested-block", "nested", "nested",
        "010a0062", "03 0a 20 22", model={"probe.c1": "1", "probe.x": "10", "probe.y": "2", "@absent": ["probe.z"]})

    # ==========================================================================
    # conformance-gates-kinds (lsb)
    # ==========================================================================
    vec("kinds", "block-in-a-kind-roundtrip", "kinds", "kinds", "011107", "01 11 07",
        model={"@kind": "a", "probe.w": "1", "probe.x": "7"})
    # bits 8-11 = 1 select kind a; bit 12 = 0, x is absent; the kind is still
    # selected (ruling 1). Encode: x is not open, its gate bit 12 reads 0 and
    # does not hold; w and the `when` reach 12 bits: 2 bytes.
    vec("kinds", "kind-selected-although-its-block-does-not-hold", "kinds", "kinds", "010107", "01 01",
        model={"@kind": "a", "probe.w": "1", "@absent": ["probe.x"]})
    # kind b: the `when` writes 2 on bits 8-11, y's gate (3) does not hold;
    # z's gate bit 12 = 1.
    vec("kinds", "when-on-the-gate-bits-of-a-block-roundtrip", "kinds", "kinds", "02120009", "02 12 00 09",
        model={"@kind": "b", "probe.w": "2", "probe.z": "9", "@absent": ["probe.y"]})

    # ==========================================================================
    # conformance-gates-groups (lsb): items of 2 bytes from byte 2
    # ==========================================================================
    # item 0 = 03 09: bit 0 = 1, val = 1, qty = 9; item 1 = 04 00: bit 0 = 0,
    # val = 2, no qty.
    vec("groups", "gate-per-item-roundtrip", "groups", "groups", "070203090400", "07 02 03 09 04 00",
        model={"probe.w": "7", "probe.items.#": "2", "probe.items[0].probe.val": "1",
               "probe.items[0].probe.qty": "9", "probe.items[1].probe.val": "2",
               "@absent": ["probe.items[1].probe.qty"]})
    vec("groups", "bits-of-an-item-block-that-does-not-hold-are-dropped", "groups", "groups",
        "0701040a", "07 01 04 00",
        model={"probe.items.#": "1", "probe.items[0].probe.val": "2", "@absent": ["probe.items[0].probe.qty"]})

    # ==========================================================================
    # conformance-gates-default-on (lsb): c2 at bit 0, default 1
    # ==========================================================================
    # 01 ff: c2 = 1, val holds its sentinel. Encode: c2 = 1 present.
    vec("default-on", "raw-key-and-sentinel-roundtrip", "default-on", "default-on", "01ff", "01 ff",
        model={"probe.c2": "1", "@absent": ["probe.val", "probe.qty"]})
    # 00 00 07: c2 = 0, qty = 7. Encode: c2 = 0 is written; qty's gate gets no value.
    vec("default-on", "raw-key-zero-holds-the-second-block", "default-on", "default-on", "000007", "00 00 07",
        model={"probe.c2": "0", "probe.qty": "7", "@absent": ["probe.val"]})

    # ==========================================================================
    # conformance-gates-overlap (lsb): x covers its own gate bits 0-1
    # ==========================================================================
    # 05 07: x's low bits 01 hold the block. Encode: x opens it, gate 1; x = 5
    # wins over the gate value on bits 0-1 and they read 1 again: held.
    vec("overlap", "field-over-its-own-gate-roundtrip", "overlap", "overlap", "0507", "05 07",
        model={"probe.x": "5", "probe.y": "7"})
    # 06 07: x's low bits 10: the block does not hold, x is absent. Encode:
    # nothing is open, bits 0-1 read 0: not held; y alone, 2 bytes.
    vec("overlap", "field-over-its-own-gate-that-does-not-hold", "overlap", "overlap", "0607", "00 07",
        model={"probe.y": "7", "@absent": ["probe.x"]})

    # ==========================================================================
    # conformance-gates-select-range (lsb): hae in units of 100 m (bit 0 = 0)
    # or of 25 m (bit 0 = 1), no raw key
    # ==========================================================================
    # 01 28: the second meaning, 40 * 25 = 1000. Encode: both blocks open, the
    # first gets gate 0: 1000 / 100 = 10.
    vec("select-range", "second-meaning-reencodes-in-the-first", "select-range", "select-range",
        "0128", "00 0a", model={"hae": "1000"})
    vec("select-range", "first-meaning-roundtrip", "select-range", "select-range", "0064", "00 64",
        model={"hae": "10000"})


    # ==========================================================================
    # conformance-gates-default-overlap (lsb, no gates)
    # ==========================================================================
    # 0f 0a: x = 15, y = bits 4-11 = 0x0 | 0xa << 4 = 160. Encode: both present;
    # x is earlier and keeps bits 4-7.
    vec("default-overlap", "overlapping-lines-roundtrip", "default-overlap", "default-overlap", "0f0a",
        "0f 0a", model={"probe.x": "15", "probe.y": "160"})

    # ==========================================================================
    # conformance-gates-default-gate (lsb): x (bits 0-3, default 3), and y
    # (bits 0-7) in a block gated by bits 0-1 holding 1 or 3
    # ==========================================================================
    # a3: x = 3; the gate reads 3: y = 0xa3 = 163. Encode: x is present and
    # written in step 2, so the gate gets no value; x wins bits 0-3.
    vec("default-gate", "overlapping-lines-on-the-gate-roundtrip", "default-gate", "default-gate", "a3", "a3",
        model={"probe.x": "3", "probe.y": "163"})

    # ==========================================================================
    # from conformance-gates-json: entities a same-format round trip cannot give
    # ==========================================================================
    # x, y and z open their blocks: bit 8, mode 1 (bit 9), bit 56; c1's block
    # does not hold on mode 1, c2's never. Length max(16, 24, 32, 56, 57).
    vec("json", "to-bits-three-gates-get-their-values", "json", "bits",
        '{"w":1,"x":7,"y":5,"z":9}', "01 03 07 09 00 00 05 01", model={"probe.w": "1", "probe.x": "7"})
    # the `!` list names both values of a 1-bit gate: no value, never holds.
    vec("json", "to-bits-not-list-naming-every-value", "json", "bits", '{"w":1,"c2":5}',
        error="transform-encode", why="probe.c2")
    vec("json", "to-bits-not-gate-holds-another-block-on-its-value", "json", "bits", '{"w":3,"c1":10}',
        "03 04 00 00 0a")
    # no raw key: hae opens both blocks, the earlier gets its gate 0.
    vec("json", "to-select-bare-earlier-block-gets-its-gate", "json", "select-bare", '{"alt":400}', "00 10",
        model={"hae": "400"})
    vec("json", "to-select-earlier-block-without-the-raw-key", "json", "select", '{"alt":400}', "00 10")
    vec("json", "to-select-raw-key-chooses-the-second-meaning", "json", "select", '{"alt":400,"c1":1}',
        "01 04")
    # x's block gets gate 1; y's gate is then written and reads 1, not 2.
    # no hae: the first hae block is not open, but its gate bit 7 is not
    # written and reads 0: held, it writes nothing (hae has no default or
    # sentinel) and its line counts; x gets gate 1. The output decodes hae=0.
    vec("json", "to-select-bare-block-held-by-zero-bits", "json", "select-bare", '{"x":42}', "00 00 04 2a")
    vec("json", "to-const-held-block-writes-its-const", "json", "const", '{"y":7}', "00 01 07 aa")
    vec("json", "to-select-bare-two-keys-on-one-gate", "json", "select-bare", '{"x":1,"y":2}',
        error="transform-encode", why="probe.y")
    # {} : x and c1 absent, nothing written; y's gate (value 0) lies inside
    # the 17 bits outside blocks and reads 0: held, the sentinel of y.
    vec("json", "to-absent-entity-without-keys-writes-the-sentinel", "json", "absent", "{}", "00 ff 00")
    # c2 is absent and has a default: its bit is not written; val opens the
    # block, whose gate value 1 replaces the default 0.
    vec("json", "to-default-gate-value-replaces-the-default", "json", "default", '{"val":5}', "01 05")
    vec("json", "to-default-raw-key-defeats-the-open-block", "json", "default", '{"val":5,"c2":0}',
        error="transform-encode", why="probe.val")
    vec("json", "to-default-entity-without-keys", "json", "default", "{}", "00")
    # no key: step 4 reads the default 1 on bit 0 (no gate value replaced
    # it): val's block holds and writes its sentinel; qty's (gate 0) does
    # not. Length 16 bits.
    vec("json", "to-default-on-the-default-holds-a-block", "json", "default-on", "{}", "01 ff")
    # qty opens its block: gate value 0 is written over the default 1 (ruling
    # 7); val's block reads 0 and does not hold. Length 24 bits.
    vec("json", "to-default-on-gate-value-over-a-nonzero-default", "json", "default-on", '{"qty":7}',
        "00 00 07")
    vec("json", "to-default-on-gate-value-equal-to-the-default", "json", "default-on", '{"val":5}', "01 05")
    # x = 6 opens the block, gate 1; x wins over the gate value on bits 0-1,
    # which read 2 on the output: the block does not hold there (step 6).
    vec("json", "to-overlap-present-field-over-its-gate-changes-the-choice", "json", "overlap",
        '{"x":6,"y":7}', error="transform-encode", why="another choice")
    vec("json", "to-overlap-present-field-agrees-with-its-gate", "json", "overlap", '{"x":9,"y":7}', "09 07")
    vec("json", "to-partial-gate-gets-its-value", "json", "partial", '{"qty":7}', "03 07")
    # y opens both blocks; no c1: both gates get 1; y at three lines.
    vec("json", "to-nested-key-opens-the-outer-and-nested-blocks", "json", "nested", '{"y":7}',
        "03 00 70 77")
    # ruling 5: nested y default 4, outer y default 3, outside y common 1.
    vec("json", "to-nested-innermost-default-wins", "json", "nested", '{"c1":1,"x":10,"z":5}',
        "03 0a 45 13")
    # the nested block is not open and does not hold: its default 4 is not
    # written; the outer default 3 and the common default 1 are.
    vec("json", "to-nested-default-of-a-block-not-held-is-not-written", "json", "nested",
        '{"c1":1,"x":10}', "01 0a 00 13")
    # no x: kind a does not qualify (requires sees the entity); kind b's
    # `when` writes 2 on y's gate bits: y's block cannot hold.
    vec("json", "to-kinds-when-defeats-an-open-block", "json", "kinds", '{"w":2,"y":5}',
        error="transform-encode", why="probe.y")
    vec("json", "to-kinds-requires-sees-the-entity", "json", "kinds", '{"w":1}', "01 02")
    vec("json", "to-kinds-block-in-the-required-kind", "json", "kinds", '{"w":1,"x":7}', "01 11 07")
    vec("json", "to-groups-gate-per-item", "json", "groups",
        '{"w":7,"items":[{"v":1,"q":9},{"v":2}]}', "07 02 03 09 04 00",
        model={"probe.items.#": "2", "probe.items[0].probe.qty": "9", "@absent": ["probe.items[1].probe.qty"]})

    # ruling 10: 10000 / 100 = 100 fits the held first block; 10000 / 25 =
    # 400 does not fit the 8 bits of the second, which is not held: no error.
    vec("json", "to-select-range-value-too-wide-for-the-block-not-held", "json", "select-range",
        '{"alt":10000}', "00 64")
    # 30000 / 100 = 300 does not fit the held block: an error of a held line.
    vec("json", "to-select-range-value-too-wide-for-the-held-block", "json", "select-range",
        '{"alt":30000}', error="transform-encode", why="uscale")

    # no gates: x is absent and written from its default 15 (0x0f) on bits
    # 0-7; y = 171 (0xab) on bits 4-11 loses bits 4-7 to the earlier line and
    # keeps bits 8-11 = 0xa: bytes 0f 0a. The output decodes y = 0xa0 = 160.
    vec("json", "to-default-overlap-earlier-default-line-wins", "json", "default-overlap", '{"y":171}',
        "0f 0a", model={"probe.y": "171", "@absent": ["probe.x"]})

    # ruling 7: x is absent, its default 3 is not written in step 2; y opens
    # the block, whose gate gets 1 and holds. Step 5: x's default line is
    # earlier and wins bits 0-3 (0011); y = 160 (0xa0) keeps bits 4-7 = 0xa.
    # Bits 0-1 are covered by y, a line with a present key: the gate value 1
    # does not go there and they keep 11 = 3, which the gate lists: a3. (A
    # gate value written over the default's bits would give a1.)
    vec("json", "to-default-gate-present-line-keeps-the-default-over-the-gate-value", "json", "default-gate",
        '{"y":160}', "a3", model={"probe.y": "160", "@absent": ["probe.x"]})

    # ==========================================================================
    # conformance-gates-armor (msb, armor sixbit; ruling 14). n bits 0-5; the
    # block's gate bit 12, x bits 6-11 and the optional y bits 13-23. Armor:
    # value v is chr(0x30 + v) below 40 and chr(0x38 + v) from 40.
    # ==========================================================================
    ref = ("spec/engine-spec.md Version 0.14 (six-bit armor: reading, writing, L) and Version 0.17 "
           "(Decode; Encode steps 1-6; ruling 14, gates under six-bit armor). ")
    # n = 1 (000001), x = 5 (000101), gate 1, y = 1000 (01111101000):
    # 000001 000101 101111 101000 = 1, 5, 47, 40 = "1", "5", "g", "`".
    # Encode: x and y open the block; gate bit 12 is not written and gets 1;
    # held. L = 24 (y is written): 4 characters, no fill bit.
    vec("armor", "gate-held-roundtrip", "armor", "armor", "15g`", "15g`",
        model={"probe.n": "1", "probe.x": "5", "probe.y": "1000"},
        ref=ref + "Bits 000001 000101 1 01111101000; L = 24 bits, 4 characters.")
    # "15P": P = 32 = 100000: gate 1, the first bit of y. 18 bits: y (13-23)
    # runs past the input and is optional: absent. Encode: x opens the block,
    # gate 1; L = max(6 n, 12 x, 13 the gate locator) = 13, y is not written
    # and does not count; 13 bits and 5 zero fill bits: "15P". Without the
    # gate locator L would be 12, "15".
    vec("armor", "gate-locator-after-its-field-adds-a-character-roundtrip", "armor", "armor", "15P", "15P",
        model={"probe.n": "1", "probe.x": "5", "@absent": ["probe.y"]},
        ref=ref + "L = 13: the gate bit 12 counts, the optional y does not; 3 characters, 5 zero fill bits.")
    # "15?`": ? = 15 = 001111, ` = 40 = 101000: gate bit 12 = 0, the block
    # does not hold: x and y set no key, although their bits are in the input.
    # Encode of {n: 1}: no block is open, the gate gets no value; step 4 reads
    # bit 12 as 0 (nothing wrote it): not held, nothing of the block is
    # written. L = 6: "1".
    vec("armor", "gate-not-held-the-text-ends-after-the-outside-field", "armor", "armor", "15?`", "1",
        model={"probe.n": "1", "@absent": ["probe.x", "probe.y"]},
        ref=ref + "Gate bit 12 = 0: x and y absent; re-encode L = 6 (n only), 1 character.")
    # "15": 12 bits; gate bit 12 lies beyond the bits the text carries and
    # does not hold, so x is absent although bits 6-11 are in the input
    # (ruling 14). Encode as above: "1".
    vec("armor", "gate-beyond-the-armored-input-does-not-hold", "armor", "armor", "15", "1",
        model={"probe.n": "1", "@absent": ["probe.x", "probe.y"]},
        ref=ref + "12 input bits: the gate bit 12 is beyond the input and does not hold; re-encode 1 character.")
    vec("json", "to-armor-gated-keys-present", "json", "armor", '{"n":1,"x":5,"y":1000}', "15g`",
        model={"probe.n": "1", "probe.x": "5", "probe.y": "1000"},
        ref=ref + "As gate-held-roundtrip: gate value 1, L = 24, 4 characters.")
    # x = 5 only: n is absent, its zero bits count toward L (0.14: a field
    # line counts whether or not its key is present): 000000 000101 1 = 13
    # bits, "0", "5", "P".
    vec("json", "to-armor-gated-key-without-the-outside-key", "json", "armor", '{"x":5}', "05P",
        model={"probe.x": "5", "@absent": ["probe.n", "probe.y"]},
        ref=ref + "n absent writes zeros and counts; gate value 1; L = 13, 3 characters.")
    # y = 1000 only: y opens the block (x absent, zero bits); the optional y
    # is written and counts: 000000 000000 101111 101000 = "0", "0", "g", "`".
    vec("json", "to-armor-optional-gated-key-alone", "json", "armor", '{"y":1000}', "00g`",
        model={"probe.y": "1000", "@absent": ["probe.n", "probe.x"]},
        ref=ref + "The optional y opens the block and is written: L = 24, 4 characters.")
    vec("json", "to-armor-without-the-gated-keys", "json", "armor", '{"n":1}', "1",
        model={"probe.n": "1", "@absent": ["probe.x", "probe.y"]},
        ref=ref + "No block open, gate bit 12 reads 0 and does not hold; L = 6, 1 character.")

    # ==========================================================================
    # load vectors from 640
    # ==========================================================================
    models = [
        ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\nkey type string -\n"
         "key lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n"),
        ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey label string -\nkey qty int -\n"
         "key x int -\nkey y int -\nkey a float -\nlist items \"a list\"\nlist subs \"a nested list\"\n"),
    ]
    head = 'format probe\nversion 0.17.0\ndistribution public\nsource "probe"\nuses probe\n'
    bits, seq, js = head + "wire bits\nword_bytes 1\n", head + "wire bits\nlayout sequential\n", head + "wire json\n"
    gated = "  field probe.x 0:8:8 uint\nend\n"
    lnum = [639]

    def load(name, text, error="bad-directive"):
        lnum[0] += 1
        full = "%d-gates-%s" % (lnum[0], name)
        d = {"name": full, "models": models, "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    load("on-a-wire-other-than-bits", js + "if 0:0:1 1\n  field probe.x x int\nend\n")
    load("locator-in-a-sequential-layout", seq + "field probe.y 8 uint\nif 0:0:1 1\n  field probe.x 8 uint\nend\n")
    load("presence-name-in-a-fixed-layout", bits + "field probe.y 0:0:8 uint\nif p.1\n" + gated)
    load("value-too-wide-for-the-gate", bits + "if 0:0:2 4\n" + gated)
    load("value-listed-twice", bits + "if 0:0:2 1,2,1\n" + gated)
    load("empty-value-list", bits + "if 0:0:2\n" + gated)
    load("empty-value-in-the-list", bits + "if 0:0:2 1,,2\n" + gated)
    load("value-not-a-decimal-integer", bits + "if 0:0:2 0x1\n" + gated)
    load("negative-value", bits + "if !0:0:2 -1\n" + gated)
    load("gate-of-no-bits", bits + "if 0:0:0 0\n" + gated)
    load("gate-of-65-bits", bits + "if 0:0:65 1\n  field probe.x 0:72:8 uint\nend\n")
    load("without-end", bits + "if 0:0:1 1\n  field probe.x 0:8:8 uint\n")
    load("when-inside-a-block", bits + "kind k\nwhen 0:0:4 1\nif 0:4:1 1\n  when 0:0:4 1\n" + gated)
    load("group-inside-a-block", bits + "if 0:0:1 1\n  group probe.items 0:16 item 8 count 2\n"
         "    field probe.qty 0:0:8 uint\n  end\nend\n")
    load("kind-inside-a-block", bits + "if 0:0:1 1\n  kind k\n" + gated)
    load("requires-inside-a-block", bits + "field probe.y 0:0:8 uint\nkind k\nwhen 0:0:4 1\nif 0:4:1 1\n"
         "  requires probe.x\n" + gated)
    load("typemap-inside-a-block", bits + "if 0:0:1 1\n  typemap 1 a-f-G\n" + gated)
    load("gate-outside-its-group-item", bits + "group probe.items 0:8 item 8 count 2\n  if 0:8:1 1\n"
         "    field probe.qty 0:0:8 uint\n  end\nend\n")
    load("gated-field-outside-its-group-item", bits + "group probe.items 0:8 item 8 count 2\n  if 0:0:1 1\n"
         "    field probe.qty 0:1:8 uint\n  end\nend\n")
    load("gate-at-the-start-of-a-group-counted-by-a-locator", bits + "group probe.items 0:16 item 8 count 0:0:8\n"
         "  field probe.qty 0:0:8 uint\nend\nif 0:16:1 1\n  field probe.y 0:8:8 uint\nend\n")
    load("gated-field-beyond-the-start-of-a-group-counted-by-a-locator", bits + "group probe.items 0:16 item 8 "
         "count 0:0:8\n  field probe.qty 0:0:8 uint\nend\nif 0:8:1 1\n  field probe.y 0:24:8 uint\nend\n")
    load("also-inside-a-block", bits + "if 0:0:1 1\n  field probe.x 0:8:8 uint\n  also probe.y\nend\n")
    load("not-list-that-never-holds-loads", bits + "if !0:0:1 0,1\n" + gated, None)
    load("in-a-kind-nested-and-in-a-group-item-loads", bits + "field probe.y 0:0:8 uint\n"
         "group probe.items 0:16 item 16 count 0:8:8\n  if 0:0:1 1\n    field probe.qty 0:8:8 uint\n  end\nend\n"
         "kind k\nwhen 0:0:4 1\nif !0:4:2 0,3\n  const 0:6:1 1\n  default probe.x 1\n  field probe.x 0:7:1 uint\n"
         "  if 0:6:2 1,2\n    default probe.x 0\n    field probe.x 0:0:1 uint\n  end\nend\n", None)
    # rulings 9 and 12, from 462
    load("gate-within-the-items-of-a-fixed-count-group", bits + "field probe.y 0:0:8 uint\n"
         "group probe.items 0:8 item 8 count 2\n  field probe.qty 0:0:8 uint\nend\n"
         "if 0:12:1 1\n  field probe.x 0:24:8 uint\nend\n")
    load("space-after-a-comma", bits + "if 0:0:2 1, 2\n" + gated)
    load("third-token", bits + "if 0:0:2 1 2\n" + gated)
    # ruling 13: the errors of this version are checks after the file
    load("ruling-13-a-later-line-error-comes-first", bits + "if 0:0:2 4\n" + gated + "bogus\n", "unknown-directive")
    load("ruling-13-on-json-a-later-line-error-comes-first", js + "if 0:0:2 1\n" + gated + "bogus\n",
         "unknown-directive")
    return written


def main(argv=None):
    return genio.vector_main("conformance-gates-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
