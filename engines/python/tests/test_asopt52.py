"""Version 0.52: a discriminator key the entity need not hold
(spec/engine-spec.md). The conformance vectors pin the behaviour; these tests
pin what they do not reach: a recorded kind (ruling 20), a `switch` on an
`optional` key in an item kind (ruling 21), ruling 4 on a pack that is not
sequential, and the read-back of bytes and sentinels under a window."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError, Item, TransformEncodeFailure  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = ("module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey c int -\nkey s string -\n"
         "list rows\n")


def engine(body, head="wire bits\nlayout sequential\nbit_order msb\n"):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load("format x\nversion 1\ndistribution public\nsource s\nuses m\n" + head + body)
    return eng


def entity(**fields):
    ent = Entity()
    ent.fields.update(("m." + k, v) for k, v in fields.items())
    return ent


class TestRecorded(unittest.TestCase):
    def test_recorded_kind_with_a_value_it_does_not_match(self):  # ruling 20
        eng = engine("kind p\nwhen 8 1 as m.a optional\nkind q\nwhen 8 2 as m.a optional\n")
        ent = entity(a=2)
        self.assertEqual(eng.encode("x", ent), b"02")
        ent.kind = ("x", "p")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", ent)
        ent.fields.clear()
        self.assertEqual(eng.encode("x", ent), b"01")


class TestItems(unittest.TestCase):
    def test_switch_on_an_optional_key_of_an_item_kind(self):  # ruling 21
        for at, body in (("", ""), ("at 0 ", "  pad 8\n")):
            eng = engine("group m.rows count 8\n  kind p\n  when 8 1,2 %sas m.a optional\n%s  switch m.a\n"
                         "    case 1\n      field m.b 8 uint\n    case 2\n      field m.c 8 uint\n  end\nend\n"
                         % (at, body))
            rows = []
            for keys in ({}, {"m.a": 2}):
                it = Item()
                it.fields.update(keys, **{"m.b": 7, "m.c": 9})
                rows.append(it)
            ent = entity()
            ent.lists["m.rows"] = rows
            self.assertEqual(eng.encode("x", ent), b"0201070209")


class TestForm(unittest.TestCase):
    def test_as_at_on_a_pack_that_is_not_sequential(self):  # ruling 4: the line does not hold `at`
        head = "wire bits\nword_bytes 1\nfield m.b 0:0:8 uint\nkind k\n"
        for line, code in (("when 0:0:8 1 as at", "bad-directive"), ("when 0:0:8 1 as at at 0", "missing-distribution")):
            eng = Engine()
            eng.load_model(CORE)
            eng.load_model(MODEL)
            with self.assertRaises(GTError) as e:
                eng.load("format x\nversion 1\nsource s\nuses m\n" + head + line + "\n")
            self.assertEqual(e.exception.code, code)


class TestReadBack(unittest.TestCase):
    def test_bytes_field_under_a_window(self):
        eng = engine("kind k\nwhen 8 65 at 0\nfield m.s 8 ascii\nswitch m.s\n  case A\n    field m.b 8 uint\n  else\nend\n")
        self.assertEqual(eng.encode("x", entity(b=7)), b"4107")

    def test_a_window_that_writes_a_sentinel(self):
        eng = engine("kind k\nwhen 8 255 at 0\nfield m.a 8 uint absent 255\nswitch m.a\n  case 0\n    field m.b 8 uint\n"
                     "  else\n    field m.c 8 uint\nend\n")
        out = eng.encode("x", entity(b=7, c=9))
        self.assertEqual(out, b"ff09")
        self.assertEqual(eng.decode("x", out).fields, {"m.c": 9})

    def test_a_window_over_a_plain_line_of_a_key_not_held(self):  # ruling 16
        eng = engine("kind k\nwhen 8 1,2 as m.a optional\nwhen 8 2 at 0\nswitch m.a\n  case 1\n    field m.b 8 uint\n"
                     "  case 2\n    field m.c 8 uint\nend\n")
        self.assertEqual(eng.encode("x", entity(b=7, c=9)), b"0209")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity(a=1, b=7))


if __name__ == "__main__":
    unittest.main()
