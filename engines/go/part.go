package goatxf

import (
	"fmt"
	"strconv"
	"strings"
)

// One text token split into coded fields (spec/engine-spec.md, "Version
// 0.64"): the `part` transform of field lines, `const … part`, the option
// `unlisted`, and the part group the lines of one locator form.

// partSpec is the parameters of `part:<sep>:<n>`.
type partSpec struct {
	sep string
	n   int
}

// isPartName reports whether a transform is `part`, parameters or not.
func isPartName(name string) bool {
	base, _, _ := strings.Cut(name, ":")
	return base == "part"
}

// parsePart reads `part:<sep>:<n>`: the separator as for `tokens` (0.18), the
// number from 0 to 255 without leading zeros.
func parsePart(name string) (*partSpec, error) {
	parts := strings.Split(name, ":")
	if len(parts) != 3 || parts[0] != "part" {
		return nil, fmt.Errorf("part is part:<sep>:<n>, got %q", name)
	}
	sep, err := parseTokenSep(parts[1])
	if err != nil {
		return nil, err
	}
	n, err := strconv.Atoi(parts[2])
	if !isDigits(parts[2]) || err != nil || n > 255 || (len(parts[2]) > 1 && parts[2][0] == '0') {
		return nil, fmt.Errorf("the number of a part is 0 to 255 without leading zeros, got %q", parts[2])
	}
	return &partSpec{sep: sep, n: n}, nil
}

// partOnWire reports whether a wire takes part lines.
func partOnWire(wire string) bool {
	switch wire {
	case WireXML, WireJSON, WireGeoJSON, WireText:
		return true
	}
	return false
}

// bindPart binds the transform `part` to a field on a wire that takes it. The
// token is read and written as `string` reads and writes it.
func bindPart(wire string, f *Field) error {
	if !partOnWire(wire) {
		return fmt.Errorf("transform %q is not valid on wire %s", f.Transform, wire)
	}
	ps, err := parsePart(f.Transform)
	if err != nil {
		return err
	}
	f.part = ps
	f.tf = transforms["string"]
	return nil
}

// partGroup is the lines of one scope with one locator, when a part line is
// among them.
type partGroup struct {
	sep    string
	first  line // the group's first line, where the token is written
	fields []*Field
	consts []*When
	whole  *Field // the `string` line of the whole token, nil for none
	max    int    // the highest part number a line names
	unique map[*Field]bool
}

// isFirst reports whether a line is the group's first.
func (g *partGroup) isFirst(ln line) bool {
	if ln.f != nil {
		return g.first.f == ln.f
	}
	return g.first.w == ln.w
}

// lineLocator is the locator of a field, when, const or group line.
func lineLocator(ln line) string {
	switch {
	case ln.f != nil:
		return ln.f.Locator
	case ln.w != nil:
		return ln.w.Locator
	case ln.g != nil:
		return ln.g.Locator
	}
	return ""
}

// lineLoc is the locator of a field or const line, as read.
func lineLoc(ln line) *locator {
	if ln.f != nil {
		return &ln.f.loc
	}
	return &ln.w.loc
}

func isPartLine(ln line) bool {
	return ln.f != nil && ln.f.part != nil || ln.w != nil && ln.w.part != nil
}

// partGroups finds the part groups of one scope; nil when it has none. fail
// reports a rule of Load errors that a line breaks.
func (p *Pack) partGroups(lines []line, fail func(at int, loc, format string, a ...any)) map[string]*partGroup {
	var groups map[string]*partGroup
	var order []string
	for _, ln := range lines {
		if !isPartLine(ln) {
			continue
		}
		if loc := lineLocator(ln); groups[loc] == nil {
			if groups == nil {
				groups = map[string]*partGroup{}
			}
			groups[loc] = &partGroup{unique: map[*Field]bool{}}
			order = append(order, loc)
		}
	}
	if groups == nil {
		return nil
	}
	count := map[string]int{}
	for _, ln := range lines {
		if ln.f != nil {
			count[ln.f.Key]++
		}
	}
	named := map[string]map[int]bool{}
	for _, ln := range lines {
		loc := lineLocator(ln)
		g := groups[loc]
		if g == nil {
			continue
		}
		at := 0
		var ps *partSpec
		switch {
		case ln.f != nil:
			at, ps = ln.f.Line, ln.f.part
		case ln.w != nil:
			at, ps = ln.w.Line, ln.w.part
		default:
			fail(ln.g.Line, loc, "a group stands on the locator of a part group")
			continue
		}
		if g.first.f == nil && g.first.w == nil {
			g.first = ln
		}
		if ps == nil {
			f := ln.f
			switch {
			case f == nil:
				fail(at, loc, "a when or const stands on the locator of a part group")
			case !p.isWholeLine(f):
				fail(at, loc, "field %s stands on the locator of a part group and is neither a part nor the whole line", f.Key)
			case g.whole != nil:
				fail(at, loc, "a second whole line of a part group (first on line %d)", g.whole.Line)
			default:
				g.whole = f
			}
			continue
		}
		if g.sep == "" {
			g.sep = ps.sep
		} else if g.sep != ps.sep {
			fail(at, loc, "a part group has one separator, got %q and %q", g.sep, ps.sep)
		}
		if named[loc] == nil {
			named[loc] = map[int]bool{}
		}
		if named[loc][ps.n] {
			fail(at, loc, "part %d is named twice in one part group", ps.n)
		}
		named[loc][ps.n] = true
		if ps.n > g.max {
			g.max = ps.n
		}
		if ln.w != nil {
			g.consts = append(g.consts, ln.w)
			continue
		}
		g.fields = append(g.fields, ln.f)
		g.unique[ln.f] = count[ln.f.Key] == 1
	}
	for _, loc := range order {
		g := groups[loc]
		at := 0
		if g.first.f != nil {
			at = g.first.f.Line
		} else if g.first.w != nil {
			at = g.first.w.Line
		}
		if len(g.fields) == 0 {
			fail(at, loc, "a part group has no part field")
		}
		for n := 0; n <= g.max; n++ {
			if !named[loc][n] {
				fail(at, loc, "no line of the part group names part %d", n)
				break
			}
		}
		for _, f := range g.fields {
			if g.whole != nil && f.Key == g.whole.Key {
				fail(f.Line, loc, "the whole line and a part line map one key, %s", f.Key)
			}
		}
	}
	return groups
}

