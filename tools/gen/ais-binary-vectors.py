#!/usr/bin/env python3
"""ais-binary-vectors: write the vectors of the ais-binary pack.

Python 3 standard library only; imports no engine and reads no pack.def. The
layouts in LAYOUTS below are this program's restatement of the binary
application messages of types 6 and 8 with a fixed length, from the gpsd
document "AIVDM/AIVDO protocol decoding" v1.58 (www/AIVDM.adoc, BSD-2-Clause):
for each kind, the message type, DAC and FI that select it and every field as
(key, first bit, bits, codec), bit 0 the first bit of the payload, most
significant bit first. Codecs: u unsigned, s two's complement, text six-bit
characters, pos a position in a fraction of a minute (the kind's divisor gives
degrees).

Inputs: payloads built here field by field from values chosen here. No message
is taken from gpsd's samples or from any other document. The six-bit text of a
payload is made here: each six bits, most significant first, as the character
0x30 + v for v below 40 and 0x38 + v from 40 on, with zero bits added to fill
the last character. Six-bit text fields use @ for 0, the letters for 1 to 26,
and 0x20 + v for 32 to 63.

Every `expect` is this program's armoring of the bits it packed; every `model`
value is the value it packed (a position as degrees, the integer divided by
the kind's divisor).

Usage: python3 -I tools/gen/ais-binary-vectors.py [--out DIR] [--check]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

LAYOUTS = [
    ('dangerous-cargo-imo236', 6, 1, 12, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.dc236_lastport', 88, 30, 'text'), ('aisbin.dc236_lmonth', 118, 4, 'u'), ('aisbin.dc236_lday', 122, 5, 'u'),
        ('aisbin.dc236_lhour', 127, 5, 'u'), ('aisbin.dc236_lminute', 132, 6, 'u'), ('aisbin.dc236_nextport', 138, 30, 'text'),
        ('aisbin.dc236_nmonth', 168, 4, 'u'), ('aisbin.dc236_nday', 172, 5, 'u'), ('aisbin.dc236_nhour', 177, 5, 'u'),
        ('aisbin.dc236_nminute', 182, 6, 'u'), ('aisbin.dc236_dangerous', 188, 120, 'text'), ('aisbin.dc236_imdcat', 308, 24, 'text'),
        ('aisbin.dc236_unid', 332, 13, 'u'), ('aisbin.dc236_amount', 345, 10, 'u'), ('aisbin.dc236_unit', 355, 2, 'u'),
        ('ais.spare2', 357, 3, 'u'),
    ]),
    ('persons-on-board-imo289', 6, 1, 16, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.pob289_persons', 88, 13, 'u'), ('ais.spare2', 101, 35, 'u'),
    ]),
    ('clearance-time', 6, 1, 18, 60000, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.linkage', 88, 10, 'u'), ('aisbin.clr_month', 98, 4, 'u'), ('aisbin.clr_day', 102, 5, 'u'),
        ('aisbin.clr_hour', 107, 5, 'u'), ('aisbin.clr_minute', 112, 6, 'u'), ('aisbin.clr_portname', 118, 120, 'text'),
        ('aisbin.clr_destination', 238, 30, 'text'), ('lon', 268, 25, 'pos'), ('lat', 293, 24, 'pos'),
        ('ais.spare2', 317, 43, 'u'),
    ]),
    ('berthing-data', 6, 1, 20, 60000, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.linkage', 88, 10, 'u'), ('aisbin.berth_berth_length', 98, 9, 'u'), ('aisbin.berth_berth_depth', 107, 8, 'u'),
        ('aisbin.berth_position', 115, 3, 'u'), ('aisbin.berth_month', 118, 4, 'u'), ('aisbin.berth_day', 122, 5, 'u'),
        ('aisbin.berth_hour', 127, 5, 'u'), ('aisbin.berth_minute', 132, 6, 'u'), ('aisbin.berth_availability', 138, 1, 'u'),
        ('aisbin.berth_agent', 139, 2, 'u'), ('aisbin.berth_fuel', 141, 2, 'u'), ('aisbin.berth_chandler', 143, 2, 'u'),
        ('aisbin.berth_stevedore', 145, 2, 'u'), ('aisbin.berth_electrical', 147, 2, 'u'), ('aisbin.berth_water', 149, 2, 'u'),
        ('aisbin.berth_customs', 151, 2, 'u'), ('aisbin.berth_cartage', 153, 2, 'u'), ('aisbin.berth_crane', 155, 2, 'u'),
        ('aisbin.berth_lift', 157, 2, 'u'), ('aisbin.berth_medical', 159, 2, 'u'), ('aisbin.berth_navrepair', 161, 2, 'u'),
        ('aisbin.berth_provisions', 163, 2, 'u'), ('aisbin.berth_shiprepair', 165, 2, 'u'), ('aisbin.berth_surveyor', 167, 2, 'u'),
        ('aisbin.berth_steam', 169, 2, 'u'), ('aisbin.berth_tugs', 171, 2, 'u'), ('aisbin.berth_solidwaste', 173, 2, 'u'),
        ('aisbin.berth_liquidwaste', 175, 2, 'u'), ('aisbin.berth_hazardouswaste', 177, 2, 'u'), ('aisbin.berth_ballast', 179, 2, 'u'),
        ('aisbin.berth_additional', 181, 2, 'u'), ('aisbin.berth_regional1', 183, 2, 'u'), ('aisbin.berth_regional2', 185, 2, 'u'),
        ('aisbin.berth_future1', 187, 2, 'u'), ('aisbin.berth_future2', 189, 2, 'u'), ('aisbin.berth_berth_name', 191, 120, 'text'),
        ('lon', 311, 25, 'pos'), ('lat', 336, 24, 'pos'),
    ]),
    ('inland-eta', 6, 200, 21, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.ieta_country', 88, 12, 'text'), ('aisbin.ieta_locode', 100, 18, 'text'), ('aisbin.ieta_section', 118, 30, 'text'),
        ('aisbin.ieta_terminal', 148, 30, 'text'), ('aisbin.ieta_hectometre', 178, 30, 'text'), ('aisbin.ieta_month', 208, 4, 'u'),
        ('aisbin.ieta_day', 212, 5, 'u'), ('aisbin.ieta_hour', 217, 5, 'u'), ('aisbin.ieta_minute', 222, 6, 'u'),
        ('aisbin.ieta_tugs', 228, 3, 'u'), ('aisbin.ieta_airdraught', 231, 12, 'u'), ('ais.spare2', 243, 5, 'u'),
    ]),
    ('inland-rta', 6, 200, 22, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.irta_country', 88, 12, 'text'), ('aisbin.irta_locode', 100, 18, 'text'), ('aisbin.irta_section', 118, 30, 'text'),
        ('aisbin.irta_terminal', 148, 30, 'text'), ('aisbin.irta_hectometre', 178, 30, 'text'), ('aisbin.irta_month', 208, 4, 'u'),
        ('aisbin.irta_day', 212, 5, 'u'), ('aisbin.irta_hour', 217, 5, 'u'), ('aisbin.irta_minute', 222, 6, 'u'),
        ('aisbin.irta_status', 228, 2, 'u'), ('ais.spare2', 230, 2, 'u'),
    ]),
    ('inland-persons-on-board', 6, 200, 55, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.ipob_crew', 88, 8, 'u'), ('aisbin.ipob_passengers', 96, 13, 'u'), ('aisbin.ipob_personnel', 109, 8, 'u'),
        ('ais.spare2', 117, 51, 'u'),
    ]),
    ('aton-monitoring-uk', 6, 235, 10, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.aton_ana_int', 88, 10, 'u'), ('aisbin.aton_ana_ext1', 98, 10, 'u'), ('aisbin.aton_ana_ext2', 108, 10, 'u'),
        ('aisbin.aton_racon', 118, 2, 'u'), ('aisbin.aton_light', 120, 2, 'u'), ('aisbin.aton_health', 122, 1, 'u'),
        ('aisbin.aton_stat_ext', 123, 8, 'u'), ('aisbin.aton_off_pos', 131, 1, 'u'), ('ais.spare2', 132, 4, 'u'),
    ]),
    ('aton-monitoring-roi', 6, 250, 10, None, [
        ('aisbin.seqno', 38, 2, 'u'), ('ais.dest_mmsi', 40, 30, 'u'), ('aisbin.retransmit', 70, 1, 'u'),
        ('ais.spare', 71, 1, 'u'), ('aisbin.dac', 72, 10, 'u'), ('aisbin.fid', 82, 6, 'u'),
        ('aisbin.aton_ana_int', 88, 10, 'u'), ('aisbin.aton_ana_ext1', 98, 10, 'u'), ('aisbin.aton_ana_ext2', 108, 10, 'u'),
        ('aisbin.aton_racon', 118, 2, 'u'), ('aisbin.aton_light', 120, 2, 'u'), ('aisbin.aton_health', 122, 1, 'u'),
        ('aisbin.aton_stat_ext', 123, 8, 'u'), ('aisbin.aton_off_pos', 131, 1, 'u'), ('ais.spare2', 132, 4, 'u'),
    ]),
    ('met-hydro-imo236', 8, 1, 11, 60000, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('lat', 56, 24, 'pos'), ('lon', 80, 25, 'pos'), ('aisbin.mh236_day', 105, 5, 'u'),
        ('aisbin.mh236_hour', 110, 5, 'u'), ('aisbin.mh236_minute', 115, 6, 'u'), ('aisbin.mh236_wspeed', 121, 7, 'u'),
        ('aisbin.mh236_wgust', 128, 7, 'u'), ('aisbin.mh236_wdir', 135, 9, 'u'), ('aisbin.mh236_wgustdir', 144, 9, 'u'),
        ('aisbin.mh236_temperature', 153, 11, 'u'), ('aisbin.mh236_humidity', 164, 7, 'u'), ('aisbin.mh236_dewpoint', 171, 10, 'u'),
        ('aisbin.mh236_pressure', 181, 9, 'u'), ('aisbin.mh236_pressuretend', 190, 2, 'u'), ('aisbin.mh236_visibility', 192, 8, 'u'),
        ('aisbin.mh236_waterlevel', 200, 9, 's'), ('aisbin.mh236_leveltrend', 209, 2, 'u'), ('aisbin.mh236_cspeed', 211, 8, 'u'),
        ('aisbin.mh236_cdir', 219, 9, 'u'), ('aisbin.mh236_cspeed2', 228, 8, 'u'), ('aisbin.mh236_cdir2', 236, 9, 'u'),
        ('aisbin.mh236_cdepth2', 245, 5, 'u'), ('aisbin.mh236_cspeed3', 250, 8, 'u'), ('aisbin.mh236_cdir3', 258, 9, 'u'),
        ('aisbin.mh236_cdepth3', 267, 5, 'u'), ('aisbin.mh236_waveheight', 272, 8, 'u'), ('aisbin.mh236_waveperiod', 280, 6, 'u'),
        ('aisbin.mh236_wavedir', 286, 9, 'u'), ('aisbin.mh236_swellheight', 295, 8, 'u'), ('aisbin.mh236_swellperiod', 303, 6, 'u'),
        ('aisbin.mh236_swelldir', 309, 9, 'u'), ('aisbin.mh236_seastate', 318, 4, 'u'), ('aisbin.mh236_watertemp', 322, 10, 'u'),
        ('aisbin.mh236_preciptype', 332, 3, 'u'), ('aisbin.mh236_salinity', 335, 9, 'u'), ('aisbin.mh236_ice', 344, 2, 'u'),
        ('ais.spare2', 346, 6, 'u'),
    ]),
    ('fairway-closed', 8, 1, 13, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.fwc_reason', 56, 120, 'text'), ('aisbin.fwc_closefrom', 176, 120, 'text'), ('aisbin.fwc_closeto', 296, 120, 'text'),
        ('aisbin.fwc_radius', 416, 10, 'u'), ('aisbin.fwc_extunit', 426, 2, 'u'), ('aisbin.fwc_fday', 428, 5, 'u'),
        ('aisbin.fwc_fmonth', 433, 4, 'u'), ('aisbin.fwc_fhour', 437, 5, 'u'), ('aisbin.fwc_fminute', 442, 6, 'u'),
        ('aisbin.fwc_tday', 448, 5, 'u'), ('aisbin.fwc_tmonth', 453, 4, 'u'), ('aisbin.fwc_thour', 457, 5, 'u'),
        ('aisbin.fwc_tminute', 462, 6, 'u'), ('ais.spare2', 468, 4, 'u'),
    ]),
    ('extended-static-imo236', 8, 1, 15, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.ess236_airdraught', 56, 11, 'u'), ('ais.spare2', 67, 5, 'u'),
    ]),
    ('traffic-signal', 8, 1, 19, 60000, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.linkage', 56, 10, 'u'), ('aisbin.sig_station', 66, 120, 'text'), ('lon', 186, 25, 'pos'),
        ('lat', 211, 24, 'pos'), ('aisbin.sig_status', 235, 2, 'u'), ('aisbin.sig_signal', 237, 5, 'u'),
        ('aisbin.sig_hour', 242, 5, 'u'), ('aisbin.sig_minute', 247, 6, 'u'), ('aisbin.sig_nextsignal', 253, 5, 'u'),
        ('ais.spare2', 258, 64, 'u'), ('ais.spare3', 322, 38, 'u'),
    ]),
    ('weather-observation', 8, 1, 21, 60000, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.wmo', 56, 1, 'u'), ('aisbin.wx_location', 57, 120, 'text'), ('lon', 177, 25, 'pos'),
        ('lat', 202, 24, 'pos'), ('aisbin.wx_day', 226, 5, 'u'), ('aisbin.wx_hour', 231, 5, 'u'),
        ('aisbin.wx_minute', 236, 6, 'u'), ('aisbin.wx_weather', 242, 4, 'u'), ('aisbin.wx_vislimit', 246, 1, 'u'),
        ('aisbin.wx_visibility', 247, 7, 'u'), ('aisbin.wx_humidity', 254, 7, 'u'), ('aisbin.wx_wspeed', 261, 7, 'u'),
        ('aisbin.wx_wdir', 268, 9, 'u'), ('aisbin.wx_pressure', 277, 9, 'u'), ('aisbin.wx_pressuretend', 286, 4, 'u'),
        ('aisbin.wx_airtemp', 290, 11, 's'), ('aisbin.wx_watertemp', 301, 10, 's'), ('aisbin.wx_waveperiod', 311, 6, 'u'),
        ('aisbin.wx_waveheight', 317, 8, 'u'), ('aisbin.wx_wavedir', 325, 9, 'u'), ('aisbin.wx_swellheight', 334, 8, 'u'),
        ('aisbin.wx_swelldir', 342, 9, 'u'), ('aisbin.wx_swellperiod', 351, 6, 'u'), ('ais.spare2', 357, 3, 'u'),
    ]),
    ('weather-observation-wmo', 8, 1, 21, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.wmo', 56, 1, 'u'), ('aisbin.wxw_lon', 57, 16, 'u'), ('aisbin.wxw_lat', 73, 15, 'u'),
        ('aisbin.wxw_month', 88, 4, 'u'), ('aisbin.wxw_day', 92, 6, 'u'), ('aisbin.wxw_hour', 98, 5, 'u'),
        ('aisbin.wxw_minute', 103, 3, 'u'), ('aisbin.wxw_course', 106, 7, 'u'), ('aisbin.wxw_speed', 113, 5, 'u'),
        ('aisbin.wxw_heading', 118, 7, 'u'), ('aisbin.wxw_pressure', 125, 11, 'u'), ('aisbin.wxw_pdelta', 136, 10, 'u'),
        ('aisbin.wxw_ptend', 146, 4, 'u'), ('aisbin.wxw_twinddir', 150, 7, 'u'), ('aisbin.wxw_twindspeed', 157, 8, 'u'),
        ('aisbin.wxw_rwinddir', 165, 7, 'u'), ('aisbin.wxw_rwindspeed', 172, 8, 'u'), ('aisbin.wxw_mgustspeed', 180, 8, 'u'),
        ('aisbin.wxw_mgustdir', 188, 7, 'u'), ('aisbin.wxw_airtemp', 195, 10, 'u'), ('aisbin.wxw_humidity', 205, 7, 'u'),
        ('aisbin.wxw_surftemp', 212, 9, 'u'), ('aisbin.wxw_visibility', 221, 6, 'u'), ('aisbin.wxw_weather', 227, 9, 'u'),
        ('aisbin.wxw_pweather1', 236, 5, 'u'), ('aisbin.wxw_pweather2', 241, 5, 'u'), ('aisbin.wxw_totalcloud', 246, 4, 'u'),
        ('aisbin.wxw_lowclouda', 250, 4, 'u'), ('aisbin.wxw_lowcloudt', 254, 6, 'u'), ('aisbin.wxw_midcloudt', 260, 6, 'u'),
        ('aisbin.wxw_highcloudt', 266, 6, 'u'), ('aisbin.wxw_cloudbase', 272, 7, 'u'), ('aisbin.wxw_wwperiod', 279, 5, 'u'),
        ('aisbin.wxw_wwheight', 284, 6, 'u'), ('aisbin.wxw_swelldir1', 290, 6, 'u'), ('aisbin.wxw_swperiod1', 296, 5, 'u'),
        ('aisbin.wxw_swheight1', 301, 6, 'u'), ('aisbin.wxw_swelldir2', 307, 6, 'u'), ('aisbin.wxw_swperiod2', 313, 5, 'u'),
        ('aisbin.wxw_swheight2', 318, 6, 'u'), ('aisbin.wxw_icedeposit', 324, 7, 'u'), ('aisbin.wxw_icerate', 331, 3, 'u'),
        ('aisbin.wxw_icecause', 334, 3, 'u'), ('aisbin.wxw_seaice', 337, 5, 'u'), ('aisbin.wxw_icetype', 342, 4, 'u'),
        ('aisbin.wxw_icestate', 346, 5, 'u'), ('aisbin.wxw_icedevel', 351, 5, 'u'), ('aisbin.wxw_icebearing', 356, 4, 'u'),
    ]),
    ('extended-static-imo289', 8, 1, 24, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.linkage', 56, 10, 'u'), ('aisbin.ess289_airdraught', 66, 13, 'u'), ('aisbin.ess289_lastport', 79, 30, 'text'),
        ('aisbin.ess289_nextport', 109, 30, 'text'), ('aisbin.ess289_secondport', 139, 30, 'text'), ('aisbin.ess289_ais_state', 169, 2, 'u'),
        ('aisbin.ess289_ata_state', 171, 2, 'u'), ('aisbin.ess289_bnwas_state', 173, 2, 'u'), ('aisbin.ess289_ecdisb_state', 175, 2, 'u'),
        ('aisbin.ess289_chart_state', 177, 2, 'u'), ('aisbin.ess289_sounder_state', 179, 2, 'u'), ('aisbin.ess289_epaid_state', 181, 2, 'u'),
        ('aisbin.ess289_steer_state', 183, 2, 'u'), ('aisbin.ess289_gnss_state', 185, 2, 'u'), ('aisbin.ess289_gyro_state', 187, 2, 'u'),
        ('aisbin.ess289_lrit_state', 189, 2, 'u'), ('aisbin.ess289_magcomp_state', 191, 2, 'u'), ('aisbin.ess289_navtex_state', 193, 2, 'u'),
        ('aisbin.ess289_arpa_state', 195, 2, 'u'), ('aisbin.ess289_sband_state', 197, 2, 'u'), ('aisbin.ess289_xband_state', 199, 2, 'u'),
        ('aisbin.ess289_hfradio_state', 201, 2, 'u'), ('aisbin.ess289_inmarsat_state', 203, 2, 'u'), ('aisbin.ess289_mfradio_state', 205, 2, 'u'),
        ('aisbin.ess289_vhfradio_state', 207, 2, 'u'), ('aisbin.ess289_grndlog_state', 209, 2, 'u'), ('aisbin.ess289_waterlog_state', 211, 2, 'u'),
        ('aisbin.ess289_thd_state', 213, 2, 'u'), ('aisbin.ess289_tcs_state', 215, 2, 'u'), ('aisbin.ess289_vdr_state', 217, 2, 'u'),
        ('ais.spare2', 219, 2, 'u'), ('aisbin.ess289_iceclass', 221, 4, 'u'), ('aisbin.ess289_horsepower', 225, 18, 'u'),
        ('aisbin.ess289_vhfchan', 243, 12, 'u'), ('aisbin.ess289_lshiptype', 255, 42, 'text'), ('aisbin.ess289_tonnage', 297, 18, 'u'),
        ('aisbin.ess289_lading', 315, 2, 'u'), ('aisbin.ess289_heavyoil', 317, 2, 'u'), ('aisbin.ess289_lightoil', 319, 2, 'u'),
        ('aisbin.ess289_dieseloil', 321, 2, 'u'), ('aisbin.ess289_totaloil', 323, 14, 'u'), ('aisbin.ess289_persons', 337, 13, 'u'),
        ('ais.spare3', 350, 10, 'u'),
    ]),
    ('met-hydro-imo289', 8, 1, 31, 60000, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('lon', 56, 25, 'pos'), ('lat', 81, 24, 'pos'), ('ais.accuracy', 105, 1, 'u'),
        ('aisbin.mh289_day', 106, 5, 'u'), ('aisbin.mh289_hour', 111, 5, 'u'), ('aisbin.mh289_minute', 116, 6, 'u'),
        ('aisbin.mh289_wspeed', 122, 7, 'u'), ('aisbin.mh289_wgust', 129, 7, 'u'), ('aisbin.mh289_wdir', 136, 9, 'u'),
        ('aisbin.mh289_wgustdir', 145, 9, 'u'), ('aisbin.mh289_airtemp', 154, 11, 's'), ('aisbin.mh289_humidity', 165, 7, 'u'),
        ('aisbin.mh289_dewpoint', 172, 10, 's'), ('aisbin.mh289_pressure', 182, 9, 'u'), ('aisbin.mh289_pressuretend', 191, 2, 'u'),
        ('aisbin.mh289_visgreater', 193, 1, 'u'), ('aisbin.mh289_visibility', 194, 7, 'u'), ('aisbin.mh289_waterlevel', 201, 12, 's'),
        ('aisbin.mh289_leveltrend', 213, 2, 'u'), ('aisbin.mh289_cspeed', 215, 8, 'u'), ('aisbin.mh289_cdir', 223, 9, 'u'),
        ('aisbin.mh289_cspeed2', 232, 8, 'u'), ('aisbin.mh289_cdir2', 240, 9, 'u'), ('aisbin.mh289_cdepth2', 249, 5, 'u'),
        ('aisbin.mh289_cspeed3', 254, 8, 'u'), ('aisbin.mh289_cdir3', 262, 9, 'u'), ('aisbin.mh289_cdepth3', 271, 5, 'u'),
        ('aisbin.mh289_waveheight', 276, 8, 'u'), ('aisbin.mh289_waveperiod', 284, 6, 'u'), ('aisbin.mh289_wavedir', 290, 9, 'u'),
        ('aisbin.mh289_swellheight', 299, 8, 'u'), ('aisbin.mh289_swellperiod', 307, 6, 'u'), ('aisbin.mh289_swelldir', 313, 9, 'u'),
        ('aisbin.mh289_seastate', 322, 4, 'u'), ('aisbin.mh289_watertemp', 326, 10, 's'), ('aisbin.mh289_preciptype', 336, 3, 'u'),
        ('aisbin.mh289_salinity', 339, 9, 'u'), ('aisbin.mh289_ice', 348, 2, 'u'), ('ais.spare2', 350, 10, 'u'),
    ]),
    ('inland-static-voyage', 8, 200, 10, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.ist_vin', 56, 48, 'text'), ('aisbin.ist_length', 104, 13, 'u'), ('aisbin.ist_beam', 117, 10, 'u'),
        ('aisbin.ist_shiptype', 127, 14, 'u'), ('aisbin.ist_hazard', 141, 3, 'u'), ('aisbin.ist_draught', 144, 11, 'u'),
        ('aisbin.ist_loaded', 155, 2, 'u'), ('aisbin.ist_speed_q', 157, 1, 'u'), ('aisbin.ist_course_q', 158, 1, 'u'),
        ('aisbin.ist_heading_q', 159, 1, 'u'), ('ais.spare2', 160, 8, 'u'),
    ]),
    ('emma-warning', 8, 200, 23, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.emma_start_year', 56, 8, 'u'), ('aisbin.emma_start_month', 64, 4, 'u'), ('aisbin.emma_start_day', 68, 5, 'u'),
        ('aisbin.emma_end_year', 73, 8, 'u'), ('aisbin.emma_end_month', 81, 4, 'u'), ('aisbin.emma_end_day', 85, 5, 'u'),
        ('aisbin.emma_start_hour', 90, 5, 'u'), ('aisbin.emma_start_minute', 95, 6, 'u'), ('aisbin.emma_end_hour', 101, 5, 'u'),
        ('aisbin.emma_end_minute', 106, 6, 'u'), ('aisbin.emma_start_lon', 112, 28, 's'), ('aisbin.emma_start_lat', 140, 27, 's'),
        ('aisbin.emma_end_lon', 167, 28, 's'), ('aisbin.emma_end_lat', 195, 27, 's'), ('aisbin.emma_type', 222, 4, 'u'),
        ('aisbin.emma_min', 226, 9, 's'), ('aisbin.emma_max', 235, 9, 's'), ('aisbin.emma_intensity', 244, 2, 'u'),
        ('aisbin.emma_wind', 246, 4, 'u'), ('ais.spare2', 250, 6, 'u'),
    ]),
    ('water-levels', 8, 200, 24, None, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('aisbin.wl_country', 56, 12, 'text'), ('aisbin.wl_gauge1_id', 68, 11, 'u'), ('aisbin.wl_gauge1_level', 79, 14, 's'),
        ('aisbin.wl_gauge2_id', 93, 11, 'u'), ('aisbin.wl_gauge2_level', 104, 14, 's'), ('aisbin.wl_gauge3_id', 118, 11, 'u'),
        ('aisbin.wl_gauge3_level', 129, 14, 's'), ('aisbin.wl_gauge4_id', 143, 11, 'u'), ('aisbin.wl_gauge4_level', 154, 14, 's'),
    ]),
    ('signal-status', 8, 200, 40, 600000, [
        ('ais.spare', 38, 2, 'u'), ('aisbin.dac', 40, 10, 'u'), ('aisbin.fid', 50, 6, 'u'),
        ('lon', 56, 28, 'pos'), ('lat', 84, 27, 'pos'), ('aisbin.isig_form', 111, 4, 'u'),
        ('aisbin.isig_facing', 115, 9, 'u'), ('aisbin.isig_direction', 124, 3, 'u'), ('aisbin.isig_status', 127, 30, 'u'),
        ('ais.spare2', 157, 11, 'u'),
    ]),
]

PACK = "ais-binary"
DAC_AT = {6: 72, 8: 40}
FID_AT = {6: 82, 8: 50}


def sixbit_text(s, n):
    """Six-bit codes of text s, padded with @ (0) to n characters."""
    assert len(s) <= n, (s, n)
    out = []
    for ch in s.ljust(n, "@"):
        c = ord(ch)
        if 0x40 <= c <= 0x5F:
            out.append(c - 0x40)
        elif 0x20 <= c <= 0x3F:
            out.append(c)
        else:
            raise ValueError(ch)
    return out


def armor(bits):
    """bits: a string of 0 and 1. Zero bits fill the last character."""
    bits = bits + "0" * (-len(bits) % 6)
    out = []
    for i in range(0, len(bits), 6):
        v = int(bits[i:i + 6], 2)
        out.append(chr(0x30 + v) if v < 40 else chr(0x38 + v))
    return "".join(out)


def plain(x):
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    r = repr(x)
    assert "e" not in r
    return r


def layout(kind):
    for row in LAYOUTS:
        if row[0] == kind:
            return row
    raise KeyError(kind)


def build(kind, values, mmsi=244123456, repeat=0, lat=None, lon=None):
    """Pack one message of a kind. values: key -> value for the kind's fields
    (missing ints are 0, missing text is empty). Returns (payload, model)."""
    name, typ, dac, fid, div, lines = layout(kind)
    end = max(s + n for _, s, n, _ in lines)
    bits = ["0"] * end

    def put(start, n, v):
        if v < 0:
            v += 1 << n
        assert 0 <= v < (1 << n), (kind, start, n, v)
        bits[start:start + n] = format(v, "0%db" % n)

    model = {"@kind": kind}
    put(0, 6, typ)
    put(6, 2, repeat)
    put(8, 30, mmsi)
    model["ais.msg_type"] = str(typ)
    model["ais.repeat"] = str(repeat)
    model["ais.mmsi"] = str(mmsi)
    for key, s, n, codec in lines:
        if key == "aisbin.dac":
            v = dac
        elif key == "aisbin.fid":
            v = fid
        elif key == "aisbin.wmo":
            v = 1 if kind.endswith("-wmo") else 0
        elif codec == "pos":
            deg = lat if key == "lat" else lon
            v = round(deg * div)
            assert v / div == deg, (deg, div)
            put(s, n, v)
            model[key] = plain(v / div)
            continue
        else:
            v = values.get(key, "" if codec == "text" else 0)
        if codec == "text":
            codes = sixbit_text(v, n // 6)
            bits[s:s + n] = "".join(format(c, "06b") for c in codes)
            model[key] = v
        else:
            put(s, n, v)
            model[key] = str(v)
    return armor("".join(bits)), model


def chosen(kind, salt=0):
    """Values for every field of a kind: ints from a fixed pattern within each
    field's range, text from the field's name, spares 0."""
    name, typ, dac, fid, div, lines = layout(kind)
    vals = {}
    for key, s, n, codec in lines:
        if codec == "pos":
            continue
        member = key.split(".", 1)[1]
        if member.startswith("spare"):
            continue
        if codec == "text":
            word = member.split("_", 1)[-1].upper().replace("_", " ")
            vals[key] = word[:n // 6].rstrip()
        else:
            vals[key] = (s * 37 + n * 11 + salt) % (1 << n)
            if codec == "s" and vals[key] >= 1 << (n - 1):
                vals[key] -= 1 << n
    return vals


def vec(name, inp, expect=None, error=None, model=None, to=PACK, ref=""):
    v = {"name": name, "from": PACK, "to": to, "input": inp}
    if error:
        v["expect_error"] = error
    else:
        v["expect"] = expect
    if model:
        v["model"] = model
    v["source"] = ref
    return v


SRC = "built by tools/gen/ais-binary-vectors.py from values chosen there; "
POSITIONS = {   # kind -> (lat, lon) chosen so that the fraction of a minute is exact
    "clearance-time": (51.5, -1.25),
    "berthing-data": (53.375, -6.25),
    "met-hydro-imo236": (-33.75, 151.25),
    "traffic-signal": (59.5, 10.75),
    "weather-observation": (47.25, -122.5),
    "met-hydro-imo289": (60.125, 5.25),
    "signal-status": (51.875, 4.5),
}


# kind -> first bit of its longitude (25 bits) and latitude (24 bits)
NO_POSITION = {"clearance-time": (268, 293), "berthing-data": (311, 336), "traffic-signal": (186, 211),
               "weather-observation": (177, 202), "met-hydro-imo289": (56, 81)}


def unarmor(text):
    return "".join(format(ord(c) - 0x30 if ord(c) < 0x60 else ord(c) - 0x38, "06b") for c in text)


def vectors():
    out = []
    for row in LAYOUTS:
        kind, typ, dac, fid = row[:4]
        lat, lon = POSITIONS.get(kind, (None, None))
        payload, model = build(kind, chosen(kind), lat=lat, lon=lon)
        out.append(vec(kind + "-roundtrip", payload, payload, model=model,
                       ref=SRC + "a type %d message, DAC %d, FI %d, every field set from a fixed pattern "
                           "within its range, text fields from the field's name, spare bits 0" % (typ, dac, fid)))
    # spare bits carry
    vals = chosen("inland-static-voyage")
    vals["ais.spare"] = 3
    vals["ais.spare2"] = 0xA5
    p, m = build("inland-static-voyage", vals)
    out.append(vec("inland-static-voyage-spare-bits-carry", p, p, model=m,
                   ref=SRC + "the inland static and voyage message with its two spare ranges non-zero; "
                       "they are mapped, so they come back"))
    # edges: largest values, negative two's complement, full-length text
    vals = chosen("emma-warning")
    vals.update({"aisbin.emma_min": -256, "aisbin.emma_max": 255,
                 "aisbin.emma_start_lon": -(1 << 27), "aisbin.emma_start_lat": (1 << 26) - 1})
    p, m = build("emma-warning", vals)
    out.append(vec("emma-warning-signed-edges-roundtrip", p, p, model=m,
                   ref=SRC + "the EMMA warning with the smallest and largest signed minimum and maximum "
                       "values and the extremes of the start longitude and latitude fields"))
    vals = chosen("fairway-closed")
    vals["aisbin.fwc_reason"] = "ICE ON THE FAIRWAY 1"
    vals["aisbin.fwc_closefrom"] = ""
    p, m = build("fairway-closed", vals)
    out.append(vec("fairway-closed-full-and-empty-text", p, p, model=m,
                   ref=SRC + "a 20-character reason, which fills its field, and an empty location, all @"))
    # conversions
    p, m = build("met-hydro-imo289", chosen("met-hydro-imo289"), mmsi=2573456, lat=60.125, lon=5.25)
    out.append(vec("met-hydro-imo289-to-geojson", p,
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[5.25,60.125]},"properties":{},"id":"2573456"}',
                   to="geojson", model={"@kind": "met-hydro-imo289", "lat": "60.125", "lon": "5.25"},
                   ref=SRC + "a meteorological station report at 60.125 N 5.25 E: 3607500 and 315000 "
                       "thousandths of a minute over 60000; the MMSI 2573456 gives the id (model/ais.def "
                       "derives uid from ais.mmsi)"))
    p, m = build("signal-status", chosen("signal-status"), lat=51.875, lon=4.5)
    out.append(vec("signal-status-to-geojson", p,
                   '{"type":"Feature","geometry":{"type":"Point","coordinates":[4.5,51.875]},"properties":{},"id":"244123456"}',
                   to="geojson", model={"@kind": "signal-status", "lat": "51.875", "lon": "4.5"},
                   ref=SRC + "an inland signal status at 51.875 N 4.5 E, in ten-thousandths of a minute "
                       "(31125000 and 2700000 over 600000)"))
    p, m = build("inland-persons-on-board", chosen("inland-persons-on-board"))
    out.append(vec("no-position-to-geojson", p,
                   '{"type":"Feature","geometry":null,"properties":{},"id":"244123456"}', to="geojson",
                   ref=SRC + "an inland persons-on-board message, which has no position: geometry null, "
                       "the id from the MMSI"))
    # errors
    bits_env = format(8, "06b") + "00" + format(244123456, "030b") + "00" + format(1, "010b") + format(26, "06b")
    out.append(vec("environmental-fi-26-is-no-kind", armor(bits_env + "0" * 112), error="no-kind",
                   ref=SRC + "a type 8 message with DAC 1 and FI 26 (environmental, whose sensor reports "
                       "repeat to the end of the message): no kind selects it"))
    bits_t1 = format(1, "06b") + "0" * 162
    out.append(vec("type1-is-no-kind", armor(bits_t1), error="no-kind",
                   ref=SRC + "a 168-bit message of type 1, which pack ais reads"))
    p, _ = build("met-hydro-imo289", chosen("met-hydro-imo289"), lat=60.125, lon=5.25)
    out.append(vec("met-hydro-imo289-one-character-short", p[:-1], error="malformed-wire",
                   ref=SRC + "the meteorological report less its last character: 354 bits, the kind maps 360"))
    out.append(vec("bad-armor-character", p[:10] + "X" + p[11:], error="malformed-wire",
                   ref=SRC + "the same report with character 11 replaced by X (0x58), which stands for no six bits"))
    out.append(vec("type6-dac-235-fi-11-is-no-kind", armor(_aton_bits(fid=11)), error="no-kind",
                   ref=SRC + "an AtoN monitoring layout sent with FI 11: DAC 235 has no kind for it"))
    # no position: the code the source's tables state, and the one its unit implies for 181 and 91 degrees
    for kind in sorted(NO_POSITION):
        base, _ = build(kind, chosen(kind), lat=10.25, lon=20.5)
        bits = unarmor(base)
        (lon_at, lat_at) = NO_POSITION[kind]
        for tag, lon, lat in (("source-code", 181000, 91000), ("unit-value", 10860000, 5460000)):
            b = bits[:lon_at] + format(lon, "025b") + bits[lon_at + 25:]
            b = b[:lat_at] + format(lat, "024b") + b[lat_at + 24:]
            p = armor(b)
            name = "%s-no-position-%s" % (kind, tag)
            ref = SRC + ("raw %d and %d: not available as the tables state it" if lon == 181000 else
                         "raw %d and %d: 181 and 91 degrees in the unit of 0.001 minute") % (lon, lat)
            out.append(vec(name, p, p, model={"@kind": kind, "aisbin.pos_lon_raw": str(lon), "aisbin.pos_lat_raw": str(lat)},
                           ref=ref + "; the message comes back as it was"))
            out.append(vec(name + "-to-geojson", p,
                           '{"type":"Feature","geometry":null,"properties":{},"id":"244123456"}', to="geojson",
                           ref=ref + "; no position, so geometry null"))
    return out


def _aton_bits(fid):
    b = format(6, "06b") + "00" + format(992351000, "030b") + "00" + format(2310001, "030b") + "00"
    b += format(235, "010b") + format(fid, "06b") + "0" * 48
    return b


def build_files(out):
    vecs = vectors()
    assert len({v["name"] for v in vecs}) == len(vecs)
    d = "packs/%s/vectors" % PACK
    keep = set()
    for i, v in enumerate(vecs, 1):
        name = "%02d-%s.json" % (i, v["name"])
        out.write(d + "/" + name, json.dumps(v, indent=2, ensure_ascii=False) + "\n")
        keep.add(name)
    for old in out.listdir(d):
        if old.endswith(".json") and old not in keep:
            out.remove(d + "/" + old)
    return {PACK: len(vecs)}


def main(argv=None):
    return genio.vector_main("ais-binary-vectors.py", __doc__, build_files, argv)


if __name__ == "__main__":
    sys.exit(main())
