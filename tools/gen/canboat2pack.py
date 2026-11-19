#!/usr/bin/env python3
"""canboat2pack: turn the CANboat NMEA 2000 PGN database into a goat-transformers pack.

Reads   <out>/sources/canboat.json   docs/canboat.json of canboat/canboat at a pinned commit
        <out>/sources/LICENSE        the license file of that repository (with --commit)
        <out>/sources/PROVENANCE.md  the pinned commit (without --commit)
Writes  <out>/sources/PROVENANCE.md  (only with --commit)
        <out>/model/n2k.def
        <out>/packs/nmea2000/pack.def
        <out>/packs/nmea2000/pack.md
        <out>/packs/nmea2000/vectors/*.json   (a *.json there that is not a vector of this run is removed)

Usage:
  canboat2pack.py --out <dir> [--check] [--commit <sha> [--fetch]] [--core-def <path to model/core.def>]

--commit <sha>  records the commit, the sizes and the SHA-256 values of the two source
                files in sources/PROVENANCE.md. Without --commit the commit is read back
                from sources/PROVENANCE.md.
--fetch         with --commit: first downloads docs/canboat.json and LICENSE from
                raw.githubusercontent.com at that commit with curl. Nothing is downloaded
                without --fetch, and --fetch is refused together with --check.
--check         writes nothing; exits 1 when a file under --out is not what the generator
                writes today.

Guarantees:
  - The same canboat.json and commit give the same bytes on every platform and locale.
  - Before anything is written, the module and the pack are loaded by gtcheck (the load
    rules of spec/engine-spec.md), the generator's own invariants are checked on the
    loaded pack (bit ranges, kind order, every module key used), and every vector is
    parsed from its text and decoded and encoded by a small bits codec written from
    spec/engine-spec.md. A refused input or a failed check leaves the output untouched.
  - Exit status 0: everything written and checked. 1: a refused input or a failed check,
    with one line on stderr. 2: wrong usage.

Python 3 standard library only.
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import zlib
from collections import Counter, OrderedDict, defaultdict, namedtuple
from decimal import Decimal
from fractions import Fraction

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

NAME = "canboat2pack"
FORMAT = "nmea2000"
MODULE = "n2k"
PACK_VERSION = "0.1.0"
MODULE_VERSION = "0.1.0"
REPO = "canboat/canboat"
DB_PATH = "docs/canboat.json"
LICENSE_PATH = "LICENSE"
PGN_BITS = 24

# Output paths, relative to --out, with `/`.
PROVENANCE = "sources/PROVENANCE.md"
MODULE_DEF = "model/%s.def" % MODULE
PACK_DEF = "packs/%s/pack.def" % FORMAT
PACK_MD = "packs/%s/pack.md" % FORMAT
VECTORS = "packs/%s/vectors" % FORMAT

# model/core.def of goat-transformers, version 0.1.0 (checked against --core-def when given)
CORE_KEYS = OrderedDict([
    ("uid", "string"), ("type", "string"), ("time_ms", "int"), ("lat", "float"),
    ("lon", "float"), ("hae", "float"), ("ce", "float"), ("le", "float"),
    ("callsign", "string"), ("course", "float"), ("speed_ms", "float"), ("how", "string"),
    ("stale_ms", "int"),
])
# packs/geojson/pack.def: member order of the canonical output
GEOJSON_PROPS = ["type", "time_ms", "how", "ce", "le", "callsign", "course", "speed_ms"]

# CANboat field types, by how the pack can carry them.
NUMERIC_TYPES = {"NUMBER", "TIME", "DURATION", "DATE", "MMSI", "PGN", "ISO_NAME", "ADDRESS",
                 "LOOKUP", "INDIRECT_LOOKUP", "BITLOOKUP", "FIELD_INDEX",
                 "DYNAMIC_FIELD_KEY", "DYNAMIC_FIELD_LENGTH"}
VARIABLE_TYPES = {"STRING_LAU", "STRING_LZ", "VARIABLE", "DYNAMIC_FIELD_VALUE"}
SKIP_TYPES = {"RESERVED", "SPARE"}

# The bits transforms the generator writes and its codec reads.
CODEC_TRANSFORMS = ("uint", "twos", "uscale", "sscale", "f32", "ascii")


class GenError(Exception):
    """A refused input or a failed check. `file` and `line` name the source
    position where one exists; str() is `<file>:<line>: <message>`."""

    def __init__(self, message, file=None, line=None):
        super().__init__(message)
        self.message, self.file, self.line = message, file, line

    def __str__(self):
        if self.file is None:
            return self.message
        where = self.file if self.line is None else "%s:%d" % (self.file, self.line)
        return "%s: %s" % (where, self.message)


# ---------------------------------------------------------------- small helpers

def snake(ident):
    """A CANboat id (camelCase) as a lower-case key name: `cogReference` -> `cog_reference`.
    Every run of characters outside [A-Za-z0-9] becomes one `_`."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", ident)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s


def plain(x):
    """Decimal text of a number in plain notation (no exponent), shortest round trip."""
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    if x == int(x) and abs(x) < 1e17:
        return str(int(x))
    t = format(Decimal(repr(x)), "f")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t


def factor_text(res):
    """Scale factor of a CANboat resolution (engine-spec 0.5 ruling 1): a decimal fraction is
    written <num>/<den>, in lowest terms, so the engine divides and gets the nearest double."""
    fr = Fraction(Decimal(repr(res))) if isinstance(res, float) else Fraction(res)
    if fr.denominator == 1:
        return str(fr.numerator)
    # A resolution CANboat computed from pi or a binary ratio and printed to 13+ digits is not
    # a decimal fraction by intent: it stays a decimal, read as the nearest double.
    if fr.numerator > 10 ** 6 or int(float(fr.denominator)) != fr.denominator:
        return plain(res)
    return "%d/%d" % (fr.numerator, fr.denominator)


def parse_factor(text):
    """-> (num, den) as doubles for a fraction, (factor, None) for a decimal."""
    if "/" in text:
        a, b = text.split("/")
        return float(int(a)), float(int(b))
    return float(text), None


def scale_decode(v, fac, offset):
    """ruling 1: v * factor (or v * num / den), then + offset, in doubles, in this order."""
    num, den = fac
    x = float(v) * num
    if den is not None:
        x = x / den
    return x + offset


def scale_encode(x, fac, offset):
    """ruling 1: (x - offset) / factor (or (x - offset) * den / num), then round."""
    num, den = fac
    q = (x - offset) / num if den is None else (x - offset) * den / num
    return round_half_away(q)


def round_half_away(q):
    """Round to the nearest integer, a half away from zero (engine-spec 0.5 `round`)."""
    f = math.floor(abs(q) + 0.5)
    return int(-f if q < 0 else f)


# ---------------------------------------------------------------- parse: canboat.json -> records

class SourceField:
    """One entry of a definition's `Fields`, as the database states it. A member the
    database leaves out is None, except: `label` is `Name`, or the id when there is no
    `Name`; `signed` and `variable_length` are booleans; `lookup` is the name of the
    lookup table of any of the four lookup members, or ""."""
    __slots__ = ("where", "id", "field_type", "bit_length", "bit_offset", "has_match", "match",
                 "resolution", "offset", "signed", "range_min", "range_max", "unit", "name",
                 "label", "description", "physical_quantity", "lookup", "variable_length")


class Definition:
    """One entry of `PGNs`. `index` is its position in the file; `repeating` is true when
    it declares a repeating field set; `where` names it in an error message."""
    __slots__ = ("where", "index", "pgn", "id", "description", "complete", "fallback",
                 "repeating", "length", "fields")


Database = namedtuple("Database", "label version schema_version license comment copyright definitions")

_JSON_TYPE_NAMES = ((bool, "true or false"), (int, "an integer"), (float, "a number"), (str, "a string"),
                    (list, "an array"), (dict, "an object"), (type(None), "null"))


def _json_type(value):
    return next(name for cls, name in _JSON_TYPE_NAMES if isinstance(value, cls))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str)


class _Reader:
    """Reads members of one JSON object and refuses a missing or mistyped one with the
    JSON path of the member and the definition it belongs to."""

    def __init__(self, label, obj, path, context):
        self.label, self.obj, self.path, self.context = label, obj, path, context

    def fail(self, member, what):
        path = ".".join(p for p in (self.path, member) if p)
        raise GenError("%s%s: %s" % (path, self.context, what), self.label)

    def get(self, member, test, expected, required=False, null_ok=False):
        if member not in self.obj:
            if required:
                self.fail(member, "is missing; expected %s" % expected)
            return None
        value = self.obj[member]
        if value is None and null_ok:
            return None
        if not test(value):
            self.fail(member, "expected %s, found %s" % (expected, _json_type(value)))
        return value


