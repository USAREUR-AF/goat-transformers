%% gt_json: a small JSON reader and canonical writer. Objects keep member order.
%%   object -> {object, [{KeyBinary, Value}]}
%%   array  -> {array, [Value]}
%%   string -> binary() (UTF-8)
%%   number -> integer() (no fraction, no exponent) | float()
%%   true/false/null -> 'true' | 'false' | 'null'
-module(gt_json).
-export([parse/1, parse_raw/1, get/2, escape/1, encode/1, number_text/1, is_number_text/1,
         has_duplicate_member/1]).

parse(Cs) when is_list(Cs) -> parse(list_to_binary(Cs));
parse(Bin) when is_binary(Bin) -> parse(Bin, num).

%% As parse/1, but a number is {num, Text} with its text as written;
%% encode/1 writes it back as that text.
parse_raw(Bin) when is_binary(Bin) -> parse(Bin, raw).

parse(Bin, Mode) ->
    {V, Rest} = value(ws(Bin), Mode),
    case ws(Rest) of
        <<>> -> V;
        _ -> erlang:error({json_trailing, Rest})
    end.

%% member lookup on an object
get({object, Members}, Key) when is_binary(Key) ->
    case lists:keyfind(Key, 1, Members) of
        {_, V} -> {ok, V};
        false -> absent
    end;
get({object, _} = O, Key) when is_list(Key) -> get(O, list_to_binary(Key));
get(_, _) -> absent.

value(<<"{", R/binary>>, Mode) -> object(ws(R), [], Mode);
value(<<"[", R/binary>>, Mode) -> array(ws(R), [], Mode);
value(<<"\"", R/binary>>, _) -> string_lit(R, []);
value(<<"true", R/binary>>, _) -> {true, R};
value(<<"false", R/binary>>, _) -> {false, R};
value(<<"null", R/binary>>, _) -> {null, R};
value(Bin, num) -> number_lit(Bin);
value(Bin, raw) ->
    {_, Rest} = number_lit(Bin),
    Len = byte_size(Bin) - byte_size(Rest),
    {{num, binary:part(Bin, 0, Len)}, Rest}.

object(<<"}", R/binary>>, [], _) -> {{object, []}, R};
object(<<"\"", R/binary>>, Acc, Mode) ->
    {Key, R1} = string_lit(R, []),
    <<":", R2/binary>> = ws(R1),
    {Val, R3} = value(ws(R2), Mode),
    case ws(R3) of
        <<",", R4/binary>> -> object(ws(R4), [{Key, Val} | Acc], Mode);
        <<"}", R4/binary>> -> {{object, lists:reverse([{Key, Val} | Acc])}, R4}
    end.

array(<<"]", R/binary>>, [], _) -> {{array, []}, R};
array(Bin, Acc, Mode) ->
    {Val, R1} = value(Bin, Mode),
    case ws(R1) of
        <<",", R2/binary>> -> array(ws(R2), [Val | Acc], Mode);
        <<"]", R2/binary>> -> {{array, lists:reverse([Val | Acc])}, R2}
    end.

%% Runs of plain characters are taken as one sub-binary.
string_lit(Bin, Acc) ->
    {Pos, 1} = binary:match(Bin, [<<"\"">>, <<"\\">>]),
    <<Run:Pos/binary, C, R/binary>> = Bin,
    Acc1 = case Pos of
               0 -> Acc;
               _ -> [Run | Acc]
           end,
    case {C, R} of
        {$", _} -> {iolist_to_binary(lists:reverse(Acc1)), R};
        {$\\, <<"u", R1/binary>>} ->
            {Cp, R2} = unicode_escape(R1),
            string_lit(R2, [<<Cp/utf8>> | Acc1]);
        {$\\, <<E, R1/binary>>} -> string_lit(R1, [unescape(E) | Acc1])
    end.

unicode_escape(<<H:4/binary, R/binary>>) ->
    U = binary_to_integer(H, 16),
    if U >= 16#D800, U =< 16#DBFF ->
           <<"\\u", L:4/binary, R1/binary>> = R,
           Lo = binary_to_integer(L, 16),
           true = (Lo >= 16#DC00) andalso (Lo =< 16#DFFF),
           {16#10000 + ((U - 16#D800) bsl 10) + (Lo - 16#DC00), R1};
       U >= 16#DC00, U =< 16#DFFF ->
           erlang:error({json_lone_surrogate, H});
       true ->
           {U, R}
    end.

unescape($n) -> $\n;
unescape($t) -> $\t;
unescape($r) -> $\r;
unescape($b) -> $\b;
unescape($f) -> $\f;
unescape($/) -> $/;
unescape($") -> $";
unescape($\\) -> $\\.

number_lit(Bin) ->
    case re:run(Bin, "^-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][-+]?[0-9]+)?",
                [{capture, [0, 2, 3], index}]) of
        {match, [{0, Len}, Frac, Exp]} when Len > 0 ->
            <<Text:Len/binary, Rest/binary>> = Bin,
            N = case {Frac, Exp} of
                    {{-1, _}, {-1, _}} -> binary_to_integer(Text);
                    _ -> gt_num:dec_to_float(Text)
                end,
            {N, Rest};
        _ -> erlang:error({json_value, Bin})
    end.

ws(<<C, R/binary>>) when C =:= $\s; C =:= $\t; C =:= $\r; C =:= $\n -> ws(R);
ws(Bin) -> Bin.

%% ---- canonical output ----

%% Canonical JSON text of a number (ruling 3 of 0.1.1).
number_text(I) when is_integer(I) -> integer_to_list(I);
number_text(F) when is_float(F) -> gt_num:fmt_float(F).

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
