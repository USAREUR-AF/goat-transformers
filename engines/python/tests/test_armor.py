"""Version 0.14: six-bit armor (spec/engine-spec.md). The conformance vectors
pin the behaviour; these tests pin the rulings no vector states."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = (
    "module m\nversion 1\ndistribution public\nsource s\n"
    "key a int -\nkey b int -\nkey s string -\nlist rows\n"
)
FIXED = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nword_bytes 4\nbit_order msb\n"
SEQ = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"


def engine(text):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(text)
    return eng


def encode(eng, fields):
    ent = Entity()
    ent.fields.update(fields)
    got = eng.encode("x", ent)
    return got.decode("utf-8") if isinstance(got, bytes) else got


class TestLoad(unittest.TestCase):
    def refused(self, text, code="bad-directive"):
        with self.assertRaises(GTError) as cm:
            engine(text)
        self.assertEqual(cm.exception.code, code)

    def test_armor_inside_a_block(self):
        """Ruling 5: `armor` is a header directive, refused inside any block."""
        self.refused(FIXED + "group m.rows 0:0 item 6 count 2\narmor sixbit\nfield m.a 0:0:6 uint\nend\n")
        self.refused(SEQ + "opt\narmor sixbit\nfield m.a 6 uint\nend\n")
        self.refused(SEQ + "group m.rows count 2\narmor sixbit\nfield m.a 6 uint\nend\n")

    def test_armor_after_a_kind_in_the_sequential_layout(self):
        self.refused(SEQ + "kind k\nwhen 6 1\narmor sixbit\nfield m.a 6 uint\n")

    def test_armor_sixbit_needs_msb_wherever_it_stands(self):
        engine(FIXED.replace("bit_order msb\n", "") + "armor sixbit\nfield m.a 0:0:6 uint\nbit_order msb\n")
        self.refused(SEQ.replace("bit_order msb", "bit_order lsb") + "armor sixbit\nfield m.a 6 uint\n")
        self.refused(SEQ.replace("bit_order msb\n", "") + "armor sixbit\nfield m.a 6 uint\n")

    def test_armor_before_missing_distribution(self):
        self.refused(FIXED.replace("distribution public\n", "") + "armor base64\nfield m.a 0:0:6 uint\n")
        self.refused(FIXED.replace("distribution public\n", "") + "field m.a 0:0:6 uint\n", "missing-distribution")

    def test_length_whole_only_under_sixbit(self):
        engine(SEQ + "armor hex\nfield m.a 6 uint\nlength 10 whole\n")
        self.refused(SEQ + "field m.a 6 uint\nlength 10 whole\narmor sixbit\n")

    def test_sixbit_lengths_and_options(self):
        for n in (6, 12, 1530):
            engine(FIXED + "field m.s 0:0:%d sixbit trim\n" % n)
            engine(SEQ + "field m.s %d sixbit trim\n" % n)
        for n in (5, 7, 8, 1536):
            self.refused(FIXED + "field m.s 0:0:%d sixbit\n" % n)
            self.refused(SEQ + "field m.s %d sixbit\n" % n)
        self.refused(SEQ + "field m.s 24 sixbit swap\n")
        self.refused(FIXED + "field m.a 0:0:6 uint trim\n")
        self.refused(SEQ + "field m.a 6 uint trim\n")

    def test_sixbit_on_another_wire(self):
        head = "format x\nversion 1\ndistribution public\nsource s\nuses m\n"
        self.refused(head + "wire json\nfield m.s s sixbit\n")
        self.refused(head + "wire xml\nroot r\nfield m.s @s sixbit\n")


class TestEncodeLength(unittest.TestCase):
    def test_optional_field_with_a_default_counts(self):
        """Ruling 7: encode writes the default, so the field counts toward L."""
        body = "armor sixbit\nfield m.a 0:0:6 uint\nfield m.b 0:6:6 uint optional\n"
        self.assertEqual(encode(engine(FIXED + body), {"m.a": 1}), "1")
        self.assertEqual(encode(engine(FIXED + body + "default m.b 3\n"), {"m.a": 1}), "13")
        self.assertEqual(encode(engine(FIXED + body), {"m.a": 1, "m.b": 40}), "1`")

    def test_nothing_to_write(self):
        """Ruling 9: a scope that writes no bit gives the empty text."""
        eng = engine(FIXED + "armor sixbit\nfield m.a 0:0:6 uint optional\n")
        self.assertEqual(encode(eng, {}), "")
        self.assertEqual(eng.decode("x", "").fields, {})

    def test_whole_words_are_not_required(self):
        eng = engine(FIXED + "armor sixbit\nfield m.a 0:0:6 uint\n")  # word_bytes 4: one character is enough
        self.assertEqual(eng.decode("x", "5").fields["m.a"], 5)
        self.assertEqual(encode(eng, {"m.a": 5}), "5")

    def test_length_bytes_block_is_padded(self):
        """Ruling 8: a `length ... bytes` block is still a whole number of bytes."""
        eng = engine(SEQ + "armor sixbit\nlength 6 bytes\n  field m.a 4 uint\nend\n")
        self.assertEqual(encode(eng, {"m.a": 5}), "1D0")
        self.assertEqual(eng.decode("x", "1D0").fields["m.a"], 5)

    def test_sixbit_text_out_of_range(self):
        eng = engine(FIXED + "armor sixbit\nfield m.s 0:0:12 sixbit\n")
        for bad in ("a", "~", "\x1f", "ABC"):
            with self.assertRaises(GTError) as cm:
                encode(eng, {"m.s": bad})
            self.assertEqual(cm.exception.code, "transform-encode")
        self.assertEqual(encode(eng, {"m.s": "_ "}), "OP")
        self.assertEqual(eng.decode("x", "OP").fields["m.s"], "_ ")


class TestAbsent(unittest.TestCase):
    """Ruling 12 of 0.14: `absent` (0.9) on armored packs, `sixbit` included.
    "AB" is the six-bit values 1, 2: the integer 66 with `msb`."""

    LINES = "armor sixbit\nfield m.s 0:0:12 sixbit absent 66\nfield m.b 0:12:6 uint\n"
    SEQ_LINES = "armor sixbit\nfield m.s 12 sixbit absent 66\nfield m.b 6 uint\n"

    def check(self, eng):
        got = eng.decode("x", "123")
        self.assertNotIn("m.s", got.fields)
        self.assertEqual(got.fields["m.b"], 3)
        self.assertEqual(encode(eng, {"m.b": 3}), "123")
        self.assertEqual(encode(eng, {"m.s": "C", "m.b": 3}), "303")
        self.assertEqual(eng.decode("x", "303").fields["m.s"], "C")

    def test_fixed(self):
        self.check(engine(FIXED + self.LINES))

    def test_sequential(self):
        self.check(engine(SEQ + self.SEQ_LINES))

    def test_optional_sentinel_counts_toward_L(self):
        eng = engine(FIXED + "armor sixbit\nfield m.a 0:0:6 uint\nfield m.b 0:6:6 uint optional absent 9\n")
        self.assertEqual(encode(eng, {"m.a": 1}), "19")
        self.assertNotIn("m.b", eng.decode("x", "19").fields)
        self.assertNotIn("m.b", eng.decode("x", "1").fields)

    def test_lsb_sixbit_sentinel(self):
        # with `lsb` the first character is the low six bits: "AB" is 1 + 2 * 64
        text = FIXED.replace("word_bytes 4", "word_bytes 2").replace("bit_order msb", "bit_order lsb")
        eng = engine(text + "field m.s 0:0:12 sixbit absent 129\nfield m.b 0:12:4 uint\n")
        wire = encode(eng, {"m.s": "AB", "m.b": 1})
        self.assertNotIn("m.s", eng.decode("x", wire).fields)
        self.assertEqual(encode(eng, {"m.b": 1}), wire)


if __name__ == "__main__":
    unittest.main()
