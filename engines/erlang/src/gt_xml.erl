%% gt_xml: a small XML reader/writer for the engine. Names and values are
%% binaries; the input is read as a binary, never as a character list.
%% Element = {element, Name, Attrs, Children, Text}
%%   Name     :: binary()
%%   Attrs    :: [{binary(), binary()}]   (document order)
%%   Children :: [Element]                (document order)
%%   Text     :: binary() | undefined     (direct text content)
-module(gt_xml).
-export([parse/1, serialize/1, name/1, attrs/1,
         new/1, get_attr/2, get_text/1, find_child/2,
         children/2, set_attr/3, set_text/3, add_root_attr/3, append_children/3]).

-define(WS(C), (C =:= $\s orelse C =:= $\t orelse C =:= $\r orelse C =:= $\n)).

%% ---- parsing ----

parse(Cs) when is_list(Cs) -> parse(unicode:characters_to_binary(Cs));
parse(Bin) when is_binary(Bin) ->
    {Elem, Rest} = parse_elem(skip_misc(Bin)),
    <<>> = skip_misc(Rest),
    Elem.

%% skip whitespace, <?...?> prologs, <!-- --> comments and a <!DOCTYPE ...>
skip_misc(<<C, R/binary>>) when ?WS(C) -> skip_misc(R);
skip_misc(<<"<?", R/binary>>) -> skip_misc(skip_until(R, <<"?>">>));
skip_misc(<<"<!--", R/binary>>) -> skip_misc(skip_until(R, <<"-->">>));
skip_misc(<<"<!DOCTYPE", R/binary>>) -> skip_misc(skip_until(R, <<">">>));
skip_misc(Bin) -> Bin.

skip_until(Bin, Marker) ->
    {Pos, Len} = binary:match(Bin, Marker),
    binary:part(Bin, Pos + Len, byte_size(Bin) - Pos - Len).

parse_elem(<<"<", Bin/binary>>) ->
    {Name, R1} = read_name(Bin),
    true = Name =/= <<>>,
    {Attrs, R2} = parse_attrs(R1, []),
    case R2 of
        <<"/>", R/binary>> -> {{element, Name, Attrs, [], undefined}, R};
        <<">", R/binary>>  -> parse_content(R, Name, Attrs, [], [])
    end.

