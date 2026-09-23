"""日常任务页测试（第 2 批）：控件齐全、与设计稿一致，并且**真的双向绑定配置**。

设计稿：`D:/AAAAA/workspaceCursor/杂项/日常任务设计稿.html`（用户 2026-09-21 提供）。
第 1 批曾是"只做界面、不碰配置"（有守卫测试钉住）；第 2 批（2026-09-22）用户确认后
改成双向绑定：控件改动写进 `AppConfig` 并置脏，`set_config()` 只负责显示。
选图 / 截取游戏画面 / 放大预览这些**碰文件与线程的动作**在 `tests/test_gui_daily_media.py`
（页面只发信号，见 `gui/pages/daily.py` 的模块说明）。
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

from luoluotool.config.models import (
    LOOP_INTERVAL_MINUTES_RANGE,
    AppConfig,
)
from luoluotool.gui.pages.daily import (
    BUILDINGS,
    DESIGN_CONTROL_IDS,
    DailyPage,
)
from luoluotool.gui.widgets import PAGE_SIZE_HINT, ScrollablePage

_APP = QApplication.instance() or QApplication([])


def _page(config: AppConfig | None = None, changes: list[str] | None = None) -> DailyPage:
    changes = changes if changes is not None else []
    return DailyPage(config or AppConfig.default(), lambda: changes.append("dirty"))


def _hover(widget, pos) -> None:
    """给控件发一个真实的鼠标移动事件（offscreen 下 `QTest.mouseMove` 不一定投递，这样最稳）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    event = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


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
        assert page.findChild(QFrame, f"{prefix}_selected_image") is not None
        assert page.findChild(QFrame, f"{prefix}_sample_image") is not None
    page.close()


def test_selected_image_area_sits_in_one_row_between_capture_and_sample() -> None:
    """三个建筑各有一块「选择的图片」显示区，位置：截取按钮右边、示例图片左边、**同一行**。

    用户 2026-09-21 要求：加一块显示所选图片的区域，并让「截取位置 / 选择的图片 / 示例图片」
    三块排在一行上。这里用**真实几何**校验（offscreen 下 Qt 照常算布局）而不是只看控件存在——
    "同行"这件事只有几何能证明。
    """
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QLabel

    def rect_of(widget) -> QRect:
        return QRect(widget.mapTo(page, QPoint(0, 0)), widget.size())

    page = _page()
    page.show()
    _APP.processEvents()

    assert any("选择的图片" in label.text() for label in page.findChildren(QLabel))

    for _title, prefix, _word, _ref_id, capture_id in BUILDINGS:
        capture = rect_of(page.findChild(QPushButton, capture_id))
        selected = rect_of(page.findChild(QFrame, f"{prefix}_selected_image"))
        sample = rect_of(page.findChild(QFrame, f"{prefix}_sample_image"))

        assert selected.left() > capture.right(), prefix          # 在「截取游戏画面」右边
        assert selected.right() <= sample.left(), prefix          # 在「示例图片」左边
        assert abs(selected.top() - sample.top()) <= 4, prefix    # 与示例图片同一行
        assert abs(selected.top() - capture.top()) <= 12, prefix  # 与截取按钮同一行（按钮在行内居中）
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


def test_daily_page_loop_interval_range_matches_the_design() -> None:
    """循环间隔范围照设计稿 1–720 分钟；**值来自配置**（配置里存秒，默认 3600 秒 = 60 分钟）。"""
    page = _page()

    assert isinstance(page.loop_interval_minutes, QSpinBox)
    assert LOOP_INTERVAL_MINUTES_RANGE == (1, 720)
    assert (
        page.loop_interval_minutes.minimum(), page.loop_interval_minutes.maximum()
    ) == LOOP_INTERVAL_MINUTES_RANGE
    assert page.loop_interval_minutes.value() == 60          # AppConfig.default() 的 3600 秒
    assert page.daily_enabled.isChecked() is False
    assert page.loop_enabled.isChecked() is False            # 循环默认关（runner 只看这个标志）
    assert page.auto_produce_least.isChecked() is False
    page.close()


