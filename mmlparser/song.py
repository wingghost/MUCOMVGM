from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from adpcm import load_song_pcm
from chips.ay8910 import SSG_PARTS
from chips.opn import FM3_PARTS
from messages import MMLError
from vgmwriter import AY_CLOCK, YM2608_CLOCK

from .model import ADPCM_PART, ALL_PARTS, ChipInfo, MusicEvent, PartState, Song
from .part import parse_part_mml
from .scan import expand_macros, strip_comment
from .voice import SSG_BUILTIN, load_voice_file, parse_ssg_preset, parse_voice_block, take_ssg_preset


def read_mml_text(path: Path) -> str:
    # UTF-8 (BOM つきも可) で読めなければ、Shift-JIS (cp932) として読む
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp932", errors="replace")


def check_ex_overlap(states: dict) -> None:
    # C/L/M/N の音符(休符を除く)が、時間的に重なり、かつ同じオペレータを担当していたらエラーにする
    spans = sorted((s, e, m, p) for p in FM3_PARTS if p in states for s, e, m in states[p].spans)
    active = []
    for s, e, m, p in spans:
        active = [a for a in active if a[1] > s]
        for s2, e2, m2, p2 in active:
            if p2 != p and m & m2:
                names = sorted((p, p2))
                ops = ",".join(str(i + 1) for i in range(4) if (m & m2) >> i & 1)
                raise MMLError("ex.overlap", a=names[0], b=names[1], ops=ops, tick=s)
        active.append((s, e, m, p))


def apply_jump(song: Song) -> None:
    # J: 一番後ろの J より前の音符・休符を全パートで取り除き、音色・音量などの設定は残したまま、その位置から演奏する。
    # 設定のイベントは時刻をマイナスにして先に実行する (ドライバーはマイナスの時刻では時間を進めない)。
    j = song.jump_tick
    if j <= 0:
        return
    dropped = {(e.part, e.aux) for e in song.events if e.kind in ("note_on", "porta") and e.tick < j}
    events, seen_note = [], set()
    for e in song.events:
        if e.kind in ("note_on", "porta"):
            if e.tick < j:
                continue
            if e.part not in seen_note:
                seen_note.add(e.part)
                if e.legato:
                    e = replace(e, legato=False)
        elif e.kind in ("rest", "rev_tail") and e.tick < j:
            continue
        elif e.kind == "note_off" and (e.tick < j or (e.part, e.aux) in dropped):
            continue
        events.append(replace(e, tick=max(0, e.tick - j)) if e.kind == "loop" else replace(e, tick=e.tick - j))
    song.events = events
    if song.loop_tick is not None:
        song.loop_tick = max(0, song.loop_tick - j)


def clocks_at_tick(marks: list, tick: int) -> int:
    # marks = [(tick, 累計クロック), ...]。tick が音符の途中なら、その音符の中を比例配分する
    prev = marks[0]
    for cur in marks:
        if cur[0] > tick:
            return prev[1] + (cur[1] - prev[1]) * (tick - prev[0]) // (cur[0] - prev[0])
        prev = cur
    return prev[1]


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
                raise MMLError("ssg.range", no=no)
            song.ssg_presets[no], i = take_ssg_preset(lines, i, no)
            continue
        if re.fullmatch(r"@\s*\d+", stripped):
            voice_no = int(re.search(r"\d+", stripped).group())
            voice, i = parse_voice_block(lines, i + 1, voice_no)
            song.voices[voice_no] = voice
            continue
        mml_lines.append((i, lines[i]))
        i += 1
    states, bodies = {}, {}
    for orig_line, raw in mml_lines:
        line = strip_comment(raw).strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("#chip"):
            parts = line.split()
            if len(parts) < 3:
                raise MMLError("chip.need_args")
            try:
                no = int(parts[1])
            except ValueError:
                raise MMLError("chip.bad_no")
            name = parts[2].lower()
            if name not in ("ym2608", "ym2151"):
                raise MMLError("chip.unsupported", name=name)
            clock = int(parts[3]) if len(parts) > 3 else (YM2608_CLOCK if name == "ym2608" else 3579545)
            if not hasattr(song, "chips"):
                song.chips = []
            song.chips.append(type("Chip", (), {"no": no, "name": name, "clock": clock})())
            continue
        if low.startswith("#title"):
            song.title = line[6:].strip()
            continue
        if low.startswith("#composer"):
            song.composer = line[9:].strip()
            continue
        if low.startswith("#album"):
            song.album = line[6:].strip()
            continue
        if low.startswith("#date"):
            song.date = line[5:].strip()
            continue
        if low.startswith("#comment"):
            song.comment = line[8:].strip()
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
        chip_no = 0
        part_line = line
        if ":" in line[:4]:
            prefix, rest = line.split(":", 1)
            if prefix.isdigit():
                chip_no = int(prefix)
                part_line = rest.strip()
        if not part_line:
            continue
        part = part_line[0].upper()
        if part not in ALL_PARTS or len(part_line) < 2:
            continue
        # チップが複数ある場合は番号必須
        chips = getattr(song, "chips", [])
        if len(chips) > 1 and ":" not in line[:4]:
            raise MMLError("chip.need_prefix", part=part)
        bodies.setdefault((chip_no, part), []).append((orig_line, part_line[1:].strip()))
    # 同じパートの行はすべて繋げて、1回で解析する (行の区切りに結果が左右されないようにする)
    for (chip_no, part), entries in bodies.items():
        pieces, line_map, total = [], [], 0
        for orig_line, text in entries:
            piece = "".join(ch for ch in expand_macros(text, song.macros) if not ch.isspace())
            line_map.append((total + len(piece), orig_line, total))
            pieces.append(piece)
            total += len(piece)
        body = "".join(pieces)
        if body.count("[") > body.count("]"):
            raise MMLError("loop.unclosed", part=part)
        state = PartState(octave=1 if part == ADPCM_PART else 6, volume_v=200 if part == ADPCM_PART else 15)
        states[(chip_no, part)] = state
        parse_part_mml(song, part, body, state, line_map)
    if song.loop_candidates:
        first = min(song.loop_candidates, key=lambda cand: cand[0])
        song.loop_tick = first[1]
        dropped = {id(cand[2]) for cand in song.loop_candidates if cand[2] is not first[2]}
        song.events = [e for e in song.events if id(e) not in dropped]
    check_ex_overlap(states)
    for part, st in states.items():
        song.part_clocks[part] = st.total_clocks
        if song.loop_tick is not None:
            song.part_loop_clocks[part] = st.total_clocks - clocks_at_tick(st.marks, max(song.loop_tick, song.jump_tick))
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
            raise MMLError("fm.voice_undefined", part=ev.part, line=ev.aux or None, no=ev.value)
    if song.pcm_file or song.pcm_list:
        song.pcm_slots, song.pcm_rom = load_song_pcm(folder or Path("."), song.pcm_file, song.pcm_list)
    apply_jump(song)
    return song
