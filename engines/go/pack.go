package goatxf

import (
	"bufio"
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Wire names the codec a pack uses.
const (
	WireXML      = "xml"
	WireGeoJSON  = "geojson"
	WireBits     = "bits"
	WireProtobuf = "protobuf"
	WireJSON     = "json"
	WireText     = "text"
	WireTLV      = "tlv"
	WireCBOR     = "cbor"
)

type locKind int

const (
	locAttr   locKind = iota + 1 // xml @name, path/@name
	locText                      // xml path/#text
	locElem                      // xml path (residue only: an empty element)
	locCoord                     // geojson geometry.lon|lat|alt
	locProp                      // geojson properties.<name>
	locTop                       // geojson <name>
	locBits                      // bits word:pos:len
	locProto                     // protobuf dot-path of field numbers
	locJSON                      // json dot-path of member names
	locTField                    // text <i>: a whole field
	locTCol                      // text <i>:<from>:<len>: a column of a field
	locTPair                     // text <i>+<j>: two fields as one value
	locTLV                       // tlv <tag>[.<tag>…][:<n>]
)

// maxBitsLen is the longest bits field: an `ascii` field of 255 bytes, or a
// `chars` field (0.15).
const maxBitsLen = 2040

// maxFieldNumber is the largest protobuf field number, 2^29 - 1.
const maxFieldNumber = 536870911

// maxLocatorLen bounds the length a sequential locator states. A field's
// transform decides which lengths it allows (bad-directive, 0.5 and 0.15 "a
// `len` it does not allow"); the bound only keeps the arithmetic on lengths
// in range.
const maxLocatorLen = 1 << 24

type locator struct {
	raw    string
	kind   locKind
	path   []string // xml element path under the root; json member path
	name   string   // attribute, property or top-level member name
	idx    int      // coordinate index for locCoord
	word   int      // bits word index
	pos    int      // bits start position, counted from the start of the word
	blen   int      // bits field length
	bit    int      // bits: absolute start bit in the message
	pbPath []int    // protobuf field-number path
	ti, tj int      // text: the field index; the second field of a pair
	from   int      // text: the first character of a column
	clen   int      // text: the length of a column
	tags   []uint64 // tlv: the tags of the path
	tsize  int      // tlv: the size `:<n>`, 0 when the path has none
	cpath  []cStep  // cbor: the steps of the path; nil for `.`
}

// Field is one `field` line: a model key bound to a wire locator through a
// transform, with the options of spec 0.6 (`via <table>`, `swap`, `trim`,
// `optional`).
type Field struct {
	Key       string
	Locator   string
	Transform string
	Line      int
	Via       string // value table name, "" when the line has no `via`
	Swap      bool
	Trim      bool
	Optional  bool
	Absent    []string // `absent <value>[,<value>…]`: the values as written, nil when the line has none
	With      string   // `with <other-key>` (0.18): the line writes only when the entity or item holds the key; "" when the line has none
	WithLine  bool     // the line has `with`
	Stop      string   // `stop <code>` (0.22): the code as written; "" when the line has none
	StopLine  bool     // the line has `stop`
	Unlisted  bool     // `unlisted` (0.64): a part with no table entry is absent

	part     *partSpec  // a `part` line (0.64), nil otherwise
	absent   *sentinels // the sentinels read for the pack's wire; nil when the line has no `absent`
	loc      locator
	group    *Group   // the innermost group the line is in, nil outside a group
	gate     *Gate    // the innermost gate block the line is in, nil outside a block (0.17)
	dot      bool     // the locator is `.`: the item itself, as a scalar
	also     []*Field // sequential layouts: the keys `also` lines bind to the same bits, in line order
	tf       *transform
	ttf      *textTf // text wire transform
	xtf      *tlvTf  // tlv wire transform
	ctf      int     // cbor wire transform (spec 0.28)
	btf      *bitsTransform
	uper     *uperLoc                // a UPER locator (spec 0.19), nil for a bit length
	charsets map[string]*packCharset // the pack's charset lines by name, for code, codestr and codenum (0.46)
	until    bool                    // the locator is `until:<code>` (0.22): characters up to a terminator
	untilC   uint64                  // the terminator code of `until:`
	pbf      *pbTransform
	jbool    bool // json `bool`
	yields   Kind // the type the transform yields
	keyType  Kind // the key's declared type; set when the pack is loaded
	table    *valueTable
	viaDec   map[string]string // canonical native text -> model text
	viaEnc   map[string]string // canonical model text -> native text
}

// When is one `when` line (the kind applies when the wire holds Value at
// Locator) or one `const` line (Value is written at Locator on encode and not
// checked on decode).
type When struct {
	Locator string
	Value   string
	Line    int
	Const   bool
	loc     locator
	group   *Group     // the innermost group the line is in, nil outside a group
	gate    *Gate      // the innermost gate block the line is in, nil outside a block (0.17)
	present bool       // the value is the word `present`
	text    string     // text wires: the value, a leading `=` stripped
	forced  bool       // text wires: the value was written with a leading `=`
	num     uint64     // bits and protobuf: the unsigned integer
	texts   []string   // text wires: every listed value, a leading `=` stripped (0.20)
	ranges  []numRange // bits and protobuf: every listed value or range (0.20)
	cv      cborVal    // cbor: the value, typed (spec 0.28, Kinds)
	part    *partSpec  // `const … part` (0.64), nil otherwise; text is its text
}

// numRange is one value (lo = hi) or one range lo..hi of a `when` list.
type numRange struct{ lo, hi uint64 }

// matchNum reports whether an unsigned wire value matches the `when`: it
// equals a listed value or lies in a listed range (0.20).
func (w *When) matchNum(u uint64) bool {
	if w.ranges == nil {
		return u == w.num
	}
	for _, r := range w.ranges {
		if u >= r.lo && u <= r.hi {
			return true
		}
	}
	return false
}

// matchText reports whether a text matches one of the listed values of a
// text-wire `when` (0.20).
func (w *When) matchText(s string) bool {
	if w.texts == nil {
		return s == w.text
	}
	for _, t := range w.texts {
		if s == t {
			return true
		}
	}
	return false
}

// Default is one `default` line: the value an encode uses for a key the
// entity lacks.
type Default struct {
	Key   string
	Value string
	Line  int
	val   Value // Value read as the key's declared type; set when the pack is loaded
}

// mapEntry is one `map` line of a value table.
type mapEntry struct {
	native, model string
	line          int
}

// valueTable is the `map` lines of one table name, in file order.
type valueTable struct {
	name      string
	entries   []mapEntry
	modelType Kind // int when every model value is an integer, else float when every one is a number, else string
}

// line is one `field`, `when` or `const` line, or one `group` block, or the
// `if` line of a gate block (0.17), in file order. The lines of a gate block
// follow its `if` line in the same scope, each with in set to its innermost
// block.
type line struct {
	f  *Field
	w  *When
	g  *Group
	gt *Gate    // the line opens this gate block
	in *Gate    // the innermost gate block the line is in, nil outside a block
	el *Element // an `element` line of an xml pack (0.18)
}

// Element is one `element <path>` line of an xml pack (0.18): the element at
// Path, and each element on the way to it, is written even when empty.
type Element struct {
	Path string
	Line int
	path []string
}

// Group is one `group` block (spec/engine-spec.md, "Version 0.7: groups"): a
// part of the message that repeats, mapped to a list of the model. Its lines
// are read relative to one item.
type Group struct {
	List    string
	Locator string
	Line    int

	parent    *Group // the group this one is nested in, nil at the top
	lines     []line
	defaults  []*Default
	body      *layout // the lines of one item, indexed
	loc       locator // xml: the element path, the last name being an item; json: the member path; geojson: the member; protobuf: the field-number path
	hasItem   bool    // the line has `item <bits>`
	hasCount  bool    // the line has `count …`
	itemText  string
	countText string
	start     int      // bits: the first bit of the first item, counted from the first bit of the scope
	itemBits  int      // bits: the size of an item
	countLoc  *locator // bits: where the scope holds the number of items; nil when the count is fixed
	countN    int      // bits: the fixed count
	seqMode   int      // sequential layouts: how the items are delimited (seqCount, seqWhile, seqMore, seqFx, …)
	countBits int      // sequential layouts: the length of the count field of a `count` group
	sizeLB    int      // UPER `group … size <lb> <ub>`: the size bounds
	sizeUB    int
	sbody     *seqBody     // sequential layouts: the lines of one item
	cnt       *seqCountDef // sequential layouts: the count a `count @<name>` group references (0.21)
	cnt2      *seqCountDef // the second count of `count @<a> @<b>` (0.31), nil for one
	innerRest bool         // sequential layouts: a `rest` group is the last line of an item, outside any length block (0.21 ruling 10)
	dots      []*Field     // the `.` fields of the body, in line order
	packed    bool         // protobuf: the first `.` field has a numeric transform, so the list is a repeated scalar
	needsMsg  bool         // protobuf: the body has a line that reads into the item as a submessage
	tstart    int          // text: the index of the first field of the first item
	titem     int          // text: the number of fields of an item
	cdot      bool         // cbor: `group <list> .`, the top item
	ckind     int          // cbor: what an item is to the body: ckDot, ckMap or ckArr
	cbody     *cNode       // cbor: the paths of the body
}

// KindDef is one `kind` of a pack: its `when`, `requires`, `field`, `const`
// and `default` lines, and on the xml wire its own root element.
type KindDef struct {
	Name     string
	Line     int
	Requires []string   // the keys of the `requires` terms, in line order
	reqs     []*reqTerm // the `requires` terms, in line order
	Root     string     // xml: the kind's root element, "" to use the pack's
	rootLine int
	lines    []line
	whens    []*When // the kind's `when` lines, in line order
	defaults []*Default
}

// layout is one scope: what one message of a pack holds (the common lines
// then the lines of one kind, in line order; a pack with no kind has one), or
// what one item of a group holds.
type layout struct {
	kind     *KindDef // nil in a pack with no kind, and in a group body
	lines    []line
	fieldsAt map[string][]*Field   // locator -> the field lines bound to it
	elemAt   map[int][][]string    // xml: line index -> the element paths an encode creates there, shortest first (0.18 ruling 13)
	whenAt   map[string]bool       // locators a `when` or `const` line maps
	forced   map[string]*When      // text wires: locator -> the when or const whose value is written there
	defaults map[string]*Default   // model key -> the default in scope
	groups   []*Group              // the scope's group blocks, in line order
	groupAt  map[string]*Group     // locator -> the group mapped there
	parts    map[string]*partGroup // locator -> the part group there (0.64)
	root     string                // xml: the root element of this layout
	maxBit   int                   // bits: the furthest bit a line outside any gate block with a fixed place reaches, from the scope's first bit
	allBit   int                   // bits: the same over every line, gate blocks and their gates included
	gates    []*Gate               // bits: the scope's gate blocks, in line order (0.17)
	needBit  int                   // bits: the same, over the lines that are not optional
	bytes    int                   // bits: the length an encode writes before any counted items, in bytes
	decBytes int                   // bits: the shortest input a decode accepts, in bytes
	text     *textScope            // text: the fields the scope addresses
	tlv      *tlvSet               // tlv: the sets the scope addresses
	cbor     *cNode                // cbor: the paths of the scope (spec 0.28)
}

// maps reports whether a field, a const or a when line of the layout maps loc.
func (l *layout) maps(loc string) bool {
	return len(l.fieldsAt[loc]) > 0 || l.whenAt[loc]
}

// keyRef is one model key a pack names, on a `field`, `requires` or `default`
// line.
type keyRef struct {
	key     string
	locator string
	line    int
	field   *Field   // nil unless a `field` line
	def     *Default // nil unless a `default` line
	group   *Group   // nil unless a `group` line
	req     bool     // a `requires` key: a key or a list
	term    *reqTerm // a `requires` term with `=` (0.20), nil otherwise
	as      bool     // the key of a `when … as` line (0.30)
}

// reqTerm is one term of a `requires` line: a key, and since 0.20 with `=`
// a list of values the key must hold one of.
type reqTerm struct {
	key   string
	eq    bool
	vals  []string        // the values as written
	canon map[string]bool // the canonical texts of the values, set when the pack is loaded
	line  int
}

// valueCheck is one line whose values are read as a key's declared type once
// the modules are known (0.20 ruling 19): a `requires` line with `=` terms,
// or a `case` line of a switch.
type valueCheck struct {
	line  int
	terms []*reqTerm // a requires line
	cas   *seqCase   // a case line
}

// parseRequires reads the terms of a `requires` line (0.20): `<key>` or
// `<key>=<value>[,<value>…]`, split at the first `=`.
func parseRequires(args []string, line int) ([]*reqTerm, error) {
	var out []*reqTerm
	for _, a := range args {
		t := &reqTerm{key: a, line: line}
		if i := strings.IndexByte(a, '='); i >= 0 {
			if i == 0 {
				return nil, fmt.Errorf("requires %q: no key before `=`", a)
			}
			rest := a[i+1:]
			if rest == "" {
				return nil, fmt.Errorf("requires %q: no value after `=`", a)
			}
			vals, err := splitValueList(rest)
			if err != nil {
				return nil, fmt.Errorf("requires %q: %v", a, err)
			}
			t.key, t.eq, t.vals = a[:i], true, vals
		}
		out = append(out, t)
	}
	return out, nil
}

// splitValueList splits a list of values separated by commas; an empty item
// is refused (0.20 ruling 16).
func splitValueList(s string) ([]string, error) {
	vals := strings.Split(s, ",")
	for _, v := range vals {
		if v == "" {
			return nil, fmt.Errorf("an empty value in the list %q", s)
		}
	}
	return vals, nil
}

// canonValue is the canonical text of a `requires =` or `case` value read as
// a key's declared type (0.20 rulings 1 and 17): an integer is an optional
// `-` then digits.
func canonValue(text string, kind Kind) (string, error) {
	switch kind {
	case KindInt:
		digits := strings.TrimPrefix(text, "-")
		if !isDigits(digits) {
			return "", fmt.Errorf("%q is not an integer (an optional - then digits)", text)
		}
		v, err := strconv.ParseInt(text, 10, 64)
		if err != nil {
			return "", fmt.Errorf("%q does not fit a 64-bit integer", text)
		}
		return strconv.FormatInt(v, 10), nil
	case KindFloat:
		if !isFloatText(text) {
			return "", fmt.Errorf("%q is not a number (-?digits[.digits] with an optional exponent)", text)
		}
		v, err := readAs(text, KindFloat)
		if err != nil {
			return "", err
		}
		return v.String(), nil
	}
	return text, nil
}

// reqHolds reports whether a record meets every `requires` term: a plain key
// present (a list with at least one item), a key with `=` present with one of
// the listed values as canonical text (0.20).
func reqHolds(terms []*reqTerm, rec *Item) bool {
	for _, t := range terms {
		if t.eq {
			v, ok := rec.Fields[t.key]
			if !ok || !t.canon[v.String()] {
				return false
			}
			continue
		}
		if _, ok := rec.Fields[t.key]; !ok && len(rec.Lists[t.key]) == 0 {
			return false
		}
	}
	return true
}

// Pack is one parsed pack.def.
type Pack struct {
	charsetLines []*packCharset // the charset lines in file order (0.46)
	charsets     map[string]*packCharset

	// The `at` errors of 0.33, reported last among the load checks
	// (rulings 10 and 25): the form, then the fixed window.
	atErr, winErr error

	Format    string
	Version   string
	Wire      string
	WordBytes int
	BitOrder  string // bits: lsb or msb
	Root      string
	Fields    []*Field   // every `field` line, in file order, those inside groups included
	Groups    []*Group   // every `group` block, in file order, nested ones included
	Kinds     []*KindDef // in file order; empty when the pack has no kind
	Source    string     // the file it was read from, for errors

	Distribution string   // public or controlled
	Sources      []string // `source` lines: the documents the pack was written from
	Uses         []string // `uses` lines, in order; core is always used

	nativeToCot    map[string]string
	cotToNative    map[string]string
	tables         map[string]*valueTable
	common         []line
	commonWhens    []*When
	commonDefaults []*Default
	layouts        []*layout        // one per kind, or one when the pack has no kind
	kindsByRoot    map[string][]int // xml: root element name -> the kinds with that root, in pack order
	keyRefs        []keyRef         // field, requires, default and group names in file order
	modelKeys      []string
	elements       []*Element   // xml: every `element` line, in file order (0.18)
	valueChecks    []valueCheck // requires lines with `=` and case lines, in file order (0.20)
	msb            bitOrder     // the pack's bit order (spec 0.2; msb-lsb, 0.22)
	seq            bool         // bits: `layout sequential` (spec 0.8)
	gates          []*Gate      // every gate block, in file order (0.17)
	sbody          *seqBody     // sequential layouts: the lines of a message

	// text wire (spec 0.10)
	delim     byte           // the delimiter, ',' by default
	delimNone bool           // `delimiter none`: the record is one field
	start     string         // the start text, "" for none
	nmea      bool           // `checksum nmea`
	textSeen  map[string]int // the line of each text directive the pack has

	tlv tlvConf // tlv wire (spec 0.13)

	cbor cborConf // cbor wire (spec 0.28)

	// bits wire, `armor` (spec 0.14)
	sixbitArmor bool // `armor sixbit`: the input and output are six-bit text
	wholeLine   int  // the line of the first `length … whole`, 0 for none

	// bits wire, `encoding uper` (spec 0.19)
	uper     bool
	uperLine int // the first `ext`, `choice`, `alt` or `group … size` line, 0 for none

	// `inner` lines (spec 0.34): the formats they name, each once, in line
	// order, and the line of the first.
	innerFormats []string
	innerLine    int

	runs    bool // the pack has an `inner … run` line: a carrier pack (0.92)
	framing bool // `framing self` (0.92)

	units bool // the pack has a `length @<name> units <u>` line (0.83)
}

// InnerFormats returns the formats the pack's `inner` lines name, each once,
// in line order (spec 0.34).
func (p *Pack) InnerFormats() []string { return append([]string(nil), p.innerFormats...) }

// hasInnerFor reports whether an `inner` line of the pack names format.
func (p *Pack) hasInnerFor(format string) bool {
	for _, f := range p.innerFormats {
		if f == format {
			return true
		}
	}
	return false
}

// HasKinds reports whether the pack declares message kinds.
func (p *Pack) HasKinds() bool { return len(p.Kinds) > 0 }

// ModelKeys is the union of the model keys the pack maps, over the common
// lines and every kind, in first appearance order. A list is named
// `<list>[]` and a key of its items `<list>[].<key>`, nested lists likewise.
func (p *Pack) ModelKeys() []string {
	if p.modelKeys != nil {
		return p.modelKeys
	}
	seen := map[string]bool{}
	out := []string{}
	add := func(k string) {
		if !seen[k] {
			seen[k] = true
			out = append(out, k)
		}
	}
	if p.seq {
		p.sbody.modelKeys(add, "", nil)
		p.modelKeys = out
		return out
	}
	var walk func(lines []line, prefix string)
	walk = func(lines []line, prefix string) {
		for _, ln := range lines {
			switch {
			case ln.f != nil:
				add(prefix + ln.f.Key)
			case ln.g != nil:
				add(prefix + ln.g.List + "[]")
				walk(ln.g.lines, prefix+ln.g.List+"[].")
			}
		}
	}
	walk(p.common, "")
	for _, k := range p.Kinds {
		walk(k.lines, "")
	}
	p.modelKeys = out
	return out
}

// TypeMapped reports whether the pack carries a typemap.
func (p *Pack) TypeMapped() bool { return len(p.nativeToCot) > 0 }

// addWithRef records the key of a line's `with` option, which is checked as a
// `requires` key is, in the same order of errors (0.18 ruling 5).
func (p *Pack) addWithRef(f *Field) {
	if f.WithLine {
		p.keyRefs = append(p.keyRefs, keyRef{key: f.With, locator: f.Locator, line: f.Line, req: true})
	}
}

// addRequires records the keys of a `requires` line for the load checks.
func (p *Pack) addRequires(terms []*reqTerm, line int) {
	var eq []*reqTerm
	for _, t := range terms {
		r := keyRef{key: t.key, line: line, req: true}
		if t.eq {
			r.term = t
			eq = append(eq, t)
		}
		p.keyRefs = append(p.keyRefs, r)
	}
	if len(eq) > 0 {
		p.valueChecks = append(p.valueChecks, valueCheck{line: line, terms: eq})
	}
}

// holdsKey reports whether a record holds a key for `with` (0.18 ruling 2): a
// scalar that is present, whatever its value, or a list with at least one
// item.
func holdsKey(rec *Item, key string) bool {
	if _, ok := rec.Fields[key]; ok {
		return true
	}
	return len(rec.Lists[key]) > 0
}

// suppressed reports whether the line's `with` key is missing from the record
// being encoded: the line is then absent everywhere, its default and its
// sentinel included (0.18 ruling 1).
func (f *Field) suppressed(rec *Item) bool {
	return f.WithLine && !holdsKey(rec, f.With)
}

// has reports whether an encode of the record writes the line from a present
// key: the record holds the key and the line is not suppressed by `with`.
func (f *Field) has(rec *Item) bool {
	if f.suppressed(rec) {
		return false
	}
	_, ok := rec.Fields[f.Key]
	return ok
}

// ParsePackFile reads and parses one pack.def.
func ParsePackFile(path string) (*Pack, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, &Error{Kind: ErrBadDirective, Source: path, Detail: err.Error()}
	}
	return ParsePack(b, path)
}

