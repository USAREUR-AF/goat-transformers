#!/usr/bin/env python3
"""proto2pack: turn public protobuf schemas into a goat-transformers pack.

Reads .proto files (proto2 and proto3), walks the envelope message, and writes
under --out:

  model/<module>.def                  raw keys of the format, one public module
  packs/<format>/pack.def             the pack (engine-spec 0.5 to 0.7, wire protobuf)
  packs/<format>/pack.md              what was mapped, what was not, and why
  packs/<format>/vectors/gen-*.json   a same-format round trip per kind, and the
                                      conversions --cross and --cross-text ask for
  packs/<other>/vectors/gen-<other>-to-<format>.json   the conversions into this format
  the --names-file                    the name of every key, so names stay fixed

The run has four steps, each a function of this file: parse (`load_schema`),
plan (`make_plan`: kinds, leaves, groups and keys, with the budget decisions
made), emit (`emit_module`, `emit_pack`, `emit_vectors`, `emit_pack_md`) and
self-check (`self_check`).

The self-check loads what the run wrote with gtcheck, as an engine would, and
decodes and encodes every vector of the pack, existing and generated, with a
small protobuf codec written from spec/engine-spec.md (0.3 to 0.7: `const`,
value tables, one key at several paths and `group` blocks; no derivations).
The run fails when a file does not load or a vector does not hold.

Usage: see --help. Run with `python3 -I`. Python 3 standard library only.
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

DEFAULT_MAX_DEPTH = 6
KEY_BUDGET = 60000              # keys and lists one module may hold
LINE_BUDGET = 100000            # `field` lines one pack.def may hold
VECTOR_BUDGET = 12 * 1024 * 1024    # bytes of generated vectors one pack may hold

# The three limits of a run. The defaults are the constants above; a test passes
# small ones to `main` to reach the code that lowers a limit.
Budgets = collections.namedtuple("Budgets", "keys lines vector_bytes")
DEFAULT_BUDGETS = Budgets(KEY_BUDGET, LINE_BUDGET, VECTOR_BUDGET)

R_BOUND = "repeated message a hand binding (--bind) reads through: one occurrence is carried"
R_EMPTY_GROUP = "repeated message with nothing mappable inside"
# The transform of each scalar type the protobuf wire of the specification can
# carry (engine-spec 0.3 "Transforms for `protobuf`").
SCALAR_TRANSFORM = {
    "string": "pstring", "double": "pdouble", "float": "pfloat",
    "int32": "pvarint", "int64": "pvarint", "uint32": "pvarint",
    "uint64": "pvarint", "bool": "pvarint",
    "sint32": "psint", "sint64": "psint",
}
FIXED_INTS = {"fixed32", "fixed64", "sfixed32", "sfixed64"}
ALL_SCALARS = set(SCALAR_TRANSFORM) | FIXED_INTS | {"bytes"}
YIELDS = gtcheck.PROTOBUF_TRANSFORMS       # transform -> the model type it yields
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
    "google/protobuf/any.proto": """
syntax = "proto3";
package google.protobuf;
message Any {
  string type_url = 1; // names the type of the message serialized in value
  bytes value = 2; // a serialized message of that type
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
    """A refused input or a failed check. `file` and `line` name the place in a
    source file when there is one; `str()` is `<file>:<line>: <message>`."""

    def __init__(self, message, file=None, line=None):
        super().__init__(message, file, line)
        self.message, self.file, self.line = message, file, line

    def __str__(self):
        if self.file is None:
            return self.message
        where = self.file if self.line is None else "%s:%d" % (self.file, self.line)
        return "%s: %s" % (where, self.message)


class NoKind(GenError):
    """Decode or encode found no kind for the message or the entity (the
    `no-kind` error of engine-spec 0.5)."""

    def __init__(self):
        super().__init__("no-kind")


class TooBig(Exception):
    """The plan passed the line budget; the caller lowers a limit and plans again."""


# --------------------------------------------------------------------------
# parse: .proto files -> Schema
# --------------------------------------------------------------------------

# The tokens of a .proto file. A string keeps its quotes; a word holds a name, a
# number or a dotted type name; comments and white space are not tokens.
TOKEN_RE = re.compile(r"""
    (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<word>[A-Za-z0-9_.+\-]+)
  | (?P<sym>[{}\[\]()<>=;,:])
  | (?P<ws>\s+)
""", re.S | re.X)


class Enum:
    """An enum: `full` is its name with package and enclosing messages."""

    def __init__(self, full, name):
        self.full, self.name, self.values = full, name, []  # (name, number)


class Field:
    """One field of a message, as declared."""

    def __init__(self):
        self.name = self.type = self.label = None
        self.number = 0
        self.line = None        # line of the field's first token
        self.oneof = None
        self.options = ""       # the tokens of `[...]`, joined by spaces
        self.comment = ""
        self.kind = None        # scalar | message | enum | map | group
        self.ref = None         # Message or Enum
        self.mandatory = False


class Message:
    """A message: `full` is its name with package and enclosing messages,
    `file` the .proto file that declares it."""

    def __init__(self, full, name, syntax, file=None):
        self.full, self.name, self.syntax, self.file = full, name, syntax, file
        self.fields = []
        self.oneofs = []        # oneof names, declaration order


class Schema:
    """Every message and enum of the files read, nested ones too."""

    def __init__(self):
        self.messages = {}      # full name -> Message, in declaration order
        self.enums = {}         # full name -> Enum


def tokenize_proto(path, text):
    """-> (tokens [(text, line)], comments {line: text of a `//` comment},
    code lines {line that holds a token})."""
    toks, comments, code_lines = [], {}, set()
    pos, line = 0, 1
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise GenError("cannot tokenise %r" % text[pos:pos + 20], path, line)
        k = m.lastgroup
        if k == "lc":
            comments[line] = m.group()[2:].strip().lstrip("/!").strip()
        elif k in ("str", "word", "sym"):
            toks.append((m.group(), line))
            code_lines.add(line)
        line += m.group().count("\n")
        pos = m.end()
    return toks, comments, code_lines


class Parser:
    """A recursive-descent parser of one .proto file. It keeps messages, enums,
    fields, oneofs and imports and skips what a pack has no use for: options,
    `reserved`, `extensions`, `extend`, `service` and the body of a proto2 group."""

    def __init__(self, schema, path, text):
        self.s, self.path = schema, path
        self.toks, self.comments, self.code_lines = tokenize_proto(path, text)
        self.i = 0
        self.syntax, self.package, self.imports = "proto2", "", []

    def fail(self, message):
        raise GenError(message, self.path, self.line())

    def peek(self, k=0):
        return self.toks[self.i + k][0] if self.i + k < len(self.toks) else None

    def line(self, k=0):
        if not self.toks:
            return 1
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j][1]

    def take(self, want=None):
        t = self.peek()
        if t is None:
            self.fail("the file ends inside a statement" if want is None
                      else "expected %r, found the end of the file" % want)
        if want is not None and t != want:
            self.fail("expected %r, found %r" % (want, t))
        self.i += 1
        return t

    def number(self):
        """A field or enum number: decimal, or hexadecimal with `0x`."""
        t = self.peek()
        try:
            value = int(t, 0)
        except (TypeError, ValueError):
            self.fail("expected a number, found %r" % t)
        self.i += 1
        return value

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
                self.fail("unexpected %r at file level" % t)

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
                e.values.append((vname, self.number()))
                self.skip_statement()
        self.take("}")
        self.s.enums[e.full] = e

    def field_comment(self, first_line, last_line):
        """The comment of a field: the `//` comment on the line the field ends
        on, else the run of comment-only lines directly above it."""
        if last_line in self.comments:
            return self.comments[last_line]
        out, ln = [], first_line - 1
        while ln in self.comments and ln not in self.code_lines:
            out.insert(0, self.comments[ln])
            ln -= 1
        return " ".join(out)

    def parse_field(self, msg, oneof):
        f = Field()
        first = f.line = self.line()
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
            f.number = self.number()
            self.skip_block()
            msg.fields.append(f)
            return
        f.name = self.take()
        self.take("=")
        f.number = self.number()
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
        m = Message(self.qual(scope, name), name, self.syntax, self.path)
        self.s.messages[m.full] = m
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


def resolve_type(schema, msg, field):
    """Set `kind` and `ref` of a field from its type name. A name is looked up
    in the scope of the message first, then in each enclosing scope; a name
    with a leading `.` is a full name."""
    if field.type in ALL_SCALARS:
        field.kind = "scalar"
        return
    if field.type.startswith("."):
        candidates = [field.type[1:]]
    else:
        candidates, scope = [], msg.full
        while True:
            candidates.append((scope + "." if scope else "") + field.type)
            if not scope:
                break
            scope = scope.rpartition(".")[0]
    for name in candidates:
        if name in schema.messages:
            field.kind, field.ref = "message", schema.messages[name]
            return
        if name in schema.enums:
            field.kind, field.ref = "enum", schema.enums[name]
            return
    raise GenError("%s.%s: type %s is not defined in the given files" % (msg.full, field.name, field.type),
                   msg.file, field.line)


def load_schema(paths, mandatory_option=None, comments=True):
    """Parse the .proto files and resolve every field type.

    An import is resolved among `paths` by file name; the well-known types of
    BUILTIN_PROTOS need no file. A field is mandatory when it is `required`
    (proto2) or carries the field option `mandatory_option` with the value
    true. With `comments` false no comment of a file is kept."""
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
        raise GenError("imports %s, which is not among the given files" % imp, src)
    mandatory_re = re.compile(r"\b%s\s*:\s*true\b" % re.escape(mandatory_option)) if mandatory_option else None
    for m in s.messages.values():
        for f in m.fields:
            f.mandatory = f.label == "required" or bool(mandatory_re and mandatory_re.search(f.options))
            if not comments:
                f.comment = ""
            if f.kind not in ("map", "group"):
                resolve_type(s, m, f)
    return s


# --------------------------------------------------------------------------
# plan, first part: walk the envelope
# --------------------------------------------------------------------------

