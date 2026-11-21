package goatxf

// The declarations of text.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// textDirective reads one `delimiter`, `start` or `checksum` line as the file
// is read: each appears at most once, before the first `kind`, with a value
// of its own shape. Whether the wire is text is checked after the file is
// read (0.10 ruling 10).
func (p *Pack) textDirective(kw, val string, line int) error {
	if p.textSeen == nil {
		p.textSeen = map[string]int{}
	}
	if prev, dup := p.textSeen[kw]; dup {
		return fmt.Errorf("%s repeated (first on line %d)", kw, prev)
	}
	if prev, dup := p.tlv.lines[kw]; dup {
		return fmt.Errorf("%s repeated (first on line %d)", kw, prev)
	}
	p.textSeen[kw] = line
	if len(p.Kinds) > 0 {
		return fmt.Errorf("%s must stand before the first kind line", kw)
	}
	switch kw {
	case "delimiter":
		switch {
		case val == "none":
			p.delimNone = true
		case len(val) == 1 && val[0] >= 0x21 && val[0] <= 0x7E && val[0] != '"':
			p.delim = val[0]
		default:
			return fmt.Errorf("delimiter is one character from 0x21 to 0x7E other than '\"', or none; got %q", val)
		}
	case "start":
		if val == "" {
			return fmt.Errorf("start needs one or more characters")
		}
		for i := 0; i < len(val); i++ {
			if val[i] < 0x21 || val[i] > 0x7E {
				return fmt.Errorf("start holds characters from 0x21 to 0x7E only, got %q", val)
			}
		}
		p.start = val
	case "checksum":
		switch val {
		case "none":
		case "nmea":
			p.nmea = true
		default:
			return fmt.Errorf("checksum is none or nmea, got %q", val)
		}
	}
	return nil
}

// checkTextDirectives runs after the file is read: the text directives on
// another wire, the start text holding the delimiter, and `delimiter "*"`
// with `checksum nmea`. It returns the line at fault.
func (p *Pack) checkTextDirectives() (int, error) {
	if p.Wire != WireText {
		for _, kw := range []string{"delimiter", "start", "checksum"} {
			if ln, has := p.textSeen[kw]; has {
				return ln, fmt.Errorf("%s is valid only on wire text", kw)
			}
		}
		return 0, nil
	}
	if p.textSeen["delimiter"] == 0 {
		p.delim = ','
	}
	if !p.delimNone && strings.IndexByte(p.start, p.delim) >= 0 {
		return p.textSeen["start"], fmt.Errorf("the start text %q holds the delimiter %q", p.start, string(p.delim))
	}
	if p.nmea && !p.delimNone && p.delim == '*' {
		return p.textSeen["delimiter"], fmt.Errorf("delimiter \"*\" cannot be used with checksum nmea")
	}
	return 0, nil
}

// parseTextIndex reads a field index or a character position: decimal digits,
// at most nine of them.
func parseTextIndex(s string) (int, bool) {
	if !isDigits(s) || len(s) > 9 {
		return 0, false
	}
	n, err := strconv.Atoi(s)
	return n, err == nil
}

// parseTextLocator reads `<i>`, `<i>:<from>:<len>` or `<i>+<j>`.
func parseTextLocator(s string) (locator, error) {
	l := locator{raw: s}
	bad := func() (locator, error) {
		return l, fmt.Errorf("a text locator is <i>, <i>:<from>:<len> or <i>+<j>, got %q", s)
	}
	if a, b, ok := strings.Cut(s, "+"); ok {
		i, ok1 := parseTextIndex(a)
		j, ok2 := parseTextIndex(b)
		if !ok1 || !ok2 {
			return bad()
		}
		l.kind, l.ti, l.tj = locTPair, i, j
		return l, nil
	}
	if strings.Contains(s, ":") {
		parts := strings.Split(s, ":")
		if len(parts) != 3 {
			return bad()
		}
		i, ok1 := parseTextIndex(parts[0])
		from, ok2 := parseTextIndex(parts[1])
		n, ok3 := parseTextIndex(parts[2])
		if !ok1 || !ok2 || !ok3 || n < 1 {
			return bad()
		}
		l.kind, l.ti, l.from, l.clen = locTCol, i, from, n
		return l, nil
	}
	i, ok := parseTextIndex(s)
	if !ok {
		return bad()
	}
	l.kind, l.ti = locTField, i
	return l, nil
}

