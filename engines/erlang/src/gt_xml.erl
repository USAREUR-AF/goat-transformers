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

%% Elements nest at most this deep; the root element is level 1.
-define(MAX_DEPTH, 64).

-define(WS(C), (C =:= $\s orelse C =:= $\t orelse C =:= $\r orelse C =:= $\n)).

%% ---- parsing ----

%% The reader is total: an input that is not one well-formed document raises
%% error:{xml_malformed, Why}, and so does an element nested deeper than
%% ?MAX_DEPTH levels, the root element being level 1 (ruling 35 of 0.8). An
%% input with no element is malformed (ruling 37).
parse(Cs) when is_list(Cs) -> parse(unicode:characters_to_binary(Cs));
parse(Bin0) when is_binary(Bin0) ->
    %% one byte order mark at the very start is skipped (ruling 1g of 0.11);
    %% then every CR LF and every CR alone is read as LF (1h)
    Bin1 = case Bin0 of
               <<16#EF, 16#BB, 16#BF, R0/binary>> -> R0;
               _ -> Bin0
           end,
    Bin = binary:replace(binary:replace(Bin1, <<"\r\n">>, <<"\n">>, [global]),
                         <<"\r">>, <<"\n">>, [global]),
    {Elem, Rest} = parse_elem(skip_misc(Bin), 1),
    case skip_misc(Rest) of
        <<>> -> Elem;
        _ -> bad(content_after_the_root_element)
    end.

bad(Why) -> erlang:error({xml_malformed, Why}).

%% skip whitespace, processing instructions and comments
skip_misc(<<C, R/binary>>) when ?WS(C) -> skip_misc(R);
skip_misc(<<"<?", R/binary>>) -> skip_misc(skip_until(R, <<"?>">>));
skip_misc(<<"<!--", R/binary>>) -> skip_misc(skip_until(R, <<"-->">>));
skip_misc(Bin) -> Bin.

%% What follows the first Marker; the input may not end before it.
skip_until(Bin, Marker) ->
    case binary:match(Bin, Marker) of
        {Pos, Len} -> binary:part(Bin, Pos + Len, byte_size(Bin) - Pos - Len);
        nomatch -> bad(unterminated_markup)
    end.

%% What stands before the first Marker, and what follows it.
split_at(Bin, Marker, Why) ->
    case binary:match(Bin, Marker) of
        {Pos, Len} ->
            {binary:part(Bin, 0, Pos),
             binary:part(Bin, Pos + Len, byte_size(Bin) - Pos - Len)};
        nomatch -> bad(Why)
    end.

parse_elem(_, Level) when Level > ?MAX_DEPTH -> bad(nesting_too_deep);
%% A document type declaration, or any other `<!` markup that is not a
%% comment or a CDATA section, is refused wherever it stands (ruling 40 of
%% 0.8): no entity is declared, expanded or fetched. The only entities are
%% the five predefined ones and numeric character references.
parse_elem(<<"<!", _/binary>>, _) -> bad(markup_declaration);
parse_elem(<<"<", Bin/binary>>, Level) ->
    {Name, R1} = read_name(Bin),
    {Attrs, R2} = parse_attrs(R1, []),
    case R2 of
        <<"/>", R/binary>> -> {{element, Name, Attrs, [], undefined}, R};
        <<">", R/binary>>  -> parse_content(R, Name, Attrs, [], [], Level)
    end;
parse_elem(_, _) -> bad(no_element).

