# BUG_HUNT_GUIDE.md — LuoLuoTool 排查手册

> 用于定位坐标、取景、输入、配置与线程问题，提供架构说明、可检查的不变量和诊断入口。
> 文件行号可能随代码变化，优先按符号名定位，快速索引见附录。
> 修改代码后同步相关说明，并用 `tools/check_guide_index.py` 核对索引。
> 配套文档：`AGENTS.md`（开发规范）、`PROJECT_SPEC.md`（功能与边界）、`CHECKLIST.md`（验收）、`README.md`（使用说明）、`PROJECT_HANDBOOK.md`（工程与构建）。

---

## ① 快速上手

### 环境

```powershell
# 项目虚拟环境解释器
.\.venv\Scripts\python.exe
# 依赖以 requirements.txt 和 requirements-dev.txt 为准
```

### 代码改动的验收命令

只有包含代码修改的提交才执行以下测试与验收命令；仅文档、忽略规则等非代码修改不执行测试。`--measure-layout` 在改动页签或布局时执行，所需检查全部通过才算完成。

```powershell
# 建议先固定临时目录（不设也能跑）
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) 'luoluotool-tmp'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:TMP = $tmp; $env:TEMP = $tmp

# 请先在仓库根目录打开 PowerShell
.\.venv\Scripts\python.exe -m pytest -q                    # 全量单测
.\.venv\Scripts\python.exe -m luoluotool --validate-config  # 配置校验，应打印 OK
.\.venv\Scripts\python.exe -m luoluotool --smoke-gui        # 离屏建窗，日志含"离屏冒烟完成"
.\.venv\Scripts\python.exe -m luoluotool --measure-layout   # 页签高度稳定性，末行须为 "[OK]"
```

### 识别命令（需要游戏窗口；不发送输入）

```powershell
# 图像识别（退出码：0 命中 / 1 未命中或取景失败 / 2 参数非法）
.\.venv\Scripts\python.exe -m luoluotool --recognize 模板.png [模板2.png ...] `
    --threshold 0.85 --max-results 20 [--no-annotate] [--no-scale]
```

其余实机入口都在 GUI「开发者调试」页（需先在设置页打开**开发者调试**开关）：
`图片识别匹配测试`、`框选截图生成模板`、`窗口诊断`、`布局测量`、单点/连点/滑动/键盘测试、干跑开关。

### 动手前必须知道的三条红线

1. **单测绝不产生真实输入**：`tests/conftest.py:26` 的 autouse 夹具把 `AppConfig.default().dry_run`
   强制为 `True`；只有 `@pytest.mark.real_defaults` 标记的测试能看到生产默认值。
2. **单测不查真实桌面**：`tests/conftest.py:41` 把 `input_sender.find_window` / `core.vision.find_window`
   改成 `lambda keyword: None`；需要窗口的测试自己 monkeypatch。
3. **不要提交构建产物、不要 force push、不要用 PowerShell 文本命令改写仓库文件**
   （PowerShell 5.1 可能按 ANSI/GBK 处理 UTF-8；使用精确补丁或显式编码的 Python）。

### 目录一览

```
src/luoluotool/
  __main__.py    CLI：--version/--validate-config/--smoke-gui/--measure-layout/--recognize
  automation/                      自动化层（不许 import PySide6）
    vision.py    取景/渲染（黑帧回退链、BitBlt/PrintWindow 几何）+ 再导出匹配名字
    template_match.py    模板读取与匹配原语（VisionError / Match / load_template / locate_all / 可辨识度评估）
    multiscale.py    多尺度两档搜索：_scale_tiers / _scan_coarse / _refine_scale / locate_all_scaled
    drag_path.py    滑动路径几何（缓出曲线 + 分帧插值，纯函数）
    input_sender.py    InputSender 协议 / DryRunSender / RealInputSender / 越界校验 / build_channel
    real_input.py    SendInput 底层：置顶置前、点击、滑动发送、按键、光标还原
    window.py    找窗口、置前、客户区几何、诊断截图
    elevation.py    权限检测 / 以管理员重启
    hotkey.py    F8 急停热键（RegisterHotKey）
  config/                        配置层（dataclass + 原子 JSON + 迁移校验）
    models.py    AppConfig / AutomationConfig / 任务参数解析 + 上限常量（20 步/点）
    validation.py    migrate() + validate()，版本迁移与字段校验
    store.py    ConfigSaveError + save/load/_recover（先校验后写 + 原子写 + 损坏恢复）
  core/                          业务编排层（不许 import PySide6/win32）
    vision.py    recognize_in_window（多模板/多区域编排）
    debug.py    调试动作：单点/连点/滑动/键盘（复用正式通道；等待可中断）
    runner.py    Runner：顺序执行任务、循环、失败计数、停止
    registry.py    任务注册表 + 占位任务（order_hold/feature_3/feature_4）
    task.py / state.py    TaskContext/TaskResult/BaseTask；RunState 状态机（加锁 + try_transition）
  gui/                           界面层（只做绑定与展示）
    main_window.py    主窗口（展示与绑定 + 线程/状态编排）
    workers.py    后台线程：任务/调试测试/框选截图/窗口诊断 + run_debug_action
    elevation_flow.py    提权流程 mixin（检测/提示/以管理员身份重启）
    icons.py    窗口图标加载（魔数校验 + 降级为空图标）
    pages/debug.py    开发者调试页（识别入口/模板列表/干跑/测试按钮）
    pages/settings.py    设置页（含开发者调试开关 + 急停热键提示）
    daily_media.py              日常参考图控制器
    daily_workers.py            截图与解码线程
    daily_files.py / daily_deletion.py  文件删除策略与控制器
    step_debug.py               单步运行界面
    pages/daily.py    日常任务页（日常开关、循环、岛屿与参考图配置）
    pages/order_hold.py    卡订单页
    pages/planned_feature.py    功能三/四公共基类（占位页）
    pages/feature3.py,4.py    功能三/四页（占位子类）
    pages/about.py    「关于」页（风险/隐私声明、第三方许可、运行环境、复制诊断/打开目录）
    dialogs/crop_dialog.py    框选弹窗外壳（提示文字 / 缩放滑条·重置 / 试识别 / 保存 + 质量检查）
    dialogs/crop_view.py    框选交互视图 CropView（选区新建/移动/手柄缩放/键盘微调/绘制/试识别标注）
    dialogs/crop_view_zoom.py    显示变换 ZoomPanMixin（滚轮缩放/平移/放大镜/相对缩放 API）
    layout_measure.py    --measure-layout 的测量与报告（控制台编码兼容）
    widgets.py    LogPanelHandler（日志进面板）；ScrollablePage（页签基类）
    app.py    入口：QApplication、任务栏图标身份、smoke 模式
  utils/                         keys.py paths.py logging_setup.py
