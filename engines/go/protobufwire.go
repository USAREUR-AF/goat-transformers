//go:build !goat_wires || goat_wire_protobuf

package goatxf

import (
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"sort"
)

// readVarint reads a base-128 varint from the front of b, returning its value
// and the number of bytes consumed.
func readVarint(b []byte) (uint64, int, error) {
	var v uint64
	var shift uint
	for i := 0; i < len(b); i++ {
		c := b[i]
		if shift >= 64 {
			return 0, 0, fmt.Errorf("varint is longer than 10 bytes")
		}
		// The tenth byte holds bit 63 only (0.8 ruling 40).
		if shift == 63 && c > 1 {
			return 0, 0, fmt.Errorf("ten-byte varint holds bits above bit 63")
		}
		v |= uint64(c&0x7f) << shift
		if c&0x80 == 0 {
			return v, i + 1, nil
		}
		shift += 7
	}
	return 0, 0, fmt.Errorf("truncated varint")
}

// putVarint appends v to dst as a base-128 varint.
func putVarint(dst []byte, v uint64) []byte {
	for v >= 0x80 {
		dst = append(dst, byte(v)|0x80)
		v >>= 7
	}
	return append(dst, byte(v))
}

// pbMaxField is the largest field number a tag may hold, 2^29-1 (0.8 ruling 38).
const pbMaxField = 1<<29 - 1

// parsePBMessage parses one protobuf message into field number -> occurrences,
// in wire order. The caller takes the last occurrence when a number repeats.
func parsePBMessage(format string, data []byte) (map[int][]pbVal, error) {
	bad := func(detail string) error {
		return &Error{Kind: ErrMalformedWire, Format: format, Detail: detail}
	}
	out := map[int][]pbVal{}
	i := 0
	for i < len(data) {
		tag, n, err := readVarint(data[i:])
		if err != nil {
			return nil, bad("reading a field tag: " + err.Error())
		}
		i += n
		wt := int(tag & 7)
		if tag>>3 < 1 || tag>>3 > pbMaxField {
			return nil, bad(fmt.Sprintf("field number %d is not valid (1 to %d)", tag>>3, uint64(pbMaxField)))
		}
		field := int(tag >> 3)
		pv := pbVal{wire: wt}
		switch wt {
		case pbVarint:
			v, m, err := readVarint(data[i:])
			if err != nil {
				return nil, bad(fmt.Sprintf("field %d varint: %v", field, err))
			}
			i += m
			pv.u = v
		case pbFixed64:
			if i+8 > len(data) {
				return nil, bad(fmt.Sprintf("field %d fixed64 is truncated", field))
			}
			pv.u = binary.LittleEndian.Uint64(data[i : i+8])
			i += 8
		case pbLenDelim:
			l, m, err := readVarint(data[i:])
			if err != nil {
				return nil, bad(fmt.Sprintf("field %d length prefix: %v", field, err))
			}
			i += m
			if l > uint64(len(data)-i) {
				return nil, bad(fmt.Sprintf("field %d length-delimited value overruns the message", field))
			}
			pv.b = data[i : i+int(l)]
			i += int(l)
		case pbFixed32:
			if i+4 > len(data) {
				return nil, bad(fmt.Sprintf("field %d fixed32 is truncated", field))
			}
			pv.u = uint64(binary.LittleEndian.Uint32(data[i : i+4]))
			i += 4
		case 3, 4:
			return nil, bad(fmt.Sprintf("field %d uses a group wire type (%d); groups are not supported", field, wt))
		default:
			return nil, bad(fmt.Sprintf("field %d uses unknown wire type %d", field, wt))
		}
		out[field] = append(out[field], pv)
	}
	return out, nil
}

// lastOf returns the last occurrence of field fn, or nil when it is absent.
func lastOf(msg map[int][]pbVal, fn int) *pbVal {
	occ := msg[fn]
	if len(occ) == 0 {
		return nil
	}
	return &occ[len(occ)-1]
}

