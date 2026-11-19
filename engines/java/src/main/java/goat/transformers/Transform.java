package goat.transformers;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.regex.Pattern;

/** The version 0.1 transform set. decode: wire text to model value; encode: model value to wire text. */
public enum Transform {
    STRING("string"),
    FLOAT("float"),
    INT("int"),
    ISO8601_MS("iso8601_ms"),
    /** Version 0.12: read as {@code iso8601_ms}; written to the whole second. */
    ISO8601_S("iso8601_s"),
    /** {@code json} wire only: JSON {@code true}/{@code false} to int 1/0. The text forms are "true" and "false". */
    BOOL("bool");

    private final String wireName;

    Transform(String wireName) { this.wireName = wireName; }

    public String wireName() { return wireName; }

    /** The model type this transform yields: {@code string}, {@code float} or {@code int}. */
    public String yields() {
        switch (this) {
            case STRING: return "string";
            case FLOAT: return "float";
            default: return "int";
        }
    }

    /** The transform named {@code name}, or null when the engine does not implement it. */
    public static Transform byName(String name) {
        for (Transform t : values()) {
            if (t.wireName.equals(name)) return t;
        }
        return null;
    }


    /** Wire text to model value. Throws IllegalArgumentException with a reason on failure. */
    public Object decode(String text) {
        switch (this) {
            case STRING:
                return text;
            case FLOAT:
                return parseFloat(text);
            case INT:
                return parseInt(text);
            case ISO8601_MS:
            case ISO8601_S:
                return parseIso(text);
            case BOOL:
                if (text.equals("true")) return 1L;
                if (text.equals("false")) return 0L;
                throw new IllegalArgumentException("not a boolean: \"" + text + "\"");
            default:
                throw new IllegalStateException(name());
        }
    }

    /** Model value (from any format) to wire text. Throws IllegalArgumentException on a value it cannot carry. */
    public String encode(Object value) {
        switch (this) {
            case STRING:
                if (value instanceof Double) return formatDouble((Double) value);
                return String.valueOf(value);
            case FLOAT:
                return formatDouble(asDouble(value));
            case INT:
                return Long.toString(asLong(value));
            case ISO8601_MS:
                return formatIso(asLong(value));
            case ISO8601_S: {
                // the text of iso8601_ms less its ".fff": the second that holds the instant
                String full = formatIso(asLong(value));
                return full.substring(0, 19) + "Z";
            }
            case BOOL: {
                long b = asLong(value);
                if (b == 1) return "true";
                if (b == 0) return "false";
                throw new IllegalArgumentException("bool carries only 1 and 0, got " + b);
            }
            default:
                throw new IllegalStateException(name());
        }
    }

    /** Integer text (ruling 2a of 0.11): an optional {@code -}, then ASCII digits; nothing else. */
    static final Pattern INT_TEXT = Pattern.compile("-?[0-9]+");
    /** Number text (ruling 2b of 0.11). */
    static final Pattern NUM_TEXT = Pattern.compile("-?[0-9]+(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?");
    /** An unsigned decimal integer (ruling 2c of 0.11). */
    static final Pattern UNSIGNED = Pattern.compile("[0-9]+");
    private static final java.math.BigInteger LONG_MIN = java.math.BigInteger.valueOf(Long.MIN_VALUE);
    private static final java.math.BigInteger LONG_MAX = java.math.BigInteger.valueOf(Long.MAX_VALUE);

    /** Number text (2b) to the nearest double; text 2b refuses, or whose nearest double is infinite, is refused. */
    static double parseFloat(String text) {
        if (!NUM_TEXT.matcher(text).matches()) throw new IllegalArgumentException("not number text: \"" + text + "\"");
        double d = Double.parseDouble(text);
        if (!Double.isFinite(d)) throw new IllegalArgumentException("out of range: \"" + text + "\"");
        return d;
    }

