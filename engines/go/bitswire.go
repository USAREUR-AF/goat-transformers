package goatxf

import (
	"encoding/hex"
	"fmt"
	"strings"
)

// parseHexInput reads the hex text a bits wire takes: whitespace ignored, even
// number of digits (spec/engine-spec.md, "I/O and canonicalisation").
func parseHexInput(format string, b []byte) ([]byte, error) {
	var sb strings.Builder
	for _, c := range b {
		if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
			continue
		}
		sb.WriteByte(c)
	}
	s := sb.String()
	if len(s)%2 != 0 {
		return nil, &Error{Kind: ErrMalformedWire, Format: format, Detail: "hex input has an odd number of digits"}
	}
	out, err := hex.DecodeString(s)
	if err != nil {
		return nil, &Error{Kind: ErrMalformedWire, Format: format, Detail: "input is not hex: " + err.Error()}
	}
	return out, nil
}

// A bits locator <word>:<pos>:<len> addresses len bits starting at bit
// word*word_bytes*8 + pos of the message (locator.bit); a field may run past
// the end of its word. With bit_order lsb, bit i of the message is bit i%8 of
// byte i/8 and a field's first bit is its least significant. With msb, bit i
// is bit 7-i%8 of byte i/8 and a field's first bit is its most significant.

// bitAt reads message bit i.
func bitAt(data []byte, i int, msb bool) uint64 {
	if msb {
		return uint64(data[i/8]>>uint(7-i%8)) & 1
	}
	return uint64(data[i/8]>>uint(i%8)) & 1
}

// getBits reads length (1..64) bits from message bit start.
func getBits(data []byte, start, length int, msb bool) uint64 {
	var v uint64
	for k := 0; k < length; k++ {
		if msb {
			v = v<<1 | bitAt(data, start+k, true)
		} else {
			v |= bitAt(data, start+k, false) << uint(k)
		}
	}
	return v
}

// putBits writes the low length (1..64) bits of v at message bit start,
// replacing what is there.
func putBits(data []byte, start, length int, v uint64, msb bool) {
	for k := 0; k < length; k++ {
		i := start + k
		var bit, mask byte
		if msb {
			bit, mask = byte(v>>uint(length-1-k))&1, 1<<uint(7-i%8)
		} else {
			bit, mask = byte(v>>uint(k))&1, 1<<uint(i%8)
		}
		if bit == 1 {
			data[i/8] |= mask
		} else {
			data[i/8] &^= mask
		}
	}
}

// swapBytes reverses the n low bytes of v.
func swapBytes(v uint64, n int) uint64 {
	var out uint64
	for k := 0; k < n; k++ {
		out = out<<8 | (v>>(8*uint(k)))&0xff
	}
	return out
}

func reverseBytes(b []byte) {
	for i, j := 0, len(b)-1; i < j; i, j = i+1, j-1 {
		b[i], b[j] = b[j], b[i]
	}
}

// decodeASCII reads an ascii field whose scope starts at bit base: its bytes
// first to last (last to first with `swap`), trailing NUL bytes removed, then
// with `trim` trailing spaces removed. A remaining byte below 0x20 or above
// 0x7E is an error.
func decodeASCII(data []byte, f *Field, base int, msb bool) (Value, error) {
	buf := make([]byte, f.loc.blen/8)
	for k := range buf {
		buf[k] = byte(getBits(data, base+f.loc.bit+8*k, 8, msb))
	}
	if f.Swap {
		reverseBytes(buf)
	}
	n := len(buf)
	for n > 0 && buf[n-1] == 0 {
		n--
	}
	if f.Trim {
		for n > 0 && buf[n-1] == 0x20 {
			n--
		}
	}
	for _, c := range buf[:n] {
		if c < 0x20 || c > 0x7e {
			return Value{}, fmt.Errorf("byte 0x%02x is not printable ASCII", c)
		}
	}
	return Value{Kind: KindString, S: string(buf[:n])}, nil
}

func decodeBits(d *decodeState, b []byte) error {
	p := d.pack
	data, err := parseHexInput(p.Format, b)
	if err != nil {
		return err
	}
	if p.seq {
		return decodeSeq(d, data)
	}
	bits := len(data) * 8
	// A when any of whose bits lies beyond the input does not hold.
	lay, err := d.choose(func(w *When) bool {
		if w.loc.bit+w.loc.blen > bits {
			return false
		}
		return getBits(data, w.loc.bit, w.loc.blen, p.msb) == w.num
	})
	if err != nil {
		return err
	}
	// Longer input is accepted and the extra bytes ignored; input that does
	// not reach every mapped bit is malformed. A field marked `optional` does
	// not count: one any of whose bits lies beyond the input is absent.
	short := func(need int) error {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: fmt.Sprintf("message is %d byte(s), the format needs at least %d", len(data), need)}
	}
	if len(data) < lay.decBytes {
		return short(lay.decBytes)
	}
	end, err := d.bitsScope(lay, data, 0)
	if err != nil {
		return err
	}
	// The items of the groups extend the message: whole words up to the
	// furthest bit they reach.
	if need := p.wholeWords(end); len(data) < need {
		return short(need)
	}
	return nil
}

