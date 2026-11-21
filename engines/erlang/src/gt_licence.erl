%% gt_licence: licence profiles in the loaders (engine-spec Version 0.29).
%% Clean-room from spec/engine-spec.md only.
%%
%% A profile is held as a rank: open 1 < open+copyleft 2 < everything 3 <
%% none 4. A loader with profile P loads what has a rank =< P. The rank 4 as
%% the asked profile is the `licences` subcommand without a profile: every
%% file is read and nothing is skipped.
%%
%% Every failure here is error:{load_error, 'bad-licence', Message}.
-module(gt_licence).
-export([profile/1, rank_name/1, start/4, pack/3, held/2, uses_names/1]).

-define(NONE, 4).

%% A profile name -> {ok, Rank} | error (ruling 3a).
profile(open) -> {ok, 1};
profile(P) when is_atom(P) -> profile(atom_to_binary(P));
profile(P) when is_list(P) ->
    case catch unicode:characters_to_binary(P) of
        B when is_binary(B) -> profile(B);
        _ -> error
    end;
profile(<<"open">>) -> {ok, 1};
profile(<<"open+copyleft">>) -> {ok, 2};
profile(<<"everything">>) -> {ok, 3};
profile(_) -> error.

rank_name(1) -> <<"open">>;
rank_name(2) -> <<"open+copyleft">>;
rank_name(3) -> <<"everything">>;
rank_name(?NONE) -> <<"none">>.

