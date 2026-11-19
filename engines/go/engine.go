// Package goatxf is the Go engine of goat-transformers: it loads model modules
// (model/<module>.def) and packs (packs/<format>/pack.def) and decodes, encodes and converts messages through
// the shared model. Written from spec/ and packs/ only.
package goatxf

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// Engine holds the loaded model modules, keyed by module name, and the loaded
// packs, keyed by format name.
type Engine struct {
	modules  map[string]*Module
	packs    map[string]*Pack
	maxDist  string
	derives  []*Derive // every derive line in application order; nil until first use
	maxItems int64     // the limit on list items one decode holds (ruling 7 of 0.11)
}

// DefaultMaxItems is the limit on list items of a decode unless the caller
// sets another (ruling 7b of 0.11).
const DefaultMaxItems = 100000

// New returns an empty engine whose distribution limit is controlled and
// whose limit on list items is DefaultMaxItems.
func New() *Engine {
	return &Engine{modules: map[string]*Module{}, packs: map[string]*Pack{}, maxDist: DistControlled, maxItems: DefaultMaxItems}
}

// SetMaxItems sets the limit on list items one decode holds, counted over
// every list of the message at every nesting level (ruling 7 of 0.11). With
// 0 any item is refused; a negative value is read as 0. Going over the limit
// is malformed-wire. Encode is not limited.
func (e *Engine) SetMaxItems(n int64) {
	if n < 0 {
		n = 0
	}
	e.maxItems = n
}

// MaxItems returns the limit on list items of a decode.
func (e *Engine) MaxItems() int64 { return e.maxItems }

// SetMaxDistribution sets the distribution limit, public or controlled. It
// governs what is loaded afterwards.
func (e *Engine) SetMaxDistribution(d string) error {
	if !validDistribution(d) {
		return &Error{Kind: ErrBadDirective, Detail: fmt.Sprintf("max distribution must be public or controlled, got %q", d)}
	}
	e.maxDist = d
	return nil
}

// MaxDistribution returns the distribution limit.
func (e *Engine) MaxDistribution() string { return e.maxDist }

// refused reports whether a marking is above the engine's limit.
func (e *Engine) refused(dist string) bool {
	return e.maxDist == DistPublic && dist != DistPublic
}

// LoadModel parses one model module and loads it. source names the text in
// errors.
func (e *Engine) LoadModel(text []byte, source string) error {
	m, err := parseModule(text, source)
	if err != nil {
		return err
	}
	return e.AddModule(m)
}

// AddModule loads a parsed model module. The checks run in the order of 0.8
// ruling 29: after the file's own missing-distribution and missing-source,
// distribution-refused, unknown-module, distribution-violation, the `derive`
// checks, duplicate-module.
func (e *Engine) AddModule(m *Module) error {
	if e.refused(m.Distribution) {
		return &Error{Kind: ErrDistributionRefused, Module: m.Name, Source: m.Source, Detail: fmt.Sprintf("module %s is %s and the engine limit is %s", m.Name, m.Distribution, e.maxDist)}
	}
	// A module is loaded after the modules it uses, and a public module uses
	// only public modules (spec 0.8, "Model additions").
	for _, name := range m.Uses {
		if _, ok := e.modules[name]; !ok {
			return &Error{Kind: ErrUnknownModule, Module: name, Source: m.Source, Detail: fmt.Sprintf("module %s uses module %s, which is not loaded", m.Name, name)}
		}
	}
	for _, name := range m.Uses {
		if u := e.modules[name]; m.Distribution == DistPublic && u.Distribution != DistPublic {
			return &Error{Kind: ErrDistributionViolation, Module: name, Source: m.Source, Detail: fmt.Sprintf("public module %s uses %s module %s", m.Name, u.Distribution, name)}
		}
	}
	if err := e.checkDerives(m); err != nil {
		return err
	}
	if prev, dup := e.modules[m.Name]; dup {
		return &Error{Kind: ErrDuplicateModule, Module: m.Name, Source: m.Source, Detail: fmt.Sprintf("module %s already loaded from %s", m.Name, prev.Source)}
	}
	e.modules[m.Name] = m
	e.derives = nil
	return nil
}

