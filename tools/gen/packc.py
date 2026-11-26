#!/usr/bin/env python3
"""packc: compile packs to the compact binary form the device engine runs.

Reads   <model>/*.def and <packs>/<format>/pack.def
Writes  a `.gtp` blob (embedded/FORMAT.md), a Rust source file that embeds the
        blob as a `static`, and a size report (bytes per table).

The device engine (embedded/gt-core) does not parse pack text. This tool does
that once, on the host: it slices the named formats to the named message
kinds, gives every model key a small integer id, removes what the conversion
cannot carry, and writes flat little-endian tables.

Usage:
  packc.py --from A[:kind,...] --to B[:kind,...] [--context key,key,...]
           [--model DIR] [--packs DIR] [--names]
           [--out-gtp FILE] [--out-rs FILE] [--static NAME] [--report FILE]
  packc.py --batch JOBS.json     many plans in one run (the proof harness)

  --from only   a decode-only plan (wire to model values)
  --to only     an encode-only plan (model values to wire)
  --context     the model keys the caller may supply at run time
  --names       keep key and kind names in the blob (debug section)

Only the `bits` wire is compiled, fixed and sequential layouts. Anything the
compiled form cannot express is refused with `packc: refused: <reason>: ...`
and exit status 2. The reasons are listed in embedded/FORMAT.md.

packc compiles packs the reference engine loads. It does not repeat the
reference engine's load checks; run the reference engine's tests first.

Python 3 standard library only. The same inputs give the same bytes.
"""
import argparse
import json
import os
import re
import struct
import sys

VERSION = 4
MAGIC = b"GTP1"

# section ids
S_FORMATS, S_OPS, S_POOL, S_CONDS, S_TABLES, S_KEYS, S_DERIVES, S_ARGS, S_PLAN, S_BYTES, S_CARRY, S_NAMEIDX, S_NAMES = range(1, 14)
SECTION_NAMES = {
    S_FORMATS: "formats", S_OPS: "ops", S_POOL: "pool", S_CONDS: "conds", S_TABLES: "tables",
    S_KEYS: "keys", S_DERIVES: "derives", S_ARGS: "args", S_PLAN: "plan", S_BYTES: "bytes",
    S_CARRY: "carry", S_NAMEIDX: "name-index", S_NAMES: "names",
}

# op codes
(OP_BODY, OP_KIND, OP_WHEN, OP_REQ, OP_DEFAULT, OP_FIELD, OP_ALSO, OP_CONST, OP_PAD, OP_ALIGN, OP_PRESENCE,
 OP_IF, OP_OPT, OP_CHAIN, OP_PART, OP_LENGTH, OP_WHOLE, OP_GROUP_SEQ, OP_GROUP_FIX, OP_GATE) = range(1, 21)
BLOCK_OPS = (OP_BODY, OP_KIND, OP_IF, OP_OPT, OP_CHAIN, OP_PART, OP_LENGTH, OP_GATE)
# GATE flags: the gate is negated (`if !<locator>`); step 3 of 0.17 Encode gives it a value
G_NEG, G_HAS_VALUE = 1, 2

XF = {"uint": 0, "twos": 1, "linscale": 2, "uscale": 3, "sscale": 4, "f32": 5, "f64": 6, "ascii": 7, "sixbit": 8,
      # the transforms of spec 0.15 from 9
      "uiscale": 9, "siscale": 10, "smag": 11, "smscale": 12, "f32scale": 13, "f64scale": 14,
      "chars_icao6": 15, "chars_ais6": 16, "chars_ascii7": 17, "octal": 18}
# transforms whose pool run starts with three parameter words
SCALED = ("linscale", "uscale", "sscale", "uiscale", "siscale", "smscale", "f32scale", "f64scale")
# transforms whose decode can fail: such a field stays in a plan that does not carry its key
FALLIBLE = ("ascii", "f32", "f64", "uiscale", "siscale", "smscale", "f32scale", "f64scale", "chars_icao6",
            "chars_ascii7")
# integer scales (spec 0.15, Exact factors): the words are integers, not doubles
EXACT = ("uiscale", "siscale")
# bits per character of `chars:<set>`
CHAR_WIDTH = {"chars_icao6": 6, "chars_ais6": 6, "chars_ascii7": 7}
T_INT, T_FLOAT, T_STR, T_LIST = 0, 1, 2, 3
TYPES = {"int": T_INT, "float": T_FLOAT, "string": T_STR}
F_SWAP, F_TRIM, F_OPTIONAL = 1, 2, 4
REP = {"count": 0, "while": 1, "more": 2, "fx": 3}
DERIVE = {"copy": 0, "hypot": 1, "bearing": 2, "east_of": 3, "north_of": 4, "neg": 5, "scale": 6,
          "offset_f": 7, "offset_i": 8, "day_seconds": 9, "any": 10, "not": 11, "parse_int": 12,
          "present": 13,
          # spec 0.16
          "sec_of": 14, "nsec_of": 15, "ms_of": 16, "deg": 17, "rad": 18, "add_i": 19, "add_f": 20,
          "sub_i": 21, "sub_f": 22, "deg_lon_of": 23, "m_lon_of": 24, "ecef_x": 25, "ecef_y": 26, "ecef_z": 27,
          "lon_of_ecef": 28}
# what gt-core must be built with for a function
DERIVE_FEATURE = {"hypot": ("sqrt",), "bearing": ("trig",), "east_of": ("trig",), "north_of": ("trig",),
                  "deg_lon_of": ("sqrt", "trig"), "m_lon_of": ("sqrt", "trig"), "ecef_x": ("sqrt", "trig"),
                  "ecef_y": ("sqrt", "trig"), "ecef_z": ("sqrt", "trig"), "lon_of_ecef": ("trig",)}
K_CONTEXT, K_LIVE = 1, 2
NONE16 = 0xFFFF
NONE32 = 0xFFFFFFFF

# limits the device engine is built with (embedded/gt-core/src/lib.rs)
MAX_SENTINELS = 255
MAX_DEPTH = 12
MAX_PRESENCE = 16
MAX_WHOLES = 4
MAX_DERIVE_ARGS = 8
MAX_GATES = 256         # gate blocks of one scope: the message's common lines and one kind, or one item


class Refused(Exception):
    def __init__(self, reason, detail):
        Exception.__init__(self, "%s: %s" % (reason, detail))
        self.reason = reason


def refuse(reason, detail):
    raise Refused(reason, detail)


# ---------------------------------------------------------------------------
# Text: tokens and numbers, read as the reference engine reads them
# ---------------------------------------------------------------------------

def tokenize(line):
    toks, cur, in_q, started = [], [], False, False
    for c in line:
        if in_q:
            if c == '"':
                in_q = False
            else:
                cur.append(c)
        elif c == '"':
            in_q, started = True, True
        elif c.isspace():
            if started:
                toks.append("".join(cur))
                cur, started = [], False
        elif c == "#" and not started:
            break
        else:
            cur.append(c)
            started = True
    if in_q:
        refuse("bad-pack", "unterminated quote in `%s`" % line.strip())
    if started:
        toks.append("".join(cur))
    return toks


_INT = re.compile(r"^[+-]?[0-9]+$")
_FLOAT = re.compile(r"^[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?$")
_DIGITS = re.compile(r"^[0-9]+$")


def read_int(text):
    """A 64-bit signed decimal integer, or None."""
    if not _INT.match(text):
        return None
    v = int(text)
    return v if -(1 << 63) <= v < (1 << 63) else None


def read_float(text):
    """A finite decimal number, or None."""
    if not _FLOAT.match(text):
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def read_as(ty, text):
    if ty == T_STR:
        return text
    return read_int(text) if ty == T_INT else read_float(text)


def f64_bits(x):
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def parse_scale(args, what):
    """`<factor>[:<offset>]`, factor a decimal or `<num>/<den>`: (num, den or 0.0, offset)."""
    parts = args.split(":")
    if len(parts) > 2:
        refuse("bad-pack", "`%s`: <factor>[:<offset>] expected" % what)
    offset = 0.0
    if len(parts) == 2:
        offset = read_float(parts[1])
        if offset is None:
            refuse("bad-pack", "`%s`: bad offset" % what)
    if "/" in parts[0]:
        n, d = parts[0].split("/", 1)
        if not (_DIGITS.match(n) and _DIGITS.match(d)) or float(n) == 0.0 or float(d) == 0.0:
            refuse("bad-pack", "`%s`: bad fraction" % what)
        return (float(n), float(d), offset)
    f = read_float(parts[0])
    if f is None or f == 0.0:
        refuse("bad-pack", "`%s`: bad factor" % what)
    return (f, 0.0, offset)


def parse_transform(name):
    """(transform name, pool words or None, yielded type)."""
    if name.startswith("linscale:"):
        p = name[len("linscale:"):].split(":")
        vals = [read_float(x) for x in p]
        if len(p) != 2 or None in vals:
            refuse("bad-pack", "`%s`: linscale needs <maxpos>:<range>" % name)
        return ("linscale", (vals[0], vals[1], 0.0), T_FLOAT)
    for prefix in ("uscale", "sscale"):
        if name.startswith(prefix + ":"):
            return (prefix, parse_scale(name[len(prefix) + 1:], name), T_FLOAT)
    if name in ("uint", "twos"):
        return (name, None, T_INT)
    if name in ("f32", "f64"):
        return (name, None, T_FLOAT)
    if name == "ascii":
        return (name, None, T_STR)
    if name == "sixbit":
        return (name, None, T_STR)
    # spec 0.15: the value transforms
    for prefix in EXACT:
        if name.startswith(prefix + ":"):
            return (prefix, parse_exact(name[len(prefix) + 1:], name), T_INT)
    for prefix in ("smscale", "f32scale", "f64scale"):
        if name.startswith(prefix + ":"):
            return (prefix, parse_scale(name[len(prefix) + 1:], name), T_FLOAT)
    if name == "smag":
        return (name, None, T_INT)
    if name == "octal":
        return (name, None, T_STR)
    if name in ("chars:icao6", "chars:ais6", "chars:ascii7"):
        return ("chars_" + name[len("chars:"):], None, T_STR)
    refuse("bad-pack", "transform `%s` is not a bits transform" % name)


