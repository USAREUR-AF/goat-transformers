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

// parseSixbitArmor reads armored text (spec 0.14): each character stands for
// six bits, first character first, most significant bit first; `0`..`W` for
// c - 0x30 and the backquote (0x60)..`w` for c - 0x38. Every character is checked before
// any line is read; any other character is malformed-wire. It returns the
// message, msb first in its bytes, and its length in bits.
func parseSixbitArmor(format string, b []byte) ([]byte, int, error) {
	nbits := 6 * len(b)
	data := make([]byte, (nbits+7)/8)
	for i, c := range b {
		var v byte
		switch {
		case c >= 0x30 && c <= 0x57:
			v = c - 0x30
		case c >= 0x60 && c <= 0x77:
			v = c - 0x38
		default:
			return nil, 0, &Error{Kind: ErrMalformedWire, Format: format, Detail: fmt.Sprintf("character %d (byte 0x%02x) is not a six-bit armor character", i, c)}
		}
		putBits(data, 6*i, 6, uint64(v), msbOrder)
	}
	return data, nbits, nil
}

// sixbitArmorText writes the first nbits bits of data (msb first) as armored
// text: zero bits up to the next multiple of 6, then each six bits as its
// character, values 0..39 as 0x30 + v and 40..63 as 0x38 + v.
func sixbitArmorText(data []byte, nbits int) []byte {
	out := make([]byte, 0, (nbits+5)/6)
	for at := 0; at < nbits; at += 6 {
		var v byte
		for k := 0; k < 6; k++ {
			v <<= 1
			if i := at + k; i < nbits && i/8 < len(data) {
				v |= byte(bitAt(data, i, msbOrder))
			}
		}
		if v < 40 {
			out = append(out, 0x30+v)
		} else {
			out = append(out, 0x38+v)
		}
	}
	return out
}

// decodeSixbit reads a sixbit field whose scope starts at bit base (spec
// 0.14): its six-bit characters first to last, each in the pack's bit order,
// values 0..31 as `@`.._ and 32..63 as space..`?`; trailing `@` removed, and
// with `trim` the whole trailing run of `@` and space.
func decodeSixbit(data []byte, f *Field, base int, msb bitOrder) Value {
	buf := make([]byte, f.loc.blen/6)
	for k := range buf {
		v := byte(getBits(data, base+f.loc.bit+6*k, 6, msb))
		if v < 32 {
			v += 0x40
		}
		buf[k] = v
	}
	n := len(buf)
	for n > 0 && (buf[n-1] == '@' || (f.Trim && buf[n-1] == ' ')) {
		n--
	}
	return Value{Kind: KindString, S: string(buf[:n])}
}

// encodeSixbit writes a sixbit field at message bit at: each character as its
// value, padded with `@` (0) to len / 6 characters.
func encodeSixbit(p *Pack, f *Field, v Value, data []byte, at int) error {
	s, err := encString(v)
	if err != nil {
		return encodeErr(p, f, err)
	}
	n := f.loc.blen / 6
	if len(s) > n {
		return encodeErr(p, f, fmt.Errorf("text is %d character(s), the field holds %d", len(s), n))
	}
	vals := make([]byte, n)
	for k := 0; k < len(s); k++ {
		c := s[k]
		if c < 0x20 || c > 0x5f {
			return encodeErr(p, f, fmt.Errorf("byte 0x%02x has no six-bit code", c))
		}
		if c >= 0x40 {
			c -= 0x40
		}
		vals[k] = c
	}
	for k, c := range vals {
		putBits(data, at+6*k, 6, uint64(c), p.msb)
	}
	return nil
}

// A bits locator <word>:<pos>:<len> addresses len bits starting at bit
// word*word_bytes*8 + pos of the message (locator.bit); a field may run past
// the end of its word. With bit_order lsb, bit i of the message is bit i%8 of
// byte i/8 and a field's first bit is its least significant. With msb, bit i
// is bit 7-i%8 of byte i/8 and a field's first bit is its most significant.

// bitAt reads message bit i.
func bitAt(data []byte, i int, o bitOrder) uint64 {
	if o != lsbOrder {
		return uint64(data[i/8]>>uint(7-i%8)) & 1
	}
	return uint64(data[i/8]>>uint(i%8)) & 1
}

// bitOrder is the bit order of a bits pack: where bit i of a word lies, and
// in which order a field's bits make its value.
type bitOrder uint8

const (
	// lsbOrder: bit i is bit i mod 8 of its byte; the first bit is the
	// value's least significant.
	lsbOrder bitOrder = iota
	// msbOrder: bit i is bit 7 - i mod 8 of its byte; the first bit is the
	// value's most significant.
	msbOrder
	// msbLsbOrder: positions as msb, values as lsb (spec 0.22).
	msbLsbOrder
)

