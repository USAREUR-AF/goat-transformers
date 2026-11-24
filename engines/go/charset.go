package goatxf

import (
	"fmt"
	"strconv"
	"strings"
)

// Character-coded identifiers (spec/engine-spec.md, "Version 0.46"): the
// pack-level `charset` lines and the transforms `code`, `codestr` and
// `codenum` over a list of them, one per position.

// maxCodePositions is the largest number of positions of a list.
const maxCodePositions = 16

// packCharset is one `charset <name> <characters> [<width>]` line.
type packCharset struct {
	name      string
	chars     string // the characters in code order
	widthText string
	hasWidth  bool
	line      int
	width     int // the bits per character on the bits wire
	code      [256]int16
}

// newPackCharset reads the arguments of a charset line, two or three.
func newPackCharset(args []string, line int) *packCharset {
	s := &packCharset{name: args[0], chars: args[1], line: line}
	if len(args) == 3 {
		s.widthText, s.hasWidth = args[2], true
	}
	return s
}

// resolve checks the line after the file is read and indexes its characters.
// Off the bits wire the width is ignored, its form included (ruling 14).
func (s *packCharset) resolve(wire string) error {
	if s.name == "" {
		return fmt.Errorf("a charset name is one or more of A-Z, a-z, 0-9, _ and -")
	}
	for i := 0; i < len(s.name); i++ {
		c := s.name[i]
		if !(c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return fmt.Errorf("a charset name is one or more of A-Z, a-z, 0-9, _ and -, got %q", s.name)
		}
	}
	if s.chars == "" {
		return fmt.Errorf("charset %s has no character", s.name)
	}
	for i := range s.code {
		s.code[i] = -1
	}
	for i := 0; i < len(s.chars); i++ {
		c := s.chars[i]
		if c < 0x21 || c > 0x7E {
			return fmt.Errorf("charset %s holds a character outside 0x21 to 0x7E", s.name)
		}
		if s.code[c] >= 0 {
			return fmt.Errorf("charset %s holds %q twice", s.name, string(rune(c)))
		}
		s.code[c] = int16(i)
	}
	s.width = 1
	for 1<<uint(s.width) < len(s.chars) {
		s.width++
	}
	if wire == WireBits && s.hasWidth {
		w, err := strconv.ParseUint(s.widthText, 10, 64)
		if !isDigits(s.widthText) || err != nil || w < uint64(s.width) || w > 8 {
			return fmt.Errorf("the width of charset %s is plain digits from %d to 8, got %q", s.name, s.width, s.widthText)
		}
		s.width = int(w)
	}
	return nil
}

// resolveCharsets checks the charset lines in order and indexes them by name.
func (p *Pack) resolveCharsets() (int, error) {
	p.charsets = map[string]*packCharset{}
	for _, s := range p.charsetLines {
		if err := s.resolve(p.Wire); err != nil {
			return s.line, err
		}
		if prev := p.charsets[s.name]; prev != nil {
			return s.line, fmt.Errorf("charset %s is already declared on line %d", s.name, prev.line)
		}
		p.charsets[s.name] = s
	}
	for _, f := range p.Fields {
		f.charsets = p.charsets
	}
	return 0, nil
}

// codeBase returns the name of a transform of this version that a field line
// names, parameters or not; "" for another transform.
func codeBase(name string) string {
	switch base, _, _ := strings.Cut(name, ":"); base {
	case "code", "codestr", "codenum":
		return base
	}
	return ""
}

// codeOnWire reports whether a wire takes a transform of this version.
func codeOnWire(base, wire string) bool {
	switch wire {
	case WireBits:
		return base != "codestr"
	case WireXML, WireJSON, WireGeoJSON, WireText:
		return base != "code"
	}
	return false
}

// codeList is the sets of a transform, first position first.
type codeList []*packCharset

// newCodeList reads the list of a transform of this version on a wire that
// may take it. Every refusal is bad-directive after the file (ruling 15).
func newCodeList(name, wire string, sets map[string]*packCharset) (codeList, error) {
	base, list, _ := strings.Cut(name, ":")
	if !codeOnWire(base, wire) {
		return nil, fmt.Errorf("transform %q is not valid on wire %s", name, wire)
	}
	names := strings.Split(list, ",")
	if len(names) > maxCodePositions {
		return nil, fmt.Errorf("%s takes 1 to %d positions, got %d", base, maxCodePositions, len(names))
	}
	var l codeList
	product := uint64(1)
	for _, n := range names {
		s := sets[n]
		if s == nil {
			return nil, fmt.Errorf("transform %q names the set %q, which no charset declares", name, n)
		}
		l = append(l, s)
		// The largest product is 2^63 (ruling 20).
		if base == "codenum" {
			if product > uint64(1)<<63/uint64(len(s.chars)) {
				return nil, fmt.Errorf("the product of the set sizes of %q is above 2^63", name)
			}
			product *= uint64(len(s.chars))
		}
	}
	return l, nil
}

// readText reads the codes of a text: one character per position, each in
// its position's set.
func (l codeList) readText(s string) ([]int, error) {
	if len(s) != len(l) {
		return nil, fmt.Errorf("the text %q does not have exactly %d character(s)", s, len(l))
	}
	codes := make([]int, len(l))
	for i, set := range l {
		c := set.code[s[i]]
		if c < 0 {
			return nil, fmt.Errorf("the text %q at position %d is not in the set %s", s, i, set.name)
		}
		codes[i] = int(c)
	}
	return codes, nil
}

