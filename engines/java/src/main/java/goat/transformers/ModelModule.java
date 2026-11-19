package goat.transformers;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** A parsed {@code model/<module>.def}: a named list of typed keys with a distribution marking. */
public final class ModelModule {
    /** The module whose keys a pack writes bare. */
    public static final String CORE = "core";

    public final String name;
    public final String version;
    public final Distribution distribution;
    public final List<String> sources;
    /** key name to declared type ({@code string}, {@code float} or {@code int}), in file order. */
    public final Map<String, String> keys;
    /** The {@code derive} lines, in file order. */
    public final List<Derive> derives;
    /** The names of the module's lists, in file order. A list shares the key namespace of its module. */
    public final Set<String> lists;
    /** The modules named in {@code uses} lines, in file order: their keys may be arguments of {@code derive} lines. */
    public final List<String> uses;

    /** One {@code derive} line: the target key follows from the argument keys through a function of the fixed set. */
    public static final class Derive {
        enum Fn {
            COPY, HYPOT, BEARING, EAST_OF, NORTH_OF, NEG, SCALE, OFFSET, JOIN, DAY_SECONDS, ANY, NOT, PARSE_INT, TEXT_OF,
            // engine-spec 0.12
            PRESENT,
            // engine-spec 0.16
            SEC_OF, NSEC_OF, MS_OF, DEG, RAD, ADD, SUB, DEG_LAT_OF, DEG_LON_OF, M_LAT_OF, M_LON_OF,
            ECEF_X, ECEF_Y, ECEF_Z, LAT_OF_ECEF, LON_OF_ECEF, HAE_OF_ECEF
        }

        /** Target and argument keys as a pack writes them: bare for {@code core}, {@code <module>.<key>} otherwise. */
        public final String target;
        public final List<String> args;
        /** The function as written, with its parameter. */
        public final String function;
        final Fn fn;
        final String type;       // the target's declared type
        double factor;           // scale: decimal factor
        boolean fraction;        // scale: the factor is num/den
        double num;
        double den;
        double addFloat;         // offset on floats
        long addInt;             // offset on ints
        String sep;              // join

        Derive(String target, List<String> args, String function, Fn fn, String type) {
            this.target = target;
            this.args = Collections.unmodifiableList(args);
            this.function = function;
            this.fn = fn;
            this.type = type;
        }

        /** WGS 84 and Heikkinen's closed form, in the order engine-spec 0.16 states it. */
        static final class Wgs84 {
            static final double A = 6378137.0;
            static final double F = 1.0 / 298.257223563;
            static final double E2 = F * (2.0 - F);
            static final double B = A * (1.0 - F);

            private static boolean bad(double d) { return !Double.isFinite(d); }

            /** {φ in radians, h}, or null when an intermediate is not finite or {@code G ≤ 0} (rulings 1, 2). */
            static double[] geodetic(double x, double y, double z) {
                double a2 = A * A, b2 = B * B, e4 = E2 * E2;
                double p = Math.sqrt(x * x + y * y);
                double f = 54.0 * b2 * z * z;
                double g = p * p + (1.0 - E2) * z * z - E2 * (a2 - b2);
                if (bad(p) || bad(f) || bad(g) || g <= 0) return null;
                double c = e4 * f * p * p / (g * g * g);
                double s = Math.cbrt(1.0 + c + Math.sqrt(c * c + 2.0 * c));
                double k = s + 1.0 + 1.0 / s;
                double pp = f / (3.0 * k * k * g * g);
                double q = Math.sqrt(1.0 + 2.0 * e4 * pp);
                if (bad(c) || bad(s) || bad(k) || bad(pp) || bad(q)) return null;
                double inner = a2 / 2.0 * (1.0 + 1.0 / q) - pp * (1.0 - E2) * z * z / (q * (1.0 + q)) - pp * p * p / 2.0;
                if (bad(inner)) return null;
                if (inner < 0) inner = 0;   // ruling 9 of 0.16
                double r0 = -pp * E2 * p / (1.0 + q) + Math.sqrt(inner);
                double d = p - E2 * r0;
                double u = Math.sqrt(d * d + z * z);
                double v = Math.sqrt(d * d + (1.0 - E2) * z * z);
                double z0 = b2 * z / (A * v);
                double h = u * (1.0 - b2 / (A * v));
                double phi = Math.atan2(z + (a2 - b2) / b2 * z0, p);
                if (bad(r0) || bad(u) || bad(v) || bad(z0) || bad(h) || bad(phi)) return null;
                return new double[] {phi, h};
            }
        }

