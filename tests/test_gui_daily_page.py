"""日常任务页（界面版，第 1 批）测试：控件齐全、类型/默认值/范围与设计稿一致、**不碰配置**。

设计稿：`D:/AAAAA/workspaceCursor/杂项/日常任务设计稿.html`（用户 2026-09-21 提供）。
本批只做界面：控件改动**不写配置、不置脏标记**，动作按钮（选择图片 / 截取游戏画面）先禁用。
第 2 批接配置时会把这些测试升级成"双向绑定"测试（见 `CHECKLIST.md` 的分批记录）。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from luoluotool.config.models import AppConfig
from luoluotool.gui.pages.daily import (
    BUILDINGS,
    DESIGN_CONTROL_IDS,
    LOOP_INTERVAL_DEFAULT,
    LOOP_INTERVAL_RANGE,
    DailyPage,
)
from luoluotool.gui.widgets import PAGE_SIZE_HINT, ScrollablePage

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig | None = None, changes: list[str] | None = None) -> DailyPage:
    changes = changes if changes is not None else []
    return DailyPage(config or AppConfig.default(), lambda: changes.append("dirty"))


def test_daily_page_is_scrollable_with_the_designed_groups() -> None:
    """页签规则：必须继承 ScrollablePage（否则会顶高页签区），且三个大分组齐全。"""
    page = _page()
    assert isinstance(page, ScrollablePage)
    assert page.sizeHint() == PAGE_SIZE_HINT
    titles = [box.title() for box in page.content.findChildren(QGroupBox)]
    assert "总开关与循环时长" in titles
    assert "关键建筑位置以及图像识别所需图片" in titles
    assert "产物制造" in titles
    page.close()


def test_daily_page_has_every_control_from_the_design() -> None:
    """设计稿里的每个控件都要在页面里找得到（控件名＝设计稿的 id）。"""
    page = _page()

    assert page.daily_enabled.objectName() == "daily_enabled"
    assert isinstance(page.daily_enabled, QCheckBox)
    assert page.auto_produce_least.objectName() == "auto_produce_least"
    assert isinstance(page.auto_produce_least, QCheckBox)

    for _title, prefix, _word, ref_id, capture_id in BUILDINGS:
        island = page.findChild(QComboBox, f"{prefix}_island")
        ref_edit = page.findChild(QLineEdit, ref_id)
        pick = page.findChild(QPushButton, f"{prefix}_pick_image")
        capture = page.findChild(QPushButton, capture_id)
        assert island is not None and ref_edit is not None, prefix
        assert pick is not None and capture is not None, capture_id
        assert island.count() == 10                       # 岛屿编号 1–10
        assert island.currentText() == "1"
        assert ref_edit.isReadOnly() is True              # 只能通过「选择图片…」填
        assert page.findChild(QFrame, f"{prefix}_island_map") is not None
        assert page.findChild(QFrame, f"{prefix}_sample_image") is not None
    page.close()


def test_daily_page_control_names_match_the_design_ids() -> None:
    """控件名必须**逐一等于设计稿的 id**（`DESIGN_CONTROL_IDS`）—— 设计稿与页面的对号契约。

    这条是为了拦住"照设计稿抄名字时抄错/自己派生"：鸡舍那个文件框在设计稿里叫
    `coop_island_ref_image`，按前缀派生成 `coop_ref_image` 就会被这里抓住。
    """
    page = _page()

    missing = [name for name in DESIGN_CONTROL_IDS if page.findChild(QWidget, name) is None]
    assert missing == [], f"这些设计稿里的 id 在页面里找不到：{missing}"
    page.close()


def test_daily_page_defaults_match_the_design() -> None:
    """默认值/范围照设计稿：循环间隔 1–720 分钟、默认 30；三个复选框默认不勾。"""
    page = _page()

    assert isinstance(page.loop_interval_minutes, QSpinBox)
    assert (page.loop_interval_minutes.minimum(), page.loop_interval_minutes.maximum()) == LOOP_INTERVAL_RANGE
    assert page.loop_interval_minutes.value() == LOOP_INTERVAL_DEFAULT == 30
    assert page.daily_enabled.isChecked() is False
    assert page.auto_produce_least.isChecked() is False
    page.close()


def test_daily_page_keeps_the_designed_tooltips() -> None:
    """设计稿里写了 title 的地方要变成悬停提示（去掉"鼠标悬停提示："这类给开发者看的注解）。"""
    page = _page()

    assert "不生效" in page.daily_enabled.toolTip()
    assert "固定间隔" in page.loop_interval_minutes.toolTip()
    assert page.findChild(QComboBox, "coop_island").toolTip() == "选择鸡舍所在的岛屿编号"
    assert page.findChild(QComboBox, "land_island").toolTip() == "选择土地所在的岛屿编号"
    assert page.findChild(QComboBox, "aqua_island").toolTip() == "选择水产养殖所在的岛屿编号"
    assert "只能选择图片" in page.findChild(QLineEdit, "coop_island_ref_image").toolTip()
    assert "最少" in page.auto_produce_least.toolTip()
    page.close()


def test_daily_page_keeps_the_designed_labels_verbatim() -> None:
    """文案照抄设计稿（含设计稿里的措辞），改文案应当先改设计稿。"""
    from PySide6.QtWidgets import QLabel

    page = _page()
    text = "\n".join(label.text() for label in page.content.findChildren(QLabel))

    assert "位于那个岛屿上" in text
    assert "岛屿编号见下图" in text
    assert "截取鸡舍位置" in text and "截取土地位置" in text and "截取水产养殖位置" in text
    assert "示例图片：" in text
    assert "功能说明：" in text
    assert page.auto_produce_least.text() == "自动识别那个产物少造那个（只读）"
    page.close()


def test_produce_check_is_read_only_today_but_is_a_saveable_switch() -> None:
    """「自动识别那个产物少造那个」**当前只读**，但它是一个**要入库的开关**（用户 2026-09-21 明确）。

    - 只读 ≠ 禁用：看得见、点不动、tooltip 照常，但控件没被灰掉；
    - **程序里仍可 `setChecked()`** —— 第 2 批要按配置（`data-key=auto_produce_least`，默认 False）把值写进去；
    - 以后开放给用户＝把 `AUTO_PRODUCE_LEAST_READONLY` 改成 False（一行），
      本用例前半段会跟着变、后半段（"它是要入库的开关"）永远成立。
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    from luoluotool.gui.pages.daily import AUTO_PRODUCE_LEAST_READONLY

    page = _page()
    box = page.auto_produce_least
    page.show()
    _APP.processEvents()

    if AUTO_PRODUCE_LEAST_READONLY:
        before = box.isChecked()
        QTest.mouseClick(box, Qt.MouseButton.LeftButton, pos=QPoint(box.width() // 2, box.height() // 2))
        _APP.processEvents()
        assert box.isChecked() is before                      # 点击不改变状态
        assert box.isEnabled() is True                        # 但没有灰掉（不是"禁用"）
        assert box.focusPolicy() == Qt.FocusPolicy.NoFocus    # 键盘也拿不到焦点
        assert "只读" in box.text() and "只读" in box.toolTip()
        assert box in page.read_only_widgets()
    else:
        assert "只读" not in box.text()                       # 已开放给用户：不再带只读标记
        assert box not in page.read_only_widgets()

    box.setChecked(True)                                      # 无论如何，程序里都能设置它的值
    assert box.isChecked() is True
    page.close()


def test_daily_page_action_buttons_are_present_but_disabled_in_this_batch() -> None:
    """本批只做界面：要动游戏的按钮（选择图片 / 截取游戏画面）摆好但**禁用**，并说明原因。"""
    page = _page()

    buttons = [page.findChild(QPushButton, f"{prefix}_pick_image")
               for _t, prefix, _w, _r, _c in BUILDINGS]
    buttons += [page.findChild(QPushButton, capture_id)
                for _t, _p, _w, _r, capture_id in BUILDINGS]
    assert len(buttons) == 6
    for button in buttons:
        assert button.isEnabled() is False, button.objectName()
        assert "第 1 批" in button.toolTip()
    page.close()


def test_daily_page_does_not_touch_config_in_the_ui_only_batch() -> None:
    """守卫（本批的核心约定）：界面版**不写配置、不置脏标记**。

    第 2 批接配置时这条会被替换成"双向绑定"测试 —— 在那之前，任何"顺手写回配置"的改动
    都会让这条红，避免半成品悄悄改了用户的配置。
    """
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    before = config.to_dict()

    page.daily_enabled.setChecked(True)
    page.loop_interval_minutes.setValue(600)
    page.auto_produce_least.setChecked(True)
    for _title, prefix, _word, ref_id, _capture in BUILDINGS:
        page.findChild(QComboBox, f"{prefix}_island").setCurrentIndex(4)
        page.findChild(QLineEdit, ref_id).setText("D:/somewhere/shot.png")

    assert config.to_dict() == before          # 配置一个字段都没变
    assert changes == []                       # 也没有请求保存
    page.close()


def test_daily_page_set_config_does_not_raise_and_resets_controls() -> None:
    """主窗口加载/重载/恢复默认都会调 `set_config()`：本批只把控件刷回设计稿默认值。"""
    page = _page()
    page.daily_enabled.setChecked(True)
    page.loop_interval_minutes.setValue(600)
    page.findChild(QLineEdit, "coop_island_ref_image").setText("D:/x.png")

    config2 = AppConfig.default()
    config2.features.daily_tasks.enabled = True
    page.set_config(config2)

    assert page.daily_enabled.isChecked() is False          # 第 2 批才会读配置
    assert page.loop_interval_minutes.value() == LOOP_INTERVAL_DEFAULT
    assert page.findChild(QLineEdit, "coop_island_ref_image").text() == ""
    page.close()
