%% gt_seq: decode and encode of a `bits` pack with `layout sequential`
%% (engine-spec Version 0.8). Clean-room from spec/ and packs/ only.
%%
%% The lines of a scope (gt_pack, "sequential layouts") are read, and
%% written, in file order from a cursor: the common lines, then the selected
%% kind's. An item of a list is #{model, lists} and, where the group body
%% holds kinds, `kind => {FormatName, KindName}`.
-module(gt_seq).
-export([decode/2, encode/4]).

%% ===================================================================
%% decode
%% ===================================================================
%% pos    the cursor, a bit offset from the message start
%% hard   the end of the input in bits; `length ... whole` moves it down
%% env    #{PresenceId => [bit numbers that are 1]}
%% model, lists, failed   of the scope being read (the message, or one item)
%% static  the presence bits an `if` in no case names; pending the bits that
%%         are 1 and that only `if` lines in cases name, until such a case
%%         is read (rulings 21, 30 and 36 of 0.20)
%% unit    how the innermost extent is counted: bytes (the message, `length
%%         ... bytes`) or bits (`length ... bits`), for a `rest` group (0.21)
%% counts  #{CountId => Items | absent}: the counts read (0.21)
%% 0.34 (a message of another pack inside a field):
%% top     the scope is the message, not an item
%% taken   #{List => _}: lists of the message read first by the other pack of
%%         a layer (the outer pack's before an inner message, the inner
%%         message's after it); a group of the message for one of them is
%%         read and its items discarded and not counted
%% uncounted  reading such a group: its items are not counted, and a failed
%%         transform in them is not an error (rulings 21 and 22 of 0.34)
%% whole   a `length ... whole` line was read: hard is the length it states
%% inner_kind  the kind the inner pack selected
%% given   #{Key => _}: the keys the inner message gave (ruling 23 of 0.34)
-record(d, {msg, hard, pos = 0, model = #{}, lists = #{}, failed = [], env = #{},
            pack, named, static = #{}, pending = [], unit = bytes, counts = #{},
            kstart = 0,
            top = true, taken = #{}, uncounted = false, whole = false, inner_kind, given = #{}}).
%% kstart  the kind start of the kind being tested (0.33)

decode(#{common := Common, kinds := Kinds, has_kinds := HasKinds, name := Name} = Pack, Bytes) ->
    Msg = gt_bits:open(gt_engine:unwire(Pack, Bytes), maps:get(bit_order, Pack)),
    D0 = #d{msg = Msg, hard = gt_bits:bit_size(Msg), pack = Pack,
            named = maps:get(presence_named, Pack),
            static = maps:get(presence_static, Pack, #{}),
            taken = maps:get(shadow, Pack, #{})},
    D1 = lines(Common, none, D0),
    {Kind, D2} = case HasKinds of
                     false -> {undefined, D1};
                     true ->
                         {K, Dk} = kind(Kinds, none, D1),
                         {{Name, K}, Dk}
                 end,
    %% the failed keys of an inner message are settled by the outer decode,
    %% which may read another line of the key (ruling 23 of 0.34)
    case is_map_key(shadow, Pack) of
        true -> ok;
        false -> check_failed(D2)
    end,
    case D2#d.pending of
        [] -> ok;
        [{_, B} | _] -> malformed(D2, "presence bit ~p is 1 and no if block of the lines read names it", [B])
    end,
    %% the end of an inner message (ruling 13 of 0.34): the length it states,
    %% else the cursor, in whole bytes
    End = case D2#d.whole of
              true -> D2#d.hard;
              false -> (D2#d.pos + 7) div 8 * 8
          end,
    gt_engine:inner_end(Pack, End, gt_bits:bit_size(Msg)),
    #{model => D2#d.model, lists => D2#d.lists, failed => D2#d.failed, residue => [], src => Name, kind => Kind,
      inner_kind => D2#d.inner_kind}.

%% A key whose every line failed its transform fails the decode.
check_failed(#d{uncounted = true}) -> ok;
check_failed(#d{failed = Failed, model = Model, pack = Pack}) ->
    case [KL || {K, _} = KL <- lists:reverse(Failed), not maps:is_key(K, Model)] of
        [] -> ok;
        Bad ->
            %% raised when the decode ends, so that the limit on list items
            %% wins over it (ruling 7f of 0.11)
            gt_engine:record_failure(Pack, "failed fields: ~s",
                                     [lists:join(", ", [[K, " of ", L, " bits"] || {K, L} <- Bad])])
    end.

malformed(#d{pack = Pack}, Fmt, Args) ->
    gt_engine:conv_error('malformed-wire', Pack, Fmt, Args).

%% The first kind, in order, whose `when` lines all hold at the cursor; the
%% decode continues after them -> {KindName, D}.
kind([], _Ext, #d{pack = Pack}) ->
    gt_engine:conv_error('no-kind', Pack, "no kind's when lines hold at the cursor", []);
kind([#{name := Name, lines := Lines} | Rest], Ext, D) ->
    {Whens, Body} = lists:splitwith(fun(L) -> element(1, L) =:= swhen end, Lines),
    %% the kind start, from which a `when ... at` counts (0.33)
    KS = D#d.pos,
    case whens(Whens, KS, Ext, D#d{kstart = KS}, []) of
        false -> kind(Rest, Ext, D);
        {Pos, Sets} -> {Name, lines(Body, Ext, set_as(Sets, D#d{pos = Pos}))}
    end.

%% A `when` any of whose bits lies beyond the input does not hold
%% -> false | {Pos after the lines, [{Key, Len, Bits}]}: the keys the
%% `when ... as` lines bind (0.30), set only once every line holds
%% (ruling 12).
whens([], Pos, _Ext, _D, Sets) -> {Pos, lists:reverse(Sets)};
%% A `when ... at <offset>` (0.33) reads at the kind start plus the offset
%% and does not move the cursor; past the input or the extent it does not
%% hold (rulings 6 and 7).
whens([{swhen, Len, Val, As, At} | Rest], Pos, Ext, D, Sets) ->
    {From, Next} = case At of
                       none -> {Pos, Pos + Len};
                       Off -> {D#d.kstart + Off, Pos}
                   end,
    case avail(From, Len, Ext, D) =:= ok of
        true ->
            U = gt_bits:read(D#d.msg, From, Len),
            case gt_pack:when_match(U, Val) of
                true when As =:= none -> whens(Rest, Next, Ext, D, Sets);
                true -> whens(Rest, Next, Ext, D, [{As, Len, U} | Sets]);
                false -> false
            end;
        false -> false
    end.

%% The key of a `when ... as` holds the bits as `uint` reads them (ruling 7
%% of 0.30).
set_as(Sets, D) ->
    lists:foldl(fun({Key, Len, U}, Acc) ->
                        set_key({Key, none}, U, Len, uint, integer_to_binary(Len), false, Acc)
                end, D, Sets).

%% Are Len bits at Pos inside the input, or inside the `length` extent that
%% ends at Ext? A line that starts at or after the end of an extent reads as
%% absent; one that straddles the end is `short`.
avail(Pos, Len, none, #d{hard = Hard}) ->
    case Pos + Len =< Hard of
        true -> ok;
        false -> short
    end;
avail(Pos, Len, End, _D) ->
    if Pos >= End -> absent;
       Pos + Len =< End -> ok;
       true -> short
    end.

need(Pos, Len, Ext, D) ->
    case avail(Pos, Len, Ext, D) of
        short when Ext =:= none ->
            malformed(D, "the input ends inside a line that needs ~p bits at bit ~p", [Len, Pos]);
        short ->
            malformed(D, "a line that needs ~p bits at bit ~p runs past its length extent", [Len, Pos]);
        Other -> Other
    end.

limit(none, #d{hard = Hard}) -> Hard;
limit(End, _D) -> End.

lines(Lines, Ext, D) -> lists:foldl(fun(L, Acc) -> line(L, Ext, Acc) end, D, Lines).

line({sfield, Keys, {uper, Loc}, Tr, LenT, _, _, _, _With}, Ext, D) ->
    case at_end(Ext, D) of
        true -> D;
        false ->
            {Res, D1} = uread(Loc, Ext, D),
            lists:foldl(fun(KV, Acc) -> set_ukey(KV, Res, Tr, LenT, Acc) end, D1, Keys)
    end;
line({uext, Body}, Ext, D) ->
    case at_end(Ext, D) of
        true -> D;
        false ->
            {E, D1} = rd(1, Ext, D),
            D2 = lines(Body, Ext, D1),
            case E of
                0 -> D2;
                1 -> skip_additions(Ext, D2)
            end
    end;
line({uchoice, N, IsExt, Alts}, Ext, D) ->
    case at_end(Ext, D) of
        true -> D;
        false ->
            {E, D1} = case IsExt of
                          true -> rd(1, Ext, D);
                          false -> {0, D}
                      end,
            case E of
                1 ->
                    %% an extension alternative: its index and an open type, skipped
                    case nsn(Ext, D1) of
                        {{bad, Why}, _} ->
                            gt_engine:conv_error('transform-decode', D#d.pack,
                                                 "the index of an extension alternative: ~s", [Why]);
                        {{ok, _}, D2} -> open_type(Ext, D2)
                    end;
                0 ->
                    {I, D2} = cwn(0, N - 1, Ext, D1),
                    case lists:keyfind(I, 1, Alts) of
                        {_, Body} -> lines(Body, Ext, D2);
                        false -> malformed(D, "choice index ~p has no alt", [I])
                    end
            end
    end;
%% `until:<code>` (0.22): characters of the set up to the terminator, which
%% is consumed. A field starting at the end of a `length` extent is absent;
%% no terminator before the end of the extent or input, or more than
%% 2040 / w characters, is malformed-wire, and wins over a bad character
%% (rulings 4, 5 and 8 of 0.22).
line({sfield, Keys, {until, Code}, {chars, Set} = Tr, LenT, _, _, _, _With}, Ext, D) ->
    case at_end(Ext, D) of
        true -> D;
        false ->
            W = gt_engine:chars_width(Set),
            {Codes, D1} = until_scan(Code, W, 2040 div W, limit(Ext, D), D, []),
            lists:foldl(fun(KV, Acc) ->
                                set_key_with(KV, fun() -> gt_engine:until_text(Set, Codes) end,
                                             Tr, LenT, Acc)
                        end, D1, Keys)
    end;
line({sfield, Keys, Len, Tr, LenT, Swap, Trim, Absent, _With}, Ext, #d{pos = Pos} = D) ->
    case need(Pos, Len, Ext, D) of
        absent -> D;
        ok ->
            U0 = gt_bits:read(D#d.msg, Pos, Len),
            U = case Swap of
                    true -> gt_engine:swap_bytes(U0, Len);
                    false -> U0
                end,
            %% a sentinel (Version 0.9): no key of the line is set
            D1 = case Absent =/= none andalso lists:member(U, Absent) of
                     true -> D;
                     false ->
                         lists:foldl(fun(KV, Acc) -> set_key(KV, U, Len, Tr, LenT, Trim, Acc) end,
                                     D, Keys)
                 end,
            D1#d{pos = Pos + Len}
    end;
line({sconst, Len, _}, Ext, D) -> skip(Len, Ext, D);
line({pad, Len}, Ext, D) -> skip(Len, Ext, D);
%% `align` stops at the end of the input or extent without error
line({align, N}, Ext, #d{pos = Pos} = D) ->
    D#d{pos = max(Pos, min(Pos + (N - Pos rem N) rem N, limit(Ext, D)))};
line({swhen, _, _, _, _} = L, Ext, #d{pos = Pos, pack = Pack} = D) ->
    case whens([L], Pos, Ext, D, []) of
        false -> gt_engine:conv_error('no-kind', Pack, "a common when does not hold", []);
        {Pos1, Sets} -> set_as(Sets, D#d{pos = Pos1})
    end;
line({presence, Id, fx}, Ext, #d{pos = Pos} = D) ->
    case need(Pos, 8, Ext, D) of
        absent -> D#d{env = (D#d.env)#{Id => []}};
        ok ->
            {Bits, Pos1} = fx_octets(Pos, 0, Ext, D, []),
            present(Id, Bits, D#d{pos = Pos1})
    end;
line({presence, Id, N}, Ext, #d{pos = Pos, msg = Msg} = D) ->
    case need(Pos, N, Ext, D) of
        absent -> D#d{env = (D#d.env)#{Id => []}};
        ok ->
            Bits = [K || K <- lists:seq(1, N), gt_bits:read(Msg, Pos + K - 1, 1) =:= 1],
            present(Id, Bits, D#d{pos = Pos + N})
    end;
line({ifb, Conds, Body}, Ext, D) ->
    case holds(Conds, D#d.env) of
        true -> lines(Body, Ext, D);
        false -> D
    end;
line({opt, Body}, Ext, D) ->
    case bit(Ext, D) of
        absent -> D;
        {0, D1} -> D1;
        {1, D1} -> lines(Body, Ext, D1)
    end;
line({chain, First, Parts, EndsFx}, Ext, D) ->
    parts(Parts, EndsFx, Ext, lines(First, Ext, D));
line({len, Len, Unit, Plus, Body}, Ext, #d{pos = Pos} = D) ->
    case need(Pos, Len, Ext, D) of
        absent -> D;
        ok ->
            Count = gt_bits:read(D#d.msg, Pos, Len) - Plus,
            Start = Pos + Len,
            End = Start + case Unit of
                              bytes -> Count * 8;
                              bits -> Count
                          end,
            case Count < 0 of
                true -> malformed(D, "the length at bit ~p states less than nothing", [Pos]);
                false -> ok
            end,
            case End =< limit(Ext, D) of
                true -> ok;
                false -> malformed(D, "the length at bit ~p reaches beyond what holds it", [Pos])
            end,
            D1 = lines(Body, End, D#d{pos = Start, unit = Unit}),
            D1#d{pos = End, unit = D#d.unit}   % what no line read is skipped
    end;
line({lenwhole, Len, Plus}, Ext, #d{pos = Pos} = D) ->
    case need(Pos, Len, Ext, D) of
        absent -> D;
        ok ->
            Bits = (gt_bits:read(D#d.msg, Pos, Len) - Plus) * 8,
            case Bits > D#d.hard of
                true -> malformed(D, "the input is shorter than the length it states", []);
                false -> ok
            end,
            case Bits < Pos + Len of
                true -> malformed(D, "the stated length is shorter than what was already read", []);
                false -> ok
            end,
            D#d{pos = Pos + Len, hard = Bits, whole = true}  % input beyond it is ignored
    end;
%% a switch (0.20): the case the key's value selects, else the else lines
line({switch, Key, _Ref, Cases, Else}, Ext, #d{pack = Pack} = D) ->
    %% a key whose line failed its transform fails the decode (ruling 35)
    case [L || {K, L} <- D#d.failed, K =:= Key] of
        [LenT | _] when not is_map_key(Key, D#d.model) ->
            gt_engine:conv_error('transform-decode', Pack, "failed fields: ~s of ~s bits", [Key, LenT]);
        _ -> ok
    end,
    case select(Key, D#d.model, Cases, Else) of
        none -> gt_engine:conv_error('no-kind', Pack,
                                     "switch ~s: no case holds the key's value and there is no else", [Key]);
        #{lines := Ls, named := Named} ->
            %% the bits pending so far that the case's `if` lines name are
            %% satisfied (ruling 36: a case read later in the decode)
            lines(Ls, Ext, D#d{pending = [IB || IB <- D#d.pending, not lists:member(IB, Named)]})
    end;
%% a count (0.21): the number of items of the group that references it is
%% the value less `plus`; a value below `plus` fails here. A count line at
%% the end of a length extent leaves its group absent.
line({scount, Id, Len, Plus}, Ext, #d{pos = Pos, counts = Cs} = D) ->
    case need(Pos, Len, Ext, D) of
        absent -> D#d{counts = Cs#{Id => absent}};
        ok ->
            V = gt_bits:read(D#d.msg, Pos, Len),
            case V < Plus of
                true -> malformed(D, "the count at bit ~p is ~p, below its plus ~p", [Pos, V, Plus]);
                false -> D#d{pos = Pos + Len, counts = Cs#{Id => V - Plus}}
            end
    end;
%% 0.34: a list of the message the other pack of a layer read first keeps
%% its items; this group is read, its count checked against the limit
%% (ruling 7 of 0.34), and its items are discarded and not counted
line({sgroup, List, Mode, Body}, Ext, #d{top = true, taken = Taken} = D)
  when is_map_key(List, Taken) ->
    case group(Mode, Body, Ext, D#d{uncounted = true}, fun() -> ok end) of
        absent -> D;
        {_Items, D1} -> D1#d{uncounted = false}
    end;
%% `inner <format>` (0.34): the bytes from the cursor to the end of the
%% extent are one message of the inner pack, decoded into this entity
line({inner, Format, Partial}, Ext, #d{pos = Pos, pack = Pack} = D) ->
    Inner = try gt_engine:inner_pack(Pack, Format)
            catch error:{convert_error, _, _} = Err -> gt_engine:pass(Err)
            end,
    case Pos rem 8 of
        0 -> ok;
        _ -> malformed(D, "the inner message would start at bit ~p, inside a byte", [Pos])
    end,
    End = max(Pos, limit(Ext, D)),
    case End rem 8 of
        0 -> ok;
        _ -> malformed(D, "the extent of the inner message ends at bit ~p, inside a byte", [End])
    end,
    case End =< gt_bits:bit_size(D#d.msg) of
        true -> ok;
        false -> malformed(D, "the extent of the inner message ends beyond the input", [])
    end,
    Hex = gt_hex:bytes_to_hex(gt_bits:slice(D#d.msg, Pos, End)),
    IE = try gt_engine:decode_inner(Inner#{shadow => D#d.lists, exact => not Partial}, Hex)
         catch error:{convert_error, Kind, _} = Err2:St ->
             %% among transform-decode errors the earliest in reading order:
             %% a field of the outer lines read so far that failed; an
             %% error that stops the decode is reported ahead of it
             case Kind of
                 'transform-decode' -> check_failed(D);
                 _ -> ok
             end,
             erlang:raise(error, Err2, St)
         end,
    %% the first value read is kept: the outer keys read so far win
    Lists = D#d.lists,
    {Kept, Dropped} = lists:partition(fun({L, _}) -> not maps:is_key(L, Lists) end,
                                      maps:to_list(maps:get(lists, IE, #{}))),
    [gt_engine:items_release(gt_engine:items_held(Is)) || {_, Is} <- Dropped],
    KeptMap = maps:from_list(Kept),
    D#d{pos = End, model = maps:merge(maps:get(model, IE), D#d.model),
        failed = maps:get(failed, IE, []) ++ D#d.failed,
        given = maps:without(maps:keys(D#d.model), maps:get(model, IE)),
        lists = maps:merge(Lists, KeptMap), taken = maps:merge(D#d.taken, KeptMap),
        inner_kind = maps:get(kind, IE, undefined)};
line({sgroup, List, Mode, Body}, Ext, D) ->
    %% a later group of a list replaces the items of an earlier one; those
    %% are no longer counted against the limit (ruling 7g of 0.11)
    Release = fun() when D#d.uncounted -> ok;
                 () ->
                      case maps:find(List, D#d.lists) of
                          {ok, Old} -> gt_engine:items_release(gt_engine:items_held(Old));
                          error -> ok
                      end
              end,
    case group(Mode, Body, Ext, D, Release) of
        absent -> D;
        {Items, D1} -> D1#d{lists = (D1#d.lists)#{List => Items}}
    end.

skip(Len, Ext, #d{pos = Pos} = D) ->
    case need(Pos, Len, Ext, D) of
        absent -> D;
        ok -> D#d{pos = Pos + Len}
    end.

%% One bit at the cursor -> absent | {Bit, D}.
bit(Ext, #d{pos = Pos} = D) ->
    case need(Pos, 1, Ext, D) of
        absent -> absent;
        ok -> {gt_bits:read(D#d.msg, Pos, 1), D#d{pos = Pos + 1}}
    end.

set_key(KV, U, Len, Tr, LenT, Trim, #d{pack = Pack} = D) ->
    set_key_with(KV, fun() ->
                             V = gt_engine:bits_decode(Tr, U, Len, maps:get(bit_order, Pack)),
                             case Trim of
                                 true -> gt_engine:trim(Tr, V);
                                 false -> V
                             end
                     end, Tr, LenT, D).

%% Set a key from the value Decode() gives, through `via` and `typemap`.
set_key_with({Key, Via}, Decode, Tr, LenT, #d{model = Model, pack = Pack} = D) ->
    case maps:is_key(Key, Model) of
        %% the inner message gave the key: a value with no table entry still
        %% fails the decode (ruling 23 of 0.34)
        true when D#d.top, Via =/= none, is_map_key(Key, D#d.given) ->
            D1 = set_key_with({Key, Via}, Decode, Tr, LenT, D#d{model = maps:remove(Key, Model)}),
            D1#d{model = Model};
        true -> D;
        false ->
            try Decode() of
                V0 ->
                    %% a value with no table entry fails the decode when it
                    %% ends, so that the limit on list items read later still
                    %% wins (ruling 7f of 0.11)
                    try gt_engine:via_decode({Via, false, false, false, none, none}, V0, Tr, Key, LenT, Pack) of
                        V1 -> D#d{model = Model#{Key => gt_engine:typemap_decode(Key, V1, Pack)}}
                    catch
                        error:{convert_error, 'transform-decode', Msg} ->
                            gt_engine:record_failure_msg(Msg),
                            %% a switch on the key fails (ruling 35 of 0.20)
                            D#d{failed = [{Key, LenT} | D#d.failed]}
                    end
            catch
                _:_ -> D#d{failed = [{Key, LenT} | D#d.failed]}
            end
    end.

%% The codes before an `until:` terminator -> {Codes, D after the
%% terminator}.
until_scan(Code, W, Max, Limit, #d{pos = Pos} = D, Acc) ->
    case Pos + W =< Limit of
        false -> malformed(D, "an until: field finds no terminator before the end of its extent", []);
        true ->
            case gt_bits:read(D#d.msg, Pos, W) of
                Code -> {lists:reverse(Acc), D#d{pos = Pos + W}};
                _ when length(Acc) >= Max ->
                    malformed(D, "an until: field reads more than 2040 bits before its terminator", []);
                C -> until_scan(Code, W, Max, Limit, D#d{pos = Pos + W}, [C | Acc])
            end
    end.

%% Octets of 7 presence bits and an extension bit -> {[BitNumber], Pos}.
fx_octets(Pos, Base, Ext, #d{msg = Msg} = D, Acc) ->
    case need(Pos, 8, Ext, D) of
        absent -> malformed(D, "the presence octets run to the end of their length extent", []);
        ok -> ok
    end,
    Acc1 = [Base + K || K <- lists:seq(1, 7), gt_bits:read(Msg, Pos + K - 1, 1) =:= 1] ++ Acc,
    case gt_bits:read(Msg, Pos + 7, 1) of
        1 -> fx_octets(Pos + 8, Base + 7, Ext, D, Acc1);
        0 -> {Acc1, Pos + 8}
    end.

%% A presence bit that is 1 and that no `if` block names: the message holds
%% a part the pack does not describe.
present(Id, Bits, #d{named = Named, env = Env} = D) ->
    case Bits -- maps:get(Id, Named) of
        [] ->
            %% a bit only `if` lines in cases name counts when one of those
            %% cases is read
            Pending = [{Id, B} || B <- Bits -- maps:get(Id, D#d.static, [])],
            D#d{env = Env#{Id => Bits}, pending = Pending ++ D#d.pending};
        [B | _] -> malformed(D, "presence bit ~p is 1 and no if block names it", [B])
    end.

%% The case of a switch the value of Key selects (as canonical text), else
%% the else -> Case | none. An absent key selects the else.
select(Key, Values, Cases, Else) ->
    case maps:find(Key, Values) of
        {ok, readback_failed} -> failed;
        {ok, V} ->
            C = gt_num:canon(V),
            case [Case || #{vals := Vals} = Case <- Cases, lists:member(C, Vals)] of
                [Case | _] -> Case;
                [] -> Else
            end;
        error -> Else
    end.

holds(Conds, Env) ->
    lists:all(fun({Id, Bit, Neg}) -> lists:member(Bit, maps:get(Id, Env, [])) =/= Neg end, Conds).

%% The parts of a chain after the first: each follows an fx bit, and a 0 bit
%% ends the chain. The bit of a closing fx line must be 0.
parts([], false, _Ext, D) -> D;
parts([], true, Ext, D) ->
    case bit(Ext, D) of
        absent -> D;
        {0, D1} -> D1;
        {1, D1} -> malformed(D1, "the last fx bit of a chain is 1", [])
    end;
parts([Part | Rest], EndsFx, Ext, D) ->
    case bit(Ext, D) of
        absent -> D;
        {0, D1} -> D1;
        {1, D1} -> parts(Rest, EndsFx, Ext, lines(Part, Ext, D1))
    end.

%% The items of a group -> absent | {[Item], D}.
group({count, Len}, Body, Ext, #d{pos = Pos} = D, Release) ->
    case need(Pos, Len, Ext, D) of
        absent -> absent;
        ok ->
            N = gt_bits:read(D#d.msg, Pos, Len),
            Pos1 = Pos + Len,
            %% the count is compared with the limit before any item is read
            Release(),
            reserve(N, D),
            case N > limit(Ext, D) - Pos1 of
                true -> malformed(D, "a count of ~p is larger than the bits left", [N]);
                false -> ok
            end,
            lists:mapfoldl(fun(_, Acc) -> item_lines(Body, Ext, Acc) end, D#d{pos = Pos1},
                           lists:seq(1, N))
    end;
group({size, Lb, Ub}, Body, Ext, D, Release) ->
    case at_end(Ext, D) of
        true -> absent;
        false ->
            {N, D1} = cwn(Lb, Ub, Ext, D),
            uitems(N, Body, Ext, D1, Release)
    end;
group({size, unc}, Body, Ext, D, Release) ->
    case at_end(Ext, D) of
        true -> absent;
        false ->
            {N, D1} = ldet(Ext, D),
            uitems(N, Body, Ext, D1, Release)
    end;
group({countref, Id}, Body, Ext, #d{pos = Pos} = D, Release) ->
    case {avail(Pos, 0, Ext, D), maps:get(Id, D#d.counts, absent)} of
        {absent, _} -> absent;
        {_, absent} -> absent;
        {_, N} ->
            %% the count is compared with the limit before any item is read
            %% (ruling 7d of 0.11), and with the bits left at the group
            %% (ruling 14 of 0.8, ruling 20 of 0.21)
            Release(),
            reserve(N, D),
            case N > limit(Ext, D) - Pos of
                true -> malformed(D, "a count of ~p is larger than the bits left", [N]);
                false -> ok
            end,
            lists:mapfoldl(fun(_, Acc) -> item_lines(Body, Ext, Acc) end, D, lists:seq(1, N))
    end;
%% two counts on one list (0.31): absent when the group is not reached or
%% either count was not read; else the two numbers must be equal (exact
%% integers), then the agreed number is checked as one count's is (ruling 4)
group({countref2, IdA, IdB}, Body, Ext, #d{pos = Pos} = D, Release) ->
    Cs = D#d.counts,
    case {avail(Pos, 0, Ext, D), maps:get(IdA, Cs, absent), maps:get(IdB, Cs, absent)} of
        {absent, _, _} -> absent;
        {_, absent, _} -> absent;
        {_, _, absent} -> absent;
        {_, N, N} -> group({countref, IdA}, Body, Ext, D, Release);
        {_, Na, Nb} ->
            malformed(D, "the two counts of the group at bit ~p disagree: ~p and ~p items", [Pos, Na, Nb])
    end;
%% items while at least 8 bits remain in a byte-counted extent, 1 in a
%% bit-counted one; fewer are padding. At the end of the extent the list is
%% present and empty (ruling 3 of 0.21).
group(rest, Body, Ext, #d{unit = Unit} = D, Release) ->
    Min = case Unit of
              bytes -> 8;
              bits -> 1
          end,
    Release(),
    rest(Body, Ext, limit(Ext, D), Min, D, []);
group(last, Body, Ext, D, Release) ->
    case bit(Ext, D) of
        absent -> absent;
        {B, D1} -> Release(), last(B, Body, Ext, D1, [])
    end;
group(while, Body, Ext, D, Release) ->
    case bit(Ext, D) of
        absent -> absent;
        {B, D1} -> Release(), while(B, Body, Ext, D1, [])
    end;
group(more, Body, Ext, D, Release) ->
    case bit(Ext, D) of
        absent -> absent;
        {B, D1} -> Release(), more(B, Body, Ext, D1, [])
    end;
group(fx, Body, Ext, D, Release) ->
    case avail(D#d.pos, 0, Ext, D) of
        absent -> absent;
        _ -> Release(), fx_items(Body, Ext, D, [])
    end.

%% A count is compared with the bits left before any item is read
%% (rulings 14 and 25 of 0.8).
uitems(N, Body, Ext, #d{pos = Pos} = D, Release) ->
    %% the count is compared with the limit before any item is read, as for
    %% `count` (ruling 7d of 0.11)
    Release(),
    reserve(N, D),
    case N > limit(Ext, D) - Pos of
        true -> malformed(D, "a count of ~p is larger than the bits left", [N]);
        false -> lists:mapfoldl(fun(_, Acc) -> item_lines(Body, Ext, Acc) end, D, lists:seq(1, N))
    end.

while(0, _Body, _Ext, D, Acc) -> {lists:reverse(Acc), D};
while(1, Body, Ext, D, Acc) ->
    {Item, D1} = item(Body, Ext, D),
    case bit(Ext, D1) of
        absent -> {lists:reverse([Item | Acc]), D1};
        {B, D2} -> while(B, Body, Ext, D2, [Item | Acc])
    end.

more(More, Body, Ext, D, Acc) ->
    {Item, D1} = item(Body, Ext, D),
    case More of
        0 -> {lists:reverse([Item | Acc]), D1};
        1 ->
            %% an indicator bit at the end of a `length` extent reads as 0:
            %% the item it stands before is the last
            case bit(Ext, D1) of
                absent -> more(0, Body, Ext, D1, [Item | Acc]);
                {B, D2} -> more(B, Body, Ext, D2, [Item | Acc])
            end
    end.

rest(Body, Ext, Limit, Min, #d{pos = Pos} = D, Acc) when Limit - Pos >= Min ->
    {Item, D1} = item(Body, Ext, D),
    case D1#d.pos =:= Pos of
        true -> malformed(D, "an item of a rest group at bit ~p reads no bits", [Pos]);
        false -> rest(Body, Ext, Limit, Min, D1, [Item | Acc])
    end;
rest(_Body, _Ext, Limit, _Min, D, Acc) ->
    {lists:reverse(Acc), D#d{pos = max(Limit, D#d.pos)}}.

%% an indicator after the first at the end of a length extent (ruling 13)
last(B, Body, Ext, D, Acc) ->
    {Item, D1} = item(Body, Ext, D),
    case B of
        1 -> {lists:reverse([Item | Acc]), D1};
        0 ->
            case bit(Ext, D1) of
                absent -> malformed(D1, "the list ends at its length extent before its last item", []);
                {B1, D2} -> last(B1, Body, Ext, D2, [Item | Acc])
            end
    end.

fx_items(Body, Ext, D, Acc) ->
    {Item, D1} = item(Body, Ext, D),
    case bit(Ext, D1) of
        {1, D2} -> fx_items(Body, Ext, D2, [Item | Acc]);
        {0, D2} -> {lists:reverse([Item | Acc]), D2};
        absent -> {lists:reverse([Item | Acc]), D1}
    end.

%% A count is compared with the limit before any item is read (7d of 0.11);
%% one in a discarded list is not taken from it (ruling 22 of 0.34).
reserve(N, #d{uncounted = true, pack = Pack}) -> gt_engine:items_check(N, Pack);
reserve(N, #d{pack = Pack}) -> gt_engine:items_reserve(N, Pack).

%% One item at the cursor: the lines common to every item, then the kind
%% its `when` lines select.
item(Body, Ext, #d{uncounted = true} = D) -> item_lines(Body, Ext, D);
item(Body, Ext, D) ->
    gt_engine:items_reserve(1, D#d.pack),
    item_lines(Body, Ext, D).

item_lines(#{lines := Common, kinds := Kinds}, Ext, #d{model = M, lists = Ls, failed = F, top = Top} = D) ->
    D1 = lines(Common, Ext, D#d{model = #{}, lists = #{}, failed = [], top = false}),
    {Item, D2} =
        case Kinds of
            [] -> {#{model => D1#d.model, lists => D1#d.lists}, D1};
            _ ->
                {K, Dk} = kind(Kinds, Ext, D1),
                {#{model => Dk#d.model, lists => Dk#d.lists,
                   kind => {maps:get(name, D#d.pack), K}}, Dk}
        end,
    check_failed(D2),
    {Item, D2#d{model = M, lists = Ls, failed = F, top = Top}}.

%% ---- ASN.1 unaligned PER (0.19) ----
-define(I64MIN, -9223372036854775808).
-define(I64MAX, 9223372036854775807).

%% A UPER line that starts at or after the end of a `length` extent reads
%% as absent, as a line of 0.8 does.
at_end(none, _D) -> false;
at_end(End, #d{pos = Pos}) -> Pos >= End.

%% Len bits at the cursor; past the input or the extent is malformed-wire.
rd(0, _Ext, D) -> {0, D};
rd(Len, Ext, #d{pos = Pos} = D) ->
    case need(Pos, Len, Ext, D) of
        ok -> {gt_bits:read(D#d.msg, Pos, Len), D#d{pos = Pos + Len}};
        absent -> malformed(D, "a UPER value at bit ~p runs past its length extent", [Pos])
    end.

bitlen(0) -> 0;
bitlen(N) -> 1 + bitlen(N bsr 1).

%% A constrained whole number in Lb..Ub; a value above Ub is malformed-wire.
cwn(Lb, Ub, Ext, D) ->
    R = Ub - Lb,
    {Off, D1} = rd(bitlen(R), Ext, D),
    case Off > R of
        true -> malformed(D, "a value of ~p lies above its constraint ~p..~p", [Lb + Off, Lb, Ub]);
        false -> {Lb + Off, D1}
    end.

%% A length determinant; a fragmented length is malformed-wire.
ldet(Ext, D) ->
    case rd(1, Ext, D) of
        {0, D1} -> rd(7, Ext, D1);
        {1, D1} ->
            case rd(1, Ext, D1) of
                {0, D2} -> rd(14, Ext, D2);
                {1, _} -> malformed(D, "a fragmented length at bit ~p", [D#d.pos])
            end
    end.

octs(L, Ext, D) ->
    {V, D1} = rd(8 * L, Ext, D),
    {<<V:(8 * L)>>, D1}.

%% An integer in a counted number of octets -> {{ok, V} | {bad, Why}, D}.
%% The octets must be in the input; 0 octets is malformed-wire; more than 8
%% is a transform failure (ruling 5 of 0.19).
int_octets(Signed, Ext, D) ->
    {L, D1} = ldet(Ext, D),
    {Bin, D2} = octs(L, Ext, D1),
    if
        L =:= 0 -> malformed(D, "an integer of zero octets at bit ~p", [D#d.pos]);
        L > 8 -> {{bad, "an integer of more than 8 octets"}, D2};
        Signed -> <<X:L/signed-unit:8>> = Bin, {{ok, X}, D2};
        true -> {{ok, binary:decode_unsigned(Bin)}, D2}
    end.

%% A normally small non-negative whole number.
nsn(Ext, D) ->
    case rd(1, Ext, D) of
        {0, D1} ->
            {V, D2} = rd(6, Ext, D1),
            {{ok, V}, D2};
        {1, D1} -> int_octets(false, Ext, D1)
    end.

open_type(Ext, D) ->
    {L, #d{pos = Pos} = D1} = ldet(Ext, D),
    case need(Pos, 8 * L, Ext, D1) of
        ok -> D1#d{pos = Pos + 8 * L};
        absent -> malformed(D, "an open type runs past its length extent", [])
    end.

%% The extension additions of an `ext` block: their number (ruling 16),
%% the presence bits, an open type for each bit that is 1; all skipped.
skip_additions(Ext, D) ->
    {M, D1} = case rd(1, Ext, D) of
                  {0, Dx} ->
                      {V, Dy} = rd(6, Ext, Dx),
                      {V + 1, Dy};
                  {1, Dx} -> ldet(Ext, Dx)
              end,
    {Bits, D2} = rd(M, Ext, D1),
    Present = length([1 || <<1:1>> <= <<Bits:M>>]),
    lists:foldl(fun(_, Acc) -> open_type(Ext, Acc) end, D2, lists:seq(1, Present)).

%% The value of a UPER locator -> {{ok, Value} | {bad, Why}, D}.
uread({int, Lb, Ub, false}, Ext, D) ->
    {V, D1} = cwn(Lb, Ub, Ext, D),
    {{ok, V}, D1};
uread({int, Lb, Ub, true}, Ext, D) ->
    case rd(1, Ext, D) of
        {0, D1} -> uread({int, Lb, Ub, false}, Ext, D1);
        {1, D1} -> int_octets(true, Ext, D1)
    end;
uread({semi, Lb}, Ext, D) ->
    case int_octets(false, Ext, D) of
        {{ok, U}, D1} when Lb + U > ?I64MAX ->
            {{bad, "a value beyond signed 64 bits"}, D1};
        {{ok, U}, D1} -> {{ok, Lb + U}, D1};
        Bad -> Bad
    end;
uread(unc, Ext, D) -> int_octets(true, Ext, D);
uread({enum, N, false}, Ext, D) ->
    {V, D1} = cwn(0, N - 1, Ext, D),
    {{ok, V}, D1};
uread({enum, N, true}, Ext, D) ->
    case rd(1, Ext, D) of
        {0, D1} -> uread({enum, N, false}, Ext, D1);
        {1, D1} ->
            case nsn(Ext, D1) of
                {{ok, K}, D2} when N + K > ?I64MAX -> {{bad, "an index beyond signed 64 bits"}, D2};
                {{ok, K}, D2} -> {{ok, N + K}, D2};
                Bad -> Bad
            end
    end;
uread({chars, Lb, Ub}, Ext, D) ->
    {C, D1} = cwn(Lb, Ub, Ext, D),
    uchars(C, Ext, D1);
uread({chars, unc}, Ext, D) ->
    {C, D1} = ldet(Ext, D),
    uchars(C, Ext, D1);
uread({octets, Lb, Ub}, Ext, D) ->
    {C, D1} = cwn(Lb, Ub, Ext, D),
    {Bin, D2} = octs(C, Ext, D1),
    {{ok, Bin}, D2};
uread({octets, unc}, Ext, D) ->
    {C, D1} = ldet(Ext, D),
    {Bin, D2} = octs(C, Ext, D1),
    {{ok, Bin}, D2}.

uchars(C, Ext, D) ->
    {V, D1} = rd(7 * C, Ext, D),
    {{ok, << <<X>> || <<X:7>> <= <<V:(7 * C)>> >>}, D1}.

set_ukey({Key, Via}, Res, Tr, LenT, #d{model = Model, pack = Pack} = D) ->
    case maps:is_key(Key, Model) of
        true -> D;
        false ->
            try uvalue(Res, Tr) of
                V0 ->
                    V1 = gt_engine:via_decode({Via, false, false, false, none, none}, V0, Tr, Key, LenT, Pack),
                    D#d{model = Model#{Key => gt_engine:typemap_decode(Key, V1, Pack)}}
            catch
                _:_ -> D#d{failed = [{Key, LenT} | D#d.failed]}
            end
    end.

%% The transform on a UPER value: integers are the value itself (not raw
%% bits), the scales v * f + o.
uvalue({bad, Why}, _Tr) -> error({uper, Why});
uvalue({ok, V}, uint) when is_integer(V) -> V;
uvalue({ok, V}, twos) when is_integer(V) -> V;
uvalue({ok, V}, {uscale, F, O}) when is_integer(V) -> uscale(V, F, O);
uvalue({ok, V}, {sscale, F, O}) when is_integer(V) -> uscale(V, F, O);
uvalue({ok, B}, ascii) when is_binary(B) -> B;
uvalue({ok, B}, hex) when is_binary(B) -> gt_hex:bytes_to_hex(B);
uvalue({ok, B}, utf8) when is_binary(B) ->
    B = unicode:characters_to_binary(B, utf8, utf8).

%% in doubles: v * factor (or v * num / den), then + offset
uscale(V, {dec, F}, O) -> float(V) * F + O;
uscale(V, {frac, Num, Den}, O) -> float(V) * Num / Den + O.

%% ===================================================================
%% encode
%% ===================================================================
%% Because a presence bit is written before the blocks that set it, a scope
%% is laid out in two passes: at a `presence` line the lines after it are
%% scanned for the `if` blocks that name it and have content; then they are
%% written. Src = #{model, lists, defaults}: what a scope is written from;
%% for the scan also `wrote` and `env` (below).
%% segs: [{Pos, Len, Value} | {whole, Pos, Len, Plus}], bits not named are 0.
%% wrote: #{Key => Value}, what decode would read back from the field lines
%%        written so far in the scope; a `switch` (0.20) selects from it.
%% Settling (rulings 33, 34 and 37 of 0.20): a presence, `opt` or `fx` bit
%% may be computed before the key of a switch it depends on is written, so
%% the scan predicts that switch's case. A switch is identified by
%% {Ref, Path}, Path the items it stands in ({List, Index}, innermost
%% first).
%% path    the items the scope being written stands in
%% forced  #{SwitchId => CaseIndex}: the cases the scan assumes (from the
%%         previous pass); a switch not in it is predicted from `wrote`
%% The cases a pass selects from the bits it writes are collected in the
%% process dictionary (gt_seq_actual), so that a pass that fails still
%% tells which cases it selected: #{SwitchId => CaseIndex}, 0 the else.
%% icount  #{{Path, List} => items written so far}
%% 0.21:
%% counts  #{CountId => Pos}: where the latest count line of that id was
%%         written; its value is filled in when the message is finished
%% cvals   #{Pos => Items}: the items of the group a count at Pos counts
%% rest_hit  a `rest` group was written in the current extent since the
%%         item of an outer `rest` group began (ruling 35)
%% unit, starts  how the innermost extent is counted (bytes | bits), and the
%%         first bits of the `rest` items written in it, checked against
%%         its byte-padded end when it is laid out (rulings 4, 21 and 34)
-record(e, {pos = 0, segs = [], env = #{}, wrote = #{}, pack,
            path = [], forced = #{}, icount = #{},
            counts = #{}, cvals = #{}, unit = bytes, starts = [], rest_hit = false,
            held = [], wins = []}).
%% 0.33:
%% held  [{Pos, Len}]: the bits of field lines that wrote a key the scope
%%       holds (ruling 12)
%% wins  [{Pos, Len, Value}], latest first: the windows of `when ... at`
%%       lines written over the bits below them

-define(MAX_PASSES, 16).

encode(Pack, Lines, Defaults, Entity) ->
    Src = #{model => maps:get(model, Entity), lists => maps:get(lists, Entity, #{}),
            defaults => Defaults, entity => Entity},
    #e{pos = End, segs = Segs, cvals = CVals, starts = Starts, wins = Wins} =
        case maps:get(has_switch, Pack, false) of
            false -> escope(Lines, ncommon(Pack), Src, #e{pack = Pack});
            true -> settle(Lines, Src, Pack, #{}, 1)
        end,
    Bytes = case {End, maps:get(encoding, Pack)} of
                {0, uper} -> 1;                 % an empty UPER encoding is 00
                _ -> (End + 7) div 8            % a whole number of bytes
            end,
    %% under `armor sixbit` the message is the End bits the cursor reached,
    %% not rounded to a byte (0.14); `length ... whole` is refused there
    M0 = case maps:get(armor, Pack) of
             sixbit -> gt_bits:new_bits(End, maps:get(bit_order, Pack));
             hex -> gt_bits:new(Bytes, maps:get(bit_order, Pack))
         end,
    %% ruling 4 of 0.21: the message stays counted in bytes, under armor
    %% too (ruling 43 of 0.21)
    check_starts(Starts, Bytes * 8, Pack),
    M1 = lists:foldl(
          fun({whole, Pos, Len, Plus}, Acc) ->
                  gt_bits:overwrite(Acc, Pos, Len, fits(Bytes + Plus, Len, Pack));
             %% a count holds its group's items plus n; n when the group was
             %% not written (ruling 30)
             ({count, Pos, Len, Plus}, Acc) ->
                  gt_bits:overwrite(Acc, Pos, Len, fits(maps:get(Pos, CVals, 0) + Plus, Len, Pack));
             ({Pos, Len, Val}, Acc) -> gt_bits:overwrite(Acc, Pos, Len, Val)
          end, M0, Segs),
    %% the windows of 0.33, in line order, over the bits below them
    M = lists:foldl(fun({P, L, V}, Acc) -> gt_bits:overwrite(Acc, P, L, V) end, M1, lists:reverse(Wins)),
    case maps:get(armor, Pack) of
        sixbit -> gt_engine:armor_out(gt_bits:to_bytes(M), End, Pack);
        hex -> gt_hex:bytes_to_hex(gt_bits:to_bytes(M))
    end.

%% Ruling 4 of 0.21 on encode: an item of a `rest` group in a byte-counted
%% extent starts with at least 8 bits left before the extent's byte-padded
%% end, or decode would not read it.
check_starts(Starts, End, Pack) ->
    case [S || S <- Starts, End - S < 8] of
        [] -> ok;
        [S | _] -> gt_engine:conv_error('transform-encode', Pack,
                                        "an item of a rest group at bit ~p starts fewer than 8 bits before the end of its extent",
                                        [S])
    end.

%% Encode again with the cases the last pass selected until every case the
%% scan assumed is the case selected from the bits written. A pass whose
%% assumptions did not hold is discarded with its errors; an encode error
%% is reported only from a pass whose assumptions held so far.
settle(_Lines, _Src, Pack, _Forced, N) when N > ?MAX_PASSES ->
    gt_engine:conv_error('transform-encode', Pack,
                         "the cases of the switches do not settle in ~p passes", [?MAX_PASSES]);
settle(Lines, Src, Pack, Forced, N) ->
    %% an inner message's encode (0.34) settles inside the outer's
    Outer = put(gt_seq_actual, #{}),
    Result = try escope(Lines, ncommon(Pack), Src, #e{pack = Pack, forced = Forced}) of
                 E -> {ok, E}
             catch
                 Class:Reason:Stack -> {error, Class, Reason, Stack}
             end,
    Actual = erase(gt_seq_actual),
    case Outer of
        undefined -> ok;
        _ -> put(gt_seq_actual, Outer)
    end,
    Held = Forced =:= maps:merge(Forced, Actual) andalso
        (N > 1 orelse Actual =:= #{}),
    case {Result, Held} of
        {{ok, E1}, true} -> E1;
        {{error, C, R, St}, true} -> erlang:raise(C, R, St);
        {_, false} ->
            Next = maps:merge(Forced, Actual),
            case Next =:= Forced of
                true -> case Result of
                            {ok, E2} -> E2;
                            {error, C, R, St} -> erlang:raise(C, R, St)
                        end;
                false -> settle(Lines, Src, Pack, Next, N + 1)
            end
    end.

fits(V, Len, _Pack) when V >= 0, V < (1 bsl Len) -> V;
fits(V, Len, Pack) ->
    gt_engine:conv_error('transform-encode', Pack,
                         "the count or length ~p does not fit its ~p bits", [V, Len]).

emit(Len, 0, #e{pos = Pos} = E) -> E#e{pos = Pos + Len};
emit(Len, Val, #e{pos = Pos, segs = Segs} = E) ->
    E#e{pos = Pos + Len, segs = [{Pos, Len, Val} | Segs]}.

elines([], _Src, E) -> E;
elines([L | Rest], Src, E) -> elines(Rest, Src, eline(L, Rest, Src, E)).

%% What the scan sees of the encode so far.
seen(Src, #e{wrote = W, env = Env, path = Path, forced = F}) ->
    Src#{wrote => W, env => Env, path => Path, forced => F}.

%% The case of a switch as the scan sees it: the one assumed for it, else
%% the one `wrote` selects.
predict(Key, Ref, Cases, Else, Src) ->
    case maps:find({Ref, maps:get(path, Src, [])}, maps:get(forced, Src, #{})) of
        {ok, 0} -> Else;
        {ok, I} -> lists:nth(I, Cases);
        error -> select(Key, maps:get(wrote, Src, #{}), Cases, Else)
    end.

case_index(Case, Cases) ->
    case [I || {I, C} <- lists:zip(lists:seq(1, length(Cases)), Cases), C =:= Case] of
        [I | _] -> I;
        [] -> 0
    end.

eline({sfield, Keys, {uper, Loc}, Tr, LenT, _, _, _, With} = L, _Rest, Src, #e{pack = Pack, wrote = Wrote} = E) ->
    %% a line suppressed by `with` (0.18) is a line whose key is absent and
    %% has no default: it writes what ruling 1 of 0.19 states for the locator
    Pieces = case pick(candidates(Keys, With, Src), Src) of
                 none -> uabsent(Loc);          % ruling 1 of 0.19
                 {Key, Via, Val} ->
                     gt_engine:guard_encode(
                       Pack, Key, LenT,
                       fun() ->
                               W = gt_engine:wire_value(Pack, Key, Tr, {Via, false, false, false, none, none}, Val),
                               uenc(Loc, Tr, W)
                       end)
             end,
    E1 = epieces(Pieces, E),
    %% a switch key on a UPER locator selects from the value decode would
    %% read back from these pieces (0.20)
    case maps:get(has_switch, Pack, false) of
        true -> E1#e{wrote = uread_back(L, Pieces, Wrote, Pack)};
        false -> E1
    end;
eline({uext, Body}, _Rest, Src, E) -> elines(Body, Src, emit(1, 0, E));
eline({uchoice, N, IsExt, Alts}, _Rest, Src, #e{pack = Pack} = E) ->
    {I, Body} = chosen(Alts, Src, Pack),
    E1 = case IsExt of
             true -> emit(1, 0, E);
             false -> E
         end,
    elines(Body, Src, emit(bitlen(N - 1), I, E1));
eline({sgroup, List, {size, Lb, Ub}, Body}, _Rest, Src, #e{pack = Pack} = E) ->
    Items = case maps:find(List, maps:get(lists, Src)) of
                {ok, Is} -> Is;
                error -> lists:duplicate(Lb, #{model => #{}, lists => #{}})
            end,
    C = length(Items),
    case C >= Lb andalso C =< Ub of
        true -> ok;
        false -> gt_engine:conv_error('transform-encode', Pack,
                                      "list ~s has ~p items, outside its size ~p..~p",
                                      [List, C, Lb, Ub])
    end,
    lists:foldl(fun(I, Acc) -> eitem(I, List, Body, Acc) end, emit(bitlen(Ub - Lb), C - Lb, E), Items);
eline({sgroup, List, {size, unc}, Body}, _Rest, Src, #e{pack = Pack} = E) ->
    Items = maps:get(List, maps:get(lists, Src), []),
    C = length(Items),
    case C < 16384 of
        true -> ok;
        false -> gt_engine:conv_error('transform-encode', Pack,
                                      "list ~s has ~p items: a fragmented length", [List, C])
    end,
    lists:foldl(fun(I, Acc) -> eitem(I, List, Body, Acc) end, epieces(ld(C), E), Items);
%% `until:` (0.22): the text's codes, then the terminator; an absent key
%% (no default) writes the terminator alone
eline({sfield, _, {until, _}, {chars, Set}, _, _, _, _, _} = L, _Rest, Src,
      #e{pack = Pack, wrote = W} = E) ->
    Codes = until_out(L, Src, Pack),
    Width = gt_engine:chars_width(Set),
    E1 = lists:foldl(fun(C, Acc) -> emit(Width, C, Acc) end, E, Codes),
    case maps:get(has_switch, Pack, false) of
        true -> E1#e{wrote = until_read_back(L, Codes, W, Pack)};
        false -> E1
    end;
eline({sfield, Keys, Len, _, _, _, _, _, With} = L, _Rest, Src, #e{pack = Pack, wrote = W} = E) ->
    {Bits, Raw} = field_bits(L, Src, Pack),
    E1 = held(Keys, With, Src, Len, emit(Len, Bits, E)),
    case maps:get(has_switch, Pack, false) of
        true -> E1#e{wrote = read_back(L, Raw, W, Pack)};
        false -> E1
    end;
%% `inner <format>` (0.34): encode(<format>, entity) written at the cursor,
%% which stands on a whole byte
eline({inner, Format, _Partial}, _Rest, Src, #e{pos = Pos, pack = Pack} = E) ->
    Inner = gt_engine:inner_pack(Pack, Format),
    case Pos rem 8 of
        0 -> ok;
        _ -> gt_engine:conv_error('transform-encode', Pack,
                                  "the inner message would start at bit ~p, inside a byte", [Pos])
    end,
    Bytes = gt_engine:encode_inner(Inner, maps:get(entity, Src)),
    Order = maps:get(bit_order, Pack),
    lists:foldl(fun(B, Acc) -> emit(8, gt_bits:byte_value(B, Order), Acc) end, E,
                binary_to_list(Bytes));
eline({sconst, Len, Val}, _Rest, _Src, E) -> emit(Len, Val, E);
%% a `when ... at` occupies no bits; its window is settled by ewalk/7
eline({swhen, _, _, _, At}, _Rest, _Src, E) when At =/= none -> E;
eline({swhen, Len, Val, none, none}, _Rest, _Src, E) -> emit(Len, gt_pack:when_first(Val), E);
eline({swhen, Len, _, Key, none} = L, _Rest, Src, #e{pack = Pack, wrote = W} = E) ->
    U = as_bits(L, Src, Pack),
    E1 = emit(Len, U, E),
    case maps:get(has_switch, Pack, false) of
        true -> E1#e{wrote = W#{Key => as_read_back(U, Len)}};
        false -> E1
    end;
eline({pad, Len}, _Rest, _Src, E) -> emit(Len, 0, E);
eline({align, N}, _Rest, _Src, #e{pos = Pos} = E) -> emit((N - Pos rem N) rem N, 0, E);
eline({presence, Id, Size}, Rest, Src, #e{pack = Pack, env = Env} = E) ->
    Bits = lists:usort(scan(Rest, seen(Src, E), Id, Pack, [])),
    N = case Size of
            fx -> max(1, (lists:max([0 | Bits]) + 6) div 7);   % octets
            _ -> Size
        end,
    E1 = E#e{env = Env#{Id => Bits}},
    case Size of
        fx ->
            lists:foldl(
              fun(Octet, Acc) ->
                      Acc1 = ebits([lists:member(Octet * 7 + K, Bits) || K <- lists:seq(1, 7)], Acc),
                      ebits([Octet < N - 1], Acc1)      % another octet follows
              end, E1, lists:seq(0, N - 1));
        _ -> ebits([lists:member(K, Bits) || K <- lists:seq(1, N)], E1)
    end;
eline({ifb, Conds, Body}, _Rest, Src, E) ->
    case holds(Conds, E#e.env) of
        true -> elines(Body, Src, E);
        false -> E
    end;
eline({opt, Body}, _Rest, Src, #e{pack = Pack} = E) ->
    case has(Body, seen(Src, E), Pack) of
        true -> elines(Body, Src, emit(1, 1, E));
        false -> emit(1, 0, E)
    end;
eline({chain, First, Parts, EndsFx}, _Rest, Src, E) ->
    eparts(Parts, EndsFx, Src, elines(First, Src, E));
eline({scount, Id, Len, Plus}, _Rest, _Src, #e{pos = Pos, segs = Segs, counts = Cs} = E) ->
    E#e{pos = Pos + Len, segs = [{count, Pos, Len, Plus} | Segs], counts = Cs#{Id => Pos}};
eline({len, Len, Unit, Plus, Body}, _Rest, Src, #e{pos = Pos, pack = Pack, unit = OUnit, starts = OStarts} = E) ->
    Start = Pos + Len,
    E1 = elines(Body, Src, E#e{pos = Start, unit = Unit, starts = [], rest_hit = false}),
    Bits = E1#e.pos - Start,
    Count = case Unit of
                bits -> Bits;
                bytes -> (Bits + 7) div 8       % padded with zero bits to a whole byte
            end,
    End = case Unit of
              bits -> E1#e.pos;
              bytes -> Start + Count * 8
          end,
    check_starts(E1#e.starts, End, Pack),
    E1#e{pos = End, segs = [{Pos, Len, fits(Count + Plus, Len, Pack)} | E1#e.segs],
         unit = OUnit, starts = OStarts, rest_hit = E#e.rest_hit};
eline({lenwhole, Len, Plus}, _Rest, _Src, #e{pos = Pos, segs = Segs} = E) ->
    E#e{pos = Pos + Len, segs = [{whole, Pos, Len, Plus} | Segs]};
%% a switch (0.20): the case decode would select from what the key's line
%% wrote; the case's defaults apply to its lines, the innermost winning
eline({switch, Key, Ref, Cases, Else}, _Rest, Src, #e{pack = Pack, wrote = W, path = Path} = E) ->
    Selected = select(Key, W, Cases, Else),
    case is_map(Selected) of
        true -> put(gt_seq_actual, (get(gt_seq_actual))#{{Ref, Path} => case_index(Selected, Cases)});
        false -> ok
    end,
    case Selected of
        failed -> gt_engine:conv_error('transform-encode', Pack,
                                       "switch ~s: the value its line wrote does not read back", [Key]);
        none -> gt_engine:conv_error('no-kind', Pack,
                                     "switch ~s: no case holds the value the key's line wrote, and there is no else",
                                     [Key]);
        Case -> elines(maps:get(lines, Case), case_src(Case, Src), E)
    end;
eline({sgroup, List, Mode, Body}, _Rest, Src, #e{pack = Pack} = E) ->
    Items = maps:get(List, maps:get(lists, Src), []),
    Item = fun(I, Acc) -> eitem(I, List, Body, Acc) end,
    case Mode of
        {count, Len} ->
            %% an absent list writes a count of 0
            lists:foldl(Item, emit(Len, fits(length(Items), Len, Pack), E), Items);
        while ->
            emit(1, 0, lists:foldl(fun(I, Acc) -> Item(I, emit(1, 1, Acc)) end, E, Items));
        %% the count line is filled in when the message is finished
        {countref, Id} ->
            #e{counts = Cs, cvals = CV} = E,
            E1 = E#e{cvals = CV#{maps:get(Id, Cs) => length(Items)}},
            lists:foldl(Item, E1, Items);
        %% 0.31: each count holds the items plus its own plus
        {countref2, IdA, IdB} ->
            #e{counts = Cs, cvals = CV} = E,
            N = length(Items),
            E1 = E#e{cvals = CV#{maps:get(IdA, Cs) => N, maps:get(IdB, Cs) => N}},
            lists:foldl(Item, E1, Items);
        rest ->
            %% ruling 10, judged by what is written (ruling 35): an item before
            %% the last that writes a rest group of the same extent, which
            %% would read the items after it
            Last = length(Items),
            {E1, _} = lists:foldl(
              fun(I, {#e{pos = P0, rest_hit = Hit} = Acc, N}) ->
                      Acc1 = Item(I, Acc#e{rest_hit = false}),
                      case Acc1#e.rest_hit andalso N < Last of
                          true -> gt_engine:conv_error('transform-encode', Pack,
                                                       "list ~s: an item before the last writes a rest group, which takes the rest of the extent",
                                                       [List]);
                          false -> ok
                      end,
                      case Acc1#e.pos =:= P0 of
                          true -> gt_engine:conv_error('transform-encode', Pack,
                                                       "an item of list ~s writes no bits (ruling 29 of 0.21)", [List]);
                          false -> ok
                      end,
                      Acc2 = Acc1#e{rest_hit = Hit},
                      {case Acc2#e.unit of
                           bytes -> Acc2#e{starts = [P0 | Acc2#e.starts]};
                           bits -> Acc2
                       end, N + 1}
              end, {E, 1}, Items),
            %% this group is written: it counts for an item that holds it
            E1#e{rest_hit = true};
        _ when Items =:= [] ->
            gt_engine:conv_error('transform-encode', Pack,
                                 "list ~s is absent or empty and its group holds at least one item",
                                 [List]);
        last ->
            Last = length(Items),
            {E1, _} = lists:foldl(
                        fun(I, {Acc, N}) ->
                                {Item(I, ebits([N =:= Last], Acc)), N + 1}
                        end, {E, 1}, Items),
            E1;
        more ->
            Last = length(Items),
            {E1, _} = lists:foldl(
                        fun(I, {Acc, N}) ->
                                {Item(I, ebits([N < Last], Acc)), N + 1}
                        end, {E, 1}, Items),
            E1;
        fx ->
            Last = length(Items),
            {E1, _} = lists:foldl(
                        fun(I, {Acc, N}) ->
                                {ebits([N < Last], Item(I, Acc)), N + 1}
                        end, {E, 1}, Items),
            E1
    end.

%% ---- ASN.1 unaligned PER (0.19) ----
epieces(Pieces, E) -> lists:foldl(fun({Len, V}, Acc) -> emit(Len, V, Acc) end, E, Pieces).

%% The alt a choice writes: the first, in line order, with content, else
%% the first.
chosen([First | _] = Alts, Src, Pack) ->
    case [A || {_, Body} = A <- Alts, has(Body, Src, Pack)] of
        [A | _] -> A;
        [] -> First
    end.

%% What an absent key writes (ruling 1 of 0.19) -> [{Len, Value}].
uabsent({int, Lb, Ub, false}) -> [{bitlen(Ub - Lb), 0}];
uabsent({int, Lb, Ub, true}) -> [{1, 0}, {bitlen(Ub - Lb), 0}];
uabsent({semi, _}) -> ld(1) ++ [{8, 0}];
uabsent(unc) -> ld(1) ++ [{8, 0}];
uabsent({enum, N, false}) -> [{bitlen(N - 1), 0}];
uabsent({enum, N, true}) -> [{1, 0}, {bitlen(N - 1), 0}];
uabsent({chars, Lb, Ub}) -> [{bitlen(Ub - Lb), 0}, {7 * Lb, 0}];
uabsent({octets, Lb, Ub}) -> [{bitlen(Ub - Lb), 0}, {8 * Lb, 0}];
uabsent({_, unc}) -> ld(0).

%% A present value; any failure is transform-encode (guard_encode).
uenc({enum, N, IsExt}, uint, V) when is_integer(V), V >= 0, V =< ?I64MAX ->
    if
        V < N, IsExt -> [{1, 0}, {bitlen(N - 1), V}];
        V < N -> [{bitlen(N - 1), V}];
        IsExt -> [{1, 1} | nsn_pieces(V - N)]
    end;
uenc({chars, Lb, Ub}, ascii, B) -> count(byte_size(B), Lb, Ub) ++ uchars_pieces(B);
uenc({chars, unc}, ascii, B) -> ld(byte_size(B)) ++ uchars_pieces(B);
uenc({octets, Lb, Ub}, Tr, W) ->
    B = uoctets(Tr, W),
    count(byte_size(B), Lb, Ub) ++ [{8 * byte_size(B), binary:decode_unsigned(B)}];
uenc({octets, unc}, Tr, W) ->
    B = uoctets(Tr, W),
    ld(byte_size(B)) ++ [{8 * byte_size(B), binary:decode_unsigned(B)}];
uenc(Loc, Tr, W) ->
    V = uint_of(Tr, W),
    true = V >= ?I64MIN andalso V =< ?I64MAX,
    case Loc of
        {int, Lb, Ub, false} when V >= Lb, V =< Ub -> [{bitlen(Ub - Lb), V - Lb}];
        {int, Lb, Ub, true} when V >= Lb, V =< Ub -> [{1, 0}, {bitlen(Ub - Lb), V - Lb}];
        {int, _, _, true} -> [{1, 1} | twos_pieces(V)];
        {semi, Lb} when V >= Lb ->
            U = V - Lb,
            L = uoctets_needed(U),
            ld(L) ++ [{8 * L, U}];
        unc -> twos_pieces(V)
    end.

count(C, Lb, Ub) when C >= Lb, C =< Ub -> [{bitlen(Ub - Lb), C - Lb}].

uint_of(T, V) when (T =:= uint orelse T =:= twos), is_integer(V) -> V;
uint_of({S, F, O}, X) when (S =:= uscale orelse S =:= sscale), is_number(X) ->
    round(case F of
              {dec, Fd} -> (X - O) / Fd;
              {frac, Num, Den} -> (X - O) * Den / Num
          end).

%% each character in 7 bits; a code above 127 is refused
uchars_pieces(B) ->
    [case C =< 127 of
         true -> {7, C};
         false -> error({uper, "a character above 127"})
     end || <<C>> <= B].

uoctets(hex, W) when is_binary(W) -> unhex(W, <<>>);
uoctets(utf8, W) when is_binary(W) -> W.

unhex(<<>>, Acc) -> Acc;
unhex(<<H, L, R/binary>>, Acc) -> unhex(R, <<Acc/binary, (nib(H) * 16 + nib(L))>>).

nib(C) when C >= $0, C =< $9 -> C - $0;
nib(C) when C >= $a, C =< $f -> C - $a + 10;
nib(C) when C >= $A, C =< $F -> C - $A + 10.

%% A length determinant; 16384 or more (a fragmented length) is refused.
ld(N) when N < 128 -> [{1, 0}, {7, N}];
ld(N) when N < 16384 -> [{2, 2}, {14, N}].

nsn_pieces(N) when N =< 63 -> [{1, 0}, {6, N}];
nsn_pieces(N) ->
    L = uoctets_needed(N),
    [{1, 1}] ++ ld(L) ++ [{8 * L, N}].

uoctets_needed(U) -> max(1, (bitlen(U) + 7) div 8).

%% The fewest octets that hold V as a two's-complement number.
twos_pieces(V) ->
    L = twos_octets(V, 1),
    ld(L) ++ [{8 * L, V band ((1 bsl (8 * L)) - 1)}].

twos_octets(V, L) ->
    case V >= -(1 bsl (8 * L - 1)) andalso V < (1 bsl (8 * L - 1)) of
        true -> L;
        false -> twos_octets(V, L + 1)
    end.

ebits(Bools, E) ->
    lists:foldl(fun(true, Acc) -> emit(1, 1, Acc);
                   (false, Acc) -> emit(1, 0, Acc)
                end, E, Bools).

%% The source of a case's lines: its defaults over those that reach the
%% switch (rulings 7 and 22 of 0.20).
case_src(#{defaults := Ds}, #{defaults := Outer} = Src) when map_size(Ds) > 0 ->
    Src#{defaults := maps:merge(Outer, Ds)};
case_src(_Case, Src) -> Src.

%% What a field line writes -> {Bits, Raw}: the bits on the wire, and the
%% value decode reads from them before `trim`, `via` and the transform
%% (after `swap`).
field_bits({sfield, Keys, Len, Tr, LenT, Swap, _Trim, Absent, With}, Src, Pack) ->
    Cands = candidates(Keys, With, Src),
    Bits = case pick(Cands, Src) of
               %% an absent key writes zero bits, or its first sentinel;
               %% neither is content for a presence, opt or fx bit (ruling 4
               %% of 0.9). A line suppressed by `with` whose `also` keys give
               %% no value writes zero bits, not its sentinel (ruling 20 of
               %% 0.18)
               none when Absent =:= none -> 0;
               none when length(Cands) < length(Keys) -> 0;
               none -> gt_engine:bits_sentinel(Absent, Len, Swap);
               {Key, Via, Val} ->
                   gt_engine:guard_encode(
                     Pack, Key, LenT,
                     fun() ->
                             W = gt_engine:wire_value(Pack, Key, Tr, {Via, false, false, false, none, none}, Val),
                             U0 = gt_engine:bits_encode(Tr, W, Len, maps:get(bit_order, Pack)),
                             case Swap of
                                 true -> gt_engine:swap_bytes(U0, Len);
                                 false -> U0
                             end
                     end)
           end,
    Raw = case Swap of
              true -> gt_engine:swap_bytes(Bits, Len);
              false -> Bits
          end,
    {Bits, Raw}.

%% The keys decode would set from Raw, put in Wrote where it does not hold
%% them yet (decode keeps a key's first value): none for a sentinel, and
%% none whose transform or table fails.
read_back({sfield, Keys, Len, Tr, _LenT, _Swap, Trim, Absent, _With}, Raw, Wrote, Pack) ->
    case Absent =/= none andalso lists:member(Raw, Absent) of
        true -> Wrote;
        false ->
            lists:foldl(
              fun({Key, Via}, W) ->
                      case maps:is_key(Key, W) of
                          true -> W;
                          false ->
                              try
                                  V0 = gt_engine:bits_decode(Tr, Raw, Len, maps:get(bit_order, Pack)),
                                  V1 = case Trim of
                                           true -> gt_engine:trim(Tr, V0);
                                           false -> V0
                                       end,
                                  V2 = gt_engine:via_decode({Via, false, false, false, none, none},
                                                            V1, Tr, Key, <<>>, Pack),
                                  gt_engine:typemap_decode(Key, V2, Pack)
                              of
                                  V -> W#{Key => V}
                              catch
                                  %% the output would not decode (ruling 31)
                                  _:_ -> W#{Key => readback_failed}
                              end
                      end
              end, Wrote, Keys)
    end.

%% The codes an `until:` line writes, its terminator last. More than
%% 2040 / w characters is transform-encode.
until_out({sfield, Keys, {until, Code}, {chars, Set} = Tr, LenT, _, _, _, With}, Src, Pack) ->
    case pick(candidates(Keys, With, Src), Src) of
        none -> [Code];
        {Key, Via, Val} ->
            gt_engine:guard_encode(
              Pack, Key, LenT,
              fun() ->
                      Text = gt_engine:wire_value(Pack, Key, Tr, {Via, false, false, false, none, none}, Val),
                      true = is_binary(Text),
                      true = byte_size(Text) =< 2040 div gt_engine:chars_width(Set),
                      gt_engine:until_codes(Set, Code, Text)
              end)
    end.

%% As read_back/4 for an `until:` field: the text decode reads from Codes.
until_read_back({sfield, Keys, {until, _}, {chars, Set} = Tr, LenT, _, _, _, _}, Codes, Wrote, Pack) ->
    lists:foldl(
      fun({Key, Via}, W) ->
              case maps:is_key(Key, W) of
                  true -> W;
                  false ->
                      try
                          V0 = gt_engine:until_text(Set, lists:droplast(Codes)),
                          V1 = gt_engine:via_decode({Via, false, false, false, none, none},
                                                    V0, Tr, Key, LenT, Pack),
                          gt_engine:typemap_decode(Key, V1, Pack)
                      of
                          V -> W#{Key => V}
                      catch
                          _:_ -> W#{Key => readback_failed}
                      end
              end
      end, Wrote, Keys).

%% As read_back/4 for a field on a UPER locator (0.19): the pieces written
%% are read as decode reads them.
uread_back({sfield, Keys, {uper, Loc}, Tr, LenT, _, _, _, _}, Pieces, Wrote, Pack) ->
    Len = lists:sum([L || {L, _} <- Pieces]),
    Pad = (8 - Len rem 8) rem 8,
    Bin = << << <<V:L>> || {L, V} <- Pieces >>/bits, 0:Pad >>,
    Msg = gt_bits:open(Bin, msb),
    D = #d{msg = Msg, hard = gt_bits:bit_size(Msg), pack = Pack, named = #{}},
    lists:foldl(
      fun({Key, Via}, W) ->
              case maps:is_key(Key, W) of
                  true -> W;
                  false ->
                      try
                          {Res, _} = uread(Loc, none, D),
                          V0 = uvalue(Res, Tr),
                          V1 = gt_engine:via_decode({Via, false, false, false, none, none},
                                                    V0, Tr, Key, LenT, Pack),
                          gt_engine:typemap_decode(Key, V1, Pack)
                      of
                          V -> W#{Key => V}
                      catch
                          %% the output would not decode (ruling 31 of 0.20)
                          _:_ -> W#{Key => readback_failed}
                      end
              end
      end, Wrote, Keys).

%% An fx bit is 1 when a line after it in the chain has content; the parts
%% after a 0 bit are not written. The bit of a closing fx line is 0.
eparts([], false, _Src, E) -> E;
eparts([], true, _Src, E) -> emit(1, 0, E);
eparts([Part | Rest] = Parts, EndsFx, Src, #e{pack = Pack} = E) ->
    case has(lists:append(Parts), seen(Src, E), Pack) of
        true -> eparts(Rest, EndsFx, Src, elines(Part, Src, emit(1, 1, E)));
        false -> emit(1, 0, E)
    end.

%% An item is a scope of its own: what its lines wrote is not the
%% message's.
eitem(Item, List, Body, #e{pack = Pack, wrote = W, path = Path, icount = IC} = E) ->
    {Lines, Src} = item_scope(Item, Body, Pack),
    N = maps:get({Path, List}, IC, 0),
    NCommon = case maps:get(kinds, Body) of
                  [] -> length(Lines);
                  _ -> length(maps:get(lines, Body))
              end,
    E1 = escope(Lines, NCommon, Src, E#e{wrote = #{}, path = [{List, N} | Path],
                                        icount = IC#{{Path, List} => N + 1}}),
    E1#e{wrote = W, path = Path}.

%% The bits a `when ... as <key>` line writes (0.30): the value of the key
%% when the scope holds it and the `when` matches it, the first listed value
%% when the scope does not hold it (a default does not count, ruling 6); a
%% held value the `when` does not match is transform-encode.
as_bits({swhen, Len, Val, Key, _}, #{model := Model}, Pack) ->
    case maps:find(Key, Model) of
        error -> gt_pack:when_first(Val);
        {ok, V} ->
            case gt_pack:as_match(V, Val) of
                {true, U} -> U;
                false -> gt_engine:conv_error('transform-encode', Pack,
                                              "~s holds ~s, which its when line of ~p bits does not match",
                                              [Key, gt_num:canon(V), Len])
            end
    end.

%% ---- look-ahead windows (0.33) ----
%% The number of common lines at the head of a scope's lines.
ncommon(#{has_kinds := true, common := Common}) -> length(Common);
ncommon(_Pack) -> infinity.

%% A scope's lines: the common lines, then the kind's, whose windows are
%% settled once every line under them is written (ewalk/7). Every line is
%% written with all the lines after it in the scope, the kind's included, so
%% that a presence line among the common lines sees them (ruling 12 of 0.8).
escope(Lines, infinity, Src, E) -> elines(Lines, Src, E);
escope(Lines, N, Src, E) when N >= length(Lines) -> elines(Lines, Src, E);
escope(Lines, N, Src, E) ->
    Kind = lists:nthtail(N, Lines),
    case [W || {swhen, _, _, _, At} = W <- Kind, At =/= none] of
        [] -> elines(Lines, Src, E);
        Wins -> ecommon(Lines, N, Wins, Src, E)
    end.

ecommon(Lines, 0, Wins, Src, #e{pos = KS} = E) ->
    %% the kind start: where the common lines ended
    ewalk(Lines, Wins, KS, KS + lists:max([At + Len || {swhen, Len, _, _, At} <- Wins]), Src, E, []);
ecommon([L | Rest], N, Wins, Src, E) -> ecommon(Rest, N - 1, Wins, Src, eline(L, Rest, Src, E)).

%% Fs: the field lines of a bit length written so far, with their first bit.
ewalk(Lines, [_ | _] = Wins, KS, End, Src, #e{pos = Pos} = E, Fs) when Pos >= End; Lines =:= [] ->
    E1 = lists:foldl(fun(W, Acc) -> settle_win(W, KS, Src, Acc) end, E, Wins),
    ewalk(Lines, [], KS, End, Src, reread(Fs, E1), []);
ewalk([], [], _KS, _End, _Src, E, _Fs) -> E;
ewalk([L | Rest], Wins, KS, End, Src, #e{pos = Pos} = E, Fs) ->
    Fs1 = case {Wins, L} of
              {[_ | _], {sfield, _, Len, _, _, _, _, _, _}} when is_integer(Len) -> [{Pos, L} | Fs];
              _ -> Fs
          end,
    ewalk(Rest, Wins, KS, End, Src, eline(L, Rest, Src, E), Fs1).

%% A switch reads its key from the bits as they stand after the windows are
%% written (Encode of 0.33): what decode reads back from a field line a
%% window wrote over is read again from those bits.
reread(Fs, #e{pack = Pack, wins = Wins, wrote = W0} = E) ->
    case maps:get(has_switch, Pack, false) andalso Wins =/= [] of
        false -> E;
        true ->
            W = lists:foldl(
                  fun({FP, {sfield, Keys, Len, _, _, Swap, _, _, _} = L}, Acc) ->
                          case lists:any(fun({WP, WL, _}) -> WP < FP + Len andalso FP < WP + WL end, Wins) of
                              false -> Acc;
                              true ->
                                  Bits = win_peek(E, FP, Len, false),
                                  Raw = case Swap of
                                            true -> gt_engine:swap_bytes(Bits, Len);
                                            false -> Bits
                                        end,
                                  read_back(L, Raw, maps:without([K || {K, _} <- Keys], Acc), Pack)
                          end
                  end, W0, lists:reverse(Fs)),
            E#e{wrote = W}
    end.

%% One window (Encode of 0.33): the bits as written stand when they match the
%% `when` and agree with a held `as` key; else the window takes the key's
%% value or the first listed value, and a bit that differs from a bit a held
%% key wrote is transform-encode (rulings 1, 12, 13 and 26).
settle_win({swhen, Len, Val, As, At} = L, KS, #{model := Model} = Src, #e{pack = Pack, wrote = W} = E) ->
    P = KS + At,
    Cur = win_peek(E, P, Len, false),
    Agrees = case As of
                 none -> true;
                 _ ->
                     case maps:find(As, Model) of
                         error -> true;
                         {ok, V} -> gt_pack:as_match(V, Val) =:= {true, Cur}
                     end
             end,
    Value = case gt_pack:when_match(Cur, Val) andalso Agrees of
                true -> Cur;
                false -> as_bits(L, Src, Pack)
            end,
    E1 = case Value =:= Cur of
             true -> E;
             false ->
                 case (Value bxor Cur) band win_peek(E, P, Len, true) of
                     0 -> E#e{wins = [{P, Len, Value} | E#e.wins]};
                     _ -> gt_engine:conv_error('transform-encode', Pack,
                                               "the window of when ... at ~p would change bits a held key wrote",
                                               [At])
                 end
         end,
    case As =/= none andalso maps:get(has_switch, Pack, false) of
        true -> E1#e{wrote = W#{As => as_read_back(Value, Len)}};
        false -> E1
    end.

%% The Len bits at P as written so far (raw stream bits in the pack's bit
%% order, ruling 8), or with Held the mask of the bits a held key wrote that
%% no window has written over.
win_peek(#e{pack = Pack, pos = Pos, segs = Segs, held = Held, wins = Wins}, P, Len, IsMask) ->
    Size = max(Pos, P + Len),
    M0 = gt_bits:new_bits(Size, maps:get(bit_order, Pack)),
    M1 = case IsMask of
             false -> lists:foldl(fun({SP, SL, SV}, A) -> gt_bits:overwrite(A, SP, SL, SV);
                                     (_, A) -> A
                                  end, M0, lists:reverse(Segs));
             true -> lists:foldl(fun({HP, HL}, A) -> gt_bits:overwrite(A, HP, HL, (1 bsl HL) - 1) end,
                                 M0, Held)
         end,
    M2 = lists:foldl(fun({WP, WL, WV}, A) ->
                             gt_bits:overwrite(A, WP, WL, case IsMask of true -> 0; false -> WV end)
                     end, M1, lists:reverse(Wins)),
    gt_bits:peek(M2, P, Len).

%% Record the bits of a field line that wrote a key the scope holds.
held(Keys, With, #{model := Model} = Src, Len, #e{pos = Pos, held = H} = E) ->
    case lists:any(fun({K, _}) -> maps:is_key(K, Model) end, candidates(Keys, With, Src)) of
        true -> E#e{held = [{Pos - Len, Len} | H]};
        false -> E
    end.

%% What decode reads back from the bits of an `as` line: `uint` (ruling 7).
as_read_back(U, 64) when U >= 1 bsl 63 -> U - (1 bsl 64);
as_read_back(U, _Len) -> U.

%% The lines an item is written by, and what it is written from: the lines
%% common to every item, then those of the kind the item recorded when it
%% was decoded from this format, else of the first kind whose every
%% `requires` term the item holds.
item_scope(Item, #{lines := Common, defaults := Defaults, kinds := Kinds}, Pack) ->
    Model = maps:get(model, Item),
    Lists = maps:get(lists, Item, #{}),
    Src = #{model => Model, lists => Lists, defaults => Defaults},
    case Kinds of
        [] -> {Common, Src};
        _ ->
            Name = maps:get(name, Pack),
            Recorded = case maps:get(kind, Item, undefined) of
                           {Name, KindName} -> [K || #{name := N} = K <- Kinds, N =:= KindName];
                           _ -> []
                       end,
            Has = fun(T) -> gt_engine:req_holds(T, Model, Lists) end,
            %% with the implicit term of each `when ... as` (0.30, ruling 4)
            Chosen = Recorded ++ [K || #{requires := Req, lines := KLs} = K <- Kinds,
                                       lists:all(Has, Req), gt_pack:as_holds(KLs, Model)],
            case Chosen of
                [] -> gt_engine:conv_error('no-kind', Pack, "an item selects no kind of its group", []);
                [#{lines := Ls, defaults := Ds} | _] -> {Common ++ Ls, Src#{defaults := Ds}}
            end
    end.

%% The value a field line writes: that of the earliest of its keys the scope
%% has, else the earliest `default` of one of them -> none | {Key, Via, Value}.
pick(Keys, #{model := Model, defaults := Defaults}) ->
    case [{K, Via, V} || {K, Via} <- Keys, {ok, V} <- [maps:find(K, Model)]] of
        [Found | _] -> Found;
        [] ->
            case [{K, Via, V} || {K, Via} <- Keys, {ok, V} <- [maps:find(K, Defaults)]] of
                [Found | _] -> Found;
                [] -> none
            end
    end.

%% The keys a field line may write from (0.18): a line `with` a key the
%% scope does not hold drops its own key, value and default alike; its
%% `also` keys stay candidates (ruling 5).
candidates(Keys, none, _Src) -> Keys;
candidates([_Own | Also] = Keys, With, #{model := Model, lists := Lists}) ->
    case gt_engine:holds(With, Model, Lists) of
        true -> Keys;
        false -> Also
    end.

%% Would these lines write a present key (a key with a default counts), or a
%% list that is not empty? A switch counts the case it would select only.
has([], _Src, _Pack) -> false;
has([L | Rest], Src, Pack) ->
    has1(L, Src, Pack) orelse has(Rest, sim1(L, Src, Pack), Pack).

%% In a UPER pack no default counts as content (rulings 2 and 19 of 0.19).
has1({sfield, Keys0, _, _, _, _, _, _, With}, #{model := Model} = Src, Pack) ->
    Keys = candidates(Keys0, With, Src),          % ruling 1 of 0.18
    case maps:get(encoding, Pack) of
        uper -> lists:any(fun({K, _}) -> maps:is_key(K, Model) end, Keys);
        _ -> pick(Keys, Src) =/= none
    end;
has1({uext, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({uchoice, _, _, Alts}, Src, Pack) -> lists:any(fun({_, B}) -> has(B, Src, Pack) end, Alts);
has1({sgroup, List, _, _}, #{lists := Lists}, _Pack) ->
    case maps:find(List, Lists) of
        {ok, [_ | _]} -> true;
        _ -> false
    end;
has1({ifb, _, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({opt, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({len, _, _, _, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({chain, First, Parts, _}, Src, Pack) -> has(lists:append([First | Parts]), Src, Pack);
has1({switch, Key, Ref, Cases, Else}, Src, Pack) ->
    case predict(Key, Ref, Cases, Else, Src) of
        Case when is_map(Case) -> has(maps:get(lines, Case), case_src(Case, Src), Pack);
        _ -> false
    end;
has1(_, _Src, _Pack) -> false.

%% The scan's view of what decode would read back from a line, were it
%% written as the encode would write it (only a pack with a switch needs
%% it): a field line records its keys; an `if` is written when its bits
%% are known to hold, or else when it has content; an `opt` when it has
%% content; a chain part when a later part has content.
sim1(L, Src, Pack) ->
    case maps:get(has_switch, Pack, false) of
        false -> Src;
        true -> sim(L, Src, Pack)
    end.

sims(Lines, Src, Pack) -> lists:foldl(fun(L, S) -> sim(L, S, Pack) end, Src, Lines).

sim({sfield, _, {until, _}, _, _, _, _, _, _} = L, Src, Pack) ->
    try until_out(L, Src, Pack) of
        Codes -> Src#{wrote => until_read_back(L, Codes, maps:get(wrote, Src, #{}), Pack)}
    catch
        _:_ -> Src
    end;
sim({sfield, _, _, _, _, _, _, _, _} = L, Src, Pack) ->
    try field_bits(L, Src, Pack) of
        {_, Raw} -> Src#{wrote => read_back(L, Raw, maps:get(wrote, Src, #{}), Pack)}
    catch
        _:_ -> Src
    end;
sim({swhen, Len, _, Key, none} = L, Src, Pack) when Key =/= none ->
    try as_bits(L, Src, Pack) of
        U -> Src#{wrote => (maps:get(wrote, Src, #{}))#{Key => as_read_back(U, Len)}}
    catch
        _:_ -> Src
    end;
sim({ifb, Conds, Body}, Src, Pack) ->
    Env = maps:get(env, Src, #{}),
    Written = case lists:all(fun({Id, _, _}) -> maps:is_key(Id, Env) end, Conds) of
                  true -> holds(Conds, Env);
                  false -> has(Body, Src, Pack)
              end,
    case Written of
        true -> sims(Body, Src, Pack);
        false -> Src
    end;
sim({opt, Body}, Src, Pack) ->
    case has(Body, Src, Pack) of
        true -> sims(Body, Src, Pack);
        false -> Src
    end;
sim({len, _, _, _, Body}, Src, Pack) -> sims(Body, Src, Pack);
sim({chain, First, Parts, _}, Src, Pack) -> sim_parts(Parts, sims(First, Src, Pack), Pack);
sim({switch, Key, Ref, Cases, Else}, Src, Pack) ->
    case predict(Key, Ref, Cases, Else, Src) of
        Case when not is_map(Case) -> Src;
        Case ->
            S1 = sims(maps:get(lines, Case), case_src(Case, Src), Pack),
            S1#{defaults := maps:get(defaults, Src)}
    end;
sim(_, Src, _Pack) -> Src.

sim_parts([], Src, _Pack) -> Src;
sim_parts([Part | Rest] = Parts, Src, Pack) ->
    case has(lists:append(Parts), Src, Pack) of
        true -> sim_parts(Rest, sims(Part, Src, Pack), Pack);
        false -> Src
    end.

%% The bits of presence Id that are 1: those some `if` block names without
%% `!` and whose content is present. The blocks may stand in nested blocks,
%% in the case a switch selects and in the items of groups.
scan([], _Src, _Id, _Pack, Acc) -> Acc;
scan([L | Rest], Src, Id, Pack, Acc) ->
    scan(Rest, sim1(L, Src, Pack), Id, Pack, scan1(L, Src, Id, Pack, Acc)).

scan1({ifb, Conds, Body}, Src, Id, Pack, Acc) ->
    Acc1 = case [B || {I, B, false} <- Conds, I =:= Id] of
               [] -> Acc;
               Named ->
                   case has(Body, Src, Pack) of
                       true -> Named ++ Acc;
                       false -> Acc
                   end
           end,
    scan(Body, Src, Id, Pack, Acc1);
scan1({opt, Body}, Src, Id, Pack, Acc) -> scan(Body, Src, Id, Pack, Acc);
scan1({uext, Body}, Src, Id, Pack, Acc) -> scan(Body, Src, Id, Pack, Acc);
scan1({uchoice, _, _, Alts}, Src, Id, Pack, Acc) ->
    {_, Body} = chosen(Alts, Src, Pack),
    scan(Body, Src, Id, Pack, Acc);
scan1({len, _, _, _, Body}, Src, Id, Pack, Acc) -> scan(Body, Src, Id, Pack, Acc);
scan1({chain, First, Parts, _}, Src, Id, Pack, Acc) ->
    scan(lists:append([First | Parts]), Src, Id, Pack, Acc);
scan1({switch, Key, Ref, Cases, Else}, Src, Id, Pack, Acc) ->
    case predict(Key, Ref, Cases, Else, Src) of
        Case when is_map(Case) -> scan(maps:get(lines, Case), case_src(Case, Src), Id, Pack, Acc);
        _ -> Acc
    end;
scan1({sgroup, List, _, Body}, #{lists := Lists} = Src, Id, Pack, Acc) ->
    Path = maps:get(path, Src, []),
    Items = maps:get(List, Lists, []),
    lists:foldl(
      fun({N, Item}, A) ->
              %% an item that selects no kind of this group fails when the
              %% group is written, and the group may stand in a block that
              %% is not
              try item_scope(Item, Body, Pack) of
                  {Lines, ISrc} ->
                      scan(Lines, ISrc#{path => [{List, N} | Path],
                                        forced => maps:get(forced, Src, #{})}, Id, Pack, A)
              catch
                  error:{convert_error, 'no-kind', _} -> A
              end
      end, Acc, lists:zip(lists:seq(0, length(Items) - 1), Items));
scan1(_, _Src, _Id, _Pack, Acc) -> Acc.
