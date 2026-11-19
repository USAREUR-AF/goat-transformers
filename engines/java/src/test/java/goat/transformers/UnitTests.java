package goat.transformers;

import static goat.transformers.TestRunner.check;
import static goat.transformers.TestRunner.eq;
import static goat.transformers.TestRunner.throwsCode;

/** Engine checks beyond the shared vectors: number and time formatting, pack errors, tolerance, residue, typemap, bits, model modules. */
final class UnitTests {
    private UnitTests() {}

    static void run(Engine packs) {
        numbers();
        times();
        packErrors();
        xmlTolerance(packs);
        residue(packs);
        typemap();
        wireErrors(packs);
        bits(packs);
        model(packs);
        kinds(packs);
        rules(packs);
        groups(packs);
        rulingsOfGroups();
        sequential(packs);
        rulingsOfSequential();
        modelAdditions();
        malformedInput(packs);
        sentinels();
        strictRulings(packs);
        tlv();
    }

    /** Version 0.11: the parts of the strict rulings no shared vector reaches through the runner. */
    static void strictRulings(Engine packs) {
        String bd = "bad-directive";
        String head = "format x\nversion 0.1.0\ndistribution public\nsource t\n";
        // ruling 6f: a format not loaded, from before to
        errorKind("capability of a format not loaded", "unknown-format", () -> packs.capability("no-such-format", "geojson"));
        errorKind("capability to a format not loaded", "unknown-format", () -> packs.capability("geojson", "no-such-format"));
        Engine.Capability self = packs.capability("geojson", "geojson");
        check("a format against itself", self.dropped.isEmpty() && self.grade.equals(self.carried.isEmpty() ? "none" : "full"), self.grade);
        // ruling 5: convert checks from, then to, before it reads the input
        try {
            packs.convert("no-such-from", "no-such-to", "not a message");
            check("convert checks from first", false, "no error");
        } catch (GtException ex) {
            check("convert checks from first", ex.kind().equals("unknown-format") && "no-such-from".equals(ex.format()), ex.getMessage());
        }
        // ruling 7b: the limit is an integer of 0 or more
        Engine limited = new Engine();
        try {
            limited.setMaxItems(-1);
            check("negative limit on list items", false, "accepted");
        } catch (IllegalArgumentException ex) {
            check("negative limit on list items", true, "");
        }
        eq("default limit on list items", 100_000L, limited.maxItems());
        // ruling 5e: one argument, a quoted value is one
        check("quoted source of two words loads", Pack.parse(head + "source \"a b\"\nwire xml\nroot r\n", "t") != null, "");
        errorKind("uses with two arguments", bd, () -> Pack.parse(head + "uses a b\nwire xml\nroot r\n", "t"));
        // ruling 4d: parameters
        String bits = head + "wire bits\nword_bytes 2\n";
        errorKind("sscale fraction with a sign", bd, () -> Pack.parse(bits + "field x 0:0:8 sscale:-1/2\n", "t"));
        errorKind("uint with a parameter", bd, () -> Pack.parse(bits + "field x 0:0:8 uint:3\n", "t"));
        errorKind("linscale range infinite", bd, () -> Pack.parse(bits + "field x 0:0:8 linscale:10:1e400\n", "t"));
        check("linscale maxpos with leading zeros loads", Pack.parse(bits + "field x 0:0:8 linscale:0010:90\n", "t") != null, "");
        // ruling 2c: unsigned decimal integers in a pack
        errorKind("item with a sign", bd, () -> Pack.parse(bits + "group probe.recs 0:8 item +8 count 1\n field probe.x 0:0:8 uint\nend\n", "t"));
        errorKind("bits locator with a sign", "bad-locator", () -> Pack.parse(bits + "field x 0:+0:8 uint\n", "t"));
        // ruling 3: iso8601_ms
        eq("iso8601_ms fraction truncated", -1L, Transform.parseIso("1969-12-31T23:59:59.9999Z"));
        eq("iso8601_ms leap day", 951782400000L, Transform.parseIso("2000-02-29T00:00:00Z"));
        check("iso8601_ms 1900-02-29 refused", refuses(() -> Transform.parseIso("1900-02-29T00:00:00Z")), "");
        eq("iso8601_ms -00:00 is UTC", 0L, Transform.parseIso("1970-01-01T00:00:00-00:00"));
        eq("iso8601_ms first instant", Transform.ISO_MIN, Transform.parseIso("0001-01-01T00:00:00.000Z"));
        eq("iso8601_ms last instant", Transform.ISO_MAX, Transform.parseIso("9999-12-31T23:59:59.999Z"));
        eq("iso8601_ms writes the first instant", "0001-01-01T00:00:00.000Z", Transform.formatIso(Transform.ISO_MIN));
        // ruling 2b: negative zero and the edge of the doubles
        check("-1e-400 is negative zero", Double.doubleToRawLongBits(Transform.parseFloat("-1e-400")) == Long.MIN_VALUE, "");
        check("1.7976931348623159e308 refused", refuses(() -> Transform.parseFloat("1.7976931348623159e308")), "");
        eq("2f smallest subnormal", "0." + "0".repeat(323) + "5", Transform.formatDouble(Double.MIN_VALUE));
        eq("2f 1e21", "1" + "0".repeat(21), Transform.formatDouble(1e21));
        eq("2f negative zero", "0", Transform.formatDouble(-0.0));
    }

    /** Version 0.9: the rulings on absent-value sentinels that no shared vector pins (17 to 22) and a few beside them. */
    static void sentinels() {
        String bd = "bad-directive";
        String json = "format j\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire json\n";
        String seq = "format s\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";
        // 17: =true and =false are strings, so not a bool sentinel; =null is the string null
        errorKind("absent =true on bool", bd, () -> Pack.parse(json + "field probe.x on bool absent =true\n", "t"));
        check("absent =null loads", Pack.parse(json + "field probe.label l string absent =null\n", "t") != null, "");
        // 18: number text that does not fit a finite double
        errorKind("absent 1e400 on json", bd, () -> Pack.parse(json + "field probe.f f float absent 1e400\n", "t"));
        // 11: a value cannot hold a double quote
        errorKind("absent value with a double quote", bd, () -> Pack.parse(json + "field probe.label l string absent a\"b\n", "t"));
        // 19: a wire integer is compared through a double
        Engine e = probeEngine(json + "field probe.x x int absent 9007199254740993\nfield probe.y y int\n");
        Entity big = e.decode("j", "{\"x\":9007199254740992,\"y\":1}");
        check("json integer compared through a double", big.get("probe.x") == null, "got " + big.get("probe.x"));
        // 20 and 16: two lines on one locator; the present key wins over the sentinel of the earlier line
        Engine t = probeEngine(json + "field probe.label s string absent -\nfield probe.s s string\n");
        Entity en = new Entity();
        en.put("probe.s", "Z");
        eq("present key of a later line wins", "{\"s\":\"Z\"}", t.encode("j", en));
        eq("absent keys write the first line's sentinel", "{\"s\":\"-\"}", t.encode("j", new Entity()));
        // 22: a wire sentinel decodes as absent, so a round trip writes the default
        Engine d = probeEngine(json + "field probe.x x int absent 0\ndefault probe.x 3\n");
        eq("sentinel then default", "{\"x\":3}", d.convert("j", "j", "{\"x\":0}", null));
        // sequential: also binds another key to the same bits, and the field line's sentinel holds for it
        Engine s = probeEngine(seq + "field probe.x 8 uint absent 255\nalso probe.y\n");
        Entity sd = s.decode("s", "ff");
        check("also: the field line's sentinel", sd.get("probe.x") == null && sd.get("probe.y") == null, "");
        eq("also: no key writes the sentinel", "ff", s.encode("s", new Entity()));
        errorKind("absent on a sequential field over 64 bits", bd, () -> Pack.parse(seq + "field probe.label 72 ascii absent 0\n", "t"));
    }

    /** Version 0.13, the tlv wire: the cases no shared vector pins. */
    static void tlv() {
        String head = "format t\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire tlv\n";
        String fixed = head + "tag 1\nlength 1\nfield probe.x 1:1 uint\nfield probe.label 2 utf8\n";
        Engine e = probeEngine(fixed);
        // residue: every occurrence, written back in input order across tags
        Entity d = e.decode("t", "0501aa0601bb0501cc");
        eq("tlv residue keeps every occurrence", "[5, 6, 5#2]", d.residue("t").keySet().toString());
        eq("tlv residue written in input order", "0501aa0601bb0501cc", e.convert("t", "t", "0501aa0601bb0501cc"));
        // a length that does not fit a fixed size is transform-encode
        Entity big = new Entity();
        big.put("probe.label", "x".repeat(256));
        errorKind("tlv length beyond length 1", "transform-encode", () -> e.encode("t", big));
        Entity edge = new Entity();
        edge.put("probe.label", "x".repeat(255));
        check("tlv length 255 under length 1", e.encode("t", edge).startsWith("02ff"), "");
        // BER-OID tags and BER lengths on encode
        Engine ber = probeEngine(head + "field probe.x 268435455:1 uint\nfield probe.y 128:1 uint\nfield probe.label 48.2 utf8\n");
        Entity v = new Entity();
        v.put("probe.x", 1L);
        v.put("probe.y", 2L);
        v.put("probe.label", "y".repeat(200));
        String out = ber.encode("t", v);
        check("tlv BER-OID tag of four bytes", out.startsWith("ffffff7f0101" + "8100" + "0102" + "3081cb" + "0281c8"), out.substring(0, 30));
        // a nested length of 2^64-1 is compared with the bytes left, not added to an offset
        errorKind("tlv nested length 2^64-1", "malformed-wire", () -> ber.decode("t", "300a0288ffffffffffffffff"));
        errorKind("tlv nested length 2^63", "malformed-wire", () -> ber.decode("t", "300a02888000000000000000"));
        errorKind("tlv length 2^31 in the top set", "malformed-wire", () -> ber.decode("t", "02848000000000"));
        // an item of the same tag on a path not walked into is one residue item, even when it is not a set
        eq("tlv unwalked nested value", "31020501", ber.convert("t", "t", "31020501"));
        // ruling 5 reads a when … present as a line at its path
        throwsCode("tlv when present over a set", GtException.Code.BAD_DIRECTIVE, () -> probeEngine(
                head + "field probe.x 48.2:1 uint\nkind a\nwhen 48 present\n"));
        throwsCode("tlv absent option (ruling 10 of 0.13)", GtException.Code.BAD_DIRECTIVE, () -> probeEngine(head + "field probe.x 2:1 uint absent 255\n"));
        throwsCode("tlv unknown transform", GtException.Code.BAD_DIRECTIVE, () -> probeEngine(head + "field probe.x 4:1 foo\n"));
        throwsCode("tlv utf8 on json", GtException.Code.BAD_DIRECTIVE, () -> probeEngine(
                "format t\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire json\nfield probe.label a utf8\n"));
        // random hex fed to a tlv pack gives only the engine's errors
        java.util.SplittableRandom rnd = new java.util.SplittableRandom(0x0013L);
        int defects = 0;
        for (int i = 0; i < 4000; i++) {
            byte[] b = new byte[rnd.nextInt(24)];
            for (int k = 0; k < b.length; k++) b[k] = (byte) (rnd.nextInt(4) == 0 ? 0x80 + rnd.nextInt(10) : rnd.nextInt(256));
            String h = Codec.toHex(b);
            for (Engine en : new Engine[]{e, ber}) {
                try {
                    en.convert("t", "t", h);
                } catch (GtException ex) {
                    // an engine error
                } catch (RuntimeException ex) {
                    defects++;
                }
            }
        }
        eq("tlv random input: engine errors only", 0, defects);
    }

