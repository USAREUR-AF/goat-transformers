%% gt_model: parse a model module file (model/<module>.def) into a module map.
%% Clean-room implementation from spec/engine-spec.md (Versions 0.4, 0.6, 0.7) only.
%%
%% Module = #{name => Bin, version => Bin, distribution => public | controlled,
%%            sources => [Bin], keys => [{NameBin, Type, Unit, Meaning}],
%%            types => #{NameBin => Type | list},   % keys and lists, one namespace
%%            derives => [{TargetKey, Function, [ArgumentKey]}]}
%% Type = string | float | int. Derive keys are entity keys, written as in a
%% pack: bare for `core`, `<module>.<key>` otherwise. Function: gt_derive.
-module(gt_model).
-export([parse/1, parse/2, key_type/2]).

parse(Text) -> parse(Text, #{}).

%% Parse one module text (binary or string) -> module map. Modules is the
%% map of modules loaded so far: a `derive` line may name keys of `core`.
parse(Text, Modules) when is_list(Text) -> parse(unicode:characters_to_binary(Text), Modules);
parse(Bin, Modules) ->
    Base = #{name => undefined, version => undefined, distribution => undefined,
             sources => [], keys => [], types => #{}, derives => []},
    M0 = lists:foldl(fun(Line, Acc) -> apply_line(gt_pack:tokens(Line), Acc) end,
                     Base, binary:split(Bin, <<"\n">>, [global])),
    M1 = M0#{sources := lists:reverse(maps:get(sources, M0)),
             keys := lists:reverse(maps:get(keys, M0))},
    %% derive lines are checked once every key line has been read
    Derives = [check_derive(D, M1, Modules) || D <- lists:reverse(maps:get(derives, M0))],
    M = M1#{derives := Derives},
    gt_pack:require_marking(["module ", name_str(M)], M),
    case maps:get(name, M) of
        undefined -> gt_pack:load_error('bad-directive', "the module has no module line", []);
        _ -> ok
    end,
    M.

%% Declared type of a key -> {ok, Type} | error.
key_type(#{types := Types}, Name) -> maps:find(Name, Types).

apply_line([], M) -> M;                      % blank or comment-only line
apply_line([<<"module">>, N], M)  -> M#{name => N};
apply_line([<<"version">>, V], M) -> M#{version => V};
apply_line([<<"distribution">>, D], M) -> M#{distribution => gt_pack:distribution_atom(D)};
apply_line([<<"source">>, S], M)  -> M#{sources := [S | maps:get(sources, M)]};
apply_line([<<"key">>, Name, Type, Unit], M) -> add_key(Name, Type, Unit, <<>>, M);
apply_line([<<"key">>, Name, Type, Unit, Meaning], M) -> add_key(Name, Type, Unit, Meaning, M);
apply_line([<<"list">>, Name], M) -> add_list(Name, M);
apply_line([<<"list">>, Name, _Meaning], M) -> add_list(Name, M);
apply_line([<<"derive">>, Target, Fun | Args], #{derives := Ds} = M) when Args =/= [] ->
    F = case gt_derive:parse_function(Fun, length(Args)) of
            {ok, Parsed} -> Parsed;
            {error, Why} ->
                gt_pack:load_error('bad-directive', "derive ~s ~s: ~s", [Target, Fun, Why])
        end,
    M#{derives := [{Target, F, Args} | Ds]};
apply_line([Dir | _], _M) ->
    case lists:member(Dir, [<<"module">>, <<"version">>, <<"distribution">>, <<"source">>,
                            <<"key">>, <<"list">>, <<"derive">>]) of
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
    TT = derive_key_type(Target, M, Modules),
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
               Mod =:= <<"core">> ->
                    case maps:find(<<"core">>, Modules) of
                        {ok, Core} -> key_type(Core, Name);
                        error -> error
                    end;
               true -> error
            end,
    case Found of
        {ok, Type} when Type =/= list -> Type;
        _ ->                                    % undeclared, or a list
            gt_pack:load_error('bad-directive',
                               "derive names ~s, which is not a declared key of core or of module ~s",
                               [Key, name_str(M)])
    end.
