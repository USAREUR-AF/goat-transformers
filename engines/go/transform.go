package goatxf

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"
)

// transform is a reversible pair between a wire string and a model value.
// number is true when the geojson wire writes the encoded text as a JSON
// number rather than a JSON string.
type transform struct {
	name   string
	number bool
	decode func(string) (Value, error)
	encode func(Value) (string, error)
}

var transforms = map[string]*transform{
	"string":     {name: "string", decode: decString, encode: encString},
	"float":      {name: "float", number: true, decode: decFloat, encode: encFloat},
	"int":        {name: "int", number: true, decode: decInt, encode: encInt},
	"iso8601_ms": {name: "iso8601_ms", decode: decISO, encode: encISO},
}

// TransformNames lists the transforms this engine implements.
func TransformNames() []string {
	return []string{"float", "int", "iso8601_ms", "string"}
}

func decString(s string) (Value, error) { return Value{Kind: KindString, S: s}, nil }

func encString(v Value) (string, error) {
	switch v.Kind {
	case KindString:
		return v.S, nil
	case KindInt:
		return strconv.FormatInt(v.I, 10), nil
	case KindFloat:
		return formatFloat(v.F)
	}
	return "", fmt.Errorf("no value")
}

// parseFloat reads number text by ruling 2b of 0.11: nothing is trimmed.
func parseFloat(s string) (float64, error) { return parseNumberText(s) }

// formatFloat writes the shortest decimal that round-trips, with no exponent;
// an integer-valued float has no decimal point (30.0 -> "30").
func formatFloat(f float64) (string, error) {
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return "", fmt.Errorf("non-finite float %v", f)
	}
	if f == 0 {
		return "0", nil
	}
	return strconv.FormatFloat(f, 'f', -1, 64), nil
}

func decFloat(s string) (Value, error) {
	f, err := parseFloat(s)
	if err != nil {
		return Value{}, err
	}
	return Value{Kind: KindFloat, F: f}, nil
}

func encFloat(v Value) (string, error) {
	switch v.Kind {
	case KindFloat:
		return formatFloat(v.F)
	case KindInt:
		return formatFloat(float64(v.I))
	case KindString:
		f, err := parseFloat(v.S)
		if err != nil {
			return "", err
		}
		return formatFloat(f)
	}
	return "", fmt.Errorf("no value")
}

// parseInt reads integer text by ruling 2a of 0.11: nothing is trimmed, and
// a fraction or an exponent is refused.
func parseInt(s string) (int64, error) { return parseIntText(s) }

func floatToInt(f float64) (int64, error) {
	if f != math.Trunc(f) || f < -9.223372036854775e18 || f > 9.223372036854775e18 {
		return 0, fmt.Errorf("not an integer: %v", f)
	}
	return int64(f), nil
}

func decInt(s string) (Value, error) {
	i, err := parseInt(s)
	if err != nil {
		return Value{}, err
	}
	return Value{Kind: KindInt, I: i}, nil
}

func encInt(v Value) (string, error) {
	switch v.Kind {
	case KindInt:
		return strconv.FormatInt(v.I, 10), nil
	case KindFloat:
		i, err := floatToInt(v.F)
		if err != nil {
			return "", err
		}
		return strconv.FormatInt(i, 10), nil
	case KindString:
		i, err := parseInt(v.S)
		if err != nil {
			return "", err
		}
		return strconv.FormatInt(i, 10), nil
	}
	return "", fmt.Errorf("no value")
}

// minISOms and maxISOms are the instants 0001-01-01T00:00:00.000Z and
// 9999-12-31T23:59:59.999Z (ruling 3 of 0.11).
const (
	minISOms = -62135596800000
	maxISOms = 253402300799999
)

// daysFromCivil is the number of days from 1970-01-01 to a date of the
// proleptic Gregorian calendar.
func daysFromCivil(y, m, d int64) int64 {
	if m <= 2 {
		y--
	}
	era := y / 400
	if y < 0 && y%400 != 0 {
		era--
	}
	yoe := y - era*400
	mp := (m + 9) % 12
	doy := (153*mp+2)/5 + d - 1
	doe := yoe*365 + yoe/4 - yoe/100 + doy
	return era*146097 + doe - 719468
}

