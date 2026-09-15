"""进程/窗口权限检测与 UAC 提权重启（Windows；不依赖 PySide6）。"""

import ctypes
import logging
import subprocess
import sys
from collections.abc import Sequence

import win32api
import win32con
import win32process
import win32security

logger = logging.getLogger(__name__)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SHELL_EXECUTE_MIN_SUCCESS = 32


def is_process_elevated() -> bool:
    """当前进程是否以管理员权限运行。"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        logger.warning("检测进程权限失败：%s", exc)
        return False


def is_window_elevated(hwnd: int) -> bool | None:
    """窗口所属进程是否以管理员权限运行；无法判断时返回 None。"""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception as exc:
        logger.warning("查询窗口进程失败：%s", exc)
        return None
    try:
        token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
        try:
            return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
        finally:
            token.Close()
    except Exception as exc:
        logger.warning("查询进程令牌失败：%s", exc)
        return None
    finally:
        process.Close()


def build_relaunch_command(extra_args: Sequence[str] = ()) -> tuple[str, str]:
    """返回 (可执行文件, 参数串)：源码运行走 `python -m luoluotool`，打包 exe 直接传参。"""
    if getattr(sys, "frozen", False):
        return sys.executable, subprocess.list2cmdline(list(extra_args))
    return sys.executable, subprocess.list2cmdline(["-m", "luoluotool", *extra_args])


def restart_as_admin(extra_args: Sequence[str] = ()) -> bool:
    """通过系统 UAC 提示以管理员身份重启本进程；成功发起返回 True。

    用户取消 UAC 时返回 False；调用方在成功后应退出当前进程。
    这是向系统"请求"提权（runas），不是绕过 UAC。
    """
    if sys.platform != "win32":
        logger.warning("非 Windows 平台，不支持以管理员身份重启")
        return False
    executable, parameters = build_relaunch_command(extra_args)
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters, None, 1)
    except Exception as exc:
        logger.exception("请求提权重启失败：%s", exc)
        return False
    if result <= SHELL_EXECUTE_MIN_SUCCESS:
        logger.warning("以管理员身份重启被取消或失败（ShellExecute 返回 %s）", result)
        return False
    logger.info("已请求以管理员身份重启：%s %s", executable, parameters)
    return True
