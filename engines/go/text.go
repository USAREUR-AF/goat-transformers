package goatxf

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

// The text wire (spec/engine-spec.md, "Version 0.10: the `text` wire"): one
// record of ASCII text, fields separated by a delimiter, optionally framed by
// a start text and a checksum. A field may also be read as columns.

// --- directives ---

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

// --- locators ---

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

// --- transforms ---

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
	if name == "bool" || name == "iso8601_short" || isBitsTransformName(name) || isPBTransformName(name) || isTLVOnlyTransform(name) || v015Base(name) != "" {
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

// pow10i is 10^n for n from 0 to 9.
var pow10i = [...]int64{1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000, 1000000000}

const twoTo53 = 9007199254740992.0

// readTextInt reads an optional sign and one or more digits.
func readTextInt(s string) (int64, error) {
	t := s
	if t != "" && (t[0] == '+' || t[0] == '-') {
		t = t[1:]
	}
	if !isDigits(t) {
		return 0, fmt.Errorf("not an integer: %q", s)
	}
	n, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0, fmt.Errorf("integer out of range: %q", s)
	}
	return n, nil
}

// readTextDecimal reads an optional sign, then digits with at most one `.`
// and at least one digit, as the double nearest the decimal.
func readTextDecimal(s string) (float64, error) {
	t := s
	if t != "" && (t[0] == '+' || t[0] == '-') {
		t = t[1:]
	}
	digits, dots := 0, 0
	for i := 0; i < len(t); i++ {
		switch c := t[i]; {
		case c >= '0' && c <= '9':
			digits++
		case c == '.':
			dots++
		default:
			return 0, fmt.Errorf("not a decimal number: %q", s)
		}
	}
	if digits == 0 || dots > 1 {
		return 0, fmt.Errorf("not a decimal number: %q", s)
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
		return 0, fmt.Errorf("number out of range: %q", s)
	}
	return f, nil
}

// fracOK reports whether s is empty or `.` followed by one or more digits.
func fracOK(s string) bool {
	return s == "" || (s[0] == '.' && isDigits(s[1:]))
}

// readHMS reads `hhmmss` then optionally `.` and digits.
func readHMS(s string) (h, m int, sec string, err error) {
	if len(s) < 6 || !isDigits(s[:6]) || !fracOK(s[6:]) {
		return 0, 0, "", fmt.Errorf("not a time hhmmss[.s]: %q", s)
	}
	h, _ = strconv.Atoi(s[0:2])
	m, _ = strconv.Atoi(s[2:4])
	ss, _ := strconv.Atoi(s[4:6])
	if h >= 24 || m >= 60 || ss >= 60 {
		return 0, 0, "", fmt.Errorf("time out of range: %q", s)
	}
	return h, m, s[4:], nil
}

func padDigits(n int64, width int) string {
	s := strconv.FormatInt(n, 10)
	if len(s) < width {
		s = strings.Repeat("0", width-len(s)) + s
	}
	return s
}

// zeroPadAfterSign pads s with zeros after any `-` until the text without
// the sign is at least w characters.
func zeroPadAfterSign(s string, w int) string {
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	if len(s) < w {
		s = strings.Repeat("0", w-len(s)) + s
	}
	return sign + s
}

