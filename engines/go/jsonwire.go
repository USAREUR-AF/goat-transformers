package goatxf

import (
	"fmt"
	"strconv"
	"strings"
)

// The json wire (spec/engine-spec.md, "Version 0.5: the `json` wire"): the
// message is one JSON object and a locator is a path of member names.

// isIntLiteral reports whether s is a JSON integer literal: an optional minus
// and digits, with no fraction and no exponent.
func isIntLiteral(s string) bool {
	t := strings.TrimPrefix(s, "-")
	if t == "" || (len(t) > 1 && t[0] == '0') {
		return false
	}
	for _, c := range t {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// canonNumber is the canonical text of a JSON number literal: shortest
// round-trip decimal in plain notation, an integral value without a decimal
// point, negative zero as 0 (0.1.1 ruling 3). An integer literal that fits a
// 64-bit integer keeps its digits.
func canonNumber(lit string) string {
	if isIntLiteral(lit) {
		if i, err := strconv.ParseInt(lit, 10, 64); err == nil {
			return strconv.FormatInt(i, 10)
		}
	}
	f, err := strconv.ParseFloat(lit, 64)
	if err != nil {
		return lit
	}
	s, err := formatFloat(f)
	if err != nil {
		return lit
	}
	return s
}

// isCanonNumberText reports whether s is canonical JSON number text.
func isCanonNumberText(s string) bool {
	t := strings.TrimPrefix(s, "-")
	intPart, frac, hasFrac := strings.Cut(t, ".")
	if !isIntLiteral(intPart) || (hasFrac && frac == "") {
		return false
	}
	for _, c := range frac {
		if c < '0' || c > '9' {
			return false
		}
	}
	return canonNumber(s) == s
}

// whenHoldsJSON reports whether a `when` holds for member v of a geojson or
// json message (nil when the member is missing): a string equal to the value,
// or a number or boolean whose canonical text equals it; `present` holds when
// the member exists and is not null.
func whenHoldsJSON(w *When, v *jval) bool {
	if v == nil || v.k == jNull {
		return false
	}
	if w.present {
		return true
	}
	switch v.k {
	case jStr, jBool:
		return v.s == w.text
	case jNum:
		return canonNumber(v.s) == w.text
	}
	return false
}

// whenJSONText is the JSON text a `when` value is written as (0.5 ruling 11):
// canonical number text as a number, true and false as booleans, anything
// else, and any value written with a leading `=`, as a string.
func whenJSONText(w *When) string {
	if !w.forced && (w.text == "true" || w.text == "false" || isCanonNumberText(w.text)) {
		return w.text
	}
	return jsonQuote(w.text)
}

// jsonQuote writes a JSON string in the json wire's canonical form: `"`, `\`
// and the control characters below U+0020 are escaped (\n \r \t \b \f by name,
// the others as \u00xx in lowercase hex); everything else is UTF-8.
func jsonQuote(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, r)
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

// jsonLookup walks a member path through nested objects. It returns nil when
// a member is missing or a name but the last does not hold an object.
func jsonLookup(root *jval, path []string) *jval {
	cur := root
	for _, seg := range path {
		if cur == nil || cur.k != jObj {
			return nil
		}
		cur = cur.member(seg)
	}
	return cur
}

// decodeJSONValue turns one JSON member into the model value of a field. A
// value of the wrong JSON type for the transform is a decode failure.
func decodeJSONValue(f *Field, v *jval) (Value, error) {
	wrong := func(want string) (Value, error) {
		return Value{}, fmt.Errorf("wire value is not a JSON %s", want)
	}
	if f.jbool {
		if v.k != jBool {
			return wrong("boolean")
		}
		if v.s == "true" {
			return Value{Kind: KindInt, I: 1}, nil
		}
		return Value{Kind: KindInt, I: 0}, nil
	}
	switch f.Transform {
	case "string", "iso8601_ms":
		if v.k != jStr {
			return wrong("string")
		}
	default: // float, int
		if v.k != jNum {
			return wrong("number")
		}
		return decodeJSONNumber(f, v.s)
	}
	return f.tf.decode(v.s)
}

// decodeJSONNumber reads a JSON number through `int` or `float` (ruling 2d
// of 0.11): through `float` the nearest double, refused when it is infinite;
// through `int` the exact value, which must be an integer within a signed
// 64-bit integer whatever its fraction of zero or its exponent.
func decodeJSONNumber(f *Field, lit string) (Value, error) {
	switch f.Transform {
	case "int":
		i, err := exactInt(lit)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindInt, I: i}, nil
	case "float":
		x, err := parseNumberText(lit)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindFloat, F: x}, nil
	}
	return f.tf.decode(lit)
}

