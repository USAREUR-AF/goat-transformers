#!/usr/bin/env python3
"""yang2pack: a YANG data tree in its JSON encoding (RFC 7951) as a goat-transformers pack.

Usage: python3 -I tools/gen/yang2pack.py [--check] --search DIR ... --module NAME --top NODE
           [--augment-module NAME ...] --format F --model-module M --title T --out CHECKOUT ...

One pack is one message: the JSON object that holds one top-level data node (a container
or a list) of one YANG module, `{"<module>:<node>": ...}`, as a NETCONF or RESTCONF
server or a gNMI target in JSON_IETF encoding returns it. The modules named with
--augment-module add their augments to that tree; every other module is read only for
what the tree imports (groupings, typedefs, identities, the targets of leafrefs).

The program is Python 3 standard library only. It

  1. reads every module and submodule it needs from the --search directories (a strict
     reader of the YANG statement grammar of RFC 7950 section 6: quoted and unquoted
     strings, `+` concatenation, comments; anything else is refused with file and line);
  2. builds the schema tree: `uses` expanded (its `augment` applied, `refine` ignored as it
     changes no type), choices and cases kept for augment paths, module augments applied
     until none is left, `if-feature` taken as enabled, rpc, action and notification left out;
  3. gives each leaf the JSON type RFC 7951 section 6 states for its YANG type (leafrefs
     through their target, typedefs through their chain, unions through their members);
  4. writes the tree as a JSON Schema document to a temporary directory and passes it to
     tools/gen/jsonschema2pack.py in this process, which writes the pack, the model module,
     pack.md and the round-trip vectors and checks them with its own codec;
  5. writes packs/<format>/PROVENANCE.md: every YANG file read, its SHA-256, the licence
     statement found in it.

What each YANG construct becomes on the json wire:

  container                 a nested object (a dotted path)
  list, leaf-list           a `group` (engine-spec 0.7); a leaf-list item is one `.` line
  choice, case              nothing of their own: their nodes sit in the parent object
  int8 .. int32, uint8 .. uint32      `int` (a JSON number)
  int64, uint64, decimal64  `string` (RFC 7951 6.1 writes them as JSON strings)
  boolean                   `bool`
  string, enumeration, bits, binary, identityref, instance-identifier   `string`
  union                     the one JSON type of all its members; members of several JSON
                            types are not mapped (the wire carries such a scalar as residue)
  empty                     not mapped: its value is `[null]`, an array the json wire does not carry
  anydata, anyxml           not mapped: member names are data
  leafref                   the type of the leaf it refers to; a target outside the modules
                            read is not mapped

Every file goes through tools/gen/genio.py: with --check nothing is written, and the exit
status is 1 when a file differs. Exit status 1 also for a refused input, 2 for usage.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio              # noqa: E402
import jsonschema2pack    # noqa: E402

NAME = "yang2pack"


class YangError(Exception):
    pass


# --------------------------------------------------------------------------
# Reading: the statement grammar (RFC 7950 section 6)
# --------------------------------------------------------------------------

class Stmt:
    __slots__ = ("kw", "arg", "subs", "parent", "ctx", "line")

    def __init__(self, kw, arg, line):
        self.kw, self.arg, self.subs, self.parent, self.ctx, self.line = kw, arg, [], None, None, line

    def find(self, kw):
        for s in self.subs:
            if s.kw == kw:
                return s
        return None

    def find_all(self, kw):
        return [s for s in self.subs if s.kw == kw]

    def where(self):
        return "%s:%d" % (self.ctx.file_name if self.ctx else "?", self.line)


def _dq_trim(raw, col):
    """A double-quoted string's text: escapes, and the indentation and trailing white
    space RFC 7950 6.1.3 strips around line breaks. `col` is the column of the quote."""
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == "\\":
            if i + 1 >= len(raw):
                raise YangError("a backslash at the end of a string")
            n = raw[i + 1]
            if n not in 'nt"\\':
                raise YangError("the escape \\%s is not one of \\n \\t \\\" \\\\" % n)
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}[n])
            i += 2
            continue
        out.append(c)
        i += 1
    text = "".join(out)
    lines = text.split("\n")
    res = [lines[0].rstrip(" \t") if len(lines) > 1 else lines[0]]
    for k, ln in enumerate(lines[1:], 1):
        j, width = 0, 0
        while j < len(ln) and ln[j] in " \t" and width <= col:
            width += 8 - (width % 8) if ln[j] == "\t" else 1
            j += 1
        ln = ln[j:]
        res.append(ln.rstrip(" \t") if k < len(lines) - 1 else ln)
    return "\n".join(res)


def tokenize(text, file_name):
    """[(kind, value, line)]: kind is ';', '{', '}' or 'str' (value the string's text)."""
    toks, i, line, n = [], 0, 1, len(text)
    line_start = 0
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if c in " \t\r":
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise YangError("%s:%d: a comment that does not end" % (file_name, line))
            line += text.count("\n", i, j)
            if text.count("\n", i, j):
                line_start = text.rfind("\n", i, j) + 1
            i = j + 2
            continue
        if c in ";{}":
            toks.append((c, None, line))
            i += 1
            continue
        if c == '"':
            col = i - line_start
            j, start = i + 1, i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise YangError("%s:%d: a double-quoted string that does not end" % (file_name, line))
            raw = text[start:j]
            try:
                val = _dq_trim(raw, col)
            except YangError as e:
                raise YangError("%s:%d: %s" % (file_name, line, e))
            toks.append(("qstr", val, line))
            line += raw.count("\n")
            if raw.count("\n"):
                line_start = start + raw.rfind("\n") + 1
            i = j + 1
            continue
        if c == "'":
            j = text.find("'", i + 1)
            if j < 0:
                raise YangError("%s:%d: a single-quoted string that does not end" % (file_name, line))
            raw = text[i + 1:j]
            toks.append(("qstr", raw, line))
            line += raw.count("\n")
            if raw.count("\n"):
                line_start = i + 1 + raw.rfind("\n") + 1
            i = j + 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n;{}\"'" and not text.startswith("//", j) \
                and not text.startswith("/*", j):
            j += 1
        if j == i:
            raise YangError("%s:%d: unexpected %r" % (file_name, line, text[i]))
        toks.append(("str", text[i:j], line))
        i = j
    return toks


def parse(text, file_name):
    """The one top statement of a file (module or submodule)."""
    toks = tokenize(text, file_name)
    pos = [0]

    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else (None, None, toks[-1][2] if toks else 0)

    def statement():
        kind, kw, line = peek()
        if kind != "str":
            raise YangError("%s:%d: a keyword was expected" % (file_name, line))
        if not re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.-]*:)?[A-Za-z_][A-Za-z0-9_.-]*", kw):
            raise YangError("%s:%d: %r is not a keyword" % (file_name, line, kw))
        pos[0] += 1
        arg = None
        kind, val, _ = peek()
        if kind in ("str", "qstr"):
            parts = [val]
            pos[0] += 1
            while peek()[0] == "str" and peek()[1] == "+":
                pos[0] += 1
                k2, v2, l2 = peek()
                if k2 != "qstr":
                    raise YangError("%s:%d: `+` joins quoted strings only" % (file_name, l2))
                if kind != "qstr":
                    raise YangError("%s:%d: `+` joins quoted strings only" % (file_name, l2))
                parts.append(v2)
                pos[0] += 1
            arg = "".join(parts)
        st = Stmt(kw, arg, line)
        kind, _, l3 = peek()
        if kind == ";":
            pos[0] += 1
        elif kind == "{":
            pos[0] += 1
            while peek()[0] != "}":
                if peek()[0] is None:
                    raise YangError("%s:%d: a block that does not end" % (file_name, line))
                sub = statement()
                sub.parent = st
                st.subs.append(sub)
            pos[0] += 1
        else:
            raise YangError("%s:%d: `;` or `{` was expected after %s" % (file_name, l3, kw))
        return st

    top = statement()
    if pos[0] != len(toks):
        raise YangError("%s:%d: text after the end of the %s" % (file_name, toks[pos[0]][2], top.kw))
    if top.kw not in ("module", "submodule"):
        raise YangError("%s: the file holds a %s, not a module or submodule" % (file_name, top.kw))
    return top


