"""decode / encode / convert over loaded packs (spec/engine-spec.md)."""

import os
from dataclasses import dataclass, field as dc_field

from . import wire_bits, wire_geojson, wire_json, wire_protobuf, wire_xml
from .errors import (
    DistributionRefused, DistributionViolation, DuplicateModule, InvalidPack, KeyTypeMismatch, MalformedWire,
    ModuleNotUsed, NoKind, TransformDecodeFailure, TransformEncodeFailure, UndeclaredKey, UnknownFormat,
    UnknownModule,
)
from .modeldef import load_model_file, parse_model_text
from .packdef import CORE, DISTRIBUTIONS, load_pack, parse_pack_text, split_key
from .transforms import canonical_text, read_typed, table_side_type

DERIVE_PASSES = 8  # spec 0.6: the pass repeats until it sets nothing, at most 8 times

_CODECS = {
    "xml": wire_xml, "geojson": wire_geojson, "json": wire_json, "bits": wire_bits, "protobuf": wire_protobuf,
}
_Num = wire_geojson.Num


def _canon(text, type_name):
    """Canonical text of a table entry read as `type_name`, or None when it
    cannot be read as that type (it then matches no value)."""
    try:
        return canonical_text(read_typed(text, type_name), type_name)
    except (ValueError, OverflowError):
        return None


def _build_via(f, table):
    """The two lookups of a `via` field: canonical native text -> model value,
    and canonical model text -> native text. The first entry for a value wins."""
    nt, kt = f.transform.yields, f.key_type
    f.via_dec, f.via_enc = {}, {}
    for native, model in table:
        n = _canon(native, nt)
        if n is not None and n not in f.via_dec:
            try:
                f.via_dec[n] = read_typed(model, kt)
            except (ValueError, OverflowError):
                pass
        m = _canon(model, kt)
        if m is not None and m not in f.via_enc:
            f.via_enc[m] = native


def _via_decode(f, value):
    """After the transform on decode: what the transform yields -> what the key holds."""
    nt = f.transform.yields
    text = canonical_text(value, nt)
    if text in f.via_dec:
        return f.via_dec[text]
    if nt == f.key_type:
        return value  # no entry and both sides one type: passes through
    raise ValueError("%s has no entry in table %s" % (text, f.via))


def _via_encode(f, value):
    """Before the transform on encode: what the key holds -> what the transform takes."""
    nt, kt = f.transform.yields, f.key_type
    try:
        text = canonical_text(value, kt)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("%r is not a %s value" % (value, kt))
    native = f.via_enc.get(text)
    if native is None:
        if nt == kt:
            return value
        raise ValueError("%s has no entry in table %s" % (text, f.via))
    return read_typed(native, nt)


@dataclass
class Item:
    """One item of a list (0.7): model keys and lists exactly as an entity
    holds them, without residue and without a kind."""

    fields: dict = dc_field(default_factory=dict)
    lists: dict = dc_field(default_factory=dict)

    def __getitem__(self, key):
        return self.fields[key]

    def get(self, key, default=None):
        return self.fields.get(key, default)


@dataclass
class Entity:
    """Shared model: named fields plus residue. `residue` maps a format name to an
    ordered {locator: original string value}; it never crosses formats. `kind`
    is the pair `(format, kind name)` a decode selected, or None. `lists` maps
    a list name to its items, in order (0.7); a list that is present and empty
    is distinct from an absent one."""

    fields: dict = dc_field(default_factory=dict)
    residue: dict = dc_field(default_factory=dict)
    kind: tuple = None
    lists: dict = dc_field(default_factory=dict)

    def __getitem__(self, key):
        return self.fields[key]

    def get(self, key, default=None):
        return self.fields.get(key, default)


