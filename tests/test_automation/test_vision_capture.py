"""automation.vision 取景 / 渲染路径测试：截图转数组、黑帧兜底与客户区原点几何。

用假 GDI 校验 BitBlt 源点 / PrintWindow 裁剪，不依赖真实游戏窗口。
模板加载、匹配原语与多尺度搜索的用例见同目录 test_vision.py。
"""

import logging

import numpy as np
import pytest

from luoluotool.automation import vision

from test_automation.vision_helpers import _haystack


# ---------------------------------------------------------------- 截图 → 数组


def test_capture_client_bgr_converts_bgra_bits(monkeypatch) -> None:
    """截图像素（BGRA 原始位）→ numpy 数组：形状/通道顺序/宽度补齐都要正确。"""
    width, height = 3, 2
    # 每行 4 字节对齐：3 像素 ×4 通道 = 12 字节（已是 4 的倍数）
    bits = bytes(
        [
            1, 2, 3, 0,     # 像素1 BGR
            4, 5, 6, 0,     # 像素2
            7, 8, 9, 0,     # 像素3
            10, 11, 12, 0, 13, 14, 15, 0, 16, 17, 18, 0,
        ]
    )
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, bits))
    image = vision.capture_client_bgr(12345)
    assert image.shape == (height, width, 3)
    assert tuple(image[0, 0]) == (1, 2, 3)
    assert tuple(image[1, 2]) == (16, 17, 18)


def test_capture_client_bgr_handles_padding(monkeypatch) -> None:
    """宽度不是 4 的倍数时，行末可能有补齐字节，必须正确跳过。"""
    width, height = 1, 1
    bits = bytes([9, 8, 7, 0])      # 1 像素 + 3 字节补齐
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, bits))
    image = vision.capture_client_bgr(1)
    assert tuple(image[0, 0]) == (9, 8, 7)


def test_capture_client_bgr_reports_render_failure(monkeypatch) -> None:
    """渲染失败（窗口已关闭/无权限）→ 先试兜底链；全失败才给可读错误，不返回空图（评审 P2-7）。"""
    def boom(hwnd: int):
        raise vision.VisionError("截图失败：窗口已关闭")

    monkeypatch.setattr(vision, "_render_client_bits", boom)
    monkeypatch.setattr(vision, "_render_client_bgr_fallback", lambda hwnd: None)
    with pytest.raises(vision.VisionError) as excinfo:
        vision.capture_client_bgr(1)

    assert "取景失败" in str(excinfo.value)
    assert "窗口已关闭" in str(excinfo.value)          # 主取景的失败原因要带出来


def test_capture_client_bgr_falls_back_when_primary_raises(monkeypatch) -> None:
    """回归（评审 P2-7）：主取景**抛异常**（不只是黑帧）时也必须走兜底链拿画面。

    旧实现只在 `is_blank_frame()` 为真时兜底：`GetWindowDC`/`CreateCompatibleBitmap` 失败
    （权限不足、窗口已关闭）会让整次识别以异常收场 —— 明明屏幕 BitBlt 还能用。
    """
    def boom(hwnd: int):
        raise vision.VisionError("CreateCompatibleBitmap 失败（模拟）")

    canvas = _haystack(40, 60)
    monkeypatch.setattr(vision, "_render_client_bits", boom)
    monkeypatch.setattr(vision, "_render_client_bgr_fallback", lambda hwnd: canvas)

    assert vision.capture_client_bgr(1) is canvas


# ---------------------------------------------------------------- 黑帧兜底


def test_is_blank_frame_detection() -> None:
    """纯色大图判为黑帧；有内容的图与极小图不算。"""
    assert vision.is_blank_frame(np.zeros((40, 40, 3), dtype=np.uint8)) is True
    assert vision.is_blank_frame(np.full((40, 40, 3), 200, dtype=np.uint8)) is True
    assert vision.is_blank_frame(_haystack(40, 40)) is False
    assert vision.is_blank_frame(np.zeros((1, 1, 3), dtype=np.uint8)) is False   # 太小无法判断


