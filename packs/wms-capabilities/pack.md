# wms-capabilities

The capabilities document a Web Map Service 1.3.0 (OGC 06-042) returns to a
GetCapabilities request: the service's metadata, its operations and output
formats, and its layers. The pack reads it as data about a service, with no
position.

## Message convention

One message is one capabilities document whose root is `WMS_Capabilities`
in the default namespace `http://www.opengis.net/wms`, with `version`
`1.3.0`: clause 7.2.4.1 puts the root in that namespace. Two common `when`
lines check the namespace and version, and the kind `capabilities` checks
that the service Name is `WMS` (clause 7.2.4.3 fixes that value). The
encoder writes all three.

## Mapping

Every value is a raw key of the module `wms`. Lines follow the element order
of the schema in Annex E, so the mapped elements are written in an order the
schema accepts.

| Part | Keys |
|---|---|
| root attribute `updateSequence` | `wms.update_sequence` |
| `Service`: Title, Abstract, KeywordList | `wms.title`, `wms.abstract`, list `wms.keywords` of `wms.keyword` |
| `Service/ContactInformation` | `wms.contact_person`, `wms.contact_organization`, `wms.contact_position`, the six address parts, `wms.contact_phone`, `wms.contact_fax`, `wms.contact_email` |
| `Service`: Fees, AccessConstraints, LayerLimit, MaxWidth, MaxHeight | `wms.fees`, `wms.access_constraints`, `wms.layer_limit`, `wms.max_width`, `wms.max_height` (integers) |
| `Capability/Request`: GetMap and GetFeatureInfo formats | lists `wms.getmap_formats`, `wms.featureinfo_formats` of `wms.format` |
| `Capability/Exception` formats | list `wms.exception_formats` of `wms.format` |
| the top-level `Capability/Layer` | `wms.layer_queryable`, `wms.layer_name`, `wms.layer_title`, `wms.layer_abstract`, list `wms.layer_crs`, the four bounds `wms.layer_west` … `wms.layer_north`, `wms.layer_min_scale`, `wms.layer_max_scale` |
| the layers directly inside it | list `wms.layers`: `wms.queryable`, `wms.opaque`, `wms.name`, `wms.layer_item_title`, `wms.layer_item_abstract`, the four bounds, `wms.min_scale`, `wms.max_scale` |

## Shared-model keys

None is bound. A layer's `EX_GeographicBoundingBox` is the smallest rectangle,
in decimal degrees of longitude and latitude, around the area the layer
covers, and may be approximate (clause 7.2.4.6.6). It is the extent of a
layer, not the position of an entity: binding one corner or the
centre to `lat` and `lon` would state a meaning the document does not have.
The model has no bounding-box keys. Conversions to GeoJSON and CoT therefore
carry nothing, and no conversion vector is written.

## Not mapped

- **Prefixed attributes.** Every `OnlineResource` (of the service and of each
  operation's `DCPType/HTTP/Get` and `Post`), and the URL elements of a layer
  (`AuthorityURL`, `MetadataURL`, `DataURL`, `FeatureListURL`, `LegendURL`,
  `LogoURL`), carry the address in `xlink:href` and `xlink:type`, attributes
  of the XLink namespace with a prefix. The xml wire compares names as
  written and the specification does not rule namespaces (Version 0.11, "Not
  ruled in 0.11"); a locator `OnlineResource/@xlink:href` would depend on the
  prefix a server chose. They are left out and dropped.
- `GetCapabilities` and the `DCPType` of every operation: their content is
  the online resources above. Their formats could be read; only GetMap's and
  GetFeatureInfo's are, as those are the ones a client chooses from.
- `_ExtendedCapabilities` and `_ExtendedOperation`: elements of other
  namespaces.
- Of a layer: `KeywordList`, `BoundingBox` (attributes `CRS`, `minx` … in the
  axis order of each CRS), `Dimension`, `Attribution`, `Identifier`,
  `Style`, and the attributes `cascaded`, `noSubsets`, `fixedWidth`,
  `fixedHeight`. Nested layers deeper than the second level, and the CRS list
  of the inner layers.
- **Unmapped elements are dropped** on a round trip (ruling 6 of 0.1.1); the
  encoder therefore writes a document without the required
  `Service/OnlineResource`, `GetCapabilities` and `DCPType` elements, which
  is not valid against the schema. Unmapped attributes of the root (for
  example `xmlns:xlink`, `xsi:schemaLocation`) are residue and are written
  back.
- **Namespaces.** A document whose root is written with a prefix
  (`<wms:WMS_Capabilities xmlns:wms="…">`) has another root name and matches no kind:
  `no-kind` (vector 03). WMS 1.3.0 servers write the default namespace.
- **WFS 2.0 capabilities** (OGC 09-025r2) are not built: their service
  metadata are OWS Common elements in the namespace
  `http://www.opengis.net/ows/1.1`, written with a prefix next to the WFS
  namespace, for example `<wfs:WFS_Capabilities xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:ows="http://www.opengis.net/ows/1.1"><ows:ServiceIdentification><ows:Title>`.
  A document with two namespaces has prefixed elements whichever prefix is the
  default, and the pack language has no namespace-aware names.
- WMS 1.1.1 has another root (`WMT_MS_Capabilities`), a DTD and no
  namespace: another pack. A 1.1.1 version attribute on a 1.3.0 root is
  `no-kind` (vector 02).

## Candidate pack-language additions

1. Namespace-aware names (docs/roadmap.md, "XML namespaces and prefixes",
   Designed): a pack declares `ns <prefix> <uri>` and its locators match by
   namespace URI, so `OnlineResource/@xlink:href` and WFS's `ows:Title` are
   addressable whatever prefix the document uses.

## Vectors

`tools/gen/ogc-geo-vectors.py` writes each document and its canonical form
from the schema's element order and the xml rules of `spec/engine-spec.md`;
no engine is run.

| File | Case |
|---|---|
| `01-capabilities-roundtrip` | every mapped part, three lists, a nested layer list; online resources, DCPType, GetCapabilities and BoundingBox dropped; root `xmlns:xlink` kept |
| `02-other-version-is-no-kind` | version 1.1.1 |
| `03-prefixed-root-is-no-kind` | the namespace limitation |
| `04-layer-limit-not-integer` | `transform-decode` |
