"""Tests of tools/gen/aplog2pack.py, ArduPilot DataFlash log messages.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_aplog2pack*.py'

`fixtures/aplog2pack/input/ardupilot/` is a small ArduPilot-like tree written for
these tests: log structure tables, `Write` calls, `#define` strings, a name that
two vehicles define differently and one that two libraries define differently,
and an `examples` directory the generator must not read. `expected/` is the tree a
run with `--commit` writes; after a deliberate change run once with
GT_UPDATE_GOLDEN=1 and review the diff.
"""
import support

import os
import shutil
import tempfile
import unittest

import aplog2pack as gen

FIXTURES = os.path.join(support.FIXTURES, "aplog2pack")
CORE_DEF = os.path.join(support.REPO, "model", "core.def")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.src = support.copy_tree(os.path.join(FIXTURES, "input", "ardupilot"), os.path.join(self.tmp, "ap"))
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "model"))
        shutil.copy(CORE_DEF, os.path.join(self.root, "model", "core.def"))

    def run_gen(self, *more):
        return support.run_main(gen.main, ["--ardupilot", self.src, "--out", self.root] + list(more))

    def first_run(self):
        status, out, err = self.run_gen("--commit", COMMIT, "--tag", "Test-0.0.0")
        self.assertEqual(status, 0, err)
        return out

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split("/")), encoding="utf-8") as fh:
            return fh.read()

    def test_golden(self):
        self.first_run()
        support.assert_same_tree(self, os.path.join(FIXTURES, "expected"), self.root, ignore=("model/core.def",))

    def test_packs_and_names(self):
        self.first_run()
        packs = sorted(d for d in os.listdir(os.path.join(self.root, "packs")) if d.startswith("ardupilot-log-"))
        self.assertEqual(packs, [
            "ardupilot-log-ahr2", "ardupilot-log-cam", "ardupilot-log-copter-ctun", "ardupilot-log-eahr",
            "ardupilot-log-fmt", "ardupilot-log-gps", "ardupilot-log-navx", "ardupilot-log-orgn",
            "ardupilot-log-plane-ctun", "ardupilot-log-pos", "ardupilot-log-sim", "ardupilot-log-trig",
            "ardupilot-log-wdog-alpha", "ardupilot-log-wdog-beta"])

    def test_layout(self):
        self.first_run()
        gps = self.read("packs/ardupilot-log-gps/pack.def")
        for line in ("field  aplog.gps_timeus  0:0:64  uint", "field  aplog.gps_hdop  0:80:16  twos",
                     "field  lat  0:96:32  sscale:1/10000000", "field  lon  0:128:32  sscale:1/10000000",
                     "field  aplog.gps_alt  0:160:32  twos", "field  aplog.gps_name  0:192:32  ascii"):
            self.assertIn(line, gps)
        navx = self.read("packs/ardupilot-log-navx/pack.def")
        self.assertIn("field  aplog.navx_arr_0  0:64:16  twos", navx)
        self.assertIn("field  aplog.navx_arr_31  0:560:16  twos", navx)
        self.assertIn("field  aplog.navx_txt  0:576:128  ascii", navx)
        self.assertIn("field  aplog.navx_q  0:704:64  f64", navx)
        orgn = self.read("packs/ardupilot-log-orgn/pack.def")
        self.assertIn("field  aplog.orgn_lat  0:64:32  twos", orgn)       # an origin: not bound

    def test_check_mode(self):
        self.first_run()
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 0, err)
        with open(os.path.join(self.root, "model", "aplog.def"), "a", encoding="utf-8") as fh:
            fh.write("# edited\n")
        status, _, err = self.run_gen("--check")
        self.assertEqual(status, 1)
        self.assertIn("model/aplog.def", err)

    def test_changed_source_is_refused(self):
        self.first_run()
        with open(os.path.join(self.src, "ArduPlane", "Log.cpp"), "a", encoding="utf-8") as fh:
            fh.write("// changed\n")
        status, _, err = self.run_gen()
        self.assertEqual(status, 1)
        self.assertIn("ArduPlane/Log.cpp: SHA-256", err)

    def test_bad_definition_is_refused(self):
        with open(os.path.join(self.src, "ArduCopter", "Log.cpp"), "a", encoding="utf-8") as fh:
            fh.write('{ LOG_X_MSG, sizeof(log_X), "XBAD", "Qf", "TimeUS", "s-", "F-" },\n')
        status, _, err = self.run_gen("--commit", COMMIT, "--tag", "Test-0.0.0")
        self.assertEqual(status, 1)
        self.assertIn("XBAD", err)
        self.assertIn("1 labels for 2 format characters", err)


if __name__ == "__main__":
    unittest.main()
