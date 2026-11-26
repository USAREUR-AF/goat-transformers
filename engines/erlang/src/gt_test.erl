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
%%   - one instance used by several processes at once: each conversion gives
%%     what it gives alone (rulings 1b and 1c of 0.25).
%% Every failure is printed as "FAIL <pack>/<vector>: <why>"; then the counts
%% "vectors: N/M passed", "load vectors: N/M passed", "capability vectors:
%% N/M passed", "malformed inputs: N/M passed" and "concurrent conversions:
%% N/M passed" (one instance converting in several processes at once,
%% rulings 1b and 1c of 0.25: run_concurrent/2). Exits non-zero on any
%% failure.
-module(gt_test).
-include_lib("kernel/include/file.hrl").
-export([main/1, run/1, run/2, run_reduced/3, run_profile_checks/0]).
-include("gt_wires.hrl").

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
    {UPass0, UFail0} = run_unit_checks(),
    {PPass, PFail} = run_profile_checks(),
    {CostPass, CostFail} = run_cost_check(),
    {UPass, UFail} = {UPass0 + PPass + CostPass, UFail0 + PFail + CostFail},
    {MPass, MFail} = {MPass0 + RPass, MFail0 + RFail},
    {KPass, KFail} = run_concurrent(PacksDir, ModelsDir),
    io:format("vectors: ~p/~p passed~n", [Pass, Pass + Fail]),
    io:format("load vectors: ~p/~p passed~n", [LPass, LPass + LFail]),
    io:format("capability vectors: ~p/~p passed~n", [CPass, CPass + CFail]),
    io:format("malformed inputs: ~p/~p passed~n", [MPass, MPass + MFail]),
    io:format("concurrent conversions: ~p/~p passed~n", [KPass, KPass + KFail]),
    io:format("unit checks: ~p/~p passed~n", [UPass, UPass + UFail]),
    io:format("elapsed: ~.1f s~n", [(erlang:monotonic_time(millisecond) - T0) / 1000]),
    case Fail + LFail + CFail + NFail + MFail + KFail + UFail of
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
           fun({F, Bin}, E) ->
                   try gt_engine:load_model(E, Bin)
                   catch C:R ->
                       io:format("FAIL loading model ~s: ~ts~n", [F, why({exception, C, R})]),
                       E
                   end
           end, gt_engine:new(), gt_engine:model_texts(ModelsDir)),
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
            Run = fun() -> gt_engine:convert_run(Engine, From, To, Input, Context) end,
            Conv = case {G(<<"expect">>), G(<<"expect_error">>), G(<<"expect_results">>), G(<<"run">>)} of
                       {Expect, undefined, undefined, undefined} when is_binary(Expect) ->
                           check_convert(Convert, Expect);
                       {undefined, Kind, undefined, undefined} when is_binary(Kind) ->
                           check_convert_error(Convert, Kind);
                       %% runs of inner messages (0.92)
                       {undefined, Kind, undefined, true} when is_binary(Kind) ->
                           check_convert_error(Run, Kind);
                       {undefined, undefined, {array, Wants}, undefined} ->
                           check_run(Run(), Wants);
                       _ ->
                           {error, vector_needs_exactly_one_of_expect_expect_error_and_expect_results}
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

%% The results of convert_run, one for one (0.92).
check_run(Got, Wants) when length(Got) =/= length(Wants) ->
    {error, {run_results, {expected, length(Wants)}, {got, Got}}};
check_run(Got, Wants) ->
    Bad = [{I, W, G} || {I, W, G} <- lists:zip3(lists:seq(1, length(Got)), Wants, Got),
                        not run_result_ok(W, G)],
    case Bad of
        [] -> ok;
        _ -> {error, {run_results, Bad}}
    end.

run_result_ok({object, [{<<"expect">>, Want}]}, {ok, Out}) -> Out =:= Want;
run_result_ok({object, [{<<"expect_error">>, Want}]}, {error, Kind, Msg}) ->
    atom_to_binary(Kind) =:= Want andalso lists:prefix(binary_to_list(Want) ++ ":", Msg);
