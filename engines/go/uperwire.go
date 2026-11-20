package goatxf

import (
	"encoding/hex"
	"fmt"
	"math"
	"math/bits"
	"strconv"
	"strings"
	"unicode/utf8"
)

// ASN.1 unaligned PER (spec/engine-spec.md, "Version 0.19: ASN.1 unaligned
// PER"): a sequential bits pack with `encoding uper` adds field locators whose
// bit length follows from an ASN.1 constraint and the value, `ext` blocks,
// `choice` blocks and `group … size`. Every value is read and written at the
// cursor, with no alignment but at the end of the message.

// The forms of a UPER locator.
const (
	uperInt       = iota + 1 // int:<lb>:<ub>[:ext]
	uperIntSemi              // int:<lb>:
	uperIntUnc               // int::
	uperEnum                 // enum:<n>[:ext]
	uperChars                // chars:<lb>:<ub>
	uperCharsUnc             // chars:
	uperOctets               // octets:<lb>:<ub>
	uperOctetsUnc            // octets:
)

// The transforms a UPER locator takes.
const (
	uperTfInt   = iota + 1 // uint, twos: the integer value
	uperTfScale            // uscale, sscale: v * f + o
	uperTfASCII            // ascii on chars
	uperTfHex              // hex on octets
	uperTfUTF8             // utf8 on octets
)

// uperLoc is one UPER locator with the transform of its field line.
type uperLoc struct {
	form   int
	lb, ub int64  // int: the bounds; chars, octets: the size bounds
	ext    bool   // int:…:ext, enum:…:ext
	n      uint64 // enum: the number of root values
	tf     int
	sc     *scale
}

