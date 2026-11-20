package goatxf

import (
	"fmt"
	"strconv"
	"strings"
)

// Gate is one gate block of a fixed-layout bits pack (spec/engine-spec.md,
// "Version 0.17: gated fields on a fixed layout"): `if [!]<locator>
// <value>[,<value>…]` … `end`. The block holds when the bits at the locator
// equal one of the values (with `!`, none of them). Its lines stay in the
// scope's lines, in file order, each marked with its innermost block.
type Gate struct {
	Locator string // as written, without the `!`
	Line    int

	not      bool
	vals     []uint64
	loc      locator
	parent   *Gate  // the block this one is nested in, nil at the top of its scope
	group    *Group // the innermost group the block is in, nil outside a group
	defs     map[string]*Default
	defaults []*Default
}

// parseGate reads the arguments of a fixed-layout `if` line. Every fault is
// bad-directive: a presence name, a locator that is not <word>:<pos>:<len>
// with len 1 to 64, an empty list, a value that is not an unsigned decimal
// integer below 2^len, a value listed twice.
func parseGate(args []string, n int) (*Gate, error) {
	if len(args) != 2 {
		return nil, fmt.Errorf("a gate is `if [!]<word>:<pos>:<len> <value>[,<value>…]`, got %d argument(s)", len(args))
	}
	g := &Gate{Line: n}
	text := args[0]
	if strings.HasPrefix(text, "!") {
		g.not, text = true, text[1:]
	}
	g.Locator = text
	loc, err := parseLocator(WireBits, text, false)
	if err != nil {
		return nil, fmt.Errorf("gate locator %q: %v (a presence name is valid only in a sequential layout)", args[0], err)
	}
	if loc.blen > 64 {
		return nil, fmt.Errorf("a gate covers 1 to 64 bits, got %d", loc.blen)
	}
	g.loc = loc
	seen := map[uint64]bool{}
	for _, s := range strings.Split(args[1], ",") {
		if !isDigits(s) {
			return nil, fmt.Errorf("a gate value is an unsigned decimal integer, got %q in %q", s, args[1])
		}
		v, err := strconv.ParseUint(s, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("gate value %q does not fit 64 bits", s)
		}
		if loc.blen < 64 && v>>uint(loc.blen) != 0 {
			return nil, fmt.Errorf("gate value %d does not fit in %d bit(s)", v, loc.blen)
		}
		if seen[v] {
			return nil, fmt.Errorf("gate value %d listed twice", v)
		}
		seen[v] = true
		g.vals = append(g.vals, v)
	}
	return g, nil
}

// matches reports whether the block holds on the value v of its bits.
func (g *Gate) matches(v uint64) bool {
	in := false
	for _, x := range g.vals {
		if x == v {
			in = true
			break
		}
	}
	return in != g.not
}

// value is the gate value encode step 3 gives an open block: the first
// listed value, or for `!` the smallest value not listed; ok is false when a
// `!` list names every value.
func (g *Gate) value() (uint64, bool) {
	if !g.not {
		return g.vals[0], true
	}
	listed := map[uint64]bool{}
	for _, x := range g.vals {
		listed[x] = true
	}
	// A list of k values leaves a value below k+1 unlisted, unless the
	// list names every value of a narrow gate.
	for v := uint64(0); v <= uint64(len(g.vals)); v++ {
		if g.loc.blen < 64 && v>>uint(g.loc.blen) != 0 {
			break
		}
		if !listed[v] {
			return v, true
		}
	}
	return 0, false
}

// holdsOn evaluates the block alone (not its enclosing blocks) on data, its
// scope starting at message bit base, as decode does: a gate any of whose
// bits lies beyond the nbits bits of the input does not hold, in either form.
// Under six-bit armor nbits is the bits the text carries (0.17 ruling 14).
func (g *Gate) holdsOn(data []byte, nbits, base int, msb bool) bool {
	at := base + g.loc.bit
	if at+g.loc.blen > nbits || at+g.loc.blen > len(data)*8 {
		return false
	}
	return g.matches(getBits(data, at, g.loc.blen, msb))
}

// gateEval evaluates the blocks of one scope on data, a nested block only
// when the block enclosing it holds.
func gateEval(data []byte, nbits, base int, msb bool) func(*Gate) bool {
	cache := map[*Gate]bool{}
	var holds func(g *Gate) bool
	holds = func(g *Gate) bool {
		if g == nil {
			return true
		}
		if r, ok := cache[g]; ok {
			return r
		}
		r := holds(g.parent) && g.holdsOn(data, nbits, base, msb)
		cache[g] = r
		return r
	}
	return holds
}

// fieldDefault is the default that applies to a field: the innermost block's
// default of its key, else that of an enclosing block, else the scope's (0.17
// ruling 5).
func fieldDefault(lay *layout, f *Field) *Default {
	for g := f.gate; g != nil; g = g.parent {
		if d := g.defs[f.Key]; d != nil {
			return d
		}
	}
	return lay.defaults[f.Key]
}

