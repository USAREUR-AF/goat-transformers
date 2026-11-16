"""Unit tests for the `bits` wire (spec/engine-spec.md, "Version 0.2: the bits wire"):
bit order, the uint/twos/linscale transforms, hex I/O tolerance, zeroed unmapped
bits and the wire/transform kind rules."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
PACKS = os.path.normpath(os.path.join(HERE, "..", "..", "..", "packs"))

from goat_transformers import (  # noqa: E402
    Engine, InvalidPack, MalformedWire, UnknownTransform, parse_model_text, parse_pack_text,
)
from goat_transformers.transforms import build_bits_transform, round_half_away  # noqa: E402

# The test formats' keys, declared as a `core` module so the packs load.
CORE = """
module core
version 0.1.0
distribution public
source "unit tests"
key a int   -
key b int   -
key c int   -
key s int   -
key x float -
"""

# One byte per word, two unsigned nibbles: `a` the low nibble, `b` the high one.
NIBBLES = """
format  t-nibbles
version 0.2.0
distribution public
source "unit tests"
wire    bits
word_bytes 1
field a 0:0:4 uint
field b 0:4:4 uint
"""

# A field that spans a byte boundary: 8 bits from bit 4 of a two-byte word.
SPAN = """
format  t-span
version 0.2.0
distribution public
source "unit tests"
wire    bits
word_bytes 2
field c 0:4:8 uint
"""

# Signed fields and a scaled field.
SIGNED = """
format  t-signed
version 0.2.0
distribution public
source "unit tests"
wire    bits
word_bytes 3
field s   0:0:8  twos
field x   0:8:16 linscale:32767:1
"""


class TestBitsParse(unittest.TestCase):
    def test_parses(self):
        p = parse_pack_text(NIBBLES)
        self.assertEqual((p.wire, p.word_bytes), ("bits", 1))
        self.assertEqual([f.loc for f in p.fields], [(0, 0, 4), (0, 4, 4)])
        self.assertTrue(all(f.transform.kind == "bits" for f in p.fields))

    def test_word_bytes_required_and_bits_only(self):
        with self.assertRaises(InvalidPack):  # bits pack with no word_bytes
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire bits\nfield a 0:0:8 uint\n")
        with self.assertRaises(InvalidPack):  # word_bytes on a non-bits wire
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire geojson\nword_bytes 4\n")

    def test_wrong_kind_transforms(self):
        with self.assertRaises(InvalidPack):  # text transform on a bits wire
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield a 0:0:8 string\n")
        with self.assertRaises(InvalidPack):  # bits transform on a text wire
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire xml\nroot r\nfield a @a uint\n")
        with self.assertRaises(InvalidPack):  # linscale on a geojson wire
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire geojson\nfield a geometry.lat linscale:1:1\n")

    def test_bad_bits_locator(self):
        for bad in ("0:0", "0:0:0", "0:0:65", "a:0:8", "-1:0:8"):
            with self.assertRaises(InvalidPack, msg=bad):
                parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield a %s uint\n" % bad)

    def test_bad_linscale_name(self):
        with self.assertRaises(UnknownTransform):
            parse_pack_text("format x\nversion 1\ndistribution public\nsource t\nwire bits\nword_bytes 2\nfield a 0:0:8 linscale:0\n")


class TestBitsTransforms(unittest.TestCase):
    def test_uint_bit_order(self):
        e = Engine([parse_pack_text(NIBBLES)], models=[parse_model_text(CORE)])
        ent = e.decode("t-nibbles", "03")  # 0b0000_0011: low nibble 3, high nibble 0
        self.assertEqual((ent["a"], ent["b"]), (3, 0))
        self.assertEqual(e.convert("t-nibbles", "t-nibbles", "03").decode(), "03")
        ent2 = e.decode("t-nibbles", "a5")  # 0xA5 = 1010_0101: low=0x5, high=0xA
        self.assertEqual((ent2["a"], ent2["b"]), (5, 10))

    def test_span_across_byte(self):
        e = Engine([parse_pack_text(SPAN)], models=[parse_model_text(CORE)])
        ent = e.decode("t-span", "a00b")
        self.assertEqual(ent["c"], 0xBA)
        self.assertEqual(e.encode("t-span", ent).decode(), "a00b")

    def test_twos_and_linscale(self):
        e = Engine([parse_pack_text(SIGNED)], models=[parse_model_text(CORE)])
        # s = 0xFF two's-complement over 8 bits = -1; x bits are 0 -> 0.0
        ent = e.decode("t-signed", "ff0000")
        self.assertEqual(ent["s"], -1)
        self.assertAlmostEqual(ent["x"], 0.0, delta=1e-12)
        self.assertEqual(e.encode("t-signed", ent).decode(), "ff0000")
        # x word holds 16384 (little-endian over bits 8..23): 16384/32767 scaled by 1.
        ent2 = e.decode("t-signed", "000040")
        self.assertAlmostEqual(ent2["x"], 16384 / 32767, delta=1e-12)
        self.assertEqual(e.encode("t-signed", ent2).decode(), "000040")

    def test_round_half_away(self):
        self.assertEqual([round_half_away(v) for v in (2.5, -2.5, 0.5, -0.5, 2.4, 2.6)],
                         [3, -3, 1, -1, 2, 3])

    def test_build_bits_transform_direct(self):
        self.assertEqual(build_bits_transform("uint", 4).encode(255), 15)   # masked to 4 bits
        self.assertEqual(build_bits_transform("twos", 8).encode(-1), 0xFF)
        self.assertEqual(build_bits_transform("linscale:100:10", 8).encode(5.0), 50)


class TestBitsIO(unittest.TestCase):
    def setUp(self):
        self.e = Engine([parse_pack_text(NIBBLES)], models=[parse_model_text(CORE)])

    def test_hex_whitespace_ignored(self):
        self.assertEqual(self.e.decode("t-nibbles", " a 5 \n").fields, {"a": 5, "b": 10})

    def test_hex_errors(self):
        for bad in ("abc", "zz", "0"):  # odd length / non-hex
            with self.assertRaises(MalformedWire, msg=bad):
                self.e.decode("t-nibbles", bad)

    def test_message_too_short(self):
        with self.assertRaises(MalformedWire):
            self.e.decode("t-nibbles", "")  # no byte for word 0

    def test_unmapped_bits_zeroed_on_encode(self):
        # Only `a` set in the entity; `b` absent -> its nibble is zero, not carried.
        from goat_transformers import Entity
        self.assertEqual(self.e.encode("t-nibbles", Entity(fields={"a": 7})).decode(), "07")


class TestDemoBitsPack(unittest.TestCase):
    def test_demo_bits_loaded_and_fields(self):
        e = Engine.from_dir(PACKS)
        self.assertIn("demo-bits", e.formats())
        ent = e.decode("demo-bits", "2244a6e03811090000")
        for key in ("lat", "lon", "time_ms"):
            self.assertIn(key, ent.fields)
        # time_ms maps into geojson properties; lat/lon into the geometry.
        out = e.convert("demo-bits", "geojson", "2244a6e03811090000").decode()
        self.assertIn("time_ms", out)


if __name__ == "__main__":
    unittest.main()
