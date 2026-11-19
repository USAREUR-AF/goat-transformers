package goat.transformers;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;

/**
 * A {@code tlv}-wire transform (0.13): {@code uint}, {@code twos}, {@code uscale}, {@code sscale}, {@code f32} and
 * {@code f64} read a value of 1 to 8 bytes (4 or 8 for the floats) at its own length and write {@code n} bytes;
 * {@code utf8} and {@code hex} turn the value's bytes into text and back.
 */
final class TlvTransform {
    enum Kind { UINT, TWOS, USCALE, SSCALE, F32, F64, UTF8, HEX }

    final Kind kind;
    final String name;
    /** uscale, sscale, f32 and f64: the bits transform whose arithmetic the tlv transform shares. */
    private final BitsTransform bits;

    private TlvTransform(Kind kind, String name, BitsTransform bits) {
        this.kind = kind;
        this.name = name;
        this.bits = bits;
    }

    /** True for the transforms that are valid on the tlv wire only. */
    static boolean isTlvOnlyName(String n) { return n.equals("utf8") || n.equals("hex"); }

    /**
     * The tlv transform named {@code name}, or null when the name is not in the table of 0.13. Parameters that do
     * not parse are {@code bad-directive} (ruling 8 of 0.13).
     */
    static TlvTransform parse(String name, String format, String where) {
        try {
            return parseName(name, format, where);
        } catch (GtException ex) {
            throw new GtException(GtException.Code.BAD_DIRECTIVE, format, null, where + ": transform \"" + name
                    + "\" on wire tlv: its parameters do not parse");
        }
    }

    private static TlvTransform parseName(String name, String format, String where) {
        int c = name.indexOf(':');
        String head = c < 0 ? name : name.substring(0, c);
        switch (head) {
            case "uscale":
                return new TlvTransform(Kind.USCALE, name, BitsTransform.parse(name, format, where));
            case "sscale":
                return new TlvTransform(Kind.SSCALE, name, BitsTransform.parse(name, format, where));
            default:
                break;
        }
        if (c >= 0) return null;
        switch (name) {
            case "uint": return new TlvTransform(Kind.UINT, name, null);
            case "twos": return new TlvTransform(Kind.TWOS, name, null);
            case "f32": return new TlvTransform(Kind.F32, name, BitsTransform.parse(name, format, where));
            case "f64": return new TlvTransform(Kind.F64, name, BitsTransform.parse(name, format, where));
            case "utf8": return new TlvTransform(Kind.UTF8, name, null);
            case "hex": return new TlvTransform(Kind.HEX, name, null);
            default: return null;
        }
    }

    String yields() {
        switch (kind) {
            case UINT:
            case TWOS: return "int";
            case UTF8:
            case HEX: return "string";
            default: return "float";
        }
    }

    /** True for the transforms that yield text: an empty value is then the empty string, not absent. */
    boolean text() { return kind == Kind.UTF8 || kind == Kind.HEX; }

    /** Null when {@code size} (0 for none) is allowed with this transform, else the reason. */
    String checkSize(int size) {
        switch (kind) {
            case UINT:
            case TWOS:
            case USCALE:
            case SSCALE:
                return size == 0 ? name + " needs a size :<n> from 1 to 8" : null;
            case F32: return size == 0 || size == 4 ? null : "f32 takes no size or :4, got :" + size;
            case F64: return size == 0 || size == 8 ? null : "f64 takes no size or :8, got :" + size;
            default: return size == 0 ? null : name + " takes no size, got :" + size;
        }
    }

    /** The value bytes as an unsigned big-endian integer (a 64-bit pattern). The caller has checked the length. */
    static long unsigned(byte[] b, int from, int to) {
        long v = 0;
        for (int i = from; i < to; i++) v = (v << 8) | (b[i] & 0xff);
        return v;
    }

