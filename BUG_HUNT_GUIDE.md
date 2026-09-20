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
    vision.py                319  取景/渲染（黑帧回退链、BitBlt/PrintWindow 几何）+ 再导出匹配名字
    template_match.py        175  模板读取与匹配原语（VisionError / Match / load_template / locate_all）
    multiscale.py            238  多尺度两档搜索：_scale_tiers / _scan_coarse / _refine_scale / locate_all_scaled
    drag_path.py              66  滑动路径几何（缓出曲线 + 分帧插值，纯函数）
    input_sender.py          540  InputSender 协议 / DryRunSender / RealInputSender / 越界校验 / build_channel
    real_input.py            583  SendInput 底层：置顶置前、点击、滑动发送、按键、光标还原
    window.py                147  找窗口、置前、客户区几何、诊断截图
    elevation.py              76  权限检测 / 以管理员重启
    hotkey.py                 72  F8 急停热键（RegisterHotKey）
  config/                        配置层（dataclass + 原子 JSON + 迁移校验）
    models.py                423  AppConfig / AutomationConfig / 任务参数解析 + 上限常量（20 步/点）
    validation.py            371  migrate() + validate()，_MIGRATIONS {1..8}，SCHEMA_VERSION = 9
    store.py                 113  ConfigSaveError + save/load/_recover（先校验后写 + 原子写 + 损坏恢复）
  core/                          业务编排层（不许 import PySide6/win32）
    vision.py                243  recognize_in_window（多模板/多区域编排）
    debug.py                 202  调试动作：单点/连点/滑动/键盘（复用正式通道；等待可中断）
    runner.py                184  Runner：顺序执行任务、循环、失败计数、停止
    registry.py              147  任务注册表 + 占位任务（order_hold/feature_3/feature_4）
    task.py / state.py        67/52  TaskContext/TaskResult/BaseTask；RunState 状态机（加锁 + try_transition）
  gui/                           界面层（只做绑定与展示）
    main_window.py           532  主窗口（展示与绑定 + 线程/状态编排）
    workers.py               137  后台线程：任务/调试测试/框选截图/窗口诊断 + run_debug_action
    elevation_flow.py        138  提权流程 mixin（检测/提示/以管理员身份重启）
    icons.py                  50  窗口图标加载（魔数校验 + 降级为空图标）
    pages/debug.py           434  开发者调试页（识别入口/模板列表/干跑/测试按钮）
    pages/settings.py        135  设置页（含开发者调试开关 + 急停热键提示）
    pages/daily.py           180  日常任务页（任务勾选、点击序列）
    pages/order_hold.py       56  卡订单页
    pages/planned_feature.py  51  功能三/四公共基类（占位页）
    pages/feature3.py,4.py    13  功能三/四页（占位子类）
    dialogs/crop_dialog.py   273  框选截图生成模板（CropView + TemplateCropDialog）
    layout_measure.py        283  --measure-layout 的测量与报告（ASCII 安全）
    widgets.py                54  LogPanelHandler（日志进面板）；ScrollablePage（页签基类）
    app.py                    73  入口：QApplication、任务栏图标身份、smoke 模式
  utils/                         keys.py(72) paths.py(50) logging_setup.py(53)
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
调试页「图片识别匹配测试」          gui/pages/debug.py:413   _on_vision_clicked()
  → 发信号 test_requested("vision", {images, threshold, max_results})
主窗口分发                          gui/main_window.py:429  _on_debug_test()
  后台线程 _DebugTestThread.run     gui/workers.py:41  （不阻塞 GUI）
  动作映射                          gui/workers.py:69  run_debug_action(kind="vision")
业务编排                            core/vision.py:67       recognize_in_window()
  ① 归一化模板列表                  core/vision.py:58       _template_paths()
  ② 找窗口 + 就绪校验               core/vision.py:71-79    find_window / is_window_ready
  ③ 取景（只截一次，多模板共用）    automation/vision.py:58 capture_client_bgr()
  ④ 逐张模板多尺度匹配              automation/multiscale.py:169 locate_all_scaled()
  ⑤ 组织消息/带框截图               core/vision.py:170       _success_result()
结果回传                            Signal finished_message → 调试页状态栏
```

**框选生成模板**链路：

```
调试页「框选截图生成模板」          gui/pages/debug.py:151   crop_button → crop_requested 信号
主窗口门禁 + 后台截图               gui/main_window.py:497   _on_crop_requested()
  截图线程                          gui/workers.py:100   _CaptureThread → core/vision.py:212 capture_window()
  弹框（GUI 线程）                  gui/main_window.py:470   _on_capture_ready() → TemplateCropDialog
  拖拽框选                          gui/dialogs/crop_dialog.py:45   CropView
  保存（**只存选区**）              gui/dialogs/crop_dialog.py:233  _on_save_clicked() → save_selection():249
  加入模板列表                      gui/main_window.py:484   debug_page.add_vision_template()
