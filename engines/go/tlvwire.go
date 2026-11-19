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
// checksum item. Input and output are hex text.

// maxTLVTag is the largest tag a path names: 2^28-1, four BER-OID bytes.
const maxTLVTag = 1<<28 - 1

// tlvConf is what the directives of a tlv pack state.
type tlvConf struct {
	tagN    int // 0: ber-oid; else 1, 2 or 4 bytes
	lenN    int // 0: ber; else 1, 2 or 4 bytes
	key     []byte
	hasKey  bool
	sum     bool   // `checksum sum16 <tag>`
	sumText string // the tag of the checksum, as written
	sumTag  uint64

	lines map[string]int // the line of each tlv directive the pack has: tag, length, key, checksum
	err   error          // the first failure of a tlv directive, reported after the file is read
}

// tlvDirective reads one `tag`, `length` (one argument, outside a sequential
// pack), `key` or `checksum sum16 …` line. Its failures are bad-directive and
// are reported after the file is read, before missing-distribution (0.13,
// and ruling 2 of 0.10).
func (p *Pack) tlvDirective(kw string, args []string, line int) {
	c := &p.tlv
	if c.lines == nil {
		c.lines = map[string]int{}
	}
	fail := func(format string, a ...any) {
		if c.err == nil {
			c.err = &Error{Kind: ErrBadDirective, Format: p.Format, Source: p.Source, Line: line, Detail: fmt.Sprintf(format, a...)}
		}
	}
	prev, dup := c.lines[kw]
	if kw == "checksum" && !dup {
		prev, dup = p.textSeen["checksum"]
	}
	if dup {
		fail("%s repeated (first on line %d)", kw, prev)
		return
	}
	c.lines[kw] = line
	if len(p.Kinds) > 0 {
		fail("%s must stand before the first kind line", kw)
		return
	}
	switch kw {
	case "tag", "length":
		other := "ber-oid"
		if kw == "length" {
			other = "ber"
		}
		n := 0
		switch args[0] {
		case other:
		case "1", "2", "4":
			n = int(args[0][0] - '0')
		default:
			fail("%s is %s, 1, 2 or 4, got %q", kw, other, args[0])
			return
		}
		if kw == "tag" {
			c.tagN = n
		} else {
			c.lenN = n
		}
	case "key":
		k := args[0]
		if len(k) < 2 || len(k) > 128 || len(k)%2 != 0 || !isLowerHex(k) {
			fail("key is 1 to 64 bytes as an even number of lowercase hex digits, got %q", k)
			return
		}
		c.key, _ = hex.DecodeString(k)
		c.hasKey = true
	case "checksum":
		if len(args) != 2 {
			fail("checksum sum16 takes a tag: `checksum sum16 <tag>`")
			return
		}
		c.sum, c.sumText = true, args[1]
	}
}

func isLowerHex(s string) bool {
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f') {
			return false
		}
	}
	return true
}

// checkTLVDirectives runs after the file is read: the failures found while
// reading the tlv directives, then a tlv directive on another wire, then the
// checksum tag. It returns the line at fault.
func (p *Pack) checkTLVDirectives() (int, error) {
	c := &p.tlv
	if c.err != nil {
		e := c.err.(*Error)
		return e.Line, fmt.Errorf("%s", e.Detail)
	}
	if p.Wire != WireTLV {
		for _, kw := range []string{"tag", "length", "key", "checksum"} {
			if ln, has := c.lines[kw]; has {
				return ln, fmt.Errorf("%s is valid only on wire tlv", kw)
			}
		}
		return 0, nil
	}
	if c.sum {
		t, ok := parseTLVTag(c.sumText, c.tagN)
		if !ok {
			return c.lines["checksum"], fmt.Errorf("the checksum tag is a decimal integer from 0 to 2^28-1 with no leading zero%s, got %q", tagFitText(c.tagN), c.sumText)
		}
		c.sumTag = t
	}
	return 0, nil
}

func tagFitText(n int) string {
	if n == 0 {
		return ""
	}
	return fmt.Sprintf(" and below 2^%d under tag %d", 8*n, n)
}

// parseTLVTag reads one tag of a path: a decimal integer from 0 to 2^28-1
// with no leading zero, below 2^(8n) under a fixed `tag <n>`.
func parseTLVTag(s string, tagN int) (uint64, bool) {
	if !isDigits(s) || len(s) > 9 || (len(s) > 1 && s[0] == '0') {
		return 0, false
	}
	v, err := strconv.ParseUint(s, 10, 64)
	if err != nil || v > maxTLVTag {
		return 0, false
	}
	if tagN > 0 && tagN < 4 && v >= 1<<(8*uint(tagN)) {
		return 0, false
	}
	return v, true
}

