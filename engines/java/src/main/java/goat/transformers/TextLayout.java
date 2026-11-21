package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * The locators of the {@code text} wire (Version 0.10) and the checks of a text pack that need the whole file. They
 * are load checks of the pack language, so they are in every build; the codec that reads and writes records is
 * {@code TextCodec}, in the text wire only.
 */
final class TextLayout {
    private TextLayout() {}

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

    static int index(String s) {
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

}