%% -> {Attrs, Rest}; Rest begins with `/>` or `>`.
parse_attrs(Bin, Acc) ->
    case skip_ws(Bin) of
        <<"/>", _/binary>> = R -> {lists:reverse(Acc), R};
        <<">", _/binary>> = R  -> {lists:reverse(Acc), R};
        <<"/", _/binary>> -> bad(unterminated_tag);
        <<>> -> bad(unterminated_tag);
        R1 ->
            {Name, R2} = read_name(R1),
            R3 = case skip_ws(R2) of
                     <<"=", After/binary>> -> skip_ws(After);
                     _ -> bad(attribute_without_value)
                 end,
            case R3 of
                <<Q, R4/binary>> when Q =:= $"; Q =:= $' ->
                    {Val, R5} = split_at(R4, <<Q>>, unterminated_attribute_value),
                    %% `<` in a value is refused; a literal tab or line feed
                    %% is read as a space, one written as a reference is kept
                    %% (rulings 1i and 1o of 0.11); a name given twice is refused
                    case binary:match(Val, <<"<">>) of
                        nomatch -> ok;
                        _ -> bad(less_than_in_an_attribute_value)
                    end,
                    case lists:keymember(Name, 1, Acc) of
                        true -> bad(attribute_given_twice);
                        false -> ok
                    end,
                    Spaced = binary:replace(Val, [<<"\t">>, <<"\n">>], <<" ">>, [global]),
                    parse_attrs(R5, [{Name, decode_entities(Spaced)} | Acc]);
                _ -> bad(attribute_value_without_quotes)
            end
    end.

parse_content(Bin, Name, Attrs, ChAcc, TxtAcc, Level) ->
    case Bin of
        <<"</", R/binary>> ->
            case read_name(R) of
                {Name, R1} ->
                    case skip_ws(R1) of
                        <<">", R2/binary>> ->
                            {{element, Name, Attrs, lists:reverse(ChAcc), text(TxtAcc)}, R2};
                        _ -> bad(unterminated_closing_tag)
                    end;
                _ -> bad(closing_tag_of_another_name)
            end;
        <<"<!--", R/binary>> ->
            parse_content(skip_until(R, <<"-->">>), Name, Attrs, ChAcc, TxtAcc, Level);
        <<"<![CDATA[", R/binary>> ->
            {Raw, R1} = split_at(R, <<"]]>">>, unterminated_cdata),
            parse_content(R1, Name, Attrs, ChAcc, [{raw, Raw} | TxtAcc], Level);
        <<"<?", R/binary>> ->
            parse_content(skip_until(R, <<"?>">>), Name, Attrs, ChAcc, TxtAcc, Level);
        <<"<", _/binary>> ->
            {Child, R} = parse_elem(Bin, Level + 1),
            parse_content(R, Name, Attrs, [Child | ChAcc], TxtAcc, Level);
        _ ->
            case binary:match(Bin, <<"<">>) of
                {Pos, 1} ->
                    <<Chunk:Pos/binary, R/binary>> = Bin,
                    parse_content(R, Name, Attrs, ChAcc, [Chunk | TxtAcc], Level);
                nomatch -> bad(unterminated_element)
            end
    end.

%% Direct text content: every character-data run of the element, joined,
%% kept exactly; whitespace alone is text. An element with no character data
%% has none (ruling 1m of 0.11).
text([]) -> undefined;
text(Acc) ->
    S = iolist_to_binary([case P of
                              {raw, Raw} -> Raw;
                              _ -> decode_entities(P)
                          end || P <- lists:reverse(Acc)]),
    case S of
        <<>> -> undefined;
        _ -> S
    end.

%% A name runs to whitespace, `/`, `>` or `=`; it has at least one byte and
%% the input does not end inside it -> {Name, Rest}.
read_name(Bin) -> read_name(Bin, 0).
read_name(Bin, N) ->
    case Bin of
        <<_:N/binary, C, _/binary>> when ?WS(C); C =:= $/; C =:= $>; C =:= $=; C =:= $< ->
            case N of
                0 -> bad(empty_name);
                _ ->
                    <<Name:N/binary, Rest/binary>> = Bin,
                    {Name, Rest}
            end;
        <<_:N/binary>> -> bad(unterminated_tag);
        _ -> read_name(Bin, N + 1)
    end.

skip_ws(<<C, R/binary>>) when ?WS(C) -> skip_ws(R);
skip_ws(Bin) -> Bin.

decode_entities(Bin) ->
    case binary:match(Bin, <<"&">>) of
        nomatch -> Bin;
        _ -> iolist_to_binary(entities(Bin, []))
    end.

entities(Bin, Acc) ->
    case binary:match(Bin, <<"&">>) of
        nomatch -> lists:reverse([Bin | Acc]);
        {Pos, 1} ->
            <<Before:Pos/binary, $&, Rest/binary>> = Bin,
            {Ent, After} = split_at(Rest, <<";">>, unterminated_entity),
            entities(After, [entity(Ent), Before | Acc])
    end.

