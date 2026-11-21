#!/usr/bin/env python3
"""Write the vectors of spec 0.33, a kind decided by a field after other
fields (`when <len> <values> at <offset> [as <key>]`): the packs
`conformance-lookahead-*` and the load vectors from 3300.

Every expected value here is worked out by hand from the spec text (Version
0.33 and its rulings 1 to 11, Version 0.30 for `as`, and the sections they
cite: 0.5 kinds, 0.6 constants and defaults, 0.8 sequential lines, `length`
and rulings 7, 9, 10, 14 and 18, 0.11 ruling 5b, 0.20 rulings 3, 19, 29 and
33 and `switch`, 0.21 `rest` and rulings 11 and 32, 0.22 ruling 12). The hand
working is the comment above each vector, bits written most significant
first unless the pack says `lsb`, and the value is written out literally.

It is checked against a second computation: a small codec below parses the
pack texts with its own parser and applies the rules to the input. It covers
only the lines these packs use. Load vectors are checked by a second small
checker of the 0.33 load rules (the `at` form, the token order, the fixed
window, the check order of ruling 10), and the same pack with every token
after a `when` line's values removed is loaded by tools/gen/gtcheck.py, so
an expected refusal comes from the 0.30 or 0.33 tokens alone and an expected
load is otherwise valid. Nothing here imports or calls an engine.

The readings first reported with these vectors are now rulings 12 to 18 of
0.33: which bits a held key wrote (12), a partial cover (13), the header
checks before any `at` error (14), `at` as a keyword only in a sequential
`when` (15), the fixed-window check after the file (16), ruling 6 amending
0.8 for `when` lines (17), and the extent of a message kind (18). The Encode
rule settles a window by its bits as written first, then by the value it
would write, compared only with the bits a held key wrote.

Inputs: none but this file and model/probe.def. Writes the pack.def files of
the `conformance-lookahead-*` packs, their vectors, and the load vectors
3300 onward. With --check nothing is written and the exit status is 1 when a
committed file differs from what this script writes.

Usage: python3 -I tools/gen/conformance-lookahead-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

PREFIX = "conformance-lookahead-"
SOURCE = '"goat-transformers spec/engine-spec.md (synthetic probe format, no external standard)"'
FIRST_LOAD = 3300


def head(name, wire="bits", order="msb"):
    out = ["format     %s%s" % (PREFIX, name), "version    0.33.0", "distribution public",
           "source  " + SOURCE, "uses       probe", "wire       " + wire]
    if wire == "bits":
        out += ["layout     sequential", "bit_order  " + order]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------------------
# the packs
# ------------------------------------------------------------------------------
PACKS = {}

PACKS["bits"] = """\
# Conformance probe pack for a kind decided by a field after other fields
# (spec 0.33, `when <len> <values> at <offset>`), most significant bit first.
# Public. One common byte, then a body whose second byte is the kind code;
# the first body byte means a different key in each kind.
#
#   byte 0      n
#   kind a      x (8), the kind code 1 (8, a `pad`), y (8)
#   kind b      z (8, two's complement), the kind code 2 (8, a `pad`), w (16)
#   kind c      the code 5 (4), the code 6 (4), the kind code 3 (8, a `pad`), c1 (8)
#
# Kind c interleaves plain `when` lines with a look-ahead one (ruling 2): its
# offset 8 counts from kind start, not from the cursor after the first nibble.
""" + head("bits") + """\
field   probe.n  8  uint
kind    a
when    8  1  at 8
field   probe.x  8  uint
pad     8
field   probe.y  8  uint
kind    b
when    8  2  at 8
field   probe.z  8  twos
pad     8
field   probe.w  16  uint
kind    c
when    4  5
when    8  3  at 8
when    4  6
pad     8
field   probe.c1  8  uint
"""

PACKS["lsb"] = """\
# Conformance probe pack for a look-ahead window in the pack's bit order
# (spec 0.33 ruling 8), least significant bit first. Public.
#
#   byte 0      n
#   byte 1      x in kind a, y in kind b; its bits 4 to 7 (the high nibble
#               under lsb) are the kind code: 5 for a, 10 for b
""" + head("lsb", order="lsb") + """\
field   probe.n  8  uint
kind    a
when    4  5  at 4
field   probe.x  8  uint
kind    b
when    4  10  at 4
field   probe.y  8  uint
"""

PACKS["swap"] = """\
# Conformance probe pack for a look-ahead window over a swapped field (spec
# 0.33 ruling 8), most significant bit first. Public.
#
#   byte 0      n
#   bytes 1-2   x in kind a, y in kind b, each a little-endian 16-bit field
#               (`swap`); the first byte on the wire, raw, is the kind code:
#               18 (0x12) for a, 52 (0x34) for b
""" + head("swap") + """\
field   probe.n  8  uint
kind    a
requires probe.x
when    8  18  at 0
field   probe.x  16  uint  swap
kind    b
requires probe.y
when    8  52  at 0
field   probe.y  16  uint  swap
"""

PACKS["settle"] = """\
# Conformance probe pack for settling a look-ahead window on encode (spec
# 0.33, Encode, rulings 1 and 29 of 0.20, `as` of 0.30), most significant
# bit first. Public.
#
#   byte 0      n
#   kind full     x (8), y (8); the window is all of y: 1 or 2
#   kind part     z (8); the window is the low nibble of z: 3
#   kind several  c1 (8), c2 (8); the window is the low nibble of c1 and
#                 the high nibble of c2: 0x5a (90)
#   kind def      v3 (8), w (8, default 9); the window is all of w: 4
#   kind as       v2 (8), v4 (8); the window is all of v4: 5 to 7, bound to v1
""" + head("settle") + """\
field   probe.n  8  uint
kind    full
requires probe.y
when    8  1,2  at 8
field   probe.x  8  uint
field   probe.y  8  uint
kind    part
requires probe.z
when    4  3  at 4
field   probe.z  8  uint
kind    several
requires probe.c1 probe.c2
when    8  90  at 4
field   probe.c1  8  uint
field   probe.c2  8  uint
kind    def
requires probe.v3
when    8  4  at 8
default probe.w  9
field   probe.v3  8  uint
field   probe.w  8  uint
kind    as
when    8  5..7  at 8  as probe.v1
field   probe.v2  8  uint
field   probe.v4  8  uint
"""

PACKS["switch"] = """\
# Conformance probe pack for a switch on a key inside a look-ahead window
# (spec 0.33, Encode: windows are settled before a switch reads its key
# back), most significant bit first. Public.
#
#   byte 0      n
#   kind a      x (8), y (8: the window, 1 or 2), then by y: z (8) for 1,
#               w (16) for 2
""" + head("switch") + """\
field   probe.n  8  uint
kind    a
when    8  1,2  at 8
field   probe.x  8  uint
field   probe.y  8  uint
switch  probe.y
  case  1
    field  probe.z  8  uint
  case  2
    field  probe.w  16  uint
end
"""

PACKS["const"] = """\
# Conformance probe pack for a look-ahead window over a `const` (spec 0.33
# ruling 3), most significant bit first. Public.
#
#   byte 0      n
#   kind a      x (8), a `const 8 9` that the window 1 or 2 covers, y (8)
""" + head("const") + """\
field   probe.n  8  uint
kind    a
when    8  1,2  at 8
field   probe.x  8  uint
const   8  9
field   probe.y  8  uint
"""

PACKS["items"] = """\
# Conformance probe pack for look-ahead windows in item kinds (spec 0.33
# ruling 4), most significant bit first. Public.
#
#   byte 0      n
#   byte 1      the number of recs
#   each rec    x (8), then by kind
#     pt        y (8), the kind code 1 (8, a `pad`)
#     tx        a two-character label (16), the kind code 2 (8, a `pad`)
#
# Each item's kind start is after its own x.
""" + head("items") + """\
field   probe.n  8  uint
group   probe.recs count 8
  field  probe.x  8  uint
  kind   pt
  when   8  1  at 8
  requires probe.y
  field  probe.y  8  uint
  pad    8
  kind   tx
  when   8  2  at 16
  requires probe.label
  field  probe.label  16  ascii
  pad    8
end
"""

PACKS["overlap"] = """\
# Conformance probe pack for two look-ahead windows that overlap, and a
# window over a plain `when` of the same kind with another value (spec 0.33
# ruling 5), most significant bit first. Public.
#
#   byte 0      n
#   kind a      x (8), a `pad 8` that two windows cover: the whole byte
#               18 or 21, then its low nibble 5 or 6
#   kind b      the code 9 (4, a plain `when`), a `pad 4`, w (8); a window
#               over the first byte has the value 55 (0x37), whose high
#               nibble is not 9
""" + head("overlap") + """\
field   probe.n  8  uint
kind    a
requires probe.x
when    8  18,21  at 8
when    4  5,6  at 12
field   probe.x  8  uint
pad     8
kind    b
requires probe.w
when    4  9
when    8  55  at 0
pad     4
field   probe.w  8  uint
"""

PACKS["end"] = """\
# Conformance probe pack for look-ahead windows past the end of the input
# (spec 0.33 ruling 6), most significant bit first. Public.
#
#   byte 0      n
#   kind long   x (8), y (16), z (8); the window is all of y: 2313 (0x0909)
#   kind wide   two plain `when` bytes 255, w (8)
#   kind short  c1 (8); the window is the high nibble of c1: 0 to 15
""" + head("end") + """\
field   probe.n  8  uint
kind    long
when    16  2313  at 8
field   probe.x  8  uint
field   probe.y  16  uint
field   probe.z  8  uint
kind    wide
when    8  255
when    8  255
field   probe.w  8  uint
kind    short
when    4  0..15  at 0
field   probe.c1  8  uint
"""

PACKS["extent"] = """\
# Conformance probe pack for look-ahead windows of item kinds inside a
# `length` extent (spec 0.33 rulings 6 and 7), most significant bit first.
# Public.
#
#   byte 0      n
#   byte 1      the length of the recs that follow, in bytes
#   each rec    x (8), then by kind, to the end of the length
#     a         y (8), the kind code 1 (8, a `pad`)
#     b         z (16); the window is bits 4 to 11 of z: 2
#   then        w (8)
""" + head("extent") + """\
field   probe.n  8  uint
length  8
  group  probe.recs rest
    field  probe.x  8  uint
    kind   a
    when   8  1  at 8
    field  probe.y  8  uint
    pad    8
    kind   b
    when   8  2  at 4
    field  probe.z  16  uint
  end
