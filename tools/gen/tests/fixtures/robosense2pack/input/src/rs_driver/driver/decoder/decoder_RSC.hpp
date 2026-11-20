// Synthetic model C, written for the robosense2pack tests: the stated length
// differs from the struct's size, so it is not built.
#pragma pack(push, 1)
typedef struct
{
  uint8_t id[2];
  uint16_t value;
} RSCMsopPkt;
#pragma pack(pop)

inline RSDecoderMechConstParam& DecoderRSC<T_PointCloud>::getConstParam()
{
  static RSDecoderMechConstParam param =
  {
      5 // msop len
    , 2 // msop id len
    , {0x01, 0x02} // msop id
  };
  return param;
}