```

### 主链路 C：鼠标单点 / 连点（含"点击时长"）

```
调试页「鼠标单点测试」              gui/pages/debug.py:188   single_hold_spin（点击时长，ms）
调试页「鼠标连点测试」              gui/pages/debug.py:215   repeat_hold_spin（连点每次都用它）
  → _on_single_clicked / _on_repeat_clicked 发信号 test_requested(kind, {...})
    载荷：single {x, y, hold_ms}｜repeat {x, y, count, interval_ms, hold_ms}
主窗口分发                          gui/workers.py:69   run_debug_action
业务编排（单点）                    core/debug.py:98         run_single_click(hold_ms=...)
业务编排（连点）                    core/debug.py:124        run_repeat_click(..., hold_ms=...)（间隔＝点击之后的等待）
校验                                core/debug.py:56         _validate_click_hold（0–5000 ms 整数）
通道（干跑/真实）                   automation/input_sender.py:516 build_channel
  点击                              input_sender.py:149      RealInputSender.click_at(x, y, hold_seconds)
  **两步移动（hover）**             input_sender.py:207      _move_cursor_for_click（中途点 → 目标）
  **点击前核对事实**                input_sender.py:222      _verify_before_press（漂移>4px 跳过）
  时间线                            input_sender.py:26/27/28 容差 4px / 步进 30ms / 松手后 350ms 才还原光标
                                    input_sender.py:87       DryRunSender.click_at（只写日志，同样校验越界）
底层原语                            automation/real_input.py:344 send_left_click(sleep, hold_seconds, stop_event)
  按下 → 按住（CLICK_SLICE_SECONDS=50ms 切片查急停）→ **finally 抬起左键**
  置前后等待 200ms（:59）、按下前等待 80ms（:58）
  命中测试/窗口描述                 automation/real_input.py:166/184 window_under_point / describe_window
```

### 主链路 B：任务执行与输入注入

```
日常任务页/卡订单页勾选 → 任务进队列（core/registry.py 注册表）
主窗口「启动」                      gui/main_window.py:315   _start()
  真实模式确认弹窗                  gui/main_window.py:342   _real_mode_warning_text()/_confirm_real_mode()
  运行线程 _RunnerThread            gui/workers.py:30
  Runner 顺序执行                   core/runner.py:68        Runner.start()
    每个任务拿到 TaskContext（含 sender）core/task.py:15
    输入通道构建                    automation/input_sender.py:516 build_channel()
      ├─ 干跑：DryRunSender（:50，只写日志，**同样做越界校验**）
      └─ 真实：WindowReadinessGate(:318) → RealInputSender(:117)
           点击/滑动前校验              input_sender.py:449/464 point_in_client_area / check_points_in_bounds
           每次输入前置顶/置前并复核    automation/real_input.py:237 ensure_window_front()
           客户端→屏幕换算              automation/real_input.py:157 client_to_screen()
           实际注入                     automation/real_input.py:300 _send()（SendInput）
    停止/F8 急停                     gui/main_window.py:365/392 _stop()/_on_failsafe() → stop_event
