package goat.transformers;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The scales of engine-spec 0.15. {@link Exact}: the integer scales ({@code uiscale}, {@code siscale},
 * {@code iscale}), whose factor and offset are exact numbers and whose arithmetic is exact rational arithmetic with
 * round-half-away-from-zero. {@link Floating}: the float scales ({@code smscale}, {@code f32scale},
 * {@code f64scale}, {@code scale}), which read factor and offset as {@code sscale} does (ruling 1 of 0.5).
 * Parse failures are IllegalArgumentException with the reason; the caller reports {@code bad-directive}.
 */
final class Scales {
    private Scales() {}

    static final BigInteger TWO32 = BigInteger.ONE.shiftLeft(32);
    static final BigInteger LONG_MIN = BigInteger.valueOf(Long.MIN_VALUE);
    static final BigInteger LONG_MAX = BigInteger.valueOf(Long.MAX_VALUE);

    /** {@code round(p / q)}, half away from zero; {@code q > 0}. */
    static BigInteger roundDiv(BigInteger p, BigInteger q) {
        BigInteger r = p.abs().shiftLeft(1).add(q).divide(q.shiftLeft(1));
        return p.signum() < 0 ? r.negate() : r;
    }

    static boolean fitsLong(BigInteger v) { return v.compareTo(LONG_MIN) >= 0 && v.compareTo(LONG_MAX) <= 0; }

    /** A model value as an exact fraction {@code {p, q}}, {@code q > 0}. */
    static BigInteger[] exactOf(Object v) {
        if (v instanceof Long || v instanceof Integer) return new BigInteger[]{BigInteger.valueOf(((Number) v).longValue()), BigInteger.ONE};
        BigDecimal d;
        if (v instanceof Double) {
            double x = (Double) v;
            if (!Double.isFinite(x)) throw new IllegalArgumentException("value is not finite");
            d = new BigDecimal(x);
        } else if (v instanceof String) {
            String s = (String) v;
            if (!s.matches("[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)")) throw new IllegalArgumentException("not a number: \"" + s + "\"");
            d = new BigDecimal(s);
        } else {
            throw new IllegalArgumentException("cannot carry " + v + " as a number");
        }
        if (d.scale() <= 0) return new BigInteger[]{d.toBigIntegerExact(), BigInteger.ONE};
        return new BigInteger[]{d.unscaledValue(), BigInteger.TEN.pow(d.scale())};
    }

    /**
     * {@code p / q} ({@code q > 0}) in plain decimal notation: {@code -} for a negative value, the integer digits,
     * and a {@code .} and the fraction digits with no trailing zero when it is not an integer. Throws when the
     * quotient does not terminate within 18 fraction digits.
     */
    static String plain(BigInteger p, BigInteger q) {
        BigInteger g = p.gcd(q);
        if (g.signum() != 0) {
            p = p.divide(g);
            q = q.divide(g);
        }
        int twos = q.getLowestSetBit();
        BigInteger rest = q.shiftRight(twos);
        int fives = 0;
        BigInteger five = BigInteger.valueOf(5);
        while (fives <= 18) {
            BigInteger[] qr = rest.divideAndRemainder(five);
            if (qr[1].signum() != 0) break;
            rest = qr[0];
            fives++;
        }
        int k = Math.max(twos, fives);
        if (!rest.equals(BigInteger.ONE) || k > 18) {
            throw new IllegalArgumentException("the quotient does not terminate within 18 fraction digits");
        }
        BigInteger scaled = p.multiply(BigInteger.TEN.pow(k)).divide(q);
        String digits = scaled.abs().toString();
        StringBuilder b = new StringBuilder();
        if (scaled.signum() < 0) b.append('-');
        if (k == 0) return b.append(digits).toString();
        while (digits.length() < k + 1) digits = "0" + digits;
        String ip = digits.substring(0, digits.length() - k);
        String fp = digits.substring(digits.length() - k);
        int end = fp.length();
        while (end > 0 && fp.charAt(end - 1) == '0') end--;
        b.append(ip);
        if (end > 0) b.append('.').append(fp, 0, end);
        return b.toString();
    }

