// Written for the aplog2pack tests: the tables the generator reads.
const struct UnitStructure log_Units[] = {
    { '-', "" },
    { 'D', "deglatitude" },
    { 'U', "deglongitude" },
    { 'm', "m" },
    { 's', "s" },
};
const struct MultiplierStructure log_Multipliers[] = {
    { '-', 0 },
    { '0', 1e0 },
    { 'B', 1e-2 },
    { 'F', 1e-6 },
    { 'G', 1e-7 },
};
#define LOG_COMMON_STRUCTURES \
    { LOG_FORMAT_MSG, sizeof(log_Format), \
      "FMT", "BBnNZ", "Type,Length,Name,Format,Columns", "-b---", "-----" }, \
    { LOG_POS_MSG, sizeof(log_POS), \
      "POS", "QLLfff", "TimeUS,Lat,Lng,Alt,RelHomeAlt,RelOriginAlt", "sDUmmm", "FGG000" }