run_result_ok(_, _) -> false.

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
             %% Version 0.34: the kind the inner pack selected
             ({<<"@inner_kind">>, Expected}) ->
                  case maps:get(inner_kind, Entity, undefined) of
                      {_Format, Expected} -> false;
                      Other -> {true, {'@inner_kind', Expected, Other}}
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
absent_in(<<"@inner_kind">>, Entity) -> maps:get(inner_kind, Entity, undefined) =:= undefined;
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
%% The vector files are listed once and grouped by pack: listing them again
%% for each pack made this check grow as packs x packs.
run_named_load(PacksDir, ModelsDir) ->
    Files = vector_files(PacksDir),
    ByPack = lists:foldl(fun({P, F}, M) -> M#{P => [F | maps:get(P, M, [])]} end,
                         #{}, Files),
    Candidates =
        lists:sort(
          [{filelib:file_size(filename:join([PacksDir, Pack, "pack.def"])), Pack}
           || Pack <- lists:sort(maps:keys(ByPack)),
              filelib:is_regular(filename:join([PacksDir, Pack, "pack.def"])),
              self_contained(Pack, maps:get(Pack, ByPack))]),
    case Candidates of
        [] -> 0;
        [{_, Pack} | _] ->
            try
                %% with the packs its `inner` lines name (0.34)
                Loaded = gt_engine:inner_names(PacksDir, [Pack]),
                E = gt_engine:load_packs(gt_engine:new(), PacksDir, Loaded, ModelsDir),
                true = maps:size(gt_engine:packs(E)) =:= length(Loaded),
                [] = [{Name, Why} || {P, File} <- Files, P =:= Pack,
                                     {error, Name, Why} <- [run_vector_file(E, File)]],
                io:format("named load: pack ~s alone, ~p module(s)~n",
                          [Pack, maps:size(gt_engine:modules(E))]),
                0
            catch C:R ->
                io:format("FAIL named load of ~s: ~ts~n", [Pack, why({exception, C, R})]),
                1
            end
    end.

%% ===================================================================
%% one instance, several processes (rulings 1b and 1c of 0.25)
%% ===================================================================
%% The cases are the first ?CONC_PER_PACK conversion vectors of each pack
%% whose directory name begins with `conformance-` (every wire), with any
%% context and `max_items`, those that convert and those that fail alike.
%% One instance is loaded with the packs the cases name that the directory
%% holds, with the modules they need (a pack that does not load is left
%% out, and its cases are `unknown-format` alike everywhere), and kept in a
%% persistent term, so that every process reads that one instance and none
%% copies it. The reference result of each case is its conversion alone, in
%% a new process. Then ?CONC_WORKERS processes, started together, each
%% convert every case on that instance, each in its own order (the case list
%% rotated), so that every conversion follows conversions of other
%% messages, failed ones included, while other processes convert at the
%% same time. A case passes when every worker's result (the bytes, or the
%% error kind and message) equals its reference. Prints "FAIL concurrent
%% <pack>/<file>: ..." for a case that does not.
-define(CONC_PER_PACK, 2).
-define(CONC_WORKERS, 4).
-define(CONC_ENGINE, {gt_test, concurrent_engine}).

run_concurrent(PacksDir, ModelsDir) ->
    ByPack = lists:foldl(fun({P, F}, M) ->
                                 case lists:prefix("conformance-", P) of
                                     true -> M#{P => [F | maps:get(P, M, [])]};
                                     false -> M
                                 end
                         end, #{}, vector_files(PacksDir)),
    Cases = list_to_tuple(
              [{P, filename:basename(F), Conv}
               || P <- lists:sort(maps:keys(ByPack)),
                  F <- lists:sublist(lists:sort(maps:get(P, ByPack)), ?CONC_PER_PACK),
                  Conv <- [concurrent_case(F)], Conv =/= skip]),
    N = tuple_size(Cases),
    %% with the packs their `inner` lines name (0.34)
    Names = gt_engine:inner_names(
              PacksDir,
              lists:usort([Name || {_, _, {_, From, To, _, _}} <- tuple_to_list(Cases),
                                   Name <- [From, To],
                                   filelib:is_regular(filename:join([PacksDir, Name, "pack.def"]))])),
    %% one load (the model directory is read once); only when a pack does not
    %% load, one load per pack
    Engine = try gt_engine:load_packs(gt_engine:new(), PacksDir, Names, ModelsDir)
             catch _:_ ->
                 lists:foldl(fun(Name, E) ->
                                     try gt_engine:load_packs(E, PacksDir, [Name], ModelsDir)
                                     catch _:_ -> E
                                     end
                             end, gt_engine:new(), Names)
             end,
    persistent_term:put(?CONC_ENGINE, Engine),
    try run_concurrent_cases(Cases, N)
    after persistent_term:erase(?CONC_ENGINE)
    end.

run_concurrent_cases(Cases, N) ->
    Ref = [isolated(fun() -> conc_result(element(3, element(I, Cases))) end)
           || I <- lists:seq(1, N)],
    Parent = self(),
    Workers = [spawn_monitor(
                 fun() ->
                         receive go -> ok end,
                         Start = (W - 1) * N div ?CONC_WORKERS,
                         Order = [(Start + J) rem N + 1 || J <- lists:seq(0, N - 1)],
                         Results = maps:from_list(
                                     [{I, conc_result(element(3, element(I, Cases)))}
                                      || I <- Order]),
                         Parent ! {self(), [maps:get(I, Results) || I <- lists:seq(1, N)]}
                 end) || W <- lists:seq(1, ?CONC_WORKERS)],
    [Pid ! go || {Pid, _} <- Workers],
    Got = [receive
               {Pid, Rs} -> erlang:demonitor(MRef, [flush]), Rs;
               {'DOWN', MRef, process, Pid, Why} -> {down, Why}
           end || {Pid, MRef} <- Workers],
    lists:foldl(
      fun({I, R}, {P, F}) ->
              Bad = [{W, G} || {W, Rs} <- lists:zip(lists:seq(1, ?CONC_WORKERS), Got),
                               G <- [case Rs of
                                         {down, Why} -> {down, Why};
                                         _ -> lists:nth(I, Rs)
                                     end],
                               G =/= R],
              case Bad of
                  [] -> {P + 1, F};
                  [{W, G} | _] ->
                      {Pack, File, _} = element(I, Cases),
                      io:format("FAIL concurrent ~s/~s: alone ~0P, worker ~p ~0P~n",
                                [Pack, File, R, 12, W, G, 12]),
                      {P, F + 1}
              end
      end, {0, 0}, lists:zip(lists:seq(1, N), Ref)).

%% A vector file -> {MaxItems, From, To, Input, Context} | skip (unreadable,
%% or a field of the wrong type: the conversion vectors report those).
concurrent_case(File) ->
    try
        {ok, Bin} = file:read_file(File),
        Obj = gt_json:parse(Bin),
        G = fun(K) ->
                    case gt_json:get(Obj, K) of
                        {ok, V} -> V;
                        absent -> undefined
                    end
            end,
        From = G(<<"from">>),
        To = G(<<"to">>),
        Input = G(<<"input">>),
        true = is_binary(From) andalso is_binary(To) andalso is_binary(Input),
        Context = case G(<<"context">>) of
                      undefined -> none;
                      {object, Pairs} -> Pairs
                  end,
        Max = case G(<<"max_items">>) of
                  undefined -> default;
                  M when is_integer(M), M >= 0 -> M
              end,
        {Max, From, To, Input, Context}
    catch _:_ -> skip
    end.

conc_result({Max, From, To, Input, Context}) ->
    E0 = persistent_term:get(?CONC_ENGINE),
    E = case Max of
            default -> E0;
            _ -> gt_engine:set_max_items(E0, Max)
        end,
    try gt_engine:convert(E, From, To, Input, Context) of
        Out -> {ok, Out}
    catch
        error:{convert_error, Kind, Msg} -> {error, Kind, Msg};
        Class:Reason -> {crash, Class, Reason}
    end.

%% The value of F in a new process.
isolated(F) ->
    {Pid, MRef} = spawn_monitor(fun() -> exit({result, F()}) end),
    receive
        {'DOWN', MRef, process, Pid, {result, R}} -> R;
        {'DOWN', MRef, process, Pid, Why} -> {down, Why}
    end.

%% Does every vector of the pack (its vector files) convert from and to the
%% pack itself?
self_contained(Pack, PackFiles) ->
    Name = list_to_binary(Pack),
    lists:all(
      fun(File) ->
              try
                  {ok, Bin} = file:read_file(File),
                  Obj = gt_json:parse(Bin),
                  gt_json:get(Obj, <<"from">>) =:= {ok, Name}
                      andalso gt_json:get(Obj, <<"to">>) =:= {ok, Name}
              catch _:_ -> false
              end
      end, PackFiles).

%% ===================================================================
%% malformed inputs (spec/engine-spec.md, Malformed input)
%% ===================================================================
%% The input of the first ?PER_PACK conversion vectors of each pack, and of
%% every vector of the packs `conformance-malformed-*`, `conformance-tlv*`,
%% `conformance-armor*`, `conformance-sixbit*`, `conformance-uper*` (0.19)
%% and `conformance-cbor*` (0.28),
%% is cut short at prefixes and has
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
                'transform-encode', 'undeclared-key', 'key-type-mismatch',
                %% raised where decode or encode reaches an `inner` line (0.34)
                'unknown-format', 'bad-directive', 'distribution-violation',
                %% a run that does not hold one message (0.92)
                'message-count']).

