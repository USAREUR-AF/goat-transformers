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
 * cursor. This file holds the parsed form and the parser of the lines; {@link SeqCodec} reads and writes messages.
 */
final class Seq {
    private Seq() {}

    enum Op { FIELD, CONST, WHEN, PAD, ALIGN, PRESENCE, IF, OPT, CHAIN, LENGTH, WHOLE, GROUP }

    enum Repeat { COUNT, WHILE, MORE, FX }

    /** One sequential line; a block line holds the lines up to its {@code end}. */
    static final class Node {
        final Op op;
        final int line;
        /** Bit length: of a field, {@code const}, {@code when}, {@code pad}, n-bit presence, count or length field; the multiple of {@code align}. */
        int len;
        /** {@code const}, {@code when}: the unsigned value. */
        long value;
        /** {@code field}: the field line and the {@code also} lines after it, all on the same bits. */
        List<Pack.Field> keys;
        /** {@code presence}: its name, whether it is {@code fx}, its slot in the state of one decode or encode. */
        String name;
        boolean fx;
        int id;
        /** {@code presence}: the bits some {@code if} block names, with or without {@code !}. */
        final BitSet named = new BitSet();
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
        /** {@code length}: counted in bits, not bytes; and the {@code plus} value. */
        boolean inBits;
        long plus;
        /** {@code group}: the list, how it repeats, and the lines of one item. */
        String list;
        Repeat repeat;
        Body items;

        Node(Op op, int line) {
            this.op = op;
            this.line = line;
        }
    }

    /** One kind of a message or of a group's items; a body with no {@code kind} line has one, with a null name. */
    static final class Kind {
        final String name;
        final List<Node> whens = new ArrayList<>();
        final List<String> requires = new ArrayList<>();
        /** The kind's lines after its {@code when} lines. */
        final List<Node> lines = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
        /** The common lines, this kind's {@code when} lines, then its own lines: what encode writes, in order. */
        List<Node> all;
        /** The defaults in force: the body's common ones, replaced by the kind's own. */
        Pack.Scope scope;

        Kind(String name) { this.name = name; }
    }

    /** The lines of the message, or of one item of a group. */
    static final class Body {
        final List<Node> common = new ArrayList<>();
        final List<Kind> kinds = new ArrayList<>();
        final LinkedHashMap<String, String> defaults = new LinkedHashMap<>();
        boolean hasKinds;
        int firstCommonWhen;

        Kind kind(String name) {
            for (Kind k : kinds) if (name.equals(k.name)) return k;
            return null;
        }
    }

    /** Directives that are lines of the layout: in a sequential pack the parser below reads them. */
    static final Set<String> LINES = Set.of("field", "also", "const", "when", "pad", "align", "presence", "if", "opt",
            "chain", "fx", "length", "group", "end", "kind", "requires", "default");

    /** Directives that exist only in a sequential pack. */
    static final Set<String> SEQUENTIAL_ONLY = Set.of("also", "pad", "align", "presence", "if", "opt", "chain", "fx", "length");

    /** The largest presence bit an {@code if} may name in an {@code fx} presence. */
    private static final int MAX_FX_BIT = 7 * 4096;

    /** Reads the layout lines of a sequential pack as the file is read; {@link #finish} runs the whole-file checks. */
    static final class Parser {
        private final String source;
        private final List<String[]> keyRefs;
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
            final char type;   // M message, G group, I if, O opt, C chain, L length
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
            /** The field line directly before the line being read, in this block. */
            Node lastField;
            boolean lastWasFx;

            Frame(char type, String what, int line, Node node, List<Node> lines) {
                this.type = type;
                this.what = what;
                this.line = line;
                this.node = node;
                this.lines = lines;
            }

            boolean isBody() { return body != null; }
        }

