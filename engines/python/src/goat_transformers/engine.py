"""decode / encode / convert over loaded packs (spec/engine-spec.md)."""

import importlib
import math
import os

from ._build import WIRES as BUILD_WIRES
from .errors import (
    GTError, BadDirective, DistributionRefused, DistributionViolation, DuplicateFormat, DuplicateModule, KeyTypeMismatch,
    MalformedWire, MessageCount,
    ModuleNotUsed, NoKind, TransformDecodeFailure, TransformEncodeFailure, UndeclaredKey, UnknownFormat,
    UnknownModule,
)
from .licence import Licences, check_profile, rank_name
from .modeldef import parse_model_text, scan_uses
from .packdef import CORE, DISTRIBUTIONS, load_pack, parse_pack_text, split_key
from . import parts
from .entity import Entity, Item, NoEntry, _build_via, _via_decode, _via_encode, apply_range, failure, via_may_fail
from .transforms import (
    canonical_value_text, read_int_text, read_number_text, read_typed, table_side_type, value_canon,
)

DERIVE_PASSES = 8  # spec 0.6: the pass repeats until it sets nothing, at most 8 times
MAX_ITEMS = 100000  # ruling 7b of 0.11: the default limit on the list items of one decode

# The codec of each wire of this build (spec 0.24, ruling 1): `wire_<name>`.
# A build leaves out the modules of the wires it does not have; a pack on such
# a wire is refused at load (`unknown-wire`), so no other code path asks for it.
_CODECS = {w: importlib.import_module(".wire_" + w, __package__) for w in BUILD_WIRES}
if "bits" in BUILD_WIRES:
    from . import wire_seq  # the sequential layout, part of `bits` (ruling 1d)
if "json" in BUILD_WIRES or "geojson" in BUILD_WIRES:
    from .jsonio import Num as _Num, RawJSON as _RawJSON, dump_as_written as _dump_as_written
else:
    class _Num(str):
        """No value is a JSON number in a build without `json` and `geojson`."""


def _model_files(models_dir, only=None, skip=None):
    """The module files of a directory in loading order: `core.def` first,
    whatever its name sorts as (0.6 ruling 9), then the others in byte order
    of file name, each after the modules its `uses` lines name (0.8). A cycle
    is `bad-directive`. A used module no file declares is left to the load,
    which reports `unknown-module`. With `only`, a set of module names: the
    files of those modules and of the modules they use, and no other.

    -> [(path, text)]: each file is read once, here, and its text is what the
    load parses (spec 0.25, ruling 1d). With `skip`, a set of file names:
    those files are as if they were not there (spec 0.29, ruling 3e)."""
    names = sorted(
        (n for n in os.listdir(models_dir) if n.endswith(".def") and os.path.isfile(os.path.join(models_dir, n))),
        key=lambda n: (n != CORE + ".def", os.fsencode(n)),
    )
    if skip:
        names = [n for n in names if n not in skip]
    uses = {}
    texts = {}
    by_module = {}
    for n in names:
        with open(os.path.join(models_dir, n), "r", encoding="utf-8") as fh:
            texts[n] = fh.read()
        module, used = scan_uses(texts[n])
        uses[n] = used
        if module is not None:
            by_module.setdefault(module, n)
    order = []
    state = {}  # file name -> 1 while its used modules are being placed, 2 when placed

    def place(n):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            raise BadDirective("the 'uses' lines of the model modules form a cycle (at %s)" % n)
        state[n] = 1
        for m in uses[n]:
            dep = by_module.get(m)
            if dep is not None and dep != n:
                place(dep)
        state[n] = 2
        order.append((os.path.join(models_dir, n), texts[n]))

    if only is None:
        for n in names:
            place(n)
    else:
        wanted = {by_module[m] for m in only if m in by_module}
        for n in names:
            if n in wanted:
                place(n)
    return order


def _model_order(models_dir, only=None):
    """The paths of `_model_files`, in the same order."""
    return [path for path, _ in _model_files(models_dir, only)]


def _model_from_text(text, path, models, max_distribution):
    """A module file's text, read once by `_model_files`, parsed as
    `load_model_file` parses the file."""
    module = parse_model_text(text, source=path, models=models, max_distribution=max_distribution)
    module.path = path
    return module


def requires_hold(kind, have, lists):
    """0.5 and 0.20: the entity holds every `requires` key, has every `requires`
    list with at least one item, and holds each `<key>=<values>` term's key with
    a value whose canonical text is listed."""
    for key in kind.requires_keys:
        if key not in have:
            return False
    for name in kind.requires_lists:
        if not lists.get(name):  # present, with at least one item
            return False
    for vc in kind.requires_eq:
        if vc.key not in have or value_canon(have[vc.key], vc.key_type) not in vc.canon:
            return False
    return True


class _Enc:
    """One encoded scope: `values` maps a field line's index in the plan's
    lines to its encoded wire value, `groups` a group line's index to the
    encoded scope of each item of its list (absent when the entity has no such
    list)."""

    __slots__ = ("plan", "values", "groups", "sentinels", "defaulted", "errors", "have", "suppressed", "nulls",
                 "omitted")

    def __init__(self, plan, have=None):
        self.plan = plan
        self.values = {}
        self.groups = {}
        self.sentinels = set()  # the indices in `values` that hold a sentinel (0.9), not a value
        self.defaulted = set()  # the indices in `values` that hold a `default`, not the scope's value
        self.errors = {}        # index of a line of a gate block -> its encode error, raised if the block is held
        self.have = have        # the scope's keys (bits: whether a gate block is open, 0.17)
        self.suppressed = set() # the indices of field lines whose `with` key the scope does not hold (0.18)
        self.nulls = set()      # the indices of `null` lines whose key is absent, with no default or sentinel (0.56)
        self.omitted = set()    # the indices in `values` that `implicit` leaves out (0.56)


def _read_range(f, key_type, fmt):
    """The arguments of `range <min> <max> [wrap]` read as the key's type
    (0.56): `bad-directive` on a key that is not `int` or `float`, on an `int`
    key's argument that is not integer text, and when `<min>` is not less than
    `<max>`. -> (min, max, wrap)."""
    lo_text, hi_text, wrap = f.range

    def bad(msg):
        return BadDirective("field option 'range' %s, at line %d" % (msg, f.lineno), format=fmt, locator=f.locator)

    if key_type not in ("int", "float"):
        raise bad("is on key %s, which is %s, not int or float" % (f.key, key_type))
    read = read_int_text if key_type == "int" else read_number_text
    try:
        lo, hi = read(lo_text), read(hi_text)
    except ValueError as e:
        raise bad("takes %s text: %s" % ("integer" if key_type == "int" else "number", e))
    if not lo < hi:
        raise bad("has <min> %s not less than <max> %s" % (lo_text, hi_text))
    return lo, hi, wrap


def _is_proto_default(enc):
    """Whether a protobuf `(wire type, payload)` holds the proto3 default of
    its wire type (0.56): the varint 0, +0.0 (every byte zero), the empty text."""
    payload = enc[1]
    if isinstance(payload, int):
        return payload == 0
    return not any(payload)


