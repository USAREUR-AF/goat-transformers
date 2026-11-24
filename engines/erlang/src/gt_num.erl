%% gt_num: number parsing and canonical number text (engine-spec ruling 3).
-module(gt_num).
-export([charcode_decode/3, charcode_encode/3, charcode_codes/3, charcode_from/3,
         charcode_split/2, charcode_join/2]).
-export([to_float/1, to_int/1, fmt_float/1, fmt_int/1, dec_to_float/1, wrap64/1,
         canon/1, read_as/2, int_text/1, uint_text/1, num_text/1, exact_int/1]).

%% Canonical text of a model value: a string as it is, an integer as decimal
%% digits, a float as in ruling 3 of 0.1.1.
canon(V) when is_binary(V) -> V;
canon(V) when is_integer(V) -> integer_to_binary(V);
canon(V) when is_float(V) -> list_to_binary(fmt_float(V)).

%% Read text as a model type; raises when the text is not of that type.
%% Integers by ruling 2a of 0.11, numbers by ruling 2b.
read_as(string, T) when is_binary(T) -> T;
read_as(int, T) when is_binary(T) -> {ok, I} = int_text(T), I;
read_as(float, T) when is_binary(T) -> {ok, F} = num_text(T), F.

%% ---- the grammars of ruling 2 of 0.11 ----

%% 2a: an optional `-`, one or more ASCII digits, within a signed 64-bit
%% integer -> {ok, integer()} | error.
int_text(<<$-, D/binary>>) when D =/= <<>> -> int_range(D, true);
int_text(D) when is_binary(D), D =/= <<>> -> int_range(D, false);
int_text(_) -> error.

int_range(D, Neg) ->
    case all_digits(D) of
        false -> error;
        true ->
            Stripped = strip_zeros(D),
            case byte_size(Stripped) > 19 of
                true -> error;
                false ->
                    N = case Neg of
                            true -> -binary_to_integer(D);
                            false -> binary_to_integer(D)
                        end,
                    in_int64(N)
            end
    end.

in_int64(N) when N >= -(1 bsl 63), N < (1 bsl 63) -> {ok, N};
in_int64(_) -> error.

strip_zeros(<<$0, R/binary>>) when R =/= <<>> -> strip_zeros(R);
strip_zeros(B) -> B.

%% An unsigned decimal integer (2c): one or more ASCII digits -> {ok, N} | error.
uint_text(B) when is_binary(B), B =/= <<>> ->
    case all_digits(B) of
        true -> {ok, binary_to_integer(B)};
        false -> error
    end;
uint_text(_) -> error.

%% 2b: [-] digits [. digits] [(e|E) [+|-] digits], read as the nearest
%% double; a text whose nearest double is infinite is refused, one nearer to
%% zero than the smallest subnormal reads as 0, and `-` before a zero gives
%% -0.0 -> {ok, float()} | error.
num_text(B) when is_binary(B) ->
    case num_parts(B) of
        {ok, Neg, Int, Frac, Exp} -> parts_to_float(Neg, Int, Frac, Exp);
        error -> error
    end;
num_text(_) -> error.

%% The parts of number text by the grammar of 2b
%% -> {ok, Negative, IntDigits, FracDigits, ExpText} | error.
num_parts(B) ->
    {Neg, B1} = case B of
                    <<$-, R/binary>> -> {true, R};
                    _ -> {false, B}
                end,
    {Int, B2} = take_digits(B1),
    case Int of
        <<>> -> error;
        _ ->
            case B2 of
                <<$., B3/binary>> ->
                    case take_digits(B3) of
                        {<<>>, _} -> error;
                        {Frac, B4} -> num_exp(Neg, Int, Frac, B4)
                    end;
                _ -> num_exp(Neg, Int, <<>>, B2)
            end
    end.

num_exp(Neg, Int, Frac, <<>>) -> {ok, Neg, Int, Frac, <<"0">>};
num_exp(Neg, Int, Frac, <<E, R/binary>>) when E =:= $e; E =:= $E ->
    {Sign, R1} = case R of
                     <<$+, X/binary>> -> {<<>>, X};
                     <<$-, X/binary>> -> {<<"-">>, X};
                     _ -> {<<>>, R}
                 end,
    case take_digits(R1) of
        {<<>>, _} -> error;
        {Ds, <<>>} -> {ok, Neg, Int, Frac, <<Sign/binary, Ds/binary>>};
        _ -> error
    end;
num_exp(_, _, _, _) -> error.

take_digits(B) -> take_digits(B, 0).
take_digits(B, N) ->
    case B of
        <<_:N/binary, C, _/binary>> when C >= $0, C =< $9 -> take_digits(B, N + 1);
        <<D:N/binary, R/binary>> -> {D, R}
    end.