// parseFieldOptions reads what follows the transform on a `field` line:
// `via <table>`, `swap`, `trim`, `optional`, in any order, each at most once.
func parseFieldOptions(f *Field, opts []string) error {
	seen := map[string]bool{}
	for i := 0; i < len(opts); i++ {
		o := opts[i]
		if seen[o] {
			return fmt.Errorf("field option %q repeated", o)
		}
		seen[o] = true
		switch o {
		case "via":
			i++
			if i >= len(opts) || opts[i] == "" {
				return fmt.Errorf("`via` needs a table name")
			}
			f.Via = opts[i]
		case "absent":
			// The token after `absent` is always its argument (0.9 ruling 11).
			i++
			if i >= len(opts) {
				return fmt.Errorf("`absent` needs one or more values separated by commas")
			}
			vals, err := splitAbsent(opts[i])
			if err != nil {
				return err
			}
			f.Absent = vals
		case "with":
			// with <other-key> (0.18): the token after `with` is its key.
			i++
			if i >= len(opts) || opts[i] == "" {
				return fmt.Errorf("`with` needs a model key")
			}
			f.With, f.WithLine = opts[i], true
		case "stop":
			// stop <code> (0.22): the token after `stop` is its code. A
			// missing code is a line check; the code's form and range are
			// checked after the file (rulings 23 and 28).
			i++
			if i >= len(opts) {
				return fmt.Errorf("`stop` needs a code")
			}
			f.Stop, f.StopLine = opts[i], true
		case "swap":
			f.Swap = true
		case "trim":
			f.Trim = true
		case "optional":
			f.Optional = true
		case "unlisted":
			f.Unlisted = true
		default:
			return fmt.Errorf("unknown field option %q (via <table>, swap, trim, optional, absent <values>, with <key>, stop <code>, unlisted)", o)
		}
	}
	return nil
}

