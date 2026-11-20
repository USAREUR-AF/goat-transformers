package goatxf

import (
	"encoding/hex"
	"fmt"
	"math/bits"
	"strconv"
	"strings"
)

// Sequential binary layouts (spec/engine-spec.md, "Version 0.8: sequential
// binary layouts"): a bits pack with `layout sequential` describes a message
// as lines read in order from a cursor. A locator is a bit length.

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

// selectCase returns the case a decoded value selects: the first case that
// lists its canonical text, else the `else`; nil when neither (no-kind). An
// absent key selects the `else` (0.20).
func (sw *seqSwitch) selectCase(vals map[string]Value) *seqCase {
	if v, ok := vals[sw.key]; ok {
		s := v.String()
		for _, c := range sw.cases {
			if c.canon[s] {
				return c
			}
		}
	}
	return sw.els
}

// inRanges reports whether u is one of the values or lies in one of the
// ranges of a `when` list.
func inRanges(rs []numRange, u uint64) bool {
	for _, r := range rs {
		if u >= r.lo && u <= r.hi {
			return true
		}
	}
	return false
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
// order.
func (b *seqBody) modelKeys(add func(string), prefix string) {
	var walk func(nodes []*seqNode)
	walk = func(nodes []*seqNode) {
		for _, n := range nodes {
			switch n.op {
			case seqField:
				add(prefix + n.f.Key)
				for _, a := range n.f.also {
					add(prefix + a.Key)
				}
			case seqGroup:
				add(prefix + n.g.List + "[]")
				n.g.sbody.modelKeys(add, prefix+n.g.List+"[].")
			case seqSwitchOp:
				for _, c := range n.sw.cases {
					walk(c.body)
				}
				if n.sw.els != nil {
					walk(n.sw.els.body)
				}
			default:
				walk(n.body)
			}
		}
	}
	walk(b.common)
	for _, k := range b.kinds {
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

// inGroup reports whether a group block is open.
func (sp *seqParser) inGroup() bool {
	for _, f := range sp.stack {
		if f.op == seqGroup {
			return true
		}
	}
	return false
}

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
	case "field", "const", "pad", "align", "presence", "opt", "fx", "length", "group", "count", "ext":
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
		top.kcnts, top.kafterRest = map[string]*seqCountDef{}, false
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

// ---- decode ----

// seqReader reads a sequential message from a cursor.
type seqReader struct {
	d     *decodeState
	p     *Pack
	data  []byte
	pos   int
	limit int  // the first bit the lines may not read
	ext   bool // inside a `length` extent: a line at or after limit reads as absent
	// extBits is set when the innermost extent is counted in bits (a
	// `length … bits` block): a rest item needs 1 bit there, not 8 (0.21).
	extBits bool
	// cnts holds what each count line last read (0.21).
	cnts map[*seqCountDef]*seqCountRead
	pres map[*seqPresenceDef][]bool
	read map[*seqCase]bool // the cases and else bodies read (0.20 ruling 21)
	// pending holds the presence bits that are 1 and that only an `if`
	// inside a case names: each is checked once the message is read.
	pending []seqPendingBit
}

// seqCountRead is what a count line read: the number of items, unless the
// line lay at or past the end of a length extent (ok false). huge is set when
// the value minus `plus` exceeds 64 bits.
type seqCountRead struct {
	ok    bool
	items uint64
	huge  bool
}

type seqPendingBit struct {
	p   *seqPresenceDef
	bit int
}

func (r *seqReader) malformed(format string, a ...any) error {
	return &Error{Kind: ErrMalformedWire, Format: r.p.Format, Detail: fmt.Sprintf(format, a...)}
}

// take reserves n bits at the cursor and returns where they start. ok is
// false when the line stands at or after the end of a `length` extent and so
// reads as absent (0.8 ruling 7); a line that runs past the end is
// malformed-wire.
func (r *seqReader) take(n int, what string) (start int, ok bool, err error) {
	if r.pos+n <= r.limit {
		start = r.pos
		r.pos += n
		return start, true, nil
	}
	if r.ext && r.pos >= r.limit {
		return 0, false, nil
	}
	if r.ext {
		return 0, false, r.malformed("%s needs %d bit(s) at bit %d and its length extent ends at bit %d", what, n, r.pos, r.limit)
	}
	return 0, false, r.malformed("%s needs %d bit(s) at bit %d and the message has %d", what, n, r.pos, r.limit)
}

// beyond reports whether the cursor stands at or after the end of a `length`
// extent.
func (r *seqReader) beyond() bool { return r.ext && r.pos >= r.limit }

func decodeSeq(d *decodeState, data []byte, nbits int) error {
	p := d.pack
	// limit is the bits the input carries: under six-bit armor not a whole
	// number of bytes (0.14).
	r := &seqReader{d: d, p: p, data: data, limit: nbits, pres: map[*seqPresenceDef][]bool{}, read: map[*seqCase]bool{}, cnts: map[*seqCountDef]*seqCountRead{}}
	k, err := r.body(p.sbody)
	if err != nil {
		return err
	}
	// A bit named only inside cases counts when one of those cases was read
	// (0.20 ruling 21 with rulings 1 and 17 of 0.8).
	for _, pb := range r.pending {
		counted := false
		for _, c := range pb.p.caseNamed[pb.bit] {
			if r.read[c] {
				counted = true
				break
			}
		}
		if !counted {
			return r.malformed("presence bit %s.%d is 1 and no if block of the lines read names it", pb.p.name, pb.bit)
		}
	}
	if k != nil {
		d.ent.Kind = EntityKind{Format: p.Format, Name: k.name}
	}
	return nil
}

// body reads one message or one item: the common lines, then the lines of
// the first kind whose `when` lines all hold where the common lines ended.
func (r *seqReader) body(b *seqBody) (*seqKind, error) {
	if err := r.nodes(b.common); err != nil {
		return nil, err
	}
	if len(b.kinds) == 0 {
		return nil, nil
	}
	for _, k := range b.kinds {
		pos, holds := r.pos, true
		for _, w := range k.whens {
			if pos+w.n > r.limit || !inRanges(w.rng, getBits(r.data, pos, w.n, r.p.msb)) {
				holds = false
				break
			}
			pos += w.n
		}
		if holds {
			r.pos = pos
			return k, r.nodes(k.nodes)
		}
	}
	return nil, &Error{Kind: ErrNoKind, Format: r.p.Format, Detail: fmt.Sprintf("what stands at bit %d matches no kind", r.pos)}
}

func (r *seqReader) nodes(list []*seqNode) error {
	for _, n := range list {
		if err := r.node(n); err != nil {
			return err
		}
	}
	return nil
}

func (r *seqReader) node(n *seqNode) error {
	p, d := r.p, r.d
	switch n.op {
	case seqField:
		f := n.f
		if f.uper != nil {
			return r.uperField(f)
		}
		at, ok, err := r.take(f.loc.blen, "field "+f.Key)
		if err != nil || !ok {
			return err
		}
		// A sentinel leaves the key of the line, and those of its `also`
		// lines, absent.
		v, absent, err := seqFieldDecode(p, f, r.data, at)
		if absent {
			return nil
		}
		if err != nil {
			d.fail(f, err.Error())
			return nil
		}
		d.store(f, v)
		for _, a := range f.also {
			d.store(a, v)
		}
	case seqConst:
		_, _, err := r.take(n.n, "const")
		return err
	case seqPad:
		_, _, err := r.take(n.n, "pad")
		return err
	case seqAlign:
		if r.beyond() {
			return nil
		}
		if rem := r.pos % n.n; rem != 0 {
			r.pos += n.n - rem
			if r.pos > r.limit {
				r.pos = r.limit
			}
		}
	case seqWhen:
		// A common when: it must hold for any message of the format.
		at, ok, err := r.take(n.n, "when")
		if err != nil || !ok || !inRanges(n.rng, getBits(r.data, at, n.n, p.msb)) {
			return &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("the message does not hold %d at the common when on line %d", n.num, n.line)}
		}
	case seqPresence:
		return r.presence(n.pres)
	case seqIf:
		for _, c := range n.conds {
			bits := r.pres[c.p]
			if (c.bit < len(bits) && bits[c.bit]) == c.neg {
				return nil
			}
		}
		return r.nodes(n.body)
	case seqOpt:
		at, ok, err := r.take(1, "opt")
		if err != nil || !ok {
			return err
		}
		if bitAt(r.data, at, p.msb) == 1 {
			return r.nodes(n.body)
		}
	case seqChain:
		for i, c := range n.body {
			if c.op != seqFx {
				if err := r.node(c); err != nil {
					return err
				}
				continue
			}
			at, ok, err := r.take(1, "fx")
			if err != nil {
				return err
			}
			if !ok || bitAt(r.data, at, p.msb) == 0 {
				break
			}
			// A chain that ends with an fx line whose bit is 1 holds a part
			// the pack does not describe (0.8 ruling 3).
			if i == len(n.body)-1 {
				return r.malformed("the last fx bit of the chain on line %d is 1", n.line)
			}
		}
	case seqLength:
		at, ok, err := r.take(n.n, "length")
		if err != nil || !ok {
			return err
		}
		size, err := r.stated(at, n)
		if err != nil {
			return err
		}
		if !n.bits {
			size *= 8
		}
		if size > int64(r.limit-r.pos) {
			return r.malformed("the length block on line %d states %d bit(s) at bit %d and %d are left", n.line, size, r.pos, r.limit-r.pos)
		}
		end := r.pos + int(size)
		limit, ext, extBits := r.limit, r.ext, r.extBits
		r.limit, r.ext, r.extBits = end, true, n.bits
		err = r.nodes(n.body)
		r.limit, r.ext, r.extBits = limit, ext, extBits
		if err != nil {
			return err
		}
		// Content of the extent no line reads is skipped.
		r.pos = end
	case seqWhole:
		at, ok, err := r.take(n.n, "length")
		if err != nil || !ok {
			return err
		}
		size, err := r.stated(at, n)
		if err != nil {
			return err
		}
		if size > int64(r.limit/8) {
			return r.malformed("the message states a length of %d byte(s) and the input has %d", size, r.limit/8)
		}
		if int(size)*8 < r.pos {
			return r.malformed("the message states a length of %d byte(s) and %d bit(s) were already read", size, r.pos)
		}
		// Input beyond the stated length is ignored.
		r.limit = int(size) * 8
	case seqGroup:
		return r.group(n.g)
	case seqExt:
		return r.extBlock(n)
	case seqChoice:
		return r.choice(n)
	case seqCountOp:
		// A count line at or past the end of a length extent leaves its
		// group absent; a value below `plus` is malformed-wire here (0.21).
		cd := n.cnt
		at, ok, err := r.take(cd.n, "count "+cd.name)
		if err != nil {
			return err
		}
		if !ok {
			r.cnts[cd] = &seqCountRead{}
			return nil
		}
		raw := getBits(r.data, at, cd.n, p.msb)
		st := &seqCountRead{ok: true}
		if cd.plus >= 0 {
			if raw < uint64(cd.plus) {
				return r.malformed("count %s on line %d holds %d, below its plus of %d", cd.name, cd.line, raw, cd.plus)
			}
			st.items = raw - uint64(cd.plus)
		} else {
			var carry uint64
			st.items, carry = bits.Add64(raw, uint64(-(cd.plus+1))+1, 0)
			st.huge = carry != 0
		}
		r.cnts[cd] = st
	case seqSwitchOp:
		// The key's decoded value when the cursor reaches the switch selects
		// the case (0.20).
		// A key whose line failed its transform fails the decode (0.20
		// ruling 35).
		if _, ok := d.rec.Fields[n.sw.key]; !ok {
			for i, fe := range d.failed {
				if d.failedKey[i] == n.sw.key && d.failedIn[i] == d.rec {
					return fe
				}
			}
		}
		c := n.sw.selectCase(d.rec.Fields)
		if c == nil {
			return &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("the switch on line %d: the value of %s is in no case and there is no else", n.sw.line, n.sw.key)}
		}
		r.read[c] = true
		return r.nodes(c.body)
	}
	return nil
}

// seqFieldDecode reads the bits of a field line at a bit of data as a decode
// does: absent when they hold a sentinel, else the transform's value.
func seqFieldDecode(p *Pack, f *Field, data []byte, at int) (v Value, absent bool, err error) {
	if f.bitsSentinel(data, at, p.msb) {
		return Value{}, true, nil
	}
	if f.btf.sixbit {
		v = decodeSixbit(data, f, at, p.msb)
	} else if f.btf.decodeAt != nil {
		v, err = f.btf.decodeAt(data, at, f.loc.blen, p.msb)
	} else if f.btf.ascii {
		v, err = decodeASCII(data, f, at, p.msb)
	} else {
		raw := getBits(data, at, f.loc.blen, p.msb)
		if f.Swap {
			raw = swapBytes(raw, f.loc.blen/8)
		}
		v, err = f.btf.decode(raw, f.loc.blen)
	}
	return v, false, err
}

// stated reads a length field and takes away what it counts beyond the
// length; a result below zero is malformed-wire.
func (r *seqReader) stated(at int, n *seqNode) (int64, error) {
	raw := getBits(r.data, at, n.n, r.p.msb)
	size := int64(raw) - n.plus
	if raw > 1<<40 || size < 0 {
		return 0, r.malformed("the length field on line %d holds %d, which states no length (plus %d)", n.line, raw, n.plus)
	}
	return size, nil
}

// presence reads the bits of a `presence` line, numbered from 1 in reading
// order. A bit that is 1 and that no `if` block names is malformed-wire
// (0.8 ruling 1).
func (r *seqReader) presence(pr *seqPresenceDef) error {
	bits := []bool{false}
	if pr.fx {
		for first := true; ; first = false {
			at, ok, err := r.take(8, "presence "+pr.name)
			if err != nil {
				return err
			}
			if !ok {
				// At the end of a length extent the presence reads as 0; a
				// continuation octet there is malformed-wire (0.8 ruling 21).
				if !first {
					return r.malformed("presence %s: a continuation octet is stated at bit %d, the end of its length extent", pr.name, r.pos)
				}
				break
			}
			for k := 0; k < 7; k++ {
				bits = append(bits, bitAt(r.data, at+k, r.p.msb) == 1)
			}
			if bitAt(r.data, at+7, r.p.msb) == 0 {
				break
			}
		}
	} else {
		at, ok, err := r.take(pr.n, "presence "+pr.name)
		if err != nil {
			return err
		}
		for k := 0; k < pr.n; k++ {
			bits = append(bits, ok && bitAt(r.data, at+k, r.p.msb) == 1)
		}
	}
	for i := 1; i < len(bits); i++ {
		if bits[i] && !pr.named[i] {
			if len(pr.caseNamed[i]) == 0 {
				return r.malformed("presence bit %s.%d is 1 and no if block names it", pr.name, i)
			}
			r.pending = append(r.pending, seqPendingBit{pr, i})
		}
	}
	r.pres[pr] = bits
	return nil
}

// group reads the items of a sequential group.
func (r *seqReader) group(g *Group) error {
	p, d := r.p, r.d
	// A group at or after the end of a length extent gives an absent list;
	// a rest group there is present and empty (0.21 ruling 3).
	if r.beyond() && g.seqMode != seqRest {
		return nil
	}
	d.replacing(g.List)
	items := []*Item{}
	item := func() error {
		it, err := d.item(func() error {
			k, err := r.body(g.sbody)
			if k != nil {
				d.rec.Kind = EntityKind{Format: p.Format, Name: k.name}
			}
			return err
		})
		if err != nil {
			return err
		}
		items = append(items, it)
		return nil
	}
	// bit reads one indicator bit; at the end of an extent it reads as 0.
	bit := func() (bool, error) {
		at, ok, err := r.take(1, "list "+g.List)
		if err != nil || !ok {
			return false, err
		}
		return bitAt(r.data, at, p.msb) == 1, nil
	}
	switch g.seqMode {
	case seqCount, seqSize, seqSizeUnc:
		var count uint64
		if g.seqMode == seqCount {
			at, _, err := r.take(g.countBits, "the count of list "+g.List)
			if err != nil {
				return err
			}
			count = getBits(r.data, at, g.countBits, p.msb)
		} else {
			c, err := r.sizeCount(g)
			if err != nil {
				return err
			}
			count = c
		}
		// A count larger than the bits left is refused before any item is
		// read (0.8 ruling 14).
		if count > uint64(r.limit-r.pos) {
			return r.malformed("list %s: a count of %d and %d bit(s) left", g.List, count, r.limit-r.pos)
		}
		if err := d.room(g.List, count); err != nil {
			return err
		}
		for i := uint64(0); i < count; i++ {
			if err := item(); err != nil {
				return err
			}
		}
	case seqCountRef:
		// The count was read at its own line; the bits left are counted at
		// the group (0.21 ruling 20).
		st := r.cnts[g.cnt]
		if st == nil || !st.ok {
			return nil
		}
		if st.huge || st.items > uint64(r.limit-r.pos) {
			return r.malformed("list %s: count %s states more items than the %d bit(s) left", g.List, g.cnt.name, r.limit-r.pos)
		}
		for i := uint64(0); i < st.items; i++ {
			if err := item(); err != nil {
				return err
			}
		}
	case seqRest:
		// Items while bits remain in the extent; fewer are padding (0.21).
		least := 8
		if r.extBits {
			least = 1
		}
		for r.limit-r.pos >= least {
			start := r.pos
			if err := item(); err != nil {
				return err
			}
			if r.pos == start {
				return r.malformed("list %s: an item of the rest group reads no bits", g.List)
			}
		}
		r.pos = r.limit
	case seqLast:
		// The first indicator at the extent end gives an absent list (above);
		// a later one there is malformed-wire (0.21 ruling 13).
		for {
			at, ok, err := r.take(1, "list "+g.List)
			if err != nil {
				return err
			}
			if !ok {
				return r.malformed("list %s: the last-item bit of an item after the first starts at bit %d, the end of its length extent", g.List, r.pos)
			}
			last := bitAt(r.data, at, p.msb) == 1
			if err := item(); err != nil {
				return err
			}
			if last {
				break
			}
		}
	case seqWhile:
		for {
			more, err := bit()
			if err != nil {
				return err
			}
			if !more {
				break
			}
			if err := item(); err != nil {
				return err
			}
		}
	case seqMore:
		for {
			more, err := bit()
			if err != nil {
				return err
			}
			if err := item(); err != nil {
				return err
			}
			if !more {
				break
			}
		}
	case seqFxMode:
		for {
			if err := item(); err != nil {
				return err
			}
			more, err := bit()
			if err != nil {
				return err
			}
			if !more {
				break
			}
		}
	}
	d.rec.SetList(g.List, items)
	return nil
}

// ---- encode ----

// seqScope is what the lines being written read: the entity's own keys and
// lists or one item, and the defaults in scope.
type seqScope struct {
	rec  *Item
	defs map[string]*Default
	uper bool // a UPER pack: no default counts as content (0.19 ruling 19)
	// vals is what a decode of the lines written so far in the scope would
	// hold, each key its first value: a switch selects from it (0.20).
	vals map[string]Value
	// bad holds the keys a written line gave that would not read back: the
	// bits fail the transform or the table on decode (0.20 ruling 31).
	bad map[string]bool
}

// withVals returns the scope with a copy of its decoded values, for a
// simulation that must not change them.
func (sc seqScope) withVals() seqScope {
	vals := make(map[string]Value, len(sc.vals))
	for k, v := range sc.vals {
		vals[k] = v
	}
	sc.vals = vals
	sc.bad = map[string]bool{}
	return sc
}

// newScope is the scope of a message or an item with nothing written yet.
func newScope(p *Pack, rec *Item, defs map[string]*Default) seqScope {
	return seqScope{rec: rec, defs: defs, uper: p.uper, vals: map[string]Value{}, bad: map[string]bool{}}
}

// inCase returns the scope of the lines of a case: its defaults over those
// in scope, the innermost winning (0.20 rulings 7 and 22).
func (sc seqScope) inCase(c *seqCase) seqScope {
	if len(c.defaults) == 0 {
		return sc
	}
	defs := make(map[string]*Default, len(sc.defs)+len(c.defaults))
	for k, d := range sc.defs {
		defs[k] = d
	}
	for _, d := range c.defaults {
		defs[d.Key] = d
	}
	sc.defs = defs
	return sc
}

// storeBack puts a value read back from written bits in vals as a decode
// stores it: through the line's value table and the typemap, the first value
// of a key staying.
func storeBack(p *Pack, sc seqScope, f *Field, v Value) {
	vals := sc.vals
	if _, done := vals[f.Key]; done {
		return
	}
	if f.table != nil {
		mv, err := f.viaDecode(v)
		if err != nil {
			sc.bad[f.Key] = true
			return
		}
		v = mv
	}
	if f.Key == "type" && p.TypeMapped() && v.Kind == KindString {
		if cot, ok := p.nativeToCot[v.S]; ok {
			v.S = cot
		}
	}
	vals[f.Key] = v
}

// readBack reads the bits a field line wrote at a bit of data as a decode
// would, and records the keys of the line and of its `also` lines in the
// scope's decoded values (0.20, Encode).
func readBack(p *Pack, f *Field, sc seqScope, data []byte, at int) {
	v, absent, err := seqFieldDecode(p, f, data, at)
	if absent {
		return
	}
	if err != nil {
		sc.bad[f.Key] = true
		for _, a := range f.also {
			sc.bad[a.Key] = true
		}
		return
	}
	storeBack(p, sc, f, v)
	for _, a := range f.also {
		storeBack(p, sc, a, v)
	}
}

// fieldBits returns the bits a field line writes, from bit 0 of a scratch
// buffer; nil when the value cannot be written.
func (w *seqWriter) fieldBits(f *Field, sc seqScope) []byte {
	buf := make([]byte, (f.loc.blen+7)/8+1)
	v, from, ok, err := seqFieldValue(w.p, f, sc)
	if err != nil {
		return nil
	}
	if !ok {
		if f.absent != nil && !f.suppressed(sc.rec) {
			putBits(buf, 0, f.loc.blen, f.sentinelBits(), w.p.msb)
		}
		return buf
	}
	if putBitsField(w.p, from, v, buf, 0) != nil {
		return nil
	}
	return buf
}

// seqWriter writes a sequential message at a cursor.
type seqWriter struct {
	p      *Pack
	buf    *bitBuf
	pos    int
	pres   map[*seqPresenceDef][]bool
	wholes []seqWholeAt
	// Settling encode (0.20 rulings 33, 34, 37): the presence, opt and fx
	// bits are computed from a prediction of the case each switch selects.
	// forced holds the cases a previous pass found the switches to select;
	// predicted the cases the prediction used; actual the cases the encode
	// selected from the bits written.
	forced    map[seqSwitchAt]*seqCase
	predicted []seqPrediction
	actual    map[seqSwitchAt]*seqCase
	// counts holds each count line written, in order; cntAt the last one
	// written of each count line, which its group fills in (0.21).
	counts []*seqCountAt
	cntAt  map[*seqCountDef]*seqCountAt
	// exts holds the extents open at the cursor: the message, then each
	// length block (0.21).
	exts []*seqExtent
}

// seqCountAt is one count field written: where it is and the number of items
// its group wrote.
type seqCountAt struct {
	cd    *seqCountDef
	at    int
	items int
}

// seqExtent is one extent while it is written: where it starts, whether it
// is counted in bits, and where each item of a rest group in it starts.
type seqExtent struct {
	start int
	bits  bool
	items []int
	// reached is set when a rest group of the extent is written.
	reached bool
}

// fillCounts writes each count: its group's items plus `plus`, checked once
// the message is laid out (0.21 ruling 30).
func (w *seqWriter) fillCounts() error {
	for _, c := range w.counts {
		v, ok := countValue(c.items, c.cd.plus)
		if !ok || (c.cd.n < 64 && v>>uint(c.cd.n) != 0) {
			return w.fail("count %s on line %d: %d item(s) plus %d do not fit its %d-bit field", c.cd.name, c.cd.line, c.items, c.cd.plus, c.cd.n)
		}
		w.put(c.at, c.cd.n, v)
	}
	return nil
}

// closeExtent checks, once an extent is laid out and padded, that each rest
// item in it starts with enough bits left for a decode to read it: 8 before
// the byte-padded end of a byte-counted extent (0.21 rulings 4, 21 and 34).
func (w *seqWriter) closeExtent() error {
	e := w.exts[len(w.exts)-1]
	w.exts = w.exts[:len(w.exts)-1]
	end, least := w.pos, 1
	// The message stays counted in bytes, under six-bit armor too (0.21
	// ruling 43).
	if !e.bits {
		least = 8
		end = e.start + (w.pos-e.start+7)/8*8
	}
	for _, at := range e.items {
		if end-at < least {
			return w.fail("an item of a rest group starts at bit %d with %d bit(s) left before the end of its extent at bit %d; the output would not decode it", at, end-at, end)
		}
	}
	return nil
}

// seqSwitchAt is one evaluation of a switch: the switch and the message or
// item it is written for.
type seqSwitchAt struct {
	sw  *seqSwitch
	rec *Item
}

type seqPrediction struct {
	at seqSwitchAt
	c  *seqCase
}

// predict returns the case a simulation takes for a switch: the case a
// previous pass found it to select, else the case decode would select from
// the values simulated so far.
func (w *seqWriter) predict(sw *seqSwitch, sc seqScope) *seqCase {
	at := seqSwitchAt{sw, sc.rec}
	c, ok := w.forced[at]
	if !ok {
		c = sw.selectCase(sc.vals)
	}
	w.predicted = append(w.predicted, seqPrediction{at, c})
	return c
}

// settled reports whether every prediction of a switch the encode reached
// is the case it selected.
func (w *seqWriter) settled() bool {
	for _, pr := range w.predicted {
		if c, ok := w.actual[pr.at]; ok && c != pr.c {
			return false
		}
	}
	return true
}

type seqWholeAt struct {
	n  *seqNode
	at int
}

func (w *seqWriter) alloc(n int) int {
	at := w.pos
	w.pos += n
	w.buf.need(w.pos)
	return at
}

func (w *seqWriter) put(at, n int, v uint64) { putBits(w.buf.data, at, n, v, w.p.msb) }

func (w *seqWriter) fail(format string, a ...any) error {
	return &Error{Kind: ErrTransformEncode, Format: w.p.Format, Detail: fmt.Sprintf(format, a...)}
}

// seqMaxPasses bounds the passes of a settling encode (0.20 ruling 33).
const seqMaxPasses = 16

func encodeSeq(p *Pack, ent *Entity) ([]byte, error) {
	rec := ent.item()
	nodes, defs, err := seqSelect(p, p.sbody, ent.Kind, rec, "the entity")
	if err != nil {
		return nil, err
	}
	forced := map[seqSwitchAt]*seqCase{}
	for pass := 1; ; pass++ {
		w := &seqWriter{p: p, buf: &bitBuf{}, pres: map[*seqPresenceDef][]bool{}, forced: forced, actual: map[seqSwitchAt]*seqCase{}}
		out, err := w.encodePass(nodes, newScope(p, rec, defs))
		// Errors of a pass whose prediction does not hold are not reported
		// (ruling 34): the next pass predicts the cases this one selected.
		if w.settled() {
			return out, err
		}
		if pass == seqMaxPasses {
			return nil, &Error{Kind: ErrTransformEncode, Format: p.Format, Detail: fmt.Sprintf("the cases predicted for the presence, opt and fx bits do not settle in %d passes", seqMaxPasses)}
		}
		next := map[seqSwitchAt]*seqCase{}
		for k, c := range forced {
			next[k] = c
		}
		for k, c := range w.actual {
			next[k] = c
		}
		forced = next
	}
}

// encodePass writes the message once, from the writer's prediction.
func (w *seqWriter) encodePass(nodes []*seqNode, sc seqScope) ([]byte, error) {
	w.cntAt = map[*seqCountDef]*seqCountAt{}
	w.exts = []*seqExtent{{}}
	if err := w.emit(nodes, sc, false); err != nil {
		return nil, err
	}
	// Armored text is the bits up to the cursor, not rounded to a byte
	// (spec 0.14); `length … whole` is refused under armor at load. Its
	// counts are filled and its rest items checked as for a message of
	// bytes (0.21 ruling 43).
	if w.p.sixbitArmor {
		if err := w.closeExtent(); err != nil {
			return nil, err
		}
		if err := w.fillCounts(); err != nil {
			return nil, err
		}
		w.buf.need(w.pos)
		return sixbitArmorText(w.buf.data, w.pos), nil
	}
	// A message is a whole number of bytes; the last bits are zero. A UPER
	// encoding of no bits is one octet 00 (spec 0.19).
	if rem := w.pos % 8; rem != 0 {
		w.alloc(8 - rem)
	}
	if w.p.uper && w.pos == 0 {
		w.alloc(8)
	}
	if err := w.closeExtent(); err != nil {
		return nil, err
	}
	if err := w.fillCounts(); err != nil {
		return nil, err
	}
	for _, wh := range w.wholes {
		if err := w.length(wh.n, wh.at, int64(w.pos/8)); err != nil {
			return nil, err
		}
	}
	return []byte(hex.EncodeToString(w.buf.data[:w.pos/8])), nil
}

// seqSelect picks the kind an encode writes for a message or an item, as for
// a message of 0.5: the kind it records for this format, else the first kind
// whose `requires` keys it all has. It returns the lines to write and the
// defaults in scope.
func seqSelect(p *Pack, b *seqBody, kind EntityKind, rec *Item, what string) ([]*seqNode, map[string]*Default, error) {
	if len(b.kinds) == 0 {
		return b.common, b.defs, nil
	}
	if kind.Format == p.Format {
		for _, k := range b.kinds {
			if k.name == kind.Name {
				return k.all, k.defs, nil
			}
		}
		// A message that names a kind the format does not have is no-kind
		// (0.5 ruling 24). An item that names a kind its group does not have
		// selects by `requires` (0.8 ruling 26).
		if b == p.sbody {
			return nil, nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("%s names kind %q, which the format does not have", what, kind.Name)}
		}
	}
	for _, k := range b.kinds {
		if reqHolds(k.requires, rec) {
			return k.all, k.defs, nil
		}
	}
	return nil, nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: what + " has the required keys of no kind"}
}

