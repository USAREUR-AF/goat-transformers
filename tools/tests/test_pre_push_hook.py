"""Tests for tools/hooks/pre-push (docs/boundary.md). Standard library only:

    python3 -I -m unittest discover -s tools/tests

The hook is run in a temporary git checkout that holds a stand-in for
tools/boundary-gate: a script that records how it was called. What is tested
is the hook's own promise: it refuses the push unless the gate ran with a
needle list, and it never runs the gate without one.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from support import REPO, TempTree, have_git

HOOK = os.path.join(REPO, "tools", "hooks", "pre-push")

# Stands in for tools/boundary-gate: writes its arguments and the needle file
# it was given to the file named by STUB_RECORD, then exits with STUB_STATUS.
GATE_STUB = '''import json, os, sys
argv = sys.argv[1:]
needles = None
if "--needles" in argv:
    with open(argv[argv.index("--needles") + 1], encoding="utf-8") as fh:
        needles = fh.read()
with open(os.environ["STUB_RECORD"], "w", encoding="utf-8") as fh:
    json.dump({"argv": argv, "needles": needles}, fh)
print("stub gate ran")
sys.exit(int(os.environ.get("STUB_STATUS", "0")))
'''


@unittest.skipUnless(have_git() and shutil.which("bash"), "git and bash are needed")
class PrePush(unittest.TestCase):
    def setUp(self):
        self.tree = TempTree()
        self.addCleanup(self.tree.cleanup)
        self.tree.git("init", "-q")
        self.tree.write("tools/boundary-gate", GATE_STUB)
        self.record = os.path.join(self.tree.beside, "record.json")
        self.overlay = os.path.join(self.tree.beside, "overlay")

    def write_generator(self, body, overlay=None):
        path = os.path.join(overlay or self.overlay, "tools", "needles.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def push(self, overlay="set", status=0, cwd=None):
        """Run the hook as git would. -> (exit status, standard output, standard error)"""
        env = dict(self.tree.env, STUB_RECORD=self.record, STUB_STATUS=str(status))
        env.pop("GOAT_XF_OVERLAY", None)
        if overlay == "set":
            env["GOAT_XF_OVERLAY"] = self.overlay
        # The hook starts `python3`; make that the interpreter running the tests.
        shim = os.path.join(self.tree.beside, "bin")
        os.makedirs(shim, exist_ok=True)
        if not os.path.exists(os.path.join(shim, "python3")):
            os.symlink(sys.executable, os.path.join(shim, "python3"))
        env["PATH"] = shim + os.pathsep + env.get("PATH", "")
        done = subprocess.run(["bash", HOOK], cwd=cwd or self.tree.root, env=env, capture_output=True, text=True)
        return done.returncode, done.stdout, done.stderr

    def recorded(self):
        with open(self.record, encoding="utf-8") as fh:
            return json.load(fh)

    def test_refuses_when_the_overlay_is_missing_and_does_not_run_the_gate(self):
        code, _, err = self.push()
        self.assertEqual(code, 1)
        self.assertIn("needle generator not found", err)
        self.assertIn("push refused", err)
        self.assertFalse(os.path.exists(self.record))

    def test_refuses_when_no_overlay_is_named_and_none_is_beside_the_repository(self):
        code, _, err = self.push(overlay="unset")
        self.assertEqual(code, 1)
        self.assertIn(os.path.join(self.tree.base, "goat-transformers-overlay", "tools", "needles.py"), err)
        self.assertFalse(os.path.exists(self.record))

    def test_refuses_when_the_needle_list_cannot_be_built(self):
        self.write_generator("import sys\nprint('zorblat')\nsys.exit(3)\n")
        code, _, err = self.push()
        self.assertEqual(code, 1)
        self.assertIn("could not build the needle list; push refused", err)
        self.assertFalse(os.path.exists(self.record))

    def test_runs_the_gate_on_the_checkout_with_the_needle_list_and_require_needles(self):
        self.write_generator("print('zorblat')\nprint('quuxfrob')\n")
        code, out, _ = self.push()
        self.assertEqual(code, 0)
        self.assertIn("stub gate ran", out)
        call = self.recorded()
        argv = call["argv"]
        self.assertEqual(argv[:2], ["--root", self.tree.root])
        self.assertEqual(argv[2], "--needles")
        self.assertEqual(argv[4:], ["--require-needles"])
        self.assertEqual(call["needles"], "zorblat\nquuxfrob\n")
        self.assertFalse(os.path.exists(argv[3]), "the needle list is removed when the hook ends")

    def test_the_gate_decides_the_push(self):
        self.write_generator("print('zorblat')\n")
        code, _, _ = self.push(status=1)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.recorded()["argv"][3]), "the needle list is removed on failure too")

    def test_the_default_overlay_is_the_directory_beside_the_repository(self):
        self.write_generator("print('zorblat')\n", overlay=os.path.join(self.tree.base, "goat-transformers-overlay"))
        code, _, _ = self.push(overlay="unset")
        self.assertEqual(code, 0)
        self.assertEqual(self.recorded()["needles"], "zorblat\n")

    def test_runs_from_a_directory_inside_the_checkout(self):
        self.write_generator("print('zorblat')\n")
        self.tree.write("docs/notes.md", "text\n")
        code, _, _ = self.push(cwd=os.path.join(self.tree.root, "docs"))
        self.assertEqual(code, 0)
        self.assertEqual(self.recorded()["argv"][:2], ["--root", self.tree.root])

    def test_with_the_real_gate_a_needle_in_the_tree_refuses_the_push(self):
        shutil.copyfile(os.path.join(REPO, "tools", "boundary-gate"), os.path.join(self.tree.root, "tools", "boundary-gate"))
        self.tree.write("docs/notes.md", "the zorblat value\n")
        self.write_generator("print('zorblat')\n")
        code, out, _ = self.push()
        self.assertEqual(code, 1)
        self.assertIn("boundary-gate: needle   docs/notes.md:1: ", out)
        self.write_generator("print('quuxfrob')\n")
        code, out, _ = self.push()
        self.assertEqual(code, 0, out)
        self.assertIn("needles: 1", out)


if __name__ == "__main__":
    unittest.main()