// checkFieldOptions refuses an option on a wire or a transform it does not
// apply to.
func checkFieldOptions(wire string, f *Field) error {
	// `stop` is an option of a fixed-size `chars` field; `until:` takes no
	// `stop`, `absent`, `swap` or `trim` (0.22, ruling 16).
	if f.StopLine && (wire != WireBits || !strings.HasPrefix(f.Transform, "chars:")) {
		return fmt.Errorf("`stop` is valid only with a chars transform on wire bits, not %s", f.Transform)
	}
	if f.until {
		for _, o := range []struct {
			set  bool
			name string
		}{{f.StopLine, "stop"}, {f.Absent != nil, "absent"}, {f.Swap, "swap"}, {f.Trim, "trim"}} {
			if o.set {
				return fmt.Errorf("field option `%s` is not valid with an until: locator", o.name)
			}
		}
	}
	if wire != WireBits {
		for _, o := range []struct {
			set  bool
			name string
		}{{f.Swap, "swap"}, {f.Trim, "trim"}, {f.Optional, "optional"}} {
			if o.set {
				return fmt.Errorf("field option `%s` is valid only on wire bits", o.name)
			}
		}
		return nil
	}
	if f.Swap && f.loc.blen%8 != 0 {
		return fmt.Errorf("`swap` needs a length that is a multiple of 8 bits, got %d", f.loc.blen)
	}
	if f.Swap && f.Transform == "sixbit" {
		return fmt.Errorf("`swap` is not valid with the sixbit transform")
	}
	if f.Swap && f.btf != nil && f.btf.noSwap {
		return fmt.Errorf("`swap` is not valid with the %s transform", f.Transform)
	}
	// trim with a transform of 0.15 is bad-directive (0.15 ruling 18).
	if f.Trim && f.Transform != "ascii" && f.Transform != "sixbit" {
		return fmt.Errorf("`trim` is valid only with the ascii or sixbit transform, not %s", f.Transform)
	}
	return nil
}

// isIntText reports whether s is a decimal integer that fits 64 bits.
func isIntText(s string) bool {
	_, err := parseIntText(s)
	return err == nil
}

