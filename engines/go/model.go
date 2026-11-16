package goatxf

import "strconv"

// Kind is the type of a shared-model value.
type Kind int

const (
	KindString Kind = iota + 1
	KindInt
	KindFloat
)

// Value is one typed shared-model value (spec/shared-model.md).
type Value struct {
	Kind Kind
	S    string
	I    int64
	F    float64
}

// String renders the value in the string form vectors use.
func (v Value) String() string {
	switch v.Kind {
	case KindInt:
		return strconv.FormatInt(v.I, 10)
	case KindFloat:
		s, err := formatFloat(v.F)
		if err != nil {
			return strconv.FormatFloat(v.F, 'g', -1, 64)
		}
		return s
	default:
		return v.S
	}
}

// ResidueEntry is one wire item no field line maps, kept so a same-format
// round trip reproduces it. Format is the pack that produced it; encode to any
// other format ignores it. JSON is true when Value is raw JSON text (a geojson
// member that was not a string).
type ResidueEntry struct {
	Format  string
	Locator string
	Value   string
	JSON    bool
}

// EntityKind is the message kind a decode selected: the format and the kind
// name (spec/engine-spec.md, "Version 0.5"). The zero value means no kind.
type EntityKind struct {
	Format string
	Name   string
}

// Item is one item of a list (spec/engine-spec.md, "Version 0.7: groups"): it
// holds model keys and lists exactly as an entity does, without residue and
// without a kind.
type Item struct {
	Fields map[string]Value
	Lists  map[string][]*Item
}

// NewItem returns an empty item.
func NewItem() *Item { return &Item{Fields: map[string]Value{}} }

// SetList sets a list of the item. A list set with no items is present and
// empty, which is distinct from a list that was never set.
func (it *Item) SetList(name string, items []*Item) {
	if it.Lists == nil {
		it.Lists = map[string][]*Item{}
	}
	if items == nil {
		items = []*Item{}
	}
	it.Lists[name] = items
}

// List returns a list of the item and whether it is present.
func (it *Item) List(name string) ([]*Item, bool) {
	l, ok := it.Lists[name]
	return l, ok
}

// Entity is the shared model: named fields and lists plus residue, and the
// kind the decode selected when the source pack has kinds. Lists maps a list
// name to its items; a list that is present and empty is distinct from an
// absent one.
type Entity struct {
	Fields  map[string]Value
	Lists   map[string][]*Item
	Residue []ResidueEntry
	Kind    EntityKind
}

// NewEntity returns an empty entity.
func NewEntity() *Entity { return &Entity{Fields: map[string]Value{}} }

// Get returns a field value and whether it is present.
func (e *Entity) Get(key string) (Value, bool) {
	v, ok := e.Fields[key]
	return v, ok
}

// List returns a list of the entity and whether it is present.
func (e *Entity) List(name string) ([]*Item, bool) {
	l, ok := e.Lists[name]
	return l, ok
}

// SetList sets a list of the entity; no items makes it present and empty.
func (e *Entity) SetList(name string, items []*Item) {
	it := e.item()
	it.SetList(name, items)
	e.Lists = it.Lists
}

// item views the entity's own keys and lists as an item, sharing its maps.
func (e *Entity) item() *Item { return &Item{Fields: e.Fields, Lists: e.Lists} }
