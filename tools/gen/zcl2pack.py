#!/usr/bin/env python3
"""zcl2pack: Zigbee Cluster Library frames, one pack per cluster, from zigbee-herdsman.

Reads: src/zspec/zcl/definition/cluster.ts and enums.ts of a zigbee-herdsman
checkout (--herdsman), and model/core.def under --out. Writes under --out:
model/zcl.def (the frame header and the generic attribute values, shared by
every pack), model/zcl<cluster>.def, packs/<format>/pack.def, pack.md and
vectors/gen-*.json for each --cluster.

A message is one ZCL frame, the payload of an APS data frame: the frame control
byte (frame type, manufacturer-specific, direction, disable default response),
the manufacturer code when that bit is set, the transaction sequence number, the
command identifier and the command's payload, little-endian (`bits`, `layout
sequential`, `bit_order lsb`). The cluster identifier travels in the APS frame,
so the caller names the pack. The frame type and the command identifier choose
the payload through `switch` blocks:

  global commands       read attributes, its response, write attributes (three
                        forms) and its response, report attributes, default
                        response, discover attributes and its response
  cluster commands      the cluster's commands (direction 0, client to server)
                        and its responses (direction 1) whose parameters are
                        plain data types

An attribute value is read by its data type byte: one `case` per ZCL type the
pack can state. In read-attribute responses and attribute reports, an attribute
of the cluster whose data type is the one the cluster definition gives is read
into a key named after the attribute; any other into the generic value keys.

The cluster.ts file is a TypeScript object literal; it is read by a small
tokenizer and a recursive-descent parser, not by regular expressions over its
structure. Comments and the `name` members are not carried beyond the
attribute and command names. Python 3 standard library only.

Exit status: 0 done (with --check: every file is what the generator writes),
1 a refused input or a --check difference, 2 a usage error.
"""
import argparse
import json
import os
import re
import struct
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402


class GenError(Exception):
    pass


# --------------------------------------------------------------------------
# reading the TypeScript object literal
# --------------------------------------------------------------------------

TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<lc>//[^\n]*)
  | (?P<bc>/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<num>-?0[xX][0-9a-fA-F_]+|-?0[bB][01_]+|-?[0-9][0-9_]*(?:\.[0-9]+)?)
  | (?P<id>[A-Za-z_$][A-Za-z0-9_$]*)
  | (?P<p>[{}\[\]():,.<>=;?|&!*+/-])
