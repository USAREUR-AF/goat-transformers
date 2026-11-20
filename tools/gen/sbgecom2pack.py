#!/usr/bin/env python3
"""sbgecom2pack: the binary logs of SBG Systems sbgECom as a goat-transformers `bits` pack.

Reads   <src>/src/sbgEComIds.h            message classes and log ids (enums)
        <src>/src/logs/sbgEComLog.c       which parse function each (class, id) calls
        <src>/src/logs/sbgEComLog*.c      the parse functions (`...ReadFromStream`)
        <src>/src/logs/sbgEComLog*.h      array sizes of members a parse function reads
                                          as one buffer
        <src>/doc/binaryMessages.md       payload sizes (a cross-check) and evidence for the shared keys
        <src>/doc/commonDefs.md           evidence for the datum (pinned, not parsed)
        <src>/LICENSE.md
        tools/gen/sources/sbgecom-PROVENANCE.md (commit and SHA-256 of every file;
                                          written with --commit, checked otherwise)
Writes  <out>/model/sbgecom.def, <out>/packs/sbgecom/{pack.def,pack.md,PROVENANCE.md,vectors/}

A message of the pack is one sbgECom frame without its framing: the message id
byte, the message class byte, then the payload. The two id bytes are the kind's
`when`. The sync bytes, the length, the CRC and the end byte are the framer's.

The layout of a payload is the sequence of reads in its parse function. The
reader is strict and understands only these statements of a function body:

  - `pLogData-><path> = [(<type>)]sbgStreamBufferRead<T>(pStreamBuffer) [* <number>f];`
    one field; `<path>` is a member, `.member` and constant `[i]` indexes; a cast to a
    non-float type changes nothing; a float cast with a factor is a scaled field;
  - `sbgStreamBufferReadBuffer(pStreamBuffer, pLogData-><m>, sizeof(pLogData-><m>))`,
    alone or after `return`: the bytes of a member array whose size the matching
    header states;
  - `if ([shouldContinue &&] sbgStreamBufferGetSpace(pStreamBuffer) >= <n>|> 0) {...}
    [else {...}]` whose first branch holds only reads: those fields are `optional`
    (a later firmware appended them); the else branch sets defaults and is ignored;
  - declarations of locals, `assert(...)`, `shouldContinue = ...;`, and
    `return sbgStreamBufferGetLastError(pStreamBuffer);`.

Any other statement (a loop, a read into a local, a condition on a value, a call)
leaves the function, and every log that calls it, not built, with the statement
as the reason.

Python 3 standard library only. Vectors are written by a serializer in this file
from the read list; the script then loads the pack through gtcheck and decodes and
re-encodes every vector with its own small codec of the fixed `bits` layout.

Usage: sbgecom2pack.py --src DIR [--out DIR] [--check] [--commit SHA --ref REF]
"""
import argparse
import collections
import hashlib
import json
import math
import os
import re
import struct
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

FORMAT = "sbgecom"
MODULE = "sbgecom"
VERSION = "0.1.0"
REPO = "https://github.com/SBG-Systems/sbgECom"
PROV = "tools/gen/sources/sbgecom-PROVENANCE.md"
DATE_READ = "2026-11-20"
FIXED_FILES = ["LICENSE.md", "src/sbgEComIds.h", "src/logs/sbgEComLog.c", "doc/binaryMessages.md", "doc/commonDefs.md"]

READS = {   # sbgStreamBufferRead<T> -> (bits, transform, kind) kind: u, s, f
    "Uint8": (8, "uint", "u"), "Uint8LE": (8, "uint", "u"), "Int8": (8, "twos", "s"), "Int8LE": (8, "twos", "s"),
    "Uint16LE": (16, "uint", "u"), "Int16LE": (16, "twos", "s"), "Uint32LE": (32, "uint", "u"),
    "Int32LE": (32, "twos", "s"), "Uint64LE": (64, "uint", "u"), "Int64LE": (64, "twos", "s"),
    "FloatLE": (32, "f32", "f"), "DoubleLE": (64, "f64", "f"),
}
MAX_UNROLL = 64

# Shared keys. (parse function, path) -> (key, evidence). The track keys need
# `uses track`. The position is in the datum of the position aiding source (WGS 84
# with GNSS aiding); pack.md states it. BIND_POSITION False keeps it raw.
BIND_POSITION = True
BINDS = {
    ("sbgEComLogEkfNavReadFromStream", "velocity[0]"): (
        "track.vel_north_ms", "the struct comment and the log's table in doc/binaryMessages.md: element 0 of "
                              "the velocity is north, in metres per second, in the NED frame"),
    ("sbgEComLogEkfNavReadFromStream", "velocity[1]"): (
        "track.vel_east_ms", "the same: element 1 is east, in metres per second"),
    ("sbgEComLogGnssVelReadFromStream", "velocity[0]"): (
        "track.vel_north_ms", "the struct comment: the GNSS velocity is north, east, down in metres per "
                              "second; element 0 is north"),
    ("sbgEComLogGnssVelReadFromStream", "velocity[1]"): (
        "track.vel_east_ms", "the same: element 1 is east"),
}
POSITION_BINDS = {
    ("sbgEComLogEkfNavReadFromStream", "position[0]"): ("lat", "latitude in degrees, positive north"),
    ("sbgEComLogEkfNavReadFromStream", "position[1]"): ("lon", "longitude in degrees, positive east"),
    ("sbgEComLogGnssPosReadFromStream", "latitude"): ("lat", "latitude in degrees, positive north"),
    ("sbgEComLogGnssPosReadFromStream", "longitude"): ("lon", "longitude in degrees, positive east"),
}
# A second line on the same bits, after the raw key's line: (key, transform, evidence)
ALSO = {
    ("sbgEComLogEkfNavReadFromStream", "velocity[2]"): (
        "track.vel_up_ms", "f32scale:-1", "element 2 of the NED velocity is down, in metres per second; up is its "
                                          "negation"),
    ("sbgEComLogGnssVelReadFromStream", "velocity[2]"): (
        "track.vel_up_ms", "f32scale:-1", "element 2 is down; up is its negation"),
}
# hae = altitude above mean sea level + undulation, as the struct comments and the
# EKF navigation log's note state: (parse function) -> (altitude path, undulation path)
HAE = {
    "sbgEComLogEkfNavReadFromStream": ("position[2]", "undulation"),
    "sbgEComLogGnssPosReadFromStream": ("altitude", "undulation"),
}


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


