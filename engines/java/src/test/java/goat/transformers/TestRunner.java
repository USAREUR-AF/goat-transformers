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
            String label = Vectors.label(packsDir, f);
            String why;
            try {
                why = Vectors.runVector(engine, f);
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
                why = Vectors.runLoadVector(f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) loadPassed++;
            else fail(Vectors.label(packsDir, f), why);
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
                why = Vectors.runCapabilityVector(engine, f);
            } catch (RuntimeException ex) {
                why = ex.toString();
            }
            if (why == null) capPassed++;
            else fail(Vectors.label(packsDir, f), why);
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
