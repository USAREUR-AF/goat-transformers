%% gt_json: a small JSON reader and canonical writer. Objects keep member order.
%%   object -> {object, [{KeyBinary, Value}]}
%%   array  -> {array, [Value]}
%%   string -> binary() (UTF-8)
%%   number -> integer() (no fraction, no exponent) | {dnum, Text}
%%   true/false/null -> 'true' | 'false' | 'null'
-module(gt_json).
-export([parse/1, parse_raw/1, get/2, escape/1, encode/1, number_text/1, is_number_text/1,
         has_duplicate_member/1, read_number/1, canonical_text/1,
         num_float/1, num_int/1, is_num/1]).

%% Arrays and objects nest at most this deep; the outermost is level 1.
-define(MAX_DEPTH, 64).

parse(Cs) when is_list(Cs) -> parse(list_to_binary(Cs));
parse(Bin) when is_binary(Bin) -> parse(Bin, num).

%% As parse/1, but a number is {num, Text} with its text as written;
%% encode/1 writes it back as that text.
parse_raw(Bin) when is_binary(Bin) -> parse(Bin, raw).

%% The reader is total: any input that is not one JSON value (RFC 8259)
%% followed only by whitespace raises error:{json_malformed, Why}, and so
%% does nesting deeper than ?MAX_DEPTH arrays and objects (ruling 35 of 0.8).
parse(Bin, Mode) ->
    {V, Rest} = value(ws(Bin), Mode, 0),
    case ws(Rest) of
        <<>> -> V;
        _ -> bad(trailing_content)
    end.

bad(Why) -> erlang:error({json_malformed, Why}).

%% member lookup on an object
get({object, Members}, Key) when is_binary(Key) ->
    case lists:keyfind(Key, 1, Members) of
        {_, V} -> {ok, V};
        false -> absent
    end;
get({object, _} = O, Key) when is_list(Key) -> get(O, list_to_binary(Key));
get(_, _) -> absent.

value(<<"{", R/binary>>, Mode, Depth) -> object(ws(R), [], Mode, deeper(Depth));
value(<<"[", R/binary>>, Mode, Depth) -> array(ws(R), [], Mode, deeper(Depth));
value(<<"\"", R/binary>>, _, _) -> string_lit(R, 0, []);
value(<<"true", R/binary>>, _, _) -> {true, R};
value(<<"false", R/binary>>, _, _) -> {false, R};
value(<<"null", R/binary>>, _, _) -> {null, R};
value(Bin, num, _) -> number_lit(Bin);
value(Bin, raw, _) ->
    {_, Rest} = number_lit(Bin),
    Len = byte_size(Bin) - byte_size(Rest),
    {{num, binary:part(Bin, 0, Len)}, Rest}.

%% The outermost array or object is level 1.
deeper(Depth) when Depth < ?MAX_DEPTH -> Depth + 1;
deeper(_) -> bad(nesting_too_deep).

object(<<"}", R/binary>>, [], _, _) -> {{object, []}, R};
object(<<"\"", R/binary>>, Acc, Mode, Depth) ->
    {Key, R1} = string_lit(R, 0, []),
    R2 = case ws(R1) of
             <<":", After/binary>> -> After;
             _ -> bad(expected_colon)
         end,
    {Val, R3} = value(ws(R2), Mode, Depth),
    case ws(R3) of
        <<",", R4/binary>> ->
            case ws(R4) of
                <<"\"", _/binary>> = R5 -> object(R5, [{Key, Val} | Acc], Mode, Depth);
                _ -> bad(expected_member_name)
            end;
        <<"}", R4/binary>> -> {{object, lists:reverse([{Key, Val} | Acc])}, R4};
        _ -> bad(expected_comma_or_brace)
    end;
object(_, _, _, _) -> bad(expected_member_name).

array(<<"]", R/binary>>, [], _, _) -> {{array, []}, R};
array(Bin, Acc, Mode, Depth) ->
    {Val, R1} = value(Bin, Mode, Depth),
    case ws(R1) of
        <<",", R2/binary>> -> array(ws(R2), [Val | Acc], Mode, Depth);
        <<"]", R2/binary>> -> {{array, lists:reverse([Val | Acc])}, R2};
        _ -> bad(expected_comma_or_bracket)
    end.

%% The content of a string after its opening quote -> {Binary, Rest}. N
%% counts the plain bytes read so far, taken as one sub-binary. A raw
%% control character (below U+0020) is refused (ruling 39 of 0.8).
string_lit(Bin, N, Acc) ->
    case Bin of
        <<Run:N/binary, $", R/binary>> ->
            {iolist_to_binary(lists:reverse(run(Run, Acc))), R};
        <<Run:N/binary, $\\, $u, R/binary>> ->
            {Cp, R1} = unicode_escape(R),
            string_lit(R1, 0, [<<Cp/utf8>> | run(Run, Acc)]);
        <<Run:N/binary, $\\, E, R/binary>> ->
            string_lit(R, 0, [unescape(E) | run(Run, Acc)]);
        <<_:N/binary, C, _/binary>> when C < 16#20 -> bad(control_character_in_string);
        <<_:N/binary, $\\>> -> bad(unterminated_escape);
        <<_:N/binary, _, _/binary>> -> string_lit(Bin, N + 1, Acc);
        _ -> bad(unterminated_string)
    end.

