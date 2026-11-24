package goat.transformers;

/**
 * What the two codecs of the {@code bits} wire share: the message as bits, read from hex or from six-bit armored
 * text (engine-spec 0.14), and armored text written back. Armor is part of the bits wire (ruling 1d of 0.24).
 */
abstract class BitsWire<W> extends Codec<W> {
    BitsWire(Pack pack) { super(pack); }

    /** A bits message: its bytes, and its length in bits (a multiple of 8 from hex, of 6 from armored text). */
    static final class BitMsg {
        final byte[] b;
        final long bits;
        BitMsg(byte[] b, long bits) { this.b = b; this.bits = bits; }
    }

    /** One message of an inner pack decoded (engine-spec 0.34), its transform failures not yet judged. */
    static final class Layer {
        final Entity entity = new Entity();
        Failures fails;
        /** The end of the message in bits, not rounded; and the bits it is rounded up to a multiple of. */
        long end;
        long unit = 8;
        /** A transform-decode that stopped the decode (a switch on a key whose line failed), or null. */
        GtException stopped;

        /** True when {@code bytes} bytes hold one at or after the message's end (rulings 13 to 16). */
        boolean leftOver(int bytes) {
            long bits = (long) bytes * 8;
            if (bits <= end) return false;
            return bits > (end + unit - 1) / unit * unit;   // end < bits: no overflow
        }
    }

    /** Decode {@code msg} as the inner message of another pack. An error that stops the decode is thrown, except a transform-decode. */
    abstract Layer decodeLayer(byte[] msg);

    /** The bits wire's input: hex, or with {@code armor sixbit} armored text. */
    BitMsg parseBits(String text) {
        if (pack.armorSixbit) return fromArmor(text);
        byte[] b = fromHex(text);
        return new BitMsg(b, (long) b.length * 8);
    }

    /** The value 0 to 63 an armor character stands for, or -1 when it is not one. */
    static int armorValue(char c) {
        if (c >= 0x30 && c <= 0x57) return c - 0x30;
        if (c >= 0x60 && c <= 0x77) return c - 0x38;
        return -1;
    }

    /**
     * Armored text to its {@code 6 * characters} bits, first character first, most significant bit first. Every
     * character is checked before anything else is read: any other character is {@code malformed-wire}.
     */
    BitMsg fromArmor(String text) {
        int n = text.length();
        for (int i = 0; i < n; i++) {
            if (armorValue(text.charAt(i)) < 0) {
                throw malformed(String.format("armored text has character U+%04X at offset %d, which is not a six-bit armor character", (int) text.charAt(i), i));
            }
        }
        long bits = 6L * n;
        byte[] b = new byte[(int) ((bits + 7) >>> 3)];
        for (int i = 0; i < n; i++) BitsCodec.writeBits(b, 6L * i, 6, armorValue(text.charAt(i)), BitsLayout.MSB);
        return new BitMsg(b, bits);
    }

    /**
     * The first {@code bits} bits of the message, then zero bits to the next multiple of 6, as armored text: values
     * 0 to 39 as {@code 0x30 + v}, 40 to 63 as {@code 0x38 + v}. Bits beyond the buffer are zero.
     */
    static String toArmor(byte[] b, long bits) {
        long chars = (bits + 5) / 6;
        if (chars > Integer.MAX_VALUE - 16) throw new GtException(GtException.Code.TRANSFORM_ENCODE, null, null, "the message is too long: " + bits + " bits");
        char[] out = new char[(int) chars];
        for (int i = 0; i < out.length; i++) {
            int v = 0;
            for (int k = 0; k < 6; k++) {
                long j = 6L * i + k;
                int bit = 0;
                if (j < bits && (j >>> 3) < b.length) bit = (b[(int) (j >>> 3)] >>> (7 - (int) (j & 7))) & 1;
                v = (v << 1) | bit;
            }
            out[i] = (char) (v < 40 ? 0x30 + v : 0x38 + v);
        }
        return new String(out);
    }

}
