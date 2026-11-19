
## A vehicle's chassis detail

The envelope is the chassis detail of one vehicle line that Apollo's canbus module supports: one
field per CAN frame of that vehicle's bus, each a message of the signals of that frame, decoded
into their engineering values. Which frames and signals there are depends on the vehicle line, so
each line has a pack of its own. The values are those of the vehicle's own signals (pedal
positions, steering angle, wheel speeds, gear, faults); none is a shared key. A position some
vehicles report (degrees, minutes and seconds as separate integers, with no datum stated) is left
raw.
