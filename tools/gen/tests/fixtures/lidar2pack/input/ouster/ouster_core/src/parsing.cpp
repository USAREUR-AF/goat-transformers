// Synthetic stand-in for parsing.cpp, written for the lidar2pack tests: two
// small profiles, the packet sizes, the header branches and a legacy IMU block.
static const Table<std::string, FieldDecodeInfo, 3> LEGACY_FIELD_INFO{{
    {ChanField::RANGE, field_info(0, 12)},
    {ChanField::FLAGS, field_info(14, 2)},
    {ChanField::RAW32_WORD1, field_info(0, 32)},
}};

static const Table<std::string, FieldDecodeInfo, 2> SINGLE_FIELD_INFO{{
    {ChanField::RANGE, field_info(0, 19)},
    {ChanField::SIGNAL, field_info(16 + 8, size_t{8} * 1)},
}};

Table<UDPProfileLidar, ProfileEntry, MAX_NUM_PROFILES> OUSTER_API_FUNCTION profiles{{
    {UDPProfileLidar::LEGACY, {LEGACY_FIELD_INFO.data(), LEGACY_FIELD_INFO.size(), 4}},
    {UDPProfileLidar::RNG19_RFL8_SIG16_NIR16,
     {SINGLE_FIELD_INFO.data(), SINGLE_FIELD_INFO.size(), 4}},
}};

struct PacketFormat::Impl {
    explicit Impl(const DataFormat& format) : Impl() {
        packet_header_size = legacy ? 0 : 6;
        col_header_size = legacy ? 4 : 2;
        col_footer_size = legacy ? 1 : 0;
        packet_footer_size = legacy ? 0 : 2;

        if (legacy) {
            frame_id_info = field_info(16, 8);
            auto start_bit = 8 * (col_size - col_footer_size);
            col_status_info = field_info(start_bit, 8, 0, (start_bit + 8) / 8);
        } else if (fusa) {
            packet_type_info = field_info(0, 8);
        } else {
            packet_type_info = field_info(0, 8);
            frame_id_info = field_info(8, 8);
            init_id_info = field_info(16, 8);
            prod_sn_info = field_info(24, 4);
            alert_flags_info = field_info(28, 1);
            countdown_thermal_shutdown_info = field_info(29, 1);
            countdown_shot_limiting_info = field_info(30, 1);
            thermal_shutdown_info = field_info(31, 1);
            shot_limiting_info = field_info(32, 4);

            col_status_info = field_info(8, 8);
        }

        col_timestamp_info = field_info(0, 8);
        col_measurement_id_info = field_info(8, 8);

        imu_profile = format.udp_profile_imu;
        if (imu_profile == UDPProfileIMU::LEGACY) {
            imu_packet_size = 8;
            imu_sys_ts_info = field_info(0, 32, 0, imu_packet_size);
            imu_nmea_ts_info = field_info(0, 0, 0, imu_packet_size);
            imu_la_x_info = field_info(32, 32, 0, imu_packet_size);
        } else if (imu_profile == UDPProfileIMU::ACCEL32_GYRO32_NMEA) {
        }
    }
};

uint64_t PacketFormat::imu_sys_ts(const uint8_t* imu_buf) const {
float PacketFormat::imu_la_x(const uint8_t* imu_buf) const {