    /** Version 0.8, rulings 35 to 39: the cases of malformed input no shared vector pins. */
    static void malformedInput(Engine packs) {
        String mw = "malformed-wire";
        String j = "conformance-malformed-json", x = "conformance-malformed-xml", p = "conformance-malformed-protobuf",
                b = "conformance-malformed-bits";
        // ruling 35: the limit holds for arrays and for a mix of arrays and objects, and far beyond it
        errorKind("json 65 arrays", mw, () -> packs.decode(j, "{\"a\":" + "[".repeat(64) + "]".repeat(64) + "}"));
        check("json 64 levels of arrays and objects", packs.decode(j, "{\"id\":\"u\",\"a\":" + "[".repeat(63) + "]".repeat(63) + "}") != null, "");
        errorKind("json nesting of 200000 levels", mw, () -> packs.decode(j, "[".repeat(200000)));
        errorKind("json nesting of 200000 objects", mw, () -> packs.decode(j, "{\"a\":".repeat(200000)));
        errorKind("xml nesting of 200000 levels", mw, () -> packs.decode(x, "<event>" + "<a>".repeat(200000)));
        // siblings do not add levels
        check("xml siblings at level 2", packs.decode(x, "<event uid=\"u\">" + "<a/>".repeat(1000) + "</event>") != null, "");
        // ruling 36
        for (String hex : new String[]{"+a", "-1", "0x01", "0a0275311005 +", "0a02753110\u00a005", "0a02753110\u200505", "\u0661\u0662"}) {
            errorKind("protobuf hex \"" + hex + "\"", mw, () -> packs.decode(p, hex));
            errorKind("bits hex \"" + hex + "\"", mw, () -> packs.decode(b, hex));
        }
        // ruling 40: whitespace in hex text is space, tab, line feed and carriage return only
        for (String hex : new String[]{"0a02\f75311005", "0a02\01375311005", "0a02\03475311005", "0a02\u008575311005", "0a02\u202875311005", "0a02\u300075311005"}) {
            errorKind("protobuf hex with another space", mw, () -> packs.decode(p, hex));
            errorKind("bits hex with another space", mw, () -> packs.decode(b, hex));
        }
        eq("hex whitespace", "u1", packs.decode(p, " 0a\t02 75\r\n31 10 05\n").get("uid"));
        // ruling 37
        errorKind("xml of whitespace and a comment", mw, () -> packs.decode(x, " <!-- c --> "));
        errorKind("xml of a declaration alone", mw, () -> packs.decode(x, "<?xml version=\"1.0\"?>"));
        errorKind("xml root of another name", "missing-root", () -> packs.decode(x, "<other/>"));
        errorKind("xml character reference with a sign", mw, () -> packs.decode(x, "<event uid=\"&#x+41;\"/>"));
        errorKind("xml character reference beyond the code points", mw, () -> packs.decode(x, "<event uid=\"&#x110000;\"/>"));
        errorKind("xml character reference with no digits", mw, () -> packs.decode(x, "<event uid=\"&#;\"/>"));
        // ruling 40: a numeric character reference names a character XML 1.0 allows
        for (String ref : new String[]{"&#0;", "&#x0;", "&#8;", "&#xB;", "&#x1F;", "&#xD800;", "&#xDFFF;", "&#xFFFE;", "&#xFFFF;", "&#-65;", "&#+65;",
                "&#x;", "&#X41;", "&#65", "&#6 5;", "&#\u0666\u0665;", "&#99999999999999999999;", "&nbsp;"}) {
            errorKind("xml reference " + ref, mw, () -> packs.decode(x, "<event uid=\"" + ref + "\"/>"));
            errorKind("xml reference " + ref + " in text", mw, () -> packs.decode(x, "<event>" + ref + "</event>"));
        }
        eq("xml references that are allowed", "\t\n\r A\ud7ff\ue000\ufffd\ud800\udc00\udbff\udfff&<>\"'",
                packs.decode(x, "<event uid=\"&#9;&#xA;&#13;&#x20;&#65;&#xD7FF;&#xE000;&#xFFFD;&#x10000;&#x10FFFF;&amp;&lt;&gt;&quot;&apos;\"/>").get("uid"));
        // ruling 40: a document type declaration anywhere
        for (String doc : new String[]{"<!DOCTYPE event><event/>", "<!DOCTYPE event [<!ENTITY a \"b\">]><event uid=\"&a;\"/>",
                "<?xml version=\"1.0\"?>\n<!DOCTYPE event SYSTEM \"http://127.0.0.1/x.dtd\"><event/>", "<event/><!DOCTYPE event>",
                "<event><!DOCTYPE event></event>", "<event><!DOCTYPE event/></event>", "<!doctype event><event/>", "<!ENTITY a \"b\"><event/>",
                "<event><!ELEMENT a ANY></event>", "<!DOCTYPE", "<event><?pi?><!DOCTYPE x></event>"}) {
            errorKind("xml " + doc, mw, () -> packs.decode(x, doc));
        }
        check("xml DOCTYPE as text of a comment and of CDATA", packs.decode(x, "<!-- <!DOCTYPE a> --><event uid=\"u\"><![CDATA[<!DOCTYPE a>]]></event>") != null, "");
        // ruling 38
        String[][] pb = {
            {"wire type 3", "0b"}, {"wire type 4", "0c"}, {"wire type 6", "0e"}, {"wire type 7", "0f"},
            {"field number 2^29", "8080808010" + "00"},
            {"field number of 61 bits", "f8ffffffffffffffff01" + "00"},
            {"length of 2^63-1", "0a" + "ffffffffffffffff7f"},
            {"length of 2^31", "0a" + "8080808008"},
            {"length one beyond the input", "0a0375"},
            {"varint of ten bytes cut", "10" + "ffffffffffffffffff"},
            {"varint of eleven bytes", "10" + "ffffffffffffffffffff01"},
            {"tag of eleven bytes", "80808080808080808080" + "00"},
            {"wire type 3 in a field no line maps", "0a027531" + "4b"},
            {"wire type 6 in a field no line maps", "0a027531" + "4e00"}, {"wire type 7 in a field no line maps", "0a027531" + "4f00"},
            {"field number 0", "0000"}, {"field number 0 of wire type 2", "0200"}, {"field number 0 in a submessage", "0a027531" + "2202" + "0000"},
            {"ten-byte varint with last byte 2", "10" + "ffffffffffffffffff02"},
            {"ten-byte varint with last byte 0x7f", "10" + "8080808080808080807f"},
            {"ten-byte tag with last byte 2", "80808080808080808002" + "00"},
            {"ten-byte length with last byte 3", "0a" + "80808080808080808003"},
            {"ten-byte varint with last byte 2 in a field no line maps", "48" + "ffffffffffffffffff02"},
            {"submessage with a length beyond it", "0a027531" + "2202" + "0a05"}, {"submessage with a cut varint", "0a027531" + "2202" + "1080"},
            {"submessage with wire type 4", "0a027531" + "2201" + "0c"},
            {"fixed64 in a submessage cut by its end", "22050900000000"},
            {"path prefix that is not a submessage", "0a027531" + "2005"},
        };
        for (String[] c : pb) errorKind("protobuf " + c[0], mw, () -> packs.decode(p, c[1]));
        eq("protobuf ten-byte varint with last byte 1", -1L, packs.decode(p, "10" + "ffffffffffffffffff01").get("time_ms"));
        eq("protobuf ten-byte varint of zero with last byte 0", 0L, packs.decode(p, "10" + "80808080808080808000").get("time_ms"));
        // ruling 40: a truncated varint inside a packed field, and a ten-byte one beyond 64 bits
        Engine packed = probeEngine("format k\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire protobuf\n"
                + "group probe.recs 3\n field probe.x . pvarint\nend\n");
        eq("protobuf packed varints", 3, packed.decode("k", "1a04" + "01" + "8101" + "02").list("probe.recs").size());
        errorKind("protobuf packed field with a cut varint", mw, () -> packed.decode("k", "1a03" + "01" + "8181"));
        errorKind("protobuf packed field of one continuation byte", mw, () -> packed.decode("k", "1a01" + "80"));
        errorKind("protobuf packed ten-byte varint with last byte 2", mw, () -> packed.decode("k", "1a0a" + "ffffffffffffffffff02"));
        eq("protobuf field number 2^29-1 in a field no line maps", "u1", packs.decode(p, "0a027531" + "f8ffffff0f" + "00").get("uid"));
        // a submessage is checked also when an earlier line gave the key its value
        Engine two = probeEngine("format w\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire protobuf\n"
                + "field probe.label 1 pstring\nfield probe.label 4.1 pstring\n");
        errorKind("protobuf submessage of a later line of a key", mw, () -> two.decode("w", "0a0141" + "2202" + "0a05"));
        // ruling 39
        for (String v : new String[]{"01", "-01", "+1", ".5", "-.5", "1.", "1.e2", "1e", "1e+", "-", "0x10", "1_0", "Infinity", "NaN",
                "\"\\x\"", "\"\\'\"", "\"\\U0041\"", "\"\\u+041\"", "\"\\u-041\"", "\"\\u00g1\"", "\"\\u\u0661\u0661\u0661\u0661\"",
                "\"a\tb\"", "\"a\nb\"", "\"a\u0000b\"", "\"a\u001fb\"", "'a'", "tru", "True", "nul"}) {
            errorKind("json value " + v, mw, () -> packs.decode(j, "{\"id\":\"u\",\"n\":" + v + "}"));
            errorKind("geojson value " + v, mw, () -> packs.decode("conformance-malformed-geojson",
                    "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"n\":" + v + "}}"));
        }
        for (String v : new String[]{"0", "-0", "0.5", "-0.5e-3", "1E+2", "10", "\"\\u00e9\\ud83d\\ude00\\/\\b\\f\\n\\r\\t\\\\\\\"\"", "\"\u007f\""}) {
            check("json value " + v + " is read", packs.decode(j, "{\"id\":\"u\",\"n\":" + v + "}") != null, "");
        }
        // ruling 40: half of a surrogate pair without its other half
        for (String v : new String[]{"\"\\ud83d\"", "\"\\ude00\"", "\"\\ude00\\ud83d\"", "\"\\ud83dx\"", "\"\\ud83d\\n\"", "\"\\ud83d\\u0041\"",
                "\"\\ud83d\\ud83d\\ude00\"", "\"\\ud83d\\ude00\\ude00\"", "\"\\uD800\"", "\"\\uDFFF\"", "\"\\ud83d\\u\"", "\"\\ud83d\\ude0\"", "\"\\ud83d \\ude00\""}) {
            errorKind("json value " + v, mw, () -> packs.decode(j, "{\"id\":\"u\",\"n\":" + v + "}"));
            errorKind("json member name " + v, mw, () -> packs.decode(j, "{\"id\":\"u\"," + v + ":1}"));
            errorKind("geojson value " + v, mw, () -> packs.decode("conformance-malformed-geojson",
                    "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"n\":" + v + "}}"));
        }
        eq("json surrogate pair of escapes", "\ud83d\ude00\ud800\udc00\udbff\udfff\ud7ff\ue000",
                packs.decode(j, "{\"id\":\"\\ud83d\\uDE00\\uD800\\udc00\\udbff\\udfff\\ud7ff\\ue000\"}").get("uid"));
        for (String doc : new String[]{"{\"id\":\"u\",}", "{,}", "[1,]", "{\"id\" \"u\"}", "{id:1}", "{\"id\":\"u\"}//", "\u00a0{}", "{}\u00a0", "{}\f"}) {
            errorKind("json document " + doc, mw, () -> packs.decode(j, doc));
        }
    }

