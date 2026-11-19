#!/usr/bin/env python3
"""ros2msg2pack: turn ROS 2 message definitions (.msg) into goat-transformers packs.

Python 3 standard library only. Reads the .msg files of one or more ROS 2
interface packages and writes, for each package <pkg>:

  <out>/model/<module>.def                 raw keys of the package, one public module
  <out>/packs/ros2-<pkg>/pack.def          the pack (engine-spec 0.5 to 0.7, wire json)
  <out>/packs/ros2-<pkg>/pack.md           what is mapped, what is not, and why
  <out>/packs/ros2-<pkg>/PROVENANCE.md     every input file with its SHA-256 and licence
  <out>/packs/ros2-<pkg>/vectors/gen-*.json   a round trip per kind, edge and error cases
  <out>/packs/geojson/vectors/gen-geojson-to-ros2-<pkg>-*.json   for a kind bound to core lat/lon
  <names-dir>/ros2-<pkg>.json              the key name of every path, kept from run to run

The message is the JSON form rosbridge (rosbridge_suite, protocol v2.1.0) gives a
ROS 2 message, inside a rosbridge `publish` operation that names the interface
type in its `type` member:

  {"op":"publish","topic":"/fix","type":"sensor_msgs/msg/NavSatFix","msg":{...}}

One kind per .msg file, selected by `type`. A field of a nested message is a
member path under `msg`; an array is a `group` (engine-spec 0.7); `uint8[]` and
`char[]` are the base64 string rosbridge writes for them.

After writing, the script reads its own output back from disk and checks it with
a second parser and a small json-wire codec written from spec/engine-spec.md
(0.1.1, 0.4 to 0.7: kinds, `when`, `requires`, groups, residue, canonical
output) and a minimal geojson codec for the cross vectors. It refuses to finish
when the grammar, a declaration, a type or any vector of the pack does not hold.

Usage: see --help. Run with `python3 -I`.
"""
import argparse
import base64
import collections
import glob
import hashlib
import json
import os
import re
import sys
from decimal import Decimal

PACK_VERSION = "0.1.0"
PRIMITIVES = {
    "bool": ("int", "bool"),
    "byte": ("int", "int"), "char": ("int", "int"),
    "int8": ("int", "int"), "uint8": ("int", "int"),
    "int16": ("int", "int"), "uint16": ("int", "int"),
    "int32": ("int", "int"), "uint32": ("int", "int"),
    "int64": ("int", "int"), "uint64": ("int", "int"),
    "float32": ("float", "float"), "float64": ("float", "float"),
    "string": ("string", "string"), "wstring": ("string", "string"),
}
INT_RANGE = {
    "byte": (0, 255), "char": (0, 255),
    "int8": (-128, 127), "uint8": (0, 255),
    "int16": (-32768, 32767), "uint16": (0, 65535),
    "int32": (-2 ** 31, 2 ** 31 - 1), "uint32": (0, 2 ** 32 - 1),
    "int64": (-2 ** 63, 2 ** 63 - 1), "uint64": (0, 2 ** 64 - 1),
}
BINARY_ARRAYS = {"uint8", "char"}       # rosbridge writes these arrays as base64 text
R_BYTE_ARRAY = ("the protocol states no JSON form for byte[] (only uint8[] and char[] become "
                "base64), and rosbridge's converter at this commit copies the octet sequence as a "
                "list of one-byte objects, which its JSON writer cannot write")
MODULE_OF = {
    "std_msgs": "ros2std", "geometry_msgs": "ros2geometry", "sensor_msgs": "ros2sensor",
    "nav_msgs": "ros2nav", "diagnostic_msgs": "ros2diagnostic", "shape_msgs": "ros2shape",
    "trajectory_msgs": "ros2trajectory", "visualization_msgs": "ros2visualization",
    "stereo_msgs": "ros2stereo", "actionlib_msgs": "ros2actionlib",
    "builtin_interfaces": "ros2builtin",
}
REPO_OF = {"builtin_interfaces": "rcl_interfaces"}     # every other package: common_interfaces
PKG_DIR = {}            # package -> directory under its repository (--package-at); default the name
REPO_LICENSE = {"common_interfaces": "Apache License 2.0", "rcl_interfaces": "Apache License 2.0"}
LICENSE_FILES = {}      # repository -> licence files read (--license-file); default as below
LICENSE_NOTES = collections.OrderedDict()   # repository -> licence statement for PROVENANCE.md
EXTRA_FILES = {}        # package -> other files read as evidence (--evidence-file)
REPO_URL = {"common_interfaces": "https://github.com/ros2/common_interfaces",
            "rcl_interfaces": "https://github.com/ros2/rcl_interfaces",
            "rosbridge_suite": "https://github.com/RobotWebTools/rosbridge_suite"}
ROSBRIDGE_FILES = ["ROSBRIDGE_PROTOCOL.md", "LICENSE",
                   "rosbridge_library/src/rosbridge_library/internal/message_conversion.py"]
VECTOR_ITEMS_TOP = 2          # items written for an unbounded array outside any group
VECTOR_ITEMS_NESTED = 1       # items written for an unbounded array inside a group


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


# --------------------------------------------------------------------------
# .msg parser
# --------------------------------------------------------------------------

class Field:
    def __init__(self, rostype, name, base, pkg_ref, array, bound, default):
        self.rostype = rostype      # as written, e.g. float64[9]
        self.name = name
        self.base = base            # primitive name, or message name
        self.pkg_ref = pkg_ref      # package of a message base, None for a primitive
        self.array = array          # None | ("unbounded",) | ("fixed", n) | ("bounded", n)
        self.bound = bound          # string<=N bound, or None
        self.default = default      # default value text, or None


class Msg:
    def __init__(self, pkg, name, path):
        self.pkg = pkg
        self.name = name
        self.path = path
        self.fields = []
        self.constants = []         # (type, name, value)


TYPE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)?)(?:<=(\d+))?"
                     r"(?:\[(<=)?(\d*)\])?$")
LINE_RE = re.compile(r"^(\S+)\s+([A-Za-z][A-Za-z0-9_]*)\s*(?:(=)\s*(.*?)|\s+(.*?))?\s*$")


def strip_comment(line):
    quote = None
    for i, c in enumerate(line):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#":
            return line[:i]
    return line


def parse_msg(pkg, name, path):
    m = Msg(pkg, name, path)
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            line = strip_comment(raw.rstrip("\n")).strip()
            if not line:
                continue
            g = LINE_RE.match(line)
            if not g:
                fail("%s:%d: cannot read %r" % (path, n, line))
            tok, fname, eq, cval, dval = g.groups()
            t = TYPE_RE.match(tok)
            if not t:
                fail("%s:%d: cannot read type %r" % (path, n, tok))
            base, bound, le, length = t.groups()
            if eq:
                m.constants.append((tok, fname, cval))
                continue
            if "[" in tok:
                if le:
                    array = ("bounded", int(length))
                elif length:
                    array = ("fixed", int(length))
                else:
                    array = ("unbounded",)
            else:
                array = None
            if "/" in base:
                pkg_ref, base = base.split("/")
            elif base in PRIMITIVES:
                pkg_ref = None
            else:
                pkg_ref = pkg
            if bound and base not in ("string", "wstring"):
                fail("%s:%d: bound on a non-string type" % (path, n))
            m.fields.append(Field(tok, fname, base, pkg_ref, array,
                                  int(bound) if bound else None, dval or None))
    return m


def pkg_dir(pkg):
    """(repository, directory of the package under it; "" when the package is the root)."""
    return REPO_OF.get(pkg, "common_interfaces"), PKG_DIR.get(pkg, pkg)


def msg_files(src, pkg):
    repo, d = pkg_dir(pkg)
    return repo, sorted(glob.glob(os.path.join(src, repo, d, "msg", "*.msg")))


class Catalog:
    def __init__(self, src):
        self.src = src
        self.msgs = {}

    def get(self, pkg, name):
        k = (pkg, name)
        if k not in self.msgs:
            repo, d = pkg_dir(pkg)
            path = os.path.join(self.src, repo, d, "msg", name + ".msg")
            if not os.path.isfile(path):
                fail("message %s/%s not found at %s" % (pkg, name, path))
            self.msgs[k] = parse_msg(pkg, name, path)
        return self.msgs[k]

    def package(self, pkg):
        _, files = msg_files(self.src, pkg)
        if not files:
            fail("package %s has no .msg files under %s" % (pkg, self.src))
        return [self.get(pkg, os.path.basename(p)[:-4]) for p in files]

    def closure_all(self, msgs):
        seen = collections.OrderedDict()
        for m in msgs:
            self.closure(m, seen)
        return seen.values()

    def closure(self, msg, seen=None):
        """Every message msg refers to, msg first, each once."""
        seen = seen if seen is not None else collections.OrderedDict()
        if (msg.pkg, msg.name) in seen:
            return seen
        seen[(msg.pkg, msg.name)] = msg
        for f in msg.fields:
            if f.pkg_ref:
                self.closure(self.get(f.pkg_ref, f.base), seen)
        return seen


# --------------------------------------------------------------------------
# Walk: message tree to pack lines
# --------------------------------------------------------------------------

