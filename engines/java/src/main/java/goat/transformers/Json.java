package goat.transformers;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Minimal JSON reader and canonical writer.
 * Values: LinkedHashMap (object, member order kept), List (array), String, Num (number, raw text kept),
 * Boolean, {@link #NULL}; and for writing only, Raw (already-serialised JSON text).
 */
public final class Json {
    private Json() {}

    /** A JSON number, keeping its source text. */
    public static final class Num {
        public final String text;
        public Num(String text) { this.text = text; }
        @Override public String toString() { return text; }
    }

    /** Pre-serialised JSON, written verbatim. */
    public static final class Raw {
        public final String text;
        public Raw(String text) { this.text = text; }
    }

    public static final Object NULL = new Object() {
        @Override public String toString() { return "null"; }
    };

    /** Thrown on malformed JSON; callers translate it into a named engine error. */
    public static final class ParseException extends RuntimeException {
        private static final long serialVersionUID = 1L;
        ParseException(String msg, int pos) { super(msg + " at offset " + pos); }
    }

    /** Parse JSON text. The same member name twice in one object is an error. */
    public static Object parse(String s) { return parse(s, false); }

    /** Parse JSON text. With {@code allowDuplicates} a repeated member name keeps its first place and its last value. */
    public static Object parse(String s, boolean allowDuplicates) {
        Reader r = new Reader(s);
        r.allowDuplicates = allowDuplicates;
        r.ws();
        Object v = r.value();
        r.ws();
        if (r.pos != s.length()) throw new ParseException("trailing content", r.pos);
        return v;
    }

    private static final class Reader {
        final String s;
        int pos;
        int depth;
        boolean allowDuplicates;
        Reader(String s) {
            this.s = s;
            // a byte order mark at the start is not JSON (ruling 2e of 0.11): it fails as any other character does
            this.pos = 0;
        }

        void ws() {
            while (pos < s.length()) {
                char c = s.charAt(pos);
                if (c == ' ' || c == '\t' || c == '\n' || c == '\r') pos++;
                else break;
            }
        }

        char peek() {
            if (pos >= s.length()) throw new ParseException("unexpected end", pos);
            return s.charAt(pos);
        }

        void expect(char c) {
            if (peek() != c) throw new ParseException("expected '" + c + "'", pos);
            pos++;
        }

        Object value() {
            char c = peek();
            switch (c) {
                case '{': return object();
                case '[': return array();
                case '"': return string();
                case 't': literal("true"); return Boolean.TRUE;
                case 'f': literal("false"); return Boolean.FALSE;
                case 'n': literal("null"); return NULL;
                default:
                    if (c == '-' || (c >= '0' && c <= '9')) return number();
                    throw new ParseException("unexpected character '" + c + "'", pos);
            }
        }

        void literal(String w) {
            if (!s.startsWith(w, pos)) throw new ParseException("expected " + w, pos);
            pos += w.length();
        }

        /** An array or an object opens: the outermost is level 1 and a level beyond the limit is malformed. */
        void open() {
            if (++depth > MAX_DEPTH) throw new ParseException("nested deeper than " + MAX_DEPTH + " levels", pos);
        }

        Map<String, Object> object() {
            open();
            try {
                return members();
            } finally {
                depth--;
            }
        }

        List<Object> array() {
            open();
            try {
                return elements();
            } finally {
                depth--;
            }
        }

        Map<String, Object> members() {
            expect('{');
            LinkedHashMap<String, Object> m = new LinkedHashMap<>();
            ws();
            if (peek() == '}') { pos++; return m; }
            while (true) {
                ws();
                if (peek() != '"') throw new ParseException("expected member name", pos);
                int at = pos;
                String k = string();
                ws();
                expect(':');
                ws();
                Object v = value();
                if (!allowDuplicates && m.containsKey(k)) throw new ParseException("duplicate member \"" + k + "\"", at);
                m.put(k, v);
                ws();
                char c = peek();
                pos++;
                if (c == '}') return m;
                if (c != ',') throw new ParseException("expected ',' or '}'", pos - 1);
            }
        }

        List<Object> elements() {
            expect('[');
            ArrayList<Object> a = new ArrayList<>();
            ws();
            if (peek() == ']') { pos++; return a; }
            while (true) {
                ws();
                a.add(value());
                ws();
                char c = peek();
                pos++;
                if (c == ']') return a;
                if (c != ',') throw new ParseException("expected ',' or ']'", pos - 1);
            }
        }

        String string() {
            expect('"');
            StringBuilder b = new StringBuilder();
            while (true) {
                char c = peek();
                pos++;
                if (c == '"') return b.toString();
                if (c < 0x20) throw new ParseException("control character in string", pos - 1);
                if (c != '\\') { b.append(c); continue; }
                char e = peek();
                pos++;
                switch (e) {
                    case '"': b.append('"'); break;
                    case '\\': b.append('\\'); break;
                    case '/': b.append('/'); break;
                    case 'b': b.append('\b'); break;
                    case 'f': b.append('\f'); break;
                    case 'n': b.append('\n'); break;
                    case 'r': b.append('\r'); break;
                    case 't': b.append('\t'); break;
                    case 'u':
                        if (pos + 4 > s.length()) throw new ParseException("short \\u escape", pos);
                        int cp = 0;
                        for (int i = 0; i < 4; i++) {
                            int d = hexDigit(s.charAt(pos + i));
                            if (d < 0) throw new ParseException("bad \\u escape", pos);
                            cp = (cp << 4) | d;
                        }
                        pos += 4;
                        b.append((char) cp);
                        // half of a surrogate pair needs its other half, as the next escape (ruling 40 of 0.8)
                        if (Character.isLowSurrogate((char) cp)) throw new ParseException("low surrogate escape with no high surrogate before it", pos - 6);
                        if (Character.isHighSurrogate((char) cp)) {
                            int lo = 0;
                            boolean ok = pos + 6 <= s.length() && s.charAt(pos) == '\\' && s.charAt(pos + 1) == 'u';
                            for (int i = 2; ok && i < 6; i++) {
                                int d = hexDigit(s.charAt(pos + i));
                                if (d < 0) ok = false;
                                lo = (lo << 4) | d;
                            }
                            if (!ok || !Character.isLowSurrogate((char) lo)) {
                                throw new ParseException("high surrogate escape with no low surrogate after it", pos - 6);
                            }
                            b.append((char) lo);
                            pos += 6;
                        }
                        break;
                    default:
                        throw new ParseException("bad escape \\" + e, pos - 1);
                }
            }
        }

        Num number() {
            int start = pos;
            if (peek() == '-') pos++;
            if (pos < s.length() && s.charAt(pos) == '0') {
                pos++;
            } else {
                digits();
            }
            if (pos < s.length() && s.charAt(pos) == '.') { pos++; digits(); }
            if (pos < s.length() && (s.charAt(pos) == 'e' || s.charAt(pos) == 'E')) {
                pos++;
                if (pos < s.length() && (s.charAt(pos) == '+' || s.charAt(pos) == '-')) pos++;
                digits();
            }
            return new Num(s.substring(start, pos));
        }

        void digits() {
            int start = pos;
            while (pos < s.length() && s.charAt(pos) >= '0' && s.charAt(pos) <= '9') pos++;
            if (pos == start) throw new ParseException("expected digit", pos);
        }
    }

    /** The nesting limit of a message (engine-spec 0.8, ruling 35): arrays and objects, the outermost is level 1. */
    static final int MAX_DEPTH = 64;

    /** The value of an ASCII hex digit, or -1. A sign and a digit of another script are not hex digits. */
    static int hexDigit(char c) {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    }

    private static final java.util.regex.Pattern INTEGER = java.util.regex.Pattern.compile("-?(?:0|[1-9]\\d*)");
    private static final java.util.regex.Pattern NUMBER =
            java.util.regex.Pattern.compile("-?(?:0|[1-9]\\d*)(?:\\.\\d+)?(?:[eE][+-]?\\d+)?");

    /** True when {@code text} is a JSON number. */
    public static boolean isNumber(String text) { return NUMBER.matcher(text).matches(); }

    /**
     * Canonical text of a JSON number: the shortest plain decimal that round-trips to the same double, an
     * integer-valued number without a decimal point, negative zero as {@code 0}. An integer literal within the
     * 64-bit range keeps every digit.
     */
    public static String canonNumber(String text) {
        if (INTEGER.matcher(text).matches()) {
            try {
                return Long.toString(Long.parseLong(text));
            } catch (NumberFormatException ex) {
                // beyond 64 bits: fall through to the double form
            }
        }
        double d = Double.parseDouble(text);
        if (!Double.isFinite(d)) throw new IllegalArgumentException("number out of range: " + text);
        return Transform.formatDouble(d);
    }

    /**
     * True when the JSON value {@code v} (null when the member is absent or {@code null}) satisfies a text-wire
     * {@code when}: a string equal to the value, or a number or boolean whose canonical text equals it;
     * {@code present} needs only that the member exists and is not {@code null}.
     */
    static boolean holds(Object v, Pack.When when) {
        if (v == null || v == NULL) return false;
        if (when.present) return true;
        if (v instanceof String) return when.matchesText((String) v);
        if (v instanceof Num) {
            try {
                return when.matchesText(canonNumber(((Num) v).text));
            } catch (IllegalArgumentException ex) {
                return false;
            }
        }
        if (v instanceof Boolean) return when.matchesText(v.toString());
        return false;
    }

    /**
     * The JSON value a {@code when} line writes: canonical JSON number text as a number, {@code true} and
     * {@code false} as booleans, anything else as a string; a leading {@code =} in the pack forces a string.
     */
    static Object whenValue(Pack.When when) {
        String t = when.text;
        if (when.forced) return t;
        if (t.equals("true")) return Boolean.TRUE;
        if (t.equals("false")) return Boolean.FALSE;
        if (isNumber(t)) {
            try {
                if (canonNumber(t).equals(t)) return new Num(t);
            } catch (IllegalArgumentException ex) {
                // not canonical number text: a string
            }
        }
        return t;
    }

    /** Canonical serialisation: members in map order, no insignificant whitespace. */
    public static String write(Object v) {
        StringBuilder b = new StringBuilder();
        write(b, v);
        return b.toString();
    }

    @SuppressWarnings("unchecked")
    static void write(StringBuilder b, Object v) {
        if (v == null || v == NULL) {
            b.append("null");
        } else if (v instanceof Raw) {
            b.append(((Raw) v).text);
        } else if (v instanceof Num) {
            b.append(((Num) v).text);
        } else if (v instanceof String) {
            writeString(b, (String) v);
        } else if (v instanceof Boolean) {
            b.append(v.toString());
        } else if (v instanceof Map) {
            b.append('{');
            boolean first = true;
            for (Map.Entry<String, Object> e : ((Map<String, Object>) v).entrySet()) {
                if (!first) b.append(',');
                first = false;
                writeString(b, e.getKey());
                b.append(':');
                write(b, e.getValue());
            }
            b.append('}');
        } else if (v instanceof List) {
            b.append('[');
            boolean first = true;
            for (Object o : (List<Object>) v) {
                if (!first) b.append(',');
                first = false;
                write(b, o);
            }
            b.append(']');
        } else {
            throw new IllegalArgumentException("not a JSON value: " + v.getClass());
        }
    }

    static void writeString(StringBuilder b, String s) {
        b.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\b': b.append("\\b"); break;
                case '\f': b.append("\\f"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default:
                    if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
                    else b.append(c);
            }
        }
        b.append('"');
    }
}
