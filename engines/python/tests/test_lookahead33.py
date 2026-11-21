"""Version 0.33: a kind decided by a field after other fields (spec/engine-spec.md).
The conformance vectors pin the behaviour; these tests pin what they state but
do not reach: rulings 22 and 26, a switch reading bits a window wrote, and the
`msb-lsb` bit order."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, TransformEncodeFailure  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = "module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey c int -\nkey d int -\n"


def engine(body, order="msb"):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load("format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\n"
             "bit_order %s\n%s" % (order, body))
    return eng


def entity(fields):
    ent = Entity()
    ent.fields.update(fields)
    return ent


class TestOverlap(unittest.TestCase):
    """Ruling 26."""

    BODY = "kind k\nwhen 4 1 at 0\nwhen 4 3 at 0\nfield m.a 4 uint\nfield m.b 4 uint\n"

    def test_written_window_is_overwritten_without_a_check(self):
        self.assertEqual(engine(self.BODY).encode("x", entity({})), b"30")

    def test_standing_window_leaves_held_bits(self):
        with self.assertRaises(TransformEncodeFailure):
            engine(self.BODY).encode("x", entity({"m.a": 1}))


class TestSwitch(unittest.TestCase):
    """Ruling 22 and the Encode text: a switch reads its key from the bits as
    they stand after the windows are written."""

    def test_switch_on_an_as_key_a_window_binds(self):
        eng = engine("kind k\nwhen 8 1..3 at 0 as m.a\nfield m.b 8 uint\nswitch m.a\n  case 1\n"
                     "    field m.c 8 uint\n  case 2\n    field m.d 8 uint\nend\n")
        out = eng.encode("x", entity({"m.a": 2, "m.d": 7}))
        self.assertEqual(out, b"0207")
        ent = eng.decode("x", out)
        self.assertEqual((ent.fields["m.a"], ent.fields["m.b"], ent.fields["m.d"]), (2, 2, 7))

    def test_switch_on_a_field_a_window_wrote(self):
        eng = engine("kind k\nwhen 8 2 at 0\nfield m.b 8 uint\nswitch m.b\n  case 2\n    field m.d 8 uint\n"
                     "  else\nend\n")
        self.assertEqual(eng.encode("x", entity({"m.d": 7})), b"0207")


class TestBitOrders(unittest.TestCase):
    def test_partial_window_round_trips(self):
        for order in ("msb", "lsb", "msb-lsb"):
            eng = engine("kind k\nwhen 4 9 at 2\nfield m.a 3 uint\nfield m.b 5 uint\nkind j\nfield m.c 8 uint\n",
                         order)
            ent = eng.decode("x", eng.encode("x", entity({})))
            self.assertEqual(ent.kind, ("x", "k"), order)


if __name__ == "__main__":
    unittest.main()