    /**
     * Version 0.8, "Malformed input": the input of every conversion vector, cut at prefixes and with single bytes
     * changed, is decoded and converted by its own formats, and one changed copy is decoded by every loaded pack.
     * Whatever is thrown is the engine's error with a named kind before a colon. The seed is fixed.
     */
    @SuppressWarnings("unchecked")
    static void malformedSweep(Engine engine, java.util.List<java.nio.file.Path> vectorFiles) {
        java.util.SplittableRandom rnd = new java.util.SplittableRandom(0x60a7_0008L);
        java.util.Set<String> kinds = new java.util.HashSet<>();
        for (GtException.Code c : GtException.Code.values()) kinds.add(c.kind());
        java.util.List<String> formats = new java.util.ArrayList<>();
        for (Pack p : engine.packs()) formats.add(p.format);
        long[] n = new long[2];            // inputs fed, errors seen
        java.util.List<String> bad = new java.util.ArrayList<>();
        java.util.function.BiConsumer<String, Runnable> feed = (what, r) -> {
            n[0]++;
            try {
                r.run();
            } catch (GtException ex) {
                n[1]++;
                String m = ex.getMessage();
                int colon = m.indexOf(':');
                if (colon < 1 || !kinds.contains(m.substring(0, colon)) || !m.startsWith(ex.kind() + ": ")) {
                    if (bad.size() < 8) bad.add(what + ": no named kind in \"" + m + "\"");
                }
            } catch (Throwable t) {
                if (bad.size() < 8) bad.add(what + ": " + t);
            }
        };
        for (java.nio.file.Path f : vectorFiles) {
            Object doc;
            try {
                doc = Json.parse(java.nio.file.Files.readString(f, java.nio.charset.StandardCharsets.UTF_8));
            } catch (java.io.IOException | RuntimeException ex) {
                continue;                  // reported by the vector run
            }
            if (!(doc instanceof java.util.Map)) continue;
            java.util.Map<String, Object> v = (java.util.Map<String, Object>) doc;
            if (!(v.get("from") instanceof String) || !(v.get("to") instanceof String) || !(v.get("input") instanceof String)) continue;
            String from = (String) v.get("from"), to = (String) v.get("to");
            byte[] in = ((String) v.get("input")).getBytes(java.nio.charset.StandardCharsets.UTF_8);
            boolean hex = true;
            for (byte c : in) hex &= Json.hexDigit((char) c) >= 0 || c == ' ' || c == '\n';
            java.util.List<byte[]> cases = new java.util.ArrayList<>();
            // prefixes: every one of a short input, 24 spread over a long one
            int step = Math.max(1, in.length / 24);
            for (int len = 0; len < in.length; len += step) cases.add(java.util.Arrays.copyOf(in, len));
            if (in.length > 0) cases.add(java.util.Arrays.copyOf(in, in.length - 1));
            // single bytes changed: to any byte, to a byte of the input's own alphabet, and one bit flipped
            for (int k = 0; k < 24 && in.length > 0; k++) {
                byte[] m = in.clone();
                int at = rnd.nextInt(m.length);
                switch (k % 3) {
                    case 0: m[at] = (byte) rnd.nextInt(256); break;
                    case 1: m[at] = hex ? (byte) "0123456789abcdef".charAt(rnd.nextInt(16)) : in[rnd.nextInt(in.length)]; break;
                    default: m[at] ^= (byte) (1 << rnd.nextInt(7));
                }
                cases.add(m);
            }
            String label = f.getParent().getParent().getFileName() + "/" + f.getFileName();
            for (byte[] c : cases) {
                String text = new String(c, java.nio.charset.StandardCharsets.UTF_8);
                String what = label + " " + from + " <- \"" + (text.length() > 120 ? text.substring(0, 120) + "..." : text) + "\"";
                feed.accept("decode " + what, () -> engine.decode(from, c));
                feed.accept("convert " + what, () -> engine.convert(from, to, text));
            }
            if (!cases.isEmpty()) {
                byte[] c = cases.get(cases.size() - 1);
                for (String fmt : formats) {
                    if (!fmt.equals(from)) feed.accept("decode " + label + " by " + fmt, () -> engine.decode(fmt, c));
                }
            }
        }
        check("malformed input sweep fed inputs", n[0] > 0 && n[1] > 0, n[0] + " inputs, " + n[1] + " errors");
        check("malformed input sweep: only the engine's error, with a named kind", bad.isEmpty(), String.join("\n  ", bad));
        System.out.println("malformed input sweep: " + n[0] + " inputs over " + vectorFiles.size() + " vectors and "
                + formats.size() + " packs, " + n[1] + " named errors, " + bad.size() + " defects");
    }

    private static final String PROBE = "module probe\nversion 0.1.0\ndistribution public\nsource t\n"
            + "key label string -\nkey x int -\nkey y int -\nkey z int -\nkey s string -\nkey f float -\nlist recs\nlist subs\n";

    private static Engine probeEngine(String... packs) {
        Engine e = new Engine();
        e.loadModel(CORE);
        e.loadModel(PROBE);
        for (String p : packs) e.loadPack(p, "t");
        return e;
    }

    /** Rulings 16 to 34 of Version 0.8. */
    static void rulingsOfSequential() {
        String head = "format s\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";
        // 16: the earliest key the entity holds; when it holds none, the default of the earliest key that has one.
        Engine e = probeEngine(head + "field probe.x 8 uint\nalso probe.y\nalso probe.z\ndefault probe.x 1\ndefault probe.y 2\n");
        Entity en = new Entity();
        eq("also: default of the earliest key that has one", "01", e.encode("s", en));
        en.put("probe.z", 7L);
        eq("also: a held key is written, not an earlier default", "07", e.encode("s", en));
        en.put("probe.y", 6L);
        eq("also: the earliest held key", "06", e.encode("s", en));
        // 18: a when may follow the requires and default lines of its kind, and no other line.
        check("when after requires and default", Pack.parse(head + "kind a\nrequires probe.x\ndefault probe.y 1\nwhen 8 1\n", "t") != null, "");
        errorKind("when after a default and a field", "bad-directive",
                () -> Pack.parse(head + "kind a\ndefault probe.x 1\nfield probe.x 8 uint\nwhen 8 1\n", "t"));
        // 23: one list in two groups of a scope only when they sit in different if or opt blocks.
        String g = "group probe.recs count 8\nend\n";
        check("list in an if and an opt block", Pack.parse(head + "presence p 1\nif p.1\n" + g + "end\nopt\n" + g + "end\n", "t") != null, "");
        check("list in two kinds", Pack.parse(head + "kind a\nwhen 8 1\n" + g + "kind b\n" + g, "t") != null, "");
        check("list in two blocks under a length", Pack.parse(head + "opt\nlength 8\n" + g + "end\nend\nopt\n" + g + "end\n", "t") != null, "");
        errorKind("list in two groups of one opt", "bad-directive", () -> Pack.parse(head + "opt\n" + g + g + "end\n", "t"));
        errorKind("list in an opt and in a block of that opt", "bad-directive",
                () -> Pack.parse(head + "opt\n" + g + "opt\n" + g + "end\nend\n", "t"));
        errorKind("list in two length blocks", "bad-directive",
                () -> Pack.parse(head + "length 8\n" + g + "end\nlength 8\n" + g + "end\n", "t"));
        errorKind("list in two parts of a chain", "bad-directive", () -> Pack.parse(head + "chain\n" + g + "fx\n" + g + "end\n", "t"));
        errorKind("list in the common lines and in a kind", "bad-directive",
                () -> Pack.parse(head + "opt\n" + g + "end\nkind a\n" + g, "t"));
        // 24: a header or table directive inside a block.
        errorKind("map inside an opt", "bad-directive", () -> Pack.parse(head + "opt\nmap t 1 2\nend\n", "t"));
        errorKind("uses inside a chain", "bad-directive", () -> Pack.parse(head + "chain\nuses probe\nend\n", "t"));
        // 20, 21: skips and indicator bits at the end of the input and of a length extent.
        Engine x = probeEngine(head + "field probe.x 4 uint\nalign 16\n",
                head.replace("format s", "format w") + "length 8 bits\n group probe.recs while\n  field probe.y 7 uint\n end\nend\n",
                head.replace("format s", "format m") + "length 8 bits\n field probe.x 8 uint\n group probe.recs more\n  field probe.y 7 uint\n end\nend\n",
                head.replace("format s", "format n") + "field probe.x 8 uint\ngroup probe.recs while\n field probe.y 7 uint\nend\n",
                head.replace("format s", "format c") + "field probe.x 8 uint\nconst 8 1\n",
                head.replace("format s", "format k") + "group probe.recs count 8\n kind a\n when 8 1\n requires probe.x\n field probe.x 8 uint\n kind b\n when 8 0\nend\n",
                head.replace("format s", "format j") + "group probe.recs count 8\n kind c\n when 8 2\n requires probe.x\n field probe.x 8 uint\n kind d\n when 8 3\nend\n");
        eq("align stops at the end of the input", 5L, x.decode("s", "50").get("probe.x"));
        eq("while indicator at the end of the extent reads 0", 1, x.decode("w", "0889").list("probe.recs").size());
        check("a group that starts at the end of the extent is an absent list", x.decode("w", "00").list("probe.recs") == null, "");
        eq("more indicator at the end of the extent reads 0", 2, x.decode("m", "100589").list("probe.recs").size());
        errorKind("while indicator past the end of the input", "malformed-wire", () -> x.decode("n", "0589"));
        errorKind("const past the end of the input", "malformed-wire", () -> x.decode("c", "05"));
        // 26: an item whose kind the group does not have selects by requires.
        eq("item kind of another group selects by requires", "020205" + "03", x.convert("k", "j", "020105" + "00"));
        Entity item = new Entity();
        item.setKind("k", "nope");
        Entity holder = new Entity();
        holder.putList("probe.recs", java.util.List.of(item));
        eq("item naming a kind the group does not have", "0100", x.encode("k", holder));
        // 29: the order of the checks of a module.
        String other = "module other\nversion 0.1.0\nuses nosuch\nkey o int -\nderive other.o copy other.nokey\n";
        Engine pub = new Engine();
        pub.setMaxDistribution(Distribution.PUBLIC);
        errorKind("module: missing-distribution first", "missing-distribution", () -> pub.loadModel(other));
        errorKind("module: missing-source next", "missing-source", () -> pub.loadModel(other + "distribution controlled\n"));
        errorKind("module: distribution-refused next", "distribution-refused", () -> pub.loadModel(other + "distribution controlled\nsource t\n"));
        errorKind("module: unknown-module next", "unknown-module", () -> pub.loadModel(other + "distribution public\nsource t\n"));
        errorKind("module: the derive checks before duplicate-module", "bad-directive", () -> {
            Engine d = probeEngine();
            d.loadModel(PROBE.replace("list subs\n", "list subs\nderive probe.x copy probe.nokey\n"));
        });
        // 31: a protobuf when path whose prefix is not a submessage does not hold; it is not an error.
        Engine pb = probeEngine("format q\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire protobuf\n"
                + "kind a\nwhen 3.1 present\nfield probe.x 2 pvarint\n"
                + "kind c\nwhen 3.1 7\nfield probe.y 2 pvarint\n"
                + "kind b\nwhen 1 present\nfield probe.label 1 pstring\n");
        Entity q = pb.decode("q", "0a01411805");   // field 1 "A", field 3 the varint 5
        check("when path through a field that is not a submessage does not hold", "b".equals(q.kindName()) && "A".equals(q.get("probe.label")), q.toString());
        errorKind("when paths that do not hold are no-kind, not malformed-wire", "no-kind", () -> pb.decode("q", "1805"));
        eq("when path through a submessage holds", "a", pb.decode("q", "1a020807").kindName());
        // 32: a derive line refused on its own text is a line error, raised as the file is read.
        errorKind("derive line refused on its text, before missing-distribution", "bad-directive",
                () -> pub.loadModel("module other\nversion 0.1.0\nkey o int -\nderive other.o nosuch other.o\n"));
        // 0.11 ruling 5b: a derive line refused on its text is checked after the file, so a later line error wins
        errorKind("derive line refused on its text, after a later line error", "unknown-directive",
                () -> pub.loadModel("module other\nversion 0.1.0\nkey o int -\nderive other.o copy\nnosuchdirective\n"));
        errorKind("derive keys are checked after missing-distribution", "missing-distribution",
                () -> pub.loadModel("module other\nversion 0.1.0\nkey o int -\nderive other.o copy other.nokey\n"));
        // 33: two groups of one list, neither block enclosing the other; decode keeps the later group's items.
        check("list in sibling blocks of one outer block", Pack.parse(head + "opt\nopt\n" + g + "end\nopt\n" + g + "end\nend\n", "t") != null, "");
        errorKind("list in an if and in an if inside it", "bad-directive",
                () -> Pack.parse(head + "presence p 2\nif p.1\n" + g + "if p.2\n" + g + "end\nend\n", "t"));
        String body = " field probe.y 8 uint\nend\n";
        Engine two = probeEngine(head + "opt\ngroup probe.recs count 7\n" + body + "end\nopt\ngroup probe.recs count 7\n" + body + "end\n");
        // opt 1, count 1, item 5; opt 1, count 2, items 6 and 7
        eq("both groups on the wire: the later group's items", "[{probe.y=6}, {probe.y=7}]",
                two.decode("s", "81058206" + "07").list("probe.recs").stream().map(i -> i.fields().toString()).collect(java.util.stream.Collectors.toList()).toString());
        // 34: a group whose first indicator lies at the end of the extent is an absent list.
        Entity m = x.decode("m", "08aa");
        check("more group whose first indicator is at the end of the extent", m.list("probe.recs") == null && Long.valueOf(0xaa).equals(m.get("probe.x")), m.toString());
    }

