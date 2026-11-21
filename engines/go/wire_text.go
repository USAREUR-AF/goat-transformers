//go:build !goat_wires || goat_wire_text

package goatxf

// The text wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_text.
func init() {
	registerWire(WireText, &wireCodec{
		decode: decodeText,
		encode: encodeText,
	})
}
