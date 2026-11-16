#include "goat_transformers/engine.hpp"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <unordered_map>
#include <unordered_set>

#include "codecs.hpp"
#include "derive.hpp"
#include "sequential.hpp"
#include "transforms.hpp"
#include "util.hpp"

namespace goat_transformers {

namespace fs = std::filesystem;

namespace {
std::string read_text(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw Error(ErrorKind::Io, "", "", "cannot read " + p.string());
    // One read of the whole file: pack files run to megabytes.
    in.seekg(0, std::ios::end);
    const std::streamoff size = in.tellg();
    if (size > 0) {
        std::string text(static_cast<std::size_t>(size), '\0');
        in.seekg(0, std::ios::beg);
        in.read(&text[0], size);
        text.resize(static_cast<std::size_t>(in.gcount()));
        return text;
    }
    in.clear();
    in.seekg(0, std::ios::beg);
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

// The `*.def` files of a model directory in byte order of file name, with
// `core.def` first, whatever its name sorts as: a `derive` line of another
// module may name a key of `core` (0.6 ruling 9).
std::vector<std::string> model_files(const fs::path& mdir) {
    std::error_code ec;
    std::vector<std::string> names;
    for (const auto& ent : fs::directory_iterator(mdir, ec))
        if (ent.is_regular_file() && ent.path().extension() == ".def") names.push_back(ent.path().filename().string());
    if (ec) throw Error(ErrorKind::Io, "", "", "cannot list " + mdir.string() + ": " + ec.message());
    std::sort(names.begin(), names.end());
    auto core = std::find(names.begin(), names.end(), "core.def");
    if (core != names.end()) std::rotate(names.begin(), core, core + 1);
    return names;
}

// Load parsed modules in the order given, each after the modules it uses
// (0.8); a cycle is bad-directive. A used module that no file defines is left
// to the load, which fails with unknown-module. With `wanted`, only the
// modules it names and the modules those use are loaded.
void load_modules(Engine& eng, std::vector<Module>& parsed, const std::vector<std::string>* wanted) {
    std::unordered_map<std::string, std::size_t> by_name;
    for (std::size_t i = 0; i < parsed.size(); ++i) by_name.emplace(parsed[i].name, i);  // the first file of a name
    std::vector<int> state(parsed.size(), 0);  // 0 not loaded, 1 loading the modules it uses, 2 loaded
    struct Loader {
        Engine& eng;
        std::vector<Module>& parsed;
        std::unordered_map<std::string, std::size_t>& by_name;
        std::vector<int>& state;
        void operator()(std::size_t i) {
            if (state[i] == 2) return;
            if (state[i] == 1)
                throw Error(ErrorKind::BadDirective, "", "",
                            "the 'uses' lines of the modules form a cycle through '" + parsed[i].name + "' (" +
                                parsed[i].origin + ")");
            state[i] = 1;
            const std::vector<std::string> uses = parsed[i].uses;
            for (const auto& u : uses) {
                auto it = by_name.find(u);
                if (it != by_name.end()) (*this)(it->second);
            }
            state[i] = 2;
            eng.add_model(std::move(parsed[i]));
        }
    } loader{eng, parsed, by_name, state};
    if (!wanted) {
        for (std::size_t i = 0; i < parsed.size(); ++i) loader(i);
        return;
    }
    for (const auto& w : *wanted) {
        auto it = by_name.find(w);
        if (it != by_name.end()) loader(it->second);
    }
}
}  // namespace

Engine Engine::load(const std::string& packs_dir, const std::string& models_dir, Distribution max_distribution) {
    Engine eng;
    eng.set_max_distribution(max_distribution);
    std::error_code ec;
    if (!fs::is_directory(packs_dir, ec))
        throw Error(ErrorKind::Io, "", "", "packs directory not found: " + packs_dir);

    // Modules first: model/*.def in byte order of file name. A named directory must
    // exist; the default one may be absent, and then no pack can load (unknown-module).
    const fs::path mdir = models_dir.empty() ? fs::path(packs_dir) / ".." / "model" : fs::path(models_dir);
    if (fs::is_directory(mdir, ec)) {
        const std::vector<std::string> names = model_files(mdir);
        std::vector<Module> parsed;
        parsed.reserve(names.size());
        for (const auto& n : names)
            parsed.push_back(detail::parse_model_unchecked(read_text(mdir / n), (mdir / n).string()));
        load_modules(eng, parsed, nullptr);
    } else if (!models_dir.empty()) {
        throw Error(ErrorKind::Io, "", "", "models directory not found: " + models_dir);
    }
    std::vector<fs::path> dirs;
    for (const auto& ent : fs::directory_iterator(packs_dir, ec))
        if (ent.is_directory() && fs::is_regular_file(ent.path() / "pack.def")) dirs.push_back(ent.path());
    if (ec) throw Error(ErrorKind::Io, "", "", "cannot list " + packs_dir + ": " + ec.message());
    std::sort(dirs.begin(), dirs.end());
    for (const auto& d : dirs) {
        fs::path def = d / "pack.def";
        eng.add_pack(parse_pack(read_text(def), def.string()));
    }
    return eng;
}

Engine Engine::load_packs(const std::string& packs_dir, const std::vector<std::string>& names,
                          const std::string& models_dir, Distribution max_distribution) {
    Engine eng;
    eng.set_max_distribution(max_distribution);
    std::error_code ec;
    if (!fs::is_directory(packs_dir, ec))
        throw Error(ErrorKind::Io, "", "", "packs directory not found: " + packs_dir);

    // The named packs, each once, in the order given. A name is a directory of
    // `packs_dir`, not a path.
    std::vector<Pack> packs;
    std::vector<std::string> seen;
    for (const auto& n : names) {
        if (std::find(seen.begin(), seen.end(), n) != seen.end()) continue;
        seen.push_back(n);
        const fs::path def = fs::path(packs_dir) / n / "pack.def";
        if (n.empty() || n == "." || n == ".." || n.find('/') != std::string::npos ||
            n.find('\\') != std::string::npos || !fs::is_regular_file(def, ec))
            throw Error(ErrorKind::Io, "", "", "no pack '" + n + "' in " + packs_dir);
        packs.push_back(parse_pack(read_text(def), def.string()));
    }

    // The modules they need: `core`, every module a pack uses, and every
    // module one of those uses. Module files are found by the name their
    // `module` line states, so every file of the directory is parsed; only the
    // needed ones are checked against the engine and loaded. A needed module
    // that no file defines is left to the load, which fails with
    // unknown-module.
    const fs::path mdir = models_dir.empty() ? fs::path(packs_dir) / ".." / "model" : fs::path(models_dir);
    if (fs::is_directory(mdir, ec)) {
        std::vector<std::string> files = model_files(mdir);
        std::vector<Module> parsed;
        parsed.reserve(files.size());
        for (const auto& n : files)
            parsed.push_back(detail::parse_model_unchecked(read_text(mdir / n), (mdir / n).string()));
        std::vector<std::string> wanted{"core"};
        for (const auto& p : packs)
            for (const auto& u : p.uses)
                if (std::find(wanted.begin(), wanted.end(), u) == wanted.end()) wanted.push_back(u);
        load_modules(eng, parsed, &wanted);
    } else if (!models_dir.empty()) {
        throw Error(ErrorKind::Io, "", "", "models directory not found: " + models_dir);
    }
    for (auto& p : packs) eng.add_pack(std::move(p));
    return eng;
}

void Engine::load_model(const std::string& text, const std::string& origin) {
    add_model(detail::parse_model_unchecked(text, origin));
}

// The checks of a module after its parse, in the order of 0.8 ruling 29.
void Engine::add_model(Module module) {
    const auto loaded = [this](const std::string& name) -> const Module* {
        auto it = modules_.find(name);
        return it == modules_.end() ? nullptr : &it->second;
    };
    if (module.distribution == Distribution::Controlled && max_distribution_ == Distribution::Public)
        throw Error(ErrorKind::DistributionRefused, "", "",
                    "module '" + module.name + "' is controlled and the engine limit is public (" + module.origin + ")");
    // v0.8: every used module is loaded, and a public module uses only public modules.
    for (const auto& u : module.uses)
        if (!loaded(u))
            throw Error(ErrorKind::UnknownModule, "", "",
                        "module '" + module.name + "' uses module '" + u + "', which is not loaded (" + module.origin + ")");
    if (module.distribution == Distribution::Public)
        for (const auto& u : module.uses)
            if (loaded(u)->distribution != Distribution::Public)
                throw Error(ErrorKind::DistributionViolation, "", "",
                            "public module '" + module.name + "' uses controlled module '" + u + "' (" + module.origin + ")");
    // `derive` lines: the target is a declared key of `core` or of the module,
    // every argument one of `core`, of the module or of a module it uses, and
    // the types fit the function (bad-directive).
    if (!module.derives.empty()) detail::check_derives(module, loaded, true);
    if (modules_.count(module.name))
        throw Error(ErrorKind::DuplicateModule, "", "",
                    "module '" + module.name + "' is already loaded (" + module.origin + ")");
    std::string name = module.name;
    modules_.emplace(std::move(name), std::move(module));
}

bool Engine::has_module(const std::string& name) const { return modules_.count(name) != 0; }

std::vector<std::string> Engine::modules() const {
    std::vector<std::string> out;
    for (const auto& kv : modules_) out.push_back(kv.first);
    return out;
}

namespace {
// A model key with no '.' is a key of `core`; otherwise the text before the first
// '.' is the module name and the rest is the key name.
void split_model_key(const std::string& key, std::string& module, std::string& name) {
    std::size_t dot = key.find('.');
    if (dot == std::string::npos) {
        module = "core";
        name = key;
    } else {
        module = key.substr(0, dot);
        name = key.substr(dot + 1);
    }
}
}  // namespace

// The v0.4 load checks, each over every `field` line of every kind (and, for the
// key checks, every `requires` key), in the spec's order.
void Engine::add_pack(Pack pack) {
    if (pack.distribution == Distribution::Controlled && max_distribution_ == Distribution::Public)
        throw Error(ErrorKind::DistributionRefused, pack.format, "",
                    "pack is controlled and the engine limit is public (" + pack.source + ")");

    std::vector<std::string> used{"core"};
    for (const auto& u : pack.uses)
        if (std::find(used.begin(), used.end(), u) == used.end()) used.push_back(u);
    for (const auto& u : used)
        if (!modules_.count(u))
            throw Error(ErrorKind::UnknownModule, pack.format, "", "module '" + u + "' is not loaded (" + pack.source + ")");

    if (pack.distribution == Distribution::Public)
        for (const auto& u : used)
            if (modules_.at(u).distribution != Distribution::Public)
                throw Error(ErrorKind::DistributionViolation, pack.format, "",
                            "public pack uses controlled module '" + u + "' (" + pack.source + ")");

    // The type of each table's model side, computed once.
    std::vector<KeyType> table_types;
    table_types.reserve(pack.tables.size());
    for (const auto& t : pack.tables) table_types.push_back(detail::table_model_type(t));

    // Every `field` line of the common lines, of every kind and of every group
    // body; every `requires` key and every `default` key (checked like a mapped
    // key, but with no transform); and the list of every `group`.
    enum class What { Field, Requires, Default, Group };
    struct Mapped {
        const std::string* key;
        const std::string* locator;
        const FieldLine* field;  // null for a `requires` key, a `default` key and a group's list
        What what;
    };
    static const std::string no_locator;
    std::vector<Mapped> mapped;
    struct Collect {
        std::vector<Mapped>& mapped;
        void fields(const std::vector<FieldLine>& fs) {
            for (const auto& f : fs) mapped.push_back({&f.key, &f.locator, &f, What::Field});
        }
        void defaults(const std::vector<DefaultLine>& ds) {
            for (const auto& d : ds) mapped.push_back({&d.key, &no_locator, nullptr, What::Default});
        }
        void groups(const std::vector<GroupLine>& gs) {
            for (const auto& g : gs) {
                mapped.push_back({&g.list, &g.locator, nullptr, What::Group});
                fields(g.fields);
                defaults(g.defaults);
                groups(g.groups);
            }
        }
    } collect{mapped};
    collect.fields(pack.fields);
    collect.groups(pack.groups);
    for (const auto& k : pack.kinds) {
        for (const auto& r : k.requires_keys) mapped.push_back({&r, &no_locator, nullptr, What::Requires});
        collect.fields(k.fields);
        collect.groups(k.groups);
    }
    collect.defaults(pack.defaults);
    for (const auto& k : pack.kinds) collect.defaults(k.defaults);
    // A sequential pack (0.8): every `field` and `also`, every group's list and
    // every `requires` key in file order, then every `default`.
    if (pack.sequential) {
        std::vector<Mapped> defaults;
        detail::SeqVisitor v;
        v.field = [&](FieldLine& f) { mapped.push_back({&f.key, &f.locator, &f, What::Field}); };
        v.group = [&](SeqNode& g) { mapped.push_back({&g.list, &no_locator, nullptr, What::Group}); };
        v.requires_key = [&](std::string& r) { mapped.push_back({&r, &no_locator, nullptr, What::Requires}); };
        v.default_line = [&](DefaultLine& d) { defaults.push_back({&d.key, &no_locator, nullptr, What::Default}); };
        detail::seq_visit(pack.seq, v);
        mapped.insert(mapped.end(), defaults.begin(), defaults.end());
    }

    // The module of each name, resolved once.
    std::vector<const Module*> owner(mapped.size(), nullptr);
    std::string mod, name;
    std::unordered_map<std::string, const Module*> used_modules;
    for (const auto& u : used) used_modules.emplace(u, &modules_.at(u));
    for (std::size_t i = 0; i < mapped.size(); ++i) {
        const Mapped& m = mapped[i];
        split_model_key(*m.key, mod, name);
        auto it = used_modules.find(mod);
        if (it == used_modules.end())
            throw Error(ErrorKind::ModuleNotUsed, pack.format, *m.locator,
                        "key '" + *m.key + "' is of module '" + mod + "', which no 'uses' line names");
        owner[i] = it->second;
    }
    for (std::size_t i = 0; i < mapped.size(); ++i) {
        const Mapped& m = mapped[i];
        split_model_key(*m.key, mod, name);
        if (!owner[i]->find(name) && !owner[i]->find_list(name))
            throw Error(ErrorKind::UndeclaredKey, pack.format, *m.locator,
                        "module '" + mod + "' declares no key or list '" + name + "'");
    }
    for (std::size_t i = 0; i < mapped.size(); ++i) {
        const Mapped& m = mapped[i];
        split_model_key(*m.key, mod, name);
        const ModelKey* key = owner[i]->find(name);
        // A `group` names a list; a `field` and a `default` name a scalar key (0.7).
        if (m.what == What::Group) {
            if (key)
                throw Error(ErrorKind::KeyTypeMismatch, pack.format, *m.locator,
                            "'group' names '" + *m.key + "', which is a key, not a list");
            continue;
        }
        if (!key) {
            if (m.what == What::Requires) continue;  // `requires <list>`
            throw Error(ErrorKind::KeyTypeMismatch, pack.format, *m.locator,
                        std::string(m.what == What::Field ? "'field'" : "'default'") + " names '" + *m.key +
                            "', which is a list, not a key");
        }
        if (!m.field) continue;
        const KeyType want = key->type;
        if (m.field->table >= 0) {
            // A field with `via`: the key's type against the type of the table's model side.
            // An all-integer table on a `float` key is accepted (0.6 ruling 4).
            const MapTable& table = pack.tables[static_cast<std::size_t>(m.field->table)];
            const KeyType got = table_types[static_cast<std::size_t>(m.field->table)];
            if (got != want && !(got == KeyType::Int && want == KeyType::Float))
                throw Error(ErrorKind::KeyTypeMismatch, pack.format, *m.locator,
                            "key '" + *m.key + "' is " + key_type_name(want) + " but the model side of table '" +
                                table.name + "' is " + key_type_name(got));
            continue;
        }
        const KeyType got = transform_yields(m.field->transform);
        if (got != want)
            throw Error(ErrorKind::KeyTypeMismatch, pack.format, *m.locator,
                        "key '" + *m.key + "' is " + key_type_name(want) + " but transform '" +
                            transform_name(m.field->transform) + "' yields " + key_type_name(got));
    }

    // Settle what the codecs need: each field's declared key type, each default
    // read as its key's type, and the kinds an xml root element selects among.
    auto settle_fields = [&](std::vector<FieldLine>& fields) {
        for (auto& f : fields) {
            split_model_key(f.key, mod, name);
            f.key_type = modules_.at(mod).find(name)->type;
        }
    };
    auto settle_defaults = [&](std::vector<DefaultLine>& defaults) {
        for (auto& d : defaults) {
            split_model_key(d.key, mod, name);
            const KeyType type = modules_.at(mod).find(name)->type;
            try {
                d.value = detail::read_as(d.text, type);
            } catch (const std::invalid_argument&) {
                throw Error(ErrorKind::KeyTypeMismatch, pack.format, "",
                            "default '" + d.text + "' cannot be read as key '" + d.key + "', which is " +
                                key_type_name(type) + " (" + pack.source + ":" + std::to_string(d.line) + ")");
            }
        }
    };
    struct SettleGroups {
        decltype(settle_fields)& fields;
        decltype(settle_defaults)& defaults;
        void operator()(std::vector<GroupLine>& gs) {
            for (auto& g : gs) {
                fields(g.fields);
                defaults(g.defaults);
                (*this)(g.groups);
            }
        }
    } settle_groups{settle_fields, settle_defaults};
    settle_fields(pack.fields);
    settle_defaults(pack.defaults);
    settle_groups(pack.groups);
    if (pack.sequential) {
        std::vector<DefaultLine> one(1);
        detail::SeqVisitor v;
        v.field = [&](FieldLine& f) {
            split_model_key(f.key, mod, name);
            f.key_type = modules_.at(mod).find(name)->type;
        };
        v.default_line = [&](DefaultLine& d) {
            one[0] = d;
            settle_defaults(one);
            d = one[0];
        };
        detail::seq_visit(pack.seq, v);
    }
    pack.kinds_by_root.clear();
    for (std::size_t k = 0; k < pack.kinds.size(); ++k) {
        settle_fields(pack.kinds[k].fields);
        settle_defaults(pack.kinds[k].defaults);
        settle_groups(pack.kinds[k].groups);
        if (pack.wire == Wire::Xml)
            pack.kinds_by_root[pack.kinds[k].root.empty() ? pack.root : pack.kinds[k].root].push_back(k);
    }

    if (packs_.count(pack.format))
        throw Error(ErrorKind::InvalidPack, pack.format, "", "format defined twice (" + pack.source + ")");
    std::string format = pack.format;
    packs_.emplace(std::move(format), std::move(pack));
}

bool Engine::has_format(const std::string& format) const { return packs_.count(format) != 0; }

const Pack& Engine::pack(const std::string& format) const {
    auto it = packs_.find(format);
    if (it == packs_.end()) throw Error(ErrorKind::UnknownFormat, format, "", "no loaded pack defines this format");
    return it->second;
}

std::vector<std::string> Engine::formats() const {
    std::vector<std::string> out;
    for (const auto& kv : packs_) out.push_back(kv.first);
    return out;
}

Entity Engine::decode(const std::string& format, const std::string& bytes) const {
    const Pack& p = pack(format);
    if (p.sequential) return detail::decode_seq(p, bytes);
    switch (p.wire) {
        case Wire::Xml: return detail::decode_xml(p, bytes);
        case Wire::GeoJson: return detail::decode_geojson(p, bytes);
        case Wire::Bits: return detail::decode_bits(p, bytes);
        case Wire::Protobuf: return detail::decode_protobuf(p, bytes);
        case Wire::Json: return detail::decode_json(p, bytes);
    }
    throw Error(ErrorKind::UnknownWire, format, "", "no codec for this wire");
}

std::string Engine::encode(const std::string& format, const Entity& entity) const {
    const Pack& p = pack(format);
    if (p.sequential) return detail::encode_seq(p, entity);
    switch (p.wire) {
        case Wire::Xml: return detail::encode_xml(p, entity);
        case Wire::GeoJson: return detail::encode_geojson(p, entity);
        case Wire::Bits: return detail::encode_bits(p, entity);
        case Wire::Protobuf: return detail::encode_protobuf(p, entity);
        case Wire::Json: return detail::encode_json(p, entity);
    }
    throw Error(ErrorKind::UnknownWire, format, "", "no codec for this wire");
}

std::string Engine::convert(const std::string& from, const std::string& to, const std::string& bytes) const {
    return convert_impl(from, to, bytes, nullptr, nullptr);
}

std::string Engine::convert(const std::string& from, const std::string& to, const std::string& bytes,
                            const Context& context) const {
    return convert_impl(from, to, bytes, &context, nullptr);
}

std::string Engine::convert_text(const std::string& from, const std::string& to, const std::string& bytes,
                                 const std::map<std::string, std::string>& context) const {
    return convert_impl(from, to, bytes, nullptr, &context);
}

// engine-spec.md 0.6, Order inside `convert`.
std::string Engine::convert_impl(const std::string& from, const std::string& to, const std::string& bytes,
                                 const Context* context, const std::map<std::string, std::string>* text) const {
    const Pack& target = pack(to);  // fail on an unknown target before decoding
    (void)target;
    Entity e = decode(from, bytes);
    if (from != to) e.kind = {};  // a cross-format conversion chooses the target kind by `requires`
    // A same-format conversion with no context skips both steps, so it stays byte-exact.
    // An empty context counts as given.
    if (from != to || context || text) {
        if (text) apply_context(e, context_from_text(*text));
        if (context) apply_context(e, *context);
        complete(e);
    }
    return encode(to, e);
}

const ModelKey* Engine::find_key(const std::string& key) const {
    std::string mod, name;
    split_model_key(key, mod, name);
    auto it = modules_.find(mod);
    return it == modules_.end() ? nullptr : it->second.find(name);
}

Engine::Context Engine::context_from_text(const std::map<std::string, std::string>& text) const {
    Context out;
    for (const auto& kv : text) {
        const ModelKey* k = find_key(kv.first);
        // A list where a scalar key is expected (0.7 ruling 18).
        if (!k && is_list(kv.first))
            throw Error(ErrorKind::KeyTypeMismatch, "", "", "context key '" + kv.first + "' is a list, not a key");
        if (!k) throw Error(ErrorKind::UndeclaredKey, "", "", "no loaded module declares context key '" + kv.first + "'");
        try {
            out[kv.first] = detail::read_as(kv.second, k->type);
        } catch (const std::invalid_argument&) {
            throw Error(ErrorKind::KeyTypeMismatch, "", "",
                        "context value '" + kv.second + "' cannot be read as key '" + kv.first + "', which is " +
                            key_type_name(k->type));
        }
    }
    return out;
}

void Engine::apply_context(Entity& entity, const Context& context) const {
    for (const auto& kv : context) {
        const ModelKey* k = find_key(kv.first);
        if (!k && is_list(kv.first))
            throw Error(ErrorKind::KeyTypeMismatch, "", "", "context key '" + kv.first + "' is a list, not a key");
        if (!k) throw Error(ErrorKind::UndeclaredKey, "", "", "no loaded module declares context key '" + kv.first + "'");
        const bool fits = (k->type == KeyType::String && kv.second.kind == Value::Kind::String) ||
                          (k->type == KeyType::Float && kv.second.kind == Value::Kind::Float) ||
                          (k->type == KeyType::Int && kv.second.kind == Value::Kind::Int);
        if (!fits)
            throw Error(ErrorKind::KeyTypeMismatch, "", "",
                        "context key '" + kv.first + "' is " + key_type_name(k->type) +
                            " and the value supplied is not");
    }
    for (const auto& kv : context) entity.fields.emplace(kv.first, kv.second);  // only the keys the entity lacks
}

void Engine::complete(Entity& entity) const {
    for (int pass = 0; pass < 8; ++pass) {
        bool set = false;
        for (const auto& m : modules_)
            for (const auto& d : m.second.derives)
                if (detail::apply_derive(d, entity)) set = true;
        if (!set) break;
    }
}

bool Engine::is_list(const std::string& list) const {
    std::string mod, name;
    split_model_key(list, mod, name);
    auto it = modules_.find(mod);
    return it != modules_.end() && it->second.find_list(name) != nullptr;
}

std::vector<std::string> Engine::model_keys(const std::string& format) const {
    const Pack& p = pack(format);
    std::vector<std::string> out;
    std::unordered_set<std::string> seen;
    // A list is `<list>[]` and an item key `<list>[].<key>`, nested lists likewise.
    struct Walk {
        std::vector<std::string>& out;
        std::unordered_set<std::string>& seen;
        void add(const std::string& key) {
            if (seen.insert(key).second) out.push_back(key);
        }
        void lines(const std::vector<detail::LineRef>& ls, const std::string& prefix) {
            for (const auto& line : ls) {
                if (line.field) add(prefix + line.field->key);
                if (!line.group) continue;
                const std::string list = prefix + line.group->list + "[]";
                add(list);
                lines(detail::group_lines(*line.group), list + ".");
            }
        }
    } walk{out, seen};
    if (p.sequential) {
        detail::seq_model_keys(p.seq, "", [&](const std::string& key) { walk.add(key); });
        return out;
    }
    walk.lines(detail::active_lines(p, nullptr), "");
    const Pack none;  // the lines of each kind alone, in line order
    for (const auto& k : p.kinds) walk.lines(detail::active_lines(none, &k), "");
    return out;
}

}  // namespace goat_transformers
