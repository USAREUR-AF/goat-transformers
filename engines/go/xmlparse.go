//go:build !goat_wires || goat_wire_xml

package goatxf

import (
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"
)

// The reader of the xml wire (ruling 1 of 0.11, with rulings 35, 37 and 40
// of 0.8). It reads one document: an optional byte order mark, then a prolog
// of whitespace, comments and processing instructions (an XML declaration
// among them), one root element, and whitespace, comments and processing
// instructions after it. A document type declaration anywhere is refused, so
// no entity is ever declared.

// xmlReader holds the document being read, its line ends already read as
// line feeds (ruling 1h).
type xmlReader struct {
	s   string
	i   int
	err string
}

// xmlChar reports whether XML 1.0 can hold the character r.
func xmlChar(r rune) bool {
	switch {
	case r == '\t' || r == '\n' || r == '\r':
		return true
	case r < 0x20:
		return false
	case r >= 0xd800 && r <= 0xdfff:
		return false
	case r == 0xfffe || r == 0xffff:
		return false
	}
	return r <= 0x10ffff
}

func isNameStart(r rune) bool {
	return r == '_' || r == ':' || unicode.IsLetter(r) || (r >= 0xc0 && r != 0xd7 && r != 0xf7 && !unicode.IsSpace(r) && !unicode.IsPunct(r) && !unicode.IsSymbol(r))
}

func isNameChar(r rune) bool {
	return isNameStart(r) || r == '-' || r == '.' || r == 0xb7 || unicode.IsDigit(r) || unicode.IsMark(r)
}

func isXMLSpace(c byte) bool { return c == ' ' || c == '\t' || c == '\n' || c == '\r' }

func (x *xmlReader) fail(format string, a ...any) bool {
	if x.err == "" {
		x.err = fmt.Sprintf(format, a...)
	}
	return false
}

func (x *xmlReader) has(prefix string) bool { return strings.HasPrefix(x.s[x.i:], prefix) }

func (x *xmlReader) skipSpace() {
	for x.i < len(x.s) && isXMLSpace(x.s[x.i]) {
		x.i++
	}
}

// name reads an element or attribute name; "" when none stands here.
func (x *xmlReader) name() string {
	start := x.i
	for x.i < len(x.s) {
		r, n := utf8.DecodeRuneInString(x.s[x.i:])
		if x.i == start && !isNameStart(r) || x.i > start && !isNameChar(r) {
			break
		}
		x.i += n
	}
	return x.s[start:x.i]
}

// skipUntil moves past the next end; false when there is none.
func (x *xmlReader) skipUntil(end string) bool {
	j := strings.Index(x.s[x.i:], end)
	if j < 0 {
		x.i = len(x.s)
		return false
	}
	x.i += j + len(end)
	return true
}

// misc reads a comment or a processing instruction at '<' (ruling 1l); a
// document type declaration is refused. It reports whether one was read.
func (x *xmlReader) misc() (bool, bool) {
	switch {
	case x.has("<!--"):
		x.i += 4
		if !x.skipUntil("-->") {
			return true, x.fail("a comment has no end")
		}
		return true, true
	case x.has("<?"):
		x.i += 2
		if !x.skipUntil("?>") {
			return true, x.fail("a processing instruction has no end")
		}
		return true, true
	case x.has("<!DOCTYPE") || (x.has("<!") && !x.has("<![CDATA[")):
		return true, x.fail("the input holds a document type or markup declaration")
	}
	return false, true
}

// reference reads one reference at '&' and appends what it gives (ruling
// 1j): the five predefined entities and numeric character references to a
// character XML 1.0 holds. Every other `&` is refused.
func (x *xmlReader) reference(b *strings.Builder) bool {
	j := strings.IndexByte(x.s[x.i:], ';')
	if j < 0 {
		return x.fail("a `&` with no `;`")
	}
	body := x.s[x.i+1 : x.i+j]
	switch body {
	case "amp":
		b.WriteByte('&')
	case "lt":
		b.WriteByte('<')
	case "gt":
		b.WriteByte('>')
	case "quot":
		b.WriteByte('"')
	case "apos":
		b.WriteByte('\'')
	default:
		if !strings.HasPrefix(body, "#") {
			return x.fail("reference &%s; names no predefined entity", body)
		}
		digits, base := body[1:], 10
		if strings.HasPrefix(digits, "x") {
			digits, base = digits[1:], 16
		}
		if digits == "" {
			return x.fail("character reference &%s; has no digits", body)
		}
		var n rune
		for k := 0; k < len(digits); k++ {
			c, d := digits[k], rune(-1)
			switch {
			case c >= '0' && c <= '9':
				d = rune(c - '0')
			case base == 16 && c >= 'a' && c <= 'f':
				d = rune(c-'a') + 10
			case base == 16 && c >= 'A' && c <= 'F':
				d = rune(c-'A') + 10
			}
			if d < 0 {
				return x.fail("character reference &%s; is not a number", body)
			}
			if n = n*rune(base) + d; n > 0x10ffff {
				n = 0x110000
			}
		}
		if !xmlChar(n) {
			return x.fail("character reference &%s; names no character XML 1.0 allows", body)
		}
		b.WriteRune(n)
	}
	x.i += j + 1
	return true
}

