package goatxf

// The declarations of tlvwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"encoding/hex"
	"fmt"
	"strconv"
	"strings"
)

// maxTLVTag is the largest tag a path names: 2^28-1, four BER-OID bytes.
const maxTLVTag = 1<<28 - 1

// tlvConf is what the directives of a tlv pack state.
type tlvConf struct {
	tagN    int // 0: ber-oid; else 1, 2 or 4 bytes
	lenN    int // 0: ber; else 1, 2 or 4 bytes
	key     []byte
	hasKey  bool
	sum     bool   // `checksum sum16 <tag>` or `checksum crc32 <tag>`
	crc     bool   // the checksum is crc32 (0.27), else sum16
	sumText string // the tag of the checksum, as written
	sumTag  uint64

	lines map[string]int // the line of each tlv directive the pack has: tag, length, key, checksum
	err   error          // the first failure of a tlv directive, reported after the file is read
}

// tlvDirective reads one `tag`, `length` (one argument, outside a sequential
// pack), `key` or `checksum sum16|crc32 …` line. Its failures are bad-directive and
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
			fail("checksum %s takes a tag: `checksum %s <tag>`", args[0], args[0])
			return
		}
		c.sum, c.crc, c.sumText = true, args[0] == "crc32", args[1]
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
		// A fraction factor is unsigned (ruling 25 of 0.15).
		if err := checkUnsignedFraction(name); err != nil {
			return nil, err
		}
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
		}{{f.Swap, "swap"}, {f.Trim, "trim"}, {f.Optional, "optional"}, {f.Absent != nil, "absent"}, {f.StopLine, "stop"}} {
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

// isTLVOnlyTransform reports a transform valid only on the tlv wire.
func isTLVOnlyTransform(name string) bool { return name == "utf8" || name == "hex" }
