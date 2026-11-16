package goat.transformers;

/** Every engine failure is one of these, carrying a named code, the format and the locator involved. */
public final class GtException extends RuntimeException {
    private static final long serialVersionUID = 1L;

    public enum Code {
        UNKNOWN_DIRECTIVE,
        UNKNOWN_TRANSFORM,
        BAD_PACK,
        UNKNOWN_FORMAT,
        MALFORMED_WIRE,
        MISSING_ROOT,
        TRANSFORM_DECODE,
        TRANSFORM_ENCODE,
        BAD_MODEL,
        // Version 0.5.
        NO_KIND,
        DUPLICATE_KIND,
        BAD_DIRECTIVE,
        // Load checks of engine-spec Version 0.4. The message of each begins with its kind token and a colon.
        MISSING_DISTRIBUTION("missing-distribution"),
        MISSING_SOURCE("missing-source"),
        DISTRIBUTION_REFUSED("distribution-refused"),
        UNKNOWN_MODULE("unknown-module"),
        DISTRIBUTION_VIOLATION("distribution-violation"),
        MODULE_NOT_USED("module-not-used"),
        UNDECLARED_KEY("undeclared-key"),
        KEY_TYPE_MISMATCH("key-type-mismatch"),
        DUPLICATE_MODULE("duplicate-module"),
        DUPLICATE_KEY("duplicate-key");

        private final String specKind;

        Code() { this.specKind = null; }

        Code(String specKind) { this.specKind = specKind; }

        /** The error kind token: the specification's kind where it names one, else the code name in lower case. */
        public String kind() { return specKind != null ? specKind : name().toLowerCase().replace('_', '-'); }
    }

    private final Code code;
    private final String format;
    private final String locator;
    private final transient Entity partial;

    public GtException(Code code, String format, String locator, String detail) {
        this(code, format, locator, detail, null);
    }

    public GtException(Code code, String format, String locator, String detail, Entity partial) {
        super(message(code, format, locator, detail));
        this.code = code;
        this.format = format;
        this.locator = locator;
        this.partial = partial;
    }

    private static String message(Code code, String format, String locator, String detail) {
        String where = "[format=" + (format == null ? "-" : format) + " locator=" + (locator == null ? "-" : locator) + "]";
        return code.kind() + ": " + detail + " " + where;
    }

    public Code code() { return code; }
    /** The error kind token, e.g. {@code undeclared-key}. */
    public String kind() { return code.kind(); }
    public String format() { return format; }
    public String locator() { return locator; }
    /** For TRANSFORM_DECODE: the entity with the failed fields absent. Never returned silently. */
    public Entity partial() { return partial; }
}
