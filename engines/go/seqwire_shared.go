package goatxf

// The declarations of seqwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"fmt"
	"strconv"
	"strings"
)

// The operations of a sequential line.
const (
	seqField = iota + 1
	seqConst
	seqPad
	seqAlign
	seqWhen
	seqPresence
	seqIf
	seqOpt
	seqChain
	seqFx
	seqLength
	seqWhole
	seqGroup
	seqExt      // UPER: an `ext` block
	seqChoice   // UPER: a `choice` block; its body is its `alt` nodes
	seqAlt      // UPER: one `alt` of a choice; num is its index
	seqSwitchOp // a `switch` block (0.20)
	seqCaseOp   // the frame of a `case` or `else` body; not a line
	seqMsg      // the frame of a message body; not a line
	seqCountOp  // a `count <name> <len> [plus <n>]` line (0.21)
	seqInner    // an `inner <format>` line (0.34)
)

// How the items of a sequential group are delimited.
const (
	seqCount    = iota + 1 // a count field, then that many items
	seqWhile               // one bit before each item: 1 = an item follows, 0 = the list ends
	seqMore                // one bit before each item: 1 = another item follows this one
	seqFxMode              // one bit after each item: 1 = another item follows
	seqSize                // UPER `size <lb> <ub>`: the count as a constrained whole number
	seqSizeUnc             // UPER `size`: the count as a length determinant
	seqRest                // items until the end of the enclosing extent (0.21)
	seqLast                // one bit before each item: 1 = this is the last item (0.21)
	seqCountRef            // as many items as a named count line states (0.21)
)

// seqCountDef is one `count <name> <len> [plus <n>]` line (0.21): a count
// field at the cursor that one later group references by name.
type seqCountDef struct {
	name string
	n    int   // the bit length of the field
	plus int64 // what the field holds beyond the number of items
	line int
	// list and idx locate the line in its block: the lines after it, to the
	// end of the block, are its range. body is set when the line is among the
	// common lines of a body: the body's kinds are in its range too.
	list *[]*seqNode
	idx  int
	body *seqBody
}

// seqStructural names the directives the sequential parser reads; the others
// (format, wire, map, …) are read as in a fixed-layout pack.
var seqStructural = map[string]bool{
	"field": true, "const": true, "when": true, "pad": true, "align": true, "presence": true,
	"if": true, "opt": true, "chain": true, "fx": true, "length": true, "also": true,
	"group": true, "end": true, "kind": true, "requires": true, "default": true,
	"ext": true, "choice": true, "alt": true,
	"switch": true, "case": true, "else": true, "count": true,
	"inner": true,
}

// uperDirective names the block directives of spec 0.19; outside a
// sequential pack they are checked after the file (ruling 21).
var uperDirective = map[string]bool{"ext": true, "choice": true, "alt": true}

// seqOnly names the directives valid only in a sequential pack.
var seqOnly = map[string]bool{
	"pad": true, "align": true, "presence": true, "if": true, "opt": true,
	"chain": true, "fx": true, "length": true, "also": true,
	"ext": true, "choice": true, "alt": true,
	"switch": true, "case": true, "else": true, "count": true,
}

// hasSequentialLayout reports whether pack text has a `layout sequential`
// line.
func hasSequentialLayout(text []byte) bool {
	for rest := string(text); ; {
		i := strings.Index(rest, "layout")
		if i < 0 {
			return false
		}
		start := strings.LastIndexByte(rest[:i], '\n') + 1
		end := strings.IndexByte(rest[i:], '\n')
		if end < 0 {
			end = len(rest)
		} else {
			end += i
		}
		toks, err := tokenize(rest[start:end])
		if err == nil && len(toks) == 2 && toks[0] == "layout" && toks[1] == "sequential" {
			return true
		}
		if end >= len(rest) {
			return false
		}
		rest = rest[end+1:]
	}
}

// seqPresenceDef is one `presence` line: n bits read as one field, or with
// fx octets of 7 presence bits each followed by an extension bit. Bits are
// numbered from 1 in reading order.
type seqPresenceDef struct {
	name  string
	n     int
	fx    bool
	line  int
	named map[int]bool // the bits some `if` block outside every case names, with or without `!`
	// caseNamed holds, for each bit an `if` inside a case names, the
	// innermost case of each such `if`: the `if` counts only when that case
	// is read (0.20 ruling 21).
	caseNamed map[int][]*seqCase
}

// seqSwitch is one `switch` block (0.20): the key whose decoded value selects
// a case, the cases in line order and the `else`.
type seqSwitch struct {
	key   string
	line  int
	cases []*seqCase
	els   *seqCase
	seen  map[string]*seqCase // canonical value -> the case listing it, filled by the load checks
}

// seqCase is one `case` or the `else` of a switch.
type seqCase struct {
	sw       *seqSwitch
	line     int
	isElse   bool
	vals     []string        // as written
	canon    map[string]bool // canonical texts, set when the pack is loaded
	body     []*seqNode
	defaults []*Default
	block    *seqNode // identifies the case as a block for ruling 23 of 0.8
}

// seqCond is one bit an `if` line names.
type seqCond struct {
	p   *seqPresenceDef
	bit int
	neg bool
}

// seqNode is one line of a sequential body, or one block with its lines.
type seqNode struct {
	op    int
	line  int
	n     int // const, pad, when, length, whole: the bit length; align: the multiple
	num   uint64
	f     *Field
	pres  *seqPresenceDef
	conds []seqCond
	body  []*seqNode
	g     *Group
	bits  bool         // length: the block is counted in bits
	plus  int64        // length, whole: what the field holds beyond the length
	ext   bool         // choice: extensible
	rng   []numRange   // when: the listed values and ranges (0.20)
	sw    *seqSwitch   // switch
	cnt   *seqCountDef // count
	key   string       // when: the key `as` binds the bits to, "" for none (0.30)
	inner string       // inner: the format of the inner pack (0.34)
}

// seqKind is one kind of a body: of the message, or of the items of a group.
type seqKind struct {
	name     string
	line     int
	whens    []*seqNode
	requires []*reqTerm
	nodes    []*seqNode
	defaults []*Default
	defs     map[string]*Default // the defaults in scope: the body's, then the kind's
	all      []*seqNode          // the body's common lines, the kind's whens, then its lines
}

