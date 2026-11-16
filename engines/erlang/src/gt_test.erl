%% gt_test: conformance runner (spec/vector-format.md).
%%
%% Loads the model modules and every pack under PacksDir, then runs
%%   - every conversion vector under PacksDir/<pack>/vectors/*.json:
%%     convert(from, to, input [, context]) equals `expect` byte for byte, or
%%     fails with the error kind in `expect_error` (message beginning
%%     "<kind>:"); and, when `model` is present, decode(from, input) has each
%%     listed key (floats within 1e-9) and selects the kind named by "@kind".
%%     With "@complete": true the keys are checked on the completed entity
%%     (decode, context, derivations), floats within 1e-9 relative;
%%   - every load vector under PacksDir/conformance/load-vectors/*.json.
%% Every failure is printed as "FAIL <pack>/<vector>: <why>"; then the counts
%% "vectors: N/M passed" and "load vectors: N/M passed". Exits non-zero on
%% any failure.
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
    {Pass, Fail} = run_conversion(PacksDir, ModelsDir),
    {LPass, LFail} = run_load_vectors(PacksDir),
    io:format("vectors: ~p/~p passed~n", [Pass, Pass + Fail]),
    io:format("load vectors: ~p/~p passed~n", [LPass, LPass + LFail]),
    io:format("elapsed: ~.1f s~n", [(erlang:monotonic_time(millisecond) - T0) / 1000]),
    case Fail + LFail of
        0 -> halt(0);
        N ->
            io:format("FAILED: ~p vector(s)~n", [N]),
            halt(1)
    end.

%% ===================================================================
%% conversion vectors
%% ===================================================================
run_conversion(PacksDir, ModelsDir) ->
    Engine = load_packs(PacksDir, ModelsDir),
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

run_vector(Engine, Obj) ->
    G = fun(K) ->
                case gt_json:get(Obj, K) of
                    {ok, V} -> V;
                    absent -> undefined
                end
        end,
    From = G(<<"from">>),
    To = G(<<"to">>),
    Input = G(<<"input">>),
    Packs = gt_engine:packs(Engine),
    Context = case G(<<"context">>) of
                  undefined -> none;
                  {object, Pairs} -> Pairs
              end,
    case {maps:is_key(From, Packs), maps:is_key(To, Packs)} of
        {false, _} -> {error, {pack_not_loaded, From}};
        {_, false} -> {error, {pack_not_loaded, To}};
        {true, true} ->
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
            end
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
    Pairs = lists:keydelete(<<"@complete">>, 1, Pairs0),
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
          end, Pairs),
    case Mismatches of
        [] -> ok;
        _ -> {error, {model, Mismatches}}
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
%% 1e-9; on a completed entity within 1e-9 relative, or equal.
model_eq(Actual, Expected, Complete) when is_float(Actual), is_binary(Expected) ->
    try gt_num:dec_to_float(Expected) of
        Want when Complete ->
            Actual == Want orelse
                abs(Actual - Want) < 1.0e-9 * max(abs(Actual), abs(Want));
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
        {ok, Pack} = gt_json:get(Obj, <<"pack">>),
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
                  _ = gt_engine:load_pack(E1, Pack),
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
