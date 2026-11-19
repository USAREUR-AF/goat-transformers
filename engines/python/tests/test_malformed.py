"""Malformed input (spec/engine-spec.md, "Malformed input (0.8)", rulings 35
to 39; spec/vector-format.md, "Malformed input").

`TestDamagedVectors` takes the input of every conversion vector of every
loaded pack, cuts it at prefixes and changes single characters (fixed seed),
and converts each damaged input. A conversion may succeed or fail; a failure
must be the engine's own exception class with a message that begins with a named
kind and a colon, and a result must be text that encodes as UTF-8.

The other classes state the rulings directly, including the cases no vector
pins.
"""

import glob
import json
import os
import random
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
PACKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs"))

from goat_transformers import Engine, GTError  # noqa: E402

SEED = 0x60A7
PREFIXES = 3   # cuts per vector input
MUTATIONS = 3  # single-character changes per vector input
KIND = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*: ")
# Characters that carry structure on one wire or another, and a few that carry
# none: a control character, a character outside ASCII, a character outside
# the basic plane.
ALPHABET = "<>/=\"'&;!?#{}[]:,\\+-.0179aefglnrstux \t\n\x00\x7fé \U0001f410"

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = Engine.from_dir(PACKS)
    return _ENGINE


def damaged(text, rng):
    """-> the damaged forms of one input: the empty input, prefixes, and
    single characters replaced, removed and doubled."""
    out = [""]
    n = len(text)
    if n == 0:
        return out
    for _ in range(PREFIXES):
        out.append(text[:rng.randrange(n)])
    for k in range(MUTATIONS):
        i = rng.randrange(n)
        if k == 0:
            out.append(text[:i] + text[i + 1:])
        elif k == 1:
            out.append(text[:i] + text[i] + text[i:])
        else:
            out.append(text[:i] + rng.choice(ALPHABET) + text[i + 1:])
    return out


def outcome(eng, src, dst, data, context=None):
    """Convert one input -> None when the engine behaved, else what it did."""
    try:
        if context is None:
            got = eng.convert(src, dst, data)
        else:
            got = eng.convert(src, dst, data, context)
    except GTError as e:
        text = str(e)
        if not KIND.match(text):
            return "error with no named kind: %r" % text[:200]
        if not text.startswith(e.code + ":"):
            return "error message does not begin with its kind %s: %r" % (e.code, text[:200])
        return None
    except BaseException as e:  # RecursionError, MemoryError, IndexError, ...
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return "%s: %s" % (type(e).__name__, str(e)[:200])
    try:
        (got if isinstance(got, bytes) else got.encode("utf-8"))
    except Exception as e:
        return "the result is not UTF-8 text: %s" % type(e).__name__
    return None


class TestDamagedVectors(unittest.TestCase):
    def test_damaged_inputs_fail_only_with_a_named_error(self):
        eng = engine()
        rng = random.Random(SEED)
        formats = set(eng.formats())
        problems = []
        vectors = inputs = 0
        seen = set()
        for path in sorted(glob.glob(os.path.join(PACKS, "*", "vectors", "*.json"))):
            with open(path, "r", encoding="utf-8") as fh:
                vec = json.load(fh)
            src, dst, text = vec.get("from"), vec.get("to"), vec.get("input")
            if src not in formats or dst not in formats or not isinstance(text, str):
                continue
            vectors += 1
            context = vec.get("context")
            for data in damaged(text, rng):
                key = (src, dst, data)
                if key in seen:
                    continue
                seen.add(key)
                inputs += 1
                what = outcome(eng, src, dst, data, context)
                if what is not None:
                    problems.append("%s: %s on input %r" % (os.path.relpath(path, PACKS), what, data[:120]))
        sys.stderr.write(
            "[goat_transformers] damaged inputs: %d from %d vectors over %d packs, %d misbehaved\n"
            % (inputs, vectors, len(formats), len(problems))
        )
        self.assertGreater(inputs, 0)
        self.assertEqual(problems, [], "\n".join(problems[:40]))

    def test_every_prefix_of_the_malformed_packs(self):
        """Every prefix and every single-character change of the well-formed
        message of each `conformance-malformed-*` pack."""
        eng = engine()
        rng = random.Random(SEED)
        problems = []
        for path in sorted(glob.glob(os.path.join(PACKS, "conformance-malformed-*", "vectors", "01-*.json"))):
            with open(path, "r", encoding="utf-8") as fh:
                vec = json.load(fh)
            fmt, text = vec["from"], vec["input"]
            forms = [text[:i] for i in range(len(text))]
            for i in range(len(text)):
                for ch in rng.sample(ALPHABET, 6):
                    forms.append(text[:i] + ch + text[i + 1:])
            for data in forms:
                what = outcome(eng, fmt, fmt, data)
                if what is not None:
                    problems.append("%s: %s on input %r" % (fmt, what, data[:120]))
        self.assertEqual(problems, [], "\n".join(problems[:40]))


