"""日常任务页的「参考图」流程测试：选择图片 / 解码 / 放大预览 / 重新加载。

被测对象：`gui/daily_media.DailyMediaController` + `ReferenceImageLoader` + `decode_reference_image`。
页面本身只发信号（`tests/test_gui_daily_page.py` 测信号）；这里测"信号之后发生了什么"：
后台解码/校验、写配置并置脏、显示缩略图、预览弹窗、刷新缩略图。

「截取游戏画面（框选）」那一段在 `tests/test_gui_daily_capture.py`（2026-09-22 拆出：
本文件到过 600 行硬线）。**绝不真的弹窗**：`QFileDialog` 与弹窗的 `exec()` 都被替换成假对象。
参考图解码是**后台线程**（第五轮评审 P2-4），所以用 `wait_for_daily_decoding()` 驱动。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication, QDialog

from gui_helpers import (
    daily_media_controller,
    daily_media_page,
    wait_for_daily_decoding,
)
from luoluotool.automation.vision import save_image
from luoluotool.config.models import MAX_IMAGE_PATH_LENGTH, AppConfig
from luoluotool.gui import daily_media
from luoluotool.gui.daily_media import decode_reference_image
from luoluotool.gui.pages.daily import BUILDINGS, ref_image_field
from luoluotool.utils.paths import to_config_path

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig, changes: list[str]):
    return daily_media_page(config, changes)


def _controller(page, config: AppConfig, changes: list[str]):
    return daily_media_controller(page, config, changes)


def _wait_for_decoding(controller, timeout_ms: int = 5000) -> None:
    wait_for_daily_decoding(controller, timeout_ms)


# ---------------------------------------------------------------- 解码（纯函数）


def test_decode_reference_image_reports_missing_file(tmp_path) -> None:
    """文件不在：返回可读原因，不抛异常（线程里不允许崩）。"""
    result = decode_reference_image(tmp_path / "没有.png", validate=False)
    assert result.ok is False and "找不到文件" in result.message and result.image is None


def test_decode_reference_image_refuses_a_flat_image_only_when_validating(tmp_path) -> None:
    """纯色图：`validate=True` 拒收（拿去识别会满地"匹配度 1.000"）；只刷新预览时不拦。"""
    flat = save_image(tmp_path / "纯色.png", np.full((30, 30, 3), 128, dtype=np.uint8))

    rejected = decode_reference_image(flat, validate=True)
    assert rejected.ok is False and "纯色" in rejected.message

    preview_only = decode_reference_image(flat, validate=False)
    assert preview_only.ok is True and preview_only.image is not None
    assert (preview_only.width, preview_only.height) == (30, 30)


def test_decode_reference_image_reports_quality(tmp_path, textured_png) -> None:
    """校验模式下顺带给出可辨识度结论（低辨识度只提示不拦）。"""
    result = decode_reference_image(textured_png(), validate=True)
    assert result.ok is True
    assert result.quality is not None and result.quality.level == "ok"


# ---------------------------------------------------------------- 选择图片…


def test_pick_image_validates_off_thread_then_writes_config(tmp_path, textured_png) -> None:
    """选中一张能用的图：**后台线程**校验/解码 → 路径写进配置、置脏、缩略图出现。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    path = textured_png()

    assert controller.start_pick("coop", path) is True
    assert controller.loader_threads(), "解码必须放到后台线程（评审 P2-4）"
    _wait_for_decoding(controller)

    assert config.features.daily_tasks.coop_island_ref_image == to_config_path(path)
    assert changes == ["dirty"]
    assert page.reference_image("coop") == to_config_path(path)
    preview = page.preview_widget("coop")
    assert preview is not None and preview.image() is not None
    assert "已选择" in controller.statuses[-1]
    assert controller.worker_threads() == ()          # 跑完要摘掉（关窗等待列表不留死引用）
    page.close()


def test_pick_image_refuses_a_flat_image_and_keeps_old_value(tmp_path, textured_png) -> None:
    """纯色图**必须拒收**，且不许动原来的参考图。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    good = textured_png("好的.png")
    controller.start_pick("land", good)
    _wait_for_decoding(controller)
    before = config.features.daily_tasks.land_ref_image

    flat = save_image(tmp_path / "纯色.png", np.full((30, 30, 3), 128, dtype=np.uint8))
    controller.start_pick("land", flat)
    _wait_for_decoding(controller)

    assert config.features.daily_tasks.land_ref_image == before
    assert "不能用" in controller.statuses[-1]
    assert page.reference_image("land") == before
    page.close()


def test_pick_image_rejects_an_overlong_path_before_decoding(tmp_path) -> None:
    """路径超过配置上限（260）当场拒绝（第五轮评审 P3-1）。

    超长路径一旦写进配置，`store.save` 会抛 `ConfigSaveError`，**本次所有改动都不落盘** ——
    所以要在选中那一刻就拦住，并且别说成"图片有问题"。
    """
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    long_path = tmp_path / ("很长" * 150 + ".png")

    assert controller.start_pick("aqua", long_path) is False
    assert controller.loader_threads() == ()          # 没解码、没起线程
    assert config.features.daily_tasks.aqua_ref_image == ""
    assert "路径太长" in controller.statuses[-1]
    assert str(MAX_IMAGE_PATH_LENGTH) in controller.statuses[-1]
    page.close()


def test_pick_image_dialog_starts_in_templates_dir_and_handles_cancel(monkeypatch) -> None:
    """对话框默认打开 `assets/templates/`；取消则不改配置、只提示。"""
    from luoluotool.utils.paths import get_templates_dir

    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    calls: list[tuple] = []

    def fake_dialog(parent, caption, directory, filters):
        calls.append((caption, directory, filters))
        return "", ""

    monkeypatch.setattr(daily_media.QFileDialog, "getOpenFileName", staticmethod(fake_dialog))
    page.pick_image_requested.emit("aqua")

    assert calls and calls[0][1] == str(get_templates_dir())
    assert "png" in calls[0][2] and "jpg" in calls[0][2]
    assert config.features.daily_tasks.aqua_ref_image == ""
    assert changes == []
    assert "已取消" in controller.statuses[-1]
    page.close()


def test_pick_image_dialog_starts_in_the_folder_of_the_current_image(monkeypatch, textured_png) -> None:
    """已经选过图时，对话框从那张图所在目录打开（换图时少点几步）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    first = textured_png("第一张.png")
    controller.start_pick("coop", first)
    _wait_for_decoding(controller)

    calls: list[str] = []

    def fake_dialog(parent, caption, directory, filters):
        calls.append(directory)
        return "", ""

    monkeypatch.setattr(daily_media.QFileDialog, "getOpenFileName", staticmethod(fake_dialog))
    page.pick_image_requested.emit("coop")
    assert calls and calls[0] == str(first.parent)
    page.close()


