#!/usr/bin/env python3
"""canboat2pack: turn the CANboat NMEA 2000 PGN database into a goat-transformers pack.

Reads   sources/canboat.json (docs/canboat.json of canboat/canboat at a pinned commit)
Writes  sources/PROVENANCE.md           (only with --commit)
        model/n2k.def
        packs/nmea2000/pack.def
        packs/nmea2000/pack.md
        packs/nmea2000/vectors/*.json

Python 3 standard library only. Re-runnable: every output is rewritten from the
source, and the vectors directory is emptied of *.json first.

Usage:
  canboat2pack.py --out <dir> [--commit <sha> [--fetch]] [--core-def <path to model/core.def>]

--commit <sha>  records the commit in sources/PROVENANCE.md; with --fetch (or when
                a source file is missing) downloads docs/canboat.json and LICENSE
                from raw.githubusercontent.com at that commit with curl.
Without --commit the commit is read back from sources/PROVENANCE.md.

After writing, the generator re-reads its own output from disk and checks it
(grammar, key declarations, type agreement, duplicate keys, bit ranges, kind
order, and every vector through a small codec written from spec/engine-spec.md).
Any failed check exits non-zero.
"""
import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import zlib
from collections import Counter, OrderedDict, defaultdict
from decimal import Decimal
from fractions import Fraction

FORMAT = "nmea2000"
MODULE = "n2k"
PACK_VERSION = "0.1.0"
MODULE_VERSION = "0.1.0"
REPO = "canboat/canboat"
DB_PATH = "docs/canboat.json"
LICENSE_PATH = "LICENSE"
PGN_BITS = 24

# model/core.def of goat-transformers, version 0.1.0 (checked against --core-def when given)
CORE_KEYS = OrderedDict([
    ("uid", "string"), ("type", "string"), ("time_ms", "int"), ("lat", "float"),
    ("lon", "float"), ("hae", "float"), ("ce", "float"), ("le", "float"),
    ("callsign", "string"), ("course", "float"), ("speed_ms", "float"), ("how", "string"),
])
# packs/geojson/pack.def: member order of the canonical output
GEOJSON_PROPS = ["type", "time_ms", "how", "ce", "le", "callsign", "course", "speed_ms"]

NUMERIC_TYPES = {"NUMBER", "TIME", "DURATION", "DATE", "MMSI", "PGN", "ISO_NAME", "ADDRESS",
                 "LOOKUP", "INDIRECT_LOOKUP", "BITLOOKUP", "FIELD_INDEX",
                 "DYNAMIC_FIELD_KEY", "DYNAMIC_FIELD_LENGTH"}
VARIABLE_TYPES = {"STRING_LAU", "STRING_LZ", "VARIABLE", "DYNAMIC_FIELD_VALUE"}
SKIP_TYPES = {"RESERVED", "SPARE"}

YIELDS = {"uint": "int", "twos": "int", "uscale": "float", "sscale": "float",
          "f32": "float", "f64": "float", "ascii": "string", "linscale": "float"}


class GenError(Exception):
    pass


def die(msg):
    raise GenError(msg)


# ---------------------------------------------------------------- small helpers

def snake(ident):
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
    f = math.floor(abs(q) + 0.5)
    return int(-f if q < 0 else f)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# ---------------------------------------------------------------- sources

def fetch_sources(src_dir, sha, force):
    os.makedirs(src_dir, exist_ok=True)
    got = {}
    for rel, name in ((DB_PATH, "canboat.json"), (LICENSE_PATH, "LICENSE")):
        dest = os.path.join(src_dir, name)
        url = "https://raw.githubusercontent.com/%s/%s/%s" % (REPO, sha, rel)
        if force or not os.path.exists(dest):
            subprocess.run(["curl", "-fsSL", "-o", dest, url], check=True)
        got[name] = (rel, url, dest)
    return got


def write_provenance(src_dir, sha, got, db):
    lic_text = open(got["LICENSE"][2], encoding="utf-8").read()
    lines = [
        "# Provenance of the inputs in this directory",
        "",
        "| Fact | Value |",
        "|---|---|",
        "| repository | https://github.com/%s |" % REPO,
        "| commit: | `%s` |" % sha,
        "| database version stated in the file | CANboat %s, schema %s |" % (db.get("Version"), db.get("SchemaVersion")),
    ]
    for name in ("canboat.json", "LICENSE"):
        rel, url, dest = got[name]
        lines.append("| `%s` | repository path `%s`, %d bytes, sha256 `%s` |" % (name, rel, os.path.getsize(dest), sha256_file(dest)))
        lines.append("| `%s` download URL | %s |" % (name, url))
    lines += [
        "",
        "## What the repository's license file states",
        "",
        "The file `%s` at the repository root at this commit is %d bytes. It holds a copyright line" % (LICENSE_PATH, os.path.getsize(got["LICENSE"][2])),
        "and the Apache License 2.0 notice; it does not hold the full license text. Verbatim:",
        "",
        "```",
        lic_text.rstrip("\n"),
        "```",
        "",
        "## What `canboat.json` states about itself",
        "",
        "- `License`: `%s`" % db.get("License"),
        "- `Comment`: `%s`" % db.get("Comment"),
        "- `Copyright` (verbatim):",
        "",
        "```",
        str(db.get("Copyright", "")).rstrip("\n"),
        "```",
        "",
    ]
    write(os.path.join(src_dir, "PROVENANCE.md"), "\n".join(lines))


def read_commit(src_dir):
    p = os.path.join(src_dir, "PROVENANCE.md")
    if not os.path.exists(p):
        die("no --commit given and %s does not exist" % p)
    m = re.search(r"\| commit: \| `([0-9a-f]{40})` \|", open(p, encoding="utf-8").read())
    if not m:
        die("cannot read the commit from %s" % p)
    return m.group(1)


# ---------------------------------------------------------------- classification

class Field:
    """One mapped wire field of a kind."""
    def __init__(self, cb, transform, typ, unit):
        self.cb = cb
        self.id = cb["Id"]
        self.pos = cb["BitOffset"] + PGN_BITS
        self.len = cb["BitLength"]
        self.transform = transform
        self.type = typ
        self.unit = unit
        self.key = None       # model key as written in the pack
        self.core = False

    @property
    def locator(self):
        return "0:%d:%d" % (self.pos, self.len)

    def signature(self):
        cb = self.cb
        res = cb.get("Resolution", 1) or 1
        return (self.type, self.unit, plain(res), plain(cb.get("Offset", 0)),
                cb.get("LookupEnumeration") or cb.get("LookupBitEnumeration")
                or cb.get("LookupIndirectEnumeration") or cb.get("LookupFieldTypeEnumeration") or "")


