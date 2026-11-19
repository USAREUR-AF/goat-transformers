package goat.transformers;

import java.time.DateTimeException;
import java.time.LocalDate;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * A transform of the {@code text} wire (Version 0.10): {@code string}, {@code int}, {@code float} and
 * {@code iso8601_ms} with this wire's readings, and the transforms valid only on it: {@code int:<w>},
 * {@code dec:<f>[:<w>]}, {@code dm:<d>:<f>:<PN>}, {@code hms:<f>} and {@code hms_dmy:<f>}.
 * decode and encode throw IllegalArgumentException with a reason; the codec turns it into the error kind.
 */
final class TextTransform {
    enum Kind { STRING, INT, FLOAT, ISO, INTW, DEC, DM, HMS, HMS_DMY }

    final Kind kind;
    final String name;
    /** {@code int:<w>} and {@code dec:<f>:<w>}: the width; 0 when not given. */
    final int w;
    /** {@code dec}, {@code dm}, {@code hms}, {@code hms_dmy}: the fraction digits. */
    final int f;
    /** {@code dm}: the degree digits. */
    final int d;
    /** {@code dm}: the letters of the positive and the negative side. */
    final char pos, neg;

    private TextTransform(Kind kind, String name, int w, int f, int d, char pos, char neg) {
        this.kind = kind;
        this.name = name;
        this.w = w;
        this.f = f;
        this.d = d;
        this.pos = pos;
        this.neg = neg;
    }

    /** The transform of the 0.1 set read on this wire; null for {@code bool}. */
    static TextTransform base(Transform t) {
        switch (t) {
            case STRING: return new TextTransform(Kind.STRING, "string", 0, 0, 0, ' ', ' ');
            case INT: return new TextTransform(Kind.INT, "int", 0, 0, 0, ' ', ' ');
            case FLOAT: return new TextTransform(Kind.FLOAT, "float", 0, 0, 0, ' ', ' ');
            case ISO8601_MS: return new TextTransform(Kind.ISO, "iso8601_ms", 0, 0, 0, ' ', ' ');
            default: return null;
        }
    }

    private static String head(String name) {
        int c = name.indexOf(':');
        return c < 0 ? name : name.substring(0, c);
    }

    /** True when {@code name} is one of the transforms valid only on the text wire, with good parameters or not. */
    static boolean isTextOnlyName(String name) {
        switch (head(name)) {
            case "dec":
            case "dm":
            case "hms":
            case "hms_dmy":
                return true;
            case "int":
                return name.indexOf(':') >= 0;
            default:
                return false;
        }
    }

    /** A parameter: decimal digits from {@code lo} to {@code hi}; -1 when it is not. */
    private static int param(String s, int lo, int hi) {
        // an unsigned decimal integer: leading zeros are allowed (ruling 2c of 0.11)
        if (s.isEmpty()) return -1;
        for (int i = 0; i < s.length(); i++) if (s.charAt(i) < '0' || s.charAt(i) > '9') return -1;
        String t = s.replaceFirst("^0+(?=.)", "");
        if (t.length() > 3) return -1;
        int v = Integer.parseInt(t);
        return v < lo || v > hi ? -1 : v;
    }