// submsg reads a length-delimited occurrence as a submessage. The parse is
// kept, so the lines that read into one submessage parse it once.
func (pv *pbVal) submsg(format string) (map[int][]pbVal, error) {
	if !pv.parsed {
		pv.sub, pv.subErr = parsePBMessage(format, pv.b)
		pv.parsed = true
	}
	return pv.sub, pv.subErr
}

func decodeProtobuf(d *decodeState, b []byte) error {
	p := d.pack
	data, err := parseHexInput(p.Format, b)
	if err != nil {
		return err
	}
	top, err := parsePBMessage(p.Format, data)
	if err != nil {
		return err
	}
	// `present`: the field at the path occurs on the wire. An integer: the
	// field is a varint equal to it.
	// A `when` path whose prefix is not a submessage does not hold; it is not
	// an error (0.8 ruling 31).
	lay, err := d.choose(func(w *When) bool {
		pv, err := resolvePBPath(p.Format, top, w.loc.pbPath)
		if err != nil || pv == nil {
			return false
		}
		return w.present || (pv.wire == pbVarint && w.matchNum(pv.u))
	})
	if err != nil {
		return err
	}
	return d.pbScope(lay, top, nil)
}

// pbScope decodes the lines of one scope: msg is the message, or one item of
// a group read as a submessage (nil when the item was not read as one); occ is
// the item's own occurrence, which a `.` field reads as a scalar.
func (d *decodeState) pbScope(lay *layout, msg map[int][]pbVal, occ *pbVal) error {
	p := d.pack
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			pv := occ
			if !f.dot {
				var derr error
				pv, derr = resolvePBPath(p.Format, msg, f.loc.pbPath)
				// A path prefix that is not a submessage is malformed-wire,
				// inside or outside a group (0.7 ruling 13, 0.8 ruling 30).
				if _, notSub := derr.(*pbNotSubmsg); notSub {
					return &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: f.Locator, Detail: "field " + f.Key + ": " + derr.Error()}
				}
				// Bytes of a submessage the path walks into that do not parse
				// are malformed-wire, not a field failure (0.8 ruling 38).
				if derr != nil {
					return derr
				}
			}
			if pv == nil {
				continue
			}
			if pv.wire != f.pbf.wire {
				d.fail(f, fmt.Sprintf("field is wire type %d, %s needs wire type %d", pv.wire, f.Transform, f.pbf.wire))
				continue
			}
			// The sentinel check comes after the wire type check (0.9 ruling
			// 15): the varint before zig-zag, the fixed bytes as an integer,
			// a pstring's bytes as text.
			if f.absent != nil {
				if f.pbf.wire == pbLenDelim {
					if f.sentinelText(string(pv.b)) {
						continue
					}
				} else if f.sentinelNum(pv.u) {
					continue
				}
			}
			v, err := f.pbf.decode(*pv)
			if err != nil {
				d.fail(f, err.Error())
				continue
			}
			d.store(f, v)
		case ln.g != nil:
			if err := d.pbGroup(ln.g, msg); err != nil {
				return err
			}
		}
	}
	return nil
}

