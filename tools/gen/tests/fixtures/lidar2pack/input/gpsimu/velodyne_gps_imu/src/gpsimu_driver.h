// Synthetic stand-in for gpsimu_driver.h, written for the lidar2pack tests.
#pragma pack(1)
struct GyroTempAccelBlockRaw
{
    uint16_t gyro;
    uint16_t temp;
};
struct VelodynePositioningPacketRaw
{
    char _not_used1[2];
    GyroTempAccelBlockRaw gyro_temp_accel[2];
    uint32_t gps_timestamp;
    char nmea_sentence[4];
};
#pragma pack()