def _check_unread_numbers(doc, read, fmt):
    """Ruling 27 of 0.15: on `json` a number outside the double range that no
    field line reads, anywhere in the document, is `malformed-wire`."""
    stack = [doc]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, _Num) and id(node) not in read and math.isinf(float(node)):
            raise MalformedWire("number %s is outside the double range" % (node[:40],), format=fmt)


def _ref_for(pack, first, second):
    """The first of two recorded kinds that names `pack`'s format, or None (0.34, Encode)."""
    if first is not None and first[0] == pack.name:
        return first
    if second is not None and second[0] == pack.name:
        return second
    return None


class Engine:
    def __init__(self, packs=(), models=(), max_distribution="controlled", max_items=MAX_ITEMS):
        self.packs = {}
        self.models = {}
        self.licences = {}  # format -> (directory, licence, profile), filled by from_dir with a profile
        self._derives = None
        self._kind_keys = {}  # (format, kind name) -> the keys of the kind (0.94), cleared by every load
        self._profile_bound = False  # a load with a profile has set the limit to `public` (0.93, ruling 6)
        self.set_max_distribution(max_distribution)
        self.set_max_items(max_items)
        for m in models:
            self.add_model(m)
        for p in packs:
            self.add(p)

    def set_max_distribution(self, limit):
        """The distribution limit: `controlled` (default) loads everything;
        `public` refuses every controlled module and pack. After a load with
        a profile the limit is the lower of `public` and `limit` (spec 0.93,
        ruling 6): setting `controlled` then is no error and has no effect."""
        if limit not in DISTRIBUTIONS:
            raise ValueError("max distribution must be one of %s, got %r" % (", ".join(DISTRIBUTIONS), limit))
        self.max_distribution = "public" if self._profile_bound else limit

    def _begin_profile_load(self, profile):
        """The start of a load with a profile (spec 0.93, rulings 5 and 6), in
        this order: a name not one of the three is `bad-licence`, the limit
        unchanged; then, when this instance already holds a controlled module
        or pack, `distribution-refused` before anything is read, the limit
        unchanged; both leave no trace; then the limit is `public` from here on, also when
        the load fails later. -> the rank of the profile."""
        rank = check_profile(profile)
        held = sorted(m for m, mod in self.models.items() if mod.distribution == "controlled")
        held += sorted(f for f, p in self.packs.items() if p.distribution == "controlled")
        if held:
            raise DistributionRefused(
                "a load with a profile on an engine that holds controlled %s %s"
                % ("module or pack" if len(held) == 1 else "modules and packs", ", ".join(held))
            )
        self._profile_bound = True
        self.max_distribution = "public"
        return rank

    def set_max_items(self, limit):
        """The limit on list items one decode holds, counted over every list
        at every nesting level (ruling 7 of 0.11): an integer of 0 or more,
        100,000 by default. The decode that would hold one item more fails
        with `malformed-wire`; `encode` is not limited."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("max items is an integer of 0 or more, got %r" % (limit,))
        self.max_items = limit

    def _within_limit(self, distribution):
        return DISTRIBUTIONS.index(distribution) <= DISTRIBUTIONS.index(self.max_distribution)

    def load_model(self, text, *, source="model.def"):
        """Parse one model module text and load it."""
        module = parse_model_text(text, source=source, models=self.models, max_distribution=self.max_distribution)
        self.add_model(module)
        return module

    def add_model(self, module):
        if not self._within_limit(module.distribution):
            raise DistributionRefused(
                "module %s is %s; this engine's limit is %s"
                % (module.name, module.distribution, self.max_distribution)
            )
        for m in module.uses:
            if m not in self.models and m != module.name:
                raise UnknownModule("module %s uses module %s, which is not loaded" % (module.name, m))
        if module.distribution == "public":  # a public module uses only public modules (0.8)
            for m in module.uses:
                if m != module.name and self.models[m].distribution != "public":
                    raise DistributionViolation(
                        "public module %s uses %s module %s" % (module.name, self.models[m].distribution, m)
                    )
        if module.name in self.models:
            raise DuplicateModule(
                "module %s loaded twice (%s, %s)" % (module.name, self.models[module.name].path, module.path)
            )
        self.models[module.name] = module
        self._derives = None

    def load(self, text, *, source="pack.def"):
        """Parse one pack.def text and load it against the modules loaded so far."""
        pack = parse_pack_text(text, source=source)
        self.add(pack)
        return pack

    def add(self, pack):
        """Check a parsed pack against the loaded modules, in the order the
        specification states (spec/engine-spec.md, Version 0.4, "Loading")."""
        fmt = pack.name
        if not self._within_limit(pack.distribution):
            raise DistributionRefused(
                "pack is %s; this engine's limit is %s" % (pack.distribution, self.max_distribution), format=fmt
            )
        used = [CORE] + [m for m in pack.uses if m != CORE]
        for m in used:
            if m not in self.models:
                raise UnknownModule("module %s is not loaded" % m, format=fmt)
        if pack.distribution == "public":
            for m in used:
                if self.models[m].distribution != "public":
                    raise DistributionViolation(
                        "public pack uses %s module %s" % (self.models[m].distribution, m), format=fmt
                    )
        # Every `field` and `group` line of every kind and of every group
        # body, every `requires` key and every `default` key, in line order.
        # `requires` and `default` keys are checked like mapped keys, but have
        # no transform. A list shares the key namespace of its module (0.7).
        keyed = [(key, ref, split_key(key)) for key, ref in pack.key_refs]
        for key, ref, (m, _) in keyed:
            if m not in used:
                raise ModuleNotUsed(
                    "key %s is of module %s, which the pack does not name in a 'uses' line" % (key, m),
                    format=fmt, locator=getattr(ref, "locator", None),
                )
        for key, ref, (m, k) in keyed:
            module = self.models[m]
            if k not in module.keys and k not in module.lists:
                role = (
                    "required" if ref is None else "mapped" if getattr(ref, "is_field", False)
                    else "mapped by a group" if getattr(ref, "is_group", False)
                    else "bound by 'when ... as'" if getattr(ref, "is_as", False) else "given a default"
                )
                raise UndeclaredKey(
                    "module %s declares no key %r (%s as %s)" % (m, k, role, key),
                    format=fmt, locator=getattr(ref, "locator", None),
                )
        for vc in pack.value_checks:  # 0.20: a list key with `=`, over every line
            m, k = split_key(vc.key)
            if vc.what == "requires" and k in self.models[m].lists:
                raise BadDirective(
                    "'requires %s=...' names a list; a list takes no value, at line %d" % (vc.key, vc.lineno),
                    format=fmt, locator=vc.key,
                )
        table_types = {}
        for key, f, (m, k) in keyed:
            if f is None:
                continue
            module = self.models[m]
            if getattr(f, "is_group", False):
                if k not in module.lists:
                    raise KeyTypeMismatch(
                        "a 'group' names %s, which is a scalar key, not a list" % key, format=fmt, locator=f.locator
                    )
                continue
            if getattr(f, "is_as", False):  # 0.30: a `when ... as` key is a scalar `int` key (ruling 17)
                if k in module.lists:
                    raise KeyTypeMismatch(
                        "'when ... as' names %s, which is a list, not a scalar key" % key, format=fmt, locator=key
                    )
                if module.keys[k].type != "int":
                    raise KeyTypeMismatch(
                        "'when ... as' names %s, which is declared %s, not int" % (key, module.keys[k].type),
                        format=fmt, locator=key,
                    )
                continue
            if not getattr(f, "is_field", False):
                continue
            if k in module.lists:
                raise KeyTypeMismatch(
                    "a 'field' names %s, which is a list, not a scalar key" % key, format=fmt, locator=f.locator
                )
            want = module.keys[k].type
            if f.via is not None:
                # With a table, the key's type is compared with the table's model
                # side. An all-integer table on a `float` key is accepted and its
                # model side read as float (0.6 ruling 4).
                have = table_types.get(f.via)
                if have is None:
                    have = table_types[f.via] = table_side_type([model for _, model in pack.tables[f.via]])
                what = "the model side of table %s is %s" % (f.via, have)
                if have == "int" and want == "float":
                    have = want
            else:
                have = f.transform.yields
                what = "transform %s yields %s" % (f.transform.name, have)
            if have != want:
                raise KeyTypeMismatch(
                    "key %s is declared %s; %s" % (f.key, want, what), format=fmt, locator=f.locator
                )
            f.key_type = want
            if getattr(f, "range", None) is not None:
                f.rng = _read_range(f, want, fmt)
            if f.via is not None:
                _build_via(f, pack.tables[f.via])
        for key, d, (m, k) in keyed:
            if d is None or any(getattr(d, a, False) for a in ("is_field", "is_group", "is_as")):
                continue
            module = self.models[m]
            if k in module.lists:
                raise KeyTypeMismatch("a 'default' names %s, which is a list" % key, format=fmt)
            want = module.keys[k].type
            try:
                d.value = read_typed(d.text, want)
            except (ValueError, OverflowError):
                raise KeyTypeMismatch(
                    "default for key %s is not a %s value: %r" % (key, want, d.text), format=fmt
                )
        cases_seen = {}  # id(switch) -> the canonical values of its cases so far
        for vc in sorted(pack.value_checks, key=lambda c: c.lineno):  # 0.20 rulings 1, 17 to 19
            m, k = split_key(vc.key)
            want = self.models[m].keys[k].type
            canon = []
            for v in vc.values:
                try:
                    canon.append(canonical_value_text(v, want))
                except (ValueError, OverflowError):
                    raise KeyTypeMismatch(
                        "%s value %r for key %s is not a %s value, at line %d"
                        % ("a 'requires'" if vc.what == "requires" else "a 'case'", v, vc.key, want, vc.lineno),
                        format=fmt, locator=vc.key,
                    )
            if vc.what == "case":
                seen = cases_seen.setdefault(id(vc.switch), set())
                mine = set()
                for c in canon:
                    if c in seen or c in mine:
                        raise BadDirective(
                            "the value %s is listed twice in the cases of one switch, at line %d" % (c, vc.lineno),
                            format=fmt, locator=vc.key,
                        )
                    mine.add(c)
                seen.update(mine)
                vc.switch.key_type = want
            vc.key_type = want
            vc.canon = frozenset(canon)
            if vc.what == "case":
                vc.target.canon = vc.canon
        if pack.late_errors:  # 0.33: the `at` checks run last among the module checks (ruling 25)
            raise pack.late_errors[0]
        kinds = pack.kinds
        if pack.seq is not None:  # a sequential pack: the kinds of the message and of every group body
            kinds = []
            for body in pack.seq.bodies():
                body._defaults.clear()
                kinds.extend(body.kinds)
        for kind in kinds:  # `requires <list>` holds when the list has at least one item
            if kind.requires:
                names = [(key, split_key(key)) for key in kind.requires]
                kind.requires_lists = tuple(key for key, (m, k) in names if k in self.models[m].lists)
                kind.requires_keys = tuple(key for key, (m, k) in names if k not in self.models[m].lists)
        pack._plans.clear()
        if pack.name in self.packs:  # ruling 5 of 0.11: the last check; the first pack stays loaded
            raise DuplicateFormat(
                "a pack with format name %r is already loaded (%s, %s)" % (pack.name, self.packs[pack.name].path,
                                                                          pack.path),
                format=pack.name,
            )
        self.packs[pack.name] = pack
        self._kind_keys = {}  # an inner line's keys depend on the packs loaded (0.94)

    @classmethod
    def from_dir(cls, packs_dir, models_dir=None, max_distribution="controlled", packs_only=None, profile=None,
                 with_inner=False):
        """Load every `<models_dir>/*.def` in byte order of file name, then every
        `<packs_dir>/<format>/pack.def`. `models_dir` defaults to the `model`
        directory beside `packs_dir`.

        With `packs_only`, the names of pack directories under `packs_dir`:
        load those packs only, and of the modules only `core`, the modules the
        packs name in `uses` lines and the modules those use. A name with no
        `<packs_dir>/<name>/pack.def` is `unknown-format`. With `with_inner`
        (spec 0.34, Vectors), also the packs the `inner` lines of those packs
        name, and so on for the packs loaded that way; a name with no
        directory under `packs_dir` is skipped (its use is `unknown-format`).

        With `profile`, one of `open`, `open+copyleft` and `everything`
        (spec 0.29): before anything is loaded, `<packs_dir>/../licences.toml`
        and the licence of every module file are read, and a module or pack
        whose profile the profile does not hold is not loaded, as if it were
        not there (a pack is skipped before it is parsed). A licence file that
        cannot be read, or a profile not one of the three, is `bad-licence`.
        Without `profile` no licence file is read. `licences` maps each loaded
        format to its pack's `(directory, licence, profile)` when a profile
        was given."""
        if profile is not None:
            check_profile(profile)  # before anything is read, also the limit (3a)
        eng = cls(max_distribution=max_distribution)
        eng.load_dir(packs_dir, models_dir, packs_only=packs_only, profile=profile, with_inner=with_inner)
        return eng

    def load_dir(self, packs_dir, models_dir=None, packs_only=None, profile=None, with_inner=False):
        """`from_dir` on this engine: the modules and packs loaded so far stay,
        and the load is bounded by this engine's distribution limit. With
        `profile` (spec 0.93, ruling 6): a name not one of the three is
        `bad-licence`; an engine that already holds a controlled module or
        pack refuses the load (`distribution-refused`) before anything is
        read; then the limit is `public` for this load and every later one,
        whatever the caller sets."""
        eng = self
        lic = None
        if profile is not None:
            limit = eng._begin_profile_load(profile)  # before anything is read (3a)
        if models_dir is None:
            models_dir = os.path.join(packs_dir, os.pardir, "model")
        skip = None
        if profile is not None:
            lic = Licences(packs_dir, models_dir).read()
            skip = lic.skipped_modules(limit)
        held = {}

        def reach(name):
            """The pack in directory `name`, or None when the profile skips it (3d)."""
            d = os.path.join(packs_dir, name)
            if lic is not None:
                licence, rank = lic.pack(d)
                if rank > limit:
                    return None
            pack = load_pack(d)
            if lic is not None:
                held[pack.name] = (name, licence, rank_name(rank))
            return pack

        if packs_only is None:
            only = None
            packs = [
                p for p in (
                    reach(name) for name in sorted(os.listdir(packs_dir))
                    if os.path.isfile(os.path.join(packs_dir, name, "pack.def"))
                ) if p is not None
            ]
        else:
            if isinstance(packs_only, str):
                packs_only = [packs_only]
            packs = []
            wanted = sorted(set(packs_only))
            for name in wanted:
                d = os.path.join(packs_dir, name)
                if not name or name in (os.curdir, os.pardir) or os.path.basename(name) != name or (
                    not os.path.isfile(os.path.join(d, "pack.def"))
                ):
                    raise UnknownFormat("no pack named %r in the packs directory" % name, format=name)
            named = set(wanted)
            while wanted:
                more = []
                for name in wanted:
                    pack = reach(name)
                    if pack is None:
                        continue
                    packs.append(pack)
                    for inner in pack.inners if with_inner else ():
                        if inner not in named and os.path.basename(inner) == inner and inner not in (
                                os.curdir, os.pardir) and os.path.isfile(os.path.join(packs_dir, inner, "pack.def")):
                            named.add(inner)
                            more.append(inner)
                wanted = sorted(more)
            only = {CORE}
            for pack in packs:
                only.update(pack.uses)
        if os.path.isdir(models_dir):
            for path, text in _model_files(models_dir, only, skip):
                eng.add_model(_model_from_text(text, path, eng.models, eng.max_distribution))
        for pack in packs:
            eng.add(pack)
        eng.licences.update(held)

    def formats(self):
        return sorted(self.packs)

    def pack(self, fmt):
        p = self.packs.get(fmt)
        if p is None:
            raise UnknownFormat("no pack loaded for %r (loaded: %s)" % (fmt, ", ".join(self.formats())), format=fmt)
        return p

    def model_keys(self, fmt):
        """The union of mapped keys over common and all kinds, in first
        appearance order; a list as `<list>[]`, an item key as `<list>[].<key>`.
        An `inner` line (0.34) whose pack passes the checks of the line adds,
        at its place, the entries of that pack; computed when asked for."""
        pack = self.pack(fmt)
        if not pack.inners:
            return pack.model_keys()
        out = []
        seen = set()

        def add(name):
            if name not in seen:
                seen.add(name)
                out.append(name)

        pack.seq.model_keys(add, inner=lambda name: self._inner_keys(pack, name))
        return out

    # --- inner lines (0.34) ------------------------------------------------

    def _inner_pack(self, outer, name, run=False):
        """The checks made when decode or encode reaches an `inner` line, in
        their order (0.34, "Reaching the inner line"; `run`: ruling 16 of
        0.92). -> the inner pack."""
        inner = self.packs.get(name)
        if inner is None:
            raise UnknownFormat("pack %s names inner format %r, which is not loaded" % (outer.name, name),
                                format=name)
        if inner.wire != "bits" or inner.armor == "sixbit" or inner.uper:
            raise BadDirective(
                "inner pack %s is %s; an inner pack is on the bits wire, with neither 'armor sixbit' nor 'encoding uper'"
                % (name, "on the %s wire" % inner.wire if inner.wire != "bits" else
                       "under 'armor sixbit'" if inner.armor == "sixbit" else "a UPER pack"),
                format=name, locator=name,
            )
        if run and (inner.seq is None or not inner.framing):
            raise BadDirective("inner pack %s of an 'inner ... run' line is not 'layout sequential' with a "
                               "'framing self' line" % name, format=name, locator=name)
        if inner is outer or inner.inners:
            raise BadDirective(
                "inner pack %s %s; one layer only" % (
                    name, "is the outer pack" if inner is outer else "has an 'inner' line of its own"),
                format=name, locator=name,
            )
        if outer.distribution == "public" and inner.distribution != "public":
            raise DistributionViolation(
                "public pack %s names %s inner pack %s" % (outer.name, inner.distribution, name),
                format=outer.name, locator=name,
            )
        return inner

    def _inner_keys(self, outer, name):
        """The entries an `inner` line adds to `model_keys` (0.34, Capability):
        none when its pack does not pass the checks of the line."""
        try:
            inner = self._inner_pack(outer, name)
        except GTError:
            return ()
        return inner.model_keys()

    def _decode_layer(self, pack, data, left, discard, exact):
        """The inner message of an `inner` line: `data` (bytes) decoded by the
        inner pack, with the item budget `left` the outer lines left (None:
        no limit). `discard` names the lists the outer entity holds already:
        their counts are checked, their items not counted (ruling 7 of 0.34).
        `exact`: bytes after the inner message are `malformed-wire`."""
        return self._decode_pack(pack, data.hex(), (1 << 62) if left is None else left, discard, exact)

    def _encode_layer(self, pack, entity):
        """The inner message of an `inner` line, as bytes. The kind is the one
        `Entity.inner_kind` names, else `Entity.kind`, else by `requires`."""
        ref = _ref_for(pack, entity.inner_kind, entity.kind)
        out = self._encode_pack(pack, entity, ref)
        return bytes.fromhex(out.decode("ascii"))

    # --- capability --------------------------------------------------------

    def capability(self, from_fmt, to_fmt):
        """How much of `from_fmt` a conversion to `to_fmt` carries
        (spec/engine-spec.md, Capability): `carried` are the keys of
        `model_keys(from_fmt)` that `to_fmt` also maps, `dropped` the rest,
        both in the source's order; the grade is `full` when nothing is
        dropped, `none` when nothing carries, else `partial`."""
        theirs = set(self.model_keys(to_fmt))
        mine = self.model_keys(from_fmt)
        carried = [k for k in mine if k in theirs]
        dropped = [k for k in mine if k not in theirs]
        grade = "none" if not carried else ("full" if not dropped else "partial")
        return {"from": from_fmt, "to": to_fmt, "carried": carried, "dropped": dropped, "grade": grade}

    def capability_matrix(self):
        """`capability` for every ordered pair of distinct loaded formats."""
        fmts = self.formats()
        return [self.capability(a, b) for a in fmts for b in fmts if a != b]

    # --- decode ------------------------------------------------------------

    def _select_decode_kind(self, pack, codec, msg):
        """spec 0.5, "Decode", steps 1 and 2. On the xml wire a kind is
        considered only when the document's root element is the kind's root
        (its own, else the pack's), before its `when` lines (0.6)."""
        for w in pack.plan(None).whens:
            if not codec.when_holds(pack, msg, w):
                raise NoKind(
                    "a common 'when' does not hold (%s %s)" % (w.locator, "present" if w.present else w.value),
                    format=pack.name, locator=w.locator,
                )
        kinds = pack.kinds_for_root(msg.name) if pack.wire == "xml" else pack.kinds
        for kind in kinds:
            for w in kind.when_lines:
                if not codec.when_holds(pack, msg, w):
                    break
            else:
                return kind
        raise NoKind("the message matches no kind of the format", format=pack.name)

    @staticmethod
    def _decode_value(wire, transform, raw):
        """Run one field's transform over its raw wire value. Raises ValueError.
        Ruling 2c and 2d of 0.11: on `xml`, and on `geojson` when the member is
        a JSON string, `int` and `float` read integer and number text; a JSON
        number is read by the JSON grammar.
        On `json` and `geojson` a mapped number outside the double range fails
        every transform but `iscale`, which reads it exactly (ruling 27 of
        0.15)."""
        if isinstance(raw, _Num) and not getattr(transform, "exact", False) and math.isinf(float(raw)):
            raise ValueError("number %s is outside the double range" % (raw[:40],))
        if wire in ("bits", "protobuf", "text", "tlv", "cbor"):
            return transform.decode(raw)
        if wire == "xml":
            return transform.decode(raw)
        if wire == "geojson":
            if not isinstance(raw, str):
                raise ValueError("not a JSON scalar string or number")
            if getattr(transform, "number_only", False) and not isinstance(raw, _Num):
                raise ValueError("%s needs a JSON number" % transform.name)  # ruling 23 of 0.15
            if isinstance(raw, _Num) and hasattr(transform, "decode_json"):
                return transform.decode_json(str(raw))
            return transform.decode(str(raw))
        # json: the JSON type must be the one the transform takes.
        if transform.kind == "bool":
            return transform.decode(raw)
        if transform.kind == "number":
            if not isinstance(raw, _Num):
                raise ValueError("%s needs a JSON number" % transform.name)
            return transform.decode_json(str(raw))
        if not isinstance(raw, str) or isinstance(raw, _Num):
            raise ValueError("%s needs a JSON string" % transform.name)
        return transform.decode(raw)

    def decode(self, fmt, data, max_items=None):
        """Message to Entity. `max_items` sets the limit on list items for this
        call (ruling 7 of 0.11); by default the engine's (`set_max_items`)."""
        pack = self.pack(fmt)
        limit = self.max_items if max_items is None else max_items
        return self._decode_pack(pack, data, limit)

    @staticmethod
    def _text(pack, data):
        fmt = pack.name
        if isinstance(data, (bytes, bytearray)):
            try:
                data = bytes(data).decode("utf-8")
            except UnicodeDecodeError as e:
                raise MalformedWire("input is not UTF-8: %s" % e, format=fmt)
        elif not data.isascii():
            try:
                data.encode("utf-8")
            except UnicodeEncodeError:  # a str holding a lone surrogate
                raise MalformedWire("input is not UTF-8 text: it holds a lone surrogate", format=fmt)
        return data

    def _decode_pack(self, pack, data, limit, discard=(), exact=False):
        fmt = pack.name
        data = self._text(pack, data)
        if pack.seq is not None:
            return wire_seq.decode(pack, data, limit, self, discard, exact)
        wire = pack.wire
        codec = _CODECS[wire]
        if wire == "geojson":
            obs = codec.read(pack, data)
            msg = codec.Top()
            for loc, val in obs:
                msg.setdefault(loc, val)
        else:
            msg = codec.parse(pack, data)
            if wire == "xml" and not pack.kinds:
                codec.check_root(pack, msg)  # in a pack with kinds a root of no kind is `no-kind` (0.6 ruling 11)

        ent = Entity()
        kind = None
        if pack.kinds:
            kind = self._select_decode_kind(pack, codec, msg)
            ent.kind = (pack.name, kind.name)
        plan = pack.plan(kind)
        if wire == "bits":
            codec.check_length(pack, msg, plan)
        elif wire == "tlv" or wire == "cbor":
            # tlv: the nested sets of the selected scope, after the kind (0.13);
            # cbor: Reading step 8 for every line of the selected scope (0.28)
            codec.walk(pack, msg, plan)

        failures = []  # (key, locator, reason) of every field that could not be decoded
        budget = [limit]  # the items this decode may still hold (ruling 7 of 0.11)
        read = set() if wire == "json" else None
        keep_in_residue = self._decode_scope(
            pack, wire, codec, plan, msg, ent.fields, ent.lists, failures, "", budget, read, discard
        )
        if read is not None:
            _check_unread_numbers(msg, read, fmt)
        if exact:  # 0.34, an inner message: ahead of any transform-decode (ruling 17)
            codec.check_end(pack, msg, plan)

        mapped = plan.mapped - keep_in_residue if keep_in_residue else plan.mapped
        res = None
        if wire == "xml" or wire == "json":
            res = codec.residue(pack, msg, mapped)
        elif wire == "text" or wire == "tlv":
            res = codec.residue(pack, msg, plan)
        elif wire == "cbor":
            res = codec.residue(pack, msg, plan, mapped)
        elif wire == "geojson":
            res = {}
            for loc, val in obs:
                if loc in res or loc in mapped:
                    continue
                # 0.1 behaviour, kept by 0.5 ruling 28 and stated by 0.6 ruling
                # 13: a number keeps its text as written and comes back as a
                # string, as does a boolean; arrays and objects come back as
                # they were; `null` is dropped.
                if val is None:
                    continue
                if isinstance(val, _Num):
                    val = str(val)
                elif val is True or val is False:
                    val = "true" if val else "false"
                elif not isinstance(val, str):
                    val = _RawJSON(_dump_as_written(val))
                res[loc] = val
        if res:
            ent.residue[pack.name] = res
        if failures:
            raise TransformDecodeFailure(
                "%d field(s) could not be decoded" % len(failures), format=fmt, entity=ent, absent=failures
            )
        return ent

    def _decode_scope(self, pack, wire, codec, plan, ctx, fields, lists, failures, prefix, budget, read=None,
                      discard=(), dropped=False):
        """Decode one scope (the message, or one item of a group) from its wire
        context into `fields` and `lists`; the fields that could not be decoded
        are added to `failures`. -> the locators of `type` fields whose native
        code has no `typemap` entry, or None.

        A key mapped by several lines takes its value from the earliest line
        whose locator is present on the wire and whose transform succeeds
        (0.6, "One key at several locators"). That line's value table, if
        any, is then applied; a value with no entry fails the decode. A line
        whose transform fails is an error only when no line of its key
        succeeds (0.6 ruling 5, ruling 10 of 0.7).

        `read`, on `json`, collects the identity of every number a field line
        reads, so that a number outside the double range that none reads is
        found afterwards (ruling 27 of 0.15).

        `discard` names the lists the outer entity of an inner message holds;
        `dropped` is true inside the items of one (rulings 7, 21 and 22 of
        0.34): no item is counted, every count read from the wire is checked
        against the budget before the list, and of the failures only a value
        with no table entry is an error."""
        settled = set()  # keys whose line has been chosen
        failed = None    # [(key, locator, reason, final)]
        keep_in_residue = None
        n2c = pack.native_to_cot
        get = codec.get
        # 0.17: a line of a gate block that does not hold counts as a line whose locator is absent
        held = codec.gates_held(pack, ctx, plan) if plan.gates else None
        walked = wire == "protobuf" or wire == "cbor"  # a path that does not parse is `malformed-wire`
        part_groups = parts.groups_of(plan)
        part_places = {g.parts[0].locator for g in part_groups} if part_groups else ()
        for f in plan.fields:
            key = f.key
            done = key in settled
            # 0.64 ruling 26: a later line of the key still fails on a missing table entry
            if held is not None and f.gate is not None and not held[f.gate]:
                continue
            if done and not via_may_fail(f):
                if read is not None or walked:  # ruling 27: what the wire states of the line holds
                    raw = get(pack, ctx, f)
                    if read is not None and isinstance(raw, _Num):
                        read.add(id(raw))
                continue
            raw = get(pack, ctx, f)
            if read is not None and isinstance(raw, _Num):
                read.add(id(raw))
            if raw is None:
                continue
            if f.absent is not None and codec.is_absent(pack, f, raw):
                continue  # a sentinel: the line yields no value, as if its locator were absent (0.9)
            try:
                value = self._decode_value(wire, f.transform, raw)
            except ValueError as e:
                if failed is None:
                    failed = []
                failed.append((key, f.locator, str(e), False))
                continue
            if f.via_dec is not None:
                try:
                    value = _via_decode(f, value)
                except ValueError as e:
                    if f.unlisted and isinstance(e, NoEntry):
                        continue  # 0.64: counts as a line whose place is absent
                    settled.add(key)
                    if failed is None:
                        failed = []
                    failed.append((key, f.locator, str(e), True))
                    continue
            if done:
                continue
            settled.add(key)
            if n2c and key == "type":
                if value in n2c:
                    value = n2c[value]
                elif f.locator not in part_places:  # ruling 14 of 0.64
                    if keep_in_residue is None:
                        keep_in_residue = set()
                    keep_in_residue.add(f.locator)
            fields[key] = value
        for g in part_groups:  # 0.64: the `const` parts, checked on decode (ruling 4)
            for ln in g.consts:
                raw = get(pack, ctx, ln)
                if raw is None:
                    continue
                try:
                    parts.check_const(ln, self._decode_value(wire, parts.WHOLE, raw))
                except ValueError as e:
                    if failed is None:
                        failed = []
                    failed.append((ln.locator, ln.locator, str(e), True))
        if failed:
            failures.extend(
                failure(prefix + k, loc, why, final) for k, loc, why, final in failed
                if final or (k not in settled and not dropped)
            )
        # For each group of the scope, in line order: one item per occurrence.
        # The number of items is compared with what the limit still allows
        # before any item is read (ruling 7 of 0.11); on `bits` the count read
        # from the wire is compared before the items are laid out.
        count = getattr(codec, "count", None)
        for g in plan.groups:
            free = dropped or (discard and g.list in discard)
            if count is not None and not (free and g.count_loc is None):  # ruling 7 of 0.34: not read from the wire
                n = count(pack, ctx, g)
                if n > budget[0]:
                    raise self._over_limit(pack, g, n, budget)
            contexts = codec.items(pack, ctx, g)
            if contexts is None:
                continue  # the list is absent
            if not free:
                if len(contexts) > budget[0]:
                    raise self._over_limit(pack, g, len(contexts), budget)
                budget[0] -= len(contexts)
            item_plan = g.plan
            out = []
            for n, item_ctx in enumerate(contexts):
                item = Item()
                self._decode_scope(
                    pack, wire, codec, item_plan, item_ctx, item.fields, item.lists, failures,
                    "%s%s[%d]." % (prefix, g.list, n), budget, read, (), free,
                )
                out.append(item)
            lists[g.list] = out
        return keep_in_residue

    def _over_limit(self, pack, group, n, budget):
        return MalformedWire(
            "list %s has %d item(s); the limit on list items allows %d more" % (group.list, n, budget[0]),
            format=pack.name, locator=group.locator,
        )

    # --- complete ------------------------------------------------------------

    def _key_type(self, key):
        """The declared type of a model key, or None when no loaded module declares it."""
        m, k = split_key(key)
        module = self.models.get(m)
        decl = module.keys.get(k) if module is not None else None
        return decl.type if decl is not None else None

    def read_context(self, context):
        """Caller-supplied keys -> {key: typed value}. A key no loaded module
        declares is `undeclared-key`; a value that is not, or as text cannot be
        read as, the key's declared type is `key-type-mismatch`."""
        out = {}
        for key, value in (context or {}).items():
            want = self._key_type(key)
            if want is None:
                m, k = split_key(key)
                if m in self.models and k in self.models[m].lists:  # ruling 18 of 0.7
                    raise KeyTypeMismatch("context key %s is a list, not a scalar key" % key)
                raise UndeclaredKey("context key %s is declared by no loaded module" % key)
            ok = True
            if isinstance(value, str):
                try:
                    value = read_typed(value, want)
                except (ValueError, OverflowError):
                    ok = False
            elif isinstance(value, bool):
                ok = False
            elif want == "int":
                ok = isinstance(value, int)
            elif want == "float":
                ok = isinstance(value, (int, float)) and value == value and abs(value) != float("inf")
                value = float(value) if ok else value
            else:
                ok = False
            if not ok:
                raise KeyTypeMismatch("context key %s is declared %s; got %r" % (key, want, value))
            out[key] = value
        return out

    def derives(self):
        """Every `derive` line: the loaded modules in byte order of name, each
        module's lines in order."""
        if self._derives is None:
            self._derives = [
                d for name in sorted(self.models, key=lambda n: n.encode("utf-8")) for d in self.models[name].derives
            ]
        return self._derives

    def complete(self, entity, context=None):
        """Steps 2 and 3 of `convert` (spec 0.6): fill the keys the entity
        lacks from `context`, then apply the derivations. A line whose target
        is absent and whose arguments are all present sets the target; the
        pass repeats until it sets nothing, at most 8 times. Changes and
        returns `entity`."""
        fields = entity.fields
        for key, value in self.read_context(context).items():
            if key not in fields:
                fields[key] = value
        derives = self.derives()
        for _ in range(DERIVE_PASSES if derives else 0):
            changed = False
            for d in derives:
                if d.target in fields:
                    continue
                try:
                    if d.partial:  # `any`: set when only some arguments are present, not when none is
                        present = [fields[a] for a in d.args if a in fields]
                        if not present:
                            continue
                        value = d.fn(*present)
                    elif d.positional:  # `tokens` (0.18 ruling 7): set when one argument is present and not 0
                        value = d.fn(*[fields.get(a) for a in d.args])
                    else:
                        value = d.fn(*[fields[a] for a in d.args])
                except KeyError:
                    continue
                except (ValueError, OverflowError, TypeError):
                    continue  # a result that is not finite leaves the target absent
                if value is None:
                    continue
                fields[d.target] = value
                changed = True
            if not changed:
                break
        return entity

    # --- encode ------------------------------------------------------------

    def _select_encode_kind(self, pack, entity, ref):
        """spec 0.5, "Encode", steps 1 and 2. `ref` is the recorded kind that
        names this format (0.34: `Entity.kind` or `Entity.inner_kind`), or None."""
        if ref is not None:
            kind = pack.kind(ref[1])
            if kind is None:
                raise NoKind("the format has no kind %r" % (ref[1],), format=pack.name)
            return kind
        have = entity.fields
        lists = entity.lists
        for kind in pack.kinds:
            if requires_hold(kind, have, lists):
                return kind
        raise NoKind("the entity has the required keys of no kind of the format", format=pack.name)

    def encode(self, fmt, entity):
        """Entity to message. The kind is the one `Entity.kind` names when it
        names the format, else the one `Entity.inner_kind` names (0.34), else
        the first whose `requires` hold."""
        pack = self.pack(fmt)
        return self._encode_pack(pack, entity, _ref_for(pack, entity.kind, getattr(entity, "inner_kind", None)))

    def _encode_pack(self, pack, entity, ref):
        if pack.seq is not None:
            return wire_seq.encode(pack, entity, ref, self).encode("utf-8")
        wire = pack.wire
        codec = _CODECS[wire]
        kind = self._select_encode_kind(pack, entity, ref) if pack.kinds else None
        plan = pack.plan(kind)
        enc = self._encode_scope(pack, plan, entity.fields, entity.lists)
        if wire == "bits":
            return codec.write(pack, enc).encode("utf-8")
        if wire == "protobuf":
            return codec.write(pack, enc, kind.when_lines if kind is not None else ()).encode("utf-8")
        residue = entity.residue.get(pack.name, {})
        if wire == "json":
            return codec.encode(pack, enc, residue).encode("utf-8")
        if wire == "text" or wire == "tlv" or wire == "cbor":
            return codec.write(pack, enc, residue).encode("utf-8")
        if wire == "xml":
            return codec.write(pack, enc, residue.items(), plan.root).encode("utf-8")
        return codec.encode(pack, enc, residue).encode("utf-8")

    def _encode_scope(self, pack, plan, have, lists):
        """Encode one scope (the entity, or one item of a list). For each
        `field`: the scope's value, else the `default` of the scope; then the
        typemap and the value table; then the transform. For each `group`
        whose list the scope has: one encoded scope per item, in order. A
        common or kind `default` does not reach into items; a `default` inside
        a group applies to its items."""
        enc = _Enc(plan, have)
        defaults = plan.defaults
        c2n = pack.cot_to_native
        values = enc.values
        skip = _CODECS[pack.wire].overridden(plan) if pack.wire in ("tlv", "cbor") else ()
        part_groups = parts.groups_of(plan)
        if part_groups:  # 0.64: one token for the lines of a part group
            skip = set(skip)
            for g in part_groups:
                skip.update(g.indexes)
                token = parts.token_of(pack, g, have, defaults)
                if token is not None:
                    values[g.at] = token
        for i, f in plan.ifields:
            if i in skip and f.rng is None:
                continue  # its item holds a `when` or `const` value (ruling 9 of 0.13)
            key = f.key
            w = f.with_key
            if w is not None and w not in have and not lists.get(w):
                enc.suppressed.add(i)
                continue  # 0.18: as a line whose key is absent, with no default and no sentinel
            if key in have:
                value = have[key]
            else:
                # 0.17 ruling 5: the innermost block's default, then the enclosing
                # blocks', then the scope's
                gate = f.gate
                d = None
                while gate is not None:
                    d = gate.defaults.get(key)
                    if d is not None:
                        break
                    gate = gate.parent
                if d is not None:
                    value = d.value
                    enc.defaulted.add(i)
                elif key in defaults:
                    value = defaults[key]
                    enc.defaulted.add(i)
                else:
                    if f.absent_out is not None:  # the first sentinel, in place of every option (0.9)
                        values[i] = f.absent_out
                        enc.sentinels.add(i)
                        if f.implicit and _is_proto_default(values[i]):
                            enc.omitted.add(i)
                    elif f.null:
                        enc.nulls.add(i)  # 0.56: null where no line on the member writes a value
                    continue
            try:
                if f.rng is not None:
                    value = apply_range(f, value)  # 0.56: before `via` and the transform
                    if i in skip:
                        enc.defaulted.discard(i)
                        continue  # reached, so checked (ruling 9 of 0.56), but not encoded
                if c2n and key == "type" and value in c2n:
                    value = c2n[value]
                if f.via_enc is not None:
                    value = _via_encode(f, value)
                values[i] = f.transform.encode(value)
                if f.implicit and _is_proto_default(values[i]):
                    enc.omitted.add(i)
            except ValueError as e:
                err = TransformEncodeFailure(str(e), format=pack.name, locator=f.locator)
                if f.gate is None:
                    raise err
                enc.defaulted.discard(i)
                enc.errors[i] = err  # a block that is not held writes nothing (0.17)
        for i, g in plan.igroups:
            items = lists.get(g.list)
            if items is None:
                continue
            item_plan = g.plan
            enc.groups[i] = [self._encode_scope(pack, item_plan, it.fields, it.lists) for it in items]
        return enc

    # --- a conversion into a kind holds one of its keys (0.94) ------------

    def _keys_of_kind(self, pack, kind):
        """-> (scalar keys, list names) of `kind` (0.94, Rule): the keys 6a to
        6c of 0.11 list over the common lines and the kind's lines, every
        block and case of them; a list by its entry; an `inner` line's
        `model_keys` (none when its pack fails the checks of the line); the
        keys of the kind's own `requires` terms. Item keys do not count."""
        cache_key = (pack.name, kind.name)
        got = self._kind_keys.get(cache_key)
        if got is not None:
            return got
        scalars = set()
        lists = set()
        if pack.seq is not None:
            from .seqdef import T_FIELD, T_GROUP, T_INNER, T_WHEN, children

            def walk(nodes):
                for nd in nodes:
                    t = nd.t
                    if t == T_FIELD:
                        for f in nd.bindings:
                            scalars.add(f.key)
                    elif t == T_WHEN:
                        if nd.as_key is not None:
                            scalars.add(nd.as_key)
                    elif t == T_GROUP:
                        lists.add(nd.list)
                    elif t == T_INNER:
                        for name in self._inner_keys(pack, nd.name):
                            if name.endswith("[]"):
                                lists.add(name[:-2])
                            elif "[]." not in name:
                                scalars.add(name)
                    else:
                        for part in children(nd):
                            walk(part)

            walk(kind.block)
        else:
            for ln in pack.common + kind.lines:
                if ln.is_field:
                    scalars.add(ln.key)
                elif ln.is_group:
                    lists.add(ln.list)
        scalars.update(kind.requires_keys)
        scalars.update(vc.key for vc in kind.requires_eq)
        lists.update(kind.requires_lists)
        got = self._kind_keys[cache_key] = (frozenset(scalars), frozenset(lists))
        return got

    def _kept(self, to, kind, entity):
        """Ruling 4 of 0.94: a recorded kind that names `to`, or the format of
        an `inner` line of the chosen kind or of the common lines."""
        refs = [r for r in (entity.kind, entity.inner_kind) if r is not None]
        if not refs:
            return False
        names = {r[0] for r in refs}
        if to.name in names:
            return True
        if not to.inners or to.seq is None:
            return False
        from .seqdef import T_INNER, children

        def walk(nodes):
            for nd in nodes:
                if nd.t == T_INNER:
                    if nd.name in names:
                        return True
                else:
                    for part in children(nd):
                        if walk(part):
                            return True
            return False

        return walk(kind.block)

    def _target_kind(self, to, entity):
        """The message kind encode chooses (0.5, 0.34), or None for a pack with no message kinds."""
        ref = _ref_for(to, entity.kind, entity.inner_kind)
        if to.seq is not None:
            if not to.seq.kinds:
                return None
            return wire_seq.select_kind(to, to.seq, ref, entity.fields, entity.lists)
        if not to.kinds:
            return None
        return self._select_encode_kind(to, entity, ref)

    def _check_held(self, to, entity, kind=None, kept=True):
        """0.94, Rule: in a conversion into a pack with message kinds, the
        entity holds a key of the chosen kind, else `no-kind`. `kind`: the
        kind already chosen (runs); `kept`: whether a recorded kind exempts."""
        if kind is None:
            kind = self._target_kind(to, entity)  # the `no-kind` of choosing comes first
            if kind is None:
                return
        if kept and self._kept(to, kind, entity):
            return
        scalars, lists = self._keys_of_kind(to, kind)
        fields = entity.fields
        for key in scalars:
            if key in fields:
                return
        have = entity.lists
        for name in lists:
            if have.get(name):
                return
        raise NoKind("the entity holds no key of kind %r" % (kind.name,), format=to.name)

    def convert(self, from_fmt, to_fmt, data, context=None, max_items=None):
        """spec 0.6, "Order inside `convert`": decode, and clear the kind unless
        `from == to`; fill absent keys from `context`; apply the derivations;
        encode. When `from == to` and no context is given the middle steps are
        skipped, so a same-format round trip stays byte-exact."""
        self.pack(from_fmt)  # ruling 5 of 0.11: `from`, then `to`, before the input is read
        to = self.pack(to_fmt)
        entity = self.decode(from_fmt, data, max_items)
        self._clear_kinds(entity, from_fmt, to)
        if from_fmt != to_fmt or context is not None:
            self.complete(entity, context)
        if from_fmt != to_fmt:
            self._check_held(to, entity)
        return self.encode(to_fmt, entity)

    @staticmethod
    def _clear_kinds(entity, from_fmt, to):
        """A cross-format conversion chooses the target kind by `requires`,
        unless `to` has an `inner` line naming the format of the kind (0.34)."""
        if from_fmt != to.name:
            if entity.kind is not None and entity.kind[0] not in to.inners:
                entity.kind = None
            ik = entity.inner_kind
            if ik is not None and ik[0] != to.name and ik[0] not in to.inners:
                entity.inner_kind = None

    # --- runs of messages (0.92) -------------------------------------------

    def _joined(self, outer, message):
        """The entity of one message of a run, joined with the outer keys
        (ruling 9: the two map no common key)."""
        return Entity(fields={**outer.fields, **message.fields}, lists={**outer.lists, **message.lists},
                      kind=outer.kind, inner_kind=message.kind)

    def decode_run(self, fmt, data, max_items=None):
        """-> (the entity of the outer lines, [one entity or error per message]).
        An ordinary message gives its entity, or its error, as the one result;
        the outer entity is then that entity (None when there is none)."""
        pack = self.pack(fmt)
        limit = self.max_items if max_items is None else max_items
        if not pack.run_kinds:
            try:
                ent = self._decode_pack(pack, data, limit)
            except GTError as e:
                return getattr(e, "entity", None), [e]
            return ent, [ent]
        got = wire_seq.decode_run(pack, self._text(pack, data), limit, self)
        if got.ordinary:
            return got.entity, [got.entity if got.error is None else got.error]
        if got.error is not None:
            raise got.error
        if got.over is not None:  # ruling 5: the sum of the joined entities' items
            raise got.over
        return got.entity, [m if isinstance(m, GTError) else self._joined(got.entity, m) for m in got.messages]

    def convert_run(self, from_fmt, to_fmt, data, context=None, max_items=None):
        """-> [result]: the bytes of a message, or its error (0.92, Operations).
        An error of the call is raised."""
        pack = self.pack(from_fmt)
        to = self.pack(to_fmt)
        if pack.run_kinds:
            limit = self.max_items if max_items is None else max_items
            got = wire_seq.decode_run(pack, self._text(pack, data), limit, self)
            if not got.ordinary:
                if to.run_kinds:
                    return [self._carrier_to_carrier(pack, to, got, context)]
                return self._carrier_to_messages(pack, to, got, context)
            entity, error = got.entity, got.error
        else:
            entity = error = None
            try:
                entity = self.decode(from_fmt, data, max_items)
            except GTError as e:
                error = e
        # an ordinary message: `convert`, whose decode and encode errors are its one result, or the call's
        # to a carrier pack
        if error is not None:
            if to.run_kinds:
                raise error
            return [error]
        if context is not None:
            self.read_context(context)  # an error of the call, always
        try:
            self._clear_kinds(entity, from_fmt, to)
            if from_fmt != to_fmt or context is not None:
                self.complete(entity, context)
            if from_fmt != to_fmt:
                self._check_held(to, entity)
            return [self.encode(to_fmt, entity)]
        except GTError as e:
            if to.run_kinds:
                raise
            return [e]

    def _carrier_to_messages(self, pack, to, got, context):
        if got.error is not None:  # of the outer lines; message errors take no part
            raise got.error
        if got.over is not None:  # ruling 5: after every other decode error, before context
            raise got.over
        self.read_context(context)
        out = []
        for m in got.messages:
            if isinstance(m, GTError):
                out.append(m)
                continue
            entity = self._joined(got.entity, m)
            self._clear_kinds(entity, pack.name, to)
            self.complete(entity, context)
            try:
                if pack is not to:
                    self._check_held(to, entity)
                out.append(self.encode(to.name, entity))
            except GTError as e:
                out.append(e)
        return out

    def _carrier_to_carrier(self, pack, to, got, context):
        # every error is the call's, in phases (ruling 4): those that stop a decode, in reading order
        # (after a message that stopped, the outer lines alone are read), then other decode errors
        if got.ended:
            raise got.messages[-1]
        if got.error is not None and got.stops:
            raise got.error
        if got.error is not None:
            raise got.error
        for m in got.messages:
            if isinstance(m, GTError):
                raise m
        if got.over is not None:  # ruling 5: after every other decode error, before context
            raise got.over
        self.read_context(context)
        same = pack is to
        outer = Entity(fields=dict(got.entity.fields), lists=dict(got.entity.lists),
                       kind=got.entity.kind if same else None)
        if not same or context is not None:
            self.complete(outer, context)
        kind = wire_seq.select_kind(to, to.seq, _ref_for(to, outer.kind, None), outer.fields, outer.lists)
        ref = (to.name, kind.name) if kind is not None else None
        joined = [self._joined(got.entity, m) for m in got.messages]
        line = wire_seq.run_line(to, kind)
        if line is None and len(joined) != 1:
            raise MessageCount("a kind with no 'inner ... run' line takes exactly one message, not %d" % len(joined),
                               format=to.name)
        for entity in joined:
            self._clear_kinds(entity, pack.name, to)
            if context is not None or (not same if line is None else line.name != got.format):
                self.complete(entity, context)
        if not same and kind is not None:
            if line is None:  # 0.94 ruling 7: the one message's joined entity, as `convert`, ruling 4 included
                self._check_held(to, joined[0], kind)
            else:  # once, on the outer entity joined with the first message; the first message's kind is not kept
                first = joined[0] if joined else outer
                if joined:
                    first = Entity(fields={**outer.fields, **first.fields}, lists={**outer.lists, **first.lists})
                self._check_held(to, first, kind, kept=False)
        if line is None:
            return wire_seq.encode(to, joined[0], ref, self).encode("utf-8")
        return wire_seq.encode(to, outer, ref, self, joined).encode("utf-8")
