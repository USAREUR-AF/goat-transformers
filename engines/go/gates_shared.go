package goatxf

// The declarations of gates.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"fmt"
	"strconv"
	"strings"
)

// Gate is one gate block of a fixed-layout bits pack (spec/engine-spec.md,
// "Version 0.17: gated fields on a fixed layout"): `if [!]<locator>
// <value>[,<value>…]` … `end`. The block holds when the bits at the locator
// equal one of the values (with `!`, none of them). Its lines stay in the
// scope's lines, in file order, each marked with its innermost block.
type Gate struct {
	Locator string // as written, without the `!`
	Line    int

	not      bool
	vals     []uint64
	loc      locator
	parent   *Gate  // the block this one is nested in, nil at the top of its scope
	group    *Group // the innermost group the block is in, nil outside a group
	defs     map[string]*Default
	defaults []*Default
}

// parseGate reads the arguments of a fixed-layout `if` line. Every fault is
// bad-directive: a presence name, a locator that is not <word>:<pos>:<len>
// with len 1 to 64, an empty list, a value that is not an unsigned decimal
// integer below 2^len, a value listed twice.
func parseGate(args []string, n int) (*Gate, error) {
	if len(args) != 2 {
		return nil, fmt.Errorf("a gate is `if [!]<word>:<pos>:<len> <value>[,<value>…]`, got %d argument(s)", len(args))
	}
	g := &Gate{Line: n}
	text := args[0]
	if strings.HasPrefix(text, "!") {
		g.not, text = true, text[1:]
	}
	g.Locator = text
	loc, err := parseLocator(WireBits, text, false)
	if err != nil {
		return nil, fmt.Errorf("gate locator %q: %v (a presence name is valid only in a sequential layout)", args[0], err)
	}
	if loc.blen > 64 {
		return nil, fmt.Errorf("a gate covers 1 to 64 bits, got %d", loc.blen)
	}
	g.loc = loc
	seen := map[uint64]bool{}
	for _, s := range strings.Split(args[1], ",") {
		if !isDigits(s) {
			return nil, fmt.Errorf("a gate value is an unsigned decimal integer, got %q in %q", s, args[1])
		}
		v, err := strconv.ParseUint(s, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("gate value %q does not fit 64 bits", s)
		}
		if loc.blen < 64 && v>>uint(loc.blen) != 0 {
			return nil, fmt.Errorf("gate value %d does not fit in %d bit(s)", v, loc.blen)
		}
		if seen[v] {
			return nil, fmt.Errorf("gate value %d listed twice", v)
		}
		seen[v] = true
		g.vals = append(g.vals, v)
	}
	return g, nil
}

// fieldDefault is the default that applies to a field: the innermost block's
// default of its key, else that of an enclosing block, else the scope's (0.17
// ruling 5).
func fieldDefault(lay *layout, f *Field) *Default {
	for g := f.gate; g != nil; g = g.parent {
		if d := g.defs[f.Key]; d != nil {
			return d
		}
	}
	return lay.defaults[f.Key]
}