// bitsScope decodes the lines of one scope whose first bit is message bit
// base: the message (base 0), or one item of a group. It returns the furthest
// bit the items of the scope's groups reach. A group has `count` items, read
// back to back from its start; an item is `item <bits>` long, or ends where a
// nested group counted by a locator ends when that is further (0.7 ruling 4).
func (d *decodeState) bitsScope(lay *layout, data []byte, base int) (int, error) {
	p := d.pack
	bits := len(data) * 8
	end := 0
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			at := base + f.loc.bit
			if at+f.loc.blen > bits {
				if f.Optional {
					continue
				}
				return 0, &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: f.Locator, Detail: fmt.Sprintf("message is %d byte(s) and does not reach field %s", len(data), f.Key)}
			}
			if f.bitsSentinel(data, at, p.msb) {
				continue
			}
			if f.btf.ascii {
				v, err := decodeASCII(data, f, base, p.msb)
				if err != nil {
					d.fail(f, err.Error())
					continue
				}
				d.store(f, v)
				continue
			}
			raw := getBits(data, at, f.loc.blen, p.msb)
			if f.Swap {
				raw = swapBytes(raw, f.loc.blen/8)
			}
			v, err := f.btf.decode(raw, f.loc.blen)
			if err != nil {
				d.fail(f, err.Error())
				continue
			}
			d.store(f, v)
		case ln.g != nil:
			g := ln.g
			bad := func(detail string) error {
				return &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: g.Locator, Detail: fmt.Sprintf("list %s: message is %d byte(s) and %s", g.List, len(data), detail)}
			}
			count := uint64(g.countN)
			if c := g.countLoc; c != nil {
				if base+c.bit+c.blen > bits {
					return 0, bad("does not reach the count of items")
				}
				count = getBits(data, base+c.bit, c.blen, p.msb)
			}
			pos := base + g.start
			// A count larger than the bits left is refused before any item
			// is read (0.8 ruling 14).
			if count > 0 && (pos > bits || count > uint64(bits-pos)) {
				return 0, bad(fmt.Sprintf("holds no %d item(s) from bit %d", count, pos))
			}
			if err := d.room(g.List, count); err != nil {
				return 0, err
			}
			items := []*Item{}
			for i := uint64(0); i < count; i++ {
				if pos+g.itemBits > bits {
					return 0, bad(fmt.Sprintf("does not reach item %d of %d", i, count))
				}
				itemEnd := 0
				it, err := d.item(func() error {
					var err error
					itemEnd, err = d.bitsScope(g.body, data, pos)
					return err
				})
				if err != nil {
					return 0, err
				}
				items = append(items, it)
				pos += g.itemBits
				if itemEnd > pos {
					pos = itemEnd
				}
			}
			d.rec.SetList(g.List, items)
			if pos > end {
				end = pos
			}
		}
	}
	return end, nil
}

// putBitsField writes the value of one field at message bit at, through the
// field's transform and its `swap` option.
func putBitsField(p *Pack, f *Field, v Value, data []byte, at int) error {
	if f.btf.ascii {
		s, err := encString(v)
		if err != nil {
			return encodeErr(p, f, err)
		}
		n := f.loc.blen / 8
		if len(s) > n {
			return encodeErr(p, f, fmt.Errorf("text is %d byte(s), the field holds %d", len(s), n))
		}
		b := make([]byte, n)
		for k := 0; k < len(s); k++ {
			if s[k] < 0x20 || s[k] > 0x7e {
				return encodeErr(p, f, fmt.Errorf("byte 0x%02x is not printable ASCII", s[k]))
			}
			b[k] = s[k]
		}
		if f.Swap {
			reverseBytes(b)
		}
		for k, c := range b {
			putBits(data, at+8*k, 8, uint64(c), p.msb)
		}
		return nil
	}
	raw, err := f.btf.encode(v, f.loc.blen)
	if err != nil {
		return encodeErr(p, f, err)
	}
	if f.Swap {
		raw = swapBytes(raw, f.loc.blen/8)
	}
	putBits(data, at, f.loc.blen, raw, p.msb)
	return nil
}

// bitBuf is the message an encode writes: it grows as the items of counted
// groups are written. New bits are zero.
type bitBuf struct{ data []byte }