    /**
     * Parse a text-only transform name (the caller has checked {@link #isTextOnlyName}); bad parameters are
     * {@code bad-directive} (rule 1 of the 0.10 transforms).
     */
    static TextTransform parseTextOnly(String name, String format, String locator, String where) {
        String[] p = name.split(":", -1);
        TextTransform t = null;
        switch (p[0]) {
            case "int":
                if (p.length == 2 && param(p[1], 1, 20) >= 0) t = new TextTransform(Kind.INTW, name, param(p[1], 1, 20), 0, 0, ' ', ' ');
                break;
            case "dec":
                if (p.length == 2 && param(p[1], 0, 9) >= 0) {
                    t = new TextTransform(Kind.DEC, name, 0, param(p[1], 0, 9), 0, ' ', ' ');
                } else if (p.length == 3 && param(p[1], 0, 9) >= 0 && param(p[2], 1, 20) >= 0) {
                    t = new TextTransform(Kind.DEC, name, param(p[2], 1, 20), param(p[1], 0, 9), 0, ' ', ' ');
                }
                break;
            case "dm":
                if (p.length == 4 && param(p[1], 1, 3) >= 0 && param(p[2], 0, 9) >= 0 && p[3].length() == 2) {
                    char a = p[3].charAt(0), b = p[3].charAt(1);
                    if (a >= 'A' && a <= 'Z' && b >= 'A' && b <= 'Z' && a != b) {
                        t = new TextTransform(Kind.DM, name, 0, param(p[2], 0, 9), param(p[1], 1, 3), a, b);
                    }
                }
                break;
            case "hms":
                if (p.length == 2 && param(p[1], 0, 3) >= 0) t = new TextTransform(Kind.HMS, name, 0, param(p[1], 0, 3), 0, ' ', ' ');
                break;
            case "hms_dmy":
                if (p.length == 2 && param(p[1], 0, 3) >= 0) t = new TextTransform(Kind.HMS_DMY, name, 0, param(p[1], 0, 3), 0, ' ', ' ');
                break;
            default:
                break;
        }
        if (t == null) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, where + ": transform \"" + name
                    + "\" has parameters outside int:<w>, dec:<f>[:<w>], dm:<d>:<f>:<PN>, hms:<f>, hms_dmy:<f>");
        }
        return t;
    }

    /** True for the transforms that take two parts: a pair locator, and only for them. */
    boolean pair() { return kind == Kind.DM || kind == Kind.HMS_DMY; }

    /** The numeric transforms: {@code int}, {@code int:<w>}, {@code float}, {@code dec:<f>}, {@code dec:<f>:<w>}. */
    boolean numeric() { return kind == Kind.INT || kind == Kind.INTW || kind == Kind.FLOAT || kind == Kind.DEC; }

    String yields() {
        switch (kind) {
            case STRING: return "string";
            case FLOAT: case DEC: case DM: case HMS: return "float";
            default: return "int";
        }
    }

    // ---- decode ----

    private static final Pattern INT = Pattern.compile("[+-]?[0-9]+");
    private static final Pattern FLOAT = Pattern.compile("[+-]?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)");
    private static final Pattern HMS = Pattern.compile("([0-9]{2})([0-9]{2})([0-9]{2})(?:\\.([0-9]+))?");
    private static final Pattern DMY = Pattern.compile("([0-9]{2})([0-9]{2})([0-9]{2})");

    static long readInt(String s) {
        if (!INT.matcher(s).matches()) throw new IllegalArgumentException("not a sign and digits: \"" + s + "\"");
        try {
            return Long.parseLong(s);
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("integer out of the 64-bit range: \"" + s + "\"");
        }
    }

    static double readFloat(String s) {
        if (!FLOAT.matcher(s).matches()) throw new IllegalArgumentException("not a sign, digits and at most one '.': \"" + s + "\"");
        double v = Double.parseDouble(s);
        if (!Double.isFinite(v)) throw new IllegalArgumentException("number out of range: \"" + s + "\"");
        return v;
    }

    /** One field's (or column's) text to its model value. */
    Object decode(String s) {
        switch (kind) {
            case STRING: return s;
            case INT: case INTW: return readInt(s);
            case FLOAT: case DEC: return readFloat(s);
            case ISO: return Transform.parseIso(s);
            case HMS: {
                Matcher m = hms(s);
                return (double) (Integer.parseInt(m.group(1)) * 3600 + Integer.parseInt(m.group(2)) * 60) + seconds(m);
            }
            default: throw new IllegalStateException(name + " takes two parts");
        }
    }

    private static Matcher hms(String s) {
        Matcher m = HMS.matcher(s);
        if (!m.matches()) throw new IllegalArgumentException("not hhmmss[.s]: \"" + s + "\"");
        if (Integer.parseInt(m.group(1)) >= 24 || Integer.parseInt(m.group(2)) >= 60 || Integer.parseInt(m.group(3)) >= 60) {
            throw new IllegalArgumentException("time out of range: \"" + s + "\"");
        }
        return m;
    }

    private static double seconds(Matcher m) {
        return Double.parseDouble(m.group(4) == null ? m.group(3) : m.group(3) + "." + m.group(4));
    }

    /** A pair's two texts, in the order of the locator, to the model value. */
    Object decode(String a, String b) {
        if (kind == Kind.DM) {
            Matcher m = Pattern.compile("([0-9]{" + d + "})([0-9]{2})(?:\\.([0-9]+))?").matcher(a);
            if (!m.matches()) throw new IllegalArgumentException("not " + d + " digits of degrees and mm[.m]: \"" + a + "\"");
            if (Integer.parseInt(m.group(2)) >= 60) throw new IllegalArgumentException("minutes of 60 or more: \"" + a + "\"");
            double minutes = Double.parseDouble(m.group(3) == null ? m.group(2) : m.group(2) + "." + m.group(3));
            double v = minutes / 60.0 + Integer.parseInt(m.group(1));
            if (b.length() == 1 && b.charAt(0) == pos) return v;
            if (b.length() == 1 && b.charAt(0) == neg) return -v;
            throw new IllegalArgumentException("letter is neither " + pos + " nor " + neg + ": \"" + b + "\"");
        }
        if (kind == Kind.HMS_DMY) {
            Matcher t = hms(a);
            Matcher dt = DMY.matcher(b);
            if (!dt.matches()) throw new IllegalArgumentException("not ddmmyy: \"" + b + "\"");
            int yy = Integer.parseInt(dt.group(3));
            LocalDate day;
            try {
                day = LocalDate.of(yy >= 80 ? 1900 + yy : 2000 + yy, Integer.parseInt(dt.group(2)), Integer.parseInt(dt.group(1)));
            } catch (DateTimeException ex) {
                throw new IllegalArgumentException("date does not exist: \"" + b + "\"");
            }
            long secs = Integer.parseInt(t.group(1)) * 3600L + Integer.parseInt(t.group(2)) * 60L + Integer.parseInt(t.group(3));
            String frac = t.group(4) == null ? "" : t.group(4);
            long ms = Integer.parseInt((frac + "000").substring(0, 3));   // digits beyond milliseconds truncated
            return day.toEpochDay() * 86_400_000L + secs * 1000L + ms;
        }
        throw new IllegalStateException(name + " takes one part");
    }

    // ---- encode ----

    private static final double[] POW10 = {1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9};
    private static final long[] LPOW10 = {1L, 10L, 100L, 1000L, 10000L, 100000L, 1000000L, 10000000L, 100000000L, 1000000000L};
    private static final double TWO53 = 9007199254740992.0;

    /** Round half away from zero, refusing a value that is not finite or whose magnitude reaches 2^53 (rule 2). */
    private static long rounded(double x) {
        double r = Transform.roundHalfAway(x);
        if (!Double.isFinite(r) || Math.abs(r) >= TWO53) throw new IllegalArgumentException("value out of range: " + Transform.formatOrText(x));
        return (long) r;
    }

    private static String zeros(String digits, int width) {
        if (digits.length() >= width) return digits;
        StringBuilder b = new StringBuilder(width);
        for (int i = digits.length(); i < width; i++) b.append('0');
        return b.append(digits).toString();
    }

    /** A model value to the field's text. */
    String encode(Object v) {
        switch (kind) {
            case STRING: return Transform.STRING.encode(v);
            case INT: return Transform.INT.encode(v);
            case FLOAT: return Transform.FLOAT.encode(v);
            case ISO: return Transform.ISO8601_MS.encode(v);
            case INTW: {
                String s = Long.toString(Transform.asLong(v));
                return s.startsWith("-") ? "-" + zeros(s.substring(1), w) : zeros(s, w);
            }
            case DEC: {
                long n = rounded(Transform.asDouble(v) * POW10[f]);
                String digits = zeros(Long.toString(Math.abs(n)), f + 1);
                String t = f == 0 ? digits : digits.substring(0, digits.length() - f) + "." + digits.substring(digits.length() - f);
                if (w > 0) t = zeros(t, w);
                return n < 0 ? "-" + t : t;
            }
            case HMS: {
                long n = rounded(Transform.asDouble(v) * POW10[f]);
                if (n < 0 || n >= 86400L * LPOW10[f]) throw new IllegalArgumentException("time of day out of range: " + v);
                return clock(n / LPOW10[f], n % LPOW10[f], f);
            }
            default: throw new IllegalStateException(name + " writes two parts");
        }
    }

    private static String clock(long secs, long frac, int f) {
        String t = zeros(Long.toString(secs / 3600), 2) + zeros(Long.toString(secs / 60 % 60), 2) + zeros(Long.toString(secs % 60), 2);
        return f == 0 ? t : t + "." + zeros(Long.toString(frac), f);
    }

    /** A model value to a pair's two texts, in the order of the locator. */
    String[] encodePair(Object v) {
        if (kind == Kind.DM) {
            double x = Transform.asDouble(v);
            long m = rounded(Math.abs(x) * 60.0 * POW10[f]);
            long unit = 60L * LPOW10[f];
            long deg = m / unit, rest = m % unit;
            if (deg >= LPOW10[d]) throw new IllegalArgumentException("degrees " + deg + " do not fit " + d + " digits");
            String first = zeros(Long.toString(deg), d) + zeros(Long.toString(rest / LPOW10[f]), 2)
                    + (f == 0 ? "" : "." + zeros(Long.toString(rest % LPOW10[f]), f));
            return new String[]{first, String.valueOf(x < 0 && m > 0 ? neg : pos)};
        }
        if (kind == Kind.HMS_DMY) {
            long t = Transform.asLong(v);
            long day = Math.floorDiv(t, 86_400_000L), ms = Math.floorMod(t, 86_400_000L);
            LocalDate date;
            try {
                date = LocalDate.ofEpochDay(day);
            } catch (DateTimeException ex) {
                throw new IllegalArgumentException("year out of 1980 to 2079: " + t);
            }
            if (date.getYear() < 1980 || date.getYear() > 2079) throw new IllegalArgumentException("year " + date.getYear() + " is outside 1980 to 2079");
            String time = clock(ms / 1000, ms % 1000 / LPOW10[3 - f], f);
            String dmy = zeros(Integer.toString(date.getDayOfMonth()), 2) + zeros(Integer.toString(date.getMonthValue()), 2)
                    + zeros(Integer.toString(date.getYear() % 100), 2);
            return new String[]{time, dmy};
        }
        throw new IllegalStateException(name + " writes one part");
    }
}
