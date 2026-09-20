"""「关于」页：版本、用途、风险与免责声明、隐私、第三方组件许可、运行环境与数据目录。

按用户 2026-09-20 的要求建立（联网查了通行字段集：GTK/Adw `AboutDialog` 与 KDE `KAboutData`
都包含「程序名 / 版本 / 一句话说明 / 作者与致谢 / 许可（含第三方组件）/ 主页与反馈渠道 / 版权声明」）。
用户已确认的内容取舍：
- 作者＝GitHub 用户名 `moweishan`；**不显示任何联系方式**；
- **不附项目许可文件**，只声明「个人学习自用、不发布不售卖」；第三方组件（PySide6 等）的许可照实列出；
- 版本号沿用 `__version__`（0.1.0）；页签里放运行环境信息 + 「复制诊断信息」+「打开数据目录」。

本页只做展示与本地动作（复制到剪贴板、打开本机目录），不产生任何输入注入、不联网。
"""

from __future__ import annotations

import platform
import struct
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from luoluotool import __version__
from luoluotool.automation.elevation import is_process_elevated
from luoluotool.gui.widgets import ScrollablePage
from luoluotool.utils.paths import get_logs_dir, get_templates_dir, get_user_data_dir

PAGE_TITLE = "关于"

APP_NAME = "LuoLuoTool"
AUTHOR = "moweishan"
REPOSITORY_URL = "https://github.com/moweishan/luoluotool"
TAGLINE = "《桃源深处有人家》辅助工具：按图识别 + 真实键鼠自动化，仅供个人学习自用。"

# 第三方组件与许可（照实列出；PySide6 是 LGPL，必须声明动态链接使用、未修改 Qt 源码）
THIRD_PARTY_NOTICES: tuple[tuple[str, str], ...] = (
    ("PySide6（Qt for Python）", "LGPL v3 —— 动态链接使用，未修改 Qt 源码；发布时随附许可证说明"),
    ("Qt 6", "LGPL v3（经 PySide6 动态链接）"),
    ("pywin32", "PSF License（Python Software Foundation）"),
    ("numpy", "BSD 3-Clause"),
    ("opencv-python-headless", "Apache License 2.0"),
)

RISK_LINES: tuple[str, ...] = (
    "· 自动化操作可能违反游戏用户协议，存在**封号风险** —— 请自行判断是否使用，后果自负。",
    "· 仅限个人学习自用：不发布、不售卖、不用于工作室多开打金。",
    "· 不提供任何未成年人防沉迷规避功能。",
    "· 本工具不读写游戏内存、不拦截或伪造网络封包、不修改游戏文件。",
)

PRIVACY_LINES: tuple[str, ...] = (
    "· 纯本地运行：程序本身不做任何网络请求（无遥测、无自动更新检查）。",
    "· 不上传日志 / 配置 / 截图；日志与配置都留在本机（见下方目录）。",
    "· 游戏画面与模板只存在本机：assets/templates 会随仓库入库（你手动整理的识别图），"
    "assets/anchors、assets/screenshots、user_data、logs 一律不入库。",
)