def parse_exact(args, what):
    """`<factor>[:<offset>]` of an integer scale (spec 0.15, Exact factors):
    (num, den, offset) as integers, the factor in lowest terms."""
    from fractions import Fraction
    parts = args.split(":")
    if len(parts) > 2:
        refuse("bad-pack", "`%s`: <factor>[:<offset>] expected" % what)
    offset = 0
    if len(parts) == 2:
        if not re.match(r"^-?[0-9]+$", parts[1]) or abs(int(parts[1])) >= 1 << 63:
            refuse("bad-pack", "`%s`: bad offset" % what)
        offset = int(parts[1])
    f = parts[0]
    neg = f.startswith("-")
    body = f[1:] if neg else f
    if "/" in body:
        n, d = body.split("/", 1)
        if not (_DIGITS.match(n) and _DIGITS.match(d)) or int(d) == 0:
            refuse("bad-pack", "`%s`: bad fraction" % what)
        q = Fraction(int(n), int(d))
    else:
        m = re.match(r"^([0-9]+)(?:\.([0-9]+))?$", body)
        if not m:
            refuse("bad-pack", "`%s`: bad factor" % what)
        q = Fraction(int(m.group(1) + (m.group(2) or "")), 10 ** len(m.group(2) or ""))
    if neg:
        q = -q
    if q == 0 or abs(q.numerator) > 1 << 32 or q.denominator > 1 << 32:
        refuse("bad-pack", "`%s`: the factor is 0 or does not fit 2^32 over 2^32" % what)
    return (q.numerator, q.denominator, offset)
# The derive functions of spec 0.16; the device profile does not carry them.
# The derive functions of spec 0.16 the device does not compute: the meridional
# radius of `deg_lat_of` and `m_lat_of` takes a power (x^1.5) and the closed
# form of `lat_of_ecef` and `hae_of_ecef` a cube root, which gt-core does not
# carry and could not give the reference engine's platform results bit for bit.
V016_DERIVES = ("deg_lat_of", "m_lat_of", "lat_of_ecef", "hae_of_ecef")
# The derive functions of spec 0.18; the device profile does not carry them.
V018_DERIVES = ("tokens", "has_token", "text_if")
V016_REASON = ("the derive function `%s` (spec 0.16) is not in the device profile: it needs a power or a cube "
               "root, which gt-core does not compute as the platform library does")


# ---------------------------------------------------------------------------
# Model modules
# ---------------------------------------------------------------------------

class Model:
    def __init__(self):
        self.types = {}      # key as written in a pack -> T_*
        self.derives = []    # (module, target, function text, [args]) in the order the reference applies them

    def load_dir(self, d):
        per_module = {}
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".def"):
                continue
            module, derives = None, []
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                rows = [tokenize(l) for l in fh.read().split("\n")]
            for t in rows:
                if t[:1] == ["module"] and len(t) == 2:
                    module = t[1]
            if module is None:
                refuse("bad-model", "%s has no `module` line" % fn)
            full = lambda name: name if module == "core" else "%s.%s" % (module, name)
            for t in rows:
                if not t:
                    continue
                if t[0] == "key" and len(t) >= 3:
                    if t[2] not in TYPES:
                        refuse("bad-model", "%s: key `%s` has type `%s`" % (fn, t[1], t[2]))
                    self.types[full(t[1])] = TYPES[t[2]]
                elif t[0] == "list" and len(t) >= 2:
                    self.types[full(t[1])] = T_LIST
                elif t[0] == "derive" and len(t) >= 4:
                    derives.append((module, t[1], t[2], t[3:]))
            per_module[module] = derives
        # the reference applies the modules in byte order of name
        for module in sorted(per_module, key=lambda s: s.encode("utf-8")):
            self.derives.extend(per_module[module])

    def type_of(self, key):
        if key not in self.types:
            if key.startswith("core.") and key[5:] in self.types:
                refuse("unsupported-feature", "`%s`: a core key written with its module (ruling 2 of 0.4) "
                       "is not in the device profile" % key)
            refuse("unknown-key", "model key `%s` is declared by no module" % key)
        return self.types[key]


# ---------------------------------------------------------------------------
# Packs: text to one tree for both layouts
# ---------------------------------------------------------------------------

def new_body():
    return {"common": [], "kinds": [], "defaults": []}


def new_kind(name):
    return {"name": name, "whens": [], "requires": [], "lines": [], "defaults": []}


