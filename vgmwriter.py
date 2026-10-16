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


def is_lockable(port: int, reg: int) -> bool:
    return 0x30 <= reg <= 0x9F or 0xB0 <= reg <= 0xB2 or 0xB4 <= reg <= 0xB6 or (port == 0 and reg <= 0x0C)


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
    def __init__(self, chips=None, clock=None):
        if chips is None:
            self.chips = [{"name": "ym2608", "clock": clock or YM2608_CLOCK}]
        else:
            self.chips = chips
        self.data = bytearray()
        self.samples = 0
        self.loop_offset = None
        self.loop_samples = None
        self.reg_cache = {}
        self.freq_hi = {}
        self.pending_wait = 0
        self.locks = {}
        self.gd3 = {}

    def set_gd3(self, title: str = "", composer: str = "", album: str = "", date: str = "", comment: str = "") -> None:
        self.gd3 = {
            "title": title or "",
            "composer": composer or "",
            "album": album or "",
            "date": date or "",
            "comment": comment or "",
        }

    def _utf16le_z(self, s: str) -> bytes:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        return s.encode("utf-16-le") + b"\x00\x00"

    def clear_lock(self, port: int, reg: int) -> None:
        self.locks.pop((port, reg), None)

    def write_wait(self, samples: int) -> None:
        left = max(0, int(samples))
        self.samples += left
        self.pending_wait += left

    def flush_wait(self) -> None:
        left, self.pending_wait = self.pending_wait, 0
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

    def write_ym2608(self, chip: int, port: int, reg: int, value: int, lock: bool = False) -> None:
        port, reg, value = 1 if port else 0, reg & 0xFF, value & 0xFF
        key = (chip, port, reg)
        if is_lockable(port, reg):
            if lock:
                self.locks[key] = value
            elif key in self.locks:
                value = self.locks[key]
        cmd = 0x57 if port else 0x56
        if chip >= 1:
            cmd += 0x50  # secondary chip
        if reg in FREQ_HI:
            self.freq_hi[key] = value
            return
        if reg in FREQ_LO:
            hi = self.freq_hi.get((chip, port, reg + 4))
            if hi is None:
                self.reg_cache.pop(key, None)
            else:
                if self.reg_cache.get(key) == (hi, value):
                    return
                self.reg_cache[key] = (hi, value)
                self.flush_wait()
                self.data += bytes((cmd, reg + 4, hi))
            self.flush_wait()
            self.data += bytes((cmd, reg, value))
            return
        if key not in NO_DEDUP_REGS:
            if self.reg_cache.get(key) == value:
                return
            self.reg_cache[key] = value
        self.flush_wait()
        self.data += bytes((cmd, reg, value))

    def write_ssg(self, reg: int, value: int, lock: bool = False) -> None:
        # SSG is on chip 0 for now
        self.write_ym2608(0, 0, reg & 0x0F, value & 0xFF, lock)

    def mark_loop(self) -> None:
        if self.loop_offset is None:
            self.flush_wait()
            self.loop_offset = len(self.data)
            self.loop_samples = self.samples
            self.reg_cache.clear()

    def write_end(self) -> None:
        self.flush_wait()
        self.data.append(0x66)

    def build(self) -> bytes:
        self.flush_wait()
        header = bytearray(256)
        header[0:4] = b"Vgm "
        header[8:12] = struct.pack("<I", 0x171)
        # YM2608
        for i, c in enumerate(self.chips):
            if c["name"] == "ym2608":
                if i == 0:
                    header[0x48:0x4C] = struct.pack("<I", c["clock"])
                else:
                    header[0x48:0x4C] = struct.pack("<I", self.chips[0]["clock"] | 0x40000000)
            elif c["name"] == "ym2151":
                header[0x30:0x34] = struct.pack("<I", c["clock"])
        header[0x18:0x1C] = struct.pack("<I", self.samples)
        header[0x24:0x28] = struct.pack("<I", SAMPLE_RATE)
        header[0x34:0x38] = struct.pack("<I", 256 - 0x34)
        if self.loop_offset is not None:
            header[0x1C:0x20] = struct.pack("<I", 256 + self.loop_offset - 0x1C)
            header[0x20:0x24] = struct.pack("<I", self.samples - (self.loop_samples or 0))

        gd3_bytes = b""
        if self.gd3 and any(self.gd3.values()):
            g = self.gd3
            fields = [
                g["title"], g["title"],
                g["album"], g["album"],
                "NEC PC-8801", "",
                g["composer"], g["composer"],
                g["date"],
                "MUCOMVGM",
                g["comment"],
            ]
            body = b"".join(self._utf16le_z(f) for f in fields)
            gd3_bytes = b"Gd3 " + struct.pack("<II", 0x00000100, len(body)) + body
            gd3_pos = 256 + len(self.data)
            header[0x14:0x18] = struct.pack("<I", gd3_pos - 0x14)

        header[0x04:0x08] = struct.pack("<I", 256 + len(self.data) + len(gd3_bytes) - 4)
        return bytes(header) + bytes(self.data) + gd3_bytes

    def write_ym2151(self, chip: int, reg: int, value: int) -> None:
        self.flush_wait()
        cmd = 0x54 if chip == 0 else 0xA4  # secondary
        self.data += bytes((cmd, reg & 0xFF, value & 0xFF))
