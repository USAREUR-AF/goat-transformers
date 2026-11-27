%% gt_derive: derived keys (engine-spec Version 0.6, Derived keys).
%%
%% A `derive` line of a model module states that a target key follows from
%% argument keys through one function of a fixed set.
%% Function = copy | hypot | bearing | east_of | north_of | neg
%%          | day_seconds | any | 'not' | parse_int | text_of   (Version 0.8)
%%          | present                                        (Version 0.12)
%%          | {scale, Factor} | {offset, Text | Number} | {join, Sep}
%%          | sec_of | nsec_of | ms_of | deg | rad | add | sub
%%          | deg_lat_of | deg_lon_of | m_lat_of | m_lon_of
%%          | ecef_x | ecef_y | ecef_z
%%          | lat_of_ecef | lon_of_ecef | hae_of_ecef            (Version 0.16)
%%          | {tokens, Sep, [Token]} | {has_token, Sep, Token}
%%          | {text_if, Text}                                    (Version 0.18)
%% Sep, Token and Text are binaries (UTF-8).
%% `add` and `sub` are resolved by check_types to {add | sub, int | float}.
-module(gt_derive).
-export([sep_and_rest/2]).                 % for `part` (0.64)
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
function(<<"present">>) -> {present, 1};
function(<<"sec_of">>) -> {sec_of, 1};
function(<<"nsec_of">>) -> {nsec_of, 1};
function(<<"ms_of">>) -> {ms_of, 2};
function(<<"deg">>) -> {deg, 1};
function(<<"rad">>) -> {rad, 1};
function(<<"add">>) -> {add, 2};
function(<<"sub">>) -> {sub, 2};
function(<<"deg_lat_of">>) -> {deg_lat_of, 2};
function(<<"deg_lon_of">>) -> {deg_lon_of, 2};
function(<<"m_lat_of">>) -> {m_lat_of, 2};
function(<<"m_lon_of">>) -> {m_lon_of, 2};
function(<<"ecef_x">>) -> {ecef_x, 3};
function(<<"ecef_y">>) -> {ecef_y, 3};
function(<<"ecef_z">>) -> {ecef_z, 3};
function(<<"lat_of_ecef">>) -> {lat_of_ecef, 3};
function(<<"lon_of_ecef">>) -> {lon_of_ecef, 3};
function(<<"hae_of_ecef">>) -> {hae_of_ecef, 3};
function(<<"scale:", F/binary>>) -> {{scale, gt_pack:factor(F)}, 1};
function(<<"offset:", N/binary>>) -> _ = gt_pack:number(N), {{offset, N}, 1};
function(<<"join:", Sep/binary>>) -> {{join, Sep}, any};
%% Version 0.18
function(<<"tokens:", Rest/binary>> = S) ->
    {Sep, List} = sep_and_rest(Rest, S),
    Tokens = binary:split(List, <<",">>, [global]),
    [token(T, Sep, S) || T <- Tokens],
    case length(lists:usort(Tokens)) =:= length(Tokens) of
        true -> ok;
        false -> bad("~s names a token twice", [S])
    end,
    {{tokens, Sep, Tokens}, length(Tokens)};
function(<<"has_token:", Rest/binary>> = S) ->
    {Sep, T} = sep_and_rest(Rest, S),
    token(T, Sep, S),
    {{has_token, Sep, T}, 1};
function(<<"text_if:", Text/binary>> = S) ->
    case Text =/= <<>> andalso not lists:any(fun is_ws/1, chars(Text, S)) of
        true -> {{text_if, Text}, 1};
        false -> bad("~s: the text is empty or holds whitespace", [S])
    end.

bad(Fmt, Args) -> gt_pack:load_error('bad-directive', Fmt, Args).

%% Space, tab, line feed and carriage return.
is_ws(C) -> C =:= $\s orelse C =:= $\t orelse C =:= $\n orelse C =:= $\r.

%% A text as its code points.
chars(Bin, S) ->
    case unicode:characters_to_list(Bin) of
        L when is_list(L) -> L;
        _ -> bad("~s is not UTF-8 text", [S])
    end.

%% `<sep>:<rest>`: the separator ends at the first `:`, which it cannot hold.
%% One code point other than `:`, `,` or whitespace, or one of the names
%% `space`, `comma`, `colon` (ruling 9: lowercase and exact).
sep_and_rest(Bin, S) ->
    {SepT, Rest} = case binary:split(Bin, <<":">>) of
                       [A, B] -> {A, B};
                       [_] -> bad("~s names no token after the separator", [S])
                   end,
    Sep = case SepT of
              <<"space">> -> <<" ">>;
              <<"comma">> -> <<",">>;
              <<"colon">> -> <<":">>;
              _ ->
                  case chars(SepT, S) of
                      [C] when C =/= $,, C =/= $: ->
                          case is_ws(C) of
                              true -> bad("~s: the separator is whitespace", [S]);
                              false -> SepT
                          end;
                      _ -> bad("~s: the separator is not one character or a name", [S])
                  end
          end,
    {Sep, Rest}.

