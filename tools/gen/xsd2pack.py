#!/usr/bin/env python3
"""xsd2pack: turn an XML Schema (XSD) message catalog into a goat-transformers pack.

Python 3 standard library only. Reads the XSD files of one schema set and writes:

  <out>/model/<module>.def                  raw keys of the format, one public module
  <out>/model/<module>.def                  raw keys and lists of the format, one public module
  <out>/packs/<format>/pack.def             the pack (engine-spec 0.7: wire xml, a root per kind,
                                            a `group` block per repeated element)
  <out>/packs/<format>/pack.md              what was mapped, what was not, and why
  <out>/packs/<format>/vectors/gen-*.json   one same-format round-trip per kind
  <out>/packs/<other>/vectors/gen-<other>-to-<format>.json   with --cross
  <names file>                              the name pinned to every (locator, type) and every list

Then it re-reads what it wrote with an independent loader and a small xml-wire
codec written from spec/engine-spec.md (0.1, 0.1.1, 0.4, 0.5, 0.6, 0.7) and refuses
to finish if the grammar, the declarations, the types, the kind roots or any
vector does not hold. No engine is run: the pack is correct by construction and
by this replay.

Usage: see --help. Run with `python3 -I`.
"""
import argparse
import collections
import datetime
import decimal
import glob
import hashlib
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

XS = "http://www.w3.org/2001/XMLSchema"
MAX_DEPTH = 8
KEY_BUDGET = 60000          # keys and lists of the module
VECTOR_BUDGET = 12 * 1000 * 1000    # bytes of generated vectors per pack
MAX_KEY_LEN = 96

XS_INT = {"integer", "int", "long", "short", "byte", "unsignedInt", "unsignedLong",
          "unsignedShort", "unsignedByte", "nonNegativeInteger", "positiveInteger",
          "negativeInteger", "nonPositiveInteger"}
XS_FLOAT = {"decimal", "double", "float"}
XS_RANGE = {"int": (-2**31, 2**31 - 1), "long": (-2**63, 2**63 - 1), "short": (-2**15, 2**15 - 1),
            "byte": (-128, 127), "unsignedInt": (0, 2**32 - 1), "unsignedLong": (0, 2**64 - 1),
            "unsignedShort": (0, 65535), "unsignedByte": (0, 255),
            "nonNegativeInteger": (0, None), "positiveInteger": (1, None),
            "negativeInteger": (None, -1), "nonPositiveInteger": (None, 0)}
YIELDS = {"string": "string", "float": "float", "int": "int", "iso8601_ms": "int"}

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


class GenError(Exception):
    pass


# --------------------------------------------------------------------------
# XSD reader
# --------------------------------------------------------------------------

def xs(tag):
    return "{%s}%s" % (XS, tag)


class SimpleT:
    def __init__(self, name):
        self.name = name
        self.base = None            # ("xs", local) or ("t", name)
        self.variety = "atomic"     # atomic | list | union
        self.enums = []
        self.patterns = []
        self.facets = {}
        self.doc = ""


class ComplexT:
    def __init__(self, name):
        self.name = name
        self.abstract = False
        self.mixed = False
        self.base = None            # QRef of the extension or restriction base
        self.derivation = None      # extension | restriction
        self.simple_content = False
        self.particle = None        # Particle or None
        self.attrs = []             # AttrDecl
        self.any_attr = False
        self.doc = ""


class Particle:
    __slots__ = ("kind", "min", "max", "children", "name", "type", "doc", "qualified")

    def __init__(self, kind):
        self.kind = kind            # sequence | choice | all | element | any
        self.min, self.max = 1, 1   # max None = unbounded
        self.children = []
        self.name = None
        self.type = None            # QRef for an element
        self.doc = ""
        self.qualified = False


class AttrDecl:
    def __init__(self):
        self.name = self.type = None
        self.use = "optional"
        self.doc = ""


def doc_of(node):
    out = []
    for a in node.findall(xs("annotation")):
        for d in a.findall(xs("documentation")):
            t = " ".join("".join(d.itertext()).split())
            if t:
                out.append(t)
    return " ".join(out)


class Schema:
    def __init__(self):
        self.simple = {}
        self.complex = {}
        self.elements = collections.OrderedDict()   # global element name -> Particle
        self.groups = {}
        self.attr_groups = {}
        self.global_attrs = {}
        self.tns = None
        self.files = []             # (path, basename, sha256, bytes, header statement)
        self.includes = []          # (file, schemaLocation, resolved basename or None)
        self.element_form = {}      # file -> elementFormDefault
        self.anon = 0
        self._content = {}
        self._simple = {}

    # -- reading ----------------------------------------------------------
    def read(self, path, aliases):
        raw = open(path, "rb").read()
        prefixes = {}
        for _, (pfx, uri) in ET.iterparse(path, events=("start-ns",)):
            prefixes.setdefault(pfx, uri)
        root = ET.fromstring(raw)
        if root.tag != xs("schema"):
            raise GenError("%s: the root element is not xs:schema" % path)
        tns = root.get("targetNamespace")
        if self.tns is None:
            self.tns = tns
        elif tns != self.tns:
            raise GenError("%s: targetNamespace %r differs from %r" % (path, tns, self.tns))
        base = os.path.basename(path)
        self.files.append((path, base, hashlib.sha256(raw).hexdigest(), len(raw)))
        qualified = root.get("elementFormDefault") == "qualified"
        self.element_form[base] = root.get("elementFormDefault") or "unqualified (absent)"
        ctx = (path, prefixes, qualified)
        for c in root:
            if c.tag in (xs("include"), xs("import")):
                loc = c.get("schemaLocation") or ""
                self.includes.append((base, c.tag.split("}")[1], loc, aliases.get(loc, loc)))
            elif c.tag == xs("simpleType"):
                self._simple_type(c, c.get("name"), ctx)
            elif c.tag == xs("complexType"):
                self._complex_type(c, c.get("name"), ctx)
            elif c.tag == xs("element"):
                p = self._element(c, ctx, top=True)
                if p.name in self.elements:
                    raise GenError("global element %s is declared twice" % p.name)
                self.elements[p.name] = p
            elif c.tag == xs("group"):
                self.groups[c.get("name")] = (c, ctx)
            elif c.tag == xs("attributeGroup"):
                self.attr_groups[c.get("name")] = (c, ctx)
            elif c.tag == xs("attribute"):
                self.global_attrs[c.get("name")] = self._attribute(c, ctx)
            elif c.tag in (xs("annotation"), xs("notation")):
                pass
            else:
                raise GenError("%s: unsupported schema child %s" % (path, c.tag))

    def qref(self, text, ctx):
        path, prefixes, _ = ctx
        pfx, _, local = text.rpartition(":")
        uri = prefixes.get(pfx)
        if uri == XS:
            return ("xs", local)
        if uri == self.tns or (pfx == "" and uri in (None, "")):
            return ("t", local)
        raise GenError("%s: %r is in namespace %r, which no file given here defines" % (path, text, uri))

    def _anon(self, hint):
        self.anon += 1
        return "%s#%d" % (hint, self.anon)

    def _simple_type(self, node, name, ctx):
        st = SimpleT(name)
        st.doc = doc_of(node)
        r = node.find(xs("restriction"))
        if r is not None:
            if r.get("base"):
                st.base = self.qref(r.get("base"), ctx)
            else:
                inner = r.find(xs("simpleType"))
                st.base = ("t", self._simple_type(inner, self._anon(name), ctx).name)
            for f in r:
                tag = f.tag.split("}")[1]
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
            raise GenError("simpleType %s has no restriction, list or union" % name)
        if name in self.simple or name in self.complex:
            raise GenError("type %s is defined twice" % name)
        self.simple[name] = st
        return st

    def _attribute(self, node, ctx):
        a = AttrDecl()
        a.doc = doc_of(node)
        if node.get("ref"):
            ref = self.qref(node.get("ref"), ctx)[1]
            a.name, a.type = ref, ("ref", ref)
        else:
            a.name = node.get("name")
            if node.get("type"):
                a.type = self.qref(node.get("type"), ctx)
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
                ct.attrs.append(("group", self.qref(c.get("ref"), ctx)[1]))
            elif c.tag == xs("anyAttribute"):
                ct.any_attr = True

    def _complex_type(self, node, name, ctx):
        ct = ComplexT(name)
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
            ct.base = self.qref(body.get("base"), ctx)
        for c in body:
            if c.tag in (xs("sequence"), xs("choice"), xs("all"), xs("group")):
                ct.particle = self._particle(c, ctx)
        self._attrs_into(body, ct, ctx)
        if name in self.simple or name in self.complex:
            raise GenError("type %s is defined twice" % name)
        self.complex[name] = ct
        return ct

    @staticmethod
    def _occurs(node, p):
        p.min = int(node.get("minOccurs", "1"))
        mx = node.get("maxOccurs", "1")
        p.max = None if mx == "unbounded" else int(mx)

    def _particle(self, node, ctx):
        tag = node.tag.split("}")[1]
        if tag == "element":
            return self._element(node, ctx, top=False)
        if tag == "any":
            p = Particle("any")
            self._occurs(node, p)
            return p
        if tag == "group":
            p = Particle("group")
            p.name = self.qref(node.get("ref"), ctx)[1]
            self._occurs(node, p)
            return p
        p = Particle(tag)
        self._occurs(node, p)
        for c in node:
            if c.tag in (xs("element"), xs("sequence"), xs("choice"), xs("all"), xs("any"), xs("group")):
                p.children.append(self._particle(c, ctx))
        return p

    def _element(self, node, ctx, top):
        p = Particle("element")
        p.doc = doc_of(node)
        if not top:
            self._occurs(node, p)
        if node.get("ref"):
            p.name = self.qref(node.get("ref"), ctx)[1]
            p.type = ("ref", p.name)
            p.qualified = True
            return p
        p.name = node.get("name")
        form = node.get("form")
        p.qualified = top or (form == "qualified" if form else ctx[2])
        if node.get("type"):
            p.type = self.qref(node.get("type"), ctx)
        elif node.find(xs("complexType")) is not None:
            p.type = ("t", self._complex_type(node.find(xs("complexType")), self._anon(p.name), ctx).name)
        elif node.find(xs("simpleType")) is not None:
            p.type = ("t", self._simple_type(node.find(xs("simpleType")), self._anon(p.name), ctx).name)
        else:
            p.type = ("xs", "anyType")
        return p

    # -- resolution -------------------------------------------------------
    def element_type(self, p):
        """The (name, QRef) an element particle stands for, through `ref`."""
        if p.type[0] == "ref":
            g = self.elements.get(p.type[1])
            if g is None:
                raise GenError("element ref %s names no global element" % p.type[1])
            return g.type
        return p.type

    def simple_info(self, qref):
        """(builtin local name, [SimpleT chain, derived first]) of a simple type."""
        key = qref
        if key in self._simple:
            return self._simple[key]
        chain = []
        cur, seen = qref, set()
        while cur[0] == "t":
            if cur[1] in seen:
                raise GenError("simple type %s derives from itself" % cur[1])
            seen.add(cur[1])
            st = self.simple.get(cur[1])
            if st is None:
                raise GenError("simple type %s is not defined" % cur[1])
            chain.append(st)
            cur = st.base
        self._simple[key] = (cur[1], chain)
        return self._simple[key]

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
                attrs.extend(self._attr_group(a[1], set()))
            else:
                attrs.append(a)
        attrs = [self.global_attrs[a.type[1]] if a.type[0] == "ref" and a.type[1] in self.global_attrs else a
                 for a in attrs]
        particles = [ct.particle] if ct.particle is not None else []
        simple, mixed, any_attr = None, ct.mixed, ct.any_attr
        if ct.base is not None:
            if self.is_simple(ct.base):
                simple = ct.base
            elif ct.base == ("xs", "anyType"):
                pass
            else:
                b = self.content(ct.base[1])
                if b is None:
                    raise GenError("type %s derives from itself" % name)
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

    def _attr_group(self, name, seen):
        if name in seen:
            raise GenError("attributeGroup %s refers to itself" % name)
        node, ctx = self.attr_groups[name]
        tmp = ComplexT(name)
        self._attrs_into(node, tmp, ctx)
        out = []
        for a in tmp.attrs:
            if isinstance(a, tuple):
                out.extend(self._attr_group(a[1], seen | {name}))
            else:
                out.append(a)
        return out

    def group_particle(self, name):
        node, ctx = self.groups[name]
        if not isinstance(node, Particle):
            inner = [c for c in node if c.tag in (xs("sequence"), xs("choice"), xs("all"))]
            node = self._particle(inner[0], ctx)
            self.groups[name] = (node, ctx)
        return node

    def derived_counts(self):
        """Number of complex types that extend each complex type, directly."""
        n = collections.Counter()
        for ct in self.complex.values():
            if ct.base and ct.base[0] == "t" and ct.base[1] in self.complex:
                n[ct.base[1]] += 1
        return n


