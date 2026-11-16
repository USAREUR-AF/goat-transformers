package goat.transformers;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** A parsed {@code pack.def}. */
public final class Pack {
    public enum Wire { XML, GEOJSON, BITS, PROTOBUF, JSON }

    /** One {@code field} or {@code when} line: a locator on the wire. */
    public abstract static class Line {
        public final String locator;
        public final int line;
        /** The locator as the pack's codec parsed it; set once by the codec. */
        Object loc;

        Line(String locator, int line) {
            this.locator = locator;
            this.line = line;
        }
    }

    /** One {@code field} line. Exactly one of {@code transform} (text wires), {@code bits} and {@code pb} is set. */
    public static final class Field extends Line {
        public final String key;
        public final Transform transform;
        public final BitsTransform bits;
        public final PbTransform pb;
        /** The value table named by {@code via}, or null. */
        public final String via;
        /** bits: the field's bytes are reversed before the transform reads them and after it writes them. */
        public final boolean swap;
        /** bits with ascii: decode also removes trailing spaces. */
        public final boolean trim;
        /** bits: a field any of whose bits lies beyond the input is absent. */
        public final boolean optional;
        /** The key's declared type; set when the pack is checked against the loaded modules. */
        String keyType;
        /** {@code via}: canonical native text to model value, and canonical model text to native value. */
        Map<String, Object> viaDecode;
        Map<String, Object> viaEncode;

        Field(String key, String locator, Transform transform, BitsTransform bits, PbTransform pb,
              String via, boolean swap, boolean trim, boolean optional, int line) {
            super(locator, line);
            this.key = key;
            this.transform = transform;
            this.bits = bits;
            this.pb = pb;
            this.via = via;
            this.swap = swap;
            this.trim = trim;
            this.optional = optional;
        }

        /** Bind the field to its key's declared type and, with {@code via}, to the entries of its table. */
        void bind(String keyType, List<String[]> entries) {
            this.keyType = keyType;
            if (entries == null) return;
            String yields = yields();
            Map<String, Object> dec = new java.util.HashMap<>();
            Map<String, Object> enc = new java.util.HashMap<>();
            for (String[] en : entries) {
                dec.putIfAbsent(canon(en[0], yields), read(en[1], keyType));
                enc.putIfAbsent(canon(en[1], keyType), read(en[0], yields));
            }
            viaDecode = dec;
            viaEncode = enc;
        }

        /** The transform's name as written in the pack. */
        public String transformName() {
            return transform != null ? transform.wireName() : bits != null ? bits.wireName() : pb.wireName();
        }

        /** The model type the transform yields: {@code string}, {@code float} or {@code int}. */
        public String yields() {
            return transform != null ? transform.yields() : bits != null ? bits.yields() : pb.yields();
        }
    }

    /** A table value that cannot be read as the type its side needs. */
    static final Object UNREADABLE = new Object();

    /** {@code text} read as {@code type} ({@code string}, {@code int} or {@code float}), or {@link #UNREADABLE}. */
    static Object read(String text, String type) {
        try {
            switch (type) {
                case "int": return Transform.parseInt(text);
                case "float": return Transform.parseFloat(text);
                default: return text;
            }
        } catch (IllegalArgumentException ex) {
            return UNREADABLE;
        }
    }

    /** The canonical text of {@code text} read as {@code type}; the text itself when it cannot be read. */
    static String canon(String text, String type) {
        Object v = read(text, type);
        return v == UNREADABLE ? text : canonText(v);
    }

    /** Canonical text of a model value: an integer as decimal digits, a float as the shortest round-trip decimal. */
    static String canonText(Object v) {
        if (v instanceof Double) return Transform.formatDouble((Double) v);
        return String.valueOf(v);
    }

    /** One {@code when} or {@code const} line: the kind applies when the wire holds {@code value} at {@code locator}. */
    public static final class When extends Line {
        /** The value as written in the pack. */
        public final String value;
        /** True for the bare value {@code present}. */
        public final boolean present;
        /** Text wires: the value with a leading {@code =} stripped. */
        public final String text;
        /** Text wires: the value was written with a leading {@code =}, which forces a string on encode. */
        public final boolean forced;
        /** bits and protobuf: the unsigned integer value, as a 64-bit pattern. */
        public final long number;
        /** True for a {@code const} line: written on encode like a {@code when} value, never checked on decode. */
        public final boolean isConst;

        When(String locator, String value, boolean present, String text, boolean forced, long number, boolean isConst, int line) {
            super(locator, line);
            this.isConst = isConst;
            this.value = value;
            this.present = present;
            this.text = text;
            this.forced = forced;
            this.number = number;
        }
    }

