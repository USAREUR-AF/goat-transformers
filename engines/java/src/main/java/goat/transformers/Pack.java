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
    public enum Wire { XML, GEOJSON, BITS, PROTOBUF, JSON, TEXT, TLV }

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

    /**
     * One {@code field} line. Exactly one of {@code transform} (the xml, geojson and json wires), {@code text}
     * (the text wire), {@code bits} and {@code pb} is set.
     */
    public static final class Field extends Line {
        public final String key;
        public final Transform transform;
        /** The text wire's transform. */
        final TextTransform text;
        public final BitsTransform bits;
        public final PbTransform pb;
        /** The tlv wire's transform; set once when the line is resolved. */
        TlvTransform tlv;
        /** Text wires: {@code scale} or {@code iscale} (engine-spec 0.15), or null; {@code transform} is then float or int. */
        TextScale scale;
        /** The value table named by {@code via}, or null. */
        public final String via;
        /** bits: the field's bytes are reversed before the transform reads them and after it writes them. */
        public final boolean swap;
        /** bits with ascii: decode also removes trailing spaces. */
        public final boolean trim;
        /** bits: a field any of whose bits lies beyond the input is absent. text: step 5 of writing a record may remove it. */
        public final boolean optional;
        /** The key's declared type; set when the pack is checked against the loaded modules. */
        String keyType;
        /** The values of the {@code absent} option (engine-spec 0.9), or null. */
        Sentinels absent;
        /** {@code via}: canonical native text to model value, and canonical model text to native value. */
        Map<String, Object> viaDecode;
        Map<String, Object> viaEncode;
        /** The key of the {@code with} option (engine-spec 0.18), or null: encode writes the line only when it is held. */
        String with;

        /**
         * True when the line has {@code with} and the entity (inside a group, the item) does not hold its key: a
         * scalar holds when present, a list when present with at least one item (ruling 2 of 0.18). The line is then
         * a line whose key is absent and that has neither a default nor a sentinel.
         */
        boolean suppressed(Entity e) {
            return with != null && !holds(e, with);
        }

        static boolean holds(Entity e, String key) {
            if (e.get(key) != null) return true;
            List<Entity> items = e.list(key);
            return items != null && !items.isEmpty();
        }

        Field(String key, String locator, Transform transform, BitsTransform bits, PbTransform pb,
              String via, boolean swap, boolean trim, boolean optional, int line) {
            this(key, locator, transform, null, bits, pb, via, swap, trim, optional, line);
        }

        Field(String key, String locator, Transform transform, TextTransform text, BitsTransform bits, PbTransform pb,
              String via, boolean swap, boolean trim, boolean optional, int line) {
            super(locator, line);
            this.key = key;
            this.transform = transform;
            this.text = text;
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
            if (scale != null) return scale.wireName();
            return tlv != null ? tlv.name : transform != null ? transform.wireName() : text != null ? text.name : bits != null ? bits.wireName() : pb.wireName();
        }

        /** The model type the transform yields: {@code string}, {@code float} or {@code int}. */
        public String yields() {
            if (scale != null) return scale.yields();
            return tlv != null ? tlv.yields() : transform != null ? transform.yields() : text != null ? text.yields() : bits != null ? bits.yields() : pb.yields();
        }
    }

    /**
     * One {@code element <path>} line of an {@code xml} pack (engine-spec 0.18): encode writes the element at
     * {@code locator}, and each element on the way to it, even when nothing inside it is written. Decode ignores it.
     */
    public static final class Element extends Line {
        Element(String path, int line) { super(path, line); }
    }

    /** A table value that cannot be read as the type its side needs. */
    static final Object UNREADABLE = new Object();

    /**
     * {@code text} written in a pack or a module ({@code default}, the model side of {@code map}) read as
     * {@code type} ({@code string}, {@code int} or {@code float}), or {@link #UNREADABLE}. A number is read as
     * written, without trimming (ruling 18 of 0.18).
     */
    static Object read(String text, String type) {
        if (!type.equals("string") && !text.equals(text.trim())) return UNREADABLE;
        return readTrimmed(text, type);
    }

    /** As {@link #read}, the number trimmed first: a value from a message or a caller, not from a pack. */
    static Object readTrimmed(String text, String type) {
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
        Object v = readTrimmed(text, type);
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
        /** Text wires (engine-spec 0.20): every listed text, each with a leading {@code =} stripped; null for one value. */
        String[] texts;
        /** bits and protobuf (engine-spec 0.20): the listed values as {@code lo, hi} pairs; null for one value. */
        long[] ranges;

        When(String locator, String value, boolean present, String text, boolean forced, long number, boolean isConst, int line) {
            super(locator, line);
            this.isConst = isConst;
            this.value = value;
            this.present = present;
            this.text = text;
            this.forced = forced;
            this.number = number;
        }

        /** True when the line lists more than one value or a range (ruling 3 of 0.20). */
        boolean isList() { return texts != null || ranges != null; }

        /** bits and protobuf: true when the unsigned wire value is listed or lies in a listed range. */
        boolean matches(long v) {
            if (ranges == null) return v == number;
            return inRanges(ranges, v);
        }

        /** Text wires: true when the text equals one of the listed texts. */
        boolean matchesText(String s) {
            if (texts == null) return s.equals(text);
            for (String t : texts) if (s.equals(t)) return true;
            return false;
        }
    }

    /** True when {@code v} (unsigned) lies in one of the {@code lo, hi} pairs of {@code ranges}, both ends included. */
    static boolean inRanges(long[] ranges, long v) {
        for (int i = 0; i < ranges.length; i += 2) {
            if (Long.compareUnsigned(v, ranges[i]) >= 0 && Long.compareUnsigned(v, ranges[i + 1]) <= 0) return true;
        }
        return false;
    }

    /**
     * Read the value list of a {@code when} on {@code bits} or {@code protobuf} (engine-spec 0.20): each item is
     * digits or digits{@code ..}digits, {@code lo ≤ hi}, each end within {@code len} bits. Returns {@code lo, hi}
     * pairs; anything else, or an empty item, is {@code bad-directive}.
     */
    static long[] numericList(String arg, int len, String format, String locator, String where) {
        String[] items = arg.split(",", -1);
        long[] out = new long[items.length * 2];
        for (int i = 0; i < items.length; i++) {
            String it = items[i];
            if (it.isEmpty()) throw badDirective(format, locator, where + ": an empty value in the list \"" + arg + "\"");
            int dots = it.indexOf("..");
            String lo = dots < 0 ? it : it.substring(0, dots);
            String hi = dots < 0 ? it : it.substring(dots + 2);
            long a = listNumber(lo, it, len, format, locator, where);
            long b = listNumber(hi, it, len, format, locator, where);
            if (Long.compareUnsigned(a, b) > 0) {
                throw badDirective(format, locator, where + ": the range " + it + " has its low end above its high end");
            }
            out[2 * i] = a;
            out[2 * i + 1] = b;
        }
        return out;
    }

    private static long listNumber(String v, String item, int len, String format, String locator, String where) {
        if (!v.matches("\\d+")) {
            throw badDirective(format, locator, where + ": a when value is digits or digits..digits, got \"" + item + "\"");
        }
        long n;
        try {
            n = Long.parseUnsignedLong(v);
        } catch (NumberFormatException ex) {
            throw badDirective(format, locator, where + ": when value " + v + " does not fit 64 bits");
        }
        if (len < 64 && Long.compareUnsigned(n, BitsTransform.mask(len)) > 0) {
            throw badDirective(format, locator, where + ": when value " + v + " does not fit " + len + " bits");
        }
        return n;
    }

    /**
     * The lines one set of model keys is read and written through: the common lines plus one kind's, or the body of
     * one {@code group} block (locators then relative to one item).
     */
    public static final class Scope {
        /** {@code field}, {@code when}, {@code const}, {@code group} and gate ({@code if}) lines, in line order. */
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

    /**
     * One gate block {@code if [!]<locator> <value>[,…]} … {@code end} of a fixed-layout bits pack (engine-spec 0.17):
     * its lines exist on the wire only when the gate's bits hold one of the values ({@code !}: none of them).
     */
    public static final class Gate extends Line {
        /** True for {@code if !<locator>}. */
        public final boolean not;
        /** The listed values, as unsigned 64-bit patterns, in the order written. */
        final long[] values;
        /** The block's {@code field}, {@code const} and nested gate lines, and its own {@code default} lines. */
        public final Scope body;
        /** The gate's length in bits. */
        final int len;

        Gate(String locator, boolean not, long[] values, int len, Scope body, int line) {
            super(locator, line);
            this.not = not;
            this.values = values;
            this.len = len;
            this.body = body;
        }

        /** True when the gate's bits, read as unsigned, make the block hold. */
        boolean holds(long v) {
            boolean in = false;
            for (long x : values) if (x == v) { in = true; break; }
            return in != not;
        }

        /**
         * The value encode gives the gate: the first listed value, or with {@code !} the smallest value not listed.
         * Null when a {@code !} list names every value of the gate.
         */
        Long gateValue() {
            if (!not) return values[0];
            // the list holds at most as many values as it has entries, so a value not listed is found within them
            long v = 0;
            for (int tries = 0; tries <= values.length; tries++, v++) {
                if (len < 64 && Long.compareUnsigned(v, BitsTransform.mask(len)) > 0) return null;
                boolean listed = false;
                for (long x : values) if (x == v) { listed = true; break; }
                if (!listed) return v;
            }
            return null;
        }
    }

    /**
     * A value list written in a pack and read as a key's declared type at load (engine-spec 0.20): the values of a
     * {@code requires <key>=…} term or of a {@code case} line. {@code canon} holds their canonical texts once the
     * pack is checked against the modules.
     */
    static final class ValueList {
        final String key;
        final String[] values;
        final int line;
        final String where;
        /** A {@code case} line: the earlier cases of its switch, whose values it may not repeat; null for a {@code requires} term. */
        final List<ValueList> earlierCases;
        Set<String> canon;

        ValueList(String key, String[] values, int line, String where, List<ValueList> earlierCases) {
            this.key = key;
            this.values = values;
            this.line = line;
            this.where = where;
            this.earlierCases = earlierCases;
        }

        boolean isCase() { return earlierCases != null; }

        /** True when the model value's canonical text is one of the listed values. */
        boolean holds(Object v) { return v != null && canon != null && canon.contains(canonText(v)); }
    }

    /** One {@code requires} term: a key that must be present, or with {@code =}, present with one of the listed values. */
    public static final class Require {
        public final String key;
        /** The values after {@code =}, or null for a plain key. */
        final ValueList values;

        Require(String key, ValueList values) {
            this.key = key;
            this.values = values;
        }

        /** True when the entity (or the item) satisfies the term. A plain list key needs at least one item. */
        boolean holds(Entity e) {
            if (values != null) return values.holds(e.get(key));
            if (e.get(key) != null) return true;
            List<Entity> items = e.list(key);
            return items != null && !items.isEmpty();
        }
    }

    /**
     * Read one {@code requires} term: {@code <key>} or {@code <key>=<value>[,<value>…]}, split at the first
     * {@code =} (ruling 4 of 0.20). Records the key in {@code keyRefs} and a value list in {@code lists}.
     */
    static Require requireTerm(String term, int line, String where, String format, List<String[]> keyRefs, List<ValueList> lists) {
        int eq = term.indexOf('=');
        if (eq < 0) {
            keyRefs.add(new String[]{term, null});
            return new Require(term, null);
        }
        String key = term.substring(0, eq), rest = term.substring(eq + 1);
        if (key.isEmpty() || rest.isEmpty()) {
            throw badDirective(format, null, where + ": a requires term is <key> or <key>=<value>[,<value>...], got \"" + term + "\"");
        }
        String[] values = valueItems(rest, where, format);
        keyRefs.add(new String[]{key, null});
        ValueList vl = new ValueList(key, values, line, where, null);
        lists.add(vl);
        return new Require(key, vl);
    }

    /** The items of a comma-separated value list; an empty item is {@code bad-directive} (ruling 16 of 0.20). */
    static String[] valueItems(String text, String where, String format) {
        if (text.isEmpty()) return new String[]{""};   // a lone "" is the empty text
        String[] items = text.split(",", -1);
        for (String it : items) {
            if (it.isEmpty()) throw badDirective(format, null, where + ": an empty value in the list \"" + text + "\"");
        }
        return items;
    }

    /** True when every term holds. */
    static boolean allHold(List<Require> terms, Entity e) {
        for (Require r : terms) if (!r.holds(e)) return false;
        return true;
    }

    /** One message kind: its name, its {@code requires} keys, and its lines after the common lines. */
    public static final class Kind {
        /** The kind's name; null for the single implicit kind of a pack with no {@code kind} line. */
        public final String name;
        public final List<Require> requires;
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

        Kind(String name, List<Require> requires, List<Line> lines, List<When> whens, String root, Map<String, String> defaults) {
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
        /** An {@code if} gate line of a fixed layout: {@code locator} without its {@code !}, {@code arg} the value list. */
        boolean gate;
        boolean not;
        /** An {@code element} line of an xml pack: {@code locator} is its path. */
        boolean element;

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
        final List<Require> requires = new ArrayList<>();
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
    /** bits wire: the bit order as BitsCodec.LSB, MSB or MSB_LSB ({@code bit_order msb-lsb}, engine-spec 0.22). */
    int bitOrder;
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
    /** bits wire with {@code layout sequential}: the lines of the message; null for every other pack. */
    final Seq.Body seq;
    /** {@code layout sequential}: the number of {@code presence} lines, each with its own slot of decode and encode state. */
    final int seqPresences;
    /** text wire: {@code delimiter none}, the record is one field. */
    boolean textNoDelimiter;
    /** text wire: the delimiter, {@code ,} by default. */
    char textDelimiter = ',';
    /** text wire: the start text, or null. */
    String textStart;
    /** text wire: {@code checksum nmea}. */
    boolean textNmea;
    /** bits wire: {@code armor sixbit}, the message is six-bit armored text instead of hex (engine-spec 0.14). */
    boolean armorSixbit;
    /** bits wire: {@code encoding uper}, ASN.1 unaligned PER (engine-spec 0.19). */
    boolean uper;
    /** tlv wire: bytes of a fixed tag, 0 for {@code ber-oid}. */
    int tlvTagSize;
    /** tlv wire: bytes of a fixed length, 0 for {@code ber}. */
    int tlvLengthSize;
    /** tlv wire: the {@code key} bytes, or null. */
    byte[] tlvKey;
    /** tlv wire: {@code checksum sum16 <tag>}. */
    boolean tlvChecksum;
    long tlvChecksumTag = -1;
    /** The {@code requires =} and {@code case} value lists, in line order: read as their keys' types at load. */
    List<ValueList> valueLists = new ArrayList<>();
    /** native code to CoT type token, in file order (first wins). */
    public final Map<String, String> nativeToCot;
    /** CoT type token to native code (first line wins). */
    public final Map<String, String> cotToNative;

    private Pack(String format, String version, Distribution distribution, List<String> sources, List<String> uses,
                 Wire wire, String root, int wordBytes, boolean msbFirst, boolean hasKinds, List<When> commonWhens,
                 List<Kind> kinds, List<Field> fields, List<Line> typed, List<Scope> bodies, List<String[]> keyRefs,
                 Map<String, List<String[]>> tables,
                 boolean kindRoots, Map<String, String> nativeToCot, Map<String, String> cotToNative,
                 Seq.Body seq, int seqPresences) {
        this.seq = seq;
        this.seqPresences = seqPresences;
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

    private String computeTableType(String table) {
        boolean allInt = true, allNum = true;
        for (String[] en : tables.get(table)) {
            if (!Transform.INT_TEXT.matcher(en[1]).matches()) allInt = false;
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
        if (seq != null) {
            Seq.modelKeys(seq, "", out);
            return new ArrayList<>(out);
        }
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
        } else if (l instanceof Gate) {
            // keys inside gate blocks are listed as every other mapped key (ruling 4 of 0.17)
            for (Line b : ((Gate) l).body.lines) modelKeys(b, prefix, out);
        }
    }

    private static GtException bad(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, detail);
    }

    private static GtException badLocator(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_LOCATOR, format, locator, detail);
    }

    private static GtException badDirective(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, detail);
    }

    /** Directives that are not allowed between {@code group} and its {@code end}. */
    private static final Set<String> NOT_IN_GROUP = Set.of("format", "version", "distribution", "source", "uses", "wire",
            "word_bytes", "bit_order", "layout", "root", "map", "kind", "requires", "when", "typemap",
            "delimiter", "start", "checksum", "tag", "key", "length", "armor", "encoding");

    /** The directives of a pack (ruling 5 of 0.11): any other first word is {@code unknown-directive}. */
    static final Set<String> DIRECTIVES = Set.of("format", "version", "distribution", "source", "uses", "wire", "root",
            "field", "when", "const", "kind", "requires", "default", "map", "typemap", "group", "end", "word_bytes",
            "bit_order", "layout", "also", "pad", "align", "presence", "if", "opt", "chain", "fx", "length",
            "delimiter", "start", "checksum", "tag", "key", "armor",
            "element",    // engine-spec 0.18
            "encoding", "ext", "choice", "alt",   // 0.19: directives on every wire (ruling 21)
            "switch", "case", "else",   // engine-spec 0.20
            "count");   // engine-spec 0.21

    /** The directives that take exactly one argument (ruling 5e of 0.11). */
    private static final Set<String> ONE_ARGUMENT = Set.of("format", "version", "distribution", "source", "uses", "wire",
            "root", "kind", "word_bytes", "bit_order", "layout", "pad", "align", "delimiter", "start", "checksum",
            "armor",    // armor: ruling 13 of 0.14
            "element",  // element (0.18): its count does not depend on the layout (step 3 of 5b of 0.11)
            "encoding", "alt");   // 0.19, ruling 23: counted at step 3 of 5b, as armor is

    /** The lines that stand after the {@code wire} line (ruling 5b of 0.11); one before it is {@code missing-wire}. */
    private static final Set<String> AFTER_WIRE = Set.of("root", "field", "when", "const", "group", "end", "word_bytes",
            "bit_order", "layout", "also", "pad", "align", "presence", "if", "opt", "chain", "fx", "length");

    /** Every transform of the specification, by the text before its first {@code :}. */
    private static final Set<String> TRANSFORMS = Set.of("string", "float", "int", "iso8601_ms", "iso8601_short", "bool", "uint", "twos",
            "linscale", "uscale", "sscale", "f32", "f64", "ascii", "pstring", "pvarint", "psint", "pdouble", "pfloat",
            "dec", "dm", "hms", "hms_dmy", "utf8", "hex", "sixbit",
            // engine-spec 0.15
            "uiscale", "siscale", "smag", "smscale", "f32scale", "f64scale", "chars", "octal", "scale", "iscale");

    /** Check 3 of ruling 5b: the number of arguments of the directives whose count does not depend on the layout. */
    private static void lineArity(String kw, List<String> args, String where, String format) {
        int n = args.size();
        boolean ok;
        switch (kw) {
            case "field": ok = n >= 3; break;
            case "when":
            case "const":
            case "default":
            case "typemap": ok = n == 2; break;
            case "map": ok = n == 3; break;
            case "requires": ok = n >= 1; break;
            case "group": ok = n >= 2; break;
            case "if": ok = n >= 1; break;   // ruling 13 of 0.17: an if with no argument is a line check
            case "end":
            case "ext": ok = n == 0; break;   // ext: ruling 23 of 0.19
            case "choice": ok = n == 1 || n == 2; break;   // ruling 23 of 0.19: its values after the file
            // ruling 39 of 0.20: switch and case take one argument, else none (a line check)
            case "switch":
            case "case": ok = n == 1; break;
            case "else": ok = n == 0; break;
            // 0.13 adds `checksum sum16 <tag>`, the tlv form, beside the one-argument form of 5e
            case "checksum": ok = n == 1 || (n == 2 && args.get(0).equals("sum16")); break;
            default: ok = !ONE_ARGUMENT.contains(kw) || n == 1;
        }
        if (!ok) throw bad(format, null, where + ": " + kw + " has the wrong number of arguments (" + n + ")");
    }

    /**
     * Check 7 of ruling 5b: the transform's name, the text before its first {@code :}, is a transform of the
     * specification ({@code unknown-transform}), and its parameters are valid ({@code bad-directive}). Whether the
     * transform is valid on the pack's wire is checked after the file.
     */
    static void checkTransformName(String name, String format, String locator, String where) {
        int c = name.indexOf(':');
        String head = c < 0 ? name : name.substring(0, c);
        if (!TRANSFORMS.contains(head)) {
            throw new GtException(GtException.Code.UNKNOWN_TRANSFORM, format, locator, where + ": unknown transform \"" + name + "\"");
        }
        if (TextTransform.isTextOnlyName(name)) {
            TextTransform.parseTextOnly(name, format, locator, where);
        } else if (head.equals("linscale") || head.equals("uscale") || head.equals("sscale") || BitsTransform.isV015(head)) {
            BitsTransform.parse(name, format, where);
        } else if (TextScale.isName(head)) {
            TextScale.parse(name, format, locator, where);
        } else if (c >= 0) {
            throw badDirective(format, locator, where + ": transform " + head + " takes no parameters, got \"" + name + "\"");
        }
    }

    /**
     * Check 8 of ruling 5b: the form of a fixed-layout locator on its wire (ruling 5a of 0.11). {@code inGroup}: the
     * line is in a group body (a {@code geojson} item is read as {@code json}).
     */
    static void lineCheckLocator(Wire wire, String loc, boolean inGroup, String format, String where) {
        String why;
        switch (wire) {
            case XML: why = XmlCodec.checkFieldLocator(loc); break;
            case JSON: why = loc.equals(".") ? null : JsonCodec.checkLocator(loc); break;
            case GEOJSON: why = loc.equals(".") ? null : inGroup ? JsonCodec.checkLocator(loc) : GeoJsonCodec.checkFieldLocator(loc); break;
            case PROTOBUF: why = loc.equals(".") ? null : ProtobufCodec.checkFieldLocator(loc); break;
            case TLV: return;   // 0.13: a tlv path is checked after the file, and its failures are bad-directive
            case BITS:
                // a bit length as the locator of a fixed-layout pack stays bad-directive (resolved after the file);
                // so does a UPER locator outside a UPER pack (ruling 9 of 0.19, checked after the file)
                if (Seq.isUperLocator(loc)) return;
                if (loc.startsWith("until:")) return;   // a sequential locator (0.22): refused after the file here
                why = Transform.UNSIGNED.matcher(loc).matches() ? null : BitsCodec.checkLocator(loc);
                break;
            default:
                if (TextCodec.parseLocator(loc) == null) {
                    throw badDirective(format, loc, where + ": a text locator is <i>, <i>:<from>:<len> (len from 1) or <i>+<j>, got \"" + loc + "\"");
                }
                why = null;
        }
        if (why != null) throw badLocator(format, loc, where + ": " + why);
    }

    /** The header lines a pack has once (check 5 of ruling 5b). */
    private static final Set<String> HEADERS = Set.of("format", "version", "wire", "distribution");

    private static final Set<String> WIRES = Set.of("xml", "geojson", "json", "bits", "protobuf", "text", "tlv");

    /** Check 8 for a {@code group} line of a fixed-layout pack: the form of its locator (ruling 5a of 0.11). */
    private static void lineCheckGroupLocator(Wire wire, String loc, boolean inGroup, String format, String where) {
        String why;
        switch (wire) {
            // xml: the forms 5a names (an empty step, an empty attribute name, a step after @name or #text); a group
            // locator that is otherwise not valid for its wire (`@a`) is bad-directive after the file (ruling 37 of 0.21)
            case XML: why = xmlGroupForm(loc); break;
            case JSON: why = JsonCodec.checkLocator(loc); break;
            case GEOJSON: why = inGroup ? JsonCodec.checkLocator(loc) : GeoJsonCodec.checkGroupLocator(loc); break;
            // protobuf: `rest` and `last` are a group locator not valid for the wire, bad-directive after the file
            // (ruling 37 of 0.21), not the bad-locator of 5a
            case PROTOBUF: why = loc.equals("rest") || loc.equals("last") ? null : ProtobufCodec.checkFieldLocator(loc); break;
            // bits: 5a names field, when and const lines only, and a group with a sequential form (`while`) in a
            // fixed-layout pack stays bad-directive; text: its group form is checked after the file
            default: why = null;
        }
        if (why != null) throw badLocator(format, loc, where + ": " + why);
    }

    /**
     * The code of a {@code stop} option or an {@code until:} locator (engine-spec 0.22): plain decimal digits, below
     * {@code 2^w} of the {@code chars} set; only {@code chars:<set>} takes one. Anything else is bad-directive.
     */
    static int stopCode(String code, BitsTransform bt, String format, String locator, String where) {
        if (bt == null || !bt.isCharSet()) {
            throw badDirective(format, locator, where + ": a terminator code is for a chars:<set> field only");
        }
        if (!Transform.UNSIGNED.matcher(code).matches()) {
            throw badDirective(format, locator, where + ": a terminator code is plain decimal digits, got \"" + code + "\"");
        }
        java.math.BigInteger n = new java.math.BigInteger(code);
        if (n.bitLength() > bt.charWidth()) {
            throw badDirective(format, locator, where + ": terminator code " + code + " does not fit " + bt.charWidth() + " bits");
        }
        return n.intValue();
    }

    /** The 5a forms of an xml locator on a {@code group} line, or null. */
    private static String xmlGroupForm(String loc) {
        boolean after = false;
        for (String seg : loc.split("/", -1)) {
            if (seg.isEmpty()) return "an xml locator has an empty step: " + loc;
            if (seg.equals("@")) return "an xml locator has an empty attribute name: " + loc;
            if (after) return "an xml locator has a step after @name or #text: " + loc;
            if (seg.startsWith("@") || seg.equals("#text")) after = true;
        }
        return null;
    }

    /** Check 8 for a {@code when} or {@code const} line of a sequential pack: its bit length (ruling 5a of 0.11). */
    private static void lineCheckSeqLocator(String loc, String format, String where) {
        // a UPER locator on a when or const line is refused after the file (ruling 26 of 0.19)
        if (Seq.isUperLocator(loc)) return;
        if (loc.indexOf(':') >= 0) {
            // an earlier version's case, bad-directive (ruling 5a)
            throw badDirective(format, loc, where + ": a sequential pack takes a bit length, not a position: " + loc);
        }
        if (!Transform.UNSIGNED.matcher(loc).matches()) throw badLocator(format, loc, where + ": a bit length, got \"" + loc + "\"");
        if (loc.matches("0+")) throw badLocator(format, loc, where + ": a bit length of 0");
    }

    /**
     * Checks 7 to 10 of ruling 5b for a {@code field} line of a sequential pack: the transform, the bit length, the
     * syntax of the options, and the values of an {@code absent} option on a field of at most 64 bits.
     */
    private static void lineCheckSeqField(List<String> args, String format, String where) {
        String loc = args.get(1);
        checkTransformName(args.get(2), format, loc, where);
        if (loc.startsWith("until:")) {
            // 0.22: the code, the transform it needs and the options it refuses are checked after the file
            optionSyntax(args, format, loc, where);
            return;
        }
        if (Seq.isUperLocator(loc)) {
            // 0.19: the form of a UPER locator, whether its transform and options fit it, and whether the pack has
            // encoding uper (ruling 9) are checked after the file; only the option syntax is a line check here
            optionSyntax(args, format, loc, where);
            return;
        }
        lineCheckSeqLocator(loc, format, where);
        String absent = optionSyntax(args, format, loc, where);
        if (absent == null) return;
        String digits = loc.replaceFirst("^0+(?=.)", "");
        if (digits.length() > 2 || Integer.parseInt(digits) > 64) return;   // ruling 4d: checked after the file
        Sentinels.integers(absent, Integer.parseInt(digits), format, loc, where);
    }

    /** Check 9: the options this specification has, each once, each with its argument. Returns the absent argument. */
    private static String optionSyntax(List<String> args, String format, String loc, String where) {
        String absent = null;
        Set<String> seen = new HashSet<>();
        for (int i = 3; i < args.size(); i++) {
            String o = args.get(i);
            switch (o) {
                case "absent":
                case "via":
                case "with":   // engine-spec 0.18
                case "stop":   // engine-spec 0.22
                    if (!seen.add(o)) throw badDirective(format, loc, where + ": " + o + " given twice");
                    if (i + 1 >= args.size()) throw badDirective(format, loc, where + ": " + o + " takes an argument");
                    String a = args.get(++i);
                    if (o.equals("absent")) absent = a;
                    break;
                case "swap":
                case "trim":
                case "optional":
                    if (!seen.add(o)) throw badDirective(format, loc, where + ": " + o + " given twice");
                    break;
                default:
                    throw badDirective(format, loc, where + ": unknown field option \"" + o + "\"");
            }
        }
        return absent;
    }

    /**
     * Checks 7 to 10 of ruling 5b for a {@code field} line of a fixed-layout pack: the transform, the locator, the
     * field options, and the values of an {@code absent} option (not on a {@code bits} field above 64 bits, whose
     * length the check after the file refuses).
     */
    private static void lineCheckField(List<String> args, Wire wire, boolean inGroup, String format, String where) {
        String loc = args.get(1), tname = args.get(2);
        if (wire == Wire.TLV) {
            // 0.13: on tlv the transform (ruling 8), the path (bad-directive, not a 5a form) and absent (ruling 10)
            // are checked after the file; only the option syntax of check 9 is a line check
            optionSyntax(args, format, loc, where);
            return;
        }
        checkTransformName(tname, format, loc, where);
        lineCheckLocator(wire, loc, inGroup, format, where);
        String absent = optionSyntax(args, format, loc, where);
        // whether an option fits the wire or the transform is checked after the file (ruling 5b, step 9)
        if (absent == null) return;
        switch (wire) {
            case BITS: {
                if (!loc.contains(":") || Seq.isUperLocator(loc) || loc.startsWith("until:")) return;   // refused after the file
                int len = BitsCodec.parseLoc(loc)[2];
                if (len > 64) return;                         // ruling 4d: the length check after the file reports it
                Sentinels.integers(absent, len, format, loc, where);
                return;
            }
            case PROTOBUF: {
                PbTransform pb = PbTransform.byName(tname);
                if (pb == null) return;                       // a transform of another wire, refused after the file
                if (pb.wireType() == 2) Sentinels.texts(absent, false, format, loc, where);
                else Sentinels.integers(absent, pb.wireType() == 5 ? 32 : 64, format, loc, where);
                return;
            }
            case XML:
                Sentinels.texts(absent, true, format, loc, where);
                return;
            case TEXT:
                return;   // absent does not fit the text wire (ruling 16 of 0.10): checked after the file
            default: {
                Sentinels sv = Sentinels.json(absent, tname.equals("bool"), format, loc, where);
                if (wire == Wire.GEOJSON && !inGroup && GeoJsonCodec.coordIndex(loc) >= 0) {
                    for (Object v : sv.json) {
                        if (!(v instanceof Json.Num)) {
                            throw badDirective(format, loc, where + ": absent: a coordinate takes only number text as a sentinel");
                        }
                    }
                }
            }
        }
    }

    /** The only lines allowed inside a gate block (engine-spec 0.17, Load errors). */
    private static final Set<String> IN_GATE = Set.of("field", "const", "default", "if", "end");

    /** What {@link #resolve} needs to know about the pack, and what it collects. */
    private static final class Ctx {
        Wire wire;
        String format;
        String source;
        int wordBytes;   // 0 when not given
        /** text wire: the fields of one item of the group being resolved; 0 outside a group. */
        int itemFields;
        /** tlv wire: bytes of a fixed tag (0 for ber-oid), and the checksum tag (-1 for none). */
        int tlvTagSize;
        long tlvChecksumTag = -1;
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
        // armor lines {value, line} (each checked once the file is read, ruling 10 of 0.10), the first kind line, and
        // the first `length ... whole` line of a sequential pack
        List<String[]> armorDirs = new ArrayList<>();
        // encoding lines {value, line, after a kind} (0.19), checked once the file is read; in a fixed-layout bits
        // pack, the first UPER line and the ext and choice blocks still open
        List<String[]> encodingDirs = new ArrayList<>();
        int fixedUperLine = 0;
        // for each such block, the number of group and gate blocks open when it began: an `end` closes it only then
        java.util.ArrayDeque<Integer> fixedUperOpen = new java.util.ArrayDeque<>();
        int firstKindLine = 0, wholeLine = 0;
        // text wire directives: {value, line}, or null when not given
        String[] delimiterDir = null, startDir = null, checksumDir = null;
        // tlv wire directives (tag, length, key, checksum sum16), checked once the file is read: {kw, args, line, after a kind}
        List<Object[]> tlvDirs = new ArrayList<>();
        Distribution distribution = null;
        List<String> sources = new ArrayList<>();
        List<String> uses = new ArrayList<>();
        KindSpec common = new KindSpec(null, 0);
        List<KindSpec> kindSpecs = new ArrayList<>();
        Set<String> kindNames = new HashSet<>();
        KindSpec cur = common;
        java.util.ArrayDeque<LineSpec> open = new java.util.ArrayDeque<>();   // the group blocks not yet ended
        List<String[]> keyRefs = new ArrayList<>();
        List<ValueList> valueLists = new ArrayList<>();
        LinkedHashMap<String, String> n2c = new LinkedHashMap<>();
        LinkedHashMap<String, String> c2n = new LinkedHashMap<>();
        LinkedHashMap<String, List<String[]>> tables = new LinkedHashMap<>();
        String[] lines = text.split("\r?\n", -1);
        // `layout` may stand anywhere in the file and decides how every line is read, so it is looked for first.
        boolean sequential = false;
        for (String l : lines) {
            String t = l.trim();
            if (!t.startsWith("layout")) continue;
            List<String> tok;
            try {
                tok = tokenize(l, source);
            } catch (GtException ex) {
                break;   // reported with its line number when the file is read
            }
            if (tok.size() == 2 && tok.get(0).equals("layout")) {
                sequential = tok.get(1).equals("sequential");
                break;
            }
        }
        // On wire tlv every transform check runs after the file is read (ruling 8 of 0.13), so the parameters of a
        // text transform are not checked as the file is read there.
        boolean tlvWire = false;
        for (String l : lines) {
            if (!l.trim().startsWith("wire")) continue;
            List<String> tok;
            try {
                tok = tokenize(l, source);
            } catch (GtException ex) {
                break;
            }
            if (tok.size() == 2 && tok.get(0).equals("wire")) {
                tlvWire = tok.get(1).equals("tlv");
                break;
            }
        }
        // A line `encoding uper` (0.19): the UPER lines of a sequential pack are then checked as the file is read.
        boolean uperHint = false;
        for (String l : lines) {
            if (!l.trim().startsWith("encoding")) continue;
            try {
                if (tokenize(l, source).equals(List.of("encoding", "uper"))) uperHint = true;
            } catch (GtException ex) {
                // reported with its line number when the file is read
            }
        }
        Seq.Parser seq = sequential ? new Seq.Parser(source, keyRefs, uperHint, valueLists) : null;
        String layout = null;
        boolean listedSeen = false;   // a line that must follow the wire line, other than layout, has been read
        Set<String> headers = new HashSet<>();   // the header lines read so far, for check 5
        // The first failure that is not a line check (steps 1 to 10 of ruling 5b): it is reported after the file, so
        // a later line's own line check wins over it. The lines after it are still read, their failures dropped.
        RuntimeException deferred = null;
        int firstGate = 0;   // the line of the first gate block, 0 when there is none
        int firstElement = 0;   // the line of the first element line, 0 when there is none
        for (int i = 0; i < lines.length; i++) {
            int ln = i + 1;
            String where = source + ":" + ln;
            // The line checks of ruling 5b of 0.11, in their order: the quote, the directive, the number of
            // arguments, missing-wire, then (in the switch) a repeated header line and the wire and distribution values.
            List<String> tok = tokenize(lines[i], where);
            if (tok.isEmpty()) continue;
            String kw = tok.get(0);
            List<String> args = tok.subList(1, tok.size());
            // ruling 11 of 0.13: a key line of any other count is the model-module form, unknown in a pack
            if (!DIRECTIVES.contains(kw) || (kw.equals("key") && args.size() != 1)) {
                throw new GtException(GtException.Code.UNKNOWN_DIRECTIVE, format, null, where + ": unknown directive \"" + kw + "\"");
            }
            lineArity(kw, args, where, format);
            if (AFTER_WIRE.contains(kw)) {
                if (wire == null) {
                    throw new GtException(GtException.Code.MISSING_WIRE, format, null,
                            where + ": " + kw + " stands before the wire line");
                }
            }
            // check 5: a repeated header line; check 6: the wire and distribution values
            if (HEADERS.contains(kw) && !headers.add(kw)) throw dup(kw, where, format);
            if (kw.equals("wire") && !WIRES.contains(args.get(0))) {
                throw new GtException(GtException.Code.UNKNOWN_WIRE, format, null, where + ": unknown wire \"" + args.get(0) + "\"");
            }
            if (kw.equals("distribution") && Distribution.byToken(args.get(0)) == null) {
                throw bad(format, null, where + ": distribution must be public or controlled, got \"" + args.get(0) + "\"");
            }
            // checks 7 to 10
            if (kw.equals("field") && seq == null) {
                lineCheckField(args, wire, !open.isEmpty(), format, where);
            } else if (kw.equals("field")) {
                lineCheckSeqField(args, format, where);
            } else if ((kw.equals("when") || kw.equals("const")) && seq == null) {
                lineCheckLocator(wire, args.get(0), !open.isEmpty(), format, where);
            } else if (kw.equals("when") || kw.equals("const")) {
                lineCheckSeqLocator(args.get(0), format, where);
            } else if (kw.equals("group") && seq == null) {
                lineCheckGroupLocator(wire, args.get(1), !open.isEmpty(), format, where);
            }
            try {
            if (AFTER_WIRE.contains(kw)) {
                if (kw.equals("layout")) {
                    if (args.get(0).equals("sequential") && listedSeen) {
                        throw badDirective(format, null, where + ": layout sequential stands after a line it must precede");
                    }
                } else {
                    listedSeen = true;
                }
            }
            if (kw.equals("kind") && firstKindLine == 0) firstKindLine = ln;
            if (seq != null && kw.equals("length") && args.contains("whole") && wholeLine == 0) wholeLine = ln;
            if (seq != null) {
                if (Seq.LINES.contains(kw)) {
                    seq.line(kw, args, ln, where, format);
                    continue;
                }
                if (seq.inBlock() && NOT_IN_GROUP.contains(kw)) {
                    throw badDirective(format, null, where + ": " + kw + " is not allowed inside a block");
                }
                if (kw.equals("word_bytes")) {
                    throw badDirective(format, null, where + ": word_bytes is not used in a sequential pack");
                }
            } else if (Seq.UPER_ONLY.contains(kw) || (kw.equals("end") && !fixedUperOpen.isEmpty()
                    && fixedUperOpen.peek() == open.size())) {
                // a UPER line outside a sequential pack, on any wire: bad-directive once the file is read (rulings 9
                // and 21 of 0.19)
                if (fixedUperLine == 0) fixedUperLine = ln;
                if (kw.equals("ext") || kw.equals("choice")) fixedUperOpen.push(open.size());
                if (kw.equals("end")) fixedUperOpen.pop();
                continue;
            } else if (Seq.SEQUENTIAL_ONLY.contains(kw) && !kw.equals("length") && !kw.equals("if")) {
                // `length` is also the tlv directive (0.13), and `if` the gate block of a fixed layout (0.17)
                throw badDirective(format, null, where + ": " + kw + " is a line of a pack with layout sequential");
            }
            if (!open.isEmpty() && open.peek().gate && !IN_GATE.contains(kw)) {
                throw badDirective(format, null, where + ": " + kw + " is not allowed inside an if block");
            }
            if (!open.isEmpty() && NOT_IN_GROUP.contains(kw)) {
                throw badDirective(format, null, where + ": " + kw + " is not allowed inside a group");
            }
            BodySpec body = open.isEmpty() ? cur : open.peek().body;
            if (kw.equals("tag") || kw.equals("key") || kw.equals("length")
                    || (kw.equals("checksum") && !args.isEmpty() && args.get(0).equals("sum16"))) {
                // `length` here is the tlv directive: a pack with layout sequential reads its length lines above
                tlvDirs.add(new Object[]{kw, new ArrayList<>(args), ln, cur != common});
                continue;
            }
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
                case "delimiter":
                case "start":
                case "checksum": {
                    arity(kw, args, 1, where, format);
                    String[] had = kw.equals("delimiter") ? delimiterDir : kw.equals("start") ? startDir : checksumDir;
                    if (had != null) throw badDirective(format, null, where + ": " + kw + " given twice");
                    if (cur != common) throw badDirective(format, null, where + ": " + kw + " after the first kind line");
                    String v = args.get(0);
                    String[] dir = {v, Integer.toString(ln)};
                    if (kw.equals("delimiter")) {
                        if (!v.equals("none") && (v.length() != 1 || v.charAt(0) < 0x21 || v.charAt(0) > 0x7e || v.charAt(0) == '"')) {
                            throw badDirective(format, null, where + ": delimiter takes one character from 0x21 to 0x7E other than \" or none, got \"" + v + "\"");
                        }
                        delimiterDir = dir;
                    } else if (kw.equals("start")) {
                        boolean ok = !v.isEmpty();
                        for (int k = 0; k < v.length(); k++) ok &= v.charAt(k) >= 0x21 && v.charAt(k) <= 0x7e;
                        if (!ok) throw badDirective(format, null, where + ": start takes one or more characters from 0x21 to 0x7E, got \"" + v + "\"");
                        startDir = dir;
                    } else {
                        if (!v.equals("none") && !v.equals("nmea")) {
                            throw badDirective(format, null, where + ": checksum takes none or nmea, got \"" + v + "\"");
                        }
                        checksumDir = dir;
                    }
                    break;
                }
                case "wire":
                    arity(kw, args, 1, where, format);
                    if (wire != null) throw dup(kw, where, format);
                    switch (args.get(0)) {
                        case "xml": wire = Wire.XML; break;
                        case "geojson": wire = Wire.GEOJSON; break;
                        case "bits": wire = Wire.BITS; break;
                        case "protobuf": wire = Wire.PROTOBUF; break;
                        case "json": wire = Wire.JSON; break;
                        case "text": wire = Wire.TEXT; break;
                        case "tlv": wire = Wire.TLV; break;
                        default:
                            throw new GtException(GtException.Code.UNKNOWN_WIRE, format, null, where + ": unknown wire \"" + args.get(0) + "\"");
                    }
                    break;
                case "word_bytes":
                    arity(kw, args, 1, where, format);
                    if (wordBytes != null) throw dup(kw, where, format);
                    {
                        Long wb = Transform.parseUnsigned(args.get(0), 31);
                        if (wb == null || wb < 1) {
                            throw bad(format, null, where + ": word_bytes must be a positive unsigned decimal integer, got \"" + args.get(0) + "\"");
                        }
                        wordBytes = (int) (long) wb;
                    }
                    break;
                case "layout":
                    arity(kw, args, 1, where, format);
                    if (layout != null) throw dup(kw, where, format);
                    if (!args.get(0).equals("fixed") && !args.get(0).equals("sequential")) {
                        throw badDirective(format, null, where + ": layout must be fixed or sequential, got \"" + args.get(0) + "\"");
                    }
                    layout = args.get(0);
                    break;
                case "encoding":
                    encodingDirs.add(new String[]{args.size() == 1 ? args.get(0) : null, Integer.toString(ln),
                            firstKindLine != 0 ? "after" : null});
                    break;
                case "armor":
                    if (!open.isEmpty()) throw badDirective(format, null, where + ": armor is not allowed inside a group");
                    armorDirs.add(new String[]{args.size() == 1 ? args.get(0) : null, Integer.toString(ln),
                            firstKindLine != 0 ? "after" : null});
                    break;
                case "bit_order":
                    arity(kw, args, 1, where, format);
                    if (bitOrder != null) throw dup(kw, where, format);
                    if (!args.get(0).equals("lsb") && !args.get(0).equals("msb") && !args.get(0).equals("msb-lsb")) {
                        throw badDirective(format, null, where + ": bit_order must be lsb, msb or msb-lsb, got \"" + args.get(0) + "\"");
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
                    if (args.contains("with")) throw badDirective(format, null, where + ": with is not an option of a const line");
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
                    for (String k : args) cur.requires.add(requireTerm(k, ln, where, format, keyRefs, valueLists));
                    break;
                case "element": {
                    // engine-spec 0.18: one path of element names under the root (ruling 13)
                    if (!open.isEmpty()) throw badDirective(format, null, where + ": element is not allowed inside a group");
                    if (args.size() != 1) throw badDirective(format, null, where + ": element takes one path, got " + args.size());
                    String path = args.get(0);
                    for (String step : path.split("/", -1)) {
                        // a step is an element name: no `@` or `#` anywhere in it (ruling 16 of 0.18)
                        if (step.isEmpty() || step.indexOf('@') >= 0 || step.indexOf('#') >= 0) {
                            throw badDirective(format, path, where + ": element takes a path of element names, got \"" + path + "\"");
                        }
                    }
                    LineSpec el = new LineSpec(null, path, null, null, false, ln);
                    el.element = true;
                    body.lines.add(el);
                    if (firstElement == 0) firstElement = ln;
                    break;
                }
                case "when": {
                    // a third token (`1, 2`) is bad-directive on every wire (ruling 23 of 0.20)
                    if (args.size() > 2) {
                        throw badDirective(format, null, where + ": a when value list has no spaces: a third token after the locator");
                    }
                    arity(kw, args, 2, where, format);
                    body.lines.add(new LineSpec(null, args.get(0), args.get(1), null, false, ln));
                    break;
                }
                case "field": {
                    if (args.size() < 3) throw bad(format, null, where + ": field takes at least 3 arguments, got " + args.size());
                    String key = args.get(0);
                    // the parameters of a text transform are checked as the file is read (ruling 2 of 0.10)
                    if (!tlvWire && TextTransform.isTextOnlyName(args.get(2))) TextTransform.parseTextOnly(args.get(2), format, args.get(1), where);
                    body.lines.add(new LineSpec(key, args.get(1), args.get(2), new ArrayList<>(args.subList(3, args.size())), false, ln));
                    keyRefs.add(new String[]{key, args.get(1)});
                    String with = withKey(args.subList(3, args.size()), args.get(1), where, format);
                    if (with != null) keyRefs.add(new String[]{with, args.get(1)});
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
                case "if": {
                    // a gate block of the fixed layout (engine-spec 0.17); the sequential `if` is read by Seq
                    LineSpec g = gateLine(args, ln, where, format);
                    if (firstGate == 0) firstGate = ln;
                    g.body = new BodySpec();
                    body.lines.add(g);
                    open.push(g);
                    break;
                }
                case "end":
                    arity(kw, args, 0, where, format);
                    if (open.isEmpty()) throw badDirective(format, null, where + ": end with no open group or if block");
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
            } catch (GtException ex) {
                if (deferred == null) deferred = ex;
            } catch (RuntimeException ex) {
                if (deferred == null) throw ex;   // a defect, not a cause: never hidden
            }
        }
        // After the file (ruling 5b of 0.11): missing-format, missing-version, missing-wire; then the checks that need
        // the whole file; then the order of 0.4 from missing-distribution on.
        if (format == null) throw new GtException(GtException.Code.MISSING_FORMAT, null, null, source + ": no format line");
        if (version == null) throw new GtException(GtException.Code.MISSING_VERSION, format, null, source + ": no version line");
        if (wire == null) throw new GtException(GtException.Code.MISSING_WIRE, format, null, source + ": no wire line");
        if (deferred != null) throw deferred;
        if (!open.isEmpty()) {
            LineSpec g = open.peek();
            throw badDirective(format, g.locator, source + ":" + g.line + ": " + (g.gate ? "if " + g.locator : "group " + g.key) + " has no end");
        }
        // Checks that need the whole file run here, before missing-distribution (ruling 25 of 0.5).
        if (fixedUperLine != 0) {
            throw badDirective(format, null, source + ":" + fixedUperLine + ": ext, choice and alt are lines of a pack with encoding uper (wire bits, layout sequential)");
        }
        Seq.Body seqRoot = null;
        if (seq != null) {
            if (wire != null && wire != Wire.BITS) {
                throw badDirective(format, null, source + ": layout sequential is for the bits wire only");
            }
            seqRoot = seq.finish(tables, format);
        } else if (layout != null && wire != null && wire != Wire.BITS) {
            throw badDirective(format, null, source + ": layout is for the bits wire only");
        }
        boolean hasKinds = seqRoot != null ? seqRoot.hasKinds : !kindSpecs.isEmpty();
        if (!hasKinds) {
            for (LineSpec s : common.lines) {
                if (s.key == null && !s.isConst && !s.gate && !s.element) {
                    throw badDirective(format, s.locator, source + ":" + s.line + ": when line in a pack with no kind line");
                }
            }
        }
        if (firstElement != 0 && wire != null && wire != Wire.XML) {
            throw badDirective(format, null, source + ":" + firstElement + ": element is for the xml wire only");
        }
        if (firstGate != 0 && wire != null && wire != Wire.BITS) {
            throw badDirective(format, null, source + ":" + firstGate + ": an if block of a fixed layout is for the bits wire only");
        }
        if (bitOrder != null && wire != null && wire != Wire.BITS) {
            throw badDirective(format, null, source + ":" + bitOrderLine + ": bit_order is for the bits wire only");
        }
        // armor (0.14): on the bits wire only, at most once, before the first kind, hex or sixbit; sixbit needs
        // bit_order msb and refuses `length ... whole`. Checked after the file is read, wherever the wire line stands.
        boolean armorSixbit = false;
        for (int k = 0; k < armorDirs.size(); k++) {
            String[] d = armorDirs.get(k);
            String at = source + ":" + d[1] + ": ";
            if (k > 0) throw badDirective(format, null, at + "armor given twice");
            if (wire != null && wire != Wire.BITS) throw badDirective(format, null, at + "armor is for the bits wire only");
            if (d[2] != null) throw badDirective(format, null, at + "armor after the first kind line");
            if (d[0] == null || (!d[0].equals("hex") && !d[0].equals("sixbit"))) {
                throw badDirective(format, null, at + "armor takes hex or sixbit");
            }
            armorSixbit = d[0].equals("sixbit");
            if (armorSixbit && !"msb".equals(bitOrder)) throw badDirective(format, null, at + "armor sixbit needs bit_order msb");
            if (armorSixbit && wholeLine != 0) {
                throw badDirective(format, null, source + ":" + wholeLine + ": length ... whole in a pack with armor sixbit: the armored text has no whole-byte length");
            }
        }
        // encoding (0.19): on the bits wire only, at most once, before the first kind, none or uper; uper needs
        // layout sequential and bit_order msb and refuses armor sixbit. Then the UPER lines need encoding uper.
        boolean uper = false;
        for (int k = 0; k < encodingDirs.size(); k++) {
            String[] d = encodingDirs.get(k);
            String at = source + ":" + d[1] + ": ";
            if (wire != null && wire != Wire.BITS) throw badDirective(format, null, at + "encoding is for the bits wire only");
            if (k > 0) throw badDirective(format, null, at + "encoding given twice");
            if (d[2] != null) throw badDirective(format, null, at + "encoding after the first kind line");
            if (d[0] == null || (!d[0].equals("none") && !d[0].equals("uper"))) {
                throw badDirective(format, null, at + "encoding takes none or uper");
            }
            uper = d[0].equals("uper");
            if (uper && seq == null) throw badDirective(format, null, at + "encoding uper needs layout sequential");
            if (uper && !"msb".equals(bitOrder)) throw badDirective(format, null, at + "encoding uper needs bit_order msb");
            if (uper && armorSixbit) throw badDirective(format, null, at + "encoding uper and armor sixbit in one pack");
        }
        if (seq != null && seq.uperLine != 0 && !uper) {
            throw badDirective(format, null, source + ":" + seq.uperLine
                    + ": UPER locators, ext, choice, alt and group ... size are lines of a pack with encoding uper");
        }
        if (seq != null && seq.uperWhy != null) throw badDirective(format, null, seq.uperWhy);
        // Checks that need the wire run after the file is read, wherever the wire line stands (ruling 10 of 0.10).
        if (wire != null && wire != Wire.TEXT) {
            for (String[] d : new String[][]{delimiterDir, startDir, checksumDir}) {
                if (d != null) throw badDirective(format, null, source + ":" + d[1] + ": delimiter, start and checksum are for the text wire only");
            }
        }
        int[] tlvSizes = wire == null ? null : tlvDirectives(tlvDirs, wire, checksumDir, format, source);
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
        byte[] tlvKey = null;
        if (wire == Wire.TLV) {
            ctx.tlvTagSize = tlvSizes[0];
            for (Object[] d : tlvDirs) {
                @SuppressWarnings("unchecked") List<String> a = (List<String>) d[1];
                if (d[0].equals("checksum")) ctx.tlvChecksumTag = Long.parseLong(a.get(1));
                if (d[0].equals("key")) {
                    String h = a.get(0);
                    tlvKey = new byte[h.length() / 2];
                    for (int k = 0; k < tlvKey.length; k++) tlvKey[k] = (byte) Integer.parseInt(h.substring(2 * k, 2 * k + 2), 16);
                }
            }
        }
        List<Line> commonLines = new ArrayList<>();
        List<When> commonWhens = new ArrayList<>();
        List<Kind> kinds = new ArrayList<>();
        if (seq != null) {
            ctx.fields.addAll(seq.fields);
            ctx.typed.addAll(seq.typed);
            ctx.bodies.addAll(seq.scopes);
        } else if (wire != null) {
            Set<String> commonLists = new HashSet<>();
            for (LineSpec s : common.lines) {
                Line l = resolve(s, ctx, false);
                commonLines.add(l);
                if (l instanceof When && !((When) l).isConst) commonWhens.add((When) l);
                if (l instanceof Group) oneGroupPerList(commonLists, (Group) l, ctx);
            }
            if (!hasKinds) {
                notThroughAGroup(commonLines, ctx);
                if (wire == Wire.TLV) TlvCodec.checkScope(commonLines, format, source);
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
                notThroughAGroup(all, ctx);
                if (wire == Wire.TLV) TlvCodec.checkScope(all, format, source);
                LinkedHashMap<String, String> defaults = new LinkedHashMap<>(common.defaults);
                defaults.putAll(ks.defaults);
                kinds.add(new Kind(ks.name, ks.requires, all, whens, ks.root != null ? ks.root : root, defaults));
            }
            if (wire == Wire.TEXT) {
                TextCodec.checkPack(kinds, ctx.bodies, delimiterDir == null ? "," : delimiterDir[0],
                        startDir == null ? null : startDir[0], checksumDir != null && checksumDir[0].equals("nmea"), format, source);
            }
            if (wire == Wire.BITS && wordBytes != null) {
                // The layout of each scope: common plus one kind (group bodies were checked as they were resolved).
                for (Kind k : kinds) BitsCodec.prepare(k.scope, wb, 0, format, source);
            }
        }
        if (wire == Wire.XML) {
            for (Kind k : kinds) {
                if (k.root == null) {
                    throw new GtException(GtException.Code.MISSING_ROOT, format, null,
                            source + ": wire xml needs a root line, in the pack or in every kind");
                }
            }
        }
        if (wire != Wire.XML && root != null) throw bad(format, null, source + ": root is xml only");
        if (wire == Wire.BITS && wordBytes == null && seq == null) throw bad(format, null, source + ": a fixed-layout bits pack needs a word_bytes line");
        if (wire != Wire.BITS && wordBytes != null) throw bad(format, null, source + ": word_bytes is bits only");
        boolean mapsType = false;
        for (String[] r : keyRefs) if (r[1] != null && r[0].equals("type")) mapsType = true;
        if (!n2c.isEmpty() && !mapsType) throw bad(format, null, source + ": typemap without a field for model key type");
        if (distribution == null) {
            throw new GtException(GtException.Code.MISSING_DISTRIBUTION, format, null, source + ": pack has no distribution line");
        }
        if (sources.isEmpty()) {
            throw new GtException(GtException.Code.MISSING_SOURCE, format, null, source + ": pack has no source line");
        }

        // Report in file order, as the 0.4 checks do.
        ctx.fields.sort((a, b) -> Integer.compare(a.line, b.line));
        ctx.typed.sort((a, b) -> Integer.compare(a.line, b.line));
        valueLists.sort((a, b) -> Integer.compare(a.line, b.line));
        Pack pack = new Pack(format, version, distribution, sources, uses, wire, root, wb, "msb".equals(bitOrder), hasKinds,
                commonWhens, kinds, ctx.fields, ctx.typed, ctx.bodies, keyRefs, tables, kindRoots, n2c, c2n,
                seqRoot, seq == null ? 0 : seq.presences);
        pack.armorSixbit = armorSixbit;
        pack.bitOrder = "msb".equals(bitOrder) ? BitsCodec.MSB : "msb-lsb".equals(bitOrder) ? BitsCodec.MSB_LSB : BitsCodec.LSB;
        pack.uper = uper;
        pack.valueLists = valueLists;
        if (wire == Wire.TEXT) {
            String d = delimiterDir == null ? "," : delimiterDir[0];
            pack.textNoDelimiter = d.equals("none");
            pack.textDelimiter = pack.textNoDelimiter ? 0 : d.charAt(0);
            pack.textStart = startDir == null ? null : startDir[0];
            pack.textNmea = checksumDir != null && checksumDir[0].equals("nmea");
        }
        if (wire == Wire.TLV) {
            pack.tlvTagSize = tlvSizes[0];
            pack.tlvLengthSize = tlvSizes[1];
            pack.tlvKey = tlvKey;
            pack.tlvChecksum = ctx.tlvChecksumTag >= 0;
            pack.tlvChecksumTag = ctx.tlvChecksumTag;
        }
        return pack;
    }

    /**
     * Check the tlv directives once the file is read (0.13): each on the tlv wire only, at most once, before the first
     * kind, with a valid value; {@code checksum nmea} and {@code none} are not for the tlv wire. Returns the tag and
     * length sizes (0 for ber-oid and ber).
     */
    @SuppressWarnings("unchecked")
    private static int[] tlvDirectives(List<Object[]> dirs, Wire wire, String[] checksumDir, String format, String source) {
        if (wire == Wire.TLV && checksumDir != null) {
            throw badDirective(format, null, source + ":" + checksumDir[1] + ": checksum on the tlv wire is checksum sum16 <tag>");
        }
        int[] sizes = {0, 0};
        Set<String> seen = new HashSet<>();
        String checksumTag = null;
        int checksumLine = 0;
        for (Object[] d : dirs) {
            String kw = (String) d[0];
            List<String> a = (List<String>) d[1];
            String where = source + ":" + d[2];
            String shown = kw.equals("checksum") ? "checksum sum16" : kw;
            if (wire != Wire.TLV) throw badDirective(format, null, where + ": " + shown + " is for the tlv wire only");
            if (!seen.add(kw)) throw badDirective(format, null, where + ": " + kw + " given twice");
            if ((Boolean) d[3]) throw badDirective(format, null, where + ": " + kw + " after the first kind line");
            switch (kw) {
                case "tag":
                case "length": {
                    String v = a.size() == 1 ? a.get(0) : "";
                    int n;
                    if (v.equals(kw.equals("tag") ? "ber-oid" : "ber")) n = 0;
                    else if (v.equals("1") || v.equals("2") || v.equals("4")) n = v.charAt(0) - '0';
                    else throw badDirective(format, null, where + ": " + kw + " takes " + (kw.equals("tag") ? "ber-oid" : "ber") + ", 1, 2 or 4, got \"" + String.join(" ", a) + "\"");
                    sizes[kw.equals("tag") ? 0 : 1] = n;
                    break;
                }
                case "key": {
                    String v = a.size() == 1 ? a.get(0) : "";
                    if (!v.matches("(?:[0-9a-f]{2}){1,64}")) {
                        throw badDirective(format, null, where + ": key takes 1 to 64 bytes as an even number of lowercase hex digits, got \"" + String.join(" ", a) + "\"");
                    }
                    break;
                }
                default:
                    if (a.size() != 2) throw badDirective(format, null, where + ": checksum takes sum16 <tag>");
                    checksumTag = a.get(1);
                    checksumLine = (Integer) d[2];
            }
        }
        if (checksumTag != null) {
            String why = TlvCodec.checkTag(checksumTag, sizes[0]);
            if (why != null) throw badDirective(format, null, source + ":" + checksumLine + ": checksum: " + why);
        }
        return sizes;
    }

    /**
     * The key of the {@code with} option among a field line's options, or null. The token after {@code absent} or
     * {@code via} is that option's argument, never an option. {@code with} given twice, or with no key after it, is
     * {@code bad-directive} (engine-spec 0.18).
     */
    static String withKey(List<String> opts, String locator, String where, String format) {
        String with = null;
        for (int i = 0; i < opts.size(); i++) {
            String o = opts.get(i);
            if (o.equals("absent") || o.equals("via")) {
                i++;
            } else if (o.equals("with")) {
                if (with != null) throw badDirective(format, locator, where + ": with given twice");
                if (i + 1 >= opts.size()) throw badDirective(format, locator, where + ": with takes one key");
                with = opts.get(++i);
            }
        }
        return with;
    }

    /**
     * A {@code field} whose locator passes through the path of a {@code group} of the same scope is
     * {@code bad-directive} (ruling 21 of 0.7; {@code field} lines only, ruling 15 of 0.8).
     */
    private static void notThroughAGroup(List<Line> lines, Ctx ctx) {
        if (ctx.wire == Wire.BITS || ctx.wire == Wire.TEXT) return;
        Map<String, Group> paths = null;
        for (Line g : lines) {
            if (!(g instanceof Group)) continue;
            if (paths == null) paths = new java.util.HashMap<>();
            paths.putIfAbsent(g.locator, (Group) g);
        }
        if (paths == null) return;
        char sep = ctx.wire == Wire.XML ? '/' : '.';
        for (Line l : lines) {
            if (l instanceof Element) {
                // an element path that equals or passes through a group's path (ruling 12 of 0.18)
                for (Group g : paths.values()) {
                    if (l.locator.equals(g.locator) || l.locator.startsWith(g.locator + "/")) {
                        throw badDirective(ctx.format, l.locator, ctx.source + ":" + l.line + ": element " + l.locator
                                + " is on or under the path of group " + g.list + " (" + g.locator + ")");
                    }
                }
                continue;
            }
            if (!(l instanceof Field) || l.locator.equals(".")) continue;
            // Every proper prefix of the locator that ends before a separator. On xml the last part is @name or
            // #text on the element the parts before it reach, so a field on an item element itself is among them.
            String loc = l.locator;
            for (int i = loc.indexOf(sep); i >= 0; i = loc.indexOf(sep, i + 1)) {
                Group g = paths.get(loc.substring(0, i));
                if (g != null) {
                    throw badDirective(ctx.format, l.locator, ctx.source + ":" + l.line + ": the locator of field "
                            + ((Field) l).key + " passes through the path of group " + g.list + " (" + g.locator + ")");
                }
            }
        }
    }

    /** Within one scope a list is mapped by at most one group. */
    private static void oneGroupPerList(Set<String> lists, Group g, Ctx ctx) {
        if (!lists.add(g.list)) {
            throw badDirective(ctx.format, g.locator, ctx.source + ":" + g.line + ": list " + g.list
                    + " is mapped by two groups of one scope");
        }
    }

    /**
     * Read an {@code if [!]<word>:<pos>:<len> <value>[,<value>…]} line of a fixed layout. Anything but one locator
     * and one value list is {@code bad-directive} (rulings 12 of 0.17), as is a value that is not an unsigned decimal
     * integer below {@code 2^len}, an empty value, an empty list or a value listed twice.
     */
    private static LineSpec gateLine(List<String> args, int ln, String where, String format) {
        if (args.size() != 2) {
            throw badDirective(format, null, where + ": a gate is if [!]<word>:<pos>:<len> <value>[,<value>...], got "
                    + args.size() + " argument(s)");
        }
        String loc = args.get(0);
        boolean not = loc.startsWith("!");
        if (not) loc = loc.substring(1);
        if (!loc.matches("\\d+:\\d+:\\d+")) {
            throw badDirective(format, loc, where + ": a gate locator of a fixed layout is <word>:<pos>:<len>, got \"" + args.get(0) + "\"");
        }
        int len;
        try {
            int[] wpl = BitsCodec.parseLoc(loc);
            len = wpl[2];
        } catch (NumberFormatException ex) {
            throw badDirective(format, loc, where + ": the gate locator is out of range: " + loc);
        }
        if (len < 1 || len > 64) throw badDirective(format, loc, where + ": a gate reads 1 to 64 bits, got " + len);
        String[] parts = args.get(1).split(",", -1);
        Set<Long> seen = new HashSet<>();
        for (String v : parts) {
            if (!v.matches("\\d+")) {
                throw badDirective(format, loc, where + ": a gate value is an unsigned decimal integer, got \"" + v + "\"");
            }
            long n;
            try {
                n = Long.parseUnsignedLong(v);
            } catch (NumberFormatException ex) {
                throw badDirective(format, loc, where + ": gate value " + v + " does not fit " + len + " bits");
            }
            if (len < 64 && Long.compareUnsigned(n, BitsTransform.mask(len)) > 0) {
                throw badDirective(format, loc, where + ": gate value " + v + " does not fit " + len + " bits");
            }
            if (!seen.add(n)) throw badDirective(format, loc, where + ": gate value " + v + " is listed twice");
        }
        LineSpec s = new LineSpec(null, loc, args.get(1), null, false, ln);
        s.gate = true;
        s.not = not;
        return s;
    }

    /** Turn one raw gate block into its typed form: its lines are resolved in the scope that holds the block. */
    private static Gate resolveGate(LineSpec s, Ctx ctx, boolean inGroup) {
        String[] parts = s.arg.split(",", -1);
        long[] values = new long[parts.length];
        for (int i = 0; i < parts.length; i++) values[i] = Long.parseUnsignedLong(parts[i]);
        List<Line> lines = new ArrayList<>(s.body.lines.size());
        for (LineSpec b : s.body.lines) lines.add(resolve(b, ctx, inGroup));
        Scope body = new Scope(lines, s.body.defaults);
        ctx.bodies.add(body);   // its own defaults are read as the keys' types with every other scope's
        return new Gate(s.locator, s.not, values, BitsCodec.parseLoc(s.locator)[2], body, s.line);
    }

    /** Turn one raw group line and its body into its typed form. {@code inGroup}: the group is nested in another. */
    private static Group resolveGroup(LineSpec s, Ctx ctx, boolean inGroup) {
        String where = ctx.source + ":" + s.line;
        String format = ctx.format;
        int itemBits = 0;
        String countLocator = null;
        long countFixed = -1;
        String why;
        TextCodec.Loc textLoc = null;
        if (ctx.wire == Wire.TLV) throw badDirective(format, s.locator, where + ": group is not allowed on the tlv wire");
        if (ctx.wire == Wire.TEXT) {
            if (inGroup) throw badDirective(format, s.locator, where + ": a group inside a group is not allowed on the text wire");
            if (s.opts.size() != 2 || !s.opts.get(0).equals("item")) {
                throw badDirective(format, s.locator, where + ": a text group is group <list> <i> item <n>");
            }
            TextCodec.Loc at = TextCodec.parseLocator(s.locator);
            if (at == null || at.type != TextCodec.FIELD) throw badDirective(format, s.locator, where + ": a text group locator is a field index");
            TextCodec.Loc n = TextCodec.parseLocator(s.opts.get(1));
            if (n == null || n.type != TextCodec.FIELD || n.i < 1) {
                throw badDirective(format, s.locator, where + ": item takes a number of fields from 1, got \"" + s.opts.get(1) + "\"");
            }
            textLoc = new TextCodec.Loc(TextCodec.GROUP, at.i, 0, n.i, 0);
        } else if (ctx.wire == Wire.BITS) {
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
            if (why != null) throw badLocator(format, s.locator, where + ": " + why);   // 5a of 0.11 (ruling 44 of 0.21)
            try {
                if (!Transform.UNSIGNED.matcher(item).matches()) throw new NumberFormatException();
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
                if (why != null) throw badLocator(format, s.locator, where + ": count: " + why);
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
            if (why != null) {
                // ruling 44 of 0.21: protobuf `rest` and `last`, and a well-formed xml locator of the wrong kind (`@a`),
                // are a group locator not valid for the wire (ruling 37), bad-directive; every other malformed group
                // locator keeps the bad-locator of 5a of 0.11
                boolean wrongKind = (ctx.wire == Wire.PROTOBUF && (s.locator.equals("rest") || s.locator.equals("last")))
                        || (ctx.wire == Wire.XML && xmlGroupForm(s.locator) == null);
                if (wrongKind) throw badDirective(format, s.locator, where + ": " + why);
                throw badLocator(format, s.locator, where + ": " + why);
            }
        }
        List<Line> lines = new ArrayList<>(s.body.lines.size());
        Set<String> lists = null;
        int outerItem = ctx.itemFields;
        if (textLoc != null) ctx.itemFields = textLoc.len;
        for (LineSpec b : s.body.lines) {
            Line l = resolve(b, ctx, true);
            lines.add(l);
            if (l instanceof Group) {
                if (lists == null) lists = new HashSet<>();
                oneGroupPerList(lists, (Group) l, ctx);
            }
        }
        ctx.itemFields = outerItem;
        notThroughAGroup(lines, ctx);
        if (ctx.wire == Wire.PROTOBUF) {
            // a protobuf body is scalar only when every line is `.` (ruling 13 of 0.7)
            boolean itself = false, other = false;
            for (Line l : lines) {
                if (l.locator.equals(".") && l instanceof Field) itself = true;
                else other = true;
            }
            if (itself && other) {
                throw badDirective(format, s.locator, where + ": a protobuf group body mixes . with other lines");
            }
            // packed: every line of the body is a . field with a numeric transform (ruling 17 of 0.18)
            boolean packed = itself && !other;
            for (Line l : lines) if (l instanceof Field && ((Field) l).pb.wireType() == 2) packed = false;
            for (Line l : lines) {
                if (packed && ((Field) l).with != null) {
                    throw badDirective(format, s.locator, ctx.source + ":" + l.line + ": with on a . field of a packed protobuf group");
                }
            }
        }
        Scope body = new Scope(lines, s.body.defaults);
        Group g = new Group(s.key, s.locator, body, itemBits, countLocator, countFixed, s.line);
        g.loc = textLoc;
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
        if (s.gate) return resolveGate(s, ctx, inGroup);
        if (s.element) return new Element(s.locator, s.line);
        if (s.body != null) return resolveGroup(s, ctx, inGroup);
        // `.` is the item itself as a scalar: a field of a group body on json, geojson and protobuf.
        boolean dot = s.locator.equals(".") && wire != Wire.XML && wire != Wire.BITS && wire != Wire.TEXT && wire != Wire.TLV;
        if (dot && (!inGroup || s.key == null)) {
            throw badDirective(format, s.locator, where + ": the locator . is for a field inside a group");
        }
        if (s.key == null) return resolveWhen(s, ctx, where, inGroup);
        String via = null, absent = null, with = null, stop = null;
        boolean swap = false, trim = false, optional = false;
        for (int i = 0; i < s.opts.size(); i++) {
            String o = s.opts.get(i);
            switch (o) {
                case "stop":
                    // engine-spec 0.22: the code that ends the text of a fixed-size chars field
                    if (stop != null) throw badDirective(format, s.locator, where + ": stop given twice");
                    if (i + 1 >= s.opts.size()) throw badDirective(format, s.locator, where + ": stop takes one code");
                    stop = s.opts.get(++i);
                    break;
                case "with":
                    if (with != null) throw badDirective(format, s.locator, where + ": with given twice");
                    if (i + 1 >= s.opts.size()) throw badDirective(format, s.locator, where + ": with takes one key");
                    with = s.opts.get(++i);
                    break;
                case "absent":
                    // the token after `absent` is always its argument, even an option name (ruling 11 of 0.9)
                    if (absent != null) throw badDirective(format, s.locator, where + ": absent given twice");
                    if (i + 1 >= s.opts.size()) throw badDirective(format, s.locator, where + ": absent takes one or more values");
                    absent = s.opts.get(++i);
                    break;
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
        if (wire == Wire.TEXT && optional && inGroup) {
            throw badDirective(format, s.locator, where + ": optional is not allowed inside a text group");
        }
        if (wire != Wire.BITS && (swap || trim || stop != null || (optional && wire != Wire.TEXT))) {
            throw badDirective(format, s.locator, where + ": " + (swap ? "swap" : trim ? "trim" : stop != null ? "stop" : "optional") + " is for the bits wire only");
        }
        if (wire != Wire.TEXT && TextTransform.isTextOnlyName(s.arg)) {
            throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is valid on the text wire only");
        }
        if (wire != Wire.BITS && s.arg.equals("sixbit")) {
            throw badDirective(format, s.locator, where + ": transform \"sixbit\" is valid on the bits wire only");
        }
        // `hex` is also a bits transform (engine-spec 0.22)
        if (wire != Wire.TLV && TlvTransform.isTlvOnlyName(s.arg) && !(wire == Wire.BITS && s.arg.equals("hex"))) {
            throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is valid on the tlv wire only");
        }
        String why;
        Field f;
        // The transforms of 0.15 on a wire they do not list are bad-directive (engine-spec 0.15, Load errors).
        String head = BitsTransform.headOf(s.arg);
        boolean textWire = wire == Wire.XML || wire == Wire.JSON || wire == Wire.GEOJSON;
        // so is iso8601_short on bits or protobuf (ruling 11 of 0.18)
        if ((BitsTransform.isV015(head) && wire != Wire.BITS) || (TextScale.isName(head) && !textWire)
                || (s.arg.equals("iso8601_short") && !textWire)) {
            throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is not valid on wire " + wire.name().toLowerCase());
        }
        if (wire == Wire.TLV) {
            TlvCodec.Loc loc = tlvLocator(s, ctx, where);
            TlvTransform tt = TlvTransform.parse(s.arg, format, where);
            if (tt == null) throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is not valid on wire tlv");
            String sizeWhy = tt.checkSize(loc.size);
            if (sizeWhy != null) throw badDirective(format, s.locator, where + ": " + sizeWhy);
            f = new Field(s.key, s.locator, null, null, null, null, via, false, false, false, s.line);
            f.tlv = tt;
            f.loc = loc;
            why = null;
        } else if (wire == Wire.TEXT) {
            TextTransform tt;
            if (TextTransform.isTextOnlyName(s.arg)) {
                tt = TextTransform.parseTextOnly(s.arg, format, s.locator, where);
            } else {
                Transform t = Transform.byName(s.arg);
                tt = t == null ? null : TextTransform.base(t);
                if (tt == null) {
                    if (t != null || BitsTransform.isBitsName(s.arg) || PbTransform.isPbName(s.arg)) {
                        throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is not valid on wire text");
                    }
                    throw badDirective(format, s.locator, where + ": transform \"" + s.arg + "\" is not valid on wire text");
                }
            }
            TextCodec.Loc loc = textLocator(s, ctx, where, inGroup);
            if (loc.type == TextCodec.PAIR && loc.i == loc.j) {
                throw badDirective(format, s.locator, where + ": a pair names field " + loc.i + " twice");
            }
            if ((loc.type == TextCodec.PAIR) != tt.pair()) {
                throw badDirective(format, s.locator, where + ": " + (tt.pair()
                        ? "transform " + tt.name + " takes a pair <i>+<j>"
                        : "a pair is for the transforms that take two parts (dm, hms_dmy), not " + tt.name));
            }
            f = new Field(s.key, s.locator, null, tt, null, null, via, false, false, optional, s.line);
            f.loc = loc;
            why = null;
        } else if (wire == Wire.BITS) {
            if (!BitsTransform.isBitsName(s.arg)) {
                String w = (Transform.byName(s.arg) != null || PbTransform.isPbName(s.arg))
                        ? "transform \"" + s.arg + "\" is not valid on wire bits"
                        : "unknown transform \"" + s.arg + "\"";
                throw badDirective(format, s.locator, where + ": " + w);
            }
            if (s.locator.matches("\\d+")) {
                throw badDirective(format, s.locator, where + ": a bit length for a locator is for a pack with layout sequential");
            }
            if (Seq.isUperLocator(s.locator)) {
                throw badDirective(format, s.locator, where + ": a UPER locator is for a pack with encoding uper");
            }
            if (s.locator.startsWith("until:")) {
                throw badDirective(format, s.locator, where + ": until: is a locator of a pack with layout sequential (engine-spec 0.22)");
            }
            BitsTransform bt = BitsTransform.parse(s.arg, format, where);
            if (stop != null) bt.stop = stopCode(stop, bt, format, s.locator, where);
            f = new Field(s.key, s.locator, null, bt, null, via, swap, trim, optional, s.line);
            why = BitsCodec.checkLocator(s.locator);
            if (trim && !bt.takesTrim()) throw badDirective(format, s.locator, where + ": trim is for the ascii and sixbit transforms only");
            if (swap && bt.isSixbit()) throw badDirective(format, s.locator, where + ": swap is not an option of sixbit");
            if (swap && bt.refusesSwap()) throw badDirective(format, s.locator, where + ": swap is not allowed with " + s.arg);
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
                throw badDirective(format, s.locator, where + ": " + w);
            }
            f = new Field(s.key, s.locator, null, null, pb, via, false, false, false, s.line);
            why = dot ? null : ProtobufCodec.checkFieldLocator(s.locator);
        } else if (TextScale.isName(head)) {
            TextScale ts = TextScale.parse(s.arg, format, s.locator, where);
            f = new Field(s.key, s.locator, ts.isExact() ? Transform.INT : Transform.FLOAT, null, null, via, false, false, false, s.line);
            f.scale = ts;
            if (dot) why = null;
            else if (wire == Wire.XML) why = XmlCodec.checkFieldLocator(s.locator);
            else if (wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkFieldLocator(s.locator);
            else why = JsonCodec.checkLocator(s.locator);
        } else {
            Transform t = Transform.byName(s.arg);
            if (t == null || (t == Transform.BOOL && wire != Wire.JSON)) {
                String w = (t != null || BitsTransform.isBitsName(s.arg) || PbTransform.isPbName(s.arg))
                        ? "transform \"" + s.arg + "\" is not valid on wire " + wire.name().toLowerCase()
                        : "unknown transform \"" + s.arg + "\"";
                throw badDirective(format, s.locator, where + ": " + w);
            }
            f = new Field(s.key, s.locator, t, null, null, via, false, false, false, s.line);
            if (dot) why = null;
            else if (wire == Wire.XML) why = XmlCodec.checkFieldLocator(s.locator);
            else if (wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkFieldLocator(s.locator);
            else why = JsonCodec.checkLocator(s.locator);
        }
        if (why != null) throw badLocator(format, s.locator, where + ": " + why);
        if (absent != null) {
            f.absent = sentinels(f, absent, wire, format, where);
            if (wire == Wire.GEOJSON && !inGroup && GeoJsonCodec.coordIndex(s.locator) >= 0) {
                // a coordinate takes only number text as a sentinel (ruling 25 of 0.9)
                for (Object v : f.absent.json) {
                    if (!(v instanceof Json.Num)) {
                        throw badDirective(format, s.locator, where + ": absent: a coordinate takes only number text as a sentinel");
                    }
                }
            }
        }
        f.with = with;
        ctx.fields.add(f);
        ctx.typed.add(f);
        return f;
    }

    /** The {@code absent} values of a field, read as its wire's raw value (Version 0.9, The raw value). */
    static Sentinels sentinels(Field f, String arg, Wire wire, String format, String where) {
        switch (wire) {
            case BITS:
                return Sentinels.integers(arg, BitsCodec.parseLoc(f.locator)[2], format, f.locator, where);
            case PROTOBUF:
                if (f.pb.wireType() == 2) return Sentinels.texts(arg, false, format, f.locator, where);
                return Sentinels.integers(arg, f.pb.wireType() == 5 ? 32 : 64, format, f.locator, where);
            case XML:
                return Sentinels.texts(arg, true, format, f.locator, where);
            case TEXT:
                // `absent` on the text wire is bad-directive (ruling 16 of 0.10)
                throw badDirective(format, f.locator, where + ": absent is not valid on the text wire (ruling 16 of 0.10)");
            case TLV:
                // `absent` on the tlv wire is bad-directive (ruling 10 of 0.13)
                throw badDirective(format, f.locator, where + ": absent is not valid on the tlv wire (ruling 10 of 0.13)");
            default:
                return Sentinels.json(arg, f.transform == Transform.BOOL, format, f.locator, where);
        }
    }

    /** A text locator: its syntax is bad-pack; in a group, an index at or beyond the item's fields is bad-directive. */
    private static TextCodec.Loc textLocator(LineSpec s, Ctx ctx, String where, boolean inGroup) {
        TextCodec.Loc loc = TextCodec.parseLocator(s.locator);
        if (loc == null) {
            throw badDirective(ctx.format, s.locator, where + ": a text locator is <i>, <i>:<from>:<len> (len from 1) or <i>+<j>, got \"" + s.locator + "\"");
        }
        if (inGroup && loc.max() >= ctx.itemFields) {
            throw badDirective(ctx.format, s.locator, where + ": locator " + s.locator + " is beyond an item of " + ctx.itemFields + " fields");
        }
        return loc;
    }

    /** A tlv path: its syntax, its tags' range, and a first tag other than the checksum tag; each bad-directive. */
    private static TlvCodec.Loc tlvLocator(LineSpec s, Ctx ctx, String where) {
        Object parsed = TlvCodec.parseLocator(s.locator, ctx.tlvTagSize);
        if (!(parsed instanceof TlvCodec.Loc)) throw badDirective(ctx.format, s.locator, where + ": " + parsed);
        TlvCodec.Loc loc = (TlvCodec.Loc) parsed;
        if (loc.tags[0] == ctx.tlvChecksumTag) {
            throw badDirective(ctx.format, s.locator, where + ": path " + s.locator + " begins with the checksum tag " + ctx.tlvChecksumTag);
        }
        return loc;
    }

    private static When resolveWhen(LineSpec s, Ctx ctx, String where, boolean inGroup) {
        Wire wire = ctx.wire;
        String format = ctx.format;
        String v = s.arg;
        if (s.isConst && v.equals("present")) {
            throw badDirective(format, s.locator, where + ": const takes a value; write =present for the text");
        }
        if (wire == Wire.TLV) {
            TlvCodec.Loc loc = tlvLocator(s, ctx, where);
            When w;
            if (v.equals("present")) {
                if (loc.size != 0) throw badDirective(format, s.locator, where + ": when <path> present takes no size");
                w = new When(s.locator, v, true, v, false, 0, false, s.line);
            } else {
                if (loc.size == 0) throw badDirective(format, s.locator, where + ": a numeric " + (s.isConst ? "const" : "when") + " needs a size :<n>");
                long n = unsigned(v, format, s.locator, where);
                if (loc.size < 8 && Long.compareUnsigned(n, 1L << (8 * loc.size)) >= 0) {
                    throw badDirective(format, s.locator, where + ": value " + v + " does not fit " + loc.size + " bytes");
                }
                w = new When(s.locator, v, false, v, false, n, s.isConst, s.line);
            }
            w.loc = loc;
            return w;
        }
        if (wire == Wire.TEXT) {
            TextCodec.Loc loc = textLocator(s, ctx, where, inGroup);
            if (loc.type == TextCodec.PAIR) {
                throw badDirective(format, s.locator, where + ": a when or const takes a field or a column, not a pair");
            }
            When w = v.equals("present")
                    ? new When(s.locator, v, true, v, false, 0, s.isConst, s.line)
                    : new When(s.locator, v, false, v.startsWith("=") ? v.substring(1) : v, v.startsWith("="), 0, s.isConst, s.line);
            w.loc = loc;
            return w;
        }
        if (wire == Wire.BITS) {
            if (Seq.isUperLocator(s.locator)) {
                throw badDirective(format, s.locator, where + ": a UPER locator is for a field line of a pack with encoding uper");
            }
            String why = BitsCodec.checkLocator(s.locator);
            if (why != null) throw badLocator(format, s.locator, where + ": " + why);
            int len = BitsCodec.parseLoc(s.locator)[2];
            if (len > 64) throw badDirective(format, s.locator, where + ": a when line reads at most 64 bits");
            if (!s.isConst) return numericWhen(s, v, len, format, where);
            long n = unsigned(v, format, s.locator, where);
            if (len < 64 && (n < 0 || n > BitsTransform.mask(len))) {
                throw badDirective(format, s.locator, where + ": when value " + v + " does not fit " + len + " bits");
            }
            return new When(s.locator, v, false, v, false, n, s.isConst, s.line);
        }
        if (wire == Wire.PROTOBUF) {
            String why = ProtobufCodec.checkFieldLocator(s.locator);
            if (why != null) throw badLocator(format, s.locator, where + ": " + why);
            if (v.equals("present")) return new When(s.locator, v, true, v, false, 0, s.isConst, s.line);
            if (!s.isConst) return numericWhen(s, v, 64, format, where);
            return new When(s.locator, v, false, v, false, unsigned(v, format, s.locator, where), s.isConst, s.line);
        }
        String why;
        if (wire == Wire.XML) why = XmlCodec.checkFieldLocator(s.locator);
        else if (wire == Wire.GEOJSON && !inGroup) why = GeoJsonCodec.checkFieldLocator(s.locator);
        else why = JsonCodec.checkLocator(s.locator);
        if (why != null) throw badLocator(format, s.locator, where + ": " + why);
        if (v.equals("present")) return new When(s.locator, v, true, v, false, 0, s.isConst, s.line);
        if (s.isConst || v.isEmpty()) {
            // a lone "" is the empty text (ruling 11 of 0.9)
            boolean forced = v.startsWith("=");
            return new When(s.locator, v, false, forced ? v.substring(1) : v, forced, 0, s.isConst, s.line);
        }
        // engine-spec 0.20: a comma separates texts; `..` is literal; every item is a value as in 0.5
        String[] items = v.split(",", -1);
        String[] texts = new String[items.length];
        for (int i = 0; i < items.length; i++) {
            String it = items[i];
            if (it.isEmpty()) throw badDirective(format, s.locator, where + ": an empty value in the list \"" + v + "\"");
            if (it.equals("present") && items.length > 1) {
                throw badDirective(format, s.locator, where + ": present may not be combined with other values");
            }
            texts[i] = it.startsWith("=") ? it.substring(1) : it;
        }
        boolean forced = items[0].startsWith("=");
        When w = new When(s.locator, v, false, texts[0], forced, 0, s.isConst, s.line);
        if (items.length > 1) w.texts = texts;
        return w;
    }

    /** A {@code when} on {@code bits} or {@code protobuf}: one value, or a list of values and ranges (engine-spec 0.20). */
    private static When numericWhen(LineSpec s, String v, int len, String format, String where) {
        if (v.equals("present") || v.startsWith("present,") || v.endsWith(",present") || v.contains(",present,")) {
            throw badDirective(format, s.locator, where + ": present may not be combined with other values");
        }
        long[] ranges = numericList(v, len, format, s.locator, where);
        When w = new When(s.locator, v, false, v, false, ranges[0], false, s.line);
        if (ranges.length > 2 || ranges[0] != ranges[1]) w.ranges = ranges;
        return w;
    }

    private static long unsigned(String v, String format, String locator, String where) {
        if (!v.matches("\\d+")) {
            throw badDirective(format, locator, where + ": a when or const value must be an unsigned decimal integer, got \"" + v + "\"");
        }
        Long n = Transform.parseUnsigned(v, 64);
        if (n == null) throw badDirective(format, locator, where + ": when value " + v + " does not fit 64 bits");
        return n;
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
    /** The whitespace between tokens: space, tab, line feed and carriage return only (ruling 15 of 0.18). */
    static boolean isSpace(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }

    static List<String> tokenize(String line, String where) {
        List<String> out = new ArrayList<>();
        int i = 0, n = line.length();
        while (i < n) {
            char c = line.charAt(i);
            if (isSpace(c)) { i++; continue; }
            if (c == '#') break;
            if (c == '"') {
                int close = line.indexOf('"', i + 1);
                if (close < 0) throw new GtException(GtException.Code.UNTERMINATED_QUOTE, null, null, where + ": unterminated quote");
                out.add(line.substring(i + 1, close));
                i = close + 1;
                if (i < n && !isSpace(line.charAt(i))) {
                    // a quoted token is a whole token: `"",0` is not a value list (ruling 11 of 0.9)
                    throw badDirective(null, null, where + ": text directly after closing quote");
                }
            } else {
                int start = i;
                while (i < n && !isSpace(line.charAt(i))) i++;
                out.add(line.substring(start, i));
            }
        }
        return out;
    }
}
