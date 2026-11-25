#!/usr/bin/env python3
"""arsdk2pack: one `bits` pack per Parrot ARSDK feature, from the XML of arsdk-xml.

Python 3 standard library only. Reads the message definitions of the Parrot ARSDK
(github.com/Parrot-Developers/arsdk-xml, directory xml/, BSD-3-Clause by each file's
header) and writes, for every feature (an XML `<project>` with classes, or a
`<feature>` without):

  <out>/model/arsdk<feature>.def                  one raw key per argument
  <out>/packs/arsdk-<feature>/pack.def            the pack: `wire bits`, one kind per command
  <out>/packs/arsdk-<feature>/pack.md             what is mapped, and the commands not built
  <out>/packs/arsdk-<feature>/PROVENANCE.md       the sources, their SHA-256 and terms
  <out>/packs/arsdk-<feature>/vectors/gen-*.json  a round trip per kind; for a feature that binds a
                                                  position, conversions to and from GeoJSON
  <out>/packs/geojson/vectors/to-arsdk-*.json     the conversions whose input is GeoJSON

The wire encoding is that of libARCommands (Parrot-Developers/libARCommands, BSD-3-Clause):
a command is the feature id (8 bits), the class id (8 bits; 0 for a feature without
classes), the command id (16 bits), then each argument in order, little-endian
(libARSAL's device byte order): integers at their size, an enum as 32 bits, a bitfield
as its base integer, `float` and `double` as IEEE-754 single and double. A string is
written up to and including its NUL byte, so its length is not fixed; the `bits` wire has
no field that ends at a NUL, and a command with a `string` or `binary` argument is not
built (pack.md lists each one).

The vectors are computed by this program's own codec; no engine is run. After writing,
the output is loaded with gtcheck.py, the loader written from the specification.

Usage: python3 -I tools/gen/arsdk2pack.py --xml-dir DIR --out DIR [--check]
           [--xml-commit SHA] [--model-dir DIR]
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402

XML_URL = "https://github.com/Parrot-Developers/arsdk-xml"
LIBARCOMMANDS = ("Parrot-Developers/libARCommands", "d25b24e3d37c4fdf092d83196f575baf17420652",
                 "Tools/libARCommandsgen.py")
LIBARSAL = ("Parrot-Developers/libARSAL", "22e1f6b12aa6e46b26a75b768fd224c29ee00326",
            "Includes/libARSAL/ARSAL_Endianness.h")

INTS = {"u8": (8, False), "i8": (8, True), "u16": (16, False), "i16": (16, True),
        "u32": (32, False), "i32": (32, True), "u64": (64, False), "i64": (64, True)}
NOT_BUILT = {"string": "a `string` argument, written up to its NUL byte: a field that ends at a NUL "
                       "(a NUL-terminated string of variable length) is not in the pack language",
             "binary": "a `binary` argument, a block whose length is not fixed by the schema"}

F64_500 = struct.unpack("<Q", struct.pack("<d", 500.0))[0]
F32_500 = struct.unpack("<I", struct.pack("<f", 500.0))[0]

# Shared keys, by evidence (pack.md states it). A binding is (shared key, transform, sentinel or
# None). `default` names the kind an entity from another format encodes as; it requires `lat`
# and `lon`. Every other kind requires the pack's raw feature id, which only a decoded ARSDK
# command holds, so an entity from another format never selects it.
BIND = {
    ("ardrone3", "PilotingState", "PositionChanged"): {
        "latitude": ("lat", "f64", F64_500), "longitude": ("lon", "f64", F64_500)},
    ("ardrone3", "PilotingState", "GpsLocationChanged"): {
        "latitude": ("lat", "f64", F64_500), "longitude": ("lon", "f64", F64_500),
        "latitude_accuracy": ("track.sigma_north_m", "sscale:1", 255),
        "longitude_accuracy": ("track.sigma_east_m", "sscale:1", 255),
        "altitude_accuracy": ("track.sigma_up_m", "sscale:1", 255)},
    ("common", "GPS", "ControllerPositionForRun"): {
        "latitude": ("lat", "f64", None), "longitude": ("lon", "f64", None)},
    ("skyctrl", "SkyControllerState", "GpsPositionChanged"): {
        "latitude": ("lat", "f64", F64_500), "longitude": ("lon", "f64", F64_500)},
    ("controller_info", None, "gps"): {
        "latitude": ("lat", "f64", None), "longitude": ("lon", "f64", None),
        "north_speed": ("track.vel_north_ms", "f32", None), "east_speed": ("track.vel_east_ms", "f32", None),
        "down_speed": ("track.vel_up_ms", "f32scale:-1", None)},
    ("controller_info", None, "gps_v2"): {
        "latitude": ("lat", "f64", None), "longitude": ("lon", "f64", None),
        "wgs84_altitude": ("hae", "f32", None),
        "north_velocity": ("track.vel_north_ms", "f32", None), "east_velocity": ("track.vel_east_ms", "f32", None),
        "up_velocity": ("track.vel_up_ms", "f32", None)},
}
DEFAULT = {"ardrone3": ("PilotingState", "PositionChanged"), "common": ("GPS", "ControllerPositionForRun"),
           "skyctrl": ("SkyControllerState", "GpsPositionChanged"), "controller_info": (None, "gps_v2")}

# The evidence for each binding, in this repository's own words (pack.md).
EVIDENCE = {
    ("ardrone3", "PilotingState", "PositionChanged"):
        "the drone's position: latitude and longitude in decimal degrees, 500 when there is none "
        "(the sentinel, so the key is absent); the altitude is metres from the GPS with no stated reference, "
        "a raw key",
    ("ardrone3", "PilotingState", "GpsLocationChanged"):
        "the drone's location: latitude and longitude in decimal degrees, 500 when there is none; the three "
        "accuracies are one-standard-deviation errors in whole metres, -1 when there is none, north for "
        "latitude, east for longitude, up for altitude; the altitude is metres with no stated reference, a raw key",
    ("common", "GPS", "ControllerPositionForRun"):
        "the controller's latitude and longitude in decimal degrees, sent to the drone",
    ("skyctrl", "SkyControllerState", "GpsPositionChanged"):
        "the SkyController's position: latitude and longitude, 500 when there is none; the altitude is above "
        "sea level (not `hae`) and the heading is magnetic (not `course`), raw keys",
    ("controller_info", None, "gps"):
        "the controller's GPS: latitude and longitude in degrees; north and east speed in metres per second; "
        "the down speed in metres per second, positive downwards, so `vel_up` is its negative (`f32scale:-1`); "
        "the altitude is above sea level, a raw key",
    ("controller_info", None, "gps_v2"):
        "the controller's GPS: latitude and longitude in degrees, the altitude above the WGS 84 ellipsoid in "
        "metres (`hae`; the altitude above mean sea level is a raw key), north, east and up velocity in metres "
        "per second, up positive",
}


class GenError(Exception):
    pass


def snake(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


class Arg:
    def __init__(self, name, xml_type):
        self.name, self.xml_type = name, xml_type
        base = xml_type.split(":")
        self.kind = base[0]
        if self.kind == "enum":
            self.bits, self.signed = 32, False
        elif self.kind == "bitfield":
            self.bits, self.signed = INTS[base[1]]
        elif self.kind in INTS:
            self.bits, self.signed = INTS[self.kind]
        elif self.kind == "float":
            self.bits, self.signed = 32, True
        elif self.kind == "double":
            self.bits, self.signed = 64, True
        else:
            self.bits, self.signed = None, None


class Cmd:
    def __init__(self, cls, cls_id, name, cmd_id, tag, args, deprecated, list_type):
        self.cls, self.cls_id, self.name, self.id = cls, cls_id, name, cmd_id
        self.tag, self.args, self.deprecated, self.list_type = tag, args, deprecated, list_type

    @property
    def kind(self):
        return snake(self.cls) + "_" + snake(self.name) if self.cls else snake(self.name)

    def why_not(self):
        for a in self.args:
            if a.kind in NOT_BUILT:
                return NOT_BUILT[a.kind]
            if a.bits is None:
                return "an argument of type `%s`" % a.xml_type
        return None


class Feature:
    def __init__(self, path):
        raw = open(path, "rb").read()
        self.sha = hashlib.sha256(raw).hexdigest()
        self.file = os.path.basename(path)
        root = ET.fromstring(raw)
        if root.tag not in ("project", "feature"):
            raise GenError("%s: root is <%s>" % (self.file, root.tag))
        text = raw.decode("utf-8")
        if "Redistribution and use in source and binary forms" not in text or "Neither the name of" not in text:
            raise GenError("%s: no BSD-3-Clause header" % self.file)
        m = re.search(r"Copyright \(C\) (\d{4}) ([^\n]*)", text)
        self.copyright = "Copyright (C) %s %s" % (m.group(1), m.group(2).strip()) if m else None
        self.name, self.id, self.is_project = root.get("name"), int(root.get("id")), root.tag == "project"
        self.cmds = []
        if self.is_project:
            for c in root.findall("class"):
                for m_ in c.findall("cmd"):
                    self._add(c.get("name"), int(c.get("id")), m_)
        else:
            msgs = root.find("msgs")
            for m_ in (msgs if msgs is not None else []):
                if m_.tag in ("cmd", "evt"):
                    self._add(None, 0, m_)
        seen = set()
        for c in self.cmds:
            if (c.cls_id, c.id) in seen:
                raise GenError("%s: command id %d of class %d twice" % (self.file, c.id, c.cls_id))
            seen.add((c.cls_id, c.id))
        kinds = [c.kind for c in self.cmds]
        if len(set(kinds)) != len(kinds):
            raise GenError("%s: two commands with one name" % self.file)

    def _add(self, cls, cls_id, node):
        args = [Arg(a.get("name"), a.get("type")) for a in node.findall("arg")]
        self.cmds.append(Cmd(cls, cls_id, node.get("name"), int(node.get("id")), node.tag, args,
                             node.get("deprecated") == "true", node.get("type")))

    @property
    def slug(self):
        return self.name.replace("_", "-").lower()

    @property
    def module(self):
        return "arsdk" + re.sub(r"[^a-z0-9]", "", self.name.lower())

    @property
    def fmt(self):
        return "arsdk-" + self.slug

    def key(self, cmd, arg):
        return "%s.%s_%s" % (self.module, cmd.kind, snake(arg.name))

    def bind(self, cmd):
        return BIND.get((self.name, cmd.cls, cmd.name), {})


def transform_of(arg):
    if arg.kind == "float":
        return "f32"
    if arg.kind == "double":
        return "f64"
    return "twos" if arg.signed else "uint"


def layout(cmd):
    """(arg, bit offset) of every argument; the header is 32 bits."""
    out, pos = [], 32
    for a in cmd.args:
        out.append((a, pos))
        pos += a.bits
    return out, pos


# ---- the vectors' own codec -------------------------------------------------

def sample(cmd, i, arg):
    """A value for argument i: never a sentinel, exact in its type."""
    if arg.kind in ("float", "double"):
        return (i + 1) * 1.25 + (cmd.id % 7) * 0.5
    if arg.kind == "enum":
        return i % 3
    n = (37 * (i + 1) + cmd.id) % (1 << (arg.bits - 1))
    return -n if arg.signed and i % 2 else n


def pack_value(arg, v):
    if arg.kind == "float":
        return struct.pack("<f", v)
    if arg.kind == "double":
        return struct.pack("<d", v)
    return (v & ((1 << arg.bits) - 1)).to_bytes(arg.bits // 8, "little")


def header(ftr, cmd):
    return bytes([ftr.id, cmd.cls_id]) + cmd.id.to_bytes(2, "little")


def text_of(x):
    """A float as a vector's `model` states it: shortest round trip, integral without `.0`."""
    if x == int(x) and abs(x) < 2 ** 53:
        return str(int(x))
    return repr(x)