```

### 线程模型（bug 高发区）

| 线程 | 位置 | 约束 |
|---|---|---|
| GUI 主线程 | `gui/**` | **禁止** sleep/忙等/同步截图；所有长任务进 QThread |
| 运行线程 `_RunnerThread` | `workers.py:30` | 只发信号回 GUI，不直接改控件 |
| 调试测试线程 `_DebugTestThread` | `workers.py:41` | 执行期间禁用按钮；可被 `request_stop()` 中断 |
| 截图线程 `_CaptureThread` | `workers.py:100` | 框选前截图，完成后发 `captured` |
| 诊断线程 `_DiagnoseThread` | `workers.py:122` | 窗口诊断 |

**找 bug 时优先怀疑**：跨线程直接操作控件、`stop_event` 没有切片检查、`finally` 里漏了资源释放或状态回滚。

---

## ③ 坐标系与几何（本项目最容易出 bug 的地方）

### 三套坐标

| 坐标 | 定义 | 谁在用 |
|---|---|---|
| **客户区坐标** | 游戏窗口客户区左上角为 (0,0)，范围 `[0,width)×[0,height)` | **识别结果、框选选区、点击/滑动入参**，全项目统一用它 |
| 窗口坐标/屏幕坐标 | Windows 原生坐标 | 只在 `client_to_screen` / `ClientToScreen` 处出现 |

- 客户区左上角在屏幕上的位置：`win32gui.ClientToScreen(hwnd, (0, 0))`。
- **客户区在窗口内的偏移**：`automation/window.py:80 client_area_offset(hwnd)` =
  `ClientToScreen(0,0) - GetWindowRect左上角` = 标题栏高度 + 边框宽度。
  实测本作窗口 1618×1070 / 客户区 1600×1024 → **(9, 37)**；无边框全屏窗口为 (0, 0)。

### 三条必须记住的几何事实（都踩过）

1. **窗口 DC（`GetWindowDC`）与 `PrintWindow` 的原点都是"窗口左上角"**（含标题栏）。
   取景必须以客户区偏移为源点/裁剪原点，否则抓到"标题栏 + 客户区上半部分"，
   画面底部缺"标题栏高度"一截，**识别坐标整体偏下标题栏高度**（实测 37px）。
   → `_render_client_bits_bitblt` 的 BitBlt 源点、`_render_client_bits_printwindow` 的整窗渲染+裁剪。
2. **屏幕 BitBlt 用 `ClientToScreen(0,0)` 作源点，天然以客户区左上为原点**，不需要再偏移/裁剪
   （`automation/vision.py:254`，它是"原点正确"的参照实现）。但它要求**窗口确实在前台**，
   否则会抓到被遮挡窗口的内容，因此调用方有前台门禁（`vision.py:110`）。
3. **窗口尺寸会变**：客户区实测过 1920×1052 与 1600×1024 两种。任何"写死 1920×1052"的假设
   都是潜在 bug；坐标/尺寸一律运行时读取。

### 取景回退链（本作实测：PrintWindow 两种 flag 都返回纯黑帧）

```
capture_client_bgr (vision.py:393)
  └─ _render_client_bits = PrintWindow(PW_RENDERFULLCONTENT)   ← 本作黑帧
     is_blank_frame() → 纯色/黑帧?
     └─ _render_client_bgr_fallback (vision.py:110)
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
| 5c | **点击前必须核对事实**：实测光标是否到达目标（偏差 >`CLICK_CURSOR_TOLERANCE_PX`=4px 就**跳过点击**）、光标处顶层窗口、前台/置顶状态、客户区尺寸，全部写进日志 | 日志写"点击完成"但游戏没反应时无法区分"没送到"与"送到了游戏不认"；光标被钳制时会点到别的控件 | `test_real_sender_logs_click_context_before_press`、`test_real_sender_skips_click_when_cursor_did_not_move`、`test_real_sender_logs_warning_when_hit_test_is_other_window` |
| 5d | **输入时间线**：光标分两步移动（先中途点，`CLICK_MOVE_STEP_SECONDS`=30ms）→ `INPUT_SETTLE_SECONDS`=80ms → 按下；置前/置顶后等 `FRONT_SETTLE_SECONDS`=200ms 再动；**松手后等 `CLICK_RESTORE_DELAY_SECONDS`=350ms 才还原光标，且必须分帧小步移回（`restore_cursor_smooth`），禁止一次 `SetCursorPos` 跳回** | 游戏按帧采样指针位置：一次跳跃 + 松手后立刻跳回别的显示器 → 处理这次点击的那一帧已经"指针不在窗口内"，点击被丢弃（实测：关掉「把真实鼠标移回原位置」就能点动） | `test_click_moves_cursor_in_two_steps_before_press`、`test_click_waits_before_restoring_cursor`、`test_real_sender_keeps_cursor_when_restore_disabled`、`test_focus_settle_is_long_enough_for_the_game`、`test_activate_sleeps_for_the_focus_settle` |
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
| 22 | **同一件事只有一份**：模块级 import 不被同名赋值遮蔽；上限/范围常量只在 `core`/`config` 定义一处（界面导入它）；`PW_*` 只定义一处；测试夹具只有 `tests/gui_helpers.py` 一份；源文件与测试文件都 ≤ 600 行 | "改一处漏一处"：界面与校验各用一份常量 → 存得下、读不回来 | `tests/test_source_guards.py` 四条守卫（import 遮蔽 / 行数硬线 / `PW_*` 单一定义 / 调试页范围与 `core.debug` 同一对象） |

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

| 16 | 单点测试"某页能点、另一页点不动"（日志显示光标偏差 0px、前台、置顶、命中窗口都对） | **松手后用 `SetCursorPos` 一次把光标跳回另一个显示器**：游戏（Unity）按帧采样指针位置，处理这次点击的那一帧看到"指针已不在窗口内"→ 点击被丢弃；页面越重帧越慢越容易丢。**用户实测关闭「把真实鼠标移回原位置」立刻可点，反证根因** | 点击还原改为与滑动同源的做法：先延迟 `CLICK_RESTORE_DELAY_SECONDS`（0.35s）再用 `restore_cursor_smooth` 分帧小步移回；另加两步移动（hover）+ 置前后 200ms + 点击前事实核对日志 | `test_click_waits_before_restoring_cursor`、`test_real_sender_keeps_cursor_when_restore_disabled`、`test_click_moves_cursor_in_two_steps_before_press`、`test_real_sender_logs_click_context_before_press` / `0b0298d`、`a43836f` |

> **第 17–24 条来自 2026-09-20 的代码审查（`reports/CODE_REVIEW_REPORT_20260920_1.md`：P1×3 / P2×9 / P3×10，已全部修复）**。
> 它们集中在三类**用户看得见的失败**上：① 自己把配置写坏（下次启动整份重置）；② 状态/资源不复位
> （窗口永久置顶、线程不收、按钮按不动）；③ 失败被藏起来（黑图报成功、热键失败只写日志）。
> 找新 bug 时值得照这三类同一句话追问："**这里失败的时候，用户看得见吗？"**

| # | 症状（用户视角） | 根因 | 修法 | 回归测试 / 提交 |
|---|---|---|---|---|
| 17 | 把配置里某个任务参数改坏后，工具**再也起不来**（启动即崩，界面都不出现） | `validation.migrate` 把畸形 `params`（不是 dict）交给迁移函数，异常不在 `try` 内 → `store.load` 直接抛 | `migrate` 每一步独立 `try/except`（失败记 WARNING + 回退原始 dict）；`store.load` 再把迁移包一层兜底走 `_recover`（备份坏文件 + 默认值） | `test_load_survives_malformed_params_during_migration` / `dab9348` |
| 18 | 界面上能保存的配置，下次启动却**整份被重置**（按键/滑动步数等） | 界面允许的步数上限**大于**校验器上限 → 能存下"自己读不回来"的配置，读回时校验失败 → 恢复默认 | 上限统一到 `config/models.py`（`MAX_KEY_STEPS`/`MAX_SWIPE_STEPS`/`MAX_CLICK_POINTS`＝20）并被解析与校验共用；`store.save` **先校验再落盘**（不合法抛 `ConfigSaveError`，文件保持原样）；GUI 弹窗 + 状态栏提示；日常页超限记 WARNING 并回滚输入框 | `test_save_refuses_invalid_config_and_keeps_old_file`、`test_daily_page_rejects_over_limit_keys_text` / `dab9348`、`af52571` |
| 19 | 对"无法置前"的窗口点一次，**游戏窗口永久浮在最上层**（只能重启游戏） | `_ensure_front_or_raise` 置顶成功、置前失败时直接抛错并丢弃 `FrontResult`，`finally` 里的取消置顶永远走不到；旧测试还把该行为写成了期望 | 抛错前先取消**本次由我们设置的**置顶（只在真的置顶过时调用）；`RELEASE_FLAGS` 并入 `TOP_FLAGS`，不误清别的程序设的置顶 | `test_real_sender_refuses_input_when_window_cannot_be_focused`、`test_real_sender_does_not_release_topmost_when_it_was_not_ours` / `082468b` |
| 20 | 程序版本比配置文件旧（降级/回滚）时，**新配置被静默覆盖** | `load` 不认更高的 `schema_version`，`save` 直接写回 | 读到更新版本只读返回默认值、**不写盘**；`save` 覆盖前先备份 `config.json.bak-v<N>-<时间戳>` | `test_load_keeps_newer_version_file_untouched`、`test_save_backs_up_newer_version_file_before_overwriting` / `dab9348` |
| 21 | 改了日志级别 / 轮转文件大小**不生效**（配置项是死配置） | `setup_logging()` 只在启动时用默认参数调用一次，重复调用还会叠加 handler | `setup_logging(level, max_file_mb, backup_count)` 幂等、参数变化时重建 `RotatingFileHandler`；`gui/app.py` 在 `store.load()` 后按配置重设 | `tests/test_utils_logging.py` / `af52571` |
| 22 | 调试测试跑着**「停止」按不动**；任务与调试测试能同时跑；关窗后线程还在注入输入 | 「停止」只认任务线程；两条启动路径互不检查；`closeEvent` 不等线程；空闲等待是整段 `sleep` | 停止按钮按 `_long_job_running`（任务或调试）判定；`_start`/`_on_debug_test` 双向互斥；`closeEvent` 走 `_wait_for_threads()`（4 个线程，超时记 ERROR）；调试等待改可中断分片 | `test_stop_button_works_for_debug_test_without_ever_starting_task`、`test_debug_test_rejected_while_task_is_running`、`test_close_event_waits_for_all_background_threads`、`test_repeat_click_interval_is_interruptible` / `501c039`、`af52571` |
| 23 | 窗口诊断报"成功"，但存下来的截图是**纯黑图**；取景主路径一抛异常就整体失败 | 诊断截图自带一套 PrintWindow 实现（本作必黑却报成功）；`capture_client_bgr` 的回退链只处理"黑帧"不处理"异常" | 诊断截图改为复用 `capture_client_bgr`（真 PNG + 黑帧检测，全失败给可读错误）；回退链把主路径包进 `try/except` 并在错误里带主因 | `test_screenshot_client_saves_real_png_via_capture_chain`、`test_diagnose_window_reports_blank_frame_instead_of_claiming_success`、`test_capture_client_bgr_falls_back_when_primary_raises` / `082468b` |
| 24 | 并发点击"停止"会抛异常；`STOPPING → ERROR` 被当成非法（真实错误被状态机掩盖）；滑动某帧 move 失败却当滑过去了 | 状态读写无锁且迁移表有死路；`SendInput` 返回值被忽略 | `state` 加锁 + `try_transition`（非法迁移返回 False 不抛）、放行 `STOPPING → ERROR`；滑动逐帧核对返回值、失败即报错；`send_key_hold` 切片下限钳到 0.01s | `test_try_transition_never_raises`、`test_stopping_can_go_to_error`、`test_send_left_drag_reports_failure_when_move_fails`、`test_send_key_hold_tolerates_zero_slice` / `501c039`、`082468b` |

> **第 25–27 条来自 2026-09-20 的第三轮审查（`reports/CODE_REVIEW_REPORT_20260920_3.md`，拆分重构复核：P2×1 / P3×4）**。
> 这一轮的共同特征是**"同一件事被写了两份"**：常量两份、夹具三份、文档与签名不一致 ——
> 单独看都不会立刻出错，但**改一处漏一处**时就会退化成第 18 条那种"配置被自己写坏"。

| # | 症状（用户视角） | 根因 | 修法 | 回归测试 / 提交 |
|---|---|---|---|---|
| 25 | （**潜在**）"以后把按键步数上限调大"时，界面上能存下 25 步的配置，**下次启动却判它损坏并整份恢复默认** | `validation.py` 先 `from ...models import MAX_KEY_STEPS`，第 15 行又写了 `MAX_KEY_STEPS = 20` —— **同名赋值遮蔽了 import**；写入路径用 models 的、校验路径用本地的，两边今天都是 20 所以没暴露 | 删掉那行遮蔽（保留 import），上限只留 `config/models.py` 一份；并新增仓库级守卫：**任何模块级 import 都不得被同名赋值遮蔽** | `tests/test_source_guards.py::test_no_module_level_import_is_shadowed` / `a07b42a` |
| 26 | （**潜在**）调试页允许填的坐标/间隔/次数与校验器各走各的，填进去了却在执行时被拒 | 同一组业务常量在两处各定义一份：`PW_*` 在 `vision.py` 与 `window.py` 各一份（后者是**死常量**）；`COORDINATE_MAX`/`INTERVAL_RANGE_MS`/`DURATION_RANGE_MS` 在 `core/debug.py` 与 `gui/pages/debug.py` 各一份 | 删掉 `window.py` 的死常量；调试页改为从 `core.debug` **导入**这些范围（`COUNT_RANGE` 由 `MAX_REPEAT` 推导）；守卫测试锁住"只允许定义一处 / 必须是同一个对象" | `test_printwindow_flags_are_defined_once`、`test_debug_page_limits_come_from_core_debug`、`test_sources_stay_under_line_limit` / `a07b42a` |
| 27 | 三处"小而真"的债：接口表写了不存在的参数、共享夹具抽了但旧文件仍各有副本（三份行为已分歧）、跨模块 `from ... import _prepare` 引用私有名 | 拆分时只搬了代码，没顺手收敛"文档/夹具/私有名"这三类**隐形重复** | 接口表改成真实签名 `capture_client_bgr(hwnd)`；`test_gui_config/test_gui_layout/test_gui_smoke` 改用 `gui_helpers.window_factory`（并给它补 `tmp_path`/`developer_mode` 支持，全仓库只剩一份夹具）；`_prepare` → 公开名 `prepare_for_match` 并写进 §8 接口表 | 三个测试文件全绿（116 passed）；`gui_helpers.window_factory` 唯一副本 / `a07b42a`、`00a348b` |

---

## ⑥ 尚未修 / 已知薄弱点（找 bug 的优先清单）

按"值得投入"排序：

1. ~~三个源文件超 600 行硬线~~ **已拆（2026-09-20，用户要求；纯搬运、行为零变化）**：
   - `automation/vision.py` 654 → **319**，拆出 `template_match.py`（175，读图与匹配原语）+
     `multiscale.py`（238，两档缩放搜索）；`vision.py` 保留取景/渲染并**再导出**旧名字，
     所以 `core/vision.py`、`__main__.py`、`window.py` 与旧导入都不用改。
   - `automation/real_input.py` 620 → **583**，拆出 `drag_path.py`（66，纯路径几何）。
   - `gui/main_window.py` 765 → **532**，拆出 `gui/workers.py`（137）、`gui/elevation_flow.py`（138）、
     `gui/icons.py`（50）；`MainWindow` 改为继承 `ElevationFlowMixin`。
   - 测试文件 `tests/test_gui_run.py` 1094 → **421 行 / 23 用例**，按主题拆出 `test_gui_hotkey.py`（124/5）、
     `test_gui_elevation.py`（231/11）、`test_gui_debug_crop.py`（288/12），共享夹具进 `tests/gui_helpers.py`（81）；
     `tests/test_automation/test_vision.py` 659 → **410 行 / 29 用例**，取景部分拆到
     `test_vision_capture.py`（259/10），共享辅助进 `tests/test_automation/vision_helpers.py`（15）；
     `tests/test_automation/test_real_input.py` 1229 → **241 行 / 19 用例**，按被测对象拆出
     `test_real_input_click.py`（368/28）、`test_real_input_drag.py`（300/22）、
     `test_real_input_keys.py`（194/16），共享夹具进 `tests/test_automation/real_input_helpers.py`（224）。
     至此**源文件与测试文件全部在 600 行以内**（唯一接近的是 `tests/test_core/test_vision.py` 589 行）。
   **搬迁手法（下次拆文件照抄）**：用脚本按 AST 行区间**原样搬运**（不改一行函数体），再用 AST 比对
   "旧文件的定义 == 新文件的定义"逐字一致；头部 import 用 AST 剪掉搬走后没人用的名字。
   **最容易踩的坑**：测试里的 `monkeypatch.setattr(模块, ...)` 目标必须跟着实现搬
   （本次改了 41 处，例如 `mw.is_process_elevated` → `elevation_flow.is_process_elevated`、
   `mw.diagnose_window` → `workers.diagnose_window`、`mw.get_icons_dir` → `icons.get_icons_dir`）；
   补丁打在没有被调用的命名空间上不会报错，只会**静默失效**，测试仍然全绿但失去意义。
   取景逻辑（`vision.py`）本次没动，但仍建议进游戏复测一次。
2. **识别尚未接入任务**："按图点击"没实现（模板/阈值也不落配置，每次手选）。接入时会碰
   `core/registry.py` 的任务参数、`config/models.py` 与 schema 迁移，是新的 bug 高发面。
3. **多模板"先命中即用"的误报风险**：模板互相形似时，靠前那张可能先蹭到低分命中。
   实测条纹模板缩到 0.5x 对另一张模板的亮块区拿到 0.883（默认阈值 0.85 就中了）。
   缓解手段：提高阈值、模板更有辨识度，或改成"全部试完取最高分"（未做）。
4. **极小模板（<40px）+ 小缩放的缩放判断不稳**（信息量不足，模板匹配固有限制）。
5. ~~窗口诊断截图可能存成纯黑图~~ **已修（评审 P2-9，`082468b`）**：改为复用 `capture_client_bgr`
   的完整回退链（真 PNG + 黑帧检测），全失败时报可读错误而不是给你一张黑图。剩余限制：窗口不在前台时
   屏幕 BitBlt 不可用，此时诊断会**失败**（可读原因），这是环境限制。
6. **识别耗时随模板数线性增长**：单张约 1.6–5s，N 张全落空 ≈ N 倍。GUI 期间按钮禁用，
   但仍可能让用户觉得卡。
7. **屏幕取景要求窗口在前台**：不在前台时只剩 BitBlt/PrintWindow（本作可能黑帧），
   会报"取景失败"。这是环境限制而非 bug，但很容易被当成 bug 报上来。
8. **权限不对等**：游戏以管理员运行、本工具普通权限时无法置前（错误 5），任务会拒绝输入并报错。
   提权流程见 `gui/elevation_flow.py:1-138`、`automation/elevation.py`。
9. **F8 急停热键常注册失败**（被占用）：**已改进但未根治**（评审 P3-9，`af52571`）—— 失败现在会在
   状态栏追加提示 + 设置页红字提示，且「停止」按钮对调试测试也已生效（原来按不动）；但热键本身在 F8
   被占用时仍不可用，根治办法是在设置页换一个键名。
10. **识别参数不落配置**（模板列表/阈值/最多列出条数都是界面态，重启即丢）。
11. **`tests/test_core/test_vision.py` 589 行**（接近硬线，尚未拆）；`tests/test_automation/test_real_input.py`
    1229 → **241 行**（2026-09-20 按被测对象拆成点击/滑动/键盘三个文件 + 共享夹具模块，见第 1 条）。
    源文件与测试文件现在**全部在 600 行硬线以内**；测试文件同样适用该规则，拆法照第 1 条的六步来。
12. **本次评审修复（P1×3 / P2×9 / P3×10）只在单测层面验证过，实机未复测**（提交 `dab9348`→`af52571`）。
    下一次进游戏前建议按顺序跑：开发者调试页的四项测试（单点 / 连点 / 滑动 / 按键）+ 窗口诊断 +
    图像识别，重点看 ① 开着「把真实鼠标移回原位置」时点击是否正常（原问题待复测）；② 诊断截图能不能
    看（应不再是纯黑）；③ 关窗后进程是否干净退出、游戏窗口是否不再浮在最上层（评审 P1-3 的实机面）。
13. **"某页点不动"已定位并修复（2026-09-20）**：根因是"松手后一次 `SetCursorPos` 把光标跳回另一个
    显示器"，游戏按帧采样指针位置时已经"指针不在窗口内"→ 这次点击被丢弃（用户实测关掉「把真实鼠标
    移回原位置」立刻可点，反证根因）。已改为"延迟 0.35s + 分帧小步移回"（见 ④ 5d 与 ⑤ 第 16 条）。
    仍待验证：**开着还原开关时是否也能点动**（用户尚未复测）；若仍不行，下一步可把
    `CLICK_RESTORE_DELAY_SECONDS` 调大（0.5–1s）或把"还原"改成只把光标移到游戏窗口边缘之外。

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
| 假 GDI | `tests/test_automation/test_vision_capture.py:118-198`（`CLIENT_OFFSET`:123 / `_window_pixels`:126 / `_expected_client_pixels`:135 / `_FakeBitmap`:141 / `_FakeDC`:158 / `fake_gdi`:192；2026-09-20 拆文件后从 `test_vision.py` 移来） | **验证取景几何**：位图里存真实像素，断言 BitBlt 源点、裁剪结果像素 |
| `build_channel` / 假 sender | `automation/input_sender.py:516`、`tests/test_automation/real_input_helpers.py` 的 `recording` 夹具 | 断言输入调用序列，零真实输入 |
| 假 `user32` | `tests/test_automation/real_input_helpers.py` 的 `user32` 夹具（2026-09-20 拆文件后从 `test_real_input.py` 移来） | 断言 `SendInput`/`SetCursorPos` 序列、置顶/还原行为 |
| `get_debug_dir` | `core/vision.py` 导入处 | 带框截图写进 tmp |
| `TemplateCropDialog` | `gui/main_window.py:473` 调用处 | 替换对话框或子类化 `exec()` 模拟"框选 + 保存" |

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

## 附：快速定位索引（常用符号 → 文件:行，基线 a88e42e）

| 符号 | 位置 | 说明 |
|---|---|---|
| `recognize_in_window` | `core/vision.py:67` | 识别编排（多模板顺序尝试 + 多区域） |
| `_success_result` | `core/vision.py:170` | 命中消息（哪张模板、使用值、上限提示） |
| `capture_window` | `core/vision.py:212` | 供框选用的截图（含就绪校验） |
| `locate_all_scaled` | `automation/multiscale.py:169` | 两档多尺度匹配主流程 |
| `_scale_tiers` | `automation/multiscale.py:104` | 档位拆分（0.3–2.0 → 0.3–4.0） |
| `_scan_coarse` / `_refine_scale` | `automation/multiscale.py:116` / `:149` | 粗搜（峰值回落才停）/ 精修 |
| `load_template` | `automation/template_match.py:78` | 读图（中文路径 + 纯色拒绝） |
| `is_blank_frame` | `automation/template_match.py:65` | 黑帧/纯色判定 |
| `capture_client_bgr` | `automation/vision.py:58` | 取景入口（含回退链） |
| `_render_client_bits_bitblt` | `automation/vision.py:211` | **BitBlt 路径（源点必须客户区偏移）** |
| `_render_client_bits_printwindow` | `automation/vision.py:155` | PrintWindow（整窗渲染 + 裁剪） |
| `client_area_offset` | `automation/window.py:80` | 客户区在窗口内的偏移（唯一真源） |
| `screenshot_client` | `automation/window.py:94` | 窗口诊断截图（走取景回退链 → 真 PNG + 黑帧检测） |
| `build_channel` | `automation/input_sender.py:516` | 干跑/真实通道选择 |
| `point_in_client_area` / `check_points_in_bounds` | `automation/input_sender.py:457` / `:472` | 越界校验 |
| `RealInputSender.click_at` / `drag` | `automation/input_sender.py:149` / `:273` | 真实输入的校验与还原策略（`click_at(..., hold_seconds=None)`＝点击时长） |
| `_move_cursor_for_click` / `_verify_before_press` | `automation/input_sender.py:207` / `:222` | 两步移动（hover）/ 点击前核对事实（漂移>4px 跳过） |
| `_restore_cursor_after_click` / `_restore_cursor_after_drag` | `automation/input_sender.py:188` / `:323` | 延迟 + 分帧小步还原光标（点击/滑动同一套做法） |
| `CLICK_CURSOR_TOLERANCE_PX` / `CLICK_MOVE_STEP_SECONDS` / `CLICK_RESTORE_DELAY_SECONDS` | `automation/input_sender.py:26` / `:27` / `:28` | 4px / 30ms / 350ms（输入时间线三档） |
| `INPUT_SETTLE_SECONDS` / `FRONT_SETTLE_SECONDS` | `automation/real_input.py:69` / `:70` | 80ms（按下前）/ 200ms（置前后） |
| `send_left_click` | `automation/real_input.py:344` | 点击原语：按下 → 按住（切片检查急停）→ **finally 抬起** |
| `window_under_point` / `describe_window` | `automation/real_input.py:166` / `:184` | 命中测试与窗口描述（诊断"点击落在谁身上"） |
| `run_single_click` | `core/debug.py:98` | 单点测试动作（`hold_ms`：None＝引擎默认 / 0＝瞬时） |
| `_validate_click_hold` | `core/debug.py:56` | 点击时长校验（0–5000 ms，整数、非布尔） |
| `single_hold_spin` / `repeat_hold_spin` | `gui/pages/debug.py:188` / `:210` | 调试页「点击时长」控件（单点 + 连点，默认 40 ms，经 `hold_ms` 下发） |
| `restore_cursor_box` | `gui/pages/debug.py:94` | 还原光标开关（2026-09-20 从设置页移入；受开发者调试门禁） |
| `settings_page.developer_box` | `gui/pages/settings.py:48` | 设置页「开发者调试」开关（决定调试页是否挂载/生效） |
| `show_hotkey_hint` | `gui/pages/settings.py:89` | 设置页红字提示（急停热键不可用等，评审 P3-9） |
| `run_repeat_click` | `core/debug.py:124` | 连点测试动作（同样支持 `hold_ms`；间隔＝点击之后的等待，可被急停打断） |
| `ensure_window_front` | `automation/real_input.py:237` | 每次输入前置顶置前 + 复核（失败时只取消**本次我们设的**置顶，评审 P1-3） |
| `client_to_screen` | `automation/real_input.py:157` | 客户区→屏幕换算（点击路径） |
| `build_drag_path` | `automation/drag_path.py:49` | 缓出曲线 + 末尾静止帧 |
| `restore_cursor_smooth` | `automation/real_input.py:397` | 分帧还原光标 |
| `CropView` / `TemplateCropDialog` | `gui/dialogs/crop_dialog.py:45` / `:167` | 框选几何与保存 |
| `_on_save_clicked` / `save_selection` | `gui/dialogs/crop_dialog.py:233` / `:249` | **只保存选区** |
| `DebugPage` | `gui/pages/debug.py:67` | 调试页（识别入口/模板列表/点击时长/干跑/测试按钮） |
| `_on_debug_test` / `run_debug_action` | `gui/main_window.py:429` / `gui/workers.py:69` | 调试请求接收 / 动作分发（含 `hold_ms`） |
| `_on_capture_ready` / `_on_crop_requested` | `gui/main_window.py:470` / `:497` | 框选回填 / 框选入口（门禁 + 后台截图） |
| `_debug_actions_allowed` | `gui/main_window.py:421` | 开发者调试门禁 |
| `_register_hotkey_or_hint` | `gui/main_window.py:256` | 热键注册 + 失败显著提示（评审 P3-9） |
| `_wait_for_threads` | `gui/main_window.py:213` | 关窗等齐 4 个后台线程（评审 P2-6） |
| `measure_layout` / `format_measure_report` | `gui/layout_measure.py:169` / `:237` | 布局测量与报告 |
| `Runner.start` | `core/runner.py:68` | 任务顺序执行/循环/失败计数 |
| `try_transition` | `core/state.py:46` | 状态迁移（非法迁移返回 False 不抛；读写加锁，评审 P3-1） |
| `ConfigSaveError` | `config/store.py:15` | 保存前校验失败（磁盘文件保持原样，评审 P1-2） |
| `MAX_KEY_STEPS` / `MAX_CLICK_POINTS` | `config/models.py:12` / `:14` | 按键/滑动/点击点上限 20（界面与校验器共用，评审 P1-2） |
| `migrate` / `validate` | `config/validation.py:309` / `:339` | 迁移链（每步独立 try，绝不崩）与校验 |
| `setup_logging` | `utils/logging_setup.py:13` | 幂等日志初始化（按配置重建 handler，评审 P2-2） |
| `PlannedFeaturePage` | `gui/pages/planned_feature.py:14` | 功能三/功能四公共基类（评审 P3-10） |
| `ease_out_quad` / `interpolate_points` | `automation/drag_path.py:22` / `:27` | 滑动缓出曲线 / 分帧插值（纯函数） |
| `scale_candidates` | `automation/multiscale.py:45` | 粗搜档位生成（按步长枚举比例） |
| `locate_best_scaled` | `automation/multiscale.py:225` | 多尺度取最佳命中（无命中返回 None） |
| `annotate` / `save_image` | `automation/vision.py:298` / `:312` | 带框截图 / 存图（中文路径用 imencode+tofile） |
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
2. **优先怀疑坐标系/线程/资源释放**三类：本项目历史上 15 条 bug 里有 8 条属于这三类。
3. **实机问题先用探针再改代码**：第 ⑧ 节的探针 1/2/3 能在 1 分钟内区分"环境限制"与"代码 bug"
   （实测中就靠它把"黑帧""坐标偏下 37px"两条从"猜测"变成"定量结论"）。