// decode reads one text, or the two texts of a pair, as a model value.
func (t *textTf) decode(a, b string) (Value, error) {
	switch t.kind {
	case ttString:
		return Value{Kind: KindString, S: a}, nil
	case ttInt, ttIntW:
		n, err := readTextInt(a)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindInt, I: n}, nil
	case ttFloat, ttDec:
		f, err := readTextDecimal(a)
		if err != nil {
			return Value{}, err
		}
		return Value{Kind: KindFloat, F: f}, nil
	case ttISO:
		return decISO(a)
	case ttDM:
		d := t.d
		if len(a) < d+2 || !isDigits(a[:d+2]) || !fracOK(a[d+2:]) {
			return Value{}, fmt.Errorf("not degrees and minutes of %d degree digits: %q", d, a)
		}
		deg, _ := strconv.Atoi(a[:d])
		// The two minute digits are compared as an integer, before any
		// fraction (0.10 ruling 15).
		mm, _ := strconv.Atoi(a[d : d+2])
		min, err := strconv.ParseFloat(a[d:], 64)
		if err != nil || mm >= 60 {
			return Value{}, fmt.Errorf("minutes of 60 or more: %q", a)
		}
		v := min/60 + float64(deg)
		switch {
		case len(b) == 1 && b[0] == t.pl:
		case len(b) == 1 && b[0] == t.nl:
			v = -v
		default:
			return Value{}, fmt.Errorf("the letter is %c or %c, got %q", t.pl, t.nl, b)
		}
		return Value{Kind: KindFloat, F: v}, nil
	case ttHMS:
		h, m, sec, err := readHMS(a)
		if err != nil {
			return Value{}, err
		}
		s, err := strconv.ParseFloat(sec, 64)
		if err != nil {
			return Value{}, fmt.Errorf("not a time: %q", a)
		}
		return Value{Kind: KindFloat, F: float64(h*3600+m*60) + s}, nil
	case ttHMSDMY:
		h, m, sec, err := readHMS(a)
		if err != nil {
			return Value{}, err
		}
		ss, _ := strconv.Atoi(sec[:2])
		ms := int64(0)
		if len(sec) > 3 {
			frac := sec[3:]
			if len(frac) > 3 {
				frac = frac[:3]
			}
			frac += strings.Repeat("0", 3-len(frac))
			ms, _ = strconv.ParseInt(frac, 10, 64)
		}
		if len(b) != 6 || !isDigits(b) {
			return Value{}, fmt.Errorf("not a date ddmmyy: %q", b)
		}
		dd, _ := strconv.Atoi(b[0:2])
		mo, _ := strconv.Atoi(b[2:4])
		yy, _ := strconv.Atoi(b[4:6])
		year := 2000 + yy
		if yy >= 80 {
			year = 1900 + yy
		}
		if mo < 1 || mo > 12 || dd < 1 || dd > daysIn(year, mo) {
			return Value{}, fmt.Errorf("the date %q does not exist", b)
		}
		days := time.Date(year, time.Month(mo), dd, 0, 0, 0, 0, time.UTC).Unix() / 86400
		v := days*86400000 + int64(h*3600+m*60+ss)*1000 + ms
		return Value{Kind: KindInt, I: v}, nil
	}
	return Value{}, fmt.Errorf("no transform")
}

func daysIn(year, month int) int {
	return time.Date(year, time.Month(month)+1, 0, 0, 0, 0, 0, time.UTC).Day()
}

// encode writes a model value as one text, or the two texts of a pair.
func (t *textTf) encode(v Value) (string, string, error) {
	switch t.kind {
	case ttString:
		s, err := encString(v)
		return s, "", err
	case ttInt:
		s, err := encInt(v)
		return s, "", err
	case ttFloat:
		s, err := encFloat(v)
		return s, "", err
	case ttISO:
		s, err := encISO(v)
		return s, "", err
	case ttIntW:
		n, err := valueToInt(v)
		if err != nil {
			return "", "", err
		}
		return zeroPadAfterSign(strconv.FormatInt(n, 10), t.w), "", nil
	case ttDec:
		x, err := valueToFloat(v)
		if err != nil {
			return "", "", err
		}
		n := math.Round(x * float64(pow10i[t.f]))
		if math.IsNaN(n) || math.IsInf(n, 0) || math.Abs(n) >= twoTo53 {
			return "", "", fmt.Errorf("value %v is out of range for %s", x, t.name)
		}
		digits := padDigits(int64(math.Abs(n)), t.f+1)
		if t.f > 0 {
			digits = digits[:len(digits)-t.f] + "." + digits[len(digits)-t.f:]
		}
		if n < 0 {
			digits = "-" + digits
		}
		if t.w > 0 {
			digits = zeroPadAfterSign(digits, t.w)
		}
		return digits, "", nil
	case ttDM:
		x, err := valueToFloat(v)
		if err != nil {
			return "", "", err
		}
		m := math.Round(math.Abs(x) * 60 * float64(pow10i[t.f]))
		if math.IsNaN(m) || math.IsInf(m, 0) || m >= twoTo53 {
			return "", "", fmt.Errorf("value %v is out of range for %s", x, t.name)
		}
		mi := int64(m)
		unit := 60 * pow10i[t.f]
		deg := mi / unit
		if deg >= pow10i[t.d] {
			return "", "", fmt.Errorf("value %v: %d degrees do not fit %d digits", x, deg, t.d)
		}
		rem := mi % unit
		a := padDigits(deg, t.d) + padDigits(rem/pow10i[t.f], 2)
		if t.f > 0 {
			a += "." + padDigits(rem%pow10i[t.f], t.f)
		}
		letter := t.pl
		if x < 0 && mi > 0 {
			letter = t.nl
		}
		return a, string(letter), nil
	case ttHMS:
		x, err := valueToFloat(v)
		if err != nil {
			return "", "", err
		}
		n := math.Round(x * float64(pow10i[t.f]))
		if math.IsNaN(n) || math.IsInf(n, 0) || math.Abs(n) >= twoTo53 || n < 0 || n >= 86400*float64(pow10i[t.f]) {
			return "", "", fmt.Errorf("value %v is not a time of day for %s", x, t.name)
		}
		ni := int64(n)
		return hmsText(ni/pow10i[t.f], ni%pow10i[t.f], t.f), "", nil
	case ttHMSDMY:
		ms, err := valueToInt(v)
		if err != nil {
			return "", "", err
		}
		days := ms / 86400000
		msod := ms % 86400000
		if msod < 0 {
			days--
			msod += 86400000
		}
		// The year is checked from the date itself, so it never wraps.
		if days < -1e8 || days > 1e8 {
			return "", "", fmt.Errorf("value %d is outside the years 1980 to 2079", ms)
		}
		tm := time.Unix(days*86400, 0).UTC()
		if y := tm.Year(); y < 1980 || y > 2079 {
			return "", "", fmt.Errorf("value %d is in the year %d, outside 1980 to 2079", ms, y)
		}
		frac := (msod % 1000) / pow10i[3-t.f]
		a := hmsText(msod/1000, frac, t.f)
		b := padDigits(int64(tm.Day()), 2) + padDigits(int64(tm.Month()), 2) + padDigits(int64(tm.Year()%100), 2)
		return a, b, nil
	}
	return "", "", fmt.Errorf("no transform")
}

