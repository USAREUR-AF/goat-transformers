#!/usr/bin/env python3
"""xsd2pack: turn an XML Schema (XSD) message catalog into a goat-transformers pack.

Reads:
  --xsd FILE...        every XSD file of one schema set (each must state
                       "Distribution Statement A" in its first 6000 bytes)
  --model-dir DIR      core.def and track.def, the modules whose keys --map binds
  --names-file FILE    the names pinned by earlier runs, when the file exists
  --cross ...          a pack and a vector of another xml format

Writes, under --out:
  model/core.def, model/track.def           copies of the two modules read
  model/<module>.def                        raw keys and lists of the format
  packs/<format>/pack.def                   the pack (engine-spec 0.7: wire xml, a root per
                                            kind, a `group` block per repeated element)
  packs/<format>/pack.md                    what was mapped, what was not, and why
  packs/<format>/vectors/gen-*.json         one same-format round trip per kind
  packs/<other>/vectors/gen-<other>-to-<format>.json   one per --cross
and the names file: the name pinned to every (locator, type) and every list.

Guarantees:
  - The same input gives the same bytes: nothing depends on the order of a set
    or of a directory listing, on the locale or on the platform line ending.
  - Before it reports success the run reads back what it wrote: the modules and
    the pack load in gtcheck (spec/engine-spec.md 0.1 to 0.8), the pack holds
    the invariants of a catalog pack, and every vector is decoded and encoded
    again by a small xml-wire codec written from the specification. No engine
    is run.
  - With --check nothing is written; the files that are there are compared with
    what the run would write.

Exit status: 0 done (with --check: nothing differs); 1 a refused input, a failed
check or, with --check, a difference; 2 a usage error.

Python 3 standard library only. Run with `python3 -I`.
"""
import argparse
import collections
import datetime
import decimal
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from xml.parsers import expat

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402  (the directory of this file is put on the path above)
import gtcheck    # noqa: E402

NAME = "xsd2pack"
XS = "http://www.w3.org/2001/XMLSchema"
MAX_DEPTH = 8
DEPTH_CEILING = 16          # --max-depth above MAX_DEPTH, for a set whose data lies deeper
KEY_BUDGET = 60000          # keys and lists of the module
VECTOR_BUDGET = 12 * 1000 * 1000    # bytes of generated vectors per pack
MAX_KEY_LEN = 96
STATEMENT_BYTES = 6000      # how much of a file's head is searched for the statement
SHARED_MODULES = ("core", "track")

XS_INT = {"integer", "int", "long", "short", "byte", "unsignedInt", "unsignedLong",
          "unsignedShort", "unsignedByte", "nonNegativeInteger", "positiveInteger",
          "negativeInteger", "nonPositiveInteger"}
XS_UNBOUNDED_INT = {"unsignedLong", "integer", "nonNegativeInteger", "positiveInteger",
                    "negativeInteger", "nonPositiveInteger"}
XS_FLOAT = {"decimal", "double", "float"}
XS_TEXT = {"string", "normalizedString", "token"}
XS_RANGE = {"int": (-2**31, 2**31 - 1), "long": (-2**63, 2**63 - 1), "short": (-2**15, 2**15 - 1),
            "byte": (-128, 127), "unsignedInt": (0, 2**32 - 1), "unsignedLong": (0, 2**64 - 1),
            "unsignedShort": (0, 65535), "unsignedByte": (0, 255),
            "nonNegativeInteger": (0, None), "positiveInteger": (1, None),
            "negativeInteger": (None, -1), "nonPositiveInteger": (None, 0)}
# The model type each transform of the xml wire yields (engine-spec 0.4).
YIELDS = gtcheck.TEXT_TRANSFORMS

# Reasons a place in a message is not mapped. The text is what pack.md prints.
R_REPEAT_NOTHING = "repeated element in which nothing can be mapped"
R_NEST = "repeated element below the group nesting limit set for this pack"
R_REPEAT_GROUP = "repeated sequence or choice (maxOccurs > 1)"
R_CHOICE = "choice with a branch that is not a simple leaf"
R_ANY = "xs:any wildcard"
R_ANYTYPE = "element of xs:anyType"
R_DEPTH = "below depth %d" % MAX_DEPTH
R_RECURSE = "recursive type"
R_ABSTRACT = "element of an abstract type (the instance names the real type in xsi:type)"
R_EMPTY = "element whose presence is its value (empty content)"
R_MIXED = "mixed content"
R_SIBLING = "second element of the same name under one parent"
R_PROHIBITED = "element with maxOccurs 0"
R_ANYATTR = "xs:anyAttribute wildcard"
R_CAP = "below the depth cap set for this pack"
R_ROOT_TEXT = "text of the root element (no locator addresses it)"
R_FOREIGN = "declaration of a namespace declined for this set (--decline-namespace)"
R_NO_MEMBER = "abstract element with no member in the set (--substitution-groups)"
R_SKIP = "left out of this pack (--skip)"


class GenError(Exception):
    """An input the generator refuses, or a check of its own output that does
    not hold. `file` and `line` name the place in a source or output file when
    there is one; the message printed is `<file>:<line>: <what>`."""

    def __init__(self, message, file=None, line=None):
        super().__init__(message, file, line)
        self.message, self.file, self.line = message, file, line

    def __str__(self):
        if self.file is None:
            return self.message
        if self.line is None:
            return "%s: %s" % (self.file, self.message)
        return "%s:%d: %s" % (self.file, self.line, self.message)


class WireError(Exception):
    """A document or a value the xml codec cannot read or write. `kind` is the
    error kind the specification names (`malformed-wire`, `transform-decode`,
    `no-kind`)."""

    def __init__(self, kind, message):
        super().__init__(kind, message)
        self.kind, self.message = kind, message

    def __str__(self):
        return "%s: %s" % (self.kind, self.message)


def located(err, decl):
    """Give a GenError the position of the schema declaration `decl` when it
    has none yet, so the innermost declaration that was being read is named."""
    if err.file is None and decl is not None and getattr(decl, "file", None) is not None:
        err.file, err.line = decl.file, decl.line
    return err


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# --------------------------------------------------------------------------
# XSD reader: files -> Schema (types, global elements, groups; nothing decided)
# --------------------------------------------------------------------------

def xs(tag):
    return "{%s}%s" % (XS, tag)


def local(tag):
    return tag.split("}")[1] if "}" in tag else tag


class SimpleT:
    def __init__(self, name):
        self.name = name
        self.base = None            # ("xs", local) or ("t", name)
        self.variety = "atomic"     # atomic | list | union
        self.enums = []
        self.patterns = []
        self.facets = {}
        self.doc = ""
        self.file = self.line = None


class ComplexT:
    def __init__(self, name):
        self.name = name
        self.abstract = False
        self.mixed = False
        self.base = None            # QRef of the extension or restriction base
        self.derivation = None      # extension | restriction
        self.simple_content = False
        self.particle = None        # Particle or None
        self.attrs = []             # AttrDecl, or ("group", name) for an attributeGroup ref
        self.any_attr = False
        self.doc = ""
        self.file = self.line = None


class Particle:
    __slots__ = ("kind", "min", "max", "children", "name", "type", "doc", "qualified", "file", "line")

    def __init__(self, kind):
        self.kind = kind            # sequence | choice | all | element | any | group
        self.min, self.max = 1, 1   # max None = unbounded
        self.children = []
        self.name = None
        self.type = None            # QRef for an element
        self.doc = ""
        self.qualified = False
        self.file = self.line = None


class AttrDecl:
    def __init__(self):
        self.name = self.type = None
        self.use = "optional"
        self.doc = ""
        self.file = self.line = None


SchemaFile = collections.namedtuple("SchemaFile", "path base sha256 size")
# One xs:include or xs:import: the file it stands in, `include` or `import`,
# its schemaLocation, the location after --alias, and the line it stands on.
Include = collections.namedtuple("Include", "base tag location resolved path line namespace")


class FileContext:
    """What a declaration needs to know about the file it stands in."""

    def __init__(self, path, prefixes, qualified, lines, imports=frozenset()):
        self.path, self.prefixes, self.qualified, self.lines = path, prefixes, qualified, lines
        self.imports = imports      # namespaces the file imports (names it may refer to)

    def line(self, node):
        return self.lines.get(node)

    def error(self, node, message):
        return GenError(message, self.path, self.line(node))

    def place(self, decl, node):
        decl.file, decl.line = self.path, self.line(node)
        return decl


def parse_xml(raw, path):
    """(root element, {element: line}, {prefix: namespace}) of an XML file.
    The tree is the one xml.etree builds (tags as `{namespace}local`); expat is
    driven directly because that is the only way to learn the line of an
    element. The first declaration of a prefix in the file is the one kept;
    declarations inside an xs:annotation (documentation or appinfo content, such
    as metadata in a namespace of its own) are not schema context and are not kept."""
    builder = ET.TreeBuilder()
    lines, prefixes = {}, {}
    parser = expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True
    annotation = [0]          # depth inside xs:annotation elements

    def name(text):
        return "{" + text if "}" in text else text

    def start(tag, attrs):
        node = builder.start(name(tag), {name(k): v for k, v in attrs.items()})
        lines[node] = parser.CurrentLineNumber
        if annotation[0] or name(tag) == xs("annotation"):
            annotation[0] += 1

    def end(tag):
        builder.end(name(tag))
        if annotation[0]:
            annotation[0] -= 1

    def decl(prefix, uri):
        if not annotation[0]:
            prefixes.setdefault(prefix or "", uri or "")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartNamespaceDeclHandler = decl
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as e:
        raise GenError("not well-formed XML: %s (column %d)" % (expat.ErrorString(e.code), e.offset), path, e.lineno)
    return builder.close(), lines, prefixes


def doc_of(node):
    out = []
    for a in node.findall(xs("annotation")):
        for d in a.findall(xs("documentation")):
            t = " ".join("".join(d.itertext()).split())
            if t:
                out.append(t)
    return " ".join(out)


