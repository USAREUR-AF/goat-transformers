package goatxf

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Derived keys (spec/engine-spec.md, "Version 0.6: mapping rules", Derived
// keys): a `derive` line of a model module states that a key follows from
// others. Convert applies the lines between decode and encode.

// Derive is one `derive` line of a model module.
type Derive struct {
	Target   string
	Function string // as written, with its parameter: `scale:1/3`
	Args     []string
	Line     int

	name   string  // the function name, without its parameter
	param  string  // the text after the first `:`, for scale, offset and join
	frac   bool    // scale: the factor is a fraction num/den
	factor float64 // scale: the decimal factor
	num    float64 // scale: fraction numerator
	den    float64 // scale: fraction denominator
	addF   float64 // offset on floats
	addI   int64   // offset on ints
	isInt  bool    // offset: integer addition
}

// deriveArity is the number of argument keys each function takes; -1 means
// one or more (0.6 ruling 7: `join` takes one or more arguments).
var deriveArity = map[string]int{
	"copy": 1, "hypot": 2, "bearing": 2, "east_of": 2, "north_of": 2,
	"neg": 1, "scale": 1, "offset": 1, "join": -1,
	// spec 0.8, "Model additions".
	"day_seconds": 1, "any": -1, "not": 1, "parse_int": 1, "text_of": 1,
}

// parseDerive reads the function of a `derive` line and checks what the line
// alone decides: the function name, its parameter and the argument count.
func parseDerive(d *Derive) error {
	name, param, hasParam := strings.Cut(d.Function, ":")
	arity, known := deriveArity[name]
	if !known {
		return fmt.Errorf("unknown derive function %q (copy, hypot, bearing, east_of, north_of, neg, scale:<factor>, offset:<n>, join:<sep>, day_seconds, any, not, parse_int, text_of)", d.Function)
	}
	d.name, d.param = name, param
	switch name {
	case "scale":
		if !hasParam {
			return fmt.Errorf("scale needs a factor: scale:<factor>")
		}
		if i := strings.IndexByte(param, '/'); i >= 0 {
			num, e1 := strconv.ParseInt(param[:i], 10, 64)
			den, e2 := strconv.ParseInt(param[i+1:], 10, 64)
			if e1 != nil || e2 != nil || den == 0 {
				return fmt.Errorf("scale fraction must be <num>/<den> of two decimal integers, got %q", param)
			}
			d.frac, d.num, d.den = true, float64(num), float64(den)
		} else {
			f, err := parseFloat(param)
			if err != nil {
				return fmt.Errorf("scale factor must be a decimal number or a fraction, got %q", param)
			}
			d.factor = f
		}
	case "offset":
		if !hasParam {
			return fmt.Errorf("offset needs a number: offset:<n>")
		}
		f, err := parseFloat(param)
		if err != nil {
			return fmt.Errorf("offset must be a decimal number, got %q", param)
		}
		d.addF = f
	case "join":
		if !hasParam {
			return fmt.Errorf("join needs a separator: join:<sep>")
		}
	default:
		if hasParam {
			return fmt.Errorf("derive function %s takes no parameter, got %q", name, d.Function)
		}
	}
	if arity < 0 && len(d.Args) < -arity {
		return fmt.Errorf("%s takes at least %d argument key(s), got %d", name, -arity, len(d.Args))
	}
	if arity >= 0 && len(d.Args) != arity {
		return fmt.Errorf("%s takes %d argument key(s), got %d", name, arity, len(d.Args))
	}
	return nil
}

// checkDerives checks the keys and types of a module's `derive` lines against
// the module itself and the loaded core module. Every failure is
// bad-directive.
func (e *Engine) checkDerives(m *Module) error {
	for i := range m.Derives {
		d := &m.Derives[i]
		bad := func(format string, a ...any) error {
			return &Error{Kind: ErrBadDirective, Module: m.Name, Source: m.Source, Line: d.Line, Detail: "derive " + d.Target + ": " + fmt.Sprintf(format, a...)}
		}
		// The target is a key of core or of the module itself; an argument may
		// also be a key of a module the module uses (spec 0.8).
		typeOf := func(key string, isTarget bool) (Kind, error) {
			mod, name := splitModelKey(key)
			var owner *Module
			switch {
			case mod == m.Name:
				owner = m
			case mod == CoreModule:
				owner = e.modules[CoreModule]
			case !isTarget && usesModule(m, mod):
				owner = e.modules[mod]
				if owner == nil {
					return 0, &Error{Kind: ErrUnknownModule, Module: mod, Source: m.Source, Line: d.Line, Detail: fmt.Sprintf("module %s uses module %s, which is not loaded", m.Name, mod)}
				}
			case isTarget:
				return 0, bad("target %s is not a key of core or of module %s", key, m.Name)
			default:
				return 0, bad("key %s is not a key of core, of module %s or of a module it uses", key, m.Name)
			}
			if owner == nil {
				return 0, bad("key %s: module %s is not loaded", key, mod)
			}
			k, ok := owner.Key(name)
			if !ok {
				return 0, bad("module %s declares no key %q", mod, name)
			}
			return k.Type, nil
		}
		target, err := typeOf(d.Target, true)
		if err != nil {
			return err
		}
		args := make([]Kind, len(d.Args))
		for j, a := range d.Args {
			if args[j], err = typeOf(a, false); err != nil {
				return err
			}
		}
		all := func(want Kind) bool {
			if target != want {
				return false
			}
			for _, a := range args {
				if a != want {
					return false
				}
			}
			return true
		}
		switch d.name {
		case "copy":
			if target != args[0] {
				return bad("copy needs a target and an argument of one type, got %s and %s", kindName(target), kindName(args[0]))
			}
		case "offset":
			switch {
			case all(KindFloat):
			case all(KindInt):
				n, err := strconv.ParseInt(d.param, 10, 64)
				if err != nil {
					return bad("offset on int keys needs an integer, got %q", d.param)
				}
				d.isInt, d.addI = true, n
			default:
				return bad("offset needs a target and an argument that are both float or both int")
			}
		case "join":
			if !all(KindString) {
				return bad("join needs a string target and string arguments")
			}
		case "day_seconds":
			if target != KindFloat || args[0] != KindInt {
				return bad("day_seconds needs a float target and an int argument")
			}
		case "any", "not":
			if !all(KindInt) {
				return bad("%s needs an int target and int arguments", d.name)
			}
		case "parse_int":
			if target != KindInt || args[0] != KindString {
				return bad("parse_int needs an int target and a string argument")
			}
		case "text_of":
			if target != KindString || args[0] != KindInt {
				return bad("text_of needs a string target and an int argument")
			}
		default:
			if !all(KindFloat) {
				return bad("%s needs a float target and float arguments", d.name)
			}
		}
	}
	return nil
}

// usesModule reports whether a module names another in a `uses` line.
func usesModule(m *Module, name string) bool {
	for _, u := range m.Uses {
		if u == name {
			return true
		}
	}
	return false
}

// isDecimalInt reports whether s is an optional `-` and decimal digits.
func isDecimalInt(s string) bool {
	if strings.HasPrefix(s, "-") {
		s = s[1:]
	}
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// degToRad is π/180 with π as the double nearest to it, and radToDeg is 180/π
// (0.6 ruling 1: radians become degrees by multiplying by 180/π, the quotient
// computed first as a double). The divisions are done in doubles: a constant
// expression would be evaluated exactly.
var (
	piDouble  float64 = math.Pi
	oneEighty float64 = 180
	degToRad          = piDouble / oneEighty
	radToDeg          = oneEighty / piDouble
)

// apply computes the target value from the argument values. ok is false when
// the line leaves the target absent: a result that is not finite, or a
// bearing of a zero vector.
func (d *Derive) apply(args []Value) (Value, bool) {
	fl := func(i int) float64 {
		f, err := valueToFloat(args[i])
		if err != nil {
			return math.NaN()
		}
		return f
	}
	var r float64
	switch d.name {
	case "copy":
		if args[0].Kind == KindFloat && (math.IsNaN(args[0].F) || math.IsInf(args[0].F, 0)) {
			return Value{}, false
		}
		return args[0], true
	case "day_seconds":
		// Seconds since UTC midnight of an instant in epoch milliseconds.
		const dayMs = 86400000
		ms := args[0].I % dayMs
		if ms < 0 {
			ms += dayMs
		}
		return Value{Kind: KindFloat, F: float64(ms) / 1000}, true
	case "any":
		// The arguments handed in are the present ones.
		for _, a := range args {
			if a.I != 0 {
				return Value{Kind: KindInt, I: 1}, true
			}
		}
		return Value{Kind: KindInt, I: 0}, true
	case "not":
		if args[0].I == 0 {
			return Value{Kind: KindInt, I: 1}, true
		}
		return Value{Kind: KindInt, I: 0}, true
	case "parse_int":
		if !isDecimalInt(args[0].S) {
			return Value{}, false
		}
		i, err := strconv.ParseInt(args[0].S, 10, 64)
		if err != nil {
			return Value{}, false
		}
		return Value{Kind: KindInt, I: i}, true
	case "text_of":
		return Value{Kind: KindString, S: strconv.FormatInt(args[0].I, 10)}, true
	case "join":
		parts := make([]string, len(args))
		for i, a := range args {
			parts[i] = a.String()
		}
		return Value{Kind: KindString, S: strings.Join(parts, d.param)}, true
	case "offset":
		if d.isInt {
			i, err := valueToInt(args[0])
			if err != nil {
				return Value{}, false
			}
			// An overflow leaves the target absent (0.6 ruling 8).
			sum := i + d.addI
			if (d.addI > 0 && sum < i) || (d.addI < 0 && sum > i) {
				return Value{}, false
			}
			return Value{Kind: KindInt, I: sum}, true
		}
		r = fl(0) + d.addF
	case "hypot":
		a, b := fl(0), fl(1)
		r = math.Sqrt(a*a + b*b)
	case "bearing":
		east, north := fl(0), fl(1)
		if east == 0 && north == 0 {
			return Value{}, false
		}
		r = math.Atan2(east, north) * radToDeg
		if r < 0 {
			r += 360
		}
		if r >= 360 {
			r -= 360
		}
	case "east_of":
		r = fl(0) * math.Sin(fl(1)*degToRad)
	case "north_of":
		r = fl(0) * math.Cos(fl(1)*degToRad)
	case "neg":
		r = -fl(0)
	case "scale":
		if d.frac {
			r = fl(0) * d.num / d.den
		} else {
			r = fl(0) * d.factor
		}
	}
	if math.IsNaN(r) || math.IsInf(r, 0) {
		return Value{}, false
	}
	return Value{Kind: KindFloat, F: r}, true
}

// deriveLines returns every `derive` line of the loaded modules: the modules
// in byte order of name, each module's lines in file order.
func (e *Engine) deriveLines() []*Derive {
	if e.derives != nil {
		return e.derives
	}
	names := make([]string, 0, len(e.modules))
	for name := range e.modules {
		names = append(names, name)
	}
	sort.Strings(names)
	out := []*Derive{}
	for _, name := range names {
		m := e.modules[name]
		for i := range m.Derives {
			out = append(out, &m.Derives[i])
		}
	}
	e.derives = out
	return out
}

// Complete applies the derivations to an entity: a line whose target key is
// absent and whose argument keys are all present sets the target. The pass
// repeats until a pass sets nothing, at most 8 times.
func (e *Engine) Complete(ent *Entity) {
	lines := e.deriveLines()
	if len(lines) == 0 {
		return
	}
	var args []Value
	for pass := 0; pass < 8; pass++ {
		set := false
	next:
		for _, d := range lines {
			if _, has := ent.Fields[d.Target]; has {
				continue
			}
			args = args[:0]
			for _, a := range d.Args {
				v, ok := ent.Fields[a]
				if !ok {
					// `any` is the one function that needs only some of its
					// arguments (spec 0.8).
					if d.name == "any" {
						continue
					}
					continue next
				}
				args = append(args, v)
			}
			if len(args) == 0 {
				continue
			}
			if v, ok := d.apply(args); ok {
				ent.Fields[d.Target] = v
				set = true
			}
		}
		if !set {
			return
		}
	}
}

// readAs reads text as a model value of the given type.
func readAs(text string, kind Kind) (Value, error) {
	switch kind {
	case KindInt:
		i, err := strconv.ParseInt(strings.TrimSpace(text), 10, 64)
		if err != nil {
			return Value{}, fmt.Errorf("%q is not an integer", text)
		}
		return Value{Kind: KindInt, I: i}, nil
	case KindFloat:
		f, err := parseFloat(text)
		if err != nil {
			return Value{}, fmt.Errorf("%q is not a number", text)
		}
		return Value{Kind: KindFloat, F: f}, nil
	}
	return Value{Kind: KindString, S: text}, nil
}

// keyType returns the declared type of a model key as a pack writes it (bare
// for core, <module>.<key> otherwise).
func (e *Engine) keyType(key string) (Kind, error) {
	mod, name := splitModelKey(key)
	m, ok := e.modules[mod]
	if !ok {
		return 0, &Error{Kind: ErrUndeclaredKey, Module: mod, Detail: fmt.Sprintf("key %s: module %s is not loaded", key, mod)}
	}
	k, ok := m.Key(name)
	if !ok && m.IsList(name) {
		return 0, &Error{Kind: ErrKeyTypeMismatch, Module: mod, Detail: fmt.Sprintf("%s is a list of module %s, not a key", key, mod)}
	}
	if !ok {
		return 0, &Error{Kind: ErrUndeclaredKey, Module: mod, Detail: fmt.Sprintf("module %s declares no key %q", mod, name)}
	}
	return k.Type, nil
}

// Fill sets each context key the entity lacks. A context is the model keys
// and values a caller supplies, values in string form. Every context key must
// be declared by a loaded module (undeclared-key) and its value readable as
// the key's declared type (key-type-mismatch), whether or not the entity
// already has the key.
func (e *Engine) Fill(ent *Entity, context map[string]string) error {
	keys := make([]string, 0, len(context))
	for k := range context {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	vals := make([]Value, len(keys))
	for i, k := range keys {
		kind, err := e.keyType(k)
		if err != nil {
			return err
		}
		v, err := readAs(context[k], kind)
		if err != nil {
			mod, _ := splitModelKey(k)
			return &Error{Kind: ErrKeyTypeMismatch, Module: mod, Detail: fmt.Sprintf("context key %s is %s: %v", k, kindName(kind), err)}
		}
		vals[i] = v
	}
	for i, k := range keys {
		if _, has := ent.Fields[k]; !has {
			ent.Fields[k] = vals[i]
		}
	}
	return nil
}
