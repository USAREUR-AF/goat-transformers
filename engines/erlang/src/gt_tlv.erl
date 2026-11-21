%% gt_tlv: the `tlv` wire (engine-spec Version 0.13). Clean-room from spec/
%% and packs/ only.
%%
%% A message is a set of items, each a tag, a length and a value; a value may
%% itself be a set. The pack gives the encodings (tag_enc ber_oid | 1 | 2 | 4,
%% len_enc ber | 1 | 2 | 4), an optional key before the set's length and an
%% optional sum16 checksum item at the end of the top set.
%%
%% A read set is a list of {Tag, Value} in input order. A path is a list of
%% tags; [] is the top set. Residue is [{Path, HexText}], every occurrence of
%% an unnamed tag, in input order within its set.
-module(gt_tlv).
-export([decode/2, encode/4]).

%% ===================================================================
%% decode
%% ===================================================================
decode(Pack, Text) ->
    Bytes = gt_engine:unhex(Pack, Text),
    Top = top_set(Pack, Bytes),
    {Kind, Lines} = select(Pack, Top),
    Sets = walk(Pack, Top, Lines),
    Model = fields(Pack, Sets, Lines),
    #{model => Model,
      lists => #{},
      residue => residue(Sets, Lines),
      src => maps:get(name, Pack),
      kind => case Kind of
                  undefined -> undefined;
                  _ -> {maps:get(name, Pack), Kind}
              end}.

malformed(Pack, Fmt, Args) ->
    gt_engine:conv_error('malformed-wire', Pack, Fmt, Args).