class _Rulings(unittest.TestCase):
    fmt = None

    def malformed(self, data, fmt=None):
        fmt = fmt or self.fmt
        for call in (engine().decode, lambda f, d: engine().convert(f, f, d)):
            with self.assertRaises(GTError, msg=repr(data[:80])) as cm:
                call(fmt, data)
            self.assertEqual(cm.exception.code, "malformed-wire", repr(data[:80]))
            self.assertTrue(str(cm.exception).startswith("malformed-wire:"))

    def converts(self, data, fmt=None):
        fmt = fmt or self.fmt
        got = engine().convert(fmt, fmt, data)
        return got.decode("utf-8") if isinstance(got, bytes) else got


class TestNesting(_Rulings):
    """Ruling 35."""

    def test_json_levels(self):
        fmt = "conformance-malformed-json"
        # the message object is level 1
        self.converts('{"id":"u1","a":' + "[" * 63 + "]" * 63 + "}", fmt)
        self.malformed('{"id":"u1","a":' + "[" * 64 + "]" * 64 + "}", fmt)
        self.malformed('{"id":"u1","a":' + '{"a":' * 64 + "1" + "}" * 64 + "}", fmt)

    def test_brackets_inside_strings_are_not_levels(self):
        fmt = "conformance-malformed-json"
        self.converts('{"id":"' + "[{" * 200 + '","k\\"[[":"]\\\\"}', fmt)

    def test_geojson_levels(self):
        fmt = "conformance-malformed-geojson"
        head = '{"type":"Feature","geometry":null,"properties":{"x":'
        self.converts(head + "[" * 62 + "]" * 62 + '},"id":"u1"}', fmt)
        self.malformed(head + "[" * 63 + "]" * 63 + '},"id":"u1"}', fmt)

    def test_xml_levels(self):
        fmt = "conformance-malformed-xml"
        self.converts('<event uid="u1">' + "<a>" * 63 + "</a>" * 63 + "</event>", fmt)
        self.malformed('<event uid="u1">' + "<a>" * 64 + "</a>" * 64 + "</event>", fmt)
        self.malformed('<event uid="u1">' + "<a>" * 63 + "<a/>" + "</a>" * 63 + "</event>", fmt)

    def test_very_deep_input_uses_no_stack(self):
        deep = 200000
        self.malformed("[" * deep, "conformance-malformed-json")
        self.malformed("[" * deep + "]" * deep, "conformance-malformed-json")
        self.malformed('{"a":' * deep, "conformance-malformed-json")
        self.malformed("[" * deep, "conformance-malformed-geojson")
        self.malformed("<a>" * deep, "conformance-malformed-xml")
        self.malformed("<event>" + "<a>" * deep + "</a>" * deep + "</event>", "conformance-malformed-xml")


