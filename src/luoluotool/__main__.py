"""python -m luoluotool 入口：CLI 参数解析与分发。"""

import argparse
import json
import sys
from pathlib import Path

from luoluotool import __version__
from luoluotool.automation.vision import DEFAULT_THRESHOLD as DEFAULT_VISION_THRESHOLD
from luoluotool.config.validation import migrate, validate
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
    parser.add_argument(
        "--measure-layout",
        action="store_true",
        help="离屏测量各页签的布局占用并打印报告（页签高度稳定规则的回归检查）",
    )
    parser.add_argument(
        "--recognize",
        metavar="IMAGE",
        help="在当前游戏窗口客户区里查找该图片（模板匹配），打印命中位置的客户区坐标",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_VISION_THRESHOLD,
        metavar="0-1",
        help=f"图像识别阈值（默认 {DEFAULT_VISION_THRESHOLD}，越高越严格）",
    )
    parser.add_argument(
        "--no-annotate",
        action="store_true",
        help="图像识别时不保存带框截图（默认跟随配置项 automation.save_vision_annotations）",
    )
    parser.add_argument(
        "--no-scale",
        action="store_true",
        help="图像识别只按原始尺寸匹配（默认两档多尺度：先搜 0.3x–2.0x，找不到再扩到 0.3x–4.0x）",
    )
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
    if args.measure_layout:
        return _measure_layout(Path(args.config) if args.config else None)
    if args.recognize:
        return _recognize(
            Path(args.recognize),
            args.threshold,
            Path(args.config) if args.config else None,
            annotate=not args.no_annotate,
            allow_scale=not args.no_scale,
        )
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
    errors = validate(migrate(raw))
    if errors:
        for error in errors:
            print(error)
        return 1
    print("OK")
    return 0


def _print_safe(text: str) -> None:
    """打印一行文本；控制台编码不支持某些字符时降级为替换字符，绝不因编码异常崩溃。

    背景（2026-09-19 实测）：冻结后的 exe 是 GUI 子系统，stdout 按系统 ANSI 代码页
    （中文机为 cp936）初始化且忽略 PYTHONIOENCODING/PYTHONUTF8，报告里的 `✓` 这类符号
    无法编码 → UnicodeEncodeError → `--measure-layout` 退出码 1。这里先原样打印，
    失败后按当前编码把不可编码字符替换掉再打印；窗口化进程 stdout 为 None 时静默跳过。
    """
    stream = sys.stdout
    try:
        stream.write(f"{text}\n")
        return
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace") + "\n")
    except AttributeError:
        # stdout 为 None（窗口化进程没有控制台，且未挂运行时钩子）：无处可写，跳过
        return


def _measure_layout(config_path: Path | None) -> int:
    """离屏测量各页签的布局占用并打印报告；退出码 0 通过 / 1 发现问题。

    只读几何测量：不写配置（配置文件不存在时用默认配置），不产生任何输入。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from luoluotool.config.models import AppConfig
    from luoluotool.config import store
    from luoluotool.gui.layout_measure import format_measure_report, measure_layout
    from luoluotool.gui.main_window import MainWindow

    path = config_path or get_user_data_dir() / "config.json"
    config = store.load(path) if path.exists() else AppConfig.default()
    app = QApplication.instance() or QApplication(["luoluotool"])
    window = MainWindow(config, path, auto_elevate=False)
    window.show()
    app.processEvents()
    measure = measure_layout(window)
    _print_safe(format_measure_report(measure))
    window.close()
    window.deleteLater()
    app.processEvents()
    return 0 if measure.ok else 1


def _recognize(
    image_path: Path,
    threshold: float,
    config_path: Path | None,
    annotate: bool,
    allow_scale: bool = True,
) -> int:
    """命令行图像识别：在游戏窗口里查找 `image_path`，打印命中位置的客户区坐标。

    退出码：0 命中；1 未命中或识别失败（便于脚本判断）；2 参数非法。
    带框截图：传 `--no-annotate` 强制关闭；否则跟随配置 `automation.save_vision_annotations`。
    匹配方式：默认两档多尺度（先 0.3x–2.0x，找不到再扩到 0.3x–4.0x）；`--no-scale` 只按原始尺寸匹配。
    """
    if not 0.0 < threshold <= 1.0:
        _print_safe(f"阈值必须大于 0 且不超过 1：{threshold}")
        return 2

    from luoluotool.config import store
    from luoluotool.config.models import AppConfig
    from luoluotool.core.vision import recognize_in_window
    from luoluotool.utils import logging_setup

    logging_setup.setup_logging()
    path = config_path or get_user_data_dir() / "config.json"
    config = store.load(path) if path.exists() else AppConfig.default()
    result = recognize_in_window(
        config, image_path, threshold=threshold,
        annotate_result=None if annotate else False,
        allow_scale=allow_scale,
    )
    _print_safe(result.message)
    return 0 if result.found else 1


if __name__ == "__main__":
    sys.exit(main())