run_malformed(Engine, PacksDir) ->
    {P, F, _, _} =
        lists:foldl(
          fun({Pack, File}, {P0, F0, Index, Seen}) ->
                  Nth = maps:get(Pack, Seen, 0),
                  {P1, F1} = case Nth < ?PER_PACK orelse lists:prefix("conformance-malformed-", Pack)
                                     orelse lists:prefix("conformance-tlv", Pack)
                                     orelse lists:prefix("conformance-armor", Pack)
                                     orelse lists:prefix("conformance-sixbit", Pack)
                                     orelse lists:prefix("conformance-uper", Pack)
                                     orelse lists:prefix("conformance-cbor", Pack) of
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
    C = <<"conformance-cbor">>,
    CA = <<"conformance-cbor-array">>,
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
     {S, refused, <<>>}] ++ cbor_cases(C, CA).

%% Hostile CBOR (0.28): nesting through arrays, maps and tags far past the
%% depth limit, declared lengths far past the input, indefinite items that
%% never end, and chunks and breaks where they cannot stand. Each must be
%% refused, at once and without taking memory for what the heads declare.
cbor_cases(C, CA) ->
    Rep = fun(Hex, N) -> binary:copy(Hex, N) end,
    %% a head of major type MT declaring the largest length of each width
    Huge = [?CBOR(gt_hex:bytes_to_hex(<<((MT bsl 5) bor AI), Arg/binary>>))
            || MT <- [2, 3, 4, 5],
               {AI, Arg} <- [{27, <<-1:64>>}, {26, <<-1:32>>}, {25, <<-1:16>>}, {24, <<255>>}]],
    [{C, refused, <<"a200010a", (Rep(<<"81">>, 100000))/binary, "00">>},       % arrays
     {C, refused, <<"a200010a", (Rep(<<"a101">>, 100000))/binary, "00">>},     % maps
     {C, refused, <<"a200010a", (Rep(<<"c1">>, 100000))/binary, "00">>},       % tags
     {C, refused, <<"a200010a", (Rep(<<"9f">>, 100000))/binary>>},             % indefinite arrays
     {C, refused, <<"a200010a", (Rep(<<"bf01">>, 100000))/binary>>},           % indefinite maps
     {C, refused, <<"a200010a", (Rep(<<"d9ffff">>, 70))/binary, "00">>},       % long tag heads
     {C, refused, <<(Rep(<<"c1">>, 64))/binary, "a10001">>},                   % the top under 64 tags
     {C, read, <<(Rep(<<"c1">>, 63))/binary, "a10001">>},                      % 63 tags and the map: 64
     {C, refused, <<"a200010a9f", (Rep(<<"00">>, 5000))/binary>>},             % no break
     {C, refused, <<"a200010a5f", (Rep(<<"4100">>, 5000))/binary>>},           % byte chunks, no break
     {C, refused, <<"a200010a7f", (Rep(<<"6161">>, 5000))/binary>>},           % text chunks, no break
     {C, refused, <<"a200010a5f6161ff">>},                                     % a text chunk in bytes
     {C, refused, <<"a200010a5f5fffff">>},                                     % an indefinite chunk
     {C, refused, <<"a200010a7f7fffff">>},
     {C, refused, <<"a200010abf01ff">>},                                       % a break where a value stands
     {C, refused, <<"a200010abf0101">>},                                       % a map with no break
     {C, read, <<"a200010abf0101ff">>},
     {C, refused, <<"a200010a1f">>},                                           % ai 31 on major 0
     {C, refused, <<"a200010a3f">>},                                           % ai 31 on major 1
     {C, refused, <<"a200010adf00">>},                                         % ai 31 on a tag
     {C, refused, <<"a200010afc">>}, {C, refused, <<"a200010afd">>}, {C, refused, <<"a200010afe">>},
     {C, refused, <<"a200010af8">>},                                           % a simple value cut short
     {C, read, <<"a200010af820">>},
     {C, refused, <<"a200010af9">>}, {C, refused, <<"a200010afa0000">>}, {C, refused, <<"a200010afb00">>},
     {C, read, <<"a200010afb7ff8000000000001">>},                              % a NaN with a payload as residue
     {C, refused, <<"a200010a62c328">>},                                       % invalid UTF-8
     {C, refused, <<"a200010a63eda080">>},                                     % a surrogate
     {C, refused, <<"a200010a62c080">>},                                       % an overlong form
     {C, refused, <<"a200010a64f4908080">>},                                   % above U+10FFFF
     {C, read, <<"a200010a64f09f9880">>},
     {C, refused, <<"a20a000a01">>},                                       % a key twice
     {C, refused, <<"a2f97e0000fb7ff800000000000001">>},                   % NaN keys equal
     {C, refused, <<"a281000081000001">>},                                 % array keys equal
     {C, read, <<"a30001810000820000 01">>},                                   % [0] and [0,0]: two keys
     {C, refused, <<"">>},
     {CA, refused, <<"d2">>},                                              % a tag and nothing
     {CA, refused, <<"db">>},
     {CA, refused, <<"dbffffffffffffffff">>}] ++
        [{C, refused, <<"a200010a", H/binary>>} || H <- Huge] ++
        [{C, refused, <<"a200010a5f", H/binary, "ff">>} || <<"5", _/binary>> = H <- Huge].