    /**
     * The lines one set of model keys is read and written through: the common lines plus one kind's, or the body of
     * one {@code group} block (locators then relative to one item).
     */
    public static final class Scope {
        /** {@code field}, {@code when}, {@code const} and {@code group} lines, in line order. */
        public final List<Line> lines;
        /** The {@code group} lines among them, in line order. */
        public final List<Group> groups;
        /** {@code default} values as written. */
        public final Map<String, String> defaults;
        /** The defaults read as each key's declared type; set when the pack is checked against the modules. */
        Map<String, Object> defaultValues = Collections.emptyMap();
        /**
         * Text wires: locator to the {@code when} or {@code const} line whose value is written there (the last such
         * line). A {@code when ... present} writes nothing and is not here.
         */
        final Map<String, When> fixed = new java.util.HashMap<>();
        /** Scratch for the codec (for example the bit extent of a bits scope). */
        Object info;

        Scope(List<Line> lines, Map<String, String> defaults) {
            this.lines = Collections.unmodifiableList(lines);
            this.defaults = Collections.unmodifiableMap(defaults);
            List<Group> gs = new ArrayList<>();
            for (Line l : lines) {
                if (l instanceof When && !((When) l).present) fixed.put(l.locator, (When) l);
                if (l instanceof Group) gs.add((Group) l);
            }
            this.groups = Collections.unmodifiableList(gs);
        }
    }

    /** One {@code group} block: a repeating part of the message mapped to a list of the model. */
    public static final class Group extends Line {
        /** The list's name, as a key is written: bare for {@code core}, {@code <module>.<name>} otherwise. */
        public final String list;
        /** The lines between {@code group} and its {@code end}; their locators are relative to one item. */
        public final Scope body;
        /** bits: the size of one item in bits; 0 on another wire. */
        public final int itemBits;
        /** bits: the {@code <word>:<pos>:<len>} of the enclosing scope that holds the number of items, or null. */
        public final String countLocator;
        /** bits: the fixed number of items; -1 when the count is a locator or the wire is not bits. */
        public final long countFixed;
        /** The count locator as the codec parsed it. */
        Object countLoc;

        Group(String list, String locator, Scope body, int itemBits, String countLocator, long countFixed, int line) {
            super(locator, line);
            this.list = list;
            this.body = body;
            this.itemBits = itemBits;
            this.countLocator = countLocator;
            this.countFixed = countFixed;
        }
    }

    /** One message kind: its name, its {@code requires} keys, and its lines after the common lines. */
    public static final class Kind {
        /** The kind's name; null for the single implicit kind of a pack with no {@code kind} line. */
        public final String name;
        public final List<String> requires;
        /** The common lines and this kind's own, with the defaults in force for them. */
        public final Scope scope;
        /** Common lines, then this kind's own lines, in line order ({@code scope.lines}). */
        public final List<Line> lines;
        /** This kind's own {@code when} lines ({@code const} lines are not among them). */
        public final List<When> whens;
        /** xml: the root element of this kind (its own {@code root} line, else the pack's). */
        public final String root;
        /** {@code default} values as written, common ones first; a kind's own line replaces a common one. */
        public final Map<String, String> defaults;
        /** {@code scope.fixed}: the {@code when} and {@code const} values written on a text wire, by locator. */
        final Map<String, When> fixed;

        Kind(String name, List<String> requires, List<Line> lines, List<When> whens, String root, Map<String, String> defaults) {
            this.name = name;
            this.root = root;
            this.scope = new Scope(lines, defaults);
            this.defaults = scope.defaults;
            this.fixed = scope.fixed;
            this.requires = Collections.unmodifiableList(requires);
            this.lines = scope.lines;
            this.whens = Collections.unmodifiableList(whens);
        }
    }

    static final String SEMVER = "\\d+\\.\\d+\\.\\d+(?:[-+][0-9A-Za-z.+-]+)?";

    /** A field, when or const line held raw until the wire is known. {@code key == null} marks a when or const line. */
    private static final class LineSpec {
        final String key;
        final String locator;
        final String arg;    // transform name (field) or value (when, const)
        final List<String> opts; // field: the tokens after the transform
        final boolean isConst;
        final int line;
        /** A {@code group} line: its body ({@code key} is then the list, {@code opts} the tokens after the locator). */
        BodySpec body;

        LineSpec(String key, String locator, String arg, List<String> opts, boolean isConst, int line) {
            this.key = key;
            this.locator = locator;
            this.arg = arg;
            this.opts = opts;
            this.isConst = isConst;
            this.line = line;
        }
    }

    /** The raw lines and defaults of the common part, of one kind, or of one group body. */
    private static class BodySpec {
        final List<LineSpec> lines = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
    }

    private static final class KindSpec extends BodySpec {
        final String name;
        final int line;
        final List<String> requires = new ArrayList<>();
        String root;
        int rootLine;

        KindSpec(String name, int line) {
            this.name = name;
            this.line = line;
        }
    }

