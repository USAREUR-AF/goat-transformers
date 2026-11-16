package goat.transformers;

import java.nio.charset.StandardCharsets;

/**
 * A protobuf-wire transform. Each one fixes the field's protobuf wire type: {@code pstring} is wire type 2
 * (length-delimited), {@code pvarint} and {@code psint} are 0 (varint), {@code pdouble} is 1 (fixed64) and
 * {@code pfloat} is 5 (fixed32). A protobuf transform is valid only on a protobuf wire; the text transforms in
 * {@link Transform} and the bits transforms in {@link BitsTransform} are not.
 */
public final class PbTransform {
    enum Kind { PSTRING, PVARINT, PSINT, PDOUBLE, PFLOAT }

    private final Kind kind;
    private final String name;
    private final int wireType;

    private PbTransform(Kind kind, String name, int wireType) {
        this.kind = kind;
        this.name = name;
        this.wireType = wireType;
    }

    public String wireName() { return name; }

    /** The model type this transform yields: {@code string}, {@code float} or {@code int}. */
    public String yields() {
        switch (kind) {
            case PSTRING: return "string";
            case PDOUBLE:
            case PFLOAT:  return "float";
            default:      return "int";
        }
    }

    /** The protobuf wire type this transform requires: 0 varint, 1 fixed64, 2 length-delimited, 5 fixed32. */
    int wireType() { return wireType; }

    /** True when {@code n} names a protobuf transform, so the other wires can reject it clearly. */
    static boolean isPbName(String n) { return byName(n) != null; }

    /** The protobuf transform named {@code n}, or null when it is not one. */
    static PbTransform byName(String n) {
        switch (n) {
            case "pstring": return new PbTransform(Kind.PSTRING, n, 2);
            case "pvarint": return new PbTransform(Kind.PVARINT, n, 0);
            case "psint":   return new PbTransform(Kind.PSINT, n, 0);
            case "pdouble": return new PbTransform(Kind.PDOUBLE, n, 1);
            case "pfloat":  return new PbTransform(Kind.PFLOAT, n, 5);
            default:        return null;
        }
    }

    /**
     * Decode one field value whose wire type the caller has already matched to {@link #wireType()}.
     * {@code num} carries the varint value (wire type 0), the fixed64 bit pattern (1) or the fixed32 bit
     * pattern in its low 32 bits (5); {@code bytes} carries the length-delimited payload (2).
     * Throws IllegalArgumentException on infinity or not-a-number.
     */
    Object decode(long num, byte[] bytes) {
        switch (kind) {
            case PSTRING: return new String(bytes, StandardCharsets.UTF_8);
            case PVARINT: return num;
            case PSINT:   return (num >>> 1) ^ -(num & 1L);          // zig-zag to signed
            case PDOUBLE: return BitsTransform.finite(Double.longBitsToDouble(num));
            case PFLOAT:  return BitsTransform.finite((double) Float.intBitsToFloat((int) num));
            default:      throw new IllegalStateException(kind.name());
        }
    }

    /** Encode a model value to this field's protobuf payload (the bytes after the tag). */
    byte[] encode(Object value) {
        switch (kind) {
            case PSTRING: {
                String s = value instanceof Double ? Transform.formatDouble((Double) value) : String.valueOf(value);
                return s.getBytes(StandardCharsets.UTF_8);
            }
            case PVARINT: return varint(Transform.asLong(value));
            case PSINT: {
                long n = Transform.asLong(value);
                return varint((n << 1) ^ (n >> 63));                // signed to zig-zag
            }
            case PDOUBLE: {
                double d = Transform.asDouble(value);
                if (!Double.isFinite(d)) throw new IllegalArgumentException("value is not finite");
                return fixed64(Double.doubleToLongBits(d));
            }
            case PFLOAT:  return fixed32(Float.floatToIntBits(BitsTransform.narrow(Transform.asDouble(value))));
            default:      throw new IllegalStateException(kind.name());
        }
    }

    /** Minimal protobuf base-128 varint of an int64. Unsigned shift, so a negative value takes ten bytes. */
    static byte[] varint(long v) {
        byte[] tmp = new byte[10];
        int i = 0;
        long x = v;
        while ((x & ~0x7FL) != 0) {
            tmp[i++] = (byte) ((x & 0x7F) | 0x80);
            x >>>= 7;
        }
        tmp[i++] = (byte) x;
        byte[] out = new byte[i];
        System.arraycopy(tmp, 0, out, 0, i);
        return out;
    }

    /** Little-endian 8-byte encoding of a fixed64 bit pattern. */
    static byte[] fixed64(long bits) {
        byte[] out = new byte[8];
        for (int i = 0; i < 8; i++) out[i] = (byte) (bits >>> (8 * i));
        return out;
    }

    /** Little-endian 4-byte encoding of a fixed32 bit pattern. */
    static byte[] fixed32(int bits) {
        byte[] out = new byte[4];
        for (int i = 0; i < 4; i++) out[i] = (byte) (bits >>> (8 * i));
        return out;
    }
}