    /** A non-empty value to its model value. Throws IllegalArgumentException with the reason. */
    Object decode(byte[] b, int from, int to) {
        int len = to - from;
        switch (kind) {
            case UINT:
            case TWOS:
            case USCALE:
            case SSCALE: {
                if (len > 8) throw new IllegalArgumentException(name + " value of " + len + " bytes is longer than 8");
                long raw = unsigned(b, from, to);
                if (kind == Kind.UINT) return raw;                     // 8 bytes: the bit pattern (ruling 2 of 0.5)
                if (kind == Kind.TWOS) return BitsTransform.twosValue(raw, 8 * len);
                return bits.decode(raw, 8 * len);                      // uscale unsigned, sscale signed, at its length
            }
            case F32:
                if (len != 4) throw new IllegalArgumentException("f32 takes exactly 4 bytes, got " + len);
                return bits.decode(unsigned(b, from, to), 32);
            case F64:
                if (len != 8) throw new IllegalArgumentException("f64 takes exactly 8 bytes, got " + len);
                return bits.decode(unsigned(b, from, to), 64);
            case UTF8:
                try {
                    return StandardCharsets.UTF_8.newDecoder()
                            .onMalformedInput(CodingErrorAction.REPORT)
                            .onUnmappableCharacter(CodingErrorAction.REPORT)
                            .decode(ByteBuffer.wrap(b, from, len)).toString();
                } catch (CharacterCodingException ex) {
                    throw new IllegalArgumentException("the value is not valid UTF-8");
                }
            default:
                return Codec.toHex(java.util.Arrays.copyOfRange(b, from, to));
        }
    }

    /** {@code v} as {@code n} big-endian bytes (its low {@code 8n} bits). */
    static byte[] bigEndian(long v, int n) {
        byte[] out = new byte[n];
        for (int i = n - 1; i >= 0; i--) {
            out[i] = (byte) v;
            v >>>= 8;
        }
        return out;
    }

    /** A model value to the value bytes, {@code size} bytes for an integer. Throws IllegalArgumentException. */
    byte[] encode(Object value, int size) {
        switch (kind) {
            case UINT: {
                long v = Transform.asLong(value);
                // an 8-byte uint carries any 64-bit pattern (ruling 2 of 0.5); a shorter one 0 to 2^(8n)-1 (ruling 3)
                if (size < 8 && (v < 0 || v >= (1L << (8 * size)))) {
                    throw new IllegalArgumentException("value " + v + " does not fit uint of " + size + " bytes");
                }
                return bigEndian(v, size);
            }
            case TWOS: {
                long v = Transform.asLong(value);
                if (size < 8 && (v < -(1L << (8 * size - 1)) || v >= (1L << (8 * size - 1)))) {
                    throw new IllegalArgumentException("value " + v + " does not fit twos of " + size + " bytes");
                }
                return bigEndian(v, size);
            }
            case USCALE:
            case SSCALE:
                return bigEndian(bits.encode(value, 8 * size), size);
            case F32:
                return bigEndian(bits.encode(value, 32), 4);
            case F64:
                return bigEndian(bits.encode(value, 64), 8);
            case UTF8:
                return text(value).getBytes(StandardCharsets.UTF_8);
            default: {
                String s = text(value);
                if (s.length() % 2 != 0) throw new IllegalArgumentException("hex text has an odd number of digits");
                byte[] out = new byte[s.length() / 2];
                for (int i = 0; i < out.length; i++) {
                    int hi = Character.digit(s.charAt(2 * i), 16), lo = Character.digit(s.charAt(2 * i + 1), 16);
                    if (hi < 0 || lo < 0 || s.charAt(2 * i) > 0x7f || s.charAt(2 * i + 1) > 0x7f) {
                        throw new IllegalArgumentException("hex text has a character that is not a hex digit");
                    }
                    out[i] = (byte) ((hi << 4) | lo);
                }
                return out;
            }
        }
    }

    private static String text(Object v) {
        return v instanceof Double ? Transform.formatDouble((Double) v) : String.valueOf(v);
    }
}
