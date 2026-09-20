# BUG_HUNT_GUIDE.md — LuoLuoTool 排查手册（给"找 bug 的工程师"）

> **用途**：让另一位工程师（或另一个 AI 会话）在**不熟悉本项目**的前提下，能在 15 分钟内跑起来、
> 30 分钟内知道"哪里最容易藏 bug"，并且**每条不变量都能立刻验证**。
>
> **基线**：`git HEAD = 9aea9a9`（2026-09-20），全量测试 468 passed，工作区干净。
> 本文件自身的提交**不改任何代码**，因此下面所有 `文件:行` 对当前 `src/**` 依然有效。
> **行号会漂移**：代码改动后用**符号名**搜索定位（第 ⑩ 节的索引表可直接搜符号）。
> 改完代码请顺手跑 `.venv\Scripts\python tools\check_guide_index.py` 自检索引是否还准。
> **维护约定**：改了代码就回来更新对应小节（尤其是第 ③④⑤ 节），否则本文档会变成误导。
>
> 配套文档：`AGENTS.md`（开发规范/红线，**必读**）、`PROJECT_SPEC.md`（边界与功能表）、
> `CHECKLIST.md`（逐项勾选清单）、`PHASE_PROMPTS.md`（分阶段记录）、`README.md`（用户视角）。

---

## ① 15 分钟上手

### 环境

```powershell
# 解释器与依赖（已存在）
D:\deepSeekHarness\LuoLuoTool\.venv\Scripts\python.exe
# 依赖：PySide6 6.11.2 / pywin32 312 / numpy 2.5.3 / opencv-python-headless 5.0.0 / pytest 9.1.1
```

### 四条廉价验收命令（改动后必跑，全绿才算过）

```powershell
# 建议先固定临时目录（本机曾因默认 tmp 出现怪问题；不设也能跑）
$env:TMP='D:\deepSeekHarness\.tmp'; $env:TEMP=$env:TMP

cd D:\deepSeekHarness\LuoLuoTool
.\.venv\Scripts\python.exe -m pytest -q                    # 全量单测（约 25s）
.\.venv\Scripts\python.exe -m luoluotool --validate-config  # 配置校验，应打印 OK
.\.venv\Scripts\python.exe -m luoluotool --smoke-gui        # 离屏建窗，日志含"离屏冒烟完成"
.\.venv\Scripts\python.exe -m luoluotool --measure-layout   # 页签高度稳定性，末行须为 "[OK]"
```

### 三条实机命令（需要游戏窗口；**不产生任何输入**）

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
   （`Get-Content -Raw | Set-Content` 在 PS 5.1 下按 GBK 读 UTF-8，曾把 `PROJECT_SPEC.md` 679 行写坏）。

### 目录一览（行数为基线实测）

```
src/luoluotool/
  __main__.py                203  CLI：--version/--validate-config/--smoke-gui/--measure-layout/--recognize
  automation/                      自动化层（不许 import PySide6）
    vision.py                642  ⚠超 600 硬线：模板匹配 + 多尺度 + 取景
    input_sender.py          435  InputSender 协议 / DryRunSender / RealInputSender / 越界校验 / build_channel
    real_input.py            562  SendInput 底层：置顶置前、点击、滑动路径、按键、光标还原
    window.py                207  找窗口、置前、客户区几何、诊断截图
    elevation.py              76  权限检测 / 以管理员重启
    hotkey.py                 72  F8 急停热键（RegisterHotKey）
  config/                        配置层（dataclass + 原子 JSON + 迁移校验）
    models.py                402  AppConfig / AutomationConfig / 任务参数解析（键序列、滑动序列）
    validation.py            357  migrate() + validate()，_MIGRATIONS {1..8}，SCHEMA_VERSION = 9
    store.py                  65  save/load/_recover（原子写 + 损坏恢复）
  core/                          业务编排层（不许 import PySide6/win32）
    vision.py                248  recognize_in_window（多模板/多区域编排）
    debug.py                 148  调试动作：单点/连点/滑动/键盘（复用正式通道）
    runner.py                174  Runner：顺序执行任务、循环、失败计数、停止
    registry.py              147  任务注册表 + 占位任务（order_hold/feature_3/feature_4）
    task.py / state.py        67/33  TaskContext/TaskResult/BaseTask；RunState 状态机
  gui/                           界面层（只做绑定与展示）
    main_window.py           695  ⚠超 600 硬线：主窗口 + 4 个后台线程 + 动作分发 + 提权流程
    pages/debug.py           380  开发者调试页（识别入口/模板列表/干跑/测试按钮）
    pages/settings.py        132  设置页（含开发者调试开关）
    pages/daily.py           171  日常任务页（任务勾选、点击序列）
    pages/order_hold.py       56  卡订单页
    pages/feature3.py,4.py    35  功能三/四页（占位）
    dialogs/crop_dialog.py   271  框选截图生成模板（CropView + TemplateCropDialog）
    layout_measure.py        283  --measure-layout 的测量与报告（ASCII 安全）
    widgets.py                54  LogPanelHandler（日志进面板）；ScrollablePage（页签基类）
    app.py                    63  入口：QApplication、任务栏图标身份、smoke 模式
  utils/                         keys.py(72) paths.py(42) logging_setup.py(33)
tests/                           与 src 同构；conftest.py 全局夹具；test_packaging.py 守卫构建红线
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
- 一条命令自检（基线应输出 `layer check violations = 0`）：

```powershell
cd D:\deepSeekHarness\LuoLuoTool
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
调试页「图片识别匹配测试」          gui/pages/debug.py:380   _on_vision_clicked()
  → 发信号 test_requested("vision", {images, threshold, max_results})
