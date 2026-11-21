package goatxf

// The declarations of cborwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24; 0.28 ruling 38).

import (
	"fmt"
	"strconv"
	"strings"
)

// cborMaxDepth is the deepest nesting of arrays, maps and tags read (0.28,
// Reading a message, step 5).
const cborMaxDepth = 64

// cborMaxPos is the largest array position a path names.
const cborMaxPos = 65535

// cborConf is what the directives of a cbor pack state.
type cborConf struct {
	topArr bool   // the top item is an array (0.28, Types)
	hasTag bool   // `tag <n>`: the message is tag n enclosing the item
	tag    uint64 // n
}

// parseCBORTagValue reads the value of `tag <n>` on cbor: a decimal integer
// from 0 to 2^64-1 with no leading zero.
func parseCBORTagValue(s string) (uint64, bool) {
	if !isDigits(s) || (len(s) > 1 && s[0] == '0') {
		return 0, false
	}
	v, err := strconv.ParseUint(s, 10, 64)
	return v, err == nil
}

// --- paths ---

const (
	csInt  = iota + 1 // an integer key
	csText            // a text key
	csPos             // an array position
)

// cStep is one step of a path. An integer key is held as CBOR holds it: the
// major type (neg for major type 1) and the argument, so the value is arg,
// or -1-arg when neg.
type cStep struct {
	kind int
	neg  bool
	arg  uint64 // csInt: the argument; csPos: the position
	text string // csText
}

// id is the step's identity among the steps of one container.
func (s cStep) id() string {
	switch s.kind {
	case csInt:
		if s.neg {
			return "i1:" + strconv.FormatUint(s.arg, 10)
		}
		return "i0:" + strconv.FormatUint(s.arg, 10)
	case csText:
		return "t:" + s.text
	}
	return posID(s.arg)
}

func posID(i uint64) string { return "p:" + strconv.FormatUint(i, 10) }

// String is the step as a path writes it.
func (s cStep) String() string {
	switch s.kind {
	case csInt:
		if s.neg {
			// An addressable negative key has an argument below 2^63, so
			// arg+1 does not wrap.
			return "-" + strconv.FormatUint(s.arg+1, 10)
		}
		return strconv.FormatUint(s.arg, 10)
	case csText:
		return s.text
	}
	return "[" + strconv.FormatUint(s.arg, 10) + "]"
}

// keyBytes is the encoded map key of an integer or text step.
func (s cStep) keyBytes() []byte {
	if s.kind == csInt {
		var m byte
		if s.neg {
			m = 1
		}
		return cborHead(nil, m, s.arg)
	}
	return append(cborHead(nil, 3, uint64(len(s.text))), s.text...)
}

// isCBORTextKey reports whether s is a text key the step grammar writes: one
// or more ASCII letters, digits, `_` and `-`, not beginning with a digit or
// `-`.
func isCBORTextKey(s string) bool {
	if s == "" || s[0] == '-' || (s[0] >= '0' && s[0] <= '9') {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return false
		}
	}
	return true
}

// parseCBORStep reads one step of a path.
func parseCBORStep(s string) (cStep, bool) {
	if s == "" {
		return cStep{}, false
	}
	if s[0] == '[' {
		if len(s) < 3 || s[len(s)-1] != ']' {
			return cStep{}, false
		}
		d := s[1 : len(s)-1]
		if !isDigits(d) || len(d) > 5 || (len(d) > 1 && d[0] == '0') {
			return cStep{}, false
		}
		n, err := strconv.ParseUint(d, 10, 64)
		if err != nil || n > cborMaxPos {
			return cStep{}, false
		}
		return cStep{kind: csPos, arg: n}, true
	}
	if s[0] == '-' || (s[0] >= '0' && s[0] <= '9') {
		neg := s[0] == '-'
		d := s
		if neg {
			d = s[1:]
		}
		if !isDigits(d) || (len(d) > 1 && d[0] == '0') || (neg && d == "0") {
			return cStep{}, false
		}
		n, err := strconv.ParseUint(d, 10, 64)
		if err != nil {
			return cStep{}, false
		}
		if neg {
			if n > 1<<63 {
				return cStep{}, false
			}
			return cStep{kind: csInt, neg: true, arg: n - 1}, true
		}
		return cStep{kind: csInt, arg: n}, true
	}
	if !isCBORTextKey(s) {
		return cStep{}, false
	}
	return cStep{kind: csText, text: s}, true
}

