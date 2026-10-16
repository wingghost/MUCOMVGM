"""エラーメッセージの多言語化。

- プログラム側は、文章ではなくキーを渡す:  raise MMLError("ex.digits", part=part, line=line_no + 1)
- 文章への変換は、表示する瞬間に tr() / MMLError.message() が行う。
- 言語を足すときは ja.py をコピーして翻訳し、下の LANGS に1行足す。
"""
from __future__ import annotations

import os
import sys

# PyInstaller が拾えるように、静的に import する (importlib での動的 import はしない)
from . import en as _en
from . import ja as _ja

DEFAULT_LANG = "ja"
LANGS = {"ja": _ja.MESSAGES, "en": _en.MESSAGES}

_lang = DEFAULT_LANG


def detect_lang() -> str:
    """OSの表示言語から言語を決める。日本語なら ja、それ以外は en。判定できなければ ja。"""
    try:
        if sys.platform == "win32":
            import ctypes

            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "ja" if (langid & 0x3FF) == 0x11 else "en"
        for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(name, "")
            if value and value not in ("C", "POSIX"):
                return "ja" if value.lower().startswith("ja") else "en"
    except Exception:
        pass
    return DEFAULT_LANG


def resolve_lang(requested: str | None) -> str:
    """--lang で指定された値があればそれを、無効または未指定なら自動判定を返す。"""
    if requested:
        requested = requested.lower()
        if requested in LANGS:
            return requested
    return detect_lang()


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else DEFAULT_LANG


def tr(key: str, **params) -> str:
    """キーを現在の言語の文章にする。無ければ ja、それも無ければキー名をそのまま返す。"""
    text = LANGS[_lang].get(key) or LANGS[DEFAULT_LANG].get(key) or key
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


class MMLError(ValueError):
    """変換エラー。メッセージのキーと値、位置(パート名・行番号)を持つ。"""

    def __init__(self, key: str, *, part: str | None = None, line: int | None = None, **params) -> None:
        super().__init__(key)
        self.key = key
        self.part = part
        self.line = line
        self.params = params

    def message(self) -> str:
        body = tr(self.key, **self.params)
        if self.part and self.line:
            return f"{tr('loc.part_line', part=self.part, line=self.line)}: {body}"
        if self.part:
            return f"{tr('loc.part', part=self.part)}: {body}"
        if self.line:
            return f"{tr('loc.line', line=self.line)}: {body}"
        return body

    def __str__(self) -> str:
        return self.message()