// fieldPresent reports whether a field line has something to write: a key of
// the line, or of its `also` lines, that is present or has a default in
// scope (0.8 ruling 2).
func fieldPresent(f *Field, sc seqScope) bool {
	has := func(key string) bool {
		if _, ok := sc.rec.Fields[key]; ok {
			return true
		}
		return !sc.uper && sc.defs[key] != nil
	}
	// A line suppressed by `with` is not content, its default included; its
	// `also` keys still are (0.18 rulings 1 and 5).
	if !f.suppressed(sc.rec) && has(f.Key) {
		return true
	}
	for _, a := range f.also {
		if has(a.Key) {
			return true
		}
	}
	return false
}

// seqSim walks lines as an encode would write them, without writing: it
// tells whether they have content (a present key, a default in scope or a
// non-empty list), records in the scope what a decode of the written lines
// would hold, so that a switch selects as decode would (0.20), and with a
// target collects the bits of that presence: a bit is 1 when an `if` that
// names it without `!`, among the lines walked, has content. Only the
// selected case of a switch is walked (0.20, rulings 1, 17 and 22 of 0.8).
type seqSim struct {
	w      *seqWriter
	target *seqPresenceDef
	bits   []bool
}

// content reports whether lines would write a present key or a non-empty
// list, the scope's decoded values left unchanged.
func (w *seqWriter) content(nodes []*seqNode, sc seqScope) bool {
	s := &seqSim{w: w}
	return s.walk(nodes, sc.withVals(), true)
}

