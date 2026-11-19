package goat.transformers;

import java.math.BigInteger;

/**
 * The text-wire scales of engine-spec 0.15, on {@code xml}, {@code json} and {@code geojson}:
 * {@code scale:<factor>[:<offset>]} yields a float through the arithmetic of ruling 1 of 0.5;
 * {@code iscale:<factor>[:<offset>]} yields an integer through exact arithmetic on the number's text.
 */
final class TextScale {
    private final String name;
    private final Scales.Exact exact;       // iscale
    private final Scales.Floating floating; // scale

    private TextScale(String name, Scales.Exact exact, Scales.Floating floating) {
        this.name = name;
        this.exact = exact;
        this.floating = floating;
    }

    static boolean isName(String head) { return head.equals("scale") || head.equals("iscale"); }

    static TextScale parse(String name, String format, String locator, String where) {
        String[] p = name.split(":", -1);
        String[] params = java.util.Arrays.copyOfRange(p, 1, p.length);
        try {
            if (p[0].equals("iscale")) return new TextScale(name, Scales.Exact.parse(params), null);
            return new TextScale(name, null, Scales.Floating.parse(params));
        } catch (IllegalArgumentException ex) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, where + ": " + name + ": " + ex.getMessage());
        }
    }

    boolean isExact() { return exact != null; }

    String wireName() { return name; }

    String yields() { return exact != null ? "int" : "float"; }

    /**
     * The number's text to the model value. {@code iscale} reads the text exactly as given (no trimming);
     * {@code scale} reads it as {@code float} does.
     */
    Object decode(String text) {
        if (exact != null) {
            BigInteger[] r = Scales.parseNumber(text);
            return exact.decode(r[0], r[1]);
        }
        double d = floating.apply(Transform.parseFloat(text));
        if (!Double.isFinite(d)) throw new IllegalArgumentException("the result is not finite");
        return d;
    }

    /** The model value to the number's text. */
    String encode(Object value) {
        if (exact != null) {
            BigInteger[] q = exact.quotient(value);
            return Scales.plain(q[0], q[1]);
        }
        double d = floating.invert(Transform.asDouble(value));
        if (!Double.isFinite(d)) throw new IllegalArgumentException("the quotient is not finite");
        return Transform.formatDouble(d);
    }
}