parse_attrs(Bin, Acc) ->
    case skip_ws(Bin) of
        <<"/>", _/binary>> = R -> {lists:reverse(Acc), R};
        <<">", _/binary>> = R  -> {lists:reverse(Acc), R};
        R1 ->
            {Name, R2} = read_name(R1),
            true = Name =/= <<>>,
            <<"=", R3/binary>> = skip_ws(R2),
            <<Q, R4/binary>> = skip_ws(R3),
            true = (Q =:= $") orelse (Q =:= $'),
            {Pos, 1} = binary:match(R4, <<Q>>),
            <<Val:Pos/binary, _, R5/binary>> = R4,
            parse_attrs(R5, [{Name, decode_entities(Val)} | Acc])
    end.

parse_content(Bin, Name, Attrs, ChAcc, TxtAcc) ->
    case Bin of
        <<"</", R/binary>> ->
            {Name, R1} = read_name(R),
            <<">", R2/binary>> = skip_ws(R1),
            {{element, Name, Attrs, lists:reverse(ChAcc), text(TxtAcc)}, R2};
        <<"<!--", R/binary>> ->
            parse_content(skip_until(R, <<"-->">>), Name, Attrs, ChAcc, TxtAcc);
        <<"<![CDATA[", R/binary>> ->
            {Pos, 3} = binary:match(R, <<"]]>">>),
            <<Raw:Pos/binary, _:3/binary, R1/binary>> = R,
            parse_content(R1, Name, Attrs, ChAcc, [{raw, Raw} | TxtAcc]);
        <<"<?", R/binary>> ->
            parse_content(skip_until(R, <<"?>">>), Name, Attrs, ChAcc, TxtAcc);
        <<"<", _/binary>> ->
            {Child, R} = parse_elem(Bin),
            parse_content(R, Name, Attrs, [Child | ChAcc], TxtAcc);
        _ ->
            {Pos, 1} = binary:match(Bin, <<"<">>),
            <<Chunk:Pos/binary, R/binary>> = Bin,
            parse_content(R, Name, Attrs, ChAcc, [Chunk | TxtAcc])
    end.

%% Direct text content: every character-data run of the element, joined.
%% Whitespace alone is no text.
text([]) -> undefined;
text(Acc) ->
    S = iolist_to_binary([case P of
                              {raw, Raw} -> Raw;
                              _ -> decode_entities(P)
                          end || P <- lists:reverse(Acc)]),
    case all_ws(S) of
        true -> undefined;
        false -> S
    end.

all_ws(<<>>) -> true;
all_ws(<<C, R/binary>>) when ?WS(C) -> all_ws(R);
all_ws(_) -> false.

read_name(Bin) -> read_name(Bin, 0).
read_name(Bin, N) ->
    case Bin of
        <<_:N/binary, C, _/binary>> when ?WS(C); C =:= $/; C =:= $>; C =:= $= ->
            <<Name:N/binary, Rest/binary>> = Bin,
            {Name, Rest};
        <<_:N/binary>> -> {Bin, <<>>};
        _ -> read_name(Bin, N + 1)
    end.

skip_ws(<<C, R/binary>>) when ?WS(C) -> skip_ws(R);
skip_ws(Bin) -> Bin.

decode_entities(Bin) ->
    case binary:match(Bin, <<"&">>) of
        nomatch -> Bin;
        _ -> iolist_to_binary(entities(Bin))
    end.

entities(Bin) ->
    case binary:match(Bin, <<"&">>) of
        nomatch -> [Bin];
        {Pos, 1} ->
            <<Before:Pos/binary, $&, Rest/binary>> = Bin,
            {End, 1} = binary:match(Rest, <<";">>),
            <<Ent:End/binary, $;, After/binary>> = Rest,
            [Before, entity(Ent) | entities(After)]
    end.

entity(<<"amp">>)  -> <<"&">>;
entity(<<"lt">>)   -> <<"<">>;
entity(<<"gt">>)   -> <<">">>;
entity(<<"quot">>) -> <<"\"">>;
entity(<<"apos">>) -> <<"'">>;
entity(<<"#x", Hex/binary>>) -> <<(binary_to_integer(Hex, 16))/utf8>>;
entity(<<"#", Dec/binary>>) -> <<(binary_to_integer(Dec))/utf8>>.

%% ---- accessors / builders ----

new(Name) -> {element, Name, [], [], undefined}.

name({element, Name, _, _, _}) -> Name.
attrs({element, _, Attrs, _, _}) -> Attrs.

get_attr({element, _, Attrs, _, _}, Name) ->
    case lists:keyfind(Name, 1, Attrs) of
        {_, V} -> {ok, V};
        false  -> absent
    end.

get_text({element, _, _, _, undefined}) -> absent;
get_text({element, _, _, _, T}) -> {ok, T}.

%% the first child of that name
find_child({element, _, _, Children, _}, Name) ->
    case lists:keyfind(Name, 2, Children) of
        {element, _, _, _, _} = E -> {ok, E};
        false -> absent
    end.

%% every child of that name, in document order
children({element, _, _, Children, _}, Name) ->
    [C || {element, N, _, _, _} = C <- Children, N =:= Name].

%% Append elements, in order, to the children of the element reached by Path.
append_children(Elem, Path, New) ->
    put_at(Elem, Path, fun({element, N, A, Ch, T}) -> {element, N, A, Ch ++ New, T} end).

%% Set an attribute on the element reached by Path (child names); the empty
%% path is the root element itself. Missing elements are made.
set_attr(Elem, Path, {Name, Val}) ->
    put_at(Elem, Path, fun({element, N, A, Ch, T}) ->
                               {element, N, put_kv(A, Name, Val), Ch, T}
                       end).

set_text(Elem, Path, Val) ->
    put_at(Elem, Path, fun({element, N, A, Ch, _}) ->
                               {element, N, A, Ch, Val}
                       end).

add_root_attr(Elem, Name, Val) -> set_attr(Elem, [], {Name, Val}).

put_at(Elem, [], Fun) -> Fun(Elem);
put_at({element, N, A, Ch, T}, [H | Rest], Fun) ->
    {element, N, A, update_child(Ch, H, Rest, Fun), T}.

update_child([], Name, Rest, Fun) ->
    [put_at(new(Name), Rest, Fun)];
update_child([{element, Name, _, _, _} = C | Tl], Name, Rest, Fun) ->
    [put_at(C, Rest, Fun) | Tl];
update_child([C | Tl], Name, Rest, Fun) ->
    [C | update_child(Tl, Name, Rest, Fun)].

put_kv(KVs, K, V) ->
    case lists:keymember(K, 1, KVs) of
        true -> lists:keyreplace(K, 1, KVs, {K, V});
        false -> KVs ++ [{K, V}]
    end.

%% ---- serialising (canonical) -> iodata ----

serialize({element, Name, Attrs, [], undefined}) ->
    [$<, Name, ser_attrs(Attrs), "/>"];
serialize({element, Name, Attrs, Children, Text}) ->
    [$<, Name, ser_attrs(Attrs), $>,
     [serialize(C) || C <- Children], ser_text(Text),
     "</", Name, $>].

ser_text(undefined) -> [];
ser_text(T) -> escape(T).

ser_attrs(Attrs) ->
    [[$\s, Name, "=\"", escape(Val), $"] || {Name, Val} <- Attrs].

escape(Bin) ->
    case binary:match(Bin, [<<"&">>, <<"<">>, <<">">>, <<"\"">>]) of
        nomatch -> Bin;
        _ -> << <<(esc(C))/binary>> || <<C>> <= Bin >>
    end.

esc($&) -> <<"&amp;">>;
esc($<) -> <<"&lt;">>;
esc($>) -> <<"&gt;">>;
esc($") -> <<"&quot;">>;
esc(C)  -> <<C>>.