class Kind:
    def __init__(self, pgn_def):
        self.d = pgn_def
        self.pgn = pgn_def["PGN"]
        self.id = pgn_def["Id"]
        self.name = None
        self.whens = []        # (pos, len, value, canboat field id or 'PGN')
        self.fields = []
        self.unexpressed = []  # (field id, reason)
        self.requires = []

    def match_set(self):
        return {(p, l): v for p, l, v, _ in self.whens[1:]}


def variable_reason(d):
    """None when the definition is fixed-layout; else (reason code, detail)."""
    if d.get("Fallback"):
        return ("pgn-range", "catch-all definition for a range of PGNs")
    if "RepeatingFieldSet1Size" in d or "RepeatingFieldSet2Size" in d:
        return ("repeating", "repeating field set")
    bad = []
    for f in d["Fields"]:
        ft = f["FieldType"]
        if ft in VARIABLE_TYPES:
            bad.append(ft)
        elif f.get("BitLengthVariable"):
            bad.append("%s of variable size" % ft)
        elif "BitLength" not in f:
            bad.append("%s without a length" % ft)
    if bad:
        return ("variable", ", ".join(sorted(set(bad))))
    if any("BitOffset" not in f for f in d["Fields"]):
        return ("variable", "field position depends on a condition")
    return None


def numeric_transform(f):
    res = f.get("Resolution", 1)
    if res is None:
        res = 1
    off = f.get("Offset", 0) or 0
    signed = bool(f.get("Signed"))
    if off != 0:
        # CANboat "Offset": value = unsigned raw * resolution + offset (J1939 excess-K).
        # The database shows it by RangeMin == Offset (raw 0 is the minimum).
        if f.get("RangeMin") != off:
            die("field %s has Offset %r but RangeMin %r: offset semantics not confirmed" % (f["Id"], off, f.get("RangeMin")))
        return "uscale:%s:%s" % (factor_text(res), plain(off)), "float"
    if res != 1:
        return "%s:%s" % ("sscale" if signed else "uscale", factor_text(res)), "float"
    return ("twos" if signed else "uint"), "int"


def map_field(f):
    """-> ('skip',) | ('when', value) | ('no', reason) | ('field', transform, type, unit)"""
    ft = f["FieldType"]
    if ft in SKIP_TYPES:
        return ("skip",)
    n = f["BitLength"]
    if "Match" in f:
        if not (1 <= n <= 64) or not isinstance(f["Match"], int) or f["Match"] < 0 or f["Match"] >= (1 << n):
            die("Match value of %s does not fit its field" % f["Id"])
        return ("when", f["Match"])
    unit = f.get("Unit") or "-"
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
    die("unhandled CANboat field type %s" % ft)


def build_kind(d):
    k = Kind(d)
    k.whens.append((0, PGN_BITS, d["PGN"], "PGN"))
    for f in d["Fields"]:
        m = map_field(f)
        if m[0] == "skip":
            continue
        if m[0] == "when":
            k.whens.append((f["BitOffset"] + PGN_BITS, f["BitLength"], m[1], f["Id"]))
        elif m[0] == "no":
            k.unexpressed.append((f["Id"], m[1]))
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


def core_mapping(k):
    """Decide the core keys of a kind. Returns {field: (core key, transform)}."""
    out = {}
    lat = [f for f in k.fields if f.cb.get("PhysicalQuantity") == "GEOGRAPHICAL_LATITUDE"]
    lon = [f for f in k.fields if f.cb.get("PhysicalQuantity") == "GEOGRAPHICAL_LONGITUDE"]

    def degrees_ok(f, ident):
        return (f.id == ident and f.cb.get("Unit") == "deg" and f.cb.get("Signed")
                and f.cb.get("Resolution") in (1e-07, 1e-16) and not f.cb.get("Offset"))
    if len(lat) == 1 and len(lon) == 1 and degrees_ok(lat[0], "latitude") and degrees_ok(lon[0], "longitude"):
        out[lat[0]] = ("lat", lat[0].transform)
        out[lon[0]] = ("lon", lon[0].transform)
    sog = [f for f in k.fields if f.id == "sog"]
    if len(sog) == 1 and sog[0].cb.get("Unit") == "m/s" and not sog[0].cb.get("Signed") and sog[0].transform.startswith("uscale:"):
        out[sog[0]] = ("speed_ms", sog[0].transform)
    # course: only a course-over-ground field the database itself states is referenced to
    # true north, in a definition with no reference selector field.
    has_ref = any(f["Id"].lower().endswith("reference") for f in k.d["Fields"])
    cog = [f for f in k.fields if f.id == "cog"]
    if len(cog) == 1 and not has_ref and cog[0].cb.get("Unit") == "rad":
        text = (cog[0].cb.get("Name", "") + " " + cog[0].cb.get("Description", "")).lower()
        if re.search(r"\btrue\b", text):
            factor = cog[0].cb["Resolution"] * 180.0 / math.pi
            out[cog[0]] = ("course", "%s:%s" % ("sscale" if cog[0].cb.get("Signed") else "uscale", plain(factor)))
    # hae: only an altitude the database states is above the WGS84 ellipsoid.
    alt = [f for f in k.fields if f.id == "altitude"]
    if len(alt) == 1 and alt[0].cb.get("Unit") == "m" and "ellipsoid" in alt[0].cb.get("Description", "").lower():
        out[alt[0]] = ("hae", alt[0].transform if ":" in alt[0].transform else "sscale:1")
    return out


