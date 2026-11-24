%% gt_cli: the engine's command-line tool, the contract of engine-spec
%% Version 0.23. Started by goat-xf.sh as
%%   erl -noshell -pa ebin -s gt_cli main -extra <arguments>
%% Exit status 0 (success), 1 (a load or call failure; standard error's first
%% line begins with the kind and a colon), 2 (a usage error, found before
%% anything is loaded).
-module(gt_cli).
-export([main/0, main/1, run/1]).

-define(MAX_I64, 9223372036854775807).

-define(USAGE,
"usage:\n"
"  goat-xf.sh convert --from <format> --to <format> [--set <key>=<value>]... <options>\n"
"  goat-xf.sh list-formats <options>\n"
"  goat-xf.sh capability --from <format> --to <format> <options>\n"
"  goat-xf.sh matrix <options>\n"
"  goat-xf.sh licences [--json] <options>\n"
"  goat-xf.sh help\n"
"options, in any order, each at most once:\n"
"  --packs <dir>             the directory whose subdirectories are packs (default: packs)\n"
"  --models <dir>            the model modules (default: <packs>/../model)\n"
"  --packs-only <a>[,<b>...] load only these packs, in this order\n"
"  --max-items <n>           list items one decode holds (default 100000)\n"
"  --max-distribution <public|controlled>   the distribution limit (default controlled)\n"
"  --profile <open|open+copyleft|everything> load only the packs and modules of this licence profile\n"
"licences writes each loaded pack: directory, format, licence, profile (--json: as JSON).\n"
"convert reads standard input to its end and writes the result with nothing added.\n").

%% -s gt_cli main: the arguments after -extra.
main() -> main(init:get_plain_arguments()).

main(Args) ->
    ok = io:setopts(standard_io, [binary, {encoding, latin1}]),
    ok = io:setopts(standard_error, [{encoding, latin1}]),
    Status = try run([arg_bin(A) || A <- Args])
             catch Class:Reason:Stack ->
                     fail(io_lib:format("internal-error: ~0P ~0P ~0P", [Class, 8, Reason, 12, Stack, 8]))
             end,
    erlang:halt(Status).

%% A command-line argument as UTF-8 bytes.
arg_bin(A) when is_binary(A) -> A;
arg_bin(A) ->
    case file:native_name_encoding() of
        utf8 ->
            case unicode:characters_to_binary(A) of
                B when is_binary(B) -> B;
                _ -> list_to_binary([C band 255 || C <- A])
            end;
        latin1 -> list_to_binary(A)
    end.

%% -> exit status; writes standard output and standard error itself.
run(Args) ->
    case parse(Args) of
        help -> out(?USAGE), 0;
        {usage, Why} -> usage(Why);
        {ok, Sub, Opts} ->
            try execute(Sub, Opts)
            catch
                error:{load_error, _Kind, Msg} -> fail(Msg);
                error:{convert_error, _Kind, Msg} -> fail(Msg);
                throw:{tool_error, Msg} -> fail(Msg)
            end
    end.

%% ===================================================================
%% arguments (Invocation: Arguments, Usage errors)
%% ===================================================================
-define(COMMON, [<<"--packs">>, <<"--models">>, <<"--packs-only">>, <<"--max-items">>,
                 <<"--max-distribution">>, <<"--profile">>]).

