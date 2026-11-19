package goatxf

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// Absent-value sentinels (spec/engine-spec.md, "Version 0.9: absent-value
// sentinels"): `absent <value>[,<value>…]` names the raw wire values of a
// field that mean "no value". A sentinel is compared with the raw value
// before `via`, `typemap` and the transform; an absent key writes the first.

// sentinels is the `absent` list of one field, read for the pack's wire.
type sentinels struct {
	nums  []uint64 // bits and the integer forms of protobuf: the raw integers
	texts []string // xml, json, geojson and pstring: the texts compared
	// json and geojson: how the first sentinel is written, 'n' a number, 'b' a
	// boolean, 's' a string (0.5 ruling 11, 0.9 ruling 9).
	jtype byte
}

// splitAbsent splits the argument of `absent` on commas. The quoted empty
// token is the one value "the empty text"; any other empty value, and a value
// holding a double quote, is refused (0.9 ruling 11).
func splitAbsent(arg string) ([]string, error) {
	if arg == "" {
		return []string{""}, nil
	}
	vals := strings.Split(arg, ",")
	for _, v := range vals {
		if v == "" {
			return nil, fmt.Errorf("`absent %s`: an empty value in the list; only the single value \"\" names the empty text", arg)
		}
		if strings.ContainsRune(v, '"') {
			return nil, fmt.Errorf("`absent %s`: a value cannot hold a double quote", arg)
		}
	}
	return vals, nil
}

// isJSONNumberText reports whether s is a number by the grammar of RFC 8259:
// an optional minus, an integer part with no leading zero, an optional
// fraction and an optional exponent.
func isJSONNumberText(s string) bool {
	i, n := 0, len(s)
	digits := func() int {
		j := i
		for i < n && s[i] >= '0' && s[i] <= '9' {
			i++
		}
		return i - j
	}
	if i < n && s[i] == '-' {
		i++
	}
	switch {
	case i < n && s[i] == '0':
		i++
	case digits() == 0:
		return false
	}
	if i < n && s[i] == '.' {
		i++
		if digits() == 0 {
			return false
		}
	}
	if i < n && (s[i] == 'e' || s[i] == 'E') {
		i++
		if i < n && (s[i] == '+' || s[i] == '-') {
			i++
		}
		if digits() == 0 {
			return false
		}
	}
	return i == n
}

// jsonNumberCanon is the canonical text of a JSON number read as a double
// (0.1.1 ruling 3, 0.9 ruling 19); ok is false when it is not finite.
func jsonNumberCanon(lit string) (string, bool) {
	f, err := strconv.ParseFloat(lit, 64)
	if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
		return "", false
	}
	s, err := formatFloat(f)
	return s, err == nil
}