%% A token: one or more characters other than `:`, `,`, whitespace and the
%% separator character.
token(T, Sep, S) ->
    [SepC] = chars(Sep, S),
    case T =/= <<>> andalso
        lists:all(fun(C) -> C =/= $: andalso C =/= $, andalso C =/= SepC andalso not is_ws(C) end,
                  chars(T, S)) of
        true -> ok;
        false -> bad("~s: the token ~s is empty or holds a character it cannot", [S, T])
    end.

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
%% `present` takes an argument of any scalar type (a list is refused where the
%% argument key is resolved) and gives an int.
check_types(present, int, [_]) -> {ok, present};
check_types({tokens, _, _} = F, string, Args) ->
    case lists:all(fun(A) -> A =:= int end, Args) of
        true -> {ok, F};
        false -> {error, "tokens takes int arguments"}
    end;
check_types({has_token, _, _} = F, int, [string]) -> {ok, F};
check_types({text_if, _} = F, string, [int]) -> {ok, F};
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
%% Version 0.16, ruling 4: no promotion
check_types(F, int, [int]) when F =:= sec_of; F =:= nsec_of -> {ok, F};
check_types(ms_of, int, [int, int]) -> {ok, ms_of};
check_types(F, T, [T, T]) when (F =:= add orelse F =:= sub),
                               (T =:= int orelse T =:= float) -> {ok, {F, T}};
check_types(F, float, Args) when F =:= deg; F =:= rad;
                                 F =:= deg_lat_of; F =:= deg_lon_of;
                                 F =:= m_lat_of; F =:= m_lon_of;
                                 F =:= ecef_x; F =:= ecef_y; F =:= ecef_z;
                                 F =:= lat_of_ecef; F =:= lon_of_ecef;
                                 F =:= hae_of_ecef;
                                 F =:= hypot; F =:= bearing; F =:= east_of;
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

%% `any` and `tokens` (ruling 7 of 0.18) are the functions whose target is
%% set when only some arguments are present: they need at least one.
fun_args({tokens, _, _}, Args, Model) ->
    case [K || K <- Args, maps:is_key(K, Model)] of
        [] -> absent;
        _ -> [maps:get(K, Model, absent) || K <- Args]
    end;
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
%% 1 when the argument is held, whatever its value (Version 0.12)
eval(present, [_]) -> 1;
%% Version 0.18. With only some arguments present, the tokens of the present
%% ones count (ruling 7); none present and not 0 leaves the target absent.
eval({tokens, Sep, Tokens}, Vals) ->
    case [T || {T, V} <- lists:zip(Tokens, Vals), V =/= absent, V =/= 0] of
        [] -> absent;
        Set -> iolist_to_binary(lists:join(Sep, Set))
    end;
eval({has_token, Sep, T}, [A]) ->
    case lists:member(T, binary:split(A, Sep, [global])) of
        true -> 1;
        false -> 0
    end;
eval({text_if, _}, [0]) -> absent;
eval({text_if, Text}, [_]) -> Text;
eval({scale, {dec, F}}, [A]) -> A * F;
eval({scale, {frac, Num, Den}}, [A]) -> A * Num / Den;
eval({offset, N}, [A]) when is_integer(N), is_integer(A) ->
    %% an overflow of the 64-bit model integer leaves the target absent
    case A + N of
        R when R >= -(1 bsl 63), R < (1 bsl 63) -> R;
        _ -> absent
    end;
eval({offset, N}, [A]) when is_float(N) -> A + N;
eval({join, Sep}, Vals) -> iolist_to_binary(lists:join(Sep, Vals));
%% ---- Version 0.16. Integer results are exact (bignums) and only the final
%% result is range-checked (ruling 3); a float operation that would not be
%% finite raises badarith in Erlang, which one/2 turns into an absent target
%% (ruling 1).
eval(sec_of, [Ms]) -> int64(floor_div(Ms, 1000));
eval(nsec_of, [Ms]) -> int64((Ms - 1000 * floor_div(Ms, 1000)) * 1000000);
eval(ms_of, [Sec, Nsec]) -> int64(Sec * 1000 + floor_div(Nsec, 1000000));
eval({add, int}, [A, B]) -> int64(A + B);
eval({sub, int}, [A, B]) -> int64(A - B);
eval({add, float}, [A, B]) -> A + B;
eval({sub, float}, [A, B]) -> A - B;
eval(deg, [R]) -> R * deg_per_rad();
eval(rad, [D]) -> D * rad_per_deg();
eval(deg_lat_of, [Dist, Lat]) ->
    with_lat(Lat, fun(Phi) -> (Dist / m_radius(Phi)) * deg_per_rad() end);
eval(deg_lon_of, [Dist, Lat]) ->
    with_lat(Lat, fun(Phi) ->
                          C = abs(math:cos(Phi)),
                          case C =< 1.0e-12 of
                              true -> absent;
                              false -> (Dist / (n_radius(Phi) * C)) * deg_per_rad()
                          end
                  end);
eval(m_lat_of, [Ang, Lat]) ->
    with_lat(Lat, fun(Phi) -> Ang * rad_per_deg() * m_radius(Phi) end);
