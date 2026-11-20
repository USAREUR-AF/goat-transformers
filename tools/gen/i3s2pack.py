#!/usr/bin/env python3
"""i3s2pack: write the packs of the JSON resources of Indexed 3D Scene Layers (I3S).

I3S is an OGC Community Standard (OGC 17-014) whose text Esri keeps at
github.com/Esri/i3s-spec. The text publishes no JSON Schema: each resource is a page of
markdown with a table of members. This script holds the member layouts of the resources it
writes, restated in this project's words from those tables (LAYOUTS below; the names,
nesting and JSON types of the members, and a description of each written here), and writes:

  model/i3s.def                    the keys and lists of every pack (one module)
  packs/i3s-*/pack.def             wire `json`, one `field` line per scalar member,
                                   one `group` per array
  packs/i3s-*/pack.md, PROVENANCE.md
  packs/i3s-*/vectors/*.json       round trips and refusals

The vectors are documents built from the layouts with values written for them; their
canonical output is worked out here by the rules of spec/engine-spec.md (0.5 `json` wire,
kinds, residue and canonical output; 0.7 groups; ruling 3 of 0.1.1 number text). No engine
is run and no pack.def is read back.

Usage: python3 -I tools/gen/i3s2pack.py [--out DIR] [--check]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REPO = "https://github.com/Esri/i3s-spec"
COMMIT = "6cfdef9024ca1abc6c9f3b408ce941abfe287f0e"
SOURCE_NOTE = "derived by tools/gen/i3s2pack.py from the member layouts it holds and spec/engine-spec.md; no engine run"

# -- the layout language -----------------------------------------------------------------------
# S(member, transform, meaning)       a scalar member: string, int, float or bool
# O(member, [children])               an object member
# A(member, transform, meaning)       an array of scalars: a list with `.` items
# A(member, [children], meaning)      an array of objects: a list, its items mapped by the children


def S(m, tr, meaning):
    return ("S", m, tr, meaning)


def O(m, children):
    return ("O", m, children)


def A(m, item, meaning, n=2):
    """`n`: how many items the vectors write (the size the specification fixes, where it fixes one)."""
    return ("A", m, item, meaning, n)


def snake(name):
    s = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name)
    s = re.sub(r"(?<=[A-Z])([A-Z][a-z])", r"_\1", s)
    return s.lower()


# -- shared objects ------------------------------------------------------------------------------

def SPATIAL_REFERENCE():
    return O("spatialReference", [
        S("wkid", "int", "well-known ID of the horizontal coordinate system"),
        S("latestWkid", "int", "the most recent well-known ID of the same horizontal coordinate system"),
        S("vcsWkid", "int", "well-known ID of the vertical coordinate system"),
        S("latestVcsWkid", "int", "the most recent well-known ID of the same vertical coordinate system"),
        S("wkt", "string", "the coordinate system as well-known text, for a system without an ID")])


def HEIGHT_MODEL_INFO():
    return O("heightModelInfo", [
        S("heightModel", "string", "kind of heights: gravity_related_height or ellipsoidal"),
        S("vertCRS", "string", "name of the vertical coordinate system"),
        S("heightUnit", "string", "unit of the heights: meter, foot, us-foot, ...")])


def SERVICE_UPDATE():
    return O("serviceUpdateTimeStamp", [S("lastUpdate", "float", "time of the last update of the layer, as the number the service gives")])


def FULL_EXTENT():
    return O("fullExtent", [SPATIAL_REFERENCE()] + [
        S(m, "float", "%s of the layer's 3D extent, in the layer's coordinate system" % w)
        for m, w in (("xmin", "least x"), ("ymin", "least y"), ("xmax", "greatest x"), ("ymax", "greatest y"),
                     ("zmin", "least z"), ("zmax", "greatest z"))])


def VALUE(member):
    return O(member, [
        S("valueType", "string", "type of each value of the binary buffer (UInt8, Int32, Float64, String, ...)"),
        S("encoding", "string", "encoding of the values, such as UTF-8 for strings"),
        S("timeEncoding", "string", "encoding of date values held as strings (ECMA_ISO8601)"),
        S("valuesPerElement", "float", "number of values that make one element")])


def GEOMETRY_ATTRIBUTE(member):
    return O(member, [
        S("byteOffset", "float", "offset of the attribute in the geometry buffer, in bytes"),
        S("valueType", "string", "type of each value (Float32, UInt8, ...)"),
        S("valuesPerElement", "float", "number of values per vertex")])


def STORE():
    return O("store", [
        S("id", "string", "identifier of the store; layers with the same store ID share their storage"),
        S("profile", "string", "profile of the store: meshpyramids, points, ..."),
        A("resourcePattern", "string", "resource kinds the store holds (3dNodeIndexDocument, Geometry, Texture, ...)"),
        S("rootNode", "string", "relative URL of the root node"),
        S("version", "string", "version of the I3S format the store follows"),
        A("extent", "float", "2D extent of the store: xmin, ymin, xmax, ymax", 4),
        S("indexCRS", "string", "coordinate system of the index, as a URL"),
        S("vertexCRS", "string", "coordinate system of the vertices, as a URL"),
        S("normalReferenceFrame", "string", "frame the normal vectors are given in: east-north-up, earth-centered or vertex-reference-frame"),
        S("nidEncoding", "string", "media type of the node index documents"),
        S("featureEncoding", "string", "media type of the feature data"),
        S("geometryEncoding", "string", "media type of the geometry"),
        S("attributeEncoding", "string", "media type of the attribute buffers"),
        A("textureEncoding", "string", "media types of the textures, in order of preference"),
        S("lodType", "string", "level-of-detail scheme: MeshPyramid, AutoThinning, Clustering or Generalizing"),
        S("lodModel", "string", "how a client moves between levels of detail: node-switching or none"),
        S("indexingScheme", "string", "indexing scheme of the store"),
        O("defaultGeometrySchema", [
            S("geometryType", "string", "geometry type of the default schema (triangles)"),
            S("topology", "string", "topology of the default schema: PerAttributeArray or Indexed"),
            A("header", [S("property", "string", "name of a header value of the geometry buffer"),
                         S("type", "string", "type of that header value")], "header values of the geometry buffer, in order"),
            A("ordering", "string", "order of the vertex attributes in the buffer"),
            O("vertexAttributes", [GEOMETRY_ATTRIBUTE(m) for m in ("position", "normal", "uv0", "color", "region")]),
            A("featureAttributeOrder", "string", "order of the feature attributes in the buffer"),
            O("featureAttributes", [VALUE("id"), VALUE("faceRange")])])])


def NODE_PAGE_DEFINITION(member):
    return O(member, [
        S("nodesPerPage", "int", "number of nodes in each node page"),
        S("rootIndex", "int", "index of the root node"),
        S("lodSelectionMetricType", "string", "metric that selects the level of detail: maxScreenThreshold or maxScreenThresholdSQ")])


def FIELDS():
    return A("fields", [S("name", "string", "name of an attribute field"),
                        S("type", "string", "type of the field (esriFieldTypeInteger, esriFieldTypeString, ...)"),
                        S("alias", "string", "display name of the field")], "attribute fields of the layer")


def ATTRIBUTE_STORAGE_INFO():
    return A("attributeStorageInfo", [
        S("key", "string", "key of an attribute buffer, which names its resource"),
        S("name", "string", "name of the field the buffer holds"),
        A("header", [S("property", "string", "what a header value counts (count, attributeValuesByteCount)"),
                     S("valueType", "string", "type of that header value")], "header values of the attribute buffer"),
        A("ordering", "string", "order of the parts of the buffer (attributeByteCounts, attributeValues, ObjectIds)"),
        VALUE("attributeValues"), VALUE("attributeByteCounts"), VALUE("objectIds")],
        "layout of each binary attribute buffer")


def STATISTICS_INFO():
    return A("statisticsInfo", [S("key", "string", "key of the statistics resource"),
                                S("name", "string", "name of the field the statistics describe"),
                                S("href", "string", "relative URL of the statistics resource")],
             "statistics resources of the layer, one per field")


def MATERIAL_TEXTURE(member, factor):
    return O(member, [S("textureSetDefinitionId", "int", "index of the texture set the texture comes from"),
                      S("texCoord", "int", "set of texture coordinates the texture uses")]
             + ([S("factor", "float", "scale of the texture's effect")] if factor else []))


def LAYER_COMMON(layer_types):
    return [S("id", "int", "numeric ID of the layer, unique in its service"),
            S("href", "string", "relative URL of the layer resource, in a service description"),
            S("layerType", "string", "layer type: %s" % layer_types),
            SPATIAL_REFERENCE(), HEIGHT_MODEL_INFO(),
            S("version", "string", "ID of the last update session that changed a resource of the layer"),
            S("name", "string", "name of the layer"),
            SERVICE_UPDATE(),
            S("alias", "string", "display name of the layer"),
            S("description", "string", "description of the layer"),
            S("copyrightText", "string", "copyright and usage statement for the layer's data"),
            A("capabilities", "string", "capabilities of the layer: View, Query, Edit, Extract"),
            S("ZFactor", "float", "factor that converts elevation units"),
            O("cachedDrawingInfo", [S("color", "bool", "whether the color of the drawing information is held in the mesh")]),
            O("elevationInfo", [S("mode", "string", "how the layer is placed vertically: relativeToGround, absoluteHeight, onTheGround, relativeToScene"),
                                S("offset", "float", "vertical offset"),
                                S("unit", "string", "unit of the offset")]),
            S("disablePopup", "bool", "whether a client hides popups"),
            STORE(), FIELDS(), ATTRIBUTE_STORAGE_INFO(), STATISTICS_INFO()]


def LAYER_TAIL():
    return [FULL_EXTENT(),
            O("timeInfo", [S("startTimeField", "string", "field that holds the start time of a feature"),
                           S("endTimeField", "string", "field that holds the end time of a feature")]),
            O("rangeInfo", [S("field", "string", "field whose values filter the features by range"),
                            S("name", "string", "name of the range filter")])]


GEOMETRY_BUFFER_ATTRS = [
    O(m, [S("type", "string", "type of each value of the %s attribute" % m),
          S("component", "int", "number of values per element of the %s attribute" % m),
          S("encoding", "string", "encoding of the %s attribute" % m),
          S("binding", "string", "what one element of the %s attribute belongs to: per-vertex, per-feature, ..." % m)])
    for m in ("position", "normal", "uv0", "color", "uvRegion", "featureId", "faceRange")]

COMPRESSED = O("compressedAttributes", [
    S("encoding", "string", "compression of the buffer (draco)"),
    A("attributes", "string", "attributes the compressed buffer holds, in order")])

MESH_LAYER = LAYER_COMMON("3DObject or IntegratedMesh") + [
    NODE_PAGE_DEFINITION("nodePages"),
    A("materialDefinitions", [
        O("pbrMetallicRoughness", [A("baseColorFactor", "float", "base color factors: red, green, blue, alpha", 4),
                                   MATERIAL_TEXTURE("baseColorTexture", False),
                                   S("metallicFactor", "float", "metalness of the material"),
                                   S("roughnessFactor", "float", "roughness of the material"),
                                   MATERIAL_TEXTURE("metallicRoughnessTexture", False)]),
        MATERIAL_TEXTURE("normalTexture", True), MATERIAL_TEXTURE("occlusionTexture", True),
        MATERIAL_TEXTURE("emissiveTexture", True),
        A("emissiveFactor", "float", "emissive color factors: red, green, blue", 3),
        S("alphaMode", "string", "how alpha is applied: opaque, mask or blend"),
        S("alphaCutoff", "float", "alpha below which a pixel is not drawn, in mask mode"),
        S("doubleSided", "bool", "whether both sides of a face are drawn"),
        S("cullFace", "string", "faces not drawn: none, front or back")], "material classes of the layer"),
    A("textureSetDefinitions", [
        A("formats", [S("name", "string", "name of the texture resource"),
                      S("format", "string", "format of the texture: jpg, png, dds, ktx-etc2, ktx2")], "formats in which the texture set is stored"),
        S("atlas", "bool", "whether the textures are atlases")], "texture sets meshes can refer to"),
    A("geometryDefinitions", [
        S("topology", "string", "topology of the geometry (triangle)"),
        A("geometryBuffers", [S("offset", "int", "bytes to skip at the start of the buffer")] + GEOMETRY_BUFFER_ATTRS + [COMPRESSED],
          "buffers of one geometry layout: uncompressed, compressed")], "layouts of mesh geometry"),
] + LAYER_TAIL()

POINT_LAYER = LAYER_COMMON("Point") + [
    NODE_PAGE_DEFINITION("pointNodePages"),
    O("geometryDefinition", [S("topology", "string", "topology of the geometry (point)"),
                             A("geometryBuffers", [COMPRESSED], "buffers of the point geometry")]),
] + LAYER_TAIL()


def OBB():
    return O("obb", [A("center", "float", "centre of the oriented bounding box: x, y, z", 3),
                     A("halfSize", "float", "half the size of the box along each of its axes", 3),
                     A("quaternion", "float", "orientation of the box as a quaternion: x, y, z, w", 4)])


NODE_PAGE = [A("nodes", [
    S("index", "int", "index of the node within the layer"),
    S("parentIndex", "int", "index of the parent node"),
    S("lodThreshold", "float", "level-of-detail threshold of the node, in the layer's metric"),
    OBB(),
    A("children", "int", "indexes of the child nodes"),
    O("mesh", [O("material", [S("definition", "int", "index of the material definition"),
                              S("resource", "int", "ID of the texture resource"),
                              S("texelCountHint", "int", "estimate of the number of texels")]),
               O("geometry", [S("definition", "int", "index of the geometry definition"),
                              S("resource", "int", "ID of the geometry resource"),
                              S("vertexCount", "int", "number of vertices"),
                              S("featureCount", "int", "number of features")]),
               O("attribute", [S("resource", "int", "ID of the attribute resource")])])],
    "nodes of the page, in order of their index")]


def HISTOGRAM():
    return O("histogram", [S("minimum", "float", "lower bound of the first bin"),
                           S("maximum", "float", "upper bound of the last bin"),
                           A("counts", "float", "number of values in each bin")])


STATISTICS = [O("stats", [
    S("totalValuesCount", "float", "number of values the statistics were computed from"),
    S("min", "float", "least value"), S("max", "float", "greatest value"),
    S("minTimeStr", "string", "least value of a date field, as text"),
    S("maxTimeStr", "string", "greatest value of a date field, as text"),
    S("count", "float", "number of values"), S("sum", "float", "sum of the values"),
    S("avg", "float", "mean of the values"), S("stddev", "float", "standard deviation of the values"),
    S("variance", "float", "variance of the values"), HISTOGRAM(),
    A("mostFrequentValues", [S("count", "float", "how often the value occurs")],
      "most frequent values and their counts (the value itself is not mapped: it is a number or a string)")])]


def SUBLAYER_SCALARS():
    return [S("id", "int", "ID of the sublayer"), S("name", "string", "name of the sublayer"),
            S("alias", "string", "display name of the sublayer"),
            S("discipline", "string", "building discipline: Architectural, Structural, Mechanical, ..."),
            S("modelName", "string", "name that identifies the sublayer's category across models"),
            S("layerType", "string", "group, 3DObject or Point"),
            S("visibility", "bool", "whether the sublayer is shown by default"),
            S("isEmpty", "bool", "whether the sublayer holds no features")]


BUILDING_LAYER = [
    S("id", "int", "numeric ID of the layer, unique in its service"),
    S("name", "string", "name of the layer"),
    S("version", "string", "ID of the last update session that changed a resource of the layer"),
    S("alias", "string", "display name of the layer"),
    S("layerType", "string", "layer type: Building"),
    S("description", "string", "description of the layer"),
    S("copyrightText", "string", "copyright and usage statement for the layer's data"),
    FULL_EXTENT(), SPATIAL_REFERENCE(), HEIGHT_MODEL_INFO(),
    A("sublayers", SUBLAYER_SCALARS() + [A("sublayers", SUBLAYER_SCALARS(), "sublayers of a group sublayer")],
      "sublayers of the building, grouped by discipline"),
    A("filters", [S("id", "string", "ID of the filter"), S("name", "string", "name of the filter"),
                  S("description", "string", "description of the filter"),
                  S("isDefaultFilter", "bool", "whether the filter is the default one"),
                  S("isVisible", "bool", "whether the filter is offered to users")], "saved filters of the building"),
    S("activeFilterID", "string", "ID of the filter applied by default"),
    S("statisticsHRef", "string", "relative URL of the building's statistics resource"),
    A("capabilities", "string", "capabilities of the layer: View, Query, Edit, Extract")]

BUILDING_STATISTICS = [A("summary", [
    S("fieldName", "string", "name of the field the summary describes"),
    S("label", "string", "display name of the field"),
    S("modelName", "string", "category of the field across models: category, family, bldgLevel, ..."),
    S("min", "float", "least value of the field"), S("max", "float", "greatest value of the field"),
    A("subLayerIds", "int", "IDs of the sublayers the field occurs in")], "one summary per field")]

PC_VALUE = lambda m: O(m, [S("valueType", "string", "type of each value (UInt8, Int32, Float64, ...)"),  # noqa: E731
                           S("valuesPerElement", "float", "number of values that make one element")])

POINT_CLOUD_LAYER = [
    S("id", "int", "numeric ID of the layer, unique in its service"),
    S("layerType", "string", "layer type: PointCloud"),
    S("name", "string", "name of the layer"), S("alias", "string", "display name of the layer"),
    S("desc", "string", "description of the layer"),
    S("copyrightText", "string", "copyright and usage statement for the layer's data"),
    A("capabilities", "string", "capabilities of the layer: View, Query, Extract"),
    SPATIAL_REFERENCE(), HEIGHT_MODEL_INFO(), SERVICE_UPDATE(),
    O("store", [S("id", "string", "identifier of the store"), S("profile", "string", "profile of the store (PointCloud)"),
                S("version", "string", "version of the I3S format the store follows"),
                A("extent", "float", "2D extent of the store: xmin, ymin, xmax, ymax", 4),
                O("index", [S("nodeVersion", "int", "version of the node pages"),
                            S("nodesPerPage", "int", "number of nodes in each node page"),
                            S("boundingVolumeType", "string", "kind of bounding volume of a node (obb)"),
                            S("lodSelectionMetricType", "string", "metric that selects the level of detail (density-threshold)"),
                            S("href", "string", "relative URL of the node pages")]),
                O("defaultGeometrySchema", [S("geometryType", "string", "geometry type (points)"),
                                            S("topology", "string", "topology (PerAttributeArray)"),
                                            S("encoding", "string", "encoding of the point positions (lepcc-xyz)"),
                                            A("ordering", "string", "order of the vertex attributes"),
                                            O("vertexAttributes", [PC_VALUE("position")])]),
                S("geometryEncoding", "string", "media type of the geometry"),
                S("attributeEncoding", "string", "media type of the attribute buffers")]),
    A("attributeStorageInfo", [S("key", "string", "key of an attribute buffer, which names its resource"),
                               S("name", "string", "name of the attribute"),
                               A("ordering", "string", "order of the parts of the buffer"),
                               S("encoding", "string", "compression of the buffer: embedded-elevation, lepcc-intensity, lepcc-rgb"),
                               PC_VALUE("attributeValues")], "layout of each attribute buffer of the points"),
    O("elevationInfo", [S("mode", "string", "how the layer is placed vertically"), S("offset", "float", "vertical offset")]),
    FIELDS()]

POINT_CLOUD_NODE_PAGE = [A("nodes", [
    S("resourceId", "int", "ID of the node's resources"), S("firstChild", "int", "index of the node's first child"),
    S("childCount", "int", "number of children"), S("vertexCount", "int", "number of points in the node"),
    OBB(), S("lodThreshold", "float", "level-of-detail threshold of the node")], "nodes of the page, in order")]

POINT_CLOUD_STATISTICS = [
    S("attribute", "string", "name of the attribute the statistics describe"),
    O("stats", [S("min", "float", "least value"), S("max", "float", "greatest value"), S("count", "float", "number of values"),
                S("sum", "float", "sum of the values"), S("avg", "float", "mean of the values"),
                S("stddev", "float", "standard deviation of the values"), S("variance", "float", "variance of the values"),
                HISTOGRAM(),
                A("mostFrequentValues", [S("value", "float", "a frequent value"), S("count", "float", "how often the value occurs")],
                  "most frequent values and their counts")]),
    O("labels", [A("labels", [S("value", "float", "a value of the attribute"), S("label", "string", "text shown for that value")],
                   "texts for values of the attribute"),
                 A("bitfieldLabels", [S("bitNumber", "int", "a bit of the attribute"), S("label", "string", "text shown for that bit")],
                   "texts for bits of the attribute")])]

# -- the packs ------------------------------------------------------------------------------------
# (format, title, files of the specification read, kinds [(name, when value of layerType or None,
# layout)], notes)

D110, D21 = "docs/1.10/", "docs/2.1/"
PACKS = [
    ("i3s-scene-layer", "the 3DSceneLayer resource (3DSceneLayerInfo) of a 3D object, integrated mesh or point scene layer, I3S 1.10",
     [D110 + "3DSceneLayer.cmn.md", D110 + "3DSceneLayer.psl.md"],
     [("3d-object", "3DObject", MESH_LAYER), ("integrated-mesh", "IntegratedMesh", MESH_LAYER), ("point", "Point", POINT_LAYER)]),
    ("i3s-node-page", "a node page of a 3D object, integrated mesh or point scene layer, I3S 1.10",
     [D110 + "nodePage.cmn.md"], [(None, None, NODE_PAGE)]),
    ("i3s-statistics", "the statistics resource of one attribute of a scene layer, I3S 1.10",
     [D110 + "stats.cmn.md"], [(None, None, STATISTICS)]),
    ("i3s-building-layer", "the layer resource of a building scene layer, I3S 1.10",
     [D110 + "layer.bld.md"], [("building", "Building", BUILDING_LAYER)]),
    ("i3s-building-statistics", "the statistics summary of a building scene layer, I3S 1.10",
     [D110 + "stats.bld.md"], [(None, None, BUILDING_STATISTICS)]),
    ("i3s-point-cloud-layer", "the layer resource of a point cloud scene layer, I3S 2.1",
     [D21 + "layer.pcsl.md"], [("point-cloud", "PointCloud", POINT_CLOUD_LAYER)]),
    ("i3s-point-cloud-node-page", "a node page of a point cloud scene layer, I3S 2.1",
     [D21 + "nodePageDefinition.pcsl.md"], [(None, None, POINT_CLOUD_NODE_PAGE)]),
    ("i3s-point-cloud-statistics", "the statistics resource of one attribute of a point cloud scene layer, I3S 2.1",
     [D21 + "statistics.pcsl.md"], [(None, None, POINT_CLOUD_STATISTICS)]),
]

# SHA-256 of each file of the specification read, at COMMIT
SHA = {
    D110 + "3DSceneLayer.cmn.md": "685f37d1fe81094690071b52775c7cf2c5fd878513d0453f00c05e8b182370c5",
    D110 + "3DSceneLayer.psl.md": "883e95d5550b6ea83124b410d54209e2ef667369a82ac36554d2d0219c6881ad",
    D110 + "nodePage.cmn.md": "8297e8a9122e460fd5deba42fdd20f728715cfe24f1308b8d04c3fb4d356f246",
    D110 + "stats.cmn.md": "3f4d13a8ef5e1a534d13a7ec23c98ef80eb5bfcb15f56484fea8673ef6480543",
    D110 + "layer.bld.md": "ea3f3a0d25c4c6239e4e6ce82243ff29b8bf4d91dc378c7a5fbf4bbd68d31d51",
    D110 + "stats.bld.md": "4edba8a1e687f74a3edf9bdc604879f669357ea4208ed2720203458d40618c84",
    D21 + "layer.pcsl.md": "39aa6ea27dd6cb4fad2c1f547642659ad3b04300810cc8711a149db0d8cc7dac",
    D21 + "nodePageDefinition.pcsl.md": "dd3e7c320b07f7fafa89cd3960e66689c4eaeed6942b620d6b81a57025e9d4b9",
    D21 + "statistics.pcsl.md": "23fa9517e301b0fea8a138908ab6176dc65f5df428810205f30237180e442d68",
    "LICENSE.md": "60cf8b478e159c4956e0c030fe314f9b3a2079ec62dd03d13b4f17be63442fcb",
    "README.md": "3aad2c8196117c55c52a69f153604fec2f476e85f8d3dd1234d86a049d8f3fe3",
}

KEY_TYPE = {"string": "string", "int": "int", "float": "float", "bool": "int"}


# -- lines and keys --------------------------------------------------------------------------------
# A line is ("f", path, key, transform), or ("g", path, list, [lines]) with paths relative to the
# enclosing scope; ("w", path, value) is a `when`.

def lines_of(layout, prefix, path, keys):
    """The lines of a layout. `prefix` is the name of the enclosing list ("" at the top), `path`
    the member path within the scope. `keys` collects name -> (kind, type, meaning)."""
    out = []
    for node in layout:
        if node[0] == "S":
            p = path + (node[1],)
            name = "_".join(([prefix] if prefix else []) + [snake(x) for x in p])
            declare(keys, name, "key", KEY_TYPE[node[2]], node[3] + ("; true or false, held as 1 or 0" if node[2] == "bool" else ""))
            out.append(("f", p, "i3s." + name, node[2]))
        elif node[0] == "O":
            out += lines_of(node[2], prefix, path + (node[1],), keys)
        else:
            p = path + (node[1],)
            lname = "_".join(([prefix] if prefix else []) + [snake(x) for x in p])
            declare(keys, lname, "list", None, node[3])
            if isinstance(node[2], str):
                declare(keys, lname + "_value", "key", KEY_TYPE[node[2]], "one item of %s" % lname)
                body = [("f", (), "i3s.%s_value" % lname, node[2])]
            else:
                body = lines_of(node[2], lname, (), keys)
            out.append(("g", p, "i3s." + lname, body))
    return out


def declare(keys, name, kind, vt, meaning):
    old = keys.get(name)
    if old and (old[0], old[1]) != (kind, vt):
        raise SystemExit("i3s2pack: %s is declared as %s %s and as %s %s" % (name, old[0], old[1], kind, vt))
    if not old:
        keys[name] = (kind, vt, meaning)


def all_packs():
    keys = {}
    packs = []
    for fmt, title, files, kinds in PACKS:
        ks = []
        for kname, layer_type, layout in kinds:
            lines = lines_of(layout, "", (), keys)
            if layer_type:
                lines = [("w", ("layerType",), layer_type)] + lines
            ks.append((kname, lines, layout))
        packs.append((fmt, title, files, ks))
    return keys, packs


# -- emit --------------------------------------------------------------------------------------------

def q(text):
    return '"' + text.replace('"', "'") + '"'


def source_line(files):
    return ("Indexed 3D Scene Layers (I3S, OGC Community Standard 17-014), specification text at %s commit %s, %s. "
            "Member layouts restated by goat-transformers; the specification text is not copied or modified"
            % (REPO, COMMIT, ", ".join(files)))


def emit_module(keys):
    L = ["# The i3s module: the members of the JSON resources of Indexed 3D Scene Layers (I3S) that",
         "# the i3s-* packs map. Generated by tools/gen/i3s2pack.py; do not edit by hand. A key is",
         "# named after its member path; a key inside a list starts with the list's name.",
         "module        i3s", "version       0.1.0", "distribution  public",
         "source        " + q(source_line(sorted({f for _, _, fs, _ in PACKS for f in fs})))]
    w = max(len(k) for k in keys)
    for name in sorted(keys):
        kind, vt, meaning = keys[name]
        if kind == "list":
            L.append("list  %-*s  %s" % (w, name, q(meaning)))
        else:
            L.append("key   %-*s  %-6s  -  %s" % (w, name, vt, q(meaning)))
    return "\n".join(L) + "\n"


def emit_lines(lines, ind, L):
    pad = "  " * ind
    for ln in lines:
        if ln[0] == "w":
            L.append("%swhen    %s  %s" % (pad, ".".join(ln[1]), ln[2]))
        elif ln[0] == "f":
            L.append("%sfield  %s  %s  %s" % (pad, ln[2], ".".join(ln[1]) or ".", ln[3]))
        else:
            L.append("%sgroup  %s  %s" % (pad, ln[2], ".".join(ln[1])))
            emit_lines(ln[3], ind + 1, L)
            L.append(pad + "end")


def emit_pack(fmt, title, files, kinds):
    L = ["# Indexed 3D Scene Layers (I3S): %s." % title,
         "# Public. Generated by tools/gen/i3s2pack.py from the member layouts it holds, restated from the",
         "# I3S specification text; do not edit by hand. Wire json. See pack.md.",
         "format  " + fmt, "version 0.1.0", "distribution public", "source  " + q(source_line(files)),
         "uses    i3s", "wire    json"]
    for kname, lines, _ in kinds:
        L.append("")
        if kname:
            L.append("kind    " + kname)
        emit_lines(lines, 0, L)
    return "\n".join(L) + "\n"


# -- vectors: documents and their canonical output -----------------------------------------------------

class Fail(Exception):
    def __init__(self, kind):
        Exception.__init__(self, kind)
        self.kind = kind


class Picker:
    """Values written for the vectors: every scalar set, two items in every list."""

    def __init__(self):
        self.i = 0

    def value(self, member, tr):
        self.i += 1
        if tr == "string":
            return "%s-%d" % (member, self.i)
        if tr == "int":
            return self.i
        if tr == "bool":
            return self.i % 2 == 0
        return self.i + 0.25

    def doc(self, layout):
        out = {}
        for node in layout:
            if node[0] == "S":
                out[node[1]] = self.value(node[1], node[2])
            elif node[0] == "O":
                out[node[1]] = self.doc(node[2])
            elif isinstance(node[2], str):
                out[node[1]] = [self.value(node[1], node[2]) for _ in range(node[4])]
            else:
                out[node[1]] = [self.doc(node[2]) for _ in range(node[4])]
        return out


def at(obj, path):
    for name in path:
        if not isinstance(obj, dict) or name not in obj:
            return None
        obj = obj[name]
    return obj


def value_of(v, tr):
    if tr == "string":
        if not isinstance(v, str):
            raise Fail("transform-decode")
        return v
    if tr == "bool":
        if not isinstance(v, bool):
            raise Fail("transform-decode")
        return v
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Fail("transform-decode")
    if tr == "int":
        if float(v) != int(v):
            raise Fail("transform-decode")
        return int(v)
    return float(v)


def select(kinds, doc):
    for kname, lines, _ in kinds:
        if all(isinstance(at(doc, ln[1]), str) and at(doc, ln[1]) == ln[2] for ln in lines if ln[0] == "w"):
            return kname, lines
    raise Fail("no-kind")


def decode(lines, obj, ent, prefix=""):
    for ln in lines:
        if ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                x = value_of(v, ln[3])
                ent[prefix + ln[2]] = (1 if x else 0) if ln[3] == "bool" else x
        elif ln[0] == "g":
            arr = at(obj, ln[1])
            if arr is None:
                continue
            ent[prefix + ln[2] + ".#"] = len(arr)
            for i, item in enumerate(arr):
                decode(ln[3], item, ent, "%s%s[%d]." % (prefix, ln[2], i))


def put(out, path, value):
    for name in path[:-1]:
        out = out.setdefault(name, {})
    out[path[-1]] = value


def encode_lines(lines, obj):
    out = {}
    for ln in lines:
        if ln[0] == "w":
            put(out, ln[1], ln[2])
        elif ln[0] == "f":
            v = at(obj, ln[1]) if ln[1] else obj
            if v is not None:
                value = value_of(v, ln[3])
                if not ln[1]:
                    return value
                if ln[1] not in [l2[1] for l2 in lines if l2[0] == "w"]:
                    put(out, ln[1], value)
        else:
            arr = at(obj, ln[1])
            if arr is not None:
                put(out, ln[1], [encode_lines(ln[3], item) for item in arr])
    return out


def add_residue(out, obj, mapped, path=()):
    for name, v in obj.items():
        p = path + (name,)
        if p in mapped or v is None or isinstance(v, list):
            continue
        if isinstance(v, dict):
            sub = out.get(name) if isinstance(out.get(name), dict) else {}
            add_residue(sub, v, mapped, p)
            if sub and name not in out:
                out[name] = sub
        elif "." not in name:
            out[name] = v


def prune(o):
    if isinstance(o, dict):
        return {k: prune(v) for k, v in o.items() if not (isinstance(v, dict) and not prune(v))}
    if isinstance(o, list):
        return [prune(v) for v in o]
    return o


def num(x):
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    r = repr(float(x))
    if "e" in r or "E" in r:
        from decimal import Decimal
        r = format(Decimal(r), "f")
    return r[:-2] if r.endswith(".0") else r


def text(o):
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + text(v) for k, v in o.items()) + "}"
    if isinstance(o, list):
        return "[" + ",".join(text(v) for v in o) + "]"
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, bool):
        return "true" if o else "false"
    return num(o)


def canonical(kinds, doc):
    kname, lines = select(kinds, doc)
    out = encode_lines(lines, doc)
    add_residue(out, doc, {ln[1] for ln in lines if ln[1]})
    return kname, text(prune(out))


def js(o):
    return json.dumps(o, separators=(",", ":"), ensure_ascii=False)


def vec(fmt, name, doc, kinds, model_keys, reference, error=None):
    v = {"name": name, "from": fmt, "to": fmt, "input": js(doc)}
    if error:
        try:
            kname, lines = select(kinds, doc)
            decode(lines, doc, {})
        except Fail as x:
            if x.kind != error:
                raise SystemExit("i3s2pack: %s/%s fails with %s, not %s" % (fmt, name, x.kind, error))
            v["expect_error"] = error
        else:
            raise SystemExit("i3s2pack: %s/%s decodes" % (fmt, name))
    else:
        kname, out = canonical(kinds, doc)
        v["expect"] = out
        ent = {}
        decode(dict((k, l) for k, l, _ in kinds)[kname], doc, ent)
        model = {"@kind": kname} if kname else {}
        for k in model_keys:
            x = ent[k]
            model[k] = num(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x
        v["model"] = model
    v["source"] = SOURCE_NOTE
    v["reference"] = reference
    return v


def first_keys(lines, n, prefix=""):
    """Up to n model keys of the first scalar lines, and the first list's count."""
    out = []
    for ln in lines:
        if len(out) >= n:
            break
        if ln[0] == "f":
            out.append(prefix + ln[2])
        elif ln[0] == "g":
            out.append(prefix + ln[2] + ".#")
            out += first_keys(ln[3], 1, "%s%s[1]." % (prefix, ln[2]))
    return out[:n + 1]


