package goat.transformers;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

/**
 * Runs every conversion vector of every pack under the packs directory, every load vector under
 * {@code conformance/load-vectors}, then the unit checks. Exits non-zero on any failure.
 */
public final class TestRunner {
    private static int failures = 0;
    private static int unitChecks = 0;
    private static final List<String> failed = new ArrayList<>();

    /** {@code <pack>/<file> (<vector name>)}. */
    @SuppressWarnings("unchecked")
    private static String label(Path packsDir, Path f) {
        String file = packsDir.relativize(f).toString();
        try {
            Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
            Object name = doc instanceof Map ? ((Map<String, Object>) doc).get("name") : null;
            return name instanceof String ? file + " (" + name + ")" : file;
        } catch (IOException | RuntimeException ex) {
            return file;
        }
    }

    private static void fail(String label, String why) {
        failures++;
        failed.add(label);
        System.out.println("FAIL " + label + ": " + why);
    }

    public static void main(String[] args) throws IOException {
        Path packsDir = Paths.get(args.length > 0 ? args[0] : "../../packs");
        // The directory loader, one pack at a time: a pack that does not load is a failure, and the vectors of the
        // other packs still run.
        Engine engine = new Engine();
        // core.def first, then byte order of file name, each module after the modules it uses.
        for (String[] m : Engine.modelsInLoadOrder(Engine.defaultModelsDir(packsDir))) {
            try {
                engine.loadModel(m[1], m[0]);
            } catch (GtException ex) {
                fail("model " + Paths.get(m[0]).getFileName(), "does not load: " + ex.getMessage());
            }
        }
        try (Stream<Path> s = Files.list(packsDir)) {
            for (Path d : (Iterable<Path>) s.sorted()::iterator) {
                Path def = d.resolve("pack.def");
                if (!Files.isRegularFile(def)) continue;
                try {
                    engine.loadPack(Files.readString(def, StandardCharsets.UTF_8), def.toString());
                } catch (GtException ex) {
                    fail("pack " + d.getFileName(), "does not load: " + ex.getMessage());
                }
            }
        }
        int vectors = 0, passed = 0;
        List<Path> files = new ArrayList<>();
        try (Stream<Path> s = Files.list(packsDir)) {
            for (Path d : (Iterable<Path>) s.sorted()::iterator) {
                Path vd = d.resolve("vectors");
                if (!Files.isDirectory(vd)) continue;
                try (Stream<Path> v = Files.list(vd)) {
                    v.filter(p -> p.toString().endsWith(".json")).sorted().forEach(files::add);
                }
            }
        }
        for (Path f : files) {
            vectors++;
            String label = label(packsDir, f);
            String why;
            try {
                why = runVector(engine, f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) passed++;
            else fail(label, why);
        }
        System.out.println("conversion vectors: " + passed + "/" + vectors + " passed (" + engine.packs().size() + " packs, "
                + engine.modules().size() + " model modules)");

        int loadVectors = 0, loadPassed = 0;
        Path loadDir = packsDir.resolve("conformance").resolve("load-vectors");
        List<Path> loadFiles = new ArrayList<>();
        if (Files.isDirectory(loadDir)) {
            try (Stream<Path> v = Files.list(loadDir)) {
                v.filter(p -> p.toString().endsWith(".json")).sorted().forEach(loadFiles::add);
            }
        }
        for (Path f : loadFiles) {
            loadVectors++;
            String why;
            try {
                why = runLoadVector(f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) loadPassed++;
            else fail(label(packsDir, f), why);
        }
        System.out.println("load vectors: " + loadPassed + "/" + loadVectors + " passed");
        if (loadVectors == 0) {
            fail("load vectors", "none found under " + loadDir);
        }

        int capVectors = 0, capPassed = 0;
        Path capDir = packsDir.resolve("conformance").resolve("capability-vectors");
        List<Path> capFiles = new ArrayList<>();
        if (Files.isDirectory(capDir)) {
            try (Stream<Path> v = Files.list(capDir)) {
                v.filter(p -> p.toString().endsWith(".json")).sorted().forEach(capFiles::add);
            }
        }
        for (Path f : capFiles) {
            capVectors++;
            String why;
            try {
                why = runCapabilityVector(engine, f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) capPassed++;
            else fail(label(packsDir, f), why);
        }
        System.out.println("capability vectors: " + capPassed + "/" + capVectors + " passed");
        if (capVectors == 0) {
            fail("capability vectors", "none found under " + capDir);
        }

        int before = failures;
        UnitTests.run(engine);
        UnitTests.packsOnly(packsDir);
        UnitTests.malformedSweep(engine, files);
        System.out.println("unit checks: " + (unitChecks - (failures - before)) + "/" + unitChecks + " passed");
        if (vectors == 0) {
            fail("conversion vectors", "none found under " + packsDir);
        }
        if (!failed.isEmpty()) {
            System.out.println("failed (" + failed.size() + "):");
            for (String l : failed) System.out.println("  " + l);
        }
        System.out.println(failures == 0 ? "OK" : "FAILED (" + failures + ")");
        System.exit(failures == 0 ? 0 : 1);
    }

    @SuppressWarnings("unchecked")
    static String runVector(Engine engine, Path f) throws IOException {
        Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) return "vector is not a JSON object";
        Map<String, Object> v = (Map<String, Object>) doc;
        for (String k : new String[]{"name", "from", "to"}) {
            if (!(v.get(k) instanceof String)) return "vector lacks string \"" + k + "\"";
        }
        String from = (String) v.get("from"), to = (String) v.get("to");
        if (!(v.get("input") instanceof String)) return "vector lacks string \"input\"";
        String input = (String) v.get("input");
        Map<String, String> context = null;
        if (v.containsKey("context")) {
            if (!(v.get("context") instanceof Map)) return "\"context\" is not an object";
            context = new java.util.LinkedHashMap<>();
            for (Map.Entry<String, Object> c : ((Map<String, Object>) v.get("context")).entrySet()) {
                if (!(c.getValue() instanceof String)) return "context." + c.getKey() + " is not in string form";
                context.put(c.getKey(), (String) c.getValue());
            }
        }
        long maxItems = engine.maxItems();
        if (v.containsKey("max_items")) {
            Object m = v.get("max_items");
            if (!(m instanceof Json.Num) || !Transform.UNSIGNED.matcher(((Json.Num) m).text).matches()
                    || ((Json.Num) m).text.length() > 18) {
                return "invalid vector: \"max_items\" is not an integer of 0 or more";
            }
            maxItems = Long.parseLong(((Json.Num) m).text);
        }
        if (v.containsKey("model")) {
            if (!(v.get("model") instanceof Map)) return "\"model\" is not an object";
            for (Map.Entry<String, Object> m : ((Map<String, Object>) v.get("model")).entrySet()) {
                if (!(m.getValue() instanceof String)) continue;   // reported with the check below
                String why = modelValueInvalid(engine, m.getKey(), (String) m.getValue());
                if (why != null) return "invalid vector: model." + m.getKey() + ": " + why;
            }
        }
        long defaultMax = engine.maxItems();
        engine.setMaxItems(maxItems);
        try {
            return runVectorChecks(engine, v, from, to, input, context);
        } finally {
            engine.setMaxItems(defaultMax);
        }
    }

    /**
     * Ruling 2c of 0.11: a member named by a model key or an item path is read by the grammar of the key's declared
     * type, {@code "<list>.#"} is an unsigned decimal integer or {@code absent}; the {@code @} members are not numbers.
     * Null when the value is valid, else the reason.
     */
    static String modelValueInvalid(Engine engine, String key, String value) {
        if (key.startsWith("@")) return null;
        String k = key;
        while (k.indexOf('[') >= 0) {
            int close = k.indexOf("].");
            if (close < 0) return null;   // not an item path; the check reports it
            k = k.substring(close + 2);
        }
        if (k.startsWith("@")) return null;
        if (k.endsWith(".#")) {
            return value.equals("absent") || Transform.UNSIGNED.matcher(value).matches() ? null
                    : "a count is an unsigned decimal integer or absent, got \"" + value + "\"";
        }
        String type = engine.keyType(k);
        if (type == null) return null;   // no declared key: the check reports it
        try {
            if (type.equals("int")) Transform.parseInt(value);
            else if (type.equals("float")) Transform.parseFloat(value);
        } catch (IllegalArgumentException ex) {
            return "\"" + value + "\" is not " + type + " text (ruling 2 of 0.11)";
        }
        return null;
    }

    @SuppressWarnings("unchecked")
    private static String runVectorChecks(Engine engine, Map<String, Object> v, String from, String to, String input,
                                          Map<String, String> context) {
        boolean wantsError = v.containsKey("expect_error");
        if (wantsError == v.containsKey("expect")) return "vector needs exactly one of \"expect\" and \"expect_error\"";
        if (wantsError) {
            if (!(v.get("expect_error") instanceof String)) return "\"expect_error\" is not a string";
            String kind = (String) v.get("expect_error");
            try {
                String got = engine.convert(from, to, input, context);
                return "convert succeeded, want error " + kind + "\n  got  " + got;
            } catch (GtException ex) {
                if (!ex.kind().equals(kind)) return "want error " + kind + ", got " + ex.getMessage();
                if (!ex.getMessage().startsWith(kind + ":")) {
                    return "message does not begin with \"" + kind + ":\": " + ex.getMessage();
                }
            }
        } else {
            if (!(v.get("expect") instanceof String)) return "\"expect\" is not a string";
            String expect = (String) v.get("expect");
            String got = engine.convert(from, to, input, context);
            if (!got.equals(expect)) return "convert mismatch\n  want " + expect + "\n  got  " + got;
        }
        if (v.containsKey("model")) {
            if (!(v.get("model") instanceof Map)) return "\"model\" is not an object";
            Map<String, Object> model = (Map<String, Object>) v.get("model");
            // "@complete": true moves the checks to the entity as convert hands it to the encoder.
            boolean complete = Boolean.TRUE.equals(model.get("@complete"));
            if (model.containsKey("@complete") && !complete) return "model.@complete is not true";
            Entity e = engine.decode(from, input);
            if (complete) {
                if (!from.equals(to)) e.clearKind();
                engine.complete(e, context);
            }
            // "@absent" (Version 0.9): keys, item paths and list names the entity must not have. An entry that is
            // also a member of "model", as text, makes the vector invalid (ruling 21 of 0.9).
            List<String> absent = new ArrayList<>();
            if (model.containsKey("@absent")) {
                if (!(model.get("@absent") instanceof List)) return "model.@absent is not an array";
                for (Object a : (List<Object>) model.get("@absent")) {
                    if (!(a instanceof String)) return "model.@absent holds an entry that is not a string";
                    String k = (String) a;
                    if (model.containsKey(k)) return "invalid vector: model.@absent lists " + k + ", which is also a member of model";
                    absent.add(k);
                }
            }
            for (String k : absent) {
                String why = absentCheck(e, k);
                if (why != null) return "model.@absent " + k + ": " + why;
            }
            for (Map.Entry<String, Object> m : model.entrySet()) {
                if (m.getKey().equals("@complete") || m.getKey().equals("@absent")) continue;
                if (!(m.getValue() instanceof String)) return "model." + m.getKey() + " is not in string form";
                String want = (String) m.getValue();
                if (m.getKey().equals("@kind")) {
                    if (!from.equals(e.kindFormat()) || !want.equals(e.kindName())) {
                        return "@kind: want (" + from + ", " + want + ") got (" + e.kindFormat() + ", " + e.kindName() + ")";
                    }
                    continue;
                }
                String why = modelCheck(e, m.getKey(), want, complete);
                if (why != null) return "model." + m.getKey() + ": " + why;
            }
        }
        return null;
    }

    /**
     * One load vector: a fresh engine, the limit set first, the modules loaded in order, then the pack, stopping at
     * the first failure. Returns null on a pass, else the reason.
     */
    @SuppressWarnings("unchecked")
    static String runLoadVector(Path f) throws IOException {
        Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) return "load vector is not a JSON object";
        Map<String, Object> v = (Map<String, Object>) doc;
        if (!(v.get("name") instanceof String)) return "load vector lacks string \"name\"";
        if (!(v.get("models") instanceof List)) return "load vector lacks array \"models\"";
        List<String> packTexts = new ArrayList<>();
        if (v.containsKey("pack") == v.containsKey("packs")) return "load vector needs exactly one of \"pack\" and \"packs\"";
        if (v.containsKey("pack")) {
            if (!(v.get("pack") instanceof String)) return "load vector lacks string \"pack\"";
            packTexts.add((String) v.get("pack"));
        } else {
            if (!(v.get("packs") instanceof List)) return "\"packs\" is not an array";
            for (Object p : (List<Object>) v.get("packs")) {
                if (!(p instanceof String)) return "\"packs\" holds an entry that is not a string";
                packTexts.add((String) p);
            }
        }
        String expect = null;
        if (v.containsKey("expect_error")) {
            if (!(v.get("expect_error") instanceof String)) return "\"expect_error\" is not a string";
            expect = (String) v.get("expect_error");
        }
        Engine engine = new Engine();
        if (v.containsKey("max_distribution")) {
            Distribution limit = v.get("max_distribution") instanceof String
                    ? Distribution.byToken((String) v.get("max_distribution")) : null;
            if (limit == null) return "\"max_distribution\" is neither public nor controlled";
            engine.setMaxDistribution(limit);
        }
        GtException failure = null;
        try {
            int n = 0;
            for (Object m : (List<Object>) v.get("models")) {
                n++;
                if (!(m instanceof String)) return "models[" + (n - 1) + "] is not a string";
                engine.loadModel((String) m, "models[" + (n - 1) + "]");
            }
            for (int i = 0; i < packTexts.size(); i++) {
                engine.loadPack(packTexts.get(i), packTexts.size() == 1 && v.containsKey("pack") ? "pack" : "packs[" + i + "]");
            }
        } catch (GtException ex) {
            failure = ex;
        }
        if (expect == null) return failure == null ? null : "load failed, want success: " + failure.getMessage();
        if (failure == null) return "load succeeded, want " + expect;
        if (!failure.kind().equals(expect)) return "want " + expect + " got " + failure.getMessage();
        if (!failure.getMessage().startsWith(expect + ":")) return "message does not begin with \"" + expect + ":\": " + failure.getMessage();
        return null;
    }

    /** One capability vector: the grade and both lists of {@code capability(from, to)}, entry for entry. */
    @SuppressWarnings("unchecked")
    static String runCapabilityVector(Engine engine, Path f) throws IOException {
        Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) return "capability vector is not a JSON object";
        Map<String, Object> v = (Map<String, Object>) doc;
        for (String k : new String[]{"name", "from", "to", "grade"}) {
            if (!(v.get(k) instanceof String)) return "capability vector lacks string \"" + k + "\"";
        }
        for (String k : new String[]{"carried", "dropped"}) {
            if (!(v.get(k) instanceof List)) return "capability vector lacks array \"" + k + "\"";
        }
        Engine.Capability c = engine.capability((String) v.get("from"), (String) v.get("to"));
        if (!c.grade.equals(v.get("grade"))) return "grade: want " + v.get("grade") + " got " + c.grade;
        if (!c.carried.equals(v.get("carried"))) return "carried: want " + v.get("carried") + " got " + c.carried;
        if (!c.dropped.equals(v.get("dropped"))) return "dropped: want " + v.get("dropped") + " got " + c.dropped;
        return null;
    }

