"""genio: how every generator in this directory writes its output.

A generator hands each file to an Output as text. The Output writes it as
UTF-8 with `\\n` line ends, whatever the platform and the locale, so the same
input gives the same bytes everywhere.

With `check=True` the Output writes nothing. It compares each file the
generator would write with the file that is there and records every
difference: a file that is missing, a file whose bytes differ, and a file the
generator would remove. `report()` prints them and gives the exit status. That
is the `--check` mode of every generator: it answers "is the committed output
what the generator writes today?" without touching the tree.

    out = genio.Output(args.out, check=args.check)
    out.write("packs/x/pack.def", text)
    text = out.read("packs/x/pack.def")       # what was just written, in either mode
    return out.report("x2pack")

Python 3 standard library only.
"""
import os
import sys


def add_arguments(parser, default_out=None, what="the checkout to write into"):
    """The two options every generator has: `--out DIR` and `--check`."""
    parser.add_argument("--out", metavar="DIR", default=default_out, required=default_out is None,
                        help=what + ("" if default_out is None else " (default: %(default)s)"))
    parser.add_argument("--check", action="store_true",
                        help="write nothing; compare what would be written with the files under --out "
                             "and exit 1 when any file differs, is missing or would be removed")


class Output:
    """The files of one generator run, under the directory `root`."""

    def __init__(self, root, check=False):
        self.root = os.path.abspath(root)
        self.check = check
        self.written = {}           # relative path -> bytes, in the order written
        self.removed = []           # relative paths removed, or that a real run would remove
        self.differences = []       # (relative path, what differs), check mode only

    def path(self, rel):
        """The absolute path of a relative output path. `rel` uses `/`."""
        return os.path.join(self.root, *rel.split("/"))

    def exists(self, rel):
        """True when the file is there now: written in this run, or on disk and not removed."""
        if rel in self.written:
            return True
        return rel not in self.removed and os.path.isfile(self.path(rel))

    def read(self, rel):
        """The text of a file as the run sees it: what this run wrote, else what is on disk."""
        if rel in self.written:
            return self.written[rel].decode("utf-8")
        if rel in self.removed:
            raise FileNotFoundError(rel)
        with open(self.path(rel), "rb") as fh:
            return fh.read().decode("utf-8")

    def write(self, rel, text):
        """Write `text` to `rel`, or in check mode compare it with the file there."""
        data = text.encode("utf-8")
        if rel in self.removed:
            self.removed.remove(rel)
        path = self.path(rel)
        if self.check:
            self.differences = [d for d in self.differences if d[0] != rel]
            if not os.path.isfile(path):
                self.differences.append((rel, "is missing"))
            else:
                with open(path, "rb") as fh:
                    have = fh.read()
                if have != data:
                    self.differences.append((rel, _first_difference(have, data)))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        self.written[rel] = data

    def remove(self, rel):
        """Remove a file of an earlier run; in check mode record that it would go."""
        was_written = self.written.pop(rel, None) is not None
        path = self.path(rel)
        if not os.path.isfile(path) and not was_written:
            return
        if rel not in self.removed:
            self.removed.append(rel)
        if self.check:
            if os.path.isfile(path):
                self.differences = [d for d in self.differences if d[0] != rel]
                self.differences.append((rel, "is not written by the generator and would be removed"))
        elif os.path.isfile(path):
            os.remove(path)

    def listdir(self, rel):
        """The file names in a directory as the run sees it, sorted."""
        path = self.path(rel)
        names = set(n for n in os.listdir(path) if os.path.isfile(os.path.join(path, n))) \
            if os.path.isdir(path) else set()
        prefix = rel.rstrip("/") + "/"
        names -= {r[len(prefix):] for r in self.removed if r.startswith(prefix)}
        names |= {r[len(prefix):] for r in self.written if r.startswith(prefix) and "/" not in r[len(prefix):]}
        return sorted(names)

    def report(self, name, stream=None):
        """Print the result of a check run and return the exit status: 0 when
        nothing differs. A run that is not a check returns 0."""
        stream = stream or sys.stderr
        if not self.check:
            return 0
        # a file a later write restored is not a difference
        differences = [(rel, what) for rel, what in self.differences
                       if not (what.endswith("would be removed") and rel in self.written)]
        for rel, what in differences:
            print("%s: --check: %s %s" % (name, rel, what), file=stream)
        if differences:
            print("%s: --check: %d of %d file(s) differ from what the generator writes"
                  % (name, len(differences), len(self.written) + len(self.removed)), file=stream)
            return 1
        print("%s: --check: ok, %d file(s) are what the generator writes" % (name, len(self.written)), file=stream)
        return 0


def _first_difference(have, want):
    """Where two byte strings first differ, as a line number of the file on disk."""
    limit = min(len(have), len(want))
    at = next((i for i in range(limit) if have[i] != want[i]), limit)
    line = have.count(b"\n", 0, at) + 1
    if at == limit and len(have) != len(want):
        return "differs: the generator writes %d bytes, the file has %d (same up to line %d)" % (
            len(want), len(have), line)
    return "differs at line %d" % line


def vector_main(name, description, build, argv=None):
    """The `main` of a script that writes hand-derived vectors: `build(out)`
    writes every file through the Output and returns {pack: files written}.
    Options are `--out` (default: the checkout this file is in) and `--check`;
    the checkout may also be given as one positional argument."""
    import argparse
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser = argparse.ArgumentParser(prog=name, description=description,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser, default_out=here)
    parser.add_argument("checkout", nargs="?", help="the same as --out")
    args = parser.parse_args(argv)
    out = Output(args.checkout or args.out, check=args.check)
    written = build(out)
    if not args.check:
        for pack, count in sorted(written.items()):
            print(pack, count)
    return out.report(name)