// parseTLVLocator reads `<tag>[.<tag>…][:<n>]`; size is 0 when there is no
// `:<n>`.
func parseTLVLocator(s string, tagN int) (locator, error) {
	l := locator{raw: s, kind: locTLV}
	path, size, hasSize := strings.Cut(s, ":")
	if hasSize {
		// One digit from 1 to 8 (0.13 ruling 6).
		if len(size) != 1 || size[0] < '1' || size[0] > '8' {
			return l, fmt.Errorf("a size is one digit from 1 to 8, got %q", size)
		}
		l.tsize = int(size[0] - '0')
	}
	for _, part := range strings.Split(path, ".") {
		t, ok := parseTLVTag(part, tagN)
		if !ok {
			return l, fmt.Errorf("a tlv path is tags separated by '.', each a decimal integer from 0 to 2^28-1 with no leading zero%s, got %q", tagFitText(tagN), s)
		}
		l.tags = append(l.tags, t)
	}
	return l, nil
}

// pathKey is the text of tags, as residue names a path.
func pathKey(tags []uint64) string {
	var b strings.Builder
	for i, t := range tags {
		if i > 0 {
			b.WriteByte('.')
		}
		b.WriteString(strconv.FormatUint(t, 10))
	}
	return b.String()
}

// --- transforms ---

const (
	tlvUint = iota + 1
	tlvTwos
	tlvUScale
	tlvSScale
	tlvF32
	tlvF64
	tlvUTF8
	tlvHex
)

// tlvTf is a transform of the tlv wire.
type tlvTf struct {
	kind  int
	size  int            // n of `:<n>`; 4 for f32 and 8 for f64
	scale *bitsTransform // uscale and sscale
}

// resolveTLVTransform reads the transform of a field line of a tlv pack
// against the size its path states. Every failure is bad-directive.
func resolveTLVTransform(name string, size int) (*tlvTf, error) {
	t := &tlvTf{size: size}
	needSize := false
	switch {
	case name == "uint":
		t.kind, needSize = tlvUint, true
	case name == "twos":
		t.kind, needSize = tlvTwos, true
	case strings.HasPrefix(name, "uscale:"), strings.HasPrefix(name, "sscale:"):
		signed := name[0] == 's'
		bt, err := newScale(name, signed)
		if err != nil {
			return nil, err
		}
		t.kind, t.scale, needSize = tlvUScale, bt, true
		if signed {
			t.kind = tlvSScale
		}
	case name == "f32", name == "f64":
		want := 4
		t.kind = tlvF32
		if name == "f64" {
			want, t.kind = 8, tlvF64
		}
		if size != 0 && size != want {
			return nil, fmt.Errorf("%s takes no size or :%d, got :%d", name, want, size)
		}
		t.size = want
		return t, nil
	case name == "utf8", name == "hex":
		t.kind = tlvUTF8
		if name == "hex" {
			t.kind = tlvHex
		}
		if size != 0 {
			return nil, fmt.Errorf("%s takes no size, got :%d", name, size)
		}
		return t, nil
	default:
		return nil, fmt.Errorf("transform %q is not valid on wire tlv (uint, twos, uscale, sscale, f32, f64, utf8, hex)", name)
	}
	if needSize && size == 0 {
		return nil, fmt.Errorf("%s needs a size :<n> from 1 to 8 after the path", name)
	}
	return t, nil
}

// beUint reads 1 to 8 bytes as an unsigned big-endian integer.
func beUint(b []byte) uint64 {
	var v uint64
	for _, c := range b {
		v = v<<8 | uint64(c)
	}
	return v
}

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