%% The check values of the CRC-32 of 0.27 ("The CRC"), a part of the tlv wire.
-if(?W_TLV).
run_unit_checks() ->
    lists:foldl(
      fun({Name, Got, Want}, {P, F}) ->
              case Got =:= Want of
                  true -> {P + 1, F};
                  false ->
                      io:format("FAIL unit ~s: expected ~.16b, got ~0p~n", [Name, Want, Got]),
                      {P, F + 1}
              end
      end, {0, 0},
      [{"crc32 of 123456789", gt_tlv:crc32(<<"123456789">>), 16#0376E6E7},
       {"crc32 of no bytes", gt_tlv:crc32(<<>>), 16#FFFFFFFF}]).
-else.
run_unit_checks() -> {0, 0}.
-endif.

%% ===================================================================
%% Version 0.93 in the library: rulings 5 and 6, and a controlled inner
%% pack (0.34) that never loads. Each check builds its own tree in a
%% temporary directory and removes it.
%% ===================================================================
run_profile_checks() ->
    Root = filename:join(case os:getenv("TMPDIR") of
                             false -> "/tmp";
                             T -> T
                         end,
                         "gt-erlang-093-" ++ os:getpid() ++ "-"
                         ++ integer_to_list(erlang:unique_integer([positive]))),
    try
        Checks = profile_checks(Root),
        lists:foldl(
          fun({_Name, ok}, {P, F}) -> {P + 1, F};
             ({Name, {fail, Why}}, {P, F}) ->
                  io:format("FAIL profile check ~s: ~0p~n", [Name, Why]),
                  {P, F + 1}
          end, {0, 0}, Checks)
    after
        rm_tree(Root)
    end.

-define(T93_CORE, <<"module core\nversion 0.1.0\ndistribution public\n"
                    "source \"goat-transformers spec/engine-spec.md, Version 0.93 (synthetic test, no external standard)\"\n"
                    "key n int - \"a test key\"\nkey w int - \"a test key\"\n">>).
-define(T93_CTL, <<"module ctl\nversion 0.1.0\ndistribution controlled\n"
                   "source \"goat-transformers spec/engine-spec.md, Version 0.93 (synthetic test, no external standard)\"\n"
                   "key c int - \"a test key\"\n">>).

t93_pack(Format, Dist, Uses, Lines) ->
    iolist_to_binary(
      ["format ", Format, "\nversion 0.1.0\ndistribution ", Dist, "\n",
       "source \"goat-transformers spec/engine-spec.md, Version 0.93 (synthetic test, no external standard)\"\n",
       [["uses ", U, "\n"] || U <- Uses],
       "wire bits\nlayout sequential\nbit_order msb\n", Lines]).

%% A tree: Root/<Name>/model/<file> and Root/<Name>/packs/<dir>/pack.def.
t93_tree(Root, Name, Modules, Packs) ->
    Dir = filename:join(Root, Name),
    lists:foreach(fun({F, Text}) -> write_file(filename:join([Dir, "model", F]), Text) end, Modules),
    lists:foreach(fun({D, Text}) -> write_file(filename:join([Dir, "packs", D, "pack.def"]), Text) end, Packs),
    {filename:join(Dir, "packs"), filename:join(Dir, "model")}.

write_file(Path, Text) ->
    ok = filelib:ensure_dir(Path),
    ok = file:write_file(Path, Text).

rm_tree(Path) ->
    case file:read_link_info(Path) of
        {ok, #file_info{type = directory}} ->
            {ok, Es} = file:list_dir_all(Path),
            [rm_tree(filename:join(Path, E)) || E <- Es],
            file:del_dir(Path);
        {ok, _} -> file:delete(Path);
        {error, _} -> ok
    end.

%% The result of F: {ok, Value} or {Class, Kind} for a load or convert error.
t93_try(F) ->
    try F() of
        V -> {ok, V}
    catch
        error:{load_error, K, _} -> {load_error, K};
        error:{convert_error, K, _} -> {convert_error, K};
        C:R -> {C, R}
    end.

t93_check(Name, Got, Want) ->
    case Got of
        Want -> {Name, ok};
        _ -> {Name, {fail, [{expected, Want}, {got, Got}]}}
    end.

t93_limit(E) -> maps:get(max_distribution, E).

profile_checks(Root) ->
    Profiles = [open, <<"open+copyleft">>, "everything"],
    Inner = <<"t93-inner">>, Outer = <<"t93-outer">>,
    OuterDef = t93_pack(Outer, "public", [], "field n 8 uint\ninner t93-inner\n"),
    %% a plain tree: one public pack, one controlled pack (in no profile)
    {PP, PM} = t93_tree(Root, "plain", [{"core.def", ?T93_CORE}],
                        [{"pub", t93_pack(<<"t93-pub">>, "public", [], "field n 8 uint\n")},
                         {"ctl", t93_pack(<<"t93-ctl">>, "controlled", [], "field n 8 uint\n")}]),
    CtlText = t93_pack(<<"t93-ctl">>, "controlled", [], "field n 8 uint\n"),
    Held = gt_engine:load_model(gt_engine:new(), ?T93_CTL),   % a controlled module held
    Missing = filename:join(Root, "no-such-dir"),
    %% (a) inner pack not shown public; (b) shown public, using a controlled module
    {AP, AM} = t93_tree(Root, "inner-a", [{"core.def", ?T93_CORE}],
                        [{"t93-outer", OuterDef},
                         {"t93-inner", t93_pack(Inner, "controlled", [], "field w 8 uint\n")}]),
    {BP, BM} = t93_tree(Root, "inner-b", [{"core.def", ?T93_CORE}, {"ctl.def", ?T93_CTL}],
                        [{"t93-outer", OuterDef},
                         {"t93-inner", t93_pack(Inner, "public", ["ctl"], "field ctl.c 8 uint\n")}]),
    Entity = #{model => #{<<"n">> => 5, <<"w">> => 6, <<"ctl.c">> => 7}, lists => #{},
               residue => [], kind => undefined},
    Rule6 =
        [%% ruling 6: a bad profile name is bad-licence first, before the
         %% instance check and before anything is read
         t93_check("6: a bad profile name is bad-licence",
                   t93_try(fun() -> gt_engine:load_dir(gt_engine:new(), Missing, Missing, "closed") end),
                   {load_error, 'bad-licence'}),
         t93_check("6: a bad profile name comes before the instance check",
                   t93_try(fun() -> gt_engine:load_packs(Held, Missing, [], Missing, nonsense) end),
                   {load_error, 'bad-licence'}),
         %% then the instance check, before anything is read (Missing is not read)
         t93_check("6: a profile on an instance holding a controlled module is distribution-refused",
                   t93_try(fun() -> gt_engine:load_dir(Held, Missing, Missing, open) end),
                   {load_error, 'distribution-refused'}),
         t93_check("6: a profile on an instance holding a controlled pack is distribution-refused",
                   t93_try(fun() ->
                                   E = gt_engine:load_pack(gt_engine:load_model(gt_engine:new(), ?T93_CORE),
                                                           CtlText),
                                   gt_engine:load_packs(E, Missing, [], Missing, everything)
                           end),
                   {load_error, 'distribution-refused'}),
         %% both refuse with the limit unchanged and no trace: the instance
         %% is a value, and after either refusal it is as it was
         t93_check("6: after both refusals the instance is unchanged and its limit is still controlled",
                   (fun() ->
                       _ = t93_try(fun() -> gt_engine:load_dir(Held, Missing, Missing, "closed") end),
                       _ = t93_try(fun() -> gt_engine:load_dir(Held, Missing, Missing, open) end),
                       {t93_limit(Held), maps:is_key(profile_limit, Held),
                        t93_limit(gt_engine:set_max_distribution(Held, public)),
                        t93_limit(gt_engine:set_max_distribution(
                                    gt_engine:set_max_distribution(Held, public), controlled))}
                   end)(),
                   {controlled, false, public, controlled}),
         %% then the limit is public, also when the caller set controlled
         %% (ruling 5), and setting controlled afterwards has no effect
         t93_check("5/6: a profile load sets the limit to public over controlled",
                   t93_try(fun() ->
                                   E0 = gt_engine:set_max_distribution(gt_engine:new(), controlled),
                                   E = gt_engine:load_dir(E0, PP, PM, open),
                                   {t93_limit(E), lists:sort(maps:keys(gt_engine:packs(E)))}
                           end),
                   {ok, {public, [<<"t93-pub">>]}}),
         t93_check("6: setting controlled after a profile load is no error and has no effect",
                   t93_try(fun() ->
                                   E = gt_engine:load_packs(gt_engine:new(), PP, [<<"pub">>], PM, open),
                                   t93_limit(gt_engine:set_max_distribution(E, controlled))
                           end),
                   {ok, public}),
         t93_check("6: a controlled text loaded directly after a profile load is distribution-refused",
                   t93_try(fun() ->
                                   E = gt_engine:load_dir(gt_engine:new(), PP, PM, open),
                                   gt_engine:load_pack(gt_engine:set_max_distribution(E, controlled), CtlText)
                           end),
                   {load_error, 'distribution-refused'}),
         t93_check("6: a later load with no profile is bounded by the limit",
                   t93_try(fun() ->
                                   E = gt_engine:load_packs(gt_engine:new(), PP, [<<"pub">>], PM, open),
                                   gt_engine:load_packs(gt_engine:set_max_distribution(E, controlled),
                                                        PP, [<<"ctl">>], PM)
                           end),
                   {load_error, 'distribution-refused'}),
         %% the limit stays public when the load fails later: a failed load
         %% gives no instance, so nothing it loaded before it failed is kept
         t93_check("6: a profile load that fails after the limit keeps nothing it loaded",
                   (fun() ->
                       {FP, FM} = t93_tree(Root, "fails-later", [{"core.def", ?T93_CORE}],
                                           [{"a-good", t93_pack(<<"t93-good">>, "public", [], "field n 8 uint\n")},
                                            {"b-bad", t93_pack(<<"t93-bad">>, "public", [], "field nope 8 uint\n")}]),
                       E0 = gt_engine:new(),
                       R = t93_try(fun() -> gt_engine:load_dir(E0, FP, FM, open) end),
                       {R, t93_limit(E0), gt_engine:packs(E0), gt_engine:modules(E0)}
                   end)(),
                   {{load_error, 'undeclared-key'}, controlled, #{}, #{}})],
    %% ruling 5: a file that reads as controlled when it is loaded is
    %% distribution-refused; this engine loads the bytes it checked, so a
    %% test hook changes them between the check and the load
    Swap = fun(T) -> binary:replace(T, <<"distribution public">>, <<"distribution controlled">>) end,
    Hooked = fun(F) ->
                     put({gt_engine, load_hook}, Swap),
                     try t93_try(F) after erase({gt_engine, load_hook}) end
             end,
    Rule5 =
        [t93_check("5: a pack that reads as controlled at load is distribution-refused",
                   Hooked(fun() ->
                                  E = gt_engine:load_model(gt_engine:new(), ?T93_CORE),
                                  gt_engine:load_packs(E, PP, [<<"pub">>], PM, open)
                          end),
                   {load_error, 'distribution-refused'}),
         t93_check("5: a module that reads as controlled at load is distribution-refused",
                   Hooked(fun() -> gt_engine:load_dir(gt_engine:new(), PP, PM, everything) end),
                   {load_error, 'distribution-refused'}),
         t93_check("5: the same changed text loads without a profile and the default limit",
                   Hooked(fun() -> map_size(gt_engine:packs(
                                              gt_engine:load_packs(gt_engine:new(), PP, [<<"pub">>], PM, none)))
                          end),
                   {ok, 1})],
    %% 0.34 and 0.93: an outer pack whose inner pack does not pass the
    %% profile checks loads alone; decode and encode through the inner line
    %% are unknown-format; model_keys of the outer does not fail
    InnerCases =
        lists:append(
          [[t93_check(lists:flatten(io_lib:format("0.34 ~s, profile ~s: only the outer pack loads", [Case, Prof])),
                      t93_try(fun() ->
                                      E = gt_engine:load_packs(gt_engine:new(), P,
                                                               gt_engine:inner_names(P, [Outer]), M, Prof),
                                      lists:sort(maps:keys(gt_engine:packs(E)))
                              end),
                      {ok, [Outer]}),
            t93_check(lists:flatten(io_lib:format("0.34 ~s, profile ~s: decode through the inner line", [Case, Prof])),
                      t93_try(fun() ->
                                      E = gt_engine:load_packs(gt_engine:new(), P,
                                                               gt_engine:inner_names(P, [Outer]), M, Prof),
                                      gt_engine:convert(E, Outer, Outer, <<"0506">>)
                              end),
                      {convert_error, 'unknown-format'}),
            t93_check(lists:flatten(io_lib:format("0.34 ~s, profile ~s: encode through the inner line", [Case, Prof])),
                      t93_try(fun() ->
                                      E = gt_engine:load_packs(gt_engine:new(), P,
                                                               gt_engine:inner_names(P, [Outer]), M, Prof),
                                      gt_engine:encode(E, Outer, Entity)
                              end),
                      {convert_error, 'unknown-format'}),
            t93_check(lists:flatten(io_lib:format("0.34 ~s, profile ~s: model_keys of the outer pack", [Case, Prof])),
                      t93_try(fun() ->
                                      E = gt_engine:load_packs(gt_engine:new(), P,
                                                               gt_engine:inner_names(P, [Outer]), M, Prof),
                                      gt_engine:model_keys(E, Outer)
                              end),
                      {ok, [<<"n">>]})]
           || {Case, P, M} <- [{"inner not shown public", AP, AM},
                               {"inner using a controlled module", BP, BM}],
              Prof <- Profiles]),
    InnerC =
        [t93_check(lists:flatten(io_lib:format("0.34 ~s, no profile, limit public: distribution-refused", [Case])),
                   t93_try(fun() ->
                                   E0 = gt_engine:set_max_distribution(gt_engine:new(), public),
                                   gt_engine:load_packs(E0, P, gt_engine:inner_names(P, [Outer]), M)
                           end),
                   {load_error, 'distribution-refused'})
         || {Case, P, M} <- [{"inner not shown public", AP, AM},
                             {"inner using a controlled module", BP, BM}]],
    Rule6 ++ Rule5 ++ InnerCases ++ InnerC.

%% A run of ten times the messages takes about ten times as long (0.92): a
%% carrier of one-byte messages converted to itself, 2000 and 20000 messages.
%% A quadratic decode or encode gives a ratio near 100. The times are the VM's
%% CPU time (statistics runtime, in ms), the two sizes alternate so that a busy
%% moment falls on both, the least of seven of each counts, and the bound has
%% three tries: load can only make a time longer, so the bound is not loosened.
run_cost_check() ->
    Head = fun(Name) -> ["format ", Name, "\nversion 0.92.0\ndistribution public\nsource \"unit check\"\n"
                         "uses probe\nwire bits\nlayout sequential\nbit_order msb\n"] end,
    Module = fun(Name, Keys) -> iolist_to_binary(["module ", Name, "\nversion 0.1.0\ndistribution public\n"
                                                  "source \"unit check\"\n", Keys]) end,
    Texts = [{load_model, Module("core", "key uid string -\nkey time_ms int ms\n")},
             {load_model, Module("probe", "key x int -\n")},
             {load_pack, iolist_to_binary([Head("unit-run-message"), "framing self\nfield probe.x 8 uint\n"])},
             {load_pack, iolist_to_binary([Head("unit-run-carrier"), "inner unit-run-message run\n"])}],
    E = lists:foldl(fun({load_model, T}, A) -> gt_engine:load_model(A, T);
                       ({load_pack, T}, A) -> gt_engine:load_pack(A, T)
                    end, gt_engine:new(), Texts),
    C = <<"unit-run-carrier">>,
    Input = fun(N) -> gt_hex:bytes_to_hex(<< <<(I rem 256)>> || I <- lists:seq(1, N) >>) end,
    {In2, In20} = {Input(2000), Input(20000)},
    Once = fun(In) ->
                   {T0, _} = erlang:statistics(runtime),
                   [{ok, Out}] = gt_engine:convert_run(E, C, C, In, none),
                   true = Out =:= In,
                   {T1, _} = erlang:statistics(runtime),
                   T1 - T0
           end,
    Try = fun() ->
                  Pairs = [{Once(In2), Once(In20)} || _ <- lists:seq(1, 7)],
                  {max(1, lists:min([S || {S, _} <- Pairs])), lists:min([L || {_, L} <- Pairs])}
          end,
    cost_tries(Try, 3, []).

cost_tries(_Try, 0, Seen) ->
    io:format("FAIL unit a run of 20000 messages against one of 2000, CPU ms, three tries: ~p~n",
              [lists:reverse(Seen)]),
    {0, 1};
cost_tries(Try, Left, Seen) ->
    {Small, Large} = Try(),
    case Large =< 40 * Small of
        true -> {1, 0};
        false -> cost_tries(Try, Left - 1, [{Small, Large} | Seen])
    end.

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
%% reduced build (Version 0.24, "What pins it")
%% ===================================================================
%% Run on a build with only the wires Wires (names, as `wire` lines write
%% them). The wire and format of each pack are read from the text of its
%% pack.def, not from the engine. Then:
%%   - every pack on a wire of the set loads;
%%   - every pack on another wire of the specification is `unknown-wire`, its
%%     message naming the wire and saying this build does not have it, and a
%%     `wire` value that is no wire stays `unknown-wire` without that text;
%%   - every conversion vector whose `from` and `to` packs are on wires of
%%     the set passes, on the engine that loaded those packs.
%% Prints "reduced vectors: N/M passed" and one "unknown-wire <wire>: N/M"
%% line per wire left out; halts 1 on any failure.
run_reduced(PacksDir, ModelsDir, Wires0) ->
    Wires = [list_to_binary(W) || W <- Wires0],
    SpecWires = [<<"xml">>, <<"geojson">>, <<"json">>, <<"bits">>, <<"protobuf">>,
                 <<"text">>, <<"tlv">>, <<"cbor">>],
    Models = lists:foldl(fun({_F, Bin}, E) -> gt_engine:load_model(E, Bin) end,
                         gt_engine:new(), gt_engine:model_texts(ModelsDir)),
    {ok, Entries} = file:list_dir(PacksDir),
    Packs = [{Dir, Text, pack_head(Text)}
             || Dir <- lists:sort(Entries),
                {ok, Text} <- [file:read_file(filename:join([PacksDir, Dir, "pack.def"]))]],
    %% ruling 1 of 0.34: the check runs no vector of an outer pack (a pack
    %% with an `inner` line), so an outer pack is on no wire here
    FormatWire = maps:from_list([{F, case outer_text(Text) of true -> outer; false -> W end}
                                 || {_, Text, {F, W}} <- Packs]),
    %% the packs on the wires of the set, in one engine
    {Engine, LoadFail} =
        lists:foldl(
          fun({Dir, Text, {_, W}}, {E, N}) ->
                  case lists:member(W, Wires) of
                      false -> {E, N};
                      true ->
                          try {gt_engine:load_pack(E, Text), N}
                          catch C:R ->
                              io:format("FAIL pack ~s (wire ~s) does not load: ~ts~n",
                                        [Dir, W, why({exception, C, R})]),
                              {E, N + 1}
                          end
                  end
          end, {Models, 0}, Packs),
    %% the packs on the other wires of the specification
    Left = [W || W <- SpecWires, not lists:member(W, Wires)],
    WireCounts =
        [{W, lists:foldl(
               fun({Dir, Text, {_, PW}}, {P, F}) when PW =:= W ->
                       case refused_as_absent(Models, Text, W) of
                           ok -> {P + 1, F};
                           {error, Why} ->
                               io:format("FAIL pack ~s (wire ~s): ~ts~n", [Dir, W, Why]),
                               {P, F + 1}
                       end;
                  (_, Acc) -> Acc
               end, {0, 0}, Packs)}
         || W <- Left],
    NotAWire = not_a_wire(Models),
    %% the conversion vectors of the set
    {VPass, VFail} =
        lists:foldl(
          fun({PackDir, File}, {P, F}) ->
                  case vector_on(File, FormatWire, Wires) of
                      false -> {P, F};
                      true ->
                          case run_vector_file(Engine, File) of
                              ok -> {P + 1, F};
                              {error, Name, Why} ->
                                  io:format("FAIL ~s/~s: ~ts~n", [PackDir, Name, why(Why)]),
                                  {P, F + 1}
                          end
                  end
          end, {0, 0}, vector_files(PacksDir)),
    io:format("wires of this build: ~s~n", [lists:join(",", Wires)]),
    io:format("reduced vectors: ~p/~p passed~n", [VPass, VPass + VFail]),
    lists:foreach(fun({W, {P, F}}) ->
                          io:format("unknown-wire ~s: ~p/~p packs refused as not in this build~n",
                                    [W, P, P + F])
                  end, WireCounts),
    io:format("unknown-wire for a value that is no wire: ~s~n",
              [case NotAWire of ok -> "ok"; _ -> "FAILED" end]),
    Failed = LoadFail + VFail + lists:sum([F || {_, {_, F}} <- WireCounts])
        + case NotAWire of ok -> 0; _ -> 1 end
        + case VPass of 0 -> 1; _ -> 0 end
        + length([W || {W, {0, _}} <- WireCounts]),
    case Failed of
        0 -> halt(0);
        N ->
            io:format("FAILED: ~p check(s)~n", [N]),
            halt(1)
    end.

%% The `format` and `wire` values of a pack.def text -> {Format, Wire}.
pack_head(Text) ->
    Lines = [string:lexemes(L, " \t\r") || L <- binary:split(Text, <<"\n">>, [global])],
    Get = fun(Key) ->
                  case [V || [K, V | _] <- Lines, K =:= Key] of
                      [V | _] -> V;
                      [] -> undefined
                  end
          end,
    {Get(<<"format">>), Get(<<"wire">>)}.

%% Is the vector's `from` and `to` each a pack on a wire of the set?
outer_text(Text) ->
    lists:any(fun(L) -> case string:lexemes(L, " \t\r") of
                            [<<"inner">>, _ | _] -> true;
                            _ -> false
                        end
              end, binary:split(Text, <<"\n">>, [global])).

vector_on(File, FormatWire, Wires) ->
    try
        {ok, Bin} = file:read_file(File),
        Obj = gt_json:parse(Bin),
        {ok, From} = gt_json:get(Obj, <<"from">>),
        {ok, To} = gt_json:get(Obj, <<"to">>),
        lists:member(maps:get(From, FormatWire, none), Wires)
            andalso lists:member(maps:get(To, FormatWire, none), Wires)
    catch _:_ -> false
    end.

%% Ruling 1c of 0.24: unknown-wire, the message naming the wire and saying
%% that this build does not have it.
refused_as_absent(Models, Text, Wire) ->
    try gt_engine:load_pack(Models, Text) of
        _ -> {error, "loaded on a build without its wire"}
    catch
        error:{load_error, 'unknown-wire', Msg} ->
            M = unicode:characters_to_binary(Msg),
            case binary:match(M, Wire) =/= nomatch
                andalso binary:match(M, <<"this build does not have">>) =/= nomatch
                andalso lists:prefix("unknown-wire:", Msg) of
                true -> ok;
                false -> {error, io_lib:format("unknown-wire without the wire's name or the reason: ~ts", [Msg])}
            end;
        C:R -> {error, why({exception, C, R})}
    end.

%% A `wire` value that is no wire of the specification is unknown-wire as
%% before, and its message does not say the build lacks it.
not_a_wire(Models) ->
    Text = <<"format not-a-wire\nversion 0.1.0\ndistribution public\nwire nowire\n">>,
    try gt_engine:load_pack(Models, Text) of
        _ -> error
    catch
        error:{load_error, 'unknown-wire', Msg} ->
            case string:find(Msg, "this build does not have") of
                nomatch -> ok;
                _ -> io:format("FAIL wire nowire: ~ts~n", [Msg]), error
            end;
        C:R -> io:format("FAIL wire nowire: ~ts~n", [why({exception, C, R})]), error
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