// LoadPack parses one pack.def and loads it. source names the text in errors.
func (e *Engine) LoadPack(text []byte, source string) error {
	p, err := ParsePack(text, source)
	if err != nil {
		return err
	}
	return e.AddPack(p)
}

// AddPack checks a parsed pack against the modules loaded so far and loads
// it. The checks run in the order spec/engine-spec.md "Loading" states.
func (e *Engine) AddPack(p *Pack) error {
	lerr := func(kind ErrorKind, module string, r *keyRef, format string, a ...any) error {
		err := &Error{Kind: kind, Format: p.Format, Module: module, Source: p.Source, Detail: fmt.Sprintf(format, a...)}
		if r != nil {
			err.Locator, err.Line = r.locator, r.line
		}
		return err
	}
	if e.refused(p.Distribution) {
		return lerr(ErrDistributionRefused, "", nil, "pack %s is %s and the engine limit is %s", p.Format, p.Distribution, e.maxDist)
	}
	used := append([]string{CoreModule}, p.Uses...)
	for _, name := range used {
		if _, ok := e.modules[name]; !ok {
			return lerr(ErrUnknownModule, name, nil, "module %s is not loaded", name)
		}
	}
	if p.Distribution == DistPublic {
		for _, name := range used {
			if m := e.modules[name]; m.Distribution != DistPublic {
				return lerr(ErrDistributionViolation, name, nil, "public pack %s uses %s module %s", p.Format, m.Distribution, name)
			}
		}
	}
	inUse := map[string]bool{}
	for _, name := range used {
		inUse[name] = true
	}
	// Each check runs over every field line and every requires key, in file
	// order, before the next check starts. A requires key is checked like a
	// mapped key, except that it has no transform.
	for i := range p.keyRefs {
		r := &p.keyRefs[i]
		if mod, _ := splitModelKey(r.key); !inUse[mod] {
			return lerr(ErrModuleNotUsed, mod, r, "key %s needs a `uses %s` line", r.key, mod)
		}
	}
	for i := range p.keyRefs {
		r := &p.keyRefs[i]
		mod, name := splitModelKey(r.key)
		m := e.modules[mod]
		if _, ok := m.Key(name); !ok && !m.IsList(name) {
			what := "key"
			if r.group != nil {
				what = "list"
			}
			return lerr(ErrUndeclaredKey, mod, r, "module %s declares no %s %q", mod, what, name)
		}
	}
	// A field with `via` is checked against the model side of its table; a
	// default value must read as its key's declared type.
	for i := range p.keyRefs {
		r := &p.keyRefs[i]
		mod, name := splitModelKey(r.key)
		k, isKey := e.modules[mod].Key(name)
		// A `group` names a list and a `field` or `default` a key; `requires`
		// takes either.
		switch {
		case r.group != nil && isKey:
			return lerr(ErrKeyTypeMismatch, mod, r, "group names %s, which is a %s key, not a list", r.key, kindName(k.Type))
		case r.group != nil || r.req:
			continue
		case !isKey:
			return lerr(ErrKeyTypeMismatch, mod, r, "%s is a list: a group maps it, not a field or a default", r.key)
		}
		if d := r.def; d != nil {
			v, err := readAs(d.Value, k.Type)
			if err != nil {
				return lerr(ErrKeyTypeMismatch, mod, r, "default for key %s, which is %s: %v", r.key, kindName(k.Type), err)
			}
			d.val = v
			continue
		}
		f := r.field
		if f == nil {
			continue
		}
		if f.table != nil {
			// An all-integer table on a float key is accepted and its model
			// side read as float (0.6 ruling 4).
			if f.table.modelType != k.Type && !(f.table.modelType == KindInt && k.Type == KindFloat) {
				return lerr(ErrKeyTypeMismatch, mod, r, "key %s is %s but the model side of table %s is %s", r.key, kindName(k.Type), f.table.name, kindName(f.table.modelType))
			}
		} else if got, ok := transformYields(f.Transform); !ok || got != k.Type {
			return lerr(ErrKeyTypeMismatch, mod, r, "key %s is %s but transform %s yields %s", r.key, kindName(k.Type), f.Transform, kindName(got))
		}
		f.keyType = k.Type
		f.bindTable()
	}
	if prev, dup := e.packs[p.Format]; dup {
		return &Error{Kind: ErrDuplicateFormat, Format: p.Format, Source: p.Source, Detail: "already loaded from " + prev.Source}
	}
	e.packs[p.Format] = p
	return nil
}

