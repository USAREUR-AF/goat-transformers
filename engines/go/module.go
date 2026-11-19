package goatxf

import (
	"bufio"
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"
)

// Distribution markings (spec/engine-spec.md, "Version 0.4"). Public is below
// controlled.
const (
	DistPublic     = "public"
	DistControlled = "controlled"
)

// CoreModule is the module whose keys a pack writes bare and always uses.
const CoreModule = "core"

func validDistribution(d string) bool { return d == DistPublic || d == DistControlled }

// ModuleKey is one `key` line of a model module.
type ModuleKey struct {
	Name    string
	Type    Kind
	Unit    string // "-" when the key has no unit
	Meaning string
	Line    int
}

// Module is one parsed model/<module>.def: a named list of typed keys.
type Module struct {
	Name         string
	Version      string
	Distribution string
	Sources      []string
	Keys         []ModuleKey
	Lists        []ModuleList // `list` lines, in file order
	Derives      []Derive     // `derive` lines, in file order
	Uses         []string     // `uses` lines, in file order (spec 0.8); core is always used
	Source       string       // the file it was read from, for errors

	byName map[string]*ModuleKey
	lists  map[string]*ModuleList
}

// ModuleList is one `list` line of a model module (spec 0.7): a list is named
// like a key and shares the key namespace of its module.
type ModuleList struct {
	Name    string
	Meaning string
	Line    int
}

// IsList reports whether the module declares a list of that name.
func (m *Module) IsList(name string) bool {
	_, ok := m.lists[name]
	return ok
}

// Key returns the declaration of a key and whether the module declares it.
func (m *Module) Key(name string) (*ModuleKey, bool) {
	k, ok := m.byName[name]
	return k, ok
}

// kindName is the type word a module file uses for a Kind.
func kindName(k Kind) string {
	switch k {
	case KindString:
		return "string"
	case KindFloat:
		return "float"
	case KindInt:
		return "int"
	}
	return "unknown"
}

// transformYields returns the model type a transform produces (spec, "The
// type a transform yields").
func transformYields(name string) (Kind, bool) {
	switch name {
	case "string", "pstring", "ascii", "sixbit", "utf8", "hex":
		return KindString, true
	case "float", "pdouble", "pfloat", "f32", "f64":
		return KindFloat, true
	case "int", "iso8601_ms", "uint", "twos", "pvarint", "psint", "bool":
		return KindInt, true
	}
	if strings.HasPrefix(name, "linscale:") || strings.HasPrefix(name, "uscale:") || strings.HasPrefix(name, "sscale:") {
		return KindFloat, true
	}
	switch v015Base(name) {
	case "uiscale", "siscale", "smag", "iscale":
		return KindInt, true
	case "smscale", "f32scale", "f64scale", "scale":
		return KindFloat, true
	case "chars", "octal":
		return KindString, true
	}
	return textTransformYields(name)
}

// splitModelKey splits a pack's model key into module and key name: a key
// with no `.` belongs to core, otherwise the text before the first `.` is the
// module.
func splitModelKey(key string) (module, name string) {
	if i := strings.IndexByte(key, '.'); i >= 0 {
		return key[:i], key[i+1:]
	}
	return CoreModule, key
}

// ParseModuleFile reads and parses one model module file.
func ParseModuleFile(path string) (*Module, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, &Error{Kind: ErrBadDirective, Source: path, Detail: err.Error()}
	}
	return ParseModule(b, path)
}

// ParseModule parses model module text. source names it in errors. The keys
// and types of its `derive` lines are checked when the module is loaded into
// an engine.
func ParseModule(text []byte, source string) (*Module, error) {
	return parseModule(text, source)
}

