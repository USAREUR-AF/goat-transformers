%% gt_bits: hex text and bit-range access for the bits wire.
%%
%% A locator is {Off, Len}: Len bits starting at bit Off of the message.
%% lsb (Version 0.2): bit i of the message is bit (i mod 8) of byte (i div 8);
%%   a field's value has its first bit least significant. Read as one
%%   little-endian integer, bit i of the message is bit i of the integer.
%% msb (Version 0.5): bit i is bit 7 - (i mod 8) of byte (i div 8); a field's
%%   value has its first bit most significant. Read as one big-endian integer
%%   of N bits, bit i of the message is bit N - 1 - i of the integer.
-module(gt_bits).
-export([hex_to_bytes/1, bytes_to_hex/1, open/2, bit_size/1, read/3,
         new/2, write/4, overwrite/4, to_bytes/1]).

-define(WS(C), (C =:= $\s orelse C =:= $\t orelse C =:= $\r orelse C =:= $\n)).

%% hex (whitespace ignored, even length) -> binary. An odd number of digits,
%% or a character that is neither a hex digit nor whitespace (a sign
%% included), raises error:{hex_malformed, Why} (ruling 36 of 0.8).
hex_to_bytes(Bin) when is_binary(Bin) -> hex(Bin, []).

hex(<<>>, Acc) -> list_to_binary(lists:reverse(Acc));
hex(<<C, R/binary>>, Acc) when ?WS(C) -> hex(R, Acc);
hex(<<H, R/binary>>, Acc) -> hex_low(R, hexval(H), Acc).

hex_low(<<C, R/binary>>, Hi, Acc) when ?WS(C) -> hex_low(R, Hi, Acc);
hex_low(<<L, R/binary>>, Hi, Acc) -> hex(R, [(Hi bsl 4) bor hexval(L) | Acc]);
hex_low(<<>>, _Hi, _Acc) -> erlang:error({hex_malformed, odd_number_of_digits}).

hexval(C) when C >= $0, C =< $9 -> C - $0;
hexval(C) when C >= $a, C =< $f -> C - $a + 10;
hexval(C) when C >= $A, C =< $F -> C - $A + 10;
hexval(C) -> erlang:error({hex_malformed, {not_a_hex_digit, C}}).

%% binary -> lowercase hex, no separators
bytes_to_hex(Bin) ->
    << <<(hexdig(B bsr 4)), (hexdig(B band 15))>> || <<B>> <= Bin >>.

hexdig(N) when N < 10 -> $0 + N;
hexdig(N) -> $a + N - 10.

%% ---- reading ----

%% A message opened for reading: {Order, BitSize, Bytes}. A read takes the
%% bytes its range covers, so its cost does not grow with the message.
open(Bin, Order) when Order =:= lsb; Order =:= msb ->
    {Order, erlang:bit_size(Bin), Bin}.

bit_size({_, Size, _}) -> Size.

%% The Len bits from Off as an unsigned integer, or `beyond` when the range
%% runs past the end of the message. Off and Len come from the pack and the
%% cursor, and are checked against the size before any bit is taken.
read({_, Size, _}, Off, Len) when Off < 0; Len < 0; Off + Len > Size -> beyond;
read({msb, _, Bin}, Off, Len) ->
    <<_:Off/bits, V:Len, _/bits>> = Bin,
    V;
read({lsb, _, Bin}, Off, Len) ->
    First = Off div 8,
    Bits = ((Off + Len + 7) div 8 - First) * 8,
    <<_:First/binary, I:Bits/little, _/binary>> = Bin,
    (I bsr (Off rem 8)) band mask(Len).

%% ---- writing ----

%% A zeroed message of Bytes bytes: {Order, BitSize, Value, WrittenMask}.
new(Bytes, Order) -> {Order, Bytes * 8, 0, 0}.

%% Write a field. Bits an earlier field already wrote keep that field's value.
write({Order, Size, Val, Written}, Off, Len, U) ->
    Shift = shift(Order, Size, Off, Len),
    Range = mask(Len) bsl Shift,
    Free = Range band (bnot Written),
    {Order, Size, Val bor (((U band mask(Len)) bsl Shift) band Free), Written bor Range}.

%% Write a `when` value over whatever is there.
overwrite({Order, Size, Val, Written}, Off, Len, U) ->
    Shift = shift(Order, Size, Off, Len),
    Range = mask(Len) bsl Shift,
    {Order, Size, (Val band (bnot Range)) bor ((U band mask(Len)) bsl Shift),
     Written bor Range}.

shift(lsb, _Size, Off, _Len) -> Off;
shift(msb, Size, Off, Len) -> Size - Off - Len.

to_bytes({lsb, Size, Val, _}) -> <<Val:Size/little>>;
to_bytes({msb, Size, Val, _}) -> <<Val:Size/big>>.

mask(L) -> (1 bsl L) - 1.
