// Written for the aplog2pack tests: a Write call, and an array field.
void Nav::log()
{
    AP::logger().Write("NAVX", "TimeUS,Arr,Txt,Q", "Qa" "Nd",
                       AP_HAL::micros64(), arr, txt, q);
    AP::logger().WriteStreaming("ORGN", "TimeUS,Lat,Lng", "s" "DU", "FGG", "QLL",
                       AP_HAL::micros64(), lat, lng);
}
