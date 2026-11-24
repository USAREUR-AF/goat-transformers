package goatxf

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"
)

// Value transforms (spec/engine-spec.md, "Version 0.15: value transforms"):
// integer scales with exact factors, sign and magnitude, scaled IEEE floats,
// 6-bit and 7-bit character sets and octal digits on `bits`; `scale` and
// `iscale` on the text wires. Every error found while reading one of these
// transforms on a field line is bad-directive.

// v015Bits and v015Text are the transforms of this version by wire.
var v015Bits = map[string]bool{"uiscale": true, "siscale": true, "smag": true, "smscale": true, "f32scale": true, "f64scale": true, "chars": true, "octal": true}
var v015Text = map[string]bool{"scale": true, "iscale": true}

// v015Base returns the name of a transform of this version that spec names
// (the text before the first `:`), or "" when it is not one.
func v015Base(spec string) string {
	base, _, _ := strings.Cut(spec, ":")
	if v015Bits[base] || v015Text[base] {
		return base
	}
	return ""
}

var (
	bigTwo32 = new(big.Int).Lsh(big.NewInt(1), 32)
	bigTen   = big.NewInt(10)
)

// --- exact numbers ---

// exactFactor is a factor in lowest terms: num may be negative, den > 0.
type exactFactor struct{ num, den *big.Int }

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// parseExactDecimal reads `[-]digits[.digits]` as the exact fraction its
// digits state.
func parseExactDecimal(s string) (*big.Rat, bool) {
	t := strings.TrimPrefix(s, "-")
	ip, fp, hasFrac := strings.Cut(t, ".")
	if !allDigits(ip) || (hasFrac && !allDigits(fp)) {
		return nil, false
	}
	n, _ := new(big.Int).SetString(ip+fp, 10)
	d := new(big.Int).Exp(bigTen, big.NewInt(int64(len(fp))), nil)
	if t != s {
		n.Neg(n)
	}
	return new(big.Rat).SetFrac(n, d), true
}

// parseExactFactor reads the factor of an integer scale (Exact factors,
// rulings 9, 11 and 19): a decimal, or `[-]num/den` with den unsigned and
// not 0; in lowest terms numerator and denominator at most 2^32, not 0.
func parseExactFactor(s string) (*exactFactor, error) {
	var r *big.Rat
	if a, b, ok := strings.Cut(s, "/"); ok {
		an := strings.TrimPrefix(a, "-")
		if !allDigits(an) || !allDigits(b) {
			return nil, fmt.Errorf("factor %q is not <num>/<den> of decimal integers (a `-` only before num)", s)
		}
		n, _ := new(big.Int).SetString(an, 10)
		d, _ := new(big.Int).SetString(b, 10)
		if d.Sign() == 0 {
			return nil, fmt.Errorf("factor %q has denominator 0", s)
		}
		if an != a {
			n.Neg(n)
		}
		r = new(big.Rat).SetFrac(n, d)
	} else {
		var ok bool
		if r, ok = parseExactDecimal(s); !ok {
			return nil, fmt.Errorf("factor %q is not a decimal [-]digits[.digits] or a fraction <num>/<den>", s)
		}
	}
	if r.Sign() == 0 {
		return nil, fmt.Errorf("factor %q is 0", s)
	}
	n, d := new(big.Int).Set(r.Num()), new(big.Int).Set(r.Denom())
	if new(big.Int).Abs(n).Cmp(bigTwo32) > 0 || d.Cmp(bigTwo32) > 0 {
		return nil, fmt.Errorf("factor %q in lowest terms is %s/%s; numerator and denominator must each be at most 2^32", s, n, d)
	}
	return &exactFactor{num: n, den: d}, nil
}

