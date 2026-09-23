"""参考图「移除时要不要连磁盘文件一起删」的策略测试（纯逻辑，不碰 Qt）。

用户 2026-09-22 选定（三个口径都是用户当场选的）：
① **只真删工具管理的两个目录**里的图片（`assets/templates/`、`assets/anchors/`），
   仓库外选的图片（比如从桌面选的）只从列表移除；
② 「×」和「清空全部」两个入口都要**二次确认**（弹框由 `gui.dialogs.confirm` 负责，
   控制器调用前先算好"到底会删哪些文件"）；
③ 同一张图**还被别的建筑引用**时不删文件，只从当前列表移除 —— 否则另一处会变成
   "找不到文件"。

这里只测**纯函数**（`plan_deletions` / `delete_files`）：什么该删、什么留下、失败了怎么报。
"""

import pathlib

from luoluotool.gui import daily_files
from luoluotool.gui.daily_files import delete_files, plan_deletions
from luoluotool.utils.paths import PROJECT_ROOT, get_anchors_dir, get_templates_dir


def _file(root: pathlib.Path, name: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")           # 内容无所谓，只要求是个真文件
    return path


def _managed(tmp_path: pathlib.Path, monkeypatch) -> tuple[pathlib.Path, pathlib.Path]:
    """把"工具管理的两个目录"指到临时目录（不碰仓库里的真实 assets/）。"""
    templates = tmp_path / "templates"
    anchors = tmp_path / "anchors"
    monkeypatch.setattr(daily_files, "managed_roots", lambda: (templates, anchors))
    return templates, anchors


def test_managed_roots_are_the_two_tool_directories() -> None:
    """契约：管理目录＝`assets/templates` 与 `assets/anchors`（不含 screenshots）。"""
    roots = daily_files.managed_roots()

    assert roots == (get_templates_dir().resolve(), get_anchors_dir().resolve())
    assert PROJECT_ROOT / "assets" / "templates" in roots
    assert PROJECT_ROOT / "assets" / "screenshots" not in roots


def test_plan_marks_files_in_managed_dirs_as_deletable(tmp_path, monkeypatch) -> None:
    """管理目录里的图片：计划里就是"要删"，`describe()` 说清删几个、叫什么。"""
    templates, anchors = _managed(tmp_path, monkeypatch)
    first = _file(templates, "鸡舍_1.png")
    second = _file(anchors, "鸡舍_岛屿1_20260922.png")

    plan = plan_deletions([str(first), str(second)])

    assert plan.deletable == ((str(first), first.resolve()), (str(second), second.resolve()))
    assert plan.will_delete() is True
    assert plan.names() == ["鸡舍_1.png", "鸡舍_岛屿1_20260922.png"]
    assert "2 个" in plan.describe() and "鸡舍_1.png" in plan.describe()
    assert plan.kept_outside == () and plan.kept_shared == () and plan.missing == ()


def test_plan_keeps_files_outside_the_managed_dirs(tmp_path, monkeypatch) -> None:
    """仓库外/其它目录的图片（从桌面选的）：只从列表移除，**不动磁盘**。"""
    templates, _anchors = _managed(tmp_path, monkeypatch)
    outside = _file(tmp_path / "桌面", "我的截图.png")

    plan = plan_deletions([str(_file(templates, "鸡舍_1.png")), str(outside)])

    assert [path.name for _value, path in plan.deletable] == ["鸡舍_1.png"]
    assert plan.kept_outside == (str(outside),)
    assert "不在" in plan.describe() and "未删除" in plan.describe()


def test_plan_keeps_files_that_other_buildings_still_reference(tmp_path, monkeypatch) -> None:
    """同一张图还被别的建筑引用：不删文件（否则那一组会变成"找不到文件"）。"""
    templates, _anchors = _managed(tmp_path, monkeypatch)
    shared = _file(templates, "共用.png")
    own = _file(templates, "鸡舍_2.png")

    plan = plan_deletions([str(shared), str(own)], still_referenced={str(shared)})

    assert [path.name for _value, path in plan.deletable] == ["鸡舍_2.png"]
    assert plan.kept_shared == (str(shared),)
    assert "其它建筑" in plan.describe()


def test_plan_reports_files_that_are_already_gone(tmp_path, monkeypatch) -> None:
    """磁盘上本来就没有的文件（用户手动删过/改了名）：单独记一笔，不算"要删"。"""
    templates, _anchors = _managed(tmp_path, monkeypatch)
    gone = templates / "没有这张.png"

    plan = plan_deletions([str(gone), ""])

    assert plan.deletable == ()
    assert plan.missing == (str(gone), "")
    assert plan.will_delete() is False
    assert "没有文件" in plan.describe()


def test_delete_files_removes_only_the_planned_files(tmp_path, monkeypatch) -> None:
    """真删：只删计划里的那些，别的文件（包括同目录的）一个都不碰。"""
    templates, anchors = _managed(tmp_path, monkeypatch)
    doomed = _file(templates, "要删的.png")
    untouched = _file(templates, "留着的.png")
    also_doomed = _file(anchors, "框选产物.png")
    plan = plan_deletions([str(doomed), str(also_doomed), str(untouched)],
                          still_referenced={str(untouched)})

    outcome = delete_files(plan, daily_files.logger)

    assert doomed.exists() is False
    assert also_doomed.exists() is False
    assert untouched.exists() is True                  # 被别的建筑引用 → 没删
    assert outcome.deleted == [str(doomed), str(also_doomed)]
    assert outcome.failed == []
    assert outcome.summary() == "已删除 2 个文件"


def test_delete_files_reports_a_failure_without_raising(tmp_path, monkeypatch, caplog) -> None:
    """删不掉（被占用/没权限）不许炸：记 WARNING + 把原因带回给调用方去提示。"""
    templates, _anchors = _managed(tmp_path, monkeypatch)
    locked = _file(templates, "被占用.png")
    plan = plan_deletions([str(locked)])

    def boom(path):
        raise PermissionError(f"另一个程序正在使用此文件：{path.name}")

    monkeypatch.setattr(daily_files, "remove_file", boom)

    with caplog.at_level("WARNING"):
        outcome = delete_files(plan, daily_files.logger)

    assert locked.exists() is True
    assert outcome.deleted == []
    assert outcome.failed == [(str(locked), "另一个程序正在使用此文件：被占用.png")]
    assert outcome.summary() == "1 个文件删除失败"
    assert any("参考图文件删除失败" in record.message for record in caplog.records)