held(#{rank := Asked}, Rank) -> Rank =< Asked.

%% Ruling 3b: the table (1c), then for each module file, in the order of the
%% list given (core.def first, then byte order of file name), its licence
%% (1b) and its `module` and `uses` lines; then every module's profile (2b).
%% LicencesPath: the --packs text followed by /../licences.toml. Read: the
%% module files, [{File, {ok, Text} | {error, Reason}}].
%% -> Ctx = #{rank, table, names => #{ModuleName => Rank}, files => #{File => Rank}}.
start(LicencesPath, ModelsDir, Rank, Read) ->
    Table = read_table(LicencesPath),
    Mods = [begin
                Lic = module_licence(filename:join(ModelsDir, F ++ ".license")),
                {Name, Uses} = case R of
                                   {ok, Bin} -> heads(Bin);
                                   _ -> {undefined, []}
                               end,
                {F, Name, Uses, licence_rank(Lic, Table)}
            end || {F, R} <- Read],
    Names = fixpoint(Mods, #{}),
    Files = maps:from_list([{F, file_rank(Own, Uses, Names)} || {F, _, Uses, Own} <- Mods]),
    #{rank => Rank, table => Table, names => Names, files => Files}.

%% Ruling 2b: name -> the widest of the files of that name, each the widest
%% of its licence and of the names it uses, through others; iterated to a
%% fixed point (the ranks only grow, and are at most 4).
fixpoint(Mods, Names) ->
    Next = lists:foldl(
             fun({_F, undefined, _, _}, Acc) -> Acc;
                ({_F, Name, Uses, Own}, Acc) ->
                     R = file_rank(Own, Uses, Names),
                     Acc#{Name => max(R, maps:get(Name, Acc, 0))}
             end, #{}, Mods),
    case Next =:= Names of
        true -> Names;
        false -> fixpoint(Mods, Next)
    end.

file_rank(Own, Uses, Names) ->
    lists:foldl(fun(U, R) -> max(R, maps:get(U, Names, 0)) end, Own, Uses).

%% Ruling 3d, 2c: a pack in directory PackDir whose pack.def text is Text
%% ({ok, Bin}, or anything else when it cannot be read) -> {Licence, Rank}.
pack(#{table := Table, names := Names}, PackDir, Text) ->
    Lic = pack_licence(filename:join(PackDir, "REUSE.toml")),
    Uses = case Text of
               {ok, Bin} -> uses_names(Bin);
               _ -> []
           end,
    Rank = file_rank(max(licence_rank(Lic, Table), maps:get(<<"core">>, Names, 0)), Uses, Names),
    {Lic, Rank}.

%% The `uses` names of a pack.def text, read as ruling 2b reads them.
uses_names(Bin) ->
    case heads(Bin) of
        {_, Uses} -> Uses
    end.

%% ===================================================================
%% Ruling 2a: the profile of a licence
%% ===================================================================
licence_rank(Lic, Table) ->
    case maps:find(Lic, Table) of
        error -> 3;
        {ok, #{distribution := controlled}} -> ?NONE;
        {ok, #{commercial := yes, field_of_use := [], share_alike := false}} -> 1;
        {ok, #{commercial := yes, field_of_use := [], share_alike := true}} -> 2;
        {ok, _} -> 3
    end.

%% ===================================================================
%% Ruling 2b: the `module` and `uses` lines of a text
%% ===================================================================
heads(Bin) ->
    case valid_utf8(Bin) of
        false -> {undefined, []};
        true ->
            Lines = lines(Bin),
            Name = case [N || L <- Lines, {match, [N]} <- [re:run(L, "^module[ \t]+([A-Za-z0-9_-]+)\\z",
                                                                [{capture, all_but_first, binary}])]] of
                       [N | _] -> N;
                       [] -> undefined
                   end,
            Uses = [U || L <- Lines, {match, [U]} <- [re:run(L, "^uses[ \t]+([A-Za-z0-9_-]+)\\z",
                                                         [{capture, all_but_first, binary}])]],
            {Name, Uses}
    end.

%% ===================================================================
%% Ruling 1: reading the files
%% ===================================================================

%% -> {ok, [TrimmedLine]} | absent; anything else is bad-licence.
read_lines(Path) ->
    case file:read_file(Path) of
        {ok, Bin} ->
            case valid_utf8(Bin) of
                true -> {ok, lines(Bin)};
                false -> bad("~s is not valid UTF-8", [Path])
            end;
        {error, R} when R =:= enoent; R =:= enotdir -> absent;
        {error, R} -> bad("~s cannot be read (~p)", [Path, R])
    end.

valid_utf8(Bin) ->
    case unicode:characters_to_binary(Bin, utf8, utf8) of
        Bin -> true;
        _ -> false
    end.

%% Cut at each line feed; one carriage return before a line feed or at the
%% end of the file goes with it; each line trimmed of spaces and tabs.
lines(Bin) ->
    [trim(strip_cr(L)) || L <- binary:split(Bin, <<"\n">>, [global])].

strip_cr(L) ->
    case byte_size(L) of
        0 -> L;
        N ->
            case binary:at(L, N - 1) of
                $\r -> binary:part(L, 0, N - 1);
                _ -> L
            end
    end.

trim(L) -> trim_right(trim_left(L)).
trim_left(<<C, R/binary>>) when C =:= $\s; C =:= $\t -> trim_left(R);
trim_left(L) -> L.
trim_right(L) ->
    case byte_size(L) of
        0 -> L;
        N ->
            case binary:at(L, N - 1) of
                C when C =:= $\s; C =:= $\t -> trim_right(binary:part(L, 0, N - 1));
                _ -> L
            end
    end.

-define(ID, "([A-Za-z0-9.+-]+)").

%% 1a: <packs>/d/REUSE.toml.
pack_licence(Path) ->
    % REUSE-IgnoreStart: the quoted licence lines below are data
    one_licence(Path, "^SPDX-License-Identifier[ \t]*=[ \t]*\"" ?ID "\"\\z",
                "^SPDX-License-Identifier[ \t=]").

%% 1b: <models>/m.def.license.
module_licence(Path) ->
    one_licence(Path, "^SPDX-License-Identifier:[ \t]+" ?ID "\\z",
                "^SPDX-License-Identifier:").
%% REUSE-IgnoreEnd

one_licence(Path, LineRe, BeginRe) ->
    case read_lines(Path) of
        absent -> <<"Apache-2.0">>;
        {ok, Lines} ->
            Found = lists:foldl(
                      fun(L, Acc) ->
                              case re:run(L, LineRe, [{capture, all_but_first, binary}]) of
                                  {match, [Id]} -> [Id | Acc];
                                  nomatch ->
                                      case re:run(L, BeginRe, [{capture, none}]) of
                                          match -> bad("~s: a line begins as a licence line and is not one: ~s",
                                                       [Path, L]);
                                          nomatch -> Acc
                                      end
                              end
                      end, [], Lines),
            case Found of
                [Id] -> Id;
                [] -> bad("~s holds no licence line", [Path]);
                _ -> bad("~s holds more than one licence line", [Path])
            end
    end.

%% 1c: licences.toml -> #{Id => #{commercial, share_alike, field_of_use, distribution}}.
read_table(Path) ->
    case read_lines(Path) of
        absent -> #{<<"Apache-2.0">> => #{commercial => yes, share_alike => false,
                                         field_of_use => [], distribution => public}};
        {ok, Lines} ->
            {Table, Row} = lists:foldl(fun(L, Acc) -> table_line(Path, L, Acc) end,
                                       {#{}, none}, Lines),
            close_row(Path, Table, Row)
    end.

table_line(_Path, <<>>, Acc) -> Acc;
table_line(_Path, <<$#, _/binary>>, Acc) -> Acc;
table_line(Path, L, {Table, Row}) ->
    case re:run(L, "^\\[licences\\.\"" ?ID "\"\\]\\z", [{capture, all_but_first, binary}]) of
        {match, [Id]} ->
            T1 = close_row(Path, Table, Row),
            case maps:is_key(Id, T1) of
                true -> bad("~s: a second row of ~s", [Path, Id]);
                false -> {T1, {Id, #{}}}
            end;
        nomatch when Row =:= none ->
            bad("~s: a line before the first row: ~s", [Path, L]);
        nomatch ->
            {Id, Got} = Row,
            {Key, Value} = row_line(Path, L),
            case maps:is_key(Key, Got) of
                true -> bad("~s: row ~s holds ~s twice", [Path, Id, Key]);
                false -> {Table, {Id, Got#{Key => Value}}}
            end
    end.

row_line(Path, L) ->
    Forms = [{commercial, "^commercial[ \t]*=[ \t]*\"(yes|no|unknown)\"\\z"},
             {share_alike, "^share_alike[ \t]*=[ \t]*(true|false)\\z"},
             {field_of_use, "^field_of_use[ \t]*=[ \t]*(\\[\\]|\\[\".*\"\\])\\z"},
             {distribution, "^distribution[ \t]*=[ \t]*\"(public|controlled)\"\\z"},
             {name, "^name[ \t=]()"}, {url, "^url[ \t=]()"},
             {attribution, "^attribution[ \t=]()"}],
    row_form(Path, L, Forms).

row_form(Path, L, []) -> bad("~s: a line a row does not take: ~s", [Path, L]);
row_form(Path, L, [{Key, Re} | Rest]) ->
    case re:run(L, Re, [{capture, all_but_first, binary}]) of
        {match, [V]} -> {Key, value(Key, V)};
        nomatch -> row_form(Path, L, Rest)
    end.

value(commercial, V) -> binary_to_atom(V);
value(share_alike, V) -> V =:= <<"true">>;
value(field_of_use, <<"[]">>) -> [];
value(field_of_use, V) -> [V];
value(distribution, V) -> binary_to_atom(V);
value(_, V) -> V.

close_row(_Path, Table, none) -> Table;
close_row(Path, Table, {Id, Got}) ->
    Four = [commercial, share_alike, field_of_use, distribution],
    case [K || K <- Four, not maps:is_key(K, Got)] of
        [] -> Table#{Id => maps:with(Four, Got)};
        [K | _] -> bad("~s: row ~s has no ~s line", [Path, Id, K])
    end.

bad(Fmt, Args) ->
    gt_pack:load_error('bad-licence', Fmt, [to_bytes(A) || A <- Args]).

%% Paths and lines as bytes, so the message is written unchanged.
to_bytes(A) when is_list(A) ->
    case catch unicode:characters_to_binary(A) of
        B when is_binary(B) -> B;
        _ -> A
    end;
to_bytes(A) -> A.