// hmsText writes seconds since midnight as hhmmss, then `.` and f digits of
// frac when f is above 0.
func hmsText(secs, frac int64, f int) string {
	s := padDigits(secs/3600, 2) + padDigits(secs/60%60, 2) + padDigits(secs%60, 2)
	if f > 0 {
		s += "." + padDigits(frac, f)
	}
	return s
}

// --- load checks ---

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
		case f.Swap || f.Trim:
			return perr(ErrBadDirective, f.Line, f.Locator, "field options swap and trim are not valid on wire text")
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

// addresses reports whether the scope addresses field i for residue: by a
// line, or by its group, whose items run from the group's index on.
func (s *textScope) addresses(i int) bool {
	return s.addressed[i] || (s.group != nil && i >= s.group.tstart)
}

// --- decode ---

func malformedText(p *Pack, format string, a ...any) error {
	return &Error{Kind: ErrMalformedWire, Format: p.Format, Detail: fmt.Sprintf(format, a...)}
}

// splitTextRecord takes the input through steps 1 to 5 of "Reading a
// record" and returns the fields.
func splitTextRecord(p *Pack, b []byte) ([]string, error) {
	s := string(b)
	if strings.HasSuffix(s, "\r\n") {
		s = s[:len(s)-2]
	} else if strings.HasSuffix(s, "\n") {
		s = s[:len(s)-1]
	}
	for i := 0; i < len(s); i++ {
		if s[i] < 0x20 || s[i] > 0x7E {
			return nil, malformedText(p, "byte 0x%02x at %d is outside 0x20 to 0x7E", s[i], i)
		}
	}
	if p.start != "" {
		if !strings.HasPrefix(s, p.start) {
			return nil, malformedText(p, "the record does not begin with %q", p.start)
		}
		s = s[len(p.start):]
	}
	if p.nmea {
		if len(s) < 3 || s[len(s)-3] != '*' {
			return nil, malformedText(p, "the record does not end with `*` and two hexadecimal digits")
		}
		want, err := strconv.ParseUint(s[len(s)-2:], 16, 8)
		if err != nil || !isHex(s[len(s)-2:]) {
			return nil, malformedText(p, "the checksum %q is not two hexadecimal digits", s[len(s)-2:])
		}
		s = s[:len(s)-3]
		if x := xorBytes(s); uint64(x) != want {
			return nil, malformedText(p, "checksum %02X does not match the record's %02X", want, x)
		}
		if strings.IndexByte(s, '*') >= 0 {
			return nil, malformedText(p, "a `*` is left in the record")
		}
	}
	if p.delimNone {
		return []string{s}, nil
	}
	return strings.Split(s, string(p.delim)), nil
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

func xorBytes(s string) byte {
	var x byte
	for i := 0; i < len(s); i++ {
		x ^= s[i]
	}
	return x
}

// textField is field i of the record, and whether it is present (not empty).
func textField(fields []string, i int) (string, bool) {
	if i < 0 || i >= len(fields) || fields[i] == "" {
		return "", false
	}
	return fields[i], true
}

// textColumn is the text of a column, its trailing spaces removed and, when
// numeric, its leading spaces too; ok is false when the column is absent.
func textColumn(fields []string, l *locator, base int, numeric bool) (string, bool) {
	f, ok := textField(fields, base+l.ti)
	if !ok || len(f) <= l.from {
		return "", false
	}
	end := l.from + l.clen
	if end > len(f) {
		end = len(f)
	}
	t := strings.TrimRight(f[l.from:end], " ")
	if numeric {
		t = strings.TrimLeft(t, " ")
	}
	return t, t != ""
}

// whenHoldsText reports whether a `when` holds on the record.
func whenHoldsText(w *When, fields []string) bool {
	var t string
	var ok bool
	if w.loc.kind == locTCol {
		t, ok = textColumn(fields, &w.loc, 0, false)
	} else {
		t, ok = textField(fields, w.loc.ti)
	}
	if !ok {
		return false
	}
	return w.present || t == w.text
}

func decodeText(d *decodeState, b []byte) error {
	p := d.pack
	fields, err := splitTextRecord(p, b)
	if err != nil {
		return err
	}
	lay, err := d.choose(func(w *When) bool { return whenHoldsText(w, fields) })
	if err != nil {
		return err
	}
	if err := d.textScope(lay, fields, 0); err != nil {
		return err
	}
	for i, f := range fields {
		if f != "" && !lay.text.addresses(i) {
			d.residue(strconv.Itoa(i), f, false)
		}
	}
	return nil
}

// textScope reads the lines of one scope: the record, or one item of a group
// whose first field is base.
func (d *decodeState) textScope(lay *layout, fields []string, base int) error {
	for _, ln := range lay.lines {
		switch {
		case ln.f != nil:
			f := ln.f
			if _, done := d.rec.Fields[f.Key]; done {
				continue
			}
			var a, b string
			var ok bool
			switch f.loc.kind {
			case locTField:
				a, ok = textField(fields, base+f.loc.ti)
			case locTCol:
				a, ok = textColumn(fields, &f.loc, base, f.ttf.numeric)
			case locTPair:
				var ok2 bool
				a, ok = textField(fields, base+f.loc.ti)
				b, ok2 = textField(fields, base+f.loc.tj)
				ok = ok && ok2
			}
			if !ok {
				continue
			}
			v, err := f.ttf.decode(a, b)
			if err != nil {
				d.fail(f, err.Error())
				continue
			}
			d.store(f, v)
		case ln.g != nil:
			g := ln.g
			if len(fields) <= g.tstart {
				continue
			}
			n := (len(fields) - g.tstart + g.titem - 1) / g.titem
			if err := d.room(g.List, uint64(n)); err != nil {
				return err
			}
			items := make([]*Item, 0, n)
			for k := 0; k < n; k++ {
				it, err := d.item(func() error {
					return d.textScope(g.body, fields, g.tstart+k*g.titem)
				})
				if err != nil {
					return err
				}
				items = append(items, it)
			}
			d.rec.SetList(g.List, items)
		}
	}
	return nil
}

// --- encode ---

// tfield is one field of the record being written.
type tfield struct {
	whole    string
	hasWhole bool
	cols     []byte
	colSet   []bool
}

// forcedText is one `when` or `const` write.
type forcedText struct {
	idx  int
	col  bool
	from int
	clen int
	text string
}

type textWriter struct {
	p      *Pack
	fields map[int]*tfield
	forced []forcedText
	max    int
}

func (w *textWriter) at(i int) *tfield {
	f := w.fields[i]
	if f == nil {
		f = &tfield{}
		w.fields[i] = f
	}
	return f
}

// checkOut refuses text that holds the delimiter, a `*` under checksum nmea,
// or a character outside 0x20 to 0x7E.
func (w *textWriter) checkOut(f *Field, s string) error {
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c < 0x20 || c > 0x7E:
			return encodeErr(w.p, f, fmt.Errorf("the text %q holds a character outside 0x20 to 0x7E", s))
		case !w.p.delimNone && c == w.p.delim:
			return encodeErr(w.p, f, fmt.Errorf("the text %q holds the delimiter", s))
		case w.p.nmea && c == '*':
			return encodeErr(w.p, f, fmt.Errorf("the text %q holds `*` under checksum nmea", s))
		}
	}
	return nil
}

