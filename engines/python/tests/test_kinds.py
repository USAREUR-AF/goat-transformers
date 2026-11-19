"""Unit tests for Version 0.5 beyond the shared vectors (spec/engine-spec.md,
"Version 0.5: message kinds and the `json` wire"): kind selection, `Entity.kind`,
the `json` wire, `bit_order`, fields past their word, the 0.5 bits transforms,
the rulings and the named errors."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import (  # noqa: E402
    BadDirective, DuplicateField, DuplicateKind, Engine, Entity, GTError, InvalidPack, MalformedWire, MissingWire,
    NoKind,
    TransformDecodeFailure, TransformEncodeFailure, parse_model_text, parse_pack_text,
)
from goat_transformers.transforms import build_bits_transform, format_float, round_half_away  # noqa: E402

CORE = """
module core
version 0.1.0
distribution public
source "unit tests"
key uid   string -
key name  string -
key alias string -
key lat   float  deg
key lon   float  deg
key alt   float  m
key n     int    -
key flag  int    -
key t     int    ms
"""

HEAD = "format %s\nversion 0.5.0\ndistribution public\nsource \"unit tests\"\n"


def engine(*packs):
    return Engine([parse_pack_text(p) for p in packs], models=[parse_model_text(CORE)])


def code(exc):
    return exc.exception.code


class TestKindGrammar(unittest.TestCase):
    def test_structure(self):
        p = parse_pack_text(
            HEAD % "k" + "wire xml\nroot r\nfield uid @id string\nwhen @v 1\n"
            "kind a\nwhen @k a\nrequires lat lon\nfield lat @lat float\nkind b\nfield lat p/@lat float\n"
        )
        self.assertEqual([k.name for k in p.kinds], ["a", "b"])
        self.assertEqual([ln.locator for ln in p.common], ["@id", "@v"])
        self.assertEqual(p.kinds[0].requires, ["lat", "lon"])
        self.assertEqual([ln.locator for ln in p.lines(p.kinds[0])], ["@id", "@v", "@k", "@lat"])
        self.assertEqual(p.model_keys(), ["uid", "lat"])

    def test_named_load_errors(self):
        x = HEAD % "k" + "wire xml\nroot r\n"
        cases = [
            (x + "kind a\nkind a\n", DuplicateKind, "duplicate-kind"),
            (x + "requires uid\nkind a\n", BadDirective, "bad-directive"),
            (x + "when @k a\n", BadDirective, "bad-directive"),
            (x + "bit_order msb\n", BadDirective, "bad-directive"),
            (HEAD % "k" + "bit_order msb\nwire json\n", MissingWire, "missing-wire"),  # ruling 5b of 0.11
        ]
        b = HEAD % "k" + "wire bits\nword_bytes 1\n"
        cases += [
            (b + "field lat 0:0:16 f32\n", BadDirective, "bad-directive"),
            (b + "field lat 0:0:32 f64\n", BadDirective, "bad-directive"),
            (b + "field name 0:0:12 ascii\n", BadDirective, "bad-directive"),
            (b + "field name 0:0:2048 ascii\n", BadDirective, "bad-directive"),
            (b + "kind a\nwhen 0:0:4 16\n", BadDirective, "bad-directive"),
            (b + "bit_order big\n", BadDirective, "bad-directive"),
        ]
        for text, cls, kind in cases:
            with self.assertRaises(cls, msg=text) as cm:
                parse_pack_text(text)
            self.assertEqual(code(cm), kind)
            self.assertTrue(str(cm.exception).startswith(kind + ":"), str(cm.exception))

    def test_same_key_twice_with_kinds_loads(self):
        # 0.6 withdraws `duplicate-field`: in any pack a key may be mapped by several lines.
        x = HEAD % "k" + "wire xml\nroot r\n"
        for text in (
            x + "kind a\nfield lat @a float\nfield lat @b float\n",
            x + "field uid @a string\nkind a\nfield uid @b string\n",
            x + "field uid @a string\nfield uid @b string\nkind a\n",
        ):
            self.assertEqual(len(parse_pack_text(text).fields), 2, text)

    def test_same_key_twice_without_kinds_loads(self):
        p = parse_pack_text(HEAD % "k" + "wire xml\nroot r\nfield uid @a string\nfield uid @b string\nfield name @a string\n")
        self.assertEqual(len(p.fields), 3)

    def test_bool_is_json_only(self):
        with self.assertRaises(InvalidPack):
            parse_pack_text(HEAD % "k" + "wire xml\nroot r\nfield flag @f bool\n")
        with self.assertRaises(InvalidPack):
            parse_pack_text(HEAD % "k" + "wire geojson\nfield flag properties.f bool\n")

    def test_quotes_and_comments(self):
        # 0.5 rulings 6 and 17: `#` inside quotes is literal; there is no escape.
        p = parse_pack_text(HEAD % "k" + 'wire json\nfield uid "a # b" string  # trailing\n')
        self.assertEqual(p.fields[0].locator, "a # b")
        p = parse_pack_text(HEAD % "k" + 'wire json\nfield uid "a\\b" string\n')
        self.assertEqual(p.fields[0].locator, "a\\b")

    def test_requires_keys_checked_at_load(self):
        e = Engine(models=[parse_model_text(CORE)])
        with self.assertRaises(GTError) as cm:
            e.load(HEAD % "k" + "wire xml\nroot r\nkind a\nrequires nope\n")
        self.assertEqual(code(cm), "undeclared-key")
        with self.assertRaises(GTError) as cm:
            e.load(HEAD % "k" + "wire xml\nroot r\nkind a\nrequires ext.rank\n")
        self.assertEqual(code(cm), "module-not-used")
        e.load(HEAD % "k" + "wire xml\nroot r\nkind a\nrequires t name\nfield lat @lat float\n")  # ruling 4


XML_KINDS = HEAD % "xk" + """
wire xml
root m
field uid @id string
kind pos
when @k p
requires lat lon
field lat @lat float
field lon @lon float
kind named
when name/@v present
requires name
field name name/@v string
kind other
"""

JSON_OTHER = HEAD % "jo" + """
wire json
field uid id string
field name label string
field lat pos.lat float
field lon pos.lon float
"""


class TestKindSelection(unittest.TestCase):
    def setUp(self):
        self.e = engine(XML_KINDS, JSON_OTHER)

    def test_decode_selects_first_matching_kind(self):
        ent = self.e.decode("xk", '<m id="a" k="p" lat="1.5" lon="2"><name v="N"/></m>')
        self.assertEqual(ent.kind, ("xk", "pos"))
        self.assertNotIn("name", ent.fields)  # fields of other kinds are not read
        self.assertEqual(self.e.decode("xk", '<m id="a"><name v="N"/></m>').kind, ("xk", "named"))
        self.assertEqual(self.e.decode("xk", '<m id="a"/>').kind, ("xk", "other"))
        self.assertIsNone(self.e.decode("jo", '{"id":"a"}').kind)

    def test_encode_uses_entity_kind_then_requires(self):
        ent = Entity(fields={"uid": "a", "lat": 1.5, "lon": 2.0, "name": "N"})
        self.assertEqual(self.e.encode("xk", ent).decode(), '<m id="a" k="p" lat="1.5" lon="2"/>')
        ent.kind = ("xk", "named")
        self.assertEqual(self.e.encode("xk", ent).decode(), '<m id="a"><name v="N"/></m>')
        ent.kind = ("jo", "named")  # names another format: selection falls to `requires`
        self.assertEqual(self.e.encode("xk", ent).decode(), '<m id="a" k="p" lat="1.5" lon="2"/>')
        ent.kind = ("xk", "gone")
        with self.assertRaises(NoKind):
            self.e.encode("xk", ent)

    def test_convert_clears_kind_across_formats_only(self):
        # Same format: the kind is kept, although `requires` would pick `pos`.
        src = '<m id="a" lat="1.5" lon="2"><name v="N"/></m>'
        self.assertEqual(self.e.convert("xk", "xk", src).decode(), '<m id="a" lat="1.5" lon="2"><name v="N"/></m>')
        # Cross format: the target kind is chosen by `requires`.
        self.assertEqual(
            self.e.convert("jo", "xk", '{"id":"a","label":"N"}').decode(), '<m id="a"><name v="N"/></m>'
        )

    def test_no_kind(self):
        e = engine(HEAD % "nk" + "wire xml\nroot m\nwhen @v 1\nkind a\nwhen @k a\nrequires lat\nfield lat @lat float\n")
        for bad in ('<m k="a"/>', '<m v="1"/>', '<m v="1" k="b"/>'):
            with self.assertRaises(NoKind, msg=bad) as cm:
                e.decode("nk", bad)
            self.assertTrue(str(cm.exception).startswith("no-kind:"))
        with self.assertRaises(NoKind):
            e.encode("nk", Entity(fields={"uid": "a"}))
        self.assertEqual(e.encode("nk", Entity(fields={"lat": 1.0})).decode(), '<m v="1" k="a" lat="1"/>')


JSON_PACK = HEAD % "j" + """
wire json
when v 1
field uid id string
field lat pos.lat float
field n count int
field t seen iso8601_ms
kind flagged
when meta.on true
requires flag
field flag meta.flag bool
kind shared
when meta.mode =2
requires name
field name meta.who string
field alias meta.who string
kind plain
"""


class TestJsonWire(unittest.TestCase):
    def setUp(self):
        self.e = engine(JSON_PACK)

    def test_types_and_canonical_output(self):
        src = '{ "seen":"2021-02-27T20:00:00Z", "count":1e3, "pos":{"lat":30.0,"x":[1],"y":null,"z":"r"}, "id":"a", "v":1.0, "q":-0.0, "big":1e21, "small":1e-7 }'
        ent = self.e.decode("j", src)
        self.assertEqual(ent.fields, {"uid": "a", "lat": 30.0, "n": 1000, "t": 1614456000000})
        self.assertEqual(ent.kind, ("j", "plain"))
        self.assertEqual(ent.residue["j"], {"pos.z": '"r"', "q": "0", "big": "1" + "0" * 21, "small": "0.0000001"})
        self.assertEqual(
            self.e.encode("j", ent).decode(),
            '{"v":1,"id":"a","pos":{"lat":30,"z":"r"},"count":1000,"seen":"2021-02-27T20:00:00.000Z",'
            '"q":0,"big":1' + "0" * 21 + ',"small":0.0000001}',
        )

    def test_wrong_json_type_is_a_decode_failure(self):
        for bad in ('{"v":1,"id":7}', '{"v":1,"count":"3"}', '{"v":1,"count":1.5}', '{"v":1,"pos":{"lat":"1"}}',
                    '{"v":1,"seen":5}', '{"v":1,"meta":{"on":true,"flag":1}}', '{"v":1,"id":["a"]}', '{"v":1,"id":{}}'):
            with self.assertRaises(TransformDecodeFailure, msg=bad) as cm:
                self.e.decode("j", bad)
            self.assertTrue(str(cm.exception).startswith("transform-decode:"), str(cm.exception))

    def test_malformed(self):
        for bad in ("[]", "{", '{"v":1,"v":1}', '{"v":NaN}', ""):
            with self.assertRaises(MalformedWire, msg=bad):
                self.e.decode("j", bad)

    def test_bool(self):
        ent = self.e.decode("j", '{"v":1,"meta":{"flag":false,"on":true}}')
        self.assertEqual((ent.kind, ent["flag"]), (("j", "flagged"), 0))
        self.assertEqual(self.e.encode("j", ent).decode(), '{"v":1,"meta":{"on":true,"flag":false}}')
        ent.fields["flag"] = 2
        with self.assertRaises(TransformEncodeFailure) as cm:
            self.e.encode("j", ent)
        self.assertTrue(str(cm.exception).startswith("transform-encode:"))

    def test_when_value_types(self):
        # `v` matches the number 1, 1.0 and the string "1"; `=2` matches 2 and "2" and writes "2".
        for v in ("1", "1.0", '"1"', "1e0"):
            self.assertEqual(self.e.decode("j", '{"v":%s}' % v).kind, ("j", "plain"))
        for v in ("2", '"01"', "true", "null", "{}"):
            with self.assertRaises(NoKind, msg=v):
                self.e.decode("j", '{"v":%s}' % v)
        ent = self.e.decode("j", '{"v":1,"meta":{"mode":2,"who":"w"}}')
        self.assertEqual((ent.kind, ent["name"], ent["alias"]), (("j", "shared"), "w", "w"))
        self.assertEqual(self.e.encode("j", ent).decode(), '{"v":1,"meta":{"mode":"2","who":"w"}}')

    def test_shared_locator_earliest_present_line_wins(self):
        # `meta.who` binds `name`, then `alias` (ruling 16).
        ent = Entity(fields={"alias": "a", "name": "n"}, kind=("j", "shared"))
        self.assertEqual(self.e.encode("j", ent).decode(), '{"v":1,"meta":{"mode":"2","who":"n"}}')
        del ent.fields["name"]
        self.assertEqual(self.e.encode("j", ent).decode(), '{"v":1,"meta":{"mode":"2","who":"a"}}')

    def test_dotted_member_dropped_and_string_escapes(self):
        src = '{"v":1,"a.b":"x","o":{"c.d":1,"e":"\\u001f\\u00e9\\"\\\\/"}}'
        ent = self.e.decode("j", src)
        self.assertEqual(ent.residue["j"], {"o.e": '"\\u001f\u00e9\\"\\\\/"'})
        self.assertEqual(self.e.encode("j", ent).decode(), '{"v":1,"o":{"e":"\\u001f\u00e9\\"\\\\/"}}')


class TestBitsV05(unittest.TestCase):
    def test_msb_order_and_past_word(self):
        e = engine(HEAD % "b" + "wire bits\nword_bytes 2\nbit_order msb\nfield n 0:0:16 uint\nfield t 0:20:20 uint\n")
        with self.assertRaises(MalformedWire):  # 40 bits reach into word 2: three whole words, 6 bytes
            e.decode("b", "12340abcde")
        self.assertEqual(e.decode("b", "12340abcde00").fields, {"n": 0x1234, "t": 0xABCDE})
        self.assertEqual(e.encode("b", Entity(fields={"n": 0x1234, "t": 0xABCDE})).decode(), "12340abcde00")

    def test_message_length(self):
        e = engine(HEAD % "b" + "wire bits\nword_bytes 2\nfield n 0:12:8 uint\n")  # 20 bits -> 2 words
        with self.assertRaises(MalformedWire) as cm:
            e.decode("b", "000000")
        self.assertTrue(str(cm.exception).startswith("malformed-wire:"))
        self.assertEqual(e.decode("b", "00f00fffff")["n"], 0xFF)  # longer input: extra bytes ignored
        self.assertEqual(e.encode("b", Entity(fields={"n": 0xFF})).decode(), "00f00f00")

    def test_lsb_is_the_default(self):
        e = engine(HEAD % "b" + "wire bits\nword_bytes 2\nfield n 0:0:16 uint\n")
        self.assertEqual(e.decode("b", "3412")["n"], 0x1234)

    def test_f32_f64_byte_order_follows_bit_order(self):
        for order, hex32, hex64 in (("lsb", "00004841", "000000000000f83f"), ("msb", "41480000", "3ff8000000000000")):
            e = engine(HEAD % "b" + "wire bits\nword_bytes 4\nbit_order %s\nfield lat 0:0:32 f32\nfield lon 1:0:64 f64\n" % order)
            ent = e.decode("b", hex32 + hex64)
            self.assertEqual((ent["lat"], ent["lon"]), (12.5, 1.5))
            self.assertEqual(e.encode("b", ent).decode(), hex32 + hex64)

    def test_ascii(self):
        e = engine(HEAD % "b" + "wire bits\nword_bytes 1\nfield name 0:0:32 ascii\n")
        self.assertEqual(e.decode("b", "41420000")["name"], "AB")
        self.assertEqual(e.decode("b", "00000000").fields, {"name": ""})  # ruling 3
        self.assertEqual(e.encode("b", Entity(fields={"name": ""})).decode(), "00000000")
        self.assertEqual(e.encode("b", Entity(fields={"name": "ABCD"})).decode(), "41424344")
        with self.assertRaises(TransformEncodeFailure):
            e.encode("b", Entity(fields={"name": "ABCDE"}))
        for bad in ("41004200", "417f0000", "411f0000", "41ff0000"):
            with self.assertRaises(TransformDecodeFailure, msg=bad):
                e.decode("b", bad)
        # Not byte-aligned, lsb: each byte is eight bits from its offset, low bit first.
        e = engine(HEAD % "b" + "wire bits\nword_bytes 1\nfield name 0:4:16 ascii\n")
        self.assertEqual(e.decode("b", "102404")["name"], "AB")
        self.assertEqual(e.encode("b", Entity(fields={"name": "AB"})).decode(), "102404")

    def test_scale(self):
        u = build_bits_transform("uscale:0.5:-1000", 16)
        self.assertEqual(u.decode(2500), 250.0)
        self.assertEqual(u.encode(250.0), 2500)
        s = build_bits_transform("sscale:1/10000000", 32)
        self.assertEqual(s.decode(0xFFFFFFFF), -1 / 10000000)
        self.assertEqual(s.decode(300090027), 30.0090027)  # the division, not the product
        self.assertEqual(s.encode(30.0090027), 300090027)
        self.assertEqual(s.encode(-0.00000015), (-2) & 0xFFFFFFFF)  # half away from zero
        for t, bad in ((u, -1000.3), (u, 31768.0), (build_bits_transform("sscale:1", 8), 128), (s, float("nan"))):
            with self.assertRaises(ValueError):
                t.encode(bad)
        self.assertEqual(build_bits_transform("sscale:1", 8).encode(-128), 0x80)
        self.assertEqual(build_bits_transform("uscale:1", 8).encode(255.4), 255)

    def test_round_and_float_text(self):
        self.assertEqual(round_half_away(0.49999999999999994), 0)
        self.assertEqual(format_float(1e-7), "0.0000001")
        self.assertEqual(format_float(1.5e-10), "0.00000000015")

    def test_uint_64_top_bit(self):
        t = build_bits_transform("uint", 64)
        self.assertEqual(t.decode(0xFFFFFFFFFFFFFFFE), -2)  # ruling 2
        self.assertEqual(t.encode(-2), 0xFFFFFFFFFFFFFFFE)
        self.assertEqual(build_bits_transform("uint", 63).decode((1 << 63) - 1), (1 << 63) - 1)

    def test_overlap_and_when_written_last(self):
        e = engine(
            HEAD % "b" + "wire bits\nword_bytes 2\nbit_order msb\nkind a\nwhen 0:12:4 5\n"
            "field n 0:0:8 uint\nfield t 0:4:12 uint\n"
        )
        # `n` is the earlier line: it keeps bits 0-7; `t` fills 8-11; the `when` overwrites 12-15.
        self.assertEqual(e.encode("b", Entity(fields={"n": 0xAB, "t": 0xFFF})).decode(), "abf5")
        ent = e.decode("b", "abf5")
        self.assertEqual((ent["n"], ent["t"], ent.kind), (0xAB, 0xBF5, ("b", "a")))

    def test_when_beyond_input_does_not_hold(self):
        e = engine(HEAD % "b" + "wire bits\nword_bytes 1\nkind long\nwhen 0:8:8 1\nkind short\nwhen 0:0:8 7\n")
        self.assertEqual(e.decode("b", "07").kind, ("b", "short"))
        with self.assertRaises(NoKind):
            e.decode("b", "")


class TestProtobufV05(unittest.TestCase):
    PACK = HEAD % "p" + """