// civilFromDays is the inverse of daysFromCivil.
func civilFromDays(z int64) (y, m, d int64) {
	z += 719468
	era := z / 146097
	if z < 0 && z%146097 != 0 {
		era--
	}
	doe := z - era*146097
	yoe := (doe - doe/1460 + doe/36524 - doe/146096) / 365
	y = yoe + era*400
	doy := doe - (365*yoe + yoe/4 - yoe/100)
	mp := (5*doy + 2) / 153
	d = doy - (153*mp+2)/5 + 1
	m = mp + 3
	if m > 12 {
		m -= 12
	}
	if m <= 2 {
		y++
	}
	return y, m, d
}

// parseISO reads an instant by the grammar of ruling 3 of 0.11:
// YYYY-MM-DD, `T` or `t`, hh:mm:ss, optionally `.` and one or more digits,
// then `Z`, `z` or `+hh:mm` / `-hh:mm`; every field of exactly its digits,
// nothing before or after. The first three fraction digits are the
// milliseconds; the others are dropped.
func parseISO(s string) (int64, error) {
	bad := func(why string) (int64, error) {
		return 0, fmt.Errorf("not an instant YYYY-MM-DDThh:mm:ss[.f…] then Z or +hh:mm / -hh:mm (%s): %q", why, s)
	}
	num := func(at, n int) (int64, bool) {
		if at+n > len(s) {
			return 0, false
		}
		var v int64
		for i := at; i < at+n; i++ {
			c := s[i]
			if c < '0' || c > '9' {
				return 0, false
			}
			v = v*10 + int64(c-'0')
		}
		return v, true
	}
	lit := func(at int, cs ...byte) bool {
		if at >= len(s) {
			return false
		}
		for _, c := range cs {
			if s[at] == c {
				return true
			}
		}
		return false
	}
	y, ok1 := num(0, 4)
	mo, ok2 := num(5, 2)
	d, ok3 := num(8, 2)
	h, ok4 := num(11, 2)
	mi, ok5 := num(14, 2)
	sec, ok6 := num(17, 2)
	if !ok1 || !ok2 || !ok3 || !ok4 || !ok5 || !ok6 || !lit(4, '-') || !lit(7, '-') || !lit(10, 'T', 't') || !lit(13, ':') || !lit(16, ':') {
		return bad("form")
	}
	i := 19
	var ms int64
	if lit(i, '.') {
		i++
		j := i
		for i < len(s) && s[i] >= '0' && s[i] <= '9' {
			i++
		}
		if i == j {
			return bad("a `.` with no digit")
		}
		frac := s[j:i] + "00"
		ms = int64(frac[0]-'0')*100 + int64(frac[1]-'0')*10 + int64(frac[2]-'0')
	}
	var off int64
	switch {
	case i == len(s)-1 && (s[i] == 'Z' || s[i] == 'z'):
	case i == len(s)-6 && (s[i] == '+' || s[i] == '-'):
		oh, ok1 := num(i+1, 2)
		om, ok2 := num(i+4, 2)
		if !ok1 || !ok2 || !lit(i+3, ':') || oh > 23 || om > 59 {
			return bad("offset")
		}
		off = oh*60 + om
		if s[i] == '-' {
			off = -off
		}
	default:
		return bad("designator")
	}
	if y < 1 || mo < 1 || mo > 12 || d < 1 || d > int64(daysIn(int(y), int(mo))) || h > 23 || mi > 59 || sec > 59 {
		return bad("range")
	}
	v := (daysFromCivil(y, mo, d)*86400+h*3600+mi*60+sec-off*60)*1000 + ms
	if v < minISOms || v > maxISOms {
		return bad("the instant lies outside years 0001 to 9999")
	}
	return v, nil
}