# --------------------------------------------------------------------------
# Modules and lookup
# --------------------------------------------------------------------------

class Ctx:
    """What a name in one file means: its own prefix, its imports, the module it is part of."""

    def __init__(self, file_name, module, prefix, imports):
        self.file_name, self.module, self.prefix, self.imports = file_name, module, prefix, imports


class Module:
    def __init__(self, name):
        self.name, self.stmts, self.files = name, [], []    # stmts: module stmt, then submodules


def _set_ctx(st, ctx):
    st.ctx = ctx
    for s in st.subs:
        _set_ctx(s, ctx)


class Library:
    """The YANG files of the search directories, read on demand."""

    def __init__(self, root, search):
        self.root = os.path.abspath(root)
        self.index = {}             # name -> {revision or "": path}
        for d in search:
            base = os.path.join(self.root, d)
            if not os.path.isdir(base):
                raise YangError("search directory %s does not exist" % d)
            for dirpath, dirs, names in os.walk(base):
                dirs.sort()
                for f in sorted(names):
                    m = re.fullmatch(r"([A-Za-z0-9_.-]+?)(?:@(\d{4}-\d{2}-\d{2}))?\.yang", f)
                    if not m:
                        continue
                    self.index.setdefault(m.group(1), {}).setdefault(m.group(2) or "", os.path.join(dirpath, f))
        self.modules = {}           # name -> Module
        self.read = collections.OrderedDict()   # relative path -> (sha256, statement text, module name)

    def path_of(self, name, revision):
        revs = self.index.get(name)
        if not revs:
            raise YangError("no file of module %s in the search directories" % name)
        if revision:
            if revision in revs:
                return revs[revision]
            if "" in revs and self._revision(revs[""]) == revision:
                return revs[""]
            raise YangError("no file of %s revision %s" % (name, revision))
        if "" in revs:
            return revs[""]
        return revs[max(revs)]

    @staticmethod
    def _revision(path):
        with open(path, encoding="utf-8") as fh:
            m = re.search(r"\brevision\s+\"?(\d{4}-\d{2}-\d{2})", fh.read())
        return m.group(1) if m else None

    def _parse_file(self, path):
        real = os.path.realpath(path)
        rel = os.path.relpath(real, self.root).replace(os.sep, "/")
        with open(real, "rb") as fh:
            data = fh.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise YangError("%s is not UTF-8" % rel)
        top = parse(text, rel)
        if rel not in self.read:
            self.read[rel] = (hashlib.sha256(data).hexdigest(), licence_statement(top), top.arg)
        return top, rel

    def module(self, name, revision=None):
        if name in self.modules:
            return self.modules[name]
        top, rel = self._parse_file(self.path_of(name, revision))
        if top.kw != "module" or top.arg != name:
            raise YangError("%s holds %s %s, not module %s" % (rel, top.kw, top.arg, name))
        mod = Module(name)
        self.modules[name] = mod
        self._attach(mod, top, rel, name)
        return mod

    def _attach(self, mod, top, rel, module_name):
        if top.kw == "module":
            pfx = top.find("prefix")
        else:
            bt = top.find("belongs-to")
            if bt is None or bt.arg != module_name:
                raise YangError("%s: submodule %s does not belong to %s" % (rel, top.arg, module_name))
            pfx = bt.find("prefix")
        if pfx is None:
            raise YangError("%s: no prefix" % rel)
        imports = {}
        for imp in top.find_all("import"):
            p = imp.find("prefix")
            if p is None:
                raise YangError("%s:%d: import %s has no prefix" % (rel, imp.line, imp.arg))
            rd = imp.find("revision-date")
            imports[p.arg] = (imp.arg, rd.arg if rd is not None else None)
        ctx = Ctx(rel, module_name, pfx.arg, imports)
        _set_ctx(top, ctx)
        mod.stmts.append(top)
        mod.files.append(rel)
        for inc in top.find_all("include"):
            if any(s.arg == inc.arg for s in mod.stmts):
                continue
            rd = inc.find("revision-date")
            sub, srel = self._parse_file(self.path_of(inc.arg, rd.arg if rd is not None else None))
            if sub.kw != "submodule" or sub.arg != inc.arg:
                raise YangError("%s holds %s %s, not submodule %s" % (srel, sub.kw, sub.arg, inc.arg))
            self._attach(mod, sub, srel, module_name)

    def imported(self, ctx, prefix, where):
        """The Module a prefix names in a file."""
        if prefix == ctx.prefix:
            return self.module(ctx.module)
        if prefix not in ctx.imports:
            raise YangError("%s: prefix %s is not imported" % (where, prefix))
        name, rev = ctx.imports[prefix]
        return self.module(name, rev)

    def lookup(self, kw, ref, at):
        """The `grouping` or `typedef` statement `ref` (`name` or `prefix:name`) names,
        seen from statement `at`: its enclosing blocks, then the module's top level
        (with its submodules), or an imported module's top level."""
        pfx, _, name = ref.rpartition(":")
        ctx = at.ctx
        if not pfx or pfx == ctx.prefix:
            s = at
            while s is not None:
                for c in s.subs:
                    if c.kw == kw and c.arg == name:
                        return c
                s = s.parent
            mod = self.module(ctx.module)
        else:
            mod = self.imported(ctx, pfx, at.where())
        for top in mod.stmts:
            for c in top.subs:
                if c.kw == kw and c.arg == name:
                    return c
        raise YangError("%s: %s %s is not defined" % (at.where(), kw, ref))


