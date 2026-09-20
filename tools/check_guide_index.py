"""BUG_HUNT_GUIDE.md 行号索引自检：确认附录索引表里的 "符号 -> 文件:行" 仍然指得准。

用法（任意工作目录均可）：
    .venv\\Scripts\\python tools/check_guide_index.py
退出码：0 全部匹配；1 有漂移（打印每条不匹配的引用与它当前指向的内容）。

为什么需要它：手册里的行号会随代码改动漂移，而漂移的索引比没有索引更误导排查者。
改完代码后跑一下这条命令，比人工核对快得多。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUIDE = ROOT / "BUG_HUNT_GUIDE.md"
SRC_ROOT = ROOT / "src" / "luoluotool"
INDEX_HEADING = "## 附：快速定位索引"

_cache: dict[str, list[str] | None] = {}


def _lines_of(rel_path: str) -> list[str] | None:
    """按相对路径（如 core/vision.py）读取源码行。"""
    if rel_path not in _cache:
        name = rel_path.split("/")[-1]
        hits = [p for p in SRC_ROOT.rglob(name) if p.as_posix().endswith(rel_path)]
        _cache[rel_path] = hits[0].read_text(encoding="utf-8").splitlines() if hits else None
    return _cache[rel_path]


def main() -> int:
    if not GUIDE.is_file():
        print(f"找不到 {GUIDE}")
        return 1
    text = GUIDE.read_text(encoding="utf-8")
    if INDEX_HEADING not in text:
        print(f"手册里找不到小节：{INDEX_HEADING}")
        return 1
    section = text.split(INDEX_HEADING)[-1]

    # 反引号用 chr(96) 拼，避免被 PowerShell 的 here-string 当转义符吃掉
    tick = chr(96)
    row = re.compile(r"^\|\s*" + tick + r"([^" + tick + r"]+)" + tick + r"\s*\|\s*"
                     + tick + r"([a-z_0-9/]+\.py):(\d+)" + tick, re.MULTILINE)

    checked = drifted = 0
    for symbol, rel_path, line_text in row.findall(section):
        source = _lines_of(rel_path)
        if source is None:
            print(f"[MISS] {symbol}: 找不到源码 {rel_path}")
            drifted += 1
            continue
        index = int(line_text) - 1
        if index >= len(source):
            print(f"[MISS] {symbol}: {rel_path}:{line_text} 超出文件长度（{len(source)} 行）")
            drifted += 1
            continue
        name = symbol.split("(")[0].split(" / ")[0].split(".")[-1].strip()
        checked += 1
        if name not in "\n".join(source[index : index + 4]):
            print(f"[DRIFT] {symbol:<34} {rel_path}:{line_text} 当前指向：{source[index].strip()[:60]}")
            drifted += 1

    print(f"文档行号自检：检查 {checked} 条索引，漂移 {drifted} 条")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
