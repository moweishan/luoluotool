"""automation.input_sender 测试：干跑降级、通道构建、窗口就绪守卫（全部注入假实现，零真实输入）。"""

import logging
import threading
from pathlib import Path

import pytest

from luoluotool.automation import input_sender
from luoluotool.config.models import AppConfig

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


@pytest.fixture(autouse=True)
def _capture_info_logs(caplog):
    caplog.set_level(logging.INFO)


def test_source_contains_no_input_takeover_apis() -> None:
    """架构红线（2026-09-16 更新）：输入注入 API 只允许出现在 `real_input.py` 里。

    背景：用户选定「真实鼠标键盘（SendInput）」方案后，`real_input.py` 成为唯一允许直接调用
    注入 API 的模块；其余模块（含本模块 `input_sender.py` 的各发送器）只能调用 `real_input`
    暴露的语义化函数，便于审计、替换与回归。
    """
    forbidden_calls = (
        "Send" + "Input(",
        "SetCursor" + "Pos(",
        "mouse_" + "event(",
        "keybd_" + "event(",
        "InjectSyntheticPointer" + "Input(",
    )
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        if path.name == "real_input.py":
            continue  # 唯一允许的注入入口（有独立守卫测试覆盖它）
        text = path.read_text(encoding="utf-8")
        offenders.extend(f"{path.name}:{call}" for call in forbidden_calls if call in text)
    assert offenders == [], f"这些模块不得直接调用输入注入 API：{offenders}"


def test_dry_run_sender_only_logs(caplog) -> None:
    """干跑模式只写日志：绝不调用任何输入通道。"""
    sender = input_sender.DryRunSender()
    sender.move_to(10, 20)
    sender.click(10, 20)
    sender.click_at(30, 40)
    sender.key_tap(0x77)
    assert "模拟点击 (30, 40)" in caplog.text
    assert "模拟按键" in caplog.text


def test_build_channel_dry_run_needs_no_window(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("干跑模式不应查询窗口")

    monkeypatch.setattr(input_sender, "find_window", boom)
    config = AppConfig.default()
    channel = input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert isinstance(channel.sender, input_sender.DryRunSender)
    assert channel.readiness is None


# ------------------------------------------------- 点击越界校验（必须在窗口内）


def test_point_in_client_area_boundaries(monkeypatch) -> None:
    """客户区判定：含左上、不含右下边界，负坐标一律算越界。"""
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    assert input_sender.point_in_client_area(1, 0, 0) == (True, "客户区 100x50")
    assert input_sender.point_in_client_area(1, 99, 49)[0] is True
    assert input_sender.point_in_client_area(1, 100, 10)[0] is False
    assert input_sender.point_in_client_area(1, 10, 50)[0] is False
    assert input_sender.point_in_client_area(1, -1, 0)[0] is False
    assert input_sender.point_in_client_area(1, 0, -1)[0] is False


def test_point_in_client_area_read_failure(monkeypatch, caplog) -> None:
    """读不到客户区时按越界处理（宁可不点击）。"""
    caplog.set_level(logging.WARNING)

    def boom(hwnd: int):
        raise OSError("窗口已关闭")

    monkeypatch.setattr(input_sender, "get_client_rect", boom)
    inside, detail = input_sender.point_in_client_area(1, 10, 10)
    assert inside is False
    assert "无法读取窗口客户区" in detail
    assert "读取窗口客户区失败" in caplog.text


def test_dry_run_sender_reports_out_of_bounds(caplog) -> None:
    """干跑通道注入窗口矩形后：越界点击只写提示日志，不写"模拟点击"，也不产生输入。"""
    caplog.set_level(logging.WARNING)
    sender = input_sender.DryRunSender(bounds=lambda x, y: (False, "客户区 100x50"))
    sender.click_at(150, 10)
    assert "不在游戏窗口内" in caplog.text and "已跳过" in caplog.text
    assert "模拟点击 (150, 10)" not in caplog.text


def test_dry_run_sender_logs_click_inside_bounds(caplog) -> None:
    """范围内的点击照常写"模拟点击"日志。"""
    caplog.set_level(logging.INFO)
    sender = input_sender.DryRunSender(bounds=lambda x, y: (True, "客户区 100x50"))
    sender.click_at(10, 10)
    assert "模拟点击 (10, 10)" in caplog.text


def test_build_channel_dry_run_validates_click_against_window(monkeypatch, caplog) -> None:
    """干跑模式下若能查到游戏窗口，就按真实客户区校验点击范围（干跑也能提前发现越界配置）。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 777)
    monkeypatch.setattr(input_sender, "get_client_rect", lambda hwnd: (0, 0, 100, 50))
    config = AppConfig.default()
    channel = input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    channel.sender.click_at(10, 10)
    channel.sender.click_at(500, 10)
    assert "模拟点击 (10, 10)" in caplog.text
    assert "不在游戏窗口内" in caplog.text


def test_build_channel_dry_run_tolerates_missing_window(monkeypatch, caplog) -> None:
    """干跑时找不到窗口不做越界校验、也不失败（干跑不需要游戏正在运行）。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: None)
    config = AppConfig.default()
    channel = input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    channel.sender.click_at(10, 10)
    assert "模拟点击 (10, 10)" in caplog.text
    assert "未找到" in caplog.text


