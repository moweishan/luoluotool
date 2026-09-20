"""布局测量：检查「页签高度稳定」规则是否成立（`--measure-layout` 与调试页共用）。

规则（2026-09-19 用户实测后固化）：页签内容是 `QTabWidget` 最小高度的来源。
若某个页签的内容过高且不可滚动，它会把整个页签区顶高 → 窗口被撑大、日志面板被压扁，
并且**所有页签高度**都会随该页签的挂载/卸载而变化。因此所有页签都继承
`gui.widgets.ScrollablePage`（内容自动进入 `QScrollArea`），本模块负责把这个
"应该成立"的事实变成**可测量、可断言、可回归**的数字。

本模块只做几何测量：不产生任何输入、不读写配置、不改动页面状态
（测量挂载/未挂载两种状态后会把页签恢复原样）。
"""

import logging
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from luoluotool.gui.pages.debug import PAGE_TITLE as DEBUG_TAB_TITLE
from luoluotool.gui.widgets import ScrollablePage

logger = logging.getLogger(__name__)

# 页签内容最小高度超过该值即视为「会顶高页签区」的页面（可滚动页面的实测值约 60–70）
MAX_PAGE_MIN_HEIGHT = 200

# 主窗口里除页签区以外的固定占用（底部按钮行 + 日志面板 + 边距）；仅用于报告说明
PAGE_TITLES: tuple[tuple[str, str], ...] = (
    ("设置", "settings_page"),
    ("日常任务", "daily_page"),
    ("卡订单", "order_hold_page"),
    ("功能三", "feature3_page"),
    ("功能四", "feature4_page"),
    ("关于", "about_page"),
    ("开发者调试", "debug_page"),
)


@dataclass(frozen=True)
class PageMeasure:
    """单个页签的几何测量结果。"""

    title: str
    attribute: str
    mounted: bool
    min_height: int
    content_height: int
    scrollable: bool

    @property
    def problem(self) -> str | None:
        """返回该页签的违规说明；合规时返回 None。"""
        if not self.scrollable:
            return f"页签「{self.title}」未继承 ScrollablePage（内容未放进 QScrollArea）"
        if self.min_height > MAX_PAGE_MIN_HEIGHT:
            return (
                f"页签「{self.title}」最小高度 {self.min_height} > {MAX_PAGE_MIN_HEIGHT}"
                "（内容过高，会顶高页签区）"
            )
        return None


@dataclass(frozen=True)
class LayoutMeasure:
    """主窗口布局测量结果（挂载/未挂载「开发者调试」页两种状态）。

    同时记录最小高度（决定窗口会不会被撑大）、建议高度与实际分配高度（决定页签区与
    日志面板各拿多少空间）——用户实测的"所有页签高度都会变"两者都涉及。
    """

    window_size: tuple[int, int]
    tabs_min_unmounted: int
    tabs_min_mounted: int
    tabs_hint_unmounted: int
    tabs_hint_mounted: int
    tabs_height_unmounted: int
    tabs_height_mounted: int
    window_min_unmounted: int
    window_min_mounted: int
    log_height_unmounted: int
    log_height_mounted: int
    pages: tuple[PageMeasure, ...]

    @property
    def unstable_items(self) -> tuple[str, ...]:
        """挂载/卸载调试页前后不一致的指标名（空列表表示完全稳定）。"""
        pairs = (
            ("页签区最小高度", self.tabs_min_unmounted, self.tabs_min_mounted),
            ("页签区建议高度", self.tabs_hint_unmounted, self.tabs_hint_mounted),
            ("页签区实际高度", self.tabs_height_unmounted, self.tabs_height_mounted),
            ("窗口最小高度", self.window_min_unmounted, self.window_min_mounted),
            ("日志面板高度", self.log_height_unmounted, self.log_height_mounted),
        )
        return tuple(name for name, before, after in pairs if before != after)

    @property
    def toggle_stable(self) -> bool:
        """挂载/卸载调试页时，页签区与日志面板的各项高度是否完全不变。"""
        return not self.unstable_items

    @property
    def fits(self) -> bool:
        """两种状态下窗口最小高度都不超过窗口当前高度（否则窗口会被撑高）。"""
        return max(self.window_min_unmounted, self.window_min_mounted) <= self.window_size[1]

    @property
    def problems(self) -> tuple[str, ...]:
        """所有违规项（页签各自的问题 + 整体规则）。"""
        found: list[str] = []
        for page in self.pages:
            if page.problem:
                found.append(page.problem)
        if not self.toggle_stable:
            found.append(
                "挂载/卸载「开发者调试」页会改变页签区或日志面板的高度："
                + "、".join(self.unstable_items)
            )
        if not self.fits:
            found.append(
                f"窗口最小高度 {max(self.window_min_unmounted, self.window_min_mounted)}"
                f" 超过窗口高度 {self.window_size[1]}（窗口会被撑高，页签高度随之变化）"
            )
        return tuple(found)

    @property
    def ok(self) -> bool:
        return not self.problems