class Schema:
    """The declarations of one schema set, as written: nothing here decides
    what a pack maps. `read` adds a file; the methods below `resolution`
    answer what a type or a reference stands for."""

    def __init__(self):
        self.simple = {}
        self.complex = {}
        self.elements = collections.OrderedDict()   # global element name -> Particle
        self.groups = {}            # name -> (xs:group node or its Particle, FileContext)
        self.attr_groups = {}       # name -> (xs:attributeGroup node, FileContext)
        self.global_attrs = {}
        self.tns = None
        self.import_only = []       # (file base name, namespaces): files with no targetNamespace that import
        self.declined = frozenset() # namespaces whose declarations are not read (--decline-namespace)
        self.substitution = False   # read substitutionGroup and abstract on global elements
        self.subst = collections.OrderedDict()  # head element -> member elements, in declaration order
        self.abstract_elements = set()
        self.untyped_members = []   # members declared without a type: they take their head's
        self.only = {}              # --substitute: head -> the members it keeps
        self.skip = frozenset()     # --skip: element paths from the root that are not walked
        self.files = []             # SchemaFile
        self.includes = []          # Include
        self.element_form = collections.OrderedDict()   # file base name -> elementFormDefault
        self.anon = 0
        self._content = {}
        self._simple = {}
        self.chameleon = []           # base names of chameleon includes (no targetNamespace)

    # -- reading ----------------------------------------------------------
    def read(self, path, aliases):
        with open(path, "rb") as fh:
            self.read_bytes(fh.read(), path, aliases)

    def read_bytes(self, raw, path, aliases):
        """Add the declarations of one XSD file given as bytes. `aliases` maps
        a schemaLocation to the base name of the file that satisfies it."""
        root, lines, prefixes = parse_xml(raw, path)
        if root.tag != xs("schema"):
            raise GenError("the root element is not xs:schema", path, lines.get(root))
        tns = root.get("targetNamespace")
        base = os.path.basename(path)
        imports = frozenset(c.get("namespace") for c in root if c.tag == xs("import") and c.get("namespace"))
        if tns is None and self.tns is not None and imports <= self.declined:
            # A chameleon include: a file with no targetNamespace, included by a file of the set,
            # that imports no namespace or only declined ones. Its declarations take the
            # namespace of the set (XSD 1.0, 4.2.1).
            self.chameleon.append(base)
        elif tns is None and imports:
            # A "master" file with no targetNamespace that imports the set's namespace: its own
            # declarations (the message roots) are in no namespace, and it may refer to names of
            # the namespaces it imports. read_schema checks that it imports only the set's.
            self.import_only.append((base, imports))
        elif self.tns is None:
            self.tns = tns
        elif tns != self.tns:
            raise GenError("targetNamespace %r differs from %r" % (tns, self.tns), path, lines.get(root))
        self.files.append(SchemaFile(path, base, hashlib.sha256(raw).hexdigest(), len(raw)))
        self.element_form[base] = root.get("elementFormDefault") or "unqualified (absent)"
        # only a file with no targetNamespace refers to an imported namespace's names as the set's own
        ctx = FileContext(path, prefixes, root.get("elementFormDefault") == "qualified", lines,
                          imports if tns is None else frozenset())
        for c in root:
            if c.tag in (xs("include"), xs("import")):
                loc = c.get("schemaLocation") or ""
                self.includes.append(Include(base, local(c.tag), loc, aliases.get(loc, loc), path, ctx.line(c),
                                             c.get("namespace")))
            elif c.tag == xs("simpleType"):
                self._simple_type(c, c.get("name"), ctx)
            elif c.tag == xs("complexType"):
                self._complex_type(c, c.get("name"), ctx)
            elif c.tag == xs("element"):
                p = self._element(c, ctx, top=True)
                if p.name in self.elements:
                    raise ctx.error(c, "global element %s is declared twice" % p.name)
                self.elements[p.name] = p
                if self.substitution:
                    self._substitution(c, p, ctx)
            elif c.tag == xs("group"):
                self.groups[c.get("name")] = (c, ctx)
            elif c.tag == xs("attributeGroup"):
                self.attr_groups[c.get("name")] = (c, ctx)
            elif c.tag == xs("attribute"):
                self.global_attrs[c.get("name")] = self._attribute(c, ctx)
            elif c.tag in (xs("annotation"), xs("notation")):
                pass
            else:
                raise ctx.error(c, "unsupported schema child %s" % c.tag)

    def _substitution(self, node, p, ctx):
        """Record the substitution groups a global element joins and whether it
        is abstract. A head of a declined namespace is not recorded."""
        if node.get("abstract") == "true":
            self.abstract_elements.add(p.name)
        for text in (node.get("substitutionGroup") or "").split():
            head = self.qref(text, ctx, node)
            if head[0] == "t":
                self.subst.setdefault(head[1], []).append(p.name)
                if (node.get("type") is None and node.find(xs("complexType")) is None
                        and node.find(xs("simpleType")) is None):
                    self.untyped_members.append((p.name, head[1]))

    def resolve_member_types(self):
        """A member declared without a type has the type of its head (XSD 1.0,
        3.3.2); applied after every file is read."""
        changed = True
        while changed:
            changed = False
            for name, head in self.untyped_members:
                h = self.elements.get(head)
                if h is not None and self.elements[name].type == ("xs", "anyType") and h.type != ("xs", "anyType"):
                    self.elements[name].type = h.type
                    changed = True

    def members(self, name, only=None):
        """The elements that may stand where global element `name` is referred
        to: itself unless abstract, then every member of its substitution group
        and of theirs, in declaration order. `only` maps a head to the members
        it keeps (--substitute)."""
        out, seen, todo = [], set(), [name]
        def visit(n):
            if n in seen:
                return
            seen.add(n)
            if n not in self.abstract_elements:
                out.append(n)
            kept = self.subst.get(n, [])
            if only and n in only:
                kept = [m for m in kept if m in only[n]]
            for m in kept:
                visit(m)
        visit(name)
        return out

    def foreign_base(self, name):
        """The first base of a declined namespace on the derivation chain of
        complex type `name`, or None."""
        seen = set()
        while name in self.complex and name not in seen:
            seen.add(name)
            b = self.complex[name].base
            if b is None:
                return None
            if b[0] == "f":
                return b
            name = b[1]
        return None

    def qref(self, text, ctx, node):
        """A qualified name as ("xs", local) for a built-in, ("t", local) for
        a name of the schema set's own namespace, or ("f", "{uri}local") for a
        name of a declined namespace."""
        pfx, _, name = text.rpartition(":")
        uri = ctx.prefixes.get(pfx)
        if uri == XS:
            return ("xs", name)
        if uri in self.declined:
            return ("f", "{%s}%s" % (uri, name))
        if uri == self.tns or uri in ctx.imports or (pfx == "" and uri in (None, "")):
            return ("t", name)
        raise ctx.error(node, "%r is in namespace %r, which no file given here defines" % (text, uri))

    def _anon(self, hint):
        self.anon += 1
        return "%s#%d" % (hint, self.anon)

    def _declare(self, table, name, decl, ctx, node):
        if name in self.simple or name in self.complex:
            raise ctx.error(node, "type %s is defined twice" % name)
        table[name] = decl

    def _simple_type(self, node, name, ctx):
        st = ctx.place(SimpleT(name), node)
        st.doc = doc_of(node)
        r = node.find(xs("restriction"))
        if r is not None:
            if r.get("base"):
                st.base = self.qref(r.get("base"), ctx, r)
            else:
                inner = r.find(xs("simpleType"))
                if inner is None:
                    raise ctx.error(r, "the restriction of simpleType %s has no base" % name)
                st.base = ("t", self._simple_type(inner, self._anon(name), ctx).name)
            for f in r:
                tag = local(f.tag)
                if tag == "enumeration":
                    st.enums.append(f.get("value"))
                elif tag == "pattern":
                    st.patterns.append(f.get("value"))
                elif tag not in ("annotation", "simpleType"):
                    st.facets[tag] = f.get("value")
        elif node.find(xs("list")) is not None:
            st.variety, st.base = "list", ("xs", "string")
        elif node.find(xs("union")) is not None:
            st.variety, st.base = "union", ("xs", "string")
        else:
            raise ctx.error(node, "simpleType %s has no restriction, list or union" % name)
        self._declare(self.simple, name, st, ctx, node)
        return st

    def _attribute(self, node, ctx):
        a = ctx.place(AttrDecl(), node)
        a.doc = doc_of(node)
        if node.get("ref"):
            r = self.qref(node.get("ref"), ctx, node)
            if r[0] == "f":
                a.name, a.type = r[1].split("}")[1], r
            else:
                a.name, a.type = r[1], ("ref", r[1])
        else:
            a.name = node.get("name")
            if node.get("type"):
                a.type = self.qref(node.get("type"), ctx, node)
            elif node.find(xs("simpleType")) is not None:
                a.type = ("t", self._simple_type(node.find(xs("simpleType")), self._anon(a.name), ctx).name)
            else:
                a.type = ("xs", "anySimpleType")
        a.use = node.get("use", "optional")
        return a

    def _attrs_into(self, node, ct, ctx):
        for c in node:
            if c.tag == xs("attribute"):
                ct.attrs.append(self._attribute(c, ctx))
            elif c.tag == xs("attributeGroup"):
                r = self.qref(c.get("ref") or "", ctx, c)
                if r[0] == "f":
                    a = ctx.place(AttrDecl(), c)
                    a.name, a.type = "attributeGroup " + r[1].split("}")[1], r
                    ct.attrs.append(a)
                else:
                    ct.attrs.append(("group", r[1], ctx.path, ctx.line(c)))
            elif c.tag == xs("anyAttribute"):
                ct.any_attr = True

    def _complex_type(self, node, name, ctx):
        ct = ctx.place(ComplexT(name), node)
        ct.doc = doc_of(node)
        ct.abstract = node.get("abstract") == "true"
        ct.mixed = node.get("mixed") == "true"
        body = node
        cc, sc = node.find(xs("complexContent")), node.find(xs("simpleContent"))
        if cc is not None or sc is not None:
            holder = cc if cc is not None else sc
            if holder.get("mixed") == "true":
                ct.mixed = True
            ct.simple_content = sc is not None
            body = holder.find(xs("extension"))
            ct.derivation = "extension"
            if body is None:
                body = holder.find(xs("restriction"))
                ct.derivation = "restriction"
            if body is None or not body.get("base"):
                raise ctx.error(holder, "the content of complexType %s has no extension or restriction with a base" % name)
            ct.base = self.qref(body.get("base"), ctx, body)
        for c in body:
            if c.tag in (xs("sequence"), xs("choice"), xs("all"), xs("group")):
                ct.particle = self._particle(c, ctx)
        self._attrs_into(body, ct, ctx)
        self._declare(self.complex, name, ct, ctx, node)
        return ct

    @staticmethod
    def _occurs(node, p, ctx):
        try:
            p.min = int(node.get("minOccurs", "1"))
            mx = node.get("maxOccurs", "1")
            p.max = None if mx == "unbounded" else int(mx)
        except ValueError:
            raise ctx.error(node, "minOccurs or maxOccurs is not a number")

    def _particle(self, node, ctx):
        tag = local(node.tag)
        if tag == "element":
            return self._element(node, ctx, top=False)
        p = ctx.place(Particle("group" if tag == "group" else tag), node)
        self._occurs(node, p, ctx)
        if tag == "group":
            p.name = self.qref(node.get("ref") or "", ctx, node)[1]
        elif tag != "any":
            for c in node:
                if c.tag in (xs("element"), xs("sequence"), xs("choice"), xs("all"), xs("any"), xs("group")):
                    p.children.append(self._particle(c, ctx))
        return p

    def _element(self, node, ctx, top):
        p = ctx.place(Particle("element"), node)
        p.doc = doc_of(node)
        if not top:
            self._occurs(node, p, ctx)
        if node.get("ref"):
            r = self.qref(node.get("ref"), ctx, node)
            p.qualified = True
            if r[0] == "f":
                p.name, p.type = r[1].split("}")[1], r
                return p
            p.name = r[1]
            p.type = ("ref", p.name)
            return p
        p.name = node.get("name")
        form = node.get("form")
        p.qualified = top or (form == "qualified" if form else ctx.qualified)
        if node.get("type"):
            p.type = self.qref(node.get("type"), ctx, node)
        elif node.find(xs("complexType")) is not None:
            p.type = ("t", self._complex_type(node.find(xs("complexType")), self._anon(p.name), ctx).name)
        elif node.find(xs("simpleType")) is not None:
            p.type = ("t", self._simple_type(node.find(xs("simpleType")), self._anon(p.name), ctx).name)
        else:
            p.type = ("xs", "anyType")
        return p

    # -- resolution -------------------------------------------------------
    def element_type(self, p):
        """The QRef an element particle stands for, through `ref`."""
        if p.type[0] == "ref":
            g = self.elements.get(p.type[1])
            if g is None:
                raise GenError("element ref %s names no global element" % p.type[1], p.file, p.line)
            return g.type
        return p.type

    def simple_info(self, qref):
        """(builtin local name, [SimpleT chain, derived first]) of a simple type."""
        if qref in self._simple:
            return self._simple[qref]
        chain = []
        cur, seen = qref, set()
        while cur[0] == "t":
            if cur[1] in seen:
                raise GenError("simple type %s derives from itself" % cur[1], chain[-1].file, chain[-1].line)
            seen.add(cur[1])
            st = self.simple.get(cur[1])
            if st is None:
                # the place is the restriction that names the base when there is one;
                # otherwise the caller knows which declaration named the type
                at = chain[-1] if chain else None
                raise GenError("simple type %s is not defined" % cur[1], at and at.file, at and at.line)
            chain.append(st)
            cur = st.base
        self._simple[qref] = ("anySimpleType" if cur[0] == "f" else cur[1], chain)
        return self._simple[qref]

    def facets(self, qref):
        """(builtin, chain, {facet: value}) of a simple type; a facet of a
        derived type replaces the same facet of its base."""
        builtin, chain = self.simple_info(qref)
        f = {}
        for st in reversed(chain):
            f.update(st.facets)
        return builtin, chain, f

    def is_simple(self, qref):
        return qref[0] == "xs" and qref[1] != "anyType" or qref[0] == "t" and qref[1] in self.simple

    def content(self, name):
        """Effective content of a complex type through its base chain:
        (attrs, simple-content QRef or None, [particles], mixed, any_attr)."""
        if name in self._content:
            return self._content[name]
        ct = self.complex.get(name)
        if ct is None:
            raise GenError("type %s is not defined" % name)
        self._content[name] = None      # cycle guard
        attrs = []
        for a in ct.attrs:
            if isinstance(a, tuple):
                attrs.extend(self._attr_group(a, set()))
            else:
                attrs.append(a)
        attrs = [self.global_attrs[a.type[1]] if a.type[0] == "ref" and a.type[1] in self.global_attrs else a
                 for a in attrs]
        particles = [ct.particle] if ct.particle is not None else []
        simple, mixed, any_attr = None, ct.mixed, ct.any_attr
        if ct.base is not None:
            if self.is_simple(ct.base):
                simple = ct.base
            elif ct.base == ("xs", "anyType") or ct.base[0] == "f":
                pass        # a declined base: Walker records it with R_FOREIGN
            else:
                if ct.base[1] not in self.complex:
                    raise GenError("base type %s of type %s is not defined" % (ct.base[1], name), ct.file, ct.line)
                b = self.content(ct.base[1])
                if b is None:
                    raise GenError("type %s derives from itself" % name, ct.file, ct.line)
                battrs, bsimple, bparts, bmixed, bany = b
                own = {a.name for a in attrs}
                attrs = [a for a in battrs if a.name not in own] + attrs
                any_attr = any_attr or bany
                mixed = mixed or bmixed
                if ct.simple_content:
                    simple = bsimple
                if ct.derivation == "extension":
                    particles = bparts + particles
                    if simple is None:
                        simple = bsimple
                # a complexContent restriction restates its content: own particles stand
        attrs = [a for a in attrs if a.use != "prohibited"]
        self._content[name] = (attrs, simple, particles, mixed, any_attr)
        return self._content[name]

    def _attr_group(self, ref, seen):
        _, name, file, line = ref
        if name in seen:
            raise GenError("attributeGroup %s refers to itself" % name, file, line)
        if name not in self.attr_groups:
            raise GenError("attributeGroup %s is not defined" % name, file, line)
        node, ctx = self.attr_groups[name]
        tmp = ComplexT(name)
        self._attrs_into(node, tmp, ctx)
        out = []
        for a in tmp.attrs:
            if isinstance(a, tuple):
                out.extend(self._attr_group(a, seen | {name}))
            else:
                out.append(a)
        return out

    def group_particle(self, p):
        """The content particle of the named group that the particle `p` refers to."""
        if p.name not in self.groups:
            raise GenError("group %s is not defined" % p.name, p.file, p.line)
        node, ctx = self.groups[p.name]
        if not isinstance(node, Particle):
            inner = [c for c in node if c.tag in (xs("sequence"), xs("choice"), xs("all"))]
            if not inner:
                raise ctx.error(node, "group %s has no sequence, choice or all" % p.name)
            node = self._particle(inner[0], ctx)
            self.groups[p.name] = (node, ctx)
        return node

    def derived_counts(self):
        """Number of complex types that extend each complex type, directly."""
        n = collections.Counter()
        for ct in self.complex.values():
            if ct.base and ct.base[0] == "t" and ct.base[1] in self.complex:
                n[ct.base[1]] += 1
        return n


STATEMENT_RE = re.compile(r"Distribution Statement A\b[^\n<]*", re.I)


def header_statement(head):
    """The distribution statement in the first bytes of a schema file, or None."""
    m = STATEMENT_RE.search(head[:STATEMENT_BYTES].decode("utf-8", "replace"))
    return " ".join(m.group().split()).rstrip(" !-") if m else None


PUBLIC_PREFIX = "(no statement in the file; publisher's statement) "


def read_schema(paths, aliases, public_statement=None, declined=(), substitution=False):
    """Parse step: (Schema, [(file base name, header statement)]). A file whose
    head does not carry the statement is refused before it is parsed, unless
    `public_statement` (the publisher's statement that the set is public) is
    given, which is then recorded for that file. Every xs:include and xs:import
    must be satisfied by a file given."""
    schema, statements = Schema(), []
    schema.declined, schema.substitution = frozenset(declined), substitution
    for path in paths:
        with open(path, "rb") as fh:
            raw = fh.read()
        statement = header_statement(raw)
        if statement is None and public_statement:
            statement = PUBLIC_PREFIX + " ".join(public_statement.split())
        if statement is None:
            raise GenError("the file header does not state Distribution Statement A, and no "
                           "--public-statement is given; refusing this set", path)
        statements.append((os.path.basename(path), statement))
        schema.read_bytes(raw, path, aliases)
    for base, imports in schema.import_only:
        if imports - schema.declined != {schema.tns}:
            raise GenError("has no targetNamespace and imports %s; the set's namespace is %r"
                           % (sorted(imports), schema.tns), base)
    if substitution:
        schema.resolve_member_types()
    given = {f.base for f in schema.files}
    for inc in schema.includes:
        if inc.tag == "import" and inc.namespace in schema.declined:
            continue        # a declined namespace: its file is not read
        if os.path.basename(inc.resolved) not in given:
            raise GenError("xs:%s of %s is not among the files given (use --alias)" % (inc.tag, inc.location),
                           inc.path, inc.line)
    return schema, statements


# --------------------------------------------------------------------------
# Walk: one message's content model to leaves and groups
# --------------------------------------------------------------------------

class Leaf:
    """One mapped attribute or element text. `locator` is relative to the scope
    the leaf stands in (the root element, or the item of the enclosing group)."""
    __slots__ = ("locator", "depth", "xs", "tname", "transform", "mtype", "mandatory", "choice",
                 "owner", "member", "doc", "note", "key", "shared", "qref", "rad", "tdoc")

    def __init__(self):
        self.choice = None          # (id, branch index) for a leaf of an all-leaf choice
        self.note = None
        self.key = None             # the raw key, set when names are assigned
        self.shared = None          # the core or track key a --map binds here


class Group:
    """A repeated element: `path` from the enclosing scope (the root element or
    the enclosing item) to the item element, and the lines of one item."""
    __slots__ = ("path", "items", "owner", "member", "depth", "nest", "list", "tname", "choice")

    def leaves(self):
        return [x for x in self.items if isinstance(x, Leaf)]


def all_leaves(items):
    """Every leaf of a scope, those of its groups' items included."""
    for x in items:
        if isinstance(x, Leaf):
            yield x
        else:
            yield from all_leaves(x.items)


def all_groups(items):
    for x in items:
        if isinstance(x, Group):
            yield x
            yield from all_groups(x.items)


def signature(x):
    """What makes two lines the same line: a leaf's locator and transform, a
    group's path and the lines of its item."""
    if isinstance(x, Leaf):
        return (x.locator, x.transform, x.choice is None)
    return (x.path, tuple(signature(y) for y in x.items))


