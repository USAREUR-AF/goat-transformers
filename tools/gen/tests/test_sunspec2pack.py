"""Tests of tools/gen/sunspec2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_sunspec2pack*.py'

fixtures/sunspec2pack/input is a synthetic stand-in for sunspec/models and for
the file of sunspec/pysunspec2 that states the not-implemented values, written
for these tests: model 1 of fixed length (a string, a fixed and a dynamic scale
factor, an accumulator, a float, a uint64, an ipv6addr split in two, a pad and
a fixed sub-group); model 305 with a position at a fixed scale factor of -7;
model 160 with a group counted by a point of the fixed part; model 701 with a
block repeated to the end of the model and a group after it; model 9 with a
counted group whose items hold a repeated group. fixtures/sunspec2pack/expected
is the tree the run writes into the checkout.
"""
import json
import os
import shutil
import tempfile
import unittest

import support

S = support.load_script("sunspec2pack.py")
FIXTURE = os.path.join(support.FIXTURES, "sunspec2pack")
INPUTS = ("model/core.def",)
COMMITS = ["--commit-models", "1" * 40, "--ref-models", "v0-test",
           "--commit-pysunspec2", "2" * 40, "--ref-pysunspec2", "v0-test"]


class SunSpecTest(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sunspec2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.src = support.copy_tree(os.path.join(FIXTURE, "input"), os.path.join(self.work, "src"))
        self.gt = os.path.join(self.work, "gt")
        os.makedirs(os.path.join(self.gt, "model"))
        shutil.copy(os.path.join(support.REPO, "model", "core.def"), os.path.join(self.gt, "model", "core.def"))

    def run_gen(self, *extra):
        return support.run_main(S.main, ["--models", os.path.join(self.src, "models"),
                                         "--pysunspec2", os.path.join(self.src, "pysunspec2"),
                                         "--out", self.gt] + list(extra))

    def read(self, *parts):
        with open(os.path.join(self.gt, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_run_writes_the_expected_tree(self):
        status, out, err = self.run_gen(*COMMITS)
        self.assertEqual((status, err), (0, ""))
        self.assertIn("packs           5 (2 of fixed length, 1 with a counted group)", out)
        self.assertIn("core bindings   2", out)
        self.assertIn("vectors         12 checked", out)
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.gt, ignore=INPUTS)

    def test_lines_of_the_packs(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        basic = self.read("packs", "sunspec-1", "pack.def")
        for line in ("when      0:0:16 1\nwhen      0:16:16 28\n",
                     "field     sunspec1.basic_mn 0:32:64 ascii\n",
                     "field     sunspec1.basic_temp 0:96:16 sscale:1/10 absent 32768\n",
                     "field     sunspec1.basic_w 0:112:16 uint absent 65535\n",
                     "field     sunspec1.basic_wh 0:144:32 uint absent 0\n",
                     "field     sunspec1.basic_hz 0:176:32 f32 absent 2143289344\n",
                     "field     sunspec1.basic_big 0:208:64 uint absent 18446744073709551615\n",
                     "field     sunspec1.basic_addr_02 0:336:64 uint absent 0\n",
                     "field     sunspec1.basic_gain 0:416:16 uiscale:100 absent 65535\n",
                     "field     sunspec1.basic_hdr_evt 0:448:32 uint absent 4294967295\n",
                     "const     0:400:16 0\n"):
            self.assertIn(line, basic)
        self.assertIn('key   basic_w  int  -  "model 1, point W, unscaled (scale factor point W_SF)"',
                      self.read("model", "sunspec1.def"))
        gps = self.read("packs", "sunspec-305", "pack.def")
        self.assertIn("field     lat 0:128:32 sscale:1/10000000 absent 2147483648\n", gps)
        self.assertIn("field     lon 0:160:32 sscale:1/10000000 absent 2147483648\n", gps)
        counted = self.read("packs", "sunspec-160", "pack.def")
        self.assertIn("field     sunspec160.l 0:16:16 uint\n", counted)
        self.assertIn("group     sunspec160.counted_module 0:64 item 48 count 0:48:16\n", counted)
        self.assertNotIn("counted_n", counted)
        self.assertNotIn("when      0:16:16", counted)
        md = self.read("packs", "sunspec-701", "pack.md")
        self.assertIn("| curve | a block repeated to the end of the model", md)
        self.assertIn("| tail | follows a part of variable length |", md)
        self.assertIn("count `M`", self.read("packs", "sunspec-9", "pack.md"))
        x = json.loads(self.read("packs", "sunspec-305", "vectors", "x-01-gps-to-geojson.json"))
        self.assertEqual(x["model"], {"@kind": "gps", "lat": "47.397742", "lon": "8.545594"})

    def test_check_after_a_run_is_ok_and_writes_nothing(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        before = support.tree(self.work)
        status, out, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        self.assertIn("self-check      ok", out)
        self.assertEqual(support.tree(self.work), before)

    def test_a_changed_input_is_refused(self):
        self.assertEqual(self.run_gen(*COMMITS)[0], 0)
        with open(os.path.join(self.src, "models", "json", "model_1.json"), "a", encoding="utf-8") as fh:
            fh.write("\n")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("models/json/model_1.json does not match the SHA-256", err)

    def test_unimplemented_values_and_refusals(self):
        with open(os.path.join(self.src, "pysunspec2", "sunspec2", "mb.py"), encoding="utf-8") as fh:
            u = S.unimpl_values(fh.read())
        self.assertEqual(u["SUNS_UNIMPL_EUI48"], (1 << 48) - 1)
        self.assertEqual(u["SUNS_UNIMPL_INT16"], -32768)
        with self.assertRaises(S.GenError):
            S.unimpl_values("X = 1\n")
        status, _, err = self.run_gen("--commit-models", "1" * 40)
        self.assertEqual(status, 1)
        self.assertIn("go together", err)
        f = os.path.join(self.src, "models", "json", "model_9.json")
        with open(f, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["group"]["points"][2]["type"] = "uint128"
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        status, _, err = self.run_gen(*COMMITS)
        self.assertEqual(status, 1)
        self.assertIn("point type uint128", err)


if __name__ == "__main__":
    unittest.main()
