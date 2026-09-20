"""框选截图生成模板：把游戏窗口截图放大显示，鼠标拖框选区 → 存成模板 PNG。

为什么需要它：手工用截图工具裁剪模板很容易裁到"会变化的区域"或裁偏；
这里直接拿工具自己截的图、在同一个坐标系里框选，保存的就是识别要用的那部分像素。

坐标说明：选区对外暴露为**图像像素坐标**，而图像就是游戏窗口的客户区截图，
因此选区左上角就是客户区坐标（与点击/滑动/识别结果同一坐标系）。

拆分说明（2026-09-21，原文件 627 行超 600 硬线）：**交互视图 `CropView` 已移到
`gui/dialogs/crop_view.py`**，本模块只保留对话框外壳（提示、按钮、保存），
并把 `CropView` 与相关常量**再导出**，`from ...crop_dialog import CropView` 等旧写法继续可用。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.template_match import RegionQuality, assess_region_quality
from luoluotool.automation.vision import save_image
from luoluotool.gui.dialogs.crop_view import (      # 再导出：旧导入路径不变
    BACKGROUND_COLOR,
    BUBBLE_COLOR,
    BUBBLE_PADDING_PX,
    DIM_COLOR,
    HANDLE_CURSORS,
    HANDLE_SIZE_PX,
    MIN_SELECTION_SIZE,
    SELECTION_COLOR,
    CropView,
    to_qimage,
)

logger = logging.getLogger(__name__)

NEAR_FULL_RATIO = 0.95          # 选区面积 ≥ 整屏的该比例时提示"几乎等于整屏"


class TemplateCropDialog(QDialog):
    """框选截图生成模板：拖拽选区 → 「保存为模板」写入 save_dir。"""

    def __init__(
        self,
        image_bgr: np.ndarray,
        window_size: tuple[int, int],
        save_dir: Path | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("框选截图生成模板")
        self._image = image_bgr
        self._save_dir = Path(save_dir) if save_dir is not None else None
        self.saved_path: Path | None = None

        width, height = int(window_size[0]), int(window_size[1])
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"在下面的截图里按住左键拖出要识别的区域（截图＝游戏客户区 {width}x{height}）。\n"
            "**改选区**：拖内部＝移动、拖四角/四边小方块＝改大小（按住 **Alt** 是以中心对称缩放）、"
            "**空格/右键拖拽**＝移动、在选区外重拖＝重新框选、**Esc**＝撤销这次拖拽（没拖拽时清空）、"
            "**双击**＝清空重来。\n"
            "**键盘微调**：方向键移动 1 像素、Shift+方向键 10 像素、Ctrl+方向键把那条边向外 1 像素、"
            "Ctrl+Shift+方向键向内 1 像素。\n"
            "**看细节**：滚轮＝以鼠标为中心缩放、中键拖拽 或 空格+拖拽＝平移画面、"
            "下面两个按钮＝「适配窗口」/「1:1 显示」；鼠标旁的放大镜显示当前像素与坐标。\n"
            "建议框选画面中**不会变化**的局部（数字、倒计时等变动区域会让匹配不稳定）。"
        ))
        self.view = CropView(image_bgr)
        self.crop_view = self.view            # 语义化别名
        self.view.setFocus()                  # 打开弹窗就把键盘焦点给框选图（方向键立刻可用）
        self.info_label = QLabel("尚未选择区域")
        self.info_label.setWordWrap(True)
        self.view.selection_changed.connect(self._refresh_info)
        self.view.view_changed.connect(self._refresh_info)

        zoom_row = QHBoxLayout()
        self.zoom_fit_button = QPushButton("适配窗口")
        self.zoom_fit_button.setToolTip("整张截图缩放到窗口大小（回到初始视图）")
        self.zoom_fit_button.clicked.connect(self.view.zoom_to_fit)
        self.zoom_actual_button = QPushButton("1:1 显示")
        self.zoom_actual_button.setToolTip("1 个图像像素 = 1 个屏幕像素（精确定位用）")
        self.zoom_actual_button.clicked.connect(self.view.zoom_to_actual)
        self.zoom_hint_label = QLabel("滚轮＝缩放（以鼠标为中心）｜中键拖拽 或 空格+拖拽＝平移画面")
        self.zoom_hint_label.setWordWrap(True)
        zoom_row.addWidget(self.zoom_fit_button)
        zoom_row.addWidget(self.zoom_actual_button)
        zoom_row.addWidget(self.zoom_hint_label, 1)

        layout.addWidget(self.view, 1)
        layout.addLayout(zoom_row)
        layout.addWidget(self.info_label)

        buttons = QDialogButtonBox()
        self.save_button = QPushButton("保存为模板")
        self.cancel_button = QPushButton("取消")
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        # 保存按钮必须走"裁剪 + 落盘"，不能直接 accept()：否则对话框一关就什么都没存
        # （历史缺陷：这里原是 connect(self.accept)，导致「保存为模板」实际只关窗口，
        #   主窗口随后报"未选择有效区域"—— 见 tests/test_gui_crop.py 的按钮回归测试）
        self.save_button.clicked.connect(self._on_save_clicked)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.resize(900, 640)

    # ------------------------------------------------------------- 选区
    def selection(self) -> tuple[int, int, int, int] | None:
        return self.view.selection_in_image()

    def set_selection_in_image(self, x: int, y: int, width: int, height: int) -> None:
        self.view.set_selection_in_image(x, y, width, height)

    def selection_quality(self) -> RegionQuality | None:
        """当前选区的可辨识度评估（没有有效选区时返回 None）。

        用户 2026-09-21 要求（D2 可辨识度提示 / C3 保存前质量检查）：纯色或几乎没有明暗变化的
        区域当模板，在真实画面上会刷出一堆"匹配度 1.000"的假坐标，必须当场告诉用户。
        """
        selection = self.selection()
        if selection is None:
            return None
        x, y, width, height = selection
        return assess_region_quality(self._image[y : y + height, x : x + width])

    def selection_text(self) -> str:
        """人读描述：尺寸 + 客户区左上角坐标 + 可辨识度（未选区时给出提示）。"""
        selection = self.selection()
        if selection is None:
            return "尚未选择区域（按住左键拖拽框选）"
        x, y, width, height = selection
        text = f"选区 {width}x{height}，客户区左上 ({x}, {y})，中心 ({x + width // 2}, {y + height // 2})"
        quality = self.selection_quality()
        if quality is not None:
            text += f"　｜　{quality.message}"
        image_w, image_h = self.view.image_size
        if width * height >= image_w * image_h * NEAR_FULL_RATIO:
            text += "　⚠ 选区几乎等于整屏，这样的模板基本没有辨识度（可能框错了）"
        return text

    def _refresh_info(self) -> None:
        """信息行 = 选区描述 + 视图状态（缩放倍率 + 鼠标处客户区坐标）。"""
        self.info_label.setText(f"{self.selection_text()}　｜　{self.view_status_text()}")

    def view_status_text(self) -> str:
        """视图状态：缩放倍率与鼠标处的客户区坐标（鼠标还没进图时只给缩放）。"""
        zoom = f"缩放 {self.view.zoom_percent()}%"
        cursor = self.view.cursor_position()
        if cursor is None:
            return f"{zoom}　｜　鼠标：移入截图后显示坐标"
        return f"{zoom}　｜　鼠标客户区 ({cursor.x()}, {cursor.y()})"

    # ------------------------------------------------------------- 保存
    def _on_save_clicked(self) -> None:
        """「保存为模板」：只把**手动框选的那块区域**裁剪存盘，成功后才关闭对话框。

        没有有效选区（没拖、或框得太小）时不写文件、也不关闭，只在提示行说明原因，
        让用户继续框 —— 避免"点了保存却什么都没存"这种静默失败。
        **质量检查（用户 2026-09-21 要求）**：选区分明没有可辨识度（纯色/几乎没有明暗变化）时
        同样不写文件、不关窗口，并说明为什么（这种模板存下来只会到处误匹配）。
        """
        if self.selection() is None:
            self.info_label.setText(
                f"请先按住左键拖拽框选要保存的区域（至少 {MIN_SELECTION_SIZE}x{MIN_SELECTION_SIZE} 像素）"
            )
            return
        quality = self.selection_quality()
        if quality is not None and not quality.is_usable:
            logger.warning("拒绝保存：选区辨识度不合格 —— %s（%dx%d）",
                           quality.message, quality.width, quality.height)
            self.info_label.setText(
                f"这块区域{quality.message}，存成模板会在画面上到处误匹配："
                "请换一块有纹理/数字/图标的区域（或把选区框大一点）"
            )
            return
        if self.save_selection() is None:
            self.info_label.setText("保存失败：请检查模板目录是否可写（详情见日志）")
            return
        self.accept()

    def save_selection(self) -> Path | None:
        """把选区裁剪成模板 PNG；无有效选区时返回 None（不写文件）。

        **纯色/没有细节**的选区同样返回 None（用户 2026-09-21 要求）—— 按钮那一层已经拦过一次，
        这里再拦一次是为了让程序化调用（测试、脚本）也走同一条规则，绝不落下一个没法用的模板。
        """
        selection = self.selection()
        if selection is None:
            logger.warning("未选择有效区域（至少 %dx%d 像素）", MIN_SELECTION_SIZE, MIN_SELECTION_SIZE)
            return None
        if self._save_dir is None:
            logger.warning("未配置模板保存目录")
            return None
        quality = self.selection_quality()
        if quality is not None and not quality.is_usable:
            logger.warning("拒绝保存辨识度不合格的模板：%s", quality.message)
            return None
        x, y, width, height = selection
        crop = self._image[y : y + height, x : x + width]
        path = self._save_dir / f"anchor_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            # 评审 P2-8：mkdir 必须在 try 内 —— 目录不可写时旧实现直接冒 OSError 进 Qt 槽，
            # 调用方那句"保存失败：请检查模板目录是否可写"永远走不到。
            self._save_dir.mkdir(parents=True, exist_ok=True)
            self.saved_path = save_image(path, crop)
            logger.info(
                "模板已保存：%s（只保存框选区域 %dx%d，客户区左上 (%d, %d)）",
                path, width, height, x, y,
            )
        except Exception as exc:                 # 磁盘/编码/权限异常 → 记录并返回 None
            logger.exception("保存模板失败：%s", exc)
            self.saved_path = None
        return self.saved_path
