package goatxf

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
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

func parseFloat(s string) (float64, error) {
	t := strings.TrimSpace(s)
	if t == "" {
		return 0, fmt.Errorf("empty number")
	}
	for _, c := range t {
		if !(c >= '0' && c <= '9') && c != '+' && c != '-' && c != '.' && c != 'e' && c != 'E' {
			return 0, fmt.Errorf("not a decimal number: %q", s)
		}
	}
	f, err := strconv.ParseFloat(t, 64)
	if err != nil {
		return 0, fmt.Errorf("not a decimal number: %q", s)
	}
	if math.IsInf(f, 0) || math.IsNaN(f) {
		return 0, fmt.Errorf("number out of range: %q", s)
	}
	return f, nil
}

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

func parseInt(s string) (int64, error) {
	t := strings.TrimSpace(s)
	if i, err := strconv.ParseInt(t, 10, 64); err == nil {
		return i, nil
	}
	f, err := parseFloat(t)
	if err != nil {
		return 0, fmt.Errorf("not a decimal integer: %q", s)
	}
	return floatToInt(f)
}

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

const isoOut = "2006-01-02T15:04:05.000Z"

// parseISO reads an ISO 8601 instant to epoch milliseconds. The designator
// is `Z`, `z` or an offset `+hh:mm` / `-hh:mm`, and the `T` may be lowercase
// (spec 0.6, replacing 0.1.1 ruling 8); the instant is converted to UTC.
// Fraction digits beyond milliseconds are truncated.
func parseISO(s string) (int64, error) {
	t := strings.TrimSpace(s)
	bad := func() (int64, error) {
		return 0, fmt.Errorf("not ISO 8601 (YYYY-MM-DDTHH:MM:SS[.fff] then Z or +hh:mm / -hh:mm): %q", s)
	}
	// YYYY-MM-DDTHH:MM:SS is 19 bytes; the designator follows the fraction.
	if len(t) < 20 || (t[10] != 'T' && t[10] != 't') {
		return bad()
	}
	b := []byte(t)
	b[10] = 'T'
	if b[len(b)-1] == 'z' {
		b[len(b)-1] = 'Z'
	}
	// The layout accepts exactly Z or a signed hh:mm offset.
	tm, err := time.Parse("2006-01-02T15:04:05.999999999Z07:00", string(b))
	if err != nil {
		return bad()
	}
	return tm.UnixMilli(), nil
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
		if i, err := strconv.ParseInt(strings.TrimSpace(v.S), 10, 64); err == nil {
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
	return time.UnixMilli(ms).UTC().Format(isoOut), nil
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
		return maskBits(uint64(i), length), nil
	},
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
		return maskBits(uint64(i), length), nil
	},
}

// newLinscale builds a linscale:<maxpos>:<range> transform: decode is the signed
// value v then v/maxpos*range (float); encode is round(x/range*maxpos).
func newLinscale(spec string) (*bitsTransform, error) {
	rest := strings.TrimPrefix(spec, "linscale:")
	parts := strings.Split(rest, ":")
	if len(parts) != 2 {
		return nil, fmt.Errorf("linscale needs <maxpos>:<range>, got %q", spec)
	}
	maxpos, err := strconv.ParseInt(parts[0], 10, 64)
	if err != nil || maxpos <= 0 {
		return nil, fmt.Errorf("linscale maxpos must be a positive integer, got %q", parts[0])
	}
	rng, err := parseFloat(parts[1])
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
			n := int64(math.Round(x / rng * float64(maxpos)))
			return maskBits(uint64(n), length), nil
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
	if i := strings.IndexByte(parts[1], '/'); i >= 0 {
		num, e1 := strconv.ParseInt(parts[1][:i], 10, 64)
		den, e2 := strconv.ParseInt(parts[1][i+1:], 10, 64)
		if e1 != nil || e2 != nil || num == 0 || den == 0 {
			return nil, fmt.Errorf("%s fraction must be <num>/<den> of two non-zero decimal integers, got %q", parts[0], parts[1])
		}
		sc.frac, sc.num, sc.den = true, float64(num), float64(den)
	} else {
		f, err := parseFloat(parts[1])
		if err != nil || f == 0 {
			return nil, fmt.Errorf("%s factor must be a non-zero decimal number, got %q", parts[0], parts[1])
		}
		sc.factor = f
	}
	if len(parts) == 3 {
		o, err := parseFloat(parts[2])
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

// down is the encode direction: (x - offset) / factor (or * den / num),
// rounded half away from zero.
func (sc *scale) down(x float64) float64 {
	if sc.frac {
		return math.Round((x - sc.offset) * sc.den / sc.num)
	}
	return math.Round((x - sc.offset) / sc.factor)
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
			r := sc.down(x)
			if math.IsNaN(r) || math.IsInf(r, 0) {
				return 0, fmt.Errorf("value %v does not scale to a number", x)
			}
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
			return maskBits(uint64(r), length), nil
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
			return ErrUnknownTransform, fmt.Errorf("transform %q is valid only on a text wire, not bits", name)
		case isPBTransformName(name):
			return ErrUnknownTransform, fmt.Errorf("transform %q is valid only on a protobuf wire, not bits", name)
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
			return ErrUnknownTransform, fmt.Errorf("transform %q is not a protobuf transform (protobuf: %s)", name, strings.Join(ProtoTransformNames(), ", "))
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
			return ErrUnknownTransform, fmt.Errorf("transform %q is valid only on a json wire", name)
		}
		if isBitsTransformName(name) {
			return ErrUnknownTransform, fmt.Errorf("transform %q is valid only on a bits wire", name)
		}
		if isPBTransformName(name) {
			return ErrUnknownTransform, fmt.Errorf("transform %q is valid only on a protobuf wire", name)
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
