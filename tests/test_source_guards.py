"""仓库级结构性守卫：防止「改一处漏一处」这类缺陷复活。

对应第三轮审查报告 `reports/CODE_REVIEW_REPORT_20260920_3.md`：
- P2-1：模块级 import 被同名赋值遮蔽（写入路径与校验路径各用一个常量 → 配置可能被自己写坏）；
- P3-3：同一业务常量在两个模块各定义一份（界面允许的值与校验接受的值可能各走各的）。

判定全部基于 AST/源码扫描，不依赖具体运行时环境。
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = ROOT / "src" / "luoluotool"
TESTS_ROOT = ROOT / "tests"

# 模板生成的 UI 文件不受行数硬线约束（AGENTS.md §2）；当前仓库没有这类文件
GENERATED_UI_PATTERNS = ("ui_*.py", "*_ui.py")
LINE_LIMIT = 600


def _iter_sources() -> list[pathlib.Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if p.is_file())


def _module_level_names(tree: ast.Module) -> tuple[set[str], dict[str, int]]:
    """返回（模块级 import 绑定的名字 → 行号列表）；同名多次导入只记第一处。"""
    imported: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported.setdefault(name, node.lineno)
    return set(imported), imported


def _module_level_assignments(tree: ast.Module) -> dict[str, int]:
    assigned: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.setdefault(node.target.id, node.lineno)
    return assigned


def test_no_module_level_import_is_shadowed() -> None:
    """评审 P2-1 回归：模块级 import 之后不得再用同名赋值把它遮蔽掉。

    遮蔽本身不报错，却会让"写入路径"与"校验路径"各用一份常量 —— 正是配置被自己写坏
    （下次启动整份恢复默认）的同类根因。
    """
    offenders: list[str] = []
    for path in _iter_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported, import_lines = _module_level_names(tree)
        for name, line in _module_level_assignments(tree).items():
            if name in imported:
                rel = path.relative_to(ROOT).as_posix()
                offenders.append(
                    f"{rel}:{line} 用 {name} = ... 遮蔽了第 {import_lines[name]} 行的同名 import"
                )
    assert offenders == [], "存在被遮蔽的模块级 import：\n" + "\n".join(offenders)


def test_sources_stay_under_line_limit() -> None:
    """AGENTS §2：源文件与测试文件都不得超过 600 行（模板生成的 UI 文件除外）。"""
    offenders: list[str] = []
    root = ROOT
    for base in (SRC_ROOT, TESTS_ROOT):
        for path in sorted(base.rglob("*.py")):
            if any(path.match(pattern) for pattern in GENERATED_UI_PATTERNS):
                continue
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > LINE_LIMIT:
                offenders.append(f"{path.relative_to(root).as_posix()} = {lines} 行")
    assert offenders == [], f"超过 {LINE_LIMIT} 行的文件：\n" + "\n".join(offenders)


def test_debug_page_limits_come_from_core_debug() -> None:
    """评审 P3-3 回归：调试页的坐标/间隔/时长/次数上限必须是 core.debug 那一份常量。

    否则界面允许填写、校验却拒绝（或反过来），又变成 P1-2 那类"可保存但读不回来"的缺陷。
    """
    from luoluotool.core import debug as core_debug
    from luoluotool.gui.pages import debug as debug_page

    assert debug_page.COORDINATE_MAX is core_debug.COORDINATE_MAX
    assert debug_page.INTERVAL_RANGE_MS is core_debug.INTERVAL_RANGE_MS
    assert debug_page.DURATION_RANGE_MS is core_debug.DURATION_RANGE_MS
    assert debug_page.COUNT_RANGE == (1, core_debug.MAX_REPEAT)


def test_printwindow_flags_are_defined_once() -> None:
    """评审 P3-3 回归：`PW_*` 取景 flag 只允许在 `automation/vision.py` 定义一处。"""
    defined_in: dict[str, list[str]] = {}
    for path in _iter_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for name in _module_level_assignments(tree):
            if name in {"PW_CLIENTONLY", "PW_RENDERFULLCONTENT"}:
                defined_in.setdefault(name, []).append(path.relative_to(ROOT).as_posix())
    for name in ("PW_CLIENTONLY", "PW_RENDERFULLCONTENT"):
        places = defined_in.get(name, [])
        assert places == ["src/luoluotool/automation/vision.py"], (
            f"{name} 应只在 automation/vision.py 定义一次，实际：{places or '未定义'}"
        )
