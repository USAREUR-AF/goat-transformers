package goat.transformers;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * A sequence of characters, each from a set the pack declares (engine-spec 0.46): the transforms {@code code:<sets>},
 * {@code codestr:<sets>} and {@code codenum:<sets>}. Methods throw IllegalArgumentException with a reason; the codec
 * turns it into the error kind.
 */
final class CodeSeq {
    /** One {@code charset}: its characters in code order and, on {@code bits}, the bits per character. */
    static final class CharSet {
        final String chars;
        final int width;

        CharSet(String chars, int width) {
            this.chars = chars;
            this.width = width;
        }
    }

    /** One {@code charset} line as read: checked once the file is read (rulings 7 to 9 and 15 to 17). */
    static final class Dir {
        final List<String> args;
        final String where;
        final boolean afterKind;

        Dir(List<String> args, String where, boolean afterKind) {
            this.args = args;
            this.where = where;
            this.afterKind = afterKind;
        }
    }

    private final boolean number;
    private final CharSet[] sets;
    /** The product of the sizes as an unsigned 64-bit number: at most 2^63 for {@code codenum}, unused otherwise. */
    private final long product;
    private final int bits;

    private CodeSeq(boolean number, CharSet[] sets, long product, int bits) {
        this.number = number;
        this.sets = sets;
        this.product = product;
        this.bits = bits;
    }

    /** True for the text before the first colon of one of the three transforms. */
    static boolean isHead(String head) { return head.equals("code") || head.equals("codestr") || head.equals("codenum"); }

    private static GtException bad(String format, String locator, String detail) {
        return new GtException(GtException.Code.BAD_DIRECTIVE, format, locator, detail);
    }

    /** The sets of a pack from its {@code charset} lines. {@code onBits}: widths count (ruling 14). */
    static Map<String, CharSet> charsets(List<Dir> dirs, boolean onBits, String format) {
        Map<String, CharSet> out = new HashMap<>();
        for (Dir d : dirs) {
            String name = d.args.get(0), chars = d.args.get(1);
            if (d.afterKind) throw bad(format, null, d.where + ": charset after the first kind line");
            if (!name.matches("[A-Za-z0-9_-]+")) {
                throw bad(format, null, d.where + ": a charset name is letters, digits, _ and -, got \"" + name + "\"");
            }
            if (chars.isEmpty()) throw bad(format, null, d.where + ": a charset has at least one character");
            Set<Character> seen = new HashSet<>();
            for (int i = 0; i < chars.length(); i++) {
                char c = chars.charAt(i);
                if (c < 0x21 || c > 0x7e) throw bad(format, null, d.where + ": charset " + name + " holds a character outside 0x21 to 0x7E");
                if (!seen.add(c)) throw bad(format, null, d.where + ": charset " + name + " holds " + c + " twice");
            }
            int least = Math.max(1, 32 - Integer.numberOfLeadingZeros(chars.length() - 1));
            int width = least;
            if (onBits && d.args.size() == 3) {
                Long w = Transform.parseUnsigned(d.args.get(2), 31);
                if (w == null || w < least || w > 8) {
                    throw bad(format, null, d.where + ": the width of charset " + name + " is " + least + " to 8 in plain digits, got \"" + d.args.get(2) + "\"");
                }
                width = (int) (long) w;
            }
            if (out.put(name, new CharSet(chars, width)) != null) {
                throw bad(format, null, d.where + ": charset " + name + " is declared twice");
            }
        }
        return out;
    }

