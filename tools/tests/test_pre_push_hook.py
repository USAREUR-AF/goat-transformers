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

    def push(self, overlay="set", status=0, cwd=None, refs="", remote="origin"):
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
        done = subprocess.run(["bash", HOOK, remote, "a-url"], cwd=cwd or self.tree.root, env=env, capture_output=True,
                              text=True, input=refs)
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

    def commit(self, message):
        self.tree.git("add", "-A")
        self.tree.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
        return self.tree.git("rev-parse", "HEAD").strip()

    def test_names_the_commits_each_pushed_ref_publishes(self):
        self.write_generator("print('zorblat')\n")
        zero = "0" * 40
        first, second = self.commit("one"), None
        self.tree.write("a.md", "a\n")
        second = self.commit("two")
        line = "refs/heads/x %s refs/heads/x %s\n"
        for refs, want in [
            (line % (second, first), ["--commits", "%s..%s" % (first, second)]),
            (line % (second, zero), ["--commits", second]),                 # nothing known of the remote
            (line % (second, "1" * 40), ["--commits", second]),             # its tip is not here
            (line % (zero, first), []),                                     # a deletion
            (line % (second, second), []),
            (line % (first, second), []),                                   # moved back
            (line % (second, first) + line % (first, zero),
             ["--commits", "%s..%s" % (first, second), "--commits", first]),
        ]:
            code, _, err = self.push(refs=refs)
            self.assertEqual(code, 0, err)
            self.assertEqual([a for a in self.recorded()["argv"][4:] if not a.startswith("--ref-name=")],
                             ["--require-needles"] + want)
        self.tree.git("update-ref", "refs/remotes/origin/main", first)
        self.push(refs=line % (second, zero))
        self.assertEqual(self.recorded()["argv"][5:],
                         ["--ref-name=refs/heads/x", "--commits", "%s..%s" % (first, second)])

    def test_with_the_real_gate_a_needle_a_later_commit_removed_refuses_the_push(self):
        self.tree.write(".gitignore", "x\n")
        shutil.copyfile(os.path.join(REPO, "tools", "boundary-gate"), os.path.join(self.tree.root, "tools", "boundary-gate"))
        base = self.commit("base")
        self.tree.write("docs/notes.md", "the zorblat value\n")
        self.commit("add")
        self.tree.write("docs/notes.md", "the value\n")
        tip = self.commit("remove")
        self.write_generator("print('zorblat')\n")
        code, out, _ = self.push()
        self.assertEqual(code, 0, out)  # the tree alone is clean
        code, out, _ = self.push(refs="refs/heads/x %s refs/heads/x %s\n" % (tip, base))
        self.assertEqual(code, 1)
        self.assertIn("boundary-gate: needle   docs/notes.md:1: ", out)

    def test_names_a_tag_on_a_published_commit(self):
        self.write_generator("print('zorblat')\n")
        tip = self.commit("one")
        self.tree.git("update-ref", "refs/remotes/origin/main", tip)
        self.tree.git("-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "v1", "-m", "text")
        tag = self.tree.git("rev-parse", "v1").strip()
        self.push(refs="refs/tags/v1 %s refs/tags/v1 %s\n" % (tag, "0" * 40))
        self.assertEqual(self.recorded()["argv"][5:], ["--ref-name=refs/tags/v1", "--tag", tag])
        self.push(refs="refs/tags/w %s refs/tags/w %s" % (tip, "0" * 40))  # lightweight; no final line break
        self.assertEqual(self.recorded()["argv"][5:], ["--ref-name=refs/tags/w"])

    def test_refuses_a_ref_that_is_no_commit(self):
        self.write_generator("print('zorblat')\n")
        self.commit("one")
        for rev in ("HEAD^{tree}", "HEAD:tools/boundary-gate"):
            oid = self.tree.git("rev-parse", rev).strip()
            code, _, err = self.push(refs="refs/tags/t %s refs/tags/t %s\n" % (oid, "0" * 40))
            self.assertEqual(code, 1)
            self.assertIn("push refused", err)
        code, _, _ = self.push(refs="refs/heads/x %s refs/heads/x %s\n" % ("1" * 40, "0" * 40))
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.record))

    def test_with_the_real_gate_a_needle_in_a_tag_or_a_ref_name_refuses_the_push(self):
        shutil.copyfile(os.path.join(REPO, "tools", "boundary-gate"), os.path.join(self.tree.root, "tools", "boundary-gate"))
        tip = self.commit("one")
        self.tree.git("update-ref", "refs/remotes/origin/main", tip)
        self.write_generator("print('zorblat')\n")
        zero = "0" * 40
        for name, message, want in [("v1", "fine", 0), ("v2", "the zorblat", 1), ("zorblat", "fine", 1)]:
            self.tree.git("-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", name, "-m", message)
            tag = self.tree.git("rev-parse", name).strip()
            code, out, _ = self.push(refs="refs/tags/%s %s refs/tags/%s %s\n" % (name, tag, name, zero))
            self.assertEqual(code, want, out)
            self.assertNotIn("zorblat", out)
        code, out, _ = self.push(refs="refs/heads/fix/zorblat-2 %s refs/heads/fix/zorblat-2 %s\n" % (tip, zero))
        self.assertEqual(code, 1, out)
        self.assertNotIn("zorblat", out)

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