// need makes the buffer hold at least bits bits.
func (b *bitBuf) need(bits int) {
	if n := (bits + 7) / 8; n > len(b.data) {
		b.data = append(b.data, make([]byte, n-len(b.data))...)
	}
}

// encodeBits writes the layout's lists, its fields that have a value, then
// its when and const values and the counts of its groups. Where two written
// fields cover the same bits the earlier line's value stays, so the fields
// are written last line first; a when or const value is written over any
// field. Bits no line covers are zero. The message is whole words up to the
// furthest bit written.
func encodeBits(p *Pack, lay *layout, rec *Item) ([]byte, error) {
	buf := &bitBuf{}
	end, err := encodeBitsScope(p, lay, rec, buf, 0)
	if err != nil {
		return nil, err
	}
	if lay.maxBit > end {
		end = lay.maxBit
	}
	n := p.wholeWords(end)
	buf.need(n * 8)
	return []byte(hex.EncodeToString(buf.data[:n])), nil
}

// encodeBitsScope writes the lines of one scope whose first bit is message
// bit base, and returns the furthest bit the items of its groups reach.
func encodeBitsScope(p *Pack, lay *layout, rec *Item, buf *bitBuf, base int) (int, error) {
	buf.need(base + lay.maxBit)
	end := 0
	for _, g := range lay.groups {
		items, present := rec.Lists[g.List]
		gerr := func(format string, a ...any) error {
			return &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: g.Locator, Detail: "list " + g.List + ": " + fmt.Sprintf(format, a...)}
		}
		if c := g.countLoc; c == nil {
			// A fixed count needs the list, with exactly that many items
			// (0.7 ruling 5: an absent list is an error too).
			if !present {
				return 0, gerr("the list is absent and the group has the fixed count %d", g.countN)
			}
			if len(items) != g.countN {
				return 0, gerr("the list has %d item(s) and the group has the fixed count %d", len(items), g.countN)
			}
		} else if c.blen < 64 && uint64(len(items))>>uint(c.blen) != 0 {
			return 0, gerr("%d item(s) do not fit the %d-bit count", len(items), c.blen)
		}
		pos := base + g.start
		for _, it := range items {
			buf.need(pos + g.itemBits)
			itemEnd, err := encodeBitsScope(p, g.body, it, buf, pos)
			if err != nil {
				return 0, err
			}
			pos += g.itemBits
			if itemEnd > pos {
				pos = itemEnd
			}
		}
		if pos > end {
			end = pos
		}
	}
	data := buf.data
	// A sentinel is a field write that any line whose key is present, or has
	// a default, writes over whatever their order (0.9 ruling 16).
	for i := len(lay.lines) - 1; i >= 0; i-- {
		if f := lay.lines[i].f; f != nil && f.writesSentinel(rec, lay.defaults) {
			putBits(data, base+f.loc.bit, f.loc.blen, f.sentinelBits(), p.msb)
		}
	}
	for i := len(lay.lines) - 1; i >= 0; i-- {
		f := lay.lines[i].f
		if f == nil {
			continue
		}
		v, ok, err := fieldValue(p, lay, f, rec)
		if err != nil {
			return 0, err
		}
		if !ok {
			continue
		}
		if err := putBitsField(p, f, v, data, base+f.loc.bit); err != nil {
			return 0, err
		}
	}
	// Over the same bits the order of writes is fields, then const, then
	// when, then counts (0.7 ruling 15).
	for _, ln := range lay.lines {
		if w := ln.w; w != nil && w.Const {
			putBits(data, base+w.loc.bit, w.loc.blen, w.num, p.msb)
		}
	}
	for _, ln := range lay.lines {
		if w := ln.w; w != nil && !w.Const {
			putBits(data, base+w.loc.bit, w.loc.blen, w.num, p.msb)
		}
	}
	// The count of a group counted by a locator is the number of items,
	// written over any field on its bits (0.7 ruling 2).
	for _, g := range lay.groups {
		if c := g.countLoc; c != nil {
			putBits(data, base+c.bit, c.blen, uint64(len(rec.Lists[g.List])), p.msb)
		}
	}
	return end, nil
}

// bitsSentinel reports whether the field at message bit at holds one of its
// sentinels: its len bits read as an unsigned integer, after `swap`, before
// `trim` and the transform (0.9 ruling 2).
func (f *Field) bitsSentinel(data []byte, at int, msb bool) bool {
	if f.absent == nil {
		return false
	}
	raw := getBits(data, at, f.loc.blen, msb)
	if f.Swap {
		raw = swapBytes(raw, f.loc.blen/8)
	}
	return f.sentinelNum(raw)
}
