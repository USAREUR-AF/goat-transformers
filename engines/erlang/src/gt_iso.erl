%% gt_iso: ISO 8601 <-> epoch milliseconds (engine-spec transform
%% `iso8601_ms`; Version 0.6 replaces ruling 8 of 0.1.1).
-module(gt_iso).
-export([decode/1, encode/1, encode_short/1, encode_seconds/1]).

-define(EPOCH_GREGORIAN_SECONDS, 62167219200).
%% 0001-01-01T00:00:00.000Z and 9999-12-31T23:59:59.999Z (ruling 3 of 0.11)
-define(MIN_MS, -62135596800000).
-define(MAX_MS, 253402300799999).

%% "YYYY-MM-DDTHH:MM:SS[.f...]<designator>" -> integer epoch ms. The
%% designator is `Z`, `z`, `+hh:mm` or `-hh:mm`; the `T` may be lowercase; the
%% instant is converted to UTC. Fraction digits beyond milliseconds are
%% truncated, not rounded.
decode(S) when is_list(S) -> decode(list_to_binary(S));
decode(<<Y:4/binary, $-, Mo:2/binary, $-, D:2/binary, T,
         H:2/binary, $:, Mi:2/binary, $:, Sec:2/binary, Rest/binary>> = Bin)
  when T =:= $T; T =:= $t ->
    Date = {Yy, _, _} = {int(Y), int(Mo), int(D)},
    Time = {Hh, Mm, Ss} = {int(H), int(Mi), int(Sec)},
    %% ruling 3b of 0.11: year 0001 to 9999, the proleptic Gregorian calendar,
    %% no leap second and no 24:00:00
    Valid = Yy >= 1 andalso calendar:valid_date(Date)
        andalso Hh =< 23 andalso Mm =< 59 andalso Ss =< 59,
    {Ms, Rest1} = fraction(Rest),
    OffsetSecs = designator(Rest1),
    case Valid of
        true ->
            Secs = calendar:datetime_to_gregorian_seconds({Date, Time})
                - ?EPOCH_GREGORIAN_SECONDS - OffsetSecs,
            Value = Secs * 1000 + Ms,
            %% 3d: the instant lies from year 0001 to the end of year 9999
            case Value >= ?MIN_MS andalso Value =< ?MAX_MS of
                true -> Value;
                false -> erlang:error({iso8601_decode, Bin})
            end;
        false -> erlang:error({iso8601_decode, Bin})
    end;
decode(Other) -> erlang:error({iso8601_decode, Other}).

%% `.` and one or more digits; the first three are the milliseconds, the
%% rest dropped (3c)
fraction(<<$., Rest/binary>>) ->
    N = digits(Rest, 0),
    true = N >= 1,
    <<Frac:N/binary, Rest1/binary>> = Rest,
    D3 = case Frac of
             <<F:3/binary, _/binary>> -> F;
             _ -> <<Frac/binary, (binary:copy(<<"0">>, 3 - N))/binary>>
         end,
    {binary_to_integer(D3), Rest1};
fraction(Rest) -> {0, Rest}.

digits(Bin, N) ->
    case Bin of
        <<_:N/binary, C, _/binary>> when C >= $0, C =< $9 -> digits(Bin, N + 1);
        _ -> N
    end.

designator(<<"Z">>) -> 0;
designator(<<"z">>) -> 0;
designator(<<Sign, H:2/binary, $:, M:2/binary>>) when Sign =:= $+; Sign =:= $- ->
    Hh = int(H),
    Mm = int(M),
    true = Hh =< 23 andalso Mm =< 59,
    Secs = Hh * 3600 + Mm * 60,
    case Sign of
        $+ -> Secs;
        $- -> -Secs
    end.

%% two or four ASCII digits, nothing else
int(B) ->
    true = digits(B, 0) =:= byte_size(B),
    binary_to_integer(B).

%% epoch ms -> "YYYY-MM-DDTHH:MM:SS.fffZ"
encode(Ms) when is_integer(Ms), Ms >= ?MIN_MS, Ms =< ?MAX_MS -> format(Ms).

%% epoch ms -> "YYYY-MM-DDTHH:MM:SSZ" (`iso8601_s`, Version 0.26, ruling 3):
%% the text encode/1 writes less its ".fff", so the second that holds the
%% instant (the milliseconds dropped, never rounded), in the range of encode/1.
encode_seconds(Ms) ->
    <<Whole:19/binary, $., _:3/binary, "Z">> = encode(Ms),
    <<Whole/binary, "Z">>.

%% 0000-01-01T00:00:00Z, the first instant `iso8601_short` writes (ruling
%% 11 of 0.18; iso8601_ms keeps 0001 of ruling 3 of 0.11)
-define(MIN_SHORT_MS, -62167219200000).

format(Ms) ->
    Milli = ((Ms rem 1000) + 1000) rem 1000,
    Secs = (Ms - Milli) div 1000,
    {{Y, Mo, D}, {H, Mi, S}} =
        calendar:gregorian_seconds_to_datetime(Secs + ?EPOCH_GREGORIAN_SECONDS),
    true = Y >= 0 andalso Y =< 9999,
    iolist_to_binary(
      io_lib:format("~4..0b-~2..0b-~2..0bT~2..0b:~2..0b:~2..0b.~3..0bZ",
                    [Y, Mo, D, H, Mi, S, Milli])).

%% epoch ms -> "YYYY-MM-DDTHH:MM:SS[.f]Z" (`iso8601_short`, 0.18): no
%% fraction when the milliseconds are 0, else their three digits with
%% trailing zeros removed. The milliseconds are ms - 1000 * floor(ms / 1000)
%% (ruling 11); a year outside 0000 - 9999 fails.
encode_short(Ms) when is_integer(Ms), Ms >= ?MIN_SHORT_MS, Ms =< ?MAX_MS ->
    <<Head:19/binary, $., Frac:3/binary, "Z">> = format(Ms),
    case strip_zeros(Frac) of
        <<>> -> <<Head/binary, "Z">>;
        F -> <<Head/binary, $., F/binary, "Z">>
    end.

strip_zeros(<<>>) -> <<>>;
strip_zeros(B) ->
    case binary:last(B) of
        $0 -> strip_zeros(binary:part(B, 0, byte_size(B) - 1));
        _ -> B
    end.