// parseExactOffset reads `[-]digits` with absolute value below 2^63.
func parseExactOffset(s string) (int64, error) {
	t := strings.TrimPrefix(s, "-")
	if !allDigits(t) {
		return 0, fmt.Errorf("offset %q is not a decimal integer [-]digits", s)
	}
	n, _ := new(big.Int).SetString(t, 10)
	if !n.IsInt64() {
		return 0, fmt.Errorf("offset %q: its absolute value must be below 2^63", s)
	}
	v := n.Int64()
	if t != s {
		v = -v
	}
	return v, nil
}

// exactScale is `<factor>[:<offset>]` of an integer scale.
type exactScale struct {
	f      *exactFactor
	offset int64
}

func parseExactScale(spec string) (*exactScale, error) {
	parts := strings.Split(spec, ":")
	if len(parts) != 2 && len(parts) != 3 {
		return nil, fmt.Errorf("%s needs <factor>[:<offset>], got %q", parts[0], spec)
	}
	f, err := parseExactFactor(parts[1])
	if err != nil {
		return nil, err
	}
	sc := &exactScale{f: f}
	if len(parts) == 3 {
		if sc.offset, err = parseExactOffset(parts[2]); err != nil {
			return nil, err
		}
	}
	return sc, nil
}

// roundRat rounds r half away from zero (ruling 4).
func roundRat(r *big.Rat) *big.Int {
	n := new(big.Int).Abs(r.Num())
	d := r.Denom()
	q, m := new(big.Int).QuoRem(n, d, new(big.Int))
	if m.Lsh(m, 1).Cmp(d) >= 0 {
		q.Add(q, big.NewInt(1))
	}
	if r.Sign() < 0 {
		q.Neg(q)
	}
	return q
}

// up is the decode direction: round(v × factor) + offset, which must lie in
// the signed 64-bit range (ruling 10).
func (sc *exactScale) up(v *big.Rat) (int64, error) {
	p := new(big.Rat).Mul(v, new(big.Rat).SetFrac(sc.f.num, sc.f.den))
	r := roundRat(p)
	r.Add(r, big.NewInt(sc.offset))
	if !r.IsInt64() {
		return 0, fmt.Errorf("result %s is outside the signed 64-bit range", r)
	}
	return r.Int64(), nil
}

// quotient is the exact (x − offset) / factor.
func (sc *exactScale) quotient(x *big.Rat) *big.Rat {
	q := new(big.Rat).Sub(x, new(big.Rat).SetInt64(sc.offset))
	return q.Mul(q, new(big.Rat).SetFrac(sc.f.den, sc.f.num))
}

// valueToRat reads a model value as an exact number: an integer, the exact
// value of a double, or a decimal text.
func valueToRat(v Value) (*big.Rat, error) {
	switch v.Kind {
	case KindInt:
		return new(big.Rat).SetInt64(v.I), nil
	case KindFloat:
		if math.IsNaN(v.F) || math.IsInf(v.F, 0) {
			return nil, fmt.Errorf("non-finite float %v", v.F)
		}
		return new(big.Rat).SetFloat64(v.F), nil
	case KindString:
		if r, err := parseExactNumberText(strings.TrimSpace(v.S)); err == nil {
			return r, nil
		}
		return nil, fmt.Errorf("%q is not a decimal number", v.S)
	}
	return nil, fmt.Errorf("no value")
}

