"""The command-line tool of spec version 0.23, the command-line contract:
`convert`, `list-formats`, `capability`, `matrix` and `help`.

Exit status 0 on success; 1 on a load or call failure, standard error's
first line being the failure's message, which begins with its kind and a
colon; 2 on a usage error, every argument being checked before anything is
loaded."""

import os
import sys

from .engine import Engine, _model_order
from .errors import GTError, UnknownFormat
from .modeldef import load_model_file
from .packdef import load_pack

PROG = "goat-xf-py"
MAX_I64 = (1 << 63) - 1

USAGE = """usage:
  {p} convert --from <format> --to <format> [--set <key>=<value>]... <options>
  {p} list-formats <options>
  {p} capability --from <format> --to <format> <options>
  {p} matrix <options>
  {p} help

<options>, in any order, each at most once:
  --packs <dir>              the directory whose subdirectories are packs
                             (default: $GT_PACKS, else ./packs)
  --models <dir>             the directory of model modules (default: <packs>/../model)
  --packs-only <name>[,...]  load only these subdirectories of --packs, in this order
  --max-items <n>            the limit on list items one decode holds (default 100000)
  --max-distribution <public|controlled>
                             the distribution limit (default controlled)

convert reads the message on standard input and writes the result on standard
output with nothing added. Exit status: 0 success, 1 a load or call failure
(standard error begins with the error kind and a colon), 2 a usage error.
""".format(p=PROG)

COMMON = ("--packs", "--models", "--packs-only", "--max-items", "--max-distribution")
TAKES = {
    "convert": COMMON + ("--from", "--to", "--set"),
    "list-formats": COMMON,
    "capability": COMMON + ("--from", "--to"),
    "matrix": COMMON,
}


class Usage(Exception):
    pass


def parse_args(argv):
    """The checked arguments: (subcommand, options, sets). Raises Usage."""
    if not argv:
        raise Usage("no subcommand")
    cmd = argv[0]
    if cmd not in TAKES:
        raise Usage("unknown subcommand %r" % cmd)
    names = TAKES[cmd]
    opts, sets = {}, []
    i = 1
    while i < len(argv):
        name = argv[i]
        if name not in names:
            raise Usage("%s does not take %r" % (cmd, name))
        if i + 1 >= len(argv):
            raise Usage("%s has no value" % name)
        value = argv[i + 1]
        i += 2
        if name == "--set":
            key, eq, val = value.partition("=")
            if not eq or not key:
                raise Usage("--set takes <key>=<value>, got %r" % value)
            sets.append((key, val))
            continue
        if name in opts:
            raise Usage("%s given twice" % name)
        if name == "--max-items":
            if not value or not all("0" <= c <= "9" for c in value) or int(value) > MAX_I64:
                raise Usage("--max-items takes digits 0 to 9, at most 2^63 - 1, got %r" % value)
        elif name == "--max-distribution":
            if value not in ("public", "controlled"):
                raise Usage("--max-distribution takes public or controlled, got %r" % value)
        elif name == "--packs-only":
            if any(n == "" for n in value.split(",")):
                raise Usage("--packs-only takes names separated by commas, none empty, got %r" % value)
        opts[name] = value
    if cmd in ("convert", "capability"):
        for name in ("--from", "--to"):
            if name not in opts:
                raise Usage("%s needs %s" % (cmd, name))
    return cmd, opts, sets


def _is_pack_dir(d):
    return os.path.isdir(d) and os.path.isfile(os.path.join(d, "pack.def"))


def load(opts):
    """Loading, as Version 0.23 states it: every module of --models (a
    regular file, or a symbolic link to one, named `*.def`), then the packs.
    With --packs-only each name is looked up in --packs, which is not
    listed. Raises GTError on a load failure, OSError on an unreadable
    --packs listed without --packs-only."""
    packs_dir = opts.get("--packs")
    if packs_dir is None:
        packs_dir = os.environ.get("GT_PACKS") or "packs"
    models_dir = opts.get("--models")
    if models_dir is None:
        models_dir = packs_dir + "/../model"
    limit = opts.get("--max-distribution", "controlled")
    eng = Engine(max_distribution=limit)
    if "--max-items" in opts:
        eng.set_max_items(int(opts["--max-items"]))
    # the modules first, before --packs is read at all (Loading, 1)
    if os.path.isdir(models_dir):
        for path in _model_order(models_dir):
            eng.add_model(load_model_file(path, models=eng.models, max_distribution=limit))
    if "--packs-only" in opts:
        for name in opts["--packs-only"].split(","):
            d = os.path.join(packs_dir, name)
            if name in (".", "..") or "/" in name or "\\" in name or not _is_pack_dir(d):
                raise UnknownFormat("no pack directory named %r in %s" % (name, packs_dir), format=name)
            eng.add(load_pack(d))
    else:
        # only without --packs-only is --packs listed; unreadable, it exits 1 with no kind
        for name in sorted(os.listdir(packs_dir), key=os.fsencode):
            d = os.path.join(packs_dir, name)
            if not name.startswith(".") and _is_pack_dir(d):
                eng.add(load_pack(d))
    return eng


def _line(report):
    return "%s\t%s\t%s\t%s\t%s\n" % (
        report["from"], report["to"], report["grade"], " ".join(report["carried"]), " ".join(report["dropped"]),
    )


def run(cmd, opts, sets, stdin):
    eng = load(opts)
    if cmd == "list-formats":
        out = "".join(
            "%s\t%s\t%s\n" % (f, eng.packs[f].version, eng.packs[f].wire)
            for f in sorted(eng.packs, key=lambda f: f.encode("utf-8"))
        )
        return out.encode("utf-8")
    if cmd == "matrix":
        fmts = sorted(eng.packs, key=lambda f: f.encode("utf-8"))
        lines = ["from\tto\tgrade\tcarried\tdropped\n"]
        lines.extend(_line(eng.capability(a, b)) for a in fmts for b in fmts)
        return "".join(lines).encode("utf-8")
    src, dst = opts["--from"], opts["--to"]
    eng.pack(src)  # `--from`, then `--to`, before standard input is read
    eng.pack(dst)
    if cmd == "capability":
        return _line(eng.capability(src, dst)).encode("utf-8")
    context = None
    if sets:
        context = {}
        for key, value in sets:
            context[key] = value  # a key given twice keeps its first place, takes its last value
    data = stdin.read()
    return eng.convert(src, dst, data, context)


def main(argv=None, stdin=None, stdout=None, stderr=None):
    if argv is None:
        argv = sys.argv[1:]
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    stderr = stderr if stderr is not None else sys.stderr
    if argv and argv[0] in ("help", "-h", "--help"):
        stdout.write(USAGE.encode("utf-8"))
        stdout.flush()
        return 0
    try:
        cmd, opts, sets = parse_args(argv)
    except Usage as e:
        stderr.write("%s: usage error: %s\n%s" % (PROG, e, USAGE))
        return 2
    try:
        out = run(cmd, opts, sets, stdin)
    except GTError as e:
        stderr.write("%s\n" % e)
        return 1
    except OSError as e:
        stderr.write("%s: cannot read: %s\n" % (PROG, e))
        return 1
    except (RecursionError, MemoryError) as e:
        stderr.write("%s: %s\n" % (PROG, type(e).__name__))
        return 1
    stdout.write(out)
    stdout.flush()
    return 0
