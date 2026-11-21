package goat.transformers;

import java.util.Set;

/**
 * The forms of a locator on each wire (ruling 5a of 0.11), as the pack reader checks them. They belong to the pack
 * language, not to a codec: every build has them, so a pack is read the same way whatever wires the build has
 * (ruling 1b of 0.24). Each check returns null when the locator is well formed, else the reason.
 */
final class Locators {
    private Locators() {}

    // ---- xml ----

    /** Null when {@code locator} is a path of element names, as a group needs, else the reason. */
    static String xmlGroup(String locator) {
        for (String seg : locator.split("/", -1)) {
            if (seg.isEmpty() || seg.startsWith("@") || seg.startsWith("#")) {
                return "an xml group locator is a path of element names: " + locator;
            }
        }
        return null;
    }

    /** Null when {@code locator} is a valid xml field locator, else the reason. */
    static String xmlField(String locator) {
        String[] parts = locator.split("/", -1);
        String last = parts[parts.length - 1];
        if (!(last.startsWith("@") && last.length() > 1) && !last.equals("#text")) {
            return "xml locator must end in @name or #text: " + locator;
        }
        for (int i = 0; i < parts.length - 1; i++) {
            if (parts[i].isEmpty() || parts[i].startsWith("@") || parts[i].startsWith("#")) {
                return "bad element path segment \"" + parts[i] + "\" in " + locator;
            }
        }
        return null;
    }

    // ---- json (and the items of a geojson group) ----

    /** Null when {@code locator} is a valid json path, else the reason. */
    static String json(String locator) {
        if (locator.isEmpty()) return "empty json path";
        for (String seg : locator.split("\\.", -1)) {
            if (seg.isEmpty()) return "json path has an empty member name: " + locator;
        }
        return null;
    }

    // ---- geojson ----

    /** The coordinate slots of a Point, in order. */
    static final String[] GEOJSON_COORD = {"lon", "lat", "alt"};

    /** The top-level members of a Feature that a locator may not name. */
    static final Set<String> GEOJSON_RESERVED = Set.of("type", "geometry", "properties");

    /** Null when {@code locator} names a member a group may map: {@code properties.<name>} or a top-level member. */
    static String geojsonGroup(String locator) {
        if (locator.startsWith("geometry.") || locator.equals("geometry")) {
            return "a geojson group is a properties.<name> member or a top-level member: " + locator;
        }
        return geojsonField(locator);
    }

    /** The coordinate slot {@code geometry.lon|lat|alt} names (0, 1 or 2), or -1. */
    static int geojsonCoord(String locator) {
        for (int i = 0; i < GEOJSON_COORD.length; i++) if (locator.equals("geometry." + GEOJSON_COORD[i])) return i;
        return -1;
    }

    static String geojsonField(String locator) {
        if (geojsonCoord(locator) >= 0) return null;
        if (locator.startsWith("properties.")) {
            return locator.length() > "properties.".length() ? null : "empty properties member name";
        }
        if (locator.startsWith("geometry.")) return "geometry locator must be geometry.lon, geometry.lat or geometry.alt: " + locator;
        if (locator.isEmpty() || locator.contains(".")) return "bad geojson locator: " + locator;
        if (GEOJSON_RESERVED.contains(locator)) return "top-level member \"" + locator + "\" is reserved by GeoJSON";
        return null;
    }

    // ---- protobuf ----

    /** Null when {@code locator} is a valid protobuf dot-path of field numbers, else the reason. */
    static String protobufField(String locator) {
        String[] p = locator.split("\\.", -1);
        for (String seg : p) {
            if (seg.isEmpty()) return "protobuf path has an empty field number: " + locator;
            if (!Transform.UNSIGNED.matcher(seg).matches()) return "protobuf path must be dot-separated field numbers: " + locator;
            long n;
            try {
                n = Long.parseLong(seg);
            } catch (NumberFormatException ex) {
                return "protobuf path must be dot-separated field numbers: " + locator;
            }
            if (n < 1 || n > 536870911) return "protobuf field number must be 1..536870911: " + locator;
        }
        return null;
    }

    // ---- bits (fixed layout) ----

    /** Null when {@code locator} is a well-formed bits group locator {@code <word>:<pos>}, else the reason. */
    static String bitsGroup(String locator) {
        String[] p = locator.split(":", -1);
        if (p.length != 2) return "a bits group locator is word:pos: " + locator;
        for (String part : p) {
            if (!Transform.UNSIGNED.matcher(part).matches()) return "a bits group locator word:pos takes two digit-only parts: " + locator;
        }
        try {
            if (Integer.parseInt(p[0]) < 0 || Integer.parseInt(p[1]) < 0) return "bits word and pos must be >= 0: " + locator;
        } catch (NumberFormatException ex) {
            return "bits group locator word:pos must be integers: " + locator;
        }
        return null;
    }

    /** {@code word:pos:len} to {@code int[]{word, pos, len}}. Assumes {@link #bits} has passed. */
    static int[] bitsParse(String locator) {
        String[] p = locator.split(":", -1);
        return new int[]{ Integer.parseInt(p[0]), Integer.parseInt(p[1]), Integer.parseInt(p[2]) };
    }

    /** Null when {@code locator} is a well-formed bits locator, else the reason. The transform checks the length. */
    static String bits(String locator) {
        String[] p = locator.split(":", -1);
        if (p.length != 3) return "bits locator must be word:pos:len: " + locator;
        for (String part : p) {
            if (!Transform.UNSIGNED.matcher(part).matches()) return "bits locator word:pos:len takes three digit-only parts: " + locator;
        }
        int word;
        int pos;
        int len;
        try {
            word = Integer.parseInt(p[0]);
            pos = Integer.parseInt(p[1]);
            len = Integer.parseInt(p[2]);
        } catch (NumberFormatException ex) {
            return "bits locator word:pos:len must be integers: " + locator;
        }
        if (word < 0) return "bits word index must be >= 0: " + locator;
        if (pos < 0) return "bits pos must be >= 0: " + locator;
        if (len < 1) return "bits len must be >= 1: " + locator;
        return null;
    }
}
