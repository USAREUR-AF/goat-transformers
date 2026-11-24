#!/usr/bin/env python3
"""Write the vectors of spec 0.94, a conversion into a kind holds one of its
keys: the packs `conformance-held-*` and their vectors.

Every expected value is worked out by hand from the spec text (Version 0.94;
0.5 kinds and `requires`, 0.6 context, derivations, defaults and constants,
0.7 lists, 0.8 sequential lines, 0.9 `absent`, 0.18 `with`, 0.20 `requires =`
and `switch`, 0.30 `as`, 0.34 `inner`); the working is the comment above each
vector and the value is written out literally. It is checked against a second
computation: a small reader of the pack texts below and codecs of the lines
they use, which choose the kind, collect its keys and the keys the entity
holds, and write the output. Nothing here imports or calls an engine. The
packs are loaded by tools/gen/gtcheck.py.

Not covered: 0.94 names an optional `as`; no section of this specification
defines one, so no pack here has it.

Writes, under --out, the pack.def files and the vectors. With --check nothing
is written and the exit status is 1 when a committed file differs.

Usage: python3 -I tools/gen/conformance-held-vectors.py [--out DIR] [--check]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PREFIX = "conformance-held-"
SEQ = "wire       bits\nlayout     sequential\nbit_order  msb\n"
JSON = "wire       json\n"
# name: (comment, wire lines, body)
PACKS = {
    "src": ("plain members, the entities the other packs are encoded from", JSON, """\
field   uid         id   string
field   lat         lat  float
field   probe.n     n    int
field   probe.x     x    int
field   probe.y     y    int  absent 99
field   probe.z     z    int
field   probe.w     w    int
field   probe.c1    c1   int
field   probe.s1    s    string
group   probe.recs  recs
  field  probe.x  x  int
  field  probe.y  y  int
end
"""),
    "one": ("one kind that maps scalars and a list, with a sentinel, `with`, a default and a constant", JSON, """\
kind    k
when    t  k
field   probe.x   x    int
field   probe.s1  s    string
field   probe.z   z    int  absent 255
field   probe.w   w    int  with probe.c1
field   probe.v1  d    int
default probe.v1  5
const   c  7
group   probe.recs  recs
  field  probe.x  x  int
end
field   core.lat  lat  float
"""),
    "list": ("a kind whose only keys are those of a list's items", JSON, """\
kind    k
when    t  k
group   probe.recs  recs
  field  probe.x  x  int
end
"""),
    "y": ("a kind that maps one key", JSON, "kind    k\nwhen    t  k\nfield   probe.y  y  int\n"),
    "derived": ("a kind that maps one derived key", JSON, "kind    k\nwhen    t  k\nfield   probe.n_copy  c  int\n"),
    "two": ("two kinds, each with a key of its own", JSON, """\
kind    first
when    t  one
field   probe.x  x  int
kind    second
when    t  two
field   probe.y  y  int
"""),
    "common": ("a key of the common lines", JSON, """\
field   probe.n  n  int
kind    k
when    t  k
field   probe.x  x  int
"""),
    "nomap": ("kinds that map no key", JSON, """\
kind    p
when    t  p
requires probe.x=1
kind    q
when    t  q
requires probe.y
kind    r
when    t  r
"""),
    "reqlist": ("a kind that requires a list it does not map", JSON, """\
kind    k
when    t  k
requires probe.recs
kind    other
when    t  other
field   probe.w  w  int
"""),
    "err": ("a kind whose default cannot be written", JSON, """\
kind    k
when    t  k
field   probe.x  x  bool
default probe.x  7
"""),
    "none": ("no line but the header (ruling 6)", JSON, ""),
    "clear": ("no field line, and a kind that holds only `requires` (ruling 6)", JSON,
              "kind    clear\nrequires probe.n\n"),
    "by": ("common lines and two kinds that hold only `requires` (ruling 6)", JSON, """\
field   probe.x  a   int
field   probe.y  b   int
field   uid      id  string
kind    by-a
requires probe.x
kind    by-b
requires probe.y
"""),
    "xml": ("xml without kinds (ruling 6)", "wire       xml\n", "root    R\nfield   probe.x  @x  int\n"),
    "xmlkind": ("xml with a kind that holds only `requires` (ruling 6)", "wire       xml\n",
                "root    R\nfield   probe.x  @x  int\nkind    by-x\nrequires probe.x\n"),
    "as": ("keys bound by `when ... as`, in the common lines and in a kind", SEQ, """\