func (s *seqSim) set(i int) {
	for len(s.bits) <= i {
		s.bits = append(s.bits, false)
	}
	s.bits[i] = true
}

// ifWritten reports whether an `if` block is written: its conditions on
// presences already written, on the bits of the target found so far, and on
// a presence not yet known as its block's content.
func (s *seqSim) ifWritten(n *seqNode, content bool) bool {
	for _, c := range n.conds {
		var bit bool
		switch bits, known := s.w.pres[c.p]; {
		case c.p == s.target:
			bit = c.bit < len(s.bits) && s.bits[c.bit]
		case known:
			bit = c.bit < len(bits) && bits[c.bit]
		default:
			bit = content && !c.neg
		}
		if bit == c.neg {
			return false
		}
	}
	return true
}

// walk walks lines; written tells whether the lines are written, so that
// their fields record decoded values. Without a target it stops at the first
// content.
func (s *seqSim) walk(nodes []*seqNode, sc seqScope, written bool) bool {
	content := false
	for _, n := range nodes {
		if content && s.target == nil {
			return true
		}
		switch n.op {
		case seqField:
			if fieldPresent(n.f, sc) {
				content = true
			}
			if written {
				if n.f.uper != nil {
					uperReadBack(s.w, n.f, sc)
				} else if buf := s.w.fieldBits(n.f, sc); buf != nil {
					readBack(s.w.p, n.f, sc, buf, 0)
				}
			}
		case seqGroup:
			items := sc.rec.Lists[n.g.List]
			if len(items) > 0 {
				content = true
			}
			if s.target == nil {
				continue
			}
			for _, it := range items {
				nodes, defs, err := seqSelect(s.w.p, n.g.sbody, it.Kind, it, "an item of list "+n.g.List)
				if err != nil {
					// The encode reports it when it reaches the group.
					continue
				}
				s.walk(nodes, newScope(s.w.p, it, defs), written)
			}
		case seqIf:
			body := s.w.content(n.body, sc)
			if body && s.target != nil {
				for _, c := range n.conds {
					if c.p == s.target && !c.neg {
						s.set(c.bit)
					}
				}
			}
			if body {
				content = true
			}
			s.walk(n.body, sc, written && s.ifWritten(n, body))
		case seqOpt:
			body := s.w.content(n.body, sc)
			if body {
				content = true
			}
			s.walk(n.body, sc, written && body)
		case seqChain:
			on := written
			for j, c := range n.body {
				if c.op == seqFx {
					// At an fx bit of 0 the chain ends.
					if on && !s.w.content(n.body[j+1:], sc) {
						on = false
					}
					continue
				}
				if s.walk([]*seqNode{c}, sc, on) {
					content = true
					if s.target == nil {
						return true
					}
				}
			}
		case seqLength:
			if s.walk(n.body, sc, written) {
				content = true
			}
		case seqExt:
			// Content is looked for inside ext, choice and alt blocks
			// (0.19 ruling 3); encode writes an ext block's lines.
			if s.walk(n.body, sc, written) {
				content = true
			}
		case seqChoice:
			// Encode writes the alt w.choice picks; with a target every alt
			// is walked for the bits it names, as before 0.20.
			alt := s.w.choiceAlt(n, sc)
			for _, a := range n.body {
				if a != alt && s.target == nil {
					continue
				}
				if s.walk(a.body, sc, written && a == alt) {
					content = true
				}
			}
		case seqSwitchOp:
			if c := s.w.predict(n.sw, sc); c != nil {
				if s.walk(c.body, sc.inCase(c), written) {
					content = true
				}
			}
		}
	}
	return content
}

