package goatxf

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"runtime/debug"
	"sort"
	"strconv"
	"strings"
	"testing"
)

// namedKind matches the start of every error message the engine returns: an
// error kind and a colon.
var namedKind = regexp.MustCompile(`^[a-z][a-z0-9]*(-[a-z0-9]+)+:`)

// convertGuarded runs one conversion and turns a panic into a returned text.
func convertGuarded(eng *Engine, from, to string, in []byte, ctx map[string]string) (out []byte, err error, panicked string) {
	defer func() {
		if r := recover(); r != nil {
			panicked = fmt.Sprint(r)
		}
	}()
	out, err = eng.ConvertWith(from, to, in, ctx)
	return out, err, ""
}

// TestMalformedInputNeverPanics feeds the input of every conversion vector of
// every loaded pack, cut at prefixes and with single bytes changed, to
// convert. No input may make the engine panic, and every error must begin
// with a named kind and a colon (spec/engine-spec.md, "Malformed input").
// On the json and geojson wires an input that converts must be RFC 8259 text.
// The seed is fixed, so every run feeds the same inputs.
func TestMalformedInputNeverPanics(t *testing.T) {
	// Inputs per vector and per form. GOAT_XF_MALFORMED_N raises it for a
	// longer run; the default keeps the test to a few seconds.
	perVector := 2
	if s := os.Getenv("GOAT_XF_MALFORMED_N"); s != "" {
		n, err := strconv.Atoi(s)
		if err != nil || n < 1 {
			t.Fatalf("GOAT_XF_MALFORMED_N must be a number >= 1, got %q", s)
		}
		perVector = n
	}
	maxPrefixes, maxMutations := perVector, perVector
	const hexDigits = "0123456789abcdefABCDEF"
	eng, err := Load(packsDir)
	if err != nil {
		t.Fatalf("loading packs from %s: %v", packsDir, err)
	}
	files, err := filepath.Glob(filepath.Join(packsDir, "*", "vectors", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(files)
	rng := rand.New(rand.NewSource(0x60a7))
	inputs, failures := 0, 0
	for _, file := range files {
		raw, err := os.ReadFile(file)
		if err != nil {
			t.Fatal(err)
		}
		var v vector
		if err := json.Unmarshal(raw, &v); err != nil {
			t.Fatalf("%s: %v", file, err)
		}
		p, err := eng.Pack(v.From)
		if err != nil {
			continue
		}
		in := bytesOf(t, v.Input, v.InputB64, "input")
		hexWire := p.Wire == WireBits || p.Wire == WireProtobuf
		jsonWire := p.Wire == WireJSON || p.Wire == WireGeoJSON
		try := func(what string, b []byte) {
			inputs++
			_, err, panicked := convertGuarded(eng, v.From, v.To, b, v.Context)
			var problem string
			switch {
			case panicked != "":
				problem = "panic: " + panicked
			case err != nil && !namedKind.MatchString(err.Error()):
				problem = fmt.Sprintf("error %q does not begin with a named kind and a colon", err.Error())
			case err == nil && jsonWire && !json.Valid(b):
				problem = "the input is not RFC 8259 text and it converted"
			}
			if problem != "" {
				failures++
				if failures <= 20 {
					t.Errorf("%s (%s) input %q: %s", file, what, b, problem)
				}
			}
		}
		// Prefixes, each shorter than the input.
		for k := 0; k < maxPrefixes && len(in) > 0; k++ {
			try("prefix", in[:rng.Intn(len(in))])
		}
		// Single bytes changed. On a hex wire two changes in three stay hex
		// digits, so the change reaches the message and not only the hex text.
		for k := 0; k < maxMutations && len(in) > 0; k++ {
			m := append([]byte(nil), in...)
			at := rng.Intn(len(m))
			c := byte(rng.Intn(256))
			if hexWire && k%3 != 0 {
				c = hexDigits[rng.Intn(len(hexDigits))]
			}
			if c == m[at] {
				c ^= 0x01
			}
			m[at] = c
			try("byte changed", m)
		}
	}
	summary := fmt.Sprintf("malformed-input inputs: %d fed, %d failed", inputs, failures)
	fmt.Println(summary)
	t.Log(summary)
}

// TestMalformedRulings holds the cases of 0.8 rulings 35 to 39 that no
// vector pins, on the conformance-malformed packs.
func TestMalformedRulings(t *testing.T) {
	eng, err := Load(packsDir)
	if err != nil {
		t.Fatalf("loading packs from %s: %v", packsDir, err)
	}
	const (
		jsonPack = "conformance-malformed-json"
		geoPack  = "conformance-malformed-geojson"
		xmlPack  = "conformance-malformed-xml"
		pbPack   = "conformance-malformed-protobuf"
		bitsPack = "conformance-malformed-bits"
		// probe.nums is field 3.1 and probe.deltas field 6, both packed.
		groupsPBPack = "conformance-groups-protobuf"
	)
	deep := 200000
	cases := []struct {
		name, pack, input string
		ok                bool
	}{
		// Ruling 35: a nesting that would exhaust a recursive reader.
		{"json deep arrays", jsonPack, `{"id":"u1","a":` + strings.Repeat("[", deep) + strings.Repeat("]", deep) + `}`, false},
		{"json deep arrays unclosed", jsonPack, `{"id":"u1","a":` + strings.Repeat("[", deep), false},
		{"json deep objects unclosed", jsonPack, strings.Repeat(`{"a":`, deep), false},
		{"geojson deep arrays unclosed", geoPack, `{"type":"Feature","geometry":null,"properties":{"x":` + strings.Repeat("[", deep), false},
		{"xml deep elements", xmlPack, `<event uid="u1">` + strings.Repeat("<a>", deep) + strings.Repeat("</a>", deep) + `</event>`, false},
		{"xml deep elements unclosed", xmlPack, strings.Repeat("<event>", deep), false},
		{"json array of 64 levels", jsonPack, `{"id":"u1","a":` + strings.Repeat("[", 63) + strings.Repeat("]", 63) + `}`, true},
		{"json array of 65 levels", jsonPack, `{"id":"u1","a":` + strings.Repeat("[", 64) + strings.Repeat("]", 64) + `}`, false},
		// Ruling 36: hex text.
		{"bits hex with a minus sign", bitsPack, "0100000002000-10", false},
		{"bits hex with a 0x prefix", bitsPack, "0x0100000002000000", false},
		{"bits one hex digit", bitsPack, "0", false},
		{"protobuf hex with a sign", pbPack, "0a02753110+5", false},
		{"protobuf hex with whitespace", pbPack, "0a 02 75 31\n10 05\n", true},
		// Ruling 37: an input with no element.
		{"xml whitespace only", xmlPack, " \n", false},
		{"xml declaration only", xmlPack, `<?xml version="1.0"?>`, false},
		{"xml comment only", xmlPack, `<!-- nothing -->`, false},
		{"xml comment after the root", xmlPack, `<event uid="u1"/><!-- end --> `, true},
		{"xml doctype after the root", xmlPack, `<event uid="u1"/><!DOCTYPE event>`, false},
		// Ruling 40.
		{"bits hex with a form feed", bitsPack, "01000000\f02000000", false},
		{"bits hex with a vertical tab", bitsPack, "01000000\v02000000", false},
		{"bits hex with a no-break space", bitsPack, "01000000\u00a002000000", false},
		{"bits hex with space, tab, LF and CR", bitsPack, " 0100\t0000\r\n02000000 ", true},
		{"protobuf ten-byte varint with last byte 1", pbPack, "0a02753110ffffffffffffffffff01", true},
		{"protobuf ten-byte varint with last byte 2", pbPack, "0a02753110ffffffffffffffffff02", false},
		{"protobuf ten-byte varint with last byte 0x7f", pbPack, "0a02753110ffffffffffffffffff7f", false},
		{"protobuf ten-byte tag with last byte 2", pbPack, "0a027531" + "80808080808080808002" + "00", false},
		{"protobuf ten-byte length with last byte 2", pbPack, "0a80808080808080808002", false},
		{"protobuf packed field", groupsPBPack, "0a0161" + "32020102", true},
		{"protobuf truncated varint in a packed field", groupsPBPack, "0a0161" + "32020180", false},
		{"protobuf ten-byte varint with last byte 2 in a packed field", groupsPBPack, "0a0161" + "320a" + "ffffffffffffffffff02", false},
		{"protobuf truncated varint in a packed field in a submessage", groupsPBPack, "0a0161" + "1a03" + "0a0180", false},
		{"json surrogate pair", jsonPack, `{"id":"\ud83d\ude00"}`, true},
		{"json high half alone", jsonPack, `{"id":"\ud83d"}`, false},
		{"json low half alone", jsonPack, `{"id":"\ude00"}`, false},
		{"json high half then another escape", jsonPack, `{"id":"\ud83d\u0041"}`, false},
		{"json high half then a character", jsonPack, `{"id":"\ud83dx"}`, false},
		{"json two high halves", jsonPack, `{"id":"\ud83d\ud83d"}`, false},
		{"json halves in the wrong order", jsonPack, `{"id":"\ude00\ud83d"}`, false},
		{"json high half alone in a member name", jsonPack, `{"id":"u1","\uD83D":1}`, false},
		{"json high half alone in a member no line maps", jsonPack, `{"id":"u1","other":["\udbff"]}`, false},
		{"json escaped backslash before u", jsonPack, `{"id":"\\ud83d"}`, true},
		{"geojson low half alone", geoPack, `{"type":"Feature","geometry":null,"properties":{"name":"\udc00"}}`, false},
		{"xml doctype before the root", xmlPack, `<!DOCTYPE event><event uid="u1"/>`, false},
		{"xml doctype that declares an entity", xmlPack, `<!DOCTYPE event [<!ENTITY a "b">]><event uid="&a;"/>`, false},
		{"xml doctype with an external entity", xmlPack, `<!DOCTYPE event [<!ENTITY a SYSTEM "file:///etc/hosts">]><event uid="&a;"/>`, false},
		{"xml doctype inside the root", xmlPack, `<event uid="u1"><!DOCTYPE event></event>`, false},
		{"xml entity that is not predefined", xmlPack, `<event uid="&nbsp;"/>`, false},
		{"xml entity that is not predefined in text", xmlPack, `<event uid="u1"><a>&foo;</a></event>`, false},
		{"xml predefined entities", xmlPack, `<event uid="&amp;&lt;&gt;&quot;&apos;"/>`, true},
		{"xml decimal and hexadecimal references", xmlPack, `<event uid="&#65;&#x42;&#x1F600;"/>`, true},
		{"xml reference with a plus sign", xmlPack, `<event uid="&#+65;"/>`, false},
		{"xml reference with a minus sign", xmlPack, `<event uid="&#-65;"/>`, false},
		{"xml hexadecimal reference with a sign", xmlPack, `<event uid="&#x+41;"/>`, false},
		{"xml hexadecimal reference with a capital X", xmlPack, `<event uid="&#X41;"/>`, false},
		{"xml reference with no digits", xmlPack, `<event uid="&#;"/>`, false},
		{"xml reference with an underscore", xmlPack, `<event uid="&#6_5;"/>`, false},
		{"xml reference to U+0000", xmlPack, `<event uid="&#0;"/>`, false},
		{"xml reference to U+0008", xmlPack, `<event uid="&#8;"/>`, false},
		{"xml reference to a surrogate", xmlPack, `<event uid="&#xD800;"/>`, false},
		{"xml decimal reference to a surrogate", xmlPack, `<event uid="&#57343;"/>`, false},
		{"xml reference to a surrogate in text", xmlPack, `<event uid="u1"><a>&#xdfff;</a></event>`, false},
		{"xml reference to U+FFFE", xmlPack, `<event uid="&#xFFFE;"/>`, false},
		{"xml reference beyond U+10FFFF", xmlPack, `<event uid="&#x110000;"/>`, false},
		{"xml reference to U+FFFD", xmlPack, `<event uid="&#xFFFD;"/>`, true},
		{"xml surrogate reference text in a comment", xmlPack, `<event uid="u1"><!-- &#xD800; --></event>`, true},
		{"xml surrogate reference text in a CDATA section", xmlPack, `<event uid="u1"><a><![CDATA[&#xD800;]]></a></event>`, true},
		// Ruling 38: protobuf syntax.
		{"protobuf wire type 3", pbPack, "0a0275313300", false},
		{"protobuf wire type 4", pbPack, "0a02753134", false},
		{"protobuf wire type 6", pbPack, "0a0275313600", false},
		{"protobuf wire type 7", pbPack, "0a0275313700", false},
		{"protobuf field number 0", pbPack, "0a0275310000", false},
		{"protobuf field number 2^29-1", pbPack, "0a027531f8ffffff0f00", true},
		{"protobuf field number 2^29", pbPack, "0a027531808080801000", false},
		{"protobuf field number 2^61-1", pbPack, "0a027531f8ffffffffffffffff0100", false},
		{"protobuf wire type 3 in a submessage a path walks into", pbPack, "0a0275312202 0b00", false},
		{"protobuf truncated varint in a submessage a path walks into", pbPack, "0a0275312202 1080", false},
		{"protobuf fixed64 cut short in a submessage a path walks into", pbPack, "0a0275312203 190000", false},
		{"protobuf bytes of an unmapped field are not parsed", pbPack, "0a0275314a02 0b00", true},
		// Ruling 39: JSON grammar.
		{"json leading zero", jsonPack, `{"id":"u1","pos":{"lat":01.5}}`, false},
		{"json leading zero after a minus", jsonPack, `{"id":"u1","pos":{"lat":-01}}`, false},
		{"json leading plus", jsonPack, `{"id":"u1","pos":{"lat":+1.5}}`, false},
		{"json bare point", jsonPack, `{"id":"u1","pos":{"lat":.5}}`, false},
		{"json point with no fraction", jsonPack, `{"id":"u1","pos":{"lat":1.}}`, false},
		{"json exponent with no digits", jsonPack, `{"id":"u1","pos":{"lat":1e}}`, false},
		{"json unknown escape", jsonPack, `{"id":"u\x"}`, false},
		{"json raw control character in a string", jsonPack, "{\"id\":\"u\n1\"}", false},
		{"json raw control character in a member name", jsonPack, "{\"i\td\":\"u1\"}", false},
		{"json unicode escape with a non-hex digit", jsonPack, `{"id":"\u00zz"}`, false},
		{"json single quotes", jsonPack, `{'id':'u1'}`, false},
		{"json trailing comma", jsonPack, `{"id":"u1",}`, false},
		{"json literal in another case", jsonPack, `{"id":"u1","flag":True}`, false},
		{"json byte that is not UTF-8", jsonPack, "{\"id\":\"u\xff\"}", false},
		{"json grammar in a member no line maps", jsonPack, `{"id":"u1","other":[1,02]}`, false},
		{"geojson leading zero", geoPack, `{"type":"Feature","geometry":{"type":"Point","coordinates":[02.5,1.5]},"properties":{}}`, false},
		{"geojson unknown escape", geoPack, `{"type":"Feature","geometry":null,"properties":{"name":"\q"}}`, false},
		{"json escapes of RFC 8259", jsonPack, `{"id":"\"\\\/\b\f\n\r\tA"}`, true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			in := []byte(c.input)
			_, err, panicked := convertGuarded(eng, c.pack, c.pack, in, nil)
			if len(in) > 200 {
				in = append(in[:200:200], "..."...)
			}
			switch {
			case panicked != "":
				t.Fatalf("panic on %q: %s", in, panicked)
			case c.ok && err != nil:
				t.Errorf("convert %q: %v, want it to convert", in, err)
			case !c.ok && err == nil:
				t.Errorf("convert %q succeeded, want %s", in, ErrMalformedWire)
			case !c.ok && (!IsKind(err, ErrMalformedWire) || !strings.HasPrefix(err.Error(), string(ErrMalformedWire)+":")):
				t.Errorf("convert %q: got %v, want %s", in, err, ErrMalformedWire)
			}
			// decode fails the same way.
			if !c.ok {
				if _, derr := eng.Decode(c.pack, []byte(c.input)); !IsKind(derr, ErrMalformedWire) {
					t.Errorf("decode: got %v, want %s", derr, ErrMalformedWire)
				}
			}
		})
	}
	// An error is never the bare text of a reader.
	if _, err := eng.Decode(xmlPack, bytes.Repeat([]byte{0xff}, 8)); err == nil || !namedKind.MatchString(err.Error()) {
		t.Errorf("xml bytes that are not UTF-8: got %v, want a named kind", err)
	}
}

// TestHeapPerListItem measures the heap a decode of conformance-seq-groups
// takes per item of a long, valid `while` list: what the returned entity
// holds, and everything the decode allocated (the peak when the collector
// does not run). It runs when GOAT_XF_HEAP is set.
func TestHeapPerListItem(t *testing.T) {
	if os.Getenv("GOAT_XF_HEAP") == "" {
		t.Skip("set GOAT_XF_HEAP=1 to measure")
	}
	eng, err := Load(packsDir)
	if err != nil {
		t.Fatal(err)
	}
	for _, n := range []int{10000, 100000, 1000000} {
		// n, no nums, then per item one byte: the 1 bit, qty 1, no subs.
		in := []byte("0100" + strings.Repeat("82", n) + "0000")
		runtime.GC()
		old := debug.SetGCPercent(-1)
		var before, after, kept runtime.MemStats
		runtime.ReadMemStats(&before)
		ent, err := eng.Decode("conformance-seq-groups", in)
		runtime.ReadMemStats(&after)
		debug.SetGCPercent(old)
		if err != nil {
			t.Fatal(err)
		}
		if got := len(ent.Lists["probe.items"]); got != n {
			t.Fatalf("decoded %d item(s), want %d", got, n)
		}
		runtime.GC()
		runtime.ReadMemStats(&kept)
		line := fmt.Sprintf("heap per list item: %d items, input %d bytes: %.0f bytes/item allocated by the decode, %.0f bytes/item held by the entity",
			n, len(in), float64(after.TotalAlloc-before.TotalAlloc)/float64(n), (float64(kept.HeapAlloc)-float64(before.HeapAlloc))/float64(n))
		fmt.Println(line)
		t.Log(line)
		runtime.KeepAlive(ent)
	}
}