// parseExactNumberText reads `-?digits(.digits)?([eE][+-]?digits)?` as an
// exact number; an exponent above 400 in absolute value is refused (ruling 9).
func parseExactNumberText(s string) (*big.Rat, error) {
	bad := func() (*big.Rat, error) {
		return nil, fmt.Errorf("%q is not a number -?digits(.digits)?([eE][+-]?digits)?", s)
	}
	mant, exp := s, ""
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		mant, exp = s[:i], s[i+1:]
	}
	neg := strings.HasPrefix(mant, "-")
	if neg {
		mant = mant[1:]
	}
	ip, fp, hasFrac := strings.Cut(mant, ".")
	if !allDigits(ip) || (hasFrac && !allDigits(fp)) {
		return bad()
	}
	e := 0
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		eneg := false
		if exp != "" && (exp[0] == '+' || exp[0] == '-') {
			eneg = exp[0] == '-'
			exp = exp[1:]
		}
		if !allDigits(exp) {
			return bad()
		}
		t := strings.TrimLeft(exp, "0")
		if len(t) > 3 {
			return nil, fmt.Errorf("%q: the exponent is above 400 in absolute value", s)
		}
		if t != "" {
			e, _ = strconv.Atoi(t)
		}
		if e > 400 {
			return nil, fmt.Errorf("%q: the exponent is above 400 in absolute value", s)
		}
		if eneg {
			e = -e
		}
	}
	n, _ := new(big.Int).SetString(ip+fp, 10)
	if neg {
		n.Neg(n)
	}
	e -= len(fp)
	r := new(big.Rat)
	if e >= 0 {
		n.Mul(n, new(big.Int).Exp(bigTen, big.NewInt(int64(e)), nil))
		r.SetInt(n)
	} else {
		r.SetFrac(n, new(big.Int).Exp(bigTen, big.NewInt(int64(-e)), nil))
	}
	return r, nil
}

// formatExactDecimal writes q in plain decimal notation with at most 18
// fraction digits and no trailing zero (rulings 21); a quotient that needs
// more is an error.
func formatExactDecimal(q *big.Rat) (string, error) {
	pow := new(big.Int).Exp(bigTen, big.NewInt(18), nil)
	scaled := new(big.Rat).Mul(q, new(big.Rat).SetInt(pow))
	if !scaled.IsInt() {
		return "", fmt.Errorf("quotient %s does not terminate within 18 fraction digits", q.RatString())
	}
	n := new(big.Int).Abs(scaled.Num())
	ip, fp := new(big.Int).QuoRem(n, pow, new(big.Int))
	var b strings.Builder
	if q.Sign() < 0 {
		b.WriteByte('-')
	}
	b.WriteString(ip.String())
	if fp.Sign() != 0 {
		f := fmt.Sprintf("%018s", fp.String())
		b.WriteByte('.')
		b.WriteString(strings.TrimRight(f, "0"))
	}
	return b.String(), nil
}

// --- float scales: factor and offset as sscale reads them ---

// parseFloatScale reads `<factor>[:<offset>]` of scale, smscale, f32scale and
// f64scale as sscale does (rulings 12 and 25): a fraction has unsigned num
// and den.
func parseFloatScale(spec string) (*scale, error) {
	if err := checkUnsignedFraction(spec); err != nil {
		return nil, err
	}
	sc, err := parseScale(spec)
	if err != nil {
		return nil, err
	}
	// Only uscale and sscale on bits take <places> (0.55).
	if sc.places >= 0 {
		return nil, fmt.Errorf("%s takes no <places> argument, got %q", strings.SplitN(spec, ":", 2)[0], spec)
	}
	return sc, nil
}

// checkUnsignedFraction refuses a fraction factor whose num or den is not
// unsigned digits (0.15 ruling 25, for every float scale transform; the
// derive function scale: keeps ruling 2c of 0.11).
func checkUnsignedFraction(spec string) error {
	parts := strings.Split(spec, ":")
	if len(parts) < 2 {
		return nil
	}
	if a, b, ok := strings.Cut(parts[1], "/"); ok && (!allDigits(a) || !allDigits(b)) {
		return fmt.Errorf("%s fraction %q must be <num>/<den> of two unsigned decimal integers", parts[0], parts[1])
	}
	return nil
}

// fup is v × factor + offset in doubles, in the order of ruling 1 of 0.5;
// the conversions keep the product and the sum two roundings.
func (sc *scale) fup(v float64) float64 {
	if sc.frac {
		return float64(float64(v*sc.num)/sc.den) + sc.offset
	}
	return float64(v*sc.factor) + sc.offset
}

