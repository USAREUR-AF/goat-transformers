package goat.transformers;

/** How far a module or pack may be distributed. {@code PUBLIC} is below {@code CONTROLLED}. */
public enum Distribution {
    PUBLIC("public"),
    CONTROLLED("controlled");

    private final String token;

    Distribution(String token) { this.token = token; }

    public String token() { return token; }

    /** The marking named {@code token}, or null when it is neither {@code public} nor {@code controlled}. */
    public static Distribution byToken(String token) {
        for (Distribution d : values()) {
            if (d.token.equals(token)) return d;
        }
        return null;
    }

    /** True when something marked {@code this} may be loaded by an engine whose limit is {@code limit}. */
    public boolean within(Distribution limit) { return compareTo(limit) <= 0; }
}
