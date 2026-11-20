package goatxf

import (
	"fmt"
	"strings"
)

// maxNesting is the deepest nesting a message may have: elements on xml (the
// root is level 1), arrays and objects on json and geojson (the outermost is
// level 1). A deeper message is malformed-wire (0.8 ruling 35).
const maxNesting = 64

type xattr struct{ name, value string }

type xnode struct {
	name     string
	attrs    []xattr
	text     strings.Builder
	children []*xnode
}

// find walks a path of child element names from n, taking the first sibling
// of each name. It returns nil when an element of the path is missing.
func (n *xnode) find(path []string) *xnode {
	cur := n
	for _, seg := range path {
		var next *xnode
		for _, c := range cur.children {
			if c.name == seg {
				next = c
				break
			}
		}
		if next == nil {
			return nil
		}
		cur = next
	}
	return cur
}

func (n *xnode) attr(name string) (string, bool) {
	for _, a := range n.attrs {
		if a.name == name {
			return a.value, true
		}
	}
	return "", false
}

func decodeXML(d *decodeState, b []byte) error {
	p := d.pack
	root, err := parseXML(p.Format, b)
	if err != nil {
		return err
	}
	if !p.HasKinds() && root.name != p.Root {
		return &Error{Kind: ErrMissingRoot, Format: p.Format, Detail: "root element is <" + root.name + ">, want <" + p.Root + ">"}
	}
	// A kind is considered only when the document's root element has the
	// kind's root name (its own, else the pack's), before its when lines.
	lay, err := d.chooseAmong(p.kindsByRoot[root.name], true, func(w *When) bool {
		n := root.find(w.loc.path)
		if n == nil {
			return false
		}
		if w.loc.kind == locAttr {
			v, ok := n.attr(w.loc.name)
			return ok && (w.present || v == w.text)
		}
		// An element with no character data has no text: a when with a
		// value, the empty text included, does not hold (ruling 1m of 0.11).
		t := n.text.String()
		return w.present || (t != "" && t == w.text)
	})
	if err != nil {
		return err
	}
	if err := d.xmlScope(lay, root); err != nil {
		return err
	}
	// Residue is the unmapped attributes of the root element (0.1.1 ruling 6);
	// unmapped child elements and their attributes are not carried.
	for _, a := range root.attrs {
		if loc := "@" + a.name; !lay.maps(loc) {
			d.residue(loc, a.value, false)
		}
	}
	return nil
}

// xmlScope decodes the lines of one scope from node: the root element, or the
// element of one item of a group. A field locator binds to the first sibling
// of each name; a group reads every child element named by the last name of
// its locator, under the first element matched by the names before it, one
// item per element, in order. The list is present when at least one item
// occurs. Unmapped content of an item is dropped.
func (d *decodeState) xmlScope(lay *layout, node *xnode) error {
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			n := node.find(f.loc.path)
			if n == nil {
				continue
			}
			if f.loc.kind == locAttr {
				if v, ok := n.attr(f.loc.name); ok && !f.sentinelText(v) {
					d.field(f, v)
				}
				continue
			}
			// The text is kept exactly; an element with no character data
			// has no text, so no sentinel is compared with it (ruling 1m of
			// 0.11).
			if text := n.text.String(); text != "" && !f.sentinelText(text) {
				d.field(f, text)
			}
		case ln.g != nil:
			g := ln.g
			names := g.loc.path
			parent := node.find(names[:len(names)-1])
			if parent == nil {
				continue
			}
			var items []*Item
			for _, c := range parent.children {
				if c.name != names[len(names)-1] {
					continue
				}
				it, err := d.item(func() error { return d.xmlScope(g.body, c) })
				if err != nil {
					return err
				}
				items = append(items, it)
			}
			if len(items) > 0 {
				d.rec.SetList(g.List, items)
			}
		}
	}
	return nil
}

func (n *xnode) child(name string) *xnode {
	for _, c := range n.children {
		if c.name == name {
			return c
		}
	}
	c := &xnode{name: name}
	n.children = append(n.children, c)
	return c
}

// setAttr writes an attribute at the position of the first write to it. The
// first value stays unless force is set.
func (n *xnode) setAttr(name, value string, force bool) {
	for i, a := range n.attrs {
		if a.name == name {
			if force {
				n.attrs[i].value = value
			}
			return
		}
	}
	n.attrs = append(n.attrs, xattr{name, value})
}

func place(root *xnode, l locator, value string, force bool) {
	n := root
	for _, seg := range l.path {
		n = n.child(seg)
	}
	switch l.kind {
	case locAttr:
		n.setAttr(l.name, value, force)
	case locText:
		if n.text.Len() == 0 || force {
			n.text.Reset()
			n.text.WriteString(value)
		}
	}
}

