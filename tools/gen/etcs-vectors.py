#!/usr/bin/env python3
"""Hand-derived vectors of the etcs-balise-telegram and etcs-radio-track-to-train packs.

Every message is built field by field, most significant bit first, from the variable lengths and
packet layouts of SUBSET-026 issue 3.6.0: chapter 8 (the 50-bit balise telegram header, the radio
message header NID_MESSAGE 8, L_MESSAGE 10, T_TRAIN 32, M_ACK 1, NID_LRBG 24, messages 3, 24 and
33) and chapter 7 (packets 0, 5, 12, 15, 21, 27, 41, 44, 255 and, in the later vectors, more track-to-train
packets, the train-to-track messages and packets 0, 1, 2, 9, 11). L_PACKET is the bit length of the
whole packet and L_MESSAGE the byte length of the whole radio message with its padding; both are
counted here from the bits written. A telegram ends after packet 255, padded with zero bits to a
whole byte (the pack's message convention). No engine is imported.

    python3 -I tools/gen/etcs-vectors.py [--check] [<checkout>]
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import genio  # noqa: E402

REF = "SUBSET-026 3.6.0 chapters 7 and 8; bits written by tools/gen/etcs-vectors.py"


class Bits:
    def __init__(self):
        self.b = []

    def put(self, n, v):
        if v < 0:
            v &= (1 << n) - 1
        assert 0 <= v < (1 << n), (n, v)
        self.b += [(v >> (n - 1 - i)) & 1 for i in range(n)]
        return self

    def extend(self, other):
        self.b += other.b
        return self

    def pad(self):
        self.b += [0] * (-len(self.b) % 8)
        return self

    def hex(self):
        return bytes(int("".join(map(str, self.b[i:i + 8])), 2) for i in range(0, len(self.b), 8)).hex()


def packet(nid, qdir, body):
    """NID_PACKET, Q_DIR, L_PACKET (bits of the whole packet) and the body."""
    p = Bits().put(8, nid).put(2, qdir).put(13, 23 + len(body.b))
    return p.extend(body)


def m(model):
    return {k: str(v) for k, v in model.items()}



def tpacket(nid, body):
    """A train-to-track packet: NID_PACKET, L_PACKET (bits of the whole packet), the body; no Q_DIR."""
    return Bits().put(8, nid).put(13, 21 + len(body.b)).extend(body)


def more(files):
    hdr = [(1, 1), (7, 32), (1, 0), (3, 1), (3, 1), (2, 0), (8, 18), (10, 253), (14, 4321), (1, 0)]
    hm = {"etcs.q_updown": 1, "etcs.m_version": 32, "etcs.q_media": 0, "etcs.n_pig": 1, "etcs.n_total": 1,
          "etcs.m_dup": 0, "etcs.m_mcount": 18, "etcs.nid_c": 253, "etcs.nid_bg": 4321, "etcs.q_link": 0}
    t = Bits()
    for n, v in hdr:
        t.put(n, v)
    # packet 3, national values with Q_NVKINT = 0
    p3 = Bits().put(2, 1).put(15, 100).put(10, 253).put(5, 0)
    for n, v in [(7, 6), (7, 8), (7, 6), (7, 20), (7, 16), (7, 8), (15, 2), (1, 1), (1, 0), (1, 1), (1, 0), (1, 0),
                 (7, 6), (7, 6), (15, 200), (8, 60), (15, 50), (2, 1), (8, 30), (1, 0), (15, 200), (1, 0),
                 (6, 10), (6, 20), (6, 30), (6, 12), (5, 0), (4, 9), (1, 0)]:
        p3.put(n, v)
    t.extend(packet(3, 1, p3))
    t.extend(packet(6, 1, Bits().put(1, 1).put(6, 4).put(10, 253).put(8, 30)))          # T_VBC after NID_C
    p68 = Bits().put(2, 1).put(1, 0).put(15, 300).put(15, 40).put(4, 3).put(5, 1).put(15, 700).put(15, 20).put(4, 5)
    t.extend(packet(68, 1, p68))
    p70 = Bits().put(2, 1).put(1, 0).put(15, 50).put(2, 2).put(4, 3).put(10, 253).put(5, 1).put(15, 90).put(2, 0).put(8, 7)
    t.extend(packet(70, 1, p70))
    p72 = Bits().put(2, 1).put(2, 0).put(1, 0).put(15, 10).put(4, 0).put(3, 1).put(8, 20).put(15, 500).put(10, 60).put(4, 0) \
        .put(3, 2).put(2, 1).put(1, 1).put(1, 1).put(8, 77).put(10, 253).put(14, 99).put(8, 4)
    for ch in b"STOP":
        p72.put(8, ch)
    t.extend(packet(72, 1, p72))
    t.extend(packet(88, 1, Bits().put(2, 1).put(8, 5).put(15, 400).put(15, 30).put(1, 1).put(7, 4).put(1, 1).put(15, 25)))
    t.extend(packet(136, 1, Bits().put(1, 1).put(10, 254).put(14, 77)))
    t.extend(packet(254, 1, Bits()))
    t.put(8, 255).pad()
    P = "etcs.packets[%d]."
    model = dict(hm, **{"etcs.packets.#": 9,
                        P % 0 + "@kind": "p3", P % 0 + "etcs.nid_packet": 3, P % 0 + "etcs.p3_d_validnv": 100, P % 0 + "etcs.p3_areas.#": 0,
                        P % 0 + "etcs.p3_m_nvebcl": 9, P % 0 + "etcs.p3_q_nvkint": 0,
                        P % 1 + "@kind": "p6", P % 1 + "etcs.p6_q_vbco": 1, P % 1 + "etcs.p6_t_vbc": 30,
                        P % 2 + "@kind": "p68", P % 2 + "etcs.p68_q_trackinit": 0, P % 2 + "etcs.p68_d_trackcond": 300,
                        P % 2 + "etcs.p68_items.#": 1, P % 2 + "etcs.p68_items[0].etcs.p68_items_m_trackcond": 5,
                        P % 3 + "@kind": "p70", P % 3 + "etcs.p70_q_suitability": 2, P % 3 + "etcs.p70_m_voltage": 3,
                        P % 3 + "etcs.p70_nid_ctraction": 253, P % 3 + "etcs.p70_items[0].etcs.p70_items_m_linegauge": 7,
                        P % 4 + "@kind": "p72", P % 4 + "etcs.p72_nid_ntc": 20, P % 4 + "etcs.p72_end_m_leveltextdisplay": 2,
                        P % 4 + "etcs.p72_nid_textmessage": 77, P % 4 + "etcs.p72_x_text.#": 4,
                        P % 4 + "etcs.p72_x_text[0].etcs.p72_x_text_byte": 83,
                        P % 5 + "@kind": "p88", P % 5 + "etcs.p88_v_lx": 4, P % 5 + "etcs.p88_l_stoplx": 25,
                        P % 6 + "@kind": "p136", P % 6 + "etcs.p136_nid_c": 254, P % 6 + "etcs.p136_nid_bg": 77,
                        P % 7 + "@kind": "p254", P % 8 + "@kind": "p255"})
    files.append(("etcs-balise-telegram", "03-national-text-conditions.json", t.hex(), m(model),
                  "packets 3 (Q_NVKINT 0), 6 (T_VBC after NID_C), 68, 70 (traction system), 72 (text STOP, report), "
                  "88 (stop at the crossing), 136, 254, 255"))

    def radio(nid, tail):
        body = Bits().put(32, 123456).put(1, 0).put(10, 253).put(14, 4321).extend(tail)
        total = (18 + len(body.b) + 7) // 8
        return Bits().put(8, nid).put(10, total).extend(body).pad()
    rm = {"etcs.t_train": 123456, "etcs.m_ack": 0, "etcs.lrbg_nid_c": 253, "etcs.lrbg_nid_bg": 4321}
    msg = radio(15, Bits().put(4, 3).put(2, 1).put(16, -40).put(2, 1).put(15, 600))
    files.append(("etcs-radio-track-to-train", "05-conditional-emergency-stop.json", msg.hex(),
                  m(dict(rm, **{"@kind": "conditional_emergency_stop", "etcs.m15_nid_em": 3, "etcs.m15_d_ref": -40,
                                "etcs.m15_d_emergencystop": 600})), "message 15, D_REF -40"))
    p12 = Bits().put(2, 1).put(7, 16).put(7, 0).put(10, 1023).put(5, 0).put(15, 900).put(1, 0).put(1, 0).put(1, 0).put(1, 0)
    msg = radio(37, packet(136, 1, Bits().put(1, 0).put(14, 88)).extend(packet(12, 1, p12)))
    files.append(("etcs-radio-track-to-train", "06-infill-ma.json", msg.hex(),
                  m(dict(rm, **{"@kind": "infill_ma", "etcs.optional_packets.#": 2,
                                "etcs.optional_packets[0].@kind": "p136", "etcs.optional_packets[0].etcs.nid_packet": 136,
                                "etcs.optional_packets[0].etcs.p136_nid_bg": 88,
                                "etcs.optional_packets[1].@kind": "p12", "etcs.optional_packets[1].etcs.p12_l_endsection": 900})),
                  "message 37: packet 136 then packet 12, read as the packet list"))
    msg = radio(45, Bits().put(1, 1))
    files.append(("etcs-radio-track-to-train", "07-coordinate-system.json", msg.hex(),
                  m(dict(rm, **{"@kind": "coordinate_system_assignment", "etcs.m45_q_orientation": 1})), "message 45"))

    def tradio(nid, tail):
        body = Bits().put(32, 98765).put(24, 0x123456).extend(tail)
        total = (18 + len(body.b) + 7) // 8
        return Bits().put(8, nid).put(10, total).extend(body).pad()
    tm = {"etcs.train_t_train": 98765, "etcs.nid_engine": 0x123456}
    def pos(two=False, qlen=0):
        b = Bits().put(2, 1).put(10, 253).put(14, 4321)
        if two:
            b.put(10, 253).put(14, 4320)
        b.put(15, 120).put(2, 1).put(2, 1).put(15, 5).put(15, 6).put(2, qlen)
        if qlen in (1, 2):
            b.put(15, 400)
        return b.put(7, 16).put(2, 1).put(4, 0).put(3, 3)
    p11 = Bits().put(4, 2).put(15, 1).put(12, 400).put(7, 32).put(8, 1).put(7, 10).put(2, 0).put(10, 24).put(5, 1).put(4, 1).put(10, 253) \
        .put(5, 1).put(8, 7)
    msg = tradio(129, tpacket(0, pos()).extend(tpacket(11, p11)))
    T = "etcs.train_packets[%d]."
    files.append(("etcs-radio-train-to-track", "01-validated-train-data.json", msg.hex(),
                  m(dict(tm, **{"@kind": "validated_train_data", "etcs.train_packets.#": 2,
                                T % 0 + "@kind": "tp0", T % 0 + "etcs.train_nid_packet": 0, T % 0 + "etcs.tp0_d_lrbg": 120, T % 0 + "etcs.tp0_v_train": 16,
                                T % 0 + "etcs.tp0_m_level": 3,
                                T % 1 + "@kind": "tp11", T % 1 + "etcs.tp11_l_train": 400, T % 1 + "etcs.tp11_n_axle": 24,
                                T % 1 + "etcs.tp11_tractions.#": 1, T % 1 + "etcs.tp11_tractions[0].etcs.tp11_tractions_nid_ctraction": 253,
                                T % 1 + "etcs.tp11_ntcs[0].etcs.tp11_ntcs_nid_ntc": 7})),
                  "message 129: packet 0 and packet 11"))
    msg = tradio(132, Bits().put(5, 0b00011).extend(tpacket(1, pos(True))).extend(tpacket(9, Bits().put(10, 253).put(14, 500))))
    files.append(("etcs-radio-train-to-track", "02-ma-request.json", msg.hex(),
                  m(dict(tm, **{"@kind": "ma_request", "etcs.tm132_q_marqstreason": 3, "etcs.train_packets.#": 2,
                                T % 0 + "@kind": "tp1", T % 0 + "etcs.tp1_prvlrbg_nid_bg": 4320,
                                T % 1 + "@kind": "tp9", T % 1 + "etcs.tp9_ltrbg_nid_bg": 500})),
                  "message 132: Q_MARQSTREASON, packet 1, packet 9"))
    msg = tradio(136, tpacket(0, pos(qlen=1)))
    files.append(("etcs-radio-train-to-track", "03-position-report.json", msg.hex(),
                  m(dict(tm, **{"@kind": "train_position_report", T % 0 + "@kind": "tp0", T % 0 + "etcs.tp0_q_length": 1,
                                T % 0 + "etcs.tp0_l_trainint": 400})), "message 136, train integrity confirmed with L_TRAININT"))
    msg = tradio(146, Bits().put(32, 123456))
    files.append(("etcs-radio-train-to-track", "04-acknowledgement.json", msg.hex(),
                  m(dict(tm, **{"@kind": "acknowledgement", "etcs.tm146_t_train": 123456, "etcs.train_packets.#": 0})), "message 146"))
    msg = tradio(155, Bits())
    files.append(("etcs-radio-train-to-track", "05-session-initiation.json", msg.hex(),
                  m(dict(tm, **{"@kind": "session_initiation", "etcs.train_packets.#": 0})), "message 155, header only"))
    msg = tradio(159, tpacket(2, Bits().put(7, 33).put(5, 1).put(7, 32)))
    files.append(("etcs-radio-train-to-track", "06-session-established.json", msg.hex(),
                  m(dict(tm, **{"@kind": "session_established", T % 0 + "@kind": "tp2", T % 0 + "etcs.tp2_m_version": 33,
                                T % 0 + "etcs.tp2_versions[0].etcs.tp2_versions_m_version": 32})), "message 159 with packet 2"))


def build(out):
    files = []
    # ---- telegram 1: header, packet 0, packet 5 (one linked group, no iteration), packet 21, packet 255
    t = Bits()
    hdr = [(1, 1), (7, 32), (1, 0), (3, 0), (3, 1), (2, 0), (8, 17), (10, 253), (14, 4321), (1, 1)]
    for n, v in hdr:
        t.put(n, v)
    hm = {"etcs.q_updown": 1, "etcs.m_version": 32, "etcs.q_media": 0, "etcs.n_pig": 0, "etcs.n_total": 1,
          "etcs.m_dup": 0, "etcs.m_mcount": 17, "etcs.nid_c": 253, "etcs.nid_bg": 4321, "etcs.q_link": 1}
    t.put(8, 0).put(6, 9)                                     # packet 0, NID_VBCMK 9
    p5 = Bits().put(2, 1).put(15, 1500).put(1, 0).put(14, 4322).put(1, 0).put(2, 1).put(6, 5).put(5, 0)
    t.extend(packet(5, 1, p5))
    p21 = Bits().put(2, 1).put(15, 0).put(1, 1).put(8, 12).put(5, 1).put(15, 800).put(1, 0).put(8, 255)
    t.extend(packet(21, 1, p21))
    t.put(8, 255).pad()
    model = dict(hm, **{"etcs.packets.#": 4,
                        "etcs.packets[0].@kind": "p0", "etcs.packets[0].etcs.p0_nid_vbcmk": 9,
                        "etcs.packets[1].@kind": "p5", "etcs.packets[1].etcs.q_dir": 1,
                        "etcs.packets[1].etcs.p5_q_scale": 1, "etcs.packets[1].etcs.p5_d_link": 1500,
                        "etcs.packets[1].etcs.p5_nid_bg": 4322, "etcs.packets[1].etcs.p5_q_linkreaction": 1,
                        "etcs.packets[1].etcs.p5_q_locacc": 5, "etcs.packets[1].etcs.p5_links.#": 0,
                        "etcs.packets[2].@kind": "p21", "etcs.packets[2].etcs.p21_q_gdir": 1,
                        "etcs.packets[2].etcs.p21_g_a": 12, "etcs.packets[2].etcs.p21_changes.#": 1,
                        "etcs.packets[2].etcs.p21_changes[0].etcs.p21_change_d_gradient": 800,
                        "etcs.packets[2].etcs.p21_changes[0].etcs.p21_change_g_a": 255,
                        "etcs.packets[3].@kind": "p255"})
    files.append(("etcs-balise-telegram", "01-linking-gradient.json", t.hex(), m(model),
                  "header, packet 0, packet 5 without further links, packet 21 ending with G_A 255, packet 255"))
    # ---- telegram 2: packet 12 (one section with a timer), 27, 41 (NTC), 44 (national), an unassigned packet 200
    t = Bits()
    for n, v in hdr:
        t.put(n, v)
    p12 = Bits().put(2, 1).put(7, 16).put(7, 0).put(10, 1023).put(5, 1)
    p12.put(15, 400).put(1, 1).put(10, 60).put(15, 350)      # section 1 with its timer
    p12.put(15, 900).put(1, 0)                                # end section, no timer
    p12.put(1, 0)                                             # Q_ENDTIMER
    p12.put(1, 1).put(15, 50).put(7, 3)                       # danger point
    p12.put(1, 0)                                             # Q_OVERLAP
    t.extend(packet(12, 1, p12))
    p27 = Bits().put(2, 1).put(15, 0).put(7, 20).put(1, 1).put(5, 2)
    p27.put(2, 0).put(4, 3).put(7, 24)                        # Q_DIFF 0: NC_CDDIFF 3
    p27.put(2, 1).put(4, 7).put(7, 18)                        # Q_DIFF 1: NC_DIFF 7
    p27.put(5, 1).put(15, 2000).put(7, 16).put(1, 0).put(5, 0)
    t.extend(packet(27, 1, p27))
    p41 = Bits().put(2, 1).put(15, 32767).put(3, 1).put(8, 20).put(15, 100).put(5, 1).put(3, 2).put(15, 100)
    t.extend(packet(41, 2, p41))
    p44 = Bits().put(9, 102).put(8, 5).put(5, 0b10110)
    t.extend(packet(44, 1, p44))
    t.extend(packet(200, 1, Bits().put(6, 0b101101)))   # NID_PACKET 200 is assigned to no packet
    t.put(8, 255).pad()
    P = "etcs.packets[%d]."
    model = dict(hm, **{"etcs.packets.#": 6,
                        P % 0 + "@kind": "p12", P % 0 + "etcs.p12_v_main": 16, P % 0 + "etcs.p12_t_ema": 1023,
                        P % 0 + "etcs.p12_sections.#": 1,
                        P % 0 + "etcs.p12_sections[0].etcs.p12_l_section": 400,
                        P % 0 + "etcs.p12_sections[0].etcs.p12_t_sectiontimer": 60,
                        P % 0 + "etcs.p12_l_endsection": 900, P % 0 + "etcs.p12_d_dp": 50,
                        P % 0 + "etcs.p12_v_releasedp": 3,
                        P % 1 + "@kind": "p27", P % 1 + "etcs.p27_v_static": 20, P % 1 + "etcs.p27_diffs.#": 2,
                        P % 1 + "etcs.p27_diffs[0].etcs.p27_diff_nc_cddiff": 3,
                        P % 1 + "etcs.p27_diffs[1].etcs.p27_diff_nc_diff": 7,
                        P % 1 + "etcs.p27_elements.#": 1,
                        P % 1 + "etcs.p27_elements[0].etcs.p27_elem_d_static": 2000,
                        P % 2 + "@kind": "p41", P % 2 + "etcs.q_dir": 2, P % 2 + "etcs.p41_d_leveltr": 32767,
                        P % 2 + "etcs.p41_m_leveltr": 1, P % 2 + "etcs.p41_nid_ntc": 20,
                        P % 2 + "etcs.p41_levels.#": 1, P % 2 + "etcs.p41_levels[0].etcs.p41_level_m_leveltr": 2,
                        P % 3 + "@kind": "p44", P % 3 + "etcs.p44_nid_xuser": 102, P % 3 + "etcs.p44_nid_ntc": 5,
                        P % 3 + "etcs.p44_data.#": 5,
                        P % 4 + "@kind": "other", P % 4 + "etcs.nid_packet": 200, P % 4 + "etcs.other_packet_bits.#": 6,
                        P % 5 + "@kind": "p255"})
    files.append(("etcs-balise-telegram", "02-ma-ssp-level-national.json", t.hex(), m(model),
                  "packets 12 (T_EMA 1023), 27 with two category speeds, 41 to an NTC, 44 for NID_XUSER 102, "
                  "packet 200 (not assigned) kept as bits, 255"))
    # ---- radio message 3 with packet 15 and optional packet 21
    def radio(nid, tail, opt):
        body = Bits().put(32, 123456).put(1, 1).put(10, 253).put(14, 4321).extend(tail).extend(opt)
        total = (8 + 10 + len(body.b) + 7) // 8
        msg = Bits().put(8, nid).put(10, total).extend(body).pad()
        assert len(msg.b) == 8 * total
        return msg
    p15 = Bits().put(2, 1).put(7, 0).put(10, 1023).put(5, 0).put(15, 1200).put(1, 0).put(1, 0).put(1, 0).put(1, 1)
    p15.put(15, 100).put(10, 30).put(15, 200).put(7, 6)
    p15p = packet(15, 1, p15)
    opt21 = packet(21, 1, Bits().put(2, 1).put(15, 0).put(1, 0).put(8, 5).put(5, 0))
    rm = {"etcs.t_train": 123456, "etcs.m_ack": 1, "etcs.lrbg_nid_c": 253, "etcs.lrbg_nid_bg": 4321}
    msg = radio(3, p15p, opt21)
    files.append(("etcs-radio-track-to-train", "01-movement-authority.json", msg.hex(),
                  m(dict(rm, **{"@kind": "movement_authority", "etcs.p15_l_endsection": 1200, "etcs.p15_t_ema": 1023,
                                "etcs.p15_d_startol": 100, "etcs.p15_t_ol": 30, "etcs.p15_d_ol": 200,
                                "etcs.p15_v_releaseol": 6, "etcs.optional_packets.#": 1,
                                "etcs.optional_packets[0].@kind": "p21", "etcs.optional_packets[0].etcs.p21_g_a": 5})),
                  "message 3: packet 15 with an overlap, optional packet 21"))
    opt41 = packet(41, 1, Bits().put(2, 2).put(15, 300).put(3, 3).put(15, 50).put(5, 0))
    msg = radio(24, Bits(), opt41)
    files.append(("etcs-radio-track-to-train", "02-general-message.json", msg.hex(),
                  m(dict(rm, **{"@kind": "general_message", "etcs.optional_packets.#": 1,
                                "etcs.optional_packets[0].@kind": "p41",
                                "etcs.optional_packets[0].etcs.p41_m_leveltr": 3})),
                  "message 24 with optional packet 41 (level 2)"))
    msg = radio(33, Bits().put(2, 1).put(16, -250).extend(p15p), Bits())
    files.append(("etcs-radio-track-to-train", "03-ma-shifted-location.json", msg.hex(),
                  m(dict(rm, **{"@kind": "ma_shifted_location", "etcs.m33_q_scale": 1, "etcs.m33_d_ref": -250,
                                "etcs.optional_packets.#": 0})),
                  "message 33: D_REF -250 in two's complement, packet 15, no optional packet"))
    more(files)
    vecs = [(pack, name, {"name": "%s-%s" % (pack, name[:-5]), "from": pack, "to": pack, "input": h, "expect": h,
                          "model": md, "source": "constructed", "reference": REF + "; " + note})
            for pack, name, h, md, note in files]
    short = files[2][2][:-4]
    vecs.append(("etcs-radio-track-to-train", "04-length-beyond-message.json",
                 {"name": "etcs-radio-track-to-train-length-beyond-message", "from": "etcs-radio-track-to-train",
                  "to": "etcs-radio-track-to-train", "input": short, "expect_error": "malformed-wire",
                  "source": "constructed", "reference": REF + "; message 3 with its last two bytes removed: L_MESSAGE exceeds the input"}))
    for pack, name, v in vecs:
        out.write("packs/%s/vectors/%s" % (pack, name), json.dumps(v, indent=2) + "\n")
    return {"etcs": len(vecs)}


if __name__ == "__main__":
    sys.exit(genio.vector_main("etcs-vectors", __doc__.split("\n")[0], build))