    /**
     * One {@code model} check against an entity or an item: {@code "<list>.#"} is the number of items of a list
     * ({@code "absent"} for an absent list), {@code "<list>[<i>].<key>"} a check inside item {@code i}, anything
     * else a model key. A model key never contains {@code [} and never ends in {@code .#}.
     */
    static String modelCheck(Entity e, String key, String want, boolean relative) {
        int open = key.indexOf('[');
        if (open >= 0) {
            int close = key.indexOf(']', open);
            if (close < 0 || close + 1 >= key.length() || key.charAt(close + 1) != '.') return "not <list>[<i>].<key>";
            int i;
            try {
                i = Integer.parseInt(key.substring(open + 1, close));
            } catch (NumberFormatException ex) {
                return "not <list>[<i>].<key>";
            }
            String list = key.substring(0, open);
            List<Entity> items = e.list(list);
            if (items == null) return "list " + list + " is absent";
            if (i < 0 || i >= items.size()) return "list " + list + " has " + items.size() + " items, no item " + i;
            return modelCheck(items.get(i), key.substring(close + 2), want, relative);
        }
        if (key.endsWith(".#")) {
            List<Entity> items = e.list(key.substring(0, key.length() - 2));
            if (want.equals("absent")) return items == null ? null : "want absent, got " + items.size() + " items";
            if (items == null) return "absent, want " + want + " items";
            boolean same = Transform.UNSIGNED.matcher(want).matches()
                    && new java.math.BigInteger(want).equals(java.math.BigInteger.valueOf(items.size()));
            return same ? null : "want " + want + " items, got " + items.size();
        }
        if (key.equals("@kind")) {
            // the kind an item recorded when it was decoded; it fails for an item that recorded none
            return e.kindName() != null && want.equals(e.kindName()) ? null : "want kind " + want + " got " + e.kindName();
        }
        return modelMismatch(want, e.get(key), relative);
    }

