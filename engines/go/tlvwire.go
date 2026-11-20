//go:build !goat_wires || goat_wire_tlv

package goatxf

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
	"unicode/utf8"
)

// The tlv wire (spec/engine-spec.md, "Version 0.13: the `tlv` wire"): a set
// of items, each a tag, a length and a value; a value may itself be a set.
// The set may follow a fixed key and a length, and may end with a sum16
// checksum item (0.13) or a CRC-32 item (0.27). Input and output are hex text.

// --- transforms ---

// putBE writes the low n bytes of v, big-endian.
func putBE(v uint64, n int) []byte {
	b := make([]byte, n)
	for i := n - 1; i >= 0; i-- {
		b[i] = byte(v & 0xff)
		v >>= 8
	}
	return b
}

// decode reads a value that is not empty.
func (t *tlvTf) decode(val []byte) (Value, error) {
	switch t.kind {
	case tlvUint, tlvTwos, tlvUScale, tlvSScale:
		if len(val) > 8 {
			return Value{}, fmt.Errorf("an integer value is 1 to 8 bytes, got %d", len(val))
		}
		raw, bits := beUint(val), 8*len(val)
		switch t.kind {
		case tlvUint:
			// 8 bytes follow ruling 2 of 0.5: the same bit pattern.
			return Value{Kind: KindInt, I: int64(raw)}, nil
		case tlvTwos:
			return Value{Kind: KindInt, I: signExtend(raw, bits)}, nil
		}
		return t.scale.decode(raw, bits)
	case tlvF32:
		if len(val) != 4 {
			return Value{}, fmt.Errorf("f32 takes exactly 4 bytes, got %d", len(val))
		}
		return bitsF32.decode(beUint(val), 32)
	case tlvF64:
		if len(val) != 8 {
			return Value{}, fmt.Errorf("f64 takes exactly 8 bytes, got %d", len(val))
		}
		return bitsF64.decode(beUint(val), 64)
	case tlvUTF8:
		if !utf8.Valid(val) {
			return Value{}, fmt.Errorf("the value is not UTF-8")
		}
		return Value{Kind: KindString, S: string(val)}, nil
	case tlvHex:
		return Value{Kind: KindString, S: hex.EncodeToString(val)}, nil
	}
	return Value{}, fmt.Errorf("no transform")
}

// emptyValue is the value of an empty item: the empty string under utf8 and
// hex; ok is false under every other transform, where it is absent (0.13
// ruling 1).
func (t *tlvTf) emptyValue() (Value, bool) {
	if t.kind == tlvUTF8 || t.kind == tlvHex {
		return Value{Kind: KindString, S: ""}, true
	}
	return Value{}, false
}

// encode writes a model value as the bytes of an item's value.
func (t *tlvTf) encode(v Value) ([]byte, error) {
	n := t.size
	switch t.kind {
	case tlvUint, tlvTwos:
		i, err := valueToInt(v)
		if err != nil {
			return nil, err
		}
		if n < 8 {
			bits := uint(8 * n)
			if t.kind == tlvUint && (i < 0 || i >= 1<<bits) {
				return nil, fmt.Errorf("%d does not fit an unsigned value of %d byte(s)", i, n)
			}
			if t.kind == tlvTwos && (i < -(1<<(bits-1)) || i >= 1<<(bits-1)) {
				return nil, fmt.Errorf("%d does not fit a two's-complement value of %d byte(s)", i, n)
			}
		}
		return putBE(uint64(i), n), nil
	case tlvUScale, tlvSScale:
		raw, err := t.scale.encode(v, 8*n)
		if err != nil {
			return nil, err
		}
		return putBE(raw, n), nil
	case tlvF32:
		raw, err := bitsF32.encode(v, 32)
		if err != nil {
			return nil, err
		}
		return putBE(raw, 4), nil
	case tlvF64:
		raw, err := bitsF64.encode(v, 64)
		if err != nil {
			return nil, err
		}
		return putBE(raw, 8), nil
	case tlvUTF8:
		s, err := encString(v)
		if err != nil {
			return nil, err
		}
		return []byte(s), nil
	case tlvHex:
		s, err := encString(v)
		if err != nil {
			return nil, err
		}
		if len(s)%2 != 0 || !isHex(s) {
			return nil, fmt.Errorf("%q is not hex text of an even number of digits", s)
		}
		b, err := hex.DecodeString(s)
		if err != nil {
			return nil, err
		}
		return b, nil
	}
	return nil, fmt.Errorf("no transform")
}