// formatISO writes YYYY-MM-DDTHH:MM:SS.fffZ (ruling 3f of 0.11).
func formatISO(ms int64) (string, error) {
	if ms < minISOms || ms > maxISOms {
		return "", fmt.Errorf("%d ms lies outside years 0001 to 9999", ms)
	}
	days := ms / 86400000
	rem := ms % 86400000
	if rem < 0 {
		rem += 86400000
		days--
	}
	y, m, d := civilFromDays(days)
	return fmt.Sprintf("%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", y, m, d, rem/3600000, rem/60000%60, rem/1000%60, rem%1000), nil
}

func decISO(s string) (Value, error) {
	ms, err := parseISO(s)
	if err != nil {
		return Value{}, err
	}
	return Value{Kind: KindInt, I: ms}, nil
}

func encISO(v Value) (string, error) {
	var ms int64
	switch v.Kind {
	case KindInt:
		ms = v.I
	case KindFloat:
		i, err := floatToInt(v.F)
		if err != nil {
			return "", err
		}
		ms = i
	case KindString:
		if i, err := parseIntText(v.S); err == nil {
			ms = i
		} else {
			i, err := parseISO(v.S)
			if err != nil {
				return "", err
			}
			ms = i
		}
	default:
		return "", fmt.Errorf("no value")
	}
	return formatISO(ms)
}

// --- bits wire transforms (spec/engine-spec.md, "Version 0.2: the bits wire") ---

// bitsTransform is a reversible pair between an unsigned field of `length` bits
// and a model value: decode turns the raw bits into a value; encode returns the
// low `length` bits to write back. `ascii` is the one transform whose field
// may be longer than 64 bits; the bits wire reads and writes its bytes itself.
type bitsTransform struct {
	name   string
	ascii  bool
	decode func(raw uint64, length int) (Value, error)
	encode func(v Value, length int) (uint64, error)
}

func maskBits(v uint64, length int) uint64 {
	if length >= 64 {
		return v
	}
	return v & ((uint64(1) << uint(length)) - 1)
}

// signExtend reads the low `length` bits of raw as a two's-complement signed
// integer.
func signExtend(raw uint64, length int) int64 {
	raw = maskBits(raw, length)
	if length < 64 && raw&(uint64(1)<<uint(length-1)) != 0 {
		raw |= ^((uint64(1) << uint(length)) - 1)
	}
	return int64(raw)
}

func valueToInt(v Value) (int64, error) {
	switch v.Kind {
	case KindInt:
		return v.I, nil
	case KindFloat:
		return floatToInt(v.F)
	case KindString:
		return parseInt(v.S)
	}
	return 0, fmt.Errorf("no value")
}

func valueToFloat(v Value) (float64, error) {
	switch v.Kind {
	case KindFloat:
		return v.F, nil
	case KindInt:
		return float64(v.I), nil
	case KindString:
		return parseFloat(v.S)
	}
	return 0, fmt.Errorf("no value")
}

var bitsUint = &bitsTransform{
	name: "uint",
	decode: func(raw uint64, length int) (Value, error) {
		return Value{Kind: KindInt, I: int64(maskBits(raw, length))}, nil
	},
	encode: func(v Value, length int) (uint64, error) {
		i, err := valueToInt(v)
		if err != nil {
			return 0, err
		}
		// Below 64 bits the value must lie from 0 to 2^len - 1; at 64 every
		// model integer is written as its two's-complement pattern (ruling
		// 4b of 0.11).
		if length < 64 && (i < 0 || uint64(i)>>uint(length) != 0) {
			return 0, fmt.Errorf("value %d does not fit an unsigned %d-bit field", i, length)
		}
		return maskBits(uint64(i), length), nil
	},
}

// fitsSigned reports whether i lies from -2^(len-1) to 2^(len-1) - 1.
func fitsSigned(i int64, length int) bool {
	if length >= 64 {
		return true
	}
	half := int64(1) << uint(length-1)
	return i >= -half && i < half
}