def classify(db):
    pgns = db["PGNs"]
    per_pgn = Counter(d["PGN"] for d in pgns if not d.get("Fallback"))
    unmapped = []   # (pgn, id, description, reason code, detail)
    cands = []
    alldefs = defaultdict(list)   # pgn -> [(def, match set or None)]
    for d in pgns:
        vr = variable_reason(d)
        if vr:
            unmapped.append((d["PGN"], d["Id"], d["Description"], vr[0], vr[1]))
            if vr[0] != "pgn-range":
                ms = {}
                known = True
                for f in d["Fields"]:
                    if "Match" in f:
                        if "BitOffset" in f and "BitLength" in f:
                            ms[(f["BitOffset"] + PGN_BITS, f["BitLength"])] = f["Match"]
                        else:
                            known = False
                alldefs[d["PGN"]].append((d["Id"], ms if known else None, False))
            continue
        k = build_kind(d)
        if not k.fields:
            unmapped.append((d["PGN"], d["Id"], d["Description"], "no-field",
                             "fields: " + ", ".join("%s%s" % (f["FieldType"], " (match)" if "Match" in f else "")
                                                    for f in d["Fields"])))
            alldefs[d["PGN"]].append((d["Id"], k.match_set(), False))
            continue
        cands.append(k)
        alldefs[d["PGN"]].append((d["Id"], k.match_set(), True))

    # distinguishability, to a fixed point
    mapped = {k.id: k for k in cands}
    changed = True
    while changed:
        changed = False
        for k in list(mapped.values()):
            a = k.match_set()
            why = None
            for other_id, b, _ in alldefs[k.pgn]:
                if other_id == k.id:
                    continue
                other_mapped = other_id in mapped
                if b is None:
                    why = "definition %s of the same PGN has a match field at a variable position" % other_id
                    break
                r = relation(a, b)
                if r == "equal":
                    why = "same match values as definition %s" % other_id
                elif r == "incomparable":
                    why = "a message can satisfy its match values and those of definition %s, and neither set contains the other" % other_id
                elif r == "sub" and not other_mapped:
                    why = "its match values also hold for the unmapped, more specific definition %s" % other_id
                if why:
                    break
            if why:
                del mapped[k.id]
                unmapped.append((k.pgn, k.id, k.d["Description"], "indistinguishable", why))
                changed = True
    kinds = [k for k in cands if k.id in mapped]

    # names and order: PGN ascending, more match values first, then source order
    src_order = {d["Id"]: i for i, d in enumerate(pgns)}
    for k in kinds:
        k.name = "pgn%d" % k.pgn if per_pgn[k.pgn] == 1 else "pgn%d_%s" % (k.pgn, snake(k.id))
    kinds.sort(key=lambda k: (k.pgn, -sum(l for _, l, _, _ in k.whens), src_order[k.id]))
    names = Counter(k.name for k in kinds)
    if any(c > 1 for c in names.values()):
        die("duplicate kind name")
    return kinds, unmapped


def assign_keys(kinds):
    """Core keys, then n2k keys: one per field id where every use agrees, PGN-qualified otherwise."""
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
    by_id = defaultdict(list)
    for k, f in raw:
        by_id[snake(f.id)].append((k, f))
    keys = OrderedDict()   # name -> dict(type, unit, meaning parts)

    def declare(name, k, f):
        e = keys.get(name)
        if e is None:
            e = keys[name] = {"type": f.type, "unit": f.unit, "sig": f.signature(),
                              "label": f.cb.get("Name", f.id), "ft": f.cb["FieldType"], "pgns": []}
        elif e["sig"] != f.signature():
            die("key %s declared with two signatures" % name)
        if k.pgn not in e["pgns"]:
            e["pgns"].append(k.pgn)
        f.key = "%s.%s" % (MODULE, name)

    for base in by_id:
        uses = by_id[base]
        if len({f.signature() for _, f in uses}) == 1:
            for k, f in uses:
                declare(base, k, f)
            continue
        by_pgn = defaultdict(list)
        for k, f in uses:
            by_pgn[k.pgn].append((k, f))
        for pgn, pu in by_pgn.items():
            if len({f.signature() for _, f in pu}) == 1:
                for k, f in pu:
                    declare("pgn%d_%s" % (pgn, base), k, f)
            else:
                for k, f in pu:
                    nm = k.name if k.name != "pgn%d" % pgn else "pgn%d" % pgn
                    declare("%s_%s" % (nm, base), k, f)
    # no clash between a bare name and a qualified one is possible unless ids collide
    for name in keys:
        if not re.fullmatch(r"[a-z0-9_]+", name):
            die("bad key name %r" % name)
    # requires: the kind's rarest raw keys (up to 6); core keys only when it has no raw key
    use_count = Counter()
    for k in kinds:
        for f in k.fields:
            use_count[f.key] += 1
    for k in kinds:
        seen = [f.key for f in k.fields]
        if len(set(seen)) != len(seen):
            die("kind %s maps a key twice" % k.name)
        rawk = [f for f in k.fields if not f.core] or k.fields
        order = sorted(range(len(rawk)), key=lambda i: (use_count[rawk[i].key], i))[:6]
        k.requires = [rawk[i].key for i in sorted(order)]
    return keys


# ---------------------------------------------------------------- emit

def q(text):
    text = str(text).replace('"', "'").replace("\n", " ")
    return '"%s"' % text


def unit_token(u):
    return q(u) if re.search(r"\s", u) or u.startswith("#") else u


def emit_module(keys, sha, db):
    out = [
        "# The n2k module: NMEA 2000 field values as the CANboat PGN database describes them,",
        "# in CANboat's units (rad, m/s, K, Pa, ...). Lookup and bit-lookup fields are the wire",
        "# integer. A key is shared by every PGN whose field of that id agrees on type, unit,",
        "# resolution, offset and lookup table; where uses disagree the key carries its PGN.",
        "# GENERATED by tools/gen/canboat2pack.py. Do not edit.",
        "module        %s" % MODULE,
        "version       %s" % MODULE_VERSION,
        "distribution  public",
        "source        " + q("%s %s at commit %s (CANboat %s, Apache License 2.0)" % (REPO, DB_PATH, sha, db.get("Version"))),
    ]
    w = max(len(n) for n in keys)
    for name, e in keys.items():
        pg = e["pgns"]
        where = "PGN " + ", ".join(str(p) for p in pg[:4]) + (" and %d more" % (len(pg) - 4) if len(pg) > 4 else "")
        lookup = e["sig"][4]
        kind = e["ft"] + (" " + lookup if lookup else "")
        out.append("key  %-*s  %-6s  %-8s  %s" % (w, name, e["type"], unit_token(e["unit"]),
                                              q("%s; CANboat %s; %s" % (e["label"], kind, where))))
    return "\n".join(out) + "\n"


def emit_pack(kinds, sha, db):
    out = [
        "# NMEA 2000 parameter groups, from the CANboat PGN database. Public.",
        "# Message = 3 bytes PGN (little-endian), then the reassembled payload.",
        "# Payload bit offsets are CANboat's BitOffset + 24. See pack.md.",
        "# GENERATED by tools/gen/canboat2pack.py. Do not edit.",
        "format        %s" % FORMAT,
        "version       %s" % PACK_VERSION,
        "distribution  public",
        "source        " + q("%s %s at commit %s (CANboat %s, Apache License 2.0)" % (REPO, DB_PATH, sha, db.get("Version"))),
        "source        " + q("https://github.com/%s/blob/%s/%s" % (REPO, sha, DB_PATH)),
        "uses          %s" % MODULE,
        "wire          bits",
        "bit_order     lsb",
        "word_bytes    1",
    ]
    for k in kinds:
        out.append("")
        out.append("# PGN %d %s: %s%s" % (k.pgn, k.id, k.d["Description"].replace("\n", " "),
                                       "" if k.d.get("Complete") else " [CANboat: incomplete]"))
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