""", re.S | re.X)


def tokens(text, label):
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise GenError("%s: cannot read the text at offset %d" % (label, pos))
        pos = m.end()
        kind = m.lastgroup
        if kind in ("ws", "lc", "bc"):
            continue
        out.append((kind, m.group(kind)))
    return out


class Parser:
    def __init__(self, toks, label):
        self.t, self.i, self.label = toks, 0, label

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise GenError("%s: expected `%s`, found `%s` (token %d)" % (self.label, value, tok[1], self.i))
        self.i += 1
        return tok

    def value(self):
        kind, v = self.peek()
        if v == "{":
            return self.obj()
        if v == "[":
            self.take("[")
            out = []
            while self.peek()[1] != "]":
                out.append(self.value())
                if self.peek()[1] == ",":
                    self.take(",")
            self.take("]")
            return out
        if kind == "str":
            self.take()
            return v[1:-1]
        if kind == "num":
            self.take()
            s = v.replace("_", "")
            return int(s, 0) if s.lower().lstrip("-")[:2] in ("0x", "0b") else (float(s) if "." in s else int(s))
        if kind == "id":
            # a dotted name (DataType.UINT8), true/false, or an expression we keep as text
            parts = [self.take()[1]]
            while self.peek()[1] == ".":
                self.take(".")
                parts.append(self.take()[1])
            name = ".".join(parts)
            if self.peek()[1] in ("|", "+", "-", "*"):
                while self.peek()[1] not in (",", "}", "]"):
                    self.take()
                return ("expr", name)
            return {"true": True, "false": False}.get(name, ("name", name))
        if v == "-":
            self.take()
            n = self.value()
            return -n
        raise GenError("%s: unexpected `%s` (token %d)" % (self.label, v, self.i))

    def obj(self):
        self.take("{")
        out = {}
        while self.peek()[1] != "}":
            kind, k = self.take()
            if kind == "str":
                k = k[1:-1]
            elif kind == "p" and k == "[":
                raise GenError("%s: computed keys are not read" % self.label)
            self.take(":")
            out[str(k)] = self.value()
            if self.peek()[1] == ",":
                self.take(",")
        self.take("}")
        return out


def read_clusters(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    label = os.path.basename(path)
    toks = tokens(text, label)
    i = next((n for n in range(len(toks) - 2) if toks[n][1] == "Clusters" and toks[n + 1][1] == ":"), None)
    if i is None:
        raise GenError("%s: no `Clusters` object" % label)
    while toks[i][1] != "=":
        i += 1
    p = Parser(toks, label)
    p.i = i + 1
    return p.obj()


def read_datatypes(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    start = text.find("export enum DataType {")
    if start < 0:
        raise GenError("enums.ts: no DataType enum")
    body = text[start:text.find("}", start)]
    out = {}
    for line in body.split("\n"):
        m = re.match(r"\s*([A-Z0-9_]+) = (0x[0-9a-fA-F]+|[0-9]+),", line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if "UINT8" not in out:
        raise GenError("enums.ts: the DataType enum has no UINT8")
    return out


# --------------------------------------------------------------------------
# the layout of a value of each data type (this repository's restatement)
# --------------------------------------------------------------------------

def value_layout(tname):
    """(form, bits, transform) for a data type name, or None when the pack cannot state it."""
    m = re.fullmatch(r"(DATA|BITMAP|UINT)(\d+)", tname)
    if m:
        return ("uint", int(m.group(2)), "uint")
    m = re.fullmatch(r"INT(\d+)", tname)
    if m:
        return ("int", int(m.group(1)), "twos")
    table = {"BOOLEAN": ("uint", 8, "uint"), "ENUM8": ("uint", 8, "uint"), "ENUM16": ("uint", 16, "uint"),
             "SEMI_PREC": ("uint", 16, "uint"), "SINGLE_PREC": ("float", 32, "f32"),
             "DOUBLE_PREC": ("float", 64, "f64"), "OCTET_STR": ("bytes", 8, None), "CHAR_STR": ("bytes", 8, None),
             "LONG_OCTET_STR": ("bytes", 16, None), "LONG_CHAR_STR": ("bytes", 16, None),
             "TOD": ("uint", 32, "uint"), "DATE": ("uint", 32, "uint"), "UTC": ("uint", 32, "uint"),
             "CLUSTER_ID": ("uint", 16, "uint"), "ATTR_ID": ("uint", 16, "uint"), "BAC_OID": ("uint", 32, "uint"),
             "IEEE_ADDR": ("uint", 64, "uint"), "SEC_KEY": ("key", 128, None), "NO_DATA": ("none", 0, None)}
    return table.get(tname)


def snake(name):
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()


class Keys:
    def __init__(self):
        self.mods = {}     # module -> {name: (type, meaning)} ; lists have type "list"

    def add(self, mod, name, typ, meaning):
        d = self.mods.setdefault(mod, {})
        if name in d and d[name][0] != typ:
            raise GenError("key %s.%s made twice with different types" % (mod, name))
        d.setdefault(name, (typ, meaning))
        return "%s.%s" % (mod, name)


def value_lines(keys, mod, prefix, layout, what):
    """Lines that read one value of `layout` into keys of `mod` named from `prefix`."""
    form, bits, tr = layout
    if form == "none":
        return []
    if form == "bytes":
        lst = keys.add(mod, prefix, "list", "the bytes of %s" % what)
        return [("group", lst, [("field", keys.add(mod, prefix + "_byte", "int", "one byte of %s" % what), 8, "uint")],
                 "count %d" % bits)]
    if form == "key":
        return [("field", keys.add(mod, prefix + "_low", "int", "%s, the first 8 bytes" % what), 64, "uint"),
                ("field", keys.add(mod, prefix + "_high", "int", "%s, the last 8 bytes" % what), 64, "uint")]
    typ = "float" if form == "float" else "int"
    return [("field", keys.add(mod, prefix, typ, what), bits, tr)]


def type_cases(keys, prefix, types, named=None):
    """A switch on the data type key: one case per type the pack states. `named` maps a type
    code to [(attribute id, lines)]: inside that type's case a switch on the attribute id reads
    a cluster attribute of that type into its own key, any other id into the generic key."""
    cases = []
    for tname, code in sorted(types.items(), key=lambda kv: kv[1]):
        lay = value_layout(tname)
        if lay is None:
            continue
        form = lay[0]
        suffix = {"uint": "value_uint", "int": "value_int", "float": "value_float", "bytes": "value_bytes",
                  "key": "value_key", "none": None}[form]
        generic = [] if suffix is None else value_lines(keys, "zcl", prefix + "_" + suffix, lay,
                                                        "an attribute value (%s)" % form)
        if named and named[1].get(code):
            cases.append((code, [("switch", named[0], named[1][code], generic)]))
        else:
            cases.append((code, generic))
    return cases


def generic_switch(keys, dtkey, prefix, types):
    return ("switch", dtkey, type_cases(keys, prefix, types), None)


def named_switch(keys, mod, cluster, attrkey, dtkey, prefix, types):
    """The value of a record whose attribute id key is `attrkey`: by its data type, and inside a
    type, by the attribute id for the cluster's attributes of that type."""
    by_type = {}
    for aname, a in sorted(cluster.get("attributes", {}).items(), key=lambda kv: kv[1]["ID"]):
        t = a.get("type")
        if not (isinstance(t, tuple) and t[1].startswith("DataType.")):
            continue
        tname = t[1].split(".", 1)[1]
        lay = value_layout(tname)
        if lay is None or lay[0] == "none" or tname not in types:
            continue
        body = value_lines(keys, mod, snake(aname), lay, "attribute %s of %s (%s)" % (aname, cluster["name"], tname))
        by_type.setdefault(types[tname], []).append((a["ID"], body))
    return ("switch", dtkey, type_cases(keys, prefix, types, (attrkey, by_type)), None)