// pbGroup decodes the list of a group: one item per occurrence of the last
// field number of its path, in wire order, under the last occurrence of each
// number before it. A group of scalars with a numeric transform also accepts
// the packed form: one length-delimited occurrence holding the values back to
// back. The list is present when at least one item occurs.
func (d *decodeState) pbGroup(g *Group, msg map[int][]pbVal) error {
	p := d.pack
	bad := func(format string, a ...any) error {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: g.Locator, Detail: "list " + g.List + ": " + fmt.Sprintf(format, a...)}
	}
	path := g.loc.pbPath
	for _, fn := range path[:len(path)-1] {
		pv := lastOf(msg, fn)
		if pv == nil {
			return nil
		}
		if pv.wire != pbLenDelim {
			return bad("path descends into field %d but it is wire type %d, not a submessage", fn, pv.wire)
		}
		sub, err := pv.submsg(p.Format)
		if err != nil {
			return err
		}
		msg = sub
	}
	occs := msg[path[len(path)-1]]
	var items []*Item
	for i := range occs {
		o := &occs[i]
		if g.packed && o.wire == pbLenDelim {
			vals, err := unpackPB(g.dots[0].pbf.wire, o.b)
			if err != nil {
				return bad("packed values: %v", err)
			}
			for j := range vals {
				it, err := d.item(func() error { return d.pbScope(g.body, nil, &vals[j]) })
				if err != nil {
					return err
				}
				items = append(items, it)
			}
			continue
		}
		var sub map[int][]pbVal
		if g.needsMsg {
			if o.wire != pbLenDelim {
				return bad("an item is wire type %d, not a submessage", o.wire)
			}
			var err error
			if sub, err = o.submsg(p.Format); err != nil {
				return err
			}
		}
		it, err := d.item(func() error { return d.pbScope(g.body, sub, o) })
		if err != nil {
			return err
		}
		items = append(items, it)
	}
	if len(items) > 0 {
		d.rec.SetList(g.List, items)
	}
	return nil
}

// unpackPB splits the payload of a packed repeated field into its values, each
// of the given wire type. A payload whose length does not fit its values is
// an error.
func unpackPB(wire int, b []byte) ([]pbVal, error) {
	var out []pbVal
	switch wire {
	case pbVarint:
		for i := 0; i < len(b); {
			v, n, err := readVarint(b[i:])
			if err != nil {
				return nil, err
			}
			i += n
			out = append(out, pbVal{wire: pbVarint, u: v})
		}
	case pbFixed64:
		if len(b)%8 != 0 {
			return nil, fmt.Errorf("%d byte(s) do not hold whole 8-byte values", len(b))
		}
		for i := 0; i < len(b); i += 8 {
			out = append(out, pbVal{wire: pbFixed64, u: binary.LittleEndian.Uint64(b[i : i+8])})
		}
	case pbFixed32:
		if len(b)%4 != 0 {
			return nil, fmt.Errorf("%d byte(s) do not hold whole 4-byte values", len(b))
		}
		for i := 0; i < len(b); i += 4 {
			out = append(out, pbVal{wire: pbFixed32, u: uint64(binary.LittleEndian.Uint32(b[i : i+4]))})
		}
	}
	return out, nil
}

// pbNotSubmsg reports a path that descends into a field that is not a
// length-delimited submessage.
type pbNotSubmsg struct{ field, wire int }

func (e *pbNotSubmsg) Error() string {
	return fmt.Sprintf("path descends into field %d but it is wire type %d, not a submessage", e.field, e.wire)
}

// resolvePBPath walks a dot-path into nested submessages and returns the leaf
// occurrence, nil when any element along the path is absent. An error means
// a non-leaf element existed but was not a length-delimited submessage, or a
// submessage could not be parsed.
func resolvePBPath(format string, top map[int][]pbVal, path []int) (*pbVal, error) {
	msg := top
	for depth, fn := range path {
		pv := lastOf(msg, fn)
		if pv == nil {
			return nil, nil
		}
		if depth == len(path)-1 {
			return pv, nil
		}
		if pv.wire != pbLenDelim {
			return nil, &pbNotSubmsg{field: fn, wire: pv.wire}
		}
		sub, err := pv.submsg(format)
		if err != nil {
			return nil, err
		}
		msg = sub
	}
	return nil, nil
}

