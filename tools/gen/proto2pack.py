#!/usr/bin/env python3
"""proto2pack: turn public protobuf schemas into a goat-transformers pack.

Python 3 standard library only. Reads .proto files (proto2 and proto3), walks
the envelope message, and writes:

  <out>/model/<module>.def            raw keys of the format, one public module
  <out>/packs/<format>/pack.def       the pack (engine-spec 0.5 to 0.7, wire protobuf)
  <out>/packs/<format>/pack.md        what was mapped, what was not, and why
  <out>/packs/<format>/vectors/gen-*.json   one same-format round-trip per kind

Then it re-reads what it wrote with an independent loader and a small protobuf
codec written from spec/engine-spec.md (0.3 to 0.7: `const`, value tables, one
key at several paths and `group` blocks, no derivations) and refuses to finish if the grammar, the
declarations, the types or any vector (existing or generated) does not hold.

Usage: see --help. Run with `python3 -I`.
"""
import argparse
import glob
import json
import os
import re
import struct
import sys

DEFAULT_MAX_DEPTH = 6
MAX_DEPTH = DEFAULT_MAX_DEPTH
KEY_BUDGET = 60000              # keys and lists one module may hold
LINE_BUDGET = 100000            # `field` lines one pack.def may hold
VECTOR_BUDGET = 12 * 1024 * 1024    # bytes of generated vectors one pack may hold
R_BOUND = "repeated message a hand binding (--bind) reads through: one occurrence is carried"
R_EMPTY_GROUP = "repeated message with nothing mappable inside"
SCALAR_TRANSFORM = {
    "string": "pstring", "double": "pdouble", "float": "pfloat",
    "int32": "pvarint", "int64": "pvarint", "uint32": "pvarint",
    "uint64": "pvarint", "bool": "pvarint",
    "sint32": "psint", "sint64": "psint",
}
FIXED_INTS = {"fixed32", "fixed64", "sfixed32", "sfixed64"}
ALL_SCALARS = set(SCALAR_TRANSFORM) | FIXED_INTS | {"bytes"}
YIELDS = {"pstring": "string", "pdouble": "float", "pfloat": "float",
          "pvarint": "int", "psint": "int"}
WIRETYPE = {"pstring": 2, "pvarint": 0, "psint": 0, "pdouble": 1, "pfloat": 5}

# Well-known types a schema may import without shipping the file.
BUILTIN_PROTOS = {
    "google/protobuf/timestamp.proto": """
syntax = "proto3";
package google.protobuf;
message Timestamp {
  int64 seconds = 1; // seconds of UTC time since the Unix epoch
  int32 nanos = 2; // non-negative fractions of a second, in nanoseconds
}
""",
    "google/protobuf/duration.proto": """
syntax = "proto3";
package google.protobuf;
message Duration {
  int64 seconds = 1; // signed seconds of the span of time
  int32 nanos = 2; // signed fractions of a second, in nanoseconds
}
""",
}
# Imported only for `extend`; nothing in a message tree needs it.
IGNORED_IMPORTS = {"google/protobuf/descriptor.proto"}


class GenError(Exception):
    pass


class TooBig(Exception):
    """The walk passed LINE_BUDGET lines inside groups; the caller lowers a limit."""


# --------------------------------------------------------------------------
# .proto parser
# --------------------------------------------------------------------------

TOKEN_RE = re.compile(r"""
    (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<word>[A-Za-z0-9_.+\-]+)
  | (?P<sym>[{}\[\]()<>=;,:])
  | (?P<ws>\s+)
""", re.S | re.X)


class Enum:
    def __init__(self, full, name):
        self.full, self.name, self.values = full, name, []  # (name, number)


class Field:
    def __init__(self):
        self.name = self.type = self.label = None
        self.number = 0
        self.oneof = None
        self.options = ""
        self.comment = ""
        self.kind = None        # scalar | message | enum | map | group
        self.ref = None         # Message or Enum
        self.mandatory = False


class Message:
    def __init__(self, full, name, syntax):
        self.full, self.name, self.syntax = full, name, syntax
        self.fields = []
        self.oneofs = []        # oneof names, declaration order


class Schema:
    def __init__(self):
        self.messages = {}      # full name -> Message
        self.enums = {}
        self.order = []         # full names in declaration order
        self.files = []         # (path, syntax, package)
        self.warnings = []


class Parser:
    def __init__(self, schema, path, text):
        self.s, self.path = schema, path
        self.toks, self.comments, self.code_lines = [], {}, set()
        pos, line = 0, 1
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m:
                raise GenError("%s:%d: cannot tokenise %r" % (path, line, text[pos:pos + 20]))
            k = m.lastgroup
            if k == "lc":
                self.comments[line] = m.group()[2:].strip().lstrip("/!").strip()
            elif k in ("str", "word", "sym"):
                self.toks.append((m.group(), line))
                self.code_lines.add(line)
            line += m.group().count("\n")
            pos = m.end()
        self.i = 0
        self.syntax, self.package, self.imports = "proto2", "", []

    def peek(self, k=0):
        return self.toks[self.i + k][0] if self.i + k < len(self.toks) else None

    def line(self, k=0):
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j][1]

    def take(self, want=None):
        t = self.peek()
        if t is None or (want is not None and t != want):
            raise GenError("%s:%d: expected %r, found %r" % (self.path, self.line(), want, t))
        self.i += 1
        return t

    def skip_statement(self):
        """Skip to the `;` that ends the statement, over balanced brackets."""
        depth = 0
        while True:
            t = self.take()
            if t in "{[(":
                depth += 1
            elif t in "}])":
                depth -= 1
            elif t == ";" and depth == 0:
                return

    def skip_block(self):
        while self.take() != "{":
            pass
        depth = 1
        while depth:
            t = self.take()
            depth += (t == "{") - (t == "}")

    def parse_file(self):
        while self.peek() is not None:
            t = self.peek()
            if t == "syntax":
                self.take(); self.take("=")
                self.syntax = self.take().strip("\"'")
                self.take(";")
            elif t == "package":
                self.take(); self.package = self.take(); self.take(";")
            elif t == "import":
                self.take()
                if self.peek() in ("public", "weak"):
                    self.take()
                self.imports.append(self.take().strip("\"'"))
                self.take(";")
            elif t == "option":
                self.skip_statement()
            elif t == "message":
                self.parse_message(self.package)
            elif t == "enum":
                self.parse_enum(self.package)
            elif t in ("extend", "service"):
                self.skip_block()
            elif t == ";":
                self.take()
            else:
                raise GenError("%s:%d: unexpected %r at file level" % (self.path, self.line(), t))
        self.s.files.append((self.path, self.syntax, self.package))

    def qual(self, scope, name):
        return (scope + "." if scope else "") + name

    def parse_enum(self, scope):
        self.take("enum")
        name = self.take()
        e = Enum(self.qual(scope, name), name)
        self.take("{")
        while self.peek() != "}":
            t = self.peek()
            if t in ("option", "reserved"):
                self.skip_statement()
            elif t == ";":
                self.take()
            else:
                vname = self.take(); self.take("=")
                e.values.append((vname, int(self.take(), 0)))
                self.skip_statement()
        self.take("}")
        self.s.enums[e.full] = e

    def field_comment(self, first_line, last_line):
        if last_line in self.comments:
            return self.comments[last_line]
        out, ln = [], first_line - 1
        while ln in self.comments and ln not in self.code_lines:
            out.insert(0, self.comments[ln])
            ln -= 1
        return " ".join(out)

    def parse_field(self, msg, oneof):
        f = Field()
        first = self.line()
        if self.peek() == "map" and self.peek(1) == "<":
            self.take(); self.take("<")
            k = self.take(); self.take(","); v = self.take(); self.take(">")
            f.label, f.type, f.kind = "repeated", "map<%s,%s>" % (k, v), "map"
        else:
            if self.peek() in ("optional", "required", "repeated") and self.peek(2) != "=":
                f.label = self.take()
            f.type = self.take()
        if f.type == "group":
            f.kind = "group"
            f.name = self.take(); self.take("=")
            f.number = int(self.take(), 0)
            self.skip_block()
            msg.fields.append(f)
            return
        f.name = self.take()
        self.take("=")
        f.number = int(self.take(), 0)
        if self.peek() == "[":
            start = self.i
            depth = 0
            while True:
                t = self.take()
                depth += (t in "[{") - (t in "]}")
                if depth == 0:
                    break
            f.options = " ".join(t for t, _ in self.toks[start:self.i])
        last = self.line()
        self.take(";")
        f.oneof = oneof
        f.comment = self.field_comment(first, last)
        msg.fields.append(f)

    def parse_message(self, scope):
        self.take("message")
        name = self.take()
        m = Message(self.qual(scope, name), name, self.syntax)
        self.s.messages[m.full] = m
        self.s.order.append(m.full)
        self.take("{")
        while self.peek() != "}":
            t = self.peek()
            if t == "message" and self.peek(2) == "{":
                self.parse_message(m.full)
            elif t == "enum" and self.peek(2) == "{":
                self.parse_enum(m.full)
            elif t == "oneof" and self.peek(2) == "{":
                self.take()
                oname = self.take()
                m.oneofs.append(oname)
                self.take("{")
                while self.peek() != "}":
                    if self.peek() == "option":
                        self.skip_statement()
                    elif self.peek() == ";":
                        self.take()
                    else:
                        self.parse_field(m, oname)
                self.take("}")
            elif t in ("option", "reserved", "extensions"):
                self.skip_statement()
            elif t == "extend":
                self.skip_block()
            elif t == ";":
                self.take()
            else:
                self.parse_field(m, None)
        self.take("}")


def load_schema(paths, mandatory_option):
    s = Schema()
    given = {os.path.basename(p): p for p in paths}
    imports = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            ps = Parser(s, p, fh.read())
        ps.parse_file()
        imports += [(p, i) for i in ps.imports]
    builtin_done = set()
    for src, imp in imports:
        if os.path.basename(imp) in given:
            continue
        if imp in BUILTIN_PROTOS:
            if imp not in builtin_done:
                builtin_done.add(imp)
                Parser(s, "<builtin %s>" % imp, BUILTIN_PROTOS[imp]).parse_file()
            continue
        if imp in IGNORED_IMPORTS:
            continue
        raise GenError("%s imports %s, which is not among the given files" % (src, imp))
    # resolve field types, innermost scope first
    for m in s.messages.values():
        for f in m.fields:
            f.mandatory = (f.label == "required" or bool(
                mandatory_option and re.search(
                    r"\b%s\s*:\s*true\b" % re.escape(mandatory_option), f.options)))
            if f.kind in ("map", "group"):
                continue
            if f.type in ALL_SCALARS:
                f.kind = "scalar"
                continue
            scope = m.full
            cands = []
            if f.type.startswith("."):
                cands = [f.type[1:]]
            else:
                while True:
                    cands.append((scope + "." if scope else "") + f.type)
                    if not scope:
                        break
                    scope = scope.rpartition(".")[0]
            for c in cands:
                if c in s.messages:
                    f.kind, f.ref = "message", s.messages[c]
                    break
                if c in s.enums:
                    f.kind, f.ref = "enum", s.enums[c]
                    break
            else:
                raise GenError("%s.%s: type %s is not defined in the given files" % (m.full, f.name, f.type))
    return s


# --------------------------------------------------------------------------
# walk
# --------------------------------------------------------------------------

def snake(name):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


class Leaf:
    def __init__(self):
        self.nums = ()          # field-number path from the envelope, or from the item inside a group
        self.names = ()         # snake field-name path, kind member excluded
        self.owner = None       # Message that declares the field
        self.field = None
        self.transform = None
        self.mandatory = False  # every hop below the kind root is mandatory
        self.oneofs = ()        # ((message full, oneof name, member number, nums prefix), ...)
        self.key = None         # model key as written in the pack
        self.kind = None        # kind name or None for common
        self.core = None
        self.is_list = False    # a stand-in that names a first-level list in assign_keys
        self.item = None        # Message whose item holds this leaf, inside a group


class Group:
    """A `repeated` field: a `group` block. Paths are relative to the scope the
    block stands in (common, a kind, or the item of the enclosing group)."""

    def __init__(self):
        self.nums = ()          # field-number path of the repeated field, relative to the scope
        self.abs = ()           # the same from the envelope, through every enclosing group
        self.names = ()
        self.owner = None
        self.field = None
        self.oneofs = ()
        self.kind = None
        self.level = 1          # 1 = in common or a kind; 2 = inside the item of a level-1 group
        self.item = None        # Message of the enclosing item, None at level 1
        self.scalar = None      # Leaf of the `.` field of a repeated scalar
        self.leaves = []        # leaves of the item, paths relative to it
        self.groups = []        # groups nested in the item
        self.list = None        # list name as written in the pack

    def all_groups(self):
        out = [self]
        for g in self.groups:
            out += g.all_groups()
        return out

    def item_leaves(self):
        return ([self.scalar] if self.scalar else []) + self.leaves


def flat_groups(groups):
    return [x for g in groups for x in g.all_groups()]


def dotted(nums):
    return ".".join(map(str, nums))


