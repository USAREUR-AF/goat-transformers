package goatxf

// The declarations of jsonwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"fmt"
	"strings"
)

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
