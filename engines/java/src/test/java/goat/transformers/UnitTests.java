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
        throwsCode("list name with a dot", GtException.Code.BAD_MODEL, () -> ModelModule.parse(probe + "list a.b\n", "t"));

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
        throwsCode("xml kind without any root", GtException.Code.BAD_PACK,
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
        errorKind("bit_order before a text wire line", "bad-directive",
                () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nbit_order lsb\nwire json\n", "t"));
        errorKind("bits when value too wide", "bad-directive", () -> Pack.parse(bitsHead + "kind a\nwhen 0:0:3 8\n", "t"));
        errorKind("f32 bad len", "bad-directive", () -> Pack.parse(bitsHead + "field x 0:0:31 f32\n", "t"));
        throwsCode("bool off the json wire", GtException.Code.UNKNOWN_TRANSFORM, () -> Pack.parse(MINI + "field x @x bool\n", "t"));

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
        throwsCode("module key with dot", GtException.Code.BAD_MODEL, () -> ModelModule.parse(CORE + "key a.b int -\n", "t"));
        throwsCode("module key bad type", GtException.Code.BAD_MODEL, () -> ModelModule.parse(CORE + "key a bool -\n", "t"));
        throwsCode("module bad distribution", GtException.Code.BAD_MODEL,
                () -> ModelModule.parse("module m\nversion 0.1.0\ndistribution secret\nsource t\n", "t"));
        throwsCode("module missing distribution before duplicate key", GtException.Code.MISSING_DISTRIBUTION,
                () -> ModelModule.parse("module m\nversion 0.1.0\nsource t\nkey a int -\nkey a int -\n", "t"));
        throwsCode("module missing source", GtException.Code.MISSING_SOURCE,
                () -> ModelModule.parse("module m\nversion 0.1.0\ndistribution public\nkey a int -\n", "t"));
        throwsCode("module duplicate key", GtException.Code.DUPLICATE_KEY, () -> ModelModule.parse(CORE + "key uid string -\n", "t"));
        throwsCode("pack bad distribution", GtException.Code.BAD_PACK,
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
        throwsCode("xml needs root", GtException.Code.BAD_PACK, () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire xml\n", "t"));
        throwsCode("unknown wire", GtException.Code.BAD_PACK, () -> Pack.parse("format x\nversion 0.1.0\ndistribution public\nsource t\nwire csv\n", "t"));
        throwsCode("bad xml locator", GtException.Code.BAD_PACK, () -> Pack.parse(MINI + "field uid point string\n", "t"));
        throwsCode("bad geojson locator", GtException.Code.BAD_PACK,
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
        throwsCode("bits transform on text wire", GtException.Code.UNKNOWN_TRANSFORM,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire geojson\nfield lat geometry.lat uint\n", "t"));
        throwsCode("text transform on bits wire", GtException.Code.UNKNOWN_TRANSFORM,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 2\nfield x 0:0:8 string\n", "t"));
        throwsCode("bits needs word_bytes", GtException.Code.BAD_PACK,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nfield x 0:0:8 uint\n", "t"));
        throwsCode("word_bytes only on bits", GtException.Code.BAD_PACK,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire geojson\nword_bytes 2\n", "t"));
        eq("bits field past its word loads", "0:4:8",
                Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield x 0:4:8 uint\n", "t").fields.get(0).locator);
        throwsCode("bits len over 64", GtException.Code.BAD_DIRECTIVE,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 1\nfield x 0:0:65 uint\n", "t"));
        throwsCode("bad linscale params", GtException.Code.BAD_PACK,
                () -> Pack.parse("format b\nversion 0.1.0\ndistribution public\nsource t\nwire bits\nword_bytes 4\nfield x 0:0:16 linscale:abc:90\n", "t"));
    }
}