LICENCE_PATTERNS = (("Simplified BSD License", "BSD-2-Clause"), ("Revised BSD License", "BSD-3-Clause"))


def licence_statement(top):
    """(SPDX id or None, the copyright and licence paragraph of the module's description)."""
    d = top.find("description")
    text = d.arg if d is not None and d.arg else ""
    m = re.search(r"Copyright \(c\).*?full legal notices\.", text, re.S) or \
        re.search(r"Copyright \(c\).*?BSD License.*?(?:\)\.|\.\s*\n\n|$)", text, re.S)
    para = re.sub(r"\s+", " ", m.group(0)).strip() if m else ""
    spdx = None
    for phrase, sid in LICENCE_PATTERNS:
        if phrase in para:
            spdx = sid
    return spdx, para


# --------------------------------------------------------------------------
# The schema tree
# --------------------------------------------------------------------------

DATA = ("container", "list", "leaf", "leaf-list", "choice", "case", "anydata", "anyxml")


class Node:
    def __init__(self, kind, name, ns, stmt, parent):
        self.kind, self.name, self.ns, self.stmt, self.parent = kind, name, ns, stmt, parent
        self.children = []

    def child(self, name, ns=None):
        hits = [c for c in self.children if c.name == name]
        if ns is not None:
            exact = [c for c in hits if c.ns == ns]
            if exact:
                hits = exact
        return hits[0] if len(hits) == 1 else (hits[0] if hits and ns is not None else None)

    def data_parent(self):
        p = self.parent
        while p is not None and p.kind in ("choice", "case"):
            p = p.parent
        return p

    def data_children(self):
        for c in self.children:
            if c.kind in ("choice", "case"):
                yield from c.data_children()
            else:
                yield c


