# Provenance: mpegts-packet pack

Read on 2026-11-21. No source file is copied into this tree.

| Source | Where | SHA-256 |
|---|---|---|
| FFmpeg n7.1 (commit b08d7969c550a804a59511c7b83f2dd8cc0499b8), libavformat/mpegts.c | https://github.com/FFmpeg/FFmpeg/blob/b08d7969c550a804a59511c7b83f2dd8cc0499b8/libavformat/mpegts.c | `da1f2f17590ccb7e497060073005cf9746039684e876dd0444be22e21aa7f0a6` |
| FFmpeg n7.1, libavformat/mpegts.h | https://github.com/FFmpeg/FFmpeg/blob/b08d7969c550a804a59511c7b83f2dd8cc0499b8/libavformat/mpegts.h | `d5a8e86937bddc40e08b33142e55021d7062a3bb5ff5e48be74072b710dad972` |
| FFmpeg n7.1, COPYING.LGPLv2.1 | https://github.com/FFmpeg/FFmpeg/blob/b08d7969c550a804a59511c7b83f2dd8cc0499b8/COPYING.LGPLv2.1 | `b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe` |
| GStreamer 1.26.9 (commit f313fae193089408e278c0dd3450145e5a12307b), gst-plugins-bad/gst/mpegtsdemux/mpegtspacketizer.c | https://github.com/GStreamer/gstreamer/blob/f313fae193089408e278c0dd3450145e5a12307b/subprojects/gst-plugins-bad/gst/mpegtsdemux/mpegtspacketizer.c | `7a85ecd4526f982ad37c6ad30ed471cc3566b475268d8a3752b09d9ba3a3a2d5` |

The sign of the splice countdown is not stated by the sources above (GStreamer prints the octet unsigned). Checked
2026-11-24, after the pack was written: TSDuck v3.40-4165, src/libtsduck/dtv/transport/tsTSPacket.h at
c158e88648fe8342d8066f551fe7751857512c9e (BSD-2-Clause, sha256 `4db44ed8cd02e3d387da4ced3ee9db604a26fd8a66d6a7cc9c7dae3402593253`) returns it as int8_t
(getSpliceCountdown); Wireshark de1eec95 epan/dissectors/packet-mp2t.c shows it unsigned (FT_UINT8). ISO/IEC 13818-1
was not read. The pack reads it signed, as TSDuck does.

## Licence

The transport stream is specified in ISO/IEC 13818-1 (a paid standard), which this project did not read.
The layout is restated from two open implementations: FFmpeg's demuxer ("Copyright (c) 2002-2003 Fabrice
Bellard", GNU Lesser General Public License, version 2.1 or later) and GStreamer's packetizer ("Copyright (C)
2007, 2008 Alessandro Decina, Zaheer Merali", GNU Library General Public License, version 2 or later). Under
rule 17 of this project a layout restated from code, with no code copied, is Apache-2.0: the pack keeps the
default label, and the sources are named here.

This pack restates the layouts (field order, sizes, codes) in its own words; no text, figure, table or
code of the sources is copied. The vectors are packets built by `tools/gen/media-vectors.py` from values
chosen there; their expected bytes are derived there, without an engine.