class TestHex(_Rulings):
    """Ruling 36."""

    def test_hex(self):
        for fmt in ("conformance-malformed-bits", "conformance-malformed-protobuf"):
            with open(glob.glob(os.path.join(PACKS, fmt, "vectors", "01-*.json"))[0], encoding="utf-8") as fh:
                good = json.load(fh)["input"]
            self.converts(good, fmt)
            self.converts(" " + good[:2] + "\t\r\n" + good[2:] + "\n", fmt)
            self.converts(good.upper(), fmt)
            self.malformed(good[:-1], fmt)
            self.malformed(good + "0", fmt)
            for bad in ("+", "-", "g", "x", "_", "١", "１", " ", "\x00", "\x0b", "\x0c", " "):
                self.malformed(bad + good[1:], fmt)
                self.malformed(good[:2] + bad + good[2:], fmt)
            self.malformed("0x" + good[2:], fmt)
            self.malformed("+" + good, fmt)


class TestXml(_Rulings):
    """Ruling 37 and the `xml` row of the table."""

    fmt = "conformance-malformed-xml"

    def test_no_element(self):
        for data in ("", " \n", "<?xml version=\"1.0\"?>", "<!-- c -->", "﻿", "text"):
            self.malformed(data)

    def test_another_root_is_missing_root(self):
        with self.assertRaises(GTError) as cm:
            engine().decode(self.fmt, '<other uid="u1"/>')
        self.assertEqual(cm.exception.code, "missing-root")

    def test_misc_after_the_root(self):
        self.assertEqual(self.converts('<event uid="u1"/> <!-- c --><?pi x?>\n'), '<event uid="u1"/>')
        for tail in ("x", "<event/>", "&amp;", "<![CDATA[x]]>", "<", "<!-- c", "<?pi"):
            self.malformed('<event uid="u1"/>' + tail)

    def test_declarations_and_entities(self):
        # no document type declaration is read, so no entity is declared,
        # expanded or fetched
        self.malformed('<!DOCTYPE event [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><event uid="&b;"/>')
        self.malformed('<!DOCTYPE event [<!ENTITY x SYSTEM "file:///etc/hostname">]><event uid="&x;"/>')
        self.malformed('<!doctype event><event uid="u1"/>')
        self.malformed('<!DocType event><event uid="u1"/>')
        self.malformed('<event uid="u1"><!ENTITY a "b"></event>')
        self.malformed('<event uid="&undeclared;"/>')
        self.malformed('<event uid="a & b"/>')
        self.malformed('<event uid="u1">&x;</event>')

    def test_document_type_declaration_anywhere(self):
        """Ruling 40."""
        d = "<!DOCTYPE event>"
        for data in (d + '<event uid="u1"/>', '<?xml version="1.0"?>\n' + d + '<event uid="u1"/>',
                     "<!-- c -->" + d + '<event uid="u1"/>', '<event uid="u1"/>' + d,
                     '<event uid="u1">' + d + "</event>", '<event uid="u1"><contact>' + d + "</contact></event>",
                     '<!DOCTYPE event SYSTEM "http://127.0.0.1:9/x.dtd"><event uid="u1"/>',
                     '<!DOCTYPE event [<!ENTITY % p SYSTEM "file:///etc/hostname"> %p;]><event uid="u1"/>'):
            self.malformed(data)

    def test_signed_and_malformed_character_references(self):
        """Ruling 40: decimal or hexadecimal digits only."""
        for ref in ("&#+65;", "&#-65;", "&#x+41;", "&#x-41;", "&#X41;", "&#0x41;", "&#4 1;", "&#x4g;", "&#6_5;",
                    "&#\u0666\u0665;", "&#1;", "&#8;", "&#xB;", "&#x1F;", "&#xFFFF;"):
            self.malformed('<event uid="%s"/>' % ref)
            self.malformed('<event uid="u1"><contact callsign="x">%s</contact></event>' % ref)
        for ref, ch in (("&#9;", "&#9;"), ("&#x10FFFF;", "\U0010ffff"), ("&#0065;", "A"), ("&#x0000041;", "A"),
                        ("&#xE000;", "\ue000"), ("&#xfffd;", "\ufffd")):
            self.assertEqual(self.converts('<event uid="%s"/>' % ref), '<event uid="%s"/>' % ch)

    def test_character_references(self):
        self.assertEqual(self.converts('<event uid="&#x41;&#66;&lt;"/>'), '<event uid="AB&lt;"/>')
        for ref in ("&#0;", "&#x0;", "&#xD800;", "&#xDFFF;", "&#xFFFE;", "&#x110000;", "&#1114112;",
                    "&#x" + "f" * 5000 + ";", "&#" + "9" * 5000 + ";", "&#x;", "&#;", "&#1"):
            self.malformed('<event uid="%s"/>' % ref)
            self.malformed('<event uid="u1"><contact callsign="x">%s</contact></event>' % ref)

    def test_tags(self):
        for data in ('<event uid="u1" uid="u2"/>', "<event uid='u1\"/>", '<event uid="a<b"/>', "<event uid=u1/>",
                     "<event uid/>", "< event/>", "<event></ event>", "<event/", "<event", "<>", "</event>",
                     "<!event/>", "<?event/>", '<event uid="u1"><!x/></event>', "<event><a></event></a>"):
            self.malformed(data)

    def test_many_attributes(self):
        # the duplicate check does not take time quadratic in the attributes
        attrs = " ".join('a%d="1"' % i for i in range(60000))
        self.assertEqual(self.converts('<event uid="u1" %s/>' % attrs)[:17], '<event uid="u1" a')
        self.malformed('<event uid="u1" %s a7="2"/>' % attrs)