// seqBody is what one message, or one item of a group, holds: the lines
// common to every kind, then the kinds.
type seqBody struct {
	common   []*seqNode
	kinds    []*seqKind
	defaults []*Default
	defs     map[string]*Default
	whens    int // the common `when` lines
}

// modelKeys reports the keys and lists the body maps, in first appearance
// order. inner, when not nil, is called at each `inner` line in reading
// order with the format it names (0.34, Capability).
func (b *seqBody) modelKeys(add func(string), prefix string, inner func(string)) {
	var walk func(nodes []*seqNode)
	walk = func(nodes []*seqNode) {
		for _, n := range nodes {
			switch n.op {
			case seqWhen:
				// A key bound by `as` is listed at its when line (0.30
				// ruling 5).
				if n.key != "" {
					add(prefix + n.key)
				}
			case seqField:
				add(prefix + n.f.Key)
				for _, a := range n.f.also {
					add(prefix + a.Key)
				}
			case seqGroup:
				add(prefix + n.g.List + "[]")
				n.g.sbody.modelKeys(add, prefix+n.g.List+"[].", inner)
			case seqSwitchOp:
				for _, c := range n.sw.cases {
					walk(c.body)
				}
				if n.sw.els != nil {
					walk(n.sw.els.body)
				}
			case seqInner:
				if inner != nil {
					inner(n.inner)
				}
			default:
				walk(n.body)
			}
		}
	}
	walk(b.common)
	for _, k := range b.kinds {
		walk(k.whens)
		walk(k.nodes)
	}
}

// seqFrame is one open block while a sequential pack is read.
type seqFrame struct {
	op        int
	line      int
	node      *seqNode
	body      *seqBody // message and group frames
	kind      *seqKind // message and group frames: the kind being read
	kindNames map[string]int
	nodes     *[]*seqNode
	pres      map[string]*seqPresenceDef // the names declared in this block
	kpres     map[string]*seqPresenceDef // message and group frames: the names declared in the kind being read
	lists     map[string][]seqListAt     // message and group frames: the groups of the common lines, by list
	klists    map[string][]seqListAt     // the groups of the kind being read, by list
	last      *Field                     // the field line directly before, for `also`
	group     *Group
	mapped    map[string]bool // message and group frames: the keys a field or also line of the common lines maps so far
	kmapped   map[string]bool // the same, in the kind being read
	sw        *seqSwitch      // switch and case frames
	cas       *seqCase        // case frames
	// Count names (0.21): those declared in this block, and in message and
	// group frames those of the kind being read.
	cnts  map[string]*seqCountDef
	kcnts map[string]*seqCountDef
	// afterRest is set once a `rest` group, or a block holding one, has
	// ended in this block: a wire line after it is bad-directive (0.21
	// ruling 11). kafterRest is the same within the kind being read, and
	// restCase, in a switch frame, that a closed case held one.
	afterRest  bool
	kafterRest bool
	restCase   bool
	// afterInner is set once an `inner` line has stood in this block, and
	// kafterInner within the kind being read: a wire line after it in the
	// same extent is bad-directive after the file (0.34).
	afterInner  bool
	kafterInner bool
}

// seqListAt is one group of a scope: its line and the `if`, `opt` and `alt` blocks
// of the scope it sits in, innermost first.
type seqListAt struct {
	line   int
	blocks []*seqNode
}

// apart reports whether two groups of one list may share a scope: each sits
// in an `if`, `opt` or `alt` block, and neither block holds the other group
// (0.8 ruling 23, 0.19 ruling 20).
func (a seqListAt) apart(b seqListAt) bool {
	if len(a.blocks) == 0 || len(b.blocks) == 0 {
		return false
	}
	for _, x := range b.blocks {
		if x == a.blocks[0] {
			return false
		}
	}
	for _, x := range a.blocks {
		if x == b.blocks[0] {
			return false
		}
	}
	return true
}

// seqParser reads the structural lines of a sequential pack.
type seqParser struct {
	p      *Pack
	perr   func(kind ErrorKind, line int, loc, format string, a ...any) error
	stack  []*seqFrame
	bodies []*seqBody
	counts []*seqCountDef
	late   error // the first failure checked after the file (ruling 5b of 0.11)
}

// lateErr records a failure that is reported after the file.
func (sp *seqParser) lateErr(err error) {
	if sp.late == nil {
		sp.late = err
	}
}

func (sp *seqParser) init() {
	body := &seqBody{}
	sp.p.sbody = body
	sp.bodies = append(sp.bodies, body)
	sp.stack = []*seqFrame{{op: seqMsg, body: body, nodes: &body.common, kindNames: map[string]int{}, pres: map[string]*seqPresenceDef{}, cnts: map[string]*seqCountDef{}, lists: map[string][]seqListAt{}, mapped: map[string]bool{}}}
}

func (sp *seqParser) top() *seqFrame { return sp.stack[len(sp.stack)-1] }

// scope returns the innermost message or group frame.
func (sp *seqParser) scope() *seqFrame {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		if f := sp.stack[i]; f.op == seqMsg || f.op == seqGroup {
			return f
		}
	}
	return sp.stack[0]
}

func (sp *seqParser) bad(line int, loc, format string, a ...any) error {
	return sp.perr(ErrBadDirective, line, loc, format, a...)
}

// bitLen reads a bit length of 1 to max bits. A positional locator is
// refused.
func (sp *seqParser) bitLen(kw, text string, max, line int) (int, error) {
	if strings.Contains(text, ":") {
		return 0, sp.bad(line, text, "%s: a locator in a sequential pack is a bit length, not <word>:<pos>:<len>", kw)
	}
	n, err := parseSmallUint(text)
	if err != nil || n < 1 || n > max {
		return 0, sp.bad(line, text, "%s takes a bit length of 1 to %d, got %q", kw, max, text)
	}
	return n, nil
}

// value reads the unsigned value of a `const` or `when` of n bits.
func (sp *seqParser) value(kw, text string, n, line int) (uint64, error) {
	v, err := parseUintText(text, 1<<64-1)
	if err != nil {
		return 0, sp.bad(line, "", "a %s value is an unsigned decimal integer, got %q", kw, text)
	}
	if n < 64 && v>>uint(n) != 0 {
		return 0, sp.bad(line, "", "%s value %d does not fit in %d bit(s)", kw, v, n)
	}
	return v, nil
}

