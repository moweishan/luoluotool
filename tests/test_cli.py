"""CLI 入口（luoluotool.__main__）测试。"""

import json

from luoluotool.__main__ import main


def test_version_prints_name_and_version(capsys) -> None:
    """--version 输出 luoluotool 0.1.0 且退出码 0。"""
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "luoluotool 0.1.0"


def test_validate_config_missing_file_ok(capsys, tmp_path) -> None:
    """配置文件不存在视为通过并输出 OK。"""
    path = tmp_path / "config.json"
    assert main(["--validate-config", "--config", str(path)]) == 0
    assert "OK" in capsys.readouterr().out


def test_validate_config_valid_file_ok(capsys, tmp_path) -> None:
    """合法配置输出 OK 且退出码 0。"""
    from luoluotool.config import store
    from luoluotool.config.models import AppConfig

    path = tmp_path / "config.json"
    store.save(AppConfig.default(), path)
    assert main(["--validate-config", "--config", str(path)]) == 0
    assert capsys.readouterr().out.strip() == "OK"


def test_validate_config_invalid_json_exit_1(capsys, tmp_path) -> None:
    """非法 JSON 打印错误并退出码 1。"""
    path = tmp_path / "config.json"
    path.write_text("{ 不是 JSON", encoding="utf-8")
    assert main(["--validate-config", "--config", str(path)]) == 1
    assert "JSON" in capsys.readouterr().out


def test_validate_config_field_errors_exit_1(capsys, tmp_path) -> None:
    """非法字段逐条打印并退出码 1。"""
    from luoluotool.config.models import AppConfig

    path = tmp_path / "config.json"
    raw = AppConfig.default().to_dict()
    raw["automation"]["click_interval_ms"] = 99999
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert main(["--validate-config", "--config", str(path)]) == 1
    assert "click_interval_ms" in capsys.readouterr().out


def test_config_arg_accepted_then_smoke(capsys) -> None:
    """--config 参数被解析且不阻断 --smoke-gui。"""
    assert main(["--config", "custom.json", "--smoke-gui"]) == 0
    assert "custom.json" in capsys.readouterr().out
