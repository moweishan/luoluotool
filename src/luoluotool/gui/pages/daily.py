"""日常任务页：按用户设计稿（`日常任务设计稿.html`）重建的界面。

**本文件当前只做界面（第 1 批）**：分组、控件、文案、默认值、提示都与设计稿一一对应，
但**不读写配置、不含任何业务逻辑**（控件改动不会写回 `AppConfig`，也不会触发脏标记）；
需要动作的按钮（选择图片 / 截取游戏画面）已按设计稿摆好但**禁用**，等第 2/3 批接入。

设计稿 → Qt 的对应关系（推导规则，改设计稿时照此翻译）：

| 设计稿 | Qt |
|---|---|
| `<fieldset><legend>` | `QGroupBox`（可嵌套） |
| `<input type="checkbox">` | `QCheckBox` |
| `<select>` | `QComboBox` |
| `<input type="number" min/max/step/value>` | `QSpinBox`（单位写成 `setSuffix`） |
| `<input type="file">` | 只读 `QLineEdit` + `QPushButton`（Qt 没有文件输入框） |
| `<button>` | `QPushButton`（本批禁用） |
| `<small>` | 灰色小字 `QLabel` |
| `<img>` | 占位框（`QLabel` + 边框），真实图片后续放进 `assets/` |
| `title="…"` | `setToolTip(…)` |
| `.three-col` | `QHBoxLayout` 三列（建筑分组那一行；左列按内容宽度，两块图片区各分余量） |

控件名直接用设计稿的 `id`（`objectName`），所以"设计稿里的 id ↔ 页面里的控件"可以逐条对号；
配置字段名（设计稿 `data-key`）留到第 2 批绑定，见文件末尾的对照注释。

**与设计稿的同步记录（用户 2026-09-21）**：

① 每个建筑分组的最后一行是**三列同行** —— 「截取…位置」/ **「选择的图片」显示区**
（`{prefix}_selected_image`，给用户看**自己选的那张**长什么样）/「示例图片」；
设计稿 HTML 已同步补上这一列（`.two-col` → `.three-col`）。三块必须**顶边对齐、左右相邻**，
有几何测试钉住 —— 改设计稿时别把「选择的图片」删掉。
② 设计稿原稿的两处错别字已按用户口径改掉，**设计稿 HTML 同步改**：
「位于那个岛屿上」→「**所在岛屿编号**」、「自动识别那个产物少造那个」→
「**自动识别存量最少的产物并优先制造**」（旧文案由
`test_the_two_design_typos_are_not_reintroduced` 钉住不许回来）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from luoluotool.config.models import AppConfig
from luoluotool.gui.widgets import ScrollablePage

logger = logging.getLogger(__name__)

# 循环间隔范围与默认值（照设计稿 data-* 里的 min/max/value）
LOOP_INTERVAL_RANGE = (1, 720)
LOOP_INTERVAL_DEFAULT = 30
ISLAND_COUNT = 10                    # 岛屿编号下拉：1–10

# 三个生产建筑分组（设计稿里是三段重复结构，这里用一份定义避免抄三遍）
# (标题, 控件名前缀, "截取…位置" 的中间词, 参考图输入框 id, 截取按钮 id)
# **id 一律照抄设计稿**：鸡舍那个文件框在设计稿里叫 `coop_island_ref_image`（不是 coop_ref_image）
BUILDINGS: tuple[tuple[str, str, str, str, str], ...] = (
    ("鸡舍", "coop", "鸡舍", "coop_island_ref_image", "capture_game_screen"),
    ("土地", "land", "土地", "land_ref_image", "land_capture_screen"),
    ("水产养殖", "aqua", "水产养殖", "aqua_ref_image", "aqua_capture_screen"),
)

IMAGE_PENDING_NOTE = "（图片待放入）"
BUTTON_PENDING_TIP = "第 1 批只做界面：这个按钮的功能还没接入（计划第 2/3 批实现）"
READONLY_MARK = "（只读）"                       # 只读项统一在文案后加这个标记
# 设计稿原文是「自动识别那个产物少造那个」（句子不通），用户 2026-09-21 确认改成下面这句，
# **设计稿 HTML 已同步改**（`test_the_two_design_typos_are_not_reintroduced` 钉住旧文案不许回来）
AUTO_PRODUCE_LEAST_TEXT = "自动识别存量最少的产物并优先制造"
# 「自动识别存量最少的产物并优先制造」**暂定只读**（用户 2026-09-21 要求）：它仍然是一个**要入库的开关**
# （设计稿 data-key＝`auto_produce_least`，第 2 批按它绑配置、默认 False），只是暂时不给用户改。
# **以后开放给用户＝把这里改成 False**（文案上的「（只读）」标记与点击拦截一起生效）；
# 别直接删只读逻辑，留着开关才能一行放开。
AUTO_PRODUCE_LEAST_READONLY = True

# 设计稿里所有可交互控件的 id（控件名必须逐一对应，有测试钉住）—— 改设计稿时同步这张表
DESIGN_CONTROL_IDS: tuple[str, ...] = (
    "daily_enabled",
    "loop_interval_minutes",
    *(name for _t, prefix, _w, ref_id, cap_id in BUILDINGS
      for name in (f"{prefix}_island", ref_id, f"{prefix}_pick_image", cap_id)),
    "auto_produce_least",
)


class DailyPage(ScrollablePage):
    """日常任务页（界面版）：照设计稿搭出控件与布局。

    第 1 批**只画界面**：
    - `set_config()` 存在（主窗口加载/恢复默认时会调），但只把控件刷回设计稿默认值，
      **不读配置**；控件改动也**不写配置**、不触发 `on_changed`（有守卫测试钉住）。
    - 这样你能先看真实外观，第 2 批再把控件与配置双向绑定（并带 schema 迁移）。
    """

    def __init__(self, config: AppConfig, on_changed: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_changed = on_changed
        layout = QVBoxLayout(self.content)
        layout.setSpacing(10)

        layout.addWidget(self._general_box())
        layout.addWidget(self._buildings_box())
        layout.addWidget(self._produce_box())
        layout.addStretch(1)

    # ---------------------------------------------------------------- 总开关
    def _general_box(self) -> QGroupBox:
        box = QGroupBox("总开关与循环时长")
        box.setObjectName("group_general")
        layout = QVBoxLayout(box)

        self.daily_enabled = QCheckBox("启用日常任务")
        self.daily_enabled.setObjectName("daily_enabled")
        self.daily_enabled.setToolTip("总开关，关闭后本页所有配置都不生效")
        row = QHBoxLayout()
        row.addWidget(self.daily_enabled)
        row.addStretch(1)
        layout.addLayout(row)

        self.loop_interval_minutes = QSpinBox()
        self.loop_interval_minutes.setObjectName("loop_interval_minutes")
        self.loop_interval_minutes.setRange(*LOOP_INTERVAL_RANGE)
        self.loop_interval_minutes.setSingleStep(1)
        self.loop_interval_minutes.setValue(LOOP_INTERVAL_DEFAULT)
        self.loop_interval_minutes.setMaximumWidth(120)     # 设计稿里数字框是窄的（90px）
        self.loop_interval_minutes.setToolTip("仅在执行方式为「按固定间隔循环」时生效")
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("循环间隔（分钟）"))           # 单位跟设计稿一样写在标签里
        row2.addWidget(self.loop_interval_minutes)
        row2.addStretch(1)
        layout.addLayout(row2)
        return box

    # ------------------------------------------------- 关键建筑位置与识别图片
    def _buildings_box(self) -> QGroupBox:
        box = QGroupBox("关键建筑位置以及图像识别所需图片")
        box.setObjectName("group_buildings")
        layout = QVBoxLayout(box)
        layout.addWidget(_hint("功能说明：自动寻找生产建筑时由于每个人的建筑位置都不一样，所以需要手动配置"))
        for title, prefix, label_word, ref_id, capture_id in BUILDINGS:
            layout.addWidget(self._building_box(title, prefix, label_word, ref_id, capture_id))
        return box

    def _building_box(self, title: str, prefix: str, label_word: str,
                      ref_id: str, capture_id: str) -> QGroupBox:
        """一个生产建筑分组（鸡舍 / 土地 / 水产养殖共用同一套结构）。"""
        box = QGroupBox(title)
        box.setObjectName(f"group_{prefix}")
        layout = QVBoxLayout(box)

        island = QComboBox()
        island.setObjectName(f"{prefix}_island")
        island.addItems([str(number) for number in range(1, ISLAND_COUNT + 1)])
        island.setFixedWidth(80)                      # 设计稿把下拉收窄到只放得下数字
        island.setToolTip(f"选择{title}所在的岛屿编号")
        island_row = QHBoxLayout()
        island_row.addWidget(QLabel("所在岛屿编号"))
        island_row.addWidget(island)
        island_row.addStretch(1)
        layout.addLayout(island_row)

        layout.addWidget(QLabel("岛屿编号见下图"))
        layout.addWidget(_image_placeholder(
            f"{prefix}_island_map", "岛屿编号参考图「临时占位」",
            tip="岛屿编号参考图，后续替换为真实截图",
        ))

        # 三列**同一行**（用户 2026-09-21 要求）：截取位置 / 选择的图片 / 示例图片
        #   左列＝「截取…位置」+ 参考图输入框 + 选择图片… + 截取游戏画面
        #   中列＝「选择的图片」显示区（用户新加：给用户看**自己选的那张**长什么样）
        #   右列＝设计稿原有的「示例图片」
        capture_col = QVBoxLayout()
        capture_col.addWidget(QLabel(f"截取{label_word}位置"))

        ref_edit = QLineEdit()
        ref_edit.setObjectName(ref_id)                 # 照抄设计稿的 id（鸡舍那个带 island 字样）
        ref_edit.setReadOnly(True)
        ref_edit.setPlaceholderText("尚未选择图片")
        ref_edit.setMinimumWidth(180)
        ref_edit.setToolTip(f"只能选择图片文件（{label_word}所在岛屿参考截图，本批只做界面）")

        pick_button = QPushButton("选择图片…")
        pick_button.setObjectName(f"{prefix}_pick_image")
        pick_button.setEnabled(False)                  # 第 1 批：按钮先摆好，功能未接入
        pick_button.setToolTip(BUTTON_PENDING_TIP)

        capture_button = QPushButton("截取游戏画面")
        capture_button.setObjectName(capture_id)
        capture_button.setEnabled(False)
        capture_button.setToolTip(BUTTON_PENDING_TIP)

        ref_row = QHBoxLayout()
        ref_row.addWidget(ref_edit, 1)
        ref_row.addWidget(pick_button)
        ref_row.addWidget(capture_button)
        ref_row.addStretch(1)
        capture_col.addLayout(ref_row)
        capture_col.addStretch(1)

        selected_col = QVBoxLayout()
        selected_col.addWidget(QLabel("选择的图片："))
        selected_col.addWidget(_image_placeholder(
            f"{prefix}_selected_image", "选择的图片「临时占位」",
            tip="选好图片后在这里显示所选图片（第 2 批接入）",
        ))
        selected_col.addStretch(1)

        sample_col = QVBoxLayout()
        sample_col.addWidget(QLabel("示例图片："))
        sample_col.addWidget(_image_placeholder(
            f"{prefix}_sample_image", "示例图片「临时占位」",
            tip="示例图片，后续替换为真实示例",
        ))
        sample_col.addStretch(1)

        columns = QHBoxLayout()
        columns.addLayout(capture_col, 0)              # 按内容宽度（输入框 + 两个按钮）
        columns.addLayout(selected_col, 1)             # 多出来的宽度给两块图片区
        columns.addLayout(sample_col, 1)
        layout.addLayout(columns)
        return box

    # ---------------------------------------------------------------- 产物制造
    def _produce_box(self) -> QGroupBox:
        box = QGroupBox("产物制造")
        box.setObjectName("group_produce")
        layout = QVBoxLayout(box)
        # 用户 2026-09-21 要求：这一项**暂时只读**（值仍要入库，以后开放给用户 —— 见
        # `AUTO_PRODUCE_LEAST_READONLY` 的说明：把那个常量改成 False 就恢复可编辑）。
        # 只读用"吃掉鼠标点击"而不是 setEnabled(False)：禁用会灰掉（看着像"暂时不可用"），
        # 只读要的是"看得见、点不动、tooltip 照常"。
        mark = READONLY_MARK if AUTO_PRODUCE_LEAST_READONLY else ""
        self.auto_produce_least = QCheckBox(f"{AUTO_PRODUCE_LEAST_TEXT}{mark}")
        self.auto_produce_least.setObjectName("auto_produce_least")
        self.auto_produce_least.setToolTip(
            "自动识别库存最少的产物并优先制造它"
            + ("（本项只读：暂由程序自动判断，不能手动修改）" if AUTO_PRODUCE_LEAST_READONLY else "")
        )
        self._read_only_widgets: set[QWidget] = set()
        if AUTO_PRODUCE_LEAST_READONLY:
            self._make_read_only(self.auto_produce_least)
        row = QHBoxLayout()
        row.addWidget(self.auto_produce_least)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    # ---------------------------------------------------------------- 只读控件
    def _make_read_only(self, widget: QWidget) -> None:
        """把一个控件变成"只读"：看得见、点不动、tooltip 照常，但**不灰掉**。

        只读 ≠ 禁用：`setEnabled(False)` 会把控件灰掉（看着像"暂时不可用"），而只读要的是
        "能看清、但不给改"。这里用事件过滤器吃掉鼠标交互，并让键盘也拿不到焦点；
        程序里仍可 `setChecked()` —— 第 2 批要按配置/程序判断把值写进去。
        """
        widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        widget.installEventFilter(self)
        self._read_only_widgets.add(widget)

    def eventFilter(self, watched, event) -> bool:        # noqa: N802 (Qt 命名)
        """拦住只读控件的鼠标交互（点击/双击都不会改它的值）。"""
        if watched in self._read_only_widgets and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            return True
        return super().eventFilter(watched, event)

    def read_only_widgets(self) -> tuple[QWidget, ...]:
        """当前被设为只读的控件（测试与文档用；以后开放某项就把它的 `_make_read_only` 去掉）。"""
        return tuple(sorted(self._read_only_widgets, key=lambda item: item.objectName()))

    # ---------------------------------------------------------------- 配置绑定
    def set_config(self, config: AppConfig) -> None:
        """重新绑定配置（主窗口在加载/重载/恢复默认时调用）。

        **第 1 批：只把控件刷回设计稿默认值，不读配置**；第 2 批改成真正的双向绑定。
        """
        self._config = config
        logger.debug("日常任务页（界面版）收到配置刷新：本批不读取配置内容")
        self.daily_enabled.setChecked(False)
        self.loop_interval_minutes.setValue(LOOP_INTERVAL_DEFAULT)
        self.auto_produce_least.setChecked(False)
        for _title, prefix, _word, ref_id, _capture in BUILDINGS:
            island = self.findChild(QComboBox, f"{prefix}_island")
            if island is not None:
                island.setCurrentIndex(0)
            ref_edit = self.findChild(QLineEdit, ref_id)
            if ref_edit is not None:
                ref_edit.clear()


# ------------------------------------------------------------------ 小工具


def _hint(text: str) -> QLabel:
    """设计稿 `<small>` 对应的灰色小字说明。"""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #666;")
    return label


def _image_placeholder(object_name: str, text: str, *, tip: str = "") -> QWidget:
    """设计稿 `<img>` 占位：带虚线边框的灰底方框，写清这里以后要放什么图。

    真实图片（岛屿编号参考图 / 示例图）后续放进 `assets/` 再换成本地文件加载；
    本批先占位，免得界面里出现一个"空的洞"而看不出缺什么。
    """
    frame = QFrame()
    frame.setObjectName(object_name)
    frame.setFrameShape(QFrame.Shape.StyledPanel)
    frame.setStyleSheet("background: #f2f2f2; border: 1px dashed #b8b8b8;")
    frame.setMinimumHeight(84)
    frame.setMinimumWidth(160)
    if tip:
        frame.setToolTip(tip)
    label = QLabel(text)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    label.setStyleSheet("color: #888; border: none;")
    inner = QVBoxLayout(frame)
    inner.addWidget(label)
    return frame
