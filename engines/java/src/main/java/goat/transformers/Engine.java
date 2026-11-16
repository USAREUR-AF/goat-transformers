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
        List<Path> models = new ArrayList<>();
        try (Stream<Path> s = Files.list(modelsDir)) {
            s.filter(p -> p.getFileName().toString().endsWith(".def") && Files.isRegularFile(p)).forEach(models::add);
        } catch (IOException ex) {
            throw new UncheckedIOException("cannot list model modules in " + modelsDir, ex);
        }
        models.sort((a, b) -> Arrays.compareUnsigned(
                a.getFileName().toString().getBytes(StandardCharsets.UTF_8),
                b.getFileName().toString().getBytes(StandardCharsets.UTF_8)));
        // core.def is loaded first whatever its name sorts as (ruling 9 of 0.6): other modules derive from its keys.
        for (int i = 1; i < models.size(); i++) {
            if (models.get(i).getFileName().toString().equals("core.def")) models.add(0, models.remove(i));
        }
        for (Path def : models) {
            try {
                e.loadModel(Files.readString(def, StandardCharsets.UTF_8), def.toString());
            } catch (IOException ex) {
                throw new UncheckedIOException("cannot read " + def, ex);
            }
        }
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

    /** Load one model module from its text. */
    public ModelModule loadModel(String text) { return loadModel(text, "<model>"); }

    /** Load one model module from its text. {@code source} names the file for error messages. */
    public ModelModule loadModel(String text, String source) {
        ModelModule core = modules.get(ModelModule.CORE);
        ModelModule m = ModelModule.parse(text, source, core == null ? null : core.keys);
        if (!m.distribution.within(maxDistribution)) {
            throw new GtException(GtException.Code.DISTRIBUTION_REFUSED, null, null, source + ": module " + m.name + " is "
                    + m.distribution.token() + ", above this engine's limit " + maxDistribution.token());
        }
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
        // Every check has passed: read each default as its key's type, then bind fields to key types and tables.
        for (Pack.Kind k : p.kinds) readDefaults(k.scope, p.format);
        for (Pack.Scope body : p.bodies) readDefaults(body, p.format);
        for (Pack.Field f : p.fields) f.bind(keyType(f.key), f.via == null ? null : p.tables.get(f.via));
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
        Object v = Pack.read(text, type);
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
                    for (int i = 0; i < args.length && all; i++) {
                        args[i] = e.get(d.args.get(i));
                        if (args[i] == null) all = false;
                    }
                    if (!all) continue;
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
            throw new GtException(GtException.Code.BAD_PACK, p.format, null, "format loaded twice");
        }
        Codec<?> codec;
        switch (p.wire) {
            case XML: codec = new XmlCodec(p); break;
            case GEOJSON: codec = new GeoJsonCodec(p); break;
            case BITS: codec = new BitsCodec(p); break;
            case PROTOBUF: codec = new ProtobufCodec(p); break;
            case JSON: codec = new JsonCodec(p); break;
            default: throw new GtException(GtException.Code.BAD_PACK, p.format, null, "no codec for wire " + p.wire);
        }
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

    public Entity decode(String format, String text) { return codec(format).decode(text); }

    public String encode(String format, Entity e) { return codec(format).encode(e); }

    public String convert(String from, String to, String text) { return convert(from, to, text, null); }

    /**
     * Decode, clear the kind unless {@code from == to}, fill absent keys from {@code context} (model key to value
     * in string form; null for none), apply the derivations, encode. With {@code from == to} and no context the
     * two middle steps are skipped, so a same-format round trip stays byte-exact.
     */
    public String convert(String from, String to, String text, Map<String, String> context) {
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