parts_to_float(Neg, Int, Frac, Exp) ->
    AllZero = all_zero(Int) andalso all_zero(Frac),
    Sign = case Neg of true -> "-"; false -> "" end,
    case AllZero of
        true ->
            {ok, case Neg of true -> -0.0; false -> 0.0 end};
        false ->
            %% an exponent of very many digits is read by its sign alone
            ExpS = binary_to_list(Exp),
            ExpN = case length(ExpS) > 12 of
                       true ->
                           case ExpS of
                               [$- | _] -> -100000000;
                               _ -> 100000000
                           end;
                       false -> list_to_integer(ExpS)
                   end,
            Text = Sign ++ binary_to_list(Int) ++ "." ++ or0(binary_to_list(Frac))
                ++ "e" ++ integer_to_list(ExpN),
            try list_to_float(Text) of
                F when F == 0.0, Neg -> {ok, -0.0};
                F -> {ok, F}
            catch _:_ ->
                %% list_to_float refuses an infinite result; a result below
                %% the smallest subnormal it gives as 0
                error
            end
    end.

all_zero(<<>>) -> true;
all_zero(<<$0, R/binary>>) -> all_zero(R);
all_zero(_) -> false.

%% The exact value of number text (2b, or JSON number text) as an integer
%% within a signed 64-bit integer (ruling 2d of 0.11) -> {ok, I} | error.
exact_int(B) when is_binary(B) ->
    case num_parts(B) of
        error -> error;
        {ok, Neg, Int, Frac, Exp} ->
            Digits0 = strip_zeros(<<Int/binary, Frac/binary>>),
            case all_zero(Digits0) of
                true -> {ok, 0};
                false ->
                    ExpS = binary_to_list(Exp),
                    case length(ExpS) > 12 of
                        true ->
                            error;          % far above the range, or not an integer
                        false ->
                            E = list_to_integer(ExpS) - byte_size(Frac),
                            {Digits, E1} = drop_trailing_zeros(Digits0, E),
                            case E1 < 0 orelse byte_size(Digits) + E1 > 19 of
                                true -> error;
                                false ->
                                    M = binary_to_integer(Digits) * pow10(E1),
                                    in_int64(case Neg of true -> -M; false -> M end)
                            end
                    end
            end
    end;
exact_int(_) -> error.

drop_trailing_zeros(D, E) when byte_size(D) > 1 ->
    case binary:last(D) of
        $0 -> drop_trailing_zeros(binary:part(D, 0, byte_size(D) - 1), E + 1);
        _ -> {D, E}
    end;
drop_trailing_zeros(D, E) -> {D, E}.

pow10(0) -> 1;
pow10(N) -> 10 * pow10(N - 1).

all_digits(<<>>) -> true;
all_digits(<<C, R/binary>>) when C >= $0, C =< $9 -> all_digits(R);
all_digits(_) -> false.

%% Parse a wire value (string/binary) or an already-typed number to a float.
to_float(F) when is_float(F) -> F;
to_float(I) when is_integer(I) -> float(I);
to_float(S) -> dec_to_float(S).

%% Parse to an integer.
to_int(I) when is_integer(I) -> I;
to_int(F) when is_float(F) ->
    case F == trunc(F) of
        true -> trunc(F);
        false -> erlang:error({int_decode, F})
    end;
to_int(B) when is_binary(B) -> to_int(binary_to_list(B));
to_int(S) when is_list(S) ->
    try list_to_integer(S)
    catch _:_ -> erlang:error({int_decode, S}) end.

%% Decimal text -> the nearest double. [-+]digits[.digits][(e|E)[-+]digits],
%% with digits on at least one side of the point.
dec_to_float(B) when is_binary(B) -> dec_to_float(binary_to_list(B));
dec_to_float(S) when is_list(S) ->
    {Sign, S1} = case S of
                     [$- | R] -> {"-", R};
                     [$+ | R] -> {"", R};
                     _ -> {"", S}
                 end,
    {Int, S2} = digits(S1, []),
    {Frac, S3} = case S2 of
                     [$. | R2] -> digits(R2, []);
                     _ -> {"", S2}
                 end,
    Exp = case S3 of
              [] -> "0";
              [E | R3] when E =:= $e; E =:= $E ->
                  {ESign, R4} = case R3 of
                                    [$- | R5] -> {"-", R5};
                                    [$+ | R5] -> {"", R5};
                                    _ -> {"", R3}
                                end,
                  case digits(R4, []) of
                      {[_ | _] = Ds, []} -> ESign ++ Ds;
                      _ -> erlang:error({float_decode, S})
                  end;
              _ -> erlang:error({float_decode, S})
          end,
    case Int ++ Frac of
        [] -> erlang:error({float_decode, S});
        _ -> ok
    end,
    try list_to_float(Sign ++ or0(Int) ++ "." ++ or0(Frac) ++ "e" ++ Exp)
    catch _:_ -> erlang:error({float_decode, S})
    end.

