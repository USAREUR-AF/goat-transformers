package goatxf

import (
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
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

func qname(n xml.Name) string {
	if n.Space != "" {
		return n.Space + ":" + n.Local
	}
	return n.Local
}

func isBlank(b []byte) bool { return len(bytes.TrimSpace(b)) == 0 }

// xmlSurrogateRef returns the first numeric character reference of b that
// names a surrogate code point (U+D800 to U+DFFF), "" when there is none.
// The decoder refuses every other character XML 1.0 does not allow, and
// would read this one as U+FFFD. Comments, processing instructions and CDATA
// sections hold no references and are skipped.
func xmlSurrogateRef(b []byte) string {
	skip := func(i int, open, end string) (int, bool) {
		if !bytes.HasPrefix(b[i:], []byte(open)) {
			return i, false
		}
		j := bytes.Index(b[i+len(open):], []byte(end))
		if j < 0 {
			return len(b), true
		}
		return i + len(open) + j + len(end), true
	}
	for i := 0; i < len(b); {
		if b[i] == '<' {
			if j, ok := skip(i, "<!--", "-->"); ok {
				i = j
				continue
			}
			if j, ok := skip(i, "<![CDATA[", "]]>"); ok {
				i = j
				continue
			}
			if j, ok := skip(i, "<?", "?>"); ok {
				i = j
				continue
			}
		}
		if b[i] != '&' || !bytes.HasPrefix(b[i:], []byte("&#")) {
			i++
			continue
		}
		// At most the digits of U+10FFFF with leading zeros matter; a longer
		// run is read until its `;` or a byte that is not a digit.
		j, base := i+2, 10
		if j < len(b) && b[j] == 'x' {
			j, base = j+1, 16
		}
		var n uint64
		k := j
		for ; k < len(b); k++ {
			c, d := b[k], uint64(99)
			switch {
			case c >= '0' && c <= '9':
				d = uint64(c - '0')
			case base == 16 && c >= 'a' && c <= 'f':
				d = uint64(c-'a') + 10
			case base == 16 && c >= 'A' && c <= 'F':
				d = uint64(c-'A') + 10
			}
			if d == 99 {
				break
			}
			if n = n*uint64(base) + d; n > 0x10ffff {
				n = 0x110000
			}
		}
		if k > j && k < len(b) && b[k] == ';' && n >= 0xd800 && n <= 0xdfff {
			return string(b[i : k+1])
		}
		i = k
	}
	return ""
}

// parseXML reads one document. It tolerates a prolog, comments and
// whitespace outside the root, and checks that end tags match.
func parseXML(format string, b []byte) (*xnode, error) {
	bad := func(detail string) error { return &Error{Kind: ErrMalformedWire, Format: format, Detail: detail} }
	if ref := xmlSurrogateRef(b); ref != "" {
		return nil, bad("character reference " + ref + " names no character XML 1.0 allows")
	}
	// Strict: the five predefined entities and numeric character references
	// only; a reference to any other entity is an error.
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
			if len(stack) >= maxNesting {
				return nil, bad(fmt.Sprintf("elements are nested deeper than %d levels", maxNesting))
			}
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
		case xml.Directive:
			// A document type declaration anywhere is refused, so no entity
			// is ever declared (0.8 ruling 40).
			return nil, bad("the input holds a document type or markup declaration")
		}
	}
	if len(stack) != 0 {
		return nil, bad("unclosed element <" + stack[len(stack)-1].name + ">")
	}
	// An input with no element is not a document (0.8 ruling 37).
	if root == nil {
		return nil, bad("the input holds no element")
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
