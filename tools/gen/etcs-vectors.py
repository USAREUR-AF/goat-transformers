#!/usr/bin/env python3
"""Hand-derived vectors of the etcs-balise-telegram and etcs-radio-track-to-train packs.

Every message is built field by field, most significant bit first, from the variable lengths and
packet layouts of SUBSET-026 issue 3.6.0: chapter 8 (the 50-bit balise telegram header, the radio
message header NID_MESSAGE 8, L_MESSAGE 10, T_TRAIN 32, M_ACK 1, NID_LRBG 24, messages 3, 24 and
33) and chapter 7 (packets 0, 5, 12, 15, 21, 27, 41, 44, 255). L_PACKET is the bit length of the
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
    # ---- telegram 2: packet 12 (one section with a timer), 27, 41 (NTC), 44 (national), an undescribed packet 3
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
    t.extend(packet(3, 1, Bits().put(6, 0b101101)))
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
                        P % 4 + "@kind": "other", P % 4 + "etcs.nid_packet": 3, P % 4 + "etcs.other_packet_bits.#": 6,
                        P % 5 + "@kind": "p255"})
    files.append(("etcs-balise-telegram", "02-ma-ssp-level-national.json", t.hex(), m(model),
                  "packets 12 (T_EMA 1023), 27 with two category speeds, 41 to an NTC, 44 for NID_XUSER 102, "
                  "packet 3 kept as bits, 255"))
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
