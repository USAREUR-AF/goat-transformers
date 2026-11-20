/* Synthetic header written for the cstruct2pack tests: two messages, one
   refused layout and one id whose type is never declared. */
#define DID_POS      (eDataIDs)1   /**< (pos_t) a position */
#define DID_STAT     (eDataIDs)2   /**< (stat_t) a status */
#define DID_BAD      (eDataIDs)3   /**< (bad_t) bit-fields */
#define DID_MISSING  (eDataIDs)4   /**< (nope_t) no such type */

#define PUSH_PACK_1  _Pragma("pack(push, 1)")
#define POP_PACK     _Pragma("pack(pop)")

PUSH_PACK_1

typedef struct
{
    uint32_t    week;
    double      tow;
} gtime_t;

typedef struct PACKED
{
    gtime_t     time;
    double      lla[3];         //!< latitude, longitude in degrees, height over the ellipsoid in metres
    float       vel[3];
    char        name[NAME_LEN];
    uint8_t     mode;
} pos_t;

typedef struct
{
    uint16_t    count;
    int16_t     samples[LONG_N];
    uint8_t     flags[2][3];
    int64_t     big;
} stat_t;

typedef struct
{
    uint32_t    a : 4;
    uint32_t    b : 28;
} bad_t;

POP_PACK

int not_a_type(void);
