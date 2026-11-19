"""Tests of tools/gen/genio.py: how generators write, and the `--check` mode."""
import io
import os
import tempfile
import unittest

import support
import genio


class OutputTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = self._dir.name

    def put(self, rel, data):
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)

    def report(self, out):
        stream = io.StringIO()
        return out.report("gen", stream), stream.getvalue()

    def test_write_creates_directories_and_writes_utf8_with_newline_line_ends(self):
        out = genio.Output(self.root)
        out.write("packs/x/pack.def", "format x\nsource \"°\"\n")
        with open(os.path.join(self.root, "packs", "x", "pack.def"), "rb") as fh:
            self.assertEqual(fh.read(), b'format x\nsource "\xc2\xb0"\n')
        self.assertEqual(self.report(out), (0, ""))

    def test_read_gives_what_the_run_wrote_and_otherwise_what_is_on_disk(self):
        self.put("a.txt", b"old\n")
        self.put("b.txt", b"kept\n")
        for check in (False, True):
            out = genio.Output(self.root, check=check)
            out.write("a.txt", "new\n")
            self.assertEqual((out.read("a.txt"), out.read("b.txt")), ("new\n", "kept\n"))
            self.put("a.txt", b"old\n")

    def test_check_writes_nothing_and_passes_when_the_bytes_are_the_same(self):
        self.put("a.txt", b"same\n")
        before = support.tree(self.root)
        out = genio.Output(self.root, check=True)
        out.write("a.txt", "same\n")
        status, text = self.report(out)
        self.assertEqual(status, 0)
        self.assertIn("ok, 1 file(s)", text)
        self.assertEqual(support.tree(self.root), before)

    def test_check_names_a_file_that_differs_and_the_line(self):
        self.put("a.txt", b"one\ntwo\nthree\n")
        out = genio.Output(self.root, check=True)
        out.write("a.txt", "one\ntwo\nTHREE\n")
        status, text = self.report(out)
        self.assertEqual(status, 1)
        self.assertIn("gen: --check: a.txt differs at line 3", text)
        with open(os.path.join(self.root, "a.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"one\ntwo\nthree\n")

    def test_check_names_a_file_that_only_differs_in_length(self):
        self.put("a.txt", b"one\n")
        out = genio.Output(self.root, check=True)
        out.write("a.txt", "one\ntwo\n")
        status, text = self.report(out)
        self.assertEqual(status, 1)
        self.assertIn("a.txt differs: the generator writes 8 bytes, the file has 4", text)

    def test_check_names_a_missing_file(self):
        out = genio.Output(self.root, check=True)
        out.write("packs/x/pack.md", "text\n")
        status, text = self.report(out)
        self.assertEqual(status, 1)
        self.assertIn("packs/x/pack.md is missing", text)
        self.assertFalse(os.path.exists(os.path.join(self.root, "packs")))

    def test_a_crlf_file_is_a_difference(self):
        self.put("a.txt", b"one\r\n")
        out = genio.Output(self.root, check=True)
        out.write("a.txt", "one\n")
        self.assertEqual(self.report(out)[0], 1)

    def test_remove_deletes_and_in_check_mode_reports_the_stale_file(self):
        self.put("v/gen-old.json", b"{}\n")
        out = genio.Output(self.root, check=True)
        out.remove("v/gen-old.json")
        self.assertFalse(out.exists("v/gen-old.json"))
        status, text = self.report(out)
        self.assertEqual(status, 1)
        self.assertIn("v/gen-old.json is not written by the generator and would be removed", text)
        self.assertTrue(os.path.exists(os.path.join(self.root, "v", "gen-old.json")))

        out = genio.Output(self.root)
        out.remove("v/gen-old.json")
        out.remove("v/never-there.json")
        self.assertFalse(os.path.exists(os.path.join(self.root, "v", "gen-old.json")))

    def test_a_file_removed_and_written_again_with_the_same_bytes_is_no_difference(self):
        # a generator clears its vectors and writes them again
        self.put("v/gen-a.json", b"{}\n")
        out = genio.Output(self.root, check=True)
        out.remove("v/gen-a.json")
        out.write("v/gen-a.json", "{}\n")
        self.assertEqual(self.report(out)[0], 0)
        self.assertTrue(out.exists("v/gen-a.json"))

    def test_listdir_sees_the_run_not_only_the_disk(self):
        self.put("v/a.json", b"1")
        self.put("v/b.json", b"2")
        out = genio.Output(self.root, check=True)
        out.remove("v/a.json")
        out.write("v/c.json", "3")
        self.assertEqual(out.listdir("v"), ["b.json", "c.json"])
        self.assertEqual(out.listdir("nowhere"), [])

    def test_read_of_a_removed_file_fails(self):
        self.put("a.txt", b"x")
        out = genio.Output(self.root, check=True)
        out.remove("a.txt")
        with self.assertRaises(FileNotFoundError):
            out.read("a.txt")


class VectorMainTest(unittest.TestCase):
    def build(self, sink):
        sink.write("packs/p/vectors/01-a.json", "{}\n")
        return {"p": 1}

    def test_writes_then_checks_then_detects_a_changed_file(self):
        with tempfile.TemporaryDirectory() as root:
            status, out, _ = support.run_main(lambda argv: genio.vector_main("v", "doc", self.build, argv),
                                              ["--out", root])
            self.assertEqual((status, out), (0, "p 1\n"))
            path = os.path.join(root, "packs", "p", "vectors", "01-a.json")
            status, _, err = support.run_main(lambda argv: genio.vector_main("v", "doc", self.build, argv),
                                              ["--check", root])
            self.assertEqual(status, 0, err)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ }\n")
            status, _, err = support.run_main(lambda argv: genio.vector_main("v", "doc", self.build, argv),
                                              ["--out", root, "--check"])
            self.assertEqual(status, 1)
            self.assertIn("packs/p/vectors/01-a.json", err)


if __name__ == "__main__":
    unittest.main()