// pbTree is the canonical shape of a protobuf message being encoded: leaf
// scalars, nested submessages and the occurrences of repeated fields, each
// keyed by field number.
type pbTree struct {
	leaves map[int]pbVal
	subs   map[int]*pbTree
	reps   map[int][]pbVal
	weak   map[int]bool // leaves that hold a sentinel, which a value replaces (0.9 ruling 16)
	// omit holds the leaves `implicit` leaves out (0.56): they hold the place
	// of their path and are not written.
	omit map[int]bool
	kept bool // `when <path> present` asked for this submessage (0.5 ruling 14)
}

func newPBTree() *pbTree {
	return &pbTree{leaves: map[int]pbVal{}, subs: map[int]*pbTree{}, reps: map[int][]pbVal{}, weak: map[int]bool{}, omit: map[int]bool{}}
}

// void reports whether nothing is written in the tree: every leaf is left
// out by `implicit`, no field repeats, every submessage is void, and no
// `when present` asked for it.
func (t *pbTree) void() bool {
	if t.kept || len(t.reps) > 0 {
		return false
	}
	for fn := range t.leaves {
		if !t.omit[fn] {
			return false
		}
	}
	for _, sub := range t.subs {
		if !sub.void() {
			return false
		}
	}
	return true
}

// setValue places a field's value at path as set does; implicit marks a
// value at the proto3 default, which holds the place and is not written.
func (t *pbTree) setValue(path []int, v pbVal, implicit bool) {
	cur, fn := t.at(path), path[len(path)-1]
	if _, has := cur.leaves[fn]; !has || cur.weak[fn] {
		cur.leaves[fn] = v
		delete(cur.weak, fn)
		delete(cur.omit, fn)
		if implicit && isProto3Default(v) {
			cur.omit[fn] = true
		}
	}
}

// at returns the submessage that holds the last number of path, creating the
// submessages along the way.
func (t *pbTree) at(path []int) *pbTree {
	cur := t
	for _, fn := range path[:len(path)-1] {
		child, ok := cur.subs[fn]
		if !ok {
			child = newPBTree()
			cur.subs[fn] = child
		}
		cur = child
	}
	return cur
}

// set places v at path, creating submessages along the way. The first value
// at a path stays unless force is set.
func (t *pbTree) set(path []int, v pbVal, force bool) {
	cur, fn := t.at(path), path[len(path)-1]
	if _, has := cur.leaves[fn]; !has || force || cur.weak[fn] {
		cur.leaves[fn] = v
		delete(cur.weak, fn)
		delete(cur.omit, fn)
	}
}

// setSentinel places a sentinel at path where nothing is written yet; a value
// written there later replaces it.
func (t *pbTree) setSentinel(path []int, v pbVal, implicit bool) {
	cur, fn := t.at(path), path[len(path)-1]
	if _, has := cur.leaves[fn]; !has {
		cur.leaves[fn] = v
		cur.weak[fn] = true
		if implicit && isProto3Default(v) {
			cur.omit[fn] = true
		}
	}
}

// repeat places the occurrences of a repeated field at path.
func (t *pbTree) repeat(path []int, occs []pbVal) {
	cur, fn := t.at(path), path[len(path)-1]
	cur.reps[fn] = append(cur.reps[fn], occs...)
}

// ensure makes the field at path occur in the output: when nothing is written
// at or under it, it becomes an empty length-delimited field.
func (t *pbTree) ensure(path []int) {
	cur, fn := t.at(path), path[len(path)-1]
	if _, has := cur.leaves[fn]; has && !cur.omit[fn] {
		return
	}
	if len(cur.reps[fn]) > 0 {
		return
	}
	if _, ok := cur.subs[fn]; !ok {
		cur.subs[fn] = newPBTree()
	}
	cur.subs[fn].kept = true
}

