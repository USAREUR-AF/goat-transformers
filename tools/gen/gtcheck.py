#!/usr/bin/env python3
"""gtcheck: load and check model modules and packs, for the generators.

Every generator in this directory reads its own output back through this
module before it reports success. The module is written from
spec/engine-spec.md (Versions 0.1 to 0.10, 0.13, 0.14, the gate blocks of 0.17, the
`with` option, `element`, `iso8601_short` and derive functions of 0.18, 0.19, and
the kind selection of 0.20: `when` lists and ranges, `requires <key>=<value>`
and `switch` blocks, and the sequential extents and counts of 0.21: `group
<list> rest`, `group <list> last`, `count <name> <len> [plus <n>]` with
`group <list> count @<name>` (two names, `count @<a> @<b>`, from 0.31), and
the long and terminated fields of 0.22:
the `hex` transform, the set `ascii8`, the locator `until:<code>`, the field
option `stop <code>` and `bit_order msb-lsb`) and imports no engine, so a generator
stays independent of the engines it writes packs for.

What it checks is what an engine checks when it loads a file: the line grammar,
the header, blocks and kinds, locators and transforms for the pack's wire, and
the model rules (every module used is loaded, every mapped key is declared, and
the transform of every line yields the key's declared type). It does not decode
or encode a message.

A refusal is a CheckError. It carries the error kind the specification names
(`bad-directive`, `undeclared-key`, ...), the file label and, for an error that
belongs to one line, the line number:

    packs/demo/pack.def:14: undeclared-key: field maps `track.speed`, which module `track` does not declare

Use from a generator:

    model = gtcheck.Model()
    model.load_dir(model_dir)                    # core first, then by `uses`
    pack = gtcheck.load_pack(text, model, label="packs/x/pack.def")

Use from a shell, to check files of a checkout:

    python3 -I tools/gen/gtcheck.py --model model packs/geojson/pack.def

Python 3 standard library only.
"""
import argparse
import math
import os
import re
import sys

KEY_TYPES = ("string", "float", "int")
DISTRIBUTIONS = ("public", "controlled")

# The type a transform yields (engine-spec 0.4 "The type a transform yields",
# with the additions of 0.5), by the wires it is valid on.
TEXT_TRANSFORMS = {"string": "string", "float": "float", "int": "int", "iso8601_ms": "int", "iso8601_s": "int",
                   "scale": "float", "iscale": "int",
                   # engine-spec 0.18: xml, json and geojson only (ruling 11)
                   "iso8601_short": "int"}
JSON_TRANSFORMS = dict(TEXT_TRANSFORMS, bool="int")
BITS_TRANSFORMS = {"uint": "int", "twos": "int", "linscale": "float", "uscale": "float",
                   "sscale": "float", "f32": "float", "f64": "float", "ascii": "string",
                   "sixbit": "string",      # `sixbit`: 0.14, either layout and either armor
                   # engine-spec 0.15
                   "uiscale": "int", "siscale": "int", "smag": "int", "smscale": "float",
                   "f32scale": "float", "f64scale": "float", "chars": "string", "octal": "string",
                   # engine-spec 0.22
                   "hex": "string"}
CHAR_SETS = {"icao6": 6, "ais6": 6, "ascii7": 7, "ascii8": 8}
BIT_ORDERS = ("lsb", "msb", "msb-lsb")      # msb-lsb: engine-spec 0.22
PROTOBUF_TRANSFORMS = {"pstring": "string", "pvarint": "int", "psint": "int",
                       "pdouble": "float", "pfloat": "float"}
# 0.10 "Transforms for `text`": `int:<w>` is `int` with a parameter; `dec`,
# `dm`, `hms` and `hms_dmy` are valid on this wire only.
RECORD_TRANSFORMS = dict(TEXT_TRANSFORMS, dec="float", dm="float", hms="float", hms_dmy="int")
del RECORD_TRANSFORMS["iso8601_short"]   # 0.18 ruling 21: xml, json and geojson only
PAIR_TRANSFORMS = ("dm", "hms_dmy")
NUMERIC_TEXT = ("int", "float", "dec")
# 0.13 "Transforms for `tlv`": `utf8` and `hex` are valid on this wire only;
# any other name is `bad-directive` on it (ruling 8).
TLV_TRANSFORMS = {"uint": "int", "twos": "int", "uscale": "float", "sscale": "float",
                  "f32": "float", "f64": "float", "utf8": "string", "hex": "string"}
TLV_SIZED = ("uint", "twos", "uscale", "sscale")       # `:<n>` required
TLV_FLOAT_SIZE = {"f32": 4, "f64": 8}                  # `:<n>` optional, and then this
# 0.19 "Transforms on UPER locators": the transforms each UPER locator takes and
# the type each yields; any other transform on such a locator is `bad-directive`
UPER_TRANSFORMS = {"int": {"uint": "int", "twos": "int", "uscale": "float", "sscale": "float"},
                   "enum": {"uint": "int"}, "chars": {"ascii": "string"},
                   "octets": {"hex": "string", "utf8": "string"}}
# 0.28 "Transforms for `cbor`": these are valid on this wire and every other
# name is `bad-directive` on it, after the file is read.
CBOR_TRANSFORMS = {"uint": "int", "int": "int", "float": "float", "text": "string",
                   "bytes": "string", "bool": "int", "epoch_s": "int"}
TRANSFORMS = {"xml": TEXT_TRANSFORMS, "geojson": TEXT_TRANSFORMS, "json": JSON_TRANSFORMS,
              "bits": BITS_TRANSFORMS, "protobuf": PROTOBUF_TRANSFORMS, "text": RECORD_TRANSFORMS,
              "tlv": TLV_TRANSFORMS, "cbor": CBOR_TRANSFORMS}
WIRES = tuple(TRANSFORMS)

# the directives of the text wire (0.10): at most once, before the first `kind`
TEXT_HEADER = ("delimiter", "start", "checksum")
# the directives of the tlv wire (0.13): at most once, before the first `kind`,
# with their allowed values (`key` and `checksum sum16 <tag>` are checked apart)
TLV_HEADER = ("tag", "length", "key", "checksum")
TLV_FORMS = {"tag": ("ber-oid", "1", "2", "4"), "length": ("ber", "1", "2", "4")}
# the armor of the bits wire (0.14): at most once, before the first `kind`
ARMORS = ("hex", "sixbit")
# the encoding of the bits wire (0.19): at most once, before the first `kind`
ENCODINGS = ("none", "uper")
HEADER = ("format", "version", "distribution", "source", "uses", "wire", "layout",
          "bit_order", "word_bytes", "armor", "encoding") + TEXT_HEADER
TABLES = ("map", "typemap")
BLOCKS = ("group", "if", "opt", "chain", "length", "ext", "choice")
UPER_ONLY = ("ext", "choice", "alt")          # 0.19 ruling 9; `alt` closes at the next `alt` or `end`
SEQUENTIAL_ONLY = ("pad", "align", "presence", "opt", "chain", "fx", "length", "also",
                   # spec 0.21: a count before other fields
                   "count")
# spec 0.17: the lines a gate block of a fixed layout may hold
GATE_BODY = ("field", "const", "default", "if")
DIRECTIVES = HEADER + TABLES + BLOCKS + SEQUENTIAL_ONLY + (
    "root", "kind", "when", "requires", "field", "const", "default", "end", "tag", "key",
    # spec 0.18: an xml element written when empty
    "element", "alt",
    # spec 0.20: a switch on a decoded value
    "switch", "case", "else")