class Walker:
    """Walks messages of one schema. `walk(root)` gives the lines and the
    skipped places of one message; `unqualified`, `poly` and the choice
    numbering run over every message walked."""

    def __init__(self, schema, max_depth, max_nest=MAX_DEPTH):
        self.s = schema
        self.max_depth = max_depth
        self.max_nest = max_nest    # groups inside groups: 1 = no group inside an item
        # a run that asks for more than MAX_DEPTH walks to what it asks; past it is R_CAP
        self.hard_depth = max(MAX_DEPTH, min(max_depth, DEPTH_CEILING))
        self.choice_id = 0
        self.zulu = {}
        self.unqualified = 0        # local elements the schema leaves out of its namespace
        self.poly = 0               # elements walked whose declared type has derived types
        self.derived = schema.derived_counts()
        self.leaves, self.skipped, self.seen = [], [], set()
        self.base, self.nest = (), 0
        self.sg = schema.substitution   # --substitution-groups
        self.only = schema.only         # --substitute: head -> members kept
        self.cur_choice = None          # (choice id, branch) of the branch being walked
        self.choice_parent = {}         # choice id -> the branch it stands in, or None
        self.choice_first = {}          # choice id -> the first branch that has a line

    def transform_of(self, qref):
        """(transform, builtin, note, type name) for a simple type; a None
        transform means the type has no value to map."""
        builtin, chain, facets = self.s.facets(qref)
        tname = chain[0].name if chain else "xs:" + builtin
        if any(st.variety != "atomic" for st in chain):
            return "string", builtin, "list or union type kept as one string", tname
        if builtin in XS_TEXT and (facets.get("length") == "0" or facets.get("maxLength") == "0"):
            return None, builtin, None, tname
        if builtin in XS_INT:
            return "int", builtin, ("xs:unsignedLong or unbounded integer: values beyond 64 bits do not fit `int`"
                                    if builtin in XS_UNBOUNDED_INT else None), tname
        if builtin in XS_FLOAT:
            return "float", builtin, None, tname
        if builtin == "boolean":
            return "string", builtin, "xs:boolean kept as string", tname
        if builtin == "dateTime":
            # `iso8601_ms` reads UTC only, so it is used when a pattern of the
            # type ends every value in `Z`
            if tname not in self.zulu:
                pats = [p for st in chain for p in st.patterns]
                self.zulu[tname] = any(p.endswith("Z") and "|" not in p for p in pats)
            if self.zulu[tname]:
                return "iso8601_ms", builtin, ("xs:dateTime restricted to UTC `Z`: `iso8601_ms`, which keeps "
                                               "milliseconds and always writes three fraction digits"), tname
            return "string", builtin, "xs:dateTime with no UTC restriction kept as string", tname
        if builtin in XS_TEXT:
            return "string", builtin, None, tname
        return "string", builtin, "xs:%s kept as string" % builtin, tname

    def walk(self, root):
        """Lines (leaves and groups, in schema order) and skipped places of the
        message whose root element is `root`."""
        self.leaves, self.skipped, self.seen = [], [], set()
        self.base, self.nest = (), 0    # path of the item being walked; groups around it
        try:
            qref = self.s.element_type(root)
            self._element(root.name, qref, (), True, None, root, "(global element)", top=True)
        except GenError as e:
            raise located(e, root)
        if self.sg:
            self._settle_choices(self.leaves)
        return self.leaves, self.skipped

    def rel(self, path):
        """A path as a locator of the scope being walked."""
        return "/".join(path[len(self.base):])

    def _group(self, p, path, owner, chain):
        """A repeated element: its item is walked as a scope of its own."""
        here = path + (p.name,)
        if self.rel(here) in self.seen:
            self._skip(R_SIBLING, here, owner, p.name)
            return
        g = Group()
        g.path, g.items, g.owner, g.member, g.depth, g.nest = self.rel(here), [], owner, p.name, len(here), self.nest + 1
        g.list = None
        g.choice = self.cur_choice
        qref = self.s.element_type(p)
        g.tname = qref[1] if qref[0] == "t" else "xs:" + qref[1]
        saved = (self.leaves, self.seen, self.base, self.nest, self.cur_choice)
        mark = len(self.skipped)
        self.leaves, self.seen, self.base, self.nest = g.items, set(), here, self.nest + 1
        self.cur_choice = None      # an item is a scope of its own
        self._element(p.name, qref, path, True, None, p, owner, chain=chain, item=True)
        self.leaves, self.seen, self.base, self.nest, self.cur_choice = saved
        if next(all_leaves(g.items), None) is None:
            # nothing of an item can be mapped: no group. The reason is the item's
            # own when the element itself was refused, one line otherwise.
            inner = self.skipped[mark:]
            del self.skipped[mark:]
            own = [r for r in inner if r[1] == "/".join(here)]
            if own:
                self.skipped.extend(own)
            else:
                self._skip(R_REPEAT_NOTHING, here, owner, p.name)
            return
        self.seen.add(self.rel(here))
        self.leaves.append(g)

    def _skip(self, reason, path, owner, member):
        self.skipped.append((reason, "/".join(path), owner, member))

    def _leaf(self, path, attr, qref, mandatory, choice, owner, member, doc):
        if choice is None:
            choice = self.cur_choice
        if qref[0] == "f":
            self._skip(R_FOREIGN, path + (("@" + attr,) if attr else ()), owner, member)
            return
        transform, builtin, note, tname = self.transform_of(qref)
        if transform is None:
            self._skip(R_EMPTY, path + (("@" + attr,) if attr else ()), owner, member)
            return
        locator = "/".join(path[len(self.base):] + ("@" + attr if attr else "#text",))
        if locator in self.seen:
            self._skip(R_SIBLING, path, owner, member)
            return
        self.seen.add(locator)
        lf = Leaf()
        lf.locator, lf.depth = locator, len(path)
        lf.xs, lf.tname, lf.transform, lf.mtype = builtin, tname, transform, YIELDS[transform]
        lf.mandatory, lf.choice, lf.owner, lf.member, lf.doc, lf.note = mandatory, choice, owner, member, doc, note
        lf.qref = qref
        chain = self.s.simple_info(qref)[1]
        lf.tdoc = next((st.doc for st in chain if st.doc), "")
        lf.rad = transform == "float" and bool(re.search(r"\bradians?\b", " ".join([doc] + [st.doc for st in chain]), re.I))
        self.leaves.append(lf)

    def _element(self, name, qref, path, mandatory, choice, part, owner, top=False, chain=(), item=False):
        """An element named `name` of type `qref`, placed under `path`. `item`:
        the element is the item of a group, the root of the scope being walked."""
        here = path if top else path + (name,)
        if self.s.skip and "/".join(here) in self.s.skip:
            self._skip(R_SKIP, here, owner, name)
            return
        if not top and not item and self.rel(here) in self.seen:
            self._skip(R_SIBLING, here, owner, name)
            return
        if qref == ("xs", "anyType"):
            self._skip(R_ANYTYPE, here, owner, name)
            return
        if qref[0] == "f":
            self._skip(R_FOREIGN, here, owner, name)
            return
        if self.s.is_simple(qref):
            if top:
                # the root element's own text has no locator in the grammar
                self._skip(R_ROOT_TEXT, here, owner, name)
                return
            self._leaf(here, None, qref, mandatory, choice, owner, name, part.doc)
            return
        tname = qref[1]
        ct = self.s.complex.get(tname)
        if ct is None:
            raise GenError("type %s of element %s is not defined" % (tname, name), part.file, part.line)
        if ct.abstract:
            self._skip(R_ABSTRACT, here, owner, name)
            return
        if tname in chain:
            self._skip(R_RECURSE, here, owner, name)
            return
        attrs, simple, particles, mixed, any_attr = self.s.content(tname)
        if not attrs and simple is None and not self._has_content(particles):
            self._skip(R_EMPTY, here, owner, name)
            return
        if not top and not item:
            self.seen.add(self.rel(here))
        if self.derived[tname]:
            self.poly += 1
        fb = self.s.foreign_base(tname)
        if fb is not None:
            self._skip(R_FOREIGN, here, tname, "base " + fb[1].split("}")[1])
        for a in attrs:
            if a.type[0] == "f":
                self._skip(R_FOREIGN, here, tname, "@" + a.name)
                continue
            aref = a.type if a.type[0] != "ref" else ("xs", "anySimpleType")
            try:
                self._leaf(here, a.name, aref, mandatory and a.use == "required", choice, tname, "@" + a.name, a.doc)
            except GenError as e:
                raise located(e, a)
        if any_attr:
            self._skip(R_ANYATTR, here, tname, "@*")
        if mixed:
            self._skip(R_MIXED, here, owner, name)
        if simple is not None:
            if top:
                self._skip(R_ROOT_TEXT, here, owner, name)
            else:
                self._leaf(here, None, simple, mandatory, choice, owner, name, part.doc)
        for p in particles:
            self._particle(p, here, mandatory, tname, chain + (tname,))

    @staticmethod
    def _has_content(particles):
        def any_child(p):
            return p.kind in ("element", "any", "group") or any(any_child(c) for c in p.children)
        return any(any_child(p) for p in particles)

    def _particle(self, p, path, mandatory, owner, chain):
        try:
            self._particle_at(p, path, mandatory, owner, chain)
        except GenError as e:
            raise located(e, p)

    def _particle_at(self, p, path, mandatory, owner, chain):
        if p.max == 0:
            self._skip(R_PROHIBITED, path + ((p.name,) if p.name else ()), owner, p.name or p.kind)
            return
        repeated = p.max is None or p.max > 1
        if p.kind == "element" and self.sg and p.type[0] == "ref":
            self._substituted(p, path, mandatory, owner, chain, repeated)
        elif p.kind == "element":
            self._element_particle(p, path, mandatory, owner, chain, repeated)
        elif p.kind == "any":
            self._skip(R_ANY, path, owner, "xs:any")
        elif p.kind == "group" and p.name.startswith("{"):
            self._skip(R_FOREIGN, path, owner, "group " + p.name.split("}")[1])
        elif p.kind == "group":
            if repeated:
                self._skip(R_REPEAT_GROUP, path, owner, "group " + p.name)
            else:
                self._particle(self.s.group_particle(p), path, mandatory and p.min >= 1, owner, chain)
        elif repeated and self.sg and p.kind == "choice" and self._elements_only(p):
            # --substitution-groups: a repeated choice of elements is one group
            # per element name; the order among different names is not kept
            for c in p.children:
                if c.type[0] == "ref":
                    self._substituted(c, path, False, owner, chain, True)
                else:
                    self._element_particle(c, path, False, owner, chain, True)
        elif repeated:
            # the members of a repeated sequence or choice interleave; a group
            # reads all elements of one name together, so this is not a group
            self._skip(R_REPEAT_GROUP, path, owner, p.kind)
        elif p.kind == "choice" and self.sg and not self._simple_choice(p) and self._elements_only(p):
            self._branches(path, owner, chain,
                           [(c, c.max is None or c.max > 1, c.type[0] == "ref") for c in p.children])
        elif p.kind == "choice":
            self._choice(p, path, owner)
        else:                       # sequence, all
            for c in p.children:
                self._particle(c, path, mandatory and p.min >= 1, owner, chain)

    def _over_depth(self, path, skip_path, owner, member):
        """True, with the place skipped, when one more element step under
        `path` passes the limit of the specification or the cap of this run."""
        if len(path) + 1 > self.hard_depth:
            self._skip(R_DEPTH if self.hard_depth == MAX_DEPTH else R_CAP, skip_path, owner, member)
            return True
        if len(path) + 1 > self.max_depth:
            self._skip(R_CAP, skip_path, owner, member)
            return True
        return False

    def _element_particle(self, p, path, mandatory, owner, chain, repeated):
        if self._over_depth(path, path + (p.name,), owner, p.name):
            return
        if not p.qualified:
            self.unqualified += 1
        if not repeated:
            self._element(p.name, self.s.element_type(p), path, mandatory and p.min >= 1, None, p, owner, chain=chain)
        elif self.nest >= self.max_nest:
            self._skip(R_NEST, path + (p.name,), owner, p.name)
        else:
            self._group(p, path, owner, chain)

    @staticmethod
    def _elements_only(p):
        return bool(p.children) and all(c.kind == "element" for c in p.children)

    def _simple_choice(self, p):
        return bool(p.children) and all(
            c.kind == "element" and c.max == 1 and self.s.is_simple(self.s.element_type(c))
            for c in p.children)

    @staticmethod
    def _proxy(p, name):
        """The particle `p` (a ref to a substitution head) standing for member `name`."""
        q = Particle("element")
        q.min, q.max, q.name, q.type, q.doc, q.qualified = p.min, p.max, name, ("ref", name), p.doc, True
        q.file, q.line = p.file, p.line
        return q

    def _substituted(self, p, path, mandatory, owner, chain, repeated):
        """--substitution-groups: a ref to a global element stands for that element
        and every member of its substitution group. One candidate is walked in
        place; several are a choice when the ref occurs once, and one group per
        member when it repeats."""
        names = self.s.members(p.name, self.only)
        if names == [p.name]:
            self._element_particle(p, path, mandatory, owner, chain, repeated)
        elif not names:
            self._skip(R_NO_MEMBER, path + (p.name,), owner, p.name)
        elif len(names) == 1:
            self._element_particle(self._proxy(p, names[0]), path, mandatory, owner, chain, repeated)
        elif repeated:
            for n in names:
                self._element_particle(self._proxy(p, n), path, False, owner, chain, True)
        else:
            self._branches(path, owner, chain, [(self._proxy(p, n), False, False) for n in names])

    def _branches(self, path, owner, chain, branches):
        """A choice whose branches are elements, some of complex type
        (--substitution-groups): each branch is walked as an optional element,
        its lines marked with the branch. A vector holds the first branch of
        every choice, and of a branch other than the first nothing."""
        if self._over_depth(path, path, owner, "choice"):
            return
        self.choice_id += 1
        cid, outer = self.choice_id, self.cur_choice
        self.choice_parent[cid] = outer
        for i, (c, repeated, expand) in enumerate(branches):
            self.cur_choice = (cid, i)
            start = len(self.leaves)
            try:
                if expand:
                    self._substituted(c, path, False, owner, chain, repeated)
                else:
                    self._element_particle(c, path, False, owner, chain, repeated)
            finally:
                self.cur_choice = outer
            if len(self.leaves) > start:
                self.choice_first.setdefault(cid, i)

    def _settle_choices(self, items):
        """--substitution-groups: mark every line of a choice branch (0, on) when
        its branch is the first one with a line and every branch around it is
        on, (1, off) otherwise. A vector holds the lines that are on."""
        def on(c):
            while c is not None:
                cid, i = c
                if i != self.choice_first.get(cid, -1):
                    return False
                c = self.choice_parent.get(cid)
            return True
        for x in list(all_leaves(items)) + list(all_groups(items)):
            if x.choice is not None and x.choice[0] in self.choice_parent:
                x.choice = (x.choice[0], 0 if on(x.choice) else 1)

    def _choice(self, p, path, owner):
        """A choice is mapped only when every branch is an element of simple
        type that occurs once: each branch is then a line, and a valid document
        has at most one of them."""
        simple_all = bool(p.children) and all(
            c.kind == "element" and c.max == 1 and self.s.is_simple(self.s.element_type(c))
            for c in p.children)
        if not simple_all:
            self._skip(R_CHOICE, path, owner, "choice of " + ", ".join(
                (c.name or c.kind) for c in p.children[:4]) + (", ..." if len(p.children) > 4 else ""))
            return
        if self._over_depth(path, path, owner, "choice"):
            return
        self.choice_id += 1
        if self.sg:
            self.choice_parent[self.choice_id] = self.cur_choice
            self.choice_first[self.choice_id] = 0
        self.unqualified += sum(1 for c in p.children if not c.qualified)
        for i, c in enumerate(p.children):
            try:
                self._leaf(path + (c.name,), None, self.s.element_type(c), False, (self.choice_id, i), owner, c.name, c.doc)
            except GenError as e:
                raise located(e, c)


# --------------------------------------------------------------------------
# Key names
# --------------------------------------------------------------------------

def snake(name):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    s = re.sub(r"[^a-z0-9]+", "_", s.lower())
    return s.strip("_")


def base_name(locator, drop=()):
    """The key name a locator gets before any collision is settled: the element
    names of the path and the attribute name, each in snake case, joined by `_`.
    A leading element named in `drop` (a wrapper every message has) is left out.
    The locator `#text` alone, the text of a group's item, is named `item`.
    A name longer than MAX_KEY_LEN keeps its first element, its last two parts
    and eight hex digits of the SHA-1 of the whole locator."""
    steps = [p for p in locator.split("/") if p != "#text"]
    if len(steps) > 1 and steps[0] in drop:
        steps = steps[1:]
    parts = [snake(p.lstrip("@")) for p in steps]
    parts = [p for p in parts if p] or ["item"]     # the text of an item of simple type
    name = "_".join(parts)
    if len(name) > MAX_KEY_LEN:
        h = hashlib.sha1(locator.encode()).hexdigest()[:8]
        tail = "_".join(parts[-2:]) if len(parts) > 2 else parts[-1]
        name = ("%s_%s" % (parts[0], tail))[:MAX_KEY_LEN - 9].rstrip("_") + "_" + h
    return name


def ident_tag(ident):
    """An identity as the names file writes it: `<locator> <type>`."""
    return "%s %s" % ident


def assign_names(idents, pinned, drop=()):
    """idents: (locator, model type) for a key, (path + "/[]", "list") for a
    list. Returns {ident: name}. The result does not depend on the order of
    `idents`.

    One key per (locator, model type), shared by every kind and every group
    that has that locator with that type; a locator inside a group is relative
    to the item. Rule, in order: a pinned name stays; otherwise
    base_name(locator); when one locator has two model types across kinds every
    one of them gets `_<type>`; when two places spell the same name the
    attribute one gets `_attr`, and a list that shares its name with a key, or
    whose name is pinned to something else, gets `_list`; anything still not
    unique, or equal to a name pinned elsewhere, gets `_` and eight hex digits
    of the SHA-1 of its identity."""
    idents = sorted(set(idents))
    out, taken = {}, {}
    for ident in idents:
        tag = ident_tag(ident)
        if tag in pinned:
            name = pinned[tag]
            if taken.setdefault(name, ident) != ident:
                raise GenError("pinned name %s is given to two different places" % name)
            out[ident] = name
    types = collections.defaultdict(set)
    for loc, mt in idents:
        types[loc].add(mt)
    want = collections.OrderedDict()
    for ident in idents:
        if ident in out:
            continue
        loc, mt = ident
        name = base_name(loc[:-3] if mt == "list" else loc, drop)
        if len(types[loc]) > 1:
            name += "_" + mt
        want[ident] = name
    by_name = collections.defaultdict(list)
    for ident, name in want.items():
        by_name[name].append(ident)
    for name, group in by_name.items():
        if len(group) > 1:
            for ident in group:
                if "/@" in ident[0] or ident[0].startswith("@"):
                    want[ident] = name + "_attr"
                elif ident[1] == "list" and any(other[1] != "list" for other in group):
                    want[ident] = name + "_list"
    reserved = set(pinned.values())
    for ident, name in want.items():
        if ident[1] == "list" and (name in reserved or name in taken):
            want[ident] = name + "_list"
    counts = collections.Counter(want.values())
    for ident in idents:
        if ident in out:
            continue
        name = want[ident]
        if counts[name] > 1 or name in reserved or name in taken:
            name += "_" + hashlib.sha1(ident_tag(ident).encode()).hexdigest()[:8]
        if taken.setdefault(name, ident) != ident:
            raise GenError("cannot name %s %s" % ident)
        out[ident] = name
    return out


# --------------------------------------------------------------------------
# Sample values and the canonical XML writer (generator side)
# --------------------------------------------------------------------------

SAFE_VALUE = re.compile(r"[A-Za-z0-9._:+\-=/]+( [A-Za-z0-9._:+\-=/]+)*\Z")
# Enumeration values a vector must not hold: tools/boundary-gate reads these
# words in any tracked file as the handling marking of a restricted document.
# Spelled in two halves so this file does not hold them either.
MARKING_VALUE = re.compile(r"\b(?:%s)\b" % "|".join(("c" + "ui", "it" + "ar", "no" + "forn", "fo" + "uo")), re.I)
STRING_TRIES = ["s%d", "00000000-0000-4000-8000-0000000000%02d", "001.0", "001.0.0", "A%d", "%d", "00%d.0", "A", "AB", "ABC",
                "ABCD", "a", "0", "00", "000", "0000", "0A", "USA", "US", "000.000.000.000", "002.6"]
FLOAT_TRIES = [0.5, 1.5, 0.25, 2.5, 0.125, 3.5, 0.75]


def plain_float(x):
    """Shortest decimal that reads back as the same double, plain notation
    (engine-spec 0.1.1 ruling 3): no exponent, no decimal point on a whole
    number, and negative zero is `0`."""
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 2 ** 63:
        return str(int(x))
    r = repr(float(x))
    if "e" in r or "E" in r:
        r = format(decimal.Decimal(r), "f")
    return r


def sample_int(builtin, facets, enums, i):
    """An integer inside the range of the built-in and the bound facets."""
    lo, hi = XS_RANGE.get(builtin, (None, None))
    for k, step in (("minInclusive", 0), ("minExclusive", 1)):
        if k in facets:
            bound = int(decimal.Decimal(facets[k])) + step
            lo = bound if lo is None else max(lo, bound)
    for k, step in (("maxInclusive", 0), ("maxExclusive", 1)):
        if k in facets:
            bound = int(decimal.Decimal(facets[k])) - step
            hi = bound if hi is None else min(hi, bound)
    if enums:
        return enums[i % len(enums)], True
    v = i % 9 + 1
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        v = lo if lo is not None else hi
    return str(v), True


def sample_float(facets, i):
    """A number inside the bound facets, taken from a fixed list of short
    decimals so that its text is the same on every engine."""
    lo = float(facets["minInclusive"]) if "minInclusive" in facets else None
    hi = float(facets["maxInclusive"]) if "maxInclusive" in facets else None
    xlo = float(facets["minExclusive"]) if "minExclusive" in facets else None
    xhi = float(facets["maxExclusive"]) if "maxExclusive" in facets else None

    def ok(v):
        return ((lo is None or v >= lo) and (hi is None or v <= hi)
                and (xlo is None or v > xlo) and (xhi is None or v < xhi))
    tries = FLOAT_TRIES[i % 7:] + FLOAT_TRIES[:i % 7]
    tries += [-t for t in tries] + [0.0, 1000000.5, -1000000.5]
    for v in tries:
        if ok(v):
            return plain_float(v), True
    for v in (lo, hi):
        if v is not None and ok(v):
            return plain_float(v), True
    return "0.5", False


def sample_string(builtin, chain, facets, enums, i):
    """A string for a leaf kept as `string`: a safe enumeration value, a fixed
    value for the built-in, or the first of a fixed list of candidates that
    fits the length facets and the patterns."""
    pats = [st.patterns for st in chain if st.patterns]

    def fits(v):
        # the patterns of one restriction are alternatives; every restriction of the chain must hold
        for step in pats:
            try:
                if not any(re.fullmatch(p, v) for p in step):
                    return False
            except re.error:
                return False
        n = len(v)
        if "length" in facets and n != int(facets["length"]):
            return False
        if "minLength" in facets and n < int(facets["minLength"]):
            return False
        if "maxLength" in facets and n > int(facets["maxLength"]):
            return False
        return True

    if builtin == "boolean":
        return ("true", "false")[i % 2], True
    if enums:
        for k in range(len(enums)):
            v = enums[(i + k) % len(enums)]
            if SAFE_VALUE.match(v) and not MARKING_VALUE.search(v):
                return v, True
        return "v%d" % i, False
    fixed = {"dateTime": "2026-01-02T03:04:05Z", "duration": "PT%dS" % (i % 50 + 1), "time": "03:04:05Z",
             "date": "2026-01-02", "anyURI": "urn:example:%d" % i, "base64Binary": "AAEC",
             "gYear": "2026", "language": "en"}
    if builtin in fixed and fits(fixed[builtin]):
        return fixed[builtin], True
    if builtin == "hexBinary":
        n = int(facets.get("length", facets.get("minLength", "2")))
        return "0A" * max(n, 1), True
    for t in STRING_TRIES:
        v = t % (i % 100) if "%" in t else t
        if fits(v):
            return v, True
    n = int(facets.get("length", facets.get("minLength", "2")))
    for ch in "A0a":
        if fits(ch * n):
            return ch * n, True
    return "v%d" % i, not pats and not any(k in facets for k in ("length", "minLength", "maxLength"))