def _parse_field(label, raw, path, context):
    if not isinstance(raw, dict):
        raise GenError("%s%s: expected an object, found %s" % (path, context, _json_type(raw)), label)
    r = _Reader(label, raw, path, context)
    f = SourceField()
    f.where = "%s%s" % (path, context)
    f.id = r.get("Id", _is_text, "a string", required=True)
    f.field_type = r.get("FieldType", _is_text, "a string", required=True)
    f.bit_length = r.get("BitLength", _is_int, "an integer")
    f.bit_offset = r.get("BitOffset", _is_int, "an integer")
    for member, value in (("BitLength", f.bit_length), ("BitOffset", f.bit_offset)):
        if value is not None and value < 0:
            r.fail(member, "is negative")
    f.has_match = "Match" in raw
    f.match = r.get("Match", _is_int, "an integer")
    f.resolution = r.get("Resolution", _is_number, "a number", null_ok=True)
    f.offset = r.get("Offset", _is_number, "a number", null_ok=True)
    f.unit = r.get("Unit", _is_text, "a string", null_ok=True)
    f.name = r.get("Name", _is_text, "a string", null_ok=True)
    f.label = raw.get("Name", f.id)
    f.description = r.get("Description", _is_text, "a string", null_ok=True)
    f.lookup = ""
    for member in ("LookupEnumeration", "LookupBitEnumeration", "LookupIndirectEnumeration",
                   "LookupFieldTypeEnumeration"):
        f.lookup = f.lookup or r.get(member, _is_text, "a string", null_ok=True) or ""
    # Members read as the database gives them: a range that is not a number is no range.
    f.signed = bool(raw.get("Signed"))
    f.range_min = raw.get("RangeMin")
    f.range_max = raw.get("RangeMax")
    f.physical_quantity = raw.get("PhysicalQuantity")
    f.variable_length = bool(raw.get("BitLengthVariable"))
    return f


def _parse_definition(label, raw, index):
    path = "PGNs[%d]" % index
    if not isinstance(raw, dict):
        raise GenError("%s: expected an object, found %s" % (path, _json_type(raw)), label)
    r = _Reader(label, raw, path, "")
    d = Definition()
    d.index = index
    d.pgn = r.get("PGN", _is_int, "an integer", required=True)
    d.id = r.get("Id", _is_text, "a string", required=True)
    r.context = " (PGN %d %s)" % (d.pgn, d.id)
    d.where = path + r.context
    d.description = r.get("Description", _is_text, "a string", required=True)
    d.complete = bool(raw.get("Complete"))
    d.fallback = bool(raw.get("Fallback"))
    d.repeating = "RepeatingFieldSet1Size" in raw or "RepeatingFieldSet2Size" in raw
    d.length = r.get("Length", _is_int, "an integer", null_ok=True)
    # A catch-all definition has no kind and its fields are not read.
    fields = r.get("Fields", lambda v: isinstance(v, list), "an array", required=not d.fallback)
    d.fields = [_parse_field(label, f, "%s.Fields[%d]" % (path, i), r.context)
                for i, f in enumerate(fields or [])]
    return d


