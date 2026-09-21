"""日常任务页的「参考图」流程测试：选择图片 / 截取游戏画面（框选）/ 放大预览。

被测对象：`gui/daily_media.DailyMediaController` + `gui/daily_media.DailyCaptureThread`。
页面本身只发信号（`tests/test_gui_daily_page.py` 测信号）；这里测"信号之后发生了什么"：
校验图片、写配置并置脏、显示缩略图、截图前的切前台、框选产物入库、预览弹窗。

**绝不真的截图、绝不真的弹窗**：`find_window` / `bring_to_front` / `capture_window` /
`TemplateCropDialog` / `QFileDialog` 全部被替换成假对象。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from luoluotool.automation.vision import save_image
from luoluotool.config.models import AppConfig
from luoluotool.gui import daily_media
from luoluotool.gui.daily_media import DailyCaptureThread, DailyMediaController
from luoluotool.gui.pages.daily import BUILDINGS, DailyPage, ref_image_field
from luoluotool.utils.paths import to_config_path

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig, changes: list[str]) -> DailyPage:
    return DailyPage(config, lambda: changes.append("dirty"))


def _controller(page: DailyPage, config: AppConfig, changes: list[str]) -> DailyMediaController:
    statuses: list[str] = []
    controller = DailyMediaController(
        page,
        get_config=lambda: config,
        on_changed=lambda: changes.append("dirty"),
        set_status=statuses.append,
    )
    controller.statuses = statuses        # 测试读它，省得再包一层
    return controller


@pytest.fixture()
def textured_png(tmp_path):
    """一张有纹理的 PNG（能被当作模板；纯色会被 `load_template` 拒掉）。"""

    def _make(name: str = "鸡舍_岛屿1.png"):
        rng = np.random.default_rng(7)
        image = rng.integers(0, 255, size=(40, 60, 3), dtype=np.uint8)
        return save_image(tmp_path / name, image)

    return _make


# ---------------------------------------------------------------- 选择图片…


def test_pick_image_writes_config_and_shows_thumbnail(tmp_path, textured_png) -> None:
    """选中一张能用的图：路径写进配置（相对仓库根）、置脏、缩略图出现在「选择的图片」区。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    path = textured_png()

    assert controller.adopt_image_file("coop", path) is True
    assert config.features.daily_tasks.coop_island_ref_image == to_config_path(path)
    assert changes == ["dirty"]
    assert page.reference_image("coop") == to_config_path(path)
    preview = page.preview_widget("coop")
    assert preview is not None and preview.image() is not None
    assert "已选择" in controller.statuses[-1]
    page.close()


def test_pick_image_refuses_a_flat_image_and_keeps_old_value(tmp_path, textured_png) -> None:
    """纯色图**必须拒收**（拿去识别会满地"匹配度 1.000"），且不许动原来的参考图。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    good = textured_png("好的.png")
    assert controller.adopt_image_file("land", good) is True
    before = config.features.daily_tasks.land_ref_image

    flat = save_image(tmp_path / "纯色.png", np.full((30, 30, 3), 128, dtype=np.uint8))
    assert controller.adopt_image_file("land", flat) is False
    assert config.features.daily_tasks.land_ref_image == before
    assert "不能用" in controller.statuses[-1]
    assert page.reference_image("land") == before
    page.close()


def test_pick_image_dialog_starts_in_templates_dir_and_handles_cancel(monkeypatch, tmp_path) -> None:
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


def test_pick_image_dialog_starts_in_the_folder_of_the_current_image(
    monkeypatch, tmp_path, textured_png
) -> None:
    """已经选过图时，对话框从那张图所在目录打开（换图时少点几步）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    first = textured_png("第一张.png")
    assert controller.adopt_image_file("coop", first) is True

    calls: list[str] = []
    monkeypatch.setattr(
        daily_media.QFileDialog, "getOpenFileName",
        staticmethod(lambda parent, caption, directory, filters: calls.append(directory) or ("", "")),
    )
    page.pick_image_requested.emit("coop")
    assert calls and calls[0] == str(first.parent)
    page.close()


# ---------------------------------------------------------------- 截取游戏画面


