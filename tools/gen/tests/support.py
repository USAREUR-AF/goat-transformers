"""Shared helpers for the generator tests. Standard library only.

    python3 -I -m unittest discover -s tools/gen/tests

Golden-file tests keep their inputs and expected outputs under
`fixtures/<generator>/`:

    fixtures/<generator>/input/...       what the generator reads, written for the test
    fixtures/<generator>/expected/...    the tree the generator must write, byte for byte

To accept a deliberate change of generator output, run the tests once with
GT_UPDATE_GOLDEN=1 in the environment; the expected trees are rewritten, the
tests of that run fail so the change is not missed, and the diff of the
expected trees is what a reviewer reads.
"""
import contextlib
import difflib
import importlib.util
import io
import os
import shutil
import sys

sys.dont_write_bytecode = True      # leave no cache beside the generators

TESTS = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.dirname(TESTS)
REPO = os.path.dirname(os.path.dirname(GEN))
FIXTURES = os.path.join(TESTS, "fixtures")
UPDATE_GOLDEN = os.environ.get("GT_UPDATE_GOLDEN") == "1"

if GEN not in sys.path:
    sys.path.insert(0, GEN)          # so tests import gtcheck, genio and the generators by name


def load_script(file_name):
    """Import a generator whose file name is not a module name
    (`conformance-seq-vectors.py`), without running its `main`."""
    name = os.path.splitext(file_name)[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, os.path.join(GEN, file_name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(main, argv):
    """Call a generator's `main(argv)`; (exit status, stdout text, stderr text).
    A SystemExit from argparse or from the generator becomes the status."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = main(list(argv))
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
            if e.code is not None and not isinstance(e.code, int):
                err.write(str(e.code) + "\n")
    return (status or 0), out.getvalue(), err.getvalue()


def tree(root):
    """{relative path with `/`: bytes} of every file under `root`."""
    files = {}
    for directory, dirs, names in os.walk(root):
        dirs.sort()
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as fh:
                files[os.path.relpath(path, root).replace(os.sep, "/")] = fh.read()
    return files


def _describe(rel, want, got):
    try:
        a, b = want.decode("utf-8").splitlines(), got.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return "%s: bytes differ" % rel
    diff = list(difflib.unified_diff(a, b, "expected/" + rel, "written/" + rel, lineterm="", n=1))
    return "\n".join(line[:200] for line in diff[:24])


def assert_same_tree(case, expected_dir, actual_dir, ignore=()):
    """Fail `case` unless the two directories hold the same files with the same
    bytes. `ignore` lists relative paths (or directory prefixes ending in `/`)
    of `actual_dir` that are inputs, not outputs. With GT_UPDATE_GOLDEN=1 the
    expected directory is rewritten from the actual one and the test fails."""
    def kept(rel):
        return not any(rel == i or (i.endswith("/") and rel.startswith(i)) for i in ignore)

    actual = {rel: data for rel, data in tree(actual_dir).items() if kept(rel)}
    if UPDATE_GOLDEN:
        shutil.rmtree(expected_dir, ignore_errors=True)
        for rel, data in actual.items():
            path = os.path.join(expected_dir, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        case.fail("GT_UPDATE_GOLDEN=1: rewrote %s; review the diff and run again without it" % expected_dir)
    expected = tree(expected_dir)
    problems = ["not written: " + rel for rel in sorted(set(expected) - set(actual))]
    problems += ["written and not expected: " + rel for rel in sorted(set(actual) - set(expected))]
    problems += [_describe(rel, expected[rel], actual[rel])
                 for rel in sorted(set(expected) & set(actual)) if expected[rel] != actual[rel]]
    if problems:
        case.fail("generator output differs from %s\n%s" % (
            os.path.relpath(expected_dir, REPO), "\n".join(problems[:12])))


def copy_tree(src, dst):
    """Copy a fixture directory to a writable place; returns `dst`."""
    shutil.copytree(src, dst, dirs_exist_ok=True)
    return dst
