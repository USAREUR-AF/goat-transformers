#!/usr/bin/env python3
"""protojson2pack: a `json` pack for the proto3 JSON form of a protobuf message.

Reads: the .proto files (--proto, parsed by tools/gen/proto2pack.py's reader),
model/core.def under --out, and the notes file. Writes under --out:
model/<module>.def, packs/<format>/pack.def, pack.md and
vectors/gen-*.json (every gen-*.json there is replaced).

The proto3 JSON mapping, as the pack states it (the member name is the field's
lowerCamelCase JSON name):

  string                      `string`
  bool                        `bool`
  int32, uint32, sint32, fixed32, sfixed32, enums    `int` (enums as their number)
  int64, uint64, sint64, fixed64, sfixed64           `string`: the mapping writes them as
                                                     decimal text, so the key is the text
  double, float               `float`
  bytes                       `string`: base64 text, or hex text for the fields --hex-bytes
                              names (OTLP writes trace and span identifiers as hex)
  a message                   a nested object
  repeated                    an array: a `group` (scalar items through `.`)

A message type that would stand inside itself is not descended. Map fields are
not carried. Every field is a raw key of --module; nothing binds a shared key.

Guarantees: the same input gives the same bytes. A refused input writes
nothing. What was written is loaded with gtcheck. Each generated vector is a
message built from the schema (one value per field, the first member of each
oneof, two items in each first-level array and one deeper) and written as the
canonical text of the json wire (members in field-line order, which is field
declaration order here; no whitespace), with the model it decodes to.

Exit status: 0 done (with --check: every file is what the generator writes),
1 a refused input or a --check difference, 2 a usage error. Standard library only.
"""
import argparse
import base64
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio      # noqa: E402
import gtcheck    # noqa: E402
import proto2pack  # noqa: E402

INT32 = {"int32", "uint32", "sint32", "fixed32", "sfixed32"}
INT64 = {"int64", "uint64", "sint64", "fixed64", "sfixed64"}


def json_name(name):
    out, up = [], False
    for ch in name:
        if ch == "_":
            up = True
        elif up:
            out.append(ch.upper())
            up = False
        else:
            out.append(ch)
    return "".join(out)


class Plan:
    def __init__(self, module, hex_names, max_depth):
        self.module, self.hex_names, self.max_depth = module, set(hex_names), max_depth
        self.keys, self.lists, self.skipped = {}, {}, []

    def key(self, name, typ, meaning):
        if name in self.lists or (name in self.keys and self.keys[name][0] != typ):
            raise proto2pack.GenError("key name %s made twice" % name)
        self.keys.setdefault(name, (typ, meaning))
        return self.module + "." + name

    def lst(self, name, meaning):
        if name in self.keys:
            raise proto2pack.GenError("list name %s is also a key" % name)
        self.lists.setdefault(name, meaning)
        return self.module + "." + name

    def scalar(self, f):
        """(transform, model type) of a scalar or enum field."""
        if f.kind == "enum" or f.type in INT32:
            return "int", "int"
        if f.type in INT64 or f.type == "string" or f.type == "bytes":
            return "string", "string"
        if f.type == "bool":
            return "bool", "int"
        if f.type in ("double", "float"):
            return "float", "float"
        raise proto2pack.GenError("type %s has no JSON form here" % f.type)

    def message(self, msg, path, name, chain, depth):
        """Lines of message `msg` at member path `path` (list of JSON names), keys from `name`."""
        lines = []
        for f in msg.fields:
            jn = json_name(f.name)
            p = path + [jn]
            n = name + "_" + proto2pack.snake(f.name) if name else proto2pack.snake(f.name)
            where = "%s.%s" % (msg.full, f.name)
            if f.kind == "map":
                self.skipped.append((where, "a map field"))
                continue
            if f.kind == "group":
                self.skipped.append((where, "a proto2 group"))
                continue
            if f.kind == "message":
                if f.ref in chain:
                    self.skipped.append((where, "the type stands inside itself"))
                    continue
                if depth >= self.max_depth:
                    self.skipped.append((where, "deeper than --max-depth"))
                    continue
                if f.label == "repeated":
                    lst = self.lst(n, "the items of %s" % where)
                    lines.append(("group", lst, ".".join(p), self.message(f.ref, [], n, chain + [f.ref], depth + 1)))
                else:
                    lines += self.message(f.ref, p, n, chain + [f.ref], depth + 1)
                continue
            tr, typ = self.scalar(f)
            what = where + (" (hex text)" if f.type == "bytes" and f.name in self.hex_names else
                            " (base64 text)" if f.type == "bytes" else
                            " (decimal text)" if f.type in INT64 else "")
            if f.label == "repeated":
                lst = self.lst(n, "the items of %s" % where)
                lines.append(("group", lst, ".".join(p), [("field", self.key(n + "_item", typ, what), ".", tr)]))
            else:
                lines.append(("field", self.key(n, typ, what), ".".join(p), tr))
        return lines


