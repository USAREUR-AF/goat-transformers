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
-record(d, {msg, hard, pos = 0, model = #{}, lists = #{}, failed = [], env = #{},
            pack, named}).

decode(#{common := Common, kinds := Kinds, has_kinds := HasKinds, name := Name} = Pack, Bytes) ->
    Msg = gt_bits:open(gt_engine:unhex(Pack, Bytes), maps:get(bit_order, Pack)),
    D0 = #d{msg = Msg, hard = gt_bits:bit_size(Msg), pack = Pack,
            named = maps:get(presence_named, Pack)},
    D1 = lines(Common, none, D0),
    {Kind, D2} = case HasKinds of
                     false -> {undefined, D1};
                     true ->
                         {K, Dk} = kind(Kinds, none, D1),
                         {{Name, K}, Dk}
                 end,
    check_failed(D2),
    #{model => D2#d.model, lists => D2#d.lists, residue => [], src => Name, kind => Kind}.

%% A key whose every line failed its transform fails the decode.
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
    case whens(Whens, D#d.pos, Ext, D) of
        false -> kind(Rest, Ext, D);
        Pos -> {Name, lines(Body, Ext, D#d{pos = Pos})}
    end.

%% A `when` any of whose bits lies beyond the input does not hold.
whens([], Pos, _Ext, _D) -> Pos;
whens([{swhen, Len, Val} | Rest], Pos, Ext, D) ->
    case avail(Pos, Len, Ext, D) =:= ok andalso gt_bits:read(D#d.msg, Pos, Len) =:= Val of
        true -> whens(Rest, Pos + Len, Ext, D);
        false -> false
    end.

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

line({sfield, Keys, Len, Tr, LenT, Swap, Trim, Absent}, Ext, #d{pos = Pos} = D) ->
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
line({swhen, Len, Val}, Ext, #d{pos = Pos, pack = Pack} = D) ->
    case whens([{swhen, Len, Val}], Pos, Ext, D) of
        false -> gt_engine:conv_error('no-kind', Pack, "a common when does not hold", []);
        Pos1 -> D#d{pos = Pos1}
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
            D1 = lines(Body, End, D#d{pos = Start}),
            D1#d{pos = End}                    % what no line read is skipped
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
            D#d{pos = Pos + Len, hard = Bits}  % input beyond it is ignored
    end;
line({sgroup, List, Mode, Body}, Ext, D) ->
    %% a later group of a list replaces the items of an earlier one; those
    %% are no longer counted against the limit (ruling 7g of 0.11)
    Release = fun() ->
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

set_key({Key, Via}, U, Len, Tr, LenT, Trim, #d{model = Model, pack = Pack} = D) ->
    case maps:is_key(Key, Model) of
        true -> D;
        false ->
            try
                V = gt_engine:bits_decode(Tr, U, Len, maps:get(bit_order, Pack)),
                case Trim of
                    true -> gt_engine:strip_trailing(V, $\s);
                    false -> V
                end
            of
                V0 ->
                    %% a value with no table entry fails the decode when it
                    %% ends, so that the limit on list items read later still
                    %% wins (ruling 7f of 0.11)
                    try gt_engine:via_decode({Via, false, false, false, none}, V0, Tr, Key, LenT, Pack) of
                        V1 -> D#d{model = Model#{Key => gt_engine:typemap_decode(Key, V1, Pack)}}
                    catch
                        error:{convert_error, 'transform-decode', Msg} ->
                            gt_engine:record_failure_msg(Msg),
                            D
                    end
            catch
                _:_ -> D#d{failed = [{Key, LenT} | D#d.failed]}
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
        [] -> D#d{env = Env#{Id => Bits}};
        [B | _] -> malformed(D, "presence bit ~p is 1 and no if block names it", [B])
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
            gt_engine:items_reserve(N, D#d.pack),
            case N > limit(Ext, D) - Pos1 of
                true -> malformed(D, "a count of ~p is larger than the bits left", [N]);
                false -> ok
            end,
            lists:mapfoldl(fun(_, Acc) -> item_lines(Body, Ext, Acc) end, D#d{pos = Pos1},
                           lists:seq(1, N))
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

fx_items(Body, Ext, D, Acc) ->
    {Item, D1} = item(Body, Ext, D),
    case bit(Ext, D1) of
        {1, D2} -> fx_items(Body, Ext, D2, [Item | Acc]);
        {0, D2} -> {lists:reverse([Item | Acc]), D2};
        absent -> {lists:reverse([Item | Acc]), D1}
    end.

%% One item at the cursor: the lines common to every item, then the kind
%% its `when` lines select.
item(Body, Ext, D) ->
    gt_engine:items_reserve(1, D#d.pack),
    item_lines(Body, Ext, D).

item_lines(#{lines := Common, kinds := Kinds}, Ext, #d{model = M, lists = Ls, failed = F} = D) ->
    D1 = lines(Common, Ext, D#d{model = #{}, lists = #{}, failed = []}),
    {Item, D2} =
        case Kinds of
            [] -> {#{model => D1#d.model, lists => D1#d.lists}, D1};
            _ ->
                {K, Dk} = kind(Kinds, Ext, D1),
                {#{model => Dk#d.model, lists => Dk#d.lists,
                   kind => {maps:get(name, D#d.pack), K}}, Dk}
        end,
    check_failed(D2),
    {Item, D2#d{model = M, lists = Ls, failed = F}}.

%% ===================================================================
%% encode
%% ===================================================================
%% Because a presence bit is written before the blocks that set it, a scope
%% is laid out in two passes: at a `presence` line the lines after it are
%% scanned for the `if` blocks that name it and have content; then they are
%% written. Src = #{model, lists, defaults}: what a scope is written from.
%% segs: [{Pos, Len, Value} | {whole, Pos, Len, Plus}], bits not named are 0.
-record(e, {pos = 0, segs = [], env = #{}, pack}).

encode(Pack, Lines, Defaults, Entity) ->
    Src = #{model => maps:get(model, Entity), lists => maps:get(lists, Entity, #{}),
            defaults => Defaults},
    #e{pos = End, segs = Segs} = elines(Lines, Src, #e{pack = Pack}),
    Bytes = (End + 7) div 8,                    % a whole number of bytes
    M = lists:foldl(
          fun({whole, Pos, Len, Plus}, Acc) ->
                  gt_bits:overwrite(Acc, Pos, Len, fits(Bytes + Plus, Len, Pack));
             ({Pos, Len, Val}, Acc) -> gt_bits:overwrite(Acc, Pos, Len, Val)
          end, gt_bits:new(Bytes, maps:get(bit_order, Pack)), Segs),
    gt_bits:bytes_to_hex(gt_bits:to_bytes(M)).

fits(V, Len, _Pack) when V >= 0, V < (1 bsl Len) -> V;
fits(V, Len, Pack) ->
    gt_engine:conv_error('transform-encode', Pack,
                         "the count or length ~p does not fit its ~p bits", [V, Len]).

emit(Len, 0, #e{pos = Pos} = E) -> E#e{pos = Pos + Len};
emit(Len, Val, #e{pos = Pos, segs = Segs} = E) ->
    E#e{pos = Pos + Len, segs = [{Pos, Len, Val} | Segs]}.

elines([], _Src, E) -> E;
elines([L | Rest], Src, E) -> elines(Rest, Src, eline(L, Rest, Src, E)).

eline({sfield, Keys, Len, Tr, LenT, Swap, _Trim, Absent}, _Rest, Src, #e{pack = Pack} = E) ->
    case pick(Keys, Src) of
        %% an absent key writes zero bits, or its first sentinel; neither is
        %% content for a presence, opt or fx bit (ruling 4 of 0.9)
        none when Absent =:= none -> emit(Len, 0, E);
        none -> emit(Len, gt_engine:bits_sentinel(Absent, Len, Swap), E);
        {Key, Via, Val} ->
            U = gt_engine:guard_encode(
                  Pack, Key, LenT,
                  fun() ->
                          W = gt_engine:wire_value(Pack, Key, Tr, {Via, false, false, false, none}, Val),
                          U0 = gt_engine:bits_encode(Tr, W, Len, maps:get(bit_order, Pack)),
                          case Swap of
                              true -> gt_engine:swap_bytes(U0, Len);
                              false -> U0
                          end
                  end),
            emit(Len, U, E)
    end;
eline({sconst, Len, Val}, _Rest, _Src, E) -> emit(Len, Val, E);
eline({swhen, Len, Val}, _Rest, _Src, E) -> emit(Len, Val, E);
eline({pad, Len}, _Rest, _Src, E) -> emit(Len, 0, E);
eline({align, N}, _Rest, _Src, #e{pos = Pos} = E) -> emit((N - Pos rem N) rem N, 0, E);
eline({presence, Id, Size}, Rest, Src, #e{pack = Pack, env = Env} = E) ->
    Bits = lists:usort(scan(Rest, Src, Id, Pack, [])),
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
    case has(Body, Src, Pack) of
        true -> elines(Body, Src, emit(1, 1, E));
        false -> emit(1, 0, E)
    end;
eline({chain, First, Parts, EndsFx}, _Rest, Src, E) ->
    eparts(Parts, EndsFx, Src, elines(First, Src, E));
eline({len, Len, Unit, Plus, Body}, _Rest, Src, #e{pos = Pos, pack = Pack} = E) ->
    Start = Pos + Len,
    E1 = elines(Body, Src, E#e{pos = Start}),
    Bits = E1#e.pos - Start,
    Count = case Unit of
                bits -> Bits;
                bytes -> (Bits + 7) div 8       % padded with zero bits to a whole byte
            end,
    End = case Unit of
              bits -> E1#e.pos;
              bytes -> Start + Count * 8
          end,
    E1#e{pos = End, segs = [{Pos, Len, fits(Count + Plus, Len, Pack)} | E1#e.segs]};
eline({lenwhole, Len, Plus}, _Rest, _Src, #e{pos = Pos, segs = Segs} = E) ->
    E#e{pos = Pos + Len, segs = [{whole, Pos, Len, Plus} | Segs]};
eline({sgroup, List, Mode, Body}, _Rest, Src, #e{pack = Pack} = E) ->
    Items = maps:get(List, maps:get(lists, Src), []),
    Item = fun(I, Acc) -> eitem(I, Body, Acc) end,
    case Mode of
        {count, Len} ->
            %% an absent list writes a count of 0
            lists:foldl(Item, emit(Len, fits(length(Items), Len, Pack), E), Items);
        while ->
            emit(1, 0, lists:foldl(fun(I, Acc) -> Item(I, emit(1, 1, Acc)) end, E, Items));
        _ when Items =:= [] ->
            gt_engine:conv_error('transform-encode', Pack,
                                 "list ~s is absent or empty and its group holds at least one item",
                                 [List]);
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

ebits(Bools, E) ->
    lists:foldl(fun(true, Acc) -> emit(1, 1, Acc);
                   (false, Acc) -> emit(1, 0, Acc)
                end, E, Bools).

%% An fx bit is 1 when a line after it in the chain has content; the parts
%% after a 0 bit are not written. The bit of a closing fx line is 0.
eparts([], false, _Src, E) -> E;
eparts([], true, _Src, E) -> emit(1, 0, E);
eparts([Part | Rest] = Parts, EndsFx, Src, #e{pack = Pack} = E) ->
    case lists:any(fun(P) -> has(P, Src, Pack) end, Parts) of
        true -> eparts(Rest, EndsFx, Src, elines(Part, Src, emit(1, 1, E)));
        false -> emit(1, 0, E)
    end.

eitem(Item, Body, #e{pack = Pack} = E) ->
    {Lines, Src} = item_scope(Item, Body, Pack),
    elines(Lines, Src, E).

%% The lines an item is written by, and what it is written from: the lines
%% common to every item, then those of the kind the item recorded when it
%% was decoded from this format, else of the first kind whose every
%% `requires` name the item has.
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
            Has = fun(K) ->
                          maps:is_key(K, Model) orelse
                              case maps:find(K, Lists) of
                                  {ok, [_ | _]} -> true;
                                  _ -> false
                              end
                  end,
            Chosen = Recorded ++ [K || #{requires := Req} = K <- Kinds, lists:all(Has, Req)],
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

%% Would these lines write a present key (a key with a default counts), or a
%% list that is not empty?
has(Lines, Src, Pack) -> lists:any(fun(L) -> has1(L, Src, Pack) end, Lines).

has1({sfield, Keys, _, _, _, _, _, _}, Src, _Pack) -> pick(Keys, Src) =/= none;
has1({sgroup, List, _, _}, #{lists := Lists}, _Pack) ->
    case maps:find(List, Lists) of
        {ok, [_ | _]} -> true;
        _ -> false
    end;
has1({ifb, _, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({opt, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({len, _, _, _, Body}, Src, Pack) -> has(Body, Src, Pack);
has1({chain, First, Parts, _}, Src, Pack) ->
    lists:any(fun(P) -> has(P, Src, Pack) end, [First | Parts]);
has1(_, _Src, _Pack) -> false.

%% The bits of presence Id that are 1: those some `if` block names without
%% `!` and whose content is present. The blocks may stand in nested blocks
%% and in the items of groups.
scan(Lines, Src, Id, Pack, Acc) ->
    lists:foldl(fun(L, A) -> scan1(L, Src, Id, Pack, A) end, Acc, Lines).

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
scan1({len, _, _, _, Body}, Src, Id, Pack, Acc) -> scan(Body, Src, Id, Pack, Acc);
scan1({chain, First, Parts, _}, Src, Id, Pack, Acc) ->
    lists:foldl(fun(P, A) -> scan(P, Src, Id, Pack, A) end, Acc, [First | Parts]);
scan1({sgroup, List, _, Body}, #{lists := Lists}, Id, Pack, Acc) ->
    lists:foldl(
      fun(Item, A) ->
              %% an item that selects no kind of this group fails when the
              %% group is written, and the group may stand in a block that
              %% is not
              try item_scope(Item, Body, Pack) of
                  {Lines, ISrc} -> scan(Lines, ISrc, Id, Pack, A)
              catch
                  error:{convert_error, 'no-kind', _} -> A
              end
      end, Acc, maps:get(List, Lists, []));
scan1(_, _Src, _Id, _Pack, Acc) -> Acc.
