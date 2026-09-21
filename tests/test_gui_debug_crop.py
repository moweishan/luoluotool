"""GUI 开发者调试页测试：调试动作分发、框选生成模板与开发者调试门禁。"""

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui_helpers import window_factory
from luoluotool.config.models import AppConfig

_APP = QApplication.instance() or QApplication([])


def test_run_debug_action_dispatches_vision(monkeypatch) -> None:
    """调试动作分发：kind="vision" 走 core.vision 识别，并把结果消息回给界面。"""
    from luoluotool.core import vision as vision_actions
    from luoluotool.gui import main_window as mw

    calls: list[tuple] = []

    class _Result:
        message = "识别成功：命中 1 处\n  1) 客户区 中心 (60, 35) 匹配度 1.000"

    def fake_recognize(config, images, threshold, max_results):
        calls.append((list(images), threshold, max_results))
        return _Result()

    monkeypatch.setattr(vision_actions, "recognize_in_window", fake_recognize)
    message = mw.run_debug_action(
        AppConfig.default(), "vision",
        {"images": ["a.png", "b.png"], "threshold": 0.8, "max_results": 7},
        logging.getLogger("t"), None,
    )
    assert calls == [(["a.png", "b.png"], 0.8, 7)]
    assert "识别成功" in message and "(60, 35)" in message


def test_vision_debug_action_reports_missing_template(monkeypatch, tmp_path) -> None:
    """端到端（不经真实截图）：模板文件不存在时，调试线程回传可读消息而不抛异常。

    多张模板共用同一张截图，所以截图排在模板读取之前 —— 这里把截图换成假画面。
    """
    import numpy as np

    from luoluotool.core import vision as vision_actions
    from luoluotool.gui import main_window as mw

    monkeypatch.setattr(vision_actions, "find_window", lambda keyword: 555)
    monkeypatch.setattr(vision_actions, "is_window_ready", lambda hwnd: True)
    monkeypatch.setattr(
        vision_actions, "capture_client_bgr",
        lambda hwnd: np.full((40, 60, 3), 30, dtype=np.uint8),
    )
    messages: list[str] = []
    thread = mw._DebugTestThread(
        AppConfig.default(), "vision",
        {"images": [str(tmp_path / "缺失.png")], "threshold": 0.85, "max_results": 20},
        logging.getLogger("t"),
    )
    thread.finished_message.connect(messages.append)
    thread.run()                       # 同步执行（不等待线程）
    assert messages and "无法读取模板图片" in messages[0]


def test_crop_flow_saves_template_and_fills_path(window_factory, tmp_path, monkeypatch) -> None:
    """框选流程：主窗口把截图交给对话框，保存后把模板路径回填到调试页并提示。"""
    import numpy as np

    from luoluotool.gui import main_window as mw

    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    opened: list[tuple] = []
    saved = tmp_path / "anchor_test.png"

    class _FakeDialog:
        def __init__(self, image, window_size, save_dir, parent=None, threshold=None):
            opened.append((image.shape, window_size, save_dir, threshold))
            self.saved_path = saved

        def selection(self):          # 与真实对话框接口一致（保存后主窗口会用它拼提示）
            return 10, 20, 30, 40

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

        def deleteLater(self):        # noqa: N802 (QObject 接口)
            return None

    monkeypatch.setattr(mw, "TemplateCropDialog", _FakeDialog)
    window.debug_page.vision_threshold_spin.setValue(0.93)     # 评审 P2-2：阈值要往下传
    window._on_capture_ready(np.zeros((50, 100, 3), dtype=np.uint8), (100, 50))

    assert opened and opened[0][0] == (50, 100, 3) and opened[0][1] == (100, 50)
    assert opened[0][3] == 0.93                 # 弹窗拿到的就是调试页当前阈值（试识别同口径）
    assert window.debug_page.vision_templates() == [str(saved)]
    assert "模板已保存" in window.debug_page.status_label.text()
    assert "选区 30x40" in window.debug_page.status_label.text()


