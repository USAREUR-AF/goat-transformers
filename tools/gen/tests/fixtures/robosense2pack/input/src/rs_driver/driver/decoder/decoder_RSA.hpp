// Synthetic model A, written for the robosense2pack tests: distinct identities,
// nested struct arrays, a #define array size and a long byte array.
#define A_CHANNELS 2
#pragma pack(push, 1)
typedef struct
{
  uint8_t id[4];
  RSTimestampUTC timestamp;
} RSAMsopHeader;

typedef struct
{
  uint16_t azimuth;
  RSChannel channels[A_CHANNELS];
} RSABlock;

typedef struct
{
  RSAMsopHeader header;
  RSABlock blocks[2];
  int16_t tail;
} RSAMsopPkt;

typedef struct
{
  uint8_t id[4];
  uint16_t rpm;
  uint8_t gprmc[10];
  RSCalibrationAngle vert_angle_cali[2];
} RSADifopPkt;
#pragma pack(pop)

inline RSDecoderMechConstParam& DecoderRSA<T_PointCloud>::getConstParam()
{
  static RSDecoderMechConstParam param =
  {
      32 // msop len
    , 22 // difop len
    , 4 // msop id len
    , 4 // difop id len
    , {0x55, 0xAA, 0x05, 0x0A} // msop id
    , {0xA5, 0xFF, 0x00, 0x5A} // difop id
  };
  return param;
}
