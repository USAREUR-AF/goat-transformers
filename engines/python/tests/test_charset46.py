"""Version 0.46: character codes (spec/engine-spec.md). The conformance vectors
pin the behaviour; these tests pin what they do not reach: ruling 21, a JSON
number on `geojson`, a set declared after its field, and the place of
`charset` beside the kinds of a group."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import BadDirective, Engine, Entity, TransformDecodeFailure, TransformEncodeFailure  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = "module m\nversion 1\ndistribution public\nsource s\nkey s string -\nkey n int -\nkey b int -\nlist rows\n"
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\n"
SETS = "charset L ABCDEFGHIJKLMNOPQRSTUVWXYZ234567\ncharset D 0123456789\n"


def engine(body):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(HEAD + body)
    return eng


def entity(**fields):
    ent = Entity()
    ent.fields.update(("m." + k, v) for k, v in fields.items())
    return ent


class TestBits(unittest.TestCase):
    def test_msb_lsb_with_a_length_of_no_whole_bytes_reads_as_uint(self):  # ruling 21
        eng = engine("wire bits\nword_bytes 1\nbit_order msb-lsb\n" + SETS
                     + "field m.s 0:0:9 code:L,D\nfield m.n 0:0:9 uint\n")
        for text, n in (("A1", 1), ("B0", 16), ("79", 31 * 16 + 9)):
            ent = eng.decode("x", eng.encode("x", entity(n=n, s=text)))
            self.assertEqual((ent.fields["m.s"], ent.fields["m.n"]), (text, n))

    def test_stop_and_until(self):  # ruling 21
        for line in ("field m.s 9 code:L,D stop 0\n", "field m.s until:0 code:L,D\n"):
            with self.assertRaises(BadDirective):
                engine("wire bits\nlayout sequential\n" + SETS + line)

    def test_a_set_declared_after_its_field(self):
        for head, loc in (("wire bits\nword_bytes 1\n", "0:0:9"), ("wire bits\nlayout sequential\n", "9")):
            eng = engine(head + "field m.s %s code:L,D\n" % loc + SETS)
            self.assertEqual(eng.decode("x", eng.encode("x", entity(s="C7"))).fields["m.s"], "C7")

    def test_charset_after_an_item_kind_and_after_a_message_kind(self):  # ruling 16
        group = "wire bits\nlayout sequential\ngroup m.rows count 8\n  kind a\n  field m.b 8 uint\nend\n"
        engine(group + SETS + "field m.s 9 code:L,D\n")
        with self.assertRaises(BadDirective):
            engine(group + "kind k\nfield m.s 9 code:L,D\n" + SETS)

    def test_width_text(self):
        for w in ("+4", "9", "3", "0", "x", "٤", "9" * 5000):
            with self.assertRaises(BadDirective):
                engine("wire bits\nword_bytes 1\ncharset D 0123456789 %s\nfield m.b 0:0:8 uint\n" % w)

    def test_codenum_range(self):
        eng = engine("wire bits\nword_bytes 1\n" + SETS + "field m.n 0:0:8 codenum:D,D\n")
        self.assertEqual(eng.encode("x", entity(n=99)), b"99")
        for n in (-1, 100, -(1 << 63), (1 << 63) - 1):
            with self.assertRaises(TransformEncodeFailure):
                eng.encode("x", entity(n=n))


class TestText(unittest.TestCase):
    def test_geojson_takes_a_string_only(self):  # ruling 11
        eng = engine("wire geojson\n" + SETS + "field m.s properties.a codestr:D,D\nfield m.n properties.b codenum:D,D\n")
        doc = b'{"type":"Feature","geometry":null,"properties":{"a":"07","b":"07"}}'
        ent = eng.decode("x", doc)
        self.assertEqual((ent.fields["m.s"], ent.fields["m.n"]), ("07", 7))
        self.assertIn(b'"b":"07"', eng.encode("x", entity(n=7)))
        with self.assertRaises(TransformDecodeFailure):
            eng.decode("x", doc.replace(b'"a":"07"', b'"a":17'))
        with self.assertRaises(TransformDecodeFailure):
            eng.decode("x", doc.replace(b'"b":"07"', b'"b":17'))

    def test_geojson_coordinates(self):  # ruling 23
        for slot in ("lon", "lat", "alt"):
            for t in ("m.s geometry.%s codestr:D", "m.n geometry.%s codenum:D"):
                with self.assertRaises(BadDirective):
                    engine("wire geojson\n" + SETS + "field " + t % slot + "\n")
                engine("wire geojson\n" + SETS + "group m.rows properties.r\n  field " + t % slot + "\nend\n")

    def test_absent_number_text(self):  # ruling 22
        for text, out in (("5", b'{"a":5}'), ("=5", b'{"a":"5"}')):
            eng = engine("wire json\n" + SETS + "field m.s a codestr:D absent %s\n" % text)
            for member in (b"5", b'"5"'):
                self.assertNotIn("m.s", eng.decode("x", b'{"a":' + member + b"}").fields)
            self.assertEqual(eng.encode("x", entity()), out)
            self.assertEqual(eng.encode("x", entity(s="5")), b'{"a":"5"}')


if __name__ == "__main__":
    unittest.main()
