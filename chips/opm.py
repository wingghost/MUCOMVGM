from __future__ import annotations

from chips.opn import CARRIERS, clamp, signed_dt_to_opn

# YM2151 channel mapping: A=0 ... H=7
OPM_CH = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7}
OPM_SLOT = (0, 8, 16, 24)  # base + channel for each operator

def write_opm(vgm, chip: int, reg: int, value: int) -> None:
    vgm.write_ym2151(chip, reg, value)


def apply_voice_opm(vgm, chip: int, part: str, voice_id: int, volume: int, voices, pan: int, vol_mode: str, base_tl, carrier_idx, ops=0xF) -> None:
    if part not in OPM_CH or voice_id not in voices:
        return
    ch = OPM_CH[part]
    data = voices[voice_id]
    alg = data[0]
    fb = data[1]
    raw_ops = data[3] if len(data) > 3 else []
    # RL / FB / CON
    rl = {0: 0x00, 1: 0x40, 2: 0x80, 3: 0xC0}.get(pan, 0xC0)
    write_opm(vgm, chip, 0x20 + ch, rl | (clamp(fb, 0, 7) << 3) | clamp(alg, 0, 7))
    # volume
    tl_add = 127 - clamp(volume, 0, 127) if vol_mode == "V" else [42, 40, 37, 34, 32, 29, 26, 24, 21, 18, 16, 13, 10, 8, 5, 2][clamp(volume, 0, 15)]
    carriers = set(CARRIERS.get(clamp(alg, 0, 7), (3,)))
    carrier_idx.clear()
    carrier_idx.update(carriers)
    # 標準スロット: M1=0, M2=8, C1=16, C2=24
    for index, base in enumerate((0, 8, 16, 24)):
        if index >= len(raw_ops):
            break
        ar, dr, sr, rr, sl, tl, ks, ml, dt, dt2, amon = raw_ops[index]
        slot = ch + base
        out_tl = clamp(tl + tl_add, 0, 127) if index in carriers else clamp(tl, 0, 127)
        base_tl[index] = out_tl
        write_opm(vgm, chip, 0x40 + slot, (clamp(signed_dt_to_opn(dt), 0, 7) << 4) | clamp(ml, 0, 15))
        write_opm(vgm, chip, 0x60 + slot, out_tl)
        write_opm(vgm, chip, 0x80 + slot, (clamp(ks, 0, 3) << 6) | clamp(ar, 0, 31))
        write_opm(vgm, chip, 0xA0 + slot, (0x80 if amon else 0) | clamp(dr, 0, 31))
        write_opm(vgm, chip, 0xC0 + slot, (clamp(dt2, 0, 3) << 6) | clamp(sr, 0, 31))
        write_opm(vgm, chip, 0xE0 + slot, (clamp(sl, 0, 15) << 4) | clamp(rr, 0, 15))


def key_on_opm(vgm, chip: int, part: str, note: int, detune: int, legato: bool = False) -> None:
    if part not in OPM_CH:
        return
    ch = OPM_CH[part]
    # KC / KF
    block = note // 12
    kf = (note % 12) * 64 // 12 + (detune & 63)
    write_opm(vgm, chip, 0x28 + ch, (clamp(block, 0, 7) << 4) | (kf & 0x3F))
    if not legato:
        write_opm(vgm, chip, 0x08, 0x78 | ch)  # all slots on


def key_off_opm(vgm, chip: int, part: str) -> None:
    if part not in OPM_CH:
        return
    write_opm(vgm, chip, 0x08, OPM_CH[part])  # key off