class Tree:
    def __init__(self, lib):
        self.lib = lib
        self.roots = collections.OrderedDict()      # module name -> root Node (kind "root")
        self.pending = []                            # (augment stmt, module name)
        self.applied = set()                         # modules whose augments are applied
        self.dropped = []                            # (augment stmt, module name) not applied

    def build_module(self, name, augments):
        mod = self.lib.module(name)
        if name in self.roots:
            return
        root = Node("root", name, name, None, None)
        self.roots[name] = root
        for top in mod.stmts:
            self.children(top, root, name, depth=0)
            if augments:
                self.applied.add(name)
                self.pending += [(a, name) for a in top.find_all("augment")]

    def children(self, st, node, ns, depth):
        if depth > 64:
            raise YangError("%s: groupings nest more than 64 deep (a loop?)" % st.where())
        for s in st.subs:
            if s.kw in ("container", "list", "leaf", "leaf-list", "anydata", "anyxml"):
                if node.kind == "choice":       # a shorthand case
                    case = Node("case", s.arg, ns, s, node)
                    node.children.append(case)
                    self.add(s, case, ns, depth)
                else:
                    self.add(s, node, ns, depth)
            elif s.kw in ("choice", "case"):
                self.add(s, node, ns, depth)
            elif s.kw == "uses":
                g = self.lib.lookup("grouping", s.arg, s)
                self.children(g, node, ns, depth + 1)
                for aug in s.find_all("augment"):
                    target = self.descend(node, aug.arg, aug)
                    self.children(aug, target, ns, depth + 1)

    def add(self, s, parent, ns, depth):
        n = Node(s.kw, s.arg, ns, s, parent)
        parent.children.append(n)
        if s.kw in ("container", "list", "choice", "case"):
            self.children(s, n, ns, depth)
        return n

    def _steps(self, path, at):
        out = []
        for step in path.strip().split("/"):
            if not step:
                continue
            pfx, _, name = step.rpartition(":")
            mod = self.lib.imported(at.ctx, pfx, at.where()).name if pfx else None
            out.append((mod, name))
        return out

    def descend(self, node, path, at):
        cur = node
        for mod, name in self._steps(path, at):
            nxt = cur.child(name, mod)
            if nxt is None:
                raise YangError("%s: %s names no node below %s" % (at.where(), path, cur.name))
            cur = nxt
        return cur

    def apply_augments(self):
        """Every pending module augment whose target exists, until none is left; an augment
        into a module whose tree is not built is dropped and returned."""
        dropped = []
        while self.pending:
            left, progress = [], False
            for aug, ns in self.pending:
                steps = self._steps(aug.arg, aug)
                if not aug.arg.startswith("/") or not steps:
                    raise YangError("%s: augment %s is not an absolute path" % (aug.where(), aug.arg))
                if any(m not in self.applied for m, _ in steps):
                    # into a node of a module whose augments this tree does not apply
                    dropped.append((aug, ns))
                    progress = True
                    continue
                cur = self.roots[steps[0][0]]
                for mod, name in steps:
                    cur = cur.child(name, mod) if cur is not None else None
                if cur is None:
                    left.append((aug, ns))
                    continue
                if cur.kind in ("leaf", "leaf-list", "anydata", "anyxml"):
                    raise YangError("%s: augment %s targets a %s" % (aug.where(), aug.arg, cur.kind))
                self.children(aug, cur, ns, 0)
                progress = True
            self.pending = left
            if not progress:
                # what is left targets nodes of an rpc, action or notification, or is wrong
                for aug, ns in left:
                    if not self._targets_operation(aug):
                        raise YangError("%s: augment %s names no node" % (aug.where(), aug.arg))
                    dropped.append((aug, ns))
                self.pending = []
        return dropped

    def _targets_operation(self, aug):
        """True when the path of an augment runs through an rpc, action or notification."""
        steps = self._steps(aug.arg, aug)
        mod = self.lib.modules.get(steps[0][0])
        if mod is None:
            return False
        names = [n for _, n in steps]
        for top in mod.stmts:
            for s in top.subs:
                if s.kw in ("rpc", "notification") and s.arg == names[0]:
                    return True

        def walk(st, i):
            if i >= len(names):
                return False
            for c in st.subs:
                if c.arg == names[i]:
                    if c.kw in ("action", "notification", "input", "output"):
                        return True
                    if walk(c, i + 1):
                        return True
                if c.kw == "uses":
                    try:
                        g = self.lib.lookup("grouping", c.arg, c)
                    except YangError:
                        continue
                    if walk(g, i):
                        return True
            return False
        return any(walk(top, 0) for top in mod.stmts)