def emit_pack_md(kinds, unmapped, keys, db, sha, n_vectors, xnames):
    total = len(db["PGNs"])
    by_reason = defaultdict(list)
    for u in unmapped:
        by_reason[u[3]].append(u)
    core_rows = []
    for k in kinds:
        ck = [f for f in k.fields if f.core]
        if ck:
            core_rows.append("| `%s` | %s | %s |" % (k.name, k.d["Description"],
                             ", ".join("`%s` `%s`" % (f.key, f.transform) for f in ck)))
    partial = [(k, k.unexpressed) for k in kinds if k.unexpressed]
    incomplete = [k for k in kinds if not k.d.get("Complete")]
    req_sets = Counter(tuple(k.requires) for k in kinds)
    shadow = sum(1 for k in kinds if req_sets[tuple(k.requires)] > 1)
    L = []
    A = L.append
    A("# Pack: nmea2000")
    A("")
    A("NMEA 2000 parameter groups (PGNs), generated from the CANboat PGN database")
    A("(`%s` `%s` at commit `%s`, CANboat %s, Apache License 2.0) by" % (REPO, DB_PATH, sha, db.get("Version")))
    A("`tools/gen/canboat2pack.py`. Do not edit `pack.def`, `model/n2k.def` or the vectors by hand;")
    A("change the generator and run it again.")
    A("")
    A("Status: Built. Generated from the database; every engine runs every vector in `vectors/` in")
    A("the conformance suite.")
    A("")
    A("## Message convention")
    A("")
    A("An NMEA 2000 payload travels in CAN frames whose 29-bit identifier carries the PGN, and the")
    A("pack language has no CAN framing. A message of this pack is therefore:")
    A("")
    A("1. 3 bytes: the PGN, little-endian;")
    A("2. the payload: the 8 data bytes of a single-frame PGN, or the payload of a fast-packet PGN")
    A("   after reassembly (sequence and frame counters and the length byte removed).")
    A("")
    A("Priority, source address and destination address are not part of the message. The pack is")
    A("`wire bits`, `bit_order lsb`, `word_bytes 1`; every locator is `0:<bit offset>:<len>` and a")
    A("payload field sits at CANboat's `BitOffset` + 24. Input and output are hex text.")
    A("")
    A("## What is mapped")
    A("")
    A("| | Count |")
    A("|---|---|")
    A("| PGN definitions in the source | %d |" % total)
    A("| kinds in `pack.def` | %d |" % len(kinds))
    A("| distinct PGNs with at least one kind | %d |" % len({k.pgn for k in kinds}))
    for code, title in REASON_TITLES.items():
        A("| not mapped: %s | %d |" % (title[0].lower() + title[1:], len(by_reason.get(code, []))))
    A("| keys in module `%s` | %d |" % (MODULE, len(keys)))
    A("| vectors | %d (%d same-format round trips, %d to `geojson`) |" % (n_vectors, len(kinds), len(xnames)))
    A("")
    A("One kind per fixed-layout PGN definition, named `pgn<number>`, with the CANboat definition id")
    A("appended where the source holds several definitions for that PGN. Each kind has")
    A("`when 0:0:24 <pgn>` and one more `when` per CANboat field with a fixed `Match` value")
    A("(manufacturer code, industry code, function and message codes). Kinds of one PGN are ordered")
    A("with the most matched bits first, so the first kind that holds is the most specific one.")
    A("Two definitions of one PGN are told apart only by these values: a definition whose match")
    A("values also hold for another definition's messages, with no order that separates them, has")
    A("no kind.")
    A("A `Match` field is written by its `when` line and is not a model key.")
    A("")
    A("Field rules:")
    A("")
    A("| CANboat field | Transform | Model type |")
    A("|---|---|---|")
    A("| NUMBER, TIME, DURATION with `Resolution` other than 1 | `uscale:<resolution>` or, when `Signed`, `sscale:<resolution>`; a decimal resolution is written as a fraction in lowest terms (1e-7 is `1/10000000`, 0.002 is `1/500`); a resolution CANboat derived from pi and printed to 13 or more digits stays a decimal | float, CANboat's unit |")
    A("| any numeric field with `Offset` | `uscale:<resolution>:<offset>` (the raw value is unsigned; value = raw x resolution + offset) | float |")
    A("| NUMBER, DATE, MMSI, PGN, ISO_NAME, ADDRESS with resolution 1 | `uint`, or `twos` when `Signed` | int |")
    A("| LOOKUP, INDIRECT_LOOKUP, BITLOOKUP, FIELD_INDEX | `uint` (the wire integer, not the lookup name) | int |")
    A("| FLOAT | `f32` | float |")
    A("| STRING_FIX | `ascii` | string |")
    A("| BINARY of 64 bits or fewer | `uint` | int |")
    A("| RESERVED, SPARE | not mapped | |")
    A("")
    A("Every raw value goes to module `n2k` (`model/n2k.def`). A field id that agrees across all its")
    A("uses on model type, unit, resolution, offset and lookup table is one key (`n2k.sid`,")
    A("`n2k.wind_speed`). Where uses disagree, each PGN gets its own key `n2k.pgn<number>_<id>`, and")
    A("where definitions of one PGN disagree, `n2k.<kind name>_<id>`.")
    A("")
    A("`requires` of a kind lists up to six of its `n2k` keys, those used by the fewest kinds; a kind")
    A("with no `n2k` key lists its core keys. %d kinds share their `requires` list with another kind;" % shadow)
    A("for those, an encode from another format selects the first in pack order.")
    A("")
    A("## Core keys")
    A("")
    A("| Kind | PGN | Core keys |")
    A("|---|---|---|")
    L.extend(core_rows)
    A("")
    A("- `lat` / `lon`: only a definition with exactly one latitude and one longitude field, ids")
    A("  `latitude` and `longitude`, in degrees at resolution 1e-7 or 1e-16. Waypoint, destination,")
    A("  station, corner and delta positions stay in `n2k`. NMEA 2000 states the datum in a separate")
    A("  PGN (129044); the pack does not read it.")
    A("- `speed_ms`: the field `sog` in m/s.")
    A("- `course`: no kind maps it. Every fixed-layout course-over-ground field either sits beside a")
    A("  reference selector (`cogReference`: true or magnetic) or has no stated reference in the")
    A("  database, so it stays `n2k.cog` in radians. The generator maps `course` with the factor")
    A("  resolution x 180/pi when a definition states a true-north reference and has no selector.")
    A("- `hae`: no kind maps it. No fixed-layout altitude field is stated to be above the WGS84")
    A("  ellipsoid (PGN 129029 says \"referenced to WGS-84\" and is not fixed-layout).")
    A("")
    A("## What the pack language cannot express yet")
    A("")
    A("- **\"Not available\" values.** NMEA 2000 marks a missing value with all bits set (and uses")
    A("  the next values down for \"out of range\" and \"reserved\"). There is no way to say so in")
    A("  `pack.def`: an all-ones field decodes as a number (`0xFFFF` at resolution 0.01 is 655.35),")
    A("  and an absent model key encodes as zero bits, not all ones.")
    A("- **Reserved and spare bits.** NMEA 2000 sets them to 1; `encode` writes 0 in every bit no")
    A("  field covers. A real message with reserved bits set does not round-trip byte-identically.")
    A("- **Trailing bytes.** The message ends at the last mapped or `when` bit, rounded up to a")
    A("  byte. A definition that ends in reserved fields encodes shorter than its NMEA 2000 length")
    A("  (PGN 129026 encodes 3 + 6 bytes, not 3 + 8). Decode accepts the full length.")
    A("- **Repeating field sets and variable-length fields** (STRING_LAU, STRING_LZ, VARIABLE,")
    A("  BINARY of variable size, key/length/value fields, fields placed after any of these). These")
    A("  need the future groups addition; the definitions are listed below.")
    A("- **PGN ranges.** A `when` compares for equality, so CANboat's catch-all definitions for a")
    A("  range of PGNs (proprietary ranges) have no kind.")
    A("- **CAN framing**: identifier, priority, addresses, fast-packet and ISO transport reassembly.")
    A("- **Opaque fields over 64 bits and DECIMAL fields.** %d kinds leave such a field unmapped:" % len(partial))
    A("")
    if partial:
        A("| Kind | Field | Reason |")
        A("|---|---|---|")
        for k, un in partial:
            for fid, why in un:
                A("| `%s` | `%s` | %s |" % (k.name, fid, why))
        A("")
    A("- **String padding.** `ascii` strips trailing NUL bytes only and refuses bytes above 0x7E.")
    A("  NMEA 2000 devices also pad fixed strings with 0xFF or `@`; 0xFF padding is a decode error.")
    A("- **Lookup names.** Lookups are carried as integers; the pack language has no value table for")
    A("  a `bits` field.")
    A("- **64-bit unsigned values.** `uint` on a 64-bit field (ISO NAME) with the top bit set")
    A("  decodes to the negative integer with the same bit pattern.")
    A("")
    A("## Kinds from definitions CANboat marks incomplete")
    A("")
    A("%d of the %d kinds come from definitions with `Complete: false` (CANboat states fields, field" % (len(incomplete), len(kinds)))
    A("lengths, resolutions or lookups may be missing or wrong). They carry `[CANboat: incomplete]`")
    A("in the comment above the kind in `pack.def`.")
    A("")
    A("## Vectors")
    A("")
    A("- `rt-<kind>.json`: one same-format round trip per kind. The generator packs the bytes itself")
    A("  from values inside each field's range that survive scaling exactly; unmapped bits are 0 and")
    A("  the message has the encoded length, so the round trip is byte-identical. `model` holds")
    A("  `@kind` and every decoded key.")
    A("- %s: conversions to `geojson`, with the expected text" % ", ".join("`%s.json`" % n for n in xnames))
    A("  written by hand from the canonical GeoJSON rules and checked by the generator against its")
    A("  own codec. PGN 129029 has no vector: it has a repeating field set and no kind.")
    A("")
    A("Vectors hold lowercase hex text in `input` / `expect`.")
    A("")
    A("## Definitions not mapped")
    A("")
    for code, title in REASON_TITLES.items():
        rows = by_reason.get(code, [])
        A("### %s (%d)" % (title, len(rows)))
        A("")
        if code in ("repeating", "variable"):
            A("These need the future groups addition.")
            A("")
        if not rows:
            A("None.")
            A("")
            continue
        A("| PGN | CANboat id | Description | Detail |")
        A("|---|---|---|---|")
        for pgn, ident, desc, _, detail in sorted(rows, key=lambda r: (r[0], r[1])):
            A("| %d | `%s` | %s | %s |" % (pgn, ident, desc.replace("|", "/").replace("\n", " "), detail))
        A("")
    return "\n".join(L)