def parse_database(text, label):
    """The records of a canboat.json text. `label` names the file in error messages.
    JSON that does not parse is refused with its line; a missing or mistyped member is
    refused with its JSON path and the PGN and id of its definition."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise GenError("not JSON: %s" % e.msg, label, e.lineno)
    if not isinstance(raw, dict):
        raise GenError("expected an object at the top, found %s" % _json_type(raw), label)
    pgns = _Reader(label, raw, "", "").get("PGNs", lambda v: isinstance(v, list), "an array", required=True)
    return Database(label, raw.get("Version"), raw.get("SchemaVersion"), raw.get("License"),
                    raw.get("Comment"), raw.get("Copyright", ""),
                    [_parse_definition(label, d, i) for i, d in enumerate(pgns)])


def _read_bytes(path, hint=""):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError as e:
        raise GenError("cannot read: %s%s" % (e.strerror or e, hint), path)


def _decode(data, path):
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise GenError("not UTF-8: %s" % e.reason, path)


# ---------------------------------------------------------------- sources and provenance

def source_urls(sha):
    """[(file name under sources/, repository path, download URL)] at a commit."""
    return [(name, rel, "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, rel))
            for name, rel in (("canboat.json", DB_PATH), ("LICENSE", LICENSE_PATH))]


def fetch_sources(src_dir, sha):
    """Download the two source files of a commit into `src_dir` with curl. This is the
    only place the generator uses the network, and only `--fetch` calls it."""
    os.makedirs(src_dir, exist_ok=True)
    for name, _, url in source_urls(sha):
        dest = os.path.join(src_dir, name)
        try:
            subprocess.run(["curl", "-fsSL", "--max-time", "300", "-o", dest, url], check=True)
        except (OSError, subprocess.CalledProcessError) as e:
            raise GenError("download failed (%s)" % e, url)


def read_commit(text, label):
    """The commit a PROVENANCE.md text records."""
    m = re.search(r"\| commit: \| `([0-9a-f]{40})` \|", text)
    if not m:
        raise GenError("no `| commit: | `<40 hex digits>` |` row; give --commit", label)
    return m.group(1)


def provenance_text(sha, db, files):
    """sources/PROVENANCE.md. `files` maps `canboat.json` and `LICENSE` to their bytes."""
    license_text = files["LICENSE"].decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        "# Provenance of the inputs in this directory",
        "",
        "| Fact | Value |",
        "|---|---|",
        "| repository | https://github.com/%s |" % REPO,
        "| commit: | `%s` |" % sha,
        "| database version stated in the file | CANboat %s, schema %s |" % (db.version, db.schema_version),
    ]
    for name, rel, url in source_urls(sha):
        lines.append("| `%s` | repository path `%s`, %d bytes, sha256 `%s` |" % (
            name, rel, len(files[name]), hashlib.sha256(files[name]).hexdigest()))
        lines.append("| `%s` download URL | %s |" % (name, url))
    lines += [
        "",
        "## What the repository's license file states",
        "",
        "The file `%s` at the repository root at this commit is %d bytes. It holds a copyright line" % (LICENSE_PATH, len(files["LICENSE"])),
        "and the Apache License 2.0 notice; it does not hold the full license text. Verbatim:",
        "",
        "```",
        license_text.rstrip("\n"),
        "```",
        "",
        "## What `canboat.json` states about itself",
        "",
        "- `License`: `%s`" % db.license,
        "- `Comment`: `%s`" % db.comment,
        "- `Copyright` (verbatim):",
        "",
        "```",
        str(db.copyright).rstrip("\n"),
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- plan: what will be emitted

class Field:
    """One mapped wire field of a kind. `key`, `core` and, for a core key, `transform`
    and `type` are settled by assign_keys."""

    def __init__(self, src, transform, typ, unit):
        self.src = src
        self.id = src.id
        self.pos = src.bit_offset + PGN_BITS
        self.len = src.bit_length
        self.transform = transform
        self.type = typ
        self.unit = unit
        self.key = None       # model key as written in the pack
        self.core = False

    @property
    def locator(self):
        return "0:%d:%d" % (self.pos, self.len)

    def signature(self):
        """What two uses of a field id must agree on to share one module key."""
        src = self.src
        return (self.type, self.unit, plain(src.resolution or 1),
                plain(src.offset if src.offset is not None else 0), src.lookup)


class Kind:
    """One kind of the pack: a fixed-layout definition with at least one mapped field."""

    def __init__(self, definition):
        self.definition = definition
        self.pgn = definition.pgn
        self.id = definition.id
        self.name = None
        self.whens = []        # (pos, len, value, CANboat field id or 'PGN')
        self.fields = []
        self.unexpressed = []  # (field id, reason)
        self.requires = []

    def match_set(self):
        return {(p, l): v for p, l, v, _ in self.whens[1:]}


# A definition with no kind. `reason` is a key of REASON_TITLES.
Unmapped = namedtuple("Unmapped", "pgn id description reason detail")

# One key of module n2k. `pgns` lists the PGNs that use it, in pack order.
KeyDecl = namedtuple("KeyDecl", "type unit sig label field_type pgns")

Plan = namedtuple("Plan", "kinds unmapped keys")


def variable_reason(d):
    """None when the definition is fixed-layout; else (reason code, detail)."""
    if d.fallback:
        return ("pgn-range", "catch-all definition for a range of PGNs")
    if d.repeating:
        return ("repeating", "repeating field set")
    bad = []
    for f in d.fields:
        if f.field_type in VARIABLE_TYPES:
            bad.append(f.field_type)
        elif f.variable_length:
            bad.append("%s of variable size" % f.field_type)
        elif f.bit_length is None:
            bad.append("%s without a length" % f.field_type)
    if bad:
        return ("variable", ", ".join(sorted(set(bad))))
    if any(f.bit_offset is None for f in d.fields):
        return ("variable", "field position depends on a condition")
    return None


def numeric_transform(f):
    """(transform text, model type) of a numeric field: an integer at resolution 1 with
    no offset, else a scale whose factor is the resolution."""
    res = 1 if f.resolution is None else f.resolution
    off = f.offset or 0
    if off != 0:
        # CANboat "Offset": value = unsigned raw * resolution + offset (J1939 excess-K).
        # The database shows it by RangeMin == Offset (raw 0 is the minimum).
        if f.range_min != off:
            raise GenError("%s: field %s has Offset %r but RangeMin %r: offset semantics not confirmed"
                           % (f.where, f.id, off, f.range_min))
        return "uscale:%s:%s" % (factor_text(res), plain(off)), "float"
    if res != 1:
        return "%s:%s" % ("sscale" if f.signed else "uscale", factor_text(res)), "float"
    return ("twos" if f.signed else "uint"), "int"


def map_field(f):
    """-> ('skip',) | ('when', value) | ('no', reason) | ('field', transform, type, unit)"""
    ft = f.field_type
    if ft in SKIP_TYPES:
        return ("skip",)
    n = f.bit_length
    if f.has_match:
        if not (1 <= n <= 64) or f.match < 0 or f.match >= (1 << n):
            raise GenError("%s: Match value of %s does not fit its field" % (f.where, f.id))
        return ("when", f.match)
    unit = f.unit or "-"
    if ft in NUMERIC_TYPES:
        if not 1 <= n <= 64:
            return ("no", "%s of %d bits (a bits field is 1..64 bits)" % (ft, n))
        t, typ = numeric_transform(f)
        return ("field", t, typ, unit)
    if ft == "FLOAT":
        if n != 32:
            return ("no", "FLOAT of %d bits" % n)
        return ("field", "f32", "float", unit)
    if ft == "STRING_FIX":
        if n % 8 or not 8 <= n <= 2040:
            return ("no", "STRING_FIX of %d bits (ascii takes 8..2040 bits in whole bytes)" % n)
        return ("field", "ascii", "string", unit)
    if ft == "BINARY":
        if n > 64:
            return ("no", "BINARY of %d bits (no transform carries more than 64 opaque bits)" % n)
        return ("field", "uint", "int", unit)
    if ft == "DECIMAL":
        return ("no", "DECIMAL (two decimal digits per byte; no transform)")
    raise GenError("%s: unhandled CANboat field type %s" % (f.where, ft))


def build_kind(d):
    """The kind of a fixed-layout definition: a `when` on the PGN and on every field
    with a Match value, a Field for every field a transform can carry."""
    k = Kind(d)
    k.whens.append((0, PGN_BITS, d.pgn, "PGN"))
    for f in d.fields:
        m = map_field(f)
        if m[0] == "skip":
            continue
        if m[0] == "when":
            k.whens.append((f.bit_offset + PGN_BITS, f.bit_length, m[1], f.id))
        elif m[0] == "no":
            k.unexpressed.append((f.id, m[1]))
        else:
            k.fields.append(Field(f, m[1], m[2], m[3]))
    return k


def match_bits(ms):
    """{(pos, len): value} -> {bit position: bit value}; a `when` is equality on these bits."""
    bits = {}
    for (p, l), v in ms.items():
        for i in range(l):
            bits[p + i] = (v >> i) & 1
    return bits


def relation(a, b):
    """How the match set of a relates to that of b (same PGN), compared bit by bit.
    conflict: no message satisfies both. super: a fixes every bit b fixes, and more."""
    a, b = match_bits(a), match_bits(b)
    if any(b.get(i, v) != v for i, v in a.items()):
        return "conflict"
    if a.keys() == b.keys():
        return "equal"
    if a.keys() > b.keys():
        return "super"
    if a.keys() < b.keys():
        return "sub"
    return "incomparable"


def _unmapped(d, reason, detail):
    return Unmapped(d.pgn, d.id, d.description, reason, detail)


def _match_set_of_unmapped(d):
    """The match set of a definition with no kind, or None when one of its match
    fields has no fixed position."""
    ms = {}
    for f in d.fields:
        if f.has_match:
            if f.bit_offset is None or f.bit_length is None:
                return None
            ms[(f.bit_offset + PGN_BITS, f.bit_length)] = f.match
    return ms


def sort_definitions(definitions):
    """First pass over the source, in source order.
    -> (candidate kinds, unmapped, {pgn: [(definition id, match set or None)]}).
    The third value lists every definition of a PGN except the catch-all ones: a kind
    must be told apart from all of them, mapped or not."""
    candidates, unmapped, siblings = [], [], defaultdict(list)
    for d in definitions:
        vr = variable_reason(d)
        if vr:
            unmapped.append(_unmapped(d, vr[0], vr[1]))
            if vr[0] != "pgn-range":
                siblings[d.pgn].append((d.id, _match_set_of_unmapped(d)))
            continue
        k = build_kind(d)
        siblings[d.pgn].append((d.id, k.match_set()))
        if k.fields:
            candidates.append(k)
        else:
            unmapped.append(_unmapped(d, "no-field", "fields: " + ", ".join(
                "%s%s" % (f.field_type, " (match)" if f.has_match else "") for f in d.fields)))
    return candidates, unmapped, siblings


def _indistinguishable(k, others, mapped):
    """Why kind k cannot be told apart from another definition of its PGN, or None.
    A less specific kind is fine as long as the more specific definition is mapped:
    the more specific kind then stands first in the pack."""
    a = k.match_set()
    for other_id, b in others:
        if other_id == k.id:
            continue
        if b is None:
            return "definition %s of the same PGN has a match field at a variable position" % other_id
        r = relation(a, b)
        if r == "equal":
            return "same match values as definition %s" % other_id
        if r == "incomparable":
            return ("a message can satisfy its match values and those of definition %s, "
                    "and neither set contains the other" % other_id)
        if r == "sub" and other_id not in mapped:
            return "its match values also hold for the unmapped, more specific definition %s" % other_id
    return None


def drop_indistinguishable(candidates, siblings, unmapped):
    """Remove, to a fixed point, every candidate that cannot be told apart from another
    definition of its PGN; each one is appended to `unmapped`. -> the kinds that stay."""
    mapped = {k.id: k for k in candidates}
    changed = True
    while changed:
        changed = False
        for k in list(mapped.values()):
            why = _indistinguishable(k, siblings[k.pgn], mapped)
            if why:
                del mapped[k.id]
                unmapped.append(_unmapped(k.definition, "indistinguishable", why))
                changed = True
    return [k for k in candidates if k.id in mapped]


def name_and_order(kinds, definitions):
    """Name each kind `pgn<number>`, with the definition id appended when the source has
    several definitions of the PGN; order by PGN, then most matched bits first (the first
    kind that holds is the most specific one), then source order."""
    per_pgn = Counter(d.pgn for d in definitions if not d.fallback)
    for k in kinds:
        k.name = "pgn%d" % k.pgn if per_pgn[k.pgn] == 1 else "pgn%d_%s" % (k.pgn, snake(k.id))
    src_order = {d.id: d.index for d in definitions}
    kinds.sort(key=lambda k: (k.pgn, -sum(l for _, l, _, _ in k.whens), src_order[k.id]))
    names = Counter(k.name for k in kinds)
    twice = sorted(n for n, c in names.items() if c > 1)
    if twice:
        raise GenError("duplicate kind name %s" % twice[0])


def classify(definitions):
    """-> (kinds in pack order, unmapped definitions)."""
    candidates, unmapped, siblings = sort_definitions(definitions)
    kinds = drop_indistinguishable(candidates, siblings, unmapped)
    name_and_order(kinds, definitions)
    return kinds, unmapped


def core_mapping(k):
    """Decide the core keys of a kind. Returns {field: (core key, transform)}."""
    out = {}
    lat = [f for f in k.fields if f.src.physical_quantity == "GEOGRAPHICAL_LATITUDE"]
    lon = [f for f in k.fields if f.src.physical_quantity == "GEOGRAPHICAL_LONGITUDE"]

    def degrees_ok(f, ident):
        return (f.id == ident and f.src.unit == "deg" and f.src.signed
                and f.src.resolution in (1e-07, 1e-16) and not f.src.offset)
    if len(lat) == 1 and len(lon) == 1 and degrees_ok(lat[0], "latitude") and degrees_ok(lon[0], "longitude"):
        out[lat[0]] = ("lat", lat[0].transform)
        out[lon[0]] = ("lon", lon[0].transform)
    sog = [f for f in k.fields if f.id == "sog"]
    if len(sog) == 1 and sog[0].src.unit == "m/s" and not sog[0].src.signed and sog[0].transform.startswith("uscale:"):
        out[sog[0]] = ("speed_ms", sog[0].transform)
    # course: only a course-over-ground field the database itself states is referenced to
    # true north, in a definition with no reference selector field.
    has_ref = any(f.id.lower().endswith("reference") for f in k.definition.fields)
    cog = [f for f in k.fields if f.id == "cog"]
    if len(cog) == 1 and not has_ref and cog[0].src.unit == "rad":
        src = cog[0].src
        text = ((src.name or "") + " " + (src.description or "")).lower()
        if re.search(r"\btrue\b", text):
            factor = (1 if src.resolution is None else src.resolution) * 180.0 / math.pi
            out[cog[0]] = ("course", "%s:%s" % ("sscale" if src.signed else "uscale", plain(factor)))
    # hae: only an altitude the database states is above the WGS84 ellipsoid.
    alt = [f for f in k.fields if f.id == "altitude"]
    if len(alt) == 1 and alt[0].src.unit == "m" and "ellipsoid" in (alt[0].src.description or "").lower():
        out[alt[0]] = ("hae", alt[0].transform if ":" in alt[0].transform else "sscale:1")
    return out


def assign_core_keys(kinds):
    """Give each field that core_mapping selects its core key (and the transform to the
    core unit). -> [(kind, field)] of the fields left for module n2k, in pack order."""
    raw = []
    for k in kinds:
        cm = core_mapping(k)
        used = set()
        for f in k.fields:
            if f in cm and cm[f][0] not in used:
                f.key, f.transform = cm[f]
                f.type, f.core = "float", True
                used.add(f.key)
            else:
                raw.append((k, f))
    return raw


def declare_module_keys(raw):
    """Name the n2k key of every field in `raw`. A field id whose uses all agree on
    signature is one key named snake(id); where uses disagree each PGN gets
    `pgn<number>_<id>`, and where definitions of one PGN disagree, `<kind name>_<id>`.
    -> {key name: KeyDecl} in order of first use."""
    by_id = OrderedDict()
    for k, f in raw:
        by_id.setdefault(snake(f.id), []).append((k, f))
    keys = OrderedDict()

    def declare(name, k, f):
        e = keys.get(name)
        if e is None:
            e = keys[name] = KeyDecl(f.type, f.unit, f.signature(), f.src.label, f.src.field_type, [])
        elif e.sig != f.signature():
            raise GenError("%s: key %s declared with two signatures" % (f.src.where, name))
        if k.pgn not in e.pgns:
            e.pgns.append(k.pgn)
        f.key = "%s.%s" % (MODULE, name)

    for base, uses in by_id.items():
        if len({f.signature() for _, f in uses}) == 1:
            for k, f in uses:
                declare(base, k, f)
            continue
        by_pgn = OrderedDict()
        for k, f in uses:
            by_pgn.setdefault(k.pgn, []).append((k, f))
        for pgn, pu in by_pgn.items():
            if len({f.signature() for _, f in pu}) == 1:
                for k, f in pu:
                    declare("pgn%d_%s" % (pgn, base), k, f)
            else:
                for k, f in pu:
                    declare("%s_%s" % (k.name, base), k, f)
    for name in keys:
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise GenError("bad key name %r" % name)
    return keys


def choose_requires(kinds):
    """`requires` of each kind: its n2k keys used by the fewest kinds (up to 6), in
    field order; its core keys when it has no n2k key."""
    use_count = Counter()
    for k in kinds:
        for f in k.fields:
            use_count[f.key] += 1
    for k in kinds:
        seen = [f.key for f in k.fields]
        if len(set(seen)) != len(seen):
            twice = next(key for key in seen if seen.count(key) > 1)
            raise GenError("%s: kind %s maps key %s twice (two field ids give one key name)"
                           % (k.definition.where, k.name, twice))
        rawk = [f for f in k.fields if not f.core] or k.fields
        order = sorted(range(len(rawk)), key=lambda i: (use_count[rawk[i].key], i))[:6]
        k.requires = [rawk[i].key for i in sorted(order)]


def assign_keys(kinds):
    """Core keys, then n2k keys, then `requires`. -> {n2k key name: KeyDecl}."""
    keys = declare_module_keys(assign_core_keys(kinds))
    choose_requires(kinds)
    return keys


def make_plan(db):
    """Every decision about the output, from the parsed database."""
    kinds, unmapped = classify(db.definitions)
    keys = assign_keys(kinds)
    if len(kinds) + len(unmapped) != len(db.definitions):
        raise GenError("definitions unaccounted for")
    if not kinds:
        raise GenError("no definition can be mapped to a kind", db.label)
    return Plan(kinds, unmapped, keys)


# ---------------------------------------------------------------- emit

def q(text):
    """A quoted token. The pack grammar has no escape: `"` becomes `'`."""
    text = str(text).replace('"', "'").replace("\n", " ")
    return '"%s"' % text


def unit_token(u):
    return q(u) if re.search(r"\s", u) or u.startswith("#") else u


def _source_line(sha, db):
    return "source        " + q("%s %s at commit %s (CANboat %s, Apache License 2.0)" % (REPO, DB_PATH, sha, db.version))


def emit_module(keys, sha, db):
    """The text of model/n2k.def."""
    out = [
        "# The n2k module: NMEA 2000 field values as the CANboat PGN database describes them,",
        "# in CANboat's units (rad, m/s, K, Pa, ...). Lookup and bit-lookup fields are the wire",
        "# integer. A key is shared by every PGN whose field of that id agrees on type, unit,",
        "# resolution, offset and lookup table; where uses disagree the key carries its PGN.",
        "# GENERATED by tools/gen/canboat2pack.py. Do not edit.",
        "module        %s" % MODULE,
        "version       %s" % MODULE_VERSION,
        "distribution  public",
        _source_line(sha, db),
    ]
    w = max(len(n) for n in keys)
    for name, e in keys.items():
        pg = e.pgns
        where = "PGN " + ", ".join(str(p) for p in pg[:4]) + (" and %d more" % (len(pg) - 4) if len(pg) > 4 else "")
        lookup = e.sig[4]
        kind = e.field_type + (" " + lookup if lookup else "")
        out.append("key  %-*s  %-6s  %-8s  %s" % (w, name, e.type, unit_token(e.unit),
                                              q("%s; CANboat %s; %s" % (e.label, kind, where))))
    return "\n".join(out) + "\n"


def emit_pack(kinds, sha, db):
    """The text of packs/nmea2000/pack.def."""
    out = [
        "# NMEA 2000 parameter groups, from the CANboat PGN database. Public.",
        "# Message = 3 bytes PGN (little-endian), then the reassembled payload.",
        "# Payload bit offsets are CANboat's BitOffset + 24. See pack.md.",
        "# GENERATED by tools/gen/canboat2pack.py. Do not edit.",
        "format        %s" % FORMAT,
        "version       %s" % PACK_VERSION,
        "distribution  public",
        _source_line(sha, db),
        "source        " + q("https://github.com/%s/blob/%s/%s" % (REPO, sha, DB_PATH)),
        "uses          %s" % MODULE,
        "wire          bits",
        "bit_order     lsb",
        "word_bytes    1",
    ]
    for k in kinds:
        out.append("")
        out.append("# PGN %d %s: %s%s" % (k.pgn, k.id, k.definition.description.replace("\n", " "),
                                       "" if k.definition.complete else " [CANboat: incomplete]"))
        out.append("kind      %s" % k.name)
        for p, l, v, _ in k.whens:
            out.append("when      0:%d:%d %d" % (p, l, v))
        out.append("requires  " + " ".join(k.requires))
        w = max(len(f.key) for f in k.fields)
        for f in k.fields:
            out.append("field     %-*s  %-12s %s" % (w, f.key, f.locator, f.transform))
    return "\n".join(out) + "\n"


REASON_TITLES = OrderedDict([
    ("repeating", "Repeating field sets"),
    ("variable", "Variable-length or conditionally placed fields"),
    ("pgn-range", "Catch-all definitions for a range of PGNs"),
    ("indistinguishable", "Not distinguishable from another definition of the same PGN"),
    ("no-field", "No field the pack language can carry"),
])


def _by_reason(unmapped):
    by_reason = defaultdict(list)
    for u in unmapped:
        by_reason[u.reason].append(u)
    return by_reason


def _md_header(db, sha):
    return [
        "# Pack: nmea2000",
        "",
        "NMEA 2000 parameter groups (PGNs), generated from the CANboat PGN database",
        "(`%s` `%s` at commit `%s`, CANboat %s, Apache License 2.0) by" % (REPO, DB_PATH, sha, db.version),
        "`tools/gen/canboat2pack.py`. Do not edit `pack.def`, `model/n2k.def` or the vectors by hand;",
        "change the generator and run it again.",
        "",
        "Status: Built. Generated from the database; every engine runs every vector in `vectors/` in",
        "the conformance suite.",
        "",
        "## Message convention",
        "",
        "An NMEA 2000 payload travels in CAN frames whose 29-bit identifier carries the PGN, and the",
        "pack language has no CAN framing. A message of this pack is therefore:",
        "",
        "1. 3 bytes: the PGN, little-endian;",
        "2. the payload: the 8 data bytes of a single-frame PGN, or the payload of a fast-packet PGN",
        "   after reassembly (sequence and frame counters and the length byte removed).",
        "",
        "Priority, source address and destination address are not part of the message. The pack is",
        "`wire bits`, `bit_order lsb`, `word_bytes 1`; every locator is `0:<bit offset>:<len>` and a",
        "payload field sits at CANboat's `BitOffset` + 24. Input and output are hex text.",
        "",
    ]


def _md_counts(kinds, unmapped, keys, db, n_vectors, xnames):
    by_reason = _by_reason(unmapped)
    L = [
        "## What is mapped",
        "",
        "| | Count |",
        "|---|---|",
        "| PGN definitions in the source | %d |" % len(db.definitions),
        "| kinds in `pack.def` | %d |" % len(kinds),
        "| distinct PGNs with at least one kind | %d |" % len({k.pgn for k in kinds}),
    ]
    for code, title in REASON_TITLES.items():
        L.append("| not mapped: %s | %d |" % (title[0].lower() + title[1:], len(by_reason.get(code, []))))
    L += [
        "| keys in module `%s` | %d |" % (MODULE, len(keys)),
        "| vectors | %d (%d same-format round trips, %d to `geojson`) |" % (n_vectors, len(kinds), len(xnames)),
        "",
        "One kind per fixed-layout PGN definition, named `pgn<number>`, with the CANboat definition id",
        "appended where the source holds several definitions for that PGN. Each kind has",
        "`when 0:0:24 <pgn>` and one more `when` per CANboat field with a fixed `Match` value",
        "(manufacturer code, industry code, function and message codes). Kinds of one PGN are ordered",
        "with the most matched bits first, so the first kind that holds is the most specific one.",
        "Two definitions of one PGN are told apart only by these values: a definition whose match",
        "values also hold for another definition's messages, with no order that separates them, has",
        "no kind.",
        "A `Match` field is written by its `when` line and is not a model key.",
        "",
    ]
    return L


def _md_field_rules(kinds):
    req_sets = Counter(tuple(k.requires) for k in kinds)
    shadow = sum(1 for k in kinds if req_sets[tuple(k.requires)] > 1)
    return [
        "Field rules:",
        "",
        "| CANboat field | Transform | Model type |",
        "|---|---|---|",
        "| NUMBER, TIME, DURATION with `Resolution` other than 1 | `uscale:<resolution>` or, when `Signed`, `sscale:<resolution>`; a decimal resolution is written as a fraction in lowest terms (1e-7 is `1/10000000`, 0.002 is `1/500`); a resolution CANboat derived from pi and printed to 13 or more digits stays a decimal | float, CANboat's unit |",
        "| any numeric field with `Offset` | `uscale:<resolution>:<offset>` (the raw value is unsigned; value = raw x resolution + offset) | float |",
        "| NUMBER, DATE, MMSI, PGN, ISO_NAME, ADDRESS with resolution 1 | `uint`, or `twos` when `Signed` | int |",
        "| LOOKUP, INDIRECT_LOOKUP, BITLOOKUP, FIELD_INDEX | `uint` (the wire integer, not the lookup name) | int |",
        "| FLOAT | `f32` | float |",
        "| STRING_FIX | `ascii` | string |",
        "| BINARY of 64 bits or fewer | `uint` | int |",
        "| RESERVED, SPARE | not mapped | |",
        "",
        "Every raw value goes to module `n2k` (`model/n2k.def`). A field id that agrees across all its",
        "uses on model type, unit, resolution, offset and lookup table is one key (`n2k.sid`,",
        "`n2k.wind_speed`). Where uses disagree, each PGN gets its own key `n2k.pgn<number>_<id>`, and",
        "where definitions of one PGN disagree, `n2k.<kind name>_<id>`.",
        "",
        "`requires` of a kind lists up to six of its `n2k` keys, those used by the fewest kinds; a kind",
        "with no `n2k` key lists its core keys. %d kinds share their `requires` list with another kind;" % shadow,
        "for those, an encode from another format selects the first in pack order.",
        "",
    ]


def _md_core_keys(kinds):
    L = [
        "## Core keys",
        "",
        "| Kind | PGN | Core keys |",
        "|---|---|---|",
    ]
    for k in kinds:
        ck = [f for f in k.fields if f.core]
        if ck:
            L.append("| `%s` | %s | %s |" % (k.name, k.definition.description,
                                         ", ".join("`%s` `%s`" % (f.key, f.transform) for f in ck)))
    L += [
        "",
        "- `lat` / `lon`: only a definition with exactly one latitude and one longitude field, ids",
        "  `latitude` and `longitude`, in degrees at resolution 1e-7 or 1e-16. Waypoint, destination,",
        "  station, corner and delta positions stay in `n2k`. NMEA 2000 states the datum in a separate",
        "  PGN (129044); the pack does not read it.",
        "- `speed_ms`: the field `sog` in m/s.",
        "- `course`: no kind maps it. Every fixed-layout course-over-ground field either sits beside a",
        "  reference selector (`cogReference`: true or magnetic) or has no stated reference in the",
        "  database, so it stays `n2k.cog` in radians. The generator maps `course` with the factor",
        "  resolution x 180/pi when a definition states a true-north reference and has no selector.",
        "- `hae`: no kind maps it. No fixed-layout altitude field is stated to be above the WGS84",
        "  ellipsoid (PGN 129029 says \"referenced to WGS-84\" and is not fixed-layout).",
        "",
    ]
    return L


def _md_limits(kinds):
    partial = [(k, k.unexpressed) for k in kinds if k.unexpressed]
    L = [
        "## What the pack language cannot express yet",
        "",
        "- **\"Not available\" values.** NMEA 2000 marks a missing value with all bits set (and uses",
        "  the next values down for \"out of range\" and \"reserved\"). There is no way to say so in",
        "  `pack.def`: an all-ones field decodes as a number (`0xFFFF` at resolution 0.01 is 655.35),",
        "  and an absent model key encodes as zero bits, not all ones.",
        "- **Reserved and spare bits.** NMEA 2000 sets them to 1; `encode` writes 0 in every bit no",
        "  field covers. A real message with reserved bits set does not round-trip byte-identically.",
        "- **Trailing bytes.** The message ends at the last mapped or `when` bit, rounded up to a",
        "  byte. A definition that ends in reserved fields encodes shorter than its NMEA 2000 length",
        "  (PGN 129026 encodes 3 + 6 bytes, not 3 + 8). Decode accepts the full length.",
        "- **Repeating field sets and variable-length fields** (STRING_LAU, STRING_LZ, VARIABLE,",
        "  BINARY of variable size, key/length/value fields, fields placed after any of these). These",
        "  need the future groups addition; the definitions are listed below.",
        "- **PGN ranges.** A `when` compares for equality, so CANboat's catch-all definitions for a",
        "  range of PGNs (proprietary ranges) have no kind.",
        "- **CAN framing**: identifier, priority, addresses, fast-packet and ISO transport reassembly.",
        "- **Opaque fields over 64 bits and DECIMAL fields.** %d kinds leave such a field unmapped:" % len(partial),
        "",
    ]
    if partial:
        L += ["| Kind | Field | Reason |", "|---|---|---|"]
        for k, un in partial:
            for fid, why in un:
                L.append("| `%s` | `%s` | %s |" % (k.name, fid, why))
        L.append("")
    L += [
        "- **String padding.** `ascii` strips trailing NUL bytes only and refuses bytes above 0x7E.",
        "  NMEA 2000 devices also pad fixed strings with 0xFF or `@`; 0xFF padding is a decode error.",
        "- **Lookup names.** Lookups are carried as integers; the pack language has no value table for",
        "  a `bits` field.",
        "- **64-bit unsigned values.** `uint` on a 64-bit field (ISO NAME) with the top bit set",
        "  decodes to the negative integer with the same bit pattern.",
        "",
    ]
    return L


def _md_incomplete(kinds):
    incomplete = [k for k in kinds if not k.definition.complete]
    return [
        "## Kinds from definitions CANboat marks incomplete",
        "",
        "%d of the %d kinds come from definitions with `Complete: false` (CANboat states fields, field" % (len(incomplete), len(kinds)),
        "lengths, resolutions or lookups may be missing or wrong). They carry `[CANboat: incomplete]`",
        "in the comment above the kind in `pack.def`.",
        "",
    ]


def _md_vectors(xnames):
    return [
        "## Vectors",
        "",
        "- `rt-<kind>.json`: one same-format round trip per kind. The generator packs the bytes itself",
        "  from values inside each field's range that survive scaling exactly; unmapped bits are 0 and",
        "  the message has the encoded length, so the round trip is byte-identical. `model` holds",
        "  `@kind` and every decoded key.",
        "- %s: conversions to `geojson`, with the expected text" % ", ".join("`%s.json`" % n for n in xnames),
        "  written by hand from the canonical GeoJSON rules and checked by the generator against its",
        "  own codec. PGN 129029 has no vector: it has a repeating field set and no kind.",
        "",
        "Vectors hold lowercase hex text in `input` / `expect`.",
        "",
    ]


def _md_unmapped(unmapped):
    by_reason = _by_reason(unmapped)
    L = ["## Definitions not mapped", ""]
    for code, title in REASON_TITLES.items():
        rows = by_reason.get(code, [])
        L += ["### %s (%d)" % (title, len(rows)), ""]
        if code in ("repeating", "variable"):
            L += ["These need the future groups addition.", ""]
        if not rows:
            L += ["None.", ""]
            continue
        L += ["| PGN | CANboat id | Description | Detail |", "|---|---|---|---|"]
        for u in sorted(rows, key=lambda r: (r.pgn, r.id)):
            L.append("| %d | `%s` | %s | %s |" % (u.pgn, u.id, u.description.replace("|", "/").replace("\n", " "), u.detail))
        L.append("")
    return L


def emit_pack_md(kinds, unmapped, keys, db, sha, n_vectors, xnames):
    """The text of packs/nmea2000/pack.md."""
    lines = (_md_header(db, sha) + _md_counts(kinds, unmapped, keys, db, n_vectors, xnames)
             + _md_field_rules(kinds) + _md_core_keys(kinds) + _md_limits(kinds)
             + _md_incomplete(kinds) + _md_vectors(xnames) + _md_unmapped(unmapped))
    return "\n".join(lines)


# ---------------------------------------------------------------- codec (from spec/engine-spec.md)
#
# A bits codec for the part of the pack language this generator writes: a fixed
# layout, `bit_order lsb`, `when` and `field` lines with the transforms of
# CODEC_TRANSFORMS. It reads the Pack that gtcheck loaded, never the pack text.

CodecField = namedtuple("CodecField", "key start len t factor offset")
CodecKind = namedtuple("CodecKind", "name whens fields requires")   # whens: [(start, len, value)]


def codec_kinds(pack):
    """The kinds of a gtcheck Pack as the codec reads them: for each kind the common
    lines followed by its own. Refuses a pack the codec does not cover."""
    def refuse(what, line=None):
        raise GenError("the codec of %s does not read %s" % (NAME, what), pack.label, line)

    if pack.wire != "bits" or pack.sequential or pack.bit_order != "lsb" or not pack.word_bytes:
        refuse("a pack that is not `wire bits`, fixed layout, `bit_order lsb`")
    kinds = []
    for kind, lines in pack.scopes():
        if kind is None:
            refuse("a pack with no kind")
        whens, fields = [], []
        for node in lines:
            if node.d == "when":
                whens.append((node.start, node.bits, int(node.value)))
            elif node.d == "field":
                if node.tr not in CODEC_TRANSFORMS or node.opts or node.via or node.also:
                    refuse("this field (transform `%s`, or an option)" % node.tr, node.line)
                factor = parse_factor(node.targs[0]) if node.targs else None
                offset = float(node.targs[1]) if len(node.targs) > 1 else 0.0
                fields.append(CodecField(node.key, node.start, node.bits, node.tr, factor, offset))
            else:
                refuse("a `%s` line" % node.d, node.line)
        kinds.append(CodecKind(kind.name, whens, fields, list(kind.requires)))
    return kinds


def get_bits(data, start, ln):
    """`ln` bits of the message from bit `start`, `bit_order lsb`: bit 0 is the least
    significant bit of byte 0, and a field's low bits come first."""
    return (int.from_bytes(data, "little") >> start) & ((1 << ln) - 1)


