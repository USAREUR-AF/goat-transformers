package goat.transformers;

import static goat.transformers.TestRunner.check;
import static goat.transformers.TestRunner.eq;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Version 0.25, ruling 1: what an engine keeps changes nothing observable, from one thread or several. */
final class ParseOnceTests {
    private ParseOnceTests() {}

    /** One conversion of a vector: its formats, input and context. */
    private static final class Conv {
        final String label, from, to, input;
        final Map<String, String> context;

        Conv(String label, String from, String to, String input, Map<String, String> context) {
            this.label = label;
            this.from = from;
            this.to = to;
            this.input = input;
            this.context = context;
        }

        /** The output, or the named error with its message: what ruling 1b compares. */
        String run(Engine e) {
            try {
                return "ok " + e.convert(from, to, input, context);
            } catch (GtException ex) {
                return "error " + ex.getMessage();
            }
        }
    }

    static void run(Engine shared, Path packsDir, List<Path> vectorFiles) {
        long t0 = System.nanoTime();
        loadReadsOnlyWhatItNeeds(packsDir);
        List<Conv> bench = benchSet(packsDir);
        freshAndUsed(shared, packsDir, bench);
        threads(shared, packsDir, vectorFiles, bench);
        System.out.println("parse once (0.25): " + (System.nanoTime() - t0) / 1_000_000 + " ms");
    }

    /** The vectors of bench/set.json beside the packs directory, empty when it is not there. */
    private static List<Conv> benchSet(Path packsDir) {
        Path set = packsDir.resolve("..").resolve("bench").resolve("set.json");
        List<Conv> out = new ArrayList<>();
        if (!Files.isRegularFile(set)) return out;
        try {
            Map<?, ?> s = (Map<?, ?>) Json.parse(Files.readString(set, StandardCharsets.UTF_8));
            for (Object p : (List<?>) s.get("vectors")) {
                Conv c = conv(packsDir.resolve("..").resolve((String) p));
                if (c != null) out.add(c);
            }
        } catch (IOException | RuntimeException ex) {
            check("parse once: bench/set.json reads", false, ex.toString());
        }
        return out;
    }