// fdown is (x − offset) / factor, not rounded (ruling 8).
func (sc *scale) fdown(x float64) float64 {
	if sc.frac {
		return float64(float64(x-sc.offset)*sc.den) / sc.num
	}
	return float64(x-sc.offset) / sc.factor
}

func finite(f float64) bool { return !math.IsNaN(f) && !math.IsInf(f, 0) }

// --- bits transforms ---

func newIntScale(spec string, signed bool) (*bitsTransform, error) {
	sc, err := parseExactScale(spec)
	if err != nil {
		return nil, err
	}
	return &bitsTransform{
		name: spec,
		decode: func(raw uint64, length int) (Value, error) {
			var v *big.Rat
			if signed {
				v = new(big.Rat).SetInt64(signExtend(raw, length))
			} else {
				v = new(big.Rat).SetInt(new(big.Int).SetUint64(maskBits(raw, length)))
			}
			i, err := sc.up(v)
			if err != nil {
				return Value{}, err
			}
			return Value{Kind: KindInt, I: i}, nil
		},
		encode: func(v Value, length int) (uint64, error) {
			x, err := valueToRat(v)
			if err != nil {
				return 0, err
			}
			r := roundRat(sc.quotient(x))
			lo, hi := new(big.Int), new(big.Int).Lsh(big.NewInt(1), uint(length))
			if signed {
				hi.Rsh(hi, 1)
				lo.Neg(hi)
			}
			if r.Cmp(lo) < 0 || r.Cmp(hi) >= 0 {
				kind := "unsigned"
				if signed {
					kind = "two's-complement"
				}
				return 0, fmt.Errorf("value %s scales to %s, which does not fit a %d-bit %s field", v.String(), r, length, kind)
			}
			if signed {
				return maskBits(uint64(r.Int64()), length), nil
			}
			return r.Uint64(), nil
		},
	}, nil
}

// smagDecode reads the field as sign and magnitude.
func smagDecode(raw uint64, length int) int64 {
	raw = maskBits(raw, length)
	mag := int64(maskBits(raw, length-1))
	if raw>>uint(length-1)&1 == 1 {
		return -mag
	}
	return mag
}

var bitsSmag = &bitsTransform{
	name: "smag",
	decode: func(raw uint64, length int) (Value, error) {
		return Value{Kind: KindInt, I: smagDecode(raw, length)}, nil
	},
	encode: func(v Value, length int) (uint64, error) {
		x, err := valueToInt(v)
		if err != nil {
			return 0, err
		}
		var sign, mag uint64
		if x < 0 {
			sign, mag = 1, uint64(-x) // -MinInt64 wraps to 2^63, refused below
		} else {
			mag = uint64(x)
		}
		if mag>>uint(length-1) != 0 {
			return 0, fmt.Errorf("magnitude of %d does not fit %d bits", x, length-1)
		}
		return sign<<uint(length-1) | mag, nil
	},
}

func newSmscale(spec string) (*bitsTransform, error) {
	sc, err := parseFloatScale(spec)
	if err != nil {
		return nil, err
	}
	return &bitsTransform{
		name: spec,
		decode: func(raw uint64, length int) (Value, error) {
			r := sc.up(float64(smagDecode(raw, length)))
			if !finite(r) {
				return Value{}, fmt.Errorf("value scales to %v, which is not finite", r)
			}
			return Value{Kind: KindFloat, F: r}, nil
		},
		encode: func(v Value, length int) (uint64, error) {
			x, err := valueToFloat(v)
			if err != nil {
				return 0, err
			}
			// scale.down does not round (rulings 4a and 4b of 0.11); smscale
			// rounds half away from zero as sscale does.
			r := math.Round(sc.down(x))
			if !finite(r) {
				return 0, fmt.Errorf("value %v does not scale to a number", x)
			}
			// The sign comes from the integer after rounding (ruling 15).
			var sign uint64
			if r < 0 {
				sign, r = 1, -r
			}
			if r >= math.Ldexp(1, length-1) {
				return 0, fmt.Errorf("value %v scales to a magnitude that does not fit %d bits", x, length-1)
			}
			return sign<<uint(length-1) | uint64(r), nil
		},
	}, nil
}