// attrValue reads a quoted attribute value (ruling 1i): between double
// quotes or apostrophes; a literal tab or line feed reads as a space, one
// written as a reference is kept; `<` is refused.
func (x *xmlReader) attrValue() (string, bool) {
	if x.i >= len(x.s) || (x.s[x.i] != '"' && x.s[x.i] != '\'') {
		return "", x.fail("an attribute value stands between quotes")
	}
	q := x.s[x.i]
	x.i++
	var b strings.Builder
	for x.i < len(x.s) {
		c := x.s[x.i]
		switch {
		case c == q:
			x.i++
			return b.String(), true
		case c == '<':
			return "", x.fail("`<` inside an attribute value")
		case c == '&':
			if !x.reference(&b) {
				return "", false
			}
		case c == '\t' || c == '\n':
			b.WriteByte(' ')
			x.i++
		default:
			b.WriteByte(c)
			x.i++
		}
	}
	return "", x.fail("an attribute value has no closing quote")
}

// element reads one element at '<' and everything inside it.
func (x *xmlReader) element(depth int) (*xnode, bool) {
	if depth > maxNesting {
		return nil, x.fail("elements are nested deeper than %d levels", maxNesting)
	}
	x.i++ // '<'
	n := &xnode{name: x.name()}
	if n.name == "" {
		return nil, x.fail("`<` is not followed by an element name")
	}
	for {
		hadSpace := x.i < len(x.s) && isXMLSpace(x.s[x.i])
		x.skipSpace()
		if x.i >= len(x.s) {
			return nil, x.fail("the start tag of <%s> has no end", n.name)
		}
		if x.has("/>") {
			x.i += 2
			return n, true
		}
		if x.s[x.i] == '>' {
			x.i++
			break
		}
		if !hadSpace {
			return nil, x.fail("attributes of <%s> are not separated by whitespace", n.name)
		}
		an := x.name()
		if an == "" {
			return nil, x.fail("the start tag of <%s> holds text that is not an attribute", n.name)
		}
		x.skipSpace()
		if x.i >= len(x.s) || x.s[x.i] != '=' {
			return nil, x.fail("attribute %s of <%s> has no value", an, n.name)
		}
		x.i++
		x.skipSpace()
		v, ok := x.attrValue()
		if !ok {
			return nil, false
		}
		// The same attribute name twice on one element (ruling 1o).
		for _, a := range n.attrs {
			if a.name == an {
				return nil, x.fail("attribute %s appears twice on <%s>", an, n.name)
			}
		}
		n.attrs = append(n.attrs, xattr{an, v})
	}
	// Content: character data, references, CDATA sections, comments,
	// processing instructions and child elements, up to the end tag.
	for x.i < len(x.s) {
		c := x.s[x.i]
		switch {
		case c == '&':
			if !x.reference(&n.text) {
				return nil, false
			}
		case c != '<':
			n.text.WriteByte(c)
			x.i++
		case x.has("</"):
			x.i += 2
			end := x.name()
			x.skipSpace()
			if end != n.name || x.i >= len(x.s) || x.s[x.i] != '>' {
				return nil, x.fail("unexpected end tag </%s> in <%s>", end, n.name)
			}
			x.i++
			return n, true
		case x.has("<![CDATA["):
			// Character data exactly as written (ruling 1k).
			x.i += 9
			j := strings.Index(x.s[x.i:], "]]>")
			if j < 0 {
				return nil, x.fail("a CDATA section has no end")
			}
			n.text.WriteString(x.s[x.i : x.i+j])
			x.i += j + 3
		default:
			if read, ok := x.misc(); read {
				if !ok {
					return nil, false
				}
				continue
			}
			child, ok := x.element(depth + 1)
			if !ok {
				return nil, false
			}
			n.children = append(n.children, child)
		}
	}
	return nil, x.fail("unclosed element <%s>", n.name)
}

// parseXML reads one document.
func parseXML(format string, b []byte) (*xnode, error) {
	bad := func(detail string) error { return &Error{Kind: ErrMalformedWire, Format: format, Detail: detail} }
	// One byte order mark at the very start is skipped (ruling 1g).
	b = []byte(strings.TrimPrefix(string(b), "\xef\xbb\xbf"))
	if !utf8.Valid(b) {
		return nil, bad("the input is not UTF-8")
	}
	// Line ends: CR LF and a CR alone read as LF, before anything else
	// (ruling 1h).
	s := strings.ReplaceAll(string(b), "\r\n", "\n")
	s = strings.ReplaceAll(s, "\r", "\n")
	for _, r := range s {
		if !xmlChar(r) {
			return nil, bad(fmt.Sprintf("character U+%04X is not one XML 1.0 allows", r))
		}
	}
	x := &xmlReader{s: s}
	var root *xnode
	for {
		x.skipSpace()
		if x.i >= len(x.s) {
			break
		}
		if x.s[x.i] != '<' {
			return nil, bad("text outside the root element")
		}
		read, ok := x.misc()
		if !ok {
			return nil, bad(x.err)
		}
		if read {
			continue
		}
		if x.has("<![CDATA[") {
			return nil, bad("a CDATA section outside the root element")
		}
		if root != nil {
			return nil, bad("more than one root element")
		}
		n, ok := x.element(1)
		if !ok {
			return nil, bad(x.err)
		}
		root = n
	}
	// An input with no element is not a document (0.8 ruling 37).
	if root == nil {
		return nil, bad("the input holds no element")
	}
	return root, nil
}