end
field   probe.w  8  uint
"""

PACKS["whole"] = """\
# Conformance probe pack for a look-ahead window beyond `length ... whole`
# (spec 0.33 ruling 6), most significant bit first. Public.
#
#   byte 0      the length of the whole message in bytes
#   kind long   x (8), y (8); the window is all of y: 7
#   kind short  z (8); no `when`, so it always holds
""" + head("whole") + """\
length  8  whole
kind    long
when    8  7  at 8
field   probe.x  8  uint
field   probe.y  8  uint
kind    short
field   probe.z  8  uint
"""

PACKS["json"] = """\
# Conformance probe pack: a flat JSON object of the integer keys of the
# `conformance-lookahead-*` bits packs (spec 0.33). Public. It is the source
# of the vectors that encode into those packs from another format, where
# the kind is chosen by `requires` and nothing on the entity records it.
""" + head("json", wire="json") + """\
field   probe.n   n   int
field   probe.x   x   int
field   probe.y   y   int
field   probe.z   z   int
field   probe.w   w   int
field   probe.c1  c1  int
field   probe.c2  c2  int
field   probe.v1  v1  int
field   probe.v2  v2  int
field   probe.v3  v3  int
field   probe.v4  v4  int
"""


PACKS["held"] = """\
# Conformance probe pack for the bits a held key wrote in a look-ahead
# window (spec 0.33 rulings 12 and 13), most significant bit first. Public.
#
#   byte 0           n
#   kind part        x (8), a `pad 4`, y (4); the window is the low nibble
#                    of x and the pad: 0x5a (90)
#   kind suppressed  y (8, written only with z), z (8); the window is all
#                    of y: 7
#   kind sentinel    w (8, absent 255), c1 (8); the window is all of w: 4
""" + head("held") + """\
field   probe.n  8  uint
kind    part
requires probe.x
when    8  90  at 4
field   probe.x  8  uint
pad     4
field   probe.y  4  uint
kind    suppressed
requires probe.y
when    8  7  at 0
field   probe.y  8  uint  with probe.z
field   probe.z  8  uint
kind    sentinel
requires probe.c1
when    8  4  at 0
field   probe.w  8  uint  absent 255
field   probe.c1  8  uint
"""

PACKS["text"] = """\
# Conformance probe pack for `at` as a value on a text wire (spec 0.33
# ruling 15). Public. The member t names the kind: the text "at" for a,
# "other" for b.
""" + head("text", wire="json") + """\
kind    a
when    t  at
field   probe.x  x  int
kind    b
when    t  other
field   probe.y  y  int
"""


# ------------------------------------------------------------------------------
# the second computation: a parser and codec of the lines these packs use
# ------------------------------------------------------------------------------
class Fail(Exception):
    """A conversion that fails with an error kind of the spec."""

    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


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


class Ln:
    def __init__(self, d, a):
        self.d, self.a = d, a
        self.body = []
        self.cases = []      # switch: [(values or None for else, body)]


HEADER = ("format", "version", "distribution", "source", "uses", "wire", "layout", "bit_order")
BLOCKS = ("group", "length", "switch", "opt", "if", "chain")


def parse(text):
    """(header dict, top lines). Blocks hold their lines in `body`."""
    hdr, root = {}, []
    stack = [("root", root)]
    for raw in text.splitlines():
        t = tokens_of(raw)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in HEADER:
            hdr[d] = a[0] if a else None
            continue
        if d == "end":
            if stack[-1][0] == "case":
                stack.pop()
            stack.pop()
            continue
        if d in ("case", "else"):
            if stack[-1][0] == "case":
                stack.pop()
            sw = stack[-1][1]
            body = []
            sw.cases.append((None if d == "else" else a[0], body))
            stack.append(("case", body))
            continue
        node = Ln(d, a)
        target = stack[-1][1]
        (target if isinstance(target, list) else target.body).append(node)
        if d == "switch":
            stack.append(("switch", node))
        elif d in BLOCKS and not (d == "length" and "whole" in a):
            stack.append(("block", node))
    return hdr, root


def split_kinds(lines):
    common, kinds = [], []
    for ln in lines:
        if ln.d == "kind":
            kinds.append((ln.a[0], []))
        elif kinds:
            kinds[-1][1].append(ln)
        else:
            common.append(ln)
    return common, kinds


def parse_values(text):
    out = []
    for v in text.split(","):
        lo, _, hi = v.partition("..")
        out.append((int(lo), int(hi or lo)))
    return out


def matches(values, v):
    return any(lo <= v <= hi for lo, hi in values)


def when_of(ln):
    """(len, values, at or None, as-key or None)."""
    a, at, as_ = ln.a, None, None
    i = 2
    while i < len(a):
        if a[i] == "at":
            at = int(a[i + 1])
        elif a[i] == "as":
            as_ = a[i + 1]
        i += 2
    return int(a[0]), parse_values(a[1]), at, as_


class Dec:
    def __init__(self, data, order):
        self.data, self.order, self.cur = data, order, 0
        self.end = 8 * len(data)

    def rd(self, pos, n):
        v = 0
        for i in range(n):
            p = pos + i
            bit = (self.data[p // 8] >> ((7 - p % 8) if self.order == "msb" else (p % 8))) & 1
            v = (v << 1) | bit if self.order == "msb" else v | (bit << i)
        return v


def field_value(raw, n, tr, opts, order):
    if "swap" in opts:
        assert order == "msb"
        raw = int.from_bytes(raw.to_bytes(n // 8, "big")[::-1], "big")
    if tr == "uint":
        return raw
    if tr == "twos":
        return raw - (1 << n) if raw >> (n - 1) else raw
    if tr == "ascii":
        b = raw.to_bytes(n // 8, "big").rstrip(b"\0")
        return b.decode("ascii")
    raise AssertionError(tr)


def field_raw(v, n, tr, opts):
    if tr == "uint":
        if not 0 <= v < (1 << n):
            raise Fail("transform-encode", "uint out of range")
        raw = v
    elif tr == "twos":
        if not -(1 << (n - 1)) <= v < (1 << (n - 1)):
            raise Fail("transform-encode", "twos out of range")
        raw = v & ((1 << n) - 1)
    elif tr == "ascii":
        b = v.encode("ascii")
        if len(b) > n // 8:
            raise Fail("transform-encode", "text too long")
        raw = int.from_bytes(b.ljust(n // 8, b"\0"), "big")
    else:
        raise AssertionError(tr)
    if "swap" in opts:
        raw = int.from_bytes(raw.to_bytes(n // 8, "big")[::-1], "big")
    return raw


def select(D, kinds, ent, limit):
    """0.33 Decode and rulings 2, 6: the first kind whose `when` lines all
    hold. A window reads at kind start plus its offset and does not move the
    cursor; a plain `when` reads at the cursor and moves it; any bit beyond
    `limit` makes the line not hold."""
    ks = D.cur
    for name, lines in kinds:
        c, ok, bound = ks, True, {}
        for ln in lines:
            if ln.d in ("requires", "default"):
                continue
            if ln.d != "when":
                break
            n, values, at, as_ = when_of(ln)
            pos = ks + at if at is not None else c
            if pos + n > limit:
                ok = False
                break
            v = D.rd(pos, n)
            if not matches(values, v):
                ok = False
                break
            if at is None:
                c += n
            if as_:
                bound[as_] = v
        if ok:
            D.cur = c
            ent.update(bound)
            return name, lines
    raise Fail("no-kind", "no kind holds at bit %d" % ks)


def skip_or_fail(D, n, limit, extent):
    """True when the line reads as absent (it starts at the end of an extent,
    ruling 7 of 0.8); malformed-wire when it straddles or is past the input."""
    if D.cur + n <= limit:
        return False
    if extent and D.cur >= limit:
        return True
    raise Fail("malformed-wire", "a line at bit %d passes the end at %d" % (D.cur, limit))


def dec_lines(D, lines, ent, lim, extent):
    for ln in lines:
        d = ln.d
        if d in ("when", "requires", "default"):
            continue
        if d == "field":
            key, n, tr, opts = ln.a[0], int(ln.a[1]), ln.a[2], ln.a[3:]
            if skip_or_fail(D, n, lim[0], extent):
                continue
            raw = D.rd(D.cur, n)
            D.cur += n
            if "absent" in opts and raw in [int(x) for x in opts[opts.index("absent") + 1].split(",")]:
                continue
            ent[key] = field_value(raw, n, tr, opts, D.order)
        elif d in ("pad", "const"):
            n = int(ln.a[0])
            if not skip_or_fail(D, n, lim[0], extent):
                D.cur += n
        elif d == "length" and "whole" in ln.a:
            n = int(ln.a[0])
            skip_or_fail(D, n, lim[0], False)
            stated = 8 * D.rd(D.cur, n)
            D.cur += n
            if stated > D.end or stated < D.cur:
                raise Fail("malformed-wire", "whole length")
            lim[0] = stated
        elif d == "length":
            n = int(ln.a[0])
            skip_or_fail(D, n, lim[0], extent)
            size = 8 * D.rd(D.cur, n)
            D.cur += n
            stop = D.cur + size
            if stop > lim[0]:
                raise Fail("malformed-wire", "length past the end")
            dec_lines(D, ln.body, ent, [stop], True)
            D.cur = stop
        elif d == "group":
            items = []
            if ln.a[1] == "count":
                n = int(ln.a[2])
                skip_or_fail(D, n, lim[0], extent)
                count = D.rd(D.cur, n)
                D.cur += n
                if count > lim[0] - D.cur:
                    raise Fail("malformed-wire", "count larger than the bits left")
                for _ in range(count):
                    items.append(dec_item(D, ln.body, lim, extent))
            elif ln.a[1] == "rest":
                while lim[0] - D.cur >= 8:
                    items.append(dec_item(D, ln.body, lim, extent))
            else:
                raise AssertionError(ln.a)
            ent[ln.a[0]] = items
        elif d == "switch":
            v = ent.get(ln.a[0])
            body = case_of(ln, v)
            dec_lines(D, body, ent, lim, extent)
        else:
            raise AssertionError(d)


def case_of(sw, v):
    other = None
    for values, body in sw.cases:
        if values is None:
            other = body
        elif v is not None and any(int(x) == v for x in values.split(",")):
            return body
    if other is None:
        raise Fail("no-kind", "no case holds %r" % (v,))
    return other


def dec_item(D, body, lim, extent):
    item = {}
    common, kinds = split_kinds(body)
    dec_lines(D, common, item, lim, extent)
    if kinds:
        name, lines = select(D, kinds, item, lim[0])
        item["@kind"] = name
        dec_lines(D, lines, item, lim, extent)
    return item


def decode(pack_text, inp):
    hdr, root = parse(pack_text)
    if hdr["wire"] == "json":
        obj = json.loads(inp)
        ent = {}
        common, kinds = split_kinds(root)
        lines = common
        if kinds:
            for name, kl in kinds:
                # 0.5: a `when` holds when the member is a string equal to the
                # value (a leading `=` stripped); ruling 15 of 0.33: `at` here
                # is a value
                if all(obj.get(w.a[0]) == w.a[1] for w in kl if w.d == "when"):
                    ent["@kind"] = name
                    lines = common + kl
                    break
            else:
                raise Fail("no-kind", "no json kind holds")
        for ln in lines:
            if ln.d == "field" and ln.a[1] in obj:
                ent[ln.a[0]] = int(obj[ln.a[1]])
        return ent
    D = Dec(bytes.fromhex(inp), hdr["bit_order"])
    ent, lim = {}, [D.end]
    common, kinds = split_kinds(root)
    dec_lines(D, common, ent, lim, False)
    if kinds:
        name, lines = select(D, kinds, ent, lim[0])
        ent["@kind"] = name
        dec_lines(D, lines, ent, lim, False)
    return ent


class Enc:
    def __init__(self, order):
        self.order, self.bits, self.held, self.cur = order, [], [], 0

    def wr(self, pos, n, v, held):
        while len(self.bits) < pos + n:
            self.bits.append(0)
            self.held.append(False)
        for i in range(n):
            self.bits[pos + i] = (v >> (n - 1 - i)) & 1 if self.order == "msb" else (v >> i) & 1
            self.held[pos + i] = held

    def rd(self, pos, n):
        v = 0
        for i in range(n):
            bit = self.bits[pos + i]
            v = (v << 1) | bit if self.order == "msb" else v | (bit << i)
        return v


def defaults_of(lines):
    return {ln.a[0]: int(ln.a[1]) for ln in lines if ln.d == "default"}


def choose(kinds, ent, recorded):
    """0.5 Encode, 0.30 implicit term: the recorded kind, else the first
    kind whose `requires` keys are held and whose `as` values match."""
    names = [k[0] for k in kinds]
    if recorded in names:
        return kinds[names.index(recorded)]
    for name, lines in kinds:
        ok = True
        for ln in lines:
            if ln.d == "requires" and not all(k in ent for k in ln.a):
                ok = False
            if ln.d == "when":
                n, values, at, as_ = when_of(ln)
                if as_ and not (as_ in ent and matches(values, ent[as_] & ((1 << n) - 1))
                                and ent[as_] >= 0):
                    ok = False
        if ok:
            return name, lines
    raise Fail("no-kind", "no kind qualifies")


def settle(E, lines, ks, ent):
    """0.33 Encode (rulings 1, 12, 13): each window of the selected kind, in
    line order. Bits as written that match (and agree with a held `as` key)
    stand. Otherwise the value is the held `as` value, else the first listed
    value; a bit of it that differs from a bit a held key wrote is
    transform-encode; else the value is written."""
    for ln in lines:
        if ln.d != "when":
            continue
        n, values, at, as_ = when_of(ln)
        if at is None:
            continue
        pos = ks + at
        assert pos + n <= len(E.bits), "a window not fixed"
        bits = E.rd(pos, n)
        if matches(values, bits) and not (as_ and as_ in ent and ent[as_] != bits):
            continue
        if as_ and as_ in ent:
            v = ent[as_]
            if not matches(values, v):
                raise Fail("transform-encode", "as value does not match")
        else:
            v = values[0][0]
        probe = Enc(E.order)
        probe.wr(0, n, v, False)
        for i in range(n):
            if E.held[pos + i] and E.bits[pos + i] != probe.bits[i]:
                raise Fail("transform-encode", "bit %d of the window value %d differs from a held key's bit" % (i, v))
        E.wr(pos, n, v, False)


def enc_lines(E, lines, ent, dflt, ctx):
    for ln in lines:
        d = ln.d
        if d in ("requires", "default"):
            continue
        if d == "when":
            n, values, at, as_ = when_of(ln)
            if at is None:
                v = ent[as_] if as_ and as_ in ent else values[0][0]
                E.wr(E.cur, n, v, False)
                E.cur += n
            continue
        if d == "field":
            key, n, tr, opts = ln.a[0], int(ln.a[1]), ln.a[2], ln.a[3:]
            ctx["pos"][key] = (E.cur, ln)
            if "with" in opts and opts[opts.index("with") + 1] not in ent:
                # 0.18: a suppressed line writes zero bits, as an absent key
                # with no default and no sentinel; not a held key's bits
                E.wr(E.cur, n, 0, False)
                E.cur += n
                continue
            if key not in ent and key not in dflt and "absent" in opts:
                # 0.9: an absent key writes its first sentinel
                E.wr(E.cur, n, int(opts[opts.index("absent") + 1].split(",")[0]), False)
                E.cur += n
                continue
            if key in ent:
                E.wr(E.cur, n, field_raw(ent[key], n, tr, opts), True)
            elif key in dflt:
                E.wr(E.cur, n, field_raw(dflt[key], n, tr, opts), False)
            else:
                E.wr(E.cur, n, 0, False)
            E.cur += n
        elif d == "const":
            E.wr(E.cur, int(ln.a[0]), int(ln.a[1]), False)
            E.cur += int(ln.a[0])
        elif d == "pad":
            E.wr(E.cur, int(ln.a[0]), 0, False)
            E.cur += int(ln.a[0])
        elif d == "length" and "whole" in ln.a:
            ctx["whole"] = (E.cur, int(ln.a[0]))
            E.wr(E.cur, int(ln.a[0]), 0, False)
            E.cur += int(ln.a[0])
        elif d == "length":
            n, p = int(ln.a[0]), E.cur
            E.wr(p, n, 0, False)
            E.cur += n
            start = E.cur
            enc_lines(E, ln.body, ent, dflt, ctx)
            while (E.cur - start) % 8:
                E.wr(E.cur, 1, 0, False)
                E.cur += 1
            size = (E.cur - start) // 8
            if size >= 1 << n:
                raise Fail("transform-encode", "length")
            E.wr(p, n, size, False)
        elif d == "group":
            items = ent.get(ln.a[0]) or []
            if ln.a[1] == "count":
                n = int(ln.a[2])
                E.wr(E.cur, n, len(items), False)
                E.cur += n
            for item in items:
                enc_item(E, ln.body, item, ctx["format"])
        elif d == "switch":
            ctx["settle"]()
            pos, fl = ctx["pos"][ln.a[0]]
            n = int(fl.a[1])
            v = field_value(E.rd(pos, n), n, fl.a[2], fl.a[3:], E.order)
            enc_lines(E, case_of(ln, v), ent, dflt, ctx)
        else:
            raise AssertionError(d)


def enc_scope(E, body, ent, recorded, fmt):
    common, kinds = split_kinds(body)
    ctx = {"pos": {}, "settle": lambda: None, "format": fmt}
    dflt = defaults_of(common)
    enc_lines(E, common, ent, dflt, ctx)
    if kinds:
        name, lines = choose(kinds, ent, recorded)
        ks, done = E.cur, []

        def once():
            if not done:
                done.append(1)
                settle(E, lines, ks, ent)
        ctx["settle"] = once
        enc_lines(E, lines, ent, dict(dflt, **defaults_of(lines)), ctx)
        once()
    return ctx


def enc_item(E, body, item, fmt):
    rec = item.get("@kind")
    enc_scope(E, body, item, rec[1] if rec and rec[0] == fmt else None, fmt)


def encode(pack_text, ent):
    hdr, root = parse(pack_text)
    fmt = hdr["format"]
    if hdr["wire"] == "json":
        common, kinds = split_kinds(root)
        lines = common
        if kinds:
            rec = ent.get("@kind")
            lines = common + choose(kinds, ent, rec[1] if rec and rec[0] == fmt else None)[1]
        parts = []
        for ln in lines:
            if ln.d == "field" and ln.a[0] in ent:
                parts.append('"%s":%d' % (ln.a[1], ent[ln.a[0]]))
            elif ln.d == "when":
                parts.append('"%s":%s' % (ln.a[0], json.dumps(ln.a[1])))
        return "{" + ",".join(parts) + "}"
    E = Enc(hdr["bit_order"])
    rec = ent.get("@kind")
    ctx = enc_scope(E, root, ent, rec[1] if rec and rec[0] == fmt else None, fmt)
    while len(E.bits) % 8:
        E.bits.append(0)
        E.held.append(False)
    if "whole" in ctx:
        p, n = ctx["whole"]
        E.wr(p, n, len(E.bits) // 8, False)
    out = bytearray()
    for i in range(0, len(E.bits), 8):
        b = 0
        for j in range(8):
            b |= E.bits[i + j] << ((7 - j) if E.order == "msb" else j)
        out.append(b)
    return out.hex()


def tag_kinds(ent, fmt):
    """Entity.kind and Item.kind record the format with the kind name."""
    if "@kind" in ent:
        ent["@kind"] = (fmt, ent["@kind"])
    for v in ent.values():
        if isinstance(v, list):
            for item in v:
                tag_kinds(item, fmt)
    return ent


def model_of(ent, prefix=""):
    out = {}
    for k, v in ent.items():
        if k == "@kind":
            out[prefix + k] = v[1]
        elif isinstance(v, list):
            out[prefix + k + ".#"] = str(len(v))
            for i, item in enumerate(v):
                out.update(model_of(item, "%s%s[%d]." % (prefix, k, i)))
        else:
            out[prefix + k] = str(v)
    return out


# ------------------------------------------------------------------------------
# the second computation for load vectors: the 0.33 load rules
# ------------------------------------------------------------------------------
def module_keys(texts):
    keys = {}
    for text in texts:
        mod = None
        for raw in text.splitlines():
            t = tokens_of(raw)
            if t and t[0] == "module":
                mod = t[1]
            elif t and t[0] == "key":
                keys[mod + "." + t[1] if mod != "core" else t[1]] = t[2]
            elif t and t[0] == "list":
                keys[mod + "." + t[1]] = "list"
    return keys


KNOWN = set(HEADER) | set(BLOCKS) | {"kind", "when", "requires", "field", "const", "default", "end",
                                     "case", "else", "pad", "align", "presence", "also", "fx", "count",
                                     "word_bytes", "root", "map", "typemap"}


def walk_all(lines):
    for ln in lines:
        yield ln
        yield from walk_all(ln.body)
        for _, body in ln.cases:
            yield from walk_all(body)


def at_errors(text, models):
    """The error kind this text fails with under the 0.33 rules and their
    order (ruling 10), or None. Only the causes the load vectors here use."""
    lines = [tokens_of(r) for r in text.splitlines()]
    for t in lines:
        if t and t[0] not in KNOWN:
            return "unknown-directive"
    hdr, root = parse(text)
    for need in ("format", "version", "wire"):
        if need not in hdr:
            return "missing-" + need
    # ruling 14: the 0.4 order puts these before the key passes, and the key
    # passes before every `at` error (ruling 10)
    for need in ("distribution", "source"):
        if need not in hdr:
            return "missing-" + need
    keys = module_keys(models)
    uses = {hdr.get("uses")} | {"core"}
    named = []
    for ln in walk_all(root):
        if ln.d in ("field", "also", "default"):
            named.append(ln.a[0])
        elif ln.d == "requires":
            named += [k.split("=")[0] for k in ln.a]
        elif ln.d == "when" and "as" in ln.a[2:]:
            i = ln.a.index("as", 2)
            if i + 1 < len(ln.a):
                named.append(ln.a[i + 1])
    for k in named:
        if "." in k and k.split(".")[0] not in uses:
            return "module-not-used"
    for k in named:
        if k not in keys:
            return "undeclared-key"
    for ln in walk_all(root):        # 0.30: the type of an `as` key
        if ln.d == "when" and "as" in ln.a[2:]:
            i = ln.a.index("as", 2)
            if i + 1 < len(ln.a) and keys.get(ln.a[i + 1]) != "int":
                return "key-type-mismatch"
    sequential = hdr.get("layout") == "sequential" and hdr["wire"] == "bits"
    # the `at` form and the token order: when <len> <values> [at <n>] [as <k>]
    for ln in walk_all(root):
        if ln.d != "when":
            continue
        rest = ln.a[2:]
        if "at" in rest and not sequential:
            return "bad-directive"
        if not sequential:
            continue
        if rest[:1] == ["at"]:
            if len(rest) < 2 or not rest[1].isdigit() or not rest[1].isascii() or int(rest[1]) >= 1 << 64:
                return "bad-directive"
            rest = rest[2:]
        if rest[:1] == ["as"]:
            if len(rest) != 2:
                return "bad-directive"
            rest = []
        if rest:
            return "bad-directive"
    # `at` on a common `when`: of the message, or of a group body
    bodies = [root] + [ln.body for ln in walk_all(root) if ln.d == "group"]
    for body in bodies:
        common, kinds = split_kinds(body)
        for ln in common:
            if ln.d == "when" and "at" in ln.a[2:]:
                return "bad-directive"
        # 0.21 rulings 11 and 32 with 0.33 ruling 9: a common `rest` group,
        # then a kind with `when` lines (with `at` or without)
        if any(ln.d == "group" and ln.a[1:2] == ["rest"] for ln in common) and \
                any(ln.d == "when" for _, kl in kinds for ln in kl):
            return "bad-directive"
        # the fixed window
        for _, kl in kinds:
            for wl in kl:
                if wl.d != "when" or "at" not in wl.a[2:]:
                    continue
                n, _, at, _ = when_of(wl)
                stop, total, fixed = at + n, 0, False
                for ln in kl:
                    if ln.d in ("requires", "default") or (ln.d == "when" and "at" in ln.a[2:]):
                        continue
                    if ln.d in ("when", "const", "pad"):
                        total += int(ln.a[0])
                    elif ln.d == "also":
                        pass
                    elif ln.d == "field" and ln.a[1].isdigit():
                        total += int(ln.a[1])
                    else:
                        break
                    if total >= stop:
                        fixed = True
                        break
                if not fixed:
                    return "bad-directive"
    return None


def strip_when(text):
    """The text with every token after a `when` line's values removed."""
    out = []
    for raw in text.splitlines():
        t = tokens_of(raw)
        if t and t[0] == "when" and len(t) > 3:
            indent = raw[:len(raw) - len(raw.lstrip())]
            raw = indent + " ".join(t[:3])
        out.append(raw)
    return "\n".join(out) + "\n"