        private static final double DEG = Math.PI / 180.0;
        private static final double RAD = 180.0 / Math.PI;

        private static final java.util.regex.Pattern DECIMAL_INTEGER = java.util.regex.Pattern.compile("-?[0-9]+");

        /**
         * The target's value from the argument values, or null when the result is absent (not finite, or no bearing).
         * {@code any} takes the arguments that are present, at least one; every other function takes them all.
         */
        Object apply(Object[] v) {
            double r;
            switch (fn) {
                case COPY:
                    return v[0];
                case DAY_SECONDS:
                    return Math.floorMod(Transform.asLong(v[0]), 86_400_000L) / 1000.0;
                case ANY: {
                    for (Object a : v) if (Transform.asLong(a) != 0) return 1L;
                    return 0L;
                }
                case NOT:
                    return Transform.asLong(v[0]) == 0 ? 1L : 0L;
                case PRESENT:
                    return 1L;   // presence, not value (ruling 1 of 0.12)
                case PARSE_INT: {
                    String t = String.valueOf(v[0]);
                    if (!DECIMAL_INTEGER.matcher(t).matches()) return null;
                    try {
                        return Long.parseLong(t);
                    } catch (NumberFormatException ex) {
                        return null;   // beyond 64 bits: not an integer the model holds
                    }
                }
                case TEXT_OF:
                    return Long.toString(Transform.asLong(v[0]));
                case JOIN: {
                    StringBuilder b = new StringBuilder();
                    for (int i = 0; i < v.length; i++) {
                        if (i > 0) b.append(sep);
                        b.append(Pack.canonText(v[i]));
                    }
                    return b.toString();
                }
                case OFFSET:
                    if (type.equals("int")) {
                        try {
                            return Math.addExact(Transform.asLong(v[0]), addInt);
                        } catch (ArithmeticException ex) {
                            return null;
                        }
                    }
                    r = Transform.asDouble(v[0]) + addFloat;
                    break;
                case HYPOT: {
                    double a = Transform.asDouble(v[0]), b = Transform.asDouble(v[1]);
                    r = Math.sqrt(a * a + b * b);
                    break;
                }
                case BEARING: {
                    double east = Transform.asDouble(v[0]), north = Transform.asDouble(v[1]);
                    if (east == 0 && north == 0) return null;
                    r = Math.atan2(east, north) * RAD;   // 180/π, the quotient computed first (ruling 1 of 0.6)
                    if (r < 0) r += 360.0;
                    if (r >= 360.0) r -= 360.0;
                    break;
                }
                case EAST_OF:
                    r = Transform.asDouble(v[0]) * Math.sin(Transform.asDouble(v[1]) * DEG);
                    break;
                case NORTH_OF:
                    r = Transform.asDouble(v[0]) * Math.cos(Transform.asDouble(v[1]) * DEG);
                    break;
                case NEG:
                    r = -Transform.asDouble(v[0]);
                    break;
                case SCALE:
                    r = fraction ? Transform.asDouble(v[0]) * num / den : Transform.asDouble(v[0]) * factor;
                    break;
                case SEC_OF:
                    return Math.floorDiv(Transform.asLong(v[0]), 1000L);
                case NSEC_OF:
                    return Math.floorMod(Transform.asLong(v[0]), 1000L) * 1_000_000L;
                case MS_OF: {
                    // exact: only the final result is range-checked (ruling 3 of 0.16)
                    java.math.BigInteger ms = java.math.BigInteger.valueOf(Transform.asLong(v[0]))
                            .multiply(java.math.BigInteger.valueOf(1000L))
                            .add(java.math.BigInteger.valueOf(Math.floorDiv(Transform.asLong(v[1]), 1_000_000L)));
                    return ms.bitLength() < 64 ? (Object) ms.longValue() : null;
                }
                case ADD:
                case SUB:
                    if (type.equals("int")) {
                        try {
                            long a = Transform.asLong(v[0]), b = Transform.asLong(v[1]);
                            return fn == Fn.ADD ? Math.addExact(a, b) : Math.subtractExact(a, b);
                        } catch (ArithmeticException ex) {
                            return null;
                        }
                    }
                    r = fn == Fn.ADD ? Transform.asDouble(v[0]) + Transform.asDouble(v[1])
                                     : Transform.asDouble(v[0]) - Transform.asDouble(v[1]);
                    break;
                case DEG:
                    r = Transform.asDouble(v[0]) * RAD;
                    break;
                case RAD:
                    r = Transform.asDouble(v[0]) * DEG;
                    break;
                case DEG_LAT_OF:
                case DEG_LON_OF:
                case M_LAT_OF:
                case M_LON_OF: {
                    double x = Transform.asDouble(v[0]), lat = Transform.asDouble(v[1]);
                    if (!(lat >= -90.0 && lat <= 90.0)) return null;   // ruling 6 of 0.16
                    double phi = lat * DEG, sin = Math.sin(phi), w = 1.0 - Wgs84.E2 * sin * sin;
                    switch (fn) {
                        case DEG_LAT_OF:
                            r = (x / (Wgs84.A * (1.0 - Wgs84.E2) / Math.pow(w, 1.5))) * RAD;
                            break;
                        case DEG_LON_OF: {
                            double cos = Math.abs(Math.cos(phi));
                            if (cos <= 1e-12) return null;
                            r = (x / (Wgs84.A / Math.sqrt(w) * cos)) * RAD;
                            break;
                        }
                        case M_LAT_OF:
                            r = x * DEG * (Wgs84.A * (1.0 - Wgs84.E2) / Math.pow(w, 1.5));
                            break;
                        default:
                            r = x * DEG * (Wgs84.A / Math.sqrt(w)) * Math.abs(Math.cos(phi));
                    }
                    break;
                }
                case ECEF_X:
                case ECEF_Y:
                case ECEF_Z: {
                    double lat = Transform.asDouble(v[0]), lon = Transform.asDouble(v[1]), hae = Transform.asDouble(v[2]);
                    if (!(lat >= -90.0 && lat <= 90.0)) return null;   // ruling 6; longitude unchecked (ruling 11)
                    double phi = lat * DEG, lam = lon * DEG, sin = Math.sin(phi);
                    double n = Wgs84.A / Math.sqrt(1.0 - Wgs84.E2 * sin * sin);
                    if (fn == Fn.ECEF_X) r = (n + hae) * Math.cos(phi) * Math.cos(lam);
                    else if (fn == Fn.ECEF_Y) r = (n + hae) * Math.cos(phi) * Math.sin(lam);
                    else r = (n * (1.0 - Wgs84.E2) + hae) * sin;
                    break;
                }
                case LON_OF_ECEF: {
                    double x = Transform.asDouble(v[0]), y = Transform.asDouble(v[1]);
                    if (x == 0 && y == 0) return null;
                    r = Math.atan2(y, x) * RAD;
                    if (r == -180.0) r = 180.0;   // ruling 5 of 0.16
                    break;
                }
                case LAT_OF_ECEF:
                case HAE_OF_ECEF: {
                    double[] g = Wgs84.geodetic(Transform.asDouble(v[0]), Transform.asDouble(v[1]), Transform.asDouble(v[2]));
                    if (g == null) return null;
                    r = fn == Fn.LAT_OF_ECEF ? g[0] * RAD : g[1];
                    break;
                }
                default:
                    throw new IllegalStateException(fn.name());
            }
            if (!Double.isFinite(r)) return null;
            return r == 0.0 ? 0.0 : r;   // no negative zero in the model
        }
    }

