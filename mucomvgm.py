from __future__ import annotations

import sys
from pathlib import Path

from driver import compile_song
from messages import resolve_lang, set_lang, tr
from mmlparser import ALL_PARTS, FM_PARTS, parse_mml, read_mml_text

VERSION = "0.1.0"


def split_lang_option(argv: list[str]) -> tuple[list[str], str | None]:
    # --lang ja / --lang=ja を取り除く。残りは従来どおりの引数 (入力ファイル, 出力ファイル)
    rest, lang, i = [], None, 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--lang":
            lang = argv[i + 1] if i + 1 < len(argv) else None
            i += 2
        elif arg.startswith("--lang="):
            lang = arg[len("--lang="):]
            i += 1
        else:
            rest.append(arg)
            i += 1
    return rest, lang


def main() -> int:
    args, lang_option = split_lang_option(sys.argv[1:])
    set_lang(resolve_lang(lang_option))
    print(f"MUCOMVGM Ver.{VERSION}")
    if len(args) < 1:
        exe = "mucomvgm.exe" if getattr(sys, "frozen", False) else "python mucomvgm.py"
        print(tr("cli.usage", exe=exe))
        return 1
    src = Path(args[0])
    dst = Path(args[1]) if len(args) >= 2 else src.with_suffix(".vgm")
    try:
        song = parse_mml(read_mml_text(src), src.parent)
        data = compile_song(song)
        dst.write_bytes(data)
    except Exception as e:
        print(tr("cli.error", msg=str(e)))
        return 1

    if song.chips:
        chip_str = ",".join(f"{c.no}:{c.name}" for c in song.chips)
        print(f"chips:{chip_str}")
    else:
        print(f"chip:{song.chip}")
    used_voices = {ev.value for ev in song.events if ev.kind == "voice" and ev.part in FM_PARTS}
    print(f"Used FM voice:{len(used_voices)}")
    print("[ Total count ]")
    if song.chips and len(song.chips) > 1:
        for key, clocks in sorted(song.part_clocks.items()):
            print(f"{key}:{clocks} ", end="")
        print()
    else:
        print("".join(f"{part}:{song.part_clocks.get(part, 0)} " for part in sorted(ALL_PARTS)))
    if song.loop_tick is not None:
        print("[ Loop count  ]")
        if song.chips and len(song.chips) > 1:
            for key, clocks in sorted(song.part_loop_clocks.items()):
                print(f"{key}:{clocks} ", end="")
            print()
        else:
            print("".join(f"{part}:{song.part_loop_clocks.get(part, 0)} " for part in sorted(ALL_PARTS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
