// Synthetic stand-in for time_conversion.hpp, written for the lidar2pack tests.
  uint32_t usecs =
    static_cast<uint32_t>(
    ((uint32_t) data[3]) << 24 |
      ((uint32_t) data[2]) << 16 |
      ((uint32_t) data[1]) << 8 |
      ((uint32_t) data[0]));
