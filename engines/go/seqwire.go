package goatxf

import (
	"encoding/hex"
	"fmt"
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
	seqMsg // the frame of a message body; not a line
)

// How the items of a sequential group are delimited.
const (
	seqCount  = iota + 1 // a count field, then that many items
	seqWhile             // one bit before each item: 1 = an item follows, 0 = the list ends
	seqMore              // one bit before each item: 1 = another item follows this one
	seqFxMode            // one bit after each item: 1 = another item follows
)

// seqStructural names the directives the sequential parser reads; the others
// (format, wire, map, …) are read as in a fixed-layout pack.
var seqStructural = map[string]bool{
	"field": true, "const": true, "when": true, "pad": true, "align": true, "presence": true,
	"if": true, "opt": true, "chain": true, "fx": true, "length": true, "also": true,
	"group": true, "end": true, "kind": true, "requires": true, "default": true,
}

// seqOnly names the directives valid only in a sequential pack.
var seqOnly = map[string]bool{
	"pad": true, "align": true, "presence": true, "if": true, "opt": true,
	"chain": true, "fx": true, "length": true, "also": true,
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
	named map[int]bool // the bits some `if` block names, with or without `!`
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
	bits  bool  // length: the block is counted in bits
	plus  int64 // length, whole: what the field holds beyond the length
}

// seqKind is one kind of a body: of the message, or of the items of a group.
type seqKind struct {
	name     string
	line     int
	whens    []*seqNode
	requires []string
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
	lists     map[string]int             // message and group frames: the lists the common lines map
	klists    map[string]int             // the lists the kind being read maps
	last      *Field                     // the field line directly before, for `also`
	group     *Group
}

// seqParser reads the structural lines of a sequential pack.
type seqParser struct {
	p      *Pack
	perr   func(kind ErrorKind, line int, loc, format string, a ...any) error
	stack  []*seqFrame
	bodies []*seqBody
}

func (sp *seqParser) init() {
	body := &seqBody{}
	sp.p.sbody = body
	sp.bodies = append(sp.bodies, body)
	sp.stack = []*seqFrame{{op: seqMsg, body: body, nodes: &body.common, kindNames: map[string]int{}, pres: map[string]*seqPresenceDef{}, lists: map[string]int{}}}
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
	n, err := strconv.Atoi(text)
	if err != nil || n < 1 || n > max {
		return 0, sp.bad(line, text, "%s takes a bit length of 1 to %d, got %q", kw, max, text)
	}
	return n, nil
}

