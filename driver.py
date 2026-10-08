from __future__ import annotations

from adpcm import delta_n, play, set_rate, stop, trim_pcm, write_rom
from chips.ay8910 import AyState, SSG_CH, SSG_PARTS, ssg_clock, tone_period
from chips.opn import (
    CARRIERS, FM3_PARTS, FM_PARTS, PORT, REG_CH, SLOT_MAP, apply_voice, init_fm, key_off, key_on, write_b4,
    scaled_pitch, split_pitch, write_ch3_porta, write_ch3_slots, write_fnum, write_pitch,
)
from mmlparser import ADPCM_PART, ALL_PARTS, MOD_PARTS, RHYTHM_PART, MusicEvent, Song, fm_reverb_volume, fine_reverb_volume, ssg_reverb_volume
from vgmwriter import DEFAULT_C, INTERNAL_WHOLE, VgmWriter, clamp, ticks_to_samples

RHYTHM_REG = (0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D)
RHYTHM_PAN = {0: 0x00, 1: 0x40, 2: 0x80, 3: 0xC0}


def flush_ssg(vgm, ay):
    for reg, value in ay.registers():
        vgm.write_ssg(reg, value)


def write_ssg_pitch(ay, part, note, detune, offset):
    block = max(0, note // 12)
    base = tone_period(ay.clock, note - block * 12, detune)
    shifted = int(round(base - offset)) >> block
    ay.channels[SSG_CH[part]].period = max(1, min(4095, shifted))


def new_mod_state():
    return {"on": False, "delay": 0, "step": 1, "depth": 0, "count": 0, "delay_left": 0, "step_left": 1, "peak_left": 0, "delta": 0, "offset": 0}


def new_env():
    return {"on": False, "al": 255, "ar": 255, "dr": 255, "sl": 255, "sr": 0, "rr": 255, "level": 0, "phase": "off"}


def env_volume(st, volume):
    return (st["level"] * (clamp(volume, 0, 15) + 1)) >> 8


def start_env(st):
    st["level"] = clamp(st["al"], 0, 255)
    st["phase"] = "decay" if st["level"] >= 255 else "attack"


def step_env(st):
    if not st["on"] or st["phase"] == "off":
        return False
    if st["phase"] == "attack":
        st["level"] = min(255, st["level"] + st["ar"])
        if st["level"] >= 255:
            st["phase"] = "decay"
    elif st["phase"] == "decay":
        st["level"] = st["level"] - st["dr"]
        if st["level"] <= st["sl"]:
            st["level"] = st["sl"]
            st["phase"] = "sustain"
    elif st["phase"] == "sustain":
        st["level"] = max(0, st["level"] - st["sr"])
        if st["level"] == 0:
            st["phase"] = "off"
    elif st["phase"] == "release":
        st["level"] = max(0, st["level"] - st["rr"])
        if st["level"] == 0:
            st["phase"] = "off"
    return True


def used_pcm_numbers(events) -> set:
    used, voice = set(), 1
    for ev in sorted(events, key=lambda e: (e.tick, e.kind != "pcm")):
        if ev.kind == "pcm":
            voice = ev.value
        elif ev.part == ADPCM_PART and ev.kind in ("note_on", "porta_on", "porta"):
            used.add(voice)
    return used


def compile_song(song: Song) -> bytes:
    vgm = VgmWriter(song.chip, song.chip_clock)
    init_fm(vgm)
    pcm_slots, pcm_rom = trim_pcm(song.pcm_slots, song.pcm_rom, used_pcm_numbers(song.events))
    write_rom(vgm, pcm_rom)
    ay = AyState(ssg_clock(song.chip, song.chip_clock))
    tempo, tempo_mode, timer_b, clock_c = 120, "T", 150, DEFAULT_C
    voice = {p: 1 for p in FM_PARTS}
    volume = {p: 15 for p in ALL_PARTS}
    volume[ADPCM_PART] = 200
    vol_mode = {p: "v" for p in ALL_PARTS}
    pan = {p: 3 for p in FM_PARTS}
    detune = {p: 0 for p in ALL_PARTS}
    mixer = {p: 1 for p in SSG_PARTS}
    pms = {p: 0 for p in FM_PARTS}
    ams = {p: 0 for p in FM_PARTS}
    amon = {p: [0, 0, 0, 0] for p in FM_PARTS}
    base_tl = {p: [0, 0, 0, 0] for p in FM_PARTS}
    carrier_idx = {p: set() for p in FM_PARTS}
    lfo = {p: new_mod_state() for p in MOD_PARTS}
    trem = {p: new_mod_state() for p in MOD_PARTS}
    env = {p: new_env() for p in SSG_PARTS}
    rev = {p: {"on": False, "val": 0, "mode": 1, "tail": False, "vol": 0} for p in ALL_PARTS}
    held = {p: None for p in ALL_PARTS}
    note_gen = {p: 0 for p in ALL_PARTS}
    hw_env = {p: False for p in SSG_PARTS}
    hw_shape = {p: 0 for p in SSG_PARTS}
    rhythm_mask = 1
    rhythm_total = 63
    rhythm_inst = [31, 31, 31, 31, 31, 31]
    rhythm_pan = [3, 3, 3, 3, 3, 3]
    pcm_voice, pcm_pan, pcm_vm, pcm_bias = 1, 3, False, 0
    slot_dt, last_tick = [0, 0, 0, 0], 0
    ext_mode = song.chip == "ym2608" and any(ev.kind == "slot_dt" or (ev.kind == "ex" and ev.value != 0xF) for ev in song.events)
    ex_ops = {p: 0xF for p in FM3_PARTS}
    key_ops = {p: 0xF for p in FM3_PARTS}
    kon = [0]

    def fm3_args(part):
        if part in FM3_PARTS:
            return ext_mode, slot_dt if part == "C" else [0, 0, 0, 0], key_ops[part]
        return False, None, 0xF

    def write_rhythm_levels():
        vgm.write_ym2608(0, 0x11, clamp(rhythm_total, 0, 63))
        for i, reg in enumerate(RHYTHM_REG):
            vgm.write_ym2608(0, reg, RHYTHM_PAN[rhythm_pan[i]] | clamp(rhythm_inst[i], 0, 31))

    def ssg_out_vol(part):
        if rev[part]["tail"]:
            ay.set_volume(SSG_CH[part], rev[part]["vol"])
            return
        if hw_env[part]:
            vgm.write_ssg(8 + SSG_CH[part], 0x10)
            return
        base = env_volume(env[part], volume[part]) if env[part]["on"] else volume[part]
        off = trem[part]["offset"] if trem[part]["on"] else 0
        ay.set_volume(SSG_CH[part], clamp(base + off, 0, 15))

    def apply_ssg_preset(part, no):
        preset = song.ssg_presets[no]
        if preset.env:
            al, ar, dr, sl, sr, rr = preset.env
            env[part].update(on=True, al=al, ar=ar, dr=dr, sl=sl, sr=sr, rr=rr)
        if preset.mixer is not None:
            mixer[part] = preset.mixer
            ay.set_mixer(SSG_CH[part], preset.mixer)
        if preset.noise is not None:
            ay.noise = preset.noise
        if preset.lfo:
            delay, step, depth, count = preset.lfo
            lfo[part].update(on=True, delay=delay, step=step, depth=depth, count=count)
            reset_mod(lfo[part])
        if preset.trem:
            delay, step, depth, count = preset.trem
            trem[part].update(on=True, delay=delay, step=step, depth=depth, count=count)
            reset_mod(trem[part])
        flush_ssg(vgm, ay)

    def refresh_voice(part, vol_override=None):
        vp = "C" if part in FM3_PARTS else part
        if part not in FM_PARTS or voice[vp] not in song.voices:
            return
        if part in FM3_PARTS and part != "C" and ex_ops[part] == 0xF:
            return
        apply_voice(vgm, part, voice[vp], volume[part] if vol_override is None else vol_override, song.voices, pan[vp], vol_mode[part], pms[vp], ams[vp], amon[vp], base_tl[part], carrier_idx[part], (key_ops[part] if held[part] is not None else ex_ops[part]) if part in FM3_PARTS else 0xF)
        off = trem[part]["offset"] if trem[part]["on"] else 0
        for index, slot in enumerate(SLOT_MAP[part]):
            if index in carrier_idx[part]:
                vgm.write_ym2608(PORT[part], 0x40 + slot, clamp(base_tl[part][index] + off, 0, 127))

    def samples_per_clock():
        return max(1, ticks_to_samples(max(1, INTERNAL_WHOLE // max(1, clock_c)), song.tick_rate, tempo, tempo_mode, timer_b, clock_c))

    def reset_mod(st):
        st.update(delay_left=max(0, st["delay"]), step_left=max(1, st["step"]), peak_left=max(0, st["count"]) // 2, delta=st["depth"], offset=0)

    def step_mod(st):
        if st["delay_left"] > 0:
            st["delay_left"] -= 1
            return False
        st["step_left"] -= 1
        if st["step_left"] > 0:
            return False
        st["step_left"] = max(1, st["step"])
        if st["peak_left"] == 0:
            st["delta"] = -st["delta"]
            st["peak_left"] = max(0, st["count"])
        st["peak_left"] -= 1
        st["offset"] += st["delta"]
        return True

    seq_of = {id(e): n for n, e in enumerate(song.events)}
    lock_seq = {}
    ssg_port = 0 if song.chip == "ym2608" else 2

    def unlock(port, reg, seq):
        # ロックより後に書かれたコマンド (通し番号が大きいもの) だけが、ロックを解除できる
        if lock_seq.get((port, reg), -1) < seq:
            vgm.clear_lock(port, reg)
            lock_seq.pop((port, reg), None)

    def unlock_voice(part, seq):
        port = PORT[part]
        for slot in SLOT_MAP[part]:
            for base in (0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90):
                unlock(port, base + slot, seq)
        unlock(port, 0xB0 + REG_CH[part], seq)

    def unlock_tl(part, seq):
        vp = "C" if part in FM3_PARTS else part
        if voice[vp] not in song.voices or (part in FM3_PARTS and part != "C" and ex_ops[part] == 0xF):
            return
        ops = (key_ops[part] if held[part] is not None else ex_ops[part]) if part in FM3_PARTS else 0xF
        for index in CARRIERS.get(clamp(song.voices[voice[vp]][0], 0, 7), (3,)):
            if (ops >> index) & 1:
                unlock(PORT[part], 0x40 + SLOT_MAP[part][index], seq)

    def unlock_ssg(regs, seq):
        for reg in regs:
            unlock(ssg_port, reg, seq)

    def rewrite_pitch(part):
        if held[part] is None or part in (RHYTHM_PART, ADPCM_PART):
            return
        if part in SSG_PARTS:
            write_ssg_pitch(ay, part, held[part], detune[part], lfo[part]["offset"] if lfo[part]["on"] else 0)
            flush_ssg(vgm, ay)
        elif ext_mode and part in FM3_PARTS:
            _, sdt, ops = fm3_args(part)
            write_ch3_slots(vgm, held[part], detune[part] + lfo[part]["offset"], sdt, ops)
        elif part in FM_PARTS:
            write_pitch(vgm, part, held[part], detune[part] + lfo[part]["offset"])

    def write_wait_mod(samples):
        left = samples
        while left > 0:
            active = [p for p in MOD_PARTS if held[p] is not None and lfo[p]["on"] and lfo[p]["depth"] and lfo[p]["count"]]
            active_trem = [p for p in MOD_PARTS if held[p] is not None and trem[p]["on"] and trem[p]["depth"] and trem[p]["count"]]
            active_env = [p for p in SSG_PARTS if env[p]["on"] and env[p]["phase"] != "off" and not hw_env[p]]
            if not active and not active_trem and not active_env:
                vgm.write_wait(left)
                return
            n = min(left, samples_per_clock())
            vgm.write_wait(n)
            left -= n
            for p in active:
                if step_mod(lfo[p]):
                    rewrite_pitch(p)
            for p in active_trem:
                if step_mod(trem[p]):
                    if p in SSG_PARTS:
                        ssg_out_vol(p)
                        flush_ssg(vgm, ay)
                    elif p in FM_PARTS:
                        refresh_voice(p)
            for p in active_env:
                if step_env(env[p]):
                    ssg_out_vol(p)
                    flush_ssg(vgm, ay)

    def pcm_volume():
        if pcm_vm and pcm_voice in song.pcm_slots:
            return clamp(song.pcm_slots[pcm_voice][2] + pcm_bias, 0, 255)
        return volume[ADPCM_PART]

    order = {"loop": 0, "tempo_bpm": 0, "tempo_tb": 0, "clock": 0, "ssg_preset": 1, "lfo": 1, "trem": 1, "ssg_env": 1, "hw_env": 1, "hw_period": 1, "reverb": 1, "slot_dt": 1, "ex": 1, "lfo22": 1, "lfo_ch": 1, "lfo_amon": 1, "reg": 1, "voice": 1, "pcm": 1, "pcm_vm": 1, "pcm_pan": 1, "mixer": 1, "noise": 1, "rhythm_mask": 1, "rhythm_vol": 1, "rhythm_pan": 1, "volume": 2, "volume_fine": 2, "pan": 2, "detune": 2, "rev_tail": 3, "note_off": 3, "rest": 5, "note_on": 4, "porta_on": 4, "porta_step": 6}

    def expand_porta(events):
        out = []
        for ev in events:
            if ev.kind != "porta":
                out.append(ev)
                continue
            clocks = ev.params[0] if ev.params else max(1, ev.duration * clock_c // INTERNAL_WHOLE)
            out.append(MusicEvent("porta_on", ev.tick, note=ev.note, value=ev.value, part=ev.part, legato=ev.legato, aux=ev.aux, duration=clocks))
            for i in range(1, clocks + 1):
                at = ev.tick + ev.duration * i // clocks
                out.append(MusicEvent("porta_step", at, note=ev.note, value=ev.value, part=ev.part, duration=i, aux=clocks))
        return out
    if song.chip == "ym2608":
        vgm.write_ym2608(0, 0x10, 0x80)
        write_rhythm_levels()
        if ext_mode:
            vgm.write_ym2608(0, 0x27, 0x40)
    def ev_key(e):
        # ポルタメントの最後のステップは、同じ時刻の次の音符より先に実行する (後だと次の音符の音程を上書きしてしまう)
        rank = 2 if e.kind == "porta_step" and e.duration >= e.aux else order.get(e.kind, 9)
        return (e.tick, rank, e.part)

    for ev in sorted(expand_porta(song.events), key=ev_key):
        cur_seq = seq_of.get(id(ev), 0)
        now = max(ev.tick, 0)
        write_wait_mod(ticks_to_samples(now - last_tick, song.tick_rate, tempo, tempo_mode, timer_b, clock_c))
        last_tick = now
        if ev.kind == "loop":
            vgm.mark_loop()
        elif ev.kind == "tempo_bpm":
            tempo_mode, tempo = "T", max(1, ev.value)
        elif ev.kind == "tempo_tb":
            tempo_mode, timer_b = "t", clamp(ev.value, 0, 255)
        elif ev.kind == "clock":
            clock_c = max(1, ev.value)
        elif ev.kind == "ssg_preset":
            unlock_ssg((7, 8 + SSG_CH[ev.part]), cur_seq)
            apply_ssg_preset(ev.part, ev.value)
        elif ev.kind == "pcm":
            if song.pcm_slots and ev.value not in song.pcm_slots:
                raise ValueError(f"PCM @{ev.value} が定義されていません")
            pcm_voice = ev.value
        elif ev.kind == "pcm_vm":
            pcm_vm, pcm_bias = True, ev.value
        elif ev.kind == "pcm_pan":
            pcm_pan = ev.value
        elif ev.kind == "hw_env":
            hw_env[ev.part], hw_shape[ev.part] = True, ev.value
            unlock_ssg((8 + SSG_CH[ev.part],), cur_seq)
            vgm.write_ssg(13, ev.value & 15)
            vgm.write_ssg(8 + SSG_CH[ev.part], 0x10)
        elif ev.kind == "hw_period":
            unlock_ssg((11, 12), cur_seq)
            vgm.write_ssg(11, ev.value & 0xFF)
            vgm.write_ssg(12, (ev.value >> 8) & 0xFF)
        elif ev.kind == "rhythm_mask":
            rhythm_mask = ev.value & 0x3F
        elif ev.kind == "rhythm_vol":
            if ev.params:
                rhythm_total = clamp(ev.params[0], 0, 63)
            for i, val in enumerate(ev.params[1:7]):
                rhythm_inst[i] = clamp(val, 0, 31)
            write_rhythm_levels()
        elif ev.kind == "rhythm_pan":
            inst, pan_bits = ev.value & 0x0F, (ev.value >> 4) & 3
            if inst < 6:
                rhythm_pan[inst] = pan_bits
                write_rhythm_levels()
        elif ev.kind == "lfo" and ev.part in MOD_PARTS:
            lfo[ev.part].update(on=bool(ev.legato), delay=ev.note, step=max(1, ev.duration), depth=ev.value, count=max(0, ev.aux))
            reset_mod(lfo[ev.part])
        elif ev.kind == "trem" and ev.part in MOD_PARTS:
            trem[ev.part].update(on=bool(ev.legato), delay=ev.note, step=max(1, ev.duration), depth=ev.value, count=max(0, ev.aux))
            reset_mod(trem[ev.part])
            if ev.part in SSG_PARTS and (held[ev.part] is not None or env[ev.part]["phase"] == "release"):
                ssg_out_vol(ev.part)
                flush_ssg(vgm, ay)
            elif ev.part in FM_PARTS:
                refresh_voice(ev.part)
        elif ev.kind == "ssg_env":
            unlock_ssg((8 + SSG_CH[ev.part],), cur_seq)
            al, ar, dr, sl, sr, rr = ev.params
            env[ev.part].update(on=True, al=clamp(al, 0, 255), ar=clamp(ar, 0, 255), dr=clamp(dr, 0, 255), sl=clamp(sl, 0, 255), sr=clamp(sr, 0, 255), rr=clamp(rr, 0, 255))
        elif ev.kind == "reverb":
            rev[ev.part].update(on=bool(ev.legato), val=ev.value, mode=ev.note)
        elif ev.kind == "slot_dt":
            slot_dt = [ev.duration, ev.aux, ev.value, ev.note]
            rewrite_pitch("C")
        elif ev.kind == "ex":
            ex_ops[ev.part] = ev.value
        elif ev.kind == "lfo22":
            vgm.write_ym2608(0, 0x22, ev.value & 0xFF)
        elif ev.kind == "lfo_ch":
            unlock(PORT[ev.part], 0xB4 + REG_CH[ev.part], cur_seq)
            pms[ev.part], ams[ev.part] = ev.note, ev.value
            write_b4(vgm, ev.part, pan[ev.part], pms[ev.part], ams[ev.part])
        elif ev.kind == "lfo_amon":
            amon[ev.part][ev.note] = ev.value
            dr = song.voices[voice[ev.part]][2][ev.note][3] & 0x1F if voice[ev.part] in song.voices else 0
            vgm.write_ym2608(PORT[ev.part], 0x60 + SLOT_MAP[ev.part][ev.note], ((1 if ev.value else 0) << 7) | dr)
        elif ev.kind == "reg":
            if ev.part in SSG_PARTS and song.chip != "ym2608":
                vgm.write_ssg(ev.note & 0x0F, ev.value, True)
                lock_seq[(2, ev.note & 0x0F)] = cur_seq
            else:
                vgm.write_ym2608(ev.duration, ev.note, ev.value, True)
                lock_seq[(1 if ev.duration else 0, ev.note & 0xFF)] = cur_seq
        elif ev.kind == "voice":
            voice[ev.part] = ev.value
            unlock_voice(ev.part, cur_seq)
            refresh_voice(ev.part)
        elif ev.kind == "mixer":
            unlock_ssg((7,), cur_seq)
            mixer[ev.part] = ev.value
            ay.set_mixer(SSG_CH[ev.part], ev.value)
            flush_ssg(vgm, ay)
        elif ev.kind == "noise":
            unlock_ssg((6,), cur_seq)
            ay.noise = ev.value
            flush_ssg(vgm, ay)
        elif ev.kind == "volume" and ev.part == ADPCM_PART:
            volume[ev.part] = clamp(ev.value, 0, 255)
            if not pcm_vm:
                vgm.write_ym2608(1, 0x0B, volume[ev.part])
        elif ev.kind == "volume":
            vol_mode[ev.part], volume[ev.part] = "v", ev.value
            if ev.part in SSG_PARTS:
                unlock_ssg((8 + SSG_CH[ev.part],), cur_seq)
            elif ev.part in FM_PARTS:
                unlock_tl(ev.part, cur_seq)
            if ev.part in SSG_PARTS and (held[ev.part] is not None or env[ev.part]["phase"] != "off"):
                ssg_out_vol(ev.part)
                flush_ssg(vgm, ay)
            elif ev.part in FM_PARTS:
                refresh_voice(ev.part)
        elif ev.kind == "volume_fine":
            vol_mode[ev.part], volume[ev.part] = "V", ev.value
            if ev.part in FM_PARTS:
                unlock_tl(ev.part, cur_seq)
                refresh_voice(ev.part)
        elif ev.kind == "pan":
            unlock(PORT[ev.part], 0xB4 + REG_CH[ev.part], cur_seq)
            pan[ev.part] = ev.value
            write_b4(vgm, ev.part, pan[ev.part], pms[ev.part], ams[ev.part])
        elif ev.kind == "detune" and ev.part == ADPCM_PART:
            detune[ev.part] = ev.value
            if held[ev.part] is not None:
                set_rate(vgm, delta_n(held[ev.part], ev.value))
        elif ev.kind == "detune":
            detune[ev.part] = ev.value
            rewrite_pitch(ev.part)
        elif ev.kind == "rev_tail" and ev.part in FM_PARTS and rev[ev.part]["on"]:
            vol = fine_reverb_volume(volume[ev.part], rev[ev.part]["val"]) if vol_mode[ev.part] == "V" else fm_reverb_volume(volume[ev.part], rev[ev.part]["val"])
            refresh_voice(ev.part, vol)
            rev[ev.part]["tail"] = True
        elif ev.kind == "rev_tail" and ev.part in SSG_PARTS and rev[ev.part]["on"]:
            vol = ssg_reverb_volume(volume[ev.part], rev[ev.part]["val"])
            rev[ev.part]["tail"], rev[ev.part]["vol"] = True, vol
            if env[ev.part]["on"] and not hw_env[ev.part]:
                env[ev.part]["phase"] = "off"
            if hw_env[ev.part]:
                vgm.write_ssg(8 + SSG_CH[ev.part], vol)
            else:
                ay.set_volume(SSG_CH[ev.part], vol)
                flush_ssg(vgm, ay)
        elif ev.kind == "note_on" and ev.part == RHYTHM_PART:
            note_gen[ev.part] = ev.aux
            held[ev.part] = rhythm_mask
            vgm.write_ym2608(0, 0x10, rhythm_mask & 0x3F)
        elif ev.kind == "note_on" and ev.part == ADPCM_PART:
            same = ev.legato and held[ev.part] == ev.note
            note_gen[ev.part] = ev.aux
            if not song.pcm_slots:
                held[ev.part] = ev.note
                continue
            if pcm_voice not in song.pcm_slots:
                raise ValueError(f"PCM @{pcm_voice} が定義されていません")
            start, end, _base = pcm_slots[pcm_voice]
            held[ev.part] = ev.note
            if same:
                set_rate(vgm, delta_n(ev.note, detune[ev.part]))
            else:
                play(vgm, start, end, delta_n(ev.note, detune[ev.part]), pcm_volume(), pcm_pan)
        elif ev.kind == "note_on":
            note_gen[ev.part] = ev.aux
            if ev.part in SSG_PARTS:
                unlock_ssg((2 * SSG_CH[ev.part], 2 * SSG_CH[ev.part] + 1), cur_seq)
                rev[ev.part]["tail"] = False
                if not ev.legato:
                    reset_mod(lfo[ev.part])
                    reset_mod(trem[ev.part])
                    if env[ev.part]["on"] and not hw_env[ev.part]:
                        start_env(env[ev.part])
                held[ev.part] = ev.note
                ay.set_mixer(SSG_CH[ev.part], mixer[ev.part])
                write_ssg_pitch(ay, ev.part, ev.note, detune[ev.part], lfo[ev.part]["offset"] if lfo[ev.part]["on"] else 0)
                flush_ssg(vgm, ay)
                if hw_env[ev.part]:
                    vgm.write_ssg(8 + SSG_CH[ev.part], 0x10)
                    vgm.write_ssg(13, hw_shape[ev.part] & 15)
                else:
                    ssg_out_vol(ev.part)
                    flush_ssg(vgm, ay)
            else:
                if ev.part in FM3_PARTS and not ev.legato:
                    key_ops[ev.part] = ex_ops[ev.part]
                if rev[ev.part]["tail"]:
                    refresh_voice(ev.part)
                    rev[ev.part]["tail"] = False
                if not ev.legato:
                    reset_mod(lfo[ev.part])
                    reset_mod(trem[ev.part])
                    refresh_voice(ev.part)
                held[ev.part] = ev.note
                eff, sdt, ops = fm3_args(ev.part)
                key_on(vgm, ev.part, ev.note, detune[ev.part] + lfo[ev.part]["offset"], ev.legato, eff, sdt, ops, kon if ev.part in FM3_PARTS else None)
        elif ev.kind == "porta_on" and ev.part in FM_PARTS:
            note_gen[ev.part] = ev.aux
            if ev.part in FM3_PARTS and not ev.legato:
                key_ops[ev.part] = ex_ops[ev.part]
            held[ev.part] = ev.note
            eff, sdt, ops = fm3_args(ev.part)
            key_on(vgm, ev.part, ev.note, detune[ev.part], ev.legato, eff, sdt, ops, kon if ev.part in FM3_PARTS else None)
        elif ev.kind == "porta_step" and ev.part in FM_PARTS:
            held[ev.part] = ev.value
            if ext_mode and ev.part in FM3_PARTS:
                _, sdt, ops = fm3_args(ev.part)
                write_ch3_porta(vgm, ev.note, ev.value, detune[ev.part], sdt, ev.duration, ev.aux, ops)
            else:
                start = scaled_pitch(ev.note, detune[ev.part])
                end = scaled_pitch(ev.value, detune[ev.part])
                block, fnum = split_pitch(start + (end - start) * ev.duration // max(1, ev.aux))
                write_fnum(vgm, ev.part, block, fnum)
        elif ev.kind == "porta_on" and ev.part in SSG_PARTS:
            note_gen[ev.part] = ev.aux
            rev[ev.part]["tail"] = False
            if not ev.legato and env[ev.part]["on"] and not hw_env[ev.part]:
                start_env(env[ev.part])
            held[ev.part] = ev.note
            ch = SSG_CH[ev.part]
            ay.set_mixer(ch, mixer[ev.part])
            ay.channels[ch].period = tone_period(ay.clock, ev.note, detune[ev.part])
            flush_ssg(vgm, ay)
            if hw_env[ev.part]:
                vgm.write_ssg(8 + ch, 0x10)
                vgm.write_ssg(13, hw_shape[ev.part] & 15)
            else:
                ssg_out_vol(ev.part)
                flush_ssg(vgm, ay)
        elif ev.kind == "porta_step" and ev.part in SSG_PARTS:
            held[ev.part] = ev.value
            ch = SSG_CH[ev.part]
            start_p = tone_period(ay.clock, ev.note, detune[ev.part])
            end_p = tone_period(ay.clock, ev.value, detune[ev.part])
            cur = max(1, min(4095, start_p + (end_p - start_p) * ev.duration // max(1, ev.aux)))
            ay.channels[ch].period = cur
            vgm.write_ssg(ch * 2, cur & 0xFF)
            vgm.write_ssg(ch * 2 + 1, (cur >> 8) & 0x0F)
        elif ev.kind == "note_off" and ev.part == RHYTHM_PART:
            if ev.aux not in (0, note_gen[ev.part]) and ev.aux != 10**9:
                continue
            mask = held[ev.part] or rhythm_mask
            held[ev.part] = None
            vgm.write_ym2608(0, 0x10, 0x80 | (mask & 0x3F))
        elif ev.kind == "note_off" and ev.part == ADPCM_PART:
            if ev.aux not in (0, note_gen[ev.part]) and ev.aux != 10**9:
                continue
            held[ev.part] = None
            stop(vgm)
        elif ev.kind == "note_off":
            if ev.aux not in (0, note_gen[ev.part]) and ev.aux != 10**9:
                continue
            held[ev.part] = None
            if ev.part in SSG_PARTS:
                if rev[ev.part]["tail"]:
                    rev[ev.part]["tail"] = False
                    if hw_env[ev.part]:
                        vgm.write_ssg(8 + SSG_CH[ev.part], 0x00)
                    else:
                        ay.set_volume(SSG_CH[ev.part], 0)
                        flush_ssg(vgm, ay)
                elif hw_env[ev.part]:
                    vgm.write_ssg(8 + SSG_CH[ev.part], 0x00)
                elif env[ev.part]["on"] and env[ev.part]["phase"] != "off":
                    env[ev.part]["phase"] = "release"
                    ssg_out_vol(ev.part)
                    flush_ssg(vgm, ay)
                else:
                    ay.set_volume(SSG_CH[ev.part], 0)
                    flush_ssg(vgm, ay)
            elif ev.part in FM_PARTS:
                key_off(vgm, ev.part, key_ops[ev.part] if ev.part in FM3_PARTS else 0xF, kon if ev.part in FM3_PARTS else None)
                if rev[ev.part]["tail"]:
                    refresh_voice(ev.part)
                    rev[ev.part]["tail"] = False
        elif ev.kind == "rest" and ev.part == ADPCM_PART:
            held[ev.part] = None
            stop(vgm)
        elif ev.kind == "rest" and ev.part in ALL_PARTS:
            if ev.part in SSG_PARTS and env[ev.part]["on"] and env[ev.part]["phase"] == "release":
                held[ev.part] = None
            elif not (rev[ev.part]["on"] and rev[ev.part]["mode"] == 0 and held[ev.part] is not None):
                held[ev.part] = None
                if ev.part in SSG_PARTS and not hw_env[ev.part]:
                    ay.set_volume(SSG_CH[ev.part], 0)
                    flush_ssg(vgm, ay)
    vgm.write_end()
    return vgm.build()
