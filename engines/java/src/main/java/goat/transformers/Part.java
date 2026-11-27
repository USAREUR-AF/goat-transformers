package goat.transformers;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** One {@code part:<sep>:<n>} (engine-spec 0.64): the {@code n}th piece of a text token between {@code sep}s. */
final class Part {
    final String name;
    final String sep;
    final int n;

    private Part(String name, String sep, int n) {
        this.name = name;
        this.sep = sep;
        this.n = n;
    }

    /** True when the text of a transform up to its first {@code :} is {@code part}. */
    static boolean isName(String t) { return t.equals("part") || t.startsWith("part:"); }

    /** Parse the parameters; anything outside the rules is {@code bad-directive}. The caller checked {@link #isName}. */
    static Part parse(String name, String format, String locator, String where) {
        String[] p = name.split(":", -1);
        String sep = null;
        if (p.length == 3) {
            switch (p[1]) {
                case "space": sep = " "; break;
                case "comma": sep = ","; break;
                case "colon": sep = ":"; break;
                default:
                    if (p[1].codePointCount(0, p[1].length()) == 1) {
                        int c = p[1].codePointAt(0);
                        if (c != ',' && c != ' ' && c != '\t' && c != '\n' && c != '\r') sep = p[1];
                    }
            }
        }
        if (sep == null || !p[2].matches("0|[1-9][0-9]{0,2}") || Integer.parseInt(p[2]) > 255) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, where
                    + ": part is part:<sep>:<n>, <sep> one character or space, comma or colon, <n> from 0 to 255, got \"" + name + "\"");
        }
        return new Part(name, sep, Integer.parseInt(p[2]));
    }

    /** The pieces of a token: empty ones count, and the empty token has one. */
    static List<String> split(String token, String sep) {
        List<String> out = new ArrayList<>();
        int from = 0;
        for (int at = token.indexOf(sep); at >= 0; at = token.indexOf(sep, from)) {
            out.add(token.substring(from, at));
            from = at + sep.length();
        }
        out.add(token.substring(from));
        return out;
    }

    /** This part of the token; IllegalArgumentException when the token has no such part. */
    String of(String token) {
        List<String> parts = split(token, sep);
        if (n >= parts.size()) throw new IllegalArgumentException("\"" + token + "\" has no part " + n);
        return parts.get(n);
    }

    /** One {@code const <locator> part:<sep>:<n> <text>} line. */
    static final class Const extends Pack.Line {
        final Part part;
        final String text;
        /** Names the line in a failure; it maps no key. */
        final Pack.Field report;

        Const(String locator, Part part, String text, int line) {
            super(locator, line);
            this.part = part;
            this.text = text;
            this.report = new Pack.Field("const " + part.name, locator, Transform.STRING, null, null, null, false, false, false, line);
        }

        /** Null when the token holds the text at this part, else the reason. */
        String why(String token) {
            List<String> parts = split(token, part.sep);
            if (part.n < parts.size() && parts.get(part.n).equals(text)) return null;
            return "part " + part.n + " of \"" + token + "\" is not \"" + text + "\"";
        }
    }

    /** The part lines of one locator in one scope, and the whole line when there is one. */
    static final class Group {
        /** The part line of each number from 0 to the highest. */
        final List<Pack.Line> parts = new ArrayList<>();
        /** The group's part fields, and for each whether no other field line of the scope maps its key (ruling 18). */
        final List<Pack.Field> fields = new ArrayList<>();
        final List<Boolean> alone = new ArrayList<>();
        final List<Const> consts = new ArrayList<>();
        Pack.Field whole;
        /** The group's first line: where the token is written. */
        Pack.Line first;
        String sep;
    }

    private static Part partOf(Pack.Line l) {
        return l instanceof Const ? ((Const) l).part : l instanceof Pack.Field ? ((Pack.Field) l).part : null;
    }

    private static GtException bad(String format, String source, Pack.Line l, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, l.locator, source + ":" + l.line + ": " + why);
    }

    /** The part groups of a scope by locator (empty for none); a group outside the rules is {@code bad-directive}. */
    static Map<String, Group> groups(List<Pack.Line> lines, String format, String source) {
        Map<String, Group> out = null;
        for (Pack.Line l : lines) {
            if (partOf(l) == null) continue;
            if (out == null) out = new HashMap<>();
            out.computeIfAbsent(l.locator, k -> new Group());
        }
        if (out == null) return Collections.emptyMap();
        Map<String, Integer> mapped = new HashMap<>();
        for (Pack.Line l : lines) if (l instanceof Pack.Field) mapped.merge(((Pack.Field) l).key, 1, Integer::sum);
        for (Pack.Line l : lines) {
            Group g = out.get(l.locator);
            if (g == null || l instanceof Pack.Element) continue;
            if (g.first == null) g.first = l;
            Part p = partOf(l);
            if (p == null) {
                if (!(l instanceof Pack.Field) || !((Pack.Field) l).plainString()) {
                    throw bad(format, source, l, "another line on the locator of a part group (one field ... string without options may stand there)");
                }
                if (g.whole != null) throw bad(format, source, l, "a second whole line of a part group");
                g.whole = (Pack.Field) l;
                continue;
            }
            if (g.sep == null) g.sep = p.sep;
            else if (!g.sep.equals(p.sep)) throw bad(format, source, l, "two separators in one part group");
            while (g.parts.size() <= p.n) g.parts.add(null);
            if (g.parts.set(p.n, l) != null) throw bad(format, source, l, "part " + p.n + " is named by two lines");
            if (l instanceof Const) {
                g.consts.add((Const) l);
            } else {
                g.fields.add((Pack.Field) l);
                g.alone.add(mapped.get(((Pack.Field) l).key) == 1);
            }
        }
        for (Group g : out.values()) {
            if (g.fields.isEmpty()) throw bad(format, source, g.first, "a part group with no part field");
            int gap = g.parts.indexOf(null);
            if (gap >= 0) throw bad(format, source, g.first, "no line names part " + gap);
            for (Pack.Field f : g.fields) {
                if (g.whole != null && g.whole.key.equals(f.key)) throw bad(format, source, f, "a whole line and a part line of one key");
            }
        }
        return out;
    }
}