class TestProtobuf(_Rulings):
    """Ruling 38."""

    fmt = "conformance-malformed-protobuf"

    def test_syntax(self):
        self.converts("0a027531")
        self.malformed("0a")                        # length missing
        self.malformed("0a0375")                    # length past the input
        self.malformed("10")                        # varint value missing
        self.malformed("1080")                      # truncated varint
        self.malformed("10" + "ff" * 10 + "01")     # varint of eleven bytes
        self.malformed("80")                        # truncated tag
        self.malformed("19" + "00" * 7)             # fixed64 cut short
        self.malformed("2d" + "00" * 3)             # fixed32 cut short
        self.malformed("0a" + "ff" * 9 + "01" + "75")  # length of 2^64-1
        self.malformed("0a" + "ff" * 9 + "7f" + "75")  # length of 2^70-1

    def test_ten_byte_varint(self):
        """Ruling 40: a tenth byte greater than 1 holds bits above bit 63."""
        self.converts("0a027531" + "10" + "ff" * 9 + "01")
        self.converts("0a027531" + "10" + "80" * 9 + "01")
        for last in ("02", "03", "7f", "40"):
            self.malformed("0a027531" + "10" + "ff" * 9 + last)   # a value
            self.malformed("0a027531" + "48" + "80" * 9 + last)   # a field no line maps
            self.malformed("80" * 9 + last + "00")                # a tag
            self.malformed("0a" + "80" * 9 + last)                # a length

    def test_packed_varints(self):
        """Ruling 40: a truncated varint inside a packed field."""
        fmt = "conformance-groups-protobuf"
        self.converts("0a0175" + "3203010203", fmt)
        self.malformed("0a0175" + "3203010280", fmt)
        self.malformed("0a0175" + "320180", fmt)
        self.malformed("0a0175" + "1a030a0180", fmt)                 # packed, inside a submessage
        self.malformed("0a0175" + "320b" + "ff" * 10 + "01", fmt)    # eleven bytes
        self.malformed("0a0175" + "320a" + "ff" * 9 + "02", fmt)     # more than 64 bits

    def test_groups_and_unknown_wire_types(self):
        for wt in (3, 4, 6, 7):
            self.malformed("%02x" % (9 << 3 | wt))
            self.malformed("%02x00" % (9 << 3 | wt))

    def test_field_numbers(self):
        top = (1 << 29) - 1
        self.converts("0a027531" + self._tag(top, 0) + "01")
        self.malformed("0a027531" + self._tag(top + 1, 0) + "01")
        self.malformed("0a027531" + self._tag(1 << 40, 0) + "01")
        self.malformed("0001")  # field number 0

    def test_unmapped_fields_are_checked(self):
        self.converts("0a027531" + "4a0141")       # field 9, one byte
        self.malformed("0a027531" + "4a0541")      # field 9, length past the input
        self.malformed("0a027531" + "49" + "00" * 7)
        self.malformed("0a027531" + "4880")

    def test_submessage_a_path_walks_into(self):
        self.converts("0a027531" + "22030a0141")
        self.malformed("0a027531" + "22030a0541")  # inner length past the submessage
        self.malformed("0a027531" + "2202" + "0a80")
        self.malformed("0a027531" + "2201" + "0b")  # a group tag inside the submessage
        self.malformed("0a027531" + "2001")         # field 4 is not a submessage

    @staticmethod
    def _tag(num, wt):
        v = num << 3 | wt
        out = bytearray()
        while True:
            b = v & 0x7F
            v >>= 7
            out.append(b | 0x80 if v else b)
            if not v:
                return out.hex()