class NotBuilt(Exception):
    pass


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read_text(src, rel):
    with open(os.path.join(src, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: " " * 0 + "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def snake(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", s.lower())).strip("_")


# --------------------------------------------------------------------------
# Ids and dispatch
# --------------------------------------------------------------------------

def enum_values(text, name):
    m = re.search(r"\}\s*%s\s*;" % re.escape(name), text)
    if not m:
        fail("sbgEComIds.h: no enum %s" % name)
    start = text.rfind("{", 0, m.start())
    if not re.search(r"typedef\s+enum\s+\w*\s*$", text[:start]):
        fail("sbgEComIds.h: %s is not a typedef enum" % name)
    out, prev = collections.OrderedDict(), -1
    for item in text[start + 1:m.start()].split(","):
        item = item.strip()
        if not item:
            continue
        mm = re.fullmatch(r"(\w+)\s*(?:=\s*(0x[0-9A-Fa-f]+|\d+))?", item)
        if not mm:
            fail("sbgEComIds.h: enum %s item `%s`" % (name, item))
        prev = int(mm.group(2), 0) if mm.group(2) else prev + 1
        out[mm.group(1)] = prev
    return out


def dispatch(text):
    """[(class constant, id constant, parse function)] from sbgEComLogParse."""
    m = re.search(r"SbgErrorCode\s+sbgEComLogParse\s*\(.*?\)\s*\{(.*?)\n\}", text, re.S)
    if not m:
        fail("sbgEComLog.c: no sbgEComLogParse")
    out, cls, pending = [], None, []
    for line in m.group(1).split("\n"):
        s = line.strip()
        c = re.search(r"msgClass\s*==\s*(SBG_ECOM_CLASS_\w+)", s)
        if c:
            cls = c.group(1)
            continue
        c = re.match(r"case\s+(\w+)\s*:", s)
        if c:
            pending.append(c.group(1))
            continue
        c = re.match(r"errorCode\s*=\s*(\w+ReadFromStream)\s*\(", s)
        if c:
            if not pending or cls is None:
                fail("sbgEComLog.c: a parse call with no case: %s" % s)
            out += [(cls, p, c.group(1)) for p in pending]
            pending = []
            continue
        if s.startswith("break"):
            pending = []
    if not out:
        fail("sbgEComLog.c: no dispatch found")
    return out


# --------------------------------------------------------------------------
# Parse functions
# --------------------------------------------------------------------------

Read = collections.namedtuple("Read", "path bits transform kind optional factor")
Buffer = collections.namedtuple("Buffer", "path nbytes optional")


def function_body(text, name):
    m = re.search(r"\bSbgErrorCode\s+%s\s*\(([^)]*)\)\s*\{" % re.escape(name), text)
    if not m:
        return None, None
    i, depth = m.end(), 1
    while depth:
        if i >= len(text):
            fail("%s: no closing brace" % name)
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return m.group(1), text[m.end():i - 1]


def statements(body):
    """Top-level statements; an `if`/`else` with its braces is one item
    ("if", condition, then-statements, else-statements)."""
    out, i, n = [], 0, len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        m = re.match(r"if\s*\(", body[i:])
        if m:
            j, depth = i + m.end(), 1
            while depth:
                depth += {"(": 1, ")": -1}.get(body[j], 0)
                j += 1
            cond = body[i + m.end():j - 1]
            then, j = block(body, j)
            els = []
            k = j
            while k < n and body[k] in " \t\r\n":
                k += 1
            if body.startswith("else", k):
                k += 4
                while body[k] in " \t\r\n":
                    k += 1
                if body.startswith("if", k):
                    raise NotBuilt("an `else if` chain")
                els, j = block(body, k)
            out.append(("if", " ".join(cond.split()), statements(then), statements(els)))
            i = j
            continue
        if body[i] == "{":
            raise NotBuilt("a bare block")
        if re.match(r"(for|while|do|switch)\b", body[i:]):
            raise NotBuilt("a `%s` statement" % re.match(r"\w+", body[i:]).group(0))
        j = body.find(";", i)
        if j < 0:
            raise NotBuilt("a statement without `;`: %s" % " ".join(body[i:].split())[:60])
        out.append(" ".join(body[i:j].split()))
        i = j + 1
    return out


def block(body, i):
    while body[i] in " \t\r\n":
        i += 1
    if body[i] != "{":
        raise NotBuilt("an `if` without braces")
    j, depth = i + 1, 1
    while depth:
        depth += {"{": 1, "}": -1}.get(body[j], 0)
        j += 1
    return body[i + 1:j - 1], j


LOCAL = re.compile(r"(?:const\s+)?(?:bool|u?int(?:8|16|32|64)_t|size_t|float|double|SbgErrorCode|uint)\s+\w+(?:\s*=\s*[^;]+)?")
READ = re.compile(r"pLogData->([A-Za-z_]\w*(?:\[\d+\]|\.\w+)*)\s*=\s*(?:\((\w+)\)\s*)?sbgStreamBufferRead(\w+)\(\s*pStreamBuffer\s*\)"
                  r"(?:\s*\*\s*([0-9]*\.?[0-9]+(?:[eE]-?\d+)?)f?)?")
BUF = re.compile(r"(?:return\s+)?sbgStreamBufferReadBuffer\(\s*pStreamBuffer\s*,\s*pLogData->(\w+)\s*,\s*"
                 r"sizeof\(\s*pLogData->(\w+)\s*\)\s*\)")
SPACE = re.compile(r"(?:shouldContinue\s*&&\s*)?\(?\s*sbgStreamBufferGetSpace\(\s*pStreamBuffer\s*\)\s*(?:>=\s*[\w()*\->. ]+|>\s*0)\s*\)?")