// text is the characters of codes that are in range.
func (l codeList) text(codes []int) string {
	b := make([]byte, len(l))
	for i, set := range l {
		b[i] = set.chars[codes[i]]
	}
	return string(b)
}

// number is the mixed-radix number of codes, first position most significant.
func (l codeList) number(codes []int) int64 {
	var v uint64
	for i, set := range l {
		v = v*uint64(len(set.chars)) + uint64(codes[i])
	}
	return int64(v)
}

// splitNumber is the reverse of number.
func (l codeList) splitNumber(x int64) ([]int, error) {
	if x < 0 {
		return nil, fmt.Errorf("value %d is below 0", x)
	}
	u := uint64(x)
	codes := make([]int, len(l))
	for i := len(l) - 1; i >= 0; i-- {
		size := uint64(len(l[i].chars))
		codes[i] = int(u % size)
		u /= size
	}
	if u != 0 {
		return nil, fmt.Errorf("value %d is at or above the product of the set sizes", x)
	}
	return codes, nil
}

// readBits reads the codes of a raw integer, position 0 at the top; a code at
// or beyond its set's size is refused.
func (l codeList) readBits(raw uint64) ([]int, error) {
	codes := make([]int, len(l))
	for i := len(l) - 1; i >= 0; i-- {
		c := int(maskBits(raw, l[i].width))
		raw >>= uint(l[i].width)
		if c >= len(l[i].chars) {
			return nil, fmt.Errorf("code %d at position %d is beyond the %d character(s) of the set %s", c, i, len(l[i].chars), l[i].name)
		}
		codes[i] = c
	}
	return codes, nil
}

// bits packs codes into a raw integer, position 0 at the top.
func (l codeList) bits(codes []int) uint64 {
	var raw uint64
	for i, set := range l {
		raw = raw<<uint(set.width) | uint64(codes[i])
	}
	return raw
}

// value and codes convert between codes and the model value: the number for
// codenum, the text otherwise.
func (l codeList) value(base string, codes []int) Value {
	if base == "codenum" {
		return Value{Kind: KindInt, I: l.number(codes)}
	}
	return Value{Kind: KindString, S: l.text(codes)}
}

func (l codeList) codes(base string, v Value) ([]int, error) {
	if base == "codenum" {
		x, err := valueToInt(v)
		if err != nil {
			return nil, err
		}
		return l.splitNumber(x)
	}
	s, err := encString(v)
	if err != nil {
		return nil, err
	}
	return l.readText(s)
}

// textTransform is codestr or codenum on the text wires.
func (l codeList) textTransform(name string) *transform {
	base := codeBase(name)
	return &transform{
		name: name, strOnly: true,
		decode: func(s string) (Value, error) {
			codes, err := l.readText(s)
			if err != nil {
				return Value{}, err
			}
			return l.value(base, codes), nil
		},
		encode: func(v Value) (string, error) {
			codes, err := l.codes(base, v)
			if err != nil {
				return "", err
			}
			return l.text(codes), nil
		},
	}
}

// resolveCode binds a transform of this version to a field on a wire other
// than text. Every refusal is bad-directive.
func resolveCode(wire, base string, f *Field) error {
	l, err := newCodeList(f.Transform, wire, f.charsets)
	if err != nil {
		return err
	}
	// A geojson coordinate is a number; in a group body the same text is a
	// member path (ruling 23).
	if f.loc.kind == locCoord {
		return fmt.Errorf("%s is not valid on the geometry locator %s", f.Transform, f.Locator)
	}
	if wire != WireBits {
		f.tf = l.textTransform(f.Transform)
		return nil
	}
	sum := 0
	for _, s := range l {
		sum += s.width
	}
	if n := f.loc.blen; n != sum || n > 64 {
		return fmt.Errorf("%s needs a length of %d bits, the sum of its widths, and at most 64; got %d", f.Transform, sum, n)
	}
	f.btf = &bitsTransform{
		name: f.Transform,
		decode: func(raw uint64, length int) (Value, error) {
			codes, err := l.readBits(raw)
			if err != nil {
				return Value{}, err
			}
			return l.value(base, codes), nil
		},
		encode: func(v Value, length int) (uint64, error) {
			codes, err := l.codes(base, v)
			if err != nil {
				return 0, err
			}
			return l.bits(codes), nil
		},
	}
	return nil
}

// resolveCodeText binds codestr or codenum to a field of a text pack. A set
// in use holds neither the delimiter nor, under checksum nmea, `*` (ruling
// 12).
func (p *Pack) resolveCodeText(f *Field) (*textTf, error) {
	l, err := newCodeList(f.Transform, WireText, p.charsets)
	if err != nil {
		return nil, err
	}
	for _, s := range l {
		if !p.delimNone && strings.IndexByte(s.chars, p.delim) >= 0 {
			return nil, fmt.Errorf("the set %s holds the delimiter %q", s.name, string(rune(p.delim)))
		}
		if p.nmea && strings.IndexByte(s.chars, '*') >= 0 {
			return nil, fmt.Errorf("the set %s holds `*` under checksum nmea", s.name)
		}
	}
	return &textTf{name: f.Transform, kind: ttCode, code: l.textTransform(f.Transform)}, nil
}