// lookup finds the presence a name refers to where the line stands: the
// innermost block that declares it.
func (sp *seqParser) lookup(name string) (*seqPresenceDef, *seqCountDef) {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		if pr := f.kpres[name]; pr != nil {
			return pr, nil
		}
		if cd := f.kcnts[name]; cd != nil {
			return nil, cd
		}
		if pr := f.pres[name]; pr != nil {
			return pr, nil
		}
		if cd := f.cnts[name]; cd != nil {
			return nil, cd
		}
	}
	return nil, nil
}

// lookupCount finds the count a `count @<name>` reference names: the
// innermost declaration of the name within the group body the line stands
// in (0.21 rulings 9, 15 and 24).
func (sp *seqParser) lookupCount(name string) (*seqCountDef, error) {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		for _, m := range []struct {
			p map[string]*seqPresenceDef
			c map[string]*seqCountDef
		}{{f.kpres, f.kcnts}, {f.pres, f.cnts}} {
			if m.p[name] != nil {
				return nil, fmt.Errorf("count @%s names a presence, not a count", name)
			}
			if cd := m.c[name]; cd != nil {
				return cd, nil
			}
		}
		if f.op == seqMsg || f.op == seqGroup {
			break
		}
	}
	return nil, fmt.Errorf("count @%s names no count visible here in the same group body", name)
}

// declared reports the line of a presence or count of the name declared in
// the block of the top frame; 0 when there is none. The common lines and a
// kind are one block (0.8 ruling 12, 0.21 ruling 15).
func (sp *seqParser) declared(name string) int {
	top := sp.top()
	if pr := top.pres[name]; pr != nil {
		return pr.line
	}
	if cd := top.cnts[name]; cd != nil {
		return cd.line
	}
	if top.kind != nil {
		if pr := top.kpres[name]; pr != nil {
			return pr.line
		}
		if cd := top.kcnts[name]; cd != nil {
			return cd.line
		}
	}
	return 0
}

// wireLine refuses a line that reads or writes bits after a `rest` group of
// the same extent (0.21 rulings 11, 26 and 32).
func (sp *seqParser) wireLine(kw string, n int) error {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		if f.afterRest || f.kafterRest {
			return sp.bad(n, "", "%s stands after a rest group of the same extent; a rest group is the last line of its extent", kw)
		}
		// After an `inner` line the same holds, checked after the file
		// (0.34, "The inner line").
		if f.afterInner || f.kafterInner {
			sp.lateErr(sp.bad(n, "", "%s stands after an inner line of the same extent; an inner line is the last wire line of its extent", kw))
		}
		if f.op == seqLength || f.op == seqMsg || f.op == seqGroup {
			break
		}
	}
	return nil
}

// restEnded records in a frame that a `rest` group, or a block holding one,
// has ended in it.
func restEnded(f *seqFrame) {
	if (f.op == seqMsg || f.op == seqGroup) && f.kind != nil {
		f.kafterRest = true
	} else {
		f.afterRest = true
	}
}

// innerCase returns the innermost case or else body the line stands in, nil
// when it stands in none. With inScope the search stops at the innermost
// message or group body.
func (sp *seqParser) innerCase(inScope bool) *seqCase {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		if f.op == seqCaseOp {
			return f.cas
		}
		if inScope && (f.op == seqMsg || f.op == seqGroup) {
			return nil
		}
	}
	return nil
}

// caseOfIf returns the innermost case that holds an `if` line being read
// and not the presence it names, nil when there is none; the search crosses
// group bodies (0.20 rulings 21 and 30).
func (sp *seqParser) caseOfIf(pr *seqPresenceDef) *seqCase {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		if f.pres[pr.name] == pr || f.kpres[pr.name] == pr {
			return nil
		}
		if f.op == seqCaseOp {
			return f.cas
		}
	}
	return nil
}

func (sp *seqParser) push(f *seqFrame) {
	if f.pres == nil {
		f.pres = map[string]*seqPresenceDef{}
	}
	if f.cnts == nil {
		f.cnts = map[string]*seqCountDef{}
	}
	sp.stack = append(sp.stack, f)
}