// indexes are the fields a text locator names.
func (l *locator) indexes() []int {
	if l.kind == locTPair {
		return []int{l.ti, l.tj}
	}
	return []int{l.ti}
}

const (
	ttString = iota + 1
	ttInt
	ttFloat
	ttISO
	ttIntW
	ttDec
	ttDM
	ttHMS
	ttHMSDMY
)

// textTf is a transform of the text wire. A pair transform reads and writes
// two texts.
type textTf struct {
	name    string
	kind    int
	w, f, d int
	pl, nl  byte // dm: the letters of the positive and negative halves
	numeric bool // int, int:<w>, float, dec: columns trim leading spaces and pad with 0
	pair    bool // dm, hms_dmy
}

// isTextOnlyTransform reports a transform valid only on the text wire, by its
// name: `int:<…>`, and `dec`, `dm`, `hms`, `hms_dmy` with or without
// parameters.
func isTextOnlyTransform(name string) bool {
	base, _, hasParam := strings.Cut(name, ":")
	switch base {
	case "dec", "dm", "hms", "hms_dmy":
		return true
	case "int":
		return hasParam
	}
	return false
}

// textTransformYields is the model type of a transform of the text wire.
func textTransformYields(name string) (Kind, bool) {
	if !isTextOnlyTransform(name) {
		return 0, false
	}
	switch base, _, _ := strings.Cut(name, ":"); base {
	case "int", "hms_dmy":
		return KindInt, true
	}
	return KindFloat, true
}

// resolveTextTransform reads the transform named on a field line of a text
// pack. A parameter out of range, and a transform of another wire, are
// bad-directive; a name no wire has is unknown-transform.
func resolveTextTransform(name string) (*textTf, ErrorKind, error) {
	switch name {
	case "string":
		return &textTf{name: name, kind: ttString}, "", nil
	case "int":
		return &textTf{name: name, kind: ttInt, numeric: true}, "", nil
	case "float":
		return &textTf{name: name, kind: ttFloat, numeric: true}, "", nil
	case "iso8601_ms":
		return &textTf{name: name, kind: ttISO}, "", nil
	}
	// iso8601_short is valid on xml, json and geojson only (0.18).
	if name == "bool" || name == "iso8601_short" || name == "iso8601_si" || isBitsTransformName(name) || isPBTransformName(name) || isTLVOnlyTransform(name) || v015Base(name) != "" {
		return nil, ErrBadDirective, fmt.Errorf("transform %q is not valid on wire text", name)
	}
	if !isTextOnlyTransform(name) {
		return nil, ErrUnknownTransform, fmt.Errorf("unknown transform %q (text: string, int, float, iso8601_ms, int:<w>, dec:<f>[:<w>], dm:<d>:<f>:<PN>, hms:<f>, hms_dmy:<f>)", name)
	}
	parts := strings.Split(name, ":")
	params := parts[1:]
	num := func(s string, lo, hi int) (int, bool) {
		n, ok := parseTextIndex(s)
		return n, ok && n >= lo && n <= hi
	}
	badParam := func() (*textTf, ErrorKind, error) {
		return nil, ErrBadDirective, fmt.Errorf("transform %q: parameters out of range or missing (w 1-20; f 0-9 for dec and dm, 0-3 for hms and hms_dmy; d 1-3; P and N two different letters A-Z)", name)
	}
	t := &textTf{name: name}
	var ok bool
	switch parts[0] {
	case "int":
		t.kind, t.numeric = ttIntW, true
		if len(params) != 1 {
			return badParam()
		}
		if t.w, ok = num(params[0], 1, 20); !ok {
			return badParam()
		}
	case "dec":
		t.kind, t.numeric = ttDec, true
		if len(params) != 1 && len(params) != 2 {
			return badParam()
		}
		if t.f, ok = num(params[0], 0, 9); !ok {
			return badParam()
		}
		if len(params) == 2 {
			if t.w, ok = num(params[1], 1, 20); !ok {
				return badParam()
			}
		}
	case "dm":
		t.kind, t.pair = ttDM, true
		if len(params) != 3 {
			return badParam()
		}
		if t.d, ok = num(params[0], 1, 3); !ok {
			return badParam()
		}
		if t.f, ok = num(params[1], 0, 9); !ok {
			return badParam()
		}
		pn := params[2]
		if len(pn) != 2 || pn[0] < 'A' || pn[0] > 'Z' || pn[1] < 'A' || pn[1] > 'Z' || pn[0] == pn[1] {
			return badParam()
		}
		t.pl, t.nl = pn[0], pn[1]
	case "hms", "hms_dmy":
		t.kind = ttHMS
		if parts[0] == "hms_dmy" {
			t.kind, t.pair = ttHMSDMY, true
		}
		if len(params) != 1 {
			return badParam()
		}
		if t.f, ok = num(params[0], 0, 3); !ok {
			return badParam()
		}
	}
	return t, "", nil
}

