"""合成指针输入：触摸/笔事件注入，**不移动真实光标**。

实测（2026-09-15）：本通道对目标游戏有效，且注入前后真实光标位置不变。
实现要点：
- 客户区坐标 → `ClientToScreen` 屏幕坐标（坐标单位为物理像素，与进程 DPI 感知一致）；
- `hwndTarget` 必须指向目标窗口，且注入时窗口应在前台（由上层就绪守卫保证）；
- 优先现代 API（Win10 1809+）：`CreateSyntheticPointerDevice` + `InjectSyntheticPointerInput`；
  不可用时回退 `InitializeTouchInjection` + `InjectTouchInput`；
- 两者都不可用或注入被拒绝 → 抛 `WindowUnavailableError`（消息可读，绝不静默）。

已知限制（2026-09-15 实测）：Windows **不会把注入的触摸再合成为鼠标事件**（Qt 窗口只收到
`TouchBegin/TouchEnd`，不产生 `mousePressEvent`）。本通道面向直接读取 `WM_POINTER` 的目标
（例如本游戏）；需要驱动常规窗口鼠标交互时请改用窗口消息通道。
"""

import ctypes
import logging
import time
from collections.abc import Callable
from ctypes import wintypes

import win32gui

from luoluotool.automation.errors import WindowUnavailableError
from luoluotool.automation.window import window_exists

logger = logging.getLogger(__name__)

PT_MOUSE = 1
PT_TOUCH = 2
PT_PEN = 3
POINTER_TYPE_BY_NAME: dict[str, int] = {"touch": PT_TOUCH, "pen": PT_PEN}

POINTER_FEEDBACK_DEFAULT = 0x00000001
TOUCH_FEEDBACK_DEFAULT = 0x00000001

POINTER_FLAG_INRANGE = 0x00000002
POINTER_FLAG_INCONTACT = 0x00000004
POINTER_FLAG_PRIMARY = 0x00002000
POINTER_FLAG_DOWN = 0x00010000
POINTER_FLAG_UP = 0x00040000

TOUCH_FLAG_NONE = 0x00000000
TOUCH_MASK_CONTACTAREA = 0x00000001
TOUCH_MASK_ORIENTATION = 0x00000002
TOUCH_MASK_PRESSURE = 0x00000004
PEN_MASK_PRESSURE = 0x00000001

TAP_HOLD_SECONDS = 0.05
CONTACT_PRESSURE = 32000


class POINTER_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerType", wintypes.DWORD),
        ("pointerId", wintypes.DWORD),
        ("frameId", wintypes.DWORD),
        ("pointerFlags", wintypes.DWORD),
        ("sourceDevice", wintypes.HANDLE),
        ("hwndTarget", wintypes.HWND),
        ("ptPixelLocation", wintypes.POINT),
        ("ptHimetricLocation", wintypes.POINT),
        ("ptPixelLocationRaw", wintypes.POINT),
        ("ptHimetricLocationRaw", wintypes.POINT),
        ("dwTime", wintypes.DWORD),
        ("historyCount", wintypes.DWORD),
        ("InputData", ctypes.c_int32),
        ("dwKeyStates", wintypes.DWORD),
        ("PerformanceCount", ctypes.c_uint64),
        ("ButtonChangeType", ctypes.c_int32),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class TOUCH_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("touchFlags", wintypes.DWORD),
        ("touchMask", wintypes.DWORD),
        ("rcContact", RECT),
        ("rcContactRaw", RECT),
        ("orientation", wintypes.DWORD),
        ("pressure", wintypes.DWORD),
    ]


class PEN_INFO(ctypes.Structure):
    _fields_ = [
        ("pointerInfo", POINTER_INFO),
        ("penMask", wintypes.DWORD),
        ("pressure", wintypes.DWORD),
        ("rotation", wintypes.DWORD),
        ("tiltX", ctypes.c_int32),
        ("tiltY", ctypes.c_int32),
    ]