run(<<>>, Acc) -> Acc;
run(Run, Acc) -> [Run | Acc].

%% The four hex digits after `\u`, and the low half when they are a high
%% surrogate -> {CodePoint, Rest}. A lone surrogate is refused.
unicode_escape(Bin) ->
    {U, R} = hex4(Bin),
    if U >= 16#D800, U =< 16#DBFF ->
           case R of
               <<"\\u", R1/binary>> ->
                   case hex4(R1) of
                       {Lo, R2} when Lo >= 16#DC00, Lo =< 16#DFFF ->
                           {16#10000 + ((U - 16#D800) bsl 10) + (Lo - 16#DC00), R2};
                       _ -> bad(lone_surrogate)
                   end;
               _ -> bad(lone_surrogate)
           end;
       U >= 16#DC00, U =< 16#DFFF -> bad(lone_surrogate);
       true -> {U, R}
    end.

hex4(<<A, B, C, D, R/binary>>) ->
    {(hexval(A) bsl 12) bor (hexval(B) bsl 8) bor (hexval(C) bsl 4) bor hexval(D), R};
hex4(_) -> bad(unterminated_unicode_escape).

hexval(C) when C >= $0, C =< $9 -> C - $0;
hexval(C) when C >= $a, C =< $f -> C - $a + 10;
hexval(C) when C >= $A, C =< $F -> C - $A + 10;
hexval(_) -> bad(unicode_escape_digit).

unescape($n) -> $\n;
unescape($t) -> $\t;
unescape($r) -> $\r;
unescape($b) -> $\b;
unescape($f) -> $\f;
unescape($/) -> $/;
unescape($") -> $";
unescape($\\) -> $\\;
unescape(_) -> bad(unknown_escape).

%% A number as RFC 8259 writes it: [-] (0 | 1-9 digits) [. digits]
%% [(e|E) [+|-] digits] -> {integer() | {dnum, Text}, Rest}. A leading zero,
%% a leading `+`, a bare `.` and a point or exponent with no digit are
%% refused (ruling 39 of 0.8).
number_lit(Bin) ->
    N0 = case Bin of
             <<$-, _/binary>> -> 1;
             _ -> 0
         end,
    N1 = case Bin of
             <<_:N0/binary, $0, D, _/binary>> when D >= $0, D =< $9 -> bad(leading_zero);
             <<_:N0/binary, $0, _/binary>> -> N0 + 1;
             <<_:N0/binary, D, _/binary>> when D >= $1, D =< $9 -> digits(Bin, N0 + 1);
             _ -> bad(not_a_value)
         end,
    N2 = case Bin of
             <<_:N1/binary, $., D1, _/binary>> when D1 >= $0, D1 =< $9 -> digits(Bin, N1 + 2);
             <<_:N1/binary, $., _/binary>> -> bad(fraction_without_digit);
             _ -> N1
         end,
    N3 = case Bin of
             <<_:N2/binary, E, _/binary>> when E =:= $e; E =:= $E ->
                 S = case Bin of
                         <<_:N2/binary, _, Sign, _/binary>> when Sign =:= $+; Sign =:= $- -> N2 + 2;
                         _ -> N2 + 1
                     end,
                 case Bin of
                     <<_:S/binary, D2, _/binary>> when D2 >= $0, D2 =< $9 -> digits(Bin, S + 1);
                     _ -> bad(exponent_without_digit)
                 end;
             _ -> N2
         end,
    <<Text:N3/binary, Rest/binary>> = Bin,
    %% a number with a fraction or an exponent keeps its text: a transform
    %% reads it exactly (ruling 2d of 0.11), and one whose nearest double is
    %% infinite fails only where it is read
    N = case N3 =:= N1 of
            true when Text =:= <<"-0">> -> {dnum, Text};   % the double -0 through float
            true -> binary_to_integer(Text);
            false -> {dnum, Text}
        end,
    {N, Rest}.

%% The offset of the first byte at or after N that is not a decimal digit.
digits(Bin, N) ->
    case Bin of
        <<_:N/binary, D, _/binary>> when D >= $0, D =< $9 -> digits(Bin, N + 1);
        _ -> N
    end.

ws(<<C, R/binary>>) when C =:= $\s; C =:= $\t; C =:= $\r; C =:= $\n -> ws(R);
ws(Bin) -> Bin.

%% ---- canonical output ----

%% Canonical JSON text of a number (ruling 3 of 0.1.1): an integer as its
%% digits, a number with a fraction or an exponent through its nearest
%% double (raises when that is infinite).
number_text(I) when is_integer(I) -> integer_to_list(I);
number_text(F) when is_float(F) -> gt_num:fmt_float(F);
number_text({dnum, _} = N) ->
    {ok, F} = num_float(N),
    gt_num:fmt_float(F).

%% A parsed number as the nearest double -> {ok, float()} | error (infinite).
num_float(I) when is_integer(I) ->
    try {ok, float(I)} catch error:badarg -> error end;
num_float(F) when is_float(F) -> {ok, F};
num_float({dnum, Text}) -> gt_num:num_text(Text);
num_float(_) -> error.

%% A parsed number as an exact integer within a signed 64-bit integer
%% (ruling 2d of 0.11) -> {ok, integer()} | error.
num_int(I) when is_integer(I), I >= -(1 bsl 63), I < (1 bsl 63) -> {ok, I};
num_int({dnum, Text}) -> gt_num:exact_int(Text);
num_int(_) -> error.

is_num(V) -> is_integer(V) orelse is_float(V) orelse
                 (is_tuple(V) andalso tuple_size(V) =:= 2 andalso element(1, V) =:= dnum).

%% Text that is wholly one JSON number (RFC 8259 grammar)
%% -> {ok, CanonicalText} | out_of_range | not_number.
read_number(Bin) when is_binary(Bin) ->
    try number_lit(Bin) of
        {N, <<>>} ->
            case num_float(N) of
                {ok, F} -> {ok, list_to_binary(gt_num:fmt_float(F))};
                error -> out_of_range
            end;
        _ -> not_number
    catch
        error:{json_malformed, _} -> not_number
    end.

%% The canonical text of a parsed scalar, as a sentinel compares it
%% (Version 0.9): a string as it is, a number through a double, a boolean
%% as `true` or `false` -> binary() | none. A number whose nearest double is
%% infinite has none (ruling 2d of 0.11).
canonical_text(V) when is_binary(V) -> V;
canonical_text(true) -> <<"true">>;
canonical_text(false) -> <<"false">>;
canonical_text(V) ->
    case is_num(V) andalso num_float(V) of
        {ok, F} -> list_to_binary(gt_num:fmt_float(F));
        _ -> none
    end.

%% Is this text canonical JSON number text: a number whose canonical text is
%% the text itself?
is_number_text(Bin) when is_binary(Bin) ->
    try number_lit(Bin) of
        {N, <<>>} -> list_to_binary(number_text(N)) =:= Bin;
        _ -> false
    catch _:_ -> false
    end.

%% String content with `"`, `\` and control characters below U+0020 escaped;
%% everything else is written as it is (UTF-8).
escape(Bin) when is_binary(Bin) ->
    case needs_escape(Bin) of
        false -> Bin;
        true -> << <<(esc(C))/binary>> || <<C>> <= Bin >>
    end.

needs_escape(<<>>) -> false;
needs_escape(<<C, _/binary>>) when C < 16#20; C =:= $"; C =:= $\\ -> true;
needs_escape(<<_, R/binary>>) -> needs_escape(R).

%% Does any object of a parsed value hold the same member name twice?
has_duplicate_member({object, Ms}) ->
    Names = [K || {K, _} <- Ms],
    length(lists:usort(Names)) =/= length(Names)
        orelse lists:any(fun({_, V}) -> has_duplicate_member(V) end, Ms);
has_duplicate_member({array, Vs}) -> lists:any(fun has_duplicate_member/1, Vs);
has_duplicate_member(_) -> false.

esc($") -> <<"\\\"">>;
esc($\\) -> <<"\\\\">>;
esc($\n) -> <<"\\n">>;
esc($\r) -> <<"\\r">>;
esc($\t) -> <<"\\t">>;
esc($\b) -> <<"\\b">>;
esc($\f) -> <<"\\f">>;
esc(C) when C < 16#20 ->
    list_to_binary(io_lib:format("\\u~4.16.0b", [C]));
esc(C) -> <<C>>.

%% Any parsed value -> canonical JSON iodata, no insignificant whitespace.
encode(B) when is_binary(B) -> [$", escape(B), $"];
encode(N) when is_number(N) -> number_text(N);
encode({dnum, _} = N) -> number_text(N);
encode({num, Text}) -> Text;
encode(true) -> "true";
encode(false) -> "false";
encode(null) -> "null";
encode({array, Vs}) -> [$[, join([encode(V) || V <- Vs]), $]];
encode({object, Ms}) ->
    [${, join([[encode(K), $:, encode(V)] || {K, V} <- Ms]), $}].

join([]) -> [];
join([X]) -> [X];
join([X | Xs]) -> [X, $, | join(Xs)].
