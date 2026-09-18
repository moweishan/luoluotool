"""主窗口：五页签配置 + 保存/重载/恢复默认 + 启动/停止 + 日志面板 + F8 急停。"""

import logging
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from luoluotool import __version__
from luoluotool.automation.elevation import (
    is_process_elevated,
    is_window_elevated,
    restart_as_admin,
)
from luoluotool.automation.hotkey import (
    DEFAULT_HOTKEY_NAME,
    VK_F8,
    WM_HOTKEY,
    HotkeyRegistrar,
    resolve_vk,
)
from luoluotool.automation.window import diagnose_window, find_window
from luoluotool.config import store
from luoluotool.config.models import AppConfig
from luoluotool.core.runner import Runner
from luoluotool.gui.pages.daily import DailyPage
from luoluotool.gui.pages.feature3 import Feature3Page
from luoluotool.gui.pages.feature4 import Feature4Page
from luoluotool.gui.pages.order_hold import OrderHoldPage
from luoluotool.gui.pages.settings import SettingsPage
from luoluotool.gui.widgets import LogPanelHandler
from luoluotool.utils.paths import get_debug_dir, get_icons_dir

logger = logging.getLogger(__name__)

WINDOW_TITLE = "LuoLooTool"
TAB_TITLES: tuple[str, ...] = ("设置", "日常任务", "卡订单", "功能三", "功能四")
WINDOW_ICON_FILES = ("luoluoTool.png", "luoluoTool.ico")
_ICO_MAGIC = b"\x00\x00\x01\x00"
_PNG_MAGIC = b"\x89PNG"
STATUS_RUNNING_DRY = "运行中 · 干跑"
STATUS_RUNNING_REAL = "运行中 · 真实模式"
STATUS_REAL_STYLE = "color: #c62828; font-weight: bold;"
THREAD_WAIT_TIMEOUT_MS = 2000
LOG_PANEL_MAX_BLOCKS = 1000


def _is_valid_icon_file(path: Path) -> bool:
    """按魔数校验图标格式（拦截伪装成 .ico 的 PNG 等）。"""
    try:
        with open(path, "rb") as fp:
            head = fp.read(4)
    except OSError:
        return False
    expected = _PNG_MAGIC if path.suffix == ".png" else _ICO_MAGIC
    return head == expected


def load_window_icon() -> QIcon:
    """从 assets/icons 加载窗口图标；文件缺失或格式非法时降级为空图标。"""
    icon = QIcon()
    icons_dir = get_icons_dir()
    for name in WINDOW_ICON_FILES:
        path = icons_dir / name
        if not path.is_file():
            continue
        if not _is_valid_icon_file(path):
            logger.warning("图标文件格式非法，已跳过：%s", path)
            continue
        icon.addFile(str(path))
    if icon.isNull():
        logger.warning("未找到可用的窗口图标：%s", icons_dir)
    return icon


def _default_runner_factory(config: AppConfig) -> Runner:
    return Runner(config)