# --------------------------------------------------------------------------
# Types (RFC 7950 section 9, RFC 7951 section 6)
# --------------------------------------------------------------------------

INT_BOUNDS = {"int8": (-128, 127), "int16": (-32768, 32767), "int32": (-2 ** 31, 2 ** 31 - 1),
              "uint8": (0, 255), "uint16": (0, 65535), "uint32": (0, 2 ** 32 - 1)}
STRING_TYPES = ("string", "enumeration", "bits", "binary", "identityref", "instance-identifier",
                "int64", "uint64", "decimal64")
# typedefs of a date and time in the form of RFC 3339 (the leaf is kept as text and can be
# read with iso8601_ms where a --map binds it)
DATE_AND_TIME = (("ietf-yang-types", "date-and-time"), ("openconfig-yang-types", "date-and-time"))
BUILTIN = set(INT_BOUNDS) | set(STRING_TYPES) | {"boolean", "empty", "union", "leafref"}


class JType:
    """The JSON form of a leaf: kind 'integer', 'string', 'boolean', or None with a reason."""

    def __init__(self, kind, reason=None, enum=None, lo=None, hi=None, fmt=None, kinds=None):
        self.kind, self.reason, self.enum, self.lo, self.hi, self.fmt = kind, reason, enum, lo, hi, fmt
        self.kinds = kinds or ({kind} if kind else set())


def _range(text, lo, hi):
    vals = []
    for part in text.split("|"):
        ends = [e.strip() for e in part.split("..")]
        for e in ends:
            if e == "min":
                vals.append(lo)
            elif e == "max":
                vals.append(hi)
            else:
                try:
                    vals.append(int(e, 0) if not re.fullmatch(r"-?\d+", e) else int(e))
                except ValueError:
                    return lo, hi
    return (min(vals), max(vals)) if vals else (lo, hi)


class Typer:
    def __init__(self, lib, tree):
        self.lib, self.tree = lib, tree
        self.busy = set()

    def leaf(self, node):
        t = node.stmt.find("type")
        if t is None:
            raise YangError("%s: %s has no type" % (node.stmt.where(), node.name))
        return self.resolve(t, node, [])

    def resolve(self, t, node, chain, enum=None, rng=None):
        """JType of the `type` statement `t` used by `node`. `chain` holds the typedef
        names passed (for the date-and-time format)."""
        name = t.arg
        pfx, _, base = name.rpartition(":")
        if rng is None and t.find("range") is not None:
            rng = t.find("range").arg
        if enum is None and t.find_all("enum"):
            enum = [e.arg for e in t.find_all("enum")]
        if not pfx and base in BUILTIN:
            return self.builtin(base, t, node, chain, enum, rng)
        td = self.lib.lookup("typedef", name, t)
        tt = td.find("type")
        if tt is None:
            raise YangError("%s: typedef %s has no type" % (td.where(), td.arg))
        return self.resolve(tt, node, chain + [(td.ctx.module, td.arg)], enum, rng)

    def builtin(self, base, t, node, chain, enum, rng):
        if base in INT_BOUNDS:
            lo, hi = INT_BOUNDS[base]
            if rng:
                lo, hi = _range(rng, lo, hi)
            return JType("integer", lo=lo, hi=hi)
        if base == "boolean":
            return JType("boolean")
        if base == "empty":
            return JType(None, "type empty: its JSON value is [null], an array the json wire does not carry",
                         kinds={"array"})
        if base == "enumeration":
            return JType("string", enum=enum)
        if base == "union":
            members = [self.resolve(m, node, chain) for m in t.find_all("type")]
            if not members:
                raise YangError("%s: a union with no member type" % t.where())
            kinds = set()
            for m in members:
                kinds |= m.kinds
            if None in kinds:
                return JType(None, "union with a leafref member whose target is outside the modules read",
                             kinds={None})
            if len(kinds) == 1 and None not in kinds:
                k = next(iter(kinds))
                if k == "integer":
                    return JType("integer", lo=min(m.lo for m in members), hi=max(m.hi for m in members))
                if k == "string" and all(m.enum for m in members):
                    return JType("string", enum=[v for m in members for v in m.enum])
                return JType(k)
            return JType(None, "union of members with several JSON types (%s)" %
                         "/".join(sorted(str(k) for k in kinds)), kinds=kinds)
        if base == "leafref":
            p = t.find("path")
            if p is None:
                raise YangError("%s: a leafref with no path" % t.where())
            target = self.target(p.arg, node, t)
            if target is None:
                return JType(None, "leafref whose target %s is outside the modules read" % p.arg.strip(),
                             kinds={None})
            if id(target) in self.busy:
                raise YangError("%s: leafref loop at %s" % (t.where(), p.arg))
            self.busy.add(id(target))
            try:
                j = self.leaf(target)
            finally:
                self.busy.discard(id(target))
            return j
        fmt = "date-time" if any(c in DATE_AND_TIME for c in chain) else None
        return JType("string", enum=None, fmt=fmt)

    def target(self, path, node, t):
        """The leaf a leafref path names, or None when it lies outside the trees built."""
        text = re.sub(r"\[[^\]]*\]", "", path).strip()
        if "(" in text:
            return None
        steps = [s.strip() for s in text.split("/")]
        if text.startswith("/"):
            steps = steps[1:]
            cur = None
            for i, step in enumerate(steps):
                pfx, _, name = step.rpartition(":")
                mod = self.lib.imported(t.ctx, pfx, t.where()).name if pfx else node.ns
                if i == 0:
                    if mod not in self.tree.roots and mod in self.lib.modules:
                        self.tree.build_module(mod, augments=False)
                    root = self.tree.roots.get(mod)
                    if root is None:
                        return None
                    cur = _data_child(root, name, mod)
                else:
                    cur = _data_child(cur, name, mod)
                if cur is None:
                    return None
            return cur
        cur = node
        for step in steps:
            if step == "..":
                cur = cur.data_parent()
                if cur is None or cur.kind == "root":
                    return None
                continue
            if step in (".", ""):
                continue
            pfx, _, name = step.rpartition(":")
            mod = self.lib.imported(t.ctx, pfx, t.where()).name if pfx else None
            cur = _data_child(cur, name, mod)
            if cur is None:
                return None
        return cur if cur.kind in ("leaf", "leaf-list") else None


