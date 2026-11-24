#!/usr/bin/env python3
"""Run the tool vectors of spec 0.23 against one engine's command-line tool.

    python3 -I tools/tool-vectors.py [--vectors DIR] [--only NAME] -- <command> [<arg>...]

Each vector under packs/conformance/tool-vectors/ (spec/vector-format.md,
Tool vectors) gives the arguments, the input, the exit status and the output.
The runner prints one `FAIL <file>: <why>` line per failing vector and
`tool vectors: N/N passed` last, and exits 1 on any failure. The files a vector
carries (`files`) are written below a new temporary directory, which is removed
after the run, also when the run fails.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = {"name", "args", "stdin_hex", "files", "exit", "stdout_text", "stdout_any", "error_kind"}
TIMEOUT_S = 120
FILE_NAME = re.compile(r"[A-Za-z0-9._-]+")
LOWER_HEX = re.compile(r"(?:[0-9a-f]{2})*")


def must_be_text(data):
    """True for the bytes of UTF-8 text with no control character but tab and
    line feed: a vector's file that holds such bytes is a string, not hex."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not any(unicodedata.category(c) == "Cc" and c not in "\t\n" for c in text)


def file_bytes(value):
    """The bytes of one value of `files`; ValueError (with why) when it is none."""
    if isinstance(value, str):
        try:
            return value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("the text is not UTF-8")
    if not isinstance(value, dict) or set(value) != {"hex"}:
        raise ValueError("neither a text nor an object with the one member hex")
    if not isinstance(value["hex"], str) or not LOWER_HEX.fullmatch(value["hex"]):
        raise ValueError("not lower-case hex")
    data = bytes.fromhex(value["hex"])
    if must_be_text(data):
        raise ValueError("hex for a file that can be text")
    return data


def invalid_files(files):
    """Why the `files` member is invalid, or None."""
    if not isinstance(files, dict):
        return "files is not an object"
    for path, data in files.items():
        names = path.split("/")
        if not all(FILE_NAME.fullmatch(n) and n not in (".", "..") for n in names):
            return "files: %r is not a path" % path
        try:
            file_bytes(data)
        except ValueError as err:
            return "files: %r: %s" % (path, err)
        if any("/".join(names[:i]) in files for i in range(1, len(names))):
            return "files: %r lies below another file" % path
    return None


def write_files(files, root):
    """Write the files below `root`, a new directory. Each file and directory
    is made here: one that is already there, a symbolic link included, is an
    error, so nothing is written outside `root`."""
    made = set()
    for path, data in files.items():
        names = path.split("/")
        for i in range(1, len(names)):
            folder = "/".join(names[:i])
            if folder not in made:
                os.mkdir(os.path.join(root, *names[:i]))
                made.add(folder)
        with open(os.path.join(root, *names), "xb") as fh:      # x: never through a link
            fh.write(file_bytes(data))


def invalid(vector):
    """Why a vector is invalid, or None."""
    if not isinstance(vector, dict):
        return "not a JSON object"
    extra = sorted(set(vector) - KEYS)
    if extra:
        return "key not in the table: " + ", ".join(extra)
    if not isinstance(vector.get("name"), str) or not vector["name"]:
        return "no name"
    args = vector.get("args")
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return "args is not an array of strings"
    if vector.get("exit") not in (0, 1, 2):
        return "exit is not 0, 1 or 2"
    if "stdin_hex" in vector:
        try:
            bytes.fromhex(vector["stdin_hex"])
        except (TypeError, ValueError):
            return "stdin_hex is not hex"
        if vector["stdin_hex"] != vector["stdin_hex"].lower():
            return "stdin_hex is not lower case"
    if "files" in vector:
        why = invalid_files(vector["files"])
        if why:
            return why
    elif any("{files}" in a for a in args):
        return "{files} in args without files"
    has_text, has_any = "stdout_text" in vector, "stdout_any" in vector
    if has_text and has_any:
        return "both stdout_text and stdout_any"
    if has_any and vector["stdout_any"] is not True:
        return "stdout_any is not true"
    if has_text and not isinstance(vector["stdout_text"], str):
        return "stdout_text is not a string"
    if vector["exit"] == 0:
        if not (has_text or has_any):
            return "exit 0 without stdout_text or stdout_any"
    elif has_text or has_any:
        return "output pinned on a non-zero exit"
    if "error_kind" in vector:
        if vector["exit"] != 1:
            return "error_kind without exit 1"
        if not isinstance(vector["error_kind"], str) or not vector["error_kind"]:
            return "error_kind is not a kind"
    return None