class Pack:
    def __init__(self, text, where):
        self.where = where
        self.format = None
        self.wire = None
        self.msb = False
        self.seq = False
        self.sixbit = False     # `armor sixbit` (engine-spec 0.14)
        self.word_bytes = 1
        self.maps = {}          # table -> [(native, model)]
        self.typemap = []       # (native, cot) in line order
        self.npresence = 0
        self.body = new_body()
        rows = []
        for raw in text.split("\n"):
            t = tokenize(raw)
            if t:
                rows.append(t)
        for t in rows:
            if t == ["layout", "sequential"]:
                self.seq = True
        self._header(rows)
        if self.wire != "bits":
            refuse("wire-not-bits", "format `%s` is on the `%s` wire; the device profile compiles the `bits` wire only"
                   % (self.format, self.wire))
        for t in rows:      # spec 0.92: a pack made for runs of messages is not in the device profile
            if t[0] == "framing":
                refuse("unsupported-feature", "%s: `framing` (a pack whose messages may stand in a run, spec 0.92) "
                       "is not in the device profile" % self.format)
        for t in rows:      # spec 0.34: a message of another pack inside a field is not in the device profile
            if t[0] == "inner":
                refuse("unsupported-feature", "%s: `inner <format>` (a message of another pack inside a field, "
                       "spec 0.34) is not in the device profile" % self.format)
        for t in rows:      # spec 0.22: long and terminated fields are not in the device profile
            if ((t[0] == "bit_order" and t[1:] == ["msb-lsb"])
                    or (t[0] in ("field", "also") and len(t) > 3
                        and (t[2].startswith("until:") or t[3] in ("hex", "chars:ascii8") or "stop" in t[4:]))):
                refuse("unsupported-feature", "%s: `bit_order msb-lsb`, `hex` on `bits`, `chars:ascii8`, `stop` "
                       "and `until:` (spec 0.22) are not in the device profile" % self.format)
        for t in rows:      # spec 0.83: a length given by an earlier count is not in the device profile
            if t[0] == "length" and len(t) > 1 and t[1].startswith("@"):
                refuse("unsupported-feature", "%s: `length @<name> units <u>` (spec 0.83) is not in the device profile"
                       % self.format)
        for t in rows:      # spec 0.21: sequential extents and counts are not in the device profile
            if t[0] == "count" or (t[0] == "group" and len(t) > 2
                                   and (t[2] in ("rest", "last") or (t[2] == "count" and len(t) > 3
                                                                     and t[3].startswith("@")))):
                refuse("unsupported-feature", "%s: `group … rest`, `group … last`, `count` lines and "
                       "`group … count @<name>` (spec 0.21) are not in the device profile" % self.format)
        for t in rows:      # spec 0.30 and 0.33: a `when` bound to a key or looking ahead is not in the device profile
            if t[0] == "when" and len(t) > 3 and t[3] in ("as", "at"):
                refuse("unsupported-feature", "%s: `when … as <key>` (spec 0.30) and `when … at <offset>` "
                       "(spec 0.33) are not in the device profile" % self.format)
        for t in rows:      # spec 0.20: kind selection beyond one value is not in the device profile
            if (t[0] in ("switch", "case", "else")
                    or (t[0] == "when" and len(t) > 2 and ("," in t[2] or ".." in t[2]))
                    or (t[0] == "requires" and any("=" in a for a in t[1:]))):
                refuse("unsupported-feature", "%s: `%s` with a list, a range, a `key=value` term or a `switch` "
                       "(kind selection, spec 0.20) is not in the device profile" % (self.format, t[0]))
        if self.seq:
            self.rows, self.i = rows, 0
            self.names = []          # visible presences: (name, id, bits)
            self.block_start = 0
            self.named = []          # per presence id: the bits `if` lines name
            self.cur_defaults = []
            self.body = self._seq_body(True)
            self._fill_named(self.body)
        else:
            self._fixed(rows)

    HEADER = ("format", "version", "wire", "layout", "bit_order", "distribution", "source", "uses", "map",
              "typemap", "word_bytes", "root", "armor", "encoding")

    def _header(self, rows):
        for t in rows:
            d = t[0]
            if d == "format":
                self.format = t[1]
            elif d == "wire":
                self.wire = t[1]
            elif d == "bit_order":
                self.msb = t[1] == "msb"
            elif d == "word_bytes":
                self.word_bytes = int(t[1])
            elif d == "encoding" and len(t) == 2 and t[1] != "none":
                refuse("unsupported-feature", "%s: `encoding %s` (ASN.1 unaligned PER, spec 0.19) is not in the "
                       "device profile" % (self.where, t[1]))
            elif d == "armor" and len(t) == 2:
                # engine-spec 0.14: `hex` (the default) or `sixbit`
                if t[1] not in ("hex", "sixbit"):
                    refuse("bad-pack", "%s: `armor %s`" % (self.where, t[1]))
                self.sixbit = t[1] == "sixbit"
            elif d == "map" and len(t) == 4:
                self.maps.setdefault(t[1], []).append((t[2], t[3]))
            elif d == "typemap" and len(t) == 3:
                self.typemap.append((t[1], t[2]))
        if self.format is None or self.wire is None:
            refuse("bad-pack", "%s: no `format` or no `wire` line" % self.where)
        if self.sixbit and not self.msb:
            refuse("bad-pack", "%s: `armor sixbit` needs `bit_order msb`" % self.where)
        if not (1 <= self.word_bytes <= 0xFFFF):
            refuse("bad-pack", "%s: word_bytes %d" % (self.where, self.word_bytes))

    # -- field line, shared -------------------------------------------------

    def _field(self, t, length, off):
        xf, params, yields = parse_transform(t[3])
        f = {"t": "field", "keys": [[t[1], None]], "len": length, "off": off, "xf": xf, "params": params,
             "yields": yields, "swap": False, "trim": False, "optional": False, "absent": []}
        i = 4
        seen_absent = False
        while i < len(t):
            if t[i] == "via" and i + 1 < len(t):
                f["keys"][0][1] = t[i + 1]
                i += 2
                continue
            if t[i] in ("swap", "trim", "optional"):
                f[t[i]] = True
                i += 1
                continue
            if t[i] == "absent":
                # engine-spec 0.9: the token after `absent` is always its argument (ruling 11)
                if i + 1 >= len(t) or seen_absent:
                    refuse("bad-pack", "%s: `absent` with no argument, or twice on one line" % self.format)
                seen_absent = True
                f["absent"] = self._sentinels(t[i + 1], length)
                i += 2
                continue
            if t[i] == "with":
                refuse("unsupported-feature", "%s: the field option `with` (spec 0.18) is not in the device profile"
                       % self.format)
            refuse("bad-pack", "%s: unknown field option `%s`" % (self.format, t[i]))
        ok = {"f32": length == 32, "f64": length == 64, "ascii": length % 8 == 0 and 8 <= length <= 2040,
              "sixbit": length % 6 == 0 and 6 <= length <= 1530,
              # spec 0.15
              "f32scale": length == 32, "f64scale": length == 64, "smag": 2 <= length <= 64,
              "smscale": 2 <= length <= 64, "octal": length % 3 == 0 and 3 <= length <= 63}.get(
            xf, 1 <= length <= 64)
        if xf in CHAR_WIDTH:
            w = CHAR_WIDTH[xf]
            ok = length % w == 0 and w <= length <= 2040
        # spec 0.15: `swap` with `chars` or `octal`, and `trim` with any of its transforms, are refused
        v015 = xf in CHAR_WIDTH or xf in ("octal", "uiscale", "siscale", "smag", "smscale", "f32scale", "f64scale")
        if f["trim"] and v015:
            refuse("bad-pack", "%s: `trim` with `%s`" % (self.format, t[3]))
        if not ok or (f["swap"] and (length % 8 != 0 or xf in CHAR_WIDTH or xf in ("octal", "sixbit"))):
            refuse("bad-pack", "%s: bit length %d is not allowed for `%s`" % (self.format, length, t[3]))
        return f

    def _sentinels(self, arg, length):
        """The values of `absent` on `bits` (engine-spec 0.9): unsigned decimal
        integers below 2^len, compared with the raw bits as `uint` reads them."""
        if length > 64:
            refuse("bad-pack", "%s: `absent` on a field of %d bits; 0.9 allows 64 at most" % (self.format, length))
        out = []
        for v in arg.split(","):
            if not _DIGITS.match(v) or int(v) >= 1 << length:
                refuse("bad-pack", "%s: `absent %s`: `%s` is not an unsigned decimal integer below 2^%d"
                       % (self.format, arg, v, length))
            out.append(int(v))
        if len(out) > MAX_SENTINELS:
            refuse("value-range", "%s: `absent` with %d values; the compiled form holds %d"
                   % (self.format, len(out), MAX_SENTINELS))
        return out

    # -- fixed layout -------------------------------------------------------

    def _span(self, loc):
        p = loc.split(":")
        if len(p) != 3:
            refuse("bad-pack", "%s: `%s` is not <word>:<pos>:<len>" % (self.format, loc))
        return int(p[0]) * self.word_bytes * 8 + int(p[1]), int(p[2])

    def _gate(self, t):
        """`if [!]<locator> <value>[,<value>...]` on a fixed layout (engine-spec 0.17)."""
        if len(t) != 3:
            refuse("bad-pack", "%s: `%s` is not one locator and one value list" % (self.format, " ".join(t)))
        loc, neg = t[1], t[1].startswith("!")
        off, ln = self._span(loc[1:] if neg else loc)
        if not 1 <= ln <= 64:
            refuse("bad-pack", "%s: a gate of %d bits" % (self.format, ln))
        values = []
        for v in t[2].split(","):
            if not _DIGITS.match(v) or int(v) >= 1 << ln or int(v) in values:
                refuse("bad-pack", "%s: gate value `%s` of `%s`" % (self.format, v, t[2]))
            values.append(int(v))
        return {"t": "gate", "off": off, "len": ln, "neg": neg, "values": values, "body": [], "defaults": []}

    def _fixed(self, rows):
        body = self.body
        # open groups and gate blocks, innermost last; `end` closes the innermost
        open_groups = []
        for t in rows:
            d = t[0]
            scope_kind = body["kinds"][-1] if body["kinds"] else None
            if open_groups and open_groups[-1]["t"] == "gate":
                lines, defaults = open_groups[-1]["body"], open_groups[-1]["defaults"]
            elif open_groups:
                lines = open_groups[-1]["body"]["common"]
                defaults = open_groups[-1]["body"]["defaults"]
            elif scope_kind is not None:
                lines, defaults = scope_kind["lines"], scope_kind["defaults"]
            else:
                lines, defaults = body["common"], body["defaults"]
            if d in self.HEADER or d == "layout":
                continue
            if d == "kind":
                body["kinds"].append(new_kind(t[1]))
            elif d == "when":
                off, ln = self._span(t[1])
                w = (off, ln, int(t[2]))
                if scope_kind is not None:
                    scope_kind["whens"].append(w)
                else:
                    body["common"].append({"t": "when", "off": off, "len": ln, "value": int(t[2])})
            elif d == "requires":
                scope_kind["requires"].extend(t[1:])
            elif d == "field":
                off, ln = self._span(t[2])
                lines.append(self._field(t, ln, off))
            elif d == "const":
                off, ln = self._span(t[1])
                lines.append({"t": "const", "off": off, "len": ln, "value": int(t[2])})
            elif d == "default":
                defaults.append((t[1], t[2]))
            elif d == "group":
                wp = t[2].split(":")
                g = {"t": "gfix", "list": t[1], "start": int(wp[0]) * self.word_bytes * 8 + int(wp[1]),
                     "item_bits": 1, "count": None, "body": new_body()}
                i = 3
                while i + 1 < len(t):
                    if t[i] == "item":
                        g["item_bits"] = int(t[i + 1])
                    elif t[i] == "count":
                        if _DIGITS.match(t[i + 1]):
                            g["count"] = ("fixed", int(t[i + 1]))
                        else:
                            off, ln = self._span(t[i + 1])
                            g["count"] = ("loc", off, ln)
                    i += 2
                if g["count"] is None:
                    refuse("bad-pack", "%s: a bits group needs `count`" % self.format)
                if any(o["t"] == "gate" for o in open_groups):
                    refuse("bad-pack", "%s: a group inside a gate block" % self.format)
                open_groups.append(g)
            elif d == "end":
                g = open_groups.pop()
                if open_groups and open_groups[-1]["t"] == "gate":
                    open_groups[-1]["body"].append(g)
                elif open_groups:
                    open_groups[-1]["body"]["common"].append(g)
                elif scope_kind is not None:
                    scope_kind["lines"].append(g)
                else:
                    body["common"].append(g)
            elif d == "if":
                # a gate block (engine-spec 0.17): field, const, default and nested gates
                open_groups.append(self._gate(t))
            else:
                refuse("bad-pack", "%s: directive `%s` is not a line of a fixed-layout bits pack" % (self.format, d))

    # -- sequential layout --------------------------------------------------

    def _peek(self):
        return self.rows[self.i] if self.i < len(self.rows) else None

    def _seq_body(self, top):
        out = new_body()
        visible = len(self.names)
        outer_block, self.block_start = self.block_start, visible
        outer_defaults, self.cur_defaults = self.cur_defaults, []
        common_names = None
        while True:
            t = self._peek()
            if t is None:
                if top:
                    break
                refuse("bad-pack", "%s: a group has no `end`" % self.format)
            d = t[0]
            if d == "end" and not top:
                self.i += 1
                break
            if d in self.HEADER:
                self.i += 1
            elif d == "kind":
                if out["kinds"]:
                    out["kinds"][-1]["defaults"] = self.cur_defaults
                else:
                    out["defaults"] = self.cur_defaults
                self.cur_defaults = []
                if common_names is None:
                    common_names = len(self.names)
                else:
                    del self.names[common_names:]
                out["kinds"].append(new_kind(t[1]))
                self.i += 1
            elif d == "when":
                ln, value = int(t[1]), int(t[2])
                if out["kinds"]:
                    out["kinds"][-1]["whens"].append((0, ln, value))
                else:
                    out["common"].append({"t": "when", "off": 0, "len": ln, "value": value})
                self.i += 1
            elif d == "requires":
                out["kinds"][-1]["requires"].extend(t[1:])
                self.i += 1
            else:
                line = self._seq_line()
                if line is not None:
                    (out["kinds"][-1]["lines"] if out["kinds"] else out["common"]).append(line)
        if out["kinds"]:
            out["kinds"][-1]["defaults"] = self.cur_defaults
        else:
            out["defaults"] = self.cur_defaults
        self.cur_defaults = outer_defaults
        del self.names[visible:]
        self.block_start = outer_block
        return out

    def _seq_block(self):
        visible = len(self.names)
        outer_block, self.block_start = self.block_start, visible
        out = []
        while True:
            t = self._peek()
            if t is None:
                refuse("bad-pack", "%s: a block has no `end`" % self.format)
            if t[0] == "end":
                self.i += 1
                break
            line = self._seq_line()
            if line is not None:
                out.append(line)
        del self.names[visible:]
        self.block_start = outer_block
        return out

    def _seq_line(self):
        t = self._peek()
        self.i += 1
        d = t[0]
        if d == "default":
            self.cur_defaults.append((t[1], t[2]))
            return None
        if d == "field":
            f = self._field(t, int(t[2]), 0)
            if f["optional"]:
                refuse("bad-pack", "%s: `optional` in a sequential pack" % self.format)
            while self._peek() is not None and self._peek()[0] == "also":
                a = self._peek()
                f["keys"].append([a[1], a[3] if len(a) == 4 else None])
                self.i += 1
            return f
        if d == "const":
            return {"t": "const", "off": 0, "len": int(t[1]), "value": int(t[2])}
        if d == "pad":
            return {"t": "pad", "n": int(t[1])}
        if d == "align":
            return {"t": "align", "n": int(t[1])}
        if d == "presence":
            bits = None if t[2] == "fx" else int(t[2])
            pid = self.npresence
            self.npresence += 1
            self.named.append(set())
            self.names.append((t[1], pid, bits))
            return {"t": "presence", "id": pid, "bits": bits, "named": None}
        if d == "if":
            conds = []
            for c in t[1:]:
                neg = c.startswith("!")
                name, bit = (c[1:] if neg else c).rsplit(".", 1)
                found = [n for n in self.names if n[0] == name]
                if not found:
                    refuse("bad-pack", "%s: `%s` names a presence that is not visible" % (self.format, c))
                pid = found[-1][1]
                self.named[pid].add(int(bit))
                conds.append((pid, int(bit), neg))
            return {"t": "if", "conds": conds, "body": self._seq_block()}
        if d == "opt":
            return {"t": "opt", "body": self._seq_block()}
        if d == "chain":
            visible = len(self.names)
            outer_block, self.block_start = self.block_start, visible
            parts, ends_fx = [[]], False
            while True:
                c = self._peek()
                if c is None:
                    refuse("bad-pack", "%s: a chain has no `end`" % self.format)
                if c[0] == "end":
                    self.i += 1
                    break
                if c[0] == "fx":
                    self.i += 1
                    parts.append([])
                    ends_fx = True
                    continue
                line = self._seq_line()
                if line is not None:
                    parts[-1].append(line)
                    ends_fx = False
            if ends_fx:
                parts.pop()
            del self.names[visible:]
            self.block_start = outer_block
            return {"t": "chain", "parts": parts, "ends_fx": ends_fx}
        if d == "length":
            in_bits, plus, whole = False, 0, False
            i = 2
            while i < len(t):
                if t[i] == "bits":
                    in_bits = True
                elif t[i] == "whole":
                    whole = True
                elif t[i] == "plus":
                    i += 1
                    plus = int(t[i])
                i += 1
            if whole:
                if self.sixbit:
                    refuse("bad-pack", "%s: `length ... whole` with `armor sixbit` (ruling 3 of 0.14)" % self.format)
                return {"t": "whole", "len": int(t[1]), "plus": plus}
            return {"t": "length", "len": int(t[1]), "in_bits": in_bits, "plus": plus, "body": self._seq_block()}
        if d == "group":
            rep = t[2]
            if rep not in REP:
                refuse("bad-pack", "%s: group `%s`: `%s` is not count, while, more or fx" % (self.format, t[1], rep))
            return {"t": "group", "list": t[1], "rep": rep, "replen": int(t[3]) if rep == "count" else 0,
                    "body": self._seq_body(False)}
        refuse("bad-pack", "%s: directive `%s` is not a line of a sequential bits pack" % (self.format, d))

    def _fill_named(self, body):
        def lines(ls):
            for l in ls:
                if l["t"] == "presence":
                    l["named"] = self.named[l["id"]]
                elif l["t"] in ("if", "opt", "length"):
                    lines(l["body"])
                elif l["t"] == "chain":
                    for p in l["parts"]:
                        lines(p)
                elif l["t"] == "group":
                    self._fill_named(l["body"])
        lines(body["common"])
        for k in body["kinds"]:
            lines(k["lines"])