digits([C | R], Acc) when C >= $0, C =< $9 -> digits(R, [C | Acc]);
digits(R, Acc) -> {lists:reverse(Acc), R}.

or0([]) -> "0";
or0(Ds) -> Ds.

%% The model integer is 64-bit two's complement: keep the low 64 bits.
wrap64(I) ->
    U = I band 16#FFFFFFFFFFFFFFFF,
    case U >= (1 bsl 63) of
        true -> U - (1 bsl 64);
        false -> U
    end.

fmt_int(I) when is_integer(I) -> integer_to_list(I).

%% Canonical float text: shortest round-trip decimal, plain notation, no
%% decimal point for integer-valued floats, negative zero printed "0".
fmt_float(F) when is_float(F) ->
    case is_int_valued(F) of
        true  -> integer_to_list(trunc(F));   % trunc(-0.0) =:= 0 -> "0"
        false -> plain(float_to_list(F, [short]))
    end.

is_int_valued(F) ->
    (F == trunc(F)) andalso (abs(F) < 1.0e15).

%% float_to_list/short never emits an exponent for the magnitudes used here,
%% but expand one defensively so output is always plain decimal.
plain(S) ->
    case string:to_lower(S) of
        Low ->
            case string:chr(Low, $e) of
                0 -> S;
                _ -> expand_exp(S)
            end
    end.

expand_exp(S) ->
    {Mant, ExpStr} = split_e(S),
    Exp = list_to_integer(ExpStr),
    {Sign, Digits0} = case Mant of
                          [$- | R] -> {"-", R};
                          _ -> {"", Mant}
                      end,
    {IntPart, FracPart} = case string:split(Digits0, ".") of
                              [I, Fr] -> {I, Fr};
                              [I] -> {I, ""}
                          end,
    AllDigits = IntPart ++ FracPart,
    PointPos = length(IntPart) + Exp,
    Result =
        if PointPos =< 0 ->
               "0." ++ lists:duplicate(-PointPos, $0) ++ AllDigits;
           PointPos >= length(AllDigits) ->
               AllDigits ++ lists:duplicate(PointPos - length(AllDigits), $0);
           true ->
               {L, Rt} = lists:split(PointPos, AllDigits),
               L ++ "." ++ Rt
        end,
    strip_trailing(Sign ++ Result).

split_e(S) ->
    [M, E] = string:split(string:to_lower(S), "e"),
    {M, E}.

strip_trailing(S) ->
    case string:chr(S, $.) of
        0 -> S;
        _ -> re_strip(S)
    end.

re_strip(S) ->
    S1 = string:trim(S, trailing, "0"),
    string:trim(S1, trailing, ".").

%% ---- character codes (Version 0.46) ----
%% Sets: [{Characters, Size, Width}], first position first. Any failure
%% raises; the caller names it.
%% the text of a text wire <-> the model value
charcode_decode(Kind, Sets, Text) -> charcode_from(Kind, Sets, charcode_text(Sets, Text)).

charcode_encode(Kind, Sets, V) -> charcode_from(codestr, Sets, charcode_codes(Kind, Sets, V)).

%% the codes of a text, one character per position
charcode_text([{Chars, _, _} | Sets], <<C, Rest/binary>>) ->
    {I, 1} = binary:match(Chars, <<C>>),
    [I | charcode_text(Sets, Rest)];
charcode_text([], <<>>) -> [].

%% the codes of a model value: a text, or a mixed-radix number
charcode_codes(codenum, Sets, X) when is_integer(X), X >= 0 ->
    {0, Codes} = lists:foldr(fun({_, N, _}, {Q, Acc}) -> {Q div N, [Q rem N | Acc]} end,
                             {X, []}, Sets),
    Codes;
charcode_codes(Kind, Sets, Text) when Kind =/= codenum, is_binary(Text) -> charcode_text(Sets, Text).

%% the model value of codes, each within its set
charcode_from(Kind, Sets, Codes) ->
    Pairs = lists:zip(Sets, Codes),
    true = lists:all(fun({{_, N, _}, C}) -> C < N end, Pairs),
    case Kind of
        codenum -> lists:foldl(fun({{_, N, _}, C}, V) -> V * N + C end, 0, Pairs);
        _ -> << <<(binary:at(Chars, C))>> || {{Chars, _, _}, C} <- Pairs >>
    end.

%% the bits of a field <-> its codes, the last position least significant
charcode_split(Sets, U) ->
    {_, Codes} = lists:foldr(fun({_, _, W}, {R, Acc}) ->
                                     {R bsr W, [R band ((1 bsl W) - 1) | Acc]}
                             end, {U, []}, Sets),
    Codes.

charcode_join(Sets, Codes) ->
    lists:foldl(fun({{_, _, W}, C}, U) -> (U bsl W) bor C end, 0, lists:zip(Sets, Codes)).