def test_daily_page_loop_switch_writes_loop_enabled() -> None:
    """「按固定间隔循环」开关真的绑 `loop.enabled`（第五轮评审 P2-2）。

    没有这个开关时，"循环间隔"是个**失效控件**：runner 不循环的条件正是 `not loop.enabled`，
    而全仓没有任何界面代码写它 —— 用户把间隔改成 30 分钟，什么都不发生。
    """
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)

    page.loop_enabled.setChecked(True)
    assert config.features.daily_tasks.loop.enabled is True
    assert changes == ["dirty"]

    page.loop_enabled.setChecked(False)
    assert config.features.daily_tasks.loop.enabled is False
    assert page.loop_interval_minutes.toolTip().startswith("仅在勾选上面的「按固定间隔循环」时生效")
    page.close()


def test_daily_page_loads_and_repopulates_the_loop_switch() -> None:
    """装载配置：循环开关跟着走，且不置脏（`_loading` 保护）。"""
    config = AppConfig.default()
    config.features.daily_tasks.loop.enabled = True
    changes: list[str] = []
    page = _page(config, changes)
    assert page.loop_enabled.isChecked() is True
    assert changes == []

    other = AppConfig.default()
    page.set_config(other)
    assert page.loop_enabled.isChecked() is False
    assert changes == []
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

    assert "所在岛屿编号" in text
    assert "岛屿编号见下图" in text
    assert "截取鸡舍位置" in text and "截取土地位置" in text and "截取水产养殖位置" in text
    assert "示例图片：" in text
    assert "选择的图片：" in text          # 用户 2026-09-21 新增的图片显示区（与「示例图片：」同一格式）
    assert "功能说明：" in text
    assert page.auto_produce_least.text() == "自动识别存量最少的产物并优先制造（只读）"
    page.close()


def test_the_two_design_typos_are_not_reintroduced() -> None:
    """设计稿里那两处错别字（用户 2026-09-21 已确认改掉）不许再出现。

    原稿：「位于那个岛屿上」（应为"哪个"）、「自动识别那个产物少造那个」（句子不通）。
    改后口径是用户选的：**「所在岛屿编号」** 与 **「自动识别存量最少的产物并优先制造」**，
    设计稿 HTML 与代码同步改；这条守卫让"谁把旧文案抄回来"当场变红。
    """
    from PySide6.QtWidgets import QLabel

    page = _page()
    text = "\n".join(label.text() for label in page.content.findChildren(QLabel))
    text += page.auto_produce_least.text() + "\n" + page.auto_produce_least.toolTip()

    assert "位于那个岛屿上" not in text
    assert "自动识别那个产物少造那个" not in text
    page.close()