def sub_blocks(line):
    """The line lists nested directly in a line (not group bodies)."""
    if line["t"] in ("if", "opt", "length", "gate"):
        return [line["body"]]
    if line["t"] == "chain":
        return line["parts"]
    return []


def walk_scope(lines, fn):
    """Every line of one scope, blocks included, group bodies excluded."""
    for l in lines:
        fn(l)
        for b in sub_blocks(l):
            walk_scope(b, fn)


def body_parts(body, kinds):
    """(lines, defaults, kind or None) of a body: common, then each kind in `kinds`."""
    out = [(body["common"], body["defaults"], None)]
    for k in body["kinds"]:
        if kinds is None or k["name"] in kinds:
            out.append((k["lines"], k["defaults"], k))
    return out


def scope_keys(body, kinds, path, keys, lists, defaults):
    """Per list path: the keys fields map, the lists groups map, the keys with a default."""
    for lines, defs, _ in body_parts(body, kinds):
        for key, _ in defs:
            defaults.setdefault(path, set()).add(key)

        def see(l):
            if l["t"] == "field":
                for key, _ in l["keys"]:
                    keys.setdefault(path, set()).add(key)
            elif l["t"] == "gate":
                for key, _ in l["defaults"]:
                    defaults.setdefault(path, set()).add(key)
            elif l["t"] in ("group", "gfix"):
                lists.setdefault(path, set()).add(l["list"])
                scope_keys(l["body"], None, path + (l["list"],), keys, lists, defaults)
        walk_scope(lines, see)


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