def _activate_layout(window) -> None:
    """不跑事件循环的前提下让布局立刻生效（避免在按钮槽里 processEvents 造成重入）。"""
    central = window.centralWidget()
    if central is not None and central.layout() is not None:
        central.layout().activate()
    if window.tabs.layout() is not None:
        window.tabs.layout().activate()


def _sample(window) -> tuple[int, int, int, int, int]:
    """取一组高度：(页签区最小/建议/实际、窗口最小、日志面板实际)。"""
    _activate_layout(window)
    return (
        int(window.tabs.minimumSizeHint().height()),
        int(window.tabs.sizeHint().height()),
        int(window.tabs.height()),
        int(window.minimumSizeHint().height()),
        int(window.log_panel.height()),
    )


def _measure_pages(window, mounted_titles: tuple[str, ...]) -> tuple[PageMeasure, ...]:
    pages: list[PageMeasure] = []
    for title, attribute in PAGE_TITLES:
        page: QWidget | None = getattr(window, attribute, None)
        if page is None:
            continue
        content = getattr(page, "content", page)
        pages.append(
            PageMeasure(
                title=title,
                attribute=attribute,
                mounted=title in mounted_titles,
                min_height=int(page.minimumSizeHint().height()),
                content_height=int(content.sizeHint().height()),
                scrollable=isinstance(page, ScrollablePage),
            )
        )
    return tuple(pages)


def measure_layout(window) -> LayoutMeasure:
    """测量主窗口布局；挂载/未挂载调试页两种状态都会被测到（测完恢复原状）。

    只读几何信息：不产生输入、不读写配置、测量结束后页签数量与当前选中项保持原样。
    """
    debug_page = window.debug_page
    index = window.tabs.indexOf(debug_page)
    currently_mounted = index >= 0
    current_index = window.tabs.currentIndex()
    original_title = window.tabs.tabText(index) if currently_mounted else None
    mounted_titles = tuple(window.tabs.tabText(i) for i in range(window.tabs.count()))

    if currently_mounted:
        (
            tabs_min_mounted, tabs_hint_mounted, tabs_height_mounted,
            window_min_mounted, log_height_mounted,
        ) = _sample(window)
        window.tabs.removeTab(index)
        try:
            (                                          # 临时卸载：测"未挂载"状态
                tabs_min_unmounted, tabs_hint_unmounted, tabs_height_unmounted,
                window_min_unmounted, log_height_unmounted,
            ) = _sample(window)
        finally:
            window.tabs.insertTab(index, debug_page, original_title)
            window.tabs.setCurrentIndex(current_index)
    else:
        (
            tabs_min_unmounted, tabs_hint_unmounted, tabs_height_unmounted,
            window_min_unmounted, log_height_unmounted,
        ) = _sample(window)
        window.tabs.addTab(debug_page, DEBUG_TAB_TITLE)
        try:
            (                                          # 临时挂载：测"已挂载"状态
                tabs_min_mounted, tabs_hint_mounted, tabs_height_mounted,
                window_min_mounted, log_height_mounted,
            ) = _sample(window)
        finally:
            window.tabs.removeTab(window.tabs.indexOf(debug_page))
            window.tabs.setCurrentIndex(current_index)

    _activate_layout(window)      # 恢复原状后的布局
    measure = LayoutMeasure(
        window_size=(int(window.size().width()), int(window.size().height())),
        tabs_min_unmounted=tabs_min_unmounted,
        tabs_min_mounted=tabs_min_mounted,
        tabs_hint_unmounted=tabs_hint_unmounted,
        tabs_hint_mounted=tabs_hint_mounted,
        tabs_height_unmounted=tabs_height_unmounted,
        tabs_height_mounted=tabs_height_mounted,
        window_min_unmounted=window_min_unmounted,
        window_min_mounted=window_min_mounted,
        log_height_unmounted=log_height_unmounted,
        log_height_mounted=log_height_mounted,
        pages=_measure_pages(window, mounted_titles),
    )
    if measure.ok:
        logger.info(
            "布局测量通过：页签区 %d（实际 %d）、日志面板 %d、窗口最小高度 %d（窗口 %d×%d）",
            measure.tabs_min_mounted, measure.tabs_height_mounted, measure.log_height_mounted,
            measure.window_min_mounted, measure.window_size[0], measure.window_size[1],
        )
    else:
        for problem in measure.problems:
            logger.warning("布局测量发现问题：%s", problem)
    return measure