    /** Loading only named packs of a directory, with the modules they need: the API and the command line. */
    static void packsOnly(java.nio.file.Path packsDir) {
        Engine e = Engine.loadOnly(packsDir, java.util.List.of("cot-xml", "geojson", "cot-xml"));
        java.util.List<String> formats = new java.util.ArrayList<>();
        for (Pack p : e.packs()) formats.add(p.format);
        eq("packs-only: the packs named", "[cot-xml, geojson]", formats.toString());
        java.util.List<String> modules = new java.util.ArrayList<>();
        for (ModelModule m : e.modules()) modules.add(m.name);
        eq("packs-only: only the modules they need", "[core, track]", modules.toString());
        Engine all = Engine.load(packsDir);
        for (Pack p : all.packs()) {
            Engine one = Engine.loadOnly(packsDir, java.util.List.of(p.format));
            java.util.Set<String> want = new java.util.TreeSet<>();
            want.add(ModelModule.CORE);
            java.util.ArrayDeque<String> todo = new java.util.ArrayDeque<>(p.uses);
            while (!todo.isEmpty()) {
                String u = todo.pop();
                if (!want.add(u)) continue;
                for (ModelModule m : all.modules()) if (m.name.equals(u)) todo.addAll(m.uses);
            }
            java.util.Set<String> got = new java.util.TreeSet<>();
            for (ModelModule m : one.modules()) got.add(m.name);
            check("packs-only " + p.format, one.packs().size() == 1 && got.equals(want), "modules " + got + ", want " + want);
        }
        errorKind("packs-only: a name that is no pack", "unknown-format", () -> Engine.loadOnly(packsDir, java.util.List.of("no-such-pack")));
        errorKind("packs-only: a name that is a path", "unknown-format", () -> Engine.loadOnly(packsDir, java.util.List.of("../packs/geojson")));
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(), err = new java.io.ByteArrayOutputStream();
        try {
            int code = Cli.run(new String[]{"list-formats", "--packs", packsDir.toString(), "--packs-only", "geojson,cot-xml"},
                    new java.io.PrintStream(out, true, "UTF-8"), new java.io.PrintStream(err, true, "UTF-8"));
            String[] lines = out.toString("UTF-8").trim().split("\\R");
            check("cli --packs-only", code == 0 && lines.length == 2 && lines[0].startsWith("cot-xml ") && lines[1].startsWith("geojson "),
                    "exit " + code + ": " + out.toString("UTF-8") + err.toString("UTF-8"));
            eq("cli --packs-only with an unknown name", 1, Cli.run(new String[]{"list-formats", "--packs", packsDir.toString(),
                    "--packs-only", "no-such-pack"}, new java.io.PrintStream(out, true, "UTF-8"), new java.io.PrintStream(err, true, "UTF-8")));
            eq("cli --packs-only with an empty name", 2, Cli.run(new String[]{"list-formats", "--packs", packsDir.toString(),
                    "--packs-only", "geojson,"}, new java.io.PrintStream(out, true, "UTF-8"), new java.io.PrintStream(err, true, "UTF-8")));
        } catch (java.io.IOException ex) {
            check("cli --packs-only", false, ex.toString());
        }
    }

    /** Rulings 11 to 21 of Version 0.7, which the vectors now pin. */
    static void rulingsOfGroups() {
        String json = "format j\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire json\n";
        String pb = "format p\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire protobuf\n";
        String bits = "format b\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire bits\nword_bytes 1\n";
        // 11: a scalar item with no value is null on json; a packed list of no values writes nothing on protobuf.
        Engine e = probeEngine(json + "group probe.recs recs\n field probe.x . int\nend\ngroup probe.subs subs\n field probe.x x int\nend\n",
                pb + "field probe.label 1 pstring\ngroup probe.recs 2.1\n field probe.x . pvarint\nend\nfield probe.s 3.1 pstring\n");
        eq("scalar item with no value is null", "{\"recs\":[1,null],\"subs\":[{}]}", e.convert("j", "j", "{\"recs\":[1,null],\"subs\":[{}]}"));
        eq("packed list of no values writes nothing", "", e.convert("j", "p", "{\"recs\":[null]}"));
        eq("packed list leaves out the item with no value", "12030a0105", e.convert("j", "p", "{\"recs\":[null,5]}"));
        // 13: a path prefix that is not a submessage is malformed-wire, for a field outside a group too.
        errorKind("path prefix that is not a submessage", "malformed-wire", () -> e.decode("p", "1805"));
        errorKind("protobuf body mixing . with a path", "bad-directive",
                () -> Pack.parse(pb + "group probe.recs 2\n field probe.x . pvarint\n field probe.y 1 pvarint\nend\n", "t"));
        // 15: a when value is written over a const on the same bits, whichever line comes first.
        Engine b = probeEngine(bits + "kind a\nwhen 0:0:8 1\nconst 0:0:8 2\n");
        eq("const then when", "01", b.encode("b", new Entity()));
        // 16: a fixed-count group whose items reach a later group counted by a locator.
        errorKind("fixed-count group reaching a counted group", "bad-directive", () -> Pack.parse(bits
                + "group probe.subs 0:8 item 8 count 2\n field probe.x 0:0:8 uint\nend\n"
                + "group probe.recs 0:16 item 8 count 0:0:8\n field probe.x 0:0:8 uint\nend\n", "t"));
        check("fixed-count group ending at a counted group loads", Pack.parse(bits
                + "group probe.subs 0:8 item 8 count 1\n field probe.x 0:0:8 uint\nend\n"
                + "group probe.recs 0:16 item 8 count 0:0:8\n field probe.x 0:0:8 uint\nend\n", "t") != null, "");
        // 21: a field through a group's path; the group's own locator and its container are not through it.
        String grp = "group probe.recs a.items\n field probe.x x int\nend\n";
        errorKind("field through a group path", "bad-directive", () -> Pack.parse(json + grp + "field probe.y a.items.n int\n", "t"));
        check("field beside a group path loads", Pack.parse(json + grp + "field probe.y a.n int\nconst a.items.k 1\n", "t") != null, "");
        String xml = "format x\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire xml\nroot r\n";
        errorKind("xml field on a group's element", "bad-directive",
                () -> Pack.parse(xml + "group probe.recs b/i\n field probe.x @x int\nend\nfield probe.y b/i/@n int\n", "t"));
        check("xml field on the container loads", Pack.parse(xml + "group probe.recs b/i\n field probe.x @x int\nend\nfield probe.y b/@n int\n", "t") != null, "");
    }

    /** Version 0.8: sequential binary layouts. */
    static void sequential(Engine packs) {
        String head = "format s\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire bits\nlayout sequential\nbit_order msb\n";
        // Load checks.
        errorKind("word_bytes in a sequential pack", "bad-directive", () -> Pack.parse(head + "word_bytes 1\n", "t"));
        errorKind("unknown layout", "bad-directive", () -> Pack.parse(head.replace("sequential", "serial"), "t"));
        errorKind("layout on another wire", "bad-directive", () -> Pack.parse(head.replace("wire bits", "wire json"), "t"));
        // 0.11 ruling 5b: layout sequential stands before the lines it decides
        errorKind("layout after the lines it decides", "bad-directive", () -> Pack.parse(head.replace("layout sequential\n", "") + "field probe.x 8 uint\nopt\nend\nlayout sequential\n", "t"));
        errorKind("bit length in a fixed pack", "bad-directive", () -> Pack.parse(head.replace("layout sequential", "word_bytes 1") + "field probe.x 8 uint\n", "t"));
        errorKind("pad in a fixed pack", "bad-directive", () -> Pack.parse(head.replace("layout sequential", "word_bytes 1") + "pad 8\n", "t"));
        errorKind("position in a sequential pack", "bad-directive", () -> Pack.parse(head + "field probe.x 0:0:8 uint\n", "t"));
        errorKind("optional in a sequential pack", "bad-directive", () -> Pack.parse(head + "field probe.x 8 uint optional\n", "t"));
        errorKind("block without end", "bad-directive", () -> Pack.parse(head + "chain\nfield probe.x 7 uint\nfx\n", "t"));
        errorKind("end without block", "bad-directive", () -> Pack.parse(head + "end\n", "t"));
        errorKind("fx outside a chain", "bad-directive", () -> Pack.parse(head + "opt\nfx\nend\n", "t"));
        errorKind("kind inside a block", "bad-directive", () -> Pack.parse(head + "opt\nkind a\nend\n", "t"));
        errorKind("map inside a block", "bad-directive", () -> Pack.parse(head + "opt\nmap t 1 2\nend\n", "t"));
        errorKind("presence bit 0", "bad-directive", () -> Pack.parse(head + "presence p 2\nif p.0\nend\n", "t"));
        errorKind("presence bit beyond its size", "bad-directive", () -> Pack.parse(head + "presence p 2\nif !p.3\nend\n", "t"));
        errorKind("presence of 65 bits", "bad-directive", () -> Pack.parse(head + "presence p 65\n", "t"));
        errorKind("presence declared twice", "bad-directive", () -> Pack.parse(head + "presence p 2\nkind a\npresence p 2\n", "t"));
        check("presence hidden in a nested block", Pack.parse(head + "presence p 2\nopt\npresence p 4\nif p.4\nend\nend\nif p.2\nend\n", "t").seqPresences == 2, "");
        errorKind("group with no repeat form", "bad-directive", () -> Pack.parse(head + "group probe.recs count\nend\n", "t"));
        errorKind("list mapped by two groups of one scope", "bad-directive",
                () -> Pack.parse(head + "group probe.recs fx\nend\nopt\ngroup probe.recs while\nend\nend\n", "t"));
        errorKind("when in a body with no kind", "bad-directive", () -> Pack.parse(head + "when 8 1\n", "t"));
        errorKind("when after another line of its kind", "bad-directive", () -> Pack.parse(head + "kind a\nfield probe.x 8 uint\nwhen 8 1\n", "t"));
        errorKind("when value that does not fit", "bad-directive", () -> Pack.parse(head + "kind a\nwhen 4 16\n", "t"));
        errorKind("kind twice in one body", "duplicate-kind", () -> Pack.parse(head + "group probe.recs fx\nkind a\nkind a\nend\n", "t"));
        errorKind("also after a pad", "bad-directive", () -> Pack.parse(head + "field probe.x 8 uint\npad 1\nalso probe.y\n", "t"));
        errorKind("also via an unknown table", "bad-directive", () -> Pack.parse(head + "field probe.x 8 uint\nalso probe.y via t\n", "t"));
        errorKind("length bits whole", "bad-directive", () -> Pack.parse(head + "length 8 bits whole\n", "t"));
        errorKind("length plus with no number", "bad-directive", () -> Pack.parse(head + "length 8 plus\nend\n", "t"));
        check("length options in any order", Pack.parse(head + "length 8 whole plus -1\nlength 8 plus 2 bytes\nend\n", "t") != null, "");
        errorKind("f32 of 16 bits", "bad-directive", () -> Pack.parse(head + "field probe.f 16 f32\n", "t"));
        Engine load = probeEngine();
        errorKind("also key of another type", "key-type-mismatch", () -> load.loadPack(head + "field probe.x 8 uint\nalso probe.label\n", "t"));
        errorKind("sequential group naming a key", "key-type-mismatch", () -> load.loadPack(head + "group probe.x fx\nend\n", "t"));
        errorKind("default for an undeclared key in a block", "undeclared-key", () -> load.loadPack(head + "opt\ndefault probe.nope 1\nend\n", "t"));
        Pack keys = Pack.parse(head + "field probe.x 8 uint\nalso probe.y\nopt\ngroup probe.recs fx\nkind a\nchain\nfield probe.z 7 uint\nfx\nend\nend\nend\n", "t");
        eq("model keys of a sequential pack", "[probe.x, probe.y, probe.recs[], probe.recs[].probe.z]", keys.modelKeys().toString());

        // A common when, kinds at the cursor, and a message-length field.
        Engine e = probeEngine(head.replace("format s", "format k") + "field probe.x 8 uint\nwhen 8 9\nlength 8 whole\n"
                + "kind a\nwhen 4 1\nrequires probe.y\nfield probe.y 4 uint\nkind b\nrequires probe.z\nfield probe.z 8 uint\n",
                head.replace("format s", "format l") + "length 8\n field probe.x 8 uint\n align 16\n opt\n  field probe.y 7 uint\n end\n"
                + " group probe.recs while\n  field probe.z 7 uint\n end\nend\nfield probe.z 8 uint\n",
                head.replace("format s", "format f") + "presence f fx\nif f.8\n field probe.x 8 uint\nend\ngroup probe.recs count 8\n if f.1\n  field probe.y 8 uint\n end\nend\n");
        Entity a = e.decode("k", "05090417");
        eq("sequential kind", "a", a.kindName());
        eq("field after the when lines", 7L, a.get("probe.y"));
        eq("kind kept and whole length written", "05090417", e.encode("k", a));
        Entity b = new Entity();
        b.put("probe.x", 5L);
        b.put("probe.z", 2L);
        eq("first kind whose requires holds", "05090402", e.encode("k", b));
        errorKind("no kind whose requires holds", "no-kind", () -> e.encode("k", new Entity()));
        errorKind("common when that does not hold", "no-kind", () -> e.decode("k", "05080417"));
        errorKind("common when beyond the input", "no-kind", () -> e.decode("k", "05"));
        Entity z = e.decode("k", "05090400ff");
        eq("kind with no when holds", "b", z.kindName());
        errorKind("stated length beyond the input", "malformed-wire", () -> e.decode("k", "05090517"));
        // Length extents: a line at the end of the extent is absent, align stops at it, a straddling line is malformed.
        Entity l = e.decode("l", "01aa07");
        eq("line inside the extent", 0xaaL, l.get("probe.x"));
        check("lines at the end of the extent are absent", l.get("probe.y") == null && l.list("probe.recs") == null, l.toString());
        eq("line after the extent", 7L, l.get("probe.z"));
        eq("encode writes every line of the extent", "02aa0007", e.encode("l", l));
        errorKind("item line that straddles the end of the extent", "malformed-wire", () -> e.decode("l", "03aa42c007"));
        eq("extent with items", "{probe.z=5}", e.decode("l", "03aa428007").list("probe.recs").get(0).fields().toString());
        errorKind("extent beyond the input", "malformed-wire", () -> e.decode("l", "09aa"));
        // An fx presence named inside the items of a group: any item with the content sets the bit.
        Entity f = e.decode("f", "8002030400");   // the last byte lies beyond the last line and is ignored
        eq("items read under a message presence", "[3, 4]", f.list("probe.recs").stream().map(i -> i.get("probe.y")).collect(java.util.stream.Collectors.toList()).toString());
        f.list("probe.recs").get(0).fields().clear();
        eq("one item sets the bit, every item writes the block", "80020004", e.encode("f", f));
        f.list("probe.recs").get(1).fields().clear();
        f.put("probe.x", 1L);
        eq("second presence octet, blocks of a 0 bit not written", "01800102", e.encode("f", f));
        errorKind("presence bit no if names", "malformed-wire", () -> e.decode("f", "4000"));
        errorKind("count larger than the bits left", "malformed-wire", () -> e.decode("f", "0011"));
    }

