"""Model module parsing (grammar: spec/engine-spec.md, "Model module grammar")."""

import math
from dataclasses import dataclass, field as dc_field

from .errors import BadDirective, DuplicateKey, InvalidModel, MissingDistribution, MissingSource, UnknownDirective
from .packdef import CORE, DISTRIBUTIONS, split_key, tokenize
from .transforms import parse_factor, read_typed

KEY_TYPES = ("string", "float", "int")
_SINGLE = ("module", "version", "distribution")


@dataclass
class Key:
    name: str
    type: str
    unit: str = None  # None when the file says `-`
    meaning: str = None


@dataclass
class Derive:
    """`derive <model-key> <function> <argument-key>...` (version 0.6): the
    target follows from the arguments. `fn` takes the argument values and
    returns the target's value, or None when the target stays absent."""

    target: str
    function: str
    args: tuple
    fn: object = None
    lineno: int = 0


@dataclass
class Module:
    name: str
    version: str
    distribution: str
    sources: list = dc_field(default_factory=list)
    keys: dict = dc_field(default_factory=dict)  # name -> Key, in file order
    path: str = None
    derives: list = dc_field(default_factory=list)  # Derive, in file order
    lists: dict = dc_field(default_factory=dict)  # list name -> meaning (0.7); shares the key namespace


_DEG = math.pi / 180.0  # degrees to radians, with pi as the double nearest to it
_RAD = 180.0 / math.pi  # radians to degrees: the quotient computed first (0.6 ruling 1)
_INT64 = (-(1 << 63), (1 << 63) - 1)


def _finite(x):
    return x if math.isfinite(x) else None


def _bearing(east, north):
    if east == 0 and north == 0:
        return None
    d = math.atan2(east, north) * _RAD
    if not math.isfinite(d):
        return None
    if d < 0:
        d += 360.0
    if d >= 360.0:
        d -= 360.0
    return d


def _build_derive(function, target_type, arg_types):
    """-> the function of one `derive` line, checked against the types of its
    target and arguments. Raises ValueError when the function name, the
    argument count or a type does not fit."""
    name, colon, param = function.partition(":")
    n = len(arg_types)

    def floats(count):
        if n != count:
            raise ValueError("%s takes %d argument(s), got %d" % (name, count, n))
        if target_type != "float" or any(t != "float" for t in arg_types):
            raise ValueError("%s needs a float target and float arguments" % name)

    if name in ("copy", "hypot", "bearing", "east_of", "north_of", "neg") and colon:
        raise ValueError("%s takes no parameter" % name)
    if name == "copy":
        if n != 1:
            raise ValueError("copy takes 1 argument(s), got %d" % n)
        if arg_types[0] != target_type:
            raise ValueError("copy needs a target and an argument of one type")
        return lambda a: _finite(a) if isinstance(a, float) else a
    if name == "hypot":
        floats(2)
        return lambda a, b: _finite(math.sqrt(float(a) * float(a) + float(b) * float(b)))
    if name == "bearing":
        floats(2)
        return lambda east, north: _bearing(float(east), float(north))
    if name == "east_of":
        floats(2)
        return lambda speed, course: _finite(float(speed) * math.sin(float(course) * _DEG))
    if name == "north_of":
        floats(2)
        return lambda speed, course: _finite(float(speed) * math.cos(float(course) * _DEG))
    if name == "neg":
        floats(1)
        return lambda a: _finite(-float(a))
    if name == "scale" and colon:
        floats(1)
        factor, fraction = parse_factor(param)
        if fraction is not None:
            num, den = fraction
            return lambda a: _finite(float(a) * num / den)
        return lambda a: _finite(float(a) * factor)
    if name == "offset" and colon:
        if n != 1:
            raise ValueError("offset takes 1 argument(s), got %d" % n)
        if target_type == "int" and arg_types[0] == "int":
            k = read_typed(param, "int")  # 0.6 ruling 8: an integer `n`; an overflow leaves the target absent

            def add(a):
                r = int(a) + k
                return r if _INT64[0] <= r <= _INT64[1] else None

            return add
        if target_type == "float" and arg_types[0] == "float":
            x = read_typed(param, "float")
            return lambda a: _finite(float(a) + x)
        raise ValueError("offset needs a target and an argument that are both float or both int")
    if name == "join" and colon:
        if n < 1:  # 0.6 ruling 7
            raise ValueError("join takes 1 or more argument(s), got %d" % n)
        if target_type != "string" or any(t != "string" for t in arg_types):
            raise ValueError("join needs a string target and string arguments")
        return lambda *parts: param.join(parts)
    raise ValueError("unknown function %r" % function)


