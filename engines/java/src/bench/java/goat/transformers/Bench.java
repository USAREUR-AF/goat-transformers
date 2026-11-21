package goat.transformers;

import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;

/**
 * The benchmark of spec 0.25, ruling 2. Usage: {@code Bench [SET]} (default {@code bench/set.json}).
 *
 * <p>The paths of the set's vectors are relative to the directory that holds the set's directory (the repository
 * root for {@code bench/set.json}); the packs are {@code <root>/packs} and the model modules {@code <root>/model}.
 * One instance loads the packs the vectors name in their {@code from} and {@code to} members, in order of first
 * appearance, with {@code core} and the modules their {@code uses} lines need ({@link Engine#loadOnly}), timed. Then
 * each vector is converted once and checked against its {@code expect}, then converted {@code iterations} times,
 * timed. Standard output holds the lines of ruling 2c and nothing else; any failure goes to standard error and exits 1.
 */
public final class Bench {
    private Bench() {}

    /** One vector of the set, read before the load. */
    private static final class Vector {
        final String path, from, to, input, expect;
        final Map<String, String> context;
        final Long maxItems;

        Vector(String path, String from, String to, String input, String expect, Map<String, String> context, Long maxItems) {
            this.path = path;
            this.from = from;
            this.to = to;
            this.input = input;
            this.expect = expect;
            this.context = context;
            this.maxItems = maxItems;
        }
    }

    private static final class Failure extends Exception {
        private static final long serialVersionUID = 1L;
        Failure(String message) { super(message); }
    }

    public static void main(String[] args) {
        PrintStream out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), false, StandardCharsets.UTF_8);
        int code;
        try {
            code = run(args, out);
        } catch (Failure | IOException | RuntimeException ex) {
            System.err.println("bench: " + ex.getMessage());
            code = 1;
        }
        out.flush();
        System.exit(code);
    }

    static int run(String[] args, PrintStream out) throws Failure, IOException {
        if (args.length > 1) {
            System.err.println("usage: Bench [SET]   (default bench/set.json)");
            return 2;
        }
        Path set = Paths.get(args.length == 1 ? args[0] : "bench/set.json").toAbsolutePath().normalize();
        Path setDir = set.getParent();
        Path root = setDir.getParent() == null ? setDir : setDir.getParent();
        Object doc = Json.parse(Files.readString(set, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) throw new Failure(set + " is not a JSON object");
        Map<?, ?> s = (Map<?, ?>) doc;
        long iterations = count(s.get("iterations"), "iterations");
        if (iterations < 1) throw new Failure("\"iterations\" is below 1");
        if (!(s.get("vectors") instanceof List)) throw new Failure("\"vectors\" is not an array");
        List<Vector> vectors = new ArrayList<>();
        LinkedHashSet<String> formats = new LinkedHashSet<>();
        for (Object p : (List<?>) s.get("vectors")) {
            if (!(p instanceof String)) throw new Failure("\"vectors\" holds an entry that is not a string");
            Vector v = vector((String) p, root.resolve((String) p));
            vectors.add(v);
            formats.add(v.from);
            formats.add(v.to);
        }

        long t0 = System.nanoTime();
        Engine engine = Engine.loadOnly(root.resolve("packs"), root.resolve("model"), Distribution.CONTROLLED, formats, null, true);   // with inner packs (0.34)
        long loadNs = System.nanoTime() - t0;
        long defaultMax = engine.maxItems();

        long sink = 0;
        for (Vector v : vectors) {
            engine.setMaxItems(v.maxItems != null ? v.maxItems : defaultMax);
            String got;
            try {
                got = engine.convert(v.from, v.to, v.input, v.context);
            } catch (GtException ex) {
                throw new Failure(v.path + ": convert failed: " + ex.getMessage());
            }
            if (!got.equals(v.expect)) {
                throw new Failure(v.path + ": output differs from expect\n  want " + v.expect + "\n  got  " + got);
            }
            long start = System.nanoTime();
            for (long i = 0; i < iterations; i++) sink += engine.convert(v.from, v.to, v.input, v.context).length();
            long ns = System.nanoTime() - start;
            out.println("{\"vector\": " + Json.write(v.path) + ", \"iterations\": " + iterations
                    + ", \"ns_per_op\": " + Long.divideUnsigned(ns, iterations) + "}");
        }
        engine.setMaxItems(defaultMax);
        out.println("{\"load\": " + engine.packs().size() + ", \"ns\": " + loadNs + "}");
        if (sink == Long.MIN_VALUE) System.err.println();   // keeps the conversions' results in use
        return 0;
    }

    private static Vector vector(String path, Path file) throws Failure, IOException {
        Object doc = Json.parse(Files.readString(file, StandardCharsets.UTF_8));
        if (!(doc instanceof Map)) throw new Failure(path + " is not a JSON object");
        Map<?, ?> v = (Map<?, ?>) doc;
        for (String k : new String[]{"from", "to", "input"}) {
            if (!(v.get(k) instanceof String)) throw new Failure(path + " lacks string \"" + k + "\"");
        }
        if (!(v.get("expect") instanceof String)) throw new Failure(path + " lacks string \"expect\"");
        Map<String, String> context = null;
        if (v.containsKey("context")) {
            if (!(v.get("context") instanceof Map)) throw new Failure(path + ": \"context\" is not an object");
            context = new LinkedHashMap<>();
            for (Map.Entry<?, ?> c : ((Map<?, ?>) v.get("context")).entrySet()) {
                if (!(c.getValue() instanceof String)) throw new Failure(path + ": context." + c.getKey() + " is not a string");
                context.put((String) c.getKey(), (String) c.getValue());
            }
        }
        Long maxItems = v.containsKey("max_items") ? count(v.get("max_items"), path + ": max_items") : null;
        return new Vector(path, (String) v.get("from"), (String) v.get("to"), (String) v.get("input"),
                (String) v.get("expect"), context, maxItems);
    }

    private static long count(Object o, String what) throws Failure {
        if (!(o instanceof Json.Num) || !((Json.Num) o).text.matches("\\d{1,18}")) {
            throw new Failure(what + " is not an integer of 0 or more");
        }
        return Long.parseLong(((Json.Num) o).text);
    }
}