    private ModelModule(String name, String version, Distribution distribution, List<String> sources, Map<String, String> keys,
                        List<Derive> derives, Set<String> lists, List<String> uses) {
        this.uses = Collections.unmodifiableList(uses);
        this.lists = Collections.unmodifiableSet(lists);
        this.derives = Collections.unmodifiableList(derives);
        this.name = name;
        this.version = version;
        this.distribution = distribution;
        this.sources = Collections.unmodifiableList(sources);
        this.keys = Collections.unmodifiableMap(keys);
    }

    /** The module name of a pack's model key: the text before the first {@code .}, or {@code core} when there is none. */
    public static String moduleOf(String modelKey) {
        int dot = modelKey.indexOf('.');
        return dot < 0 ? CORE : modelKey.substring(0, dot);
    }

    /** The key name of a pack's model key inside its module: the text after the first {@code .}, or all of it. */
    public static String keyOf(String modelKey) {
        int dot = modelKey.indexOf('.');
        return dot < 0 ? modelKey : modelKey.substring(dot + 1);
    }

    /** Parse module text with no loaded module to resolve the keys of {@code derive} lines against. */
    public static ModelModule parse(String text, String source) { return parse(text, source, Collections.emptyMap()); }

    /**
     * The module name and the modules its {@code uses} lines name, read from module text without checking anything
     * else: what a directory loader needs to load each module after the modules it uses. The name is first; null
     * when the text has no {@code module} line.
     */
    static List<String> nameAndUses(String text, String source) {
        List<String> out = new ArrayList<>();
        out.add(null);
        String[] lines = text.split("\r?\n", -1);
        for (int i = 0; i < lines.length; i++) {
            List<String> tok = Pack.tokenize(lines[i], source + ":" + (i + 1));
            if (tok.size() != 2) continue;
            if (tok.get(0).equals("module") && out.get(0) == null) out.set(0, tok.get(1));
            else if (tok.get(0).equals("uses")) out.add(tok.get(1));
        }
        return out;
    }