# ---------------------------------------------------------------- codec (from spec/engine-spec.md)

def tokenize(line):
    toks, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                die("unterminated quote: %s" % line)
            toks.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and line[j] not in " \t":
                j += 1
            toks.append(line[i:j])
            i = j
    return toks


def parse_module(text):
    mod = {"keys": OrderedDict(), "sources": 0}
    for ln in text.split("\n"):
        t = tokenize(ln)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in ("module", "version", "distribution"):
            if len(a) != 1:
                die("module: bad %s line" % d)
            mod[d] = a[0]
        elif d == "source":
            if len(a) != 1:
                die("module: bad source line")
            mod["sources"] += 1
        elif d == "key":
            if len(a) not in (3, 4):
                die("module: key line with %d arguments: %s" % (len(a), ln))
            name, typ = a[0], a[1]
            if "." in name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
                die("module: bad key name %s" % name)
            if typ not in ("string", "float", "int"):
                die("module: bad key type %s" % typ)
            if name in mod["keys"]:
                die("duplicate-key: %s" % name)
            mod["keys"][name] = typ
        else:
            die("module: unknown directive %s" % d)
    if mod.get("distribution") not in ("public", "controlled"):
        die("missing-distribution: module")
    if not mod["sources"]:
        die("missing-source: module")
    return mod


LOC_RE = re.compile(r"(\d+):(\d+):(\d+)$")
NUM_RE = r"-?\d+(?:\.\d+)?"
TRANSFORM_RE = re.compile(r"(uint|twos|f32|f64|ascii)$|(uscale|sscale):(%s|[1-9]\d*/[1-9]\d*)(?::(%s))?$" % (NUM_RE, NUM_RE))


def parse_locator(loc, word_bytes):
    m = LOC_RE.match(loc)
    if not m:
        die("bad locator %s" % loc)
    word, pos, ln = (int(x) for x in m.groups())
    return word * word_bytes * 8 + pos, ln


