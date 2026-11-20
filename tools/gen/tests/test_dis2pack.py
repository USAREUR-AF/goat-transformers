"""Tests of tools/gen/dis2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_dis2pack*.py'

`fixtures/dis2pack/input/` is a small pair of trees written for these tests:
`xmlpg/` in the shape of the open-dis xmlpg repository (a PDU description with
a case for each rule) and `opendis/` in the shape of open-dis-python (the PDU
type annotations and the decoder table).
`input/tools/gen/sources/dis-PROVENANCE.md` states the SHA-256 of each file.
After an edit of a fixture file, rewrite that table with
`--commit-xmlpg 0123456789abcdef0123456789abcdef01234567 --ref-xmlpg fixture
--commit-opendis 89abcdef0123456789abcdef0123456789abcdef --ref-opendis fixture`
into a scratch directory and copy it back, then run once with
GT_UPDATE_GOLDEN=1 and review the diff of `expected/`.
"""
import support

import json
import os
import tempfile
import unittest

import dis2pack as gen
import gtcheck

FIXTURE = os.path.join(support.FIXTURES, "dis2pack")
INPUT = os.path.join(FIXTURE, "input")
EXPECTED = os.path.join(FIXTURE, "expected")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
EXCLUDE = ["--exclude", "SkippedPdu=a reason given on the command line"]


class DisCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.xmlpg = support.copy_tree(os.path.join(INPUT, "xmlpg"), os.path.join(self.tmp, "xmlpg"))
        self.opendis = support.copy_tree(os.path.join(INPUT, "opendis"), os.path.join(self.tmp, "opendis"))

    def make_root(self):
        root = os.path.join(self.tmp, "root")
        support.copy_tree(os.path.join(INPUT, "tools"), os.path.join(root, "tools"))
        return root

    def run_gen(self, root, *more):
        return support.run_main(gen.main, ["--xmlpg", self.xmlpg, "--opendis", self.opendis, "--out", root,
                                           "--core-def", CORE_DEF] + list(more))

    def generated(self):
        root = self.make_root()
        status, out, err = self.run_gen(root, *EXCLUDE)
        self.assertEqual((status, err), (0, ""))
        return root

    def text(self, root, *path):
        with open(os.path.join(root, *path), encoding="utf-8") as fh:
            return fh.read()


class GoldenTree(DisCase):
    def test_fixture_gives_the_expected_tree(self):
        root = self.make_root()
        status, out, err = self.run_gen(root, *EXCLUDE)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("self-check      ok", out)
        support.assert_same_tree(self, EXPECTED, root, ignore=("tools/",))

    def test_second_run_and_check_mode_change_nothing(self):
        root = self.generated()
        first = support.tree(root)
        status, _, err = self.run_gen(root, "--check", *EXCLUDE)
        self.assertEqual(status, 0, err)
        self.assertIn("--check: ok", err)
        self.assertEqual(self.run_gen(root, *EXCLUDE)[0], 0)
        self.assertEqual(support.tree(root), first)

    def test_a_changed_source_is_refused(self):
        with open(os.path.join(self.xmlpg, gen.XML_FILE), "a", encoding="utf-8") as fh:
            fh.write("\n")
        root = self.make_root()
        status, _, err = self.run_gen(root, *EXCLUDE)
        self.assertEqual(status, 1, err)
        self.assertIn("does not match the SHA-256", err)
        self.assertFalse(os.path.exists(os.path.join(root, "packs")))

    def test_an_entity_declaration_is_refused(self):
        path = os.path.join(self.xmlpg, gen.XML_FILE)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("<classes>", '<!DOCTYPE c [<!ENTITY e "x">]>\n<classes>', 1))
        with self.assertRaises(gen.GenError):
            gen.Source(self.xmlpg, self.opendis)

    def test_a_malformed_or_unknown_exclusion_is_refused(self):
        for bad in ("SkippedPdu", "NoSuchPdu=why", "Ident=not a pdu"):
            status, _, err = self.run_gen(self.make_root(), "--exclude", bad)
            self.assertEqual(status, 1, bad)