def kind_bits(k):
    """The bit length of a kind's message: the end of its last `when` or `field`."""
    return max([s + l for s, l, _ in k.whens] + [f.start + f.len for f in k.fields])


def _signed(v, ln):
    return v - (1 << ln) if v >> (ln - 1) else v


def decode_field(f, v):
    """The model value of the unsigned wire integer `v` of a field."""
    t = f.t
    if t == "uint":
        return v - (1 << 64) if f.len == 64 and v >> 63 else v   # ruling 2
    if t == "twos":
        return _signed(v, f.len)
    if t == "uscale":
        return scale_decode(v, f.factor, f.offset)
    if t == "sscale":
        return scale_decode(_signed(v, f.len), f.factor, f.offset)
    if t == "f32":
        return struct.unpack("<f", v.to_bytes(4, "little"))[0]
    b = v.to_bytes(f.len // 8, "little").rstrip(b"\x00")      # ascii
    if any(c > 0x7E or c < 0x20 for c in b):
        raise GenError("transform-decode: ascii")
    return b.decode("ascii")


def encode_field(f, x):
    """The unsigned wire integer of a model value; a scaled value outside the field's
    range after rounding is `transform-encode`."""
    t, ln = f.t, f.len
    if t in ("uint", "twos"):
        return x & ((1 << ln) - 1)
    if t in ("uscale", "sscale"):
        r = scale_encode(x, f.factor, f.offset)
        lo, hi = (0, (1 << ln) - 1) if t == "uscale" else (-(1 << (ln - 1)), (1 << (ln - 1)) - 1)
        if not lo <= r <= hi:
            raise GenError("transform-encode: %s" % f.key)
        return r & ((1 << ln) - 1)
    if t == "f32":
        return int.from_bytes(struct.pack("<f", x), "little")
    b = x.encode("ascii")                                      # ascii
    if len(b) > ln // 8:
        raise GenError("transform-encode: ascii")
    return int.from_bytes(b.ljust(ln // 8, b"\x00"), "little")


def decode(kinds, data):
    """-> (the first kind whose `when` lines all hold, {key: value} in field order)."""
    def holds(w):
        s, l, v = w
        return s + l <= len(data) * 8 and get_bits(data, s, l) == v
    k = next((k for k in kinds if all(holds(w) for w in k.whens)), None)
    if k is None:
        raise GenError("no-kind")
    if (kind_bits(k) + 7) // 8 > len(data):
        raise GenError("malformed-wire")
    return k, OrderedDict((f.key, decode_field(f, get_bits(data, f.start, f.len))) for f in k.fields)


def encode(k, ent):
    """The message of kind `k` for an entity: its fields, then its `when` values over
    them; a bit no line covers is 0; the length is kind_bits rounded up to a byte."""
    acc = 0
    for f in k.fields:
        if f.key in ent:
            acc |= encode_field(f, ent[f.key]) << f.start
    for s, l, v in k.whens:
        acc = (acc & ~(((1 << l) - 1) << s)) | (v << s)
    return acc.to_bytes((kind_bits(k) + 7) // 8, "little")


def model_text(x):
    return x if isinstance(x, str) else plain(x)


def geojson_text(ent):
    """Canonical GeoJSON of the core keys an entity holds (engine-spec Canonicalisation, 0.1.1 rulings 3-5)."""
    def val(key):
        x = ent[key]
        return json.dumps(x) if isinstance(x, str) else plain(x)
    if "lat" in ent and "lon" in ent:
        coords = [val("lon"), val("lat")] + ([val("hae")] if "hae" in ent else [])
        geom = '{"type":"Point","coordinates":[%s]}' % ",".join(coords)
    else:
        geom = "null"
    props = ",".join('"%s":%s' % (p, val(p)) for p in GEOJSON_PROPS if p in ent)
    out = '{"type":"Feature","geometry":%s,"properties":{%s}' % (geom, props)
    if "uid" in ent:
        out += ',"id":%s' % val("uid")
    return out + "}"


# ---------------------------------------------------------------- vectors

def _range_number(value):
    return value if isinstance(value, (int, float)) else None


def _pick_ascii(f, h):
    nb = f.len // 8
    text = ("N2K" + "%08X" % h + "TESTVECTOR")[:min(nb, 16)]
    return int.from_bytes(text.encode().ljust(nb, b"\x00"), "little")


def _pick_f32(f, h):
    return int.from_bytes(struct.pack("<f", (h % 4001 - 2000) / 8.0), "little")


def _pick_integer(f, h, signed):
    n, cap = f.len, (1 << 62) - 1
    rmin, rmax = _range_number(f.src.range_min), _range_number(f.src.range_max)
    if not signed:
        top = (1 << n) - 1 if n < 2 else (1 << n) - 2
        if rmax is not None and 0 <= rmax <= top and rmax == int(rmax):
            top = int(rmax)
        top = min(top, cap)
        return (1 + h % top) if top >= 1 else 0
    top = (1 << (n - 1)) - 2 if n > 2 else 0
    bot = -top
    if rmax is not None:
        top = min(top, int(math.floor(rmax)))
    if rmin is not None:
        bot = max(bot, int(math.ceil(rmin)))
    top, bot = min(top, cap), max(bot, -cap)
    s = bot + h % (top - bot + 1) if top >= bot else 0
    return s & ((1 << n) - 1)


def _pick_scaled(k, f, h, name, args):
    n, src = f.len, f.src
    factor = parse_factor(args[0])
    offset = float(args[1]) if len(args) > 1 else 0.0
    signed = name == "sscale"
    # raw range: the field's bits less the top values NMEA 2000 reserves, then CANboat's
    # RangeMin/RangeMax in raw units (CANboat resolution: the raw range does not depend
    # on the unit the pack scales to), then 31 bits so the double arithmetic is exact
    lo, hi = (-(1 << (n - 1)) + 1, (1 << (n - 1)) - 4) if signed else (0, (1 << n) - 4)
    hi = max(hi, 1 if n > 1 else 0)
    lo = min(lo, 0)
    res, off = src.resolution or 1, src.offset or 0
    rmin, rmax = _range_number(src.range_min), _range_number(src.range_max)
    if rmax is not None:
        hi = min(hi, max(int(math.floor((rmax - off) / res)) - 1, 0))
    if rmin is not None:
        lo = max(lo, min(int(math.ceil((rmin - off) / res)) + 1, 0))
    lo, hi = max(lo, -(1 << 31) + 1), min(hi, (1 << 31) - 1)
    s = lo + h % (hi - lo + 1)
    if s == 0 and hi >= 1:
        s = 1
    for _ in range(4096):
        if scale_encode(scale_decode(s, factor, offset), factor, offset) == s:
            break
        s = s - 1 if s > 0 else s + 1
    else:
        raise GenError("%s: no exactly representable value for %s in %s" % (src.where, f.id, k.name))
    return s & ((1 << n) - 1)


def _pick_value(k, f, salt=0):
    """The raw wire integer of one field. `salt` 0 is the first choice; another salt
    gives another value of the same field, as repeatable as the first."""
    ident = "%s/%s" % (k.name, f.id) if not salt else "%s/%s#%d" % (k.name, f.id, salt)
    h = zlib.crc32(ident.encode())
    name, *args = f.transform.split(":")
    if name == "ascii":
        return _pick_ascii(f, h)
    if name == "f32":
        return _pick_f32(f, h)
    if name in ("uint", "twos"):
        return _pick_integer(f, h, signed=name == "twos")
    return _pick_scaled(k, f, h, name, args)


def _selected_before(k, vals, earlier):
    """The first kind of `earlier` whose `when` lines all hold on the message that
    `vals` packs for `k`: the kind a decoder selects in place of `k`. None when
    the message decodes as `k`."""
    message = int.from_bytes(pack_message(k, vals), "little")
    for other in earlier:
        if all((message >> p) & ((1 << l) - 1) == v for p, l, v, _ in other.whens):
            return other
    return None


def pick_values(k, earlier=()):
    """A raw wire integer for every mapped field: inside the field's range, not a
    'not available' value, and exactly recoverable after scaling. The choice depends
    only on the kind name and the field id (CRC-32), so it is the same on every run.

    `earlier` holds the kinds that stand before `k` in the pack. A decoder takes the
    first kind whose `when` lines hold, so a value that happens to equal the match
    value of an earlier kind of the same PGN would make the message decode as that
    kind. The fields that cover such a match are given their next choice until the
    message decodes as `k`."""
    vals = {f: _pick_value(k, f) for f in k.fields}
    for salt in range(1, 65):
        other = _selected_before(k, vals, earlier)
        if other is None:
            break
        covering = [f for f in k.fields
                    if any(f.pos < p + l and p < f.pos + f.len for p, l, _, _ in other.whens[1:])]
        if not covering:
            break       # no field of `k` reaches the match bits: the caller reports the kind
        for f in covering:
            vals[f] = _pick_value(k, f, salt)
    return vals


def pack_message(k, vals):
    """The bytes of a message of kind `k` from raw wire integers by field, packed
    without the codec: the `when` values and the field values at their bit positions,
    every other bit 0, ending at the last `when` or field bit rounded up to a byte."""
    acc = 0
    end = 0
    for p, l, v, _ in k.whens:
        acc |= v << p
        end = max(end, p + l)
    for f in k.fields:
        acc |= vals.get(f, 0) << f.pos
        end = max(end, f.pos + f.len)
    return acc.to_bytes((end + 7) // 8, "little")


# Cross-format vectors to geojson. Raw wire integers by CANboat field id; every other
# field is 0. `expect` is written by hand:
#   lat/lon = raw / 10000000 (degrees), speed_ms = raw / 100 (m/s), as IEEE doubles,
#   written as the shortest decimal that reads back to the same double;
#   geometry is null when lat or lon is absent; properties in geojson field-line order;
#   n2k keys are not GeoJSON keys and do not cross.
CROSS = [
    ("x01-pgn129025-to-geojson", "positionRapidUpdate",
     {"latitude": 525000000, "longitude": 45000000},                       # 52.5 N, 4.5 E
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,52.5]},"properties":{}}'),
    ("x02-pgn129025-south-west-to-geojson", "positionRapidUpdate",
     {"latitude": -337500000, "longitude": -1512500000},                   # 33.75 S, 151.25 W
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[-151.25,-33.75]},"properties":{}}'),
    ("x03-pgn129026-to-geojson", "cogSogRapidUpdate",
     {"sid": 7, "cogReference": 0, "cog": 15708, "sog": 250},              # COG 1.5708 rad (stays raw), SOG 2.5 m/s
     '{"type":"Feature","geometry":null,"properties":{"speed_ms":2.5}}'),
    ("x04-pgn129026-magnetic-cog-to-geojson", "cogSogRapidUpdate",
     {"sid": 8, "cogReference": 1, "cog": 31416, "sog": 1025},             # magnetic COG, SOG 10.25 m/s
     '{"type":"Feature","geometry":null,"properties":{"speed_ms":10.25}}'),
    ("x05-pgn129038-ais-class-a-to-geojson", "aisClassAPositionReport",
     {"messageId": 1, "userId": 244660000, "longitude": 45000000, "latitude": 525000000, "sog": 650},
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,52.5]},"properties":{"speed_ms":6.5}}'),
]