主窗口分发                          gui/main_window.py:495  _on_debug_test()
  后台线程 _DebugTestThread.run     gui/main_window.py:116  （不阻塞 GUI）
  动作映射                          gui/main_window.py:144  run_debug_action(kind="vision")
业务编排                            core/vision.py:67       recognize_in_window()
  ① 归一化模板列表                  core/vision.py:58       _template_paths()
  ② 找窗口 + 就绪校验               core/vision.py:71-79    find_window / is_window_ready
  ③ 取景（只截一次，多模板共用）    automation/vision.py:393 capture_client_bgr()
  ④ 逐张模板多尺度匹配              automation/vision.py:308 locate_all_scaled()
  ⑤ 组织消息/带框截图               core/vision.py:170       _success_result()
结果回传                            Signal finished_message → 调试页状态栏
```

**框选生成模板**链路：

```
调试页「框选截图生成模板」          gui/pages/debug.py:133   crop_button → crop_requested 信号
主窗口门禁 + 后台截图               gui/main_window.py:556   _on_crop_requested()
  截图线程                          gui/main_window.py:175   _CaptureThread → core/vision.py:212 capture_window()
  弹框（GUI 线程）                  gui/main_window.py:529   _on_capture_ready() → TemplateCropDialog
  拖拽框选                          gui/dialogs/crop_dialog.py:45   CropView
  保存（**只存选区**）              gui/dialogs/crop_dialog.py:233  _on_save_clicked() → save_selection():249
  加入模板列表                      gui/main_window.py:542   debug_page.add_vision_template()
```

### 主链路 C：鼠标单点 / 连点（含"点击时长"）

```
调试页「鼠标单点测试」              gui/pages/debug.py:170   single_hold_spin（点击时长，ms）
调试页「鼠标连点测试」              gui/pages/debug.py:197   repeat_hold_spin（连点每次都用它）
  → _on_single_clicked / _on_repeat_clicked 发信号 test_requested(kind, {...})
    载荷：single {x, y, hold_ms}｜repeat {x, y, count, interval_ms, hold_ms}
主窗口分发                          gui/main_window.py:144   run_debug_action
业务编排（单点）                    core/debug.py:80         run_single_click(hold_ms=...)
业务编排（连点）                    core/debug.py:106        run_repeat_click(..., hold_ms=...)（间隔＝点击之后的等待）
校验                                core/debug.py:55         _validate_click_hold（0–5000 ms 整数）
通道（干跑/真实）                   automation/input_sender.py:425 build_channel
  点击                              input_sender.py:146      RealInputSender.click_at(x, y, hold_seconds)
                                    input_sender.py:84       DryRunSender.click_at（只写日志，同样校验越界）
底层原语                            automation/real_input.py:301 send_left_click(sleep, hold_seconds, stop_event)
  按下 → 按住（CLICK_SLICE_SECONDS=50ms 切片查急停）→ **finally 抬起左键**
