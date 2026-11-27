package goatxf

import (
	"fmt"
	"math"
	"math/big"
	"strings"
)

// Output conditions (spec/engine-spec.md, "Version 0.56: output
// conditions"): the field options `null`, `implicit` and `range <min> <max>
// [wrap]`. Range sentinels of `absent` are in sentinel.go.

// fieldRange is the `range` option of one field line.
type fieldRange struct {
	minT, maxT string // the arguments as written
	wrap       bool
	isInt      bool // the key is int: imin and imax hold the bounds
	imin, imax int64
	fmin, fmax float64
}

// resolve reads the bounds as the key's declared type, after the file: an
// int key takes integer text, a float key number text, and <min> must be
// less than <max> read as that type.
func (r *fieldRange) resolve(kind Kind) error {
	switch kind {
	case KindInt:
		lo, err1 := parseIntText(r.minT)
		hi, err2 := parseIntText(r.maxT)
		if err1 != nil || err2 != nil {
			return fmt.Errorf("`range %s %s` on an int key takes decimal integers", r.minT, r.maxT)
		}
		if lo >= hi {
			return fmt.Errorf("`range %s %s`: <min> is not less than <max>", r.minT, r.maxT)
		}
		r.isInt, r.imin, r.imax = true, lo, hi
	case KindFloat:
		lo, err1 := parseNumberText(r.minT)
		hi, err2 := parseNumberText(r.maxT)
		if err1 != nil || err2 != nil {
			return fmt.Errorf("`range %s %s` takes number text", r.minT, r.maxT)
		}
		if !(lo < hi) {
			return fmt.Errorf("`range %s %s`: <min> is not less than <max>", r.minT, r.maxT)
		}
		r.fmin, r.fmax = lo, hi
	default:
		return fmt.Errorf("`range` is valid only on a field whose key is int or float, not %s", kindName(kind))
	}
	return nil
}

// applyRange checks a model value against the field's `range`, before `via`
// and the transform: outside the interval it is refused, or with `wrap`
// brought into [min, max).
func (f *Field) applyRange(v Value) (Value, error) {
	r := f.Range
	if r == nil {
		return v, nil
	}
	if r.isInt {
		x, err := valueToInt(v)
		if err != nil {
			return v, err
		}
		if !r.wrap {
			if x < r.imin || x > r.imax {
				return v, fmt.Errorf("value %d is outside range [%d, %d]", x, r.imin, r.imax)
			}
			return v, nil
		}
		if x >= r.imin && x < r.imax {
			return v, nil
		}
		// x − (max − min) × floor((x − min) / (max − min)), exactly.
		bx, bmin := big.NewInt(x), big.NewInt(r.imin)
		width := new(big.Int).Sub(big.NewInt(r.imax), bmin)
		off := new(big.Int).Sub(bx, bmin)
		m := new(big.Int).Mod(off, width) // Euclidean: 0 <= m < width
		res := new(big.Int).Add(bmin, m)
		return Value{Kind: KindInt, I: res.Int64()}, nil
	}
	x, err := valueToFloat(v)
	if err != nil {
		return v, err
	}
	if math.IsNaN(x) {
		return v, fmt.Errorf("value is not a number")
	}
	if !r.wrap {
		if x < r.fmin || x > r.fmax {
			return v, fmt.Errorf("value %v is outside range [%s, %s]", x, r.minT, r.maxT)
		}
		return v, nil
	}
	if x >= r.fmin && x < r.fmax {
		return v, nil
	}
	if math.IsInf(x, 0) {
		return v, fmt.Errorf("value %v cannot be wrapped", x)
	}
	// Five operations, each rounded on its own (ruling 11): the explicit
	// conversions keep a product or difference from being fused.
	d := float64(r.fmax - r.fmin)
	off := float64(x - r.fmin)
	q := float64(off / d)
	fl := math.Floor(q)
	m := float64(d * fl)
	res := float64(x - m)
	for _, s := range []float64{d, off, q, m, res} {
		if math.IsNaN(s) || math.IsInf(s, 0) {
			return v, fmt.Errorf("value %v cannot be wrapped into range [%s, %s): a step is not finite", x, r.minT, r.maxT)
		}
	}
	if res == r.fmax {
		res = r.fmin // the same point of the circle
	}
	if res < r.fmin || res > r.fmax {
		return v, fmt.Errorf("value %v wraps to %v, outside range [%s, %s)", x, res, r.minT, r.maxT)
	}
	return Value{Kind: KindFloat, F: res}, nil
}

// isProto3Default reports whether a protobuf value equals the proto3 default
// of its wire type: 0, +0.0 (all bits zero), or the empty text.
func isProto3Default(pv pbVal) bool {
	if pv.wire == pbLenDelim {
		return len(pv.b) == 0
	}
	return pv.u == 0
}

// checkOutputOptions refuses `null` and `implicit` on a wire, a locator or a
// transform they do not apply to; checked after the file (0.56, Load errors).
func checkOutputOptions(wire string, f *Field) error {
	if f.Null {
		if wire != WireJSON && wire != WireGeoJSON {
			return fmt.Errorf("field option `null` is valid only on wire json and geojson")
		}
		if wire == WireGeoJSON && f.group == nil && (f.Locator == "geometry" || strings.HasPrefix(f.Locator, "geometry.")) {
			return fmt.Errorf("field option `null` is not valid on a geometry locator")
		}
	}
	if f.Implicit {
		if wire != WireProtobuf {
			return fmt.Errorf("field option `implicit` is valid only on wire protobuf")
		}
		switch f.Transform {
		case "pvarint", "psint", "pdouble", "pfloat", "pstring":
		default:
			return fmt.Errorf("field option `implicit` is not valid with the %s transform", f.Transform)
		}
		if f.group != nil && f.Locator == "." {
			return fmt.Errorf("field option `implicit` is not valid on a scalar item")
		}
	}
	return nil
}

// checkUnwrittenRange checks the value of each line against its `range`, for
// the lines whose value an encode does not write: every line whose key is
// held, or that a default fills, is checked (0.56 ruling 9); a line that
// `with` suppresses is not (ruling 6).
func checkUnwrittenRange(p *Pack, lay *layout, rec *Item, fields ...*Field) error {
	for _, f := range fields {
		if f.Range == nil || f.suppressed(rec) {
			continue
		}
		v, ok := rec.Fields[f.Key]
		if !ok {
			d := fieldDefault(lay, f)
			if d == nil {
				continue
			}
			v = d.val
		}
		if _, err := f.applyRange(v); err != nil {
			return encodeErr(p, f, err)
		}
	}
	return nil
}