class TestJsonGrammar(_Rulings):
    """Ruling 39 and the `json`, `geojson` row of the table."""

    WRAPS = (
        ("conformance-malformed-json", '{"id":"u1","x":%s}'),
        ("conformance-malformed-json", '{"id":"u1","x":[%s]}'),
        ("conformance-malformed-json", '{"id":"u1","pos":{"lat":%s}}'),
        ("conformance-malformed-geojson", '{"type":"Feature","geometry":null,"properties":{"x":%s},"id":"u1"}'),
        ("conformance-malformed-geojson", '{"type":"Feature","geometry":null,"properties":{},"id":"u1","x":[%s]}'),
    )

    def each(self, values, check, numbers=False):
        for fmt, wrap in self.WRAPS:
            if "lat" in wrap and not numbers:
                continue  # the member a float field maps
            for v in values:
                check(wrap % v, fmt)

    def test_numbers(self):
        self.each(("0", "-0", "1", "-1", "1.5", "0.5", "-0.5", "1e5", "1E5", "1e+5", "1e-5", "0e0", "1.0e00",
                   "12345678901234567890"), self.converts, numbers=True)
        self.each(("01", "-01", "00", "+1", "+0", ".5", "-.5", "1.", "1.e5", ".", "-", "+", "1e", "1e+", "1.5.5",
                   "0x10", "1_000", "NaN", "Infinity", "-Infinity", "+Infinity", "nan", "inf", "1 2", "١",
                   "１", "1e1.5", "--1", "0.e1"), self.malformed, numbers=True)

    def test_huge_numbers_are_a_named_error(self):
        for fmt, wrap in self.WRAPS:
            for v in ("9" * 6000, "1e999999999", "-1e999999999", "1e-999999999", "0." + "0" * 6000 + "1",
                      "1" + "0" * 400, "1e400"):
                self.assertIsNone(outcome(engine(), fmt, fmt, wrap % v), v[:20])

    def test_huge_exponent_on_an_int_field_ends(self):
        """`2e47686170` on an `int` field is a 47-million-digit integer. The
        field's transform refuses it at once instead of building it, and the
        decode fails with `transform-decode`: through `int` the exact value of
        a JSON number must be an integer within a signed 64-bit integer
        (ruling 2d of 0.11)."""
        import time

        eng = Engine()
        eng.load_model("module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey n int -\n")
        eng.load("format x\nversion 1\ndistribution public\nsource s\nwire json\nfield n n int\n")
        for v in ("2e47686170", "-1e999999999", "1.5e4400", "1e4300"):
            start = time.monotonic()
            with self.assertRaises(GTError, msg=v) as cm:
                eng.decode("x", '{"n":%s}' % v)
            self.assertEqual(cm.exception.code, "transform-decode", v)
            self.assertLess(time.monotonic() - start, 1.0, v)
        self.assertEqual(eng.decode("x", '{"n":1e3}').fields, {"n": 1000})
        with self.assertRaises(GTError) as cm:
            eng.decode("x", '{"n":1e300}')
        self.assertEqual(cm.exception.code, "transform-decode")
        from goat_transformers.transforms import IntT

        for v in ("1e4300", "2e47686170", "1e4299", "9" * 6000):
            for read in (IntT().decode, IntT().decode_json):
                start = time.monotonic()
                with self.assertRaises(ValueError, msg=v[:20]):
                    read(v)
                self.assertLess(time.monotonic() - start, 1.0, v[:20])
        self.assertEqual(IntT().decode_json("9.223372036854775807e18"), (1 << 63) - 1)

    def test_strings(self):
        self.each(('"a"', '"\\n\\t\\r\\b\\f\\/\\\\\\""', '"\\u0041"', '"\\ud83d\\udc10"', '"\x7f"', '"é"',
                   '"\U0001f410"', '""'), self.converts)
        self.each(('"\\x41"', '"\\a"', '"\\\'"', '"\\U0041"', '"\\u004"', '"\\u00g1"', '"\\u+041"', '"\\u 041"',
                   '"\\"', '"a\nb"', '"a\tb"', '"a\x00b"', '"a\x1fb"', "'a'", '"a', 'a"',
                   '"\\ud800"', '"\\udc10"', '"\\ud83d\\u0041"', '"\\ud83dx"', '"\\udc10\\ud83d"'), self.malformed)

    def test_structure(self):
        for fmt, wrap in self.WRAPS[:2]:
            for v in ("tru", "True", "nul", "NULL", "undefined", "[1,]", "[,1]", "[1 2]", "{\"a\":1,}", "{\"a\"}",
                      "{a:1}", "{\"a\":}", "{1:2}", "[1]]", "/*c*/1", "1//c", ",", ":"):
                self.malformed(wrap % v, fmt)
        for fmt in ("conformance-malformed-json", "conformance-malformed-geojson"):
            for data in ("", " ", "{}{}", "{} x", "{},", "﻿{}", "{}\x00", "{}\x0c", "{} ", "[", "nul"):
                self.malformed(data, fmt)

    def test_whitespace(self):
        self.assertEqual(
            self.converts(' \t\r\n{ "id" : "u1" ,\n"x" : [ 1 , 2 ] }\n ', "conformance-malformed-json"),
            '{"id":"u1"}',
        )

    def test_duplicate_members(self):
        # refused on `json` (0.5 ruling 22), the last stands on `geojson` (0.5 ruling 28)
        self.malformed('{"id":"u1","id":"u2"}', "conformance-malformed-json")
        self.malformed('{"id":"u1","x":{"a":1,"a":2}}', "conformance-malformed-json")
        engine().decode(
            "conformance-malformed-geojson",
            '{"type":"Feature","geometry":null,"properties":{"a":1,"a":2},"id":"u1"}',
        )

    def test_not_utf8(self):
        for fmt in ("conformance-malformed-json", "conformance-malformed-geojson", "conformance-malformed-xml",
                    "conformance-malformed-bits", "conformance-malformed-protobuf"):
            self.malformed(b"\xff\xfe{}", fmt)
            self.malformed(b'{"id":"\xc3"}', fmt)
            self.malformed(b"\xed\xa0\x80", fmt)


