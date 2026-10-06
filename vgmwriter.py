from __future__ import annotations

import struct

SAMPLE_RATE = 44100
YM2608_CLOCK = 7987200
AY_CLOCK = 2000000
INTERNAL_WHOLE = 768
DEFAULT_C = 128

# 同じ値でも再送が必要なレジスタ (port, reg)。重複削除の対象外にする。
#   (0, 0x10) リズム キーオン/オフ  (0, 0x28) FM キーオン/オフ
#   (0, 0x0D) SSG エンベロープ形状 (書くたびに再スタート)
#   (1, 0x00) ADPCM 制御 (書くたびに再生開始/リセット)
# FNUM/BLOCK は 上位(A4～A6, AC～AE) と 下位(A0～A2, A8～AA) をペアで扱う。
# 上位は下位を書いた時点で反映されるため、ペアが前回と同じ時だけ両方を省略する。
FREQ_LO = frozenset({0xA0, 0xA1, 0xA2, 0xA8, 0xA9, 0xAA})
FREQ_HI = frozenset({0xA4, 0xA5, 0xA6, 0xAC, 0xAD, 0xAE})
NO_DEDUP_REGS = frozenset({(0, 0x10), (0, 0x28), (0, 0x0D), (1, 0x00)})


def is_lockable(port: int, reg: int) -> bool:
    # y コマンドで書いた値を、自動の書き直しから守れるレジスタ (FM の音色/B0～B6、SSG の 0x00～0x0C)
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
    def __init__(self, chip: str, clock: int):
        self.chip = chip
        self.clock = clock
        self.data = bytearray()
        self.samples = 0
        self.loop_offset = None
        self.loop_samples = None
        self.reg_cache = {}
        self.freq_hi = {}
        self.pending_wait = 0
        self.locks = {}

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

    def write_ym2608(self, port: int, reg: int, value: int, lock: bool = False) -> None:
        port, reg, value = 1 if port else 0, reg & 0xFF, value & 0xFF
        key = (port, reg)
        if is_lockable(port, reg):
            if lock:
                self.locks[key] = value
            elif key in self.locks:
                value = self.locks[key]
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
        if self.chip == "ym2608":
            self.write_ym2608(0, reg & 0x0F, value & 0xFF, lock)
            return
        reg, value = reg & 0xFF, value & 0xFF
        if reg <= 0x0C:
            if lock:
                self.locks[(2, reg)] = value
            elif (2, reg) in self.locks:
                value = self.locks[(2, reg)]
        if reg != 0x0D:
            key = (2, reg)
            if self.reg_cache.get(key) == value:
                return
            self.reg_cache[key] = value
        self.flush_wait()
        self.data += bytes((0xA0, reg, value))

    def mark_loop(self) -> None:
        if self.loop_offset is None:
            self.flush_wait()
            self.loop_offset = len(self.data)
            self.loop_samples = self.samples
            # ループ復帰時のチップ状態は曲末尾の状態になるため、ここで履歴を捨てて全レジスタを再送させる
            self.reg_cache.clear()

    def write_end(self) -> None:
        self.flush_wait()
        self.data.append(0x66)

    def build(self) -> bytes:
        self.flush_wait()
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
