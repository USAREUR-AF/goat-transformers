// Written for the tests of tools/gen/zcl2pack.py.
import {BuffaloZclDataType, DataType, ParameterCondition} from "./enums";

export const Clusters: Readonly<Record<ClusterName, Cluster>> = {
    demoCluster: {
        name: "demoCluster",
        ID: 0x0fc0,
        attributes: {
            level: {name: "level", ID: 0x0000, type: DataType.UINT8, report: true, max: 0xff},
            label: {name: "label", ID: 0x0001, type: DataType.CHAR_STR, default: ""},
            reading: {name: "reading", ID: 0x0002, type: DataType.INT16},
            items: {name: "items", ID: 0x0003, type: DataType.ARRAY},
        },
        commands: {
            set: {name: "set", ID: 0x00, parameters: [{name: "level", type: DataType.UINT8}, {name: "mask", type: 0b11}]},
            ping: {name: "ping", ID: 0x01, parameters: []},
            list: {name: "list", ID: 0x02, parameters: [{name: "ids", type: BuffaloZclDataType.LIST_UINT8}]},
        },
        commandsResponse: {
            state: {name: "state", ID: 0x00, parameters: [{name: "on", type: DataType.BOOLEAN}]},
        },
    },
};