def global_commands(keys, mod, cluster, types):
    k = lambda name, meaning, typ="int": keys.add("zcl", name, typ, meaning)
    cases = []
    # 0x00 read attributes
    cases.append((0x00, [("group", keys.add("zcl", "read_attributes", "list", "attribute ids of a read attributes command"),
                          [("field", k("read_attribute_id", "an attribute id to read"), 16, "uint")], "rest")]))
    # 0x01 read attributes response
    rid, rst, rdt = k("read_rsp_attribute_id", "attribute id of a read attributes response record"), \
        k("read_rsp_status", "status of the record, 0 success"), k("read_rsp_data_type", "data type of the value")
    cases.append((0x01, [("group", keys.add("zcl", "read_rsp_records", "list", "records of a read attributes response"), [
        ("field", rid, 16, "uint"), ("field", rst, 8, "uint"),
        ("switch", rst, [(0, [("field", rdt, 8, "uint"), named_switch(keys, mod, cluster, rid, rdt, "read_rsp", types)])], [])],
        "rest")]))
    # 0x02, 0x03, 0x05 write attributes
    wid, wdt = k("write_attribute_id", "attribute id of a write attributes record"), k("write_data_type", "data type of the value")
    wlist = keys.add("zcl", "write_records", "list", "records of a write attributes command")
    body = [("group", wlist, [("field", wid, 16, "uint"), ("field", wdt, 8, "uint"),
                              generic_switch(keys, wdt, "write", types)], "rest")]
    for cid in (0x02, 0x03, 0x05):
        cases.append((cid, body))
    # 0x04 write attributes response
    cases.append((0x04, [("group", keys.add("zcl", "write_rsp_records", "list", "records of a write attributes response"), [
        ("field", k("write_rsp_status", "status of the record"), 8, "uint"),
        ("field", k("write_rsp_attribute_id", "attribute id the status is for"), 16, "uint")], "rest")]))
    # 0x0a report attributes
    pid, pdt = k("report_attribute_id", "attribute id of a report record"), k("report_data_type", "data type of the value")
    cases.append((0x0a, [("group", keys.add("zcl", "report_records", "list", "records of a report attributes command"), [
        ("field", pid, 16, "uint"), ("field", pdt, 8, "uint"), named_switch(keys, mod, cluster, pid, pdt, "report", types)],
        "rest")]))
    # 0x0b default response
    cases.append((0x0b, [("field", k("default_rsp_command_id", "the command the default response answers"), 8, "uint"),
                         ("field", k("default_rsp_status", "its status, 0 success"), 8, "uint")]))
    # 0x0c discover attributes, 0x0d its response
    cases.append((0x0c, [("field", k("discover_start_attribute_id", "first attribute id to discover"), 16, "uint"),
                         ("field", k("discover_max_attributes", "most attribute ids to return"), 8, "uint")]))
    cases.append((0x0d, [("field", k("discover_rsp_complete", "1 when no more attributes remain"), 8, "uint"),
                         ("group", keys.add("zcl", "discover_rsp_records", "list", "records of a discover attributes response"), [
                             ("field", k("discover_rsp_attribute_id", "an attribute id"), 16, "uint"),
                             ("field", k("discover_rsp_data_type", "its data type"), 8, "uint")], "rest")]))
    return cases