def parse_pack(text, modules):
    """Parse and load-check pack.def against the modules (engine-spec 0.4 and 0.5 checks)."""
    pack = {"uses": ["core"], "sources": 0, "kinds": [], "common_fields": [], "common_whens": [],
            "bit_order": "lsb", "word_bytes": None}
    cur = None
    raw = []
    for ln in text.split("\n"):
        t = tokenize(ln)
        if not t:
            continue
        d, a = t[0], t[1:]
        if d in ("format", "version", "distribution", "wire", "word_bytes", "bit_order", "uses"):
            if len(a) != 1:
                die("pack: bad %s line" % d)
            if d == "uses":
                pack["uses"].append(a[0])
            elif d == "word_bytes":
                pack[d] = int(a[0])
            else:
                pack[d] = a[0]
        elif d == "source":
            if len(a) != 1:
                die("pack: bad source line")
            pack["sources"] += 1
        elif d == "kind":
            if len(a) != 1 or not re.fullmatch(r"[A-Za-z0-9_\-]+", a[0]):
                die("pack: bad kind line %s" % ln)
            if any(k["name"] == a[0] for k in pack["kinds"]):
                die("duplicate-kind: %s" % a[0])
            cur = {"name": a[0], "whens": [], "requires": [], "fields": []}
            pack["kinds"].append(cur)
        elif d == "when":
            if len(a) != 2:
                die("pack: bad when line %s" % ln)
            raw.append(("when", cur, a))
        elif d == "requires":
            if cur is None or not a:
                die("bad-directive: requires")
            cur["requires"].extend(a)
        elif d == "field":
            if len(a) != 3:
                die("pack: bad field line %s" % ln)
            raw.append(("field", cur, a))
        else:
            die("pack: unknown directive %s" % d)
    if pack.get("distribution") not in ("public", "controlled"):
        die("missing-distribution: pack")
    if not pack["sources"]:
        die("missing-source: pack")
    if pack.get("wire") != "bits" or pack["bit_order"] != "lsb" or not pack["word_bytes"]:
        die("pack: this checker handles wire bits, bit_order lsb")
    for m in pack["uses"]:
        if m not in modules:
            die("unknown-module: %s" % m)
        if pack["distribution"] == "public" and modules[m]["distribution"] != "public":
            die("distribution-violation: %s" % m)

    def key_type(key):
        modname, name = key.split(".", 1) if "." in key else ("core", key)
        if modname not in pack["uses"]:
            die("module-not-used: %s" % key)
        if name not in modules[modname]["keys"]:
            die("undeclared-key: %s" % key)
        return modules[modname]["keys"][name]

    for what, kind, a in raw:
        if what == "when":
            start, ln = parse_locator(a[0], pack["word_bytes"])
            if not 1 <= ln <= 64 or not re.fullmatch(r"\d+", a[1]) or int(a[1]) >= (1 << ln):
                die("pack: bad when %s %s" % (a[0], a[1]))
            (kind["whens"] if kind else pack["common_whens"]).append((start, ln, int(a[1])))
        else:
            key, loc, tr = a
            start, ln = parse_locator(loc, pack["word_bytes"])
            m = TRANSFORM_RE.match(tr)
            if not m:
                die("unknown transform %s" % tr)
            name = m.group(1) or m.group(2)
            if name == "ascii":
                if ln % 8 or not 8 <= ln <= 2040:
                    die("bad-directive: ascii length %d" % ln)
            elif not 1 <= ln <= 64:
                die("pack: field length %d" % ln)
            if (name == "f32" and ln != 32) or (name == "f64" and ln != 64):
                die("bad-directive: %s length %d" % (name, ln))
            factor = parse_factor(m.group(3)) if m.group(3) else None
            if factor is not None and factor[0] == 0:
                die("pack: zero factor")
            offset = float(m.group(4)) if m.group(4) else 0.0
            if YIELDS[name] != key_type(key):
                die("key-type-mismatch: %s %s" % (key, tr))
            (kind["fields"] if kind else pack["common_fields"]).append(
                {"key": key, "start": start, "len": ln, "t": name, "factor": factor, "offset": offset})
    for k in pack["kinds"]:
        seen = set()
        for f in pack["common_fields"] + k["fields"]:
            if f["key"] in seen:
                die("duplicate-field: %s in kind %s" % (f["key"], k["name"]))
            seen.add(f["key"])
        for r in k["requires"]:
            key_type(r)   # ruling 4: any declared key
    return pack


def get_bits(data, start, ln):
    return (int.from_bytes(data, "little") >> start) & ((1 << ln) - 1)


def kind_bits(pack, k):
    ends = [s + l for s, l, _ in pack["common_whens"] + k["whens"]]
    ends += [f["start"] + f["len"] for f in pack["common_fields"] + k["fields"]]
    return max(ends)