    /**
     * Parse module text. {@code source} names the file for error messages. {@code loaded} holds the modules loaded
     * so far, by name: a {@code derive} line may name the keys of {@code core} and, as arguments, the keys of the
     * modules its own module {@code uses}.
     */
    public static ModelModule parse(String text, String source, Map<String, ModelModule> loaded) {
        return parse(text, source, loaded, null);
    }

    /**
     * Parse module text as an engine with the distribution limit {@code limit} loads it (null: no engine). The
     * checks run in the order of ruling 29 of 0.8: {@code missing-distribution}, {@code missing-source},
     * {@code distribution-refused}, {@code unknown-module}, {@code distribution-violation}, then the {@code derive}
     * checks; the engine reports {@code duplicate-module} after them.
     */
    static ModelModule parse(String text, String source, Map<String, ModelModule> loaded, Distribution limit) {
        List<String> uses = new ArrayList<>();
        List<String[]> deriveLines = new ArrayList<>();
        String name = null, version = null;
        Distribution distribution = null;
        List<String> sources = new ArrayList<>();
        LinkedHashMap<String, String> keys = new LinkedHashMap<>();
        Set<String> lists = new java.util.LinkedHashSet<>();
        GtException afterFile = null;   // the first failure that is not a line check
        String[] lines = text.split("\r?\n", -1);
        for (int i = 0; i < lines.length; i++) {
            String where = source + ":" + (i + 1);
            List<String> tok = Pack.tokenize(lines[i], where);
            if (tok.isEmpty()) continue;
            String kw = tok.get(0);
            List<String> args = tok.subList(1, tok.size());
            switch (kw) {
                case "module":
                    arity(kw, args, 1, 1, where, name);
                    if (name != null) throw bad(name, where + ": module given twice");
                    if ((args.get(0).isEmpty() || args.get(0).indexOf('.') >= 0) && afterFile == null) {
                        afterFile = bad(name, where + ": module name must be non-empty and contain no \".\": \"" + args.get(0) + "\"");
                    }
                    name = args.get(0);
                    break;
                case "version":
                    arity(kw, args, 1, 1, where, name);
                    if (version != null) throw bad(name, where + ": version given twice");
                    if (!args.get(0).matches(Pack.SEMVER) && afterFile == null) {
                        afterFile = bad(name, where + ": version is not semver: " + args.get(0));
                    }
                    version = args.get(0);
                    break;
                case "distribution":
                    arity(kw, args, 1, 1, where, name);
                    if (distribution != null) throw bad(name, where + ": distribution given twice");
                    distribution = Distribution.byToken(args.get(0));
                    if (distribution == null) {
                        throw bad(name, where + ": distribution must be public or controlled, got \"" + args.get(0) + "\"");
                    }
                    break;
                case "source":
                    arity(kw, args, 1, 1, where, name);
                    sources.add(args.get(0));
                    break;
                case "key": {
                    arity(kw, args, 3, 4, where, name);
                    String key = args.get(0), type = args.get(1);
                    // a key's name, its type and duplicate-key are checked after the file (ruling 5b of 0.11)
                    if (key.isEmpty() || key.indexOf('.') >= 0) {
                        if (afterFile == null) afterFile = bad(name, where + ": key name must be non-empty and contain no \".\": \"" + key + "\"");
                    } else if (!type.equals("string") && !type.equals("float") && !type.equals("int")) {
                        if (afterFile == null) afterFile = bad(name, where + ": key type must be string, float or int, got \"" + type + "\"");
                    } else if (keys.containsKey(key) || lists.contains(key)) {
                        if (afterFile == null) {
                            afterFile = new GtException(GtException.Code.DUPLICATE_KEY, name, key,
                                    where + ": key " + key + " appears twice in its module");
                        }
                    } else {
                        keys.put(key, type);
                    }
                    break;
                }
                case "list": {
                    arity(kw, args, 1, 2, where, name);
                    String list = args.get(0);
                    if (list.isEmpty() || list.indexOf('.') >= 0) {
                        if (afterFile == null) afterFile = bad(name, where + ": list name must be non-empty and contain no \".\": \"" + list + "\"");
                    } else if (keys.containsKey(list) || lists.contains(list)) {
                        if (afterFile == null) {
                            afterFile = new GtException(GtException.Code.DUPLICATE_KEY, name, list,
                                    where + ": list " + list + " has the name of another key or list of its module");
                        }
                    } else {
                        lists.add(list);
                    }
                    break;
                }
                case "uses":
                    arity(kw, args, 1, 1, where, name);
                    if (!uses.contains(args.get(0))) uses.add(args.get(0));
                    break;
                case "derive": {
                    String[] d = new String[args.size() + 1];
                    d[0] = where;
                    for (int a = 0; a < args.size(); a++) d[a + 1] = args.get(a);
                    // A line refused on its own text is a line error, raised as the file is read; its keys and
                    // their types are checked in the place ruling 29 gives (ruling 32 of 0.8).
                    try {
                        derive(d, name, keys, uses, loaded, true);
                    } catch (GtException ex) {
                        if (afterFile == null) afterFile = ex;   // a function name or parameter: after the file
                    }
                    deriveLines.add(d);
                    break;
                }
                default:
                    throw new GtException(GtException.Code.UNKNOWN_DIRECTIVE, name, null, where + ": unknown directive \"" + kw + "\"");
            }
        }
        // After the file (ruling 5b of 0.11): every cause of a module line other than checks 1 to 3, 5 and 6; then
        // missing-module, missing-version; then the order of ruling 29 of 0.8.
        if (afterFile != null) throw afterFile;
        if (name == null) throw new GtException(GtException.Code.MISSING_MODULE, null, null, source + ": no module line");
        if (version == null) throw new GtException(GtException.Code.MISSING_VERSION, name, null, source + ": no version line");
        if (distribution == null) {
            throw new GtException(GtException.Code.MISSING_DISTRIBUTION, name, null, source + ": module has no distribution line");
        }
        if (sources.isEmpty()) {
            throw new GtException(GtException.Code.MISSING_SOURCE, name, null, source + ": module has no source line");
        }
        if (limit != null) {
            if (!distribution.within(limit)) {
                throw new GtException(GtException.Code.DISTRIBUTION_REFUSED, null, null, source + ": module " + name + " is "
                        + distribution.token() + ", above this engine's limit " + limit.token());
            }
            // A module is loaded after the modules it uses, and a public module uses only public modules (0.8).
            for (String u : uses) {
                if (!loaded.containsKey(u)) {
                    throw new GtException(GtException.Code.UNKNOWN_MODULE, null, null, source + ": module " + name
                            + " uses module " + u + ", which is not loaded");
                }
            }
            if (distribution == Distribution.PUBLIC) {
                for (String u : uses) {
                    if (loaded.get(u).distribution != Distribution.PUBLIC) {
                        throw new GtException(GtException.Code.DISTRIBUTION_VIOLATION, null, null, source + ": public module "
                                + name + " uses " + loaded.get(u).distribution.token() + " module " + u);
                    }
                }
            }
        }
        // A derive line may name a key declared below it, so its keys are checked once the file is read; these are
        // the last checks of a module but duplicate-module.
        List<Derive> derives = new ArrayList<>();
        for (String[] d : deriveLines) derives.add(derive(d, name, keys, uses, loaded, false));
        return new ModelModule(name, version, distribution, sources, keys, derives, lists, uses);
    }