def vectors(fmt, kinds):
    made = []
    for kname, lines, layout in kinds:
        doc = Picker().doc(layout)
        for ln in lines:
            if ln[0] == "w":
                put(doc, ln[1], ln[2])
        doc = {k: doc[k] for k in sorted(doc, key=lambda m: m != "layerType")} if kname else doc
        label = kname or "resource"
        made.append(("%s-every-member-roundtrip" % label,
                     vec(fmt, "%s-every-member-roundtrip" % label, doc, kinds, first_keys(lines, 5),
                         "every member the pack maps is set, two items in every array (the fixed size where the specification gives one); the output is the input")))
    kname, lines, layout = kinds[0]
    doc = Picker().doc(layout)
    for ln in lines:
        if ln[0] == "w":
            put(doc, ln[1], ln[2])
    extra = dict(doc)
    extra["x-vendor"] = {"note": "kept", "tags": ["dropped"]}
    if fmt == "i3s-scene-layer":
        extra["drawingInfo"] = {"renderer": {"type": "simple", "symbol": {"type": "MeshSymbol3D",
                                                                      "symbolLayers": [{"type": "Fill"}]}}}
        extra["popupInfo"] = {"title": "{NAME}"}
    made.append(("members-not-mapped", vec(fmt, "members-not-mapped", extra, kinds, [],
                 "members the pack does not map: their scalar members come back as residue after the mapped ones, "
                 "arrays among them are not carried (0.5 json residue)" +
                 ("; drawingInfo and popupInfo are such members" if fmt == "i3s-scene-layer" else ""))))
    if kname:
        other = dict(doc)
        other["layerType"] = "VoxelLayer"
        made.append(("another-layer-type", vec(fmt, "another-layer-type", other, kinds, [],
                     "a layerType the pack has no kind for: no-kind", error="no-kind")))
    bad = json.loads(js(doc))
    first = next(ln for ln in lines if ln[0] in ("f", "g"))
    if first[0] == "f":
        put(bad, first[1], "x" if first[3] != "string" else 1)
        what = "%s holds a value of the wrong JSON type" % ".".join(first[1])
    else:
        item = first[3][0]
        target = at(bad, first[1])[0]
        if item[1]:
            put(target, item[1], "x" if item[3] != "string" else 1)
        what = "an item of %s holds a value of the wrong JSON type" % ".".join(first[1])
    made.append(("wrong-json-type", vec(fmt, "wrong-json-type", bad, kinds, [], what + ": transform-decode",
                                        error="transform-decode")))
    return made


