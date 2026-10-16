from __future__ import annotations

from vgmwriter import INTERNAL_WHOLE, clamp

from .model import NOTE_MAP, MusicEvent
from .scan import read_number


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
    def with_dots(base, dots):
        extra, add = base, 0
        for _ in range(dots):
            extra //= 2
            add += extra
        return max(1, base + add)

    def one():
        nonlocal i
        explicit = False
        dots = 0
        if i + 1 < end and mml[i + 1] == "%":
            clocks, i = read_number(mml, i + 1, 1)
            base = clocks_to_internal(max(1, clocks), clock_c)
            while i + 1 < end and mml[i + 1] == ".":
                dots += 1
                i += 1
            return with_dots(base, dots)
        if i + 1 < end and mml[i + 1].isdigit():
            length, i = read_number(mml, i, def_len)
            explicit = True
        else:
            length = def_len
        while i + 1 < end and mml[i + 1] == ".":
            dots += 1
            i += 1
        if def_clocks is not None and not explicit:
            return with_dots(clocks_to_internal(def_clocks, clock_c), dots)
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


def ssg_reverb_volume(volume_v, rev_val):
    return clamp((volume_v + rev_val) // 2, 0, 15)


def fine_reverb_volume(volume_fine, rev_val):
    return clamp(((volume_fine + rev_val * 8 + 4) // 2) - 4, 0, 127)