// encodeGatedScope is the encode of a scope that has gate blocks (0.17,
// Encode, steps 1 to 6). snap is the buffer once the items of the scope's
// groups are written. It returns the furthest bit the held blocks reach, and
// the check of step 6, which the caller runs once on the final output
// (ruling 9).
func encodeGatedScope(p *Pack, lay *layout, rec *Item, buf *bitBuf, base int) (int, func([]byte, int) error, error) {
	snap := append([]byte(nil), buf.data...)
	outside := func(ln line) bool { return ln.in == nil }

	// Step 2: the lines outside any block, by the 0.5 and 0.6 rules.
	img := append([]byte(nil), snap...)
	if err := writeBitsLines(p, lay, rec, img, base, outside, nil, nil); err != nil {
		return 0, nil, err
	}
	written := make([]bool, lay.allBit)
	markStrong(lay, rec, outside, written, true)

	// Step 1: a block is open when a field of it, or of a block nested in
	// it, maps a key the record holds.
	open := map[*Gate]bool{}
	for _, ln := range lay.lines {
		if f := ln.f; f != nil && f.gate != nil {
			if f.has(rec) {
				for g := f.gate; g != nil; g = g.parent {
					open[g] = true
				}
			}
		}
	}

	// Step 3: gate values, in line order (outer blocks come first).
	vals := map[*Gate]uint64{}
	for _, g := range lay.gates {
		if !open[g] {
			continue
		}
		taken := false
		for k := 0; k < g.loc.blen; k++ {
			if written[g.loc.bit+k] {
				taken = true
				break
			}
		}
		if taken {
			continue
		}
		v, ok := g.value()
		if !ok {
			continue
		}
		vals[g] = v
		for k := 0; k < g.loc.blen; k++ {
			written[g.loc.bit+k] = true
		}
		putBits(img, base+g.loc.bit, g.loc.blen, v, p.msb)
	}

	// Step 4: the held blocks, evaluated on those bits.
	holds := gateEval(img, len(img)*8, base, p.msb)
	held := map[*Gate]bool{}
	for _, g := range lay.gates {
		if holds(g) {
			held[g] = true
		}
	}

	// Step 5: the lines outside any block and those of the held blocks.
	active := func(ln line) bool { return ln.in == nil || held[ln.in] }
	copy(buf.data, snap)
	heldVals := map[*Gate]uint64{}
	for g, v := range vals {
		if held[g] {
			heldVals[g] = v
		}
	}
	if err := writeBitsLines(p, lay, rec, buf.data, base, active, lay.gates, heldVals); err != nil {
		return 0, nil, err
	}

	// A key the record holds that only lines of blocks not held map. A line
	// suppressed by `with` counts neither as mapping its key nor as a line of
	// a block not held that maps it (0.18 ruling 1).
	mapped := map[string]bool{}
	for _, ln := range lay.lines {
		if f := ln.f; f != nil && active(ln) && !f.suppressed(rec) {
			mapped[f.Key] = true
		}
	}
	for _, ln := range lay.lines {
		f := ln.f
		if f == nil || mapped[f.Key] || active(ln) || f.suppressed(rec) {
			continue
		}
		if _, has := rec.Fields[f.Key]; has {
			return 0, nil, &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: f.Locator, Detail: fmt.Sprintf("field %s: the key is mapped only in gate blocks that do not hold (the gate on line %d)", f.Key, f.gate.Line)}
		}
	}

	end := 0
	for _, ln := range lay.lines {
		var e int
		switch {
		case ln.gt != nil && held[ln.gt]:
			e = ln.gt.loc.bit + ln.gt.loc.blen
		case ln.in != nil && held[ln.in] && ln.f != nil:
			// Under six-bit armor an optional field counts toward L only
			// when it is written (0.17 ruling 14, 0.14 ruling 12).
			if p.sixbitArmor {
				if w, err := armorWrites(p, lay, ln.f, rec); err != nil {
					return 0, nil, err
				} else if !w {
					continue
				}
			}
			e = ln.f.loc.bit + ln.f.loc.blen
		case ln.in != nil && held[ln.in] && ln.w != nil:
			e = ln.w.loc.bit + ln.w.loc.blen
		}
		if e > 0 && base+e > end {
			end = base + e
		}
	}

	// Step 6: the output decodes to the same choice, checked on the final
	// output (ruling 9).
	check := func(data []byte, nbits int) error {
		got := gateEval(data, nbits, base, p.msb)
		for _, g := range lay.gates {
			if got(g) != held[g] {
				what := "does not hold"
				if !held[g] {
					what = "holds"
				}
				return &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: g.Locator, Detail: fmt.Sprintf("the gate block on line %d %s on the output, which decodes to another choice of blocks", g.Line, what)}
			}
		}
		return nil
	}
	return end, check, nil
}

