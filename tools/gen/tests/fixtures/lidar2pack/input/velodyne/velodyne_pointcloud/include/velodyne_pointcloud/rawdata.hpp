// Synthetic stand-in for rawdata.hpp, written for the lidar2pack tests.
static const int SIZE_BLOCK = 10;
static const int RAW_SCAN_SIZE = 3;
static const int SCANS_PER_BLOCK = 2;
static const int PACKET_SIZE = 26;
static const int BLOCKS_PER_PACKET = 2;
static const int PACKET_STATUS_SIZE = 4;
struct raw_block
{
  uint16_t header;    ///< a bank
  uint16_t rotation;  ///< an angle
  uint8_t data[BLOCK_DATA_SIZE];
};
struct raw_packet
{
  raw_block blocks[BLOCKS_PER_PACKET];
  uint16_t revolution;
  uint8_t status[PACKET_STATUS_SIZE];
};