    /**
     * One {@code "@absent"} entry: {@code "<list>[<i>].<entry>"} needs item {@code i} to exist and to lack the rest;
     * anything else is a model key or a list name, and the entity has neither a value nor a list by that name.
     */
    static String absentCheck(Entity e, String key) {
        int open = key.indexOf('[');
        if (open >= 0) {
            int close = key.indexOf(']', open);
            if (close < 0 || close + 1 >= key.length() || key.charAt(close + 1) != '.') return "not <list>[<i>].<key>";
            int i;
            try {
                i = Integer.parseInt(key.substring(open + 1, close));
            } catch (NumberFormatException ex) {
                return "not <list>[<i>].<key>";
            }
            String list = key.substring(0, open);
            List<Entity> items = e.list(list);
            if (items == null) return "list " + list + " is absent";
            if (i < 0 || i >= items.size()) return "list " + list + " has " + items.size() + " items, no item " + i;
            return absentCheck(items.get(i), key.substring(close + 2));
        }
        if (e.get(key) != null) return "present, value " + e.get(key);
        List<Entity> items = e.list(key);
        if (items != null) return "a list of " + items.size() + " items";
        return null;
    }

    /** {@code relative}: floats compare within 1e-9 relative (a completed entity), else within 1e-9. */
    static String modelMismatch(String want, Object have, boolean relative) {
        if (have == null) return "absent, want " + want;
        if (have instanceof Double) {
            double w;
            try {
                w = Transform.parseFloat(want);
            } catch (IllegalArgumentException ex) {
                return "want \"" + want + "\" got float " + have;
            }
            double h = (Double) have;
            boolean ok = relative
                    ? (h == w || Math.abs(h - w) < 1e-9 * Math.max(Math.abs(h), Math.abs(w)))
                    : Math.abs(w - h) <= 1e-9;
            return ok ? null : "want " + want + " got " + have;
        }
        if (have instanceof Long) {
            try {
                return Transform.parseInt(want) == (Long) have ? null : "want " + want + " got " + have;
            } catch (IllegalArgumentException ex) {
                return "want \"" + want + "\" got int " + have;
            }
        }
        return want.equals(have) ? null : "want \"" + want + "\" got \"" + have + "\"";
    }

    static void check(String name, boolean ok, String detail) {
        unitChecks++;
        if (!ok) {
            fail("unit " + name, detail);
        }
    }

    static void eq(String name, Object want, Object got) {
        check(name, want.equals(got), "want <" + want + "> got <" + got + ">");
    }

    static void throwsCode(String name, GtException.Code code, Runnable r) {
        try {
            r.run();
            check(name, false, "no error, want " + code);
        } catch (GtException ex) {
            check(name, ex.code() == code, "want " + code + " got " + ex.code() + ": " + ex.getMessage());
        } catch (RuntimeException ex) {
            check(name, false, "want GtException " + code + " got " + ex);
        }
    }
}