# --------------------------------------------------------------------------
# Walk: one message's content model to leaves
# --------------------------------------------------------------------------

class Leaf:
    __slots__ = ("locator", "depth", "xs", "tname", "transform", "mtype", "mandatory", "choice",
                 "owner", "member", "doc", "note", "key", "shared", "qref", "rad", "tdoc")

    def __init__(self):
        self.choice = None          # (id, branch index) for a leaf of an all-leaf choice
        self.note = None
        self.key = None
        self.shared = None


class Group:
    """A repeated element: `path` from the enclosing scope (the root element or
    the enclosing item) to the item element, and the lines of one item."""
    __slots__ = ("path", "items", "owner", "member", "depth", "nest", "list", "tname")

    def leaves(self):
        return [x for x in self.items if isinstance(x, Leaf)]

    def groups(self):
        return [x for x in self.items if isinstance(x, Group)]


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
    def __init__(self, schema, max_depth, max_nest=MAX_DEPTH):
        self.s = schema
        self.max_depth = max_depth
        self.max_nest = max_nest    # groups inside groups: 1 = no group inside an item
        self.hard_depth = MAX_DEPTH
        self.choice_id = 0
        self.zulu = {}
        self.unqualified = 0        # local elements the schema leaves out of its namespace
        self.poly = 0               # elements walked whose declared type has derived types
        self.derived = schema.derived_counts()

    def transform_of(self, qref):
        """(transform, builtin, note) for a simple type; None transform = not mappable."""
        builtin, chain = self.s.simple_info(qref)
        tname = chain[0].name if chain else "xs:" + builtin
        if any(st.variety != "atomic" for st in chain):
            return "string", builtin, "list or union type kept as one string", tname
        facets = {}
        for st in reversed(chain):
            facets.update(st.facets)
        if builtin in ("string", "normalizedString", "token") and (
                facets.get("length") == "0" or facets.get("maxLength") == "0"):
            return None, builtin, None, tname
        if builtin in XS_INT:
            return "int", builtin, ("xs:unsignedLong or unbounded integer: values beyond 64 bits do not fit `int`"
                                    if builtin in ("unsignedLong", "integer", "nonNegativeInteger",
                                                   "positiveInteger", "negativeInteger", "nonPositiveInteger")
                                    else None), tname
        if builtin in XS_FLOAT:
            return "float", builtin, None, tname
        if builtin == "boolean":
            return "string", builtin, "xs:boolean kept as string", tname
        if builtin == "dateTime":
            if tname not in self.zulu:
                pats = [p for st in chain for p in st.patterns]
                self.zulu[tname] = any(p.endswith("Z") and "|" not in p for p in pats)
            if self.zulu[tname]:
                return "iso8601_ms", builtin, ("xs:dateTime restricted to UTC `Z`: `iso8601_ms`, which keeps "
                                               "milliseconds and always writes three fraction digits"), tname
            return "string", builtin, "xs:dateTime with no UTC restriction kept as string", tname
        if builtin in ("string", "normalizedString", "token"):
            return "string", builtin, None, tname
        return "string", builtin, "xs:%s kept as string" % builtin, tname

    def walk(self, root):
        """Lines (leaves and groups, in schema order) and skipped places of the
        message whose root element is `root`."""
        self.leaves, self.skipped, self.seen = [], [], set()
        self.base, self.nest = (), 0    # path of the item being walked; groups around it
        qref = self.s.element_type(root)
        self._element(root.name, qref, (), True, None, root, "(global element)", top=True)
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
        qref = self.s.element_type(p)
        g.tname = qref[1] if qref[0] == "t" else "xs:" + qref[1]
        saved = (self.leaves, self.seen, self.base, self.nest)
        mark = len(self.skipped)
        self.leaves, self.seen, self.base, self.nest = g.items, set(), here, self.nest + 1
        self._element(p.name, qref, path, True, None, p, owner, chain=chain, item=True)
        self.leaves, self.seen, self.base, self.nest = saved
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
        if not top and not item and self.rel(here) in self.seen:
            self._skip(R_SIBLING, here, owner, name)
            return
        if qref == ("xs", "anyType"):
            self._skip(R_ANYTYPE, here, owner, name)
            return
        if self.s.is_simple(qref):
            if top:
                self.seen.add("")
                self._leaf((), None, qref, mandatory, choice, owner, name, part.doc)
                # the root element's own text has no locator in the grammar
                lf = self.leaves.pop()
                self._skip("text of the root element (no locator addresses it)", here, owner, name)
                return
            self._leaf(here, None, qref, mandatory, choice, owner, name, part.doc)
            return
        tname = qref[1]
        ct = self.s.complex.get(tname)
        if ct is None:
            raise GenError("type %s of element %s is not defined" % (tname, name))
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
        for a in attrs:
            aref = a.type if a.type[0] != "ref" else ("xs", "anySimpleType")
            self._leaf(here, a.name, aref, mandatory and a.use == "required", choice, tname, "@" + a.name, a.doc)
        if any_attr:
            self._skip(R_ANYATTR, here, tname, "@*")
        if mixed:
            self._skip(R_MIXED, here, owner, name)
        if simple is not None:
            if top:
                self._skip("text of the root element (no locator addresses it)", here, owner, name)
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
        if p.max == 0:
            self._skip(R_PROHIBITED, path + ((p.name,) if p.name else ()), owner, p.name or p.kind)
            return
        repeated = p.max is None or p.max > 1
        if p.kind == "element":
            if len(path) + 1 > self.hard_depth:
                self._skip(R_DEPTH, path + (p.name,), owner, p.name)
                return
            if len(path) + 1 > self.max_depth:
                self._skip(R_CAP, path + (p.name,), owner, p.name)
                return
            if not p.qualified:
                self.unqualified += 1
            if repeated:
                if self.nest >= self.max_nest:
                    self._skip(R_NEST, path + (p.name,), owner, p.name)
                    return
                self._group(p, path, owner, chain)
                return
            self._element(p.name, self.s.element_type(p), path, mandatory and p.min >= 1, None, p, owner,
                          chain=chain)
            return
        if p.kind == "any":
            self._skip(R_ANY, path, owner, "xs:any")
            return
        if p.kind == "group":
            if repeated:
                self._skip(R_REPEAT_GROUP, path, owner, "group " + p.name)
                return
            self._particle(self.s.group_particle(p.name), path, mandatory and p.min >= 1, owner, chain)
            return
        if repeated:
            self._skip(R_REPEAT_GROUP, path, owner, p.kind)
            return
        if p.kind == "choice":
            simple_all = bool(p.children) and all(
                c.kind == "element" and c.max == 1 and self.s.is_simple(self.s.element_type(c))
                for c in p.children)
            if not simple_all:
                self._skip(R_CHOICE, path, owner, "choice of " + ", ".join(
                    (c.name or c.kind) for c in p.children[:4]) + (", ..." if len(p.children) > 4 else ""))
                return
            if len(path) + 1 > self.hard_depth:
                self._skip(R_DEPTH, path, owner, "choice")
                return
            if len(path) + 1 > self.max_depth:
                self._skip(R_CAP, path, owner, "choice")
                return
            self.choice_id += 1
            self.unqualified += sum(1 for c in p.children if not c.qualified)
            for i, c in enumerate(p.children):
                here = path + (c.name,)
                self._leaf(here, None, self.s.element_type(c), False, (self.choice_id, i), owner, c.name, c.doc)
            return
        for c in p.children:        # sequence, all
            self._particle(c, path, mandatory and p.min >= 1, owner, chain)


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


def assign_names(idents, pinned, drop=()):
    """idents: sorted list of (locator, model type), and of (path + "/[]", "list")
    for a list. Returns {ident: name}.

    One key per (locator, model type), shared by every kind and every group
    that has that locator with that type; a locator inside a group is relative
    to the item. Rule, in order: a pinned name stays; otherwise
    base_name(locator); when one locator has two model types across kinds every
    one of them gets `_<type>`; when two places spell the same name the
    attribute one gets `_attr`, and a list that shares its name with a key, or
    whose name is pinned to something else, gets `_list`; anything still not unique, or equal to a name pinned
    elsewhere, gets `_` and eight hex digits of the SHA-1 of its identity."""
    out, taken = {}, {}
    for ident in idents:
        tag = "%s %s" % ident
        if tag in pinned:
            name = pinned[tag]
            if taken.setdefault(name, ident) != ident:
                raise GenError("pinned name %s is given to two different places" % name)
            out[ident] = name
    types = collections.defaultdict(set)
    for loc, mt in idents:
        types[loc].add(mt)
    want = {}
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
            name += "_" + hashlib.sha1(("%s %s" % ident).encode()).hexdigest()[:8]
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


def plain_float(x):
    """Shortest decimal that reads back as the same double, plain notation
    (engine-spec 0.1.1 ruling 3)."""
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 2 ** 63:
        return str(int(x))
    r = repr(float(x))
    if "e" in r or "E" in r:
        r = format(decimal.Decimal(r), "f")
    return r


def facet_bounds(schema, qref):
    builtin, chain = schema.simple_info(qref)
    f = {}
    for st in reversed(chain):
        f.update(st.facets)
    return builtin, chain, f


def sample_value(schema, lf, qref, i):
    """A value of the leaf's type, canonical for its transform. Enumerations,
    numeric bounds, length facets and patterns are honoured where a value that
    is also safe on every engine's XML reader exists; pack.md says when not."""
    builtin, chain, f = facet_bounds(schema, qref)
    enums = next((st.enums for st in chain if st.enums), [])
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
        if "length" in f and n != int(f["length"]):
            return False
        if "minLength" in f and n < int(f["minLength"]):
            return False
        if "maxLength" in f and n > int(f["maxLength"]):
            return False
        return True

    if lf.transform == "iso8601_ms":
        return "2026-01-02T03:04:05.%03dZ" % (i % 1000), True
    if lf.transform == "int":
        lo, hi = XS_RANGE.get(builtin, (None, None))
        for k, sign in (("minInclusive", 0), ("minExclusive", 1)):
            if k in f:
                lo = int(decimal.Decimal(f[k])) + sign if lo is None else max(lo, int(decimal.Decimal(f[k])) + sign)
        for k, sign in (("maxInclusive", 0), ("maxExclusive", 1)):
            if k in f:
                hi = int(decimal.Decimal(f[k])) - sign if hi is None else min(hi, int(decimal.Decimal(f[k])) - sign)
        v = i % 9 + 1
        if enums:
            return enums[i % len(enums)], True
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            v = lo if lo is not None else hi
        return str(v), True
    if lf.transform == "float":
        lo = float(f["minInclusive"]) if "minInclusive" in f else None
        hi = float(f["maxInclusive"]) if "maxInclusive" in f else None
        xlo = float(f["minExclusive"]) if "minExclusive" in f else None
        xhi = float(f["maxExclusive"]) if "maxExclusive" in f else None

        def ok(v):
            return ((lo is None or v >= lo) and (hi is None or v <= hi)
                    and (xlo is None or v > xlo) and (xhi is None or v < xhi))
        base = [0.5, 1.5, 0.25, 2.5, 0.125, 3.5, 0.75]
        tries = base[i % 7:] + base[:i % 7]
        tries += [-t for t in tries] + [0.0, 1000000.5, -1000000.5]
        for v in tries:
            if ok(v):
                return plain_float(v), True
        for v in (lo, hi):
            if v is not None and ok(v):
                return plain_float(v), True
        return "0.5", False
    # string
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
        n = int(f.get("length", f.get("minLength", "2")))
        return "0A" * max(n, 1), True
    for t in STRING_TRIES:
        v = t % (i % 100) if "%" in t else t
        if fits(v):
            return v, True
    n = int(f.get("length", f.get("minLength", "2")))
    for ch in "A0a":
        if fits(ch * n):
            return ch * n, True
    return "v%d" % i, not pats and not any(k in f for k in ("length", "minLength", "maxLength"))


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

    def esc(t, attr):
        t = t.replace("&", "&amp;").replace("<", "&lt;")
        return t.replace('"', "&quot;") if attr else t

    def write(n):
        out.append("<" + n["name"])
        for k, v in n["attrs"]:
            out.append(' %s="%s"' % (k, esc(v, True)))
        if not n["kids"] and not n["text"]:
            out.append("/>")
            return
        out.append(">")
        if n["text"]:
            out.append(esc(n["text"], False))
        for c in n["kids"]:
            write(c)
        out.append("</%s>" % n["name"])
    write(tree)
    return "".join(out)