def _data_child(node, name, ns):
    hits = [c for c in node.data_children() if c.name == name]
    if ns is not None:
        exact = [c for c in hits if c.ns == ns]
        hits = exact or hits
    return hits[0] if hits else None


# --------------------------------------------------------------------------
# The JSON Schema of one message
# --------------------------------------------------------------------------

def member(node, parent_ns):
    return node.name if node.ns == parent_ns else "%s:%s" % (node.ns, node.name)


def scalar_schema(j):
    s = collections.OrderedDict([("type", j.kind)])
    if j.kind == "integer":
        s["minimum"], s["maximum"] = j.lo, j.hi
    if j.enum:
        s["enum"] = list(j.enum)
    if j.fmt:
        s["format"] = j.fmt
    return s


def to_schema(node, typer, path, left_out, counts):
    """The JSON Schema of a container or list item `node`; `left_out` collects
    (path, reason) for every node not mapped."""
    props = collections.OrderedDict()
    for c in node.data_children():
        name = member(c, node.ns)
        p = "%s.%s" % (path, name) if path else name
        counts[c.kind] = counts.get(c.kind, 0) + 1
        if c.kind == "container":
            props[name] = to_schema(c, typer, p, left_out, counts)
        elif c.kind == "list":
            props[name] = collections.OrderedDict([("type", "array"),
                                                   ("items", to_schema(c, typer, p + "[]", left_out, counts))])
        elif c.kind in ("leaf", "leaf-list"):
            j = typer.leaf(c)
            if j.kind is None and (j.reason or "").startswith("union of members"):
                # left to jsonschema2pack, which reports it; the wire carries it as residue
                sch = collections.OrderedDict([("type", sorted(k for k in j.kinds if k))])
                left_out.append((p, j.reason))
            elif j.kind is None:
                left_out.append((p, j.reason))
                continue
            else:
                sch = scalar_schema(j)
            props[name] = sch if c.kind == "leaf" else collections.OrderedDict([("type", "array"), ("items", sch)])
        else:
            left_out.append((p, "%s: its members are data" % c.kind))
    return collections.OrderedDict([("type", "object"), ("properties", props)])


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def notes_text(a, lib, top, left_out, counts, shared_notes, dropped=()):
    w = []
    if shared_notes:
        w.append(shared_notes.rstrip("\n"))
        w.append("")
    w.append("## The YANG tree of this pack")
    w.append("")
    w.append("The message is the JSON encoding (RFC 7951) of the top-level %s `%s` of module `%s`: "
             "one object whose only member is `%s:%s`." % (top.kind, top.name, a.module, a.module, top.name))
    if a.augment_module:
        w.append("The augments of %s are applied to it." % ", ".join("`%s`" % m for m in a.augment_module))
    w.append("Other modules were read for their groupings, typedefs and leafref targets only.")
    w.append("")
    w.append("| Schema nodes of the tree | Count |")
    w.append("|---|---|")
    for k in ("container", "list", "leaf", "leaf-list", "anydata", "anyxml"):
        if counts.get(k):
            w.append("| %s | %d |" % (k, counts[k]))
    w.append("")
    if dropped:
        w.append("Augments of these modules that are not applied, because they target a node that a module "
                 "outside the set adds or that lies outside this tree:")
        w.append("")
        for aug, ns in dropped:
            w.append("- `%s`: `%s`" % (ns, re.sub(r"\s+", "", aug.arg)))
        w.append("")
    w.append("### Left out by yang2pack")
    w.append("")
    if not left_out:
        w.append("Nothing.")
    else:
        w.append("Each place below has no line; a scalar there is carried as residue, an array is not. "
                 "Unions also appear in the table of jsonschema2pack above.")
        w.append("")
        reasons = collections.Counter(r for _, r in left_out)
        w.append("| Reason | Places |")
        w.append("|---|---|")
        for r, n in sorted(reasons.items()):
            w.append("| %s | %d |" % (r, n))
        w.append("")
        w.append("| Place | Reason |")
        w.append("|---|---|")
        for p, r in left_out:
            w.append("| `%s` | %s |" % (p, r))
    w.append("")
    return "\n".join(w)