def _vector(name, to, data, expect, model):
    return OrderedDict([("name", name), ("from", FORMAT), ("to", to),
                        ("input", data.hex()), ("expect", expect), ("model", model)])


def roundtrip_vector(k, codec, codec_kind, earlier=()):
    """The same-format round trip of kind `k`: bytes packed from pick_values, which the
    codec must decode as `k` and encode back to the same bytes. `earlier`: the kinds
    before `k` in the pack."""
    data = pack_message(k, pick_values(k, earlier))
    sel, ent = decode(codec, data)
    if sel.name != k.name:
        raise GenError("vector for %s decodes as %s" % (k.name, sel.name))
    if encode(codec_kind, ent) != data:
        raise GenError("vector for %s does not round-trip" % k.name)
    model = OrderedDict([("@kind", k.name)])
    for key, x in ent.items():
        model[key] = model_text(x)
    return _vector("%s-roundtrip" % k.name, FORMAT, data, data.hex(), model)


def cross_vector(spec, by_id, codec):
    """One entry of CROSS as a vector; the hand-written `expect` must equal what the
    codec's decode gives as canonical GeoJSON."""
    name, ident, rawvals, expect = spec
    k = by_id.get(ident)
    if k is None:
        raise GenError("cross-format vector %s: definition %s has no kind" % (name, ident))
    fid = {f.id: f for f in k.fields}
    vals = {}
    for i, v in rawvals.items():
        if i not in fid:
            raise GenError("cross-format vector %s: no field %s" % (name, i))
        vals[fid[i]] = v & ((1 << fid[i].len) - 1)
    data = pack_message(k, vals)
    sel, ent = decode(codec, data)
    if sel.name != k.name:
        raise GenError("cross-format vector %s decodes as %s" % (name, sel.name))
    got = geojson_text(ent)
    if got != expect:
        raise GenError("cross-format vector %s: hand-written expect differs from the codec\n  hand:  %s\n  codec: %s" % (name, expect, got))
    model = OrderedDict([("@kind", k.name)])
    for key in ("lat", "lon", "speed_ms"):
        if key in ent:
            model[key] = model_text(ent[key])
    return _vector(name, "geojson", data, expect, model)


