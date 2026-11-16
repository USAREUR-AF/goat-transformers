%% gt_derive: derived keys (engine-spec Version 0.6, Derived keys).
%%
%% A `derive` line of a model module states that a target key follows from
%% argument keys through one function of a fixed set.
%% Function = copy | hypot | bearing | east_of | north_of | neg
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
function(<<"scale:", F/binary>>) -> {{scale, gt_pack:factor(F)}, 1};
function(<<"offset:", N/binary>>) -> _ = gt_pack:number(N), {{offset, N}, 1};
function(<<"join:", Sep/binary>>) -> {{join, Sep}, any}.

%% Do the declared types fit the function? -> {ok, Function} | {error, Why}.
%% `offset` is resolved to integer or float addition here.
check_types(copy, T, [T]) -> {ok, copy};
check_types({offset, Text}, int, [int]) ->
    try binary_to_integer(Text) of N -> {ok, {offset, N}}
    catch _:_ -> {error, "an offset on an int key is a decimal integer"}
    end;
check_types({offset, Text}, float, [float]) -> {ok, {offset, gt_num:dec_to_float(Text)}};
check_types({join, _} = F, string, Args) ->
    case lists:all(fun(A) -> A =:= string end, Args) of
        true -> {ok, F};
        false -> {error, "join takes string arguments"}
    end;
check_types(F, float, Args) when F =:= hypot; F =:= bearing; F =:= east_of;
                                 F =:= north_of; F =:= neg; element(1, F) =:= scale ->
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
            case args(Args, Model, []) of
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
