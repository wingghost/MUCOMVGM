from __future__ import annotations

from pathlib import Path

from chips.opn import pack_voice
from messages import MMLError
from vgmwriter import clamp

from .model import SsgPreset
from .scan import norm_mod_count, read_imm, strip_comment


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
    raise MMLError("voice.rows_short")


def parse_voice_block(lines, start, voice_no):
    header, i = next_data_line(lines, start)
    nums = parse_nums(strip_comment(header))
    if len(nums) < 2:
        raise MMLError("voice.need_fbal", no=voice_no)
    ops = []
    for n in range(4):
        row, i = next_data_line(lines, i)
        vals = parse_nums(strip_comment(row))
        if len(vals) < 9:
            raise MMLError("voice.op_params", no=voice_no, op=n + 1)
        ops.append(vals[:10])
    return pack_voice(nums[0], nums[1], ops), i


VOICE_DAT_SIZE = 32
VOICE_DAT_REG_ORDER = (0, 2, 1, 3)


def parse_voice_dat(data: bytes) -> dict[int, tuple]:
    # 1音色32バイト: [0]=未使用, [1..25]=レジスタ順の25バイト(op1,op3,op2,op4), [26..31]=音色名
    if len(data) < VOICE_DAT_SIZE:
        raise MMLError("voice.dat_small")
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
        raise MMLError("voice.file_missing", path=path)
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
            preset.lfo = (delay, max(1, step), depth, norm_mod_count(count))
        elif c == "N":
            delay, k = read_imm(body, i + 1, end, 0)
            step, k = read_imm(body, k + 1, end, 1)
            depth, k = read_imm(body, k + 1, end, 0)
            count, i = read_imm(body, k + 1, end, 0)
            preset.trem = (delay, max(1, step), depth, norm_mod_count(count))
        else:
            raise MMLError("ssg.bad_cmd", no=no, c=c)
        i += 1
    return preset


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
    raise MMLError("ssg.unclosed_brace", no=no)
