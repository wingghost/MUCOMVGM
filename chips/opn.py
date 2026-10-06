from __future__ import annotations

FM_PARTS = "ABCHIJLMN"
FM3_PARTS = "CLMN"
EXT_PARTS = "LMN"
FNUM_MAX = 2047
PORTA_HZ = 200
SAMPLE_RATE = 44100
FNUM_TABLE = [617, 653, 692, 733, 777, 823, 872, 924, 979, 1037, 1099, 1164]
SLOT_MAP = {
    "A": (0, 8, 4, 12), "B": (1, 9, 5, 13), "C": (2, 10, 6, 14),
    "H": (0, 8, 4, 12), "I": (1, 9, 5, 13), "J": (2, 10, 6, 14),
    "L": (2, 10, 6, 14), "M": (2, 10, 6, 14), "N": (2, 10, 6, 14),
}
REG_CH = {"A": 0, "B": 1, "C": 2, "H": 0, "I": 1, "J": 2, "L": 2, "M": 2, "N": 2}
KEY_CH = {"A": 0, "B": 1, "C": 2, "H": 4, "I": 5, "J": 6, "L": 2, "M": 2, "N": 2}
PORT = {"A": 0, "B": 0, "C": 0, "H": 1, "I": 1, "J": 1, "L": 0, "M": 0, "N": 0}
CARRIERS = {0: (3,), 1: (3,), 2: (3,), 3: (3,), 4: (1, 3), 5: (1, 2, 3), 6: (1, 2, 3), 7: (0, 1, 2, 3)}
PAN_LR = {0: 0x00, 1: 0x40, 2: 0x80, 3: 0xC0}
V_TL_TABLE = [42, 40, 37, 34, 32, 29, 26, 24, 21, 18, 16, 13, 10, 8, 5, 2]
Y_SLOT_REGS = {"DM": 0x30, "TL": 0x40, "KA": 0x50, "DR": 0x60, "SR": 0x70, "SL": 0x80, "SE": 0x90}
CH3_FREQ = ((0xAD, 0xA9), (0xAE, 0xAA), (0xAC, 0xA8), (0xA6, 0xA2))


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def y_port(part: str, reg: int) -> int:
    if reg == 0x28:
        return 0
    if part in "HIJ" and 0x30 <= reg <= 0xB6:
        return 1
    return PORT.get(part, 0)


def lfo22_value(enable: int, speed: int) -> int:
    return ((1 if enable else 0) << 3) | clamp(speed, 0, 7)


def signed_dt_to_opn(dt: int) -> int:
    return min(3, -dt) + 4 if dt < 0 else dt & 7


def pack_voice(fb: int, al: int, ops: list[list[int]]) -> tuple:
    slots = []
    for op in ops:
        ar, dr, sr, rr, sl, tl, ks, ml, dt = op[:9]
        slots.append((
            (clamp(signed_dt_to_opn(dt), 0, 7) << 4) | clamp(ml, 0, 15),
            clamp(tl, 0, 127),
            (clamp(ks, 0, 3) << 6) | clamp(ar, 0, 31),
            clamp(dr, 0, 31),
            clamp(sr, 0, 31),
            (clamp(sl, 0, 15) << 4) | clamp(rr, 0, 15),
        ))
    return clamp(al, 0, 7), clamp(fb, 0, 7), slots


def init_fm(vgm) -> None:
    if vgm.chip != "ym2608":
        return
    for reg, val in ((0x22, 0), (0x27, 0), (0x28, 0), (0x29, 0x80)):
        vgm.write_ym2608(0, reg, val)


def write_b4(vgm, part, pan, pms, ams) -> None:
    val = PAN_LR[clamp(pan, 0, 3)] | (clamp(ams, 0, 3) << 4) | clamp(pms, 0, 7)
    vgm.write_ym2608(PORT[part], 0xB4 + REG_CH[part], val)


def apply_voice(vgm, part, voice_id, volume, voices, pan, vol_mode, pms, ams, amon, base_tl, carrier_idx, ops=0xF) -> None:
    if voice_id not in voices:
        raise ValueError(f"音色 @{voice_id} が定義されていません")
    alg, fb, slots = voices[voice_id]
    port, ch = PORT[part], REG_CH[part]
    vgm.write_ym2608(port, 0xB0 + ch, (clamp(fb, 0, 7) << 3) | clamp(alg, 0, 7))
    write_b4(vgm, part, pan, pms, ams)
    tl_add = 127 - clamp(volume, 0, 127) if vol_mode == "V" else V_TL_TABLE[clamp(volume, 0, 15)]
    carriers = set(CARRIERS.get(clamp(alg, 0, 7), (3,))) & {i for i in range(4) if (ops >> i) & 1}
    carrier_idx.clear()
    carrier_idx.update(carriers)
    for index, slot in enumerate(SLOT_MAP[part]):
        if not (ops >> index) & 1:
            continue
        dtml, tl, ar, dr, sr, slrr = slots[index]
        out_tl = clamp(tl + tl_add, 0, 127) if index in carriers else clamp(tl, 0, 127)
        base_tl[index] = out_tl
        vgm.write_ym2608(port, 0x30 + slot, dtml & 0x7F)
        vgm.write_ym2608(port, 0x40 + slot, out_tl)
        vgm.write_ym2608(port, 0x50 + slot, ar & 0xDF)
        vgm.write_ym2608(port, 0x60 + slot, (0x80 if amon[index] else 0) | (dr & 0x1F))
        vgm.write_ym2608(port, 0x70 + slot, sr & 0x1F)
        vgm.write_ym2608(port, 0x80 + slot, slrr & 0xFF)
        vgm.write_ym2608(port, 0x90 + slot, 0)


