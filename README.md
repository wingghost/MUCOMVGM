# MUCOMVGM

MUCOM88 形式の MML を、YM2608 用の VGM に変換するコンパイラです。

PC-8801 の MUCOM88 / MUCOM88win 向けに書いた MML を、MDPlayer などで鳴らせる VGM にするのが目的です。FM 6音、SSG、リズム、ADPCM に対応しています。

完全な互換ではありません。F-num は 11bit で正規化しており、MUCOM88 の 8bit のままでは扱いません。既存の MML を変換して、普通に演奏できることを目標にしています。

## 必要なもの

- Python 3.10 以降
- 追加のパッケージは不要です

## 使い方

python mucomvgm.py song.muc

同じフォルダに `song.vgm` ができます。出力名を指定する場合は次です。

python mucomvgm.py song.muc out.vgm

ADPCM を使う曲は、`.muc` と同じフォルダに PCM ファイルを置きます。

#pcm mucompcm.bin

新規の WAV を使う場合は、リストを書きます。番号は 1 から 32 です。

#pcmlist pcmlist.txt

pcmlist.txt の中身は、番号とファイル名です。

1 kick.wav  
2 snare.wav  

WAV は 16bit モノラルです。16kHz 以外は変換時に 16kHz へ合わせます。

## ファイル

- `mucomvgm.py` 起動
- `mmlparser.py` MML の解析
- `driver.py` 演奏データの生成
- `vgmwriter.py` VGM の書き出し
- `adpcm.py` ADPCM の読み込み
- `chips/opn.py` YM2608 の FM
- `chips/ay8910.py` SSG

## ライセンス

MIT License。詳細は LICENSE を見てください。

## 更新履歴

2026/10/03 Ver.0.0.2  
    - &のバグを修正

2026/10/03 Ver.0.0.1  
    - 初回リリース
