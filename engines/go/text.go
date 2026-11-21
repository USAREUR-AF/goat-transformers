//go:build !goat_wires || goat_wire_text

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

// --- locators ---

// --- transforms ---

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
