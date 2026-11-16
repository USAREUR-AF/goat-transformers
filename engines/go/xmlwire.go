package goatxf

import (
	"bytes"
	"encoding/xml"
	"errors"
	"io"
	"strings"
)

type xattr struct{ name, value string }

type xnode struct {
	name     string
	attrs    []xattr
	text     strings.Builder
	children []*xnode
}

func qname(n xml.Name) string {
	if n.Space != "" {
		return n.Space + ":" + n.Local
	}
	return n.Local
}

func isBlank(b []byte) bool { return len(bytes.TrimSpace(b)) == 0 }

// parseXML reads one document. It tolerates a prolog, comments and
// whitespace outside the root, and checks that end tags match.
func parseXML(format string, b []byte) (*xnode, error) {
	bad := func(detail string) error { return &Error{Kind: ErrMalformedWire, Format: format, Detail: detail} }
	dec := xml.NewDecoder(bytes.NewReader(b))
	dec.Strict = true
	var root *xnode
	var stack []*xnode
	for {
		tok, err := dec.RawToken()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, bad(err.Error())
		}
		switch t := tok.(type) {
		case xml.StartElement:
			n := &xnode{name: qname(t.Name)}
			for _, a := range t.Attr {
				n.attrs = append(n.attrs, xattr{qname(a.Name), a.Value})
			}
			if len(stack) == 0 {
				if root != nil {
					return nil, bad("more than one root element")
				}
				root = n
			} else {
				top := stack[len(stack)-1]
				top.children = append(top.children, n)
			}
			stack = append(stack, n)
		case xml.EndElement:
			if len(stack) == 0 || stack[len(stack)-1].name != qname(t.Name) {
				return nil, bad("unexpected end tag </" + qname(t.Name) + ">")
			}
			stack = stack[:len(stack)-1]
		case xml.CharData:
			if len(stack) == 0 {
				if !isBlank(t) {
					return nil, bad("text outside the root element")
				}
				continue
			}
			stack[len(stack)-1].text.Write(t)
		}
	}
	if len(stack) != 0 {
		return nil, bad("unclosed element <" + stack[len(stack)-1].name + ">")
	}
	return root, nil
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
	if root == nil {
		return &Error{Kind: ErrMissingRoot, Format: p.Format, Detail: "no root element"}
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
		return w.present || n.text.String() == w.text
	})
	if err != nil {
		return err
	}
	d.xmlScope(lay, root)
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
func (d *decodeState) xmlScope(lay *layout, node *xnode) {
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			n := node.find(f.loc.path)
			if n == nil {
				continue
			}
			if f.loc.kind == locAttr {
				if v, ok := n.attr(f.loc.name); ok {
					d.field(f, v)
				}
				continue
			}
			if text := n.text.String(); strings.TrimSpace(text) != "" {
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
				it, _ := d.item(func() error { d.xmlScope(g.body, c); return nil })
				items = append(items, it)
			}
			if len(items) > 0 {
				d.rec.SetList(g.List, items)
			}
		}
	}
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
	render(&b, root)
	return []byte(b.String()), nil
}

// encodeXMLScope writes the lines of one scope under root: the root element,
// or the element of one item. A group writes one element per item at its
// position in line order; an empty or absent list writes nothing.
func encodeXMLScope(p *Pack, lay *layout, rec *Item, root *xnode, written map[string]bool) error {
	for _, ln := range lay.lines {
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
			continue
		}
		place(root, f.loc, s, false)
		written[f.Locator] = true
	}
	return nil
}

func render(b *strings.Builder, n *xnode) {
	b.WriteByte('<')
	b.WriteString(n.name)
	for _, a := range n.attrs {
		b.WriteByte(' ')
		b.WriteString(a.name)
		b.WriteString(`="`)
		escAttr(b, a.value)
		b.WriteByte('"')
	}
	if n.text.Len() == 0 && len(n.children) == 0 {
		b.WriteString("/>")
		return
	}
	b.WriteByte('>')
	escText(b, n.text.String())
	for _, c := range n.children {
		render(b, c)
	}
	b.WriteString("</")
	b.WriteString(n.name)
	b.WriteByte('>')
}

func escAttr(b *strings.Builder, s string) {
	for _, r := range s {
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
			b.WriteString("&#x9;")
		case '\n':
			b.WriteString("&#xA;")
		case '\r':
			b.WriteString("&#xD;")
		default:
			b.WriteRune(r)
		}
	}
}

func escText(b *strings.Builder, s string) {
	for _, r := range s {
		switch r {
		case '&':
			b.WriteString("&amp;")
		case '<':
			b.WriteString("&lt;")
		case '>':
			b.WriteString("&gt;")
		case '\r':
			b.WriteString("&#xD;")
		default:
			b.WriteRune(r)
		}
	}
}
