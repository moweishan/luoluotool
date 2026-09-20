"""布局测量与「页签高度稳定」规则测试（offscreen）。

规则来源：用户实测「勾选开发者调试后所有 tab 页的高度都会改变」——页签内容是
`QTabWidget` 最小高度的来源，任一页签内容过高会把整个页签区顶高。因此所有页签统一
继承 `ScrollablePage`，并由 `gui.layout_measure` 提供可测量的回归检查。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from luoluotool.config.models import AppConfig
from luoluotool.gui.layout_measure import (
    MAX_PAGE_MIN_HEIGHT,
    PAGE_TITLES,
    LayoutMeasure,
    PageMeasure,
    format_measure_report,
    measure_layout,
)
from luoluotool.gui.widgets import PAGE_SIZE_HINT, ScrollablePage

from gui_helpers import window_factory  # 共享夹具（评审 P3-2：不再各自留副本）


def test_all_tab_pages_are_scrollable(window_factory) -> None:
    """所有页签都必须继承 ScrollablePage：内容进滚动区 + 统一建议尺寸。"""
    window = window_factory()
    for title, attribute in PAGE_TITLES:
        page = getattr(window, attribute)
        assert isinstance(page, ScrollablePage), f"页签「{title}」未继承 ScrollablePage"
        assert page.scroll_area.widget() is page.content, f"页签「{title}」内容未进入滚动区"
        assert page.content.layout() is not None, f"页签「{title}」内容区没有布局"
        assert page.minimumSizeHint().height() <= MAX_PAGE_MIN_HEIGHT, (
            f"页签「{title}」最小高度 {page.minimumSizeHint().height()} 过高"
        )
        assert page.sizeHint() == PAGE_SIZE_HINT, f"页签「{title}」建议尺寸未常量化"


def test_measure_layout_reports_stable_heights(window_factory) -> None:
    """测量结果：挂载/卸载调试页时页签区（最小/建议/实际）与日志面板高度完全不变。"""
    window = window_factory(developer_mode=True)
    measure = measure_layout(window)

    assert measure.window_size == (960, 640)
    assert measure.toggle_stable is True
    assert measure.unstable_items == ()
    assert measure.fits is True
    assert measure.problems == ()
    assert measure.ok is True
    assert measure.tabs_min_unmounted == measure.tabs_min_mounted
    assert measure.tabs_hint_unmounted == measure.tabs_hint_mounted
    assert measure.tabs_height_unmounted == measure.tabs_height_mounted
    assert measure.log_height_unmounted == measure.log_height_mounted > 0
    assert [page.title for page in measure.pages] == [title for title, _ in PAGE_TITLES]
    assert all(page.scrollable for page in measure.pages)
    assert all(page.problem is None for page in measure.pages)


def test_measure_layout_does_not_change_mounted_state(window_factory) -> None:
    """测量是只读的：测完页签数量与调试页的挂载状态保持原样。"""
    window = window_factory(developer_mode=False)
    assert window.tabs.count() == 5
    measure_layout(window)
    assert window.tabs.count() == 5
    assert window.tabs.indexOf(window.debug_page) < 0

    window.settings_page.developer_box.setChecked(True)
    assert window.tabs.count() == 6
    measure = measure_layout(window)
    assert measure.pages[-1].mounted is True
    assert window.tabs.count() == 6
    assert window.tabs.indexOf(window.debug_page) == 5


def test_format_measure_report_has_summary_and_pages(window_factory) -> None:
    """报告包含各项高度、每个页签一行与结论行（CLI 与调试页共用同一文本）。"""
    window = window_factory(developer_mode=True)
    report = format_measure_report(measure_layout(window))
    assert "布局测量" in report
    assert "页签区最小高度" in report
    assert "页签区建议高度" in report
    assert "页签区实际高度" in report
    assert "日志面板高度" in report
    assert "窗口最小高度" in report
    assert "结论：" in report
    for title, _ in PAGE_TITLES:
        assert title in report


def test_format_measure_report_is_cp936_printable(window_factory) -> None:
    """回归（2026-09-19 实测崩溃）：报告必须能用中文 Windows 控制台的 cp936 编码打印。

    冻结后的 exe 是 GUI 子系统，stdout 按系统 ANSI 代码页初始化，报告里的 `✓ ✗`
    无法编码会抛 UnicodeEncodeError → `--measure-layout` 退出码 1。
    这里钉住：不含这两个已知符号，且整份报告可被 cp936 完整编码（× 等 GBK 内字符不受限）。
    """
    window = window_factory(developer_mode=True)
    report = format_measure_report(measure_layout(window))
    for symbol in ("✓", "✗"):
        assert symbol not in report, f"报告不应包含 GBK 无法编码的符号：{symbol}"
    assert "[OK]" in report
    report.encode("cp936")      # 不抛异常即通过


def test_page_measure_flags_violations() -> None:
    """违规判定：内容过高的可滚动页面、以及未继承 ScrollablePage 的页面都要报错。"""
    tall = PageMeasure("高页", "tall_page", True, MAX_PAGE_MIN_HEIGHT + 300, 800, True)
    assert tall.problem is not None and "最小高度" in tall.problem

    raw = PageMeasure("原页", "raw_page", True, 68, 484, False)
    assert raw.problem is not None and "ScrollablePage" in raw.problem

    fine = PageMeasure("好页", "fine_page", True, 68, 484, True)
    assert fine.problem is None


def _measure(**overrides) -> LayoutMeasure:
    base = dict(
        window_size=(960, 640),
        tabs_min_unmounted=96,
        tabs_min_mounted=96,
        tabs_hint_unmounted=268,
        tabs_hint_mounted=268,
        tabs_height_unmounted=328,
        tabs_height_mounted=328,
        window_min_unmounted=285,
        window_min_mounted=285,
        log_height_unmounted=240,
        log_height_mounted=240,
        pages=(PageMeasure("设置", "settings_page", True, 68, 225, True),),
    )
    base.update(overrides)
    return LayoutMeasure(**base)


def test_layout_measure_detects_toggle_instability() -> None:
    """挂载/卸载导致页签区或日志面板高度变化时必须被判定为问题（用户遇到的 bug）。"""
    broken = _measure(
        tabs_min_mounted=516, tabs_hint_mounted=316, tabs_height_mounted=356,
        window_min_mounted=658, log_height_mounted=212,
    )
    assert broken.toggle_stable is False
    assert broken.fits is False
    assert broken.unstable_items == (
        "页签区最小高度", "页签区建议高度", "页签区实际高度", "窗口最小高度", "日志面板高度",
    )
    problems = "\n".join(broken.problems)
    assert "改变页签区或日志面板的高度" in problems
    assert "超过窗口高度 640" in problems
    assert _measure().ok is True


def test_cli_measure_layout_exits_zero(tmp_path, capsys) -> None:
    """`--measure-layout` 离屏测量并打印报告；配置文件不存在时用默认配置（不写文件）。"""
    from luoluotool.__main__ import main

    missing = tmp_path / "not_created.json"
    assert main(["--measure-layout", "--config", str(missing)]) == 0
    out = capsys.readouterr().out
    assert "布局测量" in out and "结论：挂载/卸载开发者调试页不改变任何高度" in out
    assert missing.exists() is False   # 只读测量：不创建配置文件


def test_cli_measure_layout_with_developer_mode_config(tmp_path, capsys) -> None:
    """配置里 developer_mode=true（调试页已挂载）时同样通过测量。"""
    from luoluotool.__main__ import main
    from luoluotool.config import store

    config = AppConfig.default()
    config.automation.developer_mode = True
    path = tmp_path / "config.json"
    store.save(config, path)
    assert main(["--measure-layout", "--config", str(path)]) == 0
    assert "结论：挂载/卸载开发者调试页不改变任何高度" in capsys.readouterr().out


def test_print_safe_degrades_on_gbk_console(monkeypatch, tmp_path) -> None:
    """`--measure-layout` 在只支持 GBK 的 stdout 上不得崩溃（用户实测过的冻结 exe 场景）。"""
    import io
    import sys

    from luoluotool.__main__ import _print_safe, main

    buffer = io.BytesIO()
    gbk_stdout = io.TextIOWrapper(buffer, encoding="gbk", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", gbk_stdout)
    _print_safe("结论：不可编码符号 ✓ 也要能打印")     # 不抛异常即可
    gbk_stdout.flush()
    assert "结论" in buffer.getvalue().decode("gbk")

    # 端到端：整条 CLI 在 GBK stdout 下退出码仍为 0
    buffer2 = io.BytesIO()
    gbk_stdout2 = io.TextIOWrapper(buffer2, encoding="gbk", errors="strict", newline="\n")
    monkeypatch.setattr(sys, "stdout", gbk_stdout2)
    assert main(["--measure-layout", "--config", str(tmp_path / "none.json")]) == 0
    gbk_stdout2.flush()
    assert "布局测量" in buffer2.getvalue().decode("gbk")


def test_print_safe_survives_missing_stdout(monkeypatch) -> None:
    """窗口化进程没有控制台（stdout 为 None）时，打印不得崩溃。"""
    import sys

    from luoluotool.__main__ import _print_safe

    monkeypatch.setattr(sys, "stdout", None)
    _print_safe("无处可写也不应抛异常")


def test_debug_page_layout_measure_button_shows_report(window_factory) -> None:
    """调试页「布局测量」按钮 → 报告写入状态标签（可在 GUI 里随时自查）。"""
    window = window_factory(developer_mode=True)
    window.debug_page.layout_measure_button.click()
    text = window.debug_page.status_label.text()
    assert "布局测量" in text and "结论：" in text
    # 测量不得改变页签状态
    assert window.tabs.count() == 6
    assert window.tabs.indexOf(window.debug_page) == 5