// DefaultModelsDir is where the modules of a packs directory live: the
// `model` directory beside it.
func DefaultModelsDir(packsDir string) string {
	return filepath.Join(packsDir, "..", "model")
}

// Load builds an engine from every pack under dir and the modules in the
// `model` directory beside it, with the default distribution limit.
func Load(dir string) (*Engine, error) {
	return LoadDirs(DefaultModelsDir(dir), dir, DistControlled)
}

// LoadDirs builds an engine with the given distribution limit: every
// modelsDir/*.def (core first, then each module after the modules it uses),
// then every packsDir/*/pack.def.
func LoadDirs(modelsDir, packsDir, maxDistribution string) (*Engine, error) {
	e := New()
	if err := e.SetMaxDistribution(maxDistribution); err != nil {
		return nil, err
	}
	files, err := moduleFiles(modelsDir)
	if err != nil {
		return nil, err
	}
	for _, f := range files {
		text, err := os.ReadFile(f)
		if err != nil {
			return nil, &Error{Kind: ErrBadDirective, Source: f, Detail: err.Error()}
		}
		if err := e.LoadModel(text, f); err != nil {
			return nil, err
		}
	}
	packs, err := LoadPacks(packsDir)
	if err != nil {
		return nil, err
	}
	for _, p := range packs {
		if err := e.AddPack(p); err != nil {
			return nil, err
		}
	}
	return e, nil
}

// LoadPacksOnly builds an engine that holds only the named packs of packsDir
// and the modules they need: `core`, the modules the packs name in `uses`
// lines, and the modules those use in turn. A name is a directory of
// packsDir, which by convention is the format name. The modules load in the
// order LoadDirs loads them, then the packs in the order given; a name given
// twice is loaded once. A name with no <name>/pack.def is unknown-format. A
// needed module that no file of modelsDir declares is left to the load of the
// pack or module that uses it, which reports unknown-module.
func LoadPacksOnly(modelsDir, packsDir, maxDistribution string, names []string) (*Engine, error) {
	e := New()
	if err := e.SetMaxDistribution(maxDistribution); err != nil {
		return nil, err
	}
	if len(names) == 0 {
		return nil, &Error{Kind: ErrUnknownFormat, Source: packsDir, Detail: "no pack named"}
	}
	var packs []*Pack
	seen := map[string]bool{}
	for _, name := range names {
		if seen[name] {
			continue
		}
		seen[name] = true
		path := filepath.Join(packsDir, name, "pack.def")
		if name == "" || name != filepath.Base(name) || name == "." || name == ".." {
			return nil, &Error{Kind: ErrUnknownFormat, Format: name, Source: packsDir, Detail: "a pack is named by its directory under the packs directory"}
		}
		if _, err := os.Stat(path); err != nil {
			return nil, &Error{Kind: ErrUnknownFormat, Format: name, Source: packsDir, Detail: "no " + name + "/pack.def in the packs directory"}
		}
		p, err := ParsePackFile(path)
		if err != nil {
			return nil, err
		}
		packs = append(packs, p)
	}
	files, err := moduleFiles(modelsDir)
	if err != nil {
		return nil, err
	}
	usesOf := map[string][]string{}
	for _, f := range files {
		if name, uses := moduleHeader(f); name != "" {
			if _, dup := usesOf[name]; !dup {
				usesOf[name] = uses
			}
		}
	}
	needed := map[string]bool{}
	var need func(name string)
	need = func(name string) {
		if needed[name] {
			return
		}
		needed[name] = true
		for _, u := range usesOf[name] {
			need(u)
		}
	}
	need(CoreModule)
	for _, p := range packs {
		for _, u := range p.Uses {
			need(u)
		}
	}
	for _, f := range files {
		if name, _ := moduleHeader(f); !needed[name] {
			continue
		}
		text, err := os.ReadFile(f)
		if err != nil {
			return nil, &Error{Kind: ErrBadDirective, Source: f, Detail: err.Error()}
		}
		if err := e.LoadModel(text, f); err != nil {
			return nil, err
		}
	}
	for _, p := range packs {
		if err := e.AddPack(p); err != nil {
			return nil, err
		}
	}
	return e, nil
}