def walk(msg, nums, names, chain, mandatory, oneofs, leaves, skipped, groups, base=(), level=0, item=None,
         bound=frozenset(), max_nest=99, item_depth=99, room=None):
    """Depth-first through message fields. A singular field is a leaf or is
    descended; a `repeated` field is a Group whose item is walked with paths
    relative to it. `skipped` collects (reason, absolute nums, owner, field).
    `base` is the absolute path of the enclosing item, `level` the number of
    enclosing groups."""
    for f in msg.fields:
        p = nums + (f.number,)
        n = names + (snake(f.name),)
        ap = base + p
        if f.kind == "group":
            skipped.append(("group", ap, msg, f)); continue
        if f.kind == "map":
            skipped.append(("map", ap, msg, f)); continue
        man = mandatory and f.mandatory and f.oneof is None
        one = oneofs + (((msg.full, f.oneof, f.number, nums),) if f.oneof else ())
        if f.kind == "scalar" and f.type == "bytes":
            skipped.append(("bytes", ap, msg, f)); continue
        if f.kind == "scalar" and f.type in FIXED_INTS:
            skipped.append(("fixed-width integer", ap, msg, f)); continue
        if f.label == "repeated":
            if level == 0 and ap in bound:
                skipped.append((R_BOUND, ap, msg, f)); continue
            if level >= max_nest:
                skipped.append(("repeated field below group nesting depth %d" % max_nest, ap, msg, f)); continue
            g = Group()
            g.nums, g.abs, g.names, g.owner, g.field, g.oneofs = p, ap, n, msg, f, one
            g.level, g.item = level + 1, item
            if f.kind == "message":
                if f.ref.full in chain:
                    skipped.append(("recursive message type", ap, msg, f)); continue
                if len(ap) >= MAX_DEPTH:
                    skipped.append(("below depth %d" % MAX_DEPTH, ap, msg, f)); continue
                inner = []
                walk(f.ref, (), (), chain + (f.ref.full,), False, (), g.leaves, inner, g.groups,
                     base=ap, level=level + 1, item=f.ref, bound=bound, max_nest=max_nest, item_depth=item_depth,
                     room=room)
                if not g.leaves and not g.groups:
                    skipped.append((R_EMPTY_GROUP, ap, msg, f)); continue
                skipped.extend(inner)
            else:
                lf = Leaf()
                lf.nums, lf.names, lf.owner, lf.field, lf.item = (), (), msg, f, msg
                lf.transform = "pvarint" if f.kind == "enum" else SCALAR_TRANSFORM[f.type]
                g.scalar = lf
                count_line(room)
            groups.append(g)
            continue
        if f.kind == "message":
            if f.ref.full in chain:
                skipped.append(("recursive message type", ap, msg, f)); continue
            if len(ap) >= MAX_DEPTH:
                skipped.append(("below depth %d" % MAX_DEPTH, ap, msg, f)); continue
            if level and len(p) >= item_depth:
                skipped.append(("inside an item, below item depth %d" % item_depth, ap, msg, f)); continue
            walk(f.ref, p, n, chain + (f.ref.full,), man, one, leaves, skipped, groups,
                 base=base, level=level, item=item, bound=bound, max_nest=max_nest, item_depth=item_depth,
                 room=room)
            continue
        lf = Leaf()
        lf.nums, lf.names, lf.owner, lf.field, lf.item = p, n, msg, f, item
        lf.transform = "pvarint" if f.kind == "enum" else SCALAR_TRANSFORM[f.type]
        lf.mandatory, lf.oneofs = man, one
        leaves.append(lf)
        if level:
            count_line(room)


def count_line(room):
    if room is not None:
        room[0] -= 1
        if room[0] < 0:
            raise TooBig()


def assign_keys(module, kinds, common, core_map, pinned):
    """Name every leaf that no --map binds: <container name>_<field name>.

    The container is the message instance that holds the field, identified by
    its message type and its field-name path below the kind's message. Two
    kinds that reach the same message type by the same path share the
    container, so its fields are one set of keys used by both kinds.

    A container's name is the first component of its path (the field of the
    kind's message it sits under) followed by the shortest run of trailing
    components that no other container could also be named by; the whole path
    when no shorter name is free. The kind's own message is named by the kind.
    When two kinds reach different message types by the same path, both
    containers take the kind name as a prefix.

    `pinned` maps a field-number path to the key name an earlier run gave it.
    A pinned path keeps its name whatever the rules above would now choose,
    and a new path never takes a name that is pinned to something else, so a
    schema revision cannot rename or reuse an existing key."""
    all_leaves = list(common) + [l for _, _, ls in kinds for l in ls]
    for lf in all_leaves:
        lf.cpath = lf.names[:-1]          # container path
        lf.prefixed = lf.kind is not None and not lf.cpath
        if lf.prefixed:
            lf.cpath = (lf.kind,)
        lf.path = ".".join(map(str, lf.nums)) + ("[]" if lf.is_list else "")
        lf.core = core_map.get(lf.path)
    raw = all_leaves

    def cid(l):
        scope = "common" if l.kind is None else ("kind:" + l.kind if l.prefixed else "kind")
        return (scope, l.owner.full, l.cpath)

    def candidates(cp):
        """Shortest first; the last one is the whole path."""
        return ["_".join(cp[:1] + cp[-k:]) for k in range(1, len(cp) - 1)] + ["_".join(cp)]

    while True:
        groups = {}
        for l in raw:
            groups.setdefault(cid(l), []).append(l)
        whole, anyc = {}, {}
        for c_id in groups:
            cs = candidates(c_id[2])
            whole.setdefault(cs[-1], set()).add(c_id)
            for c in cs:
                anyc.setdefault(c, set()).add(c_id)
        names, failing = {}, []
        for c_id in groups:
            cs = candidates(c_id[2])
            for c in cs:
                table = whole if c == cs[-1] else anyc
                if not table.get(c, set()) - {c_id}:
                    names[c_id] = c
                    break
            else:
                failing.append(c_id)
        progressed = False
        for c_id in failing:
            for l in groups[c_id]:
                if l.kind is not None and not l.prefixed:
                    l.prefixed, l.cpath, progressed = True, (l.kind,) + l.cpath, True
        if progressed:
            continue
        idents = {}
        for c_id, ls in groups.items():
            for l in ls:
                idents.setdefault((c_id, l.field.number), []).append(l)
        taken = {}      # name -> ident
        for ident, ls in idents.items():        # pinned names first
            for l in ls:
                if l.path in pinned:
                    if taken.setdefault(pinned[l.path], ident) != ident:
                        raise GenError("pinned name %s is given to two different fields" % pinned[l.path])
                    l.key = module + "." + pinned[l.path]
        reserved = set(pinned.values())
        for ident, ls in idents.items():
            new = [l for l in ls if l.path not in pinned]
            if not new:
                continue
            had = [l.key for l in ls if l.path in pinned]
            if had:                              # same field, reached from a new kind
                for l in new:
                    l.key = had[0]
                continue
            c_id, l0 = ident[0], ls[0]
            leaf = l0.names[-1]
            name = (names[c_id] + "_" if names[c_id] else "") + leaf if c_id in names else None
            if name is None or name in reserved or taken.get(name, ident) != ident:
                # two different paths spell the same text once joined with `_`,
                # or the name is pinned elsewhere: the field-number path settles it
                name = "_".join(l0.cpath + (leaf,)) + "_at_" + "_".join(map(str, l0.nums))
                if name in reserved or taken.get(name, ident) != ident:
                    raise GenError("cannot name %s" % name)
            taken[name] = ident
            for l in new:
                l.key = module + "." + name
        return


def assign_item_keys(module, groups, pinned, used, same):
    """Name what lies inside groups. `groups` are the first-level groups, already
    named. Inside an item a key belongs to the item's message type, not to the
    place the list stands at, so every list of one message type has the same
    item keys.

      item key     ident `<item message>:<path in the item>`   name `<message>_<field names>`
      nested list  ident `<item message>:<path in the item>[]` name the same way
      scalar item  ident `<owning message>:<field number>[]item`  name `<message>_<field>_item`

    A pinned ident keeps its name. When the name an item key would get is the
    key of that same schema field outside any group (`same`: name -> the
    (message, field number) it stands for), the item uses that key: one field,
    one key, in an entity or in an item. Any other new name that is taken
    (`used`: every name of the module so far, and every pinned name) gets
    `_at_<path>`, then the message's full name. Returns {ident: name} of
    everything it named."""
    out, by_name = {}, {}
    reserved = set(pinned.values()) | set(used)

    def name_of(ident, msg, names, nums, suffix="", field=None):
        if ident in out:
            return out[ident]
        base = "_".join((snake(msg.name),) + names) + suffix
        if ident in pinned:
            name = pinned[ident]
        elif field is not None and same.get(base) == {field} and base not in by_name:
            name = base
        else:
            full = "_".join((snake(msg.full.replace(".", "_")),) + names) + suffix
            at = "_at_" + "_".join(map(str, nums)) if nums else ""
            for name in (base, base + at, full + at, None):
                if name is None:
                    raise GenError("cannot name %s" % ident)
                if name not in reserved and name not in by_name:
                    break
        if by_name.setdefault(name, ident) != ident:
            raise GenError("name %s is given to %s and %s" % (name, by_name[name], ident))
        out[ident] = name
        return name

    def inside(g):
        if g.scalar:
            lf = g.scalar
            lf.path = "%s:%d[]item" % (g.owner.full, g.field.number)
            lf.key = module + "." + name_of(lf.path, g.owner, (snake(g.field.name),), (g.field.number,), "_item")
        for lf in g.leaves:
            lf.path = "%s:%s" % (g.field.ref.full, dotted(lf.nums))
            lf.key = module + "." + name_of(lf.path, g.field.ref, lf.names, lf.nums,
                                            field=(lf.owner.full, lf.field.number))
        for sg in g.groups:
            sg.path = "%s:%s[]" % (g.field.ref.full, dotted(sg.nums))
            sg.list = module + "." + name_of(sg.path, g.field.ref, sg.names, sg.nums)
            inside(sg)
    for g in groups:
        inside(g)
    return out


# --------------------------------------------------------------------------
# protobuf codec, written from engine-spec 0.3
# --------------------------------------------------------------------------

def enc_varint(v):
    if v < 0:
        v += 1 << 64
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def enc_value(transform, v):
    if transform == "pstring":
        b = v.encode("utf-8")
        return enc_varint(len(b)) + b
    if transform == "pvarint":
        return enc_varint(v)
    if transform == "psint":
        return enc_varint((v << 1) ^ (v >> 63))
    if transform == "pdouble":
        return struct.pack("<d", v)
    if transform == "pfloat":
        return struct.pack("<f", v)
    raise GenError("no encoder for " + transform)


class Rep(list):
    """The occurrences of a repeated field, in order: subtree dicts (items that
    are submessages) or (transform, value) pairs (one occurrence per value)."""


class Packed:
    """A repeated numeric field in packed form (engine-spec 0.7, Encode): one
    length-delimited occurrence holding the values back to back."""

    def __init__(self, transform, values):
        self.transform, self.values = transform, values


def enc_tree(tree):
    """tree: {number: (transform, value) | subtree dict | Rep | Packed}; canonical = ascending."""
    out = bytearray()

    def one(num, node):
        nonlocal out
        if isinstance(node, dict):
            body = enc_tree(node)
            out += enc_varint(num << 3 | 2) + enc_varint(len(body)) + body
        else:
            out += enc_varint(num << 3 | WIRETYPE[node[0]]) + enc_value(*node)
    for num in sorted(tree):
        node = tree[num]
        if isinstance(node, Packed):
            if node.values:
                body = b"".join(enc_value(node.transform, v) for v in node.values)
                out += enc_varint(num << 3 | 2) + enc_varint(len(body)) + body
        elif isinstance(node, Rep):
            for item in node:
                one(num, item)
        else:
            one(num, node)
    return bytes(out)


def dec_message(b):
    """-> {number: (wiretype, value)}; the last occurrence wins."""
    return {num: (wt, val) for num, wt, val in dec_fields(b)}


def dec_fields(b):
    """-> [(number, wiretype, value)], every occurrence in wire order."""
    out, i = [], 0

    def varint():
        nonlocal i
        v = shift = 0
        while True:
            if i >= len(b):
                raise GenError("malformed-wire: truncated varint")
            c = b[i]; i += 1
            v |= (c & 0x7F) << shift
            shift += 7
            if not c & 0x80:
                return v

    while i < len(b):
        tag = varint()
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            val = varint()
        elif wt == 1:
            val = b[i:i + 8]; i += 8
        elif wt == 5:
            val = b[i:i + 4]; i += 4
        elif wt == 2:
            n = varint()
            val = b[i:i + n]; i += n
        else:
            raise GenError("malformed-wire: wire type %d" % wt)
        if i > len(b):
            raise GenError("malformed-wire: truncated field %d" % num)
        out.append((num, wt, val))
    return out


def dec_packed(transform, b):
    """The values of a packed occurrence (engine-spec 0.7, ruling 8: a payload
    whose length does not fit its values is malformed-wire)."""
    if transform in ("pdouble", "pfloat"):
        n = 8 if transform == "pdouble" else 4
        if len(b) % n:
            raise GenError("malformed-wire: packed payload of %d bytes" % len(b))
        return [dec_value(transform, WIRETYPE[transform], b[i:i + n]) for i in range(0, len(b), n)]
    out, i = [], 0
    while i < len(b):
        v = shift = 0
        while True:
            if i >= len(b):
                raise GenError("malformed-wire: truncated packed varint")
            c = b[i]; i += 1
            v |= (c & 0x7F) << shift
            shift += 7
            if not c & 0x80:
                break
        out.append(dec_value(transform, 0, v))
    return out


def wire_get(b, path):
    msg = dec_message(b)
    for n in path[:-1]:
        if n not in msg:
            return None
        wt, val = msg[n]
        if wt != 2:
            raise GenError("field %s is not length-delimited" % n)
        msg = dec_message(val)
    return msg.get(path[-1])


def dec_value(transform, wt, val):
    if wt != WIRETYPE[transform]:
        raise GenError("transform-decode: wire type %d for %s" % (wt, transform))
    if transform == "pstring":
        return val.decode("utf-8")
    if transform == "pvarint":      # 64-bit two's complement (0.5 ruling 15)
        return val - (1 << 64) if val >> 63 else val
    if transform == "psint":
        return (val >> 1) ^ -(val & 1)
    if transform == "pdouble":
        return struct.unpack("<d", val)[0]
    return struct.unpack("<f", val)[0]


# --------------------------------------------------------------------------
# independent loader for the files this tool writes (engine-spec 0.4 and 0.5)
# --------------------------------------------------------------------------

