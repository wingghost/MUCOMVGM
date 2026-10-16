from __future__ import annotations

from dataclasses import dataclass, field

from chips.ay8910 import SSG_PARTS
from chips.opn import FM_PARTS
from vgmwriter import DEFAULT_C, INTERNAL_WHOLE, YM2608_CLOCK


NOTE_MAP = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}
RHYTHM_PART = "G"
ADPCM_PART = "K"
MOD_PARTS = FM_PARTS + SSG_PARTS
ALL_PARTS = MOD_PARTS + RHYTHM_PART + ADPCM_PART


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
    marks: list = field(default_factory=lambda: [(0, 0)])
    ex_mask: int = 0xF
    spans: list = field(default_factory=list)
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
    composer: str = ""
    album: str = ""
    date: str = ""
    comment: str = ""
    chip: str = "ym2608"
    chip_clock: int = YM2608_CLOCK
    tick_rate: int = INTERNAL_WHOLE
    events: list[MusicEvent] = field(default_factory=list)
    voices: dict[int, tuple] = field(default_factory=dict)
    ssg_presets: dict[int, SsgPreset] = field(default_factory=dict)
    part_clocks: dict[str, int] = field(default_factory=dict)
    part_loop_clocks: dict[str, int] = field(default_factory=dict)
    loop_tick: int | None = None
    loop_candidates: list = field(default_factory=list)
    jump_tick: int = 0
    lfo_enable: int = 0
    lfo_speed: int = 0
    voice_file: str = ""
    pcm_file: str = ""
    pcm_list: str = ""
    pcm_slots: dict = field(default_factory=dict)
    pcm_rom: bytes = b""
    macros: dict[int, str] = field(default_factory=dict)