    /** Version 0.8: uses lines in model modules, load order of a directory, and the derive functions added. */
    static void modelAdditions() {
        String other = "module other\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nkey o int -\nkey t string -\nkey d float -\n";
        Engine e = probeEngine();
        ModelModule m = e.loadModel(other + "derive other.o any probe.x probe.y\nderive other.t text_of probe.z\n"
                + "derive other.d day_seconds time_ms\nkey p int -\nkey q int -\nderive other.p parse_int probe.s\nderive other.q not probe.x\n", "t");
        eq("module uses", "[probe]", m.uses.toString());
        Entity en = new Entity();
        en.put("probe.y", 0L);
        en.put("probe.z", -7L);
        en.put("time_ms", -1L);
        en.put("probe.s", "007");
        e.complete(en);
        eq("any of the present arguments", 0L, en.get("other.o"));
        eq("text_of", "-7", en.get("other.t"));
        eq("day_seconds before 1970", 86399.999, en.get("other.d"));
        eq("parse_int", 7L, en.get("other.p"));
        check("not needs its argument", en.get("other.q") == null, String.valueOf(en.get("other.q")));
        for (String text : new String[]{"+5", " 5", "5.0", "1e3", "", "99999999999999999999"}) {
            Entity t = new Entity();
            t.put("probe.s", text);
            t.put("probe.x", 3L);
            e.complete(t);
            check("parse_int of \"" + text + "\" is absent", t.get("other.p") == null, String.valueOf(t.get("other.p")));
            eq("any and not of a non-zero value", "1 0", t.get("other.o") + " " + t.get("other.q"));
        }
        errorKind("derive argument of a module not used", "bad-directive",
                () -> probeEngine().loadModel(other.replace("uses probe\n", "") + "derive other.o copy probe.x\n", "t"));
        errorKind("derive target of a used module", "bad-directive", () -> probeEngine().loadModel(other + "derive probe.x copy other.o\n", "t"));
        errorKind("uses a module not loaded", "unknown-module", () -> new Engine().loadModel(other, "t"));
        errorKind("any of no argument", "bad-directive", () -> probeEngine().loadModel(other + "derive other.o any\n", "t"));
        errorKind("parse_int to a string", "bad-directive", () -> probeEngine().loadModel(other + "derive other.t parse_int probe.s\n", "t"));
        Engine ctl = new Engine();
        ctl.loadModel(CORE);
        ctl.loadModel(PROBE.replace("distribution public", "distribution controlled"));
        errorKind("public module uses a controlled one", "distribution-violation", () -> ctl.loadModel(other, "t"));

        // The directory loader: core first, then byte order of file name, each module after the modules it uses.
        try {
            java.nio.file.Path dir = java.nio.file.Files.createTempDirectory("gt-models");
            try {
                java.nio.file.Files.writeString(dir.resolve("core.def"), CORE);
                java.nio.file.Files.writeString(dir.resolve("a.def"), other);
                java.nio.file.Files.writeString(dir.resolve("b.def"), PROBE);
                StringBuilder order = new StringBuilder();
                for (String[] f : Engine.modelsInLoadOrder(dir)) order.append(java.nio.file.Paths.get(f[0]).getFileName()).append(' ');
                eq("a module is loaded after the modules it uses", "core.def b.def a.def ", order.toString());
                java.nio.file.Files.writeString(dir.resolve("b.def"), PROBE + "uses other\n");
                errorKind("cycle of uses lines", "bad-directive", () -> Engine.modelsInLoadOrder(dir));
            } finally {
                try (java.util.stream.Stream<java.nio.file.Path> files = java.nio.file.Files.list(dir)) {
                    for (java.nio.file.Path f : (Iterable<java.nio.file.Path>) files::iterator) java.nio.file.Files.delete(f);
                }
                java.nio.file.Files.delete(dir);
            }
        } catch (java.io.IOException ex) {
            check("model directory", false, ex.toString());
        }
    }

    /** Version 0.7: lists in the model, group blocks on every wire, and the rulings of 0.6 the vectors now pin. */
    static void groups(Engine packs) {
        // The model: a list shares the key namespace of its module.
        String probe = "module probe\nversion 0.1.0\ndistribution public\nsource t\nkey label string -\nkey qty int -\nlist items \"a list\"\nlist subs\n";
        ModelModule m = ModelModule.parse(probe, "t");
        eq("module lists", "[items, subs]", m.lists.toString());
        check("a list is not a key", !m.keys.containsKey("items"), m.keys.toString());
        errorKind("list and key of one name", "duplicate-key", () -> ModelModule.parse(probe + "key items string -\n", "t"));
        errorKind("list declared twice", "duplicate-key", () -> ModelModule.parse(probe + "list subs\n", "t"));
        throwsCode("list name with a dot", GtException.Code.BAD_DIRECTIVE, () -> ModelModule.parse(probe + "list a.b\n", "t"));

        // Load checks on the block structure.
        String json = "format g\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire json\n";
        String grp = "group probe.items items\n  field probe.label name string\n";
        errorKind("group without end", "bad-directive", () -> Pack.parse(json + grp, "t"));
        errorKind("end without group", "bad-directive", () -> Pack.parse(json + "end\n", "t"));
        errorKind("when inside a group", "bad-directive", () -> Pack.parse(json + "kind a\n" + grp + "when name x\nend\n", "t"));
        errorKind("map inside a group", "bad-directive", () -> Pack.parse(json + grp + "map t 1 a\nend\n", "t"));
        errorKind("count off the bits wire", "bad-directive", () -> Pack.parse(json + "group probe.items items count 2\nend\n", "t"));
        errorKind("list mapped twice in a scope", "bad-directive", () -> Pack.parse(json + grp + "end\n" + "group probe.items more\nend\n", "t"));
        errorKind("the item itself outside a group", "bad-directive", () -> Pack.parse(json + "field probe.label . string\n", "t"));
        errorKind("const present", "bad-directive", () -> Pack.parse(json + "const marker present\n", "t"));
        errorKind("group error before missing-distribution", "bad-directive",
                () -> Pack.parse("format g\nversion 0.1.0\nsource t\nwire json\n" + grp, "t"));
        String bits = "format b\nversion 0.1.0\ndistribution public\nsource t\nuses probe\nwire bits\nword_bytes 1\n";
        errorKind("bits group without count", "bad-directive", () -> Pack.parse(bits + "group probe.items 0:8 item 8\nend\n", "t"));
        errorKind("bits group without item", "bad-directive", () -> Pack.parse(bits + "group probe.items 0:8 count 2\nend\n", "t"));
        errorKind("field at the start of a counted group", "bad-directive",
                () -> Pack.parse(bits + "group probe.items 0:8 item 8 count 0:0:8\nend\nfield probe.qty 0:4:8 uint\n", "t"));
        errorKind("count locator reaching its group", "bad-directive",
                () -> Pack.parse(bits + "group probe.items 0:8 item 8 count 0:4:8\nend\n", "t"));
        errorKind("item field beyond the item", "bad-directive",
                () -> Pack.parse(bits + "group probe.items 0:8 item 8 count 0:0:8\n field probe.qty 0:4:8 uint\nend\n", "t"));
        Pack nested = Pack.parse(json + "field uid id string\n" + grp + "  group probe.subs subs\n    field probe.qty . int\n  end\nend\n", "t");
        eq("model keys name lists and item keys", "[uid, probe.items[], probe.items[].probe.label, probe.items[].probe.subs[], probe.items[].probe.subs[].probe.qty]",
                nested.modelKeys().toString());
        eq("group body lines", 2, nested.kinds.get(0).scope.groups.get(0).body.lines.size());

        // Load checks against the model.
        Engine e = new Engine();
        e.loadModel(CORE);
        e.loadModel(probe);
        errorKind("group naming a scalar key", "key-type-mismatch", () -> e.add(Pack.parse(json + "group probe.label items\nend\n", "t")));
        errorKind("field naming a list", "key-type-mismatch", () -> e.add(Pack.parse(json + "field probe.items items string\n", "t")));
        errorKind("group naming an undeclared list", "undeclared-key", () -> e.add(Pack.parse(json + "group probe.nope items\nend\n", "t")));
        errorKind("context naming a list", "key-type-mismatch", () -> e.complete(new Entity(), java.util.Map.of("probe.items", "1")));

        // Entity.lists: present and empty is distinct from absent; items carry keys and lists, no residue.
        e.add(nested);
        Entity d = e.decode("g", "{\"id\":\"u\",\"items\":[{\"name\":\"a\",\"extra\":1,\"subs\":[1,2]},{}],\"z\":true}");
        eq("items decoded", 2, d.list("probe.items").size());
        eq("item key", "a", d.list("probe.items").get(0).get("probe.label"));
        eq("nested scalar items", 2L, d.list("probe.items").get(0).list("probe.subs").get(1).get("probe.qty"));
        check("nested list absent", d.list("probe.items").get(1).list("probe.subs") == null, d.toString());
        check("items carry no residue", d.list("probe.items").get(0).residue("g").isEmpty() && d.residue("g").containsKey("z"), d.toString());
        eq("lists re-encode in order", "{\"id\":\"u\",\"items\":[{\"name\":\"a\",\"subs\":[1,2]},{}],\"z\":true}", e.encode("g", d));
        Entity empty = e.decode("g", "{\"items\":[]}");
        check("present and empty", empty.list("probe.items") != null && empty.list("probe.items").isEmpty(), empty.toString());
        check("absent", e.decode("g", "{\"items\":null}").list("probe.items") == null, "null member");
        errorKind("list member that is not an array", "malformed-wire", () -> e.decode("g", "{\"items\":3}"));
        errorKind("the item itself is an object", "transform-decode", () -> e.decode("g", "{\"items\":[{\"subs\":[{}]}]}"));

        // bits: a group counted by a locator extends the message; a nested one may run past its item.
        e.add(Pack.parse(bits + "group probe.items 0:8 item 16 count 0:0:8\n  field probe.qty 0:0:8 uint\n"
                + "  group probe.subs 0:16 item 8 count 0:8:8\n    field probe.qty 0:0:8 uint\n  end\nend\n", "t"));
        Entity b = e.decode("b", "02 0702 0a0b 0900");
        eq("bits items", 2, b.list("probe.items").size());
        eq("bits nested item past the item bits", 11L, b.list("probe.items").get(0).list("probe.subs").get(1).get("probe.qty"));
        eq("bits next item starts where the nested group ends", 9L, b.list("probe.items").get(1).get("probe.qty"));
        eq("bits lists re-encode", "0207020a0b0900", e.encode("b", b));
        errorKind("bits input ends inside the items", "malformed-wire", () -> e.decode("b", "02 0702 0a0b 09"));
        eq("bits absent list writes count zero", "00", e.encode("b", new Entity()));
        eq("json list carried to bits, item by item", "010000", e.convert("g", "b", "{\"items\":[{\"name\":\"x\"}]}"));

        // The shipped packs: lists carried across wires, requires <list>.
        eq("xml items to protobuf", "0a0275311a050a03038e0222017022027171",
                packs.convert("conformance-groups-xml", "conformance-groups-protobuf", "<msg id=\"u1\"><nums><n>3</n><n>270</n></nums><name>p</name><name>qq</name></msg>"));
        Entity k = packs.decode("conformance-groups-json", "{\"id\":\"u1\",\"items\":[]}");
        check("requires <list> needs an item", packs.encode("conformance-groups-kinds", k).contains("\"bare\""), packs.encode("conformance-groups-kinds", k));
        k.list("probe.items").add(new Entity());
        check("requires <list> holds with an item", packs.encode("conformance-groups-kinds", k).contains("\"listed\""), packs.encode("conformance-groups-kinds", k));
        check("model keys of a shipped pack", packs.modelKeys("conformance-groups-json").contains("probe.items[].probe.subs[].probe.val"),
                packs.modelKeys("conformance-groups-json").toString());
    }

