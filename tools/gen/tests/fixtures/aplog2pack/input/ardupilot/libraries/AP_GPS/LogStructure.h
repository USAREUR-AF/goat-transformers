// Written for the aplog2pack tests.
#define GPS_LABELS "TimeUS,I,Status,HDop,Lat,Lng,Alt,Name"
#define LOG_STRUCTURE_FROM_GPS \
    { LOG_GPS_MSG, sizeof(log_GPS), \
      "GPS", "QBBcLLen", GPS_LABELS, "s---DUm-", "F---GGB-" }, \
    { LOG_AHR2_MSG, sizeof(log_AHR2), "AHR2", "QLL", "TimeUS,Lat,Lng", "sDU", "FGG" }, \
    { LOG_EAHR_MSG, sizeof(log_EAHR), "EAHR", "QLL", "TimeUS,Lat,Lon", "sDU", "FGG" }, \
    { LOG_SIM_MSG, sizeof(log_SIM), "SIM", "QLL", "TimeUS,Lat,Lng", "sDU", "FGG" }, \
    { LOG_CAM_MSG, sizeof(log_CAM), "CAM", "QBLL", "TimeUS,I,Lat,Lng", "s-DU", "F-GG" }, \
    { LOG_TRIG_MSG, sizeof(log_TRIG), "TRIG", "QBLL", "TimeUS,I,Lat,Lng", "s-DU", "F-GG" }
