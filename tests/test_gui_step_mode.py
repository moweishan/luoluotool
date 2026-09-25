"""单步运行的界面测试：调试页最上方的开关 + 主界面「停止」右边的两个按钮。

用户 2026-09-22 要求：① 开发者调试页**最上方**新增「单步运行」；② 主界面**停止按钮最右边**
加「上一步」「下一步」；③ **只有勾了单步运行这两个按钮才显示**，其余情况都不显示；
④ 开关**不写配置**（用户选定：只在本次运行有效）。

核心语义（点一次走一步、上一步不执行动作）在 `tests/test_core/test_step_mode.py`。
"""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QVBoxLayout

from gui_helpers import window_factory  # noqa: F401  (pytest 夹具，名字必须与参数名一致)
from luoluotool.config.models import AppConfig
from luoluotool.gui.pages.debug import DebugPage

_APP = QApplication.instance() or QApplication([])


def _page(developer_mode: bool = True):
    config = AppConfig.default()
    config.automation.developer_mode = developer_mode
    return DebugPage(config, lambda: None), config


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------ 调试页开关
def test_step_mode_switch_sits_at_the_very_top_of_the_debug_page() -> None:
    """开关必须在调试页**最上方**（用户要求的第一条）。"""
    page, _config = _page()

    layout = page.content.layout()
    assert isinstance(layout, QVBoxLayout)
    first = layout.itemAt(0).widget()
    assert first is page.step_mode_box, "「单步运行」必须是本页第一个控件"
    assert isinstance(page.step_mode_box, QCheckBox)
    assert "单步运行" in page.step_mode_box.text()
    assert "下一步" in page.step_mode_box.toolTip()
    assert page.step_mode_enabled() is False          # 默认关
    page.close()


def test_step_mode_switch_does_not_write_config() -> None:
    """用户选定：**不存盘** —— 勾选只触发信号，配置一个字都不动。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    changes: list[str] = []
    page = DebugPage(config, lambda: changes.append("dirty"))
    toggled: list[bool] = []
    page.step_mode_toggled.connect(toggled.append)

    page.step_mode_box.setChecked(True)

    assert toggled == [True]
    assert changes == []                              # 没写配置、也没置脏
    assert page.step_mode_enabled() is True
    page.close()


def test_step_mode_switch_is_ignored_without_developer_mode() -> None:
    """没开「开发者调试」时本页选项一律不生效：勾选被回滚、不发射信号（与干跑开关同规矩）。"""
    page, _config = _page(developer_mode=False)
    toggled: list[bool] = []
    page.step_mode_toggled.connect(toggled.append)

    page.step_mode_box.setChecked(True)

    assert page.step_mode_enabled() is False
    assert toggled == []
    assert "不生效" in page.status_label.text()
    page.close()


# ------------------------------------------------------------------ 主界面按钮
def test_step_buttons_are_hidden_until_step_mode_is_on(window_factory) -> None:
    """「上一步」「下一步」默认不显示；勾上单步运行才显示（用户要求的第三条）。"""
    window = window_factory(developer_mode=True)

    assert window.previous_button.text() == "上一步"
    assert window.next_button.text() == "下一步"
    for button in (window.previous_button, window.next_button):
        assert button.isHidden() is True              # 没勾单步 → 都不显示
        # 说明：这里断言 isHidden()（控件自身的隐藏状态）而不是 isVisible() ——
        # 窗口没 show() 时 isVisible() 恒为 False，测不出「我们有没有主动隐藏它」

    window.debug_page.step_mode_box.setChecked(True)
    _APP.processEvents()
    for button in (window.previous_button, window.next_button):
        assert button.isHidden() is False             # 勾上 → 不再隐藏（窗口一显示就会出现）

    window.debug_page.step_mode_box.setChecked(False)
    _APP.processEvents()
    for button in (window.previous_button, window.next_button):
        assert button.isHidden() is True              # 取消勾选 → 又都不显示


def test_step_buttons_sit_to_the_right_of_the_stop_button(window_factory) -> None:
    """两个按钮必须在**停止按钮的最右边**（用户要求的第二条）。"""
    window = window_factory(developer_mode=True)
    window.debug_page.step_mode_box.setChecked(True)
    window.show()
    _APP.processEvents()

    def rect_of(widget) -> QRect:
        return QRect(widget.mapTo(window, QPoint(0, 0)), widget.size())

    stop = rect_of(window.stop_button)
    previous = rect_of(window.previous_button)
    following = rect_of(window.next_button)

    assert previous.left() > stop.right(), "「上一步」应在「停止」右边"
    assert following.left() > previous.right(), "「下一步」应在「上一步」右边"
    assert abs(following.center().y() - stop.center().y()) <= 4, "三个按钮同一行"


def test_step_buttons_explain_themselves_when_nothing_is_running(window_factory) -> None:
    """没在跑任务时点「下一步」：状态栏说明原因，不报错（也不需要弹窗）。"""
    window = window_factory(developer_mode=True)
    window.debug_page.step_mode_box.setChecked(True)
    _APP.processEvents()

    window.next_button.click()
    assert "没有停在某一步" in window.statusBar().currentMessage() or \
        "当前没有停在" in window.statusBar().currentMessage()

    window.previous_button.click()
    assert "已回到第 1 步" in window.statusBar().currentMessage()


def test_developer_mode_off_resets_step_mode_and_hides_buttons(window_factory) -> None:
    """关掉「开发者调试」：单步复位、两个按钮重新隐藏（未开启时本页选项不生效）。"""
    config = AppConfig.default()
    config.automation.developer_mode = True
    window = window_factory(config=config)
    window.debug_page.step_mode_box.setChecked(True)
    _APP.processEvents()
    assert window.next_button.isHidden() is False

    window.settings_page.developer_box.setChecked(False)      # 走设置页开关
    _APP.processEvents()

    assert window.debug_page.step_mode_enabled() is False
    assert window.next_button.isHidden() is True
    assert window.previous_button.isHidden() is True


def test_start_attaches_the_stepper_only_when_step_mode_is_on(window_factory) -> None:
    """点「启动」时才把单步控制器交给 Runner；**没勾单步就是 None**（非单步路径零开销）。"""
    window = window_factory(developer_mode=True)
    runners: list = []
    window._runner_factory = lambda cfg: _recording_runner(runners, cfg)

    window._start()
    assert _wait(lambda: bool(runners))
    assert runners[0].stepper is None                      # 没勾单步
    window._stop()
    _APP.processEvents()

    runners.clear()
    window.debug_page.step_mode_box.setChecked(True)
    window._start()
    assert _wait(lambda: bool(runners))
    assert runners[0].stepper is window._stepper           # 勾了单步才挂上
    assert runners[0].stepper.enabled() is True
    window._stop()


def _recording_runner(store: list, config):
    """造一个"只记下来、不真跑"的 Runner（避免测试里真的跑任务队列）。"""
    from luoluotool.core.runner import Runner

    runner = Runner(config, sleep=lambda _s: None, channel_factory=_idle_channel)

    class _Recorder:
        def __init__(self, real) -> None:
            self._real = real
            self.stepper = None
            store.append(self)

        def start(self) -> None:
            return None                                    # 不起线程、不跑任务

        def request_stop(self) -> None:
            return None

        def isRunning(self) -> bool:                       # noqa: N802 (QThread 接口)
            return False

    return _Recorder(runner)


def _idle_channel(config, stop_event, sleep, log):
    from luoluotool.automation.input_sender import DryRunSender, InputChannel

    return InputChannel(DryRunSender())