def expand(arg, packs, models, files=None):
    """Replace each place once, so the text put in is never read again."""
    to = {"{packs}": packs, "{models}": models}
    if files is not None:
        to["{files}"] = files
    return re.sub("|".join(re.escape(k) for k in to), lambda m: to[m.group(0)], arg)


def check(vector, command, packs, models):
    """Why the run fails, or None."""
    why = invalid(vector)
    if why:
        return "invalid vector: " + why
    if "files" not in vector:
        return run_vector(vector, command, packs, models, None)
    try:
        with tempfile.TemporaryDirectory(prefix="tool-vector-") as root:
            root = os.path.realpath(root)
            write_files(vector["files"], root)
            return run_vector(vector, command, packs, models, root)
    except OSError as err:
        return "the vector's files: %s" % err


def run_vector(vector, command, packs, models, files):
    """Why the run of a valid vector fails, or None. `files`: the directory of
    its files, or None."""
    argv = command + [expand(a, packs, models, files) for a in vector["args"]]
    data = bytes.fromhex(vector.get("stdin_hex", ""))
    try:
        run = subprocess.run(argv, input=data, capture_output=True, timeout=TIMEOUT_S, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return "no exit within %d s" % TIMEOUT_S
    except OSError as err:
        return "cannot start %s: %s" % (argv[0], err)
    out, err = run.stdout, run.stderr
    if run.returncode != vector["exit"]:
        first = err.decode("utf-8", "replace").split("\n", 1)[0]
        return "exit %d, want %d (stderr: %s)" % (run.returncode, vector["exit"], first[:200])
    if vector["exit"] == 0:
        if "stdout_any" in vector:
            if not out:
                return "stdout empty"
        elif out != vector["stdout_text"].encode("utf-8"):
            return "stdout differs: got %r, want %r" % (out[:300], vector["stdout_text"].encode("utf-8")[:300])
        if err:
            return "stderr not empty: %r" % err[:200]
        return None
    if out:
        return "stdout not empty on exit %d: %r" % (vector["exit"], out[:200])
    if not err:
        return "stderr empty on exit %d" % vector["exit"]
    if vector["exit"] == 1 and "error_kind" in vector:
        first = err.split(b"\n", 1)[0]
        if not first.startswith(vector["error_kind"].encode("utf-8") + b":"):
            return "stderr's first line %r does not begin with %s:" % (
                first[:200], vector["error_kind"])
    return None


def main(argv):
    if "--" not in argv:
        print("usage: tool-vectors.py [--vectors DIR] [--only NAME] -- <command> [<arg>...]",
              file=sys.stderr)
        return 2
    cut = argv.index("--")
    parser = argparse.ArgumentParser(prog="tool-vectors.py")
    parser.add_argument("--vectors", default=os.path.join(ROOT, "packs", "conformance", "tool-vectors"))
    parser.add_argument("--packs", default=os.path.join(ROOT, "packs"))
    parser.add_argument("--models", default=os.path.join(ROOT, "model"))
    parser.add_argument("--only", action="append", default=[])
    opts = parser.parse_args(argv[:cut])
    command = argv[cut + 1:]
    if not command:
        print("tool-vectors.py: no command after --", file=sys.stderr)
        return 2
    files = sorted(f for f in os.listdir(opts.vectors) if f.endswith(".json"))
    if opts.only:
        files = [f for f in files if any(o in f for o in opts.only)]
    names, failed = set(), 0
    for name in files:
        path = os.path.join(opts.vectors, name)
        try:
            with open(path, encoding="utf-8") as fh:
                vector = json.load(fh)
        except (OSError, ValueError) as err:
            why = "unreadable: %s" % err
        else:
            why = check(vector, command, os.path.abspath(opts.packs), os.path.abspath(opts.models))
            if why is None and vector["name"] in names:
                why = "invalid vector: name used twice"
            if isinstance(vector, dict) and isinstance(vector.get("name"), str):
                names.add(vector["name"])
        if why:
            failed += 1
            print("FAIL %s: %s" % (name, why))
    print("tool vectors: %d/%d passed" % (len(files) - failed, len(files)))
    return 1 if failed or not files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