def test_capture_thread_brings_the_window_to_front_before_capturing(monkeypatch) -> None:
    """截图前**必须先把游戏窗口切到前台**（否则截到的是盖在上面的本工具窗口）。"""
    config = AppConfig.default()
    order: list[str] = []

    monkeypatch.setattr(daily_media, "find_window", lambda keyword: order.append("find") or 4242)
    monkeypatch.setattr(daily_media, "bring_to_front", lambda hwnd: order.append("front") or True)
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: order.append("capture") or (np.zeros((10, 20, 3), dtype=np.uint8), ""),
    )
    captured: list[tuple] = []
    failures: list[str] = []
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.0)
    thread.captured.connect(lambda image, size: captured.append((image.shape, size)))
    thread.failed_message.connect(failures.append)

    thread.run()                                   # 同步执行，不真的起线程

    assert order == ["find", "front", "capture"]
    assert captured and captured[0][1] == (20, 10)
    assert failures == []


def test_capture_thread_reports_missing_window(monkeypatch) -> None:
    """找不到游戏窗口：给可读提示，**不截图**。"""
    config = AppConfig.default()
    monkeypatch.setattr(daily_media, "find_window", lambda keyword: None)
    called: list[str] = []
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: called.append("capture") or (None, ""),
    )
    failures: list[str] = []
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.0)
    thread.failed_message.connect(failures.append)

    thread.run()

    assert called == []
    assert failures and "未找到" in failures[0]


def test_capture_thread_stops_before_screenshot_when_requested(monkeypatch) -> None:
    """等待切前台期间收到停止请求 → 不再截图（关窗/急停时不用白等）。"""
    config = AppConfig.default()
    monkeypatch.setattr(daily_media, "find_window", lambda keyword: 1)
    monkeypatch.setattr(daily_media, "bring_to_front", lambda hwnd: True)
    called: list[str] = []
    monkeypatch.setattr(
        daily_media.vision_actions, "capture_window",
        lambda cfg: called.append("capture") or (None, ""),
    )
    thread = DailyCaptureThread(config, daily_media.logger, settle=0.3)
    thread.request_stop()

    thread.run()

    assert called == []


def test_capture_ready_opens_crop_dialog_and_records_the_saved_anchor(
    tmp_path, monkeypatch, textured_png
) -> None:
    """截图完成 → 弹框选窗（拿到本次截图与文件名前缀）→ 保存后写配置 + 显示缩略图。"""
    config = AppConfig.default()
    config.features.daily_tasks.coop_island = 7
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    anchors = tmp_path / "anchors"
    monkeypatch.setattr(daily_media, "get_anchors_dir", lambda: anchors)
    saved = textured_png("coop_island_7.png")     # 假装是框选产物

    opened: list[tuple] = []

    class _FakeDialog:
        def __init__(self, image, window_size, save_dir, parent=None, threshold=None, file_stem=""):
            opened.append((image.shape, window_size, save_dir, threshold, file_stem))
            self.saved_path = saved

        def selection(self):
            return 12, 34, 50, 40

        def exec(self):
            return QDialog.DialogCode.Accepted

        def deleteLater(self):                     # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(daily_media, "TemplateCropDialog", _FakeDialog)
    controller._pending_prefix = "coop"            # 正常由 capture_image() 设置
    controller.on_capture_ready(np.zeros((50, 100, 3), dtype=np.uint8), (100, 50))

    assert opened and opened[0][1] == (100, 50) and opened[0][2] == anchors
    assert opened[0][4] == "鸡舍_岛屿7"            # 文件名带建筑名 + 岛屿编号，方便回看
    assert config.features.daily_tasks.coop_island_ref_image == to_config_path(saved)
    assert page.preview_widget("coop").image() is not None
    assert "参考图已保存" in controller.statuses[-1] and "选区 50x40" in controller.statuses[-1]
    page.close()