def gtcheck_error(text, models):
    try:
        m = gtcheck.Model()
        for t in models:
            m.add(t)
        gtcheck.load_pack(text, m)
    except gtcheck.CheckError as e:
        # gtcheck names a directive this spec does not have `bad-directive`;
        # 0.11 (ruling 2) names it `unknown-directive`
        if "is not a directive" in str(e):
            return "unknown-directive"
        return e.kind
    return None


def expected_load(text, models):
    """The two computations together: the 0.33 checker gives the 0.30 and
    0.33 errors in their order; gtcheck on the stripped text gives the
    errors of earlier versions."""
    a = at_errors(text, models)
    g = gtcheck_error(strip_when(text), models)
    if a in ("unknown-directive", "missing-version", "missing-format", "missing-wire",
             "missing-distribution", "missing-source", "module-not-used", "undeclared-key"):
        # an `as` key is gone from the stripped text, so gtcheck may not see
        # it; gtcheck does not check a pack's `version` line (0.11, load
        # vector 378 pins `missing-version` for a pack)
        assert g == a or (g is None and (" as " in text or a == "missing-version")), (a, g)
        return a
    if a in ("key-type-mismatch", "bad-directive"):
        # only the 0.30 and 0.33 tokens refuse it, or an earlier rule that
        # gives the same kind (0.21 ruling 32 for ruling 9 of 0.33)
        assert g in (None, a), (a, g)
        return a
    return g


