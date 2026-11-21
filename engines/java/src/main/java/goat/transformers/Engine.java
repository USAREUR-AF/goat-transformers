package goat.transformers;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.stream.Stream;

/** Loads packs and runs decode / encode / convert. No format is compiled in. */
public final class Engine {
    private final TreeMap<String, Pack> packs = new TreeMap<>();
    private final TreeMap<String, Codec<?>> codecs = new TreeMap<>();
    /** Loaded modules in byte order of name: the order derivations are applied in. */
    private final TreeMap<String, ModelModule> modules = new TreeMap<>((a, b) -> Arrays.compareUnsigned(
            a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8)));
    /** The same modules by name, for the lookups of load checks. */
    private final HashMap<String, ModelModule> byName = new HashMap<>();
    private Distribution maxDistribution = Distribution.CONTROLLED;

    public Engine() {}

    /**
     * The wires this build has, in the order of the specification: all seven ({@code xml}, {@code geojson},
     * {@code json}, {@code bits}, {@code protobuf}, {@code text}, {@code tlv}) unless the jar was built with
     * {@code build.sh --wires} (spec 0.24). A pack on any other wire does not load: {@code unknown-wire}.
     */
    public static List<String> wires() { return Wires.NAMES; }

    /** The distribution limit: a module or pack marked above it is refused at load. {@code CONTROLLED} by default. */
    public Distribution maxDistribution() { return maxDistribution; }

    /** Set the distribution limit. It applies to every module and pack loaded afterwards. */
    public void setMaxDistribution(Distribution limit) {
        if (limit == null) throw new IllegalArgumentException("distribution limit is null");
        maxDistribution = limit;
    }

    /** Load {@code <packsDir>/../model/*.def}, then every {@code <packsDir>/<name>/pack.def}. */
    public static Engine load(Path packsDir) {
        return load(packsDir, defaultModelsDir(packsDir), Distribution.CONTROLLED);
    }

    /** The {@code model} directory beside {@code packsDir}. */
    public static Path defaultModelsDir(Path packsDir) { return packsDir.resolve("..").resolve("model"); }

    /**
     * Load every {@code <modelsDir>/*.def} in byte order of file name, then every {@code <packsDir>/<name>/pack.def},
     * under the distribution limit {@code limit}.
     */
    public static Engine load(Path packsDir, Path modelsDir, Distribution limit) {
        Engine e = new Engine();
        e.setMaxDistribution(limit);
        for (String[] m : modelsInLoadOrder(modelsDir)) e.loadModel(m[1], m[0]);
        List<Path> defs = new ArrayList<>();
        try (Stream<Path> s = Files.list(packsDir)) {
            s.sorted().forEach(d -> {
                Path def = d.resolve("pack.def");
                if (Files.isRegularFile(def)) defs.add(def);
            });
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot list packs in " + packsDir, ex);
        }
        for (Path def : defs) {
            try {
                e.loadPack(Files.readString(def, StandardCharsets.UTF_8), def.toString());
            } catch (IOException ex) {
                throw new UncheckedIOException("cannot read " + def, ex);
            }
        }
        return e;
    }

    /** As {@link #loadOnly(Path, Path, Distribution, Collection)}, with the {@code model} directory beside {@code packsDir} and the default limit. */
    public static Engine loadOnly(Path packsDir, Collection<String> names) {
        return loadOnly(packsDir, defaultModelsDir(packsDir), Distribution.CONTROLLED, names);
    }

    /**
     * Load only the named packs of {@code packsDir}, with the model modules they need: {@code core}, the modules
     * their {@code uses} lines name, and the modules those use in turn. A name is the pack's directory name, or
     * the format of a pack in the directory. A name that is neither is {@code unknown-format}; a module no file
     * of {@code modelsDir} declares is left to the pack's load, which reports {@code unknown-module}.
     */
    public static Engine loadOnly(Path packsDir, Path modelsDir, Distribution limit, Collection<String> names) {
        Map<String, Path> byFormat = null;
        List<String[]> packs = new ArrayList<>();   // {path, text}, in the order named, each once
        List<String> seen = new ArrayList<>();
        java.util.LinkedHashSet<String> needed = new java.util.LinkedHashSet<>();
        needed.add(ModelModule.CORE);
        for (String name : names) {
            Path def = name.isEmpty() || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0 || name.startsWith(".")
                    ? null : packsDir.resolve(name).resolve("pack.def");
            if (def == null || !Files.isRegularFile(def)) {
                if (byFormat == null) byFormat = packFormats(packsDir);
                def = byFormat.get(name);
            }
            if (def == null) {
                throw new GtException(GtException.Code.UNKNOWN_FORMAT, name, null, "no pack named " + name + " in " + packsDir);
            }
            if (seen.contains(def.toString())) continue;
            seen.add(def.toString());
            String text = read(def);
            packs.add(new String[]{def.toString(), text});
            needed.addAll(headValues(text, def.toString(), "uses"));
        }
        Engine e = new Engine();
        e.setMaxDistribution(limit);
        if (Files.isDirectory(modelsDir)) {
            List<String[]> models = modelsInLoadOrder(modelsDir);
            Map<String, List<String>> usesOf = new HashMap<>();
            List<String> moduleOf = new ArrayList<>();
            for (String[] m : models) {
                List<String> head = ModelModule.nameAndUses(m[1], m[0]);
                moduleOf.add(head.get(0));
                if (head.get(0) != null) usesOf.putIfAbsent(head.get(0), head.subList(1, head.size()));
            }
            List<String> queue = new ArrayList<>(needed);
            for (int i = 0; i < queue.size(); i++) {
                for (String u : usesOf.getOrDefault(queue.get(i), Collections.emptyList())) {
                    if (needed.add(u)) queue.add(u);
                }
            }
            for (int i = 0; i < models.size(); i++) {
                if (moduleOf.get(i) != null && needed.contains(moduleOf.get(i))) e.loadModel(models.get(i)[1], models.get(i)[0]);
            }
        }
        for (String[] p : packs) e.loadPack(p[1], p[0]);
        return e;
    }

    private static String read(Path file) {
        try {
            return Files.readString(file, StandardCharsets.UTF_8);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot read " + file, ex);
        }
    }

    /** The single arguments of the {@code kw} lines of a pack text, read without checking anything else. */
    private static List<String> headValues(String text, String source, String kw) {
        List<String> out = new ArrayList<>();
        String[] lines = text.split("\r?\n", -1);
        for (int i = 0; i < lines.length; i++) {
            List<String> tok;
            try {
                tok = Pack.tokenize(lines[i], source + ":" + (i + 1));
            } catch (GtException ex) {
                continue;   // reported with its line when the pack is loaded
            }
            if (tok.size() == 2 && tok.get(0).equals(kw)) out.add(tok.get(1));
        }
        return out;
    }

    /** The {@code pack.def} of each format under {@code packsDir}; the first in byte order of path wins a repeated format. */
    private static Map<String, Path> packFormats(Path packsDir) {
        Map<String, Path> out = new HashMap<>();
        List<Path> dirs = new ArrayList<>();
        try (Stream<Path> s = Files.list(packsDir)) {
            s.sorted().forEach(dirs::add);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot list packs in " + packsDir, ex);
        }
        for (Path d : dirs) {
            Path def = d.resolve("pack.def");
            if (!Files.isRegularFile(def)) continue;
            List<String> f = headValues(read(def), def.toString(), "format");
            if (!f.isEmpty()) out.putIfAbsent(f.get(0), def);
        }
        return out;
    }

    /**
     * The module files of {@code modelsDir} as {@code {path, text}}, in the order a directory loader loads them:
     * {@code core.def} first, then byte order of file name, each module after the modules its {@code uses} lines
     * name. A cycle of {@code uses} lines is {@code bad-directive}.
     */
    public static List<String[]> modelsInLoadOrder(Path modelsDir) {
        List<Path> files = new ArrayList<>();
        try (Stream<Path> s = Files.list(modelsDir)) {
            s.filter(p -> p.getFileName().toString().endsWith(".def") && Files.isRegularFile(p)).forEach(files::add);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot list model modules in " + modelsDir, ex);
        }
        files.sort((a, b) -> Arrays.compareUnsigned(
                a.getFileName().toString().getBytes(StandardCharsets.UTF_8),
                b.getFileName().toString().getBytes(StandardCharsets.UTF_8)));
        // core.def is loaded first whatever its name sorts as (ruling 9 of 0.6): other modules derive from its keys.
        for (int i = 1; i < files.size(); i++) {
            if (files.get(i).getFileName().toString().equals("core.def")) files.add(0, files.remove(i));
        }
        List<String[]> texts = new ArrayList<>();
        List<List<String>> heads = new ArrayList<>();
        Map<String, Integer> byModule = new HashMap<>();
        for (Path def : files) {
            String text;
            try {
                text = Files.readString(def, StandardCharsets.UTF_8);
            } catch (IOException ex) {
                throw new UncheckedIOException("cannot read " + def, ex);
            }
            List<String> head = ModelModule.nameAndUses(text, def.toString());
            if (head.get(0) != null) byModule.putIfAbsent(head.get(0), texts.size());
            texts.add(new String[]{def.toString(), text});
            heads.add(head);
        }
        List<String[]> out = new ArrayList<>();
        int[] state = new int[texts.size()];   // 0 not visited, 1 being placed, 2 placed
        for (int i = 0; i < texts.size(); i++) placeModel(i, texts, heads, byModule, state, out);
        return out;
    }

    private static void placeModel(int i, List<String[]> texts, List<List<String>> heads, Map<String, Integer> byModule,
                                   int[] state, List<String[]> out) {
        if (state[i] == 2) return;
        if (state[i] == 1) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, heads.get(i).get(0), null,
                    texts.get(i)[0] + ": the uses lines of the model modules form a cycle through module " + heads.get(i).get(0));
        }
        state[i] = 1;
        List<String> head = heads.get(i);
        for (int u = 1; u < head.size(); u++) {
            Integer j = byModule.get(head.get(u));
            // a module no file declares is left to load_model, which reports unknown-module
            if (j != null) placeModel(j, texts, heads, byModule, state, out);
        }
        state[i] = 2;
        out.add(texts.get(i));
    }

    /** Load one model module from its text. */
    public ModelModule loadModel(String text) { return loadModel(text, "<model>"); }

    /** Load one model module from its text. {@code source} names the file for error messages. */
    public ModelModule loadModel(String text, String source) {
        ModelModule m = ModelModule.parse(text, source, byName, maxDistribution);
        if (modules.containsKey(m.name)) {
            throw new GtException(GtException.Code.DUPLICATE_MODULE, null, null, source + ": module " + m.name + " loaded twice");
        }
        modules.put(m.name, m);
        byName.put(m.name, m);
        return m;
    }

    public Collection<ModelModule> modules() { return Collections.unmodifiableCollection(modules.values()); }

    /** Parse pack text and load it against the modules loaded so far. */
    public Pack loadPack(String text, String source) {
        Pack p = Pack.parse(text, source);
        add(p);
        return p;
    }

    /**
     * Check a parsed pack against the loaded modules, in the specification's order: distribution-refused,
     * unknown-module, distribution-violation, module-not-used, undeclared-key, key-type-mismatch.
     */
    private void checkAgainstModel(Pack p) {
        if (!p.distribution.within(maxDistribution)) {
            throw new GtException(GtException.Code.DISTRIBUTION_REFUSED, p.format, null, "pack is "
                    + p.distribution.token() + ", above this engine's limit " + maxDistribution.token());
        }
        List<String> used = new ArrayList<>();
        used.add(ModelModule.CORE);
        for (String u : p.uses) if (!used.contains(u)) used.add(u);
        for (String u : used) {
            if (!modules.containsKey(u)) {
                throw new GtException(GtException.Code.UNKNOWN_MODULE, p.format, null, "module " + u + " is not loaded");
            }
        }
        if (p.distribution == Distribution.PUBLIC) {
            for (String u : used) {
                if (modules.get(u).distribution != Distribution.PUBLIC) {
                    throw new GtException(GtException.Code.DISTRIBUTION_VIOLATION, p.format, null,
                            "a public pack uses " + modules.get(u).distribution.token() + " module " + u);
                }
            }
        }
        // Mapped keys and `requires` keys alike, in file order.
        for (String[] ref : p.keyRefs) {
            String module = ModelModule.moduleOf(ref[0]);
            if (!used.contains(module)) {
                throw new GtException(GtException.Code.MODULE_NOT_USED, p.format, ref[1],
                        "model key " + ref[0] + " is of module " + module + ", which no uses line names");
            }
        }
        for (String[] ref : p.keyRefs) {
            String module = ModelModule.moduleOf(ref[0]);
            ModelModule m = byName.get(module);
            if (!m.keys.containsKey(ModelModule.keyOf(ref[0])) && !m.lists.contains(ModelModule.keyOf(ref[0]))) {
                throw new GtException(GtException.Code.UNDECLARED_KEY, p.format, ref[1],
                        "module " + module + " declares no key " + ModelModule.keyOf(ref[0]) + " (model key " + ref[0] + ")");
            }
        }
        // A list key with `=` in a requires term (ruling 19 of 0.20: after undeclared-key over every line).
        for (Pack.ValueList vl : p.valueLists) {
            if (!vl.isCase() && isList(vl.key)) {
                throw new GtException(GtException.Code.BAD_DIRECTIVE, p.format, null,
                        vl.where + ": requires " + vl.key + "= names a list; a list takes no value");
            }
        }
        for (Pack.Line l : p.typed) {
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                if (!isList(g.list)) {
                    throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, p.format, g.locator, "group names "
                            + g.list + ", which is a " + keyType(g.list) + " key, not a list");
                }
                continue;
            }
            Pack.Field f = (Pack.Field) l;
            String declared = keyType(f.key);
            if (declared == null) {
                throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, p.format, f.locator, "field names "
                        + f.key + ", which is a list, not a key");
            }
            if (f.via != null) {
                // With a value table the key's type is compared with the type of the table's model side; an
                // all-integer table on a float key is accepted and its model side read as float (ruling 4 of 0.6).
                String model = p.tableType(f.via);
                if (!declared.equals(model) && !(declared.equals("float") && model.equals("int"))) {
                    throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, p.format, f.locator, "model key " + f.key
                            + " is declared " + declared + " but the model side of table " + f.via + " is " + model);
                }
            } else if (!declared.equals(f.yields())) {
                throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, p.format, f.locator, "model key " + f.key
                        + " is declared " + declared + " but transform " + f.transformName() + " yields " + f.yields());
            }
        }
        // engine-spec 0.56: the bounds of range read as the key's type (int text for an int key, <min> < <max>)
        for (Pack.Field f : p.fields) {
            if (f.out.min == null) continue;
            String declared = keyType(f.key);
            f.range = OutputOptions.Range.of(f.out.min, f.out.max, f.out.wrap, declared == null ? "list" : declared,
                    p.format, f.locator, "line " + f.line);
        }
        // Every check has passed: read each default as its key's type, then bind fields to key types and tables.
        for (Pack.Kind k : p.kinds) readDefaults(k.scope, p.format);
        for (Pack.Scope body : p.bodies) readDefaults(body, p.format);
        // The requires = and case values, in line order: type, then duplicates (rulings 1, 17, 18 and 19 of 0.20).
        for (Pack.ValueList vl : p.valueLists) readValueList(vl, p.format);
        for (Pack.Field f : p.fields) f.bind(keyType(f.key), f.via == null ? null : p.tables.get(f.via));
    }

    /** Read a requires = or case value list as its key's declared type, into canonical texts. */
    private void readValueList(Pack.ValueList vl, String format) {
        String type = keyType(vl.key);
        java.util.LinkedHashSet<String> canon = new java.util.LinkedHashSet<>();
        String[] texts = new String[vl.values.length];
        for (int i = 0; i < vl.values.length; i++) {
            String v = vl.values[i];
            Object o;
            if (type.equals("int")) {
                // an optional `-` then digits: `+1` and `1.0` are not int values (ruling 17)
                o = v.matches("-?\\d+") ? Pack.read(v, "int") : Pack.UNREADABLE;
            } else if (type.equals("float")) {
                // -?digits[.digits] with an optional exponent, as a JSON number (ruling 24)
                o = v.matches("-?\\d+(\\.\\d+)?([eE][+-]?\\d+)?") ? Pack.read(v, "float") : Pack.UNREADABLE;
            } else {
                o = Pack.read(v, type);
            }
            if (o == Pack.UNREADABLE) {
                throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, format, null, vl.where + ": "
                        + (vl.isCase() ? "case" : "requires") + " value \"" + v + "\" is not a " + type + " value of " + vl.key);
            }
            texts[i] = Pack.canonText(o);
        }
        for (String t : texts) {
            if (!canon.add(t) && vl.isCase()) {
                throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, vl.where + ": case value " + t + " is listed twice");
            }
            if (vl.isCase()) {
                for (Pack.ValueList other : vl.earlierCases) {
                    if (other.canon != null && other.canon.contains(t)) {
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, vl.where + ": case value " + t
                                + " is also listed by the case of line " + other.line);
                    }
                }
            }
        }
        vl.canon = canon;
    }

    private void readDefaults(Pack.Scope scope, String format) {
        if (scope.defaults.isEmpty()) return;
        Map<String, Object> values = new HashMap<>();
        for (Map.Entry<String, String> d : scope.defaults.entrySet()) {
            values.put(d.getKey(), readAs(d.getKey(), d.getValue(), format, "default"));
        }
        scope.defaultValues = values;
    }

    /** True when a loaded module declares {@code name} as a list. */
    public boolean isList(String name) {
        ModelModule m = byName.get(ModelModule.moduleOf(name));
        return m != null && m.lists.contains(ModelModule.keyOf(name));
    }

    /** The declared type of a model key, or null when no loaded module declares it. */
    public String keyType(String key) {
        ModelModule m = byName.get(ModelModule.moduleOf(key));
        return m == null ? null : m.keys.get(ModelModule.keyOf(key));
    }

    /** A value in string form read as its key's declared type: undeclared-key, or key-type-mismatch when it cannot be. */
    private Object readAs(String key, String text, String format, String what) {
        String type = keyType(key);
        if (type == null && isList(key)) {
            throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, format, null, what + " key " + key + " is a list, not a key");
        }
        if (type == null) {
            throw new GtException(GtException.Code.UNDECLARED_KEY, format, null, what + " key " + key + " is declared by no loaded module");
        }
        // a context value comes from the caller and is trimmed; a default is read as written (ruling 18 of 0.18)
        Object v = what.equals("context") ? Pack.readTrimmed(text, type) : Pack.read(text, type);
        if (v == Pack.UNREADABLE) {
            throw new GtException(GtException.Code.KEY_TYPE_MISMATCH, format, null,
                    what + " key " + key + " is declared " + type + " and \"" + text + "\" is not one");
        }
        return v;
    }

    /**
     * Apply the derivations of the loaded modules to the entity: modules in byte order of name, each module's
     * {@code derive} lines in order; a line whose target is absent and whose arguments are all present sets the
     * target. The pass repeats until one sets nothing, at most 8 times.
     */
    public Entity complete(Entity e) { return complete(e, null); }

    /** Fill the keys the entity lacks from {@code context} (values in string form), then apply the derivations. */
    public Entity complete(Entity e, Map<String, String> context) {
        if (context != null) {
            Map<String, Object> typed = new LinkedHashMap<>();
            for (Map.Entry<String, String> c : context.entrySet()) {
                typed.put(c.getKey(), readAs(c.getKey(), c.getValue(), null, "context"));
            }
            for (Map.Entry<String, Object> c : typed.entrySet()) {
                if (e.get(c.getKey()) == null) e.put(c.getKey(), c.getValue());
            }
        }
        for (int pass = 0; pass < 8; pass++) {
            boolean set = false;
            for (ModelModule m : modules.values()) {
                for (ModelModule.Derive d : m.derives) {
                    if (e.get(d.target) != null) continue;
                    Object[] args = new Object[d.args.size()];
                    boolean all = true;
                    int present = 0;
                    for (int i = 0; i < args.length; i++) {
                        Object a = e.get(d.args.get(i));
                        if (a == null) all = false;
                        else args[present++] = a;
                    }
                    if (d.fn == ModelModule.Derive.Fn.TOKENS) {
                        // set when only some arguments are present (ruling 7 of 0.18): each keeps its token's place
                        if (present == 0) continue;
                        for (int i = 0; i < args.length; i++) args[i] = e.get(d.args.get(i));
                    } else if (d.fn == ModelModule.Derive.Fn.ANY) {
                        // the one function whose target is set when only some arguments are present
                        if (present == 0) continue;
                        args = Arrays.copyOf(args, present);
                    } else if (!all) {
                        continue;
                    }
                    Object v;
                    try {
                        v = d.apply(args);
                    } catch (IllegalArgumentException ex) {
                        continue;   // a value that is not of the key's declared type derives nothing
                    }
                    if (v == null) continue;
                    e.put(d.target, v);
                    set = true;
                }
            }
            if (!set) break;
        }
        return e;
    }

    /** Load a parsed pack: check it against the modules loaded so far, then register its codec. */
    public void add(Pack p) {
        checkAgainstModel(p);
        if (packs.containsKey(p.format)) {
            throw new GtException(GtException.Code.DUPLICATE_FORMAT, p.format, null, "a pack with format " + p.format + " is already loaded");
        }
        // the codec of the pack's wire: the build has it, or Pack.parse refused the pack (ruling 1c of 0.24)
        Codec<?> codec = Wires.codec(p);
        packs.put(p.format, p);
        codecs.put(p.format, codec);
    }

    public Collection<Pack> packs() { return Collections.unmodifiableCollection(packs.values()); }

    private Codec<?> codec(String format) {
        Codec<?> c = codecs.get(format);
        if (c == null) throw new GtException(GtException.Code.UNKNOWN_FORMAT, format, null, "no pack loaded for format " + format);
        return c;
    }

    /**
     * The union of model keys the format maps, over its common lines and every kind, in first appearance order;
     * a list as {@code <list>[]} and each key of its items as {@code <list>[].<key>}.
     */
    public List<String> modelKeys(String format) {
        codec(format);
        return packs.get(format).modelKeys();
    }

    public Entity decode(String format, String text) { return codec(format).decode(text, maxItems); }

    private long maxItems = Codec.DEFAULT_MAX_ITEMS;

    /** The limit on list items of one decode (ruling 7 of 0.11): 100,000 unless set. */
    public long maxItems() { return maxItems; }

    /** Set the limit on list items of one decode, counted over every list at every level; 0 refuses any item. */
    public void setMaxItems(long limit) {
        if (limit < 0) throw new IllegalArgumentException("the limit on list items is negative: " + limit);
        maxItems = limit;
    }

    /** The capability report of one ordered pair of formats (ruling 6 of 0.11). */
    public static final class Capability {
        /** {@code full}, {@code partial} or {@code none}. */
        public final String grade;
        /** The entries of {@code model_keys(from)} that {@code model_keys(to)} also has, in the order of the first. */
        public final List<String> carried;
        /** The other entries of {@code model_keys(from)}, in its order. */
        public final List<String> dropped;

        Capability(String grade, List<String> carried, List<String> dropped) {
            this.grade = grade;
            this.carried = Collections.unmodifiableList(carried);
            this.dropped = Collections.unmodifiableList(dropped);
        }
    }

    /** {@code capability(from, to)}, computed from the two packs alone; a format not loaded is {@code unknown-format}. */
    public Capability capability(String from, String to) {
        List<String> source = modelKeys(from);
        java.util.Set<String> target = new java.util.HashSet<>(modelKeys(to));
        List<String> carried = new ArrayList<>(), dropped = new ArrayList<>();
        for (String k : source) (target.contains(k) ? carried : dropped).add(k);
        String grade = carried.isEmpty() ? "none" : dropped.isEmpty() ? "full" : "partial";
        return new Capability(grade, carried, dropped);
    }

    public String encode(String format, Entity e) { return codec(format).encode(e); }

    public String convert(String from, String to, String text) { return convert(from, to, text, null); }

    /**
     * Decode, clear the kind unless {@code from == to}, fill absent keys from {@code context} (model key to value
     * in string form; null for none), apply the derivations, encode. With {@code from == to} and no context the
     * two middle steps are skipped, so a same-format round trip stays byte-exact.
     */
    public String convert(String from, String to, String text, Map<String, String> context) {
        codec(from);   // from, then to, before the input is read (ruling 5 of 0.11)
        Codec<?> target = codec(to);
        Entity e = decode(from, text);
        if (!from.equals(to)) e.clearKind();
        if (context != null || !from.equals(to)) complete(e, context);
        return target.encode(e);
    }

    public Entity decode(String format, byte[] bytes) { return decode(format, new String(bytes, StandardCharsets.UTF_8)); }

    public byte[] encodeBytes(String format, Entity e) { return encode(format, e).getBytes(StandardCharsets.UTF_8); }

    public byte[] convert(String from, String to, byte[] bytes) {
        return convert(from, to, new String(bytes, StandardCharsets.UTF_8)).getBytes(StandardCharsets.UTF_8);
    }
}