def snake(name):
    """A schema name as part of a key name: `_` before every capital that
    follows a lower-case letter or a digit, lower case, and `_` for every
    character that is not a lower-case letter, a digit or `_`."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


class Leaf:
    """A scalar or enum field the pack maps with one `field` line (two when a
    --map key shares its path)."""

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
        self.core = None        # the first shared key of the path, or None
        self.cores = []         # every shared key of the path, in --map order
        self.is_list = False    # a stand-in that names a first-level list in assign_keys
        self.item = None        # Message whose item holds this leaf, inside a group
        self.path = None        # what the names file pins the key under
        self.cpath = ()         # field-name path of the container, set by assign_keys
        self.prefixed = False   # the container's name starts with the kind name


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
        self.path = None        # what the names file pins the list under

    def all_groups(self):
        out = [self]
        for g in self.groups:
            out += g.all_groups()
        return out

    def item_leaves(self):
        return ([self.scalar] if self.scalar else []) + self.leaves


def flat_groups(groups):
    """The groups and every group nested in them, each before what it holds."""
    return [x for g in groups for x in g.all_groups()]


def dotted(nums):
    """A field-number path as a pack writes it: `7.6.1`."""
    return ".".join(map(str, nums))


class Walk:
    """One walk of the envelope under fixed limits.

    `max_depth` is the longest field-number path from the envelope; a message
    field at that depth is not descended. `bound` holds the paths a --bind line
    reads through: a repeated field there stays one occurrence. `max_nest` is
    how many groups may stand inside one another, `item_depth` the longest path
    inside one item. `line_budget`, when given, is the number of `field` lines
    inside groups after which the walk stops with TooBig."""

    def __init__(self, max_depth, bound=frozenset(), max_nest=99, item_depth=99, line_budget=None):
        self.max_depth, self.bound = max_depth, bound
        self.max_nest, self.item_depth, self.line_budget = max_nest, item_depth, line_budget
        self.lines_in_groups = 0

    def count_line(self):
        self.lines_in_groups += 1
        if self.line_budget is not None and self.lines_in_groups > self.line_budget:
            raise TooBig()

    def message(self, msg, nums, names, chain, mandatory, oneofs, leaves, skipped, groups,
                base=(), level=0, item=None):
        """Depth-first through the fields of `msg`, in declaration order. A
        singular field is a leaf or is descended; a `repeated` field is a Group
        whose item is walked with paths relative to it. `skipped` collects
        (reason, absolute nums, owner, field). `chain` holds the message types
        on the way here, `base` the absolute path of the enclosing item,
        `level` the number of enclosing groups."""
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
                if level == 0 and ap in self.bound:
                    skipped.append((R_BOUND, ap, msg, f)); continue
                if level >= self.max_nest:
                    skipped.append(("repeated field below group nesting depth %d" % self.max_nest, ap, msg, f))
                    continue
                g = Group()
                g.nums, g.abs, g.names, g.owner, g.field, g.oneofs = p, ap, n, msg, f, one
                g.level, g.item = level + 1, item
                if f.kind == "message":
                    if f.ref.full in chain:
                        skipped.append(("recursive message type", ap, msg, f)); continue
                    if len(ap) >= self.max_depth:
                        skipped.append(("below depth %d" % self.max_depth, ap, msg, f)); continue
                    inner = []
                    self.message(f.ref, (), (), chain + (f.ref.full,), False, (), g.leaves, inner, g.groups,
                                 base=ap, level=level + 1, item=f.ref)
                    if not g.leaves and not g.groups:
                        skipped.append((R_EMPTY_GROUP, ap, msg, f)); continue
                    skipped.extend(inner)
                else:
                    g.scalar = self.leaf(msg, f, (), (), msg)
                    self.count_line()
                groups.append(g)
                continue
            if f.kind == "message":
                if f.ref.full in chain:
                    skipped.append(("recursive message type", ap, msg, f)); continue
                if len(ap) >= self.max_depth:
                    skipped.append(("below depth %d" % self.max_depth, ap, msg, f)); continue
                if level and len(p) >= self.item_depth:
                    skipped.append(("inside an item, below item depth %d" % self.item_depth, ap, msg, f)); continue
                self.message(f.ref, p, n, chain + (f.ref.full,), man, one, leaves, skipped, groups,
                             base=base, level=level, item=item)
                continue
            lf = self.leaf(msg, f, p, n, item)
            lf.mandatory, lf.oneofs = man, one
            leaves.append(lf)
            if level:
                self.count_line()

    @staticmethod
    def leaf(msg, f, nums, names, item):
        """The Leaf of a scalar or enum field; an enum is carried as its number."""
        lf = Leaf()
        lf.nums, lf.names, lf.owner, lf.field, lf.item = nums, names, msg, f, item
        lf.transform = "pvarint" if f.kind == "enum" else SCALAR_TRANSFORM[f.type]
        return lf


# --------------------------------------------------------------------------
# plan, second part: name every key and list
# --------------------------------------------------------------------------

def assign_keys(module, kinds, common, core_map, pinned):
    """Name every leaf: <container name>_<field name>. `kinds` is
    [(kind name, leaves)], `common` the leaves outside every kind; `core_map`
    maps a field-number path to the shared key --map gave it (kept in
    `leaf.core`; the leaf still gets its raw key).

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
    all_leaves = list(common) + [l for _, ls in kinds for l in ls]
    for lf in all_leaves:
        lf.cpath = lf.names[:-1]          # container path
        lf.prefixed = lf.kind is not None and not lf.cpath
        if lf.prefixed:
            lf.cpath = (lf.kind,)
        lf.path = ".".join(map(str, lf.nums)) + ("[]" if lf.is_list else "")
        lf.cores = core_map.get(lf.path, [])
        lf.core = lf.cores[0] if lf.cores else None
    containers, names = name_containers(all_leaves)
    idents = {}             # (container, field number) -> the leaves that are that field
    for c_id, ls in containers.items():
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


def name_containers(leaves):
    """Group the leaves by container and name every container that can be
    named apart from the others. -> ({container: its leaves}, {container: name}),
    both in the order the leaves are met. A container is (scope, message type,
    field-name path); where a name cannot be found and the leaf belongs to a
    kind, the kind name is put before the path and the naming starts again."""
    def cid(l):
        scope = "common" if l.kind is None else ("kind:" + l.kind if l.prefixed else "kind")
        return (scope, l.owner.full, l.cpath)

    def candidates(cp):
        """Shortest first; the last one is the whole path."""
        return ["_".join(cp[:1] + cp[-k:]) for k in range(1, len(cp) - 1)] + ["_".join(cp)]

    while True:
        containers = {}
        for l in leaves:
            containers.setdefault(cid(l), []).append(l)
        whole, anyc = {}, {}        # candidate name -> the containers it is the whole path of; could name
        for c_id in containers:
            cs = candidates(c_id[2])
            whole.setdefault(cs[-1], set()).add(c_id)
            for c in cs:
                anyc.setdefault(c, set()).add(c_id)
        names, failing = {}, []
        for c_id in containers:
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
            for l in containers[c_id]:
                if l.kind is not None and not l.prefixed:
                    l.prefixed, l.cpath, progressed = True, (l.kind,) + l.cpath, True
        if not progressed:
            return containers, names


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
# the protobuf wire, written from engine-spec 0.3 (0.7 for the packed form)
# --------------------------------------------------------------------------

def enc_varint(v):
    """A base-128 varint, low group first. A negative integer is written as
    its 64-bit two's complement (ten bytes), as protobuf does (0.5 ruling 15)."""
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
    """The bytes of one value after its tag: length and UTF-8 for `pstring`, a
    varint for `pvarint`, a zig-zag varint for `psint`, little-endian IEEE 754
    for `pdouble` (8 bytes) and `pfloat` (4 bytes)."""
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
    """(wire type, value) of the field at a field-number path, None when it or
    a submessage on the way is absent; of a repeated number the last occurrence."""
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
    """The model value of one occurrence; a wire type that is not the
    transform's is `transform-decode`."""
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
# packs as the codec reads them
#
# gtcheck loads a pack and applies the load rules of the specification. The
# codec below reads the Pack gtcheck returns through `wire_pack`, the one
# adapter; `check_protobuf_pack` holds what this generator asks of a protobuf
# pack beyond the load rules.
# --------------------------------------------------------------------------

class Scope:
    """The lines of one message that the codec reads: of the entity (the common
    lines, or those of one kind) or of one item of a group. `fields` holds
    (key, path, transform, table), `whens` and `consts` (path, value), `groups`
    GroupScope objects. A path is a tuple of field numbers; inside a group it
    is relative to the item, `()` for the `.` locator."""
    __slots__ = ("fields", "whens", "consts", "groups")

    def __init__(self):
        self.fields, self.whens, self.consts, self.groups = [], [], [], []


class GroupScope(Scope):
    """A `group` block: the list it fills and the path of the repeated field."""
    __slots__ = ("list", "path")


class KindScope(Scope):
    """A kind: its name and the keys of its `requires` lines."""
    __slots__ = ("name", "requires")


class WirePack:
    """A protobuf pack as the codec reads it: `common` (a Scope), `kinds`
    (KindScope objects in pack order) and the value tables."""

    def __init__(self, pack):
        self.format, self.tables = pack.format, pack.tables
        self.common = _fill_scope(Scope(), pack.common)
        self.kinds = []
        for kind in pack.kinds:
            scope = _fill_scope(KindScope(), kind.lines)
            scope.name, scope.requires = kind.name, list(kind.requires)
            self.kinds.append(scope)

    def kind(self, name):
        return next((k for k in self.kinds if k.name == name), None)

    def scope(self, kind):
        """(fields, consts, groups) of an entity of `kind` (None: common only)."""
        if kind is None:
            return self.common.fields, self.common.consts, self.common.groups
        return (self.common.fields + kind.fields, self.common.consts + kind.consts,
                self.common.groups + kind.groups)

    def names(self):
        """The entity keys and lists the pack maps (not the keys of items)."""
        out = set()
        for scope in [self.common] + self.kinds:
            out |= {key for key, _, _, _ in scope.fields} | {g.list for g in scope.groups}
        return out


def _fill_scope(scope, lines):
    for node in lines:
        if node.d == "field":
            scope.fields.append((node.key, node.path, node.tr, node.via))
        elif node.d == "when":
            scope.whens.append((node.path, node.value))
        elif node.d == "const":
            scope.consts.append((node.path, node.value))
        elif node.d == "group":
            group = _fill_scope(GroupScope(), node.body)
            group.list, group.path = node.key, node.path
            scope.groups.append(group)
    return scope


def wire_pack(pack):
    """The adapter from a gtcheck Pack to what the codec reads."""
    return WirePack(pack)


def check_protobuf_pack(pack):
    """What the codec and the vectors of this generator need of a protobuf pack
    and the load rules of the specification do not state:

    - the wire is `protobuf`, there is no `default` line (the codec applies
      none) and a `const` value is an unsigned integer (it is written as a
      varint);
    - in one scope a path has one transform (0.5 ruling 16 allows two keys on
      a path; they share its wire type), is not both a `field` and a `group`,
      and is not both a value and a submessage that another path passes through.

    Raises GenError naming the pack file and the line."""
    def bad(node, message):
        raise GenError(message, pack.label, node.line)

    if pack.wire != "protobuf":
        raise GenError("the pack's wire is %s, not protobuf" % pack.wire, pack.label)
    for node in gtcheck.walk(pack.common + [n for k in pack.kinds for n in k.lines]):
        if node.d == "default":
            bad(node, "a `default` line: the codec of this generator applies none")
        if node.d == "const" and not node.value.isdigit():
            bad(node, "the `const` value %s is not an unsigned integer" % node.value)

    def check_scope(lines, where):
        seen = {}                               # path -> (transform or "group", node)
        for node in lines:
            if node.d == "field" and seen.setdefault(node.path, (node.tr, node))[0] != node.tr:
                bad(node, "path %s has two transforms in %s" % (node.loc, where))
        for node in lines:
            if node.d == "group":
                if node.path in seen:
                    bad(node, "path %s is a field and a group in %s" % (node.loc, where))
                seen[node.path] = ("group", node)
        for path, (_, node) in seen.items():
            for k in range(1, len(path)):
                if path[:k] in seen:
                    bad(node, "path %s is both a value and a submessage in %s" % (dotted(path[:k]), where))
        for node in lines:
            if node.d == "group":
                check_scope(node.body, "group %s" % node.key)

    for kind, lines in pack.scopes():
        check_scope(lines, "kind %s" % kind.name if kind else "the pack")
    return pack


def load_protobuf_pack(text, model, label):
    """Load a protobuf pack with gtcheck, apply check_protobuf_pack and return
    the WirePack the codec reads."""
    return wire_pack(check_protobuf_pack(gtcheck.load_pack(text, model, label)))


def load_model(out):
    """Every module under `model/` of the output directory, as this run sees it
    (a module the run wrote is read as written, also with --check): `core`
    first, then the others in byte order of file name, a module after the
    modules its `uses` lines name (engine-spec 0.8 "Model additions")."""
    pending = sorted((n for n in out.listdir("model") if n.endswith(".def")), key=lambda n: (n != "core.def", n))
    model = gtcheck.Model()
    while pending:
        waiting = []
        for name in pending:
            rel = "model/" + name
            try:
                model.add(out.read(rel), rel)
            except gtcheck.CheckError as e:
                if e.kind != "unknown-module":
                    raise
                waiting.append((name, e))
        if len(waiting) == len(pending):
            raise waiting[0][1]
        pending = [name for name, _ in waiting]
    if "core" not in model.modules:
        raise GenError("there is no module `core`: copy model/core.def into %s" % out.path("model"))
    return model


# --------------------------------------------------------------------------
# decode and encode with a protobuf pack (engine-spec 0.3, 0.5 to 0.7)
# --------------------------------------------------------------------------

def select_kind(pack, b):
    """The kind whose `when` lines all hold for the message (0.5 "Decode"):
    the first in pack order. None for a pack with no kinds."""
    def holds(whens):
        for path, value in whens:
            got = wire_get(b, path)
            if got is None:
                return False
            if value != "present" and not (got[0] == 0 and got[1] == int(value)):
                return False
        return True
    if not holds(pack.common.whens):
        raise NoKind()
    if not pack.kinds:
        return None
    for k in pack.kinds:
        if holds(k.whens):
            return k
    raise NoKind()


def via_value(pack, via, v, to_model):
    """A value through a value table (0.6): the first entry whose side equals
    the canonical text of the value; a value with no entry passes through."""
    if via is None:
        return v
    for native, model in pack.tables[via]:
        if (native if to_model else model) == model_text(v):
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
        for n in g.path[:-1]:                       # the container: last occurrence, as for a field
            got = dec_message(body).get(n)
            if got is None:
                body = None
                break
            if got[0] != 2:
                raise GenError("malformed-wire: field %s is not length-delimited" % n)
            body = got[1]
        if body is None:
            continue
        occ = [(wt, val) for num, wt, val in dec_fields(body) if num == g.path[-1]]
        scalar = [f for f in g.fields if f[1] == ()]
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
                    raise GenError("malformed-wire: an item of %s is not a submessage" % g.list)
                items.append(decode_scope(pack, val, g.fields, g.groups))
        if items:                                   # present when at least one item occurs
            ent[g.list] = items
    return ent


