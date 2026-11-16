"""Version 0.8: sequential binary layouts, `uses` in model modules and the
derive functions added (spec/engine-spec.md). The conformance vectors pin the
behaviour; these tests pin the engine's own surface around it."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from goat_transformers import (  # noqa: E402
    BadDirective, DistributionViolation, DuplicateKind, Engine, Entity, Item, KeyTypeMismatch, MalformedWire, NoKind,
    TransformEncodeFailure, UnknownModule, parse_model_text, parse_pack_text,
)

CORE = "module core\nversion 1\ndistribution public\nsource s\nkey uid string -\nkey time_ms int ms\n"
MODEL = (
    "module m\nversion 1\ndistribution public\nsource s\n"
    "key a int -\nkey b int -\nkey c int -\nkey s string -\nkey f float -\nlist rows\nlist cells\n"
)
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nlayout sequential\nbit_order msb\n"


def engine(body, head=HEAD):
    eng = Engine()
    eng.load_model(CORE)
    eng.load_model(MODEL)
    eng.load(head + body)
    return eng


def entity(fields=None, lists=None):
    ent = Entity()
    ent.fields.update(fields or {})
    ent.lists.update(lists or {})
    return ent


def item(**fields):
    it = Item()
    it.fields.update(fields)
    return it


class TestSequentialLines(unittest.TestCase):
    def test_field_const_pad_align_at_a_cursor(self):
        eng = engine("field m.a 4 uint\nconst 4 10\npad 3\nalign 8\nfield m.b 8 twos\n")
        ent = eng.decode("x", "5f00fe")  # const and pad bits are ignored on decode
        self.assertEqual(ent.fields, {"m.a": 5, "m.b": -2})
        self.assertEqual(eng.encode("x", ent), b"5a00fe")
        self.assertEqual(eng.encode("x", entity()), b"0a0000")  # an absent key writes zero bits

    def test_lsb_order(self):
        eng = engine("field m.a 4 uint\nfield m.b 12 uint\n", HEAD.replace("msb", "lsb"))
        ent = eng.decode("x", "2143")
        self.assertEqual(ent.fields, {"m.a": 1, "m.b": 0x432})
        self.assertEqual(eng.encode("x", ent), b"2143")

    def test_input_ends_inside_a_field(self):
        eng = engine("field m.a 8 uint\nfield m.b 16 uint\n")
        with self.assertRaises(MalformedWire):
            eng.decode("x", "0102")
        self.assertEqual(eng.decode("x", "010203ff").fields["m.b"], 0x0203)  # input beyond the last line

    def test_kinds_by_sequential_when(self):
        eng = engine(
            "field m.a 8 uint\nkind one\nwhen 4 1\nwhen 4 2\nrequires m.b\nfield m.b 8 uint\n"
            "kind two\nwhen 8 7\nfield m.c 8 uint\n"
        )
        ent = eng.decode("x", "091233")
        self.assertEqual((ent.kind, ent.fields), (("x", "one"), {"m.a": 9, "m.b": 0x33}))
        self.assertEqual(eng.decode("x", "090744").kind, ("x", "two"))
        with self.assertRaises(NoKind):
            eng.decode("x", "091333")
        with self.assertRaises(NoKind):
            eng.decode("x", "09")  # a `when` beyond the input does not hold
        self.assertEqual(eng.encode("x", entity({"m.a": 1, "m.c": 2})), b"010702")
        self.assertEqual(eng.encode("x", entity({"m.a": 1, "m.b": 2})), b"011202")


class TestPresence(unittest.TestCase):
    BODY = (
        "presence p 4\nif p.1\n  field m.a 4 uint\nend\nif p.2 p.3\n  field m.b 8 uint\nend\n"
        "if p.2 !p.3\n  field m.c 8 uint\nend\nalign 8\n"
    )

    def test_bits_are_computed_from_the_entity(self):
        eng = engine(self.BODY)
        self.assertEqual(eng.encode("x", entity()), b"00")
        self.assertEqual(eng.encode("x", entity({"m.a": 9})), b"89")
        self.assertEqual(eng.encode("x", entity({"m.b": 0x55})), b"6550")
        # c sets p.2; with p.3 also 1 its block is not written (ruling 4 of 0.8)
        self.assertEqual(eng.encode("x", entity({"m.b": 0x55, "m.c": 1})), b"6550")
        self.assertEqual(eng.encode("x", entity({"m.c": 0x11})), b"4110")
        self.assertEqual(eng.decode("x", "4110").fields, {"m.c": 0x11})

    def test_set_bit_no_if_names(self):
        eng = engine(self.BODY)
        with self.assertRaises(MalformedWire):
            eng.decode("x", "10")  # p.4 (ruling 1 of 0.8)

    def test_fx_octets(self):
        eng = engine("presence f fx\nif f.1\n  field m.a 8 uint\nend\nif f.8\n  field m.b 8 uint\nend\n")
        self.assertEqual(eng.encode("x", entity()), b"00")  # at least one octet
        self.assertEqual(eng.encode("x", entity({"m.a": 1})), b"8001")
        self.assertEqual(eng.encode("x", entity({"m.b": 2})), b"018002")
        self.assertEqual(eng.decode("x", "81800102").fields, {"m.a": 1, "m.b": 2})
        self.assertEqual(eng.decode("x", "810001").fields, {"m.a": 1})  # a trailing zero octet is read
        with self.assertRaises(MalformedWire):
            eng.decode("x", "81")

    def test_default_counts_as_present(self):
        eng = engine("opt\n  field m.a 7 uint\nend\ndefault m.a 3\n")
        self.assertEqual(eng.encode("x", entity()), b"83")

    def test_message_presence_named_inside_an_item(self):
        eng = engine(
            "presence p 1\npad 7\ngroup m.rows count 8\n  field m.a 8 uint\n  if p.1\n    field m.b 8 uint\n  end\nend\n"
        )
        rows = [item(**{"m.a": 1}), item(**{"m.a": 2, "m.b": 9})]
        self.assertEqual(eng.encode("x", entity(lists={"m.rows": rows})), b"800201000209")
        self.assertEqual(eng.encode("x", entity(lists={"m.rows": rows[:1]})), b"000101")


class TestGroupsChainsLengths(unittest.TestCase):
    def test_group_forms(self):
        for mode, wire in (("count 8", "020a18"), ("while", "858600"), ("more", "8506"), ("fx", "0b0c")):
            eng = engine("group m.rows %s\n  field m.a 7 uint\nend\n" % mode)
            ent = eng.decode("x", wire)
            self.assertEqual([it.fields["m.a"] for it in ent.lists["m.rows"]], [5, 6], mode)
            self.assertEqual(eng.encode("x", ent).decode(), wire, mode)

    def test_more_and_fx_need_an_item(self):
        for mode in ("more", "fx"):
            eng = engine("group m.rows %s\n  field m.a 7 uint\nend\n" % mode)
            for lists in ({}, {"m.rows": []}):
                with self.assertRaises(TransformEncodeFailure):
                    eng.encode("x", entity(lists=lists))
            eng = engine("opt\n  group m.rows %s\n    field m.a 7 uint\n  end\nend\n" % mode)
            self.assertEqual(eng.encode("x", entity(lists={"m.rows": []})), b"00")

    def test_while_of_no_items_and_count_overflow(self):
        eng = engine("group m.rows while\n  field m.a 7 uint\nend\n")
        self.assertEqual(eng.encode("x", entity()), b"00")
        self.assertEqual(eng.decode("x", "00").lists, {"m.rows": []})
        eng = engine("group m.rows count 2\n  field m.a 8 uint\nend\n")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity(lists={"m.rows": [item()] * 4}))
        with self.assertRaises(MalformedWire):
            eng.decode("x", "c0")

    def test_items_by_kind(self):
        eng = engine(
            "group m.rows count 8\n  field m.a 4 uint\n  kind p\n  when 4 1\n  requires m.b\n  field m.b 8 uint\n"
            "  kind q\n  when 4 2\nend\n"
        )
        ent = eng.decode("x", "02512272")
        rows = ent.lists["m.rows"]
        self.assertEqual([r.kind for r in rows], [("x", "p"), ("x", "q")])
        self.assertEqual(eng.encode("x", ent), b"02512272")
        rows = [item(**{"m.a": 1}), item(**{"m.a": 2, "m.b": 3})]  # no kind recorded: chosen by `requires`
        self.assertEqual(eng.encode("x", entity(lists={"m.rows": rows})), b"02122103")
        with self.assertRaises(NoKind):
            eng.decode("x", "0153")

    def test_chain(self):
        eng = engine("chain\n  field m.a 7 uint\n  fx\n  field m.b 7 uint\n  fx\nend\n")
        self.assertEqual(eng.encode("x", entity({"m.a": 1})), b"02")
        self.assertEqual(eng.encode("x", entity({"m.b": 1})), b"0102")
        self.assertEqual(eng.decode("x", "0102").fields, {"m.a": 0, "m.b": 1})
        with self.assertRaises(MalformedWire):
            eng.decode("x", "0103")  # the chain ends with an `fx` line whose bit is 1 (ruling 3 of 0.8)

    def test_length_block(self):
        eng = engine("length 8 plus 1\n  field m.a 8 uint\n  field m.b 4 uint\nend\nfield m.c 8 uint\n")
        self.assertEqual(eng.encode("x", entity({"m.a": 1, "m.b": 2, "m.c": 3})), b"03012003")
        self.assertEqual(eng.decode("x", "020103").fields, {"m.a": 1, "m.c": 3})  # b is beyond the extent
        self.assertEqual(eng.decode("x", "050120ffff03").fields, {"m.a": 1, "m.b": 2, "m.c": 3})  # unread, skipped
        for bad in ("0001", "09012003"):
            with self.assertRaises(MalformedWire):
                eng.decode("x", bad)
        eng = engine("length 4 bits\n  field m.a 8 uint\nend\n")
        with self.assertRaises(MalformedWire):
            eng.decode("x", "4ff0")  # the field straddles the end of its extent (ruling 7 of 0.8)
        eng = engine("length 2 bits\n  field m.a 8 uint\nend\n")
        with self.assertRaises(TransformEncodeFailure):
            eng.encode("x", entity({"m.a": 1}))

    def test_length_whole(self):
        eng = engine("field m.a 8 uint\nlength 8 whole\nfield m.b 8 uint\n")
        self.assertEqual(eng.encode("x", entity({"m.a": 1, "m.b": 2})), b"010302")
        self.assertEqual(eng.decode("x", "010302ff").fields, {"m.a": 1, "m.b": 2})
        for bad in ("010402", "010202", "010102"):
            with self.assertRaises(MalformedWire):
                eng.decode("x", bad)

    def test_also_binds_a_second_key(self):
        eng = engine("field m.a 8 uint\nalso m.b via t\nmap t 1 100\n")
        self.assertEqual(eng.decode("x", "01").fields, {"m.a": 1, "m.b": 100})
        self.assertEqual(eng.encode("x", entity({"m.b": 100})), b"01")
        self.assertEqual(eng.encode("x", entity({"m.a": 7, "m.b": 100})), b"07")  # the earliest present key
        self.assertEqual(eng.model_keys("x"), ["m.a", "m.b"])


class TestSequentialLoad(unittest.TestCase):
    def test_bad_directives(self):
        for body in (
            "word_bytes 1\n",
            "field m.a 8 uint optional\n",
            "field m.a 0:0:8 uint\n",
            "const 0:0:8 1\n",
            "const 65 1\n",
            "const 4 16\n",
            "presence p 65\n",
            "presence p 2\npresence p 3\n",
            "presence p 2\nif p.3\nend\n",
            "if p.1\nend\n",
            "opt\n  presence p 2\nend\nif p.1\nend\n",
            "opt\n",
            "end\n",
            "fx\n",
            "when 8 1\n",
            "kind k\nfield m.a 8 uint\nwhen 8 1\n",
            "kind k\nopt\n  when 8 1\nend\n",
            "also m.b\n",
            "const 8 1\nalso m.b\n",
            "length 8 bits whole\n",
            "group m.rows 0:8 item 8 count 0:0:8\nend\n",
            "group m.rows count 8\n  map t 1 2\nend\n",
            "group m.rows count 8\nend\ngroup m.rows while\nend\n",
        ):
            with self.assertRaises(BadDirective, msg=body):
                engine(body)
        with self.assertRaises(DuplicateKind):
            engine("group m.rows count 8\n  kind k\n  when 8 1\n  kind k\n  when 8 2\nend\n")
        with self.assertRaises(KeyTypeMismatch):
            engine("field m.a 8 uint\nalso m.s\n")
        engine("group m.rows count 8\n  kind k\n  when 8 1\nend\nkind k\nwhen 8 1\n")  # a name per body
        engine("length 16 whole plus 1\nlength 16 bytes plus 2 whole\n")

    def test_sequential_lines_in_a_fixed_layout_pack(self):
        head = "format x\nversion 1\ndistribution public\nsource s\nuses m\nwire bits\nword_bytes 1\n"
        for body in ("pad 8\n", "align 8\n", "presence p 2\n", "opt\nend\n", "chain\nend\n", "fx\n", "length 8\nend\n",
                     "field m.a 8 uint\n", "field m.a 0:0:8 uint\nalso m.b\n",
                     "group m.rows while\n  field m.a 0:0:8 uint\nend\n"):
            with self.assertRaises(BadDirective, msg=body):
                parse_pack_text(head + body)
        parse_pack_text(head + "layout fixed\nfield m.a 0:0:8 uint\n")
        with self.assertRaises(BadDirective):
            parse_pack_text(head.replace("wire bits\nword_bytes 1\n", "wire json\n") + "layout sequential\n")


class TestModelUsesAndDerive(unittest.TestCase):
    OTHER = "module o\nversion 1\ndistribution %s\nsource s\nuses m\nkey n int -\nkey t string -\nkey d float -\n"

    def load(self, other, m_distribution="public"):
        eng = Engine()
        eng.load_model(CORE)
        eng.load_model(MODEL.replace("distribution public", "distribution " + m_distribution))
        eng.load_model(other)
        return eng

    def test_uses(self):
        eng = self.load(self.OTHER % "public" + "derive o.n copy m.a\n")
        self.assertEqual(eng.models["o"].uses, ["m"])
        with self.assertRaises(BadDirective):  # an argument of a module the module does not use
            self.load((self.OTHER % "public").replace("uses m\n", "") + "derive o.n copy m.a\n")
        with self.assertRaises(BadDirective):  # a target of another module
            self.load(self.OTHER % "public" + "derive m.a copy o.n\n")
        with self.assertRaises(DistributionViolation):
            self.load(self.OTHER % "public", m_distribution="controlled")
        self.load(self.OTHER % "controlled")
        eng = Engine()
        eng.load_model(CORE)
        with self.assertRaises(UnknownModule):
            eng.load_model(self.OTHER % "public")
        self.assertEqual(parse_model_text(self.OTHER % "public").uses, ["m"])  # no engine: nothing to check against

    def test_derive_functions(self):
        eng = self.load(
            self.OTHER % "public"
            + "derive o.d day_seconds time_ms\nderive o.n parse_int o.t\nderive o.t text_of m.a\n"
            + "derive o.n any m.a m.b\n"
        )
        got = eng.complete(entity({"time_ms": -1, "m.a": 0})).fields
        self.assertEqual((got["o.d"], got["o.t"], got["o.n"]), (86399.999, "0", 0))
        self.assertEqual(eng.complete(entity({"o.t": "x12"})).fields, {"o.t": "x12"})  # no integer, no `any` argument
        self.assertEqual(eng.complete(entity({"m.b": 4})).fields["o.n"], 1)  # `any` of the arguments present
        eng = self.load(self.OTHER % "public" + "derive o.n not m.a\n")
        self.assertEqual(eng.complete(entity({"m.a": 0})).fields["o.n"], 1)
        self.assertEqual(eng.complete(entity({"m.a": 5})).fields["o.n"], 0)
        for bad in ("derive o.d day_seconds m.f\n", "derive o.n day_seconds time_ms\n", "derive o.n any m.a m.s\n",
                    "derive o.n not m.a m.b\n", "derive o.n parse_int m.a\n", "derive o.t text_of m.s\n",
                    "derive o.n any\n"):
            with self.assertRaises(BadDirective, msg=bad):
                self.load(self.OTHER % "public" + bad)

    def test_directory_loads_a_module_after_the_modules_it_uses(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = os.path.join(tmp, "model")
            packs = os.path.join(tmp, "packs")
            os.makedirs(models)
            os.makedirs(packs)

            def write(name, text):
                with open(os.path.join(models, name), "w", encoding="utf-8") as fh:
                    fh.write(text)

            write("core.def", CORE)
            write("a.def", (self.OTHER % "public").replace("module o", "module a").replace("uses m", "uses z"))
            write("z.def", MODEL.replace("module m", "module z"))
            eng = Engine.from_dir(packs, models)
            self.assertEqual(list(eng.models), ["core", "z", "a"])
            write("z.def", MODEL.replace("module m", "module z") + "uses a\n")
            with self.assertRaises(BadDirective):
                Engine.from_dir(packs, models)


if __name__ == "__main__":
    unittest.main()
