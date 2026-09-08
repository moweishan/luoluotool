"""python -m luoluotool 入口：CLI 参数解析与分发。"""

import argparse
import json
import sys
from pathlib import Path

from luoluotool import __version__
from luoluotool.config.validation import validate
from luoluotool.gui.app import run as run_gui
from luoluotool.utils.paths import get_user_data_dir


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(prog="luoluotool", description="LuoLooTool 启动入口")
    parser.add_argument("--version", action="store_true", help="打印版本号后退出")
    parser.add_argument(
        "--config", metavar="PATH", help="指定配置路径（默认 user_data/config.json）"
    )
    parser.add_argument("--validate-config", action="store_true", help="校验配置并打印结果")
    parser.add_argument("--smoke-gui", action="store_true", help="离屏创建主窗口后立即退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数并分发；返回退出码 0/1/2。"""
    args = build_parser().parse_args(argv)
    if args.version:
        print(f"luoluotool {__version__}")
        return 0
    if args.validate_config:
        path = Path(args.config) if args.config else get_user_data_dir() / "config.json"
        return _validate_config(path)
    config_path = Path(args.config) if args.config else None
    return run_gui([sys.argv[0]], smoke=args.smoke_gui, config_path=config_path)


def _validate_config(path: Path) -> int:
    """校验配置文件并打印结果；退出码 0 通过 / 1 失败。"""
    if not path.exists():
        print(f"OK（配置文件不存在：{path}，首次启动将生成默认值）")
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"配置文件不是合法 JSON：{exc}")
        return 1
    errors = validate(raw)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
