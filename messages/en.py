# English message table.
# Keys and {placeholders} must match ja.py exactly (check_messages.py verifies this).
# To show a literal brace, write it doubled: {{ }}.
MESSAGES = {
    # --- location (added in front of a message as "location: ") ---
    "loc.part_line": "{part} line {line}",
    "loc.part": "{part}",
    "loc.line": "line {line}",

    # --- command line ---
    "cli.usage": "Usage: {exe} test.muc [--lang ja|en]\n  --lang ja|en  Message language (default: OS language setting; ja if undetermined)",
    "cli.error": "Error: {msg}",

    # --- macros ---
    "macro.too_deep": "Macro nesting is too deep",
    "macro.undefined": "Macro *{no} is not defined",

    # --- loop / portamento ---
    "loop.unclosed": "Missing ']' for loop",
    "porta.unclosed": "Missing '}}' for portamento",
    "porta.no_note": "No note in portamento",

    # --- chip ---
    "chip.unsupported": "Supported chips are ym2608 / ay8910 / ym2149",

    # --- FM voice ---
    "fm.voice_undefined": "FM voice @{no} is not defined",
    "voice.rows_short": "Not enough rows of voice data",
    "voice.need_fbal": "@ {no}: FB AL is required",
    "voice.op_params": "@ {no}: Not enough parameters for operator {op}",
    "voice.dat_small": "Voice file (voice.dat) is too small",
    "voice.file_missing": "Voice file not found: {path}",

    # --- SSG voice ---
    "ssg.range": "SSG voice @{no} must be 0-255",
    "ssg.undefined": "SSG voice @{no} is not defined",
    "ssg.bad_cmd": "SSG voice @{no}: '{c}' cannot be used. Available commands: E P M N w",
    "ssg.unclosed_brace": "SSG voice @{no}: missing '}}'",

    # --- PCM / WAV ---
    "pcm.undefined": "PCM @{no} is not defined",
    "pcm.range": "PCM @{no} must be 1-32",
    "pcm.file_small": "PCM file is too small",
    "wav.not_wav": "{name} is not a WAV file",
    "wav.format": "{name} must be 16-bit mono",
    "wav.unreadable": "Cannot read {name}",

    # --- EX / y ---
    "ex.part": "EX can only be used in parts C/L/M/N",
    "ex.digits": "EX must be given as digits 1-4 (e.g. EX1234)",
    "ex.overlap": "{a} and {b}: operator {ops} used at the same time (tick {tick})",
    "y.reg_range": "y register number must be $000-$1FF (0-511)",
}
