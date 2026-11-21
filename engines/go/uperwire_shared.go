package goatxf

// The declarations of uperwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"fmt"
	"strconv"
	"strings"
)

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
			isTLVOnlyTransform(name) || isCBOROnlyTransform(name) || isTextOnlyTransform(name) || v015Base(name) != ""
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
