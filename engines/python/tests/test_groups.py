"""Groups and lists (spec/engine-spec.md, "Version 0.7: groups"): the engine's
own interface around them. The conformance vectors pin the wire behaviour;
these tests cover `Entity.lists`, `Item`, `model_keys`, `requires <list>` and
the named load errors, on the probe packs alone."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

from goat_transformers import (  # noqa: E402
    BadDirective, DuplicateKey, Engine, Entity, Item, KeyTypeMismatch, MalformedWire, TransformDecodeFailure,
    TransformEncodeFailure, UndeclaredKey, load_model_file, load_pack, parse_model_text,
)

PROBES = ("json", "kinds", "xml", "protobuf", "bits", "bits-msb", "bits-var", "geojson")
MODEL = (
    "module m\nversion 1\ndistribution public\nsource s\n"
    "key a int -\nkey b string -\nlist rows\nlist cells \"nested\"\n"
)
HEAD = "format x\nversion 1\ndistribution public\nsource s\nuses m\n"


def probe_engine():
    eng = Engine()
    core = load_model_file(os.path.join(ROOT, "model", "core.def"))
    eng.add_model(core)
    eng.add_model(load_model_file(os.path.join(ROOT, "model", "probe.def"), core=core))
    for name in PROBES:
        eng.add(load_pack(os.path.join(ROOT, "packs", "conformance-groups-" + name)))
    return eng


def small_engine(pack):
    eng = Engine()
    eng.load_model("module core\nversion 1\ndistribution public\nsource s\nkey uid string -\n")
    eng.load_model(MODEL)
    eng.load(HEAD + pack)
    return eng


class TestLists(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = probe_engine()

    def test_decode_gives_items_in_order(self):
        ent = self.e.decode(
            "conformance-groups-json",
            '{"id":"u","items":[{"name":"aa","subs":[{"v":1},{"v":2}]},{"name":"bb"}],"names":[],"data":{"nums":[3]}}',
        )
        items = ent.lists["probe.items"]
        self.assertEqual([it["probe.label"] for it in items], ["aa", "bb"])
        self.assertIsInstance(items[0], Item)
        self.assertEqual([s["probe.val"] for s in items[0].lists["probe.subs"]], [1, 2])
        self.assertNotIn("probe.subs", items[1].lists)             # an absent list
        self.assertEqual(ent.lists["probe.names"], [])              # present and empty
        self.assertNotIn("probe.ratios", ent.lists)
        self.assertEqual(ent.lists["probe.nums"][0].get("probe.val"), 3)
        self.assertNotIn("probe.items", ent.fields)

    def test_encode_from_a_built_entity(self):
        ent = Entity(fields={"uid": "u"}, lists={
            "probe.items": [Item(fields={"probe.label": "aa"}, lists={"probe.subs": [Item(fields={"probe.val": -1})]})],
            "probe.nums": [Item(fields={"probe.val": 3}), Item(fields={"probe.val": 270})],
        })
        self.assertEqual(
            self.e.encode("conformance-groups-json", ent).decode(),
            '{"id":"u","title":"NONE","items":[{"name":"aa","n":1,"kind":"item","subs":[{"v":-1}]}],"data":{"nums":[3,270]}}',
        )
        self.assertEqual(
            self.e.encode("conformance-groups-xml", ent).decode(),
            '<msg id="u"><body><item name="aa" k="i"><qty>1</qty><sub v="-1"/></item></body>'
            '<nums><n>3</n><n>270</n></nums></msg>',
        )
        # submessage items one occurrence each; a numeric `.` field packed
        self.assertEqual(
            self.e.encode("conformance-groups-protobuf", ent).decode(),
            "0a0175120c0a026161100120092a0210011a050a03038e02",
        )

    def test_model_keys_list_lists_and_item_keys(self):
        self.assertEqual(
            self.e.model_keys("conformance-groups-kinds"),
            ["uid", "probe.names[]", "probe.names[].probe.tag", "probe.items[]", "probe.items[].probe.label"],
        )
        keys = self.e.model_keys("conformance-groups-json")
        self.assertIn("probe.items[].probe.subs[]", keys)
        self.assertIn("probe.items[].probe.subs[].probe.val", keys)
        self.assertLess(keys.index("probe.items[]"), keys.index("probe.items[].probe.label"))

    def test_requires_a_list_needs_an_item(self):
        ent = Entity(fields={"uid": "u"}, lists={"probe.items": []})
        self.assertEqual(self.e.encode("conformance-groups-kinds", ent).decode(), '{"id":"u","shape":"bare"}')
        ent.lists["probe.items"].append(Item(fields={"probe.label": "a"}))
        self.assertEqual(
            self.e.encode("conformance-groups-kinds", ent).decode(), '{"id":"u","shape":"listed","items":[{"name":"a"}]}'
        )

    def test_derivations_and_context_do_not_reach_into_items(self):
        ent = self.e.decode("conformance-groups-json", '{"id":"u","items":[{"n":5}]}')
        self.e.complete(ent, {"probe.n": "5"})
        self.assertEqual(ent["probe.n_next"], 1005)
        self.assertEqual(ent.lists["probe.items"][0].fields, {"probe.qty": 5})

    def test_item_failures_name_the_item(self):
        with self.assertRaises(TransformDecodeFailure) as cm:
            self.e.decode("conformance-groups-json", '{"items":[{"n":1},{"subs":[{"v":"x"}]}]}')
        self.assertEqual([a[0] for a in cm.exception.absent], ["probe.items[1].probe.subs[0].probe.val"])
        with self.assertRaises(MalformedWire):
            self.e.decode("conformance-groups-json", '{"items":3}')

    def test_bits_items_of_variable_size(self):
        ent = self.e.decode("conformance-groups-bits-var", "0207020a0b09020c0d")
        self.assertEqual(
            [[s["probe.val"] for s in it.lists["probe.subs"]] for it in ent.lists["probe.items"]], [[10, 11], [12, 13]]
        )
        self.assertEqual(self.e.encode("conformance-groups-bits-var", ent).decode(), "0207020a0b09020c0d")
        with self.assertRaises(MalformedWire):
            self.e.decode("conformance-groups-bits-var", "0207020a")

    def test_bits_counts_on_encode(self):
        two = [Item(fields={"probe.val": 1}), Item(fields={"probe.val": 2})]
        ent = Entity(lists={"probe.nums": two})
        self.assertEqual(self.e.encode("conformance-groups-bits-msb", ent).decode(), "0012")
        for lists in ({}, {"probe.nums": two[:1]}, {"probe.nums": two, "probe.items": [Item()] * 4}):
            with self.assertRaises(TransformEncodeFailure):
                self.e.encode("conformance-groups-bits-msb", Entity(lists=lists))

    def test_protobuf_packed_and_unpacked(self):
        ent = self.e.decode("conformance-groups-protobuf", "1a0808030a020102080432020104")
        self.assertEqual([it["probe.val"] for it in ent.lists["probe.nums"]], [3, 1, 2, 4])
        self.assertEqual([it["probe.val"] for it in ent.lists["probe.deltas"]], [-1, 2])
        self.assertNotIn("probe.nums", self.e.decode("conformance-groups-protobuf", "1a020a00").lists)
        for bad in ("2a0300000000", "1005", "32020280"):
            with self.assertRaises(MalformedWire, msg=bad):
                self.e.decode("conformance-groups-protobuf", bad)


class TestGroupLoadChecks(unittest.TestCase):
    def test_lists_share_the_key_namespace(self):
        for extra in ("list a\n", "key rows int -\n", "list rows\n"):
            with self.assertRaises(DuplicateKey, msg=extra):
                parse_model_text(MODEL + extra)
        self.assertEqual(list(parse_model_text(MODEL).lists), ["rows", "cells"])

    def test_bad_directive(self):
        json = "wire json\nfield uid id string\n"
        bits = "wire bits\nword_bytes 1\nfield m.a 0:0:8 uint\n"
        body = "field m.a n int\nend\n"
        cases = [
            json + "group m.rows rows\nfield m.a n int\n",                        # no `end`
            json + "end\n",
            json + "kind k\ngroup m.rows rows\nwhen n 1\nend\n",
            json + "kind k\ngroup m.rows rows\nrequires uid\nend\n",
            json + "group m.rows rows\nkind k\nend\n",
            json + "group m.rows rows\nmap t 1 a\nend\n",
            json + "group m.rows rows\ntypemap F a\nend\n",
            json + "group m.rows rows count 2\n" + body,
            json + "field m.a . int\n",                                           # `.` outside a group
            json + "group m.rows rows\n" + body + "group m.rows more\n" + body,
            json + "group m.rows rows\n" + body + "kind k\ngroup m.rows more\n" + body,
            bits + "group m.rows 0:8 item 8\nfield m.a 0:0:8 uint\nend\n",        # no `count`
            bits + "group m.rows 0:16 item 8 count 0:8:8\nfield m.a 0:0:8 uint\nend\nfield m.a 0:16:8 uint\n",
            bits + "group m.rows 0:16 item 8 count 0:12:8\nfield m.a 0:0:8 uint\nend\n",
            bits + "group m.rows 0:16 item 8 count 0:8:8\nfield m.a 0:4:8 uint\nend\n",
            bits + "group m.rows 0:16 item 16 count 0:8:8\ngroup m.cells 0:8 item 8 count 2\n"
                   "field m.a 0:0:8 uint\nend\nend\n",
        ]
        for text in cases:
            with self.assertRaises(BadDirective, msg=text):
                small_engine(text)

    def test_declared_and_typed(self):
        json = "wire json\nfield uid id string\n"
        with self.assertRaises(UndeclaredKey):
            small_engine(json + "group m.nolist rows\nfield m.a n int\nend\n")
        with self.assertRaises(KeyTypeMismatch):
            small_engine(json + "group m.a rows\nfield m.b n string\nend\n")
        with self.assertRaises(KeyTypeMismatch):
            small_engine(json + "group m.rows rows\nfield m.cells n string\nend\n")
        with self.assertRaises(KeyTypeMismatch):
            small_engine(json + "group m.rows rows\nfield m.a n string\nend\n")

    def test_what_loads(self):
        json = "wire json\nfield uid id string\n"
        small_engine(json + "kind p\nwhen k 1\ngroup m.rows rows\nfield m.a n int\nend\n"
                            "kind q\nwhen k 2\nrequires m.rows\ngroup m.rows more\nfield m.a . int\nend\n")
        small_engine(json + "group m.rows rows\ngroup m.rows inner\nfield m.a n int via t\nend\nend\nmap t 1 2\n")
        eng = small_engine(
            "wire bits\nword_bytes 1\nfield m.a 0:0:8 uint\n"
            "group m.rows 0:16 item 16 count 0:8:8\ngroup m.cells 0:8 item 8 count 0:0:8\n"
            "field m.a 0:0:8 uint\nend\nend\n"
        )
        ent = eng.decode("x", "07020201020000")
        self.assertEqual([len(it.lists["m.cells"]) for it in ent.lists["m.rows"]], [2, 0])
        self.assertEqual(eng.encode("x", ent).decode(), "07020201020000")


if __name__ == "__main__":
    unittest.main()