entity(<<"amp">>)  -> <<"&">>;
entity(<<"lt">>)   -> <<"<">>;
entity(<<"gt">>)   -> <<">">>;
entity(<<"quot">>) -> <<"\"">>;
entity(<<"apos">>) -> <<"'">>;
entity(<<"#x", Hex/binary>>) when Hex =/= <<>> -> char_ref(Hex, 16, 0);
entity(<<"#", Dec/binary>>) when Dec =/= <<>> -> char_ref(Dec, 10, 0);
entity(_) -> bad(unknown_entity).

%% A character reference: digits of the base only, no sign, naming a
%% character XML 1.0 allows: #x9, #xA, #xD, #x20-#xD7FF, #xE000-#xFFFD,
%% #x10000-#x10FFFF (ruling 40 of 0.8).
char_ref(<<>>, _Base, N) when N =:= 16#9; N =:= 16#A; N =:= 16#D;
                              N >= 16#20, N =< 16#D7FF;
                              N >= 16#E000, N =< 16#FFFD;
                              N >= 16#10000, N =< 16#10FFFF -> <<N/utf8>>;
char_ref(<<C, R/binary>>, Base, N) when N =< 16#10FFFF ->
    D = if C >= $0, C =< $9 -> C - $0;
           Base =:= 16, C >= $a, C =< $f -> C - $a + 10;
           Base =:= 16, C >= $A, C =< $F -> C - $A + 10;
           true -> bad(character_reference)
        end,
    case N * Base + D of
        N1 when N1 =< 16#10FFFF -> char_ref(R, Base, N1);
        _ -> bad(character_reference)
    end;
char_ref(_, _, _) -> bad(character_reference).

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

%% A string XML 1.0 cannot hold (a character below U+0020 other than tab,
%% line feed and carriage return; U+FFFE; U+FFFF) raises
%% error:{xml_unwritable, Why} (ruling 1d of 0.11).
serialize({element, Name, Attrs, [], T}) when T =:= undefined; T =:= <<>> ->
    [$<, Name, ser_attrs(Attrs), "/>"];
serialize({element, Name, Attrs, Children, Text}) ->
    [$<, Name, ser_attrs(Attrs), $>,
     [serialize(C) || C <- Children], ser_text(Text),
     "</", Name, $>].

ser_text(undefined) -> [];
ser_text(T) -> writable(T), escape_text(T).

ser_attrs(Attrs) ->
    [[$\s, Name, "=\"", (writable(Val)), escape_attr(Val), $"] || {Name, Val} <- Attrs].

writable(Bin) ->
    case binary:match(Bin, unwritable()) of
        nomatch -> [];
        _ -> erlang:error({xml_unwritable, Bin})
    end.

unwritable() ->
    [<<C>> || C <- lists:seq(0, 16#1F), C =/= $\t, C =/= $\n, C =/= $\r]
        ++ [<<16#FFFE/utf8>>, <<16#FFFF/utf8>>].

%% Attribute values (1a): & < > " tab LF CR as references.
escape_attr(Bin) ->
    case binary:match(Bin, [<<"&">>, <<"<">>, <<">">>, <<"\"">>, <<"\t">>, <<"\n">>, <<"\r">>]) of
        nomatch -> Bin;
        _ -> << <<(esc_attr(C))/binary>> || <<C>> <= Bin >>
    end.

esc_attr($") -> <<"&quot;">>;
esc_attr($\t) -> <<"&#9;">>;
esc_attr($\n) -> <<"&#10;">>;
esc_attr(C) -> esc(C).

%% Text content (1b): & < > and CR; tab, LF and both quotes as themselves.
escape_text(Bin) ->
    case binary:match(Bin, [<<"&">>, <<"<">>, <<">">>, <<"\r">>]) of
        nomatch -> Bin;
        _ -> << <<(esc(C))/binary>> || <<C>> <= Bin >>
    end.

esc($&) -> <<"&amp;">>;
esc($<) -> <<"&lt;">>;
esc($>) -> <<"&gt;">>;
esc($\r) -> <<"&#13;">>;
esc(C)  -> <<C>>.