when    8  5,6  as probe.w
kind    a
when    8  1..3  as probe.x
field   probe.y  8  uint
kind    b
when    8  9
field   probe.z  8  uint
"""),
    "also": ("a key of an `also` line", SEQ, "kind    k\nwhen    8  7\nfield   probe.x  8  uint\nalso    probe.y\n"),
    "block": ("a key of a block that is not written", SEQ, """\
kind    k
when    8  7
presence p 2
if p.1 !p.2
  field  probe.x  8  uint
end
if p.2
  field  probe.y  8  uint
end
default probe.y  9
"""),
    "case": ("keys of the cases of a switch, and the key it names", SEQ, """\
kind    k
when    8  7
field   probe.x  8  uint
switch  probe.x
  case 1
    field  probe.z  8  uint
  case 2
    field  probe.w  8  uint
  else
end
"""),
    "items": ("kinds in a group body only: no message kind", SEQ, """\
group   probe.recs  count 8
  kind   a
  when   8  1
  field  probe.x  8  uint
end
"""),
    "in": ("an inner pack: a kind with a key, one that maps nothing, and one never chosen by `requires`", SEQ, """\
kind    data
when    8  2
requires probe.x
field   probe.x  8  uint
kind    ping
when    8  1
kind    extra
when    8  3
field   probe.z  8  uint
"""),
    "out": ("an outer pack: the `inner` line in its one kind", SEQ, """\
kind    carry
when    8  7
length  8
  inner  conformance-held-in
end
"""),
    "outcommon": ("an outer pack: the `inner` line in the common lines", SEQ, """\
length  8
  inner  conformance-held-in
end
kind    k
when    8  7
field   probe.w  8  uint
"""),
    "outother": ("an outer pack: the `inner` line in a kind that is not chosen", SEQ, """\
kind    first
when    8  1
field   probe.w  8  uint
kind    second
when    8  2
requires probe.c1
inner   conformance-held-in
"""),
    "outmissing": ("an outer pack whose inner pack is not loaded", SEQ, """\
kind    k
when    8  7
field   probe.w  8  uint
inner   conformance-held-no-such-pack
"""),
    "clearin": ("an inner pack of a constant and a kind that holds only `requires` (ruling 6)", SEQ,
                "const   8  5\nkind    clear\nrequires probe.n\n"),
    "outclear": ("an outer pack of conformance-held-clearin", SEQ, """\
kind    k
when    8  7
field   probe.w  8  uint
length  8
  inner  conformance-held-clearin
