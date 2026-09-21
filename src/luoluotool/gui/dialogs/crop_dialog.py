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
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from luoluotool.automation.template_match import (
    DEFAULT_MAX_RESULTS,
    DEFAULT_THRESHOLD,
    RegionQuality,
    assess_region_quality,
)
from luoluotool.automation.vision import save_image
from luoluotool.core.vision import TemplateProbeResult
from luoluotool.gui.dialogs.crop_view import (      # 再导出：旧导入路径不变
    BACKGROUND_COLOR,
    BUBBLE_COLOR,
    BUBBLE_PADDING_PX,
    DIM_COLOR,
    HANDLE_CURSORS,
    HANDLE_SIZE_PX,
    MAX_ZOOM,
    MIN_SELECTION_SIZE,
    MIN_ZOOM,
    SELECTION_COLOR,
    CropView,
    to_qimage,
)
from luoluotool.gui.workers import start_probe_thread

logger = logging.getLogger(__name__)

NEAR_FULL_RATIO = 0.95          # 选区面积 ≥ 整屏的该比例时提示"几乎等于整屏"
PROBE_IDLE_TEXT = "尚未试识别（点左边按钮，把当前选区在本图上匹配一次）"
PROBE_STALE_TEXT = "选区已改动，上一次的试识别结果已作废（请对新选区重新试一次）"
ZOOM_SLIDER_STEPS = 1000        # 缩放滑条的行程（整数刻度；刻度含义见下面两个换算函数）


class _ZoomSlider(QSlider):
    """缩放滑条：多一个双击信号（QSlider 本身没有双击事件，只能自己补）。

    双击＝`zoom_to_actual()`（1:1 显示）：评审 P3-2 指出「1:1 显示」在换成滑条后成了没人调用的
    死 API，而评审给的另一个选项就是"把 1:1 做成快捷操作"——这样它既不是死代码，
    用户也还能一键回到 1 个图像像素 = 1 个屏幕像素（滑条很难精确拖到那个倍率）。
    """

    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event) -> None:      # noqa: N802 (Qt 命名)
        self.double_clicked.emit()
        event.accept()


def zoom_slider_to_zoom(position: int) -> float:
    """滑条位置 → 缩放倍数（**相对「整图适配」**，范围 `MIN_ZOOM`–`MAX_ZOOM`，即 0.5–8）。

    用**对数刻度**而不是线性：0.5–8 跨了 16 倍，线性刻度下 50%–100% 只占行程的 1/15，
    往左轻轻一拉就跨过一大段；对数刻度下**每 1/4 行程翻一倍**（50 → 100 → 200 → 400 → 800），
    于是「100%＝整图适配」正好落在 1/4 处，往左缩小、往右放大，手感均匀。

    **返回值是浮点倍数、不先取整成百分比**（评审 P3-3）：早先经"整数百分比"中转会让 1001 个刻度里
    402 个回不到原位（旋钮被同步逻辑写回一个略不同的值，观感会抖），现在 `zoom_to_slider()` 是它的
    精确反函数（全行程往返一致，有测试钉住）。
    """
    ratio = max(0.0, min(float(position), float(ZOOM_SLIDER_STEPS))) / ZOOM_SLIDER_STEPS
    # 用**以 2 为底**的算法：0.5–8 正好是 4 个"翻倍"，于是 1/4、1/2、3/4 处的值恰好是 1.0/2.0/4.0
    # （十进制 exp/log 会在这些整点上留下 7.999999999999998 这种尾巴）
    return MIN_ZOOM * 2.0 ** (ratio * math.log2(MAX_ZOOM / MIN_ZOOM))


def zoom_to_slider(zoom: float) -> int:
    """缩放倍数 → 滑条位置（`zoom_slider_to_zoom` 的反函数；把视图状态同步回滑条时用）。"""
    value = max(MIN_ZOOM, min(float(zoom), MAX_ZOOM))
    span = math.log2(MAX_ZOOM / MIN_ZOOM)
    return int(round(ZOOM_SLIDER_STEPS * math.log2(value / MIN_ZOOM) / span))


