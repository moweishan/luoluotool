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
| `.two-col` | `QHBoxLayout` 两列 |

控件名直接用设计稿的 `id`（`objectName`），所以"设计稿里的 id ↔ 页面里的控件"可以逐条对号；
配置字段名（设计稿 `data-key`）留到第 2 批绑定，见文件末尾的对照注释。
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
# (标题, 控件名前缀, "截取…位置" 的中间词, 截取按钮的 id)
BUILDINGS: tuple[tuple[str, str, str, str], ...] = (
    ("鸡舍", "coop", "鸡舍", "capture_game_screen"),
    ("土地", "land", "土地", "land_capture_screen"),
    ("水产养殖", "aqua", "水产养殖", "aqua_capture_screen"),
)

IMAGE_PENDING_NOTE = "（图片待放入）"
BUTTON_PENDING_TIP = "第 1 批只做界面：这个按钮的功能还没接入（计划第 2/3 批实现）"
READONLY_MARK = "（只读）"                       # 只读项统一在文案后加这个标记
AUTO_PRODUCE_LEAST_TEXT = "自动识别那个产物少造那个"


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
        for title, prefix, label_word, capture_id in BUILDINGS:
            layout.addWidget(self._building_box(title, prefix, label_word, capture_id))
        return box

    def _building_box(self, title: str, prefix: str, label_word: str, capture_id: str) -> QGroupBox:
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
        island_row.addWidget(QLabel("位于那个岛屿上"))
        island_row.addWidget(island)
        island_row.addStretch(1)
        layout.addLayout(island_row)

        layout.addWidget(QLabel("岛屿编号见下图"))
        layout.addWidget(_image_placeholder(
            f"{prefix}_island_map", "岛屿编号参考图「临时占位」",
            tip="岛屿编号参考图，后续替换为真实截图",
        ))

        # 两列：左＝选择/截取参考图，右＝示例图片
        left = QVBoxLayout()
        left.addWidget(QLabel(f"截取{label_word}位置"))

        ref_edit = QLineEdit()
        ref_edit.setObjectName(f"{prefix}_ref_image")
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
        left.addLayout(ref_row)
        left.addStretch(1)

        right = QVBoxLayout()
        right.addWidget(QLabel("示例图片："))
        right.addWidget(_image_placeholder(
            f"{prefix}_sample_image", "示例图片「临时占位」",
            tip="示例图片，后续替换为真实示例",
        ))
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns)
        return box

    # ---------------------------------------------------------------- 产物制造
    def _produce_box(self) -> QGroupBox:
        box = QGroupBox("产物制造")
        box.setObjectName("group_produce")
        layout = QVBoxLayout(box)
        # 用户 2026-09-21 要求：这一项**只读**（由程序自动判断，不给用户改）。
        # 用事件过滤器"吃掉点击"而不是 setEnabled(False)：禁用的控件会灰掉（看着像"暂时不可用"），
        # 而只读只需要"看得见、点不动、tooltip 照常能看"。
        self.auto_produce_least = QCheckBox(f"{AUTO_PRODUCE_LEAST_TEXT}{READONLY_MARK}")
        self.auto_produce_least.setObjectName("auto_produce_least")
        self.auto_produce_least.setToolTip(
            "自动识别库存最少的产物并优先制造它（本项只读：由程序自动判断，不能手动修改）"
        )
        self.auto_produce_least.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 空格/方向键也改不动它
        self.auto_produce_least.installEventFilter(self)
        row = QHBoxLayout()
        row.addWidget(self.auto_produce_least)
        row.addStretch(1)
        layout.addLayout(row)
        return box

    # ---------------------------------------------------------------- 只读控件
    def eventFilter(self, watched, event) -> bool:        # noqa: N802 (Qt 命名)
        """拦住只读控件的鼠标交互（点击/双击/滚轮都不改它的值）。

        只读与"禁用"的区别：**外观保持正常**（不灰掉），tooltip 与悬停照常，只是点不动；
        程序里仍可 `setChecked()` 改它（第 2 批按配置/程序判断来设置）。
        """
        if watched is self.auto_produce_least and event.type() in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            return True
        return super().eventFilter(watched, event)

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
        for _title, prefix, _word, _capture in BUILDINGS:
            island = self.findChild(QComboBox, f"{prefix}_island")
            if island is not None:
                island.setCurrentIndex(0)
            ref_edit = self.findChild(QLineEdit, f"{prefix}_ref_image")
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