// isWholeLine reports whether a field line can be the whole line of a part
// group: `string`, without options but, on text, `optional`.
func (p *Pack) isWholeLine(f *Field) bool {
	return f.Transform == "string" && f.Via == "" && !f.Swap && !f.Trim && (!f.Optional || p.Wire == WireText) &&
		f.Absent == nil && !f.WithLine && !f.StopLine && !f.Unlisted
}

// checkPartLines runs the checks of 0.64 that need no locator: `unlisted`
// and the wire of `const … part` (ruling 11: after the file).
func (p *Pack) checkPartLines(whens []*When, perr perrFunc) error {
	for _, f := range p.Fields {
		if f.Unlisted && (!isPartName(f.Transform) || f.Via == "") {
			return perr(ErrBadDirective, f.Line, f.Locator, "`unlisted` is valid only on a part line with `via`")
		}
	}
	for _, w := range whens {
		if w.part != nil && !partOnWire(p.Wire) {
			return perr(ErrBadDirective, w.Line, w.Locator, "const … part is not valid on wire %s", p.Wire)
		}
	}
	return nil
}

// checkParts runs the other checks of 0.64, once the locators are read.
func (p *Pack) checkParts(whens []*When, perr perrFunc) error {
	var first error
	fail := func(at int, loc, format string, a ...any) {
		if first == nil {
			first = perr(ErrBadDirective, at, loc, format, a...)
		}
	}
	place := func(at int, l *locator, ps *partSpec) {
		switch {
		case l.kind == locTCol || l.kind == locTPair:
			fail(at, l.raw, "part takes a whole field, not a column or a pair")
		case l.kind == locCoord:
			fail(at, l.raw, "part is not valid on a geometry locator")
		case p.Wire == WireText && !p.delimNone && ps.sep == string(rune(p.delim)):
			fail(at, l.raw, "the separator of a part is the delimiter %q", ps.sep)
		case p.Wire == WireText && p.nmea && ps.sep == "*":
			fail(at, l.raw, "the separator of a part is `*` under checksum nmea")
		}
	}
	any := false
	for _, f := range p.Fields {
		if f.part == nil {
			continue
		}
		any = true
		if f.Swap || f.Trim || f.Absent != nil || f.WithLine || f.StopLine || f.Optional && p.Wire != WireText {
			fail(f.Line, f.Locator, "a part line takes no field option but via, unlisted and, on text, optional")
		}
		place(f.Line, &f.loc, f.part)
	}
	for _, w := range whens {
		if w.part == nil {
			continue
		}
		any = true
		place(w.Line, &w.loc, w.part)
		if w.text == "" || strings.Contains(w.text, w.part.sep) {
			fail(w.Line, w.Locator, "the text of a const part is not empty and does not hold its separator, got %q", w.text)
		}
	}
	if !any {
		return nil
	}
	if p.HasKinds() {
		for _, k := range p.Kinds {
			p.partGroups(append(append([]line(nil), p.common...), k.lines...), fail)
		}
	} else {
		p.partGroups(p.common, fail)
	}
	for _, g := range p.Groups {
		p.partGroups(g.lines, fail)
	}
	return first
}

// --- decode ---

// hardFail records a failure that no other line forgives.
func (d *decodeState) hardFail(loc, detail string) {
	d.failed = append(d.failed, &Error{Kind: ErrTransformDecode, Format: d.pack.Format, Locator: loc, Detail: detail})
	d.failedKey = append(d.failedKey, "")
	d.failedIn = append(d.failedIn, d.rec)
	d.failedHard = append(d.failedHard, true)
}