// --- load checks ---

// --- scope ---

// named reports whether a line of the scope names tag in this set.
func (s *tlvSet) named(tag uint64) bool {
	sl := s.byTag[tag]
	return sl != nil && sl.named
}

// --- decode ---

// tlvItem is one item of a set: its tag, its value, and where the value
// starts in the set.
type tlvItem struct {
	tag uint64
	val []byte
	at  int
}

func malformedTLV(p *Pack, format string, a ...any) error {
	return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: fmt.Sprintf(format, a...)}
}

// readTag reads a tag at b[i:]; it returns the tag and the next offset.
func (p *Pack) readTag(b []byte, i int) (uint64, int, error) {
	if n := p.tlv.tagN; n > 0 {
		if len(b)-i < n {
			return 0, 0, malformedTLV(p, "a tag of %d byte(s) runs past its set at byte %d", n, i)
		}
		return beUint(b[i : i+n]), i + n, nil
	}
	if i < len(b) && b[i] == 0x80 {
		return 0, 0, malformedTLV(p, "a BER-OID tag begins with 0x80 at byte %d", i)
	}
	var v uint64
	for k := 0; k < 4; k++ {
		if i+k >= len(b) {
			return 0, 0, malformedTLV(p, "a BER-OID tag runs past its set at byte %d", i)
		}
		c := b[i+k]
		v = v<<7 | uint64(c&0x7f)
		if c&0x80 == 0 {
			return v, i + k + 1, nil
		}
	}
	return 0, 0, malformedTLV(p, "a BER-OID tag of more than four bytes at byte %d", i)
}

// readLength reads a length at b[i:]; it returns the length and the next
// offset.
func (p *Pack) readLength(b []byte, i int) (uint64, int, error) {
	if n := p.tlv.lenN; n > 0 {
		if len(b)-i < n {
			return 0, 0, malformedTLV(p, "a length of %d byte(s) runs past its set at byte %d", n, i)
		}
		return beUint(b[i : i+n]), i + n, nil
	}
	if i >= len(b) {
		return 0, 0, malformedTLV(p, "a BER length runs past its set at byte %d", i)
	}
	c := b[i]
	switch {
	case c < 0x80:
		return uint64(c), i + 1, nil
	case c == 0x80 || c > 0x88:
		return 0, 0, malformedTLV(p, "a BER length begins with 0x%02x at byte %d", c, i)
	}
	k := int(c - 0x80)
	if len(b)-i-1 < k {
		return 0, 0, malformedTLV(p, "a BER length of %d byte(s) runs past its set at byte %d", k, i)
	}
	return beUint(b[i+1 : i+1+k]), i + 1 + k, nil
}

// parseTLVSet reads a set whole: its items, to its last byte.
func (p *Pack) parseTLVSet(b []byte) ([]tlvItem, error) {
	var items []tlvItem
	for i := 0; i < len(b); {
		tag, j, err := p.readTag(b, i)
		if err != nil {
			return nil, err
		}
		n, j, err := p.readLength(b, j)
		if err != nil {
			return nil, err
		}
		// The length is compared with the bytes left, never added first.
		if n > uint64(len(b)-j) {
			return nil, malformedTLV(p, "an item of tag %d states %d byte(s) of value with %d left in its set", tag, n, len(b)-j)
		}
		items = append(items, tlvItem{tag: tag, val: b[j : j+int(n)], at: j})
		i = j + int(n)
	}
	return items, nil
}

// firstOf is the first item of tag in items, nil when there is none.
func firstOf(items []tlvItem, tag uint64) *tlvItem {
	for k := range items {
		if items[k].tag == tag {
			return &items[k]
		}
	}
	return nil
}

// sum16 is the checksum of b: a byte at an even offset counts b*256, at an
// odd offset b, modulo 65536.
func sum16(b []byte) uint16 {
	var s uint16
	for i, c := range b {
		if i%2 == 0 {
			s += uint16(c) << 8
		} else {
			s += uint16(c)
		}
	}
	return s
}

// crc32MPEG is the CRC-32 of ISO/IEC 13818-1 (Annex A) over b: polynomial
// 0x04C11DB7, register from 0xFFFFFFFF, most significant bit first, no
// reflection and no final XOR (0.27, "The CRC").
func crc32MPEG(b []byte) uint32 {
	r := uint32(0xFFFFFFFF)
	for _, c := range b {
		r ^= uint32(c) << 24
		for i := 0; i < 8; i++ {
			if r&0x80000000 != 0 {
				r = r<<1 ^ 0x04C11DB7
			} else {
				r <<= 1
			}
		}
	}
	return r
}