    private static final Pattern NUMBER = Pattern.compile("(-?)(\\d+)(?:\\.(\\d+))?(?:[eE]([+-]?)(\\d+))?");

    /** {@code iscale} text: {@code -?digits(.digits)?([eE][+-]?digits)?} to an exact fraction {@code {p, q}}. */
    static BigInteger[] parseNumber(String text) {
        Matcher m = NUMBER.matcher(text);
        if (!m.matches()) throw new IllegalArgumentException("not a decimal number: \"" + text + "\"");
        String frac = m.group(3) == null ? "" : m.group(3);
        int exp = 0;
        if (m.group(5) != null) {
            String e = m.group(5).replaceFirst("^0+(?=.)", "");
            if (e.length() > 3 || Integer.parseInt(e) > 400) {
                throw new IllegalArgumentException("the exponent of \"" + text + "\" is above 400 in absolute value");
            }
            exp = Integer.parseInt(e);
            if (m.group(4).equals("-")) exp = -exp;
        }
        BigInteger n = new BigInteger(m.group(2) + frac);
        if (m.group(1).equals("-")) n = n.negate();
        long e = (long) exp - frac.length();
        if (e >= 0) return new BigInteger[]{n.multiply(BigInteger.TEN.pow((int) e)), BigInteger.ONE};
        if (-e > Integer.MAX_VALUE / 4) throw new IllegalArgumentException("too many fraction digits: \"" + text + "\"");
        return new BigInteger[]{n, BigInteger.TEN.pow((int) -e)};
    }

    /** An integer scale: {@code factor = num / den} in lowest terms ({@code den > 0}), an integer offset. */
    static final class Exact {
        final BigInteger num;
        final BigInteger den;
        final long offset;

        private Exact(BigInteger num, BigInteger den, long offset) {
            this.num = num;
            this.den = den;
            this.offset = offset;
        }

        /** {@code <factor>[:<offset>]}, the parameters after the transform's name (Exact factors). */
        static Exact parse(String[] params) {
            if (params.length < 1 || params.length > 2) throw new IllegalArgumentException("takes <factor>[:<offset>]");
            String f = params[0];
            BigInteger num, den;
            if (f.matches("-?\\d+/\\d+")) {
                int slash = f.indexOf('/');
                num = new BigInteger(f.substring(0, slash));
                den = new BigInteger(f.substring(slash + 1));
                if (den.signum() == 0) throw new IllegalArgumentException("the denominator of factor " + f + " is 0");
            } else if (f.matches("-?\\d+(?:\\.\\d+)?")) {
                BigDecimal d = new BigDecimal(f);
                if (d.scale() <= 0) {
                    num = d.toBigIntegerExact();
                    den = BigInteger.ONE;
                } else {
                    num = d.unscaledValue();
                    den = BigInteger.TEN.pow(d.scale());
                }
            } else {
                throw new IllegalArgumentException("factor \"" + f + "\" is not [-]digits[.digits] or <num>/<den>");
            }
            if (num.signum() == 0) throw new IllegalArgumentException("factor " + f + " is 0");
            BigInteger g = num.gcd(den);
            num = num.divide(g);
            den = den.divide(g);
            if (num.abs().compareTo(TWO32) > 0 || den.compareTo(TWO32) > 0) {
                throw new IllegalArgumentException("factor " + f + " in lowest terms has a numerator or denominator above 2^32");
            }
            long offset = 0;
            if (params.length == 2) {
                String o = params[1];
                if (!o.matches("-?\\d+")) throw new IllegalArgumentException("offset \"" + o + "\" is not a decimal integer");
                BigInteger ob = new BigInteger(o);
                if (ob.abs().bitLength() > 63 || ob.abs().equals(LONG_MIN.negate())) {
                    throw new IllegalArgumentException("offset " + o + " is not below 2^63 in absolute value");
                }
                offset = ob.longValueExact();
            }
            return new Exact(num, den, offset);
        }

