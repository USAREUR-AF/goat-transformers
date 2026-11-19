%% gt_text: the `text` wire (engine-spec Version 0.10). A record of ASCII
%% text: fields separated by a delimiter, optionally framed by a start text
%% and an `nmea` checksum; a field may be read as character columns.
%% Clean-room implementation from spec/engine-spec.md and the packs only.
%%
%% The pack carries `delimiter` (binary() | none), `start` (binary(), <<>>
%% when there is none) and `checksum` (none | nmea).
%% Locators: {fld, I} | {col, I, From, Len} | {pair, I, J}; inside a group
%% they count from the item's first field.
%% A record read by open/2 is Ctx = {Fields :: tuple(), Base}: the fields of
%% the body, and the index of the first field of the scope (0 for the
%% record, the item's first field inside a group).
%% Residue: [{Index :: integer(), Text :: binary()}].
-module(gt_text).
-export([open/2, when_holds/3, raw/3, decode_value/2, items/3, residue/2,
         encode/4, numeric/1, pair_transform/1, loc_indexes/1]).

-define(EPOCH_DAYS, 719528).           % calendar:date_to_gregorian_days(1970, 1, 1)
-define(DAY_MS, 86400000).

%% ===================================================================
%% reading a record (steps 1 to 5); every failure is malformed-wire
%% ===================================================================
open(Pack, Bytes) ->
    T1 = strip_terminator(Bytes),
    case printable(T1) of
        true -> ok;
        false -> malformed(Pack, "the record holds a character outside 0x20 to 0x7E", [])
    end,
    T2 = case maps:get(start, Pack) of
             <<>> -> T1;
             S ->
                 N = byte_size(S),
                 case T1 of
                     <<S:N/binary, Rest/binary>> -> Rest;
                     _ -> malformed(Pack, "the record does not begin with ~s", [S])
                 end
         end,
    T3 = case maps:get(checksum, Pack) of
             none -> T2;
             nmea -> nmea(Pack, T2)
         end,
    Fields = case maps:get(delimiter, Pack) of
                 none -> [T3];
                 D -> binary:split(T3, D, [global])
             end,
    {list_to_tuple(Fields), 0}.

%% `\r\n` when the text ends with it, else `\n` (ruling 4).
strip_terminator(B) ->
    Size = byte_size(B),
    case B of
        <<Body:(Size - 2)/binary, "\r\n">> when Size >= 2 -> Body;
        <<Body:(Size - 1)/binary, "\n">> when Size >= 1 -> Body;
        _ -> B
    end.

nmea(Pack, T) ->
    Size = byte_size(T),
    {Body, H1, H2} =
        case T of
            <<B:(Size - 3)/binary, $*, X1, X2>> when Size >= 3 -> {B, X1, X2};
            _ -> malformed(Pack, "the record does not end with * and two hexadecimal digits", [])
        end,
    Want = case {hex(H1), hex(H2)} of
               {V1, V2} when is_integer(V1), is_integer(V2) -> V1 * 16 + V2;
               _ -> malformed(Pack, "the checksum digits are not hexadecimal", [])
           end,
    case xor_of(Body) of
        Want -> ok;
        Got -> malformed(Pack, "the checksum is ~2.16.0B and the record's bytes give ~2.16.0B",
                         [Want, Got])
    end,
    case binary:match(Body, <<"*">>) of
        nomatch -> Body;
        _ -> malformed(Pack, "a * is left in the record", [])
    end.

hex(C) when C >= $0, C =< $9 -> C - $0;
hex(C) when C >= $A, C =< $F -> C - $A + 10;
hex(C) when C >= $a, C =< $f -> C - $a + 10;
hex(_) -> error.

xor_of(B) -> xor_of(B, 0).
xor_of(<<C, R/binary>>, X) -> xor_of(R, X bxor C);
xor_of(<<>>, X) -> X.

malformed(Pack, Fmt, Args) -> gt_engine:conv_error('malformed-wire', Pack, Fmt, Args).

printable(<<C, R/binary>>) when C >= 16#20, C =< 16#7E -> printable(R);
printable(<<>>) -> true;
printable(_) -> false.

%% ===================================================================
%% locators
%% ===================================================================
%% The text of field I of the scope -> absent | binary() (possibly empty).
field({Fields, Base}, I) ->
    Idx = Base + I,
    case Idx < tuple_size(Fields) of
        true -> element(Idx + 1, Fields);
        false -> absent
    end.

%% The text a field or a column holds -> absent | {ok, Text}. A column has
%% its trailing spaces removed, and with Numeric its leading spaces too.
read(Ctx, {fld, I}, _Numeric) ->
    case field(Ctx, I) of
        absent -> absent;
        <<>> -> absent;
        T -> {ok, T}
    end;
read(Ctx, {col, I, From, Len}, Numeric) ->
    case field(Ctx, I) of
        absent -> absent;
        T when byte_size(T) =< From -> absent;
        T ->
            C0 = binary:part(T, From, min(Len, byte_size(T) - From)),
            C1 = rtrim(C0),
            C = case Numeric of
                    true -> ltrim(C1);
                    false -> C1
                end,
            case C of
                <<>> -> absent;
                _ -> {ok, C}
            end
    end.

rtrim(B) ->
    case B of
        <<>> -> B;
        _ ->
            case binary:last(B) of
                $\s -> rtrim(binary:part(B, 0, byte_size(B) - 1));
                _ -> B
            end
    end.

ltrim(<<$\s, R/binary>>) -> ltrim(R);
ltrim(B) -> B.

%% The raw value at a field's locator -> absent | {ok, Text | {Text, Text}}.
%% A pair is absent when either of its fields is.
raw(Ctx, {pair, I, J}, _Tr) ->
    case {read(Ctx, {fld, I}, false), read(Ctx, {fld, J}, false)} of
        {{ok, A}, {ok, B}} -> {ok, {A, B}};
        _ -> absent
    end;
raw(Ctx, Loc, Tr) -> read(Ctx, Loc, numeric(Tr)).

%% A `when` compares the field's text, or the column's with its trailing
%% spaces removed; a column its field does not reach does not hold.
when_holds(Ctx, Loc, present) -> read(Ctx, Loc, false) =/= absent;
when_holds(Ctx, Loc, {text, V, _}) -> read(Ctx, Loc, false) =:= {ok, V}.

numeric(int) -> true;
numeric(float) -> true;
numeric({int_w, _}) -> true;
numeric({dec, _, _}) -> true;
numeric(_) -> false.

pair_transform({dm, _, _, _, _}) -> true;
pair_transform({hms_dmy, _}) -> true;
pair_transform(_) -> false.

loc_indexes({fld, I}) -> [I];
loc_indexes({col, I, _, _}) -> [I];
loc_indexes({pair, I, J}) -> [I, J].

%% The items of a group from field Start, N fields each -> absent | [Ctx].
items({Fields, Base}, Start, N) ->
    First = Base + Start,
    Size = tuple_size(Fields),
    case Size > First of
        false -> absent;
        true ->
            Count = (Size - First + N - 1) div N,
            [{Fields, First + K * N} || K <- lists:seq(0, Count - 1)]
    end.

%% Every field that is not empty and that no line of the scope addresses;
%% none at a group's index or beyond.
residue({Fields, _Base}, Lines) ->
    {Addressed, GroupStart} = addressed(Lines),
    [{I, T} || I <- lists:seq(0, tuple_size(Fields) - 1),
               T <- [element(I + 1, Fields)],
               T =/= <<>>, I < GroupStart, not maps:is_key(I, Addressed)].

%% -> {#{Index => AllOptional}, FirstGroupIndex | infinity}. `when …
%% present` addresses nothing; a group addresses its index and beyond.
addressed(Lines) ->
    lists:foldl(
      fun({field, _, Loc, _, _, {_, _, _, Opt, _}}, {M, G}) -> {mark(Loc, Opt, M), G};
         ({wh, _, present, _}, Acc) -> Acc;
         ({wh, Loc, _, _}, {M, G}) -> {mark(Loc, false, M), G};
         ({const, Loc, _, _}, {M, G}) -> {mark(Loc, false, M), G};
         ({group, _, Start, _, _, _}, {M, G}) -> {M, min(G, Start)};
         (_, Acc) -> Acc
      end, {#{}, infinity}, Lines).

mark(Loc, Opt, M) ->
    lists:foldl(fun(I, Acc) ->
                        maps:put(I, Opt andalso maps:get(I, Acc, true), Acc)
                end, M, loc_indexes(Loc)).

%% ===================================================================
%% transforms: decode (any failure raises; the caller names it)
%% ===================================================================
decode_value(string, T) -> T;
decode_value(int, T) -> int_text(T);
decode_value({int_w, _}, T) -> int_text(T);
decode_value(float, T) -> dec_text(T);
decode_value({dec, _, _}, T) -> dec_text(T);
decode_value(iso8601_ms, T) -> gt_iso:decode(T);
decode_value(iso8601_s, T) -> gt_iso:decode(T);
decode_value({dm, D, _F, P, N}, {A, B}) ->
    <<Deg:D/binary, Min:2/binary, Frac/binary>> = A,
    true = digits(Deg) andalso digits(Min) andalso fraction_ok(Frac),
    true = binary_to_integer(Min) < 60,
    Minutes = gt_num:dec_to_float(<<Min/binary, Frac/binary>>),
    V = binary_to_integer(Deg) + Minutes / 60,
    case B of
        <<P>> -> V;
        <<N>> -> -V
    end;
decode_value({hms, _}, T) ->
    {Whole, Seconds, _Ms} = hms_text(T),
    Whole + Seconds;
decode_value({hms_dmy, _}, {T, Date}) ->
    {Whole, _Seconds, Ms} = hms_text(T),
    <<DD:2/binary, MM:2/binary, YY:2/binary>> = Date,
    true = digits(Date),
    Y0 = binary_to_integer(YY),
    Y = case Y0 >= 80 of
            true -> 1900 + Y0;
            false -> 2000 + Y0
        end,
    Day = {Y, binary_to_integer(MM), binary_to_integer(DD)},
    true = calendar:valid_date(Day),
    Days = calendar:date_to_gregorian_days(Day) - ?EPOCH_DAYS,
    Days * ?DAY_MS + Whole * 1000 + Ms.

%% `hhmmss[.d+]` -> {H * 3600 + M * 60 as an integer, the seconds as the
%% double nearest their decimal, the seconds as milliseconds with fraction
%% digits beyond the third truncated}.
hms_text(T) ->
    <<H:2/binary, M:2/binary, S:2/binary, Frac/binary>> = T,
    true = digits(H) andalso digits(M) andalso digits(S) andalso fraction_ok(Frac),
    Hh = binary_to_integer(H),
    Mm = binary_to_integer(M),
    Ss = binary_to_integer(S),
    true = Hh < 24 andalso Mm < 60 andalso Ss < 60,
    Seconds = gt_num:dec_to_float(<<S/binary, Frac/binary>>),
    Milli = case Frac of
                <<>> -> 0;
                <<$., Ds/binary>> ->
                    D3 = case Ds of
                             <<X:3/binary, _/binary>> -> X;
                             _ -> <<Ds/binary, (binary:copy(<<"0">>, 3 - byte_size(Ds)))/binary>>
                         end,
                    binary_to_integer(D3)
            end,
    {Hh * 3600 + Mm * 60, Seconds, Ss * 1000 + Milli}.

%% An optional sign and one or more digits, -2^63 to 2^63-1.
int_text(T) ->
    Ds = case T of
             <<$+, R/binary>> -> R;
             <<$-, R/binary>> -> R;
             _ -> T
         end,
    true = Ds =/= <<>> andalso digits(Ds),
    V = case T of
            <<$+, R2/binary>> -> binary_to_integer(R2);
            _ -> binary_to_integer(T)
        end,
    true = V >= -(1 bsl 63) andalso V < (1 bsl 63),
    V.

%% An optional sign, then digits with at most one `.`, at least one digit;
%% no exponent. The double nearest the decimal; not finite is a failure.
dec_text(T) ->
    Body = case T of
               <<$+, R/binary>> -> R;
               <<$-, R/binary>> -> R;
               _ -> T
           end,
    {NDigits, NDots} = count_dec(Body, 0, 0),
    true = NDigits >= 1 andalso NDots =< 1,
    gt_num:dec_to_float(T).

count_dec(<<C, R/binary>>, D, P) when C >= $0, C =< $9 -> count_dec(R, D + 1, P);
count_dec(<<$., R/binary>>, D, P) -> count_dec(R, D, P + 1);
count_dec(<<>>, D, P) -> {D, P};
count_dec(_, _, _) -> {0, 0}.

digits(<<>>) -> false;
digits(B) -> all_digits(B).

all_digits(<<C, R/binary>>) when C >= $0, C =< $9 -> all_digits(R);
all_digits(<<>>) -> true;
all_digits(_) -> false.

%% Nothing, or `.` and at least one digit.
fraction_ok(<<>>) -> true;
fraction_ok(<<$., Ds/binary>>) -> digits(Ds);
fraction_ok(_) -> false.

%% ===================================================================
%% transforms: encode -> Text | {Text, Text} for a pair
%% ===================================================================
encode_value(string, V) -> to_str(V);
encode_value(int, V) when is_integer(V) -> integer_to_binary(V);
encode_value({int_w, W}, V) when is_integer(V) ->
    signed(V < 0, pad0(integer_to_binary(abs(V)), W));
encode_value(float, V) when is_number(V) -> list_to_binary(gt_num:fmt_float(float(V)));
encode_value({dec, F, W}, V) when is_number(V) ->
    N = round(float(V) * p10(F)),
    true = abs(N) < (1 bsl 53),
    Digits = pad0(integer_to_binary(abs(N)), F + 1),
    Body = point(Digits, F),
    Body1 = case W of
                none -> Body;
                _ -> pad0(Body, W)
            end,
    signed(N < 0, Body1);
encode_value(iso8601_ms, V) when is_integer(V) -> gt_iso:encode(V);
encode_value(iso8601_s, V) when is_integer(V) -> gt_iso:encode_seconds(V);
encode_value({dm, D, F, P, N}, V) when is_number(V) ->
    X = float(V),
    M = round(abs(X) * 60 * p10(F)),
    true = M < (1 bsl 53),
    Scale = pow10(F),
    Unit = 60 * Scale,
    Deg = M div Unit,
    true = Deg < pow10(D),
    Rem = M rem Unit,
    Text = <<(pad0(integer_to_binary(Deg), D))/binary,
             (point(<<(pad0(integer_to_binary(Rem div Scale), 2))/binary,
                      (frac_digits(Rem rem Scale, F))/binary>>, F))/binary>>,
    Letter = case X < 0 andalso M > 0 of
                 true -> N;
                 false -> P
             end,
    {Text, <<Letter>>};
encode_value({hms, F}, V) when is_number(V) ->
    Scale = pow10(F),
    N = round(float(V) * p10(F)),
    true = abs(N) < (1 bsl 53),
    true = N >= 0 andalso N < 86400 * Scale,
    hms_out(N div Scale, N rem Scale, F);
encode_value({hms_dmy, F}, V) when is_integer(V) ->
    Days = floor_div(V, ?DAY_MS),
    DayMs = V - Days * ?DAY_MS,
    {Y, Mo, D} = calendar:gregorian_days_to_date(Days + ?EPOCH_DAYS),
    true = Y >= 1980 andalso Y =< 2079,
    Time = hms_out(DayMs div 1000, (DayMs rem 1000) div pow10(3 - F), F),
    Date = <<(pad0(integer_to_binary(D), 2))/binary, (pad0(integer_to_binary(Mo), 2))/binary,
             (pad0(integer_to_binary(Y rem 100), 2))/binary>>,
    {Time, Date}.

hms_out(Secs, Frac, F) ->
    H = Secs div 3600,
    M = (Secs rem 3600) div 60,
    S = Secs rem 60,
    point(<<(pad0(integer_to_binary(H), 2))/binary, (pad0(integer_to_binary(M), 2))/binary,
            (pad0(integer_to_binary(S), 2))/binary, (frac_digits(Frac, F))/binary>>, F).

frac_digits(_V, 0) -> <<>>;
frac_digits(V, F) -> pad0(integer_to_binary(V), F).

%% A `.` before the last F characters (none when F is 0).
point(Digits, 0) -> Digits;
point(Digits, F) ->
    L = byte_size(Digits) - F,
    <<Int:L/binary, Frac/binary>> = Digits,
    <<Int/binary, $., Frac/binary>>.

signed(true, B) -> <<$-, B/binary>>;
signed(false, B) -> B.

pad0(B, W) when byte_size(B) >= W -> B;
pad0(B, W) -> <<(binary:copy(<<"0">>, W - byte_size(B)))/binary, B/binary>>.

pow10(N) -> pow10(N, 1).
pow10(0, Acc) -> Acc;
pow10(N, Acc) -> pow10(N - 1, Acc * 10).

%% 10^f as the exact double
p10(F) -> float(pow10(F)).

floor_div(A, B) when A >= 0 -> A div B;
floor_div(A, B) -> -((-A + B - 1) div B).

to_str(V) when is_binary(V) -> V;
to_str(V) when is_integer(V) -> integer_to_binary(V);
to_str(V) when is_float(V) -> list_to_binary(gt_num:fmt_float(V)).

%% ===================================================================
%% writing a record
%% ===================================================================
%% Writes, per field index, in line order:
%%   {whole, Text} | {col, From, Text}          a field line
%%   {fixed_whole, Text} | {fixed_col, From, Text}   a `when` or `const`
encode(Pack, Lines, Src, Residue) ->
    {Writes, GroupEnd} = plan(Pack, Lines, Src, 0, #{}, -1),
    {Addressed, GroupStart} = addressed(Lines),
    Written = [{I, T} || {I, T} <- Residue, is_integer(I), I >= 0, I < GroupStart,
                         not maps:is_key(I, Addressed)],
    Highest = lists:max([-1, GroupEnd | maps:keys(Addressed) ++ [I || {I, _} <- Written]]),
    Texts0 = maps:map(fun(_I, Ws) -> assemble(lists:reverse(Ws)) end, Writes),
    Texts = lists:foldl(fun({I, T}, M) -> M#{I => T} end, Texts0, Written),
    Fields0 = [maps:get(I, Texts, <<>>) || I <- lists:seq(0, Highest)],
    Fields = drop_optional(lists:reverse(Fields0), Highest, Addressed),
    Body = case maps:get(delimiter, Pack) of
               none -> iolist_to_binary(Fields);
               D -> iolist_to_binary(lists:join(D, Fields))
           end,
    Tail = case maps:get(checksum, Pack) of
               none -> <<>>;
               nmea -> list_to_binary(io_lib:format("*~2.16.0B", [xor_of(Body)]))
           end,
    <<(maps:get(start, Pack))/binary, Body/binary, Tail/binary>>.

%% Step 5: the last field is removed while it is empty and every line that
%% addresses it (at least one) is `optional`. Fields given reversed.
drop_optional([<<>> | Rest], I, Addressed) ->
    case maps:find(I, Addressed) of
        {ok, true} -> drop_optional(Rest, I - 1, Addressed);
        _ -> lists:reverse([<<>> | Rest])
    end;
drop_optional(Fields, _I, _Addressed) -> lists:reverse(Fields).

%% The writes of the lines of one scope from field Base -> {Writes, GroupEnd}:
%% Writes #{Index => [Write]} latest first; GroupEnd the last field a
%% group's items write (-1 when none).
plan(Pack, Lines, {Value, Lists}, Base, Writes0, End0) ->
    %% a field written whole by a line whose key has a value: its columns
    %% are not written (ruling 3)
    Whole = lists:foldl(
              fun({field, K, {fld, I}, _, _, _}, S) ->
                      case Value(K) of
                          error -> S;
                          _ -> S#{I => true}
                      end;
                 ({field, K, {pair, I, J}, _, _, _}, S) ->
                      case Value(K) of
                          error -> S;
                          _ -> S#{I => true, J => true}
                      end;
                 (_, S) -> S
              end, #{}, Lines),
    Delim = maps:get(delimiter, Pack),
    Nmea = maps:get(checksum, Pack) =:= nmea,
    lists:foldl(
      fun({field, Key, Loc, Tr, LocT, Opts}, {W, E}) ->
              Skip = case Loc of
                         {col, I, _, _} -> maps:is_key(I, Whole);
                         _ -> false
                     end,
              case {Skip, Value(Key)} of
                  {true, _} -> {W, E};
                  {_, error} -> {W, E};
                  {false, {ok, Val}} ->
                      Out = gt_engine:guard_encode(
                              Pack, Key, LocT,
                              fun() ->
                                      T = encode_value(Tr, gt_engine:wire_value(Pack, Key, Tr, Opts, Val)),
                                      field_out(Loc, Tr, T, Delim, Nmea)
                              end),
                      {lists:foldl(fun({I, Wr}, Acc) -> add(Base + I, Wr, Acc) end, W, Out), E}
              end;
         ({wh, _, present, _}, Acc) -> Acc;
         ({wh, Loc, {text, V, _}, _}, {W, E}) -> {add_fixed(Base, Loc, V, W), E};
         ({const, Loc, {text, V, _}, _}, {W, E}) -> {add_fixed(Base, Loc, V, W), E};
         ({group, List, Start, {text_item, N}, Body, _}, {W, E}) ->
              case maps:find(List, Lists) of
                  {ok, [_ | _] = Items} ->
                      First = Base + Start,
                      {W2, _} = lists:foldl(
                                  fun(Item, {WAcc, K}) ->
                                          {WI, _} = plan(Pack, maps:get(lines, Body),
                                                         gt_engine:item_source(Item, Body),
                                                         First + K * N, WAcc, -1),
                                          {WI, K + 1}
                                  end, {W, 0}, Items),
                      {W2, max(E, First + length(Items) * N - 1)};
                  _ -> {W, E}
              end;
         (_, Acc) -> Acc
      end, {Writes0, End0}, Lines).

add(I, Wr, W) -> maps:update_with(I, fun(L) -> [Wr | L] end, [Wr], W).

add_fixed(Base, {fld, I}, V, W) -> add(Base + I, {fixed_whole, V}, W);
add_fixed(Base, {col, I, From, Len}, V, W) -> add(Base + I, {fixed_col, From, pad_right(V, Len)}, W).

%% The text a field line writes -> [{Index, Write}]. Every text is checked:
%% the delimiter, a `*` under nmea and a character outside 0x20 to 0x7E are
%% refused; a column's text longer than the column too.
field_out({pair, I, J}, _Tr, {A, B}, Delim, Nmea) ->
    [{I, {whole, check(A, Delim, Nmea)}}, {J, {whole, check(B, Delim, Nmea)}}];
field_out({fld, I}, _Tr, T, Delim, Nmea) when is_binary(T) ->
    [{I, {whole, check(T, Delim, Nmea)}}];
field_out({col, I, From, Len}, Tr, T, Delim, Nmea) when is_binary(T) ->
    T1 = check(T, Delim, Nmea),
    true = byte_size(T1) =< Len,
    Padded = case numeric(Tr) of
                 true ->
                     case T1 of
                         <<$-, R/binary>> -> <<$-, (pad0(R, Len - 1))/binary>>;
                         _ -> pad0(T1, Len)
                     end;
                 false -> pad_right(T1, Len)
             end,
    [{I, {col, From, Padded}}].

check(T, Delim, Nmea) ->
    true = printable(T),
    true = Delim =:= none orelse binary:match(T, Delim) =:= nomatch,
    true = not Nmea orelse binary:match(T, <<"*">>) =:= nomatch,
    T.

pad_right(B, Len) when byte_size(B) >= Len -> B;
pad_right(B, Len) -> <<B/binary, (binary:copy(<<" ">>, Len - byte_size(B)))/binary>>.

%% The text of one field from its writes in line order. A whole-field line
%% gives the text (the earliest stands), else the columns, an earlier
%% column's characters standing, with spaces where no column writes. Then
%% `when` and `const` are written over it, the earliest standing (ruling 11).
assemble(Ws) ->
    Base = case [T || {whole, T} <- Ws] of
               [T | _] -> T;
               [] -> columns([{F, T} || {col, F, T} <- Ws])
           end,
    Fixed = [W || W <- Ws, element(1, W) =:= fixed_whole orelse element(1, W) =:= fixed_col],
    lists:foldl(fun({fixed_whole, T}, _Acc) -> T;
                   ({fixed_col, From, T}, Acc) -> overwrite(Acc, From, T)
                end, Base, lists:reverse(Fixed)).

columns(Cols) ->
    {Chars, End} = lists:foldl(
                     fun({From, T}, {M, E}) ->
                             {lists:foldl(
                                fun({K, C}, Acc) ->
                                        case maps:is_key(From + K, Acc) of
                                            true -> Acc;
                                            false -> Acc#{From + K => C}
                                        end
                                end, M, lists:zip(lists:seq(0, byte_size(T) - 1),
                                                  binary_to_list(T))),
                              max(E, From + byte_size(T))}
                     end, {#{}, 0}, Cols),
    list_to_binary([maps:get(P, Chars, $\s) || P <- lists:seq(0, End - 1)]).

%% The text padded with spaces to reach the column, T written at From.
overwrite(Text, From, T) ->
    Len = byte_size(T),
    Padded = pad_right(Text, From + Len),
    <<Before:From/binary, _:Len/binary, After/binary>> = Padded,
    <<Before/binary, T/binary, After/binary>>.
