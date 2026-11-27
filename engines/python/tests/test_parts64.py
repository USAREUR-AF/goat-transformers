"""Version 0.64: one text token split into coded fields (spec/engine-spec.md).
The conformance vectors pin the behaviour; these tests pin what ruling 27 says
they do not reach, and ruling 26 on a sequential pack with a `default`-free key."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import (  # noqa: E402
    BadDirective, Engine, Entity, GTError, Item, TransformDecodeFailure, TransformEncodeFailure,
)

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey type string -\nkey time_ms int ms\n"
MODEL = ("module m\nversion 1\ndistribution public\nsource s\nkey a string -\nkey b string -\nkey w string -\n"
         "key n int -\nkey k int -\nlist rows\n")
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\n"


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


class TestParts(unittest.TestCase):
    def test_model_keys_in_line_order(self):  # ruling 14
        eng = engine("wire json\nfield m.b t part:-:1\nfield m.w t string\nconst t part:-:2 z\nfield m.a t part:-:0\n")
        self.assertEqual(eng.model_keys("x"), ["m.b", "m.w", "m.a"])

    def test_a_second_part_line_is_another_line(self):  # ruling 18
        eng = engine("wire json\nfield m.a t part:-:0\nfield m.a t part:-:1\nfield m.w t string\n")
        self.assertEqual(eng.encode("x", entity(w="p-q", a="other")), b'{"t":"p-q"}')
        self.assertEqual(eng.encode("x", entity(a="p")), b'{"t":"p-p"}')

    def test_const_dot_in_a_scalar_item(self):  # ruling 17
        with self.assertRaises(GTError) as e:
            engine("wire json\ngroup m.rows r\n  field m.a . part:-:0\n  const . part:-:1 z\nend\n")
        self.assertEqual(e.exception.code, "bad-directive")

    def test_scalar_items(self):  # ruling 13
        for wire, loc, out in (("json", "r", b'{"r":["p",null]}'), ("xml\nroot e", "r", b"<e><r>p</r><r/></e>")):
            at = "." if wire == "json" else '"#text"'
            eng = engine("wire %s\ngroup m.rows %s\n  field m.a %s part:-:0\nend\n" % (wire, loc, at))
            one = Item()
            one.fields["m.a"] = "p"
            ent = entity()
            ent.lists["m.rows"] = [one, Item()]
            self.assertEqual(eng.encode("x", ent), out)

    def test_a_type_code_of_a_part_is_not_residue(self):  # ruling 14
        eng = engine("wire json\ntypemap A a-f\nfield type t part:-:0\nfield m.a t part:-:1\n")
        ent = eng.decode("x", b'{"t":"Q-z"}')
        self.assertEqual((ent.fields["type"], ent.residue), ("Q", {}))
        self.assertEqual(eng.encode("x", eng.decode("x", b'{"t":"A-z"}')), b'{"t":"A-z"}')

    def test_geojson_number_reads_as_its_text(self):  # ruling 16
        eng = engine("wire geojson\nfield m.a properties.t part:.:0\nfield m.b properties.t part:.:1\n")
        ent = eng.decode("x", b'{"type":"Feature","geometry":null,"properties":{"t":12.5}}')
        self.assertEqual((ent.fields["m.a"], ent.fields["m.b"]), ("12", "5"))

    def test_options_of_other_layouts(self):
        for body in ("wire bits\nlayout sequential\nfield m.n 8 uint unlisted\n",
                     "wire bits\nlayout sequential\nconst 8 part:-:0 c\n",
                     "wire bits\nword_bytes 1\nconst 0:0:8 part:-:0 c\n", "wire cbor\nconst a part:-:0 c\n",
                     "wire protobuf\nconst 1 part:-:0 c\n", "wire tlv\nconst 5 part:-:0 c\n"):
            with self.assertRaises(BadDirective):
                engine(body)
            with self.assertRaises(GTError) as e:
                engine(body + "bogus\n")
            self.assertEqual(e.exception.code, "unknown-directive")

    def test_whole_default_is_checked(self):
        eng = engine("wire json\ndefault m.w p-y\nfield m.w t string\nfield m.a t part:-:0\nconst t part:-:1 z\n")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity())
        self.assertEqual(eng.encode("x", entity(a="p")), b'{"t":"p-z"}')


class TestTwoLines(unittest.TestCase):
    """Ruling 26."""

    def test_either_order_on_a_sequential_pack(self):
        lines = ["field m.n 8 uint\n", "field m.n 16 ascii via t\n"]
        for body, data in ((lines, b"074141"), (lines[::-1], b"414107")):
            eng = engine("wire bits\nlayout sequential\nmap t OK 7\n" + "".join(body))
            with self.assertRaises(TransformDecodeFailure):
                eng.decode("x", data)
            self.assertEqual(eng.decode("x", data.replace(b"4141", b"4f4b")).fields["m.n"], 7)

    def test_what_the_wire_states_of_a_later_line(self):  # ruling 27
        for body in ("field m.a 1 pstring\nfield m.a 2.1 pstring\n", "field m.a 2.1 pstring\nfield m.a 1 pstring\n"):
            eng = engine("wire protobuf\n" + body)
            with self.assertRaises(GTError) as e:
                eng.decode("x", b"0a01611202ffff")
            self.assertEqual(e.exception.code, "malformed-wire")

    def test_an_entry_that_does_not_read(self):  # ruling 30
        for u in ("", " unlisted"):
            eng = engine("wire json\nmap t a 1\nmap t b 99999999999999999999\nfield m.n t part:-:0 via t%s\n"
                         "field m.w t string\n" % u)
            with self.assertRaises(TransformDecodeFailure):
                eng.decode("x", b'{"t":"b"}')
            with self.assertRaises(TransformEncodeFailure):
                eng.encode("x", entity(w="b"))

    def test_a_line_of_a_switch_key_after_its_switch(self):  # ruling 31
        eng = engine("wire bits\nlayout sequential\nbit_order msb\nmap t OK 7\nfield m.n 8 uint\nswitch m.n\n"
                     "  case 0\n    field m.a 8 ascii\n  else\nend\nfield m.n 16 ascii via t\n")
        self.assertEqual(eng.encode("x", entity(n=7)), b"074f4b")
        with self.assertRaises(TransformEncodeFailure):  # the absent key: 0, then an empty text with no entry
            eng.encode("x", entity(a="z"))

    def test_the_error_stands_at_the_line_after_the_switch(self):  # ruling 31, and ruling 12 of 0.20
        eng = engine("wire bits\nlayout sequential\nbit_order msb\nmap t OK 7\nfield m.n 8 uint\nswitch m.n\n"
                     "  case 0\n    field m.a 8 ascii\n  else\nend\nfield m.n 16 ascii via t\nfield m.k 4 uint\n")
        self.assertEqual(eng.encode("x", entity(n=7, k=3)), b"074f4b30")
        with self.assertRaises(TransformEncodeFailure) as e:  # the later line's own error comes second
            eng.encode("x", entity(a="z", k=99))
        self.assertIn("switch key m.n", str(e.exception))
        self.assertEqual(e.exception.locator, "16")
        with self.assertRaises(TransformEncodeFailure) as e:  # alone, the later line fails on its own
            eng.encode("x", entity(n=7, k=99))
        self.assertNotIn("switch key", str(e.exception))


if __name__ == "__main__":
    unittest.main()