// line reads one structural line.
func (sp *seqParser) line(kw string, args []string, n int) error {
	p := sp.p
	top := sp.top()
	last := top.last
	top.last = nil
	add := func(node *seqNode) {
		node.line = n
		*top.nodes = append(*top.nodes, node)
	}
	count := func(want int) error {
		if len(args) != want {
			return sp.bad(n, "", "%s takes %d argument(s), got %d", kw, want, len(args))
		}
		return nil
	}
	// A choice holds only `alt` lines; `end` with no `alt` is a choice with
	// none (spec 0.19 and its ruling 19); both are reported after the file
	// (ruling 26).
	if top.op == seqChoice && kw != "alt" {
		if kw == "end" {
			sp.lateErr(sp.bad(n, "", "the choice on line %d has no alt line", top.line))
			sp.stack = sp.stack[:len(sp.stack)-1]
			return nil
		}
		// A line between a choice and its first alt is reported after the
		// file (ruling 26); the line is still read, so a later line's error
		// comes first.
		sp.lateErr(sp.bad(n, "", "a %s line stands between choice (line %d) and its first alt", kw, top.line))
	}
	// Between `switch` and its first `case` no line stands (0.20 ruling 20).
	if top.op == seqSwitchOp && kw != "case" && kw != "else" && kw != "end" {
		return sp.bad(n, "", "%s stands between the switch on line %d and its first case", kw, top.line)
	}
	// mark records a key a field or also line maps, for the switch lines
	// that follow in the scope.
	mark := func(key string) {
		sc := sp.scope()
		if sc.kind != nil {
			sc.kmapped[key] = true
		} else {
			sc.mapped[key] = true
		}
	}
	switch kw {
	// An ext reads its extension bit, so it is a wire line; a choice is one
	// when it reads bits itself (0.21 ruling 41, checked at its line).
	case "field", "const", "pad", "align", "presence", "opt", "fx", "length", "group", "count", "ext", "inner":
		if err := sp.wireLine(kw, n); err != nil {
			return err
		}
	case "when":
		if top.kind != nil || top.op == seqMsg || top.op == seqGroup {
			if err := sp.wireLine(kw, n); err != nil {
				return err
			}
		}
	}
	switch kw {
	case "ext":
		if sp.p.uperLine == 0 {
			sp.p.uperLine = n
		}
		node := &seqNode{op: seqExt}
		add(node)
		sp.push(&seqFrame{op: seqExt, line: n, node: node, nodes: &node.body})
	case "choice":
		// The argument count (one or two) is a line check; the values are
		// checked after the file (rulings 23 and 26 of 0.19).
		if sp.p.uperLine == 0 {
			sp.p.uperLine = n
		}
		if len(args) == 2 && args[1] != "ext" {
			sp.lateErr(sp.bad(n, "", "choice is `choice <n> [ext]`, got %q", args[1]))
		}
		c, ok := uperCount(args[0])
		if !ok || c < 1 || c > 65536 {
			sp.lateErr(sp.bad(n, "", "choice takes a number of alternatives from 1 to 65536, got %q", args[0]))
			c = 0
		}
		// A choice with ext or more than one root alternative reads bits,
		// so it is a wire line; one with a single alt is one only when the
		// alt holds a wire line, which wireLine checks at that line (0.21
		// ruling 41).
		if len(args) == 2 || c > 1 {
			if err := sp.wireLine(kw, n); err != nil {
				return err
			}
		}
		node := &seqNode{op: seqChoice, num: uint64(c), ext: len(args) == 2}
		add(node)
		sp.push(&seqFrame{op: seqChoice, line: n, node: node, nodes: &node.body})
	case "alt":
		// An alt out of range, repeated or outside a choice is checked
		// after the file (ruling 26 of 0.19); the lines under it are read.
		if sp.p.uperLine == 0 {
			sp.p.uperLine = n
		}
		var ch *seqFrame
		switch {
		case top.op == seqChoice:
			ch = top
		case top.op == seqAlt:
			ch = sp.stack[len(sp.stack)-2]
		default:
			sp.lateErr(sp.bad(n, "", "an alt line stands directly in a choice"))
			return nil
		}
		idx, ok := uperCount(args[0])
		switch {
		case !ok || uint64(idx) >= ch.node.num:
			sp.lateErr(sp.bad(n, "", "alt takes an index below the choice's %d alternatives, got %q", ch.node.num, args[0]))
		default:
			for _, a := range ch.node.body {
				if a.num == uint64(idx) {
					sp.lateErr(sp.bad(n, "", "alt %d is already given on line %d", idx, a.line))
					break
				}
			}
		}
		if top.op == seqAlt {
			// An alt that held a rest group: the lines after the choice
			// follow it (0.21 ruling 39, as for a case).
			if top.afterRest {
				ch.restCase = true
			}
			sp.stack = sp.stack[:len(sp.stack)-1]
		}
		node := &seqNode{op: seqAlt, num: uint64(idx), line: n}
		ch.node.body = append(ch.node.body, node)
		sp.push(&seqFrame{op: seqAlt, line: n, node: node, nodes: &node.body})
	case "field":
		f := &Field{Key: args[0], Locator: args[1], Transform: args[2], Line: n}
		if kind, err := p.checkFieldLine(f, args[3:], false); err != nil {
			return sp.perr(kind, n, f.Locator, "%v", err)
		}
		p.Fields = append(p.Fields, f)
		p.keyRefs = append(p.keyRefs, keyRef{key: f.Key, locator: f.Locator, line: n, field: f})
		p.addWithRef(f)
		add(&seqNode{op: seqField, f: f})
		mark(f.Key)
		top.last = f
	case "also":
		// also <key> [via <table>]: another key on the bits of the field
		// line directly before (0.8 ruling 13).
		if last == nil {
			return sp.bad(n, "", "also must come directly after a field line")
		}
		if len(args) != 1 && !(len(args) == 3 && args[1] == "via" && args[2] != "") {
			return sp.bad(n, "", "also is `also <key> [via <table>]`")
		}
		f := &Field{Key: args[0], Locator: last.Locator, Transform: last.Transform, Line: n, Swap: last.Swap, Trim: last.Trim}
		if len(args) == 3 {
			f.Via = args[2]
		}
		last.also = append(last.also, f)
		mark(f.Key)
		p.Fields = append(p.Fields, f)
		p.keyRefs = append(p.keyRefs, keyRef{key: f.Key, locator: f.Locator, line: n, field: f})
		top.last = last
	case "const":
		ln, err := sp.bitLen(kw, args[0], 64, n)
		if err != nil {
			return err
		}
		// The form of the value is checked after the file (ruling 5b of
		// 0.11).
		v, err := sp.value(kw, args[1], ln, n)
		if err != nil {
			sp.lateErr(err)
		}
		add(&seqNode{op: seqConst, n: ln, num: v})
	case "pad":
		ln, err := sp.bitLen(kw, args[0], 1<<24, n)
		if err != nil {
			return err
		}
		add(&seqNode{op: seqPad, n: ln})
	case "align":
		m, err := parseSmallUint(args[0])
		if err != nil || m < 1 {
			return sp.bad(n, "", "align takes a number of bits >= 1, got %q", args[0])
		}
		add(&seqNode{op: seqAlign, n: m})
	case "when":
		// A `when` before the first `kind` of its body is common; a kind's
		// `when` lines are its first lines (0.8 ruling 10).
		if top.op != seqMsg && top.op != seqGroup {
			return sp.bad(n, "", "a when line is not allowed inside a block")
		}
		ln, err := sp.bitLen(kw, args[0], 64, n)
		if err != nil {
			return err
		}
		// The form of the value, a list of values and ranges since 0.20,
		// is checked after the file (ruling 5b of 0.11).
		rs, err := parseNumList(args[1], ln)
		if err != nil {
			sp.lateErr(sp.bad(n, "", "%v", err))
			rs = []numRange{{}}
		}
		node := &seqNode{op: seqWhen, n: ln, num: rs[0].lo, rng: rs, line: n}
		// `as <model-key>` after the values (0.30). Its syntax is checked
		// after the file (ruling 16); ParsePack lets a line through the
		// argument count only when its third token is `as`.
		if len(args) > 2 {
			switch {
			case len(args) == 3:
				sp.lateErr(sp.bad(n, "", "when … as needs a model key after as"))
			case args[3] == "as" || hasToken(args[4:], "as"):
				sp.lateErr(sp.bad(n, "", "as stands twice on one when line"))
			case len(args) > 4:
				sp.lateErr(sp.bad(n, "", "when … as <model-key> takes no token after the key, got %q", args[4]))
			default:
				node.key = args[3]
				p.keyRefs = append(p.keyRefs, keyRef{key: node.key, line: n, as: true})
				// A kind's `as` key counts as mapped from the start of its
				// kind, a common one from its own line (ruling 2); a kind's
				// when lines are its first lines, so both are marked here.
				mark(node.key)
			}
		}
		if k := top.kind; k != nil {
			if len(k.nodes) > 0 {
				return sp.bad(n, "", "the when lines of kind %s must be its first lines", k.name)
			}
			k.whens = append(k.whens, node)
		} else {
			top.body.whens++
			add(node)
		}
	case "kind":
		if top.op != seqMsg && top.op != seqGroup {
			return sp.bad(n, "", "a kind line is not allowed inside a block")
		}
		if prev, dup := top.kindNames[args[0]]; dup {
			sp.lateErr(sp.perr(ErrDuplicateKind, n, "", "kind %q already declared on line %d", args[0], prev))
		}
		top.kindNames[args[0]] = n
		k := &seqKind{name: args[0], line: n}
		top.body.kinds = append(top.body.kinds, k)
		top.kind, top.nodes = k, &k.nodes
		top.kpres, top.klists, top.kmapped = map[string]*seqPresenceDef{}, map[string][]seqListAt{}, map[string]bool{}
		top.kcnts, top.kafterRest, top.kafterInner = map[string]*seqCountDef{}, false, false
		if top.op == seqMsg {
			p.Kinds = append(p.Kinds, &KindDef{Name: k.name, Line: n})
		}
	case "requires":
		if (top.op != seqMsg && top.op != seqGroup) || top.kind == nil {
			return sp.bad(n, "", "requires must stand in a kind, outside any block")
		}
		terms, err := parseRequires(args, n)
		if err != nil {
			return sp.bad(n, "", "%v", err)
		}
		p.addRequires(terms, n)
		top.kind.requires = append(top.kind.requires, terms...)
		if top.op == seqMsg {
			kd := p.Kinds[len(p.Kinds)-1]
			for _, t := range terms {
				kd.Requires = append(kd.Requires, t.key)
			}
			kd.reqs = append(kd.reqs, terms...)
		}
	case "default":
		// A default belongs to the message or the item it stands in.
		d := &Default{Key: args[0], Value: args[1], Line: n}
		p.keyRefs = append(p.keyRefs, keyRef{key: d.Key, line: n, def: d})
		// In a case it belongs to the case (0.20 rulings 7 and 22).
		if c := sp.innerCase(true); c != nil {
			c.defaults = append(c.defaults, d)
			break
		}
		sc := sp.scope()
		if sc.kind != nil {
			sc.kind.defaults = append(sc.kind.defaults, d)
		} else {
			sc.body.defaults = append(sc.body.defaults, d)
		}
	case "presence":
		name := args[0]
		if name == "" || strings.ContainsAny(name, ".!") {
			return sp.bad(n, "", "presence name %q must be non-empty and hold no '.' or '!'", name)
		}
		// Inside an ext block a presence line is the first line (0.19
		// ruling 15).
		if top.op == seqExt && len(top.node.body) > 0 {
			return sp.bad(n, "", "a presence line in an ext block is its first line")
		}
		pr := &seqPresenceDef{name: name, line: n, named: map[int]bool{}, caseNamed: map[int][]*seqCase{}}
		if args[1] == "fx" {
			pr.fx = true
		} else {
			bits, err := sp.bitLen(kw, args[1], 64, n)
			if err != nil {
				return err
			}
			pr.n = bits
		}
		// A name is declared once in a block; the common lines and a kind
		// are one block (0.8 ruling 12).
		if prev := sp.declared(name); prev != 0 {
			return sp.bad(n, "", "presence %s: the name is already declared in this block on line %d", name, prev)
		}
		if top.kind != nil {
			top.kpres[name] = pr
		} else {
			top.pres[name] = pr
		}
		add(&seqNode{op: seqPresence, pres: pr})
	case "if":
		node := &seqNode{op: seqIf}
		for _, a := range args {
			c := seqCond{}
			text := a
			if strings.HasPrefix(text, "!") {
				c.neg, text = true, text[1:]
			}
			i := strings.LastIndexByte(text, '.')
			if i <= 0 {
				return sp.bad(n, "", "if names presence bits as <name>.<i>, got %q", a)
			}
			bit, err := parseSmallUint(text[i+1:])
			if err != nil || bit < 1 {
				return sp.bad(n, "", "if names presence bits as <name>.<i> with i >= 1, got %q", a)
			}
			var cd *seqCountDef
			c.p, cd = sp.lookup(text[:i])
			if cd != nil {
				return sp.bad(n, "", "if names %q, which is a count, not a presence", text[:i])
			}
			if c.p == nil {
				return sp.bad(n, "", "if names presence %q, which is not visible here", text[:i])
			}
			if !c.p.fx && bit > c.p.n {
				return sp.bad(n, "", "if names bit %d of presence %s, which has %d bit(s)", bit, c.p.name, c.p.n)
			}
			c.bit = bit
			if cs := sp.caseOfIf(c.p); cs != nil {
				c.p.caseNamed[bit] = append(c.p.caseNamed[bit], cs)
			} else {
				c.p.named[bit] = true
			}
			node.conds = append(node.conds, c)
		}
		add(node)
		sp.push(&seqFrame{op: seqIf, line: n, node: node, nodes: &node.body})
	case "opt", "chain":
		if err := count(0); err != nil {
			return err
		}
		node := &seqNode{op: seqOpt}
		if kw == "chain" {
			node.op = seqChain
		}
		add(node)
		sp.push(&seqFrame{op: node.op, line: n, node: node, nodes: &node.body})
	case "fx":
		if top.op != seqChain {
			return sp.bad(n, "", "an fx line stands directly in a chain")
		}
		add(&seqNode{op: seqFx})
	case "length":
		// length <len> [bytes|bits] [plus <n>] [whole], the words after the
		// length in any order (0.8 ruling 8).
		ln, err := sp.bitLen(kw, args[0], 64, n)
		if err != nil {
			return err
		}
		node := &seqNode{op: seqLength, n: ln}
		unit, plus, whole := "", false, false
		for i := 1; i < len(args); i++ {
			switch a := args[i]; {
			case (a == "bytes" || a == "bits") && unit == "":
				unit = a
			case a == "plus" && !plus && i+1 < len(args):
				i++
				v, err := parseIntText(args[i])
				if err != nil {
					return sp.bad(n, "", "length: `plus` takes an integer, got %q", args[i])
				}
				plus, node.plus = true, v
			case a == "whole" && !whole:
				whole = true
			default:
				return sp.bad(n, "", "length is `length <len> [bytes|bits] [plus <n>] [whole]`: unknown, repeated or incomplete word %q", a)
			}
		}
		node.bits = unit == "bits"
		if whole {
			if node.bits {
				return sp.bad(n, "", "length: `whole` counts bytes; `bits` with `whole` is not allowed")
			}
			node.op = seqWhole
			if sp.p.wholeLine == 0 {
				sp.p.wholeLine = n
			}
			add(node)
			break
		}
		add(node)
		sp.push(&seqFrame{op: seqLength, line: n, node: node, nodes: &node.body})
	case "group":
		// group <list> count <len> | while | more | fx
		g := &Group{List: args[0], Locator: strings.Join(args[1:], " "), Line: n}
		for i := len(sp.stack) - 1; i >= 0; i-- {
			if sp.stack[i].op == seqGroup {
				g.parent = sp.stack[i].group
				break
			}
		}
		switch {
		case len(args) == 2 && args[1] == "rest":
			// A rest group inside an item stands in a length block of the
			// item, or is the last line of an item of a rest group (0.21
			// ruling 10).
			for i := len(sp.stack) - 1; i >= 0; i-- {
				fr := sp.stack[i]
				if fr.op == seqLength || fr.op == seqMsg {
					break
				}
				if fr.op == seqGroup {
					if fr.group.seqMode != seqRest {
						return sp.bad(n, g.Locator, "a rest group inside an item of list %s stands outside any length block of the item, and that list is not a rest list", fr.group.List)
					}
					fr.group.innerRest = true
					break
				}
			}
			g.seqMode = seqRest
		case len(args) == 2 && args[1] == "last":
			g.seqMode = seqLast
		case len(args) == 3 && args[1] == "count" && strings.HasPrefix(args[2], "@"):
			cd, err := sp.lookupCount(args[2][1:])
			if err != nil {
				return sp.bad(n, g.Locator, "%v", err)
			}
			g.seqMode, g.cnt = seqCountRef, cd
		case len(args) == 3 && args[1] == "count":
			bits, err := sp.bitLen("group count", args[2], 64, n)
			if err != nil {
				return err
			}
			g.seqMode, g.countBits = seqCount, bits
		case len(args) == 2 && args[1] == "while":
			g.seqMode = seqWhile
		case len(args) == 2 && args[1] == "more":
			g.seqMode = seqMore
		case len(args) == 2 && args[1] == "fx":
			g.seqMode = seqFxMode
		case (len(args) == 2 || len(args) == 4) && args[1] == "size":
			// UPER SEQUENCE OF (spec 0.19, ruling 12).
			if sp.p.uperLine == 0 {
				sp.p.uperLine = n
			}
			g.seqMode = seqSizeUnc
			if len(args) == 4 {
				lb, ok1 := uperCount(args[2])
				ub, ok2 := uperCount(args[3])
				if !ok1 || !ok2 || lb > ub || lb >= 65536 || ub >= 65536 {
					return sp.bad(n, g.Locator, "group size takes <lb> <ub> with 0 <= lb <= ub < 65536, got %s %s", args[2], args[3])
				}
				g.seqMode, g.sizeLB, g.sizeUB = seqSize, int(lb), int(ub)
			}
		default:
			return sp.bad(n, g.Locator, "a sequential group is `group <list> count <len>`, `count @<name>`, `while`, `more`, `fx`, `rest`, `last` or `size [<lb> <ub>]`")
		}
		// Within one scope a list is mapped by one group, or by groups that
		// sit in different `if`, `opt` or `alt` blocks (0.8 ruling 23, 0.19
		// ruling 20).
		sc := sp.scope()
		here := seqListAt{line: n}
		for i := len(sp.stack) - 1; i >= 0 && sp.stack[i] != sc; i-- {
			if fr := sp.stack[i]; fr.op == seqIf || fr.op == seqOpt || fr.op == seqAlt {
				here.blocks = append(here.blocks, fr.node)
			} else if fr.op == seqCaseOp {
				// Each case and else body is a block (0.20 ruling 10).
				here.blocks = append(here.blocks, fr.cas.block)
			}
		}
		for _, prev := range append(append([]seqListAt(nil), sc.lists[g.List]...), sc.klists[g.List]...) {
			if !here.apart(prev) {
				return sp.bad(n, g.Locator, "list %s is already mapped by the group on line %d of the same scope, and the two are not in different if, opt or alt blocks", g.List, prev.line)
			}
		}
		if sc.kind != nil {
			sc.klists[g.List] = append(sc.klists[g.List], here)
		} else {
			sc.lists[g.List] = append(sc.lists[g.List], here)
		}
		g.sbody = &seqBody{}
		sp.bodies = append(sp.bodies, g.sbody)
		p.keyRefs = append(p.keyRefs, keyRef{key: g.List, locator: g.Locator, line: n, group: g})
		add(&seqNode{op: seqGroup, g: g})
		sp.push(&seqFrame{op: seqGroup, line: n, group: g, body: g.sbody, nodes: &g.sbody.common, kindNames: map[string]int{}, lists: map[string][]seqListAt{}, mapped: map[string]bool{}})
	case "inner":
		// inner <format> (0.34): in the common lines, a kind or length
		// blocks, at any depth of length blocks; under any other block it is
		// bad-directive after the file.
		for _, f := range sp.stack[1:] {
			if f.op != seqLength {
				sp.lateErr(sp.bad(n, "", "inner stands in a block opened on line %d; it stands only in the common lines, in a kind and in length blocks", f.line))
				break
			}
		}
		add(&seqNode{op: seqInner, inner: args[0]})
		if p.innerLine == 0 {
			p.innerLine = n
		}
		if !p.hasInnerFor(args[0]) {
			p.innerFormats = append(p.innerFormats, args[0])
		}
		if top.op == seqMsg && top.kind != nil {
			top.kafterInner = true
		} else {
			top.afterInner = true
		}
	case "count":
		// count <name> <len> [plus <n>] (0.21)
		name := args[0]
		if name == "" || strings.ContainsAny(name, ".!@") {
			return sp.bad(n, "", "count name %q must be non-empty and hold no '.', '!' or '@'", name)
		}
		ln, err := sp.bitLen(kw, args[1], 64, n)
		if err != nil {
			return err
		}
		cd := &seqCountDef{name: name, n: ln, line: n}
		switch {
		case len(args) == 2:
		case len(args) == 4 && args[2] == "plus":
			v, ok := parsePlus(args[3])
			if !ok {
				return sp.bad(n, "", "count: `plus` takes an optional '-' then digits within signed 64 bits, got %q", args[3])
			}
			cd.plus = v
		default:
			return sp.bad(n, "", "a count line is `count <name> <len> [plus <n>]`")
		}
		if prev := sp.declared(name); prev != 0 {
			return sp.bad(n, "", "count %s: the name is already declared in this block on line %d", name, prev)
		}
		if top.kind != nil {
			top.kcnts[name] = cd
		} else {
			top.cnts[name] = cd
		}
		cd.list, cd.idx = top.nodes, len(*top.nodes)
		if (top.op == seqMsg || top.op == seqGroup) && top.kind == nil {
			cd.body = top.body
		}
		sp.counts = append(sp.counts, cd)
		add(&seqNode{op: seqCountOp, cnt: cd})
	case "switch":
		// switch <model-key>: the key is mapped by a field or also line of
		// the scope before this line (0.20).
		key := args[0]
		sc := sp.scope()
		if !sc.mapped[key] && !sc.kmapped[key] {
			return sp.bad(n, key, "switch %s: no field or also line of the scope before the switch maps the key", key)
		}
		sw := &seqSwitch{key: key, line: n, seen: map[string]*seqCase{}}
		add(&seqNode{op: seqSwitchOp, sw: sw})
		sp.push(&seqFrame{op: seqSwitchOp, line: n, sw: sw})
	case "case", "else":
		if top.op == seqCaseOp {
			if top.cas.isElse {
				return sp.bad(n, "", "%s after the else of the switch on line %d", kw, top.sw.line)
			}
			if top.afterRest {
				sp.stack[len(sp.stack)-2].restCase = true
			}
			sp.stack = sp.stack[:len(sp.stack)-1]
			top = sp.top()
		}
		if top.op != seqSwitchOp {
			return sp.bad(n, "", "%s outside a switch", kw)
		}
		sw := top.sw
		c := &seqCase{sw: sw, line: n, isElse: kw == "else", block: &seqNode{op: seqCaseOp, line: n}}
		if c.isElse {
			if len(sw.cases) == 0 {
				return sp.bad(n, "", "else before the first case of the switch on line %d", sw.line)
			}
			sw.els = c
		} else {
			if args[0] == "" {
				c.vals = []string{""}
			} else {
				vals, err := splitValueList(args[0])
				if err != nil {
					return sp.bad(n, "", "case: %v", err)
				}
				c.vals = vals
			}
			sw.cases = append(sw.cases, c)
			p.valueChecks = append(p.valueChecks, valueCheck{line: n, cas: c})
		}
		sp.push(&seqFrame{op: seqCaseOp, line: n, sw: sw, cas: c, nodes: &c.body})
	case "end":
		if err := count(0); err != nil {
			return err
		}
		if len(sp.stack) == 1 {
			sp.lateErr(sp.bad(n, "", "end with no open block"))
			return nil
		}
		if top.op == seqSwitchOp {
			return sp.bad(top.line, "", "the switch has no case")
		}
		if top.op == seqCaseOp {
			// The end closes the case and its switch.
			rest := top.afterRest || sp.stack[len(sp.stack)-2].restCase
			sp.stack = sp.stack[:len(sp.stack)-1]
			sp.stack = sp.stack[:len(sp.stack)-1]
			if rest {
				restEnded(sp.top())
			}
			return nil
		}
		if top.op == seqGroup && top.body.whens > 0 && len(top.body.kinds) == 0 {
			return sp.bad(top.line, "", "a when line needs a body with a kind line")
		}
		sp.stack = sp.stack[:len(sp.stack)-1]
		switch {
		case top.op == seqAlt:
			// The end of a choice closes its last alt and the choice (0.19).
			// A rest group in an alt ends the extent's other lines after
			// the choice, as one in a case does after its switch (0.21
			// ruling 39 with 0.20 ruling 40).
			rest := top.afterRest || sp.top().restCase
			sp.stack = sp.stack[:len(sp.stack)-1]
			if rest {
				restEnded(sp.top())
			}
		case top.op == seqGroup && top.group.seqMode == seqRest:
			// What follows a rest group, or a block holding one, in the
			// same extent is checked by wireLine (0.21 ruling 11). A length
			// block ends the extent; a group body is its items' own.
			restEnded(sp.top())
		case (top.op == seqIf || top.op == seqOpt || top.op == seqChain || top.op == seqExt) && top.afterRest:
			restEnded(sp.top())
		}
	}
	return nil
}