parse([]) -> {usage, "no subcommand"};
parse([H | _]) when H =:= <<"help">>; H =:= <<"-h">>; H =:= <<"--help">> -> help;
parse([Sub | Rest]) ->
    Names = case Sub of
                <<"convert">> -> [<<"--from">>, <<"--to">>, <<"--set">> | ?COMMON];
                <<"capability">> -> [<<"--from">>, <<"--to">> | ?COMMON];
                <<"list-formats">> -> ?COMMON;
                <<"matrix">> -> ?COMMON;
                <<"licences">> -> [<<"--json">> | ?COMMON];
                _ -> undefined
            end,
    case Names of
        undefined -> {usage, io_lib:format("unknown subcommand ~s", [Sub])};
        _ ->
            case pairs(Rest, Names, #{}, []) of
                {usage, _} = U -> U;
                {ok, Opts, Sets} -> check(Sub, Opts#{sets => lists:reverse(Sets)})
            end
    end.

%% Name-value pairs -> {ok, #{Name => Value}, ReversedSets}.
pairs([], _Names, Opts, Sets) -> {ok, Opts, Sets};
pairs([Name | Rest], Names, Opts, Sets) ->
    case lists:member(Name, Names) of
        false -> {usage, io_lib:format("~s is not an option of this subcommand", [Name])};
        true when Name =:= <<"--json">> ->
            %% the one option without a value (ruling 4b of 0.29)
            case maps:is_key(Name, Opts) of
                true -> {usage, "--json is given twice"};
                false -> pairs(Rest, Names, Opts#{Name => true}, Sets)
            end;
        true ->
            case Rest of
                [] -> {usage, io_lib:format("~s has no value", [Name])};
                [Value | Rest1] when Name =:= <<"--set">> ->
                    pairs(Rest1, Names, Opts, [Value | Sets]);
                [Value | Rest1] ->
                    case maps:is_key(Name, Opts) of
                        true -> {usage, io_lib:format("~s is given twice", [Name])};
                        false -> pairs(Rest1, Names, Opts#{Name => Value}, Sets)
                    end
            end
    end.

%% The checks of the values -> {ok, Sub, Opts} with typed values.
check(Sub, Opts) ->
    Steps = [fun from_to/2, fun sets/2, fun max_items/2, fun max_distribution/2,
             fun packs_only/2, fun profile/2],
    lists:foldl(fun(_, {usage, _} = U) -> U;
                   (F, {ok, S, O}) -> F(S, O)
                end, {ok, Sub, Opts}, Steps).

from_to(Sub, Opts) when Sub =:= <<"convert">>; Sub =:= <<"capability">> ->
    case {maps:is_key(<<"--from">>, Opts), maps:is_key(<<"--to">>, Opts)} of
        {false, _} -> {usage, "--from is required"};
        {_, false} -> {usage, "--to is required"};
        _ -> {ok, Sub, Opts}
    end;
from_to(Sub, Opts) -> {ok, Sub, Opts}.

%% --set <key>=<value>: the text before the first `=` is the key, not empty.
sets(Sub, #{sets := Sets} = Opts) ->
    Split = [case binary:split(S, <<"=">>) of
                 [K, V] when K =/= <<>> -> {K, V};
                 _ -> bad
             end || S <- Sets],
    case lists:member(bad, Split) of
        true -> {usage, "a --set value is <key>=<value> with a key before the first ="};
        false -> {ok, Sub, Opts#{sets := Split}}
    end.

max_items(Sub, #{<<"--max-items">> := V} = Opts) ->
    case V =/= <<>> andalso lists:all(fun(C) -> C >= $0 andalso C =< $9 end,
                                      binary_to_list(V)) of
        true ->
            N = binary_to_integer(V),
            case N =< ?MAX_I64 of
                true -> {ok, Sub, Opts#{<<"--max-items">> := N}};
                false -> {usage, "--max-items is above 2^63-1"}
            end;
        false -> {usage, "--max-items takes one or more digits 0 to 9"}
    end;
max_items(Sub, Opts) -> {ok, Sub, Opts}.

max_distribution(Sub, #{<<"--max-distribution">> := V} = Opts) ->
    case V of
        <<"public">> -> {ok, Sub, Opts#{<<"--max-distribution">> := public}};
        <<"controlled">> -> {ok, Sub, Opts#{<<"--max-distribution">> := controlled}};
        _ -> {usage, "--max-distribution takes public or controlled"}
    end;
max_distribution(Sub, Opts) -> {ok, Sub, Opts}.

packs_only(Sub, #{<<"--packs-only">> := V} = Opts) ->
    Names = binary:split(V, <<",">>, [global]),
    case lists:member(<<>>, Names) of
        true -> {usage, "--packs-only holds an empty name"};
        false -> {ok, Sub, Opts#{<<"--packs-only">> := Names}}
    end;
packs_only(Sub, Opts) -> {ok, Sub, Opts}.

%% usage error 11 (ruling 4d of 0.29)
profile(Sub, #{<<"--profile">> := V} = Opts) ->
    case gt_licence:profile(V) of
        {ok, Rank} -> {ok, Sub, Opts#{<<"--profile">> := Rank}};
        error -> {usage, "--profile takes open, open+copyleft or everything"}
    end;
profile(Sub, Opts) -> {ok, Sub, Opts}.

%% ===================================================================
%% loading (Version 0.23, Loading)
%% ===================================================================
%% -> {Engine, [{Dir, Format, Licence, Rank}]}: the packs loaded, listed
%% only when licence files are read.
%% With a profile, or for `licences`, the licence files are read first
%% (Version 0.29, ruling 3b), and a module or pack the profile does not hold
%% is skipped (3c, 3d); `licences` without a profile holds everything.
load(Sub, Opts) ->
    Packs = maps:get(<<"--packs">>, Opts, <<"packs">>),
    Models = maps:get(<<"--models">>, Opts, <<Packs/binary, "/../model">>),
    Rank = case {maps:find(<<"--profile">>, Opts), Sub} of
               {{ok, R}, _} -> R;
               {error, <<"licences">>} -> 4;
               {error, _} -> off
           end,
    %% a profile sets the limit to public, also beside --max-distribution
    %% controlled (Version 0.93, ruling 5); `licences` without a profile
    %% (rank 4) changes nothing (ruling 7)
    Limit = case Rank of
                R1 when is_integer(R1), R1 < 4 -> public;
                _ -> maps:get(<<"--max-distribution">>, Opts, controlled)
            end,
    E0 = gt_engine:set_max_distribution(gt_engine:new(), Limit),
    %% each module file read once (ruling 1d of 0.25)
    Read = gt_engine:model_read(Models),
    {Ctx, Held} = case Rank of
                      off -> {off, Read};
                      _ ->
                          C = gt_licence:start(<<Packs/binary, "/../licences.toml">>, Models,
                                               Rank, Read),
                          Files = maps:get(files, C),
                          {C, [FR || {F, _} = FR <- Read, gt_licence:held(C, maps:get(F, Files))]}
                  end,
    E1 = lists:foldl(fun({_F, _, Text}, E) -> gt_engine:load_model(E, Text) end,
                     E0, gt_engine:model_order(Held)),
    {E2, Listed} =
        case maps:find(<<"--packs-only">>, Opts) of
            {ok, Names} -> lists:foldl(fun(N, Acc) -> load_named(Acc, Ctx, Packs, N) end,
                                       {E1, []}, Names);
            error -> load_every({E1, []}, Ctx, Packs)
        end,
    E3 = case maps:find(<<"--max-items">>, Opts) of
             {ok, N} -> gt_engine:set_max_items(E2, N);
             error -> E2
         end,
    {E3, Listed}.

load_named(Acc, Ctx, Packs, Name) ->
    Component = Name =/= <<".">> andalso Name =/= <<"..">>
        andalso binary:match(Name, [<<"/">>, <<"\\">>]) =:= nomatch,
    Text = case Component of
               true ->
                   case file:read_file(filename:join([Packs, Name, <<"pack.def">>])) of
                       {ok, B} -> B;
                       {error, _} -> undefined
                   end;
               false -> undefined
           end,
    case Text of
        undefined ->
            erlang:error({load_error, 'unknown-format',
                          iolist_to_binary(["unknown-format: ", Name,
                                            " is not a pack directory of --packs"])});
        _ -> load_one(Acc, Ctx, Name, filename:join(Packs, Name), {ok, Text})
    end.

load_every(Acc0, Ctx, Packs) ->
    Entries = case file:list_dir_all(Packs) of
                  {ok, Es} -> lists:sort([arg_bin(X) || X <- Es]);
                  {error, Why} ->
                      throw({tool_error,
                             iolist_to_binary(["packs-unreadable: --packs ", Packs,
                                               " cannot be read as a directory (",
                                               atom_to_list(Why), ")"])})
              end,
    lists:foldl(
      fun(<<".", _/binary>>, Acc) -> Acc;
         (Entry, Acc) ->
              Dir = filename:join(Packs, Entry),
              Def = filename:join(Dir, <<"pack.def">>),
              case filelib:is_dir(Dir) andalso filelib:is_regular(Def) of
                  true when Ctx =:= off -> load_one(Acc, Ctx, Entry, Dir, {ok, read(Def)});
                  true -> load_one(Acc, Ctx, Entry, Dir, file:read_file(Def));
                  false -> Acc
              end
      end, Acc0, Entries).

%% One pack reached: with licence files read, its licence and `uses` lines
%% first, and skipped when the profile does not hold it (ruling 3d).
load_one({E, Listed}, off, _Entry, _Dir, {ok, Text}) ->
    {gt_engine:load_pack(E, Text), Listed};
load_one({E, Listed}, Ctx, Entry, Dir, Text) ->
    {Lic, Rank} = gt_licence:pack(Ctx, Dir, Text),
    case gt_licence:held(Ctx, Rank) of
        false -> {E, Listed};
        true ->
            Bin = case Text of
                      {ok, B} -> B;
                      _ -> read(filename:join(Dir, <<"pack.def">>))
                  end,
            Before = gt_engine:packs(E),
            E1 = gt_engine:load_pack(E, Bin),
            [Format | _] = [F || F <- maps:keys(gt_engine:packs(E1)), not maps:is_key(F, Before)],
            {E1, [{Entry, Format, Lic, Rank} | Listed]}
    end.

read(Path) ->
    case file:read_file(Path) of
        {ok, B} -> B;
        {error, Why} ->
            throw({tool_error, iolist_to_binary(["unreadable-file: ", Path, " (",
                                                 atom_to_list(Why), ")"])})
    end.

%% ===================================================================
%% the subcommands
%% ===================================================================
execute(Sub, Opts) ->
    {E, Listed} = load(Sub, Opts),
    Formats = lists:sort(maps:keys(gt_engine:packs(E))),
    case Sub of
        <<"list-formats">> ->
            out([[F, $\t, value(maps:get(version, gt_engine:pack(E, F))), $\t,
                  value(maps:get(wire, gt_engine:pack(E, F))), $\n] || F <- Formats]),
            0;
        <<"matrix">> ->
            out([<<"from\tto\tgrade\tcarried\tdropped\n">>
                 | [line(E, F, T) || F <- Formats, T <- Formats]]),
            0;
        <<"licences">> ->
            Rows = lists:sort(Listed),
            case maps:is_key(<<"--json">>, Opts) of
                false ->
                    out([[D, $\t, F, $\t, L, $\t, gt_licence:rank_name(R), $\n]
                         || {D, F, L, R} <- Rows]);
                true ->
                    Obj = fun({D, F, L, R}) ->
                                  [<<"{\"pack\":\"">>, esc(D), <<"\",\"format\":\"">>, esc(F),
                                   <<"\",\"licence\":\"">>, esc(L), <<"\",\"profile\":\"">>,
                                   gt_licence:rank_name(R), <<"\"}">>]
                          end,
                    out([<<"{\"packs\":[">>, lists:join($,, [Obj(Row) || Row <- Rows]),
                         <<"]}\n">>])
            end,
            0;
        <<"capability">> ->
            {From, To} = from_to_loaded(E, Opts),
            out(line(E, From, To)),
            0;
        <<"convert">> ->
            {From, To} = from_to_loaded(E, Opts),
            Input = read_stdin(),
            case unicode:characters_to_binary(Input, utf8, utf8) of
                Input -> ok;
                _ -> erlang:error({convert_error, 'malformed-wire',
                                   iolist_to_binary(["malformed-wire: format ", From,
                                                     ": the input is not valid UTF-8"])})
            end,
            Out = gt_engine:convert(E, From, To, Input, context(maps:get(sets, Opts))),
            out(Out),
            0
    end.

%% --from first, then --to; both before standard input is read.
from_to_loaded(E, Opts) ->
    From = maps:get(<<"--from">>, Opts),
    To = maps:get(<<"--to">>, Opts),
    _ = gt_engine:pack(E, From),
    _ = gt_engine:pack(E, To),
    {From, To}.

%% A key given twice takes its last value and keeps the place of its first.
context([]) -> none;
context(Sets) ->
    Last = maps:from_list(Sets),
    {Keys, _} = lists:foldl(fun({K, _}, {Ks, Seen}) ->
                                    case maps:is_key(K, Seen) of
                                        true -> {Ks, Seen};
                                        false -> {[K | Ks], Seen#{K => true}}
                                    end
                            end, {[], #{}}, Sets),
    [{K, maps:get(K, Last)} || K <- lists:reverse(Keys)].

line(E, From, To) ->
    {Grade, Carried, Dropped} = gt_engine:capability(E, From, To),
    [From, $\t, To, $\t, atom_to_binary(Grade), $\t, join(Carried), $\t, join(Dropped), $\n].

join(Keys) -> lists:join($\s, Keys).

%% A JSON string value of `licences --json` (ruling 4c of 0.29): `"` and
%% `\` escaped, each byte below 0x20 as \u00xx, every other byte itself.
esc(Bin) -> [esc_byte(C) || <<C>> <= Bin].
esc_byte($") -> <<"\\\"">>;
esc_byte($\\) -> <<"\\\\">>;
esc_byte(C) when C < 16#20 -> io_lib:format("\\u~4.16.0b", [C]);
esc_byte(C) -> C.

value(V) when is_atom(V) -> atom_to_binary(V);
value(V) when is_binary(V) -> V;
value(V) when is_list(V) -> unicode:characters_to_binary(V).

read_stdin() -> read_stdin([]).
read_stdin(Acc) ->
    case file:read(standard_io, 65536) of
        {ok, Data} -> read_stdin([Data | Acc]);
        eof -> iolist_to_binary(lists:reverse(Acc));
        {error, Why} -> throw({tool_error, io_lib:format("stdin-unreadable: ~p", [Why])})
    end.

%% ===================================================================
%% output
%% ===================================================================
out(IoData) -> ok = file:write(standard_io, IoData).

fail(Msg) ->
    ok = file:write(standard_error, [Msg, $\n]),
    1.

usage(Why) ->
    ok = file:write(standard_error, ["usage error: ", Why, "\n", ?USAGE]),
    2.
