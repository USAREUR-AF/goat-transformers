#!/usr/bin/env python3
"""jsonschema2pack: turn a JSON Schema message set into a goat-transformers pack.

Python 3 standard library only. Reads JSON Schema documents (draft-07, 2019-09,
2020-12) and OpenAPI 3 documents (`components.schemas`), as JSON or as the
plain subset of YAML that schema files use, and writes:

  <out>/model/<module>.def                 raw keys and lists of the format
  <out>/packs/<format>/pack.def            the pack: wire `json` (engine-spec 0.5,
                                           groups 0.7) or wire `geojson` (a Feature)
  <out>/packs/<format>/pack.md             what was mapped, what was not, and why
  <out>/packs/<format>/vectors/gen-*.json  one same-format round trip per kind
  <out>/packs/<other>/vectors/gen-<other>-to-<format>.json   with --cross
  <names file>                             the key pinned to every (path, type)

Then it re-reads the pack it wrote with its own loader and replays every vector
through its own json / geojson codec, written from spec/engine-spec.md (0.1,
0.1.1, 0.5, 0.6, 0.7), and stops if one does not hold. No engine is run.

What a schema construct becomes:

  object member of a scalar type   a `field` line; nested objects give dotted paths (json)
  array                            a `group` (json); items of a scalar type are one `.` line
  allOf, oneOf, anyOf              the members of every branch, merged by name
  ["T", "null"], oneOf [T, null]   T; null is absent on the wire
  $ref                             followed: within a file, to another file given here,
                                   to a file by its $id, or through --alias
  additionalProperties, patternProperties  not mapped (member names are data)

On the geojson wire (the message is one Feature) only the places the wire
addresses are mapped: top-level members, one level of `properties`, and the
Point coordinates through --map; the rest is residue, which that wire carries.

Every file goes through tools/gen/genio.py. With --check nothing is written:
each file the run would write is compared with the one under --out (and with the
names file), every difference is reported, and the exit status is 1 when any
file differs, is missing or would be removed.

Usage: see --help. Run with `python3 -I`.
"""
import argparse
import collections
import decimal
import fractions
import hashlib
import json
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402  (the directory of this file is put on the path above)

NAME = "jsonschema2pack"

MAX_DEPTH = 8
# --max-depth and --max-nest of the current run (set by run(); the defaults are the
# limits every pack had before the options existed)
LIMITS = {"depth": MAX_DEPTH, "nest": None}
MAX_KEY_LEN = 96
KEY_BUDGET = 60000
VECTOR_BUDGET = 12 * 1000 * 1000


class GenError(Exception):
    pass


# --------------------------------------------------------------------------
# YAML: the subset schema files use (block mappings and sequences, plain and
# quoted scalars, block scalars | and >, flow [..] and {..} of scalars)
# --------------------------------------------------------------------------

def _yaml_scalar(text):
    t = text.strip()
    if t == "" or t in ("~", "null", "Null", "NULL"):
        return None
    if t[0] == '"':
        return json.loads(t)
    if t[0] == "'":
        if not t.endswith("'"):
            raise GenError("yaml: unterminated quoted scalar %r" % t)
        return t[1:-1].replace("''", "'")
    if t[0] in "[{":
        return _yaml_flow(t)
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?\d+", t):
        return int(t)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", t):
        return float(t)
    return t


def _yaml_flow(t):
    pos = [0]

    def ws():
        while pos[0] < len(t) and t[pos[0]] in " \t":
            pos[0] += 1

    def item():
        ws()
        c = t[pos[0]]
        if c == "[":
            pos[0] += 1
            out = []
            ws()
            if t[pos[0]] == "]":
                pos[0] += 1
                return out
            while True:
                out.append(item())
                ws()
                c = t[pos[0]]
                pos[0] += 1
                if c == "]":
                    return out
                if c != ",":
                    raise GenError("yaml flow: %r" % t)
        if c == "{":
            pos[0] += 1
            out = collections.OrderedDict()
            ws()
            if t[pos[0]] == "}":
                pos[0] += 1
                return out
            while True:
                k = item()
                ws()
                if t[pos[0]] != ":":
                    raise GenError("yaml flow map: %r" % t)
                pos[0] += 1
                out[str(k)] = item()
                ws()
                c = t[pos[0]]
                pos[0] += 1
                if c == "}":
                    return out
                if c != ",":
                    raise GenError("yaml flow: %r" % t)
        if c in "\"'":
            q = c
            j = pos[0] + 1
            while True:
                j = t.index(q, j)
                if q == '"' and t[j - 1] == "\\":
                    j += 1
                    continue
                if q == "'" and j + 1 < len(t) and t[j + 1] == "'":
                    j += 2
                    continue
                break
            s = t[pos[0]:j + 1]
            pos[0] = j + 1
            return _yaml_scalar(s)
        j = pos[0]
        while j < len(t) and t[j] not in ",]}" and not (t[j] == ":" and (j + 1 == len(t) or t[j + 1] == " ")):
            j += 1
        s = t[pos[0]:j]
        pos[0] = j
        return _yaml_scalar(s)

    v = item()
    ws()
    if pos[0] != len(t):
        raise GenError("yaml flow: trailing text in %r" % t)
    return v


def _strip_comment(line):
    out, q = [], None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "\"'" and (i == 0 or line[i - 1] in " :[{,-"):
            q = c
        elif c == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(c)
    return "".join(out).rstrip()


def _split_key(content):
    """('key', rest) when the line is `key: rest` or `key:`; else None."""
    if content[0] in "\"'":
        q = content[0]
        j = content.index(q, 1)
        while q == "'" and j + 1 < len(content) and content[j + 1] == "'":
            j = content.index(q, j + 2)
        key = _yaml_scalar(content[:j + 1])
        rest = content[j + 1:]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] == " "):
            return str(key), rest[1:].strip()
        return None
    m = re.match(r"([^\s:#\[\]{},][^:]*?|\S*?):(?: (.*)|$)", content, re.S)
    if not m or content.startswith(("- ", "-\t")) or content == "-":
        return None
    return m.group(1).strip(), (m.group(2) or "").strip()


def _open_quote(line):
    """The quote character of a quoted scalar that starts on this line (as a mapping
    value or a sequence item) and is not closed on it; else None."""
    t = line.strip()
    kv = _split_key(t) if t and t[0] not in "\"'" else None
    if kv is not None:
        rest = kv[1]
    elif t.startswith("- "):
        rest = t[2:].strip()
    else:
        rest = t
    if not rest or rest[0] not in "\"'":
        return None
    q = rest[0]
    j = 1
    while j < len(rest):
        c = rest[j]
        if q == '"' and c == "\\":
            j += 2
            continue
        if c == q:
            if q == "'" and j + 1 < len(rest) and rest[j + 1] == "'":
                j += 2
                continue
            return None
        j += 1
    return q


def yaml_load(text):
    # tabs are not YAML indentation; expand only leading ones, keep those in text
    raw = [re.sub(r"^\t+", lambda m: "    " * len(m.group(0)), l) for l in text.split("\n")]
    lines = []  # (indent, content, raw line index)
    i = 0
    while i < len(raw):
        l = raw[i]
        if l.strip() in ("---", "..."):
            i += 1
            continue
        c = _strip_comment(l)
        start = i
        q = _open_quote(c)
        while q and i + 1 < len(raw):
            # a quoted scalar over several lines: each line break folds to a space,
            # an empty line to a line feed (YAML 1.2, 7.3)
            i += 1
            nxt = raw[i].strip()
            c = c.rstrip() + ("\n" if nxt == "" else " ") + nxt if not c.endswith("\n") else c + nxt
            q = _open_quote(c)
        if c.strip():
            lines.append((len(c) - len(c.lstrip(" ")), c.strip(), start))
        i += 1
    pos = [0]

    def block_scalar(style, parent_indent, start_raw):
        keep = style[1:2]
        out = []
        j = start_raw + 1
        ind = None
        while j < len(raw):
            l = raw[j]
            if l.strip() == "":
                out.append("")
                j += 1
                continue
            li = len(l) - len(l.lstrip(" "))
            if li <= parent_indent:
                break
            if ind is None:
                ind = li
            out.append(l[ind:] if li >= ind else l.strip())
            j += 1
        while pos[0] < len(lines) and lines[pos[0]][2] < j:
            pos[0] += 1
        while out and out[-1] == "":
            out.pop()
        if style[0] == "|":
            s = "\n".join(out)
        else:
            s = re.sub(r"(?<!\n)\n(?!\n)", " ", "\n".join(out))
        return s if keep == "-" else s + "\n"

    def value_after(rest, indent, raw_i):
        if rest == "":
            if pos[0] < len(lines) and lines[pos[0]][0] > indent and \
                    not _split_key(lines[pos[0]][1]) and not lines[pos[0]][1].startswith(("- ", "-")):
                # a plain scalar over several lines
                parts = []
                while pos[0] < len(lines) and lines[pos[0]][0] > indent:
                    parts.append(lines[pos[0]][1])
                    pos[0] += 1
                return _yaml_scalar(" ".join(parts)) if len(parts) == 1 else " ".join(parts)
            if pos[0] < len(lines) and (lines[pos[0]][0] > indent or
                                        (lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("-"))):
                return node(lines[pos[0]][0])
            return None
        if rest[0] in "|>":
            return block_scalar(rest, indent, raw_i)
        return _yaml_scalar(rest)

    def node(indent):
        ind, content, _ = lines[pos[0]]
        if content.startswith("-") and (content == "-" or content[1] == " "):
            out = []
            while pos[0] < len(lines) and lines[pos[0]][0] == indent and \
                    (lines[pos[0]][1] == "-" or lines[pos[0]][1].startswith("- ")):
                _, c, ri = lines[pos[0]]
                pos[0] += 1
                rest = c[1:].strip()
                if rest == "":
                    out.append(value_after("", indent, ri))
                elif _split_key(rest):
                    # a mapping that starts on the dash line
                    sub_indent = indent + 2
                    lines.insert(pos[0], (sub_indent, rest, ri))
                    out.append(node(sub_indent))
                else:
                    out.append(value_after(rest, indent, ri))
            return out
        out = collections.OrderedDict()
        while pos[0] < len(lines) and lines[pos[0]][0] == indent:
            _, c, ri = lines[pos[0]]
            kv = _split_key(c)
            if kv is None:
                raise GenError("yaml: line %d is not `key: value`: %r" % (ri + 1, c))
            pos[0] += 1
            out[kv[0]] = value_after(kv[1], indent, ri)
        return out

    if not lines:
        return None
    v = node(lines[0][0])
    if pos[0] != len(lines):
        raise GenError("yaml: line %d is outside the document's structure" % (lines[pos[0]][2] + 1))
    return v