class _Enc:
    """One encoded scope: `values` maps a field line's index in the plan's
    lines to its encoded wire value, `groups` a group line's index to the
    encoded scope of each item of its list (absent when the entity has no such
    list)."""

    __slots__ = ("plan", "values", "groups")

    def __init__(self, plan):
        self.plan = plan
        self.values = {}
        self.groups = {}


class Engine:
    def __init__(self, packs=(), models=(), max_distribution="controlled"):
        self.packs = {}
        self.models = {}
        self._derives = None
        self.set_max_distribution(max_distribution)
        for m in models:
            self.add_model(m)
        for p in packs:
            self.add(p)

    def set_max_distribution(self, limit):
        """The distribution limit: `controlled` (default) loads everything;
        `public` refuses every controlled module and pack."""
        if limit not in DISTRIBUTIONS:
            raise ValueError("max distribution must be one of %s, got %r" % (", ".join(DISTRIBUTIONS), limit))
        self.max_distribution = limit

    def _within_limit(self, distribution):
        return DISTRIBUTIONS.index(distribution) <= DISTRIBUTIONS.index(self.max_distribution)

    def load_model(self, text, *, source="model.def"):
        """Parse one model module text and load it."""
        module = parse_model_text(text, source=source, core=self.models.get(CORE))
        self.add_model(module)
        return module

    def add_model(self, module):
        if not self._within_limit(module.distribution):
            raise DistributionRefused(
                "module %s is %s; this engine's limit is %s"
                % (module.name, module.distribution, self.max_distribution)
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
                    else "mapped by a group" if getattr(ref, "is_group", False) else "given a default"
                )
                raise UndeclaredKey(
                    "module %s declares no key %r (%s as %s)" % (m, k, role, key),
                    format=fmt, locator=getattr(ref, "locator", None),
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
            if f.via is not None:
                _build_via(f, pack.tables[f.via])
        for key, d, (m, k) in keyed:
            if d is None or getattr(d, "is_field", False) or getattr(d, "is_group", False):
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
        for kind in pack.kinds:  # `requires <list>` holds when the list has at least one item
            if kind.requires:
                names = [(key, split_key(key)) for key in kind.requires]
                kind.requires_lists = tuple(key for key, (m, k) in names if k in self.models[m].lists)
                kind.requires_keys = tuple(key for key, (m, k) in names if k not in self.models[m].lists)
        pack._plans.clear()
        if pack.name in self.packs:
            raise InvalidPack(
                "format defined twice (%s, %s)" % (self.packs[pack.name].path, pack.path), format=pack.name
            )
        self.packs[pack.name] = pack

    @classmethod
    def from_dir(cls, packs_dir, models_dir=None, max_distribution="controlled"):
        """Load every `<models_dir>/*.def` in byte order of file name, then every
        `<packs_dir>/<format>/pack.def`. `models_dir` defaults to the `model`
        directory beside `packs_dir`."""
        if models_dir is None:
            models_dir = os.path.join(packs_dir, os.pardir, "model")
        eng = cls(max_distribution=max_distribution)
        if os.path.isdir(models_dir):
            # `core.def` first, whatever its name sorts as (0.6 ruling 9).
            names = sorted(os.listdir(models_dir), key=lambda n: (n != CORE + ".def", os.fsencode(n)))
            for name in names:
                path = os.path.join(models_dir, name)
                if name.endswith(".def") and os.path.isfile(path):
                    eng.add_model(load_model_file(path, core=eng.models.get(CORE)))
        for name in sorted(os.listdir(packs_dir)):
            d = os.path.join(packs_dir, name)
            if os.path.isfile(os.path.join(d, "pack.def")):
                eng.add(load_pack(d))
        return eng

    def formats(self):
        return sorted(self.packs)

    def pack(self, fmt):
        p = self.packs.get(fmt)
        if p is None:
            raise UnknownFormat("no pack loaded for %r (loaded: %s)" % (fmt, ", ".join(self.formats())), format=fmt)
        return p

    def model_keys(self, fmt):
        """The union of mapped keys over common and all kinds, in first
        appearance order; a list as `<list>[]`, an item key as `<list>[].<key>`."""
        return self.pack(fmt).model_keys()

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
        """Run one field's transform over its raw wire value. Raises ValueError."""
        if wire in ("bits", "protobuf"):
            return transform.decode(raw)
        if wire == "xml":
            return transform.decode(raw)
        if wire == "geojson":
            if not isinstance(raw, str):
                raise ValueError("not a JSON scalar string or number")
            return transform.decode(str(raw))
        # json: the JSON type must be the one the transform takes.
        if transform.kind == "bool":
            return transform.decode(raw)
        if transform.kind == "number":
            if not isinstance(raw, _Num):
                raise ValueError("%s needs a JSON number" % transform.name)
            return transform.decode(str(raw))
        if not isinstance(raw, str) or isinstance(raw, _Num):
            raise ValueError("%s needs a JSON string" % transform.name)
        return transform.decode(raw)

    def decode(self, fmt, data):
        pack = self.pack(fmt)
        if isinstance(data, (bytes, bytearray)):
            try:
                data = bytes(data).decode("utf-8")
            except UnicodeDecodeError as e:
                raise MalformedWire("input is not UTF-8: %s" % e, format=fmt)
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

        failures = []  # (key, locator, reason) of every field that could not be decoded
        keep_in_residue = self._decode_scope(pack, wire, codec, plan, msg, ent.fields, ent.lists, failures, "")

        mapped = plan.mapped - keep_in_residue if keep_in_residue else plan.mapped
        res = None
        if wire == "xml" or wire == "json":
            res = codec.residue(pack, msg, mapped)
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
                    val = wire_geojson.RawJSON(wire_geojson.dump_as_written(val))
                res[loc] = val
        if res:
            ent.residue[pack.name] = res
        if failures:
            raise TransformDecodeFailure(
                "%d field(s) could not be decoded" % len(failures), format=fmt, entity=ent, absent=failures
            )
        return ent

    def _decode_scope(self, pack, wire, codec, plan, ctx, fields, lists, failures, prefix):
        """Decode one scope (the message, or one item of a group) from its wire
        context into `fields` and `lists`; the fields that could not be decoded
        are added to `failures`. -> the locators of `type` fields whose native
        code has no `typemap` entry, or None.

        A key mapped by several lines takes its value from the earliest line
        whose locator is present on the wire and whose transform succeeds
        (0.6, "One key at several locators"). That line's value table, if
        any, is then applied; a value with no entry fails the decode. A line
        whose transform fails is an error only when no line of its key
        succeeds (0.6 ruling 5, ruling 10 of 0.7)."""
        settled = set()  # keys whose line has been chosen
        failed = None    # [(key, locator, reason, final)]
        keep_in_residue = None
        n2c = pack.native_to_cot
        get = codec.get
        for f in plan.fields:
            key = f.key
            if key in settled:
                continue
            raw = get(pack, ctx, f)
            if raw is None:
                continue
            try:
                value = self._decode_value(wire, f.transform, raw)
            except ValueError as e:
                if failed is None:
                    failed = []
                failed.append((key, f.locator, str(e), False))
                continue
            settled.add(key)
            if f.via_dec is not None:
                try:
                    value = _via_decode(f, value)
                except ValueError as e:
                    if failed is None:
                        failed = []
                    failed.append((key, f.locator, str(e), True))
                    continue
            if n2c and key == "type":
                if value in n2c:
                    value = n2c[value]
                else:
                    if keep_in_residue is None:
                        keep_in_residue = set()
                    keep_in_residue.add(f.locator)
            fields[key] = value
        if failed:
            failures.extend(
                (prefix + k, loc, why) for k, loc, why, final in failed if final or k not in settled
            )
        # For each group of the scope, in line order: one item per occurrence.
        for g in plan.groups:
            contexts = codec.items(pack, ctx, g)
            if contexts is None:
                continue  # the list is absent
            item_plan = g.plan
            out = []
            for n, item_ctx in enumerate(contexts):
                item = Item()
                self._decode_scope(
                    pack, wire, codec, item_plan, item_ctx, item.fields, item.lists, failures,
                    "%s%s[%d]." % (prefix, g.list, n),
                )
                out.append(item)
            lists[g.list] = out
        return keep_in_residue

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

    def _select_encode_kind(self, pack, entity):
        """spec 0.5, "Encode", steps 1 and 2."""
        if entity.kind is not None and entity.kind[0] == pack.name:
            kind = pack.kind(entity.kind[1])
            if kind is None:
                raise NoKind("the format has no kind %r" % (entity.kind[1],), format=pack.name)
            return kind
        have = entity.fields
        lists = entity.lists
        for kind in pack.kinds:
            for key in kind.requires_keys:
                if key not in have:
                    break
            else:
                for name in kind.requires_lists:
                    if not lists.get(name):  # present, with at least one item
                        break
                else:
                    return kind
        raise NoKind("the entity has the required keys of no kind of the format", format=pack.name)

    def encode(self, fmt, entity):
        pack = self.pack(fmt)
        wire = pack.wire
        codec = _CODECS[wire]
        kind = self._select_encode_kind(pack, entity) if pack.kinds else None
        plan = pack.plan(kind)
        enc = self._encode_scope(pack, plan, entity.fields, entity.lists)
        if wire == "bits":
            return codec.write(pack, enc).encode("utf-8")
        if wire == "protobuf":
            return codec.write(pack, enc, kind.when_lines if kind is not None else ()).encode("utf-8")
        residue = entity.residue.get(pack.name, {})
        if wire == "json":
            return codec.encode(pack, enc, residue).encode("utf-8")
        if wire == "xml":
            return codec.write(pack, enc, residue.items(), plan.root).encode("utf-8")
        return codec.encode(pack, enc, residue, wire_json.item_text).encode("utf-8")

    def _encode_scope(self, pack, plan, have, lists):
        """Encode one scope (the entity, or one item of a list). For each
        `field`: the scope's value, else the `default` of the scope; then the
        typemap and the value table; then the transform. For each `group`
        whose list the scope has: one encoded scope per item, in order. A
        common or kind `default` does not reach into items; a `default` inside
        a group applies to its items."""
        enc = _Enc(plan)
        defaults = plan.defaults
        c2n = pack.cot_to_native
        values = enc.values
        for i, f in plan.ifields:
            key = f.key
            if key in have:
                value = have[key]
            elif key in defaults:
                value = defaults[key]
            else:
                continue
            try:
                if c2n and key == "type" and value in c2n:
                    value = c2n[value]
                if f.via_enc is not None:
                    value = _via_encode(f, value)
                values[i] = f.transform.encode(value)
            except ValueError as e:
                raise TransformEncodeFailure(str(e), format=pack.name, locator=f.locator)
        for i, g in plan.igroups:
            items = lists.get(g.list)
            if items is None:
                continue
            item_plan = g.plan
            enc.groups[i] = [self._encode_scope(pack, item_plan, it.fields, it.lists) for it in items]
        return enc

    def convert(self, from_fmt, to_fmt, data, context=None):
        """spec 0.6, "Order inside `convert`": decode, and clear the kind unless
        `from == to`; fill absent keys from `context`; apply the derivations;
        encode. When `from == to` and no context is given the middle steps are
        skipped, so a same-format round trip stays byte-exact."""
        self.pack(to_fmt)  # fail before decoding when the target is unknown
        entity = self.decode(from_fmt, data)
        if from_fmt != to_fmt:
            entity.kind = None  # a cross-format conversion chooses the target kind by `requires`
        if from_fmt != to_fmt or context is not None:
            self.complete(entity, context)
        return self.encode(to_fmt, entity)
