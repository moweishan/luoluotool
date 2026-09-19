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


@pytest.fixture(autouse=True)
def _tests_never_query_real_desktop(monkeypatch):
    """单测不查询真实桌面窗口：让**调用方**持有的 `find_window` 一律返回 None。

    原因：干跑通道的坐标越界校验、图像识别都会在运行期查窗口；若测试命中用户真实运行的
    游戏窗口，断言结果就会随环境变化（实测过：客户区 0x0 → 点击被判定越界跳过，
    导致"干跑应写模拟点击日志"的用例失败）。需要窗口的测试自行 monkeypatch
    `find_window`（会覆盖本夹具的补丁）。

    注意：`automation.window.find_window` 本身是被测对象（有专属用例注入假 EnumWindows），
    这里不动它；`window.diagnose_window` 这类调用模块内函数的路径，由各自的测试自行打补丁。
    """
    from luoluotool.automation import input_sender

    monkeypatch.setattr(input_sender, "find_window", lambda keyword: None)
    try:                                  # core.vision 在导入时绑定了自己的引用
        from luoluotool.core import vision as core_vision
    except ImportError:                   # 环境缺 numpy/opencv 时跳过（不影响其它测试）
        return
    monkeypatch.setattr(core_vision, "find_window", lambda keyword: None)
