//go:build !goat_wires || goat_wire_bits

package goatxf

import (
	"encoding/hex"
	"fmt"
	"math/bits"
)

// Sequential binary layouts (spec/engine-spec.md, "Version 0.8: sequential
// binary layouts"): a bits pack with `layout sequential` describes a message
// as lines read in order from a cursor. A locator is a bit length.

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

// inGroup reports whether a group block is open.
func (sp *seqParser) inGroup() bool {
	for _, f := range sp.stack {
		if f.op == seqGroup {
			return true
		}
	}
	return false
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
			// The selected kind's `when … as` lines set their keys; a kind
			// tested and not selected sets nothing (0.30 ruling 12).
			for _, w := range k.whens {
				if w.key != "" {
					r.setAs(w.key, getBits(r.data, r.pos, w.n, r.p.msb))
				}
				r.pos += w.n
			}
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
		if f.until {
			return r.untilField(f)
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
		if n.key != "" {
			r.setAs(n.key, getBits(r.data, at, n.n, p.msb))
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
	case seqInner:
		return r.inner(n)
	}
	return nil
}

// setAs gives the key of a `when … as` line the bits it read, as `uint` reads
// them: with 64 bits a value of 2^63 or more is the negative integer of the
// same bits (0.30 ruling 7).
func (r *seqReader) setAs(key string, u uint64) {
	if _, done := r.d.rec.Fields[key]; !done {
		r.d.rec.Fields[key] = Value{Kind: KindInt, I: int64(u)}
	}
}

// asValue returns the bits a `when … as` line writes for a scope: the value
// of its key when the entity holds it, else the first listed value (0.30,
// Encode). ok is false when the entity holds a value the `when` does not
// match. A default does not count (ruling 6).
func asValue(n *seqNode, rec *Item) (u uint64, ok bool) {
	v, held := rec.Fields[n.key]
	if !held {
		return n.num, true
	}
	return asMatch(n, v)
}

// asMatch reads a value as an unsigned 64-bit pattern and reports whether a
// `when` lists it or a range of it holds it (0.30 ruling 7).
func asMatch(n *seqNode, v Value) (uint64, bool) {
	if v.Kind != KindInt {
		return 0, false
	}
	u := uint64(v.I)
	if n.n < 64 && u>>uint(n.n) != 0 {
		return 0, false
	}
	return u, inRanges(n.rng, u)
}

// asHolds reports whether the implicit `requires` terms of a kind's
// `when … as` lines hold: the entity holds each key with a value its `when`
// matches (0.30, Encode).
func asHolds(whens []*seqNode, rec *Item) bool {
	for _, w := range whens {
		if w.key == "" {
			continue
		}
		v, held := rec.Fields[w.key]
		if !held {
			return false
		}
		if _, ok := asMatch(w, v); !ok {
			return false
		}
	}
	return true
}

// inner reads an `inner` line (spec 0.34): the checks made where the line is
// reached, then the bytes from the cursor to the end of the enclosing extent
// decoded by the inner pack, whose keys join the entity, each key keeping
// the first value read.
func (r *seqReader) inner(n *seqNode) error {
	d := r.d
	if d.eng == nil {
		return &Error{Kind: ErrUnknownFormat, Format: n.inner, Detail: "no engine to find the inner pack in"}
	}
	in, err := d.eng.innerPack(r.p, n.inner)
	if err != nil {
		return err
	}
	if r.pos%8 != 0 {
		return r.malformed("the inner line on line %d stands at bit %d, not on a whole byte", n.line, r.pos)
	}
	if r.limit%8 != 0 {
		return r.malformed("the extent of the inner line on line %d ends at bit %d, not on a whole byte", n.line, r.limit)
	}
	if r.limit > len(r.data)*8 {
		return r.malformed("the extent of the inner line on line %d ends beyond the input", n.line)
	}
	start := r.pos
	if start > r.limit {
		start = r.limit
	}
	bytes := r.data[start/8 : r.limit/8]
	r.pos = r.limit
	sub := &decodeState{pack: in, ent: NewEntity(), limit: d.limit - d.held, eng: d.eng, discard: map[string]bool{}}
	for name := range d.top.Lists {
		sub.discard[name] = true
	}
	sub.rec = sub.ent.item()
	sub.top = sub.rec
	if err := decodeBitsData(sub, bytes, len(bytes)*8); err != nil {
		return err
	}
	d.joinInner(sub)
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
	// A list an inner decode gave is kept; this group's items are read and
	// discarded (spec 0.34, Decode step 4).
	kept := d.rec == d.top && d.innerLists[g.List]
	if !kept {
		d.replacing(g.List)
	}
	if d.freeList(g.List) {
		d.free++
		defer func() { d.free-- }()
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
	if kept {
		d.held -= deepItems(items)
		return nil
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
	eng    *Engine // the engine of the encode: an `inner` line finds its pack there (0.34)
	ent    *Entity // the entity being written, which an `inner` line encodes again
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

func encodeSeq(e *Engine, p *Pack, ent *Entity) ([]byte, error) {
	rec := ent.item()
	nodes, defs, err := seqSelect(p, p.sbody, ent.Kind, rec, "the entity")
	if err != nil {
		return nil, err
	}
	forced := map[seqSwitchAt]*seqCase{}
	for pass := 1; ; pass++ {
		w := &seqWriter{p: p, eng: e, ent: ent, buf: &bitBuf{}, pres: map[*seqPresenceDef][]bool{}, forced: forced, actual: map[seqSwitchAt]*seqCase{}}
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
		// A `when … as` line adds an implicit term (0.30, Encode).
		if reqHolds(k.requires, rec) && asHolds(k.whens, rec) {
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
		case seqWhen:
			if written && n.key != "" {
				if u, ok := asValue(n, sc.rec); ok {
					if _, done := sc.vals[n.key]; !done {
						sc.vals[n.key] = Value{Kind: KindInt, I: int64(u)}
					}
				}
			}
		case seqField:
			if fieldPresent(n.f, sc) {
				content = true
			}
			if written {
				if n.f.uper != nil {
					uperReadBack(s.w, n.f, sc)
				} else if n.f.until {
					untilReadBack(s.w, n.f, sc)
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
			if f.until {
				if err := w.untilField(f, sc); err != nil {
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
		case seqConst:
			w.put(w.alloc(n.n), n.n, n.num)
		case seqWhen:
			v := n.num
			if n.key != "" {
				u, ok := asValue(n, sc.rec)
				if !ok {
					return w.fail("when … as %s on line %d: the entity holds %s, which the when does not match; the output would decode another value", n.key, n.line, sc.rec.Fields[n.key].String())
				}
				v = u
				// The value written is what a decode reads, for a switch on
				// the key (0.30 ruling 19).
				if _, done := sc.vals[n.key]; !done {
					sc.vals[n.key] = Value{Kind: KindInt, I: int64(v)}
				}
			}
			w.put(w.alloc(n.n), n.n, v)
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
		case seqInner:
			if err := w.inner(n); err != nil {
				return err
			}
		}
	}
	return nil
}

// inner writes an `inner` line (spec 0.34): after the checks made where the
// line is reached, on a whole byte, the inner pack's encoding of the same
// entity.
func (w *seqWriter) inner(n *seqNode) error {
	if w.eng == nil {
		return &Error{Kind: ErrUnknownFormat, Format: n.inner, Detail: "no engine to find the inner pack in"}
	}
	in, err := w.eng.innerPack(w.p, n.inner)
	if err != nil {
		return err
	}
	if w.pos%8 != 0 {
		return w.fail("the inner line on line %d stands at bit %d, not on a whole byte", n.line, w.pos)
	}
	out, err := w.eng.encodeLayer(in, w.ent)
	if err != nil {
		return err
	}
	at := w.alloc(len(out) * 8)
	copy(w.buf.data[at/8:], out)
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

// ---- until:<code> (spec 0.22) ----

// untilField reads a field whose locator is `until:<code>`: characters of
// its set up to the terminator, which is consumed. A field that starts at or
// after the end of a `length` extent is absent; one that finds no terminator
// before the end of its extent, or after floor(2040 / w) characters, is
// malformed-wire (rulings 4, 5 and 8). A character the set does not hold is
// a failure of the key, and the cursor stays after the terminator.
func (r *seqReader) untilField(f *Field) error {
	if r.beyond() {
		return nil
	}
	set := f.btf.charSet
	w := set.width
	start := r.pos
	maxChars := maxBitsLen / w
	n := 0
	for {
		at, ok, err := r.take(w, "field "+f.Key+" (until:)")
		if err != nil {
			return r.malformed("field %s: no terminator %d before the end of its extent", f.Key, f.untilC)
		}
		if !ok {
			return r.malformed("field %s: no terminator %d before the end of its extent", f.Key, f.untilC)
		}
		if getBits(r.data, at, w, r.p.msb) == f.untilC {
			break
		}
		n++
		if n > maxChars {
			return r.malformed("field %s: more than %d characters before the terminator %d", f.Key, maxChars, f.untilC)
		}
	}
	// Nothing is removed, and NUL is an ordinary character (rulings 6, 7
	// and 20).
	buf, err := set.decodeChars(r.data, start, n, r.p.msb)
	if err != nil {
		r.d.fail(f, err.Error())
		return nil
	}
	v := Value{Kind: KindString, S: string(buf)}
	r.d.store(f, v)
	for _, a := range f.also {
		r.d.store(a, v)
	}
	return nil
}

// untilCodes returns the codes an until: field writes: the text's
// characters, then the terminator. An absent key with no default writes the
// terminator alone (ruling 10).
func untilCodes(p *Pack, f *Field, sc seqScope) ([]uint64, *Field, error) {
	set := f.btf.charSet
	v, from, ok, err := seqFieldValue(p, f, sc)
	if err != nil {
		return nil, from, err
	}
	if !ok {
		return []uint64{f.untilC}, f, nil
	}
	s, err := encString(v)
	if err != nil {
		return nil, from, err
	}
	if max := maxBitsLen / set.width; len(s) > max {
		return nil, from, fmt.Errorf("text is %d character(s), an until: field holds at most %d", len(s), max)
	}
	term := f.untilC
	codes, err := set.encodeChars(s, &term)
	if err != nil {
		return nil, from, err
	}
	return append(codes, term), from, nil
}

// untilField writes an until: field at the cursor.
func (w *seqWriter) untilField(f *Field, sc seqScope) error {
	codes, from, err := untilCodes(w.p, f, sc)
	if err != nil {
		return encodeErr(w.p, from, err)
	}
	width := f.btf.charSet.width
	for _, c := range codes {
		w.put(w.alloc(width), width, c)
	}
	return nil
}

// untilReadBack records what a decode of an until: field's written text
// would hold, for a switch on its key (0.20): the text as written, which
// decode yields unchanged (ruling 7), or "" for the terminator alone
// (ruling 11).
func untilReadBack(w *seqWriter, f *Field, sc seqScope) {
	codes, _, err := untilCodes(w.p, f, sc)
	if err != nil {
		sc.bad[f.Key] = true
		for _, a := range f.also {
			sc.bad[a.Key] = true
		}
		return
	}
	set := f.btf.charSet
	buf := make([]byte, 0, len(codes)-1)
	for _, c := range codes[:len(codes)-1] {
		b, _ := set.dec(c)
		buf = append(buf, b)
	}
	v := Value{Kind: KindString, S: string(buf)}
	storeBack(w.p, sc, f, v)
	for _, a := range f.also {
		storeBack(w.p, sc, a, v)
	}
}