def model_of(ftr, cmd, values):
    m = {"@kind": cmd.kind, "%s.feature_id" % ftr.module: str(ftr.id)}
    bind = ftr.bind(cmd)
    for a in cmd.args:
        v = values[a.name]
        if a.kind == "float":
            v = struct.unpack("<f", struct.pack("<f", v))[0]
        m[ftr.key(cmd, a)] = text_of(v) if isinstance(v, float) else str(v)
        if a.name in bind:
            key, tr, sentinel = bind[a.name]
            if tr == "f32scale:-1":
                m[key] = text_of(-v + 0.0)
            elif tr == "sscale:1":
                m[key] = text_of(float(v))
            else:
                m[key] = text_of(float(v))
    return m


def encode(ftr, cmd, values):
    return header(ftr, cmd) + b"".join(pack_value(a, values[a.name]) for a in cmd.args)


def vectors(ftr):
    """-> {relative path: vector}."""
    out = {}
    built = [c for c in ftr.cmds if c.why_not() is None]
    for n, cmd in enumerate(built, 1):
        values = {a.name: sample(cmd, i, a) for i, a in enumerate(cmd.args)}
        bind = ftr.bind(cmd)
        for a in cmd.args:
            # never a sentinel: a sample that is one would decode as an absent key
            if a.name in bind and bind[a.name][2] is not None and \
                    int.from_bytes(pack_value(a, values[a.name]), "little") == bind[a.name][2]:
                values[a.name] = 3
        if (ftr.name, cmd.cls, cmd.name) in BIND:
            for a in cmd.args:
                if a.name == "latitude":
                    values[a.name] = 48.875
                elif a.name == "longitude":
                    values[a.name] = 2.3125
        b = encode(ftr, cmd, values).hex()
        out["packs/%s/vectors/gen-%03d-%s-roundtrip.json" % (ftr.fmt, n, cmd.kind.replace("_", "-"))] = {
            "name": "%s-roundtrip" % cmd.kind.replace("_", "-"), "from": ftr.fmt, "to": ftr.fmt,
            "input": b, "expect": b, "model": model_of(ftr, cmd, values)}
    d = DEFAULT.get(ftr.name)
    if d:
        cmd = next(c for c in ftr.cmds if (c.cls, c.name) == d)
        bind = ftr.bind(cmd)
        slug = cmd.kind.replace("_", "-")
        values = {a.name: 0 for a in cmd.args}
        values.update({a.name: 0.0 for a in cmd.args if a.kind in ("float", "double")})
        values["latitude"], values["longitude"] = 48.875, 2.3125
        has = {bind[a][0] for a in bind}
        props, coords = [], ["2.3125", "48.875"]
        if "hae" in has:
            alt = next(a for a in bind if bind[a][0] == "hae")
            values[alt] = 35.5
            coords.append("35.5")
        if "track.vel_north_ms" in has:
            north = next(a for a in bind if bind[a][0] == "track.vel_north_ms")
            values[north] = 5.0
            props = ['"course":0', '"speed_ms":5']
        full = encode(ftr, cmd, values).hex()
        gj = '{"type":"Feature","geometry":{"type":"Point","coordinates":[%s]},"properties":{%s}}' % (
            ",".join(coords), ",".join(props))
        out["packs/%s/vectors/gen-%s-to-geojson.json" % (ftr.fmt, slug)] = {
            "name": "%s-to-geojson" % slug, "from": ftr.fmt, "to": "geojson", "input": full, "expect": gj,
            "model": {"@complete": True, "lat": "48.875", "lon": "2.3125"},
            "reference": "the position as a GeoJSON point (engine-spec 0.1.1 rulings 3 and 4); course 0 and "
                         "speed 5 derive exactly from a velocity of 5 north and 0 east (model/track.def)"
                         if props else "the position as a GeoJSON point (engine-spec 0.1.1 rulings 3 and 4)"}
        # The way in: shared keys only; every other argument is absent and writes zero bits, or its
        # sentinel when it has one.
        values_in = {a.name: 0 for a in cmd.args}
        values_in.update({a.name: 0.0 for a in cmd.args if a.kind in ("float", "double")})
        values_in.update({k: values[k] for k in ("latitude", "longitude")})
        if "hae" in has:
            values_in[alt] = 35.5
        if props:
            values_in[north] = 5.0
        out["packs/geojson/vectors/to-%s-%s.json" % (ftr.fmt, slug)] = {
            "name": "to-%s-%s" % (ftr.fmt, slug), "from": "geojson", "to": ftr.fmt, "input": gj,
            "expect": encode(ftr, cmd, values_in).hex(),
            "reference": "the default kind %s; the arguments with no shared key are absent and written as zero "
                         "bits (engine-spec 0.5); east velocity 0 and north 5 from course 0 and speed 5" % cmd.kind
                         if props else "the default kind %s; the arguments with no shared key are absent and "
                         "written as zero bits (engine-spec 0.5)" % cmd.kind}
        if any(bind[a][2] is not None for a in ("latitude", "longitude")):
            values_na = dict(values)
            values_na["latitude"] = values_na["longitude"] = 500.0
            na = encode(ftr, cmd, values_na).hex()
            out["packs/%s/vectors/gen-%s-unavailable-to-geojson.json" % (ftr.fmt, slug)] = {
                "name": "%s-unavailable-to-geojson" % slug, "from": ftr.fmt, "to": "geojson", "input": na,
                "expect": '{"type":"Feature","geometry":null,"properties":{}}',
                "reference": "latitude and longitude 500 mean no position (engine-spec 0.9): no geometry"}
            out["packs/%s/vectors/gen-%s-unavailable-roundtrip.json" % (ftr.fmt, slug)] = {
                "name": "%s-unavailable-roundtrip" % slug, "from": ftr.fmt, "to": ftr.fmt, "input": na,
                "expect": na, "reference": "the raw keys keep 500 on a same-format round trip"}
    return out