def test_produce_check_is_read_only_today_but_is_a_saveable_switch() -> None:
    """「自动识别存量最少的产物并优先制造」**当前只读**，但它是一个**要入库的开关**（用户 2026-09-21 明确）。

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


def test_daily_page_action_buttons_are_enabled_and_wired() -> None:
    """第 2 批起按钮真的能用（不再禁用），提示里说清它做什么。"""
    page = _page()

    for _title, prefix, _word, _ref_id, capture_id in BUILDINGS:
        pick = page.findChild(QPushButton, f"{prefix}_pick_image")
        capture = page.findChild(QPushButton, capture_id)
        assert pick.isEnabled() is True, prefix
        assert capture.isEnabled() is True, capture_id
        assert "图片" in pick.toolTip()
        assert "框选" in capture.toolTip()
    page.close()


def test_daily_page_emits_media_requests_with_the_building_prefix() -> None:
    """页面本身不碰文件（分层），只发信号；主窗口接信号去选图/截图。"""
    page = _page()
    picked: list[str] = []
    captured: list[str] = []
    page.pick_image_requested.connect(picked.append)
    page.capture_requested.connect(captured.append)

    page.findChild(QPushButton, "land_pick_image").click()
    page.findChild(QPushButton, "aqua_capture_screen").click()

    assert picked == ["land"]
    assert captured == ["aqua"]
    page.close()


def test_daily_page_writes_widget_changes_into_config_and_marks_dirty() -> None:
    """双向绑定（第 2 批）：控件改动立刻写进配置并置脏 —— 取代旧的"界面不许碰配置"守卫。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)

    page.daily_enabled.setChecked(True)
    assert config.features.daily_tasks.enabled is True
    assert changes == ["dirty"]

    page.findChild(QComboBox, "coop_island").setCurrentIndex(6)      # 索引 6 → 7 号岛
    assert config.features.daily_tasks.coop_island == 7
    page.findChild(QComboBox, "aqua_island").setCurrentIndex(9)
    assert config.features.daily_tasks.aqua_island == 10

    page.loop_interval_minutes.setValue(45)
    assert config.features.daily_tasks.loop.interval_seconds == 45 * 60

    page.auto_produce_least.setChecked(True)       # 界面点不动，但程序里写进去必须落到配置
    assert config.features.daily_tasks.auto_produce_least is True
    page.close()


def test_daily_page_loads_config_without_rewriting_it() -> None:
    """装载配置：控件跟着配置走，但**不置脏、不回写**（秒↔分钟的取整绝不改用户的值）。"""
    config = AppConfig.default()
    daily = config.features.daily_tasks
    daily.enabled = True
    daily.loop.interval_seconds = 3600
    daily.coop_island = 9
    daily.land_island = 3
    daily.aqua_island = 5
    daily.coop_island_ref_image = ["assets/templates/鸡舍_岛屿9.png"]
    daily.auto_produce_least = True
    changes: list[str] = []
    page = _page(config, changes)
    before = config.to_dict()

    assert page.daily_enabled.isChecked() is True
    assert page.loop_interval_minutes.value() == 60                  # 3600 秒 → 60 分钟
    assert page.findChild(QComboBox, "coop_island").currentText() == "9"
    assert page.findChild(QComboBox, "aqua_island").currentText() == "5"
    assert page.findChild(QLineEdit, "coop_island_ref_image").text() == "assets/templates/鸡舍_岛屿9.png"
    assert page.auto_produce_least.isChecked() is True
    assert changes == []                                             # 装载不算用户改动
    assert config.to_dict() == before
    page.close()


def test_daily_page_shows_odd_second_values_at_the_nearest_minute_without_writing_back() -> None:
    """配置里的秒数不是整分钟时：界面按四舍五入显示，**只有用户动那个框才写回**。"""
    config = AppConfig.default()
    config.features.daily_tasks.loop.interval_seconds = 90           # 1.5 分钟
    page = _page(config, [])
    assert page.loop_interval_minutes.value() == 2
    assert config.features.daily_tasks.loop.interval_seconds == 90   # 没被改掉
    page.loop_interval_minutes.setValue(3)                           # 用户真的动了它
    assert config.features.daily_tasks.loop.interval_seconds == 180
    page.close()


def test_daily_page_set_config_repopulates_widgets_without_marking_dirty() -> None:
    """主窗口加载/重载/恢复默认都会调 `set_config()`：控件跟着走，且不把自己当"用户改动"。"""
    config = AppConfig.default()
    changes: list[str] = []
    page = _page(config, changes)
    page.daily_enabled.setChecked(True)
    changes.clear()

    other = AppConfig.default()
    other.features.daily_tasks.loop.interval_seconds = 120
    other.features.daily_tasks.aqua_island = 4
    page.set_config(other)

    assert page.daily_enabled.isChecked() is False
    assert page.loop_interval_minutes.value() == 2
    assert page.findChild(QComboBox, "aqua_island").currentText() == "4"
    assert changes == []
    page.close()