class AboutPage(ScrollablePage):
    """关于页（只读展示 + 复制诊断信息 / 打开本机目录）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self.content)
        layout.setSpacing(10)

        layout.addWidget(self._header())
        layout.addWidget(self._author_box())
        layout.addWidget(self._risk_box())
        layout.addWidget(self._privacy_box())
        layout.addWidget(self._third_party_box())
        layout.addWidget(self._environment_box())
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

    # ---------------------------------------------------------------- 各区块
    def _header(self) -> QLabel:
        label = QLabel(f"<b>{APP_NAME}</b>　v{__version__}<br>{TAGLINE}")
        label.setWordWrap(True)
        return label

    def _author_box(self) -> QGroupBox:
        box = QGroupBox("作者与致谢")
        layout = QVBoxLayout(box)
        author = QLabel(
            f"作者：{AUTHOR}（GitHub）<br>"
            f"仓库：<a href='{REPOSITORY_URL}'>{REPOSITORY_URL}</a><br>"
            "致谢：PySide6 / Qt、pywin32、numpy、OpenCV 等开源项目（许可见下）。"
        )
        author.setOpenExternalLinks(True)
        author.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        author.setWordWrap(True)
        layout.addWidget(author)
        return box

    def _risk_box(self) -> QGroupBox:
        box = QGroupBox("风险与免责声明")
        layout = QVBoxLayout(box)
        for line in RISK_LINES:
            label = QLabel(line.replace("**", ""))
            label.setWordWrap(True)
            label.setStyleSheet("color: #c62828;")     # 与真实模式状态同一警告色
            layout.addWidget(label)
        return box

    def _privacy_box(self) -> QGroupBox:
        box = QGroupBox("数据与隐私")
        layout = QVBoxLayout(box)
        for line in PRIVACY_LINES:
            label = QLabel(line)
            label.setWordWrap(True)
            layout.addWidget(label)
        return box

    def _third_party_box(self) -> QGroupBox:
        box = QGroupBox("第三方组件与许可")
        layout = QVBoxLayout(box)
        for name, license_text in THIRD_PARTY_NOTICES:
            label = QLabel(f"· {name} —— {license_text}")
            label.setWordWrap(True)
            layout.addWidget(label)
        own = QLabel(
            "· 本项目自身：未附许可文件，保留所有权利；仅限个人学习自用，不发布、不售卖。"
        )
        own.setWordWrap(True)
        layout.addWidget(own)
        return box

    def _environment_box(self) -> QGroupBox:
        box = QGroupBox("运行环境与数据目录")
        layout = QVBoxLayout(box)
        self.environment_label = QLabel(self.environment_summary())
        self.environment_label.setWordWrap(True)
        layout.addWidget(self.environment_label)

        row = QHBoxLayout()
        self.copy_diagnostics_button = QPushButton("复制诊断信息")
        self.copy_diagnostics_button.setToolTip("把版本 / Python / PySide6 / 系统信息复制到剪贴板（报 bug 时贴给我）")
        self.copy_diagnostics_button.clicked.connect(self._on_copy_diagnostics)
        row.addWidget(self.copy_diagnostics_button)
        self.open_data_dir_button = self._dir_button(row, "打开数据目录", get_user_data_dir)
        self.open_logs_dir_button = self._dir_button(row, "打开日志目录", get_logs_dir)
        self.open_templates_dir_button = self._dir_button(row, "打开识别图片目录", get_templates_dir)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    def _dir_button(self, row: QHBoxLayout, text: str, path_getter) -> QPushButton:
        """目录按钮：提示里显示真实路径，点一下用系统默认方式打开。"""
        button = QPushButton(text)
        button.setToolTip(str(path_getter()))
        button.clicked.connect(lambda _=False, getter=path_getter: self._open_dir(getter))
        row.addWidget(button)
        return button

    # ---------------------------------------------------------------- 行为
    def environment_summary(self) -> str:
        """一行环境摘要（也用于「复制诊断信息」的前两行）。"""
        screen = QApplication.primaryScreen()
        if screen is not None:
            size, ratio = screen.size(), screen.devicePixelRatio()
            screen_text = f"{size.width()}x{size.height()}（缩放 {ratio:.0%}）"
        else:
            screen_text = "读不到屏幕信息"
        elevated = "是" if is_process_elevated() else "否"
        # 位数取指针宽度（不能拿 sys.maxsize.bit_length() 直接乘 8，那是“位数-1”）
        bits = struct.calcsize("P") * 8
        return (
            f"Python {platform.python_version()}（{bits} 位）　"
            f"PySide6 {self._pyside_version()}　"
            f"系统 {platform.system()} {platform.release()}（{platform.version()}）\n"
            f"管理员权限：{elevated}　主屏：{screen_text}"
        )

    @staticmethod
    def _pyside_version() -> str:
        try:
            import PySide6
            return PySide6.__version__
        except Exception:      # pragma: no cover - 仅在 PySide6 元数据缺失时
            return "未知"

    def diagnostics_text(self) -> str:
        """可复制的诊断信息（不含任何个人数据；只含版本与环境）。"""
        return (
            f"{APP_NAME} v{__version__}\n"
            f"{self.environment_summary()}\n"
            f"数据目录：{get_user_data_dir()}\n"
            f"日志目录：{get_logs_dir()}\n"
            f"识别图片目录：{get_templates_dir()}"
        )

    def _on_copy_diagnostics(self) -> None:
        QApplication.clipboard().setText(self.diagnostics_text())
        self.status_label.setText("诊断信息已复制到剪贴板（只含版本与环境，不含日志/截图内容）")

    def _open_dir(self, path_getter) -> None:
        path = path_getter()
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if opened:
            self.status_label.setText(f"已打开目录：{path}")
        else:
            self.status_label.setText(f"打不开目录（可能被系统策略阻止）：{path}")