# ---- writing ----------------------------------------------------------------

def line(key, loc, tr, sentinel=None):
    return "field     %-60s %-11s %s%s" % (key, loc, tr, "" if sentinel is None else "  absent %d" % sentinel)


def pack_text(ftr, sources):
    lines = ["# Parrot ARSDK feature %s (id %d): one command per message, as libARCommands writes it." % (
                 ftr.name, ftr.id),
             "# GENERATED by tools/gen/arsdk2pack.py from arsdk-xml; edit the generator, not this file.",
             "# pack.md states what is mapped and what is not.",
             "format        %s" % ftr.fmt, "version       0.1.0", "distribution  public"]
    lines += ["source        %s" % json.dumps(s) for s in sources]
    uses = {ftr.module}
    for c in ftr.cmds:
        for k, _tr, _s in ftr.bind(c).values():
            if "." in k:
                uses.add(k.split(".")[0])
    lines += ["uses          %s" % u for u in sorted(uses)]
    lines += ["wire          bits", "bit_order     lsb", "word_bytes    1", "",
              "# the header: feature id, class id, command id (little-endian)",
              "when      0:0:8 %d" % ftr.id,
              line("%s.feature_id" % ftr.module, "0:0:8", "uint")]
    if not ftr.is_project:
        lines.append("when      0:8:8 0")
    built = [c for c in ftr.cmds if c.why_not() is None]
    d = DEFAULT.get(ftr.name)
    order = [c for c in built if (c.cls, c.name) != d] + [c for c in built if (c.cls, c.name) == d]
    for c in order:
        lines += ["", "kind      %s" % c.kind]
        if ftr.is_project:
            lines.append("when      0:8:8 %d" % c.cls_id)
        lines.append("when      0:16:16 %d" % c.id)
        lines.append("requires  %s" % ("lat lon" if (c.cls, c.name) == d else "%s.feature_id" % ftr.module))
        bind = ftr.bind(c)
        for a, pos in layout(c)[0]:
            loc = "0:%d:%d" % (pos, a.bits)
            if a.name in bind:
                key, tr, sentinel = bind[a.name]
                lines.append(line(key, loc, tr, sentinel))
            lines.append(line(ftr.key(c, a), loc, transform_of(a)))
    return "\n".join(lines) + "\n"