def test_capture_ready_keeps_the_old_image_when_the_user_cancels(tmp_path, monkeypatch,
                                                                 textured_png) -> None:
    """用户取消框选 → 只提示，配置与显示都保持原样。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    old = textured_png("旧的.png")
    assert controller.adopt_image_file("aqua", old) is True
    before = config.features.daily_tasks.aqua_ref_image
    changes.clear()

    class _CancelDialog:
        def __init__(self, *args, **kwargs):
            self.saved_path = None

        def exec(self):
            return QDialog.DialogCode.Rejected

        def deleteLater(self):                     # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(daily_media, "TemplateCropDialog", _CancelDialog)
    controller._pending_prefix = "aqua"
    controller.on_capture_ready(np.zeros((20, 20, 3), dtype=np.uint8), (20, 20))

    assert config.features.daily_tasks.aqua_ref_image == before
    assert changes == []
    assert page.reference_image("aqua") == before
    assert "已取消" in controller.statuses[-1]
    page.close()


def test_capture_failure_points_at_the_log_file(monkeypatch) -> None:
    """截图失败：状态栏给原因 + **说清日志在哪**（用户 B9 的要求），不弹窗。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)

    controller.on_capture_failed("游戏窗口已最小化或不可见，请恢复窗口后重试")

    message = controller.statuses[-1]
    assert "截取游戏画面失败" in message and "最小化" in message
    assert "luoluotool.log" in message
    page.close()


def test_capture_image_refuses_to_start_a_second_time() -> None:
    """上一次截图还在飞时不重复发起（避免两路截图/两个框选窗口）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)

    class _Busy(DailyCaptureThread):
        def isRunning(self):                       # noqa: N802 (QThread 接口)
            return True

    controller._thread = _Busy(config, daily_media.logger)
    controller.capture_image("coop")

    assert "还没结束" in controller.statuses[-1]
    page.close()


# ---------------------------------------------------------------- 放大预览


def test_preview_dialog_shows_the_image(tmp_path, textured_png) -> None:
    """双击后的放大预览：工具内弹窗，标题带建筑名与像素尺寸。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    path = textured_png("预览.png")
    config.features.daily_tasks.land_ref_image = to_config_path(path)

    dialog = controller.build_preview_dialog("land")

    assert dialog is not None
    assert "土地" in dialog.windowTitle()
    dialog.deleteLater()
    page.close()


def test_preview_reports_missing_file_without_clearing_config(tmp_path) -> None:
    """文件不见了：提示 + 记日志，但**不动配置里的路径**（用户可能只是换机器）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    config.features.daily_tasks.land_ref_image = "assets/anchors/不存在.png"

    assert controller.build_preview_dialog("land") is None
    assert "找不到" in controller.statuses[-1]
    assert config.features.daily_tasks.land_ref_image == "assets/anchors/不存在.png"
    page.close()


def test_preview_without_any_image_says_so() -> None:
    """还没选图时双击：只说"还没选参考图"，不报错。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)

    assert controller.build_preview_dialog("coop") is None
    assert "还没选参考图" in controller.statuses[-1]
    page.close()


# ---------------------------------------------------------------- 重新加载配置


def test_refresh_previews_reads_every_building_from_config(tmp_path, textured_png) -> None:
    """加载/重载/恢复默认后：三张参考图的缩略图按配置重读（页面自己不做文件 IO）。"""
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

    assert page.preview_widget("coop").image() is not None
    assert page.preview_widget("aqua").image() is not None
    assert page.preview_widget("land").image() is None
    assert changes == []                                   # 只是显示，不算用户改动
    page.close()


def test_refresh_previews_keeps_the_path_when_the_file_is_gone(tmp_path) -> None:
    """配置里的文件被删掉：缩略图清空、路径保留（不许悄悄把用户的配置抹掉）。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    config.features.daily_tasks.coop_island_ref_image = "assets/anchors/没了.png"

    controller.refresh_previews()

    assert page.reference_image("coop") == "assets/anchors/没了.png"
    assert page.preview_widget("coop").image() is None
    page.close()


def test_every_building_has_a_config_field_for_island_and_image() -> None:
    """契约：设计稿的 data-key 必须真的存在于配置模型上（选图/截图写的就是这些字段）。"""
    daily = AppConfig.default().features.daily_tasks
    for _title, prefix, _word, ref_id, _capture in BUILDINGS:
        assert hasattr(daily, f"{prefix}_island"), prefix
        assert hasattr(daily, ref_image_field(prefix)), ref_id
