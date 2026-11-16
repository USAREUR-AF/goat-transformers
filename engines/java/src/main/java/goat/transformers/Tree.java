package goat.transformers;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.stream.Stream;

/**
 * Load a chosen set of packs from a tree: a directory holding {@code model/} and {@code packs/}, such as a checkout
 * of the library or a bundle written by {@code tools/goat-pkg bundle}.
 *
 * <pre>{@code
 * Engine engine = Tree.load(Path.of("vendor/goat"), List.of("cot-xml", "geojson"));
 * String geojson = engine.convert("cot-xml", "geojson", cotEvent);
 * }</pre>
 */
public final class Tree {
    private Tree() {}

    /** A new engine holding the named packs of the tree at {@code root}. See {@link #loadInto}. */
    public static Engine load(Path root, List<String> packs) {
        Engine e = new Engine();
        loadInto(e, root, packs);
        return e;
    }

    /**
     * Load the named packs from {@code <root>/packs/<name>/pack.def}, and before them the model modules they need
     * from {@code <root>/model/*.def}: {@code core}, every module a named pack {@code uses}, and every module one of
     * those {@code uses}, each after the modules it uses. Nothing else in the tree is loaded. A module the engine
     * already holds is not loaded again, so the call can be repeated with more packs. The engine's distribution
     * limit applies.
     */
    public static void loadInto(Engine engine, Path root, List<String> packs) {
        List<Pack> chosen = new ArrayList<>();
        for (String name : new LinkedHashSet<>(packs)) {
            Path def = root.resolve("packs").resolve(name).resolve("pack.def");
            if (!Files.isRegularFile(def)) {
                throw new GtException(GtException.Code.UNKNOWN_FORMAT, name, null, "no pack " + name + " under " + root.resolve("packs"));
            }
            chosen.add(Pack.parse(read(def), def.toString()));
        }
        // every module file of the tree by module name: {path, text} and the modules it uses
        Map<String, String[]> files = new TreeMap<>();
        Map<String, List<String>> uses = new TreeMap<>();
        Path modelDir = root.resolve("model");
        if (Files.isDirectory(modelDir)) {
            List<Path> defs = new ArrayList<>();
            try (Stream<Path> s = Files.list(modelDir)) {
                s.filter(p -> p.getFileName().toString().endsWith(".def") && Files.isRegularFile(p)).sorted().forEach(defs::add);
            } catch (IOException ex) {
                throw new UncheckedIOException("cannot list model modules in " + modelDir, ex);
            }
            for (Path def : defs) {
                String text = read(def);
                List<String> head = ModelModule.nameAndUses(text, def.toString());
                if (head.get(0) == null || files.containsKey(head.get(0))) continue;
                files.put(head.get(0), new String[]{def.toString(), text});
                uses.put(head.get(0), head.subList(1, head.size()));
            }
        }
        Set<String> loaded = new HashSet<>();
        for (ModelModule m : engine.modules()) loaded.add(m.name);
        Set<String> placing = new HashSet<>();
        place("core", engine, files, uses, loaded, placing);
        for (Pack p : chosen) {
            for (String u : p.uses) place(u, engine, files, uses, loaded, placing);
        }
        for (Pack p : chosen) engine.add(p);
    }

    private static void place(String name, Engine engine, Map<String, String[]> files, Map<String, List<String>> uses,
                              Set<String> loaded, Set<String> placing) {
        // a module no file declares is left to the pack's load, which reports unknown-module
        if (loaded.contains(name) || !files.containsKey(name)) return;
        if (!placing.add(name)) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, name, null,
                    files.get(name)[0] + ": the uses lines of the model modules form a cycle through module " + name);
        }
        for (String u : uses.get(name)) {
            if (!u.equals(name)) place(u, engine, files, uses, loaded, placing);
        }
        placing.remove(name);
        engine.loadModel(files.get(name)[1], files.get(name)[0]);
        loaded.add(name);
    }

    private static String read(Path p) {
        try {
            return Files.readString(p, StandardCharsets.UTF_8);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot read " + p, ex);
        }
    }
}
