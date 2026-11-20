/* Synthetic header written for the cstruct2pack tests (packet mode): a header
   struct with a flexible last member, a type selector, a count, and two item
   structs, under `#pragma pack(1)`. */
#include <stdint.h>

#pragma pack(1)

typedef enum {
  kItemWide = 1,
  kItemNarrow = 0x02
} ItemType;

typedef struct {
  uint8_t  version;
  uint16_t length;
  uint16_t count;
  uint8_t  item_type;
  uint8_t  rsvd[2];
  uint8_t  data[1];
} DemoPacket;

typedef struct {
  int32_t  x;
  uint8_t  flag;
} WideItem;

typedef struct {
  int16_t  x;
  char     label[3];
} NarrowItem;

#pragma pack()