class TemplateCropDialog(QDialog):
    """框选截图生成模板：拖拽选区 → 「保存为模板」写入 save_dir。"""

    def __init__(
        self,
        image_bgr: np.ndarray,
        window_size: tuple[int, int],
        save_dir: Path | None,
        parent: QWidget | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        file_stem: str = "anchor",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("框选截图生成模板")
        self._image = image_bgr
        self._save_dir = Path(save_dir) if save_dir is not None else None
        # 文件名前缀：调试页用默认的 `anchor`（框选产物）；日常任务页传「鸡舍_岛屿1」这种好认的名字
        self._file_stem = file_stem or "anchor"
        # 试识别用的阈值 = 调试页当前设定（评审 P2-2），保证与正式识别同口径
        self._threshold = float(threshold)
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
            "下面滑条＝左右拉改缩放（100%＝整图适配，最高 800%）、旁边的「重置」＝视图归位 + 清空选区；"
            "鼠标旁的放大镜显示当前像素与坐标。\n"
            "**拿不准就点「在本图试识别」**：把当前选区当模板，在这张截图上 1:1 匹配一次，"
            "当场告诉你这块区域在这张图上有没有重复。\n"
            "建议框选画面中**不会变化**的局部（数字、倒计时等变动区域会让匹配不稳定）。"
        ))
        self.view = CropView(image_bgr)
        self.crop_view = self.view            # 语义化别名
        self.view.setFocus()                  # 打开弹窗就把键盘焦点给框选图（方向键立刻可用）
        self.info_label = QLabel("尚未选择区域")
        self.info_label.setWordWrap(True)

        zoom_row = QHBoxLayout()
        self.zoom_slider = _ZoomSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(0, ZOOM_SLIDER_STEPS)
        self.zoom_slider.setValue(zoom_to_slider(1.0))
        self.zoom_slider.setToolTip(
            "左右拖动改缩放（相对「整图适配」）：100%＝整图刚好铺满，每往右 1/4 行程翻一倍（最高 800%），"
            "最左是 50%；滚轮缩放也会同步到这里；双击滑条＝1:1 显示（1 图像像素 = 1 屏幕像素）"
        )
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider_changed)
        self.zoom_slider.double_clicked.connect(self.view.zoom_to_actual)
        # 滑条**不拿键盘焦点**：方向键要留给框选图做微调（QSlider 会吃掉左右方向键，一拖滑条
        # 方向键就从"挪选区 1 像素"变成"改缩放"了）
        self.zoom_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.zoom_value_label = QLabel()
        self.zoom_value_label.setMinimumWidth(88)     # 数字位数变化时界面不抖
        self.zoom_reset_button = QPushButton("重置")
        self.zoom_reset_button.setToolTip("恢复弹窗初始状态：缩放回到整图适配、画面归位，并清空当前选区")
        self.zoom_reset_button.clicked.connect(self.reset_all)
        self.zoom_hint_label = QLabel("滚轮＝以鼠标为中心缩放｜中键拖拽 或 空格+拖拽＝平移画面")
        self.zoom_hint_label.setWordWrap(True)
        zoom_row.addWidget(self.zoom_slider, 1)
        zoom_row.addWidget(self.zoom_value_label)
        zoom_row.addWidget(self.zoom_reset_button)

        # 「在本图试识别」（D1）：把当前选区当模板，在同一张截图上匹配一次
        self.probe_button = QPushButton("在本图试识别")
        self.probe_button.setToolTip(
            "把当前选区当模板，在这张截图上匹配一次：看画面里有没有别处长一样（不保存文件、不产生任何输入）"
        )
        self.probe_button.setEnabled(False)           # 没框选就没得测
        self.probe_button.clicked.connect(self.run_probe)
        self.probe_hint_label = QLabel(
            "「在本图试识别」＝当场试一次：只命中你框的这块＝独一无二；还有别处＝识别时可能选错地方。"
        )
        self.probe_hint_label.setWordWrap(True)
        self.probe_result_label = QLabel(PROBE_IDLE_TEXT)
        self.probe_result_label.setWordWrap(True)
        probe_row = QHBoxLayout()
        probe_row.addWidget(self.probe_button)
        probe_row.addWidget(self.probe_hint_label, 1)
        self._probe_thread: TemplateProbeThread | None = None
        self._probe_region: tuple[int, int, int, int] | None = None

        layout.addWidget(self.view, 1)
        layout.addLayout(zoom_row)
        layout.addWidget(self.zoom_hint_label)
        layout.addWidget(self.info_label)
        layout.addLayout(probe_row)
        layout.addWidget(self.probe_result_label)

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

        # 信号连接放在最后：`_refresh_info` 会用试识别的按钮与结果标签（要等它们建好）
        self.view.selection_changed.connect(self._refresh_info)
        self.view.view_changed.connect(self._refresh_info)

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
        """信息行 = 选区描述 + 视图状态（缩放倍率 + 鼠标处客户区坐标）。

        顺带维护「在本图试识别」的状态：选区一变，上一次的结论就不再适用（否则用户会拿着
        上一块区域的结论判断这一块），按钮可用性也跟着选区走。
        """
        self.info_label.setText(f"{self.selection_text()}　｜　{self.view_status_text()}")
        selection = self.selection()
        self.probe_button.setEnabled(selection is not None and not self.probe_in_flight())
        if self._probe_region is not None and selection != self._probe_region:
            self._clear_probe_result()
        self._sync_zoom_controls()

    # ------------------------------------------- 缩放滑条 / 重置（用户 2026-09-21 要求）
    def _on_zoom_slider_changed(self, position: int) -> None:
        """拖滑条 → 改缩放（锚点＝选区中心，没选区则图像中心，画面不跳走）。"""
        self.view.set_zoom_relative(zoom_slider_to_zoom(position))

    def _sync_zoom_controls(self) -> None:
        """把视图的缩放同步回滑条与数值标签（滚轮 / 滑条 / 重置都共用视图这一份状态）。

        换算不带"整数百分比"中转，所以拖滑条之后这里算出来的位置就是用户拖到的那个位置，
        旋钮不会被写回一个略不同的值（评审 P3-3）。
        """
        position = zoom_to_slider(self.view.zoom_relative())
        if position != self.zoom_slider.value():
            self.zoom_slider.blockSignals(True)      # 防回环：程序设置滑条不要再触发一次缩放
            self.zoom_slider.setValue(position)
            self.zoom_slider.blockSignals(False)
        self.zoom_value_label.setText(f"适配 {self.view.zoom_relative_percent()}%")

    def reset_all(self) -> None:
        """「重置」＝恢复弹窗初始状态（用户 2026-09-21 要求）：视图归位 + 清空选区。

        与「滚轮缩小」之类不同：这里把**缩放和平移一起归零**（回到整图适配），
        并把当前框选清掉、试识别结论作废，等于把弹窗退回刚打开时的样子。
        """
        self.view.zoom_to_fit()                      # 缩放归 1（滑条跟着回 100%）、平移归零
        self.view.clear_selection()
        self._clear_probe_result()
        self._refresh_info()
        self.view.setFocus()                         # 重置完把键盘焦点交回框选图（方向键继续可用）

    # ------------------------------------------- 「在本图试识别」（D1 自检）
    @property
    def probe_thread(self) -> TemplateProbeThread | None:
        """当前在飞的试识别线程（没有则为 None）；关窗路径与测试用它确认线程已收干净。"""
        return self._probe_thread

    def probe_in_flight(self) -> bool:
        """是否还有一次试识别没结清（评审 P2-4）。

        不能用 `isRunning()`：它在**排队的 `finished` 槽执行之前**就已经是 False 了，
        于是按钮会被过早启用，极窄窗口内再点一次就会把新线程的引用覆盖掉。
        这里以"引用还在"为准（结果送达主线程后才置空），窗口更保守、也更安全。
        """
        return self._probe_thread is not None

    def run_probe(self) -> None:
        """把当前选区当模板，在同一张截图上试一次匹配（后台线程，不卡界面）。

        纯色/几乎没有细节的选区分明没有意义（匹配会满屏飘），直接提示换一块、不浪费时间。
        """
        selection = self.selection()
        if selection is None:
            self.probe_result_label.setText("请先框选要测试的区域")
            return
        if self.probe_in_flight():
            return
        quality = self.selection_quality()
        if quality is not None and not quality.is_usable:
            self.probe_result_label.setText(
                f"这块区域{quality.message}，试识别只会满屏「命中」、看不出有没有用："
                "请换一块有纹理/数字/图标的区域（或把选区框大一点）"
            )
            return
        self._clear_probe_result()
        self._probe_region = selection
        self.probe_result_label.setText("正在本图试识别…")
        self.probe_button.setEnabled(False)
        self._probe_thread = start_probe_thread(
            self._image, selection, self._threshold, DEFAULT_MAX_RESULTS
        )
        self._probe_thread.finished_probe.connect(self._on_probe_finished)
        self._probe_thread.failed_message.connect(self._on_probe_failed)
        self._probe_thread.finished.connect(self._on_probe_thread_finished)

    def _on_probe_finished(self, result: TemplateProbeResult) -> None:
        """试识别成功：写结论 + 把"别的那些位置"画在图上（自己那处＝选区本身，不重复画）。

        **跑的过程中用户改了选区就把这份结论丢掉**（评审 P2-3）：否则结论与橙框会挂在一个
        早已不是当前的选区上，而且 `_clear_probe_result()` 已经把 `_probe_region` 归零，
        后续任何选区变化都清不掉它。
        """
        if result.region != self.selection():
            logger.info(
                "试识别结果作废：选区已从 %s 变成 %s", result.region, self.selection()
            )
            self.probe_result_label.setText(PROBE_STALE_TEXT)
            self.view.set_probe_rects([])
            self._probe_region = None
            return
        self._probe_region = result.region
        self.probe_result_label.setText(result.message)
        others = [
            QRect(match.left, match.top, match.width, match.height) for match in result.others
        ]
        self.view.set_probe_rects(others)

    def _on_probe_failed(self, message: str) -> None:
        self.probe_result_label.setText(f"试识别失败：{message}")
        self.view.set_probe_rects([])

    def _on_probe_thread_finished(self) -> None:
        """线程结束（**只有仍是当前那一个**才置空，评审 P2-4）。"""
        if self.sender() is not self._probe_thread:
            return                       # 上一轮线程的迟到信号，别把新一轮的引用清掉
        self._probe_thread = None
        self.probe_button.setEnabled(self.selection() is not None)

    def _clear_probe_result(self) -> None:
        """清掉试识别的结论与图上的标记（选区变了 / 要重新测时调用）。"""
        self._probe_region = None
        self.view.set_probe_rects([])
        self.probe_result_label.setText(PROBE_IDLE_TEXT)

    def _release_probe_thread(self) -> None:
        """关窗前给在飞的试识别线程"解绑"（评审 P2-4：**不许阻塞 GUI 线程**）。

        线程体是一次 `cv2.matchTemplate`，中途没法打断；所以这里**不等它**，而是：
        ① `request_stop()` 让它结束后别再发结果；② 断开信号（这个弹窗马上要被销毁）；
        ③ 线程对象本身由 `gui.workers.ACTIVE_PROBES` 这个模块级集合持有到它自然结束 ——
        这样即使弹窗先被 `deleteLater()`，也不会出现"QThread destroyed while still running"。
        """
        thread = self._probe_thread
        if thread is None:
            return
        if thread.isRunning():
            logger.info("弹窗关闭时试识别线程仍在跑：已请求停止并交由线程自己收尾")
        thread.request_stop()
        # 只断开**本弹窗**的槽：`finished` 上还挂着 `TemplateProbeThread._unregister`（把线程从
        # ACTIVE_PROBES 摘掉），一次性 disconnect() 会连它一起断，线程就再也摘不掉了。
        for signal, slot in (
            (thread.finished_probe, self._on_probe_finished),
            (thread.failed_message, self._on_probe_failed),
            (thread.finished, self._on_probe_thread_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):      # 没连过 / 已经断开
                pass
        self._probe_thread = None

    def done(self, result: int) -> None:
        """accept / reject / close 都会走到这里：先给试识别线程解绑，再关。"""
        self._release_probe_thread()
        super().done(result)

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
        path = self._save_dir / f"{self._file_stem}_{datetime.now():%Y%m%d_%H%M%S}.png"
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