// presenceBits computes the bits of a presence before it is written, over
// the lines that follow the presence line (0.8 rulings 4 and 12). A block
// inside a group item counts for every item.
func (w *seqWriter) presenceBits(pr *seqPresenceDef, rest []*seqNode, sc seqScope) []bool {
	s := &seqSim{w: w, target: pr, bits: make([]bool, pr.n+1)}
	s.walk(rest, sc.withVals(), true)
	return s.bits
}

// seqFieldValue returns the value a field line writes and the line it comes
// from: the value of the earliest of the line's keys that the entity has,
// else the default of the earliest key that has one (0.8 ruling 13); the
// `type` key mapped back to the native code; then the line's value table.
func seqFieldValue(p *Pack, f *Field, sc seqScope) (Value, *Field, bool, error) {
	// A line suppressed by `with` is no candidate; its `also` keys stay
	// candidates (0.18 ruling 5).
	var cands []*Field
	if !f.suppressed(sc.rec) {
		cands = append(cands, f)
	}
	cands = append(cands, f.also...)
	var from *Field
	var v Value
	for _, c := range cands {
		if x, ok := sc.rec.Fields[c.Key]; ok {
			from, v = c, x
			break
		}
	}
	if from == nil {
		for _, c := range cands {
			if d := sc.defs[c.Key]; d != nil {
				from, v = c, d.val
				break
			}
		}
	}
	if from == nil {
		return Value{}, nil, false, nil
	}
	if from.Key == "type" && p.TypeMapped() && v.Kind == KindString {
		if native, ok := p.cotToNative[v.S]; ok {
			v.S = native
		}
	}
	if from.table != nil {
		nv, err := from.viaEncode(v)
		if err != nil {
			return Value{}, nil, false, encodeErr(p, from, err)
		}
		v = nv
	}
	return v, from, true, nil
}

