"""「移除参考图时连磁盘文件一起删 + 二次确认」的控制器测试。

用户 2026-09-22 选定：① 只真删 `assets/templates/` 与 `assets/anchors/` 里的图片；
② 「×」与「清空全部」都要**先弹一次确认**（取消＝配置与文件都不动）；
③ 还被别的建筑引用的文件不删。

**绝不真的弹框**：`daily_deletion.confirm_destructive` 被替换成假函数（返回 True/False）——
注意补丁要打在 **`daily_deletion`** 上（`remove_image` / `clear_images` 住在那个 mixin 里，
打在 `daily_media` 上不会生效，AGENTS §2④）。
纯策略（什么该删）在 `tests/test_gui_daily_files.py`；这里测"控制器把两者接起来"。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui_helpers import (
    daily_media_controller,
    daily_media_page,
    wait_for_daily_decoding,
)
from luoluotool.config.models import AppConfig
from luoluotool.gui import daily_deletion, daily_files
from luoluotool.utils.paths import to_config_path

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig, changes: list[str]):
    return daily_media_page(config, changes)


def _controller(page, config: AppConfig, changes: list[str]):
    return daily_media_controller(page, config, changes)


def _wait_for_decoding(controller, timeout_ms: int = 5000) -> None:
    wait_for_daily_decoding(controller, timeout_ms)


def _managed(tmp_path, monkeypatch):
    """把"工具管理的两个目录"指到临时目录，这样临时图片算"工具管的"、可以被真删。"""
    templates = tmp_path / "templates"
    anchors = tmp_path / "anchors"
    templates.mkdir(parents=True, exist_ok=True)
    anchors.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(daily_files, "managed_roots", lambda: (templates, anchors))
    return templates, anchors


def _confirm(monkeypatch, answer: bool, calls: list | None = None) -> None:
    def fake_confirm(parent, title, text, *, detail="", confirm_text="删除"):
        if calls is not None:
            calls.append({"title": title, "text": text, "detail": detail,
                          "confirm_text": confirm_text})
        return answer

    monkeypatch.setattr(daily_deletion, "confirm_destructive", fake_confirm)


def _picked(tmp_path, monkeypatch, textured_png, prefix: str, count: int, **kwargs):
    """选一组图片进来（放在"管理目录"里），返回 (config, page, controller, 文件列表)。"""
    templates, _anchors = _managed(tmp_path, monkeypatch)
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    paths = []
    for index in range(count):
        source = textured_png(f"{prefix}_{index}.png")
        target = templates / source.name
        target.write_bytes(source.read_bytes())
        paths.append(target)
    controller.start_pick(prefix, paths)
    _wait_for_decoding(controller)
    changes.clear()
    return config, page, controller, paths


def test_remove_deletes_the_real_file_after_confirmation(tmp_path, monkeypatch, textured_png) -> None:
    """确认后：配置里的那张没了，**磁盘上的文件也没了**，状态栏说清删了哪个文件。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "coop", 2)
    calls: list[dict] = []
    _confirm(monkeypatch, True, calls)

    controller.remove_image("coop", 0)

    assert calls and "删除" in calls[0]["title"]
    assert paths[0].name in calls[0]["text"]            # 弹框里点名要删哪个文件
    assert paths[0].exists() is False                   # 真删了
    assert paths[1].exists() is True                    # 另一张没动
    assert config.features.daily_tasks.coop_island_ref_image == [to_config_path(paths[1])]
    assert page.reference_images("coop") == [to_config_path(paths[1])]
    assert page.thumbnail_strip("coop").count() == 1
    assert "已移除" in controller.statuses[-1] and "删除" in controller.statuses[-1]
    page.close()