var bitsTwos = &bitsTransform{
	name: "twos",
	decode: func(raw uint64, length int) (Value, error) {
		return Value{Kind: KindInt, I: signExtend(raw, length)}, nil
	},
	encode: func(v Value, length int) (uint64, error) {
		i, err := valueToInt(v)
		if err != nil {
			return 0, err
		}
		if !fitsSigned(i, length) {
			return 0, fmt.Errorf("value %d does not fit a signed %d-bit field", i, length)
		}
		return maskBits(uint64(i), length), nil
	},
}

// roundedFits checks a quotient q of a scaled transform against the range
// of its field (rulings 4a and 4b of 0.11): q must be finite; round(q), half
// away from zero and exact, must lie within the range, compared before it
// is narrowed. It returns the bits to write.
func roundedFits(x, q float64, length int, signed bool) (uint64, error) {
	if math.IsNaN(q) || math.IsInf(q, 0) {
		return 0, fmt.Errorf("value %v does not scale to a finite number", x)
	}
	r := math.Round(q)
	if signed {
		half := math.Ldexp(1, length-1)
		if r < -half || r >= half {
			return 0, fmt.Errorf("value %v scales to %v, outside a signed %d-bit field", x, r, length)
		}
		return maskBits(uint64(int64(r)), length), nil
	}
	if r < 0 || r >= math.Ldexp(1, length) {
		return 0, fmt.Errorf("value %v scales to %v, outside an unsigned %d-bit field", x, r, length)
	}
	return uint64(r), nil
}

// newLinscale builds a linscale:<maxpos>:<range> transform: decode is the signed
// value v then v/maxpos*range (float); encode is round(x/range*maxpos).
func newLinscale(spec string) (*bitsTransform, error) {
	rest := strings.TrimPrefix(spec, "linscale:")
	parts := strings.Split(rest, ":")
	if len(parts) != 2 {
		return nil, fmt.Errorf("linscale needs <maxpos>:<range>, got %q", spec)
	}
	// <maxpos> is an unsigned decimal integer of 1 or more; <range> is number
	// text that does not read as zero (ruling 4d of 0.11).
	maxpos, err := parseUintText(parts[0], math.MaxUint64)
	if err != nil || maxpos == 0 {
		return nil, fmt.Errorf("linscale maxpos must be an unsigned decimal integer of 1 or more, got %q", parts[0])
	}
	rng, err := parseNumberText(parts[1])
	if err != nil || rng == 0 {
		return nil, fmt.Errorf("linscale range must be a non-zero number, got %q", parts[1])
	}
	return &bitsTransform{
		name: spec,
		decode: func(raw uint64, length int) (Value, error) {
			v := signExtend(raw, length)
			return Value{Kind: KindFloat, F: float64(v) / float64(maxpos) * rng}, nil
		},
		encode: func(v Value, length int) (uint64, error) {
			x, err := valueToFloat(v)
			if err != nil {
				return 0, err
			}
			return roundedFits(x, x/rng*float64(maxpos), length, true)
		},
	}, nil
}

// parseScale reads the arguments of uscale / sscale: <factor>[:<offset>],
// where <factor> is a decimal number or a fraction <num>/<den> of two decimal
// integers (spec 0.5 ruling 1).
type scale struct {
	frac     bool
	factor   float64
	num, den float64
	offset   float64
}

func parseScale(spec string) (*scale, error) {
	parts := strings.Split(spec, ":")
	if len(parts) != 2 && len(parts) != 3 {
		return nil, fmt.Errorf("%s needs <factor>[:<offset>], got %q", parts[0], spec)
	}
	sc := &scale{}
	// The factor is number text that does not read as zero, or <num>/<den>
	// of two unsigned decimal integers, neither zero; the offset is number
	// text (ruling 4d of 0.11).
	if i := strings.IndexByte(parts[1], '/'); i >= 0 {
		num, e1 := parseUintText(parts[1][:i], math.MaxUint64)
		den, e2 := parseUintText(parts[1][i+1:], math.MaxUint64)
		if e1 != nil || e2 != nil || num == 0 || den == 0 {
			return nil, fmt.Errorf("%s fraction must be <num>/<den> of two non-zero decimal integers, got %q", parts[0], parts[1])
		}
		sc.frac, sc.num, sc.den = true, float64(num), float64(den)
	} else {
		f, err := parseNumberText(parts[1])
		if err != nil || f == 0 {
			return nil, fmt.Errorf("%s factor must be a non-zero decimal number, got %q", parts[0], parts[1])
		}
		sc.factor = f
	}
	if len(parts) == 3 {
		o, err := parseNumberText(parts[2])
		if err != nil {
			return nil, fmt.Errorf("%s offset must be a decimal number, got %q", parts[0], parts[2])
		}
		sc.offset = o
	}
	return sc, nil
}

