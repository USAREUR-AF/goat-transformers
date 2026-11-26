package goat.transformers;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.stream.Stream;

/**
 * The reduced-build check of spec 0.24 ("What pins it"), run on a jar built with {@code build.sh --wires} with any
 * set of wires ({@code reduced-check.sh} runs it on xml, json and geojson, {@code single-wire-check.sh} on each wire
 * alone). It compiles against that build only, so it names no codec. It checks:
 * <ul>
 * <li>every pack on a wire of the build loads, and every pack on a wire of the specification the build lacks is
 * refused as {@code unknown-wire} with a message that names the wire (ruling 1c);</li>
 * <li>every conversion vector whose {@code from} and {@code to} packs both loaded passes (ruling 1b), except a
 * vector of an outer pack, a pack with an {@code inner} line, on either side: ruling 1 of 0.34 lets the checks at the
 * {@code inner} line differ between builds, so no vector of an outer pack runs;</li>
 * <li>the capability vectors and load vectors that touch only wires of the build, and no outer pack, pass as in
 * the full build;</li>
 * <li>for each wire of the specification the build lacks, loading one pack on it is {@code unknown-wire} with a
 * message that names the wire and says the build does not have it, and its format is then
 * {@code unknown-format} (rulings 1c and 1e); a {@code wire} value that is no wire stays plain
 * {@code unknown-wire}.</li>
 * </ul>
 * Which wire a pack is on, and whether it is an outer pack, is read from its text, not from the engine. The vector
 * files are read with {@link Json}, the engine's core JSON reader, which is part of every build whatever its wires
 * (it is not the codec of the json wire). A build with one wire also prints
 * {@code "<wire> alone: N conversion vectors run, P passed, F failed"}. Exits non-zero on any failure.
 */
public final class ReducedCheck {
    private static final List<String> SPEC_WIRES = List.of("xml", "geojson", "json", "bits", "protobuf", "text", "tlv", "cbor");
    private static int failures = 0;

    private static void fail(String what, String why) {
        failures++;
        System.out.println("FAIL " + what + ": " + why);
    }

    /** The values of the first {@code format} and {@code wire} lines of a pack text; null for a missing one. */
    private static String[] head(String text) {
        String format = null, wire = null;
        for (String line : text.split("\r?\n", -1)) {
            List<String> tok;
            try {
                tok = Pack.tokenize(line, "-");
            } catch (GtException ex) {
                continue;
            }
            if (tok.size() != 2) continue;
            if (format == null && tok.get(0).equals("format")) format = tok.get(1);
            if (wire == null && tok.get(0).equals("wire")) wire = tok.get(1);
        }
        return new String[]{format, wire};
    }

    /** True when some line of the pack text is an {@code inner} line (engine-spec 0.34): an outer pack. */
    private static boolean outer(String text) {
        for (String line : text.split("\r?\n", -1)) {
            List<String> tok;
            try {
                tok = Pack.tokenize(line, "-");
            } catch (GtException ex) {
                continue;
            }
            if (!tok.isEmpty() && tok.get(0).equals("inner")) return true;
        }
        return false;
    }

    /** True when the wire value (null for none) is a wire of this build. */
    private static boolean inBuild(String wire) {
        return wire != null && Engine.wires().contains(wire);
    }