func newFloatBitsScale(spec string, single bool) (*bitsTransform, error) {
	sc, err := parseFloatScale(spec)
	if err != nil {
		return nil, err
	}
	return &bitsTransform{
		name: spec,
		decode: func(raw uint64, length int) (Value, error) {
			var w float64
			if single {
				w = float64(math.Float32frombits(uint32(raw)))
			} else {
				w = math.Float64frombits(raw)
			}
			r := sc.fup(w)
			if !finite(r) {
				return Value{}, fmt.Errorf("wire value %v scales to %v, which is not finite", w, r)
			}
			return Value{Kind: KindFloat, F: r}, nil
		},
		encode: func(v Value, length int) (uint64, error) {
			x, err := valueToFloat(v)
			if err != nil {
				return 0, err
			}
			r := sc.fdown(x)
			if single {
				f, err := narrowToSingle(r)
				if err != nil {
					return 0, err
				}
				return uint64(math.Float32bits(f)), nil
			}
			if !finite(r) {
				return 0, fmt.Errorf("value %v scales to %v, which is not finite", x, r)
			}
			return math.Float64bits(r), nil
		},
	}, nil
}

// charSet is one character set of `chars:<set>`.
type charSet struct {
	width int
	pad   byte                        // the padding code
	dec   func(c uint64) (byte, bool) // code -> character
	enc   func(b byte) (uint64, bool) // character -> code
	space bool                        // decode also removes trailing spaces
	nul   bool                        // ascii7: NUL is the padding and ends the text
}

var charSets = map[string]*charSet{
	"icao6": {
		width: 6, pad: 32, space: true,
		dec: func(c uint64) (byte, bool) {
			switch {
			case c >= 1 && c <= 26:
				return byte('A' + c - 1), true
			case c == 32:
				return ' ', true
			case c >= 48 && c <= 57:
				return byte(c), true
			}
			return 0, false
		},
		enc: func(b byte) (uint64, bool) {
			switch {
			case b >= 'A' && b <= 'Z':
				return uint64(b-'A') + 1, true
			case b == ' ', b >= '0' && b <= '9':
				return uint64(b), true
			}
			return 0, false
		},
	},
	"ais6": {
		width: 6, pad: 0, space: true,
		dec: func(c uint64) (byte, bool) {
			if c < 32 {
				return byte(c + 64), true
			}
			return byte(c), true
		},
		enc: func(b byte) (uint64, bool) {
			switch {
			case b >= 64 && b <= 95:
				return uint64(b - 64), true
			case b >= 32 && b <= 63:
				return uint64(b), true
			}
			return 0, false
		},
	},
	// ascii8 (0.22): as ascii7, eight bits wide.
	"ascii8": {
		width: 8, pad: 0, nul: true,
		dec: func(c uint64) (byte, bool) {
			if c == 0 || (c >= 32 && c <= 126) {
				return byte(c), true
			}
			return 0, false
		},
		enc: func(b byte) (uint64, bool) {
			if b >= 32 && b <= 126 {
				return uint64(b), true
			}
			return 0, false
		},
	},
	"ascii7": {
		width: 7, pad: 0, nul: true,
		dec: func(c uint64) (byte, bool) {
			if c == 0 || (c >= 32 && c <= 126) {
				return byte(c), true
			}
			return 0, false
		},
		enc: func(b byte) (uint64, bool) {
			if b >= 32 && b <= 126 {
				return uint64(b), true
			}
			return 0, false
		},
	},
}

// encChar is the code of one character of text in the set. With
// nulOrdinary NUL is an ordinary character of a set that has it (0.22
// rulings 6, 20 and 21: a terminator other than 0).
func (set *charSet) encChar(b byte, nulOrdinary bool) (uint64, bool) {
	if b == 0 && nulOrdinary && set.nul {
		return 0, true
	}
	return set.enc(b)
}

