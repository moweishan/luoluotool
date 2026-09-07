"""CLI 入口（luoluotool.__main__）测试。"""

from luoluotool.__main__ import main


def test_version_prints_name_and_version(capsys) -> None:
    """--version 输出 luoluotool 0.1.0 且退出码 0。"""
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "luoluotool 0.1.0"


def test_validate_config_not_implemented(capsys) -> None:
    """--validate-config 本阶段返回退出码 2 并提示尚未实现。"""
    assert main(["--validate-config"]) == 2
    assert "尚未实现" in capsys.readouterr().out


def test_config_arg_accepted_then_smoke(capsys) -> None:
    """--config 参数被解析且不阻断 --smoke-gui。"""
    assert main(["--config", "custom.json", "--smoke-gui"]) == 0
    assert "custom.json" in capsys.readouterr().out