// Modules returns the loaded modules sorted by name.
func (e *Engine) Modules() []*Module {
	out := make([]*Module, 0, len(e.modules))
	for _, m := range e.modules {
		out = append(out, m)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}

// Formats returns the loaded packs sorted by format name.
func (e *Engine) Formats() []*Pack {
	out := make([]*Pack, 0, len(e.packs))
	for _, p := range e.packs {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Format < out[j].Format })
	return out
}

// Pack returns the pack for a format.
func (e *Engine) Pack(format string) (*Pack, error) {
	p, ok := e.packs[format]
	if !ok {
		return nil, &Error{Kind: ErrUnknownFormat, Format: format, Detail: "no pack loaded for this format"}
	}
	return p, nil
}

// ModelKeys is the union of the model keys a format maps, over its common
// lines and all its kinds, in first appearance order.
func (e *Engine) ModelKeys(format string) ([]string, error) {
	p, err := e.Pack(format)
	if err != nil {
		return nil, err
	}
	return p.ModelKeys(), nil
}

// Capability is the capability report of one ordered pair of formats
// (ruling 6 of 0.11): the entries of model_keys(from) that are also entries
// of model_keys(to), the other entries, both in the order of
// model_keys(from), and the grade.
type Capability struct {
	Grade   string // full, partial or none
	Carried []string
	Dropped []string
}

// Capability computes the report of (from, to) from the two packs alone. A
// format that is not loaded is unknown-format, from checked first.
func (e *Engine) Capability(from, to string) (*Capability, error) {
	src, err := e.Pack(from)
	if err != nil {
		return nil, err
	}
	dst, err := e.Pack(to)
	if err != nil {
		return nil, err
	}
	target := map[string]bool{}
	for _, k := range dst.ModelKeys() {
		target[k] = true
	}
	c := &Capability{Carried: []string{}, Dropped: []string{}}
	for _, k := range src.ModelKeys() {
		if target[k] {
			c.Carried = append(c.Carried, k)
		} else {
			c.Dropped = append(c.Dropped, k)
		}
	}
	switch {
	case len(c.Carried) == 0:
		c.Grade = "none"
	case len(c.Dropped) == 0:
		c.Grade = "full"
	default:
		c.Grade = "partial"
	}
	return c, nil
}

// Decode turns wire bytes into the shared model. When some fields cannot be
// decoded the entity is returned with those fields absent together with a
// *DecodeError listing them. In a pack with kinds the entity records the kind
// the wire selected.
func (e *Engine) Decode(format string, b []byte) (*Entity, error) {
	p, err := e.Pack(format)
	if err != nil {
		return nil, err
	}
	d := &decodeState{pack: p, ent: NewEntity(), limit: e.maxItems}
	d.rec = d.ent.item()
	switch p.Wire {
	case WireXML:
		err = decodeXML(d, b)
	case WireGeoJSON:
		err = decodeGeoJSON(d, b)
	case WireJSON:
		err = decodeJSONWire(d, b)
	case WireBits:
		err = decodeBits(d, b)
	case WireProtobuf:
		err = decodeProtobuf(d, b)
	case WireText:
		err = decodeText(d, b)
	case WireTLV:
		err = decodeTLV(d, b)
	}
	if err != nil {
		return nil, err
	}
	d.ent.Lists = d.rec.Lists
	// A key mapped by several lines takes its value from the earliest line
	// whose locator is present and whose transform succeeds, so the failure
	// of a line is an error only when no line gave its key a value, in the
	// entity or the item the line was read for. A line whose transform
	// succeeds and whose table has no entry is never forgiven (0.6 ruling 4,
	// 0.7 ruling 10).
	var failed []*Error
	for i, f := range d.failed {
		if _, has := d.failedIn[i].Fields[d.failedKey[i]]; !has || d.failedHard[i] {
			failed = append(failed, f)
		}
	}
	if len(failed) > 0 {
		return d.ent, &DecodeError{Format: p.Format, Fields: failed}
	}
	return d.ent, nil
}