// resolveTLV reads the paths, sizes and transforms of a tlv pack and runs the
// checks of 0.13 that need the whole file. Every failure is bad-directive.
func (p *Pack) resolveTLV(whens []*When, perr perrFunc) error {
	c := &p.tlv
	if len(p.Groups) > 0 {
		g := p.Groups[0]
		return perr(ErrBadDirective, g.Line, g.Locator, "group is not valid on wire tlv in 0.13")
	}
	onChecksum := func(l *locator) bool { return c.sum && len(l.tags) > 0 && l.tags[0] == c.sumTag }
	for _, f := range p.Fields {
		loc, err := parseTLVLocator(f.Locator, c.tagN)
		if err != nil {
			return perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
		}
		f.loc = loc
		if onChecksum(&f.loc) {
			return perr(ErrBadDirective, f.Line, f.Locator, "the first tag of the path is the checksum tag %d", c.sumTag)
		}
		tf, err := resolveTLVTransform(f.Transform, loc.tsize)
		if err != nil {
			return perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
		}
		f.xtf = tf
		for _, o := range []struct {
			set  bool
			name string
		}{{f.Swap, "swap"}, {f.Trim, "trim"}, {f.Optional, "optional"}, {f.Absent != nil, "absent"}} {
			if o.set {
				// `absent` (0.9) on tlv is bad-directive (0.13 ruling 10).
				return perr(ErrBadDirective, f.Line, f.Locator, "field option `%s` is not valid on wire tlv", o.name)
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
		loc, err := parseTLVLocator(w.Locator, c.tagN)
		if err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
		}
		w.loc = loc
		if onChecksum(&w.loc) {
			return perr(ErrBadDirective, w.Line, w.Locator, "the first tag of the path is the checksum tag %d", c.sumTag)
		}
		if w.Value == "present" {
			switch {
			case w.Const:
				return perr(ErrBadDirective, w.Line, w.Locator, "a const cannot be `present`")
			case loc.tsize != 0:
				return perr(ErrBadDirective, w.Line, w.Locator, "`when … present` takes no size")
			}
			w.present = true
			continue
		}
		if loc.tsize == 0 {
			return perr(ErrBadDirective, w.Line, w.Locator, "a numeric when or const needs a size :<n> after the path")
		}
		v, err := strconv.ParseUint(w.Value, 10, 64)
		if !isDigits(w.Value) || err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "a tlv when or const value is `present` or an unsigned decimal integer, got %q", w.Value)
		}
		if loc.tsize < 8 && v>>(8*uint(loc.tsize)) != 0 {
			return perr(ErrBadDirective, w.Line, w.Locator, "the value %d does not fit %d byte(s)", v, loc.tsize)
		}
		w.num = v
	}
	// A path that is both a value and a set, in one scope (0.13 ruling 5).
	check := func(lines []line) error {
		at := map[string]int{}
		for _, ln := range lines {
			if l, n := tlvLineLoc(ln); l != nil {
				if _, has := at[pathKey(l.tags)]; !has {
					at[pathKey(l.tags)] = n
				}
			}
		}
		for _, ln := range lines {
			l, n := tlvLineLoc(ln)
			if l == nil {
				continue
			}
			for k := 1; k < len(l.tags); k++ {
				if prev, has := at[pathKey(l.tags[:k])]; has {
					return perr(ErrBadDirective, n, l.raw, "the path lies under the path of the line on line %d of the same scope: an item is a value or a set, not both", prev)
				}
			}
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
	return nil
}

// tlvLineLoc is the locator and line number of a field, when or const line.
func tlvLineLoc(ln line) (*locator, int) {
	switch {
	case ln.f != nil:
		return &ln.f.loc, ln.f.Line
	case ln.w != nil:
		return &ln.w.loc, ln.w.Line
	}
	return nil, 0
}

// --- scope ---

// tlvSet is one set a scope addresses: the top set, or a nested set some line
// walks into. Its slots are in the order of the first line that names each.
type tlvSet struct {
	slots []*tlvSlot
	byTag map[uint64]*tlvSlot
}

// tlvSlot is one tag of a set that the lines of a scope address.
type tlvSlot struct {
	tag     uint64
	named   bool     // a field, a numeric when, a const, or a set some line walks into
	set     *tlvSet  // the nested set lines walk into, nil for a value
	fields  []*Field // the field lines at this path, in line order
	value   *When    // the first numeric when or const at this path
	present bool     // a `when … present` is at this path
}

func newTLVSet() *tlvSet { return &tlvSet{byTag: map[uint64]*tlvSlot{}} }

func (s *tlvSet) slot(tag uint64) *tlvSlot {
	sl := s.byTag[tag]
	if sl == nil {
		sl = &tlvSlot{tag: tag}
		s.byTag[tag] = sl
		s.slots = append(s.slots, sl)
	}
	return sl
}

// named reports whether a line of the scope names tag in this set.
func (s *tlvSet) named(tag uint64) bool {
	sl := s.byTag[tag]
	return sl != nil && sl.named
}

// newTLVScope indexes the lines of one scope as a tree of sets.
func newTLVScope(lines []line) *tlvSet {
	top := newTLVSet()
	for _, ln := range lines {
		l, _ := tlvLineLoc(ln)
		if l == nil || len(l.tags) == 0 {
			continue
		}
		s := top
		for _, t := range l.tags[:len(l.tags)-1] {
			sl := s.slot(t)
			sl.named = true
			if sl.set == nil {
				sl.set = newTLVSet()
			}
			s = sl.set
		}
		sl := s.slot(l.tags[len(l.tags)-1])
		switch {
		case ln.f != nil:
			sl.named = true
			sl.fields = append(sl.fields, ln.f)
		case ln.w.present:
			sl.present = true
		default:
			sl.named = true
			if sl.value == nil {
				sl.value = ln.w
			}
		}
	}
	return top
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
		if len(last.val) != 2 {
			return nil, malformedTLV(p, "the checksum item has a value of %d byte(s), not 2", len(last.val))
		}
		items = items[:len(items)-1]
		for _, it := range items {
			if it.tag == c.sumTag {
				return nil, malformedTLV(p, "an item of the checksum tag %d stands before the last", c.sumTag)
			}
		}
		want := uint16(beUint(last.val))
		if got := sum16(data[:base+last.at]); got != want {
			return nil, malformedTLV(p, "checksum %04x does not match the message's %04x", want, got)
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
		if set, err = w.appendItem(set, c.sumTag, []byte{0, 0}, strconv.FormatUint(c.sumTag, 10)); err != nil {
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
		s := sum16(out[:len(out)-2])
		out[len(out)-2], out[len(out)-1] = byte(s>>8), byte(s)
	}
	return []byte(hex.EncodeToString(out)), nil
}

// isTLVOnlyTransform reports a transform valid only on the tlv wire.
func isTLVOnlyTransform(name string) bool { return name == "utf8" || name == "hex" }
