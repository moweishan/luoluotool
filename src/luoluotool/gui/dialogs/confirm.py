"""破坏性操作的二次确认弹框（默认"取消"，避免误点）。

为什么单开一个模块：日常任务页删参考图会**连磁盘文件一起删**，这种事必须问一次；
而弹框本身要能被测试替换掉（`monkeypatch.setattr(daily_media, "confirm_destructive", ...)`），
所以做成一个**模块级函数**、调用方在自己的命名空间里引用它（AGENTS §2④ 的同一条道理）。

约定：
- 传给 `exec()` 的只有这一个弹框，**绝不真的在测试里打开**（测试一律替换本函数）；
- 默认按钮必须是**取消**（回车＝取消，不能一敲回车就把用户的图删了）。
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm_destructive(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    detail: str = "",
    confirm_text: str = "删除",
) -> bool:
    """弹一次确认：用户点了"确认按钮"返回 True，点取消/关窗返回 False。

    `text` 是主句（要点名删什么），`detail` 是补充说明（不可撤销、哪些文件不会删等）。
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    confirm = box.addButton(confirm_text, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)                     # 回车＝取消（不许一敲回车就删文件）
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is confirm
