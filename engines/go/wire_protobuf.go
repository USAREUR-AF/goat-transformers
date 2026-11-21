//go:build !goat_wires || goat_wire_protobuf

package goatxf

// The protobuf wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_protobuf.
func init() {
	registerWire(WireProtobuf, &wireCodec{
		decode: decodeProtobuf,
		encode: func(p *Pack, lay *layout, _ *Entity, rec *Item) ([]byte, error) { return encodeProtobuf(p, lay, rec) },
	})
}