// scope writes the lines of one scope: the record, or one item whose first
// field is base.
func (w *textWriter) scope(lay *layout, rec *Item, base int) error {
	p := w.p
	for _, ln := range lay.lines {
		switch {
		case ln.g != nil:
			g := ln.g
			items := rec.Lists[g.List]
			for k, it := range items {
				if err := w.scope(g.body, it, g.tstart+k*g.titem); err != nil {
					return err
				}
			}
			if len(items) > 0 {
				if end := g.tstart + len(items)*g.titem - 1; end > w.max {
					w.max = end
				}
			}
		case ln.w != nil:
			wl := ln.w
			if wl.present {
				continue
			}
			w.forced = append(w.forced, forcedText{idx: base + wl.loc.ti, col: wl.loc.kind == locTCol, from: wl.loc.from, clen: wl.loc.clen, text: wl.text})
		case ln.f != nil:
			f := ln.f
			v, ok, err := fieldValue(p, lay, f, rec)
			if err != nil {
				return err
			}
			if !ok {
				continue
			}
			a, b, err := f.ttf.encode(v)
			if err != nil {
				return encodeErr(p, f, err)
			}
			if err := w.checkOut(f, a); err != nil {
				return err
			}
			if err := w.checkOut(f, b); err != nil {
				return err
			}
			switch f.loc.kind {
			case locTField, locTPair:
				if t := w.at(base + f.loc.ti); !t.hasWhole {
					t.whole, t.hasWhole = a, true
				}
				if f.loc.kind == locTPair {
					if t := w.at(base + f.loc.tj); !t.hasWhole {
						t.whole, t.hasWhole = b, true
					}
				}
			case locTCol:
				if len(a) > f.loc.clen {
					return encodeErr(p, f, fmt.Errorf("the text %q is longer than its column of %d characters", a, f.loc.clen))
				}
				if f.ttf.numeric {
					// The column is clen characters, the sign included.
					w := f.loc.clen
					if strings.HasPrefix(a, "-") {
						w--
					}
					a = zeroPadAfterSign(a, w)
				} else {
					a += strings.Repeat(" ", f.loc.clen-len(a))
				}
				t := w.at(base + f.loc.ti)
				end := f.loc.from + f.loc.clen
				for len(t.cols) < end {
					t.cols = append(t.cols, ' ')
					t.colSet = append(t.colSet, false)
				}
				for k := 0; k < len(a); k++ {
					if !t.colSet[f.loc.from+k] {
						t.cols[f.loc.from+k] = a[k]
						t.colSet[f.loc.from+k] = true
					}
				}
			}
		}
	}
	return nil
}

