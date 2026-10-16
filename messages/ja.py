# 日本語メッセージ表 (基準言語)。
# {名前} は実行時に値が入る場所。波かっこそのものを表示したいときは {{ }} と二重に書く。
MESSAGES = {
    # --- 位置の表示 (メッセージの先頭に「位置: 」として付く) ---
    "loc.part_line": "{part} {line}行目",
    "loc.part": "{part}",
    "loc.line": "{line}行目",

    # --- コマンドライン ---
    "cli.usage": "使い方: {exe} test.muc [--lang ja|en]\n  --lang ja|en  メッセージの言語 (省略時はOSの言語設定。判定できなければ ja)",
    "cli.error": "エラー: {msg}",

    # --- マクロ ---
    "macro.too_deep": "マクロのネストが深すぎます",
    "macro.undefined": "マクロ *{no} が定義されていません",

    # --- ループ / ポルタメント ---
    "loop.unclosed": "ループの ']' がありません",
    "porta.unclosed": "ポルタメントの '}}' がありません",
    "porta.no_note": "ポルタメントに音符がありません",

    # --- チップ ---
    "chip.unsupported": "対応チップは ym2608 / ay8910 / ym2149 です",

    # --- FM音色 ---
    "fm.voice_undefined": "FM音色 @{no} が定義されていません",
    "voice.rows_short": "音色データの行が足りません",
    "voice.need_fbal": "@ {no}: FB AL が必要です",
    "voice.op_params": "@ {no}: オペレータ{op} のパラメータが不足しています",
    "voice.dat_small": "音色ファイル(voice.dat)が小さすぎます",
    "voice.file_missing": "音色ファイルがありません: {path}",

    # --- SSG音色 ---
    "ssg.range": "SSG音色 @{no} は 0～255 です",
    "ssg.undefined": "SSG音色 @{no} が定義されていません",
    "ssg.bad_cmd": "SSG音色 @{no}: '{c}' は使えません。使えるのは E P M N w です",
    "ssg.unclosed_brace": "SSG音色 @{no} の '}}' がありません",

    # --- PCM / WAV ---
    "pcm.undefined": "PCM @{no} が定義されていません",
    "pcm.range": "PCM @{no} は 1～32 です",
    "pcm.file_small": "PCMファイルが小さすぎます",
    "wav.not_wav": "{name} は WAV ではありません",
    "wav.format": "{name} は 16bit モノラルにしてください",
    "wav.unreadable": "{name} を読めません",

    # --- EX / y ---
    "ex.part": "EX は C/L/M/N パートでのみ使えます",
    "ex.digits": "EX は 1～4 の数字で指定します (例: EX1234)",
    "ex.overlap": "{a} と {b}: オペレータ{ops} が同時に使われています (tick {tick})",
    "y.reg_range": "y のレジスタ番号は $000～$1FF (0～511) です",
}
