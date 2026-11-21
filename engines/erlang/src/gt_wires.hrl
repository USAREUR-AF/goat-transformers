%% gt_wires.hrl: the wires of a build (engine-spec Version 0.24, ruling 1).
%%
%% A build has every wire unless it is compiled with `-Dno_wire_<wire>` for
%% the wires it leaves out (build.sh --wires does this, and leaves the
%% wire's own modules out of ebin/). ?W_<WIRE> is true when the wire is in
%% the build. Code a wire alone needs is compiled under `-if(?W_<WIRE>).`;
%% a dispatch clause of a wire that is left out calls ?ABSENT(Wire), which no
%% conversion reaches: a pack on such a wire does not load (ruling 1c).
-ifdef(no_wire_xml).
-define(W_XML, false).
-else.
-define(W_XML, true).
-endif.
-ifdef(no_wire_geojson).
-define(W_GEOJSON, false).
-else.
-define(W_GEOJSON, true).
-endif.
-ifdef(no_wire_json).
-define(W_JSON, false).
-else.
-define(W_JSON, true).
-endif.
-ifdef(no_wire_bits).
-define(W_BITS, false).
-else.
-define(W_BITS, true).
-endif.
-ifdef(no_wire_protobuf).
-define(W_PROTOBUF, false).
-else.
-define(W_PROTOBUF, true).
-endif.
-ifdef(no_wire_text).
-define(W_TEXT, false).
-else.
-define(W_TEXT, true).
-endif.
-ifdef(no_wire_tlv).
-define(W_TLV, false).
-else.
-define(W_TLV, true).
-endif.
-ifdef(no_wire_cbor).
-define(W_CBOR, false).
-else.
-define(W_CBOR, true).
-endif.

%% Every wire in the build.
-define(W_ALL, (?W_XML andalso ?W_GEOJSON andalso ?W_JSON andalso ?W_BITS
                andalso ?W_PROTOBUF andalso ?W_TEXT andalso ?W_TLV
                andalso ?W_CBOR)).

-define(ABSENT(Wire), erlang:error({wire_not_in_build, Wire})).

%% An expression only a wire of the build evaluates.
-if(?W_XML).
-define(XML(E), E).
-else.
-define(XML(E), ?ABSENT(xml)).
-endif.
-if(?W_GEOJSON).
-define(GEOJSON(E), E).
-else.
-define(GEOJSON(E), ?ABSENT(geojson)).
-endif.
-if(?W_JSON).
-define(JSON(E), E).
-else.
-define(JSON(E), ?ABSENT(json)).
-endif.
%% json or geojson: the JSON text members and arrays both wires read
-if(?W_JSON orelse ?W_GEOJSON).
-define(JSONTEXT(E), E).
-else.
-define(JSONTEXT(E), ?ABSENT(json)).
-endif.
-if(?W_BITS).
-define(BITS(E), E).
-else.
-define(BITS(E), ?ABSENT(bits)).
-endif.
-if(?W_PROTOBUF).
-define(PROTOBUF(E), E).
-else.
-define(PROTOBUF(E), ?ABSENT(protobuf)).
-endif.
-if(?W_TEXT).
-define(TEXT(E), E).
-else.
-define(TEXT(E), ?ABSENT(text)).
-endif.
-if(?W_TLV).
-define(TLV(E), E).
-else.
-define(TLV(E), ?ABSENT(tlv)).
-endif.
-if(?W_CBOR).
-define(CBOR(E), E).
-else.
-define(CBOR(E), ?ABSENT(cbor)).
-endif.

%% A dispatch clause of a wire left out keeps its head; its variables are
%% then unused.
-if(not ?W_ALL).
-compile([nowarn_unused_vars]).
-endif.
