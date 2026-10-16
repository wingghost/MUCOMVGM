from __future__ import annotations

from chips.opn import Y_SLOT_REGS
from messages import MMLError
from vgmwriter import clamp


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


def read_imm(text: str, i: int, end: int, fallback: int = 0, max_hex: int | None = None) -> tuple[int, int]:
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
        while k < end and text[k] in "0123456789abcdefABCDEF" and (max_hex is None or k - j < max_hex):
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
        raise MMLError("macro.too_deep")
    out, i = [], 0
    while i < len(text):
        if text[i] == "*":
            no, j = read_number(text, i, -1)
            if no not in macros:
                raise MMLError("macro.undefined", no=no)
            out.append(expand_macros(macros[no], macros, depth + 1))
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def norm_mod_count(n: int) -> int:
    # LFO の回数は 1 バイトのデータ。マイナスは符号なしとして扱う (-1 は 255)
    return n & 0xFF if n < 0 else n


def find_loop_end(text, start):
    depth, j = 1, start + 1
    while j < len(text) and depth:
        depth += 1 if text[j] == "[" else -1 if text[j] == "]" else 0
        j += 1
    if depth:
        raise MMLError("loop.unclosed")
    return j - 1


def find_brace_end(text, start):
    depth, j = 1, start + 1
    while j < len(text) and depth:
        depth += 1 if text[j] == "{" else -1 if text[j] == "}" else 0
        j += 1
    if depth:
        raise MMLError("porta.unclosed")
    return j - 1


def find_top_slash(text, start, end):
    depth = 0
    for j in range(start, end):
        depth += 1 if text[j] == "[" else -1 if text[j] == "]" else 0
        if text[j] == "/" and depth == 0:
            return j
    return None


def static_state_after(text, start, end, def_len, def_clocks, transpose, vol_bias):
    # ループの / より後ろにある l, K, k, V が、ループを抜けたあとの状態に与える影響を調べる
    # (コンパイル時に決まる設定。MUCOM88はループの本体を1回だけコンパイルするため、本体の最後の状態が残る)
    i = start
    while i < end:
        c = text[i]
        if c == "[":
            close = find_loop_end(text, i)
            def_len, def_clocks, transpose, vol_bias = static_state_after(text, i + 1, close, def_len, def_clocks, transpose, vol_bias)
            i = close
        elif c == "{":
            i = find_brace_end(text, i)
        elif c == "y":
            if text[i + 1:i + 3].upper() in Y_SLOT_REGS:
                i += 2
        elif c == "l":
            j = i + 1
            if j < end and text[j] == "%":
                clocks, k = read_number(text, j, 0)
                if k != j:
                    def_clocks, i = max(1, clocks), k
            elif j < end and text[j].isdigit():
                def_len, i = read_number(text, i, def_len)
                def_clocks = None
        elif c == "K":
            transpose, i = read_signed_number(text, i, transpose)
            transpose = clamp(transpose, -128, 128)
        elif c == "k":
            delta, i = read_signed_number(text, i, 0)
            transpose = clamp(transpose + delta, -128, 128)
        elif c == "V":
            vol_bias, i = read_signed_number(text, i, vol_bias)
        i += 1
    return def_len, def_clocks, transpose, vol_bias


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