def module_text(ftr, sources):
    lines = ["# The %s module: the arguments of the Parrot ARSDK feature %s, one raw key per" % (ftr.module, ftr.name),
             "# argument, named <command>_<argument>. GENERATED by tools/gen/arsdk2pack.py from arsdk-xml;",
             "# edit the generator, not this file.",
             "module        %s" % ftr.module, "version       0.1.0", "distribution  public"]
    lines += ["source        %s" % json.dumps(s) for s in sources]
    lines.append('key  %-60s int     -  %s' % ("feature_id", json.dumps(
        "the feature id of the command header (%d for %s)" % (ftr.id, ftr.name))))
    for c in ftr.cmds:
        if c.why_not():
            continue
        for a in c.args:
            ty = "float" if a.kind in ("float", "double") else "int"
            what = "%s%s %s, argument %s (%s)" % (c.cls + "." if c.cls else "", c.name, c.tag, a.name, a.xml_type)
            lines.append('key  %-60s %-6s  -  %s' % (ftr.key(c, a).split(".", 1)[1], ty, json.dumps(what)))
    return "\n".join(lines) + "\n"


def pack_md(ftr, built, skipped, commit):
    d = DEFAULT.get(ftr.name)
    rows = "\n".join("| `%s` | %s | %d | %d | %s | %d |" % (
        c.kind, c.tag, c.cls_id, c.id, "yes" if c.deprecated else "", len(c.args)) for c in built)
    nb = "\n".join("| `%s` | %d | %d | %s |" % (c.kind, c.cls_id, c.id, why) for c, why in skipped) or "| none | | | |"
    bound = [(c, ftr.bind(c)) for c in built if ftr.bind(c)]
    if bound:
        shared = ["| Kind | Argument | Key | Transform | Absent when |", "|---|---|---|---|---|"]
        for c, b in bound:
            for a in c.args:
                if a.name in b:
                    key, tr, s = b[a.name]
                    shared.append("| `%s` | `%s` | `%s` | `%s` | %s |" % (
                        c.kind, a.name, key, tr, "500" if s in (F64_500, F32_500) else ("-1" if s == 255 else "")))
        shared += [""] + ["- `%s`: %s." % (c.kind, EVIDENCE[(ftr.name, c.cls, c.name)]) for c, _b in bound]
        shared += ["",
                   ("The schema gives latitude and longitude in degrees from a GPS receiver but, apart from "
                    "`controller_info` `gps_v2` (whose other altitude is above the WGS 84 ellipsoid), names no "
                    "datum. The binding to `lat` and `lon`, which are WGS 84, rests on the reading that a GPS "
                    "receiver reports WGS 84; a reviewer who does not accept it removes the entries of `BIND` in "
                    "`tools/gen/arsdk2pack.py` and runs it again, and the raw keys, which stand on the same bits in "
                    "every case, remain."),
                   "",
                   ("Other commands carry a latitude and longitude that are not the position of the reporting thing "
                    "(a move target, a point of interest, a home, take-off or return location, a geofence centre, a "
                    "followed target's trajectory): they are raw keys.")]
        if d:
            shared += ["", "An entity from another format encodes as `%s` (it requires `lat` and `lon`); every "
                           "other kind requires the raw `%s.feature_id`, which only a decoded ARSDK command holds."
                       % (snake(d[0]) + "_" + snake(d[1]) if d[0] else snake(d[1]), ftr.module)]
        shared = "\n".join(shared)
    else:
        shared = ("None. Every argument is a raw key of `%s`, and every kind requires the raw `%s.feature_id`, which "
                  "only a decoded ARSDK command holds: an entity from another format selects no kind (`no-kind`)."
                  % (ftr.module, ftr.module))
    return """# Pack: %(fmt)s

The commands and events of the Parrot ARSDK feature `%(name)s` (id %(id)d), one kind
per command. Public. Generated by `tools/gen/arsdk2pack.py` from `xml/%(file)s` of
arsdk-xml (BSD-3-Clause, commit `%(commit)s`, sha256 `%(sha)s`).

## Message convention

A message is one ARSDK command as libARCommands encodes it: the feature id (8 bits),
the class id (8 bits; %(cls)s), the command id (16 bits), then the
arguments in schema order, little-endian. An enum is 32 bits, a bitfield is its base
integer, `float` and `double` are IEEE-754. The network framing around a command
(the ARNetworkAL frame: type, buffer id, sequence number and size) is not part of the
message; a caller removes it before `decode` and adds it after `encode`. The pack
selects the kind by the header (`when`); a command carries no length of its own, and
input beyond the last argument is not read.

Commands whose type is `LIST_ITEM` or `MAP_ITEM` are one item of a list each; each
item is one message, and the pack reads it as any other command.

## Kinds

| Kind | Element | Class id | Command id | Deprecated | Arguments |
|---|---|---|---|---|---|
%(rows)s

## Shared keys

%(shared)s

## Not mapped

These commands are not built:

| Command | Class id | Command id | Needs |
|---|---|---|---|
%(nb)s

Enum and bitfield arguments are carried as their integers; the module key's meaning
names the enum or the bitfield's base type. The schema's comments are not copied.

## Vectors

`vectors/gen-*.json`, computed by the generator's own codec: a round trip for every
kind%(extra)s.
""" % {"fmt": ftr.fmt, "name": ftr.name, "id": ftr.id, "file": ftr.file, "commit": commit, "sha": ftr.sha,
       "cls": "a class of the project" if ftr.is_project else "0 for a feature without classes",
       "rows": rows, "shared": shared, "nb": nb,
       "extra": "; for the default kind a conversion to GeoJSON and one from it (in `packs/geojson/vectors/`)"
                + ("; and a position of 500, which means none, to GeoJSON with no geometry"
                   if d and any(ftr.bind(c).get("latitude", (0, 0, None))[2] for c in built
                                if (c.cls, c.name) == d) else "") if d else ""}


