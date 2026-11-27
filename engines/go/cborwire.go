//go:build !goat_wires || goat_wire_cbor

package goatxf

import (
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// The cbor wire (spec/engine-spec.md, "Version 0.28: the `cbor` wire"): the
// message is one CBOR data item (RFC 8949), a map or an array whose items
// may be maps, arrays and scalars at any depth. Paths step through integer
// and text map keys and array positions; tags are passed over. Output has
// the core deterministic encoding of RFC 8949 4.2.1. Input and output are
// hex text.

// matches reports whether an item, its tags passed over, is of the value's
// type and equal to it. It never holds on a float, a byte string, null or
// undefined.
func (v *cborVal) matches(x *cItem) bool {
	switch v.kind {
	case cvInt:
		return ((x.major == 0 && !v.neg) || (x.major == 1 && v.neg)) && x.arg == v.arg
	case cvBool:
		return x.isSimple() && ((v.b && x.arg == 21) || (!v.b && x.arg == 20))
	case cvText:
		return x.major == 3 && string(x.str) == v.text
	}
	return false
}

// --- transforms ---

// cborInt reads a major type 0 or 1 item as a signed 64-bit integer.
func cborInt(x *cItem) (int64, error) {
	switch x.major {
	case 0:
		if x.arg > math.MaxInt64 {
			return 0, fmt.Errorf("the integer %d lies above 2^63-1", x.arg)
		}
		return int64(x.arg), nil
	case 1:
		if x.arg > math.MaxInt64 {
			return 0, fmt.Errorf("the integer -1-%d lies below -2^63", x.arg)
		}
		return -1 - int64(x.arg), nil
	}
	return 0, fmt.Errorf("the item is %s, not an integer", x.typeName())
}

// cborDecodeTf reads an item, its tags passed over and not null or
// undefined, through a transform (0.28, Transforms for `cbor`).
func cborDecodeTf(kind int, x *cItem) (Value, error) {
	switch kind {
	case cbUint:
		if x.major != 0 {
			return Value{}, fmt.Errorf("uint takes an unsigned integer (major type 0), got %s", x.typeName())
		}
		i, err := cborInt(x)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindInt, I: i}, nil
	case cbInt:
		i, err := cborInt(x)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindInt, I: i}, nil
	case cbEpoch:
		s, err := cborInt(x)
		if err != nil {
			return Value{}, err
		}
		// The range applies to the product (ruling 7).
		if s > math.MaxInt64/1000 || s < math.MinInt64/1000 {
			return Value{}, fmt.Errorf("%d seconds is a time_ms outside -2^63 to 2^63-1", s)
		}
		return Value{Kind: KindInt, I: s * 1000}, nil
	case cbFloat:
		var f float64
		switch {
		case x.major == 0:
			f = float64(x.arg)
		case x.major == 1:
			if x.arg == math.MaxUint64 {
				f = -0x1p64
			} else {
				f = -float64(x.arg + 1)
			}
		case x.isFloat():
			f = x.float()
			if math.IsNaN(f) || math.IsInf(f, 0) {
				return Value{}, fmt.Errorf("a NaN or an infinity is not a value")
			}
		default:
			return Value{}, fmt.Errorf("float takes a float or an integer, got %s", x.typeName())
		}
		return Value{Kind: KindFloat, F: f}, nil
	case cbText:
		if x.major != 3 {
			return Value{}, fmt.Errorf("text takes a text string (major type 3), got %s", x.typeName())
		}
		return Value{Kind: KindString, S: string(x.str)}, nil
	case cbBytes:
		if x.major != 2 {
			return Value{}, fmt.Errorf("bytes takes a byte string (major type 2), got %s", x.typeName())
		}
		return Value{Kind: KindString, S: hex.EncodeToString(x.str)}, nil
	case cbBool:
		if x.isSimple() && (x.arg == 20 || x.arg == 21) {
			return Value{Kind: KindInt, I: int64(x.arg - 20)}, nil
		}
		return Value{}, fmt.Errorf("bool takes false or true, got %s", x.typeName())
	}
	return Value{}, fmt.Errorf("no transform")
}

// cborWriteInt writes a signed integer as major type 0 or 1.
func cborWriteInt(out []byte, i int64) []byte {
	if i >= 0 {
		return cborHead(out, 0, uint64(i))
	}
	return cborHead(out, 1, uint64(-(i + 1)))
}

