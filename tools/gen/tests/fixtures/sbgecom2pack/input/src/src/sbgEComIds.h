/* Synthetic stand-in for sbgEComIds.h, written for the sbgecom2pack tests. */
typedef enum _SbgEComClass
{
    SBG_ECOM_CLASS_LOG_ECOM_0   = 0x00,     /*!< a comment */
    SBG_ECOM_CLASS_LOG_ECOM_1   = 0x01,
    SBG_ECOM_CLASS_LOG_CMD_0    = 0x10
} SbgEComClass;

typedef enum _SbgEComLog
{
    SBG_ECOM_LOG_NAV            = 8,
    SBG_ECOM_LOG_EXTRA,
    SBG_ECOM_LOG_LOOPED         = 20
} SbgEComLog;

typedef enum _SbgEComLog1
{
    SBG_ECOM_LOG_FAST           = 0
} SbgEComLog1;
