from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from adpcm import load_song_pcm
from chips.ay8910 import SSG_PARTS
from chips.opn import FM_PARTS, SLOT_MAP, Y_SLOT_REGS, lfo22_value, pack_voice, y_port
from vgmwriter import AY_CLOCK, DEFAULT_C, INTERNAL_WHOLE, YM2608_CLOCK, clamp

NOTE_MAP = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
RHYTHM_PART = "G"
ADPCM_PART = "K"
MOD_PARTS = FM_PARTS + SSG_PARTS
ALL_PARTS = MOD_PARTS + RHYTHM_PART + ADPCM_PART

SSG_BUILTIN = {
    0: "E255,255,255,255,0,255 P1",
    1: "E255,255,255,200,0,10 P1",
    2: "E255,255,255,200,1,10 P1",
    3: "E255,255,255,190,0,10 P1 M16,1,25,4",
    4: "E255,255,255,190,1,10 P1 M16,1,25,4",
    5: "E255,255,255,170,0,10 P1",
    6: "E40,70,14,190,0,15 P1 M16,1,24,5",
    7: "E120,30,255,255,0,10 P1 M16,1,25,4",
    8: "E255,255,255,225,8,15 P1",
    9: "E255,255,255,1,255,255 P2",
    10: "E255,255,255,200,8,255 P2",
    11: "E255,255,255,220,20,8 P1 M1,1,300,-1",
    12: "E255,255,255,255,0,10 P1 M1,1,-400,4",
    13: "E255,255,255,255,0,10 P1 M1,1,80,-1",
    14: "E120,80,255,255,0,255 P1 M1,1,-250,1",
    15: "E255,255,255,220,0,255 P1 M1,1,3000,-1",
}


@dataclass
class MusicEvent:
    kind: str
    tick: int
    duration: int = 0
    note: int = 0
    value: int = 0
    part: str = "A"
    legato: bool = False
    aux: int = 0
    params: tuple = ()


@dataclass
class SsgPreset:
    env: tuple | None = None
    mixer: int | None = None
    noise: int | None = None
    lfo: tuple | None = None
    trem: tuple | None = None


@dataclass
class PartState:
    tick: int = 0
    octave: int = 6
    def_len: int = 4
    def_clocks: int | None = None
    q: int = 0
    q_mode: str = "q"
    q_div: int = 8
    transpose: int = 0
    clock_c: int = DEFAULT_C
    total_clocks: int = 0
    vol_mode: str = "v"
    volume_v: int = 15
    volume_fine: int = 127
    vol_bias: int = 0
    shuffle: int = 0
    detune: int = 0
    muted: bool = False
    stopped: bool = False
    pms: int = 0
    ams: int = 0
    amon: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    pending_tie: bool = False
    lfo_on: bool = False
    lfo_delay: int = 0
    lfo_step: int = 1
    lfo_depth: int = 0
    lfo_count: int = 0
    trem_on: bool = False
    trem_delay: int = 0
    trem_step: int = 1
    trem_depth: int = 0
    trem_count: int = 0
    rev_on: bool = False
    rev_val: int = 0
    rev_mode: int = 1
    echo_back: int = 1
    echo_drop: int = 4
    mixer: int = 1
    noise: int = 0
    rhythm_mask: int = 1
    jump_tick: int | None = None
    note_hist: list = field(default_factory=list)


@dataclass
class Song:
    title: str = ""
    chip: str = "ym2608"
    chip_clock: int = YM2608_CLOCK
    tick_rate: int = INTERNAL_WHOLE
    events: list[MusicEvent] = field(default_factory=list)
    voices: dict[int, tuple] = field(default_factory=dict)
    ssg_presets: dict[int, SsgPreset] = field(default_factory=dict)
    part_clocks: dict[str, int] = field(default_factory=dict)
    loop_tick: int | None = None
    lfo_enable: int = 0
    lfo_speed: int = 0
    voice_file: str = ""
    pcm_file: str = ""
    pcm_list: str = ""
    pcm_slots: dict = field(default_factory=dict)
    pcm_rom: bytes = b""
    macros: dict[int, str] = field(default_factory=dict)


def strip_comment(text: str) -> str:
    pos = text.find(";")
    return text[:pos] if pos >= 0 else text


def skip_space(text: str, i: int, end: int) -> int:
    j = i + 1
    while j < end and text[j].isspace():
        j += 1
    return j


def read_number(text: str, i: int, fallback: int) -> tuple[int, int]:
    j = i + 1
    digits = ""
    while j < len(text) and text[j].isdigit():
        digits += text[j]
        j += 1
    return (int(digits), j - 1) if digits else (fallback, i)


def read_signed_number(text: str, i: int, fallback: int) -> tuple[int, int]:
    j = i + 1
    sign = 1
    if j < len(text) and text[j] in "+-":
        sign = -1 if text[j] == "-" else 1
        j += 1
    digits = ""
    while j < len(text) and text[j].isdigit():
        digits += text[j]
        j += 1
    return (sign * int(digits), j - 1) if digits else (fallback, i)


def read_imm(text: str, i: int, end: int, fallback: int = 0) -> tuple[int, int]:
    j = i
    while j < end and text[j] in " \t,":
        j += 1
    if j >= end:
        return fallback, i
    sign = 1
    if text[j] in "+-":
        sign = -1 if text[j] == "-" else 1
        j += 1
    if j < end and text[j] == "$":
        j += 1
        k = j
        while k < end and text[k] in "0123456789abcdefABCDEF":
            k += 1
        return (sign * int(text[j:k], 16), k - 1) if k > j else (fallback, i)
    if j < end and text[j].isdigit():
        k = j
        while k < end and text[k].isdigit():
            k += 1
        return sign * int(text[j:k]), k - 1
    return fallback, i