// value reads the unsigned value of a `const` or `when` of n bits.
func (sp *seqParser) value(kw, text string, n, line int) (uint64, error) {
	v, err := strconv.ParseUint(text, 10, 64)
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
func (sp *seqParser) lookup(name string) *seqPresenceDef {
	for i := len(sp.stack) - 1; i >= 0; i-- {
		f := sp.stack[i]
		if pr := f.kpres[name]; pr != nil {
			return pr
		}
		if pr := f.pres[name]; pr != nil {
			return pr
		}
	}
	return nil
}

func (sp *seqParser) push(f *seqFrame) {
	if f.pres == nil {
		f.pres = map[string]*seqPresenceDef{}
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
	switch kw {
	case "field":
		f := &Field{Key: args[0], Locator: args[1], Transform: args[2], Line: n}
		if err := parseFieldOptions(f, args[3:]); err != nil {
			return sp.bad(n, f.Locator, "%v", err)
		}
		p.Fields = append(p.Fields, f)
		p.keyRefs = append(p.keyRefs, keyRef{key: f.Key, locator: f.Locator, line: n, field: f})
		add(&seqNode{op: seqField, f: f})
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
		p.Fields = append(p.Fields, f)
		p.keyRefs = append(p.keyRefs, keyRef{key: f.Key, locator: f.Locator, line: n, field: f})
		top.last = last
	case "const":
		ln, err := sp.bitLen(kw, args[0], 64, n)
		if err != nil {
			return err
		}
		v, err := sp.value(kw, args[1], ln, n)
		if err != nil {
			return err
		}
		add(&seqNode{op: seqConst, n: ln, num: v})
	case "pad":
		ln, err := sp.bitLen(kw, args[0], 1<<24, n)
		if err != nil {
			return err
		}
		add(&seqNode{op: seqPad, n: ln})
	case "align":
		m, err := strconv.Atoi(args[0])
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
		v, err := sp.value(kw, args[1], ln, n)
		if err != nil {
			return err
		}
		node := &seqNode{op: seqWhen, n: ln, num: v, line: n}
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
			return sp.perr(ErrDuplicateKind, n, "", "kind %q already declared on line %d", args[0], prev)
		}
		top.kindNames[args[0]] = n
		k := &seqKind{name: args[0], line: n}
		top.body.kinds = append(top.body.kinds, k)
		top.kind, top.nodes = k, &k.nodes
		top.kpres, top.klists = map[string]*seqPresenceDef{}, map[string]int{}
		if top.op == seqMsg {
			p.Kinds = append(p.Kinds, &KindDef{Name: k.name, Line: n})
		}
	case "requires":
		if (top.op != seqMsg && top.op != seqGroup) || top.kind == nil {
			return sp.bad(n, "", "requires must stand in a kind, outside any block")
		}
		for _, key := range args {
			top.kind.requires = append(top.kind.requires, key)
			p.keyRefs = append(p.keyRefs, keyRef{key: key, line: n, req: true})
		}
		if top.op == seqMsg {
			kd := p.Kinds[len(p.Kinds)-1]
			kd.Requires = append(kd.Requires, args...)
		}
	case "default":
		// A default belongs to the message or the item it stands in.
		d := &Default{Key: args[0], Value: args[1], Line: n}
		p.keyRefs = append(p.keyRefs, keyRef{key: d.Key, line: n, def: d})
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
		pr := &seqPresenceDef{name: name, line: n, named: map[int]bool{}}
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
		if prev := top.pres[name]; prev != nil {
			return sp.bad(n, "", "presence %s is already declared in this block on line %d", name, prev.line)
		}
		if top.kind != nil {
			if prev := top.kpres[name]; prev != nil {
				return sp.bad(n, "", "presence %s is already declared in this block on line %d", name, prev.line)
			}
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
			bit, err := strconv.Atoi(text[i+1:])
			if err != nil || bit < 1 {
				return sp.bad(n, "", "if names presence bits as <name>.<i> with i >= 1, got %q", a)
			}
			c.p = sp.lookup(text[:i])
			if c.p == nil {
				return sp.bad(n, "", "if names presence %q, which is not visible here", text[:i])
			}
			if !c.p.fx && bit > c.p.n {
				return sp.bad(n, "", "if names bit %d of presence %s, which has %d bit(s)", bit, c.p.name, c.p.n)
			}
			c.bit = bit
			c.p.named[bit] = true
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
				v, err := strconv.ParseInt(args[i], 10, 64)
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
		default:
			return sp.bad(n, g.Locator, "a sequential group is `group <list> count <len>`, `while`, `more` or `fx`")
		}
		// Within one scope a list is mapped by at most one group.
		sc := sp.scope()
		prev, dup := sc.lists[g.List]
		if !dup && sc.kind != nil {
			prev, dup = sc.klists[g.List]
		}
		if dup {
			return sp.bad(n, g.Locator, "list %s is already mapped by the group on line %d of the same scope", g.List, prev)
		}
		if sc.kind != nil {
			sc.klists[g.List] = n
		} else {
			sc.lists[g.List] = n
		}
		g.sbody = &seqBody{}
		sp.bodies = append(sp.bodies, g.sbody)
		p.keyRefs = append(p.keyRefs, keyRef{key: g.List, locator: g.Locator, line: n, group: g})
		add(&seqNode{op: seqGroup, g: g})
		sp.push(&seqFrame{op: seqGroup, line: n, group: g, body: g.sbody, nodes: &g.sbody.common, kindNames: map[string]int{}, lists: map[string]int{}})
	case "end":
		if err := count(0); err != nil {
			return err
		}
		if len(sp.stack) == 1 {
			return sp.bad(n, "", "end with no open block")
		}
		if top.op == seqGroup && top.body.whens > 0 && len(top.body.kinds) == 0 {
			return sp.bad(top.line, "", "a when line needs a body with a kind line")
		}
		sp.stack = sp.stack[:len(sp.stack)-1]
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
	return nil
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
	pres  map[*seqPresenceDef][]bool
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

func decodeSeq(d *decodeState, data []byte) error {
	p := d.pack
	r := &seqReader{d: d, p: p, data: data, limit: len(data) * 8, pres: map[*seqPresenceDef][]bool{}}
	k, err := r.body(p.sbody)
	if err != nil {
		return err
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
			if pos+w.n > r.limit || getBits(r.data, pos, w.n, r.p.msb) != w.num {
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
		at, ok, err := r.take(f.loc.blen, "field "+f.Key)
		if err != nil || !ok {
			return err
		}
		var v Value
		if f.btf.ascii {
			v, err = decodeASCII(r.data, f, at, p.msb)
		} else {
			raw := getBits(r.data, at, f.loc.blen, p.msb)
			if f.Swap {
				raw = swapBytes(raw, f.loc.blen/8)
			}
			v, err = f.btf.decode(raw, f.loc.blen)
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
		if err != nil || !ok || getBits(r.data, at, n.n, p.msb) != n.num {
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
		limit, ext := r.limit, r.ext
		r.limit, r.ext = end, true
		err = r.nodes(n.body)
		r.limit, r.ext = limit, ext
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
	}
	return nil
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
		for {
			at, ok, err := r.take(8, "presence "+pr.name)
			if err != nil {
				return err
			}
			if !ok {
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
			return r.malformed("presence bit %s.%d is 1 and no if block names it", pr.name, i)
		}
	}
	r.pres[pr] = bits
	return nil
}

// group reads the items of a sequential group.
func (r *seqReader) group(g *Group) error {
	p, d := r.p, r.d
	// A group at or after the end of a length extent gives an absent list.
	if r.beyond() {
		return nil
	}
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
	case seqCount:
		at, _, err := r.take(g.countBits, "the count of list "+g.List)
		if err != nil {
			return err
		}
		count := getBits(r.data, at, g.countBits, p.msb)
		// A count larger than the bits left is refused before any item is
		// read (0.8 ruling 14).
		if count > uint64(r.limit-r.pos) {
			return r.malformed("list %s: a count of %d and %d bit(s) left", g.List, count, r.limit-r.pos)
		}
		for i := uint64(0); i < count; i++ {
			if err := item(); err != nil {
				return err
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
}

// seqWriter writes a sequential message at a cursor.
type seqWriter struct {
	p      *Pack
	buf    *bitBuf
	pos    int
	pres   map[*seqPresenceDef][]bool
	wholes []seqWholeAt
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

func encodeSeq(p *Pack, ent *Entity) ([]byte, error) {
	w := &seqWriter{p: p, buf: &bitBuf{}, pres: map[*seqPresenceDef][]bool{}}
	rec := ent.item()
	nodes, defs, err := seqSelect(p, p.sbody, ent.Kind, rec, "the entity")
	if err != nil {
		return nil, err
	}
	if err := w.emit(nodes, seqScope{rec: rec, defs: defs}, false); err != nil {
		return nil, err
	}
	// A message is a whole number of bytes; the last bits are zero.
	if rem := w.pos % 8; rem != 0 {
		w.alloc(8 - rem)
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
		return nil, nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("%s names kind %q, which the format does not have there", what, kind.Name)}
	}
next:
	for _, k := range b.kinds {
		for _, key := range k.requires {
			if _, ok := rec.Fields[key]; !ok && len(rec.Lists[key]) == 0 {
				continue next
			}
		}
		return k.all, k.defs, nil
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
		return sc.defs[key] != nil
	}
	if has(f.Key) {
		return true
	}
	for _, a := range f.also {
		if has(a.Key) {
			return true
		}
	}
	return false
}

// seqPresent reports whether lines would write a present key or a non-empty
// list.
func seqPresent(nodes []*seqNode, sc seqScope) bool {
	for _, n := range nodes {
		switch n.op {
		case seqField:
			if fieldPresent(n.f, sc) {
				return true
			}
		case seqGroup:
			if len(sc.rec.Lists[n.g.List]) > 0 {
				return true
			}
		case seqIf, seqOpt, seqChain, seqLength:
			if seqPresent(n.body, sc) {
				return true
			}
		}
	}
	return false
}

// presenceBits computes the bits of a presence before it is written: a bit
// is 1 when some `if` block that names it without `!`, among the lines that
// follow the presence line, has content. A block inside a group item counts
// for every item (0.8 rulings 4 and 12).
func (w *seqWriter) presenceBits(pr *seqPresenceDef, rest []*seqNode, sc seqScope) ([]bool, error) {
	bits := make([]bool, pr.n+1)
	set := func(i int) {
		for len(bits) <= i {
			bits = append(bits, false)
		}
		bits[i] = true
	}
	var walk func(nodes []*seqNode, sc seqScope) error
	walk = func(nodes []*seqNode, sc seqScope) error {
		for _, n := range nodes {
			switch n.op {
			case seqIf:
				names := false
				for _, c := range n.conds {
					if c.p == pr && !c.neg {
						names = true
					}
				}
				if names && seqPresent(n.body, sc) {
					for _, c := range n.conds {
						if c.p == pr && !c.neg {
							set(c.bit)
						}
					}
				}
				if err := walk(n.body, sc); err != nil {
					return err
				}
			case seqOpt, seqChain, seqLength:
				if err := walk(n.body, sc); err != nil {
					return err
				}
			case seqGroup:
				for _, it := range sc.rec.Lists[n.g.List] {
					nodes, defs, err := seqSelect(w.p, n.g.sbody, it.Kind, it, "an item of list "+n.g.List)
					if err != nil {
						return err
					}
					if err := walk(nodes, seqScope{rec: it, defs: defs}); err != nil {
						return err
					}
				}
			}
		}
		return nil
	}
	if err := walk(rest, sc); err != nil {
		return nil, err
	}
	return bits, nil
}

// seqFieldValue returns the value a field line writes and the line it comes
// from: the value of the earliest of the line's keys that the entity has,
// else the default of the earliest key that has one (0.8 ruling 13); the
// `type` key mapped back to the native code; then the line's value table.
func seqFieldValue(p *Pack, f *Field, sc seqScope) (Value, *Field, bool, error) {
	cands := append([]*Field{f}, f.also...)
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
			v, from, ok, err := seqFieldValue(p, f, sc)
			if err != nil {
				return err
			}
			at := w.alloc(f.loc.blen)
			if !ok {
				continue
			}
			if err := putBitsField(p, from, v, w.buf.data, at); err != nil {
				return err
			}
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
			bits, err := w.presenceBits(pr, nodes[i+1:], sc)
			if err != nil {
				return err
			}
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
			if seqPresent(n.body, sc) {
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
			if !chain || !seqPresent(nodes[i+1:], sc) {
				return nil
			}
			w.put(at, 1, 1)
		case seqLength:
			at := w.alloc(n.n)
			start := w.pos
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
			if err := w.length(n, at, size); err != nil {
				return err
			}
		case seqWhole:
			w.wholes = append(w.wholes, seqWholeAt{n: n, at: w.alloc(n.n)})
		case seqGroup:
			if err := w.group(n.g, sc); err != nil {
				return err
			}
		}
	}
	return nil
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
		return w.emit(nodes, seqScope{rec: it, defs: defs}, false)
	}
	bit := func(one bool) {
		at := w.alloc(1)
		if one {
			w.put(at, 1, 1)
		}
	}
	switch g.seqMode {
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
