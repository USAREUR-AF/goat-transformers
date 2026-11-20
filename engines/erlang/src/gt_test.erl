%% gt_test: conformance runner (spec/vector-format.md).
%%
%% Loads the model modules and every pack under PacksDir, then runs
%%   - every conversion vector under PacksDir/<pack>/vectors/*.json:
%%     convert(from, to, input [, context]) equals `expect` byte for byte, or
%%     fails with the error kind in `expect_error` (message beginning
%%     "<kind>:"); and, when `model` is present, decode(from, input) has each
%%     listed key (floats within 1e-9) and selects the kind named by "@kind".
%%     With "@complete": true the keys are checked on the completed entity
%%     (decode, context, derivations), floats within 1e-9 relative or 1e-7
%%     absolute.
%%     "@absent" lists keys, item paths and list names the entity must not
%%     have; an entry that is also a member of `model` makes the vector fail;
%%     `max_items` sets the limit on list items for the vector, a `model`
%%     value its grammar refuses makes the vector fail (ruling 2c of 0.11),
%%     and a vector whose format is not loaded is run (unknown-format);
%%   - every load vector under PacksDir/conformance/load-vectors/*.json,
%%     with `pack` or `packs`;
%%   - every capability vector under PacksDir/conformance/capability-vectors.
%%   - the named loader: one pack loaded alone with the modules it needs.
%%   - malformed inputs: every vector input cut short and with single bytes
%%     replaced converts or fails with a named conversion error.
%% Every failure is printed as "FAIL <pack>/<vector>: <why>"; then the counts
%% "vectors: N/M passed", "load vectors: N/M passed", "capability vectors:
%% N/M passed" and "malformed inputs: N/M passed". Exits non-zero on any
%% failure.
-module(gt_test).
-export([main/1, run/1, run/2]).

main(Args) ->
    case Args of
        [P, M | _] -> run(P, M);
        [P] -> run(P);
        [] -> run(default_packs_dir())
    end.

default_packs_dir() ->
    Script = escript:script_name(),
    filename:join([filename:dirname(Script), "..", "..", "packs"]).

run(PacksDir) ->
    run(PacksDir, filename:join([PacksDir, "..", "model"])).

run(PacksDir, ModelsDir) ->
    T0 = erlang:monotonic_time(millisecond),
    Engine = load_packs(PacksDir, ModelsDir),
    {Pass, Fail} = run_conversion(Engine, PacksDir),
    {LPass, LFail} = run_load_vectors(PacksDir),
    {CPass, CFail} = run_capability_vectors(Engine, PacksDir),
    NFail = run_named_load(PacksDir, ModelsDir),
    {MPass0, MFail0} = run_malformed(Engine, PacksDir),
    {RPass, RFail} = run_ruling_cases(Engine),
    {MPass, MFail} = {MPass0 + RPass, MFail0 + RFail},
    io:format("vectors: ~p/~p passed~n", [Pass, Pass + Fail]),
    io:format("load vectors: ~p/~p passed~n", [LPass, LPass + LFail]),
    io:format("capability vectors: ~p/~p passed~n", [CPass, CPass + CFail]),
    io:format("malformed inputs: ~p/~p passed~n", [MPass, MPass + MFail]),
    io:format("elapsed: ~.1f s~n", [(erlang:monotonic_time(millisecond) - T0) / 1000]),
    case Fail + LFail + CFail + NFail + MFail of
        0 -> halt(0);
        N ->
            io:format("FAILED: ~p vector(s)~n", [N]),
            halt(1)
    end.

%% ===================================================================
%% conversion vectors
%% ===================================================================
run_conversion(Engine, PacksDir) ->
    lists:foldl(
      fun({PackDir, File}, {P, F}) ->
              case run_vector_file(Engine, File) of
                  ok -> {P + 1, F};
                  {error, Name, Why} ->
                      io:format("FAIL ~s/~s: ~ts~n", [PackDir, Name, why(Why)]),
                      {P, F + 1}
              end
      end, {0, 0}, vector_files(PacksDir)).

%% Modules (`core.def` first, then byte order of file name), then each pack by itself, so that a
%% pack that does not load fails its own vectors and no others.
load_packs(PacksDir, ModelsDir) ->
    E1 = lists:foldl(
           fun(F, E) ->
                   {ok, Bin} = file:read_file(filename:join(ModelsDir, F)),
                   try gt_engine:load_model(E, Bin)
                   catch C:R ->
                       io:format("FAIL loading model ~s: ~ts~n", [F, why({exception, C, R})]),
                       E
                   end
           end, gt_engine:new(), gt_engine:model_files(ModelsDir)),
    {ok, Entries} = file:list_dir(PacksDir),
    lists:foldl(
      fun(Entry, E) ->
              Def = filename:join([PacksDir, Entry, "pack.def"]),
              case file:read_file(Def) of
                  {ok, Bin} ->
                      try gt_engine:load_pack(E, Bin)
                      catch C:R ->
                          io:format("FAIL loading pack ~s: ~ts~n",
                                    [Entry, why({exception, C, R})]),
                          E
                      end;
                  {error, _} -> E
              end
      end, E1, lists:sort(Entries)).

vector_files(PacksDir) ->
    {ok, Entries} = file:list_dir(PacksDir),
    lists:flatmap(
      fun(Pack) ->
              VDir = filename:join([PacksDir, Pack, "vectors"]),
              case file:list_dir(VDir) of
                  {ok, Files} ->
                      [{Pack, filename:join(VDir, F)}
                       || F <- lists:sort(Files), lists:suffix(".json", F)];
                  {error, _} -> []
              end
      end, lists:sort(Entries)).

run_vector_file(Engine, File) ->
    try
        {ok, Bin} = file:read_file(File),
        gt_json:parse(Bin)
    of
        Obj ->
            Name = case gt_json:get(Obj, <<"name">>) of
                       {ok, N} -> N;
                       absent -> filename:basename(File)
                   end,
            try run_vector(Engine, Obj) of
                ok -> ok;
                {error, Why} -> {error, Name, Why}
            catch C:R:St ->
                {error, Name, {exception, C, R, St}}
            end
    catch C:R ->
        {error, filename:basename(File), {unreadable_vector, C, R}}
    end.

%% A vector whose format is not loaded is run all the same: it pins
%% `unknown-format` (spec/vector-format.md, Load vectors). `max_items` sets
%% the limit on list items for the vector (ruling 7 of 0.11).
run_vector(Engine0, Obj) ->
    G = fun(K) ->
                case gt_json:get(Obj, K) of
                    {ok, V} -> V;
                    absent -> undefined
                end
        end,
    From = G(<<"from">>),
    To = G(<<"to">>),
    Input = G(<<"input">>),
    Context = case G(<<"context">>) of
                  undefined -> none;
                  {object, Pairs} -> Pairs
              end,
    case G(<<"max_items">>) of
        undefined -> run_vector(Engine0, G, From, To, Input, Context);
        N when is_integer(N), N >= 0 ->
            run_vector(gt_engine:set_max_items(Engine0, N), G, From, To, Input, Context);
        Other -> {error, {invalid_vector, max_items, Other}}
    end.

run_vector(Engine, G, From, To, Input, Context) ->
    case model_valid(Engine, G(<<"model">>)) of
        ok ->
            Convert = fun() -> gt_engine:convert(Engine, From, To, Input, Context) end,
            Conv = case {G(<<"expect">>), G(<<"expect_error">>)} of
                       {Expect, undefined} when is_binary(Expect) ->
                           check_convert(Convert, Expect);
                       {undefined, Kind} when is_binary(Kind) ->
                           check_convert_error(Convert, Kind);
                       _ ->
                           {error, vector_needs_exactly_one_of_expect_and_expect_error}
                   end,
            case Conv of
                ok -> check_model(Engine, From, Input, Context, G(<<"model">>));
                Err -> Err
            end;
        Invalid -> Invalid
    end.

%% Ruling 2c of 0.11: a `model` member named by a model key or an item path
%% `<list>[<i>].<key>` is read as that key's declared type (2a for int, 2b
%% for float); `<list>.#` is an unsigned decimal integer or `absent`; the
%% `@` members are not numbers. A value its grammar refuses makes the vector
%% invalid.
model_valid(_Engine, undefined) -> ok;
model_valid(Engine, {object, Pairs}) ->
    Bad = [{K, V} || {K, V} <- Pairs, not model_value_ok(Engine, K, V)],
    case Bad of
        [] -> ok;
        _ -> {error, {invalid_vector, model, Bad}}
    end;
model_valid(_Engine, Other) -> {error, {invalid_vector, model, Other}}.

model_value_ok(_Engine, <<"@", _/binary>>, _V) -> true;
model_value_ok(Engine, Key, V) ->
    Last = lists:last(binary:split(Key, <<"].">>, [global])),
    Size = byte_size(Key) - 2,
    case {Key, Last} of
        {_, <<"@kind">>} -> true;
        {<<_:Size/binary, ".#">>, _} ->
            V =:= <<"absent">> orelse gt_num:uint_text(V) =/= error;
        _ when is_binary(V) ->
            case key_type(Engine, Last) of
                int -> gt_num:int_text(V) =/= error;
                float -> gt_num:num_text(V) =/= error;
                _ -> true
            end;
        _ -> false
    end.

key_type(Engine, Key) ->
    {Mod, Name} = case binary:split(Key, <<".">>) of
                      [N] -> {<<"core">>, N};
                      [M, N] -> {M, N}
                  end,
    case maps:find(Mod, gt_engine:modules(Engine)) of
        {ok, Module} ->
            case gt_model:key_type(Module, Name) of
                {ok, T} -> T;
                error -> undefined
            end;
        error -> undefined
    end.

check_convert(Convert, Expect) ->
    case Convert() of
        Expect -> ok;
        Got -> {error, {convert, Expect, Got}}
    end.

%% convert must fail, and the message must begin with the kind and a colon.
check_convert_error(Convert, Kind) ->
    try Convert() of
        Got -> {error, {expected_error, Kind, {converted_to, Got}}}
    catch
        error:{convert_error, GotKind, Msg} ->
            Prefix = binary_to_list(Kind) ++ ":",
            case atom_to_list(GotKind) =:= binary_to_list(Kind)
                 andalso lists:prefix(Prefix, Msg) of
                true -> ok;
                false -> {error, {expected_error, Kind, {failed_with, Msg}}}
            end
    end.

check_model(_Engine, _From, _Input, _Context, undefined) -> ok;
check_model(Engine, From, Input, Context, {object, Pairs0}) ->
    Complete = lists:keyfind(<<"@complete">>, 1, Pairs0) =:= {<<"@complete">>, true},
    Pairs1 = lists:keydelete(<<"@complete">>, 1, Pairs0),
    %% "@absent" (Version 0.9): keys the entity must not have
    {AbsentKeys, Pairs} =
        case lists:keyfind(<<"@absent">>, 1, Pairs1) of
            false -> {[], Pairs1};
            {_, {array, Listed}} -> {Listed, lists:keydelete(<<"@absent">>, 1, Pairs1)};
            {_, Other} -> {{invalid, Other}, Pairs1}
        end,
    case absent_valid(AbsentKeys, Pairs) of
        ok -> check_model(Engine, From, Input, Context, Complete, AbsentKeys, Pairs);
        Invalid -> Invalid
    end.

%% A listed entry must be a string, and must not be, as text, a member of
%% `model` (ruling 21 of 0.9); an invalid vector fails the run.
absent_valid({invalid, Other}, _Pairs) -> {error, {invalid_vector, '@absent', Other}};
absent_valid(Listed, Pairs) ->
    case [E || E <- Listed, not is_binary(E) orelse lists:keymember(E, 1, Pairs)] of
        [] -> ok;
        Bad -> {error, {invalid_vector, '@absent_clash', Bad}}
    end.

check_model(Engine, From, Input, Context, Complete, AbsentKeys, Pairs) ->
    Decoded = gt_engine:decode(Engine, From, Input),
    %% "@complete": the entity as convert hands it to the encoder
    Entity = case Complete of
                 true -> gt_engine:complete(Engine, Decoded, Context);
                 false -> Decoded
             end,
    Mismatches =
        lists:filtermap(
          fun({<<"@kind">>, Expected}) ->
                  case maps:get(kind, Entity) of
                      {_Format, Expected} -> false;
                      Other -> {true, {'@kind', Expected, Other}}
                  end;
             ({Key, Expected}) ->
                  case lookup(Key, Entity) of
                      {count, Expected} -> false;
                      {count, Actual} -> {true, {Key, Expected, Actual}};
                      missing -> {true, {missing, Key}};
                      {ok, Actual} ->
                          case model_eq(Actual, Expected, Complete) of
                              true -> false;
                              false -> {true, {Key, Expected, Actual}}
                          end
                  end
          end, Pairs)
        ++ [{present, K} || K <- AbsentKeys, not absent_in(K, Entity)],
    case Mismatches of
        [] -> ok;
        _ -> {error, {model, Mismatches}}
    end.

%% Is a "@absent" entry absent from an entity or an item? "<list>[<i>].<key>"
%% needs the item and its lack of the key; a key or a list name needs that
%% the scope has neither.
absent_in(Key, #{model := Model, lists := Lists}) ->
    case binary:match(Key, <<"[">>) of
        {Pos, 1} ->
            List = binary:part(Key, 0, Pos),
            Rest = binary:part(Key, Pos + 1, byte_size(Key) - Pos - 1),
            case binary:split(Rest, <<"].">>) of
                [Index, Inner] ->
                    I = try binary_to_integer(Index) catch _:_ -> -1 end,
                    case maps:find(List, Lists) of
                        {ok, Items} when I >= 0, I < length(Items) ->
                            absent_in(Inner, lists:nth(I + 1, Items));
                        _ -> false
                    end;
                _ -> false
            end;
        nomatch -> not maps:is_key(Key, Model) andalso not maps:is_key(Key, Lists)
    end.

%% A `model` key read in an entity or an item (spec/vector-format.md, Lists
%% in `model`) -> {ok, Value} | {count, Text} | missing.
%%   "<list>[<i>].<key>"  <key> read the same way inside item <i> of the list
%%   "<list>.#"           the number of items, or "absent"
%%   "<key>"              a model key
lookup(<<"@kind">>, Scope) ->
    %% the kind an item recorded when it was decoded
    case maps:get(kind, Scope, undefined) of
        {_Format, Kind} -> {ok, Kind};
        _ -> missing
    end;
lookup(Key, #{model := Model, lists := Lists}) ->
    case binary:match(Key, <<"[">>) of
        {Pos, 1} ->
            List = binary:part(Key, 0, Pos),
            Rest = binary:part(Key, Pos + 1, byte_size(Key) - Pos - 1),
            case binary:split(Rest, <<"].">>) of
                [Index, Inner] ->
                    I = try binary_to_integer(Index) catch _:_ -> -1 end,
                    case maps:find(List, Lists) of
                        {ok, Items} when I >= 0, I < length(Items) ->
                            lookup(Inner, lists:nth(I + 1, Items));
                        _ -> missing
                    end;
                _ -> missing
            end;
        nomatch ->
            Size = byte_size(Key) - 2,
            case Key of
                <<List:Size/binary, ".#">> ->
                    case maps:find(List, Lists) of
                        {ok, Items} -> {count, integer_to_binary(length(Items))};
                        error -> {count, <<"absent">>}
                    end;
                _ ->
                    case maps:find(Key, Model) of
                        {ok, V} -> {ok, V};
                        error -> missing
                    end
            end
    end.

%% Expected model values are given in string form. A float compares within
%% 1e-9; on a completed entity within 1e-9 relative, or within 1e-7
%% absolute (Version 0.16), or equal.
model_eq(Actual, Expected, Complete) when is_float(Actual), is_binary(Expected) ->
    try gt_num:read_as(float, Expected) of
        Want when Complete ->
            Actual == Want orelse
                abs(Actual - Want) < 1.0e-9 * max(abs(Actual), abs(Want)) orelse
                abs(Actual - Want) < 1.0e-7;
        Want -> abs(Actual - Want) < 1.0e-9
    catch _:_ -> false
    end;
model_eq(Actual, Expected, _) when is_integer(Actual), is_binary(Expected) ->
    integer_to_binary(Actual) =:= Expected;
model_eq(Actual, Expected, _) when is_binary(Actual) ->
    Actual =:= Expected;
model_eq(_, _, _) -> false.

%% ===================================================================
%% load vectors (spec/vector-format.md, Load vectors)
%% ===================================================================
run_load_vectors(PacksDir) ->
    Dir = filename:join([PacksDir, "conformance", "load-vectors"]),
    Files = case file:list_dir(Dir) of
                {ok, Fs} -> [F || F <- lists:sort(Fs), lists:suffix(".json", F)];
                {error, _} -> []
            end,
    lists:foldl(
      fun(F, {P, Fl}) ->
              case run_load_vector(filename:join(Dir, F)) of
                  ok -> {P + 1, Fl};
                  {error, Why} ->
                      io:format("FAIL conformance/load-vectors/~s: ~ts~n", [F, why(Why)]),
                      {P, Fl + 1}
              end
      end, {0, 0}, Files).

%% The engine starts empty, loads the modules in order and then the pack,
%% stopping at the first failure.
run_load_vector(Path) ->
    try
        {ok, Bin} = file:read_file(Path),
        Obj = gt_json:parse(Bin),
        {ok, {array, Models}} = gt_json:get(Obj, <<"models">>),
        %% `packs` (Version 0.11): pack texts loaded in order into one engine
        Packs = case {gt_json:get(Obj, <<"pack">>), gt_json:get(Obj, <<"packs">>)} of
                    {{ok, Pack}, absent} when is_binary(Pack) -> [Pack];
                    {absent, {ok, {array, Ps}}} -> Ps
                end,
        Expect = case gt_json:get(Obj, <<"expect_error">>) of
                     {ok, K} -> binary_to_list(K);
                     absent -> none
                 end,
        E0 = case gt_json:get(Obj, <<"max_distribution">>) of
                 {ok, Max} -> gt_engine:set_max_distribution(gt_engine:new(), Max);
                 absent -> gt_engine:new()
             end,
        Got = try
                  E1 = lists:foldl(fun(M, E) -> gt_engine:load_model(E, M) end, E0, Models),
                  _ = lists:foldl(fun(Pk, E) -> gt_engine:load_pack(E, Pk) end, E1, Packs),
                  none
              catch error:{load_error, Kind, Msg} ->
                  %% the message must begin with the kind and a colon
                  case lists:prefix(atom_to_list(Kind) ++ ":", Msg) of
                      true -> atom_to_list(Kind);
                      false -> {bad_message, Msg}
                  end
              end,
        case Got =:= Expect of
            true -> ok;
            false -> {error, {load, [{expect_error, Expect}, {got, Got}]}}
        end
    catch Class:Reason ->
        {error, {exception, Class, Reason}}
    end.

%% ===================================================================
%% capability vectors (spec/vector-format.md, Capability vectors)
%% ===================================================================
%% capability(from, to) over the loaded packs: the grade and both lists,
%% entry for entry and in order.
run_capability_vectors(Engine, PacksDir) ->
    Dir = filename:join([PacksDir, "conformance", "capability-vectors"]),
    Files = case file:list_dir(Dir) of
                {ok, Fs} -> [F || F <- lists:sort(Fs), lists:suffix(".json", F)];
                {error, _} -> []
            end,
    lists:foldl(
      fun(F, {P, Fl}) ->
              case run_capability_vector(Engine, filename:join(Dir, F)) of
                  ok -> {P + 1, Fl};
                  {error, Why} ->
                      io:format("FAIL conformance/capability-vectors/~s: ~ts~n", [F, why(Why)]),
                      {P, Fl + 1}
              end
      end, {0, 0}, Files).

run_capability_vector(Engine, Path) ->
    try
        {ok, Bin} = file:read_file(Path),
        Obj = gt_json:parse(Bin),
        Get = fun(K) -> {ok, V} = gt_json:get(Obj, K), V end,
        {array, Carried} = Get(<<"carried">>),
        {array, Dropped} = Get(<<"dropped">>),
        Want = {binary_to_atom(Get(<<"grade">>)), Carried, Dropped},
        case gt_engine:capability(Engine, Get(<<"from">>), Get(<<"to">>)) of
            Want -> ok;
            Got -> {error, {capability, [{expect, Want}, {got, Got}]}}
        end
    catch Class:Reason ->
        {error, {exception, Class, Reason}}
    end.

%% ===================================================================
%% the named loader (gt_engine:load_packs/4)
%% ===================================================================
%% The pack directory with the smallest pack.def among those whose vectors
%% all stay inside the pack is loaded alone, with the modules it needs: the
%% engine then holds that one pack, and the pack's vectors pass on it.
%% -> the number of failures (0 or 1).
run_named_load(PacksDir, ModelsDir) ->
    Candidates =
        lists:sort(
          [{filelib:file_size(filename:join([PacksDir, Pack, "pack.def"])), Pack}
           || Pack <- lists:usort([P || {P, _} <- vector_files(PacksDir)]),
              filelib:is_regular(filename:join([PacksDir, Pack, "pack.def"])),
              self_contained(PacksDir, Pack)]),
    case Candidates of
        [] -> 0;
        [{_, Pack} | _] ->
            try
                E = gt_engine:load_packs(gt_engine:new(), PacksDir, [Pack], ModelsDir),
                1 = maps:size(gt_engine:packs(E)),
                [] = [{Name, Why} || {P, File} <- vector_files(PacksDir), P =:= Pack,
                                     {error, Name, Why} <- [run_vector_file(E, File)]],
                io:format("named load: pack ~s alone, ~p module(s)~n",
                          [Pack, maps:size(gt_engine:modules(E))]),
                0
            catch C:R ->
                io:format("FAIL named load of ~s: ~ts~n", [Pack, why({exception, C, R})]),
                1
            end
    end.

%% Does every vector of the pack convert from and to the pack itself?
self_contained(PacksDir, Pack) ->
    Name = list_to_binary(Pack),
    lists:all(
      fun({P, _}) when P =/= Pack -> true;
         ({_, File}) ->
              try
                  {ok, Bin} = file:read_file(File),
                  Obj = gt_json:parse(Bin),
                  gt_json:get(Obj, <<"from">>) =:= {ok, Name}
                      andalso gt_json:get(Obj, <<"to">>) =:= {ok, Name}
              catch _:_ -> false
              end
      end, vector_files(PacksDir)).

%% ===================================================================
%% malformed inputs (spec/engine-spec.md, Malformed input)
%% ===================================================================
%% The input of the first ?PER_PACK conversion vectors of each pack, and of
%% every vector of the packs `conformance-malformed-*`, `conformance-tlv*`,
%% `conformance-armor*` and `conformance-sixbit*`, is cut short at prefixes and has
%% single bytes replaced, and each result is converted as the vector
%% converts. A case passes when convert returns bytes or fails with a
%% conversion error of a named kind whose message begins with the kind and
%% a colon; any other exception, and a failure the engine could not
%% classify, fails it. The cases are a fixed function of the vectors:
%%   prefixes   every length below the input's when it has at most 16
%%              bytes, else 8 lengths spread evenly from 0;
%%   bytes      at most 8 positions spread evenly, each set to the next
%%              entry of ?MUTANTS that differs from the byte there.
%% Only the first failing case of a vector is printed.
%% -> {Passed, Failed} in cases.
-define(MUTANTS, "\"\\<>{}[],:&/='0189afz+-.e \0\377\n").
-define(PER_PACK, 5).
-define(KINDS, ['no-kind', 'missing-root', 'malformed-wire', 'transform-decode',
                'transform-encode', 'undeclared-key', 'key-type-mismatch']).

run_malformed(Engine, PacksDir) ->
    {P, F, _, _} =
        lists:foldl(
          fun({Pack, File}, {P0, F0, Index, Seen}) ->
                  Nth = maps:get(Pack, Seen, 0),
                  {P1, F1} = case Nth < ?PER_PACK orelse lists:prefix("conformance-malformed-", Pack)
                                     orelse lists:prefix("conformance-tlv", Pack)
                                     orelse lists:prefix("conformance-armor", Pack)
                                     orelse lists:prefix("conformance-sixbit", Pack) of
                                 true -> malformed_vector(Engine, Pack, File, Index);
                                 false -> {0, 0}
                             end,
                  {P0 + P1, F0 + F1, Index + 1, Seen#{Pack => Nth + 1}}
          end, {0, 0, 0, #{}}, vector_files(PacksDir)),
    {P, F}.

malformed_vector(Engine, Pack, File, Index) ->
    try
        {ok, Bin} = file:read_file(File),
        Obj = gt_json:parse(Bin),
        {ok, From} = gt_json:get(Obj, <<"from">>),
        {ok, To} = gt_json:get(Obj, <<"to">>),
        {ok, Input} = gt_json:get(Obj, <<"input">>),
        true = is_binary(Input),
        Packs = gt_engine:packs(Engine),
        true = maps:is_key(From, Packs) andalso maps:is_key(To, Packs),
        Context = case gt_json:get(Obj, <<"context">>) of
                      {ok, {object, Pairs}} -> Pairs;
                      _ -> none
                  end,
        {Obj, From, To, Input, Context}
    of
        {Obj1, From1, To1, Input1, Context1} ->
            Name = case gt_json:get(Obj1, <<"name">>) of
                       {ok, N} -> N;
                       absent -> filename:basename(File)
                   end,
            Bad = [{What, Why}
                   || {What, Mutant} <- malformed_cases(Input1, Index),
                      {error, Why} <- [malformed_case(Engine, From1, To1, Mutant, Context1)]],
            Cases = length(malformed_cases(Input1, Index)),
            case Bad of
                [] -> {Cases, 0};
                [{What, Why} | _] ->
                    io:format("FAIL ~s/~s: malformed input (~0p): ~0P~n",
                              [Pack, Name, What, Why, 12]),
                    {Cases - length(Bad), length(Bad)}
            end
    catch _:_ ->
        {0, 0}                       % a vector the conversion run reports
    end.

%% Cases of rulings 36 to 40 of 0.8 that the cut and replaced inputs do not
%% reach, on the packs `conformance-malformed-*` (each skipped when its pack
%% is not loaded): `refused` fails with `malformed-wire`, `read` converts.
ruling_cases() ->
    J = <<"conformance-malformed-json">>,
    P = <<"conformance-malformed-protobuf">>,
    B = <<"conformance-malformed-bits">>,
    X = <<"conformance-malformed-xml">>,
    G = <<"conformance-groups-protobuf">>,
    T = <<"conformance-tlv">>,
    F = <<"conformance-tlv-fixed">>,
    A = <<"conformance-armor">>,
    S = <<"conformance-armor-seq">>,
    [{J, refused, <<"{\"id\":\"u1\",\"n\":01}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":-01}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":+1}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":.5}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":1.}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":1.e2}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":1e}">>},
     {J, refused, <<"{\"id\":\"u1\",\"n\":-}">>},
     {J, refused, <<"{\"id\":\"u\\q1\"}">>},
     {J, refused, <<"{\"id\":\"u\t1\"}">>},
     {J, refused, <<"{\"id\":\"u", 0, "1\"}">>},
     {J, refused, <<"{\"id\":\"\\u+041\"}">>},
     {J, refused, <<"{\"id\":\"u1\",}">>},
     {J, read, <<"{\"id\":\"u\\t1\",\"n\":-0.5e+2,\"m\":0}">>},
     {P, refused, <<"0b">>},                              % wire type 3
     {P, refused, <<"0c">>},                              % wire type 4
     {P, refused, <<"0e">>},                              % wire type 6
     {P, refused, <<"808080801000">>},                    % field number 2^29
     {P, read, <<"f8ffffff0f00">>},                       % field number 2^29-1
     {P, read, <<"10ffffffffffffffffff01">>},             % a varint of ten bytes
     {P, refused, <<"22020a05">>},                        % a length past its submessage
     {P, refused, <<"-a0275311005">>},
     {B, refused, <<"-100000002000000">>},
     {B, refused, <<"+0100000002000000">>},
     {B, refused, <<"0x0100000002000000">>},
     {X, refused, <<" \n">>},
     {X, refused, <<"<?xml version=\"1.0\"?>">>},
     {X, refused, <<"<!-- no element -->">>},
     {X, refused, <<"<event uid=\"u1\"/><!DOCTYPE x>">>},
     %% ruling 40
     {B, refused, <<"01000000\v02000000">>},              % vertical tab
     {B, refused, <<"01000000\f02000000">>},              % form feed
     {B, refused, <<"01000000", 16#C2, 16#A0, "02000000">>},   % no-break space
     {B, read, <<" 01\t000000\r\n02000000\n">>},
     {P, refused, <<"0000">>},                            % field number 0
     {P, refused, <<"0f">>},                              % wire type 7
     {P, refused, <<"10ffffffffffffffffff02">>},          % tenth byte above 1
     {P, refused, <<"10ffffffffffffffffff7f">>},
     {P, refused, <<"ffffffffffffffffff0200">>},          % the same in a tag
     {P, read, <<"1080808080808080808001">>},             % bit 63 alone
     {G, read, <<"0a01751a040a020105">>},                 % a packed field
     {G, refused, <<"0a01751a040a020180">>},              % its last varint cut
     {G, refused, <<"0a01751a0d0a0bffffffffffffffffffff01">>},   % eleven bytes, packed
     {J, refused, <<"{\"id\":\"\\ud83d\"}">>},
     {J, refused, <<"{\"id\":\"\\ude00\"}">>},
     {J, refused, <<"{\"id\":\"\\ud83dx\"}">>},
     {J, refused, <<"{\"id\":\"\\ud83d\\u0041\"}">>},
     {J, refused, <<"{\"id\":\"\\ude00\\ud83d\"}">>},
     {J, read, <<"{\"id\":\"\\ud83d\\ude00\"}">>},
     {<<"conformance-malformed-geojson">>, refused,
      <<"{\"type\":\"Feature\",\"geometry\":null,\"properties\":{\"name\":\"\\ud83d\"},\"id\":\"u1\"}">>},
     {X, refused, <<"<!DOCTYPE event><event uid=\"u1\"/>">>},
     {X, refused, <<"<?xml version=\"1.0\"?><!DOCTYPE event [<!ENTITY e \"x\">]><event uid=\"&e;\"/>">>},
     {X, refused, <<"<event uid=\"u1\"><!DOCTYPE event></event>">>},
     {X, refused, <<"<event uid=\"u1\"><!ENTITY e \"x\"></event>">>},
     {X, refused, <<"<event uid=\"&e;\"/>">>},
     {X, refused, <<"<event uid=\"&#+65;\"/>">>},
     {X, refused, <<"<event uid=\"&#-65;\"/>">>},
     {X, refused, <<"<event uid=\"&#x+41;\"/>">>},
     {X, refused, <<"<event uid=\"&#;\"/>">>},
     {X, refused, <<"<event uid=\"&#x;\"/>">>},
     {X, refused, <<"<event uid=\"&#X41;\"/>">>},
     {X, refused, <<"<event uid=\"&#0;\"/>">>},
     {X, refused, <<"<event uid=\"&#8;\"/>">>},
     {X, refused, <<"<event uid=\"&#xD800;\"/>">>},
     {X, refused, <<"<event uid=\"&#xFFFE;\"/>">>},
     {X, refused, <<"<event uid=\"&#x110000;\"/>">>},
     {X, read, <<"<event uid=\"&#65;&#x42;&#9;&#x10FFFF;&amp;&lt;&gt;&quot;&apos;\"/>">>},
     %% the tlv wire (0.13)
     {T, refused, <<"060e2b34">>},                        % the key and no length
     {T, refused, <<"060e2b3400">>},                      % no checksum item
     {T, refused, <<"060e2b3488ffffffffffffffff">>},      % a set of 2^64-1 bytes
     {T, refused, <<"060e2b3481">>},                      % a long form cut short
     {T, refused, <<"060e2b3404010201023743">>},          % a wrong checksum
     {T, refused, <<"060e2b3405ffffffff7f">>},            % a tag of five bytes
     {F, read, <<>>},                                     % an empty set
     {F, read, <<"0b0000">>},                             % an empty value
     {F, read, <<"0b0001ff0c0000">>},
     {F, refused, <<"0b">>},                              % a tag alone
     {F, refused, <<"0b00">>},                            % half a length
     {F, refused, <<"0b0001">>},                          % a value past the set
     {F, refused, <<"0bffff00">>},
     {F, refused, <<"0b000">>},
     %% six-bit armor (0.14): every character is checked, wherever it stands
     {A, read, <<"1CB>fwT0p:Qr@00">>},
     {A, read, <<"1CB>fwT0p:Qr@0w">>},                    % fill bits set
     {A, read, <<"1CB>fwT0p:Qr@00www">>},                 % characters past the lines
     {A, refused, <<"1CB>fwT0p:Qr@0">>},                  % short of the callsign
     {A, refused, <<"1CB>fwT0p:Qr@0X">>},                 % 0x58, just past W
     {A, refused, <<"1CB>fwT0p:Qr@0_">>},                 % 0x5F
     {A, refused, <<"1CB>fwT0p:Qr@0/">>},                 % 0x2F, just below 0
     {A, refused, <<"1CB>fwT0p:Qr@0x">>},                 % 0x78, just past w
     {A, refused, <<"1CB>fwT0p:Qr@00\r\n">>},
     {A, refused, <<" 1CB>fwT0p:Qr@00">>},
     {A, refused, <<"1CB>fwT0p:Qr@00\t">>},
     {A, refused, <<"1CB>fwT0p:Qr@0", 0>>},
     {A, refused, <<"1CB>fwT0p:Qr@0", 16#C2, 16#A0>>},
     {A, refused, <<"X">>},                               % a bad character where the type is
     {A, refused, <<"380O">>},                            % items cut short
     {S, read, <<"9D246">>},
     {S, read, <<"@D246">>},                              % @ (0x40) stands for 16
     {S, read, <<"9D246www">>},
     {S, refused, <<"9D24">>},
     {S, refused, <<"9D24 6">>},
     {S, refused, <<"9D246\n">>},
     {S, refused, <<>>}].

run_ruling_cases(Engine) ->
    Packs = gt_engine:packs(Engine),
    lists:foldl(
      fun({Format, Want, Input}, {P, F}) ->
              Got = try gt_engine:convert(Engine, Format, Format, Input) of
                        Out when is_binary(Out) -> read
                    catch
                        error:{convert_error, 'malformed-wire', "malformed-wire:" ++ _} -> refused;
                        Class:Reason -> {Class, Reason}
                    end,
              case Got of
                  Want -> {P + 1, F};
                  _ ->
                      io:format("FAIL ~s: malformed input ~0p: expected ~s, got ~0P~n",
                                [Format, Input, Want, Got, 12]),
                      {P, F + 1}
              end
      end, {0, 0}, [C || {Format, _, _} = C <- ruling_cases(), maps:is_key(Format, Packs)]).

%% -> [{{cut, Length} | {byte, Position, Value}, Input}]
malformed_cases(Input, Index) ->
    Size = byte_size(Input),
    Cuts = case Size =< 16 of
               true -> lists:seq(0, Size - 1);
               false -> spread(Size, 8)
           end,
    Mutants = ?MUTANTS,
    NM = length(Mutants),
    [{{cut, L}, binary:part(Input, 0, L)} || L <- Cuts] ++
        [begin
             <<Before:Pos/binary, Old, After/binary>> = Input,
             New = mutant(Old, Mutants, (Pos + Index) rem NM, NM),
             {{byte, Pos, New}, <<Before/binary, New, After/binary>>}
         end || Pos <- spread(Size, 8)].

%% At most N offsets below Size, spread evenly from 0, each once.
spread(Size, N) -> lists:usort([(I * Size) div N || I <- lists:seq(0, N - 1), Size > 0]).

mutant(Old, Mutants, I, NM) ->
    case lists:nth(I + 1, Mutants) of
        Old -> lists:nth(((I + 1) rem NM) + 1, Mutants);
        New -> New
    end.

malformed_case(Engine, From, To, Input, Context) ->
    try gt_engine:convert(Engine, From, To, Input, Context) of
        Out when is_binary(Out) -> ok;
        Other -> {error, {returned, Other}}
    catch
        error:{convert_error, Kind, Msg} ->
            Named = lists:member(Kind, ?KINDS)
                andalso is_list(Msg)
                andalso lists:prefix(atom_to_list(Kind) ++ ":", Msg)
                andalso string:find(Msg, "[unclassified:") =:= nomatch,
            case Named of
                true -> ok;
                false -> {error, {error_without_a_named_kind, Kind, Msg}}
            end;
        Class:Reason -> {error, {exception, Class, Reason}}
    end.

%% ===================================================================
%% failure text
%% ===================================================================
why({convert, Expect, Got}) ->
    io_lib:format("convert~n    expect ~ts~n    got    ~ts", [clip(Expect), clip(Got)]);
why({exception, error, {convert_error, _, Msg}, _}) -> io_lib:format("error ~ts", [Msg]);
why({exception, error, {convert_error, _, Msg}}) -> io_lib:format("error ~ts", [Msg]);
why({exception, error, {load_error, _, Msg}}) -> io_lib:format("error ~ts", [Msg]);
why(Other) -> io_lib:format("~tp", [Other]).

%% Long messages are shown from a little before their first difference.
clip(Bin) when byte_size(Bin) =< 2000 -> Bin;
clip(Bin) -> <<(binary:part(Bin, 0, 2000))/binary, " ... (", (integer_to_binary(byte_size(Bin)))/binary, " bytes)">>.
