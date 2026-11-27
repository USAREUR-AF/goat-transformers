"""Version 0.56: what the vectors do not pin of `range` and `null`."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from goat_transformers import Engine, Entity, TransformEncodeFailure  # noqa: E402
from goat_transformers.entity import Item  # noqa: E402

CORE = 'module core\nversion 1\ndistribution public\nsource s\nkey uid string - "d"\n'
MODEL = ('module m\nversion 1\ndistribution public\nsource s\nkey a int - "d"\nkey b int - "d"\nkey f float - "d"\n'
         'key s string - "d"\nlist l "d"\n')


def engine(body):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load("format x\nversion 1\ndistribution public\nsource s\nuses m\n" + body)
    return eng


def entity(fields, lists=None):
    ent = Entity()
    ent.fields.update(fields)
    ent.lists.update(lists or {})
    return ent


class TestRange(unittest.TestCase):
    def test_a_line_under_a_const_is_checked_on_tlv(self):
        eng = engine("wire tlv\nfield m.a 1:1 uint range 0 10\nconst 1:1 7\n")
        self.assertEqual(eng.encode("x", entity({"m.a": 5})), eng.encode("x", entity({})))
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity({"m.a": 11}))

    def test_not_a_number_and_steps_that_are_not_finite(self):
        for opts in ("range 0 10", "range 0 10 wrap", "range -1.5e308 1.5e308 wrap"):
            eng = engine("wire json\nfield m.f v float %s\n" % opts)
            for v in (float("nan"), float("inf"), 1.7e308):
                if v == 1.7e308 and opts == "range 0 10 wrap":
                    continue
                with self.assertRaises(TransformEncodeFailure):
                    eng.encode("x", entity({"m.f": v}))

    def test_sequential_line_reached_and_not_reached(self):
        eng = engine("wire bits\nlayout sequential\nbit_order msb\nfield m.b 8 uint\nswitch m.b\n"
                     "  case 1\n    field m.a 8 uint range 0 10\n  else\n    field m.a 8 uint\nend\n")
        self.assertEqual(eng.encode("x", entity({"m.b": 2, "m.a": 50})), b"0232")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity({"m.b": 1, "m.a": 50}))


class TestNull(unittest.TestCase):
    """Ruling 1: a group that writes its list at the locator comes first."""

    def test_group_on_the_same_member(self):
        eng = engine("wire json\nfield m.s v string null\ngroup m.l v\n  field m.a a int\nend\n")
        self.assertEqual(eng.encode("x", entity({}, {"m.l": [Item({"m.a": 1})]})), b'{"v":[{"a":1}]}')
        self.assertEqual(eng.encode("x", entity({})), b'{"v":null}')


if __name__ == "__main__":
    unittest.main()