def provenance(ftr, commit, helper_shas):
    return """# Provenance: %(fmt)s pack

Generated by `tools/gen/arsdk2pack.py`. No source file is copied into this tree.

| | |
|---|---|
| Message definitions | `xml/%(file)s` of %(url)s, commit `%(commit)s`, sha256 `%(sha)s` |
| Their terms | the file's header: "%(copy)s" and the BSD-3-Clause conditions ("Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met"); the repository has no LICENSE file |
| Wire encoding | https://github.com/%(lc0)s `%(lc2)s`, commit `%(lc1)s`, sha256 `%(lcsha)s`: the header (feature 8 bits, class 8 bits, command 16 bits) and the size of each argument type, an enum as 32 bits |
| Byte order | https://github.com/%(ls0)s `%(ls2)s`, commit `%(ls1)s`, sha256 `%(lssha)s`: the device byte order is little-endian |
| Their terms | `LICENSE.md` of both repositories: "Copyright (C) 2014 Parrot SA" and the BSD-3-Clause conditions |
| Date read | 2026-11-19 |

What is taken: the names and ids of the feature, its classes and commands, and the
names and types of the arguments. The comments of the XML are not copied; the units
that support a shared key are restated in pack.md in this repository's own words.
""" % {"fmt": ftr.fmt, "file": ftr.file, "url": XML_URL, "commit": commit, "sha": ftr.sha,
       "copy": ftr.copyright or "Parrot", "lc0": LIBARCOMMANDS[0], "lc1": LIBARCOMMANDS[1], "lc2": LIBARCOMMANDS[2],
       "lcsha": helper_shas.get("libarcommands", "not given"), "ls0": LIBARSAL[0], "ls1": LIBARSAL[1],
       "ls2": LIBARSAL[2], "lssha": helper_shas.get("libarsal", "not given")}


