"""Load a chosen set of packs from a tree: a directory holding `model/` and
`packs/`, such as a checkout of the library or a bundle written by
`tools/goat-pkg bundle`."""

import os
import pathlib

from .engine import Engine
from .errors import BadDirective, UnknownFormat
from .modeldef import CORE, parse_model_text, scan_uses
from .packdef import parse_pack_text


def load_tree(root, packs, *, engine=None, max_distribution="controlled"):
    """Load the named packs from `<root>/packs/<name>/pack.def`, and before
    them the model modules they need from `<root>/model/*.def`: `core`, every
    module a named pack `uses`, and every module one of those `uses`, each
    after the modules it uses. Nothing else in the tree is loaded.

    `root` is a path, or what `importlib.resources.files()` returns, so a tree
    shipped as package data loads without a path on disk. `engine` is an
    engine to load into (a module it already holds is not loaded again);
    without one a new engine is made with `max_distribution`. Returns the
    engine."""
    if isinstance(root, (str, os.PathLike)):
        root = pathlib.Path(root)
    eng = engine if engine is not None else Engine(max_distribution=max_distribution)

    chosen = []
    for name in dict.fromkeys(packs):
        d = root.joinpath("packs").joinpath(name)
        f = d.joinpath("pack.def")
        if not f.is_file():
            raise UnknownFormat("no pack %r under %s" % (name, root.joinpath("packs")), format=name)
        pack = parse_pack_text(f.read_text(encoding="utf-8"), source=str(f))
        pack.path = str(d)
        chosen.append(pack)

    heads = {}  # module name -> (file, text, the modules it uses)
    model_dir = root.joinpath("model")
    if model_dir.is_dir():
        for f in sorted((f for f in model_dir.iterdir() if f.name.endswith(".def") and f.is_file()), key=lambda f: f.name):
            text = f.read_text(encoding="utf-8")
            module, uses = scan_uses(text)
            if module is not None:
                heads.setdefault(module, (f, text, uses))

    placing = set()

    def place(name):
        # a module no file declares is left to the pack's load: unknown-module
        if name in eng.models or name not in heads:
            return
        if name in placing:
            raise BadDirective("the 'uses' lines of the model modules form a cycle (at %s)" % name)
        placing.add(name)
        f, text, uses = heads[name]
        for used in uses:
            if used != name:
                place(used)
        placing.discard(name)
        module = parse_model_text(text, source=str(f), models=eng.models)
        module.path = str(f)
        eng.add_model(module)

    place(CORE)
    for pack in chosen:
        for used in pack.uses:
            place(used)
    for pack in chosen:
        eng.add(pack)
    return eng