class POINTER_TYPE_INFO(ctypes.Structure):
    """与 winuser.h 布局一致（x64 下 152 字节，单测有断言）。"""

    class _Union(ctypes.Union):
        _fields_ = [("touchInfo", TOUCH_INFO), ("penInfo", PEN_INFO)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _Union)]


def _configure_prototypes(user32) -> None:
    """设置正确的函数签名：x64 下句柄是 64 位，若不声明会被按 32 位转换而溢出。

    测试注入的假实现不支持设置这些属性，此时忽略（不影响注入逻辑本身）。
    """
    try:
        user32.CreateSyntheticPointerDevice.restype = wintypes.HANDLE
        user32.CreateSyntheticPointerDevice.argtypes = [wintypes.DWORD, wintypes.ULONG, wintypes.DWORD]
        user32.InjectSyntheticPointerInput.restype = wintypes.BOOL
        user32.InjectSyntheticPointerInput.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.UINT]
        user32.DestroySyntheticPointerDevice.restype = None
        user32.DestroySyntheticPointerDevice.argtypes = [wintypes.HANDLE]
        user32.InitializeTouchInjection.restype = wintypes.BOOL
        user32.InitializeTouchInjection.argtypes = [wintypes.UINT, wintypes.DWORD]
        user32.InjectTouchInput.restype = wintypes.BOOL
        user32.InjectTouchInput.argtypes = [wintypes.UINT, ctypes.c_void_p]
    except (AttributeError, TypeError):
        logger.debug("当前 user32 实现不支持声明函数签名（测试注入时属正常）")


def _fill_pointer(pointer: POINTER_INFO, hwnd: int, point: tuple[int, int], pointer_type: int, down: bool) -> None:
    pointer.pointerType = pointer_type
    pointer.pointerId = 0
    pointer.hwndTarget = hwnd
    pointer.ptPixelLocation = wintypes.POINT(point[0], point[1])
    pointer.ptHimetricLocation = wintypes.POINT(point[0], point[1])
    flags = POINTER_FLAG_INRANGE | POINTER_FLAG_INCONTACT
    pointer.pointerFlags = flags | (POINTER_FLAG_DOWN | POINTER_FLAG_PRIMARY if down else POINTER_FLAG_UP)


def _build_type_info(hwnd: int, point: tuple[int, int], pointer_type: str, down: bool) -> POINTER_TYPE_INFO:
    code = POINTER_TYPE_BY_NAME[pointer_type]
    info = POINTER_TYPE_INFO()
    info.type = code
    if pointer_type == "pen":
        _fill_pointer(info.penInfo.pointerInfo, hwnd, point, code, down)
        info.penInfo.penMask = PEN_MASK_PRESSURE
        info.penInfo.pressure = CONTACT_PRESSURE // 64
    else:
        _fill_pointer(info.touchInfo.pointerInfo, hwnd, point, code, down)
        info.touchInfo.touchFlags = TOUCH_FLAG_NONE
        info.touchInfo.touchMask = (
            TOUCH_MASK_CONTACTAREA | TOUCH_MASK_ORIENTATION | TOUCH_MASK_PRESSURE
        )
        info.touchInfo.orientation = 90
        info.touchInfo.pressure = CONTACT_PRESSURE
        info.touchInfo.rcContact = RECT(point[0] - 2, point[1] - 2, point[0] + 2, point[1] + 2)
    return info