# -- pack.md and PROVENANCE.md ---------------------------------------------------------------------------

def count_lines(lines):
    f = g = 0
    for ln in lines:
        if ln[0] == "f":
            f += 1
        elif ln[0] == "g":
            g += 1
            a, b = count_lines(ln[3])
            f, g = f + a, g + b
    return f, g


def emit_md(fmt, title, files, kinds, made):
    L = ["# %s" % fmt, "", "Indexed 3D Scene Layers (I3S): %s. Wire `json`." % title,
         "Generated by `tools/gen/i3s2pack.py` from member layouts it holds, restated in this project's words",
         "from the tables of the I3S specification text (%s at commit `%s`: %s)." % (REPO, COMMIT, ", ".join("`%s`" % f for f in files)),
         "The specification publishes no JSON Schema. Uses the module `i3s` (`model/i3s.def`).", ""]
    if kinds[0][0]:
        L += ["| Kind | Holds when | `field` lines | lists |", "|---|---|---|---|"]
        for kname, lines, _ in kinds:
            f, g = count_lines(lines)
            L.append("| `%s` | `layerType` is `%s` | %d | %d |" % (kname, lines[0][2], f, g))
    else:
        f, g = count_lines(kinds[0][1])
        L.append("No kinds: the resource has no member that names its type. %d `field` lines, %d lists." % (f, g))
    L += ["", "## How members are written", "",
          "| Member | Line |", "|---|---|",
          "| a string, integer or number | `field` with `string`, `int` or `float`; a key named after the member path |",
          "| a boolean | `field` with `bool`: the key holds 1 or 0 |",
          "| an object | its members, with dotted paths |",
          "| an array of scalars | `group` of `.` items: a list, its items under `<list>_value` |",
          "| an array of objects | `group`: a list, its item keys starting with the list's name |",
          "", "## Shared-model keys: none, and why", "",
          "No I3S resource here holds the position of one object: a layer holds an extent (a box) and a",
          "coordinate system, a node holds an oriented bounding box in the layer's system, and statistics hold",
          "values of attributes. Nothing is bound to `lat`, `lon`, `hae` or `time_ms`; the time of the last",
          "update is the layer's, not an observation's, and stays the raw key",
          "`i3s.service_update_time_stamp_last_update`.",
          "", "## Not mapped", ""]
    L += NOT_MAPPED.get(fmt, []) + COMMON_NOT_MAPPED
    L += ["", "## Vectors", "",
          "Derived by `tools/gen/i3s2pack.py` from the layouts and the rules of `spec/engine-spec.md`; no engine run.", "",
          "| File | Shows |", "|---|---|"]
    L += ["| `%s` | %s |" % (fn, v["reference"]) for fn, v in made]
    return "\n".join(L) + "\n"