def test_build_channel_real_mode_missing_window(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: None)
    config = AppConfig.default()
    config.automation.dry_run = False
    with pytest.raises(input_sender.WindowUnavailableError) as excinfo:
        input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert "未找到" in str(excinfo.value)


def test_build_channel_real_mode_minimized_window(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "find_window", lambda keyword: 555)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)
    config = AppConfig.default()
    config.automation.dry_run = False
    with pytest.raises(input_sender.WindowUnavailableError) as excinfo:
        input_sender.build_channel(config, threading.Event(), lambda s: None, input_sender.logger)
    assert "最小化" in str(excinfo.value) or "不可见" in str(excinfo.value)


def test_readiness_gate_ready_when_window_visible(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    gate = input_sender.WindowReadinessGate(1, threading.Event(), lambda s: None)
    assert gate.wait_until_ready() is True


def test_readiness_gate_returns_false_on_stop(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: True)
    stop_event = threading.Event()
    stop_event.set()
    gate = input_sender.WindowReadinessGate(1, stop_event, lambda s: None)
    assert gate.wait_until_ready() is False


def test_readiness_gate_stop_during_pause(monkeypatch, caplog) -> None:
    """暂停等待期间收到停止请求 → 返回 False（不继续执行）。"""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: False)  # 窗口不可用 → 进入等待
    stop_event = threading.Event()

    def fake_sleep(seconds: float) -> None:
        stop_event.set()  # 等待期间的第一次轮询就收到停止请求

    gate = input_sender.WindowReadinessGate(1, stop_event, fake_sleep)
    assert gate.wait_until_ready() is False
    assert "停止" in caplog.text


def test_readiness_gate_waits_when_minimized_then_restored(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO)
    states = {"ready": False}
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender, "is_window_ready", lambda hwnd: states["ready"])

    def fake_sleep(seconds: float) -> None:
        states["ready"] = True

    gate = input_sender.WindowReadinessGate(1, threading.Event(), fake_sleep)
    assert gate.wait_until_ready() is True
    assert "最小化" in caplog.text or "不可见" in caplog.text


def test_readiness_gate_raises_when_window_destroyed(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: False)
    gate = input_sender.WindowReadinessGate(1, threading.Event(), lambda s: None)
    with pytest.raises(input_sender.WindowUnavailableError):
        gate.wait_until_ready()


def test_is_window_ready_combines_checks(monkeypatch) -> None:
    monkeypatch.setattr(input_sender, "window_exists", lambda hwnd: True)
    monkeypatch.setattr(input_sender.win32gui, "IsWindowVisible", lambda hwnd: True)
    monkeypatch.setattr(input_sender.win32gui, "IsIconic", lambda hwnd: False)
    assert input_sender.is_window_ready(1) is True
    monkeypatch.setattr(input_sender.win32gui, "IsIconic", lambda hwnd: True)
    assert input_sender.is_window_ready(1) is False