end
"""),
}


def pack_text(name):
    comment, wire, body = PACKS[name]
    return ("# Conformance probe pack for spec 0.94: %s. Public.\nformat     %s%s\nversion    0.94.0\n"
            "distribution public\n"
            'source  "goat-transformers spec/engine-spec.md (synthetic probe format, no external standard)"\n'
            "uses       probe\n%s%s" % (comment, PREFIX, name, wire, body))


# ------------------------------------------------------------------------------
# the second computation
# ------------------------------------------------------------------------------
class Fail(Exception):
    def __init__(self, kind, why=""):
        super().__init__(kind, why)
        self.kind = kind


class Ln:
    def __init__(self, d, a):
        self.d, self.a, self.body, self.cases = d, a, [], []


def parse(name):
    """(wire, root element, common lines, message kinds)."""
    _, wire, body = PACKS[name]
    root, lines = None, []
    stack = [lines]
    for raw in body.splitlines():
        t = raw.split()
        d, a = t[0], t[1:]
        if d == "root":
            root = a[0]
            continue
        if d == "end":
            stack.pop()
            continue
        node = Ln(d, a)
        if d in ("case", "else"):
            while not (isinstance(stack[-1], Ln) and stack[-1].d == "switch"):
                stack.pop()
            stack[-1].cases.append((a[0].split(",") if a else None, node.body))
            stack.append(node.body)
            continue
        (stack[-1]).append(node)
        if d == "switch":
            stack.append(node)
        elif d in ("group", "if", "length"):
            stack.append(node.body)
    return wire.split()[1], root, *split(lines)


def parse_end_fix(name):
    """`end` of a switch closes its last arm and the switch."""
    _, wire, body = PACKS[name]
    out, depth = [], []
    for raw in body.splitlines():
        d = raw.split()[0]
        if d in ("switch", "group", "if", "length"):
            depth.append(d)
        out.append(raw)
        if d == "end" and depth.pop() == "switch":
            out.append("end")
    return "\n".join(out)


def split(lines):
    common, kinds = [], []
    for ln in lines:
        if ln.d == "kind":
            kinds.append((ln.a[0], []))
        else:
            (kinds[-1][1] if kinds else common).append(ln)
    return common, kinds


def opt(ln, name):
    return ln.a[ln.a.index(name) + 1] if name in ln.a[3:] else None


def when_of(ln):
    vals = []
    for v in ln.a[1].split(","):
        lo, _, hi = v.partition("..")
        vals.append((lo, hi or lo))
    return vals, (ln.a[3] if ln.a[2:3] == ["as"] else None)


def in_values(vals, v):
    return any(int(lo) <= v <= int(hi) for lo, hi in vals)


def keys_of(lines, entries):
    """0.94 "Keys of a kind": entries of 6a to 6c of 0.11 over the lines."""
    for ln in lines:
        if ln.d in ("field", "also"):
            entries.add(ln.a[0])
        elif ln.d == "when":
            if ln.a[2:3] == ["as"]:
                entries.add(ln.a[3])
        elif ln.d == "group":
            entries.add(ln.a[0] + "[]")
        elif ln.d == "requires":
            for t in ln.a:
                key = t.split("=")[0]
                entries.add(key + "[]" if key == "probe.recs" else key)
        elif ln.d == "inner":
            inner = ln.a[0][len(PREFIX):]
            if inner in PACKS:
                _, _, c, ks = parse(inner)
                got = set()
                keys_of([x for x in c if x.d != "requires"], got)
                for _, kl in ks:
                    keys_of([x for x in kl if x.d != "requires"], got)
                entries |= got
        if ln.d in ("if", "length"):
            keys_of(ln.body, entries)
        for _, b in ln.cases:
            keys_of(b, entries)
    return entries


def inner_lines(lines):
    out = []
    for ln in lines:
        if ln.d == "inner":
            out.append(ln.a[0])
        if ln.d == "length":
            out += inner_lines(ln.body)
    return out


def choose(name, ent, recorded):
    _, _, common, kinds = parse(name)
    if recorded is not None:
        return recorded, dict(kinds)[recorded]
    for k, lines in kinds:
        ok = True
        for ln in lines:
            if ln.d == "requires":
                for t in ln.a:
                    key, eq, vals = t.partition("=")
                    ok = ok and key in ent and (not eq or str(ent[key]) in vals.split(","))
            elif ln.d == "when" and ln.a[0].isdigit():
                vals, as_ = when_of(ln)
                if as_:
                    ok = ok and as_ in ent and in_values(vals, ent[as_])
        if ok:
            return k, lines
    raise Fail("no-kind", "choosing")


def check(name, ent, kind_rec, inner_rec):
    """The rule of 0.94, for convert into another format."""
    _, _, common, kinds = parse(name)
    if not kinds:
        return
    fmt = PREFIX + name
    recorded = None
    for rec in (kind_rec, inner_rec):
        if recorded is None and rec and rec[0] == fmt:
            recorded = rec[1]
    _, lines = choose(name, ent, recorded)
    kept = {r[0] for r in (kind_rec, inner_rec) if r}
    if fmt in kept or kept & set(inner_lines(common + lines)):
        return
    held = {k + "[]" if isinstance(v, list) else k for k, v in ent.items() if v != [] or not isinstance(v, list)}
    if not held & keys_of(common + lines, set()):
        raise Fail("no-kind", "nothing held")


class Bits:
    def __init__(self, text=""):
        self.b = "".join(format(x, "08b") for x in bytes.fromhex(text))
        self.at = 0

    def read(self, n):
        if self.at + n > len(self.b):
            raise Fail("malformed-wire")
        v = int(self.b[self.at:self.at + n], 2)
        self.at += n
        return v

    def write(self, n, v):
        self.b += format(v, "0%db" % n)

    def hex(self):
        b = self.b + "0" * (-len(self.b) % 8)
        return bytes(int(b[i:i + 8], 2) for i in range(0, len(b), 8)).hex()


def dec_bits(name, r):
    """(entity, kind record, inner record)."""
    _, _, common, kinds = parse(name)
    ent, state = {}, {"inner": None}

    def lines_(lines):
        for ln in lines:
            if ln.d == "when" and lines is common:
                v = r.read(int(ln.a[0]))
                vals, as_ = when_of(ln)
                if not in_values(vals, v):
                    raise Fail("no-kind")
                if as_:
                    ent[as_] = v
            elif ln.d == "field":
                ent.setdefault(ln.a[0], r.read(int(ln.a[1])))
            elif ln.d == "const":
                r.read(int(ln.a[0]))
            elif ln.d == "length":
                n = r.read(int(ln.a[0]))
                assert [x.d for x in ln.body] == ["inner"]
                sub = Bits()
                sub.b = r.b[r.at:r.at + 8 * n]
                r.at += 8 * n
                inner = ln.body[0].a[0]
                e, k, _ = dec_bits(inner[len(PREFIX):], sub)
                for key, v in e.items():
                    ent.setdefault(key, v)
                state["inner"] = k
            else:
                assert ln.d in ("when", "requires"), ln.d

    lines_(common)
    for k, lines in kinds:
        at, bound = r.at, {}
        try:
            for ln in lines:
                if ln.d == "when":
                    v = r.read(int(ln.a[0]))
                    vals, as_ = when_of(ln)
                    if not in_values(vals, v):
                        raise Fail("no-kind")
                    if as_:
                        bound[as_] = v
        except Fail:
            r.at = at
            continue
        ent.update(bound)
        lines_(lines)
        return ent, (PREFIX + name, k), state["inner"]
    if kinds:
        raise Fail("no-kind")
    return ent, None, state["inner"]


def enc_bits(name, ent, kind_rec, inner_rec, layer=False):
    fmt, out = PREFIX + name, Bits()
    _, _, common, kinds = parse(name)
    recorded = None
    for rec in ((inner_rec, kind_rec) if layer else (kind_rec, inner_rec)):
        if recorded is None and rec and rec[0] == fmt:
            recorded = rec[1]
    lines = choose(name, ent, recorded)[1] if kinds else []
    dflt = {ln.a[0]: int(ln.a[1]) for ln in common + lines if ln.d == "default"}

    def content(ls):
        return any((ln.d == "field" and (ln.a[0] in ent or ln.a[0] in dflt)) or content(ln.body) for ln in ls)

    def put(ls):
        names, also = {}, {}
        for i, ln in enumerate(ls):
            if ln.d == "presence":
                n = int(ln.a[1])
                names[ln.a[0]] = [any(x.d == "if" and "%s.%d" % (ln.a[0], j) in x.a and content(x.body)
                                      for x in ls) for j in range(1, n + 1)]
                for b in names[ln.a[0]]:
                    out.write(1, int(b))
            elif ln.d == "if":
                if all(names[c.strip("!").split(".")[0]][int(c.split(".")[1]) - 1] != c.startswith("!") for c in ln.a):
                    put(ln.body)
            elif ln.d == "when":
                vals, as_ = when_of(ln)
                v = ent[as_] if as_ in ent else int(vals[0][0])
                if not in_values(vals, v):
                    raise Fail("transform-encode")
                out.write(int(ln.a[0]), v)
            elif ln.d == "field":
                v = ent.get(ln.a[0])
                if v is None and i + 1 < len(ls) and ls[i + 1].d == "also":
                    v = ent.get(ls[i + 1].a[0])
                also[ln.a[0]] = v = dflt.get(ln.a[0], 0) if v is None else v
                if not 0 <= v < 1 << int(ln.a[1]):
                    raise Fail("transform-encode")
                out.write(int(ln.a[1]), v)
            elif ln.d == "const":
                out.write(int(ln.a[0]), int(ln.a[1]))
            elif ln.d == "switch":
                body = [b for vals, b in ln.cases if vals is None or str(also[ln.a[0]]) in vals][0]
                put(body)
            elif ln.d == "group":
                assert not ent.get(ln.a[0])
                out.write(int(ln.a[2]), 0)
            elif ln.d == "length":
                assert [x.d for x in ln.body] == ["inner"]
                h = layer_hex(ln.body[0])
                out.write(int(ln.a[0]), len(h) // 2)
                out.b += Bits(h).b
            elif ln.d == "inner":
                out.b += Bits(layer_hex(ln)).b
            else:
                assert ln.d in ("also", "default", "requires"), ln.d

    def layer_hex(ln):
        inner = ln.a[0][len(PREFIX):]
        if inner not in PACKS:
            raise Fail("unknown-format")
        return enc_bits(inner, ent, kind_rec, inner_rec, layer=True)

    put(common)
    put(lines)
    return out.hex()


def decode(name, text):
    wire, root, common, kinds = parse(name)
    if wire == "bits":
        return dec_bits(name, Bits(text))
    if wire == "xml":
        m = re.fullmatch(r'<(\w+)(?: x="(\d+)")?/>', text)
        if m.group(1) != root:
            raise Fail("no-kind" if kinds else "missing-root")
        return ({"probe.x": int(m.group(2))} if m.group(2) else {}), (PREFIX + name, kinds[0][0]) if kinds else None, None
    obj, kind, lines = json.loads(text), None, []
    for k, kl in kinds:
        if all(obj.get(ln.a[0]) == ln.a[1] for ln in kl if ln.d == "when"):
            kind, lines = (PREFIX + name, k), kl
            break
    else:
        if kinds:
            raise Fail("no-kind")
    ent = {}
    for ln in common + lines:
        if ln.d == "field" and ln.a[1] in obj and str(obj[ln.a[1]]) != opt(ln, "absent"):
            ent[ln.a[0]] = obj[ln.a[1]]
        elif ln.d == "group" and ln.a[1] in obj:
            ent[ln.a[0]] = [{f.a[0]: o[f.a[1]] for f in ln.body if f.a[1] in o} for o in obj[ln.a[1]]]
    return ent, kind, None


def encode(name, ent, kind_rec, inner_rec):
    wire, root, common, kinds = parse(name)
    if wire == "bits":
        return enc_bits(name, ent, kind_rec, inner_rec)
    rec = kind_rec[1] if kind_rec and kind_rec[0] == PREFIX + name else None
    lines = common + (choose(name, ent, rec)[1] if kinds else [])
    if wire == "xml":
        return "<%s%s/>" % (root, ' x="%d"' % ent["probe.x"] if "probe.x" in ent else "")
    dflt = {ln.a[0]: int(ln.a[1]) for ln in lines if ln.d == "default"}
    out = {}
    for ln in lines:
        if ln.d == "when":
            out[ln.a[0]] = ln.a[1]
        elif ln.d == "const":
            out[ln.a[0]] = int(ln.a[1])
        elif ln.d == "field":
            if opt(ln, "with") and opt(ln, "with") not in ent:
                continue
            v = ent.get(ln.a[0], dflt.get(ln.a[0]))
            if v is None and opt(ln, "absent"):
                v = int(opt(ln, "absent"))
            if v is not None:
                if ln.a[2] == "bool":
                    if v not in (0, 1):
                        raise Fail("transform-encode")
                    v = bool(v)
                out[ln.a[1]] = v
        elif ln.d == "group" and ln.a[0] in ent:
            out[ln.a[1]] = [{f.a[1]: o[f.a[0]] for f in ln.body if f.a[0] in o} for o in ent[ln.a[0]]]
    return json.dumps(out, separators=(",", ":"))


def convert(frm, to, text, context):
    ent, kind, inner = decode(frm, text)
    if context is not None or frm != to:
        for k, v in (context or {}).items():
            if k == "probe.nosuch":
                raise Fail("undeclared-key")
            if not re.fullmatch(r"-?\d+", v):
                raise Fail("key-type-mismatch")
            ent.setdefault(k, int(v))
        if "probe.n" in ent:
            ent.setdefault("probe.n_copy", ent["probe.n"])     # the one derivation a target here maps
    if frm != to:
        _, _, common, kinds = parse(to)
        named = set(inner_lines(common)).union(*[inner_lines(k) for _, k in kinds])
        if kind and kind[0] not in named:
            kind = None
        if inner and inner[0] != PREFIX + to and inner[0] not in named:
            inner = None
        check(to, ent, kind, inner)
    return encode(to, ent, kind, inner)


# ------------------------------------------------------------------------------
# the vectors
# ------------------------------------------------------------------------------
def build(sink):
    model = gtcheck.Model()
    targets = set()
    for m in ("core", "probe"):
        text = sink.read("model/%s.def" % m)
        model.add(text)
        targets |= {r.split()[1] for r in text.splitlines() if r.split()[:1] == ["derive"]}
    for name in PACKS:
        comment, wire, body = PACKS[name]
        sink.write("packs/%s%s/pack.def" % (PREFIX, name), pack_text(name))
        gtcheck.load_pack(pack_text(name), model, name)
        # the one derived key a pack here names is n_copy
        assert targets & set(re.findall(r"[a-z0-9_.]+", body)) <= {"probe.n_copy"}, name
    originals = dict(PACKS)
    for name in PACKS:             # the parser above closes a switch's last arm by a line of its own
        comment, wire, body = originals[name]
        PACKS[name] = (comment, wire, parse_end_fix(name))
    nums, written = {}, {}

    def vec(frm, to, name, inp, expect=None, error=None, model_=None, context=None, ref=""):
        try:
            got, failed = convert(frm, to, inp, context), None
        except Fail as e:
            got, failed = None, e.kind
        assert (got, failed) == (expect, error), (name, expect, error, got, failed)
        if model_:
            ent, kind, inner = decode(frm, inp)
            have = {k: str(v) for k, v in ent.items()}
            have.update({"@kind": kind and kind[1], "@inner_kind": inner and inner[1]})
            for k, v in model_.items():
                assert have.get(k) == v if k != "@absent" else not set(v) & set(ent), (name, k, v, have)
        d = {"name": name, "from": PREFIX + frm, "to": PREFIX + to, "input": inp}
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model_:
            d["model"] = model_
        if context is not None:
            d["context"] = context
        d["source"] = "constructed"
        d["reference"] = "spec 0.94, " + ref
        emit(frm, name, d)

    def emit(frm, name, d):
        nums[frm] = nums.get(frm, 0) + 1
        sink.write("packs/%s%s/vectors/%02d-%s.json" % (PREFIX, frm, nums[frm], name),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[PREFIX + frm] = nums[frm]

    NK = "no-kind"

    def s(to, name, inp, expect=None, error=None, ref="", **kw):
        vec("src", to, "%s-%s" % (to, name), inp, expect, error, ref=ref, **kw)

    # -- Rule: the entity holds a key of the kind. `one` always writes t, the
    # sentinel 255 of z, the default 5 of d and the constant 7.
    H, K = "Rule, Holds: ", "Rule, Keys of a kind: "
    s("one", "zero-counts", '{"x":0}', '{"t":"k","x":0,"z":255,"d":5,"c":7}', ref=H + "0 is held")
    s("one", "empty-text-counts", '{"s":""}', '{"t":"k","s":"","z":255,"d":5,"c":7}', ref=H + "the empty text is held")
    s("one", "value-equal-to-a-sentinel-counts", '{"z":255}', '{"t":"k","z":255,"d":5,"c":7}',
      ref=H + "255 is held, and equals the target's sentinel")
    s("one", "only-sentinel-default-and-constant", "{}", error=NK, ref=H + "a default, a const and a when value are not held")
    s("one", "key-of-no-line", '{"n":1}', error=NK, ref="Rule: n is no key of the kind")
    s("one", "residue-only", '{"foo":1}', error=NK, ref=H + "residue does not count")
    s("one", "suppressed-line-counts", '{"w":3}', '{"t":"k","z":255,"d":5,"c":7}',
      ref=K + "a line that `with` suppresses is included")
    s("one", "key-named-by-with-does-not-count", '{"c1":1}', error=NK, ref=K + "a key does not count by being named by `with`")
    s("one", "key-text-is-literal", '{"lat":1.5}', error=NK, ref=K + "`lat` is held and `core.lat` is mapped: literal text")
    s("one", "list-with-an-item", '{"recs":[{"x":4}]}', '{"t":"k","z":255,"d":5,"c":7,"recs":[{"x":4}]}',
      ref=H + "a list with one item")
    s("one", "list-with-an-item-that-holds-no-key", '{"recs":[{}]}', '{"t":"k","z":255,"d":5,"c":7,"recs":[{}]}',
      ref=H + "whether or not its items hold a key")
    s("one", "list-with-no-item", '{"recs":[]}', error=NK, ref=H + "a list counts when it has at least one item")
    s("list", "item-key-does-not-count", '{"x":1}', error=NK, ref=K + "the keys of a group's items do not count")
    s("list", "list-counts-by-its-entry", '{"recs":[{"x":1}]}', '{"t":"k","recs":[{"x":1}]}', ref=K + "recs[]")
    s("y", "absent-by-a-sentinel-of-the-source", '{"y":99}', error=NK, model_={"@absent": ["probe.y"]},
      ref=H + "a key left absent by a sentinel does not count")
    s("y", "held", '{"y":98}', '{"t":"k","y":98}', ref="Rule")
    s("y", "context-only", "{}", '{"t":"k","y":4}', context={"probe.y": "4"}, ref=H + "a value the context gave")
    s("y", "context-of-another-key", "{}", error=NK, context={"probe.z": "4"}, ref="Rule: after the context")
    s("y", "empty-context", "{}", error=NK, context={}, ref="Rule")
    s("derived", "derived-only", '{"n":4}', '{"t":"k","c":4}', ref=H + "a value a derivation gave (n_copy)")
    s("derived", "nothing-derived", '{"x":4}', error=NK, ref="Rule: after the derivations")
    s("common", "key-of-the-common-lines", '{"n":4}', '{"n":4,"t":"k"}', ref="one held key is enough, a common one included")
    s("common", "no-key", '{"y":4}', error=NK, ref="Rule")
    # as: common 5,6 as w; a 1..3 as x, y; b 9, z
    s("as", "as-key-of-the-kind", '{"x":2}', "050200", ref=K + "ruling 24 of 0.30; ruling 1")
    s("as", "common-as-key", '{"w":6}', "060900", ref=K + "a common `as` key; b is chosen (a needs x)")
    s("as", "field-key", '{"z":4}', "050904", ref="Rule")
    s("as", "key-of-a-kind-not-chosen", '{"y":4}', error=NK, ref="ruling 1: b is chosen (a needs x) and y is a key of a")
    s("also", "also-key", '{"y":3}', "0703", ref=K + "6a of 0.11 lists an `also` key")
    # block: p.1 (x), p.2 (default 9): 11, 00001001, 000000: c2 40
    s("block", "key-of-a-block-not-written", '{"x":5}', "07c240", ref=K + "whether or not a block is written: p.2 is set "
      "by the default of y, so the block of x is not")
    # case: x absent writes 00: else
    s("case", "key-of-a-case-not-written", '{"z":5}', "0700", ref=K + "whether or not a case is written")
    s("case", "key-the-switch-names", '{"x":1}', "070100", ref=K + "x counts by the line that maps it")
    s("case", "no-key", '{"y":1}', error=NK, ref="Rule")

    # -- Rulings 1 and 3
    s("two", "next-kind-not-tried", '{"y":1}', error=NK, ref="ruling 1: first is chosen, and refused; second maps y")
    s("two", "first-kind", '{"x":1}', '{"t":"one","x":1}', ref="Rule")
    s("nomap", "requires-with-a-value", '{"x":1}', '{"t":"p"}', ref="ruling 3: x, which no line maps, is held")
    s("nomap", "requires-of-another-value", '{"x":2}', error=NK, ref="ruling 3: r is chosen, and has no key")
    s("nomap", "requires-without-a-value", '{"y":2}', '{"t":"q"}', ref="ruling 3: y, which no line maps, is held")
    s("nomap", "no-requires", '{"n":1}', error=NK, ref="ruling 3: a kind that maps no key")
    s("reqlist", "requires-a-list-with-an-item", '{"recs":[{}]}', '{"t":"k"}', ref="ruling 3: a list with an item")
    s("reqlist", "requires-met-by-an-empty-list", '{"recs":[],"w":1}', error=NK,
      ref="ruling 1: an empty list meets a plain `requires`, so k is chosen, and then refused; the next kind is not tried")

    # -- Ruling 2
    for name, ctx, out in (("no-context", None, '{"t":"one"}'), ("empty-context", {}, '{"t":"one"}'),
                           ("context-of-no-key", {"probe.n": "4"}, '{"t":"one"}'),
                           ("context-of-its-key", {"probe.x": "4"}, '{"t":"one","x":4}')):
        vec("two", "two", "same-format-" + name, '{"t":"one"}', out, model_={"@kind": "first"}, context=ctx,
            ref="ruling 2: the same format, with or without context, is unchanged")
    vec("two", "y", "to-another-format", '{"t":"one"}', error=NK, ref="Rule")

    # -- Ruling 5
    s("two", "undeclared-context-key-first", "{}", error="undeclared-key", context={"probe.nosuch": "1"},
      ref="ruling 5: context errors come before it")
    s("two", "context-value-of-another-type-first", "{}", error="key-type-mismatch", context={"probe.n": "a"},
      ref="ruling 5: context errors come before it")
    s("err", "before-an-encode-error", '{"y":1}', error=NK, ref="ruling 5: ahead of every encode error (the default 7 is no bool)")
    s("err", "encode-error-when-held", '{"x":7}', error="transform-encode", ref="ruling 5: x is held, and 7 is no bool")
    s("outmissing", "before-the-inner-checks", '{"x":1}', error=NK,
      ref="Rule: an inner pack that does not pass 0.34's checks adds nothing; ruling 5")
    s("outmissing", "inner-checks-when-held", '{"w":1}', error="unknown-format", ref="ruling 5: w is held; 0.34 check 1")

    # -- Ruling 4: packs without message kinds
    s("none", "no-message-kinds", '{"x":1}', "{}", ref="ruling 4: a pack without message kinds is not checked")
    s("items", "kinds-in-a-group-body-only", '{"x":1}', "00", ref="ruling 4: kinds in a group body only")
    emit("src", "geojson-no-position", {
        "name": "geojson-no-position", "from": PREFIX + "src", "to": "geojson", "input": '{"n":1}',
        "expect": '{"type":"Feature","geometry":null,"properties":{}}', "source": "constructed",
        "reference": "spec 0.94, ruling 4: an empty GeoJSON Feature (0.1.1 rulings 4 and 5)"})

    # -- 0.34: the inner pack's keys. in: data 2 (requires x) x; ping 1; extra 3, z
    I = K + "the model_keys of the inner pack; "
    s("out", "inner-key", '{"x":5}', "07020205", ref=I + "x")
    s("out", "inner-key-of-a-kind-not-chosen", '{"z":5}', "070101", ref=I + "whichever inner kind encode will choose: z is of "
      "extra, and ping is chosen; ruling 4: the kind of an inner message is not checked")
    s("out", "no-key", '{"y":5}', error=NK, ref="Rule")
    s("outcommon", "inner-key-of-the-common-lines", '{"x":5}', "0202050700", ref=I + "an inner line of the common lines")
    s("outother", "inner-line-of-another-kind", '{"x":5}', error=NK, ref=I + "first is chosen; the inner line is in second")
    # -- ruling 4: a kept kind
    R4 = "ruling 4, a kept kind: "
    vec("in", "out", "inner-to-outer", "01", "070101", model_={"@kind": "ping"},
        ref=R4 + "Entity.kind names the format of an inner line of the chosen kind")
    vec("in", "outcommon", "inner-to-outer-common-lines", "01", "01010700", ref=R4 + "of the common lines")
    vec("in", "outother", "inner-line-of-another-kind", "01", error=NK,
        ref=R4 + "kept by 0.34, but the inner line is in a kind that is not chosen")
    vec("in", "y", "to-a-format-without-an-inner-line", "01", error=NK, ref="Rule: Entity.kind is cleared")
    vec("out", "in", "outer-to-inner", "070101", "01", model_={"@kind": "carry", "@inner_kind": "ping"},
        ref=R4 + "Entity.inner_kind names `to`")
    vec("out", "outcommon", "outer-to-outer", "070101", "01010700", ref=R4 + "Entity.inner_kind names the inner format of the other")
    vec("out", "outother", "outer-to-outer-inner-line-of-another-kind", "070101", error=NK,
        ref=R4 + "the inner line is in a kind that is not chosen")
    vec("out", "y", "outer-to-a-format-without-an-inner-line", "070101", error=NK, ref="Rule")

    # -- Ruling 6: the table, cell by cell (go is n; a, b, uid are x, y, uid)
    T = "ruling 6, the table: "
    table = [("only-uid", '{"id":"u"}', None, "{}", None, None),
             ("only-go", '{"n":1}', None, "{}", "{}", None),
             ("go-as-context", "{}", {"probe.n": "1"}, "{}", "{}", None),
             ("only-a", '{"x":1}', None, "{}", None, '{"a":1}'),
             ("only-b-and-uid", '{"id":"u","y":2}', None, "{}", None, '{"b":2,"id":"u"}')]
    for name, inp, ctx, *cells in table:
        for to, out in zip(("none", "clear", "by"), cells):
            s(to, "table-" + name, inp, out, None if out else NK, context=ctx, ref=T + name)
    for to, kind in (("none", None), ("clear", "clear"), ("by", "by-a")):
        vec(to, to, "table-the-same-format", "{}", "{}", model_={"@kind": kind} if kind else None, ref=T + "the same format's {}")
    vec("by", "by", "message-of-b-decodes-as-the-first-kind", '{"b":2}', '{"b":2}', model_={"@kind": "by-a", "probe.y": "2"},
        ref="ruling 6: a message that holds only b decodes as by-a, and the round trip keeps the bytes")
    vec("xml", "xml", "wrong-root-without-kinds", "<Q/>", error="missing-root", ref="ruling 6: without kinds")
    vec("xmlkind", "xmlkind", "wrong-root-with-a-kind", "<Q/>", error=NK, ref="ruling 6: `no-kind` instead of `missing-root` (0.6)")
    vec("xmlkind", "xmlkind", "same-format-holds-nothing", "<R/>", "<R/>", model_={"@kind": "by-x"}, ref="ruling 6")
    s("xmlkind", "held", '{"x":3}', '<R x="3"/>', ref="ruling 6")
    s("xmlkind", "not-held", '{"y":3}', error=NK, ref="ruling 6: by the choice of `requires`")
    # as an inner pack: clearin is 05; outclear 07, w, length, clearin
    vec("outclear", "outclear", "inner-kind-recorded", "07090105", "07090105",
        model_={"@kind": "k", "@inner_kind": "clear", "probe.w": "9"}, ref="ruling 6: as an inner pack it records inner_kind")
    s("outclear", "layer-without-a-kept-kind", '{"w":9}', error=NK, ref="ruling 6: encoding it as a layer can be no-kind")
    s("outclear", "layer-requires-held", '{"w":9,"n":1}', "07090105", ref="ruling 6: the layer's `requires` is held")
    vec("clearin", "outclear", "layer-with-a-kept-kind", "05", "07000105", model_={"@kind": "clear"},
        ref="ruling 6: unless a kind is kept; ruling 4")

    PACKS.update(originals)
    for name in PACKS:
        rel = "packs/%s%s/vectors" % (PREFIX, name)
        for f in sink.listdir(rel):
            if rel + "/" + f not in sink.written:
                sink.remove(rel + "/" + f)
    return written


def main(argv=None):
    return genio.vector_main("conformance-held-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