# ------------------------------------------------------------------------------
# the vectors
# ------------------------------------------------------------------------------
def build(sink):
    written = {}
    model = gtcheck.Model().load_dir(sink.path("model"))
    for name, text in PACKS.items():
        rel = "packs/%s%s/pack.def" % (PREFIX, name)
        sink.write(rel, text)
        gtcheck.load_pack(strip_when(text), model, label=rel)
        assert at_errors(text, [open(os.path.join(sink.path("model"), f), encoding="utf-8").read()
                                for f in ("core.def", "probe.def")]) is None, name
        written[PREFIX + name] = 0
    nums = {}

    def vec(owner, name, frm, to, inp, expect=None, error=None, model=None, ref=""):
        """`owner`, `frm`, `to`: pack names without the prefix. The second
        computation runs and must agree with the hand-derived value."""
        owner, frm, to = PREFIX + owner, PREFIX + frm, PREFIX + to
        ftext, ttext = PACKS[frm[len(PREFIX):]], PACKS[to[len(PREFIX):]]
        ent, got, failed = None, None, None
        try:
            ent = tag_kinds(decode(ftext, inp), frm)
        except Fail as e:
            failed = e
        if ent is not None:
            # 0.5: convert clears Entity.kind unless from == to; an Item.kind
            # names its format (ruling 26 of 0.8). No context. The probe
            # derive lines set keys none of these targets maps or requires.
            enc = dict(ent)
            if frm != to:
                enc.pop("@kind", None)
            try:
                got = encode(ttext, enc)
            except Fail as e:
                failed = e
        if error:
            assert failed is not None and failed.kind == error, (name, error, failed, got)
        else:
            assert failed is None, (name, failed and (failed.kind, failed.why))
            assert got == expect, (name, expect, got)
        if model:
            have = model_of(ent)
            for k, v in model.items():
                if k == "@absent":
                    for gone in v:
                        assert gone not in have, (name, gone, have)
                else:
                    assert have.get(k) == v, (name, k, v, have.get(k))
        nums[owner] = nums.get(owner, 0) + 1
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model:
            d["model"] = model
        d["source"] = "constructed"
        d["reference"] = ref
        sink.write("packs/%s/vectors/%02d-%s.json" % (owner, nums[owner], name),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[owner] += 1

    def js(**kw):
        return json.dumps(kw, separators=(",", ":"))

    # ==========================================================================
    # conformance-lookahead-bits
    # ==========================================================================
    D = "spec 0.33, Decode: "
    # 07 | 05 01 09. Kind start is bit 8. a: the window at 8+8 is 01 = 1,
    # holds. The cursor stays at 8: x = 05, pad (01), y = 09. Encode (kind
    # recorded): 07, x 05, pad 00, y 09; the window holds only `pad` bits, no
    # held key wrote there, so it is written with the first value 1: 07050109.
    vec("bits", "kind-a-by-look-ahead-roundtrip", "bits", "bits", "07050109", "07050109",
        model={"@kind": "a", "probe.n": "7", "probe.x": "5", "probe.y": "9",
               "@absent": ["probe.z", "probe.w", "probe.c1"]},
        ref=D + "the window at kind start + 8 reads 1 and does not move the cursor, so x reads the first "
                "body byte; Encode: a window over a `pad` is written with the first listed value")
    # 07 | fe 02 01 00. a: window 02 is not 1. b: 02 holds. z = fe = -2 (two's
    # complement), pad, w = 0100 = 256. Encode: fe, pad then the window 02,
    # 0100.
    vec("bits", "kind-b-reads-the-same-byte-under-another-key", "bits", "bits", "07fe020100", "07fe020100",
        model={"@kind": "b", "probe.z": "-2", "probe.w": "256", "@absent": ["probe.x", "probe.y"]},
        ref=D + "the first body byte is z in kind b and x in kind a: the kind's own field lines read the bits "
                "under the kind's own key names")
    # 07 | 56 03 2a. a: window 03 no; b: no. c: plain `when 4 5` at the cursor
    # (8) reads 5, cursor 12; the window at kind start (8) + 8 = 16 reads 03;
    # plain `when 4 6` at 12 reads 6, cursor 16. pad (03), c1 = 2a = 42.
    # Encode: 5, 6, pad, c1 2a, then the window 3 over the pad: 0756032a.
    vec("bits", "plain-and-look-ahead-when-interleaved", "bits", "bits", "0756032a", "0756032a",
        model={"@kind": "c", "probe.c1": "42", "@absent": ["probe.x", "probe.z"]},
        ref="spec 0.33 ruling 2: plain `when` lines consume bits in line order and the offset counts from kind "
            "start; kind c reads 5 at bit 8, the window 3 at bit 16, 6 at bit 12")
    # 07 | 56 00 30. a, b: window 00 no. c: 5 holds; the window at kind start
    # + 8 = bit 16 reads 00: no. (Counted from the cursor after the first
    # nibble it would read bits 20..27 = 0, 3 = 03 and hold.) no-kind.
    vec("bits", "offset-counts-from-kind-start-not-the-cursor", "bits", "bits", "07560030", error="no-kind",
        ref="spec 0.33 ruling 2: offsets count from kind start, not from the cursor; bits 16 to 23 are 00, so "
            "kind c does not hold (bits 20 to 27 would read 03)")
    # 07 | 05 04 09: window 04 is neither 1 nor 2; c: the high nibble 0 is not
    # 5. no-kind.
    vec("bits", "window-value-of-no-kind", "bits", "bits", "07050409", error="no-kind",
        ref=D + "no kind holds: the message is no-kind (Version 0.5)")
    # from json {n 7, x 5, y 9}: no kind has `requires`, so a (first). 07, x
    # 05, pad 00, y 09, window 1 at bits 16..23: 07050109.
    vec("json", "to-bits-window-written-over-a-pad", "json", "bits", js(n=7, x=5, y=9), "07050109",
        ref="spec 0.33, Encode: a window no held key wrote is written with the first listed value, here over "
            "a `pad`")

    # ==========================================================================
    # conformance-lookahead-lsb (ruling 8, bit order)
    # ==========================================================================
    # 07 | 5a. Under lsb, bits 4..7 of the byte 5a (0101 1010) are its high
    # nibble, low bit first: 5. a holds; x = 0x5a = 90. Encode: x writes 5a,
    # held; the window's bits 5 match: 075a. (Under msb the window would read
    # the low nibble a, kind b.)
    R8 = "spec 0.33 ruling 8: a window reads and writes raw stream bits in the pack's bit order; "
    vec("lsb", "window-in-lsb-order", "lsb", "lsb", "075a", "075a",
        model={"@kind": "a", "probe.x": "90", "@absent": ["probe.y"]},
        ref=R8 + "under lsb bits 4 to 7 of 5a are its high nibble, 5")
    # 07 | a5: high nibble a = 10: a no, b holds. y = 165.
    vec("lsb", "window-in-lsb-order-other-kind", "lsb", "lsb", "07a5", "07a5",
        model={"@kind": "b", "probe.y": "165", "@absent": ["probe.x"]},
        ref=R8 + "under lsb bits 4 to 7 of a5 are 10")
    # from json {n 7, x 165}: a is first and has no `requires`. x writes a5,
    # held; the window, bits 4..7 under lsb, is a = 10, not 5:
    # transform-encode.
    vec("json", "to-lsb-held-bits-do-not-match", "json", "lsb", js(n=7, x=165), error="transform-encode",
        ref=R8 + "x = 165 writes a5, whose bits 4 to 7 under lsb are 10, not 5; Encode: transform-encode")

    # ==========================================================================
    # conformance-lookahead-swap (ruling 8, swap)
    # ==========================================================================
    # 07 | 12 34. The window, 8 raw bits at kind start: 12 = 18: a. x is the
    # two bytes reversed: 0x3412 = 13330. Encode: 13330 = 0x3412 written
    # swapped is 12 34; the window's raw bits 12 = 18 match: 071234.
    vec("swap", "window-reads-raw-bits-under-swap", "swap", "swap", "071234", "071234",
        model={"@kind": "a", "probe.x": "13330", "@absent": ["probe.y"]},
        ref=R8 + "the first byte on the wire is 0x12 = 18, whatever x's swapped value 0x3412")
    # 07 | 34 12: raw 34 = 52: b. y = 0x1234 = 4660.
    vec("swap", "window-reads-raw-bits-under-swap-other-kind", "swap", "swap", "073412", "073412",
        model={"@kind": "b", "probe.y": "4660", "@absent": ["probe.x"]},
        ref=R8 + "the first byte on the wire is 0x34 = 52")
    # from json {n 7, x 4660}: a (requires x). 4660 = 0x1234 written swapped
    # is 34 12; the window's raw bits 34 = 52 are not 18: transform-encode.
    vec("json", "to-swap-held-bits-do-not-match", "json", "swap", js(n=7, x=4660), error="transform-encode",
        ref=R8 + "x = 4660 is written 34 12, so the window's raw first byte is 52, not 18; Encode: "
                 "transform-encode")
    # from json {n 7, x 13330}: 0x3412 written swapped is 12 34; window 12 =
    # 18 matches: 071234.
    vec("json", "to-swap-held-bits-match", "json", "swap", js(n=7, x=13330), "071234",
        ref=R8 + "x = 13330 is written 12 34, so the window's raw first byte is 18 and the bits stand")

    # ==========================================================================
    # conformance-lookahead-settle (Encode, ruling 1)
    # ==========================================================================
    S = "spec 0.33, Encode (ruling 1): "
    # 07 | 0a 02. full: the window, body byte 1, is 02: in 1,2. x = 10, y = 2.
    # Encode: y = 2 is held and wrote all the window's bits; they match: they
    # stand (2, not the first value 1): 070a02.
    vec("settle", "held-bits-that-match-stand", "settle", "settle", "070a02", "070a02",
        model={"@kind": "full", "probe.x": "10", "probe.y": "2"},
        ref=S + "y = 2 wrote the window's bits and they match 1,2, so they stand; the first value 1 is not "
                "written")
    # 07 | 13. full: the window at body bits 8..15 is past the input: no. part:
    # the low nibble 3 holds. z = 0x13 = 19. Encode: z held, its low nibble 3
    # matches: 0713.
    vec("settle", "window-over-part-of-a-field", "settle", "settle", "0713", "0713",
        model={"@kind": "part", "probe.z": "19"},
        ref=S + "the window is the low nibble of z; full's window lies past the input and does not hold "
                "(ruling 6)")
    # 07 | 15 a7. full: a7 no; part: low nibble 5 no; several: bits 4..11 =
    # 5, a = 0x5a = 90: holds. c1 = 21, c2 = 167. Encode: both held; the
    # window's bits 0x5a match: 0715a7.
    vec("settle", "window-over-two-fields", "settle", "settle", "0715a7", "0715a7",
        model={"@kind": "several", "probe.c1": "21", "probe.c2": "167"},
        ref=S + "the window covers the low nibble of c1 and the high nibble of c2")
    # 07 | 0b 04. full: 04 no; part: b no; several: 0xb0 no; def: 04 holds.
    # v3 = 11, w = 4. Encode: w = 4 held, matches: 070b04.
    vec("settle", "window-over-a-field-with-a-default", "settle", "settle", "070b04", "070b04",
        model={"@kind": "def", "probe.v3": "11", "probe.w": "4"},
        ref=S + "w = 4 is held, so its bits stand")
    # 07 | 0a 06. full: 06 no; part: a no; several: 0xa0 no; def: 06 no; as:
    # 6 in 5..7 holds; v1 = 6 (0.30). v2 = 10, v4 = 6. Encode: v4 = 6 held,
    # matches and equals v1: 070a06.
    vec("settle", "as-with-at", "settle", "settle", "070a06", "070a06",
        model={"@kind": "as", "probe.v1": "6", "probe.v2": "10", "probe.v4": "6"},
        ref="spec 0.33 with 0.30: the window's bits bind v1 when the kind is selected; v4 reads the same bits")
    # from json {n 7, x 10, y 5}: full (requires y). y = 5 written in the
    # window does not match 1,2: transform-encode (on a fixed layout ruling 3
    # of 0.20 would write 1).
    vec("json", "to-settle-held-bits-do-not-match", "json", "settle", js(n=7, x=10, y=5),
        error="transform-encode",
        ref=S + "y = 5 is held and its bits in the window do not match 1,2: transform-encode, the output would "
                "decode a different value")
    # from json {n 7, x 10, y 2}: full. y = 2 stands: 070a02.
    vec("json", "to-settle-held-bits-match", "json", "settle", js(n=7, x=10, y=2), "070a02",
        ref=S + "y = 2 is held and matches 1,2: its bits stand, not the first value")
    # from json {n 7, z 36}: part (requires z). z = 0x24, its low nibble 4 is
    # not 3: transform-encode.
    vec("json", "to-settle-part-of-a-field-does-not-match", "json", "settle", js(n=7, z=36),
        error="transform-encode",
        ref=S + "a partial cover is judged on the window's bits as written: the low nibble of 0x24 is 4, not 3")
    # from json {n 7, z 35}: z = 0x23, low nibble 3: 0723.
    vec("json", "to-settle-part-of-a-field-matches", "json", "settle", js(n=7, z=35), "0723",
        ref=S + "the low nibble of 0x23 is 3: the bits stand")
    # from json {n 7, c1 21, c2 183}: several. 15 b7: window 5, b = 0x5b, not
    # 0x5a: transform-encode.
    vec("json", "to-settle-two-fields-do-not-match", "json", "settle", js(n=7, c1=21, c2=183),
        error="transform-encode",
        ref=S + "c1 = 0x15 and c2 = 0xb7 put 0x5b in the window, not 0x5a")
    # from json {n 7, c1 21, c2 167}: 15 a7, window 0x5a: 0715a7.
    vec("json", "to-settle-two-fields-match", "json", "settle", js(n=7, c1=21, c2=167), "0715a7",
        ref=S + "c1 = 0x15 and c2 = 0xa7 put 0x5a in the window: the bits stand")
    # from json {n 7, v3 11}: def (requires v3). w is not held: its default 9
    # is written, 09, but a default is not a held key, so no held key wrote
    # the window: it is written with the first value 4: 070b04. (Were the
    # default counted, 9 would not match: transform-encode.)
    vec("json", "to-settle-a-default-does-not-count", "json", "settle", js(n=7, v3=11), "070b04",
        ref="spec 0.33, Encode: a `default` does not count as a held key (ruling 29 of 0.20); w's default 9 is "
            "overwritten by the window's first value 4")
    # from json {n 7, v1 7, v2 3}: full, part, several, def lack their
    # `requires` keys; as qualifies (v1 = 7 in 5..7, 0.30). v2 03, v4 absent
    # writes 00; no held key wrote the window: it is written with v1 = 7:
    # 070307.
    vec("json", "to-settle-window-written-with-the-as-value", "json", "settle", js(n=7, v1=7, v2=3), "070307",
        ref="spec 0.33, Encode: with no held key in the window it is written with the value of the `as` key "
            "(0.30), 7, not the first value 5")
    # from json {n 7, v1 6, v2 1, v4 6}: v4 = 6 held, matches and agrees with
    # v1: 070106.
    vec("json", "to-settle-held-bits-agree-with-the-as-key", "json", "settle", js(n=7, v1=6, v2=1, v4=6),
        "070106", ref=S + "v4 = 6 matches 5..7 and equals v1 = 6: the bits stand")
    # from json {n 7, v1 6, v2 1, v4 5}: v4 = 5 matches 5..7 but is not v1 =
    # 6: transform-encode.
    vec("json", "to-settle-held-bits-disagree-with-the-as-key", "json", "settle", js(n=7, v1=6, v2=1, v4=5),
        error="transform-encode",
        ref=S + "v4 = 5 matches 5..7 but disagrees with the held `as` key v1 = 6: transform-encode")
    # from json {n 7, v1 6, v2 1, v4 9}: v4 = 9 does not match 5..7:
    # transform-encode.
    vec("json", "to-settle-held-bits-outside-the-as-window", "json", "settle", js(n=7, v1=6, v2=1, v4=9),
        error="transform-encode", ref=S + "v4 = 9 does not match 5..7: transform-encode")
    # from json {n 7, v1 4, v2 1}: as needs v1 in 5..7 (0.30 implicit term);
    # no kind qualifies: no-kind.
    vec("json", "to-settle-as-value-outside-the-window", "json", "settle", js(n=7, v1=4, v2=1), error="no-kind",
        ref="spec 0.30, Encode: the implicit term of `when ... at 8 as probe.v1` needs v1 in 5..7; no kind "
            "qualifies")

    # ==========================================================================
    # conformance-lookahead-switch (windows settled before a switch)
    # ==========================================================================
    W = "spec 0.33, Encode: the windows are settled before any `switch` reads its key back; "
    # 07 | 0a 01 2a: window 01; x 10, y 1, case 1: z = 42.
    vec("switch", "switch-on-the-window-key-roundtrip", "switch", "switch", "070a012a", "070a012a",
        model={"@kind": "a", "probe.y": "1", "probe.z": "42", "@absent": ["probe.w"]},
        ref="spec 0.33 and 0.20 `switch`: y reads the window's bits, 1, and selects case 1")
    # 07 | 0a 02 01 00: window 02; y 2, case 2: w = 256.
    vec("switch", "switch-on-the-window-key-other-case", "switch", "switch", "070a020100", "070a020100",
        model={"@kind": "a", "probe.y": "2", "probe.w": "256", "@absent": ["probe.z"]},
        ref="spec 0.33 and 0.20 `switch`: y = 2 selects case 2")
    # from json {n 7, x 10, z 42}: y is not held: its line writes 00. The
    # window, which no held key wrote, takes the first value 1. The switch
    # reads y back from the bits as they stand: 1, case 1: z 2a: 070a012a.
    vec("json", "to-switch-window-settled-before-the-switch", "json", "switch", js(n=7, x=10, z=42),
        "070a012a", ref=W + "y is absent, the window writes 1, and the switch reads 1: case 1 writes z")
    # from json {n 7, x 10, w 256}: as above, the switch reads 1: case 1; z is
    # absent and writes 00; w is not written: 070a0100.
    vec("json", "to-switch-window-value-chooses-the-case", "json", "switch", js(n=7, x=10, w=256),
        "070a0100", ref=W + "the window writes 1, so the switch selects case 1 although the entity holds w; "
                            "z is absent and writes zero bits")
    # from json {n 7, x 10, y 2, w 256}: y = 2 held, matches: stands; case 2:
    # w 0100: 070a020100.
    vec("json", "to-switch-held-window-key", "json", "switch", js(n=7, x=10, y=2, w=256), "070a020100",
        ref=W + "y = 2 is held and matches, so case 2 writes w")
    # from json {n 7, x 10, y 3, z 1}: y = 3 does not match 1,2:
    # transform-encode.
    vec("json", "to-switch-held-window-key-does-not-match", "json", "switch", js(n=7, x=10, y=3, z=1),
        error="transform-encode", ref=S + "y = 3 does not match 1,2")

    # ==========================================================================
    # conformance-lookahead-const (ruling 3)
    # ==========================================================================
    C = "spec 0.33 ruling 3: a `const` is not checked on decode, and encode writes the `when`'s value over it; "
    # 07 | 0a 02 05: window 02 in 1,2 (the const 9 is not checked). x 10, y 5.
    # Encode: x, const 09, y, then the window: no held key wrote it, so the
    # first value 1: 070a0105.
    vec("const", "window-over-a-const", "const", "const", "070a0205", "070a0105",
        model={"@kind": "a", "probe.x": "10", "probe.y": "5"},
        ref=C + "the input's 2 selects the kind; the output carries the first value 1, not 2 and not the "
                "const 9")
    # 07 | 0a 01 05: the same output.
    vec("const", "window-over-a-const-first-value", "const", "const", "070a0105", "070a0105",
        model={"@kind": "a", "probe.x": "10", "probe.y": "5"},
        ref=C + "the window's first value 1 is written over the const 9")
    # 07 | 0a 09 05: the const's own value 9 is not in 1,2: no-kind.
    vec("const", "const-value-does-not-hold", "const", "const", "070a0905", error="no-kind",
        ref=C + "the bits 9 equal the const but not the window: no kind holds")

    # ==========================================================================
    # conformance-lookahead-items (ruling 4)
    # ==========================================================================
    # 07 | 02 | 05 22 01 | 06 68 69 02. Item 0: x 05, kind start at byte 3;
    # pt's window at +8 = byte 4 = 01: pt; y 0x22 = 34, pad. Item 1: x 06,
    # kind start at byte 6; pt's window at byte 7 = 69: no; tx's window at +16
    # = byte 8 = 02: tx; label "hi", pad. Encode: each item's recorded kind;
    # the windows over the pads take 1 and 2.
    vec("items", "item-kinds-by-look-ahead", "items", "items", "070205220106686902", "070205220106686902",
        model={"probe.recs.#": "2", "probe.recs[0].@kind": "pt", "probe.recs[0].probe.x": "5",
               "probe.recs[0].probe.y": "34", "probe.recs[1].@kind": "tx", "probe.recs[1].probe.x": "6",
               "probe.recs[1].probe.label": "hi"},
        ref="spec 0.33 ruling 4: in a group body kind start is where the item's common lines ended, for each "
            "item")
    # 07 | 01 | 05 22 03: pt's window 03 no; tx's window at kind start + 16 =
    # byte 5, past the input: no. The item is no-kind, and so the decode.
    vec("items", "item-with-no-kind", "items", "items", "0701052203", error="no-kind",
        ref="spec 0.33 rulings 4 and 6: no kind of the item holds (tx's window is past the input); an item "
            "that is no-kind fails the decode (ruling 11 of 0.20)")

    # ==========================================================================
    # conformance-lookahead-overlap (ruling 5)
    # ==========================================================================
    O = "spec 0.33 ruling 5: windows are settled in line order with no check between them; "
    # 07 | 0a 15: window 1 (byte 15 = 21) in 18,21; window 2 (low nibble 5)
    # in 5,6: a. x = 10. Encode: x, pad 00; window 1, no held key: first value
    # 18 = 0x12; window 2, no held key (window 1's bits are not a key's): 5
    # over the low nibble: 0x15: 070a15.
    vec("overlap", "overlapping-windows-later-bits-stand", "overlap", "overlap", "070a15", "070a15",
        model={"@kind": "a", "probe.x": "10"},
        ref=O + "the first window writes 0x12, the second writes 5 over its low nibble: 0x15")
    # from json {n 7, x 10}: a (requires x): the same 070a15.
    vec("json", "to-overlap-later-window-stands", "json", "overlap", js(n=7, x=10), "070a15",
        ref=O + "0x12 then 5 over the low nibble: 0x15")
    # from json {n 7, w 42}: a needs x; b (requires w). The plain `when`
    # writes 9 (high nibble), pad 0, w 2a. The window over the first byte: no
    # held key wrote it (a plain `when` is not a key): 55 = 0x37, over the 9:
    # 07372a. That output does not decode as b; the spec loads it and does not
    # check it.
    vec("json", "to-overlap-window-over-a-plain-when", "json", "overlap", js(n=7, w=42), "07372a",
        ref=O + "a window may cover a plain `when` of its kind with another value: 0x37 is written over the "
                "plain `when`'s 9")

    # ==========================================================================
    # conformance-lookahead-end (ruling 6)
    # ==========================================================================
    E6 = "spec 0.33 ruling 6: "
    # 07 | 05 09 09 0b: long's window, bits 16..31 = 0909 = 2313: long. x 5,
    # y 2313, z 11. Encode: y wrote the window, matches: same.
    vec("end", "long-roundtrip", "end", "end", "070509090b", "070509090b",
        model={"@kind": "long", "probe.x": "5", "probe.y": "2313", "probe.z": "11"},
        ref=E6 + "the window holds and the kind reads to its end")
    # 07 | 05 09: long's window, bits 16..31, straddles the end (24): no.
    # wide: plain 05 is not 255. short: bits 8..11 = 0 in 0..15: c1 = 5; the
    # rest (09) is ignored. Encode: 0705.
    vec("end", "window-straddling-the-end-does-not-hold", "end", "end", "070509", "0705",
        model={"@kind": "short", "probe.c1": "5", "@absent": ["probe.x", "probe.y"]},
        ref=E6 + "a window some of whose bits lie beyond the input does not hold and the next kind is tried")
    # 07 | ff: long's window starts at the end: no. wide: the first plain
    # `when` reads ff; the second lies past the input: no. short: f in 0..15:
    # c1 = 255: 07ff.
    vec("end", "plain-when-past-the-end-does-not-hold", "end", "end", "07ff", "07ff",
        model={"@kind": "short", "probe.c1": "255", "@absent": ["probe.w"]},
        ref=E6 + "a `when` without `at` in a sequential pack whose bits lie beyond the input does not hold; "
                 "the next kind is tried")
    # 07 | 05 09 09: long's window 0909 holds: long is final. x, y read; z at
    # bits 32..39 is past the input: malformed-wire. (short would hold.)
    vec("end", "selected-kind-truncated", "end", "end", "07050909", error="malformed-wire",
        ref=E6 + "once a kind is selected it is final: a later line past the end is malformed-wire and no other "
                 "kind is tried")
    # 07: every kind's first `when` lies past the input: no-kind.
    vec("end", "no-body-is-no-kind", "end", "end", "07", error="no-kind",
        ref=E6 + "no `when` of any kind lies within the input: no kind holds")
    # 07 | ff ff 2a: long's window ff2a is not 2313. wide: ff, ff: w = 42.
    vec("end", "plain-when-kind-after-a-window-kind", "end", "end", "07ffff2a", "07ffff2a",
        model={"@kind": "wide", "probe.w": "42"},
        ref=E6 + "the window kind does not hold; the plain `when` kind does")

    # ==========================================================================
    # conformance-lookahead-extent (ruling 7)
    # ==========================================================================
    X = "spec 0.33 ruling 7: the enclosing extent is the innermost `length` block around kind start; "
    # 09 | 06 | 05 07 01 | 06 00 25 | 2a. Extent: 6 bytes. Item 0: x 05, kind
    # start at extent byte 1; a's window, extent byte 2 = 01: a; y 07, pad.
    # Item 1: x 06, kind start at extent byte 4; a's window, byte 5 = 25: no;
    # b's window, bits 4..11 of 00 25 = 0000 0010 = 2: b; z = 0x0025 = 37.
    # The extent ends; w = 2a. Encode: the pad takes 1; z = 37 wrote b's
    # window, 2 matches; the length 6.
    vec("extent", "item-windows-inside-an-extent", "extent", "extent", "09060507010600252a",
        "09060507010600252a",
        model={"probe.recs.#": "2", "probe.recs[0].@kind": "a", "probe.recs[0].probe.y": "7",
               "probe.recs[1].@kind": "b", "probe.recs[1].probe.z": "37", "probe.w": "42"},
        ref=X + "both items' windows lie inside it")
    # 09 | 02 | 05 03 | 01 2a. Extent: 2 bytes. Item 0: x 05; a's window
    # starts at extent bit 16, the end: no (the byte after it, 01, would
    # hold). b's window, bits 12..19, straddles: no. no-kind.
    vec("extent", "window-at-the-extent-end-does-not-hold", "extent", "extent", "09020503012a", error="no-kind",
        ref=X + "a window that starts at its end does not hold, though the input goes on with 01; the item is "
                "no-kind, which fails the decode")
    # 09 | 02 | 05 00 | 20 2a. Item 0: a's window starts at the end: no. b's
    # window, extent bits 12..19, straddles the end at 16 (with the input
    # beyond it, it would read 0, 2 = 2 and hold): no. no-kind.
    vec("extent", "window-straddling-the-extent-end-does-not-hold", "extent", "extent", "09020500202a",
        error="no-kind",
        ref=X + "a window some of whose bits lie beyond the extent does not hold (ruling 6); bits 12 to 19 "
                "would read 2 with the input beyond the extent")

    # ==========================================================================
    # conformance-lookahead-whole (ruling 6, `length ... whole`)
    # ==========================================================================
    # 03 | 05 07: the whole length is 3 bytes; long's window, byte 2 = 07:
    # long; x 5, y 7. Encode: the length 3: 030507.
    vec("whole", "window-inside-the-whole-length", "whole", "whole", "030507", "030507",
        model={"@kind": "long", "probe.x": "5", "probe.y": "7"},
        ref=E6 + "the window lies inside the stated whole length")
    # 02 | 05 07: the whole length is 2 bytes, so the message ends at bit 16;
    # long's window at bit 16 lies beyond it: no (the input holds 07 there).
    # short: z = 5. Encode: 02 05.
    vec("whole", "window-beyond-the-whole-length", "whole", "whole", "020507", "0205",
        model={"@kind": "short", "probe.z": "5", "@absent": ["probe.x", "probe.y"]},
        ref=E6 + "a window beyond `length ... whole` does not hold, though the input holds 07 there; the next "
                 "kind is tried")

    # ==========================================================================
    # conformance-lookahead-held (rulings 12 and 13)
    # ==========================================================================
    H = "spec 0.33 rulings 12 and 13: "
    # 07 | 15 a3. part: bits 4..11 of the body = 5 (x's low nibble), a (the
    # pad) = 0x5a: holds. x = 21, pad, y = 3. Encode: x 15, pad 0, y 3: 15 03;
    # the window as written, 0x50, does not match, so its value is the first
    # value 0x5a; the bits x wrote (0101) equal its high nibble 5, the pad's
    # bits are not a held key's: 0x5a is written: 0715a3.
    vec("held", "partial-cover-over-a-pad-roundtrip", "held", "held", "0715a3", "0715a3",
        model={"@kind": "part", "probe.x": "21", "probe.y": "3"},
        ref=H + "the window's value 0x5a is chosen first; only the bits x wrote are compared with it, and the "
                "pad's bits are written over")
    # from json {n 7, x 21, y 3}: part (requires x): the same 0715a3.
    vec("json", "to-held-partial-cover-over-a-pad", "json", "held", js(n=7, x=21, y=3), "0715a3",
        ref=H + "x = 0x15 agrees with the high nibble of 0x5a; the pad nibble takes a")
    # from json {n 7, x 22, y 3}: x's low nibble 6 differs from 5:
    # transform-encode.
    vec("json", "to-held-partial-cover-over-a-pad-differs", "json", "held", js(n=7, x=22, y=3),
        error="transform-encode",
        ref=H + "x = 0x16 wrote 0110 where the window's value 0x5a has 0101: transform-encode")
    # from json {n 7, y 9}: part needs x; suppressed (requires y). z is not
    # held, so y's line is suppressed and writes 00, not a held key's bits;
    # z absent writes 00. The window 00 does not match 7: it is written with 7:
    # 070700.
    vec("json", "to-held-suppressed-line-is-not-held", "json", "held", js(n=7, y=9), "070700",
        ref=H + "a line that `with` suppressed is not bits a held key wrote: the window 7 is written over its "
                "zero bits, though the entity holds y = 9")
    # from json {n 7, y 9, z 1}: y's line writes 09, held; the value 7
    # differs: transform-encode.
    vec("json", "to-held-written-line-is-held", "json", "held", js(n=7, y=9, z=1), error="transform-encode",
        ref=H + "with z held the line writes y = 9, a held key's bits that differ from 7")
    # from json {n 7, y 7, z 1}: y 07 matches and stands: 070701.
    vec("json", "to-held-written-line-matches", "json", "held", js(n=7, y=7, z=1), "070701",
        ref=H + "with z held the line writes y = 7, which matches: the bits stand")
    # from json {n 7, c1 3}: part, suppressed lack their keys; sentinel. w
    # is absent and writes its sentinel ff, not a held key's bits; ff does not
    # match 4, so 4 is written: 070403.
    vec("json", "to-held-sentinel-is-not-held", "json", "held", js(n=7, c1=3), "070403",
        ref=H + "an absent key's sentinel (`absent 255`) is not bits a held key wrote: the window 4 is written "
                "over it")
    # from json {n 7, w 255, c1 3}: w held writes ff; 4 differs:
    # transform-encode.
    vec("json", "to-held-value-equal-to-the-sentinel-is-held", "json", "held", js(n=7, w=255, c1=3),
        error="transform-encode",
        ref=H + "w = 255 is held (0.9: a held value is written even when it equals a sentinel), so its bits are "
                "compared with 4")

    # ==========================================================================
    # conformance-lookahead-text (ruling 15)
    # ==========================================================================
    # {"t":"at","x":1}: a's `when t at` holds on the text at. Encode: the
    # `when` member then x, in line order.
    vec("text", "at-is-a-value-on-a-text-wire", "text", "text", js(t="at", x=1), js(t="at", x=1),
        model={"@kind": "a", "probe.x": "1"},
        ref="spec 0.33 ruling 15: `at` is a keyword only in a `when` of a sequential pack; on json `when t at` "
            "matches the text at")

    # json source round trip, so the pack has a vector of its own
    vec("json", "roundtrip", "json", "json", js(n=7, x=10, v1=6), js(n=7, x=10, v1=6),
        model={"probe.n": "7", "probe.x": "10", "probe.v1": "6"},
        ref="spec 0.5 json canonical output: members in line order")

    # ==========================================================================
    # load vectors from 3300
    # ==========================================================================
    core = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key time_ms int ms\n")
    probe = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey x int -\nkey y int -\n"
             "key z int -\nkey w int -\nkey a float -\nkey s string -\nkey label string -\nlist recs \"a list\"\n")
    other = "module other\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey k int -\n"
    top = 'format probe\nversion 0.33.0\ndistribution public\nsource "probe"\nuses probe\n'
    seq = top + "wire bits\nlayout sequential\n"
    fixed = top + "wire bits\nword_bytes 1\n"
    jsn = top + "wire json\n"
    two = "field probe.x 8 uint\nfield probe.y 8 uint\n"
    lnum = [FIRST_LOAD - 1]
    written["load"] = 0

    def load(name, text, error="bad-directive", models=(core, probe)):
        lnum[0] += 1
        full = "%d-lookahead-%s" % (lnum[0], name)
        got = expected_load(text, list(models))
        assert got == error, (full, error, got)
        d = {"name": full, "models": list(models), "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] += 1

    # the directive and where it stands
    load("at-loads", seq + "kind a\nwhen 8 1 at 8\n" + two, None)
    load("at-on-a-fixed-layout", fixed + "field probe.x 0:0:8 uint\nkind a\nwhen 0:8:8 1 at 0\n")
    load("at-on-json", jsn + "kind a\nwhen t a at 0\n")
    load("at-on-a-common-when", seq + "when 8 1 at 0\nfield probe.x 8 uint\nkind a\nfield probe.y 8 uint\n")
    load("at-on-a-group-body-common-when", seq + "group probe.recs count 8\n  when 8 1 at 0\n"
         "  field probe.x 8 uint\n  kind a\n  field probe.y 8 uint\nend\n")
    load("at-on-an-item-kind-loads", seq + "group probe.recs count 8\n  field probe.x 8 uint\n  kind a\n"
         "  when 8 1 at 8\n  field probe.y 8 uint\n  pad 8\nend\n", None)
    # the `at` form
    load("at-without-a-value", seq + "kind a\nwhen 8 1 at\n" + two)
    load("at-twice", seq + "kind a\nwhen 8 1 at 0 at 0\n" + two)
    load("at-with-a-plus-sign", seq + "kind a\nwhen 8 1 at +8\n" + two)
    load("at-negative", seq + "kind a\nwhen 8 1 at -8\n" + two)
    load("at-hexadecimal", seq + "kind a\nwhen 8 1 at 0x8\n" + two)
    load("at-does-not-fit-64-bits", seq + "kind a\nwhen 8 1 at 18446744073709551616\n" + two)
    load("at-with-leading-zeros-loads", seq + "kind a\nwhen 8 1 at 0008\n" + two, None)
    # the token order (ruling 11)
    load("at-then-as-loads", seq + "kind a\nwhen 8 1 at 0 as probe.x\nfield probe.y 8 uint\n", None)
    load("as-then-at", seq + "kind a\nwhen 8 1 as probe.x at 0\nfield probe.y 8 uint\n")
    load("at-then-as-without-a-key", seq + "kind a\nwhen 8 1 at 0 as\nfield probe.y 8 uint\n")
    load("at-then-as-with-a-token-after-the-key", seq + "kind a\nwhen 8 1 at 0 as probe.x y\n"
         "field probe.y 8 uint\n")
    load("at-then-another-value", seq + "kind a\nwhen 8 1 at 0 8\n" + two)
    # the fixed window
    load("window-past-the-last-line", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\n")
    load("window-over-plain-when-const-pad-field-and-also-loads", seq + "kind a\nwhen 4 1\nwhen 16 3 at 4\n"
         "const 4 2\npad 4\nfield probe.x 4 uint\nalso probe.y\nfield probe.z 4 uint\n", None)
    load("window-skips-requires-and-default-loads", seq + "kind a\nwhen 8 1 at 8\nrequires probe.x\n"
         "field probe.x 8 uint\ndefault probe.y 3\nfield probe.y 8 uint\n", None)
    load("window-over-an-until-field", seq + "kind a\nwhen 8 1 at 8\nfield probe.label until:0 chars:ascii8\n"
         "field probe.x 8 uint\n")
    load("until-field-after-the-window-loads", seq + "kind a\nwhen 8 1 at 0\nfield probe.x 8 uint\n"
         "field probe.label until:0 chars:ascii8\n", None)
    load("opt-after-the-window-loads", seq + "kind a\nwhen 8 1 at 0\nfield probe.x 8 uint\nopt\n"
         "  field probe.y 8 uint\nend\n", None)
    load("opt-before-the-window-end", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\nopt\n"
         "  field probe.y 8 uint\nend\n")
    load("window-ending-inside-the-last-line-walked-loads", seq + "kind a\nwhen 4 1 at 6\n" + two +
         "opt\n  field probe.z 8 uint\nend\n", None)
    load("window-over-an-align", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\nalign 8\n"
         "field probe.y 8 uint\n")
    load("window-over-a-presence", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\npresence p 8\n"
         "if p.1\n  field probe.y 8 uint\nend\n")
    load("window-over-a-chain", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\nchain\n"
         "  field probe.y 8 uint\nend\n")
    load("window-over-a-length", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\nlength 8\n"
         "  field probe.y 8 uint\nend\n")
    load("window-over-a-group", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\ngroup probe.recs count 8\n"
         "  field probe.y 8 uint\nend\n")
    load("window-over-a-count-line", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\ncount c 8\n"
         "group probe.recs count @c\n  field probe.y 8 uint\nend\n")
    load("window-over-a-switch", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\nswitch probe.x\n"
         "  case 1\n    field probe.y 8 uint\nend\n")
    load("window-over-fields-with-width-keeping-options-loads", seq + "kind a\nwhen 8 1 at 48\n"
         "field probe.x 16 uint swap\nfield probe.label 16 ascii trim\nfield probe.y 8 uint absent 255\n"
         "field probe.z 8 uint with probe.x\nfield probe.s 8 hex\n", None)
    # ruling 5
    load("ruling-5-overlapping-windows-over-a-plain-when-load", seq + "kind a\nwhen 4 1\nwhen 8 52 at 0\n"
         "when 4 2 at 4\nfield probe.x 4 uint\nfield probe.y 8 uint\n", None)
    # ruling 9
    load("ruling-9-common-rest-then-a-kind-with-only-at", seq + "group probe.recs rest\n  field probe.y 8 uint\n"
         "end\nkind a\nwhen 8 1 at 0\nfield probe.x 8 uint\n")
    load("ruling-9-rest-at-the-end-of-a-kind-loads", seq + "kind a\nwhen 8 1 at 0\nfield probe.x 8 uint\n"
         "group probe.recs rest\n  field probe.y 8 uint\nend\nkind b\nwhen 8 2 at 0\nfield probe.z 8 uint\n", None)
    # ruling 10
    load("ruling-10-at-is-checked-after-the-file", seq + "kind a\nwhen 8 1 at\nbogus\n", "unknown-directive")
    load("ruling-10-window-is-checked-after-the-file", seq + "kind a\nwhen 8 1 at 8\nfield probe.x 8 uint\n"
         "bogus\n", "unknown-directive")
    load("ruling-10-undeclared-key-before-the-at-form", seq + "kind a\nwhen 8 1 at +8\nfield probe.x 8 uint\n"
         "field probe.nosuch 8 uint\n", "undeclared-key")
    load("ruling-10-module-not-used-before-the-at-form", seq + "kind a\nwhen 8 1 at +8\nfield probe.x 8 uint\n"
         "field other.k 8 uint\n", "module-not-used", models=(core, probe, other))
    load("ruling-10-as-type-before-the-at-form", seq + "kind a\nwhen 8 1 at +8 as probe.label\n" + two,
         "key-type-mismatch")
    load("ruling-10-undeclared-as-key-before-the-fixed-window", seq + "kind a\nwhen 8 1 at 8 as probe.nosuch\n"
         "field probe.x 8 uint\n", "undeclared-key")
    load("ruling-10-missing-version-before-the-at-form", seq.replace("version 0.33.0\n", "") +
         "kind a\nwhen 8 1 at +8\n" + two, "missing-version")
    # rulings 14 and 15
    load("ruling-14-missing-distribution-before-the-at-form", seq.replace("distribution public\n", "") +
         "kind a\nwhen 8 1 at +8\n" + two, "missing-distribution")
    load("ruling-15-at-as-a-json-value-loads", jsn + "kind a\nwhen t at\nfield probe.x x int\n", None)
    # a vector file of these packs, or a load vector of this range, that this
    # run did not write is from an earlier run: it goes
    for name in PACKS:
        rel = "packs/%s%s/vectors" % (PREFIX, name)
        for f in sink.listdir(rel):
            if rel + "/" + f not in sink.written:
                sink.remove(rel + "/" + f)
    rel = "packs/conformance/load-vectors"
    for f in sink.listdir(rel):
        num = f.split("-")[0]
        if num.isdigit() and FIRST_LOAD <= int(num) < FIRST_LOAD + 100 and "-lookahead-" in f \
                and rel + "/" + f not in sink.written:
            sink.remove(rel + "/" + f)
    return written


def main(argv=None):
    return genio.vector_main("conformance-lookahead-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
