#!/usr/bin/env python3
"""Write the vectors of spec 0.18, conditional output and flag tokens: the
packs `conformance-cond-*`, the 0.18 vectors of `conformance-derive-functions`
(from 78) and the load vectors from 680.

Every expected value here is worked out by hand from the spec text (Version
0.18 and its rulings 1 to 23, and the sections they refer to: 0.5 json
canonical output, 0.6 defaults, several lines for one key and the order
inside `convert`, 0.7 groups and ruling 11, 0.8 presence, `opt`, chains and
ruling 2, 0.9 sentinels and ruling 16, 0.10 Writing a record, 0.13 Writing a
message, 0.14 the armor alphabet and `L`, 0.17 Encode steps 1 to 6 and
ruling 14) and the pack
layouts; the hand working is the comment above each vector and the value is
written out literally. It is checked against a second computation: the small
codecs below read the committed pack.def files and model/probe.def with their
own parser and apply the rules to the input. They cover only the lines these
packs use. Load vectors are checked against tools/gen/gtcheck.py. Nothing
here imports or calls an engine.

Readings of the text these vectors rest on (quoted in the report that came
with them):
  - A suppressed line on `bits` still occupies its bits for the message
    length: "the line is treated as a line whose key is absent and that has
    neither a `default` nor a sentinel: ... zero bits on `bits`".
  - Whitespace in separators, tokens and texts is space, tab, LF and CR.
  - An `element` is placed by the text of the lines, whether or not they
    write: "placed at the first line, of any kind, that addresses it or a
    path under it" (ruling 13), so a line suppressed by `with` still places it.
  - `tokens` under ruling 7 as amended: the target is set in the first pass
    in which an argument is present and not 0; the arguments absent then are
    taken as absent, and a later pass does not change the target once set.
  - A line suppressed on `text` still addresses its field: it counts for
    the number of fields (step 4 of 0.10) and, unless `optional`, stops the
    removal of step 5, as a line whose key is absent does (ruling 22).
  - Ruling 23 read with ruling 14 of 0.17: an `optional` field counts toward
    `L` only when it is written, and a suppressed one is never written.

Inputs: the pack.def files of the `conformance-cond-*` packs and of
`conformance-derive-functions`, and model/probe.def. Writes, under --out, the
vector files named above. With --check nothing is written and the exit
status is 1 when a committed file differs from what this script writes.

Usage: python3 -I tools/gen/conformance-cond-vectors.py [--out DIR] [--check]
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402
import gtcheck  # noqa: E402


class Fail(Exception):
    """A conversion that fails with an error kind of the spec."""

    def __init__(self, kind, why):
        super().__init__(kind, why)
        self.kind, self.why = kind, why


# ------------------------------------------------------------------------------
# a parser of the pack lines these packs use
# ------------------------------------------------------------------------------
def tokens_of(raw):
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c in " \t":
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = raw.index('"', i + 1)
            out.append(raw[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < len(raw) and raw[j] not in " \t":
                j += 1
            out.append(raw[i:j])
            i = j
    return out


def parse_pack(text):
    pack = {"wire": None, "root": None, "seq": False, "msb": False, "wb": 1, "armor": "hex", "lines": []}
    stack = []
    for raw in text.splitlines():
        toks = tokens_of(raw)
        if not toks or toks[0] in ("format", "version", "distribution", "source", "uses"):
            continue
        d, a = toks[0], toks[1:]
        if d == "wire":
            pack["wire"] = a[0]
            continue
        if d == "root":
            pack["root"] = a[0]
            continue
        if d == "layout":
            pack["seq"] = a[0] == "sequential"
            continue
        if d == "bit_order":
            pack["msb"] = a[0] == "msb"
            continue
        if d == "word_bytes":
            pack["wb"] = int(a[0])
            continue
        if d == "armor":
            pack["armor"] = a[0]
            continue
        if d == "end":
            stack.pop()
            continue
        if d == "kind":                 # one kind at most in these packs: its lines follow
            pack["kind"] = a[0]
            continue
        into = stack[-1]["body"] if stack else pack["lines"]
        if d == "field":
            line = {"d": "field", "key": a[0], "loc": a[1], "tr": a[2], "with": None, "absent": None,
                    "optional": False}
            i = 3
            while i < len(a):
                if a[i] == "optional":          # the one option without a value
                    line["optional"] = True
                    i += 1
                    continue
                line[a[i]] = a[i + 1]
                i += 2
            if pack["wire"] == "bits" and not pack["seq"]:
                w, p, n = (int(x) for x in a[1].split(":"))
                line["start"], line["n"] = w * pack["wb"] * 8 + p, n
            elif pack["wire"] == "bits":
                line["n"] = int(a[1])
            into.append(line)
        elif d == "default":
            into.append({"d": "default", "key": a[0], "value": a[1]})
        elif d == "element":
            into.append({"d": "element", "path": a[0]})
        elif d == "when":
            into.append({"d": "when", "loc": a[0], "value": a[1]})
        elif d == "presence":
            into.append({"d": "presence", "name": a[0], "n": a[1]})
        elif d == "fx":
            into.append({"d": "fx"})
        elif d == "also":
            into[-1].setdefault("also", []).append(a[0])
        elif d in ("group", "opt", "chain", "if"):
            block = {"d": d, "args": a, "body": []}
            if d == "group":
                block["list"], block["loc"] = a[0], a[1]
            if d == "if" and not pack["seq"]:
                w, p, n = (int(x) for x in a[0].split(":"))
                block["start"], block["n"] = w * pack["wb"] * 8 + p, n
                block["values"] = [int(v) for v in a[1].split(",")]
            into.append(block)
            stack.append(block)
        else:
            raise ValueError("directive %s" % d)
    return pack


def fields(lines):
    for line in lines:
        if line["d"] == "field":
            yield line
        elif line["d"] in ("if", "opt", "chain"):
            yield from fields(line["body"])


def defaults_of(lines):
    out = {}
    for line in lines:
        if line["d"] == "default":
            out.setdefault(line["key"], line["value"])
        elif line["d"] in ("if", "opt", "chain"):
            for k, v in defaults_of(line["body"]).items():
                out.setdefault(k, v)
    return out


# ------------------------------------------------------------------------------
# an entity: {"keys": {key: value}, "lists": {list: [item {key: value}]}}
# ------------------------------------------------------------------------------
def entity():
    return {"keys": {}, "lists": {}}


def holds(scope, key):
    """Ruling 2: a scalar holds when present, whatever its value; a list when
    present with at least one item. `scope` is the entity or an item."""
    if key in scope.get("keys", {}):
        return True
    items = scope.get("lists", {}).get(key)
    return bool(items)


def suppressed(line, scope):
    return line.get("with") is not None and not holds(scope, line["with"])


def read_typed(text, key_type):
    return int(text) if key_type == "int" else text


# ------------------------------------------------------------------------------
# iso8601: decode as iso8601_ms (0.6), encode iso8601_short (0.18)
# ------------------------------------------------------------------------------
def days_from_civil(y, m, d):
    y -= m <= 2
    era = y // 400                   # floor division: Python's //
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]+)?"
                  r"([Zz]|[+-][0-9]{2}:[0-9]{2})\Z")


def iso_decode(text):
    m = _ISO.match(text)
    if not m:
        raise Fail("transform-decode", "not iso8601: %s" % text)
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or ".")[1:4].ljust(3, "0")       # truncated, not rounded
    ms = ((days_from_civil(y, mo, d) * 24 + h) * 60 + mi) * 60000 + s * 1000 + int(frac)
    z = m.group(8)
    if z not in ("Z", "z"):
        sign = 1 if z[0] == "+" else -1
        ms -= sign * (int(z[1:3]) * 60 + int(z[4:6])) * 60000
    return ms


def iso_short(ms):
    """Ruling 11: the milliseconds are ms - 1000 * floor(ms / 1000)."""
    sec, milli = ms // 1000, ms - 1000 * (ms // 1000)
    days, rest = sec // 86400, sec % 86400
    y, mo, d = civil_from_days(days)
    if not 0 <= y <= 9999:
        raise Fail("transform-encode", "iso8601_short: year %d" % y)
    text = "%04d-%02d-%02dT%02d:%02d:%02d" % (y, mo, d, rest // 3600, rest // 60 % 60, rest % 60)
    if milli:
        text += "." + ("%03d" % milli).rstrip("0")
    return text + "Z"


# ------------------------------------------------------------------------------
# text values
# ------------------------------------------------------------------------------
KEY_TYPES = {}          # filled from the model files: key -> string | int | float


def tr_decode(tr, raw, key):
    if tr == "int":
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise Fail("transform-decode", "int")
        return raw
    if tr == "string":
        if not isinstance(raw, str):
            raise Fail("transform-decode", "string")
        return raw
    if tr == "iso8601_short":
        return iso_decode(raw)
    raise ValueError(tr)


def tr_encode_json(tr, v):
    if tr == "int":
        return str(v)
    if tr == "string":
        return json.dumps(v, ensure_ascii=False)
    if tr == "iso8601_short":
        return json.dumps(iso_short(v))
    raise ValueError(tr)


def tr_encode_text(tr, v):
    if tr == "iso8601_short":
        return iso_short(v)
    return str(v)


# ------------------------------------------------------------------------------
# json and geojson
# ------------------------------------------------------------------------------
def json_decode(pack, text):
    obj = json.loads(text)
    ent = entity()
    if pack["wire"] == "geojson":
        flat = dict(obj.get("properties") or {})
        flat = {"properties." + k: v for k, v in flat.items()}
        flat.update({k: v for k, v in obj.items() if k not in ("type", "geometry", "properties")})
        obj = flat
    for line in pack["lines"]:
        if line["d"] == "field":
            if line["key"] in ent["keys"] or obj.get(line["loc"]) is None:
                continue
            ent["keys"][line["key"]] = tr_decode(line["tr"], obj[line["loc"]], line["key"])
        elif line["d"] == "group" and isinstance(obj.get(line["loc"]), list):
            items = []
            for el in obj[line["loc"]]:
                item = {"keys": {}}
                for f in fields(line["body"]):
                    raw = el if f["loc"] == "." else (el.get(f["loc"]) if isinstance(el, dict) else None)
                    if raw is not None and f["key"] not in item["keys"]:
                        item["keys"][f["key"]] = tr_decode(f["tr"], raw, f["key"])
                items.append(item)
            ent["lists"][line["list"]] = items
    return ent


def text_members(lines, scope, defaults, encode_value):
    """[(locator, written text)] in the order of ruling 23 of 0.9: a locator
    once, at the first line that names it; the value of the earliest line
    that is not suppressed and whose key is present or has a default."""
    order, value = [], {}
    for line in lines:
        if line["d"] != "field":
            continue
        loc = line["loc"]
        if loc not in order:
            order.append(loc)
        if loc in value or suppressed(line, scope):
            continue
        if line["key"] in scope["keys"]:
            value[loc] = encode_value(line, scope["keys"][line["key"]])
        elif line["key"] in defaults:
            value[loc] = encode_value(line, read_typed(defaults[line["key"]], KEY_TYPES[line["key"]]))
    return [(loc, value[loc]) for loc in order if loc in value]


def json_encode(pack, ent):
    defaults = defaults_of(pack["lines"])
    enc = lambda line, v: tr_encode_json(line["tr"], v)  # noqa: E731
    flat = [(loc, v) for loc, v in text_members([x for x in pack["lines"] if x["d"] == "field"], ent, defaults, enc)]
    out, done = [], set()
    # members in line order, groups at their line
    placed = dict(flat)
    for line in pack["lines"]:
        if line["d"] == "field" and line["loc"] in placed and line["loc"] not in done:
            out.append((line["loc"], placed[line["loc"]]))
            done.add(line["loc"])
        elif line["d"] == "group" and line["list"] in ent["lists"]:
            arr = []
            for item in ent["lists"][line["list"]]:
                body = [x for x in line["body"] if x["d"] == "field"]
                if len(body) == 1 and body[0]["loc"] == ".":
                    f = body[0]
                    ok = f["key"] in item["keys"] and not suppressed(f, item)
                    arr.append(tr_encode_json(f["tr"], item["keys"][f["key"]]) if ok else "null")
                else:
                    members = text_members(body, item, defaults_of(line["body"]), enc)
                    arr.append("{" + ",".join(json.dumps(k) + ":" + v for k, v in members) + "}")
            out.append((line["loc"], "[" + ",".join(arr) + "]"))
    if pack["wire"] == "geojson":
        props = [(k[len("properties."):], v) for k, v in out if k.startswith("properties.")]
        top = [(k, v) for k, v in out if not k.startswith("properties.")]
        text = '{"type":"Feature","geometry":null,"properties":{%s}' % ",".join(
            json.dumps(k) + ":" + v for k, v in props)
        return text + "".join("," + json.dumps(k) + ":" + v for k, v in top) + "}"
    return "{" + ",".join(json.dumps(k) + ":" + v for k, v in out) + "}"


# ------------------------------------------------------------------------------
# xml
# ------------------------------------------------------------------------------
def xml_find(el, path):
    for name in path:
        el = el.find(name) if el is not None else None
    return el


def xml_value(el, loc):
    """The raw text at a field locator under `el`, or None."""
    *path, last = loc.split("/")
    el = xml_find(el, path)
    if el is None:
        return None
    if last == "#text":
        return el.text or None
    return el.get(last[1:])


def xml_decode(pack, text):
    root = ET.fromstring(text)
    if root.tag != pack["root"]:
        raise Fail("missing-root", root.tag)
    ent = entity()
    for line in pack["lines"]:
        if line["d"] == "when":
            assert line["value"] == "present"
            if xml_value(root, line["loc"]) is None:
                raise Fail("no-kind", line["loc"])
        if line["d"] == "field":
            raw = xml_value(root, line["loc"])
            if raw is not None and line["key"] not in ent["keys"]:
                ent["keys"][line["key"]] = read_typed(raw, KEY_TYPES[line["key"]]) if line["tr"] != "iso8601_short" \
                    else iso_decode(raw)
        elif line["d"] == "group":
            *path, name = line["loc"].split("/")
            box = xml_find(root, path)
            items = []
            for child in (box.findall(name) if box is not None else []):
                item = {"keys": {}}
                for f in fields(line["body"]):
                    raw = xml_value(child, f["loc"])
                    if raw is not None:
                        item["keys"][f["key"]] = read_typed(raw, KEY_TYPES[f["key"]])
                items.append(item)
            if items:
                ent["lists"][line["list"]] = items
    return ent


class El:
    def __init__(self, name):
        self.name, self.attrs, self.text, self.slots, self.forced = name, [], None, [], False

    def child(self, name):
        for kind, x in self.slots:
            if kind == "el" and x.name == name:
                return x
        x = El(name)
        self.slots.append(("el", x))
        return x

    def written(self):
        return bool(self.forced or self.attrs or self.text is not None or any(
            (kind == "el" and x.written()) or (kind == "items" and x) for kind, x in self.slots))

    def render(self):
        head = "<" + self.name + "".join(' %s="%s"' % kv for kv in self.attrs)
        inner = self.text or ""
        for kind, x in self.slots:
            if kind == "el":
                inner += x.render() if x.written() else ""
            else:
                inner += "".join(i.render() for i in x)
        return head + ("/>" if not inner else ">" + inner + "</" + self.name + ">")


def xml_place(el, loc, value):
    *path, last = loc.split("/")
    for name in path:
        el = el.child(name)
    if value is None:
        return
    if last == "#text":
        el.text = value
    else:
        el.attrs.append((last[1:], value))


def xml_encode(pack, ent):
    root = El(pack["root"])
    defaults = defaults_of(pack["lines"])
    enc = lambda line, v: tr_encode_text(line["tr"], v)  # noqa: E731
    values = dict(text_members(pack["lines"], ent, defaults, enc))
    for line in pack["lines"]:                      # every line places its elements (ruling 10 of 0.5)
        if line["d"] == "when":
            assert line["value"] == "present"       # names no position, writes nothing (ruling 19)
        if line["d"] == "field":
            xml_place(root, line["loc"], values.pop(line["loc"], None))
        elif line["d"] == "element":
            el = root
            for name in line["path"].split("/"):
                el = el.child(name)
            el.forced = True
        elif line["d"] == "group":
            *path, name = line["loc"].split("/")
            box = root
            for step in path:
                box = box.child(step)
            items = []
            for item in ent["lists"].get(line["list"], []):
                el = El(name)
                body = [x for x in line["body"] if x["d"] == "field"]
                ivals = dict(text_members(body, item, defaults_of(line["body"]), enc))
                for f in body:
                    xml_place(el, f["loc"], ivals.pop(f["loc"], None))
                items.append(el)
            box.slots.append(("items", items))
    return root.render()


# ------------------------------------------------------------------------------
# bits: bit lists, lsb or msb
# ------------------------------------------------------------------------------
def to_bits(hx, msb):
    out = []
    for byte in bytes.fromhex(hx):
        out += [(byte >> (7 - i)) & 1 if msb else (byte >> i) & 1 for i in range(8)]
    return out


def to_hex(bits, msb):
    bits = bits + [0] * (-len(bits) % 8)
    out = bytearray()
    for i in range(0, len(bits), 8):
        out.append(sum(b << (7 - k) if msb else b << k for k, b in enumerate(bits[i:i + 8])))
    return out.hex()


def vbits(v, n, msb):
    return [(v >> (n - 1 - k)) & 1 if msb else (v >> k) & 1 for k in range(n)]


def rbits(bits, msb):
    n = len(bits)
    return sum(b << (n - 1 - k) if msb else b << k for k, b in enumerate(bits))


# -- the fixed layout with gates (0.17), no nesting and no groups --------------
def from_sixbit(text):
    """0.14 Reading the armored text: `0`..`W` stand for c - 0x30, `` ` ``..`w`
    for c - 0x38; six bits each, most significant first."""
    out = []
    for c in text:
        o = ord(c)
        if 0x30 <= o <= 0x57:
            v = o - 0x30
        elif 0x60 <= o <= 0x77:
            v = o - 0x38
        else:
            raise Fail("malformed-wire", "armor character %r" % c)
        out += vbits(v, 6, True)
    return out


def to_sixbit(bits):
    """0.14 Writing the armored text: zero bits to a multiple of 6; values 0
    to 39 as 0x30 + v, 40 to 63 as 0x38 + v."""
    bits = bits + [0] * (-len(bits) % 6)
    vals = [rbits(bits[i:i + 6], True) for i in range(0, len(bits), 6)]
    return "".join(chr(0x30 + v if v < 40 else 0x38 + v) for v in vals)


def fixed_decode(pack, hx):
    msb = pack["msb"]
    bits = from_sixbit(hx) if pack["armor"] == "sixbit" else to_bits(hx, msb)
    ent = entity()

    def held(g):
        end = g["start"] + g["n"]
        return end <= len(bits) and rbits(bits[g["start"]:end], msb) in g["values"]

    active = []
    for line in pack["lines"]:
        if line["d"] == "field":
            active.append(line)
        elif line["d"] == "if" and held(line):
            active += [x for x in line["body"] if x["d"] == "field"]
    if any(x["start"] + x["n"] > len(bits) for x in active if not x["optional"]):
        raise Fail("malformed-wire", "short")
    for x in active:
        if x["start"] + x["n"] > len(bits):
            continue                    # 0.14: an optional field beyond the input is absent
        raw = rbits(bits[x["start"]:x["start"] + x["n"]], msb)
        if x["absent"] is not None and raw in [int(v) for v in x["absent"].split(",")]:
            continue
        ent["keys"].setdefault(x["key"], raw)
    return ent


def fixed_encode(pack, ent):
    msb, keys = pack["msb"], ent["keys"]
    defaults = defaults_of(pack["lines"])
    outside = [x for x in pack["lines"] if x["d"] == "field"]
    gates = [x for x in pack["lines"] if x["d"] == "if"]

    def present(x):
        return x["key"] in keys and not suppressed(x, ent)

    # step 1: a suppressed line opens no block (ruling 1)
    opened = [g for g in gates if any(present(x) for x in fields(g["body"]))]
    # step 2: bits written by lines with a present key outside blocks
    written = {}
    for x in outside:
        if present(x):
            for k, b in enumerate(vbits(keys[x["key"]], x["n"], msb)):
                written.setdefault(x["start"] + k, b)
    # step 3: gate values
    given = {}
    for g in gates:
        if g in opened and not any(g["start"] + k in written for k in range(g["n"])):
            given[id(g)] = g["values"][0]
            for k, b in enumerate(vbits(g["values"][0], g["n"], msb)):
                written[g["start"] + k] = b
    # step 4: with the bits of outside defaults and sentinels; a suppressed
    # line has neither (ruling 1)
    seen = dict(written)
    for x in outside:
        if x["key"] in keys or suppressed(x, ent):
            continue
        raw = int(defaults[x["key"]]) if x["key"] in defaults else (
            int(x["absent"].split(",")[0]) if x["absent"] else None)
        if raw is not None:
            for k, b in enumerate(vbits(raw, x["n"], msb)):
                seen.setdefault(x["start"] + k, b)
    held = [g for g in gates if rbits([seen.get(g["start"] + k, 0) for k in range(g["n"])], msb) in g["values"]]
    # step 5
    active = outside + [x for g in held for x in g["body"] if x["d"] == "field"]
    length = max([x["start"] + x["n"] for x in active] + [g["start"] + g["n"] for g in held])
    length = -(-length // (pack["wb"] * 8)) * pack["wb"] * 8

    def writes(x):
        """A line writes its bits: not suppressed, and a present key, a
        default or a sentinel (rulings 1 and 23 of 0.18, ruling 12 of 0.14)."""
        return not suppressed(x, ent) and (x["key"] in keys or x["key"] in defaults or bool(x["absent"]))
    # 0.14 and ruling 14 of 0.17: L counts every line of the scope (held
    # blocks), a suppressed one included (ruling 23), but an optional field
    # only when it is written
    armor_l = max([x["start"] + x["n"] for x in active if not x["optional"] or writes(x)]
                  + [g["start"] + g["n"] for g in held] + [0])
    out, claimed, by_present = [0] * length, set(), set()
    for x in active:
        if suppressed(x, ent):
            continue
        v = keys.get(x["key"], int(defaults[x["key"]]) if x["key"] in defaults else None)
        if v is None:
            continue
        if x["key"] in keys:
            by_present.update(range(x["start"], x["start"] + x["n"]))
        for k, b in enumerate(vbits(v & ((1 << x["n"]) - 1), x["n"], msb)):
            if x["start"] + k not in claimed:
                out[x["start"] + k] = b
                claimed.add(x["start"] + k)
    for g in held:
        if id(g) in given:
            for k, b in enumerate(vbits(given[id(g)], g["n"], msb)):
                if g["start"] + k not in by_present:
                    out[g["start"] + k] = b
                    claimed.add(g["start"] + k)
    for x in active:
        if x["absent"] and x["key"] not in keys and x["key"] not in defaults and not suppressed(x, ent):
            for k, b in enumerate(vbits(int(x["absent"].split(",")[0]), x["n"], msb)):
                if x["start"] + k not in claimed:
                    out[x["start"] + k] = b
    # step 6: a suppressed line does not count as mapping its key (ruling 1)
    for key in keys:
        mine = [x for x in fields(pack["lines"]) if x["key"] == key and not suppressed(x, ent)]
        if mine and not any(x in active for x in mine):
            raise Fail("transform-encode", "key %s is mapped only in blocks not held" % key)
    if pack["armor"] == "sixbit":
        out = (out + [0] * armor_l)[:armor_l]
    again = [g for g in gates if g["start"] + g["n"] <= len(out)
             and rbits(out[g["start"]:g["start"] + g["n"]], msb) in g["values"]]
    if again != held:
        raise Fail("transform-encode", "the output decodes to another choice of blocks")
    return to_sixbit(out) if pack["armor"] == "sixbit" else to_hex(out, msb)


# -- the sequential layout (0.8): presence n and fx, if, opt, chain ------------
def content(lines, scope, defaults):
    """Ruling 22 of 0.8 with ruling 2 of 0.8 and ruling 1 of 0.18: a key that
    is present, or has a default, on a line that is not suppressed."""
    return any(not suppressed(x, scope) and (x["key"] in scope["keys"] or x["key"] in defaults)
               for x in fields(lines))


def seq_encode(pack, ent):
    msb, defaults = pack["msb"], defaults_of(pack["lines"])
    out = []

    def lines_(nodes):
        pres = {}
        for i, node in enumerate(nodes):
            d = node["d"]
            if d == "presence":
                blocks = [b for b in nodes[i + 1:] if b["d"] == "if"]
                on = set()
                for b in blocks:
                    if content(b["body"], ent, defaults):
                        on.update(int(c.split(".")[1]) for c in b["args"])
                if node["n"] == "fx":
                    octets = max([1] + [-(-n // 7) for n in on])
                    for o in range(octets):
                        out.extend([1 if 7 * o + k + 1 in on else 0 for k in range(7)] + [int(o + 1 < octets)])
                    pres[node["name"]] = on
                else:
                    n = int(node["n"])
                    out.extend([1 if k + 1 in on else 0 for k in range(n)])
                    pres[node["name"]] = on
            elif d == "if":
                name = node["args"][0].split(".")[0]
                if all(int(c.split(".")[1]) in pres[name] for c in node["args"]):
                    lines_(node["body"])
            elif d == "opt":
                bit = content(node["body"], ent, defaults)
                out.append(int(bit))
                if bit:
                    lines_(node["body"])
            elif d == "chain":
                parts, cur = [[]], None
                for x in node["body"]:
                    if x["d"] == "fx":
                        parts.append([])
                    else:
                        parts[-1].append(x)
                lines_(parts[0])
                for k in range(1, len(parts)):
                    bit = any(content(p, ent, defaults) for p in parts[k:])
                    out.append(int(bit))
                    if not bit:
                        break
                    lines_(parts[k])
            elif d == "field":
                # ruling 5: a suppressed line's `also` keys stay candidates
                cands = ([] if suppressed(node, ent) else [node["key"]]) + node.get("also", [])
                # ruling 20: suppressed and no `also` value: zero bits, not the sentinel
                sentinel = int(node["absent"].split(",")[0]) if node.get("absent") and not suppressed(node, ent) else 0
                v = next((ent["keys"][k] for k in cands if k in ent["keys"]),
                         next((int(defaults[k]) for k in cands if k in defaults), sentinel))
                out.extend(vbits(v, node["n"], msb))
    lines_(pack["lines"])
    return to_hex(out, msb)


def seq_decode(pack, hx):
    bits, msb = to_bits(hx, pack["msb"]), pack["msb"]
    ent, at = entity(), [0]

    def take(n):
        if at[0] + n > len(bits):
            raise Fail("malformed-wire", "short")
        at[0] += n
        return bits[at[0] - n:at[0]]

    def lines_(nodes):
        pres = {}
        for node in nodes:
            d = node["d"]
            if d == "presence":
                if node["n"] == "fx":
                    on, o = set(), 0
                    while True:
                        octet = take(8)
                        on.update(7 * o + k + 1 for k in range(7) if octet[k])
                        o += 1
                        if not octet[7]:
                            break
                else:
                    on = {k + 1 for k, b in enumerate(take(int(node["n"]))) if b}
                pres[node["name"]] = on
            elif d == "if":
                name = node["args"][0].split(".")[0]
                if all(int(c.split(".")[1]) in pres[name] for c in node["args"]):
                    lines_(node["body"])
            elif d == "opt":
                if take(1)[0]:
                    lines_(node["body"])
            elif d == "chain":
                parts = [[]]
                for x in node["body"]:
                    if x["d"] == "fx":
                        parts.append([])
                    else:
                        parts[-1].append(x)
                lines_(parts[0])
                for p in parts[1:]:
                    if not take(1)[0]:
                        break
                    lines_(p)
            elif d == "field":
                raw = rbits(take(node["n"]), msb)
                if node.get("absent") and raw in [int(v) for v in node["absent"].split(",")]:
                    continue                # ruling 24 of 0.9: every key of the line absent
                for k in [node["key"]] + node.get("also", []):
                    ent["keys"].setdefault(k, raw)
    lines_(pack["lines"])
    return ent


# ------------------------------------------------------------------------------
# protobuf: varint fields and one group of `.` pstring items
# ------------------------------------------------------------------------------
def varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def pb_decode(pack, hx):
    data, i, ent = bytes.fromhex(hx), 0, entity()
    by_no = {int(x["loc"]): x for x in pack["lines"] if x["d"] == "field"}
    groups = {int(x["loc"]): x for x in pack["lines"] if x["d"] == "group"}

    def rv():
        nonlocal i
        v, s = 0, 0
        while True:
            b = data[i]
            i += 1
            v |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                return v
    while i < len(data):
        tag = rv()
        no, wt = tag >> 3, tag & 7
        if wt == 0:
            v = rv()
            if no in by_no:
                ent["keys"][by_no[no]["key"]] = v
        elif wt == 2:
            n = rv()
            payload, i = data[i:i + n], i + n
            if no in groups:
                f = groups[no]["body"][0]
                item = {"keys": {f["key"]: payload.decode()}} if payload else {"keys": {}}
                ent["lists"].setdefault(groups[no]["list"], []).append(item)
        else:
            raise ValueError(wt)
    return ent


def pb_encode(pack, ent):
    out = b""
    for line in sorted(pack["lines"], key=lambda x: int(x["loc"])):
        if line["d"] == "field":
            if line["key"] in ent["keys"] and not suppressed(line, ent):
                out += varint(int(line["loc"]) << 3) + varint(ent["keys"][line["key"]])
        else:
            f = line["body"][0]
            for item in ent["lists"].get(line["list"], []):
                text = item["keys"][f["key"]].encode() if f["key"] in item["keys"] and not suppressed(f, item) else b""
                out += varint(int(line["loc"]) << 3 | 2) + varint(len(text)) + text
    return out.hex()


# ------------------------------------------------------------------------------
# text (0.10): whole-field locators, `int`, delimiter ","; no start or checksum
# ------------------------------------------------------------------------------
def text_decode(pack, text):
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    if any(not 0x20 <= ord(c) <= 0x7E for c in text):
        raise Fail("malformed-wire", "character")
    parts, ent = text.split(","), entity()
    for line in fields(pack["lines"]):
        i = int(line["loc"])
        if i < len(parts) and parts[i] != "" and line["key"] not in ent["keys"]:
            if line["tr"] == "int":
                if not re.match(r"[+-]?[0-9]+\Z", parts[i]):
                    raise Fail("transform-decode", parts[i])
                ent["keys"][line["key"]] = int(parts[i])
            else:
                ent["keys"][line["key"]] = parts[i]
    return ent


def text_encode(pack, ent):
    lines = list(fields(pack["lines"]))
    defaults = defaults_of(pack["lines"])
    # step 1: the earliest line that is not suppressed and whose key is
    # present or has a default; a suppressed line writes what an absent key
    # writes, nothing (ruling 22 of 0.18)
    values = dict(text_members(lines, ent, defaults, lambda line, v: str(v)))
    # step 4: one more than the highest index a line addresses, written or not
    out = [values.get(str(i), "") for i in range(1 + max(int(x["loc"]) for x in lines))]
    # step 5: trailing empty fields whose every line is optional
    while out and out[-1] == "":
        mine = [x for x in lines if int(x["loc"]) == len(out) - 1]
        if not mine or not all(x["optional"] for x in mine):
            break
        out.pop()
    return ",".join(out)


# ------------------------------------------------------------------------------
# tlv (0.13): tag ber-oid and length ber, tags and lengths below 128 here; a
# top set only; `uint:<n>` and `utf8`
# ------------------------------------------------------------------------------
def tlv_decode(pack, hx):
    data, i, items = bytes.fromhex(hx), 0, []
    while i < len(data):
        tag, n = data[i], data[i + 1]
        assert tag < 0x80 and n < 0x80, "only one-byte tags and lengths here"
        if i + 2 + n > len(data):
            raise Fail("malformed-wire", "item runs past the set")
        items.append((tag, data[i + 2:i + 2 + n]))
        i += 2 + n
    ent = entity()
    for line in fields(pack["lines"]):
        tag = int(line["loc"].split(":")[0])
        value = next((v for t, v in items if t == tag), None)       # first occurrence
        if value is None or line["key"] in ent["keys"]:
            continue
        if line["tr"] == "utf8":
            ent["keys"][line["key"]] = value.decode("utf-8")
        elif value:                     # an empty value is absent but under utf8 and hex
            ent["keys"][line["key"]] = int.from_bytes(value, "big")
    return ent


def tlv_encode(pack, ent):
    out, done = b"", set()
    defaults = defaults_of(pack["lines"])
    for line in fields(pack["lines"]):
        tag, _, size = line["loc"].partition(":")
        # an absent key writes no item, and so does a suppressed line (ruling
        # 22 of 0.18); the earliest present key of a path (ruling 16 of 0.5)
        if tag in done or suppressed(line, ent):
            continue
        if line["key"] in ent["keys"]:
            v = ent["keys"][line["key"]]
        elif line["key"] in defaults:
            v = read_typed(defaults[line["key"]], KEY_TYPES[line["key"]])
        else:
            continue
        if line["tr"] == "utf8":
            value = v.encode("utf-8")
        else:
            if not 0 <= v < 1 << (8 * int(size)):
                raise Fail("transform-encode", "uint")
            value = v.to_bytes(int(size), "big")
        assert int(tag) < 0x80 and len(value) < 0x80
        out += bytes([int(tag), len(value)]) + value
        done.add(tag)
    return out.hex()


# ------------------------------------------------------------------------------
# derivations (0.6 Derived keys; 0.8 `any`; 0.18 tokens, has_token, text_if)
# ------------------------------------------------------------------------------
SEPS = {"space": " ", "comma": ",", "colon": ":"}


def parse_derives(text):
    out = []
    for raw in text.splitlines():
        toks = tokens_of(raw)
        if toks and toks[0] == "derive":
            fn, _, param = toks[2].partition(":")
            out.append((toks[1], fn, param, toks[3:]))
        elif toks and toks[0] == "key":
            KEY_TYPES["probe." + toks[1]] = toks[2]
    return out


def derive_one(fn, param, args):
    """The result, or None for an absent target. `args` hold None for an
    absent argument."""
    if fn == "tokens":
        sep, _, toks = param.partition(":")
        sep = SEPS.get(sep, sep)
        picked = [t for t, a in zip(toks.split(","), args) if a is not None and a != 0]
        return sep.join(picked) if picked else None
    if fn == "has_token":
        sep, _, tok = param.partition(":")
        sep = SEPS.get(sep, sep)
        return int(tok in [p for p in args[0].split(sep) if p])
    if fn == "text_if":
        return param if args[0] else None
    if fn == "not":
        return int(args[0] == 0)
    if fn == "join":
        return param.join(args)
    # the 0.6 and 0.8 functions whose arguments a vector here holds
    if fn == "any":
        return int(any(a for a in args if a is not None))
    if fn == "copy":
        return args[0]
    if fn == "day_seconds":
        return (args[0] % 86400000) / 1000
    if fn == "offset":
        return args[0] + int(param)
    if fn == "text_of":
        return str(args[0])
    if fn == "parse_int":
        return int(args[0]) if re.match(r"-?[0-9]+\Z", args[0]) else None
    raise NotImplementedError(fn)


PARTIAL = ("any", "tokens")             # ruling 7: set when only some arguments are present


def complete(keys, derives):
    keys = dict(keys)
    for _ in range(8):
        changed = False
        for target, fn, param, argkeys in derives:
            if target in keys:
                continue
            have = [keys.get(a) for a in argkeys]
            if fn in PARTIAL:
                if all(v is None for v in have):
                    continue
            elif any(v is None for v in have):
                continue
            v = derive_one(fn, param, have)
            if v is not None:
                keys[target] = v
                changed = True
        if not changed:
            break
    return keys


# ------------------------------------------------------------------------------
# convert
# ------------------------------------------------------------------------------
def decode(pack, inp):
    w = pack["wire"]
    if w in ("json", "geojson"):
        return json_decode(pack, inp)
    if w == "xml":
        return xml_decode(pack, inp)
    if w == "protobuf":
        return pb_decode(pack, inp)
    if w == "text":
        return text_decode(pack, inp)
    if w == "tlv":
        return tlv_decode(pack, inp)
    return seq_decode(pack, inp) if pack["seq"] else fixed_decode(pack, inp)


def encode(pack, ent):
    w = pack["wire"]
    if w in ("json", "geojson"):
        return json_encode(pack, ent)
    if w == "xml":
        return xml_encode(pack, ent)
    if w == "protobuf":
        return pb_encode(pack, ent)
    if w == "text":
        return text_encode(pack, ent)
    if w == "tlv":
        return tlv_encode(pack, ent)
    return seq_encode(pack, ent) if pack["seq"] else fixed_encode(pack, ent)


def text_of(v):
    return str(v)


def model_of(ent):
    m = {k: text_of(v) for k, v in ent["keys"].items()}
    for name, items in ent["lists"].items():
        m[name + ".#"] = str(len(items))
        for i, item in enumerate(items):
            for k, v in item["keys"].items():
                m["%s[%d].%s" % (name, i, k)] = text_of(v)
    return m


SOURCE = "constructed"


def build(sink):
    """Write every vector through the Output `sink`; {pack: number of files}."""
    written, counters, packs = {}, {}, {}
    derives = parse_derives(sink.read("model/probe.def"))
    for raw in sink.read("model/core.def").splitlines():
        toks = tokens_of(raw)
        if toks and toks[0] == "key":
            KEY_TYPES[toks[1]] = toks[2]

    def pack(name):
        if name not in packs:
            packs[name] = parse_pack(sink.read("packs/%s/pack.def" % name))
        return packs[name]

    def emit(owner, d):
        counters[owner] = counters.get(owner, 0) + 1
        sink.write("packs/%s/vectors/%02d-%s.json" % (owner, counters[owner], d["name"]),
                   json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written[owner] = written.get(owner, 0) + 1

    def vec(owner, name, frm, to, inp, expect=None, error=None, model=None, context=None, ref=""):
        """`owner`, `frm`, `to`: pack names without `conformance-cond-`, or a
        full name. The second computation runs and must agree."""
        full = lambda n: n if n.startswith("conformance-") else "conformance-cond-" + n  # noqa: E731
        owner, frm, to = full(owner), full(frm), full(to)
        ent = decode(pack(frm), inp)
        decoded = ent
        try:
            if frm != to or context is not None:
                keys = dict(ent["keys"])
                for k, v in (context or {}).items():
                    keys.setdefault(k, read_typed(v, KEY_TYPES[k]))
                ent = {"keys": complete(keys, derives), "lists": ent["lists"]}
            got, failed = encode(pack(to), ent), None
        except Fail as e:
            got, failed = None, e
        if error:
            assert failed is not None and failed.kind == error, (name, failed, got)
        else:
            assert failed is None, (name, failed and failed.why)
            assert got == expect, (name, expect, got)
        if model:
            have = model_of(ent if model.get("@complete") else decoded)
            for k, v in model.items():
                if k == "@absent":
                    for gone in v:
                        assert gone not in have, (name, gone, have)
                elif k == "@kind":          # the one kind of the pack; decode checked its `when`
                    assert pack(frm).get("kind") == v, (name, v)
                elif k.endswith(".#") and v == "absent":
                    assert k[:-2] not in ent["lists"], (name, k)
                elif k != "@complete":
                    assert have.get(k) == v, (name, k, v, have.get(k))
        d = {"name": name, "from": frm, "to": to, "input": inp}
        if context is not None:
            d["context"] = context
        if error:
            d["expect_error"] = error
        else:
            d["expect"] = expect
        if model:
            d["model"] = model
        d["source"] = SOURCE
        d["reference"] = ref
        emit(owner, d)

    # ==========================================================================
    # conformance-cond-json. Members in line order: x y z w c1 n c2 s1 s q
    # items nums. n has the default 3, so every entity without n writes "n":3.
    # ==========================================================================
    R = "spec 0.18, Written only with another key; "
    # x is held: y is written. n: its default.
    vec("src", "json-with-key-held-writes-the-line", "src", "json", '{"x":1,"y":2}',
        '{"x":1,"y":2,"n":3}', ref=R + "the entity holds x, so y is written")
    # x is not held: y writes nothing, as an absent key with no default.
    vec("src", "json-with-key-not-held-writes-nothing", "src", "json", '{"y":2}',
        '{"n":3}', ref=R + "x is not held: the line of y is treated as a line whose key is absent")
    # ruling 2: 0 holds.
    vec("src", "json-ruling-02-scalar-0-holds", "src", "json", '{"x":0,"y":2}',
        '{"x":0,"y":2,"n":3}', ref=R + "ruling 2: a scalar holds when present, whatever its value (0)")
    # ruling 2: "" holds. z with s1.
    vec("src", "json-ruling-02-empty-text-holds", "src", "json", '{"z":4,"s1":""}',
        '{"z":4,"n":3,"s1":""}', ref=R + "ruling 2: the empty text holds")
    # ruling 2: [] does not hold, so w is not written; the group writes the
    # empty list as [] (0.7 Encode).
    vec("src", "json-ruling-02-empty-list-does-not-hold", "src", "json", '{"w":5,"items":[]}',
        '{"n":3,"items":[]}', ref=R + "ruling 2: a list holds when present with at least one item; [] is written by its group (0.7)")
    # one item with no keys: the list holds, w is written; the item is {}.
    vec("src", "json-ruling-02-list-of-one-empty-item-holds", "src", "json", '{"w":5,"items":[{}]}',
        '{"w":5,"n":3,"items":[{}]}', ref=R + "ruling 2: present with one item (an item with no keys)")
    # ruling 3: c1 with c1 and default 7; the entity has no c1: nothing, not 7.
    vec("src", "json-ruling-03-own-key-not-held-default-not-written", "src", "json", '{}',
        '{"n":3}', ref=R + "ruling 3: `with` on its own key; when the entity does not hold it the line writes nothing, its default included")
    vec("src", "json-ruling-03-own-key-held-no-effect", "src", "json", '{"c1":5}',
        '{"c1":5,"n":3}', ref=R + "ruling 3: no effect when the entity holds the key")
    # ruling 2: c2 with n; n has only a default: not held; n itself writes 3.
    vec("src", "json-ruling-02-key-with-only-a-default-does-not-hold", "src", "json", '{"c2":4}',
        '{"n":3}', ref=R + "ruling 2: checked on the entity only, never on a default")
    vec("src", "json-ruling-02-key-held-after-its-default-line", "src", "json", '{"c2":4,"n":1}',
        '{"n":1,"c2":4}', ref=R + "ruling 2: n is held")
    # ruling 1: s, first line s2 with y (suppressed), second line callsign.
    vec("src", "json-ruling-01-suppressed-first-line-later-line-written", "src", "json",
        '{"s2":"a","cs":"b"}', '{"n":3,"s":"b"}',
        ref=R + "ruling 1: not a candidate for ruling 16 of 0.5, so a later line on the same locator whose key is present is written")
    # y is held although its own line is suppressed (no x): s2 is written.
    vec("src", "json-ruling-02-held-is-the-entity-not-the-output", "src", "json",
        '{"y":1,"s2":"a","cs":"b"}', '{"n":3,"s":"a"}',
        ref=R + "y is not written (x is not held) but the entity holds y, so s2 is written")
    # ruling 1 with ruling 23 of 0.9: s is placed at its first line (s2,
    # suppressed), before x; the value is callsign's.
    vec("src", "place-json-ruling-01-suppressed-line-still-places-the-member", "src", "place-json",
        '{"x":1,"s2":"a","cs":"b"}', '{"s":"b","x":1}',
        ref=R + "ruling 1: it still names its locator for ruling 23 of 0.9: the member is written at the position of the first line naming the locator, suppressed or not")
    vec("src", "place-json-companion-held", "src", "place-json", '{"x":1,"s2":"a","cs":"b","y":1}',
        '{"s":"a","x":1}', ref=R + "y held: s2 is the earliest line whose key is present")
    vec("place-json", "ruling-01-roundtrip-moves-the-member", "place-json", "place-json",
        '{"x":1,"s":"b"}', '{"s":"b","x":1}', model={"probe.s2": "b", "callsign": "b", "probe.x": "1"},
        ref=R + "ruling 1 with ruling 23 of 0.9 and ruling 6")
    # ruling 2 in a group: item 0 holds label and x; item 1 neither, though the
    # entity holds x.
    vec("src", "json-ruling-02-group-checks-the-item-only", "src", "json",
        '{"x":1,"items":[{"label":"a","qty":1,"val":2,"x":1},{"qty":3,"val":4}]}',
        '{"x":1,"n":3,"items":[{"label":"a","qty":1,"val":2},{}]}',
        ref=R + "ruling 2: inside a group only the item is checked; the key must be declared, not necessarily mapped by the group")
    # ruling 4: the second item has no tag: null.
    vec("src", "json-ruling-04-scalar-item-suppressed-is-null", "src", "json",
        '{"nums":[{"v":1,"t":"a"},{"v":2}]}', '{"n":3,"nums":[1,null]}',
        ref=R + "ruling 4: a `.` field suppressed by `with` writes its item as an item without the value (null on json)")
    # ruling 14: context fills x before encode.
    vec("src", "json-ruling-14-context-key-holds", "src", "json", '{"y":2}',
        '{"x":0,"y":2,"n":3}', context={"probe.x": "0"},
        ref=R + "ruling 14: context fills keys before encode, so `with` sees it")
    # ruling 14: notx = not x = 1 is derived (from != to: derivations run).
    vec("src", "json-ruling-14-derived-key-holds", "src", "json", '{"x":0,"qty":6}',
        '{"x":0,"n":3,"q":6}', model={"@complete": True, "probe.notx": "1"},
        ref=R + "ruling 14: derivations fill keys before encode; probe.notx is `not probe.x`")
    vec("src", "json-ruling-14-no-derived-key-not-held", "src", "json", '{"qty":6}',
        '{"n":3}', model={"@complete": True, "@absent": ["probe.notx"]},
        ref=R + "ruling 14: x is absent, so notx is not derived and q is not written")

    # same-format round trips
    full_in = '{"x":1,"y":2,"z":3,"w":4,"c1":5,"n":6,"c2":7,"s1":"t","s":"u","items":[{"label":"a","qty":1}],"nums":[]}'
    vec("json", "ruling-06-every-with-key-held-roundtrip", "json", "json", full_in, full_in,
        model={"probe.y": "2", "probe.s2": "u", "callsign": "u", "probe.items[0].probe.qty": "1", "probe.nums.#": "0"},
        ref=R + "ruling 6: a same-format round trip is byte-exact when every `with` key is held")
    vec("json", "ruling-06-companion-missing-dropped-on-reencode", "json", "json", '{"y":2,"z":3}',
        '{"n":3}', model={"probe.y": "2", "probe.z": "3", "@absent": ["probe.x", "probe.s1"]},
        ref=R + "ruling 6: decode is unchanged; a wire value whose companion key is missing is dropped on re-encode")
    vec("json", "ruling-04-scalar-items-without-the-key-roundtrip", "json", "json", '{"nums":[1,2]}',
        '{"n":3,"nums":[null,null]}', model={"probe.nums.#": "2", "probe.nums[0].probe.val": "1"},
        ref=R + "rulings 4 and 6: the items hold val only, not tag")
    vec("json", "ruling-14-roundtrip-without-context-derives-nothing", "json", "json", '{"x":0,"q":6}',
        '{"x":0,"n":3}', model={"probe.qty": "6"},
        ref=R + "ruling 14 and 0.6 Order inside convert: from == to and no context, so steps 2 and 3 are skipped")
    vec("json", "ruling-14-roundtrip-with-empty-context-derives", "json", "json", '{"x":0,"q":6}',
        '{"x":0,"n":3,"q":6}', context={}, model={"@complete": True, "probe.notx": "1"},
        ref=R + "ruling 14: an empty context counts as given (ruling 10 of 0.6); notx is derived")

    # ==========================================================================
    # conformance-cond-bits (lsb): byte 0 x with y then z; byte 1 w with y,
    # sentinel 255; byte 2 c1 with y, default 7.
    # ==========================================================================
    vec("src", "bits-ruling-01-companion-not-held", "src", "bits", '{"x":1,"z":2,"w":4,"c1":5}', "020000",
        ref=R + "ruling 1: byte 0 is z's (x is not a candidate); w and c1 write zero bits, neither the sentinel nor the default")
    vec("src", "bits-ruling-01-no-sentinel-no-default-when-suppressed", "src", "bits", '{"x":1,"z":2}', "020000",
        ref=R + "suppressed: neither a default nor a sentinel")
    vec("src", "bits-ruling-02-scalar-0-holds", "src", "bits", '{"x":1,"z":2,"y":0}', "01ff07",
        ref=R + "ruling 2: y = 0 holds: x wins byte 0 (ruling 5 of 0.5), w writes its sentinel 255, c1 its default 7")
    vec("bits", "ruling-06-roundtrip-drops-the-lines-with", "bits", "bits", "050607", "050000",
        model={"probe.x": "5", "probe.z": "5", "probe.w": "6", "probe.c1": "7"},
        ref=R + "ruling 6: decode is unchanged; y is mapped by no line, so no line with `with` is written")
    vec("bits", "ruling-06-sentinel-decodes-absent", "bits", "bits", "05ff00", "050000",
        model={"probe.x": "5", "probe.c1": "0", "@absent": ["probe.w"]},
        ref=R + "decode unchanged: 255 is w's sentinel (0.9)")

    # ==========================================================================
    # conformance-cond-gates (lsb): w at byte 0 with y; bit 0 gates x (byte
    # 1); bit 16 gates z (byte 3) with y.
    # ==========================================================================
    G = R + "with Version 0.17 Encode; "
    # z's line is suppressed: no block is open, no gate value; both gates
    # read 0; z is not mapped for step 6. Output: w's zero bits, 1 byte.
    vec("src", "gates-ruling-01-suppressed-field-opens-no-gate", "src", "gates", '{"z":5}', "00",
        ref=G + "ruling 1: it does not open a gate block and its key does not count as mapped for step 6")
    vec("src", "gates-companion-held-opens-the-gate", "src", "gates", '{"z":5,"y":1}', "00000105",
        ref=G + "y held: z opens its block, bit 16 gets 1; w absent writes zero bits")
    # w suppressed: its bits are not written, so bit 0 gets x's gate value 1.
    vec("src", "gates-ruling-01-suppressed-bits-take-the-gate-value", "src", "gates", '{"w":255,"x":5}', "0105",
        ref=G + "ruling 1: its bits are not written; step 3 gives bit 0 the gate value 1")
    # w held and written: bit 0 is written (1), no gate value, block held.
    vec("src", "gates-written-bits-hold-the-gate", "src", "gates", '{"w":255,"x":5,"y":1}', "ff05",
        ref=G + "w written in step 2: bit 0 is 1 and the block holds")
    vec("src", "gates-written-bits-close-the-gate", "src", "gates", '{"w":254,"x":5,"y":1}',
        error="transform-encode", ref=G + "w written in step 2: bit 0 is 0; x is mapped only in a block that is not held (step 6)")
    vec("src", "gates-ruling-01-suppressed-key-not-mapped-for-step-6", "src", "gates", '{"x":5,"z":6}', "0105",
        ref=G + "ruling 1: z's block is not held and its line does not count as mapping z")
    vec("gates", "ruling-06-roundtrip", "gates", "gates", "ff05", "0105",
        model={"probe.w": "255", "probe.x": "5", "@absent": ["probe.z"]},
        ref=G + "ruling 6: w decodes, and is dropped on re-encode")

    # ==========================================================================
    # conformance-cond-seq (msb): presence p 2 (p.1 x with y, p.2 z), opt (w
    # with y, default 9).
    # ==========================================================================
    S = R + "with Version 0.8 Presence; "
    # x suppressed: p.1 0; w suppressed: its default is not content: opt 0.
    # bits 00 0 -> 00.
    vec("src", "seq-ruling-01-suppressed-field-sets-no-presence-bit", "src", "seq", '{"x":5}', "00",
        ref=S + "ruling 1: not content for a presence or opt bit, and neither is its default")
    # p = 10, x = 00000101, opt 1 (w's default 9 is content, ruling 2 of
    # 0.8), w = 00001001: 1000 0001 | 0110 0001 | 001(0 0000) = 81 61 20.
    vec("src", "seq-companion-held", "src", "seq", '{"x":5,"y":1}', "816120",
        ref=S + "y held: p.1 = 1; the default of w is content for the opt bit (ruling 2 of 0.8)")
    # p = 01, z = 00000110, opt 0: 0100 0001 | 100(0 0000) = 41 80.
    vec("src", "seq-ruling-01-only-the-other-block", "src", "seq", '{"x":5,"z":6}', "4180",
        ref=S + "ruling 1: p.1 = 0, p.2 = 1")
    vec("src", "seq-ruling-01-value-and-default-not-content", "src", "seq", '{"w":3}', "00",
        ref=S + "ruling 1: w held but its line suppressed: the opt bit is 0")
    # p = 00, opt 1, w = 9: 0010 0001 | 001(0 0000) = 21 20.
    vec("src", "seq-default-is-content-when-not-suppressed", "src", "seq", '{"y":1}', "2120",
        ref=S + "ruling 2 of 0.8: a default in scope counts as present; the line is not suppressed")
    # ruling 5: x with y, also z, one byte (msb).
    vec("src", "seq-also-ruling-05-also-key-stays-a-candidate", "src", "seq-also", '{"x":1,"z":2}', "02",
        ref=S + "ruling 5: when a sequential field line is suppressed, its also keys stay candidates for the bits")
    vec("src", "seq-also-ruling-05-own-key-first-when-held", "src", "seq-also", '{"x":1,"z":2,"y":1}', "01",
        ref=S + "ruling 13 of 0.8: the earliest present key of the field is written")
    vec("seq-also", "ruling-05-roundtrip", "seq-also", "seq-also", "05", "05",
        model={"probe.x": "5", "probe.z": "5"}, ref=S + "ruling 5: z is held and written")
    vec("src", "seq-also-ruling-20-no-key-zero-bits-not-the-sentinel", "src", "seq-also", '{"x":1}', "00",
        ref=S + "ruling 20: a suppressed sequential line whose also keys give no value writes zero bits, not its sentinel (255)")
    vec("src", "seq-also-sentinel-when-not-suppressed", "src", "seq-also", '{"y":1}', "ff",
        ref=S + "y held, no key of the line has a value: the sentinel (ruling 24 of 0.9)")
    vec("seq-also", "sentinel-decodes-every-key-absent", "seq-also", "seq-also", "ff", "00",
        model={"@absent": ["probe.x", "probe.z"]}, ref=S + "ruling 24 of 0.9; on re-encode y is not held: ruling 20")
    vec("seq", "ruling-06-roundtrip", "seq", "seq", "816120", "00",
        model={"probe.x": "5", "probe.w": "9"}, ref=S + "ruling 6: y is mapped by no line")

    # ==========================================================================
    # conformance-cond-chain (msb): presence f fx (f.1 z with y), chain c1,
    # fx, c2 with y.
    # ==========================================================================
    # f: one octet 0000000 0; c1 = 1; fx 0: 00 01 0(000 0000) = 00 01 00.
    vec("src", "chain-ruling-01-suppressed-not-content-for-fx", "src", "chain", '{"z":3,"c1":1,"c2":2}', "000100",
        ref=S + "ruling 1: not content for an fx presence bit nor for the fx bit of a chain")
    # f: 1000000 0 = 80; z = 03; c1 = 01; fx 1, c2 00000010:
    # 1000 0001 | 0(000 0000) = 81 00.
    vec("src", "chain-companion-held", "src", "chain", '{"z":3,"c1":1,"c2":2,"y":1}', "8003018100",
        ref=S + "y held: f.1 = 1, the chain's fx = 1")
    vec("chain", "ruling-06-roundtrip", "chain", "chain", "8003018100", "000100",
        model={"probe.z": "3", "probe.c1": "1", "probe.c2": "2"}, ref=S + "ruling 6")

    # ==========================================================================
    # conformance-cond-protobuf: 1 x, 2 y with z, 3 z, 4 names (tag . with val)
    # ==========================================================================
    vec("protobuf", "companion-missing-nothing-written", "protobuf", "protobuf", "08011002", "0801",
        model={"probe.x": "1", "probe.y": "2"}, ref=R + "nothing on protobuf; ruling 6")
    vec("protobuf", "companion-held-roundtrip", "protobuf", "protobuf", "080110021803", "080110021803",
        model={"probe.z": "3"}, ref=R + "ruling 6: every `with` key held")
    vec("src", "protobuf-ruling-02-scalar-0-holds", "src", "protobuf", '{"y":2,"z":0}', "10021800",
        ref=R + "ruling 2: z = 0 holds")
    # item 0: tag a, val 1: 22 01 61. item 1: no val: an empty occurrence 22 00.
    vec("src", "protobuf-ruling-04-string-item-suppressed-is-empty", "src", "protobuf",
        '{"names":[{"t":"a","v":1},{"t":"b"}]}', "2201612200",
        ref=R + "ruling 4 with ruling 11 of 0.7: a pstring item without the value is an empty occurrence")

    # ==========================================================================
    # conformance-cond-xml: @id, @x with y, a/@y, names/name #text with val
    # ==========================================================================
    vec("xml", "companion-held-roundtrip", "xml", "xml", '<msg id="u" x="1"><a y="2"/></msg>',
        '<msg id="u" x="1"><a y="2"/></msg>', model={"probe.x": "1", "probe.y": "2"}, ref=R + "ruling 6")
    vec("xml", "companion-missing-attribute-not-written", "xml", "xml", '<msg id="u" x="1"/>', '<msg id="u"/>',
        model={"probe.x": "1", "@absent": ["probe.y"]}, ref=R + "nothing on text wires; ruling 6")
    vec("xml", "ruling-04-text-item-suppressed-is-an-empty-element", "xml", "xml",
        '<msg><names><name>a</name></names></msg>', '<msg><names><name/></names></msg>',
        model={"probe.names.#": "1", "probe.names[0].probe.tag": "a"},
        ref=R + "ruling 4: an empty element on xml; the item holds no val")
    vec("src", "xml-ruling-04-one-item-suppressed", "src", "xml", '{"names":[{"t":"a","v":1},{"t":"b"}]}',
        '<msg><names><name>a</name><name/></names></msg>', ref=R + "ruling 4")

    # ==========================================================================
    # conformance-cond-element. Line order: @id; d/@cs (label with x); a/@x;
    # element d; element e; e/f/@y; b/@z; element e; element g/h.
    # Placement (ruling 13): d at the label line, a, e at its element line,
    # b, g at its element line.
    # ==========================================================================
    E = "spec 0.18, xml: an element written when empty; "
    vec("element", "empty-elements-written", "element", "element", '<msg id="u"/>',
        '<msg id="u"><d/><e/><g><h/></g></msg>', model={"uid": "u"},
        ref=E + "each element at a path, and each on the way to it, is written even when nothing inside it is; a second line for e adds nothing")
    vec("element", "ruling-13-placed-at-the-first-line-under-it", "element", "element", '<msg><a x="1"/></msg>',
        '<msg><d/><a x="1"/><e/><g><h/></g></msg>', model={"probe.x": "1"},
        ref=E + "ruling 13: d is placed at the first line that addresses a path under it (d/@cs), before a")
    full_el = '<msg id="u"><d cs="L"/><a x="1"/><e><f y="2"/></e><b z="3"/><g><h/></g></msg>'
    vec("element", "ruling-13-every-line-written-roundtrip", "element", "element", full_el, full_el,
        model={"probe.label": "L", "probe.y": "2", "probe.z": "3"},
        ref=E + "ruling 13: e at its element line, before b; e holds f")
    vec("element", "suppressed-content-element-still-written", "element", "element", '<msg><d cs="L"/></msg>',
        '<msg><d/><e/><g><h/></g></msg>', model={"probe.label": "L"},
        ref=E + "label with x is suppressed; d is written empty")
    vec("element", "decode-ignores-the-line", "element", "element", '<msg><e><k/></e><g/></msg>',
        '<msg><d/><e/><g><h/></g></msg>', model={"@absent": ["probe.y"]},
        ref=E + "decode ignores the line; unmapped child elements are dropped (ruling 6 of 0.1.1)")
    vec("element-when", "ruling-19-when-present-names-no-position", "element-when", "element-when",
        '<msg><a x="1"/><b a="q" y="2"/></msg>', '<msg><a x="1"/><b y="2"/></msg>',
        model={"@kind": "k", "probe.x": "1", "probe.y": "2"},
        ref=E + "ruling 19: placement does not count `when <locator> present` lines, so a is placed before b; the when line writes nothing (ruling 27 of 0.5)")
    vec("element-when", "ruling-19-when-present-and-an-element-line", "element-when", "element-when",
        '<msg><b a="q"/></msg>', '<msg><a/><b/></msg>', model={"@kind": "k"},
        ref=E + "ruling 19: b is placed at `element b`, after `element a`; the when line names no position")
    vec("element-group", "ruling-12-prefix-of-a-group-path-written-when-the-list-is-absent", "element-group",
        "element-group", '<msg id="u"/>', '<msg id="u"><body/></msg>', model={"probe.items.#": "absent"},
        ref=E + "ruling 12: a path that is a strict prefix of a group's path writes the container even when the list is absent")
    vec("element-group", "ruling-12-container-with-items-roundtrip", "element-group", "element-group",
        '<msg><body><item name="a"/><item name="b"/></body><tail cs="C"/></msg>',
        '<msg><body><item name="a"/><item name="b"/></body><tail cs="C"/></msg>',
        model={"probe.items.#": "2", "probe.items[1].probe.label": "b"}, ref=E + "ruling 12")
    vec("src", "element-group-ruling-12-empty-list", "src", "element-group", '{"items":[],"cs":"C"}',
        '<msg><body/><tail cs="C"/></msg>', ref=E + "ruling 12 and ruling 20 of 0.7: an empty list writes no item, the element is written")

    # ==========================================================================
    # conformance-cond-time: time_ms at `ms` (int) and `t` (iso8601_short)
    # ==========================================================================
    T = "spec 0.18, A time without a zero fraction; "
    for label, ms, text in (
        ("fraction-5", 1500, "1970-01-01T00:00:01.5Z"),
        ("fraction-12", 120, "1970-01-01T00:00:00.12Z"),
        ("fraction-123", 123, "1970-01-01T00:00:00.123Z"),
        ("fraction-100", 100, "1970-01-01T00:00:00.1Z"),
        ("fraction-none", 0, "1970-01-01T00:00:00Z"),
        ("whole-second", 1000, "1970-01-01T00:00:01Z"),
        ("ruling-11-minus-1", -1, "1969-12-31T23:59:59.999Z"),
        ("ruling-11-minus-1000", -1000, "1969-12-31T23:59:59Z"),
        ("ruling-11-minus-1500", -1500, "1969-12-31T23:59:58.5Z"),
        ("ruling-11-last-instant-of-9999", 253402300799999, "9999-12-31T23:59:59.999Z"),
        ("ruling-11-first-instant-of-0000", -62167219200000, "0000-01-01T00:00:00Z"),
        ("2025", 1761739200010, "2025-10-29T12:00:00.01Z"),
    ):
        vec("time", "encode-" + label, "time", "time", '{"ms":%d}' % ms, '{"ms":%d,"t":"%s"}' % (ms, text),
            model={"time_ms": str(ms)}, ref=T + "encode; ruling 11: ms - 1000 x floor(ms / 1000)")
    vec("time", "ruling-11-after-9999-12-31", "time", "time", '{"ms":253402300800000}', error="transform-encode",
        ref=T + "ruling 11: an instant after 9999-12-31 is transform-encode")
    vec("time", "ruling-11-before-0000-01-01", "time", "time", '{"ms":-62167219200001}', error="transform-encode",
        ref=T + "ruling 11: an instant before 0000-01-01 is transform-encode")
    for label, text, ms, out in (
        ("fourth-digit-truncated", "1970-01-01T00:00:00.1239Z", 123, "1970-01-01T00:00:00.123Z"),
        ("fraction-999-9", "1970-01-01T00:00:00.9999Z", 999, "1970-01-01T00:00:00.999Z"),
        ("zero-fraction", "2025-10-29T12:00:00.000Z", 1761739200000, "2025-10-29T12:00:00Z"),
        ("no-fraction", "2025-10-29T12:00:00Z", 1761739200000, "2025-10-29T12:00:00Z"),
        ("one-digit", "1970-01-01T00:00:01.5Z", 1500, "1970-01-01T00:00:01.5Z"),
        ("offset", "1970-01-01T01:00:00.500+01:00", 500, "1970-01-01T00:00:00.5Z"),
        ("lowercase-designators", "1970-01-01t00:00:01.250z", 1250, "1970-01-01T00:00:01.25Z"),
    ):
        vec("time", "decode-" + label, "time", "time", '{"t":"%s"}' % text, '{"ms":%d,"t":"%s"}' % (ms, out),
            model={"time_ms": str(ms)}, ref=T + "decode is that of iso8601_ms: fraction digits beyond the third are truncated")
    vec("time-xml", "roundtrip-trailing-zero-removed", "time-xml", "time-xml",
        '<msg t="2025-10-29T12:00:00.120Z"/>', '<msg t="2025-10-29T12:00:00.12Z"/>',
        model={"time_ms": "1761739200120"}, ref=T + "on xml")
    vec("time-xml", "roundtrip-no-fraction", "time-xml", "time-xml",
        '<msg t="1969-12-31T23:59:59Z"/>', '<msg t="1969-12-31T23:59:59Z"/>', model={"time_ms": "-1000"}, ref=T + "on xml")
    vec("time-geojson", "roundtrip-trailing-zeros-removed", "time-geojson", "time-geojson",
        '{"type":"Feature","geometry":null,"properties":{"t":"2025-10-29T12:00:00.500Z"},"id":"u"}',
        '{"type":"Feature","geometry":null,"properties":{"t":"2025-10-29T12:00:00.5Z"},"id":"u"}',
        model={"time_ms": "1761739200500"}, ref=T + "on geojson")
    vec("time", "to-xml", "time", "time-xml", '{"ms":1761739200010}', '<msg t="2025-10-29T12:00:00.01Z"/>',
        ref=T + "json to xml")

    # ==========================================================================
    # ruling 22: conformance-cond-text. field 0 x; field 1 y with x; field 2
    # z with y, optional. Delimiter ",". Step 4 of 0.10: the record has one
    # more field than the highest index a line addresses (2), whether or not
    # the line writes; step 5 removes a last empty field whose every line is
    # optional.
    # ==========================================================================
    W = "spec 0.18 ruling 22 (`with` on text and tlv); "
    # x held: y written; y held: z written. 1,2,3
    vec("src", "text-ruling-22-every-companion-held", "src", "text", '{"x":1,"y":2,"z":3}', "1,2,3",
        ref=W + "0.10 Writing a record steps 1 and 6")
    # x absent: field 0 empty; y suppressed (x not held): field 1 empty, as
    # for an absent key; z: the entity holds y, so z is written. ,,3
    vec("src", "text-ruling-22-suppressed-field-written-empty", "src", "text", '{"y":2,"z":3}', ",,3",
        ref=W + "on text an empty field (Version 0.10); y is held by the entity although its own line is suppressed (ruling 2)")
    # y absent: field 1 empty (not optional). z suppressed (y not held):
    # field 2 empty; its one line is optional, so step 5 removes it; field 1
    # stops the removal. 1,
    vec("src", "text-ruling-22-suppressed-optional-last-field-removed", "src", "text", '{"x":1,"z":3}', "1,",
        ref=W + "the suppressed line writes an empty field, which step 5 of 0.10 removes as for an absent key: it is last and optional")
    # field 0 empty; y suppressed: field 1 empty and not optional; z absent
    # (y held, so not suppressed), empty and optional: removed. ","
    vec("src", "text-ruling-22-suppressed-non-optional-field-kept", "src", "text", '{"y":2}', ",",
        ref=W + "a suppressed line still addresses its field; field 1 is not optional, so step 5 stops there")
    vec("text", "ruling-22-roundtrip-every-companion-held", "text", "text", "1,2,3", "1,2,3",
        model={"probe.x": "1", "probe.y": "2", "probe.z": "3"}, ref=W + "ruling 6: byte-exact when every `with` key is held")
    # decode is unchanged (y = 2, z = 3); x absent, so y is dropped. ,,3
    vec("text", "ruling-22-roundtrip-companion-missing-field-emptied", "text", "text", ",2,3", ",,3",
        model={"probe.y": "2", "probe.z": "3", "@absent": ["probe.x"]},
        ref=W + "ruling 6: the value whose companion key is missing decodes and is written as an empty field")

    # ==========================================================================
    # ruling 22: conformance-cond-tlv. Tags 1 x uint:1, 2 y with x uint:1,
    # 3 z with s1 uint:2, 4 s1 utf8. Each item: tag byte, length byte, value.
    # ==========================================================================
    # 01 01 01 | 02 01 02 | 03 02 00 03 | 04 01 61
    vec("src", "tlv-ruling-22-every-companion-held", "src", "tlv", '{"x":1,"y":2,"z":3,"s1":"a"}',
        "01010102010203020003040161", ref=W + "0.13 Writing a message steps 1 and 2")
    # s1 not held: z writes no item. 01 01 01 | 02 01 02
    vec("src", "tlv-ruling-22-suppressed-no-item", "src", "tlv", '{"x":1,"y":2,"z":3}', "010101020102",
        ref=W + "on tlv no item (Version 0.13: an absent key writes no item)")
    # x absent and y suppressed: neither writes an item. s1 = "" holds (ruling
    # 2): 03 02 00 03; s1 "" is an item of length 0: 04 00.
    vec("src", "tlv-ruling-22-empty-text-holds-other-suppressed", "src", "tlv", '{"y":2,"z":3,"s1":""}',
        "030200030400", ref=W + "y suppressed writes no item; ruling 2: the empty text holds; 0.13: a key holding the empty string writes an item of length 0")
    vec("tlv", "ruling-22-roundtrip-every-companion-held", "tlv", "tlv", "01010102010203020003040161",
        "01010102010203020003040161", model={"probe.x": "1", "probe.y": "2", "probe.z": "3", "probe.s1": "a"},
        ref=W + "ruling 6")
    # decode y = 2, z = 3, s1 = a; x absent: y writes no item. 03 02 00 03 | 04 01 61
    vec("tlv", "ruling-22-roundtrip-companion-missing-item-dropped", "tlv", "tlv", "02010203020003040161",
        "03020003040161", model={"probe.y": "2", "probe.z": "3", "@absent": ["probe.x"]},
        ref=W + "ruling 6: decoded, then dropped on re-encode")

    # ==========================================================================
    # ruling 23: conformance-cond-armor (msb, armor sixbit). Bits 0-5 x; 6-11
    # w with y; 12-17 z with s1, optional. A character is six bits, 0 to 39 as
    # 0x30 + v, 40 to 63 as 0x38 + v (0.14). L (0.14, ruling 14 of 0.17): the
    # furthest bit of the lines, an optional field only when written; a
    # suppressed line counts as any line does (ruling 23 of 0.18).
    # ==========================================================================
    A = "spec 0.18 ruling 23 (`with` under six-bit armor); "
    # every line written: L = 18. x = 40 -> 0x38 + 40 = 0x60 "`"; w 3 "3";
    # z 2 "2".
    vec("src", "armor-ruling-23-every-companion-held", "src", "armor", '{"x":40,"w":3,"z":2,"y":0,"s1":""}', "`32",
        ref=A + "L = 18 bits, three characters; 40 is written 0x38 + 40")
    # w suppressed: zero bits, counts: bits 6-11 are 0. z suppressed and
    # optional: not counted. L = 12, two characters "1" "0". (Were w not
    # counted, L = 6 and "1"; were z counted, L = 18 and "100".)
    vec("src", "armor-ruling-23-suppressed-counts-optional-does-not", "src", "armor", '{"x":1,"w":3,"z":2}', "10",
        ref=A + "a suppressed line writes zero bits and counts toward L; an optional field that `with` suppresses is not written and does not count")
    # y = 0 holds: w written; z suppressed, not counted. L = 12: "1" "3".
    vec("src", "armor-ruling-23-optional-suppressed-text-shorter", "src", "armor", '{"x":1,"w":3,"z":2,"y":0}', "13",
        ref=A + "the suppressed optional field is not written, so the text ends after w")
    # s1 = "" holds: z written, L = 18; w suppressed, zero bits: "1" "0" "2".
    vec("src", "armor-ruling-23-suppressed-zero-bits-inside", "src", "armor", '{"x":1,"w":3,"z":2,"s1":""}', "102",
        ref=A + "a suppressed line writes zero bits")
    # c2 (bits 18-23, optional, absent 63, with c1): c1 absent, so c2 is
    # suppressed: no sentinel (ruling 1), not counted (ruling 23). w zero
    # bits, z written: L = 18, "1" "0" "2"; the text ends before c2.
    vec("src", "armor-ruling-23-optional-with-sentinel-suppressed-not-counted", "src", "armor",
        '{"x":1,"w":3,"z":2,"s1":""}', "102",
        ref=A + "ruling 1: a suppressed line has no sentinel; an optional field that `with` suppresses is not written and does not count")
    # c1 = 0 holds: c2 is absent with a sentinel: 63 written, counts (ruling
    # 12 of 0.14). L = 24; 63 is 0x38 + 63 = 0x77 "w".
    vec("src", "armor-ruling-23-optional-with-sentinel-companion-held", "src", "armor",
        '{"x":1,"w":3,"z":2,"s1":"","c1":0}', "102w",
        ref=A + "ruling 12 of 0.14: a field with `absent` whose key is absent writes its first sentinel and counts toward L, optional or not")
    # decode x = 1, w = 3, z = 2; y and s1 are mapped by no line: as above, "10".
    vec("armor", "ruling-23-roundtrip-drops-the-lines-with", "armor", "armor", "132", "10",
        model={"probe.x": "1", "probe.w": "3", "probe.z": "2"},
        ref=A + "ruling 6: decode is unchanged; on re-encode w writes zero bits and counts, z does not count")
    # decode of a text that stops before the optional field: z absent (0.14).
    vec("armor", "optional-beyond-the-input-absent", "armor", "armor", "13", "10",
        model={"probe.x": "1", "probe.w": "3", "@absent": ["probe.z"]},
        ref=A + "0.14: an optional field beyond the input is absent")

    # ==========================================================================
    # conformance-derive-functions, from 78: tokens, has_token, text_if
    # (model/probe.def). "context": {} so that the derivations run.
    # ==========================================================================
    DF = "conformance-derive-functions"
    counters[DF] = 77           # 1 to 77 are written by other scripts
    D = "spec 0.18, Derive functions; "

    def dvec(name, inp, expect, state, absent=(), ref=""):
        model = {"@complete": True}
        model.update(state)
        if absent:
            model["@absent"] = list(absent)
        vec(DF, name, DF, DF, inp, expect, model=model, context={}, ref=D + ref)

    # fl_c = 2 is not 0. flags = alpha,gamma (pass 1); fl_b then absent:
    # has_token(alpha,gamma, beta) = 0 in the same pass.
    dvec("tokens-present-and-not-0-in-order", '{"fla":1,"flc":2}',
         '{"fla":1,"flb":0,"flc":2,"flags":"alpha,gamma"}', {"probe.flags": "alpha,gamma", "probe.fl_b": "0"},
         ref="tokens: the tokens whose argument is present and not 0, in order, joined by the separator; ruling 8")
    dvec("tokens-every-flag", '{"fla":1,"flb":1,"flc":1}', '{"fla":1,"flb":1,"flc":1,"flags":"alpha,beta,gamma"}',
         {"probe.flags": "alpha,beta,gamma"}, ref="tokens")
    dvec("tokens-negative-is-not-0", '{"fla":-1}', '{"fla":-1,"flb":0,"flc":0,"flags":"alpha"}',
         {"probe.flags": "alpha", "probe.fl_b": "0", "probe.fl_c": "0"}, ref="tokens: not 0")
    dvec("tokens-all-0-absent", '{"fla":0,"flb":0,"flc":0}', '{"fla":0,"flb":0,"flc":0}', {},
         absent=["probe.flags"], ref="tokens: absent when no argument is present and not 0")
    dvec("tokens-some-0-rest-absent", '{"flb":0}', '{"flb":0}', {}, absent=["probe.flags", "probe.fl_a", "probe.fl_c"],
         ref="tokens: absent when no argument is present and not 0; has_token has no argument then")
    dvec("ruling-08-absent-flag-becomes-0", '{"flb":1}', '{"fla":0,"flb":1,"flc":0,"flags":"beta"}',
         {"probe.flags": "beta", "probe.fl_a": "0", "probe.fl_c": "0"},
         ref="ruling 8: a round trip through tokens and has_token turns an absent flag into a present 0")
    dvec("ruling-10-has-token-compares-exactly", '{"flags":"alpha, beta"}',
         '{"fla":1,"flb":0,"flc":0,"flags":"alpha, beta"}', {"probe.fl_a": "1", "probe.fl_b": "0", "probe.fl_c": "0"},
         ref="ruling 10: `a, b` split at comma has the parts `a` and ` b`")
    dvec("has-token-empty-parts-ignored", '{"flags":",,beta,"}', '{"fla":0,"flb":1,"flc":0,"flags":",,beta,"}',
         {"probe.fl_b": "1"}, ref="has_token: empty parts ignored")
    dvec("ruling-10-has-token-case-sensitive", '{"flags":"Alpha,BETA"}',
         '{"fla":0,"flb":0,"flc":0,"flags":"Alpha,BETA"}', {"probe.fl_a": "0", "probe.fl_b": "0"},
         ref="ruling 10: case-sensitive")
    dvec("has-token-of-the-empty-text", '{"flags":""}', '{"fla":0,"flb":0,"flc":0,"flags":""}',
         {"probe.fl_a": "0", "probe.fl_c": "0"}, ref="has_token: the empty text has no part")
    dvec("has-token-sets-only-absent-flags", '{"fla":5,"flags":"gamma"}',
         '{"fla":5,"flb":0,"flc":1,"flags":"gamma"}', {"probe.fl_a": "5", "probe.fl_c": "1"},
         ref="0.6 Derived keys: a line whose target is absent; tokens is not applied, flags is present")
    dvec("has-token-part-is-not-a-substring", '{"flags":"alphabet"}', '{"fla":0,"flb":0,"flc":0,"flags":"alphabet"}',
         {"probe.fl_a": "0"}, ref="has_token: one of the parts")
    # ruling 7: pass order. ptok's line comes before fl_late's.
    dvec("ruling-07-value-fixed-in-the-first-pass-with-an-argument", '{"flp":1,"flsrc":0}',
         '{"flp":1,"flsrc":0,"fllate":1,"ptok":"p"}', {"probe.ptok": "p", "probe.fl_late": "1"},
         ref="ruling 7: fl_p is present in pass 1, fl_late is set later in that pass; ptok is not changed in pass 2")
    dvec("ruling-07-set-in-the-pass-its-first-argument-appears", '{"flsrc":0}',
         '{"flsrc":0,"fllate":1,"ptok":"q"}', {"probe.ptok": "q"},
         ref="ruling 7: no argument is present in pass 1; fl_late is, in pass 2")
    dvec("ruling-07-both-arguments-present", '{"flp":1,"fllate":1}', '{"flp":1,"fllate":1,"ptok":"p/q"}',
         {"probe.ptok": "p/q"}, ref="tokens with a one-character separator")
    dvec("ruling-07-stays-absent-until-an-argument-is-not-0", '{"flp":0,"flsrc":0}',
         '{"flp":0,"flsrc":0,"fllate":1,"ptok":"q"}', {"probe.ptok": "q", "probe.fl_late": "1"},
         ref="ruling 7: fl_p = 0 in pass 1 leaves ptok absent; fl_late = 1 sets it in pass 2")
    dvec("ruling-07-later-argument-0", '{"flsrc":5}', '{"flsrc":5,"fllate":0}', {"probe.fl_late": "0"},
         absent=["probe.ptok"], ref="ruling 7: fl_late is 0, so no argument is present and not 0")
    # ruling 9: separator names; é is one code point.
    dvec("ruling-09-separator-names-space-and-one-code-point", '{"sp1":1,"sp2":1}',
         '{"sp1":1,"sp2":1,"spt":"x y","ut":"aéb"}', {"probe.spt": "x y", "probe.ut": "aéb"},
         ref="ruling 9: space is U+0020; a character is one Unicode code point")
    dvec("ruling-09-one-token", '{"sp1":0,"sp2":3}', '{"sp1":0,"sp2":3,"spt":"y","ut":"b"}',
         {"probe.spt": "y", "probe.ut": "b"}, ref="tokens")
    dvec("ruling-09-join-space-joins-with-the-text-space", '{"w1":"x","w2":"y"}',
         '{"w1":"x","w2":"y","wj":"xspacey"}', {"probe.wj": "xspacey"},
         ref="ruling 9: the names apply to tokens and has_token only; join:space still joins with the text space")
    for label, text, sp, col in (
        ("a-space-b", "a b", 1, 0),
        ("a-colon-b", "a:b", 0, 1),
        ("spaces-around", "  b  ", 1, 0),
        ("tab-is-not-space", "a\tb", 0, 0),
        ("b-alone", "b", 1, 1),
    ):
        dvec("ruling-09-has-token-" + label, json.dumps({"wtxt": text}),
             '{"wtxt":%s,"wsp":%d,"wcol":%d}' % (json.dumps(text), sp, col),
             {"probe.wsp": str(sp), "probe.wcol": str(col)}, ref="ruling 9: space and colon name U+0020 and :")
    dvec("text-if-not-0", '{"tifin":1}', '{"tifin":1,"tif":"a:b"}', {"probe.tif": "a:b"},
         ref="text_if: the text when a is not 0; the text may contain :")
    dvec("text-if-negative", '{"tifin":-3}', '{"tifin":-3,"tif":"a:b"}', {"probe.tif": "a:b"}, ref="text_if")
    dvec("text-if-0-absent", '{"tifin":0}', '{"tifin":0}', {}, absent=["probe.tif"], ref="text_if: absent when a is 0")
    dvec("text-if-argument-absent", '{"w1":"x"}', '{"w1":"x"}', {}, absent=["probe.tif", "probe.wj"],
         ref="text_if: absent when a is absent")

    # ==========================================================================
    # load vectors from 680
    # ==========================================================================
    core = ("module core\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey uid string -\n"
            "key type string -\nkey lat float deg\nkey lon float deg\nkey callsign string -\nkey time_ms int ms\n")
    probe = ("module probe\nversion 0.1.0\ndistribution public\nsource \"probe\"\nkey x int -\nkey y int -\n"
             "key s string -\nkey f float -\nkey label string -\nkey val int -\nkey tag string -\n"
             "list items \"a list\"\nlist nums \"scalar items\"\n")
    head = 'format probe\nversion 0.18.0\ndistribution public\nsource "probe"\nuses probe\n'
    js, xm = head + "wire json\n", head + "wire xml\nroot msg\n"
    pb, fixed = head + "wire protobuf\n", head + "wire bits\nword_bytes 1\n"
    seq = head + "wire bits\nlayout sequential\n"
    lnum = [679]

    def load(name, text, error="bad-directive", models=None):
        lnum[0] += 1
        full = "%d-cond-%s" % (lnum[0], name)
        mods = models or [core, probe]
        got = None
        try:
            m = gtcheck.Model()
            for t in mods:
                m.add(t)
            gtcheck.load_pack(text, m)
        except gtcheck.CheckError as e:
            got = e.kind
        assert got == error, (full, error, got)
        d = {"name": full, "models": mods, "pack": text}
        if error:
            d["expect_error"] = error
        sink.write("packs/conformance/load-vectors/%s.json" % full, json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        written["load"] = written.get("load", 0) + 1

    # `with`
    load("with-on-json-loads", js + "field probe.x x int with probe.y\ngroup probe.items items\n"
         "  field probe.val v int with probe.label\nend\ngroup probe.nums nums\n  field probe.val . int with probe.tag\nend\n",
         None)
    load("with-on-xml-with-a-list-key-loads", xm + "field probe.x @x int with probe.items\n", None)
    load("with-on-a-string-item-of-protobuf-loads", pb + "group probe.items 1\n  field probe.tag . pstring with probe.val\nend\n", None)
    load("with-in-a-gate-block-and-with-a-sentinel-loads", fixed + "if 0:0:1 1\n  field probe.x 0:8:8 uint absent 255 with probe.y\nend\n", None)
    load("with-in-a-sequential-block-loads", seq + "opt\n  field probe.x 8 uint with probe.y\nend\n", None)
    load("with-given-twice", js + "field probe.x x int with probe.y with probe.y\n")
    load("with-without-a-key", js + "field probe.x x int with\n")
    load("with-undeclared-key", js + "field probe.x x int with probe.nosuch\n", "undeclared-key")
    load("with-key-of-a-module-not-used", js + "field probe.x x int with track.speed\n", "module-not-used")
    load("ruling-05-module-not-used-before-undeclared-key", js + "field probe.x x int with probe.nosuch\n"
         "field probe.y y int with track.speed\n", "module-not-used")
    load("ruling-05-with-on-a-const", js + "const k 1 with probe.y\n")
    load("ruling-05-with-on-a-group", js + "group probe.items items with probe.y\n  field probe.val v int\nend\n")
    load("ruling-05-with-on-also", seq + "field probe.x 8 uint\nalso probe.y with probe.x\n")
    load("ruling-04-with-on-a-packed-protobuf-item", pb + "group probe.nums 1\n  field probe.val . pvarint with probe.x\nend\n")
    load("ruling-02-with-a-list-key-and-a-key-the-group-does-not-map-loads",
         js + "field probe.x x int with probe.nums\ngroup probe.items items\n  field probe.label l string with probe.x\nend\n", None)
    # iso8601_short
    load("iso8601-short-on-text-wires-loads", xm + "field time_ms @t iso8601_short\n", None)
    load("iso8601-short-on-geojson-loads", head + "wire geojson\nfield time_ms properties.t iso8601_short\n", None)
    load("ruling-11-iso8601-short-on-bits", fixed + "field time_ms 0:0:64 iso8601_short\n")
    load("ruling-11-iso8601-short-on-protobuf", pb + "field time_ms 1 iso8601_short\n")
    load("iso8601-short-on-a-string-key", js + "field probe.s t iso8601_short\n", "key-type-mismatch")
    # element
    load("element-loads", xm + "field uid @id string\nelement detail\nelement a/b\nelement a/b\n"
         "kind k\nelement c\n", None)
    load("element-on-json", js + "element detail\n")
    load("element-with-an-attribute", xm + "element detail/@a\n")
    load("element-with-text", xm + "element detail/#text\n")
    load("ruling-13-element-empty-path", xm + 'element ""\n')
    load("ruling-13-element-leading-slash", xm + "element /detail\n")
    load("ruling-13-element-trailing-slash", xm + "element detail/\n")
    load("ruling-13-element-empty-step", xm + "element a//b\n")
    load("element-without-a-path", xm + "element\n")
    load("element-with-two-paths", xm + "element a b\n")
    load("ruling-12-element-inside-a-group", xm + "group probe.items body/item\n  element x\nend\n")
    load("ruling-12-element-on-a-group-path", xm + "group probe.items body/item\n  field probe.label @n string\nend\n"
         "element body/item\n")
    load("ruling-12-element-through-a-group-path", xm + "element body/item/x\ngroup probe.items body/item\n"
         "  field probe.label @n string\nend\n")
    load("ruling-12-element-on-a-prefix-of-a-group-path-loads", xm + "element body\ngroup probe.items body/item\n"
         "  field probe.label @n string\nend\n", None)
    # derive functions
    def mod(lines):
        return [core, probe + "key t1 int -\nkey t2 int -\nkey out string -\nkey hit int -\n" + lines]
    load("derive-every-function-loads", js + "field uid id string\n", None,
         mod("derive probe.out tokens:comma:a,b probe.t1 probe.t2\nderive probe.out tokens:é:a probe.t1\n"
             "derive probe.out tokens:space:a-1,b.2 probe.t1 probe.t2\nderive probe.hit has_token:colon:a probe.out\n"
             "derive probe.hit has_token:/:a probe.out\nderive probe.out text_if:a:b:c probe.t1\n"))
    load("tokens-fewer-tokens-than-arguments", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma:a probe.t1 probe.t2\n"))
    load("tokens-more-tokens-than-arguments", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma:a,b,c probe.t1 probe.t2\n"))
    load("tokens-duplicate-token", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma:a,a probe.t1 probe.t2\n"))
    load("tokens-empty-token", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma:a, probe.t1 probe.t2\n"))
    load("tokens-token-holds-the-separator", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:/:a/b probe.t1\n"))
    load("tokens-string-argument", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma:a probe.s\n"))
    load("tokens-int-target", js + "field uid id string\n", models=mod(
        "derive probe.hit tokens:comma:a probe.t1\n"))
    load("tokens-no-token-list", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:comma probe.t1\n"))
    load("ruling-09-separator-name-not-lowercase", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:Space:a probe.t1\n"))
    load("separator-of-two-characters", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:ab:x probe.t1\n"))
    load("separator-comma-character", js + "field uid id string\n", models=mod(
        "derive probe.out tokens:,:a probe.t1\n"))
    load("separator-empty", js + "field uid id string\n", models=mod(
        "derive probe.out tokens::a probe.t1\n"))
    load("has-token-two-arguments", js + "field uid id string\n", models=mod(
        "derive probe.hit has_token:comma:a probe.out probe.s\n"))
    load("has-token-int-argument", js + "field uid id string\n", models=mod(
        "derive probe.hit has_token:comma:a probe.t1\n"))
    load("has-token-string-target", js + "field uid id string\n", models=mod(
        "derive probe.out has_token:comma:a probe.s\n"))
    load("has-token-empty-token", js + "field uid id string\n", models=mod(
        "derive probe.hit has_token:comma: probe.s\n"))
    load("has-token-two-tokens", js + "field uid id string\n", models=mod(
        "derive probe.hit has_token:comma:a,b probe.s\n"))
    load("text-if-text-with-a-no-break-space-loads", js + "field uid id string\n", None, mod(
        "derive probe.out text_if:a\u00a0b probe.t1\n"))
    load("text-if-empty-text", js + "field uid id string\n", models=mod(
        "derive probe.out text_if: probe.t1\n"))
    load("text-if-string-argument", js + "field uid id string\n", models=mod(
        "derive probe.out text_if:a probe.s\n"))
    load("text-if-int-target", js + "field uid id string\n", models=mod(
        "derive probe.hit text_if:a probe.t1\n"))
    load("text-if-two-arguments", js + "field uid id string\n", models=mod(
        "derive probe.out text_if:a probe.t1 probe.t2\n"))
    # rulings 15 to 18, from 522
    load("ruling-16-element-step-with-a-hash", xm + "element a#b\n")
    load("ruling-16-element-step-with-an-at", xm + "element x@y\n")
    load("ruling-17-with-on-a-dot-field-of-a-group-that-is-not-packed-loads",
         pb + "group probe.items 1\n  field probe.tag . pstring\n  field probe.val . pvarint with probe.x\nend\n", None)
    load("ruling-17-with-in-a-packed-group-of-two-numeric-fields",
         pb + "group probe.nums 1\n  field probe.val . pvarint\n  field probe.x . psint with probe.y\nend\n")
    load("ruling-18-default-with-a-trailing-space", js + 'field probe.x x int\ndefault probe.x "5 "\n',
         "key-type-mismatch")
    # rulings 21: iso8601_short on the text and tlv wires
    load("ruling-21-iso8601-short-on-text", head + "wire text\nfield time_ms 0 iso8601_short\n")
    load("ruling-21-iso8601-short-on-tlv", head + "wire tlv\nfield time_ms 5 iso8601_short\n")
    load("ruling-25-element-argument-count-is-a-line-check", head + "wire xml\nroot msg\nelement a b\nbogus\n")
    assert lnum[0] == 744, lnum[0]
    return written


def main(argv=None):
    return genio.vector_main("conformance-cond-vectors.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