// Encode writes the shared model in a format's canonical form. In a pack with
// kinds it writes the kind the entity records for this format, else the first
// kind whose `requires` keys the entity all has.
func (e *Engine) Encode(format string, ent *Entity) ([]byte, error) {
	p, err := e.Pack(format)
	if err != nil {
		return nil, err
	}
	if p.seq {
		return encodeSeq(p, ent)
	}
	lay, err := chooseEncode(p, ent)
	if err != nil {
		return nil, err
	}
	rec := ent.item()
	switch p.Wire {
	case WireXML:
		return encodeXML(p, lay, ent, rec)
	case WireBits:
		return encodeBits(p, lay, rec)
	case WireProtobuf:
		return encodeProtobuf(p, lay, rec)
	case WireJSON:
		return encodeJSONWire(p, lay, ent, rec)
	case WireText:
		return encodeText(p, lay, ent, rec)
	case WireTLV:
		return encodeTLV(p, lay, ent, rec)
	default:
		return encodeGeoJSON(p, lay, ent, rec)
	}
}

// Convert is ConvertWith with no context.
func (e *Engine) Convert(from, to string, b []byte) ([]byte, error) {
	return e.ConvertWith(from, to, b, nil)
}

// ConvertWith decodes, clears the entity's kind unless from == to, fills the
// keys the entity lacks from context, applies the derivations, and encodes
// (spec 0.6, "Order inside convert"). context holds model keys and values the
// caller supplies, values in string form; nil means no context is given. When
// from == to and no context is given the fill and the derivations are
// skipped, so a same-format round trip stays byte-exact. A decode that leaves
// any key without a value fails the conversion.
func (e *Engine) ConvertWith(from, to string, b []byte, context map[string]string) ([]byte, error) {
	// from, then to, before the input is read (ruling 5 of 0.11).
	if _, err := e.Pack(from); err != nil {
		return nil, err
	}
	if _, err := e.Pack(to); err != nil {
		return nil, err
	}
	ent, err := e.Decode(from, b)
	if err != nil {
		return nil, err
	}
	if from != to {
		ent.Kind = EntityKind{}
	}
	if from != to || context != nil {
		if err := e.Fill(ent, context); err != nil {
			return nil, err
		}
		e.Complete(ent)
	}
	return e.Encode(to, ent)
}

type decodeState struct {
	pack       *Pack
	ent        *Entity
	rec        *Item // what the lines being read fill: the entity's own keys and lists, or one item
	failed     []*Error
	failedKey  []string // the model key of each entry of failed
	failedIn   []*Item  // the entity or item each entry of failed was read for
	failedHard []bool   // the entry is an error whatever another line of its key gives
	limit      int64    // the limit on list items (ruling 7 of 0.11)
	held       int64    // the list items the entity holds so far
}

// overLimit is the failure of a decode that would hold more list items than
// the limit allows (ruling 7 of 0.11): a failure of the wire.
func (d *decodeState) overLimit(list string, n uint64) error {
	what := ""
	if list != "" {
		what = "list " + list + ": "
	}
	return &Error{Kind: ErrMalformedWire, Format: d.pack.Format, Detail: fmt.Sprintf("%s%d more item(s) would exceed the limit of %d list items (%d held)", what, n, d.limit, d.held)}
}

// room checks, before any item is read, that n more items fit the limit
// (ruling 7d of 0.11). It takes nothing.
func (d *decodeState) room(list string, n uint64) error {
	if n > uint64(d.limit-d.held) {
		return d.overLimit(list, n)
	}
	return nil
}

// replacing releases the items of a list the record already holds, which
// the group being read replaces (ruling 7g of 0.11).
func (d *decodeState) replacing(list string) {
	if old, ok := d.rec.Lists[list]; ok {
		d.held -= deepItems(old)
	}
}

// deepItems counts the items of a list and of every list inside them.
func deepItems(items []*Item) int64 {
	n := int64(len(items))
	for _, it := range items {
		for _, l := range it.Lists {
			n += deepItems(l)
		}
	}
	return n
}

// item decodes one item of a group: read fills a new item, which is returned.
// The item counts against the limit on list items before it is read (ruling
// 7 of 0.11).
func (d *decodeState) item(read func() error) (*Item, error) {
	if d.held >= d.limit {
		return nil, d.overLimit("", 1)
	}
	d.held++
	saved := d.rec
	it := NewItem()
	d.rec = it
	err := read()
	d.rec = saved
	return it, err
}