def test_capture_client_bgr_falls_back_on_blank_frame(monkeypatch, caplog) -> None:
    """PrintWindow 取到纯黑帧时自动换其它取景方式（GPU 独占渲染游戏的实测问题）。"""
    caplog.set_level(logging.WARNING)
    width, height = 40, 40
    blank_bits = bytes(width * height * 4)
    good = _haystack(height, width)
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, blank_bits))
    monkeypatch.setattr(vision, "_render_client_bgr_fallback", lambda hwnd: good.copy())

    image = vision.capture_client_bgr(1)
    assert image.std() > 1                      # 拿到的是有内容的帧
    assert image.shape == good.shape
    assert "纯色" in caplog.text or "黑帧" in caplog.text


def test_capture_client_bgr_reports_actionable_error_when_all_blank(monkeypatch) -> None:
    """所有取景方式都是黑帧 → 可读错误并给出「以管理员身份运行 / 让窗口可见」的指引。"""
    width, height = 40, 40
    blank_bits = bytes(width * height * 4)
    monkeypatch.setattr(vision, "_render_client_bits", lambda hwnd: (width, height, blank_bits))
    monkeypatch.setattr(vision, "_render_client_bgr_fallback", lambda hwnd: None)

    with pytest.raises(vision.VisionError) as excinfo:
        vision.capture_client_bgr(1)
    message = str(excinfo.value)
    assert "纯色" in message or "黑帧" in message
    assert "管理员" in message and "窗口" in message


# ------------------------------------------ 取景原点必须是客户区左上（"坐标偏下"bug 回归）


WINDOW_W, WINDOW_H = 30, 20          # 整个窗口（含标题栏/边框）
CLIENT_W, CLIENT_H = 20, 12          # 客户区
CLIENT_OFFSET = (5, 4)               # 客户区在窗口内的偏移（真实实测本作为 (9, 37)）


def _window_pixels() -> np.ndarray:
    """窗口位图内容：每个像素编码自己的坐标（B=x, G=y），便于验证裁剪位置。"""
    pixels = np.zeros((WINDOW_H, WINDOW_W, 4), dtype=np.uint8)
    for y in range(WINDOW_H):
        for x in range(WINDOW_W):
            pixels[y, x] = (x % 256, y % 256, 9, 255)
    return pixels


def _expected_client_pixels() -> np.ndarray:
    """期望的客户区像素 = 窗口位图按客户区偏移裁出来的那块。"""
    offset_x, offset_y = CLIENT_OFFSET
    return _window_pixels()[offset_y : offset_y + CLIENT_H, offset_x : offset_x + CLIENT_W, :3]


class _FakeBitmap:
    """最小假位图：内部存 numpy (H, W, 4)，字节格式与 GetBitmapBits(True) 一致。"""

    def __init__(self, width: int = 0, height: int = 0) -> None:
        self.pixels = np.zeros((max(int(height), 0), max(int(width), 0), 4), dtype=np.uint8)

    def CreateCompatibleBitmap(self, dc, width, height):      # noqa: N802 (pywin32 接口)
        self.pixels = np.zeros((int(height), int(width), 4), dtype=np.uint8)
        return self

    def GetBitmapBits(self, flag):                            # noqa: N802
        return self.pixels.tobytes()

    def GetHandle(self):                                      # noqa: N802
        return id(self)


class _FakeDC:
    """最小假 DC：BitBlt 真的按源坐标搬像素，用来校验取景裁剪的几何。

    所有派生 DC 共享同一份调用日志（`calls`），因为 BitBlt 实际发生在内存 DC 上。
    """

    def __init__(self, bitmap: _FakeBitmap | None = None, calls: list | None = None) -> None:
        self.bitmap = bitmap if bitmap is not None else _FakeBitmap()
        self.calls: list[tuple] = calls if calls is not None else []

    def CreateCompatibleDC(self):                             # noqa: N802
        return _FakeDC(calls=self.calls)

    def SelectObject(self, bitmap):                           # noqa: N802
        self.bitmap = bitmap
        return bitmap

    def GetSafeHdc(self):                                     # noqa: N802
        return self

    def BitBlt(self, dest, size, source, source_point, rop):   # noqa: N802
        self.calls.append((tuple(dest), tuple(size), tuple(source_point)))
        dx, dy = dest
        width, height = size
        sx, sy = source_point
        self.bitmap.pixels[dy : dy + height, dx : dx + width] = (
            source.bitmap.pixels[sy : sy + height, sx : sx + width]
        )

    def DeleteDC(self):                                       # noqa: N802
        return None