// emit writes lines at the cursor. chain is set for the lines of a chain,
// where an `fx` line is one bit.
func (w *seqWriter) emit(nodes []*seqNode, sc seqScope, chain bool) error {
	p := w.p
	for i, n := range nodes {
		switch n.op {
		case seqField:
			f := n.f
			if f.uper != nil {
				if err := w.uperField(f, sc); err != nil {
					return err
				}
				continue
			}
			v, from, ok, err := seqFieldValue(p, f, sc)
			if err != nil {
				return err
			}
			at := w.alloc(f.loc.blen)
			if !ok {
				// An absent key writes the sentinel in place of zero bits.
				// A line suppressed by `with` has no sentinel (0.18).
				if f.absent != nil && !f.suppressed(sc.rec) {
					w.put(at, f.loc.blen, f.sentinelBits())
				}
			} else if err := putBitsField(p, from, v, w.buf.data, at); err != nil {
				return err
			}
			// What a decode would read back from the bits (0.20).
			readBack(p, f, sc, w.buf.data, at)
		case seqConst, seqWhen:
			w.put(w.alloc(n.n), n.n, n.num)
		case seqPad:
			w.alloc(n.n)
		case seqAlign:
			if rem := w.pos % n.n; rem != 0 {
				w.alloc(n.n - rem)
			}
		case seqPresence:
			pr := n.pres
			bits := w.presenceBits(pr, nodes[i+1:], sc)
			w.pres[pr] = bits
			if !pr.fx {
				at := w.alloc(pr.n)
				for k := 1; k <= pr.n; k++ {
					if bits[k] {
						w.put(at+k-1, 1, 1)
					}
				}
				continue
			}
			// Trailing octets that are all zero are not written, and at
			// least one octet is.
			octets := 1
			for k := 1; k < len(bits); k++ {
				if bits[k] {
					octets = (k + 6) / 7
				}
			}
			for o := 0; o < octets; o++ {
				at := w.alloc(8)
				for k := 0; k < 7; k++ {
					if b := o*7 + k + 1; b < len(bits) && bits[b] {
						w.put(at+k, 1, 1)
					}
				}
				if o < octets-1 {
					w.put(at+7, 1, 1)
				}
			}
		case seqIf:
			written := true
			for _, c := range n.conds {
				bits := w.pres[c.p]
				if (c.bit < len(bits) && bits[c.bit]) == c.neg {
					written = false
					break
				}
			}
			if written {
				if err := w.emit(n.body, sc, false); err != nil {
					return err
				}
			}
		case seqOpt:
			at := w.alloc(1)
			if w.content(n.body, sc) {
				w.put(at, 1, 1)
				if err := w.emit(n.body, sc, false); err != nil {
					return err
				}
			}
		case seqChain:
			if err := w.emit(n.body, sc, true); err != nil {
				return err
			}
		case seqFx:
			// An fx bit is 1 when a line after it in the chain would write a
			// present key; at 0 the chain ends.
			at := w.alloc(1)
			if !chain || !w.content(nodes[i+1:], sc) {
				return nil
			}
			w.put(at, 1, 1)
		case seqLength:
			at := w.alloc(n.n)
			start := w.pos
			w.exts = append(w.exts, &seqExtent{start: start, bits: n.bits})
			if err := w.emit(n.body, sc, false); err != nil {
				return err
			}
			size := int64(w.pos - start)
			if !n.bits {
				// A block counted in bytes is padded to a whole byte.
				if rem := (w.pos - start) % 8; rem != 0 {
					w.alloc(8 - rem)
				}
				size = int64(w.pos-start) / 8
			}
			if err := w.closeExtent(); err != nil {
				return err
			}
			if err := w.length(n, at, size); err != nil {
				return err
			}
		case seqWhole:
			w.wholes = append(w.wholes, seqWholeAt{n: n, at: w.alloc(n.n)})
		case seqGroup:
			if err := w.group(n.g, sc); err != nil {
				return err
			}
		case seqExt:
			// Encode writes the extension bit 0 and the block.
			w.putU(1, 0)
			if err := w.emit(n.body, sc, false); err != nil {
				return err
			}
		case seqChoice:
			if err := w.choice(n, sc); err != nil {
				return err
			}
		case seqCountOp:
			// The value is written once the message is laid out; until its
			// group is reached it holds `plus` (0.21 rulings 22, 23 and 30).
			c := &seqCountAt{cd: n.cnt, at: w.alloc(n.cnt.n)}
			w.counts = append(w.counts, c)
			w.cntAt[n.cnt] = c
		case seqSwitchOp:
			// The case decode would select from the bits written (0.20).
			if _, ok := sc.vals[n.sw.key]; !ok && sc.bad[n.sw.key] {
				return &Error{Kind: ErrTransformEncode, Format: p.Format, Detail: fmt.Sprintf("the switch on line %d: the value written for %s does not read back, so the output would not decode", n.sw.line, n.sw.key)}
			}
			c := n.sw.selectCase(sc.vals)
			w.actual[seqSwitchAt{n.sw, sc.rec}] = c
			if c == nil {
				return &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("the switch on line %d: the value of %s written is in no case and there is no else", n.sw.line, n.sw.key)}
			}
			if err := w.emit(c.body, sc.inCase(c), false); err != nil {
				return err
			}
		}
	}
	return nil
}

