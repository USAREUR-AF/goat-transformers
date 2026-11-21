package goatxf

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
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

	name   string   // the function name, without its parameter
	param  string   // the text after the first `:`, for scale, offset and join
	frac   bool     // scale: the factor is a fraction num/den
	factor float64  // scale: the decimal factor
	num    float64  // scale: fraction numerator
	den    float64  // scale: fraction denominator
	addF   float64  // offset on floats
	addI   int64    // offset on ints
	isInt  bool     // offset: integer addition
	sep    string   // tokens, has_token: the separator character (0.18)
	toks   []string // tokens, has_token: the tokens, in order (0.18)
	text   string   // text_if: the text (0.18)
}

// deriveArity is the number of argument keys each function takes; -1 means
// one or more (0.6 ruling 7: `join` takes one or more arguments).
var deriveArity = map[string]int{
	"copy": 1, "hypot": 2, "bearing": 2, "east_of": 2, "north_of": 2,
	"neg": 1, "scale": 1, "offset": 1, "join": -1,
	// spec 0.8, "Model additions".
	"day_seconds": 1, "any": -1, "not": 1, "parse_int": 1, "text_of": 1,
	// spec 0.12.
	"present": 1,
	// spec 0.16, "Functions".
	"sec_of": 1, "nsec_of": 1, "ms_of": 2, "deg": 1, "rad": 1, "add": 2, "sub": 2,
	"deg_lat_of": 2, "deg_lon_of": 2, "m_lat_of": 2, "m_lon_of": 2,
	"ecef_x": 3, "ecef_y": 3, "ecef_z": 3,
	"lat_of_ecef": 3, "lon_of_ecef": 3, "hae_of_ecef": 3,
	// spec 0.18, "Derive functions": tokens takes one argument per token.
	"tokens": -1, "has_token": 1, "text_if": 1,
}

// isSpec18Space reports whether r is whitespace as Version 0.18 states it:
// space, tab, line feed and carriage return.
func isSpec18Space(r rune) bool { return r == ' ' || r == '\t' || r == '\n' || r == '\r' }

// parseTokenSep reads the <sep> of tokens and has_token (0.18): one code point
// other than `:`, `,` or whitespace, or one of the names space, comma and
// colon, lowercase and exact (ruling 9).
func parseTokenSep(s string) (string, error) {
	switch s {
	case "space":
		return " ", nil
	case "comma":
		return ",", nil
	case "colon":
		return ":", nil
	}
	if utf8.RuneCountInString(s) != 1 {
		return "", fmt.Errorf("a separator is one character or space, comma or colon, got %q", s)
	}
	r, _ := utf8.DecodeRuneInString(s)
	if r == utf8.RuneError || r == ':' || r == ',' || isSpec18Space(r) {
		return "", fmt.Errorf("a separator is one character other than `:`, `,` or whitespace, got %q", s)
	}
	return s, nil
}

// parseTokenList reads <sep>:<t1>,<t2>,… (0.18): every token one or more
// characters other than `:`, `,`, whitespace and the separator, none twice.
func parseTokenList(name, param string, hasParam bool) (string, []string, error) {
	sepText, list, ok := strings.Cut(param, ":")
	if !hasParam || !ok {
		return "", nil, fmt.Errorf("%s needs a separator and tokens: %s:<sep>:<token>", name, name)
	}
	sep, err := parseTokenSep(sepText)
	if err != nil {
		return "", nil, err
	}
	toks := strings.Split(list, ",")
	seen := map[string]bool{}
	for _, t := range toks {
		if t == "" {
			return "", nil, fmt.Errorf("%s: an empty token", name)
		}
		if strings.ContainsAny(t, ":, \t\n\r") || strings.Contains(t, sep) {
			return "", nil, fmt.Errorf("%s: token %q holds `:`, `,`, whitespace or the separator", name, t)
		}
		if seen[t] {
			return "", nil, fmt.Errorf("%s: token %q given twice", name, t)
		}
		seen[t] = true
	}
	return sep, toks, nil
}