def test_crop_flow_writes_only_selected_region(window_factory, tmp_path, monkeypatch) -> None:
    """全链路（真实对话框）：框选 → 「保存为模板」→ 只写选区尺寸的模板 → 加入模板列表。

    回归：这个按钮以前只连 accept()，"保存为模板"实际什么都没存（主窗口随后报未选区域）。
    """
    import numpy as np

    from luoluotool.automation.vision import load_template
    from luoluotool.gui import main_window as mw

    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    anchors = tmp_path / "anchors"
    monkeypatch.setattr(mw, "get_anchors_dir", lambda: anchors)

    class _AutoCrop(mw.TemplateCropDialog):
        """替代 exec()：模拟用户拖框并点「保存为模板」，再返回真实对话框结果。"""

        def exec(self):
            self.view.resize(400, 400)
            self.set_selection_in_image(30, 20, 50, 40)
            self.save_button.click()
            return self.result()

    monkeypatch.setattr(mw, "TemplateCropDialog", _AutoCrop)
    # 画布要有纹理：纯色块会被纯色模板守卫拦下（那是另一条规则），这里测的是"只存选区"
    image = np.zeros((300, 400, 3), dtype=np.uint8)
    image[:, :, 0] = np.arange(400, dtype=np.uint8)
    image[:, :, 1] = np.arange(300, dtype=np.uint8).reshape(-1, 1)
    window._on_capture_ready(image, (400, 300))

    files = list(anchors.glob("anchor_*.png"))
    assert len(files) == 1, "「保存为模板」必须写出一个模板文件"
    saved = load_template(files[0])
    assert saved.shape == (40, 50, 3)              # 只存框选的那块，不是整屏 300x400
    assert window.debug_page.vision_templates() == [str(files[0])]
    assert "模板已保存" in window.debug_page.status_label.text()


def test_crop_request_is_rejected_when_developer_mode_off(window_factory, tmp_path, caplog) -> None:
    """开发者调试未开启：框选截图入口同样不生效（不起线程、不弹窗）。"""
    import logging as _logging

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    caplog.set_level(_logging.WARNING)
    window.debug_page.crop_requested.emit()
    assert window._capture_thread is None
    assert "不生效" in window.debug_page.status_label.text()


def test_crop_capture_failure_reports_message(window_factory, tmp_path) -> None:
    """截图失败（窗口最小化等）：把可读消息写进调试页状态区。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    window._on_capture_failed("游戏窗口已最小化或不可见，请恢复窗口后重试")
    assert "最小化" in window.debug_page.status_label.text()


def test_debug_actions_are_rejected_when_developer_mode_off(window_factory, tmp_path, caplog) -> None:
    """开发者调试未开启：调试动作（测试/诊断/布局测量）一律拒绝执行并给出提示。"""
    import logging as _logging

    config = AppConfig.default()
    window = window_factory(tmp_path / "config.json", config)
    caplog.set_level(_logging.WARNING)
    assert window.tabs.indexOf(window.debug_page) < 0

    window.debug_page.test_requested.emit("single_click", {"x": 1, "y": 2})
    window.debug_page.diagnose_requested.emit()
    window.debug_page.layout_measure_requested.emit()

    assert window._debug_thread is None      # 没有起任何调试线程
    assert window._diagnose_thread is None   # 没有发起窗口诊断
    assert "不生效" in window.debug_page.status_label.text()
    assert caplog.text.count("开发者调试未开启") == 3


def test_debug_actions_run_when_developer_mode_on(window_factory, tmp_path) -> None:
    """开发者调试开启：布局测量（纯几何）正常执行，状态区出现报告。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    window.debug_page.layout_measure_requested.emit()
    assert "布局测量" in window.debug_page.status_label.text()