// fieldJSON decodes one member with the value types of the geojson wire: a
// string through the transform's text grammar, a number by ruling 2d of 0.11.
func (d *decodeState) fieldJSON(f *Field, v *jval) {
	if v.k != jNum {
		d.field(f, v.s)
		return
	}
	if _, done := d.rec.Fields[f.Key]; done {
		return
	}
	val, err := decodeJSONNumber(f, v.s)
	if err != nil {
		d.fail(f, err.Error())
		return
	}
	d.store(f, val)
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

// jsonScope decodes the lines of one scope from v: the message, or one item
// of a group. A member path reads into v when it is an object; `.` is v
// itself. geo selects the value types of the geojson wire, which the items of
// a geojson group keep (0.7 ruling 7); a member that is null is absent on
// both.
func (d *decodeState) jsonScope(lay *layout, v *jval, geo bool) error {
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			m := v
			if !f.dot {
				m = jsonLookup(v, f.loc.path)
			}
			if m == nil || m.k == jNull {
				continue
			}
			if f.sentinelJSON(m) {
				continue
			}
			if geo {
				if m.k == jStr || m.k == jNum {
					d.fieldJSON(f, m)
				} else {
					d.fail(f, "wire value is not a JSON string or number")
				}
				continue
			}
			val, err := decodeJSONValue(f, m)
			if err != nil {
				d.fail(f, err.Error())
				continue
			}
			d.store(f, val)
		case ln.g != nil:
			if err := d.jsonGroup(ln.g, jsonLookup(v, ln.g.loc.path), geo); err != nil {
				return err
			}
		}
	}
	return nil
}

// jsonGroup decodes the list of a group from the member v (nil when the
// member is missing). The list is present when the member exists and is an
// array; null is absent and any other value is malformed-wire. Each element
// is one item; unmapped content of an item is dropped.
func (d *decodeState) jsonGroup(g *Group, v *jval, geo bool) error {
	if v == nil || v.k == jNull {
		return nil
	}
	if v.k != jArr {
		return &Error{Kind: ErrMalformedWire, Format: d.pack.Format, Locator: g.Locator, Detail: "the member of list " + g.List + " is not an array"}
	}
	items := make([]*Item, 0, len(v.vals))
	for _, e := range v.vals {
		it, err := d.item(func() error { return d.jsonScope(g.body, e, geo) })
		if err != nil {
			return err
		}
		items = append(items, it)
	}
	d.rec.SetList(g.List, items)
	return nil
}

// jnode is one member of the object being encoded: a scalar (raw JSON text),
// a nested object, or a position that nothing filled.
type jnode struct {
	name     string
	raw      string
	set      bool
	weak     bool // raw is a sentinel, which a value replaces (0.9 ruling 16)
	children []*jnode
}

func (n *jnode) child(name string) *jnode {
	for _, c := range n.children {
		if c.name == name {
			return c
		}
	}
	c := &jnode{name: name}
	n.children = append(n.children, c)
	return c
}

// at returns the node at path, creating it and the objects above it at the
// position of the first line that addresses them.
func (n *jnode) at(path []string) *jnode {
	cur := n
	for _, seg := range path {
		cur = cur.child(seg)
	}
	return cur
}

// write renders the members of n that hold something. It reports false when
// n holds nothing, so a nested object with no members is not written.
func (n *jnode) write(b *strings.Builder) bool {
	if len(n.children) > 0 {
		var inner strings.Builder
		any := false
		for _, c := range n.children {
			var cb strings.Builder
			if !c.write(&cb) {
				continue
			}
			if any {
				inner.WriteByte(',')
			}
			any = true
			inner.WriteString(jsonQuote(c.name))
			inner.WriteByte(':')
			inner.WriteString(cb.String())
		}
		if any {
			b.WriteByte('{')
			b.WriteString(inner.String())
			b.WriteByte('}')
			return true
		}
	}
	if n.set {
		b.WriteString(n.raw)
		return true
	}
	return false
}

