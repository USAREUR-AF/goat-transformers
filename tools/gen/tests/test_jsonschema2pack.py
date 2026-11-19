"""Tests of tools/gen/jsonschema2pack.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_jsonschema2pack*.py'

The fixture under fixtures/jsonschema2pack/input is a synthetic schema set
written for these tests: a YAML message (`station.yaml`) and a JSON message
(`alarm.json`) that refer to shared definitions by `$id` and by relative path
(`common.json`), a GeoJSON Feature message (`site.json`) whose geometry
reference is left to the wire, a two-module model, a geojson format with one
vector to cross from, and a names file with one pinned name.
fixtures/jsonschema2pack/expected is the tree the generator writes for it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import support
import jsonschema2pack as j

FIXTURE = os.path.join(support.FIXTURES, "jsonschema2pack")
# the separator of --cross before its context keys, written apart from the text around it
CONTEXT_SEP = "@"
INPUTS = ("schema/", "model/core.def", "model/track.def", "packs/note-geo/pack.def",
          "packs/note-geo/vectors/01-note.json")


class Workspace(unittest.TestCase):
    """A temporary checkout: the fixture input copied to `out/`, the generator
    writes into the same tree (as into a real checkout)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="jsonschema2pack-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.out = support.copy_tree(os.path.join(FIXTURE, "input"), self.path("out"))

    def path(self, *parts):
        return os.path.join(self.work, *parts)

    def json_argv(self, *extra):
        s = self.path("out", "schema")
        return [
            "--schema", os.path.join(s, "common.json"), os.path.join(s, "station.yaml"),
            os.path.join(s, "alarm.json"),
            "--message", "Alarm=" + os.path.join(s, "alarm.json"),
            "--message", "StationReport=" + os.path.join(s, "station.yaml"),
            "--kind-when", "Alarm:alarmId=present", "--kind-when", "StationReport:stationId=present",
            "--map", "StationReport:stationId=uid", "--map", "StationReport:observedAt=time_ms",
            "--map", "StationReport:position.lat=lat", "--map", "StationReport:position.lon=lon",
            "--map", "StationReport:speed=speed_ms", "--map", "Alarm:raisedAt=time_ms",
            "--format", "fieldnet", "--module", "fieldnet", "--title", "Fieldnet synthetic JSON test schema",
            "--license", "written for the tests", "--source", "A second source line, given on the command line",
            "--out", self.out, "--model-dir", self.path("out", "model"),
            "--names-file", self.path("out", "names", "fieldnet.json"),
            "--cross", "%s=%s:input" % (
                self.path("out", "packs", "note-geo", "pack.def"),
                self.path("out", "packs", "note-geo", "vectors", "01-note.json")) + CONTEXT_SEP +
            "fieldnet.station=0f1e2d3c-4b5a-4968-8776-655443322110",
        ] + list(extra)

    def geo_argv(self, *extra):
        s = self.path("out", "schema")
        return [
            "--schema", os.path.join(s, "site.json"), "--opaque", "https://geojson.example/schema/",
            "--message", "Site=" + os.path.join(s, "site.json"),
            "--map", "Site:id=uid", "--map", "Site:geometry.lon=lon", "--map", "Site:geometry.lat=lat",
            "--wire", "geojson", "--top-level-members", "id",
            "--format", "sitegeo", "--module", "sitegeo", "--title", "Site synthetic GeoJSON test schema",
            "--license", "written for the tests", "--out", self.out, "--model-dir", self.path("out", "model"),
            "--names-file", self.path("out", "names", "sitegeo.json"),
            "--cross", "%s=%s:input" % (self.path("out", "packs", "note-geo", "pack.def"),
                                        self.path("out", "packs", "note-geo", "vectors", "01-note.json")),
        ] + list(extra)

    def run_both(self, *extra):
        a = support.run_main(j.main, self.json_argv(*extra))
        b = support.run_main(j.main, self.geo_argv(*extra))
        return a, b


