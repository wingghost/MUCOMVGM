from __future__ import annotations

import sys
from pathlib import Path

from driver import compile_song
from mmlparser import ALL_PARTS, parse_mml


def main() -> int:
    if len(sys.argv) < 2:
        print("使い方: python mucomvgm.py test.muc")
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) >= 3 else src.with_suffix(".vgm")
    song = parse_mml(src.read_text(encoding="utf-8"), src.parent)
    data = compile_song(song)
    dst.write_bytes(data)
    print(f"wrote {dst} ({len(data)} bytes) chip={song.chip}")
    if song.loop_tick is not None:
        print(f"loop tick ({next(ev.part for ev in song.events if ev.kind == 'loop')}): {song.loop_tick}")
    if song.part_clocks:
        print("clocks:")
        for part in ALL_PARTS:
            if part in song.part_clocks:
                print(f"  {part}: {song.part_clocks[part]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