// hasToken reports whether toks holds t.
func hasToken(toks []string, t string) bool {
	for _, x := range toks {
		if x == t {
			return true
		}
	}
	return false
}

// asBans refuses, in each reading path, two `when … as` lines naming one key
// and a key named by `as` that a `field` or `also` line also maps (0.30
// rulings 9, 16, 21 and 33). A reading path is a body's common lines plus one
// of its kinds, every block of that scope included; a group body is a scope
// of its own.
func (sp *seqParser) asBans() error {
	for _, b := range sp.bodies {
		common := map[string]int{}
		for _, n := range b.common {
			if n.op != seqWhen || n.key == "" {
				continue
			}
			if prev, dup := common[n.key]; dup {
				return sp.bad(n.line, n.key, "when … as %s: the key is already bound by the when on line %d of the common lines", n.key, prev)
			}
			common[n.key] = n.line
		}
		cfields := map[string]int{}
		scopeFields(b.common, cfields)
		check := func(as map[string]int, fields map[string]int) error {
			// The earliest `as` line in conflict is reported.
			key, at := "", 0
			for k, ln := range as {
				if _, ok := fields[k]; ok && (at == 0 || ln < at) {
					key, at = k, ln
				}
			}
			if at != 0 {
				return sp.bad(at, key, "when … as %s: the key is also mapped by the field or also line on line %d of the same reading path", key, fields[key])
			}
			return nil
		}
		if len(b.kinds) == 0 {
			if err := check(common, cfields); err != nil {
				return err
			}
		}
		for _, k := range b.kinds {
			as := map[string]int{}
			for key, ln := range common {
				as[key] = ln
			}
			for _, w := range k.whens {
				if w.key == "" {
					continue
				}
				if prev, dup := as[w.key]; dup {
					return sp.bad(w.line, w.key, "when … as %s: the key is already bound by the when on line %d of the same reading path", w.key, prev)
				}
				as[w.key] = w.line
			}
			fields := map[string]int{}
			for key, ln := range cfields {
				fields[key] = ln
			}
			scopeFields(k.nodes, fields)
			if err := check(as, fields); err != nil {
				return err
			}
		}
	}
	return nil
}