def engine_decode(pack, b):
    """decode(): (entity, kind name or None) of the message bytes `b`."""
    kind = select_kind(pack, b)
    fields, _, groups = pack.scope(kind)
    return decode_scope(pack, b, fields, groups), (kind.name if kind else None)


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
        items = ent.get(g.list)
        if not items:                               # absent, or empty: nothing is written
            continue
        node = tree
        for n in g.path[:-1]:
            node = node.setdefault(n, {})
        scalar = [f for f in g.fields if f[1] == ()]
        if scalar:
            key, _, tr, via = scalar[0]
            vals = [via_value(pack, via, it[key], False) for it in items if key in it]
            node[g.path[-1]] = Rep((tr, v) for v in vals) if tr == "pstring" else Packed(tr, vals)
        else:
            node[g.path[-1]] = Rep(encode_scope(pack, it, g.fields, g.consts, g.groups) for it in items)
    return tree


def engine_encode(pack, ent, kind_name):
    """encode(): (message bytes, kind name or None). `kind_name` None means the
    entity came from another format: the kind is the first whose `requires`
    keys are all present (0.5 "Encode")."""
    kind = pack.kind(kind_name)
    if kind is None and pack.kinds:
        # 0.7: `requires <list>` holds when the list is present and has an item
        kind = next((k for k in pack.kinds if all(r in ent and ent[r] != [] for r in k.requires)), None)
        if kind is None:
            raise NoKind()
    tree = encode_scope(pack, ent, *pack.scope(kind))
    for path, value in pack.common.whens + (kind.whens if kind else []):
        node = tree
        for n in path[:-1]:
            node = node.setdefault(n, {})
        if value == "present":
            node.setdefault(path[-1], {})        # 0.5 ruling 14: empty length-delimited field
        else:
            node[path[-1]] = ("pvarint", int(value))
    return enc_tree(tree), (kind.name if kind else None)


# --------------------------------------------------------------------------
# decode and encode with a text pack (xml, geojson), for cross-format vectors
# --------------------------------------------------------------------------

def text_lines(pack, what, directives=("field",)):
    """The top-level lines of a text pack the functions below read, in file
    order. They handle a pack with no kinds and no `typemap` line, and `field`
    lines with no option."""
    if pack.kinds or pack.typemap:
        raise GenError("%s: %s lines are not supported" % (what, "kind" if pack.kinds else "typemap"), pack.label)
    lines = [node for node in pack.common if node.d in directives]
    for node in lines:
        if node.d == "field" and (node.via or node.opts):
            raise GenError("%s: field options are not supported" % what, pack.label, node.line)
    return lines


def text_decode(pack, wire_text):
    """decode() for the two text wires of engine-spec 0.1 (xml, geojson), for
    packs without kinds: enough to derive the entity of a cross-format vector.
    The lists of a text pack are not decoded."""
    import datetime
    import xml.etree.ElementTree as ET
    wire = pack.wire
    fields = [(node.key, node.loc, node.tr) for node in text_lines(pack, "text_decode")]
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
            raise GenError("text_decode: wire %s" % wire, pack.label)
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
            raise GenError("text_decode: transform %s" % tr, pack.label)
    return ent


def plain_float(v):
    """0.1.1 ruling 3: shortest round-trip decimal, never an exponent, no
    decimal point on an integer value, negative zero as 0."""
    import decimal
    if v == int(v):
        return str(int(v))
    return format(decimal.Decimal(repr(v)), "f")


def xml_encode(pack, ent):
    """encode() for the xml wire (engine-spec 0.1 with the 0.1.1 rulings, and the
    `const` and `default` lines of 0.6), for a pack without kinds and value
    tables whose locators are attributes, and an entity without residue.
    Attributes are written in line order, a `const` at the place of its line;
    an element is created where the first line that writes into it stands; an
    empty element closes itself."""
    import datetime
    if pack.tables:
        raise GenError("xml_encode: map lines are not supported", pack.label)
    if pack.root is None:
        raise GenError("xml_encode: no root", pack.label)
    lines, defaults = [], {}
    for node in text_lines(pack, "xml_encode", ("field", "const", "default")):
        if node.d == "field":
            lines.append((node.key, node.loc, node.tr))
        elif node.d == "const":
            lines.append((None, node.loc, node.value))
        else:
            defaults[node.key] = node.value
    top = {"name": pack.root, "attrs": [], "kids": []}

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
        raise GenError("xml_encode: transform %s" % tr, pack.label)

    for key, loc, third in lines:
        text = third if key is None else text_of(key, third)
        if text is None:
            continue
        path, _, last = loc.rpartition("/")
        if not last.startswith("@"):
            raise GenError("xml_encode: locator %s is not an attribute" % loc, pack.label)
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


def geojson_encode(pack, ent):
    """encode() for the geojson wire of engine-spec 0.1 (with the 0.1.1
    rulings 3 to 5), for a pack without kinds and an entity without residue."""
    if pack.kinds or pack.typemap:
        raise GenError("text_encode: %s lines are not supported" % ("kind" if pack.kinds else "typemap"), pack.label)
    coord, props, top = {}, [], []
    for node in pack.common:
        if node.d != "field" or node.key not in ent:
            continue
        key, loc, tr = node.key, node.loc, node.tr
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
            raise GenError("text_encode: transform %s" % tr, pack.label)
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


class OtherPack:
    """Another pack a cross-format vector converts to or from: a protobuf pack
    through the codec above, an xml or geojson pack through the text functions.
    `format` and `wire` are those of the pack, `label` the file it was read from."""

    def __init__(self, text, model, label):
        self.pack = gtcheck.load_pack(text, model, label)
        self.format, self.wire, self.label = self.pack.format, self.pack.wire, label
        self.wire_pack = wire_pack(check_protobuf_pack(self.pack)) if self.wire == "protobuf" else None
        if self.wire not in ("protobuf", "xml", "geojson"):
            raise GenError("a pack of wire %s cannot be converted to or from here" % self.wire, label)

    @classmethod
    def read(cls, path, model):
        with open(path, encoding="utf-8") as fh:
            return cls(fh.read(), model, path)

    def _entity_lines(self):
        """The top-level `field` lines of the pack, of every kind."""
        return [n for n in self.pack.common + [n for k in self.pack.kinds for n in k.lines] if n.d == "field"]

    def mapped_keys(self):
        """The entity keys the pack has a `field` line for (and, for a protobuf
        pack, the lists it has a `group` for)."""
        if self.wire_pack:
            return self.wire_pack.names()
        return {node.key for node in self._entity_lines()}

    def keys_sharing_a_locator(self):
        """{key: the other keys the pack reads from a locator it reads `key`
        from}. A pack may map one locator to several keys (0.5 ruling 16):
        decode then fills every one of them from the one value on the wire."""
        by_locator = {}
        for node in self._entity_lines():
            by_locator.setdefault(node.loc, []).append(node.key)
        out = {}
        for keys in by_locator.values():
            for key in keys:
                out.setdefault(key, set()).update(k for k in keys if k != key)
        return out

    def decode(self, wire_text):
        """decode(): the entity of a message in this pack's format."""
        if self.wire_pack:
            return engine_decode(self.wire_pack, bytes.fromhex("".join(wire_text.split())))[0]
        return text_decode(self.pack, wire_text)

    def encode(self, ent):
        """encode() of an entity that came from a different format (no kind)."""
        if self.wire_pack:
            known = self.wire_pack.names()
            return engine_encode(self.wire_pack, {k: v for k, v in ent.items() if k in known}, None)[0].hex()
        scalars = {k: v for k, v in ent.items() if not isinstance(v, list)}
        return xml_encode(self.pack, scalars) if self.wire == "xml" else geojson_encode(self.pack, scalars)


def would_derive(model, keys):
    """The keys `convert` would add to an entity that has `keys` (engine-spec 0.6,
    derived keys), by presence only: this codec computes no derivation, so a
    vector it writes must not depend on one."""
    have, added = set(keys), set()
    for _ in range(8):
        progressed = False
        for name in sorted(model.modules):
            for derive in model.modules[name].derives:
                if derive.target not in have and all(k in have for k in derive.arguments):
                    have.add(derive.target); added.add(derive.target); progressed = True
        if not progressed:
            break
    return added


