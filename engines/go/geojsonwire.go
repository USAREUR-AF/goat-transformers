//go:build !goat_wires || goat_wire_geojson

package goatxf

import (
	"strings"
)

func writeJSON(b *strings.Builder, v *jval) {
	switch v.k {
	case jObj:
		b.WriteByte('{')
		for i, k := range v.keys {
			if i > 0 {
				b.WriteByte(',')
			}
			b.WriteString(jsonString(k))
			b.WriteByte(':')
			writeJSON(b, v.vals[i])
		}
		b.WriteByte('}')
	case jArr:
		b.WriteByte('[')
		for i, e := range v.vals {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSON(b, e)
		}
		b.WriteByte(']')
	case jStr:
		b.WriteString(jsonString(v.s))
	case jNum, jBool:
		b.WriteString(v.s)
	case jNull:
		b.WriteString("null")
	}
}

func rawJSON(v *jval) string {
	var b strings.Builder
	writeJSON(&b, v)
	return b.String()
}

var coordNames = [3]string{"lon", "lat", "alt"}

func decodeGeoJSON(d *decodeState, b []byte) error {
	p := d.pack
	bad := func(loc, detail string) error {
		return &Error{Kind: ErrMalformedWire, Format: p.Format, Locator: loc, Detail: detail}
	}
	root, err := parseJSON(b, true)
	if err != nil {
		return bad("", err.Error())
	}
	if root.k != jObj {
		return bad("", "top level is not a JSON object")
	}
	if t := root.member("type"); t == nil || t.k != jStr || t.s != "Feature" {
		return bad("type", `member "type" must be "Feature"`)
	}
	lay, err := d.choose(func(w *When) bool {
		var v *jval
		if w.loc.kind == locProp {
			if props := root.member("properties"); props != nil && props.k == jObj {
				v = props.member(w.loc.name)
			}
		} else {
			v = root.member(w.loc.name)
		}
		return whenHoldsJSON(w, v)
	})
	if err != nil {
		return err
	}
	// value maps one wire member to its group, its mapped fields or residue.
	var groupErr error
	members := map[string]*jval{}
	value := func(loc string, v *jval) {
		if g := lay.groupAt[loc]; g != nil {
			if err := d.jsonGroup(g, v, true); err != nil && groupErr == nil {
				groupErr = err
			}
			return
		}
		if len(lay.fieldsAt[loc]) > 0 || lay.parts[loc] != nil {
			members[loc] = v
			return
		}
		if lay.whenAt[loc] {
			return
		}
		// Residue keeps a scalar's original text and writes it back as a
		// string (0.1 behaviour, 0.5 ruling 28); an array and an object come
		// back as they were; null is dropped (0.6 ruling 13).
		switch v.k {
		case jStr, jNum, jBool:
			d.residue(loc, v.s, false)
		case jNull:
		default:
			d.residue(loc, rawJSON(v), true)
		}
	}
	for i, key := range root.keys {
		v := root.vals[i]
		switch key {
		case "type":
		case "geometry":
			if v.k == jNull {
				continue
			}
			if v.k != jObj {
				return bad("geometry", "geometry is not an object or null")
			}
			if gt := v.member("type"); gt == nil || gt.k != jStr || gt.s != "Point" {
				return bad("geometry", `geometry "type" must be "Point"`)
			}
			c := v.member("coordinates")
			if c == nil || c.k != jArr || len(c.vals) < 2 || len(c.vals) > 3 {
				return bad("geometry", "coordinates must be [lon, lat] or [lon, lat, alt]")
			}
			for j, cv := range c.vals {
				if cv.k != jNum {
					return bad("geometry."+coordNames[j], "coordinate is not a number")
				}
				value("geometry."+coordNames[j], cv)
			}
		case "properties":
			if v.k == jNull {
				continue
			}
			if v.k != jObj {
				return bad("properties", "properties is not an object or null")
			}
			for j, pk := range v.keys {
				value("properties."+pk, v.vals[j])
			}
		default:
			value(key, v)
		}
	}
	// The fields, in line order: the earliest line of a key gives its value
	// (0.6, One key at several locators).
	for _, ln := range lay.lines {
		v := members[lineLocator(ln)]
		if v == nil || v.k == jNull {
			continue
		}
		if isPartLine(ln) {
			d.partJSON(ln, v, true)
			continue
		}
		f := ln.f
		if f == nil || f.sentinelJSON(v) {
			continue
		}
		switch v.k {
		case jStr, jNum:
			if v.k == jStr && f.tf != nil && f.tf.numOnly {
				// scale and iscale refuse a string member (0.15 ruling 23).
				d.fail(f, "wire value is not a JSON number")
				continue
			}
			d.fieldJSON(f, v)
		default:
			d.fail(f, "wire value is not a JSON string or number")
		}
	}
	return groupErr
}

type jmember struct{ key, raw string }