// sumWidth is the size of the checksum item's value: 4 for crc32, 2 for
// sum16.
func (c *tlvConf) sumWidth() int {
	if c.crc {
		return 4
	}
	return 2
}

// checksumOf is the value of the checksum item over b, as big-endian bytes
// of sumWidth.
func (c *tlvConf) checksumOf(b []byte) []byte {
	if c.crc {
		v := crc32MPEG(b)
		return []byte{byte(v >> 24), byte(v >> 16), byte(v >> 8), byte(v)}
	}
	v := sum16(b)
	return []byte{byte(v >> 8), byte(v)}
}

// readTLVTop takes the input through steps 1 to 4 of "Reading a message" and
// returns the items of the top set, the checksum item removed.
func readTLVTop(p *Pack, b []byte) ([]tlvItem, error) {
	data, err := parseHexInput(p.Format, b)
	if err != nil {
		return nil, err
	}
	c := &p.tlv
	set, base := data, 0
	if c.hasKey {
		if !bytes.HasPrefix(data, c.key) {
			return nil, malformedTLV(p, "the input does not begin with the key %x", c.key)
		}
		n, j, err := p.readLength(data, len(c.key))
		if err != nil {
			return nil, err
		}
		if n > uint64(len(data)-j) {
			return nil, malformedTLV(p, "the set states %d byte(s) with %d left in the input", n, len(data)-j)
		}
		set, base = data[j:j+int(n)], j
	}
	items, err := p.parseTLVSet(set)
	if err != nil {
		return nil, err
	}
	if c.sum {
		if len(items) == 0 {
			return nil, malformedTLV(p, "the set has no checksum item of tag %d", c.sumTag)
		}
		last := items[len(items)-1]
		if last.tag != c.sumTag {
			return nil, malformedTLV(p, "the last item has tag %d, not the checksum tag %d", last.tag, c.sumTag)
		}
		if len(last.val) != c.sumWidth() {
			return nil, malformedTLV(p, "the checksum item has a value of %d byte(s), not %d", len(last.val), c.sumWidth())
		}
		items = items[:len(items)-1]
		for _, it := range items {
			if it.tag == c.sumTag {
				return nil, malformedTLV(p, "an item of the checksum tag %d stands before the last", c.sumTag)
			}
		}
		if got := c.checksumOf(data[:base+last.at]); !bytes.Equal(got, last.val) {
			return nil, malformedTLV(p, "checksum %x does not match the message's %x", last.val, got)
		}
	}
	return items, nil
}

// tlvLookup walks a path from the top set: the first occurrence of each tag,
// each value on the way read as a set. It returns nil when an item is not
// there, and an error when a value on the way is not a well-formed set.
func (p *Pack) tlvLookup(top []tlvItem, tags []uint64) (*tlvItem, error) {
	items := top
	for k, t := range tags {
		it := firstOf(items, t)
		if it == nil || k == len(tags)-1 {
			return it, nil
		}
		sub, err := p.parseTLVSet(it.val)
		if err != nil {
			return nil, err
		}
		items = sub
	}
	return nil, nil
}

// whenHoldsTLV reports whether a `when` holds on the top set.
func (p *Pack) whenHoldsTLV(w *When, top []tlvItem) bool {
	it, err := p.tlvLookup(top, w.loc.tags)
	if err != nil || it == nil {
		return false
	}
	if w.present {
		return true
	}
	return len(it.val) >= 1 && len(it.val) <= 8 && beUint(it.val) == w.num
}

// tlvRead is one set read for the selected scope: its items, and the nested
// sets of its walked-into items.
type tlvRead struct {
	items []tlvItem
	subs  map[uint64]*tlvRead
}

// readScope reads every nested set the scope walks into, whole: the first
// occurrence of each walked tag.
func (p *Pack) readScope(s *tlvSet, items []tlvItem) (*tlvRead, error) {
	r := &tlvRead{items: items}
	for _, sl := range s.slots {
		if sl.set == nil {
			continue
		}
		it := firstOf(items, sl.tag)
		if it == nil {
			continue
		}
		sub, err := p.parseTLVSet(it.val)
		if err != nil {
			return nil, err
		}
		sr, err := p.readScope(sl.set, sub)
		if err != nil {
			return nil, err
		}
		if r.subs == nil {
			r.subs = map[uint64]*tlvRead{}
		}
		r.subs[sl.tag] = sr
	}
	return r, nil
}

