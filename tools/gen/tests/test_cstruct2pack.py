"""Tests of tools/gen/cstruct2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_cstruct2pack*.py'

fixtures/cstruct2pack/input is synthetic, written for these tests: a config
(`cdemo.json`) and two headers. `inc/consts.h` holds constants, one defined
under a conditional, and an enum; `inc/demo.h` names four messages by a
`#define` with a trailing comment, packs with macros the config maps, and
declares a nested struct, a position with a three-element `lla`, a status
with an array longer than the unroll limit, a two-dimensional array and an
int64, a struct of bit-fields (skipped by the config) and a function
prototype (ignored). fixtures/cstruct2pack/expected is the tree the run
writes.

Packet mode: `cpacket.json` and `inc/packet.h` (under `#pragma pack(1)`, reset
by `#pragma pack()`): a header struct with a flexible last member, an item type
from an enum, an item count and two item structs.
fixtures/cstruct2pack/expected-packet is the tree that run writes.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

C = support.load_script("cstruct2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "cstruct2pack")
INPUTS = ("model/core.def",)
COMMIT = ["--commit", "3" * 40, "--ref", "v0-test"]


class CStructTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="cstruct2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.inp = support.copy_tree(os.path.join(FIXTURE, "input"), os.path.join(self.work, "in"))
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(os.path.join(self.gt, "model"))
        shutil.copy(os.path.join(support.REPO, "model", "core.def"), os.path.join(self.gt, "model", "core.def"))

    def run_gen(self, *extra):
        return support.run_main(C.main, ["--config", os.path.join(self.inp, "cdemo.json"),
                                         "--src", os.path.join(self.inp, "src"), "--out", self.gt] + list(extra))

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def edit(self, rel, old, new):
        path = os.path.join(self.inp, "src", *rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn(old, text)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace(old, new))

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen(*COMMIT)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("2 messages in 2 packs (2 skipped), 17 keys and lists, 8 vectors checked", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_layout_and_bindings(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        nav = self.read("packs", "cdemo-nav", "pack.def")
        for line in ("bit_order     lsb\n", "when   0:0:8  165\n", "when      0:8:8  1\nwhen      0:16:16  57\n",
                     "requires  lat lon\n", "field  cdemo.pos_t_time_tow  0:64:64  f64\n",
                     "field  lat  0:128:64  f64\n", "field  hae  0:256:64  f64\n",
                     "field  cdemo.pos_t_name  0:416:64  ascii\n", "field  cdemo.pos_t_mode  0:480:8  uint\n"):
            self.assertIn(line, nav)
        misc = self.read("packs", "cdemo-misc", "pack.def")
        self.assertIn("group  cdemo.stat_t_samples  0:48  item 16  count 70\n", misc)
        self.assertIn("field  cdemo.stat_t_flags_1_2  0:1208:8  uint\n", misc)
        self.assertIn("field  cdemo.stat_t_big  0:1216:64  twos\n", misc)
        md = self.read("packs", "cdemo-misc", "pack.md")
        self.assertIn("| `DID_BAD` (id 3, `bad_t`) | its struct holds bit-fields |", md)
        prov = self.read("packs", "cdemo-nav", "PROVENANCE.md")
        self.assertIn("`LICENSE`, quoted whole:\n\n```\nSynthetic stand-in", prov)
        x = json.loads(self.read("packs", "geojson", "vectors", "gen-geojson-to-cdemo-nav-pos.json"))
        self.assertEqual((x["from"], x["to"]), ("geojson", "cdemo-nav"))

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertEqual(support.tree(self.work), before)

    def test_a_changed_header_is_refused(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        self.edit("inc/demo.h", "uint8_t     mode;", "uint16_t    mode;")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("inc/demo.h", err)

    def test_unknown_constructs_stop_the_run(self):
        self.edit("inc/demo.h", "flags[2][3]", "flags[ROWS][3]")
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("defined under a conditional", err)

    def test_a_skip_removed_stops_the_run(self):
        path = os.path.join(self.inp, "cdemo.json")
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        del cfg["skip"]["DID_BAD"]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh)
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("DID_BAD", err)

    def test_a_pointer_member_stops_the_run(self):
        self.edit("inc/demo.h", "uint8_t     mode;", "uint8_t    *mode;")
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("pos_t", err)


class CStructPacketTest(unittest.TestCase):
    setUp = CStructTest.setUp
    read = CStructTest.read
    edit = CStructTest.edit

    def run_gen(self, *extra):
        return support.run_main(C.main, ["--config", os.path.join(self.inp, "cpacket.json"),
                                         "--src", os.path.join(self.inp, "src"), "--out", self.gt] + list(extra))

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen(*COMMIT)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("2 messages in 1 packs (0 skipped), 10 keys and lists, 5 vectors checked", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected-packet"), self.gt, ignore=INPUTS)

    def test_layout_under_pragma_pack_1(self):
        self.assertEqual(self.run_gen(*COMMIT)[0], 0)
        pack = self.read("packs", "cpacket-data", "pack.def")
        for line in ("field  cpacket.demo_packet_length  0:8:16  uint\n",
                     "field  cpacket.demo_packet_rsvd_1  0:56:8  uint\n",
                     "kind      wide\nwhen      0:40:8  1\n",
                     "group  cpacket.demo_packet_wide  0:64  item 40  count 0:24:16\n",
                     "group  cpacket.demo_packet_narrow  0:64  item 40  count 0:24:16\n",
                     "  field  cpacket.narrow_item_label  0:16:24  ascii\n"):
            self.assertIn(line, pack)
        self.assertNotIn("demo_packet_count", pack)
        v = json.loads(self.read("packs", "cpacket-data", "vectors", "gen-rt-wide.json"))
        data = bytes.fromhex(v["input"])
        self.assertEqual(len(data), 8 + 2 * 5)
        self.assertEqual(int.from_bytes(data[1:3], "little"), len(data))
        self.assertEqual((int.from_bytes(data[3:5], "little"), data[5]), (2, 1))

    def test_an_unknown_pragma_pack_stops_the_run(self):
        self.edit("inc/packet.h", "#pragma pack(1)", "#pragma pack(show)")
        status, _, err = self.run_gen(*COMMIT)
        self.assertEqual(status, 1)
        self.assertIn("a form of pack this reader does not know", err)

    def test_config_errors_stop_the_run(self):
        path = os.path.join(self.inp, "cpacket.json")
        with open(path, encoding="utf-8") as fh:
            base = json.load(fh)
        for change, message in (
                (lambda c: c["packet"]["kinds"][0].update(id="kItemNone"), "defines no constant kItemNone"),
                (lambda c: c["packet"].update(tail="rsvd"), "is not the last member"),
                (lambda c: c["packet"].update(count="rsvd"), "is not an unsigned scalar"),
                (lambda c: c["packet"]["kinds"][1].update(type="ItemType"), "has no size the C standard fixes")):
            cfg = json.loads(json.dumps(base))
            change(cfg)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            status, _, err = self.run_gen(*COMMIT)
            self.assertEqual(status, 1, message)
            self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