// parseCBORPath reads a path of one or more steps separated by `.` (0.28,
// Paths). `.` itself is read by the line that holds it.
func parseCBORPath(s string) ([]cStep, error) {
	parts := strings.Split(s, ".")
	steps := make([]cStep, 0, len(parts))
	for _, part := range parts {
		st, ok := parseCBORStep(part)
		if !ok {
			return nil, fmt.Errorf("a cbor path is steps separated by '.': an integer key from -2^63 to 2^64-1 with no leading zero, a position [i] from 0 to 65535, or a text key of letters, digits, _ and - not beginning with a digit or -; got %q", s)
		}
		steps = append(steps, st)
	}
	return steps, nil
}

// --- `when` and `const` values ---

const (
	cvInt  = iota + 1 // an integer
	cvBool            // true or false
	cvText            // a text string
)

// cborVal is a `when` or `const` value on cbor, typed (0.28, Kinds).
type cborVal struct {
	kind int
	neg  bool   // cvInt: major type 1
	arg  uint64 // cvInt: the argument
	b    bool   // cvBool
	text string // cvText
	enc  []byte // the value's encoded item
}

// parseCBORValue types a `when` or `const` value: an integer when 2a of
// 0.11 accepts it and it lies in -2^63 to 2^64-1 (ruling 8), `true` or
// `false` a bool, any other value a text string with one leading `=`
// stripped (ruling 19).
func parseCBORValue(s string) cborVal {
	d, neg := s, false
	if strings.HasPrefix(s, "-") {
		d, neg = s[1:], true
	}
	if isDigits(d) {
		if n, err := strconv.ParseUint(d, 10, 64); err == nil {
			switch {
			case n == 0:
				return cborVal{kind: cvInt, enc: cborHead(nil, 0, 0)}
			case !neg:
				return cborVal{kind: cvInt, arg: n, enc: cborHead(nil, 0, n)}
			case n <= 1<<63:
				return cborVal{kind: cvInt, neg: true, arg: n - 1, enc: cborHead(nil, 1, n-1)}
			}
		}
	}
	switch s {
	case "true":
		return cborVal{kind: cvBool, b: true, enc: []byte{0xf5}}
	case "false":
		return cborVal{kind: cvBool, enc: []byte{0xf4}}
	}
	t := strings.TrimPrefix(s, "=")
	return cborVal{kind: cvText, text: t, enc: append(cborHead(nil, 3, uint64(len(t))), t...)}
}

const (
	cbUint = iota + 1
	cbInt
	cbFloat
	cbText
	cbBytes
	cbBool
	cbEpoch
)

var cborTransforms = map[string]int{
	"uint": cbUint, "int": cbInt, "float": cbFloat, "text": cbText,
	"bytes": cbBytes, "bool": cbBool, "epoch_s": cbEpoch,
}

// isCBOROnlyTransform reports a transform valid only on the cbor wire.
func isCBOROnlyTransform(name string) bool {
	return name == "text" || name == "bytes" || name == "epoch_s"
}

// cborHead writes a head in its shortest form.
func cborHead(out []byte, major byte, arg uint64) []byte {
	m := major << 5
	switch {
	case arg < 24:
		return append(out, m|byte(arg))
	case arg <= 0xff:
		return append(out, m|24, byte(arg))
	case arg <= 0xffff:
		return append(out, m|25, byte(arg>>8), byte(arg))
	case arg <= 0xffffffff:
		return append(out, m|26, byte(arg>>24), byte(arg>>16), byte(arg>>8), byte(arg))
	}
	return append(out, m|27, byte(arg>>56), byte(arg>>48), byte(arg>>40), byte(arg>>32), byte(arg>>24), byte(arg>>16), byte(arg>>8), byte(arg))
}

// cNode is one place the lines of a scope name: the top item, or a member
// or element some path reaches. Its kids are the places one step further,
// in the order of the first line that names each.
type cNode struct {
	step    cStep
	kids    []*cNode
	by      map[string]*cNode
	arr     bool     // the kids are positions: the item is an array
	fields  []*Field // the field lines at this place, in line order
	val     *When    // the first `when` or `const` with a value at this place
	present bool     // a `when … present` names this place
	group   *Group   // the group whose path this is
}

