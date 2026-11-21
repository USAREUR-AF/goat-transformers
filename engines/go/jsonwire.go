//go:build !goat_wires || goat_wire_json

package goatxf

import (
	"math"
	"strconv"
	"strings"
)

// The json wire (spec/engine-spec.md, "Version 0.5: the `json` wire"): the
// message is one JSON object and a locator is a path of member names.

// unmappedOverflow returns a number anywhere in v whose magnitude rounds
// above the largest finite double and that no field line read, or nil.
func unmappedOverflow(v *jval) *jval {
	switch v.k {
	case jNum:
		if !v.mapped {
			if f, _ := strconv.ParseFloat(v.s, 64); math.IsInf(f, 0) {
				return v
			}
		}
	case jObj, jArr:
		for _, c := range v.vals {
			if o := unmappedOverflow(c); o != nil {
				return o
			}
		}
	}
	return nil
}

func decodeJSONWire(d *decodeState, b []byte) error {
	p := d.pack
	root, err := parseJSON(b, false)
	if err != nil {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: err.Error()}
	}
	if root.k != jObj {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: "the message is not a JSON object"}
	}
	lay, err := d.choose(func(w *When) bool {
		return whenHoldsJSON(w, jsonLookup(root, w.loc.path))
	})
	if err != nil {
		return err
	}
	if err := d.jsonScope(lay, root, false); err != nil {
		return err
	}
	// A number outside the double range that no field reads is malformed
	// (0.15 ruling 27, extending 0.8 ruling 39).
	if v := unmappedOverflow(root); v != nil {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: "number " + v.s + " is outside the double range and no field maps it"}
	}
	// Residue: every scalar member at any depth of nested objects that no
	// field or when line maps, keyed by its path, as canonical JSON text.
	// Arrays, nulls and members whose name holds a `.` are not carried.
	var residueErr error
	var walk func(o *jval, prefix string)
	walk = func(o *jval, prefix string) {
		for i, name := range o.keys {
			if strings.Contains(name, ".") {
				continue
			}
			v := o.vals[i]
			path := prefix + name
			switch v.k {
			case jObj:
				walk(v, path+".")
			case jStr:
				if !lay.maps(path) {
					d.residue(path, jsonQuote(v.s), true)
				}
			case jNum:
				if !lay.maps(path) {
					// A residue number whose nearest double is infinite has
					// no canonical text (ruling 2d of 0.11).
					if _, ok := jsonNumberCanon(v.s); !ok && residueErr == nil {
						residueErr = &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: path, Detail: "a number no line maps has no finite double value"}
					}
					d.residue(path, canonNumber(v.s), true)
				}
			case jBool:
				if !lay.maps(path) {
					d.residue(path, v.s, true)
				}
			}
		}
	}
	walk(root, "")
	return residueErr
}

// encodeJSONWire writes one JSON object: mapped and when members in line
// order, a nested object at the position of the first line that addresses
// into it, then the residue members of each object in input order.
func encodeJSONWire(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	root := &jnode{}
	if err := encodeJSONScope(p, lay, rec, root, false); err != nil {
		return nil, err
	}
	for _, r := range ent.Residue {
		if r.Format != p.Format {
			continue
		}
		n := root.at(strings.Split(r.Locator, "."))
		if n.set {
			continue
		}
		n.raw, n.set = r.Value, true
		if !r.JSON {
			n.raw = jsonQuote(r.Value)
		}
	}
	var b strings.Builder
	if !root.write(&b) {
		return []byte("{}"), nil
	}
	return []byte(b.String()), nil
}
