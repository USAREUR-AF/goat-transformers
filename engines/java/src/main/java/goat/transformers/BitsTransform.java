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
    enum Kind { UINT, TWOS, LINSCALE, USCALE, SSCALE, F32, F64, ASCII, SIXBIT,
        // engine-spec 0.15
        UISCALE, SISCALE, SMAG, SMSCALE, F32SCALE, F64SCALE, CHARS, OCTAL,
        // engine-spec 0.22
        HEX,
        // engine-spec 0.55
        UTF8 }

    /** The character sets of {@code chars:<set>}. */
    enum CharSet { ICAO6, AIS6, ASCII7, ASCII8,
        /** {@code hex} (engine-spec 0.22): 4-bit digits, read and written as the characters of a set are. */
        HEX }

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
    /** uscale, sscale: the decimal places of the third argument (engine-spec 0.55), or -1 when there is none. */
    private int places = -1;
    private Scales.Exact exact;       // uiscale, siscale
    private Scales.Floating floating; // smscale, f32scale, f64scale
    private CharSet set;              // chars

    private BitsTransform(Kind kind, String name) {
        this.kind = kind;
        this.name = name;
    }

    public String wireName() { return name; }

    /** The model type this transform yields. */
    public String yields() {
        switch (kind) {
            case UINT:
            case TWOS:
            case UISCALE:
            case SISCALE:
            case SMAG: return "int";
            case ASCII:
            case UTF8:
            case SIXBIT:
            case CHARS:
            case HEX:
            case OCTAL: return "string";
            default: return "float";
        }
    }

    boolean isAscii() { return kind == Kind.ASCII; }

    /**
     * {@code ascii} or {@code utf8} (engine-spec 0.55): the transforms that take the field's bytes in wire order, with
     * {@code swap} and {@code trim}, through {@link #decodeBytes} and {@link #encodeBytes}.
     */
    boolean isByteText() { return kind == Kind.ASCII || kind == Kind.UTF8; }

    /** {@code uscale} or {@code sscale} with a {@code <places>} argument (engine-spec 0.55). */
    boolean hasPlaces() { return places >= 0; }

    /** {@code sixbit} (engine-spec 0.14): six-bit character codes. */
    boolean isSixbit() { return kind == Kind.SIXBIT; }

    /** {@code ascii} or {@code sixbit}: the transforms that take the field option {@code trim}. */
    boolean takesTrim() { return kind == Kind.ASCII || kind == Kind.UTF8 || kind == Kind.SIXBIT; }

    /**
     * {@code chars:<set>}, and {@code hex} (engine-spec 0.22): read and written as characters of {@link #charWidth}
     * bits, each as {@code uint} reads a field of that width at its place.
     */
    boolean isChars() { return kind == Kind.CHARS || kind == Kind.HEX; }

    /** {@code chars:<set>} only: the transform that takes {@code until:} and {@code stop} (engine-spec 0.22). */
    boolean isCharSet() { return kind == Kind.CHARS; }

    /** {@code chars}, {@code octal} and {@code hex} take no {@code swap} (engine-spec 0.15, Load errors; 0.22). */
    boolean refusesSwap() { return kind == Kind.CHARS || kind == Kind.OCTAL || kind == Kind.HEX; }

    int charWidth() {
        switch (set) {
            case HEX: return 4;
            case ASCII7: return 7;
            case ASCII8: return 8;
            default: return 6;
        }
    }

    /** {@code stop <code>} (engine-spec 0.22): the code that ends the text of a fixed-size {@code chars} field, or -1. */
    int stop = -1;

    /** True when {@code head} is the name of a {@code bits} transform of engine-spec 0.15. */
    static boolean isV015(String head) {
        switch (head) {
            case "uiscale":
            case "siscale":
            case "smag":
            case "smscale":
            case "f32scale":
            case "f64scale":
            case "chars":
            case "octal":
                return true;
            default:
                return false;
        }
    }

    static String headOf(String n) { return head(n); }

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
            case "uiscale":
            case "siscale":
            case "smag":
            case "smscale":
            case "f32scale":
            case "f64scale":
            case "chars":
            case "octal":
                return true;
            case "uint":
            case "twos":
            case "f32":
            case "f64":
            case "ascii":
            case "sixbit":
            case "utf8":  // engine-spec 0.55
            case "hex":   // engine-spec 0.22
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
        if (isV015(p[0])) {
            try {
                return parseV015(name, p);
            } catch (IllegalArgumentException ex) {
                throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": " + name + ": " + ex.getMessage());
            }
        }
        switch (p[0]) {
            case "uint": return new BitsTransform(Kind.UINT, name);
            case "twos": return new BitsTransform(Kind.TWOS, name);
            case "f32": return new BitsTransform(Kind.F32, name);
            case "f64": return new BitsTransform(Kind.F64, name);
            case "ascii": return new BitsTransform(Kind.ASCII, name);
            case "utf8": return new BitsTransform(Kind.UTF8, name);
            case "sixbit": return new BitsTransform(Kind.SIXBIT, name);
            case "hex": {
                BitsTransform t = new BitsTransform(Kind.HEX, name);
                t.set = CharSet.HEX;
                return t;
            }
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
                // engine-spec 0.55: a third argument <places>; no argument may be empty, and there are at most three
                if (p.length < 2 || p.length > 4) {
                    throw bad(format, where, p[0] + " takes " + p[0] + ":<factor>[:<offset>[:<places>]], got \"" + name + "\"");
                }
                for (int i = 1; i < p.length; i++) {
                    if (p[i].isEmpty()) {
                        throw bad(format, where, "argument " + i + " of \"" + name + "\" is empty (write " + p[0] + ":<factor>:0:<places>)");
                    }
                }
                BitsTransform t = new BitsTransform(p[0].equals("uscale") ? Kind.USCALE : Kind.SSCALE, name);
                int slash = p[1].indexOf('/');
                if (slash >= 0) {
                    String a = p[1].substring(0, slash), b = p[1].substring(slash + 1);
                    // a fraction has unsigned num and den (ruling 25 of 0.15)
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
                t.offset = p.length >= 3 ? number(p[2], "scale offset", name, format, where) : 0.0;
                if (p.length == 4) {
                    // a decimal integer as 2c of 0.11 states, leading zeros allowed, at most 15
                    if (!Transform.UNSIGNED.matcher(p[3]).matches() || new BigInteger(p[3]).compareTo(BigInteger.valueOf(15)) > 0) {
                        throw bad(format, where, "places is an unsigned decimal integer from 0 to 15, got \"" + p[3] + "\" in \"" + name + "\"");
                    }
                    t.places = Integer.parseInt(p[3].replaceFirst("^0+(?=.)", ""));
                }
                return t;
            }
        }
    }

    private static BitsTransform parseV015(String name, String[] p) {
        String[] params = java.util.Arrays.copyOfRange(p, 1, p.length);
        BitsTransform t;
        switch (p[0]) {
            case "uiscale":
            case "siscale":
                t = new BitsTransform(p[0].equals("uiscale") ? Kind.UISCALE : Kind.SISCALE, name);
                t.exact = Scales.Exact.parse(params);
                return t;
            case "smscale":
            case "f32scale":
            case "f64scale":
                t = new BitsTransform(p[0].equals("smscale") ? Kind.SMSCALE : p[0].equals("f32scale") ? Kind.F32SCALE : Kind.F64SCALE, name);
                t.floating = Scales.Floating.parse(params);
                return t;
            case "smag":
            case "octal":
                if (params.length != 0) throw new IllegalArgumentException("takes no parameter");
                return new BitsTransform(p[0].equals("smag") ? Kind.SMAG : Kind.OCTAL, name);
            default: { // chars
                if (params.length != 1) throw new IllegalArgumentException("is chars:<icao6|ais6|ascii7>");
                t = new BitsTransform(Kind.CHARS, name);
                switch (params[0]) {
                    case "icao6": t.set = CharSet.ICAO6; break;
                    case "ais6": t.set = CharSet.AIS6; break;
                    case "ascii7": t.set = CharSet.ASCII7; break;
                    case "ascii8": t.set = CharSet.ASCII8; break;   // engine-spec 0.22
                    default: throw new IllegalArgumentException("unknown character set \"" + params[0] + "\"");
                }
                return t;
            }
        }
    }

    /** Null when a field of {@code len} bits may carry this transform, else the reason. */
    String checkLen(int len) {
        switch (kind) {
            case UISCALE:
            case SISCALE:
                return (len >= 1 && len <= 64) ? null : name + " needs a length of 1 to 64 bits, got " + len;
            case SMAG:
            case SMSCALE:
                return (len >= 2 && len <= 64) ? null : name + " needs a length of 2 to 64 bits, got " + len;
            case F32SCALE: return len == 32 ? null : "f32scale needs a 32-bit field, got " + len;
            case F64SCALE: return len == 64 ? null : "f64scale needs a 64-bit field, got " + len;
            case CHARS: {
                int w = charWidth();
                return (len % w == 0 && len >= w && len <= 2040) ? null
                        : name + " needs a length that is a multiple of " + w + " from " + w + " to 2040, got " + len;
            }
            case HEX:
                return (len % 4 == 0 && len >= 4 && len <= 2040) ? null
                        : "hex needs a length that is a multiple of 4 from 4 to 2040, got " + len;
            case OCTAL:
                return (len % 3 == 0 && len >= 3 && len <= 63) ? null
                        : "octal needs a length that is a multiple of 3 from 3 to 63, got " + len;
            case F32: return len == 32 ? null : "f32 needs a 32-bit field, got " + len;
            case F64: return len == 64 ? null : "f64 needs a 64-bit field, got " + len;
            case ASCII:
            case UTF8:
                return (len % 8 == 0 && len >= 8 && len <= 2040) ? null
                        : name + " needs a length that is a multiple of 8 from 8 to 2040, got " + len;
            case SIXBIT:
                return (len % 6 == 0 && len >= 6 && len <= 1530) ? null
                        : "sixbit needs a length that is a multiple of 6 from 6 to 1530, got " + len;
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

    /** The powers of ten 10^0 to 10^15, each exact as a double. */
    private static final double[] POW10 = {1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15};

    /**
     * {@code uscale} and {@code sscale} decode at a bit position or bit length (engine-spec 0.55): the value of ruling 1
     * of 0.5, then, with {@code <places>}, rounded to that many decimal places (steps 1 to 4); a value that is not
     * finite is transform-decode with {@code <places>} (ruling 5).
     */
    private double scaleDecodeBits(double v) {
        double x = scaleDecode(v);
        if (places < 0) return x;
        if (!Double.isFinite(x)) throw new IllegalArgumentException("the scaled value is not finite");
        double p = POW10[places];
        double y = x * p;
        if (Double.isFinite(y)) {
            double r = Transform.roundHalfAway(y);
            if (Math.abs(r) < 1e15) return r / p + 0.0;   // + 0.0: a result of zero is +0
        }
        return x;
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
                return scaleDecodeBits(unsignedToDouble(raw));
            case SSCALE:
                return scaleDecodeBits((double) twosValue(raw, len));
            case F32:
                return finite((double) Float.intBitsToFloat((int) raw));
            case F64:
                return finite(Double.longBitsToDouble(raw));
            case UISCALE:
                return exact.decode(new BigInteger(Long.toUnsignedString(raw)), BigInteger.ONE);
            case SISCALE:
                return exact.decode(BigInteger.valueOf(twosValue(raw, len)), BigInteger.ONE);
            case SMAG:
                return smagValue(raw, len);
            case SMSCALE:
                return finite(floating.apply((double) smagValue(raw, len)));
            case F32SCALE:
                return finite(floating.apply(finite((double) Float.intBitsToFloat((int) raw))));
            case F64SCALE:
                return finite(floating.apply(finite(Double.longBitsToDouble(raw))));
            case OCTAL: {
                StringBuilder b = new StringBuilder(Long.toOctalString(raw));
                while (b.length() < len / 3) b.insert(0, '0');
                return b.toString();
            }
            default:
                throw new IllegalStateException(kind.name());
        }
    }

    /** The sign-and-magnitude value of a {@code len}-bit field: the top bit is the sign, the rest the magnitude. */
    static long smagValue(long raw, int len) {
        long mag = raw & mask(len - 1);
        return ((raw >>> (len - 1)) & 1) != 0 ? -mag : mag;
    }

    /** {@code smag} encode of the integer {@code r}: sign 1 when negative, magnitude below {@code 2^(len-1)}. */
    static long smagBits(BigInteger r, int len) {
        BigInteger mag = r.abs();
        if (mag.bitLength() > len - 1) {
            throw new IllegalArgumentException("magnitude " + mag + " does not fit the " + (len - 1) + " magnitude bits");
        }
        long bits = mag.longValue();
        if (r.signum() < 0) bits |= 1L << (len - 1);
        return bits;
    }

    /** {@code value} fits {@code len} bits as unsigned ({@code signed} false) or two's complement. */
    private static long fit(BigInteger r, int len, boolean signed) {
        boolean ok = signed ? r.bitLength() <= len - 1 : r.signum() >= 0 && r.bitLength() <= len;
        if (!ok) {
            throw new IllegalArgumentException("value " + r + " does not fit a " + len + "-bit "
                    + (signed ? "two's-complement" : "unsigned") + " field");
        }
        return r.longValue() & mask(len);
    }

    /**
     * A UPER integer locator (0.19): the integer value {@code v}, not raw bits, to its model value. {@code uint} and
     * {@code twos} give {@code v}; the scales give {@code v * f + o} (ruling 4 of 0.19: both are signed).
     */
    Object decodeInteger(long v) {
        switch (kind) {
            case UINT:
            case TWOS:
                return v;
            case USCALE:
            case SSCALE:
                return scaleDecode((double) v);
            default:
                throw new IllegalStateException(kind.name());
        }
    }

    /**
     * A UPER integer locator: the model value to the integer to write, {@code round((x - o) / f)} for the scales.
     * Throws IllegalArgumentException when there is no such 64-bit integer; the caller checks the constraint.
     */
    long encodeInteger(Object value) {
        switch (kind) {
            case UINT:
            case TWOS:
                return Transform.asLong(value);
            case USCALE:
            case SSCALE: {
                double x = Transform.asDouble(value);
                double q = fraction ? (x - offset) * den / num : (x - offset) / factor;
                double r = Transform.roundHalfAway(q);
                if (Double.isNaN(r)) throw new IllegalArgumentException("value is not a number");
                if (!(r >= -9.223372036854775808E18 && r < 9.223372036854775808E18)) {
                    throw new IllegalArgumentException("value " + Transform.formatOrText(x) + " scales to " + r + ", outside every 64-bit integer");
                }
                return (long) r;
            }
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
            case UISCALE:
            case SISCALE:
                return fit(exact.encodeRounded(value), len, kind == Kind.SISCALE);
            case SMAG:
                return smagBits(BigInteger.valueOf(Transform.asLong(value)), len);
            case SMSCALE: {
                double q = Transform.roundHalfAway(floating.invert(Transform.asDouble(value)));
                if (!Double.isFinite(q)) throw new IllegalArgumentException("the quotient is not finite");
                return smagBits(new BigDecimal(q).toBigIntegerExact(), len);
            }
            case F32SCALE: {
                double q = floating.invert(Transform.asDouble(value));
                if (!Double.isFinite(q)) throw new IllegalArgumentException("the quotient is not finite");
                return Float.floatToIntBits(narrow(q)) & 0xFFFFFFFFL;
            }
            case F64SCALE: {
                double q = floating.invert(Transform.asDouble(value));
                if (!Double.isFinite(q)) throw new IllegalArgumentException("the quotient is not finite");
                return Double.doubleToLongBits(q);
            }
            case OCTAL: {
                String s = String.valueOf(value);
                if (s.length() != len / 3 || !s.matches("[0-7]*")) {
                    throw new IllegalArgumentException("octal needs exactly " + (len / 3) + " digits 0-7, got \"" + s + "\"");
                }
                return s.isEmpty() ? 0 : Long.parseLong(s, 8);
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

    /** {@code ascii} or {@code utf8}: the field's bytes in wire order ({@code swap} applied) to text. */
    String decodeBytes(byte[] bytes, boolean trim) {
        return kind == Kind.UTF8 ? decodeUtf8(bytes, trim) : decodeAscii(bytes, trim);
    }

    /** {@code ascii} or {@code utf8}: text to {@code size} bytes in wire order, before {@code swap}. */
    byte[] encodeBytes(Object value, int size) {
        return kind == Kind.UTF8 ? encodeUtf8(value, size) : encodeAscii(value, size);
    }

    /**
     * {@code utf8} on {@code bits} (engine-spec 0.55): trailing NUL bytes removed, then with {@code trim} the trailing
     * spaces before them; what is left is valid UTF-8 (RFC 3629) holding no NUL, else transform-decode.
     */
    static String decodeUtf8(byte[] bytes, boolean trim) {
        int n = bytes.length;
        while (n > 0 && bytes[n - 1] == 0) n--;
        if (trim) while (n > 0 && bytes[n - 1] == 0x20) n--;
        for (int i = 0; i < n; i++) {
            if (bytes[i] == 0) throw new IllegalArgumentException("a NUL byte at offset " + i + " is inside the text");
        }
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
                    .decode(java.nio.ByteBuffer.wrap(bytes, 0, n)).toString();
        } catch (java.nio.charset.CharacterCodingException ex) {
            throw new IllegalArgumentException("the field's bytes are not valid UTF-8");
        }
    }

    /**
     * {@code utf8} on {@code bits}: the text's UTF-8 bytes, NUL-padded to {@code size}. U+0000, a lone surrogate (which
     * UTF-8 cannot carry) or text longer than {@code size} bytes is transform-encode.
     */
    static byte[] encodeUtf8(Object value, int size) {
        String s = value instanceof Double ? Transform.formatDouble((Double) value) : String.valueOf(value);
        int z = s.indexOf('\u0000');
        if (z >= 0) throw new IllegalArgumentException("the text holds U+0000 at offset " + z);
        byte[] b;
        try {
            java.nio.ByteBuffer bb = StandardCharsets.UTF_8.newEncoder()
                    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
                    .encode(java.nio.CharBuffer.wrap(s));
            b = new byte[bb.remaining()];
            bb.get(b);
        } catch (java.nio.charset.CharacterCodingException ex) {
            throw new IllegalArgumentException("the text holds a lone surrogate, which UTF-8 cannot carry");
        }
        if (b.length > size) {
            throw new IllegalArgumentException("text of " + b.length + " UTF-8 bytes does not fit a field of " + size + " bytes");
        }
        byte[] out = new byte[size];
        System.arraycopy(b, 0, out, 0, b.length);
        return out;
    }

    /**
     * {@code sixbit}: the field's six-bit values, first character first, to text: 0 to 31 as {@code @} to
     * {@code _}, 32 to 63 as space to {@code ?}; trailing {@code @} removed, and with {@code trim} the whole
     * trailing run of {@code @} and space, in any mix. Never fails.
     */
    static String decodeSixbit(int[] values, boolean trim) {
        char[] c = new char[values.length];
        for (int i = 0; i < c.length; i++) {
            int v = values[i] & 0x3f;
            c[i] = (char) (v < 32 ? 0x40 + v : v);
        }
        int n = c.length;
        if (trim) {
            while (n > 0 && (c[n - 1] == '@' || c[n - 1] == ' ')) n--;
        } else {
            while (n > 0 && c[n - 1] == '@') n--;
        }
        return new String(c, 0, n);
    }

    /**
     * {@code sixbit}: text to {@code chars} six-bit values, padded with {@code @} (0). A character outside 0x20 to
     * 0x5F, or text longer than {@code chars}, is an error.
     */
    static int[] encodeSixbit(Object value, int chars) {
        String s = value instanceof Double ? Transform.formatDouble((Double) value) : String.valueOf(value);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x20 || c > 0x5F) {
                throw new IllegalArgumentException(String.format("character U+%04X at offset %d is not a six-bit character (0x20 to 0x5F)", (int) c, i));
            }
        }
        if (s.length() > chars) {
            throw new IllegalArgumentException("text of " + s.length() + " characters does not fit a field of " + chars + " six-bit characters");
        }
        int[] out = new int[chars];
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            out[i] = c >= 0x40 ? c - 0x40 : c;
        }
        return out;
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

    /**
     * {@code chars}: the codes of the field's characters, first character first, to text. With {@code stop}, the
     * text ends at the first terminator code and is exact; with none found, the 0.15 rules (rulings 18 and 19 of 0.22).
     */
    String decodeChars(int[] codes) {
        if (set == CharSet.HEX) {
            StringBuilder b = new StringBuilder(codes.length);
            for (int c : codes) b.append(Character.forDigit(c, 16));
            return b.toString();
        }
        if (stop >= 0) {
            for (int i = 0; i < codes.length; i++) {
                if (codes[i] == stop) return decodeExact(java.util.Arrays.copyOf(codes, i));
            }
        }
        char[] out = new char[codes.length];
        for (int i = 0; i < codes.length; i++) {
            int c = codes[i];
            char ch;
            switch (set) {
                case ICAO6:
                    if (c >= 1 && c <= 26) ch = (char) ('A' + c - 1);
                    else if (c == 32) ch = ' ';
                    else if (c >= 48 && c <= 57) ch = (char) c;
                    else throw new IllegalArgumentException("code " + c + " of character " + i + " is not in icao6");
                    break;
                case AIS6:
                    ch = (char) (c < 32 ? c + 64 : c);
                    break;
                default:
                    if (c == 0) ch = 0;
                    else if (c >= 32 && c <= 126) ch = (char) c;
                    else throw new IllegalArgumentException("code " + c + " of character " + i + " is not in " + setName());
                    if (c != 0 && i > 0 && out[i - 1] == 0) {
                        throw new IllegalArgumentException("a NUL is followed by a character that is not NUL at character " + i);
                    }
            }
            out[i] = ch;
        }
        int n = out.length;
        switch (set) {
            case ICAO6:
                while (n > 0 && out[n - 1] == ' ') n--;
                break;
            case AIS6:
                while (n > 0 && (out[n - 1] == ' ' || out[n - 1] == '@')) n--;
                break;
            default:
                while (n > 0 && out[n - 1] == 0) n--;
        }
        return new String(out, 0, n);
    }

    String setName() { return set.name().toLowerCase(java.util.Locale.ROOT); }

    /** The character a code of the set stands for, or -1 for a code the set does not give a character. */
    private int charOf(int c) {
        switch (set) {
            case ICAO6:
                if (c >= 1 && c <= 26) return 'A' + c - 1;
                if (c == 32 || (c >= 48 && c <= 57)) return c;
                return -1;
            case AIS6:
                return c < 32 ? c + 64 : c;
            default:
                return c == 0 || (c >= 32 && c <= 126) ? c : -1;
        }
    }

    /** The code of a character in the set, or -1 (NUL is code 0 in ascii7 and ascii8). */
    private int codeOf(char ch) {
        switch (set) {
            case ICAO6:
                if (ch >= 'A' && ch <= 'Z') return ch - 'A' + 1;
                return ch == ' ' || (ch >= '0' && ch <= '9') ? ch : -1;
            case AIS6:
                if (ch >= 64 && ch <= 95) return ch - 64;
                return ch >= 32 && ch <= 63 ? ch : -1;
            default:
                return ch == 0 || (ch >= 32 && ch <= 126) ? ch : -1;
        }
    }

    /**
     * Codes to text exactly: nothing removed, and NUL an ordinary character (the text before a terminator,
     * rulings 6, 7, 18, 20 and 21 of 0.22). A code the set does not hold is transform-decode.
     */
    String decodeExact(int[] codes) {
        StringBuilder b = new StringBuilder(codes.length);
        for (int i = 0; i < codes.length; i++) {
            int ch = charOf(codes[i]);
            if (ch < 0) throw new IllegalArgumentException("code " + codes[i] + " of character " + i + " is not in " + setName());
            b.append((char) ch);
        }
        return b.toString();
    }

    /**
     * Text to its codes before a terminator {@code term} (engine-spec 0.22): a character the set cannot hold, or one
     * whose code is the terminator's, is transform-encode; NUL is an ordinary character (ruling 20).
     */
    int[] encodeExact(String s, int term) {
        int[] codes = new int[s.length()];
        for (int i = 0; i < s.length(); i++) {
            char ch = s.charAt(i);
            int c = codeOf(ch);
            if (c < 0) throw new IllegalArgumentException(String.format("character U+%04X at %d is not in %s", (int) ch, i, setName()));
            if (c == term) throw new IllegalArgumentException(String.format("character U+%04X at %d is the terminator", (int) ch, i));
            codes[i] = c;
        }
        return codes;
    }

    /** {@code chars}: text to the codes of {@code count} characters, padded with the set's padding. */
    int[] encodeChars(Object value, int count) {
        String s = value instanceof Double ? Transform.formatDouble((Double) value) : String.valueOf(value);
        if (set == CharSet.HEX) {
            // each digit, either case, as a 4-bit field; text of another length is transform-encode (engine-spec 0.22)
            if (s.length() != count) {
                throw new IllegalArgumentException("hex text of " + s.length() + " digits, the field holds exactly " + count);
            }
            int[] codes = new int[count];
            for (int i = 0; i < count; i++) {
                int d = Character.digit(s.charAt(i), 16);
                if (d < 0 || s.charAt(i) > 'f') throw new IllegalArgumentException("character \"" + s.charAt(i) + "\" at " + i + " is not a hex digit");
                codes[i] = d;
            }
            return codes;
        }
        if (stop >= 0) {
            // the text, the terminator, then padding to the field's size (engine-spec 0.22, stop)
            int[] text = encodeExact(s, stop);
            if (text.length + 1 > count) {
                throw new IllegalArgumentException("text of " + text.length + " characters leaves no room for the terminator in " + count + " characters");
            }
            int[] codes = new int[count];
            int pad = set == CharSet.ICAO6 ? 32 : 0;
            java.util.Arrays.fill(codes, pad);
            System.arraycopy(text, 0, codes, 0, text.length);
            codes[text.length] = stop;
            return codes;
        }
        if (s.length() > count) {
            throw new IllegalArgumentException("text of " + s.length() + " characters does not fit " + count + " characters");
        }
        int[] codes = new int[count];
        int pad = set == CharSet.ICAO6 ? 32 : 0;
        for (int i = 0; i < count; i++) {
            if (i >= s.length()) {
                codes[i] = pad;
                continue;
            }
            char ch = s.charAt(i);
            int c;
            switch (set) {
                case ICAO6:
                    if (ch >= 'A' && ch <= 'Z') c = ch - 'A' + 1;
                    else if (ch == ' ' || (ch >= '0' && ch <= '9')) c = ch;
                    else c = -1;
                    break;
                case AIS6:
                    if (ch >= 64 && ch <= 95) c = ch - 64;
                    else if (ch >= 32 && ch <= 63) c = ch;
                    else c = -1;
                    break;
                default:
                    c = (ch >= 32 && ch <= 126) ? ch : -1;
            }
            if (c < 0) {
                throw new IllegalArgumentException(String.format("character U+%04X at %d is not in %s", (int) ch, i, set.name().toLowerCase()));
            }
            codes[i] = c;
        }
        return codes;
    }
}
