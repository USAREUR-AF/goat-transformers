"""Tests for tools/tool-vectors.py, the runner of the tool vectors of spec 0.23.
Standard library only:

    python3 -I -m unittest discover -s tools/tests

The runner is pointed at small Python programs that stand in for an engine's
tool, each behaving one way, so every check is seen to pass and to fail.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

from support import REPO


def _load():
    loader = importlib.machinery.SourceFileLoader("tool_vectors", os.path.join(REPO, "tools", "tool-vectors.py"))
    spec = importlib.util.spec_from_loader("tool_vectors", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


tv = _load()

# A stand-in tool: prints what its first argument asks for.
FAKE = r'''
import sys
mode = sys.argv[1] if len(sys.argv) > 1 else ""
if mode == "echo":
    sys.stdout.buffer.write(sys.stdin.buffer.read())
elif mode == "args":
    sys.stdout.write("|".join(sys.argv[2:]))
elif mode == "kind":
    sys.stderr.write("unknown-format: no pack\n"); sys.exit(1)
elif mode == "nokind":
    sys.stderr.write("cannot read the directory\n"); sys.exit(1)
elif mode == "usage":
    sys.stderr.write("usage\n"); sys.exit(2)
elif mode == "noisy":
    sys.stdout.write("x"); sys.stderr.write("warning\n")
elif mode == "silent-fail":
    sys.exit(2)
elif mode == "out-on-error":
    sys.stdout.write("x"); sys.stderr.write("unknown-format: x\n"); sys.exit(1)
elif mode == "early-exit":
    sys.stderr.write("usage\n"); sys.stderr.flush(); sys.exit(2)
'''


class Runner(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.tool = os.path.join(self.dir.name, "fake.py")
        with open(self.tool, "w") as fh:
            fh.write(FAKE)
        self.cmd = [sys.executable, "-I", self.tool]

    def tearDown(self):
        self.dir.cleanup()

    def run_one(self, vector):
        return tv.check(vector, self.cmd, "/abs/packs", "/abs/model")

    def test_stdout_text_matches_byte_for_byte(self):
        v = {"name": "a", "args": ["echo"], "stdin_hex": "6869", "exit": 0, "stdout_text": "hi"}
        self.assertIsNone(self.run_one(v))
        v["stdout_text"] = "hi\n"
        self.assertIn("stdout differs", self.run_one(v))

    def test_placeholders_are_replaced(self):
        v = {"name": "a", "args": ["args", "{packs}", "x{models}y"], "exit": 0,
             "stdout_text": "/abs/packs|x/abs/modely"}
        self.assertIsNone(self.run_one(v))

    def test_stderr_must_be_empty_on_success(self):
        v = {"name": "a", "args": ["noisy"], "exit": 0, "stdout_any": True}
        self.assertIn("stderr not empty", self.run_one(v))

    def test_stdout_any(self):
        self.assertIsNone(self.run_one({"name": "a", "args": ["args", "z"], "exit": 0, "stdout_any": True}))
        self.assertIn("stdout empty", self.run_one({"name": "a", "args": ["args"], "exit": 0, "stdout_any": True}))

    def test_error_kind(self):
        v = {"name": "a", "args": ["kind"], "exit": 1, "error_kind": "unknown-format"}
        self.assertIsNone(self.run_one(v))
        v["error_kind"] = "unknown"
        self.assertIn("does not begin with", self.run_one(v))

    def test_exit_1_without_kind_needs_stderr_only(self):
        self.assertIsNone(self.run_one({"name": "a", "args": ["nokind"], "exit": 1}))

    def test_stdout_must_be_empty_on_failure(self):
        v = {"name": "a", "args": ["out-on-error"], "exit": 1, "error_kind": "unknown-format"}
        self.assertIn("stdout not empty", self.run_one(v))

    def test_usage_error_needs_stderr(self):
        self.assertIsNone(self.run_one({"name": "a", "args": ["usage"], "exit": 2}))
        self.assertIn("stderr empty", self.run_one({"name": "a", "args": ["silent-fail"], "exit": 2}))

    def test_wrong_exit_status(self):
        self.assertIn("exit 2, want 0", self.run_one({"name": "a", "args": ["usage"], "exit": 0, "stdout_any": True}))

    def test_a_tool_that_exits_without_reading_its_input(self):
        v = {"name": "a", "args": ["early-exit"], "stdin_hex": "00" * 1_000_000, "exit": 2}
        self.assertIsNone(self.run_one(v))


class Invalid(unittest.TestCase):
    def test_invalid_vectors(self):
        base = {"name": "a", "args": [], "exit": 0, "stdout_text": ""}
        cases = [
            dict(base, extra=1),
            dict(base, stdout_any=True),
            dict(base, exit=3),
            {"name": "a", "args": [], "exit": 0},
            {"name": "a", "args": [], "exit": 2, "stdout_text": "x"},
            {"name": "a", "args": [], "exit": 2, "error_kind": "x"},
            dict(base, stdin_hex="ABCD"),
            dict(base, stdin_hex="abc"),
            dict(base, args="list-formats"),
            dict(base, name=""),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertIsNotNone(tv.invalid(case))
        self.assertIsNone(tv.invalid(base))


class Repository(unittest.TestCase):
    def test_every_committed_vector_is_valid(self):
        d = os.path.join(REPO, "packs", "conformance", "tool-vectors")
        names = set()
        for f in sorted(os.listdir(d)):
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                v = json.load(fh)
            self.assertIsNone(tv.invalid(v), f)
            self.assertNotIn(v["name"], names, f)
            names.add(v["name"])
            if v["args"] and v["args"][0] not in ("help", "-h", "--help") and v["exit"] != 2:
                self.assertIn("--packs", v["args"], f)

    def test_main_counts_and_exit_status(self):
        with tempfile.TemporaryDirectory() as d:
            for i, (exit_, args) in enumerate([(0, ["echo"]), (2, ["echo"])]):
                with open(os.path.join(d, "%d.json" % i), "w") as fh:
                    json.dump({"name": str(i), "args": args, "exit": exit_,
                               **({"stdout_text": ""} if exit_ == 0 else {})}, fh)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = tv.main(["--vectors", d, "--", sys.executable, "-I", "-c",
                              "import sys; sys.stdin.read()"])
            self.assertEqual(rc, 1)
            self.assertIn("tool vectors: 1/2 passed", out.getvalue())
            self.assertIn("FAIL 1.json", out.getvalue())


if __name__ == "__main__":
    unittest.main()