def test_remove_keeps_everything_when_the_user_cancels(tmp_path, monkeypatch, textured_png) -> None:
    """二次确认点了「取消」：配置、界面、磁盘文件**一个都不动**。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "land", 2)
    before = list(config.features.daily_tasks.land_ref_image)
    _confirm(monkeypatch, False)

    controller.remove_image("land", 0)

    assert paths[0].exists() is True
    assert config.features.daily_tasks.land_ref_image == before
    assert page.thumbnail_strip("land").count() == 2
    assert "已取消" in controller.statuses[-1]
    page.close()


def test_remove_keeps_the_file_another_building_still_references(
    tmp_path, monkeypatch, textured_png
) -> None:
    """同一张图还在别的建筑列表里：只从当前列表移除，**文件留着**并在状态栏说明原因。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "coop", 1)
    config.features.daily_tasks.land_ref_image = [to_config_path(paths[0])]   # 土地也用了同一张
    _confirm(monkeypatch, True)

    controller.remove_image("coop", 0)

    assert paths[0].exists() is True                                  # 没删（另一处还在用）
    assert config.features.daily_tasks.coop_island_ref_image == []
    assert config.features.daily_tasks.land_ref_image == [to_config_path(paths[0])]
    assert "其它建筑" in controller.statuses[-1]
    page.close()


def test_remove_keeps_a_file_outside_the_managed_dirs(
    tmp_path, monkeypatch, textured_png
) -> None:
    """不是工具管的目录（比如从桌面选的图）：只从列表移除，文件**不删**。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    controller = _controller(page, config, changes)
    outside = textured_png("桌面上的.png")            # 就在 pytest 的 tmp 里，不在管理目录
    controller.start_pick("aqua", [outside])
    _wait_for_decoding(controller)
    _confirm(monkeypatch, True)

    controller.remove_image("aqua", 0)

    assert outside.exists() is True
    assert config.features.daily_tasks.aqua_ref_image == []
    assert "不在" in controller.statuses[-1]
    page.close()


def test_clear_deletes_all_managed_files_after_confirmation(
    tmp_path, monkeypatch, textured_png
) -> None:
    """「清空全部」确认后：3 张文件全删、配置清空、界面清空，弹框里列出全部文件名。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "coop", 3)
    calls: list[dict] = []
    _confirm(monkeypatch, True, calls)

    controller.clear_images("coop")

    assert calls and "清空" in calls[0]["title"]
    assert all(path.name in calls[0]["text"] for path in paths)      # 弹框点名列全
    assert all(path.exists() is False for path in paths)
    assert config.features.daily_tasks.coop_island_ref_image == []
    assert page.thumbnail_strip("coop").count() == 0
    assert page.clear_button("coop").isEnabled() is False            # 清空后按钮回到禁用
    assert "已清空" in controller.statuses[-1] and "3 个文件" in controller.statuses[-1]
    page.close()


def test_clear_can_be_cancelled(tmp_path, monkeypatch, textured_png) -> None:
    """「清空全部」也可以取消：什么都没发生。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "aqua", 2)
    before = list(config.features.daily_tasks.aqua_ref_image)
    _confirm(monkeypatch, False)

    controller.clear_images("aqua")

    assert all(path.exists() for path in paths)
    assert config.features.daily_tasks.aqua_ref_image == before
    assert page.thumbnail_strip("aqua").count() == 2
    assert "已取消" in controller.statuses[-1]
    page.close()


def test_failed_file_deletion_is_reported_but_the_entry_is_still_removed(
    tmp_path, monkeypatch, textured_png
) -> None:
    """删文件失败（被占用）：配置照旧移除，但状态栏必须说清"文件没删掉 + 看日志"。"""
    config, page, controller, paths = _picked(tmp_path, monkeypatch, textured_png, "coop", 1)
    _confirm(monkeypatch, True)

    def boom(path):
        raise PermissionError("另一个程序正在使用此文件")

    monkeypatch.setattr(daily_files, "remove_file", boom)

    controller.remove_image("coop", 0)

    assert paths[0].exists() is True
    assert config.features.daily_tasks.coop_island_ref_image == []
    assert "没删掉" in controller.statuses[-1] and "luoluotool.log" in controller.statuses[-1]
    page.close()
