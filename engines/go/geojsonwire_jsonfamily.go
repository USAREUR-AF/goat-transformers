//go:build !goat_wires || goat_wire_json || goat_wire_geojson

package goatxf

// The declarations of geojsonwire.go that the json and the geojson wire both
// use: they are in a build that has either wire (spec/engine-spec.md,
// Version 0.24).

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"unicode/utf8"
)

func (v *jval) member(key string) *jval {
	for i, k := range v.keys {
		if k == key {
			return v.vals[i]
		}
	}
	return nil
}

// parseJSON reads one JSON value. A member name that occurs twice in one
// object is an error unless allowDup is set (the json wire refuses it, 0.5
// ruling 22; the geojson wire keeps its 0.1 behaviour and accepts it, ruling
// 28): the later value then replaces the earlier one, at the earlier position.
func parseJSON(b []byte, allowDup bool) (*jval, error) {
	// RFC 8259 text is UTF-8; the decoder below would replace a byte that is
	// not with U+FFFD instead of refusing it.
	if !utf8.Valid(b) {
		return nil, fmt.Errorf("the input is not valid UTF-8")
	}
	if jsonLoneSurrogate(b) {
		return nil, fmt.Errorf("a \\u escape is half of a surrogate pair without its other half")
	}
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	v, err := readJSON(dec, allowDup, 1)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("trailing data after the Feature")
	}
	return v, nil
}

// readJSON reads one value; level is the nesting level an array or an object
// read here has (the outermost is level 1, 0.8 ruling 35).
// jsonLoneSurrogate reports whether a string of the JSON text b holds a \u
// escape that is half of a surrogate pair without its other half (0.8 ruling
// 40); the decoder would read it as U+FFFD. The scan follows strings and
// escapes only: the decoder checks the rest of the grammar.
func jsonLoneSurrogate(b []byte) bool {
	// escape reads the \uXXXX escape at i, -1 when there is none.
	escape := func(i int) int {
		if i+6 > len(b) || b[i] != '\\' || b[i+1] != 'u' {
			return -1
		}
		n := 0
		for _, c := range b[i+2 : i+6] {
			switch {
			case c >= '0' && c <= '9':
				n = n<<4 | int(c-'0')
			case c >= 'a' && c <= 'f':
				n = n<<4 | int(c-'a'+10)
			case c >= 'A' && c <= 'F':
				n = n<<4 | int(c-'A'+10)
			default:
				return -1
			}
		}
		return n
	}
	inString := false
	for i := 0; i < len(b); i++ {
		switch {
		case !inString:
			inString = b[i] == '"'
		case b[i] == '"':
			inString = false
		case b[i] == '\\':
			n := escape(i)
			switch {
			case n < 0:
				i++ // the escaped character
			case n >= 0xdc00 && n <= 0xdfff:
				return true // a low half with no high half before it
			case n >= 0xd800 && n <= 0xdbff:
				if lo := escape(i + 6); lo < 0xdc00 || lo > 0xdfff {
					return true
				}
				i += 11
			default:
				i += 5
			}
		}
	}
	return false
}

func readJSON(dec *json.Decoder, allowDup bool, level int) (*jval, error) {
	tok, err := dec.Token()
	if err != nil {
		if errors.Is(err, io.EOF) {
			return nil, fmt.Errorf("unexpected end of input")
		}
		return nil, err
	}
	switch t := tok.(type) {
	case json.Delim:
		if (t == '{' || t == '[') && level > maxNesting {
			return nil, fmt.Errorf("arrays and objects are nested deeper than %d levels", maxNesting)
		}
		switch t {
		case '{':
			o := &jval{k: jObj}
			seen := map[string]int{}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				key, ok := kt.(string)
				if !ok {
					return nil, fmt.Errorf("object key is not a string")
				}
				at, dup := seen[key]
				if dup && !allowDup {
					return nil, fmt.Errorf("duplicate member %q", key)
				}
				val, err := readJSON(dec, allowDup, level+1)
				if err != nil {
					return nil, err
				}
				if dup {
					o.vals[at] = val
					continue
				}
				seen[key] = len(o.keys)
				o.keys = append(o.keys, key)
				o.vals = append(o.vals, val)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return o, nil
		case '[':
			a := &jval{k: jArr}
			for dec.More() {
				val, err := readJSON(dec, allowDup, level+1)
				if err != nil {
					return nil, err
				}
				a.vals = append(a.vals, val)
			}
			if _, err := dec.Token(); err != nil {
				return nil, err
			}
			return a, nil
		}
		return nil, fmt.Errorf("unexpected %q", t.String())
	case string:
		return &jval{k: jStr, s: t}, nil
	case json.Number:
		return &jval{k: jNum, s: t.String()}, nil
	case bool:
		if t {
			return &jval{k: jBool, s: "true"}, nil
		}
		return &jval{k: jBool, s: "false"}, nil
	case nil:
		return &jval{k: jNull}, nil
	}
	return nil, fmt.Errorf("unexpected token %v", tok)
}
