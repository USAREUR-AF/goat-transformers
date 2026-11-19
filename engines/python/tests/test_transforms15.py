"""Version 0.15, value transforms: points the conformance packs do not reach
(very long digit strings, the exact-decimal writer, `chars` in `lsb` order
round trips, an `ais6` mix of padding and spaces). The conformance vectors
pin the rest."""

import os
import sys
import unittest
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "src")))

from goat_transformers import BadDirective, Engine, Entity  # noqa: E402
from goat_transformers.errors import TransformDecodeFailure, TransformEncodeFailure  # noqa: E402
from goat_transformers.transforms import exact_decimal_text, parse_exact_factor, round_exact  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\n"
MODEL = "module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey f float -\nkey s string -\n"


def engine(wire, body, extra=""):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    head = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire %s\n%s" % (wire, extra)
    if wire == "xml":
        head += "root msg\n"
    eng.load(head + body)
    return eng


class TestArithmetic(unittest.TestCase):
    def test_round_half_away(self):  # ruling 4
        self.assertEqual(round_exact(Fraction(5, 2)), 3)
        self.assertEqual(round_exact(Fraction(-5, 2)), -3)
        self.assertEqual(round_exact(Fraction(-7, 3)), -2)
        self.assertEqual(round_exact(Fraction(0)), 0)

    def test_exact_decimal_text(self):  # ruling 21
        self.assertEqual(exact_decimal_text(Fraction(-1, 8)), "-0.125")
        self.assertEqual(exact_decimal_text(Fraction(1, 2 ** 18)), "0.000003814697265625")
        with self.assertRaises(ValueError):
            exact_decimal_text(Fraction(1, 2 ** 19))
        with self.assertRaises(ValueError):
            exact_decimal_text(Fraction(2, 3))
        self.assertEqual(exact_decimal_text(Fraction(12)), "12")

    def test_factor_with_more_digits_than_the_int_conversion_limit(self):  # ruling 9
        self.assertEqual(parse_exact_factor("1" + "0" * 5000 + "/" + "1" + "0" * 5000), 1)
        self.assertEqual(parse_exact_factor("2." + "0" * 5000), 2)


class TestLoad(unittest.TestCase):
    def test_float_scale_fraction_is_unsigned_and_sscale_unchanged(self):  # rulings 25 and 26
        with self.assertRaises(BadDirective):
            engine("bits", "field m.f 0:0:32 f32scale:-1/2\n", "word_bytes 1\n")
        engine("bits", "field m.f 0:0:32 f32scale:-0.5\n", "word_bytes 1\n")

    def test_smag_takes_no_parameter(self):
        with self.assertRaises(BadDirective):
            engine("bits", "field m.a 0:0:8 smag:1\n", "word_bytes 1\n")


class TestValues(unittest.TestCase):
    def test_ais6_padding_and_spaces_in_any_mix(self):  # ruling 5
        eng = engine("bits", "field m.s 0:0:36 chars:ais6\n", "word_bytes 1\nbit_order msb\n")
        hexed = eng.encode("x", Entity(fields={"m.s": "AB @ @"})).decode()
        self.assertEqual(eng.decode("x", hexed).fields["m.s"], "AB")

    def test_chars_lsb_round_trip(self):
        eng = engine("bits", "field m.s 0:3:42 chars:ascii7\n", "word_bytes 1\nbit_order lsb\n")
        hexed = eng.encode("x", Entity(fields={"m.s": "Hi ~"})).decode()
        self.assertEqual(eng.decode("x", hexed).fields["m.s"], "Hi ~")

    def test_ascii7_nul_inside_is_a_decode_failure(self):
        eng = engine("bits", "field m.s 0:0:14 chars:ascii7\n", "word_bytes 1\nbit_order msb\n")
        with self.assertRaises(TransformDecodeFailure):
            eng.decode("x", "0104")  # codes 0 then 65

    def test_iscale_long_digits_on_json(self):  # ruling 9
        eng = engine("json", "field m.a a iscale:1\n")
        text = '{"a":0.' + "0" * 5000 + "1}"
        self.assertEqual(eng.decode("x", text).fields["m.a"], 0)

    def test_iscale_geojson_writes_exact_digits(self):  # ruling 7
        eng = engine("geojson", "field m.a properties.a iscale:1/1000\n")
        out = eng.encode("x", Entity(fields={"m.a": 9007199254740993})).decode()
        self.assertIn('"a":9007199254740993000', out)

    def test_smscale_encode_magnitude_out_of_range(self):
        eng = engine("bits", "field m.f 0:0:8 smscale:0.5\n", "word_bytes 1\n")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", Entity(fields={"m.f": 64.0}))


if __name__ == "__main__":
    unittest.main()
