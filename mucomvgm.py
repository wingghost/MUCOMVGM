from __future__ import annotations

import sys
from pathlib import Path

from driver import compile_song
from mmlparser import ALL_PARTS, FM_PARTS, parse_mml


def main() -> int:
    if len(sys.argv) < 2:
        exe = "mucomvgm.exe" if getattr(sys, "frozen", False) else "python mucomvgm.py"
        print(f"使い方: {exe} test.muc")
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) >= 3 else src.with_suffix(".vgm")
    song = parse_mml(src.read_text(encoding="utf-8"), src.parent)
    data = compile_song(song)
    dst.write_bytes(data)
    print(f"chip:{song.chip}")
    used_voices = {ev.value for ev in song.events if ev.kind == "voice" and ev.part in FM_PARTS}
    print(f"Used FM voice:{len(used_voices)}")
    print("[ Total count ]")
    print("".join(f"{part}:{song.part_clocks.get(part, 0)} " for part in sorted(ALL_PARTS)))
    if song.loop_tick is not None:
        print("[ Loop count  ]")
        print("".join(f"{part}:{song.part_loop_clocks.get(part, 0)} " for part in sorted(ALL_PARTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
