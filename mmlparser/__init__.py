# 旧 mmlparser.py と同じ名前を、これまで通り `from mmlparser import ...` で使えるようにする
from chips.ay8910 import SSG_PARTS
from chips.opn import FM_PARTS

from .model import (
    NOTE_MAP,
    RHYTHM_PART,
    ADPCM_PART,
    MOD_PARTS,
    ALL_PARTS,
    MusicEvent,
    SsgPreset,
    PartState,
    Song,
)
from .scan import (
    strip_comment,
    skip_space,
    read_number,
    read_signed_number,
    read_imm,
    read_detune,
    expand_macros,
    norm_mod_count,
    find_loop_end,
    find_brace_end,
    find_top_slash,
    static_state_after,
    octave_after,
)
from .timing import (
    note_duration,
    clocks_to_internal,
    parse_duration_spec,
    gate_duration,
    emit_volume,
    note_index,
    fm_reverb_volume,
    ssg_reverb_volume,
    fine_reverb_volume,
)
from .voice import (
    SSG_BUILTIN,
    parse_nums,
    next_data_line,
    parse_voice_block,
    VOICE_DAT_SIZE,
    VOICE_DAT_REG_ORDER,
    parse_voice_dat,
    load_voice_file,
    parse_ssg_preset,
    take_ssg_preset,
)
from .part import (
    parse_porta_body,
    parse_part_mml,
)
from .song import (
    read_mml_text,
    check_ex_overlap,
    apply_jump,
    clocks_at_tick,
    parse_mml,
)
