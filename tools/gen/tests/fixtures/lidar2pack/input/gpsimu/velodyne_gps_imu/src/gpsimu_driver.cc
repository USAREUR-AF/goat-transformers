// Synthetic stand-in for gpsimu_driver.cc, written for the lidar2pack tests:
// the 12-bit conversion and the three factors the generator checks.
int16_t convert12bit2int16(uint16_t v)
{
  v = v & 0x0fff;
  int16_t r=v;
  if(r>2047)
      r=-((~(r--)) & 0x0fff);
  return r;
}
      g = convert12bit2int16(raw.gyro) * 0.09766;
      t = convert12bit2int16(raw.temp) * 0.1453+25;
      a = convert12bit2int16(raw.accel_x) * 0.001221;