// up is the decode direction: v * factor (or v * num / den), then + offset.
func (sc *scale) up(v float64) float64 {
	if sc.frac {
		return v*sc.num/sc.den + sc.offset
	}
	return v*sc.factor + sc.offset
}

// down is the encode direction, before rounding: (x - offset) / factor (or
// * den / num).
func (sc *scale) down(x float64) float64 {
	if sc.frac {
		return (x - sc.offset) * sc.den / sc.num
	}
	return (x - sc.offset) / sc.factor
}

// newScale builds uscale (signed=false) or sscale (signed=true).
func newScale(spec string, signed bool) (*bitsTransform, error) {
	sc, err := parseScale(spec)
	if err != nil {
		return nil, err
	}
	return &bitsTransform{
		name: spec,
		decode: func(raw uint64, length int) (Value, error) {
			if signed {
				return Value{Kind: KindFloat, F: sc.up(float64(signExtend(raw, length)))}, nil
			}
			return Value{Kind: KindFloat, F: sc.up(float64(maskBits(raw, length)))}, nil
		},
		encode: func(v Value, length int) (uint64, error) {
			x, err := valueToFloat(v)
			if err != nil {
				return 0, err
			}
			return roundedFits(x, sc.down(x), length, signed)
		},
	}, nil
}

var bitsF32 = &bitsTransform{
	name: "f32",
	decode: func(raw uint64, length int) (Value, error) {
		return finiteFloat(float64(math.Float32frombits(uint32(raw))))
	},
	encode: func(v Value, length int) (uint64, error) {
		x, err := valueToFloat(v)
		if err != nil {
			return 0, err
		}
		f, err := narrowToSingle(x)
		if err != nil {
			return 0, err
		}
		return uint64(math.Float32bits(f)), nil
	},
}

var bitsF64 = &bitsTransform{
	name: "f64",
	decode: func(raw uint64, length int) (Value, error) {
		return finiteFloat(math.Float64frombits(raw))
	},
	encode: func(v Value, length int) (uint64, error) {
		x, err := valueToFloat(v)
		if err != nil {
			return 0, err
		}
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return 0, fmt.Errorf("non-finite float %v", x)
		}
		return math.Float64bits(x), nil
	},
}

// finiteFloat refuses infinity and not-a-number read from a wire: a model
// float is always finite (0.5 ruling 23, extended to f64 and pdouble in 0.6).
func finiteFloat(f float64) (Value, error) {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return Value{}, fmt.Errorf("wire value %v is not a finite number", f)
	}
	return Value{Kind: KindFloat, F: f}, nil
}

// narrowToSingle narrows a double to an IEEE-754 single; a value outside
// single range is an error.
func narrowToSingle(x float64) (float32, error) {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return 0, fmt.Errorf("non-finite float %v", x)
	}
	f := float32(x)
	if math.IsInf(float64(f), 0) {
		return 0, fmt.Errorf("value %v is outside single range", x)
	}
	return f, nil
}

var bitsASCII = &bitsTransform{name: "ascii", ascii: true}

func isBitsTransformName(name string) bool {
	switch name {
	case "uint", "twos", "f32", "f64", "ascii":
		return true
	}
	return strings.HasPrefix(name, "linscale:") || strings.HasPrefix(name, "uscale:") || strings.HasPrefix(name, "sscale:")
}

// isTextTransformName reports a transform of the text wires; `bool` is one of
// them but valid only on the json wire.
func isTextTransformName(name string) bool { return transforms[name] != nil || name == "bool" }