def reads_of(stmts, fn, sizes, optional=False):
    out = []
    for st in stmts:
        if isinstance(st, tuple):
            _, cond, then, els = st
            if optional or not SPACE.fullmatch(cond):
                raise NotBuilt("a condition `%s`" % cond)
            got = reads_of(then, fn, sizes, optional=True)
            if not got:
                raise NotBuilt("a condition `%s` that reads nothing" % cond)
            if any("sbgStreamBufferRead" in s for s in flatten(els)):
                raise NotBuilt("reads in an else branch")
            out += got
            continue
        if st.startswith("assert(") or re.fullmatch(r"shouldContinue\s*=\s*(true|false)", st) \
                or st == "return sbgStreamBufferGetLastError(pStreamBuffer)" or LOCAL.fullmatch(st):
            continue
        m = READ.fullmatch(st)
        if m:
            path, cast, t, factor = m.groups()
            if t not in READS:
                raise NotBuilt("a read of type %s" % t)
            bits, tr, kind = READS[t]
            if factor is not None:
                if cast not in ("float", "double") or kind == "f":
                    raise NotBuilt("a scaled read `%s`" % st)
            elif cast in ("float", "double") and kind != "f":
                raise NotBuilt("an integer read cast to %s" % cast)
            out.append(Read(path, bits, tr, kind, optional, factor))
            continue
        m = BUF.fullmatch(st)
        if m and m.group(1) == m.group(2):
            if m.group(1) not in sizes:
                raise NotBuilt("a buffer `%s` whose size the header does not state" % m.group(1))
            out.append(Buffer(m.group(1), sizes[m.group(1)], optional))
            continue
        if re.match(r"\w+\s*=\s*(\(\w+\)\s*)?sbgStreamBufferRead", st):
            raise NotBuilt("a read into a local variable (`%s`)" % st.split("=")[0].strip())
        if "sbgStreamBufferReadBuffer" in st and "GetSpace" in st:
            raise NotBuilt("a buffer that runs to the end of the payload")
        raise NotBuilt("control flow the reader does not take, from `%s`" % (st if len(st) < 90 else st[:87] + "..."))
    seen_opt = False
    for r in out:
        if r.optional:
            seen_opt = True
        elif seen_opt:
            raise NotBuilt("a field read after an optional one, so its place depends on the payload length")
    return out


def flatten(stmts):
    for st in stmts:
        if isinstance(st, tuple):
            yield st[1]
            yield from flatten(st[2])
            yield from flatten(st[3])
        else:
            yield st


def array_sizes(htext, consts):
    """{member: bytes} of the uint8_t (or char) arrays of the structs of a header."""
    out = {}
    for m in re.finditer(r"\b(?:uint8_t|char|int8_t)\s+(\w+)\s*\[\s*(\w+)\s*\]\s*;", htext):
        n = m.group(2)
        v = int(n, 0) if re.fullmatch(r"0x[0-9A-Fa-f]+|\d+", n) else consts.get(n)
        if v is not None:
            out[m.group(1)] = v
    return out


def header_consts(htext):
    out = {}
    for m in re.finditer(r"^\s*#define\s+(\w+)\s+\(?\s*(0x[0-9A-Fa-f]+|\d+)u?\s*\)?\s*$", htext, re.M):
        out[m.group(1)] = int(m.group(2), 0)
    return out


# --------------------------------------------------------------------------
# Lines
# --------------------------------------------------------------------------

Line = collections.namedtuple("Line", "key bit bits transform keytype path optional also")
Line.__new__.__defaults__ = (False,)


def fn_short(fn):
    return snake(re.sub(r"^sbgEComLog|ReadFromStream$", "", fn))


def lines_of(fn, reads):
    out, bit = [], 16
    for r in reads:
        if isinstance(r, Buffer):
            if r.nbytes > MAX_UNROLL:
                raise NotBuilt("a buffer of %d bytes" % r.nbytes)
            for i in range(r.nbytes):
                out.append(Line("%s.%s_%s_%d" % (MODULE, fn_short(fn), snake(r.path), i), bit, 8, "uint", "int",
                                "%s[%d]" % (r.path, i), r.optional))
                bit += 8
            continue
        tr, kt = r.transform, ("float" if r.kind == "f" else "int")
        if r.factor is not None:
            tr, kt = ("sscale:%s" if r.kind == "s" else "uscale:%s") % format(Decimal(r.factor).normalize(), "f"), "float"
        key = "%s.%s_%s" % (MODULE, fn_short(fn), snake(r.path.replace("[", "_").replace("]", "").replace(".", "_")))
        b = BINDS.get((fn, r.path))
        if not b and BIND_POSITION:
            b = POSITION_BINDS.get((fn, r.path))
        if b:
            key = b[0]
        out.append(Line(key, bit, r.bits, tr, kt, r.path, r.optional))
        a = ALSO.get((fn, r.path))
        if a:
            if r.transform != "f32" or r.factor is not None:
                fail("%s %s: an ALSO line on a field that is not a plain float32" % (fn, r.path))
            out.append(Line(a[0], bit, r.bits, a[1], "float", r.path, r.optional, True))
        bit += r.bits
    return out, bit


# --------------------------------------------------------------------------
# Serializer and codec (fixed `bits` layout, lsb, one byte words)
# --------------------------------------------------------------------------

def sample(line, n):
    if line.transform == "f32":
        return (((n * 37) % 2001 - 1000) or 1) / 8.0       # never 0: -0 and 0 differ on the wire
    if line.transform == "f64":
        return (((n * 7919) % 200001 - 100000) or 1) / 64.0
    if line.transform.startswith(("sscale", "uscale")):
        raw = (n * 40503 + 7) % (1 << (line.bits - 1))
        return raw
    if line.transform == "twos":
        span = 1 << line.bits
        return (n * 40503 + 7) % span - span // 2
    return (n * 2654435761 + 12345) % (1 << line.bits) if line.bits < 64 else n * 1000003 + 1700000000


def raw_of(line, v):
    if line.transform == "f32":
        return int.from_bytes(struct.pack("<f", v), "little")
    if line.transform == "f64":
        return int.from_bytes(struct.pack("<d", v), "little")
    return v & ((1 << line.bits) - 1)