class SyntheticPointerSender:
    """真实模式输入通道：合成指针 tap（不移动真实光标）。"""

    def __init__(
        self,
        hwnd: int,
        pointer_type: str = "touch",
        log: logging.Logger | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.hwnd = hwnd
        self.pointer_type = pointer_type if pointer_type in POINTER_TYPE_BY_NAME else "touch"
        self._logger = log or logger
        self._sleep = sleep if sleep is not None else time.sleep

    # ---- InputSender 协议 ----
    def move_to(self, x: int, y: int) -> None:
        """合成指针没有"悬停"语义（触摸/笔的 tap 自带坐标），此处只记录并忽略。"""
        self._logger.debug(
            "合成指针通道不支持悬停，已忽略 move_to(%d, %d)（点击时坐标会随 tap 一起发送）", x, y
        )

    def click(self, x: int, y: int) -> None:
        self.click_at(x, y)

    def click_at(self, x: int, y: int) -> None:
        if not window_exists(self.hwnd):
            raise WindowUnavailableError(f"游戏窗口已关闭，无法注入（hwnd={self.hwnd}）")
        screen_point = win32gui.ClientToScreen(self.hwnd, (x, y))
        self._tap(screen_point)
        self._logger.info(
            "已注入合成指针点击：客户区 (%d, %d) → 屏幕 (%d, %d)（hwnd=%s，类型=%s，光标未移动）",
            x, y, screen_point[0], screen_point[1], self.hwnd, self.pointer_type,
        )

    def key_tap(self, vk: int) -> None:
        """合成指针发不了键盘事件，委托给窗口消息通道（惰性导入避免循环依赖）。"""
        from luoluotool.automation.input_sender import WindowMessageSender

        WindowMessageSender(self.hwnd, self._logger, self._sleep).key_tap(vk)

    # ---- 注入实现 ----
    def _tap(self, screen_point: tuple[int, int]) -> None:
        if self._try_synthetic_device(screen_point):
            return
        if self._try_legacy_touch(screen_point):
            return
        raise WindowUnavailableError(
            "合成指针注入不可用：系统不支持 CreateSyntheticPointerDevice / InitializeTouchInjection，"
            "或注入被系统拒绝（请确认窗口在前台、且工具与游戏权限一致）"
        )

    def _try_synthetic_device(self, screen_point: tuple[int, int]) -> bool:
        user32 = ctypes.windll.user32
        if not hasattr(user32, "CreateSyntheticPointerDevice"):
            self._logger.debug("CreateSyntheticPointerDevice 不可用，尝试后备 API")
            return False
        _configure_prototypes(user32)
        device = user32.CreateSyntheticPointerDevice(
            POINTER_TYPE_BY_NAME[self.pointer_type], 1, POINTER_FEEDBACK_DEFAULT
        )
        if not device:
            self._logger.warning("CreateSyntheticPointerDevice 失败，尝试后备 API")
            return False
        try:
            for down in (True, False):
                info = _build_type_info(self.hwnd, screen_point, self.pointer_type, down)
                if not user32.InjectSyntheticPointerInput(device, ctypes.byref(info), 1):
                    self._logger.warning(
                        "InjectSyntheticPointerInput 失败（%s），尝试后备 API", "按下" if down else "抬起"
                    )
                    return False
                self._sleep(TAP_HOLD_SECONDS)
            return True
        finally:
            try:
                user32.DestroySyntheticPointerDevice(device)
            except Exception as exc:  # pragma: no cover - 释放失败不影响主流程
                self._logger.warning("释放合成指针设备失败：%s", exc)

    def _try_legacy_touch(self, screen_point: tuple[int, int]) -> bool:
        user32 = ctypes.windll.user32
        if not hasattr(user32, "InitializeTouchInjection"):
            return False
        _configure_prototypes(user32)
        if not user32.InitializeTouchInjection(1, TOUCH_FEEDBACK_DEFAULT):
            self._logger.warning("InitializeTouchInjection 失败")
            return False
        for down in (True, False):
            info = _build_type_info(self.hwnd, screen_point, "touch", down).touchInfo
            if not user32.InjectTouchInput(1, ctypes.byref(info)):
                self._logger.warning("InjectTouchInput 失败（%s）", "按下" if down else "抬起")
                return False
            self._sleep(TAP_HOLD_SECONDS)
        return True