// residue keeps every item of a read set whose tag no line of the scope
// names there, every occurrence, in input order.
func (d *decodeState) tlvResidue(s *tlvSet, r *tlvRead, prefix string) {
	for _, it := range r.items {
		if s.named(it.tag) {
			continue
		}
		d.residue(prefix+strconv.FormatUint(it.tag, 10), hex.EncodeToString(it.val), false)
	}
	for _, sl := range s.slots {
		if sl.set == nil {
			continue
		}
		if sub := r.subs[sl.tag]; sub != nil {
			d.tlvResidue(sl.set, sub, prefix+strconv.FormatUint(sl.tag, 10)+".")
		}
	}
}

func decodeTLV(d *decodeState, b []byte) error {
	p := d.pack
	top, err := readTLVTop(p, b)
	if err != nil {
		return err
	}
	lay, err := d.choose(func(w *When) bool { return p.whenHoldsTLV(w, top) })
	if err != nil {
		return err
	}
	r, err := p.readScope(lay.tlv, top)
	if err != nil {
		return err
	}
	for _, ln := range lay.lines {
		f := ln.f
		if f == nil {
			continue
		}
		if _, done := d.rec.Fields[f.Key]; done {
			continue
		}
		set := r
		for _, t := range f.loc.tags[:len(f.loc.tags)-1] {
			if set = set.subs[t]; set == nil {
				break
			}
		}
		if set == nil {
			continue
		}
		it := firstOf(set.items, f.loc.tags[len(f.loc.tags)-1])
		if it == nil {
			continue
		}
		var v Value
		if len(it.val) == 0 {
			ev, ok := f.xtf.emptyValue()
			if !ok {
				continue
			}
			v = ev
		} else {
			v, err = f.xtf.decode(it.val)
			if err != nil {
				d.fail(f, err.Error())
				continue
			}
		}
		d.store(f, v)
	}
	d.tlvResidue(lay.tlv, r, "")
	return nil
}

// --- encode ---

// tlvResItem is one residue entry to write back into a set.
type tlvResItem struct {
	tag uint64
	val []byte
}

type tlvWriter struct {
	p   *Pack
	lay *layout
	rec *Item
	res map[string][]tlvResItem // the residue of this format, by the path of its set ("" for the top set)
}

func encodeTLVErr(p *Pack, loc string, format string, a ...any) error {
	return &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: loc, Detail: fmt.Sprintf(format, a...)}
}

// appendTag writes a tag in the pack's encoding.
func (w *tlvWriter) appendTag(out []byte, tag uint64, loc string) ([]byte, error) {
	if n := w.p.tlv.tagN; n > 0 {
		if n < 8 && tag>>(8*uint(n)) != 0 {
			return nil, encodeTLVErr(w.p, loc, "tag %d does not fit %d byte(s)", tag, n)
		}
		return append(out, putBE(tag, n)...), nil
	}
	if tag > maxTLVTag {
		return nil, encodeTLVErr(w.p, loc, "tag %d does not fit four BER-OID bytes", tag)
	}
	var groups [4]byte
	k := 0
	for {
		groups[k] = byte(tag & 0x7f)
		k++
		tag >>= 7
		if tag == 0 {
			break
		}
	}
	for i := k - 1; i >= 0; i-- {
		c := groups[i]
		if i > 0 {
			c |= 0x80
		}
		out = append(out, c)
	}
	return out, nil
}

// appendLength writes a length in the pack's encoding: under ber the short
// form below 128, else the long form with the fewest bytes.
func (w *tlvWriter) appendLength(out []byte, n int, loc string) ([]byte, error) {
	v := uint64(n)
	if k := w.p.tlv.lenN; k > 0 {
		if k < 8 && v>>(8*uint(k)) != 0 {
			return nil, encodeTLVErr(w.p, loc, "a length of %d does not fit %d byte(s)", n, k)
		}
		return append(out, putBE(v, k)...), nil
	}
	if v < 0x80 {
		return append(out, byte(v)), nil
	}
	k := 0
	for t := v; t > 0; t >>= 8 {
		k++
	}
	out = append(out, 0x80|byte(k))
	return append(out, putBE(v, k)...), nil
}