def cluster_commands(keys, mod, cluster, which, types, skipped):
    cases = []
    for cname, c in sorted(cluster.get(which, {}).items(), key=lambda kv: kv[1]["ID"]):
        body, ok = [], True
        for prm in c.get("parameters", []):
            t = prm.get("type")
            tname = t[1].split(".", 1)[1] if isinstance(t, tuple) and t[1].startswith("DataType.") else None
            lay = value_layout(tname) if tname else None
            if lay is None or lay[0] == "none" or "conditions" in prm:
                skipped.append(("%s %s" % (which[:-1] if which.endswith("s") else which, cname),
                                "parameter %s: %s" % (prm.get("name"), "conditional" if "conditions" in prm else
                                                       (t[1] if isinstance(t, tuple) else t))))
                ok = False
                break
            body += value_lines(keys, mod, "%s_%s" % (snake(cname), snake(prm["name"])), lay,
                                "parameter %s of command %s" % (prm["name"], cname))
        if ok:
            cases.append((c["ID"], body))
    return cases


def pack_lines(keys, mod, cluster, types, skipped):
    k = lambda name, meaning: keys.add("zcl", name, "int", meaning)
    ft, dr, cid = k("frame_type", "0 global (profile-wide) command, 1 cluster-specific command"), \
        k("direction", "0 client to server, 1 server to client"), k("command_id", "command identifier")
    return [("field", ft, 2, "uint"), ("presence", "fc", 1), ("field", dr, 1, "uint"),
            ("field", k("disable_default_response", "1 when no default response is wanted"), 1, "uint"),
            ("field", k("frame_control_reserved", "frame control bits 5-7, reserved"), 3, "uint"),
            ("if", "fc.1", [("field", k("manufacturer_code", "manufacturer code of a manufacturer-specific frame"), 16, "uint")]),
            ("field", k("transaction_sequence", "transaction sequence number"), 8, "uint"),
            ("field", cid, 8, "uint"),
            ("switch", ft, [
                (0, [("switch", cid, global_commands(keys, mod, cluster, types), None)]),
                (1, [("switch", dr, [(0, [("switch", cid, cluster_commands(keys, mod, cluster, "commands", types, skipped), None)]),
                                     (1, [("switch", cid, cluster_commands(keys, mod, cluster, "commandsResponse", types, skipped), None)])],
                      None)])], None)]


def emit(lines, ind, out):
    sp = "  " * ind
    for ln in lines:
        k = ln[0]
        if k == "field":
            out.append("%sfield  %s  %d  %s" % (sp, ln[1], ln[2], ln[3]))
        elif k == "presence":
            out.append("%spresence  %s  %d" % (sp, ln[1], ln[2]))
        elif k == "if":
            out.append("%sif  %s" % (sp, ln[1]))
            emit(ln[2], ind + 1, out)
            out.append(sp + "end")
        elif k == "count":
            out.append("%scount  %s  %d" % (sp, ln[1], ln[2]))
        elif k == "group":
            mode = ln[3]
            out.append("%sgroup  %s  %s" % (sp, ln[1], mode))
            emit(ln[2], ind + 1, out)
            out.append(sp + "end")
        elif k == "switch":
            if not ln[2] and ln[3] is None:
                continue
            out.append("%sswitch  %s" % (sp, ln[1]))
            for v, body in ln[2]:
                out.append("%s  case  %d" % (sp, v))
                emit(body, ind + 2, out)
            if ln[3] is not None:
                out.append("%s  else" % sp)
                emit(ln[3], ind + 2, out)
            out.append(sp + "end")


