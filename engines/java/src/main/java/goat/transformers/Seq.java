package goat.transformers;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.BitSet;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * A {@code bits} pack with {@code layout sequential} (engine-spec 0.8): the message as lines read in order from a
 * cursor. This file holds the parsed form and the parser of the lines; {@code SeqCodec}, in the bits wire, reads and writes messages.
 */
final class Seq {
    private Seq() {}

    /** {@code INNER}: engine-spec 0.34, the rest of the extent is a message of another pack. */
    enum Op { FIELD, CONST, WHEN, PAD, ALIGN, PRESENCE, IF, OPT, CHAIN, LENGTH, WHOLE, GROUP, EXT, CHOICE, SWITCH, COUNT, INNER }

    /** {@code SIZE}: engine-spec 0.19; {@code REF}: {@code count @<name>}; {@code REST} and {@code LAST}: engine-spec 0.21. */
    enum Repeat { COUNT, WHILE, MORE, FX, SIZE, REST, LAST, REF }

    /** The forms of a UPER locator (engine-spec 0.19). */
    enum UKind { INT, INT_SEMI, INT_FREE, ENUM, CHARS, OCTETS }

    /**
     * A UPER locator: {@code int:<lb>:<ub>[:ext]} (INT), {@code int:<lb>:} (INT_SEMI), {@code int::} (INT_FREE),
     * {@code enum:<n>[:ext]} (ENUM, {@code n} in {@code ub}), {@code chars:...} and {@code octets:...} (sized when
     * {@code lb..ub} is given).
     */
    static final class Uper {
        final UKind kind;
        final boolean ext;
        final boolean sized;
        final long lb;
        final long ub;

        Uper(UKind kind, boolean ext, boolean sized, long lb, long ub) {
            this.kind = kind;
            this.ext = ext;
            this.sized = sized;
            this.lb = lb;
            this.ub = ub;
        }
    }

    /** The bits of a constrained whole number of range {@code ub - lb} (an unsigned 64-bit value): 0 for one value. */
    static int rangeBits(long lb, long ub) { return 64 - Long.numberOfLeadingZeros(ub - lb); }

    /** One sequential line; a block line holds the lines up to its {@code end}. */
    static final class Node {
        final Op op;
        final int line;
        /** Bit length: of a field, {@code const}, {@code when}, {@code pad}, n-bit presence, count or length field; the multiple of {@code align}. */
        int len;
        /** {@code const}, {@code when}: the unsigned value (of a {@code when} with a list, the first value written). */
        long value;
        /** {@code when} with a list or a range (engine-spec 0.20): the {@code lo, hi} pairs; null for one value. */
        long[] ranges;
        /** {@code field}: the field line and the {@code also} lines after it, all on the same bits. */
        List<Pack.Field> keys;
        /** {@code when ... as <key>} (engine-spec 0.30): the key its bits are bound to, read as {@code uint}; else null. */
        Pack.Field as;
        /** {@code when ... at <offset>} (engine-spec 0.33): the offset in bits from kind start, unsigned; -1 for none. */
        long at = -1;
        boolean hasAt;
        /** {@code as <key> optional} (engine-spec 0.52): a key the entity does not hold does not stop the kind. */
        boolean asOptional;
        /**
         * {@code presence}: its name, whether it is {@code fx}, its slot in the state of one decode or encode;
         * {@code count}: its name; {@code inner}: the format of the inner pack (engine-spec 0.34).
         */
        String name;
        boolean fx;
        int id;
        /** {@code presence}: the bits some {@code if} block outside every case of a switch names, with or without {@code !}. */
        final BitSet named = new BitSet();
        /** {@code presence}: every bit some {@code if} names, inside a case or not. */
        final BitSet anyNamed = new BitSet();
        /**
         * {@code presence}: the bits named only by {@code if} lines inside a case (declared after the presence), with
         * the innermost case of each such line: they count only when that case is read (ruling 21 of 0.20).
         */
        final Map<Integer, List<Case>> caseNamed = new HashMap<>();
        /** {@code if}: the presence, bit and negation of each name. */
        Node[] refPresence;
        int[] refBit;
        boolean[] refNot;
        /** {@code if}, {@code opt}, {@code length}: the lines of the block. */
        List<Node> body;
        /** {@code chain}: its parts, split at the {@code fx} lines. */
        List<List<Node>> parts;
        /** {@code chain}: its last line is an {@code fx} line. */
        boolean endsWithFx;
        /** {@code length}: counted in bits, not bytes; and the {@code plus} value (also of a {@code count} line). */
        boolean inBits;
        long plus;
        /** {@code inner <format> partial} (engine-spec 0.34): bytes after the inner message are ignored. */
        boolean partial;
        /** {@code inner <format> run} (engine-spec 0.92): a run of messages. */
        boolean run;
        /** {@code group}: the list, how it repeats, and the lines of one item. */
        String list;
        Repeat repeat;
        Body items;
        /** {@code field} with a UPER locator: its form; null for a bit length. */
        Uper u;
        /** {@code field until:<code> chars:<set>} (engine-spec 0.22): the terminator code; -1 for a bit length. */
        int until = -1;
        /** {@code group ... size}: the size constraint, when there is one ({@code lb}, {@code ub} below). */
        boolean sized;
        long lb;
        long ub;
        /** {@code choice}: the number of root alternatives, the extension marker, and each alt's index and lines. */
        int alts;
        boolean ext;
        final List<Integer> altIndex = new ArrayList<>();
        final List<List<Node>> altLines = new ArrayList<>();
        /** {@code choice}: alt index to its position in {@link #altLines}. */
        final Map<Integer, Integer> altAt = new HashMap<>();
        /** {@code group ... count @<name>} and {@code length @<name> units <u>}: the {@code count} line it names. */
        Node countRef;
        /** {@code length @<name> units <u>} (engine-spec 0.83): the bits of one unit; 0 for a plain {@code length}. */
        int unit;
        /** {@code group ... count @<a> @<b>} (engine-spec 0.31): the second count line it names; else null. */
        Node countRef2;
        /** {@code switch}: the key, its cases in line order, and its {@code else} (or null). */
        String switchKey;
        /** {@code switch}: the first field line mapping its key in its scope (ruling 37 of 0.20). */
        Node keyLine;
        List<Case> cases;
        Case elseCase;

        Node(Op op, int line) {
            this.op = op;
            this.line = line;
        }
    }

    /** One {@code case} (or the {@code else}) of a {@code switch}: its values, its lines and its own defaults. */
    static final class Case {
        final int line;
        /** The listed values; null for the {@code else}. */
        final Pack.ValueList values;
        final List<Node> body = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
        /** The defaults read as the keys' types (with the pack's other scopes). */
        final Pack.Scope scope = new Pack.Scope(new ArrayList<>(), defaults);

        Case(int line, Pack.ValueList values) {
            this.line = line;
            this.values = values;
        }
    }

    /** The case a value of the switch key selects: the first that lists it, else the {@code else}; null for {@code no-kind}. */
    static Case select(Node sw, Object v) {
        if (v != null) {
            for (Case c : sw.cases) if (c.values.holds(v)) return c;
        }
        return sw.elseCase;
    }

    /** One kind of a message or of a group's items; a body with no {@code kind} line has one, with a null name. */
    static final class Kind {
        final String name;
        final List<Node> whens = new ArrayList<>();
        final List<Pack.Require> requires = new ArrayList<>();
        /** The kind's lines after its {@code when} lines. */
        final List<Node> lines = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
        /** The common lines, this kind's {@code when} lines, then its own lines: what encode writes, in order. */
        List<Node> all;
        /** The defaults in force: the body's common ones, replaced by the kind's own. */
        Pack.Scope scope;
        /** Its {@code when ... at} lines, in line order (engine-spec 0.33). */
        final List<Node> windows = new ArrayList<>();
        /** The number of its own lines ({@code whens} then {@code lines}) that cover every window: encode settles them there. */
        int prefix;

        Kind(String name) { this.name = name; }
    }

    /** The lines of the message, or of one item of a group. */
    static final class Body {
        final List<Node> common = new ArrayList<>();
        final List<Kind> kinds = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
        boolean hasKinds;
        int firstCommonWhen;
        /** A {@code length @<name> units <u>} line stands in this body, the bodies of its groups left out (engine-spec 0.83). */
        boolean unitBlocks;

        Kind kind(String name) {
            for (Kind k : kinds) if (name.equals(k.name)) return k;
            return null;
        }
    }

    /** Directives that are lines of the layout: in a sequential pack the parser below reads them. */
    static final Set<String> LINES = Set.of("field", "also", "const", "when", "pad", "align", "presence", "if", "opt",
            "chain", "fx", "length", "group", "end", "kind", "requires", "default", "ext", "choice", "alt",
            "switch", "case", "else", "count",
            "inner");   // engine-spec 0.34

    /** The lines that exist only in a UPER pack (engine-spec 0.19, ruling 9). */
    static final Set<String> UPER_ONLY = Set.of("ext", "choice", "alt");

    /** True for a locator of one of the UPER forms (engine-spec 0.19): {@code int:}, {@code enum:}, {@code chars:}, {@code octets:}. */
    static boolean isUperLocator(String loc) {
        return loc.startsWith("int:") || loc.startsWith("enum:") || loc.startsWith("chars:") || loc.startsWith("octets:");
    }

    /** A number of a UPER locator (ruling 15 of 0.19): an optional {@code -} and digits, no leading zero, no {@code -0}. */
    private static final java.util.regex.Pattern UNUMBER = java.util.regex.Pattern.compile("0|-?[1-9][0-9]*");

    private static java.math.BigInteger unumber(String s) {
        return UNUMBER.matcher(s).matches() && s.length() <= 40 ? new java.math.BigInteger(s) : null;
    }

    private static boolean within(java.math.BigInteger v, long lo, long hi) {
        return v != null && v.compareTo(java.math.BigInteger.valueOf(lo)) >= 0 && v.compareTo(java.math.BigInteger.valueOf(hi)) <= 0;
    }

