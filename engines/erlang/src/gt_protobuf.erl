%% gt_protobuf: protobuf wire reader and canonical writer (Versions 0.3, 0.5).
%%
%% parse/1 -> [{FieldNumber, WireType, Value}] in wire order
%%   wire type 0 -> the varint as an unsigned 64-bit integer
%%   wire type 1 -> 8 bytes, 2 -> the payload bytes, 5 -> 4 bytes
%% A malformed message raises error:{protobuf_malformed, Why}.
%%
%% The writer takes a tree:
%%   #{FieldNumber => Node | {rep, [Node]}},  Node = {leaf, WireType, Bytes} | {msg, Tree}
%% and writes fields in ascending field-number order, each submessage the same
%% way; {rep, Nodes} is one occurrence per node, in order.
-module(gt_protobuf).
-export([parse/1, parse_map/1, parse_msg/1, get/2, get_in/2, serialize/1, varint/1,
         read_varint/1, varints/1]).

%% the largest field number
-define(MAX_FIELD, 16#1FFFFFFF).

parse(Bin) -> parse(Bin, []).

%% One message as a map #{FieldNumber => {WireType, Value}}. When a field
%% number repeats, the last occurrence wins, as a whole.
parse_map(Bin) ->
    lists:foldl(fun({N, WT, V}, M) -> M#{N => {WT, V}} end, #{}, parse(Bin)).

%% One message as {Map, Fields}: the map of parse_map/1 and the fields in
%% wire order, for the occurrences of a repeated field.
parse_msg(Bin) ->
    Fields = parse(Bin),
    {lists:foldl(fun({N, WT, V}, M) -> M#{N => {WT, V}} end, #{}, Fields), Fields}.

%% The varints of a packed payload, back to back.
varints(Bin) -> varints(Bin, []).

varints(<<>>, Acc) -> lists:reverse(Acc);
varints(Bin, Acc) ->
    {V, Rest} = read_varint(Bin),
    varints(Rest, [V | Acc]).

%% Ruling 38 of 0.8: a truncated varint, a varint longer than ten bytes, a
%% length or fixed-width value that runs past the bytes of its message, a
%% wire type other than 0, 1, 2 and 5 (so 3, 4, 6 and 7), field number 0
%% and a field number above 2^29-1 are malformed (rulings 38 and 40). A length is compared with the bytes left before any are taken.
parse(<<>>, Acc) -> lists:reverse(Acc);
parse(Bin, Acc) ->
    {Tag, R} = read_varint(Bin),
    Num = Tag bsr 3,
    if Num =:= 0 -> bad(field_number_zero);
       Num > ?MAX_FIELD -> bad(field_number_too_large);
       true -> ok
    end,
    case Tag band 7 of
        0 ->
            {V, R1} = read_varint(R),
            parse(R1, [{Num, 0, V} | Acc]);
        1 ->
            case R of
                <<B:8/binary, R1/binary>> -> parse(R1, [{Num, 1, B} | Acc]);
                _ -> bad(truncated_fixed64)
            end;
        2 ->
            {Len, R1} = read_varint(R),
            case Len =< byte_size(R1) of
                true ->
                    <<B:Len/binary, R2/binary>> = R1,
                    parse(R2, [{Num, 2, B} | Acc]);
                false -> bad(truncated_length_delimited)
            end;
        5 ->
            case R of
                <<B:4/binary, R1/binary>> -> parse(R1, [{Num, 5, B} | Acc]);
                _ -> bad(truncated_fixed32)
            end;
        WT -> bad({unsupported_wire_type, WT})
    end.

bad(Why) -> erlang:error({protobuf_malformed, Why}).

%% A varint is a 64-bit value of at most ten bytes. The tenth byte holds bit
%% 63 alone: a continuation bit there is a longer varint, and a value above
%% 1 has bits above bit 63 (ruling 40 of 0.8); both are malformed.
read_varint(Bin) -> read_varint(Bin, 0, 0).

read_varint(<<1:1, _:7, _/binary>>, _, 63) -> bad(varint_too_long);
read_varint(<<0:1, B:7, _/binary>>, _, 63) when B > 1 -> bad(varint_above_64_bits);
read_varint(<<1:1, B:7, R/binary>>, Acc, Shift) ->
    read_varint(R, Acc bor (B bsl Shift), Shift + 7);
read_varint(<<0:1, B:7, R/binary>>, Acc, Shift) ->
    {Acc bor (B bsl Shift), R};
read_varint(_, _, _) -> bad(truncated_varint).

%% The field at a path of field numbers -> absent | {ok, WireType, Value}.
%% When a field number repeats, the last occurrence wins, as a whole: a
%% repeated submessage is not merged.
get(Bin, Path) -> get_in(parse(Bin), Path).

get_in(Fields, [N | Rest]) ->
    case last_of(N, Fields, absent) of
        absent -> absent;
        {WT, V} when Rest =:= [] -> {ok, WT, V};
        {2, Sub} -> get_in(parse(Sub), Rest);
        {_, _} -> absent
    end.

last_of(_, [], Found) -> Found;
last_of(N, [{N, WT, V} | T], _) -> last_of(N, T, {WT, V});
last_of(N, [_ | T], Found) -> last_of(N, T, Found).

%% Tree -> canonical bytes.
serialize(Tree) ->
    iolist_to_binary(
      [case maps:get(N, Tree) of
           {rep, Nodes} -> [node(N, Node) || Node <- Nodes];
           Node -> node(N, Node)
       end || N <- lists:sort(maps:keys(Tree))]).

node(N, {leaf, WT, Bytes}) when WT =:= 2 ->
    [varint((N bsl 3) bor 2), varint(byte_size(Bytes)), Bytes];
node(N, {leaf, WT, Bytes}) ->
    [varint((N bsl 3) bor WT), Bytes];
node(N, {msg, Sub}) ->
    Body = serialize(Sub),
    [varint((N bsl 3) bor 2), varint(byte_size(Body)), Body].

%% Unsigned integer -> varint bytes.
varint(N) when N < 128 -> <<N>>;
varint(N) -> <<1:1, (N band 127):7, (varint(N bsr 7))/binary>>.
