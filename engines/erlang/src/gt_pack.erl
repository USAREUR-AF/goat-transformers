%% gt_pack: parse a pack.def into a pack map (engine-spec Versions 0.1 - 0.8).
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
%%   Key, LocText :: binary()
%%   Opts = {Via :: none | TableName, Swap, Trim, Optional}
%%   Loc, by wire:
%%     xml      {[ElementName :: binary()], {attr, binary()} | text}
%%     geojson  {geom, 1 | 2 | 3} | {prop, binary()} | {top, binary()}
%%     json     [MemberName :: binary()]; inside a group `.` is []
%%     bits     {BitOffsetInScope, Len}
%%     protobuf [FieldNumber]; inside a group `.` is []
%%   Inside a group a geojson pack uses the json locators.
%%   `when` Value: bits -> integer(); protobuf -> present | integer();
%%                 text wires -> present | {text, binary(), Forced :: boolean()}
%%   `const` Value: as a `when` value, never `present`.
%%
%% gt_engine:load_pack/2 checks the pack against the loaded modules, types the
%% defaults and adds the lookup indexes (index/1).
-module(gt_pack).
-export([parse/1, tokens/1, load_error/3, distribution_atom/1,
         require_marking/2, yields/1, model_keys/1, named/1,
         index/1, factor/1, number/1]).

%% Parse a pack.def text (binary or string) -> pack map. Line errors are
%% raised as the file is read; then the checks that need the whole file; then
%% missing-distribution and missing-source. The checks against the loaded
%% modules run in gt_engine:load_pack/2.
parse(Text) when is_list(Text) -> parse(unicode:characters_to_binary(Text));
parse(Bin) ->
    Lines = [T || L <- binary:split(Bin, <<"\n">>, [global]),
                  T <- [tokens(L)], T =/= []],
    Layout = case first_arg(<<"layout">>, Lines) of
                 <<"sequential">> -> sequential;
                 _ -> fixed
             end,
    Base = #{name => undefined, version => undefined,
             wire => first_arg(<<"wire">>, Lines),
             root => undefined,
             word_bytes => first_arg(<<"word_bytes">>, Lines),
             layout => Layout,
             bit_order => lsb,
             %% in a sequential pack a `kind` line may belong to a group
             %% body; the flag is set when a kind of the message opens
             has_kinds => Layout =/= sequential andalso
                 lists:any(fun([<<"kind">> | _]) -> true; (_) -> false end, Lines),
             typemap => [], tables => #{}, table_names => [],
             distribution => undefined, sources => [], uses => [],
             common => [], defaults => [], kinds => [], kind_names => #{},
             cur => common, late => [], gstack => [], sstack => []},
    P0 = lists:foldl(fun line/2, Base, Lines),
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
    P1 = close_kind(P0),
    Tables = finish_tables(P1),
    %% the checks that need the whole file, in file order (ruling 25 of 0.5)
    lists:foreach(
      fun({bad, Fmt, Args}) -> load_error('bad-directive', Fmt, Args);
         ({via, Table}) ->
              case maps:is_key(Table, Tables) of
                  true -> ok;
                  false -> load_error('bad-directive',
                                      "via names table ~s, which has no map line", [Table])
              end
      end, lists:reverse(maps:get(late, P1))),
    P2 = P1#{common := lists:reverse(maps:get(common, P1)),
             kinds := lists:reverse(maps:get(kinds, P1))},
    P3 = case Layout of
             sequential -> seq_resolve(P2);
             fixed -> check_scopes(P2), P2
         end,
    P = maps:without([cur, late, kind_names, table_names, gstack, sstack],
                     P3#{defaults := lists:reverse(maps:get(defaults, P1)),
                         typemap := lists:reverse(maps:get(typemap, P1)),
                         sources := lists:reverse(maps:get(sources, P1)),
                         uses := lists:reverse(maps:get(uses, P1)),
                         tables := Tables}),
    require_marking(["pack ", name_str(P)], P),
    case maps:get(name, P) of
        undefined -> load_error('bad-directive', "the pack has no format line", []);
        _ -> ok
    end,
    case maps:get(wire, P) of
        undefined -> load_error('bad-directive', "pack ~s has no wire line", [name_str(P)]);
        xml -> check_roots(P);
        _ -> ok
    end,
    P.