    /** A UPER locator parsed, or the reason it is not one ({@code bad-directive}). */
    static Object parseUper(String loc) {
        String[] p = loc.split(":", -1);
        String head = p[0];
        String form = "a UPER locator is int:<lb>:<ub>[:ext], int:<lb>:, int::, enum:<n>[:ext], chars:<lb>:<ub>, chars:, octets:<lb>:<ub> or octets:";
        switch (head) {
            case "int": {
                if (p.length == 3 && p[1].isEmpty() && p[2].isEmpty()) return new Uper(UKind.INT_FREE, false, false, 0, 0);
                java.math.BigInteger lb = unumber(p.length >= 2 ? p[1] : "x");
                if (p.length == 3 && p[2].isEmpty()) {
                    if (!within(lb, Long.MIN_VALUE, Long.MAX_VALUE)) return form + ": the lower bound of " + loc + " is not a 64-bit integer";
                    return new Uper(UKind.INT_SEMI, false, false, lb.longValue(), 0);
                }
                boolean ext = p.length == 4 && p[3].equals("ext");
                if (p.length != 3 && !ext) return form + ", got \"" + loc + "\"";
                java.math.BigInteger ub = unumber(p[2]);
                if (!within(lb, Long.MIN_VALUE, Long.MAX_VALUE) || !within(ub, Long.MIN_VALUE, Long.MAX_VALUE)) {
                    return "the bounds of " + loc + " are not decimal integers from -2^63 to 2^63-1 (" + form + ")";
                }
                if (lb.compareTo(ub) > 0) return "the lower bound of " + loc + " is above its upper bound";
                return new Uper(UKind.INT, ext, true, lb.longValue(), ub.longValue());
            }
            case "enum": {
                boolean ext = p.length == 3 && p[2].equals("ext");
                if (p.length != 2 && !ext) return form + ", got \"" + loc + "\"";
                java.math.BigInteger n = unumber(p[1]);
                if (!within(n, 1, 65536)) return "enum takes 1 to 65536 root values, got \"" + p[1] + "\"";
                return new Uper(UKind.ENUM, ext, true, 0, n.longValue());
            }
            default: {
                UKind k = head.equals("chars") ? UKind.CHARS : UKind.OCTETS;
                if (p.length == 2 && p[1].isEmpty()) return new Uper(k, false, false, 0, 0);
                if (p.length != 3) return form + ", got \"" + loc + "\"";
                java.math.BigInteger lb = unumber(p[1]), ub = unumber(p[2]);
                if (!within(lb, 0, 65535) || !within(ub, 0, 65535)) return head + " takes sizes from 0 to 65535, got \"" + loc + "\"";
                if (lb.compareTo(ub) > 0) return "the lower size of " + loc + " is above its upper size";
                return new Uper(k, false, true, lb.longValue(), ub.longValue());
            }
        }
    }

    /** True when {@code t} names a transform of some wire (well-formed or not); another name is unknown-transform. */
    static boolean isKnownTransform(String t) {
        return Transform.byName(t) != null || BitsTransform.isBitsName(t) || PbTransform.isPbName(t)
                || CodeSeq.isHead(BitsTransform.headOf(t))   // engine-spec 0.46
                || Part.isName(t)   // engine-spec 0.64
                || TextTransform.isTextOnlyName(t) || TlvTransform.isTlvOnlyName(t)
                || TextScale.isName(t.indexOf(':') < 0 ? t : t.substring(0, t.indexOf(':')));   // 0.15 text-wire scales
    }

    /** True when the UPER locator form takes the transform (the table of 0.19). */
    static boolean takes(Uper u, String t) {
        String head = t.indexOf(':') < 0 ? t : t.substring(0, t.indexOf(':'));
        switch (u.kind) {
            case ENUM: return t.equals("uint");
            case CHARS: return t.equals("ascii");
            case OCTETS: return t.equals("hex") || t.equals("utf8");
            default:
                return t.equals("uint") || t.equals("twos") || head.equals("uscale") || head.equals("sscale");
        }
    }

    /**
     * True when the tokens after the values of a {@code when} hold {@code at} as a word. The token after the first
     * {@code as} is its key, and no word (rulings 4, 11 and 14 of 0.52); {@code as} itself is never a key.
     */
    static boolean holdsAt(List<String> rest) {
        int key = rest.indexOf("as") + 1;   // 0 when there is no `as`: no token is exempt (an `at` there is the word)
        for (int i = 0; i < rest.size(); i++) {
            if (rest.get(i).equals("at") && (key == 0 || i != key)) return true;
        }
        return false;
    }

    /** Directives that exist only in a sequential pack. */
    static final Set<String> SEQUENTIAL_ONLY = Set.of("also", "pad", "align", "presence", "if", "opt", "chain", "fx", "length",
            "switch", "case", "else", "count");

    /** The largest presence bit an {@code if} may name in an {@code fx} presence. */
    private static final int MAX_FX_BIT = 7 * 4096;

    /** Reads the layout lines of a sequential pack as the file is read; {@link #finish} runs the whole-file checks. */
    static final class Parser {
        private final String source;
        private final List<String[]> keyRefs;
        private final List<Pack.ValueList> valueLists;
        final List<Pack.Field> fields = new ArrayList<>();
        final List<Pack.Line> typed = new ArrayList<>();
        final List<Pack.Scope> scopes = new ArrayList<>();
        final Body root = new Body();
        int presences;
        private final ArrayDeque<Frame> stack = new ArrayDeque<>();
        /** {@code via} names to check once every {@code map} line is read: {table, locator, where}. */
        private final List<String[]> vias = new ArrayList<>();

        /** An open block: the message, a group body, or an {@code if}, {@code opt}, {@code chain} or {@code length}. */
        private static final class Frame {
            final char type;   // M message, G group, I if, O opt, C chain, L length, E ext, H choice, S switch before its first case, K case or else
            final String what;
            final int line;
            final Node node;
            List<Node> lines;
            final Map<String, Node> names = new HashMap<>();
            // a message or group body
            Body body;
            Kind kind;
            Map<String, Node> kindNames;
            boolean kindLineSeen;
            /** The groups of each list in this scope: for each, its enclosing {@code if} and {@code opt} blocks, innermost first. */
            final Map<String, List<List<Frame>>> lists = new HashMap<>();
            Map<String, List<List<Frame>>> kindLists;
            /** A choice: a marker for the alt being read, so groups in different alts may map one list. */
            Frame alt;
            /** The field line directly before the line being read, in this block. */
            Node lastField;
            boolean lastWasFx;
            /** A message or group body: the keys mapped so far by field and also lines, of the common lines and of the current kind. */
            final Map<String, Node> mapped = new HashMap<>();
            Map<String, Node> kindMapped;
            /** A case frame: its case. */
            Case kase;

            Frame(char type, String what, int line, Node node, List<Node> lines) {
                this.type = type;
                this.what = what;
                this.line = line;
                this.node = node;
                this.lines = lines;
            }

            boolean isBody() { return body != null; }
        }

        /** A line of the file reads {@code encoding uper}: UPER lines are checked as they are read. */
        private final boolean uperHint;
        /** The first UPER construct (0.19): its line, and the first reason one is refused, both checked after the file is read. */
        int uperLine;
        String uperWhy;
        /**
         * engine-spec 0.33: the first error of the form of an {@code at} (ruling 10), and the first window that is not
         * fixed in its kind. Both are checked after the file, after the module checks: the engine raises them.
         */
        GtException atError;
        GtException windowError;

        private void atBad(String format, String why) {
            if (atError == null) atError = bad(format, null, why);
        }

        /** The formats of the {@code inner} lines (engine-spec 0.34), in file order. */
        final List<String> inners = new ArrayList<>();
        /** An {@code inner ... run} line stands in the pack (engine-spec 0.92). */
        boolean carrier;
        /** The first {@code inner} line under a block that may not hold one: refused after the file is read. */
        String innerWhy;

        Parser(String source, List<String[]> keyRefs, boolean uperHint, List<Pack.ValueList> valueLists) {
            this.source = source;
            this.keyRefs = keyRefs;
            this.uperHint = uperHint;
            this.valueLists = valueLists;
            Frame f = new Frame('M', "pack", 0, null, root.common);
            f.body = root;
            stack.push(f);
        }

        /** True when a block is open: a pack-wide directive is then not allowed. */
        boolean inBlock() { return stack.size() > 1; }

        private static GtException bad(String format, String locator, String detail) {
            return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, detail);
        }