func (w *tlvWriter) appendItem(out []byte, tag uint64, val []byte, loc string) ([]byte, error) {
	out, err := w.appendTag(out, tag, loc)
	if err != nil {
		return nil, err
	}
	if out, err = w.appendLength(out, len(val), loc); err != nil {
		return nil, err
	}
	return append(out, val...), nil
}

// hasResidue reports whether the residue of the set at prefix holds an item
// of tag.
func (w *tlvWriter) hasResidue(prefix string, tag uint64) bool {
	for _, r := range w.res[prefix] {
		if r.tag == tag {
			return true
		}
	}
	return false
}

// set writes the items of one set: the slots of the scope in order, then the
// residue of the set in input order.
func (w *tlvWriter) set(s *tlvSet, prefix string) ([]byte, error) {
	var out []byte
	for _, sl := range s.slots {
		loc := prefix + strconv.FormatUint(sl.tag, 10)
		var val []byte
		has := false
		switch {
		case sl.set != nil:
			sub, err := w.set(sl.set, loc+".")
			if err != nil {
				return nil, err
			}
			// A nested set with no items is not written.
			val, has = sub, len(sub) > 0
		case sl.value != nil:
			// A `when` or `const` value is written once, at the first line's
			// position, whatever a field on the same path holds.
			val, has = putBE(sl.value.num, sl.value.loc.tsize), true
		default:
			for _, f := range sl.fields {
				v, ok, err := fieldValue(w.p, w.lay, f, w.rec)
				if err != nil {
					return nil, err
				}
				if !ok {
					continue
				}
				b, err := f.xtf.encode(v)
				if err != nil {
					return nil, encodeErr(w.p, f, err)
				}
				val, has = b, true
				break
			}
			// `when … present` writes an empty item, unless a line or the
			// residue of the set writes one at the path (0.13 ruling 2).
			if !has && sl.present && (sl.named || !w.hasResidue(prefix, sl.tag)) {
				val, has = []byte{}, true
			}
		}
		if !has {
			continue
		}
		var err error
		if out, err = w.appendItem(out, sl.tag, val, loc); err != nil {
			return nil, err
		}
	}
	for _, r := range w.res[prefix] {
		if s.named(r.tag) {
			continue
		}
		var err error
		if out, err = w.appendItem(out, r.tag, r.val, prefix+strconv.FormatUint(r.tag, 10)); err != nil {
			return nil, err
		}
	}
	return out, nil
}

// parseResiduePath reads the locator of a residue entry of a tlv format.
func (p *Pack) parseResiduePath(s string) ([]uint64, bool) {
	var tags []uint64
	for _, part := range strings.Split(s, ".") {
		t, ok := parseTLVTag(part, p.tlv.tagN)
		if !ok {
			return nil, false
		}
		tags = append(tags, t)
	}
	return tags, len(tags) > 0
}

func encodeTLV(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	w := &tlvWriter{p: p, lay: lay, rec: rec, res: map[string][]tlvResItem{}}
	for _, r := range ent.Residue {
		if r.Format != p.Format || r.JSON {
			continue
		}
		tags, ok := p.parseResiduePath(r.Locator)
		if !ok || (len(r.Value)%2 != 0) || !isHex(r.Value) {
			continue
		}
		val, err := hex.DecodeString(r.Value)
		if err != nil {
			continue
		}
		prefix := ""
		if len(tags) > 1 {
			prefix = pathKey(tags[:len(tags)-1]) + "."
		}
		w.res[prefix] = append(w.res[prefix], tlvResItem{tag: tags[len(tags)-1], val: val})
	}
	set, err := w.set(lay.tlv, "")
	if err != nil {
		return nil, err
	}
	c := &p.tlv
	if c.sum {
		if set, err = w.appendItem(set, c.sumTag, make([]byte, c.sumWidth()), strconv.FormatUint(c.sumTag, 10)); err != nil {
			return nil, err
		}
	}
	out := set
	if c.hasKey {
		out = append([]byte(nil), c.key...)
		if out, err = w.appendLength(out, len(set), ""); err != nil {
			return nil, err
		}
		out = append(out, set...)
	}
	if c.sum {
		n := c.sumWidth()
		copy(out[len(out)-n:], c.checksumOf(out[:len(out)-n]))
	}
	return []byte(hex.EncodeToString(out)), nil
}
