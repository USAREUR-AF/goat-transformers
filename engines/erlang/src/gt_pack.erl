%% gt_pack: parse a pack.def into a pack map (engine-spec Versions 0.1 - 0.13).
%% Clean-room implementation from spec/engine-spec.md and the packs only.
%%
%% Pack = #{name, version, wire, root, word_bytes, layout, bit_order, typemap,
%%          tables => #{Table => #{dec, enc, type}},
%%          distribution, sources, uses, has_kinds,
%%          common => [Line], defaults => [{Key, ValueText}],
%%          kinds => [Kind]}
%% Kind = #{name, root, requires => [Key], lines => [Line],
%%          defaults => [{Key, ValueText}]}
%% Line = {field, Key, Loc, Transform, LocText, Opts}
%%      | {wh, Loc, Value, LocText}          % `when`
%%      | {const, Loc, Value, LocText}
%%      | {group, List, GroupLoc, Spec, Body, LocText}
%%   Body = #{lines => [Line], defaults => [{Key, ValueText}]}; the locators
%%          of its lines are relative to one item
%%   Spec = none | {ItemBits, {loc, {BitOffset, Len}} | {fixed, N}}   (bits)
%%   GroupLoc, by wire:
%%     xml      [ElementName]: the items are the children named by the last
%%              name under the first element matched by the names before it
%%     geojson  {prop, Name} | {top, Name}; inside a group a json path
%%     json     [MemberName]
%%     protobuf [FieldNumber]
%%     bits     BitOffset of the first item in its scope
%%     text     the index of the item's first field; Spec {text_item, N}
%%   Key, LocText :: binary()
%%   Opts = {Via :: none | TableName, Swap, Trim, Optional, Absent}
%%   Absent = none | [Sentinel] (Version 0.9), the first is the one written:
%%     bits, and protobuf pvarint psint pdouble pfloat: the raw unsigned integer
%%     protobuf pstring, xml: the text
%%     json, geojson: {num, CanonicalText} | {bool, Text} | {str, Text}
%%   Loc, by wire:
%%     xml      {[ElementName :: binary()], {attr, binary()} | text}
%%     geojson  {geom, 1 | 2 | 3} | {prop, binary()} | {top, binary()}
%%     json     [MemberName :: binary()]; inside a group `.` is []
%%     bits     {BitOffsetInScope, Len}
%%     protobuf [FieldNumber]; inside a group `.` is []
%%     text     {fld, I} | {col, I, From, Len} | {pair, I, J}; inside a group
%%              relative to the item's first field
%%     tlv      {[Tag], Size :: none | 1..8}
%%   A text pack also has delimiter (binary() | none), start (binary(), <<>>
%%   for none) and checksum (none | nmea).
%%   A tlv pack also has tag_enc (ber_oid | 1 | 2 | 4), len_enc (ber | 1 | 2 |
%%   4), key (none | binary()) and sum16 (none | {sum16, Tag}).
%%   Inside a group a geojson pack uses the json locators.
%%   `when` Value: bits -> integer(); protobuf -> present | integer();
%%                 text wires -> present | {text, binary(), Forced :: boolean()}
%%                 tlv -> present | {uint, integer()}
%%   `const` Value: as a `when` value, never `present`.
%%
%% gt_engine:load_pack/2 checks the pack against the loaded modules, types the
%% defaults and adds the lookup indexes (index/1).
-module(gt_pack).
-export([parse/1, tokens/1, tokens_lax/1, load_error/3, distribution_atom/1,
         require_marking/2, yields/1, model_keys/1, named/1,
         index/1, factor/1, number/1]).

%% Parse a pack.def text (binary or string) -> pack map. Line errors are
%% raised as the file is read; then the checks that need the whole file; then
%% missing-distribution and missing-source. The checks against the loaded
%% modules run in gt_engine:load_pack/2.
parse(Text) when is_list(Text) -> parse(unicode:characters_to_binary(Text));
parse(Bin) ->
    RawLines = binary:split(Bin, <<"\n">>, [global]),
    %% the layout, the word size and whether the pack has kinds are read
    %% ahead, leniently; every line is checked when it is read below
    Lax = [T || L <- RawLines, T <- [tokens_lax(L)], T =/= []],
    Layout = case first_arg(<<"layout">>, Lax) of
                 <<"sequential">> -> sequential;
                 _ -> fixed
             end,
    Base = #{name => undefined, version => undefined,
             wire => undefined,
             root => undefined,
             word_bytes => first_arg(<<"word_bytes">>, Lax),
             layout => Layout,
             bit_order => lsb,
             %% in a sequential pack a `kind` line may belong to a group
             %% body; the flag is set when a kind of the message opens
             has_kinds => Layout =/= sequential andalso
                 lists:any(fun([<<"kind">> | _]) -> true; (_) -> false end, Lax),
             typemap => [], tables => #{}, table_names => [],
             distribution => undefined, sources => [], uses => [],
             common => [], defaults => [], kinds => [], kind_names => #{},
             delimiter => <<",">>, start => <<>>, checksum => none, text_seen => #{},
             tag_enc => ber_oid, len_enc => ber, key => none, sum16 => none, tlv_seen => #{},
             cur => common, late => [], gstack => [], sstack => [],
             headers => #{}, listed_seen => false},
    P0 = lists:foldl(fun(L, P) ->
                             case tokens(L) of
                                 [] -> P;
                                 T -> line(T, P)
                             end
                     end, Base, RawLines),
    %% after the file (ruling 5b of 0.11): missing-format, missing-version,
    %% missing-wire; then the checks that need the whole file; then
    %% missing-distribution and missing-source
    case maps:get(name, P0) of
        undefined -> load_error('missing-format', "the pack has no format line", []);
        _ -> ok
    end,
    case maps:get(version, P0) of
        undefined -> load_error('missing-version', "pack ~s has no version line", [name_str(P0)]);
        _ -> ok
    end,
    case maps:get(wire, P0) of
        undefined -> load_error('missing-wire', "pack ~s has no wire line", [name_str(P0)]);
        _ -> ok
    end,
    P1 = close_kind(P0),
    Tables = finish_tables(P1),
    Wire = maps:get(wire, P1),
    %% the checks that need the whole file, in file order (ruling 25 of 0.5)
    lists:foreach(
      fun({bad, Fmt, Args}) -> load_error('bad-directive', Fmt, Args);
         ({raw, Kind, Msg}) -> erlang:error({load_error, Kind, Msg});
         ({text_only, _Dir}) when Wire =:= text -> ok;
         ({tlv_only, _Dir}) when Wire =:= tlv -> ok;
         ({tlv_only, Text}) ->
              load_error('bad-directive', "~s is valid only on a tlv wire, not ~s", [Text, Wire]);
         ({text_only, Dir}) ->
              load_error('bad-directive', "~s is valid only on a text wire, not ~s", [Dir, Wire]);
         ({via, Table}) ->
              case maps:is_key(Table, Tables) of
                  true -> ok;
                  false -> load_error('bad-directive',
                                      "via names table ~s, which has no map line", [Table])
              end
      end, lists:reverse(maps:get(late, P1))),
    case maps:get(gstack, P0) of
        [] -> ok;
        [#{list := Open} | _] ->
            load_error('bad-directive', "group ~s has no end line", [Open])
    end,
    case maps:get(sstack, P0) of
        [] -> ok;
        [#{type := Type} | _] ->
            load_error('bad-directive', "a ~s block has no end line", [Type])
    end,
    P2 = P1#{common := lists:reverse(maps:get(common, P1)),
             kinds := lists:reverse(maps:get(kinds, P1))},
    case Wire of
        xml -> check_roots(P2);
        _ -> ok
    end,
    case {Wire, Layout, maps:get(word_bytes, P2)} of
        {bits, fixed, undefined} ->
            load_error('bad-directive', "the fixed-layout bits pack ~s has no word_bytes line",
                       [name_str(P2)]);
        _ -> ok
    end,
    case Wire of
        text -> text_checks(P2);
        tlv -> tlv_checks(P2);
        _ -> ok
    end,
    P3 = case Layout of
             sequential -> seq_resolve(P2);
             fixed -> check_scopes(P2), P2
         end,
    P = maps:without([cur, late, kind_names, table_names, gstack, sstack, text_seen, tlv_seen,
                      headers, listed_seen],
                     P3#{defaults := lists:reverse(maps:get(defaults, P1)),
                         typemap := lists:reverse(maps:get(typemap, P1)),
                         sources := lists:reverse(maps:get(sources, P1)),
                         uses := lists:reverse(maps:get(uses, P1)),
                         tables := Tables}),
    require_marking(["pack ", name_str(P)], P),
    P.

