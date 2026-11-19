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

    private Sentinels(long[] nums, String[] texts, Object[] json) {
        this.nums = nums;
        this.texts = texts;
        this.json = json;
    }

    boolean matches(long raw) {
        for (long n : nums) if (n == raw) return true;
        return false;
    }

    boolean matches(String raw) {
        if (raw == null) return false;
        for (String t : texts) if (t.equals(raw)) return true;
        return false;
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
        if (width > 64) throw bad(format, locator, where, "a field of " + width + " bits is longer than 64 bits");
        List<String> vs = values(arg, format, locator, where);
        long[] nums = new long[vs.size()];
        for (int i = 0; i < nums.length; i++) {
            String v = vs.get(i);
            if (!v.matches("\\d+")) {
                throw bad(format, locator, where, "a value here is an unsigned decimal integer, got \"" + v + "\"");
            }
            long n;
            try {
                n = Long.parseUnsignedLong(v);
            } catch (NumberFormatException ex) {
                throw bad(format, locator, where, "value " + v + " does not fit 64 bits");
            }
            if (width < 64 && Long.compareUnsigned(n, BitsTransform.mask(width)) > 0) {
                throw bad(format, locator, where, "value " + v + " does not fit " + width + " bits");
            }
            nums[i] = n;
        }
        return new Sentinels(nums, new String[0], new Object[0]);
    }

    /** {@code pstring} ({@code stripEq} false: {@code =} is part of the text) and {@code xml} ({@code stripEq} true). */
    static Sentinels texts(String arg, boolean stripEq, String format, String locator, String where) {
        List<String> vs = values(arg, format, locator, where);
        String[] texts = new String[vs.size()];
        for (int i = 0; i < texts.length; i++) {
            String v = vs.get(i);
            if (stripEq && v.startsWith("=")) {
                v = v.substring(1);
                if (v.isEmpty()) throw bad(format, locator, where, "a value is empty after its = is stripped; write \"\" for the empty text");
            }
            texts[i] = v;
        }
        return new Sentinels(new long[0], texts, new Object[0]);
    }

    /**
     * {@code json} and {@code geojson}: JSON number text is held as its canonical text and written as a number,
     * {@code true} and {@code false} as booleans, anything else (and anything after {@code =}) as a string;
     * {@code null} is not a sentinel. {@code bool}: the field's transform is {@code bool}.
     */
    static Sentinels json(String arg, boolean bool, String format, String locator, String where) {
        List<String> vs = values(arg, format, locator, where);
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
        return new Sentinels(new long[0], texts, json);
    }
}