def format_measure_report(measure: LayoutMeasure) -> str:
    """把测量结果格式化成可读多行报告（供 CLI 打印与调试页展示）。

    **只使用中文 Windows 控制台（cp936）能编码的字符**：报告曾经用 `✓ ✗ ×` 作标记，
    冻结后的 exe（GUI 子系统、stdout 按 ANSI 代码页初始化）打印时直接
    `UnicodeEncodeError` → `--measure-layout` 退出码 1（2026-09-19 实测）。
    现在改用 `[OK]` / `[NG]`，并由 `__main__._print_safe()` 兜底任何未来的不可编码字符。
    """
    width, height = measure.window_size
    lines = [f"布局测量（离屏，窗口 {width}×{height}）"]
    lines.append(
        f"· 页签区最小高度：未挂载调试页 {measure.tabs_min_unmounted} / "
        f"已挂载 {measure.tabs_min_mounted}"
    )
    lines.append(
        f"· 页签区建议高度：未挂载 {measure.tabs_hint_unmounted} / "
        f"已挂载 {measure.tabs_hint_mounted}"
    )
    lines.append(
        f"· 页签区实际高度：未挂载 {measure.tabs_height_unmounted} / "
        f"已挂载 {measure.tabs_height_mounted}"
    )
    lines.append(
        f"· 日志面板高度：未挂载 {measure.log_height_unmounted} / "
        f"已挂载 {measure.log_height_mounted}"
    )
    lines.append(
        f"· 窗口最小高度：未挂载 {measure.window_min_unmounted} / "
        f"已挂载 {measure.window_min_mounted} → {width}×{height} 放得下："
        f"{'是' if measure.fits else '否'}"
    )
    lines.append("· 各页签（最小高度=对页签区的压力，内容高度=不滚动时所需高度）：")
    for page in measure.pages:
        state = "已挂载" if page.mounted else "未挂载"
        scroll = "是" if page.scrollable else "否"
        flag = " [OK]" if page.problem is None else " [NG]"
        lines.append(
            f"    {page.title:<10} 最小 {page.min_height:>4}  内容 {page.content_height:>4}  "
            f"可滚动 {scroll}  {state}{flag}"
        )
    if measure.ok:
        lines.append("结论：挂载/卸载开发者调试页不改变任何高度，全部页签可滚动 [OK]")
    else:
        lines.append(f"结论：发现 {len(measure.problems)} 个问题 [NG]")
        for problem in measure.problems:
            lines.append(f"    - {problem}")
    return "\n".join(lines)
