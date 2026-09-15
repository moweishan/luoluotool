"""自动化层异常类型（供 input_sender / pointer_sender 共用，避免循环导入）。"""


class WindowUnavailableError(RuntimeError):
    """目标窗口不可用，或当前输入通道无法注入（原因写入消息，必须可读）。"""