// resolveFieldTransform binds f to the transform named on its field line and
// enforces that each transform appears only on its own kind of wire. A bit
// length the transform does not allow is bad-directive; anything else it
// refuses is unknown-transform.
func resolveFieldTransform(wire string, f *Field) (ErrorKind, error) {
	name := f.Transform
	// The transforms of the text wire are valid only on it (spec 0.10).
	if isTextOnlyTransform(name) {
		return ErrBadDirective, fmt.Errorf("transform %q is valid only on wire text", name)
	}
	// utf8 and hex are valid only on the tlv wire (spec 0.13).
	if isTLVOnlyTransform(name) {
		return ErrBadDirective, fmt.Errorf("transform %q is valid only on wire tlv", name)
	}
	switch wire {
	case WireBits:
		switch {
		case name == "uint":
			f.btf = bitsUint
		case name == "twos":
			f.btf = bitsTwos
		case name == "f32":
			f.btf = bitsF32
		case name == "f64":
			f.btf = bitsF64
		case name == "ascii":
			f.btf = bitsASCII
		case strings.HasPrefix(name, "linscale:"):
			bt, err := newLinscale(name)
			if err != nil {
				return ErrUnknownTransform, err
			}
			f.btf = bt
		case strings.HasPrefix(name, "uscale:"), strings.HasPrefix(name, "sscale:"):
			bt, err := newScale(name, name[0] == 's')
			if err != nil {
				return ErrUnknownTransform, err
			}
			f.btf = bt
		case isTextTransformName(name):
			return ErrBadDirective, fmt.Errorf("transform %q is valid only on a text wire, not bits", name)
		case isPBTransformName(name):
			return ErrBadDirective, fmt.Errorf("transform %q is valid only on a protobuf wire, not bits", name)
		default:
			return ErrUnknownTransform, fmt.Errorf("unknown transform %q (bits: uint, twos, linscale, uscale, sscale, f32, f64, ascii)", name)
		}
		n := f.loc.blen
		switch {
		case name == "f32" && n != 32:
			return ErrBadDirective, fmt.Errorf("f32 needs a 32-bit field, got %d", n)
		case name == "f64" && n != 64:
			return ErrBadDirective, fmt.Errorf("f64 needs a 64-bit field, got %d", n)
		case name == "ascii" && (n%8 != 0 || n < 8 || n > maxBitsLen):
			return ErrBadDirective, fmt.Errorf("ascii needs a multiple of 8 bits from 8 to %d, got %d", maxBitsLen, n)
		case name != "ascii" && n > 64:
			return ErrBadDirective, fmt.Errorf("%s covers at most 64 bits, got %d", name, n)
		}
		return "", nil
	case WireProtobuf:
		if pt, ok := pbTransforms[name]; ok {
			f.pbf = pt
			return "", nil
		}
		if isTextTransformName(name) || isBitsTransformName(name) {
			return ErrBadDirective, fmt.Errorf("transform %q is not a protobuf transform (protobuf: %s)", name, strings.Join(ProtoTransformNames(), ", "))
		}
		return ErrUnknownTransform, fmt.Errorf("unknown transform %q (protobuf: %s)", name, strings.Join(ProtoTransformNames(), ", "))
	default:
		if tf, ok := transforms[name]; ok {
			f.tf = tf
			return "", nil
		}
		if name == "bool" {
			if wire == WireJSON {
				f.jbool = true
				return "", nil
			}
			return ErrBadDirective, fmt.Errorf("transform %q is valid only on a json wire", name)
		}
		if isBitsTransformName(name) {
			return ErrBadDirective, fmt.Errorf("transform %q is valid only on a bits wire", name)
		}
		if isPBTransformName(name) {
			return ErrBadDirective, fmt.Errorf("transform %q is valid only on a protobuf wire", name)
		}
		return ErrUnknownTransform, fmt.Errorf("unknown transform %q (implemented: %s)", name, strings.Join(TransformNames(), ", "))
	}
}

