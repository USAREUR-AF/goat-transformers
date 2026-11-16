%% gt_num: number parsing and canonical number text (engine-spec ruling 3).
-module(gt_num).
-export([to_float/1, to_int/1, fmt_float/1, fmt_int/1, dec_to_float/1, wrap64/1,
         canon/1, read_as/2]).

%% Canonical text of a model value: a string as it is, an integer as decimal
%% digits, a float as in ruling 3 of 0.1.1.
canon(V) when is_binary(V) -> V;
canon(V) when is_integer(V) -> integer_to_binary(V);
canon(V) when is_float(V) -> list_to_binary(fmt_float(V)).

%% Read text as a model type; raises when the text is not of that type.
read_as(string, T) when is_binary(T) -> T;
read_as(int, <<$-, D/binary>> = T) when D =/= <<>> -> true = all_digits(D), binary_to_integer(T);
read_as(int, T) when is_binary(T), T =/= <<>> -> true = all_digits(T), binary_to_integer(T);
read_as(float, T) when is_binary(T) -> dec_to_float(T).

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