def read_detune(text: str, i: int, current: int) -> tuple[int, int]:
    j = i + 1
    sign = 1
    if j < len(text) and text[j] in "+-":
        sign = -1 if text[j] == "-" else 1
        j += 1
    digits = ""
    while j < len(text) and text[j].isdigit():
        digits += text[j]
        j += 1
    if not digits:
        return current, i
    value = sign * int(digits)
    if j < len(text) and text[j] == "+":
        return current + value, j
    if j < len(text) and text[j] == "-":
        return current - abs(value), j
    return value, j - 1


def expand_macros(text: str, macros: dict[int, str], depth: int = 0) -> str:
    if depth > 8:
        raise ValueError("マクロのネストが深すぎます")
    out, i = [], 0
    while i < len(text):
        if text[i] == "*":
            no, j = read_number(text, i, -1)
            if no not in macros:
                raise ValueError(f"マクロ *{no} が定義されていません")
            out.append(expand_macros(macros[no], macros, depth + 1))
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def parse_nums(line: str) -> list[int]:
    nums, i, s = [], 0, line.strip()
    while i < len(s):
        if s[i] in "+-" and i + 1 < len(s) and s[i + 1].isdigit():
            sign = -1 if s[i] == "-" else 1
            i += 1
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            nums.append(sign * int(s[i:j]))
            i = j
        elif s[i].isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            nums.append(int(s[i:j]))
            i = j
        else:
            i += 1
    return nums


def next_data_line(lines, i):
    while i < len(lines):
        if strip_comment(lines[i]).strip():
            return lines[i], i + 1
        i += 1
    raise ValueError("音色データの行が足りません")


def parse_voice_block(lines, start, voice_no):
    header, i = next_data_line(lines, start)
    nums = parse_nums(strip_comment(header))
    if len(nums) < 2:
        raise ValueError(f"@ {voice_no}: FB AL が必要です")
    ops = []
    for n in range(4):
        row, i = next_data_line(lines, i)
        vals = parse_nums(strip_comment(row))
        if len(vals) < 9:
            raise ValueError(f"@ {voice_no}: オペレータ{n + 1} のパラメータが不足しています")
        ops.append(vals[:10])
    return pack_voice(nums[0], nums[1], ops), i


VOICE_DAT_SIZE = 32
VOICE_DAT_REG_ORDER = (0, 2, 1, 3)


