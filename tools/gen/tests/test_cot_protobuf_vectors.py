"""Tests of tools/gen/cot-protobuf-vectors.py.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_cot_protobuf_vectors*.py'

The script writes the ten hand-written vectors of pack cot-protobuf from the
packs of the repository. The tests run it against the repository itself, in
check mode, and against a copy of the files it reads.
"""
import support

import json
import os
import shutil
import tempfile
import unittest

import proto2pack as p2p

script = support.load_script("cot-protobuf-vectors.py")

WRITTEN = ["packs/cot-protobuf/vectors/%s.json" % name for name, _, _, _ in script.CASES] + [
    "packs/cot-xml/vectors/19-full-event-to-cot-protobuf.json",
    "packs/geojson/vectors/90-to-cot-protobuf-no-position.json"]
READ = ["packs/cot-protobuf/pack.def", "packs/cot-xml/pack.def", "packs/geojson/pack.def",
        "packs/cot-xml/vectors/05-full-event-roundtrip.json"]


def repo_text(rel):
    with open(os.path.join(support.REPO, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


class RepositoryTest(unittest.TestCase):
    def test_the_committed_vectors_are_what_the_script_writes(self):
        status, _, err = support.run_main(script.main, ["--out", support.REPO, "--check"])
        self.assertEqual(status, 0, err)
        self.assertIn("cot-protobuf-vectors: --check: ok, 12 file(s)", err)

    def test_the_default_output_directory_is_the_repository(self):
        self.assertEqual(script.REPO, support.REPO)
        status, _, err = support.run_main(script.main, ["--check"])
        self.assertEqual(status, 0, err)


class CopyTest(unittest.TestCase):
    """A copy of what the script reads and writes: the model modules and three packs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cot-protobuf-vectors-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        support.copy_tree(os.path.join(support.REPO, "model"), os.path.join(self.tmp, "model"))
        for rel in READ + WRITTEN:
            self.write(rel, repo_text(rel))

    def path(self, rel):
        return os.path.join(self.tmp, *rel.split("/"))

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def test_a_run_writes_the_ten_committed_files_byte_for_byte(self):
        for rel in WRITTEN:
            os.remove(self.path(rel))
        status, _, err = support.run_main(script.main, ["--out", self.tmp])
        self.assertEqual(status, 0, err)
        for rel in WRITTEN:
            self.assertEqual(self.read(rel), repo_text(rel), rel)

    def test_the_checkout_may_be_given_as_a_positional_argument(self):
        status, _, err = support.run_main(script.main, [self.tmp, "--check"])
        self.assertEqual(status, 0, err)

    def test_check_fails_and_names_a_vector_that_was_changed_and_does_not_restore_it(self):
        rel = "packs/cot-protobuf/vectors/03-full-message-roundtrip.json"
        changed = self.read(rel).replace("GATOR", "GATER", 1)
        self.assertNotEqual(changed, repo_text(rel))
        self.write(rel, changed)
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 1)
        self.assertIn("cot-protobuf-vectors: --check: %s differs" % rel, err)
        self.assertEqual(self.read(rel), changed)

    def test_check_reports_a_vector_that_is_missing_and_writes_nothing(self):
        rel = "packs/geojson/vectors/90-to-cot-protobuf-no-position.json"
        os.remove(self.path(rel))
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 1)
        self.assertIn("%s is missing" % rel, err)
        self.assertFalse(os.path.exists(self.path(rel)))

    def test_a_pack_that_changed_changes_what_check_expects(self):
        rel = "packs/cot-protobuf/pack.def"
        lines = [ln for ln in self.read(rel).split("\n") if ln.split()[:2] != ["field", "takproto.cot_event_how"]]
        self.write(rel, "\n".join(lines))
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 1)
        # vector 03 states every decoded key in `model`; the raw key of `how` is no longer one
        self.assertIn("packs/cot-protobuf/vectors/03-full-message-roundtrip.json differs", err)
        self.assertNotIn("01-event-to-cot-xml.json", err)

    def test_a_pack_that_no_longer_decodes_a_key_a_vector_states_is_refused_in_one_line(self):
        rel = "packs/cot-protobuf/pack.def"
        lines = [ln for ln in self.read(rel).split("\n") if ln.split()[:2] != ["field", "callsign"]]
        self.write(rel, "\n".join(lines))
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 1)
        self.assertEqual(err, "cot-protobuf-vectors: vector 01-event-to-cot-xml: the pack does not decode callsign\n")

    def test_a_model_module_with_a_uses_line_loads(self):
        # the model directory holds a module with a `uses` line (engine-spec 0.8); every module must load
        with_uses = [name for name in sorted(os.listdir(self.path("model")))
                     if any(line.split()[:1] == ["uses"] for line in self.read("model/" + name).split("\n"))]
        self.assertTrue(with_uses, "no module of model/ has a `uses` line")
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 0, err)

    def test_a_pack_that_does_not_load_is_one_line_with_file_and_line(self):
        rel = "packs/cot-protobuf/pack.def"
        self.write(rel, self.read(rel).replace("field  uid ", "field  owner ", 1))
        status, _, err = support.run_main(script.main, ["--out", self.tmp, "--check"])
        self.assertEqual(status, 1)
        self.assertRegex(err, r"^cot-protobuf-vectors: packs/cot-protobuf/pack\.def:\d+: undeclared-key: ")
        self.assertEqual(len(err.strip().split("\n")), 1)

    def test_a_missing_pack_is_one_line(self):
        os.remove(self.path("packs/geojson/pack.def"))
        status, _, err = support.run_main(script.main, ["--out", self.tmp])
        self.assertEqual(status, 1)
        self.assertIn("pack.def", err)
        self.assertEqual(len(err.strip().split("\n")), 1)


class VectorContentTest(unittest.TestCase):
    """Facts of the committed vectors, stated by hand from the trees in the script."""

    def vector(self, rel):
        return json.loads(repo_text(rel))

    def test_the_event_message_starts_with_field_2_and_holds_the_type_first(self):
        vec = self.vector("packs/cot-protobuf/vectors/01-event-to-cot-xml.json")
        # field 2 (cotEvent), length-delimited: tag 12; inside, field 1 "a-f-G-U-C": 0a 09 ...
        self.assertTrue(vec["input"].startswith("12"))
        self.assertIn("0a09" + "a-f-G-U-C".encode().hex(), vec["input"])
        self.assertEqual(vec["model"]["@kind"], "cot_event")
        self.assertEqual(vec["model"]["time_ms"], "1614456000000")
        self.assertIn('time="2021-02-27T20:00:00.000Z"', vec["expect"])

    def test_a_start_time_alone_fills_the_report_time(self):
        model = self.vector("packs/cot-protobuf/vectors/06-start-alone-fills-time.json")["model"]
        self.assertEqual(model["time_ms"], str(script.T - 60000))
        self.assertEqual(model["takproto.cot_event_start_time"], str(script.T - 60000))

    def test_the_control_member_alone_is_its_own_kind(self):
        vec = self.vector("packs/cot-protobuf/vectors/08-control-empty-member.json")
        self.assertEqual((vec["input"], vec["expect"], vec["model"]), ("0a00", "0a00", {"@kind": "tak_control"}))
        self.assertEqual(p2p.enc_tree(script.EMPTY_CONTROL).hex(), "0a00")

    def test_a_feature_with_no_position_has_no_kind(self):
        vec = self.vector("packs/geojson/vectors/90-to-cot-protobuf-no-position.json")
        self.assertEqual(vec["expect_error"], "no-kind")
        self.assertNotIn("expect", vec)


if __name__ == "__main__":
    unittest.main()