def test_stale_pick_result_is_dropped(tmp_path, textured_png) -> None:
    """同一建筑连着选两张：旧一批的迟到结果必须丢弃（否则缩略图会闪回旧图）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    first = textured_png("第一张.png")
    second = textured_png("第二张.png")

    controller.start_pick("coop", first)
    controller.start_pick("coop", second)          # 立刻改主意再选一张
    _wait_for_decoding(controller)

    assert config.features.daily_tasks.coop_island_ref_image == to_config_path(second)
    assert page.reference_image("coop") == to_config_path(second)
    page.close()


# ---------------------------------------------------------------- 截取游戏画面


# ---------------------------------------------------------------- 放大预览


def test_show_preview_decodes_off_thread_then_opens_the_dialog(tmp_path, textured_png
                                                              , monkeypatch) -> None:
    """双击缩略图：解码在后台线程，图到了才开弹窗（弹窗只做界面）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    path = textured_png("预览.png")
    config.features.daily_tasks.land_ref_image = to_config_path(path)
    opened: list[str] = []

    def fake_exec(self):
        opened.append(self.windowTitle())
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", fake_exec)

    controller.show_preview("land")
    _wait_for_decoding(controller)

    assert opened and "土地" in opened[0]
    page.close()


def test_build_preview_dialog_uses_the_decoded_image(textured_png) -> None:
    """弹窗构造只吃**已解码**的 QImage（不 exec，便于测试）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    path = textured_png("弹窗.png")
    config.features.daily_tasks.land_ref_image = to_config_path(path)
    result = decode_reference_image(path, validate=False)

    dialog = controller.build_preview_dialog("land", result.image)

    assert dialog is not None and "土地" in dialog.windowTitle()
    dialog.deleteLater()
    assert controller.build_preview_dialog("land", None) is None   # 没图就不开窗
    page.close()


def test_preview_reports_missing_file_without_clearing_config() -> None:
    """文件不见了：提示 + 记日志，但**不动配置里的路径**（用户可能只是换机器），也不起线程。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    config.features.daily_tasks.land_ref_image = "assets/anchors/不存在.png"

    controller.show_preview("land")

    assert "找不到" in controller.statuses[-1]
    assert controller.loader_threads() == ()
    assert config.features.daily_tasks.land_ref_image == "assets/anchors/不存在.png"
    page.close()


def test_preview_without_any_image_says_so() -> None:
    """还没选图时双击：只说"还没选参考图"，不报错。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)

    controller.show_preview("coop")

    assert "还没选参考图" in controller.statuses[-1]
    assert controller.loader_threads() == ()
    page.close()


# ---------------------------------------------------------------- 重新加载配置


def test_refresh_previews_decodes_every_building_off_thread(tmp_path, textured_png) -> None:
    """加载/重载/恢复默认后：缩略图在**后台**解码（三张 4K 最坏 ~1.1 s，不能占 GUI 线程）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    coop = textured_png("鸡舍.png")
    aqua = textured_png("水产.png")
    config.features.daily_tasks.coop_island_ref_image = to_config_path(coop)
    config.features.daily_tasks.aqua_ref_image = to_config_path(aqua)
    config.features.daily_tasks.land_ref_image = ""

    controller.refresh_previews()
    assert len(controller.loader_threads()) == 1      # 一批线程处理两张（第三张是空路径）
    _wait_for_decoding(controller)

    assert page.preview_widget("coop").image() is not None
    assert page.preview_widget("aqua").image() is not None
    assert page.preview_widget("land").image() is None
    assert changes == []                                   # 只是显示，不算用户改动
    page.close()


def test_refresh_previews_keeps_the_path_when_the_file_is_gone() -> None:
    """配置里的文件被删掉：缩略图清空、路径保留（不许悄悄把用户的配置抹掉）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    config.features.daily_tasks.coop_island_ref_image = "assets/anchors/没了.png"

    controller.refresh_previews()
    _wait_for_decoding(controller)

    assert page.reference_image("coop") == "assets/anchors/没了.png"
    assert page.preview_widget("coop").image() is None
    page.close()


def test_every_building_has_a_config_field_for_island_and_image() -> None:
    """契约：设计稿的 data-key 必须真的存在于配置模型上（选图/截图写的就是这些字段）。"""
    daily = AppConfig.default().features.daily_tasks
    for _title, prefix, _word, ref_id, _capture in BUILDINGS:
        assert hasattr(daily, f"{prefix}_island"), prefix
        assert hasattr(daily, ref_image_field(prefix)), ref_id