def _check_derives(module, lines, core, source):
    """Resolve every `derive` line against the keys of `core` and of the module
    itself. Any misfit is `bad-directive`."""
    def key_type(key, where):
        m, k = split_key(key)
        if m == module.name:
            decl = module.keys.get(k)
        elif m == CORE and core is not None:
            decl = core.keys.get(k)
        else:
            decl = None
            if m != CORE:
                raise BadDirective(
                    "derive key %s is of module %s; a derive line names keys of core or of module %s, at %s"
                    % (key, m, module.name, where)
                )
        if decl is None:
            raise BadDirective("derive names undeclared key %s at %s" % (key, where))
        return decl.type

    for lineno, args in lines:
        where = "%s:%d" % (source, lineno)
        target, function, arg_keys = args[0], args[1], tuple(args[2:])
        target_type = key_type(target, where)
        arg_types = [key_type(k, where) for k in arg_keys]
        try:
            fn = _build_derive(function, target_type, arg_types)
        except ValueError as e:
            raise BadDirective("derive %s %s at %s: %s" % (target, function, where, e))
        module.derives.append(Derive(target, function, arg_keys, fn, lineno))


def parse_model_text(text, *, source="model.def", core=None):
    """Parse one module. Line errors are raised as the file is read,
    `duplicate-key` among them; then the `derive` lines are checked (they need
    the whole file); then `missing-distribution` and `missing-source`. `core`
    is the loaded `core` module, whose keys a `derive` line of another module
    may name."""
    seen = {}
    sources = []
    keys = {}
    lists = {}
    derives = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        toks = tokenize(raw, source=source, lineno=lineno, error=InvalidModel)
        if not toks:
            continue
        kw, args = toks[0], toks[1:]
        where = "%s:%d" % (source, lineno)
        if kw in _SINGLE or kw == "source":
            if len(args) != 1:
                raise InvalidModel("directive %r takes 1 argument(s), got %d at %s" % (kw, len(args), where))
            if kw == "source":
                sources.append(args[0])
            elif kw in seen:
                raise InvalidModel("duplicate directive %r at %s" % (kw, where))
            else:
                seen[kw] = args[0]
        elif kw == "key":
            if len(args) not in (3, 4):
                raise InvalidModel("directive 'key' takes 3 or 4 argument(s), got %d at %s" % (len(args), where))
            kname, ktype, unit = args[0], args[1], args[2]
            if "." in kname:
                raise InvalidModel("key name %r contains '.' at %s" % (kname, where))
            if ktype not in KEY_TYPES:
                raise InvalidModel(
                    "key %r has unknown type %r (known: %s) at %s" % (kname, ktype, ", ".join(KEY_TYPES), where)
                )
            if kname in keys or kname in lists:
                raise DuplicateKey("key %r appears twice in the module, at %s" % (kname, where))
            keys[kname] = Key(kname, ktype, None if unit == "-" else unit, args[3] if len(args) == 4 else None)
        elif kw == "list":
            if len(args) not in (1, 2):
                raise InvalidModel("directive 'list' takes 1 or 2 argument(s), got %d at %s" % (len(args), where))
            lname = args[0]
            if "." in lname:
                raise InvalidModel("list name %r contains '.' at %s" % (lname, where))
            if lname in keys or lname in lists:  # a list shares the key namespace of its module
                raise DuplicateKey("name %r appears twice in the module, at %s" % (lname, where))
            lists[lname] = args[1] if len(args) == 2 else None
        elif kw == "derive":
            if len(args) < 2:
                raise InvalidModel("directive 'derive' takes 2 or more argument(s), got %d at %s" % (len(args), where))
            derives.append((lineno, args))
        else:
            raise UnknownDirective("unknown directive %r at %s" % (kw, where))

    name = seen.get("module")
    module = Module(name=name, version=seen.get("version"), distribution=seen.get("distribution"), sources=sources,
                    keys=keys, lists=lists)
    _check_derives(module, derives, core, source)
    if module.distribution is None:
        raise MissingDistribution("module %r has no 'distribution' line in %s" % (name, source))
    if not sources:
        raise MissingSource("module %r has no 'source' line in %s" % (name, source))
    if not name:
        raise InvalidModel("missing 'module' directive in %s" % source)
    if "." in name:
        raise InvalidModel("module name %r contains '.'" % name)
    if not module.version:
        raise InvalidModel("missing 'version' directive in %s (module %s)" % (source, name))
    if module.distribution not in DISTRIBUTIONS:
        raise InvalidModel(
            "unknown distribution %r (known: %s) in module %s" % (module.distribution, ", ".join(DISTRIBUTIONS), name)
        )
    return module


def load_model_file(path, core=None):
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    module = parse_model_text(text, source=path, core=core)
    module.path = path
    return module