@pytest.fixture
def fake_gdi(monkeypatch):
    """注入假 win32gui/win32ui + 假窗口几何，并替换掉 ctypes 的 PrintWindow。"""
    import win32gui
    import win32ui

    from luoluotool.automation import window as window_module

    window_dc = _FakeDC(_FakeBitmap())
    window_dc.bitmap.pixels = _window_pixels()
    print_targets: list[tuple[int, ...]] = []

    monkeypatch.setattr(win32gui, "GetWindowDC", lambda hwnd: 1234)
    monkeypatch.setattr(win32gui, "DeleteObject", lambda handle: None)
    monkeypatch.setattr(win32gui, "ReleaseDC", lambda hwnd, dc: None)
    monkeypatch.setattr(win32ui, "CreateDCFromHandle", lambda handle: window_dc)
    monkeypatch.setattr(win32ui, "CreateBitmap", _FakeBitmap)
    monkeypatch.setattr(window_module, "get_client_rect", lambda hwnd: (0, 0, CLIENT_W, CLIENT_H))
    monkeypatch.setattr(window_module, "get_window_size", lambda hwnd: (WINDOW_W, WINDOW_H))
    monkeypatch.setattr(window_module, "client_area_offset", lambda hwnd: CLIENT_OFFSET)

    def fake_print_window(hwnd, hdc, flag):
        print_targets.append(hdc.bitmap.pixels.shape)
        hdc.bitmap.pixels = _window_pixels()          # PrintWindow 画的是整个窗口
        return True

    monkeypatch.setattr(vision, "_print_window", fake_print_window)
    return window_dc.calls, print_targets        # 共享调用日志（渲染时会往里追加）


def test_bitblt_renderer_starts_at_client_origin(fake_gdi) -> None:
    """BitBlt(窗口DC) 必须从**客户区左上**抓，不能从窗口 DC 的 (0,0)（那是标题栏）。

    回归（2026-09-20 用户实测）：从 (0,0) 抓会让画面顶部多出标题栏、底部缺一截，
    识别坐标随之整体偏下"标题栏高度"（本作实测偏 37px）。
    """
    calls, _ = fake_gdi

    width, height, bits = vision._render_client_bits_bitblt(4321)

    assert (width, height) == (CLIENT_W, CLIENT_H)
    assert calls, "必须真的调用了 BitBlt"
    assert calls[-1][2] == CLIENT_OFFSET, "BitBlt 源点必须是客户区偏移，不能是 (0, 0)"
    assert np.array_equal(vision._bits_to_bgr(width, height, bits), _expected_client_pixels())
    assert not np.array_equal(
        vision._bits_to_bgr(width, height, bits), _window_pixels()[:CLIENT_H, :CLIENT_W, :3]
    ), "抓的不能是窗口左上角那块（那正是旧的错误行为）"


def test_printwindow_renderer_crops_client_area(fake_gdi) -> None:
    """PrintWindow 画的是整个窗口：必须先按窗口尺寸渲染，再按客户区偏移裁出客户区。"""
    calls, print_targets = fake_gdi

    width, height, bits = vision._render_client_bits_printwindow(
        4321, vision.PW_RENDERFULLCONTENT
    )

    assert (width, height) == (CLIENT_W, CLIENT_H)
    assert print_targets == [(WINDOW_H, WINDOW_W, 4)], "渲染目标必须是整个窗口尺寸的位图"
    assert calls[-1] == ((0, 0), (CLIENT_W, CLIENT_H), CLIENT_OFFSET), "裁剪源点必须是客户区偏移"
    assert np.array_equal(vision._bits_to_bgr(width, height, bits), _expected_client_pixels())


def test_printwindow_clientonly_renderer_crops_client_area(fake_gdi) -> None:
    """PW_CLIENTONLY 同样按窗口尺寸渲染 + 裁剪（两种 flag 走同一套几何）。"""
    width, height, bits = vision._render_client_bits_printwindow(4321, vision.PW_CLIENTONLY)

    assert (width, height) == (CLIENT_W, CLIENT_H)
    assert np.array_equal(vision._bits_to_bgr(width, height, bits), _expected_client_pixels())
