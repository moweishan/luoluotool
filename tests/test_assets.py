"""静态资源完整性测试：图标必须是真实格式，防止「伪装成 .ico 的 PNG」再次入库。

背景：`assets/icons/luoluoTool.ico` 曾是一份改了扩展名的 PNG，
Qt 按魔数校验后拒绝加载（日志「图标文件格式非法，已跳过」），
窗口/任务栏图标静默降级，且 Phase 7 打包 exe 图标（`--icon=`）会失败。
"""

import ctypes
import struct
import sys
from pathlib import Path

import pytest

from luoluotool.gui.main_window import _is_valid_icon_file
from luoluotool.utils.paths import get_icons_dir

ICO_MAGIC = b"\x00\x00\x01\x00"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICONDIR_SIZE = 6
ICONDIRENTRY_SIZE = 16
REQUIRED_SIZES = {16, 32, 48, 256}


def _icon_path() -> Path:
    return get_icons_dir() / "luoluoTool.ico"


def _entries(path: Path) -> list[tuple[int, int, int, int, int]]:
    """解析 ICONDIR/ICONDIRENTRY，返回 [(宽, 高, 字节数, 偏移, 位深)]。"""
    data = path.read_bytes()
    reserved, image_type, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, image_type) == (0, 1), "ICO 头字段非法"
    assert count > 0, "ICO 未包含任何图像项"
    entries = []
    for index in range(count):
        offset = ICONDIR_SIZE + index * ICONDIRENTRY_SIZE
        width, height, _colors, _reserved, planes, bit_count, size, image_offset = struct.unpack_from(
            "<BBBBHHII", data, offset
        )
        entries.append(
            (width or 256, height or 256, size, image_offset, bit_count)
        )
        assert planes == 1, f"第 {index} 项 planes 异常：{planes}"
    return entries


def test_ico_is_a_real_ico_container_not_a_renamed_png() -> None:
    """核心回归：.ico 必须是 ICO 容器，而不是改了扩展名的 PNG。"""
    path = _icon_path()
    assert path.is_file(), f"图标文件缺失：{path}"
    head = path.read_bytes()[:8]
    assert head != PNG_MAGIC, "luoluoTool.ico 是伪装成 ICO 的 PNG"
    assert head[:4] == ICO_MAGIC, "luoluoTool.ico 缺少 ICO 魔数 00 00 01 00"


def test_ico_entries_are_within_file_and_use_supported_payloads() -> None:
    """每一项的偏移/长度都要落在文件内，载荷为 PNG 或 DIB（BITMAPINFOHEADER=40）。"""
    path = _icon_path()
    data = path.read_bytes()
    for width, height, size, image_offset, bit_count in _entries(path):
        assert image_offset + size <= len(data), f"{width}x{height} 项越界"
        assert bit_count == 32, f"{width}x{height} 项位深应为 32，实际 {bit_count}"
        payload = data[image_offset : image_offset + size]
        is_png = payload.startswith(PNG_MAGIC)
        is_dib = struct.unpack_from("<I", payload, 0)[0] == 40
        assert is_png or is_dib, f"{width}x{height} 项既不是 PNG 也不是 DIB"
        assert width == height, f"{width}x{height} 项不是正方形"


def test_ico_contains_the_sizes_windows_and_pyinstaller_need() -> None:
    """必须含 16/32/48/256 等尺寸，否则任务栏与资源管理器会缩放糊掉。"""
    sizes = {width for width, *_ in _entries(_icon_path())}
    missing = REQUIRED_SIZES - sizes
    assert not missing, f"缺少尺寸：{sorted(missing)}（现有 {sorted(sizes)}）"


def test_icon_files_pass_the_app_validator() -> None:
    """应用自身的魔数校验必须通过（此前 .ico 正是在这里被跳过）。"""
    icons_dir = get_icons_dir()
    assert _is_valid_icon_file(icons_dir / "luoluoTool.ico") is True
    assert _is_valid_icon_file(icons_dir / "luoluoTool.png") is True


@pytest.mark.skipif(sys.platform != "win32", reason="LoadImageW 仅在 Windows 可用")
def test_windows_shell_can_load_the_icon() -> None:
    """Win32 层面可加载：等价于任务栏/资源管理器/PyInstaller 读图标的路径。"""
    IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x0010, 0x0040
    user32 = ctypes.windll.user32
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint
    ]
    handle = user32.LoadImageW(
        None, str(_icon_path()), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
    )
    assert handle, "Windows LoadImageW 无法加载该 ICO（打包 exe 图标会失败）"
    ctypes.windll.user32.DestroyIcon(ctypes.c_void_p(handle))


def test_source_png_is_kept_as_the_icon_source() -> None:
    """保留源图：窗口图标优先用 .png，且它是重新生成 .ico 的输入。"""
    png = get_icons_dir() / "luoluoTool.png"
    assert png.is_file() and png.read_bytes()[:8] == PNG_MAGIC
    assert _entries(_icon_path()), "ICO 至少应有一项"


def test_largest_frame_actually_contains_visible_pixels() -> None:
    """防止「结构合法但内容全透明/空白」的坏图标：最大帧必须有可见像素。"""
    from PySide6.QtGui import QImage

    path = _icon_path()
    data = path.read_bytes()
    largest = max(_entries(path), key=lambda item: item[0] * item[1])
    width, height, size, image_offset, _bit = largest
    image = QImage.fromData(data[image_offset : image_offset + size])
    assert not image.isNull(), f"{width}x{height} 帧无法解码"
    assert (image.width(), image.height()) == (width, height)
    converted = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = bytes(converted.constBits())
    opaque = sum(1 for index in range(3, len(raw), 4) if raw[index] > 8)
    assert opaque > width * height * 0.05, f"{width}x{height} 帧几乎全透明（可见像素 {opaque}）"
