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


if __name__ == "__main__":
    unittest.main()