// ParsePack parses pack.def text. source names it in errors.
func ParsePack(text []byte, source string) (*Pack, error) {
	p := &Pack{Source: source, nativeToCot: map[string]string{}, cotToNative: map[string]string{}, tables: map[string]*valueTable{}}
	perr := func(kind ErrorKind, line int, loc, format string, a ...any) error {
		return &Error{Kind: kind, Format: p.Format, Locator: loc, Source: source, Line: line, Detail: fmt.Sprintf(format, a...)}
	}
	if !utf8.Valid(text) {
		return nil, perr(ErrBadDirective, 0, "", "pack.def is not valid UTF-8")
	}
	type tmLine struct {
		native, cot string
		line        int
	}
	var tms []tmLine
	var whens []*When // when and const lines, in file order
	var firstWhen *When
	var cur *KindDef
	var open []*Group // the group blocks not yet closed, outermost first
	var gates []*Gate // the gate blocks not yet closed, outermost first (inside the innermost open group)
	topGate := func() *Gate {
		if len(gates) == 0 {
			return nil
		}
		return gates[len(gates)-1]
	}
	kindNames := map[string]int{}
	seen := map[string]int{}
	firstNeedsWire := 0 // the first line that must follow the wire line
	// late holds the first failure a line shows that is not a line check;
	// it is reported after the file (ruling 5b of 0.11).
	var late error
	// `armor` lines, checked after the file is read (spec 0.14).
	var armorLines []int
	armorValue, armorAfterKind, firstKind := "", 0, 0
	// `encoding` lines, checked after the file is read (spec 0.19).
	var encLines []int
	encValue, encAfterKind := "", 0
	// `framing` lines, checked after the file is read (spec 0.92).
	var framingLines []int
	framingValue := ""
	// The argument count of each directive; a negative count is a minimum.
	want := map[string]int{"format": 1, "version": 1, "wire": 1, "root": 1, "word_bytes": 1, "bit_order": 1, "field": -3, "typemap": 2,
		"distribution": 1, "source": 1, "uses": 1, "kind": 1, "when": 2, "requires": -1, "const": 2, "default": 2, "map": 3, "group": -2, "end": 0,
		"layout": 1, "delimiter": 1, "start": 1, "checksum": -1, "tag": 1, "key": 1, "pad": 1, "align": 1, "presence": 2, "if": -1, "opt": 0, "chain": 0, "fx": 0, "length": -1, "also": -1, "armor": 1,
		"element": 1, "encoding": 1, "ext": 0, "choice": -1, "alt": 1, "switch": 1, "case": 1, "else": 0, "count": -2,
		"inner": -1, "framing": 1, "charset": -2}
	// A pack is sequential when it has a `layout sequential` line, wherever
	// the line stands.
	p.seq = hasSequentialLayout(text)
	sp := &seqParser{p: p, perr: perr}
	sp.init()
	// addLine puts a line in the innermost open group, else in the kind being
	// read, else among the common lines.
	addLine := func(ln line) {
		ln.in = topGate()
		switch {
		case len(open) > 0:
			g := open[len(open)-1]
			g.lines = append(g.lines, ln)
		case cur != nil:
			cur.lines = append(cur.lines, ln)
		default:
			p.common = append(p.common, ln)
		}
	}
	inner := func() *Group {
		if len(open) == 0 {
			return nil
		}
		return open[len(open)-1]
	}
	sc := bufio.NewScanner(bytes.NewReader(text))
	sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
	n := 0
	for sc.Scan() {
		n++
		// The line checks of ruling 5b of 0.11, in order: the quote, the
		// directive, the number of arguments, the wire line before the lines
		// that need it; the others as each directive is read below.
		toks, err := tokenize(sc.Text())
		if err != nil {
			return nil, perr(ErrUnterminatedQuote, n, "", "%v", err)
		}
		if len(toks) == 0 {
			continue
		}
		kw, args := toks[0], toks[1:]
		w, known := want[kw]
		if !known {
			return nil, perr(ErrUnknownDirective, n, "", "unknown directive %q", kw)
		}
		// `key` in a pack is unknown-directive (ruling 5 of 0.11); 0.13 adds
		// the one-argument `key <hex>` of the tlv wire, so a `key` line of
		// another argument count, the form of a model module, stays
		// unknown-directive (provisional reading, load vector 445).
		if kw == "key" && len(args) != 1 {
			return nil, perr(ErrUnknownDirective, n, "", "key with %d argument(s) is a model-module directive; a pack has only `key <hex>` (wire tlv)", len(args))
		}
		if w < 0 && len(args) < -w {
			return nil, perr(ErrBadDirective, n, "", "%s takes at least %d argument(s), got %d", kw, -w, len(args))
		}
		if kw == "choice" && len(args) > 2 {
			// `choice <n> [ext]` (spec 0.19): one or two arguments.
			return nil, perr(ErrBadDirective, n, "", "choice takes 1 or 2 arguments, got %d", len(args))
		}
		if kw == "inner" && len(args) > 2 {
			// `inner <format> [partial]` (spec 0.34): one or two arguments.
			return nil, perr(ErrBadDirective, n, "", "inner takes 1 or 2 arguments, got %d", len(args))
		}
		if kw == "charset" && len(args) > 3 {
			// `charset <name> <characters> [<width>]` (0.46).
			return nil, perr(ErrBadDirective, n, "", "charset takes 2 or 3 arguments, got %d", len(args))
		}
		// `when … as <model-key>` (0.30): a line whose third token is `as`
		// passes the argument count; its syntax, and `as` outside a
		// sequential pack, are checked after the file (ruling 16).
		whenAs := kw == "when" && len(args) >= 3 && args[2] == "as"
		// `when … at <n>` (0.33): the same, its errors reported after the
		// key and value checks (ruling 10).
		whenAt := kw == "when" && len(args) >= 3 && args[2] == "at"
		// `const <locator> part:<sep>:<n> <text>` (0.64 ruling 23).
		constPart := kw == "const" && len(args) == 3 && isPartName(args[1])
		if w >= 0 && len(args) != w && !constPart && !whenAs && !whenAt {
			return nil, perr(ErrBadDirective, n, "", "%s takes %d argument(s), got %d", kw, w, len(args))
		}
		if needsWire[kw] {
			if _, has := seen["wire"]; !has {
				return nil, perr(ErrMissingWire, n, "", "%s stands before the wire line", kw)
			}
			if kw == "layout" && args[0] == "sequential" && firstNeedsWire != 0 {
				return nil, perr(ErrBadDirective, n, "", "layout sequential stands after line %d, which it must precede", firstNeedsWire)
			}
			if firstNeedsWire == 0 {
				firstNeedsWire = n
			}
		}
		if kw == "kind" && firstKind == 0 {
			firstKind = n
		}
		if kw == "framing" {
			// A header line of a sequential pack: outside every block and
			// before the first kind, checked after the file (0.92 ruling 16).
			if late == nil {
				switch {
				case len(open) > 0 || len(gates) > 0 || len(sp.stack) > 1:
					late = perr(ErrBadDirective, n, "", "framing is not allowed inside a block")
				case len(p.Kinds) > 0:
					late = perr(ErrBadDirective, n, "", "framing stands before the first kind (line %d)", p.Kinds[0].Line)
				}
			}
			framingLines = append(framingLines, n)
			if len(framingLines) == 1 {
				framingValue = args[0]
			}
			continue
		}
		if kw == "charset" {
			// Before the first message kind, outside every block; like every
			// other error of the line, checked after the file (0.46, rulings
			// 15 and 16).
			switch {
			case len(open) > 0 || len(gates) > 0 || len(sp.stack) > 1:
				if late == nil {
					late = perr(ErrBadDirective, n, "", "charset is not allowed inside a block")
				}
			case len(p.Kinds) > 0:
				if late == nil {
					late = perr(ErrBadDirective, n, "", "charset stands before the first kind (line %d)", p.Kinds[0].Line)
				}
			}
			p.charsetLines = append(p.charsetLines, newPackCharset(args, n))
			continue
		}
		if p.seq {
			if seqStructural[kw] {
				if constPart {
					if _, err := parsePart(args[1]); err != nil {
						return nil, perr(ErrBadDirective, n, args[0], "%v", err)
					}
					if late == nil {
						late = perr(ErrBadDirective, n, args[0], "const … part is not valid on wire bits")
					}
					args = args[:2]
				}
				if err := sp.line(kw, args, n); err != nil {
					return nil, err
				}
				continue
			}
			// Header and table directives stand outside every block (0.8
			// ruling 24).
			if len(sp.stack) > 1 {
				return nil, perr(ErrBadDirective, n, "", "%s is not allowed inside a block (opened on line %d)", kw, sp.top().line)
			}
		} else if uperDirective[kw] {
			// `ext`, `choice` and `alt` outside a sequential pack: directives
			// of the language on every wire, bad-directive outside a UPER pack
			// after the file is read (0.19 ruling 21).
			if late == nil {
				late = perr(ErrBadDirective, n, "", "%s is valid only in a pack with encoding uper", kw)
			}
			continue
		} else if kw == "inner" {
			// `inner` outside a sequential bits pack is bad-directive after the
			// file (spec 0.34, "The inner line").
			if late == nil {
				late = perr(ErrBadDirective, n, "", "inner is valid only in a pack on wire bits with layout sequential")
			}
			continue
		} else if unitsForm(kw, args) {
			// `length @<name> units <u>` on a fixed layout or another wire,
			// after the file (0.83 ruling 13).
			if late == nil {
				late = perr(ErrBadDirective, n, "", "length @<name> units <u> is valid only in a pack with `layout sequential`")
			}
			continue
		} else if seqOnly[kw] && kw != "if" && !(kw == "length" && len(args) == 1) {
			// `if` outside a sequential layout opens a gate block (0.17);
			// `length` with one argument is a tlv directive (0.13).
			// Not among the line checks of ruling 5b of 0.11, so reported after
			// the file (0.64 ruling 11 for `also` after a part line).
			if late == nil {
				late = perr(ErrBadDirective, n, "", "%s is valid only in a pack with `layout sequential`", kw)
			}
			continue
		}
		if g := topGate(); g != nil {
			// Inside a gate block only these lines are allowed (0.17, Load
			// errors). The refusal is a check after the file (0.17 ruling
			// 13); the line is not read further.
			switch kw {
			case "field", "const", "default", "if", "end":
			default:
				if late == nil {
					late = perr(ErrBadDirective, n, "", "%s is not allowed inside a gate block (line %d)", kw, g.Line)
				}
				continue
			}
		}
		if len(open) > 0 {
			// Inside a group only these lines are allowed: `when`, `requires`,
			// `root` and `kind` are not, and tables are pack-wide and written
			// outside groups (0.7 ruling 9).
			switch kw {
			case "field", "const", "default", "group", "end", "if":
			default:
				return nil, perr(ErrBadDirective, n, "", "%s is not allowed inside a group (group %s, line %d)", kw, inner().List, inner().Line)
			}
		}
		switch kw {
		case "encoding":
			encLines = append(encLines, n)
			if len(encLines) == 1 {
				encValue = args[0]
				if firstKind != 0 {
					encAfterKind = n
				}
			}
		case "armor":
			armorLines = append(armorLines, n)
			// Its one argument was counted as the line was read (ruling 13
			// of 0.14); its value and its fit are checked after the file.
			if len(armorLines) == 1 {
				armorValue = args[0]
				if firstKind != 0 {
					armorAfterKind = n
				}
			}
		case "tag", "key", "length":
			// `length` with one argument outside a sequential pack (0.13).
			p.tlvDirective(kw, args, n)
		case "checksum":
			// One argument, or two whose first is sum16 or crc32, passes
			// as the line is read; any other count is refused here (ruling
			// 12 of 0.13, ruling 2 of 0.27).
			if len(args) > 2 || len(args) == 2 && args[0] != "sum16" && args[0] != "crc32" {
				return nil, perr(ErrBadDirective, n, "", "checksum takes one argument (none, nmea) or `sum16 <tag>` or `crc32 <tag>`, got %d", len(args))
			}
			if args[0] == "sum16" || args[0] == "crc32" {
				p.tlvDirective(kw, args, n)
				continue
			}
			if err := p.textDirective(kw, args[0], n); err != nil {
				return nil, perr(ErrBadDirective, n, "", "%v", err)
			}
		case "delimiter", "start":
			if err := p.textDirective(kw, args[0], n); err != nil {
				return nil, perr(ErrBadDirective, n, "", "%v", err)
			}
		case "if":
			// if [!]<word>:<pos>:<len> <value>[,<value>…] (0.17)
			// An `if` with no argument was refused by the argument count
			// (5b step 3); every other gate error is a check after the file
			// (0.17 ruling 13). A gate that does not parse still opens a
			// block, so that its `end` closes it.
			g, err := parseGate(args, n)
			if err != nil {
				if late == nil {
					late = perr(ErrBadDirective, n, "", "%v", err)
				}
				g = &Gate{Line: n, Locator: args[0]}
			}
			g.parent, g.group = topGate(), inner()
			p.gates = append(p.gates, g)
			addLine(line{gt: g})
			gates = append(gates, g)
		case "group":
			// group <list> <locator> [item <bits>] [count <count-locator> | count <n>]
			g := &Group{List: args[0], Locator: args[1], Line: n, parent: inner()}
			// `count @<a> @<b>` outside a sequential pack (0.31): on
			// protobuf the locator `count` stays bad-locator at its own
			// step; elsewhere the form is bad-directive after the file
			// (ruling 7).
			if twoCountForm(args) {
				if p.lineWire(g.parent != nil) == WireProtobuf {
					if err := p.checkGroupLocator(g.Locator, g.parent != nil); err != nil {
						return nil, perr(ErrBadLocator, n, g.Locator, "%v", err)
					}
				}
				if late == nil {
					late = perr(ErrBadDirective, n, g.Locator, "group … count @<a> @<b> is valid only in a pack with `layout sequential`")
				}
				args = args[:2]
			}
			for i := 2; i < len(args); i += 2 {
				if i+1 >= len(args) {
					return nil, perr(ErrBadDirective, n, g.Locator, "group: `%s` needs a value", args[i])
				}
				switch {
				case args[i] == "item" && !g.hasItem:
					g.hasItem, g.itemText = true, args[i+1]
				case args[i] == "count" && !g.hasCount:
					g.hasCount, g.countText = true, args[i+1]
				default:
					return nil, perr(ErrBadDirective, n, g.Locator, "group: unknown or repeated word %q (item <bits>, count <count-locator | n>)", args[i])
				}
			}
			// `rest` and `last` as the group locator of a protobuf pack are
			// bad-directive, checked after the file; every other locator
			// form keeps ruling 5a of 0.11 (0.21 rulings 37 and 44).
			if !p.seq && p.lineWire(g.parent != nil) == WireProtobuf && (g.Locator == "rest" || g.Locator == "last") {
				if late == nil {
					late = perr(ErrBadDirective, n, g.Locator, "group: %q is a sequential list form, not a protobuf path", g.Locator)
				}
			} else if err := p.checkGroupLocator(g.Locator, g.parent != nil); err != nil {
				return nil, perr(ErrBadLocator, n, g.Locator, "%v", err)
			}
			p.Groups = append(p.Groups, g)
			p.keyRefs = append(p.keyRefs, keyRef{key: g.List, locator: g.Locator, line: n, group: g})
			addLine(line{g: g})
			open = append(open, g)
		case "end":
			if len(gates) > 0 {
				gates = gates[:len(gates)-1]
				continue
			}
			if len(open) == 0 {
				if late == nil {
					late = perr(ErrBadDirective, n, "", "end with no open group")
				}
				continue
			}
			open = open[:len(open)-1]
		case "root":
			// Inside a kind, `root` is that kind's root element (xml).
			if cur != nil {
				if cur.Root != "" {
					return nil, perr(ErrBadDirective, n, "", "root repeated in kind %s (first on line %d)", cur.Name, cur.rootLine)
				}
				if args[0] == "" {
					return nil, perr(ErrBadDirective, n, "", "root needs an element name")
				}
				cur.Root, cur.rootLine = args[0], n
				continue
			}
			if prev, dup := seen[kw]; dup {
				return nil, perr(ErrBadDirective, n, "", "%s repeated (first on line %d)", kw, prev)
			}
			seen[kw] = n
			p.Root = args[0]
		case "format", "version", "wire", "word_bytes", "bit_order", "distribution", "layout":
			if prev, dup := seen[kw]; dup {
				return nil, perr(ErrBadDirective, n, "", "%s repeated (first on line %d)", kw, prev)
			}
			seen[kw] = n
			switch kw {
			case "format":
				p.Format = args[0]
			case "version":
				p.Version = args[0]
			case "wire":
				switch args[0] {
				case WireXML, WireGeoJSON, WireBits, WireProtobuf, WireJSON, WireText, WireTLV, WireCBOR:
				default:
					return nil, perr(ErrUnknownWire, n, "", "unknown wire %q (want xml, geojson, json, bits, protobuf, text, tlv or cbor)", args[0])
				}
				// A wire of the specification this build lacks is
				// unknown-wire at the same line check (ruling 1c of 0.24).
				if codecs[args[0]] == nil {
					return nil, perr(ErrUnknownWire, n, "", "%s", missingWireDetail(args[0]))
				}
				p.Wire = args[0]
			case "layout":
				if args[0] != "sequential" && args[0] != "fixed" {
					return nil, perr(ErrBadDirective, n, "", "layout must be fixed or sequential, got %q", args[0])
				}
			case "word_bytes":
				wb, err := parseSmallUint(args[0])
				if err != nil || wb <= 0 {
					return nil, perr(ErrBadDirective, n, "", "word_bytes must be a positive integer, got %q", args[0])
				}
				p.WordBytes = wb
			case "bit_order":
				if args[0] != "lsb" && args[0] != "msb" && args[0] != "msb-lsb" {
					return nil, perr(ErrBadDirective, n, "", "bit_order must be lsb, msb or msb-lsb, got %q", args[0])
				}
				p.BitOrder = args[0]
			case "distribution":
				if !validDistribution(args[0]) {
					return nil, perr(ErrBadDirective, n, "", "distribution must be public or controlled, got %q", args[0])
				}
				p.Distribution = args[0]
			}
		case "source":
			p.Sources = append(p.Sources, args[0])
		case "uses":
			if args[0] == "" || strings.Contains(args[0], ".") {
				return nil, perr(ErrBadDirective, n, "", "module name %q must be non-empty and contain no '.'", args[0])
			}
			p.Uses = append(p.Uses, args[0])
		case "kind":
			if prev, dup := kindNames[args[0]]; dup && late == nil {
				late = perr(ErrDuplicateKind, n, "", "kind %q already declared on line %d", args[0], prev)
			}
			kindNames[args[0]] = n
			cur = &KindDef{Name: args[0], Line: n}
			p.Kinds = append(p.Kinds, cur)
		case "requires":
			if cur == nil {
				return nil, perr(ErrBadDirective, n, "", "requires before the first kind line")
			}
			terms, err := parseRequires(args, n)
			if err != nil {
				return nil, perr(ErrBadDirective, n, "", "%v", err)
			}
			p.addRequires(terms, n)
			for _, t := range terms {
				cur.Requires = append(cur.Requires, t.key)
			}
			cur.reqs = append(cur.reqs, terms...)
		case "field":
			f := &Field{Key: args[0], Locator: args[1], Transform: args[2], Line: n, group: inner(), gate: topGate()}
			if kind, err := p.checkFieldLine(f, args[3:], f.group != nil); err != nil {
				return nil, perr(kind, n, f.Locator, "%v", err)
			}
			p.Fields = append(p.Fields, f)
			p.keyRefs = append(p.keyRefs, keyRef{key: f.Key, locator: f.Locator, line: n, field: f})
			p.addWithRef(f)
			addLine(line{f: f})
		case "when", "const":
			if whenAt || whenAs && whenHoldsAt(args[2:]) {
				// `as k at 0` is the late `at` error too (0.52 ruling 17).
				p.atLater(perr(ErrBadDirective, n, "", "when … at is valid only in a pack with `layout sequential`"))
				args = args[:2]
			} else if whenAs {
				if late == nil {
					late = perr(ErrBadDirective, n, "", "when … as is valid only in a pack with `layout sequential`")
				}
				args = args[:2]
			}
			w := &When{Locator: args[0], Value: args[1], Line: n, Const: kw == "const", group: inner(), gate: topGate()}
			if constPart {
				// The parameters are a line check on every wire (0.64
				// rulings 11 and 23).
				ps, err := parsePart(args[1])
				if err != nil {
					return nil, perr(ErrBadDirective, n, w.Locator, "%v", err)
				}
				w.part, w.Value = ps, args[2]
			}
			if kind, err := p.checkWhenLine(w.Locator, w.group != nil); err != nil {
				return nil, perr(kind, n, w.Locator, "%v", err)
			}
			whens = append(whens, w)
			if !w.Const && firstWhen == nil {
				firstWhen = w
			}
			addLine(line{w: w})
			if !w.Const {
				if cur == nil {
					p.commonWhens = append(p.commonWhens, w)
				} else {
					cur.whens = append(cur.whens, w)
				}
			}
		case "default":
			d := &Default{Key: args[0], Value: args[1], Line: n}
			p.keyRefs = append(p.keyRefs, keyRef{key: d.Key, line: n, def: d})
			switch {
			case topGate() != nil:
				g := topGate()
				g.defaults = append(g.defaults, d)
				if g.defs == nil {
					g.defs = map[string]*Default{}
				}
				g.defs[d.Key] = d
			case len(open) > 0:
				g := inner()
				g.defaults = append(g.defaults, d)
			case cur == nil:
				p.commonDefaults = append(p.commonDefaults, d)
			default:
				cur.defaults = append(cur.defaults, d)
			}
		case "element":
			el := &Element{Path: args[0], Line: n}
			p.elements = append(p.elements, el)
			addLine(line{el: el})
		case "map":
			t := p.tables[args[0]]
			if t == nil {
				t = &valueTable{name: args[0]}
				p.tables[args[0]] = t
			}
			t.entries = append(t.entries, mapEntry{native: args[1], model: args[2], line: n})
		case "typemap":
			tms = append(tms, tmLine{args[0], args[1], n})
		}
	}
	if err := sc.Err(); err != nil {
		return nil, perr(ErrBadDirective, n, "", "%v", err)
	}
	// After the file: missing-format, missing-version, missing-wire, then the
	// checks that need the whole file, then the order of 0.4 from
	// missing-distribution on (ruling 5b of 0.11).
	if p.Format == "" {
		return nil, perr(ErrMissingFormat, 0, "", "pack has no format line")
	}
	if p.Version == "" {
		return nil, perr(ErrMissingVersion, 0, "", "pack has no version line")
	}
	if p.Wire == "" {
		return nil, perr(ErrMissingWire, 0, "", "pack has no wire line")
	}
	if late == nil {
		late = sp.late
	}
	if late != nil {
		return nil, late
	}
	// The charset lines of 0.46, whose width needs the wire.
	if ln, err := p.resolveCharsets(); err != nil {
		return nil, perr(ErrBadDirective, ln, "", "%v", err)
	}
	// The bans of 0.30 ruling 9 need only key names: they run first among
	// the checks that need the whole file (rulings 16 and 29).
	if p.seq {
		if err := sp.asBans(); err != nil {
			return nil, err
		}
	}
	if g := topGate(); g != nil {
		return nil, perr(ErrBadDirective, g.Line, g.Locator, "the gate block has no end")
	}
	if g := inner(); g != nil {
		return nil, perr(ErrBadDirective, g.Line, g.Locator, "group %s has no end", g.List)
	}
	if p.seq {
		if err := sp.finish(); err != nil {
			return nil, err
		}
		// `layout` on a wire other than bits, and `word_bytes` in a
		// sequential pack (0.8 ruling 14).
		if p.Wire != "" && p.Wire != WireBits {
			return nil, perr(ErrBadDirective, seen["layout"], "", "layout sequential is valid only on wire bits")
		}
		if p.WordBytes != 0 {
			return nil, perr(ErrBadDirective, seen["word_bytes"], "", "word_bytes is not used in a pack with layout sequential")
		}
	} else if _, has := seen["layout"]; has && p.Wire != "" && p.Wire != WireBits {
		return nil, perr(ErrBadDirective, seen["layout"], "", "layout is valid only on wire bits")
	}
	for _, t := range p.tables {
		allInt, allNum := true, true
		for _, e := range t.entries {
			if !isIntText(e.model) {
				allInt = false
			}
			// Read as written, without trimming (0.18 ruling 18).
			if _, err := readAs(e.model, KindFloat); err != nil {
				allNum = false
			}
		}
		switch {
		case allInt:
			t.modelType = KindInt
		case allNum:
			t.modelType = KindFloat
		default:
			t.modelType = KindString
		}
	}

	// The checks that need the whole file run before missing-distribution
	// (0.5 ruling 25): a `when` with no `kind`, `bit_order` on another wire, a
	// length a transform does not allow, a `when` value that does not fit, and
	// the bad-directive causes of 0.6 (an option on a wire or transform it
	// does not apply to, `via` naming a table with no `map` line, a kind's
	// `root` on a wire other than xml). A failure of another kind found on the
	// way (a bad locator, an unknown transform) is reported in its 0.4 place,
	// after the missing-distribution and missing-source checks.
	// Every failure after the file is reported as it is found: the line
	// checks have refused the unknown transforms and the locator forms
	// (ruling 5b of 0.11).
	note := func(err error) error { return err }
	// The text directives on another wire, and their relations to one
	// another (0.10 rulings 2 and 10).
	if ln, err := p.checkTextDirectives(); err != nil {
		return nil, perr(ErrBadDirective, ln, "", "%v", err)
	}
	// The tlv directives, on another wire and with their values (0.13).
	if ln, err := p.checkTLVDirectives(); err != nil {
		return nil, perr(ErrBadDirective, ln, "", "%v", err)
	}
	if len(p.elements) > 0 && p.Wire != "" && p.Wire != WireXML {
		return nil, perr(ErrBadDirective, p.elements[0].Line, p.elements[0].Path, "element is valid only on wire xml")
	}
	for _, el := range p.elements {
		// A path of element names under the root (0.18 ruling 13).
		names := strings.Split(el.Path, "/")
		for _, e := range names {
			if e == "" || strings.ContainsAny(e, "@#") {
				return nil, perr(ErrBadDirective, el.Line, el.Path, "element takes a path of element names under the root (a, a/b), got %q", el.Path)
			}
		}
		el.path = names
	}
	if len(p.gates) > 0 && p.Wire != "" && p.Wire != WireBits {
		return nil, perr(ErrBadDirective, p.gates[0].Line, p.gates[0].Locator, "a gate block is valid only on wire bits")
	}
	if firstWhen != nil && !p.HasKinds() {
		return nil, perr(ErrBadDirective, firstWhen.Line, firstWhen.Locator, "a when line needs a pack with a kind line")
	}
	if p.Wire != "" && p.Wire != WireBits && p.BitOrder != "" {
		return nil, perr(ErrBadDirective, seen["bit_order"], "", "bit_order is valid only on wire bits")
	}
	if p.Wire == WireBits && p.BitOrder == "" {
		p.BitOrder = "lsb"
	}
	switch p.BitOrder {
	case "msb":
		p.msb = msbOrder
	case "msb-lsb":
		p.msb = msbLsbOrder
	default:
		p.msb = lsbOrder
	}
	// `armor` (spec 0.14): on the bits wire, at most once, before the first
	// kind, hex or sixbit; sixbit needs bit_order msb and refuses
	// `length … whole`.
	if len(armorLines) > 0 {
		first := armorLines[0]
		switch {
		case len(armorLines) > 1:
			return nil, perr(ErrBadDirective, armorLines[1], "", "armor repeated (first on line %d)", first)
		case p.Wire != WireBits:
			return nil, perr(ErrBadDirective, first, "", "armor is valid only on wire bits")
		case armorAfterKind != 0:
			return nil, perr(ErrBadDirective, first, "", "armor stands before the first kind (line %d)", firstKind)
		case armorValue != "hex" && armorValue != "sixbit":
			return nil, perr(ErrBadDirective, first, "", "armor must be hex or sixbit, got %q", armorValue)
		case armorValue == "sixbit" && p.BitOrder != "msb":
			return nil, perr(ErrBadDirective, first, "", "armor sixbit needs bit_order msb")
		case armorValue == "sixbit" && p.wholeLine != 0:
			return nil, perr(ErrBadDirective, p.wholeLine, "", "length … whole is not valid with armor sixbit: the text has no whole-byte length")
		}
		p.sixbitArmor = armorValue == "sixbit"
	}
	// `encoding` (spec 0.19): on the bits wire, at most once, before the
	// first kind, none or uper; uper needs layout sequential and bit_order
	// msb, and refuses armor sixbit (rulings 11 and 18).
	if len(encLines) > 0 {
		first := encLines[0]
		switch {
		case len(encLines) > 1:
			return nil, perr(ErrBadDirective, encLines[1], "", "encoding repeated (first on line %d)", first)
		case p.Wire != WireBits:
			return nil, perr(ErrBadDirective, first, "", "encoding is valid only on wire bits")
		case encAfterKind != 0:
			return nil, perr(ErrBadDirective, first, "", "encoding stands before the first kind (line %d)", firstKind)
		case encValue != "none" && encValue != "uper":
			return nil, perr(ErrBadDirective, first, "", "encoding must be none or uper, got %q", encValue)
		case encValue == "uper" && !p.seq:
			return nil, perr(ErrBadDirective, first, "", "encoding uper needs layout sequential")
		case encValue == "uper" && p.BitOrder != "msb":
			return nil, perr(ErrBadDirective, first, "", "encoding uper needs bit_order msb")
		case encValue == "uper" && p.sixbitArmor:
			return nil, perr(ErrBadDirective, first, "", "encoding uper is not valid with armor sixbit")
		}
		p.uper = encValue == "uper"
	}
	// `framing self` (spec 0.92 ruling 16).
	if len(framingLines) > 0 {
		first := framingLines[0]
		switch {
		case len(framingLines) > 1:
			return nil, perr(ErrBadDirective, framingLines[1], "", "framing repeated (first on line %d)", first)
		case framingValue != "self":
			return nil, perr(ErrBadDirective, first, "", "framing must be self, got %q", framingValue)
		case p.Wire != WireBits || !p.seq:
			return nil, perr(ErrBadDirective, first, "", "framing is valid only on wire bits with layout sequential")
		case p.sixbitArmor || p.uper:
			return nil, perr(ErrBadDirective, first, "", "framing is not valid with armor sixbit or encoding uper")
		}
		p.framing = true
		if err := sp.checkFraming(); err != nil {
			return nil, err
		}
	}
	// `inner` in a pack with `armor sixbit` or `encoding uper` (spec 0.34);
	// `armor hex`, the default, loads.
	if p.innerLine != 0 && (p.sixbitArmor || p.uper) {
		return nil, perr(ErrBadDirective, p.innerLine, "", "inner is not valid in a pack with armor sixbit or encoding uper")
	}
	// ext, choice, alt and group … size outside a UPER pack (0.19 ruling 9).
	if !p.uper && p.uperLine != 0 {
		return nil, perr(ErrBadDirective, p.uperLine, "", "ext, choice, alt and group … size are valid only in a pack with encoding uper")
	}
	if err := p.checkPartLines(whens, perr); err != nil {
		return nil, err
	}
	hasType := false
	if g, prev := p.listMappedTwice(); g != nil {
		return nil, perr(ErrBadDirective, g.Line, g.Locator, "list %s is already mapped by the group on line %d of the same scope", g.List, prev.Line)
	}
	if p.Wire != "" {
		if p.Wire != WireXML {
			for _, k := range p.Kinds {
				if k.Root != "" {
					return nil, perr(ErrBadDirective, k.rootLine, "", "root in a kind is xml only")
				}
			}
		}
		if p.Wire == WireText {
			if err := p.resolveText(whens, perr, note); err != nil {
				return nil, err
			}
			for _, f := range p.Fields {
				if f.Key == "type" {
					hasType = true
				}
			}
		} else if p.Wire == WireTLV {
			if err := p.resolveTLV(whens, perr); err != nil {
				return nil, err
			}
			for _, f := range p.Fields {
				if f.Key == "type" {
					hasType = true
				}
			}
		} else if p.Wire == WireCBOR {
			if err := p.resolveCBOR(whens, perr); err != nil {
				return nil, err
			}
			for _, f := range p.Fields {
				if f.Key == "type" {
					hasType = true
				}
			}
		} else {
			for _, g := range p.Groups {
				if kind, err := p.resolveGroup(g); err != nil {
					if err := note(perr(kind, g.Line, g.Locator, "%v", err)); err != nil {
						return nil, err
					}
				}
			}
			// Inside a group of a geojson pack the locators are those of the json
			// wire; `.` is the item itself, on json, geojson and protobuf.
			innerWire := func(g *Group) string {
				if g != nil && p.Wire == WireGeoJSON {
					return WireJSON
				}
				return p.Wire
			}
			dotWire := p.Wire == WireJSON || p.Wire == WireGeoJSON || p.Wire == WireProtobuf
			for _, f := range p.Fields {
				if f.Key == "type" {
					hasType = true
				}
				var loc locator
				var err error
				if p.Wire == WireBits && isUperLocator(f.Locator) {
					// A UPER locator (spec 0.19), valid only in a UPER pack
					// (ruling 9).
					if !p.uper {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "the locator %s is valid only in a pack with encoding uper", f.Locator)
					}
					// `absent` on a UPER locator: its bits depend on the value,
					// so 0.9's raw value is not stated (0.19 ruling 22).
					if f.Absent != nil {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "field option `absent` is not valid on the UPER locator %s", f.Locator)
					}
					if kind, err := resolveUperField(f); err != nil {
						if err := note(perr(kind, f.Line, f.Locator, "%v", err)); err != nil {
							return nil, err
						}
						continue
					}
					f.yields, _ = transformYields(f.Transform)
					if f.Via != "" {
						f.table = p.tables[f.Via]
						if f.table == nil {
							return nil, perr(ErrBadDirective, f.Line, f.Locator, "`via %s` names a table with no map line", f.Via)
						}
					}
					continue
				}
				if p.Wire == WireBits && strings.HasPrefix(f.Locator, "until:") {
					// until:<code> (0.22): characters up to a terminator, in a
					// sequential layout only; the code is plain digits.
					code := f.Locator[len("until:"):]
					if !p.seq {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "an until: locator is valid only in a pack with `layout sequential`")
					}
					c, cerr := strconv.ParseUint(code, 10, 64)
					if !isDigits(code) || cerr != nil {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "until: takes a code of plain decimal digits, got %q", code)
					}
					f.until, f.untilC = true, c
					loc = locator{raw: f.Locator, kind: locBits}
				} else if p.seq {
					// A sequential locator is a bit length; a positional locator
					// is bad-directive.
					if strings.Contains(f.Locator, ":") {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "a locator in a sequential pack is a bit length, not <word>:<pos>:<len>")
					}
					n, aerr := strconv.Atoi(f.Locator)
					if aerr != nil || n < 1 || n > maxLocatorLen {
						err = fmt.Errorf("a sequential locator is a bit length 1..%d, got %q", maxLocatorLen, f.Locator)
					}
					loc = locator{raw: f.Locator, kind: locBits, blen: n}
				} else if p.Wire == WireBits && isDigits(f.Locator) {
					return nil, perr(ErrBadDirective, f.Line, f.Locator, "a bit length for a locator is valid only in a pack with `layout sequential`")
				} else if f.Locator == "." && dotWire {
					if f.group == nil {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "the locator `.` names an item and is valid only inside a group")
					}
					f.dot = true
					loc = locator{raw: ".", kind: locJSON}
					if p.Wire == WireProtobuf {
						loc.kind = locProto
					}
				} else {
					loc, err = parseLocator(innerWire(f.group), f.Locator, false)
				}
				if err != nil {
					if err := note(perr(ErrBadLocator, f.Line, f.Locator, "%v", err)); err != nil {
						return nil, err
					}
					continue
				}
				loc.bit = loc.word*p.WordBytes*8 + loc.pos
				f.loc = loc
				if kind, err := resolveFieldTransform(p.Wire, f); err != nil {
					if err := note(perr(kind, f.Line, f.Locator, "%v", err)); err != nil {
						return nil, err
					}
					continue
				}
				f.yields, _ = transformYields(f.Transform)
				if err := checkFieldOptions(p.Wire, f); err != nil {
					return nil, perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
				}
				if p.seq && f.Optional {
					return nil, perr(ErrBadDirective, f.Line, f.Locator, "field option `optional` is not valid in a sequential pack")
				}
				if f.Absent != nil {
					if err := resolveSentinels(innerWire(f.group), f); err != nil {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "%v", err)
					}
				}
				if f.Via != "" {
					f.table = p.tables[f.Via]
					if f.table == nil {
						return nil, perr(ErrBadDirective, f.Line, f.Locator, "`via %s` names a table with no map line", f.Via)
					}
				}
			}
			for _, w := range whens {
				// `const <locator> present` is refused; `=present` writes the text
				// (0.6 ruling 3).
				// `const .` is refused: the item itself is not a place a constant is
				// written (0.7 ruling 18).
				if w.Const && w.Locator == "." {
					return nil, perr(ErrBadDirective, w.Line, w.Locator, "a const cannot name the item itself")
				}
				if w.Const && w.Value == "present" {
					return nil, perr(ErrBadDirective, w.Line, w.Locator, "a const cannot be `present`; write `=present` for the text")
				}
				loc, err := parseLocator(innerWire(w.group), w.Locator, false)
				if err != nil {
					if err := note(perr(ErrBadLocator, w.Line, w.Locator, "%v", err)); err != nil {
						return nil, err
					}
					continue
				}
				loc.bit = loc.word*p.WordBytes*8 + loc.pos
				w.loc = loc
				if err := resolveWhen(innerWire(w.group), w); err != nil {
					return nil, perr(ErrBadDirective, w.Line, w.Locator, "%v", err)
				}
			}
			for _, g := range p.gates {
				g.loc.bit = g.loc.word*p.WordBytes*8 + g.loc.pos
			}
			for _, g := range p.Groups {
				for _, ln := range g.lines {
					switch {
					case ln.gt != nil:
						// A gate block's `if` line is neither a `.` line nor a
						// line of a message (0.17).
					case ln.f != nil && ln.f.dot:
						g.dots = append(g.dots, ln.f)
					default:
						g.needsMsg = true
					}
				}
				g.packed = p.Wire == WireProtobuf && len(g.dots) > 0 && g.dots[0].pbf != nil && g.dots[0].pbf.wire != pbLenDelim
				// A protobuf group body is scalar only when every line is `.`
				// (0.7 ruling 13).
				if p.Wire == WireProtobuf && len(g.dots) > 0 && g.needsMsg {
					return nil, perr(ErrBadDirective, g.Line, g.Locator, "the body of group %s mixes `.` with other lines", g.List)
				}
			}
			for _, g := range p.Groups {
				// A packed item has no form without its value (0.18 ruling
				// 4). A packed group is one whose body is `.` fields with a
				// numeric transform only (ruling 17).
				packed17 := p.Wire == WireProtobuf && len(g.dots) > 0 && !g.needsMsg
				for _, f := range g.dots {
					if f.pbf == nil || f.pbf.wire == pbLenDelim {
						packed17 = false
					}
				}
				if packed17 {
					for _, f := range g.dots {
						if f.WithLine {
							return nil, perr(ErrBadDirective, f.Line, f.Locator, "`with` is not valid on a `.` field of a packed protobuf group")
						}
					}
				}
			}
			if el, g := p.elementOnGroup(); el != nil {
				return nil, perr(ErrBadDirective, el.Line, el.Path, "the element path equals or passes through the path of the group on line %d", g.Line)
			}
			if f, g := p.fieldThroughGroup(); f != nil {
				return nil, perr(ErrBadDirective, f.Line, f.Locator, "the locator passes through the path of the group on line %d of the same scope", g.Line)
			}
			if p.Wire == WireBits {
				if ln, loc, err := p.checkBitsGroups(); err != nil {
					return nil, perr(ErrBadDirective, ln, loc, "%v", err)
				}
			}
		}
	}
	if err := p.checkParts(whens, perr); err != nil {
		return nil, err
	}

	if p.Distribution == "" {
		return nil, perr(ErrMissingDistribution, 0, "", "pack has no distribution line")
	}
	if len(p.Sources) == 0 {
		return nil, perr(ErrMissingSource, 0, "", "pack has no source line")
	}
	if p.Wire == WireXML {
		// A pack whose every kind has a root needs no pack-level root.
		if p.Root == "" && !p.HasKinds() {
			return nil, perr(ErrMissingRoot, 0, "", "wire xml requires a root directive")
		}
		if p.Root == "" {
			for _, k := range p.Kinds {
				if k.Root == "" {
					return nil, perr(ErrMissingRoot, k.Line, "", "wire xml requires a root directive: kind %s has none and the pack has none", k.Name)
				}
			}
		}
	}
	if p.Wire != WireXML && p.Root != "" {
		return nil, perr(ErrBadDirective, seen["root"], "", "root is xml only")
	}
	if p.Wire == WireBits && p.WordBytes == 0 && !p.seq {
		return nil, perr(ErrBadDirective, 0, "", "wire bits requires a word_bytes directive")
	}
	if p.Wire != WireBits && p.WordBytes != 0 {
		return nil, perr(ErrBadDirective, seen["word_bytes"], "", "word_bytes is valid only on wire bits")
	}
	if len(tms) > 0 && !hasType {
		return nil, perr(ErrBadDirective, tms[0].line, "", "typemap needs a field bound to model key type")
	}
	for _, t := range tms {
		if prev, dup := p.nativeToCot[t.native]; dup {
			return nil, perr(ErrBadDirective, t.line, "", "native code %q already mapped to %q", t.native, prev)
		}
		p.nativeToCot[t.native] = t.cot
		if _, dup := p.cotToNative[t.cot]; !dup {
			p.cotToNative[t.cot] = t.native
		}
	}
	for _, g := range p.Groups {
		g.body = p.newLayout(nil, g.lines, g.defaults)
	}
	if p.seq {
		// The fixed-window check of 0.33 needs the field widths, resolved
		// above; its error is reported by AddPack (ruling 10).
		p.winErr = sp.atWindows()
		sp.bind()
		// Read by every decode and encode that reaches an `inner` line
		// (0.52 ruling 20), so computed before the pack is shared.
		p.ModelKeys()
		return p, nil
	}
	if p.HasKinds() {
		if p.Wire == WireXML {
			p.kindsByRoot = map[string][]int{}
		}
		for i, k := range p.Kinds {
			lines := append(append([]line(nil), p.common...), k.lines...)
			lay := p.newLayout(k, lines, p.commonDefaults, k.defaults)
			p.layouts = append(p.layouts, lay)
			if p.Wire == WireXML {
				p.kindsByRoot[lay.root] = append(p.kindsByRoot[lay.root], i)
			}
		}
	} else {
		p.layouts = []*layout{p.newLayout(nil, p.common, p.commonDefaults)}
	}
	if p.Wire == WireText {
		for _, l := range p.layouts {
			l.text = newTextScope(l.lines)
		}
		for _, g := range p.Groups {
			g.body.text = newTextScope(g.lines)
		}
	}
	if p.Wire == WireTLV {
		for _, l := range p.layouts {
			l.tlv = newTLVScope(l.lines)
		}
	}
	if p.Wire == WireCBOR {
		for _, l := range p.layouts {
			l.cbor, _ = cborTree(l.lines)
		}
		for _, g := range p.Groups {
			g.cbody, _ = cborTree(g.lines)
		}
	}
	if p.Wire == WireBits {
		p.ModelKeys()
	}
	return p, nil
}

