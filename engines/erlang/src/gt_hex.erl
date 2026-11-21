%% gt_hex: hex text, which the bits, protobuf and tlv wires read and write
%% (lowercase on output, whitespace ignored on input).
-module(gt_hex).
-export([hex_to_bytes/1, bytes_to_hex/1]).

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