// walked reports whether a line walks into the place.
func (n *cNode) walked() bool { return len(n.kids) > 0 }

// mapped reports whether a line maps the place: a field, a `when` with a
// value, a `const` or a group (ruling 24).
func (n *cNode) mapped() bool { return len(n.fields) > 0 || n.val != nil || n.group != nil }

func (n *cNode) kid(id string) *cNode {
	if n == nil {
		return nil
	}
	return n.by[id]
}

// cborLinePath is the path of a line and what the line is: a field (not
// `.`), a `when` or `const`, or a group; ok is false for a line with no
// path in the tree (a `.` field).
func cborLinePath(ln line) (path []cStep, num int, loc string, ok bool) {
	switch {
	case ln.f != nil:
		if ln.f.dot {
			return nil, 0, "", false
		}
		return ln.f.loc.cpath, ln.f.Line, ln.f.Locator, true
	case ln.w != nil:
		return ln.w.loc.cpath, ln.w.Line, ln.w.Locator, true
	case ln.g != nil:
		return ln.g.loc.cpath, ln.g.Line, ln.g.Locator, true
	}
	return nil, 0, "", false
}

// cborTreeError is a line a scope's paths refuse.
type cborTreeError struct {
	line int
	loc  string
	msg  string
}

// cborTree indexes the paths of one scope and runs the checks of 0.28 that
// are stated within a scope: one place used as a map and as an array; a
// line at or under a group's path; a line whose path is a proper prefix of
// another's, unless the shorter is a `when … present` (rulings 13 and 22).
func cborTree(lines []line) (*cNode, *cborTreeError) {
	root := &cNode{by: map[string]*cNode{}}
	var first *cborTreeError
	fail := func(num int, loc, format string, a ...any) {
		if first == nil {
			first = &cborTreeError{line: num, loc: loc, msg: fmt.Sprintf(format, a...)}
		}
	}
	for _, ln := range lines {
		path, num, loc, ok := cborLinePath(ln)
		if !ok {
			continue
		}
		n := root
		for _, st := range path {
			isPos := st.kind == csPos
			if n.walked() && n.arr != isPos {
				fail(num, loc, "one item of the scope is used as a map and as an array")
			}
			if n.mapped() {
				fail(num, loc, "the path lies under the path of another line of the scope: an item is a value or a container, not both")
			}
			k := n.by[st.id()]
			if k == nil {
				if !n.walked() {
					n.arr = isPos
				}
				k = &cNode{step: st, by: map[string]*cNode{}}
				n.by[st.id()] = k
				n.kids = append(n.kids, k)
			}
			n = k
		}
		switch {
		case ln.g != nil:
			if n.mapped() || n.present || n.walked() {
				fail(num, loc, "a group's path is named by another line of the scope")
			}
			n.group = ln.g
		case ln.w != nil && ln.w.present:
			if n.group != nil {
				fail(num, loc, "a when stands at a group's path")
			}
			n.present = true
		default:
			if n.group != nil {
				fail(num, loc, "a line stands at a group's path")
			}
			if n.walked() {
				fail(num, loc, "the path is a prefix of the path of another line of the scope: an item is a value or a container, not both")
			}
			if ln.f != nil {
				n.fields = append(n.fields, ln.f)
			} else if n.val == nil {
				n.val = ln.w
			}
		}
	}
	return root, first
}

// --- load checks ---

const (
	ckMap = iota + 1 // an item is a map
	ckArr            // an item is an array
	ckDot            // an item is a scalar, read by `.`
)