COMMON_NOT_MAPPED = [
    "- Members a table of the specification marks deprecated or that hold another document's",
    "  structure are not listed in the layouts; their scalar members come back as residue and their",
    "  arrays do not (0.5 `json` residue carries no arrays). Inside a list item nothing that is not",
    "  mapped comes back: an item carries no residue (0.7).",
    "- The binary resources (geometry, textures, attribute buffers, point cloud LEPCC data) and the",
    "  scene layer package (SLPK) archive: they are not JSON."]

NOT_MAPPED = {
    "i3s-scene-layer": [
        "- `drawingInfo` and `popupInfo`: they hold the ArcGIS renderer and popup definitions, whose",
        "  structure the I3S tables leave to those documents. Their scalars are residue; their arrays",
        "  (unique value infos, symbol layers, field infos) are not carried.",
        "- `fields[].domain`, `store.defaultTextureDefinition`, `store.defaultMaterialDefinition`:",
        "  deprecated or of free structure.",
        "- The 3DNodeIndexDocument and the shared resources of the 1.6-style node tree: node pages",
        "  replace them in 1.7 and later (`i3s-node-page`)."],
    "i3s-statistics": [
        "- The `value` of a most frequent value: it is a number or a string, by the field's type, and a",
        "  line reads one JSON type. Its `count` is mapped."],
    "i3s-building-layer": [
        "- Sublayers below the second level: the layout maps a group sublayer's sublayers and stops there.",
        "- The filter blocks and filter authoring information of a filter."],
    "i3s-building-statistics": [
        "- `mostFrequentValues`: an array of integers or of strings, by the field."],
    "i3s-point-cloud-layer": [
        "- `drawingInfo`: the point cloud renderer, whose structure the I3S tables leave to that document."],
}