def def_lines(text):
    """Tokenise a .def file: `#` starts a comment at token start; double quotes
    wrap a value with whitespace."""
    for ln, line in enumerate(text.split("\n"), 1):
        toks, i = [], 0
        while i < len(line):
            c = line[i]
            if c.isspace():
                i += 1
            elif c == "#":
                break
            elif c == '"':
                j = line.find('"', i + 1)
                if j < 0:
                    raise GenError("line %d: unterminated quote" % ln)
                toks.append(line[i + 1:j]); i = j + 1
            else:
                j = i
                while j < len(line) and not line[j].isspace():
                    j += 1
                toks.append(line[i:j]); i = j
        if toks:
            yield ln, toks


def load_module(text):
    mod = {"keys": {}, "sources": [], "derive": [], "lists": set()}
    for ln, t in def_lines(text):
        d, a = t[0], t[1:]
        if d in ("module", "version", "distribution") and len(a) == 1:
            if d == "distribution" and a[0] not in ("public", "controlled"):
                raise GenError("module line %d: bad distribution" % ln)
            mod[d] = a[0]
        elif d == "source" and len(a) == 1:
            mod["sources"].append(a[0])
        elif d == "key" and len(a) in (3, 4):
            if "." in a[0]:     # the spec's rule; model/n2k.def has keys that begin with a digit
                raise GenError("module line %d: bad key name %s" % (ln, a[0]))
            if a[1] not in ("string", "float", "int"):
                raise GenError("module line %d: bad key type %s" % (ln, a[1]))
            if a[0] in mod["keys"] or a[0] in mod["lists"]:
                raise GenError("duplicate-key: %s" % a[0])
            mod["keys"][a[0]] = a[1]
        elif d == "list" and len(a) in (1, 2):      # engine-spec 0.7: a list shares the key namespace
            if "." in a[0]:
                raise GenError("module line %d: bad list name %s" % (ln, a[0]))
            if a[0] in mod["keys"] or a[0] in mod["lists"]:
                raise GenError("duplicate-key: %s" % a[0])
            mod["lists"].add(a[0])
        elif d == "derive" and len(a) >= 3:
            mod["derive"].append((a[0], a[2:]))     # engine-spec 0.6; read for would_derive, never computed
        else:
            raise GenError("module line %d: bad directive %s" % (ln, " ".join(t)))
    for req in ("module", "version"):
        if req not in mod:
            raise GenError("module has no %s line" % req)
    if "distribution" not in mod:
        raise GenError("missing-distribution: module")
    if not mod["sources"]:
        raise GenError("missing-source: module")
    return mod


PATH_RE = re.compile(r"[1-9][0-9]*(\.[1-9][0-9]*)*")