func daysIn(year, month int) int {
	return time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
}

type perrFunc func(kind ErrorKind, line int, loc, format string, a ...any) error

// resolveText reads the locators and transforms of a text pack and runs the
// checks of 0.10 that need the whole file (ruling 2).
func (p *Pack) resolveText(whens []*When, perr perrFunc, note func(error) error) error {
	// checkIdx refuses a locator outside its item, or a field other than 0
	// under `delimiter none`.
	checkIdx := func(l *locator, g *Group) error {
		for _, i := range l.indexes() {
			if g != nil && i >= g.titem {
				return fmt.Errorf("field %d is beyond the %d fields of an item of group %s", i, g.titem, g.List)
			}
			if p.delimNone && i != 0 {
				return fmt.Errorf("under delimiter none the record is field 0, got field %d", i)
			}
		}
		return nil
	}
	for _, g := range p.Groups {
		switch {
		case g.parent != nil:
			return perr(ErrBadDirective, g.Line, g.Locator, "a group of a text pack cannot be nested")
		case g.hasCount:
			return perr(ErrBadDirective, g.Line, g.Locator, "group: `count` is not valid on wire text")
		case !g.hasItem:
			return perr(ErrBadDirective, g.Line, g.Locator, "a text group is `group <list> <i> item <n>`")
		case p.delimNone:
			return perr(ErrBadDirective, g.Line, g.Locator, "a group is not valid under delimiter none")
		}
		i, ok := parseTextIndex(g.Locator)
		if !ok {
			return perr(ErrBadDirective, g.Line, g.Locator, "a text group locator is a field index, got %q", g.Locator)
		}
		n, ok := parseTextIndex(g.itemText)
		if !ok || n < 1 {
			return perr(ErrBadDirective, g.Line, g.Locator, "group: `item` takes a number of fields >= 1, got %q", g.itemText)
		}
		g.tstart, g.titem = i, n
		g.loc = locator{raw: g.Locator, kind: locTField, ti: i}
	}
	for _, f := range p.Fields {
		loc, err := parseTextLocator(f.Locator)
		if err != nil {
			return perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
		}
		f.loc = loc
		if err := checkIdx(&f.loc, f.group); err != nil {
			return perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
		}
		tf, kind, err := resolveTextTransform(f.Transform)
		if err != nil {
			if err := note(perr(kind, f.Line, f.Locator, "%v", err)); err != nil {
				return err
			}
			continue
		}
		f.ttf = tf
		switch {
		case loc.kind == locTPair && !tf.pair:
			return perr(ErrBadDirective, f.Line, f.Locator, "a pair is valid only with dm and hms_dmy, not %s", f.Transform)
		case loc.kind != locTPair && tf.pair:
			return perr(ErrBadDirective, f.Line, f.Locator, "%s takes a pair <i>+<j>", f.Transform)
		case loc.kind == locTPair && loc.ti == loc.tj:
			return perr(ErrBadDirective, f.Line, f.Locator, "the two fields of a pair are different")
		case f.Swap || f.Trim || f.StopLine:
			// `stop` is an option of a chars field on bits (0.22).
			return perr(ErrBadDirective, f.Line, f.Locator, "field options swap, trim and stop are not valid on wire text")
		case f.Absent != nil:
			// `absent` (0.9) on text is bad-directive (0.10 ruling 16).
			return perr(ErrBadDirective, f.Line, f.Locator, "field option `absent` is not valid on wire text")
		case f.Optional && f.group != nil:
			return perr(ErrBadDirective, f.Line, f.Locator, "field option `optional` is not valid inside a group")
		}
		f.yields, _ = transformYields(f.Transform)
		if f.Via != "" {
			f.table = p.tables[f.Via]
			if f.table == nil {
				return perr(ErrBadDirective, f.Line, f.Locator, "`via %s` names a table with no map line", f.Via)
			}
		}
	}
	for _, w := range whens {
		if w.Const && w.Value == "present" {
			return perr(ErrBadDirective, w.Line, w.Locator, "a const cannot be `present`; write `=present` for the text")
		}
		loc, err := parseTextLocator(w.Locator)
		if err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
		}
		w.loc = loc
		if loc.kind == locTPair {
			return perr(ErrBadDirective, w.Line, w.Locator, "a when or const takes a field or a column, not a pair")
		}
		if err := checkIdx(&w.loc, w.group); err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
		}
		if err := resolveWhen(WireText, w); err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
		}
		if w.present {
			continue
		}
		if err := p.checkTextValue(w); err != nil {
			return perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
		}
	}
	// The group is the last thing in its scope.
	checkScope := func(lines []line) error {
		var g *Group
		for _, ln := range lines {
			if ln.g != nil {
				if g != nil {
					return perr(ErrBadDirective, ln.g.Line, ln.g.Locator, "a second group in the scope of the group on line %d", g.Line)
				}
				g = ln.g
			}
		}
		if g == nil {
			return nil
		}
		for _, ln := range lines {
			var l *locator
			var at int
			var raw string
			switch {
			case ln.f != nil:
				l, at, raw = &ln.f.loc, ln.f.Line, ln.f.Locator
			case ln.w != nil:
				l, at, raw = &ln.w.loc, ln.w.Line, ln.w.Locator
			default:
				continue
			}
			for _, i := range l.indexes() {
				if i >= g.tstart {
					return perr(ErrBadDirective, at, raw, "field %d is at or beyond the start %d of the group on line %d, which is the last thing in its scope", i, g.tstart, g.Line)
				}
			}
		}
		return nil
	}
	if p.HasKinds() {
		for _, k := range p.Kinds {
			if err := checkScope(append(append([]line(nil), p.common...), k.lines...)); err != nil {
				return err
			}
		}
	} else if err := checkScope(p.common); err != nil {
		return err
	}
	return nil
}

