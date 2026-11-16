%% gt_model: parse a model module file (model/<module>.def) into a module map.
%% Clean-room implementation from spec/engine-spec.md (Versions 0.4, 0.6, 0.7, 0.8) only.
%%
%% Module = #{name => Bin, version => Bin, distribution => public | controlled,
%%            sources => [Bin], uses => [ModuleNameBin], keys => [{NameBin, Type, Unit, Meaning}],
%%            types => #{NameBin => Type | list},   % keys and lists, one namespace
%%            derives => [{TargetKey, Function, [ArgumentKey]}]}   % once checked
%% Type = string | float | int. Derive keys are entity keys, written as in a
%% pack: bare for `core`, `<module>.<key>` otherwise. Function: gt_derive.
-module(gt_model).
-export([parse/1, parse/2, check_uses/2, check_derives/2, key_type/2]).

%% Parse one module text (binary or string) -> module map, the keys and
%% types of its `derive` lines still unchecked. Line errors
%% are raised as the text is read; then missing-distribution and
%% missing-source. The checks against the engine follow in the order of
%% gt_engine:load_model/2 (ruling 29 of 0.8).
parse(Text) when is_list(Text) -> parse(unicode:characters_to_binary(Text));
parse(Bin) ->
    Base = #{name => undefined, version => undefined, distribution => undefined,
             sources => [], uses => [], keys => [], types => #{}, derives => []},
    M0 = lists:foldl(fun(Line, Acc) -> apply_line(gt_pack:tokens(Line), Acc) end,
                     Base, binary:split(Bin, <<"\n">>, [global])),
    M = M0#{sources := lists:reverse(maps:get(sources, M0)),
            uses := lists:reverse(maps:get(uses, M0)),
            keys := lists:reverse(maps:get(keys, M0)),
            derives := lists:reverse(maps:get(derives, M0))},
    gt_pack:require_marking(["module ", name_str(M)], M),
    case maps:get(name, M) of
        undefined -> gt_pack:load_error('bad-directive', "the module has no module line", []);
        _ -> ok
    end,
    M.

%% Parse and check a module against the modules loaded so far, without an
%% engine's distribution limit.
parse(Text, Modules) ->
    M = parse(Text),
    check_uses(M, Modules),
    check_derives(M, Modules).