def test_turning_developer_mode_off_stops_running_debug_action(window_factory, tmp_path) -> None:
    """关闭开发者调试：正在跑的调试动作被立即中断，调试页禁用。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)

    stopped: list[str] = []

    class _FakeDebugThread:
        def isRunning(self) -> bool:      # noqa: N802 (QThread 命名)
            return True

        def request_stop(self) -> None:
            stopped.append("stop")

        def wait(self, timeout=None) -> bool:      # 与 QThread 接口一致（关闭窗口时会等待线程退出）
            stopped.append("wait")
            return True

    window._debug_thread = _FakeDebugThread()
    window.settings_page.developer_box.setChecked(False)
    assert stopped == ["stop"]
    assert window.tabs.indexOf(window.debug_page) < 0
    assert window.debug_page.isEnabled() is False
    assert "不生效" in window.debug_page.status_label.text()


def test_developer_mode_from_config_mounts_tab_at_startup(window_factory, tmp_path) -> None:
    """配置里 developer_mode=true 时启动即挂载调试页。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(tmp_path / "config.json", config)
    assert window.tabs.indexOf(window.debug_page) >= 0


def test_run_debug_action_dispatches_all_kinds(monkeypatch) -> None:
    """主窗口的调试动作分发：四种类型分别调用 core.debug 的对应函数。"""
    from luoluotool.gui import main_window as mw
    from luoluotool.gui import workers

    calls: list[tuple] = []
    for name in ("run_single_click", "run_repeat_click", "run_swipe", "run_key"):
        monkeypatch.setattr(workers.debug_actions, name, (lambda n: lambda *args, **kwargs: calls.append((n, args[1:])) or n)(name))

    config = AppConfig.default()
    log = logging.getLogger("t")
    mw.run_debug_action(config, "single_click", {"x": 1, "y": 2}, log, None)
    mw.run_debug_action(config, "repeat_click", {"x": 1, "y": 2, "count": 3, "interval_ms": 100}, log, None)
    mw.run_debug_action(config, "swipe", {"from_x": 1, "from_y": 2, "to_x": 3, "to_y": 4, "duration_ms": 500}, log, None)
    mw.run_debug_action(config, "key", {"combo": "a", "count": 1, "interval_ms": 100}, log, None)
    assert [name for name, _args in calls] == [
        "run_single_click", "run_repeat_click", "run_swipe", "run_key",
    ]
    assert calls[2][1][0] == (1, 2) and calls[2][1][1] == (3, 4)   # 滑动起终点

    with pytest.raises(ValueError, match="未知的调试测试类型"):
        mw.run_debug_action(config, "nope", {}, log, None)


def test_run_debug_action_passes_click_hold(monkeypatch) -> None:
    """单点/连点分发都把「点击时长」传下去；旧载荷（没有 hold_ms）走默认值而不是报错。"""
    from luoluotool.gui import main_window as mw
    from luoluotool.gui import workers

    seen: list[dict] = []
    monkeypatch.setattr(
        workers.debug_actions, "run_single_click",
        lambda config, x, y, log, stop_event=None, **kwargs: seen.append(
            {"kind": "single", "x": x, "y": y, **kwargs}
        ) or "ok",
    )
    monkeypatch.setattr(
        workers.debug_actions, "run_repeat_click",
        lambda config, x, y, count, interval_ms, log, stop_event=None, **kwargs: seen.append(
            {"kind": "repeat", "x": x, "y": y, "count": count, **kwargs}
        ) or "ok",
    )
    log = logging.getLogger("t")
    config = AppConfig.default()

    mw.run_debug_action(config, "single_click", {"x": 5, "y": 6, "hold_ms": 250}, log, None)
    mw.run_debug_action(config, "single_click", {"x": 7, "y": 8}, log, None)
    mw.run_debug_action(
        config, "repeat_click",
        {"x": 9, "y": 10, "count": 3, "interval_ms": 100, "hold_ms": 180}, log, None,
    )
    mw.run_debug_action(
        config, "repeat_click", {"x": 11, "y": 12, "count": 2, "interval_ms": 100}, log, None,
    )

    assert seen[0]["hold_ms"] == 250
    assert "hold_ms" in seen[1] and seen[1]["hold_ms"] >= 0      # 缺省时用引擎默认时长
    assert seen[2]["hold_ms"] == 180 and seen[2]["count"] == 3
    assert "hold_ms" in seen[3] and seen[3]["count"] == 2