def emit(lines, ind, out):
    sp = "  " * ind
    for ln in lines:
        if ln[0] == "field":
            out.append("%sfield  %s  %s  %s" % (sp, ln[1], ln[2], ln[3]))
        else:
            out.append("%sgroup  %s  %s" % (sp, ln[1], ln[2]))
            emit(ln[3], ind + 1, out)
            out.append(sp + "end")


class Sample:
    """A message built from the schema, as proto3 JSON, and the model it decodes to."""

    def __init__(self, plan):
        self.plan, self.n = plan, 0

    def nxt(self):
        self.n += 1
        return self.n

    def scalar(self, f):
        n = self.nxt()
        if f.kind == "enum":
            vals = [v for _, v in f.ref.values]
            return vals[n % len(vals)] if vals else 0
        if f.type in INT32:
            return (n % 1000) + 1
        if f.type in INT64:
            return str(1700000000000000000 + n)
        if f.type == "string":
            return "s%d" % n
        if f.type == "bytes":
            raw = bytes((n + i) % 256 for i in range(4))
            return raw.hex() if f.name in self.plan.hex_names else base64.b64encode(raw).decode("ascii")
        if f.type == "bool":
            return n % 2 == 1
        return n + 0.5

    def message(self, msg, name, chain, depth, ent, items):
        """(json object, model entries into `ent`); `items` is the array length at this depth."""
        obj = {}
        seen_oneof = set()
        for f in msg.fields:
            n = name + "_" + proto2pack.snake(f.name) if name else proto2pack.snake(f.name)
            if f.kind in ("map", "group"):
                continue
            if f.kind == "message" and (f.ref in chain or depth >= self.plan.max_depth):
                continue
            if f.oneof:
                if f.oneof in seen_oneof:
                    continue
                seen_oneof.add(f.oneof)
            jn = json_name(f.name)
            key = self.plan.module + "." + n
            if f.kind == "message":
                if f.label == "repeated":
                    arr, lst = [], []
                    for _ in range(items):
                        it = {"keys": {}, "lists": {}}
                        arr.append(self.message(f.ref, n, chain + [f.ref], depth + 1, it, 1))
                        lst.append(it)
                    obj[jn] = arr
                    ent["lists"][key] = lst
                else:
                    sub = self.message(f.ref, n, chain + [f.ref], depth + 1, ent, items)
                    if sub:
                        obj[jn] = sub
                continue
            if f.label == "repeated":
                vals = [self.scalar(f) for _ in range(items)]
                obj[jn] = vals
                ent["lists"][key] = [{"keys": {key + "_item": v}, "lists": {}} for v in vals]
            else:
                v = self.scalar(f)
                obj[jn] = v
                ent["keys"][key] = v
        return obj


