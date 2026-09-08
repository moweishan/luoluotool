"""通用小组件：日志面板 Handler 与 WM_HOTKEY 原生事件过滤器。"""

import ctypes
import logging

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit

from luoluotool.automation.hotkey import WM_HOTKEY


class LogPanelHandler(logging.Handler, QObject):
    """把 logging 记录转发到日志面板（跨线程经 Qt 信号投递到 UI 线程）。"""

    record_emitted = Signal(str)

    def __init__(self, panel: QPlainTextEdit) -> None:
        logging.Handler.__init__(self)
        QObject.__init__(self)
        self.record_emitted.connect(panel.appendPlainText)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        self.record_emitted.emit(self.format(record))


class HotkeyEventFilter(QAbstractNativeEventFilter):
    """Windows WM_HOTKEY 消息 → 回调（急停）。"""

    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG" and message:
            msg = ctypes.wintypes.MSG.from_address(message.__int__())
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                self._callback()
                return True, 0
        return False, 0