        private static void arity(String kw, List<String> args, int n, String where, String format) {
            if (args.size() != n) {
                throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null,
                        where + ": " + kw + " takes " + n + " argument(s), got " + args.size());
            }
        }

        /** A bit length written as a locator: a decimal integer from {@code min} to {@code max}. */
        private static int bitLength(String text, int min, int max, String what, String where, String format) {
            if (text.indexOf(':') >= 0) {
                throw bad(format, text, where + ": " + what + " takes a bit length in a sequential pack, not a position: " + text);
            }
            // an unsigned decimal integer: leading zeros are allowed (ruling 2c of 0.11)
            if (!Transform.UNSIGNED.matcher(text).matches()) throw bad(format, text, where + ": " + what + " takes a bit length, got \"" + text + "\"");
            String digits = text.replaceFirst("^0+(?=.)", "");
            if (digits.length() > 10 || Long.parseLong(digits) > Integer.MAX_VALUE) {
                throw bad(format, text, where + ": " + what + " takes a length of " + min + " to " + max + " bits, got " + text);
            }
            int n = Integer.parseInt(digits);
            if (n < min || n > max) {
                throw bad(format, text, where + ": " + what + " takes a length of " + min + " to " + max + " bits, got " + n);
            }
            return n;
        }

        private static long unsignedValue(String v, int len, String what, String where, String format) {
            if (!v.matches("\\d+")) throw bad(format, null, where + ": a " + what + " value is an unsigned decimal integer, got \"" + v + "\"");
            Long parsed = Transform.parseUnsigned(v, 64);
            if (parsed == null) throw bad(format, null, where + ": " + what + " value " + v + " does not fit 64 bits");
            long n = parsed;
            if (len < 64 && (n < 0 || n > BitsTransform.mask(len))) {
                throw bad(format, null, where + ": " + what + " value " + v + " does not fit " + len + " bits");
            }
            return n;
        }

        private Frame bodyFrame() {
            for (Frame f : stack) if (f.isBody()) return f;
            throw new IllegalStateException();
        }

        /** The innermost case frame passed before the presence {@link #lookup} last found was reached, or null. */
        private Case lookupCase;

        private Node lookup(String name) {
            lookupCase = null;
            for (Frame f : stack) {
                if (f.kindNames != null && f.kindNames.containsKey(name)) return f.kindNames.get(name);
                if (f.names.containsKey(name)) return f.names.get(name);
                if (f.type == 'K' && lookupCase == null) lookupCase = f.kase;
            }
            return null;
        }

        /** Record a key mapped by a field or also line in the scope of the innermost body. */
        private void mapped(String key, Node line) {
            Frame b = bodyFrame();
            (b.kindMapped != null ? b.kindMapped : b.mapped).putIfAbsent(key, line);
        }

        /**
         * Every key a {@code field}, {@code also} or {@code when ... as} line maps, with its scope (the body), its
         * kind (null for the common lines) and whether the line is a {@code when ... as}: for the bans of ruling 9
         * of 0.30, checked once the file is read.
         */
        private final List<Object[]> keyLines = new ArrayList<>();

        private void keyLine(String key, int ln, boolean as) {
            Frame b = bodyFrame();
            keyLines.add(new Object[]{key, b.body, b.kind, ln, as});
        }

        /**
         * The bans of rulings 9, 21 and 33 of 0.30: in one reading path of one scope (the common lines plus one kind,
         * every block of them included; a group body is a scope of its own) a key named by {@code as} is named by no
         * other {@code as} line and mapped by no {@code field} or {@code also} line.
         */
        void checkAsBans(String format) {
            for (int i = 0; i < keyLines.size(); i++) {
                Object[] a = keyLines.get(i);
                for (int j = 0; j < i; j++) {
                    Object[] b = keyLines.get(j);
                    if (!(Boolean) a[4] && !(Boolean) b[4]) continue;
                    if (!a[0].equals(b[0]) || a[1] != b[1]) continue;
                    if (a[2] != null && b[2] != null && a[2] != b[2]) continue;
                    boolean both = (Boolean) a[4] && (Boolean) b[4];
                    throw bad(format, null, source + ":" + a[3] + ": key " + a[0] + (both
                            ? " is named by two when ... as lines of one reading path (lines " + b[3] + " and " + a[3] + ")"
                            : " is named by when ... as and mapped by a field or also line in one reading path (lines " + b[3] + " and " + a[3] + ")"));
                }
            }
        }

        /** The count or presence a {@code count @<name>} names: visible here and within the same group body. */
        private Node lookupCount(String name) {
            for (Frame f : stack) {
                if (f.kindNames != null && f.kindNames.containsKey(name)) return f.kindNames.get(name);
                if (f.names.containsKey(name)) return f.names.get(name);
                if (f.isBody()) return null;
            }
            return null;
        }

        private void push(char type, String what, int ln, Node node, List<Node> lines) {
            stack.push(new Frame(type, what, ln, node, lines));
        }

        /** A UPER construct at line {@code ln}: noted for the check after the file is read (ruling 9 of 0.19). */
        private void uper(int ln) {
            if (uperLine == 0) uperLine = ln;
        }

        /**
         * A UPER line refused: in a pack with a line {@code encoding uper} it is a line error; otherwise the pack is
         * refused after the file is read because it uses a UPER line at all, so the reason is only kept.
         */
        private void uperBad(String format, String locator, String why) {
            if (uperHint) throw bad(format, locator, why);
            if (uperWhy == null) uperWhy = why;
        }

        /** A count of a {@code choice}, {@code alt} or {@code group ... size} line: digits, no leading zero (ruling 15 of 0.19). */
        private static long count(String s, long max) {
            if (!s.matches("0|[1-9][0-9]{0,9}")) return -1;
            long v = Long.parseLong(s);
            return v > max ? -1 : v;
        }

        /** One layout line of the file. */
        void line(String kw, List<String> args, int ln, String where, String format) {
            Frame f = stack.peek();
            if (f.type == 'S' && !kw.equals("case") && !kw.equals("else")) {
                // ruling 20 of 0.20: nothing stands between switch and its first case
                throw bad(format, null, where + ": " + (kw.equals("end") ? "a switch with no case" : kw + " between switch and its first case"));
            }
            if (kw.equals("case") || kw.equals("else")) {
                switchArm(kw, args, ln, where, format);
                return;
            }
            if (kw.equals("end") && f.type == 'K') {
                arity(kw, args, 0, where, format);
                stack.pop();   // the last case
                stack.pop();   // the switch
                stack.peek().lastField = null;
                return;
            }
            if (kw.equals("end")) {
                arity(kw, args, 0, where, format);
                if (stack.size() == 1) throw bad(format, null, where + ": end with no open block");
                if (f.type == 'H' && f.node.altLines.isEmpty()) {
                    uperBad(format, null, source + ":" + f.line + ": a choice has at least one alt line");
                }
                stack.pop();
                if (f.type == 'G') finishBody(f.body, format, source + ":" + f.line);
                if (f.type == 'C' && f.lastWasFx) {
                    f.node.endsWithFx = true;
                    f.node.parts.remove(f.node.parts.size() - 1);
                }
                stack.peek().lastField = null;
                return;
            }
            if (f.type == 'H' && f.lines == null && !kw.equals("alt")) {
                uperBad(format, null, where + ": a line between choice and its first alt");
                f.lines = new ArrayList<>();   // kept only to read the rest of the file
            }
            Node before = f.lastField;
            f.lastField = null;
            f.lastWasFx = kw.equals("fx");
            // requires and default lines do not count as lines of the kind: a when may follow them (ruling 18 of 0.8)
            if (f.isBody() && f.kind != null && !kw.equals("when") && !kw.equals("kind") && !kw.equals("requires")
                    && !kw.equals("default")) {
                f.kindLineSeen = true;
            }
            switch (kw) {
                case "field": {
                    if (args.size() < 3) {
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": field takes at least 3 arguments, got " + args.size());
                    }
                    String key = args.get(0), locator = args.get(1), tname = args.get(2);
                    // the line checks of ruling 5b of 0.11 in order: the transform, the locator, the options, the
                    // absent values; a length the transform does not allow is checked after the file (ruling 4d)
                    Pack.checkTransformName(tname, format, locator, where);
                    if (isUperLocator(locator)) {
                        // a UPER locator (0.19): its form, its transform and its options are checked after the file
                        uperField(f, key, locator, tname, args, ln, where, format);
                        break;
                    }
                    if (locator.startsWith("until:")) {
                        untilField(f, key, locator, tname, args, ln, where, format);
                        break;
                    }
                    if (locator.indexOf(':') < 0 && !Transform.UNSIGNED.matcher(locator).matches()) {
                        throw new GtException(GtException.Code.BAD_LOCATOR, format, locator, where + ": a field takes a bit length, got \"" + locator + "\"");
                    }
                    if (locator.matches("0+")) {
                        throw new GtException(GtException.Code.BAD_LOCATOR, format, locator, where + ": a bit length of 0");
                    }
                    int len = bitLength(locator, 1, Integer.MAX_VALUE, "a field", where, format);
                    BitsTransform bt = BitsTransform.isBitsName(tname) ? BitsTransform.parse(tname, format, where) : null;
                    String via = null, absent = null, with = null, stop = null;
                    boolean swap = false, trim = false;
                    for (int i = 3; i < args.size(); i++) {
                        String o = args.get(i);
                        if (o.equals("stop")) {
                            // engine-spec 0.22: the code that ends the text of a fixed-size chars field
                            if (stop != null) throw bad(format, locator, where + ": stop given twice");
                            if (i + 1 >= args.size()) throw bad(format, locator, where + ": stop takes one code");
                            stop = args.get(++i);
                        } else if (o.equals("with")) {
                            // engine-spec 0.18: the line writes only when the entity holds the key
                            if (with != null) throw bad(format, locator, where + ": with given twice");
                            if (i + 1 >= args.size()) throw bad(format, locator, where + ": with takes one key");
                            with = args.get(++i);
                        } else if (o.equals("absent")) {
                            // the token after `absent` is always its argument (ruling 11 of 0.9)
                            if (absent != null) throw bad(format, locator, where + ": absent given twice");
                            if (i + 1 >= args.size()) throw bad(format, locator, where + ": absent takes one or more values");
                            absent = args.get(++i);
                        } else if (o.equals("via") && via == null && i + 1 < args.size()) via = args.get(++i);
                        else if (o.equals("swap") && !swap) swap = true;
                        else if (o.equals("trim") && !trim) trim = true;
                        else if (o.equals("optional")) throw bad(format, locator, where + ": optional is not a field option of a sequential pack");
                        else throw bad(format, locator, where + ": unknown or repeated field option \"" + o + "\"");
                    }
                    Sentinels sentinels = absent != null && len <= 64 ? Sentinels.integers(absent, len, format, locator, where) : null;
                    if (stop != null) bt.stop = Pack.stopCode(stop, bt, format, locator, where);
                    if (via != null) vias.add(new String[]{via, locator, where});
                    Pack.Field fl = new Pack.Field(key, locator, null, bt, null, via, swap, trim, false, ln);
                    fl.absent = sentinels;
                    afterFile.add(new Object[]{fl, tname, len, where, absent});
                    fl.with = with;
                    fields.add(fl);
                    typed.add(fl);
                    keyRefs.add(new String[]{key, locator});
                    if (with != null) keyRefs.add(new String[]{with, locator});
                    Node n = new Node(Op.FIELD, ln);
                    mapped(key, n);
                    keyLine(key, ln, false);
                    n.len = len;
                    n.keys = new ArrayList<>();
                    n.keys.add(fl);
                    f.lines.add(n);
                    f.lastField = n;
                    break;
                }
                case "also": {
                    if (before == null) throw bad(format, null, where + ": also is written directly after a field line");
                    if (args.size() != 1 && !(args.size() == 3 && args.get(1).equals("via"))) {
                        throw bad(format, null, where + ": also is also <key> [via <table>]");
                    }
                    Pack.Field first = before.keys.get(0);
                    String via = args.size() == 3 ? args.get(2) : null;
                    if (via != null) vias.add(new String[]{via, first.locator, where});
                    Pack.Field fl = new Pack.Field(args.get(0), first.locator, null, first.bits, null, via, first.swap, first.trim, false, ln);
                    fl.absent = first.absent;   // the same bits: the field line's sentinels hold for every key on them
                    fl.tlv = first.tlv;
                    fields.add(fl);
                    typed.add(fl);
                    keyRefs.add(new String[]{args.get(0), first.locator});
                    mapped(args.get(0), before);
                    keyLine(args.get(0), ln, false);
                    before.keys.add(fl);
                    f.lastField = before;
                    break;
                }
                case "const":
                case "when": {
                    String asKey = null;
                    long at = -1;
                    boolean hasAt = false, asOptional = false;
                    if (kw.equals("when") && args.size() > 2) {
                        // `when <len> <values> [at <n>] [as <k> [optional]]`, in that order (ruling 11 of 0.33, ruling 1
                        // of 0.52); the words are matched exactly (ruling 15 of 0.33, 15 and 22 of 0.30, 12 of 0.52)
                        List<String> rest = args.subList(2, args.size());
                        int i = 0;
                        if (holdsAt(rest)) {
                            // engine-spec 0.33: a line holding `at` has the form `at <n> [as <k> [optional]]`; any token
                            // out of that order, `as` included, is an `at` form error checked after the module checks
                            // (rulings 10, 14 and 27); a word in the place of the offset is out of order (15 of 0.52)
                            hasAt = true;
                            i = rest.size();   // `as` is read here, not by the checks of 0.30
                            String v = rest.size() >= 2 ? rest.get(1) : null;
                            boolean keyed = rest.size() >= 4 && rest.get(2).equals("as") && !rest.get(3).equals("as")
                                    && (rest.size() == 4 || (rest.size() == 5 && rest.get(4).equals("optional")));
                            boolean form = rest.get(0).equals("at") && v != null && !v.equals("at") && !v.equals("as")
                                    && !v.equals("optional") && (rest.size() == 2 || keyed);
                            if (!form) {
                                atBad(format, where + ": a when holding at is when <len> <values> at <n> [as <k> [optional]], got \""
                                        + String.join(" ", rest) + "\"");
                            } else if (!v.matches("[0-9]+") || new java.math.BigInteger(v).bitLength() > 64) {
                                atBad(format, where + ": at takes plain decimal digits that fit 64 bits, got \"" + v + "\"");
                            } else {
                                at = new java.math.BigInteger(v).longValue();
                            }
                            // on a line in the right order the key is read and checked first, even when the offset
                            // alone is bad (ruling 10); on a line whose order is broken it is not read as a key (ruling 28)
                            if (form && keyed) {
                                asKey = rest.get(3);
                                asOptional = rest.size() == 5;
                            }
                        } else if (!rest.get(0).equals("as")) {
                            throw bad(format, null, where + ": a when value list has no spaces: a third token after the length");
                        }
                        if (i < rest.size()) {
                            // engine-spec 0.30, ruling 16: no key, `as` twice (ruling 31), a token after the key
                            List<String> a = rest.subList(i, rest.size());
                            if (a.size() == 1) throw bad(format, null, where + ": as names no key");
                            // engine-spec 0.52: `optional` directly after the key, once and last
                            asOptional = a.size() == 3 && a.get(2).equals("optional");
                            if (a.get(1).equals("as") || (a.size() > 2 && a.get(2).equals("as"))) {
                                throw bad(format, null, where + ": as given twice on one when line");
                            }
                            if (a.size() > 2 && !asOptional) throw bad(format, null, where + ": a token after the key of as: \"" + String.join(" ", a.subList(2, a.size())) + "\"");
                            if (asOptional && f.isBody() && f.kind == null) {
                                throw bad(format, null, where + ": optional is for the as of a kind's when, not of a common when");
                            }
                            asKey = a.get(1);
                        }
                    } else {
                        arity(kw, args, 2, where, format);
                    }
                    int len = bitLength(args.get(0), 1, 64, kw, where, format);
                    boolean isWhen = kw.equals("when");
                    if (isWhen && !f.isBody()) throw bad(format, null, where + ": when inside a block");
                    Node n = new Node(isWhen ? Op.WHEN : Op.CONST, ln);
                    n.len = len;
                    n.hasAt = hasAt;
                    n.asOptional = asOptional;
                    if (hasAt) n.at = at < 0 && atError != null ? 0 : at;   // a malformed offset: the pack is refused later
                    if (isWhen) {
                        // engine-spec 0.20: a list of values and ranges; the first value is written
                        long[] ranges = Pack.numericList(args.get(1), len, format, null, where);
                        n.value = ranges[0];
                        if (ranges.length > 2 || ranges[0] != ranges[1]) n.ranges = ranges;
                    } else {
                        n.value = unsignedValue(args.get(1), len, kw, where, format);
                    }
                    if (asKey != null) {
                        // the key holds the bits read as uint (ruling 7); its type is checked with the field lines
                        // (ruling 17), and it counts as mapped for a switch from here on (ruling 2)
                        Pack.Field fl = new Pack.Field(asKey, args.get(0), null, BitsTransform.parse("uint", format, where),
                                null, null, false, false, false, ln);
                        n.as = fl;
                        fields.add(fl);
                        typed.add(fl);
                        keyRefs.add(new String[]{asKey, null});
                        keyLine(asKey, ln, true);
                        if (f.isBody()) mapped(asKey, n);
                    }
                    if (!isWhen) {
                        f.lines.add(n);
                    } else if (f.kind == null) {
                        // before the first kind: a common when, which must hold for every message (or item)
                        if (f.body.firstCommonWhen == 0) f.body.firstCommonWhen = ln;
                        if (hasAt) {
                            atBad(format, where + ": at is for a when of a kind, not a common when (engine-spec 0.33)");
                            n.hasAt = false;
                            n.at = -1;
                        }
                        f.lines.add(n);
                    } else {
                        if (f.kindLineSeen) throw bad(format, null, where + ": when after another line of its kind");
                        f.kind.whens.add(n);
                        if (hasAt) f.kind.windows.add(n);
                    }
                    break;
                }
                case "pad":
                case "align": {
                    arity(kw, args, 1, where, format);
                    Node n = new Node(kw.equals("pad") ? Op.PAD : Op.ALIGN, ln);
                    n.len = bitLength(args.get(0), 1, Integer.MAX_VALUE, kw, where, format);
                    f.lines.add(n);
                    break;
                }
                case "presence": {
                    arity(kw, args, 2, where, format);
                    String name = args.get(0);
                    if (name.isEmpty() || name.indexOf('.') >= 0 || name.startsWith("!")) {
                        throw bad(format, null, where + ": a presence name is not empty, has no \".\" and does not start with \"!\"");
                    }
                    if (f.type == 'E' && !f.lines.isEmpty()) {
                        uperBad(format, null, where + ": inside an ext block a presence line is the first line");
                    }
                    Node n = new Node(Op.PRESENCE, ln);
                    n.name = name;
                    n.fx = args.get(1).equals("fx");
                    if (!n.fx) n.len = bitLength(args.get(1), 1, 64, "presence", where, format);
                    Map<String, Node> names = f.kindNames != null ? f.kindNames : f.names;
                    if (names.containsKey(name) || f.names.containsKey(name)) {
                        throw bad(format, null, where + ": presence " + name + " is declared twice in one block");
                    }
                    n.id = presences++;
                    names.put(name, n);
                    f.lines.add(n);
                    break;
                }
                case "count": {
                    // engine-spec 0.21: count <name> <len> [plus <n>]
                    String form = where + ": a count line is count <name> <len> [plus <n>]";
                    if (args.size() < 2) throw bad(format, null, form);
                    String name = args.get(0);
                    if (name.isEmpty() || name.indexOf('.') >= 0 || name.indexOf('!') >= 0 || name.indexOf('@') >= 0) {
                        throw bad(format, null, where + ": a count name is not empty and has no \".\", \"!\" or \"@\" (ruling 24 of 0.21)");
                    }
                    Node n = new Node(Op.COUNT, ln);
                    n.name = name;
                    n.len = bitLength(args.get(1), 1, 64, "count", where, format);
                    if (args.size() == 4 && args.get(2).equals("plus")) {
                        // an optional - then digits, leading zeros allowed, within signed 64 bits (ruling 16 of 0.21)
                        String v = args.get(3);
                        if (!v.matches("-?\\d+")) throw bad(format, null, where + ": plus takes an integer, got \"" + v + "\"");
                        try {
                            n.plus = Long.parseLong(v);
                        } catch (NumberFormatException ex) {
                            throw bad(format, null, where + ": plus " + v + " is not within signed 64 bits");
                        }
                    } else if (args.size() != 2) {
                        throw bad(format, null, form);
                    }
                    Map<String, Node> names = f.kindNames != null ? f.kindNames : f.names;
                    if (names.containsKey(name) || f.names.containsKey(name)) {
                        throw bad(format, null, where + ": the name " + name + " is declared twice in one block");
                    }
                    names.put(name, n);
                    f.lines.add(n);
                    break;
                }
                case "if": {
                    if (args.isEmpty()) throw bad(format, null, where + ": if names at least one presence bit");
                    Node n = new Node(Op.IF, ln);
                    n.refPresence = new Node[args.size()];
                    n.refBit = new int[args.size()];
                    n.refNot = new boolean[args.size()];
                    for (int i = 0; i < args.size(); i++) {
                        String a = args.get(i);
                        boolean not = a.startsWith("!");
                        if (not) a = a.substring(1);
                        int dot = a.lastIndexOf('.');
                        if (dot < 1 || !a.substring(dot + 1).matches("\\d{1,9}")) {
                            throw bad(format, null, where + ": if names bits as <name>.<i>, got \"" + args.get(i) + "\"");
                        }
                        Node p = lookup(a.substring(0, dot));
                        if (p == null) throw bad(format, null, where + ": if names presence " + a.substring(0, dot) + ", which is not visible here");
                        if (p.op == Op.COUNT) throw bad(format, null, where + ": if names " + p.name + ", which is a count, not a presence (ruling 15 of 0.21)");
                        int bit = Integer.parseInt(a.substring(dot + 1));
                        if (bit < 1 || bit > (p.fx ? MAX_FX_BIT : p.len)) {
                            throw bad(format, null, where + ": presence " + p.name + " has no bit " + bit);
                        }
                        if (lookupCase == null) p.named.set(bit);
                        else p.caseNamed.computeIfAbsent(bit, k -> new ArrayList<>()).add(lookupCase);
                        p.anyNamed.set(bit);
                        n.refPresence[i] = p;
                        n.refBit[i] = bit;
                        n.refNot[i] = not;
                    }
                    n.body = new ArrayList<>();
                    f.lines.add(n);
                    push('I', "if", ln, n, n.body);
                    break;
                }
                case "opt": {
                    arity(kw, args, 0, where, format);
                    Node n = new Node(Op.OPT, ln);
                    n.body = new ArrayList<>();
                    f.lines.add(n);
                    push('O', "opt", ln, n, n.body);
                    break;
                }
                case "chain": {
                    arity(kw, args, 0, where, format);
                    Node n = new Node(Op.CHAIN, ln);
                    n.parts = new ArrayList<>();
                    n.parts.add(new ArrayList<>());
                    f.lines.add(n);
                    push('C', "chain", ln, n, n.parts.get(0));
                    break;
                }
                case "fx": {
                    arity(kw, args, 0, where, format);
                    if (f.type != 'C') throw bad(format, null, where + ": fx is a line of a chain");
                    List<Node> part = new ArrayList<>();
                    f.node.parts.add(part);
                    f.lines = part;
                    break;
                }
                case "length": {
                    if (!args.isEmpty() && (args.get(0).startsWith("@") || args.contains("units"))) {
                        // engine-spec 0.83: length @<name> units <u>; every error of the form is a check after the file
                        if (args.size() != 3 || !args.get(0).startsWith("@") || !args.get(1).equals("units")) {
                            throw bad(format, null, where + ": a length sized by a count is length @<name> units <u>");
                        }
                        String name = args.get(0).substring(1);
                        Node c = name.isEmpty() ? null : lookupCount(name);
                        if (c == null) throw bad(format, null, where + ": length @" + name + " names no count visible here");
                        if (c.op != Op.COUNT) throw bad(format, null, where + ": length @" + name + " names a presence, not a count");
                        Node n = new Node(Op.LENGTH, ln);
                        n.countRef = c;
                        n.unit = bitLength(args.get(2), 1, 65535, "units", where, format);
                        n.inBits = n.unit % 8 != 0;
                        bodyFrame().body.unitBlocks = true;
                        f.lines.add(n);
                        n.body = new ArrayList<>();
                        push('L', "length", ln, n, n.body);
                        break;
                    }
                    if (args.isEmpty()) throw bad(format, null, where + ": length is length <len> [bytes|bits] [plus <n>] [whole]");
                    int len = bitLength(args.get(0), 1, 64, "length", where, format);
                    boolean bytes = false, bits = false, whole = false;
                    Long plus = null;
                    for (int i = 1; i < args.size(); i++) {
                        String o = args.get(i);
                        if (o.equals("bytes") && !bytes && !bits) bytes = true;
                        else if (o.equals("bits") && !bytes && !bits) bits = true;
                        else if (o.equals("whole") && !whole) whole = true;
                        else if (o.equals("plus") && plus == null && i + 1 < args.size() && Transform.INT_TEXT.matcher(args.get(i + 1)).matches()
                                && args.get(i + 1).replaceFirst("^-?0*", "").length() <= 18) {
                            plus = Transform.parseInt(args.get(++i));   // integer text (ruling 2c of 0.11)
                        } else {
                            throw bad(format, null, where + ": length is length <len> [bytes|bits] [plus <n>] [whole], got \"" + o + "\"");
                        }
                    }
                    if (whole && bits) throw bad(format, null, where + ": length ... whole counts bytes; bits with whole is not allowed");
                    Node n = new Node(whole ? Op.WHOLE : Op.LENGTH, ln);
                    n.len = len;
                    n.inBits = bits;
                    n.plus = plus == null ? 0 : plus;
                    f.lines.add(n);
                    if (!whole) {
                        n.body = new ArrayList<>();
                        push('L', "length", ln, n, n.body);
                    }
                    break;
                }
                case "group": {
                    String form = "a group of a sequential pack is group <list> count <len> | count @<name> [@<name>] | while | more | fx | rest | last";
                    if (args.size() < 2) {
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": group takes at least 2 arguments, got " + args.size());
                    }
                    Node n = new Node(Op.GROUP, ln);
                    n.list = args.get(0);
                    String mode = args.get(1);
                    if (mode.equals("count") && args.size() >= 3 && args.get(2).startsWith("@")) {
                        // a count named earlier in this group body (rulings 9, 12, 15 and 24 of 0.21); engine-spec 0.31:
                        // one list may name two counts, `count @<a> @<b>`, which must agree on decode
                        if (args.size() > 4) throw bad(format, mode, where + ": count names at most two counts, got " + (args.size() - 2) + " tokens");
                        if (args.size() == 4 && !args.get(3).startsWith("@")) {
                            throw bad(format, mode, where + ": every token after count is @<name> when the first is, got \"" + args.get(3) + "\"");
                        }
                        Node[] refs = new Node[args.size() - 2];
                        for (int i = 0; i < refs.length; i++) {
                            String name = args.get(2 + i).substring(1);
                            Node c = name.isEmpty() ? null : lookupCount(name);
                            if (c == null) throw bad(format, mode, where + ": count @" + name + " names no count visible here in this group body");
                            if (c.op != Op.COUNT) throw bad(format, mode, where + ": count @" + name + " names a presence, not a count");
                            if (i == 1 && c == refs[0]) throw bad(format, mode, where + ": count names @" + name + " twice");
                            refs[i] = c;
                        }
                        n.repeat = Repeat.REF;
                        n.countRef = refs[0];
                        if (refs.length == 2) n.countRef2 = refs[1];
                    } else if (mode.equals("count") && args.size() == 3) {
                        n.repeat = Repeat.COUNT;
                        n.len = bitLength(args.get(2), 1, 64, "count", where, format);
                    } else if (args.size() == 2 && (mode.equals("while") || mode.equals("more") || mode.equals("fx")
                            || mode.equals("rest") || mode.equals("last"))) {
                        n.repeat = mode.equals("while") ? Repeat.WHILE : mode.equals("more") ? Repeat.MORE
                                : mode.equals("fx") ? Repeat.FX : mode.equals("rest") ? Repeat.REST : Repeat.LAST;
                    } else if (mode.equals("size") && (args.size() == 2 || args.size() == 4)) {
                        uper(ln);
                        n.repeat = Repeat.SIZE;
                        if (args.size() == 4) {
                            long lb = count(args.get(2), 65535), ub = count(args.get(3), 65535);
                            if (lb < 0 || ub < 0 || lb > ub) {
                                uperBad(format, mode, where + ": group ... size <lb> <ub> takes 0 <= lb <= ub < 65536, got "
                                        + args.get(2) + " " + args.get(3));
                                lb = 0;
                                ub = 0;
                            }
                            n.sized = true;
                            n.lb = lb;
                            n.ub = ub;
                        }
                    } else {
                        throw bad(format, mode, where + ": " + form);
                    }
                    if (n.repeat == Repeat.REST) {
                        // inside an item, only within a length block of the item's body, or in the item of an outer
                        // rest group (ruling 10 of 0.21)
                        for (Frame x : stack) {
                            if (x.type == 'L' || x.type == 'M') break;
                            if (x.type == 'G') {
                                if (x.node.repeat != Repeat.REST) {
                                    throw bad(format, mode, where + ": a rest group inside an item of " + x.node.list
                                            + " is allowed only within a length block of the item");
                                }
                                break;
                            }
                        }
                    }
                    // Within one scope (common plus one kind, or one group body) two groups map one list only when
                    // they sit in if or opt blocks neither of which encloses the other (rulings 23 and 33 of 0.8).
                    Frame b = bodyFrame();
                    List<Frame> blocks = new ArrayList<>();
                    for (Frame x : stack) {
                        if (x.isBody()) break;
                        if (x.type == 'I' || x.type == 'O' || x.type == 'K') blocks.add(x);   // a case is a block (ruling 10 of 0.20)
                        // each alt of a choice is a block of its own here (ruling 20 of 0.19)
                        if (x.type == 'H' && x.alt != null) blocks.add(x.alt);
                    }
                    Map<String, List<List<Frame>>> lists = b.kindLists != null ? b.kindLists : b.lists;
                    List<List<Frame>> others = lists.computeIfAbsent(n.list, k -> new ArrayList<>());
                    for (List<Frame> o : others) {
                        if (blocks.isEmpty() || o.isEmpty() || o.contains(blocks.get(0)) || blocks.contains(o.get(0))) {
                            throw bad(format, mode, where + ": list " + n.list
                                    + " is mapped by two groups of one scope that are not in different if or opt blocks or alts");
                        }
                    }
                    others.add(blocks);
                    n.items = new Body();
                    f.lines.add(n);
                    typed.add(new Pack.Group(n.list, mode, new Pack.Scope(new ArrayList<>(), new LinkedHashMap<>()), 0, null, -1, ln));
                    keyRefs.add(new String[]{n.list, null});
                    Frame g = new Frame('G', "group " + n.list, ln, n, n.items.common);
                    g.body = n.items;
                    stack.push(g);
                    break;
                }
                case "ext": {
                    arity(kw, args, 0, where, format);
                    uper(ln);
                    Node n = new Node(Op.EXT, ln);
                    n.body = new ArrayList<>();
                    f.lines.add(n);
                    push('E', "ext", ln, n, n.body);
                    break;
                }
                case "choice": {
                    uper(ln);
                    Node n = new Node(Op.CHOICE, ln);
                    boolean ok = (args.size() == 1 || (args.size() == 2 && args.get(1).equals("ext")));
                    long alts = ok ? count(args.get(0), 65536) : -1;
                    if (alts < 1) {
                        uperBad(format, null, where + ": choice is choice <n> [ext], n from 1 to 65536");
                        alts = 65536;
                    }
                    n.alts = (int) alts;
                    n.ext = args.size() == 2;
                    f.lines.add(n);
                    push('H', "choice", ln, n, null);
                    break;
                }
                case "alt": {
                    uper(ln);
                    if (f.type != 'H') {
                        uperBad(format, null, where + ": alt is a line of a choice");
                        break;
                    }
                    long i = args.size() == 1 ? count(args.get(0), 65535) : -1;
                    if (i < 0 || i >= f.node.alts) {
                        uperBad(format, null, where + ": alt takes an index from 0 to " + (f.node.alts - 1));
                    } else if (f.node.altAt.containsKey((int) i)) {
                        uperBad(format, null, where + ": alt " + i + " is given twice");
                    } else {
                        f.node.altAt.put((int) i, f.node.altLines.size());
                    }
                    List<Node> part = new ArrayList<>();
                    f.node.altIndex.add((int) i);
                    f.node.altLines.add(part);
                    f.lines = part;
                    f.names.clear();   // each alt is its own block for presence names
                    f.alt = new Frame('A', "alt", ln, null, part);
                    break;
                }
                case "kind": {
                    arity(kw, args, 1, where, format);
                    if (!f.isBody()) throw bad(format, null, where + ": kind inside the open " + f.what + " of line " + f.line);
                    if (f.body.kind(args.get(0)) != null) {
                        throw new GtException(GtException.Code.DUPLICATE_KIND, format, null, where + ": kind " + args.get(0) + " is declared twice");
                    }
                    Kind k = new Kind(args.get(0));
                    f.body.kinds.add(k);
                    f.kind = k;
                    f.lines = k.lines;
                    f.kindNames = new HashMap<>();
                    f.kindLists = new HashMap<>();
                    f.kindMapped = new HashMap<>(f.mapped);
                    for (Map.Entry<String, List<List<Frame>>> l : f.lists.entrySet()) {
                        f.kindLists.put(l.getKey(), new ArrayList<>(l.getValue()));
                    }
                    f.kindLineSeen = false;
                    break;
                }
                case "requires": {
                    if (args.isEmpty()) {
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": requires takes at least 1 argument, got 0");
                    }
                    if (!f.isBody()) throw bad(format, null, where + ": requires inside a block");
                    if (f.kind == null) throw bad(format, null, where + ": requires before the first kind line");
                    for (String k : args) f.kind.requires.add(Pack.requireTerm(k, ln, where, format, keyRefs, valueLists));
                    break;
                }
                case "default": {
                    arity(kw, args, 2, where, format);
                    Frame c = null;   // the innermost case, when nearer than the body (rulings 7 and 22 of 0.20)
                    for (Frame x : stack) {
                        if (x.isBody()) break;
                        if (x.type == 'K') { c = x; break; }
                    }
                    Frame b = bodyFrame();
                    if (c != null) c.kase.defaults.put(args.get(0), args.get(1));
                    else (b.kind != null ? b.kind.defaults : b.body.defaults).put(args.get(0), args.get(1));
                    keyRefs.add(new String[]{args.get(0), null});
                    break;
                }
                case "inner": {
                    // engine-spec 0.34: in the common lines, a kind, or length blocks at any depth; under any other
                    // block it is bad-directive, checked after the file is read
                    inners.add(args.get(0));
                    boolean partial = args.size() > 1 && args.get(1).equals("partial"), run = args.size() > 1 && args.get(1).equals("run");
                    carrier |= run;
                    if (args.size() > 1 && !partial && !run && innerWhy == null) {
                        innerWhy = where + ": the second argument of inner is partial or run, got \"" + args.get(1) + "\"";
                    }
                    Frame under = null;
                    for (Frame x : stack) {
                        if (x.type != 'M' && x.type != 'L') { under = x; break; }
                    }
                    if (under != null) {
                        if (innerWhy == null) {
                            innerWhy = where + ": inner stands under the " + under.what + " of line " + under.line
                                    + "; it is a line of the common lines, a kind or a length block only";
                        }
                        break;
                    }
                    Node n = new Node(Op.INNER, ln);
                    n.name = args.get(0);
                    n.partial = partial;
                    n.run = run;
                    f.lines.add(n);
                    break;
                }
                case "switch": {
                    if (args.size() != 1) throw bad(format, null, where + ": switch takes one model key, got " + args.size());
                    String key = args.get(0);
                    Frame b = bodyFrame();
                    Map<String, Node> seen = b.kindMapped != null ? b.kindMapped : b.mapped;
                    if (!seen.containsKey(key)) {
                        throw bad(format, null, where + ": switch key " + key + " is not mapped by a field or also line before it in its scope");
                    }
                    Node n = new Node(Op.SWITCH, ln);
                    n.switchKey = key;
                    n.keyLine = seen.get(key);
                    n.cases = new ArrayList<>();
                    f.lines.add(n);
                    push('S', "switch " + key, ln, n, null);
                    break;
                }
                default:
                    throw new IllegalStateException(kw);
            }
        }

        /**
         * A {@code field <key> until:<code> chars:<set>} line (engine-spec 0.22): the characters run to the terminator.
         * Only {@code chars:<set>} takes it; {@code absent}, {@code swap}, {@code trim} and {@code stop} are refused.
         */
        private void untilField(Frame f, String key, String locator, String tname, List<String> args, int ln, String where, String format) {
            BitsTransform bt = BitsTransform.isBitsName(tname) ? BitsTransform.parse(tname, format, where) : null;
            if (bt == null || !bt.isCharSet()) {
                throw bad(format, locator, where + ": until: is for a chars:<set> field, got \"" + tname + "\"");
            }
            String via = null, with = null;
            for (int i = 3; i < args.size(); i++) {
                String o = args.get(i);
                if (o.equals("with") && with == null && i + 1 < args.size()) with = args.get(++i);
                else if (o.equals("via") && via == null && i + 1 < args.size()) via = args.get(++i);
                else if (o.equals("absent") || o.equals("swap") || o.equals("trim") || o.equals("stop")) {
                    throw bad(format, locator, where + ": " + o + " is not an option of an until: field (engine-spec 0.22)");
                } else if (o.equals("optional")) throw bad(format, locator, where + ": optional is not a field option of a sequential pack");
                else throw bad(format, locator, where + ": unknown or repeated field option \"" + o + "\"");
            }
            // the terminator: plain digits that fit the set's width (ruling 23 of 0.22)
            bt.stop = -1;
            int code = Pack.stopCode(locator.substring("until:".length()), bt, format, locator, where);
            if (via != null) vias.add(new String[]{via, locator, where});
            Pack.Field fl = new Pack.Field(key, locator, null, bt, null, via, false, false, false, ln);
            fl.with = with;
            fields.add(fl);
            typed.add(fl);
            keyRefs.add(new String[]{key, locator});
            if (with != null) keyRefs.add(new String[]{with, locator});
            Node n = new Node(Op.FIELD, ln);
            mapped(key, n);
            keyLine(key, ln, false);
            n.until = code;
            n.keys = new ArrayList<>();
            n.keys.add(fl);
            f.lines.add(n);
            f.lastField = n;
        }

        /** A {@code field} line with a UPER locator (0.19). */
        private void uperField(Frame f, String key, String locator, String tname, List<String> args, int ln, String where, String format) {
            uper(ln);
            Object parsed = parseUper(locator);
            Uper u;
            if (parsed instanceof Uper) {
                u = (Uper) parsed;
            } else {
                uperBad(format, locator, where + ": " + parsed);
                u = new Uper(UKind.INT_FREE, false, false, 0, 0);
            }
            if (!isKnownTransform(tname)) {
                throw new GtException(GtException.Code.UNKNOWN_TRANSFORM, format, locator, where + ": unknown transform \"" + tname + "\"");
            }
            boolean ok = takes(u, tname);
            if (!ok) uperBad(format, locator, where + ": transform \"" + tname + "\" is not one the locator " + locator + " takes");
            String via = null;
            for (int i = 3; i < args.size(); i++) {
                String o = args.get(i);
                if (o.equals("via") && via == null && i + 1 < args.size()) via = args.get(++i);
                else if (o.equals("absent")) {
                    // ruling 22 of 0.19: the bits of a UPER field depend on its value, no raw sentinel
                    if (i + 1 < args.size()) i++;   // the token after `absent` is its argument (ruling 11 of 0.9)
                    uperBad(format, locator, where + ": absent is not an option of a UPER locator");
                }
                else if (o.equals("swap") || o.equals("trim")) uperBad(format, locator, where + ": " + o + " is not an option of a UPER locator");
                else if (o.equals("optional")) throw bad(format, locator, where + ": optional is not a field option of a sequential pack");
                else throw bad(format, locator, where + ": unknown or repeated field option \"" + o + "\"");
            }
            BitsTransform bt = null;
            TlvTransform tt = null;
            if (!ok) {
                bt = BitsTransform.parse("uint", format, where);   // the pack is refused; kept only to read on
            } else if (u.kind == UKind.OCTETS) {
                tt = TlvTransform.parse(tname, format, where);
            } else {
                bt = BitsTransform.parse(tname, format, where);
            }
            if (via != null) vias.add(new String[]{via, locator, where});
            Pack.Field fl = new Pack.Field(key, locator, null, bt, null, via, false, false, false, ln);
            fl.tlv = tt;
            fields.add(fl);
            typed.add(fl);
            keyRefs.add(new String[]{key, locator});
            keyLine(key, ln, false);
            Node n = new Node(Op.FIELD, ln);
            n.u = u;
            n.keys = new ArrayList<>();
            n.keys.add(fl);
            f.lines.add(n);
            f.lastField = n;
        }

        /** A {@code case} or {@code else} line: it ends the case before it and opens its own. */
        private void switchArm(String kw, List<String> args, int ln, String where, String format) {
            Frame f = stack.peek();
            if (f.type == 'K') {
                stack.pop();
                f = stack.peek();
            }
            if (f.type != 'S') throw bad(format, null, where + ": " + kw + " outside a switch");
            Node sw = f.node;
            if (sw.elseCase != null) throw bad(format, null, where + ": " + (kw.equals("else") ? "two else lines" : "case after the else") + " in one switch");
            Case c;
            if (kw.equals("else")) {
                if (!args.isEmpty()) throw bad(format, null, where + ": else takes no value");
                if (sw.cases.isEmpty()) throw bad(format, null, where + ": else before a case");
                c = new Case(ln, null);
                sw.elseCase = c;
            } else {
                if (args.size() != 1) throw bad(format, null, where + ": case takes one value list, got " + args.size() + " tokens");
                List<Pack.ValueList> earlier = new ArrayList<>();
                for (Case o : sw.cases) earlier.add(o.values);
                Pack.ValueList vl = new Pack.ValueList(sw.switchKey, Pack.valueItems(args.get(0), where, format), ln, where, earlier);
                valueLists.add(vl);
                c = new Case(ln, vl);
                sw.cases.add(c);
            }
            scopes.add(c.scope);
            Frame k = new Frame('K', kw, ln, sw, c.body);
            k.kase = c;
            stack.push(k);
        }

        private void finishBody(Body body, String format, String where) {
            body.hasKinds = !body.kinds.isEmpty();
            if (!body.hasKinds) {
                if (body.firstCommonWhen != 0) {
                    throw bad(format, null, source + ":" + body.firstCommonWhen + ": when in a body with no kind line (" + where + ")");
                }
                body.kinds.add(new Kind(null));
            }
            for (Kind k : body.kinds) {
                List<Node> all = new ArrayList<>(body.common.size() + k.whens.size() + k.lines.size());
                all.addAll(body.common);
                all.addAll(k.whens);
                all.addAll(k.lines);
                k.all = Collections.unmodifiableList(all);
                LinkedHashMap<String, String> defaults = new LinkedHashMap<>(body.defaults);
                defaults.putAll(k.defaults);
                k.scope = new Pack.Scope(new ArrayList<>(), defaults);
                scopes.add(k.scope);
                windows(k, format);
            }
        }

        /**
         * engine-spec 0.33: each window of the kind is fixed in it. Walk the kind's own lines from its first, skipping
         * the {@code when ... at} lines, summing the lengths of the others until the sum reaches the window's end;
         * every line walked is a plain {@code when}, {@code const}, {@code pad} or a {@code field} of a bit length.
         * Records the number of lines that cover every window, where encode settles them.
         */
        private void windows(Kind k, String format) {
            List<Node> own = new ArrayList<>(k.whens);
            own.addAll(k.lines);
            for (Node w : k.windows) {
                // the window's end, kind start plus offset plus len; an offset near 2^64 is past every line
                long end = Long.compareUnsigned(w.at, Long.MAX_VALUE - 128) > 0 ? Long.MAX_VALUE : w.at + w.len;
                long sum = 0;
                boolean fixed = false;
                int i = 0;
                for (; i < own.size(); i++) {
                    Node n = own.get(i);
                    if (n.op == Op.WHEN && n.hasAt) continue;
                    boolean ok = (n.op == Op.WHEN) || n.op == Op.CONST || n.op == Op.PAD
                            || (n.op == Op.FIELD && n.u == null && n.until < 0);
                    if (!ok) break;
                    sum += n.len;
                    if (sum >= end) {
                        fixed = true;
                        break;
                    }
                }
                if (!fixed) {
                    if (windowError == null) {
                        windowError = bad(format, null, source + ":" + w.line + ": the window of when ... at " + Long.toUnsignedString(w.at)
                                + " is not fixed in its kind: " + (i < own.size() ? "line " + own.get(i).line
                                + " before its end does not have a fixed width" : "it ends past the kind's last line"));
                    }
                    continue;
                }
                k.prefix = Math.max(k.prefix, i + 1);
            }
        }

        /** The field lines whose transform and length are checked after the file: {field, transform, len, where}. */
        private final List<Object[]> afterFile = new ArrayList<>();

        // ---- counts (rulings 2 and 33 of 0.21) ----
        // The possible numbers of references on the reading paths of a range, as a mask: bit i set when some path
        // holds i references (2 standing for two or more).

        private static int combine(int a, int b) {
            int out = 0;
            for (int i = 0; i < 3; i++) {
                if ((a & (1 << i)) == 0) continue;
                for (int j = 0; j < 3; j++) if ((b & (1 << j)) != 0) out |= 1 << Math.min(i + j, 2);
            }
            return out;
        }

        /** The reference counts to count line {@code c} on the paths of {@code lines} from {@code from}. */
        private static int refs(List<Node> lines, int from, Node c) {
            int m = 1;
            for (int i = from; i < lines.size(); i++) m = combine(m, refs(lines.get(i), c));
            return m;
        }

        private static int refs(Node n, Node c) {
            switch (n.op) {
                case GROUP:
                    // a reference stays in its group body (ruling 9): an item body holds none to c
                    return n.countRef == c || n.countRef2 == c ? 2 : 1;
                case LENGTH:
                    // length @<name> is a reference as a group is (ruling 1 of 0.83)
                    return n.countRef == c ? combine(2, refs(n.body, 0, c)) : refs(n.body, 0, c);
                case IF:
                case OPT:
                case EXT:   // a SEQUENCE's extension block (0.19) is read in the same path
                    return refs(n.body, 0, c);
                case CHAIN:
                    return refs(chainLines(n), 0, c);
                case CHOICE: {
                    // the alts of a choice (0.19) do not split a reading path: references in two alts are two
                    // (ruling 40 of 0.21)
                    int m = 1;
                    for (List<Node> alt : n.altLines) m = combine(m, refs(alt, 0, c));
                    return m;
                }
                case SWITCH: {
                    // each case is a reading path of its own; an if or opt does not split a path (ruling 33)
                    int m = 0;
                    for (Case k : n.cases) m |= refs(k.body, 0, c);
                    if (n.elseCase != null) m |= refs(n.elseCase.body, 0, c);
                    return m;
                }
                default:
                    return 1;
            }
        }

        private static List<Node> chainLines(Node n) {
            List<Node> all = new ArrayList<>();
            for (List<Node> part : n.parts) all.addAll(part);
            return all;
        }

        /** Every count line is referenced exactly once on each reading path of its range. */
        private void checkCounts(Body b, String format) {
            countsIn(b.common, b, format);
            for (Kind k : b.kinds) countsIn(k.lines, null, format);
        }

        /** {@code common}: the body when {@code lines} are its common lines, whose range runs on into every kind. */
        private void countsIn(List<Node> lines, Body common, String format) {
            for (int i = 0; i < lines.size(); i++) {
                Node n = lines.get(i);
                switch (n.op) {
                    case COUNT: {
                        int m = refs(lines, i + 1, n);
                        if (common != null && common.hasKinds) {
                            int all = 0;
                            for (Kind k : common.kinds) all |= combine(m, refs(k.lines, 0, n));
                            m = all;
                        }
                        if (m != 2) {
                            throw bad(format, null, source + ":" + n.line + ": count " + n.name
                                    + " must be referenced by exactly one group ... count @" + n.name + " or length @" + n.name + " on each reading path");
                        }
                        break;
                    }
                    case IF:
                    case OPT:
                    case LENGTH:
                    case EXT:
                        countsIn(n.body, null, format);
                        break;
                    case CHOICE:
                        for (List<Node> alt : n.altLines) countsIn(alt, null, format);
                        break;
                    case CHAIN:
                        countsIn(chainLines(n), null, format);
                        break;
                    case SWITCH:
                        for (Case k : n.cases) countsIn(k.body, null, format);
                        if (n.elseCase != null) countsIn(n.elseCase.body, null, format);
                        break;
                    case GROUP:
                        checkCounts(n.items, format);
                        break;
                    default:
                        break;
                }
            }
        }

        // ---- rest is the last line of its extent (rulings 11, 26, 27 and 32 of 0.21) ----

        /** A line that reads or writes bits; an if, switch or chain is one only when it holds one. */
        private static boolean isWire(Node n) {
            switch (n.op) {
                case IF:
                    return anyWire(n.body);
                case SWITCH:
                    for (Case k : n.cases) if (anyWire(k.body)) return true;
                    return n.elseCase != null && anyWire(n.elseCase.body);
                case CHAIN:
                    return n.parts.size() > 1 || n.endsWithFx || anyWire(chainLines(n));
                case CHOICE:
                    // with ext, more than one root alternative, or an alt holding a wire line (ruling 41 of 0.21)
                    if (n.ext || n.alts > 1) return true;
                    for (List<Node> alt : n.altLines) if (anyWire(alt)) return true;
                    return false;
                default:
                    return true;   // an ext block reads its extension bit (ruling 41 of 0.21)
            }
        }

        private static boolean anyWire(List<Node> lines) {
            for (Node n : lines) if (isWire(n)) return true;
            return false;
        }

        private void checkRest(Body b, String format) {
            boolean sealed = restIn(b.common, false, format);
            for (Kind k : b.kinds) {
                restIn(k.whens, sealed, format);   // a kind's when lines are wire lines (ruling 32)
                restIn(k.lines, sealed, format);
            }
        }

        /** Walk {@code lines} in reading order; true when a rest group has been passed in this extent. */
        private boolean restIn(List<Node> lines, boolean sealed, String format) {
            for (Node n : lines) {
                if (sealed && isWire(n)) {
                    throw bad(format, null, source + ":" + n.line + ": a line after a rest group or an inner line in its extent (ruling 11 of 0.21, engine-spec 0.34)");
                }
                switch (n.op) {
                    case GROUP:
                        checkRest(n.items, format);
                        if (n.repeat == Repeat.REST) sealed = true;
                        break;
                    case INNER:
                        sealed = true;   // inner is the last wire line of its extent, as rest is (engine-spec 0.34)
                        break;
                    case IF:
                    case OPT:
                    case EXT:
                        sealed |= restIn(n.body, sealed, format);
                        break;
                    case CHOICE: {
                        boolean s = sealed;
                        for (List<Node> alt : n.altLines) s |= restIn(alt, sealed, format);
                        sealed = s;
                        break;
                    }
                    case LENGTH:
                        restIn(n.body, false, format);   // an extent of its own
                        break;
                    case CHAIN: {
                        boolean s = sealed;
                        for (int i = 0; i < n.parts.size(); i++) {
                            if (i > 0 && s) {
                                throw bad(format, null, source + ":" + n.line + ": an fx line after a rest group in its extent (ruling 11 of 0.21)");
                            }
                            s = restIn(n.parts.get(i), s, format);
                        }
                        if (n.endsWithFx && s) {
                            throw bad(format, null, source + ":" + n.line + ": an fx line after a rest group in its extent (ruling 11 of 0.21)");
                        }
                        sealed = s;
                        break;
                    }
                    case SWITCH: {
                        boolean s = sealed;
                        for (Case k : n.cases) s |= restIn(k.body, sealed, format);
                        if (n.elseCase != null) s |= restIn(n.elseCase.body, sealed, format);
                        sealed = s;
                        break;
                    }
                    default:
                        break;
                }
            }
            return sealed;
        }

        /**
         * {@code framing self} (engine-spec 0.92, ruling 16): a rest group whose extent is the message needs a
         * {@code length ... whole} before it that is read whenever it is.
         */
        void checkFraming(String format) {
            boolean whole = framed(root.common, false, format);
            for (Kind k : root.kinds) framed(k.lines, whole, format);
        }

        /** Walk lines of one block outside every {@code length}; true when a whole was passed in them or before them. */
        private boolean framed(List<Node> lines, boolean whole, String format) {
            for (Node n : lines) {
                switch (n.op) {
                    case WHOLE:
                        whole = true;
                        break;
                    case GROUP:
                        if (n.repeat == Repeat.REST && !whole) {
                            throw bad(format, null, source + ":" + n.line + ": framing self: a rest group of the message without a length ... whole before it");
                        }
                        break;   // a rest in an item is judged by the rest its group stands in
                    case IF:
                    case OPT:
                    case EXT:
                        framed(n.body, whole, format);
                        break;
                    case CHAIN: {
                        boolean w = whole;   // a part is read only when the parts before it are
                        for (List<Node> part : n.parts) w = framed(part, w, format);
                        break;
                    }
                    case CHOICE:
                        for (List<Node> alt : n.altLines) framed(alt, whole, format);
                        break;
                    case SWITCH:
                        for (Case c : n.cases) framed(c.body, whole, format);
                        if (n.elseCase != null) framed(n.elseCase.body, whole, format);
                        break;
                    default:
                        break;   // a length block is an extent of its own
                }
            }
            return whole;
        }

        // ---- at most one inner line on a reading path (engine-spec 0.34, ruling 33 of 0.21) ----

        /** The inner lines of {@code lines}, in length blocks at any depth, in reading order. */
        private static void innersIn(List<Node> lines, List<Node> out) {
            for (Node n : lines) {
                if (n.op == Op.INNER) out.add(n);
                else if (n.op == Op.LENGTH) innersIn(n.body, out);
            }
        }

        /** A reading path is the common lines and one kind: it holds at most one inner line. */
        private void checkInnerPaths(Body b, String format) {
            List<Node> common = new ArrayList<>();
            innersIn(b.common, common);
            for (Kind k : b.kinds) {
                List<Node> path = new ArrayList<>(common);
                innersIn(k.lines, path);
                if (path.size() > 1) {
                    throw bad(format, null, source + ":" + path.get(1).line + ": a second inner line on one reading path (the first at line "
                            + path.get(0).line + ")");
                }
            }
        }

        /**
         * The checks that need the whole file: every block is ended, each field's transform is a transform of the
         * bits wire and allows its length (ruling 25 of 0.5), and every table a line names has a map line.
         */
        Body finish(Map<String, List<String[]>> tables, Map<String, CodeSeq.CharSet> charsets, String format) {
            if (stack.size() > 1) {
                Frame f = stack.peek();
                throw bad(format, null, source + ":" + f.line + ": " + f.what + " has no end");
            }
            for (Object[] a : afterFile) {
                Pack.Field fl = (Pack.Field) a[0];
                String tname = (String) a[1], where = (String) a[3];
                int len = (Integer) a[2];
                if (fl.bits == null) throw bad(format, fl.locator, where + ": transform \"" + tname + "\" is not valid on wire bits");
                if (fl.trim && !fl.bits.takesTrim()) throw bad(format, fl.locator, where + ": trim is for the ascii and sixbit transforms only");
                if (fl.swap && fl.bits.isSixbit()) throw bad(format, fl.locator, where + ": swap is not an option of sixbit");
                if (fl.swap && fl.bits.refusesSwap()) throw bad(format, fl.locator, where + ": swap is not allowed with " + tname);
                fl.bits.bindCodes(charsets, format, fl.locator, where);
                String lenWhy = fl.bits.checkLen(len);
                if (lenWhy != null) throw bad(format, fl.locator, where + ": " + lenWhy);
                if (fl.swap && len % 8 != 0) throw bad(format, fl.locator, where + ": swap needs a length that is a multiple of 8, got " + len);
                // the absent option of a field above 64 bits, which the line check leaves (ruling 4d of 0.11)
                if (a[4] != null && len > 64) Sentinels.integers((String) a[4], len, format, fl.locator, where);
            }
            if (innerWhy != null) throw bad(format, null, innerWhy);
            finishBody(root, format, source);
            checkCounts(root, format);
            checkInnerPaths(root, format);
            checkRest(root, format);
            for (String[] v : vias) {
                if (!tables.containsKey(v[0])) throw bad(format, v[1], v[2] + ": via names table " + v[0] + ", which has no map line");
            }
            fields.sort((a, b) -> Integer.compare(a.line, b.line));
            typed.sort((a, b) -> Integer.compare(a.line, b.line));
            return root;
        }
    }

    /** The model keys the lines map, in first appearance order: a list as {@code <list>[]}, its item keys under it. */
    static void modelKeys(Body body, String prefix, Set<String> out) { modelKeys(body, prefix, out, f -> null); }

    /**
     * As {@link #modelKeys(Body, String, Set)}; an {@code inner} line adds, at its place, the entries {@code inner}
     * gives for its format (engine-spec 0.34), or nothing when it gives null.
     */
    static void modelKeys(Body body, String prefix, Set<String> out, java.util.function.Function<String, List<String>> inner) {
        Set<Node> seen = Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        for (Kind k : body.kinds) modelKeys(k.all, prefix, out, seen, inner);
    }

    /**
     * The keys of one message kind for the check of engine-spec 0.94: the entries {@code model_keys} lists over its
     * lines (the common lines, its {@code when} lines and its own), each {@code inner} line adding what {@code inner}
     * gives, then the keys of the kind's own {@code requires} terms.
     */
    static Set<String> kindKeys(Kind k, java.util.function.Function<String, List<String>> inner) {
        Set<String> out = new java.util.LinkedHashSet<>();
        modelKeys(k.all, "", out, Collections.newSetFromMap(new java.util.IdentityHashMap<>()), inner);
        for (Pack.Require r : k.requires) out.add(r.key);
        return out;
    }

    /** The entries of {@code model_keys} that {@code nodes} map themselves, those of an inner pack left out. */
    static Set<String> ownKeys(List<Node> nodes) {
        Set<String> out = new java.util.HashSet<>();
        modelKeys(nodes, "", out, Collections.newSetFromMap(new java.util.IdentityHashMap<>()), f -> null);
        return out;
    }

    /** The keys the {@code with} options of {@code nodes} name, as entries of {@code model_keys} are written (engine-spec 0.92, ruling 9). */
    static void withKeys(List<Node> nodes, String prefix, Set<String> out) {
        for (Node n : nodes) {
            if (n.keys != null) for (Pack.Field f : n.keys) if (f.with != null) out.add(prefix + f.with);
            if (n.body != null) withKeys(n.body, prefix, out);
            if (n.parts != null) for (List<Node> part : n.parts) withKeys(part, prefix, out);
            for (List<Node> alt : n.altLines) withKeys(alt, prefix, out);
            if (n.items != null) for (Kind k : n.items.kinds) withKeys(k.all, prefix + n.list + "[].", out);
            if (n.cases != null) for (Case c : n.cases) withKeys(c.body, prefix, out);
            if (n.elseCase != null) withKeys(n.elseCase.body, prefix, out);
        }
    }

    /** The {@code inner} lines among {@code nodes}: they stand there or in {@code length} blocks (engine-spec 0.34). */
    static List<Node> innerLines(List<Node> nodes) {
        List<Node> out = new ArrayList<>();
        for (Node n : nodes) {
            if (n.op == Op.INNER) out.add(n);
            else if (n.op == Op.LENGTH) out.addAll(innerLines(n.body));
        }
        return out;
    }

    private static void modelKeys(List<Node> nodes, String prefix, Set<String> out, Set<Node> seen,
                                  java.util.function.Function<String, List<String>> inner) {
        for (Node n : nodes) {
            if (!seen.add(n)) continue;
            switch (n.op) {
                case FIELD:
                    for (Pack.Field f : n.keys) out.add(prefix + f.key);
                    break;
                case WHEN:
                    if (n.as != null) out.add(prefix + n.as.key);   // ruling 5 of 0.30
                    break;
                case IF:
                case OPT:
                case LENGTH:
                case EXT:
                    modelKeys(n.body, prefix, out, seen, inner);
                    break;
                case CHAIN:
                    for (List<Node> part : n.parts) modelKeys(part, prefix, out, seen, inner);
                    break;
                case CHOICE:
                    for (List<Node> part : n.altLines) modelKeys(part, prefix, out, seen, inner);
                    break;
                case GROUP:
                    out.add(prefix + n.list + "[]");
                    modelKeys(n.items, prefix + n.list + "[].", out);
                    break;
                case INNER: {
                    // the inner pack's entries not yet listed, at this place (engine-spec 0.34, Capability)
                    List<String> keys = inner.apply(n.name);
                    if (keys != null) for (String k : keys) out.add(prefix + k);
                    break;
                }
                case SWITCH:
                    // keys mapped only inside a case are listed as every other mapped key (ruling 13 of 0.20)
                    for (Case c : n.cases) modelKeys(c.body, prefix, out, seen, inner);
                    if (n.elseCase != null) modelKeys(n.elseCase.body, prefix, out, seen, inner);
                    break;
                default:
                    break;
            }
        }
    }
}