// scopeFields records the keys the field and also lines of nodes map, with
// the line of each, in every block of the scope; a group body is not entered.
func scopeFields(nodes []*seqNode, out map[string]int) {
	put := func(key string, line int) {
		if _, ok := out[key]; !ok {
			out[key] = line
		}
	}
	for _, n := range nodes {
		switch n.op {
		case seqField:
			put(n.f.Key, n.f.Line)
			for _, a := range n.f.also {
				put(a.Key, a.Line)
			}
		case seqGroup:
		case seqSwitchOp:
			for _, c := range n.sw.cases {
				scopeFields(c.body, out)
			}
			if n.sw.els != nil {
				scopeFields(n.sw.els.body, out)
			}
		default:
			scopeFields(n.body, out)
		}
	}
}

// finish runs the checks that need the whole file: every block closed, and
// no `when` in a body with no kind.
func (sp *seqParser) finish() error {
	if len(sp.stack) > 1 {
		top := sp.top()
		return sp.bad(top.line, "", "the block opened on line %d has no end", top.line)
	}
	if b := sp.p.sbody; b.whens > 0 && len(b.kinds) == 0 {
		return sp.bad(0, "", "a when line needs a pack with a kind line")
	}
	// At most one `inner` line lies on a reading path (0.34, ruling 33 of
	// 0.21): the common lines and each kind.
	if b := sp.p.sbody; sp.p.innerLine != 0 {
		common := innerLines(b.common)
		paths := []int{common}
		if len(b.kinds) > 0 {
			paths = paths[:0]
			for _, k := range b.kinds {
				paths = append(paths, common+innerLines(k.nodes))
			}
		}
		for _, c := range paths {
			if c > 1 {
				return sp.bad(sp.p.innerLine, "", "a reading path holds %d inner lines, and holds at most one", c)
			}
		}
	}
	// Each reading path through a count's range holds exactly one group
	// that references it (0.21 rulings 2 and 33).
	for _, cd := range sp.counts {
		lo, hi := countRefs((*cd.list)[cd.idx+1:], cd)
		paths := [][2]int{{lo, hi}}
		if cd.body != nil && len(cd.body.kinds) > 0 {
			paths = paths[:0]
			for _, k := range cd.body.kinds {
				a, b := countRefs(k.nodes, cd)
				paths = append(paths, [2]int{lo + a, hi + b})
			}
		}
		for _, pr := range paths {
			if pr[0] != 1 || pr[1] != 1 {
				return sp.bad(cd.line, "", "count %s: a reading path holds %d to %d groups that reference it, and must hold exactly one", cd.name, pr[0], pr[1])
			}
		}
	}
	return nil
}