// marshal serialises the tree in ascending field-number order, each submessage
// likewise, writing only the fields present. The occurrences of a repeated
// field are written together, in list order.
func (t *pbTree) marshal() []byte {
	nums := make([]int, 0, len(t.leaves)+len(t.subs)+len(t.reps))
	seen := map[int]bool{}
	add := func(fn int) {
		if !seen[fn] {
			seen[fn] = true
			nums = append(nums, fn)
		}
	}
	for fn := range t.leaves {
		add(fn)
	}
	for fn := range t.subs {
		add(fn)
	}
	for fn := range t.reps {
		add(fn)
	}
	sort.Ints(nums)
	var out []byte
	for _, fn := range nums {
		pv, leaf := t.leaves[fn]
		if leaf && t.omit[fn] {
			// Left out by `implicit`; a `when present` submessage at the
			// same number is still written.
			leaf = false
			if sub, ok := t.subs[fn]; ok && sub.kept && len(t.reps[fn]) == 0 {
				out = appendPBField(out, fn, pbVal{wire: pbLenDelim, b: sub.marshal()})
			}
			for _, o := range t.reps[fn] {
				out = appendPBField(out, fn, o)
			}
			continue
		}
		if leaf {
			out = appendPBField(out, fn, pv)
		}
		for _, o := range t.reps[fn] {
			out = appendPBField(out, fn, o)
		}
		if sub, ok := t.subs[fn]; ok && !leaf && len(t.reps[fn]) == 0 && !sub.void() {
			out = appendPBField(out, fn, pbVal{wire: pbLenDelim, b: sub.marshal()})
		}
	}
	return out
}

// appendPBField writes one tag and its payload.
func appendPBField(dst []byte, fn int, pv pbVal) []byte {
	dst = putVarint(dst, uint64(fn)<<3|uint64(pv.wire))
	switch pv.wire {
	case pbVarint:
		dst = putVarint(dst, pv.u)
	case pbFixed64:
		var buf [8]byte
		binary.LittleEndian.PutUint64(buf[:], pv.u)
		dst = append(dst, buf[:]...)
	case pbLenDelim:
		dst = putVarint(dst, uint64(len(pv.b)))
		dst = append(dst, pv.b...)
	case pbFixed32:
		var buf [4]byte
		binary.LittleEndian.PutUint32(buf[:], uint32(pv.u))
		dst = append(dst, buf[:]...)
	}
	return dst
}

// appendPBScalar writes one value of a packed repeated field: the payload
// with no tag.
func appendPBScalar(dst []byte, pv pbVal) []byte {
	switch pv.wire {
	case pbVarint:
		dst = putVarint(dst, pv.u)
	case pbFixed64:
		var buf [8]byte
		binary.LittleEndian.PutUint64(buf[:], pv.u)
		dst = append(dst, buf[:]...)
	case pbFixed32:
		var buf [4]byte
		binary.LittleEndian.PutUint32(buf[:], uint32(pv.u))
		dst = append(dst, buf[:]...)
	}
	return dst
}

// encodeProtobuf writes the layout's present fields, the earliest line
// winning a path two lines share, its lists, then its when values: a varint
// for an integer, and for `present` an empty length-delimited field when no
// mapped field under the path was written.
func encodeProtobuf(p *Pack, lay *layout, rec *Item) ([]byte, error) {
	tree := newPBTree()
	if err := encodePBScope(p, lay, rec, tree); err != nil {
		return nil, err
	}
	return []byte(hex.EncodeToString(tree.marshal())), nil
}

