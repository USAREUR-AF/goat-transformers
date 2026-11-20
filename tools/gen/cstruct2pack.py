#!/usr/bin/env python3
"""cstruct2pack: packed C structs in headers, as goat-transformers `bits` packs.

Reads   the C headers a config file names (`tools/gen/cstruct/<family>.json`), and
        tools/gen/sources/<family>-PROVENANCE.md (commit and SHA-256 of every header;
        written with --commit, checked otherwise)
Writes  <out>/model/<module>.def                 raw keys of every message field
        <out>/packs/<family>-<group>/pack.def     one `bits` pack per group of messages
        <out>/packs/<family>-<group>/pack.md
        <out>/packs/<family>-<group>/PROVENANCE.md
        <out>/packs/<family>-<group>/vectors/gen-*.json
        <out>/packs/geojson/vectors/gen-geojson-to-<family>-*.json
        <out>/tools/gen/names/<family>.json      the key name of every field path

A message is a frame header the config describes, followed by the bytes of one C
struct. The config names the message identifiers: a regular expression over the
header text that yields a name, a number and a struct type per message. Each
message is a kind of its pack, selected by `when` lines on the header fields the
config marks; a checksum or trailer is the framer's and is not part of the message.

The reader is strict. It understands, and only these:

  - comments, `#define NAME <integer expression>`, `#undef`, and `#if`, `#ifdef`,
    `#ifndef`, `#elif`, `#else`, `#endif` with `defined(NAME)` and integers, taking
    the branches of the config's define set. A constant defined inside a
    conditional is marked, and a layout that uses one is refused;
  - packing: `#pragma pack(push, n)`, `#pragma pack(pop)` and macros the config maps
    to those;
  - `enum [name] { A [= expr], ... };` and `typedef enum ... name;`, for their
    constant values (an implicit value is the previous one plus 1);
  - `typedef <type> name;` and `typedef <type> name[N]...;`;
  - `typedef struct [attr] [tag] { ... } name;`, `struct tag { ... };` and the same
    with `union`, whose members are `[const] <type> name[N]...;`.

A member that is a pointer, a bit-field, an anonymous or nested definition, or of
a type whose size the reader does not know (an enum type, `int` unless the config
gives its width) makes its struct unsupported, with the reason. A union is
unsupported as a message layout. Everything else at the top level (functions,
prototypes, other macros) is skipped. A message whose layout is unsupported
stops the run, unless the config lists it under `skip` with a reason.

Layout follows the C rules for the pack value in force where the struct is
defined: a scalar aligns to min(its size, pack), a struct to the largest
alignment of its members, its size rounds up to that alignment. Integers and
floats are little-endian unless the config says otherwise.

Python 3 standard library only. Re-runnable: the same inputs give the same bytes.
Vectors are written by a serializer in this file from the layout; after writing,
the script loads every pack through gtcheck and decodes and re-encodes every
vector with a small `bits` codec written from spec/engine-spec.md (0.2, 0.5,
0.6, 0.7). Exit status is non-zero when a check fails.

Usage: cstruct2pack.py --config FILE --src DIR --out DIR [--check] [--commit SHA --ref REF]
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
import genio      # noqa: E402  (the script directory is not on the path under `python3 -I`)
import gtcheck    # noqa: E402

MAX_UNROLL = 64     # an array of more elements is a fixed-count group, not one key per element
ASCII_MAX = 255     # a char array of more bytes is a group of bytes, not `ascii`

SCALARS = {   # C type -> (bytes, kind) where kind is u (unsigned), s (signed), f (float), c (char)
    "uint8_t": (1, "u"), "int8_t": (1, "s"), "uint16_t": (2, "u"), "int16_t": (2, "s"),
    "uint32_t": (4, "u"), "int32_t": (4, "s"), "uint64_t": (8, "u"), "int64_t": (8, "s"),
    "float": (4, "f"), "double": (8, "f"), "char": (1, "c"), "bool": (1, "u"),
}


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# --------------------------------------------------------------------------
# Preprocessing
# --------------------------------------------------------------------------

def strip_comments(text):
    """Text with comments removed; the `//!<` and `/**<` comment of a line is kept
    apart, by line number, for field descriptions."""
    out, docs, i, n, line = [], {}, 0, len(text), 1
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            body = text[i + 2:j]
            if body.startswith("!<") or body.startswith("/<"):
                docs[line] = body[2:].strip()
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                fail("unterminated comment")
            body = text[i + 2:j]
            if body.startswith("*<") or body.startswith("!<"):
                docs[line] = " ".join(body[2:].split())
            nl = body.count("\n")
            out.append("\n" * nl if nl else " ")
            line += nl
            i = j + 2
        else:
            if c == "\n":
                line += 1
            out.append(c)
            i += 1
    return "".join(out), docs


class Const:
    def __init__(self, value, conditional, where):
        self.value, self.conditional, self.where = value, conditional, where


class Expr:
    """Integer expressions of #if and #define: literals, names, defined(), casts of
    known type names, unary - ~ !, binary + - * / % << >> & | ^ < > <= >= == != && ||,
    ?: and parentheses."""
    TOKEN = re.compile(r"\s*(0[xX][0-9a-fA-F]+[uUlL]*|\d+[uUlL]*|[A-Za-z_]\w*|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!<>()?:])")

    def __init__(self, text, lookup, types):
        self.toks, pos = [], 0
        text = text.strip()
        while pos < len(text):
            m = self.TOKEN.match(text, pos)
            if not m:
                raise ValueError("cannot read %r" % text)
            self.toks.append(m.group(1))
            pos = m.end()
        self.i, self.lookup, self.types = 0, lookup, types

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self, want=None):
        t = self.peek()
        if t is None or (want and t != want):
            raise ValueError("expected %s" % (want or "more"))
        self.i += 1
        return t

    def value(self):
        v = self.ternary()
        if self.peek() is not None:
            raise ValueError("trailing %r" % self.peek())
        return v

    def ternary(self):
        c = self.binary(0)
        if self.peek() == "?":
            self.take()
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            return a if c else b
        return c

    LEVELS = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", ">", "<=", ">="], ["<<", ">>"],
              ["+", "-"], ["*", "/", "%"]]

    def binary(self, level):
        if level == len(self.LEVELS):
            return self.unary()
        v = self.binary(level + 1)
        while self.peek() in self.LEVELS[level]:
            op = self.take()
            w = self.binary(level + 1)
            v = {"||": lambda a, b: int(bool(a) or bool(b)), "&&": lambda a, b: int(bool(a) and bool(b)),
                 "|": lambda a, b: a | b, "^": lambda a, b: a ^ b, "&": lambda a, b: a & b,
                 "==": lambda a, b: int(a == b), "!=": lambda a, b: int(a != b), "<": lambda a, b: int(a < b),
                 ">": lambda a, b: int(a > b), "<=": lambda a, b: int(a <= b), ">=": lambda a, b: int(a >= b),
                 "<<": lambda a, b: a << b, ">>": lambda a, b: a >> b, "+": lambda a, b: a + b,
                 "-": lambda a, b: a - b, "*": lambda a, b: a * b,
                 "/": lambda a, b: int(a / b), "%": lambda a, b: a % b}[op](v, w)
        return v

    def unary(self):
        t = self.peek()
        if t in ("-", "~", "!", "+"):
            self.take()
            v = self.unary()
            return {"-": -v, "~": ~v, "!": int(not v), "+": v}[t]
        if t == "(":
            # a cast of a type name: (uint8_t)x or (eDataIDs)3
            if self.i + 2 < len(self.toks) and self.toks[self.i + 2] == ")" and self.toks[self.i + 1] in self.types:
                self.i += 3
                return self.unary()
            self.take("(")
            v = self.ternary()
            self.take(")")
            return v
        return self.atom()

    def atom(self):
        t = self.take()
        if t == "defined":
            paren = self.peek() == "("
            if paren:
                self.take("(")
            name = self.take()
            if paren:
                self.take(")")
            return int(self.lookup(name, defined=True) is not None)
        if re.match(r"\d|0[xX]", t):
            return int(t.rstrip("uUlL"), 0)
        v = self.lookup(t)
        if v is None:
            raise ValueError("unknown name %s" % t)
        return v


class Reader:
    """Everything the headers say that a layout needs."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.defines = set(cfg.get("defines", []))
        self.consts = {}            # name -> Const
        self.types = {}             # typedef name -> ("alias", base, dims) | ("struct", Struct)
        self.structs = {}           # struct or union tag or typedef -> Struct
        self.skipped = []           # top-level constructs not read
        self.pack_macros = cfg.get("pack_macros", {})
        self.int_bits = cfg.get("int_bits")

    # -- constants -------------------------------------------------------
    def lookup(self, name, defined=False):
        if defined:
            return 1 if name in self.defines or name in self.consts else None
        c = self.consts.get(name)
        if c is None:
            return None
        if c.conditional:
            self.used_conditional.add(name)
        return c.value

    def evaluate(self, text):
        names = set(SCALARS) | set(self.types) | {"int", "unsigned"}
        return Expr(text, self.lookup, names).value()

    # -- one file --------------------------------------------------------
    def read(self, path, rel, structs=True):
        with open(path, encoding="utf-8", errors="strict") as fh:
            raw = fh.read()
        text, docs = strip_comments(raw)
        lines = text.split("\n")
        # a line ending in a backslash continues on the next one: join them, and keep
        # the line count with empty lines
        joined, k = [], 0
        while k < len(lines):
            cur, extra = lines[k], 0
            while cur.rstrip().endswith("\\") and k + 1 + extra < len(lines):
                cur = cur.rstrip()[:-1] + " " + lines[k + 1 + extra]
                extra += 1
            joined.append(cur)
            joined.extend([""] * extra)
            k += 1 + extra
        lines = joined
        stack = []                  # one (taking, taken_any, parent_taking) per open #if
        out_lines = []
        # an include guard (`#ifndef G` then `#define G` as the first two directives) is
        # not a condition: what it holds is not conditional
        directives = [(k, l.strip()) for k, l in enumerate(lines) if l.strip().startswith("#")]
        guard_line = None
        if len(directives) >= 2:
            g1 = re.match(r"#\s*ifndef\s+(\w+)\s*$", directives[0][1])
            g2 = re.match(r"#\s*define\s+(\w+)\s*$", directives[1][1])
            if g1 and g2 and g1.group(1) == g2.group(1):
                guard_line = directives[0][0] + 1
        for no, line in enumerate(lines, 1):
            s = line.strip()
            taking = all(e[0] for e in stack)
            m = re.match(r"#\s*(\w+)\s*(.*)$", s)
            if m:
                d, arg = m.group(1), m.group(2).strip()
                if d in ("if", "ifdef", "ifndef"):
                    if not taking:
                        stack.append((False, True, False, False))
                        continue
                    if d == "ifdef":
                        v = arg.split()[0] in self.defines or arg.split()[0] in self.consts
                    elif d == "ifndef":
                        v = not (arg.split()[0] in self.defines or arg.split()[0] in self.consts)
                    else:
                        v = self.cond(arg, rel, no)
                    stack.append((v, v, True, no == guard_line))
                    continue
                if d == "elif":
                    t, any_, parent, _ = stack.pop()
                    v = (not any_) and parent and self.cond(arg, rel, no)
                    stack.append((v, any_ or v, parent, False))
                    continue
                if d == "else":
                    t, any_, parent, _ = stack.pop()
                    stack.append(((not any_) and parent, True, parent, False))
                    continue
                if d == "endif":
                    stack.pop()
                    continue
                if not taking:
                    continue
                if d == "define":
                    self.define(arg, rel, no, any(not e[3] for e in stack))
                elif d == "undef":
                    self.consts.pop(arg.split()[0], None)
                elif d == "pragma":
                    pm = re.match(r"pack\s*\(\s*(push\s*,\s*(\d+)|pop)\s*\)", arg)
                    if pm:
                        out_lines.append((no, "@pack %s" % (pm.group(2) or "pop")))
                out_lines.append((no, ""))
                continue
            if not taking:
                continue
            tok = s.split()[0] if s else ""
            if tok in self.pack_macros:
                op = self.pack_macros[tok]
                out_lines.append((no, "@pack %s" % ("pop" if op == "pop" else op)))
                rest = s[len(tok):]
                out_lines.append((no, rest))
                continue
            out_lines.append((no, line))
        if stack:
            fail("%s: #if without #endif" % rel)
        self.declarations(out_lines, docs, rel)

    def cond(self, arg, rel, no):
        self.used_conditional = set()
        try:
            return bool(self.evaluate(arg))
        except ValueError:
            # a condition the reader cannot evaluate: no branch is taken, and a
            # constant defined in it stays unknown (so a layout that needs it fails)
            self.skipped.append("%s:%d: #if %s" % (rel, no, arg))
            return False

    def define(self, arg, rel, no, conditional):
        m = re.match(r"([A-Za-z_]\w*)(\(?)(.*)$", arg)
        if not m or m.group(2):
            return                          # a function-like macro: not a constant
        name, body = m.group(1), m.group(3).strip()
        if not body:
            self.defines.add(name)          # `#define NAME`: defined, no value
            return
        self.used_conditional = set()
        try:
            v = self.evaluate(body)
        except (ValueError, ZeroDivisionError):
            return                          # not an integer constant
        self.consts[name] = Const(v, conditional or bool(self.used_conditional), "%s:%d" % (rel, no))

    # -- declarations ----------------------------------------------------
    def declarations(self, out_lines, docs, rel):
        """Split the live text into top-level statements and read the type ones."""
        toks = []                           # (line, token)
        pack = [None]
        for no, line in out_lines:
            if line.startswith("@pack "):
                toks.append((no, line))
                continue
            for t in re.findall(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_]\w*|\d[\w.]*|::|->|[{}\[\]();,=*:<>?&|^~!+\-/%.#]', line):
                toks.append((no, t))
        i, n = 0, len(toks)
        while i < n:
            no, t = toks[i]
            if t.startswith("@pack "):
                v = t.split()[1]
                if v == "pop":
                    if len(pack) == 1:
                        fail("%s:%d: pack pop with nothing pushed" % (rel, no))
                    pack.pop()
                else:
                    pack.append(int(v))
                i += 1
                continue
            # one statement. A type definition (typedef, struct, union, enum) or an
            # initializer ends at the `;` at depth 0; anything else whose first `{` comes
            # before a `;` is a function, which ends at its closing `}`.
            j, depth = i, 0
            typedecl = t in ("typedef", "struct", "union", "enum")
            while j < n:
                tj = toks[j][1]
                if tj.startswith("@pack "):
                    break
                if tj == "=" and depth == 0:
                    typedecl = True
                if tj in "{([":
                    depth += 1
                elif tj in "})]":
                    depth -= 1
                    if depth == 0 and tj == "}" and not typedecl:
                        j += 1
                        if j < n and toks[j][1] == ";":
                            j += 1
                        break
                elif tj == ";" and depth == 0:
                    j += 1
                    break
                j += 1
            stmt = toks[i:j]
            i = j
            if not stmt:
                continue
            self.statement(stmt, docs, rel, pack[-1])

    def statement(self, stmt, docs, rel, pack):
        words = [t for _, t in stmt]
        where = "%s:%d" % (rel, stmt[0][0])
        if words[0] == "typedef":
            if len(words) > 1 and words[1] in ("struct", "union"):
                self.aggregate(stmt[1:], docs, rel, pack, typedef=True)
            elif len(words) > 1 and words[1] == "enum":
                self.enum(stmt[1:], where)
            elif "(" not in words:
                self.alias(words, where)
            else:
                self.skipped.append(where + ": typedef of a function type")
        elif words[0] == "enum" and "{" in words:
            self.enum(stmt, where)
        elif words[0] in ("struct", "union") and "{" in words:
            self.aggregate(stmt, docs, rel, pack, typedef=False)
        else:
            self.skipped.append(where + ": " + " ".join(words[:4]))

    def enum(self, stmt, where):
        words = [t for _, t in stmt]
        if "{" not in words:
            return
        a, b = words.index("{"), len(words) - 1 - words[::-1].index("}")
        body = words[a + 1:b]
        value, item = -1, []
        for t in body + [","]:
            if t == ",":
                if item:
                    name = item[0]
                    if len(item) > 2 and item[1] == "=":
                        self.used_conditional = set()
                        try:
                            value = self.evaluate(" ".join(item[2:]))
                        except (ValueError, ZeroDivisionError):
                            value = None
                    else:
                        value = None if value is None else value + 1
                    if value is not None:
                        self.consts[name] = Const(value, False, where)
                item = []
            else:
                item.append(t)
        tail = [t for t in words[b + 1:] if t != ";"]
        if tail:
            self.types[tail[-1]] = ("enum", None, [])

    def alias(self, words, where):
        words = [w for w in words[1:] if w != ";"]
        dims = []
        while words and words[-1] == "]":
            k = len(words) - 1 - words[::-1].index("[")
            dims.insert(0, " ".join(words[k + 1:-1]))
            words = words[:k]
        name, base = words[-1], " ".join(w for w in words[:-1] if w not in ("const",))
        if "*" in base:
            self.types[name] = ("unsupported", "a pointer type", [])
            return
        self.types[name] = ("alias", base, dims)

    def aggregate(self, stmt, docs, rel, pack, typedef):
        words = [t for _, t in stmt]
        kind = words[0]
        a = words.index("{")
        b = len(words) - 1 - words[::-1].index("}")
        tag = [w for w in words[1:a] if re.match(r"[A-Za-z_]\w*$", w) and w not in self.cfg.get("attributes", [])]
        name = [w for w in words[b + 1:] if w not in (";",) and re.match(r"[A-Za-z_]\w*$", w)]
        st = Struct(kind, name[-1] if typedef and name else (tag[-1] if tag else None), pack,
                    "%s:%d" % (rel, stmt[0][0]))
        if pack is None:
            st.pack = 0             # natural alignment, no pack in force
        # members: split body on `;` at depth 0
        body = stmt[a + 1:b]
        member, depth = [], 0
        for no, t in body:
            if t in "{([":
                depth += 1
            elif t in "})]":
                depth -= 1
            if t == ";" and depth == 0:
                if member:
                    st.member(member, docs, self)
                member = []
            else:
                member.append((no, t))
        if member:
            st.unsupported = st.unsupported or "a member without `;`"
        if typedef and name:
            self.structs[name[-1]] = st
            self.types[name[-1]] = ("struct", st, [])
        if tag:
            self.structs[tag[-1]] = st
            if not typedef:
                self.types["struct " + tag[-1]] = ("struct", st, [])


class Member:
    def __init__(self, ctype, name, dims, doc, line):
        self.ctype, self.name, self.dims, self.doc, self.line = ctype, name, dims, doc, line


class Struct:
    def __init__(self, kind, name, pack, where):
        self.kind, self.name, self.pack, self.where = kind, name, pack, where
        self.members = []
        self.unsupported = None

    def member(self, toks, docs, reader):
        words = [t for _, t in toks]
        line = toks[-1][0]
        doc = docs.get(line) or docs.get(toks[0][0]) or ""
        if any(w in ("{", "}") for w in words):
            self.unsupported = self.unsupported or "a nested definition (%s)" % " ".join(words[:3])
            return
        if "*" in words:
            self.unsupported = self.unsupported or "a pointer member (%s)" % " ".join(words)
            return
        if ":" in words:
            self.unsupported = self.unsupported or "a bit-field (%s)" % " ".join(words)
            return
        if "," in words:
            self.unsupported = self.unsupported or "several declarators in one member (%s)" % " ".join(words)
            return
        dims = []
        while words and words[-1] == "]":
            k = len(words) - 1 - words[::-1].index("[")
            dims.insert(0, " ".join(words[k + 1:-1]))
            words = words[:k]
        words = [w for w in words if w not in ("const", "volatile")]
        if len(words) < 2:
            self.unsupported = self.unsupported or "a member the reader cannot split (%s)" % " ".join(words)
            return
        name = words[-1]
        ctype = " ".join(words[:-1])
        self.members.append(Member(ctype, name, dims, doc, line))


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

class Field:
    """A member laid out: offset in bytes, the scalar or struct it holds, counts."""

    def __init__(self, member, offset, elem, counts, elem_size):
        self.member, self.offset, self.elem, self.counts, self.elem_size = member, offset, elem, counts, elem_size


class Layout:
    def __init__(self, struct, fields, size, align):
        self.struct, self.fields, self.size, self.align = struct, fields, size, align


class Unsupported(Exception):
    pass


def resolve(reader, ctype, where, dims=None):
    """(element, extra dims, size, align) of a C type: element is a scalar name or a Layout."""
    dims = list(dims or [])
    seen = 0
    while True:
        seen += 1
        if seen > 20:
            raise Unsupported("%s: typedef loop at %s" % (where, ctype))
        if ctype in SCALARS:
            size = SCALARS[ctype][0]
            return ctype, dims, size, size
        if ctype in ("int", "unsigned int", "unsigned", "signed int"):
            if not reader.int_bits:
                raise Unsupported("%s: `%s` has no fixed width (the config gives none)" % (where, ctype))
            name = ("int%d_t" if ctype in ("int", "signed int") else "uint%d_t") % reader.int_bits
            return name, dims, reader.int_bits // 8, reader.int_bits // 8
        t = reader.types.get(ctype)
        if t is None and ctype.startswith("struct "):
            t = reader.types.get(ctype) or (("struct", reader.structs[ctype[7:]], []) if ctype[7:] in reader.structs else None)
        if t is None:
            raise Unsupported("%s: unknown type `%s`" % (where, ctype))
        if t[0] == "enum":
            raise Unsupported("%s: enum type `%s` has no size the C standard fixes" % (where, ctype))
        if t[0] == "unsupported":
            raise Unsupported("%s: `%s` is %s" % (where, ctype, t[1]))
        if t[0] == "alias":
            # `typedef uint8_t v_t[30]; v_t x[4];` is uint8_t x[4][30]: the member's counts
            # are the outer ones, the typedef's the inner
            dims = dims + list(t[2])
            ctype = t[1]
            continue
        lay = layout(reader, t[1])
        return lay, dims, lay.size, lay.align


def layout(reader, st, cache={}):
    key = id(st)
    if key in cache:
        return cache[key]
    if st.unsupported:
        raise Unsupported("%s %s at %s: %s" % (st.kind, st.name, st.where, st.unsupported))
    if st.kind == "union":
        raise Unsupported("union %s at %s: the bytes mean one member or another, which a fixed layout "
                          "cannot state" % (st.name, st.where))
    fields, offset, align = [], 0, 1
    for m in st.members:
        elem, dims, esize, ealign = resolve(reader, m.ctype, "%s.%s" % (st.name, m.name), m.dims)
        counts = []
        for d in dims:
            reader.used_conditional = set()
            try:
                v = reader.evaluate(d)
            except (ValueError, ZeroDivisionError) as e:
                raise Unsupported("%s.%s: array size `%s`: %s" % (st.name, m.name, d, e))
            if reader.used_conditional:
                raise Unsupported("%s.%s: array size `%s` uses %s, defined under a conditional"
                                  % (st.name, m.name, d, ", ".join(sorted(reader.used_conditional))))
            if v <= 0:
                raise Unsupported("%s.%s: array size %d" % (st.name, m.name, v))
            counts.append(v)
        a = min(ealign, st.pack) if st.pack else ealign
        offset = (offset + a - 1) // a * a
        n = 1
        for c in counts:
            n *= c
        fields.append(Field(m, offset, elem, counts, esize))
        offset += esize * n
        align = max(align, a)
    size = (offset + align - 1) // align * align
    cache[key] = Layout(st, fields, size, align)
    return cache[key]


# --------------------------------------------------------------------------
# Lines of a kind
# --------------------------------------------------------------------------

class Leaf:
    def __init__(self, key, bit, length, transform, keytype, path, ctype, doc):
        self.key, self.bit, self.length, self.transform = key, bit, length, transform
        self.keytype, self.path, self.ctype, self.doc = keytype, path, ctype, doc


class Group:
    def __init__(self, key, bit, item_bits, count, body, path, doc):
        self.key, self.bit, self.item_bits, self.count = key, bit, item_bits, count
        self.body, self.path, self.doc = body, path, doc


def scalar_line(ctype, nbytes):
    kind = SCALARS[ctype][1]
    if kind == "f":
        return ("f32" if nbytes == 4 else "f64"), "float"
    return ("twos" if kind == "s" else "uint"), "int"


class Namer:
    def __init__(self, names):
        self.names = names
        self.taken = {v: k for k, v in names.items()}

    def name(self, pathid, proposal):
        if pathid not in self.names:
            k, i = proposal, 2
            while k in self.taken and self.taken[k] != pathid:
                k = "%s_%d" % (proposal, i)
                i += 1
            self.names[pathid] = k
            self.taken[k] = pathid
        return self.names[pathid]


def snake(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


def leaves(lay, base_bit, path, kpath, top, namer, binds):
    """Lines for a laid-out struct at bit `base_bit`; paths like `lla[0]` or `a.b`."""
    out = []
    for f in lay.fields:
        m = f.member
        p = path + ("." if path else "") + m.name
        k = kpath + [snake(m.name)]
        bit = base_bit + f.offset * 8
        if isinstance(f.elem, Layout):
            n = 1
            for c in f.counts:
                n *= c
            if not f.counts:
                out.extend(leaves(f.elem, bit, p, k, top, namer, binds))
            elif n <= MAX_UNROLL:
                for idx in indices(f.counts):
                    sub = "".join("[%d]" % x for x in idx)
                    out.extend(leaves(f.elem, bit + flat(idx, f.counts) * f.elem_size * 8, p + sub,
                                      k + [str(x) for x in idx], top, namer, binds))
            else:
                if len(f.counts) != 1:
                    raise Unsupported("%s.%s: a multi-dimensional array of %d structs" % (top, p, n))
                key = namer.name("%s:%s[]" % (top, p), "_".join([snake(top)] + k))
                body = item_leaves(f.elem, top, p + "[]", k, namer)
                out.append(Group(key, bit, f.elem_size * 8, n, body, p + "[]", m.doc))
            continue
        ctype, nbytes = f.elem, f.elem_size
        n = 1
        for c in f.counts:
            n *= c
        if SCALARS[ctype][1] == "c" and f.counts:
            if n <= ASCII_MAX and len(f.counts) == 1:
                out.append(leaf(top, p, k, bit, n * 8, "ascii", "string", "char[%d]" % n, m.doc, namer, binds))
                continue
            ctype = "uint8_t"
        if SCALARS[ctype][1] == "c":
            ctype = "uint8_t"
        tr, kt = scalar_line(ctype, nbytes)
        if not f.counts:
            out.append(leaf(top, p, k, bit, nbytes * 8, tr, kt, ctype, m.doc, namer, binds))
        elif n <= MAX_UNROLL:
            for idx in indices(f.counts):
                sub = "".join("[%d]" % x for x in idx)
                out.append(leaf(top, p + sub, k + [str(x) for x in idx], bit + flat(idx, f.counts) * nbytes * 8,
                                nbytes * 8, tr, kt, ctype, m.doc, namer, binds))
        elif len(f.counts) == 1:
            key = namer.name("%s:%s[]" % (top, p), "_".join([snake(top)] + k))
            ikey = namer.name("%s:%s[]." % (top, p), "_".join([snake(top)] + k + ["value"]))
            out.append(Group(key, bit, nbytes * 8, n,
                             [Leaf(ikey, 0, nbytes * 8, tr, kt, p + "[]", ctype, m.doc)], p + "[]", m.doc))
        else:
            # a long array of arrays: a group over the outer count, each item the inner array
            inner = 1
            for c in f.counts[1:]:
                inner *= c
            key = namer.name("%s:%s[]" % (top, p), "_".join([snake(top)] + k))
            body = []
            if SCALARS[f.elem][1] == "c" and len(f.counts) == 2 and inner <= ASCII_MAX:
                body.append(Leaf(namer.name("%s:%s[]." % (top, p), "_".join([snake(top)] + k + ["text"])),
                                 0, inner * 8, "ascii", "string", p + "[]", "char[%d]" % inner, m.doc))
            elif inner <= MAX_UNROLL:
                for idx in indices(f.counts[1:]):
                    sub = "".join("[%d]" % x for x in idx)
                    body.append(Leaf(namer.name("%s:%s[]%s" % (top, p, sub), "_".join([snake(top)] + k + [str(x) for x in idx])),
                                     flat(idx, f.counts[1:]) * nbytes * 8, nbytes * 8, tr, kt, p + "[]" + sub, ctype, m.doc))
            else:
                raise Unsupported("%s.%s: an array of %d arrays of %d elements" % (top, p, f.counts[0], inner))
            out.append(Group(key, bit, inner * nbytes * 8, f.counts[0], body, p + "[]", m.doc))
    return out


def item_leaves(lay, top, path, kpath, namer):
    """The lines of one item of a group of structs, bits counted from the item."""
    out = []
    for x in leaves(lay, 0, path, kpath, top, namer, {}):
        if isinstance(x, Group):
            raise Unsupported("%s.%s: a long array inside a long array of structs" % (top, path))
        out.append(x)
    return out


def leaf(top, path, kpath, bit, length, tr, kt, ctype, doc, namer, binds):
    b = binds.get(path)
    if b:
        return Leaf(b["key"], bit, length, b.get("transform", tr), b["type"], path, ctype, doc)
    return Leaf(namer.name("%s:%s" % (top, path), "_".join([snake(top)] + kpath)), bit, length, tr, kt,
                path, ctype, doc)


def indices(counts):
    if not counts:
        yield ()
        return
    for i in range(counts[0]):
        for rest in indices(counts[1:]):
            yield (i,) + rest


def flat(idx, counts):
    v = 0
    for i, c in zip(idx, counts):
        v = v * c + i
    return v


def iter_leaves(items):
    for x in items:
        if isinstance(x, Group):
            for y in x.body:
                yield y
        else:
            yield x


# --------------------------------------------------------------------------
# Serializer for vectors: works from the layout, not from pack.def
# --------------------------------------------------------------------------

class Sampler:
    def __init__(self):
        self.n = 0

    def value(self, ctype):
        self.n += 1
        n = self.n
        size, kind = SCALARS[ctype]
        if kind == "f":
            return (n % 61 - 30.5) * 0.25 if size == 4 else float("%s%d.%03d" % ("-" if n % 3 == 0 else "", n, n * 7 % 1000))
        if kind == "u" or kind == "c":
            return (n * 2654435761 + 12345) % (1 << (size * 8)) if size < 8 else n * 1000003 + 1700000000
        span = 1 << (size * 8)
        return (n * 40503 + 7) % span - span // 2 if size < 8 else -(n * 1000003)


PACKFMT = {(1, "u"): "B", (1, "s"): "b", (2, "u"): "H", (2, "s"): "h", (4, "u"): "I", (4, "s"): "i",
           (8, "u"): "Q", (8, "s"): "q", (4, "f"): "f", (8, "f"): "d", (1, "c"): "B"}


def serialize(lay, buf, base, sampler, values, path, override=None):
    """Sample values for every member of `lay` at byte `base`; text for char arrays."""
    for f in lay.fields:
        m = f.member
        p = path + ("." if path else "") + m.name
        at = base + f.offset
        if isinstance(f.elem, Layout):
            for idx in indices(f.counts):
                sub = "".join("[%d]" % x for x in idx)
                serialize(f.elem, buf, at + flat(idx, f.counts) * f.elem_size, sampler, values, p + sub, override)
            continue
        size, kind = SCALARS[f.elem]
        n = 1
        for c in f.counts:
            n *= c
        if kind == "c" and len(f.counts) == 1 and n <= ASCII_MAX:
            sampler.n += 1
            t = ("t%d" % sampler.n)[:n].encode("ascii")
            buf[at:at + n] = t + b"\0" * (n - len(t))
            values[p] = t.decode("ascii")
            continue
        for idx in indices(f.counts):
            sub = "".join("[%d]" % x for x in idx)
            q = p + sub
            v = override[q] if override and q in override else sampler.value(f.elem)
            if kind == "c":
                v &= 0x7f
            o = at + flat(idx, f.counts) * size
            buf[o:o + size] = struct.pack("<" + PACKFMT[(size, kind)], v)
            values[q] = v


# --------------------------------------------------------------------------
# Independent check: a fixed-layout `bits` codec with kinds (engine-spec 0.2,
# 0.5 kinds, lsb order, f32, f64, ascii, sscale; 0.6 const and default; 0.7
# groups with a fixed count). It reads pack.def text.
# --------------------------------------------------------------------------

class Fail(Exception):
    def __init__(self, kind, detail=""):
        Exception.__init__(self, "%s: %s" % (kind, detail))
        self.kind = kind


def loc(t):
    w, p, n = (int(x) for x in t.split(":"))
    return w * 8 + p, n


def read_pack(text):
    pack = {"common": [], "kinds": collections.OrderedDict(), "defaults": {}}
    cur, stack = pack["common"], []
    kind = None
    for line in text.split("\n"):
        t = gtcheck.tokenize(line)
        if not t:
            continue
        d = t[0]
        if d == "kind":
            kind = {"lines": [], "when": [], "const": [], "requires": []}
            pack["kinds"][t[1]] = kind
            cur = kind["lines"]
        elif d == "when":
            b, n = loc(t[1])
            (kind["when"] if kind else pack.setdefault("when", [])).append((b, n, int(t[2])))
        elif d == "const":
            b, n = loc(t[1])
            (kind["const"] if kind else pack.setdefault("const", [])).append((b, n, int(t[2])))
        elif d == "default":
            pack["defaults"][t[1]] = t[2]
        elif d == "requires":
            kind["requires"] = t[1:]
        elif d == "field":
            b, n = loc(t[2])
            cur.append(("field", t[1], b, n, t[3]))
        elif d == "group":
            b = int(t[2].split(":")[0]) * 8 + int(t[2].split(":")[1])
            body = []
            cur.append(("group", t[1], b, int(t[t.index("item") + 1]), int(t[t.index("count") + 1]), body))
            stack.append(cur)
            cur = body
        elif d == "end":
            cur = stack.pop()
    return pack


def extent(lines, base=0):
    end = 0
    for ln in lines:
        if ln[0] == "field":
            end = max(end, base + ln[2] + ln[3])
        else:
            end = max(end, base + ln[2] + ln[3] * ln[4])
    return end


def decode_value(raw, length, tr):
    if tr == "uint":
        return raw
    if tr == "twos":
        return raw - (1 << length) if raw >> (length - 1) else raw
    if tr in ("f32", "f64"):
        v = struct.unpack("<f" if tr == "f32" else "<d", raw.to_bytes(length // 8, "little"))[0]
        if math.isnan(v) or math.isinf(v):
            raise Fail("transform-decode", "not finite")
        return v
    if tr == "ascii":
        b = raw.to_bytes(length // 8, "little").rstrip(b"\0")
        if any(c < 0x20 or c > 0x7e for c in b):
            raise Fail("transform-decode", "ascii")
        return b.decode("ascii")
    fail("transform %s not in this codec" % tr)


def encode_value(v, length, tr):
    if tr in ("uint", "twos"):
        return int(v) & ((1 << length) - 1)
    if tr == "f32":
        return int.from_bytes(struct.pack("<f", v), "little")
    if tr == "f64":
        return int.from_bytes(struct.pack("<d", v), "little")
    if tr == "ascii":
        b = v.encode("ascii")
        if len(b) > length // 8:
            raise Fail("transform-encode", "ascii too long")
        return int.from_bytes(b + b"\0" * (length // 8 - len(b)), "little")
    fail("transform %s not in this codec" % tr)


def get(whole, b, n):
    return (whole >> b) & ((1 << n) - 1)


def decode_lines(lines, whole, base):
    ent = {}
    for ln in lines:
        if ln[0] == "field":
            ent[ln[1]] = decode_value(get(whole, base + ln[2], ln[3]), ln[3], ln[4])
        else:
            ent[ln[1]] = [decode_lines(ln[5], whole, base + ln[2] + i * ln[3]) for i in range(ln[4])]
    return ent


def msg_bits(pack, kname):
    k = pack["kinds"][kname]
    ends = [extent(pack["common"]), extent(k["lines"])]
    ends += [b + n for b, n, _ in pack.get("when", []) + pack.get("const", []) + k["when"] + k["const"]]
    return max(ends)


def decode(pack, data):
    whole = int.from_bytes(data, "little")
    nbits = len(data) * 8
    for b, n, v in pack.get("when", []):
        if b + n > nbits or get(whole, b, n) != v:
            raise Fail("no-kind", "common when")
    for name, k in pack["kinds"].items():
        if all(b + n <= nbits and get(whole, b, n) == v for b, n, v in k["when"]):
            if len(data) * 8 < msg_bits(pack, name):
                raise Fail("malformed-wire", "short input")
            ent = decode_lines(pack["common"], whole, 0)
            ent.update(decode_lines(k["lines"], whole, 0))
            return name, ent
    raise Fail("no-kind", "no kind")


def encode_lines(lines, ent, base, acc, defaults):
    for ln in lines:
        if ln[0] == "field":
            v = ent.get(ln[1])
            if v is None and ln[1] in defaults:
                v = int(defaults[ln[1]]) if ln[4] in ("uint", "twos") else float(defaults[ln[1]])
            if v is not None:
                acc |= encode_value(v, ln[3], ln[4]) << (base + ln[2])
        else:
            items = ent.get(ln[1])
            if items is None:
                raise Fail("transform-encode", "absent list under a fixed count")
            if len(items) != ln[4]:
                raise Fail("transform-encode", "count")
            for i, it in enumerate(items):
                acc = encode_lines(ln[5], it, base + ln[2] + i * ln[3], acc, defaults)
    return acc


def encode(pack, kname, ent):
    if kname is None:
        for name, k in pack["kinds"].items():
            if all(r in ent for r in k["requires"]):
                kname = name
                break
        else:
            raise Fail("no-kind", "no kind qualifies")
    k = pack["kinds"][kname]
    acc = encode_lines(pack["common"], ent, 0, 0, pack["defaults"])
    acc = encode_lines(k["lines"], ent, 0, acc, pack["defaults"])
    for b, n, v in pack.get("const", []) + k["const"] + pack.get("when", []) + k["when"]:
        acc = (acc & ~(((1 << n) - 1) << b)) | (v << b)
    return acc.to_bytes((msg_bits(pack, kname) + 7) // 8, "little")


def fmt_float(x):
    if x == 0:
        return "0"
    s = format(Decimal(repr(float(x))), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def geojson_feature(ent):
    if "lat" in ent and "lon" in ent:
        c = [ent["lon"], ent["lat"]] + ([ent["hae"]] if "hae" in ent else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(fmt_float(x) for x in c)
    else:
        geom = "null"
    return '{"type":"Feature","geometry":%s,"properties":{}}' % geom


def check_vector(vec, packs, where):
    src, dst = vec["from"], vec["to"]
    try:
        if src == "geojson":
            c = (json.loads(vec["input"]).get("geometry") or {}).get("coordinates") or []
            ent = {}
            if len(c) >= 2:
                ent = {"lon": float(c[0]), "lat": float(c[1])}
            if len(c) >= 3:
                ent["hae"] = float(c[2])
            out = encode(packs[dst], None, ent).hex()
            kname = None
        else:
            kname, ent = decode(packs[src], bytes.fromhex(vec["input"]))
            if dst == "geojson":
                out = geojson_feature({k: v for k, v in ent.items() if k in ("lat", "lon", "hae")})
            else:
                out = encode(packs[dst], kname, ent).hex()
        for k, want in vec.get("model", {}).items():
            if k == "@kind":
                if kname != want:
                    fail("%s: @kind %r, want %r" % (where, kname, want))
                continue
            got = ent.get(k)
            ok = abs(got - float(want)) <= 1e-9 if isinstance(got, float) else str(got) == want
            if not ok:
                fail("%s: model %s = %r, want %r" % (where, k, got, want))
    except Fail as e:
        if vec.get("expect_error") == e.kind:
            return
        fail("%s: %s" % (where, e))
    if "expect_error" in vec:
        fail("%s: converted, want error %s" % (where, vec["expect_error"]))
    if out != vec["expect"]:
        fail("%s:\n got    %s\n expect %s" % (where, out, vec["expect"]))


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------

def qual(module, key):
    return key if key in ("lat", "lon", "hae") else "%s.%s" % (module, key)


def emit_lines(module, items, indent=""):
    out = []
    for x in items:
        if isinstance(x, Group):
            out.append("%sgroup  %s  0:%d  item %d  count %d" % (indent, qual(module, x.key), x.bit, x.item_bits, x.count))
            out.extend(emit_lines(module, x.body, indent + "  "))
            out.append("%send" % indent)
        else:
            out.append("%sfield  %s  0:%d:%d  %s" % (indent, qual(module, x.key), x.bit, x.length, x.transform))
    return out


def frame_lines(cfg, module, kind_values):
    """The common lines of the frame header, and per kind its when and const lines."""
    common, perkind, bit = [], [], 0
    for f in cfg["frame"]["fields"]:
        n = f["bits"]
        if "when" in f and isinstance(f["when"], int):
            common.append("when   0:%d:%d  %d" % (bit, n, f["when"]))
        elif f.get("role") == "id":
            perkind.append(("when", bit, n, "id"))
        elif f.get("role") == "size":
            perkind.append(("when", bit, n, "size"))
        elif "key" in f:
            common.append("field  %s.%s  0:%d:%d  uint" % (module, f["key"], bit, n))
            if "default" in f:
                common.append("default  %s.%s  %d" % (module, f["key"], f["default"]))
        bit += n
    return common, perkind, bit


def build(args, out):
    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    fam, module = cfg["family"], cfg["module"]
    KIND_PREFIX[0] = cfg["messages"].get("strip_prefix", "")
    prov_rel = "tools/gen/sources/%s-PROVENANCE.md" % fam
    names_rel = "tools/gen/names/%s.json" % fam
    files = cfg["constant_headers"] + cfg["headers"] + cfg.get("license_files", [])
    if args.commit:
        out.write(prov_rel, emit_sources_provenance(cfg, args.commit, args.ref, files, args.src, args.date_read))
    text = out.read(prov_rel)
    commit = re.search(r"^\| Commit \| `([0-9a-f]{40})` \|$", text, re.M).group(1)
    ref = re.search(r"^\| Ref \| `([^`]+)` \|$", text, re.M).group(1)
    shas = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    for rel in files:
        if shas.get(rel) != sha256_file(os.path.join(args.src, *rel.split("/"))):
            fail("%s: SHA-256 is not the one in %s" % (rel, prov_rel))
    reader = Reader(cfg)
    reader.used_conditional = set()
    for rel in cfg["constant_headers"]:
        reader.read(os.path.join(args.src, *rel.split("/")), rel, structs=True)
    for rel in cfg["headers"]:
        reader.read(os.path.join(args.src, *rel.split("/")), rel, structs=True)
    # messages
    with open(os.path.join(args.src, *cfg["messages"]["file"].split("/")), encoding="utf-8") as fh:
        mtext = fh.read()
    msgs = []
    for m in re.finditer(cfg["messages"]["regex"], mtext, re.M):
        msgs.append({"name": m.group("name"), "id": int(m.group("id"), 0), "type": m.group("type")})
    if not msgs:
        fail("the message regex matched nothing")
    groups = cfg["groups"]
    skip = cfg.get("skip", {})
    names = json.loads(out.read(names_rel)) if out.exists(names_rel) else {}
    namer = Namer(names)
    binds = cfg.get("bind", {})
    plan = collections.OrderedDict((g["name"], []) for g in groups)
    skipped = []
    for msg in msgs:
        g = next((g["name"] for g in groups if re.search(g["match"], msg["name"])), None)
        if g is None:
            fail("message %s matches no group" % msg["name"])
        if msg["name"] in skip:
            skipped.append((g, msg, skip[msg["name"]]))
            continue
        try:
            elem, dims, _, _ = resolve(reader, msg["type"], msg["name"])
            if not isinstance(elem, Layout) or dims:
                raise Unsupported("payload type `%s` is not a struct" % msg["type"])
            lay = elem
            items = leaves(lay, cfg["frame"]["header_bits"], "", [], msg["type"], namer,
                           {k.split(":", 1)[1]: v for k, v in binds.items() if k.split(":", 1)[0] == msg["type"]})
        except Unsupported as e:
            fail("%s (%s): %s; list it under `skip` with a reason or extend the reader" % (msg["name"], msg["type"], e))
        plan[g].append((msg, lay, items))
    for k in skip:
        if not any(m["name"] == k for m in msgs):
            fail("skip lists %s, which is not a message" % k)
    # module
    decls, seen = [], set()
    hdr_keys = [(f["key"], "%s frame header: %s (%d bits)" % (fam, f["name"], f["bits"])) for f in cfg["frame"]["fields"] if "key" in f]
    for k, d in hdr_keys:
        decls.append(("key", k, "int", d))
        seen.add(k)
    for g, entries in plan.items():
        for msg, lay, items in entries:
            for x in items:
                for y in [x] + (x.body if isinstance(x, Group) else []):
                    if y.key in ("lat", "lon", "hae") or y.key in seen:
                        continue
                    seen.add(y.key)
                    if isinstance(y, Group):
                        decls.append(("list", y.key, None, "%s.%s" % (msg["type"], y.path)))
                    else:
                        decls.append(("key", y.key, y.keytype, "%s.%s (%s)" % (msg["type"], y.path, y.ctype)))
    out.write("model/%s.def" % module, emit_module(cfg, decls, commit, ref))
    out.write(names_rel, json.dumps(collections.OrderedDict(sorted(namer.names.items())), indent=1) + "\n")
    # packs
    packs_text, vectors, wanted = {}, [], set()
    common, perkind, hbits = frame_lines(cfg, module, None)
    if hbits != cfg["frame"]["header_bits"]:
        fail("frame fields add up to %d bits, header_bits says %d" % (hbits, cfg["frame"]["header_bits"]))
    for g, entries in plan.items():
        fmt = "%s-%s" % (fam, g)
        if not entries:
            fail("group %s holds no message that can be written" % g)
        wanted.add(fmt)
        rel = "packs/" + fmt
        text = emit_pack(cfg, fmt, module, g, entries, common, perkind, commit, ref)
        out.write(rel + "/pack.def", text)
        packs_text[fmt] = text
        out.write(rel + "/PROVENANCE.md", emit_provenance(cfg, commit, ref, files, shas, args.date_read, args.src))
        vs = []
        for msg, lay, items in entries:
            payload, values = sample_payload(lay)
            frame = frame_bytes(cfg, msg, lay.size) + payload
            model = collections.OrderedDict([("@kind", kind_name(msg))])
            for x in iter_leaves(items):
                if x.path in values and len(model) < 5:
                    v = values[x.path]
                    model[qual(module, x.key)] = fmt_float(v) if x.transform.startswith("f") else str(v)
            vs.append(("gen-rt-%s.json" % kind_name(msg).replace("_", "-"), vec(
                "rt-" + kind_name(msg), fmt, fmt, frame.hex(), frame.hex(), model,
                source="tools/gen/cstruct2pack.py: the %s frame header, then %s with values chosen "
                       "by the generator, packed by its serializer at the offsets of the layout" % (fam, msg["type"]))))
            bound = {x.key: x for x in iter_leaves(items) if x.key in ("lat", "lon", "hae")}
            if "lat" in bound and "lon" in bound:
                point = {"lat": 47.3977419, "lon": 8.5455938, "hae": 488.25}
                over = {bound[k].path: point[k] for k in bound}
                payload2, _ = sample_payload(lay, over)
                frame2 = frame_bytes(cfg, msg, lay.size) + payload2
                ent = {k: point[k] for k in bound}
                vs.append(("gen-x-%s-to-geojson.json" % kind_name(msg).replace("_", "-"), vec(
                    "x-%s-to-geojson" % kind_name(msg), fmt, "geojson", frame2.hex(), geojson_feature(ent),
                    collections.OrderedDict((k, fmt_float(v)) for k, v in ent.items()),
                    source="the bound fields (pack.md) are WGS 84 degrees and metres over the ellipsoid; "
                           "geojson writes [lon, lat, alt] (RFC 7946, engine-spec 0.1.1 rulings 3 to 5)")))
                if msg["name"] in cfg.get("from_geojson", []):
                    payload3 = bytearray(lay.size)
                    point3 = {"lat": 47.25, "lon": 8.5, "hae": 410.5}
                    for k, x in bound.items():
                        o = (x.bit - cfg["frame"]["header_bits"]) // 8
                        payload3[o:o + x.length // 8] = struct.pack("<d" if x.length == 64 else "<f", point3[k])
                    hdr = frame_bytes(cfg, msg, lay.size, defaults=True)
                    gv = vec("gen-geojson-to-%s-%s" % (fmt, kind_name(msg)), "geojson", fmt,
                             '{"type":"Feature","geometry":{"type":"Point","coordinates":[8.5,47.25,410.5]},'
                             '"properties":{"callsign":"UAV1"},"id":"u-1"}', (hdr + bytes(payload3)).hex(),
                             {"lat": "47.25", "lon": "8.5", "hae": "410.5"},
                             source="tools/gen/cstruct2pack.py: the kind is the first whose requires hold "
                                    "(lat lon); the frame header holds its when values and the header "
                                    "defaults; every other payload byte is zero")
                    path = "packs/geojson/vectors/gen-geojson-to-%s-%s.json" % (fmt, kind_name(msg).replace("_", "-"))
                    out.write(path, dump_json(gv))
                    vectors.append(path)
        first_msg, first_lay, _ = entries[0]
        frame = frame_bytes(cfg, first_msg, first_lay.size) + sample_payload(first_lay)[0]
        vs.append(("gen-err-short.json", vec("err-short", fmt, fmt, frame[:-1].hex(), error="malformed-wire",
                                             source="one byte short of the %d-byte message of %s (vector-format, "
                                                    "malformed input)" % (len(frame), kind_name(first_msg)))))
        unknown = 0
        ids = {m["id"] for m, _, _ in entries}
        while unknown in ids:
            unknown += 1
        bad = bytearray(frame)
        bad[cfg["frame"]["id_byte"]] = unknown
        vs.append(("gen-err-other-id.json", vec("err-other-id", fmt, fmt, bytes(bad).hex(), error="no-kind",
                                                source="message id %d is not a kind of this pack" % unknown)))
        for name in out.listdir(rel + "/vectors"):
            if name.startswith("gen-") and name not in {n for n, _ in vs}:
                out.remove(rel + "/vectors/" + name)
        for name, v in vs:
            out.write(rel + "/vectors/" + name, dump_json(v))
            vectors.append(rel + "/vectors/" + name)
        out.write(rel + "/pack.md", emit_pack_md(cfg, fmt, g, entries, [s for s in skipped if s[0] == g],
                                                 module, len(vs), reader))
    if os.path.isdir(out.path("packs")):
        for d in sorted(os.listdir(out.path("packs"))):
            if d.startswith(fam + "-") and d not in wanted:
                for sub in ("pack.def", "pack.md", "PROVENANCE.md"):
                    out.remove("packs/%s/%s" % (d, sub))
                for name in out.listdir("packs/%s/vectors" % d):
                    out.remove("packs/%s/vectors/%s" % (d, name))
    # check
    model = gtcheck.Model()
    with open(args.core_def, encoding="utf-8") as fh:
        model.add(fh.read(), "model/core.def")
    model.add(out.read("model/%s.def" % module), "model/%s.def" % module)
    codecs = {}
    for fmt, text in packs_text.items():
        try:
            gtcheck.load_pack(out.read("packs/%s/pack.def" % fmt), model, label="packs/%s/pack.def" % fmt)
        except gtcheck.CheckError as e:
            fail(str(e))
        codecs[fmt] = read_pack(out.read("packs/%s/pack.def" % fmt))
    for path in vectors:
        check_vector(json.loads(out.read(path)), codecs, path)
    return sum(len(e) for e in plan.values()), len(plan), len(skipped), len(decls), len(vectors), skipped


KIND_PREFIX = [""]      # the prefix of message names that kind names leave out (config messages.strip_prefix)


def kind_name(msg):
    n = msg["name"]
    if KIND_PREFIX[0] and n.startswith(KIND_PREFIX[0]):
        n = n[len(KIND_PREFIX[0]):]
    return n.lower()


def sample_payload(lay, override=None):
    buf = bytearray(lay.size)
    values = {}
    serialize(lay, buf, 0, Sampler(), values, "", override)
    return bytes(buf), values


def frame_bytes(cfg, msg, size, defaults=True):
    acc, bit = 0, 0
    for f in cfg["frame"]["fields"]:
        n = f["bits"]
        if isinstance(f.get("when"), int):
            v = f["when"]
        elif f.get("role") == "id":
            v = msg["id"]
        elif f.get("role") == "size":
            v = size
        else:
            v = f.get("default", 0)
        acc |= v << bit
        bit += n
    return acc.to_bytes(bit // 8, "little")


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


def dump_json(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def source_lines(cfg, commit, ref):
    return ['"%s, %s at %s, commit %s; %s"' % (cfg["title"], cfg["repository"], ref, commit, cfg["license_line"])] + \
        ['"%s"' % s for s in cfg.get("extra_sources", [])]


def emit_module(cfg, decls, commit, ref):
    a = ["# The %s module: raw keys of the %s-<group> formats, one per field of a" % (cfg["module"], cfg["family"]),
         "# message struct (nested structs flattened, short arrays one key per element).",
         "# Generated by tools/gen/cstruct2pack.py; edit the generator or its config, not this file.",
         "module        %s" % cfg["module"], "version       %s" % cfg["version"], "distribution  public"]
    a += ["source        %s" % s for s in source_lines(cfg, commit, ref)[:1]]
    w = max(len(d[1]) for d in decls)
    for kind_, name, typ, desc in decls:
        if kind_ == "list":
            a.append('list %-*s          "%s"' % (w, name, desc))
        else:
            a.append('key  %-*s  %-6s  -  "%s"' % (w, name, typ, desc))
    return "\n".join(a) + "\n"


def emit_pack(cfg, fmt, module, g, entries, common, perkind, commit, ref):
    a = ["# %s, group %s: the %s, then one message struct." % (cfg["title_short"], g, cfg["frame"]["name"]),
         "# Generated by tools/gen/cstruct2pack.py from tools/gen/cstruct/%s.json; do not edit by hand." % cfg["family"],
         "format        %s" % fmt, "version       %s" % cfg["version"], "distribution  public"]
    a += ["source        %s" % s for s in source_lines(cfg, commit, ref)]
    a += ["uses          %s" % module, "wire          bits", "bit_order     lsb", "word_bytes    1"]
    a += common
    for msg, lay, items in entries:
        a.append("")
        a.append("kind      %s" % kind_name(msg))
        for what, bit, n, role in perkind:
            a.append("when      0:%d:%d  %d" % (bit, n, msg["id"] if role == "id" else lay.size))
        bound = [x.key for x in iter_leaves(items) if x.key in ("lat", "lon")]
        first = next(iter_leaves(items), None)
        req = ["lat", "lon"] if len(bound) == 2 else ([qual(module, first.key)] if first else [])
        if req:
            a.append("requires  %s" % " ".join(req))
        a += emit_lines(module, items)
    return "\n".join(a) + "\n"


def emit_pack_md(cfg, fmt, g, entries, skipped, module, n_vec, reader):
    fr = cfg["frame"]
    a = ["# %s" % fmt, "",
         "%s, group `%s`. Generated by `tools/gen/cstruct2pack.py` from" % (cfg["title_short"], g),
         "`tools/gen/cstruct/%s.json` (run by `tools/gen/%s-run.sh`); do not edit by hand." % (cfg["family"], cfg["family"]), "",
         "## Message convention", ""]
    a += fr["convention"]
    a += ["", "| Header field | Bits | Line |", "|---|---|---|"]
    bit = 0
    for f in fr["fields"]:
        if isinstance(f.get("when"), int):
            what = "`when` %d (common)" % f["when"]
        elif f.get("role") == "id":
            what = "`when` per kind: the message id"
        elif f.get("role") == "size":
            what = "`when` per kind: the size of the message struct"
        else:
            what = "raw key `%s.%s`%s" % (module, f["key"], ", default %d" % f["default"] if "default" in f else "")
        a.append("| `%s` | %d-%d | %s |" % (f["name"], bit, bit + f["bits"] - 1, what))
        bit += f["bits"]
    a += ["", "## Kinds", "", "| Kind | Id | Struct | Bytes | Lines |", "|---|---|---|---|---|"]
    for msg, lay, items in entries:
        a.append("| `%s` | %d | `%s` | %d | %d |" % (kind_name(msg), msg["id"], msg["type"], lay.size, len(list(iter_leaves(items)))))
    a += ["", "The payload is the struct as the compiler lays it out under `#pragma pack(1)`: the",
          "members one after another with no padding, %s. A nested struct is" % cfg["byte_order_statement"],
          "flattened (`a.b`); an array of up to %d elements is one key per element (`_0`, `_1`," % MAX_UNROLL,
          "...); a longer one is a `group` with a fixed count. A `char` array of up to %d bytes" % ASCII_MAX,
          "is `ascii` text.", "", "## Shared-model keys", ""]
    bound = []
    for msg, lay, items in entries:
        for x in iter_leaves(items):
            if x.key in ("lat", "lon", "hae"):
                bound.append((msg, x))
    if bound:
        a += ["| Kind | Field | Key | Evidence in the header |", "|---|---|---|---|"]
        for msg, x in bound:
            ev = cfg["bind"]["%s:%s" % (msg["type"], x.path)]["evidence"]
            a.append("| `%s` | `%s` | `%s` | %s |" % (kind_name(msg), x.path, x.key, ev))
        a += [""] + cfg.get("bind_note", [])
    else:
        a += ["None. No struct of this group states a WGS 84 position in degrees. Every field is a",
              "raw key of module `%s`." % module]
    a += ["", "## Not mapped, and why", "", "| What | Why |", "|---|---|"]
    for row in cfg.get("not_mapped", []):
        a.append("| %s | %s |" % (row[0], row[1]))
    for gname, msg, why in skipped:
        a.append("| `%s` (id %d, `%s`) | %s |" % (msg["name"], msg["id"], msg["type"], why))
    a += ["", "## Vectors", "",
          "`vectors/gen-rt-<kind>.json`: a round trip per kind with every field set, values chosen by",
          "the generator and packed by its own serializer from the layout. `gen-x-*` convert to",
          "geojson, `gen-err-*` are a short message and an id of no kind. %d vector files." % n_vec,
          "", "## Sources", "", "See `PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def emit_provenance(cfg, commit, ref, files, shas, date_read, src):
    a = ["# Provenance", "",
         "Generated by `tools/gen/cstruct2pack.py`. No source file is copied into this repository. The",
         "generator reads struct member names, types and array sizes, the message identifiers and the",
         "constants they need from the headers below; descriptions are its own. Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % cfg["repository"], "| Ref | `%s` |" % ref, "| Commit | `%s` |" % commit, "",
         "Each file is `%s`." % cfg["raw_url"], "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in files:
        a.append("| `%s` | `%s` |" % (rel, shas[rel]))
    a += ["", "## License, as the sources state it", ""] + cfg["license_statement"]
    for rel in cfg.get("license_quote", []):
        if rel not in shas:
            fail("license_quote %s is not one of the files with a SHA-256" % rel)
        with open(os.path.join(src, *rel.split("/")), encoding="utf-8") as fh:
            body = fh.read().rstrip("\n").splitlines()
        if any(line.startswith("```") for line in body):
            fail("license_quote %s holds a code fence" % rel)
        a += ["", "`%s`, quoted whole:" % rel, "", "```"] + body + ["```"]
    a += [""] + cfg.get("licence_note", []) + (["" ] if cfg.get("licence_note") else []) + [
          "No source carries a distribution statement, handling marking, export-control",
          "notice or proprietary notice."]
    return "\n".join(a) + "\n"


def emit_sources_provenance(cfg, commit, ref, files, src, date_read):
    a = ["# Provenance of the inputs of tools/gen/cstruct2pack.py for %s" % cfg["family"], "",
         "Written by `cstruct2pack.py --commit`; every later run checks the files against it.",
         "Date read: %s." % date_read, "",
         "| Fact | Value |", "|---|---|",
         "| Repository | %s |" % cfg["repository"], "| Ref | `%s` |" % ref, "| Commit | `%s` |" % commit, "",
         "| Path | SHA-256 |", "|---|---|"]
    for rel in files:
        a.append("| `%s` | `%s` |" % (rel, sha256_file(os.path.join(src, *rel.split("/")))))
    a += ["", "License: see any `packs/%s-*/PROVENANCE.md`." % cfg["family"]]
    return "\n".join(a) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", required=True, help="tools/gen/cstruct/<family>.json")
    ap.add_argument("--src", required=True, metavar="DIR", help="the checkout the config's paths are relative to")
    genio.add_arguments(ap)
    ap.add_argument("--commit", help="write tools/gen/sources/<family>-PROVENANCE.md for this commit (with --ref)")
    ap.add_argument("--ref", help="the tag or branch of --commit")
    ap.add_argument("--core-def", help="model/core.def (default: <out>/model/core.def)")
    ap.add_argument("--date-read", default="2026-11-20")
    args = ap.parse_args(argv)
    if args.commit and not args.ref:
        ap.error("--commit needs --ref")
    args.core_def = args.core_def or os.path.join(args.out, "model", "core.def")
    out = genio.Output(args.out, check=args.check)
    try:
        nmsg, npk, nskip, nkeys, nvec, skipped = build(args, out)
    except GenError as e:
        print("cstruct2pack: %s" % e, file=sys.stderr)
        return 1
    print("cstruct2pack: %d messages in %d packs (%d skipped), %d keys and lists, %d vectors checked"
          % (nmsg, npk, nskip, nkeys, nvec))
    return out.report("cstruct2pack")


if __name__ == "__main__":
    sys.exit(main())
