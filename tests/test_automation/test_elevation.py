"""automation.elevation 测试：权限检测与 UAC 提权重启（注入假 API）。"""

from luoluotool.automation import elevation


class _FakeHandle:
    def __init__(self) -> None:
        self.closed = False

    def Close(self) -> None:
        self.closed = True


def _fake_windll(**functions):
    inner = type("S", (), {name: staticmethod(fn) for name, fn in functions.items()})()
    return type("W", (), {"shell32": inner})()


def test_is_process_elevated_true(monkeypatch) -> None:
    monkeypatch.setattr(elevation.ctypes, "windll", _fake_windll(IsUserAnAdmin=lambda: 1))
    assert elevation.is_process_elevated() is True


def test_is_process_elevated_failure_returns_false(monkeypatch) -> None:
    def boom():
        raise OSError("no shell32")

    monkeypatch.setattr(elevation.ctypes, "windll", _fake_windll(IsUserAnAdmin=boom))
    assert elevation.is_process_elevated() is False


def test_is_window_elevated_true_and_closes_handles(monkeypatch) -> None:
    process_handle = _FakeHandle()
    token_handle = _FakeHandle()
    monkeypatch.setattr(elevation.win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 4242))
    monkeypatch.setattr(elevation.win32api, "OpenProcess", lambda *args: process_handle)
    monkeypatch.setattr(elevation.win32security, "OpenProcessToken", lambda *args: token_handle)
    monkeypatch.setattr(elevation.win32security, "GetTokenInformation", lambda *args: True)
    assert elevation.is_window_elevated(123) is True
    assert process_handle.closed is True
    assert token_handle.closed is True


def test_is_window_elevated_unknown_returns_none(monkeypatch) -> None:
    def boom(*args):
        raise OSError("拒绝访问")

    monkeypatch.setattr(elevation.win32process, "GetWindowThreadProcessId", lambda hwnd: (1, 4242))
    monkeypatch.setattr(elevation.win32api, "OpenProcess", boom)
    assert elevation.is_window_elevated(123) is None


def test_build_relaunch_command_uses_module_entry(monkeypatch) -> None:
    monkeypatch.setattr(elevation.sys, "frozen", False, raising=False)
    executable, parameters = elevation.build_relaunch_command(["--config", "c.json"])
    assert executable == elevation.sys.executable
    assert "-m luoluotool" in parameters
    assert "--config c.json" in parameters


def test_build_relaunch_command_for_frozen_exe(monkeypatch) -> None:
    monkeypatch.setattr(elevation.sys, "frozen", True, raising=False)
    executable, parameters = elevation.build_relaunch_command(["--config", "c.json"])
    assert executable == elevation.sys.executable
    assert parameters == "--config c.json"


def test_restart_as_admin_success(monkeypatch) -> None:
    recorded: dict[str, str] = {}

    def fake_shell_execute(hwnd, operation, file, params, directory, show):
        recorded.update(operation=operation, file=file, params=params)
        return 42

    monkeypatch.setattr(elevation.ctypes, "windll", _fake_windll(ShellExecuteW=fake_shell_execute))
    assert elevation.restart_as_admin(["--config", "x"]) is True
    assert recorded["operation"] == "runas"
    assert "-m luoluotool" in recorded["params"]


def test_restart_as_admin_cancelled(monkeypatch) -> None:
    monkeypatch.setattr(elevation.ctypes, "windll", _fake_windll(ShellExecuteW=lambda *args: 5))
    assert elevation.restart_as_admin([]) is False


def test_restart_as_admin_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(elevation.sys, "platform", "linux")
    assert elevation.restart_as_admin([]) is False