// cborEncodeTf writes a model value through a transform as one encoded
// item.
func cborEncodeTf(kind int, v Value) ([]byte, error) {
	switch kind {
	case cbUint, cbInt, cbBool, cbEpoch:
		i, err := valueToInt(v)
		if err != nil {
			return nil, err
		}
		switch kind {
		case cbUint:
			if i < 0 {
				return nil, fmt.Errorf("uint cannot write the negative value %d", i)
			}
			return cborHead(nil, 0, uint64(i)), nil
		case cbBool:
			switch i {
			case 0:
				return []byte{0xf4}, nil
			case 1:
				return []byte{0xf5}, nil
			}
			return nil, fmt.Errorf("bool writes 0 or 1, got %d", i)
		case cbEpoch:
			// time_ms divided by 1000 exactly, rounded half away from zero.
			s, r := i/1000, i%1000
			if r >= 500 {
				s++
			} else if r <= -500 {
				s--
			}
			i = s
		}
		return cborWriteInt(nil, i), nil
	case cbFloat:
		f, err := valueToFloat(v)
		if err != nil {
			return nil, err
		}
		if math.IsNaN(f) || math.IsInf(f, 0) {
			return nil, fmt.Errorf("a NaN or an infinity is not written (ruling 20)")
		}
		return cborFloat(nil, f), nil
	case cbText:
		s, err := encString(v)
		if err != nil {
			return nil, err
		}
		if !utf8.ValidString(s) {
			return nil, fmt.Errorf("the text is not UTF-8")
		}
		return append(cborHead(nil, 3, uint64(len(s))), s...), nil
	case cbBytes:
		s, err := encString(v)
		if err != nil {
			return nil, err
		}
		if len(s)%2 != 0 || !isLowerHex(s) {
			return nil, fmt.Errorf("bytes writes an even number of lowercase hex digits, got %q", s)
		}
		b, err := hex.DecodeString(s)
		if err != nil {
			return nil, err
		}
		return append(cborHead(nil, 2, uint64(len(b))), b...), nil
	}
	return nil, fmt.Errorf("no transform")
}

// --- items ---

// cItem is one data item as read. Integers (major types 0 and 1) and tags
// hold their argument; a simple value its number; a float (major type 7,
// additional information 25 to 27) its bits.
type cItem struct {
	major byte
	ai    byte
	arg   uint64
	str   []byte   // byte and text strings, chunks joined
	arr   []*cItem // arrays
	keys  []*cItem // maps, in input order
	vals  []*cItem
	inner *cItem // tags: the item enclosed
	raw   []byte // the item as it stood in the input, tags included
}

// strip passes over the tags on an item.
func (x *cItem) strip() *cItem {
	for x.major == 6 {
		x = x.inner
	}
	return x
}

func (x *cItem) isSimple() bool { return x.major == 7 && x.ai <= 24 }
func (x *cItem) isFloat() bool  { return x.major == 7 && x.ai >= 25 && x.ai <= 27 }

// isNull reports null (22) or undefined (23), which are absent.
func (x *cItem) isNull() bool { return x.isSimple() && (x.arg == 22 || x.arg == 23) }

// float is the value of a float item.
func (x *cItem) float() float64 {
	switch x.ai {
	case 25:
		return halfToFloat(uint16(x.arg & 0xffff))
	case 26:
		return float64(math.Float32frombits(uint32(x.arg & 0xffffffff)))
	}
	return math.Float64frombits(x.arg)
}

func (x *cItem) typeName() string {
	switch x.major {
	case 0:
		return "an unsigned integer"
	case 1:
		return "a negative integer"
	case 2:
		return "a byte string"
	case 3:
		return "a text string"
	case 4:
		return "an array"
	case 5:
		return "a map"
	case 6:
		return "a tag"
	}
	switch {
	case x.isFloat():
		return "a float"
	case x.arg == 20 || x.arg == 21:
		return "a bool"
	case x.arg == 22:
		return "null"
	case x.arg == 23:
		return "undefined"
	}
	return "simple value " + strconv.FormatUint(x.arg, 10)
}

// member is the value of the map member whose key the step names: an
// integer key of major type 0 or 1, or a text key, never a tagged key.
func (x *cItem) member(st cStep) *cItem {
	for i, k := range x.keys {
		switch st.kind {
		case csInt:
			if ((k.major == 0 && !st.neg) || (k.major == 1 && st.neg)) && k.arg == st.arg {
				return x.vals[i]
			}
		case csText:
			if k.major == 3 && string(k.str) == st.text {
				return x.vals[i]
			}
		}
	}
	return nil
}

// keyStep is the step that addresses a map key, ok false when the key is
// not addressable (0.28, Paths, and ruling 17).
func keyStep(k *cItem) (cStep, bool) {
	switch k.major {
	case 0:
		return cStep{kind: csInt, arg: k.arg}, true
	case 1:
		if k.arg <= math.MaxInt64 {
			return cStep{kind: csInt, neg: true, arg: k.arg}, true
		}
	case 3:
		if s := string(k.str); isCBORTextKey(s) {
			return cStep{kind: csText, text: s}, true
		}
	}
	return cStep{}, false
}