// parseModule parses model module text. A `derive` line the file alone
// refuses (its function, parameter or argument count) is a line error,
// reported as the file is read and so before missing-distribution (0.6
// ruling 9, load vector 131). The checks of its keys and types against the
// loaded modules come later, in the order of 0.8 ruling 29.
func parseModule(text []byte, source string) (*Module, error) {
	m := &Module{Source: source, byName: map[string]*ModuleKey{}, lists: map[string]*ModuleList{}}
	perr := func(kind ErrorKind, line int, format string, a ...any) error {
		return &Error{Kind: kind, Module: m.Name, Source: source, Line: line, Detail: fmt.Sprintf(format, a...)}
	}
	if !utf8.Valid(text) {
		return nil, perr(ErrBadDirective, 0, "module file is not valid UTF-8")
	}
	seen := map[string]int{}
	// A key and a list share one namespace; a name declared twice is
	// duplicate-key, reported as the file is read.
	declared := map[string]int{}
	declare := func(name string, line int) error {
		if prev, dup := declared[name]; dup {
			return perr(ErrDuplicateKey, line, "name %q already declared on line %d", name, prev)
		}
		declared[name] = line
		return nil
	}
	// late holds the first failure of a module line that is not a line
	// check: it is reported after the file is read, before missing-module
	// (ruling 5b of 0.11).
	var late error
	lateErr := func(err error) {
		if late == nil {
			late = err
		}
	}
	sc := bufio.NewScanner(bytes.NewReader(text))
	sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
	n := 0
	for sc.Scan() {
		n++
		toks, err := tokenize(sc.Text())
		if err != nil {
			return nil, perr(ErrUnterminatedQuote, n, "%v", err)
		}
		if len(toks) == 0 {
			continue
		}
		kw, args := toks[0], toks[1:]
		switch kw {
		case "list":
			// list <name> ["meaning"]
			if len(args) != 1 && len(args) != 2 {
				return nil, perr(ErrBadDirective, n, "list takes 1 or 2 argument(s), got %d", len(args))
			}
			l := ModuleList{Name: args[0], Line: n}
			if l.Name == "" || strings.Contains(l.Name, ".") {
				lateErr(perr(ErrBadDirective, n, "list name %q must be non-empty and contain no '.'", l.Name))
				continue
			}
			if len(args) == 2 {
				l.Meaning = args[1]
			}
			if err := declare(l.Name, n); err != nil {
				lateErr(err)
				continue
			}
			m.Lists = append(m.Lists, l)
		case "module", "version", "distribution":
			if len(args) != 1 {
				return nil, perr(ErrBadDirective, n, "%s takes 1 argument(s), got %d", kw, len(args))
			}
			if prev, dup := seen[kw]; dup {
				return nil, perr(ErrBadDirective, n, "%s repeated (first on line %d)", kw, prev)
			}
			seen[kw] = n
			switch kw {
			case "module":
				if args[0] == "" || strings.Contains(args[0], ".") {
					lateErr(perr(ErrBadDirective, n, "module name %q must be non-empty and contain no '.'", args[0]))
					continue
				}
				m.Name = args[0]
			case "version":
				m.Version = args[0]
			case "distribution":
				if !validDistribution(args[0]) {
					return nil, perr(ErrBadDirective, n, "distribution must be public or controlled, got %q", args[0])
				}
				m.Distribution = args[0]
			}
		case "source":
			if len(args) != 1 {
				return nil, perr(ErrBadDirective, n, "source takes 1 argument(s), got %d", len(args))
			}
			m.Sources = append(m.Sources, args[0])
		case "uses":
			// uses <module>: the module's derive lines may take that module's
			// keys as arguments (spec 0.8, "Model additions").
			if len(args) != 1 {
				return nil, perr(ErrBadDirective, n, "uses takes 1 argument(s), got %d", len(args))
			}
			if args[0] == "" || strings.Contains(args[0], ".") {
				lateErr(perr(ErrBadDirective, n, "module name %q must be non-empty and contain no '.'", args[0]))
				continue
			}
			m.Uses = append(m.Uses, args[0])
		case "key":
			if len(args) != 3 && len(args) != 4 {
				return nil, perr(ErrBadDirective, n, "key takes 3 or 4 argument(s), got %d", len(args))
			}
			k := ModuleKey{Name: args[0], Unit: args[2], Line: n}
			if k.Name == "" || strings.Contains(k.Name, ".") {
				lateErr(perr(ErrBadDirective, n, "key name %q must be non-empty and contain no '.'", k.Name))
				continue
			}
			switch args[1] {
			case "string":
				k.Type = KindString
			case "float":
				k.Type = KindFloat
			case "int":
				k.Type = KindInt
			default:
				lateErr(perr(ErrBadDirective, n, "key %s: type must be string, float or int, got %q", k.Name, args[1]))
				continue
			}
			if len(args) == 4 {
				k.Meaning = args[3]
			}
			if err := declare(k.Name, n); err != nil {
				lateErr(err)
				continue
			}
			m.Keys = append(m.Keys, k)
		case "derive":
			// derive <model-key> <function> <argument-key> [<argument-key>…]
			if len(args) < 3 {
				return nil, perr(ErrBadDirective, n, "derive takes a key, a function and at least 1 argument key, got %d argument(s)", len(args))
			}
			d := Derive{Target: args[0], Function: args[1], Args: args[2:], Line: n}
			if err := parseDerive(&d); err != nil {
				lateErr(perr(ErrBadDirective, n, "derive %s: %v", d.Target, err))
				continue
			}
			m.Derives = append(m.Derives, d)
		default:
			return nil, perr(ErrUnknownDirective, n, "unknown directive %q", kw)
		}
	}
	if err := sc.Err(); err != nil {
		return nil, perr(ErrBadDirective, n, "%v", err)
	}
	for i := range m.Keys {
		m.byName[m.Keys[i].Name] = &m.Keys[i]
	}
	for i := range m.Lists {
		m.lists[m.Lists[i].Name] = &m.Lists[i]
	}
	// After the line checks: missing-module, missing-version, then the
	// order of 0.8 ruling 29 (ruling 5b of 0.11).
	if late != nil {
		return nil, late
	}
	if m.Name == "" {
		return nil, perr(ErrMissingModule, 0, "module has no module line")
	}
	if m.Version == "" {
		return nil, perr(ErrMissingVersion, 0, "module has no version line")
	}
	if m.Distribution == "" {
		return nil, perr(ErrMissingDistribution, 0, "module has no distribution line")
	}
	if len(m.Sources) == 0 {
		return nil, perr(ErrMissingSource, 0, "module has no source line")
	}
	return m, nil
}