class Layout(DisCase):
    def setUp(self):
        super().setUp()
        self.root = self.generated()
        self.pdef = self.text(self.root, "packs", "dis7", "pack.def")
        self.md = self.text(self.root, "packs", "dis7", "pack.md")

    def test_header_is_big_endian_and_selects_the_kind(self):
        self.assertIn("bit_order     msb\n", self.pdef)
        self.assertIn("when   0:0:8 7\n", self.pdef)
        self.assertIn("field  dis7.header_timestamp 0:32:32 uint\n", self.pdef)
        self.assertIn("kind      ping\nwhen      0:16:8 2\nwhen      0:64:16 34\n", self.pdef)

    def test_records_lists_text_and_types(self):
        for line in ("dis7.ping_from_num 0:128:16 uint", "dis7.ping_token 0:144:64 uint",
                     "dis7.ping_level 0:208:32 f32", "dis7.ping_delta 0:240:8 twos",
                     "dis7.ping_pad_03 0:264:8 uint", "dis7.track_state_mark 0:152:48 ascii",
                     "dis7.track_state_place_z 0:328:64 f64", "dis7.track_state_spin_02 0:424:32 twos"):
            self.assertIn("field     " + line + "\n", self.pdef)

    def test_a_counted_list_at_the_end_is_a_group(self):
        self.assertIn("kind      track_state\nwhen      0:16:8 1\nrequires", self.pdef)
        self.assertIn("field     dis7.pdu_length 0:64:16 uint\n", self.pdef)
        self.assertIn("group     dis7.track_state_parts 0:456 item 64 count 0:144:8\n"
                      "  field   dis7.track_state_parts_kind 0:0:8 uint\n"
                      "  field   dis7.track_state_parts_value 0:8:32 f32\n", self.pdef)
        self.assertNotIn("number_of_parts", self.pdef)          # the count is the group's locator
        module = self.text(self.root, "model", "dis7.def")
        self.assertIn("list  track_state_parts", module)

    def test_what_is_not_built(self):
        for row in ("| FastTrackStatePdu | 1 | the type source gives type 1 to TrackStatePdu as well",
                    "| TwoListsPdu | 3 | 2 counted lists (`as`, `bs`)",
                    "| SkippedPdu | 4 | a reason given on the command line |"):
            self.assertIn(row, self.md)
        self.assertIn("gives no PDU type: UnnumberedPdu.", self.md)
        self.assertIn("ECEF to geodetic", self.md.replace("from ECEF to geodetic", "ECEF to geodetic"))

    def test_vectors_decode_through_the_pack(self):
        model = gtcheck.Model()
        model.add(self.text(support.REPO, "model", "core.def"), CORE_DEF)
        model.add(self.text(self.root, "model", "dis7.def"), "dis7")
        pack = gtcheck.load_pack(self.pdef, model, "dis7")
        vdir = os.path.join(self.root, "packs", "dis7", "vectors")
        names = sorted(os.listdir(vdir))
        self.assertEqual(names, ["rt-01-track_state-no-items.json", "rt-01-track_state.json", "rt-02-ping.json"])
        for name in names:
            vec = json.loads(self.text(vdir, name))
            kind, ent, lists = gen.decode(pack, bytes.fromhex(vec["input"]))
            self.assertEqual(kind, vec["model"]["@kind"], name)
            self.assertEqual(gen.encode(pack, kind, ent, lists).hex(), vec["expect"], name)
        two = json.loads(self.text(vdir, "rt-01-track_state.json"))
        data = bytes.fromhex(two["input"])
        self.assertEqual(int.from_bytes(data[8:10], "big"), len(data))        # the length field, in bytes
        self.assertEqual(len(data), 57 + 2 * 8)


class Names(unittest.TestCase):
    def test_snake_case_keys(self):
        self.assertEqual(gen.snake("entityLinearVelocity"), "entity_linear_velocity")
        self.assertEqual(gen.snake("recordIDs"), "record_ids")
        self.assertEqual(gen.snake("exerciseID"), "exercise_id")
        self.assertEqual(gen.snake("pduType"), "pdu_type")


if __name__ == "__main__":
    unittest.main()