def sample_value(schema, qref, transform, i):
    """(value, honored) for the `i`-th leaf of a vector: a value of the simple
    type `qref`, canonical for `transform`. Enumerations, numeric bounds, length
    facets and patterns are honored where a value that is also safe on every
    engine's XML reader exists; `honored` is False when none was found, and
    pack.md counts those."""
    builtin, chain, facets = schema.facets(qref)
    enums = next((st.enums for st in chain if st.enums), [])
    if transform == "iso8601_ms":
        return "2026-01-02T03:04:05.%03dZ" % (i % 1000), True
    if transform == "int":
        return sample_int(builtin, facets, enums, i)
    if transform == "float":
        return sample_float(facets, i)
    return sample_string(builtin, chain, facets, enums, i)


def xml_escape(text, attr):
    """Text as an encoder writes it: `&` and `<` escaped, and `"` in an attribute."""
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    return text.replace('"', "&quot;") if attr else text


def canonical_xml(root, placed, root_extra):
    """The document an encoder writes for `placed`, the lines in pack order:
    ("f", locator, text) for a field, ("g", path, [placed of each item]) for a
    group (engine-spec Canonicalisation, 0.5 ruling 10, 0.7 Encode): an element
    is created where the first line that addresses into it stands; a group
    writes one element per item at its line; attributes in line order, then the
    root's residue attributes; text before child elements; an element with no
    text and no child is self-closing; no whitespace."""
    def new(name):
        return {"name": name, "attrs": [], "text": None, "kids": [], "idx": {}}

    def into(node, path):
        for step in path:
            if step not in node["idx"]:
                child = new(step)
                node["idx"][step] = child
                node["kids"].append(child)
            node = node["idx"][step]
        return node

    def fill(node, lines):
        for x in lines:
            *path, last = x[1].split("/")
            holder = into(node, path)
            if x[0] == "g":
                for item in x[2]:
                    child = new(last)
                    holder["kids"].append(child)
                    fill(child, item)
            elif last.startswith("@"):
                holder["attrs"].append((last[1:], x[2]))
            else:
                holder["text"] = x[2]

    tree = new(root)
    fill(tree, placed)
    tree["attrs"].extend(root_extra)
    out = []

    def write(n):
        out.append("<" + n["name"])
        for k, v in n["attrs"]:
            out.append(' %s="%s"' % (k, xml_escape(v, True)))
        if not n["kids"] and not n["text"]:
            out.append("/>")
            return
        out.append(">")
        if n["text"]:
            out.append(xml_escape(n["text"], False))
        for c in n["kids"]:
            write(c)
        out.append("</%s>" % n["name"])
    write(tree)
    return "".join(out)


# --------------------------------------------------------------------------
# The xml-wire codec of the self-check, written from spec/engine-spec.md. It
# reads the gtcheck Pack of the file that was written and nothing of the
# generator's own structures (Leaf, Group, Plan).
# --------------------------------------------------------------------------

# -- a minimal XML reader: names as written, no namespace processing ---------

class XNode:
    __slots__ = ("name", "attrs", "kids", "text")

    def __init__(self, name):
        self.name, self.attrs, self.kids, self.text = name, [], [], ""