    /** The conversion of a vector file; null when it has no input or names a limit on list items. */
    private static Conv conv(Path f) throws IOException {
        Object doc = Json.parse(Files.readString(f, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) return null;
        Map<?, ?> v = (Map<?, ?>) doc;
        if (!(v.get("from") instanceof String) || !(v.get("to") instanceof String) || !(v.get("input") instanceof String)) return null;
        if (v.containsKey("max_items")) return null;   // an instance setting, not part of one conversion
        Map<String, String> context = null;
        if (v.get("context") instanceof Map) {
            context = new LinkedHashMap<>();
            for (Map.Entry<?, ?> c : ((Map<?, ?>) v.get("context")).entrySet()) {
                if (!(c.getValue() instanceof String)) return null;
                context.put((String) c.getKey(), (String) c.getValue());
            }
        }
        String label = f.getParent().getParent().getFileName() + "/" + f.getFileName();
        return new Conv(label, (String) v.get("from"), (String) v.get("to"), (String) v.get("input"), context);
    }

    /**
     * Ruling 1d: loadOnly reads the files of the modules it needs, not the whole directory. A module directory
     * with an unreadable file of a module no pack uses still loads; one whose module is in a file of another name
     * is read whole, as a directory loader reads it.
     */
    private static void loadReadsOnlyWhatItNeeds(Path packsDir) {
        Path models = Engine.defaultModelsDir(packsDir);
        Path dir = null;
        try {
            dir = Files.createTempDirectory("goat-parse-once");
            Files.copy(models.resolve("core.def"), dir.resolve("core.def"));
            Files.copy(models.resolve("track.def"), dir.resolve("track.def"));
            Files.copy(models.resolve("cot.def"), dir.resolve("cot.def"));
            Files.writeString(dir.resolve("unused.def"), "module unused\nkey \"broken\n", StandardCharsets.UTF_8);
            Engine e = Engine.loadOnly(packsDir, dir, Distribution.CONTROLLED, List.of("geojson", "cot-xml"));
            List<String> names = new ArrayList<>();
            for (ModelModule m : e.modules()) names.add(m.name);
            eq("parse once: loadOnly reads only the modules it needs", "[core, cot, track]", names.toString());
            Files.delete(dir.resolve("unused.def"));
            Files.move(dir.resolve("track.def"), dir.resolve("t-renamed.def"));
            e = Engine.loadOnly(packsDir, dir, Distribution.CONTROLLED, List.of("cot-xml"));
            names.clear();
            for (ModelModule m : e.modules()) names.add(m.name);
            eq("parse once: a module in a file of another name is found in the directory", "[core, cot, track]", names.toString());
            // the same pack named twice, by directory and by format, is one pack; named again in a second load it loads again
            Engine twice = Engine.loadOnly(packsDir, List.of("geojson", "geojson"));
            eq("parse once: a pack named twice loads once", 1, twice.packs().size());
            try {
                twice.loadPack(Files.readString(packsDir.resolve("geojson").resolve("pack.def"), StandardCharsets.UTF_8), "again");
                check("parse once: a second load of the same pack is duplicate-format", false, "it loaded");
            } catch (GtException ex) {
                eq("parse once: a second load of the same pack is duplicate-format", "duplicate-format", ex.kind());
            }
        } catch (IOException ex) {
            check("parse once: temporary module directory", false, ex.toString());
        } finally {
            if (dir != null) {
                try (java.util.stream.Stream<Path> s = Files.list(dir)) {
                    for (Path p : (Iterable<Path>) s::iterator) Files.delete(p);
                    Files.delete(dir);
                } catch (IOException ignored) {
                    // a temporary directory left behind changes no result
                }
            }
        }
    }

    /**
     * Ruling 1b: the bench set on a new instance that loaded only its packs gives the same results as on the same
     * instance after malformed inputs of every format failed, and as on the shared instance that ran every vector.
     */
    private static void freshAndUsed(Engine shared, Path packsDir, List<Conv> bench) {
        if (bench.isEmpty()) return;
        LinkedHashSet<String> formats = new LinkedHashSet<>();
        for (Conv c : bench) {
            formats.add(c.from);
            formats.add(c.to);
        }
        Engine fresh = Engine.loadOnly(packsDir, Engine.defaultModelsDir(packsDir), Distribution.CONTROLLED, formats, null, true);   // with inner packs (0.34)
        List<String> first = new ArrayList<>();
        for (Conv c : bench) first.add(c.run(fresh));
        // failures of every kind the decoders have: an empty input, a cut input, bytes that are no message
        for (Conv c : bench) {
            for (String bad : new String[]{"", c.input.substring(0, c.input.length() / 2), "\u0000ÿ{<", c.input + c.input}) {
                try {
                    fresh.convert(c.from, c.to, bad, c.context);
                } catch (GtException ex) {
                    // the failure is the point
                }
            }
        }
        for (int i = bench.size() - 1; i >= 0; i--) {
            Conv c = bench.get(i);
            eq("parse once: " + c.label + " after failed conversions, same result", first.get(i), c.run(fresh));
            eq("parse once: " + c.label + " on the instance that ran every vector, same result", first.get(i), c.run(shared));
        }
    }

    /**
     * Ruling 1c: eight threads convert, each in its own order, the conformance vectors and the bench set on the one
     * shared instance, twice; every result is the result of the same conversion run alone.
     */
    private static void threads(Engine shared, Path packsDir, List<Path> vectorFiles, List<Conv> bench) {
        List<Conv> convs = new ArrayList<>(bench);
        for (Path f : vectorFiles) {
            if (!f.getParent().getParent().getFileName().toString().startsWith("conformance")) continue;
            try {
                Conv c = conv(f);
                if (c != null) convs.add(c);
            } catch (IOException | RuntimeException ex) {
                // reported by the vector run
            }
        }
        List<String> alone = new ArrayList<>();
        for (Conv c : convs) alone.add(c.run(shared));
        int threads = 8, rounds = 2;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        List<Future<List<String>>> results = new ArrayList<>();
        java.util.concurrent.CountDownLatch start = new java.util.concurrent.CountDownLatch(1);
        for (int t = 0; t < threads; t++) {
            final long seed = 0x0025_0000L + t;
            results.add(pool.submit(() -> {
                List<Integer> order = new ArrayList<>();
                for (int i = 0; i < convs.size(); i++) order.add(i);
                List<String> bad = new ArrayList<>();
                start.await();
                for (int r = 0; r < rounds; r++) {
                    Collections.shuffle(order, new java.util.Random(seed * 31 + r));
                    for (int i : order) {
                        String got = convs.get(i).run(shared);
                        if (!got.equals(alone.get(i))) {
                            bad.add(convs.get(i).label + "\n    alone  " + alone.get(i) + "\n    thread " + got);
                        }
                    }
                }
                return bad;
            }));
        }
        start.countDown();
        List<String> bad = new ArrayList<>();
        try {
            for (Future<List<String>> f : results) bad.addAll(f.get());
        } catch (InterruptedException | java.util.concurrent.ExecutionException ex) {
            bad.add(ex.toString());
        } finally {
            pool.shutdownNow();
        }
        check("parse once: " + threads + " threads x " + rounds + " rounds x " + convs.size()
                + " conversions on one instance give the results of each run alone", bad.isEmpty(),
                bad.size() + " differ, first: " + (bad.isEmpty() ? "" : bad.get(0)));
        System.out.println("parse once: " + threads + " threads x " + rounds + " rounds x " + convs.size() + " conversions on one instance, "
                + bad.size() + " differ");
    }
}
