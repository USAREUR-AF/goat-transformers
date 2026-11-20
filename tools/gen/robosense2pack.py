#!/usr/bin/env python3
"""robosense2pack: RoboSense lidar packets (MSOP and DIFOP) as goat-transformers `bits` packs.

Reads   <src>/src/rs_driver/driver/decoder/basic_attr.hpp, decoder.hpp and
        decoder_<model>.hpp of RoboSense-LiDAR/rs_driver: the packed structs of each
        model's packets, and each model's constant parameters (packet lengths and
        identity bytes) in its `getConstParam`
        <src>/LICENSE
        tools/gen/sources/robosense-PROVENANCE.md (commit and SHA-256 of every file;
        written with --commit, checked otherwise)
Writes  model/robosense.def, packs/robosense-<model>/ (pack.def, pack.md, PROVENANCE.md, vectors/)

One pack per model, one kind per packet: `msop` (point data) and `difop` (device
information). A kind's `when` is the packet's identity bytes, which the model's
constant parameters state. The layout is the packed struct (`#pragma pack(push, 1)`);
multi-byte integers are big-endian (the decoders read every field they use with
ntohs or ntohl, and assemble timestamps most significant byte first).

The struct reader is strict: inside a `#pragma pack(push, 1)` region it takes only
`typedef struct { <type> <name>[<n>]...; } <Name>;` whose member types are the
fixed-width integers, `unsigned int` or a struct it read before; anything else in
such a region stops the run. A model is built when its packet structs read and
their sizes equal the packet lengths its constant parameters state; otherwise it
is listed as not built, with the reason.

Python 3 standard library only. Vectors are written by a serializer in this file
from the layout and checked with its own codec of the fixed `bits` layout (msb,
one-byte words, nested fixed-count groups).

Usage: robosense2pack.py --src DIR [--out DIR] [--check] [--commit SHA --ref REF]
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

VERSION = "0.1.0"
MODULE = "robosense"
REPO = "https://github.com/RoboSense-LiDAR/rs_driver"
PROV = "tools/gen/sources/robosense-PROVENANCE.md"
DEC = "src/rs_driver/driver/decoder"
DATE_READ = "2026-11-20"
UNROLL = 8          # a scalar array of up to this many elements is one key per element

SCALARS = {"uint8_t": (8, "uint"), "int8_t": (8, "twos"), "uint16_t": (16, "uint"), "int16_t": (16, "twos"),
           "uint32_t": (32, "uint"), "int32_t": (32, "twos"), "uint64_t": (64, "uint"), "int64_t": (64, "twos"),
           "unsigned int": (32, "uint")}


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


class NotBuilt(Exception):
    pass


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(src, rel):
    with open(os.path.join(src, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def snake(s):
    return re.sub(r"_+", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower()).strip("_")


# --------------------------------------------------------------------------
# Structs
# --------------------------------------------------------------------------

F = collections.namedtuple("F", "name bit bits tr")
G = collections.namedtuple("G", "name bit item count body")


def read_consts(text, consts):
    for m in re.finditer(r"^\s*#define\s+(\w+)\s+\(?(\d+)\)?\s*$", strip_comments(text), re.M):
        if consts.get(m.group(1), int(m.group(2))) != int(m.group(2)):
            fail("#define %s has two values" % m.group(1))
        consts[m.group(1)] = int(m.group(2))


def read_structs(text, where, structs, consts):
    """Add the typedef structs of the packed regions of `text` to `structs`
    ({name: (where, [(type, member, count)])}); member types are checked later."""
    text = strip_comments(text)
    for region in re.findall(r"#pragma pack\(push, 1\)(.*?)#pragma pack\(pop\)", text, re.S):
        rest = region
        for m in re.finditer(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", region, re.S):
            members = []
            for decl in m.group(1).split(";"):
                d = " ".join(decl.split())
                if not d:
                    continue
                mm = re.fullmatch(r"(unsigned int|\w+) (\w+)(?:\[(\w+)\])?", d)
                if not mm:
                    fail("%s, struct %s: the member `%s`" % (where, m.group(2), d))
                n = mm.group(3)
                if n is not None and not n.isdigit():
                    if n not in consts:
                        fail("%s, struct %s: the array size `%s`" % (where, m.group(2), n))
                    n = consts[n]
                members.append((mm.group(1), mm.group(2), int(n) if n is not None else None))
            if m.group(2) in structs:
                fail("%s: struct %s read twice" % (where, m.group(2)))
            structs[m.group(2)] = members
            rest = rest.replace(m.group(0), "", 1)
        if rest.strip():
            fail("%s: a packed region holds `%s`, which is not a typedef struct" % (where, " ".join(rest.split())[:60]))


def check_types(structs, t, seen=()):
    """Raise NotBuilt when struct `t` uses a type that is neither a scalar nor a struct read."""
    if t in seen:
        raise NotBuilt("struct %s contains itself" % t)
    for mt, name, _ in structs[t]:
        if mt in SCALARS:
            continue
        if mt not in structs:
            raise NotBuilt("%s.%s is of type %s, which no packed region declares" % (t, name, mt))
        check_types(structs, mt, seen + (t,))


def size_bits(structs, t):
    if t in SCALARS:
        return SCALARS[t][0]
    return sum(size_bits(structs, mt) * (n or 1) for mt, _, n in structs[t])


def layout(structs, t, skip=()):
    """The nodes of struct `t`, bits from 0; members in `skip` (the identity bytes) are left out."""
    out, at = [], 0
    for mt, name, n in structs[t]:
        sz = size_bits(structs, mt)
        if name in skip:
            at += sz * (n or 1)
            continue
        key = snake(name)
        if mt in SCALARS:
            tr = SCALARS[mt][1]
            if n is None:
                out.append(F(key, at, sz, tr))
            elif n <= UNROLL:
                for i in range(n):
                    out.append(F("%s_%d" % (key, i), at + i * sz, sz, tr))
            else:
                out.append(G(key, at, sz, n, [F("value", 0, sz, tr)]))
        else:
            body = layout(structs, mt)
            if n is None:
                out += [x._replace(name="%s_%s" % (key, x.name), bit=x.bit + at) for x in body]
            else:
                out.append(G(key, at, sz, n, body))
        at += sz * (n or 1)
    return out


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

def const_param(text, model):
    """{msop_len, difop_len, msop_id, difop_id} from a model's getConstParam."""
    m = re.search(r"getConstParam\(\)\s*\{(.*?)\n\}", text, re.S)
    if not m:
        raise NotBuilt("no getConstParam")
    body = m.group(1)
    out = {}
    for what in ("msop len", "difop len"):
        mm = re.search(r"(\d+)\s*//\s*%s\b" % what, body)
        out[what.replace(" ", "_")] = int(mm.group(1)) if mm else None
    for what in ("msop id", "difop id"):
        mm = re.search(r"\{([^{}]*)\}\s*//\s*%s\s*$" % what, body, re.M)
        out[what.replace(" ", "_")] = [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]+", mm.group(1))] if mm else None
    return out