%% An xml pack needs a root for every message: the pack's, or one per kind.
check_roots(#{root := Root, kinds := Kinds, has_kinds := HasKinds} = P) ->
    Missing = case HasKinds of
                  false -> Root =:= undefined;
                  true -> Root =:= undefined andalso
                              lists:any(fun(#{root := R}) -> R =:= undefined end, Kinds)
              end,
    case Missing of
        true -> load_error('missing-root', "xml pack ~s has no root line", [name_str(P)]);
        false -> ok
    end.

%% Value of the first `<Directive> <arg>` line, interpreted: the wire and the
%% word size are needed to read every field and when line.
first_arg(Dir, Lines) ->
    case [A || [D, A] <- Lines, D =:= Dir] of
        [] -> undefined;
        [A | _] when Dir =:= <<"layout">> -> A;
        [A | _] when Dir =:= <<"word_bytes">> ->
            case uint(A) of
                N when is_integer(N), N >= 1 -> N;
                _ -> undefined
            end
    end.

name_str(#{name := undefined}) -> "?";
name_str(#{name := N}) -> N.

%% A pack or module must carry a distribution line and at least one source.
require_marking(What, #{distribution := D, sources := S}) ->
    case D of
        undefined -> load_error('missing-distribution', "~s has no distribution line", [What]);
        _ -> ok
    end,
    case S of
        [] -> load_error('missing-source', "~s has no source line", [What]);
        _ -> ok
    end.

%% Raise a load error. Kind is the spec's error kind as an atom; the message
%% begins with the kind and a colon.
load_error(Kind, Fmt, Args) ->
    Msg = lists:flatten(io_lib:format("~s: " ++ Fmt, [Kind | Args])),
    erlang:error({load_error, Kind, Msg}).

distribution_atom(<<"public">>) -> public;
distribution_atom(<<"controlled">>) -> controlled;
distribution_atom(D) when is_list(D) -> distribution_atom(list_to_binary(D));
distribution_atom(D) ->
    load_error('bad-directive', "distribution ~s is neither public nor controlled", [D]).

%% The model type a transform yields.
yields(string)  -> string;
yields(pstring) -> string;
yields(ascii)   -> string;
yields(float)   -> float;
yields({linscale, _, _}) -> float;
yields({uscale, _, _}) -> float;
yields({sscale, _, _}) -> float;
yields(f32)     -> float;
yields(f64)     -> float;
yields(utf8)    -> string;
yields(hex)     -> string;
yields(pdouble) -> float;
yields(pfloat)  -> float;
yields(int)        -> int;
yields(iso8601_ms) -> int;
yields(bool)       -> int;
yields(uint)       -> int;
yields(twos)       -> int;
yields(pvarint)    -> int;
yields(psint)      -> int;
yields({int_w, _})    -> int;
yields({dec, _, _})   -> float;
yields({dm, _, _, _, _}) -> float;
yields({hms, _})      -> float;
yields({hms_dmy, _})  -> int.

%% Every model name the pack uses, for the load checks -> [{Name, How}]:
%%   {field, Transform, Via}   a `field` line, also inside a group
%%   list                      the list of a `group` line
%%   requires                  a key or list of a `requires` line
%%   default                   the key of a `default` line, also inside a group
named(#{common := Common, defaults := Ds, kinds := Kinds}) ->
    Scopes = [{Common, Ds} | [{maps:get(lines, K), maps:get(defaults, K)} || K <- Kinds]],
    lists:append([named_scope(Ls, D) || {Ls, D} <- Scopes])
        ++ [{K, requires} || Kd <- Kinds, K <- maps:get(requires, Kd)].

named_scope(Lines, Defaults) ->
    lists:append(
      [case L of
           {field, K, _, Tr, _, Opts} -> [{K, {field, Tr, element(1, Opts)}}];
           {group, List, _, _, #{lines := Ls, defaults := Ds}, _} ->
               [{List, list} | named_scope(Ls, Ds)];
           {sfield, Keys, _, Tr, _, _, _, _} -> [{K, {field, Tr, Via}} || {K, Via} <- Keys];
           {sgroup, List, _, #{lines := Ls, defaults := Ds, kinds := Ks}} ->
               [{List, list} | named_scope(Ls, Ds)] ++
                   lists:append([named_scope(maps:get(lines, K), maps:get(defaults, K))
                                 || K <- Ks]) ++
                   [{R, requires} || K <- Ks, R <- maps:get(requires, K)];
           _ ->
               case seq_bodies(L) of
                   [] -> [];
                   Bodies -> named_scope(lists:append(Bodies), [])
               end
       end || L <- Lines]) ++ [{K, default} || {K, _} <- Defaults].

%% The bodies of a sequential block line that belong to the scope the line
%% stands in (`if`, `opt`, `length`, `chain`).
seq_bodies({ifb, _, Body}) -> [Body];
seq_bodies({opt, Body}) -> [Body];
seq_bodies({len, _, _, _, Body}) -> [Body];
seq_bodies({chain, First, Rest, _}) -> [First | Rest];
seq_bodies(_) -> [].

%% Union of mapped keys over common and all kinds, in first appearance order.
%% A list is named `<list>[]` and an item key `<list>[].<key>`, nested lists
%% likewise.
model_keys(#{common := Common, kinds := Kinds}) ->
    Names = lists:append([key_names(L, <<>>) || L <- [Common | [maps:get(lines, K) || K <- Kinds]]]),
    {Keys, _} = lists:foldl(fun(K, {Acc, Seen}) ->
                                    case maps:is_key(K, Seen) of
                                        true -> {Acc, Seen};
                                        false -> {[K | Acc], Seen#{K => true}}
                                    end
                            end, {[], #{}}, Names),
    lists:reverse(Keys).

key_names(Lines, Prefix) ->
    lists:append(
      [case L of
           {field, K, _, _, _, _} -> [<<Prefix/binary, K/binary>>];
           {group, List, _, _, #{lines := Ls}, _} ->
               Name = <<Prefix/binary, List/binary, "[]">>,
               [Name | key_names(Ls, <<Name/binary, ".">>)];
           {sfield, Keys, _, _, _, _, _, _} -> [<<Prefix/binary, K/binary>> || {K, _} <- Keys];
           {sgroup, List, _, #{lines := Ls, kinds := Ks}} ->
               Name = <<Prefix/binary, List/binary, "[]">>,
               [Name | key_names(Ls ++ lists:append([maps:get(lines, K) || K <- Ks]),
                                 <<Name/binary, ".">>)];
           _ -> key_names(lists:append(seq_bodies(L)), Prefix)
       end || L <- Lines]).

%% Lookup indexes over the kinds: by name, and (xml) by root element name in
%% pack order, so that a catalog of several hundred kinds selects in one
%% lookup.
index(#{kinds := Kinds, root := PackRoot} = P) ->
    ByName = maps:from_list([{maps:get(name, K), K} || K <- Kinds]),
    ByRoot = lists:foldr(
               fun(#{root := R} = K, Acc) ->
                       Root = case R of undefined -> PackRoot; _ -> R end,
                       maps:update_with(Root, fun(L) -> [K | L] end, [K], Acc)
               end, #{}, Kinds),
    P#{kind_index => ByName, root_index => ByRoot}.

%% ===================================================================
%% directives
%% ===================================================================
%% One line. Inside a group `when`, `requires`, `root`, `kind`, `map` and
%% `typemap` are not allowed.
%% Each line is checked in the order of ruling 5b of 0.11: the quotes (by
%% tokens/1), the directive, the number of arguments, the `wire` line before
%% it, a repeated header line, the wire and distribution values; then the
%% transform, the locator, the field options and the `absent` values, which
%% raise {line_error, ...}. Any other failure of the line is checked after
%% the file is read, in file order.
line(Tokens, P0) ->
    P = try pre_line(Tokens, P0)
        catch error:{line_error, K, M} -> erlang:error({load_error, K, M})
        end,
    try dispatch(Tokens, P)
    catch
        error:{line_error, Kind, Msg} -> erlang:error({load_error, Kind, Msg});
        error:{load_error, Kind, Msg} -> late({raw, Kind, Msg}, P)
    end.

%% A failure that is a line check (ruling 5b of 0.11).
line_error(Kind, Fmt, Args) ->
    Msg = lists:flatten(io_lib:format("~s: " ++ Fmt, [Kind | Args])),
    erlang:error({line_error, Kind, Msg}).

%% The directives of a pack (ruling 5 of 0.11).
pack_directives() ->
    [<<"format">>, <<"version">>, <<"distribution">>, <<"source">>, <<"uses">>, <<"wire">>,
     <<"root">>, <<"field">>, <<"when">>, <<"const">>, <<"kind">>, <<"requires">>,
     <<"default">>, <<"map">>, <<"typemap">>, <<"group">>, <<"end">>, <<"word_bytes">>,
     <<"bit_order">>, <<"layout">>, <<"also">>, <<"pad">>, <<"align">>, <<"presence">>,
     <<"if">>, <<"opt">>, <<"chain">>, <<"fx">>, <<"length">>, <<"delimiter">>,
     <<"start">>, <<"checksum">>,
     %% the `tlv` wire (Version 0.13)
     <<"tag">>, <<"key">>].

%% The lines that stand after the `wire` line (ruling 5b of 0.11).
after_wire() ->
    [<<"root">>, <<"field">>, <<"when">>, <<"const">>, <<"group">>, <<"end">>,
     <<"word_bytes">>, <<"bit_order">>, <<"layout">>, <<"also">>, <<"pad">>, <<"align">>,
     <<"presence">>, <<"if">>, <<"opt">>, <<"chain">>, <<"fx">>, <<"length">>].

%% Does a directive take this number of arguments? (ruling 5e of 0.11)
arg_count_ok(Dir, N) ->
    One = [<<"format">>, <<"version">>, <<"distribution">>, <<"source">>, <<"uses">>,
           <<"wire">>, <<"root">>, <<"kind">>, <<"word_bytes">>, <<"bit_order">>,
           <<"layout">>, <<"pad">>, <<"align">>, <<"delimiter">>, <<"start">>,
           <<"checksum">>],
    case lists:member(Dir, One) of
        true -> N =:= 1;
        false ->
            case Dir of
                <<"field">> -> N >= 3;
                <<"when">> -> N =:= 2;
                <<"const">> -> N =:= 2;
                <<"default">> -> N =:= 2;
                <<"map">> -> N =:= 3;
                <<"typemap">> -> N =:= 2;
                <<"group">> -> N >= 2;
                <<"presence">> -> N =:= 2;
                <<"end">> -> N =:= 0;
                <<"opt">> -> N =:= 0;
                <<"chain">> -> N =:= 0;
                <<"fx">> -> N =:= 0;
                _ -> N >= 1                       % requires, also, if, length
            end
    end.

pre_line([Dir | Args], P0) ->
    %% only a one-argument `key` is the directive of the tlv wire; any other
    %% `key` is the model-module form (ruling 11 of 0.13)
    IsDirective = lists:member(Dir, pack_directives())
        andalso not (Dir =:= <<"key">> andalso length(Args) =/= 1),
    case IsDirective of
        true -> ok;
        false -> line_error('unknown-directive', "~s is not a directive of a pack", [Dir])
    end,
    %% `checksum sum16 <tag>` of the tlv wire takes two (ruling 12 of 0.13)
    CountOk = case {Dir, Args} of
                  {<<"checksum">>, [<<"sum16">>, _]} -> true;
                  _ -> arg_count_ok(Dir, length(Args))
              end,
    case CountOk of
        true -> ok;
        false -> line_error('bad-directive', "~s does not take ~p argument(s)", [Dir, length(Args)])
    end,
    Listed = lists:member(Dir, after_wire()),
    case Listed andalso maps:get(wire, P0) =:= undefined of
        true -> line_error('missing-wire', "~s stands before the wire line", [Dir]);
        false -> ok
    end,
    Headers = maps:get(headers, P0),
    IsHeader = lists:member(Dir, [<<"format">>, <<"version">>, <<"wire">>, <<"distribution">>]),
    case IsHeader andalso maps:is_key(Dir, Headers) of
        true -> line_error('bad-directive', "a second ~s line", [Dir]);
        false -> ok
    end,
    P1 = case IsHeader of
             true -> P0#{headers := Headers#{Dir => true}};
             false -> P0
         end,
    P2 = case {Dir, Args} of
             {<<"wire">>, [W]} -> P1#{wire := wire_atom(W)};
             {<<"distribution">>, [D]} ->
                 case D of
                     <<"public">> -> P1;
                     <<"controlled">> -> P1;
                     _ -> line_error('bad-directive',
                                     "distribution ~s is neither public nor controlled", [D])
                 end;
             _ -> P1
         end,
    %% `layout sequential` stands before every line of the list
    case {Dir, Args, maps:get(listed_seen, P2)} of
        {<<"layout">>, [<<"sequential">>], true} ->
            line_error('bad-directive', "layout sequential stands after a line it must precede", []);
        _ -> ok
    end,
    case Listed andalso Dir =/= <<"layout">> of
        true -> P2#{listed_seen := true};
        false -> P2
    end.

dispatch(Tokens, #{layout := sequential, wire := bits} = P) -> seq_line(Tokens, P);
dispatch([Dir | _] = Tokens, #{gstack := Stack} = P) ->
    %% inside a group only these are lines of the body (ruling 18 of 0.7);
    %% a name that is no directive at all stays unknown-directive
    Allowed = [<<"field">>, <<"const">>, <<"default">>, <<"group">>, <<"end">>],
    case Stack =/= [] andalso not lists:member(Dir, Allowed)
        andalso lists:member(Dir, known_directives()) of
        true -> load_error('bad-directive', "~s is not allowed inside a group", [Dir]);
        false -> apply_line(Tokens, P)
    end.

known_directives() ->
    [<<"format">>, <<"version">>, <<"wire">>, <<"root">>, <<"word_bytes">>,
     <<"bit_order">>, <<"distribution">>, <<"source">>, <<"uses">>, <<"typemap">>,
     <<"kind">>, <<"requires">>, <<"when">>, <<"field">>, <<"const">>,
     <<"default">>, <<"map">>, <<"group">>, <<"end">>,
     <<"layout">>, <<"pad">>, <<"align">>, <<"presence">>, <<"if">>, <<"opt">>,
     <<"chain">>, <<"fx">>, <<"length">>, <<"also">>,
     <<"delimiter">>, <<"start">>, <<"checksum">>, <<"tag">>, <<"key">>].

in_group(#{gstack := Stack}) -> Stack =/= [].

apply_line([<<"format">>, N], P)   -> P#{name => N};
apply_line([<<"version">>, V], P)  -> P#{version => V};
apply_line([<<"wire">>, _W], P)    -> P;                         % read by pre_line/2
apply_line([<<"root">>, R], #{cur := Cur} = P) ->
    case Cur of
        common -> P#{root => R};
        #{} ->
            case maps:get(wire, P) of
                xml -> P#{cur := Cur#{root := R}};
                _ -> load_error('bad-directive', "root inside a kind is valid only on an xml wire", [])
            end
    end;
apply_line([<<"word_bytes">>, N], P) -> _ = word_bytes(N), P;    % read by first_arg
apply_line([<<"checksum">> | Args], #{wire := tlv} = P) -> tlv_directive(checksum, Args, P);
apply_line([<<"length">> | Args], #{wire := tlv} = P) -> tlv_directive(length, Args, P);
apply_line([<<"tag">> | Args], P) -> tlv_directive(tag, Args, P);
apply_line([<<"key">> | Args], P) -> tlv_directive(key, Args, P);
apply_line([<<"checksum">>, <<"sum16">>, _] = Args, P) ->
    tlv_directive(checksum, tl(Args), P);
apply_line([Dir, V], P) when Dir =:= <<"delimiter">>; Dir =:= <<"start">>;
                             Dir =:= <<"checksum">> ->
    text_directive(binary_to_atom(Dir), V, P);
apply_line([<<"layout">>, L], #{wire := Wire} = P) ->
    case {Wire, L} of
        {bits, <<"sequential">>} -> P;                            % read by first_arg
        {bits, <<"fixed">>} -> P;
        {bits, _} -> load_error('bad-directive', "layout ~s is neither fixed nor sequential", [L]);
        _ -> load_error('bad-directive', "layout is valid only on a bits wire", [])
    end;
apply_line([<<"bit_order">>, O], #{wire := Wire} = P0) ->
    P = case Wire of
            bits -> P0;
            _ -> late({bad, "bit_order is valid only on a bits wire", []}, P0)
        end,
    case O of
        <<"lsb">> -> P#{bit_order => lsb};
        <<"msb">> -> P#{bit_order => msb};
        _ -> load_error('bad-directive', "bit_order ~s is neither lsb nor msb", [O])
    end;
apply_line([<<"distribution">>, D], P) -> P#{distribution => distribution_atom(D)};
apply_line([<<"source">>, S], P)   -> P#{sources := [S | maps:get(sources, P)]};
apply_line([<<"uses">>, M], P)     -> P#{uses := [M | maps:get(uses, P)]};
apply_line([<<"typemap">>, Native, Cot], P) ->
    P#{typemap := [{Native, Cot} | maps:get(typemap, P)]};
apply_line([<<"map">>, Table, Native, Model], #{tables := Ts, table_names := Names} = P) ->
    case maps:find(Table, Ts) of
        {ok, L} -> P#{tables := Ts#{Table := [{Native, Model} | L]}};
        error -> P#{tables := Ts#{Table => [{Native, Model}]}, table_names := [Table | Names]}
    end;
apply_line([<<"kind">>, Name], P0) ->
    #{kind_names := Names} = P = close_kind(P0),
    case maps:is_key(Name, Names) of
        false -> ok;
        true -> load_error('duplicate-kind', "kind ~s is declared twice", [Name])
    end,
    P#{cur := #{name => Name, root => undefined, requires => [], lines => [], defaults => []},
       kind_names := Names#{Name => true}};
apply_line([<<"requires">> | Keys], #{cur := Cur} = P) when Keys =/= [] ->
    case Cur of
        common ->
            load_error('bad-directive', "requires before the first kind line", []);
        #{requires := R} ->
            P#{cur := Cur#{requires := R ++ Keys}}
    end;
apply_line([<<"when">>, LocS, ValS], #{has_kinds := HasKinds} = P0) ->
    P1 = case HasKinds of
             false -> late({bad, "when ~s in a pack with no kind line", [LocS]}, P0);
             true -> P0
         end,
    Wire = need_wire(P1),
    Loc = parse_loc(Wire, LocS, P1),
    no_pair(Loc, "when", LocS),
    {Val, P2} = fixed_value(wh, Wire, Loc, LocS, ValS, P1),
    add_line({wh, Loc, Val, LocS}, P2);
apply_line([<<"const">>, LocS, ValS], P0) ->
    Wire = need_wire(P0),
    Loc = parse_loc(Wire, LocS, P0),
    case Loc of
        [] -> load_error('bad-directive', "const . names the item itself", []);
        _ -> ok
    end,
    no_pair(Loc, "const", LocS),
    {Val, P1} = fixed_value(const, Wire, Loc, LocS, ValS, P0),
    add_line({const, Loc, Val, LocS}, P1);
apply_line([<<"default">>, Key, Val], #{gstack := [#{defaults := D} = G | Rest]} = P) ->
    P#{gstack := [G#{defaults := [{Key, Val} | D]} | Rest]};
apply_line([<<"default">>, Key, Val], #{cur := Cur} = P) ->
    case Cur of
        common -> P#{defaults := [{Key, Val} | maps:get(defaults, P)]};
        #{defaults := D} -> P#{cur := Cur#{defaults := [{Key, Val} | D]}}
    end;
apply_line([<<"group">>, List, _LocS | _], #{wire := tlv}) ->
    load_error('bad-directive', "group ~s: groups are not allowed on a tlv wire in 0.13", [List]);
apply_line([<<"group">>, List, LocS | Rest], #{gstack := Stack} = P) ->
    Wire = need_wire(P),
    Loc = group_loc(Wire, LocS, in_group(P), P),
    %% a group's options are checked after the file is read (ruling 5b of 0.11)
    {Spec, P1} = try {group_spec(Wire, Rest, LocS, P), P}
                 catch error:{load_error, K, M} -> {none, late({raw, K, M}, P)}
                 end,
    G = #{list => List, loc => Loc, spec => Spec, loct => LocS,
          lines => [], defaults => []},
    P1#{gstack := [G | Stack]};
apply_line([<<"end">>], #{gstack := Stack} = P) ->
    case Stack of
        [] -> load_error('bad-directive', "end with no open group", []);
        [#{list := List, loc := Loc, spec := Spec, loct := LocS, lines := Ls, defaults := Ds}
         | Rest] ->
            Body = #{lines => lists:reverse(Ls), defaults => lists:reverse(Ds)},
            add_line({group, List, Loc, Spec, Body, LocS}, P#{gstack := Rest})
    end;
apply_line([<<"field">>, Key, LocS, TrS | OptToks], P0) ->
    Wire = need_wire(P0),
    {Tr, TrChecks} = parse_transform(Wire, TrS),
    Loc = parse_loc(Wire, LocS, P0),
    {_Via, Swap, Trim, Optional, _} = Opts0 = parse_opts(OptToks, {none, false, false, false, none}),
    Len = case Wire of
              bits -> element(2, Loc);
              _ -> Loc                            % a geojson coordinate (ruling 25 of 0.9)
          end,
    {Opts, AbsentChecks} = sentinels(Wire, Tr, Len, Opts0),
    IsPair = case Loc of {pair, _, _} -> true; _ -> false end,
    Checks = TrChecks ++
        [{bad, "~s on ~s: a pair is only for dm and hms_dmy, and they only take a pair",
          [TrS, LocS]}
         || Wire =:= text, IsPair =/= gt_text:pair_transform(Tr)] ++
        [{bad, "optional on ~s: not allowed inside a group", [LocS]}
         || Optional, Wire =:= text, in_group(P0)] ++
        [{bad, "~s does not allow the bit length of ~s", [TrS, LocS]}
         || not len_ok(Wire, Tr, Loc)] ++
        [{bad, "swap on ~s: valid only on a bits wire, with a length that is a multiple of 8", [LocS]}
         || Swap, not (Wire =:= bits andalso element(2, Loc) rem 8 =:= 0)] ++
        [{bad, "trim on ~s: valid only on a bits wire, with ascii", [LocS]}
         || Trim, not (Wire =:= bits andalso Tr =:= ascii)] ++
        [{bad, "optional on ~s: valid only on a bits or text wire", [LocS]}
         || Optional, Wire =/= bits, Wire =/= text] ++
        [{via, T} || T <- [element(1, Opts)], T =/= none] ++
        AbsentChecks ++
        [{bad, "~s on ~s: ~s", [TrS, LocS, Why]}
         || Wire =:= tlv, Why <- [tlv_size_check(Tr, Loc)], Why =/= ok],
    P1 = lists:foldl(fun late/2, P0, Checks),
    add_line({field, Key, Loc, Tr, LocS, Opts}, P1);
apply_line([Dir | Args], _P) ->
    %% the lines of a sequential pack are here too: in a fixed-layout pack,
    %% or on another wire, they are bad-directive
    case lists:member(Dir, known_directives()) of
        true -> load_error('bad-directive', "~s takes a different number of arguments than ~p",
                           [Dir, length(Args)]);
        false -> load_error('unknown-directive', "~s", [Dir])
    end.

late(Check, #{late := L} = P) -> P#{late := [Check | L]}.

%% Field options after the transform, in any order.
%% An unknown or repeated option is bad-directive.
parse_opts([], Opts) -> Opts;
parse_opts([<<"via">>, Table | Rest], Opts) -> parse_opts(Rest, set_opt(1, none, Table, <<"via">>, Opts));
parse_opts([<<"swap">> | Rest], Opts) -> parse_opts(Rest, set_opt(2, false, true, <<"swap">>, Opts));
parse_opts([<<"trim">> | Rest], Opts) -> parse_opts(Rest, set_opt(3, false, true, <<"trim">>, Opts));
parse_opts([<<"optional">> | Rest], Opts) ->
    parse_opts(Rest, set_opt(4, false, true, <<"optional">>, Opts));
%% the token after `absent` is always its argument (ruling 11 of 0.9)
parse_opts([<<"absent">>, Arg | Rest], Opts) ->
    parse_opts(Rest, set_opt(5, none, {arg, Arg}, <<"absent">>, Opts));
parse_opts([<<"absent">>], _) -> line_error('bad-directive', "absent names no value", []);
parse_opts([<<"via">>], _) -> line_error('bad-directive', "via names no table", []);
parse_opts([Other | _], _) -> line_error('bad-directive', "unknown field option ~s", [Other]).

set_opt(I, Unset, Value, Name, Opts) ->
    case element(I, Opts) of
        Unset -> setelement(I, Opts, Value);
        _ -> line_error('bad-directive', "field option ~s is given twice", [Name])
    end.

need_wire(#{wire := undefined}) ->
    load_error('bad-directive', "the pack has no wire line", []);
need_wire(#{wire := W}) -> W.

add_line(Line, #{gstack := [#{lines := Ls} = G | Rest]} = P) ->
    P#{gstack := [G#{lines := [Line | Ls]} | Rest]};
add_line(Line, #{cur := common, common := C} = P) -> P#{common := [Line | C]};
add_line(Line, #{cur := #{lines := Ls} = Cur} = P) -> P#{cur := Cur#{lines := [Line | Ls]}}.

close_kind(#{cur := common} = P) -> P;
close_kind(#{cur := #{lines := Ls, defaults := Ds} = Cur, kinds := Kinds} = P) ->
    P#{cur := common,
       kinds := [Cur#{lines := lists:reverse(Ls), defaults := lists:reverse(Ds)} | Kinds]}.

wire_atom(<<"xml">>) -> xml;
wire_atom(<<"geojson">>) -> geojson;
wire_atom(<<"json">>) -> json;
wire_atom(<<"bits">>) -> bits;
wire_atom(<<"protobuf">>) -> protobuf;
wire_atom(<<"text">>) -> text;
wire_atom(<<"tlv">>) -> tlv;
wire_atom(W) -> line_error('unknown-wire', "~s", [W]).

word_bytes(S) ->
    case uint(S) of
        N when is_integer(N), N >= 1 -> N;
        _ -> load_error('bad-directive', "word_bytes ~s is not a positive integer", [S])
    end.

%% unsigned decimal integer -> integer() | error
uint(<<>>) -> error;
uint(B) ->
    case all_digits(B) of
        true -> binary_to_integer(B);
        false -> error
    end.

all_digits(<<>>) -> true;
all_digits(<<C, R/binary>>) when C >= $0, C =< $9 -> all_digits(R);
all_digits(_) -> false.

%% ===================================================================
%% absent-value sentinels (Version 0.9)
%% ===================================================================
%% The `absent` argument of a field line, read for its wire and transform
%% -> {Opts with Absent = none | [Sentinel], LateChecks}. A value the wire
%% cannot hold is bad-directive, checked in file order with the other
%% checks of the line.
sentinels(Wire, Tr, Len, Opts) ->
    case element(5, Opts) of
        none -> {Opts, []};
        {arg, Arg} ->
            %% the values are a line check, except on a bits field longer than
            %% 64 bits, which the check of its length after the file refuses
            %% (rulings 4d and 5b of 0.11)
            try absent_values(Wire, Tr, Len, Arg) of
                Values -> {setelement(5, Opts, Values), []}
            catch
                throw:{absent_bad, Fmt, Args} ->
                    %% `absent` on tlv is whether an option fits its wire,
                    %% checked after the file (ruling 14 of 0.13)
                    case (Wire =:= bits andalso is_integer(Len) andalso Len > 64)
                        orelse Wire =:= tlv of
                        true -> {setelement(5, Opts, none), [{bad, Fmt, Args}]};
                        false -> line_error('bad-directive', Fmt, Args)
                    end
            end
    end.

absent_bad(Fmt, Args) -> throw({absent_bad, Fmt, Args}).

%% Len: on bits the field's bit length, on the other wires its locator.
absent_values(Wire, Tr, Len, Arg) ->
    %% the quoted empty token is the one value "the empty text"
    Values = case Arg of
                 <<>> -> [<<>>];
                 _ ->
                     Vs = binary:split(Arg, <<",">>, [global]),
                     case lists:member(<<>>, Vs) of
                         true -> absent_bad("absent ~s: an empty value in the list", [Arg]);
                         false -> Vs
                     end
             end,
    [absent_bad("absent ~s: a value holds a double quote", [Arg])
     || V <- Values, binary:match(V, <<"\"">>) =/= nomatch],
    case Wire of
        bits when Len > 64 ->
            absent_bad("absent on a bits field of ~p bits, longer than 64", [Len]);
        bits -> [absent_int(V, Len) || V <- Values];
        protobuf ->
            case Tr of
                pstring -> Values;                     % `=` is part of the text
                pfloat -> [absent_int(V, 32) || V <- Values];
                _ -> [absent_int(V, 64) || V <- Values]
            end;
        xml -> [absent_text(V) || V <- Values];
        %% `absent` on `text` is bad-directive (ruling 16 of 0.10)
        text -> absent_bad("absent ~s: not a field option on a text wire", [Arg]);
        %% `absent` on `tlv` is bad-directive (ruling 10 of 0.13)
        tlv -> absent_bad("absent ~s: not a field option on a tlv wire", [Arg]);
        _ ->                                           % json, geojson
            Js = [absent_json(V) || V <- Values],
            %% a geojson coordinate takes only number text (ruling 25 of 0.9)
            case Wire =:= geojson andalso element(1, Len) =:= geom
                andalso [J || {T, _} = J <- Js, T =/= num] =/= [] of
                true -> absent_bad("absent ~s: a geojson coordinate takes only numbers", [Arg]);
                false -> ok
            end,
            case Tr =:= bool andalso [J || {T, _} = J <- Js, T =/= bool] =/= [] of
                true -> absent_bad("absent ~s: a bool field holds only true or false", [Arg]);
                false -> Js
            end
    end.

%% an unsigned decimal integer below 2^Bits
absent_int(V, Bits) ->
    case uint(V) of
        N when is_integer(N), N < (1 bsl Bits) -> N;
        N when is_integer(N) -> absent_bad("absent ~s does not fit ~p bits", [V, Bits]);
        error -> absent_bad("absent ~s is not an unsigned decimal integer", [V])
    end.

%% text, a leading `=` stripped; only `""` names the empty text
absent_text(<<>>) -> <<>>;
absent_text(<<$=>>) -> absent_bad("absent =: the value is empty after the =", []);
absent_text(<<$=, T/binary>>) -> T;
absent_text(V) -> V.

%% json and geojson: number text is held as its canonical text, `true` and
%% `false` are booleans, `=` forces a string; `null` is no sentinel
absent_json(<<>>) -> {str, <<>>};
absent_json(<<$=, _/binary>> = V) -> {str, absent_text(V)};
absent_json(<<"null">>) -> absent_bad("absent null: null is not a value", []);
absent_json(V) when V =:= <<"true">>; V =:= <<"false">> -> {bool, V};
absent_json(V) ->
    case gt_json:read_number(V) of
        {ok, Canonical} -> {num, Canonical};
        out_of_range -> absent_bad("absent ~s does not fit a double", [V]);
        not_number -> {str, V}
    end.

%% ===================================================================
%% value tables
%% ===================================================================
%% Table = #{dec => #{Type => #{NativeText => ModelText}},
%%           enc => #{Type => #{ModelText => NativeText}},
%%           type => string | int | float}.
%% A value is looked up by its canonical text in the map of its own type,
%% where each entry is canonicalised as a value of that type is (so the
%% entry `01` matches the integer 1); an entry that cannot be read as the
%% type keeps its text. Where several entries share a value, the first is
%% used. `type` is the type of the model side: string unless every model
%% value is an integer (int) or every one a number (float).
finish_tables(#{tables := Ts}) ->
    maps:map(
      fun(_Name, RevEntries) ->
              %% folding the reversed list, the first entry of the file is put last
              Side = fun(Pairs) ->
                             maps:from_list(
                               [{T, maps:from_list([{canon_as(T, K), V} || {K, V} <- Pairs])}
                                || T <- [string, int, float]])
                     end,
              Models = [M || {_, M} <- RevEntries],
              Type = case lists:all(fun is_int_text/1, Models) of
                         true -> int;
                         false ->
                             case lists:all(fun is_number_text/1, Models) of
                                 true -> float;
                                 false -> string
                             end
                     end,
              #{dec => Side(RevEntries), enc => Side([{M, N} || {N, M} <- RevEntries]),
                type => Type}
      end, Ts).

canon_as(Type, Text) ->
    try gt_num:canon(gt_num:read_as(Type, Text))
    catch _:_ -> Text
    end.

%% an entry is an integer when 2a of 0.11 accepts it, a number when 2b does
is_int_text(B) -> gt_num:int_text(B) =/= error.

is_number_text(B) -> gt_num:num_text(B) =/= error.

%% ===================================================================
%% locators
%% ===================================================================
%% Inside a group a locator is relative to one item: the same forms, and on
%% json, geojson and protobuf also `.` for the item itself.
parse_loc(tlv, S, _P) -> tlv_loc(S);
parse_loc(text, S, P) ->
    Loc = text_loc(S),
    case maps:get(gstack, P) of
        [#{spec := {text_item, N}} | _] ->
            case lists:all(fun(K) -> K < N end, gt_text:loc_indexes(Loc)) of
                true -> ok;
                false -> line_error('bad-directive', "locator ~s lies beyond an item of ~p fields",
                                    [S, N])
            end;
        _ -> ok
    end,
    Loc;
parse_loc(Wire, S, P) ->
    case in_group(P) of
        false -> top_loc(Wire, S, P);
        true ->
            case {Wire, S} of
                {geojson, <<".">>} -> [];
                {json, <<".">>} -> [];
                {protobuf, <<".">>} -> [];
                {geojson, _} -> top_loc(json, S, P);
                _ -> top_loc(Wire, S, P)
            end
    end.

%% The locator forms of ruling 5a of 0.11: a form the line does not take on
%% the pack's wire is bad-locator, raised as the line is read.
top_loc(xml, S, _P) ->
    Parts = binary:split(S, <<"/">>, [global]),
    case lists:member(<<>>, Parts) of
        true -> line_error('bad-locator', "xml locator ~s has an empty step", [S]);
        false -> ok
    end,
    Path = lists:droplast(Parts),
    case [X || X <- Path, is_leaf_step(X)] of
        [] -> ok;
        _ -> line_error('bad-locator', "xml locator ~s has a step after @name or #text", [S])
    end,
    case lists:last(Parts) of
        <<"@">> -> line_error('bad-locator', "xml locator ~s has an empty attribute name", [S]);
        <<"@", A/binary>> -> {Path, {attr, A}};
        <<"#text">> -> {Path, text};
        _ -> line_error('bad-locator', "xml locator ~s does not end in @name or #text", [S])
    end;
top_loc(geojson, <<"geometry.lon">>, _P) -> {geom, 1};
top_loc(geojson, <<"geometry.lat">>, _P) -> {geom, 2};
top_loc(geojson, <<"geometry.alt">>, _P) -> {geom, 3};
top_loc(geojson, <<"geometry.", _/binary>> = S, _P) ->
    line_error('bad-locator', "geojson locator ~s: geometry. is followed by lon, lat or alt", [S]);
top_loc(geojson, <<"properties.">> = S, _P) ->
    line_error('bad-locator', "geojson locator ~s has an empty member name", [S]);
top_loc(geojson, <<"properties.", Name/binary>>, _P) -> {prop, Name};
top_loc(geojson, <<>>, _P) ->
    line_error('bad-locator', "geojson locator with an empty member name", []);
top_loc(geojson, Name, _P) -> {top, Name};
top_loc(json, <<".">>, _P) ->
    line_error('bad-directive', "the locator . stands outside a group", []);
top_loc(json, S, _P) ->
    Parts = binary:split(S, <<".">>, [global]),
    case lists:member(<<>>, Parts) of
        true -> line_error('bad-locator', "json path ~s has an empty member name", [S]);
        false -> Parts
    end;
top_loc(bits, S, #{word_bytes := WB0}) ->
    %% a missing word_bytes line is checked after the file is read
    WB = case WB0 of
             undefined -> 1;
             _ -> WB0
         end,
    %% a bit length (digits only) as the locator is bad-directive; any other
    %% text that is not <word>:<pos>:<len> is bad-locator (ruling 5a of 0.11)
    case binary:match(S, <<":">>) =:= nomatch andalso uint(S) =/= error of
        true -> line_error('bad-directive',
                           "bits locator ~s is a bit length in a fixed-layout pack", [S]);
        false -> ok
    end,
    case [uint(X) || X <- binary:split(S, <<":">>, [global])] of
        [W, Pos, Len] when is_integer(W), is_integer(Pos), is_integer(Len), Len >= 1 ->
            {W * WB * 8 + Pos, Len};
        _ -> line_error('bad-locator', "bits locator ~s is not <word>:<pos>:<len>", [S])
    end;
top_loc(protobuf, <<".">>, _P) ->
    line_error('bad-directive', "the locator . stands outside a group", []);
top_loc(protobuf, S, _P) ->
    Nums = [uint(X) || X <- binary:split(S, <<".">>, [global])],
    case lists:all(fun(N) -> is_integer(N) andalso N >= 1 andalso N =< 536870911 end, Nums) of
        true -> Nums;
        false -> line_error('bad-locator', "protobuf path ~s is not field numbers from 1 to 536870911", [S])
    end.

is_leaf_step(<<"@", _/binary>>) -> true;
is_leaf_step(<<"#text">>) -> true;
is_leaf_step(_) -> false.

%% The locator of a `group` line.
group_loc(text, S, true, _P) ->
    load_error('bad-directive', "group at ~s is inside a group: text groups do not nest", [S]);
group_loc(text, S, false, _P) ->
    case uint(S) of
        I when is_integer(I) -> I;
        error -> load_error('bad-directive', "text group index ~s is not a field index", [S])
    end;
group_loc(xml, S, _InGroup, _P) ->
    Parts = binary:split(S, <<"/">>, [global]),
    case lists:member(<<>>, Parts) of
        true -> line_error('bad-locator', "xml locator ~s has an empty step", [S]);
        false -> ok
    end,
    Ok = lists:all(fun(<<>>) -> false;
                      (<<"@", _/binary>>) -> false;
                      (<<"#", _/binary>>) -> false;
                      (_) -> true
                   end, Parts),
    case Ok of
        true -> Parts;
        false -> load_error('bad-directive', "xml group locator ~s is not a path of element names", [S])
    end;
group_loc(geojson, <<"geometry", _/binary>> = S, false, _P) ->
    load_error('bad-directive', "geojson group locator ~s is not a member that holds an array", [S]);
group_loc(geojson, S, false, P) -> top_loc(geojson, S, P);
group_loc(geojson, S, true, P) -> top_loc(json, S, P);
group_loc(json, S, _InGroup, P) -> top_loc(json, S, P);
group_loc(protobuf, S, _InGroup, P) -> top_loc(protobuf, S, P);
group_loc(bits, S, _InGroup, #{word_bytes := WB0}) ->
    WB = case WB0 of
             undefined -> 1;
             _ -> WB0
         end,
    case [uint(X) || X <- binary:split(S, <<":">>, [global])] of
        [W, Pos] when is_integer(W), is_integer(Pos) -> W * WB * 8 + Pos;
        _ -> load_error('bad-directive', "bits group locator ~s is not <word>:<pos>", [S])
    end.

%% What follows the locator of a `group` line: on bits `item <bits> count
%% <count-locator | n>`, on the other wires nothing.
group_spec(bits, [<<"item">>, BitsS, <<"count">>, CountS], LocS, P) ->
    Bits = case uint(BitsS) of
               N when is_integer(N), N >= 1 -> N;
               _ -> load_error('bad-directive', "group at ~s: item ~s is not a positive integer",
                               [LocS, BitsS])
           end,
    Count = case binary:match(CountS, <<":">>) of
                nomatch ->
                    case uint(CountS) of
                        C when is_integer(C) -> {fixed, C};
                        error -> load_error('bad-directive', "group at ~s: count ~s is neither a locator nor an integer",
                                            [LocS, CountS])
                    end;
                _ -> {loc, top_loc(bits, CountS, P)}
            end,
    {Bits, Count};
group_spec(bits, _Other, LocS, _P) ->
    load_error('bad-directive', "bits group at ~s is not `<word>:<pos> item <bits> count <count-locator | n>`", [LocS]);
group_spec(text, [<<"item">>, NS], LocS, _P) ->
    case uint(NS) of
        N when is_integer(N), N >= 1 -> {text_item, N};
        _ -> load_error('bad-directive', "group at ~s: item ~s is not a positive integer", [LocS, NS])
    end;
group_spec(text, _Other, LocS, _P) ->
    load_error('bad-directive', "text group at ~s is not `<list> <i> item <n>`", [LocS]);
group_spec(_Wire, [], _LocS, _P) -> none;
group_spec(Wire, [Tok | _], LocS, _P) ->
    load_error('bad-directive', "group at ~s: ~s is not allowed on a ~s wire", [LocS, Tok, Wire]).

%% ===================================================================
%% checks on groups that need the whole file
%% ===================================================================
%% Within one scope (common plus one kind, or one group body) a list is
%% mapped by at most one group. On bits: a group counted by a locator is the
%% last thing in its scope, and a field of an item stays within its item.
check_scopes(#{wire := text} = P) -> text_scopes(P);
check_scopes(#{wire := tlv} = P) -> tlv_scopes(P);
check_scopes(#{common := Common, kinds := Kinds, wire := Wire}) ->
    case Kinds of
        [] -> check_scope(Common, none, Wire);
        _ ->
            lists:foreach(
              fun(#{lines := Ls}) ->
                      case has_group(Common) orelse has_group(Ls) of
                          true -> check_scope(Common ++ Ls, none, Wire);
                          false -> ok
                      end
              end, Kinds)
    end,
    lists:foreach(fun(Ls) -> check_bodies(Ls, Wire) end,
                  [Common | [maps:get(lines, K) || K <- Kinds]]).

has_group(Lines) -> lists:any(fun(L) -> element(1, L) =:= group end, Lines).

check_bodies(Lines, Wire) ->
    lists:foreach(
      fun({group, List, _, Spec, #{lines := Ls}, _}) ->
              check_scope(Ls, case Spec of none -> none; {Bits, _} -> Bits end, Wire),
              %% protobuf: a body is scalar only when every line is `.`
              %% (ruling 13 of 0.7)
              Dot = fun({field, _, [], _, _, _}) -> true; (_) -> false end,
              case Wire =:= protobuf andalso lists:any(Dot, Ls)
                  andalso not lists:all(Dot, Ls) of
                  true -> load_error('bad-directive',
                                     "the body of group ~s mixes `.` with other lines", [List]);
                  false -> ok
              end,
              check_bodies(Ls, Wire);
         (_) -> ok
      end, Lines).

%% The paths a group must not have for a field at this locator.
through_prefixes(xml, {FPath, _}) -> prefixes(FPath) ++ [FPath];
through_prefixes(bits, _) -> [];
through_prefixes(_Wire, FPath) when is_list(FPath), FPath =/= [] -> prefixes(FPath);
through_prefixes(_, _) -> [].

%% The proper prefixes of a path that are not empty.
prefixes([]) -> [];
prefixes(Path) -> prefixes(lists:droplast(Path), []).

prefixes([], Acc) -> Acc;
prefixes(Path, Acc) -> prefixes(lists:droplast(Path), [Path | Acc]).

check_scope(Lines, ItemBits, Wire) ->
    Groups = [G || G <- Lines, element(1, G) =:= group],
    %% a field's locator does not pass through a group's path (ruling 21 of
    %% 0.7): on xml the field's element path, on json and protobuf a proper
    %% prefix of its path, is no group's path
    GroupPaths = maps:from_list([{element(3, G), true} || G <- Groups]),
    lists:foreach(
      fun({field, Key, FLoc, _, LocT, _}) when Groups =/= [] ->
              case lists:any(fun(Pre) -> maps:is_key(Pre, GroupPaths) end,
                             through_prefixes(Wire, FLoc)) of
                  true -> load_error('bad-directive',
                                     "field ~s at ~s passes through the path of a group",
                                     [Key, LocT]);
                  false -> ok
              end;
         (_) -> ok
      end, Lines),
    Lists = [element(2, G) || G <- Groups],
    case length(lists:usort(Lists)) =:= length(Lists) of
        true -> ok;
        false -> load_error('bad-directive', "a list is mapped by two groups of one scope", [])
    end,
    %% bits: nothing lies at or beyond the start of a group counted by a locator
    Numbered = lists:zip(lists:seq(1, length(Groups)), Groups),
    lists:foreach(
      fun({I, {group, List, Start, {_, {loc, {CO, CL}}}, _, _}}) ->
              case CO + CL > Start of
                  true -> load_error('bad-directive', "the count locator of group ~s reaches the group's start", [List]);
                  false -> ok
              end,
              lists:foreach(
                fun({group, _, _, _, _, _}) -> ok;
                   (L) ->
                        {Off, Len} = element(line_loc_pos(L), L),
                        case Off + Len > Start of
                            true -> load_error('bad-directive',
                                               "~s lies at or beyond the start of group ~s, which is counted by a locator",
                                               [element(tuple_size(L) - line_text_back(L), L), List]);
                            false -> ok
                        end
                end, Lines),
              lists:foreach(
                fun({J, {group, Other, Start2, _, _, _}}) when J =/= I, Start2 >= Start ->
                        load_error('bad-directive',
                                   "group ~s starts at or beyond group ~s, which is counted by a locator",
                                   [Other, List]);
                   ({J, {group, Other, Start2, {Bits2, {fixed, N2}}, _, _}})
                      when J =/= I, Start2 + Bits2 * N2 > Start ->
                        load_error('bad-directive',
                                   "the items of group ~s reach group ~s, which is counted by a locator",
                                   [Other, List]);
                   (_) -> ok
                end, Numbered);
         (_) -> ok
      end, Numbered),
    %% bits: a field of an item, or a nested group with a fixed count, stays
    %% within `item <bits>`
    case ItemBits of
        none -> ok;
        _ ->
            lists:foreach(
              fun({group, List, Start, {Bits, {fixed, N}}, _, _}) when Start + Bits * N > ItemBits ->
                      load_error('bad-directive', "group ~s reaches beyond the bits of its item", [List]);
                 ({group, List, _, {_, {loc, {CO, CL}}}, _, _}) when CO + CL > ItemBits ->
                      load_error('bad-directive',
                                 "the count locator of group ~s reaches beyond the bits of its item", [List]);
                 ({group, _, _, _, _, _}) -> ok;
                 (L) ->
                      case element(line_loc_pos(L), L) of
                          {Off, Len} when Off + Len > ItemBits ->
                              load_error('bad-directive', "~s reaches beyond the bits of its item",
                                         [element(tuple_size(L) - line_text_back(L), L)]);
                          _ -> ok
                      end
              end, Lines)
    end.

%% position of the locator, and of the locator text from the end, in a line
line_loc_pos({field, _, _, _, _, _}) -> 3;
line_loc_pos({wh, _, _, _}) -> 2;
line_loc_pos({const, _, _, _}) -> 2.

line_text_back({field, _, _, _, _, _}) -> 1;
line_text_back(_) -> 0.

%% A bit length the transform does not allow is bad-directive at load.
len_ok(bits, Tr, {_Off, Len}) ->
    case Tr of
        f32 -> Len =:= 32;
        f64 -> Len =:= 64;
        ascii -> Len rem 8 =:= 0 andalso Len >= 8 andalso Len =< 2040;
        _ -> Len >= 1 andalso Len =< 64
    end;
len_ok(_Wire, _Tr, _Loc) -> true.

%% ===================================================================
%% `when` and `const` values -> {Value, Pack}
%% ===================================================================
fixed_value(_Which, bits, {_Off, Len}, LocS, ValS, P) ->
    case uint(ValS) of
        V when is_integer(V), V < (1 bsl Len) -> {V, P};
        V when is_integer(V) ->
            {V, late({bad, "value ~s does not fit ~s", [ValS, LocS]}, P)};
        error ->
            load_error('bad-directive', "bits value ~s at ~s is not an unsigned integer",
                       [ValS, LocS])
    end;
fixed_value(wh, protobuf, _Loc, _LocS, <<"present">>, P) -> {present, P};
fixed_value(_Which, protobuf, _Loc, LocS, ValS, P) ->
    case uint(ValS) of
        V when is_integer(V) -> {V, P};
        error -> load_error('bad-directive',
                            "protobuf value ~s at ~s is not an unsigned integer", [ValS, LocS])
    end;
fixed_value(wh, tlv, {_Path, Size}, LocS, <<"present">>, P) ->
    case Size of
        none -> {present, P};
        _ -> {present, late({bad, "when ~s present: present takes no size", [LocS]}, P)}
    end;
fixed_value(const, tlv, _Loc, LocS, <<"present">>, P) ->
    {{uint, 0}, late({bad, "const ~s present: a const needs a value", [LocS]}, P)};
fixed_value(Which, tlv, {_Path, Size}, LocS, ValS, P) ->
    case {uint(ValS), Size} of
        {error, _} ->
            {{uint, 0}, late({bad, "~s ~s: value ~s is not an unsigned decimal integer",
                              [Which, LocS, ValS]}, P)};
        {V, none} ->
            {{uint, V}, late({bad, "~s ~s ~s: a numeric value needs a size", [Which, LocS, ValS]}, P)};
        {V, N} when V >= 1 bsl (8 * N) ->
            {{uint, V}, late({bad, "~s ~s: value ~s does not fit ~p bytes", [Which, LocS, ValS, N]}, P)};
        {V, _} -> {{uint, V}, P}
    end;
fixed_value(wh, _Text, _Loc, _LocS, <<"present">>, P) -> {present, P};
fixed_value(const, _Text, _Loc, LocS, <<"present">>, _P) ->
    load_error('bad-directive', "const ~s present: write =present for the text", [LocS]);
fixed_value(_Which, _Text, _Loc, _LocS, <<"=", V/binary>>, P) -> {{text, V, true}, P};
fixed_value(_Which, _Text, _Loc, _LocS, V, P) -> {{text, V, false}, P}.

%% ===================================================================
%% transforms: each is valid on one kind of wire
%% ===================================================================
%% -> {Transform, [LateCheck]}: on the text wire, and for a transform valid
%% only on the text wire, the wire check runs after the file is read
%% (ruling 10 of 0.10).
%% On tlv a transform whose name or parameters do not parse is bad-directive
%% after the file is read (ruling 8 of 0.13); the line keeps the placeholder
%% `invalid`, and the pack never loads.
parse_transform(tlv, S) ->
    try transform(S) of
        _ -> parse_transform1(tlv, S)
    catch error:{E, _, Msg} when E =:= load_error; E =:= line_error ->
        %% not a line check on tlv (ruling 8 of 0.13)
        {invalid, [{bad, "transform ~s on a tlv wire: ~s", [S, Msg]}]}
    end;
parse_transform(Wire, S) -> parse_transform1(Wire, S).

parse_transform1(Wire, S) ->
    {Class, Tr} = transform(S),
    Ok = case {Class, Wire} of
             {text, xml} -> true;
             {text, geojson} -> true;
             {text, json} -> true;
             {text, text} -> true;
             {textonly, text} -> true;
             {json, json} -> true;
             {bits, bits} -> true;
             {protobuf, protobuf} -> true;
             {tlvonly, tlv} -> true;
             {tlvonly, _} -> late;
             {bits, tlv} ->
                 case tlv_transform(Tr) of
                     true -> true;
                     false -> late
                 end;
             {_, tlv} -> late;
             {textonly, _} -> late;
             {_, text} -> late;
             _ -> false
         end,
    %% a transform on a wire it is not valid for is checked after the file
    %% is read (ruling 5b of 0.11)
    case Ok of
        true -> {Tr, []};
        _ -> {Tr, [{bad, "transform ~s is not valid on a ~s wire", [S, Wire]}]}
    end.

transform(<<"string">>)     -> {text, string};
transform(<<"float">>)      -> {text, float};
transform(<<"int">>)        -> {text, int};
transform(<<"iso8601_ms">>) -> {text, iso8601_ms};
transform(<<"bool">>)       -> {json, bool};
transform(<<"uint">>)       -> {bits, uint};
transform(<<"twos">>)       -> {bits, twos};
transform(<<"f32">>)        -> {bits, f32};
transform(<<"f64">>)        -> {bits, f64};
transform(<<"ascii">>)      -> {bits, ascii};
transform(<<"linscale:", Rest/binary>> = S) ->
    %% ruling 4d of 0.11: <maxpos> an unsigned decimal integer of at least 1,
    %% <range> number text that does not read as zero
    case binary:split(Rest, <<":">>, [global]) of
        [MaxS, RangeS] ->
            Max = case gt_num:uint_text(MaxS) of
                      {ok, M} when M >= 1 -> M;
                      _ -> line_error('bad-directive', "~s: ~s is not an unsigned decimal integer of at least 1",
                                      [S, MaxS])
                  end,
            {bits, {linscale, Max, nonzero(RangeS, S)}};
        _ -> line_error('bad-directive', "~s is not linscale:<maxpos>:<range>", [S])
    end;
transform(<<"uscale:", Rest/binary>> = S) -> {bits, scale(uscale, Rest, S)};
transform(<<"sscale:", Rest/binary>> = S) -> {bits, scale(sscale, Rest, S)};
transform(<<"utf8">>)       -> {tlvonly, utf8};
transform(<<"hex">>)        -> {tlvonly, hex};
transform(<<"pstring">>)    -> {protobuf, pstring};
transform(<<"pvarint">>)    -> {protobuf, pvarint};
transform(<<"psint">>)      -> {protobuf, psint};
transform(<<"pdouble">>)    -> {protobuf, pdouble};
transform(<<"pfloat">>)     -> {protobuf, pfloat};
transform(<<"int:", W/binary>> = S) -> {textonly, {int_w, tparam(W, 1, 20, S)}};
transform(<<"dec:", Rest/binary>> = S) ->
    case binary:split(Rest, <<":">>, [global]) of
        [F] -> {textonly, {dec, tparam(F, 0, 9, S), none}};
        [F, W] -> {textonly, {dec, tparam(F, 0, 9, S), tparam(W, 1, 20, S)}};
        _ -> line_error('bad-directive', "~s is not dec:<f>[:<w>]", [S])
    end;
transform(<<"dm:", Rest/binary>> = S) ->
    case binary:split(Rest, <<":">>, [global]) of
        [D, F, <<Pos, Neg>>] when Pos >= $A, Pos =< $Z, Neg >= $A, Neg =< $Z, Pos =/= Neg ->
            {textonly, {dm, tparam(D, 1, 3, S), tparam(F, 0, 9, S), Pos, Neg}};
        _ -> line_error('bad-directive', "~s is not dm:<d>:<f>:<PN>, two different letters A to Z", [S])
    end;
transform(<<"hms:", F/binary>> = S) -> {textonly, {hms, tparam(F, 0, 3, S)}};
transform(<<"hms_dmy:", F/binary>> = S) -> {textonly, {hms_dmy, tparam(F, 0, 3, S)}};
transform(T) ->
    %% a transform's name is the text before its first `:`
    [Name | _] = binary:split(T, <<":">>),
    Known = [<<"string">>, <<"float">>, <<"int">>, <<"iso8601_ms">>, <<"bool">>, <<"uint">>,
             <<"twos">>, <<"f32">>, <<"f64">>, <<"ascii">>, <<"linscale">>, <<"uscale">>,
             <<"sscale">>, <<"pstring">>, <<"pvarint">>, <<"psint">>, <<"pdouble">>,
             <<"pfloat">>, <<"dec">>, <<"dm">>, <<"hms">>, <<"hms_dmy">>,
             <<"utf8">>, <<"hex">>],
    case lists:member(Name, Known) of
        true -> line_error('bad-directive', "transform ~s: its parameters are not valid", [T]);
        false -> line_error('unknown-transform', "~s", [T])
    end.

%% <factor>[:<offset>] (ruling 4d of 0.11)
scale(Name, Rest, S) ->
    case binary:split(Rest, <<":">>, [global]) of
        [F] -> {Name, scale_factor(F, S), 0.0};
        [F, O] ->
            case gt_num:num_text(O) of
                {ok, Off} -> {Name, scale_factor(F, S), Off};
                error -> line_error('bad-directive', "~s: offset ~s is not number text", [S, O])
            end;
        _ -> line_error('bad-directive', "~s has too many parameters", [S])
    end.

%% A factor of uscale or sscale: number text that does not read as zero, or
%% <num>/<den> of two unsigned decimal integers, neither zero.
scale_factor(Text, S) ->
    case binary:split(Text, <<"/">>, [global]) of
        [_] -> {dec, nonzero(Text, S)};
        [N, D] ->
            case {gt_num:uint_text(N), gt_num:uint_text(D)} of
                {{ok, Num}, {ok, Den}} when Num >= 1, Den >= 1 -> {frac, float(Num), float(Den)};
                _ -> line_error('bad-directive', "~s: ~s is not <num>/<den> of two integers above zero",
                                [S, Text])
            end;
        _ -> line_error('bad-directive', "~s: ~s is not a factor", [S, Text])
    end.

nonzero(Text, S) ->
    case gt_num:num_text(Text) of
        {ok, F} when F /= 0.0 -> F;
        _ -> line_error('bad-directive', "~s: ~s is not number text that reads as other than zero",
                        [S, Text])
    end.

%% The factor of the `scale` derive function (ruling 1 of 0.5, ruling 2c of
%% 0.11): number text, or <num>/<den> where <num> is integer text and <den>
%% an unsigned decimal integer that is not zero
%% -> {dec, float()} | {frac, float(), float()}.
factor(Text) ->
    case binary:split(Text, <<"/">>, [global]) of
        [_] -> {dec, number(Text)};
        [N, D] ->
            case {gt_num:int_text(N), gt_num:uint_text(D)} of
                {{ok, Num}, {ok, Den}} when Den >= 1 -> {frac, float(Num), float(Den)};
                _ -> load_error('bad-directive', "~s is not a fraction", [Text])
            end;
        _ -> load_error('bad-directive', "~s is not a fraction", [Text])
    end.

%% Number text (ruling 2b of 0.11).
number(Text) ->
    case gt_num:num_text(Text) of
        {ok, F} -> F;
        error -> load_error('bad-directive', "~s is not number text", [Text])
    end.

%% ===================================================================
%% tokens
%% ===================================================================
%% Tokenise one line -> [binary()]. '#' starts a comment only at a token
%% boundary (line start or after whitespace); inside a token, and inside a
%% double-quoted value, it is literal. A double-quoted value may contain
%% whitespace and cannot contain a double quote.
%% A value that begins with `"` and has no closing `"` on its line is
%% unterminated-quote (ruling 5 of 0.11); tokens_lax/1 reads it to the end
%% of the line, for the readers that look ahead.
tokens(Line) when is_list(Line) -> tokens(unicode:characters_to_binary(Line));
tokens(Line) -> tokens(Line, [], strict).

tokens_lax(Line) when is_list(Line) -> tokens_lax(unicode:characters_to_binary(Line));
tokens_lax(Line) -> tokens(Line, [], lax).

tokens(<<>>, Acc, _Mode) -> lists:reverse(Acc);
tokens(<<C, Rest/binary>>, Acc, Mode) when C =:= $\s; C =:= $\t; C =:= $\r ->
    tokens(Rest, Acc, Mode);                   % skip inter-token whitespace
tokens(<<$#, _/binary>>, Acc, _Mode) -> lists:reverse(Acc);   % comment to end of line
tokens(<<$", Rest/binary>>, Acc, Mode) ->
    N = scan_quoted(Rest, 0),
    <<Tok:N/binary, Rest1/binary>> = Rest,
    case Rest1 of
        <<$", Rest2/binary>> -> tokens(Rest2, [Tok | Acc], Mode);
        <<>> when Mode =:= strict ->
            load_error('unterminated-quote', "the value \"~ts has no closing quote", [Tok]);
        <<>> -> tokens(<<>>, [Tok | Acc], Mode)
    end;
tokens(Line, Acc, Mode) ->
    N = scan_bare(Line, 0),
    <<Tok:N/binary, Rest1/binary>> = Line,
    tokens(Rest1, [Tok | Acc], Mode).

scan_quoted(Bin, N) ->
    case Bin of
        <<_:N/binary, $", _/binary>> -> N;
        <<_:N/binary>> -> N;
        _ -> scan_quoted(Bin, N + 1)
    end.

%% Length of a bare token: up to the next whitespace ('#' mid-token is literal).
scan_bare(Bin, 0) ->
    case binary:match(Bin, [<<" ">>, <<"\t">>, <<"\r">>]) of
        {Pos, _} -> Pos;
        nomatch -> byte_size(Bin)
    end.

%% ===================================================================
%% sequential layouts (engine-spec Version 0.8)
%% ===================================================================
%% In a `layout sequential` pack a locator is a bit length and the lines are
%% read in file order from a cursor. Lines:
%%   {sfield, [{Key, Via}], Len, Transform, LenText, Swap, Trim, Absent}
%%        the first key is the `field` line's, the others those of the `also`
%%        lines after it
%%   {sconst, Len, Value} | {pad, Len} | {align, N} | {swhen, Len, Value}
%%   {presence, Id, Size :: pos_integer() | fx}
%%   {ifb, [{Id, Bit, Negated}], Body} | {opt, Body}
%%   {chain, FirstPart, [Part], EndsWithFx}   each later part follows an fx bit
%%   {len, Len, bytes | bits, Plus, Body} | {lenwhole, Len, Plus}
%%   {sgroup, List, {count, Len} | while | more | fx,
%%            #{lines, defaults, kinds => [Kind]}}
%% The `when` lines of a kind are the first lines of its `lines`.
%% While the file is read a presence is {presence, Name, Size} and an `if`
%% names {Name, Bit, Negated}; seq_resolve/1 gives every presence line an id,
%% binds each `if` name to the presence visible where it stands, and records
%% the bits some `if` names in `presence_named`.
seq_line([Dir | _] = Tokens, #{sstack := Stack} = P) ->
    PackLevel = [<<"format">>, <<"version">>, <<"wire">>, <<"layout">>, <<"bit_order">>,
                 <<"delimiter">>, <<"start">>, <<"checksum">>, <<"tag">>, <<"key">>,
                 <<"distribution">>, <<"source">>, <<"uses">>, <<"typemap">>, <<"map">>,
                 <<"root">>, <<"word_bytes">>],
    case lists:member(Dir, PackLevel) of
        true when Stack =/= [] ->
            load_error('bad-directive', "~s is not allowed inside a block", [Dir]);
        true when Dir =:= <<"word_bytes">> ->
            load_error('bad-directive', "word_bytes is not used in a sequential pack", []);
        true -> apply_line(Tokens, P);
        false -> seq_apply(Tokens, P)
    end.

seq_apply([<<"field">>, Key, LenS, TrS | OptToks], P0) ->
    {Tr, TrChecks} = parse_transform(bits, TrS),
    Len = seq_loc(LenS, infinity),
    {Via, Swap, Trim, Optional, _} = Opts0 = parse_opts(OptToks, {none, false, false, false, none}),
    {Opts, AbsentChecks} = sentinels(bits, Tr, Len, Opts0),
    Absent = element(5, Opts),
    case Optional of
        true -> load_error('bad-directive', "optional is not a field option of a sequential pack", []);
        false -> ok
    end,
    Checks = TrChecks ++
        [{bad, "~s does not allow the bit length ~s", [TrS, LenS]}
         || not len_ok(bits, Tr, {0, Len})] ++
        [{bad, "swap on a field of ~s bits: the length is not a multiple of 8", [LenS]}
         || Swap, Len rem 8 =/= 0] ++
        [{bad, "trim on a field of ~s bits: valid only with ascii", [LenS]}
         || Trim, Tr =/= ascii] ++
        [{via, Via} || Via =/= none] ++
        AbsentChecks,
    P1 = lists:foldl(fun late/2, P0, Checks),
    seq_add({sfield, [{Key, Via}], Len, Tr, LenS, Swap, Trim, Absent}, P1);
seq_apply([<<"also">>, Key | Rest], P0) ->
    Via = case Rest of
              [] -> none;
              [<<"via">>, T] -> T;
              _ -> load_error('bad-directive', "also ~s is not `also <key> [via <table>]`", [Key])
          end,
    P = case Via of
            none -> P0;
            _ -> late({via, Via}, P0)
        end,
    case seq_lines(P) of
        [{sfield, Keys, Len, Tr, LenS, Swap, Trim, Absent} | Before] ->
            seq_set_lines([{sfield, Keys ++ [{Key, Via}], Len, Tr, LenS, Swap, Trim, Absent} | Before], P);
        _ -> load_error('bad-directive', "also ~s does not follow a field line", [Key])
    end;
seq_apply([<<"const">>, LenS, ValS], P) ->
    Len = seq_loc(LenS, 64),
    seq_add({sconst, Len, seq_value(ValS, Len)}, P);
seq_apply([<<"pad">>, LenS], P) -> seq_add({pad, seq_len(LenS, 0, infinity)}, P);
seq_apply([<<"align">>, NS], P) -> seq_add({align, seq_len(NS, 1, infinity)}, P);
seq_apply([<<"when">>, LenS, ValS], #{sstack := Stack} = P) ->
    Len = seq_loc(LenS, 64),
    %% a `when` stands among the common lines, or first in its kind
    First = fun(Ls) -> lists:all(fun(L) -> element(1, L) =:= swhen end, Ls) end,
    Ok = case Stack of
             [] -> maps:get(cur, P) =:= common orelse First(seq_lines(P));
             [#{type := group, cur := none} | _] -> true;
             [#{type := group} | _] -> First(seq_lines(P));
             _ -> false
         end,
    case Ok of
        true -> seq_add({swhen, Len, seq_value(ValS, Len)}, P);
        false -> load_error('bad-directive',
                            "when ~s ~s stands after another line of its kind or inside a block",
                            [LenS, ValS])
    end;
seq_apply([<<"presence">>, Name, SizeS], P) ->
    Size = case SizeS of
               <<"fx">> -> fx;
               _ -> seq_len(SizeS, 1, 64)
           end,
    seq_add({presence, Name, Size}, P);
seq_apply([<<"if">> | Conds], P) when Conds =/= [] ->
    seq_push(#{type => 'if', hdr => [seq_cond(C) || C <- Conds]}, P);
seq_apply([<<"opt">>], P) -> seq_push(#{type => opt, hdr => none}, P);
seq_apply([<<"chain">>], P) -> seq_push(#{type => chain, hdr => none}, P);
seq_apply([<<"fx">>], #{sstack := Stack} = P) ->
    case Stack of
        [#{type := chain} | _] -> seq_add(fx, P);
        _ -> load_error('bad-directive', "fx is a line of a chain", [])
    end;
seq_apply([<<"length">>, LenS | Rest], P) ->
    Len = seq_len(LenS, 1, 64),
    {Unit, Plus, Whole} = seq_length_opts(Rest, {undefined, undefined, false}),
    case {Whole, Unit} of
        {true, bits} -> load_error('bad-directive', "length ... bits whole", []);
        {true, _} -> seq_add({lenwhole, Len, default(Plus, 0)}, P);
        {false, _} -> seq_push(#{type => length,
                                 hdr => {Len, default(Unit, bytes), default(Plus, 0)}}, P)
    end;
seq_apply([<<"group">>, List | ModeToks], P) ->
    Mode = case ModeToks of
               [<<"count">>, LenS] -> {count, seq_len(LenS, 1, 64)};
               [<<"while">>] -> while;
               [<<"more">>] -> more;
               [<<"fx">>] -> fx;
               _ -> load_error('bad-directive',
                               "group ~s is not `count <len>`, `while`, `more` or `fx`", [List])
           end,
    seq_push(#{type => group, hdr => {List, Mode}}, P);
seq_apply([<<"end">>], #{sstack := Stack} = P) ->
    case Stack of
        [] -> load_error('bad-directive', "end with no open block", []);
        [Frame | Rest] -> seq_add(seq_close(Frame), P#{sstack := Rest})
    end;
seq_apply([<<"kind">>, Name] = Tokens, #{sstack := Stack} = P) ->
    case Stack of
        [] -> (apply_line(Tokens, P))#{has_kinds := true};
        [#{type := group, kind_names := Names} = F0 | Rest] ->
            case maps:is_key(Name, Names) of
                true -> load_error('duplicate-kind', "kind ~s is declared twice in a group", [Name]);
                false -> ok
            end,
            F = seq_close_kind(F0),
            P#{sstack := [F#{cur := #{name => Name, requires => [], lines => [], defaults => []},
                             kind_names := Names#{Name => true}} | Rest]};
        _ -> load_error('bad-directive', "kind ~s inside a block", [Name])
    end;
seq_apply([<<"requires">> | Keys] = Tokens, #{sstack := Stack} = P) when Keys =/= [] ->
    case Stack of
        [] -> apply_line(Tokens, P);
        [#{type := group, cur := #{requires := R} = K} = F | Rest] ->
            P#{sstack := [F#{cur := K#{requires := R ++ Keys}} | Rest]};
        _ -> load_error('bad-directive', "requires outside a kind", [])
    end;
seq_apply([<<"default">>, Key, Val] = Tokens, #{sstack := Stack} = P) ->
    %% a default belongs to the scope its block stands in: the nearest group
    %% body (its open kind), else the message
    {Inner, Outer} = lists:splitwith(fun(#{type := T}) -> T =/= group end, Stack),
    case Outer of
        [] -> apply_line(Tokens, P);
        [#{cur := none, defaults := D} = F | Rest] ->
            P#{sstack := Inner ++ [F#{defaults := [{Key, Val} | D]} | Rest]};
        [#{cur := #{defaults := D} = K} = F | Rest] ->
            P#{sstack := Inner ++ [F#{cur := K#{defaults := [{Key, Val} | D]}} | Rest]}
    end;
seq_apply([Dir | Args], _P) ->
    case lists:member(Dir, known_directives()) of
        true -> load_error('bad-directive', "~s takes a different number of arguments than ~p",
                           [Dir, length(Args)]);
        false -> load_error('unknown-directive', "~s", [Dir])
    end.

default(undefined, D) -> D;
default(V, _) -> V.

%% A bit length or count: an unsigned integer within Min .. Max. A positional
%% locator is not one.
seq_len(S, Min, Max) ->
    case uint(S) of
        N when is_integer(N), N >= Min, Max =:= infinity orelse N =< Max -> N;
        _ -> load_error('bad-directive', "~s is not a bit length a sequential pack allows", [S])
    end.

%% The locator of a `field`, `when` or `const` line of a sequential pack: a
%% bit length. A `<word>:<pos>:<len>` locator is bad-directive; text that is
%% not digits only, and a length of 0, are bad-locator (ruling 5a of 0.11).
seq_loc(S, Max) ->
    case binary:match(S, <<":">>) of
        nomatch -> ok;
        _ -> line_error('bad-directive', "~s is a <word>:<pos>:<len> locator in a sequential pack", [S])
    end,
    case uint(S) of
        N when is_integer(N), N >= 1 ->
            case Max =:= infinity orelse N =< Max of
                true -> N;
                false -> load_error('bad-directive', "~s is more bits than this line allows", [S])
            end;
        _ -> line_error('bad-locator', "~s is not a bit length", [S])
    end.

seq_value(ValS, Len) ->
    case uint(ValS) of
        V when is_integer(V), V < (1 bsl Len) -> V;
        V when is_integer(V) ->
            load_error('bad-directive', "value ~s does not fit ~p bits", [ValS, Len]);
        error -> load_error('bad-directive', "value ~s is not an unsigned integer", [ValS])
    end.

%% `[!]<name>.<i>`
seq_cond(Tok) ->
    {Neg, Rest} = case Tok of
                      <<"!", R/binary>> -> {true, R};
                      _ -> {false, Tok}
                  end,
    case binary:split(Rest, <<".">>, [global]) of
        [Name, BitS] when Name =/= <<>> ->
            case uint(BitS) of
                Bit when is_integer(Bit), Bit >= 1 -> {Name, Bit, Neg};
                _ -> load_error('bad-directive', "if ~s names no presence bit", [Tok])
            end;
        _ -> load_error('bad-directive', "if ~s is not <name>.<i>", [Tok])
    end.

%% `[bytes|bits] [plus <n>] [whole]`, in any order, each at most once.
seq_length_opts([], Acc) -> Acc;
seq_length_opts([<<"bytes">> | R], {undefined, P, W}) -> seq_length_opts(R, {bytes, P, W});
seq_length_opts([<<"bits">> | R], {undefined, P, W}) -> seq_length_opts(R, {bits, P, W});
seq_length_opts([<<"whole">> | R], {U, P, false}) -> seq_length_opts(R, {U, P, true});
seq_length_opts([<<"plus">>, NS | R], {U, undefined, W}) ->
    N = case gt_num:int_text(NS) of
            {ok, I} -> I;
            error -> load_error('bad-directive', "length plus ~s is not integer text", [NS])
        end,
    seq_length_opts(R, {U, N, W});
seq_length_opts([Tok | _], _) ->
    load_error('bad-directive', "length: ~s is not expected here", [Tok]).

seq_push(Frame, #{sstack := Stack} = P) ->
    P#{sstack := [Frame#{lines => [], defaults => [], kinds => [], cur => none,
                         kind_names => #{}} | Stack]}.

%% The lines read so far, latest first, of the body a line now goes to.
seq_lines(#{sstack := [#{type := group, cur := #{lines := Ls}} | _]}) -> Ls;
seq_lines(#{sstack := [#{lines := Ls} | _]}) -> Ls;
seq_lines(#{cur := common, common := C}) -> C;
seq_lines(#{cur := #{lines := Ls}}) -> Ls.

seq_set_lines(Ls, #{sstack := [#{type := group, cur := #{} = K} = F | Rest]} = P) ->
    P#{sstack := [F#{cur := K#{lines := Ls}} | Rest]};
seq_set_lines(Ls, #{sstack := [F | Rest]} = P) -> P#{sstack := [F#{lines := Ls} | Rest]};
seq_set_lines(Ls, #{cur := common} = P) -> P#{common := Ls};
seq_set_lines(Ls, #{cur := Cur} = P) -> P#{cur := Cur#{lines := Ls}}.

seq_add(Line, P) -> seq_set_lines([Line | seq_lines(P)], P).

seq_close_kind(#{cur := none} = F) -> F;
seq_close_kind(#{cur := #{lines := Ls, defaults := Ds} = K, kinds := Ks} = F) ->
    F#{cur := none,
       kinds := [K#{lines := lists:reverse(Ls), defaults := lists:reverse(Ds)} | Ks]}.

%% The line a closed block makes.
seq_close(#{type := 'if', hdr := Conds, lines := Ls}) -> {ifb, Conds, lists:reverse(Ls)};
seq_close(#{type := opt, lines := Ls}) -> {opt, lists:reverse(Ls)};
seq_close(#{type := length, hdr := {Len, Unit, Plus}, lines := Ls}) ->
    {len, Len, Unit, Plus, lists:reverse(Ls)};
seq_close(#{type := chain, lines := Ls}) ->
    EndsFx = case Ls of [fx | _] -> true; _ -> false end,
    [First | Rest] = seq_parts(lists:reverse(Ls), [], []),
    %% the part after a closing fx line is empty and is not a part
    {chain, First, case EndsFx of true -> lists:droplast(Rest); false -> Rest end, EndsFx};
seq_close(#{type := group, hdr := {List, Mode}} = F0) ->
    #{lines := Ls, defaults := Ds, kinds := Ks} = seq_close_kind(F0),
    Common = lists:reverse(Ls),
    case Ks =:= [] andalso lists:any(fun(L) -> element(1, L) =:= swhen end, Common) of
        true -> load_error('bad-directive', "when in the body of group ~s, which has no kind", [List]);
        false -> ok
    end,
    {sgroup, List, Mode,
     #{lines => Common, defaults => lists:reverse(Ds), kinds => lists:reverse(Ks)}}.

seq_parts([], Cur, Acc) -> lists:reverse([lists:reverse(Cur) | Acc]);
seq_parts([fx | Rest], Cur, Acc) -> seq_parts(Rest, [], [lists:reverse(Cur) | Acc]);
seq_parts([L | Rest], Cur, Acc) -> seq_parts(Rest, [L | Cur], Acc).

%% ---- presence names ----
%% A name is visible from its `presence` line to the end of the enclosing
%% block; a nested block may declare it again. The common lines and the lines
%% of a kind are one block.
seq_resolve(#{common := Common, kinds := Kinds, has_kinds := HasKinds} = P) ->
    case not HasKinds andalso lists:any(fun(L) -> element(1, L) =:= swhen end, Common) of
        true -> load_error('bad-directive', "when in a pack with no kind line", []);
        false -> ok
    end,
    {Common1, Kinds1, St} = seq_res_scope(Common, Kinds, #{}, {0, #{}}),
    seq_check_lists(Common1, Kinds1),
    P#{common := Common1, kinds := Kinds1, presence_named => element(2, St)}.

%% ---- a list in two groups (rulings 23 and 33 of 0.8) ----
%% Within one scope (the common lines with one kind's, of the message or of
%% a group body) two groups may map one list only when each sits in an `if`
%% or `opt` block and neither block encloses the other. The block of a group
%% is the nearest `if` or `opt` around it inside the scope, held here as the
%% path of such blocks down to it; `length` and `chain` are not such blocks.
%% A block encloses itself.
seq_check_lists(Common, Kinds) ->
    Scopes = case Kinds of
                 [] -> [Common];
                 _ -> [Common ++ maps:get(lines, K) || K <- Kinds]
             end,
    lists:foreach(
      fun(Lines) ->
              lists:foldl(
                fun({List, Block}, Seen) ->
                        Before = maps:get(List, Seen, []),
                        case Before =/= [] andalso
                            lists:any(fun(B) ->
                                              lists:prefix(B, Block) orelse
                                                  lists:prefix(Block, B)
                                      end, Before) of
                            true ->
                                load_error('bad-directive',
                                           "list ~s is mapped by two groups of one scope whose if or opt blocks are not apart",
                                           [List]);
                            false -> Seen#{List => [Block | Before]}
                        end
                end, #{}, seq_groups(Lines, []))
      end, Scopes),
    lists:foreach(
      fun({sgroup, _, _, #{lines := Ls, kinds := Ks}}) -> seq_check_lists(Ls, Ks) end,
      lists:append([seq_group_lines(Ls)
                    || Ls <- [Common | [maps:get(lines, K) || K <- Kinds]]])).

%% The groups of a scope, each with the block it sits in -> [{List, Block}].
seq_groups(Lines, Block) ->
    lists:append(
      [case L of
           {sgroup, List, _, _} -> [{List, Block}];
           {ifb, _, Body} -> seq_groups(Body, Block ++ [make_ref()]);
           {opt, Body} -> seq_groups(Body, Block ++ [make_ref()]);
           _ -> seq_groups(lists:append(seq_bodies(L)), Block)
       end || L <- Lines, is_tuple(L)]).

%% The `group` lines of a scope, at any depth of its blocks.
seq_group_lines(Lines) ->
    lists:append(
      [case L of
           {sgroup, _, _, _} -> [L];
           _ -> seq_group_lines(lists:append(seq_bodies(L)))
       end || L <- Lines, is_tuple(L)]).

%% Common lines, then each kind from where the common lines ended.
seq_res_scope(Common, Kinds, Env, St0) ->
    {Common1, Env1, Decl1, St1} = seq_res(Common, Env, #{}, St0, []),
    {Kinds1, St2} =
        lists:mapfoldl(
          fun(#{lines := Ls} = K, St) ->
                  {Ls1, _, _, StK} = seq_res(Ls, Env1, Decl1, St, []),
                  {K#{lines := Ls1}, StK}
          end, St1, Kinds),
    {Common1, Kinds1, St2}.

%% seq_res(Lines, Visible, DeclaredInThisBlock, {NextId, Named}, Acc)
seq_res([], Env, Decl, St, Acc) -> {lists:reverse(Acc), Env, Decl, St};
seq_res([{presence, Name, Size} | Rest], Env, Decl, {Next, Named}, Acc) ->
    case maps:is_key(Name, Decl) of
        true -> load_error('bad-directive', "presence ~s is declared twice in one block", [Name]);
        false -> ok
    end,
    seq_res(Rest, Env#{Name => {Next, Size}}, Decl#{Name => true},
            {Next + 1, Named#{Next => []}}, [{presence, Next, Size} | Acc]);
seq_res([{ifb, Conds, Body} | Rest], Env, Decl, {Next, Named0}, Acc) ->
    {Conds1, Named1} =
        lists:mapfoldl(
          fun({Name, Bit, Neg}, Named) ->
                  case maps:find(Name, Env) of
                      error ->
                          load_error('bad-directive', "if names presence ~s, which is not visible here", [Name]);
                      {ok, {_, Size}} when is_integer(Size), Bit > Size ->
                          load_error('bad-directive', "if names bit ~p of presence ~s, which has ~p bits",
                                     [Bit, Name, Size]);
                      {ok, {Id, _}} ->
                          {{Id, Bit, Neg}, maps:update_with(Id, fun(Bs) -> ordsets:add_element(Bit, Bs) end, Named)}
                  end
          end, Named0, Conds),
    {Body1, St1} = seq_res_block(Body, Env, {Next, Named1}),
    seq_res(Rest, Env, Decl, St1, [{ifb, Conds1, Body1} | Acc]);
seq_res([{opt, Body} | Rest], Env, Decl, St, Acc) ->
    {Body1, St1} = seq_res_block(Body, Env, St),
    seq_res(Rest, Env, Decl, St1, [{opt, Body1} | Acc]);
seq_res([{len, Len, Unit, Plus, Body} | Rest], Env, Decl, St, Acc) ->
    {Body1, St1} = seq_res_block(Body, Env, St),
    seq_res(Rest, Env, Decl, St1, [{len, Len, Unit, Plus, Body1} | Acc]);
seq_res([{chain, First, Parts, EndsFx} | Rest], Env, Decl, St, Acc) ->
    %% the parts of a chain are one block
    {[First1 | Parts1], {_, _, St1}} =
        lists:mapfoldl(
          fun(Part, {E, D, S}) ->
                  {Part1, E1, D1, S1} = seq_res(Part, E, D, S, []),
                  {Part1, {E1, D1, S1}}
          end, {Env, #{}, St}, [First | Parts]),
    seq_res(Rest, Env, Decl, St1, [{chain, First1, Parts1, EndsFx} | Acc]);
seq_res([{sgroup, List, Mode, #{lines := Ls, kinds := Ks} = Body} | Rest], Env, Decl, St, Acc) ->
    {Ls1, Ks1, St1} = seq_res_scope(Ls, Ks, Env, St),
    seq_res(Rest, Env, Decl, St1, [{sgroup, List, Mode, Body#{lines := Ls1, kinds := Ks1}} | Acc]);
seq_res([L | Rest], Env, Decl, St, Acc) -> seq_res(Rest, Env, Decl, St, [L | Acc]).

seq_res_block(Body, Env, St) ->
    {Body1, _, _, St1} = seq_res(Body, Env, #{}, St, []),
    {Body1, St1}.

%% ===================================================================
%% the `text` wire (engine-spec Version 0.10)
%% ===================================================================
%% `delimiter`, `start` and `checksum`: the value is checked as the line is
%% read; another wire, a second line and a line after the first `kind` are
%% refused after the file is read (rulings 2 and 10 of 0.10).
text_directive(Dir, V, #{text_seen := Seen, cur := Cur, kind_names := Kinds} = P0) ->
    %% the wire is checked after the file is read, wherever the wire line
    %% stands (ruling 10 of 0.10)
    P1 = late({text_only, Dir}, P0),
    P2 = case maps:is_key(Dir, Seen) of
             true -> late({bad, "~s appears more than once", [Dir]}, P1);
             false -> P1
         end,
    P3 = case Cur =:= common andalso map_size(Kinds) =:= 0 of
             true -> P2;
             false -> late({bad, "~s stands after the first kind", [Dir]}, P2)
         end,
    P = P3#{text_seen := Seen#{Dir => true}},
    case Dir of
        delimiter ->
            case V of
                <<"none">> -> P#{delimiter := none};
                <<C>> when C >= 16#21, C =< 16#7E, C =/= $" -> P#{delimiter := V};
                _ -> load_error('bad-directive',
                                "delimiter ~s is not one character from 0x21 to 0x7E other than \", nor none", [V])
            end;
        start ->
            case V =/= <<>> andalso lists:all(fun(C) -> C >= 16#21 andalso C =< 16#7E end,
                                              binary_to_list(V)) of
                true -> P#{start := V};
                false -> load_error('bad-directive',
                                    "start ~s is not one or more characters from 0x21 to 0x7E", [V])
            end;
        checksum ->
            case V of
                <<"none">> -> P#{checksum := none};
                <<"nmea">> -> P#{checksum := nmea};
                _ -> load_error('bad-directive', "checksum ~s is neither none nor nmea", [V])
            end
    end.

%% `<i>`, `<i>:<from>:<len>` (len from 1), `<i>+<j>` (i and j different).
text_loc(S) ->
    case binary:split(S, <<"+">>) of
        [A, B] ->
            case {uint(A), uint(B)} of
                {I, J} when is_integer(I), is_integer(J), I =/= J -> {pair, I, J};
                {I, I} when is_integer(I) ->
                    line_error('bad-directive', "pair ~s names one field twice", [S]);
                _ -> line_error('bad-directive', "text locator ~s is not <i>+<j>", [S])
            end;
        [_] ->
            case [uint(X) || X <- binary:split(S, <<":">>, [global])] of
                [I] when is_integer(I) -> {fld, I};
                [I, From, Len] when is_integer(I), is_integer(From), is_integer(Len), Len >= 1 ->
                    {col, I, From, Len};
                _ -> line_error('bad-directive',
                                "text locator ~s is not <i>, <i>:<from>:<len> or <i>+<j>", [S])
            end
    end.

no_pair({pair, _, _}, What, S) ->
    load_error('bad-directive', "~s takes a field or a column, not the pair ~s", [What, S]);
no_pair(_, _, _) -> ok.

%% A transform parameter: an unsigned integer from Min to Max.
tparam(T, Min, Max, S) ->
    case uint(T) of
        N when is_integer(N), N >= Min, N =< Max -> N;
        _ -> line_error('bad-directive', "transform ~s: parameter ~s is not from ~p to ~p",
                        [S, T, Min, Max])
    end.

%% After the file is read: the directives against one another and against
%% the locators, and the `when` and `const` values.
text_checks(#{delimiter := Delim, start := Start, checksum := Sum,
              common := Common, kinds := Kinds}) ->
    case Delim =/= none andalso binary:match(Start, Delim) =/= nomatch of
        true -> load_error('bad-directive', "start ~s holds the delimiter ~s", [Start, Delim]);
        false -> ok
    end,
    case {Delim, Sum} of
        {<<"*">>, nmea} -> load_error('bad-directive', "delimiter * with checksum nmea", []);
        _ -> ok
    end,
    All = all_lines(Common ++ lists:append([maps:get(lines, K) || K <- Kinds])),
    lists:foreach(
      fun({group, List, _, _, _, _}) when Delim =:= none ->
              load_error('bad-directive', "group ~s under delimiter none", [List]);
         ({group, _, _, _, _, _}) -> ok;
         (L) ->
              Loc = line_loc_of(L),
              case Delim =:= none andalso gt_text:loc_indexes(Loc) =/= [0] of
                  true -> load_error('bad-directive', "a locator of a field other than 0 under delimiter none", []);
                  false -> ok
              end,
              case L of
                  {wh, _, present, _} -> ok;
                  {W, _, {text, V, _}, LocS} when W =:= wh; W =:= const ->
                      text_value_ok(V, Loc, Delim, Sum) orelse
                          load_error('bad-directive', "the value ~s at ~s cannot be written on this wire",
                                     [V, LocS]);
                  _ -> ok
              end
      end, All).

%% The lines of a scope and of its group bodies.
all_lines(Lines) ->
    lists:append([case L of
                      {group, _, _, _, #{lines := Ls}, _} -> [L | all_lines(Ls)];
                      _ -> [L]
                  end || L <- Lines]).

line_loc_of({field, _, Loc, _, _, _}) -> Loc;
line_loc_of({wh, Loc, _, _}) -> Loc;
line_loc_of({const, Loc, _, _}) -> Loc.

text_value_ok(V, Loc, Delim, Sum) ->
    Chars = binary_to_list(V),
    V =/= <<>>
        andalso lists:all(fun(C) -> C >= 16#20 andalso C =< 16#7E end, Chars)
        andalso (Delim =:= none orelse binary:match(V, Delim) =:= nomatch)
        andalso (Sum =/= nmea orelse binary:match(V, <<"*">>) =:= nomatch)
        andalso hd(Chars) =/= $\s andalso lists:last(Chars) =/= $\s
        andalso case Loc of
                    {col, _, _, Len} -> byte_size(V) =< Len;
                    _ -> true
                end.

%% A group is the last thing in its scope (common lines and one kind): one
%% group, and no field, when or const at its index or beyond.
text_scopes(#{common := Common, kinds := Kinds}) ->
    Scopes = case Kinds of
                 [] -> [Common];
                 _ -> [Common ++ maps:get(lines, K) || K <- Kinds]
             end,
    lists:foreach(
      fun(Lines) ->
              case [G || {group, _, _, _, _, _} = G <- Lines] of
                  [] -> ok;
                  [{group, List, Start, _, _, _}] ->
                      lists:foreach(
                        fun({group, _, _, _, _, _}) -> ok;
                           (L) ->
                                case lists:any(fun(I) -> I >= Start end,
                                               gt_text:loc_indexes(line_loc_of(L))) of
                                    true -> load_error('bad-directive',
                                                       "a line of the scope lies at or beyond the index of group ~s",
                                                       [List]);
                                    false -> ok
                                end
                        end, Lines);
                  _ -> load_error('bad-directive', "a scope holds a second group", [])
              end
      end, Scopes).

%% ===================================================================
%% the `tlv` wire (engine-spec Version 0.13)
%% ===================================================================
%% A tlv pack also has tag_enc (ber_oid | 1 | 2 | 4), len_enc (ber | 1 | 2 |
%% 4), key (none | binary()) and sum16 (none | {sum16, Tag}). Its locators are
%% {[Tag], Size :: none | 1..8}; a `when` value is present | {uint, V}, a
%% `const` value {uint, V}.
%%
%% `tag`, `length`, `key` and `checksum`: another wire, a second line, a
%% line after the first `kind` and a value of another form are refused after
%% the file is read, before missing-distribution.
tlv_directive(Dir, Args, #{tlv_seen := Seen, cur := Cur, kind_names := Kinds} = P0) ->
    Text = lists:join(" ", [binary_to_list(A) || A <- Args]),
    %% the wire is checked after the file is read: tag, key and checksum may
    %% stand before the wire line (ruling 13 of 0.13)
    P1 = late({tlv_only, [atom_to_list(Dir), " ", Text]}, P0),
    P2 = case maps:is_key(Dir, Seen) of
             true -> late({bad, "~s appears more than once", [Dir]}, P1);
             false -> P1
         end,
    P3 = case Cur =:= common andalso map_size(Kinds) =:= 0 of
             true -> P2;
             false -> late({bad, "~s stands after the first kind", [Dir]}, P2)
         end,
    P = P3#{tlv_seen := Seen#{Dir => true}},
    case tlv_value(Dir, Args) of
        {ok, Field, V} -> P#{Field := V};
        error -> late({bad, "~s ~s is not a form the tlv wire allows", [Dir, Text]}, P)
    end.

tlv_value(tag, [<<"ber-oid">>]) -> {ok, tag_enc, ber_oid};
tlv_value(tag, [N]) when N =:= <<"1">>; N =:= <<"2">>; N =:= <<"4">> ->
    {ok, tag_enc, binary_to_integer(N)};
tlv_value(length, [<<"ber">>]) -> {ok, len_enc, ber};
tlv_value(length, [N]) when N =:= <<"1">>; N =:= <<"2">>; N =:= <<"4">> ->
    {ok, len_enc, binary_to_integer(N)};
tlv_value(key, [H]) when byte_size(H) >= 2, byte_size(H) =< 128, byte_size(H) rem 2 =:= 0 ->
    case lists:all(fun(C) -> (C >= $0 andalso C =< $9) orelse (C >= $a andalso C =< $f) end,
                   binary_to_list(H)) of
        true -> {ok, key, gt_bits:hex_to_bytes(H)};
        false -> error
    end;
tlv_value(checksum, [<<"sum16">>, T]) ->
    case tag_text(T) of
        {ok, N} -> {ok, sum16, {sum16, N}};
        error -> error
    end;
tlv_value(_, _) -> error.

%% A tag: a decimal integer from 0 to 2^28-1 with no leading zero.
tag_text(<<$0, _, _/binary>>) -> error;
tag_text(S) ->
    case uint(S) of
        N when is_integer(N), N < 1 bsl 28 -> {ok, N};
        _ -> error
    end.

%% `<tag>[.<tag>...][:<n>]`, n one digit from 1 to 8 (ruling 6 of 0.13). The
%% tags are read here as digits; their form and range are checked after the
%% file is read (tlv_checks/1).
tlv_loc(S) ->
    {PathS, Size} =
        case binary:split(S, <<":">>, [global]) of
            [A] -> {A, none};
            [A, <<D>>] when D >= $1, D =< $8 -> {A, D - $0};
            _ -> load_error('bad-directive', "tlv locator ~s is not <path>[:<n>], n from 1 to 8", [S])
        end,
    Tags = [uint(T) || T <- binary:split(PathS, <<".">>, [global])],
    case lists:all(fun is_integer/1, Tags) of
        true -> {Tags, Size};
        false -> load_error('bad-directive', "tlv path ~s is not tags separated by .", [S])
    end.

%% The value transforms of the tlv wire.
tlv_transform(uint) -> true;
tlv_transform(twos) -> true;
tlv_transform(f32) -> true;
tlv_transform(f64) -> true;
tlv_transform({uscale, _, _}) -> true;
tlv_transform({sscale, _, _}) -> true;
tlv_transform(_) -> false.

%% A size against its transform -> ok | Why.
tlv_size_check(Tr, {_, Size}) ->
    Integer = lists:member(Tr, [uint, twos]) orelse
        (is_tuple(Tr) andalso lists:member(element(1, Tr), [uscale, sscale])),
    if
        Integer, Size =:= none -> "the transform needs a size :<n>";
        Integer -> ok;
        Tr =:= f32, Size =/= none, Size =/= 4 -> "f32 takes no size or :4";
        Tr =:= f64, Size =/= none, Size =/= 8 -> "f64 takes no size or :8";
        (Tr =:= utf8 orelse Tr =:= hex), Size =/= none -> "the transform takes no size";
        true -> ok
    end.

%% After the file is read: the form and range of every tag of a path and of
%% the checksum tag, and no field, when or const on the checksum tag.
tlv_checks(#{tag_enc := TagEnc, sum16 := Sum, common := Common, kinds := Kinds}) ->
    Limit = case TagEnc of
                ber_oid -> 1 bsl 28;
                N -> 1 bsl (8 * N)
            end,
    case Sum of
        {sum16, T} when T >= Limit ->
            load_error('bad-directive', "checksum tag ~p does not fit tag ~p", [T, TagEnc]);
        _ -> ok
    end,
    lists:foreach(
      fun(L) ->
              LocS = tlv_line_text(L),
              [PathS | _] = binary:split(LocS, <<":">>),
              lists:foreach(
                fun(TS) ->
                        case tag_text(TS) of
                            {ok, Tag} when Tag < Limit -> ok;
                            _ -> load_error('bad-directive',
                                            "tag ~s of ~s is not a decimal from 0 to ~p with no leading zero",
                                            [TS, LocS, Limit - 1])
                        end
                end, binary:split(PathS, <<".">>, [global])),
              {[First | _], _} = line_loc_of(L),
              case Sum of
                  {sum16, First} ->
                      load_error('bad-directive', "~s begins with the checksum tag ~p", [LocS, First]);
                  _ -> ok
              end
      end, Common ++ lists:append([maps:get(lines, K) || K <- Kinds])).

tlv_line_text({field, _, _, _, LocS, _}) -> LocS;
tlv_line_text({wh, _, _, LocS}) -> LocS;
tlv_line_text({const, _, _, LocS}) -> LocS.

%% Ruling 5 of 0.13: in one scope (the common lines with one kind's), no line
%% stands at a path under the path of another line.
tlv_scopes(#{common := Common, kinds := Kinds}) ->
    Scopes = case Kinds of
                 [] -> [Common];
                 _ -> [Common ++ maps:get(lines, K) || K <- Kinds]
             end,
    lists:foreach(
      fun(Lines) ->
              Paths = maps:from_list([{element(1, line_loc_of(L)), tlv_line_text(L)} || L <- Lines]),
              lists:foreach(
                fun(L) ->
                        {Path, _} = line_loc_of(L),
                        case [maps:get(Pre, Paths) || Pre <- prefixes(Path), maps:is_key(Pre, Paths)] of
                            [] -> ok;
                            [Pre | _] ->
                                load_error('bad-directive',
                                           "~s lies under ~s, which a line of the same scope reads as a value",
                                           [tlv_line_text(L), Pre])
                        end
                end, Lines)
      end, Scopes).