class GoldenTest(Workspace):
    def test_fixture_output_matches_the_expected_tree(self):
        (sa, _, ea), (sb, _, eb) = self.run_both()
        self.assertEqual((sa, sb), (0, 0), ea + eb)
        self.assertEqual((ea, eb), ("", ""))
        support.assert_same_tree(self, os.path.join(FIXTURE, "expected"), self.out, ignore=INPUTS)

    def test_second_run_over_its_own_output_changes_nothing(self):
        self.run_both()
        first = support.tree(self.out)
        self.run_both()
        self.assertEqual(support.tree(self.out), first)

    def test_pinned_name_is_kept(self):
        self.run_both()
        with open(self.path("out", "packs", "fieldnet", "pack.def"), encoding="utf-8") as fh:
            self.assertIn("field  fieldnet.station  stationId  string", fh.read())

    def test_summary_on_stdout(self):
        status, out, _ = support.run_main(j.main, self.json_argv())
        summary = json.loads(out)
        self.assertEqual(status, 0)
        self.assertEqual(summary["kinds"], 2)
        self.assertEqual(summary["cross"], ["gen-note-geo-to-fieldnet.json"])

    def test_a_generated_vector_no_longer_written_is_removed(self):
        self.run_both()
        stale = self.path("out", "packs", "fieldnet", "vectors", "gen-009-old-roundtrip.json")
        kept = self.path("out", "packs", "fieldnet", "vectors", "01-hand-written.json")
        for p in (stale, kept):
            with open(p, "w") as fh:
                fh.write("{}\n")
        self.assertEqual(support.run_main(j.main, self.json_argv())[0], 0)
        self.assertFalse(os.path.exists(stale))
        self.assertTrue(os.path.exists(kept))

    def test_output_does_not_depend_on_the_hash_seed(self):
        trees = []
        for seed in ("1", "2"):
            shutil.rmtree(self.out)
            support.copy_tree(os.path.join(FIXTURE, "input"), self.out)
            done = subprocess.run([sys.executable, os.path.join(support.GEN, "jsonschema2pack.py")] + self.json_argv(),
                                  env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE="1"),
                                  capture_output=True)
            self.assertEqual(done.returncode, 0, done.stderr.decode())
            trees.append(support.tree(self.out))
        self.assertEqual(trees[0], trees[1])

    def test_an_unresolved_reference_is_a_named_error(self):
        argv = self.json_argv()
        i = argv.index(os.path.join(self.path("out", "schema"), "common.json"))
        del argv[i]
        status, _, err = support.run_main(j.main, argv)
        self.assertEqual(status, 1)
        self.assertIn("names no file given here", err)


class CheckModeTest(Workspace):
    def test_check_on_fresh_output_passes_and_writes_nothing(self):
        self.run_both()
        before = support.tree(self.work)
        (sa, oa, ea), (sb, ob, eb) = self.run_both("--check")
        self.assertEqual((sa, sb), (0, 0), ea + eb)
        self.assertIn("--check: ok", ea)
        self.assertIn("--check: ok", eb)
        self.assertEqual(oa + ob, "")
        self.assertEqual(support.tree(self.work), before)

    def test_check_names_a_changed_file_and_leaves_the_tree_alone(self):
        self.run_both()
        target = self.path("out", "packs", "fieldnet", "pack.def")
        with open(target, "rb") as fh:
            data = fh.read()
        with open(target, "wb") as fh:
            fh.write(data.replace(b"kind      alarm", b"kind      alarn"))
        before = support.tree(self.work)
        status, _, err = support.run_main(j.main, self.json_argv("--check"))
        self.assertEqual(status, 1)
        self.assertIn("packs/fieldnet/pack.def differs at line", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_on_a_tree_without_output_reports_every_file_and_creates_none(self):
        before = support.tree(self.work)
        status, _, err = support.run_main(j.main, self.json_argv("--check"))
        self.assertEqual(status, 1)
        for rel in ("model/fieldnet.def", "packs/fieldnet/pack.def", "packs/fieldnet/pack.md",
                    "packs/fieldnet/vectors/gen-001-alarm-roundtrip.json",
                    "packs/note-geo/vectors/gen-note-geo-to-fieldnet.json"):
            self.assertIn("%s is missing" % rel, err)
        self.assertIn("names/fieldnet.json differs", err)
        self.assertEqual(support.tree(self.work), before)

    def test_check_reports_a_stale_generated_vector(self):
        self.run_both()
        stale = self.path("out", "packs", "fieldnet", "vectors", "gen-009-old-roundtrip.json")
        shutil.copy(self.path("out", "packs", "fieldnet", "vectors", "gen-001-alarm-roundtrip.json"), stale)
        status, _, err = support.run_main(j.main, self.json_argv("--check"))
        self.assertEqual(status, 1)
        self.assertIn("gen-009-old-roundtrip.json is not written by the generator and would be removed", err)
        self.assertTrue(os.path.exists(stale))

    def test_check_covers_a_names_file_outside_the_output_directory(self):
        names = self.path("elsewhere", "fieldnet.json")
        os.makedirs(os.path.dirname(names))
        shutil.copy(self.path("out", "names", "fieldnet.json"), names)
        argv = self.json_argv()
        argv[argv.index("--names-file") + 1] = names
        self.assertEqual(support.run_main(j.main, argv)[0], 0)
        with open(names, "a") as fh:
            fh.write(" ")
        status, _, err = support.run_main(j.main, argv + ["--check"])
        self.assertEqual(status, 1)
        self.assertIn("jsonschema2pack (names file): --check: fieldnet.json differs", err)


if __name__ == "__main__":
    unittest.main()