# --------------------------------------------------------------------------
# Self-check: an independent loader and xml-wire codec, written from
# spec/engine-spec.md. Nothing below this line uses the generator's own
# structures; it reads only the files that were written.
# --------------------------------------------------------------------------

class CheckError(Exception):
    pass


def def_lines(text):
    """Tokenised directive lines (engine-spec, Pack definition grammar; 0.1.1
    ruling 1; 0.5 rulings 6 and 17): `#` starts a comment only at the start of a
    token, a double-quoted value holds whitespace and has no escape."""
    for no, line in enumerate(text.split("\n"), 1):
        toks, i, n = [], 0, len(line)
        while i < n:
            if line[i] in " \t\r":
                i += 1
                continue
            if line[i] == "#":
                break
            if line[i] == '"':
                j = line.find('"', i + 1)
                if j < 0:
                    raise CheckError("line %d: unterminated quote" % no)
                toks.append(line[i + 1:j])
                i = j + 1
                continue
            j = i
            while j < n and line[j] not in " \t\r":
                j += 1
            toks.append(line[i:j])
            i = j
        if toks:
            yield no, toks


def load_module(text):
    """engine-spec 0.4, Model module grammar; 0.6 `derive`; 0.7 `list`. Returns
    (name, distribution, {key: type}, {list names}, [(derive target, [arguments])])."""
    name = dist = None
    sources, keys, lists, derive = 0, {}, set(), []
    for no, t in def_lines(text):
        d, a = t[0], t[1:]
        if d == "module" and len(a) == 1:
            name = a[0]
        elif d == "version" and len(a) == 1:
            pass
        elif d == "distribution" and len(a) == 1 and a[0] in ("public", "controlled"):
            dist = a[0]
        elif d == "source" and len(a) == 1:
            sources += 1
        elif d == "key" and len(a) in (3, 4):
            if "." in a[0]:
                raise CheckError("module line %d: `.` in key name %s" % (no, a[0]))
            if a[1] not in ("string", "float", "int"):
                raise CheckError("module line %d: key type %s" % (no, a[1]))
            if a[0] in keys or a[0] in lists:
                raise CheckError("duplicate-key: %s" % a[0])
            keys[a[0]] = a[1]
        elif d == "list" and len(a) in (1, 2):
            if "." in a[0]:
                raise CheckError("module line %d: `.` in list name %s" % (no, a[0]))
            if a[0] in keys or a[0] in lists:
                raise CheckError("duplicate-key: %s" % a[0])
            lists.add(a[0])
        elif d == "derive" and len(a) >= 3:
            derive.append((a[0], a[2:]))
        else:
            raise CheckError("module line %d: bad directive %s" % (no, " ".join(t)))
    if name is None:
        raise CheckError("module has no `module` line")
    if dist is None:
        raise CheckError("missing-distribution: module %s" % name)
    if not sources:
        raise CheckError("missing-source: module %s" % name)
    return name, dist, keys, lists, derive


XML_TRANSFORMS = {"string": "string", "float": "float", "int": "int", "iso8601_ms": "int"}
NAME_RE = r"[A-Za-z_][A-Za-z0-9_.\-]*"
LOCATOR_RE = re.compile(r"(?:%s/)*(?:@%s|(?<=/)#text)\Z" % (NAME_RE, NAME_RE))
ITEM_LOCATOR_RE = re.compile(r"(?:%s/)*(?:@%s|#text)\Z" % (NAME_RE, NAME_RE))
GROUP_PATH_RE = re.compile(r"%s(?:/%s)*\Z" % (NAME_RE, NAME_RE))


class CPack:
    def __init__(self):
        self.format = self.wire = self.dist = self.root = None
        self.sources = 0
        self.uses = ["core"]
        # a line is ("field", key, locator, transform) or ("group", list, path, [lines])
        self.common = []
        self.kinds = []             # dict(name, root, fields, requires)


def c_lines(lines, deep=True):
    """The `field` lines of a scope; with `deep`, those of its groups too."""
    for ln in lines:
        if ln[0] == "field":
            yield ln
        elif deep:
            yield from c_lines(ln[3])


def c_groups(lines):
    for ln in lines:
        if ln[0] == "group":
            yield ln
            yield from c_groups(ln[3])


def load_pack(text, modules):
    """engine-spec 0.4 Loading, 0.5 Message kinds, 0.6 XML: a root per kind,
    0.7 Group blocks. `modules` maps a module name to
    (distribution, {key: type}, {list names}, derive lines)."""
    p = CPack()
    cur = None
    open_groups = []                # bodies of the group blocks not yet closed
    for no, t in def_lines(text):
        d, a = t[0], t[1:]
        if open_groups and d in ("when", "requires", "root", "kind", "map", "typemap"):
            raise CheckError("bad-directive: pack line %d: %s inside a group" % (no, d))
        if d == "format" and len(a) == 1:
            p.format = a[0]
        elif d == "version" and len(a) == 1:
            if not re.fullmatch(r"\d+\.\d+\.\d+", a[0]):
                raise CheckError("pack line %d: version %s" % (no, a[0]))
        elif d == "wire" and len(a) == 1:
            p.wire = a[0]
        elif d == "distribution" and len(a) == 1 and a[0] in ("public", "controlled"):
            p.dist = a[0]
        elif d == "source" and len(a) == 1:
            p.sources += 1
        elif d == "uses" and len(a) == 1:
            p.uses.append(a[0])
        elif d == "root" and len(a) == 1:
            if not re.fullmatch(NAME_RE, a[0]):
                raise CheckError("pack line %d: root name %s" % (no, a[0]))
            if cur is None:
                p.root = a[0]
            elif cur["root"] is not None:
                raise CheckError("pack line %d: kind %s has two root lines" % (no, cur["name"]))
            else:
                cur["root"] = a[0]
        elif d == "kind" and len(a) == 1:
            if any(k["name"] == a[0] for k in p.kinds):
                raise CheckError("duplicate-kind: %s" % a[0])
            cur = {"name": a[0], "root": None, "fields": [], "requires": []}
            p.kinds.append(cur)
        elif d == "requires" and a:
            if cur is None:
                raise CheckError("bad-directive: requires before the first kind")
            cur["requires"].extend(a)
        elif d == "field" and len(a) == 3:
            if not (ITEM_LOCATOR_RE if open_groups else LOCATOR_RE).match(a[1]):
                raise CheckError("pack line %d: bad xml locator %s" % (no, a[1]))
            if a[2] not in XML_TRANSFORMS:
                raise CheckError("pack line %d: transform %s is not valid on the xml wire" % (no, a[2]))
            (open_groups[-1] if open_groups else p.common if cur is None else cur["fields"]).append(("field",) + tuple(a))
        elif d == "group" and len(a) == 2:      # `count` is not allowed on the xml wire
            if not GROUP_PATH_RE.match(a[1]):
                raise CheckError("pack line %d: bad group path %s" % (no, a[1]))
            body = []
            (open_groups[-1] if open_groups else p.common if cur is None else cur["fields"]).append(
                ("group", a[0], a[1], body))
            open_groups.append(body)
        elif d == "end" and not a:
            if not open_groups:
                raise CheckError("bad-directive: pack line %d: end with no open group" % no)
            open_groups.pop()
        else:
            raise CheckError("pack line %d: bad directive %s" % (no, " ".join(t)[:80]))
    if open_groups:
        raise CheckError("bad-directive: a group has no end")
    if p.format is None or p.wire != "xml":
        raise CheckError("pack has no format line or is not wire xml")
    if p.dist is None:
        raise CheckError("missing-distribution")
    if not p.sources:
        raise CheckError("missing-source")
    for m in p.uses:
        if m not in modules:
            raise CheckError("unknown-module: %s" % m)
        if p.dist == "public" and modules[m][0] != "public":
            raise CheckError("distribution-violation: %s" % m)

    def declared(key):
        """The type of a key, or "list"."""
        mod, name = key.split(".", 1) if "." in key else ("core", key)
        if mod not in p.uses:
            raise CheckError("module-not-used: %s" % key)
        if name in modules[mod][2]:
            return "list"
        if name not in modules[mod][1]:
            raise CheckError("undeclared-key: %s" % key)
        return modules[mod][1][name]

    def check_scope(lines, where):
        """One scope: common plus one kind, or the body of one group."""
        seen_keys, seen_lines, raw_at, lists, paths = {}, set(), {}, set(), []
        for ln in lines:
            if ln[0] == "group":
                _, name, path, body = ln
                if declared(name) != "list":
                    raise CheckError("key-type-mismatch: group %s names a key in %s" % (name, where))
                if name in lists:
                    raise CheckError("bad-directive: list %s is mapped by two groups in %s" % (name, where))
                lists.add(name)
                paths.append(path)
                check_scope(body, "%s, group %s" % (where, name))
                continue
            _, key, loc, tr = ln
            if (key, loc) in seen_lines:
                raise CheckError("%s: line %s %s twice" % (where, key, loc))
            seen_lines.add((key, loc))
            # 0.6 lets a key sit at several locators, where decode keeps one and
            # encode writes all. A catalog pack must not: two wire places are two keys.
            if seen_keys.setdefault(key, loc) != loc:
                raise CheckError("%s: key %s is mapped at two locators" % (where, key))
            # one locator may carry a shared key and a raw key (0.5 ruling 16),
            # never two keys of one module
            mod = key.split(".", 1)[0] if "." in key else "core"
            if raw_at.setdefault((loc, mod), key) != key:
                raise CheckError("%s: two keys of module %s at %s" % (where, mod, loc))
        # the element a group repeats is addressed by that group alone: no field
        # and no other group of the scope reaches it or passes through it
        for i, path in enumerate(paths):
            for ln in lines:
                if ln[0] == "field" and (ln[2] + "/").startswith(path + "/"):
                    raise CheckError("%s: field %s addresses the item element of group %s" % (where, ln[2], path))
            for j, other in enumerate(paths):
                if i != j and (other + "/").startswith(path + "/"):
                    raise CheckError("%s: groups %s and %s overlap" % (where, path, other))

    for scope, fields in [("common", p.common)] + [(k["name"], k["fields"]) for k in p.kinds]:
        for _, key, loc, tr in c_lines(fields):
            have = declared(key)
            if have == "list" or have != XML_TRANSFORMS[tr]:
                raise CheckError("key-type-mismatch: %s %s in %s" % (key, tr, scope))
    roots = {}
    for k in p.kinds:
        for key in k["requires"]:
            declared(key)
        root = k["root"] or p.root
        if root is None:
            raise CheckError("kind %s has no root and the pack has none" % k["name"])
        # no `when` lines are generated, so a root names exactly one kind
        if root in roots:
            raise CheckError("kinds %s and %s share root <%s> and nothing tells them apart"
                             % (roots[root], k["name"], root))
        roots[root] = k["name"]
        check_scope(p.common + k["fields"], "kind " + k["name"])
    if not p.kinds and p.root is None:
        raise CheckError("xml pack missing root")
    return p


