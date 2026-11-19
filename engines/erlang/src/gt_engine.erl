%% gt_engine: decode(format, bytes) -> entity, encode(format, entity) -> bytes,
%% complete(entity), convert. Clean-room from spec/ and packs/ only
%% (engine-spec Versions 0.1 - 0.9; a sequential
%% bits pack is read and written by gt_seq).
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
-export([new/0, set_max_distribution/2, load_model/2, load_pack/2, load_dir/2,
         load_dir/3, load_packs/3, load_packs/4, model_files/1, packs/1, modules/1,
         model_keys/1, pack/2]).
-export([decode/2, decode/3, encode/2, encode/3, complete/2, complete/3,
         convert/4, convert/5]).
%% for gt_seq (sequential layouts)
-export([conv_error/4, bits_decode/4, bits_encode/4, swap_bytes/2, strip_trailing/2,
         bits_sentinel/3,
         via_decode/6, typemap_decode/3, wire_value/5, guard_encode/4, unhex/2]).

-define(M64, 16#FFFFFFFFFFFFFFFF).

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
modules(#{modules := Modules}) -> Modules.

%% A loaded pack by format name.
pack(#{packs := Packs}, Name) ->
    case maps:find(Name, Packs) of
        {ok, P} -> P;
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
    lists:foreach(
      fun({_Key, _Type, requires}) -> ok;
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
    Kinds = [K#{defaults := maps:merge(CommonDefaults, TypeDefaults(maps:get(defaults, K))),
                lines := type_groups(maps:get(lines, K), TypeDefaults)}
             || K <- maps:get(kinds, P)],
    %% the typemap by either side; of two entries with one value the first is used
    Typemap = maps:get(typemap, P),
    P1 = gt_pack:index(P#{defaults := CommonDefaults, kinds := Kinds, key_types => KeyTypes,
                          typemap_dec => maps:from_list(lists:reverse(Typemap)),
                          typemap_enc => maps:from_list([{C, N} || {N, C} <- lists:reverse(Typemap)]),
                          common := type_groups(maps:get(common, P), TypeDefaults)}),
    Engine#{packs := maps:put(Name, P1, Packs)}.

%% The defaults of every group body, read as their keys' types.
type_groups(Lines, TypeDefaults) ->
    [case L of
         {group, List, Loc, Spec, #{lines := Ls, defaults := Ds}, LocT} ->
             {group, List, Loc, Spec,
              #{lines => type_groups(Ls, TypeDefaults), defaults => TypeDefaults(Ds)}, LocT};
         %% sequential: a kind of a group body has the body's defaults and its own
         {sgroup, List, Mode, #{lines := Ls, defaults := Ds, kinds := Ks}} ->
             Common = TypeDefaults(Ds),
             {sgroup, List, Mode,
              #{lines => type_groups(Ls, TypeDefaults), defaults => Common,
                kinds => [K#{lines := type_groups(maps:get(lines, K), TypeDefaults),
                             defaults := maps:merge(Common, TypeDefaults(maps:get(defaults, K)))}
                          || K <- Ks]}};
         {ifb, Conds, Body} -> {ifb, Conds, type_groups(Body, TypeDefaults)};
         {opt, Body} -> {opt, type_groups(Body, TypeDefaults)};
         {len, Len, Unit, Plus, Body} -> {len, Len, Unit, Plus, type_groups(Body, TypeDefaults)};
         {chain, First, Parts, EndsFx} ->
             {chain, type_groups(First, TypeDefaults),
              [type_groups(Part, TypeDefaults) || Part <- Parts], EndsFx};
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
    E1 = lists:foldl(
           fun(F, E) ->
                   {ok, Bin} = file:read_file(filename:join(ModelsDir, F)),
                   load_model(E, Bin)
           end, Engine, model_files(ModelsDir)),
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
    Files = model_files(ModelsDir),
    Heads = [{F, module_head(filename:join(ModelsDir, F))} || F <- Files],
    ByName = maps:from_list([{Name, Us} || {_, {Name, Us}} <- Heads]),
    Needed = needed_modules(Wanted, ByName, Loaded, #{}),
    %% model_files/1 already puts every module after those it uses
    E1 = lists:foldl(
           fun({F, {Name, _}}, E) ->
                   case maps:is_key(Name, Needed) of
                       true ->
                           {ok, Bin} = file:read_file(filename:join(ModelsDir, F)),
                           load_model(E, Bin);
                       false -> E
                   end
           end, Engine, Heads),
    lists:foldl(fun(T, E) -> load_pack(E, T) end, E1, Texts).

uses_lines(Text) ->
    [U || L <- binary:split(Text, <<"\n">>, [global]),
          [<<"uses">>, U] <- [gt_pack:tokens(L)]].

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
model_files(ModelsDir) ->
    case file:list_dir(ModelsDir) of
        {ok, Files} ->
            Defs = [F || F <- lists:sort(Files), lists:suffix(".def", F)],
            Ordered = [F || F <- Defs, F =:= "core.def"] ++ [F || F <- Defs, F =/= "core.def"],
            Heads = [{F, module_head(filename:join(ModelsDir, F))} || F <- Ordered],
            ByName = maps:from_list([{Name, F} || {F, {Name, _}} <- Heads]),
            Uses = maps:from_list([{F, [maps:get(U, ByName) || U <- Us, maps:is_key(U, ByName)]}
                                   || {F, {_, Us}} <- Heads]),
            {Out, _} = lists:foldl(fun(F, Acc) -> place_module(F, Uses, [], Acc) end,
                                   {[], #{}}, Ordered),
            lists:reverse(Out);
        {error, _} -> []
    end.

%% The module name and the `uses` names of a module file.
module_head(Path) ->
    {ok, Bin} = file:read_file(Path),
    Toks = [gt_pack:tokens(L) || L <- binary:split(Bin, <<"\n">>, [global])],
    {case [N || [<<"module">>, N] <- Toks] of
         [N | _] -> N;
         [] -> undefined
     end,
     [U || [<<"uses">>, U] <- Toks]}.

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
%% -> {KindName | undefined, Lines}
select_decode(#{has_kinds := false, common := Common}, _Wire, _Ctx) -> {undefined, Common};
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
                     xml -> maps:get(gt_xml:name(Ctx), maps:get(root_index, Pack), []);
                     _ -> maps:get(kinds, Pack)
                 end,
    case first_kind(Candidates, fun(#{lines := Ls}) -> Holds(Ls) end) of
        none -> conv_error('no-kind', Pack, "no kind's root and when lines hold for this message", []);
        #{name := Name, lines := Ls} -> {Name, Common ++ Ls}
    end.

%% Encode: the entity's recorded kind when it names this format, else the
%% first kind, in pack order, whose every `requires` key the entity has.
%% -> {Lines, Defaults, Root}
select_encode(#{has_kinds := false, common := Common, defaults := Defaults, root := Root},
              _Entity) ->
    {Common, Defaults, Root};
select_encode(#{name := Name, common := Common, kinds := Kinds, root := PackRoot} = Pack,
              Entity) ->
    Model = maps:get(model, Entity),
    Lists = maps:get(lists, Entity, #{}),
    %% a required key is present in the entity; a required list is present
    %% and has at least one item
    Has = fun(K) ->
                  maps:is_key(K, Model) orelse
                      case maps:find(K, Lists) of
                          {ok, [_ | _]} -> true;
                          _ -> false
                      end
          end,
    Chosen =
        case maps:get(kind, Entity, undefined) of
            {Name, KindName} ->
                maps:get(KindName, maps:get(kind_index, Pack), none);
            _ ->
                first_kind(Kinds, fun(#{requires := Req}) -> lists:all(Has, Req) end)
        end,
    case Chosen of
        none -> conv_error('no-kind', Pack, "the entity selects no kind of the pack", []);
        #{lines := Ls, defaults := Defaults, root := Root} ->
            {Common ++ Ls, Defaults, case Root of undefined -> PackRoot; _ -> Root end}
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
    try decode_wire(Pack, Bytes)
    catch
        error:{convert_error, _, _} = Named:Stack -> erlang:raise(error, Named, Stack);
        error:{protobuf_malformed, Why} ->
            conv_error('malformed-wire', Pack, "protobuf: ~0p", [Why]);
        error:{json_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not json: ~0p", [Why]);
        error:{xml_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not well-formed xml: ~0p", [Why]);
        error:{hex_malformed, Why} ->
            conv_error('malformed-wire', Pack, "the input is not hex text of even length: ~0p", [Why]);
        Class:Reason ->
            conv_error('malformed-wire', Pack, "the input cannot be read ~s ~0P]",
                       [?UNCLASSIFIED, {Class, Reason}, 8])
    end.

decode_wire(#{wire := bits, layout := sequential} = Pack, Bytes) -> gt_seq:decode(Pack, Bytes);
decode_wire(#{wire := Wire} = Pack, Bytes) ->
    Ctx = open(Wire, Pack, Bytes),
    {Kind, Lines} = select_decode(Pack, Wire, Ctx),
    fit(Wire, Pack, Ctx, static_end(Wire, Lines)),
    {Model, Lists, End} = decode_scope(Wire, Ctx, Lines, Pack),
    fit(Wire, Pack, Ctx, End),             % the items extend the message
    #{model => Model,
      lists => Lists,
      residue => residue(Wire, Ctx, Lines, Bytes),
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
                          case raw(Wire, Ctx, Loc, Opts, C) of
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
            conv_error('transform-decode', Pack, "failed fields: ~s",
                       [lists:join(", ", [[K, " at ", L] || {K, L} <- Bad])])
    end,
    {Model, Lists, End}.

%% One item of a list, from its place on the wire.
decode_item(Wire, Ctx, #{lines := Lines}, Pack) ->
    {Model, Lists, _End} = decode_scope(Wire, Ctx, Lines, Pack),
    #{model => Model, lists => Lists}.

%% ---- the items of a group -> {absent | {ok, [Item]}, Cache, End} ----
%% xml: each child element named by the last name, under the first element
%% matched by the names before it; the list is present when an item occurs.
decode_group(xml, Elem, Path, _Spec, Body, Pack, C) ->
    Found = case navigate(Elem, lists:droplast(Path)) of
                absent -> [];
                {ok, Parent} -> gt_xml:children(Parent, lists:last(Path))
            end,
    case Found of
        [] -> {absent, C, 0};
        _ -> {{ok, [decode_item(xml, E, Body, Pack) || E <- Found]}, C, 0}
    end;
%% json, geojson: the member is an array and each element an item. `null` is
%% an absent list; another value is malformed-wire.
decode_group(Wire, Json, Loc, _Spec, Body, Pack, C)
  when Wire =:= json; Wire =:= geojson; Wire =:= gjitem ->
    case member(Wire, Json, Loc) of
        absent -> {absent, C, 0};
        {ok, {array, Els}} ->
            ItemWire = item_wire(Wire),
            {{ok, [decode_item(ItemWire, E, Body, Pack) || E <- Els]}, C, 0};
        {ok, _} ->
            conv_error('malformed-wire', Pack, "the member of a group is not an array", [])
    end;
%% protobuf: each occurrence of the last field number, in wire order. A body
%% of `.` lines reads scalars, and a numeric transform accepts the packed
%% form; another body reads each occurrence as a submessage.
decode_group(Wire, Msg, Path, _Spec, #{lines := Lines} = Body, Pack, C)
  when Wire =:= protobuf; Wire =:= pbitem ->
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
        _ -> {{ok, [decode_item(pbitem, X, Body, Pack) || X <- Ctxs]}, C2, 0}
    end;
%% bits: `count` consecutive items from the group's start; an item is
%% `item <bits>` long, or longer when a nested group counted by a locator
%% runs past that, and the next item starts where it ends.
decode_group(bits, {Msg, Base}, Start, {ItemBits, Count}, #{lines := Lines}, Pack, C) ->
    N = case Count of
            {fixed, K} -> K;
            {loc, {CO, CL}} ->
                case gt_bits:read(Msg, Base + CO, CL) of
                    beyond -> conv_error('malformed-wire', Pack,
                                         "the input ends before the count of a group", []);
                    K -> K
                end
        end,
    {Items, End} = bits_items(N, Base + Start, Msg, ItemBits, Lines, Pack, []),
    {{ok, Items}, C, End}.

bits_items(0, Pos, _Msg, _ItemBits, _Lines, _Pack, Acc) -> {lists:reverse(Acc), Pos};
bits_items(N, Pos, Msg, ItemBits, Lines, Pack, Acc) ->
    case Pos + ItemBits =< gt_bits:bit_size(Msg) of
        true -> ok;
        false -> conv_error('malformed-wire', Pack, "the input ends before the counted items", [])
    end,
    {Model, Lists, End} = decode_scope(bits, {Msg, Pos}, Lines, Pack),
    bits_items(N - 1, max(Pos + ItemBits, End), Msg, ItemBits, Lines, Pack,
               [#{model => Model, lists => Lists} | Acc]).

%% Inside a geojson item the json locators and `null` rule apply, with the
%% geojson value types.
item_wire(geojson) -> gjitem;
item_wire(Wire) -> Wire.

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

%% ---- open the wire ----
open(xml, Pack, Bytes) ->
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
    end;
open(Wire, Pack, Bytes) when Wire =:= geojson; Wire =:= json ->
    Json = gt_json:parse(Bytes),
    case Json of
        {object, _} -> ok;
        _ -> conv_error('malformed-wire', Pack, "the input is not a json object", [])
    end,
    case Wire =:= json andalso gt_json:has_duplicate_member(Json) of
        true -> conv_error('malformed-wire', Pack,
                           "an object holds the same member name twice", []);
        false -> Json
    end;
open(bits, Pack, Bytes) ->
    {gt_bits:open(unhex(Pack, Bytes), maps:get(bit_order, Pack)), 0};
open(protobuf, Pack, Bytes) ->
    gt_protobuf:parse_msg(unhex(Pack, Bytes)).

%% The bytes of hex text (ruling 36 of 0.8).
unhex(Pack, Bytes) ->
    try gt_bits:hex_to_bytes(Bytes)
    catch error:{hex_malformed, Why} ->
        conv_error('malformed-wire', Pack, "the input is not hex text of even length: ~0p", [Why])
    end.

%% ---- does a `when` hold? the value is compared with the raw wire value ----
when_holds(xml, Tree, Loc, present) -> xml_when(Tree, Loc) =/= absent;
when_holds(xml, Tree, Loc, {text, T, _}) -> xml_when(Tree, Loc) =:= {ok, T};
when_holds(Wire, Json, Loc, Val) when Wire =:= geojson; Wire =:= json ->
    case {member(Wire, Json, Loc), Val} of
        {absent, _} -> false;
        {{ok, _}, present} -> true;
        {{ok, V}, {text, T, _}} when is_binary(V) -> V =:= T;
        {{ok, V}, {text, T, _}} when is_number(V) ->
            list_to_binary(gt_json:number_text(V)) =:= T;
        {{ok, true}, {text, T, _}} -> T =:= <<"true">>;
        {{ok, false}, {text, T, _}} -> T =:= <<"false">>;
        _ -> false
    end;
%% a `when` any of whose bits lies beyond the input does not hold
when_holds(bits, {Msg, Base}, {Off, Len}, Val) -> gt_bits:read(Msg, Base + Off, Len) =:= Val;
when_holds(protobuf, Top, Path, Val) ->
    {Found, _} = pb_get(Top, Path, #{}),
    case {Found, Val} of
        {absent, _} -> false;
        {{ok, _}, present} -> true;
        {{ok, {0, V}}, _} -> V =:= Val;
        _ -> false
    end.

%% ---- the message must hold whole words up to a bit (bits) ----
fit(bits, #{word_bytes := WB} = Pack, {Msg, _}, EndBit) ->
    Need = whole_words(EndBit, WB) * 8,
    case gt_bits:bit_size(Msg) >= Need of
        true -> ok;
        false -> conv_error('malformed-wire', Pack,
                            "the message needs ~p bytes and the input has ~p",
                            [Need div 8, gt_bits:bit_size(Msg) div 8])
    end;
fit(_, _, _, _) -> ok.

%% Bytes of as many whole words as reach a bit.
whole_words(EndBit, WB) ->
    WordBits = WB * 8,
    ((EndBit + WordBits - 1) div WordBits) * WB.

%% The furthest bit the lines of a scope reach before any item is read:
%% every `field` that is not `optional`, every `when` and `const`, and the
%% count locator of every group.
static_end(bits, Lines) ->
    lists:foldl(fun({field, _, _, _, _, {_, _, _, true, _}}, Max) -> Max;
                   ({field, _, {Off, Len}, _, _, _}, Max) -> max(Max, Off + Len);
                   ({wh, {Off, Len}, _, _}, Max) -> max(Max, Off + Len);
                   ({const, {Off, Len}, _, _}, Max) -> max(Max, Off + Len);
                   ({group, _, _, {_, {loc, {Off, Len}}}, _, _}, Max) -> max(Max, Off + Len);
                   (_, Max) -> Max
                end, 0, Lines);
static_end(_Wire, _Lines) -> 0.

line_loc({field, _, Loc, _, _, _}) -> Loc;
line_loc({wh, Loc, _, _}) -> Loc;
line_loc({const, Loc, _, _}) -> Loc;
line_loc({group, _, Loc, _, _, _}) -> Loc.

%% The locators the selected lines map: every `field`, `const` and `group`,
%% and every `when` that holds a value. `when <locator> present` does not
%% map its member (ruling 27 of 0.5).
mapped_locs(Lines) ->
    lists:foldl(fun({wh, _, present, _}, Acc) -> Acc;
                   (L, Acc) -> Acc#{line_loc(L) => true}
                end, #{}, Lines).

%% ---- the raw wire value at a field's locator ----
%% -> {absent | {ok, Raw}, Cache}. The cache holds the protobuf submessages
%% parsed so far, so each is parsed once however many lines address into it.
raw(xml, Tree, {Path, Last}, _Opts, C) ->
    R = case navigate(Tree, Path) of
            absent -> absent;
            {ok, Elem} ->
                case Last of
                    {attr, A} -> gt_xml:get_attr(Elem, A);
                    text -> gt_xml:get_text(Elem)
                end
        end,
    {R, C};
raw(Wire, Json, Loc, _Opts, C) when Wire =:= geojson; Wire =:= json; Wire =:= gjitem ->
    {member(Wire, Json, Loc), C};
raw(bits, {Msg, Base}, {Off, Len}, {_, Swap, _, _, _}, C) ->
    case gt_bits:read(Msg, Base + Off, Len) of
        beyond -> {absent, C};             % an `optional` field past the input
        U when Swap -> {{ok, swap_bytes(U, Len)}, C};
        U -> {{ok, U}, C}
    end;
%% a scalar item is read by `.`; a path reads into an item that is a message
raw(protobuf, {scalar, Found}, [], _Opts, C) -> {{ok, Found}, C};
raw(protobuf, {scalar, _}, _Path, _Opts, C) -> {absent, C};
raw(protobuf, _Msg, [], _Opts, C) -> {absent, C};
%% a path prefix that is on the wire and is not a submessage is
%% malformed-wire, inside or outside a group (ruling 13 of 0.7, ruling 30 of
%% 0.8)
raw(protobuf, Msg, Path, _Opts, C) ->
    case pb_get(Msg, Path, C) of
        {absent, C1} = Absent ->
            pb_prefix_check(lists:droplast(Path), C1),
            Absent;
        Found -> Found
    end;
raw(pbitem, {scalar, _} = Item, Path, Opts, C) -> raw(protobuf, Item, Path, Opts, C);
raw(pbitem, _Msg, [], _Opts, C) -> {absent, C};
raw(pbitem, Msg, Path, Opts, C) -> raw(protobuf, Msg, Path, Opts, C).

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

%% The bytes of a field in reverse order.
swap_bytes(U, Len) ->
    <<V:Len/little>> = <<U:Len/big>>,
    V.

field_decode(xml, Tr, Raw, _Loc, _Opts, _Pack) -> xml_decode(Tr, Raw);
field_decode(geojson, Tr, Raw, _Loc, _Opts, _Pack) -> geojson_decode(Tr, Raw);
field_decode(gjitem, Tr, Raw, _Loc, _Opts, _Pack) -> geojson_decode(Tr, Raw);
field_decode(json, Tr, Raw, _Loc, _Opts, _Pack) -> json_decode(Tr, Raw);
field_decode(bits, Tr, U, {_Off, Len}, {_, _, Trim, _, _}, Pack) ->
    V = bits_decode(Tr, U, Len, maps:get(bit_order, Pack)),
    case Trim of
        true -> strip_trailing(V, $\s);
        false -> V
    end;
field_decode(Wire, Tr, {WT, V}, _Loc, _Opts, _Pack) when Wire =:= protobuf; Wire =:= pbitem ->
    pb_decode(Tr, WT, V).

%% ---- residue: what no selected `field`, `const`, `group` or valued `when` maps ----
residue(xml, Tree, Lines, _Bytes) ->
    Mapped = mapped_locs(Lines),
    [{<<"@", Name/binary>>, Val}
     || {Name, Val} <- gt_xml:attrs(Tree), not maps:is_key({[], {attr, Name}}, Mapped)];
%% geojson: a string as it is; a number as a string holding its text as
%% written; arrays and objects as they were, numbers in them keeping their
%% text; `null` dropped. Of two members with one name, the last value is used
%% at the first position.
residue(geojson, _Json, Lines, Bytes) ->
    Mapped = mapped_locs(Lines),
    {object, Members} = Raw = gt_json:parse_raw(Bytes),
    Props = case gt_json:get(Raw, <<"properties">>) of
                {ok, {object, PM}} ->
                    [{{prop, K}, V} || {K, V} <- geojson_residue(PM),
                                       not maps:is_key({prop, K}, Mapped)];
                _ -> []
            end,
    Top = [{{top, K}, V} || {K, V} <- geojson_residue(Members),
                     not lists:member(K, [<<"type">>, <<"geometry">>, <<"properties">>]),
                     not maps:is_key({top, K}, Mapped)],
    Props ++ Top;
residue(json, {object, Members}, Lines, _Bytes) ->
    lists:reverse(json_residue(Members, [], mapped_locs(Lines), []));
residue(_, _, _, _) -> [].

%% The members of a geojson object as residue -> [{Name, JsonText}].
geojson_residue(Members) ->
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
                            false -> [{path_text(Path), V} | Acc]
                        end
                end;
            _ -> Acc
        end,
    json_residue(Rest, Prefix, Mapped, Acc1).

path_text(Path) -> iolist_to_binary(lists:join(<<".">>, Path)).

%% ===================================================================
%% encode
%% ===================================================================
encode(Engine, Format, Entity) -> encode(pack(Engine, Format), Entity).

encode(#{wire := bits, layout := sequential} = Pack, Entity) ->
    {Lines, Defaults, _Root} = select_encode(Pack, Entity),
    gt_seq:encode(Pack, Lines, Defaults, Entity);
encode(#{wire := Wire} = Pack, Entity) ->
    {Lines, Defaults, Root} = select_encode(Pack, Entity),
    Residue = case maps:get(src, Entity, undefined) =:= maps:get(name, Pack) of
                  true -> maps:get(residue, Entity, []);
                  false -> []
              end,
    Src = source(maps:get(model, Entity), maps:get(lists, Entity, #{}), Defaults),
    iolist_to_binary(encode_wire(Wire, Pack#{root := Root}, Lines, Src, Residue)).

%% What the lines of a scope are encoded from -> {Value, Lists}. Value(Key)
%% is the scope's value for a `field`: the entity's (or the item's), else
%% the `default` of the scope. A default of the message does not reach into
%% items; a default of a group body applies to its items.
source(Model, Lists, Defaults) ->
    {fun(Key) ->
             case maps:find(Key, Model) of
                 {ok, _} = Found -> Found;
                 error -> maps:find(Key, Defaults)
             end
     end, Lists}.

item_source(Item, #{defaults := Defaults}) ->
    source(maps:get(model, Item), maps:get(lists, Item, #{}), Defaults).

%% The value a field's transform is given: the model value through the
%% typemap (key `type`) and the field's value table.
wire_value(Pack, Key, Tr, Opts, Val) ->
    via_encode(Opts, typemap_encode(Key, Val, Pack), Tr, Key, Pack).

encode_wire(xml, Pack, Lines, Src, Residue) ->
    Root1 = xml_build(gt_xml:new(maps:get(root, Pack)), Lines, Src, Pack),
    Root2 = lists:foldl(
              fun({<<"@", Name/binary>>, Val}, R) ->
                      case gt_xml:get_attr(R, Name) of
                          absent -> gt_xml:add_root_attr(R, Name, Val);
                          _ -> R
                      end;
                 (_, R) -> R
              end, Root1, Residue),
    gt_xml:serialize(Root2);
encode_wire(geojson, Pack, Lines, Src, Residue) ->
    Ops = [{Loc, V} || {Loc, {value, V}} <- json_plan(Lines, Src, Pack)],
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
     [[$,, T] || T <- Top], "}"];
encode_wire(json, Pack, Lines, Src, Residue) ->
    T1 = json_tree(json_plan(Lines, Src, Pack)),
    T2 = lists:foldl(
           fun({PathText, V}, T) ->
                   jt_set(T, binary:split(PathText, <<".">>, [global]),
                          gt_json:encode(V), residue)
           end, T1, Residue),
    jt_write(T2);
encode_wire(bits, #{word_bytes := WB} = Pack, Lines, Src, _Residue) ->
    {Writes, Overs, End} = bits_plan(Pack, Lines, Src, 0, {[], [], 0}),
    M0 = gt_bits:new(whole_words(End, WB), maps:get(bit_order, Pack)),
    %% fields in line order: where two present fields cover the same bits,
    %% the bits hold the earlier line's value
    %% the sentinels of absent keys after them, in the bits no present
    %% field wrote (ruling 16 of 0.9)
    {Values, Sentinels} = lists:partition(fun(W) -> tuple_size(W) =:= 3 end,
                                          lists:reverse(Writes)),
    M1 = lists:foldl(fun({Off, Len, U}, M) -> gt_bits:write(M, Off, Len, U) end,
                     M0, Values ++ [{Off, Len, U} || {sentinel, Off, Len, U} <- Sentinels]),
    %% `const` values, then `when` values, then the counts of groups are
    %% written last, over any field
    M2 = lists:foldl(fun({_, Off, Len, U}, M) -> gt_bits:overwrite(M, Off, Len, U) end,
                     M1, lists:keysort(1, lists:reverse(Overs))),
    gt_bits:bytes_to_hex(gt_bits:to_bytes(M2));
encode_wire(protobuf, Pack, Lines, Src, _Residue) ->
    gt_bits:bytes_to_hex(gt_protobuf:serialize(pb_tree(Pack, Lines, Src))).

%% ---- xml: the lines of a scope written into its element ----
%% An element is made at its first write, so elements come in line order; a
%% group writes one element per item at its position, and nothing for an
%% empty list.
xml_build(Elem, Lines, Src, Pack) ->
    Ops = text_plan(Lines, Src, Pack, fun xml_render/1, fun({text, T, _}) -> T end,
                    fun(Group, Items) -> xml_items(Group, Items, Pack) end),
    lists:foldl(
      fun({_Loc, none}, R) -> R;
         ({{Path, {attr, A}}, {value, S}}, R) -> gt_xml:set_attr(R, Path, {A, S});
         ({{Path, text}, {value, S}}, R) -> gt_xml:set_text(R, Path, S);
         ({Path, {value, {items, Elems}}}, R) ->
              gt_xml:append_children(R, lists:droplast(Path), Elems)
      end, Elem, Ops).

xml_items(_Group, [], _Pack) -> none;
xml_items({group, _, Path, _, #{lines := Ls} = Body, _}, Items, Pack) ->
    Name = lists:last(Path),
    {items, [xml_build(gt_xml:new(Name), Ls, item_source(I, Body), Pack) || I <- Items]}.

%% ---- json, geojson: what each line of a scope writes ----
json_plan(Lines, Src, Pack) ->
    text_plan(Lines, Src, Pack, fun json_render/1, fun fixed_json/1,
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
json_item(Item, #{lines := Ls} = Body, Pack) ->
    Ops = json_plan(Ls, item_source(Item, Body), Pack),
    case [V || {[], {value, V}} <- Ops] of
        [V | _] -> V;
        [] ->
            %% a scalar (`.`) item with no value is `null` (ruling 11 of 0.7)
            case lists:any(fun({field, _, [], _, _, _}) -> true; (_) -> false end, Ls) of
                true -> "null";
                false -> jt_write(json_tree([Op || {Loc, _} = Op <- Ops, Loc =/= []]))
            end
    end.

%% ---- bits: what the lines of a scope write, from the scope's first bit ----
%% -> {Writes, Overwrites, End}: Writes [{Offset, Len, Value}] latest first,
%% the sentinel of an absent key as {sentinel, Offset, Len, Value};
%% Overwrites [{Rank, Offset, Len, Value}] latest first, Rank 1 for `const`,
%% 2 for `when`, 3 for the count of a group; End the furthest bit reached.
bits_plan(Pack, Lines, {Value, Lists}, Base, Acc0) ->
    Order = maps:get(bit_order, Pack),
    lists:foldl(
      fun({field, Key, {Off, Len}, Tr, LocT, {_, Swap, _, _, Absent} = Opts}, {Ws, Os, End}) ->
              End1 = max(End, Base + Off + Len),
              case Value(Key) of
                  error when Absent =:= none -> {Ws, Os, End1};
                  error ->
                      {[{sentinel, Base + Off, Len, bits_sentinel(Absent, Len, Swap)} | Ws], Os, End1};
                  {ok, Val} ->
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
                      {[{Base + Off, Len, U} | Ws], Os, End1}
              end;
         ({const, {Off, Len}, Val, _}, {Ws, Os, End}) ->
              {Ws, [{1, Base + Off, Len, Val} | Os], max(End, Base + Off + Len)};
         ({wh, {Off, Len}, Val, _}, {Ws, Os, End}) ->
              {Ws, [{2, Base + Off, Len, Val} | Os], max(End, Base + Off + Len)};
         ({group, List, Start, {ItemBits, Count}, #{lines := Ls} = Body, LocT}, {Ws, Os, End}) ->
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
              %% the items back to back; an item that a nested group makes
              %% longer than `item <bits>` ends where that group ends
              {Ws2, Os2, Pos} =
                  lists:foldl(
                    fun(Item, {W, O, P}) ->
                            {W1, O1, E} = bits_plan(Pack, Ls, item_source(Item, Body), P, {W, O, 0}),
                            {W1, O1, max(P + ItemBits, E)}
                    end, {Ws, Os1, Base + Start}, Items),
              {Ws2, Os2, max(End1, Pos)}
      end, Acc0, Lines).

%% ---- protobuf: the lines of a scope as a writer tree ----
pb_tree(Pack, Lines, {Value, Lists}) ->
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
            fun({field, Key, Path, Tr, _LocT, {_, _, _, _, [_ | _] = Absent}}, T) ->
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
              (_, T) -> T
           end, T2, Lines),
    %% `when <path> present` with nothing written under the path: an empty
    %% length-delimited field, so the output decodes as the same kind
    lists:foldl(
      fun({wh, Path, present, _}, T) -> pb_put(T, Path, {leaf, 2, <<>>}, keep);
         (_, T) -> T
      end, T3, Lines).

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
pb_scalar_item(Pack, Lines, {Value, _} = Src) ->
    case pb_scalar_value(Pack, Lines, Src) of
        none ->
            case [pb_sentinel(Tr, Absent)
                  || {field, Key, _, Tr, _, {_, _, _, _, [_ | _] = Absent}} <- Lines,
                     Value(Key) =:= error] of
                [Leaf | _] -> Leaf;
                [] -> none
            end;
        Leaf -> Leaf
    end.

pb_scalar_value(_Pack, [], _Src) -> none;
pb_scalar_value(Pack, [{field, Key, _, Tr, LocT, Opts} | Rest], {Value, _} = Src) ->
    case Value(Key) of
        error -> pb_scalar_value(Pack, Rest, Src);
        {ok, Val} ->
            guard_encode(Pack, Key, LocT,
                         fun() -> pb_encode(Tr, wire_value(Pack, Key, Tr, Opts, Val)) end)
    end.

guard_encode(Pack, Key, LocT, Fun) ->
    try Fun()
    catch _:_ ->
        conv_error('transform-encode', Pack, "field ~s at ~s cannot be encoded", [Key, LocT])
    end.

%% ---- text wires: what each line writes, in line order ----
%% -> [{Loc, none | {value, Rendered}}]. A locator is written once. Where a
%% `const` or a valued `when` names the locator, its value is written, at the
%% position of the first line naming the locator (ruling 26 of 0.5); else
%% the value is that of the earliest `field` line that has one, at that
%% line's position. A `group` whose list the scope has writes what
%% RenderGroup makes of the items. A line that writes nothing still holds
%% its place (`none`).
text_plan(Lines, {Value, Lists}, Pack, RenderField, RenderFixed, RenderGroup) ->
    Consts = maps:from_list([{Loc, V} || {const, Loc, V, _} <- Lines]),
    Fixed = maps:merge(Consts,
                       maps:from_list([{Loc, V} || {wh, Loc, {text, _, _} = V, _} <- Lines])),
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
               ({const, _, _, _}) -> true;
               ({wh, _, {text, _, _}, _}) -> true;
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
is_sentinel(_Json, _Tr, V, Sentinels) ->
    case gt_json:canonical_text(V) of
        none -> false;
        Text -> lists:keymember(Text, 2, Sentinels)
    end.

%% The bits of the first sentinel, low `len` bits, then `swap`.
bits_sentinel([S | _], Len, Swap) ->
    U = S band ((1 bsl Len) - 1),
    case Swap of
        true -> swap_bytes(U, Len);
        false -> U
    end.

%% The first sentinel as a protobuf leaf: no zig-zag on psint.
pb_sentinel(pstring, [S | _]) -> {leaf, 2, S};
pb_sentinel(pdouble, [S | _]) -> {leaf, 1, <<S:64/little>>};
pb_sentinel(pfloat, [S | _]) -> {leaf, 5, <<S:32/little>>};
pb_sentinel(_Varint, [S | _]) -> {leaf, 0, gt_protobuf:varint(S)}.

%% A sentinel on a text wire: xml text as it is; on json and geojson a number,
%% a boolean, or a string.
text_sentinel(S) when is_binary(S) -> S;
text_sentinel({num, T}) -> T;
text_sentinel({bool, T}) -> T;
text_sentinel({str, T}) -> [$", gt_json:escape(T), $"].

%% ===================================================================
%% value tables (`via`) and the typemap
%% ===================================================================
%% Decode: after the transform. The value is looked up by its canonical
%% text, the entries canonicalised as a value of its type is; the result is
%% read as the key's declared type. A value with no entry passes through
%% when the transform yields the key's type, and fails the decode otherwise.
via_decode({none, _, _, _, _}, V, _Tr, _Key, _LocT, _Pack) -> V;
via_decode({Table, _, _, _, _}, V, Tr, Key, LocT, #{tables := Tables, key_types := KeyTypes} = Pack) ->
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
via_encode({none, _, _, _, _}, V, _Tr, _Key, _Pack) -> V;
via_encode({Table, _, _, _, _}, V, Tr, Key, #{tables := Tables, key_types := KeyTypes}) ->
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
%% xml: the wire value is text
xml_decode(string, S) -> S;
xml_decode(float, S) -> gt_num:dec_to_float(S);
xml_decode(int, S) -> gt_num:wrap64(binary_to_integer(S));
xml_decode(iso8601_ms, S) -> gt_iso:decode(S).

%% geojson (Version 0.1): the wire value is a JSON value
geojson_decode(string, V) when is_binary(V) -> V;
geojson_decode(string, V) when is_number(V) -> list_to_binary(gt_json:number_text(V));
geojson_decode(float, V) when is_number(V) -> float(V);
geojson_decode(float, V) when is_binary(V) -> gt_num:dec_to_float(V);
geojson_decode(int, V) when is_number(V); is_binary(V) -> gt_num:wrap64(gt_num:to_int(V));
geojson_decode(iso8601_ms, V) when is_binary(V) -> gt_iso:decode(V).

%% json (Version 0.5): a value of the wrong JSON type is a decode failure
json_decode(string, V) when is_binary(V) -> V;
json_decode(float, V) when is_number(V) -> float(V);
json_decode(int, V) when is_number(V) -> gt_num:wrap64(gt_num:to_int(V));
json_decode(iso8601_ms, V) when is_binary(V) -> gt_iso:decode(V);
json_decode(bool, true) -> 1;
json_decode(bool, false) -> 0.

%% model value -> a tagged value a text wire renders
text_encode(string, V) -> {str, to_str(V)};
text_encode(float, V) when is_number(V) -> {float, float(V)};
text_encode(int, V) when is_integer(V) -> {int, V};
text_encode(iso8601_ms, V) when is_integer(V) -> {str, gt_iso:encode(V)};
text_encode(bool, 1) -> {bool, <<"true">>};
text_encode(bool, 0) -> {bool, <<"false">>}.

xml_render({str, S}) -> S;
xml_render({int, I}) -> integer_to_binary(I);
xml_render({float, F}) -> list_to_binary(gt_num:fmt_float(F)).

json_render({str, S}) -> [$", gt_json:escape(S), $"];
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

%% ===================================================================
%% transforms (bits wire)
%% ===================================================================
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
    Text.

printable(<<>>) -> true;
printable(<<C, R/binary>>) when C >= 16#20, C =< 16#7E -> printable(R);
printable(_) -> false.

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

bits_encode(uint, V, L, _) when is_integer(V) -> V band mask(L);
bits_encode(twos, V, L, _) when is_integer(V) -> V band mask(L);
bits_encode({linscale, Max, Range}, V, L, _) when is_number(V) ->
    round((V / Range) * Max) band mask(L);
bits_encode({uscale, Factor, Offset}, V, L, _) when is_number(V) ->
    R = round(scale_encode(float(V), Factor, Offset)),
    true = (R >= 0) andalso (R =< mask(L)),
    R;
bits_encode({sscale, Factor, Offset}, V, L, _) when is_number(V) ->
    R = round(scale_encode(float(V), Factor, Offset)),
    true = (R >= -(1 bsl (L - 1))) andalso (R < (1 bsl (L - 1))),
    R band mask(L);
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
    end.

%% A double narrowed to a big-endian IEEE-754 single. A value outside single
%% range narrows to an infinity, which is refused.
single(V) ->
    <<_:32/float>> = B = <<(float(V)):32/float>>,
    B.

to_signed(U, L) ->
    case U >= (1 bsl (L - 1)) of
        true -> U - (1 bsl L);
        false -> U
    end.

mask(L) -> (1 bsl L) - 1.

%% ===================================================================
%% transforms (protobuf wire): each fixes the field's wire type
%% ===================================================================
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

%% ===================================================================
%% xml locators
%% ===================================================================
navigate(Elem, []) -> {ok, Elem};
navigate(Elem, [H | T]) ->
    case gt_xml:find_child(Elem, H) of
        absent -> absent;
        {ok, Child} -> navigate(Child, T)
    end.

%% The text a `when` compares: the attribute's value, or the element's text
%% (empty when the element exists and has none) -> absent | {ok, Binary}
xml_when(Tree, {Path, Last}) ->
    case navigate(Tree, Path) of
        absent -> absent;
        {ok, Elem} ->
            case Last of
                {attr, A} -> gt_xml:get_attr(Elem, A);
                text ->
                    case gt_xml:get_text(Elem) of
                        absent -> {ok, <<>>};
                        Found -> Found
                    end
            end
    end.

%% ===================================================================
%% json and geojson members; a member whose value is null is absent
%% ===================================================================
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

%% ===================================================================
%% small coercions
%% ===================================================================
to_str(V) when is_binary(V) -> V;
to_str(V) when is_integer(V) -> integer_to_binary(V);
to_str(V) when is_float(V) -> list_to_binary(gt_num:fmt_float(V)).
