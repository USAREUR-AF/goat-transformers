// Sequential binary layouts (engine-spec.md, Version 0.8): a `bits` pack with
// `layout sequential` is a tree of lines read, and written, in order from a
// cursor.
#pragma once

#include <functional>
#include <optional>
#include <string>
#include <vector>

#include "goat_transformers/engine.hpp"

namespace goat_transformers::detail {

// One line of a pack.def or model module split into tokens (pack.cpp). Returns
// false with `err` set on an unterminated or misplaced quote.
bool tokenize_line(const std::string& line, std::vector<std::string>& out, std::string& err);

// True when the text has a `layout sequential` line.
bool is_sequential_pack(const std::string& text);

// Parse the text of a pack.def that has `layout sequential`.
Pack parse_seq_pack(const std::string& text, const std::string& source);

// Every line of a sequential pack that names a model key or a list, in file
// order: each `field` and `also` binding, each `default`, each `group` and
// each `requires` key. A callback that is empty is skipped.
struct SeqVisitor {
    std::function<void(FieldLine&)> field;
    std::function<void(DefaultLine&)> default_line;
    std::function<void(SeqNode&)> group;
    std::function<void(std::string&)> requires_key;
    std::function<void(SeqKind&)> kind;          // v0.20: every kind, message and item kinds
    std::function<void(SeqNode&)> switch_node;   // v0.20: every `switch`
};
void seq_visit(SeqBody& body, const SeqVisitor& v);

// The model keys of a body, first appearance order: a list is `<list>[]` and
// an item key `<list>[].<key>`. `inner`, when given, is called with the format
// of each `inner` line at its place in that order (v0.34).
void seq_model_keys(const SeqBody& body, const std::string& prefix,
                    const std::function<void(const std::string&)>& add,
                    const std::function<void(const std::string&)>* inner = nullptr);

// v0.92: the messages decode finds at an `inner ... run` line, for the run
// operations, and where encode takes them from.
struct RunMessage {
    Entity entity;               // the message alone
    std::optional<Error> error;
    bool stopped = false;        // the error ended the run
};
struct RunSink {
    std::uint64_t max_items = 0;
    bool reached = false;
    // No `run` line can be reached any more (ruling 4): the message is ordinary.
    bool passed = false;
    std::string inner_format;
    std::vector<RunMessage> messages;
};
struct RunSource {
    std::size_t count = 0;
    // The bytes of message `k` as the inner pack writes it, in hex.
    std::function<std::string(const Pack& inner, std::size_t k)> hex;
};

// v0.34: what decode and encode of a sequential pack ask of the engine when
// they reach an `inner` line.
class InnerHost {
public:
    virtual ~InnerHost() = default;
    // The inner pack, after the checks made where the line is reached, in
    // their order: unknown-format, bad-directive (its wire, armor, encoding;
    // an `inner` line of its own, or the outer pack itself), and
    // distribution-violation.
    // `run` (0.92 ruling 16): the inner pack is sequential and has `framing self`,
    // between the second and the third check.
    virtual const Pack& reach(const Pack& outer, const std::string& format, bool run = false) const = 0;
    // v0.92: set in the run operations; null otherwise.
    virtual RunSink* sink() const { return nullptr; }
    virtual const RunSource* source() const { return nullptr; }
    // model_keys(<format>) of the inner pack, for the fifth check (0.52 ruling 20).
    virtual std::vector<std::string> model_keys(const Pack& inner) const = 0;
    // decode(<format>, hex) by the inner pack's rules, within the decode that
    // is running (its limit on list items and its failed fields).
    // Unless `partial`, bytes at or after the inner
    // message's end are malformed-wire.
    virtual Entity decode(const Pack& inner, const std::string& hex, bool partial) const = 0;
    // encode(<format>, entity) as a layer: the inner kind selected by
    // Entity.inner_kind, then Entity.kind, then `requires`. Hex text.
    virtual std::string encode(const Pack& inner, const Entity& entity) const = 0;
};

// Every `case` and `else` of the pack by id (0.20), for encode; the plan keeps it (0.25).
std::vector<const SeqCase*> seq_cases_by_id(const Pack& p);

// `host` serves the `inner` lines (v0.34); without one, reaching an `inner`
// line is unknown-format.
// `exact`: input after the message's end (rulings 13 and 16 of 0.34) is
// malformed-wire; without it, that input is ignored.
Entity decode_seq(const Pack& p, const std::string& bytes, const InnerHost* host = nullptr, bool exact = false);
std::string encode_seq(const Pack& p, const Entity& e, const InnerHost* host = nullptr);

// v0.92: the kind an entity selects in a sequential pack (null when the pack
// has none; throws no-kind) and the `inner` line of a run in the common lines
// or in that kind; null when there is none.
struct RunLine {
    const SeqKind* kind = nullptr;
    const SeqNode* line = nullptr;
};
RunLine seq_run_line(const Pack& p, const Entity& e);

}  // namespace goat_transformers::detail