// resolveCBOR reads the paths, transforms and values of a cbor pack and
// runs the checks of 0.28 that need the whole file. Every failure is
// bad-directive.
func (p *Pack) resolveCBOR(whens []*When, perr perrFunc) error {
	for _, g := range p.Groups {
		if g.hasCount {
			return perr(ErrBadDirective, g.Line, g.Locator, "group: `count` is valid only on wire bits")
		}
		if g.hasItem {
			return perr(ErrBadDirective, g.Line, g.Locator, "group: `item` is valid only on wire bits")
		}
		if g.Locator == "." {
			g.cdot = true
			continue
		}
		steps, err := parseCBORPath(g.Locator)
		if err != nil {
			return perr(ErrBadLocator, g.Line, g.Locator, "%v", err)
		}
		g.loc = locator{raw: g.Locator, cpath: steps}
	}
	for _, f := range p.Fields {
		if f.Locator == "." {
			f.dot = true
			f.loc = locator{raw: "."}
		} else {
			steps, err := parseCBORPath(f.Locator)
			if err != nil {
				return perr(ErrBadLocator, f.Line, f.Locator, "%v", err)
			}
			f.loc = locator{raw: f.Locator, cpath: steps}
		}
		tf, ok := cborTransforms[f.Transform]
		if !ok {
			return perr(ErrBadDirective, f.Line, f.Locator, "transform %q is not valid on wire cbor (uint, int, float, text, bytes, bool, epoch_s)", f.Transform)
		}
		f.ctf = tf
		for _, o := range []struct {
			set  bool
			name string
		}{{f.Absent != nil, "absent"}, {f.Swap, "swap"}, {f.Trim, "trim"}, {f.Optional, "optional"}} {
			if o.set {
				return perr(ErrBadDirective, f.Line, f.Locator, "field option `%s` is not valid on wire cbor", o.name)
			}
		}
		f.yields, _ = transformYields(f.Transform)
		if f.Via != "" {
			f.table = p.tables[f.Via]
			if f.table == nil {
				return perr(ErrBadDirective, f.Line, f.Locator, "`via %s` names a table with no map line", f.Via)
			}
		}
	}
	for _, w := range whens {
		steps, err := parseCBORPath(w.Locator)
		if err != nil {
			return perr(ErrBadLocator, w.Line, w.Locator, "%v", err)
		}
		w.loc = locator{raw: w.Locator, cpath: steps}
		if w.Value == "present" {
			if w.Const {
				return perr(ErrBadDirective, w.Line, w.Locator, "a const cannot be `present`; write `=present` for the text")
			}
			w.present = true
			continue
		}
		w.cv = parseCBORValue(w.Value)
	}
	// What an item is to each group body; a body that mixes `.` with other
	// paths is bad-directive (ruling 13).
	for _, g := range p.Groups {
		g.dots = nil
		paths, kind := 0, 0
		for _, ln := range g.lines {
			if ln.f != nil && ln.f.dot {
				g.dots = append(g.dots, ln.f)
				continue
			}
			path, _, _, ok := cborLinePath(ln)
			if !ok {
				continue
			}
			paths++
			if kind == 0 && len(path) > 0 {
				kind = ckMap
				if path[0].kind == csPos {
					kind = ckArr
				}
			}
		}
		if len(g.dots) > 0 && paths > 0 {
			return perr(ErrBadDirective, g.Line, g.Locator, "the body of group %s mixes `.` with other paths", g.List)
		}
		switch {
		case len(g.dots) > 0:
			g.ckind = ckDot
		case kind != 0:
			g.ckind = kind
		default:
			g.ckind = ckMap
		}
	}
	// The type of the top item: every path outside a group body decides it,
	// across the kinds (0.28, Types).
	decided, firstLine := 0, 0
	decide := func(lines []line) error {
		for _, ln := range lines {
			path, num, loc, ok := cborLinePath(ln)
			if !ok {
				continue
			}
			kind := ckMap
			if (ln.g != nil && ln.g.cdot) || (len(path) > 0 && path[0].kind == csPos) {
				kind = ckArr
			}
			if decided == 0 {
				decided, firstLine = kind, num
			} else if decided != kind {
				return perr(ErrBadDirective, num, loc, "the path decides the top item is %s, and the line on line %d decides otherwise", map[int]string{ckMap: "a map", ckArr: "an array"}[kind], firstLine)
			}
		}
		return nil
	}
	if err := decide(p.common); err != nil {
		return err
	}
	for _, k := range p.Kinds {
		if err := decide(k.lines); err != nil {
			return err
		}
	}
	p.cbor.topArr = decided == ckArr
	// The checks within one scope.
	check := func(lines []line) error {
		if _, e := cborTree(lines); e != nil {
			return perr(ErrBadDirective, e.line, e.loc, "%s", e.msg)
		}
		return nil
	}
	if p.HasKinds() {
		for _, k := range p.Kinds {
			if err := check(append(append([]line(nil), p.common...), k.lines...)); err != nil {
				return err
			}
		}
	} else if err := check(p.common); err != nil {
		return err
	}
	for _, g := range p.Groups {
		if err := check(g.lines); err != nil {
			return err
		}
	}
	return nil
}

// --- decode ---