# Derive functions this codec computes, exactly as engine-spec 0.16 states them:
# integer arithmetic, floor toward negative infinity, no float step.
EXACT_DERIVES = {
    "sec_of": lambda ms: ms // 1000,
    "nsec_of": lambda ms: (ms - 1000 * (ms // 1000)) * 1000000,
}


def apply_derives(model, ent):
    """The entity `convert` would make of `ent` (engine-spec 0.6): the modules in
    byte order of name, each module's derive lines in order, a line setting its
    target when the target is absent and every argument present, repeated until
    a pass sets nothing (at most 8). Only the functions of EXACT_DERIVES are
    computed; the targets of lines with another function that would fire are
    returned, and the caller refuses a vector that depends on one, as
    would_derive does. -> (entity, set of targets not computed)."""
    out, skipped = dict(ent), set()
    for _ in range(8):
        progressed = False
        for name in sorted(model.modules):
            for derive in model.modules[name].derives:
                if derive.target in out or not all(k in out for k in derive.arguments):
                    continue
                fn = EXACT_DERIVES.get(derive.function)
                if fn is None or derive.parameter is not None:
                    skipped.add(derive.target)
                    continue
                out[derive.target] = fn(*[out[k] for k in derive.arguments])
                progressed = True
        if not progressed:
            break
    return out, skipped


def within(part, whole):
    """True when `part` is `whole` as far as it goes: equal scalars; for a list,
    as many items, each item's keys and lists within the other's (a list
    converted between two formats keeps, per item, the keys both groups map)."""
    if isinstance(part, list):
        return (isinstance(whole, list) and len(part) == len(whole) and all(
            all(k in w and within(v, w[k]) for k, v in p.items()) for p, w in zip(part, whole)))
    return part == whole


def model_text(v):
    """The canonical text of a model value, as a vector's `model` object and a
    value table state it: a float with an integer value has no decimal point."""
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


def dump_vector(vec):
    """The text of a vector file."""
    return json.dumps(vec, indent=2) + "\n"


def check_vectors(out, vec_dir, fmt, pack, old_pack):
    """Decode every vector under `vec_dir` (existing and generated) with `pack`
    and compare it with what the vector states: the kind, the `model` values
    and, for a vector into the same format, the bytes. A vector that was not
    generated must decode with `old_pack` (--supersedes) to keys this pack
    decodes to the same values. Returns the number of vectors."""
    n = 0
    for name in out.listdir(vec_dir):
        if not name.endswith(".json"):
            continue
        path = vec_dir + "/" + name

        def fail(message):
            raise GenError(message, path)

        v = json.loads(out.read(path))
        if v["from"] != fmt:
            fail("vector is not from %s" % fmt)
        b = bytes.fromhex("".join(v["input"].split()))
        ent, kind = engine_decode(pack, b)
        for k, want in v.get("model", {}).items():
            if k == "@kind":
                if kind != want:
                    fail("selected kind %s, vector says %s" % (kind, want))
                continue
            if k == "@complete" or v["model"].get("@complete"):
                continue        # checked on the derived entity (0.6); this codec does not derive
            got = model_lookup(ent, k)
            if got is None:
                fail("model key %s not decoded" % k)
            ok = abs(got - float(want)) <= 1e-9 if isinstance(got, float) else str(got) == want
            if not ok:
                fail("model key %s is %r, vector says %s" % (k, got, want))
        if v["to"] == fmt:
            if engine_encode(pack, ent, kind)[0].hex() != v["expect"]:
                fail("same-format round trip differs")
        if old_pack is not None and not name.startswith("gen-"):
            old_ent, _ = engine_decode(old_pack, b)
            if any(ent.get(k) != value for k, value in old_ent.items()):
                fail("the superseded pack decodes %r, this pack decodes %r" % (old_ent, ent))
        n += 1
    return n


# --------------------------------------------------------------------------
# plan, third part: options, kinds, limits
# --------------------------------------------------------------------------

PATH_RE = re.compile(r"[1-9][0-9]*(\.[1-9][0-9]*)*")


class KindPlan:
    """One kind of the pack. `number` is the field of the envelope whose
    presence selects it (`when <number> present`), None for the one kind of an
    envelope with no members. `leaves` and `groups` are its own lines, `skipped`
    what the walk did not map, `requires` its `requires` keys and
    `vector_number` the number in the name of its generated vector."""

    def __init__(self, name, number, leaves, groups, skipped):
        self.name, self.number = name, number
        self.leaves, self.groups, self.skipped = leaves, groups, skipped
        self.requires = []
        self.vector_number = None


class BaseModule:
    """The module a run extends (--module-base): its text and what it declares.
    Empty when the module is written afresh."""

    def __init__(self, text="", module=None):
        self.text = text
        self.keys = dict(module.keys) if module else {}        # name -> type
        self.lists = set(module.lists) if module else set()
        self.sources = list(module.sources) if module else []

    @classmethod
    def read(cls, path, module_name):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        module = gtcheck.parse_module(text, path)
        if module.name != module_name:
            raise GenError("--module-base is module %s, not %s" % (module.name, module_name), path)
        if module.distribution != "public":
            raise GenError("--module-base is not a public module", path)
        return cls(text, module)

    def names(self):
        return set(self.keys) | self.lists


class Plan:
    """Everything a run will emit, with every decision made: the kinds in pack
    order, the leaves and groups with their keys, the limits the budgets left,
    the hand bindings and the content of the module. The emit functions read a
    Plan and decide nothing."""

    def __init__(self, opts, schema, env, budgets):
        self.opts, self.schema, self.env, self.budgets = opts, schema, env, budgets
        self.common, self.common_groups, self.skipped_common = [], [], []
        self.kinds, self.empty_kinds = [], []       # KindPlan objects; (name, number) of kinds with no line
        self.walked_kinds = []      # the kinds in schema order, as the walk met them
        self.beside = {}            # kind name -> field number, for each --common-member
        self.n_names = 0            # keys and lists the module holds after this run
        self.nest = self.item_depth = self.nest_asked = self.depth_asked = None
        self.core_map = {}          # field-number path -> shared keys, in --map order
        self.binds, self.consts, self.tables = {}, {}, {}
        self.names = {}             # the content of the names file
        self.inherited = 0          # names taken from --names-from files
        self.base = BaseModule()
        self.mod_keys, self.mod_lists = {}, {}      # name -> (type, meaning); name -> meaning
        self.new_keys, self.new_lists = {}, {}      # the same, without what --module-base declares

    @property
    def all_leaves(self):
        """The leaves outside every group, common first, then by kind."""
        return self.common + [l for k in self.kinds for l in k.leaves]

    @property
    def top_groups(self):
        return self.common_groups + [g for k in self.kinds for g in k.groups]

    @property
    def all_groups(self):
        return flat_groups(self.top_groups)

    @property
    def item_leaves(self):
        return [l for g in self.all_groups for l in g.item_leaves()]

    @property
    def skipped_lists(self):
        """What the walk did not map, by kind in schema order, then common."""
        return [k.skipped for k in self.walked_kinds] + [self.skipped_common]

    @property
    def core_lines(self):
        return [l for l in self.all_leaves if l.core]

    @property
    def bound_keys(self):
        return [b[0] for bs in self.binds.values() for b in bs]

    @property
    def single(self):
        """True for a pack of one kind with no `when`: the format has one layout."""
        return len(self.kinds) == 1 and self.kinds[0].number is None

    def kind(self, name):
        return next((k for k in self.kinds if k.name == name), None)


def find_envelope(schema, name):
    found = [m for m in schema.messages.values() if m.name == name or m.full == name]
    if len(found) != 1:
        raise GenError("envelope %s matches %d messages" % (name, len(found)))
    return found[0]


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise GenError("%s is not JSON: %s" % (what, e.msg), path, e.lineno)


def read_names(opts):
    """-> (pinned, own, inherited). `own` is the content of --names-file as it
    is before the run; `pinned` adds the names of every --names-from file
    (a path under its prefix; a name pinned by message type, inside a group,
    as it is); `inherited` counts those."""
    own = {}
    if opts.names_file and os.path.exists(opts.names_file):
        own = read_json(opts.names_file, "--names-file")
    pinned, inherited = dict(own), 0
    for spec in opts.names_from:
        nfile, _, prefix = spec.rpartition("=")
        if not nfile or not PATH_RE.fullmatch(prefix):
            raise GenError("--names-from %s: want FILE=PREFIX with PREFIX a field-number path" % spec)
        for p, name in read_json(nfile, "--names-from").items():
            ident = prefix + "." + p if p[:1].isdigit() else p
            if pinned.setdefault(ident, name) != name:
                raise GenError("--names-from %s: %s is already pinned to another name" % (spec, ident))
            inherited += 1
    return pinned, own, inherited


def bound_paths(binds):
    """The paths a --bind line reads through: every proper prefix of its path.
    A repeated field there stays one occurrence, read by that line."""
    bound = set()
    for spec in binds:
        m = re.fullmatch(r"[^:]+:([0-9.]+)=.*", spec)
        if m:
            nums = tuple(map(int, m.group(1).split(".")))
            bound |= {nums[:k] for k in range(1, len(nums))}
    return bound


def envelope_members(env, opts):
    """-> (members, beside). The members of the envelope are the fields that
    select a kind: every member of its oneofs, or with --kinds-from-fields every
    singular message field. `beside` are the --common-member fields among them."""
    members = [f for f in env.fields if f.oneof]
    if opts.one_layout:
        # the envelope is one kind; the members of its oneofs are plain lines of it, as the
        # members of a nested oneof are
        members = []
    if opts.kinds_from_fields:
        members = [f for f in env.fields if f.kind == "message" and f.label != "repeated"]
    beside = [f for f in members if f.name in opts.common_member]
    if len(beside) != len(set(opts.common_member)):
        raise GenError("--common-member: not a singular message field of %s: %s" % (
            env.name, " ".join(sorted(set(opts.common_member) - {f.name for f in beside}))))
    return members, beside


def walk_envelope(plan, members, beside, walk):
    """Fill the common lines and the kinds of `plan` from one walk. With no
    member the envelope itself is the one kind."""
    env = plan.env
    plan.common, plan.skipped_common, plan.common_groups = [], [], []
    plan.kinds, plan.empty_kinds = [], []
    if not members:
        name = snake(env.name)
        leaves, skipped, groups = [], [], []
        walk.message(env, (), (), (env.full,), True, (), leaves, skipped, groups)
        for x in leaves + groups:
            x.kind = name
        plan.kinds.append(KindPlan(name, None, leaves, groups, skipped))
        return
    shell = Message(env.full, env.name, env.syntax, env.file)
    shell.fields = [f for f in env.fields if f not in members or f in beside]
    walk.message(shell, (), (), (env.full,), True, (), plan.common, plan.skipped_common, plan.common_groups)
    for f in members:
        name = snake(f.name)
        leaves, skipped, groups = [], [], []
        if f in beside:
            # its fields are common lines; the kind has none of its own
            if not any(l.nums[0] == f.number for l in plan.common):
                raise GenError("--common-member %s has no mappable field outside a repeated one" % f.name)
            plan.kinds.append(KindPlan(name, f.number, [], [], []))
            continue
        if f.kind != "message" or f.label == "repeated":
            raise GenError("oneof member %s is not a singular message" % f.name, env.file, f.line)
        walk.message(f.ref, (f.number,), (), (env.full, f.ref.full), True, (), leaves, skipped, groups)
        for x in leaves + groups:
            x.kind = name
        plan.kinds.append(KindPlan(name, f.number, leaves, groups, skipped))
        if not leaves and not groups:
            plan.empty_kinds.append((name, f.number))


def name_plan(plan, pinned):
    """Give every leaf its key and every group its list, and set `plan.n_names`."""
    module = plan.opts.module
    # a first-level list is named as a leaf at its place would be: a stand-in leaf
    stand = {}
    for name, groups in [(None, plan.common_groups)] + [(k.name, k.groups) for k in plan.kinds]:
        for g in groups:
            lf = Leaf()
            lf.nums, lf.names, lf.owner, lf.field, lf.kind, lf.is_list = g.nums, g.names, g.owner, g.field, name, True
            stand[id(g)] = lf
    named = [(k.name, k.leaves + [stand[id(g)] for g in k.groups]) for k in plan.kinds]
    assign_keys(module, named, plan.common + [stand[id(g)] for g in plan.common_groups], plan.core_map, pinned)
    for g in plan.top_groups:
        g.list, g.path = stand[id(g)].key, stand[id(g)].path
    top_names = {l.key.split(".", 1)[1] for l in plan.all_leaves}
    top_names |= {g.list.split(".", 1)[1] for g in plan.top_groups}
    same = {}
    for l in plan.all_leaves:
        same.setdefault(l.key.split(".", 1)[1], set()).add((l.owner.full, l.field.number))
    inner = assign_item_keys(module, plan.top_groups, pinned, top_names | plan.base.names(), same)
    plan.n_names = len(top_names | set(inner.values()) | plan.base.names())


def plan_within_budgets(plan, pinned):
    """Walk and name the envelope under the limits asked for, lowering them
    until the pack fits: the path length inside an item while pack.def would
    hold more than `budgets.lines` `field` lines, then the number of groups
    inside one another; the nesting again while the module would hold more
    than `budgets.keys` names. A lower limit removes lines; it never reorders
    the lines that stay."""
    opts, budgets = plan.opts, plan.budgets
    members, beside = envelope_members(plan.env, opts)
    plan.beside = {snake(f.name): f.number for f in plan.env.fields if f.name in opts.common_member}
    bound = bound_paths(opts.bind)
    plan.nest_asked = opts.max_depth if opts.max_group_nesting is None else opts.max_group_nesting
    plan.depth_asked = opts.max_depth if opts.max_item_depth is None else opts.max_item_depth
    nest, item_depth = plan.nest_asked, plan.depth_asked
    while True:
        try:
            walk = Walk(opts.max_depth, bound, nest, item_depth, budgets.lines)
            walk_envelope(plan, members, beside, walk)
            leaves = plan.all_leaves
            lines = (len(leaves) + sum(len(plan.core_map.get(dotted(l.nums), ())) for l in leaves)
                     + len(opts.bind) + walk.lines_in_groups)
            if lines > budgets.lines:
                raise TooBig()
            name_plan(plan, pinned)
        except TooBig:
            if item_depth > 1:
                item_depth -= 1
            elif nest > 0:
                nest -= 1
            else:
                raise GenError("pack.def would hold more than %d field lines with no group at all" % budgets.lines)
            continue
        if plan.n_names <= budgets.keys:
            break
        if nest == 0:
            raise GenError("module %s would hold %d keys, over %d, with no group at all" % (
                opts.module, plan.n_names, budgets.keys))
        nest -= 1
    plan.nest, plan.item_depth = nest, item_depth


def order_kinds(plan):
    """Put the kinds in pack order and number their vectors.

    Without --default-kind the order is that of the schema. With it: the kinds
    with fields or groups, then the default kind, then the kinds with neither.
    A kind with no field requires only common keys; placed after the default
    kind, an entity from another format that carries those common keys (a node
    id the caller supplied, 0.6) still encodes as the default kind. A generated
    vector keeps the number its kind has when the default kind is simply last,
    so the place of the kinds with no field names no vector file."""
    default = plan.opts.default_kind
    plan.walked_kinds = list(plan.kinds)
    if default:
        if plan.kind(default) is None:
            raise GenError("--default-kind %s is not a kind" % default)
        numbered = sorted(plan.kinds, key=lambda k: k.name == default)
        plan.kinds.sort(key=lambda k: 2 if not (k.leaves or k.groups) else int(k.name == default))
    else:
        numbered = plan.kinds
    for i, kind in enumerate(numbered, 1):
        kind.vector_number = i


def parse_hand_lines(plan):
    """Read --bind, --const and --table into `plan.binds` ({kind: [(key, path,
    transform, table)]}), `plan.consts` ({kind: [(path, value)]}) and
    `plan.tables` ({table: [(native, model)]}), each in option order."""
    opts = plan.opts
    kind_names = [k.name for k in plan.kinds]
    walked = {l.path for l in plan.all_leaves}
    for spec in opts.bind:
        m = re.fullmatch(r"([^:]+):([0-9.]+)=([^:]+):([a-z]+)(?::([^:]+))?", spec)
        if not m or m.group(1) not in kind_names or m.group(4) not in YIELDS:
            raise GenError("--bind %s: want KIND:PATH=KEY:TRANSFORM[:TABLE] with a kind of the schema" % spec)
        if m.group(2) in walked:
            raise GenError("--bind %s: the walk maps that path; use --map" % spec)
        plan.binds.setdefault(m.group(1), []).append((m.group(3), m.group(2), m.group(4), m.group(5)))
    for spec in opts.const:
        m = re.fullmatch(r"([^:]+):([0-9.]+)=([0-9]+)", spec)
        if not m or m.group(1) not in kind_names:
            raise GenError("--const %s: want KIND:PATH=VALUE with a kind of the schema" % spec)
        plan.consts.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
    for spec in opts.table:
        m = re.fullmatch(r"([^:=]+):([^=]+)=(.+)", spec)
        if not m:
            raise GenError("--table %s: want TABLE:NATIVE=MODEL" % spec)
        plan.tables.setdefault(m.group(1), []).append((m.group(2), m.group(3)))
    for kind_binds in plan.binds.values():
        for _, _, _, table in kind_binds:
            if table is not None and table not in plan.tables:
                raise GenError("--bind names table %s, which has no --table line" % table)


def plan_module(plan):
    """Decide the `key` and `list` lines of the module: one per name, in the
    order the pack reaches them, with the meaning taken from the schema."""
    base = plan.base
    for l in plan.all_leaves + plan.item_leaves:
        name = l.key.split(".", 1)[1]
        ty = YIELDS[l.transform]
        if name in plan.mod_keys and plan.mod_keys[name][0] != ty:
            raise GenError("key %s reached with two types" % name)
        plan.mod_keys.setdefault(name, (ty, key_meaning(l) + ("; one item of the repeated field" if not l.nums else "")))
    for g in plan.all_groups:
        f = g.field
        what = "%s.%s (repeated %s)" % (g.owner.name, f.name, f.type)
        holds = ("each item holds %s" % g.scalar.key if g.scalar else
                 "each item is one %s message" % f.ref.name)
        plan.mod_lists.setdefault(g.list.split(".", 1)[1],
                                  "%s%s; %s" % (what, ": " + f.comment if f.comment else "", holds))
    both = set(plan.mod_keys) & set(plan.mod_lists)
    if both:
        raise GenError("%s is a key and a list" % sorted(both)[0])
    for k, (ty, _) in plan.mod_keys.items():
        if k in base.keys and base.keys[k] != ty:
            raise GenError("key %s is %s in --module-base and %s here" % (k, base.keys[k], ty))
        if k in base.lists:
            raise GenError("%s is a list in --module-base and a key here" % k)
    for k in plan.mod_lists:
        if k in base.keys:
            raise GenError("%s is a key in --module-base and a list here" % k)
    plan.new_keys = {k: v for k, v in plan.mod_keys.items() if k not in base.keys}
    plan.new_lists = {k: v for k, v in plan.mod_lists.items() if k not in base.lists}
    held = len(base.keys) + len(base.lists) + len(plan.new_keys) + len(plan.new_lists)
    if held != plan.n_names:
        raise GenError("the module holds %d names, the plan counted %d" % (held, plan.n_names))


def plan_requires(plan):
    """Choose the `requires` keys of every kind, so that on encode an entity
    from another format is given the default kind and no other (0.5 "Encode":
    the first kind in pack order whose `requires` keys are all present)."""
    opts, common = plan.opts, plan.common
    key_kinds, list_kinds = {}, {}
    for kind in plan.kinds:
        for l in kind.leaves:
            key_kinds.setdefault(l.key, set()).add(kind.name)
        for g in kind.groups:
            list_kinds.setdefault(g.list, set()).add(kind.name)
    common_keys = {l.key for l in common}
    for kind in plan.kinds:
        name, ls = kind.name, kind.leaves
        if plan.single:
            kind.requires = []           # one layout, no `when`: any entity encodes as it
        elif name == opts.default_kind:
            kind.requires = opts.default_requires or [l.core for l in ls if l.core]
            if not kind.requires:
                raise GenError("default kind %s maps no shared key to require" % name)
        elif name in plan.beside:
            # its fields are common lines: the first of them, a raw key no other format carries
            kind.requires = [l.key for l in common if l.nums[0] == plan.beside[name]][:1]
        elif not ls and kind.groups:
            # no field of its own, and a repeated one: a list no other kind maps
            # (0.7: `requires <list>` holds when the list has at least one item)
            own = [g.list for g in kind.groups if list_kinds[g.list] == {name}]
            if not own:
                raise GenError("kind %s has only lists other kinds map too; nothing to require" % name)
            kind.requires = own[:1]
        elif not ls:
            # nothing of its own to require: the mandatory common fields, so an
            # entity from another format never encodes as this kind
            kind.requires = [l.key for l in common if l.mandatory][:6]
            if not kind.requires:
                raise GenError("kind %s has no field and the envelope has no mandatory common field to require" % name)
        else:
            dist = [l for l in ls if l.key.startswith(opts.module + ".") and key_kinds[l.key] == {name}
                    and l.key not in common_keys]
            dist.sort(key=lambda l: len(l.nums))            # stable: shallow first, then schema order
            man = [l for l in dist if l.mandatory]
            kind.requires = [l.key for l in (man[:6] if man else dist[:1])]


def make_plan(schema, opts, budgets=DEFAULT_BUDGETS):
    """The plan of a run: walk the envelope of `schema` under the options and
    the budgets, name every key and decide every line. Reads the names files
    and --module-base; writes nothing."""
    if opts.one_layout and opts.kinds_from_fields:
        raise GenError("--one-layout and --kinds-from-fields exclude each other")
    if opts.common_member and not opts.kinds_from_fields:
        raise GenError("--common-member needs --kinds-from-fields")
    plan = Plan(opts, schema, find_envelope(schema, opts.envelope), budgets)
    for spec in opts.map:
        path, _, key = spec.partition("=")
        plan.core_map.setdefault(path, []).append(key)     # several keys on one path: lines in this order
    pinned, own_names, plan.inherited = read_names(opts)
    if opts.module_base:
        plan.base = BaseModule.read(opts.module_base, opts.module)
    plan_within_budgets(plan, pinned)
    order_kinds(plan)
    plan.names = dict(own_names)
    plan.names.update({l.path: l.key.split(".", 1)[1] for l in plan.all_leaves + plan.item_leaves})
    plan.names.update({g.path: g.list.split(".", 1)[1] for g in plan.all_groups})
    unused = set(plan.core_map) - {dotted(l.nums) for l in plan.all_leaves}
    if unused:
        raise GenError("--map paths that are not mapped leaves of the schema: %s" % sorted(unused))
    parse_hand_lines(plan)
    plan_module(plan)
    plan_requires(plan)
    return plan


# --------------------------------------------------------------------------
# emit: the text of each file, from a Plan
# --------------------------------------------------------------------------

def quote(s):
    """A text as one quoted value of a .def line: there is no escape (0.1.1
    ruling 1), so `"` becomes `'`, `#` is dropped and white space is one space."""
    s = re.sub(r"\s+", " ", s.replace('"', "'").replace("#", "")).strip()
    return '"%s"' % s


def key_meaning(lf):
    """The meaning text of a key: the schema field, its type (for an enum the
    first twelve values) and its comment."""
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


def emit_names(plan):
    """The text of the names file: every pinned path and its name, sorted."""
    return json.dumps(plan.names, indent=1, sort_keys=True) + "\n"


def emit_module(plan):
    """The text of model/<module>.def. With --module-base the `key` and `list`
    lines of that file are kept as they are and the new ones follow."""
    opts, base = plan.opts, plan.base
    new_keys, new_lists = plan.new_keys, plan.new_lists
    check_derive(opts, set(plan.mod_keys) | set(base.keys))
    w = max(len(k) for k in (new_keys or plan.mod_keys))
    lines = ["# The %s module: raw keys of the %s format, one per schema field the" % (opts.module, opts.format),
             "# pack maps and no core or track key covers. Generated by",
             "# tools/gen/proto2pack.py from the sources below; edit the generator, not this file.",
             "module        %s" % opts.module, "version       %s" % opts.module_version, "distribution  public"]
    srcs = [quote(s) for s in base.sources]
    srcs += [quote(s) for s in opts.source if quote(s) not in srcs]
    if opts.module_base:
        lines[0:2] = ["# The %s module: raw keys shared by the packs that name it in a `uses` line," % opts.module,
                      "# one per schema field a pack maps. Extended, never rewritten: a key keeps",
                      "# its line once it has one. Last extended for the %s format by" % opts.format]
    lines += ["source        %s" % s for s in srcs]
    lines += ["uses          %s" % m for m in derive_uses(opts)]
    lines += [ln for ln in base.text.split("\n") if ln.split()[:1] in (["key"], ["list"])]
    lines += ["key  %-*s  %-6s  -  %s" % (w, k, ty, quote(mean)) for k, (ty, mean) in new_keys.items()]
    if new_lists:
        lw = max(len(k) for k in new_lists)
        if not base.lists:
            lines += ["# Lists (engine-spec 0.7): one per repeated field the pack maps as a `group`. The keys",
                      "# an item holds are keys of this module, named from the item's message type."]
        lines += ["list %-*s  %s" % (lw, k, quote(mean)) for k, mean in new_lists.items()]
    if opts.derive:
        lines += ["# Derived keys (engine-spec 0.6): set on convert when the target is absent",
                  "# and every argument is present."]
        lines += ["derive  %s" % "  ".join(d.split()) for d in opts.derive]
    return "\n".join(lines) + "\n"


def derive_uses(opts):
    """The modules other than core and this one that the --derive arguments name."""
    mods = []
    for d in opts.derive:
        for k in d.split()[2:]:
            m = k.split(".")[0] if "." in k else None
            if m and m != opts.module and m not in mods:
                mods.append(m)
    return sorted(mods)


def check_derive(opts, mod_keys):
    """Each --derive is `<target> <function> <arg>...` and its target is a key of
    this module (engine-spec 0.6: a derive line sets a key of core or of its module)."""
    for d in opts.derive:
        a = d.split()
        if len(a) < 3:
            raise GenError("--derive %r: give a target, a function and at least one argument" % d)
        tgt = a[0]
        if not tgt.startswith(opts.module + ".") or tgt.split(".", 1)[1] not in mod_keys:
            raise GenError("--derive %r: the target is not a key of module %s" % (d, opts.module))


def group_lines(g, ind=""):
    """A `group` block (engine-spec 0.7): paths inside it are relative to one item."""
    out = ["%sgroup  %s  %s" % (ind, g.list, dotted(g.nums))]
    if g.scalar:    # numeric transforms: both encodings read, the packed one written
        out.append("%s  field  %s  .  %s" % (ind, g.scalar.key, g.scalar.transform))
    out += ["%s  field  %s  %s  %s" % (ind, l.key, dotted(l.nums), l.transform) for l in g.leaves]
    for sg in g.groups:
        out += group_lines(sg, ind + "  ")
    return out + [ind + "end"]


def emit_pack(plan):
    """The text of packs/<format>/pack.def: the header, the common lines, then
    each kind with its `when`, `requires`, `field`, hand-bound `field`, `const`
    and `group` lines, then the value tables."""
    opts, env = plan.opts, plan.env
    all_leaves = plan.all_leaves
    used_mods = sorted({k.split(".")[0] for k in [k for l in all_leaves for k in [l.key] + l.cores] + plan.bound_keys
                        + [g.list for g in plan.all_groups]      # an envelope may hold only repeated fields
                        if k and "." in k})
    kw = max((len(l.key) for l in all_leaves), default=0)      # an envelope may hold only repeated fields
    pw = max((len(dotted(l.nums)) for l in all_leaves), default=0)

    def field_line(l):
        # shared keys and the raw key on one path (0.5 ruling 16): shared lines first,
        # in --map order, because on encode the earliest line whose key is present is written
        return "\n".join("field  %-*s  %-*s  %s" % (kw, k, pw, l.path, l.transform)
                         for k in l.cores + [l.key] if k)

    out = ["# %s: envelope message %s, protobuf. Generated by tools/gen/proto2pack.py" % (opts.format, env.full),
           "# from the sources below; edit the generator, not this file. Paths are",
           "# dot-separated field numbers. Counts and what is not mapped: pack.md.",
           "format        %s" % opts.format, "version       %s" % opts.pack_version, "distribution  public"]
    out += ["source        %s" % quote(s) for s in opts.source]
    out += ["uses          %s" % m for m in used_mods]
    out += ["wire          protobuf"]
    if plan.common or plan.common_groups:
        what = ("# common: fields of %s outside its oneof" % env.name if not plan.beside else
                "# common: the fields of %s, a member that may stand beside any other" % " and ".join(
                    "%s.%s" % (env.name, f.name) for f in env.fields if f.name in opts.common_member))
        out += ["", what] + [field_line(l) for l in plan.common]
        out += [ln for g in plan.common_groups for ln in group_lines(g)]
    for kind in plan.kinds:
        out += ["", "kind      %s" % kind.name]
        if kind.number is not None:
            out += ["when      %d present" % kind.number]
        if kind.requires:
            out += ["requires  %s" % " ".join(kind.requires)]
        out += [field_line(l) for l in kind.leaves]
        out += ["field  %-*s  %-*s  %s%s" % (kw, key, pw, p, tr, "  via %s" % table if table else "")
                for key, p, tr, table in plan.binds.get(kind.name, [])]
        out += ["const  %-*s  %s" % (pw, p, v) for p, v in plan.consts.get(kind.name, [])]
        out += [ln for g in kind.groups for ln in group_lines(g)]
    if plan.tables:
        out += ["", "# value tables: <table> <value on the wire> <value of the model key>"]
        tw = max(len(t) for t in plan.tables)
        nw = max(len(n) for es in plan.tables.values() for n, _ in es)
        out += ["map  %-*s  %-*s  %s" % (tw, t, nw, n, m) for t, es in plan.tables.items() for n, m in es]
    return "\n".join(out) + "\n"


def sample_value(lf, i):
    """The value of a leaf in a generated vector; `i` is the place of the leaf
    in the message, so two fields of one type differ."""
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


class MessageBuilder:
    """Builds the generated message of one vector. `next_index` numbers the
    sample values; `groups` collects the id of every group the message holds.
    `fixed` maps a path to the value a `const` line writes there."""

    def __init__(self, n_items, variant, fixed=None):
        self.n_items, self.variant, self.fixed = n_items, variant, fixed or {}
        self.next_index = 0
        self.groups = set()

    def build(self, leaves, groups, top=True):
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
            pick[gid] = order[self.variant % len(order)]

        def unset(x):
            return any(pick[(o[0], o[1], o[3])] != o[2] for o in x.oneofs)

        fixed = self.fixed if top else {}
        tree, ent = {}, {}
        for l in leaves:
            i = self.next_index
            self.next_index += 1
            if unset(l):
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
            for c in l.cores:
                ent[c] = v
        for g in groups:
            if unset(g):
                continue
            self.groups.add(id(g))
            node = tree
            for n in g.nums[:-1]:
                node = node.setdefault(n, {})
            count = self.n_items if g.level == 1 else 1
            if g.scalar:
                vals = []
                for _ in range(count):
                    vals.append(sample_value(g.scalar, self.next_index))
                    self.next_index += 1
                tr = g.scalar.transform
                node[g.nums[-1]] = Rep((tr, v) for v in vals) if tr == "pstring" else Packed(tr, vals)
                ent[g.list] = [{g.scalar.key: v} for v in vals]
            else:
                made = [self.build(g.leaves, g.groups, top=False) for _ in range(count)]
                node[g.nums[-1]] = Rep(t for t, _ in made)
                ent[g.list] = [e for _, e in made]
        return tree, ent


class Vectors:
    """The generated same-format vectors of a pack: `texts` maps a file name to
    its text, in pack order; `samples` maps a kind to the hex of its first
    message. `n_items` is the number of items per first-level group,
    `n_variants` the number of `-oneof<j>` vectors, `groups_out` the number of
    groups no vector holds and `gen_bytes` the size of all texts."""

    def __init__(self, n_items):
        self.n_items = n_items
        self.texts, self.samples = {}, {}
        self.n_variants = self.groups_out = self.gen_bytes = 0


def kind_vectors(plan, kind, n_items, vectors):
    """Add the vectors of one kind: its round trip, and a further vector per
    oneof variant while that brings in a group no earlier vector of the kind holds."""
    opts = plan.opts
    scope_groups = plan.common_groups + kind.groups
    n_groups = len(flat_groups(scope_groups))
    covered = set()     # groups some vector of the kind holds
    for variant in range(9):
        if variant and len(covered) == n_groups:
            break
        builder = MessageBuilder(n_items, variant)
        if kind.name in plan.beside:
            tree, ent = builder.build([l for l in plan.common if l.nums[0] == kind.number], [])
        elif not kind.leaves and not kind.groups:
            tree, ent = {kind.number: {}}, {}       # the member alone, as an empty submessage (0.5 ruling 14)
        else:
            builder.fixed = dict(plan.consts.get(kind.name, []))
            tree, ent = builder.build(plan.common + kind.leaves, scope_groups)
        if variant and not builder.groups - covered:
            continue
        covered |= builder.groups
        model = {"@kind": kind.name}
        model.update(flat_model(ent, values=2))
        hexs = enc_tree(tree).hex()
        tag = "-oneof%d" % variant if variant else ""
        if not variant:
            vectors.samples[kind.name] = hexs
        vectors.n_variants += bool(variant)
        vec = {"name": "gen-%s-roundtrip%s" % (kind.name, tag), "from": opts.format, "to": opts.format,
               "input": hexs, "expect": hexs, "model": model}
        vectors.texts["gen-%02d-%s-roundtrip%s.json" % (kind.vector_number, kind.name, tag)] = dump_vector(vec)
    vectors.groups_out += n_groups - len(covered)


def emit_vectors(plan, vector_budget=VECTOR_BUDGET):
    """The generated round-trip vectors, with two items per first-level group,
    or with one when two would take more than `vector_budget` bytes. The
    budget changes the number of items only, never a file name or the order."""
    for n_items in (2, 1):
        vectors = Vectors(n_items)
        for kind in plan.kinds:
            kind_vectors(plan, kind, n_items, vectors)
        vectors.gen_bytes = sum(len(t.encode("utf-8")) for t in vectors.texts.values())
        if vectors.gen_bytes <= vector_budget:
            break
    return vectors


# --------------------------------------------------------------------------
# self-check: load what the run wrote and prove every vector
# --------------------------------------------------------------------------

def check_kind_order(pack, default_kind):
    """Two rules of this generator about the order of kinds, on the loaded
    pack: only the last kind may have no `requires` (encode takes the first
    kind whose `requires` hold, so such a kind hides every kind after it), and
    no kind with lines follows the default kind."""
    for kind in pack.kinds[:-1]:
        if not kind.requires:
            raise GenError("kind %s has no requires and would shadow the kinds after it on encode" % kind.name)
    if default_kind:
        names = [k.name for k in pack.kinds]
        if any(k.fields or k.groups for k in pack.kinds[names.index(default_kind) + 1:]):
            raise GenError("a kind with fields follows the default kind")


def check_supersedes(pack, old_pack):
    """Every common `field` line of the pack this one replaces is a line of this pack."""
    if old_pack.format != pack.format:
        raise GenError("--supersedes names format %s" % old_pack.format)
    kept = {(key, path, tr) for scope in [pack.common] + pack.kinds for key, path, tr, _ in scope.fields}
    for key, path, tr, _ in old_pack.common.fields:
        if (key, path, tr) not in kept:
            raise GenError("superseded mapping %s %s %s is not preserved" % (key, dotted(path), tr))


class Checked:
    """What the self-check loaded: the model, the pack as the codec reads it,
    the pack it replaces (--supersedes) or None, and, once the vectors are
    proved, their number."""

    def __init__(self, model, pack, old_pack):
        self.model, self.pack, self.old_pack = model, pack, old_pack
        self.n_vectors = 0


def self_check(out, plan):
    """The first half of the self-check: load the modules and the pack the run
    wrote with gtcheck, as an engine loads them, and apply the checks of this
    generator. The second half is `check_vectors`."""
    opts = plan.opts
    pack_rel = "packs/%s/pack.def" % opts.format
    model = load_model(out)
    pack = load_protobuf_pack(out.read(pack_rel), model, pack_rel)
    if pack.format != opts.format or len(pack.kinds) != len(plan.kinds):
        raise GenError("the pack that loads is not the pack that was planned", pack_rel)
    check_kind_order(pack, opts.default_kind)
    old_pack = None
    if opts.supersedes:
        with open(opts.supersedes, encoding="utf-8") as fh:
            old_pack = load_protobuf_pack(fh.read(), model, opts.supersedes)
        check_supersedes(pack, old_pack)
    return Checked(model, pack, old_pack)


# --------------------------------------------------------------------------
# vectors to and from other formats
# --------------------------------------------------------------------------

# One row of the tables of pack.md. CrossIn: an entity of format `source`
# encodes as `kind` (None: the error `no-kind`). CrossOut: the generated message
# of `kind` converted into format `target`.
CrossIn = collections.namedtuple("CrossIn", "source kind carried dropped vector")
CrossOut = collections.namedtuple("CrossOut", "target kind carried vector")


def cross_vector_path(source, target):
    return "packs/%s/vectors/gen-%s-to-%s.json" % (source, source, target)


def cross_in(out, plan, checked, spec):
    """--cross PACKDEF=VECTOR:FIELD: decode FIELD of an existing vector with the
    other pack, encode with this pack, check the keys both map and write the
    vector into the other format's directory."""
    opts, pack = plan.opts, checked.pack
    packdef, _, rest = spec.partition("=")
    vfile, _, vfield = rest.rpartition(":")
    other = OtherPack.read(packdef, checked.model)
    src_vec = read_json(vfile, "--cross vector")
    if src_vec["to" if vfield == "expect" else "from"] != other.format:
        raise GenError("--cross %s: that text is not %s" % (spec, other.format))
    decoded = other.decode(src_vec[vfield])
    ent, skipped = apply_derives(checked.model, decoded)
    if skipped & pack.names():
        raise GenError("--cross %s: the engine would derive %s, which this pack writes" % (
            spec, " ".join(sorted(skipped & pack.names()))))
    ent = {k: v for k, v in ent.items() if k in decoded or k in pack.names()}
    b, chosen = engine_encode(pack, ent, None)
    if opts.default_kind and chosen != opts.default_kind:
        raise GenError("--cross %s: encoded as kind %s, not the default kind" % (spec, chosen))
    derived = would_derive(checked.model, ent) & pack.names()
    if derived:
        raise GenError("--cross %s: the engine would derive %s, which this pack writes" % (
            spec, " ".join(sorted(derived))))
    back, back_kind = engine_decode(pack, b)
    if back_kind != chosen:
        raise GenError("--cross %s: output decodes as kind %s" % (spec, back_kind))
    for k in sorted(k for k in ent if k in back):
        if back[k] != ent[k]:
            raise GenError("--cross %s: key %s does not survive" % (spec, k))
    carried = sorted(k for k in decoded if k in back)
    if vfield == "expect" and src_vec["from"] == opts.format and "".join(src_vec["input"].split()) != b.hex():
        raise GenError("--cross %s: does not return the bytes that vector started from" % spec)
    vec = {"name": "gen-%s-to-%s" % (other.format, opts.format), "from": other.format, "to": opts.format,
           "input": src_vec[vfield], "expect": b.hex(),
           "model": flat_model(decoded, values=2)}
    rel = cross_vector_path(other.format, opts.format)
    out.write(rel, dump_vector(vec))
    return CrossIn(other.format, chosen, carried, [k for k in decoded if k not in back], rel)


def omit_paths(pack, kname, ent, cross_omit):
    """--cross-omit: the message of kind `kname` without the keys bound to the
    given paths, encoded again. -> (hex, entity)."""
    omit = {tuple(map(int, p.split("."))) for p in cross_omit}
    lines = pack.common.fields + pack.kind(kname).fields
    unknown = omit - {path for _, path, _, _ in lines}
    if unknown:
        raise GenError("--cross-omit: kind %s has no field at %s" % (
            kname, " ".join(dotted(p) for p in sorted(unknown))))
    kept = {k: v for k, v in ent.items() if k not in {key for key, path, _, _ in lines if path in omit}}
    sample = engine_encode(pack, kept, kname)[0].hex()
    ent, got_kind = engine_decode(pack, bytes.fromhex(sample))
    if got_kind != kname or ent != kept:
        raise GenError("--cross-omit: the %s message without those paths does not decode as it was built" % kname)
    return sample, ent


def carried_keys(other, ent, seen, what):
    """The keys of `ent` that reached the other format, with their values:
    `seen` is what the other pack decodes from the text it wrote for `ent`.

    Every key of `seen` must be a key of `ent` with the same value. One case is
    not an error and is left out of the result: a key `ent` does not hold that
    the other pack reads from a locator it also reads a key of `ent` from, with
    that key's value (0.5 ruling 16: one locator, several keys). The other pack
    fills it from what `ent` wrote; `decode` of this format never yields it, so
    it is not part of what a vector from this format states. The key may also
    be of another type than the key of `ent` on its locator (the sender's text
    of an instant, `time_text`, beside `time_ms`): the same text read another way."""
    shares = other.keys_sharing_a_locator()
    carried = {}
    for k, v in seen.items():
        if k in ent:
            if not within(v, ent[k]):
                raise GenError("%s: key %s does not survive" % (what, k))
            carried[k] = v
        elif not any(p in ent and (within(v, ent[p]) or type(v) is not type(ent[p]))
                     for p in sorted(shares.get(k, ()))):
            raise GenError("%s: key %s does not survive" % (what, k))
    return carried


def cross_text(out, plan, checked, vectors, packdef, written):
    """--cross-text PACKDEF: convert the generated message of one kind into the
    other pack's format, and the result back. -> (CrossOut, CrossIn or None).
    The vector into the other format is written; the vector back is written
    unless `written` holds its path (--cross wrote one from that format), in
    which case it is checked only and no CrossIn is returned."""
    opts, pack, model = plan.opts, checked.pack, checked.model
    what = "--cross-text %s" % packdef
    other = OtherPack.read(packdef, model)
    kname = opts.cross_kind or opts.default_kind or plan.kinds[0].name
    if kname not in vectors.samples:
        raise GenError("--cross-kind %s is not a kind" % kname)
    sample = vectors.samples[kname]
    ent, got_kind = engine_decode(pack, bytes.fromhex(sample))
    if got_kind != kname:
        raise GenError("--cross-text: the %s message decodes as kind %s" % (kname, got_kind))
    if opts.cross_omit:
        sample, ent = omit_paths(pack, kname, ent, opts.cross_omit)
    derived = would_derive(model, ent) & other.mapped_keys()
    if derived:
        raise GenError("%s: the engine would derive %s, which that pack writes; "
                       "leave the paths bound to the keys it derives from out with --cross-omit" % (
                           what, " ".join(sorted(derived))))
    text = other.encode(ent)
    seen = other.decode(text)
    carried = carried_keys(other, ent, seen, what)
    model_out = {"@kind": kname}
    model_out.update(flat_model(carried, values=2))
    vec = {"name": "gen-%s-to-%s" % (opts.format, other.format), "from": opts.format, "to": other.format,
           "input": sample, "expect": text, "model": model_out}
    rel = cross_vector_path(opts.format, other.format)
    out.write(rel, dump_vector(vec))
    row_out = CrossOut(other.format, kname, sorted(carried), rel)

    # and back: the text just written, into this pack
    vec = {"name": "gen-%s-to-%s" % (other.format, opts.format), "from": other.format, "to": opts.format,
           "input": text}
    rel = cross_vector_path(other.format, opts.format)
    derived = would_derive(model, seen) & pack.names()
    if derived:
        raise GenError("%s: on the way back the engine would derive %s, which this pack writes" % (
            what, " ".join(sorted(derived))))
    try:
        b, chosen = engine_encode(pack, seen, None)
    except NoKind:
        vec["expect_error"] = "no-kind"
        row_in = CrossIn(other.format, None, [], sorted(seen), rel)
    else:
        if opts.default_kind and chosen != opts.default_kind:
            raise GenError("%s: encoded as kind %s, not the default kind" % (what, chosen))
        back, back_kind = engine_decode(pack, b)
        if back_kind != chosen:
            raise GenError("%s: output decodes as kind %s" % (what, back_kind))
        for k in seen:
            if k in back and not within(back[k], seen[k]):
                raise GenError("%s: key %s does not survive" % (what, k))
        if other.encode(back) != text:
            raise GenError("%s: the text does not come back" % what)
        vec["expect"] = b.hex()
        row_in = CrossIn(other.format, chosen, sorted(k for k in seen if k in back),
                         [k for k in seen if k not in back], rel)
    vec["model"] = flat_model(seen, values=2)
    if rel in written:
        return row_out, None
    out.write(rel, dump_vector(vec))
    return row_out, row_in


def cross_vectors(out, plan, checked, vectors):
    """Write every vector --cross and --cross-text ask for.
    -> (rows into this format, rows out of it)."""
    rows_in = [cross_in(out, plan, checked, spec) for spec in plan.opts.cross]
    written = {row.vector for row in rows_in}
    rows_out = []
    for packdef in plan.opts.cross_text:
        row_out, row_in = cross_text(out, plan, checked, vectors, packdef, written)
        rows_out.append(row_out)
        if row_in is not None:
            rows_in.append(row_in)
    return rows_in, rows_out


# --------------------------------------------------------------------------
# emit: pack.md and the run report
# --------------------------------------------------------------------------

def in_groups(groups):
    """(number of groups, number of `field` lines inside them), nested ones too."""
    ag = flat_groups(groups)
    return len(ag), sum(len(g.item_leaves()) for g in ag)


def schema_counts(plan):
    """The counts of the schema that pack.md and the report state."""
    reachable = set()

    def reach(m):
        if m.full in reachable:
            return
        reachable.add(m.full)
        for f in m.fields:
            if f.kind == "message":
                reach(f.ref)
    reach(plan.env)
    reasons = {}
    for skipped in plan.skipped_lists:
        for reason, *_ in skipped:
            reasons[reason] = reasons.get(reason, 0) + 1
    item_leaves = plan.item_leaves
    walked = {l.owner.full for l in plan.all_leaves + item_leaves} | {
        m.full for skipped in plan.skipped_lists for _, _, m, _ in skipped}
    return {
        "messages_defined": len([m for m in plan.schema.messages.values() if not m.full.startswith("google.")]),
        "enums_defined": len(plan.schema.enums),
        "reachable": len(reachable), "walked": len(walked), "reasons": reasons,
        "n_fields": sum(1 + len(l.cores) for l in plan.all_leaves) + len(plan.bound_keys) + len(item_leaves),
        "scalar_groups": sum(1 for g in plan.all_groups if g.scalar),
    }


def lowered_limits(plan, vectors):
    """One sentence for each limit the run lowered to stay within a budget."""
    budgets, limits = plan.budgets, []
    if plan.item_depth < plan.depth_asked:
        limits.append("Inside an item a path is at most %d field numbers long (`--max-item-depth`, lowered by the run "
                      "from %d): with longer paths pack.def would hold more than %d `field` lines." % (
                          plan.item_depth, plan.depth_asked, budgets.lines))
    if plan.nest < plan.nest_asked:
        limits.append("Groups stand at most %d inside one another (`--max-group-nesting`, lowered by the run from %d) "
                      "to keep pack.def within %d `field` lines and module `%s` within %d keys and lists." % (
                          plan.nest, plan.nest_asked, budgets.lines, plan.opts.module, budgets.keys))
    if vectors.n_items == 1:
        limits.append("The generated vectors hold one item per group: with two they would pass %d bytes."
                      % budgets.vector_bytes)
    return limits


def keys_cell(keys):
    """A table cell of keys: every key when there are few; the shared keys and a count otherwise."""
    if len(keys) <= 12:
        return " ".join("`%s`" % k for k in keys) or "none"
    shared = [k for k in keys if "." not in k]
    if len(shared) == len(keys):
        return " ".join("`%s`" % k for k in keys)
    return "%s and %d keys of other modules" % (" ".join("`%s`" % k for k in shared), len(keys) - len(shared))


def md_schema(plan, counts, n_vectors, n_cross):
    """The heading, the sources and the table of counts."""
    opts, env, base = plan.opts, plan.env, plan.base
    all_groups = plan.all_groups
    keys_row = "| keys in module `%s` | %d |" % (opts.module, len(base.keys) + len(plan.new_keys))
    fields_row = "| `field` lines | %d |" % counts["n_fields"]
    md = ["# Pack: %s" % opts.format, "",
          "Generated by `tools/gen/proto2pack.py` from the envelope message `%s`." % env.full,
          "Wire `protobuf`, engine-spec version 0.5 (message kinds) with the `const`, `map` and `via` lines",
          "of version 0.6 where the generator was given them, and a `group` block of version 0.7 for every",
          "`repeated` field it maps. Edit the generator, not this file.", "",
          "## Sources", ""] + ["- %s" % s for s in opts.source] + [
          "",
          "## Schema", "",
          "| | Count |", "|---|---|",
          "| .proto files read | %d |" % len(opts.proto),
          "| messages defined | %d |" % counts["messages_defined"],
          "| enums defined | %d |" % counts["enums_defined"],
          "| messages reachable from `%s` (through repeated fields too) | %d |" % (env.name, counts["reachable"]),
          "| message types on the walked paths | %d |" % counts["walked"],
          "| kinds | %d |" % len(plan.kinds)]
    # rows for the options a run was given; a run without them keeps the rows above and below
    if opts.max_depth != DEFAULT_MAX_DEPTH:
        md.append("| longest path walked (`--max-depth`) | %d |" % opts.max_depth)
    md += [fields_row,
           "| of those, inside a `group` | %d |" % len(plan.item_leaves),
           "| `group` blocks | %d |" % len(all_groups),
           "| of those, inside another group | %d |" % (len(all_groups) - len(plan.top_groups)),
           "| of those, a repeated scalar (one `.` field) | %d |" % counts["scalar_groups"]]
    if opts.module_base:
        md.append("| keys of module `%s` this pack maps | %d |" % (opts.module, len(plan.mod_keys)))
    md += [keys_row,
           "| lists in module `%s` | %d |" % (opts.module, len(base.lists) + len(plan.new_lists)),
           "| `field` lines bound to `core` or `track` keys | %d |" % (len(plan.core_lines) + len(plan.bound_keys)),
           "| `const` lines | %d |" % sum(len(c) for c in plan.consts.values()),
           "| value tables (`map` lines) | %d (%d) |" % (len(plan.tables), sum(len(e) for e in plan.tables.values())),
           "| vectors (existing and generated) | %d |" % n_vectors]
    if opts.cross_text:
        md.append("| vectors to and from other formats, generated | %d |" % n_cross)
    return md + [""]


def md_kinds(plan):
    md = ["## Kinds", "",
          "| Kind | Selected by | Fields | Groups | Fields in groups | Requires |", "|---|---|---|---|---|---|"]
    if plan.common or plan.common_groups:
        md.append("| (common) | every message | %d | %d | %d | |" % ((len(plan.common),) + in_groups(plan.common_groups)))
    for kind in plan.kinds:
        md.append("| `%s` | %s | %d | %d | %d | %s |" % ((
            kind.name,
            "`when %d present`" % kind.number if kind.number is not None else "always (the format has one layout)",
            len(kind.leaves)) + in_groups(kind.groups) + (" ".join("`%s`" % r for r in kind.requires) or "none",)))
    return md


def md_repeated(plan, limits):
    md = ["", "## Repeated fields", "",
          "A `repeated` field is a `group` block and a list of module `%s` (engine-spec 0.7). The block's" % plan.opts.module,
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
    if any(reason == R_BOUND for skipped in plan.skipped_lists for reason, *_ in skipped):
        md += ["- A repeated message that a hand binding reads through (below) is not a group: a `field` and a",
               "  `group` on one path are not defined together. One occurrence of it is carried, the last on decode."]
    if limits:
        md += [""] + limits
    return md


def md_shared_keys(plan):
    opts, core_lines = plan.opts, plan.core_lines
    md = ["", "## Mapped to shared keys", ""]
    if core_lines and opts.no_comments:
        md += ["| Key | Path | Schema field |", "|---|---|---|"]
        md += ["| `%s` | `%s` | `%s.%s` (%s) |" % (c, dotted(l.nums), l.owner.name,
                                                 l.field.name, l.field.type) for l in core_lines for c in l.cores]
    elif core_lines:
        md += ["| Key | Path | Schema field | Schema comment |", "|---|---|---|---|"]
        for l in core_lines:
            for c in l.cores:
                md.append("| `%s` | `%s` | `%s.%s` (%s) | %s |" % (c, dotted(l.nums), l.owner.name,
                                                                 l.field.name, l.field.type, l.field.comment or "none"))
    else:
        md.append("None.")
    if core_lines:
        md += ["", "Each of these paths has two `field` lines (0.5 ruling 16): the shared key first, the",
               "raw key of module `%s` second. Decode fills both keys with the same value. On encode" % opts.module,
               "the value written is that of the earliest line whose key is present: the shared key",
               "when the entity has it, the raw key only when the shared key is absent. So a consumer",
               "that changes the shared key and encodes back to this format gets the new value, and an",
               "entity from another format, which has only the shared key, writes it."]
        multi = [l for l in core_lines if len(l.cores) > 1]
        if multi:
            md += ["", "%s %s more than one shared key: one line per key, in the order given, before the" % (
                       ", ".join("`%s`" % dotted(l.nums) for l in multi), "carries" if len(multi) == 1 else "carry"),
                   "raw key. Decode fills every key with the value; encode writes the value of the first",
                   "key the entity has."]
    if plan.binds:
        md += ["", "Bound by hand to a path the walk does not descend (a repeated message; one occurrence",
               "is carried, the last on decode):", "", "| Key | Path | Transform | Table |", "|---|---|---|---|"]
        md += ["| `%s` | `%s` | `%s` | %s |" % (key, p, tr, "`%s`" % table if table else "none")
               for bs in plan.binds.values() for key, p, tr, table in bs]
    if plan.consts:
        md += ["", "Constants, written on every encode of the kind over any field (engine-spec 0.6):", "",
               "| Kind | Path | Value |", "|---|---|---|"]
        md += ["| `%s` | `%s` | %s |" % (k, p, v) for k, cs in plan.consts.items() for p, v in cs]
    return md


def md_cross(plan, rows_in, rows_out):
    opts = plan.opts
    default = opts.default_kind
    md = ["", "## Encoding from another format", ""]
    if plan.single:
        md += ["The pack has one kind, with no `when` and no `requires`: every entity encodes as `%s`," % plan.kinds[0].name,
               "and the shared keys it carries are written."]
    elif default and plan.beside and plan.kinds[0].name == default:
        requires = "` `".join(plan.kind(default).requires)
        md += ["Kinds are tried in pack order and the first whose `requires` keys are all present is used.",
               "`%s` is first and requires `%s`: an entity from another format that has" % (default, requires),
               "those keys encodes as `%s`. %s after it and" % (
                   default, " ".join("`%s` stands" % n for n in plan.beside)),
               "requires a raw key of module `%s`, which only a %s message or the caller (`convert`" % (
                   opts.module, opts.format),
               "context) supplies; an entity that has the keys of no kind ends in `no-kind`."]
    elif default:
        requires = "` `".join(plan.kind(default).requires)
        md += ["Kinds are tried in pack order and the first whose `requires` keys are all present is used.",
               "Every kind before `%s` requires raw keys of module `%s`%s" % (
                   default, opts.module,
                   " that no other kind of this pack" if opts.module_base else ", which only a %s message" % opts.format),
               "%s. `%s` requires `%s`: an entity from another format" % (
                   "maps" if opts.module_base else "carries", default, requires),
               "that has those keys encodes as `%s`. The kinds after it have no field of their own and" % default,
               "require only common keys, so they are reached only by an entity that lacks",
               "`%s`; one that has the keys of no kind ends in `no-kind`." % requires]
    else:
        md += ["Every kind requires raw keys of module `%s` that no other kind of this pack maps, so an entity" % opts.module,
               "from a format that does not use that module ends in `no-kind`."]
    if rows_in:
        md += ["", "| From | Encodes as | Keys carried | Keys the pack has no place for | Vector |", "|---|---|---|---|---|"]
        for row in rows_in:
            md.append("| `%s` | %s | %s | %s | `%s` |" % (
                row.source, "`%s`" % row.kind if row.kind else "error `no-kind`",
                keys_cell(row.carried), keys_cell(row.dropped), row.vector))
    if rows_out:
        md += ["", "## Encoding into another format", "",
               "A key crosses when the other pack maps it: the shared keys, and the keys of module `%s`" % opts.module,
               "only into a pack that also uses that module.", "",
               "| To | From kind | Keys carried | Vector |", "|---|---|---|---|"]
        for row in rows_out:
            md.append("| `%s` | `%s` | %s | `%s` |" % (row.target, row.kind, keys_cell(row.carried), row.vector))
        if opts.cross_omit:
            md += ["", "The message converted is the generated round-trip message without the paths %s." % (
                       " ".join("`%s`" % p for p in opts.cross_omit)),
                   "Each is bound to a key a `derive` line of a model module reads, and the key derived from it",
                   "is one the other pack writes; a vector states a derived value in `model`, never in the",
                   "expected output (engine-spec, derived keys)."]
    return md


def md_vectors(vectors):
    md = ["", "## Generated vectors", "",
          "`vectors/gen-<n>-<kind>-roundtrip.json`, one per kind: every mapped field of the kind, one member",
          "per `oneof` (the one bound to a shared key, else the lowest field number, so that the bytes are a",
          "message of the schema), and every group with %s and one item in a group inside" % (
              "two items" if vectors.n_items == 2 else "one item"),
          "another. Fields are in ascending number order, the items of a list one after another, a repeated",
          "number packed, so `input` equals `expect`. `model` holds every key of the message, `<list>.#` of",
          "every list and the first two keys of every item."]
    if vectors.n_variants:
        md += ["`gen-<n>-<kind>-roundtrip-oneof<j>.json` (%d): the same message with, of every `oneof`, the member"
               % vectors.n_variants,
               "j places further on; written when that brings in a group no earlier vector of the kind holds."]
    if vectors.groups_out:
        md += ["%d groups are in no vector: they lie under a `oneof` member no vector sets." % vectors.groups_out]
    return md + [""]


def md_not_mapped(plan, reasons):
    md = ["## Not mapped", "",
          "Counted once per place a field is reached in a kind's tree, inside groups too. Everything",
          "below a field that is not descended is not counted.", "",
          "| Reason | Fields |", "|---|---|"]
    for r in sorted(reasons, key=lambda r: -reasons[r]):    # stable: most fields first, then first met
        md.append("| %s | %d |" % (r, reasons[r]))
    if not reasons:
        md.append("| (none) | 0 |")
    md += ["", "Per kind:", "", "| Kind | Mapped | Mapped inside groups | Not mapped |", "|---|---|---|---|"]
    if plan.common or plan.skipped_common or plan.common_groups:
        md.append("| (common) | %d | %d | %d |" % (
            len(plan.common), in_groups(plan.common_groups)[1], len(plan.skipped_common)))
    for kind in plan.kinds:
        by = {}
        for r, *_ in kind.skipped:
            by[r] = by.get(r, 0) + 1
        md.append("| `%s` | %d | %d | %s |" % (kind.name, len(kind.leaves), in_groups(kind.groups)[1],
                                              ", ".join("%d %s" % (by[r], r) for r in sorted(by)) or "0"))
    if plan.empty_kinds:
        md += ["", "Kinds with no mappable field: " + ", ".join("`%s` (field %d)" % e for e in plan.empty_kinds) + ".",
               "Such a kind has a `when` line and no `field` line. Its message decodes to the common keys,",
               "and on encode the member is written as an empty length-delimited field (0.5 ruling 14),",
               "so the kind survives a round trip while the content of the message does not."]
    md += ["", "## What this pack does not express", "",
           "- `map` fields: no line addresses an entry by its key.",
           "- `bytes` and the fixed-width integer types, single or repeated: no transform yields them.",
           "- A value below path depth %d, and a message type that contains itself: the walk stops where a" % plan.opts.max_depth,
           "  message type would stand inside itself, through a repeated field as through a single one.",
           "- An unmapped field of an item: items carry no residue (engine-spec 0.7).",
           "- The content of a message with no mappable field: its kind is kept, its fields are not.",
           "- Which member of a nested `oneof` is set: each member's fields are plain `field` lines of the kind",
           "  or of the group. An item is not decoded by a discriminator (0.7 has no `when` inside a group).",
           "- Enum names: an enum is carried as its number; the module key's meaning lists the names.",
           "- `google.protobuf.Timestamp`: carried as two raw integer keys (seconds, nanos); no transform joins them into `time_ms`.",
           ""]
    return md


def emit_pack_md(plan, vectors, n_vectors, rows_in, rows_out, notes=None):
    """The text of packs/<format>/pack.md. `notes` is the text of --notes-file."""
    counts = schema_counts(plan)
    md = md_schema(plan, counts, n_vectors, len(rows_in) + len(rows_out))
    md += md_kinds(plan)
    md += md_repeated(plan, lowered_limits(plan, vectors))
    md += md_shared_keys(plan)
    md += md_cross(plan, rows_in, rows_out)
    if notes is not None:
        md += ["", notes.rstrip("\n")]
    md += md_vectors(vectors)
    md += md_not_mapped(plan, counts["reasons"])
    return "\n".join(md)


def run_report(plan, vectors, n_vectors, rows_in, rows_out):
    """The counts of a run, printed as JSON on standard output."""
    opts, base = plan.opts, plan.base
    counts = schema_counts(plan)
    all_groups, n_top = plan.all_groups, len(plan.top_groups)
    return {
        "format": opts.format, "envelope": plan.env.full,
        "files": len(opts.proto),
        "messages_defined": counts["messages_defined"],
        "enums_defined": counts["enums_defined"],
        "messages_reachable": counts["reachable"], "message_types_walked": counts["walked"],
        "kinds": [{"name": k.name, "when": k.number, "fields": len(k.leaves), "requires": k.requires,
                   "groups": in_groups(k.groups)[0], "fields_in_groups": in_groups(k.groups)[1],
                   "not_mapped": len(k.skipped)} for k in plan.kinds],
        "common_fields": len(plan.common), "field_lines": counts["n_fields"],
        "module_keys": len(base.keys) + len(plan.new_keys), "pack_module_keys": len(plan.mod_keys),
        "shared_key_lines": len(plan.core_lines),
        "not_mapped_by_reason": counts["reasons"], "vectors_checked": n_vectors,
        "kinds_without_fields": [n for n, _ in plan.empty_kinds],
        "cross_vectors": [{"from": r.source, "kind": r.kind, "carried": r.carried, "dropped": r.dropped}
                          for r in rows_in],
        "cross_out_vectors": [{"to": r.target, "kind": r.kind, "carried": r.carried} for r in rows_out],
        "max_depth": opts.max_depth, "names_inherited": plan.inherited,
        "groups": len(all_groups), "groups_first_level": n_top, "groups_nested": len(all_groups) - n_top,
        "groups_scalar": counts["scalar_groups"], "field_lines_in_groups": len(plan.item_leaves),
        "module_lists": len(base.lists) + len(plan.new_lists), "group_nesting_limit": plan.nest,
        "item_depth_limit": plan.item_depth,
        "limits_lowered": lowered_limits(plan, vectors), "vector_items_per_group": vectors.n_items,
        "generated_vector_bytes": vectors.gen_bytes,
        "groups_in_no_vector": vectors.groups_out, "oneof_variant_vectors": vectors.n_variants,
        "module_keys_from_base": len(base.keys), "module_keys_new": len(plan.new_keys),
    }


# --------------------------------------------------------------------------
# command line
# --------------------------------------------------------------------------

DESCRIPTION = """\
Turn protobuf schema files into a goat-transformers pack.

Reads: the .proto files (--proto), the model modules under <out>/model (core.def
and every module a --map key names), the names file if it exists, and what
--module-base, --names-from, --supersedes, --cross, --cross-text and
--notes-file name.

Writes under --out: model/<module>.def, packs/<format>/pack.def, pack.md and
vectors/gen-*.json (every gen-*.json there is replaced), one
packs/<other>/vectors/gen-<other>-to-<format>.json per --cross and --cross-text
pack, and the names file. A summary of the run is printed as JSON on standard
output.

Guarantees: the same input gives the same bytes. A refused input writes
nothing. What was written is loaded with gtcheck, as an engine loads it, and
every vector of the pack, existing and generated, is decoded and encoded with
a codec written from the specification; the run fails when one does not hold.

Exit status: 0 done (with --check: every file is what the generator writes),
1 a refused input, a failed check or a --check difference, 2 a usage error."""


def argument_parser():
    ap = argparse.ArgumentParser(prog="proto2pack.py", description=DESCRIPTION,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proto", nargs="+", required=True, help=".proto files (imports are resolved among them by file name)")
    ap.add_argument("--envelope", required=True, help="top-level message name")
    ap.add_argument("--format", required=True, help="format name of the pack: packs/<format>/")
    ap.add_argument("--module", required=True, help="model module the raw keys go to: model/<module>.def")
    genio.add_arguments(ap, what="checkout root holding model/ and packs/")
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
    ap.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
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
    ap.add_argument("--one-layout", action="store_true",
                    help="the envelope is one kind even when it has a oneof: every member's fields are lines of it "
                         "(for a oneof with scalar or empty members, which cannot each be a kind)")
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
    ap.add_argument("--derive", action="append", default=[], metavar="'TARGET FUNCTION ARG...'",
                    help="a derive line (engine-spec 0.6) written at the end of the module; the target is "
                         "a key of --module; an argument of another module adds its `uses` line; repeatable")
    return ap


def generate(opts, out, budgets=DEFAULT_BUDGETS):
    """One run: parse, plan, emit, self-check. Every file goes through `out`
    (a genio.Output). Returns the run report.

    Nothing is written before the plan is whole. The module and the pack are
    written and loaded before a vector is built, so a key of the wrong type is
    refused by the load check and not met while a message is encoded."""
    schema = load_schema(opts.proto, opts.mandatory_option, comments=not opts.no_comments)
    plan = make_plan(schema, opts, budgets)
    module_text, pack_text = emit_module(plan), emit_pack(plan)
    notes = None
    if opts.notes_file:
        with open(opts.notes_file, encoding="utf-8") as fh:
            notes = fh.read()

    if opts.names_file:
        out.write(os.path.relpath(os.path.abspath(opts.names_file), out.root).replace(os.sep, "/"), emit_names(plan))
    out.write("model/%s.def" % opts.module, module_text)
    pack_dir = "packs/%s" % opts.format
    out.write(pack_dir + "/pack.def", pack_text)
    checked = self_check(out, plan)

    vectors = emit_vectors(plan, budgets.vector_bytes)
    for name in out.listdir(pack_dir + "/vectors"):
        if name.startswith("gen-") and name.endswith(".json"):
            out.remove("%s/vectors/%s" % (pack_dir, name))
    for name, text in vectors.texts.items():
        out.write("%s/vectors/%s" % (pack_dir, name), text)
    checked.n_vectors = check_vectors(out, pack_dir + "/vectors", opts.format, checked.pack, checked.old_pack)

    rows_in, rows_out = cross_vectors(out, plan, checked, vectors)
    out.write(pack_dir + "/pack.md", emit_pack_md(plan, vectors, checked.n_vectors, rows_in, rows_out, notes))
    return run_report(plan, vectors, checked.n_vectors, rows_in, rows_out)


def main(argv=None, budgets=DEFAULT_BUDGETS):
    """Run the generator; returns the exit status. `budgets` is for tests."""
    opts = argument_parser().parse_args(argv)
    out = genio.Output(opts.out, check=opts.check)
    try:
        report = generate(opts, out, budgets)
    except (GenError, gtcheck.CheckError) as e:
        print("proto2pack: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("proto2pack: %s: %s" % (e.filename, e.strerror), file=sys.stderr)
        return 1
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return out.report("proto2pack")


if __name__ == "__main__":
    sys.exit(main())