// encodePBScope writes the lines of one scope into tree: the message, or one
// item of a group written as a submessage.
func encodePBScope(p *Pack, lay *layout, rec *Item, tree *pbTree) error {
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			if f.dot {
				continue // written by the group, as the item itself
			}
			v, ok, err := fieldValue(p, lay, f, rec)
			if err != nil {
				return err
			}
			if !ok {
				if f.hasExact() && !f.suppressed(rec) {
					tree.setSentinel(f.loc.pbPath, f.sentinelPB(), f.Implicit)
				}
				continue
			}
			pv, err := f.pbf.encode(v)
			if err != nil {
				return encodeErr(p, f, err)
			}
			tree.setValue(f.loc.pbPath, pv, f.Implicit)
		case ln.g != nil:
			g := ln.g
			items := rec.Lists[g.List]
			if len(items) == 0 {
				continue // an empty or absent list writes nothing
			}
			occs, err := encodePBItems(p, g, items)
			if err != nil {
				return err
			}
			if len(occs) == 0 {
				continue
			}
			tree.repeat(g.loc.pbPath, occs)
		}
	}
	for _, ln := range lay.lines {
		w := ln.w
		if w == nil {
			continue
		}
		if w.present {
			tree.ensure(w.loc.pbPath)
		} else {
			tree.set(w.loc.pbPath, pbVal{wire: pbVarint, u: whenPBValue(p, lay, rec, w)}, true)
		}
	}
	return nil
}

// encodePBItems returns the occurrences a list is written as: one per item,
// each a submessage or, for a `.` field, the scalar itself; a `.` field with
// a numeric transform writes the packed form, one length-delimited occurrence
// holding the values back to back. An item with nothing written is an empty
// length-delimited occurrence.
func encodePBItems(p *Pack, g *Group, items []*Item) ([]pbVal, error) {
	// dot returns the value an item writes as itself: that of the earliest
	// `.` line whose key the item has, or has a default for, else the first
	// sentinel of the earliest `.` line with `absent` (0.9 ruling 5).
	dot := func(it *Item) (pbVal, bool, error) {
		for i, f := range g.dots {
			v, ok, err := fieldValue(p, g.body, f, it)
			if err != nil {
				return pbVal{}, false, err
			}
			if !ok {
				continue
			}
			pv, err := f.pbf.encode(v)
			if err != nil {
				return pbVal{}, false, encodeErr(p, f, err)
			}
			if err := checkHeldRange(p, it, g.dots[i+1:]...); err != nil {
				return pbVal{}, false, err
			}
			return pv, true, nil
		}
		for _, f := range g.dots {
			if f.hasExact() && !f.suppressed(it) {
				return f.sentinelPB(), true, nil
			}
		}
		return pbVal{}, false, nil
	}
	if g.packed {
		var payload []byte
		for _, it := range items {
			pv, ok, err := dot(it)
			if err != nil {
				return nil, err
			}
			if ok {
				payload = appendPBScalar(payload, pv)
			}
		}
		// An item with no value is left out, and a list whose items all lack
		// the value writes nothing (0.7 ruling 11).
		if len(payload) == 0 {
			return nil, nil
		}
		return []pbVal{{wire: pbLenDelim, b: payload}}, nil
	}
	occs := make([]pbVal, 0, len(items))
	for _, it := range items {
		if len(g.dots) > 0 {
			pv, ok, err := dot(it)
			if err != nil {
				return nil, err
			}
			if ok {
				occs = append(occs, pv)
				continue
			}
		}
		sub := newPBTree()
		if err := encodePBScope(p, g.body, it, sub); err != nil {
			return nil, err
		}
		occs = append(occs, pbVal{wire: pbLenDelim, b: sub.marshal()})
	}
	return occs, nil
}

// whenPBValue is the varint an encode writes for an integer `when`: the value
// of the first field line with a present key on the same path whose varint
// matches the when, else the when's first value (0.20 rulings 3 and 15).
func whenPBValue(p *Pack, lay *layout, rec *Item, w *When) uint64 {
	for _, ln := range lay.lines {
		f := ln.f
		if f == nil || f.dot || f.pbf == nil || !f.has(rec) || !samePath(f.loc.pbPath, w.loc.pbPath) {
			continue
		}
		v, ok, err := fieldValue(p, lay, f, rec)
		if err != nil || !ok {
			continue
		}
		pv, err := f.pbf.encode(v)
		if err == nil && pv.wire == pbVarint && w.matchNum(pv.u) {
			return pv.u
		}
	}
	return w.num
}

func samePath(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