def test_selected_image_area_previews_the_picture_and_asks_for_an_enlarged_view() -> None:
    """「选择的图片」显示区：设置图片＝显示，双击＝请求放大（具体弹窗由主窗口做）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    from luoluotool.gui.widgets import ImagePreview

    page = _page()
    preview = page.findChild(ImagePreview, "coop_selected_image")
    assert preview is not None and preview.image() is None
    assert preview.empty_text() == "尚未选择图片"

    image = QImage(6, 4, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    path = "assets/anchors/鸡舍_岛屿1.png"
    page.set_reference_images("coop", [path], [image])
    assert page.findChild(QLineEdit, "coop_island_ref_image").text() == path   # 单张＝显示完整路径
    assert preview.image() is not None and preview.image().size() == image.size()

    requested: list[tuple[str, int]] = []
    page.preview_requested.connect(lambda prefix, index: requested.append((prefix, index)))
    page.show()
    _APP.processEvents()
    QTest.mouseDClick(preview, Qt.MouseButton.LeftButton, pos=preview.rect().center())
    assert requested == [("coop", 0)]                                 # 大图＝放大当前选中那张

    page.set_reference_images("coop", [], [])                         # 清空（例如配置被换掉）
    assert page.findChild(QLineEdit, "coop_island_ref_image").text() == ""
    assert preview.image() is None
    page.close()


def test_daily_page_shows_a_summary_and_thumbnails_for_multiple_images() -> None:
    """多选（用户 2026-09-22 要求）：输入框显示"共 N 张：文件名"、缩略图条每张一格、大图显示选中的那张。"""
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt

    page = _page()
    paths = ["assets/templates/鸡舍_1.png", "assets/templates/鸡舍_2.png",
             "assets/anchors/鸡舍_岛屿1_x.png"]
    images = []
    for index in range(3):
        image = QImage(6, 4, QImage.Format.Format_RGB32)
        image.fill(0x100000 * index)
        images.append(image)

    page.set_reference_images("coop", paths, images)

    edit = page.findChild(QLineEdit, "coop_island_ref_image")
    assert edit.text() == "共 3 张：鸡舍_1.png、鸡舍_2.png、鸡舍_岛屿1_x.png"
    assert "鸡舍_1.png" in edit.toolTip() and "3 张" in edit.toolTip()   # 悬停里给完整路径
    strip = page.thumbnail_strip("coop")
    assert strip is not None and strip.count() == 3
    assert page.reference_images("coop") == paths
    assert page.selected_index("coop") == 0
    assert page.preview_widget("coop").image() is images[0]             # 大图＝第 1 张

    page.show()
    _APP.processEvents()
    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.item_rect(2).center())
    assert page.selected_index("coop") == 2
    assert page.preview_widget("coop").image() is images[2]             # 点缩略图＝换大图

    activated: list[tuple[str, int]] = []
    page.preview_requested.connect(lambda prefix, index: activated.append((prefix, index)))
    QTest.mouseDClick(strip, Qt.MouseButton.LeftButton, pos=strip.item_rect(1).center())
    assert activated == [("coop", 1)]                                   # 双击＝放大那一张
    page.close()


def test_daily_page_emits_remove_and_clear_requests() -> None:
    """右键菜单的两条动作由页面发信号（写配置交给控制器）。"""
    from PySide6.QtGui import QImage

    page = _page()
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    page.set_reference_images("aqua", ["a.png", "b.png"], [image, image])
    removed: list[tuple[str, int]] = []
    cleared: list[str] = []
    page.remove_image_requested.connect(lambda prefix, index: removed.append((prefix, index)))
    page.clear_images_requested.connect(cleared.append)

    page.thumbnail_strip("aqua").remove_requested.emit(1)
    page.thumbnail_strip("aqua").clear_requested.emit()

    assert removed == [("aqua", 1)]
    assert cleared == ["aqua"]
    page.close()


def test_daily_page_thumbnail_strip_explains_itself_when_empty() -> None:
    """还没选图时缩略图条显示一句提示（可多选、怎么操作），不是一块空白。"""
    page = _page()
    strip = page.thumbnail_strip("land")

    assert strip is not None and strip.count() == 0
    assert "可一次选多张" in strip.empty_text()
    assert "右键" in strip.toolTip()
    page.close()


def test_daily_page_thumbnail_has_a_visible_close_badge() -> None:
    """可见的移除入口（用户 2026-09-22 选定）：每张缩略图右上角有「×」角标，点它删这张。

    角标必须真的画在图内（不是画到框外）、**点角标只删那张、不改当前选中项**，
    点缩略图中间仍然是"看大图"（两条路径不许互相吃掉）。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    page = _page()
    image = QImage(6, 4, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    page.set_reference_images("coop", ["a.png", "b.png", "c.png"], [image, image, image])
    strip = page.thumbnail_strip("coop")
    removed: list[tuple[str, int]] = []
    page.remove_image_requested.connect(lambda prefix, index: removed.append((prefix, index)))

    for index in range(3):                                   # 每一格都得有角标
        badge = strip.close_badge_rect(index)
        assert strip.item_rect(index).contains(badge), index
    assert strip.item_rect(0).width() > strip.close_badge_rect(0).width()

    page.show()
    _APP.processEvents()
    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.item_rect(2).center())
    assert page.selected_index("coop") == 2                  # 先选第 3 张
    removed.clear()

    QTest.mouseClick(strip, Qt.MouseButton.LeftButton, pos=strip.close_badge_rect(0).center())

    assert removed == [("coop", 0)]                          # 点第 1 张的 × → 只删第 1 张
    assert page.selected_index("coop") == 2                  # 选中项没被角标点掉

    _hover(strip, strip.close_badge_rect(1).center())        # 悬停角标要提示这是删哪张
    assert "移除第 2 张" in strip.toolTip()
    _hover(strip, strip.item_rect(1).center())
    assert "移除第" not in strip.toolTip()                   # 移开就恢复原提示
    page.close()