// markStrong marks, relative to the scope, the bits that active lines with a
// present key write, and with all the bits of active `const` lines, `when`
// lines and group counts.
func markStrong(lay *layout, rec *Item, active func(line) bool, mask []bool, withConst bool) {
	mark := func(bit, n int) {
		for k := 0; k < n && bit+k < len(mask); k++ {
			mask[bit+k] = true
		}
	}
	for _, ln := range lay.lines {
		if !active(ln) {
			continue
		}
		switch {
		case ln.f != nil:
			if ln.f.has(rec) {
				mark(ln.f.loc.bit, ln.f.loc.blen)
			}
		case ln.w != nil && withConst:
			mark(ln.w.loc.bit, ln.w.loc.blen)
		case ln.g != nil && withConst && ln.g.countLoc != nil:
			mark(ln.g.countLoc.bit, ln.g.countLoc.blen)
		}
	}
}

// writeBitsLines writes the active lines of a scope whose first bit is message
// bit base: their sentinels, their fields that have a value (the earlier
// line's value staying where two overlap), the gate values of the held blocks
// over the bits of a default or a sentinel and under those of a present key,
// then the `const` and `when` values and the counts of the groups (0.7 ruling
// 15, 0.17 ruling 7).
func writeBitsLines(p *Pack, lay *layout, rec *Item, data []byte, base int, active func(line) bool, gates []*Gate, vals map[*Gate]uint64) error {
	// A sentinel is a field write that any line whose key is present, or has
	// a default, writes over whatever their order (0.9 ruling 16).
	for i := len(lay.lines) - 1; i >= 0; i-- {
		ln := lay.lines[i]
		if f := ln.f; f != nil && active(ln) && f.writesSentinel(rec, fieldDefault(lay, f)) {
			putBits(data, base+f.loc.bit, f.loc.blen, f.sentinelBits(), p.msb)
		}
	}
	for i := len(lay.lines) - 1; i >= 0; i-- {
		ln := lay.lines[i]
		f := ln.f
		if f == nil || !active(ln) {
			continue
		}
		v, ok, err := fieldValue(p, lay, f, rec)
		if err != nil {
			return err
		}
		if !ok {
			continue
		}
		if err := putBitsField(p, f, v, data, base+f.loc.bit); err != nil {
			return err
		}
	}
	if len(vals) > 0 {
		present := make([]bool, lay.allBit)
		markStrong(lay, rec, active, present, false)
		for _, g := range gates {
			v, ok := vals[g]
			if !ok {
				continue
			}
			for k := 0; k < g.loc.blen; k++ {
				if present[g.loc.bit+k] {
					continue
				}
				var bit uint64
				if p.msb {
					bit = v >> uint(g.loc.blen-1-k) & 1
				} else {
					bit = v >> uint(k) & 1
				}
				putBits(data, base+g.loc.bit+k, 1, bit, p.msb)
			}
		}
	}
	// Over the same bits the order of writes is fields, then const, then
	// when, then counts (0.7 ruling 15).
	for _, ln := range lay.lines {
		if w := ln.w; w != nil && w.Const && active(ln) {
			putBits(data, base+w.loc.bit, w.loc.blen, w.num, p.msb)
		}
	}
	for _, ln := range lay.lines {
		if w := ln.w; w != nil && !w.Const && active(ln) {
			putBits(data, base+w.loc.bit, w.loc.blen, whenBitsValue(p, lay, rec, w, active), p.msb)
		}
	}
	// The count of a group counted by a locator is the number of items,
	// written over any field on its bits (0.7 ruling 2).
	for _, g := range lay.groups {
		if c := g.countLoc; c != nil {
			putBits(data, base+c.bit, c.blen, uint64(len(rec.Lists[g.List])), p.msb)
		}
	}
	return nil
}

// whenBitsValue is the value an encode writes for a `when` on the bits wire:
// the value of the first active field line with a present key that covers
// exactly the when's bits and whose value matches the when, else the when's
// first value (0.20 rulings 3 and 15; a default does not count).
func whenBitsValue(p *Pack, lay *layout, rec *Item, w *When, active func(line) bool) uint64 {
	if len(w.ranges) <= 1 && (len(w.ranges) == 0 || w.ranges[0].lo == w.ranges[0].hi) {
		return w.num
	}
	for _, ln := range lay.lines {
		f := ln.f
		if f == nil || !active(ln) || f.loc.bit != w.loc.bit || f.loc.blen != w.loc.blen || !f.has(rec) {
			continue
		}
		v, ok, err := fieldValue(p, lay, f, rec)
		if err != nil || !ok {
			continue
		}
		scratch := make([]byte, (f.loc.blen+7)/8+1)
		if putBitsField(p, f, v, scratch, 0) != nil {
			continue
		}
		if raw := getBits(scratch, 0, f.loc.blen, p.msb); w.matchNum(raw) {
			return raw
		}
	}
	return w.num
}