// --- protobuf wire transforms (spec/engine-spec.md, "Version 0.3: the protobuf wire") ---

// The four protobuf wire types this engine reads.
const (
	pbVarint   = 0
	pbFixed64  = 1
	pbLenDelim = 2
	pbFixed32  = 5
)

// pbVal is one occurrence of a protobuf field on the wire: its wire type and
// either the scalar bits (varint / fixed) or the length-delimited bytes.
type pbVal struct {
	wire int
	u    uint64
	b    []byte

	parsed bool // b was read as a submessage; sub and subErr hold the result
	sub    map[int][]pbVal
	subErr error
}

// pbTransform is a reversible pair between a protobuf field occurrence and a
// model value. wire is the single wire type this transform reads and writes.
type pbTransform struct {
	name   string
	wire   int
	decode func(pv pbVal) (Value, error)
	encode func(v Value) (pbVal, error)
}

var pbTransforms = map[string]*pbTransform{
	"pstring": {name: "pstring", wire: pbLenDelim, decode: decPString, encode: encPString},
	"pvarint": {name: "pvarint", wire: pbVarint, decode: decPVarint, encode: encPVarint},
	"psint":   {name: "psint", wire: pbVarint, decode: decPSint, encode: encPSint},
	"pdouble": {name: "pdouble", wire: pbFixed64, decode: decPDouble, encode: encPDouble},
	"pfloat":  {name: "pfloat", wire: pbFixed32, decode: decPFloat, encode: encPFloat},
}

// ProtoTransformNames lists the protobuf transforms this engine implements.
func ProtoTransformNames() []string {
	return []string{"pdouble", "pfloat", "psint", "pstring", "pvarint"}
}

func isPBTransformName(name string) bool { _, ok := pbTransforms[name]; return ok }

func decPString(pv pbVal) (Value, error) {
	if !utf8.Valid(pv.b) {
		return Value{}, fmt.Errorf("length-delimited bytes are not valid UTF-8")
	}
	return Value{Kind: KindString, S: string(pv.b)}, nil
}

func encPString(v Value) (pbVal, error) {
	s, err := encString(v)
	if err != nil {
		return pbVal{}, err
	}
	return pbVal{wire: pbLenDelim, b: []byte(s)}, nil
}

func decPVarint(pv pbVal) (Value, error) {
	return Value{Kind: KindInt, I: int64(pv.u)}, nil
}

func encPVarint(v Value) (pbVal, error) {
	i, err := valueToInt(v)
	if err != nil {
		return pbVal{}, err
	}
	return pbVal{wire: pbVarint, u: uint64(i)}, nil
}

func decPSint(pv pbVal) (Value, error) {
	return Value{Kind: KindInt, I: int64(pv.u>>1) ^ -int64(pv.u&1)}, nil
}

func encPSint(v Value) (pbVal, error) {
	i, err := valueToInt(v)
	if err != nil {
		return pbVal{}, err
	}
	return pbVal{wire: pbVarint, u: uint64((i << 1) ^ (i >> 63))}, nil
}

func decPDouble(pv pbVal) (Value, error) {
	return finiteFloat(math.Float64frombits(pv.u))
}

func encPDouble(v Value) (pbVal, error) {
	fv, err := valueToFloat(v)
	if err != nil {
		return pbVal{}, err
	}
	if math.IsNaN(fv) || math.IsInf(fv, 0) {
		return pbVal{}, fmt.Errorf("non-finite float %v", fv)
	}
	return pbVal{wire: pbFixed64, u: math.Float64bits(fv)}, nil
}

func decPFloat(pv pbVal) (Value, error) {
	return finiteFloat(float64(math.Float32frombits(uint32(pv.u))))
}

func encPFloat(v Value) (pbVal, error) {
	fv, err := valueToFloat(v)
	if err != nil {
		return pbVal{}, err
	}
	f, err := narrowToSingle(fv)
	if err != nil {
		return pbVal{}, err
	}
	return pbVal{wire: pbFixed32, u: uint64(math.Float32bits(f))}, nil
}
