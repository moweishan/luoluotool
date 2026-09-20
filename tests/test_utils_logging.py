"""utils.logging_setup / utils.paths 测试（评审 P2-2、P3-7 的回归）。"""

import logging

import pytest

from luoluotool.utils import logging_setup, paths


@pytest.fixture(autouse=True)
def _isolate_logging(tmp_path, monkeypatch):
    """把日志目录指到 tmp，并在用例结束后还原根日志器（避免污染其它测试）。"""
    monkeypatch.setattr(logging_setup, "get_logs_dir", lambda: tmp_path)
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield tmp_path
    for handler in list(root.handlers):
        if handler not in saved_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(saved_level)


def _file_handler() -> logging.Handler | None:
    return next(
        (h for h in logging.getLogger().handlers
         if isinstance(h, logging.handlers.RotatingFileHandler)),
        None,
    )


def test_setup_logging_applies_configured_level_and_rotation(tmp_path) -> None:
    """回归（评审 P2-2）：config.logging 的 level / max_file_mb / backup_count 必须真正生效。"""
    logging_setup.setup_logging(level=logging.WARNING, max_file_mb=5, backup_count=7)

    assert logging.getLogger().level == logging.WARNING
    handler = _file_handler()
    assert handler is not None
    assert handler.maxBytes == 5 * 1024 * 1024
    assert handler.backupCount == 7
    assert (tmp_path / "luoluotool.log").exists()


def test_setup_logging_reconfigures_without_duplicating_handlers(tmp_path) -> None:
    """重复调用（GUI 先默认初始化、读到配置后再按配置重建）不能叠加 handler。"""
    logging_setup.setup_logging(level=logging.INFO, max_file_mb=2, backup_count=3)
    logging_setup.setup_logging(level=logging.DEBUG, max_file_mb=9, backup_count=1)
    logging_setup.setup_logging(level=logging.DEBUG, max_file_mb=9, backup_count=1)   # 幂等

    file_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].maxBytes == 9 * 1024 * 1024
    assert file_handlers[0].backupCount == 1
    assert logging.getLogger().level == logging.DEBUG


def test_ensure_dir_reports_failure_without_raising(tmp_path, monkeypatch, caplog) -> None:
    """回归（评审 P3-7）：目录创建失败只告警并返回路径，不冒原始 traceback。"""
    caplog.set_level(logging.WARNING)

    def boom(self, parents=False, exist_ok=False):
        raise OSError("模拟只读盘")

    monkeypatch.setattr(paths.Path, "mkdir", boom)
    result = paths._ensure_dir(tmp_path / "nope")

    assert result == tmp_path / "nope"
    assert "无法创建目录" in caplog.text