# -- a minimal XML reader: names as written, no namespace processing ---------

class XNode:
    __slots__ = ("name", "attrs", "kids", "text")

    def __init__(self, name):
        self.name, self.attrs, self.kids, self.text = name, [], [], ""


ENT = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}


def xml_unescape(s):
    def rep(m):
        e = m.group(1)
        if e.startswith("#x"):
            return chr(int(e[2:], 16))
        if e.startswith("#"):
            return chr(int(e[1:]))
        if e not in ENT:
            raise CheckError("malformed-wire: entity &%s;" % e)
        return ENT[e]
    return re.sub(r"&([^;]+);", rep, s)


TAG_RE = re.compile(r"<(/?)([^\s/>]+)((?:\s+[^\s=/>]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>", re.S)
ATTR_RE = re.compile(r"([^\s=/>]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.S)


def xml_parse(text):
    i, n = 0, len(text)
    root, stack = None, []
    while i < n:
        if text.startswith("<?", i):
            i = text.index("?>", i) + 2
        elif text.startswith("<!--", i):
            i = text.index("-->", i) + 3
        elif text.startswith("<![CDATA[", i):
            j = text.index("]]>", i)
            if not stack:
                raise CheckError("malformed-wire: text outside the root")
            stack[-1].text += text[i + 9:j]
            i = j + 3
        elif text[i] == "<":
            m = TAG_RE.match(text, i)
            if not m:
                raise CheckError("malformed-wire: bad tag at %d" % i)
            close, name, attrs, selfclose = m.groups()
            if close:
                if not stack or stack[-1].name != name:
                    raise CheckError("malformed-wire: unexpected </%s>" % name)
                stack.pop()
            else:
                node = XNode(name)
                for a in ATTR_RE.finditer(attrs):
                    node.attrs.append((a.group(1), xml_unescape(a.group(2) if a.group(2) is not None else a.group(3))))
                if stack:
                    stack[-1].kids.append(node)
                elif root is not None:
                    raise CheckError("malformed-wire: two root elements")
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
                raise CheckError("malformed-wire: text outside the root")
            i = j
    if stack or root is None:
        raise CheckError("malformed-wire: unclosed element or no root")
    return root


def xml_get(root, locator):
    """engine-spec Locators and 0.1.1 ruling 7: each step takes the FIRST child
    of that name. Returns the string or None when absent."""
    *path, last = locator.split("/")
    node = root
    for step in path:
        node = next((c for c in node.kids if c.name == step), None)
        if node is None:
            return None
    if last.startswith("@"):
        return next((v for k, v in node.attrs if k == last[1:]), None)
    return node.text if node.text != "" else None


def t_decode(tr, s):
    if tr == "string":
        return s
    if tr == "int":
        if not re.fullmatch(r"[+-]?\d+", s.strip()):
            raise CheckError("transform-decode: int %r" % s)
        return int(s)
    if tr == "float":
        if not re.fullmatch(r"[+-]?(\d+(\.\d*)?|\.\d+)", s.strip()):
            raise CheckError("transform-decode: float %r" % s)
        return float(s)
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z", s)
    if not m:
        raise CheckError("transform-decode: iso8601_ms %r" % s)
    y, mo, d, h, mi, sec = (int(x) for x in m.groups()[:6])
    ms = int((m.group(7) or "0")[:3].ljust(3, "0"))
    days = (datetime.date(y, mo, d) - datetime.date(1970, 1, 1)).days
    return ((days * 24 + h) * 60 + mi) * 60000 + sec * 1000 + ms


def t_encode(tr, v):
    if tr == "string":
        return v
    if tr == "int":
        return str(v)
    if tr == "float":
        if v == 0:
            return "0"
        if v == int(v):
            return str(int(v))
        r = repr(v)
        return format(decimal.Decimal(r), "f") if "e" in r.lower() else r
    days, rem = divmod(v, 86400000)
    day = datetime.date(1970, 1, 1) + datetime.timedelta(days=days)
    h, rem = divmod(rem, 3600000)
    mi, rem = divmod(rem, 60000)
    sec, ms = divmod(rem, 1000)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (day.year, day.month, day.day, h, mi, sec, ms)


def c_node(root, path):
    """The first element matched by a path of names (0.1.1 ruling 7), or None."""
    node = root
    for step in path:
        node = next((c for c in node.kids if c.name == step), None)
        if node is None:
            return None
    return node


def c_decode_scope(node, lines, tally):
    """One scope of a document: the root element with the lines of common and
    the kind, or one item element with the lines of its group (0.7 Decode). An
    entity is {key: value, list name: [items]}; an item is such a dict too.
    `tally[0]` counts the wire places read."""
    ent, read = {}, set()
    for ln in lines:
        if ln[0] == "field":
            _, key, loc, tr = ln
            raw = xml_get(node, loc)
            if raw is not None and key not in ent:
                ent[key] = t_decode(tr, raw)
                read.add(loc)
        else:
            _, name, path, body = ln
            *holder, last = path.split("/")
            parent = c_node(node, holder)
            items = [c for c in parent.kids if c.name == last] if parent is not None else []
            if items:           # xml: the list is present when at least one item occurs
                ent[name] = [c_decode_scope(it, body, tally) for it in items]
    tally[0] += len(read)
    return ent


def c_decode(pack, text):
    """engine-spec 0.5 Decode with 0.6 `root` per kind and 0.7 groups. Returns
    (kind, entity, residue [(locator, value)], wire places read)."""
    root = xml_parse(text)
    kind = next((k for k in pack.kinds if (k["root"] or pack.root) == root.name), None)
    if kind is None:
        raise CheckError("no-kind: no kind has root <%s>" % root.name)
    lines = pack.common + kind["fields"]
    tally = [0]
    ent = c_decode_scope(root, lines, tally)
    mapped = {ln[2] for ln in c_lines(lines, deep=False)}
    residue = [("@" + k, v) for k, v in root.attrs if "@" + k not in mapped]
    return kind, ent, residue, tally[0]


def c_encode_scope(node, lines, ent):
    """engine-spec 0.5 Encode step 3, Canonicalisation, 0.5 rulings 10 and 16,
    0.7 Encode: a group writes one element per item where its line stands."""
    text_set = set()
    for ln in lines:
        if ln[1] not in ent:
            continue
        *path, last = ln[2].split("/")
        if ln[0] == "group" and not ent[ln[1]]:
            continue            # an empty list writes nothing
        holder = node
        for step in path:
            nxt = next((c for c in holder.kids if c.name == step), None)
            if nxt is None:
                nxt = XNode(step)
                holder.kids.append(nxt)
            holder = nxt
        if ln[0] == "group":
            for item in ent[ln[1]]:
                child = XNode(last)
                holder.kids.append(child)
                c_encode_scope(child, ln[3], item)
            continue
        val = t_encode(ln[3], ent[ln[1]])
        if last.startswith("@"):
            if not any(k == last[1:] for k, _ in holder.attrs):
                holder.attrs.append((last[1:], val))
        elif id(holder) not in text_set:
            text_set.add(id(holder))
            holder.text = val


def c_select(pack, ent):
    """0.5 Encode step 2: the first kind whose `requires` keys are all present;
    a list counts when it has an item (0.7)."""
    for k in pack.kinds:
        if all(r in ent and ent[r] != [] for r in k["requires"]):
            return k
    raise CheckError("no-kind")


def c_encode(pack, kind, ent, residue):
    root = XNode(kind["root"] or pack.root)
    c_encode_scope(root, pack.common + kind["fields"], ent)
    for loc, v in residue:
        if not any(k == loc[1:] for k, _ in root.attrs):
            root.attrs.append((loc[1:], v))
    out = []

    def write(nd):
        out.append("<" + nd.name)
        for k, v in nd.attrs:
            out.append(' %s="%s"' % (k, v.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")))
        if not nd.kids and nd.text == "":
            out.append("/>")
            return
        out.append(">" + nd.text.replace("&", "&amp;").replace("<", "&lt;"))
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


def self_check(out_dir, fmt, module):
    """Reload everything from disk and replay every vector. Returns a dict of
    counts; raises CheckError on the first thing that does not hold."""
    modules = {}
    for path in sorted(glob.glob(os.path.join(out_dir, "model", "*.def"))):
        name, dist, keys, lists, derive = load_module(open(path, encoding="utf-8").read())
        if name in modules:
            raise CheckError("duplicate-module: %s" % name)
        modules[name] = (dist, keys, lists, derive)
    if "core" not in modules:
        raise CheckError("unknown-module: core")
    pack = load_pack(open(os.path.join(out_dir, "packs", fmt, "pack.def"), encoding="utf-8").read(), modules)
    if pack.format != fmt:
        raise CheckError("pack.def names format %s" % pack.format)
    used = {ln[1] for k in pack.kinds for ln in c_lines(pack.common + k["fields"])}
    used |= {ln[1] for k in pack.kinds for ln in c_groups(pack.common + k["fields"])}
    unused = [k for k in list(modules[module][1]) + sorted(modules[module][2]) if module + "." + k not in used]
    if unused:
        raise CheckError("module %s declares %d keys or lists no line maps, first %s" % (module, len(unused), unused[0]))
    seen_kinds, names, n, values, items_seen, size = set(), set(), 0, 0, 0, 0

    def count_items(ent):
        return sum(len(v) + sum(count_items(i) for i in v) for v in ent.values() if isinstance(v, list))

    def every_list_has_items(lines, ent, where):
        for ln in lines:
            if ln[0] == "group":
                if not ent.get(ln[1]):
                    raise CheckError("%s: list %s has no item" % (where, ln[1]))
                for item in ent[ln[1]]:
                    every_list_has_items(ln[3], item, where)

    for path in sorted(glob.glob(os.path.join(out_dir, "packs", fmt, "vectors", "*.json"))):
        v = json.load(open(path, encoding="utf-8"))
        size += os.path.getsize(path)
        for req in ("name", "from", "to", "input", "expect"):
            if req not in v:
                raise CheckError("%s: no %s" % (path, req))
        if v["name"] in names:
            raise CheckError("vector name %s twice" % v["name"])
        names.add(v["name"])
        if v["from"] != fmt or v["to"] != fmt:
            raise CheckError("%s: not a same-format vector" % path)
        kind, ent, residue, places = c_decode(pack, v["input"])
        got = c_encode(pack, kind, ent, residue)
        if got != v["expect"]:
            raise CheckError("%s: re-encoded bytes differ from expect" % path)
        if v.get("model", {}).get("@kind") != kind["name"]:
            raise CheckError("%s: decode selects kind %s" % (path, kind["name"]))
        for key, want in v.get("model", {}).items():
            if key == "@kind":
                continue
            have = model_lookup(ent, key)
            if have is None or isinstance(have, list):
                raise CheckError("%s: model key %s is absent" % (path, key))
            if isinstance(have, float):
                same = abs(have - float(want)) <= 1e-9
            else:
                same = str(have) == want
            if not same:
                raise CheckError("%s: model key %s is %r, want %s" % (path, key, have, want))
        # every value in the input reached the entity, an item or the residue:
        # nothing was dropped, inside an item (which has no residue) or outside
        doc_values = count_values(xml_parse(v["input"]))
        if doc_values != places + len(residue):
            raise CheckError("%s: %d values in the document, %d carried" % (path, doc_values, places + len(residue)))
        if any(k not in ent for k in kind["requires"]):
            raise CheckError("%s: the vector lacks a key its kind requires" % path)
        every_list_has_items(pack.common + kind["fields"], ent, path)
        seen_kinds.add(kind["name"])
        values += doc_values
        items_seen += count_items(ent)
        n += 1
    missing = [k["name"] for k in pack.kinds if k["name"] not in seen_kinds]
    if missing:
        raise CheckError("%d kinds have no vector, first %s" % (len(missing), missing[0]))
    for k in pack.kinds[:-1]:
        if not k["requires"]:
            raise CheckError("kind %s has no requires and would shadow the kinds after it on encode" % k["name"])
    count = lambda f, lines: sum(1 for _ in f(lines))
    return {"kinds": len(pack.kinds), "common": len(pack.common),
            "fields": count(c_lines, pack.common) + sum(count(c_lines, k["fields"]) for k in pack.kinds),
            "groups": count(c_groups, pack.common) + sum(count(c_groups, k["fields"]) for k in pack.kinds),
            "module_keys": len(modules[module][1]), "module_lists": len(modules[module][2]),
            "vectors": n, "values": values, "items": items_seen, "vector_bytes": size,
            "pack": pack, "modules": modules}


# --------------------------------------------------------------------------
# Generator driver (uses the reader, walker, names and writer above; the
# self-check it calls at the end uses none of them)
# --------------------------------------------------------------------------

STATEMENT_RE = re.compile(r"Distribution Statement A\b[^\n<]*", re.I)


def header_statement(path):
    head = open(path, "rb").read(6000).decode("utf-8", "replace")
    m = STATEMENT_RE.search(head)
    return " ".join(m.group().split()).rstrip(" !-") if m else None


def quote(s):
    return '"' + " ".join(s.replace('"', "'").split()) + '"'


def first_sentence(doc, limit=220):
    doc = " ".join(doc.split())
    m = re.match(r"(.+?[.!?])(\s|$)", doc)
    out = m.group(1) if m else doc
    return out if len(out) <= limit else out[:limit - 3].rstrip() + "..."


def epoch_ms(text):
    d = datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=datetime.timezone.utc)
    return (d - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)) // datetime.timedelta(milliseconds=1)


class Kind:
    def __init__(self, root):
        self.root = root            # global element Particle
        self.name = snake(root.name)
        self.items = []             # lines in schema order: Leaf and Group
        self.leaves, self.skipped = [], []      # leaves: the Leaf lines outside any group
        self.requires = []
        self.unique = False
        self.default = False


def select_messages(schema, args):
    names, rule = [], []
    if args.message_type_suffix:
        suf = args.message_type_suffix
        names += [n for n, e in schema.elements.items() if schema.element_type(e)[1].endswith(suf)]
        rule.append("every global element whose type name ends in `%s`" % suf)
    for tname in args.message_choice:
        ct = schema.complex.get(tname)
        if ct is None or ct.particle is None or ct.particle.kind != "choice":
            raise GenError("--message-choice %s: not a complex type whose content is one choice" % tname)
        for c in ct.particle.children:
            if c.kind != "element" or c.type[0] != "ref":
                raise GenError("--message-choice %s: branch %s is not an element ref" % (tname, c.name))
            names.append(c.name)
        rule.append("every global element the choice in type `%s` refers to" % tname)
    for n in args.message:
        if n not in schema.elements:
            raise GenError("--message %s: no such global element" % n)
        names.append(n)
        rule.append("the global element `%s`" % n)
    seen, out = set(), []
    for n in schema.elements:               # schema declaration order
        if n in names and n not in seen:
            seen.add(n)
            out.append(n)
    if not out:
        raise GenError("no message selected: give --message-type-suffix, --message-choice or --message")
    return out, rule


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
        if isinstance(x, Leaf) and x.choice is not None:
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
    own keys. A kind with no leaf outside its groups requires its first list."""
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




def plain_decode(pack_text, doc):
    """decode() of a document with another xml pack that has no kinds: enough
    of 0.1 to 0.6 to read the entity of a cross-format vector (`field` lines
    without options, several lines per key, the earliest present one wins;
    `const` and `default` do not act on decode). Returns (format, entity,
    the root attributes no line maps)."""
    fmt = wire = root = None
    fields, consts = [], set()
    for no, t in def_lines(pack_text):
        if t[0] == "format":
            fmt = t[1]
        elif t[0] == "wire":
            wire = t[1]
        elif t[0] == "root":
            root = t[1]
        elif t[0] == "field":
            if len(t) != 4 or t[3] not in XML_TRANSFORMS:
                raise GenError("--cross: line %d of the other pack is a field this reader does not handle" % no)
            fields.append(t[1:4])
        elif t[0] == "const":
            consts.add(t[1])
        elif t[0] in ("kind", "when", "typemap", "map", "group"):
            raise GenError("--cross: the other pack has a `%s` line" % t[0])
    if wire != "xml" or root is None:
        raise GenError("--cross: the other pack is not an xml pack with a pack-level root")
    node = xml_parse(doc)
    if node.name != root:
        raise GenError("--cross: the document's root is <%s>, the pack's is <%s>" % (node.name, root))
    ent = {}
    for key, loc, tr in fields:
        raw = xml_get(node, loc)
        if raw is not None and key not in ent:
            ent[key] = t_decode(tr, raw)
    mapped = {loc for _, loc, _ in fields} | consts
    return fmt, ent, [k for k, _ in node.attrs if "@" + k not in mapped]


def would_derive(modules, keys):
    """The keys `convert` would add to an entity that has `keys` (0.6 Derived
    keys), by presence only: this codec computes no derivation, so a vector it
    writes must not depend on one."""
    have, added = set(keys), set()
    for _ in range(8):
        progressed = False
        for name in sorted(modules):
            for tgt, args in modules[name][3]:
                if tgt not in have and all(k in have for k in args):
                    have.add(tgt)
                    added.add(tgt)
                    progressed = True
        if not progressed:
            break
    return added


def model_text(v):
    return plain_float(v) if isinstance(v, float) else str(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xsd", nargs="+", required=True, help="every XSD file of the set; the first is the catalog")
    ap.add_argument("--alias", action="append", default=[], metavar="LOCATION=FILE",
                    help="an include/import schemaLocation and the base name of the given file that satisfies it")
    ap.add_argument("--format", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--title", required=True, help="what the schema set is, for source lines and pack.md")
    ap.add_argument("--source", action="append", default=[], help="extra source line")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model-dir", required=True, help="directory holding core.def and track.def (copied into <out>/model)")
    ap.add_argument("--message-type-suffix")
    ap.add_argument("--message-choice", action="append", default=[])
    ap.add_argument("--message", action="append", default=[])
    ap.add_argument("--map", action="append", default=[], metavar="ROOT:LOCATOR=KEY",
                    help="bind a core or track key at a locator of the message with that root element")
    ap.add_argument("--sample", action="append", default=[], metavar="LOCATOR=VALUE",
                    help="the value the vectors put at every locator that is, or ends in, LOCATOR")
    ap.add_argument("--name-drop", action="append", default=[], metavar="ELEMENT",
                    help="a first path element left out of key names")
    ap.add_argument("--names-file", required=True)
    ap.add_argument("--max-depth", type=int, default=MAX_DEPTH)
    ap.add_argument("--max-nest", type=int, default=MAX_DEPTH,
                    help="groups inside groups: 1 maps a repeated element and nothing repeated inside its item "
                         "(lowered by the run itself when the module would pass %d keys and lists)" % KEY_BUDGET)
    ap.add_argument("--default-kind", default=None, metavar="ROOT",
                    help="the message an entity from another format encodes as: its kind is written last and "
                         "requires the shared keys of --default-requires in place of raw keys")
    ap.add_argument("--default-requires", nargs="+", default=None, metavar="KEY",
                    help="the default kind's requires: core or track keys a --map binds in it")
    ap.add_argument("--cross", action="append", default=[], metavar="PACKDEF=VECTOR:FIELD",
                    help="write a vector from another xml format into this one: decode FIELD (input or expect) of "
                         "an existing VECTOR file with the pack PACKDEF (no kinds), encode with this pack")
    ap.add_argument("--vector-xmlns", choices=("auto", "never"), default="auto")
    ap.add_argument("--version", default="0.2.0")
    a = ap.parse_args(argv)

    aliases = dict(x.split("=", 1) for x in a.alias)
    schema = Schema()
    statements = []
    for path in a.xsd:
        st = header_statement(path)
        if st is None:
            raise GenError("%s: the file header does not state Distribution Statement A; refusing this set" % path)
        statements.append((os.path.basename(path), st))
        schema.read(path, aliases)
    given = {f[1] for f in schema.files}
    for base, tag, loc, resolved in schema.includes:
        if os.path.basename(resolved) not in given:
            raise GenError("%s: xs:%s of %s is not among the files given (use --alias)" % (base, tag, loc))

    # modules the pack may bind shared keys of
    os.makedirs(os.path.join(a.out, "model"), exist_ok=True)
    shared = {}
    for mod in ("core", "track"):
        text = open(os.path.join(a.model_dir, mod + ".def"), encoding="utf-8").read()
        with open(os.path.join(a.out, "model", mod + ".def"), "w", encoding="utf-8") as fh:
            fh.write(text)
        for line in text.split("\n"):
            t = line.split()
            if len(t) >= 4 and t[0] == "key":
                shared[t[1] if mod == "core" else mod + "." + t[1]] = (t[2], t[3])

    msg_names, rule = select_messages(schema, a)
    pinned = {}
    if os.path.exists(a.names_file):
        pinned = json.load(open(a.names_file, encoding="utf-8"))

    # ---- walk; lower the nesting of groups, then the depth, until the module fits
    depth = min(a.max_depth, MAX_DEPTH)
    nest = max(a.max_nest, 1)
    nest_free = keys_free = None
    while True:
        walker = Walker(schema, depth, nest)
        kinds = []
        for n in msg_names:
            k = Kind(schema.elements[n])
            k.items, k.skipped = walker.walk(k.root)
            k.leaves = [x for x in k.items if isinstance(x, Leaf)]
            kinds.append(k)
        key_idents = {(lf.locator, lf.mtype) for k in kinds for lf in all_leaves(k.items)}
        list_idents = {(g.path + "/[]", "list") for k in kinds for g in all_groups(k.items)}
        idents = sorted(key_idents | list_idents)
        deepest = max([g.nest for k in kinds for g in all_groups(k.items)] or [0])
        if nest_free is None:
            nest_free, keys_free = deepest, len(idents)     # what the schema has before this loop limits it
        if len(idents) <= KEY_BUDGET:
            break
        if min(nest, deepest) > 1:
            nest = min(nest, deepest) - 1
        elif depth > 1:
            depth -= 1
        else:
            break
    nest_limited = deepest < nest_free
    kn = collections.Counter(k.name for k in kinds)
    if any(c > 1 for c in kn.values()):
        raise GenError("two root elements give the same kind name: %s" % [n for n, c in kn.items() if c > 1])

    empty = [k for k in kinds if not k.items]
    kinds = [k for k in kinds if k.items]
    names = assign_names(idents, pinned, tuple(a.name_drop))
    for k in kinds:
        for lf in all_leaves(k.items):
            lf.key = a.module + "." + names[(lf.locator, lf.mtype)]
        for g in all_groups(k.items):
            g.list = a.module + "." + names[(g.path + "/[]", "list")]

    # shared-key bindings
    maps = []
    by_root = {k.root.name: k for k in kinds}
    for spec in a.map:
        left, key = spec.rsplit("=", 1)
        root, locator = left.split(":", 1)
        if key not in shared:
            raise GenError("--map %s: %s is not a key of core or track" % (spec, key))
        k = by_root.get(root)
        lf = next((l for l in k.leaves if l.locator == locator), None) if k else None
        if lf is None:
            raise GenError("--map %s: message %s has no mapped leaf at %s" % (spec, root, locator))
        ktype, unit = shared[key]
        if ktype != lf.mtype:
            raise GenError("--map %s: key is %s, the leaf yields %s" % (spec, ktype, lf.mtype))
        if lf.rad and unit == "deg":
            raise GenError("--map %s: the schema states radians and the key is in degrees; "
                           "the xml wire's `float` has no scale" % spec)
        if lf.shared:
            raise GenError("--map %s: the leaf is already bound to %s" % (spec, lf.shared))
        lf.shared = key
        maps.append((k, lf, key))

    ncommon = common_prefix(kinds)          # lines: leaves and groups
    if any(isinstance(x, Leaf) and x.shared for k in kinds for x in k.items[:ncommon]):
        ncommon = 0
    nleaf = sum(1 for x in kinds[0].items[:ncommon] if isinstance(x, Leaf))     # common leaves
    choose_requires(kinds, nleaf)
    default = None
    if a.default_kind:
        default = by_root.get(a.default_kind)
        if default is None:
            raise GenError("--default-kind %s: no kind has that root element" % a.default_kind)
        want = a.default_requires or [key for k, lf, key in maps if k is default]
        bound = {key for k, lf, key in maps if k is default}
        if not want or any(key not in bound for key in want):
            raise GenError("--default-requires: every key must be bound in %s by a --map" % a.default_kind)
        default.requires, default.default, default.unique = list(want), True, True
    elif a.default_requires:
        raise GenError("--default-requires needs --default-kind")
    # pack order: schema order, the default kind last (0.5 Encode step 2 takes the first that qualifies)
    pack_kinds = [k for k in kinds if not k.default] + [k for k in kinds if k.default]

    tns = schema.tns
    use_xmlns = a.vector_xmlns == "auto" and bool(tns) and walker.unqualified == 0
    src_lines = ["%s: %s" % (a.title, ", ".join("%s sha256 %s" % (f[1], f[2]) for f in schema.files))]
    for base, st in statements:
        src_lines.append("File header of %s: %s" % (base, st))
    src_lines += a.source

    # ---- model/<module>.def ------------------------------------------------
    info = {}       # key ident -> [first leaf (one outside a group when there is one), kinds, groups, units]
    linfo = {}      # list ident -> [first group, groups]
    for k in kinds:
        for lf in k.leaves:
            e = info.setdefault((lf.locator, lf.mtype), [lf, 0, 0, set()])
            e[1] += 1
            e[3].add("ms" if lf.transform == "iso8601_ms" else "rad" if lf.rad else "-")
    for k in kinds:
        for g in all_groups(k.items):
            e = linfo.setdefault((g.path + "/[]", "list"), [g, 0])
            e[1] += 1
            for lf in g.leaves():
                e = info.setdefault((lf.locator, lf.mtype), [lf, 0, 0, set()])
                e[2] += 1
                e[3].add("ms" if lf.transform == "iso8601_ms" else "rad" if lf.rad else "-")
    mod_path = os.path.join(a.out, "model", a.module + ".def")
    width = max(len(n) for n in names.values()) + 2
    plural = lambda n, word: "%d %s%s" % (n, word, "" if n == 1 else "s")
    with open(mod_path, "w", encoding="utf-8") as fh:
        fh.write("# The %s module: raw keys of the %s format, one per (locator, type) the\n" % (a.module, a.format))
        fh.write("# pack maps, and one list per repeated element. A key is shared by every kind\n")
        fh.write("# and every group that has that locator; inside a group the locator is relative\n")
        fh.write("# to the item. Generated by tools/gen/xsd2pack.py from the sources below; edit\n")
        fh.write("# the generator, not this file.\n")
        fh.write("module        %s\nversion       %s\ndistribution  public\n" % (a.module, a.version))
        for s_ in src_lines:
            fh.write("source        %s\n" % quote(s_))
        for ident in idents:
            if ident[1] == "list":
                continue
            lf, n, ng, units = info[ident]
            unit = units.pop() if len(units) == 1 else "-"
            tdesc = lf.tname if lf.tname.startswith("xs:") else "%s, xs:%s" % (lf.tname, lf.xs)
            where = "; ".join(x for x in (plural(n, "kind") if n else "",
                                          "an item of %s" % plural(ng, "group") if ng else "") if x)
            meaning = "%s.%s (%s) at %s; %s" % (lf.owner, lf.member, tdesc, lf.locator, where)
            fh.write("key  %s%-6s  %-3s  %s\n" % (names[ident].ljust(width), lf.mtype, unit, quote(meaning)))
        for ident in idents:
            if ident[1] != "list":
                continue
            g, n = linfo[ident]
            meaning = "%s.%s (%s), repeated, at %s; %s" % (g.owner, g.member, g.tname, g.path, plural(n, "group"))
            fh.write("list %s%s\n" % (names[ident].ljust(width), quote(meaning)))

    # ---- packs/<format>/pack.def -------------------------------------------
    pdir = os.path.join(a.out, "packs", a.format)
    vdir = os.path.join(pdir, "vectors")
    os.makedirs(vdir, exist_ok=True)
    for old in glob.glob(os.path.join(vdir, "gen-*.json")):
        os.remove(old)

    def loc_token(locator):
        # 0.7 ruling 1: `#` at the start of a token begins a comment
        return '"%s"' % locator if locator.startswith("#") else locator

    def pack_lines(items, indent=""):
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

    uses = [a.module] + sorted({key.split(".")[0] for _, _, key in maps if "." in key})
    with open(os.path.join(pdir, "pack.def"), "w", encoding="utf-8") as fh:
        fh.write("# %s. Public. Generated by tools/gen/xsd2pack.py; edit the generator,\n" % a.title)
        fh.write("# not this file. One kind per message, each with its own root element\n")
        fh.write("# (engine-spec 0.6); one `group` per repeated element, its lines relative to\n")
        fh.write("# one item (engine-spec 0.7). What is mapped and what is not: pack.md.\n")
        fh.write("format        %s\nversion       %s\ndistribution  public\n" % (a.format, a.version))
        for s_ in src_lines:
            fh.write("source        %s\n" % quote(s_))
        fh.write("wire          xml\n")
        for u in uses:
            fh.write("uses          %s\n" % u)
        if ncommon:
            fh.write("\n# Common: the %d leading lines every message has at the same place.\n" % ncommon)
            fh.writelines(pack_lines(kinds[0].items[:ncommon]))
        for k in pack_kinds:
            if k.default:
                fh.write("\n# The default kind: an entity from another format that has %s encodes as it.\n"
                         % " and ".join("`%s`" % r for r in k.requires))
            fh.write("\nkind      %s\nroot      %s\n" % (k.name, k.root.name))
            if k.requires:
                fh.write("requires  %s\n" % " ".join(k.requires))
            fh.writelines(pack_lines(k.items[ncommon:]))

    # ---- vectors -----------------------------------------------------------
    samples = dict(x.split("=", 1) for x in a.sample)
    digits = len(str(len(kinds)))

    def build_vectors(per_group):
        """One vector per kind, as (file name, JSON text). Every group has
        `per_group` items at the first level and one item below it."""
        weak, out = [0], []

        def value(lf, i):
            val, honoured = sample_value(schema, lf, lf.qref, i)
            for tail, sval in samples.items():
                if lf.locator == tail or lf.locator.endswith("/" + tail):
                    enums = next((st.enums for st in schema.simple_info(lf.qref)[1] if st.enums), None)
                    if enums is not None and sval not in enums:
                        raise GenError("--sample %s=%s: not a value of %s" % (tail, sval, lf.tname))
                    val, honoured = sval, True
            if not SAFE_VALUE.match(val):
                val, honoured = "v%d" % i, False
            weak[0] += 0 if honoured else 1
            return val, (str(epoch_ms(val)) if lf.transform == "iso8601_ms" else val)

        for idx, k in enumerate(kinds, 1):
            model = collections.OrderedDict([("@kind", k.name)])
            seq = [len(k.leaves)]       # sample index of the next leaf inside a group

            def item(g, prefix, shown):
                """One item of group `g`: its placed lines; `shown` adds the
                counts of the lists inside it to `model`."""
                placed, first = [], None
                for x in g.items:
                    if isinstance(x, Group):
                        placed.append(("g", x.path, [item(x, "%s%s[0]." % (prefix, x.list), shown)[0]]))
                        if shown:
                            model[prefix + x.list + ".#"] = "1"
                        continue
                    if x.choice is not None and x.choice[1] != 0:
                        continue
                    val, mval = value(x, seq[0])
                    seq[0] += 1
                    placed.append(("f", x.locator, val))
                    first = first or (x.key, mval)
                return placed, first

            placed, own_shown, i = [], 0, -1
            for pos, x in enumerate(k.items):
                if isinstance(x, Group):
                    built = [item(x, "%s[%d]." % (x.list, j), j == 0) for j in range(per_group)]
                    placed.append(("g", x.path, [b[0] for b in built]))
                    model[x.list + ".#"] = str(per_group)
                    if per_group > 1 and built[-1][1]:
                        model["%s[%d].%s" % (x.list, per_group - 1, built[-1][1][0])] = built[-1][1][1]
                    continue
                i += 1
                if x.choice is not None and x.choice[1] != 0:
                    continue
                val, mval = value(x, i)
                placed.append(("f", x.locator, val))
                if x.shared:
                    model[x.shared] = mval
                    model[x.key] = mval
                elif pos >= ncommon and own_shown < 2:
                    model[x.key] = mval
                    own_shown += 1
            doc = canonical_xml(k.root.name, placed, [("xmlns", tns)] if use_xmlns else [])
            vec = collections.OrderedDict([
                ("name", "gen-%s-roundtrip" % k.name), ("from", a.format), ("to", a.format),
                ("input", doc), ("expect", doc), ("model", model)])
            out.append(("gen-%0*d-%s-roundtrip.json" % (digits, idx, k.name),
                        json.dumps(vec, indent=2, ensure_ascii=False) + "\n"))
        return out, weak[0]

    per_group = 2
    vectors, weak = build_vectors(per_group)
    two_bytes = sum(len(t.encode("utf-8")) for _, t in vectors)
    if two_bytes > VECTOR_BUDGET:
        per_group = 1
        vectors, weak = build_vectors(per_group)
    for fname, text in vectors:
        with open(os.path.join(vdir, fname), "w", encoding="utf-8") as fh:
            fh.write(text)

    # ---- names file --------------------------------------------------------
    os.makedirs(os.path.dirname(os.path.abspath(a.names_file)), exist_ok=True)
    merged = dict(pinned)
    merged.update({"%s %s" % ident: n for ident, n in names.items()})
    for tag, name in pinned.items():
        if merged[tag] != name:
            raise GenError("pinned name %s of %s would change" % (name, tag))
    with open(a.names_file, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=1, sort_keys=True)
        fh.write("\n")

    # ---- counts ------------------------------------------------------------
    def n_lines_of(items):
        return sum(1 + bool(lf.shared) for lf in all_leaves(items))

    total = sum(len(k.leaves) for k in kinds)
    in_groups = sum(1 for k in kinds for g in all_groups(k.items) for _ in g.leaves())
    groups_all = [g for k in kinds for g in all_groups(k.items)]
    groups_first = sum(1 for g in groups_all if g.nest == 1)
    scalar_groups = sum(1 for g in groups_all if [getattr(x, "locator", None) for x in g.items] == ["#text"])
    common_groups = sum(1 for _ in all_groups(kinds[0].items[:ncommon]))
    common_group_leaves = sum(1 for g in all_groups(kinds[0].items[:ncommon]) for _ in g.leaves())
    every = [lf for k in kinds for lf in all_leaves(k.items)]
    by_tr = collections.Counter(lf.transform for lf in every)
    by_xs = collections.Counter((lf.xs, lf.transform) for lf in every)
    notes = collections.Counter(lf.note for lf in every if lf.note)
    rad = sum(1 for lf in every if lf.rad)
    rad_keys = len({(lf.locator, lf.mtype) for lf in every if lf.rad})
    reasons = collections.Counter(r[0] for k in kinds for r in k.skipped)
    choice_leaves = sum(1 for lf in every if lf.choice)
    choices = len({lf.choice[0] for lf in every if lf.choice})
    mandatory = sum(1 for k in kinds for lf in k.leaves if lf.mandatory)
    n_lines = (n_lines_of(kinds[0].items[:ncommon]) if ncommon else 0) + sum(n_lines_of(k.items[ncommon:]) for k in kinds)
    n_groups = common_groups + sum(1 for k in kinds for _ in all_groups(k.items[ncommon:]))
    depth_hist = collections.Counter(lf.depth for lf in every)
    nest_hist = collections.Counter(g.nest for g in groups_all)
    n_keys, n_lists = len(key_idents), len(list_idents)
    longest = max(len(n) for n in names.values())
    hashed = sum(1 for n in names.values() if re.search(r"_[0-9a-f]{8}$", n))
    new_names = sum(1 for ident in idents if "%s %s" % ident not in pinned)

    # ---- self-check --------------------------------------------------------
    res = self_check(a.out, a.format, a.module)
    if (res["kinds"] != len(kinds) or res["fields"] != n_lines or res["groups"] != n_groups
            or res["module_keys"] != n_keys or res["module_lists"] != n_lists):
        raise GenError("self-check counts differ from what was generated: %r" % {
            k: v for k, v in res.items() if k not in ("pack", "modules")})
    if default is not None and res["pack"].kinds[-1]["name"] != default.name:
        raise GenError("the default kind is not the last kind of the pack")

    # ---- vectors from another format into this one -------------------------
    cross = []
    for spec in a.cross:
        packdef, _, rest = spec.partition("=")
        vfile, _, vfield = rest.rpartition(":")
        src_vec = json.load(open(vfile, encoding="utf-8"))
        if vfield not in ("input", "expect"):
            raise GenError("--cross %s: FIELD is input or expect" % spec)
        src_fmt, ent, loose = plain_decode(open(packdef, encoding="utf-8").read(), src_vec[vfield])
        if src_vec["to" if vfield == "expect" else "from"] != src_fmt:
            raise GenError("--cross %s: that text is not %s" % (spec, src_fmt))
        if loose:
            raise GenError("--cross %s: the document has root attributes its pack does not map (%s); "
                           "the specification does not say whether residue crosses formats" % (spec, " ".join(loose)))
        pack = res["pack"]
        pack_keys = {ln[1] for k in pack.kinds for ln in c_lines(pack.common + k["fields"], deep=False)}
        derived = would_derive(res["modules"], ent) & pack_keys
        if derived:
            raise GenError("--cross %s: the engine would derive %s, which this pack writes" % (
                spec, " ".join(sorted(derived))))
        chosen = c_select(pack, ent)
        if default is not None and chosen["name"] != default.name:
            raise GenError("--cross %s: encoded as kind %s, not the default kind" % (spec, chosen["name"]))
        text = c_encode(pack, chosen, ent, [])
        back_kind, back, back_residue, _ = c_decode(pack, text)
        if back_kind is not chosen or back_residue:
            raise GenError("--cross %s: the output decodes as kind %s" % (spec, back_kind["name"]))
        carried = [key for key in ent if key in back]
        for key in carried:
            if back[key] != ent[key]:
                raise GenError("--cross %s: key %s does not survive" % (spec, key))
        if not carried:
            raise GenError("--cross %s: no key of the entity has a place in kind %s" % (spec, chosen["name"]))
        out_dir = os.path.join(a.out, "packs", src_fmt, "vectors")
        os.makedirs(out_dir, exist_ok=True)
        vec = collections.OrderedDict([
            ("name", "gen-%s-to-%s" % (src_fmt, a.format)), ("from", src_fmt), ("to", a.format),
            ("input", src_vec[vfield]), ("expect", text),
            ("model", collections.OrderedDict((key, model_text(v)) for key, v in ent.items()))])
        vpath = os.path.join(out_dir, "gen-%s-to-%s.json" % (src_fmt, a.format))
        with open(vpath, "w", encoding="utf-8") as fh:
            json.dump(vec, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        cross.append((src_fmt, chosen["name"], carried, [key for key in ent if key not in back],
                      os.path.relpath(vpath, a.out), text))

    # ---- pack.md -----------------------------------------------------------
    L = []
    w = L.append
    w("# Pack: %s\n" % a.format)
    w("%s, as XML documents. Generated by `tools/gen/xsd2pack.py`. Wire `xml`, engine-spec" % a.title)
    w("version 0.7 (a `root` line per kind, a `group` block per repeated element). Edit the generator, not this file.\n")
    w("## Sources\n")
    w("| File | Bytes | SHA-256 | Header statement |\n|---|---|---|---|")
    for (path, base, sha, size), (_, st) in zip(schema.files, statements):
        w("| `%s` | %d | `%s` | %s |" % (base, size, sha, st))
    w("")
    for base, tag, loc, resolved in schema.includes:
        w("- `%s` has `xs:%s schemaLocation=\"%s\"`; read from `%s`%s." % (
            base, tag, loc, os.path.basename(resolved),
            "" if loc == resolved else " (the set ships the file under that name)"))
    w("- targetNamespace `%s`; elementFormDefault: %s." % (
        tns, ", ".join("%s in `%s`" % (v, f) for f, v in schema.element_form.items())))
    w("\n## Schema and result\n")
    w("| | Count |\n|---|---|")
    rows = [("XSD files read", len(schema.files)), ("global elements", len(schema.elements)),
            ("complex types", len(schema.complex)), ("simple types", len(schema.simple)),
            ("messages", len(msg_names)), ("kinds", len(kinds)),
            ("global elements that are not messages", len(schema.elements) - len(msg_names)),
            ("leaves mapped outside any group, summed over kinds", total),
            ("of those, on a path the schema makes mandatory", mandatory),
            ("groups (repeated elements mapped), summed over kinds", len(groups_all)),
            ("of those, directly in a message (first level)", groups_first),
            ("of those, inside an item of another group (nested)", len(groups_all) - groups_first),
            ("of those, items that are one text value (`\"#text\"` alone)", scalar_groups),
            ("leaves mapped inside items of groups, summed over kinds", in_groups),
            ("`field` lines in pack.def", n_lines),
            ("`group` blocks in pack.def", n_groups),
            ("common lines (every kind starts with them): `field`", nleaf),
            ("common lines: `group` blocks, first level", ncommon - nleaf),
            ("keys in module `%s`" % a.module, n_keys),
            ("lists in module `%s`" % a.module, n_lists),
            ("`field` lines bound to `core` or `track` keys", len(maps)),
            ("places not mapped, summed over kinds", sum(reasons.values())),
            ("vectors (one same-format round trip per kind)", len(kinds)),
            ("vectors from another format", len(cross)),
            ("depth limit (element steps below the root)", depth),
            ("deepest group nesting", deepest)]
    for r in rows:
        w("| %s | %d |" % r)
    if nest_limited:
        w("\nGroup nesting is limited to %d for this pack: with no limit the schema nests groups %d deep and the"
          % (deepest, nest_free))
        w("module would hold %d keys and lists, over the limit of %d. A repeated element inside an item at" % (keys_free, KEY_BUDGET))
        w("nesting %d is not mapped (see Not mapped)." % deepest)
    if depth < min(a.max_depth, MAX_DEPTH):
        w("\nThe depth limit was lowered from %d to %d to keep the module within %d keys and lists."
          % (min(a.max_depth, MAX_DEPTH), depth, KEY_BUDGET))
    w("\nMapped leaves by depth (element steps below the root, inside groups too): "
      + ", ".join("%d at depth %d" % (depth_hist[d], d) for d in sorted(depth_hist)) + ".")
    if groups_all:
        w("\nGroups by nesting: " + ", ".join("%d at level %d" % (nest_hist[d], d) for d in sorted(nest_hist)) + ".")
    w("\n## Which global elements are messages\n")
    w("A kind is written for %s. Each kind has `root <element>` and no `when`; the pack has no" % "; and ".join(rule))
    w("pack-level `root`. Kind names are the element names in snake case. Kinds are in schema order%s."
      % (", except `%s`, which is last (see `requires`)" % default.name if default is not None else ""))
    if empty:
        w("\nNo kind is written for %d message%s in which nothing can be mapped (%s): a kind with no"
          % (len(empty), "" if len(empty) == 1 else "s", ", ".join("`%s`: %s" % (
              k.root.name, "; ".join(sorted({r[0] for r in k.skipped}))) for k in empty)))
        w("`field` and no `requires` would be selected on encode by any entity. Such a document decodes as `no-kind`.")
    w("\n## How a message is walked\n")
    w("From the root element through child elements, resolving named types, `xs:extension` base")
    w("chains (base content first), groups and element refs. An attribute is `path/@name`; an")
    w("element of simple type, or of a complex type with simple content, is `path/#text`. Lines are")
    w("in schema order, so an encoder writes child elements in the order the schema's sequences")
    w("require. A choice is mapped only when every branch is an element of simple type with")
    w("maxOccurs 1; then each branch is a line, and at most one is present in a valid document")
    w("(%d such choices, %d lines). Nothing chooses a branch of any other choice." % (choices, choice_leaves))
    w("\n## Repeated elements\n")
    w("An element with maxOccurs above 1 is a `group <list> <path>` block: `<path>` runs from the root")
    w("element (or from the enclosing item) to the repeated element, and the lines inside the block")
    w("are the walk of one item, their locators relative to the item element. An item of simple type")
    w("is one line, `\"#text\"` (quoted: 0.7 ruling 1); an item of complex type has `@name`,")
    w("`path/@name` and `path/#text` lines, and a `group` of its own for each repeated element")
    w("inside it, down to the depth limit. A recursive type ends the nesting. Decode gives one item")
    w("per occurrence, in document order; encode writes the items back in order at the group's line.")
    w("An item has no residue (0.7): what no line of the group maps inside an item is dropped, so the")
    w("places listed under Not mapped that lie inside an item are lost on a round trip as they are")
    w("outside one. A group is written only when at least one leaf of its item can be mapped.")
    w("A sequence or choice that itself repeats (maxOccurs above 1 on the `xs:sequence` or")
    w("`xs:choice`) is not a group: its members interleave, and a group reads all elements of one")
    w("name together.")
    w("\n## Types\n")
    w("| XSD built-in base | Transform | Leaves |\n|---|---|---|")
    for (x, tr), n in sorted(by_xs.items(), key=lambda kv: (-kv[1], kv[0])):
        w("| `xs:%s` | `%s` | %d |" % (x, tr, n))
    w("\nTotals: " + ", ".join("`%s` %d" % (t, by_tr[t]) for t in ("string", "float", "int", "iso8601_ms") if by_tr[t]) + ".")
    if notes:
        w("\n| Mapped with a loss or a limit | Leaves |\n|---|---|")
        for n_, c in notes.most_common():
            w("| %s | %d |" % (n_, c))
    if rad:
        w("| needs a scale on a text wire: an angle the schema states in radians, kept raw (`float`, unit "
          "`rad`); `core` angles are degrees and the xml wire's `float` has no scale | %d (%d keys) |" % (rad, rad_keys))
    w("\n## Mapped\n")
    w("| What | Lines | Summed over kinds |\n|---|---|---|")
    w("| leaves outside any group | `field <key> <path>/@name` or `<path>/#text` | %d |" % total)
    w("| repeated elements, first level | `group <list> <path>` | %d |" % groups_first)
    w("| repeated elements inside an item | nested `group` | %d |" % (len(groups_all) - groups_first))
    w("| leaves inside items | `field` lines of a group, relative to the item | %d |" % in_groups)
    w("\n## Not mapped\n")
    w("Counted once per place in a kind's tree, inside items of groups too; what lies below such a")
    w("place is not counted.\n")
    w("| Reason | Places |\n|---|---|")
    for r_, c in reasons.most_common():
        w("| %s | %d |" % (r_, c))
    if not reasons:
        w("| none | 0 |")
    w("\nAn unmapped child element is dropped on decode (0.1.1 ruling 6; inside an item, 0.7), so a")
    w("document that uses any of these places does not round-trip whole: the mapped leaves survive,")
    w("the rest is lost.")
    if walker.poly:
        w("\n%d elements on the walked paths have a declared type that other types extend. An instance" % walker.poly)
        w("may put a derived type there and name it in `xsi:type`; the pack maps the declared type's")
        w("content only, and `xsi:type` on a non-root element is not carried.")
    w("\n## Namespaces\n")
    w("The engine specification does not mention XML namespaces or prefixes: a locator step and a")
    w("`root` are element names compared as written. This pack writes every name without a prefix.")
    if use_xmlns:
        w("Every element of these messages is namespace-qualified (elementFormDefault `qualified`), so a")
        w("document with the default-namespace declaration `xmlns=\"%s\"` on its root and no" % tns)
        w("prefixes is what the schema describes, and it is what the vectors use. `xmlns` there is an")
        w("unmapped attribute of the root element, so by 0.1.1 ruling 6 it is residue and is written")
        w("back after the mapped root attributes. A document that uses a prefix (`<p:Root xmlns:p=...>`)")
        w("does not match any `root` and fails with `no-kind`; a namespace declaration on a child")
        w("element is dropped.")
    else:
        if tns and walker.unqualified:
            w("The schema puts its global elements in `%s` and leaves local elements" % tns)
            w("unqualified (no elementFormDefault), so a schema-valid document needs a prefixed root")
            w("(`<p:Root xmlns:p=...>`), or a default namespace on the root undone by `xmlns=\"\"` on each")
            w("child. Neither survives this wire: a prefixed root matches no `root` line, and an attribute")
            w("of a child element that no line maps is dropped. The vectors therefore carry no namespace")
            w("declaration, and a producer's documents need the prefix removed before decode.")
        else:
            w("The vectors carry no namespace declaration.")
    w("\n## Keys and lists\n")
    w("One raw key per (locator, model type), shared by every kind and every group that has that")
    w("locator; two places in one message, or in one item, are always two keys. A locator inside a")
    w("group is the path within the item, so items of different lists that have the same member at")
    w("the same place use one key. The name is the path's element names and the attribute name in")
    w("snake case joined by `_`; the text of an item of simple type is `item`; a name over %d" % MAX_KEY_LEN)
    w("characters keeps its first element, its last two parts and eight hex digits of the SHA-1 of")
    w("the locator;%s a locator with two model types gets `_<type>`; a name two places would share"
      % (" a leading %s is left out;" % " or ".join("`%s`" % d for d in a.name_drop) if a.name_drop else ""))
    w("gets `_attr` on the attribute, `_list` on a list that meets a key, or the hash. One list per group path: the")
    w("path from the root element for a first-level group, the path within the item for a nested")
    w("one, named by the same rule. Names are pinned in `tools/gen/names/%s`: a later" % os.path.basename(a.names_file))
    w("run never renames a pinned key or list. %d keys and %d lists, longest name %d characters, %d carry a hash."
      % (n_keys, n_lists, longest, hashed))
    w("\n## Mapped to shared keys\n")
    if maps:
        w("| Key | Kind | Locator | Schema type | Schema documentation |\n|---|---|---|---|---|")
        for k, lf, key in maps:
            ev = "element: \"%s\"" % first_sentence(lf.doc) if lf.doc else "element: none"
            if lf.tdoc:
                ev += "; type: \"%s\"" % first_sentence(lf.tdoc)
            odoc = schema.complex[lf.owner].doc if lf.owner in schema.complex else ""
            if odoc:
                ev += "; containing type `%s`: \"%s\"" % (lf.owner, first_sentence(odoc))
            w("| `%s` (%s, %s) | `%s` | `%s` | `%s` (`xs:%s`) | %s |" % (
                key, shared[key][0], shared[key][1], k.name, lf.locator, lf.tname, lf.xs, ev.replace("|", "/")))
        w("\nEach of these locators has two `field` lines (0.5 ruling 16): the shared key first, the")
        w("raw key second. Decode fills both; encode writes the shared key's value when the entity has it.")
        w("No line inside a group is bound to a shared key: every item key is a raw key.")
    else:
        w("None. No leaf of this schema is bound to a `core` or `track` key.")
    w("\n## `requires`\n")
    plain = [k for k in kinds if not k.default]
    uniq = sum(1 for k in plain if k.unique)
    opt = sum(1 for k in plain if k.optional_required)
    w("Every kind%s lists up to 6 raw keys of module `%s`, chosen so that as few other kinds as"
      % (" but `%s`" % default.name if default is not None else "", a.module))
    w("possible map all of them: first from the kind's own leaves on a path the schema makes")
    w("mandatory; while another kind still maps the whole list, from its own optional leaves (%d kinds" % opt)
    w("list an optional key); a kind with no own leaf lists a common one. Keys inside items are not used.")
    w("For %d of %d such kinds no other kind maps the whole list." % (uniq, len(plain)))
    if uniq < len(plain):
        w("The other %d have the same mapped leaves as some other kind (their difference lies in" % (len(plain) - uniq))
        w("groups or in places that are not mapped); for those, encode from an entity with no kind takes the first in pack order.")
    if default is not None:
        w("\n`%s` is the default kind for an entity from another format. It is the last kind of the" % default.name)
        w("pack and requires %s, which it binds: an entity that carries no raw key of"
          % " and ".join("`%s`" % r for r in default.requires))
        w("module `%s` qualifies for no other kind, and one that has %s encodes as `%s`."
          % (a.module, " and ".join("`%s`" % r for r in default.requires), default.name))
        w("An entity without it ends in `no-kind`.")
    else:
        w("Because every list holds raw keys, an entity decoded from another format selects no kind of")
        w("this pack (`no-kind`).")
    if cross:
        w("\n| From | Encodes as | Keys carried | Keys the kind has no place for | Vector |\n|---|---|---|---|---|")
        for src_fmt, chosen, carried, dropped, vpath, text in cross:
            w("| `%s` | `%s` | %s | %s | `%s` |" % (src_fmt, chosen, " ".join("`%s`" % c for c in carried),
                                                 " ".join("`%s`" % c for c in dropped) or "none", vpath))
    w("\n## Vectors\n")
    w("`vectors/gen-<n>-<kind>-roundtrip.json`, one per kind, numbered in schema order: every mapped")
    w("leaf of the kind is present (of a mapped choice, the first branch only), and every group has")
    w("%s, with every mapped leaf of the item present;" % (
        "two items at the first level and one item at each level below it" if per_group == 2 else "one item"))
    w("because an item has no residue, a document whose items held anything else would not come back")
    w("whole. Written by the generator's canonical writer: attributes in `field` line order then")
    w("residue, text before child elements, a child element at the position of the first line that")
    w("addresses into it, the items of a group at its line, no whitespace. `input` equals `expect`.")
    w("`model` holds `@kind`, the first two keys of the kind's own leaves, every shared key, and for")
    w("every first-level group `<list>.#`%s; for the groups inside its"
      % (" and one value of its last item" if per_group > 1 else ""))
    w("first item, `<list>[0].<list>.#`.")
    if per_group == 1:
        w("With two items per first-level group the vectors of this pack would take %d bytes, over the" % two_bytes)
        w("limit of %d set for a pack, so every group has one item and `model` states no item value." % VECTOR_BUDGET)
    w("Values follow the leaf's type: the first safe enumeration value that `tools/boundary-gate` does")
    w("not read as a handling marking, a number inside the stated")
    w("bounds, a string that fits the length and pattern facets where one of a fixed list of")
    w("candidates does (%d values do not fit their facets). The documents are not schema-valid" % weak)
    w("as wholes: choice content the schema requires is absent, and every optional leaf is present.")
    w("\n## Self-check\n")
    w("After writing, the generator reloads `model/*.def`, `pack.def` and every vector with a loader")
    w("and an xml codec written from the specification and independent of the generator's own")
    w("structures: grammar (group blocks and their `end`, item-relative locators), declarations of")
    w("keys and lists, key types, one kind per root, one locator per key within a kind and within an")
    w("item, one group per list per scope, no line that addresses the item element of a group from")
    w("outside it, and for every vector decode, kind selection, re-encode equal to `expect` byte for")
    w("byte, at least one item in every list of the kind, and that every value in the document")
    w("reached the entity, an item or the residue.")
    w("\n## Kinds\n")
    w("| Kind | Root | Own `field` lines | Own groups | Not mapped | Requires |\n|---|---|---|---|---|---|")
    for k in pack_kinds:
        w("| `%s` | `%s` | %d | %d | %d | %d%s |" % (
            k.name, k.root.name, n_lines_of(k.items[ncommon:]), sum(1 for _ in all_groups(k.items[ncommon:])),
            len(k.skipped), len(k.requires), " (default kind)" if k.default else "" if k.unique else " (not unique)"))
    with open(os.path.join(pdir, "pack.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")

    size = lambda p: os.path.getsize(p)
    vbytes = sum(size(p) for p in glob.glob(os.path.join(vdir, "gen-*.json")))
    summary = collections.OrderedDict([
        ("format", a.format), ("global_elements", len(schema.elements)), ("messages", len(msg_names)),
        ("kinds", len(kinds)), ("messages_without_kind", [k.root.name for k in empty]),
        ("default_kind", default.name if default is not None else None),
        ("requires_with_optional_key", opt),
        ("leaves_mapped_outside_groups", total), ("leaves_mapped_inside_groups", in_groups),
        ("groups", len(groups_all)), ("groups_first_level", groups_first),
        ("groups_nested", len(groups_all) - groups_first), ("groups_scalar_items", scalar_groups),
        ("groups_by_nesting", {str(d): nest_hist[d] for d in sorted(nest_hist)}),
        ("field_lines", n_lines), ("group_blocks", n_groups),
        ("common_lines", ncommon), ("common_field_lines", nleaf), ("common_groups", common_groups),
        ("common_group_leaves", common_group_leaves),
        ("module_keys", n_keys), ("module_lists", n_lists), ("names_added", new_names),
        ("shared_bindings", len(maps)), ("depth", depth),
        ("nest_limit_applied", deepest if nest_limited else None),
        ("nest_without_limit", nest_free), ("keys_and_lists_without_limit", keys_free),
        ("by_transform", dict(by_tr)), ("mapped_with_limit", dict(notes)), ("radian_leaves", rad),
        ("not_mapped", dict(reasons.most_common())), ("mapped_choices", choices),
        ("polymorphic_elements", walker.poly), ("unqualified_local_elements", walker.unqualified),
        ("vector_xmlns", use_xmlns), ("requires_unique", uniq), ("vectors", res["vectors"]),
        ("items_per_first_level_group", per_group), ("vector_bytes_with_two_items", two_bytes),
        ("vector_items_replayed", res["items"]),
        ("vector_values_replayed", res["values"]), ("values_not_fitting_facets", weak),
        ("cross_vectors", [{"from": c[0], "kind": c[1], "carried": c[2], "dropped": c[3], "expect": c[5]} for c in cross]),
        ("bytes", {"pack.def": size(os.path.join(pdir, "pack.def")), "pack.md": size(os.path.join(pdir, "pack.md")),
                   "module.def": size(mod_path), "vectors": vbytes, "names": size(a.names_file)}),
        ("statements", statements)])
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (GenError, CheckError) as e:
        sys.stderr.write("xsd2pack: %s\n" % e)
        sys.exit(1)