class Compiler:
    def __init__(self, model, keep_names):
        self.model = model
        self.keep_names = keep_names
        self.pool, self.pool_at = [], {}
        self.bytes_, self.bytes_at = bytearray(), {}
        self.conds = []
        self.tables, self.table_at = [], {}
        self.keys, self.key_at = [], {}       # [type, flags, name]
        self.names, self.name_at = [], {}
        self.ops = []
        self.formats = []
        self.derives, self.args = [], []
        self.features = set()
        self.notes = []
        self.max_depth = 0
        # (format, list) -> kind name -> its number among the item kinds of
        # every group of that list (ruling 26 of 0.8: an item's kind is its name)
        self.item_kinds = {}

    # -- shared tables ------------------------------------------------------

    def pool_of(self, words):
        words = tuple(w & 0xFFFFFFFFFFFFFFFF for w in words)
        if words not in self.pool_at:
            self.pool_at[words] = len(self.pool)
            self.pool.extend(words)
            if len(self.pool) > NONE16:
                refuse("table-overflow", "more than 65535 pool words; compile fewer kinds")
        return self.pool_at[words]

    def str_ref(self, text):
        b = text.encode("utf-8")
        if len(b) > 0xFFFF:
            refuse("table-overflow", "a text value of %d bytes" % len(b))
        if b not in self.bytes_at:
            at = self.bytes_.find(b) if b else 0
            if at < 0:
                at = len(self.bytes_)
                self.bytes_.extend(b)
            self.bytes_at[b] = at
        return self.bytes_at[b] | (len(b) << 32)

    def value_word(self, ty, v):
        if ty == T_INT:
            return v
        if ty == T_FLOAT:
            return f64_bits(float(v))
        return self.str_ref(v)

    def name_id(self, text):
        if not self.keep_names:
            return NONE16
        if text not in self.name_at:
            self.name_at[text] = len(self.names)
            self.names.append(text)
            if len(self.names) >= NONE16:
                refuse("table-overflow", "more than 65534 names; compile without --names")
        return self.name_at[text]

    def key(self, name, flags=K_LIVE):
        if name not in self.key_at:
            self.key_at[name] = len(self.keys)
            self.keys.append([self.model.type_of(name), 0, name])
            if len(self.keys) >= NONE16:
                refuse("table-overflow", "more than 65534 model keys; compile fewer kinds")
        i = self.key_at[name]
        self.keys[i][1] |= flags
        return i

    def table(self, pack, name, native_ty, key_ty):
        """A value table specialised to the two types it is used with."""
        ident = (pack.format, name, native_ty, key_ty)
        if ident in self.table_at:
            return self.table_at[ident]
        entries = []   # (flags, native word, model word): 1 native valid, 2 model valid, 4 decode, 8 encode
        if name is None:
            # the pack-wide typemap on the key `type`: the last line for a code wins, each way
            dec, enc = {}, {}
            for native, cot in pack.typemap:
                dec[native] = cot
                enc[cot] = native
            for native, cot in dec.items():
                entries.append((1 | 2 | 4, self.str_ref(native), self.str_ref(cot)))
            for cot, native in enc.items():
                entries.append((1 | 2 | 8, self.str_ref(native), self.str_ref(cot)))
        else:
            for native, model_v in pack.maps[name]:
                n, m = read_as(native_ty, native), read_as(key_ty, model_v)
                flags = 4 | 8 | (1 if n is not None else 0) | (2 if m is not None else 0)
                entries.append((flags, self.value_word(native_ty, n) if n is not None else 0,
                                self.value_word(key_ty, m) if m is not None else 0))
        words = []
        for e in entries:
            words.extend(e)
        first = self.pool_of(words) if words else 0
        self.table_at[ident] = len(self.tables)
        self.tables.append((native_ty, key_ty, len(entries), first))
        if len(self.tables) >= NONE16:
            refuse("table-overflow", "more than 65534 value tables")
        return self.table_at[ident]

    def table_fallible(self, pack, name, native_ty, key_ty):
        """Can decode through this table fail?"""
        if native_ty != key_ty:
            return True
        return any(read_as(key_ty, m) is None for _, m in pack.maps[name])

    def field_table(self, pack, key, via, yields):
        key_ty = self.model.type_of(key)
        if key_ty == T_LIST:
            refuse("bad-pack", "%s: a field names the list `%s`" % (pack.format, key))
        if key == "type" and pack.typemap and yields == T_STR:
            if via is not None:
                refuse("via-with-typemap", "%s: key `type` goes through `via %s` and the pack-wide typemap; "
                       "the compiled form holds one table per field" % (pack.format, via))
            return self.table(pack, None, T_STR, T_STR)
        if via is None:
            return NONE16
        if via not in pack.maps:
            refuse("bad-pack", "%s: `via %s` names a table with no `map` line" % (pack.format, via))
        return self.table(pack, via, yields, key_ty)

    # -- ops ----------------------------------------------------------------

    @staticmethod
    def node(op, xf=0, flags=0, key=NONE16, length=0, a=0, b=0, c=NONE16, kids=None, nabsent=0):
        return {"op": op, "xf": xf, "flags": flags, "key": key, "len": length, "a": a, "b": b, "c": c,
                "nabsent": nabsent, "kids": kids if kids is not None else []}

    def flatten(self, node, out):
        at = len(out)
        out.append(node)
        for k in node["kids"]:
            self.flatten(k, out)
        if node["op"] in BLOCK_OPS:
            node["a"] = len(out) - at - 1
        return out

    def check(self, cond, reason, detail):
        if not cond:
            refuse(reason, detail)

    def u16(self, v, what):
        self.check(0 <= v <= 0xFFFF, "value-range", "%s is %d; the compiled form holds 0 to 65535" % (what, v))
        return v

    def u32(self, v, what):
        self.check(0 <= v <= 0xFFFFFFFF, "value-range", "%s is %d; the compiled form holds 32 bits" % (what, v))
        return v

    def compile_format(self, pack, kinds, role, view):
        """One format as an op tree. `role`: "dec", "enc" or "both". `view` says what the plan keeps."""
        self.check(pack.npresence <= MAX_PRESENCE, "too-many-presences",
                   "%s declares %d presence fields; the device engine holds %d" % (pack.format, pack.npresence, MAX_PRESENCE))
        if kinds is not None:
            have = [k["name"] for k in pack.body["kinds"]]
            for k in kinds:
                self.check(k in have, "unknown-kind", "format `%s` has no kind `%s`" % (pack.format, k))
        self.wholes = 0
        root = self.body(pack, pack.body, kinds, role, view, (), 1, True)
        self.check(self.wholes <= MAX_WHOLES, "too-many-wholes",
                   "%s has %d `length ... whole` lines; the device engine holds %d" % (pack.format, self.wholes, MAX_WHOLES))
        first = len(self.ops)
        self.flatten(root, self.ops)
        self.formats.append({"flags": (1 if pack.msb else 0) | (2 if pack.seq else 0) | (4 if pack.sixbit else 0), "word_bytes": pack.word_bytes,
                             "body": first, "name": self.name_id(pack.format), "npresence": pack.npresence,
                             "first": first, "end": len(self.ops), "format": pack.format})
        return len(self.formats) - 1

    def fixed_extent(self, lines):
        """(reach, decode need, encode need) in bits of the fixed-layout lines of one part."""
        reach = need_dec = need_enc = 0
        for l in lines:
            if l["t"] == "field":
                end = l["off"] + l["len"]
                need_enc = max(need_enc, end)
                if not l["optional"]:
                    reach, need_dec = max(reach, end), max(need_dec, end)
            elif l["t"] in ("const", "when"):
                end = l["off"] + l["len"]
                need_dec, need_enc = max(need_dec, end), max(need_enc, end)
        return reach, need_dec, need_enc

    def kind_number(self, pack, lst, name, i):
        """The number of a kind: its position in the message body, or, for an
        item kind of a group of list `lst`, one number per kind name across
        all groups of that list in the pack, so that an item decoded through
        one group is known by its name in another."""
        if lst is None:
            return i
        names = self.item_kinds.setdefault((pack.format, lst), {})
        return names.setdefault(name, len(names))

    def body(self, pack, body, kinds, role, view, path, depth, top, lst=None):
        self.check(depth <= MAX_DEPTH, "nesting-too-deep",
                   "%s nests blocks more than %d deep" % (pack.format, MAX_DEPTH))
        self.max_depth = max(self.max_depth, depth)
        enc = role in ("enc", "both")
        dec = role in ("dec", "both")
        n = self.node(OP_BODY)
        kids = n["kids"]
        defaults = lambda defs: self.defaults(pack, defs, enc)
        # gate blocks are numbered per scope, in line order, depth first: the
        # common lines from 0, each kind after them
        gates = [0]
        kids.extend(defaults(body["defaults"]))
        kids.extend(self.lines(pack, body["common"], role, view, path, depth, top, gates))
        if not pack.seq:
            ext = self.fixed_extent(body["common"])
            w0 = [k for k in body["common"] if k["t"] == "when"]
            for w in w0:
                ext = (ext[0], max(ext[1], w["off"] + w["len"]), max(ext[2], w["off"] + w["len"]))
            n["b"] = self.pool_of(ext)
        # kinds: the named ones in full; an earlier kind that is not named keeps
        # only what selects it, so a message of that kind is refused and not
        # read as a later kind
        kept = [k for k in body["kinds"] if kinds is None or k["name"] in kinds]
        last = body["kinds"].index(kept[-1]) if kept and kinds is not None else len(body["kinds"]) - 1
        for i, k in enumerate(body["kinds"]):
            if i > last:
                break
            excluded = kinds is not None and k["name"] not in kinds
            kn = self.node(OP_KIND, key=self.kind_number(pack, lst, k["name"], i), flags=1 if excluded else 0, c=self.name_id(k["name"]))
            for off, ln, value in k["whens"]:
                self.check(1 <= ln <= 64, "bad-pack", "%s: a `when` of %d bits" % (pack.format, ln))
                kn["kids"].append(self.node(OP_WHEN, length=ln, a=self.u32(off, "a bit offset"), b=self.pool_of([value])))
            if excluded and enc and not dec and not all(view.possible(path, r) for r in k["requires"]):
                # the conversion can never give this kind its required keys
                continue
            # one format both ways encodes the kind it decoded: a kind left out needs no `requires`
            if enc and not (excluded and dec):
                for r in k["requires"]:
                    ty = self.model.type_of(r)
                    kn["kids"].append(self.node(OP_REQ, key=self.key(r), flags=1 if ty == T_LIST else 0))
            if not excluded:
                kn["kids"].extend(defaults(k["defaults"]))
                kn["kids"].extend(self.lines(pack, k["lines"], role, view, path, depth, top, [gates[0]]))
            if not pack.seq:
                kn["b"] = self.pool_of(self.fixed_extent(k["lines"])[:1] + tuple(
                    max(x, max([off + ln for off, ln, _ in k["whens"]] or [0])) for x in self.fixed_extent(k["lines"])[1:]))
            kids.append(kn)
        return n

    def defaults(self, pack, defs, enc):
        out = []
        for key, text in defs if enc else []:
            ty = self.model.type_of(key)
            v = read_as(ty, text)
            self.check(ty != T_LIST and v is not None, "bad-pack",
                       "%s: default `%s` of `%s` is not of the key's type" % (pack.format, text, key))
            out.append(self.node(OP_DEFAULT, xf=ty, key=self.key(key), b=self.pool_of([self.value_word(ty, v)])))
        return out

    def lines(self, pack, lines, role, view, path, depth, top, gates=None):
        self.check(depth <= MAX_DEPTH, "nesting-too-deep",
                   "%s nests blocks more than %d deep" % (pack.format, MAX_DEPTH))
        self.max_depth = max(self.max_depth, depth)
        out = []
        if not pack.seq:
            # fixed layout: the engine passes over a scope by kind of line; fields and gate
            # blocks come first, in line order (the sort is stable)
            order = {"field": 0, "gate": 0, "when": 1, "const": 2, "gfix": 3}
            lines = sorted(lines, key=lambda l: order[l["t"]])
        for l in lines:
            t = l["t"]
            if t == "field":
                out.extend(self.field(pack, l, role, view, path))
            elif t == "gate":
                out.append(self.gate(pack, l, role, view, path, depth, top, gates))
            elif t in ("const", "when"):
                self.check(1 <= l["len"] <= 64, "bad-pack", "%s: a `%s` of %d bits" % (pack.format, t, l["len"]))
                out.append(self.node(OP_CONST if t == "const" else OP_WHEN, length=l["len"],
                                     a=self.u32(l["off"], "a bit offset"), b=self.pool_of([l["value"]])))
            elif t == "pad":
                out.append(self.node(OP_PAD, a=self.u32(l["n"], "a `pad` length")))
            elif t == "align":
                out.append(self.node(OP_ALIGN, a=self.u32(l["n"], "an `align` step")))
            elif t == "presence":
                bits = l["bits"]
                self.check(bits is None or 1 <= bits <= 64, "presence-too-wide",
                           "%s: a presence of %s bits; the device engine holds 64" % (pack.format, bits))
                self.check(all(1 <= b <= 64 for b in l["named"]), "presence-too-wide",
                           "%s: an `if` names presence bit %d; the device engine holds bits 1 to 64"
                           % (pack.format, max(l["named"] or [0])))
                mask = 0
                for b in l["named"]:
                    mask |= 1 << (b - 1)
                out.append(self.node(OP_PRESENCE, key=l["id"], length=bits or 0, b=self.pool_of([mask])))
            elif t == "if":
                first = len(self.conds)
                for pid, bit, neg in l["conds"]:
                    self.conds.append((pid, bit, 1 if neg else 0))
                self.check(len(self.conds) < NONE16, "table-overflow", "more than 65534 `if` conditions")
                out.append(self.node(OP_IF, length=len(l["conds"]), b=first,
                                     kids=self.lines(pack, l["body"], role, view, path, depth + 1, top)))
            elif t == "opt":
                out.append(self.node(OP_OPT, kids=self.lines(pack, l["body"], role, view, path, depth + 1, top)))
            elif t == "chain":
                parts = [self.node(OP_PART, kids=self.lines(pack, p, role, view, path, depth + 1, top)) for p in l["parts"]]
                out.append(self.node(OP_CHAIN, flags=1 if l["ends_fx"] else 0, length=self.u16(len(parts), "chain parts"),
                                     kids=parts))
            elif t == "length":
                self.check(1 <= l["len"] <= 64, "bad-pack", "%s: a `length` of %d bits" % (pack.format, l["len"]))
                self.check(abs(l["plus"]) < (1 << 31), "length-plus-range",
                           "%s: `length ... plus %d`; the device engine holds a 32-bit `plus`" % (pack.format, l["plus"]))
                out.append(self.node(OP_LENGTH, flags=1 if l["in_bits"] else 0, length=l["len"], b=self.pool_of([l["plus"]]),
                                     kids=self.lines(pack, l["body"], role, view, path, depth + 1, top)))
            elif t == "whole":
                self.check(top, "whole-in-group", "%s: `length ... whole` inside a group" % pack.format)
                self.check(abs(l["plus"]) < (1 << 31), "length-plus-range",
                           "%s: `length ... plus %d`; the device engine holds a 32-bit `plus`" % (pack.format, l["plus"]))
                self.wholes += 1
                out.append(self.node(OP_WHOLE, length=l["len"], b=self.pool_of([l["plus"]])))
            elif t in ("group", "gfix"):
                out.append(self.group(pack, l, role, view, path, depth))
        return out

    def gate(self, pack, l, role, view, path, depth, top, gates):
        """A gate block (engine-spec 0.17): its defaults, its fields and nested blocks in line
        order, then its `const` lines. Every block stays in the plan, also one whose lines the
        conversion does not carry: its gate and its extent still decide the length."""
        index = gates[0]
        gates[0] += 1
        self.check(index < MAX_GATES, "too-many-gates", "%s: more than %d gate blocks in one scope; the device "
                   "engine holds %d" % (pack.format, MAX_GATES, MAX_GATES))
        enc = role in ("enc", "both")
        kids = self.defaults(pack, l["defaults"], enc)
        kids.extend(self.lines(pack, l["body"], role, view, path, depth + 1, top, gates))
        # step 3 of Encode: the first value listed, or for `!` the smallest value not listed
        if l["neg"]:
            listed = set(l["values"])
            value = next((v for v in range(len(listed) + 1) if v not in listed), None)
            if value is not None and value >= 1 << l["len"]:
                value = None
        else:
            value = l["values"][0]
        self.check(len(l["values"]) <= 0xFFFF, "value-range", "%s: a gate with %d values; the compiled form "
                   "holds 65535" % (pack.format, len(l["values"])))
        # the extent of the block's own lines: nested blocks count only when they hold
        words = [l["off"]] + list(self.fixed_extent(l["body"])) + [value or 0] + l["values"]
        flags = (G_NEG if l["neg"] else 0) | (G_HAS_VALUE if value is not None else 0)
        return self.node(OP_GATE, flags=flags, key=index, length=l["len"], b=self.pool_of(words),
                         c=len(l["values"]), kids=kids)

    def field(self, pack, l, role, view, path):
        enc = role in ("enc", "both")
        dec = role in ("dec", "both")
        keys = []
        for key, via in l["keys"]:
            keep = (dec and view.src_keep(path, key)) or (enc and view.tgt_keep(path, key))
            if keep:
                keys.append((key, via))
        always_absent = False
        if not keys and enc and l["absent"]:
            # a target field the conversion never gives a value still writes
            # its first sentinel (engine-spec 0.9, Encode): it stays, on its
            # first key, which the plan never sets
            keys, always_absent = [l["keys"][0]], True
        if not keys:
            # nothing the plan carries: a sequential field still takes its bits
            return [self.node(OP_PAD, a=l["len"])] if pack.seq else []
        flags = (F_SWAP if l["swap"] else 0) | (F_TRIM if l["trim"] else 0) | (F_OPTIONAL if l["optional"] else 0)
        # the pool run of a field: its scale (three words), then its sentinels
        if l["xf"] in EXACT:
            words = list(l["params"])
        else:
            words = [f64_bits(x) for x in l["params"]] if l["params"] else []
        words += l["absent"]
        b = self.pool_of(words) if words else 0
        out = []
        for i, (key, via) in enumerate(keys):
            table = NONE16 if always_absent else self.field_table(pack, key, via, l["yields"])
            if i == 0:
                out.append(self.node(OP_FIELD, xf=XF[l["xf"]], flags=flags,
                                     key=self.key(key, 0 if always_absent else K_LIVE), length=l["len"],
                                     a=self.u32(l["off"], "a bit offset"), b=b, c=table, nabsent=len(l["absent"])))
            else:
                out.append(self.node(OP_ALSO, key=self.key(key), c=table))
        return out

    def group(self, pack, l, role, view, path, depth):
        enc = role in ("enc", "both")
        dec = role in ("dec", "both")
        lst = l["list"]
        self.check(self.model.type_of(lst) == T_LIST, "bad-pack", "%s: `group %s` names a key, not a list" % (pack.format, lst))
        carried = (dec and view.src_list_keep(path, lst)) or (enc and view.tgt_list_possible(path, lst))
        inner = path + (lst,)
        if enc and not dec and not carried:
            # the list is never present on encode: its body is never written
            body = self.node(OP_BODY)
            if not pack.seq:
                body["b"] = self.pool_of((0, 0, 0))
        else:
            body = self.body(pack, l["body"], None, role, view, inner, depth + 1, False, lst)
        flags = 0 if carried else 1
        if l["t"] == "group":
            self.check(1 <= l["replen"] <= 64 or l["rep"] != "count", "bad-pack",
                       "%s: a group count of %d bits" % (pack.format, l["replen"]))
            return self.node(OP_GROUP_SEQ, xf=REP[l["rep"]], flags=flags, key=self.key(lst), length=l["replen"], kids=[body])
        if l["count"][0] == "fixed":
            xf, ln, second = 0, 0, l["count"][1]
        else:
            xf, ln, second = 1, l["count"][2], l["count"][1]
            self.check(1 <= ln <= 64, "bad-pack", "%s: a group count of %d bits" % (pack.format, ln))
        return self.node(OP_GROUP_FIX, xf=xf, flags=flags, key=self.key(lst), length=ln,
                         a=self.u32(l["start"], "a bit offset"), b=self.pool_of([l["item_bits"], second]), kids=[body])

    # -- derivations --------------------------------------------------------

    def derive_fn(self, text, target, args):
        """(function name, pool words) of a derive line, or a refusal reason."""
        tty = self.model.type_of(target)
        if text.startswith("scale:"):
            num, den, _ = parse_scale(text[len("scale:"):], text)
            return "scale", (f64_bits(num), f64_bits(den))
        if text.startswith("offset:"):
            a = text[len("offset:"):]
            if tty == T_INT:
                return "offset_i", (read_int(a),)
            return "offset_f", (f64_bits(read_float(a)),)
        if text.startswith("join:") or text == "text_of":
            return None, "`%s` builds new text, and the device engine has no text store" % text.split(":")[0]
        if text in ("add", "sub"):
            # spec 0.16, ruling 4: all `int` or all `float`
            return text + ("_i" if tty == T_INT else "_f"), ()
        if text in DERIVE:
            return text, ()
        if text.split(":", 1)[0] in V018_DERIVES:
            return None, "the derive function `%s` (spec 0.18) is not in the device profile" % text.split(":", 1)[0]
        if text in V016_DERIVES:
            return None, V016_REASON % text
        return None, "unknown function `%s`" % text

    def compile_derives(self, possible, needed, strict, produced=()):
        """The derive lines the plan can use, in the order the reference applies them.

        `possible`: keys that may be present before derivation. `needed`: keys the
        encoder reads. Both are extended. `produced`: keys the source decode itself
        gives or the caller supplies as context; a line whose target is one of them
        is not needed, because a derive line only sets a key the entity lacks (the `uid` <-> `mmsi` pair of a model
        module, say, never derives `uid` from a source that decodes `uid`).
        Returns the lines kept."""
        produced = set(produced)
        lines = [l for l in self.model.derives if l[1] not in produced] if produced else self.model.derives
        changed = True
        while changed:
            changed = False
            for _, target, fn, args in lines:
                can = any(a in possible for a in args) if fn == "any" else all(a in possible for a in args)
                if can and target not in possible:
                    possible.add(target)
                    changed = True
        if needed is not None:
            changed = True
            while changed:
                changed = False
                for _, target, fn, args in lines:
                    can = any(a in possible for a in args) if fn == "any" else all(a in possible for a in args)
                    if can and target in needed:
                        for a in args:
                            if a in possible and a not in needed:
                                needed.add(a)
                                changed = True
        kept = []
        for _, target, fn, args in lines:
            can = any(a in possible for a in args) if fn == "any" else all(a in possible for a in args)
            if not can or (needed is not None and target not in needed):
                continue
            name, extra = self.derive_fn(fn, target, args)
            if name is None or len(args) > MAX_DERIVE_ARGS:
                why = extra if name is None else "more than %d arguments" % MAX_DERIVE_ARGS
                if strict and (fn in V016_DERIVES or fn.split(":", 1)[0] in V018_DERIVES):
                    refuse("unsupported-feature", "`derive %s %s ...` is needed by this conversion: %s" % (target, fn, why))
                if strict:
                    refuse("derive-function", "`derive %s %s ...` is needed by this conversion: %s" % (target, fn, why))
                self.notes.append("derive %s %s: not compiled (%s)" % (target, fn, why))
                continue
            if name in DERIVE_FEATURE:
                self.features.update(DERIVE_FEATURE[name])
            first = len(self.args)
            self.args.extend(self.key(a) for a in args)
            self.check(len(self.args) < NONE16, "table-overflow", "more than 65534 derive arguments")
            self.derives.append((DERIVE[name], len(args), self.key(target), first, self.pool_of(extra) if extra else 0))
            kept.append((target, fn, args))
        return kept

    # -- the blob -----------------------------------------------------------

    def blob(self, plan):
        sections = []

        def add(sid, entry, count, data):
            sections.append((sid, entry, count, bytes(data)))

        add(S_FORMATS, 16, len(self.formats), b"".join(
            struct.pack("<BBHIHHI", f["flags"], 0, f["word_bytes"], f["body"], f["name"], f["npresence"], 0)
            for f in self.formats))
        add(S_OPS, 16, len(self.ops), b"".join(
            struct.pack("<BBBBHHIHH", o["op"], o["xf"], o["flags"], o["nabsent"], o["key"], o["len"], o["a"], o["b"], o["c"])
            for o in self.ops))
        add(S_POOL, 8, len(self.pool), b"".join(struct.pack("<Q", w) for w in self.pool))
        add(S_CONDS, 4, len(self.conds), b"".join(struct.pack("<HBB", *c) for c in self.conds))
        add(S_TABLES, 8, len(self.tables), b"".join(struct.pack("<BBHI", *t) for t in self.tables))
        add(S_KEYS, 4, len(self.keys), b"".join(struct.pack("<BBH", k[0], k[1], self.name_id(k[2])) for k in self.keys))
        add(S_DERIVES, 8, len(self.derives), b"".join(struct.pack("<BBHHH", *d) for d in self.derives))
        add(S_ARGS, 2, len(self.args), b"".join(struct.pack("<H", a) for a in self.args))
        add(S_PLAN, 12, 1, struct.pack("<HHBBHI", plan["src"], plan["dst"], plan["flags"], self.max_depth, len(self.keys), 0))
        add(S_BYTES, 1, len(self.bytes_), self.bytes_)
        add(S_CARRY, 12, len(plan["carry"]), b"".join(struct.pack("<HHII", *c) for c in plan["carry"]))
        if self.keep_names:
            data, offsets = bytearray(), []
            for name in self.names:
                b = name.encode("utf-8")
                self.check(len(b) <= 255, "table-overflow", "a name of %d bytes" % len(b))
                offsets.append(len(data))
                data.append(len(b))
                data.extend(b)
            add(S_NAMEIDX, 4, len(offsets), b"".join(struct.pack("<I", o) for o in offsets))
            add(S_NAMES, 1, len(data), data)
        head = 16 + 12 * len(sections)
        out, directory, at = bytearray(), bytearray(), head
        for sid, entry, count, data in sections:
            directory.extend(struct.pack("<HHII", sid, entry, at, count))
            at += len(data) + (-len(data)) % 4
        out.extend(MAGIC)
        out.extend(struct.pack("<HHIHH", VERSION, 1 if self.keep_names else 0, at, len(sections), 0))
        out.extend(directory)
        sizes = {"header": head}
        for sid, entry, count, data in sections:
            out.extend(data)
            out.extend(b"\0" * ((-len(data)) % 4))
            sizes[SECTION_NAMES[sid]] = len(data)
        assert len(out) == at
        return bytes(out), sizes


