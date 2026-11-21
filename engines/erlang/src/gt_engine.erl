%% gt_engine: decode(format, bytes) -> entity, encode(format, entity) -> bytes,
%% complete(entity), convert. Clean-room from spec/ and packs/ only
%% (engine-spec Versions 0.1 - 0.13; a sequential
%% bits pack is read and written by gt_seq, the `text` wire by gt_text, the
%% `tlv` wire by gt_tlv).
%%
%% Entity = #{model => #{Key :: binary() => binary() | integer() | float()},
%%            lists => #{ListName :: binary() => [Item]},
%%            residue => [{Locator, Value}],   % xml and json: locator text;
%%                                             % geojson: {prop | top, Name},
%%                                             % the value as JSON text
%%            src => FormatName :: binary(),
%%            kind => undefined | {FormatName, KindName}}
%%
%% Engine = #{max_distribution => public | controlled,
%%            modules => #{NameBin => Module}, packs => #{NameBin => Pack},
%%            derives => [{Target, Function, [Argument]}]}
%% Item = #{model => #{Key => Value}, lists => #{ListName => [Item]}}: an
%% item of a list holds keys and lists as an entity does, without residue
%% and without a kind. A list that is present and empty is `[]`; an absent
%% list has no entry.
%% An engine starts empty; modules are loaded before the packs that use them.
%%
%% Errors:
%%   load:       error:{load_error, Kind :: atom(), Message}
%%   conversion: error:{convert_error, Kind :: atom(), Message}
%% Message begins with the kind and a colon. Conversion kinds: 'no-kind',
%% 'missing-root' (xml, a pack without kinds), 'malformed-wire',
%% 'transform-decode', 'transform-encode', and for a caller-supplied key
%% 'undeclared-key', 'key-type-mismatch'.
-module(gt_engine).
-include("gt_wires.hrl").
-export([new/0, set_max_distribution/2, load_model/2, load_pack/2, load_dir/2,
         load_dir/3, load_dir/4, load_packs/3, load_packs/4, load_packs/5,
         model_files/1, model_texts/1, model_read/1, model_order/1, licence_start/3, packs/1, modules/1,
         model_keys/1, pack/2, set_max_items/2, capability/3]).
-export([decode/2, decode/3, encode/2, encode/3, complete/2, complete/3,
         convert/4, convert/5]).
%% for the readers and writers of gt_seq, gt_text and gt_tlv
-export([conv_error/4, item_source/2,
         items_reserve/2, items_release/1, items_held/1, record_failure/3,
         record_failure_msg/1,
         via_decode/6, typemap_decode/3, wire_value/5, guard_encode/4,
         holds/3, line_value/3, req_holds/3]).
%% the transforms of the bits wire, which the tlv wire uses too
-if(?W_BITS orelse ?W_TLV).
-export([bits_decode/4, bits_encode/4]).
-endif.
%% hex text: the input and output of bits, protobuf and tlv
-if(?W_BITS orelse ?W_PROTOBUF orelse ?W_TLV).
-export([unhex/2]).
-endif.
%% for gt_seq (sequential layouts); characters ending at a terminator (0.22)
-if(?W_BITS).
-export([chars_width/1, until_text/2, until_codes/3, swap_bytes/2, bits_sentinel/3,
         unwire/2, trim/2, armor_out/3]).
-endif.

