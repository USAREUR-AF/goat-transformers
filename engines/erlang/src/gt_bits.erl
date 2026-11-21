%% gt_bits: bit-range access and six-bit armor for the bits wire (hex text
%% is gt_hex).
%%
%% A locator is {Off, Len}: Len bits starting at bit Off of the message.
%% lsb (Version 0.2): bit i of the message is bit (i mod 8) of byte (i div 8);
%%   a field's value has its first bit least significant. Read as one
%%   little-endian integer, bit i of the message is bit i of the integer.
%% msb (Version 0.5): bit i is bit 7 - (i mod 8) of byte (i div 8); a field's
%%   value has its first bit most significant. Read as one big-endian integer
%%   of N bits, bit i of the message is bit N - 1 - i of the integer.
-module(gt_bits).
-export([open/2, bit_size/1, read/3,
         new/2, new_bits/2, write/4, overwrite/4, to_bytes/1,
         unarmor/1, armor/2, peek/3, written_any/3, write_within/5]).

%% Six-bit armored text (Version 0.14) -> the bitstring of 6 * N bits it
%% stands for, first character first, each most significant bit first.
%% Every character is checked: one outside `0`..`W` and `` ` ``..`w` raises
%% error:{armor_malformed, {position, Index, Byte}}.
unarmor(Bin) when is_binary(Bin) -> unarmor(Bin, 0, <<>>).

unarmor(<<>>, _I, Acc) -> Acc;
unarmor(<<C, R/binary>>, I, Acc) when C >= 16#30, C =< 16#57 ->
    unarmor(R, I + 1, <<Acc/bits, (C - 16#30):6>>);
unarmor(<<C, R/binary>>, I, Acc) when C >= 16#60, C =< 16#77 ->
    unarmor(R, I + 1, <<Acc/bits, (C - 16#38):6>>);
unarmor(<<C, _/binary>>, I, _Acc) ->
    erlang:error({armor_malformed, {position, I, C}}).

%% The first L bits of a bitstring, then zero bits to a multiple of 6, as
%% armored text: values 0 to 39 as 0x30 + v, 40 to 63 as 0x38 + v.
armor(Bits, L) ->
    Fill = (6 - L rem 6) rem 6,
    <<Head:L/bits, _/bits>> = Bits,
    << <<(armor_char(V))>> || <<V:6>> <= <<Head/bits, 0:Fill>> >>.

armor_char(V) when V < 40 -> 16#30 + V;
armor_char(V) -> 16#38 + V.

%% ---- reading ----

%% A message opened for reading: {Order, BitSize, Bytes}. A read takes the
%% bytes its range covers, so its cost does not grow with the message.
open(Bin, Order) when Order =:= lsb; Order =:= msb; Order =:= msblsb ->
    {Order, erlang:bit_size(Bin), Bin}.

bit_size({_, Size, _}) -> Size.

%% The Len bits from Off as an unsigned integer, or `beyond` when the range
%% runs past the end of the message. Off and Len come from the pack and the
%% cursor, and are checked against the size before any bit is taken.
read({_, Size, _}, Off, Len) when Off < 0; Len < 0; Off + Len > Size -> beyond;
read({msb, _, Bin}, Off, Len) ->
    <<_:Off/bits, V:Len, _/bits>> = Bin,
    V;
%% msb-lsb (Version 0.22): positions as msb, the value with its first bit
%% least significant, as lsb
read({msblsb, _, Bin}, Off, Len) ->
    <<_:Off/bits, V:Len, _/bits>> = Bin,
    rev(V, Len);
read({lsb, _, Bin}, Off, Len) ->
    First = Off div 8,
    Bits = ((Off + Len + 7) div 8 - First) * 8,
    <<_:First/binary, I:Bits/little, _/binary>> = Bin,
    (I bsr (Off rem 8)) band mask(Len).

%% ---- writing ----

%% A zeroed message of Bytes bytes: {Order, BitSize, Value, WrittenMask}.
new(Bytes, Order) -> {Order, Bytes * 8, 0, 0}.

%% A zeroed message of Bits bits (msb; to_bytes gives a bitstring).
new_bits(Bits, Order) -> {Order, Bits, 0, 0}.

%% Write a field. Bits an earlier field already wrote keep that field's value.
%% msb-lsb writes as msb, with the value's bits in reverse order
write({msblsb, _, _, _} = M, Off, Len, U) -> as_msblsb(write(as_msb(M), Off, Len, rev(U, Len)));
write({Order, Size, Val, Written}, Off, Len, U) ->
    Shift = shift(Order, Size, Off, Len),
    Range = mask(Len) bsl Shift,
    Free = Range band (bnot Written),
    {Order, Size, Val bor (((U band mask(Len)) bsl Shift) band Free), Written bor Range}.

%% Write a field only on the bits another message of the same size has
%% written, and that this one has not.
write_within({msblsb, _, _, _} = M, Off, Len, U, A) ->
    as_msblsb(write_within(as_msb(M), Off, Len, rev(U, Len), as_msb(A)));
write_within({Order, Size, Val, Written}, Off, Len, U, {_, _, _, Allowed}) ->
    Shift = shift(Order, Size, Off, Len),
    Range = mask(Len) bsl Shift,
    Free = Range band (bnot Written) band Allowed,
    {Order, Size, Val bor (((U band mask(Len)) bsl Shift) band Free), Written bor Free}.

%% Write a `when` value over whatever is there.
overwrite({msblsb, _, _, _} = M, Off, Len, U) -> as_msblsb(overwrite(as_msb(M), Off, Len, rev(U, Len)));
overwrite({Order, Size, Val, Written}, Off, Len, U) ->
    Shift = shift(Order, Size, Off, Len),
    Range = mask(Len) bsl Shift,
    {Order, Size, (Val band (bnot Range)) bor ((U band mask(Len)) bsl Shift),
     Written bor Range}.

%% The Len bits from Off of a message being written, or `beyond` when the
%% range runs past its end. Bits nothing wrote read as 0.
peek({_, Size, _, _}, Off, Len) when Off + Len > Size -> beyond;
peek({msblsb, _, _, _} = M, Off, Len) ->
    case peek(as_msb(M), Off, Len) of
        beyond -> beyond;
        V -> rev(V, Len)
    end;
peek({Order, Size, Val, _}, Off, Len) ->
    (Val bsr shift(Order, Size, Off, Len)) band mask(Len).

%% Has a write covered any of the Len bits from Off?
written_any({Order, Size, _, Written}, Off, Len) ->
    (Written band (mask(Len) bsl shift(Order, Size, Off, Len))) =/= 0.

shift(msblsb, Size, Off, Len) -> Size - Off - Len;
shift(lsb, _Size, Off, _Len) -> Off;
shift(msb, Size, Off, Len) -> Size - Off - Len.

to_bytes({lsb, Size, Val, _}) -> <<Val:Size/little>>;
to_bytes({_, Size, Val, _}) -> <<Val:Size/big>>.      % msb, msb-lsb

as_msb({_, Size, Val, Written}) -> {msb, Size, Val, Written}.
as_msblsb({msb, Size, Val, Written}) -> {msblsb, Size, Val, Written}.

%% The Len bits of V in reverse order.
rev(V, Len) ->
    Bits = list_to_bitstring(lists:reverse([<<B:1>> || <<B:1>> <= <<V:Len>>])),
    <<R:Len>> = Bits,
    R.

mask(L) -> (1 bsl L) - 1.
