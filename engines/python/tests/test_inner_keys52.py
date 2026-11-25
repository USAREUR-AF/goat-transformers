"""Version 0.52, rulings 20 to 20d: the fifth check of an `inner` line, a key
that lines of both packs map (spec/engine-spec.md)."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError, Item  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey type string -\nkey time_ms int ms\n"
MODEL = ("module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey c int -\nkey n int -\n"
         "key s string -\nlist rows\nlist subs\n")
HEAD = "format %s\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"
BLOCK = "length 8 bytes\n  inner in\nend\n"


def engine(inner, outer):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(HEAD % "x" + outer)
    if inner is not None:
        eng.load(HEAD % "in" + inner)
    return eng


def entity(**fields):
    ent = Entity()
    ent.fields.update(("m." + k, v) for k, v in fields.items())
    return ent


class Base(unittest.TestCase):
    def code(self, fn, *args):
        try:
            fn(*args)
        except GTError as e:
            return e.code
        return None


class TestReach(Base):
    A = "field m.a 8 uint\n"

    def both(self, inner, outer, data=b"01010101", ent=None):
        eng = engine(inner, outer)
        ent = ent or entity(a=1, b=1)
        return self.code(eng.decode, "x", data), self.code(eng.encode, "x", ent)

    def test_lines_of_every_block_count(self):
        for outer in (BLOCK + self.A, self.A + BLOCK, BLOCK + "opt\n  field m.a 7 uint\nend\n",
                      "presence p 8\n" + BLOCK + "if p.1\n  field m.a 8 uint\nend\n",
                      "field m.b 8 uint\n" + BLOCK + "switch m.b\n  case 9\n    field m.a 8 uint\n  else\nend\n",
                      "field m.b 8 uint\n" + BLOCK + "switch m.b\n  case 9\n  else\n    field m.a 8 uint\nend\n",
                      "field m.b 8 uint\nalso m.a\n" + BLOCK):
            self.assertEqual(self.both(self.A, outer, b"00" * 12), ("bad-directive", "bad-directive"), outer)

    def test_as_lines_of_both_packs(self):
        for line in ("when 8 1 as m.a\n", "when 8 1 as m.a optional\n", "when 8 1 at 0 as m.a optional\npad 8\n"):
            self.assertEqual(self.both(self.A, "kind k\n" + line + BLOCK), ("bad-directive", "bad-directive"))
            self.assertEqual(self.both("kind k\n" + line, self.A + BLOCK), ("bad-directive", "bad-directive"))

    def test_kinds_of_the_outer_pack(self):
        kinds = "kind k\nwhen 8 1\nfield m.c 8 uint\nkind j\nwhen 8 2\n" + self.A
        # in the common lines: every kind is in reach, the one not selected included
        self.assertEqual(self.both(self.A, BLOCK + kinds, b"010501ff", entity(c=1)), ("bad-directive", "bad-directive"))
        # in a kind: the lines of other kinds are not
        own = "kind k\nwhen 8 1\n" + BLOCK + "kind j\nwhen 8 2\n" + self.A
        eng = engine(self.A, own)
        self.assertEqual(eng.decode("x", b"010105").fields, {"m.a": 5})
        self.assertEqual(eng.encode("x", entity(a=5)), b"010105")
        self.assertEqual(self.both(self.A, "field m.a 8 uint\n" + own, b"05010105"), ("bad-directive", "bad-directive"))

    def test_every_kind_of_the_inner_pack(self):
        inner = "kind k\nwhen 8 1\nkind j\nwhen 8 2\n" + self.A
        self.assertEqual(self.both(inner, self.A + BLOCK), ("bad-directive", "bad-directive"))

    def test_entries_are_compared_as_text(self):
        rows = "group m.rows count 8\n  field m.a 8 uint\nend\n"
        subs = "group m.subs count 8\n  group m.rows count 8\n    field m.a 8 uint\n  end\nend\n"
        self.assertEqual(self.both(rows, rows.replace("m.a", "m.b") + BLOCK, b"000100"), ("bad-directive",) * 2)
        self.assertEqual(self.both(rows, self.A + BLOCK, b"000100"), (None, None))
        self.assertEqual(self.both(rows, subs + BLOCK, b"000100"), (None, None))

    def test_names_that_do_not_map(self):
        outer = "default m.a 1\nkind k\nrequires m.a\nfield m.b 8 uint\n" + BLOCK
        self.assertEqual(self.both(self.A, outer, b"010105"), (None, None))


class TestOrder(Base):
    CLASH = "field m.a 8 uint\n"

    def test_before_the_tests_of_the_line(self):
        for data in (b"00", b"02aabb"):  # an empty input, a cursor inside a byte
            for outer in ("field m.a 4 uint\n  length 4 bytes\n  inner in\nend\n",
                          "field m.a 3 uint\nlength 4 bytes\n  inner in partial\nend\n"):
                eng = engine(self.CLASH, outer)
                self.assertEqual(self.code(eng.decode, "x", data), "bad-directive")
                self.assertEqual(self.code(eng.encode, "x", entity(a=1)), "bad-directive")

    def test_the_other_checks_come_first(self):
        eng = engine(None, "field m.a 8 uint\n" + BLOCK)
        self.assertEqual(self.code(eng.decode, "x", b"0100"), "unknown-format")
        eng.load((HEAD % "in").replace("layout sequential\nbit_order msb\n", "") .replace("wire bits", "wire json")
                 + "field m.a a int\n")
        self.assertEqual(self.code(eng.decode, "x", b"0100"), "bad-directive")

    def test_decode_errors_before_and_after(self):
        outer = "field m.s 8 ascii\n" + BLOCK + "field m.a 8 uint\n"
        self.assertEqual(self.code(engine(self.CLASH, outer).decode, "x", b"ff0101"), "bad-directive")
        self.assertEqual(self.code(engine(self.CLASH, "when 8 1\n" + BLOCK + "kind k\n" + self.CLASH).decode, "x", b"02"),
                         "no-kind")

    def test_encode_errors(self):
        outer = "field m.n 4 uint\npad 4\n" + BLOCK + "kind k\nrequires m.b\n" + self.CLASH
        eng = engine(self.CLASH, outer)
        self.assertEqual(self.code(eng.encode, "x", entity(a=1)), "no-kind")
        self.assertEqual(self.code(eng.encode, "x", entity(b=1, n=16)), "transform-encode")
        self.assertEqual(self.code(eng.encode, "x", entity(b=1, n=1)), "bad-directive")
        later = "field m.n 8 uint\n" + BLOCK + "switch m.n\n  case 9\n    field m.a 8 uint\nend\n"
        self.assertEqual(self.code(engine(self.CLASH, later).encode, "x", entity(n=1)), "bad-directive")

    def test_names_the_inner_format_and_is_not_a_check_of_the_pack(self):
        eng = engine(self.CLASH, "field m.b 8 uint\n" + BLOCK + "kind k\n" + self.CLASH)
        with self.assertRaises(GTError) as e:
            eng.decode("x", b"0100")
        self.assertEqual(e.exception.format, "in")
        self.assertEqual(eng.model_keys("x"), ["m.b", "m.a"])


class TestUnread(Base):
    """Ruling 20b: an `inner` line in a block that reads as absent is not reached on decode."""

    OUTER = "length 8 bytes\n  field m.c 8 uint\n  length 8 bytes\n    inner in\n  end\nend\nfield m.n 8 uint\n"

    def decode(self, inner, outer=None):
        ent = engine(inner, outer or self.OUTER).decode("x", b"010507")
        self.assertEqual(ent.fields, {"m.c": 5, "m.n": 7})
        self.assertEqual(ent.lists, {})
        self.assertIsNone(ent.inner_kind)

    def test_an_inner_list_is_absent(self):
        self.decode("group m.rows rest\n  field m.b 8 uint\nend\n")

    def test_an_inner_pack_that_needs_bits(self):
        self.decode("field m.b 8 uint\n")

    def test_an_inner_format_that_is_not_loaded(self):
        self.decode(None)

    def test_a_clash_and_blocks_at_any_depth(self):
        deeper = self.OUTER.replace("    inner in\n", "    length 8 bytes\n      inner in\n    end\n")
        self.decode("field m.n 8 uint\n")
        self.decode("field m.n 8 uint\n", deeper)

    def test_the_end_of_its_own_extent_is_reached(self):
        eng = engine("field m.n 8 uint\n", self.OUTER)
        self.assertEqual(self.code(eng.decode, "x", b"02050007"), "bad-directive")
        self.assertEqual(self.code(engine(None, self.OUTER).decode, "x", b"02050007"), "unknown-format")
        self.assertEqual(self.code(engine("field m.b 8 uint\n", self.OUTER).decode, "x", b"02050007"), "malformed-wire")


class TestTypemap(Base):
    def test_each_pack_maps_its_own_lines(self):  # ruling 20d
        eng = engine("typemap B a-n-G\nfield type 8 ascii\n", "typemap A a-f-G\ntypemap a-n-G a-u-G\n" + BLOCK)
        ent = eng.decode("x", b"0142")
        self.assertEqual(ent.fields, {"type": "a-n-G"})
        self.assertEqual(eng.encode("x", ent), b"0142")
        ent = eng.decode("x", b"0141")
        self.assertEqual(ent.fields, {"type": "A"})
        self.assertEqual(eng.encode("x", ent), b"0141")


if __name__ == "__main__":
    unittest.main()
