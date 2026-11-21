package goatxf

// The declarations of geojsonwire.go that the pack loader, the transforms or
// another wire use: they are in every build, whatever its set of wires
// (spec/engine-spec.md, Version 0.24).

import (
	"bytes"
	"encoding/json"
	"strings"
)

type jkind int

const (
	jObj jkind = iota + 1
	jArr
	jStr
	jNum
	jBool
	jNull
)

// jval is an order-preserving JSON value; s holds a string's text, a number's
// literal, or "true"/"false".
type jval struct {
	k    jkind
	s    string
	keys []string
	vals []*jval
	// mapped is set when a field line reads this value (0.15 ruling 27).
	mapped bool
}

func jsonString(s string) string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(s)
	return strings.TrimSuffix(b.String(), "\n")
}