_INT = re.compile(r"-?[0-9]+\Z")
_UINT = re.compile(r"[0-9]+\Z")
_NUMBER = re.compile(r"[-+]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?\Z")
_FRACTION = re.compile(r"([0-9]+)/([0-9]+)\Z")  # spec 0.15 ruling 25: unsigned
_BITS_LOCATOR = re.compile(r"([0-9]+):([0-9]+):([0-9]+)\Z")
_BITS_START = re.compile(r"([0-9]+):([0-9]+)\Z")
_PROTOBUF_PATH = re.compile(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*\Z")
_CONDITION = re.compile(r"(!?)([^.!]+)\.([0-9]+)\Z")
_TEXT_COLUMN = re.compile(r"([0-9]+):([0-9]+):([0-9]+)\Z")
_TEXT_PAIR = re.compile(r"([0-9]+)\+([0-9]+)\Z")
_TLV_TAG = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_TLV_LOCATOR = re.compile(r"((?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))*)(?::([0-9]+))?\Z")
_TLV_KEY = re.compile(r"(?:[0-9a-f]{2}){1,64}\Z")
_GATE = re.compile(r"(!?)([0-9]+:[0-9]+:[0-9]+)\Z")
# 0.19 ruling 15: an optional `-` and digits with no leading zero, `-0` refused
_UPER_NUMBER = re.compile(r"(?:0|-?[1-9][0-9]*)\Z")
_UPER_LOCATOR = re.compile(r"(int|enum|chars|octets):(.*)\Z")
INT64 = (-(1 << 63), (1 << 63) - 1)
# spec 0.20: a value of a `when` list on bits and protobuf: digits, or a range
_WHEN_RANGE = re.compile(r"([0-9]+)\.\.([0-9]+)\Z")
# spec 0.21 ruling 16: a `plus` value of a count line, within signed 64 bits
_PLUS = re.compile(r"-?[0-9]+\Z")
_COUNT_NAME = re.compile(r"[^.!@]+\Z")
# spec 0.20: the lines a `case` or `else` body may hold
CASE_BODY = ("field", "also", "const", "pad", "align", "default", "presence", "if", "opt", "chain",
             "length", "group", "switch", "count")
# the steps of a cbor path (0.28 "Paths")
_CBOR_INT_KEY = re.compile(r"-?(?:0|[1-9][0-9]*)\Z")
_CBOR_POSITION = re.compile(r"\[(0|[1-9][0-9]*)\]\Z")
_CBOR_TEXT_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
CBOR_INT_MIN, CBOR_UINT_MAX = -(1 << 63), (1 << 64) - 1


def cbor_path(text, dot=False):
    """The steps of a cbor path (0.28 "Paths") as a tuple of (kind, value):
    ("int", n) for an integer key, ("pos", i) for an array position `[i]`,
    ("text", s) for a text key; `()` for `.` when `dot` allows it (a field of
    a group body, or a `group` outside one). None for text that is not a path."""
    if text == ".":
        return () if dot else None
    steps = []
    for step in text.split("."):
        position = _CBOR_POSITION.match(step)
        if _CBOR_INT_KEY.match(step) and step != "-0":
            value = int(step)
            if not CBOR_INT_MIN <= value <= CBOR_UINT_MAX:
                return None
            steps.append(("int", value))
        elif position:
            if int(position.group(1)) > 65535:
                return None
            steps.append(("pos", int(position.group(1))))
        elif _CBOR_TEXT_KEY.match(step):
            steps.append(("text", step))
        else:
            return None
    return tuple(steps)


def cbor_value(text):
    """A `when` or `const` value of the cbor wire (0.28 "Kinds", rulings 8 and
    19): an int when 2a of 0.11 reads it as one in -2^63 to 2^64-1, a bool for
    `true` and `false`, else a text string with one leading `=` stripped."""
    if _INT.match(text) and CBOR_INT_MIN <= int(text) <= CBOR_UINT_MAX:
        return int(text)
    if text in ("true", "false"):
        return text == "true"
    return text[1:] if text.startswith("=") else text


def printable(text, low=0x20):
    """True when every character of `text` is from `low` to 0x7E."""
    return all(low <= ord(c) <= 0x7E for c in text)


class CheckError(Exception):
    """A file that does not load. `kind` is the error kind of the specification;
    `line` is the 1-based line the error belongs to, or None for an error about
    the whole file (a missing `distribution` line has no line to name)."""

    def __init__(self, kind, message, line=None, label=None):
        self.kind, self.message, self.line, self.label = kind, message, line, label
        super().__init__(kind, message, line, label)

    def __str__(self):
        where = self.label or "<text>"
        if self.line is not None:
            where += ":%d" % self.line
        return "%s: %s: %s" % (where, self.kind, self.message)


# --------------------------------------------------------------------------
# lines
# --------------------------------------------------------------------------

def tokenize(line, line_no=None, label=None):
    """The tokens of one line (engine-spec "Pack definition grammar"; 0.1.1
    ruling 1; 0.5 rulings 6 and 17).

    Tokens are separated by spaces and tabs. `#` starts a comment only at the
    start of a token; inside a token, and inside double quotes, it is literal.
    A double quote at the start of a token opens a value that runs to the next
    double quote and may hold whitespace; there is no escape."""
    if '"' not in line and "#" not in line:
        return [t for t in line.replace("\t", " ").replace("\r", " ").split(" ") if t]
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        if c in " \t\r":
            i += 1
        elif c == "#":
            break
        elif c == '"':
            j = line.find('"', i + 1)
            if j < 0:
                raise CheckError("bad-directive", "a double quote is not closed", line_no, label)
            out.append(line[i + 1:j])
            i = j + 1
        else:
            j = i
            while j < n and line[j] not in " \t\r":
                j += 1
            out.append(line[i:j])
            i = j
    return out


def directive_lines(text, label=None):
    """[(line number, tokens)] for every line of `text` that holds a directive."""
    rows = []
    for no, line in enumerate(text.split("\n"), 1):
        toks = tokenize(line, no, label)
        if toks:
            rows.append((no, toks))
    return rows


def split_key(key):
    """(module, name) of a model key as a pack writes it: the text before the
    first `.` is the module; a key with no `.` is a key of `core`."""
    module, dot, name = key.partition(".")
    return (module, name) if dot else ("core", key)


def parse_factor(text, signed=False):
    """A scale factor (0.5 ruling 1): a decimal number as a float, or a fraction
    `<num>/<den>` as the pair (num, den). None when the text is neither. A
    transform's fraction is unsigned (0.15 ruling 25); the derive function
    `scale:` takes integer text as `<num>` (0.11 ruling 2c): signed=True."""
    if signed and text.startswith(("-", "+")) and _FRACTION.match(text[1:]):
        m = _FRACTION.match(text[1:])
        num, den = int(m.group(1)), int(m.group(2))
        return (-num if text[0] == "-" else num, den) if num and den else None
    m = _FRACTION.match(text)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        return (num, den) if num and den else None
    if _NUMBER.match(text) and float(text) != 0:
        return float(text)
    return None


_EXACT_DECIMAL = re.compile(r"(-?)([0-9]+)(?:\.([0-9]+))?\Z")
_EXACT_FRACTION = re.compile(r"(-?)([0-9]+)/([0-9]+)\Z")
_EXACT_OFFSET = re.compile(r"-?[0-9]+\Z")


def exact_factor_ok(text):
    """An exact factor of the integer scales (engine-spec 0.15): a decimal with
    no exponent or a fraction with a sign only before the numerator; not 0; in
    lowest terms numerator and denominator at most 2^32."""
    from fractions import Fraction
    m = _EXACT_FRACTION.match(text)
    if m:
        if int(m.group(3)) == 0:
            return False
        value = Fraction(int(m.group(2)), int(m.group(3)))
    else:
        m = _EXACT_DECIMAL.match(text)
        if not m:
            return False
        value = Fraction(m.group(2) + (m.group(3) or "")) / (10 ** len(m.group(3) or ""))
    return value != 0 and value.numerator <= 2 ** 32 and value.denominator <= 2 ** 32


def exact_offset_ok(text):
    return bool(_EXACT_OFFSET.match(text)) and abs(int(text)) < 2 ** 63


_VALUE_FLOAT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?\Z")


def reads_as_value(value, key_type):
    """True when `value` reads as `key_type` in a `requires =` list or a `case`
    (spec 0.20 rulings 17 and 24): an int is `-` and digits; a float is
    `-?digits[.digits]` with an optional exponent; no leading `+`."""
    if key_type == "float":
        return bool(_VALUE_FLOAT.match(value))
    return reads_as(value, key_type)


def reads_as(value, key_type):
    """True when the text `value` can be read as `key_type` (a `default` value)."""
    if key_type == "int":
        return bool(_INT.match(value))
    if key_type == "float":
        return bool(_NUMBER.match(value))
    return key_type == "string"


# --------------------------------------------------------------------------
# model modules
# --------------------------------------------------------------------------

# function -> (minimum arguments, maximum arguments or None, takes a parameter)
_DERIVE_SHAPE = {
    "copy": (1, 1, False), "hypot": (2, 2, False), "bearing": (2, 2, False),
    "east_of": (2, 2, False), "north_of": (2, 2, False), "neg": (1, 1, False),
    "scale": (1, 1, True), "offset": (1, 1, True), "join": (1, None, True),
    "day_seconds": (1, 1, False), "any": (1, None, False), "not": (1, 1, False),
    "parse_int": (1, 1, False), "text_of": (1, 1, False), "present": (1, 1, False),
    # Version 0.16
    "sec_of": (1, 1, False), "nsec_of": (1, 1, False), "ms_of": (2, 2, False),
    "deg": (1, 1, False), "rad": (1, 1, False), "add": (2, 2, False), "sub": (2, 2, False),
    "deg_lat_of": (2, 2, False), "deg_lon_of": (2, 2, False),
    "m_lat_of": (2, 2, False), "m_lon_of": (2, 2, False),
    "ecef_x": (3, 3, False), "ecef_y": (3, 3, False), "ecef_z": (3, 3, False),
    "lat_of_ecef": (3, 3, False), "lon_of_ecef": (3, 3, False), "hae_of_ecef": (3, 3, False),
    # Version 0.18
    "tokens": (1, None, True), "has_token": (1, 1, True), "text_if": (1, 1, True),
}
# function -> (type of every argument, type of the target); `copy`, `offset`,
# `present`, `add` and `sub` are checked apart because they take more than one type.
_DERIVE_TYPES = {
    "hypot": ("float", "float"), "bearing": ("float", "float"), "east_of": ("float", "float"),
    "north_of": ("float", "float"), "neg": ("float", "float"), "scale": ("float", "float"),
    "join": ("string", "string"), "day_seconds": ("int", "float"), "any": ("int", "int"),
    "not": ("int", "int"), "parse_int": ("string", "int"), "text_of": ("int", "string"),
    # Version 0.16 (ruling 4: no promotion)
    "sec_of": ("int", "int"), "nsec_of": ("int", "int"), "ms_of": ("int", "int"),
    "deg": ("float", "float"), "rad": ("float", "float"),
    "deg_lat_of": ("float", "float"), "deg_lon_of": ("float", "float"),
    "m_lat_of": ("float", "float"), "m_lon_of": ("float", "float"),
    "ecef_x": ("float", "float"), "ecef_y": ("float", "float"), "ecef_z": ("float", "float"),
    "lat_of_ecef": ("float", "float"), "lon_of_ecef": ("float", "float"), "hae_of_ecef": ("float", "float"),
    # Version 0.18
    "tokens": ("int", "string"), "has_token": ("string", "int"), "text_if": ("int", "string"),
}

# spec 0.18: the separator names of `tokens` and `has_token` (ruling 9:
# lowercase and exact)
_SEPARATOR_NAMES = {"space": " ", "comma": ",", "colon": ":"}


# spec 0.18: whitespace in separators, tokens and texts is these four only
_WS = " \t\n\r"


def _separator(text):
    """The separator character of `tokens` and `has_token`, or None when the
    text is neither a name nor one character other than `:`, `,` and
    whitespace (a character is one code point)."""
    if text in _SEPARATOR_NAMES:
        return _SEPARATOR_NAMES[text]
    if len(text) == 1 and text not in ":," + _WS:
        return text
    return None


def _token_ok(token, sep):
    """A token: one or more characters other than `:`, `,`, whitespace and
    the separator character."""
    return bool(token) and not any(c in ":," + _WS or c == sep for c in token)


def token_parameter_error(function, parameter, count):
    """Why the parameter of a 0.18 derive function does not load, or None.
    `count` is the number of argument keys of the line."""
    if function == "text_if":
        # one or more characters other than whitespace; `:` allowed
        return None if parameter and not any(c in _WS for c in parameter) else \
            "`text_if` takes a text of one or more characters other than whitespace"
    sep_text, colon, rest = parameter.partition(":")
    sep = _separator(sep_text)
    if sep is None or not colon:
        return "`%s` takes a separator (one character, or space, comma or colon) and then `:`" % function
    if function == "has_token":
        return None if _token_ok(rest, sep) else "`has_token` takes one token after the separator"
    tokens = rest.split(",")
    if not all(_token_ok(t, sep) for t in tokens):
        return "`tokens`: an empty token, or a token holding `:`, `,`, whitespace or the separator"
    if len(set(tokens)) != len(tokens):
        return "`tokens`: a token listed twice"
    if len(tokens) != count:
        return "`tokens` lists %d token(s) and has %d argument(s)" % (len(tokens), count)
    return None


class Derive:
    """One `derive` line: target key, function name, its parameter (the text
    after `:`, or None) and the argument keys."""
    __slots__ = ("line", "target", "function", "parameter", "arguments")

    def __init__(self, line, target, function, parameter, arguments):
        self.line, self.target, self.function = line, target, function
        self.parameter, self.arguments = parameter, arguments


class Module:
    """One model module. `keys` maps a key name to its type, `units` to its unit
    token, `lists` holds the list names; all three keep file order."""

    def __init__(self, label):
        self.label = label
        self.name = self.version = self.distribution = None
        self.sources, self.uses, self.derives = [], [], []
        self.keys, self.units, self.lists = {}, {}, {}

    def type_of(self, name):
        """`string`, `float` or `int` for a key, `list` for a list, None when
        the module declares neither."""
        if name in self.keys:
            return self.keys[name]
        return "list" if name in self.lists else None


def parse_module(text, label=None):
    """Read one module text and apply the checks that need no other module:
    the line grammar, `duplicate-key`, then `missing-distribution` and
    `missing-source` (engine-spec 0.4 "Model module grammar", 0.6 `derive`,
    0.7 `list`, 0.8 `uses`)."""
    label = label or "<module>"
    mod = Module(label)

    for no, toks in directive_lines(text, label):
        d, a = toks[0], toks[1:]

        def bad(message):
            raise CheckError("bad-directive", message, no, label)

        if d in ("module", "version", "distribution", "source", "uses"):
            if len(a) != 1:
                bad("`%s` takes one argument, has %d" % (d, len(a)))
            if d == "module":
                if mod.name is not None:
                    bad("a second `module` line")
                mod.name = a[0]
            elif d == "version":
                mod.version = a[0]
            elif d == "distribution":
                if a[0] not in DISTRIBUTIONS:
                    bad("distribution `%s` is not public or controlled" % a[0])
                if mod.distribution is not None:
                    bad("a second `distribution` line")
                mod.distribution = a[0]
            elif d == "source":
                mod.sources.append(a[0])
            else:
                mod.uses.append(a[0])
        elif d in ("key", "list"):
            if d == "key" and len(a) not in (3, 4):
                bad("`key` takes a name, a type, a unit and an optional meaning")
            if d == "list" and len(a) not in (1, 2):
                bad("`list` takes a name and an optional meaning")
            name = a[0]
            if not name or "." in name:
                bad("the %s name `%s` holds a `.` or is empty" % (d, name))
            if d == "key" and a[1] not in KEY_TYPES:
                bad("key type `%s` is not string, float or int" % a[1])
            if mod.type_of(name) is not None:
                raise CheckError("duplicate-key", "`%s` is declared twice" % name, no, label)
            if d == "key":
                mod.keys[name], mod.units[name] = a[1], a[2]
            else:
                mod.lists[name] = a[1] if len(a) == 2 else ""
        elif d == "derive":
            if len(a) < 3:
                bad("`derive` takes a target, a function and one or more arguments")
            function, colon, parameter = a[1].partition(":")
            shape = _DERIVE_SHAPE.get(function)
            if shape is None:
                bad("derive function `%s` is not one the specification lists" % function)
            least, most, takes_parameter = shape
            if bool(colon) != takes_parameter:
                bad("derive function `%s` %s a parameter" % (function, "takes" if takes_parameter else "takes no"))
            if function == "scale" and parse_factor(parameter, signed=True) is None:
                bad("`%s` is not a scale factor" % parameter)
            if function == "offset" and not _NUMBER.match(parameter):
                bad("`%s` is not a number" % parameter)
            args = a[2:]
            if len(args) < least or (most is not None and len(args) > most):
                bad("derive function `%s` has %d argument(s)" % (function, len(args)))
            if function in ("tokens", "has_token", "text_if"):
                why = token_parameter_error(function, parameter, len(args))
                if why:
                    bad(why)
            mod.derives.append(Derive(no, a[0], function, parameter if colon else None, args))
        else:
            bad("`%s` is not a directive of a model module" % d)

    if mod.name is None:
        raise CheckError("bad-directive", "the module has no `module` line", None, label)
    if mod.distribution is None:
        raise CheckError("missing-distribution", "module `%s` has no `distribution` line" % mod.name, None, label)
    if not mod.sources:
        raise CheckError("missing-source", "module `%s` has no `source` line" % mod.name, None, label)
    return mod


class Model:
    """The modules loaded so far. `max_distribution` is the engine's limit
    (engine-spec 0.4 "Distribution limit"): `public` refuses every controlled
    module and pack."""

    def __init__(self, max_distribution="controlled"):
        if max_distribution not in DISTRIBUTIONS:
            raise ValueError("max_distribution is public or controlled")
        self.max_distribution = max_distribution
        self.modules = {}

    def refuses(self, distribution):
        return self.max_distribution == "public" and distribution != "public"

    def type_of(self, key):
        """The type of a key as a pack writes it, `list` for a list, None when
        its module is not loaded or does not declare it."""
        module, name = split_key(key)
        mod = self.modules.get(module)
        return mod.type_of(name) if mod else None

    def add(self, text, label=None):
        """Load one module (`load_model` of the specification). Checks run in
        the order of 0.8 ruling 29."""
        mod = parse_module(text, label)

        def fail(kind, message, line=None):
            raise CheckError(kind, message, line, mod.label)

        if self.refuses(mod.distribution):
            fail("distribution-refused", "module `%s` is controlled and the limit is public" % mod.name)
        for used in mod.uses:
            if used not in self.modules and used != mod.name:
                fail("unknown-module", "module `%s` uses `%s`, which is not loaded" % (mod.name, used))
        for used in mod.uses:
            if mod.distribution == "public" and used != mod.name and self.modules[used].distribution != "public":
                fail("distribution-violation", "public module `%s` uses controlled module `%s`" % (mod.name, used))
        for derive in mod.derives:
            self._check_derive(mod, derive)
        if mod.name in self.modules:
            fail("duplicate-module", "module `%s` is already loaded" % mod.name)
        self.modules[mod.name] = mod
        return mod

    def _check_derive(self, mod, derive):
        """The `derive` checks that need keys (0.6 "Derived keys"; 0.7 ruling
        18; 0.8 rulings 29 and 32): target of `core` or of the module itself,
        arguments of `core`, the module or a module it uses, declared scalar
        keys, and types that fit the function."""

        def bad(message):
            raise CheckError("bad-directive", "derive %s: %s" % (derive.target, message), derive.line, mod.label)

        def key_type(key, reachable, role):
            module, name = split_key(key)
            if module not in reachable:
                bad("%s `%s` is a key of a module this module may not name here" % (role, key))
            owner = mod if module == mod.name else self.modules.get(module)
            found = owner.type_of(name) if owner else None
            if found is None:
                bad("%s `%s` is not declared" % (role, key))
            if found == "list":
                bad("%s `%s` is a list" % (role, key))
            return found

        target = key_type(derive.target, ("core", mod.name), "target")
        args = [key_type(a, ["core", mod.name] + mod.uses, "argument") for a in derive.arguments]
        fn = derive.function
        if fn == "copy":
            fits = args[0] == target
        elif fn == "present":
            fits = target == "int"  # any scalar argument (spec 0.12); a list is refused above
        elif fn == "offset":
            fits = args[0] == target and target in ("int", "float") and (
                target == "float" or bool(_INT.match(derive.parameter)))
        elif fn in ("add", "sub"):
            # 0.16 ruling 4: the target and both arguments all int or all float
            fits = target in ("int", "float") and all(a == target for a in args)
        else:
            want_arg, want_target = _DERIVE_TYPES[fn]
            fits = target == want_target and all(a == want_arg for a in args)
        if not fits:
            bad("the types %s -> %s do not fit `%s`" % (", ".join(args), target, fn))

    def load_dir(self, directory):
        """Load every `*.def` of a model directory: `core.def` first, then each
        module after the modules it uses, otherwise in byte order of file name
        (0.6 ruling 9; 0.8 "Model additions"). A cycle is `bad-directive`."""
        names = sorted(n for n in os.listdir(directory) if n.endswith(".def"))
        pending = []
        for name in sorted(names, key=lambda n: (n != "core.def", n)):
            path = os.path.join(directory, name)
            with open(path, encoding="utf-8") as fh:
                pending.append((path, fh.read()))
        parsed = [(path, text, parse_module(text, path)) for path, text in pending]
        declared = {mod.name for _, _, mod in parsed}
        while parsed:
            ready = [row for row in parsed
                     if all(u in self.modules or u not in declared or u == row[2].name for u in row[2].uses)]
            if not ready:
                path, _, mod = parsed[0]
                raise CheckError("bad-directive", "module `%s` is part of a `uses` cycle" % mod.name, None, path)
            path, text, _ = ready[0]
            self.add(text, path)
            parsed.remove(ready[0])
        return self


# --------------------------------------------------------------------------
# packs
# --------------------------------------------------------------------------

_JSON_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?\Z")


class Node:
    """One line of a pack below the header. `d` is the directive, `line` its
    line number, `args` the tokens after the directive. The other slots are
    filled for the directives that have them and are None otherwise:

      field    key, loc, tr (transform name), targs (its `:` arguments), via,
               opts (set of `swap`, `trim`, `optional`), also ([(key, via)])
      when     loc, value
      const    loc, value
      default  key, value
      group    key (the list), loc, mode (`count`, `while`, `more`, `fx`,
               and from 0.21 `rest`, `last` and `ref`, or None), count (an
               int, or a locator on a fixed layout), name (the count a `ref`
               group names), item (item bits), body, kinds (item kinds of a
               sequential group)
      count    name, bits, plus (0.21: a count line)
      if       conds ([(negated, presence name, bit number)]), body; on a
               fixed layout (a gate, 0.17) instead gate ((negated, values)),
               start, bits, body
      opt, chain          body
      length   bits, unit (`bytes` or `bits`), plus, whole, body (None when `whole`)
      presence name, bits (a count, or the text `fx`)
      pad, align          bits
      switch   key, body (its `case` and `else` nodes, in file order)
      case     values (the texts of the list), body; `else`: body

    `when` also has `values`: the texts of its list (0.20), and on bits and
    protobuf `ranges`, the (lo, hi) pairs of the list, a value being (v, v).

    On the bits wire a locator is also given as numbers: `start` is the first
    bit (from the message start on a fixed layout, from the item start inside a
    group) and `bits` the length; on a sequential layout only `bits` is set.
    On the protobuf wire `path` is the tuple of field numbers, `()` for `.`.
    On the text wire `fields` is the tuple of field indexes (one, or two for a
    pair) and `col` is (from, len) for a column, None otherwise; a group's
    `start` is its first field and `item` the fields of one item.
    On the tlv wire `path` is the tuple of tags and `size` the `:<n>` bytes,
    None when the locator has none.
    In a UPER pack (0.19) a field with a UPER locator has `bits` None and
    `uper` = (form, lb, ub, ext): form `int`, `enum`, `chars` or `octets`, the
    bounds as ints or None when not written (for `enum`, lb is n), ext a bool.
    A `group ... size` has mode `size` and count (lb, ub) or None; a `choice`
    has count n and its body holds only `alt` nodes, each with `count` its
    index and its own body."""
    __slots__ = ("d", "line", "args", "body", "kinds", "key", "loc", "tr", "targs", "via",
                 "opts", "also", "value", "mode", "count", "item", "conds", "name", "bits",
                 "unit", "plus", "whole", "start", "path", "absent", "fields", "col", "size", "gate", "with_", "uper",
                 "values", "ranges", "until", "stop", "as_key", "names", "at")

    def __init__(self, d, line, args):
        self.d, self.line, self.args = d, line, args
        self.body = self.kinds = self.key = self.loc = self.tr = self.targs = self.via = None
        self.opts = self.also = self.value = self.mode = self.count = self.item = None
        self.conds = self.name = self.bits = self.unit = self.plus = self.whole = None
        self.start = self.path = self.absent = self.fields = self.col = self.size = self.gate = self.with_ = self.uper = None
        self.values = self.ranges = None
        self.until = self.stop = None
        self.as_key = None          # spec 0.30: the key of `when ... as <key>`
        self.at = None              # spec 0.33: the offset of `when ... at <offset>`
        self.names = None           # spec 0.31: the count names of `group <list> count @<a> [@<b>]`

    def __repr__(self):
        return "<%s line %d: %s>" % (self.d, self.line, " ".join(self.args))


class Kind:
    """A message kind, or an item kind of a sequential group: its name, its
    `root` (xml), the terms of its `requires` lines as written (`<key>` or,
    0.20, `<key>=<value>[,<value>...]`) and its lines in file order (`when`,
    `field`, `const`, `default` and blocks; not `requires` or `root`)."""

    def __init__(self, name, line):
        self.name, self.line = name, line
        self.root = None
        self.requires = []
        self.lines = []


class Pack:
    """A loaded pack. `common` holds the lines before the first `kind`; `uses`
    starts with `core`; `tables` maps a table name to its (native, model)
    pairs in file order."""

    def __init__(self, label):
        self.label = label
        self.format = self.version = self.wire = self.distribution = self.root = None
        self.layout, self.bit_order, self.word_bytes = "fixed", "lsb", None
        self.armor = "hex"                                       # bits wire, 0.14
        self.encoding = "none"                                   # bits wire, 0.19
        self.delimiter = self.start = self.checksum = None      # text wire, as written
        self.tag, self.length, self.key = "ber-oid", "ber", None  # tlv wire
        self.sum16 = None                                        # tlv: the checksum tag, an int
        self.cbor_tag = None        # cbor: the `tag <n>` the message is enclosed in, an int (0.28)
        self.cbor_top = "map"       # cbor: the type of the top item, "map" or "array" (0.28)
        self.sources, self.uses = [], ["core"]
        self.tables, self.typemap = {}, []
        self.common, self.kinds = [], []

    @property
    def sequential(self):
        return self.layout == "sequential"

    @property
    def uper(self):
        return self.encoding == "uper"

    @property
    def separator(self):
        """The delimiter of a text pack, None for `delimiter none`."""
        if self.delimiter == "none":
            return None
        return self.delimiter or ","

    def scopes(self):
        """[(kind or None, lines)]: for each kind the common lines followed by
        its own, or the common lines alone for a pack with no kinds."""
        if not self.kinds:
            return [(None, self.common)]
        return [(kind, self.common + kind.lines) for kind in self.kinds]


def walk(lines, directive=None):
    """Every node of `lines` and of the blocks and item kinds below them, in
    file order; only those of one directive when `directive` is given."""
    for node in lines:
        if directive is None or node.d == directive:
            yield node
        if node.body:
            yield from walk(node.body, directive)
        if node.kinds:
            for kind in node.kinds:
                yield from walk(kind.lines, directive)


def _as_of(node):
    """The key of `when ... [at <n>] as <key>` (spec 0.30, 0.33), or None."""
    a = node.args
    if len(a) == 4 and a[2] == "as" and a[3] != "as":
        return a[3]
    if len(a) == 6 and a[2] == "at" and a[4] == "as" and a[5] != "as":
        return a[5]
    return None


def keys_of(node):
    """The model keys a `field` node binds: its own and those of its `also` lines."""
    return [node.key] + [key for key, _ in (node.also or ())]


class _Loader:
    """Reads one pack text. `structure` builds the tree; `lines` reads every
    line for the pack's wire; `model` applies the checks against the modules."""

    def __init__(self, text, model, label):
        self.text, self.model = text, model
        self.pack = Pack(label or "<pack>")
        self.key_uses = []          # (node or line number, key, what is expected)
        self.tlv_lines = []         # (line number, directive, args, after a `kind`), 0.13
        self.armor_line = None      # (line number, value, after a `kind`), 0.14
        self.encoding_line = None   # (line number, value, after a `kind`), 0.19
        self._header_lines = {}
        self.switches = []          # spec 0.20: `switch` nodes, for the checks of their values
        self.counts = []            # spec 0.21: count lines
        # spec 0.33: `at` errors are checks after the file, after the key
        # passes (rulings 10, 14 and 16); (line, message) of the `at` form,
        # then of the fixed window
        self.at_form, self.at_window = [], []

    def fail(self, kind, message, line=None):
        raise CheckError(kind, message, line, self.pack.label)

    def bad(self, node, message):
        self.fail("bad-directive", message, node if isinstance(node, int) else node.line)

    # -- the tree ------------------------------------------------------------

    def structure(self):
        pack = self.pack
        seen = set()
        open_blocks = []                    # Node of each block not yet closed
        last = None                         # the previous line's node, for `also`
        for no, toks in directive_lines(self.text, pack.label):
            d, a = toks[0], toks[1:]
            if d not in DIRECTIVES:
                self.bad(no, "`%s` is not a directive" % d)
            if open_blocks and d in HEADER + TABLES + ("tag", "key"):
                self.bad(no, "`%s` inside a `%s` block" % (d, open_blocks[-1].d))
            if d == "tag" and len(a) != 1:
                # 0.28: one argument, a line check (step 3 of 5b of 0.11) on any wire
                self.bad(no, "`tag` takes one argument, has %d" % len(a))
            if pack.wire == "cbor":
                self._cbor_line_locator(no, d, a, any(b.d == "group" for b in open_blocks))
            # the forms of 0.13 are recorded here and checked in `lines`, after
            # the file is read; `length` is one of them on the tlv wire only, and
            # `checksum` when it is not the one-word form of 0.10
            if d in ("tag", "key") or (d in ("length", "checksum") and pack.wire == "tlv") \
                    or (d == "checksum" and len(a) != 1):
                if open_blocks:
                    self.bad(no, "`%s` inside a `%s` block" % (d, open_blocks[-1].d))
                self.tlv_lines.append((no, d, a, bool(pack.kinds)))
                continue
            if d in HEADER:
                if len(a) != 1:
                    self.bad(no, "`%s` takes one argument, has %d" % (d, len(a)))
                if d not in ("source", "uses") and d in seen:
                    self.bad(no, "a second `%s` line" % d)
                seen.add(d)
                self._header(no, d, a[0])
                continue
            if d == "map":
                if len(a) != 3:
                    self.bad(no, "`map` takes a table, a native value and a model value")
                pack.tables.setdefault(a[0], []).append((a[1], a[2]))
                continue
            if d == "typemap":
                if len(a) != 2:
                    self.bad(no, "`typemap` takes a native code and a type")
                pack.typemap.append((a[0], a[1]))
                continue
            owner = open_blocks[-1] if open_blocks else None
            kinds = owner.kinds if owner is not None else pack.kinds
            if d == "end":
                if a:
                    self.bad(no, "`end` takes no argument")
                if owner is None:
                    self.bad(no, "`end` with no open block")
                if owner.d == "alt":            # one `end` closes the last `alt` and its `choice`
                    open_blocks.pop()
                open_blocks.pop()
                last = None
                continue
            if d == "alt":                      # 0.19: an `alt` ends the `alt` before it
                if owner is not None and owner.d == "alt":
                    open_blocks.pop()
                    owner = open_blocks[-1]
                if owner is None or owner.d != "choice":
                    self.bad(no, "`alt` outside a `choice`")
                node = Node(d, no, a)
                node.body = []
                owner.body.append(node)
                open_blocks.append(node)
                last = None
                continue
            if d == "kind":
                if len(a) != 1:
                    self.bad(no, "`kind` takes one name")
                if owner is not None and owner.d != "group":
                    self.bad(no, "`kind` inside a `%s` block" % owner.d)
                if owner is not None and kinds is None:
                    owner.kinds = kinds = []
                if any(k.name == a[0] for k in kinds):
                    self.fail("duplicate-kind", "kind `%s` is declared twice" % a[0], no)
                kinds.append(Kind(a[0], no))
                last = None
                continue
            node = Node(d, no, a)
            if d == "also":
                node.name = last          # the field this line extends, or None
            if d in ("requires", "root"):
                self._kind_line(node, owner, kinds)
                last = None
                continue
            if d in ("case", "else"):
                self._arm(node, owner)
                last = None
                continue
            if kinds:
                kinds[-1].lines.append(node)
            elif owner is not None and owner.d == "switch":
                if not owner.body:
                    self.bad(node, "`%s` between `switch` and its first `case`" % d)
                owner.body[-1].body.append(node)
            elif owner is not None:
                owner.body.append(node)
            else:
                pack.common.append(node)
            if (d in BLOCKS and not (d == "length" and "whole" in a)) or d == "switch":
                node.body = []
                open_blocks.append(node)
            if d != "also":
                last = node if d == "field" else None
        if open_blocks:
            self.bad(open_blocks[-1], "this `%s` has no `end`" % open_blocks[-1].d)
        return self

    def _arm(self, node, owner):
        """A `case` or `else` line (spec 0.20): an arm of the innermost open
        block, which must be a `switch`. `else` is the last arm and comes once,
        after at least one `case`."""
        if owner is None or owner.d != "switch":
            self.bad(node, "`%s` outside a `switch`" % node.d)
        arms = owner.body
        if node.d == "else":
            if node.args:
                self.bad(node, "`else` takes no argument")
            if any(arm.d == "else" for arm in arms):
                self.bad(node, "a second `else` in one `switch`")
            if not arms:
                self.bad(node, "`else` before a `case`")
        else:
            if len(node.args) != 1:
                self.bad(node, "`case` takes one list of values")
            if any(arm.d == "else" for arm in arms):
                self.bad(node, "a `case` after the `else` of its `switch`")
            node.values = node.args[0].split(",")
            if any(v == "" for v in node.values) and node.args[0] != "":
                # ruling 16: an empty item is refused; only a lone `""` is the empty text
                self.bad(node, "an empty value in the list of a `case`")
            # duplicates are a model check (rulings 18 and 19)
        node.body = []
        arms.append(node)

    def _cbor_line_locator(self, no, d, a, in_group):
        """0.28 "Paths": the path form is a line check (step 8 of 5b of 0.11),
        after the argument count, so a line with too few arguments is left to
        the checks after the file."""
        if d in ("field", "group") and len(a) >= (3 if d == "field" else 2):
            text = a[1]
        elif d in ("when", "const") and len(a) == 2:
            text = a[0]
        else:
            return
        self._cbor_path(no, text, d, in_group)

    def _cbor_path(self, at, text, d, in_group):
        """The steps of one cbor path, or `bad-locator`. `.` is a path for a
        `field` of a group body (the element) and a `group` outside one (the
        top item)."""
        path = cbor_path(text, dot=(d == "field" and in_group) or (d == "group" and not in_group))
        if path is None:
            self.fail("bad-locator", "`%s` is not a cbor path of integer keys, `[i]` positions "
                                     "and text keys" % text, at if isinstance(at, int) else at.line)
        return path

    def _header(self, no, d, value):
        pack = self.pack
        if d == "source":
            pack.sources.append(value)
        elif d == "uses":
            pack.uses.append(value)
        elif d == "distribution":
            if value not in DISTRIBUTIONS:
                self.bad(no, "distribution `%s` is not public or controlled" % value)
            pack.distribution = value
        elif d == "wire":
            if value not in WIRES:
                self.bad(no, "wire `%s` is not one of %s" % (value, ", ".join(WIRES)))
            pack.wire = value
        elif d == "layout":
            if value not in ("fixed", "sequential"):
                self.bad(no, "layout `%s` is not fixed or sequential" % value)
            pack.layout = value
        elif d == "bit_order":
            if value not in BIT_ORDERS:
                self.bad(no, "bit_order `%s` is not lsb, msb or msb-lsb" % value)
            pack.bit_order = value
        elif d == "word_bytes":
            if not _UINT.match(value) or int(value) < 1:
                self.bad(no, "word_bytes `%s` is not a positive integer" % value)
            pack.word_bytes = int(value)
        elif d == "armor":
            # checked in `lines`, after the file is read (0.14; ruling 10 of 0.10)
            self.armor_line = (no, value, bool(pack.kinds))
        elif d == "encoding":
            # checked in `lines`, after the file is read (0.19; ruling 10 of 0.10)
            self.encoding_line = (no, value, bool(pack.kinds))
        elif d in TEXT_HEADER:
            if pack.kinds:
                self.bad(no, "`%s` after the first `kind`" % d)
            if d == "delimiter" and value != "none" and (len(value) != 1 or value == '"' or not printable(value, 0x21)):
                self.bad(no, "delimiter `%s` is not one character from 0x21 to 0x7E other than `\"`, or `none`" % value)
            if d == "checksum" and value not in ("none", "nmea"):
                self.bad(no, "checksum `%s` is not none or nmea" % value)
            setattr(pack, d, value)
        else:
            setattr(pack, d, value)
        self._header_lines.setdefault(d, no)

    def _kind_line(self, node, owner, kinds):
        """`requires` and `root`: lines of the kind they follow, or `root` of the pack."""
        if node.d == "root":
            if len(node.args) != 1:
                self.bad(node, "`root` takes one element name")
            if owner is not None:
                self.bad(node, "`root` inside a `%s` block" % owner.d)
            target = kinds[-1] if kinds else self.pack
            if target.root is not None:
                self.bad(node, "a second `root` line")
            target.root = node.args[0]
            self._header_lines.setdefault("root", node.line)
            return
        if not node.args:
            self.bad(node, "`requires` names no key")
        if not kinds:
            self.bad(node, "`requires` before the first `kind`" if owner is None
                     else "`requires` inside a `%s` block with no `kind`" % owner.d)
        for term in node.args:
            kinds[-1].requires.append(term)
            key, eq, values = term.partition("=")
            if not eq:
                self.key_uses.append((node.line, key, "requires"))
                continue
            # spec 0.20 ruling 4: split at the first `=`; `k=` is refused
            if not key or not values:
                self.bad(node, "`requires %s`: a key and a value list around `=`" % term)
            if "" in values.split(","):
                self.bad(node, "`requires %s`: an empty value in the list (ruling 16)" % term)
            self.key_uses.append((node.line, key, ("requires=", values.split(","))))

    # -- lines, by wire --------------------------------------------------------

    def lines(self):
        pack = self.pack
        for need in ("format", "wire"):
            if getattr(pack, need) is None:
                self.fail("bad-directive", "the pack has no `%s` line" % need)
        where = self._header_lines
        if pack.wire != "bits":
            for d in ("layout", "bit_order", "word_bytes"):
                if d in where:
                    self.bad(where[d], "`%s` on the %s wire" % (d, pack.wire))
        elif pack.sequential:
            if "word_bytes" in where:
                self.bad(where["word_bytes"], "`word_bytes` in a sequential pack")
        elif pack.word_bytes is None:
            self.fail("bad-directive", "a fixed-layout bits pack has no `word_bytes` line")
        if pack.wire != "text":
            for d in TEXT_HEADER:
                if d in where:
                    self.bad(where[d], "`%s` on the %s wire" % (d, pack.wire))
        else:
            if pack.delimiter == "*" and pack.checksum == "nmea":
                self.bad(where["delimiter"], "`delimiter \"*\"` with `checksum nmea`")
            if pack.start is not None and (not pack.start or not printable(pack.start, 0x21)
                                           or (pack.separator is not None and pack.separator in pack.start)):
                self.bad(where["start"], "start `%s` is not one or more characters from 0x21 to 0x7E "
                                         "without the delimiter" % pack.start)
        self._tlv_header()
        self._armor()
        self._encoding()
        if pack.wire != "xml" and (pack.root is not None or any(k.root is not None for k in pack.kinds)):
            self.bad(where["root"], "`root` on the %s wire" % pack.wire)
        if not pack.kinds:
            for node in pack.common:
                if node.d == "when":
                    self.bad(node, "`when` in a pack with no `kind`")
        self._scope(pack.common, pack.kinds, group=None, visible=[{}], top=True)
        if pack.wire == "bits" and pack.sequential:
            self._count_paths(pack.common, pack.kinds)
            self._rest_extents(pack.common, pack.kinds, None)

        if pack.wire == "cbor":
            self._cbor_top()
        if pack.wire == "bits" and not pack.sequential:
            for _, lines in pack.scopes():
                self._fixed_extents(lines, item=None)
        return self

    def _armor(self):
        """0.14: `armor <hex|sixbit>` on the bits wire only, before the first
        `kind`; `armor sixbit` needs `bit_order msb` (the default is lsb)."""
        if self.armor_line is None:
            return
        pack = self.pack
        no, value, after_kind = self.armor_line
        if pack.wire != "bits":
            self.bad(no, "`armor` on the %s wire" % pack.wire)
        if after_kind:
            self.bad(no, "`armor` after the first `kind`")
        if value not in ARMORS:
            self.bad(no, "armor `%s` is not hex or sixbit" % value)
        if value == "sixbit" and pack.bit_order != "msb":
            self.bad(no, "`armor sixbit` needs `bit_order msb`")
        pack.armor = value

    def _encoding(self):
        """0.19: `encoding <none|uper>` on the bits wire only (any value, ruling
        18), before the first `kind`; `uper` needs `layout sequential` and
        `bit_order msb` and is refused with `armor sixbit` (ruling 11)."""
        if self.encoding_line is None:
            return
        pack = self.pack
        no, value, after_kind = self.encoding_line
        if pack.wire != "bits":
            self.bad(no, "`encoding` on the %s wire" % pack.wire)
        if after_kind:
            self.bad(no, "`encoding` after the first `kind`")
        if value not in ENCODINGS:
            self.bad(no, "encoding `%s` is not none or uper" % value)
        if value == "uper":
            if not pack.sequential:
                self.bad(no, "`encoding uper` needs `layout sequential`")
            if pack.bit_order != "msb":
                self.bad(no, "`encoding uper` needs `bit_order msb`")
            if pack.armor == "sixbit":
                self.bad(no, "`encoding uper` with `armor sixbit` (ruling 11 of 0.19)")
        pack.encoding = value

    def _tlv_header(self):
        """0.13: `tag`, `length`, `key` and `checksum sum16 <tag>` on the tlv
        wire only, at most once each, before the first `kind`, with their values."""
        pack = self.pack
        seen = set()
        for no, d, a, after_kind in self.tlv_lines:
            if pack.wire == "cbor" and d == "tag":
                self._cbor_tag(no, a, after_kind, seen)
                continue
            if pack.wire != "tlv":
                self.bad(no, "`%s %s` on the %s wire" % (d, " ".join(a), pack.wire))
            if d in seen:
                self.bad(no, "a second `%s` line" % d)
            seen.add(d)
            if after_kind:
                self.bad(no, "`%s` after the first `kind`" % d)
            if d in TLV_FORMS:
                if len(a) != 1 or a[0] not in TLV_FORMS[d]:
                    self.bad(no, "`%s %s`: the %s is one of %s" % (d, " ".join(a), d, ", ".join(TLV_FORMS[d])))
                setattr(pack, d, a[0])
            elif d == "key":
                if len(a) != 1 or not _TLV_KEY.match(a[0]):
                    self.bad(no, "`key %s` is not 1 to 64 bytes of lowercase hex" % " ".join(a))
                pack.key = a[0]
            elif len(a) != 2 or a[0] not in ("sum16", "crc32") or not _TLV_TAG.match(a[1]):
                self.bad(no, "`checksum %s` is not `checksum sum16 <tag>` or `checksum crc32 <tag>` on the tlv wire"
                         % " ".join(a))
        for no, d, a, _ in self.tlv_lines:      # the tag is checked against the final `tag` form
            if d == "checksum":
                pack.sum16 = self._tlv_tag(no, a[1])

    def _cbor_tag(self, no, a, after_kind, seen):
        """0.28 and its ruling 5: `tag <n>` on cbor, once, before the first
        `kind`, n a decimal from 0 to 2^64-1 with no leading zero."""
        if "tag" in seen:
            self.bad(no, "a second `tag` line")
        seen.add("tag")
        if after_kind:
            self.bad(no, "`tag` after the first `kind`")
        if not _TLV_TAG.match(a[0]) or int(a[0]) > CBOR_UINT_MAX:
            self.bad(no, "`tag %s` on cbor is not a decimal from 0 to 2^64-1 with no leading zero" % a[0])
        self.pack.cbor_tag = int(a[0])

    def _tlv_tag(self, node, text):
        """One tag of the tlv wire as an int: decimal, no leading zero, 0 to
        2^28-1, and below 2^(8n) under `tag <n>`."""
        tag = int(text) if _TLV_TAG.match(text) else -1
        limit = 1 << 28 if self.pack.tag == "ber-oid" else 1 << (8 * int(self.pack.tag))
        if not 0 <= tag < min(limit, 1 << 28):
            self.bad(node, "tag `%s` is not a decimal from 0 to %d with no leading zero" % (text, min(limit, 1 << 28) - 1))
        return tag

    def _scope(self, common, kinds, group, visible, top=False):
        """One body: the common lines, then each kind's. `group` is the group
        node the body belongs to, None for the message."""
        sequential = self.pack.sequential
        frame, declared = dict(visible[-1]), set()
        # spec 0.20: the keys mapped so far in reading order, for `switch`;
        # a group body is a scope of its own
        outer = getattr(self, "_mapped", None)
        self._mapped = set()
        # spec 0.21 ruling 9: a `count @` reference sees the counts of its own
        # group body only; this body's frames start here
        outer_base, self._body_base = getattr(self, "_body_base", 0), len(visible) - 1
        self._block(common, group, visible[:-1] + [frame], declared, in_kind=False, top=top)
        after_common = set(self._mapped)
        for kind in kinds or ():       # a kind continues the block its common lines began
            # spec 0.30 ruling 2: a kind's `as` key counts as mapped from the
            # start of its kind
            self._mapped = set(after_common) | {k for k in (_as_of(n) for n in kind.lines if n.d == "when")
                                                 if k is not None}
            self._block(kind.lines, group, visible[:-1] + [dict(frame)], set(declared), in_kind=True, top=top)
        self._mapped = outer
        self._body_base = outer_base
        for lines in ([common + kind.lines for kind in kinds] if kinds else [common]):
            if sequential:
                self._as_keys(lines)
                self._sequential_lists(lines)
            elif self.pack.wire == "text":
                self._one_group_per_list(lines)
                self._text_group_last(lines)
            elif self.pack.wire == "tlv":
                self._tlv_paths(lines)
            elif self.pack.wire == "cbor":
                self._one_group_per_list(lines)
                self._cbor_scope(lines, body=group is not None)
            else:
                self._one_group_per_list(lines)
                self._paths_through_groups(lines)

    def _block(self, lines, group, visible, declared, in_kind, top, chain=False):
        """The lines of one block. `visible` is a stack of {presence name: size}
        frames, the last one this block's; `declared` holds the presence names
        the block has declared so far (0.8 ruling 12)."""
        sequential = self.pack.sequential
        lines_seen = False          # a line of the kind other than requires, default, when
        for node in lines:
            d = node.d
            if d in SEQUENTIAL_ONLY and not sequential:
                self.bad(node, "`%s` in a pack that is not `layout sequential`" % d)
            if group is not None and not sequential and d not in ("field", "const", "default", "group", "if"):
                self.bad(node, "`%s` inside a group" % d)
            if not sequential and not top and d not in GATE_BODY:
                self.bad(node, "`%s` inside a gate block" % d)
            if d in UPER_ONLY and not self.pack.uper:
                self.bad(node, "`%s` in a pack without `encoding uper` (ruling 9 of 0.19)" % d)
            if d == "when":
                if sequential and (not top or (in_kind and lines_seen)):
                    self.bad(node, "`when` after another line of its kind, or inside a block")
                self._when(node, group)
                if node.as_key is not None:
                    self._mapped.add(node.as_key)
            elif d == "field":
                self._field(node, group)
                self._mapped.add(node.key)
            elif d == "also":
                self._also(node)
                self._mapped.add(node.key)
            elif d == "switch":
                self._switch(node, group, visible, in_kind)
            elif d == "const":
                self._const(node, group)
            elif d == "default":
                if len(node.args) != 2:
                    self.bad(node, "`default` takes a key and a value")
                node.key, node.value = node.args
                self.key_uses.append((node, node.key, "default"))
            elif d in ("pad", "align"):
                if len(node.args) != 1 or not _UINT.match(node.args[0]) or int(node.args[0]) < 1:
                    self.bad(node, "`%s` takes a positive bit count" % d)
                node.bits = int(node.args[0])
            elif d == "presence":
                self._presence(node, visible, declared)
            elif d == "count":
                self._count(node, visible, declared)
            elif d == "fx":
                if node.args or not chain:
                    self.bad(node, "`fx` outside a chain, or with an argument")
            elif d == "element":
                self._element(node, group)
            elif d == "group":
                self._group(node, group)
                if node.mode == "ref":
                    self._count_ref(node, visible)
                inner = visible + [{}]
                if node.kinds:
                    if not sequential:
                        self.bad(node.kinds[0].line, "`kind` inside a group of a pack that is not `layout sequential`")
                else:
                    for line in node.body:
                        if line.d == "when":
                            self.bad(line, "`when` in a group body with no `kind`")
                self._scope(node.body, node.kinds, group=node, visible=inner, top=True)
            elif d == "if":
                if sequential:
                    self._if(node, visible)
                else:
                    self._gate(node, group)
                self._block(node.body, group, visible + [{}], set(), in_kind, top=False)
            elif d == "opt":
                if node.args:
                    self.bad(node, "`opt` takes no argument")
                self._block(node.body, group, visible + [{}], set(), in_kind, top=False)
            elif d == "chain":
                if node.args:
                    self.bad(node, "`chain` takes no argument")
                self._block(node.body, group, visible + [{}], set(), in_kind, top=False, chain=True)
            elif d == "length":
                self._length(node)
                if node.body is not None:
                    self._block(node.body, group, visible + [{}], set(), in_kind, top=False)
            elif d == "ext":
                if node.args:
                    self.bad(node, "`ext` takes no argument")
                for i, line in enumerate(node.body):
                    if line.d == "presence" and i:
                        self.bad(line, "a `presence` line inside an `ext` block that is not its first line")
                self._block(node.body, group, visible + [{}], set(), in_kind, top=False)
            elif d == "choice":
                self._choice(node)
                for alt in node.body:
                    self._block(alt.body, group, visible + [{}], set(), in_kind, top=False)
            if d not in ("when", "default"):
                lines_seen = True

    # each reader below fills the node's slots or refuses the line

    def _choice(self, node):
        """0.19 "CHOICE" and ruling 15: `choice <n> [ext]` with n from 1 to
        65536, then only `alt <i>` lines, each index in 0..n-1 and given once,
        and at least one."""
        a = node.args
        if not (len(a) in (1, 2) and _UPER_NUMBER.match(a[0]) and 1 <= int(a[0]) <= 65536
                and a[1:] in ([], ["ext"])):
            self.bad(node, "`choice <n> [ext]` with n from 1 to 65536")
        node.count = n = int(a[0])
        if not node.body:
            self.bad(node, "a `choice` with no `alt` line")
        seen = set()
        for alt in node.body:
            if alt.d != "alt":
                self.bad(alt, "`%s` between `choice` and its first `alt`" % alt.d)
            if len(alt.args) != 1 or not _UPER_NUMBER.match(alt.args[0]) or not 0 <= int(alt.args[0]) < n:
                self.bad(alt, "`alt <i>` with i from 0 to %d" % (n - 1))
            alt.count = int(alt.args[0])
            if alt.count in seen:
                self.bad(alt, "`alt %d` is given twice" % alt.count)
            seen.add(alt.count)

    def _uper_locator(self, node, form, rest):
        """0.19 "Locators" and ruling 15: the bounds of a UPER locator."""
        text = node.loc

        def number(t, low, high):
            if not _UPER_NUMBER.match(t) or not low <= int(t) <= high:
                self.bad(node, "`%s` in `%s` is not a decimal from %d to %d with no leading zero"
                         % (t, text, low, high))
            return int(t)

        parts = rest.split(":")
        lb = ub = None
        ext = False
        if form == "int":
            if parts == ["", ""]:
                pass
            elif len(parts) == 2 and parts[1] == "":
                lb = number(parts[0], *INT64)
            elif len(parts) == 2 or (len(parts) == 3 and parts[2] == "ext"):
                lb, ub = number(parts[0], *INT64), number(parts[1], *INT64)
                ext = len(parts) == 3
            else:
                self.bad(node, "`%s` is not `int:<lb>:<ub>[:ext]`, `int:<lb>:` or `int::`" % text)
        elif form == "enum":
            if len(parts) not in (1, 2) or parts[1:] not in ([], ["ext"]):
                self.bad(node, "`%s` is not `enum:<n>[:ext]`" % text)
            lb, ext = number(parts[0], 1, 65536), len(parts) == 2
        elif rest != "":
            if len(parts) != 2:
                self.bad(node, "`%s` is not `%s:<lb>:<ub>` or `%s:`" % (text, form, form))
            lb, ub = number(parts[0], 0, 65535), number(parts[1], 0, 65535)
        if ub is not None and lb > ub:
            self.bad(node, "`%s` has a lower bound above its upper bound" % text)
        node.uper = (form, lb, ub, ext)

    def _transform(self, node, text, bits):
        """Split `<name>[:<arg>...]`, check it against the wire and, on the bits
        wire, against the field's length (0.5 "bits: more transforms")."""
        name, *targs = text.split(":")
        table = TRANSFORMS[self.pack.wire]
        if node.uper is not None:
            table = UPER_TRANSFORMS[node.uper[0]]
            if name not in table:
                self.bad(node, "transform `%s` is not one a `%s:` locator takes" % (name, node.uper[0]))
        if name not in table:
            self.bad(node, "transform `%s` is not valid on the %s wire" % (name, self.pack.wire))
        if name in ("uscale", "sscale"):
            if len(targs) not in (1, 2) or parse_factor(targs[0]) is None or not all(
                    _NUMBER.match(t) for t in targs[1:]):
                self.bad(node, "`%s` takes a factor (a number or `<num>/<den>`) and an optional offset" % name)
        elif name in ("smscale", "f32scale", "f64scale", "scale"):
            if len(targs) not in (1, 2) or parse_factor(targs[0]) is None or not all(
                    _NUMBER.match(t) for t in targs[1:]):
                self.bad(node, "`%s` takes a factor (a number or `<num>/<den>`) and an optional offset" % name)
        elif name in ("uiscale", "siscale", "iscale"):
            if len(targs) not in (1, 2) or not exact_factor_ok(targs[0]) or not all(
                    exact_offset_ok(t) for t in targs[1:]):
                self.bad(node, "`%s` takes an exact factor and an optional integer offset" % name)
        elif name == "chars":
            if len(targs) != 1 or targs[0] not in CHAR_SETS:
                self.bad(node, "`chars` takes one of the sets %s" % ", ".join(sorted(CHAR_SETS)))
        elif name == "linscale":
            if len(targs) != 2 or not all(_NUMBER.match(t) for t in targs) or float(targs[0]) == 0:
                self.bad(node, "`linscale` takes a maximum and a range")
        elif self.pack.wire == "text":
            self._text_parameters(node, name, targs)
        elif targs:
            self.bad(node, "transform `%s` takes no argument" % name)
        if bits is not None:
            if name == "ascii":
                ok = bits % 8 == 0 and 8 <= bits <= 2040
            elif name == "sixbit":
                ok = bits % 6 == 0 and 6 <= bits <= 1530
            elif name in ("f32", "f64"):
                ok = bits == int(name[1:])
            elif name in ("f32scale", "f64scale"):
                ok = bits == int(name[1:3])
            elif name in ("smag", "smscale"):
                ok = 2 <= bits <= 64
            elif name == "chars":
                w = CHAR_SETS[targs[0]]
                ok = bits % w == 0 and w <= bits <= 2040
            elif name == "octal":
                ok = bits % 3 == 0 and 3 <= bits <= 63
            elif name == "hex":
                # engine-spec 0.22: a multiple of 4, from 4 to 2040
                ok = bits % 4 == 0 and 4 <= bits <= 2040
            else:
                ok = 1 <= bits <= 64
            if not ok:
                self.bad(node, "transform `%s` does not allow a length of %d bits" % (name, bits))
        node.tr, node.targs = name, tuple(targs)

    def _text_parameters(self, node, name, targs):
        """Rule 1 of 0.10 "Transforms for `text`": the parameters and their ranges."""
        def number(text, low, high):
            return bool(_UINT.match(text)) and low <= int(text) <= high

        if name == "int":
            ok = not targs or (len(targs) == 1 and number(targs[0], 1, 20))
        elif name == "dec":
            ok = len(targs) in (1, 2) and number(targs[0], 0, 9) and (len(targs) == 1 or number(targs[1], 1, 20))
        elif name == "dm":
            ok = (len(targs) == 3 and number(targs[0], 1, 3) and number(targs[1], 0, 9)
                  and len(targs[2]) == 2 and all("A" <= c <= "Z" for c in targs[2])
                  and targs[2][0] != targs[2][1])
        elif name in ("hms", "hms_dmy"):
            ok = len(targs) == 1 and number(targs[0], 0, 3)
        else:
            ok = not targs
        if not ok:
            self.bad(node, "transform `%s` has parameters out of shape or range: `%s`"
                     % (name, ":".join([name] + targs)))

    def _text_locator(self, node, text, group, what):
        """A locator of the text wire (0.10 "Locators"; ruling 14): `<i>`,
        `<i>:<from>:<len>` or `<i>+<j>`, relative to the item inside a group."""
        pack = self.pack
        column, pair = _TEXT_COLUMN.match(text), _TEXT_PAIR.match(text)
        if _UINT.match(text):
            node.fields = (int(text),)
        elif column:
            index, start, length = (int(x) for x in column.groups())
            if length < 1:
                self.bad(node, "the column `%s` has a length of 0" % text)
            node.fields, node.col = (index,), (start, length)
        elif pair:
            node.fields = (int(pair.group(1)), int(pair.group(2)))
            if node.fields[0] == node.fields[1]:
                self.bad(node, "the pair `%s` names one field twice" % text)
            if what != "field":
                self.bad(node, "a `%s` takes a field or a column, not the pair `%s`" % (what, text))
        else:
            self.bad(node, "`%s` is not a text locator (`<i>`, `<i>:<from>:<len>` or `<i>+<j>`)" % text)
        if pack.separator is None and any(node.fields):
            self.bad(node, "`%s` names a field other than 0 under `delimiter none`" % text)
        if group is not None and max(node.fields) >= group.item:
            self.bad(node, "`%s` reaches beyond `item %d`" % (text, group.item))

    def _text_value(self, node, what):
        """A `when` or `const` value of the text wire (0.10 "Locators")."""
        pack = self.pack
        if what == "when" and node.value == "present":
            return
        text = node.value[1:] if node.value.startswith("=") else node.value
        if (not text or not printable(text) or text != text.strip(" ")
                or (pack.separator is not None and pack.separator in text)
                or (pack.checksum == "nmea" and "*" in text)):
            self.bad(node, "the `%s` value `%s` is empty, holds the delimiter, a `*` under nmea, a "
                           "character outside 0x20 to 0x7E, or a space at its start or end" % (what, node.value))
        if node.col is not None and len(text) > node.col[1]:
            self.bad(node, "the `%s` value `%s` is longer than its column" % (what, node.value))

    def _locator(self, node, text, group, what):
        """Set `loc` and, by wire, `start`/`bits` or `path`."""
        pack = self.pack
        node.loc = text
        if pack.wire == "text":
            self._text_locator(node, text, group, what)
        elif pack.wire == "cbor":
            node.path = self._cbor_path(node, text, what, group is not None)
        elif pack.wire == "tlv":
            m = _TLV_LOCATOR.match(text)
            if not m:
                self.bad(node, "`%s` is not a tlv path of decimal tags with an optional `:<n>`" % text)
            node.path = tuple(self._tlv_tag(node, t) for t in m.group(1).split("."))
            if m.group(2) is not None:
                if len(m.group(2)) != 1 or not 1 <= int(m.group(2)) <= 8:
                    self.bad(node, "the size `:%s` is not one digit from 1 to 8" % m.group(2))
                node.size = int(m.group(2))
        elif pack.wire == "bits":
            if pack.sequential and what == "field" and text.startswith("until:"):
                # engine-spec 0.22: characters up to a terminator code, plain digits
                code = text[len("until:"):]
                if not _UINT.match(code):
                    self.bad(node, "`%s`: the terminator code is not plain digits" % text)
                node.until = int(code)
            elif pack.sequential:
                uper = _UPER_LOCATOR.match(text)
                if pack.uper and what == "field" and uper:
                    self._uper_locator(node, *uper.groups())
                    return
                if not _UINT.match(text):
                    self.bad(node, "a %s of a sequential pack takes a bit length, not `%s`%s" % (
                        what, text, " (a UPER locator needs `encoding uper`)" if uper and not pack.uper else ""))
                node.bits = int(text)
            else:
                m = _BITS_LOCATOR.match(text)
                if not m:
                    self.bad(node, "`%s` is not a `<word>:<pos>:<len>` locator" % text)
                word, pos, node.bits = (int(x) for x in m.groups())
                node.start = word * pack.word_bytes * 8 + pos
        elif pack.wire == "protobuf":
            if text == "." and group is not None and what == "field":
                node.path = ()
            elif _PROTOBUF_PATH.match(text):
                node.path = tuple(int(x) for x in text.split("."))
            else:
                self.bad(node, "`%s` is not a protobuf field-number path" % text)
        elif not text or (text == "." and (group is None or what != "field")):
            self.bad(node, "`%s` is not a locator of a %s here" % (text, what))

    def _field(self, node, group):
        a = node.args
        if len(a) < 3:
            self.bad(node, "`field` takes a key, a locator and a transform")
        node.key = a[0]
        self._locator(node, a[1], group, "field")
        self._transform(node, a[2], node.bits if self.pack.wire == "bits" and node.until is None else None)
        node.opts, node.also = set(), []
        i = 3
        while i < len(a):
            opt = a[i]
            if opt == "via" and node.via is None and i + 1 < len(a):
                node.via = a[i + 1]
                i += 1
            elif opt in ("swap", "trim", "optional") and opt not in node.opts:
                node.opts.add(opt)
            elif opt == "absent" and node.absent is None and i + 1 < len(a):
                # spec 0.9: the token after `absent` is always its argument
                node.absent = a[i + 1]
                i += 1
            elif opt == "stop" and node.stop is None and i + 1 < len(a):
                # engine-spec 0.22: a fixed-size `chars` field whose text ends at a code
                node.stop = a[i + 1]
                i += 1
            elif opt == "with" and node.with_ is None and i + 1 < len(a):
                # spec 0.18: written only when the entity (the item) holds the key
                node.with_ = a[i + 1]
                i += 1
            else:
                self.bad(node, "field option `%s` is unknown, repeated or incomplete" % opt)
            i += 1
        bits_wire = self.pack.wire == "bits"
        self._terminated(node, bits_wire)
        if self.pack.wire == "cbor" and (node.opts or node.absent is not None):
            self.bad(node, "`%s` on the cbor wire, whose only field option is `via`"
                     % ("absent" if node.absent is not None else sorted(node.opts)[0]))
        if node.absent is not None:
            self._absent(node, group)
        bits_wire = self.pack.wire == "bits"
        if node.uper is not None and node.opts & {"swap", "trim"}:
            self.bad(node, "`%s` on a UPER locator (ruling 10 of 0.19)" % " ".join(sorted(node.opts & {"swap", "trim"})))
        if "swap" in node.opts and not (bits_wire and node.bits % 8 == 0):
            self.bad(node, "`swap` needs the bits wire and a length that is a multiple of 8")
        if "swap" in node.opts and node.tr in ("sixbit", "chars", "octal", "hex"):
            self.bad(node, "`swap` with `%s`" % node.tr)
        if "trim" in node.opts and not (bits_wire and node.tr in ("ascii", "sixbit")):
            self.bad(node, "`trim` needs the bits wire and the `ascii` or `sixbit` transform")
        text_wire = self.pack.wire == "text"
        if "optional" in node.opts and not ((bits_wire and not self.pack.sequential) or text_wire):
            self.bad(node, "`optional` needs a fixed-layout bits pack or the text wire")
        if "optional" in node.opts and text_wire and group is not None:
            self.bad(node, "`optional` inside a group of the text wire")
        if text_wire and (node.tr in PAIR_TRANSFORMS) != (len(node.fields) == 2):
            self.bad(node, "transform `%s` %s" % (node.tr, "takes a pair `<i>+<j>`" if node.tr in PAIR_TRANSFORMS
                                                  else "does not take a pair"))
        if self.pack.wire == "tlv":
            self._tlv_size(node)
        self._via(node, node.via)
        self.key_uses.append((node, node.key, "field"))
        if node.with_ is not None:
            # 0.18 ruling 5: checked as a `requires` key is
            self.key_uses.append((node.line, node.with_, "requires"))

    def _terminated(self, node, bits_wire):
        """engine-spec 0.22: `until:<code>` and `stop <code>` (rulings 9 and 16)."""
        if node.until is not None:
            if node.tr != "chars":
                self.bad(node, "`until:` is valid only with `chars:<set>`")
            if node.until >> CHAR_SETS[node.targs[0]]:
                self.bad(node, "`until:%d` does not fit the set's width" % node.until)
            if node.absent is not None or node.opts & {"swap", "trim"}:
                self.bad(node, "`until:` takes no `absent`, `swap` or `trim`")
            if node.stop is not None:
                self.bad(node, "`stop` and `until:` on one line")
        if node.stop is not None:
            if not bits_wire or node.tr != "chars":
                self.bad(node, "`stop` needs a `chars` field of the bits wire")
            if not _UINT.match(node.stop) or int(node.stop) >> CHAR_SETS[node.targs[0]]:
                self.bad(node, "`stop %s` is not a code below 2^w" % node.stop)
            node.stop = int(node.stop)

    def _absent(self, node, group):
        """The load checks of `absent <value>[,<value>...]` (spec 0.9)."""
        arg, wire = node.absent, self.pack.wire
        if wire == "text":
            self.bad(node, "`absent` is not valid on the text wire (ruling 16 of 0.10)")
        if wire == "tlv":
            self.bad(node, "`absent` is not valid on the tlv wire (ruling 10 of 0.13)")
        if getattr(node, "uper", None):
            self.bad(node, "`absent` is not valid on a UPER locator (ruling 22 of 0.19)")
        values = [""] if arg == "" else arg.split(",")
        for v in values:
            if '"' in v or (v == "" and arg != ""):
                self.bad(node, "`absent %s`: an empty value or a double quote" % arg)
        def unsigned(limit):
            for v in values:
                if not v.isdigit() or not v.isascii() or int(v) >= limit:
                    self.bad(node, "`absent %s`: each value is an unsigned integer below %d" % (arg, limit))
        if wire == "bits":
            if node.bits is None or node.bits > 64:
                self.bad(node, "`absent` on a bits field longer than 64 bits")
            unsigned(1 << node.bits)
        elif wire == "protobuf":
            if node.tr == "pstring":
                return
            unsigned(1 << 32 if node.tr == "pfloat" else 1 << 64)
        else:
            stripped = [v[1:] if v.startswith("=") else v for v in values]
            for v, t in zip(values, stripped):
                if t == "" and arg != "":
                    self.bad(node, "`absent %s`: a value empty after `=`" % arg)
            if wire in ("json", "geojson"):
                for v in values:
                    if v == "null":
                        self.bad(node, "`absent null` on %s" % wire)
                    if _JSON_NUMBER.match(v):
                        try:
                            ok = math.isfinite(float(v))
                        except OverflowError:
                            ok = False
                        if not ok:
                            self.bad(node, "`absent %s`: number text outside a finite double" % v)
                if node.tr == "bool" and any(v not in ("true", "false") for v in values):
                    self.bad(node, "`absent` on `bool` takes only `true` and `false`")
                if wire == "geojson" and group is None and node.loc is not None \
                        and str(node.loc).startswith("geometry.") \
                        and not all(_JSON_NUMBER.match(v) for v in values):
                    self.bad(node, "`absent` on a geojson coordinate takes only number text")

    def _tlv_size(self, node):
        """0.13 "Transforms for `tlv`": the size each transform needs or allows."""
        tr, size = node.tr, node.size
        if tr in TLV_SIZED and size is None:
            self.bad(node, "transform `%s` needs a size `:<n>` after the path `%s`" % (tr, node.loc))
        if tr in TLV_FLOAT_SIZE and size not in (None, TLV_FLOAT_SIZE[tr]):
            self.bad(node, "transform `%s` takes no size or `:%d`, not `:%d`" % (tr, TLV_FLOAT_SIZE[tr], size))
        if tr not in TLV_SIZED + tuple(TLV_FLOAT_SIZE) and size is not None:
            self.bad(node, "transform `%s` takes no size, has `:%d`" % (tr, size))

    def _tlv_value(self, node, what):
        """0.13 "`when` and `const`": a numeric value needs a size and fits it;
        `when <path> present` takes no size."""
        if what == "when" and node.value == "present":
            if node.size is not None:
                self.bad(node, "`when %s present` with a size" % node.loc)
            return
        if node.size is None:
            self.bad(node, "a numeric `%s` without a size `:<n>`" % what)
        if not _UINT.match(node.value) or int(node.value) >> (8 * node.size):
            self.bad(node, "the `%s` value `%s` does not fit %d bytes" % (what, node.value, node.size))

    def _via(self, node, table):
        if table is not None and table not in self.pack.tables:
            self.bad(node, "`via %s` names a table with no `map` line" % table)

    def _also(self, node):
        field, a = node.name, node.args
        node.name = None
        if field is None or len(a) not in (1, 3) or (len(a) == 3 and a[1] != "via"):
            self.bad(node, "`also <key> [via <table>]` stands directly after a `field` line")
        node.key, node.via = a[0], a[2] if len(a) == 3 else None
        self._via(node, node.via)
        field.also.append((node.key, node.via))
        self.key_uses.append((node, node.key, ("also", field)))

    def _unsigned(self, node, text, what):
        """A `when` or `const` value of the bits wire: unsigned, fits the bits."""
        if not 1 <= node.bits <= 64:
            self.bad(node, "a `%s` is 1 to 64 bits" % what)
        if not _UINT.match(text) or int(text) >> node.bits:
            self.bad(node, "the `%s` value `%s` does not fit %d bits" % (what, text, node.bits))

    def _when(self, node, group):
        """`when <locator> <value>[,<value>...] [as <key>]` (0.5, lists and
        ranges 0.20, `as` 0.30 on a sequential pack only, ruling 15)."""
        a = node.args
        sequential = self.pack.wire == "bits" and self.pack.sequential
        if sequential and "at" in a[2:]:
            self._when_at(node)
        elif len(a) > 2 and a[2] == "at":
            # spec 0.33 ruling 30: `at` on a pack that is not sequential is an
            # `at` error with the late timing of rulings 10 and 14 (a third
            # token that is neither `at` nor `as` stays the line check, 29)
            self.at_form.append((node.line, "`at` on a `when` of a pack that is not `layout sequential`"))
        elif len(a) == 4 and a[2] == "as" and a[3] != "as" and sequential:
            node.as_key = a[3]
            self.key_uses.append((node, a[3], "as"))
        elif len(a) != 2:
            self.bad(node, "`when` takes a locator and a value" + (
                " (`as <key>` follows the values only on a `layout sequential` pack, 0.30)" if "as" in a[2:] else ""))
        self._locator(node, node.args[0], group, "when")
        node.value = node.args[1]
        if self.pack.wire == "text":
            self._text_value(node, "when")
        elif self.pack.wire == "tlv":
            self._tlv_value(node, "when")
        wire = self.pack.wire
        if wire == "cbor":
            # 0.28 ruling 36: no `when` lists on cbor; a comma is part of a text
            node.values = [node.value]
            return
        node.values = [""] if node.value == "" else node.value.split(",")
        if any(v == "" for v in node.values) and node.value != "":
            self.bad(node, "an empty value in the list of a `when`")
        if "present" in node.values and len(node.values) > 1:
            self.bad(node, "`present` combined with other values")
        if wire == "bits" and not 1 <= node.bits <= 64:
            self.bad(node, "a `when` is 1 to 64 bits")
        if wire not in ("bits", "protobuf") or node.values == ["present"]:
            if wire == "bits":
                self.bad(node, "a bits `when` value is an unsigned integer or a range")
            return
        limit = 1 << (node.bits if wire == "bits" else 64)
        node.ranges = []
        for v in node.values:
            m = _WHEN_RANGE.match(v)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
            elif _UINT.match(v):
                lo = hi = int(v)
            else:
                self.bad(node, "the `when` value `%s` is not an unsigned integer or a range `<lo>..<hi>`" % v)
            if lo > hi:
                self.bad(node, "the `when` range `%s` has lo above hi" % v)
            if hi >= limit:
                self.bad(node, "the `when` value `%s` does not fit the field" % v)
            node.ranges.append((lo, hi))

    def _const(self, node, group):
        if len(node.args) != 2:
            self.bad(node, "`const` takes a locator and a value")
        self._locator(node, node.args[0], group, "const")
        node.value = node.args[1]
        if node.value == "present":
            self.bad(node, "`const <path> present` on the tlv wire" if self.pack.wire == "tlv"
                     else "`const <locator> present`; write `=present` for the text")
        if self.pack.wire == "bits":
            self._unsigned(node, node.value, "const")
        elif self.pack.wire == "text":
            self._text_value(node, "const")
        elif self.pack.wire == "tlv":
            self._tlv_value(node, "const")

    def _presence(self, node, visible, declared):
        a = node.args
        if len(a) != 2 or not (a[1] == "fx" or (_UINT.match(a[1]) and 1 <= int(a[1]) <= 64)):
            self.bad(node, "`presence <name> <n>` with n from 1 to 64, or `presence <name> fx`")
        if a[0] in declared:
            self.bad(node, "`%s` is declared twice in one block (a presence or a count, 0.21 ruling 15)" % a[0])
        declared.add(a[0])
        node.name, node.bits = a[0], a[1] if a[1] == "fx" else int(a[1])
        visible[-1][a[0]] = node.bits

    def _count(self, node, visible, declared):
        """`count <name> <len> [plus <n>]` (spec 0.21): len 1 to 64; `plus` at
        most once with an optional `-` then digits within signed 64 bits
        (ruling 16); no other option. The name shares the namespace of the
        presence names of its block (ruling 15)."""
        a = node.args
        if len(a) < 2 or not _COUNT_NAME.match(a[0]) or not _UINT.match(a[1]) or not 1 <= int(a[1]) <= 64:
            self.bad(node, "`count <name> <len>` with len from 1 to 64")
        node.name, node.bits, node.plus = a[0], int(a[1]), 0
        opts = a[2:]
        if opts:
            if len(opts) != 2 or opts[0] != "plus" or not _PLUS.match(opts[1]) \
                    or not -(1 << 63) <= int(opts[1]) < (1 << 63):
                self.bad(node, "a count line takes only `plus <n>`, once, n an optional `-` then digits "
                               "within signed 64 bits")
            node.plus = int(opts[1])
        if node.name in declared:
            self.bad(node, "`%s` is declared twice in one block (a presence or a count, 0.21 ruling 15)" % node.name)
        declared.add(node.name)
        visible[-1][node.name] = "count"
        self.counts.append(node)

    def _count_ref(self, node, visible):
        """`group <list> count @<name>` (spec 0.21): the name is a count
        visible here, declared in the same group body (ruling 9), not a
        presence (ruling 15). With two names (spec 0.31) each is checked so."""
        frames = visible[self._body_base:]
        for name in node.names:
            size = next((frame[name] for frame in reversed(frames) if name in frame), None)
            if size is None:
                self.bad(node, "`count @%s`: no count of that name is visible in this group body" % name)
            if size != "count":
                self.bad(node, "`count @%s` names a presence (0.21 ruling 15)" % name)

    def _if(self, node, visible):
        if not node.args:
            self.bad(node, "`if` names no presence bit")
        node.conds = []
        for text in node.args:
            m = _CONDITION.match(text)
            if not m:
                self.bad(node, "`%s` is not `[!]<presence>.<bit>`" % text)
            name, bit = m.group(2), int(m.group(3))
            size = next((frame[name] for frame in reversed(visible) if name in frame), None)
            if size is None:
                self.bad(node, "`if` names presence `%s`, which is not visible here" % name)
            if size == "count":
                self.bad(node, "`if %s`: `%s` is a count, not a presence (0.21 ruling 15)" % (text, name))
            if bit < 1 or (size != "fx" and bit > size):
                self.bad(node, "presence `%s` has no bit %d" % (name, bit))
            node.conds.append((m.group(1) == "!", name, bit))

    def _switch(self, node, group, visible, in_kind):
        """`switch <key>` (spec 0.20): a sequential layout; the key mapped by a
        `field` or `also` line earlier in reading order in the same scope; at
        least one `case`; each arm a block of its own (rulings 8 and 10)."""
        if not self.pack.sequential:
            self.bad(node, "`switch` in a pack that is not `layout sequential`")
        if len(node.args) != 1:
            self.bad(node, "`switch` takes one model key")
        node.key = node.args[0]
        if node.key not in self._mapped:
            self.bad(node, "`switch %s`: the key is not mapped by an earlier line of the scope" % node.key)
        if not any(arm.d == "case" for arm in node.body):
            self.bad(node, "a `switch` with no `case`")
        for arm in node.body:
            for line in arm.body:
                if line.d not in CASE_BODY:
                    self.bad(line, "`%s` directly inside a `%s`" % (line.d, arm.d))
            self._block(arm.body, group, visible + [{}], set(), in_kind, top=False)
        self.switches.append(node)

    def _gate(self, node, group):
        """A gate block of a fixed layout (spec 0.17): `if [!]<word>:<pos>:<len>
        <value>[,<value>...]`, each value an unsigned decimal below 2^len,
        none listed twice."""
        if self.pack.wire != "bits":
            self.bad(node, "`if` on the %s wire" % self.pack.wire)
        a = node.args
        m = _GATE.match(a[0]) if len(a) == 2 else None
        if not m:
            self.bad(node, "a gate is `if [!]<word>:<pos>:<len> <value>[,<value>...]`")
        self._locator(node, m.group(2), group, "gate")
        if not 1 <= node.bits <= 64:
            self.bad(node, "a gate is 1 to 64 bits")
        values = a[1].split(",")
        for v in values:
            if not _UINT.match(v) or int(v) >> node.bits:
                self.bad(node, "the gate value `%s` is not an unsigned integer that fits %d bits" % (v, node.bits))
        if len(set(int(v) for v in values)) != len(values):
            self.bad(node, "a gate lists a value twice")
        node.gate = (m.group(1) == "!", tuple(int(v) for v in values))

    def _element(self, node, group):
        """`element <path>` (spec 0.18): xml only, not inside a group, a path
        of element names (no `@` or `#` in a step, no empty step: rulings 13
        and 16)."""
        if self.pack.wire != "xml":
            self.bad(node, "`element` on the %s wire" % self.pack.wire)
        if group is not None:
            self.bad(node, "`element` inside a group (0.18 ruling 12)")
        if len(node.args) != 1:
            self.bad(node, "`element` takes one path")
        path = node.args[0]
        names = path.split("/")
        if not path or any(not n for n in names) or "@" in path or "#" in path:
            self.bad(node, "`%s` is not a path of element names" % path)
        node.loc = path

    def _length(self, node):
        a = node.args
        if not a or not _UINT.match(a[0]) or not 1 <= int(a[0]) <= 64:
            self.bad(node, "`length` takes a field length of 1 to 64 bits")
        node.bits, node.unit, node.plus, node.whole = int(a[0]), None, None, False
        i = 1
        while i < len(a):
            word = a[i]
            if word in ("bytes", "bits") and node.unit is None:
                node.unit = word
            elif word == "plus" and node.plus is None and i + 1 < len(a) and _INT.match(a[i + 1]):
                node.plus = int(a[i + 1])
                i += 1
            elif word == "whole" and not node.whole:
                node.whole = True
            else:
                self.bad(node, "`length` argument `%s` is unknown, repeated or incomplete" % word)
            i += 1
        if node.whole and node.unit == "bits":
            self.bad(node, "`length ... bits whole`")
        if node.whole and self.pack.armor == "sixbit":
            self.bad(node, "`length ... whole` in a pack with `armor sixbit` (ruling 3 of 0.14)")
        node.unit, node.plus = node.unit or "bytes", node.plus or 0

    def _group(self, node, group):
        pack, a = self.pack, node.args
        if len(a) < 2:
            self.bad(node, "`group` takes a list and a locator or a repeat form")
        if pack.wire == "tlv":
            self.bad(node, "`group` on the tlv wire")
        node.key = a[0]
        self.key_uses.append((node, node.key, "group"))
        rest = a[1:]
        if pack.wire == "bits" and pack.sequential:
            if rest in (["while"], ["more"], ["fx"], ["rest"], ["last"]):
                node.mode = rest[0]
            elif len(rest) == 2 and rest[0] == "count" and _UINT.match(rest[1]) and 1 <= int(rest[1]) <= 64:
                node.mode, node.count = "count", int(rest[1])
            elif rest[0] == "size" and len(rest) in (1, 3):
                if not pack.uper:
                    self.bad(node, "`group ... size` in a pack without `encoding uper`")
                node.mode = "size"
                if len(rest) == 3:
                    if not all(_UPER_NUMBER.match(t) and 0 <= int(t) < 65536 for t in rest[1:]) \
                            or int(rest[1]) > int(rest[2]):
                        self.bad(node, "`size <lb> <ub>` needs 0 <= lb <= ub < 65536")
                    node.count = (int(rest[1]), int(rest[2]))
            elif len(rest) in (2, 3) and rest[0] == "count" \
                    and all(t.startswith("@") and _COUNT_NAME.match(t[1:]) for t in rest[1:]) \
                    and len(set(rest[1:])) == len(rest) - 1:
                # spec 0.21: the items a count line of the same body names;
                # spec 0.31: or two count lines, which must agree (the same
                # name twice, a third name or a token that is not `@<name>`
                # is `bad-directive`)
                node.names = tuple(t[1:] for t in rest[1:])
                node.mode, node.name = "ref", node.names[0]
            else:
                self.bad(node, "a sequential group is `count <len>` (1 to 64 bits), `count @<name>`, `while`, "
                               "`more`, `fx`, `rest` or `last`, one of them%s" % (" or `size [<lb> <ub>]`" if pack.uper else ""))
            return
        node.loc = rest[0]
        if pack.wire == "text":
            if group is not None:
                self.bad(node, "a group inside a group of the text wire")
            if pack.separator is None:
                self.bad(node, "a group in a pack with `delimiter none`")
            if len(rest) != 3 or rest[1] != "item" or not _UINT.match(rest[0]) or not _UINT.match(rest[2]) \
                    or int(rest[2]) < 1:
                self.bad(node, "a text group is `group <list> <i> item <n>` with n from 1")
            node.start, node.item = int(rest[0]), int(rest[2])
            return
        if pack.wire != "bits":
            if len(rest) != 1:
                self.bad(node, "`%s` after the locator of a group on the %s wire" % (rest[1], pack.wire))
            if pack.wire == "protobuf":
                if not _PROTOBUF_PATH.match(node.loc):
                    self.bad(node, "`%s` is not a protobuf field-number path" % node.loc)
                node.path = tuple(int(x) for x in node.loc.split("."))
                dotted = [f.args[1] == "." for f in node.body if f.d == "field" and len(f.args) > 1]
                if any(dotted) and (not all(dotted) or any(x.d not in ("field", "default") for x in node.body)):
                    self.bad(node, "a protobuf group body mixes `.` with paths")
                # 0.18 rulings 4 and 17: a packed group is a body of `.` fields
                # with numeric transforms only; `with` is refused there
                numeric = ("pvarint", "psint", "pdouble", "pfloat")
                packed = node.body and all(x.d == "field" and len(x.args) > 2 and x.args[1] == "."
                                           and x.args[2] in numeric for x in node.body)
                if packed:
                    for x in node.body:
                        if "with" in x.args[3:]:
                            self.bad(x, "`with` on a `.` field of a packed protobuf group (0.18 ruling 4)")
            elif pack.wire == "cbor":
                node.path = self._cbor_path(node, node.loc, "group", group is not None)
            elif not node.loc or node.loc == ".":
                self.bad(node, "`%s` is not a group locator" % node.loc)
            elif pack.wire == "xml" and (any(not step for step in node.loc.split("/"))
                                         or "@" in node.loc or "#" in node.loc):
                # 0.7: a path of element names; spec 0.21 ruling 37
                self.bad(node, "`%s` is not a path of element names" % node.loc)
            return
        m = _BITS_START.match(node.loc)
        if not m or len(rest) != 5 or rest[1] != "item" or rest[3] != "count" or not _UINT.match(rest[2]):
            self.bad(node, "a bits group is `<word>:<pos> item <bits> count <locator | n>`")
        node.start = int(m.group(1)) * pack.word_bytes * 8 + int(m.group(2))
        node.item = int(rest[2])
        counted = _BITS_LOCATOR.match(rest[4])
        if counted:
            word, pos, length = (int(x) for x in counted.groups())
            if not 1 <= length <= 64:
                self.bad(node, "a count locator is 1 to 64 bits")
            node.mode, node.count = "locator", (word * pack.word_bytes * 8 + pos, length)
        elif _UINT.match(rest[4]):
            node.mode, node.count = "count", int(rest[4])
        else:
            self.bad(node, "`%s` is not a count locator or a number" % rest[4])
        if node.item < 1:
            self.bad(node, "`item` takes a positive bit count")

    # -- rules over one scope --------------------------------------------------

    def _count_paths(self, common, kinds):
        """Spec 0.21 rulings 2 and 12: a count name reaches from its line to
        the end of its block, and from common lines into each kind. In each
        reading path it reaches (one kind, one arm of each switch) exactly one
        group references it."""
        def visit(nodes, alternatives):
            for i, node in enumerate(nodes):
                if node.d == "count":
                    tail = nodes[i + 1:]
                    for path in ([tail + alt for alt in alternatives] if alternatives else [tail]):
                        found = self._refs(path, node.name)
                        if found != {1}:
                            self.bad(node, "count `%s` is referenced by %s group in a reading path "
                                           "(0.21 ruling 2)" % (node.name, "no" if 0 in found else "more than one"))
                if node.d == "group":
                    visit(node.body, [k.lines for k in node.kinds or ()])
                    for k in node.kinds or ():
                        visit(k.lines, [])
                elif node.d == "switch":
                    for arm in node.body:
                        visit(arm.body, [])
                elif node.body:
                    visit(node.body, [])
        visit(common, [k.lines for k in kinds])
        for k in kinds:
            visit(k.lines, [])

    def _refs(self, lines, name):
        """The numbers of `count @<name>` groups over the reading paths of
        `lines` (2 standing for two or more); a group body is not entered and a
        nested block that declares the name again hides it to its end. A group
        with two names (spec 0.31 ruling 3) is one reference to each."""
        got = {0}
        for node in lines:
            if node.d in ("count", "presence") and node.name == name:
                break
            if node.d == "group":
                add = {1} if node.mode == "ref" and name in node.names else {0}
            elif node.d == "switch":
                add = set().union(*(self._refs(arm.body, name) for arm in node.body))
            elif node.body:
                add = self._refs(node.body, name)
            else:
                continue
            got = {min(a + b, 2) for a in got for b in add}
        return got

    def _rest_extents(self, common, kinds, group):
        """Spec 0.21 rulings 10 and 11: a `rest` group is the last wire line of
        its extent (the innermost `length` block, or the message) in reading
        order, whatever arm of a switch is read; `default` is not a wire line.
        Inside an item it stands within a `length` block of the item's body,
        or in the body of an item of an outer `rest` group."""
        def wire(node):
            if node.d == "default":
                return False
            if node.d in ("if", "chain"):
                return any(wire(x) for x in node.body)
            if node.d == "switch":
                return any(wire(x) for arm in node.body for x in arm.body)
            return True

        def visit(nodes, tails, item):
            # tails: the lines that follow `nodes` in this path up to the end
            # of the extent; item: the group whose item body holds `nodes` with
            # no `length` block between (None at message level or in a length)
            for i, node in enumerate(nodes):
                following = [nodes[i + 1:]] + tails
                if node.d == "group":
                    if node.mode == "rest":
                        later = next((x for seq in following for x in seq if wire(x)), None)
                        if later is not None:
                            self.bad(later, "`%s` after the `rest` group of `%s` in its extent (0.21 ruling 11)"
                                     % (later.d, node.key))
                        if item is not None and item.mode != "rest":
                            self.bad(node, "`rest` inside an item and not within a `length` block of the item "
                                           "(0.21 ruling 10)")
                    bodies(node.body, node.kinds, node)
                elif node.d == "length":
                    if node.body is not None:
                        visit(node.body, [], None)
                elif node.d == "switch":
                    for arm in node.body:
                        visit(arm.body, following, item)
                elif node.body:
                    visit(node.body, following, item)

        def bodies(lines, item_kinds, item):
            for k in item_kinds or ():
                visit(lines, [k.lines], item)
                visit(k.lines, [], item)
            if not item_kinds:
                visit(lines, [], item)
        bodies(common, kinds, group)

    def _one_group_per_list(self, lines):
        """0.7: within one scope a list is mapped by at most one `group`."""
        seen = set()
        for node in lines:
            if node.d == "group":
                if node.key in seen:
                    self.bad(node, "list `%s` is mapped by two groups of one scope" % node.key)
                seen.add(node.key)

    def _text_group_last(self, lines):
        """0.10 "Groups": the group is the last thing in its scope; no other
        group, and no `field`, `when` or `const` at its index or beyond."""
        groups = [n for n in lines if n.d == "group"]
        if not groups:
            return
        if len(groups) > 1:
            self.bad(groups[1], "a second group in one scope of the text wire")
        first = groups[0].start
        for node in lines:
            if node.d in ("field", "when", "const") and max(node.fields) >= first:
                self.bad(node, "the %s at `%s` lies at or beyond the group's field %d" % (node.d, node.loc, first))

    def _tlv_paths(self, lines):
        """0.13 "Locators" and ruling 5, over one scope: no `field`, `when` or
        `const` on the checksum tag, and no line at a path with another at a
        path under it."""
        placed = [n for n in lines if n.d in ("field", "when", "const")]
        for node in placed:
            if node.path[0] == self.pack.sum16:
                self.bad(node, "the %s at `%s` is on the checksum tag" % (node.d, node.loc))
        paths = {}
        for node in placed:
            paths.setdefault(node.path, node)
        for node in placed:
            for i in range(1, len(node.path)):
                other = paths.get(node.path[:i])
                if other is not None:
                    later = node if node.line > other.line else other
                    self.bad(later, "`%s` and `%s` read one item both as a value and as a set"
                             % (other.loc, node.loc))

    def _cbor_scope(self, lines, body):
        """0.28 "Types" and rulings 13, over one scope (the common lines with
        one kind's, or one group body): no step used both as a map and as an
        array; no `field`, `when` or `const` at or under a group's path; no
        line at a proper prefix of another line's path, a `when … present`
        excepted as the prefix; no group at or under another group's path; and
        in a group body, `.` alone or not at all."""
        placed = [n for n in lines if n.d in ("field", "when", "const", "group")]
        groups = [n for n in placed if n.d == "group"]
        if body:
            dotted = [n for n in placed if n.path == ()]
            if dotted and len(dotted) != len(placed):
                self.bad(next(n for n in placed if n.path != ()), "a group body mixes `.` with other paths")
        used = {}                   # prefix -> (container type, the line that uses it so)
        for node in placed:
            steps = node.path + ((("pos", 0),) if node.d == "group" else ())   # a group's item is an array
            for i in range(0 if body else 1, len(steps)):
                kind = "array" if steps[i][0] == "pos" else "map"
                prefix = steps[:i]
                seen = used.setdefault(prefix, (kind, node))
                if seen[0] != kind:
                    self.bad(node, "`%s` and `%s` use one item both as a map and as an array"
                             % (seen[1].loc, node.loc))
        for g in groups:
            for node in placed:
                if node is not g and node.path[:len(g.path)] == g.path:
                    self.bad(max(g, node, key=lambda n: n.line),
                             "the %s at `%s` is at or under the path of the group at `%s`"
                             % (node.d, node.loc, g.loc))
        for short in placed:
            if short.d == "when" and short.value == "present":
                continue
            for node in placed:
                if len(short.path) < len(node.path) and node.path[:len(short.path)] == short.path:
                    self.bad(max(short, node, key=lambda n: n.line),
                             "`%s` is a value and a container of `%s` in one scope" % (short.loc, node.loc))

    def _cbor_top(self):
        """0.28 "Types": the first step of every path outside a group body,
        and `group <list> .`, decide one type for the top item."""
        pack, first = self.pack, None
        for lines in [pack.common] + [k.lines for k in pack.kinds]:
            for node in lines:
                if node.d not in ("field", "when", "const", "group"):
                    continue
                kind = "array" if node.path == () or node.path[0][0] == "pos" else "map"
                if first is None:
                    first = (kind, node)
                elif first[0] != kind:
                    self.bad(node, "`%s` makes the top item %s, `%s` %s"
                             % (node.loc, "an array" if kind == "array" else "a map",
                                first[1].loc, "an array" if first[0] == "array" else "a map"))
        if first is not None:
            pack.cbor_top = first[0]

    def _when_at(self, node):
        """Spec 0.33: `when <len> <values> at <offset> [as <key>]` on a
        sequential pack, the only order (ruling 11). `at` is a keyword there
        only (ruling 15). Its errors are recorded and raised after the key
        passes (ruling 10): `at` not right after the values, with no value,
        twice, with a value that is not plain digits or does not fit in 64
        bits, and any token that is not a following `as <key>`."""
        rest = node.args[2:]
        # the `as` key is registered whatever the offset, since the 0.30 `as`
        # checks come before the `at` form (ruling 10)
        if len(rest) == 4 and rest[0] == "at" and rest[2] == "as" and rest[3] != "as":
            node.as_key = rest[3]
            self.key_uses.append((node, rest[3], "as"))
        if rest[0] != "at":
            self.at_form.append((node.line, "`at` must follow the values (`when <len> <values> [at <n>] [as <k>]`)"))
        elif len(rest) < 2 or not _UINT.match(rest[1]) or int(rest[1]) >> 64:
            self.at_form.append((node.line, "`at` takes an unsigned decimal offset below 2^64"))
        elif len(rest) not in (2, 4) or (len(rest) == 4 and node.as_key is None):
            self.at_form.append((node.line, "after `at <n>` only `as <key>` may follow"))
        else:
            node.at = int(rest[1])

    def _look_ahead(self):
        """Spec 0.33 after the file: `at` on a common `when` (of the message
        or of a group body) is an `at` form error; each window must be fixed
        in its kind. Walk the kind's lines from its first, skipping `when ...
        at`, `default` and `also` (`requires` is not a line of `kind.lines`),
        summing the others' bits until the sum reaches the window's end; each
        line walked must be a plain `when`, `const`, `pad` or a `field` with a
        bit length."""
        pack = self.pack
        bodies = [(pack.common, pack.kinds)] + [(n.body or [], n.kinds or []) for n in walk(pack.common, "group")]
        for common, kinds in bodies:
            for node in common:
                if node.d == "when" and node.at is not None:
                    self.at_form.append((node.line, "`at` on a common `when`"))
            for kind in kinds:
                for w in kind.lines:
                    if w.d != "when" or w.at is None:
                        continue
                    stop, total, fixed = w.at + int(w.args[0]), 0, False
                    for node in kind.lines:
                        if node.d in ("default", "also") or (node.d == "when" and node.at is not None):
                            continue
                        if node.d in ("when", "const", "pad") and _UINT.match(node.args[0]):
                            total += int(node.args[0])
                        elif node.d == "field" and len(node.args) > 1 and _UINT.match(node.args[1]):
                            total += int(node.args[1])
                        else:
                            break
                        if total >= stop:
                            fixed = True
                            break
                    if not fixed:
                        self.at_window.append((w.line, "the window of `when ... at %d` is not fixed in kind `%s`"
                                               % (w.at, kind.name)))

    def _as_keys(self, lines):
        """Spec 0.30 load errors and ruling 9, over one reading path (common
        lines plus one kind; a group body's common lines plus one item kind):
        two `when ... as` lines naming one key, or an `as` key that a `field`
        or `also` line of the path maps (in any case of a switch; a group
        body is a scope of its own), are `bad-directive`. Ruling 16: only key
        names are needed."""
        bound = {}
        for node in lines:
            if node.d == "when" and node.as_key is not None:
                if node.as_key in bound:
                    self.bad(node, "a second `when ... as %s` in one reading path (ruling 9 of 0.30)" % node.as_key)
                bound[node.as_key] = node

        def mapped(ls):
            for n in ls:
                if n.d == "field":
                    yield n, keys_of(n)
                elif n.d == "also":
                    yield n, [n.key]
                if n.d != "group" and n.body:
                    for sub in n.body:
                        if sub.d in ("case", "else"):
                            yield from mapped(sub.body or ())
                        else:
                            yield from mapped([sub])

        for node, keys in mapped(lines):
            for key in keys:
                if key in bound:
                    self.bad(node, "`%s` is bound by `when ... as` and mapped by this line (0.30)" % key)

    def _sequential_lists(self, lines):
        """0.8 rulings 23 and 33, with 0.19 ruling 20: two groups of one list in
        a sequential scope are allowed only when each sits in an `if`, `opt` or
        `alt` block and neither block encloses the other group."""
        found = {}                  # list -> [(group node, chain of enclosing if/opt nodes)]

        def visit(nodes, blocks):
            for node in nodes:
                if node.d == "group":
                    for other, other_blocks in found.get(node.key, ()):
                        apart = blocks and other_blocks and blocks[-1] not in other_blocks \
                            and other_blocks[-1] not in blocks
                        if not apart:
                            self.bad(node, "list `%s` is mapped by two groups that are not in separate "
                                           "`if`, `opt` or `alt` blocks" % node.key)
                    found.setdefault(node.key, []).append((node, blocks))
                elif node.body is not None:
                    # spec 0.20 ruling 10: each `case` and `else` is a block
                    visit(node.body, blocks + [node] if node.d in ("if", "opt", "alt", "case", "else") else blocks)
        visit(lines, [])

    def _paths_through_groups(self, lines):
        """0.7 ruling 21 with 0.8 ruling 30: a `field` whose locator passes
        through the path of a group of its scope is refused; a field at exactly
        the group's path is refused on xml only."""
        wire = self.pack.wire
        groups = [n for n in lines if n.d == "group"]
        if wire in ("bits", "text") or not groups:
            return
        xml = wire == "xml"
        below = tuple(g.loc + ("/" if xml else ".") for g in groups)
        exact = {g.loc for g in groups} if xml else ()
        for node in lines:
            if node.d == "element":
                # 0.18 ruling 12: equal to a group's path, or through it
                if node.loc in exact or (node.loc + "/").startswith(below):
                    self.bad(node, "element `%s` is or passes through the path of a group" % node.loc)
                continue
            if node.d != "field":
                continue
            # on xml the last step names an attribute or the text, not an element
            where = node.loc.rpartition("/")[0] if xml else node.loc
            if where.startswith(below) or where in exact:
                self.bad(node, "field locator `%s` passes through the path of a group of its scope" % node.loc)

    def _fixed_extents(self, lines, item):
        """The bit rules of a fixed-layout scope (0.7 "Group locators", rulings
        2 to 4, 15 and 16). `item` is the item size inside a group body."""
        groups = [n for n in lines if n.d == "group"]
        # a gate (0.17 ruling 2) and the lines of its block are placed as a field is
        placed = [n for n in walk([x for x in lines if x.d != "group"])
                  if n.d in ("field", "when", "const", "if")]
        if item is not None:
            for n in placed:
                if n.start + n.bits > item:
                    self.bad(n, "the %s reaches beyond `item %d`" % (n.d, item))
            for g in groups:
                if g.mode == "count" and g.start + g.count * g.item > item:
                    self.bad(g, "the nested group reaches beyond `item %d`" % item)
                if g.mode == "locator" and sum(g.count) > item:
                    self.bad(g, "the count locator reaches beyond `item %d`" % item)
        for g in groups:
            if g.mode == "count":
                # 0.17 ruling 9: a gate of the scope may not lie within the items
                for n in placed:
                    if n.d == "if" and n.start < g.start + g.count * g.item and n.start + n.bits > g.start:
                        self.bad(n, "the gate lies within the items of group `%s`" % g.key)
            if g.mode == "locator":
                if sum(g.count) > g.start:
                    self.bad(g, "the count locator reaches the start of its group")
                for n in placed:
                    if n.start + n.bits > g.start:
                        self.bad(n, "the %s lies at or beyond the start of the counted group `%s`" % (n.d, g.key))
                for other in groups:
                    if other is g:
                        continue
                    reach = other.start + (other.count * other.item if other.mode == "count" else 1)
                    if other.start >= g.start or reach > g.start:
                        self.bad(other, "the group reaches or follows the counted group `%s`" % g.key)
            self._fixed_extents(g.body, g.item)

    # -- the model ---------------------------------------------------------------

    def model_checks(self):
        """The checks of 0.4 "Loading" in their order, each over every line
        before the next starts."""
        pack, model = self.pack, self.model
        if pack.distribution is None:
            self.fail("missing-distribution", "the pack has no `distribution` line")
        if not pack.sources:
            self.fail("missing-source", "the pack has no `source` line")
        if model.refuses(pack.distribution):
            self.fail("distribution-refused", "the pack is controlled and the limit is public")
        for used in pack.uses:
            if used not in model.modules:
                self.fail("unknown-module", "the pack uses module `%s`, which is not loaded" % used)
        for used in pack.uses:
            if pack.distribution == "public" and model.modules[used].distribution != "public":
                self.fail("distribution-violation", "the public pack uses controlled module `%s`" % used)
        uses = set(pack.uses)
        for at, key, _ in self.key_uses:
            if split_key(key)[0] not in uses:
                self._key_fail("module-not-used", at, "`%s` is a key of a module the pack does not use" % key)
        types = {}
        for at, key, _ in self.key_uses:
            found = types.get(key)
            if found is None:
                found = types[key] = model.type_of(key)
                if found is None:
                    module, name = split_key(key)
                    self._key_fail("undeclared-key", at, "`%s`: module `%s` does not declare `%s`" % (key, module, name))
        # spec 0.20 ruling 4: a `requires` term with `=` on a list key, after
        # the key is found declared and before its values are typed
        for at, key, role in self.key_uses:
            if isinstance(role, tuple) and role[0] == "requires=" and types[key] == "list":
                self._key_fail("bad-directive", at, "`requires %s=`: a list key takes no value" % key)
        value_checks = []           # ruling 19: (line, check), run last in line order
        for at, key, role in self.key_uses:
            if isinstance(role, tuple) and role[0] == "requires=":
                value_checks.append((at, lambda at=at, key=key, role=role: self._type_check(at, key, role, types[key])))
            else:
                self._type_check(at, key, role, types[key])
        for node in self.switches:
            key_type, seen = model.type_of(node.key), set()
            for arm in node.body:
                if arm.d == "case":
                    value_checks.append((arm.line, lambda node=node, arm=arm, key_type=key_type, seen=seen:
                                         self._case_values(node, arm, key_type, seen)))
        for _, check in sorted(value_checks, key=lambda c: c[0]):
            check()
        # spec 0.33 ruling 10: the `at` form, then the fixed window
        if pack.wire == "bits" and pack.sequential:
            self._look_ahead()
        for errors in (self.at_form, self.at_window):
            if errors:
                line, message = min(errors)
                self.bad(line, message)
        return pack

    def _case_values(self, node, arm, key_type, seen):
        """Spec 0.20: each value of a `case` reads as the key's type (an `int`
        is an optional `-` and digits, ruling 17), then no value is listed
        twice in the switch once read (ruling 18: `01` and `1` are one value)."""
        for v in arm.values:
            if not reads_as_value(v, key_type):
                self._key_fail("key-type-mismatch", arm, "`case %s`: `%s` is declared %s" % (v, node.key, key_type))
        for v in arm.values:
            canonical = int(v) if key_type == "int" else float(v) if key_type == "float" else v
            if canonical in seen:
                self._key_fail("bad-directive", arm, "`case %s` lists a value of the switch again" % v)
            seen.add(canonical)

    def _key_fail(self, kind, at, message):
        self.fail(kind, message, at if isinstance(at, int) else at.line)

    def _table_type(self, table):
        """The type of a table's model side (0.6 "Value tables")."""
        values = [model for _, model in self.pack.tables[table]]
        if all(_INT.match(v) for v in values):
            return "int"
        return "float" if all(_NUMBER.match(v) for v in values) else "string"

    def _type_check(self, at, key, role, found):
        def mismatch(message):
            self._key_fail("key-type-mismatch", at, "`%s` is %s: %s" % (
                key, "a list" if found == "list" else "declared " + found, message))

        if role == "requires":
            return
        if isinstance(role, tuple) and role[0] == "requires=":
            for v in role[1]:
                if not reads_as_value(v, found):
                    mismatch("the `requires` value `%s` cannot be read as that type" % v)
            return
        if role == "group":
            if found != "list":
                mismatch("a `group` needs a list")
            return
        if role == "as":
            # spec 0.30: the key of `when ... as` is declared `int`
            if found != "int":
                mismatch("`when ... as` needs an `int` key")
            return
        if found == "list":
            mismatch("a `%s` needs a scalar key" % (role if isinstance(role, str) else "also"))
        if role == "default":
            if not reads_as(at.value, found):
                mismatch("the default `%s` cannot be read as that type" % at.value)
            return
        field = at if role == "field" else role[1]
        if at.via is not None:
            yields = self._table_type(at.via)
            if yields != found and not (yields == "int" and found == "float"):
                mismatch("table `%s` holds %s values" % (at.via, yields))
        else:
            table = UPER_TRANSFORMS[field.uper[0]] if field.uper else TRANSFORMS[self.pack.wire]
            yields = table[field.tr]
            if yields != found:
                mismatch("transform `%s` yields %s" % (field.tr, yields))


def load_pack(text, model, label=None):
    """Load one pack text against the modules of `model` and return the Pack.
    Raises CheckError for the first rule the text breaks, in the order of
    engine-spec 0.4 "Loading": line errors and the checks that need the whole
    file, then `missing-distribution`, `missing-source`, `distribution-refused`,
    `unknown-module`, `distribution-violation`, `module-not-used`,
    `undeclared-key`, `key-type-mismatch`."""
    return _Loader(text, model, label).structure().lines().model_checks()


def load_pack_file(path, model):
    with open(path, encoding="utf-8") as fh:
        return load_pack(fh.read(), model, path)


def check_output(model_dir, pack_paths, max_distribution="controlled"):
    """Load a model directory and then each pack file; the packs, in order.
    This is the whole of a generator's check of what it wrote."""
    model = Model(max_distribution).load_dir(model_dir)
    return model, [load_pack_file(path, model) for path in pack_paths]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Load model modules and packs as an engine does and report the first rule each file breaks. "
                    "Inputs: a model directory and pack.def files. Guarantee: exit status 0 only when every "
                    "file loads; nothing is written.")
    ap.add_argument("--model", required=True, metavar="DIR", help="directory of model modules (*.def)")
    ap.add_argument("--max-distribution", choices=DISTRIBUTIONS, default="controlled")
    ap.add_argument("packs", nargs="*", metavar="PACK.DEF")
    args = ap.parse_args(argv)
    try:
        model = Model(args.max_distribution).load_dir(args.model)
    except (CheckError, OSError) as e:
        print("gtcheck: %s" % e, file=sys.stderr)
        return 1
    failed = 0
    for path in args.packs:
        try:
            load_pack_file(path, model)
        except (CheckError, OSError) as e:
            print("gtcheck: %s" % e, file=sys.stderr)
            failed += 1
    if not failed:
        print("gtcheck: ok, %d modules, %d packs" % (len(model.modules), len(args.packs)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