// innerLines counts the `inner` lines along the lines of a body, through
// length blocks; a group body is another body.
func innerLines(nodes []*seqNode) int {
	c := 0
	for _, n := range nodes {
		switch n.op {
		case seqInner:
			c++
		case seqGroup:
		case seqSwitchOp:
			for _, cs := range n.sw.cases {
				c += innerLines(cs.body)
			}
			if n.sw.els != nil {
				c += innerLines(n.sw.els.body)
			}
		default:
			c += innerLines(n.body)
		}
	}
	return c
}

// countRefs returns the fewest and the most groups that reference a count
// along the reading paths through lines. Paths split only at switch cases
// (0.21 ruling 33); a group body is not entered (ruling 9).
func countRefs(nodes []*seqNode, cd *seqCountDef) (lo, hi int) {
	for _, n := range nodes {
		switch n.op {
		case seqGroup:
			if n.g.cnt == cd {
				lo++
				hi++
			}
		case seqSwitchOp:
			cases := append([]*seqCase(nil), n.sw.cases...)
			if n.sw.els != nil {
				cases = append(cases, n.sw.els)
			}
			cl, ch := -1, 0
			for _, c := range cases {
				a, b := countRefs(c.body, cd)
				if cl < 0 || a < cl {
					cl = a
				}
				if b > ch {
					ch = b
				}
			}
			if cl > 0 {
				lo += cl
			}
			hi += ch
		default:
			a, b := countRefs(n.body, cd)
			lo += a
			hi += b
		}
	}
	return lo, hi
}

// parsePlus reads the `plus` value of a count line: an optional '-' then
// digits, leading zeros allowed, within signed 64 bits (0.21 ruling 16).
func parsePlus(s string) (int64, bool) {
	if !isDigits(strings.TrimPrefix(s, "-")) {
		return 0, false
	}
	v, err := strconv.ParseInt(s, 10, 64)
	return v, err == nil
}

// bind indexes each body once the pack has loaded: the defaults in scope of
// each kind and the lines an encode writes for it.
func (sp *seqParser) bind() {
	for _, b := range sp.bodies {
		b.defs = map[string]*Default{}
		for _, d := range b.defaults {
			b.defs[d.Key] = d
		}
		for _, k := range b.kinds {
			k.defs = map[string]*Default{}
			for _, d := range b.defaults {
				k.defs[d.Key] = d
			}
			for _, d := range k.defaults {
				k.defs[d.Key] = d
			}
			k.all = append(append(append([]*seqNode(nil), b.common...), k.whens...), k.nodes...)
		}
	}
}
