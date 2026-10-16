from __future__ import annotations

from chips.ay8910 import SSG_PARTS
from chips.opn import EXT_PARTS, FM3_PARTS, FM_PARTS, SLOT_MAP, Y_SLOT_REGS, lfo22_value, y_port
from messages import MMLError
from vgmwriter import INTERNAL_WHOLE, clamp

from .model import ADPCM_PART, NOTE_MAP, RHYTHM_PART, MOD_PARTS, MusicEvent
from .scan import (
    expand_macros, find_brace_end, find_loop_end, find_top_slash, norm_mod_count, octave_after,
    read_detune, read_imm, read_number, read_signed_number, skip_space, static_state_after, strip_comment,
)
from .timing import (
    clocks_to_internal, emit_volume, gate_duration, note_duration, note_index, parse_duration_spec,
)


def parse_porta_body(mml, start, end, octave, def_len, def_clocks, clock_c, transpose, lo, part, source_pos):
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
        line_no, _ = source_pos(start)
        raise MMLError("porta.no_note", part=part, line=line_no + 1)
    return notes[0], notes[-1], duration or note_duration(def_len, False), octave


def parse_part_mml(song, part, mml, state, line_map=None):
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
        if rev_on and (part in FM_PARTS or part in SSG_PARTS):
            song.events.append(MusicEvent("rev_tail", tick + gate, part=part))
            if rev_mode == 1:
                song.events.append(MusicEvent("note_off", tick + max(gate, duration), note=note, part=part, aux=gen))
        else:
            song.events.append(MusicEvent("note_off", tick + gate, note=note, part=part, aux=gen))
        pending_tie = False

    def source_pos(i):
        # 連結したパートの文字位置 i が、ファイルの何番目の行の何文字目か
        if not line_map:
            return (0, i)
        for end, orig_line, start in line_map:
            if i < end:
                return (orig_line, i - start)
        return (line_map[-1][1], i - line_map[-1][2])

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
        song.events.append(MusicEvent("note_on", on_at, duration=duration, note=note, part=part, legato=legato, aux=note_gen, value=state.ex_mask if part in FM3_PARTS else 0))
        if part in FM3_PARTS:
            state.spans.append([tick, tick + duration, state.ex_mask])
        return note_gen

    def emit_echo():
        nonlocal tick, total_clocks
        if echo_back <= 0 or echo_back > len(note_hist):
            note = note_index(1, "c", 0, 0)
            duration = clocks_to_internal(def_clocks, clock_c) if def_clocks else note_duration(def_len, False)
        else:
            note, duration = note_hist[-echo_back]
        if part in EXT_PARTS and state.ex_mask == 0xF:
            total_clocks += duration * clock_c // INTERNAL_WHOLE
            tick += duration
            state.marks.append((tick, total_clocks))
            return
        apply_volume_delta(-max(0, echo_drop))
        gen = shuffled_on(note, duration, False)
        emit_note_tail(duration, note, gen)
        total_clocks += duration * clock_c // INTERNAL_WHOLE
        tick += duration
        state.marks.append((tick, total_clocks))
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
                song.jump_tick = max(song.jump_tick, tick)
                i += 1
                continue
            if c == "[":
                close = find_loop_end(mml, i)
                count, k = read_number(mml, close, 2)
                body, slash = i + 1, find_top_slash(mml, i + 1, close)
                # オクターブ・音長(l)・移調(K,k)・音量の相対変化(V)は、コンパイル時に決まる設定。
                # ループの本体は1回だけコンパイルされて繰り返されるので、繰り返しのたびに、ループ先頭の値に戻す。
                saved = (octave, def_len, def_clocks, transpose, vol_bias)
                for rep in range(max(1, count)):
                    octave, def_len, def_clocks, transpose, vol_bias = saved
                    parse_range(body, slash if rep == count - 1 and slash is not None else close)
                    if stopped:
                        break
                if slash is not None and count >= 1:
                    def_len, def_clocks, transpose, vol_bias = static_state_after(mml, slash + 1, close, def_len, def_clocks, transpose, vol_bias)
                octave = octave_after(mml, body, close, saved[0], lo)
                i = k + 1
                continue
            if c == "{":
                close = find_brace_end(mml, i)
                start_note, end_note, duration, octave = parse_porta_body(mml, i + 1, close, octave, def_len, def_clocks, clock_c, transpose, lo, part, source_pos)
                i = close
                j = skip_space(mml, i, end)
                tied = j < end and mml[j] == "&"
                if tied:
                    i = j
                total_clocks += duration * clock_c // INTERNAL_WHOLE
                if not muted and not (part in EXT_PARTS and state.ex_mask == 0xF):
                    note_gen += 1
                    if part in FM3_PARTS:
                        state.spans.append([tick, tick + duration, state.ex_mask])
                    porta_clocks = max(1, duration * clock_c // INTERNAL_WHOLE)
                    song.events.append(MusicEvent("porta", tick, duration=duration, note=start_note, value=end_note, part=part, legato=pending_tie, aux=note_gen, params=(porta_clocks,)))
                    if tied:
                        pending_tie = True
                    else:
                        emit_note_tail(duration, end_note, note_gen)
                        remember(end_note, duration)
                        pending_tie = False
                tick += duration
                state.marks.append((tick, total_clocks))
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
                if part not in EXT_PARTS:
                    line_no, _ = source_pos(i)
                    song.events.append(MusicEvent("voice", tick, value=voice, part=part, aux=line_no + 1))
            elif c == "@" and part in SSG_PARTS:
                no, i = read_number(mml, i, 0)
                if not 0 <= no <= 255:
                    line_no, _ = source_pos(i)
                    raise MMLError("ssg.range", part=part, line=line_no + 1, no=no)
                if no not in song.ssg_presets:
                    line_no, _ = source_pos(i)
                    raise MMLError("ssg.undefined", part=part, line=line_no + 1, no=no)
                song.events.append(MusicEvent("ssg_preset", tick, value=no, part=part))
            elif c == "@" and part == RHYTHM_PART:
                rhythm_mask, i = read_number(mml, i, rhythm_mask)
                rhythm_mask &= 0x3F
                song.events.append(MusicEvent("rhythm_mask", tick, value=rhythm_mask, part=part))
            elif c == "@" and part == ADPCM_PART:
                no, i = read_number(mml, i, 1)
                if not 1 <= no <= 32:
                    line_no, _ = source_pos(i)
                    raise MMLError("pcm.range", part=part, line=line_no + 1, no=no)
                song.events.append(MusicEvent("pcm", tick, value=no, part=part))
            elif c == "p" and part == RHYTHM_PART:
                pan, i = read_imm(mml, i + 1, end, 3)
                song.events.append(MusicEvent("rhythm_pan", tick, value=pan & 0xFF, part=part))
            elif c == "p" and part == ADPCM_PART:
                pan, i = read_number(mml, i, 3)
                song.events.append(MusicEvent("pcm_pan", tick, value=clamp(pan, 0, 3), part=part))
            elif c == "p" and part in FM_PARTS:
                pan, i = read_number(mml, i, 3)
                if part not in EXT_PARTS:
                    song.events.append(MusicEvent("pan", tick, value=pan, part=part))
            elif c == "P" and part in SSG_PARTS:
                mixer, i = read_number(mml, i, mixer)
                song.events.append(MusicEvent("mixer", tick, value=clamp(mixer, 0, 3), part=part))
            elif c == "w" and part in SSG_PARTS:
                noise, i = read_number(mml, i, noise)
                song.events.append(MusicEvent("noise", tick, value=clamp(noise, 0, 31), part=part))
            elif c == "E" and i + 1 < end and mml[i + 1] == "X":
                line_no, _ = source_pos(i)
                if part not in FM3_PARTS:
                    raise MMLError("ex.part", part=part, line=line_no + 1)
                k = i + 2
                while k < end and mml[k] in "0123456789":
                    k += 1
                digits = mml[i + 2:k]
                if not digits or any(d not in "1234" for d in digits):
                    raise MMLError("ex.digits", part=part, line=line_no + 1)
                state.ex_mask = sum(1 << (int(d) - 1) for d in set(digits))
                song.events.append(MusicEvent("ex", tick, value=state.ex_mask, part=part))
                i = k - 1
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
                # L が複数あるときは、ファイルの中で最初に書かれたものだけが有効 (parse_mml で選ぶ)
                loop_ev = MusicEvent("loop", tick, part=part)
                song.events.append(loop_ev)
                song.loop_candidates.append((source_pos(i), tick, loop_ev))
            elif c == "S" and part in EXT_PARTS:
                k = i
                for _ in range(3):
                    _, k = read_imm(mml, k + 1, end, 0)
                _, i = read_imm(mml, k + 1, end, 0)
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
                    lfo_count = norm_mod_count(lfo_count)
                else:
                    lfo_delay, k = read_imm(mml, i + 1, end, 0)
                    lfo_step, k = read_imm(mml, k + 1, end, 1)
                    lfo_depth, k = read_imm(mml, k + 1, end, 0)
                    lfo_count, i = read_imm(mml, k + 1, end, 0)
                    lfo_step, lfo_count, lfo_on = max(1, lfo_step), norm_mod_count(lfo_count), True
                song.events.append(MusicEvent("lfo", tick, duration=max(1, lfo_step), note=lfo_delay, value=lfo_depth, part=part, legato=lfo_on, aux=lfo_count))
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
                    trem_count = norm_mod_count(trem_count)
                else:
                    trem_delay, k = read_imm(mml, i + 1, end, 0)
                    trem_step, k = read_imm(mml, k + 1, end, 1)
                    trem_depth, k = read_imm(mml, k + 1, end, 0)
                    trem_count, i = read_imm(mml, k + 1, end, 0)
                    trem_step, trem_count, trem_on = max(1, trem_step), norm_mod_count(trem_count), True
                song.events.append(MusicEvent("trem", tick, duration=max(1, trem_step), note=trem_delay, value=trem_depth, part=part, legato=trem_on, aux=trem_count))
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
            elif c == "H" and part in EXT_PARTS:
                nxt = mml[i + 1] if i + 1 < end else ""
                if nxt in "FfWwPpAa":
                    _, i = read_imm(mml, i + 2, end, 0)
                elif nxt in "Mm":
                    _, k = read_imm(mml, i + 2, end, 1)
                    _, i = read_imm(mml, k + 1, end, 1)
                else:
                    _, k = read_imm(mml, i + 1, end, 0)
                    _, k = read_imm(mml, k + 1, end, 0)
                    _, i = read_imm(mml, k + 1, end, 0)
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
                    data, k = read_imm(mml, k + 1, end, 0, 2)
                    slot_i = clamp(slot, 1, 4) - 1
                    if tag == "DR":
                        amon[slot_i] = 1 if data & 0x80 else 0
                    reg = Y_SLOT_REGS[tag] + SLOT_MAP[part][slot_i]
                    song.events.append(MusicEvent("reg", tick, duration=y_port(part, reg), note=reg, value=data & 0xFF, part=part))
                    i = k
                else:
                    reg, k = read_imm(mml, i + 1, end, 0)
                    data, k = read_imm(mml, k + 1, end, 0, 2)
                    if not 0 <= reg <= 0x1FF:
                        line_no, _ = source_pos(i)
                        raise MMLError("y.reg_range", part=part, line=line_no + 1)
                    song.events.append(MusicEvent("reg", tick, duration=1 if reg >= 0x100 else 0, note=reg & 0xFF, value=data & 0xFF, part=part))
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
                if c == "r" or muted or (part in EXT_PARTS and state.ex_mask == 0xF):
                    if pending_tie and not (rev_on and rev_mode == 0):
                        song.events.append(MusicEvent("note_off", tick, part=part, aux=note_gen))
                        pending_tie = False
                    song.events.append(MusicEvent("rest", tick, duration=duration, part=part))
                else:
                    note = 0 if part == RHYTHM_PART else note_index(octave, c.lower(), acc, transpose)
                    if pending_tie and note == tie_note and part != RHYTHM_PART:
                        tie_dur += duration
                        if part in FM3_PARTS and state.spans:
                            state.spans[-1][1] = tie_origin + tie_dur
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
                state.marks.append((tick, total_clocks))
            i += 1

    parse_range(0, len(mml))
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
