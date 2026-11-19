"""Version 0.9, absent-value sentinels: the rulings stated and not yet pinned
by a vector (17 to 22), and points the conformance packs do not reach. The
conformance vectors pin the rest."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "src")))

from goat_transformers import BadDirective, Engine, Entity, GTError  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\n"
MODEL = "module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey f float -\nkey s string -\n"


def engine(wire, body):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    head = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire %s\n" % wire
    if wire == "xml":
        head += "root msg\n"
    eng.load(head + body)
    return eng


class TestLoad(unittest.TestCase):
    def assertBad(self, wire, body):
        with self.assertRaises(BadDirective, msg=body):
            engine(wire, body)

    def test_forced_booleans_on_bool_are_strings(self):  # ruling 17
        self.assertBad("json", "field m.a on bool absent =true\n")
        self.assertBad("json", "field m.a on bool absent =false\n")
        engine("json", "field m.a on bool absent true,false\n")

    def test_forced_null_is_a_string(self):  # rulings 17 and 26
        engine("json", "field m.s v string absent =null\n")
        self.assertBad("json", "field m.a on bool absent =null\n")
        self.assertBad("geojson", "field m.f geometry.lat float absent =1\n")  # ruling 25
        self.assertBad("geojson", "field m.f geometry.lat float absent \"\"\n")
        self.assertBad("json", "field m.s v string absent null\n")
        self.assertBad("geojson", "field m.s properties.v string absent null\n")

    def test_number_text_out_of_range(self):  # ruling 18
        self.assertBad("json", "field m.f v float absent 1e400\n")
        self.assertBad("geojson", "field m.f geometry.alt float absent -1e400\n")
        engine("json", "field m.f v float absent =1e400\n")  # a string

    def test_comma_inside_quotes(self):  # ruling 11
        self.assertBad("xml", 'field m.s @v string absent "",0\n')
        self.assertBad("xml", "field m.s @v string absent 1,\n")

    def test_equals_sign_on_bits_and_integer_protobuf(self):  # ruling 12
        self.assertBad("bits", "word_bytes 1\nfield m.a 0:0:8 uint absent =1\n")
        self.assertBad("protobuf", "field m.a 1 pvarint absent =1\n")
        self.assertBad("protobuf", "field m.f 1 pdouble absent 18446744073709551616\n")
        engine("protobuf", "field m.f 1 pdouble absent 18446744073709551615\n")


class TestDecodeEncode(unittest.TestCase):
    def test_json_integers_through_a_double(self):  # ruling 19
        eng = engine("json", "field m.f v float absent 9007199254740993\n")
        # 2^53 + 1 is not a double: held as 9007199254740992, and so is the wire number
        self.assertNotIn("m.f", eng.decode("x", '{"v":9007199254740992}').fields)
        self.assertNotIn("m.f", eng.decode("x", '{"v":9007199254740993}').fields)
        self.assertEqual(eng.encode("x", Entity()), b'{"v":9007199254740992}')

    def test_same_place_on_text_wires(self):  # ruling 20
        eng = engine("xml", "field m.s @v string absent -\nfield uid @v string\n")
        self.assertEqual(eng.encode("x", Entity(fields={"uid": "u"})), b'<msg v="u"/>')
        self.assertEqual(eng.encode("x", Entity()), b'<msg v="-"/>')

    def test_sentinel_and_default_on_one_key(self):  # ruling 22
        eng = engine("json", "field m.a q int absent 5\ndefault m.a 7\n")
        self.assertEqual(eng.convert("x", "x", '{"q":5}'), b'{"q":7}')

    def test_xml_text_not_trimmed(self):  # ruling 14; rulings 1n and 2a of 0.11: `int` refuses " 0 "
        eng = engine("xml", "field m.a e/#text int absent 0\n")
        with self.assertRaises(GTError) as cm:
            eng.decode("x", "<msg><e> 0 </e></msg>")
        self.assertEqual(cm.exception.code, "transform-decode")
        self.assertEqual(eng.decode("x", "<msg><e>0</e></msg>").fields, {})

    def test_sequential_also_shares_the_sentinel(self):
        eng = Engine()
        eng.load_model(CORE)
        eng.load_model(MODEL)
        eng.load("format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\n"
                 "bit_order msb\nfield m.a 8 uint absent 255\nalso m.b\n")
        self.assertEqual(eng.decode("x", "ff").fields, {})
        self.assertEqual(eng.decode("x", "07").fields, {"m.a": 7, "m.b": 7})
        self.assertEqual(eng.encode("x", Entity()), b"ff")

    def test_protobuf_double_and_string_sentinels_written(self):
        eng = engine("protobuf", "field m.f 1 pdouble absent 1\nfield m.s 2 pstring absent =x\n")
        self.assertEqual(eng.encode("x", Entity()), b"0901000000000000001202" + "=x".encode().hex().encode())


if __name__ == "__main__":
    unittest.main()
