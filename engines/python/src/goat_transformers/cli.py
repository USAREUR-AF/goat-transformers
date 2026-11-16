"""Command line: `convert` (stdin -> stdout, `--set <key>=<value>` for
caller-supplied keys) and `list-formats`."""

import argparse
import os
import sys

from .engine import Engine
from .errors import GTError
from .packdef import DISTRIBUTIONS


def main(argv=None):
    ap = argparse.ArgumentParser(prog="goat_transformers", description="goat-transformers Python engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    default_packs = os.environ.get("GT_PACKS")

    c = sub.add_parser("convert", help="convert stdin from one format to another, write stdout")
    c.add_argument("--from", dest="src", required=True)
    c.add_argument("--to", dest="dst", required=True)
    c.add_argument("--packs", default=default_packs, required=default_packs is None)
    c.add_argument(
        "--set", dest="context", action="append", default=None, metavar="KEY=VALUE",
        help="a caller-supplied model key, read as the key's declared type; repeatable",
    )

    lf = sub.add_parser("list-formats", help="list loaded formats")
    lf.add_argument("--packs", default=default_packs, required=default_packs is None)

    for p in (c, lf):
        p.add_argument("--models", default=None, help="model module directory (default: <packs>/../model)")
        p.add_argument(
            "--max-distribution", dest="max_distribution", choices=DISTRIBUTIONS, default="controlled",
            help="refuse modules and packs above this distribution (default: controlled)",
        )

    args = ap.parse_args(argv)
    try:
        eng = Engine.from_dir(args.packs, args.models, args.max_distribution)
        if args.cmd == "list-formats":
            for name in eng.formats():
                p = eng.packs[name]
                sys.stdout.write("%s\t%s\t%s\n" % (p.name, p.version, p.wire))
            return 0
        context = None
        if args.context is not None:
            context = {}
            for item in args.context:
                key, eq, value = item.partition("=")
                if not eq or not key:
                    ap.error("--set takes <key>=<value>, got %r" % item)
                context[key] = value
        out = eng.convert(args.src, args.dst, sys.stdin.buffer.read(), context)
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
        return 0
    except GTError as e:
        sys.stderr.write("goat_transformers: %s\n" % e)
        return 2
    except OSError as e:
        sys.stderr.write("goat_transformers: %s\n" % e)
        return 2
