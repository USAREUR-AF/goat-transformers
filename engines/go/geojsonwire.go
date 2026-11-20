package goatxf

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"unicode/utf8"
)

type jkind int

const (
	jObj jkind = iota + 1
	jArr
	jStr
	jNum
	jBool
	jNull
)

// jval is an order-preserving JSON value; s holds a string's text, a number's
// literal, or "true"/"false".
type jval struct {
	k    jkind
	s    string
	keys []string
	vals []*jval
	// mapped is set when a field line reads this value (0.15 ruling 27).
	mapped bool
}

func (v *jval) member(key string) *jval {
	for i, k := range v.keys {
		if k == key {
			return v.vals[i]
		}
	}
	return nil
}

// parseJSON reads one JSON value. A member name that occurs twice in one
// object is an error unless allowDup is set (the json wire refuses it, 0.5
// ruling 22; the geojson wire keeps its 0.1 behaviour and accepts it, ruling
// 28): the later value then replaces the earlier one, at the earlier position.
func parseJSON(b []byte, allowDup bool) (*jval, error) {
	// RFC 8259 text is UTF-8; the decoder below would replace a byte that is
	// not with U+FFFD instead of refusing it.
	if !utf8.Valid(b) {
		return nil, fmt.Errorf("the input is not valid UTF-8")
	}
	if jsonLoneSurrogate(b) {
		return nil, fmt.Errorf("a \\u escape is half of a surrogate pair without its other half")
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	v, err := readJSON(dec, allowDup, 1)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("trailing data after the Feature")
	}
	return v, nil
}

// readJSON reads one value; level is the nesting level an array or an object
// read here has (the outermost is level 1, 0.8 ruling 35).
// jsonLoneSurrogate reports whether a string of the JSON text b holds a \u
// escape that is half of a surrogate pair without its other half (0.8 ruling
// 40); the decoder would read it as U+FFFD. The scan follows strings and
// escapes only: the decoder checks the rest of the grammar.
func jsonLoneSurrogate(b []byte) bool {
	// escape reads the \uXXXX escape at i, -1 when there is none.
	escape := func(i int) int {
		if i+6 > len(b) || b[i] != '\\' || b[i+1] != 'u' {
			return -1
		}
		n := 0
		for _, c := range b[i+2 : i+6] {
			switch {
			case c >= '0' && c <= '9':
				n = n<<4 | int(c-'0')
			case c >= 'a' && c <= 'f':
				n = n<<4 | int(c-'a'+10)
			case c >= 'A' && c <= 'F':
				n = n<<4 | int(c-'A'+10)
			default:
				return -1
			}
		}
		return n
	}
	inString := false
	for i := 0; i < len(b); i++ {
		switch {
		case !inString:
			inString = b[i] == '"'
		case b[i] == '"':
			inString = false
		case b[i] == '\\':
			n := escape(i)
			switch {
			case n < 0:
				i++ // the escaped character
			case n >= 0xdc00 && n <= 0xdfff:
				return true // a low half with no high half before it
			case n >= 0xd800 && n <= 0xdbff:
				if lo := escape(i + 6); lo < 0xdc00 || lo > 0xdfff {
					return true
				}
				i += 11
			default:
				i += 5
			}
		}
	}
	return false
}

func readJSON(dec *json.Decoder, allowDup bool, level int) (*jval, error) {
	tok, err := dec.Token()
	if err != nil {
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("unexpected end of input")
		}
		return nil, err
	}
	switch t := tok.(type) {
	case json.Delim:
		if (t == '{' || t == '[') && level > maxNesting {
			return nil, fmt.Errorf("arrays and objects are nested deeper than %d levels", maxNesting)
		}
		switch t {
		case '{':
			o := &jval{k: jObj}
			seen := map[string]int{}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key, ok := kt.(string)
				if !ok {
					return nil, fmt.Errorf("object key is not a string")
				}
				at, dup := seen[key]
				if dup && !allowDup {
					return nil, fmt.Errorf("duplicate member %q", key)
				}
				val, err := readJSON(dec, allowDup, level+1)
				if err != nil {
					return nil, err
				}
				if dup {
					o.vals[at] = val
					continue
				}
				seen[key] = len(o.keys)
				o.keys = append(o.keys, key)
				o.vals = append(o.vals, val)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return o, nil
		case '[':
			a := &jval{k: jArr}
			for dec.More() {
				val, err := readJSON(dec, allowDup, level+1)
				if err != nil {
					return nil, err
				}
				a.vals = append(a.vals, val)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return a, nil
		}
		return nil, fmt.Errorf("unexpected %q", t.String())
	case string:
		return &jval{k: jStr, s: t}, nil
	case json.Number:
		return &jval{k: jNum, s: t.String()}, nil
	case bool:
		if t {
			return &jval{k: jBool, s: "true"}, nil
		}
		return &jval{k: jBool, s: "false"}, nil
	case nil:
		return &jval{k: jNull}, nil
	}
	return nil, fmt.Errorf("unexpected token %v", tok)
}

func jsonString(s string) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	return strings.TrimSuffix(b.String(), "\n")
}

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
	value := func(loc string, v *jval) {
		if g := lay.groupAt[loc]; g != nil {
			if err := d.jsonGroup(g, v, true); err != nil && groupErr == nil {
				groupErr = err
			}
			return
		}
		if fs := lay.fieldsAt[loc]; len(fs) > 0 {
			for _, f := range fs {
				if v.k != jNull && f.sentinelJSON(v) {
					continue
				}
				switch v.k {
				case jNull:
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
	weak := map[string]bool{} // the locators that hold a sentinel, which a value replaces (0.9 ruling 16)
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
			if f.absent != nil && !f.suppressed(rec) && !written[f.Locator] {
				put(f.loc, f.sentinelJSONText(true), false)
				written[f.Locator], weak[f.Locator] = true, true
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
