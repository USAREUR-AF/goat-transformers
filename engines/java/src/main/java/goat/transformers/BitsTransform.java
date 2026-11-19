package goat.transformers;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;

/**
 * A {@code bits}-wire transform. {@code uint}, {@code twos}, {@code linscale:<maxpos>:<range>},
 * {@code uscale:<factor>[:<offset>]}, {@code sscale:<factor>[:<offset>]}, {@code f32} and {@code f64} turn a raw
 * value of up to 64 bits into a model value and back; {@code ascii} turns the field's bytes into text and back.
 * A bits transform is valid only on a bits wire.
 */
public final class BitsTransform {
    enum Kind { UINT, TWOS, LINSCALE, USCALE, SSCALE, F32, F64, ASCII }

    private final Kind kind;
    private final String name;
    private long maxpos;      // linscale
    private double maxposD;   // linscale: maxpos as the nearest double
    private double range;     // linscale
    private double factor;    // uscale, sscale: decimal factor
    private boolean fraction; // uscale, sscale: the factor is num/den
    private double num;
    private double den;
    private double offset;

    private BitsTransform(Kind kind, String name) {
        this.kind = kind;
        this.name = name;
    }

    public String wireName() { return name; }

    /** The model type this transform yields. */
    public String yields() {
        switch (kind) {
            case UINT:
            case TWOS: return "int";
            case ASCII: return "string";
            default: return "float";
        }
    }

    boolean isAscii() { return kind == Kind.ASCII; }

    private static String head(String n) {
        int c = n.indexOf(':');
        return c < 0 ? n : n.substring(0, c);
    }

    /** True when {@code n} names a bits transform (well-formed or not), so another wire can reject it clearly. */
    static boolean isBitsName(String n) {
        switch (head(n)) {
            case "linscale":
            case "uscale":
            case "sscale":
                return true;
            case "uint":
            case "twos":
            case "f32":
            case "f64":
            case "ascii":
                return n.indexOf(':') < 0;
            default:
                return false;
        }
    }