-define(M64, 16#FFFFFFFFFFFFFFFF).

%% the limit on list items of one decode (ruling 7 of 0.11)
-define(DEFAULT_MAX_ITEMS, 100000).
-define(ITEMS, {gt_engine, items}).
-define(OVER, {gt_engine, over}).
-define(FAILED, {gt_engine, failed}).

%% Marks the message of a failure that no reader or writer names.
-define(UNCLASSIFIED, "[unclassified:").

%% ===================================================================
%% engine instance: model modules, packs, distribution limit (0.4)
%% ===================================================================
new() -> #{max_distribution => controlled, modules => #{}, packs => #{}, derives => []}.

set_max_distribution(Engine, Max) when Max =:= public; Max =:= controlled ->
    Engine#{max_distribution := Max};
set_max_distribution(Engine, Max) ->
    set_max_distribution(Engine, gt_pack:distribution_atom(Max)).

packs(#{packs := Packs}) -> Packs.

%% The limit on the list items of one decode (ruling 7b of 0.11): an
%% integer of 0 or more.
set_max_items(Engine, N) when is_integer(N), N >= 0 -> Engine#{max_items => N}.

%% The capability report of an ordered pair of formats (ruling 6 of 0.11),
%% from the two packs alone -> {Grade, Carried, Dropped}.
capability(Engine, From, To) ->
    FromKeys = model_keys(pack(Engine, From)),
    ToKeys = maps:from_list([{K, true} || K <- model_keys(pack(Engine, To))]),
    {Carried, Dropped} = lists:partition(fun(K) -> maps:is_key(K, ToKeys) end, FromKeys),
    Grade = if Carried =:= [] -> none;
               Dropped =:= [] -> full;
               true -> partial
            end,
    {Grade, Carried, Dropped}.
modules(#{modules := Modules}) -> Modules.

%% A loaded pack by format name.
pack(#{packs := Packs} = Engine, Name) ->
    case maps:find(Name, Packs) of
        {ok, P} -> P#{max_items => maps:get(max_items, Engine, ?DEFAULT_MAX_ITEMS)};
        error -> conv_error('unknown-format', "format ~s is not loaded", [Name])
    end.

%% Union of the keys a pack maps, common lines and all kinds, in first
%% appearance order; a list as `<list>[]`, an item key as `<list>[].<key>`.
model_keys(Pack) -> gt_pack:model_keys(Pack).

%% Load one model module text -> Engine. The checks run in this order
%% (ruling 29 of 0.8): missing-distribution, missing-source,
%% distribution-refused, unknown-module, distribution-violation, the `derive`
%% checks, duplicate-module.
load_model(#{modules := Modules} = Engine, Text) ->
    M0 = gt_model:parse(Text),
    Name = maps:get(name, M0),
    within_limit(Engine, "module", Name, M0),
    gt_model:check_uses(M0, Modules),
    case maps:get(distribution, M0) of
        public ->
            lists:foreach(
              fun(U) ->
                      case maps:get(distribution, maps:get(U, Modules)) of
                          public -> ok;
                          controlled ->
                              gt_pack:load_error('distribution-violation',
                                                 "public module ~s uses controlled module ~s",
                                                 [Name, U])
                      end
              end, maps:get(uses, M0));
        controlled -> ok
    end,
    M = gt_model:check_derives(M0, Modules),
    case maps:is_key(Name, Modules) of
        true -> gt_pack:load_error('duplicate-module', "module ~s is already loaded", [Name]);
        false -> ok
    end,
    Modules1 = Modules#{Name => M},
    %% the derivations: the loaded modules in byte order of name, each
    %% module's `derive` lines in order
    Derives = [D || N <- lists:sort(maps:keys(Modules1)),
                    D <- maps:get(derives, maps:get(N, Modules1))],
    Engine#{modules := Modules1, derives := Derives}.

%% Load one pack.def text, checked against the modules loaded so far -> Engine.
load_pack(#{modules := Modules, packs := Packs} = Engine, Text) ->
    P = gt_pack:parse(Text),
    Name = maps:get(name, P),
    within_limit(Engine, "pack", Name, P),
    Used = [<<"core">> | [U || U <- maps:get(uses, P), U =/= <<"core">>]],
    lists:foreach(
      fun(U) ->
              case maps:is_key(U, Modules) of
                  true -> ok;
                  false -> gt_pack:load_error('unknown-module',
                                              "pack ~s uses module ~s, which is not loaded",
                                              [Name, U])
              end
      end, Used),
    case maps:get(distribution, P) of
        public ->
            lists:foreach(
              fun(U) ->
                      case maps:get(distribution, maps:get(U, Modules)) of
                          public -> ok;
                          controlled ->
                              gt_pack:load_error('distribution-violation',
                                                 "public pack ~s uses controlled module ~s",
                                                 [Name, U])
                      end
              end, Used);
        controlled -> ok
    end,
    %% every name the pack uses: mapped keys, lists of `group` lines, and the
    %% `requires` and `default` keys, which are checked like mapped keys.
    %% Each check runs over every name before the next check starts.
    UsedSet = maps:from_list([{U, true} || U <- Used]),
    Named = [{Key, split_key(Key), How} || {Key, How} <- gt_pack:named(P)],
    lists:foreach(
      fun({Key, {Mod, _}, _}) ->
              case maps:is_key(Mod, UsedSet) of
                  true -> ok;
                  false -> gt_pack:load_error('module-not-used',
                                              "pack ~s names ~s but has no `uses ~s` line",
                                              [Name, Key, Mod])
              end
      end, Named),
    Typed = lists:map(
              fun({Key, {Mod, KeyName}, How}) ->
                      case gt_model:key_type(maps:get(Mod, Modules), KeyName) of
                          {ok, Type} -> {Key, Type, How};
                          error -> gt_pack:load_error('undeclared-key',
                                                      "pack ~s names ~s, which module ~s does not declare",
                                                      [Name, Key, Mod])
                      end
              end, Named),
    Tables = maps:get(tables, P),
    Mismatch = fun(Fmt, Args) ->
                       gt_pack:load_error('key-type-mismatch', "pack ~s " ++ Fmt, [Name | Args])
               end,
    %% a list key with `=` in a `requires` term (0.20, ruling 19)
    lists:foreach(
      fun({Key, list, requires_eq}) ->
              gt_pack:load_error('bad-directive', "pack ~s requires ~s with = and it is a list",
                                 [Name, Key]);
         (_) -> ok
      end, Typed),
    lists:foreach(
      fun({_Key, _Type, requires}) -> ok;
         ({_Key, _Type, requires_eq}) -> ok;
         ({_Key, list, list}) -> ok;
         ({Key, Type, list}) ->
              Mismatch("maps the group ~s, which is a key of type ~s, not a list", [Key, Type]);
         ({Key, list, {field, _, _}}) ->
              Mismatch("maps ~s with a field line, and it is a list", [Key]);
         ({Key, list, default}) ->
              Mismatch("has a default for ~s, and it is a list", [Key]);
         ({_Key, _Type, default}) -> ok;        % the value is read below
         ({Key, Type, {field, Tr, none}}) ->
              case gt_pack:yields(Tr) of
                  Type -> ok;
                  Got -> Mismatch("maps ~s (declared ~s) through a transform that yields ~s",
                                  [Key, Type, Got])
              end;
         ({Key, Type, {field, _Tr, Via}}) ->
              %% with a value table, the key's type is compared with the
              %% type of the table's model side; an all-integer table on a
              %% float key is accepted
              case maps:get(type, maps:get(Via, Tables)) of
                  Type -> ok;
                  int when Type =:= float -> ok;
                  Got -> Mismatch("maps ~s (declared ~s) through table ~s, whose model side is ~s",
                                  [Key, Type, Via, Got])
              end
      end, Typed),
    KeyTypes = maps:from_list([{Key, Type} || {Key, Type, _} <- Typed]),
    %% a default is read as its key's declared type
    TypeDefaults =
        fun(Pairs) ->
                maps:from_list(
                  lists:reverse(      % the first default line of a key is used
                    [try {Key, gt_num:read_as(maps:get(Key, KeyTypes), Val)}
                     catch _:_ ->
                         Mismatch("has the default ~s for ~s, which is not of type ~s",
                                  [Val, Key, maps:get(Key, KeyTypes)])
                     end || {Key, Val} <- Pairs]))
        end,
    CommonDefaults = TypeDefaults(maps:get(defaults, P)),
    %% a kind's default is used for common and kind fields alike; a default
    %% of a group body applies to its items only
    Ctx = {TypeDefaults, KeyTypes},
    Wire = maps:get(wire, P),
    Kinds = [K#{defaults := maps:merge(CommonDefaults, TypeDefaults(maps:get(defaults, K))),
                requires := [canon_term(T, KeyTypes) || T <- maps:get(requires, K)],
                lines := plan_bodies(Wire, type_groups(maps:get(lines, K), Ctx))}
             || K <- maps:get(kinds, P)],
    Common = plan_bodies(Wire, type_groups(maps:get(common, P), Ctx)),
    %% the `requires =` and `case` values, in line order: each line's types,
    %% then its duplicates (0.20, ruling 19)
    value_checks(maps:get(vchecks, P, []), KeyTypes, Mismatch),
    %% the typemap by either side; of two entries with one value the first is used
    Typemap = maps:get(typemap, P),
    %% kept for the life of the instance (ruling 1a of 0.25): each kind's
    %% scope (the common lines, then the kind's) and what the wire computes
    %% from a scope's lines alone (scope_plan/2), so that no conversion
    %% computes them again
    Kinds1 = [begin
                  Scope = Common ++ Ls,
                  K#{scope => Scope, plan => scope_plan(Wire, Scope)}
              end || #{lines := Ls} = K <- Kinds],
    P1 = gt_pack:index(P#{defaults := CommonDefaults, kinds := Kinds1, key_types => KeyTypes,
                          typemap_dec => maps:from_list(lists:reverse(Typemap)),
                          typemap_enc => maps:from_list([{C, N} || {N, C} <- lists:reverse(Typemap)]),
                          common := Common, plan => scope_plan(Wire, Common)}),
    %% last: a format name already loaded, compared byte for byte; the first
    %% pack stays loaded (ruling 5 of 0.11)
    case maps:is_key(Name, Packs) of
        true -> gt_pack:load_error('duplicate-format', "format ~s is already loaded", [Name]);
        false -> ok
    end,
    Engine#{packs := maps:put(Name, P1, Packs)}.

%% A value of a `requires =` term or a `case` read as the key's type
%% -> its canonical text (ruling 1 of 0.20); raises when it cannot be read.
canon_value(float, Text) ->
    %% `-?digits[.digits]` and an optional exponent, as a JSON number (ruling 24)
    true = float_value_text(Text),
    gt_num:canon(gt_num:read_as(float, Text));
canon_value(Type, Text) -> gt_num:canon(gt_num:read_as(Type, Text)).

float_value_text(<<$-, R/binary>>) -> json_int_part(R);
float_value_text(R) -> json_int_part(R).

json_int_part(B) ->
    case take_ds(B) of
        {<<>>, _} -> false;
        {_, <<$., R/binary>>} ->
            case take_ds(R) of
                {<<>>, _} -> false;
                {_, R2} -> json_exp_part(R2)
            end;
        {_, R} -> json_exp_part(R)
    end.

json_exp_part(<<>>) -> true;
json_exp_part(<<E, R/binary>>) when E =:= $e; E =:= $E ->
    R1 = case R of
             <<S, T/binary>> when S =:= $+; S =:= $- -> T;
             _ -> R
         end,
    case take_ds(R1) of
        {D, <<>>} when D =/= <<>> -> true;
        _ -> false
    end;
json_exp_part(_) -> false.

take_ds(B) -> take_ds(B, 0).
take_ds(B, N) ->
    case B of
        <<_:N/binary, C, _/binary>> when C >= $0, C =< $9 -> take_ds(B, N + 1);
        <<D:N/binary, R/binary>> -> {D, R}
    end.

%% A `requires` term with its values as canonical text; a value that cannot
%% be read keeps its text (value_checks/3 has refused it).
canon_term({K, Vals}, KeyTypes) ->
    Type = maps:get(K, KeyTypes, string),
    {K, [try canon_value(Type, V) catch _:_ -> V end || V <- Vals]};
canon_term(K, _KeyTypes) -> K.

value_checks(Checks, KeyTypes, Mismatch) ->
    Read = fun(Key, V) ->
                   Type = maps:get(Key, KeyTypes),
                   try canon_value(Type, V)
                   catch _:_ ->
                       Mismatch("lists the value ~s for ~s, which is not of type ~s", [V, Key, Type])
                   end
           end,
    lists:foldl(
      fun({req, Key, Vals}, Seen) -> [Read(Key, V) || V <- Vals], Seen;
         ({'case', Ref, Key, Vals}, Seen) ->
              Canon = [Read(Key, V) || V <- Vals],
              Before = maps:get(Ref, Seen, []),
              case length(lists:usort(Canon)) =:= length(Canon) andalso
                  not lists:any(fun(C) -> lists:member(C, Before) end, Canon) of
                  true -> ok;
                  false -> gt_pack:load_error('bad-directive',
                                              "switch ~s lists a case value twice", [Key])
              end,
              Seen#{Ref => Canon ++ Before}
      end, #{}, Checks),
    ok.

%% The defaults of every group body, read as their keys' types; the values
%% of every switch case as canonical text, and the requires of item kinds.
type_groups(Lines, {TypeDefaults, KeyTypes} = Ctx) ->
    [case L of
         {group, List, Loc, Spec, #{lines := Ls, defaults := Ds}, LocT} ->
             {group, List, Loc, Spec,
              #{lines => type_groups(Ls, Ctx), defaults => TypeDefaults(Ds)}, LocT};
         %% sequential: a kind of a group body has the body's defaults and its own
         {sgroup, List, Mode, #{lines := Ls, defaults := Ds, kinds := Ks}} ->
             Common = TypeDefaults(Ds),
             {sgroup, List, Mode,
              #{lines => type_groups(Ls, Ctx), defaults => Common,
                kinds => [K#{lines := type_groups(maps:get(lines, K), Ctx),
                             requires := [canon_term(T, KeyTypes) || T <- maps:get(requires, K)],
                             defaults := maps:merge(Common, TypeDefaults(maps:get(defaults, K)))}
                          || K <- Ks]}};
         {gate, Loc, Neg, Vals, #{lines := Ls, defaults := Ds}, LocT} ->
             {gate, Loc, Neg, Vals,
              #{lines => type_groups(Ls, Ctx), defaults => TypeDefaults(Ds)}, LocT};
         {ifb, Conds, Body} -> {ifb, Conds, type_groups(Body, Ctx)};
         {opt, Body} -> {opt, type_groups(Body, Ctx)};
         {uext, Body} -> {uext, type_groups(Body, Ctx)};
         {uchoice, N, Ext, Alts} ->
             {uchoice, N, Ext, [{I, type_groups(B, Ctx)} || {I, B} <- Alts]};
         {len, Len, Unit, Plus, Body} -> {len, Len, Unit, Plus, type_groups(Body, Ctx)};
         {chain, First, Parts, EndsFx} ->
             {chain, type_groups(First, Ctx),
              [type_groups(Part, Ctx) || Part <- Parts], EndsFx};
         {switch, Key, Ref, Cases, Else} ->
             Type = maps:get(Key, KeyTypes, string),
             Case = fun(#{vals := Vals, lines := Ls, defaults := Ds} = C) ->
                            C#{vals := [try canon_value(Type, V) catch _:_ -> V end || V <- Vals],
                               lines := type_groups(Ls, Ctx),
                               defaults := TypeDefaults(Ds)}
                    end,
             {switch, Key, Ref, [Case(C) || C <- Cases],
              case Else of
                  none -> none;
                  _ -> Case(Else)
              end};
         _ -> L
     end || L <- Lines].

%% `public` is below `controlled`: a public-only engine refuses controlled.
within_limit(#{max_distribution := public}, What, Name, #{distribution := controlled}) ->
    gt_pack:load_error('distribution-refused',
                       "~s ~s is controlled and the engine's limit is public", [What, Name]);
within_limit(_Engine, _What, _Name, _Item) -> ok.

%% <<"lat">> -> {<<"core">>, <<"lat">>};
%% <<"track.confidence">> -> {<<"track">>, <<"confidence">>}.
%% The text before the first `.` is the module name.
split_key(Key) ->
    case binary:split(Key, <<".">>) of
        [Name] -> {<<"core">>, Name};
        [Mod, Name] -> {Mod, Name}
    end.

%% Directory loader: model/*.def in byte order of file name, then every pack
%% directory under PacksDir. The model directory defaults to the one beside
%% PacksDir.
load_dir(Engine, PacksDir) ->
    load_dir(Engine, PacksDir, filename:join([PacksDir, "..", "model"])).

load_dir(Engine, PacksDir, ModelsDir) ->
    E1 = lists:foldl(fun({_F, Bin}, E) -> load_model(E, Bin) end,
                     Engine, model_texts(ModelsDir)),
    {ok, Entries} = file:list_dir(PacksDir),
    lists:foldl(
      fun(Entry, E) ->
              Def = filename:join([PacksDir, Entry, "pack.def"]),
              case filelib:is_file(Def) of
                  true ->
                      {ok, Bin} = file:read_file(Def),
                      load_pack(E, Bin);
                  false -> E
              end
      end, E1, lists:sort(Entries)).

%% Named loader: only the packs named, each from PacksDir/<name>/pack.def,
%% with the modules they need: `core`, the modules of their `uses` lines and
%% the modules those use, each loaded once and after the modules it uses. A
%% module the engine already holds is not loaded again. Names are pack
%% directory names (binaries or strings), loaded in the order given. The
%% model directory defaults to the one beside PacksDir. A name with no
%% pack.def is `unknown-format`; a module with no file in ModelsDir is
%% `unknown-module`.
load_packs(Engine, PacksDir, Names) ->
    load_packs(Engine, PacksDir, Names, filename:join([PacksDir, "..", "model"])).

load_packs(#{modules := Loaded} = Engine, PacksDir, Names, ModelsDir) ->
    Texts = [begin
                 Def = filename:join([PacksDir, N, "pack.def"]),
                 case file:read_file(Def) of
                     {ok, Bin} -> Bin;
                     {error, _} ->
                         gt_pack:load_error('unknown-format',
                                            "no pack.def for ~s in the packs directory", [N])
                 end
             end || N <- Names],
    Wanted = [<<"core">> | [U || T <- Texts, U <- uses_lines(T)]],
    %% each module file is read once (ruling 1d of 0.25): its head and its
    %% text come from that one read
    Heads = model_entries(ModelsDir),
    ByName = maps:from_list([{Name, Us} || {_, {Name, Us}, _} <- Heads]),
    Needed = needed_modules(Wanted, ByName, Loaded, #{}),
    %% model_entries/1 already puts every module after those it uses
    E1 = lists:foldl(
           fun({_F, {Name, _}, Bin}, E) ->
                   case maps:is_key(Name, Needed) of
                       true -> load_model(E, Bin);
                       false -> E
                   end
           end, Engine, Heads),
    lists:foldl(fun(T, E) -> load_pack(E, T) end, E1, Texts).

%% Loaders with a licence profile (Version 0.29): Profile is `none` (load
%% as load_dir/3 and load_packs/4, reading no licence file), or one of
%% open, open+copyleft, everything (an atom, a string or a binary). Any
%% other value is bad-licence before anything is read. The licence table
%% is the PacksDir text followed by /../licences.toml.
load_dir(Engine, PacksDir, ModelsDir, none) -> load_dir(Engine, PacksDir, ModelsDir);
load_dir(Engine, PacksDir, ModelsDir, Profile) ->
    {Ctx, Files} = licence_start(PacksDir, ModelsDir, Profile),
    E1 = lists:foldl(fun({_F, _, Bin}, E) -> load_model(E, Bin) end, Engine, model_order(Files)),
    {ok, Entries} = file:list_dir(PacksDir),
    lists:foldl(
      fun(Entry, E) ->
              Dir = filename:join(PacksDir, Entry),
              Def = filename:join(Dir, "pack.def"),
              case filelib:is_file(Def) of
                  true ->
                      Text = file:read_file(Def),
                      {_Lic, Rank} = gt_licence:pack(Ctx, Dir, Text),
                      case gt_licence:held(Ctx, Rank) of
                          true -> {ok, Bin} = Text, load_pack(E, Bin);
                          false -> E
                      end;
                  false -> E
              end
      end, E1, lists:sort(Entries)).

load_packs(Engine, PacksDir, Names, ModelsDir, none) ->
    load_packs(Engine, PacksDir, Names, ModelsDir);
load_packs(#{modules := Loaded} = Engine, PacksDir, Names, ModelsDir, Profile) ->
    {Ctx, Files} = licence_start(PacksDir, ModelsDir, Profile),
    Texts = lists:append(
              [begin
                   Dir = filename:join(PacksDir, N),
                   case file:read_file(filename:join(Dir, "pack.def")) of
                       {ok, Bin} ->
                           {_Lic, Rank} = gt_licence:pack(Ctx, Dir, {ok, Bin}),
                           case gt_licence:held(Ctx, Rank) of
                               true -> [Bin];
                               false -> []
                           end;
                       {error, _} ->
                           gt_pack:load_error('unknown-format',
                                              "no pack.def for ~s in the packs directory", [N])
                   end
               end || N <- Names]),
    Wanted = case Texts of
                 [] -> [];
                 _ -> [<<"core">> | [U || T <- Texts, U <- uses_lines(T)]]
             end,
    Heads = model_order(Files),
    ByName = maps:from_list([{Name, Us} || {_, {Name, Us}, _} <- Heads]),
    Needed = needed_modules(Wanted, ByName, Loaded, #{}),
    E1 = lists:foldl(
           fun({_F, {Name, _}, Bin}, E) ->
                   case maps:is_key(Name, Needed) of
                       true -> load_model(E, Bin);
                       false -> E
                   end
           end, Engine, Heads),
    lists:foldl(fun(T, E) -> load_pack(E, T) end, E1, Texts).

%% The profile checked, the licence table and every module file's licence
%% read (ruling 3b) -> {Ctx, the module files the profile holds}.
licence_start(PacksDir, ModelsDir, Profile) ->
    Rank = case gt_licence:profile(Profile) of
               {ok, R} -> R;
               error -> gt_pack:load_error('bad-licence',
                                           "~p is not a profile (open, open+copyleft, everything)",
                                           [Profile])
           end,
    Read = model_read(ModelsDir),
    Ctx = gt_licence:start(licences_path(PacksDir), ModelsDir, Rank, Read),
    {Ctx, held_files(Ctx, Read)}.

%% The --packs text as given, followed by /../licences.toml.
licences_path(PacksDir) when is_binary(PacksDir) -> <<PacksDir/binary, "/../licences.toml">>;
licences_path(PacksDir) -> PacksDir ++ "/../licences.toml".

%% The module files whose profile the asked profile holds (ruling 3c).
held_files(Ctx, Read) ->
    Files = maps:get(files, Ctx),
    [FR || {F, _} = FR <- Read, gt_licence:held(Ctx, maps:get(F, Files))].

uses_lines(Text) ->
    [U || L <- binary:split(Text, <<"\n">>, [global]),
          [<<"uses">>, U] <- [gt_pack:tokens_lax(L)]].

%% The modules to load for a set of names: those names and what they use,
%% less what the engine holds.
needed_modules([], _ByName, _Loaded, Acc) -> Acc;
needed_modules([N | Rest], ByName, Loaded, Acc) ->
    case maps:is_key(N, Acc) orelse maps:is_key(N, Loaded) of
        true -> needed_modules(Rest, ByName, Loaded, Acc);
        false ->
            case maps:find(N, ByName) of
                {ok, Us} -> needed_modules(Us ++ Rest, ByName, Loaded, Acc#{N => true});
                error ->
                    gt_pack:load_error('unknown-module',
                                       "module ~s has no file in the model directory", [N])
            end
    end.

%% The module files of a directory: `core.def` first, whatever its name
%% sorts as, then the others in byte order of file name, each after the
%% modules its `uses` lines name. A cycle is bad-directive.
model_files(ModelsDir) -> [F || {F, _, _} <- model_entries(ModelsDir)].

%% The same files with their texts, in the same order -> [{File, Text}]. Each
%% file is read once (ruling 1d of 0.25); a loader loads these texts and
%% does not read the files again.
model_texts(ModelsDir) -> [{F, Bin} || {F, _, Bin} <- model_entries(ModelsDir)].

%% -> [{File, {ModuleName, [UsesName]}, Text}] in the order of model_files/1.
model_entries(ModelsDir) -> model_order(model_read(ModelsDir)).

%% The module files of a directory, each read once, before any is ordered by
%% its `uses`: `core.def` first, then the other names ending in `.def` in
%% byte order, each a regular file or a symbolic link to one (Version 0.23,
%% Loading, 1) -> [{File, {ok, Text} | {error, Reason}}]. A directory that
%% cannot be listed holds no module.
model_read(ModelsDir) ->
    case file:list_dir(ModelsDir) of
        {ok, Files} ->
            Defs = [F || F <- lists:sort(Files), lists:suffix(".def", F),
                         filelib:is_regular(filename:join(ModelsDir, F))],
            Ordered = [F || F <- Defs, F =:= "core.def"] ++ [F || F <- Defs, F =/= "core.def"],
            [{F, file:read_file(filename:join(ModelsDir, F))} || F <- Ordered];
        {error, _} -> []
    end.

%% The files of model_read/1, each placed after the modules it uses.
model_order(Files) ->
    Ordered = [F || {F, _} <- Files],
    Read = [begin
                {ok, Bin} = R,
                {F, module_head(Bin), Bin}
            end || {F, R} <- Files],
    ByName = maps:from_list([{Name, F} || {F, {Name, _}, _} <- Read]),
    Uses = maps:from_list([{F, [maps:get(U, ByName) || U <- Us, maps:is_key(U, ByName)]}
                           || {F, {_, Us}, _} <- Read]),
    {Out, _} = lists:foldl(fun(F, Acc) -> place_module(F, Uses, [], Acc) end,
                           {[], #{}}, Ordered),
    ByFile = maps:from_list([{F, E} || {F, _, _} = E <- Read]),
    [maps:get(F, ByFile) || F <- lists:reverse(Out)].

%% The module name and the `uses` names of a module text. Only a line that
%% holds `module` or `uses` can tokenise to either, so only those lines are
%% cut out of the text (each once, in text order).
module_head(Bin) ->
    Starts = line_starts(Bin, [P || {P, _} <- binary:matches(Bin, [<<"module">>, <<"uses">>])],
                         -1),
    Toks = [gt_pack:tokens_lax(line_at(Bin, S)) || S <- Starts],
    {case [N || [<<"module">>, N] <- Toks] of
         [N | _] -> N;
         [] -> undefined
     end,
     [U || [<<"uses">>, U] <- Toks]}.

%% The start of the line of each position, ascending, each line once.
line_starts(_Bin, [], _Last) -> [];
line_starts(Bin, [P | Rest], Last) ->
    case line_start(Bin, P) of
        Last -> line_starts(Bin, Rest, Last);
        S -> [S | line_starts(Bin, Rest, S)]
    end.

line_start(_Bin, 0) -> 0;
line_start(Bin, P) ->
    case binary:at(Bin, P - 1) of
        $\n -> P;
        _ -> line_start(Bin, P - 1)
    end.

%% The line that starts at S, without its line feed.
line_at(Bin, S) ->
    End = case binary:match(Bin, <<"\n">>, [{scope, {S, byte_size(Bin) - S}}]) of
              {E, _} -> E;
              nomatch -> byte_size(Bin)
          end,
    binary:part(Bin, S, End - S).

place_module(F, Uses, Path, {Out, Done} = Acc) ->
    case maps:is_key(F, Done) of
        true -> Acc;
        false ->
            case lists:member(F, Path) of
                true -> gt_pack:load_error('bad-directive',
                                           "the modules of ~s use one another in a cycle", [F]);
                false -> ok
            end,
            {Out1, Done1} = lists:foldl(fun(U, A) -> place_module(U, Uses, [F | Path], A) end,
                                        {Out, Done}, maps:get(F, Uses)),
            {[F | Out1], Done1#{F => true}}
    end.

%% ===================================================================
%% errors
%% ===================================================================
conv_error(Kind, #{name := Name}, Fmt, Args) ->
    conv_error(Kind, "format ~s: " ++ Fmt, [Name | Args]).

conv_error(Kind, Fmt, Args) ->
    Msg = lists:flatten(io_lib:format("~s: " ++ Fmt, [Kind | Args])),
    erlang:error({convert_error, Kind, Msg}).

%% ===================================================================
%% convert, complete
%% ===================================================================
%% convert(Engine, From, To, Bytes [, Context]); From and To are format
%% names. Context is the caller-supplied keys: a map or a list of
%% {Key, Value}, values in string form (or already typed).
%%   1. decode; clear the recorded kind unless From == To
%%   2. fill absent keys from the context
%%   3. apply the derivations
%%   4. encode
%% When From == To and no context is given, steps 2 and 3 are skipped.
convert(Engine, From, To, Bytes) -> convert(Engine, From, To, Bytes, none).

convert(Engine, From, To, Bytes, Context) ->
    FromPack = pack(Engine, From),
    ToPack = pack(Engine, To),
    Entity = decode(FromPack, Bytes),
    Same = From =:= To,
    Entity1 = case Same of
                  true -> Entity;
                  false -> Entity#{kind := undefined}
              end,
    %% What a decoded message cannot be written as is a named error too: a
    %% failure no encoder names is `transform-encode`, marked ?UNCLASSIFIED.
    try
        Entity2 = case Same andalso Context =:= none of
                      true -> Entity1;
                      false -> complete(Engine, Entity1, Context)
                  end,
        encode(ToPack, Entity2)
    catch
        error:{convert_error, _, _} = Named:Stack -> erlang:raise(error, Named, Stack);
        Class:Reason ->
            conv_error('transform-encode', ToPack, "the entity cannot be written ~s ~0P]",
                       [?UNCLASSIFIED, {Class, Reason}, 8])
    end.

%% The step between decode and encode on its own: absent keys filled from
%% the context, then the derivations.
complete(Engine, Entity) -> complete(Engine, Entity, none).

complete(#{derives := Derives} = Engine, #{model := Model} = Entity, Context) ->
    Supplied = context(Engine, Context),
    Model1 = lists:foldl(fun({K, V}, M) ->
                                 case maps:is_key(K, M) of
                                     true -> M;
                                     false -> M#{K => V}
                                 end
                         end, Model, Supplied),
    Entity#{model := gt_derive:apply_all(Derives, Model1)}.

%% Every context key must be declared by a loaded module and hold its
%% declared type -> [{Key, TypedValue}].
context(_Engine, none) -> [];
context(Engine, Context) when is_map(Context) -> context(Engine, maps:to_list(Context));
context(#{modules := Modules}, Pairs) when is_list(Pairs) ->
    [begin
         {Mod, Name} = split_key(Key),
         Type = case maps:find(Mod, Modules) of
                    {ok, M} ->
                        case gt_model:key_type(M, Name) of
                            {ok, T} -> T;
                            error -> undeclared
                        end;
                    error -> undeclared
                end,
         case Type of
             undeclared ->
                 conv_error('undeclared-key',
                            "context key ~s is declared by no loaded module", [Key]);
             _ -> ok
         end,
         try {Key, context_value(Type, Val)}
         catch _:_ ->
             conv_error('key-type-mismatch',
                        "context key ~s is declared ~s and its value cannot be read as one",
                        [Key, Type])
         end
     end || {Key, Val} <- Pairs].

context_value(Type, Val) when is_binary(Val) -> gt_num:read_as(Type, Val);
context_value(Type, Val) when is_list(Val) -> gt_num:read_as(Type, list_to_binary(Val));
context_value(int, Val) when is_integer(Val) -> Val;
context_value(float, Val) when is_float(Val) -> Val.

%% ===================================================================
%% kind selection
%% ===================================================================
%% Decode: every common `when` must hold; then the first kind, in pack
%% order, whose every `when` holds. On xml a kind is considered only when
%% the document's root element has the kind's root name.
%% -> {KindName | undefined, Lines, Plan}: the scope and its plan, both
%% kept since load (ruling 1a of 0.25)
select_decode(#{has_kinds := false, common := Common, plan := Plan}, _Wire, _Ctx) ->
    {undefined, Common, Plan};
select_decode(#{common := Common} = Pack, Wire, Ctx) ->
    Holds = fun(Ls) ->
                    lists:all(fun({wh, Loc, Val, _}) -> when_holds(Wire, Ctx, Loc, Val);
                                 (_) -> true
                              end, Ls)
            end,
    case Holds(Common) of
        true -> ok;
        false -> conv_error('no-kind', Pack, "a common when does not hold", [])
    end,
    Candidates = case Wire of
                     xml -> ?XML(maps:get(gt_xml:name(Ctx), maps:get(root_index, Pack), []));
                     _ -> maps:get(kinds, Pack)
                 end,
    case first_kind(Candidates, fun(#{lines := Ls}) -> Holds(Ls) end) of
        none -> conv_error('no-kind', Pack, "no kind's root and when lines hold for this message", []);
        #{name := Name, scope := Scope, plan := Plan} -> {Name, Scope, Plan}
    end.

%% Encode: the entity's recorded kind when it names this format, else the
%% first kind, in pack order, whose every `requires` key the entity has.
%% -> {Lines, Defaults, Root, Plan}
select_encode(#{has_kinds := false, common := Common, defaults := Defaults, root := Root,
                plan := Plan}, _Entity) ->
    {Common, Defaults, Root, Plan};
select_encode(#{name := Name, kinds := Kinds, root := PackRoot} = Pack, Entity) ->
    Model = maps:get(model, Entity),
    Lists = maps:get(lists, Entity, #{}),
    Has = fun(T) -> req_holds(T, Model, Lists) end,
    Chosen =
        case maps:get(kind, Entity, undefined) of
            {Name, KindName} ->
                maps:get(KindName, maps:get(kind_index, Pack), none);
            _ ->
                first_kind(Kinds, fun(#{requires := Req}) -> lists:all(Has, Req) end)
        end,
    case Chosen of
        none -> conv_error('no-kind', Pack, "the entity selects no kind of the pack", []);
        #{scope := Scope, defaults := Defaults, root := Root, plan := Plan} ->
            {Scope, Defaults, case Root of undefined -> PackRoot; _ -> Root end, Plan}
    end.

%% Does a scope hold a `requires` term? A plain key: the key is present, or
%% the list is present with at least one item. `<key>=<values>` (0.20): the
%% key is present and its canonical text is one of the values.
req_holds({K, Canon}, Model, _Lists) ->
    case maps:find(K, Model) of
        {ok, V} -> lists:member(gt_num:canon(V), Canon);
        error -> false
    end;
req_holds(K, Model, Lists) ->
    maps:is_key(K, Model) orelse
        case maps:find(K, Lists) of
            {ok, [_ | _]} -> true;
            _ -> false
        end.

first_kind([], _Pred) -> none;
first_kind([K | Rest], Pred) ->
    case Pred(K) of
        true -> K;
        false -> first_kind(Rest, Pred)
    end.

%% ===================================================================
%% decode
%% ===================================================================
decode(Engine, Format, Bytes) -> decode(pack(Engine, Format), Bytes).

%% No input makes a decode fail with anything but a conversion error
%% (Malformed input, 0.8): what a reader raises for an input that is not a
%% well-formed message of its wire is `malformed-wire`. A failure no reader
%% names is `malformed-wire` too, its message marked ?UNCLASSIFIED: the
%% conformance runner counts such a message as a defect of the engine.
decode(Pack, Bytes) when is_list(Bytes) -> decode(Pack, iolist_to_binary(Bytes));
decode(Pack, Bytes) when is_binary(Bytes) ->
    %% the limit on list items (ruling 7 of 0.11) and the first field
    %% failure, which is raised when the decode ends or fails otherwise, so
    %% that going over the limit wins over it (7f)
    put(?ITEMS, {maps:get(max_items, Pack, ?DEFAULT_MAX_ITEMS), 0}),
    erase(?OVER),
    erase(?FAILED),
    try decode_checked(Pack, Bytes)
    after
        erase(?ITEMS),
        erase(?OVER),
        erase(?FAILED)
    end.

decode_checked(Pack, Bytes) ->
    try decode_wire(Pack, Bytes) of
        Entity ->
            case get(?FAILED) of
                undefined -> Entity;
                Msg -> erlang:error({convert_error, 'transform-decode', Msg})
            end
    catch
        error:{convert_error, _, _} = Named:Stack ->
            case {get(?OVER), get(?FAILED)} of
                {true, _} -> erlang:raise(error, Named, Stack);
                {_, undefined} -> erlang:raise(error, Named, Stack);
                {_, Msg} -> erlang:error({convert_error, 'transform-decode', Msg})
            end;
        Class:Reason:Stack ->
            case {get(?OVER), get(?FAILED)} of
                {undefined, Msg} when Msg =/= undefined ->
                    erlang:error({convert_error, 'transform-decode', Msg});
                _ -> decode_failure(Pack, Class, Reason, Stack)
            end
    end.

decode_failure(Pack, Class, Reason, Stack) ->
    try erlang:raise(Class, Reason, Stack)
    catch
        error:{protobuf_malformed, Why} ->
            conv_error('malformed-wire', Pack, "protobuf: ~0p", [Why]);
        error:{json_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not json: ~0p", [Why]);
        error:{xml_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not well-formed xml: ~0p", [Why]);
        error:{hex_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not hex text of even length: ~0p", [Why]);
        Class2:Reason2 ->
            conv_error('malformed-wire', Pack, "the input cannot be read ~s ~0P]",
                       [?UNCLASSIFIED, {Class2, Reason2}, 8])
    end.

%% Take N items of the limit; one more than it allows is malformed-wire.
items_reserve(N, Pack) ->
    {Limit, Count} = get(?ITEMS),
    case Count + N > Limit of
        true ->
            put(?OVER, true),
            conv_error('malformed-wire', Pack, "the message holds more than ~p list items", [Limit]);
        false -> put(?ITEMS, {Limit, Count + N})
    end.

%% Give back the items of a list a later group replaces (ruling 7g of 0.11).
items_release(N) ->
    {Limit, Count} = get(?ITEMS),
    put(?ITEMS, {Limit, Count - N}).

%% The number of items a list holds, at every nesting level.
items_held(Items) ->
    lists:sum([1 + lists:sum([items_held(L) || L <- maps:values(maps:get(lists, I, #{}))])
               || I <- Items]).

%% A field failure whose message is formed: kept when it is the first.
record_failure_msg(Msg) ->
    case get(?FAILED) of
        undefined -> put(?FAILED, Msg);
        _ -> ok
    end.

%% A field failure of the decode: the first is kept and raised at the end.
record_failure(Pack, Fmt, Args) ->
    case get(?FAILED) of
        undefined ->
            #{name := Name} = Pack,
            Msg = lists:flatten(io_lib:format("~s: format ~s: " ++ Fmt,
                                              ['transform-decode', Name | Args])),
            put(?FAILED, Msg);
        _ -> ok
    end.

decode_wire(#{wire := bits, layout := sequential} = Pack, Bytes) -> ?BITS(gt_seq:decode(Pack, Bytes));
decode_wire(#{wire := tlv} = Pack, Bytes) -> ?TLV(gt_tlv:decode(Pack, Bytes));
decode_wire(#{wire := Wire} = Pack, Bytes) ->
    Ctx = open(Wire, Pack, Bytes),
    {Kind, Lines0, Plan} = select_decode(Pack, Wire, Ctx),
    Lines = held_lines(Wire, Ctx, Lines0),
    fit(Wire, Pack, Ctx, static_end(Wire, Lines)),
    {Model, Lists, End} = decode_scope(Wire, Ctx, Lines, Pack),
    fit(Wire, Pack, Ctx, End),             % the items extend the message
    #{model => Model,
      lists => Lists,
      residue => residue(Wire, Ctx, Lines, Plan, Bytes),
      src => maps:get(name, Pack),
      kind => case Kind of
                  undefined -> undefined;
                  _ -> {maps:get(name, Pack), Kind}
              end}.

%% The lines of one scope (the message, or one item of a group) read from
%% its place on the wire -> {Model, Lists, End}. End is, on bits, the
%% furthest bit the scope's groups reach; 0 on the other wires.
%% A key mapped by several lines takes its value from the earliest line
%% whose locator is present and whose transform succeeds; a line whose
%% transform fails is an error only when no line of its key succeeds. A line
%% whose transform succeeds and whose table has no entry for a value of
%% another type fails the decode.
decode_scope(Wire, Ctx, Lines, Pack) ->
    {Model, Lists, Failed, _Cache, End} =
        lists:foldl(
          fun({field, Key, Loc, Tr, LocT, Opts}, {M, Ls, F, C, E} = Acc) ->
                  case maps:is_key(Key, M) of
                      true -> Acc;
                      false ->
                          case raw_tr(Wire, Ctx, Loc, Tr, Opts, C) of
                              {absent, C1} -> {M, Ls, F, C1, E};
                              {{ok, Raw}, C1} ->
                                  %% a sentinel: the line yields no value and
                                  %% the next line of the key is read
                                  case is_sentinel(Wire, Tr, Raw, element(5, Opts)) of
                                      true -> {M, Ls, F, C1, E};
                                      false ->
                                          try field_decode(Wire, Tr, Raw, Loc, Opts, Pack) of
                                              V0 ->
                                                  V1 = via_decode(Opts, V0, Tr, Key, LocT, Pack),
                                                  {M#{Key => typemap_decode(Key, V1, Pack)}, Ls, F, C1, E}
                                          catch
                                              _:_ -> {M, Ls, [{Key, LocT} | F], C1, E}
                                          end
                                  end
                          end
                  end;
             ({group, List, Loc, Spec, Body, _LocT}, {M, Ls, F, C, E}) ->
                  case decode_group(Wire, Ctx, Loc, Spec, Body, Pack, C) of
                      {absent, C1, E1} -> {M, Ls, F, C1, max(E, E1)};
                      {{ok, Items}, C1, E1} -> {M, Ls#{List => Items}, F, C1, max(E, E1)}
                  end;
             (_, Acc) -> Acc
          end, {#{}, #{}, [], #{}, 0}, Lines),
    case [KL || {K, _} = KL <- lists:reverse(Failed), not maps:is_key(K, Model)] of
        [] -> ok;
        Bad ->
            record_failure(Pack, "failed fields: ~s",
                           [lists:join(", ", [[K, " at ", L] || {K, L} <- Bad])])
    end,
    {Model, Lists, End}.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON orelse ?W_PROTOBUF orelse ?W_TEXT).
%% One item of a list, from its place on the wire.
decode_item(Wire, Ctx, #{lines := Lines}, Pack) ->
    {Model, Lists, _End} = decode_scope(Wire, Ctx, Lines, Pack),
    #{model => Model, lists => Lists}.
-endif.

%% ---- the items of a group -> {absent | {ok, [Item]}, Cache, End} ----
decode_group(text, Ctx, Start, Spec, Body, Pack, C) ->
    ?TEXT(text_group(Ctx, Start, Spec, Body, Pack, C));
decode_group(xml, Elem, Path, _Spec, Body, Pack, C) ->
    ?XML(xml_group(Elem, Path, Body, Pack, C));
decode_group(Wire, Json, Loc, _Spec, Body, Pack, C)
  when Wire =:= json; Wire =:= geojson; Wire =:= gjitem ->
    ?JSONTEXT(json_group(Wire, Json, Loc, Body, Pack, C));
decode_group(Wire, Msg, Path, _Spec, Body, Pack, C)
  when Wire =:= protobuf; Wire =:= pbitem ->
    ?PROTOBUF(pb_group_items(Msg, Path, Body, Pack, C));
decode_group(bits, Ctx, Start, Spec, Body, Pack, C) ->
    ?BITS(bits_group(Ctx, Start, Spec, Body, Pack, C)).

-if(?W_TEXT).
%% text: items of N fields from field Start to the end of the record.
text_group(Ctx, Start, {text_item, N}, Body, Pack, C) ->
    case gt_text:items(Ctx, Start, N) of
        absent -> {absent, C, 0};
        Items ->
            items_reserve(length(Items), Pack),
            {{ok, [decode_item(text, X, Body, Pack) || X <- Items]}, C, 0}
    end.
-endif.

%% xml: each child element named by the last name, under the first element
%% matched by the names before it; the list is present when an item occurs.
-if(?W_XML).
xml_group(Elem, Path, Body, Pack, C) ->
    Found = case navigate(Elem, lists:droplast(Path)) of
                absent -> [];
                {ok, Parent} -> gt_xml:children(Parent, lists:last(Path))
            end,
    case Found of
        [] -> {absent, C, 0};
        _ ->
            items_reserve(length(Found), Pack),
            {{ok, [decode_item(xml, E, Body, Pack) || E <- Found]}, C, 0}
    end.
-endif.

%% json, geojson: the member is an array and each element an item. `null` is
%% an absent list; another value is malformed-wire.
-if(?W_JSON orelse ?W_GEOJSON).
json_group(Wire, Json, Loc, Body, Pack, C) ->
    case member(Wire, Json, Loc) of
        absent -> {absent, C, 0};
        {ok, {array, Els}} ->
            items_reserve(length(Els), Pack),
            ItemWire = item_wire(Wire),
            {{ok, [decode_item(ItemWire, E, Body, Pack) || E <- Els]}, C, 0};
        {ok, _} ->
            conv_error('malformed-wire', Pack, "the member of a group is not an array", [])
    end.
-endif.

%% protobuf: each occurrence of the last field number, in wire order. A body
%% of `.` lines reads scalars, and a numeric transform accepts the packed
%% form; another body reads each occurrence as a submessage.
-if(?W_PROTOBUF).
pb_group_items(Msg, Path, #{lines := Lines} = Body, Pack, C) ->
    N = lists:last(Path),
    {Container, C1} = pb_sub(Msg, lists:droplast(Path), [], C),
    %% a path prefix that is not a submessage is malformed-wire (ruling 13 of 0.7)
    case Container of
        absent -> pb_prefix_check(lists:droplast(Path), C1);
        _ -> ok
    end,
    %% the occurrences of every field number of the container, indexed once
    %% however many groups read from it
    {Occs, C2} = case Container of
                     {ok, {_Map, Fields}} ->
                         Key = {occurrences, lists:droplast(Path)},
                         Index = case maps:find(Key, C1) of
                                     {ok, I} -> I;
                                     error ->
                                         lists:foldr(
                                           fun({Num, WT, V}, M) ->
                                                   maps:update_with(Num, fun(L) -> [{WT, V} | L] end,
                                                                    [{WT, V}], M)
                                           end, #{}, Fields)
                                 end,
                         {maps:get(N, Index, []), C1#{Key => Index}};
                     _ -> {[], C1}
                 end,
    Ctxs = case pb_scalar_body(Lines) of
               {true, Tr} ->
                   [{scalar, S} || Occ <- Occs, S <- pb_unpack(Tr, Occ)];
               false when Lines =:= [] -> [{#{}, []} || _ <- Occs];
               false ->
                   [case Occ of
                        {2, Bin} -> gt_protobuf:parse_msg(Bin);
                        _ -> conv_error('malformed-wire', Pack,
                                        "an item at ~w is not a submessage", [Path])
                    end || Occ <- Occs]
           end,
    case Ctxs of
        [] -> {absent, C2, 0};
        _ ->
            items_reserve(length(Ctxs), Pack),
            {{ok, [decode_item(pbitem, X, Body, Pack) || X <- Ctxs]}, C2, 0}
    end.
-endif.

%% bits: `count` consecutive items from the group's start; an item is
%% `item <bits>` long, or longer when a nested group counted by a locator
%% runs past that, and the next item starts where it ends.
-if(?W_BITS).
bits_group({Msg, Base}, Start, {ItemBits, Count}, #{lines := Lines}, Pack, C) ->
    N = case Count of
            {fixed, K} -> K;
            {loc, {CO, CL}} ->
                case gt_bits:read(Msg, Base + CO, CL) of
                    beyond -> conv_error('malformed-wire', Pack,
                                         "the input ends before the count of a group", []);
                    K -> K
                end
        end,
    %% a count is compared with the limit before any item is read (7d)
    items_reserve(N, Pack),
    {Items, End} = bits_items(N, Base + Start, Msg, ItemBits, Lines, Pack, []),
    {{ok, Items}, C, End}.

bits_items(0, Pos, _Msg, _ItemBits, _Lines, _Pack, Acc) -> {lists:reverse(Acc), Pos};
bits_items(N, Pos, Msg, ItemBits, Lines, Pack, Acc) ->
    case Pos + ItemBits =< gt_bits:bit_size(Msg) of
        true -> ok;
        false -> conv_error('malformed-wire', Pack, "the input ends before the counted items", [])
    end,
    {Model, Lists, End} = decode_scope(bits, {Msg, Pos}, held_lines(bits, {Msg, Pos}, Lines), Pack),
    bits_items(N - 1, max(Pos + ItemBits, End), Msg, ItemBits, Lines, Pack,
               [#{model => Model, lists => Lists} | Acc]).
-endif.

%% Gate blocks (0.17): the lines of a scope with each block that holds
%% replaced by its lines and each block that does not hold dropped, so that
%% a line of a block that does not hold is a line whose locator is absent.
%% A gate is read like a `when`: a gate any of whose bits lies beyond the
%% input does not hold, and neither does its `!` form.
held_lines(bits, Ctx, Lines) -> ?BITS(bits_held_lines(Ctx, Lines));
held_lines(_Wire, _Ctx, Lines) -> Lines.

-if(?W_BITS).
bits_held_lines({Msg, Base} = Ctx, Lines) ->
    lists:append(
      [case L of
           {gate, {Off, Len}, Neg, Vals, #{lines := Ls}, _} ->
               case gate_holds(gt_bits:read(Msg, Base + Off, Len), Neg, Vals) of
                   true -> bits_held_lines(Ctx, Ls);
                   false -> []
               end;
           _ -> [L]
       end || L <- Lines]).

gate_holds(beyond, _Neg, _Vals) -> false;
gate_holds(V, Neg, Vals) -> lists:member(V, Vals) =/= Neg.
-endif.

%% Inside a geojson item the json locators and `null` rule apply, with the
%% geojson value types.
-if(?W_JSON orelse ?W_GEOJSON).
item_wire(geojson) -> gjitem;
item_wire(Wire) -> Wire.
-endif.

-if(?W_PROTOBUF).
%% A group body made of `.` lines only reads scalar items
%% -> {true, TransformOfTheFirstLine} | false.
pb_scalar_body([{field, _, [], Tr, _, _} | Rest]) ->
    case lists:all(fun({field, _, [], _, _, _}) -> true; (_) -> false end, Rest) of
        true -> {true, Tr};
        false -> false
    end;
pb_scalar_body(_) -> false.

%% The scalars of one occurrence: a length-delimited occurrence of a numeric
%% field is the packed form, its values back to back.
pb_unpack(Tr, {2, Bin}) when Tr =:= pvarint; Tr =:= psint ->
    [{0, V} || V <- gt_protobuf:varints(Bin)];
pb_unpack(pdouble, {2, Bin}) ->
    case byte_size(Bin) rem 8 of
        0 -> [{1, B} || <<B:8/binary>> <= Bin];
        _ -> erlang:error({protobuf_malformed, packed_fixed64_length})
    end;
pb_unpack(pfloat, {2, Bin}) ->
    case byte_size(Bin) rem 4 of
        0 -> [{5, B} || <<B:4/binary>> <= Bin];
        _ -> erlang:error({protobuf_malformed, packed_fixed32_length})
    end;
pb_unpack(_Tr, Occ) -> [Occ].
-endif.

%% ---- open the wire ----
open(xml, Pack, Bytes) -> ?XML(xml_open(Pack, Bytes));
open(Wire, Pack, Bytes) when Wire =:= geojson; Wire =:= json ->
    ?JSONTEXT(json_open(Wire, Pack, Bytes));
open(text, Pack, Bytes) -> ?TEXT(gt_text:open(Pack, Bytes));
open(bits, Pack, Bytes) ->
    ?BITS({gt_bits:open(unwire(Pack, Bytes), maps:get(bit_order, Pack)), 0});
open(protobuf, Pack, Bytes) ->
    ?PROTOBUF(gt_protobuf:parse_msg(unhex(Pack, Bytes))).

-if(?W_XML).
xml_open(Pack, Bytes) ->
    Tree = gt_xml:parse(Bytes),
    case Pack of
        #{has_kinds := false, root := Root} ->
            case gt_xml:name(Tree) of
                Root -> Tree;
                Other ->
                    conv_error('missing-root', Pack,
                               "the pack's root is ~s and the document root is ~s", [Root, Other])
            end;
        _ -> Tree
    end.
-endif.

-if(?W_JSON orelse ?W_GEOJSON).
json_open(Wire, Pack, Bytes) ->
    Json = gt_json:parse(Bytes),
    case Json of
        {object, _} -> ok;
        _ -> conv_error('malformed-wire', Pack, "the input is not a json object", [])
    end,
    case Wire =:= json andalso gt_json:has_duplicate_member(Json) of
        true -> conv_error('malformed-wire', Pack,
                           "an object holds the same member name twice", []);
        false -> Json
    end.
-endif.

-if(?W_BITS).
%% The message of a bits pack: hex text, or under `armor sixbit` the six-bit
%% armored text, every character checked before any line is read (0.14).
unwire(#{armor := sixbit} = Pack, Text) ->
    try gt_bits:unarmor(Text)
    catch error:{armor_malformed, Why} ->
        conv_error('malformed-wire', Pack, "the input is not six-bit armored text: ~0p", [Why])
    end;
unwire(Pack, Bytes) -> unhex(Pack, Bytes).

%% The first L bits of a laid-out message as armored text (0.14).
armor_out(Bits, L, _Pack) -> gt_bits:armor(Bits, L).
-endif.

-if(?W_BITS orelse ?W_PROTOBUF orelse ?W_TLV).
%% The bytes of hex text (ruling 36 of 0.8).
unhex(Pack, Bytes) ->
    try gt_hex:hex_to_bytes(Bytes)
    catch error:{hex_malformed, Why} ->
        conv_error('malformed-wire', Pack, "the input is not hex text of even length: ~0p", [Why])
    end.
-endif.

%% ---- does a `when` hold? the value is compared with the raw wire value ----
when_holds(Wire, Ctx, Loc, {anyof, Items}) when Wire =/= bits, Wire =/= protobuf ->
    lists:any(fun(V) -> when_holds(Wire, Ctx, Loc, V) end, Items);
when_holds(xml, Tree, Loc, Val) -> ?XML(xml_when_holds(Tree, Loc, Val));
when_holds(Wire, Json, Loc, Val) when Wire =:= geojson; Wire =:= json ->
    ?JSONTEXT(json_when_holds(Wire, Json, Loc, Val));
when_holds(text, Ctx, Loc, Val) -> ?TEXT(gt_text:when_holds(Ctx, Loc, Val));
%% a `when` any of whose bits lies beyond the input does not hold
when_holds(bits, {Msg, Base}, {Off, Len}, Val) ->
    ?BITS(gt_pack:when_match(gt_bits:read(Msg, Base + Off, Len), Val));
when_holds(protobuf, Top, Path, Val) -> ?PROTOBUF(pb_when_holds(Top, Path, Val)).

-if(?W_XML).
%% `when <locator> present` on `#text` holds when the element exists
xml_when_holds(Tree, {Path, text}, present) -> navigate(Tree, Path) =/= absent;
xml_when_holds(Tree, Loc, present) -> xml_when(Tree, Loc) =/= absent;
xml_when_holds(Tree, Loc, {text, T, _}) -> xml_when(Tree, Loc) =:= {ok, T}.
-endif.

-if(?W_JSON orelse ?W_GEOJSON).
json_when_holds(Wire, Json, Loc, Val) ->
    case {member(Wire, Json, Loc), Val} of
        {absent, _} -> false;
        {{ok, _}, present} -> true;
        {{ok, V}, {text, T, _}} when is_binary(V) -> V =:= T;
        {{ok, V}, {text, T, _}} when not is_atom(V) ->
            %% a number by its canonical text; one with none holds no value
            gt_json:canonical_text(V) =:= T;
        {{ok, true}, {text, T, _}} -> T =:= <<"true">>;
        {{ok, false}, {text, T, _}} -> T =:= <<"false">>;
        _ -> false
    end.
-endif.

-if(?W_PROTOBUF).
%% A `when` path never fails a decode: a prefix whose bytes do not parse as
%% a message makes it not hold (ruling 9b of 0.11).
pb_when_holds(Top, Path, Val) ->
    {Found, _} = try pb_get(Top, Path, #{})
                 catch error:{protobuf_malformed, _} -> {absent, #{}}
                 end,
    case {Found, Val} of
        {absent, _} -> false;
        {{ok, _}, present} -> true;
        {{ok, {0, V}}, _} -> gt_pack:when_match(V, Val);
        _ -> false
    end.
-endif.

%% ---- the message must hold whole words up to a bit (bits) ----
fit(bits, Pack, Ctx, EndBit) -> ?BITS(bits_fit(Pack, Ctx, EndBit));
fit(_, _, _, _) -> ok.

-if(?W_BITS).
%% Under `armor sixbit` the message must only reach the bit (0.14).
bits_fit(#{armor := sixbit} = Pack, {Msg, _}, EndBit) ->
    case gt_bits:bit_size(Msg) >= EndBit of
        true -> ok;
        false -> conv_error('malformed-wire', Pack,
                            "the message needs ~p bits and the input has ~p",
                            [EndBit, gt_bits:bit_size(Msg)])
    end;
bits_fit(#{word_bytes := WB} = Pack, {Msg, _}, EndBit) ->
    Need = whole_words(EndBit, WB) * 8,
    case gt_bits:bit_size(Msg) >= Need of
        true -> ok;
        false -> conv_error('malformed-wire', Pack,
                            "the message needs ~p bytes and the input has ~p",
                            [Need div 8, gt_bits:bit_size(Msg) div 8])
    end;
bits_fit(_, _, _) -> ok.

%% Bytes of as many whole words as reach a bit.
whole_words(EndBit, WB) ->
    WordBits = WB * 8,
    ((EndBit + WordBits - 1) div WordBits) * WB.
-endif.

%% The furthest bit the lines of a scope reach before any item is read:
%% every `field` that is not `optional`, every `when` and `const`, and the
%% count locator of every group.
static_end(bits, Lines) -> ?BITS(bits_static_end(Lines));
static_end(_Wire, _Lines) -> 0.

-if(?W_BITS).
bits_static_end(Lines) ->
    lists:foldl(fun({field, _, _, _, _, {_, _, _, true, _, _}}, Max) -> Max;
                   ({field, _, {Off, Len}, _, _, _}, Max) -> max(Max, Off + Len);
                   ({wh, {Off, Len}, _, _}, Max) -> max(Max, Off + Len);
                   ({const, {Off, Len}, _, _}, Max) -> max(Max, Off + Len);
                   ({group, _, _, {_, {loc, {Off, Len}}}, _, _}, Max) -> max(Max, Off + Len);
                   (_, Max) -> Max
                end, 0, Lines).
-endif.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON).
line_loc({field, _, Loc, _, _, _}) -> Loc;
line_loc({wh, Loc, _, _}) -> Loc;
line_loc({const, Loc, _, _}) -> Loc;
line_loc({group, _, Loc, _, _, _}) -> Loc;
line_loc({sup, Loc, _}) -> Loc;
line_loc({element, Path, _}) -> {element, Path}.

%% The locators the selected lines map: every `field`, `const` and `group`,
%% and every `when` that holds a value. `when <locator> present` does not
%% map its member (ruling 27 of 0.5).
mapped_locs(Lines) ->
    lists:foldl(fun({wh, _, present, _}, Acc) -> Acc;
                   (L, Acc) -> Acc#{line_loc(L) => true}
                end, #{}, Lines).
-endif.

%% What a wire computes from the lines of one scope alone (a kind's scope,
%% or the common lines of a pack without kinds), computed when the pack is
%% loaded and kept with it (ruling 1a of 0.25): on xml, json and geojson the
%% locators the lines map (residue); on tlv the sets the lines walk into and
%% the order of each set's items (gt_tlv:plan/1).
%% On xml, json and geojson the plan also holds the values the lines fix
%% (fixed_locs/1), and on xml where `element` lines make elements
%% (xml_ensure/1): the same plan, without `mapped`, is kept with the body of
%% every group (plan_bodies/2), whose items are written with it.
scope_plan(xml, Lines) ->
    ?XML(#{mapped => mapped_locs(Lines), fixed => fixed_locs(Lines), ensure => xml_ensure(Lines)});
scope_plan(json, Lines) -> ?JSON(#{mapped => mapped_locs(Lines), fixed => fixed_locs(Lines)});
scope_plan(geojson, Lines) -> ?GEOJSON(#{mapped => mapped_locs(Lines), fixed => fixed_locs(Lines)});
scope_plan(tlv, Lines) -> ?TLV(gt_tlv:plan(Lines));
scope_plan(_Wire, _Lines) -> #{}.

%% The body of every `group` line, at any depth, with its plan.
plan_bodies(Wire, Lines) when Wire =:= xml; Wire =:= json; Wire =:= geojson ->
    [case L of
         {group, List, Loc, Spec, #{lines := Ls} = Body, LocT} ->
             Ls1 = plan_bodies(Wire, Ls),
             {group, List, Loc, Spec,
              Body#{lines := Ls1, plan => maps:remove(mapped, scope_plan(Wire, Ls1))}, LocT};
         _ -> L
     end || L <- Lines];
plan_bodies(_Wire, Lines) -> Lines.

%% On `text` the transform decides whether a column's leading spaces are
%% removed.
raw_tr(text, Ctx, Loc, Tr, _Opts, C) -> ?TEXT({gt_text:raw(Ctx, Loc, Tr), C});
raw_tr(Wire, Ctx, Loc, _Tr, Opts, C) -> raw(Wire, Ctx, Loc, Opts, C).

%% ---- the raw wire value at a field's locator ----
%% -> {absent | {ok, Raw}, Cache}. The cache holds the protobuf submessages
%% parsed so far, so each is parsed once however many lines address into it.
raw(xml, Tree, Loc, _Opts, C) -> ?XML({xml_when(Tree, Loc), C});
raw(Wire, Json, Loc, _Opts, C) when Wire =:= geojson; Wire =:= json; Wire =:= gjitem ->
    ?JSONTEXT({member(Wire, Json, Loc), C});
raw(bits, Ctx, Loc, Opts, C) -> ?BITS(bits_raw(Ctx, Loc, Opts, C));
raw(Wire, Msg, Path, _Opts, C) when Wire =:= protobuf; Wire =:= pbitem ->
    ?PROTOBUF(pb_raw(Msg, Path, C)).

-if(?W_BITS).
bits_raw({Msg, Base}, {Off, Len}, {_, Swap, _, _, _, _}, C) ->
    case gt_bits:read(Msg, Base + Off, Len) of
        beyond -> {absent, C};             % an `optional` field past the input
        U when Swap -> {{ok, swap_bytes(U, Len)}, C};
        U -> {{ok, U}, C}
    end.
-endif.

-if(?W_PROTOBUF).
%% a scalar item is read by `.`; a path reads into an item that is a message
pb_raw({scalar, Found}, [], C) -> {{ok, Found}, C};
pb_raw({scalar, _}, _Path, C) -> {absent, C};
pb_raw(_Msg, [], C) -> {absent, C};
%% a path prefix that is on the wire and is not a submessage is
%% malformed-wire, inside or outside a group (ruling 13 of 0.7, ruling 30 of
%% 0.8)
pb_raw(Msg, Path, C) ->
    case pb_get(Msg, Path, C) of
        {absent, C1} = Absent ->
            pb_prefix_check(lists:droplast(Path), C1),
            Absent;
        Found -> Found
    end.

%% After a path was not found: was a field on the way on the wire and not
%% a submessage? pb_sub/4 marked it in the cache.
pb_prefix_check(Prefix, C) -> pb_prefix_check(Prefix, [], C).

pb_prefix_check([], _Rev, _C) -> ok;
pb_prefix_check([N | Rest], Rev, C) ->
    Rev1 = [N | Rev],
    case maps:find(Rev1, C) of
        {ok, not_a_message} ->
            erlang:error({protobuf_malformed, {path_prefix_not_a_submessage, lists:reverse(Rev1)}});
        _ -> pb_prefix_check(Rest, Rev1, C)
    end.

%% The field at a path of field numbers; when a number repeats, the last
%% occurrence wins. Cache: #{ReversedPrefix => Message | none}.
pb_get(Msg, Path, Cache) ->
    case pb_sub(Msg, lists:droplast(Path), [], Cache) of
        {absent, C} -> {absent, C};
        {{ok, {Map, _}}, C} ->
            case maps:find(lists:last(Path), Map) of
                {ok, {_WT, _V} = Found} -> {{ok, Found}, C};
                error -> {absent, C}
            end
    end.

%% The submessage at a path of field numbers -> {absent | {ok, Message}, Cache}.
pb_sub(Msg, [], _Rev, C) -> {{ok, Msg}, C};
pb_sub({Map, _}, [N | Rest], Rev, C) ->
    Rev1 = [N | Rev],
    case maps:find(Rev1, C) of
        {ok, none} -> {absent, C};
        {ok, not_a_message} -> {absent, C};
        {ok, Sub} -> pb_sub(Sub, Rest, Rev1, C);
        error ->
            case maps:find(N, Map) of
                {ok, {2, Bin}} ->
                    Sub = gt_protobuf:parse_msg(Bin),
                    pb_sub(Sub, Rest, Rev1, C#{Rev1 => Sub});
                {ok, _} -> {absent, C#{Rev1 => not_a_message}};
                error -> {absent, C#{Rev1 => none}}
            end
    end.
-endif.

-if(?W_BITS).
%% The bytes of a field in reverse order.
swap_bytes(U, Len) ->
    <<V:Len/little>> = <<U:Len/big>>,
    V.
-endif.

field_decode(xml, Tr, Raw, _Loc, _Opts, _Pack) -> ?XML(xml_decode(Tr, Raw));
field_decode(text, Tr, Raw, _Loc, _Opts, _Pack) -> ?TEXT(gt_text:decode_value(Tr, Raw));
field_decode(Wire, {iscale, N, D, Off}, Raw, _Loc, _Opts, _Pack)
  when Wire =:= geojson; Wire =:= gjitem; Wire =:= json ->
    ?JSONTEXT(iscale_decode(json_number_text(Raw), N, D, Off));
field_decode(geojson, Tr, Raw, _Loc, _Opts, _Pack) -> ?GEOJSON(geojson_decode(Tr, Raw));
field_decode(gjitem, Tr, Raw, _Loc, _Opts, _Pack) -> ?GEOJSON(geojson_decode(Tr, Raw));
field_decode(json, Tr, Raw, _Loc, _Opts, _Pack) -> ?JSON(json_decode(Tr, Raw));
field_decode(bits, Tr, U, Loc, Opts, Pack) -> ?BITS(bits_field_decode(Tr, U, Loc, Opts, Pack));
field_decode(Wire, Tr, {WT, V}, _Loc, _Opts, _Pack) when Wire =:= protobuf; Wire =:= pbitem ->
    ?PROTOBUF(pb_decode(Tr, WT, V)).

-if(?W_BITS).
bits_field_decode(Tr, U, {_Off, Len}, {_, _, Trim, _, _, _}, Pack) ->
    V = bits_decode(Tr, U, Len, maps:get(bit_order, Pack)),
    case Trim of
        true -> trim(Tr, V);
        false -> V
    end.
-endif.

%% ---- residue: what no selected `field`, `const`, `group` or valued `when` maps ----
%% Plan is the scope's plan (scope_plan/2): on xml, json and geojson it holds
%% the mapped locators.
residue(xml, Tree, _Lines, Plan, _Bytes) -> ?XML(xml_residue(Tree, Plan));
residue(geojson, _Json, _Lines, Plan, Bytes) -> ?GEOJSON(geojson_residue(Plan, Bytes));
residue(json, Json, Lines, Plan, _Bytes) -> ?JSON(json_residue(Json, Lines, Plan));
residue(text, Ctx, Lines, _Plan, _Bytes) -> ?TEXT(gt_text:residue(Ctx, Lines));
residue(_, _, _, _, _) -> [].

-if(?W_XML).
xml_residue(Tree, #{mapped := Mapped}) ->
    [{<<"@", Name/binary>>, Val}
     || {Name, Val} <- gt_xml:attrs(Tree), not maps:is_key({[], {attr, Name}}, Mapped)].
-endif.

-if(?W_GEOJSON).
%% geojson: a string as it is; a number as a string holding its text as
%% written; arrays and objects as they were, numbers in them keeping their
%% text; `null` dropped. Of two members with one name, the last value is used
%% at the first position.
geojson_residue(#{mapped := Mapped}, Bytes) ->
    {object, Members} = Raw = gt_json:parse_raw(Bytes),
    Props = case gt_json:get(Raw, <<"properties">>) of
                {ok, {object, PM}} ->
                    [{{prop, K}, V} || {K, V} <- geojson_members(PM),
                                       not maps:is_key({prop, K}, Mapped)];
                _ -> []
            end,
    Top = [{{top, K}, V} || {K, V} <- geojson_members(Members),
                     not lists:member(K, [<<"type">>, <<"geometry">>, <<"properties">>]),
                     not maps:is_key({top, K}, Mapped)],
    Props ++ Top.

%% The members of a geojson object as residue -> [{Name, JsonText}].
geojson_members(Members) ->
    Last = maps:from_list(Members),
    {Out, _} =
        lists:foldl(
          fun({K, _}, {Acc, Seen}) ->
                  case maps:is_key(K, Seen) of
                      true -> {Acc, Seen};
                      false ->
                          Acc1 = case maps:get(K, Last) of
                                     null -> Acc;
                                     V -> [{K, iolist_to_binary(geojson_residue_text(V))} | Acc]
                                 end,
                          {Acc1, Seen#{K => true}}
                  end
          end, {[], #{}}, Members),
    lists:reverse(Out).

geojson_residue_text({num, Text}) -> gt_json:encode(Text);
geojson_residue_text(V) when is_boolean(V) -> gt_json:encode(atom_to_binary(V));
geojson_residue_text(V) -> gt_json:encode(V).
-endif.

-if(?W_JSON).
json_residue({object, Members} = Json, Lines, #{mapped := Mapped}) ->
    json_unread_check(Json, Lines),
    lists:reverse(json_residue(Members, [], Mapped, [])).

%% Scalars at any depth of nested objects, in input order, keyed by path.
%% Arrays, nulls and members whose name contains `.` are not carried.
json_residue([], _Prefix, _Mapped, Acc) -> Acc;
json_residue([{Name, V} | Rest], Prefix, Mapped, Acc) ->
    Path = Prefix ++ [Name],
    Acc1 =
        case binary:match(Name, <<".">>) of
            nomatch ->
                case V of
                    {object, Ms} -> json_residue(Ms, Path, Mapped, Acc);
                    {array, _} -> Acc;
                    null -> Acc;
                    _ ->
                        case maps:is_key(Path, Mapped) of
                            true -> Acc;
                            %% a residue number whose nearest double is
                            %% infinite has no canonical text (ruling 2d of
                            %% 0.11); json_unread_check/2 has refused it
                            false -> [{path_text(Path), V} | Acc]
                        end
                end;
            _ -> Acc
        end,
    json_residue(Rest, Prefix, Mapped, Acc1).

path_text(Path) -> iolist_to_binary(lists:join(<<".">>, Path)).

%% A number outside the double range that no field line reads, anywhere in
%% the document, is malformed-wire (ruling 2d of 0.11, as ruling 27 of 0.15
%% extends it): in arrays, in unmapped members of group items and in `when`
%% members too. A member at a field line's locator is read, whether or not
%% that line gave its key's value; the items of a group are read by the
%% group's body.
json_unread_check(Json, Lines) ->
    Fields = maps:from_list([{Loc, true} || {field, _, Loc, _, _, _} <- Lines]),
    Groups = maps:from_list([{Loc, BLs} || {group, _, Loc, _, #{lines := BLs}, _} <- Lines]),
    unread_value(Json, [], Fields, Groups).

unread_value({object, Ms}, Path, Fields, Groups) ->
    lists:foreach(fun({Name, V}) -> unread_value(V, Path ++ [Name], Fields, Groups) end, Ms);
unread_value({array, Vs}, Path, _Fields, Groups) ->
    case maps:find(Path, Groups) of
        {ok, BLs} -> [json_unread_check(V, BLs) || V <- Vs];
        error -> [unread_value(V, Path ++ [<<"[]">>], #{}, #{}) || V <- Vs]
    end,
    ok;
unread_value(V, Path, Fields, _Groups) ->
    case gt_json:is_num(V) andalso gt_json:num_float(V) =:= error
        andalso not maps:is_key(Path, Fields) of
        true -> erlang:error({json_malformed, {unread_number_outside_the_double_range,
                                               path_text(Path)}});
        false -> ok
    end.
-endif.

%% ===================================================================
%% encode
%% ===================================================================
encode(Engine, Format, Entity) -> encode(pack(Engine, Format), Entity).

encode(#{wire := bits, layout := sequential} = Pack, Entity) ->
    {Lines, Defaults, _Root, _Plan} = select_encode(Pack, Entity),
    ?BITS(gt_seq:encode(Pack, Lines, Defaults, Entity));
encode(#{wire := bits} = Pack, Entity) ->
    {Lines, Defaults, _Root, _Plan} = select_encode(Pack, Entity),
    ?BITS(encode_bits(Pack, Lines, {maps:get(model, Entity), maps:get(lists, Entity, #{}), Defaults}));
encode(#{wire := Wire} = Pack, Entity) ->
    {Lines, Defaults, Root, Plan} = select_encode(Pack, Entity),
    Residue = case maps:get(src, Entity, undefined) =:= maps:get(name, Pack) of
                  true -> maps:get(residue, Entity, []);
                  false -> []
              end,
    Src = source(maps:get(model, Entity), maps:get(lists, Entity, #{}), Defaults),
    iolist_to_binary(encode_wire(Wire, Pack#{root := Root, plan := Plan}, Lines, Src, Residue)).

%% What the lines of a scope are encoded from -> {Value, Lists, Held}.
%% Held(Key) tells whether the scope holds Key (`with`, 0.18). Value(Key)
%% is the scope's value for a `field`: the entity's (or the item's), else
%% the `default` of the scope. A default of the message does not reach into
%% items; a default of a group body applies to its items.
source(Model, Lists, Defaults) ->
    {fun(Key) ->
             case maps:find(Key, Model) of
                 {ok, _} = Found -> Found;
                 error -> maps:find(Key, Defaults)
             end
     end, Lists, fun(Key) -> holds(Key, Model, Lists) end}.

%% Does a scope (the entity, or an item) hold a key (0.18, ruling 2)? A
%% scalar when it is present, whatever its value; a list when it is present
%% with at least one item. A default is never looked at.
holds(Key, Model, Lists) ->
    maps:is_key(Key, Model) orelse
        case maps:find(Key, Lists) of
            {ok, [_ | _]} -> true;
            _ -> false
        end.

%% The lines of one scope with every `field ... with <key>` whose key the
%% scope does not hold replaced by {sup, Loc, LocText}: a line that writes
%% nothing, has no default and no sentinel, opens no gate block and maps no
%% key, but still names its locator (0.18, ruling 1). The bodies of gate
%% blocks belong to the scope; the bodies of groups are items, done per
%% item.
-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON orelse ?W_BITS orelse ?W_PROTOBUF).
suppress(Lines, Held) ->
    [case L of
         {field, _, Loc, _, LocT, Opts} when element(6, Opts) =/= none ->
             case Held(element(6, Opts)) of
                 true -> L;
                 false -> {sup, Loc, LocT}
             end;
         {gate, GLoc, Neg, Vals, #{lines := Ls} = Body, LocT} ->
             {gate, GLoc, Neg, Vals, Body#{lines := suppress(Ls, Held)}, LocT};
         _ -> L
     end || L <- Lines].
-endif.

%% The value a `field` line writes from, in a scope Src of source/3: the
%% scope's value of its key (or default), or error when the line is
%% suppressed by `with` (0.18). For the wires whose encoders read line by
%% line (text, tlv).
line_value({Value, _Lists, Held}, Key, Opts) ->
    case element(6, Opts) of
        none -> Value(Key);
        With ->
            case Held(With) of
                true -> Value(Key);
                false -> error
            end
    end.

item_source(Item, #{defaults := Defaults}) ->
    source(maps:get(model, Item), maps:get(lists, Item, #{}), Defaults).

%% The value a field's transform is given: the model value through the
%% typemap (key `type`) and the field's value table.
wire_value(Pack, Key, Tr, Opts, Val) ->
    via_encode(Opts, typemap_encode(Key, Val, Pack), Tr, Key, Pack).

encode_wire(xml, Pack, Lines, Src, Residue) -> ?XML(xml_encode(Pack, Lines, Src, Residue));
encode_wire(geojson, Pack, Lines, Src, Residue) -> ?GEOJSON(geojson_encode(Pack, Lines, Src, Residue));
encode_wire(json, Pack, Lines, Src, Residue) -> ?JSON(json_encode(Pack, Lines, Src, Residue));
encode_wire(text, Pack, Lines, Src, Residue) -> ?TEXT(gt_text:encode(Pack, Lines, Src, Residue));
encode_wire(tlv, Pack, Lines, Src, Residue) -> ?TLV(gt_tlv:encode(Pack, Lines, Src, Residue));
encode_wire(protobuf, Pack, Lines, Src, _Residue) ->
    ?PROTOBUF(gt_hex:bytes_to_hex(gt_protobuf:serialize(pb_tree(Pack, Lines, Src)))).

-if(?W_XML).
xml_encode(Pack, Lines, Src, Residue) ->
    Root1 = xml_build(gt_xml:new(maps:get(root, Pack)), Lines, maps:get(plan, Pack), Src, Pack),
    Root2 = lists:foldl(
              fun({<<"@", Name/binary>>, Val}, R) ->
                      case gt_xml:get_attr(R, Name) of
                          absent -> gt_xml:add_root_attr(R, Name, Val);
                          _ -> R
                      end;
                 (_, R) -> R
              end, Root1, Residue),
    try iolist_to_binary(gt_xml:serialize(Root2))
    catch error:{xml_unwritable, Text} ->
        conv_error('transform-encode', Pack,
                   "the text ~0p holds a character XML 1.0 cannot hold", [Text])
    end.
-endif.

-if(?W_GEOJSON).
geojson_encode(Pack, Lines, Src, Residue) ->
    Ops = [{Loc, V} || {Loc, {value, V}} <- json_plan(Lines, maps:get(plan, Pack), Src, Pack)],
    Coord = fun(I) -> proplists:get_value({geom, I}, Ops) end,
    Geometry =
        case {Coord(1), Coord(2), Coord(3)} of
            {undefined, _, _} -> "null";
            {_, undefined, _} -> "null";
            {Lon, Lat, undefined} ->
                ["{\"type\":\"Point\",\"coordinates\":[", Lon, $,, Lat, "]}"];
            {Lon, Lat, Alt} ->
                ["{\"type\":\"Point\",\"coordinates\":[", Lon, $,, Lat, $,, Alt, "]}"]
        end,
    Member = fun(K, V) -> [$", gt_json:escape(K), "\":", V] end,
    Props = [Member(K, V) || {{prop, K}, V} <- Ops] ++
            [Member(K, V) || {{prop, K}, V} <- Residue],
    Top = [Member(K, V) || {{top, K}, V} <- Ops] ++
          [Member(K, V) || {{top, K}, V} <- Residue],
    ["{\"type\":\"Feature\",\"geometry\":", Geometry,
     ",\"properties\":{", lists:join($,, Props), "}",
     [[$,, T] || T <- Top], "}"].
-endif.

-if(?W_JSON).
json_encode(Pack, Lines, Src, Residue) ->
    T1 = json_tree(json_plan(Lines, maps:get(plan, Pack), Src, Pack)),
    T2 = lists:foldl(
           fun({PathText, V}, T) ->
                   jt_set(T, binary:split(PathText, <<".">>, [global]),
                          gt_json:encode(V), residue)
           end, T1, Residue),
    jt_write(T2).
-endif.

-if(?W_XML).
%% ---- xml: the lines of a scope written into its element ----
%% An element is made at its first write, so elements come in line order; a
%% group writes one element per item at its position, and nothing for an
%% empty list.
%% The plan of the scope (scope_plan/2) holds its fixed values and where
%% its `element` lines make elements, both kept since load.
xml_build(Elem, Lines, #{fixed := Fixed, ensure := Ensure}, Src, Pack) ->
    Ops = text_plan(Lines, Fixed, Src, Pack, fun xml_render/1, fun({text, T, _}) -> T end,
                    fun(Group, Items) -> xml_items(Group, Items, Pack) end),
    {R9, _} =
        lists:foldl(
          fun(Op, {R0, I}) ->
                  R = lists:foldl(fun(Path, Acc) -> gt_xml:ensure(Acc, Path) end,
                                  R0, maps:get(I, Ensure, [])),
                  {case Op of
                       {_Loc, none} -> R;
                       {{Path, {attr, A}}, {value, S}} -> gt_xml:set_attr(R, Path, {A, S});
                       {{Path, text}, {value, S}} -> gt_xml:set_text(R, Path, S);
                       {Path, {value, {items, Elems}}} ->
                           gt_xml:append_children(R, lists:droplast(Path), Elems)
                   end, I + 1}
          end, {Elem, 1}, Ops),
    R9.

%% `element <path>` lines (0.18) -> #{LineIndex => [Path]}: each element
%% path of an `element` line, and each element on the way to it, is made at
%% the first line, of any kind, that addresses it or a path under it
%% (ruling 13), shorter paths first.
xml_ensure(Lines) ->
    Targets = lists:usort([lists:sublist(Path, N)
                           || {element, Path, _} <- Lines, N <- lists:seq(1, length(Path))]),
    Indexed = lists:zip(lists:seq(1, length(Lines)), [xml_addressed(L) || L <- Lines]),
    lists:foldl(
      fun(T, Acc) ->
              N = length(T),
              case [I || {I, A} <- Indexed, A =/= none, lists:sublist(A, N) =:= T] of
                  [I | _] -> maps:update_with(I, fun(Ps) -> Ps ++ [T] end, [T], Acc);
                  [] -> Acc
              end
      end, #{}, lists:sort(fun(A, B) -> length(A) =< length(B) end, Targets)).

%% The element path an xml line addresses.
xml_addressed({field, _, {Path, _}, _, _, _}) -> Path;
xml_addressed({sup, {Path, _}, _}) -> Path;
xml_addressed({wh, _, present, _}) -> none;     % no position (ruling 19)
xml_addressed({wh, {Path, _}, _, _}) -> Path;
xml_addressed({const, {Path, _}, _, _}) -> Path;
xml_addressed({group, _, Path, _, _, _}) -> Path;
xml_addressed({element, Path, _}) -> Path;
xml_addressed(_) -> none.

xml_items(_Group, [], _Pack) -> none;
xml_items({group, _, Path, _, #{lines := Ls, plan := Plan} = Body, _}, Items, Pack) ->
    Name = lists:last(Path),
    {items, [xml_build(gt_xml:new(Name), Ls, Plan, item_source(I, Body), Pack) || I <- Items]}.

-endif.

%% ---- json, geojson: what each line of a scope writes ----
-if(?W_JSON orelse ?W_GEOJSON).
json_plan(Lines, #{fixed := Fixed}, Src, Pack) ->
    text_plan(Lines, Fixed, Src, Pack, fun json_render/1, fun fixed_json/1,
              fun(Group, Items) -> json_array(Group, Items, Pack) end).

json_tree(Ops) ->
    lists:foldl(
      fun({Path, none}, T) -> jt_reserve(T, lists:droplast(Path));
         ({Path, {value, V}}, T) -> jt_set(T, Path, V, mapped)
      end, {obj, []}, Ops).

%% A list is an array, `[]` when it is empty.
json_array({group, _, _, _, Body, _}, Items, Pack) ->
    [$[, lists:join($,, [json_item(I, Body, Pack) || I <- Items]), $]].

%% An item is the scalar its `.` line writes, else an object; an item with no
%% members written is `{}`.
json_item(Item, #{lines := Ls, plan := Plan} = Body, Pack) ->
    Ops = json_plan(Ls, Plan, item_source(Item, Body), Pack),
    case [V || {[], {value, V}} <- Ops] of
        [V | _] -> V;
        [] ->
            %% a scalar (`.`) item with no value is `null` (ruling 11 of 0.7)
            case lists:any(fun({field, _, [], _, _, _}) -> true; (_) -> false end, Ls) of
                true -> "null";
                false -> jt_write(json_tree([Op || {Loc, _} = Op <- Ops, Loc =/= []]))
            end
    end.

-endif.

%% ---- bits (fixed layout): what the lines of a scope write ----
-if(?W_BITS).
%% Src = {Model, Lists, Defaults}: the scope's keys (the entity's, or the
%% item's), its lists, and the defaults that reach its lines.
%%
%% Writes [{Tier, Offset, Len, Value}] in line order: 1 a field with a
%% present key, 2 a gate value, 3 a field written from a default, 4 a
%% sentinel. See compose/3 for the precedence on one bit.
%% Overs [{Rank, Offset, Len, Value}] in line order, written over any field:
%% Rank 1 for `const`, 2 for `when`, 3 for the count of a group.
%% Checks [{Offset, Len, Negated, Values, Held}]: every gate decode
%% evaluates and whether the encode holds its block (Encode step 6).
encode_bits(#{word_bytes := WB} = Pack, Lines, Src) ->
    {Writes, Overs, End, Checks} = bits_scope(Pack, Lines, Src, 0),
    %% under `armor sixbit` the message is the first L bits (0.14), laid out
    %% here up to the next multiple of 6 with zeros, as the output is read
    %% back for step 6 (ruling 14 of 0.17)
    Armor = maps:get(armor, Pack),
    M0 = case Armor of
             sixbit -> gt_bits:new_bits(((End + 5) div 6) * 6, maps:get(bit_order, Pack));
             hex -> gt_bits:new(whole_words(End, WB), maps:get(bit_order, Pack))
         end,
    M2 = compose(M0, Writes, Overs),
    %% the output decodes to the same choice of blocks
    lists:foreach(
      fun({Off, Len, Neg, Vals, Held}) ->
              case gate_holds(gt_bits:peek(M2, Off, Len), Neg, Vals) of
                  Held -> ok;
                  _ -> conv_error('transform-encode', Pack,
                                  "the gate at bit ~p ~s on the output, where the encode ~s its block",
                                  [Off, case Held of true -> "does not hold"; false -> "holds" end,
                                   case Held of true -> "holds"; false -> "does not hold" end])
              end
      end, Checks),
    case Armor of
        sixbit -> armor_out(gt_bits:to_bytes(M2), End, Pack);
        hex -> gt_hex:bytes_to_hex(gt_bits:to_bytes(M2))
    end.

%% The bits of Writes and Overs (ruling 7 of 0.17), highest first: `const`,
%% `when` and group counts; field lines, the earlier line winning (ruling 5
%% of 0.5), a line written from a default included; a gate value, which is
%% written over a bit that only a default or a sentinel wrote; a sentinel,
%% where no field line writes (ruling 16 of 0.9). Without gate values this
%% is the 0.5 order: field lines in line order, then sentinels.
compose(M0, Writes, Overs) ->
    Present = lists:foldl(fun({1, Off, Len, U}, M) -> gt_bits:write(M, Off, Len, U);
                             (_, M) -> M
                          end, M0, Writes),
    %% field lines in line order, a default only on the bits a present key
    %% also covers
    M1 = lists:foldl(fun({1, Off, Len, U}, M) -> gt_bits:write(M, Off, Len, U);
                        ({3, Off, Len, U}, M) -> gt_bits:write_within(M, Off, Len, U, Present);
                        (_, M) -> M
                     end, M0, Writes),
    M2 = lists:foldl(fun({T, Off, Len, U}, M) when T >= 2 -> gt_bits:write(M, Off, Len, U);
                        (_, M) -> M
                     end, M1, lists:keysort(1, Writes)),
    lists:foldl(fun({_, Off, Len, U}, M) -> gt_bits:overwrite(M, Off, Len, U) end,
                M2, lists:keysort(1, Overs)).

%% One scope -> {Writes, Overs, End, Checks}, offsets from the message's
%% first bit.
bits_scope(Pack, Lines0, {Model, Lists, Defaults} = Src, Base) ->
    Held = fun(K) -> holds(K, Model, Lists) end,
    Lines = suppress(armor_unwritten(Pack, Lines0, Held), Held),
    case lists:any(fun(L) -> element(1, L) =:= gate end, Lines) of
        false -> bits_lines(Pack, Lines, Src, Defaults, Base, true);
        true -> bits_gated(Pack, Lines, Src, Model, Defaults, Base)
    end.

%% Under `armor sixbit` an `optional` field that `with` suppresses is not
%% written, and so does not count toward the length L (0.14, ruling 14 of
%% 0.17): the line is dropped. Elsewhere it is a suppressed line, which
%% writes zero bits and counts (0.18).
armor_unwritten(#{armor := sixbit}, Lines, Held) ->
    lists:append(
      [case L of
           {field, _, _, _, _, {_, _, _, true, _, With}} when With =/= none ->
               case Held(With) of
                   true -> [L];
                   false -> []
               end;
           {gate, GLoc, Neg, Vals, #{lines := Ls} = Body, LocT} ->
               [{gate, GLoc, Neg, Vals, Body#{lines := armor_unwritten(#{armor => sixbit}, Ls, Held)},
                 LocT}];
           _ -> [L]
       end || L <- Lines]);
armor_unwritten(_Pack, Lines, _Held) -> Lines.

%% A scope with gate blocks (Version 0.17, Encode steps 1 to 6).
bits_gated(Pack, Lines, Src, Model, Defaults, Base) ->
    Order = maps:get(bit_order, Pack),
    Outside = [L || L <- Lines, element(1, L) =/= gate],
    Gates = [L || L <- Lines, element(1, L) =:= gate],
    %% steps 2 to 4 on the scope's own bits, item-relative; the bits of the
    %% items of its groups are not written for its gates (ruling 9)
    {OwnWs, OwnOs, _, _} = bits_lines(Pack, Outside, Src, Defaults, Base, false),
    Rel = fun(Ws) -> [{T, Off - Base, Len, U} || {T, Off, Len, U} <- Ws] end,
    Ext = scope_extent(Lines),
    V0 = gt_bits:new(max(1, (Ext + 7) div 8), Order),
    %% step 2: the union of the ranges of `const`, `when`, group counts and
    %% present keys is written (ruling 11)
    W1 = lists:foldl(fun({_, Off, Len, U}, M) -> gt_bits:overwrite(M, Off, Len, U) end,
                     V0, Rel(OwnOs)),
    W2 = lists:foldl(fun({1, Off, Len, U}, M) -> gt_bits:write(M, Off, Len, U);
                        (_, M) -> M
                     end, W1, Rel(OwnWs)),
    %% step 3: gate values, in line order, depth first
    {_, GateVals} = assign_gates(Gates, [], Model, W2, #{}),
    %% step 4: the outside lines with every gate value of step 3, composed
    %% as the output is; bits nothing wrote read as 0
    GateWs = gate_writes(Gates, [], GateVals),
    V4 = compose(V0, Rel(OwnWs) ++ GateWs, Rel(OwnOs)),
    {Held, Checks0} = held_gates(Gates, [], V4, Base, #{}, []),
    %% step 5: the outside lines and the held blocks, in line order
    {Ws, Os, End, Checks} =
        bits_emit(Pack, Lines, [], Src, Defaults, Base, Held, GateVals,
                  {[], [], 0, lists:reverse(Checks0)}),
    %% step 6: a key the scope holds is mapped by a line that is written
    Mapped = maps:from_list([{K, true} || K <- written_keys(Lines, [], Held)]),
    lists:foreach(
      fun(K) ->
              case maps:is_key(K, Model) andalso not maps:is_key(K, Mapped) of
                  true -> conv_error('transform-encode', Pack,
                                     "~s is mapped only by gate blocks that do not hold", [K]);
                  false -> ok
              end
      end, gated_keys(Gates)),
    {Ws, Os, End, Checks}.

%% Is a block open: does one of its fields, or a nested open block, map a
%% key the scope holds? A default or a sentinel does not open it.
gate_open({gate, _, _, _, #{lines := Ls}, _}, Model) ->
    lists:any(fun({field, K, _, _, _, _}) -> maps:is_key(K, Model);
                 ({gate, _, _, _, _, _} = G) -> gate_open(G, Model);
                 (_) -> false
              end, Ls).

%% Step 3 over the blocks of one level and the blocks nested in them, in
%% line order -> {Bits, #{BlockId => Value}}. A block's id is the list of
%% its indexes among the blocks of each level.
assign_gates(Gates, Prefix, Model, V, Acc) ->
    {_, V9, Acc9} =
        lists:foldl(
          fun({gate, {Off, Len}, Neg, Vals, #{lines := Ls}, _} = G, {I, V0, A0}) ->
                  Id = [I | Prefix],
                  {V1, A1} =
                      case gate_open(G, Model) andalso not gt_bits:written_any(V0, Off, Len) of
                          true ->
                              case gate_value(Neg, Vals, Len) of
                                  none -> {V0, A0};
                                  U -> {gt_bits:write(V0, Off, Len, U), A0#{Id => U}}
                              end;
                          false -> {V0, A0}
                      end,
                  {V2, A2} = assign_gates(nested(Ls), Id, Model, V1, A1),
                  {I + 1, V2, A2}
          end, {1, V, Acc}, Gates),
    {V9, Acc9}.

nested(Lines) -> [L || L <- Lines, element(1, L) =:= gate].

%% The gate values of step 3 as writes, item-relative.
gate_writes(Gates, Prefix, GateVals) ->
    {_, Ws} =
        lists:foldl(
          fun({gate, {Off, Len}, _, _, #{lines := Ls}, _}, {I, Acc}) ->
                  Id = [I | Prefix],
                  Own = case maps:find(Id, GateVals) of
                            {ok, U} -> [{2, Off, Len, U}];
                            error -> []
                        end,
                  {I + 1, Acc ++ Own ++ gate_writes(nested(Ls), Id, GateVals)}
          end, {1, []}, Gates),
    Ws.

%% The first listed value; for `!` the smallest value not listed, none when
%% the list names every value.
gate_value(false, [V | _], _Len) -> V;
gate_value(true, Vals, Len) ->
    Set = maps:from_list([{V, true} || V <- Vals]),
    case length(Vals) >= (1 bsl Len) of
        true -> none;
        false -> smallest_free(0, Set)
    end.

smallest_free(N, Set) ->
    case maps:is_key(N, Set) of
        true -> smallest_free(N + 1, Set);
        false -> N
    end.

%% Step 4: the blocks that hold, a nested block evaluated only when its
%% enclosing block holds -> {#{BlockId => true}, Checks latest first}.
held_gates(Gates, Prefix, V, Base, Held, Checks) ->
    {_, H9, C9} =
        lists:foldl(
          fun({gate, {Off, Len}, Neg, Vals, #{lines := Ls}, _}, {I, H0, C0}) ->
                  Id = [I | Prefix],
                  Holds = gate_holds(gt_bits:peek(V, Off, Len), Neg, Vals),
                  C1 = [{Base + Off, Len, Neg, Vals, Holds} | C0],
                  case Holds of
                      true ->
                          {H1, C2} = held_gates(nested(Ls), Id, V, Base, H0#{Id => true}, C1),
                          {I + 1, H1, C2};
                      false -> {I + 1, H0, C1}
                  end
          end, {1, Held, Checks}, Gates),
    {H9, C9}.

%% Step 5 over one level: each line outside a block, and each held block
%% with its gate value and its lines under the block's defaults.
bits_emit(Pack, Lines, Prefix, Src, Defaults, Base, Held, GateVals, Acc0) ->
    {_, Acc9} =
        lists:foldl(
          fun({gate, {Off, Len}, _, _, #{lines := Ls, defaults := Ds}, _}, {I, Acc}) ->
                  Id = [I | Prefix],
                  case maps:is_key(Id, Held) of
                      false -> {I + 1, Acc};
                      true ->
                          {Ws, Os, End, Cs} = Acc,
                          Ws1 = case maps:find(Id, GateVals) of
                                    {ok, U} -> Ws ++ [{2, Base + Off, Len, U}];
                                    error -> Ws
                                end,
                          Acc1 = {Ws1, Os, max(End, Base + Off + Len), Cs},
                          {I + 1, bits_emit(Pack, Ls, Id, Src, maps:merge(Defaults, Ds), Base,
                                            Held, GateVals, Acc1)}
                  end;
             (L, {I, {Ws, Os, End, Cs}}) ->
                  {Ws1, Os1, End1, Cs1} = bits_lines(Pack, [L], Src, Defaults, Base, true),
                  {I, {Ws ++ Ws1, Os ++ Os1, max(End, End1), Cs ++ Cs1}}
          end, {1, Acc0}, Lines),
    Acc9.

%% The keys of the lines outside any block and of the held blocks.
written_keys(Lines, Prefix, Held) ->
    {_, Keys} =
        lists:foldl(
          fun({gate, _, _, _, #{lines := Ls}, _}, {I, Acc}) ->
                  Id = [I | Prefix],
                  case maps:is_key(Id, Held) of
                      true -> {I + 1, Acc ++ written_keys(Ls, Id, Held)};
                      false -> {I + 1, Acc}
                  end;
             ({field, K, _, _, _, _}, {I, Acc}) -> {I, [K | Acc]};
             (_, {I, Acc}) -> {I, Acc}
          end, {1, []}, Lines),
    Keys.

%% The keys of the fields inside blocks, at any depth.
gated_keys(Gates) ->
    lists:usort(lists:append(
                  [[K || {field, K, _, _, _, _} <- Ls] ++ gated_keys(nested(Ls))
                   || {gate, _, _, _, #{lines := Ls}, _} <- Gates])).

%% The furthest bit, from the scope's first bit, that a line, a gate or a
%% count locator of the scope covers.
scope_extent(Lines) ->
    lists:foldl(fun({field, _, {Off, Len}, _, _, _}, M) -> max(M, Off + Len);
                   ({sup, {Off, Len}, _}, M) -> max(M, Off + Len);
                   ({wh, {Off, Len}, _, _}, M) -> max(M, Off + Len);
                   ({const, {Off, Len}, _, _}, M) -> max(M, Off + Len);
                   ({group, _, _, {_, {loc, {Off, Len}}}, _, _}, M) -> max(M, Off + Len);
                   ({gate, {Off, Len}, _, _, #{lines := Ls}, _}, M) ->
                        max(M, max(Off + Len, scope_extent(Ls)));
                   (_, M) -> M
                end, 0, Lines).

%% The lines of a scope that are not gate blocks -> {Writes, Overs, End,
%% Checks}. A field takes the scope's value of its key, else the default
%% that reaches it. WithItems false leaves out the items of groups.
bits_lines(Pack, Lines, {Model, Lists, _}, Defaults, Base, WithItems) ->
    Order = maps:get(bit_order, Pack),
    Armor = maps:get(armor, Pack, hex),
    {Ws9, Os9, End9, Cs9} = lists:foldl(
      fun({field, Key, {Off, Len}, Tr, LocT, {_, Swap, _, Optional, Absent, _} = Opts}, {Ws, Os, End, Cs}) ->
              End1 = max(End, Base + Off + Len),
              Found = case maps:find(Key, Model) of
                          {ok, V} -> {1, V};
                          error ->
                              case maps:find(Key, Defaults) of
                                  {ok, V} -> {3, V};
                                  error -> error
                              end
                      end,
              case Found of
                  %% under armor an optional field whose key is absent, with
                  %% no default and no `absent`, does not count toward the
                  %% length L (0.14); one with `absent` writes its first
                  %% sentinel and counts, optional or not (ruling 12 of 0.14)
                  error when Absent =:= none, Optional, Armor =:= sixbit -> {Ws, Os, End, Cs};
                  error when Absent =:= none -> {Ws, Os, End1, Cs};
                  error ->
                      {[{4, Base + Off, Len, bits_sentinel(Absent, Len, Swap)} | Ws], Os, End1, Cs};
                  {Tier, Val} ->
                      U = guard_encode(
                            Pack, Key, LocT,
                            fun() ->
                                    U0 = bits_encode(Tr, wire_value(Pack, Key, Tr, Opts, Val),
                                                     Len, Order),
                                    case Swap of
                                        true -> swap_bytes(U0, Len);
                                        false -> U0
                                    end
                            end),
                      {[{Tier, Base + Off, Len, U} | Ws], Os, End1, Cs}
              end;
         ({sup, {Off, Len}, _}, {Ws, Os, End, Cs}) ->
              %% suppressed by `with`: zero bits, no default, no sentinel
              {Ws, Os, max(End, Base + Off + Len), Cs};
         ({const, {Off, Len}, Val, _}, {Ws, Os, End, Cs}) ->
              {Ws, [{1, Base + Off, Len, Val} | Os], max(End, Base + Off + Len), Cs};
         ({wh, {Off, Len}, Val, _}, {Ws, Os, End, Cs}) ->
              {Ws, [{2, Base + Off, Len, Val} | Os], max(End, Base + Off + Len), Cs};
         ({group, List, Start, {ItemBits, Count}, #{lines := Ls, defaults := IDs}, LocT},
          {Ws, Os, End, Cs}) ->
              %% a count locator is written with the number of items, 0 for
              %% an absent list; a fixed count needs that many items
              {Items, Os1, End1} =
                  case {Count, maps:find(List, Lists)} of
                      {{loc, {CO, CL}}, Found} ->
                          Is = case Found of
                                   {ok, L} -> L;
                                   error -> []
                               end,
                          N = length(Is),
                          case N < (1 bsl CL) of
                              true -> ok;
                              false ->
                                  conv_error('transform-encode', Pack,
                                             "list ~s has ~p items, which does not fit the count of the group at ~s",
                                             [List, N, LocT])
                          end,
                          {Is, [{3, Base + CO, CL, N} | Os], max(End, Base + CO + CL)};
                      {{fixed, N}, {ok, L}} when length(L) =:= N -> {L, Os, End};
                      {{fixed, N}, {ok, L}} ->
                          conv_error('transform-encode', Pack,
                                     "list ~s has ~p items and the group at ~s holds ~p",
                                     [List, length(L), LocT, N]);
                      {{fixed, N}, error} ->
                          conv_error('transform-encode', Pack,
                                     "list ~s is absent and the group at ~s holds ~p items",
                                     [List, LocT, N])
                  end,
              case WithItems of
                  false -> {Ws, Os1, End1, Cs};
                  true ->
                      %% the items back to back; an item that a nested group
                      %% makes longer than `item <bits>` ends where that group
                      %% ends
                      {Ws2, Os2, Pos, Cs2} =
                          lists:foldl(
                            fun(Item, {W, O, P, C}) ->
                                    ISrc = {maps:get(model, Item), maps:get(lists, Item, #{}), IDs},
                                    {W1, O1, E, C1} = bits_scope(Pack, Ls, ISrc, P),
                                    {lists:reverse(W1, W), lists:reverse(O1, O),
                                     max(P + ItemBits, E), lists:reverse(C1, C)}
                            end, {Ws, Os1, Base + Start, Cs}, Items),
                      {Ws2, Os2, max(End1, Pos), Cs2}
              end;
         (_, Acc) -> Acc
      end, {[], [], 0, []}, Lines),
    Ws = lists:reverse(Ws9),
    %% a `when` with a list or a range (ruling 3 of 0.20): the value of a
    %% field line with a present key on exactly its bits when it matches,
    %% else the first value
    Os = [case O of
              {2, Pos, Len, {anyof, _} = Val} ->
                  case [U || {1, P, L, U} <- Ws, P =:= Pos, L =:= Len] of
                      [U | _] -> case gt_pack:when_match(U, Val) of
                                     true -> {2, Pos, Len, U};
                                     false -> {2, Pos, Len, gt_pack:when_first(Val)}
                                 end;
                      [] -> {2, Pos, Len, gt_pack:when_first(Val)}
                  end;
              _ -> O
          end || O <- lists:reverse(Os9)],
    {Ws, Os, End9, lists:reverse(Cs9)}.

-endif.

%% ---- protobuf: the lines of a scope as a writer tree ----
-if(?W_PROTOBUF).
pb_tree(Pack, Lines0, {Value, Lists, Held}) ->
    Lines = suppress(Lines0, Held),
    %% the earliest line that has a value writes a locator; a group writes
    %% one occurrence per item, and nothing for an empty list
    T1 = lists:foldl(
           fun({field, Key, Path, Tr, LocT, Opts}, T) ->
                   case Value(Key) of
                       error -> T;
                       {ok, Val} ->
                           Leaf = guard_encode(
                                    Pack, Key, LocT,
                                    fun() -> pb_encode(Tr, wire_value(Pack, Key, Tr, Opts, Val)) end),
                           pb_put(T, Path, Leaf, keep)
                   end;
              ({group, List, Path, _, Body, _}, T) ->
                   case maps:find(List, Lists) of
                       {ok, [_ | _] = Items} ->
                           %% a packed list whose items all lack the value
                           %% writes nothing (ruling 11 of 0.7)
                           case pb_group(Pack, Body, Items) of
                               {leaf, 2, <<>>} -> T;
                               Leaf -> pb_put(T, Path, Leaf, keep)
                           end;
                       _ -> T
                   end;
              (_, T) -> T
           end, #{}, Lines),
    %% the sentinel of an absent key, where no line with a value wrote
    %% (ruling 16 of 0.9)
    T1s = lists:foldl(
            fun({field, Key, Path, Tr, _LocT, {_, _, _, _, [_ | _] = Absent, _}}, T) ->
                    case Value(Key) of
                        error -> pb_put(T, Path, pb_sentinel(Tr, Absent), keep);
                        {ok, _} -> T
                    end;
               (_, T) -> T
            end, T1, Lines),
    %% a `const`, and an integer `when`, is written as a varint over any field
    T2 = lists:foldl(
           fun({const, Path, Val, _}, T) ->
                   pb_put(T, Path, {leaf, 0, gt_protobuf:varint(Val)}, force);
              (_, T) -> T
           end, T1s, Lines),
    T3 = lists:foldl(
           fun({wh, Path, Val, _}, T) when is_integer(Val) ->
                   pb_put(T, Path, {leaf, 0, gt_protobuf:varint(Val)}, force);
              ({wh, Path, {anyof, _} = Val, _}, T) ->
                   pb_put(T, Path, {leaf, 0, gt_protobuf:varint(pb_when_value(Pack, Lines, Path, Val, Value, Held))},
                          force);
              (_, T) -> T
           end, T2, Lines),
    %% `when <path> present` with nothing written under the path: an empty
    %% length-delimited field, so the output decodes as the same kind
    lists:foldl(
      fun({wh, Path, present, _}, T) -> pb_put(T, Path, {leaf, 2, <<>>}, keep);
         (_, T) -> T
      end, T3, Lines).

%% A protobuf `when` with a list or a range (rulings 3 and 15 of 0.20): the
%% varint the earliest field line with a value writes on the same path,
%% when the entity holds its key and the value matches; else the first.
pb_when_value(Pack, Lines, Path, Val, Value, Held) ->
    First = gt_pack:when_first(Val),
    case [L || {field, K, P, _, _, _} = L <- Lines, P =:= Path, Value(K) =/= error] of
        [{field, Key, _, Tr, LocT, Opts} | _] ->
            case Held(Key) of
                false -> First;
                true ->
                    {ok, V} = Value(Key),
                    case guard_encode(Pack, Key, LocT,
                                      fun() -> pb_encode(Tr, wire_value(Pack, Key, Tr, Opts, V)) end) of
                        {leaf, 0, Bin} ->
                            case gt_protobuf:varints(Bin) of
                                [U] -> case gt_pack:when_match(U, Val) of
                                           true -> U;
                                           false -> First
                                       end;
                                _ -> First
                            end;
                        _ -> First
                    end
            end;
        [] -> First
    end.

%% The occurrences of a list that has at least one item. A body of `.`
%% lines writes scalars: with a numeric transform the packed form, else one
%% occurrence per item. Another body writes one submessage per item. An item
%% with nothing written is an empty length-delimited occurrence.
pb_group(Pack, #{lines := Ls} = Body, Items) ->
    case pb_scalar_body(Ls) of
        {true, Tr} ->
            Leaves = [pb_scalar_item(Pack, Ls, item_source(I, Body)) || I <- Items],
            case lists:member(Tr, [pvarint, psint, pdouble, pfloat]) of
                true -> {leaf, 2, iolist_to_binary([B || {leaf, _, B} <- Leaves])};
                false -> {rep, [case L of
                                    none -> {leaf, 2, <<>>};
                                    _ -> L
                                end || L <- Leaves]}
            end;
        false ->
            {rep, [{msg, pb_tree(Pack, Ls, item_source(I, Body))} || I <- Items]}
    end.

%% An item without the value writes the sentinel of the first line that has
%% one (ruling 5 of 0.9).
pb_scalar_item(Pack, Lines0, {Value, _, Held} = Src) ->
    Lines = suppress(Lines0, Held),
    case pb_scalar_value(Pack, Lines, Src) of
        none ->
            case [pb_sentinel(Tr, Absent)
                  || {field, Key, _, Tr, _, {_, _, _, _, [_ | _] = Absent, _}} <- Lines,
                     Value(Key) =:= error] of
                [Leaf | _] -> Leaf;
                [] -> none
            end;
        Leaf -> Leaf
    end.

pb_scalar_value(_Pack, [], _Src) -> none;
pb_scalar_value(Pack, [{sup, _, _} | Rest], Src) -> pb_scalar_value(Pack, Rest, Src);
pb_scalar_value(Pack, [{field, Key, _, Tr, LocT, Opts} | Rest], {Value, _, _} = Src) ->
    case Value(Key) of
        error -> pb_scalar_value(Pack, Rest, Src);
        {ok, Val} ->
            guard_encode(Pack, Key, LocT,
                         fun() -> pb_encode(Tr, wire_value(Pack, Key, Tr, Opts, Val)) end)
    end.

-endif.

guard_encode(Pack, Key, LocT, Fun) ->
    try Fun()
    catch _:_ ->
        conv_error('transform-encode', Pack, "field ~s at ~s cannot be encoded", [Key, LocT])
    end.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON).
%% ---- text wires: what each line writes, in line order ----
%% -> [{Loc, none | {value, Rendered}}]. A locator is written once. Where a
%% `const` or a valued `when` names the locator, its value is written, at the
%% position of the first line naming the locator (ruling 26 of 0.5); else
%% the value is that of the earliest `field` line that has one, at that
%% line's position. A `group` whose list the scope has writes what
%% RenderGroup makes of the items. A line that writes nothing still holds
%% its place (`none`).
%% Fixed is fixed_locs/1 of the scope's lines, kept since load.
text_plan(Lines0, Fixed, {Value, Lists, Held}, Pack, RenderField, RenderFixed, RenderGroup) ->
    Lines = suppress(Lines0, Held),
    %% a sentinel is written only at a locator no line with a value writes
    %% (ruling 16 of 0.9)
    Valued = maps:from_list([{Loc, true} || {field, K, Loc, _, _, _} <- Lines,
                                            Value(K) =/= error]),
    {Ops, _} =
        lists:foldl(
          fun(Line, {Acc, Placed}) ->
                  Loc = line_loc(Line),
                  Cand =
                      case maps:find(Loc, Fixed) of
                          {ok, FV} -> {fixed, FV};
                          error ->
                              case Line of
                                  {field, K, _, Tr, LocT, Opts} ->
                                      case {Value(K), element(5, Opts)} of
                                          {error, [S0 | _]} ->
                                              case maps:is_key(Loc, Valued) of
                                                  true -> none;
                                                  false -> {sentinel, S0}
                                              end;
                                          {error, _} -> none;
                                          {{ok, Val}, _} -> {field, K, Tr, Val, LocT, Opts}
                                      end;
                                  {group, List, _, _, _, _} ->
                                      case maps:find(List, Lists) of
                                          error -> none;
                                          {ok, Items} ->
                                              case RenderGroup(Line, Items) of
                                                  none -> none;
                                                  Rendered -> {group, Rendered}
                                              end
                                      end;
                                  _ -> none        % `when <locator> present`
                              end
                      end,
                  case Cand =:= none orelse maps:is_key(Loc, Placed) of
                      true -> {[{Loc, none} | Acc], Placed};
                      false ->
                          R = case Cand of
                                  {fixed, W} -> RenderFixed(W);
                                  {sentinel, S} -> text_sentinel(S);
                                  {group, G} -> G;
                                  {field, Key, Tr1, Val1, LocT1, Opts1} ->
                                      guard_encode(
                                        Pack, Key, LocT1,
                                        fun() ->
                                                RenderField(
                                                  text_encode(Tr1, wire_value(Pack, Key, Tr1,
                                                                              Opts1, Val1)))
                                        end)
                              end,
                          {[{Loc, {value, R}} | Acc], Placed#{Loc => true}}
                  end
          end, {[], #{}}, Lines),
    %% a member or attribute that several lines name is written at the
    %% position of the first `field`, `const` or valued `when` line naming
    %% it, whichever line's value is written there (ruling 23 of 0.9). A
    %% `when <locator> present` holds no position, and groups and elements
    %% are not moved.
    InOrder = lists:reverse(Ops),
    Names = fun({field, _, _, _, _, _}) -> true;
               ({sup, _, _}) -> true;
               ({const, _, _, _}) -> true;
               ({wh, _, {text, _, _}, _}) -> true;
               ({wh, _, {anyof, _}, _}) -> true;
               (_) -> false
            end,
    Written = maps:from_list([{Loc, V} || {Line, {Loc, {value, _} = V}} <- lists:zip(Lines, InOrder),
                                          Names(Line)]),
    {Placed, _} = lists:mapfoldl(
                    fun({Line, {Loc, _} = Op}, Seen) ->
                            case Names(Line) of
                                false -> {Op, Seen};
                                true ->
                                    case maps:is_key(Loc, Seen) of
                                        true -> {{Loc, none}, Seen};
                                        false -> {{Loc, maps:get(Loc, Written, none)},
                                                  Seen#{Loc => true}}
                                    end
                            end
                    end, #{}, lists:zip(Lines, InOrder)),
    Placed.

%% The values a scope's `const` and valued `when` lines write, by locator
%% (ruling 26 of 0.5); a `when` with a list writes its first value (ruling
%% 15 of 0.20). `with` (suppress/2) never touches these lines, so the map is
%% one per scope, computed at load (scope_plan/2).
fixed_locs(Lines) ->
    Consts = maps:from_list([{Loc, V} || {const, Loc, V, _} <- Lines]),
    maps:merge(Consts,
               maps:from_list([{Loc, V} || {wh, Loc, {text, _, _} = V, _} <- Lines] ++
                              [{Loc, V} || {wh, Loc, {anyof, [{text, _, _} = V | _]}, _} <- Lines])).
-endif.

%% ===================================================================
%% absent-value sentinels (Version 0.9)
%% ===================================================================
%% Is the raw wire value one of the field's sentinels? It is compared after
%% `swap` and before `trim`, `via`, `typemap` and the transform. A protobuf
%% field whose wire type is not its transform's is never a sentinel: the
%% transform fails (ruling 15 of 0.9).
is_sentinel(_Wire, _Tr, _Raw, none) -> false;
is_sentinel(bits, _Tr, U, Sentinels) -> lists:member(U, Sentinels);
is_sentinel(Wire, Tr, {WT, V}, Sentinels) when Wire =:= protobuf; Wire =:= pbitem ->
    case {Tr, WT, V} of
        {pvarint, 0, _} -> lists:member(V, Sentinels);
        {psint, 0, _} -> lists:member(V, Sentinels);
        {pdouble, 1, <<U:64/little>>} -> lists:member(U, Sentinels);
        {pfloat, 5, <<U:32/little>>} -> lists:member(U, Sentinels);
        {pstring, 2, _} -> lists:member(V, Sentinels);
        _ -> false
    end;
is_sentinel(xml, _Tr, Text, Sentinels) -> lists:member(Text, Sentinels);
is_sentinel(_Json, _Tr, V, Sentinels) -> ?JSONTEXT(json_is_sentinel(V, Sentinels)).

-if(?W_JSON orelse ?W_GEOJSON).
json_is_sentinel(V, Sentinels) ->
    case gt_json:canonical_text(V) of
        none -> false;
        Text -> lists:keymember(Text, 2, Sentinels)
    end.
-endif.

-if(?W_BITS).
%% The bits of the first sentinel, low `len` bits, then `swap`.
bits_sentinel([S | _], Len, Swap) ->
    U = S band ((1 bsl Len) - 1),
    case Swap of
        true -> swap_bytes(U, Len);
        false -> U
    end.

-endif.

-if(?W_PROTOBUF).
%% The first sentinel as a protobuf leaf: no zig-zag on psint.
pb_sentinel(pstring, [S | _]) -> {leaf, 2, S};
pb_sentinel(pdouble, [S | _]) -> {leaf, 1, <<S:64/little>>};
pb_sentinel(pfloat, [S | _]) -> {leaf, 5, <<S:32/little>>};
pb_sentinel(_Varint, [S | _]) -> {leaf, 0, gt_protobuf:varint(S)}.
-endif.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON).

%% A sentinel on a text wire: xml text as it is; on json and geojson a number,
%% a boolean, or a string.
text_sentinel(S) when is_binary(S) -> S;
text_sentinel({num, T}) -> T;
text_sentinel({bool, T}) -> T;
text_sentinel({str, T}) -> ?JSONTEXT([$", gt_json:escape(T), $"]).
-endif.

%% ===================================================================
%% value tables (`via`) and the typemap
%% ===================================================================
%% Decode: after the transform. The value is looked up by its canonical
%% text, the entries canonicalised as a value of its type is; the result is
%% read as the key's declared type. A value with no entry passes through
%% when the transform yields the key's type, and fails the decode otherwise.
via_decode({none, _, _, _, _, _}, V, _Tr, _Key, _LocT, _Pack) -> V;
via_decode({Table, _, _, _, _, _}, V, Tr, Key, LocT, #{tables := Tables, key_types := KeyTypes} = Pack) ->
    KeyType = maps:get(Key, KeyTypes),
    #{dec := Dec} = maps:get(Table, Tables),
    Found = case maps:find(gt_num:canon(V), maps:get(type_of(V), Dec)) of
                {ok, ModelText} ->
                    try {ok, gt_num:read_as(KeyType, ModelText)}
                    catch _:_ -> error
                    end;
                error ->
                    case gt_pack:yields(Tr) of
                        KeyType -> {ok, V};
                        _ -> error
                    end
            end,
    case Found of
        {ok, Value} -> Value;
        error ->
            conv_error('transform-decode', Pack,
                       "field ~s at ~s: table ~s has no entry for the value", [Key, LocT, Table])
    end.

%% Encode: before the transform; the result is read as the type the
%% transform yields.
via_encode({none, _, _, _, _, _}, V, _Tr, _Key, _Pack) -> V;
via_encode({Table, _, _, _, _, _}, V, Tr, Key, #{tables := Tables, key_types := KeyTypes}) ->
    WireType = gt_pack:yields(Tr),
    #{enc := Enc} = maps:get(Table, Tables),
    case maps:find(gt_num:canon(V), maps:get(type_of(V), Enc)) of
        {ok, NativeText} -> gt_num:read_as(WireType, NativeText);
        error ->
            WireType = maps:get(Key, KeyTypes),
            V
    end.

type_of(V) when is_binary(V) -> string;
type_of(V) when is_integer(V) -> int;
type_of(V) when is_float(V) -> float.

%% typemap: the pack-wide table between native type codes and CoT tokens,
%% applied to the `type` key on every wire.
typemap_decode(<<"type">>, V, #{typemap_dec := Map}) when is_binary(V) ->
    maps:get(V, Map, V);
typemap_decode(_, V, _) -> V.

typemap_encode(<<"type">>, V, #{typemap_enc := Map}) when is_binary(V) ->
    maps:get(V, Map, V);
typemap_encode(_, V, _) -> V.

%% ===================================================================
%% transforms (text wires)
%% ===================================================================
%% xml: the wire value is text, read by the grammars of ruling 2 of 0.11;
%% iscale reads it untrimmed as an exact decimal (ruling 24 of 0.15)
-if(?W_XML orelse ?W_GEOJSON).
xml_decode({iscale, N, D, Off}, S) -> iscale_decode(S, N, D, Off);
xml_decode({scale, F, O}, S) -> scale_decode(xml_decode(float, S), F, O);
xml_decode(string, S) -> S;
xml_decode(float, S) -> {ok, F} = gt_num:num_text(S), F;
xml_decode(int, S) -> {ok, I} = gt_num:int_text(S), I;
xml_decode(iso8601_ms, S) -> gt_iso:decode(S);
xml_decode(iso8601_short, S) -> gt_iso:decode(S);
xml_decode(iso8601_s, S) -> gt_iso:decode(S).
-endif.

-if(?W_GEOJSON).
%% geojson (Version 0.1): the wire value is a JSON value; a string member is
%% read as xml text is, a number member as ruling 2d of 0.11 states. scale
%% refuses a string member, as on json (ruling 23 of 0.15).
geojson_decode({scale, _, _} = Tr, V) -> json_decode(Tr, V);
geojson_decode(string, V) when is_binary(V) -> V;
geojson_decode(Tr, V) when is_binary(V), Tr =/= iso8601_ms, Tr =/= iso8601_short,
                                 Tr =/= iso8601_s -> xml_decode(Tr, V);
geojson_decode(iso8601_ms, V) when is_binary(V) -> gt_iso:decode(V);
geojson_decode(iso8601_short, V) when is_binary(V) -> gt_iso:decode(V);
geojson_decode(iso8601_s, V) when is_binary(V) -> gt_iso:decode(V);
geojson_decode(string, V) ->
    true = gt_json:is_num(V),
    list_to_binary(gt_json:number_text(V));
geojson_decode(Tr, V) -> json_decode(Tr, V).
-endif.

-if(?W_JSON orelse ?W_GEOJSON).
%% json (Version 0.5): a value of the wrong JSON type is a decode failure
json_decode({scale, F, O}, V) -> scale_decode(json_decode(float, V), F, O);
json_decode(string, V) when is_binary(V) -> V;
json_decode(float, V) -> {ok, F} = gt_json:num_float(V), F;
json_decode(int, V) -> {ok, I} = gt_json:num_int(V), I;
json_decode(iso8601_ms, V) when is_binary(V) -> gt_iso:decode(V);
json_decode(iso8601_short, V) when is_binary(V) -> gt_iso:decode(V);
json_decode(iso8601_s, V) when is_binary(V) -> gt_iso:decode(V);
json_decode(bool, true) -> 1;
json_decode(bool, false) -> 0.
-endif.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON).
%% model value -> a tagged value a text wire renders
text_encode({scale, F, O}, V) when is_number(V) -> {float, scale_encode(float(V), F, O)};
text_encode({iscale, N, D, Off}, V) when is_integer(V) -> {num, iscale_encode(V, N, D, Off)};
text_encode(string, V) -> {str, to_str(V)};
text_encode(float, V) when is_number(V) -> {float, float(V)};
text_encode(int, V) when is_integer(V) -> {int, V};
text_encode(iso8601_ms, V) when is_integer(V) -> {str, gt_iso:encode(V)};
text_encode(iso8601_short, V) when is_integer(V) -> {str, gt_iso:encode_short(V)};
text_encode(iso8601_s, V) when is_integer(V) -> {str, gt_iso:encode_seconds(V)};
text_encode(bool, 1) -> {bool, <<"true">>};
text_encode(bool, 0) -> {bool, <<"false">>}.
-endif.

-if(?W_XML).
xml_render({str, S}) -> S;
xml_render({num, T}) -> T;
xml_render({int, I}) -> integer_to_binary(I);
xml_render({float, F}) -> list_to_binary(gt_num:fmt_float(F)).
-endif.

-if(?W_JSON orelse ?W_GEOJSON).
json_render({str, S}) -> [$", gt_json:escape(S), $"];
json_render({num, T}) -> T;
json_render({int, I}) -> integer_to_list(I);
json_render({float, F}) -> gt_num:fmt_float(F);
json_render({bool, B}) -> B.

%% A written `when` or `const` value on json and geojson: canonical JSON
%% number text is a number, `true` and `false` booleans, anything else a
%% string; a leading `=` forces a string.
fixed_json({text, T, true}) -> [$", gt_json:escape(T), $"];
fixed_json({text, T, false}) when T =:= <<"true">>; T =:= <<"false">> -> T;
fixed_json({text, T, false}) ->
    case gt_json:is_number_text(T) of
        true -> T;
        false -> [$", gt_json:escape(T), $"]
    end.

%% ---- iscale (Version 0.15): exact decimals ----
%% The text of a json number as written: a plain integer is its digits.
json_number_text(I) when is_integer(I) -> integer_to_binary(I);
json_number_text({dnum, T}) -> T.
-endif.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON).
%% -?digits(.digits)?([eE][+-]?digits)? read exactly, then
%% round(r * N / D) + Off, which must fit the signed 64-bit range. An
%% exponent above 400 in absolute value fails.
iscale_decode(Text, N, D, Off) when is_binary(Text) ->
    {Neg, R0} = case Text of
                    <<$-, R/binary>> -> {true, R};
                    _ -> {false, Text}
                end,
    {Int, R1} = take_digits(R0),
    true = Int =/= <<>>,
    {Frac, R2} = case R1 of
                     <<$., RF/binary>> ->
                         {F, RF1} = take_digits(RF),
                         true = F =/= <<>>,
                         {F, RF1};
                     _ -> {<<>>, R1}
                 end,
    Exp = case R2 of
              <<>> -> 0;
              <<E, RE/binary>> when E =:= $e; E =:= $E ->
                  {ESign, RE1} = case RE of
                                     <<$-, X/binary>> -> {-1, X};
                                     <<$+, X/binary>> -> {1, X};
                                     _ -> {1, RE}
                                 end,
                  {ED, <<>>} = take_digits(RE1),
                  true = ED =/= <<>>,
                  ESign * binary_to_integer(ED)
          end,
    true = abs(Exp) =< 400,
    M0 = binary_to_integer(<<Int/binary, Frac/binary>>),
    M = case Neg of
            true -> -M0;
            false -> M0
        end,
    E10 = Exp - byte_size(Frac),
    {Num, Den} = case E10 >= 0 of
                     true -> {M * pow10(E10), 1};
                     false -> {M, pow10(-E10)}
                 end,
    int64(round_div(Num * N, Den * D) + Off).

take_digits(Bin) -> take_digits(Bin, 0).
take_digits(Bin, I) ->
    case Bin of
        <<_:I/binary, C, _/binary>> when C >= $0, C =< $9 -> take_digits(Bin, I + 1);
        <<Ds:I/binary, Rest/binary>> -> {Ds, Rest}
    end.

pow10(E) -> pow10(E, 1).
pow10(0, Acc) -> Acc;
pow10(E, Acc) -> pow10(E - 1, Acc * 10).

%% (x - Off) / (N / D) exactly, in plain decimal notation with at most 18
%% fraction digits and no trailing zero.
iscale_encode(X, N, D, Off) ->
    {A0, B0} = {(X - Off) * D, N},
    {A, B} = case B0 < 0 of
                 true -> {-A0, -B0};
                 false -> {A0, B0}
             end,
    Scaled = A * pow10(18),
    0 = Scaled rem B,
    Q = Scaled div B,
    Sign = case Q < 0 of
               true -> <<"-">>;
               false -> <<>>
           end,
    Abs = abs(Q),
    IntPart = integer_to_binary(Abs div pow10(18)),
    FracPart = case Abs rem pow10(18) of
                   0 -> <<>>;
                   F ->
                       Ds = iolist_to_binary(io_lib:format("~18..0b", [F])),
                       <<$., (strip_trailing(Ds, $0))/binary>>
               end,
    <<Sign/binary, IntPart/binary, FracPart/binary>>.
-endif.

%% ===================================================================
%% transforms (bits wire)
%% ===================================================================
%% Under msb-lsb a field's value is read as under lsb, each character and
%% digit as `uint` reads a field of its width at its place (ruling 3 of
%% 0.22), so the transforms take it as lsb.
-if(?W_BITS orelse ?W_TLV).
bits_decode(Tr, U, L, msblsb) -> bits_decode(Tr, U, L, lsb);
bits_decode(uint, U, 64, _) -> gt_num:wrap64(U);
bits_decode(uint, U, _L, _) -> U;
bits_decode(twos, U, L, _) -> to_signed(U, L);
bits_decode({linscale, Max, Range}, U, L, _) -> (to_signed(U, L) / Max) * Range;
bits_decode({uscale, Factor, Offset}, U, _L, _) -> scale_decode(U, Factor, Offset);
bits_decode({sscale, Factor, Offset}, U, L, _) -> scale_decode(to_signed(U, L), Factor, Offset);
%% infinity and NaN do not match a float segment: a decode failure
bits_decode(f32, U, 32, _) -> <<F:32/float>> = <<U:32>>, F;
bits_decode(f64, U, 64, _) -> <<F:64/float>> = <<U:64>>, F;
bits_decode(ascii, U, L, Order) ->
    Bytes = case Order of
                msb -> <<U:L/big>>;
                lsb -> <<U:L/little>>
            end,
    Text = strip_trailing(Bytes, 0),
    true = printable(Text),
    Text;
%% sixbit (0.14): each six bits, first character first in the pack's bit
%% order, as @.._ for 0..31 and space..? for 32..63; trailing @ removed.
bits_decode(sixbit, U, L, Order) ->
    N = L div 6,
    Chars = [sixbit_char((U bsr sixbit_shift(Order, I, N)) band 63) || I <- lists:seq(0, N - 1)],
    strip_trailing(list_to_binary(Chars), $@);
%% ---- Version 0.15 ----
bits_decode({uiscale, N, D, Off}, U, _L, _) -> int64(round_div(U * N, D) + Off);
bits_decode({siscale, N, D, Off}, U, L, _) -> int64(round_div(to_signed(U, L) * N, D) + Off);
bits_decode(smag, U, L, _) -> smag_decode(U, L);
bits_decode({smscale, Factor, Offset}, U, L, _) -> scale_decode(smag_decode(U, L), Factor, Offset);
bits_decode({f32scale, Factor, Offset}, U, 32, _) ->
    <<F:32/float>> = <<U:32>>,
    scale_decode(F, Factor, Offset);
bits_decode({f64scale, Factor, Offset}, U, 64, _) ->
    <<F:64/float>> = <<U:64>>,
    scale_decode(F, Factor, Offset);
bits_decode({chars, Set}, U, L, Order) ->
    W = chars_width(Set),
    Codes = [char_code(U, L, W, I, Order) || I <- lists:seq(0, L div W - 1)],
    Text = list_to_binary([chars_char(Set, C) || C <- Codes]),
    chars_strip(Set, Text);
%% `stop <code>` (0.22): the text ends at the first terminator; the rest of
%% the field is ignored and nothing is removed (ruling 18). With no
%% terminator the field reads as without `stop` (ruling 19).
bits_decode({chars_stop, Set, Stop}, U, L, Order) ->
    W = chars_width(Set),
    Codes = [char_code(U, L, W, I, Order) || I <- lists:seq(0, L div W - 1)],
    case lists:splitwith(fun(C) -> C =/= Stop end, Codes) of
        {Before, [_ | _]} -> until_text(Set, Before);
        {_, []} -> bits_decode({chars, Set}, U, L, Order)
    end;
%% `hex` (0.22): len / 4 lowercase digits, digit k the 4-bit field at bit 4k
%% read as uint reads it in the pack's bit order
bits_decode(hex, U, L, Order) ->
    << <<(hexdigit(char_code(U, L, 4, I, Order)))>> || I <- lists:seq(0, L div 4 - 1) >>;
bits_decode(octal, U, L, _) ->
    N = L div 3,
    list_to_binary(io_lib:format("~*.8.0b", [N, U])).

sixbit_char(V) when V < 32 -> 16#40 + V;
sixbit_char(V) -> V.

%% the shift of character I of N in the field value
sixbit_shift(msb, I, N) -> 6 * (N - 1 - I);
sixbit_shift(lsb, I, _N) -> 6 * I.

sixbit_value(C) when C >= 16#40, C =< 16#5F -> C - 16#40;
sixbit_value(C) when C >= 16#20, C =< 16#3F -> C.

-if(?W_BITS).
%% The field option `trim`: ascii removes trailing spaces, sixbit the whole
%% trailing run of @ and spaces in any mix (0.14).
trim(sixbit, V) -> strip_trailing_any(V, [$@, $\s]);
trim(_Tr, V) -> strip_trailing(V, $\s).
-endif.

strip_trailing_any(<<>>, _Cs) -> <<>>;
strip_trailing_any(Bin, Cs) ->
    case lists:member(binary:last(Bin), Cs) of
        true -> strip_trailing_any(binary:part(Bin, 0, byte_size(Bin) - 1), Cs);
        false -> Bin
    end.

printable(<<>>) -> true;
printable(<<C, R/binary>>) when C >= 16#20, C =< 16#7E -> printable(R);
printable(_) -> false.

%% A value that does not fit the field fails; nothing is wrapped or clamped
%% (ruling 4b of 0.11). `round` is to the nearest integer, a half away from
%% zero (4a); an infinite or NaN quotient raises in the arithmetic.
bits_encode(Tr, V, L, msblsb) -> bits_encode(Tr, V, L, lsb);
bits_encode(uint, V, 64, _) when is_integer(V) -> V band mask(64);
bits_encode(uint, V, L, _) when is_integer(V), V >= 0, V =< (1 bsl L) - 1 -> V;
bits_encode(twos, V, L, _) when is_integer(V) -> signed_fit(V, L);
bits_encode({linscale, Max, Range}, V, L, _) when is_number(V) ->
    signed_fit(round((float(V) / Range) * Max), L);
bits_encode({uscale, Factor, Offset}, V, L, _) when is_number(V) ->
    R = round(scale_encode(float(V), Factor, Offset)),
    true = (R >= 0) andalso (R =< mask(L)),
    R;
bits_encode({sscale, Factor, Offset}, V, L, _) when is_number(V) ->
    signed_fit(round(scale_encode(float(V), Factor, Offset)), L);
%% a value outside single range does not fit a 32-bit float segment
bits_encode(f32, V, 32, _) when is_number(V) -> <<U:32>> = single(V), U;
bits_encode(f64, V, 64, _) when is_number(V) -> <<U:64>> = <<(float(V)):64/float>>, U;
bits_encode(ascii, V, L, Order) when is_binary(V) ->
    N = L div 8,
    true = byte_size(V) =< N,
    true = printable(V),
    Padded = <<V/binary, 0:((N - byte_size(V)) * 8)>>,
    case Order of
        msb -> <<U:L/big>> = Padded, U;
        lsb -> <<U:L/little>> = Padded, U
    end;
bits_encode(sixbit, V, L, Order) when is_binary(V) ->
    N = L div 6,
    true = byte_size(V) =< N,
    Vals = [sixbit_value(C) || <<C>> <= V] ++ lists:duplicate(N - byte_size(V), 0),
    {U, _} = lists:foldl(fun(X, {Acc, I}) -> {Acc bor (X bsl sixbit_shift(Order, I, N)), I + 1} end,
                         {0, 0}, Vals),
    U;
bits_encode({uiscale, N, D, Off}, V, L, _) when is_integer(V) ->
    R = round_div((V - Off) * D, N),
    true = (R >= 0) andalso (R =< mask(L)),
    R;
bits_encode({siscale, N, D, Off}, V, L, _) when is_integer(V) ->
    R = round_div((V - Off) * D, N),
    true = (R >= -(1 bsl (L - 1))) andalso (R < (1 bsl (L - 1))),
    R band mask(L);
bits_encode(smag, V, L, _) when is_integer(V) -> smag_encode(V, L);
bits_encode({smscale, Factor, Offset}, V, L, _) when is_number(V) ->
    smag_encode(round(scale_encode(float(V), Factor, Offset)), L);
bits_encode({f32scale, Factor, Offset}, V, 32, _) when is_number(V) ->
    <<U:32>> = single(scale_encode(float(V), Factor, Offset)),
    U;
bits_encode({f64scale, Factor, Offset}, V, 64, _) when is_number(V) ->
    <<U:64>> = <<(scale_encode(float(V), Factor, Offset)):64/float>>,
    U;
bits_encode({chars, Set}, V, L, Order) when is_binary(V) ->
    W = chars_width(Set),
    N = L div W,
    true = byte_size(V) =< N,
    Codes = [chars_code(Set, C) || <<C>> <= V] ++
        lists:duplicate(N - byte_size(V), chars_pad(Set)),
    {U, _} = lists:foldl(
               fun(C, {Acc, I}) ->
                       Shift = case Order of
                                   msb -> L - (I + 1) * W;
                                   lsb -> I * W
                               end,
                       {Acc bor (C bsl Shift), I + 1}
               end, {0, 0}, Codes),
    U;
bits_encode({chars_stop, Set, Stop}, V, L, Order) when is_binary(V) ->
    W = chars_width(Set),
    N = L div W,
    %% the text, its terminator, then padding; no room for the terminator
    %% fails
    true = byte_size(V) + 1 =< N,
    Codes = until_codes(Set, Stop, V) ++ lists:duplicate(N - byte_size(V) - 1, chars_pad(Set)),
    pack_codes(Codes, L, W, Order);
bits_encode(hex, V, L, Order) when is_binary(V) ->
    true = byte_size(V) =:= L div 4,
    pack_codes([binary_to_integer(<<C>>, 16) || <<C>> <= V], L, 4, Order);
bits_encode(octal, V, L, _) when is_binary(V) ->
    true = byte_size(V) =:= L div 3,
    true = lists:all(fun(C) -> C >= $0 andalso C =< $7 end, binary_to_list(V)),
    binary_to_integer(V, 8).

%% sign and magnitude: the field's top bit is the sign, 1 negative
smag_decode(U, L) ->
    M = U band mask(L - 1),
    case U bsr (L - 1) of
        1 -> -M;
        0 -> M
    end.

smag_encode(V, L) ->
    M = abs(V),
    true = M < (1 bsl (L - 1)),
    case V < 0 of
        true -> (1 bsl (L - 1)) bor M;
        false -> M
    end.

chars_width(ascii7) -> 7;
chars_width(ascii8) -> 8;
chars_width(_) -> 6.

%% Codes written W bits each from the field's first bit, as uint writes a
%% W-bit field at its place.
pack_codes(Codes, L, W, Order) ->
    {U, _} = lists:foldl(
               fun(C, {Acc, I}) ->
                       Shift = case Order of
                                   msb -> L - (I + 1) * W;
                                   lsb -> I * W
                               end,
                       {Acc bor (C bsl Shift), I + 1}
               end, {0, 0}, Codes),
    U.

hexdigit(D) when D < 10 -> $0 + D;
hexdigit(D) -> $a + D - 10.

%% The text of the codes before a terminator (`until:`, `stop`): each
%% character as its set reads it; nothing is removed (rulings 7 and 18 of
%% 0.22). A code the set does not hold raises.
until_text(Set, Codes) -> list_to_binary([chars_char(Set, C) || C <- Codes]).

%% The codes of a text, then the terminator. A character the set cannot
%% hold, or the terminator's own character, raises. NUL is an ordinary
%% character when the terminator is not 0 (rulings 6, 20 and 21 of 0.22).
until_codes(Set, Term, Text) ->
    Codes = [case {C, Set} of
                 {0, ascii7} when Term =/= 0 -> 0;
                 {0, ascii8} when Term =/= 0 -> 0;
                 _ -> chars_code(Set, C)
             end || <<C>> <= Text],
    false = lists:member(Term, Codes),
    Codes ++ [Term].

%% character I of a field: the W bits at bit I * W of the field, read as
%% uint reads a W-bit field there in the pack's bit order
char_code(U, L, W, I, msb) -> (U bsr (L - (I + 1) * W)) band mask(W);
char_code(U, _L, W, I, lsb) -> (U bsr (I * W)) band mask(W).

chars_char(icao6, C) when C >= 1, C =< 26 -> $A + C - 1;
chars_char(icao6, 32) -> $\s;
chars_char(icao6, C) when C >= 48, C =< 57 -> C;
chars_char(ais6, C) when C < 32 -> C + 64;
chars_char(ais6, C) -> C;
chars_char(ascii7, 0) -> 0;
chars_char(ascii7, C) when C >= 32, C =< 126 -> C;
chars_char(ascii8, 0) -> 0;
chars_char(ascii8, C) when C >= 32, C =< 126 -> C.

chars_code(icao6, C) when C >= $A, C =< $Z -> C - $A + 1;
chars_code(icao6, $\s) -> 32;
chars_code(icao6, C) when C >= $0, C =< $9 -> C;
chars_code(ais6, C) when C >= 64, C =< 95 -> C - 64;
chars_code(ais6, C) when C >= 32, C =< 63 -> C;
chars_code(ascii7, C) when C >= 32, C =< 126 -> C;
chars_code(ascii8, C) when C >= 32, C =< 126 -> C.

chars_pad(icao6) -> 32;
chars_pad(ais6) -> 0;
chars_pad(ascii7) -> 0;
chars_pad(ascii8) -> 0.

%% trailing padding removed, with icao6 and ais6 trailing spaces too in any
%% mix; with ascii7 a NUL before a character that is not NUL fails
chars_strip(Set, Text) when Set =:= ascii7; Set =:= ascii8 ->
    T = strip_trailing(Text, 0),
    nomatch = binary:match(T, <<0>>),
    T;
chars_strip(_, Text) -> strip_trailing_any(Text, [$@, $\s]).

to_signed(U, L) ->
    case U >= (1 bsl (L - 1)) of
        true -> U - (1 bsl L);
        false -> U
    end.

mask(L) -> (1 bsl L) - 1.

%% -2^(L-1) .. 2^(L-1) - 1, written as its low L bits
signed_fit(R, L) when R >= -(1 bsl (L - 1)), R < (1 bsl (L - 1)) -> R band mask(L).

-endif.

%% ===================================================================
%% arithmetic the transforms of several wires share
%% ===================================================================
-if(?W_BITS orelse ?W_TLV orelse ?W_PROTOBUF).
%% A double narrowed to a big-endian IEEE-754 single. A value outside single
%% range narrows to an infinity, which is refused.
single(V) ->
    <<_:32/float>> = B = <<(float(V)):32/float>>,
    B.
-endif.

-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON orelse ?W_BITS orelse ?W_TLV).
%% in doubles, in this order: v * factor (or v * num / den), then + offset
scale_decode(V, {dec, F}, Offset) -> float(V) * F + Offset;
scale_decode(V, {frac, Num, Den}, Offset) -> float(V) * Num / Den + Offset.

%% (x - offset) / factor (or (x - offset) * den / num)
scale_encode(X, {dec, F}, Offset) -> (X - Offset) / F;
scale_encode(X, {frac, Num, Den}, Offset) -> (X - Offset) * Den / Num.

strip_trailing(<<>>, _C) -> <<>>;
strip_trailing(Bin, C) when is_binary(Bin) ->
    case binary:last(Bin) of
        C -> strip_trailing(binary:part(Bin, 0, byte_size(Bin) - 1), C);
        _ -> Bin
    end.

%% round-half-away-from-zero of the exact quotient A / B, B not 0
round_div(A, B) when B < 0 -> round_div(-A, -B);
round_div(A, B) when A >= 0 -> (2 * A + B) div (2 * B);
round_div(A, B) -> -((2 * (-A) + B) div (2 * B)).

%% a result outside the signed 64-bit range fails the decode
int64(V) when V >= -(1 bsl 63), V < (1 bsl 63) -> V.
-endif.

%% ===================================================================
%% transforms (protobuf wire): each fixes the field's wire type
%% ===================================================================
-if(?W_PROTOBUF).
pb_decode(pstring, 2, B) ->
    case unicode:characters_to_binary(B, utf8, utf8) of
        B -> B
    end;
pb_decode(pvarint, 0, V) -> gt_num:wrap64(V);
pb_decode(psint, 0, V) -> (V bsr 1) bxor -(V band 1);
%% infinity and NaN do not match a float segment: a decode failure
pb_decode(pdouble, 1, <<F:64/float-little>>) -> F;
pb_decode(pfloat, 5, <<F:32/float-little>>) -> F.

pb_encode(pstring, V) -> {leaf, 2, to_str(V)};
pb_encode(pvarint, V) when is_integer(V) -> {leaf, 0, gt_protobuf:varint(V band ?M64)};
pb_encode(psint, V) when is_integer(V) ->
    {leaf, 0, gt_protobuf:varint(((V bsl 1) bxor (V bsr 63)) band ?M64)};
pb_encode(pdouble, V) when is_number(V) -> {leaf, 1, <<(float(V)):64/float-little>>};
pb_encode(pfloat, V) when is_number(V) ->
    <<U:32>> = single(V),
    {leaf, 5, <<U:32/little>>}.

%% Put a leaf at a path of field numbers. `keep` leaves what an earlier line
%% wrote; `force` replaces it.
pb_put(Tree, [N], Leaf, Mode) ->
    case Mode =:= keep andalso maps:is_key(N, Tree) of
        true -> Tree;
        false -> Tree#{N => Leaf}
    end;
pb_put(Tree, [N | Rest], Leaf, Mode) ->
    case maps:get(N, Tree, {msg, #{}}) of
        {msg, Sub} -> Tree#{N => {msg, pb_put(Sub, Rest, Leaf, Mode)}};
        {leaf, 2, <<>>} -> Tree#{N => {msg, pb_put(#{}, Rest, Leaf, Mode)}};
        {leaf, _, _} -> Tree;
        {rep, _} -> Tree
    end.

-endif.

%% ===================================================================
%% xml locators
%% ===================================================================
-if(?W_XML).
navigate(Elem, []) -> {ok, Elem};
navigate(Elem, [H | T]) ->
    case gt_xml:find_child(Elem, H) of
        absent -> absent;
        {ok, Child} -> navigate(Child, T)
    end.

%% The text a `when` compares: the attribute's value, or the element's text
%% -> absent | {ok, Binary}. An element with no character data has no text,
%% so a `when` with a value does not hold on it (ruling 1m of 0.11).
xml_when(Tree, {Path, Last}) ->
    case navigate(Tree, Path) of
        absent -> absent;
        {ok, Elem} ->
            case Last of
                {attr, A} -> gt_xml:get_attr(Elem, A);
                text -> gt_xml:get_text(Elem)
            end
    end.

-endif.

%% ===================================================================
%% json and geojson members; a member whose value is null is absent
%% ===================================================================
-if(?W_JSON orelse ?W_GEOJSON).
member(geojson, Json, {geom, I}) ->
    case gt_json:get(Json, <<"geometry">>) of
        {ok, {object, _} = Geom} ->
            case gt_json:get(Geom, <<"coordinates">>) of
                {ok, {array, Coords}} when length(Coords) >= I ->
                    not_null(lists:nth(I, Coords));
                _ -> absent
            end;
        _ -> absent
    end;
member(geojson, Json, {prop, Name}) ->
    case gt_json:get(Json, <<"properties">>) of
        {ok, {object, _} = Props} -> member(json, Props, [Name]);
        _ -> absent
    end;
member(geojson, Json, {top, Name}) -> member(json, Json, [Name]);
member(gjitem, Json, Path) -> member(json, Json, Path);
member(json, Json, []) -> not_null(Json);          % `.`: the item itself
member(json, Json, [Name]) ->
    case gt_json:get(Json, Name) of
        {ok, V} -> not_null(V);
        absent -> absent
    end;
member(json, Json, [Name | Rest]) ->
    case gt_json:get(Json, Name) of
        {ok, {object, _} = Child} -> member(json, Child, Rest);
        _ -> absent
    end.

not_null(null) -> absent;
not_null(V) -> {ok, V}.

%% ===================================================================
%% json output tree: {obj, [{Name, Node}]} | {val, IoData}
%% ===================================================================
%% Make the nested objects along a path, each at the end of its parent if it
%% is not there yet: a nested object appears at the position of the first
%% line that addresses into it.
jt_reserve(Node, []) -> Node;
jt_reserve({obj, Ms}, [N | Rest]) ->
    case lists:keyfind(N, 1, Ms) of
        {_, {obj, _} = Child} ->
            {obj, lists:keyreplace(N, 1, Ms, {N, jt_reserve(Child, Rest)})};
        {_, {val, _}} -> {obj, Ms};
        false -> {obj, Ms ++ [{N, jt_reserve({obj, []}, Rest)}]}
    end.

%% Set a member. A mapped value replaces an object that has no members yet;
%% a residue value never replaces anything.
jt_set({obj, Ms}, [N], V, Mode) ->
    case lists:keyfind(N, 1, Ms) of
        false -> {obj, Ms ++ [{N, {val, V}}]};
        {_, {obj, []}} when Mode =:= mapped -> {obj, lists:keyreplace(N, 1, Ms, {N, {val, V}})};
        _ -> {obj, Ms}
    end;
jt_set({obj, Ms}, [N | Rest], V, Mode) ->
    case lists:keyfind(N, 1, Ms) of
        {_, {obj, _} = Child} ->
            {obj, lists:keyreplace(N, 1, Ms, {N, jt_set(Child, Rest, V, Mode)})};
        {_, {val, _}} -> {obj, Ms};
        false -> {obj, Ms ++ [{N, jt_set({obj, []}, Rest, V, Mode)}]}
    end.

%% A nested object that would have no members is not written.
jt_write({obj, Ms}) ->
    [${, lists:join($,, [[$", gt_json:escape(N), "\":", jt_write(Node)]
                         || {N, Node} <- Ms, not jt_empty(Node)]), $}];
jt_write({val, V}) -> V.

jt_empty({val, _}) -> false;
jt_empty({obj, Ms}) -> lists:all(fun({_, Node}) -> jt_empty(Node) end, Ms).
-endif.

%% ===================================================================
%% small coercions
%% ===================================================================
-if(?W_XML orelse ?W_JSON orelse ?W_GEOJSON orelse ?W_PROTOBUF).
to_str(V) when is_binary(V) -> V;
to_str(V) when is_integer(V) -> integer_to_binary(V);
to_str(V) when is_float(V) -> list_to_binary(gt_num:fmt_float(V)).
-endif.
