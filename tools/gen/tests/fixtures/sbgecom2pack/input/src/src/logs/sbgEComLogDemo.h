/* Synthetic stand-in for a log header, written for the sbgecom2pack tests. */
#define DEMO_BLOB_SIZE      (4)

typedef struct _SbgEComLogDemoExtra
{
    uint32_t    timeStamp;
    uint8_t     blob[DEMO_BLOB_SIZE];
} SbgEComLogDemoExtra;