eval(m_lon_of, [Ang, Lat]) ->
    with_lat(Lat, fun(Phi) -> Ang * rad_per_deg() * n_radius(Phi) * abs(math:cos(Phi)) end);
eval(ecef_x, [Lat, Lon, Hae]) ->
    with_lat(Lat, fun(Phi) ->
                          L = Lon * rad_per_deg(),
                          (n_radius(Phi) + Hae) * math:cos(Phi) * math:cos(L)
                  end);
eval(ecef_y, [Lat, Lon, Hae]) ->
    with_lat(Lat, fun(Phi) ->
                          L = Lon * rad_per_deg(),
                          (n_radius(Phi) + Hae) * math:cos(Phi) * math:sin(L)
                  end);
eval(ecef_z, [Lat, _Lon, Hae]) ->
    with_lat(Lat, fun(Phi) -> (n_radius(Phi) * (1 - e2()) + Hae) * math:sin(Phi) end);
eval(lon_of_ecef, [X, Y, _Z]) ->
    case X == 0 andalso Y == 0 of
        true -> absent;
        false ->
            D = math:atan2(Y, X) * deg_per_rad(),
            %% ruling 5: (-180, 180]
            case D == -180.0 of
                true -> 180.0;
                false -> D
            end
    end;
eval(lat_of_ecef, [X, Y, Z]) ->
    case heikkinen(X, Y, Z) of
        absent -> absent;
        {Phi, _H} -> Phi * deg_per_rad()
    end;
eval(hae_of_ecef, [X, Y, Z]) ->
    case heikkinen(X, Y, Z) of
        absent -> absent;
        {_Phi, H} -> H
    end.

%% floor(A / B) for integers, rounding toward negative infinity (B > 0 here)
floor_div(A, B) ->
    Q = A div B,
    case (A rem B =/= 0) andalso ((A < 0) =/= (B < 0)) of
        true -> Q - 1;
        false -> Q
    end.

int64(N) when N >= -(1 bsl 63), N < (1 bsl 63) -> N;
int64(_) -> absent.

%% ruling 6: a latitude outside [-90, 90] leaves the target absent
with_lat(Lat, F) when Lat >= -90, Lat =< 90 -> F(Lat * rad_per_deg());
with_lat(_, _) -> absent.

%% WGS 84
wgs_a() -> 6378137.0.
wgs_f() -> 1 / 298.257223563.
e2() -> F = wgs_f(), F * (2 - F).
wgs_b() -> wgs_a() * (1 - wgs_f()).

%% prime vertical radius N and meridional radius M at φ
n_radius(Phi) ->
    S = math:sin(Phi),
    wgs_a() / math:sqrt(1 - e2() * S * S).
m_radius(Phi) ->
    S = math:sin(Phi),
    wgs_a() * (1 - e2()) / math:pow(1 - e2() * S * S, 1.5).

%% ECEF to geodetic, Heikkinen's closed form in the order of the spec:
%% {φ in radians, h} | absent (ruling 2: G =< 0).
heikkinen(X, Y, Z) ->
    A = wgs_a(), B = wgs_b(), E2 = e2(), E4 = E2 * E2,
    A2 = A * A, B2 = B * B,
    P = math:sqrt(X * X + Y * Y),
    F = 54 * B2 * Z * Z,
    G = P * P + (1 - E2) * Z * Z - E2 * (A2 - B2),
    case G =< 0 of
        true -> absent;
        false ->
            C = E4 * F * P * P / (G * G * G),
            S = cbrt(1 + C + math:sqrt(C * C + 2 * C)),
            K = S + 1 + 1 / S,
            PP = F / (3 * K * K * G * G),
            Q = math:sqrt(1 + 2 * E4 * PP),
            %% ruling 9: a negative argument of this square root is taken as 0
            Arg = A2 / 2 * (1 + 1 / Q) - PP * (1 - E2) * Z * Z / (Q * (1 + Q)) - PP * P * P / 2,
            R0 = -PP * E2 * P / (1 + Q) + math:sqrt(max(Arg, 0.0)),
            T = P - E2 * R0,
            U = math:sqrt(T * T + Z * Z),
            V = math:sqrt(T * T + (1 - E2) * Z * Z),
            Z0 = B2 * Z / (A * V),
            H = U * (1 - B2 / (A * V)),
            Phi = math:atan2(Z + (A2 - B2) / B2 * Z0, P),
            {Phi, H}
    end.

%% The real cube root (ruling 1). Erlang's math module has no cbrt: pow on
%% |x|, the sign restored, then one Newton step to bring it to the double
%% nearest the root.
cbrt(X) when X == 0 -> X;
cbrt(X) when X < 0 -> -cbrt(-X);
cbrt(X) ->
    R = math:pow(X, 1 / 3),
    R - (R * R * R - X) / (3 * R * R).

%% 180/π with π as the double nearest to it, the quotient computed first
deg_per_rad() -> 180.0 / math:pi().

%% π/180 with π as the double nearest to it
rad_per_deg() -> math:pi() / 180.0.
