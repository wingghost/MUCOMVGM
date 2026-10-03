# MUCOMVGM

MUCOM88 形式の MML を、YM2608 用の VGM に変換するコンパイラです。

PC-8801 の MUCOM88 / MUCOM88win 向けに書いた MML を、MDPlayer などで鳴らせる VGM にするのが目的です。FM 6音、SSG、リズム、ADPCM に対応しています。

完全な互換ではありません。

## 使い方

mucomvgm.exe song.muc

同じフォルダに `song.vgm` ができます。出力名を指定する場合は次です。

mucomvgm.exe song.muc out.vgm

プリセットの音色ファイルを使う場合は、`.muc` と同じフォルダに VOICE ファイルを置きます。

#voice voice.dat

ADPCM を使う曲は、`.muc` と同じフォルダに PCM ファイルを置きます。

#pcm mucompcm.bin

新規の WAV を使う場合は、リストを書きます。番号は 1 から 32 です。

#pcmlist pcmlist.txt

pcmlist.txt の中身は、番号とファイル名です。

1 kick.wav  
2 snare.wav  

WAV は 16kHz/16bit モノラルです。16kHz 以外は変換時に 16kHz へ合わせます。

## MUCOM88と違うコマンド

l%      前にスペースが入っている「 %」と同等です。クロック単位での音長設定。  
{}      ポルタメント。{c>>>c}などとオクターブ超えが可能に。  
@1      音色パラメーターのキャリアのTLが反映される。

## 新しく実装されたコマンド

v%      TL値の 127～0 でボリュームを設定。 v% 後に設定された()は、TL値で増減。  
Q       8分割のスタッカート。Q8はq0と同等。

## 未実装のコマンド（実装予定なし）

@"音色名"  
@%

## ライセンス

MIT License。詳細は LICENSE.txt を見てください。

## 更新履歴

2026/10/03 Ver.0.0.3  
    - エラーメッセージを修正  
    - コンパイル時のメッセージを修正

2026/10/03 Ver.0.0.2  
    - &のバグを修正

2026/10/03 Ver.0.0.1  
    - 初回リリース
