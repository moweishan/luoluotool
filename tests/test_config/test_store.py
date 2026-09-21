"""config.store 测试：原子读写、损坏备份与恢复。"""

import json

import pytest

from luoluotool.config import models
from luoluotool.config import store


@pytest.mark.real_defaults
def test_first_run_config_file_has_dry_run_off(tmp_path) -> None:
    """首次启动生成的文件必须是 `dry_run: false`（用户 2026-09-19 要求：干跑默认不开启）。"""
    path = tmp_path / "config.json"
    store.load(path)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["automation"]["dry_run"] is False


def test_load_missing_file_creates_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = store.load(path)
    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert (
        json.loads(path.read_text(encoding="utf-8"))["schema_version"] == models.SCHEMA_VERSION
    )


def test_load_migrates_v1_file_and_rewrites(tmp_path) -> None:
    """旧版 v1 文件：迁移为 v2（补默认字段）并写回，不作为损坏处理。"""
    v1_raw = {
        "schema_version": 1,
        "features": {
            "daily_tasks": {
                "enabled": True,
                "tasks": {"placeholder_task_a": {"enabled": False, "order": 1, "params": {}}},
                "loop": {"enabled": False, "interval_seconds": 3600},
            },
            "order_hold": {
                "enabled": False,
                "reserved_switch_1": False,
                "reserved_switch_2": False,
            },
            "feature_3": {"enabled": False},
            "feature_4": {"enabled": False},
        },
        "automation": {
            "dry_run": True,
            "window_title_keyword": "桃源深处有人家",
            "click_interval_ms": 1234,
            "post_click_wait_ms": 500,
            "max_consecutive_failures": 3,
            "failsafe_hotkey": "F8",
        },
        "logging": {"level": "INFO", "max_file_mb": 2, "backup_count": 3},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(v1_raw, ensure_ascii=False), encoding="utf-8")
    config = store.load(path)
    assert config.schema_version == models.SCHEMA_VERSION
    assert config.automation.ask_elevation_on_start is True
    assert config.automation.click_interval_ms == 1234
    assert config.features.daily_tasks.enabled is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == models.SCHEMA_VERSION
    assert on_disk["automation"]["ask_elevation_on_start"] is True
    assert not list(tmp_path.glob("config.json.bak-*"))


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
    broken.automation.click_interval_ms = 4555      # 合法值（保存前的校验通过），只是写盘会失败

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


# ------------------------------------------- 评审修复：迁移崩溃 / 自毁 / 高版本（P1-1、P1-2、P2-1）


def test_load_survives_malformed_params_during_migration(tmp_path) -> None:
    """回归（评审 P1-1）：迁移遇到畸形 `params`（list 等合法 JSON）必须走损坏恢复，不能崩溃。

    旧实现里 `dict(item.get("params") or {})` 会抛 TypeError，而 `store.load` 只把 JSON 解析包在
    try 内 → 异常直冒到 GUI，进程启动即崩溃。
    """
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({
            "schema_version": 5,
            "automation": {"dry_run": False},
            "features": {"daily_tasks": {"tasks": {"placeholder_task_a": {"params": [1, 2]}}}},
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    config = store.load(path)                      # 不得抛异常

    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert len(list(tmp_path.glob("config.json.bak-*"))) == 1


def test_save_refuses_invalid_config_and_keeps_old_file(tmp_path) -> None:
    """回归（评审 P1-2）：不合法配置**拒绝保存**并抛可读错误，旧文件保持不变。

    旧行为：GUI 能存下"自己读不回来"的配置，下次启动判损坏 → 备份后整份恢复默认（用户设置全丢）。
    """
    path = tmp_path / "config.json"
    good = models.AppConfig.default()
    store.save(good, path)

    broken = models.AppConfig.default()
    broken.automation.click_interval_ms = 1                  # 越界（校验要求 100–5000）

    with pytest.raises(store.ConfigSaveError, match="click_interval_ms"):
        store.save(broken, path)

    assert store.load(path).to_dict() == good.to_dict()      # 磁盘上仍是好的那份
    assert not list(tmp_path.glob("*.tmp"))


def test_load_keeps_newer_version_file_untouched(tmp_path) -> None:
    """回归（评审 P2-1）：文件版本高于本程序时只读返回默认值，**不改动文件**、不生成 .bak。"""
    path = tmp_path / "config.json"
    raw = models.AppConfig.default().to_dict()
    raw["schema_version"] = models.SCHEMA_VERSION + 1
    raw["automation"]["click_interval_ms"] = 4321
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    config = store.load(path)

    assert config.to_dict() == models.AppConfig.default().to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["automation"]["click_interval_ms"] == 4321
    assert not list(tmp_path.glob("config.json.bak-*"))


def test_save_backs_up_newer_version_file_before_overwriting(tmp_path) -> None:
    """降级运行时若用户主动保存：先把更高版本的文件备份出来，再写本程序版本。"""
    path = tmp_path / "config.json"
    raw = models.AppConfig.default().to_dict()
    raw["schema_version"] = models.SCHEMA_VERSION + 1
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    store.save(models.AppConfig.default(), path)

    backups = list(tmp_path.glob("config.json.bak-v*-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["schema_version"] == models.SCHEMA_VERSION + 1


def test_load_normalizes_the_file_and_drops_unknown_fields(tmp_path) -> None:
    """既有行为（第五轮评审 P3-6）：迁移写回会把文件**规范化** —— 未知键会消失。

    `migrate()` 本身特意保留未知键（见 `test_migrate_*`），但 `store.load` 在迁移后
    用 `AppConfig.from_dict(...).to_dict()` 重写文件，于是"程序不认识的字段"不会留在盘上。
    这不是缺陷（配置文件由本程序独占），但得有用例把行为记下来，免得日后误以为"未知键会被保留"。
    """
    path = tmp_path / "config.json"
    raw = models.AppConfig.default().to_dict()
    raw["schema_version"] = models.SCHEMA_VERSION - 1        # 老版本 → 会触发迁移写回
    raw["future_field"] = {"kept_by_migrate": True}          # 程序不认识的顶层键
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    store.load(path)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == models.SCHEMA_VERSION
    assert "future_field" not in on_disk
    # 认识的字段一个都不能丢
    assert on_disk["features"]["daily_tasks"]["loop"]["interval_seconds"] == 3600
    assert on_disk["automation"]["window_title_keyword"] == "桃源深处有人家"