        Parser(String source, List<String[]> keyRefs) {
            this.source = source;
            this.keyRefs = keyRefs;
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

        private Node lookup(String name) {
            for (Frame f : stack) {
                if (f.kindNames != null && f.kindNames.containsKey(name)) return f.kindNames.get(name);
                if (f.names.containsKey(name)) return f.names.get(name);
            }
            return null;
        }

        private void push(char type, String what, int ln, Node node, List<Node> lines) {
            stack.push(new Frame(type, what, ln, node, lines));
        }

        /** One layout line of the file. */
        void line(String kw, List<String> args, int ln, String where, String format) {
            Frame f = stack.peek();
            if (kw.equals("end")) {
                arity(kw, args, 0, where, format);
                if (stack.size() == 1) throw bad(format, null, where + ": end with no open block");
                stack.pop();
                if (f.type == 'G') finishBody(f.body, format, source + ":" + f.line);
                if (f.type == 'C' && f.lastWasFx) {
                    f.node.endsWithFx = true;
                    f.node.parts.remove(f.node.parts.size() - 1);
                }
                stack.peek().lastField = null;
                return;
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
                    if (locator.indexOf(':') < 0 && !Transform.UNSIGNED.matcher(locator).matches()) {
                        throw new GtException(GtException.Code.BAD_LOCATOR, format, locator, where + ": a field takes a bit length, got \"" + locator + "\"");
                    }
                    if (locator.matches("0+")) {
                        throw new GtException(GtException.Code.BAD_LOCATOR, format, locator, where + ": a bit length of 0");
                    }
                    int len = bitLength(locator, 1, Integer.MAX_VALUE, "a field", where, format);
                    BitsTransform bt = BitsTransform.isBitsName(tname) ? BitsTransform.parse(tname, format, where) : null;
                    String via = null, absent = null;
                    boolean swap = false, trim = false;
                    for (int i = 3; i < args.size(); i++) {
                        String o = args.get(i);
                        if (o.equals("absent")) {
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
                    if (via != null) vias.add(new String[]{via, locator, where});
                    Pack.Field fl = new Pack.Field(key, locator, null, bt, null, via, swap, trim, false, ln);
                    fl.absent = sentinels;
                    afterFile.add(new Object[]{fl, tname, len, where, absent});
                    fields.add(fl);
                    typed.add(fl);
                    keyRefs.add(new String[]{key, locator});
                    Node n = new Node(Op.FIELD, ln);
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
                    fields.add(fl);
                    typed.add(fl);
                    keyRefs.add(new String[]{args.get(0), first.locator});
                    before.keys.add(fl);
                    f.lastField = before;
                    break;
                }
                case "const":
                case "when": {
                    arity(kw, args, 2, where, format);
                    int len = bitLength(args.get(0), 1, 64, kw, where, format);
                    boolean isWhen = kw.equals("when");
                    if (isWhen && !f.isBody()) throw bad(format, null, where + ": when inside a block");
                    Node n = new Node(isWhen ? Op.WHEN : Op.CONST, ln);
                    n.len = len;
                    n.value = unsignedValue(args.get(1), len, kw, where, format);
                    if (!isWhen) {
                        f.lines.add(n);
                    } else if (f.kind == null) {
                        // before the first kind: a common when, which must hold for every message (or item)
                        if (f.body.firstCommonWhen == 0) f.body.firstCommonWhen = ln;
                        f.lines.add(n);
                    } else {
                        if (f.kindLineSeen) throw bad(format, null, where + ": when after another line of its kind");
                        f.kind.whens.add(n);
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
                        int bit = Integer.parseInt(a.substring(dot + 1));
                        if (bit < 1 || bit > (p.fx ? MAX_FX_BIT : p.len)) {
                            throw bad(format, null, where + ": presence " + p.name + " has no bit " + bit);
                        }
                        p.named.set(bit);
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
                    String form = "a group of a sequential pack is group <list> count <len> | while | more | fx";
                    if (args.size() < 2) {
                        throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": group takes at least 2 arguments, got " + args.size());
                    }
                    Node n = new Node(Op.GROUP, ln);
                    n.list = args.get(0);
                    String mode = args.get(1);
                    if (mode.equals("count") && args.size() == 3) {
                        n.repeat = Repeat.COUNT;
                        n.len = bitLength(args.get(2), 1, 64, "count", where, format);
                    } else if (args.size() == 2 && (mode.equals("while") || mode.equals("more") || mode.equals("fx"))) {
                        n.repeat = mode.equals("while") ? Repeat.WHILE : mode.equals("more") ? Repeat.MORE : Repeat.FX;
                    } else {
                        throw bad(format, mode, where + ": " + form);
                    }
                    // Within one scope (common plus one kind, or one group body) two groups map one list only when
                    // they sit in if or opt blocks neither of which encloses the other (rulings 23 and 33 of 0.8).
                    Frame b = bodyFrame();
                    List<Frame> blocks = new ArrayList<>();
                    for (Frame x : stack) {
                        if (x.isBody()) break;
                        if (x.type == 'I' || x.type == 'O') blocks.add(x);
                    }
                    Map<String, List<List<Frame>>> lists = b.kindLists != null ? b.kindLists : b.lists;
                    List<List<Frame>> others = lists.computeIfAbsent(n.list, k -> new ArrayList<>());
                    for (List<Frame> o : others) {
                        if (blocks.isEmpty() || o.isEmpty() || o.contains(blocks.get(0)) || blocks.contains(o.get(0))) {
                            throw bad(format, mode, where + ": list " + n.list
                                    + " is mapped by two groups of one scope that are not in different if or opt blocks");
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
                    for (String k : args) {
                        if (!f.kind.requires.contains(k)) f.kind.requires.add(k);
                        keyRefs.add(new String[]{k, null});
                    }
                    break;
                }
                case "default": {
                    arity(kw, args, 2, where, format);
                    Frame b = bodyFrame();
                    (b.kind != null ? b.kind.defaults : b.body.defaults).put(args.get(0), args.get(1));
                    keyRefs.add(new String[]{args.get(0), null});
                    break;
                }
                default:
                    throw new IllegalStateException(kw);
            }
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
            }
        }

        /** The field lines whose transform and length are checked after the file: {field, transform, len, where}. */
        private final List<Object[]> afterFile = new ArrayList<>();

        /**
         * The checks that need the whole file: every block is ended, each field's transform is a transform of the
         * bits wire and allows its length (ruling 25 of 0.5), and every table a line names has a map line.
         */
        Body finish(Map<String, List<String[]>> tables, String format) {
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
                String lenWhy = fl.bits.checkLen(len);
                if (lenWhy != null) throw bad(format, fl.locator, where + ": " + lenWhy);
                if (fl.swap && len % 8 != 0) throw bad(format, fl.locator, where + ": swap needs a length that is a multiple of 8, got " + len);
                // the absent option of a field above 64 bits, which the line check leaves (ruling 4d of 0.11)
                if (a[4] != null && len > 64) Sentinels.integers((String) a[4], len, format, fl.locator, where);
            }
            finishBody(root, format, source);
            for (String[] v : vias) {
                if (!tables.containsKey(v[0])) throw bad(format, v[1], v[2] + ": via names table " + v[0] + ", which has no map line");
            }
            fields.sort((a, b) -> Integer.compare(a.line, b.line));
            typed.sort((a, b) -> Integer.compare(a.line, b.line));
            return root;
        }
    }

    /** The model keys the lines map, in first appearance order: a list as {@code <list>[]}, its item keys under it. */
    static void modelKeys(Body body, String prefix, Set<String> out) {
        Set<Node> seen = Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        for (Kind k : body.kinds) modelKeys(k.all, prefix, out, seen);
    }

    private static void modelKeys(List<Node> nodes, String prefix, Set<String> out, Set<Node> seen) {
        for (Node n : nodes) {
            if (!seen.add(n)) continue;
            switch (n.op) {
                case FIELD:
                    for (Pack.Field f : n.keys) out.add(prefix + f.key);
                    break;
                case IF:
                case OPT:
                case LENGTH:
                    modelKeys(n.body, prefix, out, seen);
                    break;
                case CHAIN:
                    for (List<Node> part : n.parts) modelKeys(part, prefix, out, seen);
                    break;
                case GROUP:
                    out.add(prefix + n.list + "[]");
                    modelKeys(n.items, prefix + n.list + "[].", out);
                    break;
                default:
                    break;
            }
        }
    }
}