PROVENANCE = """# Provenance of the {fmt} pack

Generated by `tools/gen/i3s2pack.py`, which holds the member layouts of the I3S JSON resources,
restated in this project's words from the specification text. No file of the specification is
kept in this repository, and no specification text is copied or modified: the pack and the module
`i3s` state member names, their nesting and their JSON types, and describe each member in this
project's words. Read on 2026-11-20.

## Source

| Fact | Value |
|---|---|
| standard | Indexed 3D Scene Layers (I3S), an OGC Community Standard (OGC 17-014); the community specification is kept by Esri |
| repository | {repo} |
| commit | `{commit}` |
| files read | {files} |
| licence files | `LICENSE.md` (SHA-256 `{lic}`), `README.md` (SHA-256 `{readme}`) |

## Licence

The specification's README states:

> Both the current I3S specifciation and the OGC standard are licensed under the Creative Commons
> Attribution-NoDerivatives 4.0 International Public License. Implementers can use the standard in
> services, clients or processing tools without restrictions.

and, in its licence section:

> The specification is licensed under the Creative Commons Attribution-NoDerivatives 4.0
> International Public License.

The no-derivatives term governs copies of the specification document. This pack is an
implementation of the standard, which the README permits without restriction; it is not a copy,
modified or not, of the specification. The pack, the module and the generator are this project's
work and carry its licence: `Apache-2.0`. Credit: the I3S specification is the work of Esri, and
OGC published it as a Community Standard; neither has reviewed or endorsed this implementation.
"""