def decode(pack, data):
    def holds(w):
        s, l, v = w
        return s + l <= len(data) * 8 and get_bits(data, s, l) == v
    if not all(holds(w) for w in pack["common_whens"]):
        die("no-kind")
    for k in pack["kinds"]:
        if all(holds(w) for w in k["whens"]):
            break
    else:
        die("no-kind")
    if (kind_bits(pack, k) + 7) // 8 > len(data):
        die("malformed-wire")
    ent = OrderedDict()
    for f in pack["common_fields"] + k["fields"]:
        v = get_bits(data, f["start"], f["len"])
        t = f["t"]
        if t == "uint":
            x = v - (1 << 64) if f["len"] == 64 and v >> 63 else v   # ruling 2
        elif t == "twos":
            x = v - (1 << f["len"]) if v >> (f["len"] - 1) else v
        elif t == "uscale":
            x = scale_decode(v, f["factor"], f["offset"])
        elif t == "sscale":
            s = v - (1 << f["len"]) if v >> (f["len"] - 1) else v
            x = scale_decode(s, f["factor"], f["offset"])
        elif t == "f32":
            import struct
            x = struct.unpack("<f", v.to_bytes(4, "little"))[0]
        elif t == "ascii":
            b = v.to_bytes(f["len"] // 8, "little").rstrip(b"\x00")
            if any(c > 0x7E or c < 0x20 for c in b):
                die("transform-decode: ascii")
            x = b.decode("ascii")
        else:
            die("codec: transform %s" % t)
        ent[f["key"]] = x
    return k, ent


def encode(pack, k, ent):
    acc = 0
    for f in pack["common_fields"] + k["fields"]:
        if f["key"] not in ent:
            continue
        x, t, ln = ent[f["key"]], f["t"], f["len"]
        if t in ("uint", "twos"):
            v = x & ((1 << ln) - 1)
        elif t in ("uscale", "sscale"):
            r = scale_encode(x, f["factor"], f["offset"])
            lo, hi = (0, (1 << ln) - 1) if t == "uscale" else (-(1 << (ln - 1)), (1 << (ln - 1)) - 1)
            if not lo <= r <= hi:
                die("transform-encode: %s" % f["key"])
            v = r & ((1 << ln) - 1)
        elif t == "f32":
            import struct
            v = int.from_bytes(struct.pack("<f", x), "little")
        elif t == "ascii":
            b = x.encode("ascii")
            if len(b) > ln // 8:
                die("transform-encode: ascii")
            v = int.from_bytes(b.ljust(ln // 8, b"\x00"), "little")
        acc |= v << f["start"]
    for s, l, v in pack["common_whens"] + k["whens"]:
        acc = (acc & ~(((1 << l) - 1) << s)) | (v << s)
    return acc.to_bytes((kind_bits(pack, k) + 7) // 8, "little")


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

def pick_values(k):
    """A raw wire integer for every mapped field: inside the field's range, not a
    'not available' value, and exactly recoverable after scaling."""
    vals = {}
    for f in k.fields:
        h = zlib.crc32(("%s/%s" % (k.name, f.id)).encode())
        n, cb, t = f.len, f.cb, f.transform.split(":")
        name = t[0]
        if name == "ascii":
            nb = n // 8
            text = ("N2K" + "%08X" % h + "TESTVECTOR")[:min(nb, 16)]
            vals[f] = int.from_bytes(text.encode().ljust(nb, b"\x00"), "little")
            continue
        if name == "f32":
            import struct
            vals[f] = int.from_bytes(struct.pack("<f", (h % 4001 - 2000) / 8.0), "little")
            continue
        if name in ("uint", "twos"):
            cap = (1 << 62) - 1
            if name == "uint":
                top = (1 << n) - 1 if n < 2 else (1 << n) - 2
                rmax = cb.get("RangeMax")
                if isinstance(rmax, (int, float)) and 0 <= rmax <= top and rmax == int(rmax):
                    top = int(rmax)
                top = min(top, cap)
                vals[f] = (1 + h % top) if top >= 1 else 0
            else:
                top = (1 << (n - 1)) - 2 if n > 2 else 0
                bot = -top
                if isinstance(cb.get("RangeMax"), (int, float)):
                    top = min(top, int(math.floor(cb["RangeMax"])))
                if isinstance(cb.get("RangeMin"), (int, float)):
                    bot = max(bot, int(math.ceil(cb["RangeMin"])))
                top, bot = min(top, cap), max(bot, -cap)
                s = bot + h % (top - bot + 1) if top >= bot else 0
                vals[f] = s & ((1 << n) - 1)
            continue
        factor = parse_factor(t[1])
        offset = float(t[2]) if len(t) > 2 else 0.0
        signed = name == "sscale"
        # raw range: the field's bits less the top values NMEA 2000 reserves, then CANboat's
        # RangeMin/RangeMax in raw units (CANboat resolution: the raw range does not depend
        # on the unit the pack scales to), then 31 bits so the double arithmetic is exact
        lo, hi = (-(1 << (n - 1)) + 1, (1 << (n - 1)) - 4) if signed else (0, (1 << n) - 4)
        hi = max(hi, 1 if n > 1 else 0)
        lo = min(lo, 0)
        res, off = cb.get("Resolution", 1) or 1, cb.get("Offset", 0) or 0
        if isinstance(cb.get("RangeMax"), (int, float)):
            hi = min(hi, max(int(math.floor((cb["RangeMax"] - off) / res)) - 1, 0))
        if isinstance(cb.get("RangeMin"), (int, float)):
            lo = max(lo, min(int(math.ceil((cb["RangeMin"] - off) / res)) + 1, 0))
        lo, hi = max(lo, -(1 << 31) + 1), min(hi, (1 << 31) - 1)
        s = lo + h % (hi - lo + 1)
        if s == 0 and hi >= 1:
            s = 1
        for _ in range(4096):
            if scale_encode(scale_decode(s, factor, offset), factor, offset) == s:
                break
            s = s - 1 if s > 0 else s + 1
        else:
            die("no exactly representable value for %s in %s" % (f.id, k.name))
        vals[f] = s & ((1 << n) - 1)
    return vals


def pack_message(k, vals):
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


def write_vectors(out_dir, kinds, pack):
    vdir = os.path.join(out_dir, "packs", FORMAT, "vectors")
    os.makedirs(vdir, exist_ok=True)
    for fn in os.listdir(vdir):
        if fn.endswith(".json"):
            os.remove(os.path.join(vdir, fn))
    pk = {k["name"]: k for k in pack["kinds"]}
    count = 0
    for k in kinds:
        data = pack_message(k, pick_values(k))
        sel, ent = decode(pack, data)
        if sel["name"] != k.name:
            die("vector for %s decodes as %s" % (k.name, sel["name"]))
        if encode(pack, pk[k.name], ent) != data:
            die("vector for %s does not round-trip" % k.name)
        model = OrderedDict([("@kind", k.name)])
        for key, x in ent.items():
            model[key] = model_text(x)
        vec = OrderedDict([("name", "%s-roundtrip" % k.name), ("from", FORMAT), ("to", FORMAT),
                           ("input", data.hex()), ("expect", data.hex()), ("model", model)])
        write(os.path.join(vdir, "rt-%s.json" % k.name), json.dumps(vec, indent=2) + "\n")
        count += 1
    by_id = {k.id: k for k in kinds}
    xnames = []
    for name, ident, rawvals, expect in CROSS:
        k = by_id.get(ident)
        if k is None:
            die("cross-format vector %s: definition %s has no kind" % (name, ident))
        fid = {f.id: f for f in k.fields}
        vals = {}
        for i, v in rawvals.items():
            if i not in fid:
                die("cross-format vector %s: no field %s" % (name, i))
            vals[fid[i]] = v & ((1 << fid[i].len) - 1)
        data = pack_message(k, vals)
        sel, ent = decode(pack, data)
        if sel["name"] != k.name:
            die("cross-format vector %s decodes as %s" % (name, sel["name"]))
        got = geojson_text(ent)
        if got != expect:
            die("cross-format vector %s: hand-written expect differs from the codec\n  hand:  %s\n  codec: %s" % (name, expect, got))
        model = OrderedDict([("@kind", k.name)])
        for key in ("lat", "lon", "speed_ms"):
            if key in ent:
                model[key] = model_text(ent[key])
        vec = OrderedDict([("name", name), ("from", FORMAT), ("to", "geojson"),
                           ("input", data.hex()), ("expect", expect), ("model", model)])
        write(os.path.join(vdir, "%s.json" % name), json.dumps(vec, indent=2) + "\n")
        xnames.append(name)
        count += 1
    return count, xnames


# ---------------------------------------------------------------- self-check of the written files

def self_check(out_dir, kinds, core_def):
    core = {"distribution": "public", "keys": CORE_KEYS}
    if core_def:
        real = parse_module(open(core_def, encoding="utf-8").read())
        if dict(real["keys"]) != dict(CORE_KEYS):
            die("the core keys built into the generator differ from %s" % core_def)
    n2k = parse_module(open(os.path.join(out_dir, "model", MODULE + ".def"), encoding="utf-8").read())
    if n2k.get("module") != MODULE:
        die("module name")
    pack = parse_pack(open(os.path.join(out_dir, "packs", FORMAT, "pack.def"), encoding="utf-8").read(),
                      {"core": core, MODULE: n2k})
    if pack.get("format") != FORMAT or len(pack["kinds"]) != len(kinds):
        die("pack: kind count")
    src = {k.name: k for k in kinds}
    used = set()
    last_pgn = {}
    for pos, k in enumerate(pack["kinds"]):
        d = src[k["name"]].d
        if not k["whens"] or k["whens"][0] != (0, PGN_BITS, d["PGN"]):
            die("kind %s: first when is not its PGN" % k["name"])
        # bit ranges inside the message, and no two lines of a kind on the same bit
        limit = PGN_BITS + (d["Length"] * 8 if d.get("Length") else sum(f["BitLength"] for f in d["Fields"]))
        spans = sorted([(s, s + l) for s, l, _ in k["whens"]] + [(f["start"], f["start"] + f["len"]) for f in k["fields"]])
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            if b0 < a1:
                die("kind %s: overlapping bit ranges" % k["name"])
        if spans[-1][1] > limit:
            die("kind %s: a bit range ends at %d, past the message (%d bits)" % (k["name"], spans[-1][1], limit))
        if not k["requires"] or len(k["requires"]) > 6:
            die("kind %s: requires count" % k["name"])
        if not k["fields"]:
            die("kind %s: no field" % k["name"])
        for key in ("lat", "lon", "hae", "course", "speed_ms"):
            if sum(1 for f in k["fields"] if f["key"] == key) > 1:
                die("kind %s maps %s twice" % (k["name"], key))
        used.update(f["key"] for f in k["fields"])
        last_pgn.setdefault(d["PGN"], []).append(k)
    # kinds of one PGN: every earlier kind either conflicts with a later one or is strictly more specific
    for pgn, ks in last_pgn.items():
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a = {(s, l): v for s, l, v in ks[i]["whens"][1:]}
                b = {(s, l): v for s, l, v in ks[j]["whens"][1:]}
                if relation(a, b) not in ("conflict", "super"):
                    die("kinds %s and %s cannot be told apart in this order" % (ks[i]["name"], ks[j]["name"]))
    declared = {"%s.%s" % (MODULE, n) for n in n2k["keys"]}
    unused = declared - used
    if unused:
        die("module keys no kind maps: %s" % sorted(unused)[:5])
    # every vector, re-read from disk
    vdir = os.path.join(out_dir, "packs", FORMAT, "vectors")
    names, seen_kinds = set(), set()
    pk = {k["name"]: k for k in pack["kinds"]}
    files = sorted(fn for fn in os.listdir(vdir) if fn.endswith(".json"))
    for fn in files:
        v = json.load(open(os.path.join(vdir, fn), encoding="utf-8"))
        if v["name"] in names:
            die("duplicate vector name %s" % v["name"])
        names.add(v["name"])
        if v["from"] != FORMAT or not re.fullmatch(r"(?:[0-9a-f]{2})+", v["input"]):
            die("vector %s: input" % fn)
        data = bytes.fromhex(v["input"])
        sel, ent = decode(pack, data)
        if sel["name"] != v["model"]["@kind"]:
            die("vector %s: kind" % fn)
        for key, want in v["model"].items():
            if key == "@kind":
                continue
            got = ent[key]
            if isinstance(got, float):
                if abs(got - float(want)) > 1e-9:
                    die("vector %s: %s" % (fn, key))
            elif model_text(got) != want:
                die("vector %s: %s" % (fn, key))
        if v["to"] == FORMAT:
            seen_kinds.add(sel["name"])
            if encode(pack, pk[sel["name"]], ent).hex() != v["expect"] or v["expect"] != v["input"]:
                die("vector %s: round trip" % fn)
        elif v["to"] == "geojson":
            if geojson_text(ent) != v["expect"]:
                die("vector %s: geojson" % fn)
            json.loads(v["expect"])
        else:
            die("vector %s: target" % fn)
    if seen_kinds != set(pk):
        die("kinds without a round-trip vector: %s" % sorted(set(pk) - seen_kinds)[:5])
    return len(files), len(n2k["keys"])


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output root (holds sources/, model/, packs/)")
    ap.add_argument("--commit", help="canboat commit SHA; writes sources/PROVENANCE.md")
    ap.add_argument("--fetch", action="store_true", help="download the sources again even when present")
    ap.add_argument("--core-def", help="goat-transformers model/core.def, to check the built-in core key table")
    args = ap.parse_args()
    out = os.path.abspath(args.out)
    src = os.path.join(out, "sources")
    try:
        got = None
        if args.commit:
            if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
                die("--commit takes a full 40-character SHA")
            got = fetch_sources(src, args.commit, args.fetch)
            sha = args.commit
        else:
            sha = read_commit(src)
        db = json.load(open(os.path.join(src, "canboat.json"), encoding="utf-8"))
        if got:
            write_provenance(src, sha, got, db)

        kinds, unmapped = classify(db)
        keys = assign_keys(kinds)
        if len(kinds) + len(unmapped) != len(db["PGNs"]):
            die("definitions unaccounted for")
        pack_text = emit_pack(kinds, sha, db)
        write(os.path.join(out, "model", MODULE + ".def"), emit_module(keys, sha, db))
        write(os.path.join(out, "packs", FORMAT, "pack.def"), pack_text)
        core = {"distribution": "public", "keys": CORE_KEYS}
        pack = parse_pack(pack_text, {"core": core, MODULE: parse_module(emit_module(keys, sha, db))})
        n_vec, xnames = write_vectors(out, kinds, pack)
        write(os.path.join(out, "packs", FORMAT, "pack.md"),
              emit_pack_md(kinds, unmapped, keys, db, sha, n_vec, xnames))
        n_files, n_keys = self_check(out, kinds, args.core_def)
    except GenError as e:
        print("canboat2pack: FAILED: %s" % e, file=sys.stderr)
        return 1

    reasons = Counter(u[3] for u in unmapped)
    print("source: %s %s @ %s (CANboat %s)" % (REPO, DB_PATH, sha, db.get("Version")))
    print("PGN definitions in the source: %d (%d distinct PGNs)" % (len(db["PGNs"]), len({d["PGN"] for d in db["PGNs"]})))
    print("kinds generated: %d (%d distinct PGNs)" % (len(kinds), len({k.pgn for k in kinds})))
    for code in REASON_TITLES:
        print("not mapped, %s: %d" % (code, reasons.get(code, 0)))
    print("module %s keys: %d" % (MODULE, n_keys))
    core_use = Counter(f.key for k in kinds for f in k.fields if f.core)
    print("core mappings: %s" % dict(core_use))
    print("kinds with an unmapped inexpressible field: %d" % sum(1 for k in kinds if k.unexpressed))
    print("kinds from definitions CANboat marks incomplete: %d" % sum(1 for k in kinds if not k.d.get("Complete")))
    print("vectors: %d (%d round trips, %d to geojson)" % (n_files, len(kinds), len(xnames)))
    print("self-check: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