def plan_model(structs, cp, prefix, pair=None):
    """`pair` ({kind: struct}) names the structs when a file holds one of each."""
    kinds = []
    for kind in ("msop", "difop"):
        if pair is not None:
            name = pair.get(kind)
        else:
            name = next((n for n in ("%s%sPkt" % (prefix, kind.capitalize()), "%s_%sPkt" % (prefix, kind.capitalize()))
                         if n in structs), None)
        ident, length = cp["%s_id" % kind], cp["%s_len" % kind]
        if name is None:
            continue
        if not ident or length is None:
            raise NotBuilt("%s: no %s id or length in getConstParam" % (name, kind))
        check_types(structs, name)
        if size_bits(structs, name) != 8 * length:
            raise NotBuilt("%s is %d bytes, the %s length is %d" % (name, size_bits(structs, name) // 8, kind, length))
        body = layout(structs, name)
        lead = [x for x in body if x.bit < 8 * len(ident)]
        want = ["id_%d" % i for i in range(len(ident))]
        if [x.name.split("_", 1)[-1] if x.name.startswith(("header_", "head_")) else x.name for x in lead] != want \
                or any(isinstance(x, G) or x.bits != 8 for x in lead):
            raise NotBuilt("%s does not start with %d identity bytes `id`" % (name, len(ident)))
        kinds.append({"kind": kind, "struct": name, "id": ident, "bytes": length,
                      "body": [x for x in body if x.bit >= 8 * len(ident)]})
    if not kinds:
        raise NotBuilt("no MsopPkt or DifopPkt struct")
    return kinds


# --------------------------------------------------------------------------
# Emit, serializer and codec
# --------------------------------------------------------------------------

def key(prefix, path, name):
    return "%s.%s" % (MODULE, "_".join([prefix] + path + [name]))


def node_lines(prefix, nodes, path, indent=""):
    out = []
    for n in nodes:
        if isinstance(n, G):
            out.append("%sgroup  %s  0:%d  item %d  count %d" % (indent, key(prefix, path, n.name), n.bit, n.item, n.count))
            out += node_lines(prefix, n.body, path + [n.name], indent + "  ")
            out.append("%send" % indent)
        else:
            out.append("%sfield  %s  0:%d:%d  %s" % (indent, key(prefix, path, n.name), n.bit, n.bits, n.tr))
    return out


def node_decls(prefix, nodes, path, where, out):
    for n in nodes:
        k = key(prefix, path, n.name).split(".", 1)[1]
        if isinstance(n, G):
            out[k] = ("list", None, "%s: %s (%d items)" % (where, ".".join(path + [n.name]), n.count))
            node_decls(prefix, n.body, path + [n.name], where, out)
        else:
            out[k] = ("key", "int", "%s: %s (%d bits)" % (where, ".".join(path + [n.name]), n.bits))


def fill(nodes, base, acc, total, salt):
    for n in nodes:
        if isinstance(n, G):
            for i in range(n.count):
                acc, salt = fill(n.body, base + n.bit + i * n.item, acc, total, salt)
        else:
            salt += 1
            raw = (salt * 2654435761 + 12345) % (1 << n.bits)
            acc |= raw << (total - base - n.bit - n.bits)
    return acc, salt


def message(k, salt):
    total = 8 * k["bytes"]
    acc, _ = fill(k["body"], 0, 0, total, salt)
    acc |= int.from_bytes(bytes(k["id"]), "big") << (total - 8 * len(k["id"]))
    return acc.to_bytes(k["bytes"], "big")


class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


def read_pack(text):
    pack = collections.OrderedDict()
    cur, stack = None, None
    for line in text.split("\n"):
        t = gtcheck.tokenize(line)
        if not t:
            continue
        if t[0] == "kind":
            cur = {"when": [], "body": []}
            pack[t[1]] = cur
            stack = [cur["body"]]
        elif t[0] == "when":
            w, b, n = (int(x) for x in t[1].split(":"))
            cur["when"].append((w * 8 + b, n, int(t[2])))
        elif t[0] == "field":
            w, b, n = (int(x) for x in t[2].split(":"))
            stack[-1].append(("f", t[1], w * 8 + b, n))
        elif t[0] == "group":
            w, b = (int(x) for x in t[2].split(":"))
            body = []
            stack[-1].append(("g", t[1], w * 8 + b, int(t[t.index("item") + 1]), int(t[t.index("count") + 1]), body))
            stack.append(body)
        elif t[0] == "end":
            stack.pop()
    return pack


def extent(nodes):
    return max(n[2] + (n[3] if n[0] == "f" else n[3] * n[4]) for n in nodes)


def get(whole, total, b, n):
    return (whole >> (total - b - n)) & ((1 << n) - 1)


def dec(nodes, whole, total, base):
    ent = {}
    for n in nodes:
        if n[0] == "f":
            ent[n[1]] = get(whole, total, base + n[2], n[3])
        else:
            ent[n[1]] = [dec(n[5], whole, total, base + n[2] + i * n[3]) for i in range(n[4])]
    return ent


def enc(nodes, ent, total, base, acc):
    for n in nodes:
        if n[0] == "f":
            if n[1] in ent:
                acc |= ent[n[1]] << (total - base - n[2] - n[3])
        else:
            items = ent.get(n[1])
            if items is None or len(items) != n[4]:
                raise Fail("transform-encode")
            for i, it in enumerate(items):
                acc = enc(n[5], it, total, base + n[2] + i * n[3], acc)
    return acc


def roundtrip(pack, data):
    whole, nbits = int.from_bytes(data, "big"), 8 * len(data)
    for name, k in pack.items():
        if all(b + n <= nbits and get(whole, nbits, b, n) == v for b, n, v in k["when"]):
            end = max([extent(k["body"])] + [b + n for b, n, _ in k["when"]])
            if nbits < end:
                raise Fail("malformed-wire")
            ent = dec(k["body"], whole, nbits, 0)
            total = (end + 7) // 8 * 8
            acc = enc(k["body"], ent, total, 0, 0)
            for b, n, v in k["when"]:
                acc |= v << (total - b - n)
            return name, acc.to_bytes(total // 8, "big").hex()
    raise Fail("no-kind")


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def vec(name, fmt, inp, expect=None, error=None, model=None, source=None):
    v = collections.OrderedDict([("name", name), ("from", fmt), ("to", fmt)])
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


def dump(v):
    return json.dumps(v, indent=2) + "\n"


def source_files(src):
    names = sorted(f for f in os.listdir(os.path.join(src, *DEC.split("/"))) if re.fullmatch(r"decoder_\w+\.hpp", f))
    return ["LICENSE", DEC + "/basic_attr.hpp", DEC + "/decoder.hpp", DEC + "/chan_angles.hpp"] + [DEC + "/" + f for f in names]


def build(args, out):
    files = source_files(args.src)
    if args.commit:
        a = ["# Provenance of the inputs of tools/gen/robosense2pack.py", "",
             "Written by `robosense2pack.py --commit`; every later run checks the files against it.",
             "Date read: %s." % DATE_READ, "", "| Fact | Value |", "|---|---|", "| Repository | %s |" % REPO,
             "| Ref | `%s` |" % args.ref, "| Commit | `%s` |" % args.commit, "", "| Path | SHA-256 |", "|---|---|"]
        a += ["| `%s` | `%s` |" % (rel, sha256_file(os.path.join(args.src, *rel.split("/")))) for rel in files]
        out.write(PROV, "\n".join(a) + "\n")
    text = out.read(PROV)
    commit = re.search(r"^\| Commit \| `([0-9a-f]{40})` \|$", text, re.M).group(1)
    ref = re.search(r"^\| Ref \| `([^`]+)` \|$", text, re.M).group(1)
    shas = dict(re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    if set(shas) != set(files):
        fail("%s lists other files than the generator reads" % PROV)
    for rel in files:
        if shas[rel] != sha256_file(os.path.join(args.src, *rel.split("/"))):
            fail("%s: SHA-256 is not the one in %s" % (rel, PROV))
    structs, consts, owner = {}, {}, {}
    for rel in files[1:]:
        read_consts(read(args.src, rel), consts)
    for rel in files[1:]:
        before = set(structs)
        read_structs(read(args.src, rel), rel, structs, consts)
        for s in set(structs) - before:
            owner[s] = rel
    models, notbuilt = [], collections.OrderedDict()
    for rel in files[4:]:
        name = re.fullmatch(r".*/decoder_(\w+)\.hpp", rel).group(1)
        text = read(args.src, rel)
        found = [(m.group(1), m.group(2).lower(), s) for s in sorted(structs) if owner[s] == rel
                 for m in [re.fullmatch(r"(\w+?)_?(Msop|Difop)_?Pkt", s)] if m]
        if not found:
            continue
        msops = [f for f in found if f[1] == "msop"]
        difops = [f for f in found if f[1] == "difop"]
        pairs = None
        if len(msops) == 1 and len(difops) <= 1:
            # one packet of each in the file: a pair named by the file, whatever the struct prefixes
            # (the RSM3 file names its DIFOP struct RRSM3DifopPkt; the RSE1 file's MSOP struct is RSEOSMsopPkt)
            pairs = {name: dict([(msops[0][1], msops[0][2])] + [(d[1], d[2]) for d in difops])}
        prefixes = sorted({f[0] for f in found}) if pairs is None else list(pairs)
        try:
            cp = const_param(strip_comments_keep_markers(text), name)
        except NotBuilt as e:
            notbuilt[name] = str(e)
            continue
        for prefix in prefixes:
            try:
                kinds = plan_model(structs, cp, prefix, pairs[prefix] if pairs else None)
            except NotBuilt as e:
                notbuilt[prefix] = str(e)
                continue
            used = set()

            def walk(s):
                used.add(owner[s])
                for mt, _, _ in structs[s]:
                    if mt in structs:
                        walk(mt)
            for k in kinds:
                walk(k["struct"])
            if len(kinds) == 2 and kinds[0]["id"] == kinds[1]["id"]:
                # MSOP and DIFOP carry the same identity bytes (the ports tell them apart):
                # each is a pack of its own
                models.append({"model": prefix, "suffix": "-difop", "file": rel, "kinds": [kinds[1]], "cp": cp,
                               "same_id": True,
                               "files": [rel] + sorted(used - {rel, DEC + "/basic_attr.hpp", DEC + "/decoder.hpp",
                                                               DEC + "/chan_angles.hpp"})})
                kinds = [kinds[0]]
            models.append({"model": prefix, "suffix": "", "file": rel, "kinds": kinds, "cp": cp,
                           "same_id": len(kinds) == 1 and cp["msop_id"] == cp["difop_id"] and cp["difop_len"] is not None,
                           "files": [rel] + sorted(used - {rel, DEC + "/basic_attr.hpp", DEC + "/decoder.hpp",
                                                           DEC + "/chan_angles.hpp"})})
    if not models:
        fail("no model could be built")
    # module
    decls = collections.OrderedDict()
    for m in models:
        for k in m["kinds"]:
            node_decls(snake(m["model"]) + "_" + k["kind"], k["body"], [], k["struct"], decls)
    srcline = ('source        "RoboSense rs_driver packet structs (%s/decoder_*.hpp, decoder.hpp, basic_attr.hpp), '
               '%s at %s, commit %s; field places and sizes only; BSD-3-Clause"' % (DEC, REPO, ref, commit))
    a = ["# The robosense module: raw keys of the robosense-<model> lidar packet formats.",
         "# Generated by tools/gen/robosense2pack.py; do not edit by hand.",
         "module        %s" % MODULE, "version       %s" % VERSION, "distribution  public", srcline]
    w = max(len(k) for k in decls)
    for k, (kind, t, d) in decls.items():
        a.append(('list %-*s          "%s"' % (w, k, d)) if kind == "list" else ('key  %-*s  %-6s  -  "%s"' % (w, k, t, d)))
    out.write("model/%s.def" % MODULE, "\n".join(a) + "\n")
    model = gtcheck.Model()
    model.add(out.read("model/core.def"), "model/core.def")
    model.add(out.read("model/%s.def" % MODULE), "model/%s.def" % MODULE)
    nvec = 0
    for mi, m in enumerate(models):
        fmt = "robosense-%s%s" % (m["model"].lower().replace("_", "-"), m["suffix"])
        rel = "packs/" + fmt
        p = ["# %s: RoboSense %s packets. Generated by tools/gen/robosense2pack.py; do not edit by hand." % (fmt, m["model"]),
             "format        %s" % fmt, "version       %s" % VERSION, "distribution  public", srcline,
             "uses          %s" % MODULE, "wire          bits", "bit_order     msb", "word_bytes    1"]
        for k in m["kinds"]:
            prefix = snake(m["model"]) + "_" + k["kind"]
            nid = 8 * len(k["id"])
            p += ["", "kind      %s" % k["kind"], "when      0:0:%d  %d" % (nid, int.from_bytes(bytes(k["id"]), "big"))]
            first = next(x for x in k["body"] if isinstance(x, F))
            p.append("requires  %s" % key(prefix, [], first.name))
            p += node_lines(prefix, k["body"], [])
        text = "\n".join(p) + "\n"
        out.write(rel + "/pack.def", text)
        try:
            gtcheck.load_pack(text, model, label=rel + "/pack.def")
        except gtcheck.CheckError as e:
            fail(str(e))
        codec = read_pack(text)
        vs = []
        for ki, k in enumerate(m["kinds"]):
            data = message(k, 1000 * (mi + 1) + 100 * ki)
            prefix = snake(m["model"]) + "_" + k["kind"]
            firsts = [x for x in k["body"] if isinstance(x, F)][:2]
            whole = int.from_bytes(data, "big")
            mv = collections.OrderedDict([("@kind", k["kind"])])
            for x in firsts:
                mv[key(prefix, [], x.name)] = str(get(whole, 8 * len(data), x.bit, x.bits))
            vs.append(("gen-rt-%s.json" % k["kind"], vec("rt-" + k["kind"], fmt, data.hex(), data.hex(), model=mv,
                       source="tools/gen/robosense2pack.py: the identity bytes of getConstParam, then every field of %s "
                              "set to a value chosen by the generator, big-endian at its place" % k["struct"])))
        k0 = m["kinds"][0]
        data = message(k0, 7)
        vs.append(("gen-err-short.json", vec("err-short", fmt, data[:-1].hex(), error="malformed-wire",
                                             source="one byte short of the %d-byte %s packet" % (len(data), k0["kind"]))))
        bad = bytearray(data)
        bad[0] ^= 0xFF
        vs.append(("gen-err-other-id.json", vec("err-other-id", fmt, bytes(bad).hex(), error="no-kind",
                                                source="the first identity byte changed: no kind's `when` holds")))
        for f in out.listdir(rel + "/vectors"):
            if f.startswith("gen-") and f not in {n for n, _ in vs}:
                out.remove(rel + "/vectors/" + f)
        for f, v in vs:
            out.write(rel + "/vectors/" + f, dump(v))
            try:
                kname, got = roundtrip(codec, bytes.fromhex(v["input"]))
                if "expect_error" in v:
                    fail("%s/%s: converted, want %s" % (rel, f, v["expect_error"]))
                if got != v["expect"] or kname != v["model"]["@kind"]:
                    fail("%s/%s: the codec gives other bytes" % (rel, f))
            except Fail as e:
                if v.get("expect_error") != e.kind:
                    fail("%s/%s: %s" % (rel, f, e.kind))
            nvec += 1
        out.write(rel + "/pack.md", pack_md(fmt, m, len(vs), ref, commit))
        out.write(rel + "/PROVENANCE.md", provenance_md(fmt, m, files, shas, ref, commit, args.src))
    return models, notbuilt, len(decls), nvec


def strip_comments_keep_markers(text):
    """Block comments removed; line comments kept (getConstParam marks its values with them)."""
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def layout_rows(nodes, path):
    rows = []
    for n in nodes:
        name = ".".join(path + [n.name])
        if isinstance(n, G):
            rows.append("| `%s` | %d | %d x %d bits | group |" % (name, n.bit, n.count, n.item))
            rows += layout_rows(n.body, path + [n.name])
        else:
            rows.append("| `%s` | %d | %d | `%s` |" % (name, n.bit, n.bits, n.tr))
    return rows


def pack_md(fmt, m, nvec, ref, commit):
    a = ["# %s" % fmt, "",
         "RoboSense %s lidar packets, from `%s` of %s at %s (commit `%s`). Generated by" % (m["model"], m["file"], REPO, ref, commit),
         "`tools/gen/robosense2pack.py` (run by `tools/gen/robosense-run.sh`); do not edit by hand.", "",
         "## Message convention", "",
         "A message is the UDP payload of one packet of the model: an MSOP packet (point data) or a",
         "DIFOP packet (device information), the driver's packed structs. The packet starts with",
         "identity bytes that the model's constant parameters (`getConstParam`) state; they are the",
         "kind's `when`. The ports and the order of packets are the transport's.", ""] + ([
         "This model's MSOP and DIFOP packets carry the same identity bytes and are told apart by",
         "their port, so each is a pack of its own (`robosense-%s` and `robosense-%s-difop`)." % (
             m["model"].lower().replace("_", "-"), m["model"].lower().replace("_", "-")), ""] if m.get("same_id") else []) + [
         "Byte order: big-endian. The decoders read every multi-byte field they use with `ntohs`,",
         "`ntohl` or `RS_SWAP_INT16` (a byte swap on the little-endian hosts they run on), and assemble",
         "the timestamps most significant byte first (`basic_attr.hpp`). The 2-byte temperature",
         "(`RSTemperature`) is a byte array, carried byte by byte; some models read it little-endian.", "",
         "| Kind | Struct | Bytes | Identity bytes |", "|---|---|---|---|"]
    for k in m["kinds"]:
        a.append("| `%s` | `%s` | %d | %s |" % (k["kind"], k["struct"], k["bytes"], " ".join("%02X" % b for b in k["id"])))
    for k in m["kinds"]:
        a += ["", "### %s" % k["kind"], "", "| Field | Bit | Bits | Transform |", "|---|---|---|---|"] + layout_rows(k["body"], [])
    a += ["", "## Shared keys", "",
          "None. Distances and angles are in the sensor's frame and need the model's resolution and",
          "calibration; the timestamps are calendar fields from the year 2000 or seconds and a",
          "sub-second count whose unit differs by model, which the pack keeps raw. Every field is a raw",
          "key of module `robosense`.", "",
          "## Not mapped, and why", "", "| What | Why |", "|---|---|",
          "| Distances in metres, angles in degrees | the resolution is the model's (`DISTANCE_RES` in `getConstParam`) |",
          "| Byte arrays longer than %d bytes (reserved areas, `gprmc` text, calibration tables) | carried as groups of raw bytes |" % UNROLL,
          "", "## Vectors", "",
          "`gen-rt-<kind>.json`: a round trip with every field set, values chosen by the generator and",
          "packed by its own serializer from the struct. `gen-err-short`: one byte short",
          "(`malformed-wire`); `gen-err-other-id`: other identity bytes (`no-kind`). %d vector files." % nvec,
          "", "## Sources", "", "See `PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def provenance_md(fmt, m, files, shas, ref, commit, src):
    used = ["LICENSE", DEC + "/basic_attr.hpp", DEC + "/decoder.hpp", DEC + "/chan_angles.hpp"] + m["files"]
    a = ["# Provenance", "",
         "Generated by `tools/gen/robosense2pack.py`. No source file is copied into this repository; the pack",
         "restates field places and sizes, with descriptions of its own. Date read: %s." % DATE_READ, "",
         "| Fact | Value |", "|---|---|", "| Repository | %s |" % REPO, "| Ref | `%s` |" % ref,
         "| Commit | `%s` |" % commit, "", "| Path | SHA-256 |", "|---|---|"]
    a += ["| `%s` | `%s` |" % (rel, shas[rel]) for rel in used]
    a += ["", "## License", "", "`LICENSE` at the root of the repository, quoted whole:", "", "```"]
    a += read(src, "LICENSE").rstrip("\n").splitlines()
    a += ["```", "", "The source files carry the same licence text in their headers.", "",
          "Licence of this pack: Apache-2.0, the repository's (REUSE.toml); the BSD notice above is kept",
          "with it here and in NOTICE.", "",
          "No source carries a distribution statement, handling marking, export-control notice or",
          "proprietary notice."]
    return "\n".join(a) + "\n"


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", required=True)
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    ap.add_argument("--commit")
    ap.add_argument("--ref")
    args = ap.parse_args(argv)
    if args.commit and not args.ref:
        ap.error("--commit needs --ref")
    out = genio.Output(args.out, check=args.check)
    try:
        models, notbuilt, nkeys, nvec = build(args, out)
    except GenError as e:
        print("robosense2pack: %s" % e, file=sys.stderr)
        return 1
    print("robosense2pack: %d packs (%d kinds), %d not built, %d keys and lists, %d vectors checked" % (
        len(models), sum(len(m["kinds"]) for m in models), len(notbuilt), nkeys, nvec))
    for n, why in notbuilt.items():
        print("  not built  %s: %s" % (n, why))
    return out.report("robosense2pack")


if __name__ == "__main__":
    sys.exit(main())