    /** Integer text (2a) within a signed 64-bit integer. */
    static long parseInt(String text) {
        if (!INT_TEXT.matcher(text).matches()) throw new IllegalArgumentException("not integer text: \"" + text + "\"");
        java.math.BigInteger b = new java.math.BigInteger(text);
        if (b.compareTo(LONG_MIN) < 0 || b.compareTo(LONG_MAX) > 0) {
            throw new IllegalArgumentException("not an integer in 64-bit range: \"" + text + "\"");
        }
        return b.longValue();
    }

    /** True when {@code text} is number text (2b) whose nearest double is finite. */
    static boolean isNumText(String text) {
        try {
            parseFloat(text);
            return true;
        } catch (IllegalArgumentException ex) {
            return false;
        }
    }

    /** An unsigned decimal integer (2c) below 2^{@code width}; null when the text is not one or does not fit. */
    static Long parseUnsigned(String text, int width) {
        if (!UNSIGNED.matcher(text).matches()) return null;
        java.math.BigInteger b = new java.math.BigInteger(text);
        if (b.bitLength() > width) return null;
        return b.longValue();
    }

    private static final Pattern DECIMAL_LENIENT =
            Pattern.compile("[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");

    /** A model string value carried through a number transform on encode: the reading of the versions before 0.11. */
    private static double lenientFloat(String text) {
        String t = text.trim();
        if (!DECIMAL_LENIENT.matcher(t).matches()) throw new IllegalArgumentException("not a decimal number: \"" + text + "\"");
        double d = Double.parseDouble(t);
        if (!Double.isFinite(d)) throw new IllegalArgumentException("out of range: \"" + text + "\"");
        return d;
    }

    private static long lenientInt(String text) {
        String t = text.trim();
        if (!DECIMAL_LENIENT.matcher(t).matches()) throw new IllegalArgumentException("not a decimal integer: \"" + text + "\"");
        try {
            return new BigDecimal(t).longValueExact();
        } catch (ArithmeticException e) {
            throw new IllegalArgumentException("not an integer in 64-bit range: \"" + text + "\"");
        }
    }

    /** The first and last instants {@code iso8601_ms} carries (ruling 3 of 0.11). */
    static final long ISO_MIN = -62135596800000L, ISO_MAX = 253402300799999L;

    private static int digits(String s, int from, int n) {
        int v = 0;
        for (int i = from; i < from + n; i++) {
            char c = s.charAt(i);
            if (c < '0' || c > '9') return -1;
            v = v * 10 + (c - '0');
        }
        return v;
    }

    private static boolean leap(int y) { return (y % 4 == 0 && y % 100 != 0) || y % 400 == 0; }