def build_vectors(kinds, codec):
    """-> ([(file name, text)] of every vector, names of the cross-format vectors)."""
    by_name = {ck.name: ck for ck in codec}
    files = []
    for i, k in enumerate(kinds):
        earlier = [other for other in kinds[:i] if other.pgn == k.pgn]
        files.append(("rt-%s.json" % k.name, roundtrip_vector(k, codec, by_name[k.name], earlier)))
    by_id = {k.id: k for k in kinds}
    xnames = []
    for spec in CROSS:
        files.append(("%s.json" % spec[0], cross_vector(spec, by_id, codec)))
        xnames.append(spec[0])
    return [(fn, json.dumps(vec, indent=2) + "\n") for fn, vec in files], xnames


# ---------------------------------------------------------------- checks of the written files

def core_module_text():
    """A module `core` with the keys of CORE_KEYS, for loading the pack."""
    lines = ["module core", "version 0.1.0", "distribution public",
             "source " + q("core key table built into tools/gen/canboat2pack.py")]
    lines += ["key %s %s -" % (name, typ) for name, typ in CORE_KEYS.items()]
    return "\n".join(lines) + "\n"


def check_core_def(text, label):
    """The key table built into the generator must be that of the given model/core.def."""
    try:
        real = gtcheck.parse_module(text, label)
    except gtcheck.CheckError as e:
        raise GenError(str(e))
    if dict(real.keys) != dict(CORE_KEYS):
        differ = sorted(set(real.keys.items()) ^ set(CORE_KEYS.items()))
        raise GenError("the core keys built into the generator differ (%s)"
                       % ", ".join("%s %s" % kv for kv in differ), label)


