package goat.transformers;

import java.util.ArrayList;
import java.util.BitSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The {@code text} wire (Version 0.10): one record of ASCII text, fields separated by a delimiter, optionally framed
 * by a start text and an {@code nmea} checksum. A locator is a field ({@code <i>}), a column of a field
 * ({@code <i>:<from>:<len>}) or a pair of fields ({@code <i>+<j>}). Residue is every non-empty field no line
 * addresses, keyed by its index in decimal.
 */
final class TextCodec extends Codec<String[]> {
    static final int FIELD = 0, COLUMN = 1, PAIR = 2, GROUP = 3;

    /** A parsed locator. For a group, {@code i} is its first field and {@code len} the fields of one item. */
    static final class Loc {
        final int type, i, from, len, j;

        Loc(int type, int i, int from, int len, int j) {
            this.type = type;
            this.i = i;
            this.from = from;
            this.len = len;
            this.j = j;
        }

        /** The highest field index the locator names. */
        int max() { return type == PAIR ? Math.max(i, j) : i; }
    }

    private static int index(String s) {
        if (s.isEmpty() || s.length() > 9) return -1;
        for (int k = 0; k < s.length(); k++) if (s.charAt(k) < '0' || s.charAt(k) > '9') return -1;
        return Integer.parseInt(s);
    }

    /** The locator of a field, when or const line, or null when its syntax is not one of the three forms. */
    static Loc parseLocator(String s) {
        int plus = s.indexOf('+');
        if (plus >= 0) {
            int i = index(s.substring(0, plus)), j = index(s.substring(plus + 1));
            return i < 0 || j < 0 ? null : new Loc(PAIR, i, 0, 0, j);
        }
        String[] p = s.split(":", -1);
        if (p.length == 1) {
            int i = index(p[0]);
            return i < 0 ? null : new Loc(FIELD, i, 0, 0, 0);
        }
        if (p.length == 3) {
            int i = index(p[0]), from = index(p[1]), len = index(p[2]);
            return i < 0 || from < 0 || len < 1 ? null : new Loc(COLUMN, i, from, len, 0);
        }
        return null;
    }

