#!/usr/bin/env python3
"""lidar2pack: Ouster and Velodyne lidar UDP packets as goat-transformers `bits` packs.

Reads   <ouster>/ouster_core/src/parsing.cpp            the field tables of the lidar profiles,
                                                         the packet, column and IMU field places
        <ouster>/ouster_core/include/ouster/core/defaults.h      columns per packet
        <ouster>/ouster_core/include/ouster/core/impl/lidar_frame_impl.h   packet type values
        <ouster>/LICENSE
        <velodyne>/velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp   the data packet
        <velodyne>/velodyne_pointcloud/src/lib/rawdata.cpp        how a return is read
        <velodyne>/velodyne_driver/include/velodyne_driver/time_conversion.hpp   the timestamp
        <velodyne>/LICENSE
        <gpsimu>/velodyne_gps_imu/src/gpsimu_driver.h, .cc   the HDL-32E position packet
        <gpsimu>/COPYING
        tools/gen/sources/lidar-PROVENANCE.md   (commits and SHA-256 of every file; written
                                                with --commit-*, checked otherwise)
Writes  model/ouster.def, model/velodyne.def, packs/ouster-*/, packs/velodyne-*/

Every layout is read from the source files with patterns that must match exactly
once; a file that changed shape stops the run. Bits a source does not name are
raw keys `..._gap_<bit>` (at most 64 bits each), so a round trip keeps them.

Python 3 standard library only. The vectors are written by a serializer in this
file from the layouts; the script then loads every pack through gtcheck and
decodes and re-encodes every vector with its own codec of the fixed `bits`
layout (lsb, one-byte words, nested fixed-count groups).

Usage: lidar2pack.py --ouster DIR --velodyne DIR --gpsimu DIR [--out DIR] [--check]
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402

VERSION = "0.1.0"
PROV = "tools/gen/sources/lidar-PROVENANCE.md"
DATE_READ = "2026-11-20"
PIXELS = (16, 32, 64, 128)      # beam counts of the Ouster product lines (test metadata of the SDK)

SOURCES = collections.OrderedDict([
    ("ouster", {"repo": "https://github.com/ouster-lidar/ouster-sdk", "files": [
        "LICENSE", "ouster_core/src/parsing.cpp", "ouster_core/include/ouster/core/defaults.h",
        "ouster_core/include/ouster/core/impl/lidar_frame_impl.h"]}),
    ("velodyne", {"repo": "https://github.com/ros-drivers/velodyne", "files": [
        "LICENSE", "velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp",
        "velodyne_pointcloud/src/lib/rawdata.cpp", "velodyne_driver/include/velodyne_driver/time_conversion.hpp"]}),
    ("gpsimu", {"repo": "https://github.com/ros-drivers/velodyne", "files": [
        "COPYING", "velodyne_gps_imu/src/gpsimu_driver.h", "velodyne_gps_imu/src/gpsimu_driver.cc"]}),
])


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


def sha256_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def read(src, rel):
    with open(os.path.join(src, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def one(pattern, text, what, flags=0):
    m = list(re.finditer(pattern, text, flags))
    if len(m) != 1:
        fail("%s: %d matches, want 1" % (what, len(m)))
    return m[0]


def num(expr):
    """An integer expression of digits, `+`, `*` and `size_t{n}`."""
    e = re.sub(r"size_t\{(\d+)\}", r"\1", expr.strip())
    if not re.fullmatch(r"[\d\s+*()]+", e):
        fail("expression `%s`" % expr)
    return eval(e, {"__builtins__": {}}, {})   # digits and + * only, checked above


# --------------------------------------------------------------------------
# Layout nodes
# --------------------------------------------------------------------------

F = collections.namedtuple("F", "name bit bits tr")              # a field: key suffix, place, transform
G = collections.namedtuple("G", "name bit item count body")      # a fixed-count group


def with_gaps(nodes, size, prefix="gap", whens=()):
    """`nodes` plus raw fields for every bit range of [0, size) no node and no `when` covers."""
    cover = sorted([(n.bit, n.bit + (n.bits if isinstance(n, F) else n.item * n.count)) for n in nodes] +
                   [(b, b + n) for b, n, _ in whens])
    out, at = list(nodes), 0
    for a, b in cover + [(size, size)]:
        if a < at:
            at = max(at, b)
            continue
        while at < a:
            n = min(64, a - at)
            out.append(F("%s_%d" % (prefix, at), at, n, "uint"))
            at += n
        at = max(at, b)
    for x in out:
        end = x.bit + (x.bits if isinstance(x, F) else x.item * x.count)
        if end > size:
            fail("%s ends at bit %d, beyond %d" % (x.name, end, size))
    return sorted(out, key=lambda x: x.bit)


# --------------------------------------------------------------------------
# Ouster
# --------------------------------------------------------------------------

def ouster_tables(text):
    tables = {}
    for m in re.finditer(r"static const Table<std::string, FieldDecodeInfo, \d+> (\w+)\{\{(.*?)\}\};", text, re.S):
        fields = []
        for e in re.finditer(r"\{ChanField::(\w+), field_info\(([^(){}]*(?:\{[^{}]*\}[^(){}]*)*)\)\}", m.group(2)):
            args = [num(a) for a in e.group(2).split(",")]
            fields.append((e.group(1), args))
        tables[m.group(1)] = fields
    profiles = {}
    body = one(r"profiles\{\{(.*?)\}\};", text, "parsing.cpp: the profiles table", re.S).group(1)
    for m in re.finditer(r"\{UDPProfileLidar::(\w+),\s*\{(\w+)\.data\(\),\s*\w+\.size\(\),\s*(\d+)\}\}", body):
        profiles[m.group(1)] = (m.group(2), int(m.group(3)))
    return tables, profiles


def pixel_fields(table, size_bits):
    out = []
    for name, args in table:
        if name.startswith("RAW32_"):
            continue                    # whole words that alias the named fields
        start, bits = args[0], args[1]
        upshift = args[2] if len(args) > 2 else 0
        if upshift or (len(args) > 4 and args[4] != 1):
            fail("pixel field %s: upshift or several elements" % name)
        out.append(F(name.lower(), start, bits, "uint"))
    return with_gaps(out, size_bits, "gap")


def ouster_layouts(src):
    text = read(src, "ouster_core/src/parsing.cpp")
    tables, profiles = ouster_tables(text)
    cols = int(one(r"constexpr int DEFAULT_COLUMNS_PER_PACKET = (\d+);",
                   read(src, "ouster_core/include/ouster/core/defaults.h"), "defaults.h").group(1))
    sizes = {}
    for name in ("packet_header_size", "col_header_size", "col_footer_size", "packet_footer_size"):
        m = one(r"\b%s = legacy \? (\d+) : (\d+);" % name, text, "parsing.cpp: %s" % name)
        sizes[name] = (int(m.group(1)), int(m.group(2)))
    ctor = one(r"explicit Impl\(const DataFormat& format\) : Impl\(\) \{(.*?)\n    \}\n\};", text,
               "parsing.cpp: the PacketFormat::Impl constructor", re.S).group(1)
    branches = one(r"if \(legacy\) \{(.*?)\} else if \(fusa\) \{(.*?)\} else \{(.*?)\}\s*col_timestamp_info", ctor,
                   "the legacy / fusa / standard header branches", re.S)
    common = dict((m.group(1), (int(m.group(2)), int(m.group(3)))) for m in
                  re.finditer(r"(col_timestamp|col_measurement_id)_info = field_info\((\d+), (\d+)\);", ctor))

    def infos(block):
        return dict((m.group(1), (int(m.group(2)), int(m.group(3)))) for m in
                    re.finditer(r"(\w+)_info = field_info\((\d+), (\d+)\);", block))
    legacy_hdr, std_hdr = infos(branches.group(1)), infos(branches.group(3))
    # the legacy column status is the column footer: its start is the footer's first bit
    one(r"auto start_bit = 8 \* \(col_size - col_footer_size\);", branches.group(1), "legacy col_status start")
    legacy_status_bits = int(one(r"col_status_info = field_info\(start_bit, (\d+), 0, \(start_bit \+ \d+\) / 8\);",
                                 branches.group(1), "legacy col_status").group(1))
    imu_block = one(r"if \(imu_profile == UDPProfileIMU::LEGACY\) \{(.*?)\} else if", ctor, "the legacy IMU block", re.S).group(1)
    imu_size = int(one(r"imu_packet_size = (\d+);", imu_block, "legacy IMU size").group(1))
    imu = [(m.group(1), int(m.group(2)), int(m.group(3))) for m in
           re.finditer(r"imu_(\w+)_info = field_info\((\d+), (\d+), 0, imu_packet_size\);", imu_block)]
    getters = dict((m.group(2), m.group(1)) for m in re.finditer(r"^(float|uint\d+_t) PacketFormat::(\w+)\(", text, re.M))
    impl = read(src, "ouster_core/include/ouster/core/impl/lidar_frame_impl.h")
    lidar_type = int(one(r"set_packet_type\(lidar_buf, (0x[0-9A-Fa-f]+)\)", impl, "lidar packet type").group(1), 16)
    return {"tables": tables, "profiles": profiles, "cols": cols, "sizes": sizes, "common": common,
            "legacy_hdr": legacy_hdr, "std_hdr": std_hdr, "legacy_status_bits": legacy_status_bits, "imu_size": imu_size, "imu": imu,
            "getters": getters, "lidar_type": lidar_type}


def ouster_packs(o):
    packs = []
    for profile, short in (("LEGACY", "legacy"), ("RNG19_RFL8_SIG16_NIR16", "rng19")):
        table_name, chan = o["profiles"][profile]
        legacy = profile == "LEGACY"
        k = 0 if legacy else 1
        ph, ch, cf, pf = (o["sizes"][n][k] for n in ("packet_header_size", "col_header_size",
                                                      "col_footer_size", "packet_footer_size"))
        px = pixel_fields(o["tables"][table_name], chan * 8)
        for n in o["pixels"]:
            col_size = ch + n * chan + cf
            col = [F("timestamp", *o["common"]["col_timestamp"], tr="uint"),
                   F("measurement_id", *o["common"]["col_measurement_id"], tr="uint"),
                   G("pixels", ch * 8, chan * 8, n, px)]
            if legacy:
                col.append(F("frame_id", *o["legacy_hdr"]["frame_id"], tr="uint"))
                col.append(F("status", (col_size - cf) * 8, o["legacy_status_bits"], "uint"))
            else:
                col.append(F("status", *o["std_hdr"]["col_status"], tr="uint"))
            col = with_gaps(col, col_size * 8)
            body = [G("columns", ph * 8, col_size * 8, o["cols"], col)]
            whens = []
            if not legacy:
                for name in ("packet_type", "frame_id", "init_id", "prod_sn", "alert_flags",
                             "countdown_thermal_shutdown", "countdown_shot_limiting", "thermal_shutdown",
                             "shot_limiting"):
                    b, nb = o["std_hdr"][name]
                    if name == "packet_type":
                        whens.append((b, nb, o["lidar_type"]))
                        continue
                    if nb == 0:
                        fail("header field %s of 0 bits" % name)
                    body.append(F("hdr_" + name, b, nb, "uint"))
            total = (ph + o["cols"] * col_size + pf) * 8
            packs.append({"format": "ouster-%s-%d" % (short, n), "module": "ouster", "prefix": short,
                          "kind": "lidar", "whens": whens, "body": with_gaps(body, total, "gap", whens),
                          "bits": total, "profile": profile, "pixels": n, "chan": chan,
                          "sizes": (ph, ch, cf, pf, col_size)})
    fields = []
    for name, b, nb in o["imu"]:
        if nb == 0:
            continue
        t = o["getters"].get("imu_" + name)
        if t is None:
            fail("no getter imu_%s" % name)
        tr = "f32" if t == "float" else "uint"
        if tr == "f32" and nb != 32:
            fail("imu_%s: float of %d bits" % (name, nb))
        fields.append(F(name, b, nb, tr))
    packs.append({"format": "ouster-imu-legacy", "module": "ouster", "prefix": "imu", "kind": "imu",
                  "whens": [], "body": with_gaps(fields, o["imu_size"] * 8), "bits": o["imu_size"] * 8,
                  "profile": "IMU LEGACY"})
    return packs


# --------------------------------------------------------------------------
# Velodyne
# --------------------------------------------------------------------------

def velodyne_layouts(src, gps):
    h = read(src, "velodyne_pointcloud/include/velodyne_pointcloud/rawdata.hpp")
    consts = dict((m.group(1), int(m.group(2))) for m in
                  re.finditer(r"static const int (\w+) = (\d+);", h))
    for c in ("SIZE_BLOCK", "RAW_SCAN_SIZE", "SCANS_PER_BLOCK", "PACKET_SIZE", "BLOCKS_PER_PACKET", "PACKET_STATUS_SIZE"):
        if c not in consts:
            fail("rawdata.hpp: no %s" % c)
    blk = one(r"struct raw_block\s*\{\s*uint16_t header;[^\n]*\n\s*uint16_t rotation;[^\n]*\n\s*uint8_t data\[BLOCK_DATA_SIZE\];\s*\};",
              h, "rawdata.hpp: raw_block")
    one(r"struct raw_packet\s*\{\s*raw_block blocks\[BLOCKS_PER_PACKET\];\s*uint16_t revolution;\s*uint8_t status\[PACKET_STATUS_SIZE\];\s*\};",
        h, "rawdata.hpp: raw_packet")
    cpp = read(src, "velodyne_pointcloud/src/lib/rawdata.cpp")
    one(r"tmp\.bytes\[0\] = block\.data\[k\];\s*tmp\.bytes\[1\] = block\.data\[k \+ 1\];", cpp, "rawdata.cpp: distance bytes")
    if "data[k + 2]" not in cpp:
        fail("rawdata.cpp: the intensity byte is not data[k + 2]")
    one(r"pkt\.data\[1204\] == 57", cpp, "rawdata.cpp: return mode byte")
    one(r"pkt\.data\[1205\] == VLS128_MODEL_ID", cpp, "rawdata.cpp: model byte")
    tc = read(src, "velodyne_driver/include/velodyne_driver/time_conversion.hpp")
    one(r"\(\(uint32_t\) data\[3\]\) << 24 \|\s*\(\(uint32_t\) data\[2\]\) << 16 \|\s*\(\(uint32_t\) data\[1\]\) << 8 \|\s*\(\(uint32_t\) data\[0\]\)",
        tc, "time_conversion.hpp: little-endian timestamp")
    gh = read(gps, "velodyne_gps_imu/src/gpsimu_driver.h")
    raw_blk = one(r"struct GyroTempAccelBlockRaw\s*\{(.*?)\};", gh, "GyroTempAccelBlockRaw", re.S).group(1)
    raw_pkt = one(r"struct VelodynePositioningPacketRaw\s*\{(.*?)\};", gh, "VelodynePositioningPacketRaw", re.S).group(1)
    if "#pragma pack(1)" not in gh:
        fail("gpsimu_driver.h: not packed")
    # what pack.md says of the 12-bit words, checked against the driver
    gc = read(gps, "velodyne_gps_imu/src/gpsimu_driver.cc")
    one(r"v = v & 0x0fff;\s*int16_t r=v;\s*if\(r>2047\)\s*r=-\(\(~\(r--\)\) & 0x0fff\);", gc, "gpsimu_driver.cc: convert12bit2int16")
    for f in (r"\.gyro\) \* 0\.09766", r"\.temp\) \* 0\.1453\+25", r"\.accel_x\) \* 0\.001221"):
        one(f, gc, "gpsimu_driver.cc: the factor %s" % f)
    return consts, struct_members(raw_blk), struct_members(raw_pkt)


def struct_members(body):
    out = []
    for line in body.split(";"):
        s = " ".join(line.split())
        if not s:
            continue
        m = re.fullmatch(r"(uint16_t|uint32_t|char|GyroTempAccelBlockRaw) (\w+)(?:\[(\d+)\])?", s)
        if not m:
            fail("a member `%s`" % s)
        out.append((m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None))
    return out


def velodyne_packs(consts, blk_members, pkt_members):
    scan = consts["RAW_SCAN_SIZE"] * 8
    ret = [F("distance", 0, 16, "uint"), F("intensity", 16, 8, "uint")]
    if scan != 24:
        fail("a return of %d bits" % scan)
    block = [F("flag", 0, 16, "uint"), F("azimuth", 16, 16, "uint"),
             G("returns", 32, scan, consts["SCANS_PER_BLOCK"], ret)]
    nblk = consts["BLOCKS_PER_PACKET"]
    blk_bits = consts["SIZE_BLOCK"] * 8
    if 32 + consts["SCANS_PER_BLOCK"] * scan != blk_bits:
        fail("a block is not %d bytes" % consts["SIZE_BLOCK"])
    tail = nblk * blk_bits
    body = [G("blocks", 0, blk_bits, nblk, block), F("timestamp_us", tail, 32, "uint"),
            F("return_mode", tail + 32, 8, "uint"), F("product_id", tail + 40, 8, "uint")]
    total = consts["PACKET_SIZE"] * 8
    if tail + 48 != total:
        fail("blocks and tail are not PACKET_SIZE")
    packs = [{"format": "velodyne-data", "module": "velodyne", "prefix": "data", "kind": "data", "whens": [],
              "body": with_gaps(body, total), "bits": total}]
    # the HDL-32E position packet
    sizes = {"uint16_t": 16, "uint32_t": 32, "char": 8}
    blk = []
    at = 0
    for t, name, n in blk_members:
        if t != "uint16_t" or n:
            fail("GyroTempAccelBlockRaw: %s %s" % (t, name))
        blk.append(F(snake(name), at, 12, "uint"))
        blk.append(F(snake(name) + "_top", at + 12, 4, "uint"))
        at += 16
    blk_bits = at
    body, at = [], 0
    for t, name, n in pkt_members:
        if t == "GyroTempAccelBlockRaw":
            body.append(G(snake(name), at, blk_bits, n, blk))
            at += blk_bits * n
        elif t == "char":
            body.append(G(snake(name).strip("_"), at, 8, n, [F("byte", 0, 8, "uint")]))
            at += 8 * n
        else:
            body.append(F(snake(name), at, sizes[t], "uint"))
            at += sizes[t]
    packs.append({"format": "velodyne-position-hdl32e", "module": "velodyne", "prefix": "pos", "kind": "position",
                  "whens": [], "body": body, "bits": at})
    return packs


def snake(s):
    return re.sub(r"_+", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s).lower())


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------

def key(p, path, name):
    return "%s.%s_%s" % (p["module"], "_".join([p["prefix"]] + path), name)


def lines(p, nodes, path, indent=""):
    out = []
    for n in nodes:
        if isinstance(n, G):
            out.append("%sgroup  %s  0:%d  item %d  count %d" % (indent, key(p, path, n.name), n.bit, n.item, n.count))
            out += lines(p, n.body, path + [n.name], indent + "  ")
            out.append("%send" % indent)
        else:
            out.append("%sfield  %s  0:%d:%d  %s" % (indent, key(p, path, n.name), n.bit, n.bits, n.tr))
    return out


def decls(p, nodes, path, out):
    for n in nodes:
        k = key(p, path, n.name).split(".", 1)[1]
        if isinstance(n, G):
            out[k] = ("list", None, "%s: %s (%d items of %d bits)" % (p["format"], "/".join(path + [n.name]), n.count, n.item))
            decls(p, n.body, path + [n.name], out)
        else:
            out[k] = ("key", "float" if n.tr == "f32" else "int", "%s: %s (%d bits)" % (p["format"], "/".join(path + [n.name]), n.bits))


def pack_text(p, srcline):
    a = ["# %s. Generated by tools/gen/lidar2pack.py; do not edit by hand." % p["format"],
         "format        %s" % p["format"], "version       %s" % VERSION, "distribution  public", srcline,
         "uses          %s" % p["module"], "wire          bits", "bit_order     lsb", "word_bytes    1", "",
         "kind      %s" % p["kind"]]
    for b, n, v in p["whens"]:
        a.append("when      0:%d:%d  %d" % (b, n, v))
    first = next((x for x in p["body"] if isinstance(x, F) and "gap_" not in x.name), p["body"][0])
    a.append("requires  %s" % key(p, [], first.name))
    a += lines(p, p["body"], [])
    return "\n".join(a) + "\n"


# --------------------------------------------------------------------------
# Serializer and codec
# --------------------------------------------------------------------------

class Sampler:
    def __init__(self, salt):
        self.n = salt

    def raw(self, f):
        self.n += 1
        if f.tr == "f32":
            v = ((self.n * 37) % 2001 - 1000) / 8.0 or 0.125
            return int.from_bytes(struct.pack("<f", v), "little")
        return (self.n * 2654435761 + 12345) % (1 << f.bits)


def fill(nodes, base, acc, s, whens=()):
    for n in nodes:
        if isinstance(n, G):
            for i in range(n.count):
                acc = fill(n.body, base + n.bit + i * n.item, acc, s)
        else:
            acc |= s.raw(n) << (base + n.bit)
    for b, nb, v in whens:
        acc = (acc & ~(((1 << nb) - 1) << b)) | (v << b)
    return acc


class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


def read_pack(text):
    root = {"whens": [], "body": []}
    stack = [root["body"]]
    for line in text.split("\n"):
        t = gtcheck.tokenize(line)
        if not t:
            continue
        if t[0] == "when":
            w, b, n = (int(x) for x in t[1].split(":"))
            root["whens"].append((w * 8 + b, n, int(t[2])))
        elif t[0] == "field":
            w, b, n = (int(x) for x in t[2].split(":"))
            stack[-1].append(("f", t[1], w * 8 + b, n, t[3]))
        elif t[0] == "group":
            w, b = (int(x) for x in t[2].split(":"))
            body = []
            stack[-1].append(("g", t[1], w * 8 + b, int(t[t.index("item") + 1]), int(t[t.index("count") + 1]), body))
            stack.append(body)
        elif t[0] == "end":
            stack.pop()
    return root


def extent(nodes):
    return max(n[2] + (n[3] if n[0] == "f" else n[3] * n[4]) for n in nodes)


def dec(nodes, whole, base):
    ent = {}
    for n in nodes:
        if n[0] == "f":
            raw = (whole >> (base + n[2])) & ((1 << n[3]) - 1)
            if n[4] == "f32":
                v = struct.unpack("<f", raw.to_bytes(4, "little"))[0]
                if math.isnan(v) or v in (float("inf"), float("-inf")):
                    raise Fail("transform-decode")
                ent[n[1]] = v
            else:
                ent[n[1]] = raw
        else:
            ent[n[1]] = [dec(n[5], whole, base + n[2] + i * n[3]) for i in range(n[4])]
    return ent


def enc(nodes, ent, base, acc):
    for n in nodes:
        if n[0] == "f":
            if n[1] in ent:
                v = ent[n[1]]
                raw = int.from_bytes(struct.pack("<f", v), "little") if n[4] == "f32" else v
                acc |= raw << (base + n[2])
        else:
            items = ent.get(n[1])
            if items is None or len(items) != n[4]:
                raise Fail("transform-encode")
            for i, it in enumerate(items):
                acc = enc(n[5], it, base + n[2] + i * n[3], acc)
    return acc


def roundtrip(pk, data):
    whole, nbits = int.from_bytes(data, "little"), 8 * len(data)
    for b, n, v in pk["whens"]:
        if b + n > nbits or (whole >> b) & ((1 << n) - 1) != v:
            raise Fail("no-kind")
    end = max([extent(pk["body"])] + [b + n for b, n, _ in pk["whens"]])
    if nbits < end:
        raise Fail("malformed-wire")
    ent = dec(pk["body"], whole, 0)
    acc = enc(pk["body"], ent, 0, 0)
    for b, n, v in pk["whens"]:
        acc = (acc & ~(((1 << n) - 1) << b)) | (v << b)
    return acc.to_bytes((end + 7) // 8, "little").hex(), ent


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


def provenance_table(text):
    facts = {}
    for name in SOURCES:
        m = re.search(r"^\| %s \| (\S+) \| `([^`]+)` \| `([0-9a-f]{40})` \|$" % name, text, re.M)
        if not m:
            fail("%s: no line for %s" % (PROV, name))
        facts[name] = (m.group(2), m.group(3))
    shas = dict(((m.group(1), m.group(2)), m.group(3)) for m in
                re.finditer(r"^\| (\w+) \| `([^`]+)` \| `([0-9a-f]{64})` \|$", text, re.M))
    return facts, shas


def write_provenance(out, args, dirs):
    a = ["# Provenance of the inputs of tools/gen/lidar2pack.py", "",
         "Written by `lidar2pack.py --commit-*`; every later run checks the files against it.",
         "Date read: %s." % DATE_READ, "", "| Source | Repository | Ref | Commit |", "|---|---|---|---|"]
    for name, s in SOURCES.items():
        a.append("| %s | %s | `%s` | `%s` |" % (name, s["repo"], getattr(args, "ref_" + name), getattr(args, "commit_" + name)))
    a += ["", "| Source | Path | SHA-256 |", "|---|---|---|"]
    for name, s in SOURCES.items():
        for rel in s["files"]:
            a.append("| %s | `%s` | `%s` |" % (name, rel, sha256_file(os.path.join(dirs[name], *rel.split("/")))))
    out.write(PROV, "\n".join(a) + "\n")


def build(args, out):
    dirs = {"ouster": args.ouster, "velodyne": args.velodyne, "gpsimu": args.gpsimu}
    if args.commit_ouster:
        write_provenance(out, args, dirs)
    facts, shas = provenance_table(out.read(PROV))
    for name, s in SOURCES.items():
        for rel in s["files"]:
            if shas.get((name, rel)) != sha256_file(os.path.join(dirs[name], *rel.split("/"))):
                fail("%s %s: SHA-256 is not the one in %s" % (name, rel, PROV))
    o = ouster_layouts(args.ouster)
    o["pixels"] = tuple(int(x) for x in args.pixels.split(","))
    packs = ouster_packs(o) + velodyne_packs(*velodyne_layouts(args.velodyne, args.gpsimu))
    srcs = {"ouster": 'source        "Ouster SDK packet formats (ouster_core/src/parsing.cpp), %s at %s, commit %s; '
                      'field places and sizes only; BSD-3-Clause"' % (SOURCES["ouster"]["repo"], *facts["ouster"]),
            "velodyne": 'source        "ROS velodyne driver (velodyne_pointcloud rawdata, velodyne_driver time conversion), '
                        '%s at %s, commit %s, and the velodyne_gps_imu position packet struct at %s, commit %s; field '
                        'places and sizes only; BSD-3-Clause"' % (SOURCES["velodyne"]["repo"], facts["velodyne"][0],
                                                                  facts["velodyne"][1], facts["gpsimu"][0], facts["gpsimu"][1])}
    modules = collections.OrderedDict((m, collections.OrderedDict()) for m in ("ouster", "velodyne"))
    for p in packs:
        decls(p, p["body"], [], modules[p["module"]])
    for m, ds in modules.items():
        a = ["# The %s module: raw keys of the %s-* lidar packet formats." % (m, m),
             "# Generated by tools/gen/lidar2pack.py; do not edit by hand.",
             "module        %s" % m, "version       %s" % VERSION, "distribution  public", srcs[m]]
        w = max(len(k) for k in ds)
        for k, (kind, t, d) in ds.items():
            a.append(('list %-*s          "%s"' % (w, k, d)) if kind == "list" else ('key  %-*s  %-6s  -  "%s"' % (w, k, t, d)))
        out.write("model/%s.def" % m, "\n".join(a) + "\n")
    model = gtcheck.Model()
    model.add(out.read("model/core.def"), "model/core.def")
    for m in modules:
        model.add(out.read("model/%s.def" % m), "model/%s.def" % m)
    nvec = 0
    for i, p in enumerate(packs):
        rel = "packs/" + p["format"]
        text = pack_text(p, srcs[p["module"]])
        out.write(rel + "/pack.def", text)
        try:
            gtcheck.load_pack(text, model, label=rel + "/pack.def")
        except gtcheck.CheckError as e:
            fail(str(e))
        codec = read_pack(text)
        data = fill(p["body"], 0, 0, Sampler(1000 * (i + 1)), p["whens"]).to_bytes(p["bits"] // 8, "little")
        firsts = [n for n in p["body"] if isinstance(n, F)][:3]
        _, ent = roundtrip(codec, data)
        model_kv = collections.OrderedDict([("@kind", p["kind"])])
        for n in firsts:
            v = ent[key(p, [], n.name)]
            model_kv[key(p, [], n.name)] = repr(v) if isinstance(v, float) else str(v)
        vs = [("gen-rt-%s.json" % p["kind"], vec("rt-" + p["kind"], p["format"], data.hex(), data.hex(), model=model_kv,
                                                 source="tools/gen/lidar2pack.py: every field set to a value chosen by "
                                                        "the generator, little-endian at its place in the layout"))]
        vs.append(("gen-err-short.json", vec("err-short", p["format"], data[:-1].hex(), error="malformed-wire",
                                             source="one byte short of the %d-byte packet" % len(data))))
        if p["whens"]:
            b, n, v = p["whens"][0]
            bad = int.from_bytes(data, "little") ^ (1 << (b + n - 1))
            vs.append(("gen-err-other-type.json", vec("err-other-type", p["format"], bad.to_bytes(len(data), "little").hex(),
                                                      error="no-kind", source="the packet type is not %d" % v)))
        for f in out.listdir(rel + "/vectors"):
            if f.startswith("gen-") and f not in {n for n, _ in vs}:
                out.remove(rel + "/vectors/" + f)
        for f, v in vs:
            out.write(rel + "/vectors/" + f, dump(v))
            try:
                got, _ = roundtrip(codec, bytes.fromhex(v["input"]))
                if "expect_error" in v:
                    fail("%s/%s: converted, want %s" % (rel, f, v["expect_error"]))
                if got != v["expect"]:
                    fail("%s/%s: the codec gives other bytes" % (rel, f))
            except Fail as e:
                if v.get("expect_error") != e.kind:
                    fail("%s/%s: %s" % (rel, f, e.kind))
            nvec += 1
        out.write(rel + "/pack.md", pack_md(p, o, facts, len(vs)))
        out.write(rel + "/PROVENANCE.md", provenance_md(p, facts, shas, dirs))
    return packs, nvec, sum(len(d) for d in modules.values())


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------

def layout_rows(nodes, path, depth=0):
    rows = []
    for n in nodes:
        name = "/".join(path + [n.name])
        if isinstance(n, G):
            rows.append("| `%s` | %d | %d x %d bits | group |" % (name, n.bit, n.count, n.item))
            rows += layout_rows(n.body, path + [n.name], depth + 1)
        else:
            rows.append("| `%s` | %d | %d | `%s` |" % (name, n.bit, n.bits, n.tr))
    return rows


def pack_md(p, o, facts, nvec):
    fmt = p["format"]
    a = ["# %s" % fmt, "", "Generated by `tools/gen/lidar2pack.py` (run by `tools/gen/lidar-run.sh`); do not edit by hand.", ""]
    if fmt.startswith("ouster-") and fmt != "ouster-imu-legacy":
        ph, ch, cf, pf, col = p["sizes"]
        a += ["## Message convention", "",
              "One Ouster lidar data packet (the UDP payload) of the `%s` lidar profile, for a sensor" % p["profile"],
              "with %d pixels per column and %d columns per packet (the SDK's default). The layout" % (p["pixels"], o["cols"]),
              "is `PacketFormat` in `ouster_core/src/parsing.cpp` at %s: a packet header of %d bytes," % (facts["ouster"][0], ph),
              "%d columns of %d bytes (a column header of %d bytes, %d pixels of %d bytes, a column" % (o["cols"], col, ch, p["pixels"], p["chan"]),
              "footer of %d bytes), and a packet footer of %d bytes: %d bytes in all." % (cf, pf, p["bits"] // 8), "",
              "Byte order: little-endian. The SDK reads each field as an unsigned 64-bit word in the",
              "host's order with no swap (`FieldDecodeInfo::get`), masks and shifts it, on little-endian",
              "hosts; its zone-monitoring tests read packet words as `<u4`. Bits count from the least",
              "significant bit of that word, which is the pack's `bit_order lsb`.", ""]
        if p["profile"] == "LEGACY":
            a += ["The legacy profile has no packet header and no packet type: the kind has no `when`, and the",
                  "packet is told apart from other streams by its port and size. The frame id is in each",
                  "column header (the SDK reads it from the first); the column status is the column footer.", ""]
        else:
            a += ["The packet header's `packet_type` is the kind's `when`: %d for a lidar packet, the value" % o["lidar_type"],
                  "the SDK writes when it builds one (`lidar_frame_impl.h`).", ""]
        a += ["The number of pixels per column is the sensor's (16, 32, 64 or 128 by product line, as the",
              "SDK's test metadata shows) and is not in the packet: each count is its own pack. A sensor",
              "configured with another number of columns per packet needs another pack.", ""]
    elif fmt == "ouster-imu-legacy":
        a += ["## Message convention", "",
              "One Ouster IMU packet of the legacy IMU profile, %d bytes, as `PacketFormat` in" % (p["bits"] // 8),
              "`ouster_core/src/parsing.cpp` lays it out: three 64-bit timestamps (system, accelerometer,",
              "gyroscope), linear acceleration in g and angular velocity in degrees per second as",
              "float32 (the getters return `float`). Little-endian, as for the lidar packets. It has no",
              "type field: the kind has no `when`.", ""]
    elif fmt == "velodyne-data":
        a += ["## Message convention", "",
              "One Velodyne data packet (the UDP payload, 1206 bytes) as the ROS velodyne driver reads it,",
              "for the VLP-16, VLP-32C and HDL-32E, which share the layout: 12 blocks of a 16-bit flag",
              "(`UPPER_BANK` 0xEEFF or `LOWER_BANK` 0xDDFF), a 16-bit azimuth in hundredths of a degree and",
              "32 returns of a 16-bit distance and an 8-bit intensity; then a 32-bit timestamp, a return",
              "mode byte and a product byte. The driver's `raw_packet` struct names the last six bytes",
              "`revolution` and `status`, but its code reads bytes 1200-1203 as the timestamp",
              "(`time_conversion.hpp`), byte 1204 as the return mode (57 is dual) and byte 1205 as the",
              "model (161 is the VLS-128); the pack follows the code. How a model fills the 32 returns of",
              "a block (VLP-16: two firings of 16 lasers) is the reader's, from the model and calibration.", "",
              "Byte order: little-endian. The driver assembles the distance from `data[k]` (low) and",
              "`data[k + 1]` (high) and the timestamp from `data[0]` (low) to `data[3]` (high).", ""]
    else:
        a += ["## Message convention", "",
              "One HDL-32E position packet (512 bytes) as the `velodyne_gps_imu` node of the ROS velodyne",
              "driver reads it (`VelodynePositioningPacketRaw`, packed, on the `gps_imu` branch): 14 unused",
              "bytes, three gyroscope, temperature and accelerometer blocks of 16-bit words, 160 unused",
              "bytes, a 32-bit GPS timestamp, 4 unused bytes, 72 bytes of NMEA `$GPRMC` text and 234",
              "unused bytes. Little-endian, as the data packet. Each 16-bit sensor word holds a 12-bit value",
              "in its low bits; the top four bits are a separate raw key.", ""]
    a += ["## Layout", "", "| Field | Bit | Bits | Transform |", "|---|---|---|---|"] + layout_rows(p["body"], []) + [""]
    a += ["## Shared keys", "",
          "None. Ranges, azimuths and returns are in the sensor's own frame. The Ouster timestamps",
          "are counts of the sensor's clock whose unit and epoch the packet format does not state;",
          "the Velodyne timestamps are microseconds past the top of the hour, with no hour. Neither is",
          "a time with a stated epoch, so no field binds `time_ms`. Every field is a raw key of",
          "module `%s`." % p["module"], "",
          "## Not mapped, and why", "", "| What | Why |", "|---|---|",
          "| Bits the source does not name (`..._gap_<bit>`) | carried as raw keys so that a round trip keeps them |"]
    if fmt.startswith("ouster-") and fmt != "ouster-imu-legacy":
        a += ["| Other lidar profiles (dual return, low bandwidth, zone and RGB profiles, FuSa headers) | not asked for in this round; the generator reads the same tables |",
              "| The `RAW32_WORD*` aliases of the profile table | whole words over the named fields, not fields of their own |",
              "| Columns per packet other than %d | the count is a fixed group; it is a sensor setting not in the packet |" % o["cols"]]
    if fmt == "ouster-imu-legacy":
        a += ["| The `ACCEL32_GYRO32_NMEA` IMU profile | its number of measurements is a sensor setting (`imu_measurements_per_packet`), not in the packet |"]
    if fmt == "velodyne-data":
        a += ["| Distance in metres | the resolution is per model and calibration (`distance_resolution_m`) |",
              "| VLS-128 data packets | another block layout (four banks), not asked for |"]
    if fmt == "velodyne-position-hdl32e":
        a += ["| Scaled gyroscope, temperature and acceleration | the driver reads each 12-bit word as `(v & 0x0fff)`, and above 2047 as `v - 4095`, then scales it (0.09766 deg/s, 0.1453 C plus 25, 0.001221 g). That is neither two's complement nor sign and magnitude, so the pack keeps the 12 bits raw |",
              "| The `$GPRMC` text | 72 bytes of NMEA text ending in CR LF and NUL padding: `ascii` refuses the control bytes, so it is a group of 72 raw bytes; the `nmea0183` pack is on another wire and cannot be referenced |",
              "| VLP-16 and VLP-32C position packets | their layout is not in the driver's sources (only in Velodyne's manuals), so they are not built |"]
    a += ["", "## Vectors", "",
          "`gen-rt-*`: a round trip with every field set, values chosen by the generator and packed by",
          "its own serializer from the layout. `gen-err-short`: one byte short (`malformed-wire`).%s" %
          (" `gen-err-other-type`: another packet type (`no-kind`)." if p["whens"] else ""),
          "%d vector files." % nvec, "", "## Sources", "", "See `PROVENANCE.md`."]
    return "\n".join(a) + "\n"


def provenance_md(p, facts, shas, dirs):
    names = ["ouster"] if p["module"] == "ouster" else ["velodyne", "gpsimu"]
    a = ["# Provenance", "",
         "Generated by `tools/gen/lidar2pack.py`. No source file is copied into this repository; the pack",
         "restates field places and sizes, with descriptions of its own. Date read: %s." % DATE_READ, "",
         "| Source | Repository | Ref | Commit |", "|---|---|---|---|"]
    for n in names:
        a.append("| %s | %s | `%s` | `%s` |" % (n, SOURCES[n]["repo"], facts[n][0], facts[n][1]))
    a += ["", "| Source | Path | SHA-256 |", "|---|---|---|"]
    for n in names:
        for rel in SOURCES[n]["files"]:
            a.append("| %s | `%s` | `%s` |" % (n, rel, shas[(n, rel)]))
    a += ["", "## License", ""]
    for n in names:
        lic = "LICENSE" if n != "gpsimu" else "COPYING"
        a += ["`%s` of %s at `%s`, quoted whole:" % (lic, n, facts[n][1][:12]), "", "```"]
        a += read(dirs[n], lic).rstrip("\n").splitlines()
        a += ["```", ""]
    a += ["Licence of this pack: Apache-2.0, the repository's (REUSE.toml); the BSD notice above is kept",
          "with it here and in NOTICE.", "",
          "No source carries a distribution statement, handling marking, export-control notice or",
          "proprietary notice."]
    return "\n".join(a) + "\n"


def main(argv=None):
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ouster", required=True)
    ap.add_argument("--velodyne", required=True)
    ap.add_argument("--gpsimu", required=True)
    ap.add_argument("--pixels", default=",".join(str(n) for n in PIXELS),
                    help="the pixels per column to build Ouster lidar packs for (default %(default)s)")
    genio.add_arguments(ap, default_out=os.path.normpath(os.path.join(here, "..", "..")))
    for n in SOURCES:
        ap.add_argument("--commit-" + n)
        ap.add_argument("--ref-" + n)
    args = ap.parse_args(argv)
    out = genio.Output(args.out, check=args.check)
    try:
        packs, nvec, nkeys = build(args, out)
    except GenError as e:
        print("lidar2pack: %s" % e, file=sys.stderr)
        return 1
    print("lidar2pack: %d packs, %d keys and lists, %d vectors checked" % (len(packs), nkeys, nvec))
    return out.report("lidar2pack")


if __name__ == "__main__":
    sys.exit(main())