class View:
    """What a plan keeps: asked by the compiler for every key and list."""

    def __init__(self):
        self.all = True
        self.src_keys, self.src_lists = {}, {}
        self.tgt_keys, self.tgt_lists, self.tgt_defaults = {}, {}, {}
        self.possible_top, self.needed_top = set(), set()
        self.fallible = {}
        self.cross = False

    def possible(self, path, key):
        if not self.cross:
            return True
        if path == ():
            return key in self.possible_top
        return key in self.src_keys.get(path, ()) or key in self.src_lists.get(path, ())

    def src_keep(self, path, key):
        if not self.cross:
            return True
        if key in self.fallible.get(path, ()):
            return True
        if path == ():
            return key in self.needed_top
        return key in self.tgt_keys.get(path, ())

    def tgt_keep(self, path, key):
        if not self.cross:
            return True
        return self.possible(path, key) or any(key in d for d in self.tgt_defaults.values())

    def src_list_keep(self, path, lst):
        if not self.cross:
            return True
        return lst in self.tgt_lists.get(path, ()) or (path == () and lst in self.needed_top)

    def tgt_list_possible(self, path, lst):
        if not self.cross:
            return True
        return lst in self.src_lists.get(path, ())


def parse_side(text):
    if ":" in text:
        name, kinds = text.split(":", 1)
        return name, [k for k in kinds.split(",") if k]
    return text, None