%% An xml pack needs a root for every message: the pack's, or one per kind.
check_roots(#{root := Root, kinds := Kinds, has_kinds := HasKinds} = P) ->
    Missing = case HasKinds of
                  false -> Root =:= undefined;
                  true -> Root =:= undefined andalso
                              lists:any(fun(#{root := R}) -> R =:= undefined end, Kinds)
              end,
    case Missing of
        true -> load_error('bad-directive', "xml pack ~s has no root line", [name_str(P)]);
        false -> ok
    end.

%% Value of the first `<Directive> <arg>` line, interpreted: the wire and the
%% word size are needed to read every field and when line.
first_arg(Dir, Lines) ->
    case [A || [D, A] <- Lines, D =:= Dir] of
        [] -> undefined;
        [A | _] when Dir =:= <<"wire">> -> wire_atom(A);
        [A | _] when Dir =:= <<"layout">> -> A;
        [A | _] when Dir =:= <<"word_bytes">> -> word_bytes(A)
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
yields(pdouble) -> float;
yields(pfloat)  -> float;
yields(int)        -> int;
yields(iso8601_ms) -> int;
yields(bool)       -> int;
yields(uint)       -> int;
yields(twos)       -> int;
yields(pvarint)    -> int;
yields(psint)      -> int.

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
           {sfield, Keys, _, Tr, _, _, _} -> [{K, {field, Tr, Via}} || {K, Via} <- Keys];
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
           {sfield, Keys, _, _, _, _, _} -> [<<Prefix/binary, K/binary>> || {K, _} <- Keys];
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
line(Tokens, #{layout := sequential, wire := bits} = P) -> seq_line(Tokens, P);
line([Dir | _] = Tokens, #{gstack := Stack} = P) ->
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
     <<"chain">>, <<"fx">>, <<"length">>, <<"also">>].

in_group(#{gstack := Stack}) -> Stack =/= [].

apply_line([<<"format">>, N], P)   -> P#{name => N};
apply_line([<<"version">>, V], P)  -> P#{version => V};
apply_line([<<"wire">>, W], P)     -> _ = wire_atom(W), P;       % read by first_arg
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
    {Val, P2} = fixed_value(wh, Wire, Loc, LocS, ValS, P1),
    add_line({wh, Loc, Val, LocS}, P2);
apply_line([<<"const">>, LocS, ValS], P0) ->
    Wire = need_wire(P0),
    Loc = parse_loc(Wire, LocS, P0),
    case Loc of
        [] -> load_error('bad-directive', "const . names the item itself", []);
        _ -> ok
    end,
    {Val, P1} = fixed_value(const, Wire, Loc, LocS, ValS, P0),
    add_line({const, Loc, Val, LocS}, P1);
apply_line([<<"default">>, Key, Val], #{gstack := [#{defaults := D} = G | Rest]} = P) ->
    P#{gstack := [G#{defaults := [{Key, Val} | D]} | Rest]};
apply_line([<<"default">>, Key, Val], #{cur := Cur} = P) ->
    case Cur of
        common -> P#{defaults := [{Key, Val} | maps:get(defaults, P)]};
        #{defaults := D} -> P#{cur := Cur#{defaults := [{Key, Val} | D]}}
    end;
apply_line([<<"group">>, List, LocS | Rest], #{gstack := Stack} = P) ->
    Wire = need_wire(P),
    G = #{list => List, loc => group_loc(Wire, LocS, in_group(P), P),
          spec => group_spec(Wire, Rest, LocS, P), loct => LocS,
          lines => [], defaults => []},
    P#{gstack := [G | Stack]};
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
    Tr = parse_transform(Wire, TrS),
    Loc = parse_loc(Wire, LocS, P0),
    {_Via, Swap, Trim, Optional} = Opts = parse_opts(OptToks, {none, false, false, false}),
    Checks =
        [{bad, "~s does not allow the bit length of ~s", [TrS, LocS]}
         || not len_ok(Wire, Tr, Loc)] ++
        [{bad, "swap on ~s: valid only on a bits wire, with a length that is a multiple of 8", [LocS]}
         || Swap, not (Wire =:= bits andalso element(2, Loc) rem 8 =:= 0)] ++
        [{bad, "trim on ~s: valid only on a bits wire, with ascii", [LocS]}
         || Trim, not (Wire =:= bits andalso Tr =:= ascii)] ++
        [{bad, "optional on ~s: valid only on a bits wire", [LocS]}
         || Optional, Wire =/= bits] ++
        [{via, T} || T <- [element(1, Opts)], T =/= none],
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
parse_opts([<<"via">>], _) -> load_error('bad-directive', "via names no table", []);
parse_opts([Other | _], _) -> load_error('bad-directive', "unknown field option ~s", [Other]).

set_opt(I, Unset, Value, Name, Opts) ->
    case element(I, Opts) of
        Unset -> setelement(I, Opts, Value);
        _ -> load_error('bad-directive', "field option ~s is given twice", [Name])
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
wire_atom(W) -> load_error('bad-directive', "unknown wire ~s", [W]).

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

is_int_text(<<$-, R/binary>>) -> R =/= <<>> andalso all_digits(R);
is_int_text(B) -> B =/= <<>> andalso all_digits(B).

is_number_text(B) ->
    try gt_num:dec_to_float(B) of _ -> true
    catch _:_ -> false
    end.

%% ===================================================================
%% locators
%% ===================================================================
%% Inside a group a locator is relative to one item: the same forms, and on
%% json, geojson and protobuf also `.` for the item itself.
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

top_loc(xml, S, _P) ->
    Parts = binary:split(S, <<"/">>, [global]),
    Path = lists:droplast(Parts),
    case lists:last(Parts) of
        <<"@", A/binary>> when A =/= <<>> -> {Path, {attr, A}};
        <<"#text">> -> {Path, text};
        _ -> load_error('bad-directive', "xml locator ~s names no attribute or #text", [S])
    end;
top_loc(geojson, <<"geometry.lon">>, _P) -> {geom, 1};
top_loc(geojson, <<"geometry.lat">>, _P) -> {geom, 2};
top_loc(geojson, <<"geometry.alt">>, _P) -> {geom, 3};
top_loc(geojson, <<"properties.", Name/binary>>, _P) when Name =/= <<>> -> {prop, Name};
top_loc(geojson, Name, _P) -> {top, Name};
top_loc(json, S, _P) ->
    Parts = binary:split(S, <<".">>, [global]),
    case lists:member(<<>>, Parts) of
        true -> load_error('bad-directive', "json path ~s has an empty member name", [S]);
        false -> Parts
    end;
top_loc(bits, S, #{word_bytes := WB}) ->
    case WB of
        undefined -> load_error('bad-directive', "the bits pack has no word_bytes line", []);
        _ -> ok
    end,
    case [uint(X) || X <- binary:split(S, <<":">>, [global])] of
        [W, Pos, Len] when is_integer(W), is_integer(Pos), is_integer(Len), Len >= 1 ->
            {W * WB * 8 + Pos, Len};
        _ -> load_error('bad-directive', "bits locator ~s is not <word>:<pos>:<len>", [S])
    end;
top_loc(protobuf, S, _P) ->
    Nums = [uint(X) || X <- binary:split(S, <<".">>, [global])],
    case lists:all(fun(N) -> is_integer(N) andalso N >= 1 end, Nums) of
        true -> Nums;
        false -> load_error('bad-directive', "protobuf path ~s is not field numbers", [S])
    end.

%% The locator of a `group` line.
group_loc(xml, S, _InGroup, _P) ->
    Parts = binary:split(S, <<"/">>, [global]),
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
group_loc(bits, S, _InGroup, #{word_bytes := WB}) ->
    case WB of
        undefined -> load_error('bad-directive', "the bits pack has no word_bytes line", []);
        _ -> ok
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
group_spec(_Wire, [], _LocS, _P) -> none;
group_spec(Wire, [Tok | _], LocS, _P) ->
    load_error('bad-directive', "group at ~s: ~s is not allowed on a ~s wire", [LocS, Tok, Wire]).

%% ===================================================================
%% checks on groups that need the whole file
%% ===================================================================
%% Within one scope (common plus one kind, or one group body) a list is
%% mapped by at most one group. On bits: a group counted by a locator is the
%% last thing in its scope, and a field of an item stays within its item.
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
fixed_value(wh, _Text, _Loc, _LocS, <<"present">>, P) -> {present, P};
fixed_value(const, _Text, _Loc, LocS, <<"present">>, _P) ->
    load_error('bad-directive', "const ~s present: write =present for the text", [LocS]);
fixed_value(_Which, _Text, _Loc, _LocS, <<"=", V/binary>>, P) -> {{text, V, true}, P};
fixed_value(_Which, _Text, _Loc, _LocS, V, P) -> {{text, V, false}, P}.

%% ===================================================================
%% transforms: each is valid on one kind of wire
%% ===================================================================
parse_transform(Wire, S) ->
    {Class, Tr} = transform(S),
    Ok = case {Class, Wire} of
             {text, xml} -> true;
             {text, geojson} -> true;
             {text, json} -> true;
             {json, json} -> true;
             {bits, bits} -> true;
             {protobuf, protobuf} -> true;
             _ -> false
         end,
    case Ok of
        true -> Tr;
        false -> load_error('bad-transform', "transform ~s is not valid on a ~s wire", [S, Wire])
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
    case binary:split(Rest, <<":">>, [global]) of
        [Max, Range] -> {bits, {linscale, number(Max), number(Range)}};
        _ -> load_error('bad-directive', "~s is not linscale:<maxpos>:<range>", [S])
    end;
transform(<<"uscale:", Rest/binary>> = S) -> {bits, scale(uscale, Rest, S)};
transform(<<"sscale:", Rest/binary>> = S) -> {bits, scale(sscale, Rest, S)};
transform(<<"pstring">>)    -> {protobuf, pstring};
transform(<<"pvarint">>)    -> {protobuf, pvarint};
transform(<<"psint">>)      -> {protobuf, psint};
transform(<<"pdouble">>)    -> {protobuf, pdouble};
transform(<<"pfloat">>)     -> {protobuf, pfloat};
transform(T) -> load_error('unknown-transform', "~s", [T]).

%% <factor>[:<offset>]
scale(Name, Rest, S) ->
    case binary:split(Rest, <<":">>, [global]) of
        [F] -> {Name, factor(F), 0.0};
        [F, O] -> {Name, factor(F), number(O)};
        _ -> load_error('bad-directive', "~s has too many arguments", [S])
    end.

%% A factor is a decimal or a fraction <num>/<den> of two decimal integers
%% (ruling 1 of 0.5) -> {dec, float()} | {frac, float(), float()}.
factor(Text) ->
    case binary:split(Text, <<"/">>, [global]) of
        [_] -> {dec, number(Text)};
        [N, D] -> {frac, float(integer(N)), float(integer(D))};
        _ -> load_error('bad-directive', "~s is not a fraction", [Text])
    end.

number(Text) ->
    try gt_num:dec_to_float(Text)
    catch _:_ -> load_error('bad-directive', "~s is not a decimal number", [Text])
    end.

integer(Text) ->
    try binary_to_integer(Text)
    catch _:_ -> load_error('bad-directive', "~s is not a decimal integer", [Text])
    end.

%% ===================================================================
%% tokens
%% ===================================================================
%% Tokenise one line -> [binary()]. '#' starts a comment only at a token
%% boundary (line start or after whitespace); inside a token, and inside a
%% double-quoted value, it is literal. A double-quoted value may contain
%% whitespace and cannot contain a double quote.
tokens(Line) when is_list(Line) -> tokens(unicode:characters_to_binary(Line));
tokens(Line) -> tokens(Line, []).

tokens(<<>>, Acc) -> lists:reverse(Acc);
tokens(<<C, Rest/binary>>, Acc) when C =:= $\s; C =:= $\t; C =:= $\r ->
    tokens(Rest, Acc);                         % skip inter-token whitespace
tokens(<<$#, _/binary>>, Acc) -> lists:reverse(Acc);   % comment to end of line
tokens(<<$", Rest/binary>>, Acc) ->
    N = scan_quoted(Rest, 0),
    <<Tok:N/binary, Rest1/binary>> = Rest,
    case Rest1 of
        <<$", Rest2/binary>> -> tokens(Rest2, [Tok | Acc]);
        <<>> -> tokens(<<>>, [Tok | Acc])
    end;
tokens(Line, Acc) ->
    N = scan_bare(Line, 0),
    <<Tok:N/binary, Rest1/binary>> = Line,
    tokens(Rest1, [Tok | Acc]).

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
%%   {sfield, [{Key, Via}], Len, Transform, LenText, Swap, Trim}
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
    Tr = parse_transform(bits, TrS),
    Len = seq_len(LenS, 1, infinity),
    {Via, Swap, Trim, Optional} = parse_opts(OptToks, {none, false, false, false}),
    case Optional of
        true -> load_error('bad-directive', "optional is not a field option of a sequential pack", []);
        false -> ok
    end,
    Checks =
        [{bad, "~s does not allow the bit length ~s", [TrS, LenS]}
         || not len_ok(bits, Tr, {0, Len})] ++
        [{bad, "swap on a field of ~s bits: the length is not a multiple of 8", [LenS]}
         || Swap, Len rem 8 =/= 0] ++
        [{bad, "trim on a field of ~s bits: valid only with ascii", [LenS]}
         || Trim, Tr =/= ascii] ++
        [{via, Via} || Via =/= none],
    P1 = lists:foldl(fun late/2, P0, Checks),
    seq_add({sfield, [{Key, Via}], Len, Tr, LenS, Swap, Trim}, P1);
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
        [{sfield, Keys, Len, Tr, LenS, Swap, Trim} | Before] ->
            seq_set_lines([{sfield, Keys ++ [{Key, Via}], Len, Tr, LenS, Swap, Trim} | Before], P);
        _ -> load_error('bad-directive', "also ~s does not follow a field line", [Key])
    end;
seq_apply([<<"const">>, LenS, ValS], P) ->
    Len = seq_len(LenS, 1, 64),
    seq_add({sconst, Len, seq_value(ValS, Len)}, P);
seq_apply([<<"pad">>, LenS], P) -> seq_add({pad, seq_len(LenS, 0, infinity)}, P);
seq_apply([<<"align">>, NS], P) -> seq_add({align, seq_len(NS, 1, infinity)}, P);
seq_apply([<<"when">>, LenS, ValS], #{sstack := Stack} = P) ->
    Len = seq_len(LenS, 1, 64),
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
    N = try binary_to_integer(NS)
        catch _:_ -> load_error('bad-directive', "length plus ~s is not an integer", [NS])
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
    P#{common := Common1, kinds := Kinds1, presence_named => element(2, St)}.

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