// cborReader reads one data item; every failure is malformed-wire.
type cborReader struct {
	b []byte
	i int
}

func (r *cborReader) left() uint64 { return uint64(len(r.b) - r.i) }

// head reads the head of an item: its major type, additional information
// and argument, in any length; indef is set for additional information 31.
func (r *cborReader) head() (major, ai byte, arg uint64, indef bool, err error) {
	if r.i >= len(r.b) {
		return 0, 0, 0, false, fmt.Errorf("the input ends where an item stands, at byte %d", r.i)
	}
	c := r.b[r.i]
	r.i++
	major, ai = c>>5, c&0x1f
	switch {
	case ai < 24:
		arg = uint64(ai)
	case ai <= 27:
		n := 1 << (ai - 24)
		if len(r.b)-r.i < n {
			return 0, 0, 0, false, fmt.Errorf("a head of %d byte(s) runs past the input at byte %d", n+1, r.i-1)
		}
		for k := 0; k < n; k++ {
			arg = arg<<8 | uint64(r.b[r.i+k])
		}
		r.i += n
	case ai == 31:
		indef = true
	default:
		return 0, 0, 0, false, fmt.Errorf("additional information %d at byte %d is reserved", ai, r.i-1)
	}
	return major, ai, arg, indef, nil
}

// item reads one well-formed item (RFC 8949 Appendix C). level is the level
// the item has when it is an array, a map or a tag.
func (r *cborReader) item(level int) (*cItem, error) {
	start := r.i
	major, ai, arg, indef, err := r.head()
	if err != nil {
		return nil, err
	}
	x := &cItem{major: major, ai: ai, arg: arg}
	switch major {
	case 0, 1:
		if indef {
			return nil, fmt.Errorf("an integer at byte %d has additional information 31", start)
		}
	case 2, 3:
		if !indef {
			// The length is compared with the bytes left before anything
			// is taken for it.
			if arg > r.left() {
				return nil, fmt.Errorf("a string at byte %d states %d byte(s) with %d left", start, arg, r.left())
			}
			n := int(arg)
			x.str = r.b[r.i : r.i+n]
			r.i += n
			if major == 3 && !utf8.Valid(x.str) {
				return nil, fmt.Errorf("the text string at byte %d is not UTF-8", start)
			}
			break
		}
		buf := []byte{}
		for {
			if r.i >= len(r.b) {
				return nil, fmt.Errorf("the indefinite string at byte %d has no break", start)
			}
			if r.b[r.i] == 0xff {
				r.i++
				break
			}
			at := r.i
			cm, _, clen, cindef, err := r.head()
			if err != nil {
				return nil, err
			}
			if cm != major || cindef {
				return nil, fmt.Errorf("the chunk at byte %d of an indefinite string is not a definite string of its type", at)
			}
			if clen > r.left() {
				return nil, fmt.Errorf("a chunk at byte %d states %d byte(s) with %d left", at, clen, r.left())
			}
			n := int(clen)
			chunk := r.b[r.i : r.i+n]
			r.i += n
			// Each chunk of a text string is UTF-8 on its own.
			if major == 3 && !utf8.Valid(chunk) {
				return nil, fmt.Errorf("the text chunk at byte %d is not UTF-8", at)
			}
			buf = append(buf, chunk...)
		}
		x.str = buf
	case 4, 5, 6:
		if level > cborMaxDepth {
			return nil, fmt.Errorf("the item at byte %d nests deeper than %d levels", start, cborMaxDepth)
		}
		switch major {
		case 4:
			if indef {
				for {
					if r.i >= len(r.b) {
						return nil, fmt.Errorf("the indefinite array at byte %d has no break", start)
					}
					if r.b[r.i] == 0xff {
						r.i++
						break
					}
					e, err := r.item(level + 1)
					if err != nil {
						return nil, err
					}
					x.arr = append(x.arr, e)
				}
				break
			}
			// Each element takes at least one byte.
			if arg > r.left() {
				return nil, fmt.Errorf("the array at byte %d states %d element(s) with %d byte(s) left", start, arg, r.left())
			}
			x.arr = make([]*cItem, 0, int(arg))
			for k := uint64(0); k < arg; k++ {
				e, err := r.item(level + 1)
				if err != nil {
					return nil, err
				}
				x.arr = append(x.arr, e)
			}
		case 5:
			seen := map[string]bool{}
			pair := func() error {
				k, err := r.item(level + 1)
				if err != nil {
					return err
				}
				v, err := r.item(level + 1)
				if err != nil {
					return err
				}
				id := cborKeyID(k)
				if seen[id] {
					return fmt.Errorf("the map at byte %d holds two equal keys", start)
				}
				seen[id] = true
				x.keys, x.vals = append(x.keys, k), append(x.vals, v)
				return nil
			}
			if indef {
				for {
					if r.i >= len(r.b) {
						return nil, fmt.Errorf("the indefinite map at byte %d has no break", start)
					}
					if r.b[r.i] == 0xff {
						r.i++
						break
					}
					if err := pair(); err != nil {
						return nil, err
					}
				}
				break
			}
			// Each member takes at least two bytes.
			if arg > r.left()/2 {
				return nil, fmt.Errorf("the map at byte %d states %d member(s) with %d byte(s) left", start, arg, r.left())
			}
			x.keys, x.vals = make([]*cItem, 0, int(arg)), make([]*cItem, 0, int(arg))
			for k := uint64(0); k < arg; k++ {
				if err := pair(); err != nil {
					return nil, err
				}
			}
		case 6:
			if indef {
				return nil, fmt.Errorf("a tag at byte %d has additional information 31", start)
			}
			in, err := r.item(level + 1)
			if err != nil {
				return nil, err
			}
			x.inner = in
		}
	case 7:
		switch {
		case indef:
			return nil, fmt.Errorf("a break at byte %d stands outside an indefinite item", start)
		case ai == 24 && arg < 32:
			return nil, fmt.Errorf("a two-byte simple value below 32 at byte %d", start)
		}
	}
	x.raw = r.b[start:r.i]
	return x, nil
}

