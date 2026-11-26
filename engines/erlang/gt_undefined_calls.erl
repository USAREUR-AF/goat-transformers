%% gt_undefined_calls: lists every call from the .beam files of the given directories to a function
%% that does not exist, one "<caller module> calls M:F/A" a line.
%% Usage: erl -noshell -pa <dir> -s gt_undefined_calls main -extra <ebin>...
%% exits 1 when it lists one. single_wire_check.sh compiles it; it is in no build.
%%
%% It is what xref's undefined_function_calls gives, on stdlib and compiler
%% alone (xref is in the tools application, which an OTP install may lack, and
%% needs debug_info). A call is an entry of the module's import table or an
%% external fun literal (fun M:F/A). A called module is looked for in the same
%% directory, then in OTP, never in another directory of the engine. A call
%% whose module is a variable is not seen; the engine has none.
-module(gt_undefined_calls).
-export([main/0]).

main() -> main(init:get_plain_arguments()).

main([]) -> io:format("usage: -extra <ebin>...~n"), halt(2);
main(Dirs) ->
    case lists:sum([check(D) || D <- Dirs]) of
        0 -> halt(0);
        _ -> halt(1)
    end.

check(Dir) ->
    Beams = filelib:wildcard(filename:join(Dir, "*.beam")),
    Beams =/= [] orelse begin io:format("no .beam files in ~s~n", [Dir]), halt(2) end,
    Mods = [load(B) || B <- Beams],
    Exports = maps:from_list([{M, E} || {M, E, _} <- Mods]),
    Bad = [{M, C} || {M, _, Calls} <- Mods, C <- Calls, not defined(C, Exports)],
    [io:format("~s: ~s calls ~s:~s/~p, which does not exist~n", [Dir, M, CM, CF, CA])
     || {M, {CM, CF, CA}} <- Bad],
    length(Bad).

load(Beam) ->
    {ok, {M, [{exports, E}, {imports, I}]}} = beam_lib:chunks(Beam, [exports, imports]),
    Code = element(6, beam_disasm:file(Beam)),   % #beam_file.code
    {M, E, lists:usort(I ++ funs(Code))}.

%% the external funs anywhere in a term
funs(F) when is_function(F) ->
    case erlang:fun_info(F, type) of
        {type, external} ->
            [list_to_tuple([element(2, erlang:fun_info(F, K)) || K <- [module, name, arity]])];
        _ -> []
    end;
funs([H | T]) -> funs(H) ++ funs(T);
funs(T) when is_tuple(T) -> funs(tuple_to_list(T));
funs(M) when is_map(M) -> funs(maps:to_list(M));
funs(_) -> [].

defined({M, F, A}, Exports) ->
    case Exports of
        #{M := E} -> lists:member({F, A}, E) orelse
                         (F =:= module_info andalso A < 2);
        _ ->
            _ = code:ensure_loaded(M),
            erlang:function_exported(M, F, A) orelse erlang:is_builtin(M, F, A)
                %% is_builtin leaves out the guard operators and BIFs that
                %% the compiler makes instructions
                orelse (M =:= erlang andalso (erl_internal:guard_bif(F, A)
                                              orelse is_op(F, A)))
    end.

is_op(F, A) ->
    try erl_internal:op_type(F, A) of _ -> true
    catch error:_ -> false
    end.