def load_doc(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig")
    if path.endswith((".yaml", ".yml")):
        return yaml_load(text), raw
    return json.loads(text, object_pairs_hook=collections.OrderedDict), raw


# --------------------------------------------------------------------------
# Schema registry and $ref resolution
# --------------------------------------------------------------------------

class Ctx:
    __slots__ = ("doc", "base")

    def __init__(self, doc, base):
        self.doc, self.base = doc, base


class Registry:
    def __init__(self, files, aliases, opaque):
        self.by_uri = {}
        self.files = []
        for f in files:
            doc, raw = load_doc(f)
            uri = "file://" + os.path.abspath(f)
            self.by_uri[uri] = doc
            if isinstance(doc, dict) and isinstance(doc.get("$id"), str):
                self.by_uri[doc["$id"].split("#")[0]] = doc
            self.files.append((f, None, hashlib.sha256(raw).hexdigest(), len(raw), doc))
        root = os.path.commonpath([os.path.dirname(os.path.abspath(f)) for f in files])
        self.root = root
        self.files = [(f, os.path.relpath(os.path.abspath(f), root), sha, n, doc) for f, _, sha, n, doc in self.files]
        self.base_of = {}
        for uri, doc in self.by_uri.items():
            self.base_of[id(doc)] = doc.get("$id", uri) if isinstance(doc, dict) and isinstance(doc.get("$id"), str) else uri
        self.aliases = {k: "file://" + os.path.abspath(v) for k, v in aliases.items()}
        self.opaque = opaque
        self.unresolved = collections.Counter()

    def ctx_for(self, path):
        uri = "file://" + os.path.abspath(path)
        doc = self.by_uri[uri]
        return Ctx(doc, self.base_of[id(doc)])

    def resolve(self, ref, ctx):
        """(schema, ctx) the reference names, or None for an opaque reference."""
        target = urllib.parse.urljoin(ctx.base, ref) if not ref.startswith("#") else ctx.base + ref
        uri, _, frag = target.partition("#")
        for o in self.opaque:
            if target.startswith(o):
                return None
        uri = self.aliases.get(uri, uri)
        doc = self.by_uri.get(uri)
        if doc is None:
            raise GenError("$ref %r (as %s) names no file given here; pass it with --schema or --alias" % (ref, uri))
        node = doc
        if frag:
            for part in frag.lstrip("/").split("/"):
                part = urllib.parse.unquote(part).replace("~1", "/").replace("~0", "~")
                if isinstance(node, list):
                    node = node[int(part)]
                elif part in node:
                    node = node[part]
                else:
                    raise GenError("$ref %r: no %r in %s" % (ref, part, uri))
        return node, Ctx(doc, self.base_of[id(doc)])


# --------------------------------------------------------------------------
# Merging a schema into one node
# --------------------------------------------------------------------------

class Node:
    def __init__(self):
        self.types = set()
        self.props = collections.OrderedDict()   # name -> [(schema, ctx)]
        self.items = []                          # [(schema, ctx)]
        self.enum = []
        self.format = None
        self.minimum = None
        self.maximum = None
        self.multiple_of = None
        self.free_members = False
        self.opaque = False
        self.descs = []
        self.required = set()
        self.refs = []


def collect(schema, ctx, reg, node, seen, depth=0):
    if depth > 64:
        raise GenError("schema nesting beyond 64 levels")
    if schema is True or schema is None:
        return
    if schema is False or not isinstance(schema, dict):
        return
    if "$ref" in schema:
        key = (id(ctx.doc), schema["$ref"], ctx.base)
        r = reg.resolve(schema["$ref"], ctx)
        if r is None:
            node.opaque = True
        elif key not in seen:
            node.refs.append(schema["$ref"])
            collect(r[0], r[1], reg, node, seen | {key}, depth + 1)
    t = schema.get("type")
    if isinstance(t, str):
        node.types.add(t)
    elif isinstance(t, list):
        node.types.update(x for x in t if isinstance(x, str))
    if "nullable" in schema and schema["nullable"] is True:
        node.types.add("null")
    for name, sub in (schema.get("properties") or {}).items():
        node.props.setdefault(name, []).append((sub, ctx))
    for r in schema.get("required") or []:
        if isinstance(r, str):
            node.required.add(r)
    it = schema.get("items")
    if isinstance(it, dict):
        node.items.append((it, ctx))
    elif isinstance(it, list) or "prefixItems" in schema:
        node.items.append(({"x-tuple": True}, ctx))
    if "enum" in schema and isinstance(schema["enum"], list):
        node.enum += [v for v in schema["enum"] if v not in node.enum]
    if "const" in schema and schema["const"] not in node.enum:
        node.enum.append(schema["const"])
    if isinstance(schema.get("format"), str):
        node.format = node.format or schema["format"]
    for k in ("minimum", "maximum", "multipleOf"):
        if isinstance(schema.get(k), (int, float)) and not isinstance(schema.get(k), bool):
            setattr(node, {"minimum": "minimum", "maximum": "maximum", "multipleOf": "multiple_of"}[k],
                    schema[k])
    ap = schema.get("additionalProperties")
    if isinstance(ap, dict) and ap or schema.get("patternProperties"):
        node.free_members = True
    if isinstance(schema.get("description"), str):
        node.descs.append(" ".join(schema["description"].split()))
    if isinstance(schema.get("title"), str) and not node.descs:
        pass
    for kw in ("allOf", "oneOf", "anyOf"):
        for sub in schema.get(kw) or []:
            collect(sub, ctx, reg, node, seen, depth + 1)
    if schema.get("x-tuple"):
        node.types.add("x-tuple")


def merged(entries, reg):
    n = Node()
    for s, c in entries:
        collect(s, c, reg, n, frozenset())
    return n


def kind_of(n):
    """('object'|'array'|'string'|'integer'|'number'|'boolean'|None, reason)."""
    types = set(n.types) - {"null"}
    if "x-tuple" in types:
        return None, "array of fixed positions (tuple)"
    if not types:
        if n.props:
            types = {"object"}
        elif n.items:
            types = {"array"}
        elif n.enum:
            vals = [v for v in n.enum if v is not None]
            if vals and all(isinstance(v, str) for v in vals):
                types = {"string"}
            elif vals and all(isinstance(v, bool) for v in vals):
                types = {"boolean"}
            elif vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
                types = {"integer"}
            elif vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
                types = {"number"}
    if types == {"integer", "number"}:
        types = {"number"}
    if len(types) > 1:
        return None, "several JSON types (%s)" % "/".join(sorted(types))
    if not types:
        if n.opaque:
            return None, "schema outside this set (opaque reference)"
        return None, "no type stated"
    t = types.pop()
    if t == "number" and n.multiple_of in (1, 1.0):
        t = "integer"
    return t, None


# --------------------------------------------------------------------------
# Walking a message
# --------------------------------------------------------------------------

class Leaf:
    def __init__(self, path, jtype, node, required):
        self.path = path          # list of member names (relative to the scope)
        self.jtype = jtype        # string | integer | number | boolean
        self.node = node
        self.required = required
        self.key = None
        self.shared = None        # shared key bound here, if any
        self.transform = None


class Group:
    def __init__(self, path, scalar_item):
        self.path = path
        self.scalar_item = scalar_item
        self.lines = []           # Leaf | Group, relative to the item
        self.list = None


def walk_json(entries, reg, path, required, out, notmapped, depth, stack, nest=0):
    n = merged(entries, reg)
    t, why = kind_of(n)
    loc = ".".join(path) or "(message)"
    if t is None:
        notmapped.append((loc, why))
        return
    if t == "object":
        if depth >= LIMITS["depth"]:
            notmapped.append((loc, "below depth %d" % LIMITS["depth"]))
            return
        if n.free_members and not n.props:
            notmapped.append((loc, "object whose member names are data (additionalProperties / patternProperties)"))
            return
        if n.free_members:
            notmapped.append((loc + ".*", "members beyond the named ones (additionalProperties)"))
        for name, subs in n.props.items():
            if "." in name:
                notmapped.append((loc + "." + name, "member name contains `.` (not addressable, engine-spec 0.5)"))
                continue
            sig = tuple(sorted((id(s), c.base) for s, c in subs))
            if sig in stack:
                notmapped.append((loc + "." + name, "recursive schema"))
                continue
            walk_json(subs, reg, path + [name], required and name in n.required, out, notmapped,
                      depth + 1, stack | {sig}, nest)
        return
    if t == "array":
        if not path:
            notmapped.append((loc, "the message is an array"))
            return
        if not n.items:
            notmapped.append((loc, "array with no item schema"))
            return
        inner = merged(n.items, reg)
        it, why = kind_of(inner)
        if it is None:
            notmapped.append((loc + "[]", why))
            return
        if it == "array":
            notmapped.append((loc + "[]", "array of arrays (an item is not an object or a scalar)"))
            return
        if LIMITS["nest"] is not None and nest >= LIMITS["nest"]:
            notmapped.append((loc, "array inside %d arrays (--max-nest %d)" % (nest, LIMITS["nest"])))
            return
        g = Group(path, it != "object")
        if it == "object":
            walk_json(n.items, reg, [], True, g.lines, notmapped_inner(notmapped, loc + "[]"), depth + 1, stack,
                      nest + 1)
            if not g.lines:
                notmapped.append((loc + "[]", "array of objects in which nothing can be mapped"))
                return
        else:
            g.lines.append(Leaf([], it, inner, True))
        out.append(g)
        return
    out.append(Leaf(path, t, n, required))


class notmapped_inner(list):
    def __init__(self, outer, prefix):
        super().__init__()
        self.outer, self.prefix = outer, prefix

    def append(self, x):
        loc, why = x
        self.outer.append((self.prefix + ("." + loc if loc != "(message)" else ""), why))


def walk_geojson(entries, reg, notmapped, top_members=None):
    """Top-level scalar members and scalar members of `properties`."""
    out = []
    n = merged(entries, reg)
    for name, subs in n.props.items():
        if name in ("type", "geometry"):
            continue
        sub = merged(subs, reg)
        t, why = kind_of(sub)
        if name == "properties" and t == "object":
            for pname, psubs in sub.props.items():
                pn = merged(psubs, reg)
                pt, pwhy = kind_of(pn)
                loc = "properties." + pname
                if pt in ("string", "integer", "number"):
                    out.append(Leaf(["properties", pname], pt, pn, pname in sub.required))
                elif pt == "boolean":
                    notmapped.append((loc, "boolean (no boolean transform on the geojson wire); residue, type on the way back not ruled"))
                elif pt in ("object", "array"):
                    notmapped.append((loc, "%s inside properties; carried as residue" % pt))
                else:
                    notmapped.append((loc, (pwhy or "no type") + "; carried as residue"))
            if sub.free_members:
                notmapped.append(("properties.*", "members beyond the named ones; carried as residue"))
            continue
        if t in ("string", "integer", "number") and top_members is not None and name not in top_members:
            notmapped.append((name, "top-level member not in --top-level-members; not carried (see pack.md)"))
        elif t in ("string", "integer", "number"):
            out.append(Leaf([name], t, sub, name in n.required))
        elif t == "boolean":
            notmapped.append((name, "boolean (no boolean transform on the geojson wire); not carried (see pack.md)"))
        elif t in ("object", "array"):
            notmapped.append((name, "top-level %s; not carried (top-level residue is not settled, see pack.md)" % t))
        else:
            notmapped.append((name, (why or "no type") + "; carried as residue"))
    return out


# --------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------

def slug(s):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "x"


def short(name):
    if len(name) <= MAX_KEY_LEN:
        return name
    h = hashlib.sha256(name.encode()).hexdigest()[:8]
    return name[:MAX_KEY_LEN - 9].rstrip("_") + "_" + h


MODEL_TYPE = {"string": "string", "integer": "int", "number": "float", "boolean": "int"}


class Names:
    def __init__(self, path):
        self.path = path
        self.data = {"keys": {}, "lists": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        self.used = set(self.data["keys"].values()) | set(self.data["lists"].values())

    def key(self, ident, base):
        if ident in self.data["keys"]:
            return self.data["keys"][ident]
        name = short(base)
        k = 2
        while name in self.used:
            name = short("%s_%d" % (base, k))
            k += 1
        self.data["keys"][ident] = name
        self.used.add(name)
        return name

    def list(self, ident, base):
        if ident in self.data["lists"]:
            return self.data["lists"][ident]
        name = short(base)
        k = 2
        while name in self.used:
            name = short("%s_%d" % (base, k))
            k += 1
        self.data["lists"][ident] = name
        self.used.add(name)
        return name

    def text(self):
        return json.dumps(self.data, indent=1, sort_keys=True) + "\n"


def names_output(names_file, out):
    """(Output, relative path) through which the names file is written: the
    run's Output when the file lies under --out, one of its own otherwise."""
    path = os.path.abspath(names_file)
    if path.startswith(out.root + os.sep):
        return out, os.path.relpath(path, out.root).replace(os.sep, "/")
    return genio.Output(os.path.dirname(path), check=out.check), os.path.basename(path)


def transform_for(leaf, wire, shared_type=None):
    j = leaf.jtype
    if shared_type == "int" and j == "string" and leaf.node.format == "date-time":
        return "iso8601_ms"
    if j == "string":
        return "string"
    if j == "integer":
        return "int"
    if j == "number":
        return "int" if shared_type == "int" else "float"
    if j == "boolean":
        return "bool"
    raise GenError("no transform for %s" % j)


def assign(lines, names, module, scope, wire):
    """Give every leaf its raw key and every group its list. `scope` names the
    enclosing list ('' for the message), so item keys of different lists differ."""
    for ln in lines:
        if isinstance(ln, Leaf):
            loc = ".".join(ln.path) if ln.path else "."
            mt = MODEL_TYPE[ln.jtype]
            ident = "%s|%s|%s" % (scope, loc, mt)
            base = slug((scope + "_" if scope else "") + (loc if loc != "." else "value"))
            ln.key = "%s.%s" % (module, names.key(ident, base))
            ln.transform = transform_for(ln, wire)
        else:
            ident = "%s|%s" % (scope, ".".join(ln.path))
            ln.list = "%s.%s" % (module, names.list(ident, slug((scope + "_" if scope else "") + "_".join(ln.path))))
            assign(ln.lines, names, module, ln.list.split(".", 1)[1], wire)


# --------------------------------------------------------------------------
# JSON text, canonical (engine-spec 0.5 "Canonical output", ruling 3 of 0.1.1)
# --------------------------------------------------------------------------

def fmt_float(x):
    if x == 0:
        return "0"
    if x != x or x in (float("inf"), float("-inf")):
        raise GenError("not a finite float")
    r = repr(float(x))
    d = decimal.Decimal(r)
    if d == d.to_integral_value():
        return str(int(d))
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def fmt_str(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif o < 0x20:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


class Raw:
    """A JSON value kept as text (residue)."""
    def __init__(self, text):
        self.text = text


def dump(v):
    if isinstance(v, Raw):
        return v.text
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return fmt_float(v)
    if isinstance(v, str):
        return fmt_str(v)
    if isinstance(v, list):
        return "[" + ",".join(dump(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(fmt_str(k) + ":" + dump(x) for k, x in v.items()) + "}"
    raise GenError("cannot write %r" % (v,))


def when_value(text):
    if text.startswith("="):
        return text[1:]
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?", text):
        v = json.loads(text)
        return v
    return text


# --------------------------------------------------------------------------
# A small pack loader and codec (json and geojson wires), for the self-check
# --------------------------------------------------------------------------

def tokens(line):
    out, cur, q = [], [], False
    i = 0
    while i < len(line):
        c = line[i]
        if q:
            if c == '"':
                q = False
                out.append("".join(cur))
                cur = []
            else:
                cur.append(c)
        elif c == '"':
            q = True
        elif c in " \t\r\n":
            if cur:
                out.append("".join(cur))
                cur = []
        elif c == "#" and not cur:
            break
        else:
            cur.append(c)
        i += 1
    if cur:
        out.append("".join(cur))
    return out


class Pack:
    def __init__(self, text):
        self.wire = None
        self.common = {"when": [], "lines": []}
        self.kinds = []
        self.format = None
        cur = self.common
        stack = []
        for raw in text.split("\n"):
            t = tokens(raw)
            if not t:
                continue
            d = t[0]
            if d in ("format", "version", "distribution", "source", "uses"):
                if d == "format":
                    self.format = t[1]
                continue
            if d == "wire":
                self.wire = t[1]
            elif d == "kind":
                cur = {"name": t[1], "when": [], "lines": [], "requires": []}
                self.kinds.append(cur)
            elif d == "when":
                cur["when"].append((t[1], t[2]))
            elif d == "requires":
                cur["requires"] = t[1:]
            elif d == "field":
                (stack[-1].lines if stack else cur["lines"]).append(("field", t[1], t[2], t[3]))
            elif d == "group":
                g = PackGroup(t[1], t[2])
                (stack[-1].lines if stack else cur["lines"]).append(("group", g))
                stack.append(g)
            elif d == "end":
                stack.pop()
            else:
                raise GenError("self-check: unknown directive %s" % d)
        if stack:
            raise GenError("self-check: unbalanced group")


class PackGroup:
    def __init__(self, lst, path):
        self.list, self.path, self.lines = lst, path, []


def get_path(obj, path):
    cur = obj
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def dec_value(v, tr, where):
    if v is None:
        return None
    if tr == "string":
        if not isinstance(v, str):
            raise GenError("self-check: %s is not a string" % where)
        return v
    if tr == "float":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise GenError("self-check: %s is not a number" % where)
        return float(v)
    if tr == "int":
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
            raise GenError("self-check: %s is not an integer" % where)
        return int(v)
    if tr == "bool":
        if not isinstance(v, bool):
            raise GenError("self-check: %s is not a boolean" % where)
        return 1 if v else 0
    if tr == "iso8601_ms":
        return iso_to_ms(v)
    if tr.startswith("iscale:"):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise GenError("self-check: %s is not a number" % where)
        factor, offset = iscale_params(tr)
        r = fractions.Fraction(v) if isinstance(v, int) else fractions.Fraction(decimal.Decimal(repr(v)))
        x = r * factor
        # round half away from zero (engine-spec 0.15, ruling 4)
        n = (abs(x.numerator) * 2 + x.denominator) // (2 * x.denominator)
        return (n if x >= 0 else -n) + offset
    raise GenError("self-check: transform %s" % tr)


def iscale_params(tr):
    """(factor, offset) of `iscale:<factor>[:<offset>]`: an integer or `num/den` factor,
    an integer offset (engine-spec 0.15, Exact factors)."""
    parts = tr.split(":")
    if len(parts) not in (2, 3) or parts[0] != "iscale" or not re.fullmatch(r"-?\d+(/\d+)?", parts[1]) or \
            (len(parts) == 3 and not re.fullmatch(r"-?\d+", parts[2])):
        raise GenError("transform %r: not iscale:<factor>[:<offset>]" % tr)
    factor = fractions.Fraction(parts[1])
    if factor == 0:
        raise GenError("transform %r: factor 0" % tr)
    return factor, int(parts[2]) if len(parts) == 3 else 0


def exact_decimal(q):
    """The exact plain-decimal text of a Fraction, or None when it does not terminate
    within 18 fraction digits (engine-spec 0.15, iscale encode)."""
    sign = "-" if q < 0 else ""
    q = abs(q)
    whole, rest = divmod(q.numerator, q.denominator)
    digits = ""
    while rest and len(digits) < 18:
        rest *= 10
        d, rest = divmod(rest, q.denominator)
        digits += str(d)
    if rest:
        return None
    return sign + str(whole) + ("." + digits if digits else "")


def iso_to_ms(s):
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?([Zz]|[+-]\d\d:\d\d)", s)
    if not m:
        raise GenError("self-check: %r is not ISO 8601" % s)
    import datetime
    y, mo, d, h, mi, se = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "")[:3].ljust(3, "0")
    dt = datetime.datetime(y, mo, d, h, mi, se, tzinfo=datetime.timezone.utc)
    ms = int(dt.timestamp()) * 1000 + int(frac)
    z = m.group(8)
    if z not in ("Z", "z"):
        sign = 1 if z[0] == "+" else -1
        ms -= sign * (int(z[1:3]) * 60 + int(z[4:6])) * 60000
    return ms


def ms_to_iso(ms):
    import datetime
    dt = datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (ms % 1000)


def enc_value(v, tr):
    if tr == "string":
        return str(v)
    if tr == "float":
        return float(v)
    if tr == "int":
        return int(v)
    if tr == "bool":
        if v not in (0, 1):
            raise GenError("self-check: bool value %r" % v)
        return v == 1
    if tr == "iso8601_ms":
        return ms_to_iso(int(v))
    if tr.startswith("iscale:"):
        factor, offset = iscale_params(tr)
        q = fractions.Fraction(int(v) - offset) / factor
        if q.denominator == 1:
            return int(q)
        text = exact_decimal(q)
        if text is None:
            raise GenError("self-check: %s does not encode %r exactly" % (tr, v))
        return Raw(text)
    raise GenError(tr)


def parse_json(text):
    def hook(pairs):
        d = collections.OrderedDict()
        for k, v in pairs:
            if k in d:
                raise GenError("self-check: member %s twice" % k)
            d[k] = v
        return d
    return json.loads(text, object_pairs_hook=hook)


def decode_lines(obj, lines, ent, root):
    mapped = set()
    for ln in lines:
        if ln[0] == "field":
            _, key, loc, tr = ln
            v = obj if loc == "." else get_path(obj, loc)
            mapped.add(loc)
            if v is None or isinstance(v, (dict, list)) and loc != ".":
                continue
            val = dec_value(v, tr, loc)
            if key not in ent:
                ent[key] = val
        else:
            g = ln[1]
            mapped.add(g.path)
            arr = get_path(obj, g.path)
            if arr is None:
                continue
            if not isinstance(arr, list):
                raise GenError("self-check: %s is not an array" % g.path)
            items = []
            for el in arr:
                it = collections.OrderedDict()
                decode_lines(el if not (isinstance(el, dict) and False) else el, g.lines, it, False)
                items.append(it)
            ent[g.list] = items
    return mapped


def residue_of(obj, mapped, prefix=""):
    out = []
    for k, v in obj.items():
        p = prefix + k
        if "." in k:
            continue
        if p in mapped:
            continue
        if isinstance(v, dict):
            out += residue_of(v, mapped, p + ".")
        elif isinstance(v, list) or v is None:
            continue
        else:
            out.append((p, v))
    return out


def select_kind(pack, obj, wire):
    def holds(loc, val):
        v = geo_get(obj, loc) if wire == "geojson" else get_path(obj, loc)
        if val == "present":
            return v is not None
        want = val[1:] if val.startswith("=") else val
        if isinstance(v, str):
            return v == want
        if isinstance(v, bool):
            return ("true" if v else "false") == want
        if isinstance(v, (int, float)):
            return fmt_float(v) == fmt_float(float(want)) if re.fullmatch(r"-?[\d.eE+-]+", want) else False
        return False
    for loc, val in pack.common["when"]:
        if not holds(loc, val):
            raise GenError("self-check: common when %s fails" % loc)
    if not pack.kinds:
        return None
    for k in pack.kinds:
        if all(holds(l, v) for l, v in k["when"]):
            return k
    raise GenError("self-check: no kind")


def geo_get(obj, loc):
    if loc.startswith("geometry."):
        g = obj.get("geometry")
        if not isinstance(g, dict) or g.get("type") != "Point":
            return None
        c = g.get("coordinates") or []
        i = {"lon": 0, "lat": 1, "alt": 2}[loc.split(".")[1]]
        return c[i] if i < len(c) else None
    if loc.startswith("properties."):
        p = obj.get("properties") or {}
        return p.get(loc[len("properties."):])
    return obj.get(loc)


def decode(pack, text):
    obj = parse_json(text)
    if not isinstance(obj, dict):
        raise GenError("self-check: not an object")
    kind = select_kind(pack, obj, pack.wire)
    lines = pack.common["lines"] + (kind["lines"] if kind else [])
    ent = collections.OrderedDict()
    if pack.wire == "json":
        mapped = decode_lines(obj, lines, ent, True)
        mapped |= {l for l, _ in pack.common["when"] + (kind["when"] if kind else [])}
        res = residue_of(obj, mapped)
    else:
        mapped = set()
        for ln in lines:
            _, key, loc, tr = ln
            mapped.add(loc)
            v = geo_get(obj, loc)
            if v is not None and key not in ent:
                ent[key] = dec_value(v, tr, loc)
        for loc, _ in pack.common["when"] + (kind["when"] if kind else []):
            mapped.add(loc)
        res = []
        for k, v in (obj.get("properties") or {}).items():
            if "properties." + k not in mapped and v is not None:
                res.append(("properties." + k, v))
        for k, v in obj.items():
            if k not in ("type", "geometry", "properties") and k not in mapped and v is not None:
                res.append((k, v))
    return kind, ent, res


def set_path(obj, path, v):
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, collections.OrderedDict())
    cur[parts[-1]] = v


def put_path(obj, path, v):
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, collections.OrderedDict())
    if parts[-1] not in cur:
        cur[parts[-1]] = v


def encode_lines(lines, ent, obj):
    for ln in lines:
        if ln[0] == "field":
            _, key, loc, tr = ln
            if key in ent:
                v = enc_value(ent[key], tr)
                if loc == ".":
                    return v
                put_path(obj, loc, v)
            elif loc != ".":
                # reserve the position of the first line that addresses a nested object
                pass
        else:
            g = ln[1]
            if g.list in ent:
                arr = []
                for it in ent[g.list]:
                    if len(g.lines) == 1 and g.lines[0][0] == "field" and g.lines[0][2] == ".":
                        k = g.lines[0][1]
                        arr.append(enc_value(it[k], g.lines[0][3]) if k in it else None)
                    else:
                        o = collections.OrderedDict()
                        encode_lines(g.lines, it, o)
                        arr.append(prune(o))
                put_path(obj, g.path, arr)
    return obj


def prune(o):
    out = collections.OrderedDict()
    for k, v in o.items():
        if isinstance(v, dict):
            v = prune(v)
            if not v:
                continue
        out[k] = v
    return out


def order_skeleton(lines, whens):
    """Positions: a nested object appears at its first line."""
    skel = collections.OrderedDict()
    # a `when <path> present` maps nothing (ruling 27 of 0.5), so it gives no position
    for loc in [l for l, v in whens if v != "present"] + [ln[2] if ln[0] == "field" else ln[1].path for ln in lines]:
        if loc == ".":
            continue
        cur = skel
        for p in loc.split("."):
            cur = cur.setdefault(p, collections.OrderedDict())
    return skel


def fill(skel, values):
    out = collections.OrderedDict()
    for k, sub in skel.items():
        if k not in values:
            continue
        v = values[k]
        if isinstance(v, dict) and not isinstance(v, Raw) and sub:
            v2 = fill(sub, v)
            for kk, vv in v.items():
                if kk not in v2:
                    v2[kk] = vv
            if v2:
                out[k] = v2
        else:
            out[k] = v
    for k, v in values.items():
        if k not in out and not (isinstance(v, dict) and not v):
            out[k] = v
    return out


def encode(pack, kind, ent, residue):
    whens = pack.common["when"] + (kind["when"] if kind else [])
    lines = pack.common["lines"] + (kind["lines"] if kind else [])
    if pack.wire == "json":
        vals = collections.OrderedDict()
        encode_lines(lines, ent, vals)
        for loc, val in whens:
            if val != "present":
                parts = loc.split(".")
                cur = vals
                for p in parts[:-1]:
                    cur = cur.setdefault(p, collections.OrderedDict())
                cur[parts[-1]] = when_value(val)
        for loc, v in residue:
            put_path(vals, loc, v)
        skel = order_skeleton(lines, whens)
        obj = fill(skel, prune(vals))
        return dump(obj)
    # geojson
    props = collections.OrderedDict()
    top = collections.OrderedDict()
    lon = lat = alt = None
    for ln in lines:
        _, key, loc, tr = ln
        if key not in ent:
            continue
        v = enc_value(ent[key], tr)
        if loc == "geometry.lon":
            lon = v if lon is None else lon
        elif loc == "geometry.lat":
            lat = v if lat is None else lat
        elif loc == "geometry.alt":
            alt = v if alt is None else alt
        elif loc.startswith("properties."):
            props.setdefault(loc[11:], v)
        else:
            top.setdefault(loc, v)
    for loc, val in whens:
        if val == "present":
            continue
        if loc.startswith("properties."):
            props[loc[11:]] = when_value(val)
        else:
            top[loc] = when_value(val)
    for loc, v in residue:
        if loc.startswith("properties."):
            props.setdefault(loc[11:], v)
        else:
            top.setdefault(loc, v)
    out = collections.OrderedDict()
    out["type"] = "Feature"
    if lon is None or lat is None:
        out["geometry"] = None
    else:
        out["geometry"] = collections.OrderedDict([("type", "Point"),
                                                   ("coordinates", [lon, lat] + ([alt] if alt is not None else []))])
    out["properties"] = props
    for k, v in top.items():
        out[k] = v
    return dump(out)


# --------------------------------------------------------------------------
# Sample values for vectors
# --------------------------------------------------------------------------

def rnd(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


FLOATS = [12.5, -3.25, 0.75, 101.125, 7.0625, -0.5, 42.375, 1.5]


def sample(leaf, seed, shared=None):
    n = leaf.node
    r = rnd(seed, ".".join(leaf.path))
    if n.enum:
        vals = [v for v in n.enum if v is not None]
        if leaf.jtype == "string":
            # an enum value a YAML reader typed as a number (`08`) is no sample for a string
            vals = [v for v in vals if isinstance(v, str)]
        if vals:
            v = vals[r % len(vals)]
            if leaf.jtype == "number" and isinstance(v, int):
                return float(v)
            return v
    if shared in ("time_ms",):
        ms = 1700000000000 + r % 100000000000
        st = getattr(leaf, "shared_transform", "") or ""
        if st.startswith("iscale:"):
            # a whole number on the wire, which the transform reads back exactly
            factor, offset = iscale_params(st)
            return int((fractions.Fraction(ms - offset) / factor).__floor__())
        return ms_to_iso(ms) if leaf.transform == "iso8601_ms" or (leaf.jtype == "string") else ms
    if shared == "lat":
        return [38.8977, -33.865, 51.4775, 21.3069][r % 4]
    if shared == "lon":
        return [-77.0365, 151.2094, -0.0014, -157.8583][r % 4]
    j = leaf.jtype
    if j == "string":
        f = n.format
        if f == "uuid":
            h = hashlib.sha256(("uuid" + seed + ".".join(leaf.path)).encode()).hexdigest()
            return "%s-%s-4%s-8%s-%s" % (h[:8], h[8:12], h[13:16], h[17:20], h[20:32])
        if f == "date-time":
            return ms_to_iso(1700000000000 + r % 100000000000)
        if f == "date":
            return "2024-%02d-%02d" % (1 + r % 12, 1 + r % 28)
        if f in ("uri", "iri", "url", "uri-reference", "iri-reference"):
            return "https://example.org/%d" % (r % 1000)
        return "s%d" % (r % 100000)
    if j == "integer":
        lo = n.minimum if n.minimum is not None else 0
        hi = n.maximum if n.maximum is not None else lo + 100000
        lo, hi = int(lo), int(hi)
        return lo + r % max(1, hi - lo + 1)
    if j == "number":
        lo = n.minimum if n.minimum is not None else -1e6
        hi = n.maximum if n.maximum is not None else 1e6
        for k in range(len(FLOATS)):
            v = FLOATS[(r + k) % len(FLOATS)]
            if lo <= v <= hi:
                return v
        return float(lo)
    if j == "boolean":
        return bool(r % 2)
    raise GenError(j)


def build_instance(lines, seed, depth, shared_of):
    obj = collections.OrderedDict()
    for ln in lines:
        if isinstance(ln, Leaf):
            v = sample(ln, seed, shared_of.get(id(ln)))
            if not ln.path:
                return v
            put_path(obj, ".".join(ln.path), v)
        else:
            n = 2 if depth == 0 else 1
            arr = []
            for i in range(n):
                arr.append(build_instance(ln.lines, "%s/%s[%d]" % (seed, ".".join(ln.path), i), depth + 1,
                                          shared_of))
            put_path(obj, ".".join(ln.path), arr)
    return obj


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def parse_kv(spec, what):
    if "=" not in spec:
        raise GenError("%s %r: expected NAME=VALUE" % (what, spec))
    return spec.split("=", 1)


def read_module_keys(model_dir):
    keys, derives = {}, []
    for fn in sorted(os.listdir(model_dir)):
        if not fn.endswith(".def"):
            continue
        mod = None
        with open(os.path.join(model_dir, fn), encoding="utf-8") as fh:
            text = fh.read()
        for raw in text.split("\n"):
            t = tokens(raw)
            if not t:
                continue
            if t[0] == "module":
                mod = t[1]
            elif t[0] == "key" and mod:
                keys[t[1] if mod == "core" else "%s.%s" % (mod, t[1])] = (t[2], t[3])
            elif t[0] == "derive":
                derives.append((t[1], t[3:]))
    return keys, derives


def main(argv=None):
    try:
        return run(argv)
    except GenError as e:
        sys.stderr.write("%s: %s\n" % (NAME, e))
        return 1


def run(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--schema", nargs="+", required=True, help="every schema file of the set (JSON or YAML)")
    ap.add_argument("--alias", action="append", default=[], metavar="URI=FILE")
    ap.add_argument("--opaque", action="append", default=[], metavar="URI-PREFIX",
                    help="references under this prefix are not followed (the wire's own structure)")
    ap.add_argument("--message", action="append", required=True, metavar="KIND=FILE[#POINTER]",
                    help="a message of the set; with one message and no --kind-when the pack has no kinds")
    ap.add_argument("--kind-when", action="append", default=[], metavar="KIND:PATH=VALUE")
    ap.add_argument("--when", action="append", default=[], metavar="PATH=VALUE", help="a common `when`")
    ap.add_argument("--map", action="append", default=[], metavar="KIND:PATH=KEY",
                    help="bind the leaf at PATH of KIND (or * for every kind) to a shared key")
    ap.add_argument("--scale", action="append", default=[], metavar="KIND:PATH=iscale:FACTOR[:OFFSET]",
                    help="the line of a --map binding reads the number through this transform "
                         "(engine-spec 0.15), e.g. POSIX seconds to time_ms with iscale:1000")
    ap.add_argument("--wire", choices=("json", "geojson"), default="json")
    ap.add_argument("--top-level-members", metavar="NAME,...",
                    help="geojson: the only top-level members to map (others are residue)")
    ap.add_argument("--format", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--license", required=True, help="the license statement, for source lines and pack.md")
    genio.add_arguments(ap, what="the checkout that receives model/ and packs/")
    ap.add_argument("--model-dir", required=True, help="the checkout's model/ (core.def, track.def, ...)")
    ap.add_argument("--names-file", required=True)
    ap.add_argument("--notes-file", help="hand-written notes placed into pack.md")
    ap.add_argument("--cross", action="append", default=[], metavar="PACKDEF=VECTOR:FIELD[@KEY=VALUE,...]",
                    help="also write a vector from that pack's vector text into this pack, with optional context")
    ap.add_argument("--version", default="0.1.0")
    ap.add_argument("--max-depth", type=int, metavar="N",
                    help="json: objects nested deeper than N levels (arrays count as a level) are not "
                         "mapped; default %d" % MAX_DEPTH)
    ap.add_argument("--max-nest", type=int, metavar="N",
                    help="json: an array inside N arrays is not mapped; default no limit")
    ap.add_argument("--limit-reason", metavar="TEXT",
                    help="why --max-depth or --max-nest is set, for pack.md")
    a = ap.parse_args(argv)
    for opt in ("max_depth", "max_nest"):
        v = getattr(a, opt)
        if v is not None and v < 1:
            raise GenError("--%s must be at least 1" % opt.replace("_", "-"))
    LIMITS["depth"] = a.max_depth if a.max_depth is not None else MAX_DEPTH
    LIMITS["nest"] = a.max_nest

    reg = Registry(a.schema, dict(parse_kv(x, "--alias") for x in a.alias), a.opaque)
    names = Names(a.names_file)
    shared_keys, derives = read_module_keys(a.model_dir)
    KEYS_CACHE.update(shared_keys)
    kinds = []
    for spec in a.message:
        kname, ref = parse_kv(spec, "--message")
        f, _, ptr = ref.partition("#")
        ctx = reg.ctx_for(f)
        schema = ctx.doc
        if ptr:
            schema, ctx = reg.resolve("#" + ptr, ctx)
        notmapped = []
        if a.wire == "json":
            lines = []
            walk_json([(schema, ctx)], reg, [], True, lines, notmapped, 0, frozenset())
        else:
            lines = walk_geojson([(schema, ctx)], reg, notmapped,
                                 a.top_level_members.split(",") if a.top_level_members else None)
        kinds.append({"name": slug(kname), "label": kname, "ref": os.path.relpath(os.path.abspath(f), reg.root) + ("#" + ptr if ptr else ""), "lines": lines,
                      "notmapped": notmapped, "when": [], "maps": []})
    by = {k["label"]: k for k in kinds}
    for spec in a.kind_when:
        kn, rest = spec.split(":", 1)
        path, val = parse_kv(rest, "--kind-when")
        if kn not in by:
            raise GenError("--kind-when names no --message %s" % kn)
        by[kn]["when"].append((path, val))
    # a `when` needs kinds (ruling 8 of 0.5): a common --when gives the one message a kind
    use_kinds = len(kinds) > 1 or any(k["when"] for k in kinds) or bool(a.when)
    if len(kinds) > 1 and not all(k["when"] for k in kinds[:-1]):
        raise GenError("with several messages every kind but the last needs a --kind-when")

    for k in kinds:
        assign(k["lines"], names, a.module, "", a.wire)

    # shared-key bindings
    maps = []
    for spec in a.map:
        kn, rest = spec.split(":", 1)
        path, key = parse_kv(rest, "--map")
        if key not in shared_keys:
            raise GenError("--map %s: %s is not a key of the model" % (spec, key))
        targets = kinds if kn == "*" else [by[kn]] if kn in by else None
        if targets is None:
            raise GenError("--map names no --message %s" % kn)
        for k in targets:
            maps.append((k, path, key))
    bound = []
    for k, path, key in maps:
        if a.wire == "geojson" and path.startswith("geometry."):
            k["maps"].append(("geometry", path, key))
            bound.append((k, path, key, None))
            continue
        leaf = [ln for ln in k["lines"] if isinstance(ln, Leaf) and ".".join(ln.path) == path]
        if not leaf:
            raise GenError("--map %s:%s: no mapped leaf at that path" % (k["label"], path))
        leaf = leaf[0]
        st = shared_keys[key][0]
        leaf.shared = key
        leaf.shared_transform = transform_for(leaf, a.wire, st)
        if MODEL_TYPE[leaf.jtype] != st and not (st == "int" and leaf.shared_transform in ("iso8601_ms", "int")) \
                and not (st == "float" and leaf.jtype == "integer"):
            raise GenError("--map %s:%s: the leaf is %s, the key %s is %s" % (k["label"], path, leaf.jtype, key, st))
        if st == "float" and leaf.jtype == "integer":
            leaf.shared_transform = "float"
        bound.append((k, path, key, leaf))
    for spec in a.scale:
        kn, rest = spec.split(":", 1) if ":" in spec else (spec, "")
        path, tr = parse_kv(rest, "--scale")
        iscale_params(tr)
        hits = [(k, p, key, leaf) for k, p, key, leaf in bound
                if leaf is not None and p == path and (kn == "*" or k["label"] == kn)]
        if not hits:
            raise GenError("--scale %s: no --map binding at that path" % spec)
        for k, p, key, leaf in hits:
            if leaf.jtype not in ("integer", "number"):
                raise GenError("--scale %s: the leaf is %s, not a number" % (spec, leaf.jtype))
            if shared_keys[key][0] != "int":
                raise GenError("--scale %s: iscale yields int, the key %s is %s" % (spec, key, shared_keys[key][0]))
            leaf.shared_transform = tr

    # model module
    module_keys = collections.OrderedDict()
    module_lists = collections.OrderedDict()

    def declare(lines, kind_label, where):
        for ln in lines:
            if isinstance(ln, Leaf):
                name = ln.key.split(".", 1)[1]
                rec = module_keys.setdefault(name, {"type": MODEL_TYPE[ln.jtype], "where": [], "jtype": ln.jtype,
                                                    "format": ln.node.format})
                # the path in backticks, then "of" and the message: never two bare names side by side
                rec["where"].append("`%s` of %s" % (where + (".".join(ln.path) or "."), kind_label))
            else:
                name = ln.list.split(".", 1)[1]
                rec = module_lists.setdefault(name, {"where": []})
                rec["where"].append("`%s` of %s" % (where + ".".join(ln.path), kind_label))
                declare(ln.lines, kind_label, where + ".".join(ln.path) + "[].")
    for k in kinds:
        declare(k["lines"], k["label"], "")
    if len(module_keys) + len(module_lists) > KEY_BUDGET:
        raise GenError("module of %d keys and lists is over the budget" % (len(module_keys) + len(module_lists)))

    # requires: ruling 27 of 0.5 - a kind selected by `when <path> present` requires a key at or under it
    for k in kinds:
        req = []
        for path, val in k["when"]:
            if val == "present":
                under = [ln for ln in walk_leaves(k["lines"]) if ".".join(ln.path) == path or
                         ".".join(ln.path).startswith(path + ".")]
                if not under:
                    raise GenError("kind %s: nothing mapped at or under %s" % (k["label"], path))
                req.append(under[0].key)
        k["requires"] = req

    src_lines = ["%s: %s sha256 %s" % (a.title, b, sha) for (_, b, sha, _, _) in reg.files]
    src_lines.append("License: %s" % a.license)
    src_lines += a.source

    pack_text = write_pack(a, kinds, use_kinds, src_lines)
    module_text = write_module(a, module_keys, module_lists, src_lines)
    pack = Pack(pack_text)

    # vectors
    vectors = []
    for idx, k in enumerate(kinds, 1):
        shared_of = {id(l): key for kk, path, key, l in bound if kk is k and l is not None}
        inst = build_instance(k["lines"], k["name"], 0, shared_of)
        # a `when` value holds in the sample whatever value the sampler chose there
        for path, val in k["when"]:
            if val != "present":
                set_path(inst, path, when_value(val))
        for path, val in [parse_kv(x, "--when") for x in a.when]:
            set_path(inst, path, when_value(val))
        geo = None
        if a.wire == "geojson":
            gm = {p: key for kk, p, key, l in bound if kk is k and l is None}
            if gm:
                geo = {"geometry.lon": -77.0365, "geometry.lat": 38.8977, "geometry.alt": 12.5}
            inst = geo_instance(inst, geo, gm)
        text = canonical_input(pack, inst)
        kind, ent, res = decode(pack, text)
        back = encode(pack, kind, ent, res)
        if back != text:
            raise GenError("self-check: kind %s does not round-trip:\n%s\n%s" % (k["name"], text, back))
        model = collections.OrderedDict()
        if use_kinds:
            model["@kind"] = k["name"]
        for kk, path, key, l in bound:
            if kk is k and key in ent:
                model[key] = model_text(ent[key])
        for key, v in ent.items():
            if len(model) >= 8:
                break
            if isinstance(v, list):
                model[key + ".#"] = str(len(v))
            elif key not in model:
                model[key] = model_text(v)
        vectors.append(("gen-%03d-%s-roundtrip.json" % (idx, k["name"]),
                        collections.OrderedDict([("name", "gen-%s-roundtrip" % k["name"]), ("from", a.format),
                                                 ("to", a.format), ("input", text), ("expect", text),
                                                 ("model", model)])))
        # residue: unmapped content the wire carries back (engine-spec 0.5 json residue;
        # 0.1 and ruling 13 of 0.6 for geojson). The input holds it in schema order;
        # the expected output is the canonical order, worked out here from the rules.
        obj = parse_json(text)
        extra = []
        if a.wire == "geojson":
            for loc, why in k["notmapped"]:
                # only `properties` members: whether top-level members are residue is not
                # settled (the Residue section of 0.1 names `properties` members; ruling 4 of
                # 0.1.1 orders "top-level residue"), so no vector here depends on it
                if not loc.startswith("properties."):
                    continue
                if loc.endswith(".*"):
                    continue
                if "boolean" in why:
                    # a boolean in geojson residue: no ruling says whether it comes back as a
                    # boolean or as text (ruling 13 of 0.6 covers numbers, arrays, objects, null)
                    continue
                v = (["r1", "r2"] if "array" in why else
                     collections.OrderedDict([("r", "1")]) if "object" in why else
                     True if "boolean" in why else "r")
                extra.append((loc, v))
        else:
            extra.append(("x_residue", "r"))
            extra.append(("x_residue_n", 7))
        if extra:
            inp = collections.OrderedDict()
            for kk, vv in obj.items():
                inp[kk] = vv
            for loc, v in extra:
                if loc.startswith("properties."):
                    inp.setdefault("properties", collections.OrderedDict())[loc[11:]] = v
                else:
                    inp[loc] = v
            # the residue goes first in the input, so the output must move it
            if a.wire == "json":
                first = collections.OrderedDict((kk, inp[kk]) for kk, _ in extra)
                for kk, vv in inp.items():
                    if kk not in first:
                        first[kk] = vv
                inp = first
            itext = dump(inp)
            kind, ent2, res2 = decode(pack, itext)
            etext = encode(pack, kind, ent2, res2)
            if a.wire == "json":
                want = parse_json(text)
                for loc, v in extra:
                    want[loc] = v
                if etext != dump(want):
                    raise GenError("self-check: residue of kind %s:\n%s\n%s" % (k["name"], etext, dump(want)))
            vectors.append(("gen-%03d-%s-residue.json" % (idx, k["name"]),
                            collections.OrderedDict([("name", "gen-%s-residue" % k["name"]), ("from", a.format),
                                                     ("to", a.format), ("input", itext), ("expect", etext)])))
    cross = []
    for spec in a.cross:
        cross.append(make_cross(spec, a, pack, kinds, shared_keys, derives))

    # write, through genio: with --check nothing is written and every difference is reported
    out = genio.Output(a.out, check=a.check)
    pdir = "packs/%s" % a.format
    vdir = pdir + "/vectors"
    texts = [(fn, json.dumps(v, indent=1, ensure_ascii=False) + "\n") for fn, v in vectors]
    total = sum(len(t) for _, t in texts)
    if total > VECTOR_BUDGET:
        raise GenError("vectors of %d bytes are over the budget" % total)
    new = {fn for fn, _ in texts}
    for old in out.listdir(vdir):
        if old.startswith("gen-") and old not in new:
            out.remove("%s/%s" % (vdir, old))
    for fn, t in texts:
        out.write("%s/%s" % (vdir, fn), t)
    for other, fn, v, _c, _d in cross:
        out.write("packs/%s/vectors/%s" % (other, fn), json.dumps(v, indent=1, ensure_ascii=False) + "\n")
    out.write(pdir + "/pack.def", pack_text)
    out.write("model/%s.def" % a.module, module_text)
    out.write(pdir + "/pack.md", write_md(a, reg, kinds, bound, module_keys, module_lists, vectors, cross,
                                          use_kinds))
    names_out, names_rel = names_output(a.names_file, out)
    names_out.write(names_rel, names.text())
    if not a.check:
        print(json.dumps({"format": a.format, "kinds": len(kinds), "keys": len(module_keys),
                          "lists": len(module_lists), "bound": len(bound), "vectors": len(vectors),
                          "cross": [c[1] for c in cross],
                          "not_mapped": sum(len(k["notmapped"]) for k in kinds)}, indent=1))
    status = out.report(NAME)
    if names_out is not out:
        status = max(status, names_out.report(NAME + " (names file)"))
    return status


def walk_leaves(lines):
    for ln in lines:
        if isinstance(ln, Leaf):
            yield ln


def model_text(v):
    if isinstance(v, float):
        return fmt_float(v)
    return str(v)


def geo_instance(inst, geo, gm):
    out = collections.OrderedDict()
    out["type"] = "Feature"
    if geo:
        coords = [geo["geometry.lon"], geo["geometry.lat"]]
        if "geometry.alt" in gm:
            coords.append(geo["geometry.alt"])
        out["geometry"] = collections.OrderedDict([("type", "Point"), ("coordinates", coords)])
    else:
        out["geometry"] = None
    out["properties"] = inst.get("properties", collections.OrderedDict())
    for k, v in inst.items():
        if k != "properties":
            out[k] = v
    return out


def canonical_input(pack, inst):
    """The instance as the pack writes it: decode the plain dump, encode."""
    text = dump(inst)
    kind, ent, res = decode(pack, text)
    return encode(pack, kind, ent, res)


def line_for(ln, indent, wire, shared):
    out = []
    loc = ".".join(ln.path) if ln.path else "."
    if getattr(ln, "shared", None):
        out.append("%sfield  %s  %s  %s" % (indent, ln.shared, q(loc), ln.shared_transform))
    out.append("%sfield  %s  %s  %s" % (indent, ln.key, q(loc), ln.transform))
    return out


def q(s):
    return '"%s"' % s if (" " in s or s.startswith("#")) else s


def lines_text(lines, indent, wire):
    out = []
    for ln in lines:
        if isinstance(ln, Leaf):
            out += line_for(ln, indent, wire, None)
        else:
            out.append("%sgroup  %s  %s" % (indent, ln.list, ".".join(ln.path)))
            out += lines_text(ln.lines, indent + "  ", wire)
            out.append("%send" % indent)
    return out


def write_pack(a, kinds, use_kinds, src_lines):
    p = ["# %s. Public. Generated by tools/gen/jsonschema2pack.py; edit the generator," % a.title,
         "# not this file. What is mapped and what is not: pack.md.",
         "format        %s" % a.format,
         "version       %s" % a.version,
         "distribution  public"]
    for s in src_lines:
        p.append('source        "%s"' % s.replace('"', "'"))
    p.append("uses          %s" % a.module)
    p.append("wire          %s" % a.wire)
    for spec in a.when:
        path, val = parse_kv(spec, "--when")
        p.append("when    %s  %s" % (q(path), q(val)))
    for k in kinds:
        if use_kinds:
            p.append("")
            p.append("kind      %s" % k["name"])
            for path, val in k["when"]:
                p.append("when      %s  %s" % (q(path), q(val)))
            if k["requires"]:
                p.append("requires  %s" % " ".join(k["requires"]))
        for kind_, path, key in [m for m in k["maps"] if m[0] == "geometry"]:
            p.append("field  %s  %s  float" % (key, path))
        p += lines_text(k["lines"], "", a.wire)
    return "\n".join(p) + "\n"


def write_module(a, keys, lists, src_lines):
    m = ["# The %s module: raw keys of %s, one per place in a message." % (a.module, a.format),
         "# Generated by tools/gen/jsonschema2pack.py; do not edit by hand.",
         "module        %s" % a.module,
         "version       %s" % a.version,
         "distribution  public"]
    for s in src_lines:
        m.append('source        "%s"' % s.replace('"', "'"))
    for name, rec in keys.items():
        where = rec["where"][0] + ("" if len(rec["where"]) == 1 else " and %d more" % (len(rec["where"]) - 1))
        what = "JSON %s%s" % (rec["jtype"], (", format " + rec["format"]) if rec["format"] else "")
        m.append('key   %s  %s  -  "member %s (%s)"' % (name, rec["type"], where.replace('"', "'"), what))
    for name, rec in lists.items():
        where = rec["where"][0] + ("" if len(rec["where"]) == 1 else " and %d more" % (len(rec["where"]) - 1))
        m.append('list  %s  "array %s, one item per element"' % (name, where.replace('"', "'")))
    return "\n".join(m) + "\n"


def make_cross(spec, a, pack, kinds, shared_keys, derives):
    """A vector from another pack's vector text into this pack. The other pack
    is read with this program's loader: a json or geojson pack of field lines."""
    ctx_part = ""
    if "@" in spec:
        spec, ctx_part = spec.split("@", 1)
    pdef, rest = spec.split("=", 1)
    vpath, field = rest.rsplit(":", 1)
    with open(pdef, encoding="utf-8") as fh:
        other = Pack(fh.read())
    if other.wire not in ("json", "geojson") or other.kinds:
        raise GenError("--cross: %s is not a json or geojson pack without kinds" % pdef)
    with open(vpath, encoding="utf-8") as fh:
        v = json.load(fh)
    text = v[field]
    _, ent, _ = decode(other, text)
    source_keys = list(ent)
    context = collections.OrderedDict()
    for kv in [x for x in ctx_part.split(",") if x]:
        key, val = kv.split("=", 1)
        t = shared_keys.get(key, ("string",))[0] if key in shared_keys else None
        context[key] = val
        if key not in ent:
            ent[key] = int(val) if module_type(key, kinds) == "int" else float(val) \
                if module_type(key, kinds) == "float" else val
    for target, args in derives:
        if target not in ent and all(x in ent for x in args):
            if any(ln[1] == target for ln in all_field_lines(pack)):
                raise GenError("--cross: an engine would derive %s, which this pack writes" % target)
    chosen = None
    for k in pack.kinds or [None]:
        if k is None or all(r in ent for r in k["requires"]):
            chosen = k
            break
    if pack.kinds and chosen is None:
        raise GenError("--cross: no kind's requires hold")
    out = encode(pack, chosen, {kk: vv for kk, vv in ent.items()}, [])
    kind2, back, _ = decode(pack, out)
    carried = [kk for kk in ent if kk in back]
    # `model` is checked against decode(from, input) (spec/vector-format.md): the source
    # entity, so it lists the carried keys as the source pack decodes them
    model = collections.OrderedDict()
    for kk in carried:
        if kk in source_keys:
            model[kk] = model_text(ent[kk])
    vec = collections.OrderedDict([("name", "gen-%s-to-%s" % (other.format, a.format)), ("from", other.format),
                                   ("to", a.format), ("input", text)])
    if context:
        vec["context"] = context
    vec["expect"] = out
    vec["model"] = model
    return other.format, "gen-%s-to-%s.json" % (other.format, a.format), vec, carried, \
        [kk for kk in ent if kk not in back]


def module_type(key, kinds):
    for k in kinds:
        for ln in walk_all(k["lines"]):
            if isinstance(ln, Leaf) and ln.key == key:
                return MODEL_TYPE[ln.jtype]
    return "string"


def walk_all(lines):
    for ln in lines:
        yield ln
        if isinstance(ln, Group):
            for x in walk_all(ln.lines):
                yield x


def all_field_lines(pack):
    def rec(lines):
        for ln in lines:
            if ln[0] == "field":
                yield ln
            else:
                for x in rec(ln[1].lines):
                    yield x
    for x in rec(pack.common["lines"]):
        yield x
    for k in pack.kinds:
        for x in rec(k["lines"]):
            yield x


def write_md(a, reg, kinds, bound, keys, lists, vectors, cross, use_kinds):
    """The text of pack.md."""
    w = []
    w.append("# Pack: %s\n" % a.format)
    w.append("%s, as %s. Generated by `tools/gen/jsonschema2pack.py`. Wire `%s`. Edit the generator, "
             "not this file.\n" % (a.title, "JSON objects" if a.wire == "json" else "GeoJSON Features", a.wire))
    w.append("## Sources\n")
    w.append("| File | Bytes | SHA-256 |\n|---|---|---|")
    for (_, b, sha, size, _) in reg.files:
        w.append("| `%s` | %d | `%s` |" % (b, size, sha))
    w.append("\nLicense: %s\n" % a.license)
    for s in a.source:
        w.append("- %s" % s)
    w.append("")
    w.append("## Messages\n")
    w.append("| Kind | Schema | `when` | Lines | Not mapped |\n|---|---|---|---|---|")
    for k in kinds:
        nlines = sum(1 for _ in walk_all(k["lines"]))
        w.append("| `%s` | `%s` | %s | %d | %d |" % (k["name"], k["ref"],
                                                     ", ".join("`%s %s`" % x for x in k["when"]) or "-",
                                                     nlines, len(k["notmapped"])))
    if not use_kinds:
        w.append("\nOne message, no `when`: the pack has no `kind` lines.")
    w.append("")
    w.append("## How a schema is read\n")
    if a.wire == "json":
        w.append("Each member of a scalar type is a `field` line; members of nested objects have dotted paths.")
        w.append("An array is a `group` (engine-spec 0.7): items that are objects are walked as a message is,")
        w.append("with paths relative to the item; items of a scalar type are one `.` line. `allOf`, `oneOf`")
        w.append("and `anyOf` contribute the members of every branch, merged by name; `null` among the")
        w.append("types means the member may be absent. Types: string `string`, integer `int`, number")
        w.append("`float` (`int` when the schema states `multipleOf: 1`), boolean `bool`. A `date-time`")
        w.append("string is kept as text in its raw key, so it round-trips as written.\n")
        w.append("Residue (engine-spec 0.5): a scalar member no line maps, at any depth of nested objects, is")
        w.append("carried back; arrays no group maps, and anything inside them, are not.\n")
        if a.max_depth is not None or a.max_nest is not None:
            lim = []
            if a.max_depth is not None:
                lim.append("objects nested deeper than %d levels (an array counts as a level) are not mapped"
                           % a.max_depth)
            if a.max_nest is not None:
                lim.append("an array inside %d arrays is not mapped" % a.max_nest)
            w.append("Limits of this pack: %s%s. Such a place is in the table under Not mapped;" % (
                "; ".join(lim), (" (%s)" % a.limit_reason.rstrip(".")) if a.limit_reason else ""))
            w.append("outside an array its scalars are residue and round-trip, inside an array they are dropped.\n")
    else:
        w.append("The message is one GeoJSON Feature. The wire addresses the Point coordinates, top-level")
        w.append("members and one level of `properties`; so scalar members there are `field` lines and")
        w.append("everything else (nested objects, arrays, booleans) is residue, which the geojson wire")
        w.append("carries back as it was (engine-spec 0.1, ruling 13 of 0.6).\n")
    w.append("## Mapped to shared keys\n")
    if bound:
        w.append("| Kind | Path | Key | Schema type | Evidence (the schema's own text) |\n|---|---|---|---|---|")
        for k, path, key, leaf in bound:
            if leaf is None:
                w.append("| `%s` | `%s` | `%s` | Point coordinate | see the notes below |" % (k["name"], path, key))
            else:
                ev = " / ".join('"%s"' % d for d in leaf.node.descs[:2]) or "see the notes below"
                w.append("| `%s` | `%s` | `%s` (%s, %s) | %s%s | %s |" % (
                    k["name"], path, key, KEYS_CACHE.get(key, ("?", "?"))[0], KEYS_CACHE.get(key, ("?", "?"))[1],
                    leaf.jtype, ((", " + leaf.node.format) if leaf.node.format else "") +
                    ((", read with `%s`" % leaf.shared_transform)
                     if str(getattr(leaf, "shared_transform", "")).startswith("iscale:") else ""),
                    ev.replace("|", "\\|")))
        w.append("\nEach bound path also has its raw key on a second line (ruling 16 of 0.5): the shared")
        w.append("key first, so encode writes the shared value when the entity has it.\n")
    else:
        w.append("None.\n")
    if a.notes_file:
        with open(a.notes_file, encoding="utf-8") as fh:
            w.append(fh.read().rstrip() + "\n")
    w.append("## Not mapped\n")
    reasons = collections.Counter(why for k in kinds for _, why in k["notmapped"])
    if reasons:
        w.append("| Reason | Places |\n|---|---|")
        for why, c in reasons.most_common():
            w.append("| %s | %d |" % (why, c))
        w.append("")
        w.append("| Kind | Place | Reason |\n|---|---|---|")
        for k in kinds:
            for loc, why in k["notmapped"]:
                w.append("| `%s` | `%s` | %s |" % (k["name"], loc, why))
    else:
        w.append("Nothing.")
    w.append("")
    w.append("## Keys and lists\n")
    w.append("Module `%s`: %d keys, %d lists. A key is named by its path (`a.b` is `a_b`; inside a list, the" %
             (a.module, len(keys), len(lists)))
    w.append("list name comes first). Names are pinned in `tools/gen/names/%s`: a later run keeps every"
             % os.path.basename(a.names_file))
    w.append("existing name and only adds new ones.\n")
    w.append("## Vectors\n")
    w.append("One same-format round trip per kind, computed by the generator's own json codec (no engine):")
    w.append("every mapped place holds a value, an array has two items (one inside an item), the input is")
    w.append("canonical, so the expected output is the input.")
    for other, fn, v, carried, dropped in cross:
        w.append("\n`packs/%s/vectors/%s`: from the input of an existing hand-written `%s` vector. Carried: %s."
                 " Not carried: %s.%s" % (other, fn, other, ", ".join("`%s`" % x for x in carried) or "none",
                                          ", ".join("`%s`" % x for x in dropped) or "none",
                                          (" Context: %s." % ", ".join("`%s`" % x for x in v.get("context", {})))
                                          if v.get("context") else ""))
    w.append("")
    return "\n".join(w) + "\n"


KEYS_CACHE = {}

if __name__ == "__main__":
    sys.exit(main())
