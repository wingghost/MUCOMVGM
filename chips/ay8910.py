from __future__ import annotations

from dataclasses import dataclass, field

SSG_PARTS = "DEF"
SSG_CH = {"D": 0, "E": 1, "F": 2}


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def tone_period(clock: int, midi_note: int, detune: int = 0) -> int:
    if midi_note < 0 or clock <= 0:
        return 0
    freq = 440.0 * (2 ** ((midi_note - 69) / 12))
    if detune:
        freq *= 2 ** (detune / 1200)
    if freq <= 0:
        return 0
    return clamp(int(round(clock / (16 * freq))), 1, 4095)


def ssg_clock(kind: str, master: int) -> int:
    if kind == "ym2608":
        return master // 16
    return master


@dataclass
class AyChannel:
    period: int = 0
    volume: int = 0
    use_tone: bool = True
    use_noise: bool = False
    env: bool = False


@dataclass
class AyState:
    clock: int
    channels: list[AyChannel] = field(default_factory=lambda: [AyChannel() for _ in range(3)])
    noise: int = 0
    env_period: int = 0
    env_shape: int = 0
    env_dirty: bool = False

    def set_note(self, ch: int, midi_note: int, detune: int = 0) -> None:
        self.channels[ch].period = tone_period(self.clock, midi_note, detune)

    def set_volume(self, ch: int, volume: int, env: bool = False) -> None:
        self.channels[ch].volume = clamp(volume, 0, 15)
        self.channels[ch].env = env

    def set_mixer(self, ch: int, mode: int) -> None:
        self.channels[ch].use_tone = mode in (1, 3)
        self.channels[ch].use_noise = mode in (2, 3)

    def registers(self) -> list[tuple[int, int]]:
        regs: list[tuple[int, int]] = []
        mixer = 0x3F
        for i, ch in enumerate(self.channels):
            regs.append((i * 2, ch.period & 0xFF))
            regs.append((i * 2 + 1, (ch.period >> 8) & 0x0F))
            if ch.use_tone:
                mixer &= ~(1 << i)
            if ch.use_noise:
                mixer &= ~(1 << (i + 3))
            regs.append((8 + i, 0x10 if ch.env else clamp(ch.volume, 0, 15)))
        regs.append((6, clamp(self.noise, 0, 31)))
        regs.append((7, mixer))
        regs.append((11, self.env_period & 0xFF))
        regs.append((12, (self.env_period >> 8) & 0xFF))
        if self.env_dirty:
            regs.append((13, self.env_shape & 0x0F))
            self.env_dirty = False
        return regs
    