// part decodes one part line, a field or a const, from the token of its
// place. readable is false when `string` cannot read the place: each line of
// the group then fails (ruling 4).
func (d *decodeState) part(ln line, tok string, readable bool) {
	if w := ln.w; w != nil {
		if !readable {
			d.hardFail(w.Locator, "const part: the place holds no text")
			return
		}
		if err := checkConstPart(w, strings.Split(tok, w.part.sep)); err != nil {
			d.hardFail(w.Locator, err.Error())
		}
		return
	}
	f := ln.f
	if !readable {
		d.fail(f, "the place holds no text")
		return
	}
	parts := strings.Split(tok, f.part.sep)
	if f.part.n >= len(parts) {
		d.fail(f, fmt.Sprintf("the token %q has no part %d", tok, f.part.n))
		return
	}
	s := parts[f.part.n]
	if f.Unlisted && !hasKey(f.viaDec, s) {
		return
	}
	d.store(f, Value{Kind: KindString, S: s})
}

func checkConstPart(w *When, parts []string) error {
	if w.part.n >= len(parts) {
		return fmt.Errorf("const part %d is missing", w.part.n)
	}
	if parts[w.part.n] != w.text {
		return fmt.Errorf("part %d is %q, the const is %q", w.part.n, parts[w.part.n], w.text)
	}
	return nil
}

// --- encode ---

// mapType passes the text of the key `type` through the typemap.
func mapType(key string, v Value, m map[string]string) Value {
	if key == "type" && v.Kind == KindString {
		if t, ok := m[v.S]; ok {
			v.S = t
		}
	}
	return v
}

// token is the text an encode writes for a part group; ok is false when it
// writes nothing.
func (g *partGroup) token(p *Pack, lay *layout, rec *Item) (string, bool, error) {
	wholeText := func(v Value) (string, bool, error) {
		s, err := encString(mapType(g.whole.Key, v, p.cotToNative))
		if err != nil {
			return "", false, encodeErr(p, g.whole, err)
		}
		if err := g.check(p, rec, s); err != nil {
			return "", false, err
		}
		return s, true, nil
	}
	if g.whole != nil {
		if v, held := rec.Fields[g.whole.Key]; held {
			return wholeText(v)
		}
	}
	anyHeld, all := false, true
	for _, f := range g.fields {
		if _, held := rec.Fields[f.Key]; held {
			anyHeld = true
		} else if fieldDefault(lay, f) == nil {
			all = false
		}
	}
	if anyHeld || all {
		parts := make([]string, g.max+1)
		for _, w := range g.consts {
			parts[w.part.n] = w.text
		}
		for _, f := range g.fields {
			v, ok, err := fieldValue(p, lay, f, rec)
			if err != nil {
				return "", false, err
			}
			if !ok {
				return "", false, encodeErr(p, f, fmt.Errorf("another part of the token has a value and this one has none"))
			}
			s, err := encString(v)
			if err != nil {
				return "", false, encodeErr(p, f, err)
			}
			if strings.Contains(s, g.sep) {
				return "", false, encodeErr(p, f, fmt.Errorf("the text %q holds the separator %q", s, g.sep))
			}
			parts[f.part.n] = s
		}
		return strings.Join(parts, g.sep), true, nil
	}
	if g.whole != nil {
		if d := fieldDefault(lay, g.whole); d != nil {
			return wholeText(d.val)
		}
	}
	return "", false, nil
}

// check refuses a whole text that does not fit the group: a const part that
// is not there and equal, and a part that does not decode to what the entity
// holds (Encode, step 1). A key with another field line in the scope is not
// checked (rulings 2, 18 and 25).
func (g *partGroup) check(p *Pack, rec *Item, tok string) error {
	parts := strings.Split(tok, g.sep)
	for _, w := range g.consts {
		if err := checkConstPart(w, parts); err != nil {
			return &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: w.Locator, Detail: fmt.Sprintf("the token %q: %v", tok, err)}
		}
	}
	for _, f := range g.fields {
		if !g.unique[f] {
			continue
		}
		if f.part.n >= len(parts) {
			return encodeErr(p, f, fmt.Errorf("the token %q has no part %d", tok, f.part.n))
		}
		s := parts[f.part.n]
		held, has := rec.Fields[f.Key]
		if f.Unlisted && !hasKey(f.viaDec, s) {
			if has {
				return encodeErr(p, f, fmt.Errorf("the part %q of the token is in no table entry and the entity holds the key", s))
			}
			continue
		}
		v := Value{Kind: KindString, S: s}
		if f.table != nil {
			mv, err := f.viaDecode(v)
			if err != nil {
				return encodeErr(p, f, err)
			}
			v = mv
		}
		v = mapType(f.Key, v, p.nativeToCot)
		if has && !sameValue(v, held) {
			return encodeErr(p, f, fmt.Errorf("the token %q gives %q and the entity holds %q", tok, v.String(), held.String()))
		}
	}
	return nil
}

// sameValue compares two values of one key, numbers as numbers (ruling 22).
func sameValue(a, b Value) bool {
	switch {
	case a.Kind != b.Kind:
		return a.String() == b.String()
	case a.Kind == KindInt:
		return a.I == b.I
	case a.Kind == KindFloat:
		return a.F == b.F
	}
	return a.S == b.S
}
