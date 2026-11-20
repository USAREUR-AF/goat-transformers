"""Unit tests for Version 0.20 beyond the shared vectors (spec/engine-spec.md,
"Version 0.20: kind selection"): presence bits named only inside cases
(ruling 21), a presence written before the key its switch reads, and the
`when` token count on a text wire."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError  # noqa: E402

MODEL = (
    "module core\nversion 1\ndistribution public\nsource s\n"
    "key uid string -\nkey x int -\nkey y int -\nkey z int -\n"
)
HEAD = "format p\nversion 1\ndistribution public\nsource s\n"
SWITCHED = HEAD + (
    "wire bits\nlayout sequential\nbit_order msb\n"
    "presence p 8\nfield x 8 uint\n"
    "switch x\n  case 1\n    if p.1\n      field y 8 uint\n    end\n"
    "  case 2\n    if p.2\n      field z 8 uint\n    end\nend\n"
)


def engine(pack):
    eng = Engine()
    eng.load_model(MODEL)
    eng.load(pack)
    return eng


def entity(**fields):
    ent = Entity()
    ent.fields.update(fields)
    return ent


class TestSwitchPresence(unittest.TestCase):
    def test_bits_of_the_selected_case_decode(self):
        eng = engine(SWITCHED)
        self.assertEqual(eng.decode("p", "800105").fields, {"x": 1, "y": 5})
        self.assertEqual(eng.decode("p", "400207").fields, {"x": 2, "z": 7})

    def test_bit_named_only_by_another_case_is_malformed(self):
        eng = engine(SWITCHED)
        for data in ("400107", "800205"):
            with self.assertRaises(GTError, msg=data) as cm:
                eng.decode("p", data)
            self.assertEqual(cm.exception.code, "malformed-wire", data)

    def test_presence_before_the_key_counts_the_selected_case(self):
        eng = engine(SWITCHED)
        self.assertEqual(eng.encode("p", entity(x=1, y=5)), b"800105")
        # y is held but its case is not selected: its bit is not set
        self.assertEqual(eng.encode("p", entity(x=2, y=5, z=7)), b"400207")

    def test_value_no_case_holds_is_no_kind(self):
        eng = engine(SWITCHED)
        with self.assertRaises(GTError) as cm:
            eng.encode("p", entity(x=3, z=1))
        self.assertEqual(cm.exception.code, "no-kind")


class TestWhenTokens(unittest.TestCase):
    def test_space_in_a_text_list_is_bad_directive(self):
        with self.assertRaises(GTError) as cm:
            engine(HEAD + "wire json\nkind a\nwhen t a, b\n")
        self.assertEqual(cm.exception.code, "bad-directive")


if __name__ == "__main__":
    unittest.main()
