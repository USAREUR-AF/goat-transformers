"""The scripts that write hand-derived conformance vectors must reproduce the
committed vectors byte for byte, and must notice when they do not.

Each script states its vectors as data and computes expected bytes without an
engine. A committed vector that no longer equals what its script writes means
one of the two was edited alone; `--check` is how that is found.
"""
import os
import shutil
import tempfile
import unittest

import support

SCRIPTS = (
    "conformance-absent-vectors.py",
    "conformance-asopt-inner-vectors.py",
    "conformance-asopt-vectors.py",
    "conformance-cat062-vectors.py",
    "conformance-charset-vectors.py",
    "conformance-cond-vectors.py",
    "conformance-derive16-vectors.py",
    "conformance-emptygroup-vectors.py",
    "conformance-extents-vectors.py",
    "conformance-gates-vectors.py",
    "conformance-groups-vectors.py",
    "conformance-held-vectors.py",
    "conformance-inner-refused-vectors.py",
    "conformance-kinds-vectors.py",
    "conformance-lineorder-vectors.py",
    "conformance-long-vectors.py",
    "conformance-lookahead-vectors.py",
    "conformance-malformed-vectors.py",
    "conformance-noword-vectors.py",
    "conformance-part-vectors.py",
    "conformance-rulings07-vectors.py",
    "conformance-rulings011-vectors.py",
    "conformance-rulings011b-vectors.py",
    "conformance-rulings08-vectors.py",
    "conformance-run-vectors.py",
    "conformance-seconds-vectors.py",
    "conformance-seq-vectors.py",
    "conformance-tool-vectors.py",
    "conformance-transforms-vectors.py",
    "conformance-twocount-vectors.py",
    "conformance-twolines-vectors.py",
    "conformance-twolines-wires-vectors.py",
    "conformance-units-vectors.py",
    "conformance-whenas-vectors.py",
)


class VectorScriptsTest(unittest.TestCase):
    def test_each_script_reproduces_the_committed_vectors(self):
        for name in SCRIPTS:
            with self.subTest(name):
                status, _, err = support.run_main(support.load_script(name).main, ["--check", "--out", support.REPO])
                self.assertEqual(status, 0, err)
                self.assertIn("--check: ok", err)

    def test_every_vector_script_in_the_directory_is_listed_here(self):
        present = sorted(n for n in os.listdir(support.GEN) if n.startswith("conformance-") and n.endswith(".py"))
        self.assertEqual(present, sorted(SCRIPTS))

    def test_a_script_writes_the_same_files_into_an_empty_directory(self):
        script = support.load_script("conformance-rulings07-vectors.py")
        with tempfile.TemporaryDirectory() as root:
            status, out, err = support.run_main(script.main, ["--out", root])
            self.assertEqual(status, 0, err)
            written = support.tree(root)
            self.assertTrue(written)
            for rel, data in written.items():
                with open(os.path.join(support.REPO, *rel.split("/")), "rb") as fh:
                    self.assertEqual(fh.read(), data, rel)
            # the summary names each pack with the number of files written to it
            counts = dict(line.rsplit(" ", 1) for line in out.splitlines())
            self.assertEqual(sum(int(n) for n in counts.values()), len(written))

    def test_check_fails_and_names_the_file_when_a_committed_vector_was_edited(self):
        script = support.load_script("conformance-cat062-vectors.py")
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(support.run_main(script.main, ["--out", root])[0], 0)
            victim = sorted(support.tree(root))[0]
            path = os.path.join(root, *victim.split("/"))
            with open(path, "rb") as fh:
                data = fh.read()
            with open(path, "wb") as fh:
                fh.write(data.replace(b'"expect"', b'"expect" ', 1))
            before = support.tree(root)
            status, _, err = support.run_main(script.main, ["--out", root, "--check"])
            self.assertEqual(status, 1)
            self.assertIn(victim, err)
            self.assertEqual(support.tree(root), before, "--check changed the tree")

    def test_check_fails_when_a_vector_is_missing(self):
        script = support.load_script("conformance-cat062-vectors.py")
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(support.run_main(script.main, ["--out", root])[0], 0)
            shutil.rmtree(os.path.join(root, "packs", "canonical-track-v2"))
            status, _, err = support.run_main(script.main, ["--out", root, "--check"])
            self.assertEqual(status, 1)
            self.assertIn("is missing", err)


if __name__ == "__main__":
    unittest.main()