// countValue is items + plus as an unsigned field value; ok is false when it
// is below 0 or above 2^64-1.
func countValue(items int, plus int64) (uint64, bool) {
	if plus >= 0 {
		v, carry := bits.Add64(uint64(items), uint64(plus), 0)
		return v, carry == 0
	}
	m := uint64(-(plus + 1)) + 1
	if uint64(items) < m {
		return 0, false
	}
	return uint64(items) - m, true
}

// length writes a length field: the size plus what the field counts beyond
// it.
func (w *seqWriter) length(n *seqNode, at int, size int64) error {
	v := size + n.plus
	if v < 0 || (n.n < 64 && uint64(v)>>uint(n.n) != 0) {
		return w.fail("the length %d (plus %d) of the block on line %d does not fit its %d-bit field", size, n.plus, n.line, n.n)
	}
	w.put(at, n.n, uint64(v))
	return nil
}

// group writes the items of a sequential group.
func (w *seqWriter) group(g *Group, sc seqScope) error {
	items := sc.rec.Lists[g.List]
	item := func(it *Item) error {
		nodes, defs, err := seqSelect(w.p, g.sbody, it.Kind, it, "an item of list "+g.List)
		if err != nil {
			return err
		}
		return w.emit(nodes, newScope(w.p, it, defs), false)
	}
	bit := func(one bool) {
		at := w.alloc(1)
		if one {
			w.put(at, 1, 1)
		}
	}
	switch g.seqMode {
	case seqSize, seqSizeUnc:
		items, err := w.sizeItems(g, sc)
		if err != nil {
			return err
		}
		for _, it := range items {
			if err := item(it); err != nil {
				return err
			}
		}
	case seqCountRef:
		if c := w.cntAt[g.cnt]; c != nil {
			c.items = len(items)
		}
		for _, it := range items {
			if err := item(it); err != nil {
				return err
			}
		}
	case seqRest:
		ext := w.exts[len(w.exts)-1]
		for i, it := range items {
			start := w.pos
			ext.reached = false
			if err := item(it); err != nil {
				return err
			}
			if w.pos == start {
				return w.fail("list %s: an item of the rest group writes no bits, so the output would not decode", g.List)
			}
			// An item whose lines reach a rest group of the same extent
			// takes the rest of it: only the last item may (0.21 rulings 10
			// and 27).
			if g.innerRest && ext.reached && i < len(items)-1 {
				return w.fail("list %s: item %d reaches a rest list that takes the rest of the extent, and %d item(s) follow it", g.List, i, len(items)-1-i)
			}
			ext.items = append(ext.items, start)
		}
		ext.reached = true
	case seqLast:
		// The list holds at least one item on the wire (0.21).
		if len(items) == 0 {
			return w.fail("list %s is absent or empty and its last group holds at least one item", g.List)
		}
		for i, it := range items {
			bit(i == len(items)-1)
			if err := item(it); err != nil {
				return err
			}
		}
	case seqCount:
		// An absent list writes a count of 0 (0.7 ruling 14).
		if g.countBits < 64 && uint64(len(items))>>uint(g.countBits) != 0 {
			return w.fail("list %s: %d item(s) do not fit the %d-bit count", g.List, len(items), g.countBits)
		}
		w.put(w.alloc(g.countBits), g.countBits, uint64(len(items)))
		for _, it := range items {
			if err := item(it); err != nil {
				return err
			}
		}
	case seqWhile:
		for _, it := range items {
			bit(true)
			if err := item(it); err != nil {
				return err
			}
		}
		bit(false)
	case seqMore, seqFxMode:
		// These forms hold at least one item on the wire.
		if len(items) == 0 {
			return w.fail("list %s is absent or empty and its group holds at least one item", g.List)
		}
		for i, it := range items {
			if g.seqMode == seqMore {
				bit(i < len(items)-1)
			}
			if err := item(it); err != nil {
				return err
			}
			if g.seqMode == seqFxMode {
				bit(i < len(items)-1)
			}
		}
	}
	return nil
}
