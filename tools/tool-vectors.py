#!/usr/bin/env python3
"""Run the tool vectors of spec 0.23 against one engine's command-line tool.

    python3 -I tools/tool-vectors.py [--vectors DIR] [--only NAME] -- <command> [<arg>...]

Each vector under packs/conformance/tool-vectors/ (spec/vector-format.md,
Tool vectors) gives the arguments, the input, the exit status and the output.
The runner prints one `FAIL <file>: <why>` line per failing vector and
`tool vectors: N/N passed` last, and exits 1 on any failure.
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = {"name", "args", "stdin_hex", "exit", "stdout_text", "stdout_any", "error_kind"}
TIMEOUT_S = 120


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


def expand(arg, packs, models):
    return arg.replace("{packs}", packs).replace("{models}", models)


def check(vector, command, packs, models):
    """Why the run fails, or None."""
    why = invalid(vector)
    if why:
        return "invalid vector: " + why
    argv = command + [expand(a, packs, models) for a in vector["args"]]
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