def slug(name):
    s = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", s)
    s = re.sub(r"([0-9])([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


class FLine:
    def __init__(self, key, loc, transform, keytype, desc, pathid, rostype):
        self.key, self.loc, self.transform, self.keytype = key, loc, transform, keytype
        self.desc, self.pathid, self.rostype = desc, pathid, rostype


class GLine:
    def __init__(self, key, loc, body, desc, pathid):
        self.key, self.loc, self.body, self.desc, self.pathid = key, loc, body, desc, pathid


class Namer:
    """Pins the key name of every path: names already in the file are kept."""

    def __init__(self, path):
        self.path = path
        self.names = collections.OrderedDict()
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.names.update(json.load(fh))
        self.taken = {}
        for p, k in self.names.items():
            self.taken[k] = p
        self.used = set()

    def name(self, pathid, proposal):
        if pathid in self.names:
            k = self.names[pathid]
        else:
            k = proposal
            i = 2
            while k in self.taken and self.taken[k] != pathid:
                k = "%s_%d" % (proposal, i)
                i += 1
            self.names[pathid] = k
            self.taken[k] = pathid
        if k in self.used:
            fail("key %s named twice" % k)
        self.used.add(k)
        return k

    def save(self):
        if not self.path:
            return
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(collections.OrderedDict(sorted(self.names.items())), fh, indent=1)
            fh.write("\n")


class Walker:
    def __init__(self, cat, module, namer, maps):
        self.cat, self.module, self.namer, self.maps = cat, module, namer, maps
        self.not_mapped = []        # (kind msg name, path, rostype, reason)

    def walk(self, kind, msg, loc, kpath, ppath, desc):
        """loc: locator parts relative to the current scope; kpath: path parts for the
        key name from the kind; ppath: path id text from the kind; desc: dotted path."""
        out = []
        for f in msg.fields:
            l2 = loc + [f.name]
            k2 = kpath + [f.name]
            p2 = ppath + ("." if ppath and not ppath.endswith(".") else "") + f.name
            d2 = desc + "." + f.name
            if f.array is None:
                if f.pkg_ref is None:
                    out.append(self.scalar(kind, f, ".".join(l2), k2, p2, d2, f.rostype))
                else:
                    out.extend(self.walk(kind, self.cat.get(f.pkg_ref, f.base), l2, k2, p2, d2))
                continue
            if f.pkg_ref is None and f.base in BINARY_ARRAYS:
                out.append(FLine(self.key(kind, k2, p2), ".".join(l2), "string", "string",
                                 "%s (%s, base64 text)" % (d2, f.rostype), p2, f.rostype))
                continue
            if f.pkg_ref is None and f.base == "byte":
                self.not_mapped.append((kind.name, d2[len(kind.name) + 1:], f.rostype, R_BYTE_ARRAY))
                continue
            lp = p2 + "[]"
            lkey = self.key(kind, k2, lp)
            if f.pkg_ref is None:
                kt, tr = PRIMITIVES[f.base]
                ip = lp + "."
                ikey = self.key(kind, k2 + ["value"], ip)
                body = [FLine(ikey, ".", tr, kt, "%s[] item (%s)" % (d2, f.base), ip, f.base)]
            else:
                sub = self.cat.get(f.pkg_ref, f.base)
                body = self.walk(kind, sub, [], k2, lp + ".", d2 + "[]")
                if not body:
                    self.not_mapped.append((kind.name, d2[len(kind.name) + 1:], f.rostype,
                                            "array of a message with nothing mappable"))
                    continue
            out.append(GLine(lkey, ".".join(l2), body, "%s (%s)" % (d2, f.rostype), lp))
        return out

    def key(self, kind, kpath, pathid):
        return self.namer.name("%s:%s" % (kind.name, pathid), "_".join([slug(kind.name)] + kpath))

    def scalar(self, kind, f, loc, kpath, pathid, desc, rostype):
        kt, tr = PRIMITIVES[f.base]
        shared = self.maps.get((kind.name, pathid))
        if shared:
            return FLine(shared, loc, tr, kt, desc, pathid, rostype)
        return FLine(self.key(kind, kpath, pathid), loc, tr, kt,
                     "%s (%s)" % (desc, rostype), pathid, rostype)


def iter_lines(lines):
    for ln in lines:
        yield ln
        if isinstance(ln, GLine):
            for x in iter_lines(ln.body):
                yield x


class Kind:
    def __init__(self, msg, name, rtype, lines, requires):
        self.msg, self.name, self.rtype, self.lines, self.requires = msg, name, rtype, lines, requires


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------

def qual(module, key):
    return key if "." not in key and key in CORE_KEYS else "%s.%s" % (module, key)


CORE_KEYS = {}


def emit_module(module, pkg, keys, sources):
    a = []
    a.append("# The %s module: raw keys of the ros2-%s format, one per field of a" % (
        module, pkg.replace("_", "-")))
    a.append("# ROS 2 %s message that no core key covers. Generated by" % pkg)
    a.append("# tools/gen/ros2msg2pack.py; edit the generator, not this file.")
    a.append("module        %s" % module)
    a.append("version       %s" % PACK_VERSION)
    a.append("distribution  public")
    for s in sources:
        a.append('source        "%s"' % s)
    w = max(len(k[1]) for k in keys) if keys else 10
    for kind_, name, typ, desc in keys:
        if kind_ == "list":
            a.append('list %-*s          "%s"' % (w, name, desc))
        else:
            a.append('key  %-*s  %-6s  -  "%s"' % (w, name, typ, desc))
    return "\n".join(a) + "\n"


def emit_lines(module, lines, indent):
    out = []
    pad = "  " * indent
    for ln in lines:
        if isinstance(ln, FLine):
            out.append("%sfield  %s  %s  %s" % (pad, qual(module, ln.key), ln.loc, ln.transform))
        else:
            out.append("%sgroup  %s  %s" % (pad, qual(module, ln.key), ln.loc))
            out.extend(emit_lines(module, ln.body, indent + 1))
            out.append("%send" % pad)
    return out


def emit_pack(fmt, module, pkg, kinds, sources):
    a = []
    a.append("# ROS 2 %s messages in the JSON form of a rosbridge `publish` operation." % pkg)
    a.append("# Generated by tools/gen/ros2msg2pack.py; do not edit by hand.")
    a.append('# One kind per .msg file, selected by the member `type` ("<package>/msg/<Name>").')
    a.append("# The ROS message is the object under `msg`; arrays are groups.")
    a.append("format        %s" % fmt)
    a.append("version       %s" % PACK_VERSION)
    a.append("distribution  public")
    for s in sources:
        a.append('source        "%s"' % s)
    a.append("uses          %s" % module)
    a.append("wire          json")
    a.append("when   op  publish")
    a.append("field  %s.topic  topic  string" % module)
    for k in kinds:
        a.append("")
        a.append("kind      %s" % k.name)
        a.append("when      type  %s" % k.rtype)
        a.append("requires  %s" % " ".join(qual(module, r) for r in k.requires))
        a.extend(emit_lines(module, k.lines, 0))
    return "\n".join(a) + "\n"


# --------------------------------------------------------------------------
# JSON text: the canonical form of engine-spec 0.5 (shared by the vector writer
# and the codec below; it is formatting only)
# --------------------------------------------------------------------------

def fmt_float(x):
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        fail("not finite: %r" % x)
    if x == 0:
        return "0"
    s = format(Decimal(repr(x)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_string(s):
    out = ['"']
    for c in s:
        o = ord(c)
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c == "\n":
            out.append("\\n")
        elif c == "\r":
            out.append("\\r")
        elif c == "\t":
            out.append("\\t")
        elif c == "\b":
            out.append("\\b")
        elif c == "\f":
            out.append("\\f")
        elif o < 0x20:
            out.append("\\u%04x" % o)
        else:
            out.append(c)
    out.append('"')
    return "".join(out)


class Num:
    """A JSON number as written: int, or float text."""

    def __init__(self, v, is_float):
        self.v, self.is_float = v, is_float


def dump(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return fmt_float(v)
    if isinstance(v, Decimal):
        return fmt_float(float(v))
    if isinstance(v, str):
        return fmt_string(v)
    if isinstance(v, list):
        return "[" + ",".join(dump(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(fmt_string(k) + ":" + dump(x) for k, x in v.items()) + "}"
    fail("cannot write %r" % (v,))


# --------------------------------------------------------------------------
# Vector values, from the message tree (not from pack.def)
# --------------------------------------------------------------------------

class Sampler:
    def __init__(self, cat):
        self.cat = cat
        self.n = 0

    def scalar(self, base):
        self.n += 1
        n = self.n
        if base == "bool":
            return n % 2 == 1
        if base in INT_RANGE:
            lo, hi = INT_RANGE[base]
            if base in ("int64", "uint64"):
                v = n * 123456789013
                return -v if (base == "int64" and n % 2) else v
            span = hi - lo + 1
            return lo + (n * 40503 + span // 2 + 7) % span
        if base == "float32":
            return (n % 50 - 20.5) * 0.25
        if base == "float64":
            return float("%s%d.%03d" % ("-" if n % 3 == 0 else "", n, n * 7 % 1000))
        if base in ("string", "wstring"):
            return "s%d" % n
        fail("no sample for %s" % base)

    def binary(self):
        self.n += 1
        n = self.n
        return base64.b64encode(bytes([n % 256, (n * 3) % 256, 255, 0, 128])).decode("ascii")

    def count(self, f, depth):
        if f.array[0] in ("fixed", "bounded"):
            return f.array[1]
        return VECTOR_ITEMS_TOP if depth == 0 else VECTOR_ITEMS_NESTED

    def message(self, msg, depth):
        obj = collections.OrderedDict()
        for f in msg.fields:
            if f.array is None:
                if f.pkg_ref is None:
                    obj[f.name] = self.scalar(f.base)
                else:
                    obj[f.name] = self.message(self.cat.get(f.pkg_ref, f.base), depth)
            elif f.pkg_ref is None and f.base in BINARY_ARRAYS:
                obj[f.name] = self.binary()
            elif f.pkg_ref is None and f.base == "byte":
                obj[f.name] = [self.scalar("uint8") for _ in range(2)]    # written, not carried
            elif f.pkg_ref is None:
                obj[f.name] = [self.scalar(f.base) for _ in range(self.count(f, depth))]
            else:
                sub = self.cat.get(f.pkg_ref, f.base)
                obj[f.name] = [self.message(sub, depth + 1) for _ in range(self.count(f, depth))]
        return obj


def carried(msg, obj, cat):
    """The message object as the pack carries it: byte[] dropped, empty objects dropped."""
    out = collections.OrderedDict()
    for f in msg.fields:
        if f.name not in obj or obj[f.name] is None:
            continue
        v = obj[f.name]
        if f.array is None and f.pkg_ref:
            c = carried(cat.get(f.pkg_ref, f.base), v, cat)
            if c:
                out[f.name] = c
        elif f.array is not None and f.pkg_ref is None and f.base == "byte":
            continue
        elif f.array is not None and f.pkg_ref:
            sub = cat.get(f.pkg_ref, f.base)
            out[f.name] = [carried(sub, x, cat) for x in v]
        else:
            out[f.name] = v
    return out


def envelope(kind, topic, msgobj, extra):
    e = collections.OrderedDict()
    e["op"] = "publish"
    if topic is not None:
        e["topic"] = topic
    e["type"] = kind.rtype
    if msgobj:
        e["msg"] = msgobj
    for k, v in extra:
        e[k] = v
    return e


def model_value(v, transform):
    if transform == "bool":
        return "1" if v else "0"
    if transform == "float":
        return fmt_float(v)
    return str(v)


def model_checks(module, kind, obj, limit=5):
    """A few model values of the decoded entity, from the sample object."""
    out = collections.OrderedDict()
    out["@kind"] = kind.name
    n = 0
    for ln in kind.lines:
        v = lookup(obj, ln.loc)
        if v is None:
            continue
        if isinstance(ln, FLine):
            if n < limit:
                out[qual(module, ln.key)] = model_value(v, ln.transform)
                n += 1
        else:
            lk = qual(module, ln.key)
            out[lk + ".#"] = str(len(v))
            if v and isinstance(ln.body[0], FLine) and ln.body[0].loc == ".":
                out["%s[0].%s" % (lk, qual(module, ln.body[0].key))] = model_value(v[0], ln.body[0].transform)
            elif v and isinstance(ln.body[0], FLine):
                iv = lookup(v[0], ln.body[0].loc)
                if iv is not None:
                    out["%s[0].%s" % (lk, qual(module, ln.body[0].key))] = model_value(iv, ln.body[0].transform)
    return out


def lookup(obj, loc):
    cur = obj
    for p in loc.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


# --------------------------------------------------------------------------
# Independent check: parse what was written, then run a json-wire codec
# written from spec/engine-spec.md
# --------------------------------------------------------------------------

def tokens(line, where):
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == "#":
            break
        if c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                fail("%s: unterminated quote" % where)
            out.append(line[i + 1:j])
            i = j + 1
            continue
        j = i
        while j < n and line[j] not in " \t":
            j += 1
        out.append(line[i:j])
        i = j
    return out


def read_module(text, where):
    mod = {"name": None, "keys": {}, "lists": set(), "dist": None, "sources": 0}
    for n, line in enumerate(text.split("\n"), 1):
        t = tokens(line, "%s:%d" % (where, n))
        if not t:
            continue
        d = t[0]
        if d == "module":
            mod["name"] = t[1]
        elif d == "version":
            pass
        elif d == "distribution":
            mod["dist"] = t[1]
        elif d == "source":
            mod["sources"] += 1
        elif d == "key":
            if len(t) not in (4, 5) or t[2] not in ("string", "float", "int") or "." in t[1]:
                fail("%s:%d: bad key line" % (where, n))
            if t[1] in mod["keys"] or t[1] in mod["lists"]:
                fail("%s:%d: duplicate-key %s" % (where, n, t[1]))
            mod["keys"][t[1]] = t[2]
        elif d == "list":
            if len(t) not in (2, 3) or "." in t[1]:
                fail("%s:%d: bad list line" % (where, n))
            if t[1] in mod["keys"] or t[1] in mod["lists"]:
                fail("%s:%d: duplicate-key %s" % (where, n, t[1]))
            mod["lists"].add(t[1])
        elif d in ("derive", "uses"):
            pass
        else:
            fail("%s:%d: unknown directive %s" % (where, n, d))
    if mod["dist"] != "public" or not mod["sources"]:
        fail("%s: distribution public and a source are required" % where)
    return mod


YIELDS = {"string": "string", "float": "float", "int": "int", "bool": "int", "iso8601_ms": "int"}


class Pack:
    pass


def read_pack(text, where, modules):
    p = Pack()
    p.format = p.wire = p.dist = None
    p.sources = 0
    p.uses = ["core"]
    p.common = []           # lines: ("when", loc, value) | ("field", key, loc, tr) | ("group", key, loc, body)
    p.kinds = collections.OrderedDict()
    cur = p.common
    stack = []
    kreq = None
    for n, line in enumerate(text.split("\n"), 1):
        w = "%s:%d" % (where, n)
        t = tokens(line, w)
        if not t:
            continue
        d = t[0]
        if d in ("format", "version", "distribution", "source", "uses", "wire"):
            if stack or p.kinds and d != "source":
                fail("%s: %s after a kind or inside a group" % (w, d))
            if len(t) != 2:
                fail("%s: %s takes one argument" % (w, d))
            if d == "format":
                p.format = t[1]
            elif d == "distribution":
                p.dist = t[1]
            elif d == "source":
                p.sources += 1
            elif d == "uses":
                p.uses.append(t[1])
            elif d == "wire":
                p.wire = t[1]
        elif d == "kind":
            if stack:
                fail("%s: kind inside a group" % w)
            if t[1] in p.kinds:
                fail("%s: duplicate-kind %s" % (w, t[1]))
            kreq = []
            p.kinds[t[1]] = {"lines": [], "requires": kreq}
            cur = p.kinds[t[1]]["lines"]
        elif d == "when":
            if stack or len(t) != 3:
                fail("%s: bad when" % w)
            cur.append(("when", t[1], t[2]))
        elif d == "requires":
            if kreq is None or stack:
                fail("%s: bad-directive requires" % w)
            kreq.extend(t[1:])
        elif d == "field":
            if len(t) != 4:
                fail("%s: field takes three arguments" % w)
            cur.append(("field", t[1], t[2], t[3]))
        elif d == "group":
            if len(t) != 3:
                fail("%s: group takes two arguments here" % w)
            body = []
            cur.append(("group", t[1], t[2], body))
            stack.append(cur)
            cur = body
        elif d == "end":
            if not stack:
                fail("%s: end with no open group" % w)
            cur = stack.pop()
        else:
            fail("%s: unknown directive %s" % (w, d))
    if stack:
        fail("%s: group with no end" % where)
    if p.dist != "public" or not p.sources:
        fail("%s: distribution public and a source are required" % where)
    if p.wire != "json":
        fail("%s: wire json expected" % where)
    for u in p.uses:
        if u not in modules:
            fail("%s: unknown-module %s" % (where, u))

    def resolve(key):
        mod, name = ("core", key) if "." not in key else key.split(".", 1)
        if mod not in p.uses:
            fail("%s: module-not-used %s" % (where, key))
        return modules[mod], name

    def check(lines):
        for ln in lines:
            if ln[0] == "field":
                m, name = resolve(ln[1])
                if name in m["lists"]:
                    fail("%s: key-type-mismatch (field on list %s)" % (where, ln[1]))
                if name not in m["keys"]:
                    fail("%s: undeclared-key %s" % (where, ln[1]))
                if ln[3] not in YIELDS or YIELDS[ln[3]] != m["keys"][name]:
                    fail("%s: key-type-mismatch %s %s" % (where, ln[1], ln[3]))
            elif ln[0] == "group":
                m, name = resolve(ln[1])
                if name not in m["lists"]:
                    fail("%s: group on a key that is not a list: %s" % (where, ln[1]))
                if not ln[3]:
                    fail("%s: empty group %s" % (where, ln[1]))
                check(ln[3])
    check(p.common)
    for k in p.kinds.values():
        check(k["lines"])
        for r in k["requires"]:
            m, name = resolve(r)
            if name not in m["keys"] and name not in m["lists"]:
                fail("%s: undeclared-key %s in requires" % (where, r))
    return p


class Fail(Exception):
    """A named engine error: kind is the error name of engine-spec."""

    def __init__(self, kind, detail=""):
        Exception.__init__(self, "%s: %s" % (kind, detail))
        self.kind = kind


def parse_json(text):
    def pairs(items):
        d = collections.OrderedDict()
        for k, v in items:
            if k in d:
                raise Fail("malformed-wire", "member %s twice" % k)
            d[k] = v
        return d

    def const(name):
        raise Fail("malformed-wire", name)
    try:
        v = json.loads(text, object_pairs_hook=pairs, parse_float=Decimal, parse_int=int,
                       parse_constant=const)
    except Fail:
        raise
    except (ValueError, RecursionError) as e:
        raise Fail("malformed-wire", str(e))
    check_depth_and_text(v, 1)
    return v


def check_depth_and_text(v, depth):
    """vector-format, malformed input: at most 64 levels of arrays and objects; a
    string holding half a surrogate pair (json.loads joins a whole pair into one
    character, so any surrogate left is a lone half)."""
    if isinstance(v, (dict, list)):
        if depth > 64:
            raise Fail("malformed-wire", "nesting deeper than 64")
        items = v.items() if isinstance(v, dict) else enumerate(v)
        for k, x in items:
            if isinstance(k, str):
                check_depth_and_text(k, depth)
            check_depth_and_text(x, depth + 1)
    elif isinstance(v, str):
        if any(0xD800 <= ord(c) <= 0xDFFF for c in v):
            raise Fail("malformed-wire", "lone surrogate")


def is_num(v):
    return isinstance(v, (int, Decimal)) and not isinstance(v, bool)


def get_path(obj, loc):
    cur = obj
    for p in loc.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def canon_text(v):
    """A wire scalar as canonical text, for `when` comparison."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, Decimal):
        return fmt_float(float(v))
    return v


def when_holds(obj, loc, value):
    v = get_path(obj, loc)
    if value.startswith("="):
        value = value[1:]
    elif value == "present":
        return v is not None
    if isinstance(v, str):
        return v == value
    if is_num(v) or isinstance(v, bool):
        return canon_text(v) == value
    return False


def decode_value(v, tr, where):
    if v is None:
        return None
    if tr == "string":
        if not isinstance(v, str):
            raise Fail("transform-decode", where)
        return v
    if tr == "float":
        if not is_num(v):
            raise Fail("transform-decode", where)
        return float(v)
    if tr == "int":
        if not is_num(v):
            raise Fail("transform-decode", where)
        d = Decimal(v)
        if d != d.to_integral_value():
            raise Fail("transform-decode", where)
        i = int(d)
        if not -2 ** 63 <= i < 2 ** 63:
            raise Fail("transform-decode", where)
        return i
    if tr == "bool":
        if not isinstance(v, bool):
            raise Fail("transform-decode", where)
        return 1 if v else 0
    fail("transform %s not in this codec" % tr)


class Entity:
    def __init__(self):
        self.keys = collections.OrderedDict()
        self.lists = collections.OrderedDict()
        self.residue = []           # (path, value)
        self.kind = None
        self.fmt = None             # the format the residue belongs to


def decode_lines(obj, lines, ent, mapped, prefix):
    for ln in lines:
        if ln[0] == "when":
            if ln[2] != "present":
                mapped.add(prefix + ln[1])
        elif ln[0] == "field":
            mapped.add(prefix + ln[2])
            v = get_path(obj, ln[2]) if ln[2] != "." else obj
            val = decode_value(v, ln[3], ln[2])
            if val is not None and ln[1] not in ent.keys:
                ent.keys[ln[1]] = val
        elif ln[0] == "group":
            mapped.add(prefix + ln[2])
            v = get_path(obj, ln[2])
            if v is None:
                continue
            if not isinstance(v, list):
                raise Fail("malformed-wire", "%s is not an array" % ln[2])
            items = []
            scalar = all(x[0] == "field" and x[2] == "." for x in ln[3])
            for el in v:
                item = Entity()
                if scalar:
                    if isinstance(el, (dict, list)):
                        raise Fail("transform-decode", "item of %s" % ln[2])
                    decode_lines(el, ln[3], item, set(), "")
                elif isinstance(el, dict):
                    decode_lines(el, ln[3], item, set(), "")
                items.append(item)
            ent.lists[ln[1]] = items


def collect_residue(obj, mapped, prefix, out):
    for k, v in obj.items():
        if "." in k:
            continue
        p = prefix + k
        if isinstance(v, dict):
            collect_residue(v, mapped, p + ".", out)
        elif isinstance(v, list) or v is None:
            continue
        elif p not in mapped:
            out.append((p, v))


def json_decode(pack, text):
    obj = parse_json(text)
    if not isinstance(obj, dict):
        raise Fail("malformed-wire", "not an object")
    for ln in pack.common:
        if ln[0] == "when" and not when_holds(obj, ln[1], ln[2]):
            raise Fail("no-kind", "common when %s" % ln[1])
    kname = None
    for name, k in pack.kinds.items():
        if all(when_holds(obj, ln[1], ln[2]) for ln in k["lines"] if ln[0] == "when"):
            kname = name
            break
    if kname is None and pack.kinds:
        raise Fail("no-kind", "no kind")
    ent = Entity()
    ent.kind = (pack.format, kname) if kname else None
    ent.fmt = pack.format
    mapped = set()
    failed = []
    for lines in (pack.common, pack.kinds[kname]["lines"] if kname else []):
        try:
            decode_lines(obj, lines, ent, mapped, "")
        except Fail as e:
            if e.kind != "transform-decode":
                raise
            failed.append(e)
    if failed:
        raise failed[0]
    collect_residue(obj, mapped, "", ent.residue)
    return ent


def when_value(value):
    if value.startswith("="):
        return value[1:]
    if value in ("true", "false"):
        return value == "true"
    if re.match(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$", value):
        return Decimal(value) if re.search(r"[.eE]", value) else int(value)
    return value


def place(obj, loc):
    """Make the objects on the way to loc, in order; return (parent, member)."""
    parts = loc.split(".")
    cur = obj
    for p in parts[:-1]:
        if cur.get(p) is None:
            cur[p] = collections.OrderedDict()
        if not isinstance(cur[p], dict):
            raise Fail("transform-encode", "%s is written as a value and as an object" % loc)
        cur = cur[p]
    if parts[-1] not in cur:
        cur[parts[-1]] = None       # a slot; filled or removed later
    return cur, parts[-1]


def encode_value(v, tr):
    if tr == "bool":
        if v not in (0, 1):
            raise Fail("transform-encode", "bool %r" % v)
        return v == 1
    if tr == "float":
        return float(v)
    if tr == "int":
        return int(v)
    return v


def encode_lines(obj, lines, keys, lists):
    for ln in lines:
        if ln[0] == "when":
            par, m = place(obj, ln[1])
            par[m] = when_value(ln[2])
        elif ln[0] == "field":
            if ln[2] == ".":
                continue
            par, m = place(obj, ln[2])
            if ln[1] in keys and par[m] is None:
                par[m] = encode_value(keys[ln[1]], ln[3])
        elif ln[0] == "group":
            par, m = place(obj, ln[2])
            if ln[1] in lists:
                arr = []
                scalar = all(x[0] == "field" and x[2] == "." for x in ln[3])
                for it in lists[ln[1]]:
                    if scalar:
                        x = ln[3][0]
                        arr.append(encode_value(it.keys[x[1]], x[3]) if x[1] in it.keys else None)
                    else:
                        o = collections.OrderedDict()
                        encode_lines(o, ln[3], it.keys, it.lists)
                        arr.append(prune(o) or collections.OrderedDict())
                par[m] = arr


def prune(obj):
    out = collections.OrderedDict()
    for k, v in obj.items():
        if isinstance(v, dict):
            v = prune(v)
            if not v:
                continue
        elif v is None:
            continue
        out[k] = v
    return out


def json_encode(pack, ent):
    if not pack.kinds:
        kname = None
    elif ent.kind and ent.kind[0] == pack.format:
        kname = ent.kind[1]
        if kname not in pack.kinds:
            raise Fail("no-kind", kname)
    else:
        kname = None
        for name, k in pack.kinds.items():
            ok = True
            for r in k["requires"]:
                if r in ent.lists:
                    ok = ok and len(ent.lists[r]) > 0
                else:
                    ok = ok and r in ent.keys
            if ok:
                kname = name
                break
        if kname is None:
            raise Fail("no-kind", "no kind qualifies")
    obj = collections.OrderedDict()
    # mapped members and when members in line order, common first
    order = pack.common + (pack.kinds[kname]["lines"] if kname else [])
    whens = [ln for ln in order if ln[0] == "when" and ln[2] != "present"]
    for ln in order:
        if ln[0] == "when":
            if ln[2] != "present":
                par, m = place(obj, ln[1])
        else:
            encode_lines(obj, [ln], ent.keys, ent.lists)
    for ln in whens:                    # when values are written over any field
        par, m = place(obj, ln[1])
        par[m] = when_value(ln[2])
    if ent.fmt == pack.format:           # residue is per format
        for path, v in ent.residue:
            par, m = place(obj, path)
            if par[m] is None:
                par[m] = v
    return dump(prune(obj))


def geojson_pack(text):
    lines = []
    for line in text.split("\n"):
        t = tokens(line, "geojson")
        if t and t[0] == "field":
            lines.append((t[1], t[2], t[3]))
    return lines


def geojson_decode(glines, text):
    obj = parse_json(text)
    ent = Entity()
    geom = obj.get("geometry")
    coords = geom.get("coordinates") if isinstance(geom, dict) else None
    for key, loc, tr in glines:
        if loc.startswith("geometry."):
            i = {"lon": 0, "lat": 1, "alt": 2}[loc.split(".")[1]]
            if coords and len(coords) > i:
                ent.keys[key] = float(coords[i])
        elif loc.startswith("properties."):
            v = (obj.get("properties") or {}).get(loc.split(".", 1)[1])
            if v is not None:
                ent.keys[key] = decode_value(v, tr, loc)
        else:
            v = obj.get(loc)
            if v is not None:
                ent.keys[key] = decode_value(v, tr, loc)
    return ent


def geojson_encode(glines, ent):
    if "lat" in ent.keys and "lon" in ent.keys:
        c = [ent.keys["lon"], ent.keys["lat"]]
        if "hae" in ent.keys:
            c.append(ent.keys["hae"])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(fmt_float(x) for x in c)
    else:
        geom = "null"
    props, top = [], []
    for key, loc, tr in glines:
        if key not in ent.keys or loc.startswith("geometry."):
            continue
        v = encode_value(ent.keys[key], tr)
        if loc.startswith("properties."):
            props.append(fmt_string(loc.split(".", 1)[1]) + ":" + dump(v))
        else:
            top.append(fmt_string(loc) + ":" + dump(v))
    s = '{"type":"Feature","geometry":%s,"properties":{%s}' % (geom, ",".join(props))
    if top:
        s += "," + ",".join(top)
    return s + "}"


def model_get(ent, key):
    m = re.match(r"^([^\[]+)\[(\d+)\]\.(.+)$", key)
    if m:
        lst = ent.lists.get(m.group(1))
        if lst is None or int(m.group(2)) >= len(lst):
            return "<none>"
        return model_get(lst[int(m.group(2))], m.group(3))
    if key.endswith(".#"):
        lst = ent.lists.get(key[:-2])
        return "absent" if lst is None else str(len(lst))
    if key not in ent.keys:
        return "<none>"
    return ent.keys[key]


def model_equal(got, want):
    if isinstance(got, float):
        try:
            return abs(got - float(want)) <= 1e-9
        except ValueError:
            return False
    return str(got) == want


def check_vector(vec, packs, glines, where):
    src, dst = vec["from"], vec["to"]
    try:
        if src == "geojson":
            ent = geojson_decode(glines, vec["input"])
        else:
            ent = json_decode(packs[src], vec["input"])
        if "model" in vec:
            for k, want in vec["model"].items():
                if k == "@kind":
                    if not ent.kind or ent.kind[1] != want:
                        fail("%s: @kind %r, want %r" % (where, ent.kind, want))
                    continue
                got = model_get(ent, k)
                if not model_equal(got, want):
                    fail("%s: model %s = %r, want %r" % (where, k, got, want))
        if src != dst:
            ent.kind = None
        out = geojson_encode(glines, ent) if dst == "geojson" else json_encode(packs[dst], ent)
    except Fail as e:
        if vec.get("expect_error") == e.kind:
            return
        fail("%s: %s" % (where, e))
    if "expect_error" in vec:
        fail("%s: converted, want error %s" % (where, vec["expect_error"]))
    if out != vec["expect"]:
        fail("%s:\n got    %s\n expect %s" % (where, out, vec["expect"]))


# --------------------------------------------------------------------------
# Vectors
# --------------------------------------------------------------------------

def vec_obj(name, src, dst, inp, expect=None, model=None, error=None, source=None):
    v = collections.OrderedDict()
    v["name"] = name
    v["from"] = src
    v["to"] = dst
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


SRC_RT = ("tools/gen/ros2msg2pack.py: values chosen by the generator from the .msg field types; "
          "input written in the field order of the .msg file, which is the order rosbridge "
          "writes; expect is that text with byte[] arrays and empty objects removed")


def roundtrip_vectors(fmt, module, kinds, cat):
    out = []
    for k in kinds:
        s = Sampler(cat)
        obj = s.message(k.msg, 0)
        inp = dump(envelope(k, "/gen/%s" % k.name, obj, [("id", "gen-%s" % k.name)]))
        exp = dump(envelope(k, "/gen/%s" % k.name, carried(k.msg, obj, cat),
                            [("id", "gen-%s" % k.name)]))
        model = model_checks(module, k, {"msg": obj})
        model["%s.topic" % module] = "/gen/%s" % k.name
        out.append(("gen-rt-%s.json" % k.name.replace("_", "-"),
                    vec_obj("rt-%s" % k.name, fmt, fmt, inp, exp, model, source=SRC_RT)))
    return out


def special_vectors(pkg, fmt, module, kinds, cat):
    """Edge and error cases; each states where its expected value comes from."""
    by = {k.msg.name: k for k in kinds}
    out = []

    def add(fname, name, inp, expect=None, model=None, error=None, why=None, dst=None):
        out.append((fname, vec_obj(name, fmt, dst or fmt, inp, expect, model, error, why)))
    m = module
    if pkg == "std_msgs":
        add("gen-edge-string-escapes.json", "edge-string-escapes",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/String","msg":{"data":"q\\"b\\\\n\\nt\\tc\\u0001e\\u00e9s\\/"}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/String","msg":{"data":"q\\"b\\\\n\\nt\\tc\\u0001eés/"}}',
            {"@kind": "string", m + ".string_data": 'q"b\\n\nt\tc\x01eés/'},
            why="engine-spec 0.5, json canonical output: escape quote, backslash and controls; "
                "other characters as UTF-8; \\/ and \\u00e9 on input are read as / and e-acute")
        add("gen-edge-int64-beyond-double.json", "edge-int64-beyond-double",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int64","msg":{"data":9007199254740993}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int64","msg":{"data":9007199254740993}}',
            {"@kind": "int64", m + ".int64_data": "9007199254740993"},
            why="2^53+1 is an int64 value rosbridge writes as a JSON integer; the model int is 64-bit")
        add("gen-edge-int64-extremes.json", "edge-int64-extremes",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int64MultiArray","msg":{"layout":{"dim":[],"data_offset":0},"data":[-9223372036854775808,9223372036854775807]}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int64MultiArray","msg":{"layout":{"dim":[],"data_offset":0},"data":[-9223372036854775808,9223372036854775807]}}',
            {"@kind": "int64_multi_array", m + ".int64_multi_array_layout_dim.#": "0",
             m + ".int64_multi_array_data.#": "2",
             m + ".int64_multi_array_data[1]." + m + ".int64_multi_array_data_value": "9223372036854775807"},
            why="the int64 range ends; an empty array is a present empty list and is written []")
        add("gen-edge-float-plain-notation.json", "edge-float-plain-notation",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Float64MultiArray","msg":{"layout":{"dim":[{"label":"x","size":2,"stride":2}],"data_offset":0},"data":[1e-07,2.0,-0.0,1.5E+3]}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Float64MultiArray","msg":{"layout":{"dim":[{"label":"x","size":2,"stride":2}],"data_offset":0},"data":[0.0000001,2,0,1500]}}',
            {"@kind": "float64_multi_array", m + ".float64_multi_array_data.#": "4"},
            why="engine-spec 0.1.1 ruling 3: shortest round-trip decimal, plain notation, "
                "integral floats without a point, negative zero as 0")
        add("gen-edge-int-written-as-float.json", "edge-int-written-as-float",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int32","msg":{"data":5.0}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int32","msg":{"data":5}}',
            {"@kind": "int32", m + ".int32_data": "5"},
            why="engine-spec 0.5 ruling 12: int accepts any integral number")
        add("gen-edge-bool-false.json", "edge-bool-false",
            '{"op":"publish","type":"std_msgs/msg/Bool","msg":{"data":false}}',
            '{"op":"publish","type":"std_msgs/msg/Bool","msg":{"data":false}}',
            {"@kind": "bool", m + ".bool_data": "0"},
            why="engine-spec 0.5, transform bool: false is 0 and is written false; no topic, none written")
        add("gen-edge-unknown-member-is-residue.json", "edge-unknown-member-is-residue",
            '{ "msg" : {"data":"x","note":"kept"}, "type":"std_msgs/msg/String", "op":"publish", "id":"a1", "qos":{"depth":10,"reliability":"reliable"}, "topic":"/t" }',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/String","msg":{"data":"x","note":"kept"},"id":"a1","qos":{"depth":10,"reliability":"reliable"}}',
            {"@kind": "string", m + ".string_data": "x", m + ".topic": "/t"},
            why="engine-spec 0.5, json residue and canonical order: mapped and when members in "
                "line order, then residue of each object in input order")
        add("gen-edge-byte-array-dropped.json", "edge-byte-array-dropped",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/ByteMultiArray","msg":{"layout":{"dim":[],"data_offset":3},"data":[1,2]}}',
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/ByteMultiArray","msg":{"layout":{"dim":[],"data_offset":3}}}',
            {"@kind": "byte_multi_array", m + ".byte_multi_array_layout_data_offset": "3"},
            why="byte[] is not mapped (pack.md); arrays are not residue (engine-spec 0.5)")
        add("gen-err-no-type.json", "err-no-type",
            '{"op":"publish","topic":"/t","msg":{"data":"x"}}', error="no-kind",
            why="a publish with no type member selects no kind (pack.md, message convention)")
        add("gen-err-short-type-form.json", "err-short-type-form",
            '{"op":"publish","topic":"/t","type":"std_msgs/String","msg":{"data":"x"}}', error="no-kind",
            why="the pack selects by the full form <package>/msg/<Name> only (pack.md)")
        add("gen-err-op-not-publish.json", "err-op-not-publish",
            '{"op":"advertise","topic":"/t","type":"std_msgs/msg/String"}', error="no-kind",
            why="the common when op publish does not hold")
        add("gen-err-string-of-wrong-type.json", "err-string-of-wrong-type",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/String","msg":{"data":5}}',
            error="transform-decode", why="engine-spec 0.5: a value of the wrong JSON type")
        add("gen-err-bool-as-number.json", "err-bool-as-number",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Bool","msg":{"data":1}}',
            error="transform-decode", why="engine-spec 0.5: bool reads true and false only")
        add("gen-err-int-with-fraction.json", "err-int-with-fraction",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Int8","msg":{"data":1.5}}',
            error="transform-decode", why="engine-spec 0.5: int needs an integral number")
        add("gen-err-array-not-an-array.json", "err-array-not-an-array",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/Float32MultiArray","msg":{"data":"x"}}',
            error="malformed-wire", why="engine-spec 0.7, decode: a group member that is not an array")
        add("gen-err-truncated.json", "err-truncated",
            '{"op":"publish","topic":"/t","type":"std_msgs/msg/String","msg":{"data":"x"',
            error="malformed-wire", why="vector-format, malformed input: the input ends inside an object")
        add("gen-err-duplicate-member.json", "err-duplicate-member",
            '{"op":"publish","op":"publish","type":"std_msgs/msg/String","msg":{"data":"x"}}',
            error="malformed-wire", why="engine-spec 0.5 ruling 22: one member name twice")
    if pkg == "sensor_msgs" and "NavSatFix" in by:
        hdr = '"header":{"stamp":{"sec":1700000000,"nanosec":250000000},"frame_id":"gps"}'
        cov = '[1.5,0,0,0,1.5,0,0,0,4]'
        add("gen-edge-navsatfix-rosbridge-text.json", "edge-navsatfix-rosbridge-text",
            '{"msg": {%s, "status": {"status": 0, "service": 1}, "latitude": 48.1372, '
            '"longitude": 11.5756, "altitude": 519.0, "position_covariance": '
            '[1.5, 0.0, 0.0, 0.0, 1.5, 0.0, 0.0, 0.0, 4.0], "position_covariance_type": 2}, '
            '"op": "publish", "topic": "/fix", "type": "sensor_msgs/msg/NavSatFix"}' % hdr.replace(":", ": "),
            '{"op":"publish","topic":"/fix","type":"sensor_msgs/msg/NavSatFix","msg":{%s,"status":{"status":0,"service":1},'
            '"latitude":48.1372,"longitude":11.5756,"altitude":519,"position_covariance":%s,'
            '"position_covariance_type":2}}' % (hdr, cov),
            {"@kind": "nav_sat_fix", "lat": "48.1372", "lon": "11.5756", "hae": "519",
             m + ".nav_sat_fix_position_covariance.#": "9"},
            why="Python json text as rosbridge writes it (spaces, 0.0 and 519.0); canonical output "
                "per engine-spec 0.5")
        add("gen-x-navsatfix-to-geojson.json", "x-navsatfix-to-geojson",
            '{"op":"publish","topic":"/fix","type":"sensor_msgs/msg/NavSatFix","msg":{%s,"status":{"status":0,"service":1},'
            '"latitude":48.1372,"longitude":11.5756,"altitude":519.25,"position_covariance":%s,'
            '"position_covariance_type":2}}' % (hdr, cov),
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5756,48.1372,519.25]},"properties":{}}',
            {"@kind": "nav_sat_fix", "lat": "48.1372", "lon": "11.5756", "hae": "519.25"},
            dst="geojson",
            why="latitude, longitude and altitude are core lat, lon, hae (pack.md); geojson writes "
                "[lon, lat, alt] (RFC 7946, engine-spec 0.1.1 ruling 4); no other key of this kind is a geojson key")
        add("gen-x-navsatfix-no-altitude-to-geojson.json", "x-navsatfix-no-altitude-to-geojson",
            '{"op":"publish","topic":"/fix","type":"sensor_msgs/msg/NavSatFix","msg":{"status":{"status":-1,"service":0},'
            '"latitude":-33.75,"longitude":151.25,"altitude":null,"position_covariance_type":0}}',
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[151.25,-33.75]},"properties":{}}',
            {"@kind": "nav_sat_fix", "lat": "-33.75", "lon": "151.25"},
            dst="geojson",
            why="rosbridge writes a NaN altitude (no altitude available) as null; null is absent "
                "(engine-spec 0.5), so the point has two coordinates")
        add("gen-err-navsatfix-latitude-text.json", "err-navsatfix-latitude-text",
            '{"op":"publish","topic":"/fix","type":"sensor_msgs/msg/NavSatFix","msg":{"latitude":"48.1","longitude":11.5}}',
            error="transform-decode", why="engine-spec 0.5: a value of the wrong JSON type")
    return out


def geojson_cross_vectors(fmt, pkg, kinds):
    by = {k.msg.name: k for k in kinds}
    out = []
    if pkg == "sensor_msgs" and "NavSatFix" in by:
        out.append(("gen-geojson-to-%s-navsatfix.json" % fmt, vec_obj(
            "gen-geojson-to-%s-navsatfix" % fmt, "geojson", fmt,
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[11.5756,48.1372,519.25]},'
            '"properties":{"callsign":"ROVER"},"id":"r-1"}',
            '{"op":"publish","type":"sensor_msgs/msg/NavSatFix","msg":{"latitude":48.1372,"longitude":11.5756,"altitude":519.25}}',
            {"lat": "48.1372", "lon": "11.5756", "hae": "519.25", "uid": "r-1"},
            source="tools/gen/ros2msg2pack.py: the kind is chosen by requires lat lon (the first kind "
                   "whose requires the entity holds); op and type are its when values; uid and callsign "
                   "have no line in the pack and are not written; no topic is known")))
        out.append(("gen-geojson-to-%s-no-position.json" % fmt, vec_obj(
            "gen-geojson-to-%s-no-position" % fmt, "geojson", fmt,
            '{"type":"Feature","geometry":null,"properties":{"callsign":"ROVER"},"id":"r-1"}',
            error="no-kind",
            source="no kind of the pack has its requires held by uid and callsign")))
    return out


CROSS_POINT = {"lat": 47.0625, "lon": 8.53125, "hae": 431.5}    # exact in binary


def set_path(obj, loc, value):
    parts = loc.split(".")[1:]          # the locator starts at the envelope's `msg`
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, collections.OrderedDict())
    cur[parts[-1]] = value


def generic_cross(fmt, module, kinds, cat, names):
    """Vectors for kinds bound to core lat/lon (and hae): to geojson from a full sample
    message, and from geojson into the kind the pack's requires select."""
    by = {k.msg.name: k for k in kinds}
    out, gout = [], []
    for name in names:
        if name not in by:
            fail("--cross %s: no such kind in %s" % (name, fmt))
        k = by[name]
        bound = [x for x in k.lines if isinstance(x, FLine) and x.key in CORE_KEYS]
        if {x.key for x in bound} - set(CROSS_POINT) or not {"lat", "lon"} <= {x.key for x in bound}:
            fail("--cross %s: binds %s; only lat, lon, hae are handled" % (name, [x.key for x in bound]))
        obj = Sampler(cat).message(k.msg, 0)
        for x in bound:
            set_path(obj, x.loc, CROSS_POINT[x.key])
        inp = dump(envelope(k, "/geo", obj, []))
        coords = [CROSS_POINT["lon"], CROSS_POINT["lat"]] + (
            [CROSS_POINT["hae"]] if any(x.key == "hae" for x in bound) else [])
        exp = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s]},"properties":{}}' % (
            ",".join(fmt_float(c) for c in coords))
        model = collections.OrderedDict([("@kind", k.name)])
        for x in bound:
            model[x.key] = fmt_float(CROSS_POINT[x.key])
        out.append(("gen-x-%s-to-geojson.json" % k.name.replace("_", "-"), vec_obj(
            "x-%s-to-geojson" % k.name, fmt, "geojson", inp, exp, model,
            source="tools/gen/ros2msg2pack.py: a full sample message with the bound fields set to "
                   "a point; latitude, longitude and altitude are core lat, lon, hae (pack.md); "
                   "geojson writes [lon, lat, alt] (RFC 7946, engine-spec 0.1.1 ruling 4)")))
    # from geojson: uid, lat, lon, hae and callsign; the first kind whose requires hold
    have = {"uid", "lat", "lon", "hae", "callsign"}
    sel = next((k for k in kinds if set(k.requires) <= have), None)
    if sel is not None:
        msgobj = collections.OrderedDict()
        for x in sel.lines:
            if isinstance(x, FLine) and x.key in CROSS_POINT:
                set_path(msgobj, x.loc, CROSS_POINT[x.key])
        exp = dump(envelope(sel, None, msgobj, []))
        gout.append(("gen-geojson-to-%s-%s.json" % (fmt, sel.name.replace("_", "-")), vec_obj(
            "gen-geojson-to-%s-%s" % (fmt, sel.name), "geojson", fmt,
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s,%s,%s]},'
            '"properties":{"callsign":"ROVER"},"id":"r-1"}' % tuple(
                fmt_float(CROSS_POINT[c]) for c in ("lon", "lat", "hae")),
            exp, {"lat": fmt_float(CROSS_POINT["lat"]), "uid": "r-1"},
            source="tools/gen/ros2msg2pack.py: the kind is the first in pack order whose requires "
                   "the entity holds (%s); op and type are its when values; uid and callsign have "
                   "no line in the pack; no topic is known" % " ".join(sel.requires))))
    return out, gout


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def emit_provenance(args, fmt, pkg, files):
    a = []
    a.append("# Provenance of %s" % fmt)
    a.append("")
    a.append("Generated by `tools/gen/ros2msg2pack.py` (run by `tools/gen/ros2-run.sh`). No")
    a.append("source file is copied into this repository: the generator reads field names,")
    a.append("types, array forms and constant names from the .msg files, and the JSON")
    a.append("representation from the rosbridge protocol. Descriptions in the pack and the")
    a.append("module are composed by the generator. Date read: %s." % args.date_read)
    a.append("")
    a.append("## Repositories")
    a.append("")
    a.append("| Repository | Address | Tag or branch | Commit |")
    a.append("|---|---|---|---|")
    repos = sorted({r for r, _ in files} | {"rosbridge_suite"})
    for r in repos:
        a.append("| %s | %s | %s | `%s` |" % (r, REPO_URL[r], args.ref[r], args.commit[r]))
    a.append("")
    a.append("Each file is `https://raw.githubusercontent.com/<owner>/<repository>/<commit>/<path>`.")
    a.append("")
    a.append("## Files")
    a.append("")
    a.append("| Repository | Path | SHA-256 |")
    a.append("|---|---|---|")
    for r, rel in files:
        a.append("| %s | `%s` | `%s` |" % (r, rel, sha256(os.path.join(args.src, r, rel))))
    a.append("")
    a.append("## Licenses, as the sources state them")
    a.append("")
    if {"common_interfaces", "rcl_interfaces"} & set(repos):
        a.append("- common_interfaces and rcl_interfaces: each package directory of common_interfaces")
        a.append("  holds a `LICENSE` file, and rcl_interfaces holds one at its root, that begins")
        a.append('  "Apache License / Version 2.0, January 2004" and is the full text of the Apache')
        a.append("  License, Version 2.0. Each package's `package.xml` states")
        a.append("  `<license>Apache License 2.0</license>`. The .msg files carry no header.")
    for r, note in LICENSE_NOTES.items():
        if r in repos:
            a.append("- %s: %s" % (r, note))
    a.append("- rosbridge_suite: `LICENSE` at the root begins \"BSD 3-Clause License\" and")
    a.append('  "Copyright (c) The Rosbridge Authors"; `message_conversion.py` carries the header')
    a.append('  "Software License Agreement (BSD License)", "Copyright (c) 2012, Willow Garage, Inc."')
    a.append("  The protocol text `ROSBRIDGE_PROTOCOL.md` (rosbridge v2.1.0 Protocol")
    a.append("  Specification) is in the same repository under that license.")
    a.append("")
    a.append("No source carries a distribution statement, handling marking, export-control")
    a.append("notice or proprietary notice.")
    return "\n".join(a) + "\n"


def emit_pack_md(fmt, module, pkg, kinds, walker, consts, defaults, stats, notes, n_vec, cross,
                 pkg_msgs):
    a = []
    a.append("# %s" % fmt)
    a.append("")
    a.append("ROS 2 `%s` messages as the JSON of a rosbridge `publish` operation. Generated by" % pkg)
    a.append("`tools/gen/ros2msg2pack.py` from the .msg files of the package (and the files")
    a.append("they refer to); do not edit by hand, run `tools/gen/ros2-run.sh`.")
    a.append("")
    a.append("## Why the `json` wire")
    a.append("")
    a.append("Inside ROS 2 a message is serialized as CDR by the middleware (and stored so by")
    a.append("rosbag2). A program outside ROS most often meets it as the JSON that rosbridge")
    a.append("publishes. rosbridge writes a message as one JSON object: each field a member")
    a.append("under its .msg name, a nested message an object, an array a JSON array,")
    a.append("`uint8[]` and `char[]` a base64 string (protocol section 3.1),")
    a.append("`builtin_interfaces/Time` and `Duration` an object `{sec, nanosec}`, and a float")
    a.append("that is NaN or infinite `null`. Every one of those maps to the `json` wire")
    a.append("(engine-spec 0.5, 0.7) with no addition to the pack language, for every message")
    a.append("of the package. CDR on the `bits` wire is not written: a CDR payload carries no")
    a.append("type, so no `when` can tell one message from another and each message would be")
    a.append("a format of its own; and a message with a string or an unbounded array places")
    a.append("every later field at an offset that depends on that length and its alignment,")
    a.append("which `layout sequential` has no line for (`align` is relative to the field")
    a.append("before it, not to a variable start).")
    a.append("")
    a.append("## Message convention")
    a.append("")
    a.append("A message is one rosbridge `publish` operation (protocol v2.1.0, section 4.3.3)")
    a.append("that carries the optional `type` member in the full notation of section 4.1:")
    a.append("")
    a.append("```")
    a.append('{"op":"publish","topic":"<topic>","type":"%s/msg/<Name>","msg":{<message>}}' % pkg)
    a.append("```")
    a.append("")
    a.append("- `op` must be `publish` (a common `when`); it is written on encode.")
    a.append("- `type` selects the kind; it is written on encode. The short notation")
    a.append("  `%s/<Name>`, which rosbridge also accepts, selects no kind (`no-kind`)." % pkg)
    a.append("  A `publish` the server sends to a subscriber has no `type`: the receiver adds")
    a.append("  it from its subscription before decoding.")
    a.append("- `topic` is the raw key `%s.topic`." % module)
    a.append("- Other members of the operation (`id`, `qos`, `latch`, `queue_size`) and any")
    a.append("  member of `msg` the pack does not map are residue when they are scalars or")
    a.append("  objects of scalars, and are written back after the mapped members.")
    a.append("- On encode for an entity from another format, the kind is the first, in the")
    a.append("  order below, whose `requires` keys the entity holds. Each kind requires its")
    a.append("  first key (a message with no field requires `%s.topic`)." % module)
    a.append("")
    a.append("## Counts")
    a.append("")
    a.append("| Item | Count |")
    a.append("|---|---|")
    for k, v in stats:
        a.append("| %s | %s |" % (k, v))
    a.append("")
    a.append("## Shared-model keys")
    a.append("")
    if notes:
        a.append(notes.strip())
    else:
        a.append("None. No field of this package is stated in a geodetic frame, in UTC, or with")
        a.append("another meaning a `core` or `track` key has: poses, points, velocities and")
        a.append("covariances are in the frame `header.frame_id` names, and `header.stamp` is ROS")
        a.append("time, which may be simulation time. Every field is a raw key of module")
        a.append("`%s`." % module)
    a.append("")
    a.append("## Kinds")
    a.append("")
    a.append("| Kind | `type` | Fields | Lists | Constants not mapped |")
    a.append("|---|---|---|---|---|")
    for k in kinds:
        nf = sum(1 for x in iter_lines(k.lines) if isinstance(x, FLine))
        nl = sum(1 for x in iter_lines(k.lines) if isinstance(x, GLine))
        a.append("| `%s` | `%s` | %d | %d | %d |" % (k.name, k.rtype, nf, nl, len(consts.get(k.msg.name, []))))
    a.append("")
    a.append("Fields and lists count every line of the kind, the fields of nested messages and")
    a.append("of array items included.")
    a.append("")
    a.append("## Not mapped, and why")
    a.append("")
    a.append("| What | Why |")
    a.append("|---|---|")
    nconst = sum(len(v) for v in consts.values())
    if nconst:
        a.append("| Constants (`uint8 STATUS_FIX = 0` and the like), %d in this package | the "
                 "pack language has no line that names a constant of a field; the value of the "
                 "field is carried as a number |" % nconst)
    a.append("| Default values in the .msg (%s) | not written on encode: rosbridge fills a "
             "field the `msg` omits with its default (protocol 4.3.3), so an absent key needs "
             "no value |" % (", ".join(defaults) if defaults else "none in this package"))
    fixed = sorted({"%s.%s %s" % (m.name, f.name, f.rostype) for m in pkg_msgs for f in m.fields
                    if f.array and f.array[0] in ("fixed", "bounded")})
    if fixed:
        a.append("| Length of a fixed array and bound of a bounded one (%s) | a `json` group has "
                 "no `count` (engine-spec 0.7); any number of items decodes and encodes, and a "
                 "sender that writes another number is not refused |" % ", ".join(fixed))
    bounded = sorted({"%s.%s" % (m.name, f.name) for m in pkg_msgs for f in m.fields if f.bound})
    if bounded:
        a.append("| Bound of a bounded string (%s) | no transform limits a json string's length |"
                 % ", ".join(bounded))
    if any(f.base == "uint64" for m in pkg_msgs for f in m.fields):
        a.append("| `uint64` values above 2^63-1 | a model `int` is a 64-bit signed integer "
                 "(engine-spec 0.5 ruling 2); such a value is outside it |")
    a.append("| NaN and infinite floats | rosbridge writes them `null`; `null` is absent "
             "(engine-spec 0.5), so the key is absent and nothing is written back |")
    if any(f.array and f.base in BINARY_ARRAYS for m in pkg_msgs for f in m.fields):
        a.append("| `uint8[]` and `char[]` sent as a list of numbers | rosbridge accepts that from "
                 "a client (protocol 3.1) but writes base64; the pack reads the base64 string "
                 "only, and a list there is `transform-decode` |")
    a.append("| Members inside an array item that the .msg does not define | engine-spec 0.7: "
             "items carry no residue |")
    empty = [k.msg.name for k in kinds if not k.lines]
    if empty:
        a.append("| `msg` of a message with no field (%s) | encode writes no `msg` member, because "
                 "a nested object with no members is not written (engine-spec 0.5); rosbridge "
                 "requires `msg` |" % ", ".join(empty))
    a.append("| PNG, CBOR and fragment encodings of the protocol (sections 3.2 to 3.5) | other "
             "byte forms of the operation; the pack reads JSON text |")
    for kname, path, rostype, reason in walker.not_mapped:
        a.append("| `%s.%s` (`%s`) | %s |" % (kname, path, rostype, reason))
    a.append("")
    a.append("## Vectors")
    a.append("")
    a.append("`vectors/gen-rt-<kind>.json`: one round trip per kind, every field of the")
    a.append("message present, two items in each unbounded array outside a group and one")
    a.append("inside, the stated number in a fixed or bounded one, and an `id` member as")
    a.append("residue. `gen-edge-*` and `gen-err-*` are edge and error cases, each naming the")
    a.append("rule it rests on in `source`; `gen-x-*` convert to geojson. %d vector files." % n_vec)
    if cross:
        a.append("`packs/geojson/vectors/gen-geojson-to-%s-*.json` convert from geojson." % fmt)
    a.append("Expected text is written by the generator from the .msg field order and checked")
    a.append("by its own json-wire codec; no engine produced it.")
    return "\n".join(a) + "\n"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_maps(items):
    maps = {}
    for it in items or []:
        m = re.match(r"^([a-z_]+)/([A-Za-z0-9]+):([a-z0-9_.]+)=([a-z_.]+)$", it)
        if not m:
            fail("--map %r: want <package>/<Msg>:<field path>=<key>" % it)
        maps.setdefault(m.group(1), {})[(m.group(2), m.group(3))] = m.group(4)
    return maps


def parse_requires(items):
    req = {}
    for it in items or []:
        m = re.match(r"^([a-z_]+)/([A-Za-z0-9]+)=([a-z_.,]+)$", it)
        if not m:
            fail("--requires %r: want <package>/<Msg>=<key>[,<key>]" % it)
        req[(m.group(1), m.group(2))] = m.group(3).split(",")
    return req


def remove_gen(d, pattern):
    for p in glob.glob(os.path.join(d, pattern)):
        os.remove(p)


def run_package(args, cat, pkg, maps, reqs):
    fmt = "ros2-" + pkg.replace("_", "-")
    module = MODULE_OF[pkg]
    names_path = os.path.join(args.names_dir, fmt + ".json") if args.names_dir else None
    namer = Namer(names_path)
    walker = Walker(cat, module, namer, maps.get(pkg, {}))
    msgs = cat.package(pkg)
    namer.name("topic", "topic")
    kinds = []
    for msg in msgs:
        lines = walker.walk(msg, msg, ["msg"], [], "", msg.name)
        kname = slug(msg.name)
        explicit = reqs.get((pkg, msg.name))
        if explicit:
            requires = explicit
        elif any(isinstance(x, FLine) and x.key == "lat" for x in lines) and \
                any(isinstance(x, FLine) and x.key == "lon" for x in lines):
            requires = ["lat", "lon"]
        elif lines:
            requires = [lines[0].key]
        else:
            requires = ["topic"]
        kinds.append(Kind(msg, kname, "%s/msg/%s" % (pkg, msg.name), lines, requires))
    names = [k.name for k in kinds]
    if len(set(names)) != len(names):
        fail("%s: two kinds with one name" % fmt)
    kinds.sort(key=lambda k: (not k.lines, k.msg.name))
    # declarations
    decls = [("key", "topic", "string", "rosbridge publish: topic name")]
    for k in kinds:
        for ln in iter_lines(k.lines):
            if isinstance(ln, FLine):
                if ln.key in CORE_KEYS:
                    if CORE_KEYS[ln.key] != ln.keytype:
                        fail("%s: core key %s is %s, field is %s" % (fmt, ln.key, CORE_KEYS[ln.key], ln.keytype))
                    continue
                decls.append(("key", ln.key, ln.keytype, ln.desc))
            else:
                decls.append(("list", ln.key, None, ln.desc))
    for (mname, path), key in maps.get(pkg, {}).items():
        if not any(isinstance(x, FLine) and x.key == key and x.pathid == path
                   for k in kinds if k.msg.name == mname for x in iter_lines(k.lines)):
            fail("--map %s/%s:%s matched no field" % (pkg, mname, path))
    # sources
    repo, pdir = pkg_dir(pkg)
    msg_src = "ROS 2 interface package %s, %s %s (%s) at commit %s, directory %s; field names, types and array forms only" % (
        pkg, REPO_URL[repo], args.ref[repo], REPO_LICENSE[repo], args.commit[repo],
        (pdir + "/msg") if pdir else "msg")
    deps = sorted({(m.pkg) for k in kinds for (p, _), m in cat.closure(k.msg).items() if p != pkg})
    sources = [msg_src]
    for d in deps:
        r = REPO_OF.get(d, "common_interfaces")
        sources.append("ROS 2 interface package %s (messages %s refers to), %s %s at commit %s, %s" % (
            d, pkg, REPO_URL[r], args.ref[r], args.commit[r], REPO_LICENSE[r]))
    sources.append("rosbridge v2.1.0 Protocol Specification, ROSBRIDGE_PROTOCOL.md, %s %s at commit %s, BSD 3-Clause License; JSON form of a message and of the publish operation" % (
        REPO_URL["rosbridge_suite"], args.ref["rosbridge_suite"], args.commit["rosbridge_suite"]))
    # write
    mod_path = os.path.join(args.out, "model", module + ".def")
    pack_dir = os.path.join(args.out, "packs", fmt)
    vec_dir = os.path.join(pack_dir, "vectors")
    os.makedirs(vec_dir, exist_ok=True)
    with open(mod_path, "w", encoding="utf-8") as fh:
        fh.write(emit_module(module, pkg, decls, sources))
    with open(os.path.join(pack_dir, "pack.def"), "w", encoding="utf-8") as fh:
        fh.write(emit_pack(fmt, module, pkg, kinds, sources))
    remove_gen(vec_dir, "gen-*.json")
    gj_dir = os.path.join(args.out, "packs", "geojson", "vectors")
    remove_gen(gj_dir, "gen-geojson-to-%s-*.json" % fmt)
    vecs = roundtrip_vectors(fmt, module, kinds, cat) + special_vectors(pkg, fmt, module, kinds, cat)
    for fname, v in vecs:
        write_json(os.path.join(vec_dir, fname), v)
    cross = geojson_cross_vectors(fmt, pkg, kinds)
    if pkg in args.cross:
        more, gmore = generic_cross(fmt, module, kinds, cat, args.cross[pkg])
        for fname, v in more:
            write_json(os.path.join(vec_dir, fname), v)
        vecs += more
        cross += gmore
    for fname, v in cross:
        write_json(os.path.join(gj_dir, fname), v)
    # provenance: every .msg the pack reads, the licence files, the rosbridge files
    files = []
    seen = set()
    for k in kinds:
        for (p, n), m in cat.closure(k.msg).items():
            r = REPO_OF.get(p, "common_interfaces")
            rel = os.path.relpath(m.path, os.path.join(args.src, r))
            if (r, rel) not in seen:
                seen.add((r, rel))
                files.append((r, rel))
    files.sort()
    lic = set()
    for p_ in sorted({m.pkg for k in kinds for m in cat.closure(k.msg).values()}):
        r, d = pkg_dir(p_)
        if r in LICENSE_FILES:
            for lf in LICENSE_FILES[r]:
                lic.add((r, lf))
        else:
            lic.add((r, "LICENSE") if r == "rcl_interfaces" else (r, d + "/LICENSE"))
        lic.add((r, (d + "/package.xml") if d else "package.xml"))
    files = sorted(lic) + files + EXTRA_FILES.get(pkg, []) + [("rosbridge_suite", f) for f in ROSBRIDGE_FILES]
    with open(os.path.join(pack_dir, "PROVENANCE.md"), "w", encoding="utf-8") as fh:
        fh.write(emit_provenance(args, fmt, pkg, files))
    # pack.md
    consts = {m.name: m.constants for m in msgs if m.constants}
    defaults = sorted({"%s.%s %s" % (m.name, f.name, f.default) for (p, _), m in cat.msgs.items()
                       if p == pkg for f in m.fields if f.default})
    notes = None
    if args.notes_dir:
        np_ = os.path.join(args.notes_dir, fmt + ".md")
        if os.path.isfile(np_):
            with open(np_, encoding="utf-8") as fh:
                notes = fh.read()
    nfield = sum(1 for k in kinds for x in iter_lines(k.lines) if isinstance(x, FLine)) + 1
    ngroup = sum(1 for k in kinds for x in iter_lines(k.lines) if isinstance(x, GLine))
    stats = [("Message kinds (.msg files)", len(kinds)),
             ("`field` lines (the common `topic` included)", nfield),
             ("`group` blocks", ngroup),
             ("Keys and lists of module `%s`" % module, len(decls)),
             ("Shared-model keys bound", len(maps.get(pkg, {}))),
             ("Fields not mapped", len(walker.not_mapped))]
    with open(os.path.join(pack_dir, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write(emit_pack_md(fmt, module, pkg, kinds, walker, consts, defaults, stats, notes,
                              len(vecs), bool(cross), list(cat.closure_all(msgs))))
    namer.save()
    # self-check from disk
    verify(args, fmt, module, vec_dir, [os.path.join(gj_dir, f) for f, _ in cross])
    return fmt, len(kinds), nfield, ngroup, len(vecs) + len(cross)


def write_json(path, v):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(v, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def verify(args, fmt, module, vec_dir, extra):
    modules = {}
    for name in ("core", "track", module):
        path = os.path.join(args.out, "model", name + ".def")
        if not os.path.isfile(path):
            path = os.path.join(args.model_dir, name + ".def")
        with open(path, encoding="utf-8") as fh:
            mod = read_module(fh.read(), path)
        modules[mod["name"]] = mod
    with open(os.path.join(args.out, "packs", fmt, "pack.def"), encoding="utf-8") as fh:
        pack = read_pack(fh.read(), fmt + "/pack.def", modules)
    if pack.format != fmt:
        fail("%s: format line names %s" % (fmt, pack.format))
    with open(args.geojson_pack, encoding="utf-8") as fh:
        glines = geojson_pack(fh.read())
    packs = {fmt: pack}
    n = 0
    for path in sorted(glob.glob(os.path.join(vec_dir, "*.json"))) + extra:
        with open(path, encoding="utf-8") as fh:
            vec = json.load(fh)
        check_vector(vec, packs, glines, os.path.basename(path))
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", required=True,
                    help="directory holding common_interfaces/, rcl_interfaces/ and rosbridge_suite/")
    ap.add_argument("--out", required=True, help="goat-transformers checkout to write into")
    ap.add_argument("--package", action="append", required=True, help="ROS 2 package; repeatable")
    ap.add_argument("--ref", action="append", default=[], help="<repository>=<tag or branch>")
    ap.add_argument("--commit", action="append", default=[], help="<repository>=<commit>")
    ap.add_argument("--map", action="append", help="<package>/<Msg>:<field path>=<core key>")
    ap.add_argument("--requires", action="append", help="<package>/<Msg>=<key>[,<key>]")
    ap.add_argument("--names-dir", help="tools/gen/names")
    ap.add_argument("--notes-dir", help="tools/gen/notes; <format>.md is put into pack.md")
    ap.add_argument("--model-dir", help="model/ of the checkout (core.def, track.def)")
    ap.add_argument("--geojson-pack", help="packs/geojson/pack.def of the checkout")
    ap.add_argument("--date-read", default="2026-11-19")
    ap.add_argument("--repo", action="append", default=[], help="<repository>=<address>")
    ap.add_argument("--package-at", action="append", default=[],
                    help="<package>=<repository>:<directory> ('.' when the package is the root)")
    ap.add_argument("--module", action="append", default=[], help="<package>=<module name>")
    ap.add_argument("--license", action="append", default=[], help="<repository>=<licence name>")
    ap.add_argument("--license-file", action="append", default=[],
                    help="<repository>=<path of a licence file>; repeatable")
    ap.add_argument("--license-note", action="append", default=[],
                    help="<repository>=<licence statement for PROVENANCE.md>")
    ap.add_argument("--evidence-file", action="append", default=[],
                    help="<package>=<repository>:<path> of a file read as evidence for a binding")
    ap.add_argument("--cross", action="append", default=[],
                    help="<package>/<Msg>: write geojson vectors for a kind bound to lat and lon")
    args = ap.parse_args()
    args.model_dir = args.model_dir or os.path.join(args.out, "model")
    args.geojson_pack = args.geojson_pack or os.path.join(args.out, "packs", "geojson", "pack.def")
    args.ref = dict(x.split("=", 1) for x in args.ref)
    args.commit = dict(x.split("=", 1) for x in args.commit)
    for x in args.repo:
        k, v = x.split("=", 1)
        REPO_URL[k] = v
    for x in args.package_at:
        k, v = x.split("=", 1)
        r, d = v.split(":", 1)
        REPO_OF[k] = r
        PKG_DIR[k] = "" if d == "." else d
    for x in args.module:
        k, v = x.split("=", 1)
        MODULE_OF[k] = v
    for x in args.license:
        k, v = x.split("=", 1)
        REPO_LICENSE[k] = v
    for x in args.license_file:
        k, v = x.split("=", 1)
        LICENSE_FILES.setdefault(k, []).append(v)
    for x in args.license_note:
        k, v = x.split("=", 1)
        LICENSE_NOTES[k] = v
    for x in args.evidence_file:
        k, v = x.split("=", 1)
        r, f = v.split(":", 1)
        EXTRA_FILES.setdefault(k, []).append((r, f))
    cross = {}
    for x in args.cross:
        pk, mn = x.split("/", 1)
        cross.setdefault(pk, []).append(mn)
    args.cross = cross
    for r in REPO_URL:
        if r not in args.ref or r not in args.commit:
            fail("--ref and --commit are needed for %s" % r)
    with open(os.path.join(args.model_dir, "core.def"), encoding="utf-8") as fh:
        for line in fh:
            t = tokens(line, "core.def")
            if t and t[0] == "key":
                CORE_KEYS[t[1]] = t[2]
    maps = parse_maps(args.map)
    for pkg, m in maps.items():
        for _k, key in m.items():
            if key not in CORE_KEYS:
                fail("--map: %s is not a core key" % key)
    reqs = parse_requires(args.requires)
    cat = Catalog(args.src)
    for pkg in args.package:
        if pkg not in MODULE_OF:
            fail("unknown package %s" % pkg)
        fmt, nk, nf, ng, nv = run_package(args, cat, pkg, maps, reqs)
        print("%-26s kinds %4d  fields %5d  groups %4d  vectors %4d  checked" % (fmt, nk, nf, ng, nv))


if __name__ == "__main__":
    try:
        main()
    except GenError as e:
        sys.stderr.write("ros2msg2pack: %s\n" % e)
        sys.exit(1)