// encodeJSONField returns the JSON text of a field's value.
func encodeJSONField(p *Pack, f *Field, v Value) (string, error) {
	if f.jbool {
		i, err := valueToInt(v)
		if err != nil {
			return "", encodeErr(p, f, err)
		}
		switch i {
		case 1:
			return "true", nil
		case 0:
			return "false", nil
		}
		return "", encodeErr(p, f, fmt.Errorf("bool writes 1 or 0, got %d", i))
	}
	s, err := f.tf.encode(v)
	if err != nil {
		return "", encodeErr(p, f, err)
	}
	if f.tf.number {
		return s, nil
	}
	return jsonQuote(s), nil
}

// jsonFieldRaw is the JSON text of a field's value: on the json wire by its
// transform; in an item of a geojson group a number for a numeric transform
// and a string otherwise, as the geojson wire writes its members.
func jsonFieldRaw(p *Pack, f *Field, v Value, geo bool) (string, error) {
	if !geo {
		return encodeJSONField(p, f, v)
	}
	s, err := f.tf.encode(v)
	if err != nil {
		return "", encodeErr(p, f, err)
	}
	if f.tf.number {
		return s, nil
	}
	return jsonString(s), nil
}

// encodeJSONItems writes the array of a group: one element per item, each by
// the group body's lines. An item with nothing written is `{}`, or `null`
// when the body reads the item itself as a scalar.
func encodeJSONItems(p *Pack, g *Group, items []*Item, geo bool) (string, error) {
	var b strings.Builder
	b.WriteByte('[')
	for i, it := range items {
		if i > 0 {
			b.WriteByte(',')
		}
		node := &jnode{}
		if err := encodeJSONScope(p, g.body, it, node, geo); err != nil {
			return "", err
		}
		if !node.write(&b) {
			// A scalar (`.`) item with no value is `null` (0.7 ruling 11).
			if len(g.dots) > 0 {
				b.WriteString("null")
			} else {
				b.WriteString("{}")
			}
		}
	}
	b.WriteByte(']')
	return b.String(), nil
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

// encodeJSONScope writes the lines of one scope under root: the message, or
// one item of a group. A group writes an array at its member when the list is
// present, `[]` when it is empty.
func encodeJSONScope(p *Pack, lay *layout, rec *Item, root *jnode, geo bool) error {
	for _, ln := range lay.lines {
		if g := ln.g; g != nil {
			n := root.at(g.loc.path)
			items, ok := rec.Lists[g.List]
			if !ok {
				continue
			}
			raw, err := encodeJSONItems(p, g, items, geo)
			if err != nil {
				return err
			}
			if !n.set {
				n.raw, n.set = raw, true
			}
			continue
		}
		if w := ln.w; w != nil {
			// `present` does not map the member (0.5 ruling 27): only the
			// objects above it take their position from this line, and a
			// scalar there is written with the residue.
			if w.present {
				root.at(w.loc.path[:len(w.loc.path)-1])
				continue
			}
			n := root.at(w.loc.path)
			n.raw, n.set, n.weak = whenJSONText(w), true, false
			continue
		}
		f := ln.f
		n := root.at(f.loc.path)
		v, ok, err := fieldValue(p, lay, f, rec)
		if err != nil {
			return err
		}
		if !ok {
			// An absent key writes the sentinel where nothing is written; a
			// scalar item writes it in place of null (0.9 ruling 5).
			if f.absent != nil && !n.set {
				n.raw, n.set, n.weak = f.sentinelJSONText(geo), true, true
			}
			continue
		}
		raw, err := jsonFieldRaw(p, f, v, geo)
		if err != nil {
			return err
		}
		if !n.set || n.weak {
			n.raw, n.set, n.weak = raw, true, false
		}
	}
	return nil
}