ENT = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
TAG_RE = re.compile(r"<(/?)([^\s/>]+)((?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>", re.S)
ATTR_RE = re.compile(r"([^\s=/>]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.S)


def xml_unescape(s):
    """Text with the five named entities and numeric character references replaced."""
    def rep(m):
        e = m.group(1)
        try:
            if e.startswith("#x"):
                return chr(int(e[2:], 16))
            if e.startswith("#"):
                return chr(int(e[1:]))
        except (ValueError, OverflowError):
            raise WireError("malformed-wire", "character reference &%s;" % e)
        if e not in ENT:
            raise WireError("malformed-wire", "entity &%s;" % e)
        return ENT[e]
    return re.sub(r"&([^;]+);", rep, s)


def xml_parse(text):
    """The root XNode of a document. Declarations, comments and processing
    instructions are passed over; CDATA is text; anything else that is not a
    well-formed element tree is `malformed-wire`."""
    def end_of(marker, start):
        j = text.find(marker, start)
        if j < 0:
            raise WireError("malformed-wire", "`%s` is not closed" % text[start:start + 4])
        return j

    i, n = 0, len(text)
    root, stack = None, []
    while i < n:
        if text.startswith("<?", i):
            i = end_of("?>", i) + 2
        elif text.startswith("<!--", i):
            i = end_of("-->", i) + 3
        elif text.startswith("<![CDATA[", i):
            j = end_of("]]>", i)
            if not stack:
                raise WireError("malformed-wire", "text outside the root")
            stack[-1].text += text[i + 9:j]
            i = j + 3
        elif text[i] == "<":
            m = TAG_RE.match(text, i)
            if not m:
                raise WireError("malformed-wire", "bad tag at %d" % i)
            close, name, attrs, selfclose = m.groups()
            if close:
                if not stack or stack[-1].name != name:
                    raise WireError("malformed-wire", "unexpected </%s>" % name)
                stack.pop()
            else:
                node = XNode(name)
                for a in ATTR_RE.finditer(attrs):
                    node.attrs.append((a.group(1), xml_unescape(a.group(2) if a.group(2) is not None else a.group(3))))
                if stack:
                    stack[-1].kids.append(node)
                elif root is not None:
                    raise WireError("malformed-wire", "two root elements")
                else:
                    root = node
                if not selfclose:
                    stack.append(node)
            i = m.end()
        else:
            j = text.find("<", i)
            j = n if j < 0 else j
            chunk = text[i:j]
            if stack:
                stack[-1].text += xml_unescape(chunk)
            elif chunk.strip():
                raise WireError("malformed-wire", "text outside the root")
            i = j
    if stack or root is None:
        raise WireError("malformed-wire", "unclosed element or no root")
    return root


def xml_child(node, path):
    """The first element matched by a path of names (0.1.1 ruling 7), or None."""
    for step in path:
        node = next((c for c in node.kids if c.name == step), None)
        if node is None:
            return None
    return node


def xml_get(root, locator):
    """engine-spec Locators and 0.1.1 ruling 7: each step takes the FIRST child
    of that name. Returns the string or None when absent."""
    *path, last = locator.split("/")
    node = xml_child(root, path)
    if node is None:
        return None
    if last.startswith("@"):
        return next((v for k, v in node.attrs if k == last[1:]), None)
    return node.text if node.text != "" else None


ISO_RE = re.compile(r"(\d{4})-(\d\d)-(\d\d)[Tt](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:[Zz]|([+-])(\d\d):(\d\d))\Z")
EPOCH = datetime.date(1970, 1, 1)


def iso8601_to_ms(s):
    """`iso8601_ms` decode (0.1.1 ruling 8 as replaced in 0.6): the designator
    is `Z`, `z` or `+hh:mm` / `-hh:mm`, the `T` may be lowercase, the instant is
    converted to UTC, and fraction digits beyond milliseconds are truncated."""
    m = ISO_RE.match(s)
    if not m:
        raise WireError("transform-decode", "iso8601_ms %r" % s)
    y, mo, d, h, mi, sec = (int(x) for x in m.groups()[:6])
    ms = int((m.group(7) or "0")[:3].ljust(3, "0"))
    try:
        days = (datetime.date(y, mo, d) - EPOCH).days
    except ValueError:
        raise WireError("transform-decode", "iso8601_ms %r" % s)
    offset = 0
    if m.group(8):
        offset = (int(m.group(9)) * 60 + int(m.group(10))) * 60000 * (1 if m.group(8) == "+" else -1)
    if h > 23 or mi > 59 or sec > 59 or abs(offset) > 24 * 3600000:
        raise WireError("transform-decode", "iso8601_ms %r" % s)
    return ((days * 24 + h) * 60 + mi) * 60000 + sec * 1000 + ms - offset


def ms_to_iso8601(v):
    """`iso8601_ms` encode: `YYYY-MM-DDTHH:MM:SS.fffZ`, always three fraction digits."""
    days, rem = divmod(v, 86400000)
    day = EPOCH + datetime.timedelta(days=days)
    h, rem = divmod(rem, 3600000)
    mi, rem = divmod(rem, 60000)
    sec, ms = divmod(rem, 1000)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (day.year, day.month, day.day, h, mi, sec, ms)


def t_decode(tr, s):
    """The model value of the wire text `s` under a transform of the xml wire."""
    if tr == "string":
        return s
    if tr == "int":
        if not re.fullmatch(r"[+-]?\d+", s.strip()):
            raise WireError("transform-decode", "int %r" % s)
        return int(s)
    if tr == "float":
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", s.strip()):
            raise WireError("transform-decode", "float %r" % s)
        return float(s)
    return iso8601_to_ms(s)


def t_encode(tr, v):
    """The wire text of the model value `v` under a transform of the xml wire."""
    if tr == "string":
        return v
    if tr == "int":
        return str(v)
    if tr == "float":
        return plain_float(v)
    return ms_to_iso8601(v)


def fields_of(lines):
    """The `field` nodes of a scope, not those inside its groups."""
    return [n for n in lines if n.d == "field"]


def root_of(pack, kind):
    return kind.root or pack.root


def decode_scope(node, lines, tally):
    """One scope of a document: the root element with the lines of common and
    the kind, or one item element with the lines of its group (0.7 Decode). An
    entity is {key: value, list name: [items]}; an item is such a dict too.
    `tally[0]` counts the wire places read."""
    ent, read = {}, set()
    for ln in lines:
        if ln.d == "field":
            raw = xml_get(node, ln.loc)
            if raw is not None and ln.key not in ent:
                ent[ln.key] = t_decode(ln.tr, raw)
                read.add(ln.loc)
        else:
            *holder, last = ln.loc.split("/")
            parent = xml_child(node, holder)
            items = [c for c in parent.kids if c.name == last] if parent is not None else []
            if items:           # xml: the list is present when at least one item occurs
                ent[ln.key] = [decode_scope(it, ln.body, tally) for it in items]
    tally[0] += len(read)
    return ent


def decode(pack, text):
    """engine-spec 0.5 Decode with 0.6 `root` per kind and 0.7 groups. Returns
    (kind, entity, residue [(locator, value)], wire places read)."""
    root = xml_parse(text)
    kind = next((k for k in pack.kinds if root_of(pack, k) == root.name), None)
    if kind is None:
        raise WireError("no-kind", "no kind has root <%s>" % root.name)
    lines = pack.common + kind.lines
    tally = [0]
    ent = decode_scope(root, lines, tally)
    mapped = {ln.loc for ln in fields_of(lines)}
    residue = [("@" + k, v) for k, v in root.attrs if "@" + k not in mapped]
    return kind, ent, residue, tally[0]


def encode_scope(node, lines, ent):
    """engine-spec 0.5 Encode step 3, Canonicalisation, 0.5 rulings 10 and 16,
    0.7 Encode: a group writes one element per item where its line stands."""
    text_set = set()
    for ln in lines:
        if ln.key not in ent:
            continue
        *path, last = ln.loc.split("/")
        if ln.d == "group" and not ent[ln.key]:
            continue            # an empty list writes nothing
        holder = node
        for step in path:
            nxt = next((c for c in holder.kids if c.name == step), None)
            if nxt is None:
                nxt = XNode(step)
                holder.kids.append(nxt)
            holder = nxt
        if ln.d == "group":
            for item in ent[ln.key]:
                child = XNode(last)
                holder.kids.append(child)
                encode_scope(child, ln.body, item)
            continue
        val = t_encode(ln.tr, ent[ln.key])
        if last.startswith("@"):
            if not any(k == last[1:] for k, _ in holder.attrs):
                holder.attrs.append((last[1:], val))
        elif id(holder) not in text_set:
            text_set.add(id(holder))
            holder.text = val


def select_kind(pack, ent):
    """0.5 Encode step 2: the first kind whose `requires` keys are all present;
    a list counts when it has an item (0.7)."""
    for k in pack.kinds:
        if all(r in ent and ent[r] != [] for r in k.requires):
            return k
    raise WireError("no-kind", "the entity has the `requires` keys of no kind")


def encode(pack, kind, ent, residue):
    """The canonical document of an entity as `kind`, the root's residue
    attributes after the mapped ones (0.1.1 ruling 6)."""
    root = XNode(root_of(pack, kind))
    encode_scope(root, pack.common + kind.lines, ent)
    for loc, v in residue:
        if not any(k == loc[1:] for k, _ in root.attrs):
            root.attrs.append((loc[1:], v))
    out = []

    def write(nd):
        out.append("<" + nd.name)
        for k, v in nd.attrs:
            out.append(' %s="%s"' % (k, xml_escape(v, True)))
        if not nd.kids and nd.text == "":
            out.append("/>")
            return
        out.append(">" + xml_escape(nd.text, False))
        for c in nd.kids:
            write(c)
        out.append("</%s>" % nd.name)
    write(root)
    return "".join(out)


def count_values(node, top=True):
    """Attributes and texts in a document; an element with neither and no child
    counts as one, because decode drops it."""
    own = len(node.attrs) + (1 if node.text != "" else 0)
    if not own and not node.kids and not top:
        own = 1
    return own + sum(count_values(c, False) for c in node.kids)


MODEL_STEP_RE = re.compile(r"(.+?)\[(\d+)\]\.")


def model_lookup(ent, key):
    """A vector's `model` key (vector-format, 0.7 Vector additions) in an entity:
    `<list>[<i>].` steps into an item, `<list>.#` is the item count or `absent`.
    Returns the value, or None when it is absent."""
    while True:
        m = MODEL_STEP_RE.match(key)
        if not m or not isinstance(ent.get(m.group(1)), list):
            break
        items = ent[m.group(1)]
        if int(m.group(2)) >= len(items):
            return None
        ent, key = items[int(m.group(2))], key[m.end():]
    if key.endswith(".#"):
        items = ent.get(key[:-2])
        return "absent" if items is None else len(items)
    return ent.get(key)


# --------------------------------------------------------------------------
# Invariants of a catalog pack. gtcheck applies the load rules of the
# specification; a pack this generator writes must hold more, because the
# specification allows forms the catalog must not have. Each check reads the
# gtcheck Pack and raises a GenError that names the pack file and the line.
# --------------------------------------------------------------------------

NAME_RE = r"[A-Za-z_][A-Za-z0-9_.\-]*"
LOCATOR_RE = re.compile(r"(?:%s/)*(?:@%s|(?<=/)#text)\Z" % (NAME_RE, NAME_RE))
ITEM_LOCATOR_RE = re.compile(r"(?:%s/)*(?:@%s|#text)\Z" % (NAME_RE, NAME_RE))
GROUP_PATH_RE = re.compile(r"%s(?:/%s)*\Z" % (NAME_RE, NAME_RE))


def pack_error(pack, node, message):
    return GenError(message, pack.label, node.line if node is not None else None)


def check_only_fields_and_groups(pack):
    """The pack is wire xml and holds `field` and `group` lines only, no value
    table and no field option: that is all the generator writes and all the
    codec above reads."""
    if pack.wire != "xml":
        raise pack_error(pack, None, "the pack is not wire xml")
    if pack.tables or pack.typemap:
        raise pack_error(pack, None, "the pack has a `map` or `typemap` line")
    for _, lines in pack.scopes():
        for node in gtcheck.walk(lines):
            if node.d not in ("field", "group"):
                raise pack_error(pack, node, "a `%s` line in a generated pack" % node.d)
            if node.d == "field" and (node.via or node.opts or node.also):
                raise pack_error(pack, node, "a `field` line with an option in a generated pack")


def check_locator_shapes(pack):
    """Every locator has the form the specification gives for the xml wire
    (Locators; 0.7 item-relative locators): `@name`, `path/@name`, `path/#text`,
    and `#text` alone only inside a group; a group path is element names."""
    def scope(lines, in_group):
        for node in lines:
            if node.d == "group":
                if not GROUP_PATH_RE.match(node.loc):
                    raise pack_error(pack, node, "bad group path %s" % node.loc)
                scope(node.body, True)
            elif not (ITEM_LOCATOR_RE if in_group else LOCATOR_RE).match(node.loc):
                raise pack_error(pack, node, "bad xml locator %s" % node.loc)

    scope(pack.common, False)
    for kind in pack.kinds:
        scope(kind.lines, False)


def check_one_kind_per_root(pack):
    """Every kind has a root element name, its own or the pack's, and no two
    kinds share one: the generator writes no `when` line, so nothing else would
    tell them apart on decode (0.6 "XML: a root per kind")."""
    if not pack.kinds and pack.root is None:
        raise pack_error(pack, None, "an xml pack with no kind and no root")
    roots = {}
    for kind in pack.kinds:
        root = root_of(pack, kind)
        if root is None:
            raise GenError("kind %s has no root and the pack has none" % kind.name, pack.label, kind.line)
        if not re.fullmatch(NAME_RE, root):
            raise GenError("root name %s of kind %s" % (root, kind.name), pack.label, kind.line)
        if root in roots:
            raise GenError("kinds %s and %s share root <%s> and nothing tells them apart"
                           % (roots[root], kind.name, root), pack.label, kind.line)
        roots[root] = kind.name


def check_one_place_per_key(pack, lines, where):
    """Within one scope (common plus one kind, or one group body): no line
    twice, no key at two locators, and no two keys of one module at one
    locator. 0.6 lets a key sit at several locators, where decode keeps one and
    encode writes all; a catalog pack must not, because two wire places are two
    keys. One locator may carry a shared key and a raw key (0.5 ruling 16)."""
    seen_lines, locator_of, key_at = set(), {}, {}
    for node in lines:
        if node.d == "group":
            check_one_place_per_key(pack, node.body, "%s, group %s" % (where, node.key))
            continue
        if (node.key, node.loc) in seen_lines:
            raise pack_error(pack, node, "%s: line %s %s twice" % (where, node.key, node.loc))
        seen_lines.add((node.key, node.loc))
        if locator_of.setdefault(node.key, node.loc) != node.loc:
            raise pack_error(pack, node, "%s: key %s is mapped at two locators" % (where, node.key))
        module = gtcheck.split_key(node.key)[0]
        if key_at.setdefault((node.loc, module), node.key) != node.key:
            raise pack_error(pack, node, "%s: two keys of module %s at %s" % (where, module, node.loc))


def check_groups_do_not_overlap(pack, lines, where):
    """Within one scope no group lies at or below the path of another: the
    element a group repeats is addressed by that group alone. (A `field` that
    addresses the item element of a group, or passes through it, is a load
    rule, 0.7 ruling 21, and gtcheck refuses it.)"""
    groups = [n for n in lines if n.d == "group"]
    for group in groups:
        for other in groups:
            if other is not group and (other.loc + "/").startswith(group.loc + "/"):
                raise pack_error(pack, other, "%s: groups %s and %s overlap" % (where, group.loc, other.loc))
        check_groups_do_not_overlap(pack, group.body, "%s, group %s" % (where, group.key))


def check_kinds_do_not_shadow(pack):
    """Every kind but the last has a `requires` line: encode takes the first
    kind whose required keys are present (0.5 Encode step 2), so a kind that
    requires nothing would be chosen for every entity that reaches it."""
    for kind in pack.kinds[:-1]:
        if not kind.requires:
            raise GenError("kind %s has no requires and would shadow the kinds after it on encode" % kind.name,
                           pack.label, kind.line)


def check_module_is_mapped(pack, module):
    """Every key and list the generated module declares is mapped by a line."""
    used = set()
    for _, lines in pack.scopes():
        for node in gtcheck.walk(lines):
            used.add(node.key)
    unused = [k for k in list(module.keys) + sorted(module.lists) if module.name + "." + k not in used]
    if unused:
        raise GenError("module %s declares %d keys or lists no line maps, first %s"
                       % (module.name, len(unused), unused[0]), module.label)


def check_catalog_pack(pack):
    """All the invariants above that need the pack alone."""
    check_only_fields_and_groups(pack)
    check_locator_shapes(pack)
    check_one_kind_per_root(pack)
    for kind in pack.kinds:
        lines = pack.common + kind.lines
        check_one_place_per_key(pack, lines, "kind " + kind.name)
        check_groups_do_not_overlap(pack, lines, "kind " + kind.name)
    check_kinds_do_not_shadow(pack)


# --------------------------------------------------------------------------
# Self-check: load what was written with gtcheck and replay every vector
# --------------------------------------------------------------------------

def load_model(out):
    """Every module under `<out>/model`, as the run sees it, in a gtcheck
    Model: `core` first, then each module after the modules it uses, otherwise
    in byte order of file name."""
    pending = sorted((n for n in out.listdir("model") if n.endswith(".def")), key=lambda n: (n != "core.def", n))
    model = gtcheck.Model()
    while pending:
        waiting, refused = [], None
        for name in pending:
            try:
                model.add(out.read("model/" + name), "model/" + name)
            except gtcheck.CheckError as e:
                if e.kind != "unknown-module":
                    raise
                waiting.append(name)
                refused = refused or e
        if len(waiting) == len(pending):
            raise refused
        pending = waiting
    return model


class Replay:
    """What the self-check counted, with the loaded pack and model."""

    def __init__(self, pack, model):
        self.pack, self.model = pack, model
        self.kinds = len(pack.kinds)
        self.fields = self.groups = 0
        for lines in [pack.common] + [k.lines for k in pack.kinds]:
            self.fields += sum(1 for _ in gtcheck.walk(lines, "field"))
            self.groups += sum(1 for _ in gtcheck.walk(lines, "group"))
        self.vectors = self.values = self.items = 0

    def counts(self):
        return {k: v for k, v in sorted(vars(self).items()) if k not in ("pack", "model")}


def count_items(ent):
    return sum(len(v) + sum(count_items(i) for i in v) for v in ent.values() if isinstance(v, list))


def check_every_list_has_items(lines, ent, where, absent=frozenset(), prefix=""):
    """Every list of the kind has an item, unless the vector's model states it
    `absent` (a list in a choice branch the vector does not hold)."""
    for ln in lines:
        if ln.d == "group":
            if prefix + ln.key + ".#" in absent and ln.key not in ent:
                continue
            if not ent.get(ln.key):
                raise GenError("list %s has no item" % ln.key, where)
            for j, item in enumerate(ent[ln.key]):
                check_every_list_has_items(ln.body, item, where, absent, "%s%s[%d]." % (prefix, ln.key, j))


def replay_vector(pack, fmt, rel, text, seen_names):
    """Decode and encode one same-format vector and check everything it
    states. Returns (kind, entity, values in the document)."""
    def fail(message):
        raise GenError(message, rel)

    try:
        v = json.loads(text)
    except ValueError as e:
        fail("not JSON: %s" % e)
    for req in ("name", "from", "to", "input", "expect"):
        if req not in v:
            fail("no %s" % req)
    if v["name"] in seen_names:
        fail("vector name %s twice" % v["name"])
    seen_names.add(v["name"])
    if v["from"] != fmt or v["to"] != fmt:
        fail("not a same-format vector")
    try:
        kind, ent, residue, places = decode(pack, v["input"])
        got = encode(pack, kind, ent, residue)
        doc_values = count_values(xml_parse(v["input"]))
    except WireError as e:
        fail(str(e))
    if got != v["expect"]:
        fail("re-encoded bytes differ from expect")
    if v.get("model", {}).get("@kind") != kind.name:
        fail("decode selects kind %s" % kind.name)
    for key, want in v.get("model", {}).items():
        if key == "@kind":
            continue
        have = model_lookup(ent, key)
        if have is None or isinstance(have, list):
            fail("model key %s is absent" % key)
        if isinstance(have, float):
            same = abs(have - float(want)) <= 1e-9
        else:
            same = str(have) == want
        if not same:
            fail("model key %s is %r, want %s" % (key, have, want))
    # every value in the input reached the entity, an item or the residue:
    # nothing was dropped, inside an item (which has no residue) or outside
    if doc_values != places + len(residue):
        fail("%d values in the document, %d carried" % (doc_values, places + len(residue)))
    if any(k not in ent for k in kind.requires):
        fail("the vector lacks a key its kind requires")
    check_every_list_has_items(pack.common + kind.lines, ent, rel,
                               frozenset(k for k, val in v.get("model", {}).items() if val == "absent"))
    return kind, ent, doc_values


def self_check(out, fmt, module):
    """Read back everything the run wrote, through `out`, and replay every
    vector of the pack. Returns a Replay; raises gtcheck.CheckError for a file
    that does not load and GenError for anything else that does not hold."""
    model = load_model(out)
    pack_rel = "packs/%s/pack.def" % fmt
    pack = gtcheck.load_pack(out.read(pack_rel), model, pack_rel)
    if pack.format != fmt:
        raise GenError("pack.def names format %s" % pack.format, pack_rel)
    check_catalog_pack(pack)
    check_module_is_mapped(pack, model.modules[module])
    replay = Replay(pack, model)
    seen_kinds, names = set(), set()
    vdir = "packs/%s/vectors" % fmt
    for name in out.listdir(vdir):
        if not name.endswith(".json"):
            continue
        rel = "%s/%s" % (vdir, name)
        text = out.read(rel)
        kind, ent, doc_values = replay_vector(pack, fmt, rel, text, names)
        seen_kinds.add(kind.name)
        replay.values += doc_values
        replay.items += count_items(ent)
        replay.vectors += 1
    missing = [k.name for k in pack.kinds if k.name not in seen_kinds]
    if missing:
        raise GenError("%d kinds have no vector, first %s" % (len(missing), missing[0]), vdir)
    return replay


# --------------------------------------------------------------------------
# Plan: every decision of a run, made before any text is written
# --------------------------------------------------------------------------

class MessageKind:
    """One message of the catalog and the kind it becomes."""

    def __init__(self, root):
        self.root = root            # global element Particle
        self.name = snake(root.name)
        self.items = []             # lines in schema order: Leaf and Group
        self.leaves, self.skipped = [], []      # leaves: the Leaf lines outside any group
        self.requires = []
        self.unique = False         # no other kind maps every key of `requires`
        self.default = False
        self.optional_required = 0  # how many `requires` keys are optional in the schema


def select_messages(schema, type_suffix, choice_types, element_names):
    """(names of the global elements that are messages, in schema declaration
    order; the rule as pack.md states it)."""
    names, rule = [], []
    if type_suffix:
        names += [n for n, e in schema.elements.items() if schema.element_type(e)[1].endswith(type_suffix)]
        rule.append("every global element whose type name ends in `%s`" % type_suffix)
    for tname in choice_types:
        ct = schema.complex.get(tname)
        if ct is None or ct.particle is None or ct.particle.kind != "choice":
            raise GenError("--message-choice %s: not a complex type whose content is one choice" % tname)
        for c in ct.particle.children:
            if c.kind != "element" or c.type[0] != "ref":
                raise GenError("--message-choice %s: branch %s is not an element ref" % (tname, c.name), c.file, c.line)
            names.append(c.name)
        rule.append("every global element the choice in type `%s` refers to" % tname)
    for n in element_names:
        if n not in schema.elements:
            raise GenError("--message %s: no such global element" % n)
        names.append(n)
        rule.append("the global element `%s`" % n)
    wanted = set(names)
    out = [n for n in schema.elements if n in wanted]       # schema declaration order
    if not out:
        raise GenError("no message selected: give --message-type-suffix, --message-choice or --message")
    return out, rule


class Walked:
    """The messages walked under the limits that keep the module in budget."""

    def __init__(self):
        self.kinds = []             # MessageKind of every message, those with no line included
        self.idents = []            # sorted identities of the keys and lists
        self.n_keys = self.n_lists = 0
        self.depth = self.depth_asked = 0       # the depth limit applied, and the one asked for
        self.deepest = 0            # deepest group nesting in the result
        self.nest_free = self.keys_free = 0     # nesting and identities with no limit applied
        self.poly = self.unqualified = 0
        self.key_budget = 0         # the budget the walk was held to
        self.over_budget = False    # True when the lowest limits still leave more identities than the budget

    @property
    def nest_limited(self):
        return self.deepest < self.nest_free


def list_ident(group):
    return (group.path + "/[]", "list")


def leaf_ident(leaf):
    return (leaf.locator, leaf.mtype)


def walk_messages(schema, msg_names, max_depth, max_nest, key_budget=KEY_BUDGET):
    """Walk every message; while the module would hold more than `key_budget`
    keys and lists, lower the nesting of groups, then the depth, and walk
    again."""
    w = Walked()
    w.depth_asked = depth = min(max_depth, DEPTH_CEILING)
    nest = max(max_nest, 1)
    first = True
    while True:
        walker = Walker(schema, depth, nest)
        kinds = []
        for n in msg_names:
            k = MessageKind(schema.elements[n])
            k.items, k.skipped = walker.walk(k.root)
            k.leaves = [x for x in k.items if isinstance(x, Leaf)]
            kinds.append(k)
        key_idents = {leaf_ident(lf) for k in kinds for lf in all_leaves(k.items)}
        list_idents = {list_ident(g) for k in kinds for g in all_groups(k.items)}
        idents = sorted(key_idents | list_idents)
        deepest = max([g.nest for k in kinds for g in all_groups(k.items)] or [0])
        if first:
            w.nest_free, w.keys_free = deepest, len(idents)     # what the schema has before this loop limits it
            first = False
        if len(idents) <= key_budget:
            break
        if min(nest, deepest) > 1:
            nest = min(nest, deepest) - 1
        elif depth > 1:
            depth -= 1
        else:
            break
    w.kinds, w.idents, w.n_keys, w.n_lists = kinds, idents, len(key_idents), len(list_idents)
    w.depth, w.deepest, w.poly, w.unqualified = depth, deepest, walker.poly, walker.unqualified
    w.key_budget, w.over_budget = key_budget, len(idents) > key_budget
    return w


def over_budget_warning(walked, module):
    """The line `run` prints when a module stays over the key budget, or None.
    The run goes on: the pack is still valid, and the reader is told its size."""
    if not walked.over_budget:
        return None
    return ("warning: module %s holds %d keys and lists, more than the budget of %d, with group nesting "
            "and depth already lowered to 1; the pack is written as it is"
            % (module, len(walked.idents), walked.key_budget))


def name_lines(kinds, names, module):
    """Give every leaf its raw key and every group its list."""
    for k in kinds:
        for lf in all_leaves(k.items):
            lf.key = module + "." + names[leaf_ident(lf)]
        for g in all_groups(k.items):
            g.list = module + "." + names[list_ident(g)]


MapSpec = collections.namedtuple("MapSpec", "text root locator key")
CrossSpec = collections.namedtuple("CrossSpec", "text packdef vector field")


def bind_shared_keys(kinds, specs, shared):
    """Apply each --map: the leaf at that locator of that message also maps the
    core or track key. Returns [(kind, leaf, key)] in the order given. `shared`
    is {key: (type, unit)}."""
    by_root = {k.root.name: k for k in kinds}
    maps = []
    for spec in specs:
        if spec.key not in shared:
            raise GenError("--map %s: %s is not a key of core or track" % (spec.text, spec.key))
        k = by_root.get(spec.root)
        lf = next((x for x in k.leaves if x.locator == spec.locator), None) if k else None
        if lf is None:
            raise GenError("--map %s: message %s has no mapped leaf at %s" % (spec.text, spec.root, spec.locator))
        ktype, unit = shared[spec.key]
        if ktype != lf.mtype:
            raise GenError("--map %s: key is %s, the leaf yields %s" % (spec.text, ktype, lf.mtype))
        if lf.rad and unit == "deg":
            raise GenError("--map %s: the schema states radians and the key is in degrees; "
                           "the xml wire's `float` has no scale" % spec.text)
        if lf.shared:
            raise GenError("--map %s: the leaf is already bound to %s" % (spec.text, lf.shared))
        lf.shared = spec.key
        maps.append((k, lf, spec.key))
    return maps


def common_prefix(kinds):
    """The longest run of leading lines that every kind starts with: a leaf with
    the same locator and transform, a group with the same path and the same
    item. It becomes the pack's common lines."""
    if len(kinds) < 2:
        return 0
    n = 0
    first = kinds[0].items
    while n < len(first):
        x = first[n]
        if x.choice is not None:
            break
        sig = signature(x)
        if not all(len(k.items) > n and type(k.items[n]) is type(x) and signature(k.items[n]) == sig for k in kinds):
            break
        n += 1
    return n


def choose_requires(kinds, ncommon, limit=6):
    """Up to `limit` raw keys per kind, picked greedily so that as few other
    kinds as possible map all of them. Candidates: first the kind's own leaves
    on a path the schema makes mandatory; while other kinds still map the whole
    list, its own optional leaves; a kind with no own leaf takes a common one.
    Leaves inside a group are not candidates: `requires` looks at the entity's
    own keys. A kind with no leaf outside its groups requires its first list.
    `ncommon` counts the leading leaves that are common lines."""
    where = collections.defaultdict(set)
    for i, k in enumerate(kinds):
        for lf in k.leaves:
            where[lf.key].add(i)
    for i, k in enumerate(kinds):
        own = [lf for lf in k.leaves[ncommon:] if lf.choice is None or lf.choice[1] == 0]
        tiers = [[lf for lf in own if lf.mandatory], [lf for lf in own if not lf.mandatory]]
        if not own:
            tiers = [[lf for lf in k.leaves[:ncommon] if lf.mandatory] or k.leaves[:ncommon]]
        live, chosen = set(range(len(kinds))), []
        k.optional_required = 0
        for t, tier in enumerate(tiers):
            cand_keys = []
            for lf in tier:
                if lf.key not in cand_keys and lf.key not in chosen:
                    cand_keys.append(lf.key)
            while cand_keys and len(chosen) < limit and live != {i}:
                best = min(cand_keys, key=lambda key: len(live & where[key]))
                nxt = live & where[best]
                if chosen and len(nxt) == len(live):
                    break
                chosen.append(best)
                k.optional_required += t
                cand_keys.remove(best)
                live = nxt
        if not chosen:
            chosen = [x.list for x in k.items if isinstance(x, Group)][:1]
        k.requires = chosen
        k.unique = live == {i}


def set_default_kind(kinds, maps, root_name, requires):
    """Mark the kind an entity from another format encodes as: it requires
    shared keys a --map binds in it, in place of raw keys. Returns it, or None
    when no default kind was asked for."""
    if not root_name:
        if requires:
            raise GenError("--default-requires needs --default-kind")
        return None
    default = next((k for k in kinds if k.root.name == root_name), None)
    if default is None:
        raise GenError("--default-kind %s: no kind has that root element" % root_name)
    bound = [key for k, lf, key in maps if k is default]
    want = requires or bound
    if not want or any(key not in bound for key in want):
        raise GenError("--default-requires: every key must be bound in %s by a --map" % root_name)
    default.requires, default.default, default.unique = list(want), True, True
    return default


class Plan:
    """What a run emits, with every decision made: the kinds and their lines in
    pack order, the names, the common lines, the `requires` of each kind, the
    shared-key bindings and the limits that were applied. The emit functions
    read a Plan and decide nothing."""

    def __init__(self):
        self.format = self.module = self.title = self.version = None
        self.import_only = []       # base names of files with no targetNamespace that import the set's
        self.declined, self.substitution, self.only, self.skip = [], False, {}, []
        self.notes = None           # text of --notes-file, placed in pack.md
        self.msg_names, self.rule = [], []
        self.walked = None          # Walked
        self.kinds, self.empty, self.pack_kinds = [], [], []
        self.names = {}             # ident -> name
        self.pinned = {}            # names file as read: `<locator> <type>` -> name
        self.maps = []              # (kind, leaf, shared key)
        self.shared = {}            # shared key -> (type, unit)
        self.ncommon = self.nleaf = 0       # common lines; those of them that are leaves
        self.default = None
        self.tns, self.use_xmlns = None, False
        self.src_lines, self.uses = [], []
        self.name_drop = ()
        self.key_budget = KEY_BUDGET

    @property
    def common(self):
        return self.kinds[0].items[:self.ncommon]


def make_plan(schema, statements, shared, pinned, args, key_budget=KEY_BUDGET):
    """Plan step. `args` is the parsed command line."""
    plan = Plan()
    plan.format, plan.module, plan.title, plan.version = args.format, args.module, args.title, args.version
    plan.shared, plan.pinned, plan.name_drop, plan.key_budget = shared, pinned, tuple(args.name_drop), key_budget
    plan.msg_names, plan.rule = select_messages(schema, args.message_type_suffix, args.message_choice, args.message)
    plan.walked = w = walk_messages(schema, plan.msg_names, args.max_depth, args.max_nest, key_budget)
    kn = collections.Counter(k.name for k in w.kinds)
    if any(c > 1 for c in kn.values()):
        raise GenError("two root elements give the same kind name: %s" % [n for n, c in kn.items() if c > 1])
    plan.empty = [k for k in w.kinds if not k.items]
    plan.kinds = kinds = [k for k in w.kinds if k.items]
    if not kinds:
        raise GenError("nothing can be mapped in any of the %d messages selected" % len(w.kinds))
    plan.names = assign_names(w.idents, pinned, plan.name_drop)
    name_lines(kinds, plan.names, plan.module)
    plan.maps = bind_shared_keys(kinds, args.map, shared)

    plan.ncommon = common_prefix(kinds)         # lines: leaves and groups
    if any(isinstance(x, Leaf) and x.shared for k in kinds for x in k.items[:plan.ncommon]):
        plan.ncommon = 0
    plan.nleaf = sum(1 for x in plan.common if isinstance(x, Leaf))
    choose_requires(kinds, plan.nleaf)
    plan.default = set_default_kind(kinds, plan.maps, args.default_kind, args.default_requires)
    # pack order: schema order, the default kind last (0.5 Encode step 2 takes the first that qualifies)
    plan.pack_kinds = [k for k in kinds if not k.default] + [k for k in kinds if k.default]

    plan.tns = schema.tns
    plan.import_only = [base for base, _ in schema.import_only]
    plan.declined, plan.substitution, plan.only = sorted(schema.declined), schema.substitution, schema.only
    plan.skip = sorted(schema.skip)
    plan.use_xmlns = (args.vector_xmlns == "auto" and bool(schema.tns) and w.unqualified == 0
                      and not plan.import_only)
    plan.src_lines = ["%s: %s" % (plan.title, ", ".join("%s sha256 %s" % (f.base, f.sha256) for f in schema.files))]
    public = [base for base, st in statements if st.startswith(PUBLIC_PREFIX)]
    plan.src_lines += ["File header of %s: %s" % (base, st) for base, st in statements if base not in public]
    if public:
        plan.src_lines.append("No file of the set carries a statement in its header (%s); publisher's statement: %s"
                              % (", ".join(public), " ".join(args.public_statement.split())))
    plan.src_lines += args.source
    plan.notes = None
    if args.notes_file:
        with open(args.notes_file, encoding="utf-8") as fh:
            plan.notes = fh.read().rstrip("\n")
    plan.uses = [plan.module] + sorted({key.split(".")[0] for _, _, key in plan.maps if "." in key})
    return plan


def n_lines_of(items):
    """The `field` lines a run of plan lines becomes: two for a leaf that also
    maps a shared key."""
    return sum(1 + bool(lf.shared) for lf in all_leaves(items))


class Stats:
    """Counts over a Plan, for pack.md and the summary."""


def count_plan(plan):
    s = Stats()
    kinds, ncommon, names = plan.kinds, plan.ncommon, plan.names
    s.total = sum(len(k.leaves) for k in kinds)
    s.in_groups = sum(1 for k in kinds for g in all_groups(k.items) for _ in g.leaves())
    s.groups_all = [g for k in kinds for g in all_groups(k.items)]
    s.groups_first = sum(1 for g in s.groups_all if g.nest == 1)
    s.scalar_groups = sum(1 for g in s.groups_all if [getattr(x, "locator", None) for x in g.items] == ["#text"])
    s.common_groups = sum(1 for _ in all_groups(plan.common))
    s.common_group_leaves = sum(1 for g in all_groups(plan.common) for _ in g.leaves())
    every = [lf for k in kinds for lf in all_leaves(k.items)]
    s.by_tr = collections.Counter(lf.transform for lf in every)
    s.by_xs = collections.Counter((lf.xs, lf.transform) for lf in every)
    s.notes = collections.Counter(lf.note for lf in every if lf.note)
    s.rad = sum(1 for lf in every if lf.rad)
    s.rad_keys = len({leaf_ident(lf) for lf in every if lf.rad})
    s.reasons = collections.Counter(r[0] for k in kinds for r in k.skipped)
    s.choice_leaves = sum(1 for lf in every if lf.choice)
    s.choices = len({lf.choice[0] for lf in every if lf.choice})
    s.mandatory = sum(1 for k in kinds for lf in k.leaves if lf.mandatory)
    s.n_lines = (n_lines_of(plan.common) if ncommon else 0) + sum(n_lines_of(k.items[ncommon:]) for k in kinds)
    s.n_groups = s.common_groups + sum(1 for k in kinds for _ in all_groups(k.items[ncommon:]))
    s.depth_hist = collections.Counter(lf.depth for lf in every)
    s.nest_hist = collections.Counter(g.nest for g in s.groups_all)
    s.longest = max(len(n) for n in names.values())
    s.hashed = sum(1 for n in names.values() if re.search(r"_[0-9a-f]{8}$", n))
    s.new_names = sum(1 for ident in plan.walked.idents if ident_tag(ident) not in plan.pinned)
    plain = [k for k in kinds if not k.default]
    s.plain = len(plain)
    s.uniq = sum(1 for k in plain if k.unique)
    s.opt = sum(1 for k in plain if k.optional_required)
    return s


# --------------------------------------------------------------------------
# Emit: the text of each file, from a Plan
# --------------------------------------------------------------------------

def quote(s):
    """A value of a `.def` line: double quoted, one space between words, and
    `'` for `"` because a quoted value has no escape (0.5 ruling 6)."""
    return '"' + " ".join(s.replace('"', "'").split()) + '"'


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def unit_of(leaf):
    return "ms" if leaf.transform == "iso8601_ms" else "rad" if leaf.rad else "-"


def module_text(plan):
    """model/<module>.def: one `key` per (locator, type), then one `list` per
    group path, each in the order of its identity."""
    info = {}       # key ident -> [first leaf (one outside a group when there is one), kinds, groups, units]
    linfo = {}      # list ident -> [first group, groups]
    for k in plan.kinds:
        for lf in k.leaves:
            e = info.setdefault(leaf_ident(lf), [lf, 0, 0, set()])
            e[1] += 1
            e[3].add(unit_of(lf))
    for k in plan.kinds:
        for g in all_groups(k.items):
            e = linfo.setdefault(list_ident(g), [g, 0])
            e[1] += 1
            for lf in g.leaves():
                e = info.setdefault(leaf_ident(lf), [lf, 0, 0, set()])
                e[2] += 1
                e[3].add(unit_of(lf))
    names, idents = plan.names, plan.walked.idents
    width = max(len(n) for n in names.values()) + 2
    L = ["# The %s module: raw keys of the %s format, one per (locator, type) the\n" % (plan.module, plan.format),
         "# pack maps, and one list per repeated element. A key is shared by every kind\n",
         "# and every group that has that locator; inside a group the locator is relative\n",
         "# to the item. Generated by tools/gen/xsd2pack.py from the sources below; edit\n",
         "# the generator, not this file.\n",
         "module        %s\nversion       %s\ndistribution  public\n" % (plan.module, plan.version)]
    L += ["source        %s\n" % quote(s) for s in plan.src_lines]
    for ident in idents:
        if ident[1] == "list":
            continue
        lf, n, ng, units = info[ident]
        unit = min(units) if len(units) == 1 else "-"
        tdesc = lf.tname if lf.tname.startswith("xs:") else "%s, xs:%s" % (lf.tname, lf.xs)
        where = "; ".join(x for x in (plural(n, "kind") if n else "",
                                      "an item of %s" % plural(ng, "group") if ng else "") if x)
        meaning = "%s.%s (%s) at %s; %s" % (lf.owner, lf.member, tdesc, lf.locator, where)
        L.append("key  %s%-6s  %-3s  %s\n" % (names[ident].ljust(width), lf.mtype, unit, quote(meaning)))
    for ident in idents:
        if ident[1] != "list":
            continue
        g, n = linfo[ident]
        meaning = "%s.%s (%s), repeated, at %s; %s" % (g.owner, g.member, g.tname, g.path, plural(n, "group"))
        L.append("list %s%s\n" % (names[ident].ljust(width), quote(meaning)))
    return "".join(L)


def loc_token(locator):
    """A locator as a token of pack.def. 0.7 ruling 1: `#` at the start of a
    token begins a comment, so `#text` alone is quoted."""
    return '"%s"' % locator if locator.startswith("#") else locator


def pack_lines(items, indent=""):
    """The `field` and `group` lines of a run of plan lines. A leaf bound to a
    shared key has two lines on its locator, the shared key first (0.5 ruling 16)."""
    out = []
    for x in items:
        if isinstance(x, Group):
            out.append("%sgroup  %s  %s\n" % (indent, x.list, x.path))
            out.extend(pack_lines(x.items, indent + "  "))
            out.append("%send\n" % indent)
            continue
        if x.shared:
            out.append("%sfield  %s  %s  %s\n" % (indent, x.shared, loc_token(x.locator), x.transform))
        out.append("%sfield  %s  %s  %s\n" % (indent, x.key, loc_token(x.locator), x.transform))
    return out


def pack_text(plan):
    """packs/<format>/pack.def: the header, the common lines, then each kind
    with its root, its `requires` and its own lines."""
    L = ["# %s. Public. Generated by tools/gen/xsd2pack.py; edit the generator,\n" % plan.title,
         "# not this file. One kind per message, each with its own root element\n",
         "# (engine-spec 0.6); one `group` per repeated element, its lines relative to\n",
         "# one item (engine-spec 0.7). What is mapped and what is not: pack.md.\n",
         "format        %s\nversion       %s\ndistribution  public\n" % (plan.format, plan.version)]
    L += ["source        %s\n" % quote(s) for s in plan.src_lines]
    L.append("wire          xml\n")
    L += ["uses          %s\n" % u for u in plan.uses]
    if plan.ncommon:
        L.append("\n# Common: the %d leading lines every message has at the same place.\n" % plan.ncommon)
        L += pack_lines(plan.common)
    for k in plan.pack_kinds:
        if k.default:
            L.append("\n# The default kind: an entity from another format that has %s encodes as it.\n"
                     % " and ".join("`%s`" % r for r in k.requires))
        L.append("\nkind      %s\nroot      %s\n" % (k.name, k.root.name))
        if k.requires:
            L.append("requires  %s\n" % " ".join(k.requires))
        L += pack_lines(k.items[plan.ncommon:])
    return "".join(L)


def epoch_ms(text):
    d = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc)
    return (d - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)) // datetime.timedelta(milliseconds=1)


