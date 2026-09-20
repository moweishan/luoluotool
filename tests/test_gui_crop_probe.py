"""框选弹窗「在本图试识别」（D1）的界面用例（离屏）。

用户视角：框完一块，点一下「在本图试识别」，弹窗立刻告诉你 ——
"本图只找到你框的这一处"（放心存）还是"本图共 3 处相似，除你框的还有 2 处（位置…）"（会认错）。
命中"别的那些地方"会直接标在图上，不用自己去数。

本文件自带最小夹具（`_scene` / `_dialog`），与兄弟测试文件一致，不跨文件共享夹具。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import numpy as np
from PySide6.QtWidgets import QApplication

from luoluotool.gui.dialogs.crop_dialog import TemplateCropDialog

_APP = QApplication.instance() or QApplication([])

STAMP_SIZE = (30, 24)
STAMP_POSITIONS = [(30, 24), (150, 100), (250, 180)]


def _scene(positions: list[tuple[int, int]] | None = None, size: tuple[int, int] = (320, 240)) -> np.ndarray:
    """有纹理的底图 + 在指定位置贴同一枚图章（模拟"画面里出现多处一样的东西"）。"""
    width, height = size
    rng = np.random.default_rng(7)
    scene = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)
    stamp = rng.integers(0, 255, (STAMP_SIZE[1], STAMP_SIZE[0], 3), dtype=np.uint8)
    for x, y in positions or [STAMP_POSITIONS[0]]:
        scene[y : y + STAMP_SIZE[1], x : x + STAMP_SIZE[0]] = stamp
    return scene


def _dialog(image: np.ndarray, tmp_path) -> TemplateCropDialog:
    return TemplateCropDialog(image, (image.shape[1], image.shape[0]), save_dir=tmp_path)


def _wait_for(predicate, timeout_ms: int = 5000) -> bool:
    """转事件循环等后台线程把信号送到（超时返回 False，测试自己断言）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _select_stamp(dialog: TemplateCropDialog, position: tuple[int, int]) -> None:
    dialog.set_selection_in_image(position[0], position[1], *STAMP_SIZE)


def test_probe_button_needs_a_selection(tmp_path) -> None:
    """没框选时按钮不可点（点了也没得测），框上之后才可用。"""
    dialog = _dialog(_scene(), tmp_path)

    assert dialog.probe_button.isEnabled() is False

    _select_stamp(dialog, STAMP_POSITIONS[0])
    assert dialog.probe_button.isEnabled() is True
    assert "试识别" in dialog.probe_hint_label.text()      # 初始就有说明（不会保存/不产生输入）
    dialog.deleteLater()


def test_probe_reports_a_unique_region(tmp_path) -> None:
    """只有一处：提示"只找到你框的这一处"，图上不标任何别的框。"""
    dialog = _dialog(_scene([STAMP_POSITIONS[0]]), tmp_path)
    _select_stamp(dialog, STAMP_POSITIONS[0])

    dialog.probe_button.click()
    assert _wait_for(lambda: "只" in dialog.probe_result_label.text()), dialog.probe_result_label.text()

    assert "只" in dialog.probe_result_label.text()
    assert dialog.view.probe_rects() == []
    dialog.deleteLater()


def test_probe_marks_the_other_places_on_the_image(tmp_path) -> None:
    """三处一样：文案说清"还有 2 处"，并把那两处标在图上（图像坐标，不含自己那处）。"""
    dialog = _dialog(_scene(STAMP_POSITIONS), tmp_path)
    _select_stamp(dialog, STAMP_POSITIONS[1])

    dialog.probe_button.click()
    assert _wait_for(lambda: "3 处" in dialog.probe_result_label.text()), dialog.probe_result_label.text()

    text = dialog.probe_result_label.text()
    assert "3 处" in text and "2 处" in text
    others = {position for position in STAMP_POSITIONS if position != STAMP_POSITIONS[1]}
    marked = {(rect.left(), rect.top()) for rect in dialog.view.probe_rects()}
    assert marked == others
    dialog.deleteLater()


def test_probe_refuses_a_featureless_region(tmp_path) -> None:
    """纯色选区：连试都不试（那种区域满屏都会"命中"），直接提示换一块。"""
    image = np.full((240, 320, 3), 120, dtype=np.uint8)
    dialog = _dialog(image, tmp_path)
    dialog.set_selection_in_image(20, 20, 60, 40)

    dialog.probe_button.click()
    _APP.processEvents()

    assert "换" in dialog.probe_result_label.text()
    assert dialog.view.probe_rects() == []
    assert dialog.probe_thread is None                     # 根本没起线程
    dialog.deleteLater()


def test_probe_result_is_dropped_when_the_selection_changes(tmp_path) -> None:
    """改选区后旧结论作废（否则用户会拿着上一块的结果判断这一块）。"""
    dialog = _dialog(_scene(STAMP_POSITIONS), tmp_path)
    _select_stamp(dialog, STAMP_POSITIONS[1])
    dialog.probe_button.click()
    assert _wait_for(lambda: dialog.view.probe_rects() != []), "试识别没有标出其它位置"

    dialog.set_selection_in_image(200, 150, *STAMP_SIZE)

    assert dialog.view.probe_rects() == []
    assert "试识别" in dialog.probe_result_label.text()
    dialog.deleteLater()


def test_closing_waits_for_the_probe_thread(tmp_path, monkeypatch) -> None:
    """关窗口时必须等后台线程（正在跑也不许把 QThread 丢了，否则会崩）。"""
    from luoluotool.core.vision import probe_region_on_image as real_probe

    dialog = _dialog(_scene([STAMP_POSITIONS[0]]), tmp_path)
    _select_stamp(dialog, STAMP_POSITIONS[0])

    started = {"called": False}

    def _slow(image, region, **kwargs):
        """慢版本：把"线程还在跑"这一瞬间固定下来，好验证关窗路径。"""
        started["called"] = True
        time.sleep(0.4)
        return real_probe(image, region, **kwargs)

    monkeypatch.setattr("luoluotool.core.vision.probe_region_on_image", _slow)
    dialog.probe_button.click()
    assert _wait_for(lambda: started["called"], 2000), "试识别线程没有起来"

    dialog.done(int(TemplateCropDialog.DialogCode.Rejected))

    thread = dialog.probe_thread
    assert thread is None or not thread.isRunning()
    dialog.deleteLater()