// addMember writes a member at the position of the first write to it. The
// first value stays unless force is set.
func addMember(ms []jmember, key, raw string, force bool) []jmember {
	for i, m := range ms {
		if m.key == key {
			if force {
				ms[i].raw = raw
			}
			return ms
		}
	}
	return append(ms, jmember{key, raw})
}

// encodeGeoJSON writes the layout's field and when lines in line order. Of
// two fields on one locator the earliest present wins; a when value is
// written over any field.
func encodeGeoJSON(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	var coords [3]*string
	var props, top []jmember
	written := map[string]bool{}
	weak := map[string]bool{}  // the locators that hold a sentinel, which a value replaces (0.9 ruling 16)
	nulls := map[string]bool{} // the locators that hold the null of a `null` option (0.56)
	put := func(l locator, raw string, force bool) {
		switch l.kind {
		case locCoord:
			if coords[l.idx] == nil || force {
				s := raw
				coords[l.idx] = &s
			}
		case locProp:
			props = addMember(props, l.name, raw, force)
		case locTop:
			top = addMember(top, l.name, raw, force)
		}
	}
	for _, ln := range lay.lines {
		if pg := lay.parts[lineLocator(ln)]; pg != nil {
			if !pg.isFirst(ln) {
				continue
			}
			tok, ok, err := pg.token(p, lay, rec)
			if err != nil {
				return nil, err
			}
			if ok {
				put(pg.fields[0].loc, jsonString(tok), false)
				written[pg.fields[0].Locator] = true
			}
			continue
		}
		if g := ln.g; g != nil {
			// A group writes an array at its member when the list is present.
			if items, ok := rec.Lists[g.List]; ok {
				raw, err := encodeJSONItems(p, g, items, true)
				if err != nil {
					return nil, err
				}
				put(g.loc, raw, false)
				written[g.Locator] = true
			}
			continue
		}
		if w := ln.w; w != nil {
			if !w.present {
				put(w.loc, whenJSONText(w), true)
				written[w.Locator] = true
			}
			continue
		}
		f := ln.f
		s, ok, err := encodeField(p, lay, f, rec)
		if err != nil {
			return nil, err
		}
		if w := lay.forced[f.Locator]; w != nil {
			put(w.loc, whenJSONText(w), true)
			written[f.Locator] = true
			continue
		}
		if !ok {
			// A sentinel is written where no line has written; one for lon or
			// lat counts as a value, so geometry is written (0.9 ruling 10).
			if f.hasExact() && !f.suppressed(rec) && (!written[f.Locator] || nulls[f.Locator]) {
				put(f.loc, f.sentinelJSONText(true), nulls[f.Locator])
				written[f.Locator], weak[f.Locator] = true, true
				delete(nulls, f.Locator)
			} else if f.Null && !f.suppressed(rec) && !written[f.Locator] {
				// No line on the member writes a value: the member is null
				// (0.56).
				put(f.loc, "null", false)
				written[f.Locator], weak[f.Locator], nulls[f.Locator] = true, true, true
			}
			continue
		}
		raw := s
		if !f.tf.number {
			raw = jsonString(s)
		}
		if f.loc.kind == locCoord && !f.tf.number {
			return nil, &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: f.Locator, Detail: "coordinate needs a numeric transform"}
		}
		put(f.loc, raw, weak[f.Locator])
		delete(weak, f.Locator)
		delete(nulls, f.Locator)
		written[f.Locator] = true
	}
	for _, r := range residueFor(p, ent, written) {
		l, err := parseLocator(WireGeoJSON, r.Locator, true)
		if err != nil {
			return nil, &Error{Kind: ErrBadLocator, Format: p.Format, Locator: r.Locator, Detail: "residue: " + err.Error()}
		}
		raw := r.Value
		if !r.JSON {
			raw = jsonString(r.Value)
		}
		put(l, raw, false)
	}
	var b strings.Builder
	b.WriteString(`{"type":"Feature","geometry":`)
	switch {
	case coords[0] == nil || coords[1] == nil:
		// If either lon or lat is absent, geometry is null (0.1.1 ruling 5).
		b.WriteString("null")
	default:
		b.WriteString(`{"type":"Point","coordinates":[`)
		b.WriteString(*coords[0])
		b.WriteByte(',')
		b.WriteString(*coords[1])
		if coords[2] != nil {
			b.WriteByte(',')
			b.WriteString(*coords[2])
		}
		b.WriteString("]}")
	}
	b.WriteString(`,"properties":{`)
	for i, m := range props {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(jsonString(m.key))
		b.WriteByte(':')
		b.WriteString(m.raw)
	}
	b.WriteByte('}')
	for _, m := range top {
		b.WriteByte(',')
		b.WriteString(jsonString(m.key))
		b.WriteByte(':')
		b.WriteString(m.raw)
	}
	b.WriteByte('}')
	return []byte(b.String()), nil
}
