"""Version 0.30: a sequential discriminator that is also a key
(spec/engine-spec.md). The conformance vectors pin the behaviour; these tests
pin what they state but cannot reach through `convert` (rulings 25 and 31)."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import BadDirective, Engine, Entity, Item, TransformEncodeFailure  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = "module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nlist rows\n"
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"


def engine(body):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(HEAD + body)
    return eng


def entity(fields, kind=None):
    ent = Entity()
    ent.fields.update(fields)
    ent.kind = kind
    return ent


class TestRecordedKind(unittest.TestCase):
    """Ruling 25: a kind recorded on the entity is not checked against the
    implicit term; a held value it does not match is `transform-encode`."""

    BODY = "kind p\nwhen 8 1..3 as m.a\nfield m.b 8 uint\nkind q\nwhen 8 9 as m.a\n"

    def test_recorded_kind_writes_the_held_value(self):
        eng = engine(self.BODY)
        self.assertEqual(eng.encode("x", entity({"m.a": 2, "m.b": 5}, ("x", "p"))), b"0205")

    def test_recorded_kind_with_no_key_writes_the_first_value(self):
        eng = engine(self.BODY)
        self.assertEqual(eng.encode("x", entity({}, ("x", "q"))), b"09")

    def test_recorded_kind_with_a_value_it_does_not_match(self):
        eng = engine(self.BODY)
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity({"m.a": 9, "m.b": 5}, ("x", "p")))

    def test_recorded_item_kind_with_a_value_it_does_not_match(self):
        eng = engine("group m.rows count 8\n  kind p\n  when 4 1 as m.a\n  kind q\n  when 4 2 as m.a\nend\n")
        it = Item()
        it.fields["m.a"] = 2
        it.kind = ("x", "p")
        ent = entity({})
        ent.lists["m.rows"] = [it]
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", ent)


class TestWide(unittest.TestCase):
    def test_64_bit_label_round_trips_as_negative(self):
        eng = engine("kind k\nwhen 64 0..18446744073709551615 as m.a\n")
        ent = eng.decode("x", b"ffffffffffffffff")
        self.assertEqual(ent.fields["m.a"], -1)
        self.assertEqual(eng.encode("x", ent), b"ffffffffffffffff")


class TestSyntax(unittest.TestCase):
    def test_as_as_is_as_twice(self):  # ruling 31
        with self.assertRaises(BadDirective):
            engine("kind k\nwhen 8 1 as as\n")


if __name__ == "__main__":
    unittest.main()