    private static GtException badDirective(String format, Pack.Line l, String source, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, l == null ? null : l.locator,
                source + (l == null ? "" : ":" + l.line) + ": " + why);
    }

    /**
     * The checks of a text pack that need the whole file (ruling 2 of 0.10): the directives against one another and
     * against the locators, the when and const values, and the group and scope rules. All are bad-directive.
     */
    static void checkPack(List<Pack.Kind> kinds, List<Pack.Scope> bodies, String delimiter, String start, boolean nmea,
                          String format, String source) {
        boolean none = delimiter.equals("none");
        char delim = none ? 0 : delimiter.charAt(0);
        if (nmea && !none && delim == '*') throw badDirective(format, null, source, "delimiter \"*\" with checksum nmea");
        if (start != null && !none && start.indexOf(delim) >= 0) {
            throw badDirective(format, null, source, "start " + start + " holds the delimiter " + delim);
        }
        List<Pack.Scope> scopes = new ArrayList<>();
        for (Pack.Kind k : kinds) scopes.add(k.scope);
        scopes.addAll(bodies);
        for (Pack.Scope sc : scopes) {
            for (Pack.Line l : sc.lines) {
                Loc loc = (Loc) l.loc;
                if (l instanceof Pack.Group) {
                    if (none) throw badDirective(format, l, source, "a group under delimiter none");
                    continue;
                }
                if (none && loc.max() != 0) throw badDirective(format, l, source, "under delimiter none every locator is of field 0");
                if (l instanceof Pack.When && !((Pack.When) l).present) {
                    String v = ((Pack.When) l).text;
                    String why = v.isEmpty() ? "is empty"
                            : v.charAt(0) == ' ' || v.charAt(v.length() - 1) == ' ' ? "has a space at its start or end"
                            : loc.type == COLUMN && v.length() > loc.len ? "is longer than its column of " + loc.len : null;
                    for (int k = 0; why == null && k < v.length(); k++) {
                        char c = v.charAt(k);
                        if (c < 0x20 || c > 0x7e) why = "holds a character outside 0x20 to 0x7E";
                        else if (!none && c == delim) why = "holds the delimiter";
                        else if (nmea && c == '*') why = "holds a * under checksum nmea";
                    }
                    if (why != null) throw badDirective(format, l, source, "the value \"" + v + "\" " + why);
                }
            }
        }
        // The group is the last thing in its scope (common lines plus one kind).
        for (Pack.Kind k : kinds) {
            Pack.Group g = null;
            for (Pack.Line l : k.scope.lines) {
                if (!(l instanceof Pack.Group)) continue;
                if (g != null) throw badDirective(format, l, source, "a second group in one scope");
                g = (Pack.Group) l;
            }
            if (g == null) continue;
            int at = ((Loc) g.loc).i;
            for (Pack.Line l : k.scope.lines) {
                if (l instanceof Pack.Group) continue;
                Loc loc = (Loc) l.loc;
                if (loc.max() >= at) {
                    throw badDirective(format, l, source, "locator " + l.locator + " is at or beyond the index " + at + " of group " + g.list);
                }
            }
        }
    }

    /** What encode and decode need to know about the lines of one scope (common lines plus one kind). */
    private static final class Info {
        /** Field index to true when every line addressing it carries {@code optional}. */
        final Map<Integer, Boolean> allOptional = new HashMap<>();
        /** The highest field index a line other than a group addresses; -1 for none. */
        int max = -1;
        /** The scope's group, or null; fields at its index and beyond are its items'. */
        Pack.Group group;
    }

    private final boolean none;
    private final char delimiter;
    private final String start;
    private final boolean nmea;

    TextCodec(Pack pack) {
        super(pack);
        this.none = pack.textNoDelimiter;
        this.delimiter = pack.textDelimiter;
        this.start = pack.textStart;
        this.nmea = pack.textNmea;
        for (Pack.Kind k : pack.kinds) k.scope.info = info(k.scope);
    }

    private static Info info(Pack.Scope scope) {
        Info in = new Info();
        for (Pack.Line l : scope.lines) {
            if (l instanceof Pack.Group) {
                in.group = (Pack.Group) l;
                continue;
            }
            if (l instanceof Pack.When && ((Pack.When) l).present) continue;   // `when … present` addresses nothing
            boolean opt = l instanceof Pack.Field && ((Pack.Field) l).optional;
            Loc loc = (Loc) l.loc;
            in.allOptional.merge(loc.i, opt, Boolean::logicalAnd);
            if (loc.type == PAIR) in.allOptional.merge(loc.j, opt, Boolean::logicalAnd);
            in.max = Math.max(in.max, loc.max());
        }
        return in;
    }

    private boolean addressed(Info in, int idx) {
        return in.allOptional.containsKey(idx) || (in.group != null && idx >= ((Loc) in.group.loc).i);
    }

    // ---- decode ----

    @Override
    String[] parse(String text) {
        String t = text;
        if (t.endsWith("\r\n")) t = t.substring(0, t.length() - 2);
        else if (t.endsWith("\n")) t = t.substring(0, t.length() - 1);
        for (int k = 0; k < t.length(); k++) {
            char c = t.charAt(k);
            if (c < 0x20 || c > 0x7e) throw malformed("character " + (int) c + " at " + k + " is outside 0x20 to 0x7E");
        }
        if (start != null) {
            if (!t.startsWith(start)) throw malformed("the record does not begin with " + start);
            t = t.substring(start.length());
        }
        if (nmea) {
            int n = t.length();
            if (n < 3 || t.charAt(n - 3) != '*' || Json.hexDigit(t.charAt(n - 2)) < 0 || Json.hexDigit(t.charAt(n - 1)) < 0) {
                throw malformed("the record does not end with * and two hexadecimal digits");
            }
            int want = Json.hexDigit(t.charAt(n - 2)) * 16 + Json.hexDigit(t.charAt(n - 1));
            String body = t.substring(0, n - 3);
            if (xor(body) != want) throw malformed("checksum " + t.substring(n - 2) + " does not match the record, which XORs to " + hex2(xor(body)));
            if (body.indexOf('*') >= 0) throw malformed("a * is left in the record");
            t = body;
        }
        if (none) return new String[]{t};
        List<String> fields = new ArrayList<>();
        int from = 0;
        for (int k = 0; k < t.length(); k++) {
            if (t.charAt(k) == delimiter) {
                fields.add(t.substring(from, k));
                from = k + 1;
            }
        }
        fields.add(t.substring(from));
        return fields.toArray(new String[0]);
    }

    private static int xor(String s) {
        int x = 0;
        for (int k = 0; k < s.length(); k++) x ^= s.charAt(k);
        return x & 0xff;
    }

    private static String hex2(int v) {
        return "" + "0123456789ABCDEF".charAt(v >> 4) + "0123456789ABCDEF".charAt(v & 15);
    }

    /** A whole field's text, or null when it is empty or the record does not have it. */
    private static String field(String[] rec, int idx) {
        if (idx >= rec.length || rec[idx].isEmpty()) return null;
        return rec[idx];
    }

    /** A column's text, trailing spaces removed (and leading ones for a numeric transform), or null when absent. */
    private static String column(String[] rec, int idx, int from, int len, boolean numeric) {
        if (idx >= rec.length) return null;
        String f = rec[idx];
        if (f.length() <= from) return null;
        int end = (int) Math.min(f.length(), (long) from + len), b = from;
        while (end > b && f.charAt(end - 1) == ' ') end--;
        if (numeric) while (b < end && f.charAt(b) == ' ') b++;
        return b == end ? null : f.substring(b, end);
    }

    /** The text at a field or column locator, at an item's first field {@code base}; null when absent. */
    private static String text(String[] rec, Loc l, int base, boolean numeric) {
        return l.type == COLUMN ? column(rec, base + l.i, l.from, l.len, numeric) : field(rec, base + l.i);
    }

    @Override
    boolean holds(String[] rec, Pack.When when) {
        String t = text(rec, (Loc) when.loc, 0, false);
        if (t == null) return false;
        return when.present || t.equals(when.text);
    }

    @Override
    Entity decodeKind(String[] rec, Pack.Kind kind) {
        Entity e = new Entity();
        Failures fails = new Failures();
        decodeScope(rec, kind.scope, 0, e, fails);
        Info in = (Info) kind.scope.info;
        for (int idx = 0; idx < rec.length; idx++) {
            if (!rec[idx].isEmpty() && !addressed(in, idx)) e.putResidue(pack.format, Integer.toString(idx), rec[idx]);
        }
        finishDecode(e, fails);
        return e;
    }

    /** Decode the lines of one scope, its locators counted from field {@code base}. */
    private void decodeScope(String[] rec, Pack.Scope scope, int base, Entity e, Failures fails) {
        for (Pack.Line l : scope.lines) {
            Loc loc = (Loc) l.loc;
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                int first = base + loc.i, n = loc.len;
                if (rec.length <= first) continue;                 // no field at the group's index: the list is absent
                int count = (rec.length - first + n - 1) / n;
                List<Entity> items = new ArrayList<>(count);
                for (int k = 0; k < count; k++) {
                    Entity item = new Entity();
                    decodeScope(rec, g.body, first + k * n, item, fails);
                    items.add(item);
                }
                e.putList(g.list, items);
                continue;
            }
            if (!(l instanceof Pack.Field)) continue;
            Pack.Field f = (Pack.Field) l;
            if (e.get(f.key) != null) continue;                    // an earlier line already gave the key its value
            Object v;
            try {
                if (loc.type == PAIR) {
                    String a = field(rec, base + loc.i), b = field(rec, base + loc.j);
                    if (a == null || b == null) continue;          // a pair is absent when either field is
                    v = f.text.decode(a, b);
                } else {
                    String t = text(rec, loc, base, f.text.numeric());
                    if (t == null) continue;
                    v = f.text.decode(t);
                }
            } catch (IllegalArgumentException ex) {
                fails.add(f, ex.getMessage(), e);
                continue;
            }
            putDecoded(f, v, e, fails);
        }
    }

    // ---- encode ----

    /** The characters written into one field. */
    private static final class Buf {
        String whole;                                    // a whole-field line's text
        final StringBuilder cols = new StringBuilder();  // column text; unwritten characters are spaces
        final BitSet colSet = new BitSet();
        String fixedWhole;                               // a whole-field when or const
        final StringBuilder fixedCols = new StringBuilder();
        final BitSet fixedSet = new BitSet();

        String text() {
            String base = whole != null ? whole : cols.toString();
            if (fixedWhole != null) base = fixedWhole;
            if (fixedSet.isEmpty()) return base;
            StringBuilder b = new StringBuilder(base);
            for (int k = fixedSet.nextSetBit(0); k >= 0; k = fixedSet.nextSetBit(k + 1)) {
                while (b.length() <= k) b.append(' ');
                b.setCharAt(k, fixedCols.charAt(k));
            }
            return b.toString();
        }
    }

    private static void put(StringBuilder b, BitSet set, int from, String s) {
        while (b.length() < from + s.length()) b.append(' ');
        for (int k = 0; k < s.length(); k++) {
            if (set.get(from + k)) continue;             // the earlier line's characters stand
            b.setCharAt(from + k, s.charAt(k));
            set.set(from + k);
        }
    }

    /** A when or const line to write after every field, at an item's first field {@code base}. */
    private static final class Fixed {
        final Pack.When when;
        final int base;

        Fixed(Pack.When when, int base) {
            this.when = when;
            this.base = base;
        }
    }

    private Buf buf(Map<Integer, Buf> bufs, int idx) {
        return bufs.computeIfAbsent(idx, k -> new Buf());
    }

    /** Text a transform wrote: the delimiter, a * under nmea and characters outside 0x20 to 0x7E are refused. */
    private void check(Pack.Field f, String s) {
        for (int k = 0; k < s.length(); k++) {
            char c = s.charAt(k);
            String why = c < 0x20 || c > 0x7e ? "a character outside 0x20 to 0x7E"
                    : !none && c == delimiter ? "the delimiter " + delimiter
                    : nmea && c == '*' ? "a * under checksum nmea" : null;
            if (why != null) throw encodeFailure(f, new IllegalArgumentException("text \"" + s + "\" holds " + why));
        }
    }

    @Override
    String encodeKind(Entity e, Pack.Kind kind) {
        Map<Integer, Buf> bufs = new HashMap<>();
        List<Fixed> fixed = new ArrayList<>();
        int[] groupEnd = {0};
        encodeScope(e, kind.scope, 0, bufs, fixed, groupEnd);
        writeFixed(bufs, fixed);
        Info in = (Info) kind.scope.info;
        int count = Math.max(in.max + 1, groupEnd[0]);
        for (Map.Entry<String, String> r : e.residue(pack.format).entrySet()) {
            int idx = index(r.getKey());
            if (idx < 0 || addressed(in, idx)) continue;
            buf(bufs, idx).whole = r.getValue();
            count = Math.max(count, idx + 1);
        }
        while (count > 0) {
            int last = count - 1;
            Buf b = bufs.get(last);
            if (b != null && !b.text().isEmpty()) break;
            Boolean opt = in.allOptional.get(last);
            if (opt == null || !opt || (in.group != null && last >= ((Loc) in.group.loc).i)) break;
            count--;
        }
        StringBuilder body = new StringBuilder();
        for (int idx = 0; idx < count; idx++) {
            if (idx > 0) body.append(delimiter);
            Buf b = bufs.get(idx);
            if (b != null) body.append(b.text());
        }
        StringBuilder out = new StringBuilder();
        if (start != null) out.append(start);
        out.append(body);
        if (nmea) out.append('*').append(hex2(xor(body.toString())));
        return out.toString();
    }

    private void encodeScope(Entity e, Pack.Scope scope, int base, Map<Integer, Buf> bufs, List<Fixed> fixed, int[] groupEnd) {
        for (Pack.Line l : scope.lines) {
            Loc loc = (Loc) l.loc;
            if (l instanceof Pack.Group) {
                Pack.Group g = (Pack.Group) l;
                List<Entity> items = e.list(g.list);
                if (items == null || items.isEmpty()) continue;   // an empty or absent list writes no fields
                int first = base + loc.i, n = loc.len;
                for (int k = 0; k < items.size(); k++) encodeScope(items.get(k), g.body, first + k * n, bufs, fixed, groupEnd);
                groupEnd[0] = Math.max(groupEnd[0], first + items.size() * n);
                continue;
            }
            if (l instanceof Pack.When) {
                if (!((Pack.When) l).present) fixed.add(new Fixed((Pack.When) l, base));
                continue;
            }
            Pack.Field f = (Pack.Field) l;
            Object v = valueToEncode(f, e, scope);
            if (v == null) continue;
            if (loc.type == PAIR) {
                String[] two;
                try {
                    two = f.text.encodePair(v);
                } catch (IllegalArgumentException ex) {
                    throw encodeFailure(f, ex);
                }
                check(f, two[0]);
                check(f, two[1]);
                Buf a = buf(bufs, base + loc.i), b = buf(bufs, base + loc.j);
                if (a.whole == null) a.whole = two[0];
                if (b.whole == null) b.whole = two[1];
                continue;
            }
            String s;
            try {
                s = f.text.encode(v);
            } catch (IllegalArgumentException ex) {
                throw encodeFailure(f, ex);
            }
            check(f, s);
            Buf b = buf(bufs, base + loc.i);
            if (loc.type == FIELD) {
                if (b.whole == null) b.whole = s;
                continue;
            }
            if (s.length() > loc.len) {
                throw encodeFailure(f, new IllegalArgumentException("text \"" + s + "\" is longer than its column of " + loc.len));
            }
            put(b.cols, b.colSet, loc.from, pad(s, loc.len, f.text.numeric()));
        }
    }

    /** Text padded to a column: zeros after any {@code -} for a numeric transform, spaces on the right otherwise. */
    private static String pad(String s, int len, boolean numeric) {
        if (s.length() >= len) return s;
        StringBuilder b = new StringBuilder(len);
        if (numeric) {
            boolean neg = s.startsWith("-");
            if (neg) b.append('-');
            for (int k = s.length(); k < len; k++) b.append('0');
            b.append(neg ? s.substring(1) : s);
        } else {
            b.append(s);
            while (b.length() < len) b.append(' ');
        }
        return b.toString();
    }

    /** {@code when} and {@code const} values, over any field; among them the earlier line's characters stand. */
    private void writeFixed(Map<Integer, Buf> bufs, List<Fixed> fixed) {
        for (Fixed x : fixed) {
            Loc loc = (Loc) x.when.loc;
            Buf b = buf(bufs, x.base + loc.i);
            if (loc.type == FIELD) {
                if (b.fixedWhole == null && b.fixedSet.isEmpty()) b.fixedWhole = x.when.text;
            } else {
                BitSet taken = (BitSet) b.fixedSet.clone();
                if (b.fixedWhole != null) taken.set(0, b.fixedWhole.length());
                StringBuilder sb = b.fixedCols;
                String s = pad(x.when.text, loc.len, false);
                while (sb.length() < loc.from + s.length()) sb.append(' ');
                for (int k = 0; k < s.length(); k++) {
                    if (taken.get(loc.from + k)) continue;
                    sb.setCharAt(loc.from + k, s.charAt(k));
                    b.fixedSet.set(loc.from + k);
                }
            }
        }
    }
}