def provenance(a, lib):
    w = []
    given = dict(x.split("=", 1) for x in a.file_licence)
    spdx = sorted({v[1][0] or given.get(v[2]) for v in lib.read.values() if v[1][0] or given.get(v[2])})
    if a.licence_spdx:
        spdx = sorted(set(spdx) | {a.licence_spdx})
    w.append("SPDX licence of the sources: %s. This pack restates them under Apache-2.0." % " AND ".join(spdx))
    w.append("")
    w.append("# Provenance of the %s pack" % a.format)
    w.append("")
    w.append("`tools/gen/yang2pack.py` read the YANG files below and wrote this pack from their "
             "statements (node names, types, value ranges); no description text is used. The files "
             "are not kept in this repository. Read on %s." % a.read_on)
    w.append("")
    w.append("| | |")
    w.append("|---|---|")
    w.append("| Message | the top-level node `%s` of module `%s`, JSON encoding of RFC 7951 |" % (a.top, a.module))
    for r in a.repository:
        w.append("| Repository | %s |" % r)
    if a.download:
        w.append("| Download | `%s` |" % a.download)
    w.append("| Generated by | `%s` (yang2pack.py) |" % a.run_script)
    w.append("")
    w.append("A file is `<directory>/<module>.yang`, or `<directory>/<module>@<revision>.yang` where a "
             "revision is given (the publisher's naming).")
    w.append("")
    w.append("| Directory | Module | Revision | SHA-256 | Licence in the file |")
    w.append("|---|---|---|---|---|")
    for rel, (sha, (sid, _), mod) in lib.read.items():
        if sid:
            lic = sid
        elif mod in given:
            lic = "none stated in the file; %s by the document that holds it (below)" % given[mod]
        elif a.licence_spdx:
            lic = "none stated in the file; %s, the repository's licence file" % a.licence_spdx
        else:
            lic = "none stated in the file"
        d, _, f = _shown(a, rel).rpartition("/")
        m = re.fullmatch(r"(.+?)(?:@(\d{4}-\d{2}-\d{2}))?\.yang", f)
        w.append("| `%s` | `%s` | %s | `%s` | %s |" % (d or ".", m.group(1), m.group(2) or "-", sha, lic))
    w.append("")
    w.append("## Licence")
    w.append("")
    stmts = collections.OrderedDict()
    for rel, (sha, (sid, para), mod) in lib.read.items():
        if para:
            stmts.setdefault(para, []).append(mod)
    if stmts:
        w.append("The modules state their licence in their description; each statement as found:")
        w.append("")
        for para, mods in stmts.items():
            w.append("- %s:" % ", ".join("`%s`" % m for m in sorted(set(mods))))
            w.append("")
            w.append("  > %s" % para)
            w.append("")
    for path in a.licence_file:
        with open(path, "rb") as fh:
            data = fh.read()
        first = [ln.strip() for ln in data.decode("utf-8").splitlines() if ln.strip()][:3]
        w.append("The repository's licence file (sha256 `%s`) opens:" % hashlib.sha256(data).hexdigest())
        w.append("")
        for ln in first:
            w.append("> %s" % ln)
        w.append("")
    for t in a.licence_note:
        w.append(t)
        w.append("")
    w.append("The pack restates structure only. It is not endorsed by the publishers of the modules.")
    w.append("")
    return "\n".join(w)


def _shown(a, rel):
    for pre, rep in (x.split("=", 1) for x in a.path_prefix):
        if rel.startswith(pre):
            return rep + rel[len(pre):]
    return rel