    private static GtException bad(String format, String where, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": " + detail);
    }

    /** Number text (ruling 2b of 0.11) as a parameter; refused text is {@code bad-directive}. */
    private static double number(String s, String what, String name, String format, String where) {
        if (!Transform.isNumText(s)) throw bad(format, where, what + " is not number text in \"" + name + "\"");
        return Double.parseDouble(s);
    }

    /** An unsigned decimal integer (ruling 2c of 0.11) of at least 1 as a parameter. */
    private static long positive(String s, String what, String name, String format, String where) {
        if (!Transform.UNSIGNED.matcher(s).matches()) {
            throw bad(format, where, what + " is not an unsigned decimal integer in \"" + name + "\"");
        }
        double d = new BigDecimal(s).doubleValue();
        if (d < 1) throw bad(format, where, what + " must be at least 1 in \"" + name + "\"");
        return d >= 9.223372036854775807E18 ? Long.MAX_VALUE : new BigInteger(s).longValue();
    }

    /** Parse a bits transform token, checking its parameters (ruling 4d of 0.11). The caller has checked the name. */
    static BitsTransform parse(String name, String format, String where) {
        String[] p = name.split(":", -1);
        switch (p[0]) {
            case "uint": return new BitsTransform(Kind.UINT, name);
            case "twos": return new BitsTransform(Kind.TWOS, name);
            case "f32": return new BitsTransform(Kind.F32, name);
            case "f64": return new BitsTransform(Kind.F64, name);
            case "ascii": return new BitsTransform(Kind.ASCII, name);
            case "linscale": {
                if (p.length != 3) throw bad(format, where, "linscale takes linscale:<maxpos>:<range>, got \"" + name + "\"");
                BitsTransform t = new BitsTransform(Kind.LINSCALE, name);
                t.maxpos = positive(p[1], "linscale maxpos", name, format, where);
                t.maxposD = new BigDecimal(p[1]).doubleValue();
                t.range = number(p[2], "linscale range", name, format, where);
                if (t.range == 0) throw bad(format, where, "linscale range reads as zero in \"" + name + "\"");
                return t;
            }
            default: {
                if (p.length != 2 && p.length != 3) {
                    throw bad(format, where, p[0] + " takes " + p[0] + ":<factor>[:<offset>], got \"" + name + "\"");
                }
                BitsTransform t = new BitsTransform(p[0].equals("uscale") ? Kind.USCALE : Kind.SSCALE, name);
                int slash = p[1].indexOf('/');
                if (slash >= 0) {
                    String a = p[1].substring(0, slash), b = p[1].substring(slash + 1);
                    if (!Transform.UNSIGNED.matcher(a).matches() || !Transform.UNSIGNED.matcher(b).matches()) {
                        throw bad(format, where, "a fraction factor is <num>/<den> of two unsigned decimal integers, got \"" + p[1] + "\"");
                    }
                    t.fraction = true;
                    t.num = new BigDecimal(a).doubleValue();
                    t.den = new BigDecimal(b).doubleValue();
                    if (t.num == 0 || t.den == 0) throw bad(format, where, "a scale factor cannot be zero: \"" + p[1] + "\"");
                } else {
                    t.factor = number(p[1], "scale factor", name, format, where);
                    if (t.factor == 0) throw bad(format, where, "a scale factor reads as zero: \"" + p[1] + "\"");
                }
                t.offset = p.length == 3 ? number(p[2], "scale offset", name, format, where) : 0.0;
                return t;
            }
        }
    }

    /** Null when a field of {@code len} bits may carry this transform, else the reason. */
    String checkLen(int len) {
        switch (kind) {
            case F32: return len == 32 ? null : "f32 needs a 32-bit field, got " + len;
            case F64: return len == 64 ? null : "f64 needs a 64-bit field, got " + len;
            case ASCII:
                return (len % 8 == 0 && len >= 8 && len <= 2040) ? null
                        : "ascii needs a length that is a multiple of 8 from 8 to 2040, got " + len;
            default: return (len >= 1 && len <= 64) ? null : name + " needs a length of 1 to 64 bits, got " + len;
        }
    }

    /** The low {@code len} bits set, as a mask ({@code len == 64} is all ones). */
    static long mask(int len) { return len >= 64 ? -1L : (1L << len) - 1; }

    /** Interpret the {@code len}-bit {@code raw} value as a two's-complement signed integer. */
    static long twosValue(long raw, int len) {
        if (len >= 64) return raw;
        long signBit = 1L << (len - 1);
        return (raw & signBit) != 0 ? raw - (1L << len) : raw;
    }

    private static double unsignedToDouble(long raw) {
        return raw >= 0 ? (double) raw : new BigInteger(Long.toUnsignedString(raw)).doubleValue();
    }

    private double scaleDecode(double v) {
        double d = fraction ? v * num / den : v * factor;
        return d + offset;
    }

    /** Raw {@code len}-bit value to model value. Not for {@code ascii}. */
    Object decode(long raw, int len) {
        switch (kind) {
            case UINT:
                return raw;
            case TWOS:
                return twosValue(raw, len);
            case LINSCALE:
                return (double) twosValue(raw, len) / maxposD * range;
            case USCALE:
                return scaleDecode(unsignedToDouble(raw));
            case SSCALE:
                return scaleDecode((double) twosValue(raw, len));
            case F32:
                return finite((double) Float.intBitsToFloat((int) raw));
            case F64:
                return finite(Double.longBitsToDouble(raw));
            default:
                throw new IllegalStateException(kind.name());
        }
    }

    /** A model float is always finite: infinity and not-a-number on the wire are a decode failure. */
    static double finite(double d) {
        if (Double.isNaN(d)) throw new IllegalArgumentException("not-a-number on the wire");
        if (Double.isInfinite(d)) throw new IllegalArgumentException("infinity on the wire");
        return d;
    }

    /** A double narrowed to a single. A value outside single range is an encode failure. */
    static float narrow(double d) {
        float f = (float) d;
        if (Float.isNaN(f) || Float.isInfinite(f)) {
            throw new IllegalArgumentException("value " + Transform.formatOrText(d) + " is outside the range of a single");
        }
        return f;
    }

    /**
     * Model value to the {@code len} bits to write. A value outside the field's range is refused, never wrapped or
     * clamped (ruling 4b of 0.11). Throws IllegalArgumentException on a value it cannot carry.
     */
    long encode(Object value, int len) {
        switch (kind) {
            case UINT: {
                long v = Transform.asLong(value);
                if (len < 64 && (v < 0 || v > mask(len))) {
                    throw new IllegalArgumentException("value " + v + " does not fit a " + len + "-bit uint field");
                }
                return v & mask(len);
            }
            case TWOS: {
                long v = Transform.asLong(value);
                if (len < 64 && (v < -(1L << (len - 1)) || v > (1L << (len - 1)) - 1)) {
                    throw new IllegalArgumentException("value " + v + " does not fit a " + len + "-bit twos field");
                }
                return v & mask(len);
            }
            case LINSCALE: {
                double x = Transform.asDouble(value);
                double q = x / range * maxposD;
                return fit(q, len, true, x);
            }
            case USCALE:
            case SSCALE: {
                double x = Transform.asDouble(value);
                double q = fraction ? (x - offset) * den / num : (x - offset) / factor;
                return fit(q, len, kind == Kind.SSCALE, x);
            }
            case F32:
                return Float.floatToIntBits(narrow(Transform.asDouble(value))) & 0xFFFFFFFFL;
            case F64: {
                double d = Transform.asDouble(value);
                if (!Double.isFinite(d)) throw new IllegalArgumentException("value is not finite");
                return Double.doubleToLongBits(d);
            }
            default:
                throw new IllegalStateException(kind.name());
        }
    }

    /** {@code round(q)} (ruling 4a) checked against the field's range (4b), as the bits to write. */
    private static long fit(double q, int len, boolean signed, double x) {
        if (!Double.isFinite(q)) {
            throw new IllegalArgumentException("value " + Transform.formatOrText(x) + " scales to a quotient that is not finite");
        }
        double r = Transform.roundHalfAway(q);
        double lo = signed ? -Math.scalb(1.0, len - 1) : 0;
        double hi = signed ? Math.scalb(1.0, len - 1) : Math.scalb(1.0, len);   // lo <= r < hi, exact powers of two
        if (!(r >= lo && r < hi)) {
            throw new IllegalArgumentException("value " + Transform.formatOrText(x) + " rounds to " + Transform.formatOrText(r)
                    + ", outside the range of a " + len + "-bit " + (signed ? "signed" : "unsigned") + " field");
        }
        return toLong(r) & mask(len);
    }

    /** An integral double within the range of a 64-bit field to the 64-bit pattern of that integer. */
    private static long toLong(double r) {
        if (r >= -9.223372036854775808E18 && r < 9.223372036854775808E18) return (long) r;
        return new BigDecimal(r).toBigInteger().longValue();   // an unsigned 64-bit value at or above 2^63
    }

    /**
     * {@code ascii}: the field's bytes in wire order to text, trailing NUL bytes removed; with {@code trim}, the
     * trailing spaces after them too.
     */
    String decodeAscii(byte[] bytes, boolean trim) {
        int n = bytes.length;
        while (n > 0 && bytes[n - 1] == 0) n--;
        if (trim) while (n > 0 && bytes[n - 1] == 0x20) n--;
        for (int i = 0; i < n; i++) {
            int b = bytes[i] & 0xff;
            if (b > 0x7E || b < 0x20) {
                throw new IllegalArgumentException(String.format("byte 0x%02x at offset %d is not printable ASCII", b, i));
            }
        }
        return new String(bytes, 0, n, StandardCharsets.US_ASCII);
    }

    /** {@code ascii}: text to {@code size} bytes, NUL-padded. Longer text is an error. */
    byte[] encodeAscii(Object value, int size) {
        String s = value instanceof Double ? Transform.formatDouble((Double) value) : String.valueOf(value);
        byte[] b = s.getBytes(StandardCharsets.UTF_8);
        for (int i = 0; i < b.length; i++) {
            int c = b[i] & 0xff;
            if (c > 0x7E || c < 0x20) {
                throw new IllegalArgumentException(String.format("byte 0x%02x at offset %d is not printable ASCII", c, i));
            }
        }
        if (b.length > size) {
            throw new IllegalArgumentException("text of " + b.length + " bytes does not fit a field of " + size + " bytes");
        }
        byte[] out = new byte[size];
        System.arraycopy(b, 0, out, 0, b.length);
        return out;
    }
}
