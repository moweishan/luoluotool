"""PyInstaller 运行时钩子（只在打包产物里生效）：让窗口化进程的 stdio 安全可用。

背景（2026-09-19 用户要求打包后**不显示 cmd 窗口** → `console=False`）：
窗口化进程没有控制台，PyInstaller 会把 `sys.stdout` / `sys.stderr` 置为 `None`；
而项目的 `utils/logging_setup.setup_logging()` 会注册一个写 `stderr` 的 `StreamHandler`，
`None` 流会让每次日志 emit 都抛 AttributeError（不影响日志文件与 GUI 日志面板，但会产生噪音）。

本钩子把缺失的流接到空设备；若进程带有有效的重定向句柄（例如命令行把输出重定向到文件），
两个流本来就有效，本钩子不做任何事——因此 `--version` / `--validate-config` 这类
"重定向后可见"的 CLI 行为不受影响。
"""

import os
import sys

if sys.stdout is None or sys.stderr is None:
    _devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
    if sys.stdout is None:
        sys.stdout = _devnull
    if sys.stderr is None:
        sys.stderr = _devnull