class _RunnerThread(QThread):
    """在工作线程中执行 Runner.start()（阻塞主循环）。"""

    def __init__(self, runner: Runner, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner

    def run(self) -> None:
        self._runner.start()


class _DiagnoseThread(QThread):
    """在工作线程中执行窗口诊断；结果（消息, 是否需要提权）经信号回 UI 线程。"""

    finished_message = Signal(str, bool)

    def __init__(self, keyword: str, debug_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self._keyword = keyword
        self._debug_dir = debug_dir

    def run(self) -> None:
        try:
            result = diagnose_window(self._keyword, self._debug_dir)
            self.finished_message.emit(result.message, result.needs_elevation)
        except Exception:
            logger.exception("窗口诊断失败")
            self.finished_message.emit("窗口诊断失败，详见日志", False)


class MainWindow(QMainWindow):
    """LuoLooTool 主窗口：仅展示与绑定；文件/任务逻辑调用 config/core 模块。"""

    def __init__(
        self,
        config: AppConfig,
        config_path: Path,
        runner_factory: Callable[[AppConfig], Runner] | None = None,
        auto_elevate: bool = True,
    ) -> None:
        super().__init__()
        self._config = config
        self._config_path = config_path
        self._runner_factory = runner_factory or _default_runner_factory
        self._auto_elevate_enabled = auto_elevate
        self._runner: Runner | None = None
        self._thread: _RunnerThread | None = None
        self._diagnose_thread: _DiagnoseThread | None = None
        self._dirty = False
        self._idle_status = f"版本 {__version__}"
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(960, 640)
        self.setWindowIcon(load_window_icon())
        self.tabs: QTabWidget = QTabWidget(self)
        pages = (
            SettingsPage(self._config, self._mark_dirty),
            DailyPage(self._config, self._mark_dirty),
            OrderHoldPage(self._config, self._mark_dirty),
            Feature3Page(self._config, self._mark_dirty),
            Feature4Page(self._config, self._mark_dirty),
        )
        (
            self.settings_page,
            self.daily_page,
            self.order_hold_page,
            self.feature3_page,
            self.feature4_page,
        ) = pages
        for page, title in zip(pages, TAB_TITLES):
            self.tabs.addTab(page, title)
        self.tabs.setCurrentIndex(0)  # 默认打开设置页
        self.settings_page.diagnose_button.clicked.connect(self._on_diagnose)
        self.settings_page.restart_admin_button.clicked.connect(self._on_restart_admin_clicked)
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self._save)
        self.reload_button = QPushButton("重新加载")
        self.reload_button.clicked.connect(self._reload)
        self.reset_button = QPushButton("恢复默认")
        self.reset_button.clicked.connect(self._reset)
        self.start_button = QPushButton("启动")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(LOG_PANEL_MAX_BLOCKS)
        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.reload_button)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.tabs)
        layout.addLayout(buttons)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(central)
        self.statusBar().showMessage(self._idle_status)
        self._log_handler = LogPanelHandler(self.log_panel)
        logging.getLogger().addHandler(self._log_handler)
        self._hotkey_name = self._config.automation.failsafe_hotkey or DEFAULT_HOTKEY_NAME
        self._hotkey = HotkeyRegistrar(
            vk=resolve_vk(self._hotkey_name) or VK_F8, name=self._hotkey_name
        )
        # 必须注册到本窗口句柄：hwnd=0 的线程消息不会被 Qt 派发
        self._hotkey_hwnd = int(self.winId())
        self._hotkey.register(self._hotkey_hwnd)
        # 用窗口子对象的定时器：窗口销毁后回调自动失效（避免悬空调用）
        self._startup_timer = QTimer(self)
        self._startup_timer.setSingleShot(True)
        self._startup_timer.timeout.connect(self._startup_elevation_flow)
        self._startup_timer.start(0)

    def nativeEvent(self, event_type, message):
        """处理 WM_HOTKEY 急停消息。

        Qt 6 中 RegisterHotKey 投递的队列消息经 QWidget.nativeEvent 到达，
        QAbstractNativeEventFilter 收不到该路径的消息。
        """
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(message.__int__())
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey.hotkey_id:
                self._on_failsafe()
                return True, 0
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._startup_timer.stop()  # 窗口关闭后不再执行启动逻辑
        self._stop()
        if self._diagnose_thread is not None and self._diagnose_thread.isRunning():
            self._diagnose_thread.wait(THREAD_WAIT_TIMEOUT_MS)
        self._hotkey.unregister(self._hotkey_hwnd)
        logging.getLogger().removeHandler(self._log_handler)
        super().closeEvent(event)

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._refresh_title()

    def _refresh_title(self) -> None:
        self.setWindowTitle(f"{WINDOW_TITLE} *" if self._dirty else WINDOW_TITLE)

    def _save(self) -> None:
        store.save(self._config, self._config_path)
        self._dirty = False
        self._refresh_title()
        logger.info("配置已保存：%s", self._config_path)
        self.statusBar().showMessage(f"配置已保存：{self._config_path}")
        self._apply_hotkey_config()

    def _apply_hotkey_config(self) -> None:
        """保存后使急停键配置生效（热键变更时重新注册）。"""
        name = self._config.automation.failsafe_hotkey or DEFAULT_HOTKEY_NAME
        if name == self._hotkey_name:
            return
        vk = resolve_vk(name)
        if vk is None:
            logger.warning("不支持的急停热键 %s，继续使用 %s", name, self._hotkey_name)
            return
        self._hotkey.unregister(self._hotkey_hwnd)
        self._hotkey = HotkeyRegistrar(vk=vk, name=name)
        self._hotkey.register(self._hotkey_hwnd)
        self._hotkey_name = name
        logger.info("急停热键已更新为 %s", name)

    def _reload(self) -> None:
        self._config = store.load(self._config_path)
        self._apply_config()

    def _reset(self) -> None:
        self._config = AppConfig.default()
        self._apply_config()
        self._mark_dirty()
        logger.info("已恢复默认配置（尚未保存，点击「保存」后写入文件）")
        self.statusBar().showMessage("已恢复默认配置（点击「保存」后生效）")

    def _apply_config(self) -> None:
        for page in (
            self.daily_page,
            self.order_hold_page,
            self.feature3_page,
            self.feature4_page,
            self.settings_page,
        ):
            page.set_config(self._config)
        self._dirty = False
        self._refresh_title()

    def _start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return
        self._save()  # 启动前先把当前配置落盘，避免“改了没保存就运行”
        dry_run = self._config.automation.dry_run
        if not dry_run and not self._confirm_real_mode():
            self.statusBar().showMessage("已取消启动（未确认真实模式）")
            return
        logger.info("启动任务（%s）", "干跑" if dry_run else "真实模式")
        self._runner = self._runner_factory(self._config)
        self._thread = _RunnerThread(self._runner, self)
        self._thread.finished.connect(self._on_runner_finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        if dry_run:
            self.statusBar().setStyleSheet("")
            self.statusBar().showMessage(STATUS_RUNNING_DRY)
        else:
            self.statusBar().setStyleSheet(STATUS_REAL_STYLE)
            self.statusBar().showMessage(STATUS_RUNNING_REAL)
        self._thread.start()

    def _real_mode_warning_text(self) -> str:
        """真实模式的告知文案（单独抽出，便于测试断言关键风险点已如实告知）。"""
        return (
            "即将以真实模式执行：程序会用系统级输入注入"
            "（真实移动鼠标 + 模拟真实按键）操作游戏窗口。\n\n"
            "· 每次点击/按键前都会把游戏窗口置于最顶层并置前，"
            "因此执行期间会抢前台，不宜同时操作其它软件\n"
            "· 真实鼠标会被移动到点击坐标；默认在点击后移回原位置"
            "（可在设置页关闭）\n"
            "· 会在游戏内产生真实操作，可能违反游戏用户协议，封号风险自负\n"
            f"· 运行中按 {self._hotkey_name} 可立即急停"
        )

    def _confirm_real_mode(self) -> bool:
        """真实模式启动前的确认：如实告知真实键鼠的副作用、急停方式与封号风险。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("确认真实模式")
        box.setText(self._real_mode_warning_text() + "\n\n是否继续？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _stop(self) -> None:
        if self._runner is not None:
            self._runner.request_stop()
        if self._thread is not None and self._thread.isRunning():
            self._thread.wait(THREAD_WAIT_TIMEOUT_MS)

    def _on_stop_clicked(self) -> None:
        """停止按钮：给出日志与状态栏反馈。"""
        if self._runner is None:
            logger.info("停止：当前没有运行中的任务")
            self.statusBar().showMessage("当前没有运行中的任务")
            return
        logger.info("已请求停止任务")
        self.statusBar().showMessage("已请求停止…")
        self._stop()

    def _on_runner_finished(self) -> None:
        self._thread = None
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.statusBar().setStyleSheet("")
        self.statusBar().showMessage(self._idle_status)

    def _on_failsafe(self) -> None:
        logger.info("急停触发（F8）")
        self._stop()

    def _on_diagnose(self) -> None:
        if self._diagnose_thread is not None and self._diagnose_thread.isRunning():
            return  # 防重复点击
        self.settings_page.diagnose_button.setEnabled(False)
        self.statusBar().showMessage("窗口诊断中…")
        self._diagnose_thread = _DiagnoseThread(
            self._config.automation.window_title_keyword, get_debug_dir(), self
        )
        self._diagnose_thread.finished_message.connect(self._on_diagnose_finished)
        self._diagnose_thread.finished.connect(self._on_diagnose_thread_finished)
        self._diagnose_thread.start()

    def _on_diagnose_finished(self, message: str, needs_elevation: bool) -> None:
        logger.info("%s", message)
        self.statusBar().showMessage(message)
        if needs_elevation:
            self._show_elevation_hint()
            self._offer_elevated_restart()

    def _on_diagnose_thread_finished(self) -> None:
        self.settings_page.diagnose_button.setEnabled(True)
        self._diagnose_thread = None

    def _show_elevation_hint(self) -> None:
        """设置页显示提权提示（自动检测到权限不足时）。"""
        self.settings_page.elevation_hint_label.setText(
            "检测到游戏以管理员权限运行，本工具为普通权限，无法置前/截图"
            "（后续键鼠模拟同样会被系统拦截）。请点击下方「以管理员身份重启」。"
        )
        self.settings_page.elevation_hint_label.setVisible(True)

    def _check_elevation_need(self) -> None:
        """启动时自动检测：游戏窗口权限更高而本工具未提权时给出提示。"""
        if is_process_elevated():
            return
        hwnd = find_window(self._config.automation.window_title_keyword)
        if hwnd is None or is_window_elevated(hwnd) is not True:
            return
        logger.warning("检测到游戏窗口以管理员权限运行，本工具为普通权限，建议以管理员身份重启")
        self._show_elevation_hint()

    def _startup_elevation_flow(self) -> None:
        """启动完成后：权限检测（提示条）+ 自动走一次提权重启流程。"""
        self._check_elevation_need()
        if not self._auto_elevate_enabled:
            return
        self._auto_elevate_if_needed()

    def _auto_elevate_if_needed(self) -> None:
        """非管理员时自动执行「以管理员身份重启」的询问流程。

        已是管理员时只记录日志与状态栏提示，不弹窗（避免每次启动都需确认）；
        配置为「不再询问」时不弹框，直接发起提权重启（UAC 取消则继续运行）。
        """
        if is_process_elevated():
            logger.info("当前已是管理员权限")
            self.statusBar().showMessage("当前已是管理员权限")
            return
        if not self._config.automation.ask_elevation_on_start:
            logger.info("已设置「不再询问」，直接以管理员身份重启")
            self._perform_elevated_restart()
            return
        logger.info("启动时未以管理员权限运行，询问是否提权重启")
        confirmed, dont_ask = self._ask_restart_confirmation(allow_dont_ask=True)
        if dont_ask:
            self._set_ask_elevation_on_start(False)
        if confirmed:
            self._perform_elevated_restart()
        else:
            self.statusBar().showMessage("已取消以管理员身份重启")

    def _set_ask_elevation_on_start(self, enabled: bool) -> None:
        """记录「不再询问」偏好并立即落盘（启动阶段尚无未保存改动）。"""
        self._config.automation.ask_elevation_on_start = enabled
        self.settings_page.set_config(self._config)
        store.save(self._config, self._config_path)
        logger.info("已更新「启动时自动询问提权」为 %s 并保存配置", enabled)

    def _relaunch_args(self) -> list[str]:
        return ["--config", str(self._config_path)]

    def _offer_elevated_restart(self) -> None:
        answer = QMessageBox.question(
            self,
            "需要管理员权限",
            "游戏以管理员权限运行，本工具权限不足，无法还原窗口/截图。\n是否立即以管理员身份重启本工具？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._perform_elevated_restart()

    def _ask_restart_confirmation(self, allow_dont_ask: bool = False) -> tuple[bool, bool]:
        """弹确认框，返回 (是否重启, 是否勾选「不再询问」)。

        allow_dont_ask=True 时才显示「不再询问」勾选框（启动自动流程使用）。
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("以管理员身份重启")
        box.setText("将以管理员权限重新启动本工具（会弹出 UAC 确认），当前窗口会关闭。是否继续？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        dont_ask_box = None
        if allow_dont_ask:
            dont_ask_box = QCheckBox("不再询问（以后启动直接提权重启，可在设置页改回）")
            box.setCheckBox(dont_ask_box)
        answer = box.exec()
        return answer == QMessageBox.StandardButton.Yes, bool(dont_ask_box and dont_ask_box.isChecked())

    def _on_restart_admin_clicked(self) -> None:
        if is_process_elevated():
            QMessageBox.information(
                self,
                "已经是管理员权限",
                "本工具当前已以管理员权限运行，无需重启。",
            )
            self.statusBar().showMessage("当前已是管理员权限，无需重启")
            return
        confirmed, _ = self._ask_restart_confirmation()
        if confirmed:
            self._perform_elevated_restart()
        else:
            self.statusBar().showMessage("已取消以管理员身份重启")

    def _perform_elevated_restart(self) -> None:
        if restart_as_admin(self._relaunch_args()):
            self.statusBar().showMessage("正在以管理员身份重启…")
            self.close()
            QApplication.instance().quit()
        else:
            self.statusBar().showMessage("以管理员身份重启被取消或失败（详见日志）")