def load_pack(text, modules):
    """engine-spec 0.4 Loading, 0.5 kinds, 0.6 `const`, `map`, `via`, 0.7 `group`
    blocks. A scope is a dict with `fields`, `const` and `groups`; a group is a
    scope with `list` and `path`. A field path inside a group is relative to
    the item, `()` for the `.` locator."""
    pack = {"sources": [], "uses": ["core"],
            "common": {"fields": [], "when": [], "const": [], "groups": []}, "kinds": [], "tables": {}}
    cur = pack["common"]
    stack = []          # open groups, outermost first
    for ln, t in def_lines(text):
        d, a = t[0], t[1:]
        scope = stack[-1] if stack else cur
        if stack and d in ("format", "version", "wire", "distribution", "source", "uses", "kind", "when",
                           "requires", "root", "map", "typemap"):
            raise GenError("bad-directive: pack line %d: %s inside a group" % (ln, d))
        if d in ("format", "version", "wire", "distribution") and len(a) == 1:
            pack[d] = a[0]
        elif d == "source" and len(a) == 1:
            pack["sources"].append(a[0])
        elif d == "uses" and len(a) == 1:
            pack["uses"].append(a[0])
        elif d == "kind" and len(a) == 1:
            if any(k["name"] == a[0] for k in pack["kinds"]):
                raise GenError("duplicate-kind: %s" % a[0])
            cur = {"name": a[0], "fields": [], "when": [], "requires": [], "const": [], "groups": []}
            pack["kinds"].append(cur)
        elif d == "when" and len(a) == 2:
            if not PATH_RE.fullmatch(a[0]) or not (a[1] == "present" or a[1].isdigit()):
                raise GenError("pack line %d: bad when" % ln)
            cur["when"].append((tuple(map(int, a[0].split("."))), a[1]))
        elif d == "requires" and a:
            if cur is pack["common"]:
                raise GenError("bad-directive: requires before the first kind")
            cur["requires"] += a
        elif d == "const" and len(a) == 2:
            if not PATH_RE.fullmatch(a[0]) or not a[1].isdigit():
                raise GenError("pack line %d: bad const" % ln)
            scope["const"].append((tuple(map(int, a[0].split("."))), a[1]))
        elif d == "map" and len(a) == 3:
            pack["tables"].setdefault(a[0], []).append((a[1], a[2]))
        elif d == "group" and len(a) == 2:      # `count` is not allowed on this wire
            if not PATH_RE.fullmatch(a[1]):
                raise GenError("pack line %d: bad group path %s" % (ln, a[1]))
            g = {"list": a[0], "path": tuple(map(int, a[1].split("."))), "fields": [], "const": [], "groups": []}
            scope["groups"].append(g)
            stack.append(g)
        elif d == "end" and not a:
            if not stack:
                raise GenError("bad-directive: pack line %d: end with no open group" % ln)
            stack.pop()
        elif d == "field" and (len(a) == 3 or (len(a) == 5 and a[3] == "via")):
            if a[1] == "." and stack:
                path = ()
            elif PATH_RE.fullmatch(a[1]):
                path = tuple(map(int, a[1].split(".")))
            else:
                raise GenError("pack line %d: bad protobuf path %s" % (ln, a[1]))
            if a[2] not in YIELDS:
                raise GenError("pack line %d: %s is not a protobuf transform" % (ln, a[2]))
            scope["fields"].append((a[0], path, a[2], a[4] if len(a) == 5 else None))
        else:
            raise GenError("pack line %d: bad directive %s" % (ln, " ".join(t)))
    if stack:
        raise GenError("bad-directive: group %s has no end" % stack[-1]["list"])
    if not pack["kinds"] and pack["common"]["when"]:
        raise GenError("bad-directive: when in a pack with no kind")
    if pack.get("wire") != "protobuf":
        raise GenError("pack wire is not protobuf")
    if "distribution" not in pack:
        raise GenError("missing-distribution: pack")
    if not pack["sources"]:
        raise GenError("missing-source: pack")
    for u in pack["uses"]:
        if u not in modules:
            raise GenError("unknown-module: %s" % u)
        if pack["distribution"] == "public" and modules[u]["distribution"] != "public":
            raise GenError("distribution-violation: %s" % u)

    def check_key(key, want_list=False):
        """The declared type of a key; `list` for a list."""
        mod, name = key.split(".", 1) if "." in key else ("core", key)
        if mod not in pack["uses"]:
            raise GenError("module-not-used: %s" % key)
        if name in modules[mod]["lists"]:
            if not want_list:
                raise GenError("key-type-mismatch: field names the list %s" % key)
            return "list"
        if name not in modules[mod]["keys"]:
            raise GenError("undeclared-key: %s" % key)
        if want_list:
            raise GenError("key-type-mismatch: group names the scalar key %s" % key)
        return modules[mod]["keys"][name]

    def table_type(name):
        models = [m for _, m in pack["tables"][name]]
        if all(re.fullmatch(r"-?[0-9]+", m) for m in models):
            return "int"
        if all(re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", m) for m in models):
            return "float"
        return "string"

    def check_scope(fields, groups, where):
        for key, path, tr, via in fields:
            if via is not None and via not in pack["tables"]:
                raise GenError("bad-directive: via %s names a table with no map line" % via)
            if check_key(key) != (table_type(via) if via else YIELDS[tr]):
                raise GenError("key-type-mismatch: %s through %s" % (key, via or tr))
        seen_p = {}
        for key, path, tr, via in fields:           # 0.6: a key may be mapped by several lines
            if seen_p.setdefault(path, tr) != tr:   # 0.5 ruling 16 allows two keys; one wire type
                raise GenError("path %s has two transforms in %s" % (path, where))
        lists = set()
        for g in groups:
            check_key(g["list"], want_list=True)
            if g["list"] in lists:                  # 0.7: one group per list in a scope
                raise GenError("bad-directive: list %s is mapped by two groups in %s" % (g["list"], where))
            lists.add(g["list"])
            if g["path"] in seen_p:
                raise GenError("path %s is a field and a group in %s" % (g["path"], where))
            seen_p[g["path"]] = "group"
        for path in seen_p:      # a path is a scalar, a submessage or a repeated field, never two
            for k in range(1, len(path)):
                if path[:k] in seen_p:
                    raise GenError("path %s is both a value and a submessage in %s" % (path[:k], where))
        for g in groups:
            if () in [p for _, p, _, _ in g["fields"]] and (
                    len({p for _, p, _, _ in g["fields"]}) > 1 or g["groups"] or g["const"]):
                raise GenError("group %s reads its item as a scalar and as a submessage" % g["list"])
            check_scope(g["fields"], g["groups"], "group %s" % g["list"])

    for kind in pack["kinds"]:
        for key in kind["requires"]:
            mod, name = key.split(".", 1) if "." in key else ("core", key)
            if mod not in pack["uses"]:
                raise GenError("module-not-used: %s" % key)
            if name not in modules[mod]["keys"] and name not in modules[mod]["lists"]:
                raise GenError("undeclared-key: %s" % key)
    for kind in pack["kinds"] or [None]:
        check_scope(pack["common"]["fields"] + (kind["fields"] if kind else []),
                    pack["common"]["groups"] + (kind["groups"] if kind else []),
                    "kind %s" % kind["name"] if kind else "the pack")
    return pack


def select_kind(pack, b):
    def holds(when):
        for path, value in when:
            got = wire_get(b, path)
            if got is None:
                return False
            if value != "present" and not (got[0] == 0 and got[1] == int(value)):
                return False
        return True
    if not holds(pack["common"]["when"]):
        raise GenError("no-kind")
    if not pack["kinds"]:
        return None
    for k in pack["kinds"]:
        if holds(k["when"]):
            return k
    raise GenError("no-kind")


def canon(v):
    """Canonical text of a value, as a value table compares it (0.6)."""
    return model_text(v)


def via_value(pack, via, v, to_model):
    """A value through a table. Tables here are string to string (0.6: a value
    with no entry passes through when the two types are the same)."""
    if via is None:
        return v
    for native, model in pack["tables"][via]:
        if (native if to_model else model) == canon(v):
            return model if to_model else native
    return v


def decode_scope(pack, b, fields, groups):
    """The keys and lists of one message: the entity, or one item. A list is a
    Python list of such dicts under its name (engine-spec 0.7, Decode)."""
    ent = {}
    for key, path, tr, via in fields:
        got = wire_get(b, path)
        if got is not None and key not in ent:      # 0.6: the earliest line present on the wire
            ent[key] = via_value(pack, via, dec_value(tr, *got), True)
    for g in groups:
        body = b
        for n in g["path"][:-1]:                    # the container: last occurrence, as for a field
            got = dec_message(body).get(n)
            if got is None:
                body = None
                break
            if got[0] != 2:
                raise GenError("malformed-wire: field %s is not length-delimited" % n)
            body = got[1]
        if body is None:
            continue
        occ = [(wt, val) for num, wt, val in dec_fields(body) if num == g["path"][-1]]
        scalar = [f for f in g["fields"] if f[1] == ()]
        items = []
        for wt, val in occ:
            if scalar:
                key, _, tr, via = scalar[0]
                if wt == 2 and tr != "pstring":     # packed form
                    vals = dec_packed(tr, val)
                else:
                    vals = [dec_value(tr, wt, val)]
                items += [{key: via_value(pack, via, v, True)} for v in vals]
            else:
                if wt != 2:                         # 0.7 ruling 8
                    raise GenError("malformed-wire: an item of %s is not a submessage" % g["list"])
                items.append(decode_scope(pack, val, g["fields"], g["groups"]))
        if items:                                   # present when at least one item occurs
            ent[g["list"]] = items
    return ent


def engine_decode(pack, b):
    kind = select_kind(pack, b)
    ent = decode_scope(pack, b, pack["common"]["fields"] + (kind["fields"] if kind else []),
                       pack["common"]["groups"] + (kind["groups"] if kind else []))
    return ent, (kind["name"] if kind else None)


def encode_scope(pack, ent, fields, consts, groups):
    """-> the tree enc_tree writes, for the entity or for one item (0.7, Encode)."""
    tree = {}
    for key, path, tr, via in fields:
        if key in ent:
            node = tree
            for n in path[:-1]:
                node = node.setdefault(n, {})
            # 0.5 ruling 16: the earliest line whose key is present
            node.setdefault(path[-1], (tr, via_value(pack, via, ent[key], False)))
    for path, value in consts:
        node = tree
        for n in path[:-1]:
            node = node.setdefault(n, {})
        node[path[-1]] = ("pvarint", int(value))     # 0.6: a constant is written over any field
    for g in groups:
        items = ent.get(g["list"])
        if not items:                               # absent, or empty: nothing is written
            continue
        node = tree
        for n in g["path"][:-1]:
            node = node.setdefault(n, {})
        scalar = [f for f in g["fields"] if f[1] == ()]
        if scalar:
            key, _, tr, via = scalar[0]
            vals = [via_value(pack, via, it[key], False) for it in items if key in it]
            node[g["path"][-1]] = Rep((tr, v) for v in vals) if tr == "pstring" else Packed(tr, vals)
        else:
            node[g["path"][-1]] = Rep(encode_scope(pack, it, g["fields"], g["const"], g["groups"]) for it in items)
    return tree


def engine_encode(pack, ent, kind_name):
    """kind_name None: the entity came from another format; choose by `requires`."""
    kind = next((k for k in pack["kinds"] if k["name"] == kind_name), None)
    if kind is None and pack["kinds"]:
        # 0.7: `requires <list>` holds when the list is present and has an item
        kind = next((k for k in pack["kinds"] if all(r in ent and ent[r] != [] for r in k["requires"])), None)
        if kind is None:
            raise GenError("no-kind")
    tree = encode_scope(pack, ent, pack["common"]["fields"] + (kind["fields"] if kind else []),
                        pack["common"]["const"] + (kind["const"] if kind else []),
                        pack["common"]["groups"] + (kind["groups"] if kind else []))
    for path, value in pack["common"]["when"] + (kind["when"] if kind else []):
        node = tree
        for n in path[:-1]:
            node = node.setdefault(n, {})
        if value == "present":
            node.setdefault(path[-1], {})        # 0.5 ruling 14: empty length-delimited field
        else:
            node[path[-1]] = ("pvarint", int(value))
    return enc_tree(tree), (kind["name"] if kind else None)


def pack_names(pack):
    """The entity keys and lists a protobuf pack maps (not the keys of items)."""
    out = set()
    for g in [pack["common"]] + pack["kinds"]:
        out |= {k for k, _, _, _ in g["fields"]} | {x["list"] for x in g["groups"]}
    return out


def top_lines(pack_text):
    """The directive lines of a pack outside every `group` block."""
    depth = 0
    for _, t in def_lines(pack_text):
        if t[0] == "group":
            depth += 1
        elif t[0] == "end":
            depth -= 1
        elif depth == 0:
            yield t


def text_decode(pack_text, wire_text):
    """decode() for the two text wires of engine-spec 0.1 (xml, geojson), for
    packs without kinds: enough to derive the entity of a cross-format vector."""
    import datetime
    import xml.etree.ElementTree as ET
    wire, fields = None, []
    for t in top_lines(pack_text):     # lists of a text pack are not decoded here
        if t[0] == "wire":
            wire = t[1]
        elif t[0] == "field":
            if len(t) != 4:
                raise GenError("text_decode: field options are not supported")
            fields.append(t[1:4])
        elif t[0] in ("kind", "when", "typemap"):
            raise GenError("text_decode: %s lines are not supported" % t[0])
    doc = ET.fromstring(wire_text) if wire == "xml" else json.loads(wire_text)
    ent = {}
    for key, loc, tr in fields:
        if key in ent:          # 0.6: the earliest line present on the wire
            continue
        if wire == "xml":
            path, _, last = loc.rpartition("/")
            el = doc.find(path) if path else doc
            if el is None:
                continue
            raw = el.text if last == "#text" else el.get(last[1:])
        elif wire == "geojson":
            if loc.startswith("geometry."):
                c = (doc.get("geometry") or {}).get("coordinates") or []
                i = ("lon", "lat", "alt").index(loc.split(".")[1])
                raw = c[i] if i < len(c) else None
            elif loc.startswith("properties."):
                raw = (doc.get("properties") or {}).get(loc.split(".", 1)[1])
            else:
                raw = doc.get(loc)
        else:
            raise GenError("text_decode: wire %s" % wire)
        if raw is None:
            continue
        if tr == "string":
            ent[key] = str(raw)
        elif tr == "float":
            ent[key] = float(raw)
        elif tr == "int":
            ent[key] = int(raw)
        elif tr == "iso8601_ms":
            m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z", raw)   # offsets (0.6) not needed here
            if not m:
                raise GenError("transform-decode: %s" % raw)
            dt = datetime.datetime(*map(int, m.groups()[:6]), tzinfo=datetime.timezone.utc)
            ent[key] = int(dt.timestamp()) * 1000 + int((m.group(7) or "0").ljust(3, "0")[:3])
        else:
            raise GenError("text_decode: transform %s" % tr)
    return ent


def plain_float(v):
    """0.1.1 ruling 3: shortest round-trip decimal, never an exponent, no
    decimal point on an integer value, negative zero as 0."""
    import decimal
    if v == int(v):
        return str(int(v))
    return format(decimal.Decimal(repr(v)), "f")


def xml_encode(pack_text, ent):
    """encode() for the xml wire (engine-spec 0.1 with the 0.1.1 rulings, and the
    `const` and `default` lines of 0.6), for a pack without kinds whose locators
    are attributes, and an entity without residue. Attributes are written in
    line order, a `const` at the place of its line; an element is created where
    the first line that writes into it stands; an empty element closes itself."""
    import datetime
    root, lines, defaults = None, [], {}
    for t in top_lines(pack_text):
        if t[0] == "root":
            root = t[1]
        elif t[0] == "field":
            if len(t) != 4:
                raise GenError("xml_encode: field options are not supported")
            lines.append(t[1:4])
        elif t[0] == "const":
            lines.append((None, t[1], t[2]))
        elif t[0] == "default":
            defaults[t[1]] = t[2]
        elif t[0] in ("kind", "when", "typemap", "map"):
            raise GenError("xml_encode: %s lines are not supported" % t[0])
    if root is None:
        raise GenError("xml_encode: no root")
    top = {"name": root, "attrs": [], "kids": []}

    def text_of(key, tr):
        if key in ent:
            v = ent[key]
        elif key in defaults:       # 0.6: read as the type the transform writes
            d = defaults[key]
            v = d if tr == "string" else float(d) if tr == "float" else int(d)
        else:
            return None
        if tr == "string":
            if not isinstance(v, str):
                raise GenError("xml_encode: %s is not a string" % key)
            return v
        if tr == "float":
            return plain_float(float(v))
        if tr == "int" or tr == "iso8601_ms":
            if not isinstance(v, int):
                raise GenError("xml_encode: %s is not an integer" % key)
            if tr == "int":
                return str(v)
            dt = datetime.datetime.fromtimestamp(v // 1000, tz=datetime.timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (v % 1000)
        raise GenError("xml_encode: transform %s" % tr)

    for key, loc, third in lines:
        text = third if key is None else text_of(key, third)
        if text is None:
            continue
        path, _, last = loc.rpartition("/")
        if not last.startswith("@"):
            raise GenError("xml_encode: locator %s is not an attribute" % loc)
        el = top
        for name in (path.split("/") if path else []):
            nxt = next((k for k in el["kids"] if k["name"] == name), None)
            if nxt is None:
                nxt = {"name": name, "attrs": [], "kids": []}
                el["kids"].append(nxt)
            el = nxt
        if last[1:] not in [n for n, _ in el["attrs"]]:
            el["attrs"].append((last[1:], text))

    def write(el):
        attrs = "".join(' %s="%s"' % (n, v.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;"))
                        for n, v in el["attrs"])
        if not el["kids"]:
            return "<%s%s/>" % (el["name"], attrs)
        return "<%s%s>%s</%s>" % (el["name"], attrs, "".join(write(k) for k in el["kids"]), el["name"])
    return write(top)


def text_encode(pack_text, ent):
    """encode() for the geojson wire of engine-spec 0.1 (with the 0.1.1
    rulings 3 to 5), for a pack without kinds and an entity without residue;
    the xml wire through xml_encode."""
    if other_wire(pack_text) == "xml":
        return xml_encode(pack_text, ent)
    wire, fields = None, []
    for t in top_lines(pack_text):
        if t[0] == "wire":
            wire = t[1]
        elif t[0] == "field":
            fields.append(t[1:4])
        elif t[0] in ("kind", "when", "typemap"):
            raise GenError("text_encode: %s lines are not supported" % t[0])
    if wire != "geojson":
        raise GenError("text_encode: wire %s" % wire)
    coord, props, top = {}, [], []
    for key, loc, tr in fields:
        if key not in ent:
            continue
        v = ent[key]
        if tr == "string":
            if not isinstance(v, str):
                raise GenError("text_encode: %s is not a string" % key)
            js = json.dumps(v, ensure_ascii=False)
        elif tr == "float":
            js = plain_float(float(v))
        elif tr == "int":
            if not isinstance(v, int):
                raise GenError("text_encode: %s is not an integer" % key)
            js = str(v)
        else:
            raise GenError("text_encode: transform %s" % tr)
        if loc.startswith("geometry."):
            coord.setdefault(loc.split(".")[1], js)
        elif loc.startswith("properties."):
            props.append("%s:%s" % (json.dumps(loc.split(".", 1)[1]), js))
        else:
            top.append("%s:%s" % (json.dumps(loc), js))
    if "lon" in coord and "lat" in coord:
        arr = [coord["lon"], coord["lat"]] + ([coord["alt"]] if "alt" in coord else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(arr)
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{%s}%s}' % (
        geom, ",".join(props), "".join("," + t for t in top))


def would_derive(modules, keys):
    """The keys `convert` would add to an entity that has `keys` (engine-spec 0.6,
    derived keys), by presence only: this codec computes no derivation, so a
    vector it writes must not depend on one."""
    have, added = set(keys), set()
    for _ in range(8):
        progressed = False
        for name in sorted(modules):
            for tgt, args in modules[name]["derive"]:
                if tgt not in have and all(k in have for k in args):
                    have.add(tgt); added.add(tgt); progressed = True
        if not progressed:
            break
    return added


def mapped_keys(pack_text, modules):
    """The keys a pack has a `field` line for."""
    if other_wire(pack_text) == "protobuf":
        return pack_names(load_pack(pack_text, modules))
    return {t[1] for t in top_lines(pack_text) if t[0] == "field"}


def other_wire(pack_text):
    return next(t[1] for _, t in def_lines(pack_text) if t[0] == "wire")


def other_decode(pack_text, modules, wire_text):
    """decode() with another pack: a protobuf pack through the loader and codec
    above, a text pack through text_decode."""
    if other_wire(pack_text) == "protobuf":
        return engine_decode(load_pack(pack_text, modules), bytes.fromhex("".join(wire_text.split())))[0]
    return text_decode(pack_text, wire_text)


def other_encode(pack_text, modules, ent):
    """encode() of an entity that came from a different format (no kind)."""
    if other_wire(pack_text) == "protobuf":
        other = load_pack(pack_text, modules)
        known = pack_names(other)
        return engine_encode(other, {k: v for k, v in ent.items() if k in known}, None)[0].hex()
    return text_encode(pack_text, {k: v for k, v in ent.items() if not isinstance(v, list)})


def within(part, whole):
    """True when `part` is `whole` as far as it goes: equal scalars; for a list,
    as many items, each item's keys and lists within the other's (a list
    converted between two formats keeps, per item, the keys both groups map)."""
    if isinstance(part, list):
        return (isinstance(whole, list) and len(part) == len(whole) and all(
            all(k in w and within(v, w[k]) for k, v in p.items()) for p, w in zip(part, whole)))
    return part == whole


def model_text(v):
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v)


def flat_model(ent, prefix="", values=None):
    """An entity as the `model` object of a vector (engine-spec 0.7, Vector
    additions): every key; for every list its `.#`, and of each item the first
    `values` keys (all when None) and its nested lists."""
    out = {}
    for k, v in ent.items():
        if not isinstance(v, list):
            out[prefix + k] = model_text(v)
    for k, v in ent.items():
        if isinstance(v, list):
            out["%s%s.#" % (prefix, k)] = str(len(v))
            for i, item in enumerate(v):
                shown = {x: y for x, y in item.items() if isinstance(y, list)}
                scal = [x for x, y in item.items() if not isinstance(y, list)]
                shown.update({x: item[x] for x in (scal if values is None else scal[:values])})
                out.update(flat_model(shown, "%s%s[%d]." % (prefix, k, i), values))
    return out


def model_lookup(ent, key):
    """The value a `model` key of a vector names: a key, `<list>.#` (a count,
    or `absent`), or `<list>[<i>].<key>` with further steps. None: not there."""
    if "[" in key:
        name, _, rest = key.partition("[")
        idx, _, rest = rest.partition("].")
        items = ent.get(name)
        if not isinstance(items, list) or int(idx) >= len(items):
            return None
        return model_lookup(items[int(idx)], rest)
    if key.endswith(".#"):
        items = ent.get(key[:-2])
        return len(items) if isinstance(items, list) else "absent"
    return ent.get(key)


def check_vectors(vec_dir, fmt, pack, old_pack):
    n = 0
    for path in sorted(glob.glob(os.path.join(vec_dir, "*.json"))):
        with open(path, encoding="utf-8") as fh:
            v = json.load(fh)
        if v["from"] != fmt:
            raise GenError("%s: vector is not from %s" % (path, fmt))
        b = bytes.fromhex("".join(v["input"].split()))
        ent, kind = engine_decode(pack, b)
        for k, want in v.get("model", {}).items():
            if k == "@kind":
                if kind != want:
                    raise GenError("%s: selected kind %s, vector says %s" % (path, kind, want))
                continue
            if k == "@complete" or v["model"].get("@complete"):
                continue        # checked on the derived entity (0.6); this loader does not derive
            got = model_lookup(ent, k)
            if got is None:
                raise GenError("%s: model key %s not decoded" % (path, k))
            ok = abs(got - float(want)) <= 1e-9 if isinstance(got, float) else str(got) == want
            if not ok:
                raise GenError("%s: model key %s is %r, vector says %s" % (path, k, got, want))
        if v["to"] == fmt:
            out = engine_encode(pack, ent, kind)[0].hex()
            if out != v["expect"]:
                raise GenError("%s: same-format round trip differs" % path)
        if old_pack is not None and not os.path.basename(path).startswith("gen-"):
            old_ent, _ = engine_decode(old_pack, b)
            if any(ent.get(k) != v for k, v in old_ent.items()):
                raise GenError("%s: the superseded pack decodes %r, this pack decodes %r" % (path, old_ent, ent))
        n += 1
    return n


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------

def quote(s):
    s = re.sub(r"\s+", " ", s.replace('"', "'").replace("#", "")).strip()
    return '"%s"' % s


def key_meaning(lf):
    f = lf.field
    ty = f.type
    text = "%s.%s (%s)" % (lf.owner.name, f.name, ty)
    if f.kind == "enum":
        vals = ["%d=%s" % (n, nm) for nm, n in f.ref.values]
        more = len(vals) - 12
        text = "%s.%s (enum %s: %s%s)" % (lf.owner.name, f.name, f.ref.name, ", ".join(vals[:12]),
                                          ", and %d more" % more if more > 0 else "")
    if f.comment:
        text += ": " + f.comment
    return text


def sample_value(lf, i):
    f = lf.field
    if lf.transform == "pstring":
        return "%s-%d" % (snake(f.name), i)
    if lf.transform == "pdouble":
        return ((i * 7) % 160) / 4 + 0.25
    if lf.transform == "pfloat":
        return ((i * 5) % 64) / 8 + 0.125
    if lf.transform == "psint":
        return -(3 + i * 5)
    if f.kind == "enum":
        nz = [n for _, n in f.ref.values if n > 0]
        return nz[0] if nz else f.ref.values[0][1]
    if f.type == "bool":
        return 1
    return 100 + i * 37


def main(argv=None):
    global MAX_DEPTH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proto", nargs="+", required=True, help=".proto files (imports are resolved among them by file name)")
    ap.add_argument("--envelope", required=True, help="top-level message name")
    ap.add_argument("--format", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--out", required=True, help="root holding model/ and packs/")
    ap.add_argument("--source", action="append", required=True, help="source line text; repeatable")
    ap.add_argument("--map", action="append", default=[], metavar="PATH=KEY",
                    help="bind a field-number path to an existing model key (core key bare, else module.key)")
    ap.add_argument("--bind", action="append", default=[], metavar="KIND:PATH=KEY:TRANSFORM[:TABLE]",
                    help="a `field` line the walk does not produce, added to KIND: a path the schema reaches only "
                         "through a repeated field (one occurrence is carried, the last on decode), with a "
                         "protobuf transform and optionally `via TABLE`")
    ap.add_argument("--table", action="append", default=[], metavar="TABLE:NATIVE=MODEL",
                    help="one `map` line of a value table (engine-spec 0.6); repeatable, in order")
    ap.add_argument("--const", action="append", default=[], metavar="KIND:PATH=VALUE",
                    help="a `const` line of KIND: the unsigned integer written at PATH on every encode")
    ap.add_argument("--mandatory-option", default=None,
                    help="name of a custom field option whose `true` marks a mandatory field (proto2 `required` always counts)")
    ap.add_argument("--max-depth", type=int, default=MAX_DEPTH,
                    help="longest field-number path walked; a message field at this depth is not descended (default %(default)s)")
    ap.add_argument("--max-group-nesting", type=int, default=None,
                    help="how many `group` blocks may stand inside one another (default: as many as --max-depth "
                         "allows; lowered by the run when the module would pass %d keys and lists)" % KEY_BUDGET)
    ap.add_argument("--max-item-depth", type=int, default=None,
                    help="longest field-number path inside one item of a group (default: as --max-depth allows; "
                         "lowered by the run when pack.def would pass %d `field` lines)" % LINE_BUDGET)
    ap.add_argument("--names-from", action="append", default=[], metavar="FILE=PREFIX",
                    help="names file of another pack whose envelope sits at field-number path PREFIX of this "
                         "envelope: its names are pinned here under that prefix, so both packs use one key "
                         "per field (with --module-base, in one module); a name of something inside a group "
                         "(it is pinned by message type, not by path) is taken as it is; read only; repeatable")
    ap.add_argument("--module-base", default=None,
                    help="existing model module this run extends: its key lines are kept as they are and "
                         "keys new in this run are appended; without it the module file is written afresh")
    ap.add_argument("--cross-text", action="append", default=[], metavar="PACKDEF",
                    help="write two vectors against the pack PACKDEF (geojson, xml with attribute locators, or "
                         "protobuf using modules under --out): this pack's default (or only) kind into it, from "
                         "the generated round-trip message, and the result back; the vector back is checked and "
                         "not written when --cross has written one from that format; repeatable")
    ap.add_argument("--cross-omit", action="append", default=[], metavar="PATH",
                    help="field-number path left out of the message --cross-text converts; for a path bound to a "
                         "key that a `derive` line of a model module reads, when the derived key is one the "
                         "other pack writes (the run stops and names the keys otherwise); repeatable")
    ap.add_argument("--cross-kind", default=None,
                    help="kind whose generated message --cross-text converts (default: the default kind, else the first)")
    ap.add_argument("--kinds-from-fields", action="store_true",
                    help="proto2 union envelope: every singular message field of the envelope is a kind")
    ap.add_argument("--common-member", action="append", default=[], metavar="FIELD",
                    help="with --kinds-from-fields: a singular message field of the envelope that may stand beside "
                         "any other member. Its fields are common lines, read in every kind; it is also a kind of "
                         "its own with no line, written after the default kind and selected when the member "
                         "stands alone; repeatable")
    ap.add_argument("--no-comments", action="store_true",
                    help="take names, field numbers and types only: no comment of a schema file reaches the "
                         "module, the pack or pack.md")
    ap.add_argument("--default-kind", default=None,
                    help="kind an entity from another format encodes as: it is written last and requires shared keys")
    ap.add_argument("--default-requires", nargs="+", default=None,
                    help="the default kind's requires (default: every core key it maps)")
    ap.add_argument("--names-file", default=None,
                    help="JSON map of path to key name, read and rewritten, so key names stay fixed across runs")
    ap.add_argument("--cross", action="append", default=[], metavar="PACKDEF=VECTOR:FIELD",
                    help="write a vector from another format into this one: decode FIELD (input or expect) of "
                         "an existing VECTOR file with the text pack PACKDEF, encode with this pack")
    ap.add_argument("--supersedes", default=None, help="pack.def this output replaces; its vectors must decode identically")
    ap.add_argument("--notes-file", default=None, help="markdown placed in pack.md after the shared-key table")
    ap.add_argument("--pack-version", default="0.2.0")
    ap.add_argument("--module-version", default="0.1.0")
    a = ap.parse_args(argv)
    MAX_DEPTH = a.max_depth

    schema = load_schema(a.proto, a.mandatory_option)
    if a.no_comments:
        for m in schema.messages.values():
            for f in m.fields:
                f.comment = ""
    if a.common_member and not a.kinds_from_fields:
        raise GenError("--common-member needs --kinds-from-fields")
    env = [m for m in schema.messages.values() if m.name == a.envelope or m.full == a.envelope]
    if len(env) != 1:
        raise GenError("envelope %s matches %d messages" % (a.envelope, len(env)))
    env = env[0]

    core_map = {}
    for m in a.map:
        p, _, k = m.partition("=")
        core_map[p] = k
    # a repeated field a --bind path passes through stays one occurrence, read by that line
    bound = set()
    for spec in a.bind:
        m = re.fullmatch(r"[^:]+:([0-9.]+)=.*", spec)
        if m:
            nums = tuple(map(int, m.group(1).split(".")))
            bound |= {nums[:k] for k in range(1, len(nums))}
    pinned = {}
    if a.names_file and os.path.exists(a.names_file):
        with open(a.names_file, encoding="utf-8") as fh:
            pinned = json.load(fh)
    own_pinned = dict(pinned)
    inherited = 0
    for spec in a.names_from:
        nfile, _, prefix = spec.rpartition("=")
        if not nfile or not PATH_RE.fullmatch(prefix):
            raise GenError("--names-from %s: want FILE=PREFIX with PREFIX a field-number path" % spec)
        with open(nfile, encoding="utf-8") as fh:
            for p, name in json.load(fh).items():
                # a path is prefixed; a name pinned by message type (inside a group) is not
                ident = prefix + "." + p if p[:1].isdigit() else p
                if pinned.setdefault(ident, name) != name:
                    raise GenError("--names-from %s: %s is already pinned to another name" % (spec, ident))
                inherited += 1
    base_text, base = "", {"keys": {}, "lists": set(), "sources": []}
    if a.module_base:
        with open(a.module_base, encoding="utf-8") as fh:
            base_text = fh.read()
        base = load_module(base_text)
        if base["module"] != a.module:
            raise GenError("--module-base is module %s, not %s" % (base["module"], a.module))
        if base["distribution"] != "public":
            raise GenError("--module-base is not a public module")

    def plan(max_nest, item_depth):
        """Walk the envelope and name everything. kinds: (name, when path or None, leaves)."""
        room = [LINE_BUDGET]
        lim = dict(bound=bound, max_nest=max_nest, item_depth=item_depth, room=room)
        common, skipped_common, common_groups = [], [], []
        kinds, skipped, kgroups, empty_kinds = [], {}, {}, []
        # kinds: every member of the envelope's oneof(s); none -> one kind, the envelope itself
        members = [f for f in env.fields if f.oneof]
        if a.kinds_from_fields:
            members = [f for f in env.fields if f.kind == "message" and f.label != "repeated"]
        beside = [f for f in members if f.name in a.common_member]
        if len(beside) != len(set(a.common_member)):
            raise GenError("--common-member: not a singular message field of %s: %s" % (
                env.name, " ".join(sorted(set(a.common_member) - {f.name for f in beside}))))
        if members:
            shell = Message(env.full, env.name, env.syntax)
            shell.fields = [f for f in env.fields if f not in members or f in beside]
            walk(shell, (), (), (env.full,), True, (), common, skipped_common, common_groups, **lim)
            for f in members:
                name = snake(f.name)
                leaves, sk, groups = [], [], []
                if f in beside:
                    # its fields are common lines; the kind has none of its own
                    if not any(l.nums[0] == f.number for l in common):
                        raise GenError("--common-member %s has no mappable field outside a repeated one" % f.name)
                    skipped[name], kgroups[name] = [], []
                    kinds.append((name, f.number, []))
                    continue
                if f.kind != "message" or f.label == "repeated":
                    raise GenError("oneof member %s is not a singular message" % f.name)
                walk(f.ref, (f.number,), (), (env.full, f.ref.full), True, (), leaves, sk, groups, **lim)
                for x in leaves + groups:
                    x.kind = name
                skipped[name], kgroups[name] = sk, groups
                kinds.append((name, f.number, leaves))
                if not leaves and not groups:
                    empty_kinds.append((name, f.number))
        else:
            name = snake(env.name)
            leaves, sk, groups = [], [], []
            walk(env, (), (), (env.full,), True, (), leaves, sk, groups, **lim)
            for x in leaves + groups:
                x.kind = name
            kinds.append((name, None, leaves))
            skipped[name], kgroups[name] = sk, groups
        top = len(common) + sum(len(ls) for _, _, ls in kinds)
        if top + sum(1 for l in common + [l for _, _, ls in kinds for l in ls] if core_map.get(dotted(l.nums))) \
                + len(a.bind) + LINE_BUDGET - room[0] > LINE_BUDGET:
            raise TooBig()
        # a first-level list is named as a leaf at its place would be: a stand-in leaf
        stand = {}
        for name, _, ls in [(None, None, common)] + kinds:
            for g in (common_groups if name is None else kgroups[name]):
                lf = Leaf()
                lf.nums, lf.names, lf.owner, lf.field, lf.kind, lf.is_list = g.nums, g.names, g.owner, g.field, name, True
                stand[id(g)] = lf
        named = [(n, num, ls + [stand[id(g)] for g in kgroups[n]]) for n, num, ls in kinds]
        assign_keys(a.module, named, common + [stand[id(g)] for g in common_groups], core_map, pinned)
        top_groups = common_groups + [g for n, _, _ in kinds for g in kgroups[n]]
        for g in top_groups:
            g.list, g.path = stand[id(g)].key, stand[id(g)].path
        top_names = {l.key.split(".", 1)[1] for l in common + [l for _, _, ls in kinds for l in ls]}
        top_names |= {g.list.split(".", 1)[1] for g in top_groups}
        same = {}
        for l in common + [l for _, _, ls in kinds for l in ls]:
            same.setdefault(l.key.split(".", 1)[1], set()).add((l.owner.full, l.field.number))
        inner = assign_item_keys(a.module, top_groups, pinned, top_names | set(base["keys"]) | base["lists"], same)
        n_names = len(top_names | set(inner.values()) | set(base["keys"]) | base["lists"])
        return (common, skipped_common, common_groups, kinds, skipped, kgroups, empty_kinds, n_names)

    # Limits, lowered until the pack fits: the path length inside an item while pack.def
    # would hold more than LINE_BUDGET `field` lines, then the number of groups inside one
    # another; the nesting again while the module would hold more than KEY_BUDGET names.
    nest_asked = MAX_DEPTH if a.max_group_nesting is None else a.max_group_nesting
    depth_asked = MAX_DEPTH if a.max_item_depth is None else a.max_item_depth
    nest, item_depth = nest_asked, depth_asked
    while True:
        try:
            common, skipped_common, common_groups, kinds, skipped, kgroups, empty_kinds, n_names = plan(nest, item_depth)
        except TooBig:
            if item_depth > 1:
                item_depth -= 1
            elif nest > 0:
                nest -= 1
            else:
                raise GenError("pack.def would hold more than %d field lines with no group at all" % LINE_BUDGET)
            continue
        if n_names <= KEY_BUDGET:
            break
        if nest == 0:
            raise GenError("module %s would hold %d keys, over %d, with no group at all" % (a.module, n_names, KEY_BUDGET))
        nest -= 1

    if a.default_kind:
        if a.default_kind not in [k[0] for k in kinds]:
            raise GenError("--default-kind %s is not a kind" % a.default_kind)
        # stable: the kinds with fields or groups, then the default kind, then the kinds
        # with neither. A kind with no field requires only common keys (below); placed after the
        # default kind, an entity from another format that carries those common keys
        # (a node id the caller supplied, 0.6) still encodes as the default kind.
        # A generated vector keeps the number its kind had when the default kind was simply
        # last, so moving the kinds with no field renames no vector file.
        vec_number = {k[0]: i for i, k in enumerate(sorted(kinds, key=lambda k: k[0] == a.default_kind), 1)}
        kinds.sort(key=lambda k: 2 if not (k[2] or kgroups[k[0]]) else int(k[0] == a.default_kind))
    if not a.default_kind:
        vec_number = {k[0]: i for i, k in enumerate(kinds, 1)}
    all_leaves = common + [l for _, _, ls in kinds for l in ls]
    top_groups = common_groups + [g for n, _, _ in kinds for g in kgroups[n]]
    all_groups = flat_groups(top_groups)
    item_leaves = [l for g in all_groups for l in g.item_leaves()]
    if a.names_file:
        merged = dict(own_pinned)
        merged.update({l.path: l.key.split(".", 1)[1] for l in all_leaves + item_leaves})
        merged.update({g.path: g.list.split(".", 1)[1] for g in all_groups})
        os.makedirs(os.path.dirname(a.names_file), exist_ok=True)
        with open(a.names_file, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=1, sort_keys=True)
            fh.write("\n")
    unused = set(core_map) - {".".join(map(str, l.nums)) for l in all_leaves}
    if unused:
        raise GenError("--map paths that are not mapped leaves of the schema: %s" % sorted(unused))
    kind_names = [k[0] for k in kinds]
    binds, consts, tables = {}, {}, {}
    for spec in a.bind:
        m = re.fullmatch(r"([^:]+):([0-9.]+)=([^:]+):([a-z]+)(?::([^:]+))?", spec)
        if not m or m.group(1) not in kind_names or m.group(4) not in YIELDS:
            raise GenError("--bind %s: want KIND:PATH=KEY:TRANSFORM[:TABLE] with a kind of the schema" % spec)
        if m.group(2) in {l.path for l in all_leaves}:
            raise GenError("--bind %s: the walk maps that path; use --map" % spec)
        binds.setdefault(m.group(1), []).append((m.group(3), m.group(2), m.group(4), m.group(5)))
    for spec in a.const:
        m = re.fullmatch(r"([^:]+):([0-9.]+)=([0-9]+)", spec)
        if not m or m.group(1) not in kind_names:
            raise GenError("--const %s: want KIND:PATH=VALUE with a kind of the schema" % spec)
        consts.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
    for spec in a.table:
        m = re.fullmatch(r"([^:=]+):([^=]+)=(.+)", spec)
        if not m:
            raise GenError("--table %s: want TABLE:NATIVE=MODEL" % spec)
        tables.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
    for kind_binds in binds.values():
        for _, _, _, table in kind_binds:
            if table is not None and table not in tables:
                raise GenError("--bind names table %s, which has no --table line" % table)

    # ---- model module
    mod_keys, mod_lists = {}, {}
    for l in all_leaves + item_leaves:
        name = l.key.split(".", 1)[1]
        ty = YIELDS[l.transform]
        if name in mod_keys and mod_keys[name][0] != ty:
            raise GenError("key %s reached with two types" % name)
        mod_keys.setdefault(name, (ty, key_meaning(l) + ("; one item of the repeated field" if not l.nums else "")))
    for g in all_groups:
        f = g.field
        what = "%s.%s (repeated %s)" % (g.owner.name, f.name, f.type)
        holds = ("each item holds %s" % g.scalar.key if g.scalar else
                 "each item is one %s message" % f.ref.name)
        mod_lists.setdefault(g.list.split(".", 1)[1], "%s%s; %s" % (what, ": " + f.comment if f.comment else "", holds))
    both = set(mod_keys) & set(mod_lists)
    if both:
        raise GenError("%s is a key and a list" % sorted(both)[0])
    base_keys, base_sources, base_lists = base["keys"], base["sources"], base["lists"]
    base_lines = [ln for ln in base_text.split("\n") if ln.split()[:1] in (["key"], ["list"])]
    for k, (ty, _) in mod_keys.items():
        if k in base_keys and base_keys[k] != ty:
            raise GenError("key %s is %s in --module-base and %s here" % (k, base_keys[k], ty))
        if k in base_lists:
            raise GenError("%s is a list in --module-base and a key here" % k)
    for k in mod_lists:
        if k in base_keys:
            raise GenError("%s is a key in --module-base and a list here" % k)
    new_keys = {k: v for k, v in mod_keys.items() if k not in base_keys}
    new_lists = {k: v for k, v in mod_lists.items() if k not in base_lists}
    if len(base_keys) + len(base_lists) + len(new_keys) + len(new_lists) != n_names:
        raise GenError("the module holds %d names, the plan counted %d" % (
            len(base_keys) + len(base_lists) + len(new_keys) + len(new_lists), n_names))
    w = max(len(k) for k in (new_keys or mod_keys))
    lines = ["# The %s module: raw keys of the %s format, one per schema field the" % (a.module, a.format),
             "# pack maps and no core or track key covers. Generated by",
             "# tools/gen/proto2pack.py from the sources below; edit the generator, not this file.",
             "module        %s" % a.module, "version       %s" % a.module_version, "distribution  public"]
    srcs = [quote(s) for s in base_sources]
    srcs += [quote(s) for s in a.source if quote(s) not in srcs]
    if a.module_base:
        lines[0:2] = ["# The %s module: raw keys shared by the packs that name it in a `uses` line," % a.module,
                      "# one per schema field a pack maps. Extended, never rewritten: a key keeps",
                      "# its line once it has one. Last extended for the %s format by" % a.format]
    lines += ["source        %s" % s for s in srcs]
    lines += base_lines
    lines += ["key  %-*s  %-6s  -  %s" % (w, k, ty, quote(mean)) for k, (ty, mean) in new_keys.items()]
    if new_lists:
        lw = max(len(k) for k in new_lists)
        if not base_lists:
            lines += ["# Lists (engine-spec 0.7): one per repeated field the pack maps as a `group`. The keys",
                      "# an item holds are keys of this module, named from the item's message type."]
        lines += ["list %-*s  %s" % (lw, k, quote(mean)) for k, mean in new_lists.items()]
    os.makedirs(os.path.join(a.out, "model"), exist_ok=True)
    mod_path = os.path.join(a.out, "model", a.module + ".def")
    with open(mod_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    # ---- requires per kind
    key_kinds = {}
    for name, _, ls in kinds:
        for l in ls:
            key_kinds.setdefault(l.key, set()).add(name)
    common_keys = {l.key for l in common}
    list_kinds = {}
    for name, _, _ in kinds:
        for g in kgroups[name]:
            list_kinds.setdefault(g.list, set()).add(name)
    requires = {}
    beside_kinds = {snake(f.name): f.number for f in env.fields if f.name in a.common_member}
    single = len(kinds) == 1 and kinds[0][1] is None
    for name, _, ls in kinds:
        if single:
            requires[name] = []          # one layout, no `when`: any entity encodes as it
            continue
        if name == a.default_kind:
            requires[name] = a.default_requires or [l.core for l in ls if l.core]
            if not requires[name]:
                raise GenError("default kind %s maps no shared key to require" % name)
            continue
        if name in beside_kinds:
            # its fields are common lines: the first of them, a raw key no other format carries
            requires[name] = [l.key for l in common if l.nums[0] == beside_kinds[name]][:1]
            continue
        if not ls and kgroups[name]:
            # no field of its own, and a repeated one: a list no other kind maps
            # (0.7: `requires <list>` holds when the list has at least one item)
            own = [g.list for g in kgroups[name] if list_kinds[g.list] == {name}]
            if not own:
                raise GenError("kind %s has only lists other kinds map too; nothing to require" % name)
            requires[name] = own[:1]
            continue
        if not ls:
            # nothing of its own to require: the mandatory common fields, so an
            # entity from another format never encodes as this kind
            requires[name] = [l.key for l in common if l.mandatory][:6]
            if not requires[name]:
                raise GenError("kind %s has no field and the envelope has no mandatory common field to require" % name)
            continue
        dist = [l for l in ls if l.key.startswith(a.module + ".") and key_kinds[l.key] == {name}
                and l.key not in common_keys]
        dist.sort(key=lambda l: len(l.nums))            # stable: shallow first, then schema order
        man = [l for l in dist if l.mandatory]
        requires[name] = [l.key for l in (man[:6] if man else dist[:1])]

    # ---- pack.def
    bound_keys = [b[0] for bs in binds.values() for b in bs]
    used_mods = sorted({k.split(".")[0] for k in [k for l in all_leaves for k in (l.key, l.core)] + bound_keys
                        if k and "." in k})
    kw = max(len(l.key) for l in all_leaves)
    pw = max(len(".".join(map(str, l.nums))) for l in all_leaves)

    def field_line(l):
        # a shared key and the raw key on one path (0.5 ruling 16): shared line
        # first, because on encode the earliest line whose key is present is written
        return "\n".join("field  %-*s  %-*s  %s" % (kw, k, pw, l.path, l.transform)
                         for k in (l.core, l.key) if k)

    def group_lines(g, ind=""):
        """A `group` block (engine-spec 0.7): paths inside it are relative to one item."""
        out = ["%sgroup  %s  %s" % (ind, g.list, dotted(g.nums))]
        if g.scalar:    # numeric transforms: both encodings read, the packed one written
            out.append("%s  field  %s  .  %s" % (ind, g.scalar.key, g.scalar.transform))
        out += ["%s  field  %s  %s  %s" % (ind, l.key, dotted(l.nums), l.transform) for l in g.leaves]
        for sg in g.groups:
            out += group_lines(sg, ind + "  ")
        return out + [ind + "end"]

    out = ["# %s: envelope message %s, protobuf. Generated by tools/gen/proto2pack.py" % (a.format, env.full),
           "# from the sources below; edit the generator, not this file. Paths are",
           "# dot-separated field numbers. Counts and what is not mapped: pack.md.",
           "format        %s" % a.format, "version       %s" % a.pack_version, "distribution  public"]
    out += ["source        %s" % quote(s) for s in a.source]
    out += ["uses          %s" % m for m in used_mods]
    out += ["wire          protobuf"]
    if common or common_groups:
        what = ("# common: fields of %s outside its oneof" % env.name if not beside_kinds else
                "# common: the fields of %s, a member that may stand beside any other" % " and ".join(
                    "%s.%s" % (env.name, f.name) for f in env.fields if f.name in a.common_member))
        out += ["", what] + [field_line(l) for l in common]
        out += [ln for g in common_groups for ln in group_lines(g)]
    for name, num, ls in kinds:
        out += ["", "kind      %s" % name]
        if num is not None:
            out += ["when      %d present" % num]
        if requires[name]:
            out += ["requires  %s" % " ".join(requires[name])]
        out += [field_line(l) for l in ls]
        out += ["field  %-*s  %-*s  %s%s" % (kw, key, pw, p, tr, "  via %s" % table if table else "")
                for key, p, tr, table in binds.get(name, [])]
        out += ["const  %-*s  %s" % (pw, p, v) for p, v in consts.get(name, [])]
        out += [ln for g in kgroups[name] for ln in group_lines(g)]
    if tables:
        out += ["", "# value tables: <table> <value on the wire> <value of the model key>"]
        tw = max(len(t) for t in tables)
        nw = max(len(n) for es in tables.values() for n, _ in es)
        out += ["map  %-*s  %-*s  %s" % (tw, t, nw, n, m) for t, es in tables.items() for n, m in es]
    pack_dir = os.path.join(a.out, "packs", a.format)
    vec_dir = os.path.join(pack_dir, "vectors")
    os.makedirs(vec_dir, exist_ok=True)
    pack_path = os.path.join(pack_dir, "pack.def")
    with open(pack_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")

    # ---- vectors: one same-format round trip per kind
    def build(leaves, groups, state, fixed, n_items, variant=0):
        """One message of a scope: (tree for enc_tree, entity). Every leaf is
        present, one member per oneof so the bytes are a valid message of the
        schema; every group has `n_items` items at the first level and one below.
        Variant 0 sets, of every oneof, the member with a shared key, else the
        lowest field number; variant j the member j places further on."""
        members = {}
        for x in leaves + groups:
            for o in x.oneofs:
                rank = (0 if getattr(x, "core", None) else 1, o[2])
                best = members.setdefault((o[0], o[1], o[3]), {})
                best[o[2]] = min(rank, best.get(o[2], rank))
        pick = {}
        for gid, ms in members.items():
            order = sorted(ms, key=lambda n: ms[n])
            pick[gid] = (None, order[variant % len(order)])
        tree, ent = {}, {}
        for l in leaves:
            i = state[0]
            state[0] += 1
            if any(pick[(o[0], o[1], o[3])][1] != o[2] for o in l.oneofs):
                continue
            v = sample_value(l, i)
            v = int(fixed[l.path]) if l.path in fixed else v
            if l.core and l.core in ent:
                # one shared key at several paths (0.6): encode writes one value at each,
                # so the message that comes back byte for byte holds one value there
                v = ent[l.core]
            node = tree
            for n in l.nums[:-1]:
                node = node.setdefault(n, {})
            node[l.nums[-1]] = (l.transform, v)
            ent[l.key] = v
            if l.core:
                ent[l.core] = v
        for g in groups:
            if any(pick[(o[0], o[1], o[3])][1] != o[2] for o in g.oneofs):
                continue
            state[1].add(id(g))
            node = tree
            for n in g.nums[:-1]:
                node = node.setdefault(n, {})
            count = n_items if g.level == 1 else 1
            if g.scalar:
                vals = []
                for _ in range(count):
                    vals.append(sample_value(g.scalar, state[0]))
                    state[0] += 1
                tr = g.scalar.transform
                node[g.nums[-1]] = Rep((tr, v) for v in vals) if tr == "pstring" else Packed(tr, vals)
                ent[g.list] = [{g.scalar.key: v} for v in vals]
            else:
                made = [build(g.leaves, g.groups, state, {}, n_items, variant) for _ in range(count)]
                node[g.nums[-1]] = Rep(t for t, _ in made)
                ent[g.list] = [e for _, e in made]
        return tree, ent

    for old in glob.glob(os.path.join(vec_dir, "gen-*.json")):
        os.remove(old)
    for n_items in (2, 1):
        samples, texts, groups_out, n_variants = {}, {}, 0, 0
        for name, num, ls in kinds:
            idx = vec_number[name]
            scope_groups = common_groups + kgroups[name]
            covered = set()     # groups some vector of the kind holds
            # a further vector per kind while it sets a oneof member that brings in a group no
            # earlier vector of the kind holds
            for variant in range(9):
                if variant and len(covered) == len(flat_groups(scope_groups)):
                    break
                state = [0, set()]      # next sample index; groups in this message
                if name in beside_kinds:
                    tree, ent = build([l for l in common if l.nums[0] == num], [], state, {}, n_items, variant)
                elif not ls and not kgroups[name]:
                    tree, ent = {num: {}}, {}       # the member alone, as an empty submessage (0.5 ruling 14)
                else:
                    tree, ent = build(common + ls, scope_groups, state, dict(consts.get(name, [])), n_items, variant)
                if variant and not state[1] - covered:
                    continue
                covered |= state[1]
                model = {"@kind": name}
                model.update(flat_model(ent, values=2))
                hexs = enc_tree(tree).hex()
                tag = "-oneof%d" % variant if variant else ""
                if not variant:
                    samples[name] = hexs
                n_variants += bool(variant)
                vec = {"name": "gen-%s-roundtrip%s" % (name, tag), "from": a.format, "to": a.format,
                       "input": hexs, "expect": hexs, "model": model}
                texts["gen-%02d-%s-roundtrip%s.json" % (idx, name, tag)] = json.dumps(vec, indent=2) + "\n"
            groups_out += len(flat_groups(scope_groups)) - len(covered)
        gen_bytes = sum(len(t.encode("utf-8")) for t in texts.values())
        if gen_bytes <= VECTOR_BUDGET:
            break
    for fname, text in texts.items():
        with open(os.path.join(vec_dir, fname), "w", encoding="utf-8") as fh:
            fh.write(text)

    # ---- self-check: reload everything this run wrote, with the independent loader
    modules = {}
    for p in sorted(glob.glob(os.path.join(a.out, "model", "*.def"))):
        with open(p, encoding="utf-8") as fh:
            m = load_module(fh.read())
        if m["module"] in modules:
            raise GenError("duplicate-module: %s" % m["module"])
        modules[m["module"]] = m
    if "core" not in modules:
        raise GenError("unknown-module: core (copy model/core.def into %s/model)" % a.out)
    with open(pack_path, encoding="utf-8") as fh:
        pack = load_pack(fh.read(), modules)
    if pack["format"] != a.format or len(pack["kinds"]) != len(kinds):
        raise GenError("reloaded pack differs from what was generated")
    for k in pack["kinds"]:
        if not k["requires"] and k is not pack["kinds"][-1]:
            raise GenError("kind %s has no requires and would shadow the kinds after it on encode" % k["name"])
    if a.default_kind:
        after = [k for k in pack["kinds"][[k["name"] for k in pack["kinds"]].index(a.default_kind) + 1:]]
        if any(k["fields"] or k["groups"] for k in after):
            raise GenError("a kind with fields follows the default kind")
    old_pack = None
    if a.supersedes:
        with open(a.supersedes, encoding="utf-8") as fh:
            old_pack = load_pack(fh.read(), modules)
        if old_pack["format"] != a.format:
            raise GenError("--supersedes names format %s" % old_pack["format"])
        new_bind = {(k, p, t) for g in [pack["common"]] + pack["kinds"] for k, p, t, _ in g["fields"]}
        for k, p, t, _ in old_pack["common"]["fields"]:
            if (k, p, t) not in new_bind:
                raise GenError("superseded mapping %s %s %s is not preserved" % (k, p, t))
    n_vec = check_vectors(vec_dir, a.format, pack, old_pack)
    pack_keys = pack_names(pack)

    # ---- vectors from another format into this one
    cross = []
    for spec in a.cross:
        packdef, _, rest = spec.partition("=")
        vfile, _, vfield = rest.rpartition(":")
        with open(packdef, encoding="utf-8") as fh:
            src_text = fh.read()
        src_fmt = next(t[1] for _, t in def_lines(src_text) if t[0] == "format")
        with open(vfile, encoding="utf-8") as fh:
            src_vec = json.load(fh)
        if src_vec["to" if vfield == "expect" else "from"] != src_fmt:
            raise GenError("--cross %s: that text is not %s" % (spec, src_fmt))
        ent = other_decode(src_text, modules, src_vec[vfield])
        b, chosen = engine_encode(pack, ent, None)
        if a.default_kind and chosen != a.default_kind:
            raise GenError("--cross %s: encoded as kind %s, not the default kind" % (spec, chosen))
        derived = would_derive(modules, ent) & pack_keys
        if derived:
            raise GenError("--cross %s: the engine would derive %s, which this pack writes" % (
                spec, " ".join(sorted(derived))))
        back, back_kind = engine_decode(pack, b)
        if back_kind != chosen:
            raise GenError("--cross %s: output decodes as kind %s" % (spec, back_kind))
        carried = sorted(k for k in ent if k in back)
        for k in carried:
            if back[k] != ent[k]:
                raise GenError("--cross %s: key %s does not survive" % (spec, k))
        if vfield == "expect" and src_vec["from"] == a.format and "".join(src_vec["input"].split()) != b.hex():
            raise GenError("--cross %s: does not return the bytes that vector started from" % spec)
        out_dir = os.path.join(a.out, "packs", src_fmt, "vectors")
        os.makedirs(out_dir, exist_ok=True)
        vec = {"name": "gen-%s-to-%s" % (src_fmt, a.format), "from": src_fmt, "to": a.format,
               "input": src_vec[vfield], "expect": b.hex(),
               "model": flat_model(ent, values=2)}
        vpath = os.path.join(out_dir, "gen-%s-to-%s.json" % (src_fmt, a.format))
        with open(vpath, "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2)
            fh.write("\n")
        cross.append((src_fmt, chosen, carried, [k for k in ent if k not in back], vpath))
    cross_written = {c[4] for c in cross}

    # ---- vectors into a text format and back, from the generated message of one kind
    cross_out = []
    for packdef in a.cross_text:
        with open(packdef, encoding="utf-8") as fh:
            tgt_text = fh.read()
        tgt_fmt = next(t[1] for _, t in def_lines(tgt_text) if t[0] == "format")
        kname = a.cross_kind or a.default_kind or kinds[0][0]
        if kname not in samples:
            raise GenError("--cross-kind %s is not a kind" % kname)
        sample = samples[kname]
        ent, got_kind = engine_decode(pack, bytes.fromhex(sample))
        if got_kind != kname:
            raise GenError("--cross-text: the %s message decodes as kind %s" % (kname, got_kind))
        if a.cross_omit:
            omit = {tuple(map(int, p.split("."))) for p in a.cross_omit}
            lines = pack["common"]["fields"] + next(k for k in pack["kinds"] if k["name"] == kname)["fields"]
            if omit - {path for _, path, _, _ in lines}:
                raise GenError("--cross-omit: kind %s has no field at %s" % (
                    kname, " ".join(".".join(map(str, p)) for p in sorted(omit - {path for _, path, _, _ in lines}))))
            kept = {k: v for k, v in ent.items() if k not in {key for key, path, _, _ in lines if path in omit}}
            sample = engine_encode(pack, kept, kname)[0].hex()
            ent, got_kind = engine_decode(pack, bytes.fromhex(sample))
            if got_kind != kname or ent != kept:
                raise GenError("--cross-omit: the %s message without those paths does not decode as it was built" % kname)
        derived = would_derive(modules, ent) & mapped_keys(tgt_text, modules)
        if derived:
            raise GenError("--cross-text %s: the engine would derive %s, which that pack writes; "
                           "leave the paths bound to the keys it derives from out with --cross-omit" % (
                               packdef, " ".join(sorted(derived))))
        text = other_encode(tgt_text, modules, ent)
        seen = other_decode(tgt_text, modules, text)
        for k, v in seen.items():
            if k not in ent or not within(v, ent[k]):
                raise GenError("--cross-text %s: key %s does not survive" % (packdef, k))
        model = {"@kind": kname}
        model.update(flat_model(seen, values=2))
        vec = {"name": "gen-%s-to-%s" % (a.format, tgt_fmt), "from": a.format, "to": tgt_fmt,
               "input": sample, "expect": text, "model": model}
        vpath = os.path.join(vec_dir, "gen-%s-to-%s.json" % (a.format, tgt_fmt))
        with open(vpath, "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2)
            fh.write("\n")
        cross_out.append((tgt_fmt, kname, sorted(seen), vpath))
        # and back: the text just written, into this pack
        out_dir = os.path.join(a.out, "packs", tgt_fmt, "vectors")
        os.makedirs(out_dir, exist_ok=True)
        vec = {"name": "gen-%s-to-%s" % (tgt_fmt, a.format), "from": tgt_fmt, "to": a.format, "input": text}
        vpath = os.path.join(out_dir, "gen-%s-to-%s.json" % (tgt_fmt, a.format))
        derived = would_derive(modules, seen) & pack_keys
        if derived:
            raise GenError("--cross-text %s: on the way back the engine would derive %s, which this pack writes" % (
                packdef, " ".join(sorted(derived))))
        try:
            b, chosen = engine_encode(pack, seen, None)
        except GenError as e:
            if str(e) != "no-kind":
                raise
            vec["expect_error"] = "no-kind"
            cross.append((tgt_fmt, None, [], sorted(seen), vpath))
        else:
            if a.default_kind and chosen != a.default_kind:
                raise GenError("--cross-text %s: encoded as kind %s, not the default kind" % (packdef, chosen))
            back, back_kind = engine_decode(pack, b)
            if back_kind != chosen:
                raise GenError("--cross-text %s: output decodes as kind %s" % (packdef, back_kind))
            for k in seen:
                if k in back and not within(back[k], seen[k]):
                    raise GenError("--cross-text %s: key %s does not survive" % (packdef, k))
            if other_encode(tgt_text, modules, back) != text:
                raise GenError("--cross-text %s: the text does not come back" % packdef)
            vec["expect"] = b.hex()
            cross.append((tgt_fmt, chosen, sorted(k for k in seen if k in back),
                          [k for k in seen if k not in back], vpath))
        vec["model"] = flat_model(seen, values=2)
        if vpath in cross_written:
            cross.pop()         # --cross wrote the vector from that format; this one was checked only
            continue
        with open(vpath, "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2)
            fh.write("\n")

    # ---- pack.md
    reasons = {}
    for sk in list(skipped.values()) + [skipped_common]:
        for r, *_ in sk:
            reasons[r] = reasons.get(r, 0) + 1
    seen_r = set()

    def reach_all(m):
        if m.full in seen_r:
            return
        seen_r.add(m.full)
        for f in m.fields:
            if f.kind == "message":
                reach_all(f.ref)
    reach_all(env)
    n_fields = sum(1 + bool(l.core) for l in all_leaves) + len(bound_keys) + len(item_leaves)
    walked = {l.owner.full for l in all_leaves + item_leaves} | {
        m.full for sk in list(skipped.values()) + [skipped_common] for _, _, m, _ in sk}
    n_top = len(top_groups)
    scalar_groups = sum(1 for g in all_groups if g.scalar)
    limits = []
    if item_depth < depth_asked:
        limits.append("Inside an item a path is at most %d field numbers long (`--max-item-depth`, lowered by the run "
                      "from %d): with longer paths pack.def would hold more than %d `field` lines." % (
                          item_depth, depth_asked, LINE_BUDGET))
    if nest < nest_asked:
        limits.append("Groups stand at most %d inside one another (`--max-group-nesting`, lowered by the run from %d) "
                      "to keep pack.def within %d `field` lines and module `%s` within %d keys and lists." % (
                          nest, nest_asked, LINE_BUDGET, a.module, KEY_BUDGET))
    if n_items == 1:
        limits.append("The generated vectors hold one item per group: with two they would pass %d bytes." % VECTOR_BUDGET)
    core_lines = [l for l in all_leaves if l.core]
    md = ["# Pack: %s" % a.format, "",
          "Generated by `tools/gen/proto2pack.py` from the envelope message `%s`." % env.full,
          "Wire `protobuf`, engine-spec version 0.5 (message kinds) with the `const`, `map` and `via` lines",
          "of version 0.6 where the generator was given them, and a `group` block of version 0.7 for every",
          "`repeated` field it maps. Edit the generator, not this file.", "",
          "## Sources", ""] + ["- %s" % s for s in a.source] + ["",
          "## Schema", "",
          "| | Count |", "|---|---|",
          "| .proto files read | %d |" % len(a.proto),
          "| messages defined | %d |" % len([m for m in schema.messages.values() if not m.full.startswith("google.")]),
          "| enums defined | %d |" % len(schema.enums),
          "| messages reachable from `%s` (through repeated fields too) | %d |" % (env.name, len(seen_r)),
          "| message types on the walked paths | %d |" % len(walked),
          "| kinds | %d |" % len(kinds),
          "| `field` lines | %d |" % n_fields,
          "| of those, inside a `group` | %d |" % len(item_leaves),
          "| `group` blocks | %d |" % len(all_groups),
          "| of those, inside another group | %d |" % (len(all_groups) - n_top),
          "| of those, a repeated scalar (one `.` field) | %d |" % scalar_groups,
          "| keys in module `%s` | %d |" % (a.module, len(base_keys) + len(new_keys)),
          "| lists in module `%s` | %d |" % (a.module, len(base_lists) + len(new_lists)),
          "| `field` lines bound to `core` or `track` keys | %d |" % (len(core_lines) + len(bound_keys)),
          "| `const` lines | %d |" % sum(len(c) for c in consts.values()),
          "| value tables (`map` lines) | %d (%d) |" % (len(tables), sum(len(e) for e in tables.values())),
          "| vectors (existing and generated) | %d |" % n_vec, "",
          "## Kinds", "",
          "| Kind | Selected by | Fields | Groups | Fields in groups | Requires |", "|---|---|---|---|---|---|"]
    # rows for the options a run was given; a run without them keeps the table above
    if a.module_base:
        at = md.index("| keys in module `%s` | %d |" % (a.module, len(base_keys) + len(new_keys)))
        md.insert(at, "| keys of module `%s` this pack maps | %d |" % (a.module, len(mod_keys)))
    if MAX_DEPTH != DEFAULT_MAX_DEPTH:
        at = md.index("| `field` lines | %d |" % n_fields)
        md.insert(at, "| longest path walked (`--max-depth`) | %d |" % MAX_DEPTH)
    if a.cross_text:
        md.insert(md.index("## Kinds") - 1,
                  "| vectors to and from other formats, generated | %d |" % (len(cross) + len(cross_out)))
    def in_groups(groups):
        ag = flat_groups(groups)
        return len(ag), sum(len(g.item_leaves()) for g in ag)

    if common or common_groups:
        md.append("| (common) | every message | %d | %d | %d | |" % ((len(common),) + in_groups(common_groups)))
    for name, num, ls in kinds:
        md.append("| `%s` | %s | %d | %d | %d | %s |" % ((
            name, "`when %d present`" % num if num is not None else "always (the format has one layout)",
            len(ls)) + in_groups(kgroups[name]) + (" ".join("`%s`" % r for r in requires[name]) or "none",)))
    md += ["", "## Repeated fields", "",
           "A `repeated` field is a `group` block and a list of module `%s` (engine-spec 0.7). The block's" % a.module,
           "path is the field-number path of the repeated field from the scope the block stands in: the",
           "message for a block of a kind, one item for a block inside another block. Paths of the lines",
           "inside a block start at the item.", "",
           "- A repeated message: each occurrence is an item. Its fields are the block's `field` lines, a",
           "  repeated field inside it is a nested block. An item has no residue: a field of the item",
           "  that no line maps is dropped on decode, so only an item whose every field is mapped comes back",
           "  byte for byte.",
           "- A repeated string, number, bool or enum: a block with one line, `field <key> . <transform>`.",
           "  With `pvarint`, `psint`, `pdouble` and `pfloat` decode accepts one occurrence per value and the",
           "  packed form, and encode writes the packed form; `pstring` is one occurrence per item. A message",
           "  that arrives unpacked therefore leaves packed: the same values, other bytes.",
           "- A list is named as a field at its place would be. A list inside an item, and every key of an",
           "  item, is named from the item's message type and the path inside the item, so every list of",
           "  one message type holds the same keys; where that name is the key the same schema field",
           "  has outside any group, the item uses that key. Names are pinned in the names file under",
           "  `<path>[]`, `<message>:<path in the item>` and `<message>:<field>[]item`.",
           "- No key of an item is bound to a `core` or `track` key.",
           "- `requires` of a kind whose only content is repeated names a list of the kind: it holds when",
           "  the list has at least one item."]
    if any(r == R_BOUND for sk in list(skipped.values()) + [skipped_common] for r, *_ in sk):
        md += ["- A repeated message that a hand binding reads through (below) is not a group: a `field` and a",
               "  `group` on one path are not defined together. One occurrence of it is carried, the last on decode."]
    if limits:
        md += [""] + limits
    md += ["", "## Mapped to shared keys", ""]
    if core_lines and a.no_comments:
        md += ["| Key | Path | Schema field |", "|---|---|---|"]
        md += ["| `%s` | `%s` | `%s.%s` (%s) |" % (l.core, ".".join(map(str, l.nums)), l.owner.name,
                                                 l.field.name, l.field.type) for l in core_lines]
    elif core_lines:
        md += ["| Key | Path | Schema field | Schema comment |", "|---|---|---|---|"]
        for l in core_lines:
            md.append("| `%s` | `%s` | `%s.%s` (%s) | %s |" % (l.core, ".".join(map(str, l.nums)), l.owner.name,
                                                             l.field.name, l.field.type, l.field.comment or "none"))
    else:
        md.append("None.")
    if core_lines:
        md += ["", "Each of these paths has two `field` lines (0.5 ruling 16): the shared key first, the",
               "raw key of module `%s` second. Decode fills both keys with the same value. On encode" % a.module,
               "the value written is that of the earliest line whose key is present: the shared key",
               "when the entity has it, the raw key only when the shared key is absent. So a consumer",
               "that changes the shared key and encodes back to this format gets the new value, and an",
               "entity from another format, which has only the shared key, writes it."]
    if binds:
        md += ["", "Bound by hand to a path the walk does not descend (a repeated message; one occurrence",
               "is carried, the last on decode):", "", "| Key | Path | Transform | Table |", "|---|---|---|---|"]
        md += ["| `%s` | `%s` | `%s` | %s |" % (key, p, tr, "`%s`" % table if table else "none")
               for bs in binds.values() for key, p, tr, table in bs]
    if consts:
        md += ["", "Constants, written on every encode of the kind over any field (engine-spec 0.6):", "",
               "| Kind | Path | Value |", "|---|---|---|"]
        md += ["| `%s` | `%s` | %s |" % (k, p, v) for k, cs in consts.items() for p, v in cs]

    def keys_cell(keys):
        """Every key when there are few; the shared keys and a count otherwise."""
        if len(keys) <= 12:
            return " ".join("`%s`" % k for k in keys) or "none"
        shared = [k for k in keys if "." not in k]
        if len(shared) == len(keys):
            return " ".join("`%s`" % k for k in keys)
        return "%s and %d keys of other modules" % (" ".join("`%s`" % k for k in shared), len(keys) - len(shared))

    md += ["", "## Encoding from another format", ""]
    if single:
        md += ["The pack has one kind, with no `when` and no `requires`: every entity encodes as `%s`," % kinds[0][0],
               "and the shared keys it carries are written."]
    elif a.default_kind and beside_kinds and kinds[0][0] == a.default_kind:
        md += ["Kinds are tried in pack order and the first whose `requires` keys are all present is used.",
               "`%s` is first and requires `%s`: an entity from another format that has" % (
                   a.default_kind, "` `".join(requires[a.default_kind])),
               "those keys encodes as `%s`. %s after it and" % (
                   a.default_kind, " ".join("`%s` stands" % n for n in beside_kinds)),
               "requires a raw key of module `%s`, which only a %s message or the caller (`convert`" % (a.module, a.format),
               "context) supplies; an entity that has the keys of no kind ends in `no-kind`."]
    elif a.default_kind:
        md += ["Kinds are tried in pack order and the first whose `requires` keys are all present is used.",
               "Every kind before `%s` requires raw keys of module `%s`%s" % (
                   a.default_kind, a.module,
                   " that no other kind of this pack" if a.module_base else ", which only a %s message" % a.format),
               "%s. `%s` requires `%s`: an entity from another format" % (
                   "maps" if a.module_base else "carries",
                   a.default_kind, "` `".join(requires[a.default_kind])),
               "that has those keys encodes as `%s`. The kinds after it have no field of their own and" % a.default_kind,
               "require only common keys, so they are reached only by an entity that lacks",
               "`%s`; one that has the keys of no kind ends in `no-kind`." % "` `".join(requires[a.default_kind])]
    else:
        md += ["Every kind requires raw keys of module `%s` that no other kind of this pack maps, so an entity" % a.module,
               "from a format that does not use that module ends in `no-kind`."]
    if cross:
        md += ["", "| From | Encodes as | Keys carried | Keys the pack has no place for | Vector |", "|---|---|---|---|---|"]
        for src_fmt, chosen, carried, dropped, vpath in cross:
            md.append("| `%s` | %s | %s | %s | `%s` |" % (
                src_fmt, "`%s`" % chosen if chosen else "error `no-kind`",
                keys_cell(carried), keys_cell(dropped), os.path.relpath(vpath, a.out)))
    if cross_out:
        md += ["", "## Encoding into another format", "",
               "A key crosses when the other pack maps it: the shared keys, and the keys of module `%s`" % a.module,
               "only into a pack that also uses that module.", "",
               "| To | From kind | Keys carried | Vector |", "|---|---|---|---|"]
        for tgt_fmt, kname, carried, vpath in cross_out:
            md.append("| `%s` | `%s` | %s | `%s` |" % (tgt_fmt, kname, keys_cell(carried),
                                                     os.path.relpath(vpath, a.out)))
        if a.cross_omit:
            md += ["", "The message converted is the generated round-trip message without the paths %s." % (
                       " ".join("`%s`" % p for p in a.cross_omit)),
                   "Each is bound to a key a `derive` line of a model module reads, and the key derived from it",
                   "is one the other pack writes; a vector states a derived value in `model`, never in the",
                   "expected output (engine-spec, derived keys)."]
    if a.notes_file:
        with open(a.notes_file, encoding="utf-8") as fh:
            md += ["", fh.read().rstrip("\n")]
    md += ["", "## Generated vectors", "",
           "`vectors/gen-<n>-<kind>-roundtrip.json`, one per kind: every mapped field of the kind, one member",
           "per `oneof` (the one bound to a shared key, else the lowest field number, so that the bytes are a",
           "message of the schema), and every group with %s and one item in a group inside" % (
               "two items" if n_items == 2 else "one item"),
           "another. Fields are in ascending number order, the items of a list one after another, a repeated",
           "number packed, so `input` equals `expect`. `model` holds every key of the message, `<list>.#` of",
           "every list and the first two keys of every item."]
    if n_variants:
        md += ["`gen-<n>-<kind>-roundtrip-oneof<j>.json` (%d): the same message with, of every `oneof`, the member" % n_variants,
               "j places further on; written when that brings in a group no earlier vector of the kind holds."]
    if groups_out:
        md += ["%d groups are in no vector: they lie under a `oneof` member no vector sets." % groups_out]
    md += [""]
    md += ["## Not mapped", "",
           "Counted once per place a field is reached in a kind's tree, inside groups too. Everything",
           "below a field that is not descended is not counted.", "",
           "| Reason | Fields |", "|---|---|"]
    for r in sorted(reasons, key=lambda r: -reasons[r]):
        md.append("| %s | %d |" % (r, reasons[r]))
    if not reasons:
        md.append("| (none) | 0 |")
    md += ["", "Per kind:", "", "| Kind | Mapped | Mapped inside groups | Not mapped |", "|---|---|---|---|"]
    if common or skipped_common or common_groups:
        md.append("| (common) | %d | %d | %d |" % (len(common), in_groups(common_groups)[1], len(skipped_common)))
    for name, _, ls in kinds:
        by = {}
        for r, *_ in skipped[name]:
            by[r] = by.get(r, 0) + 1
        md.append("| `%s` | %d | %d | %s |" % (name, len(ls), in_groups(kgroups[name])[1],
                                              ", ".join("%d %s" % (by[r], r) for r in sorted(by)) or "0"))
    if empty_kinds:
        md += ["", "Kinds with no mappable field: " + ", ".join("`%s` (field %d)" % e for e in empty_kinds) + ".",
               "Such a kind has a `when` line and no `field` line. Its message decodes to the common keys,",
               "and on encode the member is written as an empty length-delimited field (0.5 ruling 14),",
               "so the kind survives a round trip while the content of the message does not."]
    md += ["", "## What this pack does not express", "",
           "- `map` fields: no line addresses an entry by its key.",
           "- `bytes` and the fixed-width integer types, single or repeated: no transform yields them.",
           "- A value below path depth %d, and a message type that contains itself: the walk stops where a" % MAX_DEPTH,
           "  message type would stand inside itself, through a repeated field as through a single one.",
           "- An unmapped field of an item: items carry no residue (engine-spec 0.7).",
           "- The content of a message with no mappable field: its kind is kept, its fields are not.",
           "- Which member of a nested `oneof` is set: each member's fields are plain `field` lines of the kind",
           "  or of the group. An item is not decoded by a discriminator (0.7 has no `when` inside a group).",
           "- Enum names: an enum is carried as its number; the module key's meaning lists the names.",
           "- `google.protobuf.Timestamp`: carried as two raw integer keys (seconds, nanos); no transform joins them into `time_ms`.",
           ""]
    with open(os.path.join(pack_dir, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    report = {
        "format": a.format, "envelope": env.full,
        "files": len(a.proto),
        "messages_defined": len([m for m in schema.messages.values() if not m.full.startswith("google.")]),
        "enums_defined": len(schema.enums),
        "messages_reachable": len(seen_r), "message_types_walked": len(walked),
        "kinds": [{"name": n, "when": num, "fields": len(ls), "requires": requires[n],
                   "groups": in_groups(kgroups[n])[0], "fields_in_groups": in_groups(kgroups[n])[1],
                   "not_mapped": len(skipped[n])} for n, num, ls in kinds],
        "common_fields": len(common), "field_lines": n_fields,
        "module_keys": len(base_keys) + len(new_keys), "pack_module_keys": len(mod_keys), "shared_key_lines": len(core_lines),
        "not_mapped_by_reason": reasons, "vectors_checked": n_vec,
        "kinds_without_fields": [n for n, _ in empty_kinds],
        "cross_vectors": [{"from": c[0], "kind": c[1], "carried": c[2], "dropped": c[3]} for c in cross],
        "cross_out_vectors": [{"to": c[0], "kind": c[1], "carried": c[2]} for c in cross_out],
        "max_depth": MAX_DEPTH, "names_inherited": inherited,
        "groups": len(all_groups), "groups_first_level": n_top, "groups_nested": len(all_groups) - n_top,
        "groups_scalar": scalar_groups, "field_lines_in_groups": len(item_leaves),
        "module_lists": len(base_lists) + len(new_lists), "group_nesting_limit": nest, "item_depth_limit": item_depth,
        "limits_lowered": limits, "vector_items_per_group": n_items, "generated_vector_bytes": gen_bytes,
        "groups_in_no_vector": groups_out, "oneof_variant_vectors": n_variants,
        "module_keys_from_base": len(base_keys), "module_keys_new": len(new_keys),
    }
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except GenError as e:
        sys.stderr.write("proto2pack: %s\n" % e)
        sys.exit(1)
