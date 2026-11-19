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
        <out>/packs/nmea2000-seq/pack.def, pack.md, vectors/*.json
                                     definitions with one counted repeating field set, in a
                                     second pack of layout sequential (spec 0.8); module n2k
                                     gains their keys and lists after the existing ones.
                                     Not written when no definition qualifies.

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
SEQ_FORMAT = "nmea2000-seq"
MODULE = "n2k"
PACK_VERSION = "0.2.0"
MODULE_VERSION = "0.2.0"
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
SEQ_PACK_DEF = "packs/%s/pack.def" % SEQ_FORMAT
SEQ_PACK_MD = "packs/%s/pack.md" % SEQ_FORMAT
SEQ_VECTORS = "packs/%s/vectors" % SEQ_FORMAT

# model/core.def of goat-transformers, version 0.2.0 (checked against --core-def when given)
CORE_KEYS = OrderedDict([
    ("uid", "string"), ("type", "string"), ("time_ms", "int"),
    ("time_error_ms", "float"), ("time_state", "string"), ("lat", "float"),
    ("lon", "float"), ("hae", "float"), ("ce", "float"), ("le", "float"),
    ("callsign", "string"), ("course", "float"), ("speed_ms", "float"), ("how", "string"),
    ("stale_ms", "int"), ("time_text", "string"), ("stale_text", "string"),
    ("access", "string"), ("display_name", "string"),
])
# packs/geojson/pack.def: member order of the canonical output
GEOJSON_PROPS = ["type", "time_ms", "how", "ce", "le", "callsign", "course", "speed_ms"]

# CANboat field types, by how the pack can carry them.
NUMERIC_TYPES = {"NUMBER", "TIME", "DURATION", "DATE", "MMSI", "PGN", "ISO_NAME", "ADDRESS",
                 "LOOKUP", "INDIRECT_LOOKUP", "BITLOOKUP", "FIELD_INDEX",
                 "DYNAMIC_FIELD_KEY", "DYNAMIC_FIELD_LENGTH"}
VARIABLE_TYPES = {"STRING_LAU", "STRING_LZ", "VARIABLE", "DYNAMIC_FIELD_VALUE"}
SKIP_TYPES = {"RESERVED", "SPARE"}
# Members of a CANboat field that state a raw "no value" (spec 0.9 sentinels), in the order
# written to `absent`: the first is what encode writes for an absent key.
SENTINEL_MEMBERS = ("UnknownValue", "OutOfRangeValue", "ReservedValue")

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
                 "label", "description", "physical_quantity", "lookup", "variable_length", "sentinels", "stated")


class Definition:
    """One entry of `PGNs`. `index` is its position in the file; `repeating` is true when
    it declares a repeating field set; `where` names it in an error message."""
    __slots__ = ("where", "index", "pgn", "id", "description", "complete", "fallback",
                 "repeating", "repeat", "repeat2", "length", "fields")


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
    # Raw wire values that mean "no value" (spec 0.9 `absent`), as the database states them
    # for the field: UnknownValue first (what encode writes for an absent key), then
    # OutOfRangeValue and ReservedValue. An MMSI also takes 0: the database's description of
    # the MMSI field type says devices send it for "none" and it is treated as not available.
    sent, f.stated = [], {}
    for member in SENTINEL_MEMBERS:
        v = r.get(member, _is_int, "an integer", null_ok=True)
        if v is not None:
            if v < 0:
                r.fail(member, "is negative")
            sent.append(v)
            f.stated[member] = v
    if f.field_type == "MMSI":
        sent.append(0)
    f.sentinels = tuple(OrderedDict.fromkeys(sent))
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
    # the first repeating field set: (size, start field, count field), 1-based field
    # numbers; the count field is None when the set repeats to the end of the message
    d.repeat = None
    if "RepeatingFieldSet1Size" in raw:
        d.repeat = tuple(r.get("RepeatingFieldSet1%s" % m, _is_int, "an integer", null_ok=True)
                         for m in ("Size", "StartField", "CountField"))
    d.repeat2 = "RepeatingFieldSet2Size" in raw
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
        self.absent = src.sentinels
        for v in self.absent:
            if v >= 1 << self.len:
                raise GenError("%s: field %s states the raw value %d for no value, which does not fit %d bits"
                               % (src.where, src.id, v, self.len))

    @property
    def absent_option(self):
        """` absent <values>` for the field line, or ""."""
        return " absent " + ",".join(str(v) for v in self.absent) if self.absent else ""

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

Plan = namedtuple("Plan", "kinds unmapped keys seq seq_keys seq_lists")


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


# ---------------------------------------------------------------- sequential pack (spec 0.8)
#
# A definition with one repeating field set whose count field stands directly before the
# set can be stated with `layout sequential` and `group <list> count <len>`. `layout` holds
# for a whole pack, so these definitions go to a second pack, SEQ_FORMAT, and the
# fixed-layout pack stays as it is.

class SeqKind:
    """A definition stated as sequential lines: `when` lines, the top-level lines, then one
    counted group. `lines` and `items` hold ("field", Field), ("const", bits, value) and
    ("pad", bits) in wire order."""

    def __init__(self, definition):
        self.definition = definition
        self.pgn = definition.pgn
        self.id = definition.id
        self.name = None
        self.whens = [(0, PGN_BITS, definition.pgn, "PGN")]   # (pos, len, value, id)
        self.lines = []
        self.fields = []
        self.count_len = None
        self.count_id = None
        self.items = []
        self.item_fields = []
        self.list = None
        self.unexpressed = []
        self.requires = []

    def match_set(self):
        """The match fields only; a reserved `when` narrows the kind further."""
        return {(p, l): v for p, l, v, i in self.whens[1:] if not i.startswith("reserved:")}


# One list of module n2k: its meaning and its PGN.
ListDecl = namedtuple("ListDecl", "label pgn")


def skip_lines(f):
    """RESERVED bits shall be 1 and SPARE bits 0 (CANboat FieldTypes); a `const` is 1 to
    64 bits, so a longer reserved field is several."""
    n = f.bit_length
    if f.field_type == "SPARE":
        return [("pad", n)]
    out = []
    while n > 0:
        c = min(n, 64)
        out.append(("const", c, (1 << c) - 1))
        n -= c
    return out


def seq_plan(d):
    """(SeqKind, None), or (None, detail) naming what the pack language cannot state;
    (None, None) for a definition with no repeating field set."""
    fl = d.fields
    if d.repeat is None:
        return None, None
    size, start, count = d.repeat
    for f in fl:
        if f.field_type in VARIABLE_TYPES or f.variable_length or f.bit_length is None:
            return None, "repeating field set, and a %s field" % (
                f.field_type + (" of variable size" if f.field_type == "BINARY" else ""))
    if count is None:
        return None, "repeating field set with no count field: it repeats to the end of the message"
    if d.repeat2:
        return None, "two repeating field sets"
    if size is None or start is None:
        raise GenError("%s: a repeating field set without its size or start field" % d.where)
    if count != start - 1:
        return None, ("repeating field set whose count (field %d) is not directly before the set (field %d)"
                      % (count, start))
    if start + size - 1 != len(fl):
        return None, "fields follow the repeating field set"
    if any(f.bit_offset is None for f in fl):
        raise GenError("%s: a field without a position and no variable field before it" % d.where)
    end = 0
    for f in fl[:start]:
        if f.bit_offset != end:
            return None, "repeating field set; fields overlap or leave a gap"
        end += f.bit_length
    if any(f.has_match for f in fl[start - 1:]):
        return None, "a match value inside the repeating field set"
    cf = fl[count - 1]
    if (cf.field_type != "NUMBER" or cf.signed or (cf.resolution or 1) != 1 or cf.offset
            or cf.has_match or not 1 <= cf.bit_length <= 64):
        return None, "repeating field set whose count field is not an unsigned integer"
    k = SeqKind(d)
    head = fl[:count - 1]
    # The leading run of match and reserved fields becomes the kind's `when` lines (spec
    # 0.8: `when` lines are a kind's first lines). A reserved field inside the run is a
    # `when` of its all-ones value, which NMEA 2000 requires on the wire.
    run = 0
    while run < len(head) and (head[run].has_match or head[run].field_type in SKIP_TYPES):
        run += 1
    while run > 0 and not head[run - 1].has_match:
        run -= 1
    if any(f.has_match for f in head[run:]):
        return None, "a match value follows a data field (a kind's `when` lines come first)"
    for f in head[:run]:
        pos = f.bit_offset + PGN_BITS
        if f.has_match:
            k.whens.append((pos, f.bit_length, map_field(f)[1], f.id))
        else:
            if f.bit_length > 64:
                return None, "a reserved field of more than 64 bits between match values"
            v = (1 << f.bit_length) - 1 if f.field_type == "RESERVED" else 0
            k.whens.append((pos, f.bit_length, v, "reserved:" + f.id))

    def body(fields, lines, mapped):
        for f in fields:
            m = map_field(f)
            if m[0] == "skip":
                lines.extend(skip_lines(f))
            elif m[0] == "no":
                k.unexpressed.append((f.id, m[1]))
                lines.append(("pad", f.bit_length))
            else:
                fo = Field(f, m[1], m[2], m[3])
                lines.append(("field", fo))
                mapped.append(fo)
    body(head[run:], k.lines, k.fields)
    k.count_len, k.count_id = cf.bit_length, cf.id
    body(fl[start - 1:], k.items, k.item_fields)
    if not k.item_fields:
        return None, "repeating field set with no field the pack language can carry"
    return k, None


def _seq_match_sets(definitions, fixed, plans):
    """{pgn: [(definition id, match set or None)]} over every definition but the
    catch-all ones, with the match set each one has in either pack."""
    sets = defaultdict(list)
    for d in definitions:
        if d.fallback:
            continue
        if d.id in fixed:
            ms = fixed[d.id].match_set()
        elif d.id in plans:
            ms = plans[d.id].match_set()
        else:
            ms = _match_set_of_unmapped(d)
        sets[d.pgn].append((d.id, ms))
    return sets


def _seq_indistinguishable(k, others, fixed, mapped):
    """Why a sequential kind cannot be told apart, or None. Against a kind of the fixed
    pack the match sets must conflict, so the two packs accept disjoint messages and
    either can be tried first; against the rest, the rule of _indistinguishable."""
    a = k.match_set()
    for oid, b in others:
        if oid == k.id:
            continue
        if b is None:
            return "definition %s of the same PGN has a match field at a variable position" % oid
        r = relation(a, b)
        if oid in fixed and r != "conflict":
            return "a message can satisfy its match values and those of kind %s of pack %s" % (fixed[oid].name, FORMAT)
        if r == "equal":
            return "same match values as definition %s" % oid
        if r == "incomparable":
            return ("a message can satisfy its match values and those of definition %s, "
                    "and neither set contains the other" % oid)
        if r == "sub" and oid not in mapped:
            return "its match values also hold for the unmapped, more specific definition %s" % oid
    return None


def classify_seq(definitions, kinds, unmapped):
    """-> (sequential kinds in pack order, the unmapped list for the record). `kinds`,
    the fixed pack, is not changed."""
    fixed = {k.id: k for k in kinds}
    by_id = {d.id: d for d in definitions}
    plans, rest = OrderedDict(), []
    for u in unmapped:
        if u.reason not in ("repeating", "variable"):
            rest.append(u)
            continue
        k, why = seq_plan(by_id[u.id])
        if k is None:
            rest.append(u._replace(detail=why or u.detail))
        else:
            plans[u.id] = k
    sets = _seq_match_sets(definitions, fixed, plans)
    mapped = OrderedDict(plans)
    dropped = []
    changed = True
    while changed:
        changed = False
        for k in list(mapped.values()):
            why = _seq_indistinguishable(k, sets[k.pgn], fixed, mapped)
            if why:
                del mapped[k.id]
                dropped.append(_unmapped(k.definition, "indistinguishable", why))
                changed = True
    per_pgn = Counter(d.pgn for d in definitions if not d.fallback)
    seq = [k for i, k in plans.items() if i in mapped]
    for k in seq:
        k.name = "pgn%d" % k.pgn if per_pgn[k.pgn] == 1 else "pgn%d_%s" % (k.pgn, snake(k.id))
        k.list = "pgn%d_%s" % (k.pgn, snake(k.count_id))
    clash = Counter(k.list for k in seq)
    for k in seq:
        if clash[k.list] > 1:
            k.list = "%s_%s" % (k.name, snake(k.count_id))
    seq.sort(key=lambda k: (k.pgn, -sum(l for _, l, _, i in k.whens if not i.startswith("reserved:")),
                            k.definition.index))
    names = {k.name for k in seq} | {k.name for k in kinds}
    if len(names) != len(seq) + len(kinds):
        raise GenError("a kind name in both packs")
    # A fixed-layout definition left out because a more specific one had no kind: say
    # where that one is now, and why the fixed one still has none.
    out = []
    for u in rest:
        m = re.match(r"its match values also hold for the unmapped, more specific definition (\w+)$", u.detail)
        if u.reason == "indistinguishable" and m and m.group(1) in mapped:
            u = u._replace(detail="its match values also hold for the more specific definition %s, which pack %s "
                                  "maps; the two packs accept disjoint messages" % (m.group(1), SEQ_FORMAT))
        out.append(u)
    return seq, out + dropped


def assign_seq_keys(seq, keys):
    """Keys of the sequential pack. A key of `keys` (the fixed pack's) is reused where its
    signature agrees; a new key follows the naming rule of declare_module_keys, and no
    existing key changes (AGENTS.md rule 7). -> ({new key: KeyDecl}, {list: ListDecl})."""
    new, lists, raw = OrderedDict(), OrderedDict(), []
    for k in seq:
        cm = core_mapping(k)
        used = set()
        for f in k.fields:
            if f in cm and cm[f][0] not in used:
                f.key, f.transform = cm[f]
                f.type, f.core = "float", True
                used.add(f.key)
            else:
                raw.append((k, f))
        raw.extend((k, f) for f in k.item_fields)
        if k.list in keys:
            raise GenError("%s: list %s has the name of a key" % (k.definition.where, k.list))
        lists[k.list] = ListDecl("%s: one item per %s" % (k.definition.description, k.count_id), k.pgn)

    def take(name, k, f):
        old = keys.get(name) or new.get(name)
        if old is not None and old.sig != f.signature():
            return False
        if old is None:
            old = new[name] = KeyDecl(f.type, f.unit, f.signature(), f.src.label, f.src.field_type, [])
        if name in new and k.pgn not in old.pgns:
            old.pgns.append(k.pgn)
        f.key = "%s.%s" % (MODULE, name)
        return True

    by_id = OrderedDict()
    for k, f in raw:
        by_id.setdefault(snake(f.id), []).append((k, f))
    for base, uses in by_id.items():
        agree = len({f.signature() for _, f in uses}) == 1
        for k, f in uses:
            if base in keys and keys[base].sig == f.signature():
                take(base, k, f)
            elif base not in keys and base not in lists and agree and take(base, k, f):
                pass
            elif take("pgn%d_%s" % (k.pgn, base), k, f):
                pass
            elif not take("%s_%s" % (k.name, base), k, f):
                raise GenError("%s: no free key name for %s" % (k.definition.where, f.id))
    for name in list(new) + list(lists):
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise GenError("bad key name %r" % name)
    if set(new) & set(lists):
        raise GenError("a list and a key share a name")
    use_count = Counter(f.key for k in seq for f in k.fields)
    for k in seq:
        for scope in (k.fields, k.item_fields):
            ks = [f.key for f in scope]
            if len(set(ks)) != len(ks):
                raise GenError("%s: kind %s maps a key twice in one scope" % (k.definition.where, k.name))
        rawk = [f for f in k.fields if not f.core]
        order = sorted(range(len(rawk)), key=lambda i: (use_count[rawk[i].key], i))[:5]
        k.requires = [rawk[i].key for i in sorted(order)] + ["%s.%s" % (MODULE, k.list)]
    return new, lists


def make_plan(db):
    """Every decision about the output, from the parsed database."""
    kinds, unmapped = classify(db.definitions)
    keys = assign_keys(kinds)
    seq, unmapped = classify_seq(db.definitions, kinds, unmapped)
    seq_keys, seq_lists = assign_seq_keys(seq, keys)
    if len(kinds) + len(seq) + len(unmapped) != len(db.definitions):
        raise GenError("definitions unaccounted for")
    if not kinds:
        raise GenError("no definition can be mapped to a kind", db.label)
    return Plan(kinds, unmapped, keys, seq, seq_keys, seq_lists)


# ---------------------------------------------------------------- emit

def q(text):
    """A quoted token. The pack grammar has no escape: `"` becomes `'`."""
    text = str(text).replace('"', "'").replace("\n", " ")
    return '"%s"' % text


def unit_token(u):
    return q(u) if re.search(r"\s", u) or u.startswith("#") else u


def _source_line(sha, db):
    return "source        " + q("%s %s at commit %s (CANboat %s, Apache License 2.0)" % (REPO, DB_PATH, sha, db.version))


def emit_module(keys, sha, db, seq_keys=None, seq_lists=None):
    """The text of model/n2k.def: the keys of the fixed pack, then those the sequential
    pack adds and its lists. The lines of the first part do not depend on the second."""
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
    if seq_keys or seq_lists:
        out += ["",
                "# Keys and lists first used by pack %s (PGNs with a repeating field set). Keys" % SEQ_FORMAT,
                "# above are reused there where the field agrees; the PGNs named above are those of",
                "# pack %s." % FORMAT]
        w = max(len(n) for n in seq_keys) if seq_keys else 1
        for name, e in seq_keys.items():
            lookup = e.sig[4]
            kind = e.field_type + (" " + lookup if lookup else "")
            out.append("key  %-*s  %-6s  %-8s  %s" % (w, name, e.type, unit_token(e.unit),
                                                  q("%s; CANboat %s; PGN %s" % (e.label, kind, ", ".join(str(p) for p in e.pgns)))))
        w = max(len(n) for n in seq_lists) if seq_lists else 1
        for name, e in seq_lists.items():
            out.append("list  %-*s  %s" % (w, name, q("%s; PGN %d" % (e.label, e.pgn))))
    return "\n".join(out) + "\n"


def emit_seq_pack(seq, sha, db):
    """The text of packs/nmea2000-seq/pack.def."""
    out = [
        "# NMEA 2000 parameter groups with a repeating field set, from the CANboat PGN database.",
        "# Public. Message = 3 bytes PGN (little-endian), then the reassembled payload, read in",
        "# order (spec 0.8 sequential layout). The fixed-layout PGNs are in pack nmea2000.",
        "# GENERATED by tools/gen/canboat2pack.py. Do not edit.",
        "format        %s" % SEQ_FORMAT,
        "version       %s" % PACK_VERSION,
        "distribution  public",
        _source_line(sha, db),
        "source        " + q("https://github.com/%s/blob/%s/%s" % (REPO, sha, DB_PATH)),
        "uses          %s" % MODULE,
        "wire          bits",
        "layout        sequential",
        "bit_order     lsb",
    ]

    def lines(ls, ind):
        w = max([len(x[1].key) for x in ls if x[0] == "field"] or [1])
        for x in ls:
            if x[0] == "field":
                out.append("%sfield     %-*s  %-3d %s%s" % (ind, w, x[1].key, x[1].len, x[1].transform, x[1].absent_option))
            elif x[0] == "const":
                out.append("%sconst     %d %d" % (ind, x[1], x[2]))
            else:
                out.append("%spad       %d" % (ind, x[1]))
    for k in seq:
        out.append("")
        out.append("# PGN %d %s: %s%s" % (k.pgn, k.id, k.definition.description.replace("\n", " "),
                                       "" if k.definition.complete else " [CANboat: incomplete]"))
        out.append("kind      %s" % k.name)
        for _, l, v, _ in k.whens:
            out.append("when      %d %d" % (l, v))
        out.append("requires  " + " ".join(k.requires))
        lines(k.lines, "")
        out.append("group     %s.%s count %d" % (MODULE, k.list, k.count_len))
        lines(k.items, "  ")
        out.append("end")
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
            out.append(("field     %-*s  %-12s %s" % (w, f.key, f.locator, f.transform + f.absent_option)).rstrip())
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


def _md_counts(kinds, unmapped, keys, db, n_vectors, xnames, seq=()):
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
    if seq:
        L.append("| mapped by pack `%s` (a repeating field set with a count) | %d |" % (SEQ_FORMAT, len(seq)))
    for code, title in REASON_TITLES.items():
        L.append("| not mapped: %s | %d |" % (title[0].lower() + title[1:], len(by_reason.get(code, []))))
    L += [
        "| keys in module `%s`%s | %d |" % (MODULE, " that this pack maps" if seq else "", len(keys)),
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


def _md_core_keys(kinds, seq=()):
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
    ]
    if seq:
        L += ["  ellipsoid (PGN 129029, in pack `%s`, says \"referenced to WGS-84\" and does not name" % SEQ_FORMAT,
              "  the ellipsoid)."]
    else:
        L.append("  ellipsoid (PGN 129029 says \"referenced to WGS-84\" and is not fixed-layout).")
    L.append("")
    return L


def _md_limits(kinds, seq=()):
    partial = [(k, k.unexpressed) for k in kinds if k.unexpressed]
    L = [
        "## What the pack language cannot express yet",
        "",
        "- **\"Not available\" values where the database states none.** Section \"Absent values\"",
        "  lists the field types whose fields carry no `absent` option, and why.",
        "- **Reserved and spare bits.** NMEA 2000 sets them to 1; `encode` writes 0 in every bit no",
        "  field covers. A real message with reserved bits set does not round-trip byte-identically.",
        "- **Trailing bytes.** The message ends at the last mapped or `when` bit, rounded up to a",
        "  byte. A definition that ends in reserved fields encodes shorter than its NMEA 2000 length",
        "  (PGN 129026 encodes 3 + 6 bytes, not 3 + 8). Decode accepts the full length.",
    ] + ([
        "- **Repeating field sets and variable-length fields.** The layout of this pack is fixed",
        "  (`layout` is pack-wide). A definition with one repeating field set whose count field stands",
        "  directly before the set is in pack `%s` (spec 0.8 sequential layout). The others," % SEQ_FORMAT,
        "  listed below with the reason, need an addition named in `packs/%s/pack.md`." % SEQ_FORMAT,
    ] if seq else [
        "- **Repeating field sets and variable-length fields** (STRING_LAU, STRING_LZ, VARIABLE,",
        "  BINARY of variable size, key/length/value fields, fields placed after any of these). These",
        "  need the future groups addition; the definitions are listed below.",
    ]) + [
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


# Field types with no per-field "no value" statement in the database, and what the database
# says of the type: why the pack writes no `absent` option for them.
NO_SENTINEL_REASONS = OrderedDict([
    ("FLOAT", "the database names NaN for the type and no raw value; a NaN has many bit patterns"),
    ("STRING_FIX", "the database names the empty string for the type and no raw value, and allows 0x00, 0xff "
                   "and `@` as padding; most such fields are longer than the 64 bits `absent` takes"),
    ("BITLOOKUP", "the database states no sentinel for the type: any combination of bits is a value"),
    ("BINARY", "the database states no sentinel for the type"),
    ("PGN", "the database states no sentinel for the type"),
    ("ISO_NAME", "the database states no sentinel for the type"),
    ("ADDRESS", "the database states that every value is meaningful (254 is the null address, 255 broadcast)"),
])


def sentinel_counts(kinds):
    """-> (Counter of field types with `absent`, Counter of those without), over mapped fields."""
    with_, without = Counter(), Counter()
    for k in kinds:
        for f in list(k.fields) + list(getattr(k, "item_fields", [])):
            (with_ if f.absent else without)[f.src.field_type] += 1
    return with_, without


def _md_absent(kinds, seq=()):
    with_, without = sentinel_counts(list(kinds) + list(seq))
    L = [
        "## Absent values",
        "",
        "NMEA 2000 reserves the top values of a field for \"no value\": all bits set for not available",
        "and the values just below it for out of range and reserved. The database states them for each",
        "field as raw wire integers: `UnknownValue`, `OutOfRangeValue`, `ReservedValue`. A field that",
        "states them carries the option `absent <unknown>,<out of range>,<reserved>` (spec 0.9), in",
        "that order, so:",
        "",
        "- decode leaves the key absent when the raw value is one of them (an all-ones latitude is no",
        "  latitude, not 214.7 degrees);",
        "- encode writes the first, the not-available value, for a key the entity does not hold, where",
        "  it wrote zero bits before.",
        "",
        "An MMSI field also takes the raw value 0: the database's description of the MMSI field type",
        "says devices send 0 for \"none\" and that it is treated as not available. A field the database",
        "gives no such member keeps no option, whatever its type: a lookup of one or two bits uses every",
        "value, and the database states none for the 64-bit numbers (the latitude and longitude of PGN",
        "129029, for example). The pack uses only these statements of the database.",
        "",
        "| Field type | Mapped fields with `absent` | Mapped fields without |",
        "|---|---|---|",
    ]
    for ft in sorted(set(with_) | set(without)):
        L.append("| %s | %d | %d |" % (ft, with_.get(ft, 0), without.get(ft, 0)))
    L += ["", "Types whose fields never carry `absent`:", "", "| Field type | Why |", "|---|---|"]
    for ft, why in NO_SENTINEL_REASONS.items():
        if without.get(ft):
            L.append("| %s | %s |" % (ft, why))
    L += ["",
          "The option needs engine version 0.9. A round trip of a message that holds an out-of-range or",
          "reserved value returns the not-available value in its place (ruling 7 of 0.9).",
          ""]
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


def _md_vectors(xnames, seq=()):
    return [
        "## Vectors",
        "",
        "- `rt-<kind>.json`: one same-format round trip per kind. The generator packs the bytes itself",
        "  from values inside each field's range that survive scaling exactly; unmapped bits are 0 and",
        "  the message has the encoded length, so the round trip is byte-identical. `model` holds",
        "  `@kind` and every decoded key.",
        "- %s: conversions to `geojson`, with the expected text" % ", ".join("`%s.json`" % n for n in xnames),
        "  written by hand from the canonical GeoJSON rules and checked by the generator against its",
    ] + ([
        "  own codec. PGN 129029 (GNSS Position Data) is in pack `%s`, with its own vector to" % SEQ_FORMAT,
        "  `geojson`.",
    ] if seq else [
        "  own codec. PGN 129029 has no vector: it has a repeating field set and no kind.",
    ]) + [
        "- %s: a latitude that holds its not-available or its out-of-range value decodes to no" % ", ".join(
            "`%s.json`" % spec[0] for spec in SENTINEL_VECTORS),
        "  `lat` (`@absent`); the out-of-range value re-encodes as the not-available one, and the",
        "  position without a latitude has no GeoJSON geometry. The raw values are those the database",
        "  states for the field; the expected bytes are packed by hand from them.",
        "- `%s`: the other way, a key the entity does not hold is written as its" % GEOJSON_VECTOR,
        "  not-available value: a Feature with no geometry, with the `requires` keys of the AIS Class A",
        "  position report as context, encodes latitude and longitude as all-but-the-sign-bit ones.",
        "  The vector belongs to the pack that owns its input.",
        "",
        "Vectors hold lowercase hex text in `input` / `expect`.",
        "",
    ]


def _md_unmapped(unmapped, seq=()):
    by_reason = _by_reason(unmapped)
    L = ["## Definitions not mapped", ""]
    for code, title in REASON_TITLES.items():
        rows = by_reason.get(code, [])
        L += ["### %s (%d)" % (title, len(rows)), ""]
        if code in ("repeating", "variable"):
            L += (["The Detail column names what the pack language cannot state; `packs/%s/pack.md`" % SEQ_FORMAT,
                   "names the addition each needs.", ""] if seq else ["These need the future groups addition.", ""])
        if not rows:
            L += ["None.", ""]
            continue
        L += ["| PGN | CANboat id | Description | Detail |", "|---|---|---|---|"]
        for u in sorted(rows, key=lambda r: (r.pgn, r.id)):
            L.append("| %d | `%s` | %s | %s |" % (u.pgn, u.id, u.description.replace("|", "/").replace("\n", " "), u.detail))
        L.append("")
    return L


def emit_pack_md(kinds, unmapped, keys, db, sha, n_vectors, xnames, seq=()):
    """The text of packs/nmea2000/pack.md."""
    lines = (_md_header(db, sha) + _md_counts(kinds, unmapped, keys, db, n_vectors, xnames, seq)
             + _md_field_rules(kinds) + _md_absent(kinds, seq) + _md_core_keys(kinds, seq) + _md_limits(kinds, seq)
             + _md_incomplete(kinds) + _md_vectors(xnames, seq) + _md_unmapped(unmapped, seq))
    return "\n".join(lines)


SEQ_ADDITIONS = [
    ("repeating field set, and a STRING_LAU", "text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset)"),
    ("repeating field set, and a STRING_LZ", "text whose length a preceding byte states, followed by a zero byte (a counted `ascii`)"),
    ("repeating field set, and a VARIABLE", "a field laid out as a field of the PGN another field names: an indirect layout"),
    ("repeating field set, and a DYNAMIC_FIELD_VALUE", "a value whose type and length follow from an earlier key field"),
    ("repeating field set, and a BINARY of variable size", "an opaque field whose bit length an earlier field states"),
    ("repeating field set with no count field", "a group that repeats to the end of the message (or of a `length` extent)"),
    ("repeating field set whose count", "a `count` taken from a field read earlier, not from the bits at the cursor"),
    ("two repeating field sets", "a `count` taken from a field read earlier"),
    ("STRING_LAU", "text whose length a preceding byte states, counting itself and the encoding byte (a counted `ascii`, with an offset)"),
    ("STRING_LZ", "text whose length a preceding byte states, followed by a zero byte (a counted `ascii`)"),
    ("BINARY of variable size", "an opaque field whose bit length an earlier field states"),
    ("DYNAMIC_FIELD_VALUE", "a value whose type and length follow from an earlier key field"),
    ("catch-all definition", "a `when` that holds for a range of values"),
]


def seq_addition(detail):
    for head, need in SEQ_ADDITIONS:
        if detail.startswith(head):
            return need
    return None


def emit_seq_pack_md(seq, unmapped, seq_keys, seq_lists, db, sha, vec_names):
    L = []
    A = L.append
    A("# Pack: %s" % SEQ_FORMAT)
    A("")
    A("NMEA 2000 parameter groups (PGNs) that hold a repeating field set, generated from the CANboat")
    A("PGN database (`%s` `%s` at commit `%s`, CANboat %s, Apache License 2.0) by" % (REPO, DB_PATH, sha, db.version))
    A("`tools/gen/canboat2pack.py`, the generator of pack `%s`. Do not edit `pack.def`, `model/%s.def`" % (FORMAT, MODULE))
    A("or the vectors by hand; change the generator and run it again.")
    A("")
    A("Status: Built. Generated from the database; the generator checks every vector with its own")
    A("codec, written from `spec/engine-spec.md` and not from an engine.")
    A("")
    A("## Why a second pack")
    A("")
    A("A repeating field set needs `group <list> count <len>` of the sequential layout (spec 0.8),")
    A("and `layout` holds for a whole pack. Pack `%s` stays fixed-layout and byte-identical; this" % FORMAT)
    A("pack holds the definitions the sequential layout can state. Both use module `%s`." % MODULE)
    A("The two packs accept disjoint messages: a kind here is generated only when its match")
    A("values conflict with those of every kind of the same PGN in `%s`, so a reader may try" % FORMAT)
    A("either pack first. A fixed-layout PGN is `no-kind` here (vector `e02`).")
    A("")
    A("## Message convention")
    A("")
    A("As pack `%s`: 3 bytes of PGN, little-endian, then the payload after fast-packet" % FORMAT)
    A("reassembly. The lines are read in order from the first bit, least significant bit first")
    A("(`bit_order lsb`). The message ends after the last item; it is as long as CANboat's fields")
    A("make it, trailing reserved bits included.")
    A("")
    A("## What is mapped")
    A("")
    A("| | Count |")
    A("|---|---|")
    A("| kinds | %d |" % len(seq))
    A("| distinct PGNs | %d |" % len({k.pgn for k in seq}))
    A("| lists in module `%s` | %d |" % (MODULE, len(seq_lists)))
    A("| keys added to module `%s` by this pack | %d |" % (MODULE, len(seq_keys)))
    A("| vectors | %d |" % len(vec_names))
    A("")
    A("| Kind | PGN | CANboat id | Description | List (one item per) |")
    A("|---|---|---|---|---|")
    for k in seq:
        A("| `%s` | %d | `%s` | %s%s | `%s.%s` (%s) |" % (k.name, k.pgn, k.id, k.definition.description,
                                                   "" if k.definition.complete else " [CANboat: incomplete]",
                                                   MODULE, k.list, k.count_id))
    A("")
    A("Each kind is:")
    A("")
    A("1. `when 24 <pgn>`, then a `when` for every leading CANboat field with a fixed `Match` value.")
    A("   A reserved field between two match fields is a `when` of all ones: CANboat states that")
    A("   reserved bits shall be 1, and spec 0.8 lets only `when` lines come before a kind's other")
    A("   lines. A message whose reserved bits there are not all ones is `no-kind`.")
    A("2. The fields before the repeating set, in order. A RESERVED field is `const <len> <all ones>`")
    A("   and a SPARE field `pad <len>`, so encode writes what NMEA 2000 requires (pack `%s`" % FORMAT)
    A("   writes zeros there).")
    A("3. `group %s.<list> count <len>`: the CANboat count field is the group's count. It is not a" % MODULE)
    A("   model key; encode writes the number of items.")
    A("")
    A("Field transforms, key naming and `when` ordering follow pack `%s` (its `pack.md`). An item" % FORMAT)
    A("field reuses a key of module `%s` where the key's type, unit, resolution, offset and lookup" % MODULE)
    A("agree; otherwise it gets a new key under the same naming rule. No existing key is renamed or")
    A("retyped. `requires` lists up to five rare top-level keys and the kind's list.")
    A("")
    A("## Core keys")
    A("")
    A("| Kind | Core keys | Evidence |")
    A("|---|---|---|")
    for k in seq:
        ck = [f for f in k.fields if f.core]
        if ck:
            A("| `%s` | %s | the rule and evidence of pack `%s`: CANboat fields `latitude` and `longitude`, unit `deg`, signed, resolution 1e-16; NMEA 2000 states the datum in PGN 129044, which neither pack reads |" % (
                k.name, ", ".join("`%s` `%s`" % (f.key, f.transform) for f in ck), FORMAT))
    A("")
    A("- `hae`: not mapped. PGN 129029 describes its altitude as \"referenced to WGS-84\" and carries")
    A("  a separate geoidal separation; the database does not say the height is above the")
    A("  ellipsoid, so it stays a key of module `%s`." % MODULE)
    A("")
    A("## Not mapped, and what each needs")
    A("")
    A("Every definition with a repeating field set or a variable-length field that has no kind in")
    A("either pack, with the addition to the pack language that would state it. Fast-packet and ISO")
    A("transport reassembly stay outside both packs (layered wires and framing: designed, not built).")
    A("")
    rows = [u for u in unmapped if u[3] in ("repeating", "variable", "pgn-range")
            or (u[3] == "indistinguishable" and any(k.pgn == u[0] for k in seq))]
    need = Counter()
    A("| PGN | CANboat id | Description | Reason | Needs |")
    A("|---|---|---|---|---|")
    for pgn, ident, desc, code, detail in sorted(rows, key=lambda r: (r[0], r[1])):
        n = seq_addition(detail)
        if n is None and code == "indistinguishable" and SEQ_FORMAT in detail:
            n = "fixed-layout and sequential kinds in one pack (a `layout` per kind), so one kind order covers both"
        if n is None:
            raise GenError("no addition named for: %s" % detail)
        need[n] += 1
        A("| %d | `%s` | %s | %s | %s |" % (pgn, ident, desc.replace("|", "/").replace("\n", " "), detail, n))
    A("")
    A("By addition:")
    A("")
    A("| Addition | Definitions |")
    A("|---|---|")
    for n, c in need.most_common():
        A("| %s | %d |" % (n, c))
    A("")
    A("Pack `%s` also lists definitions with no field the pack language can carry, and the" % FORMAT)
    A("limits both packs share (\"not available\" values, lookup names, 64-bit unsigned values).")
    A("")
    A("## Vectors")
    A("")
    A("- `rt-<kind>.json`: a round trip with two items; `rt-<kind>-no-items.json`: the list present")
    A("  and empty. The generator packs the bytes from CANboat's field list, not from `pack.def`,")
    A("  with values inside each field's range that survive scaling exactly, and decodes them with")
    A("  its own codec of the `pack.def` text. `model` holds `@kind`, every key, `<list>.#` and every")
    A("  item value.")
    A("- `x01-pgn129029-to-geojson.json`: GNSS Position Data at 52.5 N, 4.5 E; `expect` written by")
    A("  hand (raw / 10^16, exact in doubles) and checked against the codec.")
    A("- `e01-pgn129029-count-beyond-the-input.json`: the count states one item more than the input")
    A("  holds: `malformed-wire` (spec 0.8 ruling 14 and Errors).")
    A("- `e02-fixed-layout-pgn-is-no-kind.json`: a PGN 129025 message is `no-kind` here.")
    A("- `s01-pgn129029-time-not-available-roundtrip.json`: the position of `x01` with the time of day")
    A("  at the value the database states for not available: no time key (`@absent`), same bytes back.")
    A("  The 64-bit latitude and longitude of PGN 129029 state no such value, so they carry no `absent`.")
    A("")
    A("Fields carry `absent` as in pack `%s` (its section \"Absent values\"); the option needs" % FORMAT)
    A("engine version 0.9.")
    A("")
    A("Vectors hold lowercase hex text in `input` / `expect`.")
    A("")
    return "\n".join(L)


# ---------------------------------------------------------------- codec (from spec/engine-spec.md)
#
# A bits codec for the part of the pack language this generator writes: a fixed
# layout, `bit_order lsb`, `when` and `field` lines with the transforms of
# CODEC_TRANSFORMS and the option `absent` (spec 0.9). It reads the Pack that gtcheck
# loaded, never the pack text.

CodecField = namedtuple("CodecField", "key start len t factor offset absent")   # absent: (raw ints)
CodecKind = namedtuple("CodecKind", "name whens fields requires")   # whens: [(start, len, value)]


def absent_of(node):
    """The sentinels of a loaded `field` line as raw integers, () without `absent`."""
    return tuple(int(v) for v in node.absent.split(",")) if node.absent else ()


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
                fields.append(CodecField(node.key, node.start, node.bits, node.tr, factor, offset, absent_of(node)))
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
    ent = OrderedDict()
    for f in k.fields:
        raw = get_bits(data, f.start, f.len)
        if raw not in f.absent:            # spec 0.9: a sentinel leaves the key absent
            ent[f.key] = decode_field(f, raw)
    return k, ent


def encode(k, ent):
    """The message of kind `k` for an entity: its fields (the first sentinel for an absent
    key of a field with `absent`), then its `when` values over them; a bit no line covers
    is 0; the length is kind_bits rounded up to a byte."""
    acc = 0
    for f in k.fields:
        if f.key in ent:
            acc |= encode_field(f, ent[f.key]) << f.start
        elif f.absent:                     # spec 0.9: an absent key writes the first sentinel
            acc |= f.absent[0] << f.start
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
    """The raw wire integer of one field, never one of its sentinels (a sentinel decodes to
    an absent key). `salt` 0 is the first choice; another salt gives another value of the
    same field, as repeatable as the first."""
    for extra in range(256):
        v = _pick_raw(k, f, salt + 1000 * extra if extra else salt)
        if v not in getattr(f, "absent", ()):
            return v
    raise GenError("%s: every value picked for %s in %s is a sentinel" % (f.src.where, f.id, k.name))


def _pick_raw(k, f, salt=0):
    """The value _pick_value starts from; see there."""
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


# Vectors that pin spec 0.9 sentinels. Raw values by CANboat field id; a text value names the
# member of the field that states the raw value ("UnknownValue", "OutOfRangeValue"); every
# other field is 0. `to` is the target; `expect` for geojson is written by hand: with `lat`
# absent the Feature has no geometry (ruling 5 of 0.1.1). For a same-format target `expect`
# is the message packed by hand with `reencode` in place of the input values (ruling 7 of
# 0.9: a sentinel other than the first re-encodes as the first).
SENTINEL_VECTORS = [
    ("s01-pgn129025-latitude-not-available-roundtrip", "positionRapidUpdate",
     {"latitude": "UnknownValue", "longitude": 45000000}, FORMAT, None, ["lat"]),
    ("s02-pgn129025-latitude-out-of-range-reencodes-as-not-available", "positionRapidUpdate",
     {"latitude": "OutOfRangeValue", "longitude": 45000000}, FORMAT, {"latitude": "UnknownValue"}, ["lat"]),
    ("s03-pgn129025-latitude-not-available-to-geojson", "positionRapidUpdate",
     {"latitude": "UnknownValue", "longitude": 45000000}, "geojson",
     '{"type":"Feature","geometry":null,"properties":{}}', ["lat"]),
]

# A missing key encodes as its sentinel. The vector belongs to the pack that owns its input,
# packs/geojson: a Feature with no geometry and a speed, converted to nmea2000 with the
# `requires` keys of the AIS Class A position report as context. Latitude and longitude are
# absent, so the message carries their UnknownValue.
GEOJSON_VECTOR = "packs/geojson/vectors/gen-to-nmea2000-position-not-given.json"
GEOJSON_VECTOR_INPUT = '{"type":"Feature","geometry":null,"properties":{"speed_ms":6.5}}'
GEOJSON_VECTOR_KIND = "aisClassAPositionReport"


def _stated(f, spec, name):
    """A raw value of a vector spec: an integer, or the member of the field that states it."""
    if isinstance(spec, int):
        return spec & ((1 << f.len) - 1)
    if spec not in f.src.stated:
        raise GenError("vector %s: field %s states no %s" % (name, f.id, spec))
    return f.src.stated[spec]


def sentinel_vector(spec, by_id, codec):
    """One entry of SENTINEL_VECTORS as a vector, checked against the codec."""
    name, ident, rawvals, to, expect, absent = spec
    k = by_id.get(ident)
    if k is None:
        raise GenError("sentinel vector %s: definition %s has no kind" % (name, ident))
    fid = {f.id: f for f in k.fields}
    for i in rawvals:
        if i not in fid:
            raise GenError("sentinel vector %s: no field %s" % (name, i))
    data = pack_message(k, {fid[i]: _stated(fid[i], v, name) for i, v in rawvals.items()})
    sel, ent = decode(codec, data)
    if sel.name != k.name or any(key in ent for key in absent):
        raise GenError("sentinel vector %s: decodes as %s with %s" % (name, sel.name, sorted(ent)))
    model = OrderedDict([("@kind", k.name)])
    for key, x in ent.items():
        model[key] = model_text(x)
    model["@absent"] = list(absent)
    if to == FORMAT:
        vals = dict(rawvals)
        vals.update(expect or {})
        want = pack_message(k, {fid[i]: _stated(fid[i], v, name) for i, v in vals.items()})
        if encode(sel, ent) != want:
            raise GenError("sentinel vector %s: the codec writes %s, packed by hand %s" % (name, encode(sel, ent).hex(), want.hex()))
        return _vector(name, FORMAT, data, want.hex(), model)
    got = geojson_text(ent)
    if got != expect:
        raise GenError("sentinel vector %s: hand-written expect differs from the codec\n  hand:  %s\n  codec: %s" % (name, expect, got))
    return _vector(name, to, data, expect, model)


def select_kind(codec, ent):
    """The kind encode takes for an entity from another format: the first whose `requires`
    keys the entity holds (spec 0.5, Encode)."""
    k = next((ck for ck in codec if all(r in ent for r in ck.requires)), None)
    if k is None:
        raise GenError("no-kind")
    return k


def geojson_vector(kinds, codec):
    """The vector of GEOJSON_VECTOR: from the GeoJSON input, with context, to nmea2000."""
    by_id = {k.id: k for k in kinds}
    k = by_id.get(GEOJSON_VECTOR_KIND)
    if k is None:
        raise GenError("%s: definition %s has no kind" % (GEOJSON_VECTOR, GEOJSON_VECTOR_KIND))
    ck = next(c for c in codec if c.name == k.name)
    fields = {f.key: f for f in k.fields}
    context = OrderedDict()
    for key in ck.requires:
        f = fields[key]
        x = decode_field(next(cf for cf in ck.fields if cf.key == key), _pick_value(k, f))
        context[key] = model_text(x)
    ent = {"speed_ms": 6.5}
    ent.update((key, int(v) if fields[key].type == "int" else float(v)) for key, v in context.items())
    sel = select_kind(codec, ent)
    if sel.name != k.name:
        raise GenError("%s: the context selects kind %s, not %s" % (GEOJSON_VECTOR, sel.name, k.name))
    data = encode(sel, ent)
    for f in k.fields:
        if f.key in ("lat", "lon") and (not f.absent or get_bits(data, f.pos, f.len) != f.absent[0]):
            raise GenError("%s: %s is not written as its sentinel" % (GEOJSON_VECTOR, f.key))
    return OrderedDict([("name", "gen-to-nmea2000-position-not-given"), ("from", "geojson"), ("to", FORMAT),
                        ("input", GEOJSON_VECTOR_INPUT), ("context", context), ("expect", data.hex()),
                        ("source", "generated by tools/gen/canboat2pack.py from %s" % DB_PATH),
                        ("reference", "a Feature with no geometry: the AIS Class A position report it encodes to "
                                      "carries the UnknownValue of latitude and longitude (spec 0.9, Encode)")])


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
    for spec in SENTINEL_VECTORS:
        files.append(("%s.json" % spec[0], sentinel_vector(spec, by_id, codec)))
    return [(fn, json.dumps(vec, indent=2) + "\n") for fn, vec in files], xnames


# ---------------------------------------------------------------- sequential codec (spec 0.8)
#
# The part of `layout sequential` the second pack uses: `when`, `field`, `const`, `pad` and
# `group <list> count <len>` with no nesting, bit order lsb (bit i of the message is bit
# i mod 8 of byte i div 8; a field's first bit is its least significant). It reads the Pack
# that gtcheck loaded, never the pack text.

SeqCodecKind = namedtuple("SeqCodecKind", "name whens lines requires")   # whens: [(bits, value)]


def seq_codec_kinds(pack):
    """The kinds of a gtcheck Pack as the sequential codec reads them."""
    def refuse(what, line=None):
        raise GenError("the sequential codec of %s does not read %s" % (NAME, what), pack.label, line)

    if pack.wire != "bits" or not pack.sequential or pack.bit_order != "lsb":
        refuse("a pack that is not `wire bits`, `layout sequential`, `bit_order lsb`")
    if pack.common or not pack.kinds:
        refuse("common lines, or a pack with no kind")

    def lines_of(nodes, in_group):
        out = []
        for node in nodes:
            if node.d == "field":
                if node.tr not in CODEC_TRANSFORMS or node.opts or node.via or node.also:
                    refuse("this field (transform `%s`, or an option)" % node.tr, node.line)
                factor = parse_factor(node.targs[0]) if node.targs else None
                offset = float(node.targs[1]) if len(node.targs) > 1 else 0.0
                out.append(("field", CodecField(node.key, None, node.bits, node.tr, factor, offset, absent_of(node))))
            elif node.d == "const":
                out.append(("const", node.bits, int(node.value)))
            elif node.d == "pad":
                out.append(("pad", node.bits))
            elif node.d == "group" and not in_group and node.mode == "count" and not node.kinds:
                out.append(("group", node.key, node.count, lines_of(node.body, True)))
            else:
                refuse("a `%s` line" % node.d, node.line)
        return out
    kinds = []
    for kind in pack.kinds:
        whens = [(n.bits, int(n.value)) for n in kind.lines if n.d == "when"]
        kinds.append(SeqCodecKind(kind.name, whens, lines_of([n for n in kind.lines if n.d != "when"], False),
                                  list(kind.requires)))
    return kinds


class _Bits:
    """Reads a message from its first bit, least significant bit first."""

    def __init__(self, data):
        self.v, self.n, self.pos = int.from_bytes(data, "little"), len(data) * 8, 0

    def take(self, n):
        if self.pos + n > self.n:
            raise GenError("malformed-wire")
        x = (self.v >> self.pos) & ((1 << n) - 1)
        self.pos += n
        return x


def seq_decode(kinds, data):
    """-> (the first kind whose `when` lines hold, {key: value or [item dict]}). A `when`
    beyond the input does not hold (ruling 21 of 0.5); a line or an item beyond it, and a
    count larger than the bits left (ruling 14 of 0.8), are `malformed-wire`."""
    for k in kinds:
        r = _Bits(data)
        if all(r.pos + n <= r.n and r.take(n) == v for n, v in k.whens):
            break
    else:
        raise GenError("no-kind")

    def run(lines, ent):
        for x in lines:
            if x[0] == "field":
                raw = r.take(x[1].len)
                if raw not in x[1].absent:
                    ent[x[1].key] = decode_field(x[1], raw)
            elif x[0] in ("const", "pad"):
                r.take(x[1])
            else:
                cnt = r.take(x[2])
                if cnt > r.n - r.pos:
                    raise GenError("malformed-wire")
                items = []
                for _ in range(cnt):
                    items.append(OrderedDict())
                    run(x[3], items[-1])
                ent[x[1]] = items
    ent = OrderedDict()
    run(k.lines, ent)
    return k, ent


def seq_encode(k, ent):
    """The message of kind `k`: its `when` values, then its lines; an absent key writes its
    first sentinel, or zero bits without one; a group writes its count then its items; ends
    at a whole byte."""
    acc, pos = 0, 0

    def put(n, v):
        nonlocal acc, pos
        acc |= (v & ((1 << n) - 1)) << pos
        pos += n

    def run(lines, e):
        for x in lines:
            if x[0] == "field":
                f = x[1]
                put(f.len, encode_field(f, e[f.key]) if f.key in e else (f.absent[0] if f.absent else 0))
            elif x[0] == "const":
                put(x[1], x[2])
            elif x[0] == "pad":
                put(x[1], 0)
            else:
                items = e.get(x[1], [])
                if len(items) >= 1 << x[2]:
                    raise GenError("transform-encode: count")
                put(x[2], len(items))
                for it in items:
                    run(x[3], it)
    for n, v in k.whens:
        put(n, v)
    run(k.lines, ent)
    return acc.to_bytes((pos + 7) // 8, "little")


def seq_model(ent):
    """The vector `model` of an entity: keys, `<list>.#` and `<list>[i].<key>`."""
    out = OrderedDict()
    for key, x in ent.items():
        if isinstance(x, list):
            out["%s.#" % key] = str(len(x))
            for i, it in enumerate(x):
                for ik, iv in it.items():
                    out["%s[%d].%s" % (key, i, ik)] = model_text(iv)
        else:
            out[key] = model_text(x)
    return out


# ---------------------------------------------------------------- sequential vectors

def seq_message(k, top, items):
    """Bytes of a message of SeqKind k from raw wire integers by Field, packed from the
    CANboat field list and not from the pack: the `when` values, the top-level lines, the
    count, then each item's lines."""
    acc, pos = 0, 0

    def put(n, v):
        nonlocal acc, pos
        acc |= (v & ((1 << n) - 1)) << pos
        pos += n
    for _, l, v, _ in k.whens:
        put(l, v)

    def run(lines, vals):
        for x in lines:
            if x[0] == "field":
                put(x[1].len, vals.get(x[1], 0))
            elif x[0] == "const":
                put(x[1], x[2])
            else:
                put(x[1], 0)
    run(k.lines, top)
    put(k.count_len, len(items))
    for it in items:
        run(k.items, it)
    return acc.to_bytes((pos + 7) // 8, "little")


class _Named:
    """What pick_values needs of a kind: a name (the seed of the values) and fields."""

    def __init__(self, name, fields):
        self.name, self.fields, self.whens = name, fields, []


# GNSS position in PGN 129029 at 1e-16 degree: 52.5 N, 4.5 E. `expect` written by hand:
# lat = 525000000000000000 / 10^16 = 52.5 and lon = 45000000000000000 / 10^16 = 4.5, exact in
# doubles; no hae (the altitude is not stated to be above the ellipsoid); n2k keys do not cross.
SEQ_CROSS = [
    ("x01-pgn129029-to-geojson", "gnssPositionData",
     {"sid": 3, "latitude": 525000000000000000, "longitude": 45000000000000000, "altitude": 12500000},
     [{"referenceStationType": 0, "referenceStationId": 42, "ageOfDgnssCorrections": 150}],
     '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,52.5]},"properties":{}}'),
]

# A message of PGN 129025 (Position, Rapid Update, fixed layout): no kind of the second pack.
FIXED_LAYOUT_MESSAGE = (129025).to_bytes(3, "little") + bytes.fromhex("5047f41f40a9ae02")


def _seq_vector(name, data, **rest):
    v = OrderedDict([("name", name), ("from", SEQ_FORMAT), ("to", rest.pop("to", SEQ_FORMAT)),
                     ("input", data.hex())])
    v.update(rest)
    return v


def _expect_error(codec, data, kind):
    try:
        seq_decode(codec, data)
    except GenError as e:
        if str(e) != kind:
            raise
        return
    raise GenError("an error vector of %s decodes" % SEQ_FORMAT)


def build_seq_vectors(seq, codec):
    """-> [(file name, text)]: per kind a round trip with two items and one with none; the
    position of PGN 129029 to geojson; a count beyond the input; a fixed-layout PGN."""
    by_name = {ck.name: ck for ck in codec}
    files = []
    for k in seq:
        top = pick_values(_Named(k.name, k.fields))
        items = [pick_values(_Named("%s[%d]" % (k.name, i), k.item_fields)) for i in range(2)]
        for suffix, its in (("", items), ("-no-items", [])):
            data = seq_message(k, top, its)
            sel, ent = seq_decode(codec, data)
            if sel.name != k.name:
                raise GenError("vector for %s decodes as %s" % (k.name, sel.name))
            if seq_encode(by_name[k.name], ent) != data:
                raise GenError("vector for %s does not round-trip" % k.name)
            model = OrderedDict([("@kind", k.name)])
            model.update(seq_model(ent))
            files.append(("rt-%s%s.json" % (k.name, suffix),
                          _seq_vector("%s%s-roundtrip" % (k.name, suffix), data, expect=data.hex(), model=model)))
    by_id = {k.id: k for k in seq}
    for name, ident, topraw, itemraw, expect in SEQ_CROSS:
        k = by_id.get(ident)
        if k is None:
            raise GenError("cross-format vector %s: definition %s has no kind of %s" % (name, ident, SEQ_FORMAT))
        tf = {f.id: f for f in k.fields}
        itf = {f.id: f for f in k.item_fields}
        try:
            top = {tf[i]: v & ((1 << tf[i].len) - 1) for i, v in topraw.items()}
            items = [{itf[i]: v & ((1 << itf[i].len) - 1) for i, v in it.items()} for it in itemraw]
        except KeyError as e:
            raise GenError("cross-format vector %s: no field %s" % (name, e.args[0]))
        data = seq_message(k, top, items)
        sel, ent = seq_decode(codec, data)
        got = geojson_text(ent)
        if sel.name != k.name or got != expect:
            raise GenError("cross-format vector %s: hand-written expect differs from the codec\n  hand:  %s\n  codec: %s"
                           % (name, expect, got))
        model = OrderedDict([("@kind", k.name)] + [(key, model_text(ent[key])) for key in ("lat", "lon")])
        files.append(("%s.json" % name, _seq_vector(name, data, to="geojson", expect=expect, model=model)))
        # the count states one item more than the input holds (ruling 14 of 0.8)
        bits = sum(l for _, l, _, _ in k.whens) + sum(x[1].len if x[0] == "field" else x[1] for x in k.lines)
        if bits % 8:
            raise GenError("cross-format vector %s: the count does not start at a byte" % name)
        bad = bytearray(data)
        bad[bits // 8] += 1
        _expect_error(codec, bytes(bad), "malformed-wire")
        files.append(("e01-%s-count-beyond-the-input.json" % k.name,
                      _seq_vector("%s-count-beyond-the-input" % k.name, bytes(bad), expect_error="malformed-wire")))
        # the time of day at the value the database states for "not available" (spec 0.9); the
        # 64-bit latitude and longitude of the PGN state none
        top = dict(top)
        tf = tf.get("time")
        if tf is None:
            raise GenError("cross-format vector %s: no field time" % name)
        top[tf] = _stated(tf, "UnknownValue", name)
        data = seq_message(k, top, items)
        sel, ent = seq_decode(codec, data)
        if tf.key in ent or seq_encode(sel, ent) != data:
            raise GenError("sentinel vector of %s: time" % k.name)
        model = OrderedDict([("@kind", k.name)])
        model.update(seq_model(ent))
        model["@absent"] = [tf.key]
        files.append(("s01-%s-time-not-available-roundtrip.json" % k.name,
                      _seq_vector("%s-time-not-available-roundtrip" % k.name, data, expect=data.hex(), model=model)))
    _expect_error(codec, FIXED_LAYOUT_MESSAGE, "no-kind")
    files.append(("e02-fixed-layout-pgn-is-no-kind.json",
                  _seq_vector("fixed-layout-pgn-is-no-kind", FIXED_LAYOUT_MESSAGE, expect_error="no-kind")))
    return [(fn, json.dumps(vec, indent=2) + "\n") for fn, vec in files]


def check_seq_vectors(codec, kinds, vectors):
    """Every vector of the second pack ([(file name, parsed JSON)]) decodes to its model
    and encodes back, or fails with its error; every kind has a round trip; the counted
    part of each kind matches the CANboat field list."""
    by_name = {ck.name: ck for ck in codec}
    src = {k.name: k for k in kinds}
    for ck in codec:
        d = src[ck.name].definition
        bits = sum(n for n, _ in ck.whens) + sum(x[1].len if x[0] == "field" else (x[2] if x[0] == "group" else x[1])
                                                  for x in ck.lines)
        want = PGN_BITS + sum(f.bit_length for f in d.fields[:d.repeat[1] - 1])
        if bits != want:
            raise GenError("kind %s: %d bits before the items, CANboat states %d" % (ck.name, bits, want))
    names, seen = set(), set()
    for fn, v in vectors:
        if v["name"] in names:
            raise GenError("duplicate vector name %s" % v["name"])
        names.add(v["name"])
        data = bytes.fromhex(v["input"])
        if "expect_error" in v:
            _expect_error(codec, data, v["expect_error"])
            continue
        sel, ent = seq_decode(codec, data)
        if sel.name != v["model"]["@kind"]:
            raise GenError("vector %s: kind" % fn)
        got = seq_model(ent)
        for key, want in v["model"].items():
            if key == "@kind":
                continue
            if key == "@absent":
                if any(k in ent for k in want):
                    raise GenError("vector %s: a key of @absent is present" % fn)
                continue
            if key not in got:
                raise GenError("vector %s: %s missing" % (fn, key))
            if got[key] != want and not (re.search(r"\d", want) and abs(float(got[key]) - float(want)) <= 1e-9):
                raise GenError("vector %s: %s" % (fn, key))
        if v["to"] == SEQ_FORMAT:
            seen.add(sel.name)
            if seq_encode(by_name[sel.name], ent).hex() != v["expect"] or v["expect"] != v["input"]:
                raise GenError("vector %s: round trip" % fn)
        elif v["to"] == "geojson":
            if geojson_text(ent) != v["expect"]:
                raise GenError("vector %s: geojson" % fn)
        else:
            raise GenError("vector %s: target" % fn)
    missing = set(by_name) - seen
    if missing:
        raise GenError("kinds of %s without a round-trip vector: %s" % (SEQ_FORMAT, sorted(missing)[:5]))


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


def seq_keys_used(seq_codec):
    """The module keys and lists the kinds of the second pack map."""
    used = set()

    def walk_lines(lines):
        for x in lines:
            if x[0] == "field":
                used.add(x[1].key)
            elif x[0] == "group":
                used.add(x[1])
                walk_lines(x[3])
    for ck in seq_codec:
        walk_lines(ck.lines)
    return used


def check_module_keys_used(module, codec, seq_codec=()):
    """Every key and list the module declares is mapped by a kind of either pack."""
    used = {f.key for ck in codec for f in ck.fields} | seq_keys_used(seq_codec)
    lists = getattr(module, "lists", {})
    unused_lists = {"%s.%s" % (MODULE, n) for n in lists} - used
    if unused_lists:
        raise GenError("module lists no kind maps: %s" % sorted(unused_lists)[:5])
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
        if key == "@absent":
            if any(k in ent for k in want):
                raise GenError("vector %s: a key of @absent is present" % fn)
            continue
        got = ent[key]
        if isinstance(got, float):
            if abs(got - float(want)) > 1e-9:
                raise GenError("vector %s: %s" % (fn, key))
        elif model_text(got) != want:
            raise GenError("vector %s: %s" % (fn, key))
    if v["to"] == FORMAT:
        if encode(by_name[sel.name], ent).hex() != v["expect"]:
            raise GenError("vector %s: round trip" % fn)
        if v["expect"] != v["input"] and "@absent" not in v["model"]:
            raise GenError("vector %s: a round trip whose input is not its expect" % fn)
    elif v["to"] == "geojson":
        if geojson_text(ent) != v["expect"]:
            raise GenError("vector %s: geojson" % fn)
        json.loads(v["expect"])
    else:
        raise GenError("vector %s: target" % fn)
    return sel.name


def geojson_entity(text):
    """The core keys a GeoJSON Feature holds as the geojson pack decodes them: a Point's
    coordinates and the numeric `properties` members of GEOJSON_PROPS."""
    obj = json.loads(text)
    ent = {}
    geom = obj.get("geometry")
    if geom:
        for key, x in zip(("lon", "lat", "hae"), geom["coordinates"]):
            ent[key] = float(x)
    for key, x in (obj.get("properties") or {}).items():
        if key in GEOJSON_PROPS and isinstance(x, (int, float)) and not isinstance(x, bool):
            ent[key] = int(x) if CORE_KEYS[key] == "int" else float(x)
    return ent


def check_geojson_vector(codec, module, v):
    """The vector of GEOJSON_VECTOR: decode its input, add its context, select the kind by
    `requires`, encode; the result must be its `expect`."""
    ent = geojson_entity(v["input"])
    for key, text in v["context"].items():
        typ = module.keys[key.split(".", 1)[1]]
        ent.setdefault(key, int(text) if typ == "int" else float(text))
    if encode(select_kind(codec, ent), ent).hex() != v["expect"]:
        raise GenError("%s: expect" % GEOJSON_VECTOR)


def check_vectors(codec, vectors):
    """Check every vector ([(file name, parsed JSON)]): names are unique, each passes
    check_vector, and every kind has a same-format round trip."""
    names, seen_kinds = set(), set()
    for fn, v in vectors:
        if v["name"] in names:
            raise GenError("duplicate vector name %s" % v["name"])
        names.add(v["name"])
        kind = check_vector(codec, fn, v)
        if v["to"] == FORMAT and fn.startswith("rt-"):
            seen_kinds.add(kind)
    missing = {ck.name for ck in codec} - seen_kinds
    if missing:
        raise GenError("kinds without a round-trip vector: %s" % sorted(missing)[:5])


def load_seq_output(module_text, pack_text):
    """Load the module and the second pack as an engine does (gtcheck). -> Pack."""
    try:
        model = gtcheck.Model()
        model.add(core_module_text(), "core")
        model.add(module_text, MODULE_DEF)
        return gtcheck.load_pack(pack_text, model, SEQ_PACK_DEF)
    except gtcheck.CheckError as e:
        raise GenError("generated file does not load: %s" % e)


def self_check(files, kinds, seq=()):
    """Check the texts of a run before any is written: `files` maps each output path
    to its text. The module and the packs are loaded from their text and every vector is
    parsed from its text, so what is checked is what is written.
    -> (vector files, module keys, vector files of the second pack)."""
    module, pack = load_output(files[MODULE_DEF], files[PACK_DEF])
    if module.name != MODULE:
        raise GenError("module name")
    codec = codec_kinds(pack)
    if pack.format != FORMAT or len(codec) != len(kinds):
        raise GenError("pack: kind count")
    check_kind_shapes(codec, kinds)
    check_kind_order(codec)
    seq_codec, n_seq = [], 0
    if seq:
        seq_pack = load_seq_output(files[MODULE_DEF], files[SEQ_PACK_DEF])
        seq_codec = seq_codec_kinds(seq_pack)
        if seq_pack.format != SEQ_FORMAT or [ck.name for ck in seq_codec] != [k.name for k in seq]:
            raise GenError("%s: kinds" % SEQ_PACK_DEF)
        prefix = SEQ_VECTORS + "/"
        seq_vectors = sorted((rel[len(prefix):], json.loads(text)) for rel, text in files.items() if rel.startswith(prefix))
        check_seq_vectors(seq_codec, seq, seq_vectors)
        n_seq = len(seq_vectors)
    elif any(rel.startswith("packs/%s/" % SEQ_FORMAT) for rel in files):
        raise GenError("files of %s with no kind" % SEQ_FORMAT)
    check_module_keys_used(module, codec, seq_codec)
    prefix = VECTORS + "/"
    vectors = sorted((rel[len(prefix):], json.loads(text)) for rel, text in files.items() if rel.startswith(prefix))
    check_vectors(codec, vectors)
    check_geojson_vector(codec, module, json.loads(files[GEOJSON_VECTOR]))
    return len(vectors), len(module.keys), n_seq


# ---------------------------------------------------------------- main

def build_outputs(db, sha):
    """Plan and emit. -> (plan, {output path: text} in the order written, cross vector
    names). Nothing is written and nothing is read."""
    plan = make_plan(db)
    files = OrderedDict()
    files[MODULE_DEF] = emit_module(plan.keys, sha, db, plan.seq_keys, plan.seq_lists)
    files[PACK_DEF] = emit_pack(plan.kinds, sha, db)
    codec = codec_kinds(load_output(files[MODULE_DEF], files[PACK_DEF])[1])
    vectors, xnames = build_vectors(plan.kinds, codec)
    for fn, text in vectors:
        files["%s/%s" % (VECTORS, fn)] = text
    files[PACK_MD] = emit_pack_md(plan.kinds, plan.unmapped, plan.keys, db, sha, len(vectors), xnames, plan.seq)
    files[GEOJSON_VECTOR] = json.dumps(geojson_vector(plan.kinds, codec), indent=2) + "\n"
    if plan.seq:
        files[SEQ_PACK_DEF] = emit_seq_pack(plan.seq, sha, db)
        seq_codec = seq_codec_kinds(load_seq_output(files[MODULE_DEF], files[SEQ_PACK_DEF]))
        seq_vectors = build_seq_vectors(plan.seq, seq_codec)
        for fn, text in seq_vectors:
            files["%s/%s" % (SEQ_VECTORS, fn)] = text
        files[SEQ_PACK_MD] = emit_seq_pack_md(plan.seq, plan.unmapped, plan.seq_keys, plan.seq_lists, db, sha,
                                              [fn[:-5] for fn, _ in seq_vectors])
    return plan, files, xnames


def write_outputs(out, files):
    """Write the checked texts and remove every *.json of the vectors directory that
    is not a vector of this run."""
    for vdir in (VECTORS, SEQ_VECTORS):
        for fn in out.listdir(vdir):
            if fn.endswith(".json") and "%s/%s" % (vdir, fn) not in files:
                out.remove("%s/%s" % (vdir, fn))
    for rel, text in files.items():
        out.write(rel, text)


def print_summary(db, sha, plan, xnames, n_files, n_keys, n_seq=0):
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
    print("%s kinds: %d (%d distinct PGNs); new module keys %d, lists %d; vectors %d" % (
        SEQ_FORMAT, len(plan.seq), len({k.pgn for k in plan.seq}), len(plan.seq_keys), len(plan.seq_lists), n_seq))
    print("%s core mappings: %s" % (SEQ_FORMAT, dict(Counter(f.key for k in plan.seq for f in k.fields if f.core))))
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
    n_files, n_keys, n_seq = self_check(files, plan.kinds, plan.seq)
    # Everything is checked: only now does the run touch the output tree.
    if provenance is not None:
        out.write(PROVENANCE, provenance)
    write_outputs(out, files)
    print_summary(db, sha, plan, xnames, n_files, n_keys, n_seq)


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