// decodeChars reads n characters of the set at bit at, each as `uint` reads
// a field of the set's width there (0.22 ruling 3).
func (set *charSet) decodeChars(data []byte, at, n int, o bitOrder) ([]byte, error) {
	buf := make([]byte, n)
	for i := 0; i < n; i++ {
		c := getBits(data, at+i*set.width, set.width, o)
		b, ok := set.dec(c)
		if !ok {
			return nil, fmt.Errorf("character %d has code %d, which the set does not hold", i, c)
		}
		buf[i] = b
	}
	return buf, nil
}

// encodeChars returns the codes of text in the set, refusing a character
// whose code is the terminator term (when term is not nil).
func (set *charSet) encodeChars(s string, term *uint64) ([]uint64, error) {
	codes := make([]uint64, len(s))
	for i := 0; i < len(s); i++ {
		c, ok := set.encChar(s[i], term != nil && *term != 0)
		if !ok {
			return nil, fmt.Errorf("byte 0x%02x is not a character of the set", s[i])
		}
		if term != nil && c == *term {
			return nil, fmt.Errorf("character %d has the terminator's code %d", i, c)
		}
		codes[i] = c
	}
	return codes, nil
}

// newChars builds `chars:<set>`; with stop, the field option `stop <code>`
// (0.22): the text ends at the first character with that code.
func newChars(set *charSet, stop *uint64) *bitsTransform {
	w := set.width
	padChar, _ := set.dec(uint64(set.pad))
	return &bitsTransform{
		name:    "chars",
		noSwap:  true,
		charSet: set,
		decodeAt: func(data []byte, at, length int, o bitOrder) (Value, error) {
			n := length / w
			if stop != nil {
				// The text is exactly the characters before the first
				// terminator (rulings 18 and 21); with none the field
				// decodes as without `stop` (ruling 19).
				for i := 0; i < n; i++ {
					if getBits(data, at+i*w, w, o) == *stop {
						buf, err := set.decodeChars(data, at, i, o)
						if err != nil {
							return Value{}, err
						}
						return Value{Kind: KindString, S: string(buf)}, nil
					}
				}
			}
			buf, err := set.decodeChars(data, at, n, o)
			if err != nil {
				return Value{}, err
			}
			if set.nul {
				for i := 1; i < n; i++ {
					if buf[i-1] == 0 && buf[i] != 0 {
						return Value{}, fmt.Errorf("a NUL at character %d is followed by a character", i-1)
					}
				}
			}
			for n > 0 && (buf[n-1] == padChar || (set.space && buf[n-1] == ' ')) {
				n--
			}
			return Value{Kind: KindString, S: string(buf[:n])}, nil
		},
		encodeAt: func(v Value, data []byte, at, length int, o bitOrder) error {
			s, err := encString(v)
			if err != nil {
				return err
			}
			n := length / w
			text, err := set.encodeChars(s, stop)
			if err != nil {
				return err
			}
			if stop != nil {
				// The text, the terminator, then padding (0.22).
				if len(text)+1 > n {
					return fmt.Errorf("text is %d character(s), and the field holds %d with its terminator", len(text), n)
				}
				text = append(text, *stop)
			} else if len(text) > n {
				return fmt.Errorf("text is %d character(s), the field holds %d", len(s), n)
			}
			for i := 0; i < n; i++ {
				c := uint64(set.pad)
				if i < len(text) {
					c = text[i]
				}
				putBits(data, at+i*w, w, c, o)
			}
			return nil
		},
	}
}