# --------------------------------------------------------------------------
# vectors: frames written by a ZCL frame writer, independent of the pack lines
# --------------------------------------------------------------------------

def write_value(tname, v):
    form, bits, _ = value_layout(tname)
    if form == "bytes":
        return (struct.pack("<B", len(v)) if bits == 8 else struct.pack("<H", len(v))) + v
    if form == "float":
        return struct.pack("<f" if bits == 32 else "<d", v)
    if form == "int":
        return (v & ((1 << bits) - 1)).to_bytes(bits // 8, "little")
    return v.to_bytes(bits // 8, "little")


def header(frame_type, direction, seq, cid, manuf=None, ddr=1):
    fc = frame_type | (4 if manuf is not None else 0) | (direction << 3) | (ddr << 4)
    out = bytes([fc]) + (struct.pack("<H", manuf) if manuf is not None else b"") + bytes([seq, cid])
    m = {"zcl.frame_type": frame_type, "zcl.direction": direction, "zcl.disable_default_response": ddr,
         "zcl.frame_control_reserved": 0, "zcl.transaction_sequence": seq, "zcl.command_id": cid}
    if manuf is not None:
        m["zcl.manufacturer_code"] = manuf
    return out, {k: str(v) for k, v in m.items()}


def sample(tname, n):
    form, bits, _ = value_layout(tname)
    if form == "bytes":
        return ("v%d" % n).encode()
    if form == "float":
        return n + 0.5
    if form == "int":
        return -(n % 100) - 1
    if tname == "BOOLEAN":
        return 1
    return (n * 7 + 3) % (1 << min(bits, 16))


def value_model(mod, prefix, tname, v, base):
    form, bits, _ = value_layout(tname)
    if form == "bytes":
        out = {"%s%s.%s.#" % (base, mod, prefix): str(len(v))}
        for i, b in enumerate(v):
            out["%s%s.%s[%d].%s.%s_byte" % (base, mod, prefix, i, mod, prefix)] = str(b)
        return out
    return {"%s%s.%s" % (base, mod, prefix): (repr(v) if isinstance(v, float) else str(v))}


def vectors(fmt, mod, cluster, types):
    files = []
    attrs = [(n, a) for n, a in sorted(cluster.get("attributes", {}).items(), key=lambda kv: kv[1]["ID"])
             if isinstance(a.get("type"), tuple) and a["type"][1].startswith("DataType.")
             and (value_layout(a["type"][1].split(".", 1)[1]) or ("none",))[0] not in ("none", "key")]
    named = attrs[:2]
    # report attributes: two named attributes and one id the cluster does not define (generic uint16)
    hdr, m = header(0, 1, 0x21, 0x0a)
    body = b""
    recs = []
    for i, (aname, a) in enumerate(named):
        tname = a["type"][1].split(".", 1)[1]
        v = sample(tname, i + 1)
        body += struct.pack("<HB", a["ID"], types[tname]) + write_value(tname, v)
        recs.append(("named", aname, a["ID"], tname, v))
    unknown = 0xfff0
    body += struct.pack("<HB", unknown, types["UINT16"]) + write_value("UINT16", 4660)
    recs.append(("generic", None, unknown, "UINT16", 4660))
    model = dict(m)
    model["zcl.report_records.#"] = str(len(recs))
    for i, (how, aname, aid, tname, v) in enumerate(recs):
        base = "zcl.report_records[%d]." % i
        model[base + "zcl.report_attribute_id"] = str(aid)
        model[base + "zcl.report_data_type"] = str(types[tname])
        if how == "named":
            model.update(value_model(mod, snake(aname), tname, v, base))
        else:
            model.update(value_model("zcl", "report_value_uint", tname, v, base))
    files.append(("gen-01-report-attributes.json", hdr + body, model, "report attributes: two attributes of the cluster and one id it does not define"))
    # read attributes response: one success, one unsupported attribute (status 0x86)
    hdr, m = header(0, 1, 0x22, 0x01)
    aname, a = named[0]
    tname = a["type"][1].split(".", 1)[1]
    v = sample(tname, 5)
    body = struct.pack("<HBB", a["ID"], 0, types[tname]) + write_value(tname, v) + struct.pack("<HB", 0x1234, 0x86)
    model = dict(m)
    model["zcl.read_rsp_records.#"] = "2"
    b0 = "zcl.read_rsp_records[0]."
    model.update({b0 + "zcl.read_rsp_attribute_id": str(a["ID"]), b0 + "zcl.read_rsp_status": "0",
                  b0 + "zcl.read_rsp_data_type": str(types[tname])})
    model.update(value_model(mod, snake(aname), tname, v, b0))
    model.update({"zcl.read_rsp_records[1].zcl.read_rsp_attribute_id": "4660", "zcl.read_rsp_records[1].zcl.read_rsp_status": "134"})
    files.append(("gen-02-read-attributes-response.json", hdr + body, model, "a success record and a status-only record"))
    # read attributes, manufacturer-specific header
    hdr, m = header(0, 0, 0x23, 0x00, manuf=0x115f, ddr=0)
    body = struct.pack("<HH", 0x0000, 0x0005)
    model = dict(m)
    model.update({"zcl.read_attributes.#": "2", "zcl.read_attributes[0].zcl.read_attribute_id": "0",
                  "zcl.read_attributes[1].zcl.read_attribute_id": "5"})
    files.append(("gen-03-read-attributes-manufacturer.json", hdr + body, model, "manufacturer-specific frame with a manufacturer code"))
    # default response
    hdr, m = header(0, 1, 0x24, 0x0b)
    model = dict(m, **{"zcl.default_rsp_command_id": "2", "zcl.default_rsp_status": "0"})
    files.append(("gen-04-default-response.json", hdr + bytes([2, 0]), model, "default response"))
    # a cluster command with parameters, if there is one the pack carries
    for which, direction in (("commands", 0), ("commandsResponse", 1)):
        for cname, c in sorted(cluster.get(which, {}).items(), key=lambda kv: kv[1]["ID"]):
            prms = c.get("parameters", [])
            ok = all(isinstance(p.get("type"), tuple) and p["type"][1].startswith("DataType.")
                     and value_layout(p["type"][1].split(".", 1)[1]) not in (None,)
                     and value_layout(p["type"][1].split(".", 1)[1])[0] not in ("none", "key") and "conditions" not in p
                     for p in prms)
            if not ok:
                continue
            hdr, m = header(1, direction, 0x30 + direction, c["ID"])
            body, model = b"", dict(m)
            for i, prm in enumerate(prms):
                tname = prm["type"][1].split(".", 1)[1]
                v = sample(tname, 10 + i)
                body += write_value(tname, v)
                model.update(value_model(mod, "%s_%s" % (snake(cname), snake(prm["name"])), tname, v, ""))
            files.append(("gen-%02d-%s.json" % (5 + direction, snake(cname).replace("_", "-")), hdr + body, model,
                          "cluster command %s (%s)" % (cname, "client to server" if direction == 0 else "server to client")))
            break
    out = []
    for name, data, model, note in files:
        out.append((name, {"name": "%s-%s" % (fmt, name[:-5]), "from": fmt, "to": fmt,
                           "input": data.hex(), "expect": data.hex(), "model": model,
                           "source": "constructed", "reference": "tools/gen/zcl2pack.py: frame bytes by its ZCL frame writer; " + note}))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="zcl2pack", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    genio.add_arguments(p)
    p.add_argument("--herdsman", required=True, help="a zigbee-herdsman checkout")
    p.add_argument("--cluster", action="append", required=True, metavar="NAME=FORMAT",
                   help="a cluster of cluster.ts and the pack name, e.g. genOnOff=zcl-on-off")
    p.add_argument("--source", action="append", required=True)
    p.add_argument("--notes-file")
    a = p.parse_args(argv)
    d = os.path.join(a.herdsman, "src", "zspec", "zcl", "definition")
    try:
        clusters = read_clusters(os.path.join(d, "cluster.ts"))
        types = read_datatypes(os.path.join(d, "enums.ts"))
        keys = Keys()
        packs = []
        for spec in a.cluster:
            cname, fmt = spec.split("=", 1)
            if cname not in clusters:
                raise GenError("cluster.ts has no cluster %s" % cname)
            cl = clusters[cname]
            mod = "zcl" + snake(cname).replace("_", "")
            skipped = []
            lines = pack_lines(keys, mod, cl, types, skipped)
            out = ["# Zigbee Cluster Library frames of cluster %s (0x%04x), as zigbee-herdsman defines it." % (cname, cl["ID"]),
                   "# Generated by tools/gen/zcl2pack.py; do not edit by hand. What is not mapped: pack.md.",
                   "format        %s" % fmt, "version       0.1.0", "distribution  public"]
            out += ["source        %s" % json.dumps(s) for s in a.source]
            uses = ["zcl"] + ([mod] if mod in keys.mods else [])
            out += ["uses          %s" % u for u in uses]
            out += ["wire          bits", "layout        sequential", "bit_order     lsb"]
            emit(lines, 0, out)
            packs.append((cname, fmt, mod, cl, "\n".join(out) + "\n", skipped))

        def mtext(mod, title):
            m = ["# %s Generated by tools/gen/zcl2pack.py; do not edit by hand." % title,
                 "module        %s" % mod, "version       0.1.0", "distribution  public"]
            m += ["source        %s" % json.dumps(s) for s in a.source]
            for name, (typ, meaning) in sorted(keys.mods[mod].items()):
                if typ == "list":
                    m.append("list  %s  %s" % (name, json.dumps(meaning)))
                else:
                    m.append("key   %s  %s  -  %s" % (name, typ, json.dumps(meaning)))
            return "\n".join(m) + "\n"

        model = gtcheck.Model()
        with open(os.path.join(a.out, "model", "core.def"), encoding="utf-8") as fh:
            model.add(fh.read(), "model/core.def")
        mods = {"zcl": mtext("zcl", "ZCL frame header and generic attribute values, shared by every zcl-* pack.")}
        model.add(mods["zcl"], "model/zcl.def")
        for cname, fmt, mod, cl, ptext, skipped in packs:
            if mod in keys.mods:
                mods[mod] = mtext(mod, "Attributes and command parameters of ZCL cluster %s." % cname)
                model.add(mods[mod], "model/%s.def" % mod)
        for cname, fmt, mod, cl, ptext, skipped in packs:
            gtcheck.load_pack(ptext, model, label="packs/%s/pack.def" % fmt)
    except (GenError, gtcheck.CheckError) as e:
        print("zcl2pack: %s" % e, file=sys.stderr)
        return 1
    o = genio.Output(a.out, check=a.check)
    for mod, text in sorted(mods.items()):
        o.write("model/%s.def" % mod, text)
    notes = ""
    if a.notes_file:
        with open(a.notes_file, encoding="utf-8") as fh:
            notes = fh.read().rstrip("\n") + "\n"
    for cname, fmt, mod, cl, ptext, skipped in packs:
        base = "packs/%s/" % fmt
        o.write(base + "pack.def", ptext)
        attrs = sorted(cl.get("attributes", {}).items(), key=lambda kv: kv[1]["ID"])
        md = ["# %s" % fmt, "",
              "Generated by `tools/gen/zcl2pack.py`; do not edit by hand. Zigbee Cluster Library frames of the",
              "cluster `%s` (cluster id 0x%04x) as zigbee-herdsman defines it: %d attributes, %d commands and"
              % (cname, cl["ID"], len(attrs), len(cl.get("commands", {}))),
              "%d command responses in the definition." % len(cl.get("commandsResponse", {})), ""]
        if skipped:
            md += ["## Cluster commands not built", "", "| Command | Reason |", "|---|---|"]
            md += ["| %s | %s |" % s for s in skipped] + [""]
        md.append(notes)
        o.write(base + "pack.md", "\n".join(md))
        vecs = vectors(fmt, mod, cl, {k: v for k, v in read_datatypes(os.path.join(d, "enums.ts")).items()})
        names = {n for n, _ in vecs}
        for n in o.listdir(base + "vectors"):
            if n.startswith("gen-") and n not in names:
                o.remove(base + "vectors/" + n)
        for n, v in vecs:
            o.write(base + "vectors/" + n, json.dumps(v, indent=2) + "\n")
    return o.report("zcl2pack")


if __name__ == "__main__":
    sys.exit(main())