// readCBORItem reads b as exactly one well-formed data item.
func readCBORItem(b []byte) (*cItem, error) {
	r := &cborReader{b: b}
	x, err := r.item(1)
	if err != nil {
		return nil, err
	}
	if r.i != len(b) {
		return nil, fmt.Errorf("%d byte(s) follow the data item", len(b)-r.i)
	}
	return x, nil
}

// cborKeyID is the identity of a map key for the check of equal keys
// (Reading a message, step 4): keys of different major types differ; two
// integer keys are equal when their values are, two text keys when their
// bytes are, and other keys when their core deterministic encodings are.
func cborKeyID(k *cItem) string {
	switch k.major {
	case 0, 1:
		return string(rune('0'+k.major)) + strconv.FormatUint(k.arg, 16)
	case 3:
		return "3" + string(k.str)
	}
	return "e" + string(cborDet(nil, k))
}

// --- the core deterministic encoding (RFC 8949 4.2.1) ---

// cborDet writes an item in the core deterministic encoding: shortest
// heads, definite lengths, floats at the shortest width that holds them
// exactly, map members in the bytewise order of their encoded keys.
func cborDet(out []byte, x *cItem) []byte {
	switch x.major {
	case 0, 1:
		return cborHead(out, x.major, x.arg)
	case 2, 3:
		out = cborHead(out, x.major, uint64(len(x.str)))
		return append(out, x.str...)
	case 4:
		out = cborHead(out, 4, uint64(len(x.arr)))
		for _, e := range x.arr {
			out = cborDet(out, e)
		}
		return out
	case 5:
		pairs := make([]cborPair, len(x.keys))
		for i := range x.keys {
			pairs[i] = cborPair{key: string(cborDet(nil, x.keys[i])), val: cborDet(nil, x.vals[i])}
		}
		return cborWriteMap(out, pairs)
	case 6:
		out = cborHead(out, 6, x.arg)
		return cborDet(out, x.inner)
	}
	if x.isFloat() {
		return cborFloatBits(out, x)
	}
	if x.arg < 24 {
		return append(out, 0xe0|byte(x.arg))
	}
	return append(out, 0xf8, byte(x.arg&0xff))
}

// cborPair is one encoded map member.
type cborPair struct {
	key string
	val []byte
}

// cborWriteMap writes a map of encoded members, sorted by their keys.
func cborWriteMap(out []byte, pairs []cborPair) []byte {
	sort.Slice(pairs, func(i, j int) bool { return pairs[i].key < pairs[j].key })
	out = cborHead(out, 5, uint64(len(pairs)))
	for _, p := range pairs {
		out = append(out, p.key...)
		out = append(out, p.val...)
	}
	return out
}

// halfToFloat is the value of an IEEE-754 half.
func halfToFloat(h uint16) float64 {
	e, m := int(h>>10)&0x1f, float64(h&0x3ff)
	var f float64
	switch e {
	case 0:
		f = math.Ldexp(m, -24)
	case 31:
		if m == 0 {
			f = math.Inf(1)
		} else {
			f = math.NaN()
		}
	default:
		f = math.Ldexp(m+1024, e-25)
	}
	if h&0x8000 != 0 {
		f = -f
	}
	return f
}

