"""Version 0.83: a length given by an earlier count (spec/engine-spec.md)."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import Engine, Entity, GTError, Item  # noqa: E402

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = ("module m\nversion 1\ndistribution public\nsource s\nkey a int -\nkey b int -\nkey c int -\nkey n int -\n"
         "list rows\nlist subs\n")
HEAD = "format %s\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"
REST = "group m.rows rest\n  field m.a 8 uint\nend\n"


def engine(body, inner=None):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(HEAD % "x" + body)
    if inner is not None:
        eng.load(HEAD % "in" + inner)
    return eng


def entity(rows=None, **fields):
    ent = Entity()
    ent.fields.update(("m." + k, v) for k, v in fields.items())
    if rows is not None:
        ent.lists["m.rows"] = []
        for v in rows:
            it = Item()
            it.fields["m.a"] = v
            ent.lists["m.rows"].append(it)
    return ent


class Base(unittest.TestCase):
    def code(self, fn, *args):
        try:
            fn(*args)
        except GTError as e:
            return e.code
        return None

    def rows(self, ent):
        return None if "m.rows" not in ent.lists else [it.fields.get("m.a") for it in ent.lists["m.rows"]]


class TestCodec(Base):
    W = "count w 8 plus 1\nfield m.b 8 uint\nlength @w units 16\n"

    def test_round_trip(self):
        eng = engine(self.W + REST + "end\nfield m.c 8 uint\n")
        ent = eng.decode("x", b"0307" b"01020304" b"09")
        self.assertEqual((self.rows(ent), ent.fields), ([1, 2, 3, 4], {"m.b": 7, "m.c": 9}))
        self.assertEqual(eng.encode("x", ent), b"03070102030409")
        self.assertEqual(self.code(eng.decode, "x", b"0007"), "malformed-wire")
        self.assertEqual(self.code(eng.encode, "x", entity(rows=[1, 2, 3])), "transform-encode")
        self.assertEqual(self.code(eng.encode, "x", entity(rows=[1] * 510)), "transform-encode")
        self.assertEqual(eng.encode("x", entity(rows=[])), b"010000")

    def test_content_skipped_absent_and_straddling(self):
        eng = engine("count w 8\nlength @w units 8\n  field m.a 8 uint\n  field m.b 16 uint\nend\nfield m.c 8 uint\n")
        self.assertEqual(eng.decode("x", b"040100020909").fields, {"m.a": 1, "m.b": 2, "m.c": 9})
        self.assertEqual(eng.decode("x", b"010109").fields, {"m.a": 1, "m.c": 9})
        self.assertEqual(eng.decode("x", b"0009").fields, {"m.c": 9})
        self.assertEqual(self.code(eng.decode, "x", b"02010909"), "malformed-wire")

    def test_beyond_the_input(self):  # rulings 5 and 15
        eng = engine("count w 8\nlength @w units 8\n  field m.a 8 uint\nend\n")
        self.assertEqual(eng.decode("x", b"0101").fields, {"m.a": 1})
        self.assertEqual(eng.decode("x", b"020109").fields, {"m.a": 1})
        self.assertEqual(self.code(eng.decode, "x", b"0201"), "malformed-wire")  # also when its lines fit
        self.assertEqual(self.code(engine("count w 8\nlength @w units 8\nend\n").decode, "x", b"01"), "malformed-wire")
        kinds = "group m.rows rest\n  kind k\n  when 8 1\n  kind j\n  when 8 2\nend\n"
        self.assertEqual(self.code(engine("count w 8\nlength @w units 8\n" + kinds + "end\n").decode, "x", b"0307"),
                         "malformed-wire")  # before an item is read
        whole = "length 8 whole\ncount w 8\nlength @w units 8\n  field m.a 8 uint\nend\n"
        self.assertEqual(self.code(engine(whole).decode, "x", b"03020102"), "malformed-wire")
        self.assertEqual(engine(whole).decode("x", b"03010102").fields, {"m.a": 1})
        huge = engine("count w 64\nlength @w units 65535\n  group m.rows rest\n    field m.a 8 uint\n  end\nend\n")
        self.assertEqual(self.code(huge.decode, "x", b"ff" * 9), "malformed-wire")

    def test_a_count_whose_block_is_not_read(self):  # ruling 9
        B = "length @w units 8\n  field m.a 8 uint\nend\n"
        G = "group m.rows count @w\n  field m.a 8 uint\nend\n"
        cases = (
            ("count w 8\nopt\n" + B + "end\npad 7\n", b"0000", b"0100"),
            ("count w 8\npresence p 8\nif p.1\n" + B + "end\n", b"0000", b"0100"),
            ("count w 8\nchain\npad 7\nfx\n" + B + "end\n", b"0000", b"0100"),
            ("count w 8\nlength 8\n  field m.b 8 uint\n" + B + "end\n", b"000109", b"010109"),
            ("count w 8\nlength 8\n  length 8\n" + B + "  end\nend\n", b"0000", b"0100"),
            ("count w 8\nfield m.b 8 uint\nswitch m.b\n  case 1\n  opt\n" + B + "  end\n  else\n" + B + "end\npad 7\n",
             b"000100", b"010100"),
        )
        for body, good, bad in cases:
            eng = engine(body)
            self.assertIsNone(self.code(eng.decode, "x", good), body)
            self.assertEqual(self.code(eng.decode, "x", bad), "malformed-wire", body)
        # a list on the path read is ruling 6 of 0.21
        eng = engine("count w 8\nkind k\nwhen 8 1\nopt\n" + G + "end\nkind j\nwhen 8 2\n" + B)
        self.assertIsNone(self.code(eng.decode, "x", b"050100"))
        eng = engine("count w 8\nfield m.b 8 uint\nswitch m.b\n  case 1\n  opt\n" + G + "  end\n  else\n" + B + "end\n")
        self.assertIsNone(self.code(eng.decode, "x", b"050100"))
        # a switch in a part not read counts when any of its cases holds the block
        eng = engine("count w 8\nfield m.b 8 uint\nopt\n  switch m.b\n  case 1\n" + G + "  else\n" + B + "  end\nend\npad 7\n")
        self.assertEqual(self.code(eng.decode, "x", b"050100"), "malformed-wire")
        self.assertIsNone(self.code(eng.decode, "x", b"000100"))
        # an item is a scope of its own, and one item says nothing of the next
        eng = engine("group m.subs count 8\n  count w 7\n  opt\n" + B.replace("m.a", "m.c") + "  end\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"02" b"0309" b"02"), "malformed-wire")
        self.assertIsNone(self.code(eng.decode, "x", b"02" b"0309" b"00"))
        # when the scope has been read: an error in a later line of it comes first
        eng = engine("count w 8\nopt\n" + B + "end\npad 7\ngroup m.rows count 8\n  kind k\n  when 8 1\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"01000109"), "no-kind")
        eng = engine("count w 8\nopt\n" + B + "end\npad 7\nfield m.n 8 twos\n")
        self.assertEqual(self.code(eng.decode, "x", b"010007"), "malformed-wire")

    def test_a_choice(self):  # ruling 9
        head = "encoding uper\ncount w 8\n"
        B = "length @w units 8\n  field m.a 8 uint\nend\n"
        eng = engine(head + "choice 2\n  alt 0\n" + B + "  alt 1\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"0180"), None)  # not chosen
        self.assertEqual(eng.decode("x", b"010380").fields, {"m.a": 7})
        eng = engine(head + "choice 2\n  alt 0\n  opt\n" + B + "  end\n  alt 1\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"0100"), "malformed-wire")  # an opt not read in the chosen alt
        self.assertEqual(self.code(eng.decode, "x", b"0180"), None)
        self.assertEqual(self.code(eng.decode, "x", b"0000"), None)
        eng = engine(head + "opt\n  choice 2\n  alt 0\n" + B + "  alt 1\n  end\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"0100"), "malformed-wire")  # the opt is what is not read
        eng = engine(head + "choice 2 ext\n  alt 0\n" + B + "  alt 1\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"01800080"), None)  # an extension alternative

    def test_a_count_of_one_item_is_not_the_next_ones(self):
        eng = engine("group m.subs count 8\n  length 8\n    count w 8\n    field m.b 8 uint\n    length @w units 8\n"
                     "      group m.rows rest\n        field m.a 8 uint\n      end\n    end\n  end\nend\n")
        ent = eng.decode("x", b"03" b"0301" b"0507" b"00" b"020009")
        self.assertEqual([self.rows(it) for it in ent.lists["m.subs"]], [[7], None, None])
        opt = engine("group m.subs count 8\n  opt\n    count w 7\n    length @w units 8\n      field m.a 8 uint\n    end\n"
                     "  end\n  pad 7\nend\n")
        self.assertEqual([it.fields for it in opt.decode("x", b"0281070000").lists["m.subs"]], [{"m.a": 7}, {}])

    def test_enclosing_extents(self):  # ruling 4
        eng = engine("length 8\n  count w 8\n  length @w units 8\n    field m.a 8 uint\n" + REST + "  end\nend\n"
                     "field m.c 8 uint\n")
        self.assertEqual(self.code(eng.decode, "x", b"02020109"), "malformed-wire")
        self.assertEqual(self.code(eng.decode, "x", b"01ff09"), "malformed-wire")  # absent, and its count states units
        self.assertIsNone(self.rows(eng.decode("x", b"010009")))
        self.assertEqual(eng.decode("x", b"010009").fields, {"m.c": 9})
        self.assertIsNone(self.rows(eng.decode("x", b"0009")))  # the count was not read
        self.assertEqual(self.rows(eng.decode("x", b"02000909")), [])  # zero units, one byte skipped

    def test_inner(self):
        eng = engine("count w 8\nlength @w units 16\n  inner in\nend\n", REST)
        self.assertEqual(self.rows(eng.decode("x", b"01" b"0102")), [1, 2])
        self.assertEqual(self.rows(eng.decode("x", b"00")), [])
        self.assertEqual(self.code(eng.decode, "x", b"0201020304"), None)
        self.assertEqual(self.code(eng.decode, "x", b"02010203"), "malformed-wire")
        self.assertEqual(eng.encode("x", entity(rows=[1, 2])), b"010102")
        self.assertEqual(self.code(eng.encode, "x", entity(rows=[1])), "transform-encode")
        bits = engine("count w 8\nlength @w units 12\n  inner in\nend\n", REST)
        self.assertEqual(self.code(bits.decode, "x", b"010102"), "malformed-wire")
        self.assertEqual(self.rows(bits.decode("x", b"02010203")), [1, 2, 3])

    def test_padding_and_units_in_bits(self):  # ruling 10
        eng = engine("count w 8\nlength @w units 8\n  field m.a 4 uint\nend\n")
        self.assertEqual(eng.encode("x", entity(a=1)), b"0110")
        eng = engine("count w 4\nlength @w units 12\n  field m.a 12 uint\nend\n")
        self.assertEqual(eng.encode("x", entity(a=0x123)), b"1123")
        one = engine("count w 8\nlength @w units 1\n  group m.rows rest\n    field m.a 1 uint\n  end\nend\n")
        self.assertEqual(self.rows(one.decode("x", b"03a0")), [1, 0, 1])
        self.assertEqual(one.encode("x", entity(rows=[1, 0, 1])), b"03a0")

    def test_not_written_and_empty(self):  # rulings 2 and 9
        eng = engine("count w 8 plus 2\nopt\n  length @w units 8\n    field m.a 8 uint\n  end\nend\n")
        self.assertEqual(eng.encode("x", entity()), b"0200")
        self.assertEqual(eng.decode("x", eng.encode("x", entity(a=5))).fields, {"m.a": 5})
        eng = engine("count w 8\nlength @w units 72\nend\nfield m.c 8 uint\n")
        self.assertEqual(eng.encode("x", entity(c=1)), b"0001")
        self.assertEqual(eng.decode("x", b"01" + b"ff" * 9 + b"07").fields, {"m.c": 7})

    def test_order_of_encode_errors(self):  # ruling 11
        body = "count w 8\nlength @w units 16\n  field m.a 8 uint\nend\n"
        with self.assertRaises(GTError) as e:
            engine(body + "field m.b 8 uint\n").encode("x", entity(b=256))
        self.assertIn("units", str(e.exception))
        with self.assertRaises(GTError) as e:
            engine(body).encode("x", entity(a=256))
        self.assertNotIn("units", str(e.exception))

    def test_a_whole_length_inside(self):  # ruling 16
        body = "count w 8\nlength @w units 8\n  length 8 whole\n  field m.a 8 uint\n  field m.b 8 uint\nend\n"
        eng = engine(body)
        self.assertEqual(eng.decode("x", b"03040102").fields, {"m.a": 1, "m.b": 2})
        self.assertEqual(self.code(eng.decode, "x", b"03030102"), "malformed-wire")
        self.assertEqual(eng.decode("x", b"02030102").fields, {"m.a": 1})

    def test_a_whole_length_inside_a_plain_block(self):  # ruling 16 is for every block
        body = "length 8 bytes\n  length 8 whole\n"
        eng = engine(body + "  field m.a 8 uint\n  field m.b 8 uint\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"03030102"), "malformed-wire")
        self.assertEqual(eng.decode("x", b"03040102").fields, {"m.a": 1, "m.b": 2})
        self.assertEqual(eng.decode("x", b"02030102").fields, {"m.a": 1})  # b starts at the end of its block
        self.assertEqual(self.code(engine(body + REST + "end\n").decode, "x", b"03030102"), "malformed-wire")
        self.assertEqual(self.rows(engine(body + REST + "end\n").decode("x", b"02030102")), [1])
        inner = engine(body + "  inner in\nend\n", REST)
        self.assertEqual(self.code(inner.decode, "x", b"03030102"), "malformed-wire")  # step 2 of 0.34
        self.assertEqual(self.rows(inner.decode("x", b"03040102")), [1, 2])
        self.assertEqual(self.code(engine(body + "  length 8 bytes\n    field m.a 8 uint\n  end\nend\n").decode, "x",
                                   b"03030102"), "malformed-wire")
        eng = engine(body + "  align 64\nend\n")
        self.assertEqual(eng.decode("x", b"03030102").fields, {})

    def test_a_whole_length_ends_the_input_of_a_plain_block_around(self):
        block = "length 8 bytes\n  count w 8\n  length @w units 8\n    length 8 whole\n  end\n"
        eng = engine(block + "  field m.a 8 uint\n  field m.b 8 uint\nend\n")
        self.assertEqual(eng.decode("x", b"0401050102").fields, {"m.a": 1, "m.b": 2})
        self.assertEqual(self.code(eng.decode, "x", b"0401040102"), "malformed-wire")  # b is past it, in the block
        self.assertEqual(eng.decode("x", b"0301040102").fields, {"m.a": 1})  # b is past the block
        self.assertEqual(self.code(engine(block + REST + "end\n").decode, "x", b"0401040102"), "malformed-wire")
        self.assertEqual(self.code(engine(block + "  inner in\nend\n", REST).decode, "x", b"0401040102"),
                         "malformed-wire")

    def test_a_whole_length_at_any_depth(self):
        eng = engine("count w 8\nlength @w units 8\n  length 8 bytes\n    length 8 whole\n    field m.a 8 uint\n"
                     "    field m.b 8 uint\n  end\n  field m.c 8 uint\nend\n")
        self.assertEqual(eng.decode("x", b"040305" b"0102").fields, {"m.a": 1, "m.b": 2})  # c is past its block
        self.assertEqual(self.code(eng.decode, "x", b"040304" b"0102"), "malformed-wire")  # b, in the plain block
        self.assertEqual(self.code(eng.decode, "x", b"040204" b"0102"), "malformed-wire")  # c, in the length @
        self.assertEqual(eng.decode("x", b"040205" b"0102").fields, {"m.a": 1, "m.c": 2})

    def test_a_when_past_the_whole(self):  # rulings 15 and 16
        kinds = "group m.rows rest\n  kind k\n  when 8 1\n  kind j\n  when 8 2\nend\n"
        for head, tail in (("length 8 bytes\n", b"03030101"), ("count w 8\nlength @w units 8\n", b"03030101")):
            eng = engine(head + "  length 8 whole\n" + kinds + "end\n")
            self.assertEqual(self.code(eng.decode, "x", tail), "no-kind")

    def test_message_level_after_a_plain_block(self):
        block = "length 8 bytes\n  length 8 whole\nend\n"
        for line in ("field m.a 8 uint\n", "pad 1\n", "opt\nend\n", "presence p 8\n", "length 8 bytes\nend\n",
                     "group m.rows while\n  field m.a 7 uint\nend\n", "const 8 0\n", "length 8 whole\n"):
            self.assertEqual(self.code(engine(block + line).decode, "x", b"0202ff"), "malformed-wire", line)
        self.assertEqual(engine(block + "align 64\n").decode("x", b"0202ff").fields, {})
        self.assertEqual(self.rows(engine(block + REST).decode("x", b"0202ff")), [])
        eng = engine("count w 8\n" + block + "group m.rows count @w\n  field m.a 8 uint\nend\n")
        self.assertEqual(self.rows(eng.decode("x", b"000203ff")), [])
        self.assertEqual(self.code(eng.decode, "x", b"010203ff"), "malformed-wire")
        self.assertEqual(self.rows(engine(block + "inner in\n", REST).decode("x", b"0202ff")), [])
        self.assertEqual(self.code(engine(block + "inner in\n", "field m.a 8 uint\n").decode, "x", b"0202ff"),
                         "malformed-wire")
        bits = engine("length 8 bits\n  length 8 whole\nend\ninner in\n", REST)
        self.assertEqual(self.code(bits.decode, "x", b"0902ffff"), "malformed-wire")  # inside a byte

    def test_a_plain_length_inside(self):  # ruling 17
        eng = engine("count w 8\nlength @w units 8\n  length 8\n    field m.a 8 uint\n  end\nend\n")
        self.assertEqual(self.code(eng.decode, "x", b"ff0201"), "malformed-wire")
        self.assertEqual(self.code(eng.decode, "x", b"02020107"), "malformed-wire")
        self.assertEqual(eng.decode("x", b"020101").fields, {"m.a": 1})


class TestLoad(Base):
    def load(self, body):
        return self.code(engine, body)

    def test_form(self):
        C = "count w 8\n"
        for line in ("length @w", "length @w units", "length @w 8", "length @w bytes 8", "length @w units 8 plus 1",
                     "length @w units 8 units 8", "length @ units 8", "length 8 units 8", "length units 8 @w",
                     "length @w 8 units", "length @w units 0", "length @w units 65536", "length @w units +8",
                     "length @w units -8", "length @w units 0x8", "length @w units 8.0", "length @w units ٨",
                     "length @w units " + "9" * 5000, "length @z units 8", "length @w units 8 bits", "length 8 bytes units"):
            self.assertEqual(self.load(C + line + "\nend\n"), "bad-directive", line)
            self.assertEqual(self.load(C + line + "\nend\nbogus\n"), "unknown-directive", line)
        for u in ("1", "8", "0008", "65535", "0" * 5000 + "8"):
            self.assertIsNone(self.load(C + "length @w units %s\nend\n" % u))

    def test_references(self):
        C = "count w 8\n"
        B = "length @w units 8\nend\n"
        G = "group m.rows count @w\n  field m.a 8 uint\nend\n"
        for body in (C, C + B + B, C + B + G, C + G + B, C + "length @w units 8\n" + G + "end\n",
                     C + "length @w units 8\n" + B + "end\n", B + C,
                     C + "kind k\nwhen 8 1\n" + B + "kind j\nwhen 8 2\n", C + "length @w units 8\n",
                     "presence w 8\n" + B, C + "group m.rows count 8\n" + B + "end\n" + B,
                     "opt\n" + C + "end\n" + B, "length @w units 8\n" + REST + "end\n"):
            self.assertEqual(self.load(body), "bad-directive", body)
        for body in (C + B, C + "kind k\nwhen 8 1\n" + B + "kind j\nwhen 8 2\n" + G, C + "opt\n" + B + "end\n",
                     "group m.rows count 8\n" + C + B + "end\n", "length 8\n" + C + B + "end\n"):
            self.assertIsNone(self.load(body), body)

    def test_wire_line(self):  # ruling 12
        self.assertEqual(self.load("count w 8\n" + REST + "length @w units 8\nend\n"), "bad-directive")
        self.assertIsNone(self.load("count w 8\nlength @w units 8\n" + REST + "end\n"))

    def test_other_layouts_and_wires(self):
        for head in ("wire bits\nword_bytes 1\n", "wire json\n", "wire xml\nroot r\n", "wire text\n", "wire protobuf\n",
                     "wire tlv\n", "wire cbor\n"):
            for tail, code in (("", "bad-directive"), ("bogus\n", "unknown-directive")):
                eng = Engine()
                eng.load_model(CORE)
                eng.load_model(MODEL)
                self.assertEqual(self.code(eng.load, "format x\nversion 1\ndistribution public\nsource s\nuses m\n" + head
                                           + "length @w units 8\nend\n" + tail), code, head)


if __name__ == "__main__":
    unittest.main()