var bitsOctal = &bitsTransform{
	name:   "octal",
	noSwap: true,
	decode: func(raw uint64, length int) (Value, error) {
		return Value{Kind: KindString, S: fmt.Sprintf("%0*o", length/3, maskBits(raw, length))}, nil
	},
	encode: func(v Value, length int) (uint64, error) {
		s, err := encString(v)
		if err != nil {
			return 0, err
		}
		if len(s) != length/3 {
			return 0, fmt.Errorf("octal text %q must be exactly %d digits", s, length/3)
		}
		var u uint64
		for i := 0; i < len(s); i++ {
			if s[i] < '0' || s[i] > '7' {
				return 0, fmt.Errorf("octal text %q holds a character that is not 0-7", s)
			}
			u = u<<3 | uint64(s[i]-'0')
		}
		return u, nil
	},
}

// --- text wire transforms ---

func newTextScale(spec string) (*transform, error) {
	sc, err := parseFloatScale(spec)
	if err != nil {
		return nil, err
	}
	return &transform{
		name: spec, number: true, numOnly: true,
		decode: func(s string) (Value, error) {
			v, err := parseFloat(s)
			if err != nil {
				return Value{}, err
			}
			r := sc.fup(v)
			if !finite(r) {
				return Value{}, fmt.Errorf("%s scales to %v, which is not finite", s, r)
			}
			return Value{Kind: KindFloat, F: r}, nil
		},
		encode: func(v Value) (string, error) {
			x, err := valueToFloat(v)
			if err != nil {
				return "", err
			}
			return formatFloat(sc.fdown(x))
		},
	}, nil
}

func newTextIScale(spec string) (*transform, error) {
	sc, err := parseExactScale(spec)
	if err != nil {
		return nil, err
	}
	return &transform{
		name: spec, number: true, numOnly: true,
		decode: func(s string) (Value, error) {
			r, err := parseExactNumberText(s)
			if err != nil {
				return Value{}, err
			}
			i, err := sc.up(r)
			if err != nil {
				return Value{}, err
			}
			return Value{Kind: KindInt, I: i}, nil
		},
		encode: func(v Value) (string, error) {
			x, err := valueToRat(v)
			if err != nil {
				return "", err
			}
			return formatExactDecimal(sc.quotient(x))
		},
	}, nil
}

// resolveV015 binds a transform of this version to f, checking the wire it
// is on and the field's length. Every refusal is bad-directive.
func resolveV015(wire, base string, f *Field) error {
	name := f.Transform
	if wire != WireBits && v015Bits[base] {
		return fmt.Errorf("transform %q is valid only on a bits wire", name)
	}
	if v015Text[base] && wire != WireXML && wire != WireJSON && wire != WireGeoJSON {
		return fmt.Errorf("transform %q is valid only on the xml, json and geojson wires", name)
	}
	var err error
	switch base {
	case "scale":
		f.tf, err = newTextScale(name)
		return err
	case "iscale":
		f.tf, err = newTextIScale(name)
		return err
	}
	n := f.loc.blen
	lenRange := func(lo, hi int) error {
		if n < lo || n > hi {
			return fmt.Errorf("%s needs a length from %d to %d bits, got %d", base, lo, hi, n)
		}
		return nil
	}
	switch base {
	case "uiscale", "siscale":
		if f.btf, err = newIntScale(name, base == "siscale"); err != nil {
			return err
		}
		return lenRange(1, 64)
	case "smag":
		if name != "smag" {
			return fmt.Errorf("smag takes no parameter, got %q", name)
		}
		f.btf = bitsSmag
		return lenRange(2, 64)
	case "smscale":
		if f.btf, err = newSmscale(name); err != nil {
			return err
		}
		return lenRange(2, 64)
	case "f32scale", "f64scale":
		if f.btf, err = newFloatBitsScale(name, base == "f32scale"); err != nil {
			return err
		}
		want := 64
		if base == "f32scale" {
			want = 32
		}
		if n != want {
			return fmt.Errorf("%s needs a %d-bit field, got %d", base, want, n)
		}
		return nil
	case "chars":
		set := charSets[strings.TrimPrefix(name, "chars:")]
		if !strings.HasPrefix(name, "chars:") || set == nil {
			return fmt.Errorf("chars needs a character set icao6, ais6, ascii7 or ascii8, got %q", name)
		}
		var stop *uint64
		if f.StopLine {
			c, err := strconv.ParseUint(f.Stop, 10, 64)
			if !isDigits(f.Stop) || err != nil || (set.width < 64 && c>>uint(set.width) != 0) {
				return fmt.Errorf("stop %s: the code must be below 2^%d", f.Stop, set.width)
			}
			stop = &c
		}
		f.btf = newChars(set, stop)
		if f.until {
			// until:<code> (0.22): the code fits the set's width; the field
			// has no fixed length.
			if set.width < 64 && f.untilC>>uint(set.width) != 0 {
				return fmt.Errorf("until:%d: the code must be below 2^%d", f.untilC, set.width)
			}
			return nil
		}
		if n%set.width != 0 || n < set.width || n > maxBitsLen {
			return fmt.Errorf("%s needs a multiple of %d bits from %d to %d, got %d", name, set.width, set.width, maxBitsLen, n)
		}
		return nil
	case "octal":
		if name != "octal" {
			return fmt.Errorf("octal takes no parameter, got %q", name)
		}
		f.btf = bitsOctal
		if n%3 != 0 || n < 3 || n > 63 {
			return fmt.Errorf("octal needs a multiple of 3 bits from 3 to 63, got %d", n)
		}
		return nil
	}
	return fmt.Errorf("unknown transform %q", name)
}