def run(args):
    paths = sorted(glob.glob(os.path.join(args.xml_dir, "*.xml")))
    if not paths:
        raise GenError("%s: no .xml file" % args.xml_dir)
    feats = [Feature(p) for p in paths]
    names = [f.fmt for f in feats]
    if len(set(names)) != len(names):
        raise GenError("two features with one pack name")
    for (fname, cls, cmd), b in BIND.items():
        f = next((x for x in feats if x.name == fname), None)
        if f is None:
            continue
        c = next((x for x in f.cmds if (x.cls, x.name) == (cls, cmd)), None)
        if c is None or c.why_not() or set(b) - {a.name for a in c.args}:
            raise GenError("binding %s %s %s does not match the schema" % (fname, cls, cmd))
    helper_shas = {}
    for label, path in (("libarcommands", args.libarcommands_gen), ("libarsal", args.libarsal_endianness)):
        if path:
            helper_shas[label] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    out = genio.Output(args.out, check=args.check)
    files = {}
    n_built = n_skipped = 0
    for ftr in feats:
        built = [c for c in ftr.cmds if c.why_not() is None]
        skipped = [(c, c.why_not()) for c in ftr.cmds if c.why_not()]
        n_built += len(built)
        n_skipped += len(skipped)
        if not built:
            continue
        sources = ["arsdk-xml xml/%s at commit %s (BSD-3-Clause, %s), sha256 %s: feature, class and command "
                   "ids and names, argument names and types" % (ftr.file, args.xml_commit, ftr.copyright, ftr.sha),
                   "libARCommands %s at commit %s and libARSAL %s at commit %s (BSD-3-Clause, Parrot SA): the "
                   "command header, the argument sizes and the little-endian byte order"
                   % (LIBARCOMMANDS[2], LIBARCOMMANDS[1], LIBARSAL[2], LIBARSAL[1])]
        files["model/%s.def" % ftr.module] = module_text(ftr, sources)
        dpk = "packs/%s" % ftr.fmt
        files[dpk + "/pack.def"] = pack_text(ftr, sources)
        files[dpk + "/pack.md"] = pack_md(ftr, built, skipped, args.xml_commit)
        files[dpk + "/PROVENANCE.md"] = provenance(ftr, args.xml_commit, helper_shas)
        for rel, v in vectors(ftr).items():
            v = dict(v)
            v.setdefault("source", "constructed")
            files[rel] = json.dumps(v, indent=2) + "\n"
    for rel, text in sorted(files.items()):
        out.write(rel, text)
    dirs = {"packs/%s/vectors" % f.fmt: "gen-" for f in feats}
    dirs["packs/geojson/vectors"] = "to-arsdk-"
    for dv, prefix in sorted(dirs.items()):
        for old in out.listdir(dv):
            if old.startswith(prefix) and "%s/%s" % (dv, old) not in files:
                out.remove("%s/%s" % (dv, old))
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "model"))
        for name in ("core.def", "track.def"):
            shutil.copy(os.path.join(args.model_dir, name), os.path.join(tmp, "model", name))
        packs = []
        for rel, text in files.items():
            if rel.endswith(".def"):
                path = os.path.join(tmp, *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                if rel.startswith("packs/"):
                    packs.append(path)
        gtcheck.check_output(os.path.join(tmp, "model"), sorted(packs))
    print("features        %d" % len([f for f in feats if any(c.why_not() is None for c in f.cmds)]))
    print("commands built  %d" % n_built)
    print("features with no command built: %s" % (
        " ".join(f.name for f in feats if not any(c.why_not() is None for c in f.cmds)) or "none"))
    print("not built       %d" % n_skipped)
    print("self-check      ok")
    return out.report("arsdk2pack")


def main(argv=None):
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xml-dir", required=True, help="the xml/ directory of arsdk-xml")
    genio.add_arguments(ap, default_out=here)
    ap.add_argument("--xml-commit", default="2299c689be5951fa2104793e0154b0b5b1896c03")
    ap.add_argument("--model-dir", default=os.path.join(here, "model"), help="holds core.def and track.def")
    ap.add_argument("--libarcommands-gen", default=None, help="libARCommands Tools/libARCommandsgen.py (for its SHA-256)")
    ap.add_argument("--libarsal-endianness", default=None, help="libARSAL ARSAL_Endianness.h (for its SHA-256)")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except (GenError, gtcheck.CheckError) as e:
        print("arsdk2pack: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
