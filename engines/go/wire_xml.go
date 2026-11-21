//go:build !goat_wires || goat_wire_xml

package goatxf

// The xml wire is in this build (spec/engine-spec.md, Version 0.24): without
// the tag goat_wires, or with the tag goat_wire_xml.
func init() {
	registerWire(WireXML, &wireCodec{
		decode: decodeXML,
		encode: encodeXML,
	})
}
