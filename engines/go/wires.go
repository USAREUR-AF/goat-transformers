package goatxf

import (
	"fmt"
	"sort"
	"strings"
)

// The wires of a build (spec/engine-spec.md, "Version 0.24: builds with fewer
// wires"). The codec of each wire is in files that carry the build constraint
// `!goat_wires || goat_wire_<wire>`, and its file wire_<wire>.go registers it
// here from an init function. A build with no tags has all eight wires; a
// build with the tag goat_wires has only the wires named by a tag
// goat_wire_<wire>, for example
//
//	go build -tags goat_wires,goat_wire_xml,goat_wire_json,goat_wire_geojson
//
// The pack language (the loader and its line checks) is part of every build,
// so a pack on a wire of the build loads, and fails, exactly as in a build
// with all eight (ruling 1b).

// allWires are the wires of the specification.
var allWires = []string{WireXML, WireGeoJSON, WireJSON, WireBits, WireProtobuf, WireText, WireTLV, WireCBOR}

// wireCodec reads and writes the messages of one wire.
type wireCodec struct {
	decode func(d *decodeState, b []byte) error
	// encode writes one message of a pack with a fixed layout or no layout.
	encode func(p *Pack, lay *layout, ent *Entity, rec *Item) ([]byte, error)
	// encodeWhole writes a message of a pack with `layout sequential`; nil on
	// a wire that has no sequential layout.
	encodeWhole func(e *Engine, p *Pack, ent *Entity) ([]byte, error)
	// encodeRun writes a carrier from its outer entity and the joined entities
	// of its messages, and runKind chooses its kind on the outer entity: the
	// kind's name and the inner format of its `run` line, "" for none (0.92);
	// nil on a wire that has no sequential layout.
	encodeRun func(e *Engine, p *Pack, outer *Entity, msgs []*Entity) ([]byte, error)
	runKind   func(p *Pack, outer *Entity) (kind, format string, err error)
}

// codecs holds the codec of every wire of this build.
var codecs = map[string]*wireCodec{}

func registerWire(wire string, c *wireCodec) {
	codecs[wire] = c
}

// BuiltWires returns the wires this build has, in the order of the
// specification.
func BuiltWires() []string {
	var out []string
	for _, w := range allWires {
		if codecs[w] != nil {
			out = append(out, w)
		}
	}
	return out
}

// missingWireDetail is the message of the unknown-wire error a pack raises
// when its wire is a wire of the specification that this build lacks (ruling
// 1c of 0.24).
func missingWireDetail(wire string) string {
	built := BuiltWires()
	sort.Strings(built)
	return fmt.Sprintf("wire %q is a wire of the specification, but this build does not have it (built with the wires %s)",
		wire, strings.Join(built, ", "))
}

// builtCodec returns the codec of a loaded pack's wire. A pack on a wire this
// build lacks never loads, so the error is not reached.
func builtCodec(p *Pack) (*wireCodec, error) {
	c := codecs[p.Wire]
	if c == nil {
		return nil, &Error{Kind: ErrUnknownWire, Format: p.Format, Detail: missingWireDetail(p.Wire)}
	}
	return c, nil
}
