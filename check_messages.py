"""メッセージ表の整合性チェック。  実行: python check_messages.py

- コード中の MMLError("キー") / tr("キー") のキーが、ja.py にあるか
- 渡している値の名前が、ja.py の {名前} と一致するか
- 全言語のキーと {名前} が、ja.py と過不足なく一致するか
- (警告) どこからも使われていないキー
"""
from __future__ import annotations

import ast
import string
import sys
from pathlib import Path

from messages import LANGS

ROOT = Path(__file__).parent
POSITION_ARGS = {"part", "line"}  # MMLError の位置指定。メッセージの {名前} には使わない


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def collect_usages() -> list[tuple[str, str, int, set[str]]]:
    # (キー, ファイル, 行, 渡している値の名前) の一覧
    usages = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "check_messages.py" or "orig_backup" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id not in ("MMLError", "tr") or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue  # キーが変数のもの (messages/__init__.py の内部処理) は対象外
            names = {kw.arg for kw in node.keywords if kw.arg}
            if node.func.id == "MMLError":
                names -= POSITION_ARGS
            usages.append((first.value, str(path.relative_to(ROOT)), node.lineno, names))
    return usages


def main() -> int:
    errors, warnings = [], []
    base = LANGS["ja"]

    for lang, table in LANGS.items():
        if lang == "ja":
            continue
        for key in sorted(set(base) - set(table)):
            errors.append(f"[{lang}] キーが足りません: {key}")
        for key in sorted(set(table) - set(base)):
            errors.append(f"[{lang}] ja.py にないキーです: {key}")
        for key in sorted(set(base) & set(table)):
            if placeholders(base[key]) != placeholders(table[key]):
                errors.append(f"[{lang}] {key}: {{名前}} が ja と違います ({sorted(placeholders(table[key]))} / ja: {sorted(placeholders(base[key]))})")

    used = set()
    for key, file, line, names in collect_usages():
        used.add(key)
        if key not in base:
            errors.append(f"{file}:{line}: キー {key!r} が ja.py にありません")
            continue
        if key.startswith("loc."):
            continue  # 位置の表示は MMLError が part / line から組み立てる
        if names != placeholders(base[key]):
            errors.append(f"{file}:{line}: {key} に渡す値 {sorted(names)} が、メッセージの {{名前}} {sorted(placeholders(base[key]))} と違います")
    for key in sorted(set(base) - used):
        if not key.startswith("loc."):
            warnings.append(f"使われていないキー: {key}")

    for w in warnings:
        print("警告:", w)
    for e in errors:
        print("エラー:", e)
    if not errors:
        print(f"OK  (キー {len(base)} 個 / 言語 {', '.join(LANGS)})")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