// halfExact returns the half that holds f exactly, subnormals and the
// infinities included; ok is false when no half holds it. f is not NaN.
func halfExact(f float64) (uint16, bool) {
	var sign uint16
	if math.Signbit(f) {
		sign, f = 0x8000, -f
	}
	switch {
	case f == 0:
		return sign, true
	case math.IsInf(f, 0):
		return sign | 0x7c00, true
	case f >= 0x1p-14:
		frac, exp := math.Frexp(f) // f = frac * 2^exp, frac in [0.5, 1)
		e := exp - 1
		if e > 15 {
			return 0, false
		}
		m := (2*frac - 1) * 1024
		if m != math.Floor(m) {
			return 0, false
		}
		return sign | uint16(e+15)<<10 | uint16(m), true
	}
	m := f * 0x1p24
	if m != math.Floor(m) || m >= 1024 {
		return 0, false
	}
	return sign | uint16(m), true
}

// cborFloat writes a float that is not NaN at the shortest of half, single
// and double that holds it exactly (RFC 8949 4.2.2); -0.0 is f98000.
func cborFloat(out []byte, f float64) []byte {
	if h, ok := halfExact(f); ok {
		return append(out, 0xf9, byte(h>>8), byte(h))
	}
	if s := float32(f); float64(s) == f {
		b := math.Float32bits(s)
		return append(out, 0xfa, byte(b>>24), byte(b>>16), byte(b>>8), byte(b))
	}
	b := math.Float64bits(f)
	return append(out, 0xfb, byte(b>>56), byte(b>>48), byte(b>>40), byte(b>>32), byte(b>>24), byte(b>>16), byte(b>>8), byte(b))
}

// cborFloatBits re-encodes a float item of residue. A NaN keeps its sign
// and payload, at the shortest width that holds the payload.
func cborFloatBits(out []byte, x *cItem) []byte {
	f := x.float()
	if !math.IsNaN(f) {
		return cborFloat(out, f)
	}
	var sign, m uint64 // m: the 52-bit significand field of the double
	switch x.ai {
	case 25:
		sign, m = x.arg>>15&1, (x.arg&0x3ff)<<42
	case 26:
		sign, m = x.arg>>31&1, (x.arg&0x7fffff)<<29
	default:
		sign, m = x.arg>>63, x.arg&(1<<52-1)
	}
	switch {
	case m&(1<<42-1) == 0:
		h := sign<<15 | 0x7c00 | m>>42
		return append(out, 0xf9, byte(h>>8), byte(h))
	case m&(1<<29-1) == 0:
		s := sign<<31 | 0x7f800000 | m>>29
		return append(out, 0xfa, byte(s>>24), byte(s>>16), byte(s>>8), byte(s))
	}
	d := sign<<63 | 0x7ff<<52 | m
	return append(out, 0xfb, byte(d>>56), byte(d>>48), byte(d>>40), byte(d>>32), byte(d>>24), byte(d>>16), byte(d>>8), byte(d))
}

// --- the paths of a scope ---

func malformedCBOR(p *Pack, format string, a ...any) error {
	return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: fmt.Sprintf(format, a...)}
}

const (
	cbFound = iota
	cbAbsent
	cbWrong
)

// cborAt walks a path from a container: the item at the path as it stands,
// tags not passed over. A null or undefined partway, or a member that is
// not there, is absent (ruling 12); a map or array of the wrong type for
// the next step is cbWrong.
func cborAt(root *cItem, steps []cStep) (*cItem, int) {
	cur := root
	for _, st := range steps {
		c := cur.strip()
		if c.isNull() {
			return nil, cbAbsent
		}
		if st.kind == csPos {
			if c.major != 4 {
				return nil, cbWrong
			}
			if st.arg >= uint64(len(c.arr)) {
				return nil, cbAbsent
			}
			cur = c.arr[st.arg]
			continue
		}
		if c.major != 5 {
			return nil, cbWrong
		}
		if cur = c.member(st); cur == nil {
			return nil, cbAbsent
		}
	}
	return cur, cbFound
}

// cborWhenHolds reports whether a `when` holds on the top item.
func cborWhenHolds(w *When, top *cItem) bool {
	x, st := cborAt(top, w.loc.cpath)
	if st != cbFound {
		return false
	}
	x = x.strip()
	if w.present {
		return !x.isNull()
	}
	return w.cv.matches(x)
}

