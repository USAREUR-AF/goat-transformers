%% gt_derive: derived keys (engine-spec Version 0.6, Derived keys).
%%
%% A `derive` line of a model module states that a target key follows from
%% argument keys through one function of a fixed set.
%% Function = copy | hypot | bearing | east_of | north_of | neg
%%          | day_seconds | any | 'not' | parse_int | text_of   (Version 0.8)
%%          | {scale, Factor} | {offset, Text | Number} | {join, Sep}
-module(gt_derive).
-export([parse_function/2, check_types/3, apply_all/2]).

%% Function text and argument count -> {ok, Function} | {error, Why}.
parse_function(Text, NArgs) ->
    try function(Text) of
        {F, any} when NArgs >= 1 -> {ok, F};
        {F, NArgs} -> {ok, F};
        {_, N} -> {error, io_lib:format("takes ~p argument(s), not ~p", [N, NArgs])}
    catch
        error:{load_error, _, Msg} -> {error, Msg};
        _:_ -> {error, "is not a function of the table"}
    end.

function(<<"copy">>) -> {copy, 1};
function(<<"hypot">>) -> {hypot, 2};
function(<<"bearing">>) -> {bearing, 2};
function(<<"east_of">>) -> {east_of, 2};
function(<<"north_of">>) -> {north_of, 2};
function(<<"neg">>) -> {neg, 1};
function(<<"day_seconds">>) -> {day_seconds, 1};
function(<<"any">>) -> {any, any};
function(<<"not">>) -> {'not', 1};
function(<<"parse_int">>) -> {parse_int, 1};
function(<<"text_of">>) -> {text_of, 1};
function(<<"scale:", F/binary>>) -> {{scale, gt_pack:factor(F)}, 1};
function(<<"offset:", N/binary>>) -> _ = gt_pack:number(N), {{offset, N}, 1};
function(<<"join:", Sep/binary>>) -> {{join, Sep}, any}.

%% Do the declared types fit the function? -> {ok, Function} | {error, Why}.
%% `offset` is resolved to integer or float addition here.
check_types(copy, T, [T]) -> {ok, copy};
check_types(day_seconds, float, [int]) -> {ok, day_seconds};
check_types(any, int, Args) ->
    case lists:all(fun(A) -> A =:= int end, Args) of
        true -> {ok, any};
        false -> {error, "any takes int arguments"}
    end;
check_types('not', int, [int]) -> {ok, 'not'};
check_types(parse_int, int, [string]) -> {ok, parse_int};
check_types(text_of, string, [int]) -> {ok, text_of};
%% the parameter is integer text (2a of 0.11) on an int key, number text
%% (2b) on a float key
check_types({offset, Text}, int, [int]) ->
    case gt_num:int_text(Text) of
        {ok, N} -> {ok, {offset, N}};
        error -> {error, "an offset on an int key is integer text"}
    end;
check_types({offset, Text}, float, [float]) -> {ok, {offset, gt_num:read_as(float, Text)}};
check_types({join, _} = F, string, Args) ->
    case lists:all(fun(A) -> A =:= string end, Args) of
        true -> {ok, F};
        false -> {error, "join takes string arguments"}
    end;
check_types(F, float, Args) when F =:= hypot; F =:= bearing; F =:= east_of;
                                 F =:= north_of; F =:= neg;
                                 is_tuple(F) andalso element(1, F) =:= scale ->
    case lists:all(fun(A) -> A =:= float end, Args) of
        true -> {ok, F};
        false -> {error, "the function takes float arguments"}
    end;
check_types(_, _, _) -> {error, "the key types do not fit the function"}.

%% Apply the derive lines, in order, to a model map: a line whose target is
%% absent and whose arguments are all present sets the target. The pass
%% repeats until a pass sets nothing, at most 8 times.
apply_all(Derives, Model) -> passes(Derives, Model, 8).

passes(_Derives, Model, 0) -> Model;
passes(Derives, Model, Left) ->
    case lists:foldl(fun one/2, Model, Derives) of
        Model -> Model;
        Model1 -> passes(Derives, Model1, Left - 1)
    end.

one({Target, Fun, Args}, Model) ->
    case maps:is_key(Target, Model) of
        true -> Model;
        false ->
            case fun_args(Fun, Args, Model) of
                absent -> Model;
                Vals ->
                    %% a result that is not finite leaves the target absent
                    try eval(Fun, Vals) of
                        absent -> Model;
                        V -> Model#{Target => V}
                    catch _:_ -> Model
                    end
            end
    end.

%% `any` is the one function whose target is set when only some arguments
%% are present: it needs at least one.
fun_args(any, Args, Model) ->
    case [V || K <- Args, {ok, V} <- [maps:find(K, Model)]] of
        [] -> absent;
        Vals -> Vals
    end;
fun_args(_Fun, Args, Model) -> args(Args, Model, []).

args([], _Model, Acc) -> lists:reverse(Acc);
args([K | Rest], Model, Acc) ->
    case maps:find(K, Model) of
        {ok, V} -> args(Rest, Model, [V | Acc]);
        error -> absent
    end.

eval(copy, [A]) -> A;
eval(hypot, [A, B]) -> math:sqrt(A * A + B * B);
eval(bearing, [East, North]) ->
    case East == 0 andalso North == 0 of
        true -> absent;
        false ->
            %% radians to degrees: times 180/π, the quotient computed first
            D = math:atan2(East, North) * (180.0 / math:pi()),
            D1 = if D < 0 -> D + 360.0; true -> D end,
            if D1 >= 360.0 -> D1 - 360.0; true -> D1 end
    end;
eval(east_of, [Speed, Course]) -> Speed * math:sin(Course * rad_per_deg());
eval(north_of, [Speed, Course]) -> Speed * math:cos(Course * rad_per_deg());
eval(neg, [A]) -> -A;
%% seconds since UTC midnight of an instant in epoch ms
eval(day_seconds, [Ms]) -> (((Ms rem 86400000) + 86400000) rem 86400000) / 1000;
eval(any, Vals) ->
    case lists:any(fun(V) -> V =/= 0 end, Vals) of
        true -> 1;
        false -> 0
    end;
eval('not', [0]) -> 1;
eval('not', [_]) -> 0;
eval(parse_int, [Text]) ->
    Digits = case Text of
                 <<$-, R/binary>> -> R;
                 _ -> Text
             end,
    case Digits =/= <<>> andalso lists:all(fun(C) -> C >= $0 andalso C =< $9 end,
                                           binary_to_list(Digits)) of
        true ->
            case binary_to_integer(Text) of
                N when N >= -(1 bsl 63), N < (1 bsl 63) -> N;
                _ -> absent
            end;
        false -> absent
    end;
eval(text_of, [N]) -> integer_to_binary(N);
eval({scale, {dec, F}}, [A]) -> A * F;
eval({scale, {frac, Num, Den}}, [A]) -> A * Num / Den;
eval({offset, N}, [A]) when is_integer(N), is_integer(A) ->
    %% an overflow of the 64-bit model integer leaves the target absent
    case A + N of
        R when R >= -(1 bsl 63), R < (1 bsl 63) -> R;
        _ -> absent
    end;
eval({offset, N}, [A]) when is_float(N) -> A + N;
eval({join, Sep}, Vals) -> iolist_to_binary(lists:join(Sep, Vals)).

%% π/180 with π as the double nearest to it
rad_per_deg() -> math:pi() / 180.0.
