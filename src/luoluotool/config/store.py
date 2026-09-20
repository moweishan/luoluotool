"""配置持久化：原子读写与损坏恢复。"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from luoluotool.config.models import SCHEMA_VERSION, AppConfig
from luoluotool.config.validation import migrate, validate

logger = logging.getLogger(__name__)


class ConfigSaveError(RuntimeError):
    """拒绝保存不合法配置（保存它会在下次启动被判损坏 → 整份恢复默认，评审 P1-2）。"""


def save(config: AppConfig, path: Path) -> None:
    """原子保存：写临时文件后 os.replace；失败时清理临时文件并抛出。

    保存前先 `validate()`：不合法就抛 `ConfigSaveError` 且**不动磁盘上的旧文件** ——
    旧实现允许写出"自己读不回来"的配置，下次启动判损坏、备份后整份恢复默认（用户设置全丢）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    errors = validate(config.to_dict())
    if errors:
        logger.error("拒绝保存不合法配置（%s）：%s", path, "；".join(errors))
        raise ConfigSaveError("配置不合法，未保存：" + "；".join(errors))
    _backup_if_newer(path)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(config.to_dict(), fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(tmp_path, path)
    except Exception:                              # 含 json.dump 的类型错误：临时文件都要清理（评审 P3-6）
        logger.exception("配置保存失败：%s", path)
        tmp_path.unlink(missing_ok=True)
        raise


def _backup_if_newer(path: Path) -> None:
    """磁盘上的配置版本比本程序新时，先备份再覆盖（评审 P2-1：降级运行不得静默吃掉新配置）。"""
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        version = raw.get("schema_version") if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(version, bool) or not isinstance(version, int) or version <= SCHEMA_VERSION:
        return
    backup = Path(f"{path}.bak-v{version}-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    try:
        os.replace(path, backup)
        logger.warning(
            "磁盘上的配置是更新的 schema v%d（本程序 v%d），已备份到 %s 后再写入",
            version, SCHEMA_VERSION, backup,
        )
    except OSError as exc:
        logger.error("备份更新版本的配置失败（%s），仍继续写入：%s", backup, exc)


def load(path: Path) -> AppConfig:
    """加载配置；不存在则生成默认；旧版本自动迁移；损坏则备份恢复默认。"""
    path = Path(path)
    if not path.exists():
        config = AppConfig.default()
        save(config, path)
        logger.info("配置文件不存在，已生成默认配置：%s", path)
        return config
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return _recover(path, f"读取/解析失败：{exc}")
    if isinstance(raw, dict):
        version = raw.get("schema_version")
        if isinstance(version, int) and not isinstance(version, bool) and version > SCHEMA_VERSION:
            # 更高版本：只读返回默认值，**不改动文件**（评审 P2-1；降级启动不再吃掉用户设置）
            logger.warning(
                "配置文件的 schema v%d 高于本程序 v%d，已按默认值只读启动（文件未被修改）：%s",
                version, SCHEMA_VERSION, path,
            )
            return AppConfig.default()
    try:
        migrated_raw = migrate(raw)
    except Exception as exc:       # 迁移内部任何异常都转成损坏恢复，绝不冒到 GUI（评审 P1-1）
        logger.exception("配置迁移失败：%s", path)
        return _recover(path, f"迁移失败：{exc}")
    errors = validate(migrated_raw)
    if errors:
        return _recover(path, "；".join(errors))
    config = AppConfig.from_dict(migrated_raw)
    if migrated_raw is not raw:
        save(config, path)
        logger.info("配置已迁移到 schema v%d 并写回：%s", SCHEMA_VERSION, path)
    logger.info("配置加载成功：%s", path)
    return config


def _recover(path: Path, reason: str) -> AppConfig:
    """损坏文件备份为 <文件名>.bak-<时间戳>，写回默认配置。"""
    backup = Path(f"{path}.bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
    try:
        os.replace(path, backup)
        logger.warning("配置损坏（%s），已备份到 %s，恢复默认值", reason, backup)
    except OSError as exc:
        logger.error("配置损坏（%s），备份失败（%s），直接恢复默认值", reason, exc)
    config = AppConfig.default()
    save(config, path)
    return config