func decodeCBOR(d *decodeState, b []byte) error {
	p := d.pack
	data, err := parseHexInput(p.Format, b)
	if err != nil {
		return err
	}
	top, err := readCBORItem(data)
	if err != nil {
		return malformedCBOR(p, "%v", err)
	}
	if p.cbor.hasTag {
		if top.major != 6 || top.arg != p.cbor.tag {
			return malformedCBOR(p, "the outermost tag of the input is not %d", p.cbor.tag)
		}
		top = top.inner
	}
	top = top.strip()
	want, what := byte(5), "a map"
	if p.cbor.topArr {
		want, what = 4, "an array"
	}
	if top.major != want {
		return malformedCBOR(p, "the top item is %s, and the paths of the pack decide %s", top.typeName(), what)
	}
	lay, err := d.choose(func(w *When) bool { return cborWhenHolds(w, top) })
	if err != nil {
		return err
	}
	if err := d.cborLines(lay.lines, top); err != nil {
		return err
	}
	d.cborResidue(lay.cbor, top, "")
	return nil
}

// cborLines reads the lines of a scope, in line order, from its container:
// the top item or a group item. Every path is walked: a map or array of the
// wrong type on the way is malformed-wire (Reading a message, step 8).
func (d *decodeState) cborLines(lines []line, root *cItem) error {
	p := d.pack
	for _, ln := range lines {
		path, _, loc, ok := cborLinePath(ln)
		if !ok {
			continue
		}
		var x *cItem
		if ln.g != nil && ln.g.cdot {
			x = root
		} else {
			var st int
			x, st = cborAt(root, path)
			if st == cbWrong {
				return malformedCBOR(p, "the path %s passes through an item that is not the map or array its next step needs", loc)
			}
			if st == cbAbsent {
				continue
			}
		}
		xs := x.strip()
		switch {
		case ln.f != nil:
			d.cborField(ln.f, xs)
		case ln.g != nil:
			// A group path at null or undefined is an absent list.
			if xs.isNull() {
				continue
			}
			if xs.major != 4 {
				return malformedCBOR(p, "the group path %s holds %s, not an array", loc, xs.typeName())
			}
			if err := d.cborGroup(ln.g, xs); err != nil {
				return err
			}
		}
	}
	return nil
}

// cborField decodes one field from its item, tags passed over. null and
// undefined are absent.
func (d *decodeState) cborField(f *Field, x *cItem) {
	if x.isNull() {
		return
	}
	v, err := cborDecodeTf(f.ctf, x)
	if err != nil {
		d.fail(f, err.Error())
		return
	}
	d.store(f, v)
}

// cborGroup reads one item per element of the array at a group's path.
func (d *decodeState) cborGroup(g *Group, arr *cItem) error {
	items := make([]*Item, 0, len(arr.arr))
	for _, e := range arr.arr {
		it, err := d.item(func() error { return d.cborItem(g, e) })
		if err != nil {
			return err
		}
		items = append(items, it)
	}
	d.rec.SetList(g.List, items)
	return nil
}

// cborItem reads one group item. An element of the wrong type for the body
// is an item with no keys (ruling 12 of 0.7), and so is null under a `.`
// body; a map or an array under a `.` body goes to the transform, which
// refuses it (ruling 14).
func (d *decodeState) cborItem(g *Group, e *cItem) error {
	es := e.strip()
	switch g.ckind {
	case ckDot:
		for _, f := range g.dots {
			d.cborField(f, es)
		}
		return nil
	case ckArr:
		if es.major != 4 {
			return nil
		}
	default:
		if es.major != 5 {
			return nil
		}
	}
	return d.cborLines(g.lines, es)
}

// cborResidue keeps every member or element of a container that the scope
// walks into and that no line maps or walks into (0.28, Residue).
func (d *decodeState) cborResidue(n *cNode, c *cItem, prefix string) {
	if n == nil || n.group != nil {
		return
	}
	if c.major == 4 {
		for i, e := range c.arr {
			// Array residue past position 65535 is dropped (ruling 18).
			if i > cborMaxPos {
				break
			}
			pos := uint64(i)
			d.cborResidueAt(n.kid(posID(pos)), e, prefix+"["+strconv.FormatUint(pos, 10)+"]")
		}
		return
	}
	for i, k := range c.keys {
		if st, ok := keyStep(k); ok {
			d.cborResidueAt(n.kid(st.id()), c.vals[i], prefix+st.String())
		} else {
			// A key that is not addressable: the key's bytes as they stood
			// (ruling 16).
			d.residue(prefix+"#"+hex.EncodeToString(k.raw), hex.EncodeToString(c.vals[i].raw), false)
		}
	}
}