    public final String format;
    public final String version;
    public final Distribution distribution;
    public final List<String> sources;
    /** modules named in {@code uses} lines, in file order; {@code core} is always used and need not be listed. */
    public final List<String> uses;
    public final Wire wire;
    public final String root;
    /** bytes per word on a bits wire; 0 on another wire. */
    public final int wordBytes;
    /** bits wire: true for {@code bit_order msb}. */
    public final boolean msbFirst;
    /** True when the pack has at least one {@code kind} line. */
    public final boolean hasKinds;
    /** {@code when} lines before the first {@code kind}. */
    public final List<When> commonWhens;
    /** The kinds in pack order. A pack with no {@code kind} line has one implicit kind with a null name. */
    public final List<Kind> kinds;
    /** Every {@code field} line, common, of every kind and of every group body, in file order. */
    public final List<Field> fields;
    /** Every {@code field} and {@code group} line at any depth, in file order: the lines checked against key types. */
    final List<Line> typed;
    /** The body of every {@code group} block at any depth. */
    final List<Scope> bodies;
    /** Every model key a {@code field}, {@code requires} or {@code default} line names, with the locator to report, in file order. */
    final List<String[]> keyRefs;
    /** Value tables: name to its {@code map} lines as {@code {native, model}}, in file order. */
    public final Map<String, List<String[]>> tables;
    /** xml: true when at least one kind has its own {@code root} line. */
    public final boolean kindRoots;
    /** native code to CoT type token, in file order (first wins). */
    public final Map<String, String> nativeToCot;
    /** CoT type token to native code (first line wins). */
    public final Map<String, String> cotToNative;

    private Pack(String format, String version, Distribution distribution, List<String> sources, List<String> uses,
                 Wire wire, String root, int wordBytes, boolean msbFirst, boolean hasKinds, List<When> commonWhens,
                 List<Kind> kinds, List<Field> fields, List<Line> typed, List<Scope> bodies, List<String[]> keyRefs,
                 Map<String, List<String[]>> tables,
                 boolean kindRoots, Map<String, String> nativeToCot, Map<String, String> cotToNative) {
        this.typed = typed;
        this.bodies = bodies;
        this.tables = tables;
        this.kindRoots = kindRoots;
        this.format = format;
        this.version = version;
        this.distribution = distribution;
        this.sources = Collections.unmodifiableList(sources);
        this.uses = Collections.unmodifiableList(uses);
        this.wire = wire;
        this.root = root;
        this.wordBytes = wordBytes;
        this.msbFirst = msbFirst;
        this.hasKinds = hasKinds;
        this.commonWhens = Collections.unmodifiableList(commonWhens);
        this.kinds = Collections.unmodifiableList(kinds);
        this.fields = Collections.unmodifiableList(fields);
        this.keyRefs = keyRefs;
        this.nativeToCot = Collections.unmodifiableMap(nativeToCot);
        this.cotToNative = Collections.unmodifiableMap(cotToNative);
    }

    private Map<String, Kind> kindsByName;

    /** The kind named {@code name}, or null. */
    public Kind kind(String name) {
        if (kindsByName == null) {
            Map<String, Kind> m = new java.util.HashMap<>();
            for (Kind k : kinds) if (k.name != null) m.putIfAbsent(k.name, k);
            kindsByName = m;
        }
        return kindsByName.get(name);
    }

    /**
     * The model-side type of a value table: {@code int} when every model value is an integer, {@code float} when
     * every one is a number, else {@code string}.
     */
    public String tableType(String table) {
        String cached = tableTypes.get(table);
        if (cached == null) {
            cached = computeTableType(table);
            tableTypes.put(table, cached);
        }
        return cached;
    }

    private final Map<String, String> tableTypes = new java.util.HashMap<>();
    private static final java.util.regex.Pattern INTEGER = java.util.regex.Pattern.compile("[+-]?\\d+");

    private String computeTableType(String table) {
        boolean allInt = true, allNum = true;
        for (String[] en : tables.get(table)) {
            if (!INTEGER.matcher(en[1]).matches()) allInt = false;
            if (read(en[1], "float") == UNREADABLE) allNum = false;
        }
        return allInt ? "int" : allNum ? "float" : "string";
    }

    /**
     * The union of model keys over the common lines and every kind, in first appearance order. A list is named
     * {@code <list>[]} and each key of its items {@code <list>[].<key>}, nested lists likewise.
     */
    public List<String> modelKeys() {
        LinkedHashSet<String> out = new LinkedHashSet<>();
        Set<Line> seen = java.util.Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        for (Kind k : kinds) {
            for (Line l : k.lines) if (seen.add(l)) modelKeys(l, "", out);   // common lines are shared by the kinds
        }
        return new ArrayList<>(out);
    }

    private static void modelKeys(Line l, String prefix, Set<String> out) {
        if (l instanceof Field) {
            out.add(prefix + ((Field) l).key);
        } else if (l instanceof Group) {
            Group g = (Group) l;
            out.add(prefix + g.list + "[]");
            for (Line b : g.body.lines) modelKeys(b, prefix + g.list + "[].", out);
        }
    }

