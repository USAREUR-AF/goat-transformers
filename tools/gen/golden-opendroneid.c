/* golden-opendroneid.c: encodes Remote ID messages with opendroneid-core-c's
 * encoders, decodes them with its decoders and prints one line per message:
 *   name <TAB> kind <TAB> hex <TAB> key=value <TAB> ...
 * Built and read by tools/gen/golden-opendroneid.py. Uses no engine. Values
 * come from the library's decoders; the wire-integer keys (direction_raw,
 * ew_direction, speed_h_raw, speed_mult, timestamp_ds) come from the fields of
 * the library's encoded struct. A code the encoder refuses stops the program. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "opendroneid.h"

static void need(int rc, const char *what) {
    if (rc != ODID_SUCCESS) { fprintf(stderr, "golden-opendroneid: %s failed\n", what); exit(1); }
}
static void head(const char *kind, int n, const void *p, size_t len) {
    const unsigned char *b = p;
    printf("golden-%s-%d\t%s\t", kind, n, kind);
    for (size_t i = 0; i < len; i++) printf("%02x", b[i]);
}
#define I(k, v) printf("\t%s=i:%ld", k, (long)(v))
#define F(k, v) printf("\t%s=f:%.17g", k, (double)(v))
#define S(k, v) printf("\t%s=s:%s", k, v)

static ODID_Message_encoded basic(int n, int ua, int id, const char *uid) {
    ODID_BasicID_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initBasicIDData(&d); d.UAType = ua; d.IDType = id; strncpy(d.UASID, uid, ODID_ID_SIZE);
    need(encodeBasicIDMessage(&m.basicId, &d), "encodeBasicIDMessage");
    need(decodeBasicIDMessage(&r, &m.basicId), "decodeBasicIDMessage");
    if (n) { head("basic-id", n, &m, ODID_MESSAGE_SIZE);
        I("rid.msg_type", decodeMessageType(m.rawData[0])); I("rid.proto_version", ODID_PROTOCOL_VERSION);
        I("rid.ua_type", r.UAType); I("rid.id_type", r.IDType); S("uid", r.UASID); putchar('\n'); }
    return m;
}
static ODID_Message_encoded location(int n, int st, float dir, float sh, float sv, double lat, double lon,
                                     float baro, float geo, int ht, float h, int ac, float ts) {
    ODID_Location_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initLocationData(&d);
    d.Status = st; d.Direction = dir; d.SpeedHorizontal = sh; d.SpeedVertical = sv; d.Latitude = lat; d.Longitude = lon;
    d.AltitudeBaro = baro; d.AltitudeGeo = geo; d.HeightType = ht; d.Height = h;
    d.HorizAccuracy = 1 + ac % 12; d.VertAccuracy = 1 + ac % 6; d.BaroAccuracy = 1 + (ac + 2) % 6;
    d.SpeedAccuracy = 1 + ac % 4; d.TSAccuracy = 1 + ac % 15; d.TimeStamp = ts;
    need(encodeLocationMessage(&m.location, &d), "encodeLocationMessage");
    need(decodeLocationMessage(&r, &m.location), "decodeLocationMessage");
    if (n) { head("location", n, &m, ODID_MESSAGE_SIZE);
        I("rid.msg_type", decodeMessageType(m.rawData[0])); I("rid.status", r.Status);
        I("rid.direction_raw", m.location.Direction); I("rid.ew_direction", m.location.EWDirection);
        I("rid.speed_h_raw", m.location.SpeedHorizontal); I("rid.speed_mult", m.location.SpeedMult);
        F("rid.speed_v", r.SpeedVertical); F("lat", r.Latitude); F("lon", r.Longitude);
        F("rid.alt_baro", r.AltitudeBaro); F("hae", r.AltitudeGeo); I("rid.height_type", r.HeightType);
        F("rid.height", r.Height); I("rid.horiz_acc", r.HorizAccuracy); I("rid.vert_acc", r.VertAccuracy);
        I("rid.baro_acc", r.BaroAccuracy); I("rid.speed_acc", r.SpeedAccuracy); I("rid.ts_acc", r.TSAccuracy);
        I("rid.timestamp_ds", m.location.TimeStamp); putchar('\n'); }
    return m;
}
static void auth(const char *kind, int n, int page, int type, int last, int len, unsigned ts, int b) {
    ODID_Auth_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initAuthData(&d); d.DataPage = page; d.AuthType = type;
    if (!page) { d.LastPageIndex = last; d.Length = len; d.Timestamp = ts; }
    /* the pack maps the last data byte of a page only, so only it is set */
    d.AuthData[(page ? ODID_AUTH_PAGE_NONZERO_DATA_SIZE : ODID_AUTH_PAGE_ZERO_DATA_SIZE) - 1] = b;
    need(encodeAuthMessage(&m.auth, &d), "encodeAuthMessage");
    memset(&r, 0, sizeof r);
    need(decodeAuthMessage(&r, &m.auth), "decodeAuthMessage");
    head(kind, n, &m, ODID_MESSAGE_SIZE);
    I("rid.msg_type", decodeMessageType(m.rawData[0])); I("rid.auth_type", r.AuthType);
    if (page) { I("rid.auth_data_page", r.DataPage); I("rid.auth_data_last", r.AuthData[ODID_AUTH_PAGE_NONZERO_DATA_SIZE - 1]); }
    else { I("rid.auth_last_page_index", r.LastPageIndex); I("rid.auth_length", r.Length); I("rid.auth_timestamp", r.Timestamp);
           I("rid.auth_data_last", r.AuthData[ODID_AUTH_PAGE_ZERO_DATA_SIZE - 1]); }
    putchar('\n');
}
static ODID_Message_encoded self(int n, int type, const char *s) {
    ODID_SelfID_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initSelfIDData(&d); d.DescType = type; strncpy(d.Desc, s, ODID_STR_SIZE);
    need(encodeSelfIDMessage(&m.selfId, &d), "encodeSelfIDMessage");
    need(decodeSelfIDMessage(&r, &m.selfId), "decodeSelfIDMessage");
    if (n) { head("self-id", n, &m, ODID_MESSAGE_SIZE); I("rid.msg_type", decodeMessageType(m.rawData[0]));
        I("rid.desc_type", r.DescType); S("rid.description", r.Desc); putchar('\n'); }
    return m;
}
static ODID_Message_encoded sys(int n, int lt, int cl, double lat, double lon, int cnt, int rad, float ceil, float floor_,
                                int cat, int cls, float hae, unsigned ts) {
    ODID_System_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initSystemData(&d); d.OperatorLocationType = lt; d.ClassificationType = cl; d.OperatorLatitude = lat;
    d.OperatorLongitude = lon; d.AreaCount = cnt; d.AreaRadius = rad; d.AreaCeiling = ceil; d.AreaFloor = floor_;
    d.CategoryEU = cat; d.ClassEU = cls; d.OperatorAltitudeGeo = hae; d.Timestamp = ts;
    need(encodeSystemMessage(&m.system, &d), "encodeSystemMessage");
    need(decodeSystemMessage(&r, &m.system), "decodeSystemMessage");
    if (n) { head("system", n, &m, ODID_MESSAGE_SIZE); I("rid.msg_type", decodeMessageType(m.rawData[0]));
        I("rid.operator_location_type", r.OperatorLocationType); I("rid.classification_type", r.ClassificationType);
        F("rid.operator_lat", r.OperatorLatitude); F("rid.operator_lon", r.OperatorLongitude);
        I("rid.area_count", r.AreaCount); F("rid.area_radius", r.AreaRadius); F("rid.area_ceiling", r.AreaCeiling);
        F("rid.area_floor", r.AreaFloor);
        I("rid.category_eu", r.CategoryEU); I("rid.class_eu", r.ClassEU);
        F("rid.operator_hae", r.OperatorAltitudeGeo); I("rid.system_timestamp", r.Timestamp); putchar('\n'); }
    return m;
}
static ODID_Message_encoded oper(int n, int type, const char *s) {
    ODID_OperatorID_data d, r; ODID_Message_encoded m; memset(&m, 0, sizeof m);
    odid_initOperatorIDData(&d); d.OperatorIdType = type; strncpy(d.OperatorId, s, ODID_ID_SIZE);
    need(encodeOperatorIDMessage(&m.operatorId, &d), "encodeOperatorIDMessage");
    need(decodeOperatorIDMessage(&r, &m.operatorId), "decodeOperatorIDMessage");
    if (n) { head("operator-id", n, &m, ODID_MESSAGE_SIZE); I("rid.msg_type", decodeMessageType(m.rawData[0]));
        I("rid.operator_id_type", r.OperatorIdType); S("rid.operator_id", r.OperatorId); putchar('\n'); }
    return m;
}
static void pack(int n, ODID_Message_encoded *ms, int count) {
    ODID_MessagePack_data d; ODID_MessagePack_encoded m; ODID_UAS_Data u; memset(&m, 0, sizeof m);
    odid_initMessagePackData(&d); d.MsgPackSize = count; memcpy(d.Messages, ms, count * sizeof *ms);
    need(encodeMessagePack(&m, &d), "encodeMessagePack");
    odid_initUasData(&u); need(decodeMessagePack(&u, &m), "decodeMessagePack");
    head("message-pack", n, &m, 3 + count * ODID_MESSAGE_SIZE);
    I("rid.msg_type", decodeMessageType(m.ProtoVersion | m.MessageType << 4)); I("rid.pack_msg_size", m.SingleMessageSize);
    I("rid.messages.#", m.MsgPackSize);
    for (int i = 0; i < m.MsgPackSize; i++)
        printf("\trid.messages[%d].rid.msg_type=i:%d\trid.messages[%d].rid.proto_version=i:%d", i,
               decodeMessageType(m.Messages[i].rawData[0]), i, m.Messages[i].basicId.ProtoVersion);
    putchar('\n');
}
int main(void) {
    basic(1, 2, 1, "1ABCD123456789012345"); basic(2, 1, 2, "FIN87astrdge12k8"); basic(3, 15, 1, "9QXYZ"); basic(4, 6, 1, "1A");
    location(1, 2, 37.0f, 12.25f, 3.5f, 48.1251234, 11.5823456, 520.5f, 567.0f, 0, 80.5f, 1, 1234.5f);
    location(2, 2, 215.0f, 5.5f, -4.5f, -33.8688197, 151.2092955, 101.0f, 88.5f, 1, 42.0f, 2, 0.1f);
    location(3, 3, 179.0f, 100.5f, 61.5f, 40.7127753, -74.0059728, 10.5f, -22.5f, 0, 12.0f, 3, 3599.9f);
    location(4, 1, 180.0f, 63.75f, -61.5f, -54.8019121, -68.3029511, -400.5f, 25.5f, 1, -10.5f, 4, 1800.0f);
    location(5, 2, 359.0f, 0.25f, 0.5f, -0.0012345, 179.9876543, 3000.0f, 2999.5f, 0, 0.5f, 5, 59.9f);
    location(6, 2, 1.0f, 254.25f, -0.5f, 78.2231722, 15.6267229, 12000.0f, 12050.5f, 1, 120.0f, 6, 3000.3f);
    auth("auth-page0", 1, 0, 1, 2, 63, 28000000u, 0x5a); auth("auth-page0", 2, 0, 2, 1, 40, 239000001u, 0xff);
    auth("auth-page", 1, 1, 1, 0, 0, 0, 0xa5); auth("auth-page", 2, 15, 3, 0, 0, 0, 1);
    self(1, 0, "DronesRUS: Real Estate"); self(2, 1, "Emergency landing now!!"); self(3, 2, "Low battery");
    sys(1, 1, 1, 48.1251111, 11.5821111, 1, 0, 120.0f, 0.5f, 1, 3, 530.5f, 28056789u);
    sys(2, 0, 0, -33.8681111, 151.2091111, 35, 750, 176.5f, 41.5f, 0, 0, 20.5f, 239000001u);
    sys(3, 2, 1, 40.7121111, -74.0051111, 65000, 2550, 5000.0f, -30.5f, 3, 7, -25.5f, 2147483649u);
    oper(1, 0, "FIN87astrdge12k8"); oper(2, 0, "GBR-OP-1234567890ABC"); oper(3, 0, "X1");
    ODID_Message_encoded ms[6] = { basic(0, 2, 1, "1ABCD123456789012345"),
        location(0, 2, 37.0f, 12.25f, 3.5f, 48.1251234, 11.5823456, 520.5f, 567.0f, 0, 80.5f, 1, 1234.5f),
        self(0, 0, "DronesRUS: Real Estate"),
        sys(0, 1, 1, 48.1251111, 11.5821111, 1, 0, 120.0f, 0.5f, 1, 3, 530.5f, 28056789u), oper(0, 0, "FIN87astrdge12k8") };
    pack(1, ms, 1); pack(2, ms, 3); pack(3, ms, 5);
    return 0;
}
