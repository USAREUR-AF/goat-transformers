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

    private static final String DECIMAL = "[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?";

    private static double decimal(String s, String what, String name, String format, String where) {
        if (!s.matches(DECIMAL)) {
            throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": " + what + " is not a decimal number in \"" + name + "\"");
        }
        double d = Double.parseDouble(s);
        if (!Double.isFinite(d)) {
            throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": " + what + " is out of range in \"" + name + "\"");
        }
        return d;
    }

    /** Parse a bits transform token. The caller has checked {@link #isBitsName}. */
    static BitsTransform parse(String name, String format, String where) {
        String[] p = name.split(":", -1);
        switch (p[0]) {
            case "uint": return new BitsTransform(Kind.UINT, name);
            case "twos": return new BitsTransform(Kind.TWOS, name);
            case "f32": return new BitsTransform(Kind.F32, name);
            case "f64": return new BitsTransform(Kind.F64, name);
            case "ascii": return new BitsTransform(Kind.ASCII, name);
            case "linscale": {
                if (p.length != 3) {
                    throw new GtException(GtException.Code.BAD_PACK, format, null,
                            where + ": linscale transform must be linscale:<maxpos>:<range>, got \"" + name + "\"");
                }
                BitsTransform t = new BitsTransform(Kind.LINSCALE, name);
                try {
                    t.maxpos = Long.parseLong(p[1]);
                } catch (NumberFormatException ex) {
                    throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": linscale maxpos is not an integer: \"" + p[1] + "\"");
                }
                if (t.maxpos <= 0) {
                    throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": linscale maxpos must be positive, got " + t.maxpos);
                }
                t.range = decimal(p[2], "linscale range", name, format, where);
                return t;
            }
            default: {
                if (p.length != 2 && p.length != 3) {
                    throw new GtException(GtException.Code.BAD_PACK, format, null,
                            where + ": transform must be " + p[0] + ":<factor>[:<offset>], got \"" + name + "\"");
                }
                BitsTransform t = new BitsTransform(p[0].equals("uscale") ? Kind.USCALE : Kind.SSCALE, name);
                int slash = p[1].indexOf('/');
                if (slash >= 0) {
                    String a = p[1].substring(0, slash), b = p[1].substring(slash + 1);
                    if (!a.matches("[+-]?\\d+") || !b.matches("[+-]?\\d+")) {
                        throw new GtException(GtException.Code.BAD_PACK, format, null,
                                where + ": a fraction factor is <num>/<den> of two decimal integers, got \"" + p[1] + "\"");
                    }
                    t.fraction = true;
                    t.num = Double.parseDouble(a);
                    t.den = Double.parseDouble(b);
                    if (t.num == 0 || t.den == 0) {
                        throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": a scale factor cannot be zero: \"" + p[1] + "\"");
                    }
                } else {
                    t.factor = decimal(p[1], "scale factor", name, format, where);
                    if (t.factor == 0) {
                        throw new GtException(GtException.Code.BAD_PACK, format, null, where + ": a scale factor cannot be zero: \"" + p[1] + "\"");
                    }
                }
                t.offset = p.length == 3 ? decimal(p[2], "scale offset", name, format, where) : 0.0;
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
                return (double) twosValue(raw, len) / maxpos * range;
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

    /** Model value to the low {@code len} bits to write. Throws IllegalArgumentException on a value it cannot carry. */
    long encode(Object value, int len) {
        switch (kind) {
            case UINT:
            case TWOS:
                return Transform.asLong(value) & mask(len);
            case LINSCALE: {
                double x = Transform.asDouble(value);
                double q = Transform.roundHalfAway(x / range * maxpos);
                return toLong(q) & mask(len);
            }
            case USCALE:
            case SSCALE: {
                double x = Transform.asDouble(value);
                double q = fraction ? (x - offset) * den / num : (x - offset) / factor;
                double r = Transform.roundHalfAway(q);
                double lo, hi; // lo <= r < hi
                if (kind == Kind.USCALE) {
                    lo = 0;
                    hi = Math.scalb(1.0, len);
                } else {
                    lo = -Math.scalb(1.0, len - 1);
                    hi = Math.scalb(1.0, len - 1);
                }
                if (!(r >= lo && r < hi)) {
                    throw new IllegalArgumentException("value " + Transform.formatOrText(x) + " scales to " + r
                            + ", outside the range of a " + len + "-bit " + (kind == Kind.USCALE ? "unsigned" : "signed") + " field");
                }
                return toLong(r) & mask(len);
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

    /** An integral double to the 64-bit pattern of that integer (the low 64 bits when it does not fit). */
    private static long toLong(double r) {
        if (Double.isNaN(r)) throw new IllegalArgumentException("value is not a number");
        if (Double.isInfinite(r)) throw new IllegalArgumentException("value is infinite");
        if (r >= -9.223372036854775808E18 && r < 9.223372036854775808E18) return (long) r;
        return new BigDecimal(r).toBigInteger().longValue();
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
