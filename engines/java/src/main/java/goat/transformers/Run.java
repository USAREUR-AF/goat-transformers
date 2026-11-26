package goat.transformers;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** The results of {@code decode_run} and {@code convert_run} (engine-spec 0.92). */
public final class Run {
    private Run() {}

    /** One result of {@code convert_run}: the target message, or the error that stands in its place. */
    public static final class Result {
        /** The message in the target format; null for an error. */
        public final String output;
        /** The error; null for a message. */
        public final GtException error;

        Result(String output, GtException error) {
            this.output = output;
            this.error = error;
        }
    }

    /** What {@code decode_run} gives: the outer lines' entity and, per message, its joined entity or its error. */
    public static final class Decoded {
        /** The entity of the outer lines alone; null for an ordinary message that did not decode. */
        public final Entity outer;
        /** Per message an {@link Entity} or a {@link GtException}. */
        public final List<Object> messages;

        Decoded(Entity outer, List<Object> messages) {
            this.outer = outer;
            this.messages = Collections.unmodifiableList(messages);
        }
    }

    /** One decode of a message of a carrier pack in a run operation. */
    static final class State {
        /** The run goes to a carrier pack: an error that stops a message's decode is the call's (ruling 4). */
        final boolean toCarrier;
        /** At most this many messages (ruling 5). */
        final long max;
        /** A {@code run} line was reached. */
        boolean reached;
        /** It is known that none is: the kind selected has none, or its block is absent. */
        boolean ordinary;
        /** The inner format of the {@code run} line reached. */
        String inner;
        /** Per message its own entity (not joined) or its error. */
        final List<Object> messages = new ArrayList<>();
        Entity outer;
        /** A transform-decode of the outer lines that no outer line forgives. */
        GtException outerError;
        /** Of an ordinary message: its decode error. */
        GtException ordinaryError;

        /** The messages whose decode came to its end, a transform-decode included (ruling 5). */
        long ended;
        /** The items of those messages' own entities, summed (ruling 5); saturates at Long.MAX_VALUE. */
        long items;

        State(boolean toCarrier, long max) {
            this.toCarrier = toCarrier;
            this.max = max;
        }

        /** A message whose decode came to its end: its own items join the sum of ruling 5. */
        void ended(Entity message) {
            ended++;
            items = add(items, Codec.listItems(message));
        }

        /**
         * Ruling 5: over the messages whose decode came to its end, the outer entity's items once for each and each
         * message's own items, summed; one more than {@code max} is {@code malformed-wire} of the call. Made once the
         * carrier's decode has ended, after the call's other decode errors, before context and encode.
         */
        void checkSum(String format) {
            long outerItems = Codec.listItems(outer);
            long sum = add(items, outerItems == 0 || ended == 0 ? 0
                    : ended > Long.MAX_VALUE / outerItems ? Long.MAX_VALUE : ended * outerItems);
            if (sum > max) {
                throw new GtException(GtException.Code.MALFORMED_WIRE, format, null, "the joined entities of the run hold "
                        + sum + " list items together, more than " + max + " (the limit on list items)");
            }
        }

        private static long add(long a, long b) {
            long s = a + b;
            return s < 0 ? Long.MAX_VALUE : s;
        }
    }

    /** The joined entity of one message: the outer keys, the message's keys, both kind records (ruling 9). */
    static Entity join(Entity outer, Entity message) {
        Entity e = copy(outer);
        message.fields().forEach((k, v) -> { if (e.get(k) == null) e.put(k, v); });
        message.lists().forEach((k, v) -> { if (e.list(k) == null) e.putList(k, v); });
        if (message.kindFormat() != null) e.setInnerKind(message.kindFormat(), message.kindName());
        return e;
    }

    /** The keys, lists and kind records of a bits entity, which has no residue. */
    static Entity copy(Entity from) {
        Entity e = new Entity();
        from.fields().forEach(e::put);
        from.lists().forEach(e::putList);
        if (from.kindFormat() != null) e.setKind(from.kindFormat(), from.kindName());
        if (from.innerKindFormat() != null) e.setInnerKind(from.innerKindFormat(), from.innerKindName());
        return e;
    }
}
