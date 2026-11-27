package goat.transformers;

import java.util.ArrayList;
import java.util.List;

/**
 * The values of a field's {@code absent} option (engine-spec 0.9): the raw wire values that mean "no value". A
 * sentinel is compared with the raw value before {@code via}, {@code typemap} and the transform; on encode the
 * first one is written for a key the entity lacks.
 */
final class Sentinels {
    /** {@code bits} and the integer forms of {@code protobuf}: the unsigned values, as 64-bit patterns. */
    final long[] nums;
    /** Text wires and {@code pstring}: the texts compared (for {@code json}, the canonical text of a number). */
    final String[] texts;
    /** {@code json} and {@code geojson}: the value each writes, a {@link Json.Num}, a Boolean or a String. */
    final Object[] json;

    /**
     * The range sentinels (engine-spec 0.56), in the order written: {@code >=} when true, {@code <=} when false.
     * {@code bits} and the integer forms of {@code protobuf} hold their bound in {@link #rangeNums} (unsigned), the
     * text wires in {@link #rangeVals} (the nearest double of the number text).
     */
    private boolean[] rangeAtLeast = new boolean[0];
    private long[] rangeNums = new long[0];
    private double[] rangeVals = new double[0];

    private Sentinels(long[] nums, String[] texts, Object[] json) {
        this.nums = nums;
        this.texts = texts;
        this.json = json;
    }

    boolean matches(long raw) {
        for (long n : nums) if (n == raw) return true;
        for (int i = 0; i < rangeNums.length; i++) {
            int c = Long.compareUnsigned(raw, rangeNums[i]);
            if (rangeAtLeast[i] ? c >= 0 : c <= 0) return true;
        }
        return false;
    }

    boolean matches(String raw) {
        if (raw == null) return false;
        for (String t : texts) if (t.equals(raw)) return true;
        if (rangeVals.length > 0 && Transform.isNumText(raw)) {
            // the raw text read as number text (2b of 0.11) and compared by its nearest double (engine-spec 0.56)
            double d = Transform.parseFloat(raw);
            for (int i = 0; i < rangeVals.length; i++) {
                if (rangeAtLeast[i] ? d >= rangeVals[i] : d <= rangeVals[i]) return true;
            }
        }
        return false;
    }

    /** True when the option holds an exact value: encode of an absent key writes the first (engine-spec 0.56). */
    boolean writes() { return nums.length > 0 || texts.length > 0; }

    /** True when the option holds a range sentinel, {@code >=} or {@code <=} (engine-spec 0.56). */
    boolean hasRange() { return rangeAtLeast.length > 0; }

    /** True when {@code v} begins with {@code >=} or {@code <=}: a range sentinel (engine-spec 0.56). */
    static boolean isRange(String v) { return v.startsWith(">=") || v.startsWith("<="); }

    private Sentinels withRanges(List<Boolean> atLeast, long[] ns, double[] ds) {
        rangeAtLeast = new boolean[atLeast.size()];
        for (int i = 0; i < rangeAtLeast.length; i++) rangeAtLeast[i] = atLeast.get(i);
        rangeNums = ns;
        rangeVals = ds;
        return this;
    }

    /** The bound of a text-wire range sentinel: number text (2b of 0.11) with a finite nearest double. */
    private static double textBound(String v, String format, String locator, String where) {
        String n = v.substring(2);
        if (!Transform.isNumText(n)) {
            throw bad(format, locator, where, "the bound of a range sentinel here is number text, got \"" + v + "\"");
        }
        return Transform.parseFloat(n);
    }

    long firstNum() { return nums[0]; }

    String firstText() { return texts[0]; }

    Object firstJson() { return json[0]; }

    /**
     * The raw text a {@code json} or {@code geojson} value is compared as: a string's text, a number's canonical text
     * through a double (ruling 19 of 0.9), {@code true} or {@code false}; null for anything else (never a sentinel).
     */
    static String jsonRaw(Object v) {
        if (v instanceof String) return (String) v;
        if (v instanceof Boolean) return v.toString();
        if (v instanceof Json.Num) {
            try {
                double d = Double.parseDouble(((Json.Num) v).text);
                return Double.isFinite(d) ? Transform.formatDouble(d) : null;
            } catch (NumberFormatException ex) {
                return null;
            }
        }
        return null;
    }