def parse_voice_dat(data: bytes) -> dict[int, tuple]:
    # 1音色32バイト: [0]=未使用, [1..25]=レジスタ順の25バイト(op1,op3,op2,op4), [26..31]=音色名
    if len(data) < VOICE_DAT_SIZE:
        raise ValueError("音色ファイル(voice.dat)が小さすぎます")
    voices = {}
    for no in range(len(data) // VOICE_DAT_SIZE):
        reg = data[no * VOICE_DAT_SIZE + 1:no * VOICE_DAT_SIZE + 26]
        if not any(reg):
            continue
        dtml, tl, ksar, dr, sr, slrr, fbal = reg[0:4], reg[4:8], reg[8:12], reg[12:16], reg[16:20], reg[20:24], reg[24]
        ops = []
        for pos in VOICE_DAT_REG_ORDER:
            ops.append([
                ksar[pos] & 31, dr[pos] & 31, sr[pos] & 31, slrr[pos] & 15,
                slrr[pos] >> 4, tl[pos] & 127, ksar[pos] >> 6, dtml[pos] & 15, (dtml[pos] >> 4) & 7,
            ])
        voices[no] = pack_voice((fbal >> 3) & 7, fbal & 7, ops)
    return voices


def load_voice_file(folder: Path, name: str) -> dict[int, tuple]:
    path = folder / name
    if not path.is_file():
        raise ValueError(f"音色ファイルがありません: {path}")
    return parse_voice_dat(path.read_bytes())


def parse_ssg_preset(no: int, body: str) -> SsgPreset:
    preset = SsgPreset()
    i, end = 0, len(body)
    while i < end:
        c = body[i]
        if c.isspace() or c == ",":
            i += 1
            continue
        if c == "E":
            al, k = read_imm(body, i + 1, end, 255)
            ar, k = read_imm(body, k + 1, end, 255)
            dr, k = read_imm(body, k + 1, end, 255)
            sl, k = read_imm(body, k + 1, end, 255)
            sr, k = read_imm(body, k + 1, end, 0)
            rr, i = read_imm(body, k + 1, end, 255)
            preset.env = tuple(clamp(n, 0, 255) for n in (al, ar, dr, sl, sr, rr))
        elif c == "P":
            n, i = read_imm(body, i + 1, end, 1)
            preset.mixer = clamp(n, 0, 3)
        elif c == "w":
            n, i = read_imm(body, i + 1, end, 0)
            preset.noise = clamp(n, 0, 31)
        elif c == "M":
            delay, k = read_imm(body, i + 1, end, 0)
            step, k = read_imm(body, k + 1, end, 1)
            depth, k = read_imm(body, k + 1, end, 0)
            count, i = read_imm(body, k + 1, end, 0)
            preset.lfo = (delay, max(1, step), depth, max(0, count))
        elif c == "N":
            delay, k = read_imm(body, i + 1, end, 0)
            step, k = read_imm(body, k + 1, end, 1)
            depth, k = read_imm(body, k + 1, end, 0)
            count, i = read_imm(body, k + 1, end, 0)
            preset.trem = (delay, max(1, step), depth, max(0, count))
        else:
            raise ValueError(f"SSG音色 @{no}: '{c}' は使えません。使えるのは E P M N w です")
        i += 1
    return preset


def find_loop_end(text, start):
    depth, j = 1, start + 1
    while j < len(text) and depth:
        depth += 1 if text[j] == "[" else -1 if text[j] == "]" else 0
        j += 1
    if depth:
        raise ValueError("ループの ']' がありません")
    return j - 1


def find_brace_end(text, start):
    depth, j = 1, start + 1
    while j < len(text) and depth:
        depth += 1 if text[j] == "{" else -1 if text[j] == "}" else 0
        j += 1
    if depth:
        raise ValueError("ポルタメントの '}' がありません")
    return j - 1


def find_top_slash(text, start, end):
    depth = 0
    for j in range(start, end):
        depth += 1 if text[j] == "[" else -1 if text[j] == "]" else 0
        if text[j] == "/" and depth == 0:
            return j
    return None


def octave_after(text, start, end, octave, lo=1):
    i = start
    while i < end:
        c = text[i]
        if c == "[":
            close = find_loop_end(text, i)
            octave = octave_after(text, i + 1, close, octave, lo)
            i = close
        elif c == "{":
            close = find_brace_end(text, i)
            octave = octave_after(text, i + 1, close, octave, lo)
            i = close
        elif c == "o":
            octave, i = read_number(text, i, octave)
            octave = clamp(octave, lo, 8)
        elif c == ">":
            octave = clamp(octave + 1, lo, 8)
        elif c == "<":
            octave = clamp(octave - 1, lo, 8)
        i += 1
    return octave


def note_duration(length, dots):
    duration = INTERNAL_WHOLE // max(1, length)
    extra, add = duration, 0
    for _ in range(max(0, dots)):
        extra //= 2
        add += extra
    return max(1, duration + add)


def clocks_to_internal(clocks, clock_c):
    return max(1, clocks * INTERNAL_WHOLE // max(1, clock_c))


def parse_duration_spec(mml, i, end, def_len, def_clocks, clock_c):
    def one():
        nonlocal i
        if i + 1 < end and mml[i + 1] == "%":
            clocks, i = read_number(mml, i + 1, 1)
            return clocks_to_internal(max(1, clocks), clock_c)
        dots = 0
        if i + 1 < end and mml[i + 1].isdigit():
            length, i = read_number(mml, i, def_len)
        else:
            length = def_len
        while i + 1 < end and mml[i + 1] == ".":
            dots += 1
            i += 1
        if def_clocks is not None and dots == 0 and length == def_len and not (i + 1 < end and mml[i + 1].isdigit()):
            return clocks_to_internal(def_clocks, clock_c)
        return note_duration(length, dots)
    duration = one()
    while i + 1 < end and mml[i + 1] == "^":
        i += 1
        duration += one()
    return duration, i


def gate_duration(duration, q, q_mode, q_div, clock_c):
    if q_mode == "Q":
        return max(1, duration * clamp(q_div, 0, 8) // 8)
    return max(1, duration - q * INTERNAL_WHOLE // max(1, clock_c))


def emit_volume(song, part, tick, vol_mode, volume_v, volume_fine):
    kind = "volume_fine" if vol_mode == "V" else "volume"
    song.events.append(MusicEvent(kind, tick, value=volume_fine if vol_mode == "V" else volume_v, part=part))


def note_index(octave, name, acc, transpose):
    return (octave - 1) * 12 + NOTE_MAP[name] + acc + transpose


def fm_reverb_volume(volume_v, rev_val):
    return clamp(((volume_v + rev_val + 4) // 2) - 4, 0, 15)


def fine_reverb_volume(volume_fine, rev_val):
    return clamp(((volume_fine + rev_val * 8 + 4) // 2) - 4, 0, 127)


def parse_porta_body(mml, start, end, octave, def_len, def_clocks, clock_c, transpose, lo):
    i, notes, duration = start, [], None
    while i < end:
        c = mml[i]
        if c.isspace() or c in "|&":
            i += 1
            continue
        if c == "o":
            octave, i = read_number(mml, i, octave)
            octave = clamp(octave, lo, 8)
        elif c == ">":
            octave = clamp(octave + 1, lo, 8)
        elif c == "<":
            octave = clamp(octave - 1, lo, 8)
        elif c.lower() in NOTE_MAP:
            acc = 1 if i + 1 < end and mml[i + 1] == "+" else -1 if i + 1 < end and mml[i + 1] == "-" else 0
            if acc:
                i += 1
            notes.append(note_index(octave, c.lower(), acc, transpose))
            if duration is None:
                duration, i = parse_duration_spec(mml, i, end, def_len, def_clocks, clock_c)
        i += 1
    if not notes:
        raise ValueError("ポルタメントに音符がありません")
    return notes[0], notes[-1], duration or note_duration(def_len, False), octave


def parse_part_mml(song, part, mml, state):
    if state.stopped:
        return
    mml = expand_macros(strip_comment(mml), song.macros)
    mml = "".join(ch for ch in mml if not ch.isspace())
    lo = 0 if part == ADPCM_PART else 1
    tick, octave = state.tick, state.octave
    def_len, def_clocks = state.def_len, state.def_clocks
    q, q_mode, q_div = state.q, state.q_mode, state.q_div
    transpose, clock_c, total_clocks = state.transpose, state.clock_c, state.total_clocks
    vol_mode, volume_v, volume_fine = state.vol_mode, state.volume_v, state.volume_fine
    vol_bias, shuffle, detune = state.vol_bias, state.shuffle, state.detune
    muted, stopped = state.muted, state.stopped
    pms, ams, amon = state.pms, state.ams, list(state.amon)
    pending_tie = state.pending_tie
    lfo_on, lfo_delay, lfo_step = state.lfo_on, state.lfo_delay, state.lfo_step
    lfo_depth, lfo_count = state.lfo_depth, state.lfo_count
    trem_on, trem_delay, trem_step = state.trem_on, state.trem_delay, state.trem_step
    trem_depth, trem_count = state.trem_depth, state.trem_count
    rev_on, rev_val, rev_mode = state.rev_on, state.rev_val, state.rev_mode
    echo_back, echo_drop = state.echo_back, state.echo_drop
    mixer, noise, rhythm_mask = state.mixer, state.noise, state.rhythm_mask
    jump_tick, note_hist, note_gen = state.jump_tick, list(state.note_hist), 0
    tie_note, tie_origin, tie_dur, tie_gen = None, 0, 0, 0

    def emit_note_tail(duration, note, gen):
        nonlocal pending_tie
        gate = gate_duration(duration, q, q_mode, q_div, clock_c)
        if rev_on and part in FM_PARTS:
            song.events.append(MusicEvent("rev_tail", tick + gate, part=part))
            if rev_mode == 1:
                song.events.append(MusicEvent("note_off", tick + max(gate, duration), note=note, part=part, aux=gen))
        else:
            song.events.append(MusicEvent("note_off", tick + gate, note=note, part=part, aux=gen))
        pending_tie = False

    def remember(note, duration):
        note_hist.append((note, duration))
        del note_hist[:-16]

    def apply_volume_delta(delta):
        nonlocal volume_v, volume_fine
        if vol_mode == "V":
            volume_fine = clamp(volume_fine + delta, 0, 127)
        else:
            volume_v = clamp(volume_v + delta, 0, 255 if part == ADPCM_PART else 15)
        emit_volume(song, part, tick, vol_mode, volume_v, volume_fine)

    def shuffled_on(note, duration, legato):
        nonlocal note_gen
        note_gen += 1
        shift = shuffle * INTERNAL_WHOLE // max(1, clock_c)
        gate = gate_duration(duration, q, q_mode, q_div, clock_c)
        on_at = tick + shift
        if shift > 0:
            on_at = min(on_at, tick + max(1, gate) - 1)
        if shift < 0 and not legato:
            song.events.append(MusicEvent("note_off", on_at, part=part, aux=note_gen - 1))
        song.events.append(MusicEvent("note_on", on_at, duration=duration, note=note, part=part, legato=legato, aux=note_gen))
        return note_gen

    def emit_echo():
        nonlocal tick, total_clocks
        if echo_back <= 0 or echo_back > len(note_hist):
            note = note_index(1, "c", 0, 0)
            duration = clocks_to_internal(def_clocks, clock_c) if def_clocks else note_duration(def_len, False)
        else:
            note, duration = note_hist[-echo_back]
        apply_volume_delta(-max(0, echo_drop))
        gen = shuffled_on(note, duration, False)
        emit_note_tail(duration, note, gen)
        total_clocks += duration * clock_c // INTERNAL_WHOLE
        tick += duration
        apply_volume_delta(max(0, echo_drop))

    def parse_range(start, end):
        nonlocal tick, octave, def_len, def_clocks, q, q_mode, q_div, transpose
        nonlocal clock_c, total_clocks, vol_mode, volume_v, volume_fine, vol_bias, shuffle, detune
        nonlocal muted, stopped, pending_tie, pms, ams, jump_tick, tie_note, tie_origin, tie_dur, tie_gen
        nonlocal lfo_on, lfo_delay, lfo_step, lfo_depth, lfo_count
        nonlocal trem_on, trem_delay, trem_step, trem_depth, trem_count
        nonlocal rev_on, rev_val, rev_mode, echo_back, echo_drop, mixer, noise, rhythm_mask, note_gen
        i = start
        while i < end and not stopped:
            c = mml[i]
            if c.isspace() or c in "/|":
                i += 1
                continue
            if c == ":":
                stopped = True
                break
            if c == "!":
                muted = True
                i += 1
                continue
            if c == "J":
                jump_tick = tick
                i += 1
                continue
            if c == "[":
                close = find_loop_end(mml, i)
                count, k = read_number(mml, close, 2)
                body, slash, saved = i + 1, find_top_slash(mml, i + 1, close), octave
                for rep in range(max(1, count)):
                    octave = saved
                    parse_range(body, slash if rep == count - 1 and slash is not None else close)
                    if stopped:
                        break
                octave = octave_after(mml, body, close, saved, lo)
                i = k + 1
                continue
            if c == "{":
                close = find_brace_end(mml, i)
                start_note, end_note, duration, octave = parse_porta_body(mml, i + 1, close, octave, def_len, def_clocks, clock_c, transpose, lo)
                i = close
                j = skip_space(mml, i, end)
                tied = j < end and mml[j] == "&"
                if tied:
                    i = j
                total_clocks += duration * clock_c // INTERNAL_WHOLE
                if not muted:
                    note_gen += 1
                    porta_clocks = max(1, duration * clock_c // INTERNAL_WHOLE)
                    song.events.append(MusicEvent("porta", tick, duration=duration, note=start_note, value=end_note, part=part, legato=pending_tie, aux=note_gen, params=(porta_clocks,)))
                    if tied:
                        pending_tie = True
                    else:
                        emit_note_tail(duration, end_note, note_gen)
                        remember(end_note, duration)
                        pending_tie = False
                tick += duration
            elif c in "\\¥":
                if i + 1 < end and mml[i + 1] == "=":
                    echo_back, k = read_imm(mml, i + 2, end, 1)
                    echo_drop, i = read_imm(mml, k + 1, end, 4)
                    echo_back, echo_drop = clamp(echo_back, 0, 9), max(0, echo_drop)
                else:
                    emit_echo()
            elif c == "C":
                clock_c, i = read_number(mml, i, clock_c)
                clock_c = max(1, clock_c)
                song.events.append(MusicEvent("clock", tick, value=clock_c, part=part))
            elif c == "T":
                tempo, i = read_number(mml, i, 120)
                song.events.append(MusicEvent("tempo_bpm", tick, value=max(1, tempo), part=part))
            elif c == "t":
                tb, i = read_number(mml, i, 0)
                song.events.append(MusicEvent("tempo_tb", tick, value=clamp(tb, 0, 255), part=part))
            elif c == "o":
                octave, i = read_number(mml, i, octave)
                octave = clamp(octave, lo, 8)
            elif c == "l":
                j = i + 1
                while j < end and mml[j].isspace():
                    j += 1
                if j < end and mml[j] == "%":
                    clocks, k = read_number(mml, j, 0)
                    if k != j:
                        def_clocks, i = max(1, clocks), k
                elif j < end and mml[j].isdigit():
                    def_len, i = read_number(mml, i, def_len)
                    def_clocks = None
            elif c == "q":
                q, i = read_number(mml, i, q)
                q_mode = "q"
            elif c == "Q":
                q_div, i = read_number(mml, i, 8)
                q_div, q_mode = clamp(q_div, 0, 8), "Q"
            elif c == "v" and part == ADPCM_PART and i + 1 < end and mml[i + 1] in "mM":
                bias, i = read_number(mml, i + 1, 0)
                song.events.append(MusicEvent("pcm_vm", tick, value=clamp(bias, 0, 255), part=part))
            elif c == "v" and part == RHYTHM_PART:
                vals, k = [], i
                for n in range(7):
                    val, k = read_imm(mml, k + 1, end, 63 if n == 0 else 31)
                    vals.append(val)
                    if n < 6 and (k + 1 >= end or mml[k + 1] != ","):
                        break
                i = k
                song.events.append(MusicEvent("rhythm_vol", tick, part=part, params=tuple(vals)))
            elif c == "v" and part == ADPCM_PART:
                volume_v, i = read_number(mml, i, volume_v)
                volume_v, vol_mode = clamp(volume_v, 0, 255), "v"
                emit_volume(song, part, tick, vol_mode, volume_v, volume_fine)
            elif c == "v":
                if i + 1 < end and mml[i + 1] == "%":
                    volume_fine, i = read_number(mml, i + 1, volume_fine)
                    volume_fine, vol_mode = clamp(volume_fine, 0, 127), "V"
                else:
                    volume_v, i = read_number(mml, i, volume_v)
                    volume_v, vol_mode = clamp(volume_v + vol_bias, 0, 15), "v"
                emit_volume(song, part, tick, vol_mode, volume_v, volume_fine)
            elif c == "V":
                vol_bias, i = read_signed_number(mml, i, vol_bias)
            elif c == "s" and part in SSG_PARTS:
                shape, i = read_number(mml, i, 0)
                song.events.append(MusicEvent("hw_env", tick, value=clamp(shape, 0, 15), part=part))
            elif c == "s" and part in FM_PARTS:
                shuffle, i = read_signed_number(mml, i, shuffle)
            elif c == "m" and part in SSG_PARTS:
                period, i = read_number(mml, i, 0)
                song.events.append(MusicEvent("hw_period", tick, value=clamp(period, 0, 65535), part=part))
            elif c == ")":
                n, i = read_number(mml, i, 1)
                apply_volume_delta(n)
            elif c == "(":
                n, i = read_number(mml, i, 1)
                apply_volume_delta(-n)
            elif c == "@" and part in FM_PARTS:
                voice, i = read_number(mml, i, 1)
                song.events.append(MusicEvent("voice", tick, value=voice, part=part))
            elif c == "@" and part in SSG_PARTS:
                no, i = read_number(mml, i, 0)
                if not 0 <= no <= 255:
                    raise ValueError(f"SSG音色 @{no} は 0～255 です")
                if no not in song.ssg_presets:
                    raise ValueError(f"SSG音色 @{no} が定義されていません")
                song.events.append(MusicEvent("ssg_preset", tick, value=no, part=part))
            elif c == "@" and part == RHYTHM_PART:
                rhythm_mask, i = read_number(mml, i, rhythm_mask)
                rhythm_mask &= 0x3F
                song.events.append(MusicEvent("rhythm_mask", tick, value=rhythm_mask, part=part))
            elif c == "@" and part == ADPCM_PART:
                no, i = read_number(mml, i, 1)
                if not 1 <= no <= 32:
                    raise ValueError(f"PCM @{no} は 1～32 です")
                song.events.append(MusicEvent("pcm", tick, value=no, part=part))
            elif c == "p" and part == RHYTHM_PART:
                pan, i = read_imm(mml, i + 1, end, 3)
                song.events.append(MusicEvent("rhythm_pan", tick, value=pan & 0xFF, part=part))
            elif c == "p" and part == ADPCM_PART:
                pan, i = read_number(mml, i, 3)
                song.events.append(MusicEvent("pcm_pan", tick, value=clamp(pan, 0, 3), part=part))
            elif c == "p" and part in FM_PARTS:
                pan, i = read_number(mml, i, 3)
                song.events.append(MusicEvent("pan", tick, value=pan, part=part))
            elif c == "P" and part in SSG_PARTS:
                mixer, i = read_number(mml, i, mixer)
                song.events.append(MusicEvent("mixer", tick, value=clamp(mixer, 0, 3), part=part))
            elif c == "w" and part in SSG_PARTS:
                noise, i = read_number(mml, i, noise)
                song.events.append(MusicEvent("noise", tick, value=clamp(noise, 0, 31), part=part))
            elif c == "E" and part in SSG_PARTS:
                al, k = read_imm(mml, i + 1, end, 255)
                ar, k = read_imm(mml, k + 1, end, 255)
                dr, k = read_imm(mml, k + 1, end, 255)
                sl, k = read_imm(mml, k + 1, end, 255)
                sr, k = read_imm(mml, k + 1, end, 0)
                rr, i = read_imm(mml, k + 1, end, 255)
                song.events.append(MusicEvent("ssg_env", tick, part=part, params=(al, ar, dr, sl, sr, rr)))
            elif c == "D":
                detune, i = read_detune(mml, i, detune)
                song.events.append(MusicEvent("detune", tick, value=detune, part=part))
            elif c == "K":
                transpose, i = read_signed_number(mml, i, transpose)
                transpose = clamp(transpose, -128, 128)
            elif c == "k":
                delta, i = read_signed_number(mml, i, 0)
                transpose = clamp(transpose + delta, -128, 128)
            elif c == "L":
                if song.loop_tick is not None:
                    raise ValueError("L は1つだけです")
                song.loop_tick = tick
                song.events.append(MusicEvent("loop", tick, part=part))
            elif c == "S" and part == "C":
                op4, k = read_imm(mml, i + 1, end, 0)
                op3, k = read_imm(mml, k + 1, end, 0)
                op1, k = read_imm(mml, k + 1, end, 0)
                op2, i = read_imm(mml, k + 1, end, 0)
                song.events.append(MusicEvent("slot_dt", tick, duration=op1, note=op4, value=op3, aux=op2, part=part))
            elif c == "M" and part in MOD_PARTS:
                nxt = mml[i + 1] if i + 1 < end else ""
                if nxt in "Ff":
                    n, i = read_imm(mml, i + 2, end, 1)
                    lfo_on = n != 0
                elif nxt in "Ww":
                    lfo_delay, i = read_imm(mml, i + 2, end, lfo_delay)
                elif nxt in "Cc":
                    lfo_step, i = read_imm(mml, i + 2, end, lfo_step)
                    lfo_step = max(1, lfo_step)
                elif nxt in "Ll":
                    lfo_depth, i = read_imm(mml, i + 2, end, lfo_depth)
                elif nxt in "Dd":
                    lfo_count, i = read_imm(mml, i + 2, end, lfo_count)
                    lfo_count = max(0, lfo_count)
                else:
                    lfo_delay, k = read_imm(mml, i + 1, end, 0)
                    lfo_step, k = read_imm(mml, k + 1, end, 1)
                    lfo_depth, k = read_imm(mml, k + 1, end, 0)
                    lfo_count, i = read_imm(mml, k + 1, end, 0)
                    lfo_step, lfo_count, lfo_on = max(1, lfo_step), max(0, lfo_count), True
                song.events.append(MusicEvent("lfo", tick, duration=max(1, lfo_step), note=lfo_delay, value=lfo_depth, part=part, legato=lfo_on, aux=max(0, lfo_count)))
            elif c == "N" and part in MOD_PARTS:
                nxt = mml[i + 1] if i + 1 < end else ""
                if nxt in "Ff":
                    n, i = read_imm(mml, i + 2, end, 1)
                    trem_on = n != 0
                elif nxt in "Ww":
                    trem_delay, i = read_imm(mml, i + 2, end, trem_delay)
                elif nxt in "Cc":
                    trem_step, i = read_imm(mml, i + 2, end, trem_step)
                    trem_step = max(1, trem_step)
                elif nxt in "Ll":
                    trem_depth, i = read_imm(mml, i + 2, end, trem_depth)
                elif nxt in "Dd":
                    trem_count, i = read_imm(mml, i + 2, end, trem_count)
                    trem_count = max(0, trem_count)
                else:
                    trem_delay, k = read_imm(mml, i + 1, end, 0)
                    trem_step, k = read_imm(mml, k + 1, end, 1)
                    trem_depth, k = read_imm(mml, k + 1, end, 0)
                    trem_count, i = read_imm(mml, k + 1, end, 0)
                    trem_step, trem_count, trem_on = max(1, trem_step), max(0, trem_count), True
                song.events.append(MusicEvent("trem", tick, duration=max(1, trem_step), note=trem_delay, value=trem_depth, part=part, legato=trem_on, aux=max(0, trem_count)))
            elif c == "R":
                nxt = mml[i + 1] if i + 1 < end else ""
                if nxt in "Ff":
                    n, i = read_imm(mml, i + 2, end, 1)
                    rev_on = n != 0
                elif nxt in "Mm":
                    n, i = read_imm(mml, i + 2, end, 1)
                    rev_mode = 0 if n == 0 else 1
                else:
                    rev_val, i = read_imm(mml, i + 1, end, rev_val)
                    rev_on = True
                song.events.append(MusicEvent("reverb", tick, note=rev_mode, value=rev_val, part=part, legato=rev_on))
            elif c == "H" and part in FM_PARTS:
                nxt = mml[i + 1] if i + 1 < end else ""
                if nxt in "Ff":
                    n, i = read_imm(mml, i + 2, end, 1)
                    song.lfo_enable = 1 if n else 0
                    song.events.append(MusicEvent("lfo22", tick, value=lfo22_value(song.lfo_enable, song.lfo_speed), part=part))
                elif nxt in "Ww":
                    n, i = read_imm(mml, i + 2, end, 0)
                    song.lfo_speed = clamp(n, 0, 7)
                    song.events.append(MusicEvent("lfo22", tick, value=lfo22_value(song.lfo_enable, song.lfo_speed), part=part))
                elif nxt in "Pp":
                    n, i = read_imm(mml, i + 2, end, 0)
                    pms = clamp(n, 0, 7)
                    song.events.append(MusicEvent("lfo_ch", tick, note=pms, value=ams, part=part))
                elif nxt in "Aa":
                    n, i = read_imm(mml, i + 2, end, 0)
                    ams = clamp(n, 0, 3)
                    song.events.append(MusicEvent("lfo_ch", tick, note=pms, value=ams, part=part))
                elif nxt in "Mm":
                    slot, k = read_imm(mml, i + 2, end, 1)
                    on, i = read_imm(mml, k + 1, end, 1)
                    slot_i = clamp(slot, 1, 4) - 1
                    amon[slot_i] = 1 if on else 0
                    song.events.append(MusicEvent("lfo_amon", tick, note=slot_i, value=amon[slot_i], part=part))
                else:
                    speed, k = read_imm(mml, i + 1, end, 0)
                    pm, k = read_imm(mml, k + 1, end, 0)
                    am, i = read_imm(mml, k + 1, end, 0)
                    song.lfo_enable, song.lfo_speed = 1, clamp(speed, 0, 7)
                    pms, ams = clamp(pm, 0, 7), clamp(am, 0, 3)
                    song.events.append(MusicEvent("lfo22", tick, value=lfo22_value(1, song.lfo_speed), part=part))
                    song.events.append(MusicEvent("lfo_ch", tick, note=pms, value=ams, part=part))
            elif c == "y":
                tag = mml[i + 1:i + 3].upper()
                if part in FM_PARTS and tag in Y_SLOT_REGS:
                    slot, k = read_imm(mml, i + 3, end, 1)
                    data, k = read_imm(mml, k + 1, end, 0)
                    slot_i = clamp(slot, 1, 4) - 1
                    if tag == "DR":
                        amon[slot_i] = 1 if data & 0x80 else 0
                    reg = Y_SLOT_REGS[tag] + SLOT_MAP[part][slot_i]
                    song.events.append(MusicEvent("reg", tick, duration=y_port(part, reg), note=reg, value=data & 0xFF, part=part))
                    i = k
                else:
                    reg, k = read_imm(mml, i + 1, end, 0)
                    data, k = read_imm(mml, k + 1, end, 0)
                    if part == ADPCM_PART:
                        port = 1
                    elif part in FM_PARTS:
                        port = y_port(part, reg & 0xFF)
                    else:
                        port = 0
                    song.events.append(MusicEvent("reg", tick, duration=port, note=reg & 0xFF, value=data & 0xFF, part=part))
                    i = k
            elif c == ">":
                octave = clamp(octave + 1, lo, 8)
            elif c == "<":
                octave = clamp(octave - 1, lo, 8)
            elif c == "r" or c.lower() in NOTE_MAP:
                acc = 1 if i + 1 < end and mml[i + 1] == "+" else -1 if i + 1 < end and mml[i + 1] == "-" else 0
                if acc:
                    i += 1
                duration, i = parse_duration_spec(mml, i, end, def_len, def_clocks, clock_c)
                j = skip_space(mml, i, end)
                tied = j < end and mml[j] == "&"
                if tied:
                    i = j
                total_clocks += duration * clock_c // INTERNAL_WHOLE
                if c == "r" or muted:
                    if pending_tie and not (rev_on and rev_mode == 0):
                        song.events.append(MusicEvent("note_off", tick, part=part, aux=note_gen))
                        pending_tie = False
                    song.events.append(MusicEvent("rest", tick, duration=duration, part=part))
                else:
                    note = 0 if part == RHYTHM_PART else note_index(octave, c.lower(), acc, transpose)
                    if pending_tie and note == tie_note and part != RHYTHM_PART:
                        tie_dur += duration
                        if tied:
                            pending_tie = True
                        else:
                            n_before = len(song.events)
                            emit_note_tail(tie_dur, note, tie_gen)
                            # note_off must be measured from the first note, not this one
                            # (今回 emit_note_tail が追加したイベントだけを対象にする)
                            off = [e for e in song.events[n_before:] if e.part == part and e.kind in ("note_off", "rev_tail") and e.aux == tie_gen]
                            for e in off[-2:]:
                                e.tick = tie_origin + (e.tick - tick)
                            remember(note, tie_dur)
                            pending_tie = False
                            tie_note = None
                    else:
                        gen = shuffled_on(note, duration, pending_tie)
                        if tied:
                            pending_tie = True
                            tie_note, tie_origin, tie_dur, tie_gen = note, tick, duration, gen
                        else:
                            emit_note_tail(duration, note, gen)
                            remember(note, duration)
                            tie_note = None
                tick += duration
            i += 1

    parse_range(0, len(mml))
    if jump_tick is not None:
        song.events = [
            e if e.part != part else replace(e, tick=e.tick - jump_tick)
            for e in song.events
            if e.part != part or e.tick >= jump_tick
        ]
        tick -= jump_tick
        total_clocks = max(0, total_clocks - jump_tick * clock_c // INTERNAL_WHOLE)
    state.tick, state.octave = tick, octave
    state.def_len, state.def_clocks = def_len, def_clocks
    state.q, state.q_mode, state.q_div = q, q_mode, q_div
    state.transpose, state.clock_c, state.total_clocks = transpose, clock_c, total_clocks
    state.vol_mode, state.volume_v, state.volume_fine = vol_mode, volume_v, volume_fine
    state.vol_bias, state.shuffle, state.detune = vol_bias, shuffle, detune
    state.muted, state.stopped = muted, stopped
    state.pms, state.ams, state.amon = pms, ams, amon
    state.pending_tie = pending_tie
    state.lfo_on, state.lfo_delay, state.lfo_step = lfo_on, lfo_delay, lfo_step
    state.lfo_depth, state.lfo_count = lfo_depth, lfo_count
    state.trem_on, state.trem_delay, state.trem_step = trem_on, trem_delay, trem_step
    state.trem_depth, state.trem_count = trem_depth, trem_count
    state.rev_on, state.rev_val, state.rev_mode = rev_on, rev_val, rev_mode
    state.echo_back, state.echo_drop = echo_back, echo_drop
    state.mixer, state.noise, state.rhythm_mask = mixer, noise, rhythm_mask
    state.jump_tick, state.note_hist = jump_tick, note_hist


def take_ssg_preset(lines, i, no):
    buf = []
    first = strip_comment(lines[i])
    brace = first.find("{")
    buf.append(first[brace + 1:])
    if "}" in buf[0]:
        body, _, _ = buf[0].partition("}")
        return parse_ssg_preset(no, body), i + 1
    i += 1
    while i < len(lines):
        row = strip_comment(lines[i])
        if "}" in row:
            body, _, _ = row.partition("}")
            buf.append(body)
            return parse_ssg_preset(no, "".join(buf)), i + 1
        buf.append(row)
        i += 1
    raise ValueError(f"SSG音色 @{no} の '}}' がありません")


def parse_mml(text: str, folder: Path | None = None) -> Song:
    song = Song()
    song.ssg_presets = {no: parse_ssg_preset(no, body) for no, body in SSG_BUILTIN.items()}
    lines, mml_lines, i = text.splitlines(), [], 0
    while i < len(lines):
        stripped = strip_comment(lines[i]).strip()
        macro = re.match(r"#\s*\*\s*(\d+)\s*\{(.*)", stripped)
        if macro:
            no, body = int(macro.group(1)), macro.group(2)
            if "}" in body:
                song.macros[no] = body.split("}", 1)[0]
                i += 1
                continue
            i += 1
            while i < len(lines):
                row = strip_comment(lines[i])
                if "}" in row:
                    body += row.split("}", 1)[0]
                    i += 1
                    break
                body += row
                i += 1
            song.macros[no] = body
            continue
        preset = re.fullmatch(r"@\s*(\d+)\s*=\s*\{.*", stripped)
        if preset:
            no = int(preset.group(1))
            if not 0 <= no <= 255:
                raise ValueError(f"SSG音色 @{no} は 0～255 です")
            song.ssg_presets[no], i = take_ssg_preset(lines, i, no)
            continue
        if re.fullmatch(r"@\s*\d+", stripped):
            voice_no = int(re.search(r"\d+", stripped).group())
            voice, i = parse_voice_block(lines, i + 1, voice_no)
            song.voices[voice_no] = voice
            continue
        mml_lines.append(lines[i])
        i += 1
    states, pending = {}, {}
    for raw in mml_lines:
        line = strip_comment(raw).strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("#chip"):
            parts = line.split()
            song.chip = parts[1].lower() if len(parts) > 1 else "ym2608"
            if song.chip not in ("ym2608", "ay8910", "ym2149"):
                raise ValueError("対応チップは ym2608 / ay8910 / ym2149 です")
            song.chip_clock = int(parts[2]) if len(parts) > 2 else (YM2608_CLOCK if song.chip == "ym2608" else AY_CLOCK)
            continue
        if low.startswith("#title"):
            song.title = line[6:].strip()
            continue
        if low.startswith("#voice"):
            song.voice_file = line.split(maxsplit=1)[1].strip() if len(line.split()) > 1 else ""
            continue
        if low.startswith("#pcmlist"):
            song.pcm_list = line.split(maxsplit=1)[1] if len(line.split()) > 1 else ""
            continue
        if low.startswith("#pcm"):
            song.pcm_file = line.split(maxsplit=1)[1] if len(line.split()) > 1 else ""
            continue
        part = line[0].upper()
        if part not in ALL_PARTS or len(line) < 2:
            continue
        if song.chip != "ym2608" and part not in SSG_PARTS:
            continue
        body = pending.get(part, "") + line[1:].strip()
        if body.count("[") > body.count("]"):
            pending[part] = body
            continue
        pending.pop(part, None)
        state = states.setdefault(part, PartState(octave=1 if part == ADPCM_PART else 6, volume_v=200 if part == ADPCM_PART else 15))
        parse_part_mml(song, part, body, state)
    if pending:
        part = next(iter(pending))
        raise ValueError(f"{part}: ループの ']' がありません")
    for part, st in states.items():
        song.part_clocks[part] = st.total_clocks
        if st.pending_tie or st.rev_on:
            song.events.append(MusicEvent("note_off", st.tick, part=part, aux=10**9))
    end = max((s.tick for s in states.values()), default=0)
    if end:
        song.events.append(MusicEvent("rest", end, part="A"))
    if song.voice_file:
        for no, voice in load_voice_file(folder or Path("."), song.voice_file).items():
            song.voices.setdefault(no, voice)
    for ev in song.events:
        if ev.kind == "voice" and ev.value not in song.voices:
            raise ValueError(f"{ev.part}: FM音色 @{ev.value} が定義されていません")
    if song.pcm_file or song.pcm_list:
        song.pcm_slots, song.pcm_rom = load_song_pcm(folder or Path("."), song.pcm_file, song.pcm_list)
    return song
