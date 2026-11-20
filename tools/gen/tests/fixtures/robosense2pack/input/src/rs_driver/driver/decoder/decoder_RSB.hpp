// Synthetic model B, written for the robosense2pack tests: the same identity bytes
// for both packets, and a DIFOP struct whose prefix differs from the file's.
#pragma pack(push, 1)
typedef struct
{
  uint8_t id[2];
  uint16_t value;
} RSBMsopPkt;

typedef struct
{
  uint8_t id[2];
  uint32_t value;
} XRSBDifopPkt;
#pragma pack(pop)

inline RSDecoderMechConstParam& DecoderRSB<T_PointCloud>::getConstParam()
{
  static RSDecoderMechConstParam param =
  {
      4 // msop len
    , 6 // difop len
    , 2 // msop id len
    , 2 // difop id len
    , {0x12, 0x34} // msop id
    , {0x12, 0x34} // difop id
  };
  return param;
}