func (d *decodeState) cborResidueAt(n *cNode, x *cItem, loc string) {
	switch {
	case n == nil || (!n.mapped() && !n.walked()):
		// `when … present` alone leaves its item residue (ruling 15).
		d.residue(loc, hex.EncodeToString(x.raw), false)
	case n.mapped():
	default:
		// A null walked into is neither mapped nor residue (ruling 12).
		xs := x.strip()
		if (n.arr && xs.major == 4) || (!n.arr && xs.major == 5) {
			d.cborResidue(n, xs, loc+".")
		}
	}
}

// --- encode ---

// oNode is one place of the output: a scalar or whole item written as its
// encoding (leaf), or a map or an array of places.
type oNode struct {
	arr  bool
	m    map[string]*oNode // maps: by encoded key
	a    map[uint64]*oNode // arrays: by position
	leaf []byte
	cn   *cNode // the place of the scope's paths, nil when only residue made it
}

// at returns the place one step into a container, made when it is not
// there.
func (o *oNode) at(key string, pos uint64, isPos bool) *oNode {
	if isPos {
		if o.a == nil {
			o.a = map[uint64]*oNode{}
		}
		c := o.a[pos]
		if c == nil {
			c = &oNode{}
			o.a[pos] = c
		}
		return c
	}
	if o.m == nil {
		o.m = map[string]*oNode{}
	}
	c := o.m[key]
	if c == nil {
		c = &oNode{}
		o.m[key] = c
	}
	return c
}

func (o *oNode) get(key string, pos uint64, isPos bool) *oNode {
	if isPos {
		return o.a[pos]
	}
	return o.m[key]
}

// written reports whether anything is written at the place.
func (o *oNode) written() bool {
	if o.leaf != nil {
		return true
	}
	for _, c := range o.m {
		if c.written() {
			return true
		}
	}
	for _, c := range o.a {
		if c.written() {
			return true
		}
	}
	return false
}

type cborWriter struct {
	p *Pack
}

// build writes the lines of a scope into a container: at each place the
// first `when` or `const` value, else the earliest line whose key is
// present (Writing a message, step 1, and ruling 16 of 0.5).
func (w *cborWriter) build(lay *layout, n *cNode, o *oNode, rec *Item) error {
	o.cn = n
	for _, k := range n.kids {
		isPos := k.step.kind == csPos
		key := ""
		if !isPos {
			key = string(k.step.keyBytes())
		}
		leaf, err := w.leaf(lay, k, rec)
		if err != nil {
			return err
		}
		if leaf != nil {
			c := o.at(key, k.step.arg, isPos)
			c.leaf, c.cn = leaf, k
			continue
		}
		if k.walked() {
			c := o.at(key, k.step.arg, isPos)
			c.arr = k.arr
			if err := w.build(lay, k, c, rec); err != nil {
				return err
			}
		}
	}
	return nil
}

// leaf is the encoding a line writes at a place, nil for none.
func (w *cborWriter) leaf(lay *layout, n *cNode, rec *Item) ([]byte, error) {
	switch {
	case n.group != nil:
		items, ok := rec.Lists[n.group.List]
		if !ok {
			return nil, nil
		}
		return w.list(n.group, items)
	case n.val != nil:
		return n.val.cv.enc, nil
	}
	for _, f := range n.fields {
		b, ok, err := w.field(lay, f, rec)
		if err != nil {
			return nil, err
		}
		if ok {
			return b, nil
		}
	}
	return nil, nil
}

func (w *cborWriter) field(lay *layout, f *Field, rec *Item) ([]byte, bool, error) {
	v, ok, err := fieldValue(w.p, lay, f, rec)
	if err != nil || !ok {
		return nil, false, err
	}
	b, err := cborEncodeTf(f.ctf, v)
	if err != nil {
		return nil, false, encodeErr(w.p, f, err)
	}
	return b, true, nil
}

// list writes a present list: its array, one element per item in list
// order (Writing a message, step 4).
func (w *cborWriter) list(g *Group, items []*Item) ([]byte, error) {
	out := cborHead(nil, 4, uint64(len(items)))
	for _, it := range items {
		if g.ckind == ckDot {
			var b []byte
			for _, f := range g.dots {
				fb, ok, err := w.field(g.body, f, it)
				if err != nil {
					return nil, err
				}
				if ok {
					b = fb
					break
				}
			}
			if b == nil {
				b = []byte{0xf6}
			}
			out = append(out, b...)
			continue
		}
		o := &oNode{arr: g.ckind == ckArr}
		if err := w.build(g.body, g.cbody, o, it); err != nil {
			return nil, err
		}
		out, _ = w.serialize(out, o, true)
	}
	return out, nil
}