def text(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else repr(v)
    return str(v)


def model_strings(ent, prefix=""):
    out = {}
    for k, v in ent["keys"].items():
        out[prefix + k] = text(v)
    for name, items in ent["lists"].items():
        out[prefix + name + ".#"] = str(len(items))
        for i, it in enumerate(items):
            out.update(model_strings(it, "%s%s[%d]." % (prefix, name, i)))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="protojson2pack", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    genio.add_arguments(p)
    p.add_argument("--proto", nargs="+", required=True)
    p.add_argument("--envelope", required=True)
    p.add_argument("--format", required=True)
    p.add_argument("--module", required=True)
    p.add_argument("--source", action="append", required=True)
    p.add_argument("--hex-bytes", action="append", default=[], metavar="FIELD",
                   help="a bytes field of this name is hex text, not base64")
    p.add_argument("--max-depth", type=int, default=12)
    p.add_argument("--notes-file")
    p.add_argument("--pack-version", default="0.1.0")
    args = p.parse_args(argv)
    try:
        schema = proto2pack.load_schema(args.proto, comments=False)
        env = schema.messages.get(args.envelope)
        if env is None:
            raise proto2pack.GenError("no message %s in the given files" % args.envelope)
        plan = Plan(args.module, args.hex_bytes, args.max_depth)
        lines = plan.message(env, [], "", [env], 0)
        if not lines:
            raise proto2pack.GenError("%s has no field the pack can carry" % args.envelope)
        out = ["# The proto3 JSON form of %s. Generated by tools/gen/protojson2pack.py;" % args.envelope,
               "# do not edit by hand. What is not mapped: pack.md.",
               "format        %s" % args.format, "version       %s" % args.pack_version, "distribution  public"]
        out += ["source        %s" % json.dumps(s) for s in args.source]
        out += ["uses          %s" % args.module, "wire          json"]
        emit(lines, 0, out)
        ptext = "\n".join(out) + "\n"
        mod = ["# Raw keys of the proto3 JSON form of %s. Generated by tools/gen/protojson2pack.py." % args.envelope,
               "module        %s" % args.module, "version       %s" % args.pack_version, "distribution  public"]
        mod += ["source        %s" % json.dumps(s) for s in args.source]
        for k in sorted(plan.keys):
            typ, meaning = plan.keys[k]
            mod.append("key   %s  %s  -  %s" % (k, typ, json.dumps("field " + meaning)))
        for k in sorted(plan.lists):
            mod.append("list  %s  %s" % (k, json.dumps(plan.lists[k])))
        mtext = "\n".join(mod) + "\n"
        model = gtcheck.Model()
        with open(os.path.join(args.out, "model", "core.def"), encoding="utf-8") as fh:
            model.add(fh.read(), "model/core.def")
        model.add(mtext, "model/%s.def" % args.module)
        gtcheck.load_pack(ptext, model, label="packs/%s/pack.def" % args.format)
        ent = {"keys": {}, "lists": {}}
        msg = Sample(plan).message(env, "", [env], 0, ent, 2)
        body = json.dumps(msg, separators=(",", ":"), ensure_ascii=False)
        vec = {"name": "gen-%s-roundtrip" % args.format, "from": args.format, "to": args.format,
               "source": "tools/gen/protojson2pack.py: a message built from the schema, in canonical json text",
               "input": body, "expect": body, "model": model_strings(ent)}
    except (proto2pack.GenError, gtcheck.CheckError) as e:
        print("protojson2pack: %s" % e, file=sys.stderr)
        return 1
    o = genio.Output(args.out, check=args.check)
    o.write("model/%s.def" % args.module, mtext)
    base = "packs/%s/" % args.format
    o.write(base + "pack.def", ptext)
    md = ["# %s" % args.format, "",
          "Generated by `tools/gen/protojson2pack.py`; do not edit by hand. The proto3 JSON form of",
          "`%s`: %d raw keys and %d lists of module `%s`. No field binds a shared key."
          % (args.envelope, len(plan.keys), len(plan.lists), args.module), "",
          "## How the JSON mapping is stated", "",
          "Member names are the lowerCamelCase JSON names of the fields. 64-bit integers are decimal text in",
          "the mapping and are carried as text (`string`), so a writer that sends them as JSON numbers is",
          "`transform-decode`. `bytes` are text: hex for %s, base64 otherwise. Enums are their numbers."
          % (", ".join("`%s`" % h for h in args.hex_bytes) or "no field"),
          "`NaN` and `Infinity` written as text for a `double` are `transform-decode`.", "",
          "## Not mapped", ""]
    md += ["| Field | Reason |", "|---|---|"] + ["| `%s` | %s (%d places) |" % (w, r, plan.skipped.count((w, r))) for w, r in sorted(set(plan.skipped))] if plan.skipped else ["(nothing)"]
    md += ["", "Everything inside an array that no line maps is dropped (items carry no residue); scalar members",
           "outside arrays that no line maps are residue.", "",
           "## Generated vector", "",
           "`vectors/gen-01-roundtrip.json`: a message built from the schema, one value per field, the first",
           "member of each oneof, two items in each first-level array and one deeper, in canonical text.", ""]
    if args.notes_file:
        with open(args.notes_file, encoding="utf-8") as fh:
            md += [fh.read().rstrip("\n"), ""]
    o.write(base + "pack.md", "\n".join(md))
    for n in o.listdir(base + "vectors"):
        if n.startswith("gen-") and n != "gen-01-roundtrip.json":
            o.remove(base + "vectors/" + n)
    o.write(base + "vectors/gen-01-roundtrip.json", json.dumps(vec, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"format": args.format, "keys": len(plan.keys), "lists": len(plan.lists),
                      "not_mapped": len(plan.skipped)}))
    return o.report("protojson2pack")


if __name__ == "__main__":
    sys.exit(main())