// isUperLocator reports whether a bits locator has the form of a UPER
// locator (spec 0.19, ruling 9).
func isUperLocator(s string) bool {
	for _, p := range []string{"int:", "enum:", "chars:", "octets:"} {
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}

// uperNumber reads a number of a UPER locator, `choice` or `group … size`:
// an optional `-` and digits with no leading zero, `-0` refused, within 64
// signed bits (ruling 15).
func uperNumber(s string) (int64, bool) {
	d := strings.TrimPrefix(s, "-")
	if d == "" || (d[0] == '0' && (len(d) > 1 || len(d) < len(s))) {
		return 0, false
	}
	for _, c := range d {
		if c < '0' || c > '9' {
			return 0, false
		}
	}
	v, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// uperCount reads a number of a `choice`, `alt` or `group … size` line:
// digits with no leading zero and no sign (ruling 15).
func uperCount(s string) (int64, bool) {
	if strings.HasPrefix(s, "-") {
		return 0, false
	}
	return uperNumber(s)
}

// constrainedBits is the number of bits of a constrained whole number of
// range r = ub - lb: the fewest that hold r.
func constrainedBits(r uint64) int { return bits.Len64(r) }

// parseUperLocator reads a UPER locator. Every failure is bad-directive.
func parseUperLocator(s string) (*uperLoc, error) {
	parts := strings.Split(s, ":")
	bad := func() (*uperLoc, error) {
		return nil, fmt.Errorf("%q is not a UPER locator (int:<lb>:<ub>[:ext], int:<lb>:, int::, enum:<n>[:ext], chars:<lb>:<ub>, chars:, octets:<lb>:<ub>, octets:)", s)
	}
	u := &uperLoc{}
	switch parts[0] {
	case "int":
		switch {
		case len(parts) == 3 && parts[1] == "" && parts[2] == "":
			u.form = uperIntUnc
		case len(parts) == 3 && parts[2] == "":
			lb, ok := uperNumber(parts[1])
			if !ok {
				return bad()
			}
			u.form, u.lb = uperIntSemi, lb
		case len(parts) == 3 || (len(parts) == 4 && parts[3] == "ext"):
			lb, ok1 := uperNumber(parts[1])
			ub, ok2 := uperNumber(parts[2])
			if !ok1 || !ok2 || lb > ub {
				return bad()
			}
			u.form, u.lb, u.ub, u.ext = uperInt, lb, ub, len(parts) == 4
		default:
			return bad()
		}
	case "enum":
		if len(parts) != 2 && !(len(parts) == 3 && parts[2] == "ext") {
			return bad()
		}
		n, ok := uperNumber(parts[1])
		if !ok || n < 1 || n > 65536 {
			return bad()
		}
		u.form, u.n, u.ext = uperEnum, uint64(n), len(parts) == 3
	case "chars", "octets":
		switch {
		case len(parts) == 2 && parts[1] == "":
			u.form = uperCharsUnc
		case len(parts) == 3:
			lb, ok1 := uperNumber(parts[1])
			ub, ok2 := uperNumber(parts[2])
			if !ok1 || !ok2 || lb < 0 || lb > ub || ub >= 65536 {
				return bad()
			}
			u.form, u.lb, u.ub = uperChars, lb, ub
		default:
			return bad()
		}
		if parts[0] == "octets" {
			u.form += uperOctets - uperChars
		}
	default:
		return bad()
	}
	return u, nil
}

// resolveUperField binds the locator and the transform of a field line of a
// UPER pack whose locator is a UPER form. A known transform the locator does
// not take is bad-directive; an unknown name keeps its error of 0.1
// (ruling 19).
func resolveUperField(f *Field) (ErrorKind, error) {
	u, err := parseUperLocator(f.Locator)
	if err != nil {
		return ErrBadDirective, err
	}
	name := f.Transform
	takes := ""
	switch u.form {
	case uperInt, uperIntSemi, uperIntUnc:
		takes = "uint, twos, uscale, sscale"
		switch {
		case name == "uint", name == "twos":
			u.tf = uperTfInt
		case strings.HasPrefix(name, "uscale:"), strings.HasPrefix(name, "sscale:"):
			// A fraction factor is unsigned on every wire (0.15 ruling 25).
			if err := checkUnsignedFraction(name); err != nil {
				return ErrBadDirective, err
			}
			sc, err := parseScale(name)
			if err != nil {
				return ErrUnknownTransform, err
			}
			u.tf, u.sc = uperTfScale, sc
		}
	case uperEnum:
		takes = "uint"
		if name == "uint" {
			u.tf = uperTfInt
		}
	case uperChars, uperCharsUnc:
		takes = "ascii"
		if name == "ascii" {
			u.tf = uperTfASCII
		}
	case uperOctets, uperOctetsUnc:
		takes = "hex, utf8"
		switch name {
		case "hex":
			u.tf = uperTfHex
		case "utf8":
			u.tf = uperTfUTF8
		}
	}
	if u.tf == 0 {
		// The value transforms of 0.15 are known transforms too: on a UPER
		// locator they are bad-directive (0.19, Transforms on UPER locators).
		known := isBitsTransformName(name) || isTextTransformName(name) || isPBTransformName(name) ||
			isTLVOnlyTransform(name) || isTextOnlyTransform(name) || v015Base(name) != ""
		if known {
			return ErrBadDirective, fmt.Errorf("transform %q is not valid on the locator %s (it takes %s)", name, f.Locator, takes)
		}
		return ErrUnknownTransform, fmt.Errorf("unknown transform %q (the locator %s takes %s)", name, f.Locator, takes)
	}
	if f.Swap || f.Trim {
		return ErrBadDirective, fmt.Errorf("`swap` and `trim` are not valid on a UPER locator")
	}
	f.uper = u
	return "", nil
}

// ---- decode ----

// left is the number of bits the lines may still read.
func (r *seqReader) left() uint64 {
	if r.pos >= r.limit {
		return 0
	}
	return uint64(r.limit - r.pos)
}

// u reads n (0..64) bits at the cursor; running past the input or the
// extent is malformed-wire.
func (r *seqReader) u(n int, what string) (uint64, error) {
	if uint64(n) > r.left() {
		return 0, r.malformed("%s needs %d bit(s) at bit %d and %d are left", what, n, r.pos, r.left())
	}
	at := r.pos
	r.pos += n
	if n == 0 {
		return 0, nil
	}
	return getBits(r.data, at, n, msbOrder), nil
}

// lenDet reads a length determinant (X.691): 0 and 7 bits, or 10 and 14
// bits; 11 (a fragmented length) is malformed-wire.
func (r *seqReader) lenDet(what string) (uint64, error) {
	b, err := r.u(1, what)
	if err != nil || b == 0 {
		if err != nil {
			return 0, err
		}
		return r.u(7, what)
	}
	if b, err = r.u(1, what); err != nil {
		return 0, err
	}
	if b == 1 {
		return 0, r.malformed("%s: a fragmented length (first bits 11) at bit %d", what, r.pos-2)
	}
	return r.u(14, what)
}

// octets reads c octets at the cursor, after comparing c with the bits left.
func (r *seqReader) octets(c uint64, what string) ([]byte, error) {
	if c > r.left()/8 {
		return nil, r.malformed("%s states %d octet(s) at bit %d and %d bit(s) are left", what, c, r.pos, r.left())
	}
	out := make([]byte, c)
	for i := range out {
		out[i] = byte(getBits(r.data, r.pos, 8, msbOrder))
		r.pos += 8
	}
	return out, nil
}

// skipOctets passes over c octets, after comparing c with the bits left.
func (r *seqReader) skipOctets(c uint64, what string) error {
	if c > r.left()/8 {
		return r.malformed("%s states %d octet(s) at bit %d and %d bit(s) are left", what, c, r.pos, r.left())
	}
	r.pos += int(c) * 8
	return nil
}

// intOctets reads an octet count then that many octets of an integer. big is
// set when there are more than 8 octets (passed over); a count of 0 is
// malformed-wire (ruling 5).
func (r *seqReader) intOctets(what string) (raw uint64, n int, big bool, err error) {
	c, err := r.lenDet(what)
	if err != nil {
		return 0, 0, false, err
	}
	if c == 0 {
		return 0, 0, false, r.malformed("%s: an integer of 0 octets", what)
	}
	if c > 8 {
		return 0, 0, true, r.skipOctets(c, what)
	}
	b, err := r.octets(c, what)
	if err != nil {
		return 0, 0, false, err
	}
	return beUint(b), int(c), false, nil
}

// nsnn reads a normally small non-negative whole number. big is set when its
// long form has more than 8 octets; an octet count of 0 is malformed-wire
// (ruling 19).
func (r *seqReader) nsnn(what string) (v uint64, big bool, err error) {
	b, err := r.u(1, what)
	if err != nil {
		return 0, false, err
	}
	if b == 0 {
		v, err = r.u(6, what)
		return v, false, err
	}
	raw, _, big, err := r.intOctets(what)
	return raw, big, err
}

// constrained reads a constrained whole number of range rng; a value above
// it is outside the constraint and malformed-wire.
func (r *seqReader) constrained(rng uint64, what string) (uint64, error) {
	off, err := r.u(constrainedBits(rng), what)
	if err != nil {
		return 0, err
	}
	if off > rng {
		return 0, r.malformed("%s: %d above the lower bound lies outside the constraint (at most %d)", what, off, rng)
	}
	return off, nil
}

// uperField reads one field line with a UPER locator.
func (r *seqReader) uperField(f *Field) error {
	d := r.d
	// A line at or after the end of a `length` extent reads as absent.
	if r.beyond() {
		return nil
	}
	u := f.uper
	what := "field " + f.Key
	var v Value
	failed := ""
	intValue := func(i int64) Value {
		if u.tf == uperTfScale {
			return Value{Kind: KindFloat, F: u.sc.up(float64(i))}
		}
		return Value{Kind: KindInt, I: i}
	}
	switch u.form {
	case uperInt:
		ext := uint64(0)
		if u.ext {
			b, err := r.u(1, what)
			if err != nil {
				return err
			}
			ext = b
		}
		if ext == 0 {
			off, err := r.constrained(uint64(u.ub)-uint64(u.lb), what)
			if err != nil {
				return err
			}
			v = intValue(int64(uint64(u.lb) + off))
			break
		}
		raw, n, big, err := r.intOctets(what)
		if err != nil {
			return err
		}
		if big {
			failed = "an integer of more than 8 octets"
			break
		}
		v = intValue(signExtend(raw, 8*n))
	case uperIntSemi:
		raw, _, big, err := r.intOctets(what)
		if err != nil {
			return err
		}
		if big {
			failed = "an integer of more than 8 octets"
			break
		}
		if raw > uint64(math.MaxInt64)-uint64(u.lb) {
			failed = fmt.Sprintf("%d above the lower bound %d does not fit a signed 64-bit integer", raw, u.lb)
			break
		}
		v = intValue(int64(uint64(u.lb) + raw))
	case uperIntUnc:
		raw, n, big, err := r.intOctets(what)
		if err != nil {
			return err
		}
		if big {
			failed = "an integer of more than 8 octets"
			break
		}
		v = intValue(signExtend(raw, 8*n))
	case uperEnum:
		ext := uint64(0)
		if u.ext {
			b, err := r.u(1, what)
			if err != nil {
				return err
			}
			ext = b
		}
		if ext == 0 {
			idx, err := r.constrained(u.n-1, what)
			if err != nil {
				return err
			}
			v = intValue(int64(idx))
			break
		}
		idx, big, err := r.nsnn(what)
		if err != nil {
			return err
		}
		if big || idx > uint64(math.MaxInt64)-u.n {
			failed = "an extension index that does not fit a signed 64-bit integer"
			break
		}
		v = intValue(int64(u.n + idx))
	case uperChars, uperCharsUnc, uperOctets, uperOctetsUnc:
		var count uint64
		var err error
		if u.form == uperChars || u.form == uperOctets {
			count, err = r.constrained(uint64(u.ub-u.lb), what+" count")
			count += uint64(u.lb)
		} else {
			count, err = r.lenDet(what)
		}
		if err != nil {
			return err
		}
		if u.form == uperChars || u.form == uperCharsUnc {
			if count > r.left()/7 {
				return r.malformed("%s states %d character(s) at bit %d and %d bit(s) are left", what, count, r.pos, r.left())
			}
			buf := make([]byte, count)
			for i := range buf {
				buf[i] = byte(getBits(r.data, r.pos, 7, msbOrder))
				r.pos += 7
			}
			v = Value{Kind: KindString, S: string(buf)}
			break
		}
		b, err := r.octets(count, what)
		if err != nil {
			return err
		}
		if u.tf == uperTfHex {
			v = Value{Kind: KindString, S: hex.EncodeToString(b)}
		} else if !utf8.Valid(b) {
			failed = "the octets are not UTF-8"
		} else {
			v = Value{Kind: KindString, S: string(b)}
		}
	}
	if failed != "" {
		d.fail(f, failed)
		return nil
	}
	d.store(f, v)
	for _, a := range f.also {
		d.store(a, v)
	}
	return nil
}

// extBlock reads an `ext` block: one bit, the block, and with the bit 1 the
// extension additions, which are skipped (spec 0.19, "Extension markers on a
// SEQUENCE").
func (r *seqReader) extBlock(n *seqNode) error {
	if r.beyond() {
		return nil
	}
	bit, err := r.u(1, "the extension bit")
	if err != nil {
		return err
	}
	if err := r.nodes(n.body); err != nil {
		return err
	}
	if bit == 0 {
		return nil
	}
	// The number of additions as a normally small length (ruling 16).
	what := "the extension additions"
	long, err := r.u(1, what)
	if err != nil {
		return err
	}
	var m uint64
	if long == 0 {
		v, err := r.u(6, what)
		if err != nil {
			return err
		}
		m = v + 1
	} else if m, err = r.lenDet(what); err != nil {
		return err
	}
	if m > r.left() {
		return r.malformed("%s: %d presence bit(s) at bit %d and %d bit(s) are left", what, m, r.pos, r.left())
	}
	present := 0
	for i := uint64(0); i < m; i++ {
		if bitAt(r.data, r.pos, msbOrder) == 1 {
			present++
		}
		r.pos++
	}
	for ; present > 0; present-- {
		c, err := r.lenDet("an open type")
		if err != nil {
			return err
		}
		if err := r.skipOctets(c, "an open type"); err != nil {
			return err
		}
	}
	return nil
}

// choice reads a `choice` block: under `ext` one bit; then the index and the
// lines of its `alt`, or with the bit 1 an extension alternative, skipped.
func (r *seqReader) choice(n *seqNode) error {
	if r.beyond() {
		return nil
	}
	if n.ext {
		bit, err := r.u(1, "the choice extension bit")
		if err != nil {
			return err
		}
		if bit == 1 {
			_, big, err := r.nsnn("the choice extension index")
			if err != nil {
				return err
			}
			if big {
				return &Error{Kind: ErrTransformDecode, Format: r.p.Format, Detail: fmt.Sprintf("the extension index of the choice on line %d has more than 8 octets", n.line)}
			}
			c, err := r.lenDet("an open type")
			if err != nil {
				return err
			}
			return r.skipOctets(c, "an open type")
		}
	}
	idx, err := r.constrained(n.num-1, "the choice index")
	if err != nil {
		return err
	}
	for _, a := range n.body {
		if a.num == idx {
			return r.nodes(a.body)
		}
	}
	return r.malformed("the choice on line %d has no alt %d", n.line, idx)
}

// sizeCount reads the count of a `group … size`.
func (r *seqReader) sizeCount(g *Group) (uint64, error) {
	what := "the count of list " + g.List
	if g.seqMode == seqSizeUnc {
		return r.lenDet(what)
	}
	off, err := r.constrained(uint64(g.sizeUB-g.sizeLB), what)
	return off + uint64(g.sizeLB), err
}

// ---- encode ----

// putU writes the low n (0..64) bits of v at the cursor.
func (w *seqWriter) putU(n int, v uint64) {
	if n == 0 {
		return
	}
	w.put(w.alloc(n), n, v)
}

// putLenDet writes a length determinant; 16384 or more (a fragmented length)
// is transform-encode.
func (w *seqWriter) putLenDet(n uint64, what string) error {
	switch {
	case n < 128:
		w.putU(8, n)
	case n < 16384:
		w.putU(16, 0x8000|n)
	default:
		return w.fail("%s: a length of %d needs a fragmented length determinant", what, n)
	}
	return nil
}

func (w *seqWriter) putOctets(b []byte) {
	for _, c := range b {
		w.putU(8, uint64(c))
	}
}

// putIntOctets writes an octet count then the low c octets of raw.
func (w *seqWriter) putIntOctets(raw uint64, c int) {
	w.putU(8, uint64(c)) // c is 1 to 8: a short length determinant
	for k := c - 1; k >= 0; k-- {
		w.putU(8, (raw>>(8*uint(k)))&0xff)
	}
}

// twosOctets is the fewest octets that hold v in two's complement.
func twosOctets(v int64) int {
	for c := 1; c < 8; c++ {
		half := int64(1) << (8*uint(c) - 1)
		if v >= -half && v < half {
			return c
		}
	}
	return 8
}

// unsignedOctets is the fewest octets, at least one, that hold u.
func unsignedOctets(u uint64) int {
	if c := (bits.Len64(u) + 7) / 8; c > 1 {
		return c
	}
	return 1
}

// putNSNN writes a normally small non-negative whole number.
func (w *seqWriter) putNSNN(v uint64) {
	if v <= 63 {
		w.putU(7, v)
		return
	}
	w.putU(1, 1)
	w.putIntOctets(v, unsignedOctets(v))
}

// uperIntValue reads the integer a value of an int or enum line stands for:
// the value, or round((x - o) / f) under a scale.
func uperIntValue(u *uperLoc, v Value) (int64, error) {
	if u.tf != uperTfScale {
		return valueToInt(v)
	}
	x, err := valueToFloat(v)
	if err != nil {
		return 0, err
	}
	// round(q) half away from zero, exact (ruling 4a of 0.11); a quotient
	// that is not finite, or a value outside 64 signed bits, does not fit
	// (4b), compared before it is narrowed.
	r := math.Round(u.sc.down(x))
	if math.IsNaN(r) || r < -9.223372036854775808e18 || r >= 9.223372036854775808e18 {
		return 0, fmt.Errorf("value %v scales to %v, which is not a 64-bit integer", x, r)
	}
	return int64(r), nil
}

// uperField writes one field line with a UPER locator. An absent key with no
// default writes the value of ruling 1.
func (w *seqWriter) uperField(f *Field, sc seqScope) error {
	p := w.p
	u := f.uper
	v, from, ok, err := seqFieldValue(p, f, sc)
	if err != nil {
		return err
	}
	fail := func(format string, a ...any) error {
		return encodeErr(p, from, fmt.Errorf(format, a...))
	}
	switch u.form {
	case uperInt, uperIntSemi, uperIntUnc, uperEnum:
		var i int64
		if ok {
			if i, err = uperIntValue(u, v); err != nil {
				return encodeErr(p, from, err)
			}
		} else if u.form == uperInt || u.form == uperIntSemi {
			i = u.lb
		}
		switch u.form {
		case uperInt:
			if i < u.lb || i > u.ub {
				if !u.ext {
					return fail("%d lies outside the constraint %d..%d", i, u.lb, u.ub)
				}
				w.putU(1, 1)
				w.putIntOctets(uint64(i), twosOctets(i))
				return nil
			}
			if u.ext {
				w.putU(1, 0)
			}
			w.putU(constrainedBits(uint64(u.ub)-uint64(u.lb)), uint64(i)-uint64(u.lb))
		case uperIntSemi:
			if i < u.lb {
				return fail("%d lies below the lower bound %d", i, u.lb)
			}
			off := uint64(i) - uint64(u.lb)
			w.putIntOctets(off, unsignedOctets(off))
		case uperIntUnc:
			w.putIntOctets(uint64(i), twosOctets(i))
		case uperEnum:
			if i < 0 {
				return fail("an enumerated index is not negative, got %d", i)
			}
			idx := uint64(i)
			if idx >= u.n {
				if !u.ext {
					return fail("index %d lies outside the %d root value(s)", idx, u.n)
				}
				w.putU(1, 1)
				w.putNSNN(idx - u.n)
				return nil
			}
			if u.ext {
				w.putU(1, 0)
			}
			w.putU(constrainedBits(u.n-1), idx)
		}
	case uperChars, uperCharsUnc, uperOctets, uperOctetsUnc:
		var b []byte
		chars := u.form == uperChars || u.form == uperCharsUnc
		switch {
		case !ok:
			// lb characters of code 0, or lb zero octets (rulings 1 and 18).
			b = make([]byte, u.lb)
		default:
			s, err := encString(v)
			if err != nil {
				return encodeErr(p, from, err)
			}
			switch u.tf {
			case uperTfASCII:
				for k := 0; k < len(s); k++ {
					if s[k] > 127 {
						return fail("the text holds a character above 127")
					}
				}
				b = []byte(s)
			case uperTfHex:
				if len(s)%2 != 0 || !isHex(s) {
					return fail("%q is not hex text of an even number of digits", s)
				}
				if b, err = hex.DecodeString(s); err != nil {
					return encodeErr(p, from, err)
				}
			default:
				b = []byte(s)
			}
		}
		count := uint64(len(b))
		if u.form == uperChars || u.form == uperOctets {
			if count < uint64(u.lb) || count > uint64(u.ub) {
				return fail("a count of %d lies outside %d..%d", count, u.lb, u.ub)
			}
			w.putU(constrainedBits(uint64(u.ub-u.lb)), count-uint64(u.lb))
		} else if err := w.putLenDet(count, "field "+f.Key); err != nil {
			return err
		}
		if chars {
			for _, c := range b {
				w.putU(7, uint64(c))
			}
		} else {
			w.putOctets(b)
		}
	}
	return nil
}

// choice writes a `choice` block: the first `alt`, in line order, that has
// content, else the first `alt`; under `ext` the bit 0 first.
func (w *seqWriter) choice(n *seqNode, sc seqScope) error {
	alt := w.choiceAlt(n, sc)
	if n.ext {
		w.putU(1, 0)
	}
	w.putU(constrainedBits(n.num-1), alt.num)
	return w.emit(alt.body, sc, false)
}

// sizeItems returns the items a `group … size` writes, after writing their
// count: an absent list is lb items with no keys.
func (w *seqWriter) sizeItems(g *Group, sc seqScope) ([]*Item, error) {
	items, present := sc.rec.Lists[g.List]
	if !present && g.seqMode == seqSize && g.sizeLB > 0 {
		items = make([]*Item, g.sizeLB)
		for i := range items {
			items[i] = NewItem()
		}
	}
	count := uint64(len(items))
	if g.seqMode == seqSizeUnc {
		return items, w.putLenDet(count, "list "+g.List)
	}
	if count < uint64(g.sizeLB) || count > uint64(g.sizeUB) {
		return nil, w.fail("list %s: %d item(s) lie outside the size %d..%d", g.List, count, g.sizeLB, g.sizeUB)
	}
	w.putU(constrainedBits(uint64(g.sizeUB-g.sizeLB)), count-uint64(g.sizeLB))
	return items, nil
}

// choiceAlt is the alt an encode of a choice writes: the first, in line
// order, that has content (spec 0.19), else the first.
func (w *seqWriter) choiceAlt(n *seqNode, sc seqScope) *seqNode {
	for _, a := range n.body {
		if w.content(a.body, sc) {
			return a
		}
	}
	return n.body[0]
}

// uperReadBack records in the scope's decoded values what a decode of the
// bits a UPER field line writes would hold, for a switch on its key (0.20,
// Encode): the line is written to a scratch buffer and read back. A value
// that does not write or does not read back marks the keys of the line, and
// of its `also` lines, as not reading back (0.20 ruling 31).
func uperReadBack(w *seqWriter, f *Field, sc seqScope) {
	keys := append([]*Field{f}, f.also...)
	bad := func() {
		for _, k := range keys {
			sc.bad[k.Key] = true
		}
	}
	tmp := &seqWriter{p: w.p, buf: &bitBuf{}, pres: map[*seqPresenceDef][]bool{}}
	if err := tmp.uperField(f, sc); err != nil {
		bad()
		return
	}
	tmp.buf.need(tmp.pos + 8)
	d := &decodeState{pack: w.p, ent: NewEntity(), rec: NewItem(), nbits: tmp.pos}
	r := &seqReader{d: d, p: w.p, data: tmp.buf.data, limit: tmp.pos, pres: map[*seqPresenceDef][]bool{}, read: map[*seqCase]bool{}}
	if err := r.uperField(f); err != nil || len(d.failed) > 0 {
		bad()
		return
	}
	for _, k := range keys {
		if v, ok := d.rec.Fields[k.Key]; ok {
			if _, done := sc.vals[k.Key]; !done {
				sc.vals[k.Key] = v
			}
		}
	}
}