// checkTextValue checks the value of a `when` or `const` on wire text.
func (p *Pack) checkTextValue(w *When) error {
	v := w.text
	if v == "" {
		return fmt.Errorf("a when or const value on wire text is not empty")
	}
	if v[0] == ' ' || v[len(v)-1] == ' ' {
		return fmt.Errorf("a when or const value on wire text has no space at its start or end, got %q", v)
	}
	for i := 0; i < len(v); i++ {
		c := v[i]
		switch {
		case c < 0x20 || c > 0x7E:
			return fmt.Errorf("a when or const value on wire text holds characters from 0x20 to 0x7E only, got %q", v)
		case !p.delimNone && c == p.delim:
			return fmt.Errorf("a when or const value holds the delimiter, got %q", v)
		case p.nmea && c == '*':
			return fmt.Errorf("a when or const value holds `*` under checksum nmea, got %q", v)
		}
	}
	if w.loc.kind == locTCol && len(v) > w.loc.clen {
		return fmt.Errorf("the value %q is longer than its column of %d characters", v, w.loc.clen)
	}
	return nil
}

// textScope is what one scope of a text pack addresses: the fields its lines
// other than its group address, whether every line that addresses a field
// carries `optional`, and its group.
type textScope struct {
	addressed map[int]bool
	allOpt    map[int]bool
	maxAddr   int // the highest index addressed, -1 for none
	group     *Group
}

func newTextScope(lines []line) *textScope {
	s := &textScope{addressed: map[int]bool{}, allOpt: map[int]bool{}, maxAddr: -1}
	add := func(i int, opt bool) {
		if !s.addressed[i] {
			s.addressed[i] = true
			s.allOpt[i] = opt
		} else if !opt {
			s.allOpt[i] = false
		}
		if i > s.maxAddr {
			s.maxAddr = i
		}
	}
	for _, ln := range lines {
		switch {
		case ln.f != nil:
			for _, i := range ln.f.loc.indexes() {
				add(i, ln.f.Optional)
			}
		case ln.w != nil:
			if !ln.w.present {
				add(ln.w.loc.ti, false)
			}
		case ln.g != nil:
			if s.group == nil {
				s.group = ln.g
			}
		}
	}
	return s
}

func isHex(s string) bool {
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !(c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F') {
			return false
		}
	}
	return true
}
