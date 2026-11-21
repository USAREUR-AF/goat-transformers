%% gt_cbor: the `cbor` wire (engine-spec Version 0.28). Clean-room from spec/
%% and packs/ only.
%%
%% A message is one CBOR data item (RFC 8949), read and written here with no
%% library. Input and output are hex text.
%%
%% A path is a list of steps: {i, Integer} (an integer map key), {t, Binary}
%% (a text map key) or {p, Index} (an array position); `.` inside a group
%% body is []. A residue path may also hold {x, KeyBytes}: a key that no step
%% can write, as its bytes stood in the input.
%%
%% A read item is a 3-tuple {Type, Value, Raw}, Raw its bytes in the input:
%%   {int, Integer, Raw}            major types 0 and 1
%%   {bytes, Binary, Raw}           major type 2, chunks joined
%%   {text, Binary, Raw}            major type 3, chunks joined
%%   {array, tuple(Item), Raw}      major type 4
%%   {map, {[{Key, Value}], #{Step => Value}}, Raw}   major type 5; the index
%%                                  holds the members whose key a step names
%%   {tag, {N, Item}, Raw}          major type 6
%%   {simple, N, Raw}               major type 7: 20 false, 21 true, 22 null,
%%                                  23 undefined, others as read
%%   {float, Bits64, Raw}           a half, single or double as the bits of
%%                                  the double it is (exactly)
%% Residue is [{Path, RawBytes}], each item as it stood, tags included.
-module(gt_cbor).
-export([decode/2, encode/4]).
-export([path/1, fixed/1, tag_value/1, check_pack/1, prepare/1, transform_ok/1]).

-define(MAX_DEPTH, 64).
-define(MIN63, -(1 bsl 63)).
-define(MAX63, (1 bsl 63) - 1).
-define(MAX64, (1 bsl 64) - 1).

%% ===================================================================
%% load: paths, values, the `tag` directive, the checks after the file
%% ===================================================================
%% A path that is not `.` -> [Step]; anything else is bad-locator, a line
%% check (step 8 of 5b of 0.11).
path(S) ->
    Steps = binary:split(S, <<".">>, [global]),
    [step(St, S) || St <- Steps].

step(<<>>, S) -> bad_locator("cbor path ~s has an empty step", [S]);
step(<<"[", Rest/binary>> = St, S) ->
    case byte_size(Rest) >= 2 andalso binary:last(Rest) =:= $] of
        true ->
            Digits = binary:part(Rest, 0, byte_size(Rest) - 1),
            case decimal(Digits) of
                {ok, N} when N =< 65535 -> {p, N};
                _ -> bad_locator("cbor path ~s: ~s is not a position [0] to [65535] with no leading zero",
                                 [S, St])
            end;
        false -> bad_locator("cbor path ~s: ~s is not a position [i]", [S, St])
    end;
step(<<$-, Digits/binary>> = St, S) ->
    case decimal(Digits) of
        {ok, N} when N >= 1, N =< 1 bsl 63 -> {i, -N};
        _ -> bad_locator("cbor path ~s: ~s is not an integer key from -2^63 to 2^64-1", [S, St])
    end;
step(<<C, _/binary>> = St, S) when C >= $0, C =< $9 ->
    case decimal(St) of
        {ok, N} when N =< ?MAX64 -> {i, N};
        _ -> bad_locator("cbor path ~s: ~s is not an integer key from -2^63 to 2^64-1", [S, St])
    end;
step(St, S) ->
    case text_key(St) of
        true -> {t, St};
        false -> bad_locator("cbor path ~s: ~s is not an integer key, a position or a text key", [S, St])
    end.

%% Decimal digits with no leading zero.
decimal(<<$0>>) -> {ok, 0};
decimal(<<$0, _/binary>>) -> error;
decimal(<<>>) -> error;
decimal(B) ->
    case lists:all(fun(C) -> C >= $0 andalso C =< $9 end, binary_to_list(B)) of
        true -> {ok, binary_to_integer(B)};
        false -> error
    end.

%% One or more ASCII letters, digits, `_` and `-`, not beginning with a
%% digit or `-`.
text_key(<<C, _/binary>>) when C >= $0, C =< $9 -> false;
text_key(<<$-, _/binary>>) -> false;
text_key(<<>>) -> false;
text_key(B) -> lists:all(fun key_char/1, binary_to_list(B)).

key_char(C) when C >= $a, C =< $z -> true;
key_char(C) when C >= $A, C =< $Z -> true;
key_char(C) when C >= $0, C =< $9 -> true;
key_char($_) -> true;
key_char($-) -> true;
key_char(_) -> false.

bad_locator(Fmt, Args) ->
    Msg = lists:flatten(io_lib:format("~s: " ++ Fmt, ['bad-locator' | Args])),
    erlang:error({line_error, 'bad-locator', Msg}).

%% A `when` or `const` value (Kinds of 0.28): an integer when 2a of 0.11
%% reads it and it lies in -2^63 to 2^64-1 (ruling 8; beyond, ruling 19 makes
%% it text); `true`, `false` a bool; anything else text, one `=` stripped.
fixed(V) ->
    case int_text(V) of
        {ok, N} when N >= ?MIN63, N =< ?MAX64 -> {int, N};
        _ ->
            case V of
                <<"true">> -> {bool, true};
                <<"false">> -> {bool, false};
                <<$=, T/binary>> -> {text, T};
                _ -> {text, V}
            end
    end.

%% 2a of 0.11 without its range: an optional `-` and one or more digits.
int_text(<<$-, D/binary>>) ->
    case digits(D) of
        true -> {ok, -binary_to_integer(D)};
        false -> error
    end;
int_text(D) ->
    case digits(D) of
        true -> {ok, binary_to_integer(D)};
        false -> error
    end.

digits(<<>>) -> false;
digits(B) -> lists:all(fun(C) -> C >= $0 andalso C =< $9 end, binary_to_list(B)).

%% The argument of `tag <n>` on `cbor`: a decimal integer from 0 to 2^64-1
%% with no leading zero -> {ok, N} | error.
tag_value([B]) ->
    case decimal(B) of
        {ok, N} when N =< ?MAX64 -> {ok, N};
        _ -> error
    end;
tag_value(_) -> error.

%% The transforms of the cbor table.
transform_ok(Tr) -> lists:member(Tr, [uint, int, float, text, bytes, bool, epoch_s]).

%% The checks of "Paths" and of rulings 13 and 22 that need the whole file;
%% each failure is bad-directive.
check_pack(#{common := Common, kinds := Kinds}) ->
    All = Common ++ lists:append([maps:get(lines, K) || K <- Kinds]),
    case lists:usort([T || L <- All, T <- [top_of(L)], T =/= none]) of
        [_, _] -> load_bad("the paths decide both a map and an array as the top item", []);
        _ -> ok
    end,
    Scopes = case Kinds of
                 [] -> [Common];
                 _ -> [Common ++ maps:get(lines, K) || K <- Kinds]
             end,
    lists:foreach(fun scope_check/1, Scopes).

%% The pack's top type and tag, read once at load.
prepare(#{common := Common, kinds := Kinds} = P) ->
    All = Common ++ lists:append([maps:get(lines, K) || K <- Kinds]),
    Top = case lists:member(array, [top_of(L) || L <- All]) of
              true -> array;
              false -> map
          end,
    Tag = case maps:get(tag_args, P, none) of
              none -> none;
              Args ->
                  {ok, N} = tag_value(Args),
                  N
          end,
    P#{cbor_top => Top, cbor_tag => Tag}.

load_bad(Fmt, Args) -> gt_pack:load_error('bad-directive', Fmt, Args).

top_of(L) ->
    case line_path(L) of
        none -> none;
        [] -> array;                              % group <list> .
        [{p, _} | _] -> array;
        [_ | _] -> map
    end.

%% The path of a line, and what the line does there.
line_path({field, _, Path, _, _, _}) -> Path;
line_path({wh, Path, _, _}) -> Path;
line_path({const, Path, _, _}) -> Path;
line_path({group, _, Path, _, _, _}) -> Path;
line_path(_) -> none.

line_role({field, _, _, _, _, _}) -> value;
line_role({wh, _, present, _}) -> present;
line_role({wh, _, _, _}) -> value;
line_role({const, _, _, _}) -> value;
line_role({group, _, _, _, _, _}) -> group.

line_text({field, _, _, _, T, _}) -> T;
line_text({wh, _, _, T}) -> T;
line_text({const, _, _, T}) -> T;
line_text({group, _, _, _, _, T}) -> T.

%% One scope: the common lines with one kind's, or one group body.
scope_check(Lines0) ->
    Lines = [L || L <- Lines0, line_path(L) =/= none],
    Roles = lists:foldl(fun(L, M) ->
                                maps:update_with(line_path(L), fun(Rs) -> [line_role(L) | Rs] end,
                                                 [line_role(L)], M)
                        end, #{}, Lines),
    %% a step whose item is used both as a map and as an array
    lists:foldl(
      fun(L, Types) ->
              Path = line_path(L),
              Own = case line_role(L) of
                        group -> [{Path, array}];
                        _ -> []
                    end,
              Uses = [{lists:sublist(Path, N), step_type(lists:nth(N + 1, Path))}
                      || N <- lists:seq(0, length(Path) - 1)] ++ Own,
              lists:foldl(
                fun({Pre, T}, Acc) ->
                        case maps:find(Pre, Acc) of
                            {ok, T} -> Acc;
                            {ok, _} -> load_bad("~s uses an item both as a map and as an array",
                                                [line_text(L)]);
                            error -> Acc#{Pre => T}
                        end
                end, Types, Uses)
      end, #{}, Lines),
    %% a list is mapped by at most one group of the scope
    Lists = [List || {group, List, _, _, _, _} <- Lines],
    case length(lists:usort(Lists)) =:= length(Lists) of
        true -> ok;
        false -> load_bad("a list is mapped by two groups of one scope", [])
    end,
    lists:foreach(
      fun(L) ->
              Path = line_path(L),
              Role = line_role(L),
              Here = maps:get(Path, Roles),
              %% at a group's path: another line there (ruling 13, Types)
              case length([R || R <- Here, R =:= group]) of
                  0 -> ok;
                  1 when Role =:= group -> ok;
                  _ -> load_bad("~s stands at the path of a group", [line_text(L)])
              end,
              %% under the path of another line: a when ... present is
              %% exempt only as the shorter path (rulings 13 and 22)
              lists:foreach(
                fun(Pre) ->
                        case maps:find(Pre, Roles) of
                            error -> ok;
                            {ok, Rs} ->
                                case lists:any(fun(R) -> R =/= present end, Rs) of
                                    true -> load_bad("~s lies under the path of another line of its scope",
                                                     [line_text(L)]);
                                    false -> ok
                                end
                        end
                end, [lists:sublist(Path, N) || N <- lists:seq(0, length(Path) - 1)])
      end, Lines),
    lists:foreach(fun({group, _, _, _, #{lines := Body}, _}) -> scope_check(Body);
                     (_) -> ok
                  end, Lines).

step_type({p, _}) -> array;
step_type(_) -> map.

%% ===================================================================
%% decode
%% ===================================================================
decode(Pack, Text) ->
    Bytes = gt_engine:unhex(Pack, Text),
    Item = read_all(Pack, Bytes),
    Top0 = case maps:get(cbor_tag, Pack) of
               none -> Item;
               N ->
                   case Item of
                       {tag, {N, Inner}, _} -> Inner;
                       {tag, {M, _}, _} -> malformed(Pack, "the outermost tag is ~p, not ~p", [M, N]);
                       _ -> malformed(Pack, "the message is not enclosed in tag ~p", [N])
                   end
           end,
    Top = strip(Top0),
    case {maps:get(cbor_top, Pack), element(1, Top)} of
        {T, T} -> ok;
        {T, Got} -> malformed(Pack, "the top item is ~s where the paths decide ~s", [Got, T])
    end,
    {Kind, Lines} = select(Pack, Top),
    check_scope(Pack, Top, Lines),
    {Model, Lists} = scope(Pack, Top, Lines),
    #{model => Model,
      lists => Lists,
      residue => residue(Top, Lines),
      src => maps:get(name, Pack),
      kind => case Kind of
                  undefined -> undefined;
                  _ -> {maps:get(name, Pack), Kind}
              end}.

malformed(Pack, Fmt, Args) ->
    gt_engine:conv_error('malformed-wire', Pack, Fmt, Args).

strip({tag, {_, I}, _}) -> strip(I);
strip(I) -> I.

is_nil({simple, V, _}) -> V =:= 22 orelse V =:= 23;
is_nil(_) -> false.

%% ---- kinds (Reading step 7) ----
select(#{has_kinds := false, common := Common}, _Top) -> {undefined, Common};
select(#{common := Common, kinds := Kinds} = Pack, Top) ->
    Holds = fun(Ls) ->
                    lists:all(fun({wh, Path, Val, _}) -> when_holds(Top, Path, Val);
                                 (_) -> true
                              end, Ls)
            end,
    case Holds(Common) of
        true -> ok;
        false -> gt_engine:conv_error('no-kind', Pack, "a common when does not hold", [])
    end,
    case first(fun(#{lines := Ls}) -> Holds(Ls) end, Kinds) of
        none -> gt_engine:conv_error('no-kind', Pack, "no kind's when lines hold for this message", []);
        #{name := Name, lines := Ls} -> {Name, Common ++ Ls}
    end.

first(_Pred, []) -> none;
first(Pred, [X | Rest]) ->
    case Pred(X) of
        true -> X;
        false -> first(Pred, Rest)
    end.

when_holds(Top, Path, Val) ->
    case walk(Top, Path) of
        {ok, I} -> holds(I, Val);
        _ -> false
    end.

holds(I, _) when element(1, I) =:= simple, element(2, I) =:= 22 -> false;
holds(I, _) when element(1, I) =:= simple, element(2, I) =:= 23 -> false;
holds(_, present) -> true;
holds({int, V, _}, {int, V}) -> true;
holds({simple, 21, _}, {bool, true}) -> true;
holds({simple, 20, _}, {bool, false}) -> true;
holds({text, B, _}, {text, B}) -> true;
holds(_, _) -> false.

%% The item at a path, its tags passed over -> {ok, Item} | absent | bad.
%% `null` or `undefined` partway down is absent (ruling 12); an item that is
%% not the map or array its next step needs is bad.
walk(I, []) -> {ok, strip(I)};
walk(I0, [S | Rest]) ->
    I = strip(I0),
    case {I, S} of
        {{simple, V, _}, _} when V =:= 22; V =:= 23 -> absent;
        {{array, T, _}, {p, N}} ->
            case N < tuple_size(T) of
                true -> walk(element(N + 1, T), Rest);
                false -> absent
            end;
        {{array, _, _}, _} -> bad;
        {{map, {_, Index}, _}, {p, _}} when is_map(Index) -> bad;
        {{map, {_, Index}, _}, _} ->
            case maps:find(S, Index) of
                {ok, V} -> walk(V, Rest);
                error -> absent
            end;
        _ -> bad
    end.

%% ---- Reading step 8, for the lines of a scope and of every group item ----
check_scope(Pack, Ctx, Lines) ->
    lists:foreach(
      fun({group, _, Path, _, Body, LocT}) ->
              case walk(Ctx, Path) of
                  bad -> malformed(Pack, "the path of group ~s passes through an item of another type", [LocT]);
                  absent -> ok;
                  {ok, {array, T, _}} ->
                      lists:foreach(fun(E) -> check_item(Pack, E, Body) end, tuple_to_list(T));
                  {ok, I} ->
                      case is_nil(I) of
                          true -> ok;
                          false -> malformed(Pack, "the item at group ~s is not an array", [LocT])
                      end
              end;
         (L) ->
              case line_path(L) of
                  none -> ok;
                  [] -> ok;
                  Path ->
                      case walk(Ctx, Path) of
                          bad -> malformed(Pack, "~s passes through an item that is not the map or array its next step needs",
                                           [line_text(L)]);
                          _ -> ok
                      end
              end
      end, Lines).

check_item(Pack, E, #{lines := Lines}) ->
    case item_ctx(E, body_type(Lines)) of
        none -> ok;
        Ctx -> check_scope(Pack, Ctx, Lines)
    end.

%% What a group body reads an element as: scalar (`.`), map or array, or
%% none when its lines have no path.
body_type(Lines) ->
    case [P || L <- Lines, P <- [line_path(L)], P =/= none] of
        [] -> none;
        [[] | _] -> scalar;
        [[{p, _} | _] | _] -> array;
        _ -> map
    end.

%% The element as the context of its body's lines, or none when it is of the
%% wrong type: an item with no keys (ruling 12 of 0.7).
item_ctx(_E, none) -> none;
item_ctx(E, scalar) -> E;
item_ctx(E, Type) ->
    I = strip(E),
    case element(1, I) of
        Type -> I;
        _ -> none
    end.

%% ---- the lines of a scope read -> {Model, Lists} ----
%% A key mapped by several lines takes its value from the earliest line
%% whose item is present and whose transform succeeds; a failing line is an
%% error only when no line of its key succeeds.
scope(Pack, Ctx, Lines) ->
    {Model, Lists, Failed} =
        lists:foldl(
          fun({field, Key, Path, Tr, LocT, Opts}, {M, Ls, F} = Acc) ->
                  case maps:is_key(Key, M) of
                      true -> Acc;
                      false ->
                          case walk(Ctx, Path) of
                              {ok, I} ->
                                  case is_nil(I) of
                                      true -> Acc;
                                      false ->
                                          try value(Tr, I) of
                                              V0 ->
                                                  V1 = gt_engine:via_decode(Opts, V0, Tr, Key, LocT, Pack),
                                                  {M#{Key => gt_engine:typemap_decode(Key, V1, Pack)}, Ls, F}
                                          catch
                                              _:_ -> {M, Ls, [{Key, LocT} | F]}
                                          end
                                  end;
                              _ -> Acc
                          end
                  end;
             ({group, List, Path, _, Body, _}, {M, Ls, F}) ->
                  case walk(Ctx, Path) of
                      {ok, {array, T, _}} ->
                          Els = tuple_to_list(T),
                          gt_engine:items_reserve(length(Els), Pack),
                          {M, Ls#{List => [group_item(Pack, E, Body) || E <- Els]}, F};
                      _ -> {M, Ls, F}
                  end;
             (_, Acc) -> Acc
          end, {#{}, #{}, []}, Lines),
    case [KL || {K, _} = KL <- lists:reverse(Failed), not maps:is_key(K, Model)] of
        [] -> ok;
        Bad ->
            gt_engine:record_failure(Pack, "failed fields: ~s",
                                     [lists:join(", ", [[K, " at ", L] || {K, L} <- Bad])])
    end,
    {Model, Lists}.

group_item(Pack, E, #{lines := Lines}) ->
    case item_ctx(E, body_type(Lines)) of
        none -> #{model => #{}, lists => #{}};
        Ctx ->
            {M, Ls} = scope(Pack, Ctx, Lines),
            #{model => M, lists => Ls}
    end.

%% An item through a transform; another type than the transform takes fails.
value(uint, {int, V, _}) when V >= 0, V =< ?MAX63 -> V;
value(int, {int, V, _}) when V >= ?MIN63, V =< ?MAX63 -> V;
value(float, {float, D, _}) -> double(D);
value(float, {int, V, _}) -> int_to_double(V);
value(text, {text, B, _}) -> B;
value(bytes, {bytes, B, _}) -> gt_hex:bytes_to_hex(B);
value(bool, {simple, 20, _}) -> 0;
value(bool, {simple, 21, _}) -> 1;
value(epoch_s, {int, V, _}) when V * 1000 >= ?MIN63, V * 1000 =< ?MAX63 -> V * 1000;
value(Tr, I) -> erlang:error({cbor_type, Tr, element(1, I)}).

%% A double from its bits; a NaN or an infinity is refused.
double(D) when (D bsr 52) band 16#7FF =:= 16#7FF -> erlang:error(not_finite);
double(D) ->
    <<F:64/float>> = <<D:64>>,
    F.

%% The nearest double to an integer, a tie to the even one (2b of 0.11).
int_to_double(V) when V < 0 -> -int_to_double(-V);
int_to_double(V) when V < 1 bsl 53 -> float(V);
int_to_double(V) ->
    Shift = bit_length(V) - 53,
    Q = V bsr Shift,
    R = V - (Q bsl Shift),
    Half = 1 bsl (Shift - 1),
    Q1 = if
             R > Half -> Q + 1;
             R =:= Half, Q band 1 =:= 1 -> Q + 1;
             true -> Q
         end,
    float(Q1) * math:pow(2, Shift).

bit_length(0) -> 0;
bit_length(V) -> bit_length(V bsr 1) + 1.

%% ---- residue ----
%% Every member or element of the top item, and of each item a line of the
%% selected scope walks into, that no line maps and no line walks into. A
%% `when ... present` walks into its prefixes and maps nothing; a group maps
%% its own path (ruling 24).
residue(Top, Lines) ->
    {Mapped, Walked} =
        lists:foldl(
          fun(L, {M, W}) ->
                  case line_path(L) of
                      none -> {M, W};
                      Path ->
                          Pres = [lists:sublist(Path, N) || N <- lists:seq(0, length(Path) - 1)],
                          W1 = lists:foldl(fun(P, A) -> A#{P => true} end, W, Pres),
                          case line_role(L) of
                              present -> {M, W1};
                              _ -> {M#{Path => true}, W1}
                          end
                  end
          end, {#{}, #{}}, Lines),
    case maps:is_key([], Mapped) of
        true -> [];
        false -> lists:reverse(res(Top, [], Mapped, Walked, []))
    end.

res(I0, Path, Mapped, Walked, Acc) ->
    Members =
        case strip(I0) of
            {map, {Pairs, _}, _} -> [{key_step(K), V} || {K, V} <- Pairs];
            {array, T, _} ->
                %% past position 65535 no path can write it (ruling 18)
                [{{p, N}, element(N + 1, T)} || N <- lists:seq(0, min(tuple_size(T), 65536) - 1)];
            _ -> []
        end,
    lists:foldl(
      fun({Step, V}, A) ->
              P = Path ++ [Step],
              case maps:is_key(P, Mapped) of
                  true -> A;
                  false ->
                      case maps:is_key(P, Walked) of
                          true -> res(V, P, Mapped, Walked, A);
                          false -> [{P, element(3, V)} | A]
                      end
              end
      end, Acc, Members).

%% The step that names a map key, or {x, KeyBytes} for a key no step can
%% write: another type, a text the grammar refuses, an integer below -2^63
%% (ruling 17).
key_step({int, V, _}) when V >= ?MIN63 -> {i, V};
key_step({text, B, Raw}) ->
    case text_key(B) of
        true -> {t, B};
        false -> {x, Raw}
    end;
key_step(K) -> {x, element(3, K)}.

%% ===================================================================
%% the CBOR reader (RFC 8949): one well-formed item, nothing after it
%% ===================================================================
read_all(Pack, Bytes) ->
    try item(Bytes, 0, 1) of
        {I, End} when End =:= byte_size(Bytes) -> I;
        {_, End} -> malformed(Pack, "~p bytes follow the data item", [byte_size(Bytes) - End])
    catch
        throw:{cbor_bad, Fmt, Args} -> malformed(Pack, Fmt, Args)
    end.

bad(Fmt, Args) -> throw({cbor_bad, Fmt, Args}).

item(B, P, D) ->
    case B of
        <<_:P/binary, IB, _/binary>> -> item(IB bsr 5, IB band 31, B, P, D);
        _ -> bad("the input ends where an item stands at byte ~p", [P])
    end.

item(7, AI, B, P, _D) -> simple(AI, B, P);
item(MT, 31, B, P, D) -> indefinite(MT, B, P, D);
item(MT, AI, B, P, D) ->
    {Arg, P1} = arg(AI, B, P + 1),
    case MT of
        0 -> {{int, Arg, raw(B, P, P1)}, P1};
        1 -> {{int, -1 - Arg, raw(B, P, P1)}, P1};
        2 ->
            {S, P2} = take(B, P1, Arg),
            {{bytes, S, raw(B, P, P2)}, P2};
        3 ->
            {S, P2} = take(B, P1, Arg),
            utf8(S),
            {{text, S, raw(B, P, P2)}, P2};
        4 ->
            depth(D),
            %% each element takes at least one byte
            fits(Arg, B, P1),
            {Els, P2} = items(Arg, B, P1, D + 1, []),
            {{array, list_to_tuple(Els), raw(B, P, P2)}, P2};
        5 ->
            depth(D),
            fits(2 * Arg, B, P1),
            {Pairs, P2} = pairs(Arg, B, P1, D + 1, []),
            {{map, index(Pairs), raw(B, P, P2)}, P2};
        6 ->
            depth(D),
            {I, P2} = item(B, P1, D + 1),
            {{tag, {Arg, I}, raw(B, P, P2)}, P2}
    end.

raw(B, From, To) -> binary:part(B, From, To - From).

%% Arrays, maps and tags count one level each, the top item level 1.
depth(D) when D > ?MAX_DEPTH -> bad("the items nest deeper than ~p levels", [?MAX_DEPTH]);
depth(_) -> ok.

%% A declared count is compared with the bytes left before anything is read.
fits(N, B, P) when N =< byte_size(B) - P -> ok;
fits(N, B, P) -> bad("an item declares ~p and ~p bytes are left", [N, byte_size(B) - P]).

%% The argument of a head, read in any length.
arg(AI, _B, P) when AI < 24 -> {AI, P};
arg(24, B, P) -> fixed_arg(B, P, 8);
arg(25, B, P) -> fixed_arg(B, P, 16);
arg(26, B, P) -> fixed_arg(B, P, 32);
arg(27, B, P) -> fixed_arg(B, P, 64);
arg(AI, _B, P) -> bad("additional information ~p at byte ~p is reserved", [AI, P - 1]).

fixed_arg(B, P, Bits) ->
    case B of
        <<_:P/binary, V:Bits, _/binary>> -> {V, P + Bits div 8};
        _ -> bad("a head runs past the input at byte ~p", [P])
    end.

take(B, P, Len) ->
    case Len =< byte_size(B) - P of
        true -> {binary:part(B, P, Len), P + Len};
        false -> bad("a string declares ~p bytes and ~p are left", [Len, byte_size(B) - P])
    end.

utf8(S) ->
    case unicode:characters_to_binary(S, utf8, utf8) of
        S -> ok;
        _ -> bad("a text string is not valid UTF-8", [])
    end.

items(0, _B, P, _D, Acc) -> {lists:reverse(Acc), P};
items(N, B, P, D, Acc) ->
    {I, P1} = item(B, P, D),
    items(N - 1, B, P1, D, [I | Acc]).

pairs(0, _B, P, _D, Acc) -> {lists:reverse(Acc), P};
pairs(N, B, P, D, Acc) ->
    {K, P1} = item(B, P, D),
    {V, P2} = item(B, P1, D),
    pairs(N - 1, B, P2, D, [{K, V} | Acc]).

%% Major type 7: simple values and floats.
simple(AI, B, P) when AI < 24 -> {{simple, AI, raw(B, P, P + 1)}, P + 1};
simple(24, B, P) ->
    case B of
        <<_:P/binary, _, V, _/binary>> when V >= 32 -> {{simple, V, raw(B, P, P + 2)}, P + 2};
        <<_:P/binary, _, V, _/binary>> -> bad("a simple value ~p in two bytes", [V]);
        _ -> bad("a simple value runs past the input", [])
    end;
simple(25, B, P) ->
    {H, P1} = fixed_arg(B, P + 1, 16),
    {{float, widen(H, 5, 10), raw(B, P, P1)}, P1};
simple(26, B, P) ->
    {S, P1} = fixed_arg(B, P + 1, 32),
    {{float, widen(S, 8, 23), raw(B, P, P1)}, P1};
simple(27, B, P) ->
    {F, P1} = fixed_arg(B, P + 1, 64),
    {{float, F, raw(B, P, P1)}, P1};
simple(31, _B, P) -> bad("a break where an item stands at byte ~p", [P]);
simple(AI, _B, P) -> bad("additional information ~p of major type 7 at byte ~p is reserved", [AI, P]).

%% Indefinite lengths: strings in definite chunks of their own type, arrays
%% and maps up to a break.
indefinite(MT, B, P, _D) when MT =:= 2; MT =:= 3 ->
    {Chunks, P1} = chunks(MT, B, P + 1, []),
    S = iolist_to_binary(Chunks),
    Type = case MT of 2 -> bytes; 3 -> text end,
    {{Type, S, raw(B, P, P1)}, P1};
indefinite(4, B, P, D) ->
    depth(D),
    {Els, P1} = until_break(B, P + 1, D + 1, []),
    {{array, list_to_tuple(Els), raw(B, P, P1)}, P1};
indefinite(5, B, P, D) ->
    depth(D),
    {Pairs, P1} = pairs_until_break(B, P + 1, D + 1, []),
    {{map, index(Pairs), raw(B, P, P1)}, P1};
indefinite(MT, _B, P, _D) ->
    bad("major type ~p takes no indefinite length (byte ~p)", [MT, P]).

chunks(MT, B, P, Acc) ->
    case B of
        <<_:P/binary, 16#FF, _/binary>> -> {lists:reverse(Acc), P + 1};
        <<_:P/binary, IB, _/binary>> when IB bsr 5 =:= MT, IB band 31 =/= 31 ->
            {Len, P1} = arg(IB band 31, B, P + 1),
            {S, P2} = take(B, P1, Len),
            case MT of
                3 -> utf8(S);                    % each chunk on its own
                2 -> ok
            end,
            chunks(MT, B, P2, [S | Acc]);
        <<_:P/binary, _, _/binary>> ->
            bad("a chunk of an indefinite string is not a definite string of its type (byte ~p)", [P]);
        _ -> bad("an indefinite string has no break", [])
    end.

until_break(B, P, D, Acc) ->
    case B of
        <<_:P/binary, 16#FF, _/binary>> -> {lists:reverse(Acc), P + 1};
        <<_:P/binary, _, _/binary>> ->
            {I, P1} = item(B, P, D),
            until_break(B, P1, D, [I | Acc]);
        _ -> bad("an indefinite array has no break", [])
    end.

pairs_until_break(B, P, D, Acc) ->
    case B of
        <<_:P/binary, 16#FF, _/binary>> -> {lists:reverse(Acc), P + 1};
        <<_:P/binary, _, _/binary>> ->
            {K, P1} = item(B, P, D),
            {V, P2} = item(B, P1, D),
            pairs_until_break(B, P2, D, [{K, V} | Acc]);
        _ -> bad("an indefinite map has no break", [])
    end.

%% The members of a map, indexed by the steps that name them; two equal
%% keys are refused (Reading step 4).
index(Pairs) ->
    {Index, _} =
        lists:foldl(
          fun({K, V}, {Ix, Seen}) ->
                  Id = key_id(K),
                  case maps:is_key(Id, Seen) of
                      true -> bad("a map holds the key ~s twice", [gt_hex:bytes_to_hex(element(3, K))]);
                      false -> ok
                  end,
                  Ix1 = case key_step(K) of
                            {x, _} -> Ix;
                            Step -> Ix#{Step => V}
                        end,
                  {Ix1, Seen#{Id => true}}
          end, {#{}, #{}}, Pairs),
    {Pairs, Index}.

%% Keys of different major types are never equal; integers by value, text
%% by bytes, others by their core deterministic encoding.
key_id({int, V, _}) -> {i, V};
key_id({text, B, _}) -> {t, B};
key_id(K) -> {o, iolist_to_binary(det(K))}.

%% Half and single bits -> the bits of the same double.
widen(Bits, EB, MB) ->
    EMax = (1 bsl EB) - 1,
    Bias = EMax bsr 1,
    S = Bits bsr (EB + MB),
    E = (Bits bsr MB) band EMax,
    M = Bits band ((1 bsl MB) - 1),
    if
        E =:= EMax -> (S bsl 63) bor (16#7FF bsl 52) bor (M bsl (52 - MB));
        E =:= 0, M =:= 0 -> S bsl 63;
        E =:= 0 ->
            K = bit_length(M),
            Exp = (K - 1) + (1 - Bias - MB),
            Mant = (M - (1 bsl (K - 1))) bsl (52 - (K - 1)),
            (S bsl 63) bor ((Exp + 1023) bsl 52) bor Mant;
        true -> (S bsl 63) bor ((E - Bias + 1023) bsl 52) bor (M bsl (52 - MB))
    end.

%% ===================================================================
%% the core deterministic encoding (RFC 8949 4.2.1)
%% ===================================================================
%% A read item re-encoded -> iodata.
det({int, V, _}) -> int_bytes(V);
det({bytes, B, _}) -> [head(2, byte_size(B)), B];
det({text, B, _}) -> [head(3, byte_size(B)), B];
det({array, T, _}) -> [head(4, tuple_size(T)) | [det(E) || E <- tuple_to_list(T)]];
det({map, {Pairs, _}, _}) ->
    Ents = lists:sort([{iolist_to_binary(det(K)), det(V)} || {K, V} <- Pairs]),
    [head(5, length(Ents)) | [[K, V] || {K, V} <- Ents]];
det({tag, {N, I}, _}) -> [head(6, N), det(I)];
det({simple, N, _}) when N < 24 -> <<(16#E0 + N)>>;
det({simple, N, _}) -> <<16#F8, N>>;
det({float, D, _}) -> float_bits(D).

head(MT, V) when V < 24 -> <<MT:3, V:5>>;
head(MT, V) when V < 16#100 -> <<MT:3, 24:5, V:8>>;
head(MT, V) when V < 16#10000 -> <<MT:3, 25:5, V:16>>;
head(MT, V) when V < 16#100000000 -> <<MT:3, 26:5, V:32>>;
head(MT, V) -> <<MT:3, 27:5, V:64>>.

int_bytes(V) when V >= 0 -> head(0, V);
int_bytes(V) -> head(1, -1 - V).

%% A double's bits at the shortest of half, single and double that holds
%% them exactly, subnormal halves included.
float_bits(D) ->
    case narrow(D, 5, 10) of
        {ok, H} -> <<16#F9, H:16>>;
        error ->
            case narrow(D, 8, 23) of
                {ok, S} -> <<16#FA, S:32>>;
                error -> <<16#FB, D:64>>
            end
    end.

narrow(D, EB, MB) ->
    EMax = (1 bsl EB) - 1,
    Bias = EMax bsr 1,
    S = D bsr 63,
    E = (D bsr 52) band 16#7FF,
    M = D band ((1 bsl 52) - 1),
    Shift = 52 - MB,
    Sign = S bsl (EB + MB),
    if
        E =:= 16#7FF ->
            case M band ((1 bsl Shift) - 1) of
                0 -> {ok, Sign bor (EMax bsl MB) bor (M bsr Shift)};
                _ -> error
            end;
        E =:= 0, M =:= 0 -> {ok, Sign};
        E =:= 0 -> error;                          % a double subnormal
        true ->
            Exp = E - 1023,
            if
                Exp > Bias -> error;
                Exp >= 1 - Bias ->
                    case M band ((1 bsl Shift) - 1) of
                        0 -> {ok, Sign bor ((Exp + Bias) bsl MB) bor (M bsr Shift)};
                        _ -> error
                    end;
                true ->
                    Full = (1 bsl 52) bor M,
                    K = 53 - Bias - MB - Exp,
                    case K =< 52 andalso Full band ((1 bsl K) - 1) =:= 0 of
                        true -> {ok, Sign bor (Full bsr K)};
                        false -> error
                    end
            end
    end.

%% ===================================================================
%% encode
%% ===================================================================
%% Lines: the selected scope; Src = {Value, Lists, Held}; Residue: [{Path,
%% Raw}] when the entity was decoded from this format.
encode(Pack, Lines, Src, Residue) ->
    Type = case maps:get(cbor_top, Pack) of
               array -> a;
               map -> m
           end,
    Tree0 = tree(Pack, Lines, Src, Type),
    Tree = lists:foldl(fun({Path, Raw}, T) -> insert(T, Path, {v, redet(Raw)}) end,
                       Tree0, Residue),
    Body = ser(Tree, [], walk_types(Lines)),
    Out = case maps:get(cbor_tag, Pack) of
              none -> Body;
              N -> [head(6, N), Body]
          end,
    gt_hex:bytes_to_hex(iolist_to_binary(Out)).

%% A read item's bytes re-encoded with the core deterministic encoding.
redet(Raw) ->
    {I, _} = item(Raw, 0, 1),
    iolist_to_binary(det(I)).

%% Tree = {m, #{Step => Tree}} | {a, #{Index => Tree}} | {v, Bytes}.
tree(Pack, Lines, Src, Type) ->
    lists:foldl(fun({Path, Bytes}, T) -> insert(T, Path, {v, Bytes}) end,
                {Type, #{}}, writes(Pack, Lines, Src)).

%% Put a value at a path, making the maps and arrays on the way. A place
%% that holds something already keeps it: a line wins over residue (ruling
%% 21), and nothing is written through a value or a container of the other
%% type.
insert({v, _} = T, _Path, _V) -> T;
insert(T, [], _V) -> T;
insert({m, M} = T, [S | Rest], V) when element(1, S) =/= p -> {m, put_child(M, S, Rest, V, T)};
insert({a, M} = T, [{p, N} | Rest], V) -> {a, put_child(M, N, Rest, V, T)};
insert(T, _Path, _V) -> T.

put_child(M, K, [], V, _T) ->
    case maps:is_key(K, M) of
        true -> M;
        false -> M#{K => V}
    end;
put_child(M, K, [Next | _] = Rest, V, _T) ->
    Child = case maps:find(K, M) of
                {ok, C} -> C;
                error ->
                    case Next of
                        {p, _} -> {a, #{}};
                        _ -> {m, #{}}
                    end
            end,
    M#{K => insert(Child, Rest, V)}.

%% What the lines of a scope write -> [{Path, Bytes}], one per path: a
%% `when` or `const` value over a `field`, then the earliest field line with
%% a value (ruling 16 of 0.5), then a present list.
writes(Pack, Lines, Src) ->
    {Order, ByPath} =
        lists:foldl(
          fun(L, {O, B}) ->
                  case line_path(L) of
                      none -> {O, B};
                      P ->
                          case maps:find(P, B) of
                              {ok, Ls} -> {O, B#{P := Ls ++ [L]}};
                              error -> {[P | O], B#{P => [L]}}
                          end
                  end
          end, {[], #{}}, Lines),
    [{P, Bytes} || P <- lists:reverse(Order),
                   Bytes <- [place(Pack, maps:get(P, ByPath), Src)], Bytes =/= none].

place(Pack, Ls, {_Value, Lists, _Held} = Src) ->
    case [V || L <- Ls, V <- fixed_of(L)] of
        [V | _] -> fixed_bytes(V);
        [] ->
            Fields = [{K, Tr, LocT, Opts, Val} || {field, K, _, Tr, LocT, Opts} <- Ls,
                                                 {ok, Val} <- [gt_engine:line_value(Src, K, Opts)]],
            case Fields of
                [{K, Tr, LocT, Opts, Val} | _] ->
                    gt_engine:guard_encode(
                      Pack, K, LocT,
                      fun() ->
                              iolist_to_binary(enc_value(Tr, gt_engine:wire_value(Pack, K, Tr, Opts, Val)))
                      end);
                [] ->
                    case [{G, Items} || {group, List, _, _, _, _} = G <- Ls,
                                        {ok, Items} <- [maps:find(List, Lists)]] of
                        [{{group, _, _, _, Body, _}, Items} | _] ->
                            iolist_to_binary([head(4, length(Items)) |
                                              [enc_item(Pack, Body, I) || I <- Items]]);
                        [] -> none
                    end
            end
    end.

fixed_of({const, _, V, _}) -> [V];
fixed_of({wh, _, present, _}) -> [];
fixed_of({wh, _, V, _}) -> [V];
fixed_of(_) -> [].

fixed_bytes({int, V}) -> int_bytes(V);
fixed_bytes({bool, true}) -> <<16#F5>>;
fixed_bytes({bool, false}) -> <<16#F4>>;
fixed_bytes({text, B}) -> iolist_to_binary([head(3, byte_size(B)), B]).

%% One item of a list (Writing step 4): the scalar of its `.` line, f6 when
%% it has none; else its map, or its array when the body's paths begin with
%% positions, empty when nothing is written.
enc_item(Pack, #{lines := Lines} = Body, Item) ->
    Src = gt_engine:item_source(Item, Body),
    case body_type(Lines) of
        scalar ->
            case writes(Pack, Lines, Src) of
                [{[], Bytes} | _] -> Bytes;
                _ -> <<16#F6>>
            end;
        array -> ser(tree(Pack, Lines, Src, a), [], walk_types(Lines));
        _ -> ser(tree(Pack, Lines, Src, m), [], walk_types(Lines))
    end.

%% The type each item on the lines' paths is walked into as: #{Path => m | a}.
%% A group's own path is not walked into.
walk_types(Lines) ->
    lists:foldl(
      fun(L, Acc) ->
              case line_path(L) of
                  none -> Acc;
                  Path ->
                      lists:foldl(
                        fun(N, A) ->
                                Pre = lists:sublist(Path, N),
                                case maps:is_key(Pre, A) of
                                    true -> A;
                                    false ->
                                        A#{Pre => case lists:nth(N + 1, Path) of
                                                      {p, _} -> a;
                                                      _ -> m
                                                  end}
                                end
                        end, Acc, lists:seq(0, length(Path) - 1))
              end
      end, #{}, Lines).

%% A tree written: map members in the bytewise order of their encoded keys;
%% an array up to its highest present position, a gap as a0, 80 or f6 by
%% what the lines walk into there (Writing step 3, ruling 23).
ser({v, B}, _Path, _WT) -> B;
ser({m, M}, Path, WT) ->
    Ents = lists:sort([{key_bytes(S), ser(C, Path ++ [S], WT)} || {S, C} <- maps:to_list(M)]),
    [head(5, length(Ents)) | [[K, V] || {K, V} <- Ents]];
ser({a, M}, Path, WT) ->
    Max = lists:max([-1 | maps:keys(M)]),
    [head(4, Max + 1) |
     [case maps:find(N, M) of
          {ok, C} -> ser(C, Path ++ [{p, N}], WT);
          error ->
              case maps:find(Path ++ [{p, N}], WT) of
                  {ok, m} -> <<16#A0>>;
                  {ok, a} -> <<16#80>>;
                  error -> <<16#F6>>
              end
      end || N <- lists:seq(0, Max)]].

key_bytes({i, V}) -> int_bytes(V);
key_bytes({t, B}) -> iolist_to_binary([head(3, byte_size(B)), B]);
key_bytes({x, Raw}) -> redet(Raw).

%% A model value through a transform -> iodata; a value it cannot write
%% fails (the caller makes that transform-encode).
enc_value(uint, V) when is_integer(V), V >= 0, V =< ?MAX64 -> head(0, V);
enc_value(int, V) when is_integer(V), V >= -(1 bsl 64), V =< ?MAX64 -> int_bytes(V);
enc_value(float, V) when is_number(V) ->
    <<D:64>> = <<(float(V)):64/float>>,
    float_bits(D);
enc_value(text, V) when is_binary(V) ->
    V = unicode:characters_to_binary(V, utf8, utf8),
    [head(3, byte_size(V)), V];
enc_value(bytes, V) when is_binary(V), byte_size(V) rem 2 =:= 0 ->
    B = lower_hex(V, <<>>),
    [head(2, byte_size(B)), B];
enc_value(bool, 1) -> <<16#F5>>;
enc_value(bool, 0) -> <<16#F4>>;
enc_value(epoch_s, V) when is_integer(V), V >= ?MIN63, V =< ?MAX63 -> int_bytes(round_div1000(V)).

lower_hex(<<>>, Acc) -> Acc;
lower_hex(<<H, L, R/binary>>, Acc) -> lower_hex(R, <<Acc/binary, (nib(H) * 16 + nib(L))>>).

nib(C) when C >= $0, C =< $9 -> C - $0;
nib(C) when C >= $a, C =< $f -> C - $a + 10.

%% time_ms / 1000, exactly, rounded half away from zero.
round_div1000(V) ->
    Q = V div 1000,
    R = V rem 1000,
    if
        R >= 500 -> Q + 1;
        R =< -500 -> Q - 1;
        true -> Q
    end.
