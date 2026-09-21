"""「关于」页测试（offscreen）：内容块齐全、版本号、复制诊断信息、打开目录按钮。

对应需求（用户 2026-09-20）与仓库规范（`CHECKLIST.md` §11：关于页与 README 必须声明
封号风险 / 仅限个人学习自用 / 不提供防沉迷规避；PySide6 属 LGPL 需许可说明）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QPushButton

from luoluotool import __version__
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


# ------------------------------------------------- 第四轮评审 P3-6 / P3-7 的回归


def test_diagnostics_text_has_no_absolute_user_path() -> None:
    """评审 P3-6①：诊断信息里**不许出现绝对路径**（否则会把 C:\\Users\\<用户名> 贴出去）。"""
    text = AboutPage().diagnostics_text()

    assert "程序目录：" in text and "数据目录：" in text
    assert "user_data" in text and "logs" in text and "assets/templates" in text
    assert ":\\" not in text and ":/" not in text          # 没有任何盘符 / 绝对路径
    assert "Users" not in text                             # 也不带家目录那一段
    assert "用户" not in text


def test_about_page_states_misoperation_risk() -> None:
    """评审 P3-7：PROJECT_SPEC §5 要求的"误操作风险"必须出现在关于页。"""
    text = _page_text(AboutPage())

    assert "误操作风险" in text
    assert "置顶" in text or "前台" in text        # 会抢前台
    assert "光标" in text                          # 会真实移动鼠标
    assert "停止" in text                          # 给了退路


def test_dir_buttons_do_not_create_directories_until_used(monkeypatch) -> None:
    """评审 P3-6③：构造关于页不该顺带建目录（`get_*_dir()` 会 mkdir）。"""
    from pathlib import Path

    calls: list[Path] = []
    fake = Path(os.environ["TEMP"]) / "about_dir_probe"      # 刻意不创建

    def fake_getter() -> Path:
        calls.append(fake)
        return fake

    monkeypatch.setattr(about_module, "get_user_data_dir", fake_getter)
    page = AboutPage()

    assert calls == []                       # 构造时一次都没调用
    assert not fake.exists()                 # 也就不会建目录

    QApplication.sendEvent(page.open_data_dir_button, QEvent(QEvent.Type.Enter))
    assert calls == [fake]                   # 悬停时才取路径
    assert str(fake) in page.open_data_dir_button.toolTip()
    assert not fake.exists()                 # 取路径本身不建目录（建目录是 get_*_dir 的事）
    page.close()


def test_pyside_version_failure_is_logged_not_swallowed(monkeypatch, caplog) -> None:
    """评审 P3-6②：读不到版本号时要记日志，不能 `except: return "未知"` 一声不响。"""
    import logging as _logging
    import sys

    class _Broken:
        @property
        def __version__(self):
            raise RuntimeError("元数据缺失")

    monkeypatch.setitem(sys.modules, "PySide6", _Broken())
    caplog.set_level(_logging.WARNING)

    assert AboutPage._pyside_version() == "未知"
    assert any("PySide6 版本" in record.message for record in caplog.records)
