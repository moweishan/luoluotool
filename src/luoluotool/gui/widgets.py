"""通用小组件：日志面板 Handler。"""

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit


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
