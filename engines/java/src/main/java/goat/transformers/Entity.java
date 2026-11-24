package goat.transformers;

import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * The shared model: named fields (String, Long or Double values), lists and residue.
 * Residue is kept per format name, keyed by that format's locator, so it never
 * crosses formats. A list is an ordered sequence of items; an item is an Entity
 * that holds keys and lists and has neither residue nor a kind.
 */
public final class Entity {
    private final LinkedHashMap<String, Object> fields = new LinkedHashMap<>();
    private final LinkedHashMap<String, LinkedHashMap<String, String>> residue = new LinkedHashMap<>();

    private final LinkedHashMap<String, List<Entity>> lists = new LinkedHashMap<>();
    /** Per format: the locators whose residue text is JSON to write back as it is, not as a string. */
    private Map<String, Set<String>> rawResidue;

    private String kindFormat;
    private String kindName;

    /** The format whose decode selected a message kind for this entity, or null. */
    public String kindFormat() { return kindFormat; }

    /** The selected kind's name, or null. {@code Entity.kind} is the pair (kindFormat, kindName). */
    public String kindName() { return kindName; }

    public void setKind(String format, String name) { kindFormat = format; kindName = name; }

    public void clearKind() { kindFormat = null; kindName = null; }

    private String innerKindFormat;
    private String innerKindName;

    /**
     * The format of the inner pack whose decode selected a kind for this entity (engine-spec 0.34), or null.
     * {@code Entity.inner_kind} is the pair (innerKindFormat, innerKindName); it is set by decode only.
     */
    public String innerKindFormat() { return innerKindFormat; }

    /** The kind the inner pack selected, or null. */
    public String innerKindName() { return innerKindName; }

    public void setInnerKind(String format, String name) { innerKindFormat = format; innerKindName = name; }

    public void clearInnerKind() { innerKindFormat = null; innerKindName = null; }

    public Map<String, Object> fields() { return fields; }

    public Object get(String key) { return fields.get(key); }

    public void put(String key, Object value) { fields.put(key, value); }

    /** {@code Entity.lists}: list name to its items. A list that is present and empty is distinct from an absent one. */
    public Map<String, List<Entity>> lists() { return lists; }

    /** The items of the list, or null when the entity does not have it. */
    public List<Entity> list(String name) { return lists.get(name); }

    public void putList(String name, List<Entity> items) { lists.put(name, items); }

    /** Mark the residue at {@code locator} as JSON text that is written back verbatim. */
    void markRawResidue(String format, String locator) {
        if (rawResidue == null) rawResidue = new java.util.HashMap<>();
        rawResidue.computeIfAbsent(format, k -> new HashSet<>()).add(locator);
    }

    boolean isRawResidue(String format, String locator) {
        Set<String> s = rawResidue == null ? null : rawResidue.get(format);
        return s != null && s.contains(locator);
    }

    /** Residue recorded by {@code format}, in decode order. Empty if none. */
    public Map<String, String> residue(String format) {
        Map<String, String> r = residue.get(format);
        return r == null ? Collections.emptyMap() : Collections.unmodifiableMap(r);
    }

    public void putResidue(String format, String locator, String value) {
        residue.computeIfAbsent(format, k -> new LinkedHashMap<>()).put(locator, value);
    }

    @Override
    public String toString() { return "Entity{kind=" + (kindFormat == null ? "-" : kindFormat + "/" + kindName)
            + (innerKindFormat == null ? "" : ", inner_kind=" + innerKindFormat + "/" + innerKindName) + ", fields=" + fields + (lists.isEmpty() ? "" : ", lists=" + lists) + ", residue=" + residue + "}"; }
}