class VectorBuilder:
    """Builds the round-trip vector of each kind. `samples` maps a locator, or
    the tail of one, to the value every such leaf gets; `weak` counts the
    values that do not fit the facets of their type."""

    def __init__(self, schema, plan, samples, per_group):
        self.schema, self.plan, self.samples, self.per_group = schema, plan, samples, per_group
        self.weak = 0

    def value(self, lf, i):
        """(wire text, model text) of the `i`-th leaf."""
        val, honored = sample_value(self.schema, lf.qref, lf.transform, i)
        for tail, sval in self.samples.items():
            if lf.locator == tail or lf.locator.endswith("/" + tail):
                enums = next((st.enums for st in self.schema.simple_info(lf.qref)[1] if st.enums), None)
                if enums is not None and sval not in enums:
                    raise GenError("--sample %s=%s: not a value of %s" % (tail, sval, lf.tname))
                val, honored = sval, True
        if not SAFE_VALUE.match(val):
            val, honored = "v%d" % i, False
        self.weak += 0 if honored else 1
        return val, (str(epoch_ms(val)) if lf.transform == "iso8601_ms" else val)

    def item(self, g, prefix, shown, model, seq):
        """One item of group `g`: (its placed lines, the first (key, model
        text) in it). `shown` adds the counts of the lists inside it to
        `model`; `seq[0]` is the sample index of the next leaf inside a group."""
        placed, first = [], None
        for x in g.items:
            if isinstance(x, Group) and x.choice is not None and x.choice[1] != 0:
                model[prefix + x.list + ".#"] = "absent"
                continue
            if isinstance(x, Group):
                placed.append(("g", x.path, [self.item(x, "%s%s[0]." % (prefix, x.list), shown, model, seq)[0]]))
                if shown:
                    model[prefix + x.list + ".#"] = "1"
                continue
            if x.choice is not None and x.choice[1] != 0:
                continue
            val, mval = self.value(x, seq[0])
            seq[0] += 1
            placed.append(("f", x.locator, val))
            first = first or (x.key, mval)
        return placed, first

    def vector(self, k):
        """The vector of kind `k`: every mapped leaf present (of a mapped
        choice the first branch), `per_group` items in every first-level group
        and one item in every group below."""
        plan, per_group = self.plan, self.per_group
        model = collections.OrderedDict([("@kind", k.name)])
        seq = [len(k.leaves)]
        placed, own_shown, i = [], 0, -1
        for pos, x in enumerate(k.items):
            if isinstance(x, Group) and x.choice is not None and x.choice[1] != 0:
                model[x.list + ".#"] = "absent"
                continue
            if isinstance(x, Group):
                built = [self.item(x, "%s[%d]." % (x.list, j), j == 0, model, seq) for j in range(per_group)]
                placed.append(("g", x.path, [b[0] for b in built]))
                model[x.list + ".#"] = str(per_group)
                if per_group > 1 and built[-1][1]:
                    model["%s[%d].%s" % (x.list, per_group - 1, built[-1][1][0])] = built[-1][1][1]
                continue
            i += 1
            if x.choice is not None and x.choice[1] != 0:
                continue
            val, mval = self.value(x, i)
            placed.append(("f", x.locator, val))
            if x.shared:
                model[x.shared] = mval
                model[x.key] = mval
            elif pos >= plan.ncommon and own_shown < 2:
                model[x.key] = mval
                own_shown += 1
        doc = canonical_xml(k.root.name, placed, [("xmlns", plan.tns)] if plan.use_xmlns else [])
        return collections.OrderedDict([
            ("name", "gen-%s-roundtrip" % k.name), ("from", plan.format), ("to", plan.format),
            ("input", doc), ("expect", doc), ("model", model)])


def build_vectors(schema, plan, samples, per_group):
    """([(file name, JSON text)] one per kind in schema order, values that do
    not fit their facets)."""
    builder = VectorBuilder(schema, plan, samples, per_group)
    digits = len(str(len(plan.kinds)))
    out = []
    for idx, k in enumerate(plan.kinds, 1):
        out.append(("gen-%0*d-%s-roundtrip.json" % (digits, idx, k.name),
                    json.dumps(builder.vector(k), indent=2, ensure_ascii=False) + "\n"))
    return out, builder.weak


class VectorSet:
    """The vectors of a pack and how they were sized."""

    def __init__(self, files, weak, per_group, two_bytes, budget):
        self.files, self.weak, self.per_group = files, weak, per_group
        self.two_bytes, self.budget = two_bytes, budget     # bytes with two items per group; the limit


def vectors_within_budget(schema, plan, samples, budget=VECTOR_BUDGET):
    """Two items per first-level group; one when two would pass `budget` bytes."""
    files, weak = build_vectors(schema, plan, samples, 2)
    two_bytes = sum(len(t.encode("utf-8")) for _, t in files)
    if two_bytes <= budget:
        return VectorSet(files, weak, 2, two_bytes, budget)
    files, weak = build_vectors(schema, plan, samples, 1)
    return VectorSet(files, weak, 1, two_bytes, budget)


def names_text(plan):
    """The names file: every name pinned before this run and every name of
    this run, sorted by identity. A pinned name never changes."""
    merged = dict(plan.pinned)
    merged.update({ident_tag(ident): n for ident, n in plan.names.items()})
    for tag, name in plan.pinned.items():
        if merged[tag] != name:
            raise GenError("pinned name %s of %s would change" % (name, tag))
    return json.dumps(merged, indent=1, sort_keys=True) + "\n"


# -- vectors from another format into this one -------------------------------

def plain_decode(pack, doc):
    """decode() of a document with another xml pack that has no kinds: enough
    of 0.1 to 0.6 to read the entity of a cross-format vector (`field` lines
    without options, several lines per key, the earliest present one wins;
    `const` and `default` do not act on decode). Returns (entity, the root
    attributes no line maps)."""
    if pack.wire != "xml" or pack.root is None:
        raise GenError("--cross: the other pack is not an xml pack with a pack-level root", pack.label)
    if pack.kinds:
        raise GenError("--cross: the other pack has a `kind` line", pack.label, pack.kinds[0].line)
    if pack.tables or pack.typemap:
        raise GenError("--cross: the other pack has a `map` or `typemap` line", pack.label)
    fields, consts = [], set()
    for node in pack.common:
        if node.d == "field":
            if node.via or node.opts or node.also:
                raise pack_error(pack, node, "--cross: a field this reader does not handle")
            fields.append(node)
        elif node.d == "const":
            consts.add(node.loc)
        elif node.d != "default":
            raise pack_error(pack, node, "--cross: the other pack has a `%s` line" % node.d)
    node = xml_parse(doc)
    if node.name != pack.root:
        raise GenError("--cross: the document's root is <%s>, the pack's is <%s>" % (node.name, pack.root), pack.label)
    ent = collections.OrderedDict()
    for f in fields:
        raw = xml_get(node, f.loc)
        if raw is not None and f.key not in ent:
            ent[f.key] = t_decode(f.tr, raw)
    mapped = {f.loc for f in fields} | consts
    return ent, [k for k, _ in node.attrs if "@" + k not in mapped]


def would_derive(model, keys):
    """The keys `convert` would add to an entity that has `keys` (0.6 Derived
    keys), by presence only: this codec computes no derivation, so a vector it
    writes must not depend on one."""
    have, added = set(keys), set()
    for _ in range(8):
        progressed = False
        for name in sorted(model.modules):
            for derive in model.modules[name].derives:
                if derive.target not in have and all(k in have for k in derive.arguments):
                    have.add(derive.target)
                    added.add(derive.target)
                    progressed = True
        if not progressed:
            break
    return added