_INDEX = {}    # packs directory -> {format: (text, where)}
_MODELS = {}   # model directory -> Model


def load_pack(packs_dir, name):
    if packs_dir not in _INDEX:
        index = {}
        for d in sorted(os.listdir(packs_dir)):
            p = os.path.join(packs_dir, d, "pack.def")
            if not os.path.isfile(p):
                continue
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
            for line in text.split("\n"):
                t = line.split()
                if len(t) >= 2 and t[0] == "format":
                    index.setdefault(t[1], (text, "packs/%s/pack.def" % d))
                    break
        _INDEX[packs_dir] = index
    if name not in _INDEX[packs_dir]:
        refuse("unknown-format", "no pack under the packs directory declares `format %s`" % name)
    return Pack(*_INDEX[packs_dir][name])


def compile_plan(model_dir, packs_dir, src, dst, context, keep_names):
    if model_dir not in _MODELS:
        _MODELS[model_dir] = Model()
        _MODELS[model_dir].load_dir(model_dir)
    model = _MODELS[model_dir]
    c = Compiler(model, keep_names)
    view = View()
    sname, skinds = parse_side(src) if src else (None, None)
    dname, dkinds = parse_side(dst) if dst else (None, None)
    spack = load_pack(packs_dir, sname) if sname else None
    dpack = load_pack(packs_dir, dname) if dname else None
    same = sname is not None and sname == dname
    if same and skinds != dkinds:
        refuse("bad-arguments", "a same-format plan takes one kind list; give the same kinds on both sides")
    for k in context:
        if model.type_of(k) == T_LIST:
            refuse("bad-arguments", "context key `%s` is a list" % k)
    report = {"from": src, "to": dst, "context": list(context), "carried": [], "checked_not_carried": [],
              "dropped_source_keys": [], "derives": []}
    possible, needed = None, None
    if spack is not None and dpack is not None and not same:
        view.cross = True
        scope_keys(spack.body, skinds, (), view.src_keys, view.src_lists, {})
        scope_keys(dpack.body, dkinds, (), view.tgt_keys, view.tgt_lists, view.tgt_defaults)
        possible = set(view.src_keys.get((), ())) | set(view.src_lists.get((), ())) | set(context)
        needed = set(view.tgt_keys.get((), ()))
        for k in dpack.body["kinds"]:
            # an earlier kind left out still selects by its required keys
            needed.update(k["requires"])
        # A context key is filled before derivation (engine-spec, Order inside convert), so a
        # derive line whose target the caller supplies is never needed either.
        produced = set(view.src_keys.get((), ())) | set(view.src_lists.get((), ())) | set(context)
        kept = c.compile_derives(possible, needed, True, produced)
        view.possible_top, view.needed_top = possible, needed

        # keys whose decode can fail stay checked, so a bad message is refused as the reference refuses it
        def fallible(body, kinds, path):
            for lines, _, _ in body_parts(body, kinds):
                def see(l):
                    if l["t"] == "field":
                        for key, via in l["keys"]:
                            if l["xf"] in FALLIBLE or (
                                    via is not None and c.table_fallible(spack, via, l["yields"], model.type_of(key))):
                                view.fallible.setdefault(path, set()).add(key)
                    elif l["t"] in ("group", "gfix"):
                        fallible(l["body"], None, path + (l["list"],))
                walk_scope(lines, see)
        fallible(spack.body, skinds, ())
        # a conversion that can never select a kind of the target is refused here, not on the device
        tk = [k for k in dpack.body["kinds"] if dkinds is None or k["name"] in dkinds]
        missing = [[r for r in k["requires"] if r not in possible] for k in tk]
        if tk and all(missing):
            refuse("target-unreachable", "no kind of `%s` can be selected: %s. Supply them with --context or choose "
                   "another source kind" % (dname, "; ".join(
                       "kind `%s` requires %s, which the source does not give" % (k["name"], ", ".join(m))
                       for k, m in zip(tk, missing))))
        for k, m in zip(tk, missing):
            if m:
                c.notes.append("target kind `%s` is never selected: the source does not give %s" % (k["name"], ", ".join(m)))
    elif dpack is not None and spack is None:
        # encode-only: the caller may set any key the format reads
        keys, lists, defs = {}, {}, {}
        scope_keys(dpack.body, dkinds, (), keys, lists, defs)
        needed = set(keys.get((), ()))
        for k in dpack.body["kinds"]:
            needed.update(k["requires"])
        possible = set(model.types)
        kept = c.compile_derives(possible, needed, False)
    else:
        # decode-only, or one format both ways: the derivations its own keys and the context feed.
        # A same-format conversion derives only when the caller gives a context.
        keys, lists = {}, {}
        scope_keys(spack.body, skinds, (), keys, lists, {})
        possible = set(keys.get((), ())) | set(context)
        needed = None
        if same:
            needed = set(keys.get((), ()))
            for k in spack.body["kinds"]:
                needed.update(k["requires"])
        kept = c.compile_derives(possible, needed, same) if (context or not same) else []
    report["derives"] = ["%s = %s(%s)" % (t, f, ", ".join(a)) for t, f, a in kept]
    for k in context:
        c.key(k, K_CONTEXT | (K_LIVE if (not view.cross or k in needed) else 0))
    si = di = NONE16
    if same:
        si = di = c.compile_format(spack, skinds, "both", view)
    else:
        if spack is not None:
            si = c.compile_format(spack, skinds, "dec", view)
        if dpack is not None:
            di = c.compile_format(dpack, dkinds, "enc", view)
    carry = []
    if view.cross:
        def first_ops(fmt):
            seen = {}
            for i in range(fmt["first"], fmt["end"]):
                o = c.ops[i]
                if o["op"] in (OP_FIELD, OP_ALSO, OP_GROUP_SEQ, OP_GROUP_FIX) and o["key"] not in seen:
                    seen[o["key"]] = i
            return seen
        s_ops, d_ops = first_ops(c.formats[si]), first_ops(c.formats[di])
        derived = set(d[2] for d in c.derives)
        for kid, (ty, flags, name) in enumerate(c.keys):
            if kid in d_ops:
                how = (1 if kid in s_ops else 0) | (2 if flags & K_CONTEXT else 0) | (4 if kid in derived else 0)
                if how:
                    carry.append((kid, how, s_ops.get(kid, NONE32), d_ops[kid]))
                    report["carried"].append(name + ("" if how & 1 else " (context)" if how & 2 else " (derived)"))
            elif kid in s_ops and kid not in set(c.args) and name not in needed:
                report["checked_not_carried"].append(name)
        all_src = set()
        for keys in view.src_keys.values():
            all_src |= keys
        report["dropped_source_keys"] = sorted(k for k in all_src if k not in c.key_at)
    plan = {"src": si, "dst": di, "flags": 1 if same else 0, "carry": carry}
    blob, sizes = c.blob(plan)
    report.update({"sizes": sizes, "total": len(blob), "features": sorted(c.features), "notes": c.notes,
                   "keys": len(c.keys), "ops": len(c.ops), "max_depth": c.max_depth,
                   "key_ids": {k[2]: i for i, k in enumerate(c.keys)},
                   "context_ids": {k: c.key_at[k] for k in context}})
    return blob, report