    private static GtException badDerive(String module, String where, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, module, null, where + ": derive: " + why);
    }

    /**
     * The declared type of a derive line's key: a bare key of {@code core}, {@code <module>.<key>} of this module,
     * or, for an argument, {@code <other>.<key>} of a module this one uses.
     */
    private static String deriveKeyType(String key, String module, Map<String, String> keys, List<String> uses,
                                        Map<String, ModelModule> loaded, boolean isTarget, String where) {
        String m = moduleOf(key), k = keyOf(key);
        Map<String, String> table;
        if (m.equals(module)) {
            // a core key is written bare (ruling 2 of 0.4); `core.<key>` is not how a key of core is named
            if (CORE.equals(module) && key.indexOf('.') >= 0) throw badDerive(module, where, "key " + key + " is not a key of core or of this module");
            table = keys;
        } else if (CORE.equals(m) && key.indexOf('.') < 0) {
            ModelModule core = loaded.get(CORE);
            table = core == null ? null : core.keys;
        } else if (!isTarget && uses.contains(m) && key.indexOf('.') >= 0) {
            ModelModule used = loaded.get(m);
            if (used == null) {
                throw new GtException(GtException.Code.UNKNOWN_MODULE, module, null,
                        where + ": derive: key " + key + " is of module " + m + ", which is not loaded");
            }
            table = used.keys;
        } else if (uses.contains(m) && key.indexOf('.') >= 0) {
            throw badDerive(module, where, "target " + key + " is a key of another module");
        } else {
            throw badDerive(module, where, "key " + key + " is not a key of core, of this module or of a module it uses");
        }
        String type = table == null ? null : table.get(k);
        if (type == null) throw badDerive(module, where, "key " + key + " is not declared");
        return type;
    }

    /** A derive parameter is number text (ruling 2c of 0.11). */
    private static double decimal(String s, String module, String where) {
        if (!Transform.isNumText(s)) throw badDerive(module, where, "\"" + s + "\" is not number text");
        return Double.parseDouble(s);
    }

    /**
     * Check one derive line ({@code d[0]} is its place in the file, the rest its arguments) and build it. With
     * {@code shapeOnly} only the line itself is checked (its function, parameter and argument count) and null is
     * returned: the checks that need no key, which run as the file is read (ruling 32 of 0.8).
     */
    private static Derive derive(String[] d, String module, Map<String, String> keys, List<String> uses,
                                 Map<String, ModelModule> loaded, boolean shapeOnly) {
        String where = d[0];
        if (d.length < 4) throw badDerive(module, where, "takes a target key, a function and at least one argument key");
        String target = d[1], function = d[2];
        List<String> args = new ArrayList<>();
        for (int i = 3; i < d.length; i++) args.add(d[i]);
        int colon = function.indexOf(':');
        String head = colon < 0 ? function : function.substring(0, colon);
        String param = colon < 0 ? null : function.substring(colon + 1);
        Derive.Fn fn;
        int argc; // -1: one or more
        switch (head) {
            case "copy": fn = Derive.Fn.COPY; argc = 1; break;
            case "hypot": fn = Derive.Fn.HYPOT; argc = 2; break;
            case "bearing": fn = Derive.Fn.BEARING; argc = 2; break;
            case "east_of": fn = Derive.Fn.EAST_OF; argc = 2; break;
            case "north_of": fn = Derive.Fn.NORTH_OF; argc = 2; break;
            case "neg": fn = Derive.Fn.NEG; argc = 1; break;
            case "scale": fn = Derive.Fn.SCALE; argc = 1; break;
            case "offset": fn = Derive.Fn.OFFSET; argc = 1; break;
            case "join": fn = Derive.Fn.JOIN; argc = -1; break;
            case "day_seconds": fn = Derive.Fn.DAY_SECONDS; argc = 1; break;
            case "any": fn = Derive.Fn.ANY; argc = -1; break;
            case "not": fn = Derive.Fn.NOT; argc = 1; break;
            case "parse_int": fn = Derive.Fn.PARSE_INT; argc = 1; break;
            case "text_of": fn = Derive.Fn.TEXT_OF; argc = 1; break;
            case "present": fn = Derive.Fn.PRESENT; argc = 1; break;
            case "sec_of": fn = Derive.Fn.SEC_OF; argc = 1; break;
            case "nsec_of": fn = Derive.Fn.NSEC_OF; argc = 1; break;
            case "ms_of": fn = Derive.Fn.MS_OF; argc = 2; break;
            case "deg": fn = Derive.Fn.DEG; argc = 1; break;
            case "rad": fn = Derive.Fn.RAD; argc = 1; break;
            case "add": fn = Derive.Fn.ADD; argc = 2; break;
            case "sub": fn = Derive.Fn.SUB; argc = 2; break;
            case "deg_lat_of": fn = Derive.Fn.DEG_LAT_OF; argc = 2; break;
            case "deg_lon_of": fn = Derive.Fn.DEG_LON_OF; argc = 2; break;
            case "m_lat_of": fn = Derive.Fn.M_LAT_OF; argc = 2; break;
            case "m_lon_of": fn = Derive.Fn.M_LON_OF; argc = 2; break;
            case "ecef_x": fn = Derive.Fn.ECEF_X; argc = 3; break;
            case "ecef_y": fn = Derive.Fn.ECEF_Y; argc = 3; break;
            case "ecef_z": fn = Derive.Fn.ECEF_Z; argc = 3; break;
            case "lat_of_ecef": fn = Derive.Fn.LAT_OF_ECEF; argc = 3; break;
            case "lon_of_ecef": fn = Derive.Fn.LON_OF_ECEF; argc = 3; break;
            case "hae_of_ecef": fn = Derive.Fn.HAE_OF_ECEF; argc = 3; break;
            default: throw badDerive(module, where, "unknown function \"" + function + "\"");
        }
        boolean takesParam = fn == Derive.Fn.SCALE || fn == Derive.Fn.OFFSET || fn == Derive.Fn.JOIN;
        if (takesParam != (param != null)) {
            throw badDerive(module, where, takesParam ? head + " needs a parameter, as " + head + ":<value>" : head + " takes no parameter");
        }
        if (argc >= 0 && args.size() != argc) {
            throw badDerive(module, where, head + " takes " + argc + " argument key(s), got " + args.size());
        }
        if (shapeOnly) return null;
        String type = deriveKeyType(target, module, keys, uses, loaded, true, where);
        List<String> argTypes = new ArrayList<>();
        for (String a : args) argTypes.add(deriveKeyType(a, module, keys, uses, loaded, false, where));
        Derive out = new Derive(target, args, function, fn, type);
        String need; // the type the target and every argument must have
        String needArg = null; // the type every argument must have, when it differs from the target's
        switch (fn) {
            case DAY_SECONDS:
                need = "float";
                needArg = "int";
                break;
            case ANY:
            case NOT:
                need = "int";
                break;
            case PRESENT:
                need = "int";
                needArg = "";   // any scalar type: the argument is read for presence only (ruling 3 of 0.12)
                break;
            case PARSE_INT:
                need = "int";
                needArg = "string";
                break;
            case TEXT_OF:
                need = "string";
                needArg = "int";
                break;
            case COPY:
                need = type;
                break;
            case SEC_OF:
            case NSEC_OF:
            case MS_OF:
                need = "int";
                break;
            case ADD:
            case SUB:
                // all int or all float, no promotion (ruling 4 of 0.16)
                need = type.equals("int") ? "int" : "float";
                break;
            case JOIN:
                need = "string";
                out.sep = param;
                break;
            case OFFSET:
                if (type.equals("int") && argTypes.get(0).equals("int")) {
                    need = "int";
                    if (!Transform.INT_TEXT.matcher(param).matches()) {
                        throw badDerive(module, where, "an offset on integers is integer text, got \"" + param + "\"");
                    }
                    try {
                        out.addInt = Transform.parseInt(param);
                    } catch (IllegalArgumentException ex) {
                        throw badDerive(module, where, "offset " + param + " does not fit 64 bits");
                    }
                } else {
                    need = "float";
                    out.addFloat = decimal(param, module, where);
                }
                break;
            case SCALE: {
                need = "float";
                int slash = param.indexOf('/');
                if (slash >= 0) {
                    String a = param.substring(0, slash), b = param.substring(slash + 1);
                    // <num> integer text, <den> an unsigned decimal integer (ruling 2c of 0.11); the derive function
                    // is not a transform, so ruling 25 of 0.15 (unsigned fractions) does not apply to it
                    if (!Transform.INT_TEXT.matcher(a).matches() || !Transform.UNSIGNED.matcher(b).matches()) {
                        throw badDerive(module, where, "a fraction factor is <num>/<den>: integer text over an unsigned decimal integer, got \"" + param + "\"");
                    }
                    out.fraction = true;
                    out.num = new java.math.BigDecimal(a).doubleValue();
                    out.den = new java.math.BigDecimal(b).doubleValue();
                    if (out.den == 0) throw badDerive(module, where, "a fraction factor cannot have a zero denominator");
                } else {
                    out.factor = decimal(param, module, where);
                }
                break;
            }
            default:
                need = "float";
        }
        if (!type.equals(need)) {
            throw badDerive(module, where, "target " + target + " is " + type + ", " + head + " gives " + need);
        }
        if (needArg == null) needArg = need;
        for (int i = 0; i < args.size() && !needArg.isEmpty(); i++) {
            if (!argTypes.get(i).equals(needArg)) {
                throw badDerive(module, where, "argument " + args.get(i) + " is " + argTypes.get(i) + ", " + head + " takes " + needArg);
            }
        }
        return out;
    }

    private static void arity(String kw, List<String> args, int min, int max, String where, String module) {
        if (args.size() < min || args.size() > max) {
            String n = min == max ? Integer.toString(min) : min + " or " + max;
            throw bad(module, where + ": " + kw + " takes " + n + " argument(s), got " + args.size());
        }
    }

    private static GtException bad(String module, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, module, null, detail);
    }
}
