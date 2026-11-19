"""The scripts that write the hand-derived vectors of the protobuf packs generated
from public schemas (tools/gen/protobuf-*-vectors.py) reproduce the committed
vectors byte for byte.

    python3 -I -m unittest discover -s tools/gen/tests -p 'test_protobuf_family*.py'

Each script states its messages field by field and works out the expected bytes
with an encoder of its own; it imports no engine and no generator.
"""
import os
import tempfile
import unittest

import support


def scripts():
    return sorted(n for n in os.listdir(support.GEN) if n.startswith("protobuf-") and n.endswith("-vectors.py"))


class ProtobufFamilyVectorsTest(unittest.TestCase):
    def test_there_is_a_script(self):
        self.assertTrue(scripts())

    def test_each_script_reproduces_the_committed_vectors(self):
        for name in scripts():
            with self.subTest(name):
                status, _, err = support.run_main(support.load_script(name).main, ["--check", "--out", support.REPO])
                self.assertEqual(status, 0, err)
                self.assertIn("--check: ok", err)

    def test_each_script_writes_only_vector_files(self):
        for name in scripts():
            with self.subTest(name), tempfile.TemporaryDirectory() as root:
                status, _, err = support.run_main(support.load_script(name).main, ["--out", root])
                self.assertEqual(status, 0, err)
                files = sorted(os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
                               for d, _, fs in os.walk(root) for f in fs)
                self.assertTrue(files)
                for rel in files:
                    self.assertRegex(rel, r"^packs/[a-z0-9-]+/vectors/[0-9]{2,3}-[a-z0-9-]+\.json$")

    def test_check_notices_a_changed_vector(self):
        for name in scripts():
            with self.subTest(name), tempfile.TemporaryDirectory() as root:
                script = support.load_script(name)
                self.assertEqual(support.run_main(script.main, ["--out", root])[0], 0)
                victim = next(os.path.join(d, f) for d, _, fs in sorted(os.walk(root)) for f in sorted(fs))
                with open(victim, "a", encoding="utf-8") as fh:
                    fh.write(" ")
                status, _, err = support.run_main(script.main, ["--check", "--out", root])
                self.assertEqual(status, 1, err)


if __name__ == "__main__":
    unittest.main()
