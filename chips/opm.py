from __future__ import annotations

from chips.opn import CARRIERS, clamp, signed_dt_to_opn

# YM2151 channel mapping: A=0 ... H=7
OPM_CH = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6, "H": 7}
# y コマンドのタグ → YM2151 のオペレーターレジスタ(YM2608 のタグと役割が近いものを割り当てる)
OPM_Y_SLOT_REGS = {"DM": 0x40, "TL": 0x60, "KA": 0x80, "DR": 0xA0, "SR": 0xC0, "SL": 0xE0}
OPM_SLOT = (0, 16, 8, 24)  # base + channel for each operator
OPM_NOTE_CODE = (14, 0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13)  # C, C#, D, ... B → KCのノートコード(Cは1つ下のオクターブ側)

def write_opm(vgm, chip: int, reg: int, value: int) -> None:
    vgm.write_ym2151(chip, reg, value)


def apply_voice_opm(vgm, chip: int, part: str, voice_id: int, volume: int, voices, pan: int, vol_mode: str, base_tl, carrier_idx, ops=0xF, amon_override=None) -> None:
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
    for index, base in enumerate(OPM_SLOT):
        if index >= len(raw_ops):
            break
        ar, dr, sr, rr, sl, tl, ks, ml, dt, dt2, amon = raw_ops[index]
        if amon_override is not None and index < len(amon_override) and amon_override[index] is not None:
            amon = amon_override[index]  # HM で指定された値を優先(None なら音色のAMONに従う)
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
    # KC / KF(detune は KF の1単位=半音の1/64 として扱う)
    total = max(0, note) * 64 + detune
    semitone, kf = divmod(total, 64)
    block, name = divmod(semitone, 12)
    octave = block - 1 if name == 0 else block
    octave = clamp(octave, 0, 7)
    write_opm(vgm, chip, 0x28 + ch, (octave << 4) | OPM_NOTE_CODE[name])
    write_opm(vgm, chip, 0x30 + ch, kf << 2)
    if not legato:
        write_opm(vgm, chip, 0x08, 0x78 | ch)  # all slots on


def key_off_opm(vgm, chip: int, part: str) -> None:
    if part not in OPM_CH:
        return
    write_opm(vgm, chip, 0x08, OPM_CH[part])  # key off