// moduleHeader reads the `module` line and the `uses` lines of a module file
// without checking anything else. A file that does not read gives "".
func moduleHeader(path string) (name string, uses []string) {
	text, err := os.ReadFile(path)
	if err != nil {
		return "", nil
	}
	for _, ln := range strings.Split(string(text), "\n") {
		toks, err := tokenize(ln)
		if err != nil || len(toks) != 2 {
			continue
		}
		switch toks[0] {
		case "module":
			if name == "" {
				name = toks[1]
			}
		case "uses":
			uses = append(uses, toks[1])
		}
	}
	return name, uses
}

// moduleFiles lists every *.def under dir in loading order: core.def first
// whatever its name sorts as (0.6 ruling 9), then each module after the
// modules it uses (spec 0.8), ties in byte order of file name. A cycle of
// `uses` lines is bad-directive. A used module no file declares is left to
// the load, which reports unknown-module.
func moduleFiles(dir string) ([]string, error) {
	matches, err := filepath.Glob(filepath.Join(dir, "*.def"))
	if err != nil {
		return nil, err
	}
	isCore := func(path string) bool { return filepath.Base(path) == CoreModule+".def" }
	sort.SliceStable(matches, func(i, j int) bool {
		if ci, cj := isCore(matches[i]), isCore(matches[j]); ci != cj {
			return ci
		}
		return filepath.Base(matches[i]) < filepath.Base(matches[j])
	})
	// Read the `module` and `uses` lines of each file; a file that does not
	// read keeps its place and fails when it is loaded.
	names := make([]string, len(matches))
	uses := make([][]string, len(matches))
	fileOf := map[string]int{}
	for i, f := range matches {
		names[i], uses[i] = moduleHeader(f)
		if names[i] != "" {
			if _, dup := fileOf[names[i]]; !dup {
				fileOf[names[i]] = i
			}
		}
	}
	const (
		unseen = iota
		visiting
		done
	)
	state := make([]int, len(matches))
	out := make([]string, 0, len(matches))
	var visit func(i int) error
	visit = func(i int) error {
		switch state[i] {
		case done:
			return nil
		case visiting:
			return &Error{Kind: ErrBadDirective, Module: names[i], Source: matches[i], Detail: fmt.Sprintf("module %s is in a cycle of uses lines", names[i])}
		}
		state[i] = visiting
		for _, u := range uses[i] {
			if j, ok := fileOf[u]; ok {
				if err := visit(j); err != nil {
					return err
				}
			}
		}
		state[i] = done
		out = append(out, matches[i])
		return nil
	}
	for i := range matches {
		if err := visit(i); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// LoadModules parses every *.def under dir: core.def first, then the others
// in byte order of file name.
func LoadModules(dir string) ([]*Module, error) {
	matches, err := moduleFiles(dir)
	if err != nil {
		return nil, err
	}
	var mods []*Module
	for _, f := range matches {
		m, err := ParseModuleFile(f)
		if err != nil {
			return nil, err
		}
		mods = append(mods, m)
	}
	return mods, nil
}
