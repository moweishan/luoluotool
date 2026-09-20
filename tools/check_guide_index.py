"""BUG_HUNT_GUIDE.md 行号索引自检：确认附录索引表里的 "符号 -> 文件:行" 仍然指得准。

用法（任意工作目录均可）：
    .venv\\Scripts\\python tools/check_guide_index.py
退出码：0 全部匹配；1 有漂移（打印每条不匹配的引用与它当前指向的内容）。

为什么需要它：手册里的行号会随代码改动漂移，而漂移的索引比没有索引更误导排查者。
改完代码后跑一下这条命令，比人工核对快得多。

支持两种写法（2026-09-21：从前只认第一种，第二种整行等于没被检查）：
    | `符号` | `path/file.py:123` | 说明 |
    | `符号A` / `符号B` | `path/file.py:123` / `:456` | 说明 |      ← 后面的 `:456` 是同一文件的行号
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
    # 一行 = 「符号单元格 | 引用单元格」；符号与引用各自靠反引号识别，
    # 不要求固定的分隔写法（`A` / `B`、`A`（说明）/ `B` 都算），否则整行会被静默跳过。
    row = re.compile(r"^\|(?P<syms>[^|\n]*)\|(?P<refs>[^|\n]*)\|", re.MULTILINE)
    symbol_re = re.compile(tick + r"([^" + tick + r"]+)")
    identifier_re = re.compile(r"[A-Za-z_][\w.]*")
    ref_re = re.compile(tick + r"([a-z_0-9/]+\.py):(\d+)" + tick)
    relative_line_re = re.compile(tick + r"\s*:(\d+)" + tick)

    checked = drifted = 0
    for match in row.finditer(section):
        refs = ref_re.findall(match.group("refs"))
        if not refs:
            continue                       # 不是"符号 → 文件:行"的行（表头、纯说明行）
        rel_path, first_line = refs[0]
        lines = [int(first_line)] + [int(n) for n in relative_line_re.findall(match.group("refs"))]
        source = _lines_of(rel_path)
        # 第一格里的反引号内容里只保留"像标识符"的那些：两个名字之间的 ` / `、`（说明）` 等
        # 本身也被反引号夹住（前一个的收尾 + 后一个的开头），不排掉会把符号与行号错位配对。
        symbols = [
            name.strip() for name in symbol_re.findall(match.group("syms"))
            if identifier_re.fullmatch(name.strip())
        ]
        if source is None:
            for symbol in symbols:
                print(f"[MISS] {symbol}: 找不到源码 {rel_path}")
                drifted += 1
            continue
        # 只核对"符号与行号配得上对"的那些；符号多于行号时多出来的不猜（不报假漂移）
        for symbol, line_text in zip(symbols, lines):
            index = line_text - 1
            name = symbol.split("(")[0].split(" / ")[0].split(".")[-1].strip()
            checked += 1
            if index >= len(source):
                print(f"[MISS] {symbol}: {rel_path}:{line_text} 超出文件长度（{len(source)} 行）")
                drifted += 1
                continue
            if name not in "\n".join(source[index : index + 4]):
                print(f"[DRIFT] {symbol:<34} {rel_path}:{line_text} 当前指向：{source[index].strip()[:60]}")
                drifted += 1

    print(f"文档行号自检：检查 {checked} 条索引，漂移 {drifted} 条")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