%% Steps 2 to 4 of "Reading a message": the key and the set's length, the
%% top set read whole, the checksum item checked and removed.
top_set(#{key := Key, sum16 := Sum} = Pack, Bytes) ->
    {SetStart, SetBin} =
        case Key of
            none -> {0, Bytes};
            _ ->
                KS = byte_size(Key),
                case Bytes of
                    <<Key:KS/binary, Rest/binary>> ->
                        case length_of(Pack, Rest) of
                            {ok, Len, After} when Len =< byte_size(After) ->
                                Start = byte_size(Bytes) - byte_size(After),
                                {Start, binary:part(After, 0, Len)};
                            {ok, Len, After} ->
                                malformed(Pack, "the set states ~p bytes and ~p follow",
                                          [Len, byte_size(After)]);
                            {error, Why} -> malformed(Pack, "the length of the set: ~s", [Why])
                        end;
                    _ -> malformed(Pack, "the input does not begin with the key", [])
                end
        end,
    Items = case items(Pack, SetBin, SetStart, []) of
                {ok, Is} -> Is;
                {error, Why2} -> malformed(Pack, "the top set: ~s", [Why2])
            end,
    case Sum of
        none -> [{T, V} || {T, _, V} <- Items];
        {sum16, CT} ->
            case lists:reverse(Items) of
                [{CT, At, <<Want:16>>} | RevRest] ->
                    case [T || {T, _, _} <- RevRest, T =:= CT] of
                        [] -> ok;
                        _ -> malformed(Pack, "an item of the checksum tag ~p before the last", [CT])
                    end,
                    Got = sum16(binary:part(Bytes, 0, At), 0, 0),
                    case Got =:= Want of
                        true -> [{T, V} || {T, _, V} <- lists:reverse(RevRest)];
                        false -> malformed(Pack, "checksum ~4.16.0b where the bytes sum to ~4.16.0b",
                                           [Want, Got])
                    end;
                _ -> malformed(Pack, "the last item is not a checksum item of tag ~p with two bytes", [CT])
            end
    end.

%% Every byte at an even offset counts b * 256, at an odd offset b; modulo
%% 65536.
sum16(<<A, B, R/binary>>, _, S) -> sum16(R, 0, (S + A * 256 + B) band 16#FFFF);
sum16(<<A>>, _, S) -> (S + A * 256) band 16#FFFF;
sum16(<<>>, _, S) -> S.

%% The items of a set to its last byte -> {ok, [{Tag, ValueOffset, Value}]} |
%% {error, Why}. Base is the offset of the set in the input. Every length is
%% compared with the bytes left, never added to an offset first.
items(_Pack, <<>>, _Base, Acc) -> {ok, lists:reverse(Acc)};
items(Pack, Bin, Base, Acc) ->
    case tag_of(Pack, Bin) of
        {error, _} = E -> E;
        {ok, Tag, R1} ->
            case length_of(Pack, R1) of
                {error, _} = E -> E;
                {ok, Len, R2} when Len =< byte_size(R2) ->
                    At = Base + byte_size(Bin) - byte_size(R2),
                    <<V:Len/binary, R3/binary>> = R2,
                    items(Pack, R3, At + Len, [{Tag, At, V} | Acc]);
                {ok, Len, R2} ->
                    {error, io_lib:format("item ~p states ~p bytes and ~p are left",
                                          [Tag, Len, byte_size(R2)])}
            end
    end.

%% A set's items without offsets -> {ok, [{Tag, Value}]} | {error, Why}.
read_set(Pack, Bin) ->
    case items(Pack, Bin, 0, []) of
        {ok, Is} -> {ok, [{T, V} || {T, _, V} <- Is]};
        E -> E
    end.

tag_of(#{tag_enc := ber_oid}, Bin) -> oid(Bin, 0, 0);
tag_of(#{tag_enc := N}, Bin) ->
    case Bin of
        <<T:N/unit:8, R/binary>> -> {ok, T, R};
        _ -> {error, "a tag runs past its set"}
    end.

%% Base 128, most significant group first, at most four bytes; a first byte
%% of 0x80 is refused.
oid(<<16#80, _/binary>>, 0, _) -> {error, "a tag begins with 0x80"};
oid(_, 4, _) -> {error, "a tag of more than four bytes"};
oid(<<B, R/binary>>, N, Acc) when B >= 16#80 -> oid(R, N + 1, (Acc bsl 7) bor (B band 16#7F));
oid(<<B, R/binary>>, _N, Acc) -> {ok, (Acc bsl 7) bor B, R};
oid(<<>>, _, _) -> {error, "a tag runs past its set"}.

length_of(#{len_enc := ber}, Bin) ->
    case Bin of
        <<L, R/binary>> when L < 16#80 -> {ok, L, R};
        <<L, R/binary>> when L >= 16#81, L =< 16#88 ->
            N = L - 16#80,
            case R of
                <<V:N/unit:8, R2/binary>> -> {ok, V, R2};
                _ -> {error, "a length runs past its set"}
            end;
        <<L, _/binary>> -> {error, io_lib:format("a length begins with 0x~2.16.0b", [L])};
        <<>> -> {error, "a length runs past its set"}
    end;
length_of(#{len_enc := N}, Bin) ->
    case Bin of
        <<V:N/unit:8, R/binary>> -> {ok, V, R};
        _ -> {error, "a length runs past its set"}
    end.

%% ---- kinds: selected on the top set, before any nested set is read ----
select(#{has_kinds := false, common := Common}, _Top) -> {undefined, Common};
select(#{common := Common, kinds := Kinds} = Pack, Top) ->
    Holds = fun(Ls) ->
                    lists:all(fun({wh, {Path, _}, Val, _}) -> when_holds(Pack, Top, Path, Val);
                                 (_) -> true
                              end, Ls)
            end,
    case Holds(Common) of
        true -> ok;
        false -> gt_engine:conv_error('no-kind', Pack, "a common when does not hold", [])
    end,
    case [K || #{lines := Ls} = K <- Kinds, Holds(Ls)] of
        [] -> gt_engine:conv_error('no-kind', Pack, "no kind's when lines hold for this message", []);
        [#{name := Name, lines := Ls} | _] -> {Name, Common ++ Ls}
    end.

%% A `when` whose item lies in a value that is not a well-formed set does not
%% hold.
when_holds(_Pack, Set, [Tag], Val) ->
    case {lists:keyfind(Tag, 1, Set), Val} of
        {false, _} -> false;
        {_, present} -> true;
        {{_, V}, {uint, Want}} -> byte_size(V) >= 1 andalso byte_size(V) =< 8
                                      andalso binary:decode_unsigned(V) =:= Want
    end;
when_holds(Pack, Set, [Tag | Rest], Val) ->
    case lists:keyfind(Tag, 1, Set) of
        false -> false;
        {_, V} ->
            case read_set(Pack, V) of
                {ok, Sub} -> when_holds(Pack, Sub, Rest, Val);
                {error, _} -> false
            end
    end.

%% ---- the sets the selected lines walk into ----
%% -> #{Path => [{Tag, Value}]}: the top set at [], and each nested set on
%% the path of a line that is in the message. A walked value that is not a
%% well-formed set is malformed-wire.
walk(Pack, Top, Lines) ->
    Prefixes = lists:usort(fun(A, B) -> {length(A), A} =< {length(B), B} end,
                           [Pre || L <- Lines, Pre <- proper_prefixes(line_path(L))]),
    lists:foldl(
      fun(Pre, Sets) ->
              Parent = lists:droplast(Pre),
              Tag = lists:last(Pre),
              case maps:find(Parent, Sets) of
                  error -> Sets;
                  {ok, Items} ->
                      case lists:keyfind(Tag, 1, Items) of
                          false -> Sets;
                          {_, V} ->
                              case read_set(Pack, V) of
                                  {ok, Sub} -> Sets#{Pre => Sub};
                                  {error, Why} ->
                                      malformed(Pack, "the set at ~s: ~s", [path_text(Pre), Why])
                              end
                      end
              end
      end, #{[] => Top}, Prefixes).

line_path({field, _, {Path, _}, _, _, _}) -> Path;
line_path({wh, {Path, _}, _, _}) -> Path;
line_path({const, {Path, _}, _, _}) -> Path.

%% The non-empty proper prefixes of a path, shortest first.
proper_prefixes(Path) -> [lists:sublist(Path, N) || N <- lists:seq(1, length(Path) - 1)].

path_text(Path) -> lists:join(".", [integer_to_list(T) || T <- Path]).

%% The first occurrence of the item at a path -> {ok, Value} | absent.
item_at(Sets, Path) ->
    case maps:find(lists:droplast(Path), Sets) of
        error -> absent;
        {ok, Items} ->
            case lists:keyfind(lists:last(Path), 1, Items) of
                false -> absent;
                {_, V} -> {ok, V}
            end
    end.

%% ---- fields ----
%% A key mapped by several lines takes its value from the earliest line
%% whose item is present and whose transform succeeds; a failing line is an
%% error only when no line of its key succeeds.
fields(Pack, Sets, Lines) ->
    {Model, Failed} =
        lists:foldl(
          fun({field, Key, {Path, _}, Tr, LocT, Opts}, {M, F} = Acc) ->
                  case maps:is_key(Key, M) of
                      true -> Acc;
                      false ->
                          case value_of(item_at(Sets, Path), Tr) of
                              absent -> Acc;
                              {ok, Raw} ->
                                  try decode_value(Tr, Raw) of
                                      V0 ->
                                          V1 = gt_engine:via_decode(Opts, V0, Tr, Key, LocT, Pack),
                                          {M#{Key => gt_engine:typemap_decode(Key, V1, Pack)}, F}
                                  catch
                                      _:_ -> {M, [{Key, LocT} | F]}
                                  end
                          end
                  end;
             (_, Acc) -> Acc
          end, {#{}, []}, Lines),
    case [KL || {K, _} = KL <- lists:reverse(Failed), not maps:is_key(K, Model)] of
        [] -> Model;
        Bad ->
            gt_engine:conv_error('transform-decode', Pack, "failed fields: ~s",
                                 [lists:join(", ", [[K, " at ", L] || {K, L} <- Bad])])
    end.

%% An empty value is absent, except under utf8 and hex (ruling 1 of 0.13).
value_of({ok, <<>>}, Tr) when Tr =/= utf8, Tr =/= hex -> absent;
value_of(Found, _Tr) -> Found.

%% Integers are read at their own length, 1 to 8 bytes.
decode_value(utf8, B) ->
    B = unicode:characters_to_binary(B, utf8, utf8);
decode_value(hex, B) -> gt_hex:bytes_to_hex(B);
decode_value(f32, <<_:32>> = B) -> <<F:32/float>> = B, float(F);
decode_value(f64, <<_:64>> = B) -> <<F:64/float>> = B, F;
decode_value(Tr, B) when byte_size(B) >= 1, byte_size(B) =< 8 ->
    L = 8 * byte_size(B),
    U = binary:decode_unsigned(B),
    case Tr of
        uint -> gt_engine:bits_decode(uint, U, L, msb);           % 8 bytes: ruling 2 of 0.5
        twos -> gt_engine:bits_decode(twos, U, L, msb);
        {uscale, _, _} -> gt_engine:bits_decode(Tr, U, L, msb);   % unsigned (ruling 4)
        {sscale, _, _} -> gt_engine:bits_decode(Tr, U, L, msb)
    end.

%% ---- residue ----
%% Every item of a walked set whose tag no selected line names at that
%% place, every occurrence; later occurrences of a named tag are dropped.
%% `when … present` names the sets on its path, not its last tag.
residue(Sets, Lines) ->
    Named = lists:foldl(
              fun(L, Acc) ->
                      Path = line_path(L),
                      Walked = proper_prefixes(Path),
                      Own = case L of
                                {wh, _, present, _} -> [];
                                _ -> [Path]
                            end,
                      lists:foldl(fun(P, A) -> A#{P => true} end, Acc, Walked ++ Own)
              end, #{}, Lines),
    Order = lists:sort(fun(A, B) -> {length(A), A} =< {length(B), B} end, maps:keys(Sets)),
    [{Path, gt_hex:bytes_to_hex(V)}
     || Q <- Order, {T, V} <- maps:get(Q, Sets),
        Path <- [Q ++ [T]], not maps:is_key(Path, Named)].

%% ===================================================================
%% encode
%% ===================================================================
%% Lines: the selected scope; Src = {Value, Lists, Held}; Residue: [{Path, Hex}]
%% when the entity was decoded from this format.
encode(Pack, Lines, Src, Residue) ->
    %% the children of each set, in order of the first line naming them
    Kids = lists:foldl(
             fun(L, Acc) ->
                     Path = line_path(L),
                     lists:foldl(
                       fun(N, A) ->
                               Parent = lists:sublist(Path, N - 1),
                               Tag = lists:nth(N, Path),
                               Ks = maps:get(Parent, A, []),
                               case lists:member(Tag, Ks) of
                                   true -> A;
                                   false -> A#{Parent => Ks ++ [Tag]}
                               end
                       end, Acc, lists:seq(1, length(Path)))
             end, #{}, Lines),
    ByPath = lists:foldl(fun(L, A) ->
                                 P = line_path(L),
                                 A#{P => maps:get(P, A, []) ++ [L]}
                         end, #{}, Lines),
    ResPaths = maps:from_list([{P, true} || {P, _} <- Residue]),
    Env = #{pack => Pack, kids => Kids, lines => ByPath, src => Src,
            residue => Residue, res_paths => ResPaths},
    gt_hex:bytes_to_hex(top(Pack, set_items(Env, []))).

%% The key, the length of the set and the set; with a checksum, its item
%% last, its value the sum of the output to its length.
top(#{key := Key, sum16 := Sum} = Pack, Items) ->
    Set0 = iolist_to_binary(Items),
    case Sum of
        none ->
            iolist_to_binary([key_part(Pack, Key, byte_size(Set0)), Set0]);
        {sum16, CT} ->
            Head = iolist_to_binary([tag_bytes(Pack, CT), len_bytes(Pack, 2)]),
            SetLen = byte_size(Set0) + byte_size(Head) + 2,
            Before = iolist_to_binary([key_part(Pack, Key, SetLen), Set0, Head]),
            S = sum16(Before, 0, 0),
            <<Before/binary, S:16>>
    end.

key_part(_Pack, none, _Len) -> [];
key_part(Pack, Key, Len) -> [Key, len_bytes(Pack, Len)].

%% The items of the set at a path: the lines' items in line order (a nested
%% set at its first line), then the residue of the set in input order.
set_items(#{kids := Kids, lines := ByPath} = Env, Q) ->
    Mapped = [Item || T <- maps:get(Q, Kids, []),
                      Item <- child(Env, Q ++ [T], maps:is_key(Q ++ [T], ByPath))],
    Mapped ++ residue_items(Env, Q).

child(#{pack := Pack} = Env, Path, true) ->
    case leaf(Env, Path) of
        none -> [];
        Bytes -> [item(Pack, lists:last(Path), Bytes)]
    end;
child(#{pack := Pack} = Env, Path, false) ->
    case iolist_to_binary(set_items(Env, Path)) of
        <<>> -> [];                         % a nested set with no items
        Bin -> [item(Pack, lists:last(Path), Bin)]
    end.

%% The value of the item at a path its lines name -> binary() | none. A
%% `when` or `const` value first, then the earliest field whose key has a
%% value, then an empty item for `when … present` unless residue of the set
%% holds the item.
leaf(#{pack := Pack, lines := ByPath, src := Src, res_paths := ResPaths}, Path) ->
    Ls = maps:get(Path, ByPath),
    case [{V, N} || L <- Ls, {W, {_, N}, {uint, V}, _} <- [L], W =:= wh orelse W =:= const] of
        [{V, N} | _] -> <<V:(8 * N)>>;
        [] ->
            Fields = [{K, Tr, LocT, Opts, Val, Size}
                      || {field, K, {_, Size}, Tr, LocT, Opts} <- Ls,
                         %% a line suppressed by `with` has no value (0.18)
                         {ok, Val} <- [gt_engine:line_value(Src, K, Opts)]],
            case Fields of
                [{K, Tr, LocT, Opts, Val, Size} | _] ->
                    gt_engine:guard_encode(
                      Pack, K, LocT,
                      fun() -> encode_value(Tr, gt_engine:wire_value(Pack, K, Tr, Opts, Val), Size) end);
                [] ->
                    Present = lists:any(fun({wh, _, present, _}) -> true; (_) -> false end, Ls),
                    case Present andalso not maps:is_key(Path, ResPaths) of
                        true -> <<>>;
                        false -> none
                    end
            end
    end.

%% Residue whose set is Q: an entry of the set itself is an item; an entry
%% deeper in a set no line names makes that set at its first entry.
residue_items(#{pack := Pack, residue := Residue, kids := Kids} = Env, Q) ->
    QL = length(Q),
    Named = maps:get(Q, Kids, []),
    {Items, _} =
        lists:foldl(
          fun({Path, Hex}, {Acc, Done}) when length(Path) > QL ->
                  case lists:split(QL, Path) of
                      {Q, [T]} -> {[item(Pack, T, unhex(Hex)) | Acc], Done};
                      {Q, [T | _]} ->
                          case lists:member(T, Named) orelse maps:is_key(T, Done) of
                              true -> {Acc, Done};
                              false ->
                                  Sub = iolist_to_binary(residue_items(Env, Q ++ [T])),
                                  {[item(Pack, T, Sub) | Acc], Done#{T => true}}
                          end;
                      _ -> {Acc, Done}
                  end;
             (_, Acc) -> Acc
          end, {[], #{}}, Residue),
    lists:reverse(Items).

unhex(Hex) -> gt_hex:hex_to_bytes(Hex).

item(Pack, Tag, Value) ->
    [tag_bytes(Pack, Tag), len_bytes(Pack, byte_size(Value)), Value].

tag_bytes(#{tag_enc := ber_oid}, Tag) -> oid_bytes(Tag);
tag_bytes(#{tag_enc := N} = Pack, Tag) ->
    case Tag < 1 bsl (8 * N) of
        true -> <<Tag:N/unit:8>>;
        false -> gt_engine:conv_error('transform-encode', Pack, "tag ~p does not fit ~p bytes", [Tag, N])
    end.

oid_bytes(Tag) when Tag < 128 -> <<Tag>>;
oid_bytes(Tag) -> oid_bytes(Tag bsr 7, [Tag band 16#7F]).

oid_bytes(0, Acc) -> list_to_binary(Acc);
oid_bytes(T, Acc) -> oid_bytes(T bsr 7, [16#80 bor (T band 16#7F) | Acc]).

%% BER: the short form below 128, else the long form with the fewest bytes.
len_bytes(#{len_enc := ber}, Len) when Len < 128 -> <<Len>>;
len_bytes(#{len_enc := ber} = Pack, Len) ->
    B = binary:encode_unsigned(Len),
    case byte_size(B) =< 8 of
        true -> <<(16#80 + byte_size(B)), B/binary>>;
        false -> gt_engine:conv_error('transform-encode', Pack, "a length of ~p bytes", [Len])
    end;
len_bytes(#{len_enc := N} = Pack, Len) ->
    case Len < 1 bsl (8 * N) of
        true -> <<Len:N/unit:8>>;
        false -> gt_engine:conv_error('transform-encode', Pack, "length ~p does not fit ~p bytes", [Len, N])
    end.

%% A model value -> the value bytes. Integers into n bytes; a value that
%% does not fit fails (ruling 3 of 0.13; an 8-byte uint takes a negative
%% model integer by ruling 2 of 0.5).
encode_value(uint, V, 8) when is_integer(V), V >= -(1 bsl 63), V < 1 bsl 64 ->
    <<(V band 16#FFFFFFFFFFFFFFFF):64>>;
encode_value(uint, V, N) when is_integer(V), V >= 0, V < 1 bsl (8 * N) -> <<V:N/unit:8>>;
encode_value(twos, V, N) when is_integer(V), V >= -(1 bsl (8 * N - 1)), V < 1 bsl (8 * N - 1) ->
    <<V:N/signed-unit:8>>;
encode_value({uscale, _, _} = Tr, V, N) ->
    U = gt_engine:bits_encode(Tr, V, 8 * N, msb),
    <<U:N/unit:8>>;
encode_value({sscale, _, _} = Tr, V, N) ->
    U = gt_engine:bits_encode(Tr, V, 8 * N, msb),
    <<U:N/unit:8>>;
encode_value(f32, V, _) ->
    U = gt_engine:bits_encode(f32, V, 32, msb),
    <<U:32>>;
encode_value(f64, V, _) when is_number(V) -> <<(float(V)):64/float>>;
encode_value(utf8, V, _) when is_binary(V) -> V;
encode_value(hex, V, _) when is_binary(V) -> strict_hex(V, <<>>).

%% Hex digits, either case, an even number; nothing else.
strict_hex(<<>>, Acc) -> Acc;
strict_hex(<<H, L, R/binary>>, Acc) -> strict_hex(R, <<Acc/binary, (nib(H) * 16 + nib(L))>>).

nib(C) when C >= $0, C =< $9 -> C - $0;
nib(C) when C >= $a, C =< $f -> C - $a + 10;
nib(C) when C >= $A, C =< $F -> C - $A + 10.
