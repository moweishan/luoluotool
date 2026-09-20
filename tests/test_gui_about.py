"""「关于」页测试（offscreen）：内容块齐全、版本号、复制诊断信息、打开目录按钮。

对应需求（用户 2026-09-20）与仓库规范（`CHECKLIST.md` §11：关于页与 README 必须声明
封号风险 / 仅限个人学习自用 / 不提供防沉迷规避；PySide6 属 LGPL 需许可说明）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from luoluotool import __version__
from luoluotool.config.models import AppConfig
from luoluotool.gui.pages import about as about_module
from luoluotool.gui.pages.about import PAGE_TITLE, AboutPage
from luoluotool.gui.widgets import PAGE_SIZE_HINT, ScrollablePage

_APP = QApplication.instance() or QApplication([])


def _page_text(page: AboutPage) -> str:
    """整页可见文字（标签 + 按钮文本 + 分组标题）拼起来，用来断言"这一块真的在页面上"。"""
    parts = [child.text() for child in page.content.findChildren(QLabel)]
    parts += [child.text() for child in page.content.findChildren(QPushButton)]
    parts += [child.title() for child in page.content.findChildren(QGroupBox)]
    return "\n".join(parts)


def test_about_page_is_scrollable_with_expected_title_and_hint() -> None:
    """关于页必须和别的页签一样继承 ScrollablePage（否则会顶高页签区）。"""
    page = AboutPage()
    assert PAGE_TITLE == "关于"
    assert isinstance(page, ScrollablePage)
    assert page.sizeHint() == PAGE_SIZE_HINT
    page.close()


def test_about_page_shows_name_version_author_and_repository() -> None:
    page = AboutPage()
    text = _page_text(page)
    assert "LuoLuoTool" in text
    assert f"v{__version__}" in text
    assert "moweishan" in text
    assert about_module.REPOSITORY_URL in text
    assert "仅供个人学习自用" in text          # 一句话用途说明
    page.close()


def test_about_page_states_risk_and_privacy() -> None:
    """规范强制项：封号风险、仅个人学习自用、不发布不售卖、不提供防沉迷规避、不联网不上传。"""
    page = AboutPage()
    text = _page_text(page)
    for keyword in ("封号风险", "个人学习自用", "不发布", "不售卖", "防沉迷",
                    "不读写游戏内存", "网络请求", "不上传"):
        assert keyword in text, f"关于页缺少声明：{keyword}"
    page.close()


def test_about_page_lists_third_party_components_and_licenses() -> None:
    page = AboutPage()
    text = _page_text(page)
    for keyword in ("PySide6", "LGPL", "Qt 6", "pywin32", "numpy", "opencv-python-headless"):
        assert keyword in text, f"第三方组件清单缺少：{keyword}"
    assert "未修改 Qt 源码" in text              # LGPL 动态链接用法声明
    page.close()


def test_about_page_copy_diagnostics_puts_environment_on_clipboard() -> None:
    page = AboutPage()
    assert f"v{__version__}" in page.diagnostics_text()
    assert "Python" in page.diagnostics_text()

    page.copy_diagnostics_button.click()

    clip = QApplication.clipboard().text()
    assert f"LuoLuoTool v{__version__}" in clip
    assert "PySide6" in clip and "Python" in clip and "管理员权限" in clip
    assert "已复制" in page.status_label.text()
    page.close()


def test_about_page_reports_sane_python_bit_width() -> None:
    """回归：位数必须按指针宽度算（曾误用 sys.maxsize.bit_length()*8-8 → 显示 496 位）。"""
    import struct

    bits = struct.calcsize("P") * 8
    assert bits in (32, 64)
    summary = AboutPage().environment_summary()
    assert f"{bits} 位" in summary
    assert "496" not in summary
    assert "系统" in summary and "主屏" in summary


def test_about_page_open_dir_buttons_target_real_directories(monkeypatch) -> None:
    """三个「打开目录」按钮必须指向真实的 user_data / logs / assets/templates。"""
    from pathlib import Path

    from luoluotool.utils.paths import get_logs_dir, get_templates_dir, get_user_data_dir

    opened: list[str] = []
    monkeypatch.setattr(
        about_module.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    page = AboutPage()
    page.open_data_dir_button.click()
    page.open_logs_dir_button.click()
    page.open_templates_dir_button.click()

    # QUrl 会把路径规范化成 `/` 分隔，这里按 Path 比对（Windows 与 / 混用不该让测试变红）
    expected = [get_user_data_dir(), get_logs_dir(), get_templates_dir()]
    assert [Path(p) for p in opened] == expected
    assert "已打开目录" in page.status_label.text()
    page.close()


def test_about_page_reports_when_directory_cannot_be_opened(monkeypatch) -> None:
    """打开失败也要给可读提示（不吞掉）。"""
    monkeypatch.setattr(about_module.QDesktopServices, "openUrl", lambda url: False)
    page = AboutPage()
    page.open_data_dir_button.click()
    assert "打不开目录" in page.status_label.text()
    page.close()