// resolveSentinels reads the `absent` values of f for the wire its locator is
// read on (a geojson group item reads json locators).
func resolveSentinels(wire string, f *Field) error {
	s := &sentinels{}
	unsigned := func(bits int) error {
		for _, v := range f.Absent {
			n, err := strconv.ParseUint(v, 10, 64)
			if err != nil || !isDigits(v) {
				return fmt.Errorf("`absent`: %q is not an unsigned decimal integer", v)
			}
			if bits < 64 && n>>uint(bits) != 0 {
				return fmt.Errorf("`absent`: %s does not fit the %d-bit raw value", v, bits)
			}
			s.nums = append(s.nums, n)
		}
		return nil
	}
	switch wire {
	case WireBits:
		if f.loc.blen > 64 {
			return fmt.Errorf("`absent` is valid on a bits field of at most 64 bits, got %d", f.loc.blen)
		}
		if err := unsigned(f.loc.blen); err != nil {
			return err
		}
	case WireProtobuf:
		switch f.pbf.wire {
		case pbLenDelim:
			// On pstring the text is as written: `=` is part of it (0.9
			// ruling 12).
			s.texts = append(s.texts, f.Absent...)
		case pbFixed32:
			if err := unsigned(32); err != nil {
				return err
			}
		default:
			if err := unsigned(64); err != nil {
				return err
			}
		}
	case WireXML:
		for _, v := range f.Absent {
			t := strings.TrimPrefix(v, "=")
			if t == "" && v != "" {
				return fmt.Errorf("`absent`: %q is empty once `=` is stripped; only \"\" names the empty text", v)
			}
			s.texts = append(s.texts, t)
		}
	default: // json, geojson
		for i, v := range f.Absent {
			forced := strings.HasPrefix(v, "=")
			t := v
			if forced {
				t = v[1:]
				if t == "" {
					return fmt.Errorf("`absent`: %q is empty once `=` is stripped; only \"\" names the empty text", v)
				}
			}
			typ := byte('s')
			switch {
			case forced:
			case t == "null":
				return fmt.Errorf("`absent null`: null is not a value a sentinel can hold")
			case t == "true" || t == "false":
				typ = 'b'
			case isJSONNumberText(t):
				c, ok := jsonNumberCanon(t)
				if !ok {
					return fmt.Errorf("`absent`: %s does not fit a finite double", t)
				}
				t, typ = c, 'n'
			}
			// On `bool` only the bare true and false (0.9 rulings 13 and 26).
			if f.jbool && typ != 'b' {
				return fmt.Errorf("`absent` on the bool transform takes true or false, got %q", v)
			}
			// A geojson coordinate takes only number text (0.9 ruling 25).
			if f.loc.kind == locCoord && typ != 'n' {
				return fmt.Errorf("`absent` on a geometry locator takes number text, got %q", v)
			}
			if i == 0 {
				s.jtype = typ
			}
			s.texts = append(s.texts, t)
		}
	}
	f.absent = s
	return nil
}

// sentinelNum reports whether a raw integer is one of the field's sentinels.
func (f *Field) sentinelNum(raw uint64) bool {
	if f.absent == nil {
		return false
	}
	for _, n := range f.absent.nums {
		if n == raw {
			return true
		}
	}
	return false
}

// sentinelText reports whether a raw text is one of the field's sentinels.
func (f *Field) sentinelText(raw string) bool {
	if f.absent == nil {
		return false
	}
	for _, t := range f.absent.texts {
		if t == raw {
			return true
		}
	}
	return false
}

// sentinelJSON reports whether a json or geojson member holds one of the
// field's sentinels: a string's text, a number's canonical text through a
// double, or a boolean's text (0.9 rulings 9 and 19).
func (f *Field) sentinelJSON(v *jval) bool {
	if f.absent == nil || v == nil {
		return false
	}
	switch v.k {
	case jStr, jBool:
		return f.sentinelText(v.s)
	case jNum:
		c, ok := jsonNumberCanon(v.s)
		return ok && f.sentinelText(c)
	}
	return false
}

// writesSentinel reports whether an encode writes the field's first sentinel:
// the line has `absent`, and the record has no value for the key and no
// default applies.
func (f *Field) writesSentinel(rec *Item, defaults map[string]*Default) bool {
	if f.absent == nil {
		return false
	}
	if _, has := rec.Fields[f.Key]; has {
		return false
	}
	return defaults[f.Key] == nil
}

// sentinelBits is the raw integer the first sentinel writes into a bits
// field: its low len bits, then `swap`.
func (f *Field) sentinelBits() uint64 {
	raw := maskBits(f.absent.nums[0], f.loc.blen)
	if f.Swap {
		raw = swapBytes(raw, f.loc.blen/8)
	}
	return raw
}

// sentinelPB is the protobuf value the first sentinel writes: a varint with
// no zig-zag, 8 or 4 little-endian bytes, or the text.
func (f *Field) sentinelPB() pbVal {
	switch f.pbf.wire {
	case pbLenDelim:
		return pbVal{wire: pbLenDelim, b: []byte(f.absent.texts[0])}
	default:
		return pbVal{wire: f.pbf.wire, u: f.absent.nums[0]}
	}
}

// sentinelJSONText is the JSON text the first sentinel writes: a number, a
// boolean or a string. geo selects the geojson wire's string writer.
func (f *Field) sentinelJSONText(geo bool) string {
	t := f.absent.texts[0]
	switch f.absent.jtype {
	case 'n', 'b':
		return t
	}
	if geo {
		return jsonString(t)
	}
	return jsonQuote(t)
}
