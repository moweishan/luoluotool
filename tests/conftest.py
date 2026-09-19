"""测试全局夹具。

**红线**：单测绝不产生真实输入（AGENTS.md §4）。生产环境的 `dry_run` 出厂默认已按用户
要求改为 `false`（首次启动即真实模式），但测试里必须恒为干跑——否则真实通道会去查找真实
游戏窗口并移动真实鼠标。因此本夹具把 `AppConfig.default()` 的 `dry_run` 统一强制为 `True`。

需要断言"生产默认值"的测试用 `@pytest.mark.real_defaults` 跳过本夹具（只有这类测试才能看到
生产的 `dry_run: false`）。
"""

import pytest

from luoluotool.config.models import AppConfig

REAL_DEFAULTS_MARKER = "real_defaults"


def pytest_configure(config: pytest.Config) -> None:
    """注册自定义 marker，避免未知标记告警。"""
    config.addinivalue_line(
        "markers",
        f"{REAL_DEFAULTS_MARKER}: 保留生产的 dry_run 默认值（仅用于断言出厂默认的测试）",
    )


@pytest.fixture(autouse=True)
def _tests_always_run_in_dry_run(request, monkeypatch):
    """让所有测试用配置默认走干跑（打印真实默认值需要 real_defaults 标记）。"""
    if request.node.get_closest_marker(REAL_DEFAULTS_MARKER) is not None:
        return
    original = AppConfig.default.__func__

    def patched(cls) -> AppConfig:
        config = original(cls)
        config.automation.dry_run = True
        return config

    monkeypatch.setattr(AppConfig, "default", classmethod(patched))