        /** {@code round(v × factor) + offset} of the exact value {@code vp / vq}; must fit signed 64 bits. */
        long decode(BigInteger vp, BigInteger vq) {
            BigInteger r = roundDiv(vp.multiply(num), vq.multiply(den)).add(BigInteger.valueOf(offset));
            if (!fitsLong(r)) throw new IllegalArgumentException("the result " + r + " is outside the signed 64-bit range");
            return r.longValue();
        }

        /** {@code (x − offset) / factor} exactly, as {@code {p, q}} with {@code q > 0}. */
        BigInteger[] quotient(Object x) {
            BigInteger[] v = exactOf(x);
            BigInteger p = v[0].subtract(BigInteger.valueOf(offset).multiply(v[1])).multiply(den);
            BigInteger q = v[1].multiply(num);
            if (q.signum() < 0) {
                p = p.negate();
                q = q.negate();
            }
            return new BigInteger[]{p, q};
        }

        /** {@code round((x − offset) / factor)}. */
        BigInteger encodeRounded(Object x) {
            BigInteger[] pq = quotient(x);
            return roundDiv(pq[0], pq[1]);
        }
    }

    private static final String DECIMAL = "[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?";

    /** A float scale: factor and offset as {@code sscale} reads them, the arithmetic of ruling 1 of 0.5. */
    static final class Floating {
        final boolean fraction;
        final double factor;
        final double num;
        final double den;
        final double offset;

        private Floating(boolean fraction, double factor, double num, double den, double offset) {
            this.fraction = fraction;
            this.factor = factor;
            this.num = num;
            this.den = den;
            this.offset = offset;
        }

        private static double decimal(String s, String what) {
            if (!s.matches(DECIMAL)) throw new IllegalArgumentException(what + " \"" + s + "\" is not a decimal number");
            double d = Double.parseDouble(s);
            if (!Double.isFinite(d)) throw new IllegalArgumentException(what + " \"" + s + "\" is out of range");
            return d;
        }

        /** {@code <factor>[:<offset>]}: a fraction has unsigned {@code num} and {@code den} (ruling 25 of 0.15). */
        static Floating parse(String[] params) {
            if (params.length < 1 || params.length > 2) throw new IllegalArgumentException("takes <factor>[:<offset>]");
            String f = params[0];
            boolean fraction = false;
            double factor = 0, num = 0, den = 0;
            if (f.indexOf('/') >= 0) {
                if (!f.matches("\\d+/\\d+")) {
                    throw new IllegalArgumentException("a fraction factor is <num>/<den> of two unsigned decimal integers, got \"" + f + "\"");
                }
                int slash = f.indexOf('/');
                fraction = true;
                num = Double.parseDouble(f.substring(0, slash));
                den = Double.parseDouble(f.substring(slash + 1));
                if (num == 0 || den == 0) throw new IllegalArgumentException("factor " + f + " has a zero part");
                if (!Double.isFinite(num) || !Double.isFinite(den)) throw new IllegalArgumentException("factor " + f + " is out of range");
            } else {
                factor = decimal(f, "factor");
                if (factor == 0) throw new IllegalArgumentException("factor " + f + " is 0");
            }
            double offset = params.length == 2 ? decimal(params[1], "offset") : 0.0;
            return new Floating(fraction, factor, num, den, offset);
        }

        /** {@code v × factor + offset} (or {@code v × num / den + offset}), in doubles and in that order. */
        double apply(double v) {
            double d = fraction ? v * num / den : v * factor;
            return d + offset;
        }

        /** {@code (x − offset) / factor} (or {@code (x − offset) × den / num}), in doubles. */
        double invert(double x) {
            return fraction ? (x - offset) * den / num : (x - offset) / factor;
        }
    }
}