def load_output(module_text, pack_text, module_label=MODULE_DEF, pack_label=PACK_DEF):
    """Load the module and the pack as an engine does (gtcheck). -> (Module, Pack)."""
    try:
        model = gtcheck.Model()
        model.add(core_module_text(), "core")
        module = model.add(module_text, module_label)
        return module, gtcheck.load_pack(pack_text, model, pack_label)
    except gtcheck.CheckError as e:
        raise GenError("generated file does not load: %s" % e)


def check_kind_shapes(codec, kinds):
    """Invariants of the generator's output that are not load rules: each kind starts
    with the `when` of its PGN, has a field, has 1 to 6 `requires` keys, no two of its
    lines share a bit, and none ends past the definition's message."""
    src = {k.name: k for k in kinds}
    for ck in codec:
        d = src[ck.name].definition
        if not ck.whens or ck.whens[0] != (0, PGN_BITS, d.pgn):
            raise GenError("kind %s: first when is not its PGN" % ck.name)
        if not ck.fields:
            raise GenError("kind %s: no field" % ck.name)
        limit = PGN_BITS + (d.length * 8 if d.length else sum(f.bit_length for f in d.fields))
        spans = sorted([(s, s + l) for s, l, _ in ck.whens] + [(f.start, f.start + f.len) for f in ck.fields])
        for (_, a1), (b0, _) in zip(spans, spans[1:]):
            if b0 < a1:
                raise GenError("kind %s: overlapping bit ranges" % ck.name)
        if spans[-1][1] > limit:
            raise GenError("kind %s: a bit range ends at %d, past the message (%d bits)" % (ck.name, spans[-1][1], limit))
        if not ck.requires or len(ck.requires) > 6:
            raise GenError("kind %s: requires count" % ck.name)