def rust_source(blob, report, static):
    out = ["// Generated by tools/gen/packc.py. Do not edit; compile the plan again.",
           "// from: %s   to: %s" % (report["from"], report["to"]),
           "// gt-core features this plan needs: %s" % (", ".join(report["features"]) or "none"),
           "",
           "/// The compiled plan (embedded/FORMAT.md, version %d), %d bytes." % (VERSION, len(blob)),
           "pub static %s: [u8; %d] = [" % (static, len(blob))]
    for i in range(0, len(blob), 16):
        out.append("    " + " ".join("0x%02x," % b for b in blob[i:i + 16]))
    out.append("];")
    for name, kid in sorted(report["context_ids"].items(), key=lambda kv: kv[1]):
        ident = re.sub(r"[^A-Za-z0-9]", "_", name).upper()
        out.append("")
        out.append("/// Context key `%s`." % name)
        out.append("pub const KEY_%s: u16 = %d;" % (ident, kid))
    return "\n".join(out) + "\n"


def print_report(report, fh):
    w = lambda s="": fh.write(s + "\n")
    w("plan: %s -> %s" % (report["from"], report["to"]))
    w("bytes per table:")
    for name, size in report["sizes"].items():
        w("  %-12s %6d" % (name, size))
    w("  %-12s %6d" % ("total", report["total"]))
    w("ops: %d   keys: %d   nesting: %d" % (report["ops"], report["keys"], report["max_depth"]))
    w("gt-core features needed: %s" % (", ".join(report["features"]) or "none"))
    if report["carried"]:
        w("carried (%d): %s" % (len(report["carried"]), ", ".join(report["carried"])))
    if report["checked_not_carried"]:
        w("read and checked, not carried (%d): %s" % (len(report["checked_not_carried"]),
                                                      ", ".join(report["checked_not_carried"])))
    if report["dropped_source_keys"]:
        w("source keys not compiled (%d): %s" % (len(report["dropped_source_keys"]),
                                                 ", ".join(report["dropped_source_keys"])))
    if report["derives"]:
        w("derivations compiled (%d): %s" % (len(report["derives"]), "; ".join(report["derives"])))
    for n in report["notes"]:
        w("note: " + n)


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    ap = argparse.ArgumentParser(description="compile packs to the device engine's binary form")
    ap.add_argument("--from", dest="src", default=None, metavar="A[:kind,...]")
    ap.add_argument("--to", dest="dst", default=None, metavar="B[:kind,...]")
    ap.add_argument("--context", default="", metavar="key,key")
    ap.add_argument("--model", default=os.path.join(root, "model"))
    ap.add_argument("--packs", default=os.path.join(root, "packs"))
    ap.add_argument("--names", action="store_true", help="keep key and kind names (debug section)")
    ap.add_argument("--out-gtp", default=None)
    ap.add_argument("--out-rs", default=None)
    ap.add_argument("--static", default="PLAN")
    ap.add_argument("--report", default=None, help="write the size report as JSON")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--batch", default=None, metavar="JOBS.json",
                    help='compile many plans: a JSON list of {"from", "to", "context", "names", "out_gtp"}; '
                         'writes JOBS.json.out, a list of {"ok"} or {"refused"} in the same order')
    a = ap.parse_args(argv)
    if a.batch:
        with open(a.batch, encoding="utf-8") as fh:
            jobs = json.load(fh)
        results = []
        for job in jobs:
            try:
                blob, report = compile_plan(a.model, a.packs, job.get("from"), job.get("to"),
                                            job.get("context", []), job.get("names", False))
                with open(job["out_gtp"], "wb") as fh:
                    fh.write(blob)
                results.append({"ok": report["total"]})
            except Refused as e:
                results.append({"refused": str(e)})
        with open(a.batch + ".out", "w", encoding="utf-8") as fh:
            json.dump(results, fh)
        return 0
    if a.src is None and a.dst is None:
        ap.error("give --from, --to or both")
    context = [k for k in a.context.split(",") if k]
    try:
        blob, report = compile_plan(a.model, a.packs, a.src, a.dst, context, a.names)
    except Refused as e:
        sys.stderr.write("packc: refused: %s\n" % e)
        return 2
    if a.out_gtp:
        with open(a.out_gtp, "wb") as fh:
            fh.write(blob)
    if a.out_rs:
        with open(a.out_rs, "w", encoding="utf-8") as fh:
            fh.write(rust_source(blob, report, a.static))
    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1, sort_keys=True)
            fh.write("\n")
    if not a.quiet:
        print_report(report, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