```

### 主链路 B：任务执行与输入注入

```
日常任务页/卡订单页勾选 → 任务进队列（core/registry.py 注册表）
主窗口「启动」                      gui/main_window.py:387   _start()
  真实模式确认弹窗                  gui/main_window.py:409   _real_mode_warning_text()/_confirm_real_mode()
  运行线程 _RunnerThread            gui/main_window.py:102
  Runner 顺序执行                   core/runner.py:65        Runner.start()
    每个任务拿到 TaskContext（含 sender）core/task.py:15
    输入通道构建                    automation/input_sender.py:425 build_channel()
      ├─ 干跑：DryRunSender（:50，只写日志，**同样做越界校验**）
      └─ 真实：WindowReadinessGate(:318) → RealInputSender(:114)
           点击/滑动前校验              input_sender.py:366/381 point_in_client_area / check_points_in_bounds
           每次输入前置顶/置前并复核    automation/real_input.py:194 ensure_window_front()
           客户端→屏幕换算              automation/real_input.py:148 client_to_screen()
           实际注入                     automation/real_input.py:257 _send()（SendInput）
    停止/F8 急停                     gui/main_window.py:432/458 _stop()/_on_failsafe() → stop_event
```

### 线程模型（bug 高发区）

| 线程 | 位置 | 约束 |
|---|---|---|
| GUI 主线程 | `gui/**` | **禁止** sleep/忙等/同步截图；所有长任务进 QThread |
| 运行线程 `_RunnerThread` | `main_window.py:102` | 只发信号回 GUI，不直接改控件 |
| 调试测试线程 `_DebugTestThread` | `main_window.py:116` | 执行期间禁用按钮；可被 `request_stop()` 中断 |
| 截图线程 `_CaptureThread` | `main_window.py:171` | 框选前截图，完成后发 `captured` |
| 诊断线程 `_DiagnoseThread` | `main_window.py:193` | 窗口诊断 |

**找 bug 时优先怀疑**：跨线程直接操作控件、`stop_event` 没有切片检查、`finally` 里漏了资源释放或状态回滚。

---

## ③ 坐标系与几何（本项目最容易出 bug 的地方）

### 三套坐标

| 坐标 | 定义 | 谁在用 |
|---|---|---|
| **客户区坐标** | 游戏窗口客户区左上角为 (0,0)，范围 `[0,width)×[0,height)` | **识别结果、框选选区、点击/滑动入参**，全项目统一用它 |
| 窗口坐标/屏幕坐标 | Windows 原生坐标 | 只在 `client_to_screen` / `ClientToScreen` 处出现 |

- 客户区左上角在屏幕上的位置：`win32gui.ClientToScreen(hwnd, (0, 0))`。
- **客户区在窗口内的偏移**：`automation/window.py:87 client_area_offset(hwnd)` =
  `ClientToScreen(0,0) - GetWindowRect左上角` = 标题栏高度 + 边框宽度。
  实测本作窗口 1618×1070 / 客户区 1600×1024 → **(9, 37)**；无边框全屏窗口为 (0, 0)。

### 三条必须记住的几何事实（都踩过）

1. **窗口 DC（`GetWindowDC`）与 `PrintWindow` 的原点都是"窗口左上角"**（含标题栏）。
   取景必须以客户区偏移为源点/裁剪原点，否则抓到"标题栏 + 客户区上半部分"，
   画面底部缺"标题栏高度"一截，**识别坐标整体偏下标题栏高度**（实测 37px）。
   → `_render_client_bits_bitblt` 的 BitBlt 源点、`_render_client_bits_printwindow` 的整窗渲染+裁剪。
2. **屏幕 BitBlt 用 `ClientToScreen(0,0)` 作源点，天然以客户区左上为原点**，不需要再偏移/裁剪
   （`automation/vision.py:577`，它是"原点正确"的参照实现）。但它要求**窗口确实在前台**，
   否则会抓到被遮挡窗口的内容，因此调用方有前台门禁（`vision.py:433`）。
3. **窗口尺寸会变**：客户区实测过 1920×1052 与 1600×1024 两种。任何"写死 1920×1052"的假设
   都是潜在 bug；坐标/尺寸一律运行时读取。

### 取景回退链（本作实测：PrintWindow 两种 flag 都返回纯黑帧）

```
capture_client_bgr (vision.py:393)
  └─ _render_client_bits = PrintWindow(PW_RENDERFULLCONTENT)   ← 本作黑帧
     is_blank_frame() → 纯色/黑帧?
     └─ _render_client_bgr_fallback (vision.py:433)
          ├─ PrintWindow(PW_CLIENTONLY)      ← 本作黑帧
          ├─ BitBlt(窗口DC)                  ← **本作实际生效的就是它**（源点必须是客户区偏移）
          └─ 屏幕 BitBlt(桌面DC)             ← 仅当前台；本作的"正确参照"
     全失败 → 抛可读 VisionError（提示以管理员运行 / 让窗口可见）
```

### 自检方法（实战验证过，直接照抄）

抓一张客户区图 + 一张整屏图，用模板匹配量出"客户区图左上角在屏幕上的真实位置"，
它必须等于 `ClientToScreen(0,0)`；再独立核对"识别出的客户区中心"与"整屏定位换算值"，
偏差应 ≤3px。**修复前的实测值是偏差 (-9, -37)（就是标题栏/边框），修复后 (0, 0)。**
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
| 6 | 滑动结束后**延迟 + 分帧**还原光标，禁止一次 `SetCursorPos` 跳回 | 画面继续乱飘（残留拖拽状态被算成大位移） | `test_real_sender_drag_waits_before_restoring_cursor`、`test_restore_cursor_smooth_moves_in_small_steps` |
| 7 | 每次真实输入前置顶/置前并回读复核；无法确保则**绝不输入** | 输入打到别的窗口 | `test_ensure_window_front_*`、`test_real_sender_refuses_input_when_window_cannot_be_focused` |
| 8 | **取景原点必须是客户区左上**（BitBlt 源点用 `client_area_offset`，PrintWindow 整窗渲染后裁剪） | 坐标整体偏下"标题栏高度"（实测 37px） | `test_bitblt_renderer_starts_at_client_origin`、`test_printwindow_renderer_crops_client_area`、`test_client_area_offset_is_title_bar_plus_border` |
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

---

## ⑤ 历史 bug 档案（症状 / 根因 / 修法 / 回归测试）

> **这份档案是找 bug 的最短路径**：同一根因往往在别处还有第二份（例如"原点/坐标系搞错"这类）。
> 建议逐条问："这条例子里**同一类错误**，换一个函数还会不会犯？"

| # | 症状（用户视角） | 根因 | 修法 | 回归测试 / 提交 |
|---|---|---|---|---|
| 1 | 识别到的图像没问题，但**坐标总比真实位置偏下**；框选时画面**下方少一截（≈标题框高度）** | 实际生效的 `BitBlt(窗口DC)` 从窗口 DC 的 `(0,0)`（标题栏左上）取图，于是图像顶部多出标题栏、底部缺一截 → 图像行号 = 真实客户区 y + 37 | 新增 `client_area_offset()` 作唯一真源；BitBlt 源点改为该偏移；PrintWindow 整窗渲染后按偏移裁 | `test_bitblt_renderer_starts_at_client_origin` 等 5 条 / `6304270` |
| 2 | 点「保存为模板」后**什么都没发生**（模板没生成、主窗口却报"未选择有效区域"） | 保存按钮从功能第一版起就只 `connect(self.accept)`，裁剪函数 `save_selection()` 从未被 GUI 调用 | 保存按钮改连 `_on_save_clicked`：校验选区 → 裁剪落盘 → 成功才关窗；失败给提示且不关窗 | `test_save_button_writes_only_selected_region`、`test_crop_flow_writes_only_selected_region` / `df31f82` |
| 3 | 一张纯色模板刷出 **20 处"匹配度 1.000"** 的假坐标（还耗 16s） | `TM_CCOEFF_NORMED` 对无纹理模板在平坦区域天然满分 | `load_template` 用 `is_blank_frame` 在**读取阶段**拒绝纯色模板 | `test_load_template_rejects_flat_image`、`test_recognize_skips_flat_template` / `b177a39` |
| 4 | 画面放大/缩小后**识别不到** | 只做 1:1 匹配（缩放后模板像素尺寸变了） | 多尺度搜索：粗搜 + 精修 + 阈值在精修后判断 | `test_locate_scaled_finds_{enlarged,shrunk}_template` / `c0c522d` |
| 5 | 带框截图整帧**纯黑**，却报告"未识别到目标" | 本作 PrintWindow 返回黑帧，旧代码把它当"匹配度 0" | `is_blank_frame` 检测 + 逐级回退取景；全失败给可读错误 | `test_capture_client_bgr_falls_back_on_blank_frame`、`..._reports_actionable_error_when_all_blank` / `c0c522d` |
| 6 | 真值 3.50x 被测成 3.36x（框小一圈） | 粗搜"遇到第一个够强的候选就停"：3.30x 已 0.9018 就停，±0.06 精修够不到 3.50 | 改为"越过峰值回落才停"（`SCALE_PEAK_DROP`）+ 保留"候选面积 ≥30%"保护 | `test_locate_scaled_stops_coarse_search_only_after_peak` / `4779f76` |
| 7 | 高倍缩放识别不到（>2.0x） | 范围上界太小 | 两档搜索：0.3–2.0 先搜，落空扩到 4.0（第二档不重复扫） | `test_locate_scaled_finds_two_and_a_half_times_zoom`、`test_default_scale_range_is_fast_then_extended` / `251215d` |
| 8 | 打开开发者调试页后**所有页签高度都变了**、日志面板被压扁 | `QTabWidget` 高度取"所有页最大最小高度"与"最大建议高度"；调试页控件多把最小高度顶高 | 全部页签改 `ScrollablePage`（内容进 `QScrollArea` + 固定 `sizeHint`）+ 页签区 `stretch=1` + 日志面板最小高度；新增 `--measure-layout` 做回归 | `test_developer_tab_does_not_change_page_heights`、`test_measure_layout_reports_stable_heights` |
| 9 | 冻结 exe 里 `--measure-layout` 崩溃（`UnicodeEncodeError: 'gbk'`） | GUI 子系统 stdout 按 ANSI 代码页，报告里的 `✓` 编不出来 | 报告改 ASCII 安全的 `[OK]/[NG]` + `_print_safe()` 降级替换 | `test_format_measure_report_is_cp936_printable`、`test_cli_measure_layout_exits_zero` |
| 10 | `PROJECT_SPEC.md` 679 行、`config.example.json` 中文全部变乱码 | PS 5.1 `Get-Content -Raw \| Set-Content` 按 GBK 读无 BOM 的 UTF-8 | `git checkout --` 恢复后改用 Python 显式 `encoding="utf-8"`；写进 AGENTS 禁止条款 | AGENTS §2 末条 |
| 11 | 框选出来的模板**宽度多 1 像素** | Qt `QRect(左上, 右下)` 右下角是**包含式**的 | 一律按"左上 + 宽高"构造选区（`_set_selection_from_points`） | `test_crop_view_maps_widget_selection_to_image_pixels` |
| 12 | 滑动结束后画面**继续乱飘** | 瞬移式路径被引擎当甩动；残留拖拽状态把光标回跳算成大位移 | 缓出曲线分帧 + 末尾静止帧 + 松手后复查左键 + 延迟后**分帧**还原光标 | `test_build_drag_path_is_eased_out_with_still_tail`、`test_drag_path_holds_still_before_release`、`test_real_sender_drag_waits_before_restoring_cursor` |
| 13 | 勾了"还原光标"但滑动后鼠标没回去 | 滑动路径漏了还原（或还原被一次跳回） | 滑动结束走同一套 `restore_cursor_after_click` 逻辑（延迟 + 分步，被中断也要还原） | `test_real_sender_drag_restores_cursor_after_drag`、`..._even_if_wait_raises` |
| 14 | 模板列表里"移除选中"一次把**全部**删掉 | `QListWidget.setCurrentRow` 在多选模式下会把新行**叠加**进选区 | 改用 `setCurrentItem(..., ClearAndSelect)` | `test_debug_page_vision_remove_and_clear_templates` / `059b8e6` |
| 15 | 打包脚本在 PowerShell 5.1 下报一堆解析错误；exe 起来却没有 stdout；`dist` 被占用导致构建失败但看不清原因 | `build.ps1` 缺 UTF-8 **BOM**；GUI 子系统无 stdout/stderr；`&` 不等待 GUI 进程、`$LASTEXITCODE` 为空；运行中的 exe 锁住日志文件 | 文件带 BOM；`rthook_windowed_stdio.py` 把缺失的 stdio 指向 `os.devnull`；冒烟改用 `Start-Process -Wait -PassThru -RedirectStandard*`；dist 清理失败给可读原因 | `tests/test_packaging.py` 8 条守卫 |

---

## ⑥ 尚未修 / 已知薄弱点（找 bug 的优先清单）

按"值得投入"排序：

1. **`automation/vision.py` 642 行、`gui/main_window.py` 695 行都超过 AGENTS 的 600 行硬线**
   （main_window 是历史遗留）。建议拆法：多尺度匹配（`scale_candidates`/`_resize_scale`/
   `_scan_coarse`/`_refine_scale`/`locate_all_scaled`，约 200 行）移到 `automation/multiscale.py`；
   取景部分**不要动**（刚做实机验证）。拆完必须重跑全量 + 实机交叉验证。
2. **识别尚未接入任务**："按图点击"没实现（模板/阈值也不落配置，每次手选）。接入时会碰
   `core/registry.py` 的任务参数、`config/models.py` 与 schema 迁移，是新的 bug 高发面。
3. **多模板"先命中即用"的误报风险**：模板互相形似时，靠前那张可能先蹭到低分命中。
   实测条纹模板缩到 0.5x 对另一张模板的亮块区拿到 0.883（默认阈值 0.85 就中了）。
   缓解手段：提高阈值、模板更有辨识度，或改成"全部试完取最高分"（未做）。
4. **极小模板（<40px）+ 小缩放的缩放判断不稳**（信息量不足，模板匹配固有限制）。
5. **`automation/window.screenshot_client`（窗口诊断截图）** 用 PrintWindow 整窗渲染，
   对同类黑帧游戏可能存成纯黑图（诊断页因此可能误导），未接入黑帧兜底链。
6. **识别耗时随模板数线性增长**：单张约 1.6–5s，N 张全落空 ≈ N 倍。GUI 期间按钮禁用，
   但仍可能让用户觉得卡。
7. **屏幕取景要求窗口在前台**：不在前台时只剩 BitBlt/PrintWindow（本作可能黑帧），
   会报"取景失败"。这是环境限制而非 bug，但很容易被当成 bug 报上来。
8. **权限不对等**：游戏以管理员运行、本工具普通权限时无法置前（错误 5），任务会拒绝输入并报错。
   提权流程见 `gui/main_window.py:589-695`、`automation/elevation.py`。
9. **F8 急停热键常注册失败**（被占用）：只告警不中断。若任务正在跑而急停不可用，风险较大。
10. **识别参数不落配置**（模板列表/阈值/最多列出条数都是界面态，重启即丢）。
11. **`tests/test_core/test_vision.py` 589 行、`tests/test_automation/test_vision.py` 638 行**
    也在往硬线靠（测试文件同样适用长度建议）。
12. **内存里那三条 P1（来自 `CODE_REVIEW_REPORT.md`，基线 7e56cc4）仍未修**：
    ① `config/validation.py` 迁移对畸形 `params` 抛异常且不在 `try` 内 → 启动崩溃；
    ② GUI 能存下"自己读不回来"的配置（按键步数超 `MAX_KEY_STEPS`）→ 下次启动整份配置被重置；
    ③ `input_sender._ensure_front_or_raise` 置顶成功但置前失败时直接抛错、**永不取消置顶**，
    且现有测试把该行为固化成了期望。三条都能在 1 小时内修完（②③是同一片代码）。

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
| `_render_client_bits` | `automation/vision.py:466` | 主取景方式注入（黑帧/正常帧/抛错） |
| `_print_window` | `automation/vision.py:471` | 替换 ctypes 调用（假 GDI 测试用） |
| 假 GDI | `tests/test_automation/test_vision.py:520-599`（`_FakeBitmap`:520 / `_FakeDC`:537 / `fake_gdi`:571） | **验证取景几何**：位图里存真实像素，断言 BitBlt 源点、裁剪结果像素 |
| `build_channel` / 假 sender | `automation/input_sender.py:425`、`tests/test_automation/test_real_input.py` 的 `recording` 夹具 | 断言输入调用序列，零真实输入 |
| 假 `user32` | `tests/test_automation/test_real_input.py` 的 `user32` 夹具 | 断言 `SendInput`/`SetCursorPos` 序列、置顶/还原行为 |
| `get_debug_dir` | `core/vision.py` 导入处 | 带框截图写进 tmp |
| `TemplateCropDialog` | `gui/main_window.py:528` 调用处 | 替换对话框或子类化 `exec()` 模拟"框选 + 保存" |

### 写"几何 bug"测试的模板（本次用的手法）

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
cd D:\deepSeekHarness\LuoLuoTool
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

期望：`client offset` 等于标题栏+边框（本作实测 `(9, 37)`）；取景图像的 (0,0) 必须对应
`client origin`（用探针 2 或 3 验证）。

### 探针 2：逐条取景路径量偏移（找出是哪一条错）

思路：`_render_client_bits_printwindow(hwnd, flag)` / `_render_client_bits_bitblt(hwnd)` /
`_render_client_bits_screen(hwnd)` 各抓一张 → 用 `cv2.matchTemplate` 在一张**整屏截图**里定位图像里
一块纹理区域 → 反推"图像左上角在屏幕上的位置" → 与 `ClientToScreen(0,0)` 比较。
`is_blank_frame` 为 True 的路径直接标"不可用（黑帧）"。
（基线实测：PrintWindow 两种 flag 都是黑帧；`BitBlt(窗口DC)` 修复前偏 `(-9, -37)`、修复后 `(0, 0)`。）

### 探针 3：坐标端到端交叉验证（判断"坐标可信"）

```powershell
cd D:\deepSeekHarness\LuoLuoTool
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

期望：`delta = (0, 0)`（≤3px 可接受）。基线实测：识别 (650, 430) vs 整屏换算 (650, 430)。

> **编码注意**：上面两个探针的**字符串字面量全是 ASCII**，窗口标题从 `user_data/config.json` 读，
> 所以无论是粘到终端还是存成 `.ps1` 都不会炸。**但如果你要存成 `.ps1`，请存成 UTF-8 with BOM**
> —— Windows PowerShell 5.1 会把不带 BOM 的文件按 ANSI/GBK 读，脚本里的中文会全变乱码
> （实测过：`SyntaxError: unterminated string literal`）。最省事的做法是直接粘进终端。

> **正常噪音**：探针跑起来会在 **stderr** 里带日志行（例如 `PrintWindow 取到纯色/黑帧…`、
> `取景(BitBlt 窗口DC)：从客户区左上 (9, 37) 抓取…`）。PowerShell 会把它显示成红字错误记录，
> 这是日志不是异常；判读只看脚本自己 print 的那几行。

### 日志与产物位置

| 内容 | 路径 |
|---|---|
| 日志 | `user_data/logs/luoluotool.log` |
| 识别带框截图 | `user_data/debug/vision_<时间戳>.png`（整屏 + 画框，每处命中一个编号） |
| 窗口诊断截图 | `user_data/debug/window_<时间戳>.png` |
| 模板 | `assets/anchors/anchor_<时间戳>.png`（**不入库**） |
| 配置 | `user_data/config.json`（schema v9；损坏会自动恢复并在日志说明） |

---

## ⑨ 红线与规范速查（改代码前必看）

1. **需要逐项授权**：内存读写、封包拦截、驱动级注入、任何联网上传（工程负责人已明确不实现
   ACE 绕过；见 `PROJECT_SPEC.md` §4.1/§4.2）。**其余功能改动不需要额外授权**。
2. **禁止**：把 `user_data/config.json`、日志、截图、构建产物提交入库；force push；删除/破坏既有
   测试来让测试变绿；吞异常（`except: pass` / `except Exception: continue`）。
3. **提交规范**：Conventional Commits + 中文说明 + 范围前缀（`fix(automation): …`）。一次提交只做一件事。
   提交前自检：全量测试通过、无未使用 import、无调试 print、变更文件与目标一致。
4. **构建**：**只在用户明确要求时**跑 `packaging\build.ps1`（需 PowerShell，文件必须带 UTF-8 BOM）。
   产物不入库，守卫测试扫描 git 索引。
5. **文件长度**：>400 行考虑拆分，>600 行必须拆分（当前 2 个文件超线，见第 ⑥ 节）。
6. **编码**：Python 3.11+、UTF-8、4 空格、公共函数全类型注解；配置用 dataclass；JSON 原子写。
7. **可观测**：关键动作写日志；异常记录完整堆栈；GUI 里禁止 sleep/忙等。
8. **新增依赖**：改 `requirements.txt` 并在提交信息说明理由与体积代价（当前 numpy + opencv-python-headless）。

---

## 附：快速定位索引（常用符号 → 文件:行，基线 9aea9a9）

| 符号 | 位置 | 说明 |
|---|---|---|
| `recognize_in_window` | `core/vision.py:67` | 识别编排（多模板顺序尝试 + 多区域） |
| `_success_result` | `core/vision.py:170` | 命中消息（哪张模板、使用值、上限提示） |
| `capture_window` | `core/vision.py:212` | 供框选用的截图（含就绪校验） |
| `locate_all_scaled` | `automation/vision.py:308` | 两档多尺度匹配主流程 |
| `_scale_tiers` | `automation/vision.py:243` | 档位拆分（0.3–2.0 → 0.3–4.0） |
| `_scan_coarse` / `_refine_scale` | `automation/vision.py:255` / `:288` | 粗搜（峰值回落才停）/ 精修 |
| `load_template` | `automation/vision.py:81` | 读图（中文路径 + 纯色拒绝） |
| `is_blank_frame` | `automation/vision.py:383` | 黑帧/纯色判定 |
| `capture_client_bgr` | `automation/vision.py:393` | 取景入口（含回退链） |
| `_render_client_bits_bitblt` | `automation/vision.py:534` | **BitBlt 路径（源点必须客户区偏移）** |
| `_render_client_bits_printwindow` | `automation/vision.py:478` | PrintWindow（整窗渲染 + 裁剪） |
| `client_area_offset` | `automation/window.py:87` | 客户区在窗口内的偏移（唯一真源） |
| `build_channel` | `automation/input_sender.py:425` | 干跑/真实通道选择 |
| `point_in_client_area` / `check_points_in_bounds` | `automation/input_sender.py:366` / `:381` | 越界校验 |
| `RealInputSender.click_at` / `drag` | `automation/input_sender.py:146` / `:190` | 真实输入的校验与还原策略（`click_at(..., hold_seconds=None)`＝点击时长） |
| `send_left_click` | `automation/real_input.py:301` | 点击原语：按下 → 按住（切片检查急停）→ **finally 抬起** |
| `run_single_click` | `core/debug.py:80` | 单点测试动作（`hold_ms`：None＝引擎默认 / 0＝瞬时） |
| `_validate_click_hold` | `core/debug.py:55` | 点击时长校验（0–5000 ms，整数、非布尔） |
| `single_hold_spin` / `repeat_hold_spin` | `gui/pages/debug.py:170` / `:197` | 调试页「点击时长」控件（单点 + 连点，默认 40 ms，经 `hold_ms` 下发） |
| `run_repeat_click` | `core/debug.py:106` | 连点测试动作（同样支持 `hold_ms`；间隔＝点击之后的等待） |
| `ensure_window_front` | `automation/real_input.py:194` | 每次输入前置顶置前 + 复核 |
| `client_to_screen` | `automation/real_input.py:148` | 客户区→屏幕换算（点击路径） |
| `build_drag_path` | `automation/real_input.py:381` | 缓出曲线 + 末尾静止帧 |
| `restore_cursor_smooth` | `automation/real_input.py:401` | 分帧还原光标 |
| `CropView` / `TemplateCropDialog` | `gui/dialogs/crop_dialog.py:45` / `:167` | 框选几何与保存 |
| `_on_save_clicked` / `save_selection` | `gui/dialogs/crop_dialog.py:233` / `:249` | **只保存选区** |
| `DebugPage` | `gui/pages/debug.py:62` | 调试页（识别入口/模板列表/点击时长/干跑/测试按钮） |
| `_on_debug_test` / `run_debug_action` | `gui/main_window.py:495` / `:144` | 调试请求接收 / 动作分发（含 `hold_ms`） |
| `_on_capture_ready` / `_on_crop_requested` | `gui/main_window.py:529` / `:556` | 框选回填 / 框选入口（门禁 + 后台截图） |
| `_debug_actions_allowed` | `gui/main_window.py:487` | 开发者调试门禁 |
| `measure_layout` / `format_measure_report` | `gui/layout_measure.py:169` / `:237` | 布局测量与报告 |
| `Runner.start` | `core/runner.py:65` | 任务顺序执行/循环/失败计数 |
| `migrate` / `validate` | `config/validation.py:301` / `:325` | 迁移链与校验 |

> **索引自检**：改完代码后跑 `.venv\Scripts\python tools\check_guide_index.py` —— 它会逐条核对本表
> 的"符号 → 文件:行"是否还指得准（漂移会打印 `[DRIFT] 符号 文件:行 当前指向…` 并以退出码 1 结束）。
> 行号漂移的索引比没有索引更误导人，所以改代码后顺手跑一下。

---

## 附：给排查者的三个建议

1. **先跑不变量表**（第 ④ 节）：对每条问一句"如果我把它破坏掉，哪个测试会红？"——没有测试红的条目
   就是最可能有真 bug 的地方。
2. **优先怀疑坐标系/线程/资源释放**三类：本项目历史上 15 条 bug 里有 8 条属于这三类。
3. **实机问题先用探针再改代码**：第 ⑧ 节的探针 1/2/3 能在 1 分钟内区分"环境限制"与"代码 bug"
   （实测中就靠它把"黑帧""坐标偏下 37px"两条从"猜测"变成"定量结论"）。