// listMappedTwice returns a group whose list an earlier group of the same
// scope already maps, and that earlier group. A scope is the common lines
// plus one kind, or one group body.
func (p *Pack) listMappedTwice() (dup, first *Group) {
	scan := func(lines []line, seen map[string]*Group, also map[string]*Group) (*Group, *Group) {
		for _, ln := range lines {
			g := ln.g
			if g == nil {
				continue
			}
			if prev := seen[g.List]; prev != nil {
				return g, prev
			}
			if prev := also[g.List]; prev != nil {
				return g, prev
			}
			seen[g.List] = g
		}
		return nil, nil
	}
	common := map[string]*Group{}
	if g, prev := scan(p.common, common, nil); g != nil {
		return g, prev
	}
	for _, k := range p.Kinds {
		if g, prev := scan(k.lines, map[string]*Group{}, common); g != nil {
			return g, prev
		}
	}
	for _, grp := range p.Groups {
		if g, prev := scan(grp.lines, map[string]*Group{}, nil); g != nil {
			return g, prev
		}
	}
	return nil, nil
}

// fieldThroughGroup returns a `field` line whose locator passes through the
// path of a group of the same scope, and that group (0.7 ruling 21; `field`
// lines only, 0.8 ruling 15). A scope is the common lines plus one kind, or
// one group body.
func (p *Pack) fieldThroughGroup() (*Field, *Group) {
	hasPrefix := func(path, prefix []string) bool {
		if len(prefix) > len(path) {
			return false
		}
		for i := range prefix {
			if path[i] != prefix[i] {
				return false
			}
		}
		return true
	}
	through := func(f *Field, g *Group) bool {
		if f.dot || f.loc.kind == 0 {
			return false
		}
		switch {
		case f.loc.kind == locJSON && g.loc.kind == locJSON:
			return len(f.loc.path) > len(g.loc.path) && hasPrefix(f.loc.path, g.loc.path)
		case (f.loc.kind == locAttr || f.loc.kind == locText) && g.loc.kind == locElem:
			return hasPrefix(f.loc.path, g.loc.path)
		case f.loc.kind == locProto && g.loc.kind == locProto:
			if len(f.loc.pbPath) <= len(g.loc.pbPath) {
				return false
			}
			for i, n := range g.loc.pbPath {
				if f.loc.pbPath[i] != n {
					return false
				}
			}
			return true
		}
		return false
	}
	// first is the first step of a path: a group can lie on the path of a
	// field only when the two start alike.
	first := func(l *locator) string {
		switch {
		case l.kind == locProto && len(l.pbPath) > 0:
			return strconv.Itoa(l.pbPath[0])
		case len(l.path) > 0:
			return l.path[0]
		}
		return ""
	}
	scan := func(lines ...[]line) (*Field, *Group) {
		var groups map[string][]*Group
		for _, ls := range lines {
			for _, ln := range ls {
				if ln.g != nil {
					if groups == nil {
						groups = map[string][]*Group{}
					}
					k := first(&ln.g.loc)
					groups[k] = append(groups[k], ln.g)
				}
			}
		}
		if groups == nil {
			return nil, nil
		}
		for _, ls := range lines {
			for _, ln := range ls {
				if ln.f == nil {
					continue
				}
				for _, g := range groups[first(&ln.f.loc)] {
					if through(ln.f, g) {
						return ln.f, g
					}
				}
			}
		}
		return nil, nil
	}
	if f, g := scan(p.common); f != nil {
		return f, g
	}
	for _, k := range p.Kinds {
		if f, g := scan(p.common, k.lines); f != nil {
			return f, g
		}
	}
	for _, grp := range p.Groups {
		if f, g := scan(grp.lines); f != nil {
			return f, g
		}
	}
	return nil, nil
}