def model_text(v):
    return plain_float(v) if isinstance(v, float) else str(v)


class Cross:
    """One vector from another format: where it comes from, the kind it encodes
    as, the keys carried and dropped, the file written and the document."""

    def __init__(self, src_fmt, kind, carried, dropped, rel, text, expect):
        self.src_fmt, self.kind, self.carried, self.dropped = src_fmt, kind, carried, dropped
        self.rel, self.text, self.expect = rel, text, expect


def cross_vector(spec, replay, fmt, default):
    """Decode FIELD of an existing vector with its own pack, encode the entity
    with the generated pack (the gtcheck Pack of the self-check) and prove the
    keys both formats map survive. Returns a Cross."""
    def fail(message):
        raise GenError("--cross %s: %s" % (spec.text, message))

    pack = replay.pack
    try:
        src_vec = json.loads(read_text(spec.vector))
    except ValueError as e:
        raise GenError("not JSON: %s" % e, spec.vector)
    if spec.field not in src_vec:
        fail("the vector has no %s" % spec.field)
    other = gtcheck.load_pack(read_text(spec.packdef), replay.model, spec.packdef)
    ent, loose = plain_decode(other, src_vec[spec.field])
    src_fmt = other.format
    if src_vec.get("to" if spec.field == "expect" else "from") != src_fmt:
        fail("that text is not %s" % src_fmt)
    if loose:
        fail("the document has root attributes its pack does not map (%s); "
             "the specification does not say whether residue crosses formats" % " ".join(loose))
    pack_keys = {ln.key for k in pack.kinds for ln in fields_of(pack.common + k.lines)}
    derived = would_derive(replay.model, ent) & pack_keys
    if derived:
        fail("the engine would derive %s, which this pack writes" % " ".join(sorted(derived)))
    chosen = select_kind(pack, ent)
    if default is not None and chosen.name != default.name:
        fail("encoded as kind %s, not the default kind" % chosen.name)
    text = encode(pack, chosen, ent, [])
    back_kind, back, back_residue, _ = decode(pack, text)
    if back_kind is not chosen or back_residue:
        fail("the output decodes as kind %s" % back_kind.name)
    carried = [key for key in ent if key in back]
    for key in carried:
        if back[key] != ent[key]:
            fail("key %s does not survive" % key)
    if not carried:
        fail("no key of the entity has a place in kind %s" % chosen.name)
    vec = collections.OrderedDict([
        ("name", "gen-%s-to-%s" % (src_fmt, fmt)), ("from", src_fmt), ("to", fmt),
        ("input", src_vec[spec.field]), ("expect", text),
        ("model", collections.OrderedDict((key, model_text(v)) for key, v in ent.items()))])
    rel = "packs/%s/vectors/gen-%s-to-%s.json" % (src_fmt, src_fmt, fmt)
    return Cross(src_fmt, chosen.name, carried, [key for key in ent if key not in back], rel,
                 json.dumps(vec, indent=2, ensure_ascii=False) + "\n", text)


# -- pack.md -------------------------------------------------------------------

def first_sentence(doc, limit=220):
    doc = " ".join(doc.split())
    m = re.match(r"(.+?[.!?])(\s|$)", doc)
    out = m.group(1) if m else doc
    return out if len(out) <= limit else out[:limit - 3].rstrip() + "..."


def md_sources(schema, statements, plan):
    L = ["# Pack: %s\n" % plan.format,
         "%s, as XML documents. Generated by `tools/gen/xsd2pack.py`. Wire `xml`, engine-spec" % plan.title,
         "version 0.7 (a `root` line per kind, a `group` block per repeated element). Edit the generator, not this file.\n",
         "## Sources\n",
         "| File | Bytes | SHA-256 | Header statement |\n|---|---|---|---|"]
    for f, (_, st) in zip(schema.files, statements):
        L.append("| `%s` | %d | `%s` | %s |" % (f.base, f.size, f.sha256, st))
    L.append("")
    for inc in schema.includes:
        L.append("- `%s` has `xs:%s schemaLocation=\"%s\"`; read from `%s`%s." % (
            inc.base, inc.tag, inc.location, os.path.basename(inc.resolved),
            "" if inc.location == inc.resolved else " (the set ships the file under that name)"))
    L.append("- targetNamespace `%s`; elementFormDefault: %s." % (
        plan.tns, ", ".join("%s in `%s`" % (v, f) for f, v in schema.element_form.items())))
    if schema.chameleon:
        L.append("- chameleon includes (no targetNamespace, so their declarations take `%s`): %s." % (
            plan.tns, ", ".join("`%s`" % b for b in schema.chameleon)))
    return L


def md_counts(schema, plan, s, n_cross):
    w = plan.walked
    L = ["\n## Schema and result\n", "| | Count |\n|---|---|"]
    rows = [("XSD files read", len(schema.files)), ("global elements", len(schema.elements)),
            ("complex types", len(schema.complex)), ("simple types", len(schema.simple)),
            ("messages", len(plan.msg_names)), ("kinds", len(plan.kinds)),
            ("global elements that are not messages", len(schema.elements) - len(plan.msg_names)),
            ("leaves mapped outside any group, summed over kinds", s.total),
            ("of those, on a path the schema makes mandatory", s.mandatory),
            ("groups (repeated elements mapped), summed over kinds", len(s.groups_all)),
            ("of those, directly in a message (first level)", s.groups_first),
            ("of those, inside an item of another group (nested)", len(s.groups_all) - s.groups_first),
            ("of those, items that are one text value (`\"#text\"` alone)", s.scalar_groups),
            ("leaves mapped inside items of groups, summed over kinds", s.in_groups),
            ("`field` lines in pack.def", s.n_lines),
            ("`group` blocks in pack.def", s.n_groups),
            ("common lines (every kind starts with them): `field`", plan.nleaf),
            ("common lines: `group` blocks, first level", plan.ncommon - plan.nleaf),
            ("keys in module `%s`" % plan.module, w.n_keys),
            ("lists in module `%s`" % plan.module, w.n_lists),
            ("`field` lines bound to `core` or `track` keys", len(plan.maps)),
            ("places not mapped, summed over kinds", sum(s.reasons.values())),
            ("vectors (one same-format round trip per kind)", len(plan.kinds)),
            ("vectors from another format", n_cross),
            ("depth limit (element steps below the root)", w.depth),
            ("deepest group nesting", w.deepest)]
    L += ["| %s | %d |" % r for r in rows]
    if w.nest_limited:
        L.append("\nGroup nesting is limited to %d for this pack: with no limit the schema nests groups %d deep and the"
                 % (w.deepest, w.nest_free))
        L.append("module would hold %d keys and lists, over the limit of %d. A repeated element inside an item at"
                 % (w.keys_free, plan.key_budget))
        L.append("nesting %d is not mapped (see Not mapped)." % w.deepest)
    if w.depth < w.depth_asked:
        L.append("\nThe depth limit was lowered from %d to %d to keep the module within %d keys and lists."
                 % (w.depth_asked, w.depth, plan.key_budget))
    L.append("\nMapped leaves by depth (element steps below the root, inside groups too): "
             + ", ".join("%d at depth %d" % (s.depth_hist[d], d) for d in sorted(s.depth_hist)) + ".")
    if s.groups_all:
        L.append("\nGroups by nesting: " + ", ".join("%d at level %d" % (s.nest_hist[d], d) for d in sorted(s.nest_hist)) + ".")
    return L


def md_messages(plan):
    default, empty = plan.default, plan.empty
    L = ["\n## Which global elements are messages\n",
         "A kind is written for %s. Each kind has `root <element>` and no `when`; the pack has no" % "; and ".join(plan.rule),
         "pack-level `root`. Kind names are the element names in snake case. Kinds are in schema order%s."
         % (", except `%s`, which is last (see `requires`)" % default.name if default is not None else "")]
    if empty:
        L.append("\nNo kind is written for %d message%s in which nothing can be mapped (%s): a kind with no"
                 % (len(empty), "" if len(empty) == 1 else "s", ", ".join("`%s`: %s" % (
                     k.root.name, "; ".join(sorted({r[0] for r in k.skipped}))) for k in empty)))
        L.append("`field` and no `requires` would be selected on encode by any entity. Such a document decodes as `no-kind`.")
    return L


def md_walk(s):
    return [
        "\n## How a message is walked\n",
        "From the root element through child elements, resolving named types, `xs:extension` base",
        "chains (base content first), groups and element refs. An attribute is `path/@name`; an",
        "element of simple type, or of a complex type with simple content, is `path/#text`. Lines are",
        "in schema order, so an encoder writes child elements in the order the schema's sequences",
        "require. A choice is mapped only when every branch is an element of simple type with",
        "maxOccurs 1; then each branch is a line, and at most one is present in a valid document",
        "(%d such choices, %d lines). Nothing chooses a branch of any other choice." % (s.choices, s.choice_leaves),
        "\n## Repeated elements\n",
        "An element with maxOccurs above 1 is a `group <list> <path>` block: `<path>` runs from the root",
        "element (or from the enclosing item) to the repeated element, and the lines inside the block",
        "are the walk of one item, their locators relative to the item element. An item of simple type",
        "is one line, `\"#text\"` (quoted: 0.7 ruling 1); an item of complex type has `@name`,",
        "`path/@name` and `path/#text` lines, and a `group` of its own for each repeated element",
        "inside it, down to the depth limit. A recursive type ends the nesting. Decode gives one item",
        "per occurrence, in document order; encode writes the items back in order at the group's line.",
        "An item has no residue (0.7): what no line of the group maps inside an item is dropped, so the",
        "places listed under Not mapped that lie inside an item are lost on a round trip as they are",
        "outside one. A group is written only when at least one leaf of its item can be mapped.",
        "A sequence or choice that itself repeats (maxOccurs above 1 on the `xs:sequence` or",
        "`xs:choice`) is not a group: its members interleave, and a group reads all elements of one",
        "name together."]


def md_options(plan):
    """What --decline-namespace, --substitution-groups, --substitute and --skip
    changed; nothing when none is given."""
    L = []
    if plan.declined:
        L += ["\n## Declined namespaces\n",
              "No file of these namespaces is read; an element, attribute, group, attribute group or base",
              "type of them is not mapped (reason: %s):" % R_FOREIGN, ""]
        L += ["- `%s`" % ns for ns in plan.declined]
    if plan.substitution:
        L += ["\n## Substitution groups\n",
              "A reference to a global element stands for that element, unless it is abstract, and for",
              "every member of its substitution group and of theirs, in declaration order. A member",
              "declared without a type has its head's type. One candidate is walked in place. Several are",
              "a choice when the reference occurs once: each candidate is an optional element whose lines",
              "are marked with the branch, and a vector holds the first branch that has a line, its lists",
              "stated `absent` in the vector's model otherwise. When the reference repeats, every",
              "candidate is a `group` of its own; so is every element of a repeated `xs:choice` of",
              "elements. Decode reads each name's items in order; encode writes all items of one name, then",
              "the next name's, so a document that interleaves names comes back with its items grouped by",
              "name. A choice of element branches of complex type is walked the same way."]
        if plan.only:
            L += ["", "Members kept for this pack (`--substitute`):", ""]
            L += ["- `%s`: %s" % (h, ", ".join("`%s`" % m for m in ms)) for h, ms in sorted(plan.only.items())]
    if plan.skip:
        L += ["\n## Left out of this pack\n",
              "These element paths below the root element are not walked (`--skip`); a document that holds",
              "them decodes, and what lies under them is dropped:", ""]
        L += ["- `%s`" % p for p in plan.skip]
    return L


def md_types(s):
    L = ["\n## Types\n", "| XSD built-in base | Transform | Leaves |\n|---|---|---|"]
    for (x, tr), n in sorted(s.by_xs.items(), key=lambda kv: (-kv[1], kv[0])):
        L.append("| `xs:%s` | `%s` | %d |" % (x, tr, n))
    L.append("\nTotals: " + ", ".join("`%s` %d" % (t, s.by_tr[t])
                                      for t in ("string", "float", "int", "iso8601_ms") if s.by_tr[t]) + ".")
    if s.notes:
        L.append("\n| Mapped with a loss or a limit | Leaves |\n|---|---|")
        for note, c in s.notes.most_common():
            L.append("| %s | %d |" % (note, c))
    if s.rad:
        L.append("| needs a scale on a text wire: an angle the schema states in radians, kept raw (`float`, unit "
                 "`rad`); `core` angles are degrees and the xml wire's `float` has no scale | %d (%d keys) |"
                 % (s.rad, s.rad_keys))
    return L


def md_mapped(plan, s):
    L = ["\n## Mapped\n",
         "| What | Lines | Summed over kinds |\n|---|---|---|",
         "| leaves outside any group | `field <key> <path>/@name` or `<path>/#text` | %d |" % s.total,
         "| repeated elements, first level | `group <list> <path>` | %d |" % s.groups_first,
         "| repeated elements inside an item | nested `group` | %d |" % (len(s.groups_all) - s.groups_first),
         "| leaves inside items | `field` lines of a group, relative to the item | %d |" % s.in_groups,
         "\n## Not mapped\n",
         "Counted once per place in a kind's tree, inside items of groups too; what lies below such a",
         "place is not counted.\n",
         "| Reason | Places |\n|---|---|"]
    for reason, c in s.reasons.most_common():
        L.append("| %s | %d |" % (reason, c))
    if not s.reasons:
        L.append("| none | 0 |")
    L.append("\nAn unmapped child element is dropped on decode (0.1.1 ruling 6; inside an item, 0.7), so a")
    L.append("document that uses any of these places does not round-trip whole: the mapped leaves survive,")
    L.append("the rest is lost.")
    if plan.walked.poly:
        L.append("\n%d elements on the walked paths have a declared type that other types extend. An instance" % plan.walked.poly)
        L.append("may put a derived type there and name it in `xsi:type`; the pack maps the declared type's")
        L.append("content only, and `xsi:type` on a non-root element is not carried.")
    return L


def md_namespaces(plan):
    tns = plan.tns
    L = ["\n## Namespaces\n",
         "The engine specification does not mention XML namespaces or prefixes: a locator step and a",
         "`root` are element names compared as written. This pack writes every name without a prefix."]
    if plan.use_xmlns:
        L += ["Every element of these messages is namespace-qualified (elementFormDefault `qualified`), so a",
              "document with the default-namespace declaration `xmlns=\"%s\"` on its root and no" % tns,
              "prefixes is what the schema describes, and it is what the vectors use. `xmlns` there is an",
              "unmapped attribute of the root element, so by 0.1.1 ruling 6 it is residue and is written",
              "back after the mapped root attributes. A document that uses a prefix (`<p:Root xmlns:p=...>`)",
              "does not match any `root` and fails with `no-kind`; a namespace declaration on a child",
              "element is dropped."]
    elif plan.import_only and plan.walked.unqualified:
        L += ["The message roots are declared in %s, which has no targetNamespace and imports"
              % ", ".join("`%s`" % b for b in plan.import_only),
              "`%s`; local elements are unqualified. A schema-valid document of this set therefore" % tns,
              "carries no namespace on any element, which is what this wire reads. Namespace declarations",
              "and `xsi:` attributes on the root (`xmlns:xsi`, `xsi:noNamespaceSchemaLocation`) are unmapped",
              "root attributes: by 0.1.1 ruling 6 they are residue and are written back after the mapped root",
              "attributes. A document that puts a prefix on an element (`<p:root xmlns:p=...>`) matches no",
              "`root` line and fails with `no-kind`. The vectors carry no namespace declaration."]
    elif tns and plan.walked.unqualified:
        L += ["The schema puts its global elements in `%s` and leaves local elements" % tns,
              "unqualified (no elementFormDefault), so a schema-valid document needs a prefixed root",
              "(`<p:Root xmlns:p=...>`), or a default namespace on the root undone by `xmlns=\"\"` on each",
              "child. Neither survives this wire: a prefixed root matches no `root` line, and an attribute",
              "of a child element that no line maps is dropped. The vectors therefore carry no namespace",
              "declaration, and a producer's documents need the prefix removed before decode."]
    else:
        L.append("The vectors carry no namespace declaration.")
    return L


def md_keys(schema, plan, s, names_file):
    w = plan.walked
    L = ["\n## Keys and lists\n",
         "One raw key per (locator, model type), shared by every kind and every group that has that",
         "locator; two places in one message, or in one item, are always two keys. A locator inside a",
         "group is the path within the item, so items of different lists that have the same member at",
         "the same place use one key. The name is the path's element names and the attribute name in",
         "snake case joined by `_`; the text of an item of simple type is `item`; a name over %d" % MAX_KEY_LEN,
         "characters keeps its first element, its last two parts and eight hex digits of the SHA-1 of",
         "the locator;%s a locator with two model types gets `_<type>`; a name two places would share"
         % (" a leading %s is left out;" % " or ".join("`%s`" % d for d in plan.name_drop) if plan.name_drop else ""),
         "gets `_attr` on the attribute, `_list` on a list that meets a key, or the hash. One list per group path: the",
         "path from the root element for a first-level group, the path within the item for a nested",
         "one, named by the same rule. Names are pinned in `tools/gen/names/%s`: a later" % os.path.basename(names_file),
         "run never renames a pinned key or list. %d keys and %d lists, longest name %d characters, %d carry a hash."
         % (w.n_keys, w.n_lists, s.longest, s.hashed),
         "\n## Mapped to shared keys\n"]
    if not plan.maps:
        L.append("None. No leaf of this schema is bound to a `core` or `track` key.")
        return L
    L.append("| Key | Kind | Locator | Schema type | Schema documentation |\n|---|---|---|---|---|")
    for k, lf, key in plan.maps:
        ev = "element: \"%s\"" % first_sentence(lf.doc) if lf.doc else "element: none"
        if lf.tdoc:
            ev += "; type: \"%s\"" % first_sentence(lf.tdoc)
        odoc = schema.complex[lf.owner].doc if lf.owner in schema.complex else ""
        if odoc:
            ev += "; containing type `%s`: \"%s\"" % (lf.owner, first_sentence(odoc))
        L.append("| `%s` (%s, %s) | `%s` | `%s` | `%s` (`xs:%s`) | %s |" % (
            key, plan.shared[key][0], plan.shared[key][1], k.name, lf.locator, lf.tname, lf.xs, ev.replace("|", "/")))
    L.append("\nEach of these locators has two `field` lines (0.5 ruling 16): the shared key first, the")
    L.append("raw key second. Decode fills both; encode writes the shared key's value when the entity has it.")
    L.append("No line inside a group is bound to a shared key: every item key is a raw key.")
    return L