wire protobuf
field uid 1 pstring
kind arm
when 5 present
requires lat
field lat 5.1 pdouble
kind coded
when 3 7
requires n
field n 3 pvarint
field t 2 pvarint
kind empty
when 6.2 present
"""

    def setUp(self):
        self.e = engine(self.PACK)

    def test_present_writes_empty_field(self):
        # ruling 14: nothing mapped under 6.2 is written, so an empty field marks the kind.
        ent = Entity(fields={"uid": "a"})
        out = self.e.encode("p", ent).decode()
        self.assertEqual(out, "0a0161" "3202" "1200")
        self.assertEqual(self.e.decode("p", out).kind, ("p", "empty"))

    def test_integer_when_overrides_field_and_selects(self):
        out = self.e.encode("p", Entity(fields={"n": 9, "t": -1})).decode()
        self.assertEqual(out, "10ffffffffffffffffff01" "1807")  # ten-byte varint; `when` written over `n`
        ent = self.e.decode("p", out)
        self.assertEqual((ent.kind, ent["n"], ent["t"]), (("p", "coded"), 7, -1))

    def test_when_through_a_non_message_does_not_hold(self):
        with self.assertRaises(NoKind):
            self.e.decode("p", "0a0161" "3001")  # field 6 is a varint, not a submessage


if __name__ == "__main__":
    unittest.main()
