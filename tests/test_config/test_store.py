"""config.store 测试：原子读写、损坏备份与恢复。"""

import json

import pytest

from luoluotool.config import models
from luoluotool.config import store


def test_load_missing_file_creates_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = store.load(path)
    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_save_load_roundtrip(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = models.AppConfig.default()
    config.automation.click_interval_ms = 4321
    config.features.order_hold.enabled = True
    store.save(config, path)
    assert store.load(path).to_dict() == config.to_dict()


def test_corrupt_json_backup_and_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ 这不是 JSON", encoding="utf-8")
    config = store.load(path)
    assert config.to_dict() == models.AppConfig.default().to_dict()
    backups = list(tmp_path.glob("config.json.bak-*"))
    assert len(backups) == 1
    assert "{ 这不是 JSON" in backups[0].read_text(encoding="utf-8")


def test_invalid_values_backup_and_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    raw = models.AppConfig.default().to_dict()
    raw["automation"]["click_interval_ms"] = 1
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    config = store.load(path)
    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert len(list(tmp_path.glob("config.json.bak-*"))) == 1


def test_save_is_atomic_and_leaves_no_tmp(tmp_path) -> None:
    path = tmp_path / "config.json"
    store.save(models.AppConfig.default(), path)
    assert not list(tmp_path.glob("*.tmp"))
    assert json.loads(path.read_text(encoding="utf-8"))


def test_replace_failure_keeps_original(tmp_path, monkeypatch) -> None:
    """模拟 os.replace 失败：原配置不被破坏，临时文件被清理。"""
    path = tmp_path / "config.json"
    original = models.AppConfig.default()
    store.save(original, path)
    broken = models.AppConfig.default()
    broken.automation.click_interval_ms = 5555

    def fake_replace(src, dst):
        raise OSError("模拟磁盘满")

    monkeypatch.setattr(store.os, "replace", fake_replace)
    with pytest.raises(OSError):
        store.save(broken, path)
    assert store.load(path).to_dict() == original.to_dict()
    assert not list(tmp_path.glob("*.tmp"))


def test_bom_utf8_file_loads_without_recovery(tmp_path) -> None:
    """Windows 记事本保存的 UTF-8 BOM 文件应正常加载，不被误判为损坏。"""
    path = tmp_path / "config.json"
    raw = models.AppConfig.default().to_dict()
    raw["automation"]["click_interval_ms"] = 2345
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8-sig")
    config = store.load(path)
    assert config.automation.click_interval_ms == 2345
    assert not list(tmp_path.glob("config.json.bak-*"))


def test_backup_failure_then_recover(tmp_path, monkeypatch) -> None:
    """备份失败时抛出异常；恢复后再次加载可正常备份并恢复默认。"""
    path = tmp_path / "config.json"
    path.write_text("{ 坏配置", encoding="utf-8")

    def fake_replace(src, dst):
        raise OSError("模拟备份失败")

    monkeypatch.setattr(store.os, "replace", fake_replace)
    with pytest.raises(OSError):
        store.load(path)
    monkeypatch.undo()
    config = store.load(path)
    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert len(list(tmp_path.glob("config.json.bak-*"))) == 1
