package goatxf

import (
	"fmt"
	"strings"
)

// The line checks of ruling 5b of 0.11 that read a `field`, `when` or
// `const` line: the transform's name and its parameters, the locator form,
// the field options and the values of an `absent` option. The wire is known
// when such a line is read, since the `wire` line stands before it.

// needsWire names the directives that stand after the `wire` line (ruling 5b
// of 0.11); such a line before it is missing-wire.
var needsWire = map[string]bool{
	"root": true, "field": true, "when": true, "const": true, "group": true, "end": true,
	"word_bytes": true, "bit_order": true, "layout": true, "also": true, "pad": true,
	"align": true, "presence": true, "if": true, "opt": true, "chain": true, "fx": true,
	"length": true,
}

// noParamTransforms are the transforms whose name stands alone.
var noParamTransforms = map[string]bool{
	"string": true, "float": true, "int": true, "iso8601_ms": true, "bool": true,
	"uint": true, "twos": true, "f32": true, "f64": true, "ascii": true, "sixbit": true,
	"pstring": true, "pvarint": true, "psint": true, "pdouble": true, "pfloat": true,
	"utf8": true, "hex": true, // tlv (0.13); their wire is checked after the file
}

// checkTransformName checks the transform of a field line whatever the wire:
// a name, the text before its first `:`, that no wire has is
// unknown-transform; parameters that are not valid are bad-directive (ruling
// 4d of 0.11, and the parameters of the text transforms of 0.10). Whether
// the transform is valid on the pack's wire is checked after the file.
func checkTransformName(name string) (ErrorKind, error) {
	base, _, hasParam := strings.Cut(name, ":")
	switch base {
	case "linscale":
		if _, err := newLinscale(name); err != nil {
			return ErrBadDirective, err
		}
	case "uscale", "sscale":
		// A fraction factor is unsigned (ruling 25 of 0.15).
		if err := checkUnsignedFraction(name); err != nil {
			return ErrBadDirective, err
		}
		if _, err := newScale(name, base == "sscale"); err != nil {
			return ErrBadDirective, err
		}
	case "uiscale", "siscale", "smag", "smscale", "f32scale", "f64scale", "chars", "octal", "scale", "iscale":
		// The value transforms of 0.15: a parameter that does not parse and
		// an unknown character set are bad-directive.
		if err := checkV015Params(base, name); err != nil {
			return ErrBadDirective, err
		}
	case "dec", "dm", "hms", "hms_dmy":
		if _, kind, err := resolveTextTransform(name); err != nil {
			return kind, err
		}
	default:
		if !noParamTransforms[base] {
			return ErrUnknownTransform, fmt.Errorf("unknown transform %q", name)
		}
		if hasParam {
			if base == "int" {
				if _, kind, err := resolveTextTransform(name); err != nil {
					return kind, err
				}
				return "", nil
			}
			return ErrBadDirective, fmt.Errorf("transform %s takes no parameter, got %q", base, name)
		}
	}
	return "", nil
}

// lineWire is the wire a line's locator is read on: inside a group of a
// geojson pack, the json wire.
func (p *Pack) lineWire(inGroup bool) string {
	if inGroup && p.Wire == WireGeoJSON {
		return WireJSON
	}
	return p.Wire
}

// checkLocatorForm checks the form of the locator of a field, when or const
// line (ruling 5a of 0.11). The forms earlier versions name stay
// bad-directive and are checked after the file; the locator `.` is checked
// there too. It returns the locator read, or ok false when the line leaves it
// to the checks after the file.
func (p *Pack) checkLocatorForm(s string, inGroup bool) (locator, bool, ErrorKind, error) {
	wire := p.lineWire(inGroup)
	switch {
	case wire == WireTLV:
		// Every tag of a tlv path is checked after the file, against the
		// `tag` line (0.13, "every check in this paragraph ... runs after
		// the file is read"); 5a of 0.11 names no tlv form.
		return locator{}, false, "", nil
	case wire == WireText:
		l, err := parseTextLocator(s)
		if err != nil {
			return l, false, ErrBadDirective, err
		}
		return l, true, "", nil
	case p.seq:
		if strings.Contains(s, ":") {
			// A positional locator in a sequential pack is bad-directive,
			// reported after the file as in 0.8.
			return locator{}, false, "", nil
		}
		n, err := parseSmallUint(s)
		if err != nil || n < 1 {
			return locator{}, false, ErrBadLocator, fmt.Errorf("a sequential locator is a bit length of 1 or more, got %q", s)
		}
		return locator{raw: s, kind: locBits, blen: n}, true, "", nil
	case wire == WireBits && isDigits(s):
		return locator{}, false, "", nil
	case s == "." && (wire == WireJSON || wire == WireGeoJSON || wire == WireProtobuf):
		return locator{}, false, "", nil
	}
	l, err := parseLocator(wire, s, false)
	if err != nil {
		return l, false, ErrBadLocator, err
	}
	return l, true, "", nil
}

// checkFieldLine runs the line checks of a field line in order: the
// transform (7), the locator form (8), the field options (9) and the values
// of an `absent` option (10), the last not on a bits field longer than 64
// bits, nor where the transform is not valid on the wire: both are checked
// after the file (ruling 4d of 0.11).
func (p *Pack) checkFieldLine(f *Field, opts []string, inGroup bool) (ErrorKind, error) {
	// On tlv a transform not in its table, and uscale or sscale parameters
	// that do not parse, are bad-directive after the file (0.13 ruling 8).
	if p.Wire != WireTLV {
		if kind, err := checkTransformName(f.Transform); err != nil {
			return kind, err
		}
	}
	loc, ok, kind, err := p.checkLocatorForm(f.Locator, inGroup)
	if err != nil {
		return kind, err
	}
	if err := parseFieldOptions(f, opts); err != nil {
		return ErrBadDirective, err
	}
	if f.Absent == nil || !ok || p.Wire == WireText {
		return "", nil
	}
	tmp := *f
	tmp.loc = loc
	if _, err := resolveFieldTransform(p.Wire, &tmp); err != nil {
		return "", nil
	}
	if err := resolveSentinels(p.lineWire(inGroup), &tmp); err != nil {
		return ErrBadDirective, err
	}
	return "", nil
}

// checkGroupLocator checks the locator form of a group line as it is read
// (ruling 5a of 0.11): an empty step on xml, an empty member name on json
// and geojson, a step that is not a field number on protobuf. The other
// group forms are checked after the file.
func (p *Pack) checkGroupLocator(s string, inGroup bool) error {
	if p.seq {
		return nil
	}
	switch p.lineWire(inGroup) {
	case WireXML:
		for _, e := range strings.Split(s, "/") {
			if e == "" {
				return fmt.Errorf("an xml group locator has an empty step, got %q", s)
			}
		}
	case WireJSON, WireGeoJSON:
		for _, e := range strings.Split(s, ".") {
			if e == "" {
				return fmt.Errorf("a group locator has an empty member name, got %q", s)
			}
		}
	case WireProtobuf:
		if _, err := parseLocator(WireProtobuf, s, false); err != nil {
			return err
		}
	}
	return nil
}

// checkWhenLine checks the locator form of a when or const line (8).
func (p *Pack) checkWhenLine(s string, inGroup bool) (ErrorKind, error) {
	if p.seq {
		return "", nil
	}
	_, _, kind, err := p.checkLocatorForm(s, inGroup)
	if err != nil {
		return kind, err
	}
	return "", nil
}