// choose selects the layout a decode reads: every common `when` must hold,
// then the first kind in pack order whose every `when` holds. holds reports
// whether one `when` line holds on the wire being decoded.
func (d *decodeState) choose(holds func(*When) bool) (*layout, error) {
	return d.chooseAmong(nil, false, holds)
}

// chooseAmong is choose over the kinds whose indexes are in among, in pack
// order, when restrict is set (the xml wire considers a kind only when the
// document's root element has the kind's root name).
func (d *decodeState) chooseAmong(among []int, restrict bool, holds func(*When) bool) (*layout, error) {
	p := d.pack
	if !p.HasKinds() {
		return p.layouts[0], nil
	}
	for _, w := range p.commonWhens {
		if !holds(w) {
			return nil, &Error{Kind: ErrNoKind, Format: p.Format, Locator: w.Locator, Detail: fmt.Sprintf("the message does not hold %q at the common when on line %d", w.Value, w.Line)}
		}
	}
	try := func(i int) bool {
		for _, w := range p.Kinds[i].whens {
			if !holds(w) {
				return false
			}
		}
		return true
	}
	if restrict {
		for _, i := range among {
			if try(i) {
				d.ent.Kind = EntityKind{Format: p.Format, Name: p.Kinds[i].Name}
				return p.layouts[i], nil
			}
		}
	} else {
		for i := range p.Kinds {
			if try(i) {
				d.ent.Kind = EntityKind{Format: p.Format, Name: p.Kinds[i].Name}
				return p.layouts[i], nil
			}
		}
	}
	return nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: "the message matches no kind of the format"}
}

// chooseEncode selects the layout an encode writes.
func chooseEncode(p *Pack, ent *Entity) (*layout, error) {
	if !p.HasKinds() {
		return p.layouts[0], nil
	}
	if ent.Kind.Format == p.Format {
		for i, k := range p.Kinds {
			if k.Name == ent.Kind.Name {
				return p.layouts[i], nil
			}
		}
		// The entity names this format and a kind the pack does not have
		// (0.5 ruling 24).
		return nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: fmt.Sprintf("the entity names kind %q, which the format does not have", ent.Kind.Name)}
	}
next:
	for i, k := range p.Kinds {
		// A required key is present; a required list is present and has at
		// least one item.
		for _, key := range k.Requires {
			if _, ok := ent.Fields[key]; !ok && len(ent.Lists[key]) == 0 {
				continue next
			}
		}
		return p.layouts[i], nil
	}
	return nil, &Error{Kind: ErrNoKind, Format: p.Format, Detail: "the entity has the required keys of no kind of the format"}
}

func (d *decodeState) residue(loc, val string, isJSON bool) {
	d.ent.Residue = append(d.ent.Residue, ResidueEntry{Format: d.pack.Format, Locator: loc, Value: val, JSON: isJSON})
}

// field decodes one mapped text value.
func (d *decodeState) field(f *Field, raw string) {
	if _, done := d.rec.Fields[f.Key]; done {
		return
	}
	v, err := f.tf.decode(raw)
	if err != nil {
		d.fail(f, err.Error())
		return
	}
	d.store(f, v)
}

// store puts one decoded value in the entity: through the field's value
// table when it has one, and through the pack's typemap when the key is
// `type`. An unmapped native code passes through unchanged and is not
// residue. The first value a key receives stays: a key mapped by several
// lines takes its value from the earliest line that yields one.
func (d *decodeState) store(f *Field, v Value) {
	if _, done := d.rec.Fields[f.Key]; done {
		return
	}
	if f.table != nil {
		mv, err := f.viaDecode(v)
		if err != nil {
			d.fail(f, err.Error())
			d.failedHard[len(d.failedHard)-1] = true
			return
		}
		v = mv
	}
	if f.Key == "type" && d.pack.TypeMapped() && v.Kind == KindString {
		if cot, ok := d.pack.nativeToCot[v.S]; ok {
			v.S = cot
		}
	}
	d.rec.Fields[f.Key] = v
}

func (d *decodeState) fail(f *Field, detail string) {
	d.failed = append(d.failed, &Error{Kind: ErrTransformDecode, Format: d.pack.Format, Locator: f.Locator, Detail: "field " + f.Key + " (" + f.Transform + "): " + detail})
	d.failedKey = append(d.failedKey, f.Key)
	d.failedIn = append(d.failedIn, d.rec)
	d.failedHard = append(d.failedHard, false)
}

