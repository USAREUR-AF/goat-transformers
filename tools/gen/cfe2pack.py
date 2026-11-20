#!/usr/bin/env python3
"""cfe2pack: NASA cFE core command and telemetry packets as goat-transformers `bits` packs.

Reads   a checkout of github.com/nasa/cFE (the default, non-EDS headers):
          modules/<m>/config/default_cfe_<m>_*.h     payload structs, message structs,
                                                     function codes, message IDs, sizes
          modules/<m>/fsw/inc/*.h                    topic IDs and function-code names
          modules/<m>/fsw/src/cfe_<m>_dispatch.c     which struct a message ID and a
                                                     function code carry (commands)
          modules/core_api/config/default_*.h        message ID bases, mission sizes
          modules/resourceid/option_inc/cfe_resourceid_simple.h
          modules/msg/option_inc/default_cfe_msg_*.h header layout (checked, see below)
Writes  <out>/model/cfemsg.def                    keys of the cFE secondary headers
        <out>/model/cfe<m>.def                    raw keys of the payloads of module m
        <out>/packs/cfe-<m>/pack.def, pack.md     one `bits` pack per module, payload little-endian
        <out>/packs/cfe-<m>-be/pack.def, pack.md  the same layout, payload big-endian
        <out>/tools/gen/cfe/layout.json           every kind's message ID, function code,
                                                  size and payload layout; the input of
                                                  tools/gen/cfe-vectors.py, which writes the
                                                  vectors (and runs in CI without cFE)
        <out>/tools/gen/names/cfe.json            the key of every payload path

A message is one whole cFE Software Bus packet: the CCSDS primary header (6 octets,
big-endian), the cFE secondary header (commands: function code and checksum, 2
octets; telemetry: 6-octet time and 4 spare octets), then the payload struct. The
primary header fields bind to the keys of `ccsdssp` (the ccsds-space-packet pack's
module), so a cFE packet converts to and from a bare space packet header.

Kinds. A command is selected by its stream ID (the first 16 bits: version, type,
secondary header flag and APID, which cFE's message ID equals in the default
mapping) and, on the module's command message ID, by its function code (the low 7
bits of octet 6); a command on another message ID (send housekeeping, the time
tone and one-hertz commands) by its stream ID alone, as the module's dispatch
function selects them. A telemetry packet is selected by its stream ID; which
struct each telemetry message ID carries is the table TLM below, from the
message ID names and the comments of default_cfe_<m>_msgids.h.

Layout rule (natural C alignment, the one the default build gives): every scalar
aligns to its own size (1, 2, 4 or 8 octets), a struct to the largest alignment of
its members, an array to its element's; a struct's size rounds up to its
alignment. The payload member follows the 8-octet command header or the 16-octet
telemetry header at the next multiple of its alignment (the headers are octet
arrays, alignment 1; the telemetry header's 4 spare octets exist so that a payload
of 8-octet alignment needs no padding). Payload integers and floats
are in the sending processor's byte order (cFE does not convert them): cfe-<m> states
little-endian and its lines carry `swap`; cfe-<m>-be states big-endian, with no `swap`.
Both use the same keys and modules. Implicit padding is not mapped; when it ends
the struct a `const` of 0 on its last octet keeps the message its C size.

Reader. Strict and small: comments; `#define` object and function-like macros
(with `##`), `#if`/`#ifdef`/`#ifndef`/`#elif`/`#else`/`#endif` over the macros
defined so far (no macro is predefined, so EDS and strict options are off);
`enum` constants; `typedef <type> name[...];`; `typedef struct [tag] {...} name;`
and `struct tag {...};` with members `<type> a[N]..., b;`. A member that is a
pointer, a bit-field or of an unknown type stops the run with its name.

Python 3 standard library only. Re-runnable: the same inputs give the same bytes.
After writing, every pack is loaded with tools/gen/gtcheck.py. Vectors are written by
tools/gen/cfe-vectors.py from layout.json; no engine is run.

Usage: python3 -I tools/gen/cfe2pack.py --src <cFE checkout> --out <checkout> [--check]
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

TAG = "v7.0.2-rc1"
COMMIT = "73f6fe102eae7949fc5f550e6818fec60319ddea"
REPO = "https://github.com/nasa/cFE"
SOURCE = "%s at tag %s, commit %s; Apache-2.0" % (REPO, TAG, COMMIT)
MODULES = ["es", "evs", "sb", "tbl", "time"]
TITLES = {"es": "Executive Services", "evs": "Event Services", "sb": "Software Bus",
          "tbl": "Table Services", "time": "Time Services"}
UNROLL = 8          # a scalar array of more elements is a fixed-count group
ASCII_MAX = 255     # a char array of more octets is a group of octets

BASE = {  # C type -> (size, kind): u unsigned, s signed, f float, c char
    "uint8": (1, "u"), "int8": (1, "s"), "uint16": (2, "u"), "int16": (2, "s"),
    "uint32": (4, "u"), "int32": (4, "s"), "uint64": (8, "u"), "int64": (8, "s"),
    "uint8_t": (1, "u"), "int8_t": (1, "s"), "uint16_t": (2, "u"), "int16_t": (2, "s"),
    "uint32_t": (4, "u"), "int32_t": (4, "s"), "uint64_t": (8, "u"), "int64_t": (8, "s"),
    "char": (1, "c"), "bool": (1, "u"), "float": (4, "f"), "double": (8, "f"),
}

# Telemetry: the struct each telemetry message ID carries (default_cfe_<m>_msgids.h
# names the IDs; the struct names match them one for one).
TLM = {
    "es": [("HousekeepingTlm", "HK_TLM"), ("OneAppTlm", "APP_TLM"), ("MemStatsTlm", "MEMSTATS_TLM")],
    "evs": [("HousekeepingTlm", "HK_TLM"), ("LongEventTlm", "LONG_EVENT_MSG"),
            ("ShortEventTlm", "SHORT_EVENT_MSG")],
    "sb": [("HousekeepingTlm", "HK_TLM"), ("StatsTlm", "STATS_TLM"),
           ("AllSubscriptionsTlm", "ALLSUBS_TLM"), ("SingleSubscriptionTlm", "ONESUB_TLM")],
    "tbl": [("HousekeepingTlm", "HK_TLM"), ("TableRegistryTlm", "REG_TLM")],
    "time": [("HousekeepingTlm", "HK_TLM"), ("DiagnosticTlm", "DIAG_TLM")],
}


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


# --------------------------------------------------------------------------
# Reading C
# --------------------------------------------------------------------------

def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


class C:
    def __init__(self):
        self.macros = {}          # name -> (params or None, body)
        self.typedefs = {}        # name -> (base type name, dims)
        self.structs = {}         # name (typedef or "struct tag") -> [(type, name, dims)]
        self.enums = {}           # constant -> int
        self.files = []           # every file read, in order

    # -- macros ------------------------------------------------------------
    def expand(self, text, depth=0, hide=frozenset()):
        if depth > 40:
            fail("macro expansion too deep: %s" % text)
        out, i = [], 0
        toks = re.findall(r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*|##|\S", text)
        while i < len(toks):
            t = toks[i]
            if t in self.macros and t not in hide:
                params, body = self.macros[t]
                if params is None:
                    out.append(self.expand(body, depth + 1, hide | {t}))
                    i += 1
                    continue
                if i + 1 < len(toks) and toks[i + 1] == "(":
                    args, cur, level, j = [], [], 0, i + 2
                    while j < len(toks):
                        if toks[j] == "(":
                            level += 1
                        elif toks[j] == ")":
                            if level == 0:
                                break
                            level -= 1
                        elif toks[j] == "," and level == 0:
                            args.append(" ".join(cur))
                            cur = []
                            j += 1
                            continue
                        cur.append(toks[j])
                        j += 1
                    args.append(" ".join(cur))
                    sub = dict(zip(params, args))
                    btoks = re.findall(r"[A-Za-z_]\w*|0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*|##|\S", body)
                    res = []
                    for k, bt in enumerate(btoks):
                        pasted = (k > 0 and btoks[k - 1] == "##") or (k + 1 < len(btoks) and btoks[k + 1] == "##")
                        if bt in sub:
                            res.append(sub[bt].replace(" ", "") if pasted else sub[bt])
                        else:
                            res.append(bt)
                    joined = " ".join(res)
                    joined = re.sub(r"\s*##\s*", "", joined)
                    out.append(self.expand(joined, depth + 1, hide | {t}))
                    i = j + 1
                    continue
            out.append(t)
            i += 1
        return " ".join(out)

    def value(self, expr):
        e = self.expand(expr)
        e = " ".join(str(self.enums[t]) if t in self.enums else t for t in e.split())
        e = re.sub(r"\b(0[xX][0-9A-Fa-f]+|\d+)[uUlL]+\b", r"\1", e)
        e = re.sub(r"\(\s*(?:uint\d+|int\d+|unsigned|int|long)\s*\)", "", e)
        if re.search(r"[A-Za-z_]", re.sub(r"0[xX][0-9A-Fa-f]+", "0", e)):
            fail("cannot evaluate %r (%r)" % (expr, e))
        e = e.replace("/", "//").replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        return int(eval(e, {"__builtins__": {}}))  # noqa: S307 - digits and operators only, checked above

    # -- files -------------------------------------------------------------
    def read(self, path):
        self.files.append(path)
        with open(path, encoding="utf-8") as fh:
            text = strip_comments(fh.read())
        text = re.sub(r"\\\n", " ", text)
        stack, body = [], []
        for line in text.split("\n"):
            s = line.strip()
            active = all(x[0] for x in stack)
            m = re.match(r"#\s*(\w+)\s*(.*)", s)
            if m:
                d, rest = m.group(1), m.group(2).strip()
                if d in ("ifdef", "ifndef"):
                    v = (rest.split()[0] in self.macros) == (d == "ifdef")
                    stack.append([v and active, v])
                elif d == "if":
                    v = self.cond(rest) if active else False
                    stack.append([v and active, v])
                elif d == "elif":
                    top = stack[-1]
                    par = all(x[0] for x in stack[:-1])
                    v = (not top[1]) and par and self.cond(rest)
                    top[0], top[1] = v, top[1] or v
                elif d == "else":
                    top = stack[-1]
                    par = all(x[0] for x in stack[:-1])
                    top[0], top[1] = par and not top[1], True
                elif d == "endif":
                    stack.pop()
                elif d == "define" and active:
                    mm = re.match(r"([A-Za-z_]\w*)(\(([^)]*)\))?\s*(.*)", rest)
                    params = [p.strip() for p in mm.group(3).split(",")] if mm.group(2) else None
                    self.macros[mm.group(1)] = (params, mm.group(4))
                elif d == "undef" and active:
                    self.macros.pop(rest.split()[0], None)
                continue
            if active:
                body.append(line)
        self.declarations(" ".join(body))

    def cond(self, expr):
        e = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)",
                   lambda m: "1" if (m.group(1) or m.group(2)) in self.macros else "0", expr)
        try:
            return bool(self.value(e))
        except GenError:
            return False

    def declarations(self, text):
        for m in re.finditer(r"\benum\s*(\w*)\s*\{([^}]*)\}", text):
            nxt = -1
            for item in m.group(2).split(","):
                item = item.strip()
                if not item:
                    continue
                name, _, val = item.partition("=")
                nxt = self.value(val) if val.strip() else nxt + 1
                self.enums[name.strip()] = nxt
        for m in re.finditer(r"\b(typedef\s+)?struct\s+(\w*)\s*\{([^{}]*)\}\s*(\w*)\s*;", text):
            members = self.members(m.group(3))
            if m.group(2):
                self.structs["struct " + m.group(2)] = members
            if m.group(1) and m.group(4):
                self.structs[m.group(4)] = members
        for m in re.finditer(r"\btypedef\s+(?!struct\b|enum\b|union\b)([\w\s]+?)\s+(\w+)\s*((?:\[[^\]]*\]\s*)*);", text):
            base = m.group(1).split()[-1]
            dims = [x for x in re.findall(r"\[([^\]]*)\]", m.group(3))]
            self.typedefs[m.group(2)] = (base, dims)
        for m in re.finditer(r"\btypedef\s+struct\s+(\w+)\s+(\w+)\s*;", text):
            self.typedefs[m.group(2)] = ("struct " + m.group(1), [])
        for m in re.finditer(r"\btypedef\s+enum\s+\w*\s*\{[^}]*\}\s*(\w+)\s*;", text):
            self.typedefs[m.group(1)] = ("int32", [])

    def members(self, body):
        out = []
        for decl in body.split(";"):
            decl = decl.strip()
            if not decl:
                continue
            if "(" in decl or "*" in decl or re.search(r":\s*\d", decl):
                fail("unsupported member: %s" % decl)
            m = re.match(r"((?:const\s+|struct\s+)*[A-Za-z_]\w*)\s+(.*)", decl)
            typ = m.group(1).replace("const ", "").strip()
            for d in m.group(2).split(","):
                dm = re.match(r"\s*(\w+)\s*((?:\[[^\]]*\]\s*)*)$", d)
                if not dm:
                    fail("unsupported declarator: %s" % decl)
                out.append((typ, dm.group(1), re.findall(r"\[([^\]]*)\]", dm.group(2))))
        return out

    # -- layout ------------------------------------------------------------
    def resolve(self, typ):
        dims = []
        seen = 0
        while typ not in BASE and typ not in self.structs:
            if typ not in self.typedefs and typ in self.macros and self.macros[typ][0] is None:
                typ = self.expand(typ).strip()
                seen += 1
                continue
            if typ not in self.typedefs:
                fail("unknown type %s" % typ)
            typ, d = self.typedefs[typ]
            dims = [self.value(x) for x in d] + dims
            seen += 1
            if seen > 20:
                fail("typedef loop at %s" % typ)
        return typ, dims

    def layout(self, typ):
        """(size, align) of a type."""
        typ, dims = self.resolve(typ)
        n = 1
        for d in dims:
            n *= d
        if typ in BASE:
            size, _ = BASE[typ]
            return size * n, size
        size, align = 0, 1
        for mt, _, md in self.structs[typ]:
            s, a = self.layout(mt)
            for d in md:
                s *= self.value(d)
            size = (size + a - 1) // a * a + s
            align = max(align, a)
        return (size + align - 1) // align * align * n, align


# --------------------------------------------------------------------------
# Layout to lines
# --------------------------------------------------------------------------

def snake(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


class Leaf:
    """A field of the layout: offset in octets from the start of its scope."""

    def __init__(self, path, offset, size, kind, count=1):
        self.path, self.offset, self.size, self.kind, self.count = path, offset, size, kind, count


class Group:
    def __init__(self, path, offset, item_size, count, body):
        self.path, self.offset, self.item_size, self.count, self.body = path, offset, item_size, count, body


def flatten(c, typ, offset, path):
    """Leaves and groups of `typ` placed at `offset`."""
    typ, dims = c.resolve(typ)
    if dims:
        return place_array(c, typ, dims, offset, path)
    if typ in BASE:
        size, kind = BASE[typ]
        return [Leaf(path, offset, size, kind)]
    out, pos = [], 0
    for mt, mn, md in c.structs[typ]:
        s, a = c.layout(mt)
        pos = (pos + a - 1) // a * a
        dims_m = [c.value(d) for d in md]
        if dims_m:
            rt, rdims = c.resolve(mt)
            out += place_array(c, rt, dims_m + rdims, offset + pos, path + [mn])
            n = 1
            for d in dims_m:
                n *= d
            pos += s * n
        else:
            out += flatten(c, mt, offset + pos, path + [mn])
            pos += s
    return out


def place_array(c, typ, dims, offset, path):
    n = 1
    for d in dims:
        n *= d
    esize, _ = c.layout(typ)
    if typ == "char" and len(dims) == 1 and n <= ASCII_MAX:
        return [Leaf(path, offset, n, "a")]
    if typ in BASE and n <= UNROLL:
        return [Leaf(path + [str(i)], offset + i * esize, esize, BASE[typ][1]) for i in range(n)]
    body = flatten(c, typ, 0, [])
    return [Group(path, offset, esize, n, body)]


# --------------------------------------------------------------------------
# Plan of one module
# --------------------------------------------------------------------------

READ_EXTRA = []


def dispatch_map(path, m):
    """[(struct, mid macro, cc macro or None)] from cfe_<m>_dispatch.c."""
    READ_EXTRA.append(path)
    with open(path, encoding="utf-8") as fh:
        t = strip_comments(fh.read())
    out, last_cc, last_mid = [], None, None
    P = "CFE_%s_" % m.upper()
    # a table of entries (TBL): <PREFIX>_ENTRY(mid, cc, struct, handler, type); a
    # MSG-type entry is selected by its message ID alone
    for e in re.finditer(r"\b%sENTRY\(\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)_t\s*,\s*\w+\s*,\s*(\w+)\s*\)" % P, t):
        mid, cc, st, typ = e.groups()
        out.append((st, mid, None if typ.endswith("_MSG_MSGTYPE") else cc))
    if out:
        return out
    toks = re.findall(r"\bcase\s+(\w+_CC)\s*:|\b(\w+_MID)\b|\(const\s+(\w+)_t\s*\*\)", t)
    for cc, mid, st in toks:
        if cc:
            last_cc, last_mid = cc, None
        elif mid:
            last_mid, last_cc = mid, None
        elif st:
            if last_cc:
                out.append((st, P + "CMD_MID", last_cc))
            elif last_mid:
                full = last_mid if last_mid.startswith(P) else P + last_mid
                out.append((st, full, None))
            last_cc = last_mid = None
    return out


def plan_module(c, src, m):
    P = "CFE_%s_" % m.upper()
    msgs = []
    disp = dispatch_map(os.path.join(src, "modules/%s/fsw/src/cfe_%s_dispatch.c" % (m, m)), m)
    seen = set()
    for st, mid, cc in disp:
        if st in seen:
            continue
        seen.add(st)
        msgs.append(dict(struct=st + "_t", mid=c.value(mid), mid_name=mid, cc=None if cc is None else c.value(cc),
                         cc_name=cc, cmd=True))
    for st, mid in TLM[m]:
        name = P + st + "_t"
        msgs.append(dict(struct=name, mid=c.value(P + mid + "_MID"), mid_name=P + mid + "_MID", cc=None,
                         cc_name=None, cmd=False))
    skipped = []
    for name in sorted(n for n in c.structs if n.startswith(P) and n.endswith(("Cmd_t", "Tlm_t"))
                       and c.structs[n] and c.structs[n][0][1] in ("CommandHeader", "TelemetryHeader")):
        if name not in [x["struct"] for x in msgs]:
            skipped.append(name)
    for msg in msgs:
        if msg["struct"] not in c.structs:
            fail("%s: no struct %s" % (m, msg["struct"]))
        mem = c.structs[msg["struct"]]
        hdr = "CommandHeader" if msg["cmd"] else "TelemetryHeader"
        if mem[0][1] != hdr:
            fail("%s: %s does not start with %s" % (m, msg["struct"], hdr))
        hsize = 8 if msg["cmd"] else 16
        msg["size"], _ = c.layout(msg["struct"])
        msg["body"] = []
        if len(mem) > 1:
            if len(mem) != 2 or mem[1][1] != "Payload":
                fail("%s: %s has members other than a header and Payload" % (m, msg["struct"]))
            ptype = mem[1][0]
            psize, palign = c.layout(ptype)
            off = (hsize + palign - 1) // palign * palign
            if off != hsize:
                fail("%s: payload of %s does not follow its header" % (m, msg["struct"]))
            msg["ptype"] = ptype
            msg["body"] = flatten(c, ptype, off, [])
        msg["kind"] = snake(msg["struct"][len(P):-2])
    return msgs, skipped


def module_header_checks(src):
    """The header layouts this generator assumes, checked against the source text."""
    READ_EXTRA.extend(os.path.join(src, "modules/msg/option_inc/default_cfe_msg_%s.h" % x) for x in ("hdr_pri", "sechdr"))
    pri = strip_comments(open(os.path.join(src, "modules/msg/option_inc/default_cfe_msg_hdr_pri.h")).read())
    sec = strip_comments(open(os.path.join(src, "modules/msg/option_inc/default_cfe_msg_sechdr.h")).read())
    need = [(sec, r"uint8\s+FunctionCode\s*;"), (sec, r"uint8\s+Checksum\s*;"), (sec, r"uint8\s+Time\[6\]\s*;"),
            (pri, r"uint8\s+Spare\[4\]\s*;")]
    for text, pat in need:
        if not re.search(pat, text):
            fail("header layout changed: %s" % pat)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

class Names:
    def __init__(self, path):
        self.path = path
        self.map = {}
        if os.path.exists(path):
            with open(path) as fh:
                self.map = json.load(fh)

    def key(self, module, ident, proposed):
        k = "%s:%s" % (module, ident)
        if k not in self.map:
            used = {v for kk, v in self.map.items() if kk.startswith(module + ":")}
            name, i = proposed, 2
            while name in used:
                name, i = "%s_%d" % (proposed, i), i + 1
            self.map[k] = name
        return self.map[k]

    def text(self):
        return json.dumps(dict(sorted(self.map.items())), indent=1) + "\n"


def transform(leaf, big=False):
    if leaf.kind == "a":
        return "ascii"
    if leaf.kind == "f":
        t = "f32" if leaf.size == 4 else "f64"
    elif leaf.kind == "s":
        t = "twos"
    else:
        t = "uint"
    return t + (" swap" if leaf.size > 1 and not big else "")


def ptype_short(m, ptype):
    P = "CFE_%s_" % m.upper()
    s = ptype[len(P):] if ptype.startswith(P) else ptype
    s = re.sub(r"_t$", "", s)
    s = re.sub(r"_Payload$", "", s)
    return snake(s)


def emit_body(lines, keys, names, mod, scope, prefix, items, base_bits, indent, big=False):
    """`scope` names the payload type (and list) for the names file; `prefix` starts each key."""
    for it in items:
        rel = "_".join(snake(p) for p in it.path)
        ident = scope + "." + ".".join(it.path)
        if isinstance(it, Group):
            lname = names.key(mod, ident, prefix + "_" + rel if rel else prefix + "_items")
            it.key = lname
            keys.append(("list", lname, "%s: %d items of %d octets" % (".".join(it.path), it.count, it.item_size)))
            lines.append("%sgroup  %s.%s  0:%d  item %d  count %d" % (indent, mod, lname, base_bits + it.offset * 8,
                                                                     it.item_size * 8, it.count))
            emit_body(lines, keys, names, mod, ident, lname, it.body, 0, indent + "  ", big)
            lines.append(indent + "end")
        else:
            k = names.key(mod, ident, prefix + "_" + rel if rel else prefix + "_value")
            it.key = k
            typ = "string" if it.kind == "a" else ("float" if it.kind == "f" else "int")
            keys.append(("key", k, typ, ".".join(it.path) or "(item)", it.size))
            lines.append("%sfield  %s.%s  0:%d:%d  %s" % (indent, mod, k, base_bits + it.offset * 8, it.size * 8,
                                                         transform(it, big)))


def build(c, src, out, names):
    module_header_checks(src)
    written = {}
    plans = {}
    layout = {}
    for m in MODULES:
        plans[m] = plan_module(c, src, m)
    # cfemsg module
    out.write("model/cfemsg.def", "\n".join([
        "# The cfemsg module: the cFE secondary headers that follow the CCSDS primary header",
        "# of every cFE Software Bus packet (modules/msg/option_inc/default_cfe_msg_sechdr.h and",
        "# default_cfe_msg_hdr_pri.h of nasa/cFE). Generated by tools/gen/cfe2pack.py.",
        "module        cfemsg",
        "version       0.1.0",
        "distribution  public",
        "source        \"%s, modules/msg/option_inc\"" % SOURCE,
        "key  function_code  int  -  \"command: function code, low 7 bits of octet 6 (bit 7 is reserved)\"",
        "key  checksum       int  -  \"command: octet 7, chosen so that the XOR of every octet of the packet is 0xFF\"",
        "key  time_seconds   int  s  \"telemetry: octets 6-9, big-endian: seconds of the CCSDS unsegmented time (CUC) the packet was stamped with, from the mission epoch\"",
        "key  time_subseconds  int  -  \"telemetry: octets 10-11, big-endian: fraction of a second in units of 2^-16 s\"",
        "key  spare          int  -  \"telemetry: octets 12-15, padding so that a payload of 8-octet alignment needs none\"",
        ""]))
    for m, big in [(m, b) for m in MODULES for b in (False, True)]:
        msgs, skipped = plans[m]
        mod = "cfe" + m
        fmt = "cfe-" + m + ("-be" if big else "")
        order = "big-endian" if big else "little-endian (swap)"
        lines, keys = [], []
        head = [
            "# NASA cFE %s (%s) command and telemetry packets: one whole Software Bus" % (m.upper(), TITLES[m]),
            "# packet, CCSDS primary header, cFE secondary header and payload. Generated by",
            "# tools/gen/cfe2pack.py from the default headers of nasa/cFE; do not edit by hand.",
            "# Payload integers and floats are %s; pack.md states the layout rule." % order,
            "format     %s" % fmt,
            "version    0.1.0",
            "distribution public",
            "source     \"%s, modules/%s/config and modules/%s/fsw\"" % (SOURCE, m, m),
            "uses       ccsdssp",
            "uses       cfemsg",
            "uses       %s" % mod,
            "wire       bits",
            "word_bytes 1",
            "bit_order  msb",
            "field  ccsdssp.packet_type            0:3:1    uint",
            "field  ccsdssp.secondary_header_flag  0:4:1    uint",
            "field  ccsdssp.apid                   0:5:11   uint",
            "field  ccsdssp.sequence_flags         0:16:2   uint",
            "field  ccsdssp.data_length            0:32:16  uint",
            "default  ccsdssp.sequence_flags  3",
        ]
        for msg in msgs:
            sid = msg["mid"]
            apid = sid & 0x7FF
            lines.append("")
            lines.append("kind  %s" % msg["kind"])
            lines.append("when  0:0:16  %d" % sid)
            if msg["cc"] is not None:
                lines.append("when  0:49:7  %d" % msg["cc"])
                lines.append("requires  ccsdssp.packet_type=1 ccsdssp.apid=%d cfemsg.function_code=%d" % (apid, msg["cc"]))
            else:
                lines.append("requires  ccsdssp.packet_type=%d ccsdssp.apid=%d" % (1 if msg["cmd"] else 0, apid))
            lines.append("default  ccsdssp.data_length  %d" % (msg["size"] - 7))
            if msg["cmd"]:
                lines.append("field  ccsdssp.sequence_count_or_name  0:18:14  uint")
                lines.append("field  cfemsg.function_code  0:49:7  uint")
                lines.append("field  cfemsg.checksum       0:56:8  uint")
                if msg["cc"] is not None:
                    lines.append("default  cfemsg.function_code  %d" % msg["cc"])
            else:
                lines.append("field  ccsdssp.sequence_count   0:18:14  uint")
                lines.append("field  cfemsg.time_seconds     0:48:32  uint")
                lines.append("field  cfemsg.time_subseconds  0:80:16  uint")
                lines.append("field  cfemsg.spare            0:96:32  uint")
            if msg["body"]:
                emit_body(lines, keys, names, mod, ptype_short(m, msg["ptype"]), ptype_short(m, msg["ptype"]), msg["body"], 0, "", big)
            end = end_of(msg["body"], 8 if msg["cmd"] else 16)
            if end < msg["size"]:
                lines.append("const  0:%d:8  0" % ((msg["size"] - 1) * 8))
            msg["pad_const"] = end < msg["size"]
        out.write("packs/%s/pack.def" % fmt, "\n".join(head + lines) + "\n")
        # module of raw keys, one line per key (first declaration wins)
        seen, kl = set(), []
        for k in keys:
            if k[1] in seen:
                continue
            seen.add(k[1])
            if k[0] == "list":
                kl.append("list  %s  \"%s\"" % (k[1], k[2]))
            else:
                kl.append("key   %s  %s  -  \"payload member %s, %d octet%s%s\"" % (
                    k[1], k[2], k[3], k[4], "s" if k[4] > 1 else "",
                    ", text NUL-padded" if k[2] == "string" else (", in the packet's byte order" if k[4] > 1 else "")))
        out.write("model/%s.def" % mod, "\n".join([
            "# The %s module: the payload members of the NASA cFE %s packets, one raw key per" % (mod, m.upper()),
            "# member path of each payload struct. Generated by tools/gen/cfe2pack.py.",
            "module        %s" % mod, "version       0.1.0", "distribution  public",
            "source        \"%s, modules/%s/config\"" % (SOURCE, m)] + kl) + "\n")
        out.write("packs/%s/pack.md" % fmt, pack_md(m, fmt, msgs, skipped, sources(c, src, m), big))
        layout[fmt] = {"endian": "big" if big else "little", "messages": [dict(kind=x["kind"], struct=x["struct"], mid=x["mid"], mid_name=x["mid_name"], cc=x["cc"],
                            cc_name=x["cc_name"], cmd=x["cmd"], size=x["size"], body=to_json(x["body"]))
                       for x in msgs]}
        written[fmt] = len(msgs)
    out.write("tools/gen/names/cfe.json", names.text())
    out.write("tools/gen/cfe/layout.json", json.dumps({"source": SOURCE, "packs": layout}, indent=1) + "\n")
    return written, plans


def to_json(body):
    out = []
    for it in body:
        if isinstance(it, Group):
            out.append({"group": it.key, "offset": it.offset, "item_size": it.item_size, "count": it.count,
                        "body": to_json(it.body)})
        else:
            out.append({"key": it.key, "offset": it.offset, "size": it.size, "type": it.kind})
    return out


def end_of(body, start):
    end = start
    for it in body:
        if isinstance(it, Group):
            end = max(end, it.offset + it.item_size * it.count)
        else:
            end = max(end, it.offset + it.size)
    return end


# --------------------------------------------------------------------------
# pack.md
# --------------------------------------------------------------------------

def sources(c, src, m):
    """(relative path, octets, sha256) of every file read that bears on module m."""
    import hashlib
    rows = []
    for f in sorted(set(c.files + READ_EXTRA)):
        rel = os.path.relpath(f, src)
        if "/%s/" % m in rel or rel.startswith(("modules/core_api/", "modules/msg/", "modules/resourceid/")) \
                or (m != "sb" and rel.startswith("modules/sb/config")) or (m != "time" and rel.startswith("modules/time/config")) \
                or (m != "es" and rel.startswith("modules/es/config")):
            with open(f, "rb") as fh:
                data = fh.read()
            rows.append((rel, len(data), hashlib.sha256(data).hexdigest()))
    return rows


def pack_md(m, fmt, msgs, skipped, srcs, big=False):
    other = "cfe-%s" % m if big else "cfe-%s-be" % m
    w = ["# Pack: %s" % fmt, "",
         "NASA core Flight Executive (cFE) %s (%s): the command and telemetry packets of the module" % (m.upper(), TITLES[m]),
         "from a %s processor," % ("big-endian" if big else "little-endian"),
         "as they travel on the Software Bus. Generated by `tools/gen/cfe2pack.py` from %s at tag `%s`." % (REPO, TAG),
         "Wire `bits`, most significant bit first. Edit the generator, not this file.", "",
         "## Message convention", "",
         "One whole packet: the CCSDS primary header (octets 0-5, big-endian), the cFE secondary header,",
         "then the payload struct. A command's secondary header is the function code (low 7 bits of octet",
         "6) and a checksum (octet 7); a telemetry packet's is a 6-octet time (4 octets of seconds, 2 of",
         "subseconds, big-endian) and 4 spare octets, so its payload starts at octet 16.", "",
         "The primary header fields are the keys of module `ccsdssp`, which the pack `ccsds-space-packet`",
         "maps: a cFE packet converts to a bare space packet header, and a bare header converts to the",
         "packet its packet type and APID name, with the rest written as zero octets (a payload that holds",
         "a fixed-count array cannot be written from a bare header: `transform-encode`).", "",
         "## Layout rule", "",
         "The payload structs are laid out with natural C alignment: a scalar at a multiple of its size,",
         "a struct at the largest alignment of its members, a struct's size rounded up to that alignment.",
         ("Byte order: payload integers and floats are **big-endian**, as a big-endian processor writes"
          if big else "Byte order: payload integers and floats are **little-endian** (the lines carry `swap`), as"),
         ("them (no `swap`). cFE does not convert the payload's byte order, so the processor that sends a"
          if big else "a little-endian processor writes them. cFE does not convert the payload's byte order, so the"),
         ("packet decides it; `%s` is the same layout for little-endian processors. The headers are" % other
          if big else "processor that sends a packet decides it; `%s` is the same layout for big-endian processors." % other),
         ("big-endian in both. A char array is" if big else "The headers are big-endian in both. A char array is"),
         "`ascii`: printable text, NUL-padded; a NUL followed by other octets fails the decode.",
         "Implicit padding is not mapped and is written as zero; a `const` of 0 on the last octet keeps a",
         "packet whose struct ends in padding its C size.", "",
         "## Shared keys", "",
         "Only the primary header (`ccsdssp`). The telemetry time is CCSDS unsegmented time from the",
         "mission's epoch, which the packet does not state (cFE's default is 1980-01-06, the mission may",
         "choose another): `cfemsg.time_seconds` and `cfemsg.time_subseconds` are raw and `time_ms` is not",
         "bound. No payload member carries a position or a shared identifier.", "",
         "## Kinds", "",
         "| Kind | Struct | Message ID | Function code | Octets |", "|---|---|---|---|---|"]
    for msg in msgs:
        w.append("| `%s` | `%s` | `%s` 0x%04x | %s | %d |" % (
            msg["kind"], msg["struct"], msg["mid_name"], msg["mid"],
            "-" if msg["cc"] is None else "`%s` %d" % (msg["cc_name"], msg["cc"]), msg["size"]))
    w += ["", "Commands on the command message ID are selected by the function code; the others, and every",
          "telemetry packet, by the stream ID alone (`dispatch` in `modules/%s/fsw/src/cfe_%s_dispatch.c`)." % (m, m),
          "Encode selects a kind by `requires ccsdssp.packet_type=<0|1> ccsdssp.apid=<n>` (and the function",
          "code), so an entity from",
          "another format becomes the packet its APID names.", "",
          "## Not mapped", ""]
    w.append("- The checksum is carried as a raw key; nothing recomputes it when a command is re-encoded from")
    w.append("  other keys.")
    w.append("- Message IDs other than the defaults: a mission that changes its topic IDs or message ID bases")
    w.append("  needs the generator run with its own headers.")
    for s in skipped:
        w.append("- `%s`: no message ID of this module's dispatch or message ID list carries it." % s)
    w += ["", "## Sources", "", "Read from %s at tag `%s`, commit `%s` (Apache-2.0). The headers of other" % (REPO, TAG, COMMIT),
          "modules are read for the types and sizes they define.", "",
          "| File | Octets | SHA-256 |", "|---|---|---|"]
    w += ["| `%s` | %d | `%s` |" % r for r in srcs]
    w += ["", "## Vectors", "",
          "Written by `tools/gen/cfe-vectors.py` from `tools/gen/cfe/layout.json`: one round trip per kind,",
          "serialized octet by octet from the C layout with values of the script's own;",
          "a conversion to and from `ccsds-space-packet`; and an unknown function code (`no-kind`).", ""]
    return "\n".join(w)


# --------------------------------------------------------------------------

def load(src):
    c = C()
    # The two headers, as module_header_checks() verifies them in the source: a command
    # header of 6 + 2 octets and a telemetry header of 6 + 6 + 4 octets, all octet arrays.
    c.structs["CFE_MSG_CommandHeader_t"] = [("uint8", "Octets", ["8"])]
    c.structs["CFE_MSG_TelemetryHeader_t"] = [("uint8", "Octets", ["16"])]
    order = [
        "modules/core_api/config/default_cfe_core_api_base_msgid_values.h",
        "modules/core_api/config/default_cfe_core_api_msgid_mapping.h",
        "modules/core_api/config/default_cfe_core_api_interface_cfg_values.h",
        "modules/core_api/fsw/inc/cfe_core_api_interface_cfg.h",
        "modules/core_api/config/default_cfe_mission_cfg.h",
        "modules/resourceid/option_inc/cfe_resourceid_simple.h",
    ]
    for p in order:
        fp = os.path.join(src, p)
        if os.path.exists(fp):
            c.read(fp)
    for m in ["sb", "time", "es", "evs", "fs", "tbl"]:
        cfg = os.path.join(src, "modules", m, "config")
        inc = os.path.join(src, "modules", m, "fsw", "inc")
        files = []
        for d in (cfg, inc):
            if os.path.isdir(d):
                files += sorted(os.path.join(d, f) for f in os.listdir(d)
                                if f.endswith(".h") and not f.startswith("eds_") and "platform_cfg" not in f
                                and "internal_cfg" not in f)
        # values and typedefs first, then message definitions
        rank = lambda f: (0 if re.search(r"(values|mission_cfg|interface_cfg|extern_typedefs|memaddress|topicids|fcncodes)", f) else 1, f)  # noqa: E731
        for f in sorted(files, key=rank):
            c.read(f)
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cfe2pack.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="a checkout of nasa/cFE at %s" % TAG)
    genio.add_arguments(ap)
    a = ap.parse_args(argv)
    try:
        got = subprocess.run(["git", "-C", a.src, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if got != COMMIT:
            fail("%s is at %s, not %s (%s)" % (a.src, got or "?", COMMIT, TAG))
        c = load(a.src)
        out = genio.Output(a.out, check=a.check)
        names = Names(os.path.join(a.out, "tools/gen/names/cfe.json"))
        written, _ = build(c, a.src, out, names)
        if not a.check:
            rc = gtcheck.main(["--model", os.path.join(a.out, "model")] +
                              [os.path.join(a.out, "packs", f, "pack.def") for f in sorted(written)] +
                              [os.path.join(a.out, "packs/ccsds-space-packet/pack.def")])
            if rc:
                fail("gtcheck refused the output")
            for f, n in sorted(written.items()):
                print(f, n)
        return out.report("cfe2pack")
    except GenError as e:
        print("cfe2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