def model_value(line, raw):
    """The model value of a raw sample, as vector text."""
    if line.transform in ("f32", "f64") or line.transform.startswith("f32scale:"):
        v = struct.unpack("<d" if line.transform == "f64" else "<f", raw.to_bytes(line.bits // 8, "little"))[0]
        if line.transform.startswith("f32scale:"):
            v *= float(line.transform.split(":")[1])
        return fmt_float(v)
    if line.transform.startswith(("sscale", "uscale")):
        signed = raw - (1 << line.bits) if line.transform.startswith("s") and raw >> (line.bits - 1) else raw
        return fmt_float(float(Decimal(signed) * Decimal(line.transform.split(":")[1])))
    if line.transform == "twos":
        return str(raw - (1 << line.bits) if raw >> (line.bits - 1) else raw)
    return str(raw)


def fmt_float(x):
    if x == 0:
        return "0"
    s = format(Decimal(repr(float(x))), "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def message(kind_id, cls, lines, total_bits, salt, upto=None, override=None):
    acc = kind_id | (cls << 8)
    raws = {}
    for i, ln in enumerate(lines):
        if upto is not None and ln.bit >= upto:
            break
        if ln.also:
            continue
        v = override[ln.path] if override and ln.path in override else sample(ln, salt + 7 * i + 1)
        raw = raw_of(ln, v)
        raws[ln.path] = raw
        acc |= raw << ln.bit
    end = total_bits if upto is None else upto
    return acc.to_bytes(end // 8, "little"), raws


class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


def read_pack(text, module_texts=()):
    """The pack's kinds, and the `derive` lines of the modules in the order given
    (engine-spec 0.16: modules in byte order of name, lines in order)."""
    pack = {"kinds": collections.OrderedDict(), "derive": []}
    for module_text in module_texts:
        for line in module_text.split("\n"):
            t = gtcheck.tokenize(line)
            if t and t[0] == "derive":
                pack["derive"].append((t[1], t[2], t[3:]))
    cur = None
    for line in text.split("\n"):
        t = gtcheck.tokenize(line)
        if not t:
            continue
        if t[0] == "kind":
            cur = {"when": [], "fields": []}
            pack["kinds"][t[1]] = cur
        elif t[0] == "when":
            w, p, n = (int(x) for x in t[1].split(":"))
            cur["when"].append((w * 8 + p, n, int(t[2])))
        elif t[0] == "field":
            w, p, n = (int(x) for x in t[2].split(":"))
            cur["fields"].append((t[1], w * 8 + p, n, t[3], "optional" in t[4:]))
        elif t[0] == "requires":
            cur["requires"] = t[1:]
    return pack


def derive(pack, ent):
    """The modules' `derive` lines, to the decoded entity (engine-spec 0.16); the
    functions this pack's keys can reach: add, hypot and bearing."""
    for _ in range(8):
        changed = False
        for target, fn, argv in pack["derive"]:
            if target in ent or not all(a in ent for a in argv):
                continue
            x = [float(ent[a]) for a in argv]
            if fn == "add":
                v = sum(x)
            elif fn == "hypot":
                v = math.sqrt(x[0] * x[0] + x[1] * x[1])
            elif fn == "bearing":
                if x[0] == 0 and x[1] == 0:
                    continue
                v = math.degrees(math.atan2(x[0], x[1])) % 360.0
            else:
                fail("derive function %s reached, not in this codec" % fn)
            if math.isfinite(v):
                ent[target] = v
                changed = True
        if not changed:
            break
    return ent


def decode(pack, data):
    whole, nbits = int.from_bytes(data, "little"), len(data) * 8
    for name, k in pack["kinds"].items():
        if all(b + n <= nbits and (whole >> b) & ((1 << n) - 1) == v for b, n, v in k["when"]):
            need = max([b + n for b, n, _ in k["when"]] + [b + n for _, b, n, _, opt in k["fields"] if not opt])
            if nbits < need:
                raise Fail("malformed-wire")
            ent = {}
            for key, b, n, tr, opt in k["fields"]:
                if b + n > nbits:
                    continue
                raw = (whole >> b) & ((1 << n) - 1)
                if tr in ("f32", "f64") or tr.startswith("f32scale:"):
                    v = struct.unpack("<d" if tr == "f64" else "<f", raw.to_bytes(n // 8, "little"))[0]
                    if math.isnan(v) or math.isinf(v):
                        raise Fail("transform-decode")
                    if tr.startswith("f32scale:"):
                        v = v * float(tr.split(":")[1])
                elif tr == "twos":
                    v = raw - (1 << n) if raw >> (n - 1) else raw
                elif tr.startswith(("sscale", "uscale")):
                    s = raw - (1 << n) if tr.startswith("s") and raw >> (n - 1) else raw
                    v = float(Decimal(s) * Decimal(tr.split(":")[1]))
                else:
                    v = raw
                ent[key] = v
            return name, ent
    raise Fail("no-kind")


def encode(pack, name, ent):
    k = pack["kinds"][name]
    acc, end = 0, 0
    for key, b, n, tr, opt in k["fields"]:
        end = max(end, b + n)
        if key not in ent:
            continue
        v = ent[key]
        if tr in ("f32", "f64"):
            raw = int.from_bytes(struct.pack("<f" if tr == "f32" else "<d", v), "little")
        elif tr.startswith("f32scale:"):
            raw = int.from_bytes(struct.pack("<f", v / float(tr.split(":")[1])), "little")
        elif tr.startswith(("sscale", "uscale")):
            q = Decimal(repr(v)) / Decimal(tr.split(":")[1])
            raw = int(q.to_integral_value(rounding="ROUND_HALF_UP")) & ((1 << n) - 1)
        else:
            raw = int(v) & ((1 << n) - 1)
        acc |= raw << b
    for b, n, v in k["when"]:
        end = max(end, b + n)
        acc = (acc & ~(((1 << n) - 1) << b)) | (v << b)
    return acc.to_bytes((end + 7) // 8, "little")


def geojson(ent):
    if "lat" in ent and "lon" in ent:
        c = [ent["lon"], ent["lat"]] + ([ent["hae"]] if "hae" in ent else [])
        props = ",".join('"%s":%s' % (k, fmt_float(ent[k])) for k in ("course", "speed_ms") if k in ent)
        return '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s]},"properties":{%s}}' % (
            ",".join(fmt_float(x) for x in c), props)
    return '{"type":"Feature","geometry":null,"properties":{}}'


def check_vector(pack, vec, where):
    try:
        if vec["from"] == "geojson":
            c = json.loads(vec["input"])["geometry"]["coordinates"]
            ent = {"lon": float(c[0]), "lat": float(c[1])}
            if len(c) > 2:
                ent["hae"] = float(c[2])
            name = next((n for n, k in pack["kinds"].items() if k.get("requires") and
                         all(r in ent for r in k["requires"])), None)
            if name is None:
                raise Fail("no-kind")
            out = encode(pack, name, ent).hex()
        else:
            name, ent = decode(pack, bytes.fromhex(vec["input"]))
            derive(pack, ent)
            out = encode(pack, name, ent).hex() if vec["to"] == FORMAT else geojson(ent)
        for k, want in vec.get("model", {}).items():
            got = name if k == "@kind" else ent.get(k)
            ok = abs(got - float(want)) <= 1e-9 * max(1.0, abs(float(want))) if isinstance(got, float) else str(got) == want
            if not ok:
                fail("%s: model %s = %r, want %r" % (where, k, got, want))
    except Fail as e:
        if vec.get("expect_error") == e.kind:
            return
        fail("%s: %s" % (where, e.kind))
    if "expect_error" in vec:
        fail("%s: converted, want %s" % (where, vec["expect_error"]))
    if out != vec["expect"]:
        fail("%s:\n got    %s\n expect %s" % (where, out, vec["expect"]))


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def vec(name, src, dst, inp, expect=None, model=None, error=None, source=None):
    v = collections.OrderedDict([("name", name), ("from", src), ("to", dst)])
    if source:
        v["source"] = source
    v["input"] = inp
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    return v


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def log_files(src):
    d = os.path.join(src, "src", "logs")
    names = sorted(f for f in os.listdir(d) if re.fullmatch(r"sbgEComLog\w*\.[ch]", f))
    return ["src/logs/" + f for f in names if f not in ("sbgEComLog.c",)]


def doc_sizes(doc):
    """{heading anchor: payload bytes} for the logs doc/binaryMessages.md gives a fixed size."""
    out, heads = {}, list(re.finditer(r"^### .*\{#(SBG_ECOM_LOG_\w+)\}\s*$", doc, re.M))
    for i, h in enumerate(heads):
        part = doc[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(doc)]
        m = re.search(r"\*\*Payload Size:\*\*\s*(\d+) bytes\s*$", part, re.M)
        if m:
            out[h.group(1)] = int(m.group(1))
    return out


def doc_size_of(sizes, idname):
    if idname in sizes:
        return sizes[idname]
    hits = [v for a, v in sizes.items() if re.fullmatch(re.sub(r"X+(?=_|$)", r"\\w+", a), idname)]
    return hits[0] if len(hits) == 1 else None


def build(args, out):
    files = FIXED_FILES + log_files(args.src)
    if args.commit:
        out.write(PROV, sources_provenance(args.commit, args.ref, files, args.src))
    text = out.read(PROV)
    commit = re.search(r"^\| Commit \| `([0-9a-f]{40})` \|$", text, re.M).group(1)
    ref = re.search(r"^\| Ref \| `([^`]+)` \|$", text, re.M).group(1)
    shas = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in files:
        if shas.get(rel) != sha256_file(os.path.join(args.src, *rel.split("/"))):
            fail("%s: SHA-256 is not the one in %s" % (rel, PROV))
    if set(shas) != set(files):
        fail("%s lists other files than the generator reads" % PROV)
    ids_text = strip_comments(read_text(args.src, "src/sbgEComIds.h"))
    classes = enum_values(ids_text, "SbgEComClass")
    ids = {"SBG_ECOM_CLASS_LOG_ECOM_0": enum_values(ids_text, "SbgEComLog"),
           "SBG_ECOM_CLASS_LOG_ECOM_1": enum_values(ids_text, "SbgEComLog1")}
    calls = dispatch(strip_comments(read_text(args.src, "src/logs/sbgEComLog.c")))
    ctext = {rel: strip_comments(read_text(args.src, rel)) for rel in files if rel.endswith(".c") and "/logs/" in rel}
    sizes = {}
    for rel in files:
        if rel.endswith(".h") and "/logs/" in rel:
            h = strip_comments(read_text(args.src, rel))
            sizes.update(array_sizes(h, header_consts(h)))
    plans, notbuilt = collections.OrderedDict(), collections.OrderedDict()
    for fn in sorted({c for _, _, c in calls}):
        body = None
        for rel, t in ctext.items():
            params, body = function_body(t, fn)
            if body is not None:
                break
        if body is None:
            fail("no definition of %s" % fn)
        try:
            reads = reads_of(statements(body), fn, sizes)
            plans[fn] = lines_of(fn, reads)
        except NotBuilt as e:
            notbuilt[fn] = str(e)
    kinds, skipped = [], []
    for cls, idname, fn in calls:
        if cls not in ids or idname not in ids[cls]:
            fail("%s: id %s is not in the enum of its class" % (fn, idname))
        name = idname.replace("SBG_ECOM_LOG_", "").lower()
        entry = (name, idname, ids[cls][idname], cls, classes[cls], fn)
        (kinds if fn in plans else skipped).append(entry)
    kinds.sort(key=lambda e: (e[4], e[2]))
    # cross-check: the payload size of each kind against the documentation's table, where it gives one
    dsz = doc_sizes(read_text(args.src, "doc/binaryMessages.md"))
    args.doc_checked = 0
    for name, idname, idv, cls, clsv, fn in kinds:
        want = doc_size_of(dsz, idname)
        if want is not None:
            got = plans[fn][1] // 8 - 2
            if got != want:
                fail("%s: the reads of %s give %d payload bytes, doc/binaryMessages.md says %d" % (idname, fn, got, want))
            args.doc_checked += 1
    skipped.sort(key=lambda e: (e[4], e[2]))
    # module
    decls = collections.OrderedDict()
    for fn, (lines, _) in plans.items():
        for ln in lines:
            if ln.key.startswith(MODULE + "."):
                decls[ln.key[len(MODULE) + 1:]] = (ln.keytype, "%s: %s" % (fn_short(fn), ln.path))
    mod = ["# The sbgecom module: raw keys of the sbgecom format, one per field a parse function of",
           "# sbgECom reads. Generated by tools/gen/sbgecom2pack.py; do not edit by hand.",
           "module        %s" % MODULE, "version       %s" % VERSION, "distribution  public", source_line(commit, ref)]
    w = max(len(k) for k in decls)
    for k, (t, d) in decls.items():
        mod.append('key  %-*s  %-6s  -  "%s"' % (w, k, t, d))
    if BIND_POSITION:
        for fn, (alt, und) in sorted(HAE.items()):
            if fn not in plans:
                continue
            by = {ln.path: ln.key for ln in plans[fn][0] if not ln.also}
            if alt in by and und in by:
                mod.append("derive  hae  add  %s  %s" % (by[alt], by[und]))
    out.write("model/%s.def" % MODULE, "\n".join(mod) + "\n")
    # pack
    uses_track = any(ln.key.startswith("track.") for lines, _ in plans.values() for ln in lines)
    p = ["# sbgECom binary logs: the message id and class bytes, then the payload.",
         "# Generated by tools/gen/sbgecom2pack.py; do not edit by hand.",
         "format        %s" % FORMAT, "version       %s" % VERSION, "distribution  public", source_line(commit, ref),
         "uses          %s" % MODULE] + (["uses          track"] if uses_track else []) + [
         "wire          bits", "bit_order     lsb", "word_bytes    1"]
    for name, idname, idv, cls, clsv, fn in kinds:
        lines, _ = plans[fn]
        p += ["", "kind      %s" % name, "when      0:0:8  %d" % idv, "when      0:8:8  %d" % clsv]
        keys = {ln.key for ln in lines}
        first = next((ln.key for ln in lines if not ln.optional), None)
        if "lat" in keys and "lon" in keys:
            p.append("requires  lat lon")
        elif first:
            p.append("requires  %s" % first)
        for ln in lines:
            p.append("field     %s  0:%d:%d  %s%s" % (ln.key, ln.bit, ln.bits, ln.transform, "  optional" if ln.optional else ""))
    out.write("packs/%s/pack.def" % FORMAT, "\n".join(p) + "\n")
    # vectors
    vs = []
    for n, (name, idname, idv, cls, clsv, fn) in enumerate(kinds):
        lines, total = plans[fn]
        data, raws = message(idv, clsv, lines, total, 1000 * (n + 1))
        model = collections.OrderedDict([("@kind", name)])
        for ln in lines[:4]:
            model[ln.key] = model_value(ln, raws[ln.path])
        vs.append(("gen-rt-%s.json" % name.replace("_", "-"), vec(
            "rt-" + name, FORMAT, FORMAT, data.hex(), data.hex(), model,
            source="tools/gen/sbgecom2pack.py: id %d, class %d, then the fields %s reads, with values chosen "
                   "by the generator, little-endian at their offsets" % (idv, clsv, fn))))
        opt = [ln for ln in lines if ln.optional]
        if opt and fn not in {k[5] for k in kinds[:n]}:
            cut = opt[0].bit
            short, _ = message(idv, clsv, lines, total, 1000 * (n + 1), upto=cut)
            vs.append(("gen-rt-%s-before-optional.json" % name.replace("_", "-"), vec(
                "rt-%s-before-optional" % name, FORMAT, FORMAT, short.hex(), short.hex() + "00" * ((total - cut) // 8),
                collections.OrderedDict([("@kind", name)]),
                source="a message of an earlier firmware that ends before the optional fields: they decode "
                       "as absent, and encode writes zero bits for them (engine-spec 0.6, `optional`; "
                       "encode is unchanged)")))
    # the position: EKF_NAV to geojson (hae derived from altitude and undulation), and geojson to
    # the first kind whose requires (lat lon) hold
    xv = []
    nav = next((k for k in kinds if k[5] == "sbgEComLogEkfNavReadFromStream"), None)
    if BIND_POSITION and nav:
        name, idname, idv, cls, clsv, fn = nav
        lines, total = plans[fn]
        by = {ln.path: ln for ln in lines if not ln.also}
        point = {"position[0]": 47.3977419, "position[1]": 8.5455938, "position[2]": 488.25, "undulation": 47.5,
                 "velocity[0]": 5.0, "velocity[1]": 0.0}
        data, raws = message(idv, clsv, lines, total, 4242, override=point)
        hae = point["position[2]"] + point["undulation"]
        vs.append(("gen-x-%s-to-geojson.json" % name.replace("_", "-"), vec(
            "x-%s-to-geojson" % name, FORMAT, "geojson", data.hex(),
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},'
            '"properties":{"course":0,"speed_ms":5}}' % (
                fmt_float(point["position[1]"]), fmt_float(point["position[0]"]), fmt_float(hae)),
            collections.OrderedDict([("@kind", name), ("lat", fmt_float(point["position[0]"])),
                                     ("lon", fmt_float(point["position[1]"]))]),
            source="latitude and longitude in degrees bind lat and lon; hae is altitude above mean sea level "
                   "plus undulation (the module's derive add, engine-spec 0.16); the velocity is 5 m/s north and "
                   "0 east, so track's derives give course 0 (bearing) and speed_ms 5 (hypot); geojson writes "
                   "[lon, lat, alt] (RFC 7946, engine-spec 0.1.1 rulings 3 to 5)")))
        first = next(k for k in kinds if {"lat", "lon"} <= {ln.key for ln in plans[k[5]][0]})
        fname, _, fid, _, fcls, ffn = first
        flines, ftotal = plans[ffn]
        acc = fid | (fcls << 8)
        for ln in flines:
            if ln.key in ("lat", "lon"):
                acc |= raw_of(ln, {"lat": 47.25, "lon": 8.5}[ln.key]) << ln.bit
        gv = vec("geojson-to-%s-%s" % (FORMAT, fname), "geojson", FORMAT,
                 '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5,47.25,410.5]},'
                 '"properties":{"callsign":"UAV1"},"id":"u-1"}', acc.to_bytes(ftotal // 8, "little").hex(),
                 collections.OrderedDict([("lat", "47.25"), ("lon", "8.5"), ("hae", "410.5")]),
                 source="tools/gen/sbgecom2pack.py: the kind is the first whose requires hold (lat lon); "
                        "hae has no field (the pack carries altitude above mean sea level, and a derive runs "
                        "one way); every other payload byte is zero")
        xv.append(("packs/geojson/vectors/gen-geojson-to-%s-%s.json" % (FORMAT, fname.replace("_", "-")), gv))
    name, idname, idv, cls, clsv, fn = kinds[0]
    lines, total = plans[fn]
    need = max(ln.bit + ln.bits for ln in lines if not ln.optional)
    data, _ = message(idv, clsv, lines, total, 7)
    vs.append(("gen-err-short.json", vec("err-short", FORMAT, FORMAT, data[:need // 8 - 1].hex(), error="malformed-wire",
                                         source="one byte short of the fields of %s that are not optional" % name)))
    used = {(k[2], k[4]) for k in kinds}
    other = next(i for i in range(256) if (i, 0) not in used)
    vs.append(("gen-err-other-id.json", vec("err-other-id", FORMAT, FORMAT, bytes([other, 0, 0, 0]).hex(),
                                            error="no-kind", source="id %d of class 0 is not a kind of this pack" % other)))
    rel = "packs/%s/vectors" % FORMAT
    for f in out.listdir(rel):
        if f.startswith("gen-") and f not in {n for n, _ in vs}:
            out.remove(rel + "/" + f)
    for f, v in vs:
        out.write(rel + "/" + f, dump(v))
    for path, v in xv:
        out.write(path, dump(v))
    out.write("packs/%s/pack.md" % FORMAT, pack_md(kinds, skipped, notbuilt, plans, len(vs), commit, ref))
    out.write("packs/%s/PROVENANCE.md" % FORMAT, provenance(commit, ref, files, shas, args.src))
    # check
    model = gtcheck.Model()
    for mrel in ("model/core.def", "model/track.def"):
        model.add(out.read(mrel) if args.model_from_out else read_text(args.root, mrel), mrel)
    model.add(out.read("model/%s.def" % MODULE), "model/%s.def" % MODULE)
    try:
        gtcheck.load_pack(out.read("packs/%s/pack.def" % FORMAT), model, label="packs/%s/pack.def" % FORMAT)
    except gtcheck.CheckError as e:
        fail(str(e))
    codec = read_pack(out.read("packs/%s/pack.def" % FORMAT),
                      [out.read(m) for m in ("model/core.def", "model/%s.def" % MODULE, "model/track.def")])
    for f, _ in vs:
        check_vector(codec, json.loads(out.read(rel + "/" + f)), rel + "/" + f)
    for path, _ in xv:
        check_vector(codec, json.loads(out.read(path)), path)
    return kinds, skipped, notbuilt, len(decls), len(vs) + len(xv)


def source_line(commit, ref):
    return ('source        "sbgECom binary logs: the parse functions of src/logs and the ids of src/sbgEComIds.h, '
            '%s at %s, commit %s; field order, types and sizes only; MIT License"' % (REPO, ref, commit))


def pack_md(kinds, skipped, notbuilt, plans, nvec, commit, ref):
    a = ["# sbgecom", "",
         "SBG Systems sbgECom binary output logs (classes 0 and 1), from %s at %s, commit" % (REPO, ref),
         "`%s`. Generated by `tools/gen/sbgecom2pack.py`; do not edit by hand." % commit, "",
         "## Message convention", "",
         "A message of this format is one sbgECom frame without its framing: the message id byte, the",
         "message class byte, then the payload. The two bytes are the kind's `when` lines. The two sync",
         "bytes before them, the 16-bit payload length after them, and the CRC-16 and end byte after the",
         "payload are the framer's: `src/protocol/sbgEComProtocol.c` checks and strips them, and an",
         "extended (multi-page) frame, whose class byte has its top bit set, is reassembled there before",
         "a log is parsed. The payload is little-endian: the parse functions read every field with the",
         "`...LE` readers of the stream buffer.", "",
         "The layout of each payload is the order, type and size of the reads in its parse function",
         "(`src/logs/*.c`). Fields that a later firmware appended, and that the parse function reads only",
         "when the payload holds them, are `optional`: an earlier, shorter payload decodes with them",
         "absent. Encode writes the whole layout (zero bits for an absent optional field).", "",
         "## Kinds", "", "| Kind | Id | Class | Parse function | Payload bytes |", "|---|---|---|---|---|"]
    for name, idname, idv, cls, clsv, fn in kinds:
        a.append("| `%s` | %d | %d | `%s` | %d |" % (name, idv, clsv, fn, plans[fn][1] // 8 - 2))
    a += ["", "## Shared keys", ""]
    rows = [(fn, path, k, "", ev) for (fn, path), (k, ev) in BINDS.items()]
    rows += [(fn, path, k, tr, ev) for (fn, path), (k, tr, ev) in ALSO.items()]
    if BIND_POSITION:
        rows += [(fn, path, k, "", ev) for (fn, path), (k, ev) in POSITION_BINDS.items()]
    a += ["| Parse function | Field | Key | Transform | Evidence |", "|---|---|---|---|---|"]
    for fn, path, k, tr, ev in sorted(rows):
        a.append("| `%s` | `%s` | `%s` | %s | %s |" % (fn, path, k, "`%s`" % tr if tr else "as the field", ev))
    a += ["",
          "The velocities are stated in the North-East-Down frame in metres per second. North and east",
          "bind `track.vel_north_ms` and `track.vel_east_ms`. Down keeps its raw key, and a second line on",
          "the same bits binds `track.vel_up_ms` with `f32scale:-1`; encode from either key writes the",
          "same bits (a down velocity of 0 decodes as an up velocity of -0, which encodes back to 0).",
          "The body-frame velocities (`EKF_VEL_BODY`, odometer, DVL) are not in a shared frame.", ""]
    if BIND_POSITION:
        a += ["Latitude and longitude are in degrees, positive north and east, and bind `lat` and `lon`.",
              "The altitude is above mean sea level, with the undulation (the geoid's height over the",
              "ellipsoid) beside it; the struct comments and the EKF navigation log's note give the height",
              "over the ellipsoid as altitude plus undulation. The module states that as",
              "`derive hae add <altitude> <undulation>` (engine-spec 0.16), for the EKF navigation log and",
              "the GNSS position logs. The altitude above mean sea level stays a raw key; a derive runs one",
              "way, so a message encoded from `hae` alone leaves altitude and undulation zero.", "",
              "**Datum.** The documentation of the EKF navigation log and the common definitions",
              "(`doc/binaryMessages.md`, `doc/commonDefs.md`) state that the position is in the datum of the",
              "position aiding source, with no datum conversion. With GNSS aiding that is WGS 84, the datum",
              "of the shared `lat`, `lon` and `hae`. With aiding in a local frame, such as an RTK base whose",
              "coordinates are given in ETRS89, the position is in that frame, which differs from WGS 84 by",
              "up to about a metre; the pack cannot tell the two apart. Times are microseconds since the",
              "unit started, or the time into the GPS week, and stay raw.", ""]
    else:
        a += ["Latitude and longitude are raw keys, not `lat` and `lon`: the position is in the datum of",
              "the position aiding source (`doc/binaryMessages.md`), which the source does not fix to",
              "WGS 84.", ""]
    a += ["## Not mapped, and why", "", "| What | Why |", "|---|---|",
          "| The frame (sync, length, CRC-16, end byte; extended frames) | the framer's (see Message convention) |",
          "| Enumerations and bit fields (status words) | carried as the integer the log holds |",
          "| NaN and infinite floats | the `f32` and `f64` transforms refuse them on decode (`transform-decode`) |",
          "| Defaults the parse functions set for a missing optional field (`UINT8_MAX`, `NAN`, ...) | the pack language leaves an absent field absent and encodes zero bits |"]
    for fn, why in notbuilt.items():
        logs = ", ".join("`%s`" % e[1] for e in skipped if e[5] == fn)
        a.append("| %s (`%s`) | the parse function holds %s, which a fixed layout cannot state |" % (logs, fn, why))
    a += ["", "## Vectors", "",
          "`vectors/gen-rt-<kind>.json`: a round trip per kind with every field set, values chosen by the",
          "generator and packed by its own serializer from the read list. `-before-optional`: a payload",
          "that ends before the optional fields, re-encoded with them as zero bytes. `gen-err-short` is",
          "one byte short of the fields that are not optional; `gen-err-other-id` names no kind.",
          "%d vector files." % nvec, "", "## Sources", "", "See `PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def provenance(commit, ref, files, shas, src):
    lic = read_text(src, "LICENSE.md").rstrip("\n").splitlines()
    a = ["# Provenance", "",
         "Generated by `tools/gen/sbgecom2pack.py`. No source file is copied into this repository. The",
         "generator reads the order, types and sizes of the reads in the parse functions, the message ids",
         "and classes, and the sizes of byte arrays from the files below; descriptions are its own.",
         "`doc/binaryMessages.md` is read by a person for the evidence of the shared keys. Date read: %s." % DATE_READ,
         "", "| Fact | Value |", "|---|---|", "| Repository | %s |" % REPO, "| Ref | `%s` |" % ref,
         "| Commit | `%s` |" % commit, "",
         "Each file is `https://raw.githubusercontent.com/SBG-Systems/sbgECom/<commit>/<path>`.", "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in files:
        a.append("| `%s` | `%s` |" % (rel, shas[rel]))
    a += ["", "## License", "", "`LICENSE.md` at the root of the repository, quoted whole:", "", "```"] + lic + ["```", "",
          "Licence of this pack: Apache-2.0, the repository's (REUSE.toml). It restates field order, types,",
          "sizes and identifiers, with descriptions of its own; the MIT notice above is kept with it here",
          "and in NOTICE.", "",
          "No source carries a distribution statement, handling marking, export-control notice or",
          "proprietary notice."]
    return "\n".join(a) + "\n"


def sources_provenance(commit, ref, files, src):
    a = ["# Provenance of the inputs of tools/gen/sbgecom2pack.py", "",
         "Written by `sbgecom2pack.py --commit`; every later run checks the files against it.",
         "Date read: %s." % DATE_READ, "", "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % REPO, "| Ref | `%s` |" % ref, "| Commit | `%s` |" % commit, "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in files:
        a.append("| `%s` | `%s` |" % (rel, sha256_file(os.path.join(src, *rel.split("/")))))
    a += ["", "License: MIT; see `packs/sbgecom/PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", required=True, metavar="DIR", help="a checkout of %s" % REPO)
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--commit", help="write %s for this commit (with --ref)" % PROV)
    ap.add_argument("--ref", help="the tag of --commit")
    args = ap.parse_args(argv)
    if args.commit and not args.ref:
        ap.error("--commit needs --ref")
    args.root = args.out
    args.model_from_out = True
    out = genio.Output(args.out, check=args.check)
    try:
        kinds, skipped, notbuilt, nkeys, nvec = build(args, out)
    except GenError as e:
        print("sbgecom2pack: %s" % e, file=sys.stderr)
        return 1
    print("sbgecom2pack: %d kinds from %d parse functions (%d payload sizes agree with the documentation), "
          "%d logs not built (%d functions), %d keys, %d vectors checked"
          % (len(kinds), len({k[5] for k in kinds}), args.doc_checked, len(skipped), len(notbuilt), nkeys, nvec))
    for fn, why in notbuilt.items():
        print("  not built  %s: %s" % (fn, why))
    return out.report("sbgecom2pack")


if __name__ == "__main__":
    sys.exit(main())