// gap is what stands at a position below the highest present one that has
// nothing to write (ruling 23).
func gap(n *cNode) byte {
	if n != nil && n.walked() {
		if n.arr {
			return 0x80
		}
		return 0xa0
	}
	return 0xf6
}

// serialize writes a place; ok is false when nothing is written there. A
// top item, and a group item, is written even when empty.
func (w *cborWriter) serialize(out []byte, o *oNode, top bool) ([]byte, bool) {
	if o.leaf != nil {
		return append(out, o.leaf...), true
	}
	if o.arr {
		encs := map[uint64][]byte{}
		var hi uint64
		for pos, c := range o.a {
			if b, ok := w.serialize(nil, c, false); ok {
				encs[pos] = b
				if pos >= hi {
					hi = pos
				}
			}
		}
		if len(encs) == 0 {
			if top {
				return append(out, 0x80), true
			}
			return out, false
		}
		out = cborHead(out, 4, hi+1)
		for i := uint64(0); i <= hi; i++ {
			if b, ok := encs[i]; ok {
				out = append(out, b...)
				continue
			}
			out = append(out, gap(o.cn.kid(posID(i))))
		}
		return out, true
	}
	var pairs []cborPair
	for k, c := range o.m {
		if b, ok := w.serialize(nil, c, false); ok {
			pairs = append(pairs, cborPair{key: k, val: b})
		}
	}
	if len(pairs) == 0 {
		if top {
			return append(out, 0xa0), true
		}
		return out, false
	}
	return cborWriteMap(out, pairs), true
}

// cborResidueStep is one step of a residue path: a step of the path
// grammar, or as the last step the encoded key `#<hex>` of a key that is
// not addressable.
type cborResidueStep struct {
	st  cStep
	key []byte // the deterministic encoding of a `#` key; nil for a step
}

// parseCBORResiduePath reads the locator of a residue entry.
func parseCBORResiduePath(s string) ([]cborResidueStep, bool) {
	parts := strings.Split(s, ".")
	out := make([]cborResidueStep, 0, len(parts))
	for i, part := range parts {
		if strings.HasPrefix(part, "#") {
			if i != len(parts)-1 {
				return nil, false
			}
			b, err := hex.DecodeString(part[1:])
			if err != nil {
				return nil, false
			}
			k, err := readCBORItem(b)
			if err != nil {
				return nil, false
			}
			out = append(out, cborResidueStep{key: cborDet(nil, k)})
			continue
		}
		st, ok := parseCBORStep(part)
		if !ok {
			return nil, false
		}
		out = append(out, cborResidueStep{st: st})
	}
	return out, len(out) > 0
}

// place puts one residue item back into its map or array, unless a line
// writes at its place (ruling 21) or its path does not fit the output.
func (w *cborWriter) place(root *oNode, steps []cborResidueStep, val []byte) {
	o := root
	for i, rs := range steps {
		isPos := rs.key == nil && rs.st.kind == csPos
		if o.leaf != nil || o.arr != isPos {
			return
		}
		key := string(rs.key)
		if rs.key == nil && !isPos {
			key = string(rs.st.keyBytes())
		}
		if i == len(steps)-1 {
			if c := o.get(key, rs.st.arg, isPos); c != nil && c.written() {
				return
			}
			c := o.at(key, rs.st.arg, isPos)
			c.leaf, c.m, c.a = val, nil, nil
			return
		}
		c := o.at(key, rs.st.arg, isPos)
		if c.leaf == nil && c.m == nil && c.a == nil && c.cn == nil {
			next := steps[i+1]
			c.arr = next.key == nil && next.st.kind == csPos
		}
		o = c
	}
}

func encodeCBOR(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	w := &cborWriter{p: p}
	root := &oNode{arr: p.cbor.topArr, cn: lay.cbor}
	if g := lay.cbor.group; g != nil {
		if items, ok := rec.Lists[g.List]; ok {
			b, err := w.list(g, items)
			if err != nil {
				return nil, err
			}
			root.leaf = b
		}
	} else if err := w.build(lay, lay.cbor, root, rec); err != nil {
		return nil, err
	}
	for _, r := range ent.Residue {
		if r.Format != p.Format || r.JSON {
			continue
		}
		steps, ok := parseCBORResiduePath(r.Locator)
		if !ok {
			continue
		}
		b, err := hex.DecodeString(r.Value)
		if err != nil {
			continue
		}
		x, err := readCBORItem(b)
		if err != nil {
			continue
		}
		w.place(root, steps, cborDet(nil, x))
	}
	var out []byte
	if p.cbor.hasTag {
		out = cborHead(out, 6, p.cbor.tag)
	}
	out, _ = w.serialize(out, root, true)
	return []byte(hex.EncodeToString(out)), nil
}