// parseDerive reads the function of a `derive` line and checks what the line
// alone decides: the function name, its parameter and the argument count.
func parseDerive(d *Derive) error {
	name, param, hasParam := strings.Cut(d.Function, ":")
	arity, known := deriveArity[name]
	if !known {
		return fmt.Errorf("unknown derive function %q (copy, hypot, bearing, east_of, north_of, neg, scale:<factor>, offset:<n>, join:<sep>, day_seconds, any, not, parse_int, text_of, present, sec_of, nsec_of, ms_of, deg, rad, add, sub, deg_lat_of, deg_lon_of, m_lat_of, m_lon_of, ecef_x, ecef_y, ecef_z, lat_of_ecef, lon_of_ecef, hae_of_ecef)", d.Function)
	}
	d.name, d.param = name, param
	switch name {
	case "scale":
		if !hasParam {
			return fmt.Errorf("scale needs a factor: scale:<factor>")
		}
		if i := strings.IndexByte(param, '/'); i >= 0 {
			// <num> is integer text and <den> an unsigned decimal integer
			// that is not zero (ruling 2c of 0.11).
			num, e1 := parseIntText(param[:i])
			uden, e2 := parseUintText(param[i+1:], 1<<63-1)
			den := int64(uden)
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
	case "tokens", "has_token":
		sep, toks, err := parseTokenList(name, param, hasParam)
		if err != nil {
			return err
		}
		if name == "has_token" && len(toks) != 1 {
			return fmt.Errorf("has_token takes one token, got %d", len(toks))
		}
		if name == "tokens" && len(d.Args) != len(toks) {
			return fmt.Errorf("tokens takes one argument key per token: %d token(s), %d argument key(s)", len(toks), len(d.Args))
		}
		d.sep, d.toks = sep, toks
	case "text_if":
		if !hasParam || param == "" {
			return fmt.Errorf("text_if needs a text: text_if:<text>")
		}
		if strings.IndexFunc(param, isSpec18Space) >= 0 {
			return fmt.Errorf("text_if: the text holds whitespace")
		}
		d.text = param
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
				n, err := parseIntText(d.param)
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
		case "text_of", "tokens", "text_if":
			if target != KindString {
				return bad("%s needs a string target and int arguments", d.name)
			}
			for _, a := range args {
				if a != KindInt {
					return bad("%s needs a string target and int arguments", d.name)
				}
			}
		case "has_token":
			if target != KindInt || args[0] != KindString {
				return bad("has_token needs an int target and a string argument")
			}
		case "present":
			// The argument is any scalar key (0.12 ruling 3); a list is no key
			// and fails in typeOf.
			if target != KindInt {
				return bad("present needs an int target")
			}
		case "sec_of", "nsec_of", "ms_of":
			// spec 0.16 ruling 4: the types the table states, no promotion.
			if !all(KindInt) {
				return bad("%s needs an int target and int arguments", d.name)
			}
		case "add", "sub":
			// spec 0.16 ruling 4: all int or all float.
			switch {
			case all(KindInt):
				d.isInt = true
			case all(KindFloat):
			default:
				return bad("%s needs a target and arguments that are all int or all float", d.name)
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
	case "present":
		// The argument handed in is held by the entity, whatever its value
		// (spec 0.12 ruling 1).
		return Value{Kind: KindInt, I: 1}, true
	case "has_token":
		for _, part := range strings.Split(args[0].S, d.sep) {
			if part != "" && part == d.toks[0] {
				return Value{Kind: KindInt, I: 1}, true
			}
		}
		return Value{Kind: KindInt, I: 0}, true
	case "text_if":
		if args[0].I == 0 {
			return Value{}, false
		}
		return Value{Kind: KindString, S: d.text}, true
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
	case "sec_of", "nsec_of", "ms_of":
		return deriveTime(d.name, args)
	case "add", "sub":
		if d.isInt {
			return deriveIntSum(d.name, args[0].I, args[1].I)
		}
		if d.name == "add" {
			r = fl(0) + fl(1)
		} else {
			r = fl(0) - fl(1)
		}
	default:
		var ok bool
		if r, ok = deriveGeo(d.name, argOr(args, 0, fl), argOr(args, 1, fl), argOr(args, 2, fl)); !ok {
			return Value{}, false
		}
	}
	if math.IsNaN(r) || math.IsInf(r, 0) {
		return Value{}, false
	}
	return Value{Kind: KindFloat, F: r}, true
}

// addDerives records a loaded module's `derive` lines: the lines of every
// loaded module that has some, the modules in byte order of name, each
// module's lines in file order. It runs when the module loads, so a
// conversion only reads the list.
func (e *Engine) addDerives(m *Module) {
	i := sort.Search(len(e.deriveMods), func(i int) bool { return e.deriveMods[i].Name >= m.Name })
	e.deriveMods = append(e.deriveMods, nil)
	copy(e.deriveMods[i+1:], e.deriveMods[i:])
	e.deriveMods[i] = m
	out := []*Derive{}
	for _, dm := range e.deriveMods {
		for j := range dm.Derives {
			out = append(out, &dm.Derives[j])
		}
	}
	e.derives = out
}

// deriveLines returns every `derive` line of the loaded modules in
// application order (addDerives).
func (e *Engine) deriveLines() []*Derive { return e.derives }

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
			if d.name == "tokens" {
				// tokens needs only some of its arguments, and sets its
				// target once one of them is present and not 0 (0.18 ruling 7).
				var parts []string
				for i, a := range d.Args {
					if v, ok := ent.Fields[a]; ok && v.I != 0 {
						parts = append(parts, d.toks[i])
					}
				}
				if len(parts) > 0 {
					ent.Fields[d.Target] = Value{Kind: KindString, S: strings.Join(parts, d.sep)}
					set = true
				}
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

// readAs reads text as a model value of the given type. A number is read as
// written, without trimming: `"5 "` is not an int (0.18 ruling 18).
func readAs(text string, kind Kind) (Value, error) {
	if (kind == KindInt || kind == KindFloat) && strings.TrimSpace(text) != text {
		return Value{}, fmt.Errorf("%q is not a number: a number is read as written, without whitespace", text)
	}
	switch kind {
	case KindInt:
		i, err := parseIntText(text)
		if err != nil {
			return Value{}, fmt.Errorf("%q is not integer text", text)
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
	return e.fillInOrder(ent, keys, context)
}

// fillInOrder is Fill with the context keys checked in the order of keys, so
// the first failing key names the kind.
func (e *Engine) fillInOrder(ent *Entity, keys []string, context map[string]string) error {
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