    /** The transform {@code name} with the pack's sets; every error of its list is {@code bad-directive} (ruling 15). */
    static CodeSeq parse(String name, Map<String, CharSet> charsets, String format, String locator, String where) {
        int colon = name.indexOf(':');
        if (colon < 0 || colon == name.length() - 1) throw bad(format, locator, where + ": " + name + " names no character set");
        String[] names = name.substring(colon + 1).split(",", -1);
        if (names.length > 16) throw bad(format, locator, where + ": " + name + " has " + names.length + " positions, more than 16");
        CharSet[] sets = new CharSet[names.length];
        int bits = 0;
        java.math.BigInteger product = java.math.BigInteger.ONE;
        for (int i = 0; i < names.length; i++) {
            sets[i] = charsets.get(names[i]);
            if (sets[i] == null) throw bad(format, locator, where + ": " + name + ": no charset line declares \"" + names[i] + "\"");
            bits += sets[i].width;
            product = product.multiply(java.math.BigInteger.valueOf(sets[i].chars.length()));
        }
        boolean number = name.startsWith("codenum:");
        if (number && product.compareTo(java.math.BigInteger.ONE.shiftLeft(63)) > 0) {
            throw bad(format, locator, where + ": " + name + ": the product of the sizes is above 2^63");
        }
        return new CodeSeq(number, sets, product.longValue(), bits);
    }

    String yields() { return number ? "int" : "string"; }

    /** Null when a {@code bits} field of {@code len} bits may carry the sequence, else the reason. */
    String checkLen(int len) {
        if (bits > 64) return "the widths of the positions sum to " + bits + " bits, more than 64";
        return len == bits ? null : "the widths of the positions sum to " + bits + " bits, the field has " + len;
    }

    /** True when some position's set holds {@code c}. */
    boolean uses(char c) {
        for (CharSet s : sets) if (s.chars.indexOf(c) >= 0) return true;
        return false;
    }

    // ---- codes to and from the field's raw bits, the text and the model value ----

    private int[] codesOfRaw(long raw) {
        int[] c = new int[sets.length];
        for (int i = sets.length - 1; i >= 0; i--) {
            CharSet s = sets[i];
            c[i] = (int) (raw & ((1L << s.width) - 1));
            raw >>>= s.width;
            if (c[i] >= s.chars.length()) {
                throw new IllegalArgumentException("code " + c[i] + " at position " + i + " is not in its set of " + s.chars.length());
            }
        }
        return c;
    }

    private long rawOfCodes(int[] c) {
        long raw = 0;
        for (int i = 0; i < c.length; i++) raw = (raw << sets[i].width) | c[i];
        return raw;
    }

    private int[] codesOfText(String t) {
        if (t.length() != sets.length) {
            throw new IllegalArgumentException("needs exactly " + sets.length + " characters, got \"" + t + "\"");
        }
        int[] c = new int[sets.length];
        for (int i = 0; i < c.length; i++) {
            c[i] = sets[i].chars.indexOf(t.charAt(i));
            if (c[i] < 0) throw new IllegalArgumentException("character " + i + " of \"" + t + "\" is not in its set");
        }
        return c;
    }

    private String textOfCodes(int[] c) {
        StringBuilder b = new StringBuilder(c.length);
        for (int i = 0; i < c.length; i++) b.append(sets[i].chars.charAt(c[i]));
        return b.toString();
    }

    private Object valueOfCodes(int[] c) {
        if (!number) return textOfCodes(c);
        long v = 0;
        for (int i = 0; i < c.length; i++) v = v * sets[i].chars.length() + c[i];
        return v;
    }

    private int[] codesOfValue(Object value) {
        if (!number) return codesOfText(String.valueOf(value));
        long x = Transform.asLong(value);
        if (x < 0 || Long.compareUnsigned(x, product) >= 0) {
            throw new IllegalArgumentException("value " + x + " is outside 0 to " + Long.toUnsignedString(product - 1));
        }
        int[] c = new int[sets.length];
        for (int i = c.length - 1; i >= 0; i--) {
            int size = sets[i].chars.length();
            c[i] = (int) (x % size);
            x /= size;
        }
        return c;
    }

    Object decodeRaw(long raw) { return valueOfCodes(codesOfRaw(raw)); }

    long encodeRaw(Object value) { return rawOfCodes(codesOfValue(value)); }

    Object decodeText(String text) { return valueOfCodes(codesOfText(text)); }

    String encodeText(Object value) { return textOfCodes(codesOfValue(value)); }
}
