package goat.transformers;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * The paths and tags of the {@code tlv} wire (0.13) and the scope check of a tlv pack. They are load checks of the
 * pack language, so they are in every build; the codec that reads and writes tlv messages is {@code TlvCodec}, in
 * the tlv wire only.
 */
final class TlvLayout {
    private TlvLayout() {}

    /** The largest tag a path, a checksum or a BER-OID tag may hold: 2^28-1. */
    static final long MAX_TAG = (1L << 28) - 1;

    /** A parsed path with its size: {@code 48.2:1}. */
    static final class Loc {
        final long[] tags;
        /** {@code :<n>}, 0 when not given. */
        final int size;
        /** The path without its size, as written (tags have no leading zero, so it is canonical). */
        final String path;

        Loc(long[] tags, int size, String path) {
            this.tags = tags;
            this.size = size;
            this.path = path;
        }
    }

    /**
     * {@code <tag>[.<tag>…][:<n>]}, or a reason. Every tag is a decimal integer from 0 to 2^28-1 with no leading
     * zero, below 2^(8 tagSize) under a fixed tag size; {@code n} is one digit from 1 to 8 (ruling 6 of 0.13).
     */
    static Object parseLocator(String locator, int tagSize) {
        String path = locator;
        int size = 0;
        int colon = locator.indexOf(':');
        if (colon >= 0) {
            path = locator.substring(0, colon);
            String n = locator.substring(colon + 1);
            if (n.length() != 1 || n.charAt(0) < '1' || n.charAt(0) > '8') {
                return "a size is :<n> with n one digit from 1 to 8, got \"" + locator + "\"";
            }
            size = n.charAt(0) - '0';
        }
        String[] parts = path.split("\\.", -1);
        long[] tags = new long[parts.length];
        for (int i = 0; i < parts.length; i++) {
            String t = parts[i];
            String why = checkTag(t, tagSize);
            if (why != null) return why + " in path \"" + locator + "\"";
            tags[i] = Long.parseLong(t);
        }
        return new Loc(tags, size, path);
    }

    /** Null when {@code t} is a valid tag under the tag encoding ({@code tagSize} 0 for ber-oid), else the reason. */
    static String checkTag(String t, int tagSize) {
        if (t.isEmpty() || t.length() > 9) return "a tag is a decimal integer from 0 to 268435455, got \"" + t + "\"";
        for (int i = 0; i < t.length(); i++) {
            if (t.charAt(i) < '0' || t.charAt(i) > '9') return "a tag is a decimal integer, got \"" + t + "\"";
        }
        if (t.length() > 1 && t.charAt(0) == '0') return "a tag has no leading zero, got \"" + t + "\"";
        long v = Long.parseLong(t);
        if (v > MAX_TAG) return "a tag is at most 268435455, got " + t;
        if (tagSize > 0 && tagSize < 4 && v >= (1L << (8 * tagSize))) {
            return "tag " + t + " does not fit tag " + tagSize;
        }
        return null;
    }

    /**
     * Ruling 5 of 0.13: in one scope, a line at a path and another line at a path under it is
     * {@code bad-directive}.
     */
    static void checkScope(List<Pack.Line> lines, String format, String source) {
        Map<String, Pack.Line> ends = new HashMap<>(), through = new HashMap<>();
        for (Pack.Line l : lines) {
            Loc loc = (Loc) l.loc;
            ends.putIfAbsent(loc.path, l);
            StringBuilder p = new StringBuilder();
            for (int i = 0; i < loc.tags.length - 1; i++) {
                if (i > 0) p.append('.');
                p.append(loc.tags[i]);
                through.putIfAbsent(p.toString(), l);
            }
        }
        for (Pack.Line l : lines) {
            Loc loc = (Loc) l.loc;
            Pack.Line under = through.get(loc.path);
            if (under != null) {
                Pack.Line later = under.line > l.line ? under : l;
                throw new GtException(GtException.Code.BAD_DIRECTIVE, format, later.locator, source + ":" + later.line
                        + ": path " + loc.path + " is read as a value and as a set in one scope (lines " + l.line
                        + " and " + under.line + ")");
            }
        }
    }

}
