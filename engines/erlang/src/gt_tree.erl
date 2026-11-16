%% Load a chosen set of packs from a tree: a directory holding `model/` and
%% `packs/`, such as a checkout of the library or a bundle written by
%% `tools/goat-pkg bundle`.
%%
%%   E = gt_tree:load("vendor/goat", ["cot-xml", "geojson"]),
%%   Out = gt_engine:convert(E, <<"cot-xml">>, <<"geojson">>, CotEvent).
-module(gt_tree).

-export([load/2, load/3]).

%% A new engine holding the named packs of the tree at Root.
load(Root, Packs) ->
    load(gt_engine:new(), Root, Packs).

%% Load the named packs from `<Root>/packs/<Name>/pack.def`, and before them
%% the model modules they need from `<Root>/model/*.def`: `core`, every module
%% a named pack `uses`, and every module one of those `uses`, each after the
%% modules it uses. Nothing else in the tree is loaded. A module the engine
%% already holds is not loaded again, so the call can be repeated with more
%% packs. The engine's distribution limit applies. A pack name is a string or
%% a binary. -> Engine
load(Engine, Root, Packs) ->
    Names = dedup([to_list(P) || P <- Packs]),
    Texts = [pack_text(Root, N) || N <- Names],
    ModelDir = filename:join(Root, "model"),
    Files = case file:list_dir(ModelDir) of
                {ok, Fs} -> [F || F <- lists:sort(Fs), lists:suffix(".def", F)];
                {error, _} -> []
            end,
    %% module name -> {Text, the modules it uses}; the first file of a name
    Heads = lists:foldl(
              fun(F, Acc) ->
                      {ok, Bin} = file:read_file(filename:join(ModelDir, F)),
                      case head(Bin) of
                          {undefined, _} -> Acc;
                          {Name, Uses} ->
                              case maps:is_key(Name, Acc) of
                                  true -> Acc;
                                  false -> Acc#{Name => {Bin, Uses}}
                              end
                      end
              end, #{}, Files),
    Wanted = [<<"core">> | lists:append([element(2, head(T)) || T <- Texts])],
    E1 = lists:foldl(fun(M, E) -> place(M, Heads, [], E) end, Engine, Wanted),
    lists:foldl(fun(T, E) -> gt_engine:load_pack(E, T) end, E1, Texts).

pack_text(Root, Name) ->
    Def = filename:join([Root, "packs", Name, "pack.def"]),
    case file:read_file(Def) of
        {ok, Bin} -> Bin;
        {error, _} ->
            gt_pack:load_error('unknown-format', "no pack ~s under ~s",
                               [Name, filename:join(Root, "packs")])
    end.

%% A module no file declares is left to the pack's load: unknown-module.
place(Name, Heads, Path, Engine) ->
    case maps:is_key(Name, gt_engine:modules(Engine)) orelse not maps:is_key(Name, Heads) of
        true -> Engine;
        false ->
            case lists:member(Name, Path) of
                true -> gt_pack:load_error('bad-directive',
                                           "the modules of ~s use one another in a cycle", [Name]);
                false -> ok
            end,
            {Text, Uses} = maps:get(Name, Heads),
            E1 = lists:foldl(fun(U, E) -> place(U, Heads, [Name | Path], E) end,
                             Engine, [U || U <- Uses, U =/= Name]),
            gt_engine:load_model(E1, Text)
    end.

%% The `module` name and the `uses` names of a module or pack text. Only the
%% lines that start with one of the two words are tokenized: a pack file runs
%% to megabytes.
head(Bin) ->
    Toks = [gt_pack:tokens(L) || L <- binary:split(Bin, <<"\n">>, [global]), head_line(L)],
    {case [N || [<<"module">>, N] <- Toks] of
         [N | _] -> N;
         [] -> undefined
     end,
     [U || [<<"uses">>, U] <- Toks]}.

head_line(<<C, Rest/binary>>) when C =:= $\s; C =:= $\t -> head_line(Rest);
head_line(<<"uses", _/binary>>) -> true;
head_line(<<"module", _/binary>>) -> true;
head_line(_) -> false.

to_list(B) when is_binary(B) -> binary_to_list(B);
to_list(L) when is_list(L) -> L.

dedup(L) -> dedup(L, []).
dedup([], Acc) -> lists:reverse(Acc);
dedup([H | T], Acc) ->
    case lists:member(H, Acc) of
        true -> dedup(T, Acc);
        false -> dedup(T, [H | Acc])
    end.