    /** Version 0.6: constants, defaults, value tables, field options, derived keys, caller-supplied keys. */
    static void rules(Engine packs) {
        String bitsHead = "format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 1\n";
        // Load checks.
        errorKind("via without map", "bad-directive", () -> Pack.parse(MINI + "field uid @a string via t\n", "t"));
        errorKind("unknown field option", "bad-directive", () -> Pack.parse(MINI + "field uid @a string loud\n", "t"));
        errorKind("swap on xml", "bad-directive", () -> Pack.parse(MINI + "field uid @a string swap\n", "t"));
        errorKind("swap needs whole bytes", "bad-directive", () -> Pack.parse(bitsHead + "field time_ms 0:0:12 uint swap\n", "t"));
        errorKind("trim needs ascii", "bad-directive", () -> Pack.parse(bitsHead + "field time_ms 0:0:16 uint trim\n", "t"));
        errorKind("root in a kind off xml", "bad-directive",
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire json\nkind a\nroot r\n", "t"));
        errorKind("option error before missing-distribution", "bad-directive",
                () -> Pack.parse("format x\nversion 0.1.0\nsource t\nwire xml\nroot r\nfield uid @a string swap\n", "t"));
        eq("const without kinds loads", 1, Pack.parse(MINI + "const @v 1\n", "t").kinds.get(0).scope.fixed.size());
        Pack roots = Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire xml\nkind a\nroot ra\nkind b\nroot rb\n", "t");
        eq("root per kind", "rb", roots.kind("b").root);
        throwsCode("xml kind without any root", GtException.Code.MISSING_ROOT,
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire xml\nkind a\nroot ra\nkind b\n", "t"));
        Pack tables = Pack.parse(MINI + "field uid @a string via s\nmap s 1 one\nmap i a 1\nmap i b -2\nmap f a 1\nmap f b 2.5\n", "t");
        eq("table type string", "string", tables.tableType("s"));
        eq("table type int", "int", tables.tableType("i"));
        eq("table type float", "float", tables.tableType("f"));
        Engine e = new Engine();
        e.loadModel(CORE + "key hae float m\nkey callsign string -\n");
        errorKind("default undeclared key", "undeclared-key", () -> e.add(Pack.parse(MINI + "default nope 1\n", "t")));
        errorKind("default of the wrong type", "key-type-mismatch", () -> e.add(Pack.parse(MINI + "default lat north\n", "t")));
        errorKind("table type against key type", "key-type-mismatch",
                () -> e.add(Pack.parse(MINI + "field lat @a string via t\nmap t a one\n", "t")));

        // Encode: const first, default through the table, every locator of a key written; decode: earliest success.
        e.add(Pack.parse("format r\nversion 0.1.0\ndistribution public\nsource t\nwire xml\nroot m\n"
                + "field uid @id string\nfield lat @lat float\nfield lat @y float\nfield callsign @c int via t\nfield hae @h float\n"
                + "const @id fixed\ndefault callsign two\ndefault hae -1\nmap t 1 one\nmap t 2 two\nmap t 3 one\n", "t"));
        Entity d = e.decode("r", "<m id=\"q\" lat=\"x\" y=\"2\" c=\"3\"/>");
        eq("earliest line that succeeds", 2.0, d.get("lat"));
        eq("table decode", "one", d.get("callsign"));
        eq("const not checked on decode", "q", d.get("uid"));
        eq("const over field, defaults, first table entry", "<m id=\"fixed\" lat=\"2\" y=\"2\" c=\"1\" h=\"-1\"/>", e.encode("r", d));
        eq("default through the table", "<m id=\"fixed\" c=\"2\" h=\"-1\"/>", e.encode("r", new Entity()));
        check("default leaves the entity alone", d.get("hae") == null, String.valueOf(d.get("hae")));
        errorKind("table without entry on decode", "transform-decode", () -> e.decode("r", "<m c=\"9\"/>"));
        errorKind("table without entry on encode", "transform-encode", () -> {
            Entity x = new Entity();
            x.put("callsign", "nine");
            e.encode("r", x);
        });
        errorKind("both locators fail", "transform-decode", () -> e.decode("r", "<m lat=\"x\" y=\"z\"/>"));

        // Field options on the bits wire.
        eq("swap 16", 0x3412L, BitsCodec.swapBytes(0x1234L, 16));
        eq("swap 64", 0x0807060504030201L, BitsCodec.swapBytes(0x0102030405060708L, 64));
        eq("ascii trim", "A B", BitsTransform.parse("ascii", "t", "t:1").decodeAscii(new byte[]{0x41, 0x20, 0x42, 0x20, 0x20, 0}, true));
        eq("ascii without trim keeps spaces", "A B  ", BitsTransform.parse("ascii", "t", "t:1").decodeAscii(new byte[]{0x41, 0x20, 0x42, 0x20, 0x20, 0}, false));
        check("ascii encode refuses a control byte", refuses(() -> BitsTransform.parse("ascii", "t", "t:1").encodeAscii("A\tB", 4)), "accepted");
        check("f64 refuses NaN on the wire", refuses(() -> BitsTransform.parse("f64", "t", "t:1").decode(0x7ff8000000000000L, 64)), "accepted");
        check("f32 refuses infinity on the wire", refuses(() -> BitsTransform.parse("f32", "t", "t:1").decode(0x7f800000L, 32)), "accepted");
        check("f32 refuses a value outside single range", refuses(() -> BitsTransform.parse("f32", "t", "t:1").encode(1e39, 32)), "accepted");
        check("pdouble refuses NaN on the wire", refuses(() -> PbTransform.byName("pdouble").decode(0x7ff8000000000000L, null)), "accepted");
        check("pfloat refuses a value outside single range", refuses(() -> PbTransform.byName("pfloat").encode(-1e39)), "accepted");
        Entity opt = packs.decode("conformance-rules-bits", "5a341240ee2d120146524e44");
        check("optional field beyond the input is absent", opt.get("callsign") == null && opt.get("ce") == null, opt.toString());
        eq("swapped little-endian field in an msb pack", 4660L, opt.get("time_ms"));

        // Derived keys.
        String core = CORE + "key lon float deg\nkey callsign string -\nkey course float deg\nkey speed_ms float m/s\n";
        String mod = "module m\nversion 0.1.0\ndistribution public\nsource t\nkey e float -\nkey n float -\nkey i int -\nkey s string -\n";
        Engine g = new Engine();
        g.loadModel(core);
        errorKind("derive unknown function", "bad-directive", () -> g.loadModel(mod + "derive m.e cube m.n\n"));
        errorKind("derive argument count", "bad-directive", () -> g.loadModel(mod + "derive m.e hypot m.n\n"));
        errorKind("derive undeclared key", "bad-directive", () -> g.loadModel(mod + "derive m.e neg m.zz\n"));
        errorKind("derive type", "bad-directive", () -> g.loadModel(mod + "derive m.i neg m.e\n"));
        errorKind("derive copy types differ", "bad-directive", () -> g.loadModel(mod + "derive m.i copy m.e\n"));
        errorKind("derive scale without parameter", "bad-directive", () -> g.loadModel(mod + "derive m.e scale m.n\n"));
        errorKind("derive int offset by a fraction", "bad-directive", () -> g.loadModel(mod + "derive m.i offset:0.5 time_ms\n"));
        g.loadModel(mod + "derive speed_ms hypot m.e m.n\nderive course bearing m.e m.n\nderive m.e east_of speed_ms course\n"
                + "derive m.n north_of speed_ms course\nderive m.i offset:-5 time_ms\nderive m.s join:- uid callsign\nderive lon scale:1/3 lat\n");
        Entity v = new Entity();
        v.put("m.e", 3.0);
        v.put("m.n", 4.0);
        v.put("time_ms", 12L);
        v.put("uid", "a");
        g.complete(v);
        eq("derive hypot", 5.0, v.get("speed_ms"));
        check("derive bearing", Math.abs((Double) v.get("course") - 36.86989764584402) < 1e-12, String.valueOf(v.get("course")));
        eq("derive int offset", 7L, v.get("m.i"));
        check("derive needs every argument", v.get("m.s") == null && v.get("lon") == null, v.toString());
        Entity w = new Entity();
        w.put("m.e", 0.0);
        w.put("m.n", 0.0);
        w.put("m.s", "kept");
        java.util.Map<String, String> ctx = new java.util.LinkedHashMap<>();
        ctx.put("callsign", "c");
        ctx.put("uid", "u");
        ctx.put("lat", "3");
        ctx.put("m.s", "replaced");
        g.complete(w, ctx);
        check("bearing of no velocity is absent", w.get("course") == null, String.valueOf(w.get("course")));
        eq("hypot of zero", 0.0, w.get("speed_ms"));
        eq("context does not replace a value", "kept", w.get("m.s"));
        eq("context value read as the key's type, then derived from", 1.0, w.get("lon"));
        Entity west = new Entity();
        west.put("m.e", -1.0);
        west.put("m.n", 0.0);
        g.complete(west);
        eq("bearing reduced to [0, 360)", 270.0, west.get("course"));
        errorKind("context undeclared key", "undeclared-key", () -> g.complete(new Entity(), java.util.Map.of("nope", "1")));
        errorKind("context wrong type", "key-type-mismatch", () -> g.complete(new Entity(), java.util.Map.of("time_ms", "soon")));
        errorKind("context float must be finite", "key-type-mismatch", () -> g.complete(new Entity(), java.util.Map.of("lat", "NaN")));

        // convert: no context and the same format skips derivation; a context turns it on.
        String in = "{\"id\":\"u1\",\"a\":3}";
        eq("same format, no context: byte-exact", in, packs.convert("conformance-derive", "conformance-derive", in));
        check("same format with an empty context derives",
                packs.convert("conformance-derive", "conformance-derive", in, new java.util.HashMap<>()).contains("\"neg_a\":-3"), "not derived");
        check("decode alone does not derive", packs.decode("conformance-derive", in).get("probe.neg_a") == null, "derived");
    }

    static boolean refuses(Runnable r) {
        try {
            r.run();
            return false;
        } catch (IllegalArgumentException ex) {
            return true;
        }
    }

    static void errorKind(String name, String kind, Runnable r) {
        try {
            r.run();
            check(name, false, "no error, want " + kind);
        } catch (GtException ex) {
            check(name, ex.kind().equals(kind) && ex.getMessage().startsWith(kind + ":"), ex.getMessage());
        }
    }

    /** Version 0.5: kinds, the json wire, bit order, the new bits transforms. */
    static void kinds(Engine packs) {
        // Entity.kind: set by decode, kept by a same-format convert, cleared by a cross-format one.
        Entity st = packs.decode("demo-kinds-bits", "2201000010000000");
        eq("kind format", "demo-kinds-bits", st.kindFormat());
        eq("kind name", "status", st.kindName());
        check("kind-less pack records no kind", packs.decode("cot-xml", "<event uid=\"a\"/>").kindFormat() == null, "kind set");
        // An entity whose kind names another format is encoded by `requires`.
        Entity pos = packs.decode("demo-kinds-protobuf", "0a074a2d303133333410809ccea8fe2e521b09fca9f1d24d023e4011cdcccccccc7c55c0190000000000205e40");
        eq("kind kept for encode", "position", pos.kindName());
        pos.clearKind();
        pos.put("course", 1.0);
        pos.put("speed_ms", 2.0);
        check("requires picks the first qualifying kind", packs.encode("demo-kinds-protobuf", pos).contains("52"), packs.encode("demo-kinds-protobuf", pos));
        Entity none = new Entity();
        none.put("uid", "x");
        errorKind("encode no-kind", "no-kind", () -> packs.encode("canonical-track-v2", none));
        eq("model keys union", "[time_ms, callsign, lat, lon, ce, course, track.vel_east_ms, track.vel_north_ms, speed_ms, hae, track.confirmed, track.coasting]",
                packs.modelKeys("demo-kinds-bits").toString());

        // Error kinds and their message prefix.
        errorKind("malformed-wire prefix", "malformed-wire", () -> packs.decode("geojson", "{"));
        errorKind("transform-decode prefix", "transform-decode", () -> packs.decode("cot-xml", "<event time=\"x\"/>"));
        errorKind("json wrong type", "transform-decode", () -> packs.decode("demo-track-json", "{\"lat\":\"1\"}"));
        errorKind("json bool encode", "transform-encode", () -> {
            Entity e = new Entity();
            e.put("track.confirmed", 2L);
            packs.encode("demo-track-json", e);
        });
        errorKind("ascii too long", "transform-encode", () -> {
            Entity e = packs.decode("demo-bits-bytes", "470200603aa4c011e302abccc3e0ba474f4154");
            e.put("callsign", "TOOLONG");
            packs.encode("demo-bits-bytes", e);
        });
        errorKind("sscale out of range", "transform-encode", () -> {
            Entity e = packs.decode("demo-bits-bytes", "470200603aa4c011e302abccc3e0ba474f4154");
            e.put("lat", 300.0);
            packs.encode("demo-bits-bytes", e);
        });
        errorKind("ascii control byte", "transform-decode", () -> packs.decode("demo-bits-bytes", "470200603aa4c011e302abccc3e0ba470a4154"));
        String bitsHead = "format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 4\n";
        errorKind("duplicate-kind", "duplicate-kind", () -> Pack.parse(MINI + "kind a\nkind a\n", "t"));
        // 0.6 withdrew duplicate-field: a key may be mapped by several lines, in common and in a kind.
        eq("one key at several locators loads", 3,
                Pack.parse(MINI + "field uid @a string\nfield uid @b string\nkind a\nfield uid @c string\n", "t").fields.size());
        errorKind("requires before kind", "bad-directive", () -> Pack.parse(MINI + "requires uid\n", "t"));
        errorKind("when without kind", "bad-directive", () -> Pack.parse(MINI + "when @k a\n", "t"));
        errorKind("bit_order on a text wire", "bad-directive",
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire json\nbit_order lsb\n", "t"));
        // 0.11 ruling 5b: bit_order stands after the wire line
        errorKind("bit_order before the wire line", "missing-wire",
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nbit_order lsb\nwire json\n", "t"));
        errorKind("bits when value too wide", "bad-directive", () -> Pack.parse(bitsHead + "kind a\nwhen 0:0:3 8\n", "t"));
        errorKind("f32 bad len", "bad-directive", () -> Pack.parse(bitsHead + "field x 0:0:31 f32\n", "t"));
        throwsCode("bool off the json wire", GtException.Code.BAD_DIRECTIVE, () -> Pack.parse(MINI + "field x @x bool\n", "t"));

        // Tokens: no escape inside quotes, and # inside quotes is literal.
        eq("quote without escape", "[source, a\\b #c, x]", Pack.tokenize("source \"a\\b #c\" x # tail", "t").toString());

        // Transforms.
        eq("round half away, positive", 3.0, Transform.roundHalfAway(2.5));
        eq("round half away, negative", -3.0, Transform.roundHalfAway(-2.5));
        eq("round below half", 0.0, Transform.roundHalfAway(0.49999999999999994));
        BitsTransform us = BitsTransform.parse("uscale:0.5:-1000", "t", "t:1");
        eq("uscale decode", 250.0, us.decode(2500L, 16));
        eq("uscale encode", 2500L, us.encode(250.0, 16));
        BitsTransform fr = BitsTransform.parse("sscale:1/10000000", "t", "t:1");
        eq("sscale fraction decode", -33.7512, fr.decode(-337512000L & 0xFFFFFFFFL, 32));
        eq("sscale fraction encode", -337512000L & 0xFFFFFFFFL, fr.encode(-33.7512, 32));
        eq("uint 64 top bit", -2L, BitsTransform.parse("uint", "t", "t:1").decode(-2L, 64));
        eq("f32 decode", 12.5, BitsTransform.parse("f32", "t", "t:1").decode(0x41480000L, 32));
        eq("ascii empty", "", BitsTransform.parse("ascii", "t", "t:1").decodeAscii(new byte[4], false));
        eq("json number canonical", "150", Json.canonNumber("1.5e2"));
        eq("json negative zero", "0", Json.canonNumber("-0.0"));
    }

    static final String CORE = "module core\nversion 0.1.0\ndistribution public\nsource t\n"
            + "key uid string -\nkey type string -\nkey lat float deg \"latitude, WGS84\"\nkey time_ms int ms\n";

    static void model(Engine packs) {
        ModelModule m = ModelModule.parse(CORE + "# comment\n", "t");
        eq("module name", "core", m.name);
        eq("module distribution", Distribution.PUBLIC, m.distribution);
        eq("module key type", "float", m.keys.get("lat"));
        eq("module key count", 4, m.keys.size());
        java.util.List<String> loaded = packs.modules().stream().map(x -> x.name).collect(java.util.stream.Collectors.toList());
        check("loaded modules", loaded.contains("core") && loaded.contains("track"), loaded.toString());
        eq("module of bare key", "core", ModelModule.moduleOf("lat"));
        eq("module of dotted key", "track", ModelModule.moduleOf("track.confidence"));
        eq("key of dotted key", "b.c", ModelModule.keyOf("a.b.c"));
        throwsCode("module unknown directive", GtException.Code.UNKNOWN_DIRECTIVE, () -> ModelModule.parse(CORE + "field uid @id string\n", "t"));
        throwsCode("module key with dot", GtException.Code.BAD_DIRECTIVE, () -> ModelModule.parse(CORE + "key a.b int -\n", "t"));
        throwsCode("module key bad type", GtException.Code.BAD_DIRECTIVE, () -> ModelModule.parse(CORE + "key a bool -\n", "t"));
        throwsCode("module bad distribution", GtException.Code.BAD_DIRECTIVE,
                () -> ModelModule.parse("module m\nversion 0.1.0\ndistribution secret\nsource t\n", "t"));
        // 0.11 ruling 5b: duplicate-key is checked right after the file, before missing-distribution
        throwsCode("module duplicate key before missing distribution", GtException.Code.DUPLICATE_KEY,
                () -> ModelModule.parse("module m\nversion 0.1.0\nsource t\nkey a int -\nkey a int -\n", "t"));
        throwsCode("module missing source", GtException.Code.MISSING_SOURCE,
                () -> ModelModule.parse("module m\nversion 0.1.0\ndistribution public\nkey a int -\n", "t"));
        throwsCode("module duplicate key", GtException.Code.DUPLICATE_KEY, () -> ModelModule.parse(CORE + "key uid string -\n", "t"));
        throwsCode("pack bad distribution", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution secret\nsource t\nwire xml\nroot r\n", "t"));
        throwsCode("pack missing distribution before missing source", GtException.Code.MISSING_DISTRIBUTION,
                () -> Pack.parse("format x\nversion 0.1.0\nwire xml\nroot r\n", "t"));
        Pack p = Pack.parse(MINI + "source \"second document\"\nuses track\nuses ext\nfield track.confidence @c float\n", "t");
        eq("pack sources", "[t, second document]", p.sources.toString());
        eq("pack uses", "[track, ext]", p.uses.toString());
        eq("pack distribution", Distribution.PUBLIC, p.distribution);

        try {
            new Engine().add(Pack.parse(MINI + "field uid @id string\n", "t"));
            check("kind in message", false, "no error");
        } catch (GtException ex) {
            eq("kind token", "unknown-module", ex.kind());
            check("kind in message", ex.getMessage().startsWith("unknown-module:"), ex.getMessage());
        }

        // Check order: refused before unknown-module; violation before module-not-used; then undeclared-key, then type.
        Engine pub = new Engine();
        pub.setMaxDistribution(Distribution.PUBLIC);
        throwsCode("refused before unknown-module", GtException.Code.DISTRIBUTION_REFUSED,
                () -> pub.add(Pack.parse("format x\nversion 0.1.0\ndistribution controlled\nsource t\nwire xml\nroot r\nuses nope\n", "t")));
        throwsCode("public engine refuses controlled module", GtException.Code.DISTRIBUTION_REFUSED,
                () -> pub.loadModel("module c\nversion 0.1.0\ndistribution controlled\nsource t\n"));
        Engine e = new Engine();
        e.loadModel(CORE);
        e.loadModel("module ctl\nversion 0.1.0\ndistribution controlled\nsource t\nkey code int -\n");
        throwsCode("duplicate module", GtException.Code.DUPLICATE_MODULE, () -> e.loadModel(CORE));
        throwsCode("violation before module-not-used", GtException.Code.DISTRIBUTION_VIOLATION,
                () -> e.add(Pack.parse(MINI + "uses ctl\nfield ext.a @a int\n", "t")));
        throwsCode("module-not-used before undeclared-key", GtException.Code.MODULE_NOT_USED,
                () -> e.add(Pack.parse(MINI + "field nope @n int\nfield ext.a @a int\n", "t")));
        throwsCode("undeclared-key before key-type-mismatch", GtException.Code.UNDECLARED_KEY,
                () -> e.add(Pack.parse(MINI + "field lat @lat int\nfield nope @n int\n", "t")));
        throwsCode("key-type-mismatch", GtException.Code.KEY_TYPE_MISMATCH,
                () -> e.add(Pack.parse(MINI + "field time_ms @t float\n", "t")));
        throwsCode("dotted remainder is undeclared", GtException.Code.UNDECLARED_KEY,
                () -> e.add(Pack.parse("format y\nversion 0.1.0\ndistribution controlled\nsource t\nwire xml\nroot r\nuses ctl\nfield ctl.code.x @c int\n", "t")));
        check("failed loads register nothing", e.packs().isEmpty(), e.packs().toString());
        e.add(Pack.parse("format y\nversion 0.1.0\ndistribution controlled\nsource t\nwire xml\nroot r\nuses ctl\n"
                + "field ctl.code @c int\nfield time_ms @t iso8601_ms\n", "t"));
        eq("controlled pack loads", 1, e.packs().size());
        eq("yields linscale", "float", BitsTransform.parse("linscale:1000:100", "t", "t:1").yields());
        eq("yields twos", "int", BitsTransform.parse("twos", "t", "t:1").yields());
        eq("yields pfloat", "float", PbTransform.byName("pfloat").yields());
        eq("yields psint", "int", PbTransform.byName("psint").yields());
        eq("yields pstring", "string", PbTransform.byName("pstring").yields());
    }

    static void numbers() {
        eq("float 30.0090027", "30.0090027", Transform.formatDouble(30.0090027));
        eq("float integer-valued", "30", Transform.formatDouble(30.0));
        eq("float negative", "-42.6", Transform.formatDouble(-42.6));
        eq("float small plain", "0.0000001", Transform.formatDouble(1e-7));
        eq("float large plain", "1000000000000000000000", Transform.formatDouble(1e21));
        eq("float 0.1", "0.1", Transform.formatDouble(0.1));
        eq("float 0.1+0.2", "0.30000000000000004", Transform.formatDouble(0.1 + 0.2));
        eq("float 2^53+2", "9007199254740994", Transform.formatDouble(9007199254740994.0));
        eq("float zero", "0", Transform.formatDouble(0.0));
        eq("float 2e-3", "0.002", Transform.formatDouble(2e-3));
        eq("float shortest 5e-324", "0." + "0".repeat(323) + "5",
                Transform.formatDouble(Double.MIN_VALUE));
        eq("float 1.0E23", "100000000000000000000000", Transform.formatDouble(1.0E23));
        for (double d : new double[]{30.0090027, -85.9578182, 45.3, 99.5, 1e-300, 123456.789e10, Math.PI, Double.MAX_VALUE}) {
            eq("float round-trip " + d, d, Double.parseDouble(Transform.formatDouble(d)));
        }
        eq("int decode", 1614456000000L, Transform.INT.decode("1614456000000"));
        eq("int encode from float", "1614456000000", Transform.INT.encode(1614456000000.0));
        check("int rejects fraction", rejects(Transform.INT, "1.5"), "accepted 1.5");
        check("float rejects NaN", rejects(Transform.FLOAT, "NaN"), "accepted NaN");
        check("float rejects hex", rejects(Transform.FLOAT, "0x1p3"), "accepted hex");
    }

    static void times() {
        eq("iso vector", 1614456000000L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00.000Z"));
        eq("iso no fraction", 1614456000000L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00Z"));
        eq("iso one digit fraction", 1614456000500L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00.5Z"));
        eq("iso sub-ms truncated", 1614456000123L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00.123987Z"));
        eq("iso encode", "2021-02-27T20:00:00.000Z", Transform.ISO8601_MS.encode(1614456000000L));
        eq("iso epoch", "1970-01-01T00:00:00.000Z", Transform.ISO8601_MS.encode(0L));
        eq("iso before epoch", "1969-12-31T23:59:59.999Z", Transform.ISO8601_MS.encode(-1L));
        eq("iso leap day", "2024-02-29T12:34:56.789Z",
                Transform.ISO8601_MS.encode(Transform.ISO8601_MS.decode("2024-02-29T12:34:56.789Z")));
        // 0.6: an offset and lowercase designators are accepted and converted to UTC.
        eq("iso offset plus", 1614452400000L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00+01:00"));
        eq("iso offset minus", 1614459600500L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00.5-01:00"));
        eq("iso offset zero", 1614456000000L, Transform.ISO8601_MS.decode("2021-02-27T20:00:00+00:00"));
        eq("iso lowercase t and z", 1614456000000L, Transform.ISO8601_MS.decode("2021-02-27t20:00:00z"));
        check("iso rejects offset without colon", rejects(Transform.ISO8601_MS, "2021-02-27T20:00:00+0100"), "accepted +0100");
        check("iso rejects no designator", rejects(Transform.ISO8601_MS, "2021-02-27T20:00:00"), "accepted no designator");
        check("iso rejects offset hour 24", rejects(Transform.ISO8601_MS, "2021-02-27T20:00:00+24:00"), "accepted +24:00");
        check("iso rejects Feb 30", rejects(Transform.ISO8601_MS, "2021-02-30T20:00:00Z"), "accepted Feb 30");
    }

    static boolean rejects(Transform t, String s) {
        try {
            t.decode(s);
            return false;
        } catch (IllegalArgumentException e) {
            return true;
        }
    }

    static final String MINI = "format x\nversion 0.1.0\ndistribution public\nsource t\nwire xml\nroot r\n";

    static void packErrors() {
        throwsCode("unknown directive", GtException.Code.UNKNOWN_DIRECTIVE, () -> Pack.parse(MINI + "frobnicate a b\n", "t"));
        throwsCode("unknown transform", GtException.Code.UNKNOWN_TRANSFORM, () -> Pack.parse(MINI + "field uid @uid base64\n", "t"));
        throwsCode("xml needs root", GtException.Code.MISSING_ROOT, () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire xml\n", "t"));
        throwsCode("unknown wire", GtException.Code.UNKNOWN_WIRE, () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire csv\n", "t"));
        throwsCode("bad xml locator", GtException.Code.BAD_LOCATOR, () -> Pack.parse(MINI + "field uid point string\n", "t"));
        throwsCode("bad geojson locator", GtException.Code.BAD_LOCATOR,
                () -> Pack.parse("format g\nversion 0.1.0\ndistribution public\nsource t\nwire geojson\nfield lat geometry.z float\n", "t"));
        Pack p = Pack.parse(MINI + "field remarks  \"a b/#text\"  string  # trailing comment\nfield t note/#text string\n", "t");
        eq("quoted locator", "a b/#text", p.fields.get(0).locator);
        eq("#text kept, comment dropped", "note/#text", p.fields.get(1).locator);
    }

    static void xmlTolerance(Engine e) {
        String messy = "<?xml version='1.0' encoding='UTF-8'?>\n<!-- c -->\n<event how='m-g' uid=\"J-01334\"\n"
                + "  type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00Z\">\n  <point le=\"99.5\" lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" ></point>\n"
                + "  <detail>\n    <contact callsign=\"GATOR\"/>\n  </detail>\n</event>\n";
        // The cot-xml pack writes the constant `version` first and the report time at `start` as well as `time`.
        String canon = "<event version=\"2.0\" uid=\"J-01334\" type=\"a-f-G-U-C\" time=\"2021-02-27T20:00:00.000Z\" start=\"2021-02-27T20:00:00.000Z\" how=\"m-g\">"
                + "<point lat=\"30.0090027\" lon=\"-85.9578182\" hae=\"-42.6\" ce=\"45.3\" le=\"99.5\"/>"
                + "<detail><contact callsign=\"GATOR\"/></detail></event>";
        eq("xml tolerance -> canonical", canon, e.convert("cot-xml", "cot-xml", messy));
    }

    static void residue(Engine e) {
        String in = "<event access=\"open\" version=\"1.0\" uid=\"U&amp;1\" type=\"a-h-A\" time=\"2021-02-27T20:00:00.000Z\" how=\"h-e\">"
                + "<point lat=\"1\" lon=\"2\" hae=\"3\" ce=\"4\" le=\"5\"/>"
                + "<detail><contact callsign=\"X\" endpoint=\"*:-1:stcp\"/><__group name=\"Cyan\" role=\"Team\"/>"
                + "<remarks>hi &lt;there&gt;</remarks><status/></detail></event>";
        // Residue is the unmapped attributes of the root element; unmapped child elements and their attributes
        // are not carried (0.1.1 ruling 6). `version` is a const of the pack: mapped, so not residue, and written as 2.0.
        String want = "<event version=\"2.0\" uid=\"U&amp;1\" type=\"a-h-A\" time=\"2021-02-27T20:00:00.000Z\" start=\"2021-02-27T20:00:00.000Z\" how=\"h-e\" access=\"open\">"
                + "<point lat=\"1\" lon=\"2\" hae=\"3\" ce=\"4\" le=\"5\"/>"
                + "<detail><contact callsign=\"X\"/></detail></event>";
        eq("xml residue round-trip", want, e.convert("cot-xml", "cot-xml", in));
        String gj = e.convert("cot-xml", "geojson", in);
        check("xml residue does not cross into geojson", !gj.contains("access") && !gj.contains("Cyan"), gj);
        eq("geojson integer-valued floats", "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[2,1,3]},"
                + "\"properties\":{\"type\":\"a-h-A\",\"time_ms\":1614456000000,\"how\":\"h-e\",\"ce\":4,\"le\":5,\"callsign\":\"X\"},\"id\":\"U&1\"}", gj);

        String g = "{ \"id\": \"A\", \"type\": \"Feature\", \"bbox\": [0, 0, 1, 1],\n \"properties\": {\"speed\": 3.50, \"callsign\": \"Q\\\"x\", \"tags\": [\"a\", {\"b\": null}]},"
                + " \"geometry\": {\"type\": \"Point\", \"coordinates\": [10.5, 20.25]} }";
        // geojson residue (ruling 13 of 0.6): a number comes back as a string of its text as written; an array or
        // an object comes back as it was.
        eq("geojson residue round-trip", "{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[10.5,20.25]},"
                + "\"properties\":{\"callsign\":\"Q\\\"x\",\"speed\":\"3.50\",\"tags\":[\"a\",{\"b\":null}]},\"id\":\"A\",\"bbox\":[0,0,1,1]}",
                e.convert("geojson", "geojson", g));
        eq("geojson residue drops null", "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{},\"id\":\"A\"}",
                e.convert("geojson", "geojson", "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"gone\":null},\"id\":\"A\",\"bbox\":null}"));
        eq("geojson accepts a repeated member name, last value", "B",
                e.decode("geojson", "{\"type\":\"Feature\",\"geometry\":null,\"properties\":{},\"id\":\"A\",\"id\":\"B\"}").get("uid"));
        errorKind("json refuses a repeated member name", "malformed-wire", () -> e.decode("demo-track-json", "{\"id\":\"A\",\"id\":\"B\"}"));
    }

    static void typemap() {
        Engine t = new Engine();
        t.loadModel(CORE);
        t.add(Pack.parse("format nat\nversion 0.1.0\ndistribution public\nsource t\nwire xml\nroot m\nfield uid @id string\nfield type @kind string\n"
                + "typemap TANK a-h-G-E-V-A-T\ntypemap FW a-f-A-M-F\n", "t"));
        Entity e = t.decode("nat", "<m id=\"1\" kind=\"TANK\"/>");
        eq("typemap decode", "a-h-G-E-V-A-T", e.get("type"));
        eq("typemap encode", "<m id=\"1\" kind=\"TANK\"/>", t.encode("nat", e));
        Entity u = t.decode("nat", "<m id=\"2\" kind=\"ZZZ\"/>");
        eq("typemap unmapped passes through", "ZZZ", u.get("type"));
        check("typemap unmapped not in residue", u.residue("nat").isEmpty(), u.residue("nat").toString());
        eq("typemap unmapped round-trip", "<m id=\"2\" kind=\"ZZZ\"/>", t.encode("nat", u));
    }

    static void wireErrors(Engine e) {
        throwsCode("missing root", GtException.Code.MISSING_ROOT, () -> e.decode("cot-xml", "<evnt uid=\"a\"/>"));
        throwsCode("malformed xml", GtException.Code.MALFORMED_WIRE, () -> e.decode("cot-xml", "<event uid=\"a\">"));
        throwsCode("malformed json", GtException.Code.MALFORMED_WIRE, () -> e.decode("geojson", "{\"type\":\"Feature\","));
        throwsCode("not a feature", GtException.Code.MALFORMED_WIRE, () -> e.decode("geojson", "{\"type\":\"Point\"}"));
        throwsCode("unknown format", GtException.Code.UNKNOWN_FORMAT, () -> e.decode("vmf", "x"));
        try {
            e.decode("cot-xml", "<event uid=\"a\" time=\"yesterday\"><point lat=\"north\" lon=\"2\"/></event>");
            check("transform decode failure", false, "no error");
        } catch (GtException ex) {
            check("transform decode failure code", ex.code() == GtException.Code.TRANSFORM_DECODE, ex.getMessage());
            check("transform decode lists every field", ex.getMessage().contains("time_ms") && ex.getMessage().contains("lat"), ex.getMessage());
            check("transform decode partial entity", ex.partial() != null && "a".equals(ex.partial().get("uid"))
                    && ex.partial().get("lat") == null && Double.valueOf(2.0).equals(ex.partial().get("lon")), String.valueOf(ex.partial()));
        }
    }

    static void bits(Engine e) {
        // The loaded demo-bits pack: round-trip identity and decoded model values.
        String hex = "2244a6e03811090000";
        eq("bits round-trip identity", hex, e.convert("demo-bits", "demo-bits", hex));
        Entity d = e.decode("demo-bits", hex);
        check("bits linscale lat", Math.abs((Double) d.get("lat") - 35.247092482655034) < 1e-9, String.valueOf(d.get("lat")));
        check("bits linscale lon", Math.abs((Double) d.get("lon") - 54.99801397228908) < 1e-9, String.valueOf(d.get("lon")));
        eq("bits uint time_ms", 290L, d.get("time_ms"));
        eq("bits hex whitespace tolerated", hex, e.convert("demo-bits", "demo-bits", "2244 a6e0 3811 0900 00"));

        // Transform behaviour in isolation.
        BitsTransform u = BitsTransform.parse("uint", "t", "t:1");
        eq("uint decode", 5L, u.decode(5L, 4));
        eq("uint encode low bits", 5L, u.encode(5L, 4));
        BitsTransform tw = BitsTransform.parse("twos", "t", "t:1");
        eq("twos decode negative", -1L, tw.decode(0xFL, 4));
        eq("twos decode positive", 7L, tw.decode(7L, 4));
        eq("twos encode negative low bits", 0xFL, tw.encode(-1L, 4));
        BitsTransform ls = BitsTransform.parse("linscale:1000:100", "t", "t:1");
        eq("linscale decode", 50.0, ls.decode(500L, 16));
        eq("linscale encode rounds", 500L, ls.encode(50.0, 16));

        // Wire-kind mismatches and bits-pack structural errors.
        throwsCode("bits transform on text wire", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire geojson\nfield lat geometry.lat uint\n", "t"));
        throwsCode("text transform on bits wire", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 2\nfield x 0:0:8 string\n", "t"));
        throwsCode("bits needs word_bytes", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nfield x 0:0:8 uint\n", "t"));
        throwsCode("word_bytes only on bits", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire geojson\nword_bytes 2\n", "t"));
        eq("bits field past its word loads", "0:4:8",
                Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield x 0:4:8 uint\n", "t").fields.get(0).locator);
        throwsCode("bits len over 64", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield x 0:0:65 uint\n", "t"));
        throwsCode("bad linscale params", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 4\nfield x 0:0:16 linscale:abc:90\n", "t"));
    }
}