    private static GtException bad(String format, String locator, String where, String why) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, where + ": absent: " + why);
    }

    /**
     * The values of the argument: the quoted empty token {@code ""} is the one value "the empty text"; otherwise the
     * argument is split on commas and no value may be empty or hold a double quote (ruling 11 of 0.9).
     */
    private static List<String> values(String arg, String format, String locator, String where) {
        List<String> out = new ArrayList<>();
        if (arg.isEmpty()) {
            out.add("");
            return out;
        }
        if (arg.indexOf('"') >= 0) throw bad(format, locator, where, "a value cannot hold a double quote: " + arg);
        for (String v : arg.split(",", -1)) {
            if (v.isEmpty()) throw bad(format, locator, where, "an empty value in the list " + arg);
            out.add(v);
        }
        return out;
    }

    /** {@code bits} ({@code width} = the field's length) and the integer forms of {@code protobuf}. */
    static Sentinels integers(String arg, int width, String format, String locator, String where) {
        return integers(arg, width, true, format, locator, where);
    }

    /**
     * As above; {@code ranges} false refuses a range sentinel ({@code pdouble} and {@code pfloat}, engine-spec 0.56).
     */
    static Sentinels integers(String arg, int width, boolean ranges, String format, String locator, String where) {
        if (width > 64) throw bad(format, locator, where, "a field of " + width + " bits is longer than 64 bits");
        List<String> all = values(arg, format, locator, where);
        List<String> vs = new ArrayList<>();
        List<Boolean> atLeast = new ArrayList<>();
        List<String> bounds = new ArrayList<>();
        for (String v : all) {
            if (isRange(v)) {
                if (!ranges) throw bad(format, locator, where, "a range sentinel is not allowed here; use exact values: " + v);
                atLeast.add(v.startsWith(">="));
                bounds.add(v.substring(2));
            } else {
                vs.add(v);
            }
        }
        long[] rangeNums = new long[bounds.size()];
        for (int i = 0; i < rangeNums.length; i++) rangeNums[i] = unsigned(bounds.get(i), width, format, locator, where);
        long[] nums = new long[vs.size()];
        for (int i = 0; i < nums.length; i++) nums[i] = unsigned(vs.get(i), width, format, locator, where);
        return new Sentinels(nums, new String[0], new Object[0]).withRanges(atLeast, rangeNums, new double[0]);
    }

    /** One unsigned decimal integer below {@code 2^width} (2c of 0.11). */
    private static long unsigned(String v, int width, String format, String locator, String where) {
        if (!v.matches("\\d+")) {
            throw bad(format, locator, where, "a value here is an unsigned decimal integer, got \"" + v + "\"");
        }
        Long parsed = Transform.parseUnsigned(v, 64);
        if (parsed == null) throw bad(format, locator, where, "value " + v + " does not fit 64 bits");
        long n = parsed;
        if (width < 64 && Long.compareUnsigned(n, BitsTransform.mask(width)) > 0) {
            throw bad(format, locator, where, "value " + v + " does not fit " + width + " bits");
        }
        return n;
    }

    /** {@code pstring} ({@code stripEq} false: {@code =} is part of the text) and {@code xml} ({@code stripEq} true). */
    static Sentinels texts(String arg, boolean stripEq, String format, String locator, String where) {
        List<String> vs = new ArrayList<>();
        List<Boolean> atLeast = new ArrayList<>();
        List<Double> bounds = new ArrayList<>();
        // the prefix is looked for before anything is stripped: `=>=5` is the exact text >=5 (engine-spec 0.56)
        for (String v : values(arg, format, locator, where)) {
            if (isRange(v)) {
                atLeast.add(v.startsWith(">="));
                bounds.add(textBound(v, format, locator, where));
            } else {
                vs.add(v);
            }
        }
        String[] texts = new String[vs.size()];
        for (int i = 0; i < texts.length; i++) {
            String v = vs.get(i);
            if (stripEq && v.startsWith("=")) {
                v = v.substring(1);
                if (v.isEmpty()) throw bad(format, locator, where, "a value is empty after its = is stripped; write \"\" for the empty text");
            }
            texts[i] = v;
        }
        return new Sentinels(new long[0], texts, new Object[0]).withRanges(atLeast, new long[0], doubles(bounds));
    }

    private static double[] doubles(List<Double> ds) {
        double[] out = new double[ds.size()];
        for (int i = 0; i < out.length; i++) out[i] = ds.get(i);
        return out;
    }

    /**
     * {@code json} and {@code geojson}: JSON number text is held as its canonical text and written as a number,
     * {@code true} and {@code false} as booleans, anything else (and anything after {@code =}) as a string;
     * {@code null} is not a sentinel. {@code bool}: the field's transform is {@code bool}.
     */
    static Sentinels json(String arg, boolean bool, String format, String locator, String where) {
        List<String> vs = new ArrayList<>();
        List<Boolean> atLeast = new ArrayList<>();
        List<Double> bounds = new ArrayList<>();
        for (String v : values(arg, format, locator, where)) {
            if (isRange(v)) {
                if (bool) throw bad(format, locator, where, "a bool field takes true or false, not a range: " + v);
                atLeast.add(v.startsWith(">="));
                bounds.add(textBound(v, format, locator, where));
            } else {
                vs.add(v);
            }
        }
        String[] texts = new String[vs.size()];
        Object[] json = new Object[vs.size()];
        for (int i = 0; i < texts.length; i++) {
            String v = vs.get(i);
            Object jv;
            if (v.isEmpty()) {
                jv = "";
            } else if (v.startsWith("=")) {
                v = v.substring(1);
                if (v.isEmpty()) throw bad(format, locator, where, "a value is empty after its = is stripped; write \"\" for the empty text");
                jv = v;
            } else if (v.equals("null")) {
                throw bad(format, locator, where, "null is not a sentinel; write =null for the text");
            } else if (v.equals("true") || v.equals("false")) {
                jv = Boolean.valueOf(v);
            } else if (Json.isNumber(v)) {
                double d = Double.parseDouble(v);
                if (!Double.isFinite(d)) throw bad(format, locator, where, "number " + v + " does not fit a finite double");
                v = Transform.formatDouble(d);
                jv = new Json.Num(v);
            } else {
                jv = v;
            }
            if (bool && !(jv instanceof Boolean)) {
                throw bad(format, locator, where, "a bool field takes true or false, got \"" + vs.get(i) + "\"");
            }
            texts[i] = v;
            json[i] = jv;
        }
        return new Sentinels(new long[0], texts, json).withRanges(atLeast, new long[0], doubles(bounds));
    }
}