// checkV015Params checks the parameters of a transform of this version
// without its wire or length, which are checked after the file (step 7 of
// ruling 5b of 0.11).
func checkV015Params(base, name string) error {
	var err error
	switch base {
	case "uiscale", "siscale":
		_, err = newIntScale(name, base == "siscale")
	case "smscale":
		_, err = newSmscale(name)
	case "f32scale", "f64scale":
		_, err = newFloatBitsScale(name, base == "f32scale")
	case "scale":
		_, err = newTextScale(name)
	case "iscale":
		_, err = newTextIScale(name)
	case "smag", "octal":
		if name != base {
			err = fmt.Errorf("%s takes no parameter, got %q", base, name)
		}
	case "chars":
		if !strings.HasPrefix(name, "chars:") || charSets[name[len("chars:"):]] == nil {
			err = fmt.Errorf("chars needs a character set icao6, ais6, ascii7 or ascii8, got %q", name)
		}
	}
	return err
}

// bitsHex is `hex` on the bits wire (0.22): len / 4 lowercase hex digits,
// digit k the 4-bit field at bit 4k of the field read as `uint` reads it.
var bitsHex = &bitsTransform{
	name:   "hex",
	noSwap: true,
	decodeAt: func(data []byte, at, length int, o bitOrder) (Value, error) {
		const digits = "0123456789abcdef"
		buf := make([]byte, length/4)
		for k := range buf {
			buf[k] = digits[getBits(data, at+4*k, 4, o)]
		}
		return Value{Kind: KindString, S: string(buf)}, nil
	},
	encodeAt: func(v Value, data []byte, at, length int, o bitOrder) error {
		s, err := encString(v)
		if err != nil {
			return err
		}
		if len(s) != length/4 {
			return fmt.Errorf("hex text %q must be exactly %d digits", s, length/4)
		}
		for k := 0; k < len(s); k++ {
			var d uint64
			switch c := s[k]; {
			case c >= '0' && c <= '9':
				d = uint64(c - '0')
			case c >= 'a' && c <= 'f':
				d = uint64(c-'a') + 10
			case c >= 'A' && c <= 'F':
				d = uint64(c-'A') + 10
			default:
				return fmt.Errorf("hex text %q holds a character that is not a hex digit", s)
			}
			putBits(data, at+4*k, 4, d, o)
		}
		return nil
	},
}
