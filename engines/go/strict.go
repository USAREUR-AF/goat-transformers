package goatxf

import (
	"fmt"
	"math"
	"strconv"
)

// The number grammars of Version 0.11 (ruling 2 of spec/engine-spec.md,
// "Version 0.11: strict rulings").

// parseUintText reads an unsigned decimal integer (ruling 2c): one or more
// ASCII digits and nothing else, leading zeros allowed. Its value must not
// exceed max.
func parseUintText(s string, max uint64) (uint64, error) {
	if !isDigits(s) {
		return 0, fmt.Errorf("%q is not an unsigned decimal integer", s)
	}
	var v uint64
	for i := 0; i < len(s); i++ {
		d := uint64(s[i] - '0')
		if v > (math.MaxUint64-d)/10 {
			return 0, fmt.Errorf("%q is out of range", s)
		}
		v = v*10 + d
	}
	if v > max {
		return 0, fmt.Errorf("%q is out of range (at most %d)", s, max)
	}
	return v, nil
}

// parseUintBits reads an unsigned decimal integer whose value must lie below
// 2^bits (bits from 1 to 64).
func parseUintBits(s string, bits int) (uint64, error) {
	max := uint64(math.MaxUint64)
	if bits < 64 {
		max = uint64(1)<<uint(bits) - 1
	}
	v, err := parseUintText(s, max)
	if err != nil {
		return 0, fmt.Errorf("%v: an unsigned decimal integer that fits %d bit(s)", err, bits)
	}
	return v, nil
}

// parseSmallUint reads an unsigned decimal integer that fits an int.
func parseSmallUint(s string) (int, error) {
	v, err := parseUintText(s, math.MaxInt32)
	return int(v), err
}

// parseIntText reads integer text (ruling 2a): an optional `-`, then one or
// more ASCII digits, and nothing else; leading zeros allowed, `-0` is 0. The
// value lies within a signed 64-bit integer.
func parseIntText(s string) (int64, error) {
	neg := len(s) > 0 && s[0] == '-'
	digits := s
	if neg {
		digits = s[1:]
	}
	if !isDigits(digits) {
		return 0, fmt.Errorf("%q is not integer text", s)
	}
	limit := uint64(math.MaxInt64)
	if neg {
		limit++
	}
	u, err := parseUintText(digits, limit)
	if err != nil {
		return 0, fmt.Errorf("%q is outside a signed 64-bit integer", s)
	}
	if neg {
		return int64(-u), nil // -2^63 wraps to itself
	}
	return int64(u), nil
}

// isNumberText reports whether s has the form of number text (ruling 2b): an
// optional `-`, one or more digits, optionally `.` and one or more digits,
// optionally `e` or `E`, an optional sign and one or more digits.
func isNumberText(s string) bool {
	i := 0
	if i < len(s) && s[i] == '-' {
		i++
	}
	digits := func() bool {
		j := i
		for i < len(s) && s[i] >= '0' && s[i] <= '9' {
			i++
		}
		return i > j
	}
	if !digits() {
		return false
	}
	if i < len(s) && s[i] == '.' {
		i++
		if !digits() {
			return false
		}
	}
	if i < len(s) && (s[i] == 'e' || s[i] == 'E') {
		i++
		if i < len(s) && (s[i] == '+' || s[i] == '-') {
			i++
		}
		if !digits() {
			return false
		}
	}
	return i == len(s)
}

// parseNumberText reads number text (ruling 2b) to the nearest double, a tie
// to the double whose last bit is 0. A text whose nearest double is infinite
// is refused; a text nearer to zero than to the smallest subnormal reads as
// zero, negative zero when it begins with `-`.
func parseNumberText(s string) (float64, error) {
	if !isNumberText(s) {
		return 0, fmt.Errorf("%q is not number text", s)
	}
	f, err := strconv.ParseFloat(s, 64)
	if math.IsInf(f, 0) {
		return 0, fmt.Errorf("%q is out of range for a double", s)
	}
	if err != nil && f != 0 {
		return 0, fmt.Errorf("%q is not number text", s)
	}
	if f == 0 && s[0] == '-' {
		f = math.Copysign(0, -1)
	}
	return f, nil
}

// exactInt reads the exact value of JSON number text (ruling 2d): it must be
// an integer within a signed 64-bit integer, whatever its fraction of zero
// or its exponent. It works on the digits, so no exponent makes it slow.
func exactInt(lit string) (int64, error) {
	if i, err := parseIntText(lit); err == nil {
		return i, nil
	}
	if !isNumberText(lit) {
		return 0, fmt.Errorf("%q is not a number", lit)
	}
	s := lit
	neg := s[0] == '-'
	if neg {
		s = s[1:]
	}
	mant, exp := s, ""
	for i := 0; i < len(s); i++ {
		if s[i] == 'e' || s[i] == 'E' {
			mant, exp = s[:i], s[i+1:]
			break
		}
	}
	intPart, frac := mant, ""
	for i := 0; i < len(mant); i++ {
		if mant[i] == '.' {
			intPart, frac = mant[:i], mant[i+1:]
			break
		}
	}
	digits := intPart + frac
	// The exponent, held within a bound far beyond any digit count that
	// can matter.
	e := 0
	if exp != "" {
		eneg := exp[0] == '-'
		if exp[0] == '+' || exp[0] == '-' {
			exp = exp[1:]
		}
		for i := 0; i < len(exp); i++ {
			if e < 1<<40 {
				e = e*10 + int(exp[i]-'0')
			}
		}
		if eneg {
			e = -e
		}
	}
	e -= len(frac)
	// Strip leading zeros; then trailing zeros, which raise the exponent.
	k := 0
	for k < len(digits) && digits[k] == '0' {
		k++
	}
	digits = digits[k:]
	if digits == "" {
		return 0, nil
	}
	for len(digits) > 0 && digits[len(digits)-1] == '0' {
		digits = digits[:len(digits)-1]
		e++
	}
	if e < 0 {
		return 0, fmt.Errorf("%s is not an integer", lit)
	}
	if len(digits)+e > 19 {
		return 0, fmt.Errorf("%s is outside a signed 64-bit integer", lit)
	}
	text := digits
	for ; e > 0; e-- {
		text += "0"
	}
	if neg {
		text = "-" + text
	}
	v, err := parseIntText(text)
	if err != nil {
		return 0, fmt.Errorf("%s is outside a signed 64-bit integer", lit)
	}
	return v, nil
}
