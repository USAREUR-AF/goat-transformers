package goat.transformers;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.DateTimeException;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** The version 0.1 transform set. decode: wire text to model value; encode: model value to wire text. */
public enum Transform {
    STRING("string"),
    FLOAT("float"),
    INT("int"),
    ISO8601_MS("iso8601_ms"),
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

    private static final Pattern DECIMAL =
            Pattern.compile("[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?");
    private static final Pattern ISO =
            Pattern.compile("(\\d{4})-(\\d{2})-(\\d{2})[Tt](\\d{2}):(\\d{2}):(\\d{2})(?:\\.(\\d+))?(?:[Zz]|([+-])(\\d{2}):(\\d{2}))");

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

    static double parseFloat(String text) {
        String t = text.trim();
        if (!DECIMAL.matcher(t).matches()) throw new IllegalArgumentException("not a decimal number: \"" + text + "\"");
        double d = Double.parseDouble(t);
        if (!Double.isFinite(d)) throw new IllegalArgumentException("out of range: \"" + text + "\"");
        return d;
    }

    static long parseInt(String text) {
        String t = text.trim();
        if (!DECIMAL.matcher(t).matches()) throw new IllegalArgumentException("not a decimal integer: \"" + text + "\"");
        try {
            return new BigDecimal(t).longValueExact();
        } catch (ArithmeticException e) {
            throw new IllegalArgumentException("not an integer in 64-bit range: \"" + text + "\"");
        }
    }

    static long parseIso(String text) {
        Matcher m = ISO.matcher(text.trim());
        if (!m.matches()) {
            throw new IllegalArgumentException("not ISO 8601 YYYY-MM-DDTHH:MM:SS[.fff] with Z or an offset +hh:mm: \"" + text + "\"");
        }
        try {
            LocalDateTime ldt = LocalDateTime.of(
                    Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)),
                    Integer.parseInt(m.group(4)), Integer.parseInt(m.group(5)), Integer.parseInt(m.group(6)));
            long ms = 0;
            String frac = m.group(7);
            if (frac != null) {
                String three = (frac + "00").substring(0, 3); // milliseconds, sub-ms digits truncated
                ms = Integer.parseInt(three);
            }
            long offsetSecs = 0;
            if (m.group(8) != null) {
                int hh = Integer.parseInt(m.group(9)), mm = Integer.parseInt(m.group(10));
                if (hh > 23 || mm > 59) throw new DateTimeException("offset out of range");
                offsetSecs = (hh * 60L + mm) * 60L;
                if (m.group(8).equals("-")) offsetSecs = -offsetSecs;
            }
            // The wire time is local to its offset; the instant in UTC is that time less the offset.
            return Math.addExact(Math.multiplyExact(ldt.toEpochSecond(ZoneOffset.UTC) - offsetSecs, 1000L), ms);
        } catch (DateTimeException | ArithmeticException e) {
            throw new IllegalArgumentException("invalid date-time \"" + text + "\": " + e.getMessage());
        }
    }

    static String formatIso(long epochMs) {
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
        if (v instanceof String) return parseFloat((String) v);
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
        if (v instanceof String) return parseInt((String) v);
        throw new IllegalArgumentException("cannot carry " + v + " as int");
    }
}