def run(a):
    lib = Library(a.source_root, a.search)
    tree = Tree(lib)
    lib.module(a.module)
    for m in a.augment_module:
        lib.module(m)
    # the trees of the message's module and of every module it augments with, then of
    # the modules they import (for leafref targets only), until no new module appears
    tree.build_module(a.module, augments=True)
    for m in a.augment_module:
        tree.build_module(m, augments=True)
    seen = set()
    while True:
        new = [n for n in list(lib.modules) if n not in tree.roots and n not in seen]
        if not new:
            break
        for n in new:
            seen.add(n)
            tree.build_module(n, augments=False)
    dropped = tree.apply_augments()
    root = tree.roots[a.module]
    top = root.child(a.top)
    if top is None or top.kind not in ("container", "list"):
        raise YangError("module %s has no top-level container or list %s" % (a.module, a.top))
    typer = Typer(lib, tree)
    left_out, counts = [], {}
    name = member(top, None)
    if top.kind == "container":
        inner = to_schema(top, typer, name, left_out, counts)
    else:
        inner = collections.OrderedDict([("type", "array"), ("items", to_schema(top, typer, name + "[]",
                                                                                   left_out, counts))])
    counts[top.kind] = counts.get(top.kind, 0) + 1
    doc = collections.OrderedDict([("$schema", "http://json-schema.org/draft-07/schema#"),
                                   ("type", "object"),
                                   ("properties", collections.OrderedDict([(name, inner)]))])
    kind = re.sub(r"[^a-z0-9]+", "_", a.top.lower()).strip("_")
    shared = ""
    if a.notes_file:
        with open(a.notes_file, encoding="utf-8") as fh:
            shared = fh.read()
    out = genio.Output(a.out, check=a.check)
    with tempfile.TemporaryDirectory(prefix="yang2pack-") as tmp:
        sp = os.path.join(tmp, "%s.json" % a.format)
        with open(sp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=1) + "\n")
        np = os.path.join(tmp, "notes.md")
        with open(np, "w", encoding="utf-8") as fh:
            fh.write(notes_text(a, lib, top, left_out, counts, shared, dropped))
        argv = ["--schema", sp, "--message", "%s=%s" % (kind, sp),
                "--format", a.format, "--module", a.model_module, "--title", a.title,
                "--license", a.license, "--out", a.out, "--model-dir", a.model_dir,
                "--names-file", a.names_file, "--notes-file", np, "--max-depth", str(a.max_depth),
                "--version", a.version]
        for s in a.source:
            argv += ["--source", s]
        for m in a.map:
            argv += ["--map", "%s:%s" % (kind, m)]
        for e in a.evidence:
            argv += ["--evidence", "%s:%s" % (kind, e)]
        if a.limit_reason:
            argv += ["--limit-reason", a.limit_reason]
        if a.check:
            argv.append("--check")
        with open(os.devnull, "w") as null, contextlib.redirect_stdout(null):
            r = jsonschema2pack.main(argv)
    if r:
        print("%s: jsonschema2pack failed for %s" % (NAME, a.format), file=sys.stderr)
        return 1
    out.write("packs/%s/PROVENANCE.md" % a.format, provenance(a, lib))
    st = out.report("%s (PROVENANCE.md)" % NAME)
    if not a.check:
        print("%s: %s, %d leaves left out, %d files read" % (a.format, a.top, len(left_out), len(lib.read)))
    return st


def main(argv=None):
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__.split("\n\n")[0])
    ap.add_argument("--source-root", required=True, help="the directory the --search paths are relative to")
    ap.add_argument("--search", action="append", required=True, help="a directory of YANG files (repeatable)")
    ap.add_argument("--module", required=True, help="the module of the message's top-level node")
    ap.add_argument("--top", required=True, help="the top-level container or list")
    ap.add_argument("--augment-module", action="append", default=[], help="a module whose augments apply")
    ap.add_argument("--format", required=True)
    ap.add_argument("--model-module", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--license", required=True, help="the licence statement for source lines and pack.md")
    ap.add_argument("--licence-spdx", default=None, help="the SPDX id of the repository's licence file, which covers a file that states none")
    ap.add_argument("--licence-file", action="append", default=[], help="a licence file to cite in PROVENANCE.md")
    ap.add_argument("--licence-note", action="append", default=[], help="a paragraph for PROVENANCE.md")
    ap.add_argument("--file-licence", action="append", default=[], metavar="MODULE=SPDX",
                    help="the licence of a module whose file states none, given by its publisher elsewhere "
                         "(say where with --licence-note)")
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--repository", action="append", default=[], help="a Repository row of PROVENANCE.md")
    ap.add_argument("--download", default=None)
    ap.add_argument("--path-prefix", action="append", default=[], metavar="READ=SHOWN",
                    help="show a file path read under READ as SHOWN in PROVENANCE.md")
    ap.add_argument("--run-script", required=True)
    ap.add_argument("--read-on", required=True)
    ap.add_argument("--map", action="append", default=[], metavar="PATH=KEY")
    ap.add_argument("--evidence", action="append", default=[], metavar="PATH=TEXT")
    ap.add_argument("--max-depth", type=int, default=16)
    ap.add_argument("--limit-reason", default=None)
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--names-file", required=True)
    ap.add_argument("--notes-file", default=None)
    genio.add_arguments(ap)
    a = ap.parse_args(argv)
    try:
        return run(a)
    except (YangError, jsonschema2pack.GenError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