class TestTlv(_Rulings):
    """The `tlv` wire (0.13, "Encodings" and "Reading a message"): every
    failure of the reading steps is `malformed-wire`, on lengths compared with
    the bytes left, whatever the pack maps."""

    fmt = "conformance-tlv"   # key 060e2b34, BER-OID tags, BER lengths, checksum sum16 1
    fixed = "conformance-tlv-fixed"  # tags of one byte, lengths of two, no key, no checksum

    @staticmethod
    def message(items, length=None):
        """The key, the set's BER length (or `length`, hex) and `items` (hex), then a correct checksum item."""
        body = bytes.fromhex(items) + b"\x01\x02"
        n = len(body) + 2
        head = bytes.fromhex("060e2b34") + (
            bytes.fromhex(length) if length is not None else
            bytes((n,)) if n < 128 else bytes((0x80 | ((n.bit_length() + 7) // 8),)) + n.to_bytes(
                (n.bit_length() + 7) // 8, "big"))
        out = head + body
        total = sum(b * 256 if i % 2 == 0 else b for i, b in enumerate(out)) & 0xFFFF
        return (out + total.to_bytes(2, "big")).hex()

    def test_well_formed(self):
        # the default probe.y 7 writes 48.200 on encode
        self.assertEqual(self.converts(self.message("410101")), self.message("30058148020007" + "410101"))
        self.converts(self.message("410101" + "ffffff7f00"))        # a four-byte tag, residue
        self.converts(self.message("410101" + "3283000001aa"))      # a long form longer than needed
        self.converts(self.message("410101" + "3288" + "00" * 7 + "01aa"))
        self.assertEqual(self.converts("", self.fixed), "")         # no key, no checksum: an empty set

    def test_tags(self):
        self.malformed(self.message("410101" + "8001" + "00"))          # first byte 0x80
        self.malformed(self.message("410101" + "8180808001" + "00"))    # a fifth byte
        self.malformed(self.message("410101" + "ffffffff7f" + "00"))
        self.malformed(self.message("410101" + "81"))                   # a tag cut by the end of the set
        self.malformed("02", self.fixed)

    def test_lengths(self):
        for bad in ("80", "89", "ff", "8a01"):
            self.malformed(self.message("410101" + "32" + bad + "00"))
        self.malformed(self.message("410101" + "3281"))                      # a long form cut short
        self.malformed(self.message("410101" + "3288" + "ff" * 8 + "00"))    # 2^64-1
        self.malformed(self.message("410101" + "3288" + "ff" * 7 + "fe" + "00"))
        self.malformed(self.message("410101" + "3203" + "aabb"))             # past its set
        self.malformed(self.message("410101", length="88" + "ff" * 8))       # the set: 2^64-1
        self.malformed(self.message("410101", length="80"))
        self.malformed("0200", self.fixed)
        self.malformed("0200ff41", self.fixed)
        self.malformed("02ffff41", self.fixed)

    def test_key_and_checksum(self):
        good = self.message("410101")
        self.malformed("")
        self.malformed("060e2b")
        self.malformed("060e2b35" + good[8:])
        self.malformed(good[:-2] + "%02x" % (int(good[-2:], 16) ^ 1))
        self.malformed(good[:-8])                                    # no checksum item
        self.malformed(self.message("410101" + "01020000"))        # a checksum tag before the last
        self.malformed(good + "0")                                   # odd digits
        self.assertEqual(self.converts(good + "dead"), self.converts(good))  # bytes after the set are ignored

    def test_nested_sets(self):
        # 48 is walked into by the common lines: its items are read whole
        self.converts(self.message("410101" + "3003020105"))
        self.malformed(self.message("410101" + "30030205ff"))
        self.malformed(self.message("410101" + "300180"))
        self.malformed(self.message("410101" + "30028001"))
        # 49 is walked into by no line: one residue item, never read as a set
        self.converts(self.message("410101" + "310180"))

    def test_every_prefix_and_change(self):
        """Every prefix and every single-character change of a well-formed
        message of each tlv probe pack."""
        rng = random.Random(SEED)
        problems = []
        for fmt in (self.fmt, self.fixed):
            with open(glob.glob(os.path.join(PACKS, fmt, "vectors", "01-*.json"))[0], encoding="utf-8") as fh:
                text = json.load(fh)["input"]
            forms = [text[:i] for i in range(len(text))]
            for i in range(len(text)):
                for ch in rng.sample("0123456789abcdef8f " + ALPHABET, 6):
                    forms.append(text[:i] + ch + text[i + 1:])
            for data in forms:
                what = outcome(engine(), fmt, fmt, data)
                if what is not None:
                    problems.append("%s: %s on input %r" % (fmt, what, data[:120]))
        self.assertEqual(problems, [], "\n".join(problems[:40]))


if __name__ == "__main__":
    unittest.main()