// bindTable indexes the field's value table for the two directions. Both
// sides are compared as canonical text: an integer as decimal digits, a float
// as the shortest round-trip decimal. Of several entries sharing a value the
// first is used.
func (f *Field) bindTable() {
	if f.table == nil {
		return
	}
	f.viaDec, f.viaEnc = map[string]string{}, map[string]string{}
	for _, e := range f.table.entries {
		if n := canonText(e.native, f.yields); !hasKey(f.viaDec, n) {
			f.viaDec[n] = e.model
		}
		if m := canonText(e.model, f.keyType); !hasKey(f.viaEnc, m) {
			f.viaEnc[m] = e.native
		}
	}
}

func hasKey(m map[string]string, k string) bool { _, ok := m[k]; return ok }

// canonText is the canonical text of a table value read as kind; text that
// does not read as that kind is compared as written.
func canonText(text string, kind Kind) string {
	if kind == KindInt || kind == KindFloat {
		if v, err := readAs(text, kind); err == nil {
			return v.String()
		}
	}
	return text
}

// viaDecode passes a value the transform yielded through the field's table:
// the entry's model side, read as the key's declared type. A value with no
// entry passes through when the two types are the same.
func (f *Field) viaDecode(v Value) (Value, error) {
	if m, ok := f.viaDec[v.String()]; ok {
		mv, err := readAs(m, f.keyType)
		if err != nil {
			return Value{}, fmt.Errorf("table %s: %v", f.table.name, err)
		}
		return mv, nil
	}
	if f.yields == f.keyType {
		return v, nil
	}
	return Value{}, fmt.Errorf("table %s has no entry for wire value %q", f.table.name, v.String())
}

// viaEncode is the reverse: the entry's native side, read as the type the
// transform yields.
func (f *Field) viaEncode(v Value) (Value, error) {
	if n, ok := f.viaEnc[v.String()]; ok {
		nv, err := readAs(n, f.yields)
		if err != nil {
			return Value{}, fmt.Errorf("table %s: %v", f.table.name, err)
		}
		return nv, nil
	}
	if f.yields == f.keyType {
		return v, nil
	}
	return Value{}, fmt.Errorf("table %s has no entry for model value %q", f.table.name, v.String())
}

// fieldValue returns the value an encode writes for a field: the entity's
// value, else the default in scope; the `type` key mapped back to the
// format's native code; then the field's value table. ok is false when there
// is neither a value nor a default.
func fieldValue(p *Pack, lay *layout, f *Field, rec *Item) (Value, bool, error) {
	v, ok := rec.Fields[f.Key]
	if !ok {
		d := lay.defaults[f.Key]
		if d == nil {
			return Value{}, false, nil
		}
		v = d.val
	}
	if f.Key == "type" && p.TypeMapped() && v.Kind == KindString {
		if native, ok := p.cotToNative[v.S]; ok {
			v.S = native
		}
	}
	if f.table != nil {
		nv, err := f.viaEncode(v)
		if err != nil {
			return Value{}, false, encodeErr(p, f, err)
		}
		v = nv
	}
	return v, true, nil
}

func encodeErr(p *Pack, f *Field, err error) error {
	return &Error{Kind: ErrTransformEncode, Format: p.Format, Locator: f.Locator, Detail: "field " + f.Key + " (" + f.Transform + "): " + err.Error()}
}

// encodeField returns the wire text for a field, or ok=false when there is
// no value for it.
func encodeField(p *Pack, lay *layout, f *Field, rec *Item) (string, bool, error) {
	v, ok, err := fieldValue(p, lay, f, rec)
	if err != nil || !ok {
		return "", false, err
	}
	s, err := f.tf.encode(v)
	if err != nil {
		return "", false, encodeErr(p, f, err)
	}
	return s, true, nil
}

// residueFor returns the residue entries that belong to pack p and whose
// locator no written field already covered.
func residueFor(p *Pack, ent *Entity, written map[string]bool) []ResidueEntry {
	var out []ResidueEntry
	for _, r := range ent.Residue {
		if r.Format != p.Format || written[r.Locator] {
			continue
		}
		out = append(out, r)
	}
	return out
}