    private static GtException bad(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_PACK, format, locator, detail);
    }

    private static GtException badDirective(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, detail);
    }

    /** Directives that are not allowed between {@code group} and its {@code end}. */
    private static final Set<String> NOT_IN_GROUP = Set.of("format", "version", "distribution", "source", "uses", "wire",
            "word_bytes", "bit_order", "root", "map", "kind", "requires", "when", "typemap");

    /** What {@link #resolve} needs to know about the pack, and what it collects. */
    private static final class Ctx {
        Wire wire;
        String format;
        String source;
        int wordBytes;   // 0 when not given
        Map<String, List<String[]>> tables;
        final List<Field> fields = new ArrayList<>();
        final List<Line> typed = new ArrayList<>();
        final List<Scope> bodies = new ArrayList<>();
    }

    /** Parse pack.def text. {@code source} names the file for error messages. */
    public static Pack parse(String text, String source) {
        String format = null, version = null, root = null;
        Wire wire = null;
        Integer wordBytes = null;
        String bitOrder = null;
        int bitOrderLine = 0;
        Distribution distribution = null;
        List<String> sources = new ArrayList<>();
        List<String> uses = new ArrayList<>();
        KindSpec common = new KindSpec(null, 0);
        List<KindSpec> kindSpecs = new ArrayList<>();
        Set<String> kindNames = new HashSet<>();
        KindSpec cur = common;
        java.util.ArrayDeque<LineSpec> open = new java.util.ArrayDeque<>();   // the group blocks not yet ended
        List<String[]> keyRefs = new ArrayList<>();
        LinkedHashMap<String, String> n2c = new LinkedHashMap<>();
        LinkedHashMap<String, String> c2n = new LinkedHashMap<>();
        LinkedHashMap<String, List<String[]>> tables = new LinkedHashMap<>();
        String[] lines = text.split("\r?\n", -1);
        for (int i = 0; i < lines.length; i++) {
            int ln = i + 1;
            String where = source + ":" + ln;
            List<String> tok = tokenize(lines[i], where);
            if (tok.isEmpty()) continue;
            String kw = tok.get(0);
            List<String> args = tok.subList(1, tok.size());
            if (!open.isEmpty() && NOT_IN_GROUP.contains(kw)) {
                throw badDirective(format, null, where + ": " + kw + " is not allowed inside a group");
            }
            BodySpec body = open.isEmpty() ? cur : open.peek().body;
            switch (kw) {
                case "format":
                    arity(kw, args, 1, where, format);
                    if (format != null) throw dup(kw, where, format);
                    format = args.get(0);
                    break;
                case "version":
                    arity(kw, args, 1, where, format);
                    if (version != null) throw dup(kw, where, format);
                    if (!args.get(0).matches(SEMVER)) throw bad(format, null, where + ": version is not semver: " + args.get(0));
                    version = args.get(0);
                    break;
                case "distribution":
                    arity(kw, args, 1, where, format);
                    if (distribution != null) throw dup(kw, where, format);
                    distribution = Distribution.byToken(args.get(0));
                    if (distribution == null) {
                        throw bad(format, null, where + ": distribution must be public or controlled, got \"" + args.get(0) + "\"");
                    }
                    break;
                case "source":
                    arity(kw, args, 1, where, format);
                    sources.add(args.get(0));
                    break;
                case "uses":
                    arity(kw, args, 1, where, format);
                    if (!uses.contains(args.get(0))) uses.add(args.get(0));
                    break;
                case "wire":
                    arity(kw, args, 1, where, format);
                    if (wire != null) throw dup(kw, where, format);
                    switch (args.get(0)) {
                        case "xml": wire = Wire.XML; break;
                        case "geojson": wire = Wire.GEOJSON; break;
                        case "bits": wire = Wire.BITS; break;
                        case "protobuf": wire = Wire.PROTOBUF; break;
                        case "json": wire = Wire.JSON; break;
                        default:
                            throw bad(format, null, where + ": unknown wire \"" + args.get(0) + "\"");
                    }
                    break;
                case "word_bytes":
                    arity(kw, args, 1, where, format);
                    if (wordBytes != null) throw dup(kw, where, format);
                    try {
                        int wb = Integer.parseInt(args.get(0));
                        if (wb < 1) throw new NumberFormatException();
                        wordBytes = wb;
                    } catch (NumberFormatException ex) {
                        throw bad(format, null, where + ": word_bytes must be a positive integer, got \"" + args.get(0) + "\"");
                    }
                    break;
                case "bit_order":
                    arity(kw, args, 1, where, format);
                    if (bitOrder != null) throw dup(kw, where, format);
                    if (!args.get(0).equals("lsb") && !args.get(0).equals("msb")) {
                        throw badDirective(format, null, where + ": bit_order must be lsb or msb, got \"" + args.get(0) + "\"");
                    }
                    bitOrder = args.get(0);
                    bitOrderLine = ln;
                    break;
                case "root":
                    arity(kw, args, 1, where, format);
                    if (cur != common) {
                        if (cur.root != null) throw dup(kw, where, format);
                        cur.root = args.get(0);
                        cur.rootLine = ln;
                        break;
                    }
                    if (root != null) throw dup(kw, where, format);
                    root = args.get(0);
                    break;
                case "const":
                    arity(kw, args, 2, where, format);
                    body.lines.add(new LineSpec(null, args.get(0), args.get(1), null, true, ln));
                    break;
                case "default":
                    arity(kw, args, 2, where, format);
                    body.defaults.put(args.get(0), args.get(1));
                    keyRefs.add(new String[]{args.get(0), null});
                    break;
                case "map":
                    arity(kw, args, 3, where, format);
                    tables.computeIfAbsent(args.get(0), k -> new ArrayList<>()).add(new String[]{args.get(1), args.get(2)});
                    break;
                case "kind": {
                    arity(kw, args, 1, where, format);
                    if (!kindNames.add(args.get(0))) {
                        throw new GtException(GtException.Code.DUPLICATE_KIND, format, null,
                                where + ": kind " + args.get(0) + " is declared twice");
                    }
                    cur = new KindSpec(args.get(0), ln);
                    kindSpecs.add(cur);
                    break;
                }
                case "requires":
                    if (args.isEmpty()) throw bad(format, null, where + ": requires takes at least 1 argument, got 0");
                    if (cur == common) {
                        throw badDirective(format, null, where + ": requires before the first kind line");
                    }
                    for (String k : args) {
                        if (!cur.requires.contains(k)) cur.requires.add(k);
                        keyRefs.add(new String[]{k, null});
                    }
                    break;
                case "when":
                    arity(kw, args, 2, where, format);
                    body.lines.add(new LineSpec(null, args.get(0), args.get(1), null, false, ln));
                    break;
                case "field": {
                    if (args.size() < 3) throw bad(format, null, where + ": field takes at least 3 arguments, got " + args.size());
                    String key = args.get(0);
                    body.lines.add(new LineSpec(key, args.get(1), args.get(2), new ArrayList<>(args.subList(3, args.size())), false, ln));
                    keyRefs.add(new String[]{key, args.get(1)});
                    break;
                }
                case "group": {
                    if (args.size() < 2) throw bad(format, null, where + ": group takes at least 2 arguments, got " + args.size());
                    LineSpec g = new LineSpec(args.get(0), args.get(1), null, new ArrayList<>(args.subList(2, args.size())), false, ln);
                    g.body = new BodySpec();
                    body.lines.add(g);
                    open.push(g);
                    keyRefs.add(new String[]{args.get(0), null});
                    break;
                }
                case "end":
                    arity(kw, args, 0, where, format);
                    if (open.isEmpty()) throw badDirective(format, null, where + ": end with no open group");
                    open.pop();
                    break;
                case "typemap":
                    arity(kw, args, 2, where, format);
                    n2c.putIfAbsent(args.get(0), args.get(1));
                    c2n.putIfAbsent(args.get(1), args.get(0));
                    break;
                default:
                    throw new GtException(GtException.Code.UNKNOWN_DIRECTIVE, format, null, where + ": unknown directive \"" + kw + "\"");
            }
        }
        if (!open.isEmpty()) {
            LineSpec g = open.peek();
            throw badDirective(format, g.locator, source + ":" + g.line + ": group " + g.key + " has no end");
        }
        boolean hasKinds = !kindSpecs.isEmpty();
        // Checks that need the whole file run here, before missing-distribution (ruling 25 of 0.5).
        if (!hasKinds) {
            for (LineSpec s : common.lines) {
                if (s.key == null && !s.isConst) {
                    throw badDirective(format, s.locator, source + ":" + s.line + ": when line in a pack with no kind line");
                }
            }
        }
        if (bitOrder != null && wire != null && wire != Wire.BITS) {
            throw badDirective(format, null, source + ":" + bitOrderLine + ": bit_order is for the bits wire only");
        }
        boolean kindRoots = false;
        for (KindSpec ks : kindSpecs) {
            if (ks.root == null) continue;
            kindRoots = true;
            if (wire != null && wire != Wire.XML) {
                throw badDirective(format, null, source + ":" + ks.rootLine + ": root in a kind is for the xml wire only");
            }
        }
        int wb = wordBytes == null ? 0 : wordBytes;
        Ctx ctx = new Ctx();
        ctx.wire = wire;
        ctx.format = format;
        ctx.source = source;
        ctx.wordBytes = wb;
        ctx.tables = tables;
        List<Line> commonLines = new ArrayList<>();
        List<When> commonWhens = new ArrayList<>();
        List<Kind> kinds = new ArrayList<>();
        if (wire != null) {
            Set<String> commonLists = new HashSet<>();
            for (LineSpec s : common.lines) {
                Line l = resolve(s, ctx, false);
                commonLines.add(l);
                if (l instanceof When && !((When) l).isConst) commonWhens.add((When) l);
                if (l instanceof Group) oneGroupPerList(commonLists, (Group) l, ctx);
            }
            if (!hasKinds) {
                kinds.add(new Kind(null, new ArrayList<>(), commonLines, new ArrayList<>(), root, common.defaults));
            }
            for (KindSpec ks : kindSpecs) {
                List<Line> all = new ArrayList<>(commonLines.size() + ks.lines.size());
                all.addAll(commonLines);
                List<When> whens = new ArrayList<>();
                Set<String> lists = null;
                for (LineSpec s : ks.lines) {
                    Line l = resolve(s, ctx, false);
                    all.add(l);
                    if (l instanceof When && !((When) l).isConst) whens.add((When) l);
                    if (l instanceof Group) {
                        if (lists == null) lists = new HashSet<>(commonLists);
                        oneGroupPerList(lists, (Group) l, ctx);
                    }
                }
                LinkedHashMap<String, String> defaults = new LinkedHashMap<>(common.defaults);
                defaults.putAll(ks.defaults);
                kinds.add(new Kind(ks.name, ks.requires, all, whens, ks.root != null ? ks.root : root, defaults));
            }
            if (wire == Wire.BITS && wordBytes != null) {
                // The layout of each scope: common plus one kind (group bodies were checked as they were resolved).
                for (Kind k : kinds) BitsCodec.prepare(k.scope, wb, 0, format, source);
            }
        }
        if (distribution == null) {
            throw new GtException(GtException.Code.MISSING_DISTRIBUTION, format, null, source + ": pack has no distribution line");
        }
        if (sources.isEmpty()) {
            throw new GtException(GtException.Code.MISSING_SOURCE, format, null, source + ": pack has no source line");
        }
        if (format == null) throw bad(null, null, source + ": no format directive");
        if (version == null) throw bad(format, null, source + ": no version directive");
        if (wire == null) throw bad(format, null, source + ": no wire directive");
        if (wire == Wire.XML) {
            for (Kind k : kinds) {
                if (k.root == null) {
                    throw bad(format, null, source + ": wire xml needs a root directive, in the pack or in every kind");
                }
            }
        }
        if (wire != Wire.XML && root != null) throw bad(format, null, source + ": root is xml only");
        if (wire == Wire.BITS && wordBytes == null) throw bad(format, null, source + ": wire bits needs a word_bytes directive");
        if (wire != Wire.BITS && wordBytes != null) throw bad(format, null, source + ": word_bytes is bits only");
        boolean mapsType = false;
        for (String[] r : keyRefs) if (r[1] != null && r[0].equals("type")) mapsType = true;
        if (!n2c.isEmpty() && !mapsType) throw bad(format, null, source + ": typemap without a field for model key type");

        // Report in file order, as the 0.4 checks do.
        ctx.fields.sort((a, b) -> Integer.compare(a.line, b.line));
        ctx.typed.sort((a, b) -> Integer.compare(a.line, b.line));
        return new Pack(format, version, distribution, sources, uses, wire, root, wb, "msb".equals(bitOrder), hasKinds,
                commonWhens, kinds, ctx.fields, ctx.typed, ctx.bodies, keyRefs, tables, kindRoots, n2c, c2n);
    }

    /** Within one scope a list is mapped by at most one group. */
    private static void oneGroupPerList(Set<String> lists, Group g, Ctx ctx) {
        if (!lists.add(g.list)) {
            throw badDirective(ctx.format, g.locator, ctx.source + ":" + g.line + ": list " + g.list
                    + " is mapped by two groups of one scope");
        }
    }

    /** Turn one raw group line and its body into its typed form. {@code inGroup}: the group is nested in another. */
    private static Group resolveGroup(LineSpec s, Ctx ctx, boolean inGroup) {
        String where = ctx.source + ":" + s.line;
        String format = ctx.format;
        int itemBits = 0;
        String countLocator = null;
        long countFixed = -1;
        String why;
        if (ctx.wire == Wire.BITS) {
            String item = null, count = null;
            for (int i = 0; i < s.opts.size(); i++) {
                String o = s.opts.get(i);
                if (o.equals("item") && item == null && i + 1 < s.opts.size()) item = s.opts.get(++i);
                else if (o.equals("count") && count == null && i + 1 < s.opts.size()) count = s.opts.get(++i);
                else throw badDirective(format, s.locator, where + ": a bits group is group <list> <word>:<pos> item <bits> count <locator | n>");
            }
            if (item == null) throw badDirective(format, s.locator, where + ": a bits group needs item <bits>");
            if (count == null) throw badDirective(format, s.locator, where + ": a bits group needs count <locator | n>");
            why = BitsCodec.checkGroupLocator(s.locator);
            if (why != null) throw bad(format, s.locator, where + ": " + why);
            try {
                itemBits = Integer.parseInt(item);
                if (itemBits < 1) throw new NumberFormatException();
            } catch (NumberFormatException ex) {
                throw bad(format, s.locator, where + ": item takes a positive number of bits, got \"" + item + "\"");
            }
            if (count.matches("\\d+")) {
                try {
                    countFixed = Long.parseLong(count);
                } catch (NumberFormatException ex) {
                    throw bad(format, s.locator, where + ": count " + count + " is too large");
                }
            } else {
                why = BitsCodec.checkLocator(count);
                if (why != null) throw bad(format, s.locator, where + ": count: " + why);
                if (BitsCodec.parseLoc(count)[2] > 64) {
                    throw badDirective(format, s.locator, where + ": a count locator reads at most 64 bits");
                }
                countLocator = count;
            }
        } else {
            if (!s.opts.isEmpty()) {
                String o = s.opts.get(0);
                throw badDirective(format, s.locator, where + ": "
                        + (o.equals("count") || o.equals("item") ? o + " is for the bits wire only" : "unexpected \"" + o + "\" after the group locator"));
            }
            if (ctx.wire == Wire.XML) why = XmlCodec.checkGroupLocator(s.locator);
            else if (ctx.wire == Wire.PROTOBUF) why = ProtobufCodec.checkFieldLocator(s.locator);
            else if (ctx.wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkGroupLocator(s.locator);
            else why = JsonCodec.checkLocator(s.locator);
            if (why != null) throw bad(format, s.locator, where + ": " + why);
        }
        List<Line> lines = new ArrayList<>(s.body.lines.size());
        Set<String> lists = null;
        for (LineSpec b : s.body.lines) {
            Line l = resolve(b, ctx, true);
            lines.add(l);
            if (l instanceof Group) {
                if (lists == null) lists = new HashSet<>();
                oneGroupPerList(lists, (Group) l, ctx);
            }
        }
        Scope body = new Scope(lines, s.body.defaults);
        Group g = new Group(s.key, s.locator, body, itemBits, countLocator, countFixed, s.line);
        if (ctx.wire == Wire.BITS && ctx.wordBytes > 0) BitsCodec.prepare(body, ctx.wordBytes, itemBits, format, ctx.source);
        ctx.bodies.add(body);
        ctx.typed.add(g);
        return g;
    }

    /**
     * Turn one raw field, when, const or group line into its typed form for the pack's wire, checking transform and
     * locator. {@code inGroup}: the line is in a group body, so its locator is relative to one item.
     */
    private static Line resolve(LineSpec s, Ctx ctx, boolean inGroup) {
        Wire wire = ctx.wire;
        String format = ctx.format;
        Map<String, List<String[]>> tables = ctx.tables;
        String where = ctx.source + ":" + s.line;
        if (s.body != null) return resolveGroup(s, ctx, inGroup);
        // `.` is the item itself as a scalar: a field of a group body on json, geojson and protobuf.
        boolean dot = s.locator.equals(".") && wire != Wire.XML && wire != Wire.BITS;
        if (dot && (!inGroup || s.key == null)) {
            throw badDirective(format, s.locator, where + ": the locator . is for a field inside a group");
        }
        if (s.key == null) return resolveWhen(s, wire, format, where, inGroup);
        String via = null;
        boolean swap = false, trim = false, optional = false;
        for (int i = 0; i < s.opts.size(); i++) {
            String o = s.opts.get(i);
            switch (o) {
                case "via":
                    if (via != null || i + 1 >= s.opts.size()) throw badDirective(format, s.locator, where + ": via takes one table name, once");
                    via = s.opts.get(++i);
                    if (!tables.containsKey(via)) {
                        throw badDirective(format, s.locator, where + ": via names table " + via + ", which has no map line");
                    }
                    break;
                case "swap":
                    if (swap) throw badDirective(format, s.locator, where + ": swap given twice");
                    swap = true;
                    break;
                case "trim":
                    if (trim) throw badDirective(format, s.locator, where + ": trim given twice");
                    trim = true;
                    break;
                case "optional":
                    if (optional) throw badDirective(format, s.locator, where + ": optional given twice");
                    optional = true;
                    break;
                default:
                    throw badDirective(format, s.locator, where + ": unknown field option \"" + o + "\"");
            }
        }
        if (wire != Wire.BITS && (swap || trim || optional)) {
            throw badDirective(format, s.locator, where + ": " + (swap ? "swap" : trim ? "trim" : "optional") + " is for the bits wire only");
        }
        String why;
        Field f;
        if (wire == Wire.BITS) {
            if (!BitsTransform.isBitsName(s.arg)) {
                String w = (Transform.byName(s.arg) != null || PbTransform.isPbName(s.arg))
                        ? "transform \"" + s.arg + "\" is not valid on wire bits"
                        : "unknown transform \"" + s.arg + "\"";
                throw new GtException(GtException.Code.UNKNOWN_TRANSFORM, format, s.locator, where + ": " + w);
            }
            BitsTransform bt = BitsTransform.parse(s.arg, format, where);
            f = new Field(s.key, s.locator, null, bt, null, via, swap, trim, optional, s.line);
            why = BitsCodec.checkLocator(s.locator);
            if (trim && !bt.isAscii()) throw badDirective(format, s.locator, where + ": trim is for the ascii transform only");
            if (why == null) {
                int len = BitsCodec.parseLoc(s.locator)[2];
                String lenWhy = bt.checkLen(len);
                if (lenWhy != null) throw badDirective(format, s.locator, where + ": " + lenWhy);
                if (swap && len % 8 != 0) {
                    throw badDirective(format, s.locator, where + ": swap needs a length that is a multiple of 8, got " + len);
                }
            }
        } else if (wire == Wire.PROTOBUF) {
            PbTransform pb = PbTransform.byName(s.arg);
            if (pb == null) {
                String w = (Transform.byName(s.arg) != null || BitsTransform.isBitsName(s.arg))
                        ? "transform \"" + s.arg + "\" is not valid on wire protobuf"
                        : "unknown transform \"" + s.arg + "\"";
                throw new GtException(GtException.Code.UNKNOWN_TRANSFORM, format, s.locator, where + ": " + w);
            }
            f = new Field(s.key, s.locator, null, null, pb, via, false, false, false, s.line);
            why = dot ? null : ProtobufCodec.checkFieldLocator(s.locator);
        } else {
            Transform t = Transform.byName(s.arg);
            if (t == null || (t == Transform.BOOL && wire != Wire.JSON)) {
                String w = (t != null || BitsTransform.isBitsName(s.arg) || PbTransform.isPbName(s.arg))
                        ? "transform \"" + s.arg + "\" is not valid on wire " + wire.name().toLowerCase()
                        : "unknown transform \"" + s.arg + "\"";
                throw new GtException(GtException.Code.UNKNOWN_TRANSFORM, format, s.locator, where + ": " + w);
            }
            f = new Field(s.key, s.locator, t, null, null, via, false, false, false, s.line);
            if (dot) why = null;
            else if (wire == Wire.XML) why = XmlCodec.checkFieldLocator(s.locator);
            else if (wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkFieldLocator(s.locator);
            else why = JsonCodec.checkLocator(s.locator);
        }
        if (why != null) throw bad(format, s.locator, where + ": " + why);
        ctx.fields.add(f);
        ctx.typed.add(f);
        return f;
    }

    private static When resolveWhen(LineSpec s, Wire wire, String format, String where, boolean inGroup) {
        String v = s.arg;
        if (s.isConst && v.equals("present")) {
            throw badDirective(format, s.locator, where + ": const takes a value; write =present for the text");
        }
        if (wire == Wire.BITS) {
            String why = BitsCodec.checkLocator(s.locator);
            if (why != null) throw bad(format, s.locator, where + ": " + why);
            int len = BitsCodec.parseLoc(s.locator)[2];
            if (len > 64) throw badDirective(format, s.locator, where + ": a when line reads at most 64 bits");
            long n = unsigned(v, format, s.locator, where);
            if (len < 64 && (n < 0 || n > BitsTransform.mask(len))) {
                throw badDirective(format, s.locator, where + ": when value " + v + " does not fit " + len + " bits");
            }
            return new When(s.locator, v, false, v, false, n, s.isConst, s.line);
        }
        if (wire == Wire.PROTOBUF) {
            String why = ProtobufCodec.checkFieldLocator(s.locator);
            if (why != null) throw bad(format, s.locator, where + ": " + why);
            if (v.equals("present")) return new When(s.locator, v, true, v, false, 0, s.isConst, s.line);
            return new When(s.locator, v, false, v, false, unsigned(v, format, s.locator, where), s.isConst, s.line);
        }
        String why;
        if (wire == Wire.XML) why = XmlCodec.checkFieldLocator(s.locator);
        else if (wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkFieldLocator(s.locator);
        else why = JsonCodec.checkLocator(s.locator);
        if (why != null) throw bad(format, s.locator, where + ": " + why);
        if (v.equals("present")) return new When(s.locator, v, true, v, false, 0, s.isConst, s.line);
        boolean forced = v.startsWith("=");
        return new When(s.locator, v, false, forced ? v.substring(1) : v, forced, 0, s.isConst, s.line);
    }

    private static long unsigned(String v, String format, String locator, String where) {
        if (!v.matches("\\d+")) {
            throw badDirective(format, locator, where + ": a when or const value must be an unsigned decimal integer, got \"" + v + "\"");
        }
        try {
            return Long.parseUnsignedLong(v);
        } catch (NumberFormatException ex) {
            throw badDirective(format, locator, where + ": when value " + v + " does not fit 64 bits");
        }
    }

    private static void arity(String kw, List<String> args, int n, String where, String format) {
        if (args.size() != n) {
            throw bad(format, null, where + ": " + kw + " takes " + n + " argument(s), got " + args.size());
        }
    }

    private static GtException dup(String kw, String where, String format) {
        return bad(format, null, where + ": " + kw + " given twice");
    }

    /**
     * Split a line into tokens. {@code #} starts a comment only at the start of a token, so a locator such as
     * {@code path/#text} is kept, and it is literal inside double quotes. Double quotes wrap a token containing
     * whitespace; there is no escape, so a quoted value cannot contain a double quote.
     */
    static List<String> tokenize(String line, String where) {
        List<String> out = new ArrayList<>();
        int i = 0, n = line.length();
        while (i < n) {
            char c = line.charAt(i);
            if (Character.isWhitespace(c)) { i++; continue; }
            if (c == '#') break;
            if (c == '"') {
                int close = line.indexOf('"', i + 1);
                if (close < 0) throw bad(null, null, where + ": unterminated quote");
                out.add(line.substring(i + 1, close));
                i = close + 1;
                if (i < n && !Character.isWhitespace(line.charAt(i))) {
                    throw bad(null, null, where + ": text directly after closing quote");
                }
            } else {
                int start = i;
                while (i < n && !Character.isWhitespace(line.charAt(i))) i++;
                out.add(line.substring(start, i));
            }
        }
        return out;
    }
}