// getBits reads length (1..64) bits from message bit start.
func getBits(data []byte, start, length int, o bitOrder) uint64 {
	var v uint64
	for k := 0; k < length; k++ {
		if o == msbOrder {
			v = v<<1 | bitAt(data, start+k, o)
		} else {
			v |= bitAt(data, start+k, o) << uint(k)
		}
	}
	return v
}

// putBits writes the low length (1..64) bits of v at message bit start,
// replacing what is there.
func putBits(data []byte, start, length int, v uint64, o bitOrder) {
	for k := 0; k < length; k++ {
		i := start + k
		var bit byte
		if o == msbOrder {
			bit = byte(v>>uint(length-1-k)) & 1
		} else {
			bit = byte(v>>uint(k)) & 1
		}
		mask := byte(1) << uint(i%8)
		if o != lsbOrder {
			mask = 1 << uint(7-i%8)
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
func decodeASCII(data []byte, f *Field, base int, msb bitOrder) (Value, error) {
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
	var data []byte
	var bits int
	var err error
	if p.sixbitArmor {
		data, bits, err = parseSixbitArmor(p.Format, b)
	} else {
		data, err = parseHexInput(p.Format, b)
		bits = len(data) * 8
	}
	if err != nil {
		return err
	}
	d.nbits = bits
	if p.seq {
		return decodeSeq(d, data, bits)
	}
	// A when any of whose bits lies beyond the input does not hold.
	lay, err := d.choose(func(w *When) bool {
		if w.loc.bit+w.loc.blen > bits {
			return false
		}
		return w.matchNum(getBits(data, w.loc.bit, w.loc.blen, p.msb))
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
	if p.sixbitArmor {
		// Armored text is any number of bits: it must reach every bit of the
		// lines that are not optional, and the group items (checked as they
		// are read); whole words are not required (spec 0.14).
		if bits < lay.needBit {
			return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: fmt.Sprintf("message is %d bit(s), the format needs at least %d", bits, lay.needBit)}
		}
		_, err := d.bitsScope(lay, data, 0)
		return err
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
	bits := d.nbits
	end := 0
	// A line of a gate block that does not hold sets no key: decode goes on
	// to the key's next line (0.17, Decode).
	holds := gateEval(data, bits, base, p.msb)
	for _, ln := range lay.lines {
		if ln.in != nil && !holds(ln.in) {
			continue
		}
		switch {
		case ln.w != nil && ln.in != nil:
			// A held block's const counts toward the length.
			if w := ln.w; base+w.loc.bit+w.loc.blen > bits {
				return 0, &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: w.Locator, Detail: fmt.Sprintf("message is %d byte(s) and does not reach the const of a held gate block (line %d)", len(data), w.Line)}
			}
		case ln.f != nil:
			f := ln.f
			at := base + f.loc.bit
			if at+f.loc.blen > bits {
				if f.Optional {
					continue
				}
				return 0, &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: f.Locator, Detail: fmt.Sprintf("message is %d bit(s) and does not reach field %s", bits, f.Key)}
			}
			// A sentinel is read before any transform, `sixbit` and `ascii`
			// included (0.9 ruling 2, 0.14 ruling 12).
			if f.bitsSentinel(data, at, p.msb) {
				continue
			}
			if f.btf.sixbit {
				d.store(f, decodeSixbit(data, f, base, p.msb))
				continue
			}
			if f.btf.decodeAt != nil {
				v, err := f.btf.decodeAt(data, at, f.loc.blen, p.msb)
				if err != nil {
					d.fail(f, err.Error())
					continue
				}
				d.store(f, v)
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
				return &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: g.Locator, Detail: fmt.Sprintf("list %s: message is %d bit(s) and %s", g.List, bits, detail)}
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
	if f.btf.sixbit {
		return encodeSixbit(p, f, v, data, at)
	}
	if f.btf.encodeAt != nil {
		if err := f.btf.encodeAt(v, data, at, f.loc.blen, p.msb); err != nil {
			return encodeErr(p, f, err)
		}
		return nil
	}
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
type bitBuf struct {
	data   []byte
	checks []func([]byte, int) error // the step 6 checks of the scopes with gate blocks (0.17), on the output and its length in bits
}

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
	end, check, err := encodeBitsScope(p, lay, rec, buf, 0)
	if err != nil {
		return nil, err
	}
	if p.sixbitArmor {
		// The armored text is the first L bits (spec 0.14): one more than the
		// highest bit of any line of the scope or of its group items, except
		// an optional field with no value to write.
		l, err := armorLength(p, lay, rec, end)
		if err != nil {
			return nil, err
		}
		buf.need(l)
		// Step 6 of 0.17 decodes the output as it will be read: L rounded
		// up to a multiple of 6 bits, padded with zeros (0.17 ruling 14).
		if check != nil {
			buf.checks = append(buf.checks, check)
		}
		if len(buf.checks) > 0 {
			nb := (l + 5) / 6 * 6
			out := make([]byte, (nb+7)/8)
			for i := 0; i < l; i++ {
				if bitAt(buf.data, i, msbOrder) != 0 {
					out[i/8] |= 0x80 >> uint(i%8)
				}
			}
			for _, c := range buf.checks {
				if err := c(out, nb); err != nil {
					return nil, err
				}
			}
		}
		return sixbitArmorText(buf.data, l), nil
	}
	if lay.maxBit > end {
		end = lay.maxBit
	}
	n := p.wholeWords(end)
	buf.need(n * 8)
	// Step 6 of 0.17 is checked once, on the final output, for the message
	// and every item (ruling 9), the items first as they were written.
	if check != nil {
		buf.checks = append(buf.checks, check)
	}
	for _, c := range buf.checks {
		if err := c(buf.data[:n], n*8); err != nil {
			return nil, err
		}
	}
	return []byte(hex.EncodeToString(buf.data[:n])), nil
}

// armorLength is the length L in bits of the armored text an encode of a
// fixed-layout scope writes: the furthest bit of its field, when and const
// lines, counts and group items (end, the furthest bit the items reach), an
// optional field counting only when it has a value or a default to write, or
// a sentinel (`absent`, 0.9) to write when its key is absent (0.14 ruling 12).
func armorLength(p *Pack, lay *layout, rec *Item, end int) (int, error) {
	l := end
	for _, ln := range lay.lines {
		// A gate and the lines of a gate block count only when the block is
		// held; end already holds them (0.17 ruling 14).
		if ln.gt != nil || ln.in != nil {
			continue
		}
		var loc locator
		switch {
		case ln.f != nil:
			w, err := armorWrites(p, lay, ln.f, rec)
			if err != nil {
				return 0, err
			}
			if !w {
				continue
			}
			loc = ln.f.loc
		case ln.w != nil:
			loc = ln.w.loc
		case ln.g != nil:
			g := ln.g
			e := g.start + g.countN*g.itemBits
			if g.countLoc != nil {
				e = g.countLoc.bit + g.countLoc.blen
			}
			if e > l {
				l = e
			}
			continue
		}
		if e := loc.bit + loc.blen; e > l {
			l = e
		}
	}
	return l, nil
}

// encodeBitsScope writes the lines of one scope whose first bit is message
// bit base, and returns the furthest bit the items of its groups reach.
//
// A scope with gate blocks is written by encodeGatedScope; the check it
// returns is run on the final output (0.17 ruling 9).
func encodeBitsScope(p *Pack, lay *layout, rec *Item, buf *bitBuf, base int) (int, func([]byte, int) error, error) {
	buf.need(base + lay.allBit)
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
				return 0, nil, gerr("the list is absent and the group has the fixed count %d", g.countN)
			}
			if len(items) != g.countN {
				return 0, nil, gerr("the list has %d item(s) and the group has the fixed count %d", len(items), g.countN)
			}
		} else if c.blen < 64 && uint64(len(items))>>uint(c.blen) != 0 {
			return 0, nil, gerr("%d item(s) do not fit the %d-bit count", len(items), c.blen)
		}
		pos := base + g.start
		for _, it := range items {
			buf.need(pos + g.itemBits)
			itemEnd, check, err := encodeBitsScope(p, g.body, it, buf, pos)
			if err != nil {
				return 0, nil, err
			}
			if check != nil {
				buf.checks = append(buf.checks, check)
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
	if len(lay.gates) > 0 {
		heldEnd, check, err := encodeGatedScope(p, lay, rec, buf, base)
		if err != nil {
			return 0, nil, err
		}
		if heldEnd > end {
			end = heldEnd
		}
		return end, check, nil
	}
	all := func(line) bool { return true }
	if err := writeBitsLines(p, lay, rec, buf.data, base, all, nil, nil); err != nil {
		return 0, nil, err
	}
	return end, nil, nil
}

// bitsSentinel reports whether the field at message bit at holds one of its
// sentinels: its len bits read as an unsigned integer, after `swap`, before
// `trim` and the transform (0.9 ruling 2).
func (f *Field) bitsSentinel(data []byte, at int, msb bitOrder) bool {
	if f.absent == nil {
		return false
	}
	raw := getBits(data, at, f.loc.blen, msb)
	if f.Swap {
		raw = swapBytes(raw, f.loc.blen/8)
	}
	return f.sentinelNum(raw)
}

// armorWrites reports whether a field counts toward the armored length L: a
// field that is not optional always does; an optional one when it has a
// value or a default to write, or a sentinel (0.14 ruling 12).
func armorWrites(p *Pack, lay *layout, f *Field, rec *Item) (bool, error) {
	// An optional field that `with` suppresses is not written and does not
	// count, its sentinel included; a suppressed line that is not optional
	// writes zero bits and counts (0.18 rulings 1 and 23).
	if f.Optional && f.suppressed(rec) {
		return false, nil
	}
	if !f.Optional || f.absent != nil {
		return true, nil
	}
	_, ok, err := fieldValue(p, lay, f, rec)
	return ok, err
}
