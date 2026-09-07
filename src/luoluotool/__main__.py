"""python -m luoluotool 入口：CLI 参数解析与分发。"""

import argparse
import sys

from luoluotool import __version__
from luoluotool.gui.app import run as run_gui


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(prog="luoluotool", description="LuoLooTool 启动入口")
    parser.add_argument("--version", action="store_true", help="打印版本号后退出")
    parser.add_argument("--config", metavar="PATH", help="指定配置路径启动（Phase 1 生效）")
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
        print("配置校验尚未实现（Phase 1 提供）")
        return 2
    if args.config:
        print(f"已接收配置路径参数：{args.config}（配置功能将在 Phase 1 实现，本阶段不生效）")
    return run_gui([sys.argv[0]], smoke=args.smoke_gui)


if __name__ == "__main__":
    sys.exit(main())
