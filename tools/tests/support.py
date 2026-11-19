"""What the tests of the tools share: loading a tool that has no .py name,
building a temporary tree, and running a `main` to its exit status and output.
Standard library only.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # the tools have no .py name; leave no cache beside them

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE_SRC = os.path.join(REPO, "engines", "python", "src")

# git variables that would point a `git` started by a test, or by the tool
# under test, at another repository or at the configuration of whoever runs
# the tests.
_GIT_POINTERS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR")


def load_tool(name):
    """The tool `tools/<name>` as a module."""
    module_name = name.replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(module_name, os.path.join(REPO, "tools", name))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def run_main(main, *argv, **kwargs):
    """Call a tool's `main`. -> (exit status, what it printed, what it wrote to
    standard error). A wrong command line ends argparse with status 2."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv), **kwargs)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def isolated_git_env(ceiling):
    """An environment in which git sees only the repository it is started in:
    no repository above `ceiling`, and no user or system configuration."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_POINTERS}
    env.update({
        "GIT_CEILING_DIRECTORIES": ceiling,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    })
    return env


class TempTree:
    """A directory tree under a temporary directory, removed by `cleanup`.
    `root` is the tree; `beside` is a directory next to it for files that must
    not be part of it."""

    def __init__(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="goat-tools-test-"))
        self.root = os.path.join(self.base, "tree")
        self.beside = os.path.join(self.base, "beside")
        os.makedirs(self.root)
        os.makedirs(self.beside)
        self.env = isolated_git_env(self.base)

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def write(self, rel, content=""):
        """Write a file of the tree; `content` is text (UTF-8) or bytes."""
        return self._write(self.root, rel, content)

    def write_beside(self, rel, content=""):
        """Write a file next to the tree, outside it."""
        return self._write(self.beside, rel, content)

    @staticmethod
    def _write(base, rel, content):
        path = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def remove(self, rel):
        os.remove(os.path.join(self.root, *rel.split("/")))

    def git(self, *args):
        """Run git in the tree; the test fails if git does."""
        return subprocess.run(
            ["git", "-C", self.root, *args], check=True, capture_output=True, text=True, env=self.env,
        ).stdout


def have_git():
    return shutil.which("git") is not None