    private static final int[] MONTH_DAYS = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};

    /** Days from 1970-01-01 to the date, proleptic Gregorian. */
    private static long epochDay(int y, int m, int d) {
        long yy = m <= 2 ? y - 1 : y;
        long era = Math.floorDiv(yy, 400);
        long yoe = yy - era * 400;
        long mp = (m + 9) % 12;
        long doy = (153 * mp + 2) / 5 + d - 1;
        long doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
        return era * 146097 + doe - 719468;
    }

    /** {@code iso8601_ms} decode, by the grammar of ruling 3 of 0.11. */
    static long parseIso(String s) {
        IllegalArgumentException bad = new IllegalArgumentException("not an iso8601_ms time: \"" + s + "\"");
        int n = s.length();
        if (n < 20) throw bad;
        if (s.charAt(4) != '-' || s.charAt(7) != '-' || (s.charAt(10) != 'T' && s.charAt(10) != 't')
                || s.charAt(13) != ':' || s.charAt(16) != ':') throw bad;
        int y = digits(s, 0, 4), mo = digits(s, 5, 2), d = digits(s, 8, 2);
        int h = digits(s, 11, 2), mi = digits(s, 14, 2), se = digits(s, 17, 2);
        if (y < 1 || mo < 1 || mo > 12 || d < 1 || h < 0 || h > 23 || mi < 0 || mi > 59 || se < 0 || se > 59) throw bad;
        int last = MONTH_DAYS[mo - 1] + (mo == 2 && leap(y) ? 1 : 0);
        if (d > last) throw bad;
        int i = 19;
        int ms = 0;
        if (i < n && s.charAt(i) == '.') {
            int start = ++i;
            while (i < n && s.charAt(i) >= '0' && s.charAt(i) <= '9') i++;
            if (i == start) throw bad;
            for (int k = 0; k < 3; k++) ms = ms * 10 + (start + k < i ? s.charAt(start + k) - '0' : 0);
        }
        if (i >= n) throw bad;
        long offsetMs;
        char z = s.charAt(i);
        if (z == 'Z' || z == 'z') {
            if (i + 1 != n) throw bad;
            offsetMs = 0;
        } else if (z == '+' || z == '-') {
            if (i + 6 != n || s.charAt(i + 3) != ':') throw bad;
            int oh = digits(s, i + 1, 2), om = digits(s, i + 4, 2);
            if (oh < 0 || oh > 23 || om < 0 || om > 59) throw bad;
            offsetMs = (oh * 60L + om) * 60_000L;
            if (z == '-') offsetMs = -offsetMs;
        } else {
            throw bad;
        }
        long v = ((epochDay(y, mo, d) * 24 + h) * 60 + mi) * 60_000L + se * 1000L + ms - offsetMs;
        if (v < ISO_MIN || v > ISO_MAX) throw new IllegalArgumentException("time \"" + s + "\" lies outside years 0001 to 9999");
        return v;
    }

    static String formatIso(long epochMs) {
        if (epochMs < ISO_MIN || epochMs > ISO_MAX) {
            throw new IllegalArgumentException("time " + epochMs + " ms lies outside years 0001 to 9999");
        }
        long secs = Math.floorDiv(epochMs, 1000L);
        int ms = (int) Math.floorMod(epochMs, 1000L);
        LocalDateTime t = LocalDateTime.ofEpochSecond(secs, 0, ZoneOffset.UTC);
        return String.format("%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                t.getYear(), t.getMonthValue(), t.getDayOfMonth(),
                t.getHour(), t.getMinute(), t.getSecond(), ms);
    }

    /**
     * Shortest round-trip plain decimal: the fewest significant digits that parse back to
     * exactly {@code d}, never in exponent form, integer-valued doubles without a decimal point.
     * Does not rely on Double.toString, which in JDK 17 is not always shortest.
     */
    public static String formatDouble(double d) {
        if (!Double.isFinite(d)) throw new IllegalArgumentException("non-finite float " + d);
        if (d == 0.0) return "0";
        BigDecimal exact = new BigDecimal(d);
        for (int p = 1; p <= 17; p++) {
            BigDecimal r = exact.round(new MathContext(p, RoundingMode.HALF_EVEN));
            if (r.doubleValue() == d) return r.stripTrailingZeros().toPlainString();
        }
        return exact.stripTrailingZeros().toPlainString();
    }

    /** Round half away from zero. The result is integral; NaN and infinities pass through. */
    static double roundHalfAway(double d) {
        double a = Math.abs(d);
        double f = Math.floor(a);
        if (a - f >= 0.5) f += 1;
        return d < 0 ? -f : f;
    }

    static String formatOrText(double d) { return Double.isFinite(d) ? formatDouble(d) : Double.toString(d); }

    static double asDouble(Object v) {
        if (v instanceof Number) return ((Number) v).doubleValue();
        if (v instanceof String) return lenientFloat((String) v);
        throw new IllegalArgumentException("cannot carry " + v + " as float");
    }

    static long asLong(Object v) {
        if (v instanceof Long || v instanceof Integer) return ((Number) v).longValue();
        if (v instanceof Double) {
            double d = (Double) v;
            if (d != Math.rint(d) || Math.abs(d) > 9.007199254740992E15) {
                throw new IllegalArgumentException("float " + d + " is not an exact integer");
            }
            return (long) d;
        }
        if (v instanceof String) return lenientInt((String) v);
        throw new IllegalArgumentException("cannot carry " + v + " as int");
    }
}