def test_daily_page_has_a_visible_clear_button_next_to_the_strip() -> None:
    """缩略图条旁边有可见的「清空全部」按钮（右键菜单之外的第二条路）：没图时禁用，有图时可用。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest

    page = _page()
    strip = page.thumbnail_strip("land")
    button = page.findChild(QPushButton, "land_clear_images")
    assert button is not None and button.text() == "清空全部"
    assert button.isEnabled() is False                       # 还没选图
    assert "没有可清空" in button.toolTip()

    image = QImage(4, 4, QImage.Format.Format_RGB32)
    page.set_reference_images("land", ["a.png", "b.png"], [image, image])
    assert button.isEnabled() is True
    cleared: list[str] = []
    page.clear_images_requested.connect(cleared.append)

    page.show()
    _APP.processEvents()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert cleared == ["land"]
    page.set_reference_images("land", [], [])
    assert button.isEnabled() is False                       # 清空之后又回到禁用
    page.close()


def test_daily_page_clear_button_sits_beside_the_thumbnail_strip() -> None:
    """「清空全部」按钮必须与缩略图条**在同一行、且在它右边**（不是另起一行藏起来）。"""
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QImage

    def rect_of(widget) -> QRect:
        return QRect(widget.mapTo(page, QPoint(0, 0)), widget.size())

    page = _page()
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    page.set_reference_images("aqua", ["a.png"], [image])
    page.show()
    _APP.processEvents()

    strip = rect_of(page.thumbnail_strip("aqua"))
    button = rect_of(page.findChild(QPushButton, "aqua_clear_images"))

    assert button.left() >= strip.right()                                  # 紧跟在条的右边
    assert abs(button.center().y() - strip.center().y()) <= strip.height()
    page.close()
