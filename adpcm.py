from __future__ import annotations

import struct
from pathlib import Path

PCM_SLOTS = 32
PCM_INFO = 0x400
PCMNMB = (
    0x49BA + 0x200, 0x4E1C + 0x200, 0x52C1 + 0x200, 0x57AD + 0x200,
    0x5CE4 + 0x200, 0x626A + 0x200, 0x6844 + 0x200, 0x6E77 + 0x200,
    0x7509 + 0x200, 0x7BFE + 0x120, 0x835E + 0x200, 0x8B2D + 0x200,
)


def word(buf: bytes, pos: int) -> int:
    return buf[pos] | (buf[pos + 1] << 8)


def parse_mucompcm(data: bytes) -> tuple[dict[int, tuple[int, int, int]], bytes]:
    if len(data) < PCM_INFO:
        raise ValueError("PCMファイルが小さすぎます")
    found = []
    for i in range(PCM_SLOTS):
        ent = data[i * 32:(i + 1) * 32]
        if ent and ent[0] != 0:
            found.append((i, word(ent, 28), word(ent, 30), ent[26]))
    found.sort(key=lambda item: item[1])
    slots = {}
    for n, (i, start, length, vol) in enumerate(found):
        if n + 1 < len(found):
            end = max(start, found[n + 1][1] - 1)
        else:
            end = max(start, start + max(1, length >> 5) - 1)
        slots[i + 1] = (start, end, vol)
    return slots, data[PCM_INFO:]


def load_pcm(folder: Path, name: str) -> tuple[dict[int, tuple[int, int, int]], bytes]:
    path = folder / name
    if not path.is_file():
        raise ValueError(f"PCMファイルがありません: {path}")
    return parse_mucompcm(path.read_bytes())


def read_wav(path: Path) -> tuple[list[int], int]:
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path.name} は WAV ではありません")
    pos, rate, samples = 12, 0, []
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + size]
        if tag == b"fmt ":
            if int.from_bytes(body[0:2], "little") != 1 or int.from_bytes(body[2:4], "little") != 1:
                raise ValueError(f"{path.name} は 16bit モノラルにしてください")
            if int.from_bytes(body[14:16], "little") != 16:
                raise ValueError(f"{path.name} は 16bit モノラルにしてください")
            rate = int.from_bytes(body[4:8], "little")
        elif tag == b"data":
            count = len(body) // 2
            samples = list(struct.unpack("<" + "h" * count, body[:count * 2]))
        pos += 8 + size + (size & 1)
    if not samples or not rate:
        raise ValueError(f"{path.name} を読めません")
    return samples, rate


def resample(samples: list[int], rate: int, target: int = 16000) -> list[int]:
    if rate == target or len(samples) < 2:
        return samples
    out, pos, step, last = [], 0.0, rate / target, len(samples) - 1
    while pos < last:
        i = int(pos)
        frac = pos - i
        out.append(int(samples[i] + (samples[i + 1] - samples[i]) * frac))
        pos += step
    return out or samples[:1]


def encode_adpcm(samples: list[int]) -> bytes:
    xn, step, out, byte, high = 0, 127, bytearray(), 0, False
    scale = (57, 57, 57, 57, 77, 102, 128, 153)
    for sample in samples:
        diff = sample - xn
        adpcm = 8 if diff < 0 else 0
        diff = abs(diff)
        for bit, div in ((4, 1), (2, 2), (1, 4)):
            if diff >= step // div:
                adpcm |= bit
                diff -= step // div
        delta = step >> 3
        if adpcm & 4:
            delta += step
        if adpcm & 2:
            delta += step >> 1
        if adpcm & 1:
            delta += step >> 2
        xn = max(-32768, min(32767, xn - delta if adpcm & 8 else xn + delta))
        step = max(127, min(24576, step * scale[adpcm & 7] // 64))
        if high:
            out.append(byte | (adpcm & 0x0F))
        else:
            byte = (adpcm & 0x0F) << 4
        high = not high
    if high:
        out.append(byte)
    return bytes(out)


def append_pcm(slots, rom, folder: Path, list_name: str) -> None:
    path = folder / list_name
    if not path.is_file():
        raise ValueError(f"PCMリストがありません: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        no_s, name = line.split(maxsplit=1)
        no = int(no_s)
        if not 1 <= no <= PCM_SLOTS:
            raise ValueError(f"PCM @{no} は 1～32 です")
        src = folder / name
        if not src.is_file():
            raise ValueError(f"PCMファイルがありません: {src}")
        payload = src.read_bytes() if src.suffix.lower() != ".wav" else encode_adpcm(resample(*read_wav(src)))
        start = (len(rom) + 31) // 32
        rom.extend(b"\x00" * (start * 32 - len(rom)))
        rom.extend(payload)
        slots[no] = (start, max(start, ((len(rom) + 31) // 32) - 1), 255)


def load_song_pcm(folder: Path, pcm_file: str, pcm_list: str):
    slots, rom = load_pcm(folder, pcm_file) if pcm_file else ({}, b"")
    buf = bytearray(rom)
    if pcm_list:
        append_pcm(slots, buf, folder, pcm_list)
    return slots, bytes(buf)


def delta_n(note: int, detune: int) -> int:
    rate = PCMNMB[note % 12] + detune
    block = note // 12
    rate = rate << -block if block < 0 else rate >> block
    return max(1, min(0xFFFF, rate))


def write_rom(vgm, rom: bytes) -> None:
    if not rom:
        return
    payload = struct.pack("<II", len(rom), 0) + rom
    vgm.data += bytes((0x67, 0x66, 0x81)) + struct.pack("<I", len(payload)) + payload


def play(vgm, start: int, end: int, rate: int, volume: int, pan: int) -> None:
    pan_bits = (0x00, 0x80, 0x40, 0xC0)[pan & 3]
    vgm.write_ym2608(1, 0x00, 0x01)
    vgm.write_ym2608(1, 0x01, pan_bits)
    vgm.write_ym2608(1, 0x02, start & 0xFF)
    vgm.write_ym2608(1, 0x03, (start >> 8) & 0xFF)
    vgm.write_ym2608(1, 0x04, end & 0xFF)
    vgm.write_ym2608(1, 0x05, (end >> 8) & 0xFF)
    vgm.write_ym2608(1, 0x0C, end & 0xFF)
    vgm.write_ym2608(1, 0x0D, (end >> 8) & 0xFF)
    vgm.write_ym2608(1, 0x09, rate & 0xFF)
    vgm.write_ym2608(1, 0x0A, (rate >> 8) & 0xFF)
    vgm.write_ym2608(1, 0x0B, volume & 0xFF)
    vgm.write_ym2608(1, 0x00, 0xA0)


def set_rate(vgm, rate: int) -> None:
    vgm.write_ym2608(1, 0x09, rate & 0xFF)
    vgm.write_ym2608(1, 0x0A, (rate >> 8) & 0xFF)


def stop(vgm) -> None:
    vgm.write_ym2608(1, 0x00, 0x01)