// elementOnGroup returns an `element` line whose path equals or passes through
// the path of a group of the same scope, and that group (0.18 ruling 12).
func (p *Pack) elementOnGroup() (*Element, *Group) {
	if len(p.elements) == 0 || p.Wire != WireXML {
		return nil, nil
	}
	scan := func(lines []line) (*Element, *Group) {
		for _, ln := range lines {
			if ln.el == nil {
				continue
			}
			for _, lg := range lines {
				if g := lg.g; g != nil && g.loc.kind == locElem && pathHasPrefix(ln.el.path, g.loc.path) {
					return ln.el, g
				}
			}
		}
		return nil, nil
	}
	if !p.HasKinds() {
		return scan(p.common)
	}
	for _, k := range p.Kinds {
		if el, g := scan(append(append([]line(nil), p.common...), k.lines...)); el != nil {
			return el, g
		}
	}
	return nil, nil
}

// pathHasPrefix reports whether path starts with prefix.
func pathHasPrefix(path, prefix []string) bool {
	if len(prefix) > len(path) {
		return false
	}
	for i := range prefix {
		if path[i] != prefix[i] {
			return false
		}
	}
	return true
}

// elementPlaces computes, for the `element` lines of an xml layout, where an
// encode creates each element and each element on the way to it: at the
// first line, of any kind, that addresses the element or a path under it
// (0.18 ruling 13).
func elementPlaces(lines []line) map[int][][]string {
	var need [][]string
	seen := map[string]bool{}
	for _, ln := range lines {
		if ln.el == nil {
			continue
		}
		for i := 1; i <= len(ln.el.path); i++ {
			if k := strings.Join(ln.el.path[:i], "/"); !seen[k] {
				seen[k] = true
				need = append(need, ln.el.path[:i])
			}
		}
	}
	if len(need) == 0 {
		return nil
	}
	addressed := func(ln line) []string {
		switch {
		case ln.el != nil:
			return ln.el.path
		case ln.f != nil:
			return ln.f.loc.path
		case ln.w != nil && !ln.w.present:
			// `when <locator> present` names no position (0.18 ruling 19).
			return ln.w.loc.path
		case ln.g != nil:
			return ln.g.loc.path
		}
		return nil
	}
	at := map[int][][]string{}
	for _, path := range need {
		for i, ln := range lines {
			if pathHasPrefix(addressed(ln), path) {
				at[i] = append(at[i], path)
				break
			}
		}
	}
	for _, ps := range at {
		sort.SliceStable(ps, func(a, b int) bool { return len(ps[a]) < len(ps[b]) })
	}
	return at
}