def emit_provenance(fmt, files):
    return PROVENANCE.format(
        fmt=fmt, repo=REPO, commit=COMMIT,
        files="; ".join("`%s` (SHA-256 `%s`)" % (f, SHA[f]) for f in files),
        lic=SHA["LICENSE.md"], readme=SHA["README.md"])


def dump(v):
    return json.dumps(v, indent=2, ensure_ascii=False) + "\n"


def build(out):
    keys, packs = all_packs()
    out.write("model/i3s.def", emit_module(keys))
    written = {}
    for fmt, title, files, kinds in packs:
        base = "packs/%s/" % fmt
        made = vectors(fmt, kinds)
        made = [("%02d-%s.json" % (i + 1, n), v) for i, (n, v) in enumerate(made)]
        for rel in (out.listdir(base + "vectors") if out.exists(base + "vectors") else []):
            if rel.endswith(".json") and rel not in dict(made):
                out.remove(base + "vectors/" + rel)
        for fn, v in made:
            out.write(base + "vectors/" + fn, dump(v))
        out.write(base + "pack.def", emit_pack(fmt, title, files, kinds))
        out.write(base + "pack.md", emit_md(fmt, title, files, kinds, made))
        out.write(base + "PROVENANCE.md", emit_provenance(fmt, files))
        written[fmt] = len(made)
    return written


def main(argv=None):
    return genio.vector_main("i3s2pack.py", __doc__, build, argv)


if __name__ == "__main__":
    sys.exit(main())