// encodeXML writes the layout's field, when and const lines in line order,
// under the layout's root element. Of two fields on one locator the earliest
// with a value wins; a when or const value is written over any field, at the
// position of the first line naming the locator.
func encodeXML(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	root := &xnode{name: lay.root}
	written := map[string]bool{}
	if err := encodeXMLScope(p, lay, rec, root, written); err != nil {
		return nil, err
	}
	for _, r := range residueFor(p, ent, written) {
		l, err := parseLocator(WireXML, r.Locator, true)
		if err != nil {
			return nil, &Error{Kind: ErrBadLocator, Format: p.Format, Locator: r.Locator, Detail: "residue: " + err.Error()}
		}
		place(root, l, r.Value, false)
	}
	var b strings.Builder
	if err := render(&b, root); err != nil {
		return nil, &Error{Kind: ErrTransformEncode, Format: p.Format, Detail: err.Error()}
	}
	return []byte(b.String()), nil
}

// encodeXMLScope writes the lines of one scope under root: the root element,
// or the element of one item. A group writes one element per item at its
// position in line order; an empty or absent list writes nothing.
func encodeXMLScope(p *Pack, lay *layout, rec *Item, root *xnode, written map[string]bool) error {
	weak := map[string]bool{} // the locators that hold a sentinel, which a value replaces (0.9 ruling 16)
	for i, ln := range lay.lines {
		// The elements of `element` lines are created at the first line that
		// addresses them or a path under them (0.18 ruling 13).
		for _, path := range lay.elemAt[i] {
			n := root
			for _, seg := range path {
				n = n.child(seg)
			}
		}
		if ln.el != nil {
			continue
		}
		if g := ln.g; g != nil {
			items := rec.Lists[g.List]
			if len(items) == 0 {
				continue
			}
			names := g.loc.path
			parent := root
			for _, seg := range names[:len(names)-1] {
				parent = parent.child(seg)
			}
			for _, it := range items {
				n := &xnode{name: names[len(names)-1]}
				parent.children = append(parent.children, n)
				if err := encodeXMLScope(p, g.body, it, n, map[string]bool{}); err != nil {
					return err
				}
			}
			continue
		}
		if w := ln.w; w != nil {
			if !w.present {
				place(root, w.loc, w.text, true)
				written[w.Locator] = true
			}
			continue
		}
		f := ln.f
		s, ok, err := encodeField(p, lay, f, rec)
		if err != nil {
			return err
		}
		if w := lay.forced[f.Locator]; w != nil {
			place(root, w.loc, w.text, true)
			written[f.Locator] = true
			continue
		}
		if !ok {
			// A sentinel is written where no line has written (0.9).
			if f.absent != nil && !f.suppressed(rec) && !written[f.Locator] {
				place(root, f.loc, f.absent.texts[0], false)
				written[f.Locator], weak[f.Locator] = true, true
			}
			continue
		}
		place(root, f.loc, s, weak[f.Locator])
		delete(weak, f.Locator)
		written[f.Locator] = true
	}
	return nil
}

// render writes an element (rulings 1a to 1e of 0.11). A character XML 1.0
// cannot hold, in an attribute value or in text, is transform-encode.
func render(b *strings.Builder, n *xnode) error {
	b.WriteByte('<')
	b.WriteString(n.name)
	for _, a := range n.attrs {
		b.WriteByte(' ')
		b.WriteString(a.name)
		b.WriteString(`="`)
		if err := escAttr(b, a.value); err != nil {
			return fmt.Errorf("attribute %s of <%s>: %v", a.name, n.name, err)
		}
		b.WriteByte('"')
	}
	if n.text.Len() == 0 && len(n.children) == 0 {
		b.WriteString("/>")
		return nil
	}
	b.WriteByte('>')
	if err := escText(b, n.text.String()); err != nil {
		return fmt.Errorf("text of <%s>: %v", n.name, err)
	}
	for _, c := range n.children {
		if err := render(b, c); err != nil {
			return err
		}
	}
	b.WriteString("</")
	b.WriteString(n.name)
	b.WriteByte('>')
	return nil
}

// writable refuses a character XML 1.0 cannot hold (ruling 1d of 0.11):
// below U+0020 other than tab, line feed and carriage return, U+FFFE and
// U+FFFF.
func writable(r rune) error {
	if (r < 0x20 && r != '\t' && r != '\n' && r != '\r') || r == 0xfffe || r == 0xffff {
		return fmt.Errorf("character U+%04X cannot be written in XML 1.0", r)
	}
	return nil
}

func escAttr(b *strings.Builder, s string) error {
	for _, r := range s {
		if err := writable(r); err != nil {
			return err
		}
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '"':
			b.WriteString("&quot;")
		case '\t':
			b.WriteString("&#9;")
		case '\n':
			b.WriteString("&#10;")
		case '\r':
			b.WriteString("&#13;")
		default:
			b.WriteRune(r)
		}
	}
	return nil
}

func escText(b *strings.Builder, s string) error {
	for _, r := range s {
		if err := writable(r); err != nil {
			return err
		}
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '\r':
			b.WriteString("&#13;")
		default:
			b.WriteRune(r)
		}
	}
	return nil
}
