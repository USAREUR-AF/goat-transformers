%% gt_bench: the benchmark of engine-spec Version 0.25, ruling 2.
%%
%% Reads a benchmark set (bench/set.json: `iterations` and a list of
%% conversion vector paths, relative to the repository root, which is the
%% directory above the set's own directory). Then:
%%   1. loads into one new instance only the packs the vectors name (their
%%      `from` and `to` formats, in order of first appearance, each from
%%      <root>/packs/<format>/pack.def), the packs their `inner` lines name
%%      (Version 0.34, transitively; a name with no directory is skipped)
%%      and the model modules those packs use (gt_engine:load_packs/4), and
%%      records the time that took;
%%   2. for each vector in order: converts its input once and checks the
%%      output against `expect` byte for byte (a difference fails the run:
%%      a message on standard error, exit status 1); then converts the input
%%      `iterations` times and records the time.
%% Standard output holds exactly one line per vector, then one for the load:
%%   {"vector": "<path as in the set>", "iterations": <n>, "ns_per_op": <integer>}
%%   {"load": <number of packs>, "ns": <integer>}
%% ns_per_op is the total time divided by `iterations`, rounded down.
%% Everything else goes to standard error.
-module(gt_bench).
-export([main/0, main/1, run/1]).

main() -> main(init:get_plain_arguments()).

main(Args) ->
    Set = case Args of
              [S | _] -> S;
              [] -> "bench/set.json"
          end,
    Status = try run(Set) of
                 ok -> 0
             catch
                 throw:{bench_failed, Fmt, FArgs} ->
                     io:format(standard_error, "bench: " ++ Fmt ++ "~n", FArgs),
                     1;
                 C:R:St ->
                     io:format(standard_error, "bench: ~0p:~0P~n~0P~n", [C, R, 20, St, 30]),
                     1
             end,
    halt(Status).

run(SetPath) ->
    Root = filename:dirname(filename:dirname(filename:absname(SetPath))),
    Set = gt_json:parse(read(SetPath)),
    Iterations = case gt_json:get(Set, <<"iterations">>) of
                     {ok, N} when is_integer(N), N > 0 -> N;
                     Other -> fail("the set's iterations is not a positive integer: ~0p", [Other])
                 end,
    Paths = case gt_json:get(Set, <<"vectors">>) of
                {ok, {array, Ps}} -> Ps;
                Other2 -> fail("the set's vectors is not an array: ~0p", [Other2])
            end,
    Vectors = [vector(Root, P) || P <- Paths],
    PacksDir = filename:join(Root, "packs"),
    %% Version 0.34: with the packs named by their `inner` lines, transitively
    Names = gt_engine:inner_names(
              PacksDir, first_appearance(lists:append([[F, T] || {_, F, T, _, _, _} <- Vectors]))),
    ModelsDir = filename:join(Root, "model"),
    T0 = erlang:monotonic_time(nanosecond),
    Engine = gt_engine:load_packs(gt_engine:new(), PacksDir, Names, ModelsDir),
    LoadNs = erlang:monotonic_time(nanosecond) - T0,
    lists:foreach(fun(V) -> bench_vector(Engine, Iterations, V) end, Vectors),
    io:format("{\"load\": ~b, \"ns\": ~b}~n", [length(Names), LoadNs]),
    ok.

bench_vector(Engine, Iterations, {Path, From, To, Input, Context, Expect}) ->
    Convert = fun() -> gt_engine:convert(Engine, From, To, Input, Context) end,
    case Convert() of
        Expect -> ok;
        Got -> fail("~ts: the output differs from expect: ~0p", [Path, Got])
    end,
    T0 = erlang:monotonic_time(nanosecond),
    repeat(Iterations, Convert),
    Ns = erlang:monotonic_time(nanosecond) - T0,
    io:format("{\"vector\": \"~ts\", \"iterations\": ~b, \"ns_per_op\": ~b}~n",
              [gt_json:escape(Path), Iterations, Ns div Iterations]).

repeat(0, _F) -> ok;
repeat(N, F) ->
    _ = F(),
    repeat(N - 1, F).

%% -> {Path, From, To, Input, Context, Expect}
vector(Root, Path) when is_binary(Path) ->
    Obj = gt_json:parse(read(filename:join(Root, Path))),
    G = fun(K) ->
                case gt_json:get(Obj, K) of
                    {ok, V} -> V;
                    absent -> undefined
                end
        end,
    [From, To, Input, Expect] =
        [case G(K) of
             V when is_binary(V) -> V;
             V -> fail("~ts: `~s` is not a string: ~0p", [Path, K, V])
         end || K <- [<<"from">>, <<"to">>, <<"input">>, <<"expect">>]],
    Context = case G(<<"context">>) of
                  undefined -> none;
                  {object, Pairs} -> Pairs;
                  C -> fail("~ts: `context` is not an object: ~0p", [Path, C])
              end,
    {Path, From, To, Input, Context, Expect};
vector(_Root, Other) -> fail("a vector entry is not a path: ~0p", [Other]).

first_appearance(Names) ->
    {Out, _} = lists:foldl(fun(N, {Acc, Seen}) ->
                                   case maps:is_key(N, Seen) of
                                       true -> {Acc, Seen};
                                       false -> {[N | Acc], Seen#{N => true}}
                                   end
                           end, {[], #{}}, Names),
    lists:reverse(Out).

read(Path) ->
    case file:read_file(Path) of
        {ok, Bin} -> Bin;
        {error, Why} -> fail("cannot read ~ts: ~p", [Path, Why])
    end.

fail(Fmt, Args) -> throw({bench_failed, Fmt, Args}).
