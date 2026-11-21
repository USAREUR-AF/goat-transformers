package goat.transformers;

import java.math.BigInteger;
import java.util.List;

/**
 * The field options of engine-spec 0.56, output conditions: {@code null}, {@code implicit} and
 * {@code range <min> <max> [wrap]}. {@link #take} reads their form as the line is read (ruling 5b of 0.11, step 9);
 * the checks that need the wire, the key's type or the group are made after the file.
 */
final class OutputOptions {
    boolean nul;
    boolean implicit;
    boolean wrap;
    /** The two arguments of {@code range} as written, or null. */
    String min;
    String max;
    /** The index of the token directly after {@code range <min> <max>}: the only place of {@code wrap}. */
    private int rangeEnd = -1;

    /** True when {@code o} is the name of an option of 0.56. */
    static boolean isName(String o) {
        return o.equals("null") || o.equals("implicit") || o.equals("range") || o.equals("wrap");
    }

    /**
     * Read the option at {@code args[i]}, one of {@link #isName}; returns the index of its last token. Every failure
     * of form is {@code bad-directive}.
     */
    int take(List<String> args, int i, String format, String locator, String where) {
        String o = args.get(i);
        switch (o) {
            case "null":
                if (nul) throw bad(format, locator, where, "null given twice");
                nul = true;
                return i;
            case "implicit":
                if (implicit) throw bad(format, locator, where, "implicit given twice");
                implicit = true;
                return i;
            case "range":
                if (min != null) throw bad(format, locator, where, "range given twice");
                if (i + 2 >= args.size()) throw bad(format, locator, where, "range takes <min> <max>");
                min = args.get(i + 1);
                max = args.get(i + 2);
                for (String a : new String[]{min, max}) {
                    if (!Transform.isNumText(a)) {
                        throw bad(format, locator, where, "a bound of range is number text, got \"" + a + "\"");
                    }
                }
                rangeEnd = i + 3;
                return i + 2;
            case "wrap":
                if (wrap) throw bad(format, locator, where, "wrap given twice");
                if (i != rangeEnd) throw bad(format, locator, where, "wrap is the argument directly after range <min> <max>");
                wrap = true;
                return i;
            default:
                throw new IllegalStateException(o);
        }
    }

    static GtException bad(String format, String locator, String where, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, where + ": " + why);
    }

    /** A {@code range} bound and wrap, read as the key's type once it is known. */
    static final class Range {
        final boolean isInt;
        final boolean wrap;
        final BigInteger lo, hi;
        final double loF, hiF;

        private Range(boolean isInt, boolean wrap, BigInteger lo, BigInteger hi, double loF, double hiF) {
            this.isInt = isInt;
            this.wrap = wrap;
            this.lo = lo;
            this.hi = hi;
            this.loF = loF;
            this.hiF = hiF;
        }

        private static final BigInteger LONG_MIN = BigInteger.valueOf(Long.MIN_VALUE);
        private static final BigInteger LONG_MAX = BigInteger.valueOf(Long.MAX_VALUE);

        /** The range of a field whose key is {@code keyType}; {@code bad-directive} when the arguments do not fit it. */
        static Range of(String min, String max, boolean wrap, String keyType, String format, String locator, String where) {
            if (keyType.equals("int")) {
                BigInteger[] b = new BigInteger[2];
                String[] t = {min, max};
                for (int k = 0; k < 2; k++) {
                    if (!Transform.INT_TEXT.matcher(t[k]).matches()) {
                        throw bad(format, locator, where, "a bound of range on an int key is a decimal integer, got \"" + t[k] + "\"");
                    }
                    b[k] = new BigInteger(t[k]);
                    if (b[k].compareTo(LONG_MIN) < 0 || b[k].compareTo(LONG_MAX) > 0) {
                        throw bad(format, locator, where, "a bound of range on an int key lies outside a signed 64-bit integer: " + t[k]);
                    }
                }
                if (b[0].compareTo(b[1]) >= 0) throw bad(format, locator, where, "range: <min> " + min + " is not less than <max> " + max);
                return new Range(true, wrap, b[0], b[1], 0, 0);
            }
            if (keyType.equals("float")) {
                double lo = Transform.parseFloat(min), hi = Transform.parseFloat(max);
                if (!(lo < hi)) throw bad(format, locator, where, "range: <min> " + min + " is not less than <max> " + max);
                return new Range(false, wrap, null, null, lo, hi);
            }
            throw bad(format, locator, where, "range is for a field whose key is int or float, not " + keyType);
        }

        /**
         * The model value checked, or wrapped, before {@code via} and the transform. A value that is not a number of
         * the key's type passes unchanged: the transform refuses it.
         */
        Object apply(Object v) {
            if (isInt) {
                Long x = asLong(v);
                if (x == null) return v;
                BigInteger bx = BigInteger.valueOf(x);
                if (bx.compareTo(lo) >= 0 && (wrap ? bx.compareTo(hi) < 0 : bx.compareTo(hi) <= 0)) return x;
                if (!wrap) throw new IllegalArgumentException("value " + x + " is outside range [" + lo + ", " + hi + "]");
                // x - (max - min) * floor((x - min) / (max - min)), exactly (ruling 7 of 0.56)
                return bx.subtract(lo).mod(hi.subtract(lo)).add(lo).longValue();
            }
            if (!(v instanceof Number)) return v;
            double x = ((Number) v).doubleValue();
            if (Double.isNaN(x)) return v;
            if (x >= loF && (wrap ? x < hiF : x <= hiF)) return v;
            if (!wrap) {
                throw new IllegalArgumentException("value " + Transform.formatOrText(x) + " is outside range ["
                        + Transform.formatOrText(loF) + ", " + Transform.formatOrText(hiF) + "]");
            }
            if (Double.isInfinite(x)) throw new IllegalArgumentException("value " + x + " cannot be wrapped");
            double span = hiF - loF;
            double r = x - span * Math.floor((x - loF) / span);
            if (r >= hiF || r < loF) r = loF;
            return r;
        }

        private static Long asLong(Object v) {
            if (v instanceof Long || v instanceof Integer) return ((Number) v).longValue();
            if (v instanceof Double) {
                try {
                    return Transform.asLong(v);
                } catch (IllegalArgumentException ex) {
                    return null;
                }
            }
            return null;
        }
    }
}