// text is the final text of field i: the whole-field text when a line wrote
// one, else the columns, then the `when` and `const` writes over it, the
// earlier line's characters standing.
func (w *textWriter) text(i int) string {
	var s []byte
	if t := w.fields[i]; t != nil {
		if t.hasWhole {
			s = []byte(t.whole)
		} else {
			s = append(s, t.cols...)
		}
	}
	for k := len(w.forced) - 1; k >= 0; k-- {
		fc := w.forced[k]
		if fc.idx != i {
			continue
		}
		if !fc.col {
			s = []byte(fc.text)
			continue
		}
		v := fc.text + strings.Repeat(" ", fc.clen-len(fc.text))
		for len(s) < fc.from+len(v) {
			s = append(s, ' ')
		}
		copy(s[fc.from:], v)
	}
	return string(s)
}

func encodeText(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error) {
	w := &textWriter{p: p, fields: map[int]*tfield{}, max: lay.text.maxAddr}
	if err := w.scope(lay, rec, 0); err != nil {
		return nil, err
	}
	// Residue of this format, at the fields no line of the scope addresses.
	for _, r := range ent.Residue {
		if r.Format != p.Format {
			continue
		}
		i, ok := parseTextIndex(r.Locator)
		if !ok || lay.text.addresses(i) {
			continue
		}
		if t := w.at(i); !t.hasWhole {
			t.whole, t.hasWhole = r.Value, true
			if i > w.max {
				w.max = i
			}
		}
	}
	n := w.max + 1
	texts := make([]string, n)
	for i := range texts {
		texts[i] = w.text(i)
	}
	sc := lay.text
	for n > 0 && texts[n-1] == "" && sc.addressed[n-1] && sc.allOpt[n-1] && !(sc.group != nil && n-1 >= sc.group.tstart) {
		n--
	}
	var body string
	if p.delimNone {
		if n > 0 {
			body = texts[0]
		}
	} else {
		body = strings.Join(texts[:n], string(p.delim))
	}
	out := p.start + body
	if p.nmea {
		out += fmt.Sprintf("*%02X", xorBytes(body))
	}
	return []byte(out), nil
}