    /** True when the wire value is a wire of the specification this build lacks. */
    private static boolean lacking(String wire) {
        return wire != null && SPEC_WIRES.contains(wire) && !Engine.wires().contains(wire);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> object(Path f) throws IOException {
        Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
        return doc instanceof Map ? (Map<String, Object>) doc : null;
    }

    public static void main(String[] args) throws IOException {
        Path packsDir = Paths.get(args.length > 0 ? args[0] : "../../packs");
        List<String> built = Engine.wires();
        System.out.println("build wires: " + String.join(", ", built));

        // Every pack directory, with the format and wire its text names.
        TreeMap<String, String[]> packs = new TreeMap<>();   // directory name -> {format, wire, path, text}
        try (Stream<Path> s = Files.list(packsDir)) {
            for (Path d : (Iterable<Path>) s.sorted()::iterator) {
                Path def = d.resolve("pack.def");
                if (!Files.isRegularFile(def)) continue;
                String text = Files.readString(def, StandardCharsets.UTF_8);
                String[] h = head(text);
                packs.put(d.getFileName().toString(), new String[]{h[0], h[1], def.toString(), text});
            }
        }
        Map<String, String> wireOf = new LinkedHashMap<>();   // format -> wire, from the pack texts
        for (String[] p : packs.values()) if (p[0] != null) wireOf.putIfAbsent(p[0], p[1]);
        Set<String> outers = new HashSet<>();                 // formats of outer packs
        for (String[] p : packs.values()) if (p[0] != null && outer(p[3])) outers.add(p[0]);

        // One engine: every model module, every pack on a wire of the build.
        Engine engine = new Engine();
        for (String[] m : Engine.modelsInLoadOrder(Engine.defaultModelsDir(packsDir))) {
            try {
                engine.loadModel(m[1], m[0]);
            } catch (GtException ex) {
                fail("model " + Paths.get(m[0]).getFileName(), "does not load: " + ex.getMessage());
            }
        }
        // Every pack on a wire of the build loads; every pack on a wire the build lacks is refused, the wire named.
        int inSet = 0, otherPacks = 0, otherRefused = 0;
        Set<String> loaded = new HashSet<>();                 // formats that loaded
        for (Map.Entry<String, String[]> p : packs.entrySet()) {
            String wire = p.getValue()[1];
            if (inBuild(wire)) {
                inSet++;
                try {
                    loaded.add(engine.loadPack(p.getValue()[3], p.getValue()[2]).format);
                } catch (GtException ex) {
                    fail("pack " + p.getKey(), "does not load: " + ex.getMessage());
                }
            } else if (lacking(wire)) {
                otherPacks++;
                try {
                    engine.loadPack(p.getValue()[3], p.getValue()[2]);
                    fail("pack " + p.getKey() + " on " + wire, "loaded on a build without " + wire);
                } catch (GtException ex) {
                    String m = ex.getMessage();
                    if (!ex.kind().equals("unknown-wire") || !m.contains("\"" + wire + "\"")
                            || !m.contains("this build does not have it")) {
                        fail("pack " + p.getKey() + " on " + wire, "want unknown-wire naming \"" + wire
                                + "\" and saying this build does not have it, got " + m);
                    } else {
                        otherRefused++;
                    }
                }
            }
        }
        System.out.println("packs on other wires refused as unknown-wire, the wire named: " + otherRefused + "/" + otherPacks);

        // Conversion vectors whose from and to packs are both on wires of the build.
        int run = 0, passed = 0, skipped = 0, skippedOuter = 0;
        for (String dir : packs.keySet()) {
            Path vd = packsDir.resolve(dir).resolve("vectors");
            if (!Files.isDirectory(vd)) continue;
            List<Path> files = new ArrayList<>();
            try (Stream<Path> v = Files.list(vd)) {
                v.filter(p -> p.toString().endsWith(".json")).sorted().forEach(files::add);
            }
            for (Path f : files) {
                Map<String, Object> v;
                try {
                    v = object(f);
                } catch (RuntimeException ex) {
                    v = null;
                }
                Object from = v == null ? null : v.get("from"), to = v == null ? null : v.get("to");
                if (!(from instanceof String) || !(to instanceof String)
                        || !loaded.contains(from) || !loaded.contains(to)) {
                    skipped++;
                    continue;
                }
                if (outers.contains(from) || outers.contains(to)) {   // ruling 1 of 0.34
                    skippedOuter++;
                    continue;
                }
                run++;
                String why;
                try {
                    why = Vectors.runVector(engine, f);
                } catch (RuntimeException ex) {
                    why = ex.toString();
                }
                if (why == null) passed++;
                else fail(Vectors.label(packsDir, f), why);
            }
        }
        System.out.println("conversion vectors: " + passed + "/" + run + " passed (" + inSet + " packs on "
                + String.join(", ", built) + "; " + skipped + " vectors on other wires and " + skippedOuter
                + " vectors of outer packs not run)");
        if (run == 0) fail("conversion vectors", "none on the wires of the build");
        if (built.size() == 1) {
            System.out.println(built.get(0) + " alone: " + run + " conversion vectors run, " + passed + " passed, "
                    + (run - passed) + " failed");
        }

        // Capability vectors between formats on wires of the build (ruling 1e).
        int capRun = 0, capPassed = 0;
        for (Path f : jsonFiles(packsDir.resolve("conformance").resolve("capability-vectors"))) {
            Map<String, Object> v = object(f);
            if (v == null || !loaded.contains(v.get("from")) || !loaded.contains(v.get("to"))
                    || outers.contains(v.get("from")) || outers.contains(v.get("to"))) continue;
            capRun++;
            String why;
            try {
                why = Vectors.runCapabilityVector(engine, f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) capPassed++;
            else fail(Vectors.label(packsDir, f), why);
        }
        System.out.println("capability vectors: " + capPassed + "/" + capRun + " passed (those between formats on wires of the build)");

        // Load vectors none of whose packs is on a wire the build lacks (ruling 1b: the same named errors).
        int loadRun = 0, loadPassed = 0;
        for (Path f : jsonFiles(packsDir.resolve("conformance").resolve("load-vectors"))) {
            Map<String, Object> v = object(f);
            if (v == null) continue;
            List<Object> texts = new ArrayList<>();
            if (v.get("pack") instanceof String) texts.add(v.get("pack"));
            if (v.get("packs") instanceof List) texts.addAll((List<?>) v.get("packs"));
            boolean other = false;
            for (Object t : texts) {
                if (t instanceof String && (lacking(head((String) t)[1]) || outer((String) t))) other = true;
            }
            if (other) continue;
            loadRun++;
            String why;
            try {
                why = Vectors.runLoadVector(f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) loadPassed++;
            else fail(Vectors.label(packsDir, f), why);
        }
        System.out.println("load vectors: " + loadPassed + "/" + loadRun + " passed (those with no pack on a wire this build lacks and no outer pack)");

        // One pack on each wire of the specification the build lacks: unknown-wire, the wire named (ruling 1c).
        int lackingWires = 0, refused = 0;
        for (String wire : SPEC_WIRES) {
            if (built.contains(wire)) continue;
            lackingWires++;
            String dir = null;
            for (Map.Entry<String, String[]> p : packs.entrySet()) {
                if (wire.equals(p.getValue()[1])) {
                    dir = p.getKey();
                    break;
                }
            }
            if (dir == null) {
                fail("unknown-wire " + wire, "no pack on wire " + wire + " under " + packsDir);
                continue;
            }
            String what = "unknown-wire " + wire + " (pack " + dir + ")";
            try {
                Engine.loadOnly(packsDir, List.of(dir));
                fail(what, "the pack loaded");
                continue;
            } catch (GtException ex) {
                String m = ex.getMessage();
                if (!ex.kind().equals("unknown-wire") || !m.startsWith("unknown-wire:")) {
                    fail(what, "want unknown-wire, got " + m);
                    continue;
                }
                if (!m.contains("\"" + wire + "\"") || !m.contains("this build does not have it")) {
                    fail(what, "the message does not name the wire and say this build lacks it: " + m);
                    continue;
                }
                System.out.println("unknown-wire: " + wire + " (pack " + dir + "): " + m);
            }
            // ruling 1e: the format did not load, so it is unknown-format
            String format = packs.get(dir)[0];
            try {
                engine.convert(format, format, "");
                fail(what, "convert from " + format + " succeeded");
                continue;
            } catch (GtException ex) {
                if (!ex.kind().equals("unknown-format")) {
                    fail(what, "convert from " + format + ": want unknown-format, got " + ex.getMessage());
                    continue;
                }
            }
            refused++;
        }
        System.out.println("unknown-wire loads: " + refused + "/" + lackingWires + " passed");

        // A wire value that is no wire of the specification stays the plain unknown-wire.
        try {
            new Engine().loadPack("format nowire-check\nversion 1.0.0\nwire nowire\n", "nowire-check");
            fail("unknown-wire nowire", "the pack loaded");
        } catch (GtException ex) {
            if (!ex.kind().equals("unknown-wire") || ex.getMessage().contains("this build")) {
                fail("unknown-wire nowire", "want the plain unknown-wire, got " + ex.getMessage());
            } else {
                System.out.println("unknown-wire: nowire (no wire of the specification): " + ex.getMessage());
            }
        }

        System.out.println(failures == 0 ? "OK" : "FAILED (" + failures + ")");
        System.exit(failures == 0 ? 0 : 1);
    }

    private static List<Path> jsonFiles(Path dir) throws IOException {
        List<Path> out = new ArrayList<>();
        if (!Files.isDirectory(dir)) return out;
        try (Stream<Path> v = Files.list(dir)) {
            v.filter(p -> p.toString().endsWith(".json")).sorted().forEach(out::add);
        }
        return out;
    }
}