assets/                          icons/（入库）、templates/（自己整理的识别图片，**入库**）、screenshots/（识别底图，不入库）、anchors/（框选产物，不入库）
tests/                           与 src 同构；conftest.py 全局夹具；gui_helpers.py 共享 GUI 夹具；test_packaging.py / test_source_guards.py / test_paths.py 是仓库级守卫
packaging/                       build.ps1（UTF-8 **带 BOM**）、LuoLuoTool.spec、rthook_windowed_stdio.py
```

---

## ② 架构、数据流与线程模型

### 依赖方向（硬规则，违反即缺陷）

```
gui  →  core  →  automation / utils
```

- `core` **不得** import PySide6 / win32（要用窗口能力时经 `automation.*`）。
- `automation` **不得** import PySide6。
- 分层自检应输出 `layer check violations = 0`：

```powershell
# 请先在仓库根目录打开 PowerShell
.\.venv\Scripts\python.exe -c @"
# 分层自检：core 禁 PySide6/win32/ctypes；automation 仅禁 PySide6
# 必须按 AST 检查真实 import —— 按文本匹配会把 docstring 里提到 'PySide6' 的文件误报成违规
import ast, pathlib
bad = 0
for p in sorted(pathlib.Path('src/luoluotool').rglob('*.py')):
    parts = p.parts
    layer = 'core' if 'core' in parts else ('automation' if 'automation' in parts else None)
    if layer is None:
        continue
    for node in ast.walk(ast.parse(p.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            names = [a.name.split('.')[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or '').split('.')[0]]
        else:
            continue
        hits = [n for n in names
                if n == 'PySide6' or (layer == 'core'
                                      and (n.startswith('win32') or n in {'pywintypes', 'ctypes'}))]
        if hits:
            print('VIOLATION', layer, p, '->', hits); bad += 1
print('layer check violations =', bad)
"@
```

### 主链路 A：图像识别（框选模板 → 识别 → 坐标）

```
调试页「图片识别匹配测试」          gui/pages/debug.py   _on_vision_clicked()
  → 发信号 test_requested("vision", {images, threshold, max_results})
主窗口分发                          gui/main_window.py  _on_debug_test()
  后台线程 _DebugTestThread.run     gui/workers.py  （不阻塞 GUI）
  动作映射                          gui/workers.py  run_debug_action(kind="vision")
业务编排                            core/vision.py       recognize_in_window()
  ① 归一化模板列表                  core/vision.py       _template_paths()
  ② 找窗口 + 就绪校验               core/vision.py    find_window / is_window_ready
  ③ 取景（只截一次，多模板共用）    automation/vision.py capture_client_bgr()
  ④ 逐张模板多尺度匹配              automation/multiscale.py locate_all_scaled()
  ⑤ 组织消息/带框截图               core/vision.py       _success_result()
结果回传                            Signal finished_message → 调试页状态栏
```

**框选生成模板**链路：

```
调试页「框选截图生成模板」          gui/pages/debug.py   crop_button → crop_requested 信号
主窗口门禁 + 后台截图               gui/main_window.py   _on_crop_requested()
  截图线程                          gui/workers.py   _CaptureThread → core/vision.py capture_window()
  弹框（GUI 线程）                  gui/main_window.py   _on_capture_ready() → TemplateCropDialog
  拖拽框选                          gui/dialogs/crop_view.py    CropView（选区外＝新框选）
  修改选区         gui/dialogs/crop_view.py   hit_test() → _apply_move() / _apply_resize()
                                    选区内部＝整体移动；四角/四边 8 个手柄＝改大小（对角固定、≥MIN_SELECTION_SIZE=8）
                                    Alt+手柄＝以选区中心对称缩放（_symmetric_resize）
  键盘微调       gui/dialogs/crop_view.py   keyPressEvent → _nudge_whole() / _nudge_edge()
                                    方向键＝整体 1 图像像素（Shift=10）；Ctrl+方向＝该边外扩 1；Ctrl+Shift＝该边内收 1
  视觉反馈与撤销      gui/dialogs/crop_view.py   drag_bubble_text() / _paint_dim_mask()
                                    Esc＝撤销拖拽或清空；双击＝清空；空格·右键拖拽＝移动
  视图变换       gui/dialogs/crop_view_zoom.py  fit_scale/image_rect/_set_zoom/wheelEvent
                                    滚轮＝以鼠标为锚点缩放；中键·空格拖拽＝平移；magnifier_rect＝放大镜
  可辨识度提示 / 保存前检查 automation/template_match.py assess_region_quality()（对比度 + 边缘占比）
     ↑ 界面侧                      gui/dialogs/crop_dialog.py  selection_quality() → selection_text()
                                    几乎是纯色（is_blank_frame）时：不写文件、不关窗口，只说明原因
  在本图试识别                gui/dialogs/crop_dialog.py  run_probe() → start_probe_thread()（workers.py）
     ↑ 判据                        core/vision.py  probe_region_on_image()（1 试匹配，看除自己外还有几处；阈值＝调试页当前值）
     ↑ 结论展示                    gui/dialogs/crop_view.py  set_probe_rects()（橙色框 + 序号标注其它位置）
                                    关窗不阻塞：crop_dialog.py done() → _release_probe_thread()（request_stop + 交 ACTIVE_PROBES）
  缩放滑条（相对整图适配 50%–800%）  gui/dialogs/crop_dialog.py  zoom_slider → _on_zoom_slider_changed()
     刻度换算（对数，互为反函数）    gui/dialogs/crop_dialog.py   zoom_slider_to_zoom / zoom_to_slider
  重置（视图归位 + 清空选区）        gui/dialogs/crop_dialog.py  reset_all()（含 zoom_to_fit + clear_selection）
  滑条状态同步                       gui/dialogs/crop_dialog.py  _sync_zoom_controls()（blockSignals 防回环）
  HUD（选区+辨识度+缩放%+鼠标坐标）  gui/dialogs/crop_dialog.py  _refresh_info() → view_status_text()
  保存（**只存选区**）              gui/dialogs/crop_dialog.py  _on_save_clicked() → save_selection()
  加入模板列表                      gui/main_window.py   debug_page.add_vision_template()
```

### 主链路 C：鼠标单点 / 连点（含"点击时长"）

```
调试页「鼠标单点测试」              gui/pages/debug.py   single_hold_spin（点击时长，ms）
调试页「鼠标连点测试」              gui/pages/debug.py   repeat_hold_spin（连点每次都用它）
  → _on_single_clicked / _on_repeat_clicked 发信号 test_requested(kind, {...})
    载荷：single {x, y, hold_ms}｜repeat {x, y, count, interval_ms, hold_ms}
主窗口分发                          gui/workers.py   run_debug_action
业务编排（单点）                    core/debug.py         run_single_click(hold_ms=...)
业务编排（连点）                    core/debug.py        run_repeat_click(..., hold_ms=...)（间隔＝点击之后的等待）
校验                                core/debug.py         _validate_click_hold（0–5000 ms 整数）
通道（干跑/真实）                   automation/input_sender.py build_channel
  点击                              input_sender.py      RealInputSender.click_at(x, y, hold_seconds)
  **两步移动（hover）**             input_sender.py      _move_cursor_for_click（中途点 → 目标）
  **点击前核对事实**                input_sender.py      _verify_before_press（漂移>4px 跳过）
  时间线                            input_sender.py 容差 4px / 步进 30ms / 松手后 350ms 才还原光标
                                    input_sender.py       DryRunSender.click_at（只写日志，同样校验越界）
底层原语                            automation/real_input.py send_left_click(sleep, hold_seconds, stop_event)
  按下 → 按住（CLICK_SLICE_SECONDS=50ms 切片查急停）→ **finally 抬起左键**
  置前后等待 200ms、按下前等待 80ms
  命中测试/窗口描述                 automation/real_input.py window_under_point / describe_window
```

### 主链路 B：任务执行与输入注入

```
日常任务总开关 + 任务开关 → 按 order / ID 入队；启用的卡订单、功能三和功能四按固定顺序追加
主窗口「启动」                      gui/main_window.py   _start()
  真实模式确认弹窗                  gui/main_window.py   _real_mode_warning_text()/_confirm_real_mode()
  运行线程 _RunnerThread            gui/workers.py
  Runner 顺序执行                   core/runner.py        Runner.start()
    每个任务拿到 TaskContext（含 sender）core/task.py
    输入通道构建                    automation/input_sender.py build_channel()
      ├─ 干跑：DryRunSender（，只写日志，**同样做越界校验**）
      └─ 真实：WindowReadinessGate() → RealInputSender()
           点击/滑动前校验              input_sender.py point_in_client_area / check_points_in_bounds
           每次输入前置顶/置前并复核    automation/real_input.py ensure_window_front()
           客户端→屏幕换算              automation/real_input.py client_to_screen()
           实际注入                     automation/real_input.py _send()（SendInput）
    停止/F8 急停                     gui/main_window.py _stop()/_on_failsafe() → stop_event
```

### 线程模型（bug 高发区）

| 线程 | 位置 | 约束 |
|---|---|---|
| GUI 主线程 | `gui/**` | **禁止** sleep/忙等/同步截图；所有长任务进 QThread |
| 运行线程 `_RunnerThread` | `workers.py:30` | 只发信号回 GUI，不直接改控件 |
| 调试测试线程 `_DebugTestThread` | `workers.py:41` | 执行期间禁用按钮；可被 `request_stop()` 中断 |
| 截图线程 `_CaptureThread` | `workers.py:100` | 框选前截图，完成后发 `captured` |
| 诊断线程 `_DiagnoseThread` | `workers.py:122` | 窗口诊断 |
| 日常截图/解码线程 | `gui/daily_workers.py` | 后台截图或解码，结果发回 GUI，作废结果丢弃 |
| 试识别线程 | `gui/workers.py` | `ACTIVE_PROBES` 持有至结束，关弹窗不阻塞 GUI |

**找 bug 时优先怀疑**：跨线程直接操作控件、`stop_event` 没有切片检查、`finally` 里漏了资源释放或状态回滚。

---

## ③ 坐标系与几何（本项目最容易出 bug 的地方）

### 三套坐标

| 坐标 | 定义 | 谁在用 |
|---|---|---|
| **客户区坐标** | 游戏窗口客户区左上角为 (0,0)，范围 `[0,width)×[0,height)` | **识别结果、框选选区、点击/滑动入参**，全项目统一用它 |
| **窗口坐标** | 窗口左上角为原点，包含标题栏与边框 | 窗口 DC、PrintWindow 与客户区裁剪 |
| **屏幕坐标** | 桌面坐标 | 真实输入、屏幕取景及 `ClientToScreen` 换算 |

- 客户区左上角在屏幕上的位置：`win32gui.ClientToScreen(hwnd, (0, 0))`。
- **客户区在窗口内的偏移**：`automation/window.py:80 client_area_offset(hwnd)` =
  `ClientToScreen(0,0) - GetWindowRect左上角` = 标题栏高度 + 边框宽度。
  偏移由当前窗口几何计算；无边框窗口为 (0, 0)。

### 几何约束

1. **窗口 DC（`GetWindowDC`）与 `PrintWindow` 的原点都是"窗口左上角"**（含标题栏）。
   取景必须以客户区偏移为源点/裁剪原点，否则抓到"标题栏 + 客户区上半部分"，
   画面底部缺"标题栏高度"一截，**识别坐标整体偏下标题栏高度**。
   → `_render_client_bits_bitblt` 的 BitBlt 源点、`_render_client_bits_printwindow` 的整窗渲染+裁剪。
2. **屏幕 BitBlt 用 `ClientToScreen(0,0)` 作源点，天然以客户区左上为原点**，不需要再偏移/裁剪
   （`automation/vision.py:254`，它是"原点正确"的参照实现）。但它要求**窗口确实在前台**，
   否则会抓到被遮挡窗口的内容，因此调用方有前台门禁（`vision.py:110`）。
3. **窗口尺寸会变**：客户区坐标与尺寸一律运行时读取，不写死分辨率。


### 取景回退链

```text
capture_client_bgr
  → PrintWindow(PW_RENDERFULLCONTENT)
  → 纯色/黑帧或主路径异常时回退
      → PrintWindow(PW_CLIENTONLY)
      → BitBlt(窗口 DC)，源点为客户区偏移
      → 屏幕 BitBlt，仅窗口在前台时使用
  → 全部失败时抛带原因的 VisionError
```

### 坐标自检方法

抓一张客户区图 + 一张整屏图，用模板匹配量出"客户区图左上角在屏幕上的真实位置"，
它必须等于 `ClientToScreen(0,0)`；再独立核对"识别出的客户区中心"与"整屏定位换算值"，
偏差应 ≤3px。
可运行脚本见第 ⑧ 节。

---

## ④ 不变量清单（每条都能立刻验证；违反后的症状也列了）

> 用法：挑一条，写一个"故意违反它"的测试或脚本，看现有测试是否能抓住。抓不住的地方就是漏洞。

| # | 不变量 | 违反后的症状 | 现有守卫 |
|---|---|---|---|
| 1 | 单测恒为干跑，绝不产生真实输入 | 单测移动真实鼠标、查真实游戏窗口，结果随环境变化 | `tests/conftest.py:26` |
| 2 | 单测不查询真实桌面窗口 | 断言依赖用户当前是否开着游戏 | `tests/conftest.py:41` |
| 3 | 点击坐标必须在客户区内；**读不到客户区按越界处理**（宁可不点） | 点到窗口外/别的程序上 | `test_point_in_client_area_boundaries`、`test_real_sender_click_bounds_are_exclusive`、`test_real_sender_skips_click_when_bounds_unreadable` |
| 4 | 滑动**起点与终点**都必须在客户区，任一端越界整段跳过 | 拖到标题栏/窗口外，画面乱飘 | `test_real_sender_skips_drag_when_{start,end,both}_outside_window` |
| 5 | 滑动任何退出路径都释放左键；松手后复查 `VK_LBUTTON`；长按不卡键 | 鼠标卡在按下状态、游戏一直拖 | `test_send_left_drag_releases_button_on_exception`、`test_drag_reports_failure_when_button_cannot_be_released`、`test_send_left_drag_aborts_on_stop_and_releases_button` |
| 5b | **点击时长**：点击＝按下→按住 `hold_seconds`→抬起；`None`＝引擎默认（40 ms）、`0`＝瞬时；按住期间切片检查急停，**任何退出路径都抬起左键** | 长按被急停后左键卡住；瞬时点击被游戏吞掉；「不传时长」被误当成 0 ms | `test_send_left_click_honours_requested_hold`、`test_send_left_click_checks_stop_while_holding`、`test_send_left_click_releases_when_sleep_raises`、`test_real_sender_passes_click_hold_to_primitive`、`test_single_click_passes_click_hold`、`test_single_click_zero_hold_means_instant` |
| 5c | **点击前必须核对事实**：实测光标是否到达目标（偏差 >`CLICK_CURSOR_TOLERANCE_PX`=4px 就**跳过点击**）、光标处顶层窗口、前台/置顶状态、客户区尺寸，全部写进日志 | 日志写"点击完成"但游戏没反应时无法区分"没送到"与"送到了游戏不认"；光标被钳制时会点到别的控件 | `test_real_sender_logs_click_context_before_press`、`test_real_sender_skips_click_when_cursor_did_not_move`、`test_real_sender_logs_warning_when_hit_test_is_other_window` |
| 5d | **输入时间线**：光标分两步移动（先中途点，`CLICK_MOVE_STEP_SECONDS`=30ms）→ `INPUT_SETTLE_SECONDS`=80ms → 按下；置前/置顶后等 `FRONT_SETTLE_SECONDS`=200ms 再动；**松手后等 `CLICK_RESTORE_DELAY_SECONDS`=350ms 才还原光标，且必须分帧小步移回（`restore_cursor_smooth`），禁止一次 `SetCursorPos` 跳回** | 游戏按帧采样指针位置：一次跳跃 + 松手后立刻跳回别的显示器 → 处理这次点击的那一帧已经"指针不在窗口内"，点击被丢弃 | `test_click_moves_cursor_in_two_steps_before_press`、`test_click_waits_before_restoring_cursor`、`test_real_sender_keeps_cursor_when_restore_disabled`、`test_focus_settle_is_long_enough_for_the_game`、`test_activate_sleeps_for_the_focus_settle` |
| 6 | 滑动结束后**延迟 + 分帧**还原光标，禁止一次 `SetCursorPos` 跳回 | 画面继续乱飘（残留拖拽状态被算成大位移） | `test_real_sender_drag_waits_before_restoring_cursor`、`test_restore_cursor_smooth_moves_in_small_steps` |
| 7 | 每次真实输入前置顶/置前并回读复核；无法确保则**绝不输入** | 输入打到别的窗口 | `test_ensure_window_front_*`、`test_real_sender_refuses_input_when_window_cannot_be_focused` |
| 8 | **取景原点必须是客户区左上**（BitBlt 源点用 `client_area_offset`，PrintWindow 整窗渲染后裁剪） | 坐标整体偏下"标题栏高度" | `test_bitblt_renderer_starts_at_client_origin`、`test_printwindow_renderer_crops_client_area`、`test_client_area_offset_is_title_bar_plus_border` |
| 9 | 黑帧绝不能当成"未识别到目标"；纯色模板必须拒绝 | 报"未识别到目标"掩盖真因；纯色模板刷出一堆满分假坐标 | `test_capture_client_bgr_falls_back_on_blank_frame`、`test_load_template_rejects_flat_image`、`test_recognize_skips_flat_template` |
| 10 | 多尺度：**阈值必须在精修之后判断**；粗搜只在"越过峰值回落"后停 | 真实缩放（如 0.75x／3.50x）被漏掉或框小一圈 | `test_locate_scaled_finds_scale_between_coarse_steps`、`test_locate_scaled_stops_coarse_search_only_after_peak` |
| 11 | 两档搜索：先 0.3x–2.0x，落空才扩到 4.0x，第二档不重复扫第一档 | 命中慢一倍；或高倍缩放识别不到 | `test_default_scale_range_is_fast_then_extended`、`test_locate_scaled_fast_pass_does_not_touch_extended_range`、`test_locate_scaled_extended_pass_runs_when_fast_pass_misses` |
| 12 | 多模板：按顺序试、**先达到阈值的即用**、共用同一张截图、坏图跳过；一张模板命中多处全部列出且 `matches[0]` 为使用值 | 多截几次图（结果不一致）；坏图导致整批失败；只报第一处 | `test_recognize_uses_first_template_that_matches`、`test_recognize_captures_only_once_for_many_templates`、`test_recognize_lists_every_region_for_one_template` |
| 13 | 框选**只保存选区**；没选区不写文件也不关窗口 | 整屏被当模板存下来；点了保存却什么都没发生 | `test_save_button_writes_only_selected_region`、`test_save_button_without_selection_keeps_dialog_open`、`test_crop_flow_writes_only_selected_region` |
| 14 | 识别本身**不产生任何输入** | 只想看坐标却动了鼠标 | 全链路只用假 capture；`test_dry_run_channel_produces_no_real_input` |
| 15 | 开发者调试关闭时，调试页**所有**选项不生效（不发请求、开关改动回滚不写配置） | 误触真实输入 | `test_crop_request_is_rejected_when_developer_mode_off`、`test_debug_actions_are_rejected_when_developer_mode_off`、`test_debug_page_vision_annotate_switch_inert_without_developer_mode` |
| 16 | 所有页签继承 `ScrollablePage`；挂载/卸载调试页**不改变任何高度** | 打开调试页后所有页签高度变化、日志面板被挤 | `test_developer_tab_does_not_change_page_heights`、`test_measure_layout_reports_stable_heights`、`--measure-layout` |
| 17 | 配置 schema 变更必须 `+1` + 迁移函数 + 单测；未知版本原样不动 | 老配置字段被静默丢弃 | `tests/test_config/test_migrations.py` 全组 |
| 18 | 配置写入必须原子（临时文件 + `os.replace`），损坏文件能恢复 | 断电/异常后配置全丢 | `test_replace_failure_keeps_original`、`test_store.py` |
| 19 | 占位任务只允许"日志 + 心跳 + 响应停止"，禁止任何输入/读 params | 占位功能偷偷干活 | `test_placeholder_feature_tasks_do_not_touch_input_protocol` |
| 20 | 分层：`core` 不 import PySide6/win32；`automation` 不 import PySide6 | 层次崩坏、单测无法脱离 GUI | 第 ② 节的自检命令 |
| 21 | 构建产物（`dist/ build/ *.exe *.pyd *.dll *.zip`）不入库 | 仓库被几十 MB 二进制污染 | `test_no_build_artifacts_are_tracked`、`test_gitignore_covers_build_artifacts` |
| 22 | **同一件事只有一份**：模块级 import 不被同名赋值遮蔽；上限/范围常量只在 `core`/`config` 定义一处（界面导入它）；`PW_*` 只定义一处；测试夹具只有 `tests/gui_helpers.py` 一份；源文件与测试文件都 ≤ 600 行 | "改一处漏一处"：界面与校验各用一份常量 → 存得下、读不回来 | `tests/test_source_guards.py` 四条守卫（import 遮蔽 / 行数硬线 / `PW_*` 单一定义 / 调试页范围与 `core.debug` 同一对象） |

---

## ⑤ 常见症状排查

按当前症状检查对应条件；代码修改遵守 `AGENTS.md`，输入相关问题先核对日志与干跑结果。

| 症状 | 检查要点 | 相关位置 |
|---|---|---|
| 识别或框选坐标整体偏移、画面底部缺失 | 窗口 DC 源点为客户区偏移；PrintWindow 整窗渲染后裁客户区；结果统一用客户区坐标 | `automation/window.py`、`automation/vision.py`，第 ③ 节探针 |
| 点击无反应但日志显示完成 | 核对实测光标偏差、命中窗口、前台与置顶状态，以及两步移动、按下前等待、松手后平滑还原 | `_verify_before_press`、`_move_cursor_for_click`、`send_left_click` |
| 松手后画面继续移动或鼠标卡住 | 滑动尾部静止帧、每帧返回值、`finally` 释放、左键复查、延迟与平滑还原 | `automation/drag_path.py`、`automation/real_input.py` |
| 急停后按键仍按住 | 点击和长按切片检查停止事件，所有退出路径释放按键，组合键逆序释放修饰键 | `send_left_click`、`send_key_hold`、`send_key_combo` |
| 输入命中窗口外或其他控件 | 客户区范围、读尺寸失败是否跳过、实测光标容差、窗口置前复核 | `point_in_client_area`、`check_points_in_bounds`、`RealInputSender` |
| 输入失败后游戏仍置顶 | 置前失败与异常退出都取消本次设置的置顶，不清除外部置顶 | `_ensure_front_or_raise`、`ensure_window_front` |
| 模板大量满分命中或误选重复元素 | 纯色拒收、区域质量、匹配阈值、多模板顺序和本图试识别的重复位置；同图 1:1 结论不能保证正式匹配唯一 | `load_template`、`assess_region_quality`、`probe_region_on_image` |
| 放大或缩小后找不到模板，匹配框尺寸不准 | 两档搜索实际执行范围、精修后判断阈值、粗搜越过峰值后停止、候选面积约束 | `automation/multiscale.py` |
| 截图全黑、不可用或识别报取景失败 | 每条取景路径的黑帧与异常回退，屏幕取景前台条件，工具与游戏权限 | `capture_client_bgr`，第 ⑧ 节探针 |
| 窗口诊断截图和识别取景不一致 | 诊断复用同一取景链，生成真实 PNG 并校验黑帧 | `screenshot_client`、`capture_client_bgr` |
| 中文路径读不到图片 | 编码、`np.fromfile` + `cv2.imdecode`、配置路径换算与实际文件状态 | `load_template`、`utils/paths.py` |
| 保存模板失败、保存整屏或选区不可见 | 有效选区与最小尺寸、退化选区清理、手柄命中、当前选区用于裁剪、保存失败不关窗 | `CropView`、`save_selection`、`_discard_degenerate_selection` |
| 选区移动/缩放不准、键盘微调失效 | 图像与控件坐标换算、边界夹取、焦点、手柄几何与滑条 `NoFocus` | `crop_view.py`、`crop_view_zoom.py` |
| 滑条跳动、图像居中偏移、放大镜不跟鼠标 | 对数换算精确互逆、尺寸差居中、悬停重绘、缩放状态同步与 `blockSignals` | `zoom_slider_to_zoom`、`zoom_to_slider`、`_refresh_info` |
| 试识别结论与当前选区不一致、关窗卡住 | 结果区域与选区比对、结论失效、槽的线程身份、`ACTIVE_PROBES` 生命周期，不在 GUI `wait()` | `crop_dialog.py`、`gui/workers.py` |
| 模板列表移除影响其他选中项 | QListWidget 选择模式、移除目标与当前行状态 | 调试页模板列表与相关 GUI 测试 |
| 配置损坏后不能启动或保存后被恢复默认 | 迁移异常兜底、保存前校验、GUI 与校验器共用上限、非法字段提示 | `config/validation.py`、`config/store.py` |
| 程序版本低于配置时覆盖了新配置 | 更高 schema 只读，覆盖前备份 | `config/store.py` |
| 日志设置不生效或重复输出 | 加载后应用 `config.logging`、handler 幂等与参数变化时重建 | `setup_logging`、`gui/app.py` |
| 停止、运行状态或关窗表现异常 | 任务与调试互斥、所有相关线程接入停止、状态加锁、`try_transition`、资源释放 | `main_window.py`、`gui/workers.py`、`core/state.py` |
| F8 不可用 | 其他程序占用、权限、界面提示与重注册；使用停止按钮或调整热键 | `HotkeyRegistrar`、`show_hotkey_hint` |
| 改上限后一处允许、另一处拒绝 | import 遮蔽、常量重复定义、GUI 与配置校验共享同一对象 | `config/models.py`、`tests/test_source_guards.py` |
| 换电脑后路径守卫误报 | Git 路径转义配置，使用 `-c core.quotePath=false` | `tests/test_paths.py` |
| 打开调试页或换参考图后页签高度变化 | `ScrollablePage`、建议尺寸、日志最小高度、图片占位尺寸 | `gui/widgets.py`、`gui/layout_measure.py` |
| 日常参考图不更新或误删除文件 | 控制器信号、解码代次、GUI 写配置、删除确认、管理目录与共享引用保护 | `gui/daily_media.py`、`daily_workers.py`、`daily_files.py`、`daily_deletion.py` |

---

## ⑥ 当前限制与待实现功能

1. **识别尚未接入日常执行**：按图自动找建筑和完整日常动作未实现。实现时同步任务参数、配置结构、迁移和相关验收。
2. **多模板顺序影响结果**：采用第一张达标模板，相似模板可能先误命中；选择更有辨识度的区域并核对阈值。逐张比较后取全局最佳尚未实现。
3. **极小模板与小缩放信息不足**：少于约 40 px 的模板可能难以准确判断缩放，需核对结果与目标尺寸。
4. **使用识别底图匹配尚未实现**：`assets/screenshots/` 为识别底图素材目录，当前没有离线底图匹配入口。后续设计须明确以下约定：
   - 可复用 `recognize_in_window(..., capture=...)` 的截图注入点，不提前预埋空接口。
   - 底图以客户区尺寸与原点为准；整屏或缩放过的图片须先校准，不能直接将其坐标作为客户区坐标。
   - 保留黑帧、纯色模板、模板大于底图等校验。
5. **识别耗时随模板数量与搜索范围增加**：模板逐张匹配，全部落空时需完成各张搜索；运行期间禁用动作按钮，任务放后台线程。
6. **屏幕取景依赖前台**：窗口被遮挡时屏幕 BitBlt 不可用，其他路径也可能返回黑帧；全部失败时报告取景原因。
7. **权限须与游戏匹配**：工具权限不足时可能无法置前窗口，须拒绝输入并提示；提权流程见 `gui/elevation_flow.py` 与 `automation/elevation.py`。
8. **全局热键可能被占用**：注册失败在状态栏与设置页提示，停止按钮仍可用；设置热键后重新注册。
9. **调试识别参数为界面状态**：模板列表、阈值和最多结果条数不持久化，重启后重新设置。
10. **维护时检查模块长度**：源文件与测试文件均遵守 600 行上限，拆分按 `AGENTS.md`「模块拆分与维护」执行，更新测试替身与符号索引。

---

## ⑦ 测试结构与"注入缝"（写能抓住 bug 的测试）

### 夹具（`tests/conftest.py`）

- `_tests_always_run_in_dry_run`（autouse）：`AppConfig.default()` 的 `dry_run` 强制 True；
  需要看生产默认值的测试加 `@pytest.mark.real_defaults`。
- `_tests_never_query_real_desktop`（autouse）：`input_sender.find_window` 与 `core.vision.find_window`
  一律返回 None；需要窗口的测试自行 monkeypatch（覆盖夹具补丁）。

### 可注入的缝（monkeypatch 这些就能脱离真实环境）

| 缝 | 位置 | 用途 |
|---|---|---|
| `capture` 参数 | `core/vision.py:67 recognize_in_window(..., capture=fn)`、`capture_window(..., capture=fn)` | 喂假截图，零真实取景 |
| `find_window` / `is_window_ready` | `core/vision.py`、`automation/input_sender.py` | 假装有/没有窗口、最小化 |
| `_render_client_bits` | `automation/vision.py:143` | 主取景方式注入（黑帧/正常帧/抛错） |
| `_print_window` | `automation/vision.py:148` | 替换 ctypes 调用（假 GDI 测试用） |
| 假 GDI | `tests/test_automation/test_vision_capture.py:118-198`（`CLIENT_OFFSET`:123 / `_window_pixels`:126 / `_expected_client_pixels`:135 / `_FakeBitmap`:141 / `_FakeDC`:158 / `fake_gdi`:192） | **验证取景几何**：位图里存真实像素，断言 BitBlt 源点、裁剪结果像素 |
| `build_channel` / 假 sender | `automation/input_sender.py:575`、`tests/test_automation/real_input_helpers.py` 的 `recording` 夹具 | 断言输入调用序列，零真实输入 |
| 假 `user32` | `tests/test_automation/real_input_helpers.py` 的 `user32` 夹具 | 断言 `SendInput`/`SetCursorPos` 序列、置顶/还原行为 |
| `get_debug_dir` | `core/vision.py` 导入处 | 带框截图写进 tmp |
| `TemplateCropDialog` | `gui/main_window.py:473` 调用处 | 替换对话框或子类化 `exec()` 模拟"框选 + 保存" |

### 几何测试示例

```python
# 1) 纯函数级：把几何换算钉死
monkeypatch.setattr(window.win32gui, "GetWindowRect", lambda hwnd: (86, 0, 1704, 1070))
monkeypatch.setattr(window.win32gui, "ClientToScreen", lambda hwnd, point: (95, 37))
assert window.client_area_offset(123) == (9, 37)      # 标题栏 + 边框

# 2) GDI 级：假 DC 真的搬像素，断言"从哪取"和"取到哪"
width, height, bits = vision._render_client_bits_bitblt(hwnd)
assert calls[-1][2] == (9, 37)                        # 源点必须是客户区偏移
assert not np.array_equal(bgr, window_pixels[:h, :w, :3])   # 不能是窗口左上角那块

# 3) 实机交叉验证（见第 ⑧ 节脚本）：识别坐标 vs 整屏定位换算坐标，偏差必须 ≤3px
```

---

## ⑧ 诊断命令与实机探针

### 命令速查

| 命令 | 作用 | 判读 |
|---|---|---|
| `--version` | 版本 | — |
| `--validate-config` | 配置迁移+校验 | 打印 `OK` |
| `--smoke-gui` | 离屏建窗 | 日志含"离屏冒烟完成" |
| `--measure-layout` | 页签高度稳定性 | 末行 `结论：…不改变任何高度…[OK]` |
| `--recognize 图 [图…] [--threshold] [--max-results] [--no-annotate] [--no-scale]` | 识别 | 退出码 0/1/2；输出含"模板：…（第 k/N 张）"与每处命中坐标 |

### 探针 1：窗口几何 + 取景原点（只读，最有用）

```powershell
# 请先在仓库根目录打开 PowerShell
.\.venv\Scripts\python.exe -c @"
# 取景几何探针：确认客户区偏移与取景原点（只读，不产生任何输入）
import ctypes, json, pathlib, sys
sys.path.insert(0, 'src')
import win32gui
from luoluotool.automation import vision as av
from luoluotool.automation.window import client_area_offset, find_window, get_client_rect
ctypes.windll.user32.SetProcessDPIAware()
cfg = pathlib.Path('user_data/config.json')
if not cfg.exists():
    raise SystemExit('missing user_data/config.json - start the GUI once first')
keyword = json.loads(cfg.read_text(encoding='utf-8'))['automation']['window_title_keyword']
hwnd = find_window(keyword)
print('hwnd             =', hwnd)
if hwnd is None:
    raise SystemExit('game window not found - is it running windowed?')
print('window rect      =', win32gui.GetWindowRect(hwnd))
print('client rect      =', get_client_rect(hwnd))
print('client origin    =', win32gui.ClientToScreen(hwnd, (0, 0)))
print('client offset    =', client_area_offset(hwnd), '<- title bar + border = capture origin')
img = av.capture_client_bgr(hwnd)
print('capture          = %dx%d  std=%.2f' % (img.shape[1], img.shape[0], img.std()))
"@
```

期望：`client offset` 为当前窗口的客户区偏移；取景图像的 (0,0) 必须对应
`client origin`（用探针 2 或 3 验证）。

### 探针 2：逐条取景路径量偏移（找出是哪一条错）

思路：`_render_client_bits_printwindow(hwnd, flag)` / `_render_client_bits_bitblt(hwnd)` /
`_render_client_bits_screen(hwnd)` 各抓一张 → 用 `cv2.matchTemplate` 在一张**整屏截图**里定位图像里
一块纹理区域 → 反推"图像左上角在屏幕上的位置" → 与 `ClientToScreen(0,0)` 比较。
`is_blank_frame` 为 True 的路径直接标"不可用（黑帧）"。

### 探针 3：坐标端到端交叉验证（判断"坐标可信"）

```powershell
# 请先在仓库根目录打开 PowerShell
.\.venv\Scripts\python.exe -c @"
# 坐标交叉验证：识别出的客户区坐标 vs 整屏定位换算值，偏差必须 <=3px（只读）
import ctypes, json, pathlib, sys
sys.path.insert(0, 'src')
import cv2
import win32con, win32gui, win32ui
from luoluotool.automation import vision as av
from luoluotool.automation.window import find_window
ctypes.windll.user32.SetProcessDPIAware()
cfg = pathlib.Path('user_data/config.json')
if not cfg.exists():
    raise SystemExit('missing user_data/config.json - start the GUI once first')
keyword = json.loads(cfg.read_text(encoding='utf-8'))['automation']['window_title_keyword']
hwnd = find_window(keyword)
if hwnd is None:
    raise SystemExit('game window not found')
origin = win32gui.ClientToScreen(hwnd, (0, 0))
frame = av.capture_client_bgr(hwnd)
h, w = frame.shape[:2]
if h < 600 or w < 800:
    raise SystemExit('window too small for this probe: %dx%d' % (w, h))
tmpl = frame[300:560, 500:800].copy()      # self-cropped template: independent of game state
m = av.locate_best_scaled(frame, tmpl, threshold=0.85)
if m is None:
    raise SystemExit('recognition missed - try another crop region')
scaled = cv2.resize(tmpl, (int(round(tmpl.shape[1] * m.scale)), int(round(tmpl.shape[0] * m.scale))))
dc = win32gui.GetDC(0)
sx = ctypes.windll.user32.GetSystemMetrics(0)
sy = ctypes.windll.user32.GetSystemMetrics(1)
src = win32ui.CreateDCFromHandle(dc)
mem = src.CreateCompatibleDC()
bmp = win32ui.CreateBitmap()
bmp.CreateCompatibleBitmap(src, sx, sy)
mem.SelectObject(bmp)
mem.BitBlt((0, 0), (sx, sy), src, (0, 0), win32con.SRCCOPY)
screen = av._bits_to_bgr(sx, sy, bmp.GetBitmapBits(True))
s = av.locate_best(screen, scaled, threshold=0.5)
if s is None:
    raise SystemExit('target not found on screen - window covered?')
expected = (s.center[0] - origin[0], s.center[1] - origin[1])
print('recognized client center =', m.center)
print('screen-derived center    =', expected)
print('delta                    =', (m.center[0] - expected[0], m.center[1] - expected[1]))
print('verdict                  =', 'OK' if max(abs(m.center[0] - expected[0]), abs(m.center[1] - expected[1])) <= 3 else 'NG')
"@
```

期望：`delta = (0, 0)`，偏差 ≤3px 可接受。

> **编码注意**：上面两个探针的**字符串字面量全是 ASCII**，窗口标题从 `user_data/config.json` 读，
> 所以无论是粘到终端还是存成 `.ps1` 都不会炸。**但如果你要存成 `.ps1`，请存成 UTF-8 with BOM**
> —— Windows PowerShell 5.1 会把不带 BOM 的文件按 ANSI/GBK 读，脚本里的中文会全变乱码
> 直接粘贴到终端也可运行。

> **正常噪音**：探针跑起来会在 **stderr** 里带日志行（例如 `PrintWindow 取到纯色/黑帧…`、
> `取景(BitBlt 窗口DC)：从客户区左上 (9, 37) 抓取…`）。PowerShell 会把它显示成红字错误记录，
> 这是日志不是异常；判读只看脚本自己 print 的那几行。

### 日志与产物位置

| 内容 | 路径 |
|---|---|
| 日志 | `logs/luoluotool.log` |
| 识别带框截图 | `user_data/debug/vision_<时间戳>.png`（整屏 + 画框，每处命中一个编号） |
| 窗口诊断截图 | `user_data/debug/window_<时间戳>.png` |
| 框选产物 | `assets/anchors/`：调试页 `anchor_<时间戳>.png`、日常任务页 `{建筑}_岛屿{N}_<时间戳>.png`（**不入库**） |
| 识别图片 | `assets/templates/*.png`（用户自己整理，**入库**；调试页「添加图片…」默认打开它） |
| 识别底图 | `assets/screenshots/*.png`（用工具自带截图功能截的画面，**不入库**；"用底图识别"功能待实现） |
| 配置 | `user_data/config.json`（当前 schema v11；损坏会自动备份恢复并在日志说明） |

---

## ⑨ 红线与规范速查（改代码前必看）

1. **项目边界**：不读写游戏进程内存，不拦截或伪造封包，不上传本地数据；新增输入通道、系统级操作
   或联网功能须先明确范围并取得用户确认（见 `PROJECT_SPEC.md`「项目边界与安全」「远程配置计划」）。
2. **禁止**：把 `user_data/config.json`、日志、截图、构建产物提交入库；force push；删除/破坏既有
   测试来让测试变绿；吞异常（`except: pass` / `except Exception: continue`）。
3. **提交规范**：Conventional Commits + 中文说明 + 范围前缀（`fix(automation): …`）。一次提交只做一件事。
   包含代码修改时，提交前全量测试通过，并检查无未使用 import、无调试 print；仅文档等非代码修改不执行测试。
   所有提交都要核对变更文件与目标一致。
4. **构建**：**只在用户明确要求时**跑 `packaging\build.ps1`（需 PowerShell，文件必须带 UTF-8 BOM）。
   产物不入库，守卫测试扫描 git 索引。
5. **文件长度**：>400 行考虑拆分，>600 行必须拆分。
6. **编码**：Python 3.11+、UTF-8、4 空格、公共函数全类型注解；配置用 dataclass；JSON 原子写。
7. **可观测**：关键动作写日志；异常记录完整堆栈；GUI 里禁止 sleep/忙等。
8. **新增依赖**：改 `requirements.txt` 并在提交信息说明理由与体积代价（当前 numpy + opencv-python-headless）。

---

## 附：快速定位索引（常用符号 → 文件:行）

| 符号 | 位置 | 说明 |
|---|---|---|
| `recognize_in_window` | `core/vision.py:68` | 识别编排（多模板顺序尝试 + 多区域） |
| `_success_result` | `core/vision.py:171` | 命中消息（哪张模板、使用值、上限提示） |
| `capture_window` | `core/vision.py:213` | 供框选用的截图（含就绪校验） |
| `locate_all_scaled` | `automation/multiscale.py:169` | 两档多尺度匹配主流程 |
| `_scale_tiers` | `automation/multiscale.py:104` | 档位拆分（0.3–2.0 → 0.3–4.0） |
| `_scan_coarse` / `_refine_scale` | `automation/multiscale.py:116` / `:149` | 粗搜（峰值回落才停）/ 精修 |
| `load_template` | `automation/template_match.py:183` | 读图（中文路径 + 纯色拒绝） |
| `is_blank_frame` | `automation/template_match.py:74` | 黑帧/纯色判定 |
| `capture_client_bgr` | `automation/vision.py:59` | 取景入口（含回退链） |
| `_render_client_bits_bitblt` | `automation/vision.py:212` | **BitBlt 路径（源点必须客户区偏移）** |
| `_render_client_bits_printwindow` | `automation/vision.py:156` | PrintWindow（整窗渲染 + 裁剪） |
| `client_area_offset` | `automation/window.py:80` | 客户区在窗口内的偏移（唯一真源） |
| `screenshot_client` | `automation/window.py:94` | 窗口诊断截图（走取景回退链 → 真 PNG + 黑帧检测） |
| `build_channel` | `automation/input_sender.py:575` | 干跑/真实通道选择 |
| `point_in_client_area` / `check_points_in_bounds` | `automation/input_sender.py:516` / `:531` | 越界校验 |
| `RealInputSender.click_at` / `drag` | `automation/input_sender.py:42` / `:46` | 真实输入的校验与还原策略（`click_at(..., hold_seconds=None)`＝点击时长；协议里的同名方法在 `:42`/`:46`） |
| `_move_cursor_for_click` / `_verify_before_press` | `automation/input_sender.py:237` / `:259` | 两步移动（hover）/ 点击前核对事实（漂移>4px 跳过） |
| `_restore_cursor_after_click` / `_restore_cursor_after_drag` | `automation/input_sender.py:218` / `:360` | 延迟 + 分帧小步还原光标（点击/滑动同一套做法） |
| `CLICK_CURSOR_TOLERANCE_PX` / `CLICK_MOVE_STEP_SECONDS` / `CLICK_RESTORE_DELAY_SECONDS` | `automation/input_sender.py:26` / `:27` / `:28` | 4px / 30ms / 350ms（输入时间线三档） |
| `INPUT_SETTLE_SECONDS` / `FRONT_SETTLE_SECONDS` | `automation/real_input.py:69` / `:70` | 80ms（按下前）/ 200ms（置前后） |
| `send_left_click` | `automation/real_input.py:344` | 点击原语：按下 → 按住（切片检查急停）→ **finally 抬起** |
| `window_under_point` / `describe_window` | `automation/real_input.py:166` / `:184` | 命中测试与窗口描述（诊断"点击落在谁身上"） |
| `run_single_click` | `core/debug.py:98` | 单点测试动作（`hold_ms`：None＝引擎默认 / 0＝瞬时） |
| `_validate_click_hold` | `core/debug.py:56` | 点击时长校验（0–5000 ms，整数、非布尔） |
| `single_hold_spin` / `repeat_hold_spin` | `gui/pages/debug.py:203` / `:230` | 调试页「点击时长」控件（单点 + 连点，默认 40 ms，经 `hold_ms` 下发） |
| `restore_cursor_box` | `gui/pages/debug.py:109` | 还原光标开关（受开发者调试门禁） |
| `settings_page.developer_box` | `gui/pages/settings.py:48` | 设置页「开发者调试」开关（决定调试页是否挂载/生效） |
| `show_hotkey_hint` | `gui/pages/settings.py:89` | 设置页红字提示（急停热键不可用等） |
| `run_repeat_click` | `core/debug.py:124` | 连点测试动作（同样支持 `hold_ms`；间隔＝点击之后的等待，可被急停打断） |
| `ensure_window_front` | `automation/real_input.py:237` | 每次输入前置顶置前 + 复核（失败时只取消**本次我们设的**置顶） |
| `client_to_screen` | `automation/real_input.py:157` | 客户区→屏幕换算（点击路径） |
| `build_drag_path` | `automation/drag_path.py:49` | 缓出曲线 + 末尾静止帧 |
| `restore_cursor_smooth` | `automation/real_input.py:397` | 分帧还原光标 |
| `CropView` / `TemplateCropDialog` | `gui/dialogs/crop_view.py:66` / `gui/dialogs/crop_dialog.py:105` | 框选几何与保存 |
| `hit_test` / `_apply_move` / `_apply_resize` | `gui/dialogs/crop_view.py:206` / `:218` / `:230` | 选区命中判定 / 整体移动 / 拖手柄改大小（Alt＝中心对称缩放） |
| `drag_bubble_text` / `_paint_dim_mask` | `gui/dialogs/crop_view.py:396` / `:590` | 拖拽尺寸气泡/ 选区外压暗 |
| `keyPressEvent`（框选）/ `_nudge_edge` | `gui/dialogs/crop_view.py:445` / `:507` | 方向键微调 / Ctrl 调单边 |
| `image_rect` / `_set_zoom` / `wheelEvent` | `gui/dialogs/crop_view_zoom.py:42` / `:108` / `:149` | 图像显示矩形（缩放+平移）/ 以鼠标为锚点缩放 / 滚轮缩放 |
| `magnifier_rect` / `magnifier_source_rect` | `gui/dialogs/crop_view_zoom.py:160` / `:177` | 放大镜位置（贴鼠标、靠边翻转）/ 取样区域（夹在图像内） |
| `zoom_slider` / `zoom_reset_button` | `gui/dialogs/crop_dialog.py:150` / `:164` | 缩放滑条（相对整图适配 50%–800%）/ 「重置」按钮 |
| `zoom_slider_to_zoom` / `zoom_to_slider` | `gui/dialogs/crop_dialog.py:81` / `:98` | 滑条刻度换算（对数：每 1/4 行程翻一倍，互为反函数）|
| `reset_all` / `_sync_zoom_controls` | `gui/dialogs/crop_dialog.py:282` / `:269` | 重置（视图归位 + 清空选区）/ 缩放状态同步回滑条 |
| `clear_selection` | `gui/dialogs/crop_view.py:131` | 清空选区（双击 / Esc / 重置共用）|
| `zoom_relative_percent` / `set_zoom_relative` | `gui/dialogs/crop_view_zoom.py:60` / `:68` | 相对整图适配的缩放百分比 / 按倍数设置（锚点＝选区中心）|
| `selection_quality` / `selection_text` | `gui/dialogs/crop_dialog.py:224` / `:236` | 可辨识度评估（`RegionQuality`）/ 信息行文案（含辨识度） |
| `view_status_text` | `gui/dialogs/crop_dialog.py:409` | HUD 文字：缩放倍率 + 鼠标客户区坐标 |
| `_on_save_clicked` / `save_selection` | `gui/dialogs/crop_dialog.py:418` / `:445` | **只保存选区**；纯色（`flat`）时拒绝保存 |
| `assess_region_quality` / `RegionQuality` | `automation/template_match.py:101` / `:85` | 模板区域可辨识度（对比度 + 边缘占比；`flat` 拒存，`low` 只提示） |
| `probe_region_on_image` / `TemplateProbeResult` | `core/vision.py:288` / `:253` | **「在本图试识别」**：选区当模板在同图 1:1 试匹配；`duplicates`＝除自己以外的命中数 |
| `run_probe` / `probe_thread` | `gui/dialogs/crop_dialog.py:309` / `:296` | 试识别入口（纯色短路 / 禁用按钮 / 起线程）/ 当前线程（关窗交由 `ACTIVE_PROBES` 持有至结束） |
| `TemplateProbeThread` | `gui/workers.py:140` | 试识别后台线程（匹配是 CPU 密集的，不许放 GUI 线程） |
| `set_probe_rects` / `_paint_probe_rects` | `gui/dialogs/crop_view.py:564` / `:576` | 把试识别命中的**其它**位置画成橙框 + 序号（图像像素坐标） |
| `DebugPage` | `gui/pages/debug.py:68` | 调试页（识别入口/模板列表/点击时长/干跑/测试按钮） |
| `AboutPage` | `gui/pages/about.py:79` | 「关于」页（风险/隐私声明、第三方许可、运行环境、复制诊断、打开目录） |
| `diagnostics_text` | `gui/pages/about.py:222` | 可复制的诊断信息（只含版本与环境，不含日志/截图内容） |
| `_on_debug_test` / `run_debug_action` | `gui/main_window.py:476` / `gui/workers.py:69` | 调试请求接收 / 动作分发（含 `hold_ms`） |
| `_on_capture_ready` / `_on_crop_requested` | `gui/main_window.py:517` / `:553` | 框选回填 / 框选入口（门禁 + 后台截图） |
| `_debug_actions_allowed` | `gui/main_window.py:468` | 开发者调试门禁 |
| `_register_hotkey_or_hint` | `gui/main_window.py:281` | 热键注册 + 失败显著提示 |
| `_wait_for_threads` | `gui/main_window.py:232` | 关窗处理任务、调试与日常媒体线程 |
| `measure_layout` / `format_measure_report` | `gui/layout_measure.py:170` / `:238` | 布局测量与报告 |
| `Runner.start` | `core/runner.py:86` | 任务顺序执行/循环/失败计数 |
| `try_transition` | `core/state.py:46` | 状态迁移（非法迁移返回 False 不抛；读写加锁） |
| `ConfigSaveError` | `config/store.py:15` | 保存前校验失败（磁盘文件保持原样） |
| `MAX_KEY_STEPS` / `MAX_CLICK_POINTS` | `config/models.py:12` / `:14` | 按键/滑动/点击点上限 20（界面与校验器共用） |
| `migrate` / `validate` | `config/validation.py:386` / `:416` | 迁移链（每步独立 try，绝不崩）与校验 |
| `setup_logging` | `utils/logging_setup.py:13` | 幂等日志初始化（按配置重建 handler） |
| `get_templates_dir` / `get_screenshots_dir` / `get_anchors_dir` | `utils/paths.py:65` / `:55` / `:45` | 识别图片（`templates`，**入库**）/ 识别底图（`screenshots`，不入库）/ 框选产物（`anchors`，不入库） |
| `prepare_for_match` | `automation/template_match.py:196` | 匹配前的灰度预处理（`multiscale` 共用） |
| `_on_vision_add_clicked` | `gui/pages/debug.py:468` | 「添加图片…」对话框默认打开 `assets/templates` |
| `PlannedFeaturePage` | `gui/pages/planned_feature.py:14` | 功能三/功能四公共基类 |
| `ease_out_quad` / `interpolate_points` | `automation/drag_path.py:22` / `:27` | 滑动缓出曲线 / 分帧插值（纯函数） |
| `scale_candidates` | `automation/multiscale.py:45` | 粗搜档位生成（按步长枚举比例） |
| `locate_best_scaled` | `automation/multiscale.py:225` | 多尺度取最佳命中（无命中返回 None） |
| `annotate` / `save_image` | `automation/vision.py:299` / `:313` | 带框截图 / 存图（中文路径用 imencode+tofile） |
| `run_debug_action` | `gui/workers.py:69` | 调试动作分发（线程体调用，含 `hold_ms`） |
| `_RunnerThread` / `_DebugTestThread` | `gui/workers.py:30` / `:41` | 任务线程 / 调试测试线程（可被停止请求中断） |
| `_CaptureThread` / `_DiagnoseThread` | `gui/workers.py:100` / `:122` | 框选前截图线程 / 窗口诊断线程 |
| `load_window_icon` / `_is_valid_icon_file` | `gui/icons.py:36` / `:25` | 窗口图标加载（魔数校验 + 降级为空图标） |
| `ElevationFlowMixin` | `gui/elevation_flow.py:29` | 提权流程 mixin（`MainWindow` 继承；monkeypatch 目标是本模块） |

> **索引自检**：改完代码后跑 `.venv\Scripts\python tools\check_guide_index.py` —— 它会逐条核对本表
> 的"符号 → 文件:行"是否还指得准（漂移会打印 `[DRIFT] 符号 文件:行 当前指向…` 并以退出码 1 结束）。
> 行号漂移的索引比没有索引更误导人，所以改代码后顺手跑一下。

---

## 附：给排查者的三个建议

1. **先跑不变量表**（第 ④ 节）：对每条问一句"如果我把它破坏掉，哪个测试会红？"——没有测试红的条目
   就是最可能有真 bug 的地方。
2. **优先检查坐标系、线程与资源释放**：核对坐标换算、跨线程控件访问、停止事件与 finally 清理。
3. **实机问题先取诊断数据再改代码**：用第 ⑧ 节探针核对客户区原点、取景路径与识别中心偏差，区分环境限制和代码问题。
