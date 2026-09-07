"""配置持久化：原子读写与损坏恢复。"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from luoluotool.config.models import AppConfig
from luoluotool.config.validation import validate

logger = logging.getLogger(__name__)


def save(config: AppConfig, path: Path) -> None:
    """原子保存：写临时文件后 os.replace；失败时清理临时文件并抛出。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(config.to_dict(), fp, ensure_ascii=False, indent=2)
            fp.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        logger.exception("配置保存失败：%s", path)
        tmp_path.unlink(missing_ok=True)
        raise


def load(path: Path) -> AppConfig:
    """加载配置；不存在则生成默认；损坏则备份为 .bak-<时间戳> 并恢复默认。"""
    path = Path(path)
    if not path.exists():
        config = AppConfig.default()
        save(config, path)
        logger.info("配置文件不存在，已生成默认配置：%s", path)
        return config
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        errors = validate(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return _recover(path, f"读取/解析失败：{exc}")
    if errors:
        return _recover(path, "；".join(errors))
    logger.info("配置加载成功：%s", path)
    return AppConfig.from_dict(raw)


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