%% Every module a `uses` line names is loaded.
check_uses(#{uses := Uses} = M, Modules) ->
    lists:foreach(
      fun(U) ->
              case maps:is_key(U, Modules) of
                  true -> ok;
                  false -> gt_pack:load_error('unknown-module',
                                              "module ~s uses module ~s, which is not loaded",
                                              [name_str(M), U])
              end
      end, Uses).

%% The `derive` checks that need keys, in line order: declared, of a module
%% the line may name, typed as the function takes them -> the module with
%% its derives checked.
check_derives(#{derives := Ds} = M, Modules) ->
    M#{derives := [check_derive(D, M, Modules) || D <- Ds]}.

%% Declared type of a key -> {ok, Type} | error.
key_type(#{types := Types}, Name) -> maps:find(Name, Types).

apply_line([], M) -> M;                      % blank or comment-only line
apply_line([<<"module">>, N], M)  -> M#{name => N};
apply_line([<<"version">>, V], M) -> M#{version => V};
apply_line([<<"distribution">>, D], M) -> M#{distribution => gt_pack:distribution_atom(D)};
apply_line([<<"source">>, S], M)  -> M#{sources := [S | maps:get(sources, M)]};
apply_line([<<"uses">>, U], M)    -> M#{uses := [U | maps:get(uses, M)]};
apply_line([<<"key">>, Name, Type, Unit], M) -> add_key(Name, Type, Unit, <<>>, M);
apply_line([<<"key">>, Name, Type, Unit, Meaning], M) -> add_key(Name, Type, Unit, Meaning, M);
apply_line([<<"list">>, Name], M) -> add_list(Name, M);
apply_line([<<"list">>, Name, _Meaning], M) -> add_list(Name, M);
%% a `derive` line refused on its own text (function name, parameter, number
%% of arguments) is a line error, raised as the file is read (ruling 32 of 0.8)
apply_line([<<"derive">>, Target, Fun | Args], #{derives := Ds} = M) when Args =/= [] ->
    F = case gt_derive:parse_function(Fun, length(Args)) of
            {ok, Parsed} -> Parsed;
            {error, Why} ->
                gt_pack:load_error('bad-directive', "derive ~s ~s: ~s", [Target, Fun, Why])
        end,
    M#{derives := [{Target, F, Args} | Ds]};
apply_line([Dir | _], _M) ->
    case lists:member(Dir, [<<"module">>, <<"version">>, <<"distribution">>, <<"source">>,
                            <<"uses">>, <<"key">>, <<"list">>, <<"derive">>]) of
        true -> gt_pack:load_error('bad-directive', "~s has the wrong number of arguments", [Dir]);
        false -> gt_pack:load_error('unknown-directive', "~s", [Dir])
    end.

add_key(Name, Type, Unit, Meaning, #{keys := Keys, types := Types} = M) ->
    new_name(Name, M),
    T = type_atom(Type),
    M#{keys := [{Name, T, Unit, Meaning} | Keys], types := maps:put(Name, T, Types)}.

%% A list is named like a key and shares the key namespace of its module; its
%% type is `list`.
add_list(Name, #{types := Types} = M) ->
    new_name(Name, M),
    M#{types := maps:put(Name, list, Types)}.

new_name(Name, #{types := Types} = M) ->
    case binary:match(Name, <<".">>) of
        nomatch -> ok;
        _ -> gt_pack:load_error('bad-directive', "key name ~s contains a `.`", [Name])
    end,
    case maps:is_key(Name, Types) of
        true -> gt_pack:load_error('duplicate-key', "module ~s declares the name ~s twice",
                                   [name_str(M), Name]);
        false -> ok
    end.

type_atom(<<"string">>) -> string;
type_atom(<<"float">>)  -> float;
type_atom(<<"int">>)    -> int;
type_atom(T) -> gt_pack:load_error('bad-directive', "key type ~s is not string, float or int", [T]).

name_str(#{name := undefined}) -> "?";
name_str(#{name := N}) -> N.

%% The target and the arguments are keys of `core` or of the module itself;
%% their types must fit the function.
check_derive({Target, Fun, Args}, M, Modules) ->
    TT = derive_key_type(Target, M#{uses := []}, Modules),
    ATs = [derive_key_type(A, M, Modules) || A <- Args],
    case gt_derive:check_types(Fun, TT, ATs) of
        {ok, Fun1} -> {Target, Fun1, Args};
        {error, Why} ->
            gt_pack:load_error('bad-directive', "derive ~s: ~s", [Target, Why])
    end.

derive_key_type(Key, #{name := Own} = M, Modules) ->
    {Mod, Name} = case binary:split(Key, <<".">>) of
                      [N] -> {<<"core">>, N};
                      [Md, N] -> {Md, N}
                  end,
    Found = if Mod =:= Own -> key_type(M, Name);
               true ->
                    %% `core`, or for an argument a module of a `uses` line
                    case Mod =:= <<"core">> orelse lists:member(Mod, maps:get(uses, M)) of
                        true ->
                            case maps:find(Mod, Modules) of
                                {ok, Other} -> key_type(Other, Name);
                                error -> error
                            end;
                        false -> error
                    end
            end,
    case Found of
        {ok, Type} when Type =/= list -> Type;
        _ ->                                    % undeclared, or a list
            gt_pack:load_error('bad-directive',
                               "derive names ~s, which is not a declared key of core, of module ~s or (an argument) of a module it uses",
                               [Key, name_str(M)])
    end.