def block_fnum(note: int, detune: int) -> tuple[int, int]:
    if note < 0:
        return 0, 0
    block, fnum = note // 12, FNUM_TABLE[note % 12] + detune
    while fnum > FNUM_MAX and block < 7:
        fnum >>= 1
        block += 1
    while fnum < FNUM_TABLE[0] and block > 0:
        fnum <<= 1
        block -= 1
    return clamp(block, 0, 7), clamp(fnum, 0, FNUM_MAX)


def scaled_pitch(note: int, detune: int) -> int:
    block, fnum = block_fnum(note, detune)
    return fnum << block


def split_pitch(scaled: int) -> tuple[int, int]:
    if scaled <= 0:
        return 0, 0
    block, fnum = 0, scaled
    while fnum > FNUM_MAX and block < 7:
        fnum >>= 1
        block += 1
    return block, min(fnum, FNUM_MAX)


def write_fnum(vgm, part, block, fnum) -> None:
    ch = REG_CH[part]
    vgm.write_ym2608(PORT[part], 0xA4 + ch, (block << 3) | ((fnum >> 8) & 7))
    vgm.write_ym2608(PORT[part], 0xA0 + ch, fnum & 0xFF)


def write_pitch(vgm, part, midi_note, detune) -> None:
    write_fnum(vgm, part, *block_fnum(midi_note, detune))


def write_ch3_slots(vgm, midi_note, extra, slot_dt, ops=0xF) -> None:
    for index, (dt, (hi, lo)) in enumerate(zip(slot_dt, CH3_FREQ)):
        if not (ops >> index) & 1:
            continue
        block, fnum = block_fnum(midi_note, extra + dt)
        vgm.write_ym2608(0, hi, (block << 3) | ((fnum >> 8) & 7))
        vgm.write_ym2608(0, lo, fnum & 0xFF)


def write_ch3_porta(vgm, start_note, end_note, extra, slot_dt, step, total, ops=0xF) -> None:
    for index, (dt, (hi, lo)) in enumerate(zip(slot_dt, CH3_FREQ)):
        if not (ops >> index) & 1:
            continue
        start = scaled_pitch(start_note, extra + dt)
        end = scaled_pitch(end_note, extra + dt)
        block, fnum = split_pitch(start + (end - start) * step // max(1, total))
        vgm.write_ym2608(0, hi, (block << 3) | ((fnum >> 8) & 7))
        vgm.write_ym2608(0, lo, fnum & 0xFF)


def key_on(vgm, part, midi_note, detune, legato=False, effect=False, slot_dt=None, ops=0xF, kon=None) -> None:
    if effect and part in FM3_PARTS:
        write_ch3_slots(vgm, midi_note, detune, slot_dt or [0, 0, 0, 0], ops)
    else:
        write_pitch(vgm, part, midi_note, detune)
    if not legato:
        if kon is None:
            vgm.write_ym2608(0, 0x28, 0xF0 | KEY_CH[part])
        else:
            kon[0] |= ops
            vgm.write_ym2608(0, 0x28, (kon[0] << 4) | KEY_CH[part])


def key_off(vgm, part, ops=0xF, kon=None) -> None:
    if kon is None:
        vgm.write_ym2608(0, 0x28, KEY_CH[part])
    else:
        kon[0] &= ~ops & 0xF
        vgm.write_ym2608(0, 0x28, (kon[0] << 4) | KEY_CH[part])


def porta_linear(note: int, detune: int) -> int:
    semi = note % 12
    block = note // 12
    fnum = FNUM_TABLE[semi] + detune
    while fnum > FNUM_MAX:
        fnum >>= 1
        block += 1
    while fnum < FNUM_TABLE[0] and block > 0:
        fnum <<= 1
        block -= 1
    return (max(0, min(7, block)) << 11) | max(0, min(FNUM_MAX, fnum))


def write_linear(vgm, part: str, linear: int, effect: bool, slot_dt) -> None:
    block, fnum = (linear >> 11) & 7, linear & FNUM_MAX
    if effect and part == "C":
        write_ch3_slots(vgm, block * 12, fnum - FNUM_TABLE[0], slot_dt)
        return
    vgm.write_ym2608(PORT[part], 0xA4 + REG_CH[part], (block << 3) | ((fnum >> 8) & 7))
    vgm.write_ym2608(PORT[part], 0xA0 + REG_CH[part], fnum & 0xFF)


def write_porta(vgm, part, start_note, end_note, detune, clocks, samples_per_clock, legato, effect, slot_dt) -> None:
    clocks = max(1, clocks)
    start = scaled_pitch(start_note, detune)
    end = scaled_pitch(end_note, detune)
    if not legato:
        key_on(vgm, part, start_note, detune, False, effect, slot_dt)
    previous = None
    for i in range(1, clocks + 1):
        block, fnum = split_pitch(start + (end - start) * i // clocks)
        if (block, fnum) != previous:
            if effect and part == "C":
                write_ch3_slots(vgm, block * 12, fnum - FNUM_TABLE[0], slot_dt)
            else:
                write_fnum(vgm, part, block, fnum)
            previous = (block, fnum)
        vgm.write_wait(max(1, samples_per_clock))
        