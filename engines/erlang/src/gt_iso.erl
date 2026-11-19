%% gt_iso: ISO 8601 <-> epoch milliseconds (engine-spec transform
%% `iso8601_ms`; Version 0.6 replaces ruling 8 of 0.1.1).
-module(gt_iso).
-export([decode/1, encode/1, encode_seconds/1]).

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

%% `iso8601_s` encode (Version 0.12): the text of encode/1 less its ".fff",
%% so the second that holds the instant.
encode_seconds(Ms) ->
    <<Whole:19/binary, _/binary>> = encode(Ms),
    <<Whole/binary, "Z">>.

%% epoch ms -> "YYYY-MM-DDTHH:MM:SS.fffZ"
encode(Ms) when is_integer(Ms), Ms >= ?MIN_MS, Ms =< ?MAX_MS ->
    Milli = ((Ms rem 1000) + 1000) rem 1000,
    Secs = (Ms - Milli) div 1000,
    {{Y, Mo, D}, {H, Mi, S}} =
        calendar:gregorian_seconds_to_datetime(Secs + ?EPOCH_GREGORIAN_SECONDS),
    true = Y >= 0 andalso Y =< 9999,
    iolist_to_binary(
      io_lib:format("~4..0b-~2..0b-~2..0bT~2..0b:~2..0b:~2..0b.~3..0bZ",
                    [Y, Mo, D, H, Mi, S, Milli])).