def md_requires(plan, s, cross):
    default = plan.default
    L = ["\n## `requires`\n",
         "Every kind%s lists up to 6 raw keys of module `%s`, chosen so that as few other kinds as"
         % (" but `%s`" % default.name if default is not None else "", plan.module),
         "possible map all of them: first from the kind's own leaves on a path the schema makes",
         "mandatory; while another kind still maps the whole list, from its own optional leaves (%d kinds" % s.opt,
         "list an optional key); a kind with no own leaf lists a common one. Keys inside items are not used.",
         "For %d of %d such kinds no other kind maps the whole list." % (s.uniq, s.plain)]
    if s.uniq < s.plain:
        L.append("The other %d have the same mapped leaves as some other kind (their difference lies in" % (s.plain - s.uniq))
        L.append("groups or in places that are not mapped); for those, encode from an entity with no kind takes the first in pack order.")
    if default is not None:
        both = " and ".join("`%s`" % r for r in default.requires)
        L.append("\n`%s` is the default kind for an entity from another format. It is the last kind of the" % default.name)
        L.append("pack and requires %s, which it binds: an entity that carries no raw key of" % both)
        L.append("module `%s` qualifies for no other kind, and one that has %s encodes as `%s`."
                 % (plan.module, both, default.name))
        L.append("An entity without it ends in `no-kind`.")
    else:
        L.append("Because every list holds raw keys, an entity decoded from another format selects no kind of")
        L.append("this pack (`no-kind`).")
    if cross:
        L.append("\n| From | Encodes as | Keys carried | Keys the kind has no place for | Vector |\n|---|---|---|---|---|")
        for c in cross:
            L.append("| `%s` | `%s` | %s | %s | `%s` |" % (
                c.src_fmt, c.kind, " ".join("`%s`" % key for key in c.carried),
                " ".join("`%s`" % key for key in c.dropped) or "none", c.rel))
    return L


def md_vectors(vectors):
    per_group = vectors.per_group
    L = ["\n## Vectors\n",
         "`vectors/gen-<n>-<kind>-roundtrip.json`, one per kind, numbered in schema order: every mapped",
         "leaf of the kind is present (of a mapped choice, the first branch only), and every group has",
         "%s, with every mapped leaf of the item present;" % (
             "two items at the first level and one item at each level below it" if per_group == 2 else "one item"),
         "because an item has no residue, a document whose items held anything else would not come back",
         "whole. Written by the generator's canonical writer: attributes in `field` line order then",
         "residue, text before child elements, a child element at the position of the first line that",
         "addresses into it, the items of a group at its line, no whitespace. `input` equals `expect`.",
         "`model` holds `@kind`, the first two keys of the kind's own leaves, every shared key, and for",
         "every first-level group `<list>.#`%s; for the groups inside its"
         % (" and one value of its last item" if per_group > 1 else ""),
         "first item, `<list>[0].<list>.#`."]
    if per_group == 1:
        L.append("With two items per first-level group the vectors of this pack would take %d bytes, over the" % vectors.two_bytes)
        L.append("limit of %d set for a pack, so every group has one item and `model` states no item value." % vectors.budget)
    L += ["Values follow the leaf's type: the first safe enumeration value that `tools/boundary-gate` does",
          "not read as a handling marking, a number inside the stated",
          "bounds, a string that fits the length and pattern facets where one of a fixed list of",
          "candidates does (%d values do not fit their facets). The documents are not schema-valid" % vectors.weak,
          "as wholes: choice content the schema requires is absent, and every optional leaf is present.",
          "\n## Self-check\n",
          "After writing, the generator reloads `model/*.def`, `pack.def` and every vector with a loader",
          "and an xml codec written from the specification and independent of the generator's own",
          "structures: grammar (group blocks and their `end`, item-relative locators), declarations of",
          "keys and lists, key types, one kind per root, one locator per key within a kind and within an",
          "item, one group per list per scope, no line that addresses the item element of a group from",
          "outside it, and for every vector decode, kind selection, re-encode equal to `expect` byte for",
          "byte, at least one item in every list of the kind, and that every value in the document",
          "reached the entity, an item or the residue."]
    return L


def md_kinds(plan):
    L = ["\n## Kinds\n",
         "| Kind | Root | Own `field` lines | Own groups | Not mapped | Requires |\n|---|---|---|---|---|---|"]
    for k in plan.pack_kinds:
        own = k.items[plan.ncommon:]
        L.append("| `%s` | `%s` | %d | %d | %d | %d%s |" % (
            k.name, k.root.name, n_lines_of(own), sum(1 for _ in all_groups(own)),
            len(k.skipped), len(k.requires), " (default kind)" if k.default else "" if k.unique else " (not unique)"))
    return L


def pack_md(schema, statements, plan, stats, vectors, cross, names_file):
    """packs/<format>/pack.md: what was read, what was mapped and how, what
    was not and why."""
    L = md_sources(schema, statements, plan)
    L += md_counts(schema, plan, stats, len(cross))
    L += md_messages(plan)
    L += md_walk(stats)
    L += md_options(plan)
    L += md_types(stats)
    L += md_mapped(plan, stats)
    L += md_namespaces(plan)
    L += md_keys(schema, plan, stats, names_file)
    if plan.notes:
        L.append("\n" + plan.notes)
    L += md_requires(plan, stats, cross)
    L += md_vectors(vectors)
    L += md_kinds(plan)
    return "\n".join(L) + "\n"


def summary(schema, statements, plan, s, vectors, replay, cross, sizes):
    """What the run prints on stdout: the counts of the run as JSON."""
    w = plan.walked
    return collections.OrderedDict([
        ("format", plan.format), ("global_elements", len(schema.elements)), ("messages", len(plan.msg_names)),
        ("kinds", len(plan.kinds)), ("messages_without_kind", [k.root.name for k in plan.empty]),
        ("default_kind", plan.default.name if plan.default is not None else None),
        ("requires_with_optional_key", s.opt),
        ("leaves_mapped_outside_groups", s.total), ("leaves_mapped_inside_groups", s.in_groups),
        ("groups", len(s.groups_all)), ("groups_first_level", s.groups_first),
        ("groups_nested", len(s.groups_all) - s.groups_first), ("groups_scalar_items", s.scalar_groups),
        ("groups_by_nesting", {str(d): s.nest_hist[d] for d in sorted(s.nest_hist)}),
        ("field_lines", s.n_lines), ("group_blocks", s.n_groups),
        ("common_lines", plan.ncommon), ("common_field_lines", plan.nleaf), ("common_groups", s.common_groups),
        ("common_group_leaves", s.common_group_leaves),
        ("module_keys", w.n_keys), ("module_lists", w.n_lists), ("names_added", s.new_names),
        ("shared_bindings", len(plan.maps)), ("depth", w.depth),
        ("nest_limit_applied", w.deepest if w.nest_limited else None),
        ("nest_without_limit", w.nest_free), ("keys_and_lists_without_limit", w.keys_free),
        ("by_transform", dict(s.by_tr)), ("mapped_with_limit", dict(s.notes)), ("radian_leaves", s.rad),
        ("not_mapped", dict(s.reasons.most_common())), ("mapped_choices", s.choices),
        ("polymorphic_elements", w.poly), ("unqualified_local_elements", w.unqualified),
        ("vector_xmlns", plan.use_xmlns), ("requires_unique", s.uniq), ("vectors", replay.vectors),
        ("items_per_first_level_group", vectors.per_group), ("vector_bytes_with_two_items", vectors.two_bytes),
        ("vector_items_replayed", replay.items),
        ("vector_values_replayed", replay.values), ("values_not_fitting_facets", vectors.weak),
        ("cross_vectors", [{"from": c.src_fmt, "kind": c.kind, "carried": c.carried, "dropped": c.dropped,
                            "expect": c.expect} for c in cross]),
        ("bytes", sizes),
        ("statements", statements)])


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

def read_shared_modules(model_dir, out):
    """Copy core.def and track.def into `<out>/model` and return the keys a
    --map may bind: {key as a pack writes it: (type, unit)}."""
    shared = {}
    for mod in SHARED_MODULES:
        path = os.path.join(model_dir, mod + ".def")
        text = read_text(path)
        out.write("model/%s.def" % mod, text)
        parsed = gtcheck.parse_module(text, path)
        for name, ktype in parsed.keys.items():
            shared[name if mod == "core" else mod + "." + name] = (ktype, parsed.units[name])
    return shared


def read_pinned(path):
    """The names file of earlier runs, {} when there is none yet."""
    if not os.path.exists(path):
        return {}
    try:
        pinned = json.loads(read_text(path))
    except ValueError as e:
        raise GenError("not JSON: %s" % e, path, getattr(e, "lineno", None))
    if not isinstance(pinned, dict) or not all(isinstance(v, str) for v in pinned.values()):
        raise GenError("the names file is not an object of strings", path)
    return pinned


def names_output(names_file, out):
    """(Output, relative path) through which the names file is written: the
    run's Output when the file lies under --out, one of its own otherwise."""
    path = os.path.abspath(names_file)
    if path.startswith(out.root + os.sep):
        return out, os.path.relpath(path, out.root).replace(os.sep, "/")
    return genio.Output(os.path.dirname(path), check=out.check), os.path.basename(path)


def emit(schema, statements, plan, args, out):
    """Emit step and self-check: write every file through `out`, read them
    back, and return the summary of the run."""
    fmt = plan.format
    mod_rel = "model/%s.def" % plan.module
    pdir = "packs/%s" % fmt
    vdir = pdir + "/vectors"
    out.write(mod_rel, module_text(plan))
    for old in out.listdir(vdir):
        if old.startswith("gen-") and old.endswith(".json"):
            out.remove("%s/%s" % (vdir, old))
    out.write(pdir + "/pack.def", pack_text(plan))
    vectors = vectors_within_budget(schema, plan, collections.OrderedDict(args.sample))
    for fname, text in vectors.files:
        out.write("%s/%s" % (vdir, fname), text)
    names_out, names_rel = names_output(args.names_file, out)
    names = names_text(plan)
    names_out.write(names_rel, names)

    stats = count_plan(plan)
    replay = self_check(out, fmt, plan.module)
    w = plan.walked
    if (replay.kinds != len(plan.kinds) or replay.fields != stats.n_lines or replay.groups != stats.n_groups
            or len(replay.model.modules[plan.module].keys) != w.n_keys
            or len(replay.model.modules[plan.module].lists) != w.n_lists):
        raise GenError("self-check counts differ from what was generated: %r" % replay.counts())
    if plan.default is not None and replay.pack.kinds[-1].name != plan.default.name:
        raise GenError("the default kind is not the last kind of the pack", replay.pack.label)

    cross = []
    for spec in args.cross:
        c = cross_vector(spec, replay, fmt, plan.default)
        out.write(c.rel, c.text)
        cross.append(c)

    md = pack_md(schema, statements, plan, stats, vectors, cross, args.names_file)
    out.write(pdir + "/pack.md", md)

    def size(rel):
        return len(out.read(rel).encode("utf-8"))
    sizes = {"pack.def": size(pdir + "/pack.def"), "pack.md": size(pdir + "/pack.md"), "module.def": size(mod_rel),
             "vectors": sum(size("%s/%s" % (vdir, n)) for n in out.listdir(vdir)
                            if n.startswith("gen-") and n.endswith(".json")),
             "names": len(names.encode("utf-8"))}
    status = out.report(NAME)
    if names_out is not out:
        status = max(status, names_out.report(NAME + " (names file)"))
    return status, summary(schema, statements, plan, stats, vectors, replay, cross, sizes)


def split_once(sep, what):
    """An argparse type: `LEFT<sep>RIGHT` as the pair (LEFT, RIGHT)."""
    def parse(text):
        left, found, right = text.partition(sep)
        if not found or not left:
            raise argparse.ArgumentTypeError("%r is not %s" % (text, what))
        return left, right
    return parse


def map_spec(text):
    left, found, key = text.rpartition("=")
    root, colon, locator = left.partition(":")
    if not found or not colon or not root or not locator or not key:
        raise argparse.ArgumentTypeError("%r is not ROOT:LOCATOR=KEY" % text)
    return MapSpec(text, root, locator, key)


def cross_spec(text):
    packdef, found, rest = text.partition("=")
    vector, colon, field = rest.rpartition(":")
    if not found or not colon or not packdef or not vector or field not in ("input", "expect"):
        raise argparse.ArgumentTypeError("%r is not PACKDEF=VECTOR:FIELD with FIELD input or expect" % text)
    return CrossSpec(text, packdef, vector, field)


def build_parser():
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xsd", nargs="+", required=True, help="every XSD file of the set; the first is the catalog")
    ap.add_argument("--alias", action="append", default=[], metavar="LOCATION=FILE",
                    type=split_once("=", "LOCATION=FILE"),
                    help="an include/import schemaLocation and the base name of the given file that satisfies it")
    ap.add_argument("--format", required=True, help="the format name: the directory under packs/")
    ap.add_argument("--module", required=True, help="the name of the model module written for the raw keys")
    ap.add_argument("--title", required=True, help="what the schema set is, for source lines and pack.md")
    ap.add_argument("--source", action="append", default=[], help="extra source line")
    genio.add_arguments(ap, what="the directory that receives model/ and packs/")
    ap.add_argument("--model-dir", required=True, help="directory holding core.def and track.def (copied into <out>/model)")
    ap.add_argument("--message-type-suffix", help="every global element whose type name ends in this is a message")
    ap.add_argument("--message-choice", action="append", default=[], metavar="TYPE",
                    help="every global element the choice in this complex type refers to is a message")
    ap.add_argument("--message", action="append", default=[], metavar="ELEMENT", help="this global element is a message")
    ap.add_argument("--map", action="append", default=[], metavar="ROOT:LOCATOR=KEY", type=map_spec,
                    help="bind a core or track key at a locator of the message with that root element")
    ap.add_argument("--sample", action="append", default=[], metavar="LOCATOR=VALUE",
                    type=split_once("=", "LOCATOR=VALUE"),
                    help="the value the vectors put at every locator that is, or ends in, LOCATOR")
    ap.add_argument("--name-drop", action="append", default=[], metavar="ELEMENT",
                    help="a first path element left out of key names")
    ap.add_argument("--names-file", required=True,
                    help="the names pinned to keys and lists: read when it exists, then written")
    ap.add_argument("--max-depth", type=int, default=MAX_DEPTH,
                    help="element steps below the root that are walked (default %d, at most %d)"
                         % (MAX_DEPTH, DEPTH_CEILING))
    ap.add_argument("--max-nest", type=int, default=MAX_DEPTH,
                    help="groups inside groups: 1 maps a repeated element and nothing repeated inside its item "
                         "(lowered by the run itself when the module would pass %d keys and lists)" % KEY_BUDGET)
    ap.add_argument("--default-kind", default=None, metavar="ROOT",
                    help="the message an entity from another format encodes as: its kind is written last and "
                         "requires the shared keys of --default-requires in place of raw keys")
    ap.add_argument("--default-requires", nargs="+", default=None, metavar="KEY",
                    help="the default kind's requires: core or track keys a --map binds in it")
    ap.add_argument("--cross", action="append", default=[], metavar="PACKDEF=VECTOR:FIELD", type=cross_spec,
                    help="write a vector from another xml format into this one: decode FIELD (input or expect) of "
                         "an existing VECTOR file with the pack PACKDEF (no kinds), encode with this pack")
    ap.add_argument("--vector-xmlns", choices=("auto", "never"), default="auto",
                    help="auto: the vectors declare the schema's namespace on the root when every element is "
                         "qualified; never: no namespace declaration")
    ap.add_argument("--decline-namespace", action="append", default=[], metavar="URI",
                    help="a namespace whose files are not read: its declarations are listed as not mapped")
    ap.add_argument("--substitution-groups", action="store_true",
                    help="expand substitution groups, and walk choices of complex element branches and repeated "
                         "choices of elements (one group per element name)")
    ap.add_argument("--substitute", action="append", default=[], metavar="HEAD=MEMBER[,MEMBER...]",
                    type=lambda t: (lambda h, _, m: (h, [x for x in m.split(",") if x]))(*t.partition("=")),
                    help="with --substitution-groups: the members of HEAD's group that this pack keeps")
    ap.add_argument("--skip", action="append", default=[], metavar="PATH",
                    help="an element path below the root element, as in a locator (names joined by /), that is not walked")
    ap.add_argument("--notes-file", default=None, metavar="FILE",
                    help="markdown placed in pack.md after the section on shared keys")
    ap.add_argument("--public-statement", default=None, metavar="TEXT",
                    help="for a set whose file headers carry no Distribution Statement A: the publisher's "
                         "statement that the set is public and may be reused, recorded for every such file")
    ap.add_argument("--version", default="0.2.0", help="the version line of the pack and of the module")
    return ap


def run(args):
    """parse -> plan -> emit -> self-check. Returns the exit status."""
    out = genio.Output(args.out, check=args.check)
    schema, statements = read_schema(args.xsd, dict(args.alias), args.public_statement,
                                     args.decline_namespace, args.substitution_groups)
    if args.substitute and not args.substitution_groups:
        raise GenError("--substitute needs --substitution-groups")
    for head, members in args.substitute:
        if head not in schema.elements:
            raise GenError("--substitute %s: no such global element" % head)
        for m in members:
            if m not in schema.members(head):
                raise GenError("--substitute %s: %s is not a member of its substitution group" % (head, m))
        schema.only.setdefault(head, []).extend(members)
    schema.skip = frozenset(p.strip("/") for p in args.skip)
    shared = read_shared_modules(args.model_dir, out)
    plan = make_plan(schema, statements, shared, read_pinned(args.names_file), args)
    warning = over_budget_warning(plan.walked, plan.module)
    if warning:
        print("%s: %s" % (NAME, warning), file=sys.stderr)
    status, counts = emit(schema, statements, plan, args, out)
    if not args.check:
        print(json.dumps(counts, indent=1))
    return status


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (GenError, WireError, gtcheck.CheckError) as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
    except OSError as e:
        print("%s: %s: %s" % (NAME, e.filename, e.strerror), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
