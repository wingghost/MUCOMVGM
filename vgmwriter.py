from __future__ import annotations

import struct

SAMPLE_RATE = 44100
YM2608_CLOCK = 7987200
AY_CLOCK = 2000000
INTERNAL_WHOLE = 768
DEFAULT_C = 128
FREQ_LO = frozenset({0xA0, 0xA1, 0xA2, 0xA8, 0xA9, 0xAA})
FREQ_HI = frozenset({0xA4, 0xA5, 0xA6, 0xAC, 0xAD, 0xAE})
NO_DEDUP_REGS = frozenset({(0, 0x10), (0, 0x28), (0, 0x0D), (1, 0x00)})


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def ticks_to_samples(ticks: int, tick_rate: int, tempo: int, tempo_mode: str, timer_b: int, clock_c: int) -> int:
    if ticks <= 0:
        return 0
    clocks = ticks * max(1, clock_c) / INTERNAL_WHOLE
    if tempo_mode == "t":
        step = SAMPLE_RATE * 1152 * max(1, 256 - timer_b) / (YM2608_CLOCK / 2)
    else:
        step = SAMPLE_RATE * 60 / (max(1, tempo) * max(1, clock_c) / 4)
    return max(0, int(round(clocks * step)))


class VgmWriter:
    def __init__(self, chip: str, clock: int):
        self.chip = chip
        self.clock = clock
        self.data = bytearray()
        self.samples = 0
        self.loop_offset = None
        self.loop_samples = None
        self.reg_cache = {}
        self.freq_hi = {}

    def write_wait(self, samples: int) -> None:
        left = max(0, int(samples))
        self.samples += left
        while left > 0:
            if left == 735:
                self.data.append(0x62)
                left = 0
            elif left == 882:
                self.data.append(0x63)
                left = 0
            elif left <= 16:
                self.data.append(0x6F + left)
                left = 0
            else:
                n = min(left, 65535)
                self.data += bytes((0x61, n & 0xFF, (n >> 8) & 0xFF))
                left -= n

    def write_ym2608(self, port: int, reg: int, value: int) -> None:
        port, reg, value = 1 if port else 0, reg & 0xFF, value & 0xFF
        key = (port, reg)
        cmd = 0x57 if port else 0x56
        if reg in FREQ_HI:
            self.freq_hi[key] = value
            return
        if reg in FREQ_LO:
            hi = self.freq_hi.get((port, reg + 4))
            if hi is None:
                self.reg_cache.pop(key, None)
            else:
                if self.reg_cache.get(key) == (hi, value):
                    return
                self.reg_cache[key] = (hi, value)
                self.data += bytes((cmd, reg + 4, hi))
            self.data += bytes((cmd, reg, value))
            return
        if key not in NO_DEDUP_REGS:
            if self.reg_cache.get(key) == value:
                return
            self.reg_cache[key] = value
        self.data += bytes((cmd, reg, value))

    def write_ssg(self, reg: int, value: int) -> None:
        if self.chip == "ym2608":
            self.write_ym2608(0, reg & 0x0F, value & 0xFF)
            return
        reg, value = reg & 0xFF, value & 0xFF
        if reg != 0x0D:
            key = (2, reg)
            if self.reg_cache.get(key) == value:
                return
            self.reg_cache[key] = value
        self.data += bytes((0xA0, reg, value))

    def mark_loop(self) -> None:
        if self.loop_offset is None:
            self.loop_offset = len(self.data)
            self.loop_samples = self.samples
            self.reg_cache.clear()

    def write_end(self) -> None:
        self.data.append(0x66)

    def build(self) -> bytes:
        header = bytearray(256)
        header[0:4] = b"Vgm "
        header[8:12] = struct.pack("<I", 0x171)
        if self.chip == "ym2608":
            header[0x48:0x4C] = struct.pack("<I", self.clock)
        else:
            header[0x74:0x78] = struct.pack("<I", self.clock)
        header[0x18:0x1C] = struct.pack("<I", self.samples)
        header[0x24:0x28] = struct.pack("<I", SAMPLE_RATE)
        header[0x34:0x38] = struct.pack("<I", 256 - 0x34)
        if self.loop_offset is not None:
            header[0x1C:0x20] = struct.pack("<I", 256 + self.loop_offset - 0x1C)
            header[0x20:0x24] = struct.pack("<I", self.samples - (self.loop_samples or 0))
        header[0x04:0x08] = struct.pack("<I", 256 + len(self.data) - 4)
        return bytes(header) + bytes(self.data)