def check_kind_order(codec):
    """Kinds of one PGN: every earlier kind either conflicts with a later one or is
    strictly more specific, so the first kind that holds is the right one."""
    by_pgn = OrderedDict()
    for ck in codec:
        by_pgn.setdefault(ck.whens[0][2], []).append(ck)
    for ks in by_pgn.values():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a = {(s, l): v for s, l, v in ks[i].whens[1:]}
                b = {(s, l): v for s, l, v in ks[j].whens[1:]}
                if relation(a, b) not in ("conflict", "super"):
                    raise GenError("kinds %s and %s cannot be told apart in this order" % (ks[i].name, ks[j].name))


def check_module_keys_used(module, codec):
    """Every key the module declares is mapped by a kind."""
    used = {f.key for ck in codec for f in ck.fields}
    unused = {"%s.%s" % (MODULE, n) for n in module.keys} - used
    if unused:
        raise GenError("module keys no kind maps: %s" % sorted(unused)[:5])


def check_vector(codec, fn, v):
    """Decode a vector's input and compare with its `model`; a round trip must encode
    back to `expect`, a geojson vector must give `expect` as canonical GeoJSON.
    -> the name of the kind it decodes as."""
    by_name = {ck.name: ck for ck in codec}
    if v["from"] != FORMAT or not re.fullmatch(r"(?:[0-9a-f]{2})+", v["input"]):
        raise GenError("vector %s: input" % fn)
    sel, ent = decode(codec, bytes.fromhex(v["input"]))
    if sel.name != v["model"]["@kind"]:
        raise GenError("vector %s: kind" % fn)
    for key, want in v["model"].items():
        if key == "@kind":
            continue
        got = ent[key]
        if isinstance(got, float):
            if abs(got - float(want)) > 1e-9:
                raise GenError("vector %s: %s" % (fn, key))
        elif model_text(got) != want:
            raise GenError("vector %s: %s" % (fn, key))
    if v["to"] == FORMAT:
        if encode(by_name[sel.name], ent).hex() != v["expect"] or v["expect"] != v["input"]:
            raise GenError("vector %s: round trip" % fn)
    elif v["to"] == "geojson":
        if geojson_text(ent) != v["expect"]:
            raise GenError("vector %s: geojson" % fn)
        json.loads(v["expect"])
    else:
        raise GenError("vector %s: target" % fn)
    return sel.name


def check_vectors(codec, vectors):
    """Check every vector ([(file name, parsed JSON)]): names are unique, each passes
    check_vector, and every kind has a same-format round trip."""
    names, seen_kinds = set(), set()
    for fn, v in vectors:
        if v["name"] in names:
            raise GenError("duplicate vector name %s" % v["name"])
        names.add(v["name"])
        kind = check_vector(codec, fn, v)
        if v["to"] == FORMAT:
            seen_kinds.add(kind)
    missing = {ck.name for ck in codec} - seen_kinds
    if missing:
        raise GenError("kinds without a round-trip vector: %s" % sorted(missing)[:5])


def self_check(files, kinds):
    """Check the texts of a run before any is written: `files` maps each output path
    to its text. The module and the pack are loaded from their text and every vector is
    parsed from its text, so what is checked is what is written.
    -> (vector files, module keys)."""
    module, pack = load_output(files[MODULE_DEF], files[PACK_DEF])
    if module.name != MODULE:
        raise GenError("module name")
    codec = codec_kinds(pack)
    if pack.format != FORMAT or len(codec) != len(kinds):
        raise GenError("pack: kind count")
    check_kind_shapes(codec, kinds)
    check_kind_order(codec)
    check_module_keys_used(module, codec)
    prefix = VECTORS + "/"
    vectors = sorted((rel[len(prefix):], json.loads(text)) for rel, text in files.items() if rel.startswith(prefix))
    check_vectors(codec, vectors)
    return len(vectors), len(module.keys)


# ---------------------------------------------------------------- main

def build_outputs(db, sha):
    """Plan and emit. -> (plan, {output path: text} in the order written, cross vector
    names). Nothing is written and nothing is read."""
    plan = make_plan(db)
    files = OrderedDict()
    files[MODULE_DEF] = emit_module(plan.keys, sha, db)
    files[PACK_DEF] = emit_pack(plan.kinds, sha, db)
    codec = codec_kinds(load_output(files[MODULE_DEF], files[PACK_DEF])[1])
    vectors, xnames = build_vectors(plan.kinds, codec)
    for fn, text in vectors:
        files["%s/%s" % (VECTORS, fn)] = text
    files[PACK_MD] = emit_pack_md(plan.kinds, plan.unmapped, plan.keys, db, sha, len(vectors), xnames)
    return plan, files, xnames


def write_outputs(out, files):
    """Write the checked texts and remove every *.json of the vectors directory that
    is not a vector of this run."""
    for fn in out.listdir(VECTORS):
        if fn.endswith(".json") and "%s/%s" % (VECTORS, fn) not in files:
            out.remove("%s/%s" % (VECTORS, fn))
    for rel, text in files.items():
        out.write(rel, text)


def print_summary(db, sha, plan, xnames, n_files, n_keys):
    kinds, definitions = plan.kinds, db.definitions
    reasons = Counter(u.reason for u in plan.unmapped)
    print("source: %s %s @ %s (CANboat %s)" % (REPO, DB_PATH, sha, db.version))
    print("PGN definitions in the source: %d (%d distinct PGNs)" % (len(definitions), len({d.pgn for d in definitions})))
    print("kinds generated: %d (%d distinct PGNs)" % (len(kinds), len({k.pgn for k in kinds})))
    for code in REASON_TITLES:
        print("not mapped, %s: %d" % (code, reasons.get(code, 0)))
    print("module %s keys: %d" % (MODULE, n_keys))
    core_use = Counter(f.key for k in kinds for f in k.fields if f.core)
    print("core mappings: %s" % dict(core_use))
    print("kinds with an unmapped inexpressible field: %d" % sum(1 for k in kinds if k.unexpressed))
    print("kinds from definitions CANboat marks incomplete: %d" % sum(1 for k in kinds if not k.definition.complete))
    print("vectors: %d (%d round trips, %d to geojson)" % (n_files, len(kinds), len(xnames)))
    print("self-check: passed")


def run(args, out):
    src_dir = os.path.join(args.out, "sources")
    db_path = os.path.join(src_dir, "canboat.json")
    hint = "; download it with --commit <sha> --fetch"
    if args.core_def:
        check_core_def(_decode(_read_bytes(args.core_def), args.core_def), args.core_def)
    if args.commit:
        if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
            raise GenError("--commit takes a full 40-character SHA")
        if args.fetch:
            fetch_sources(src_dir, args.commit)
        sha = args.commit
    else:
        prov_path = os.path.join(src_dir, "PROVENANCE.md")
        sha = read_commit(_decode(_read_bytes(prov_path, "; give --commit <sha>"), prov_path), prov_path)
    db_bytes = _read_bytes(db_path, hint)
    db = parse_database(_decode(db_bytes, db_path), db_path)
    provenance = None
    if args.commit:
        license_path = os.path.join(src_dir, "LICENSE")
        license_bytes = _read_bytes(license_path, hint)
        _decode(license_bytes, license_path)
        provenance = provenance_text(sha, db, {"canboat.json": db_bytes, "LICENSE": license_bytes})
    plan, files, xnames = build_outputs(db, sha)
    n_files, n_keys = self_check(files, plan.kinds)
    # Everything is checked: only now does the run touch the output tree.
    if provenance is not None:
        out.write(PROVENANCE, provenance)
    write_outputs(out, files)
    print_summary(db, sha, plan, xnames, n_files, n_keys)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    genio.add_arguments(ap, what="output root (holds sources/, model/, packs/)")
    ap.add_argument("--commit", help="canboat commit SHA; writes sources/PROVENANCE.md")
    ap.add_argument("--fetch", action="store_true",
                    help="with --commit: download the two source files of that commit first")
    ap.add_argument("--core-def", help="goat-transformers model/core.def, to check the built-in core key table")
    args = ap.parse_args(argv)
    if args.fetch and not args.commit:
        ap.error("--fetch needs --commit <sha>")
    if args.fetch and args.check:
        ap.error("--fetch downloads files and --check writes nothing; give one of them")
    out = genio.Output(args.out, check=args.check)
    try:
        run(args, out)
    except GenError as e:
        print("%s: %s" % (NAME, e), file=sys.stderr)
        return 1
    return out.report(NAME)


if __name__ == "__main__":
    sys.exit(main())