// isDigits reports whether s is one or more decimal digits.
func isDigits(s string) bool {
	if s == "" {
		return false
	}
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// resolveGroup reads the locator of a `group` line, and on the bits wire its
// `item <bits>` and `count`, for the pack's wire (spec 0.7, "Group locators
// and item-relative locators, by wire").
//
// A group locator that is not valid for its wire is bad-directive (0.21
// ruling 37); on protobuf `rest` and `last` are such a locator.
func (p *Pack) resolveGroup(g *Group) (ErrorKind, error) {
	if p.Wire != WireBits {
		if g.hasCount {
			return ErrBadDirective, fmt.Errorf("group: `count` is valid only on wire bits")
		}
		if g.hasItem {
			return ErrBadDirective, fmt.Errorf("group: `item` is valid only on wire bits")
		}
	}
	switch p.Wire {
	case WireXML:
		names := strings.Split(g.Locator, "/")
		for _, e := range names {
			if e == "" || strings.ContainsAny(e, "@#") {
				return ErrBadDirective, fmt.Errorf("an xml group locator is a path of element names, got %q", g.Locator)
			}
		}
		g.loc = locator{raw: g.Locator, kind: locElem, path: names}
	case WireGeoJSON, WireJSON:
		wire := p.Wire
		if g.parent != nil {
			wire = WireJSON
		}
		loc, err := parseLocator(wire, g.Locator, false)
		if err != nil {
			return ErrBadDirective, err
		}
		if loc.kind == locCoord {
			return ErrBadDirective, fmt.Errorf("a geojson group locator is a properties member or a top-level member")
		}
		g.loc = loc
	case WireProtobuf:
		loc, err := parseLocator(WireProtobuf, g.Locator, false)
		if err != nil {
			return ErrBadDirective, err
		}
		g.loc = loc
	case WireBits:
		if !g.hasItem || !g.hasCount {
			return ErrBadDirective, fmt.Errorf("a bits group is `group <list> <word>:<pos> item <bits> count <count-locator | n>`: `item` and `count` are required")
		}
		parts := strings.Split(g.Locator, ":")
		if len(parts) != 2 {
			return ErrBadDirective, fmt.Errorf("a bits group locator is word:pos, got %q", g.Locator)
		}
		word, e1 := parseSmallUint(parts[0])
		pos, e2 := parseSmallUint(parts[1])
		if e1 != nil || e2 != nil {
			return ErrBadLocator, fmt.Errorf("a bits group locator is two non-negative integers word:pos, got %q", g.Locator)
		}
		g.start = word*p.WordBytes*8 + pos
		g.loc = locator{raw: g.Locator, kind: locBits, word: word, pos: pos, bit: g.start}
		bits, err := parseSmallUint(g.itemText)
		if err != nil || bits < 1 {
			return ErrBadDirective, fmt.Errorf("group: `item` takes a number of bits >= 1, got %q", g.itemText)
		}
		g.itemBits = bits
		if strings.Contains(g.countText, ":") {
			loc, err := parseLocator(WireBits, g.countText, false)
			if err != nil {
				return ErrBadLocator, fmt.Errorf("group count locator: %v", err)
			}
			if loc.blen > 64 {
				return ErrBadDirective, fmt.Errorf("a group count locator covers at most 64 bits, got %d", loc.blen)
			}
			loc.bit = loc.word*p.WordBytes*8 + loc.pos
			g.countLoc = &loc
		} else {
			n, err := parseSmallUint(g.countText)
			if err != nil || n < 0 {
				return ErrBadDirective, fmt.Errorf("group: `count` takes a count locator word:pos:len or a number >= 0, got %q", g.countText)
			}
			g.countN = n
		}
	}
	return "", nil
}

// checkBitsGroups checks the places of the groups of a bits pack against the
// other lines of their scope (spec 0.7, and rulings 2 to 4 of 0.7). It
// returns the line and locator at fault.
func (p *Pack) checkBitsGroups() (int, string, error) {
	// check runs over one scope; itemBits is the size of an item when the
	// scope is a group body, 0 for a message.
	check := func(lines []line, itemBits int) (int, string, error) {
		var counted []*Group // the groups counted by a locator
		for _, ln := range lines {
			if g := ln.g; g != nil && g.countLoc != nil {
				if g.countLoc.bit+g.countLoc.blen > g.start {
					return g.Line, g.Locator, fmt.Errorf("the count locator %s reaches the start of its group", g.countText)
				}
				counted = append(counted, g)
			}
		}
		for _, ln := range lines {
			var end, at int
			var what, loc string
			switch {
			case ln.f != nil:
				end, at, what, loc = ln.f.loc.bit+ln.f.loc.blen, ln.f.Line, "field", ln.f.Locator
			case ln.w != nil:
				// The bound of an item is stated for its fields and its nested
				// groups with a fixed count (0.7 ruling 4).
				// A const of an item is bounded by `item <bits>` as a field is
				// (0.7 ruling 15).
				end, at, what, loc = ln.w.loc.bit+ln.w.loc.blen, ln.w.Line, "when or const", ln.w.Locator
			case ln.gt != nil:
				// A gate is bounded as a field is (0.17 ruling 2).
				end, at, what, loc = ln.gt.loc.bit+ln.gt.loc.blen, ln.gt.Line, "gate", ln.gt.Locator
				// A gate may not lie within the items of a fixed-count group
				// of its scope (0.17 ruling 9).
				for _, l2 := range lines {
					if g := l2.g; g != nil && g.countLoc == nil && g.countN > 0 {
						if ln.gt.loc.bit < g.start+g.countN*g.itemBits && end > g.start {
							return at, loc, fmt.Errorf("the gate lies within the items of the fixed-count group on line %d", g.Line)
						}
					}
				}
			default:
				g := ln.g
				at, what, loc = g.Line, "group", g.Locator
				for _, c := range counted {
					if c != g && g.start >= c.start {
						return at, loc, fmt.Errorf("the group starts at or beyond the start of the group counted by a locator on line %d, which is the last thing in its scope", c.Line)
					}
				}
				if g.countLoc == nil && itemBits > 0 && g.start+g.countN*g.itemBits > itemBits {
					return at, loc, fmt.Errorf("the nested group with a fixed count reaches beyond the %d bits of an item", itemBits)
				}
				// The count locator of a nested group is bounded by the item
				// too (0.7 ruling 15).
				if c := g.countLoc; c != nil && itemBits > 0 && c.bit+c.blen > itemBits {
					return at, loc, fmt.Errorf("the count locator of the nested group reaches beyond the %d bits of an item", itemBits)
				}
				// A fixed-count group that starts before a group counted by a
				// locator may not reach its start (0.7 ruling 16).
				if g.countLoc == nil {
					for _, c := range counted {
						if g.start < c.start && g.start+g.countN*g.itemBits > c.start {
							return at, loc, fmt.Errorf("the items of the fixed-count group reach the start of the group counted by a locator on line %d", c.Line)
						}
					}
				}
				continue
			}
			if itemBits > 0 && end > itemBits {
				return at, loc, fmt.Errorf("the %s reaches beyond the %d bits of an item", what, itemBits)
			}
			for _, c := range counted {
				if end > c.start {
					return at, loc, fmt.Errorf("the %s lies at or beyond the start of the group counted by a locator on line %d, which is the last thing in its scope", what, c.Line)
				}
			}
		}
		return 0, "", nil
	}
	if p.HasKinds() {
		for _, k := range p.Kinds {
			lines := append(append([]line(nil), p.common...), k.lines...)
			if ln, loc, err := check(lines, 0); err != nil {
				return ln, loc, err
			}
		}
	} else if ln, loc, err := check(p.common, 0); err != nil {
		return ln, loc, err
	}
	for _, g := range p.Groups {
		if ln, loc, err := check(g.lines, g.itemBits); err != nil {
			return ln, loc, err
		}
	}
	return 0, "", nil
}

// newLayout indexes the lines of one scope: a message layout (the common
// defaults, then the kind's) or a group body (the group's defaults).
func (p *Pack) newLayout(k *KindDef, lines []line, defaults ...[]*Default) *layout {
	l := &layout{kind: k, lines: lines, fieldsAt: map[string][]*Field{}, whenAt: map[string]bool{}, root: p.Root}
	l.parts = p.partGroups(lines, func(int, string, string, ...any) {})
	textWire := p.Wire == WireXML || p.Wire == WireGeoJSON || p.Wire == WireJSON
	maxBit, needBit, allBit := 0, 0, 0
	if p.Wire == WireXML {
		l.elemAt = elementPlaces(lines)
	}
	for _, ln := range lines {
		var loc locator
		optional := false
		if ln.el != nil {
			continue
		}
		if g := ln.gt; g != nil {
			l.gates = append(l.gates, g)
			if end := g.loc.bit + g.loc.blen; end > allBit {
				allBit = end
			}
			continue
		}
		if g := ln.g; g != nil {
			l.groups = append(l.groups, g)
			if l.groupAt == nil {
				l.groupAt = map[string]*Group{}
			}
			l.groupAt[g.Locator] = g
			// A group with a fixed count has a fixed place; of a group counted
			// by a locator only the count has one.
			end := g.start + g.countN*g.itemBits
			if g.countLoc != nil {
				end = g.countLoc.bit + g.countLoc.blen
			}
			if end > maxBit {
				maxBit = end
			}
			if end > needBit {
				needBit = end
			}
			continue
		}
		if ln.f != nil {
			l.fieldsAt[ln.f.Locator] = append(l.fieldsAt[ln.f.Locator], ln.f)
			loc, optional = ln.f.loc, ln.f.Optional
		} else {
			w := ln.w
			loc = w.loc
			// `when <locator> present` on a text wire does not map the member
			// (0.5 ruling 27); a const, and a when with a value, do.
			if !textWire || !w.present {
				l.whenAt[w.Locator] = true
			}
			if textWire && !w.present && w.part == nil {
				if l.forced == nil {
					l.forced = map[string]*When{}
				}
				l.forced[w.Locator] = w
			}
		}
		end := loc.bit + loc.blen
		if end > allBit {
			allBit = end
		}
		// The lines of a gate block count toward a length only when the
		// block holds (0.17).
		if ln.in != nil {
			continue
		}
		if end > maxBit {
			maxBit = end
		}
		if !optional && end > needBit {
			needBit = end
		}
	}
	if maxBit > allBit {
		allBit = maxBit
	}
	l.maxBit, l.needBit, l.allBit = maxBit, needBit, allBit
	if p.Wire == WireBits && p.WordBytes > 0 {
		l.bytes = p.wholeWords(maxBit)
		l.decBytes = p.wholeWords(needBit)
	}
	// A default in a kind takes precedence over a common default of the key;
	// a group body has its own defaults only.
	for _, ds := range defaults {
		for _, d := range ds {
			if l.defaults == nil {
				l.defaults = map[string]*Default{}
			}
			l.defaults[d.Key] = d
		}
	}
	if k != nil && k.Root != "" {
		l.root = k.Root
	}
	return l
}

// wholeWords is the length in bytes of the whole words that hold bits bits.
func (p *Pack) wholeWords(bits int) int {
	wordBits := p.WordBytes * 8
	return (bits + wordBits - 1) / wordBits * p.WordBytes
}

// resolveWhen reads the value of a `when` line for the pack's wire
// (spec/engine-spec.md, "`when` values, by wire"): since 0.20 a list of values
// separated by commas, and on `bits` and `protobuf` ranges `lo..hi`.
func resolveWhen(wire string, w *When) error {
	switch wire {
	case WireBits, WireProtobuf:
		if wire == WireBits && w.loc.blen > 64 {
			return fmt.Errorf("a when covers at most 64 bits, got %d", w.loc.blen)
		}
		if wire == WireProtobuf && w.Value == "present" && !w.Const {
			w.present = true
			return nil
		}
		bits := 64
		if wire == WireBits {
			bits = w.loc.blen
		}
		if w.Const {
			v, err := strconv.ParseUint(w.Value, 10, 64)
			if err != nil || !isDigits(w.Value) {
				return fmt.Errorf("a const value is an unsigned decimal integer, got %q", w.Value)
			}
			if bits < 64 && v>>uint(bits) != 0 {
				return fmt.Errorf("const value %d does not fit in %d bit(s)", v, bits)
			}
			w.num = v
			return nil
		}
		rs, err := parseNumList(w.Value, bits)
		if err != nil {
			return err
		}
		w.ranges, w.num = rs, rs[0].lo
	default:
		if wire == WireGeoJSON && w.loc.kind == locCoord {
			return fmt.Errorf("a when names a member, not a coordinate")
		}
		// On the `text` wire (0.10) a when value stays one literal value:
		// the lists of 0.20 are for xml, json and geojson (its ruling 15),
		// and a comma there is checked against the delimiter (ruling 25 of
		// 0.10). Provisional reading.
		if w.Const || w.Value == "" || wire == WireText {
			switch {
			case !w.Const && w.Value == "present":
				w.present = true
			case strings.HasPrefix(w.Value, "="):
				w.text, w.forced = w.Value[1:], true
			default:
				w.text = w.Value
			}
			return nil
		}
		items := strings.Split(w.Value, ",")
		for i, it := range items {
			if it == "" {
				return fmt.Errorf("when %q: an empty value in the list; only the single value \"\" names the empty text", w.Value)
			}
			if it == "present" {
				if len(items) > 1 {
					return fmt.Errorf("when %q: `present` may not be combined with other values", w.Value)
				}
				w.present = true
				return nil
			}
			text, forced := it, false
			if strings.HasPrefix(it, "=") {
				text, forced = it[1:], true
			}
			if i == 0 {
				w.text, w.forced = text, forced
			}
			w.texts = append(w.texts, text)
		}
	}
	return nil
}

// parseNumList reads the value list of a `when` on `bits` or `protobuf`: each
// item digits or digits..digits, lo <= hi, every end below 2^bits (0.20).
func parseNumList(text string, bits int) ([]numRange, error) {
	num := func(s string) (uint64, error) {
		if !isDigits(s) {
			return 0, fmt.Errorf("when %q: %q is not an unsigned decimal integer", text, s)
		}
		v, err := strconv.ParseUint(s, 10, 64)
		if err != nil {
			return 0, fmt.Errorf("when %q: %q does not fit in 64 bits", text, s)
		}
		if bits < 64 && v>>uint(bits) != 0 {
			return 0, fmt.Errorf("when value %d does not fit in %d bit(s)", v, bits)
		}
		return v, nil
	}
	var out []numRange
	for _, it := range strings.Split(text, ",") {
		if it == "" {
			return nil, fmt.Errorf("when %q: an empty value in the list", text)
		}
		var r numRange
		if i := strings.Index(it, ".."); i >= 0 {
			lo, err := num(it[:i])
			if err != nil {
				return nil, err
			}
			hi, err := num(it[i+2:])
			if err != nil {
				return nil, err
			}
			if lo > hi {
				return nil, fmt.Errorf("when %q: the range %s has lo > hi", text, it)
			}
			r = numRange{lo, hi}
		} else {
			v, err := num(it)
			if err != nil {
				return nil, err
			}
			r = numRange{v, v}
		}
		out = append(out, r)
	}
	return out, nil
}

// tokenize splits a directive line. `#` at the start of a token begins a
// comment, so locators such as `path/#text` survive. Double quotes wrap a
// token holding whitespace; there is no escape, so a quoted value cannot hold a
// double quote, and `#` inside the quotes is literal.
func tokenize(line string) ([]string, error) {
	var toks []string
	i := 0
	isSpace := func(c byte) bool { return c == ' ' || c == '\t' || c == '\r' }
	for i < len(line) {
		c := line[i]
		switch {
		case isSpace(c):
			i++
		case c == '#':
			return toks, nil
		case c == '"':
			i++
			var b strings.Builder
			closed := false
			for i < len(line) {
				c = line[i]
				if c == '"' {
					i++
					closed = true
					break
				}
				b.WriteByte(c)
				i++
			}
			if !closed {
				return nil, fmt.Errorf("unterminated quote")
			}
			toks = append(toks, b.String())
		default:
			j := i
			for j < len(line) && !isSpace(line[j]) {
				j++
			}
			toks = append(toks, line[i:j])
			i = j
		}
	}
	return toks, nil
}

func parseLocator(wire, s string, residue bool) (locator, error) {
	l := locator{raw: s}
	if s == "" {
		return l, fmt.Errorf("empty locator")
	}
	switch wire {
	case WireXML:
		segs := strings.Split(s, "/")
		last := segs[len(segs)-1]
		elems := segs[:len(segs)-1]
		switch {
		case strings.HasPrefix(last, "@"):
			l.kind, l.name = locAttr, last[1:]
			if l.name == "" {
				return l, fmt.Errorf("attribute name missing")
			}
		case last == "#text":
			l.kind = locText
		default:
			if !residue {
				return l, fmt.Errorf("xml field locator must end in @attr or #text")
			}
			l.kind = locElem
			elems = segs
		}
		for _, e := range elems {
			if e == "" || strings.ContainsAny(e, "@#") {
				return l, fmt.Errorf("bad element name %q", e)
			}
		}
		l.path = elems
	case WireGeoJSON:
		switch {
		case strings.HasPrefix(s, "geometry."):
			switch s[len("geometry."):] {
			case "lon":
				l.idx = 0
			case "lat":
				l.idx = 1
			case "alt":
				l.idx = 2
			default:
				return l, fmt.Errorf("geometry locator must be geometry.lon, geometry.lat or geometry.alt")
			}
			l.kind = locCoord
		case strings.HasPrefix(s, "properties."):
			l.kind, l.name = locProp, s[len("properties."):]
			if l.name == "" {
				return l, fmt.Errorf("property name missing")
			}
		default:
			if strings.Contains(s, ".") {
				return l, fmt.Errorf("unknown geojson locator")
			}
			if s == "type" || s == "geometry" || s == "properties" {
				return l, fmt.Errorf("%q is a reserved Feature member", s)
			}
			l.kind, l.name = locTop, s
		}
	case WireBits:
		parts := strings.Split(s, ":")
		if len(parts) != 3 {
			return l, fmt.Errorf("bits locator must be word:pos:len")
		}
		// Three unsigned decimal integers (ruling 5a of 0.11). A length
		// above what a transform allows is refused after the file.
		word, e1 := parseSmallUint(parts[0])
		pos, e2 := parseSmallUint(parts[1])
		ln, e3 := parseSmallUint(parts[2])
		if e1 != nil || e2 != nil || e3 != nil {
			return l, fmt.Errorf("bits locator fields must be unsigned decimal integers (word:pos:len), got %q", s)
		}
		if ln < 1 {
			return l, fmt.Errorf("bits len must be 1 or more, got %d", ln)
		}
		l.kind, l.word, l.pos, l.blen = locBits, word, pos, ln
	case WireProtobuf:
		parts := strings.Split(s, ".")
		nums := make([]int, 0, len(parts))
		for _, part := range parts {
			fn, err := parseSmallUint(part)
			if err != nil || fn < 1 || fn > maxFieldNumber {
				return l, fmt.Errorf("protobuf locator must be dot-separated field numbers from 1 to %d, got %q", maxFieldNumber, s)
			}
			nums = append(nums, fn)
		}
		l.kind, l.pbPath = locProto, nums
	case WireJSON:
		segs := strings.Split(s, ".")
		for _, seg := range segs {
			if seg == "" {
				return l, fmt.Errorf("json locator must be member names separated by '.', got %q", s)
			}
		}
		l.kind, l.path = locJSON, segs
	default:
		return l, fmt.Errorf("unknown wire %q", wire)
	}
	return l, nil
}

// LoadPacks parses every packs/<dir>/pack.def under dir.
func LoadPacks(dir string) ([]*Pack, error) {
	matches, err := filepath.Glob(filepath.Join(dir, "*", "pack.def"))
	if err != nil {
		return nil, err
	}
	sort.Strings(matches)
	if len(matches) == 0 {
		return nil, &Error{Kind: ErrUnknownFormat, Source: dir, Detail: "no */pack.def found"}
	}
	var packs []*Pack
	for _, m := range matches {
		p, err := ParsePackFile(m)
		if err != nil {
			return nil, err
		}
		packs = append(packs, p)
	}
	return packs, nil
}

// isFloatText reports whether s is -?digits[.digits][(e|E)[+|-]digits], the
// grammar of a float `requires =` or `case` value (0.20 ruling 24).
func isFloatText(s string) bool {
	s = strings.TrimPrefix(s, "-")
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		exp := s[i+1:]
		if len(exp) > 0 && (exp[0] == '+' || exp[0] == '-') {
			exp = exp[1:]
		}
		if !isDigits(exp) {
			return false
		}
		s = s[:i]
	}
	if i := strings.IndexByte(s, '.'); i >= 0 {
		return isDigits(s[:i]) && isDigits(s[i+1:])
	}
	return isDigits(s)
}
