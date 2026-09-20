# AGENTS.md — LuoLuoTool 长期开发规范

> 本文件面向 Codex / Cursor / Claude Code / Windsurf 等 AI 编程代理。
> **所有开发动作（包括规划、写码、修改文件、跑命令）都必须遵守本文件。**
> 与 `PROJECT_SPEC.md` 冲突时，以 `PROJECT_SPEC.md` 的边界条款为准。

---

## 1. 开发原则

1. **小步推进**：每次只完成一个可验证的增量（见第 6 节）。禁止一次性生成整个项目。
2. **按阶段执行**：只能执行用户指定的 `PHASE_PROMPTS.md` 中的一个阶段；未指定的一律不做。
3. **先测试后实现**：核心逻辑（config/core/automation 的纯逻辑部分）先写失败测试，再实现。
4. **分层单向依赖**：`gui → core → automation/utils`。`core` 不得 import PySide6/win32；`automation` 不得 import PySide6；任何反向 import 都视为缺陷。
5. **UI 与业务分离**：GUI 文件里不允许出现任务流程、输入注入、文件读写等逻辑；只允许出现事件绑定与展示。
6. **默认安全**：任何真实输入注入路径都必须经过显式用户确认（询问频率可配置，默认每次）+ 急停可中断。**`dry_run` 出厂默认已按用户要求改为 `false`（2026-09-19：干跑默认不开启，首次启动即真实模式）**，因此"默认安全"由三件事共同保证：真实模式启动前**强制确认弹窗**、F8 急停、以及**点击越界校验**（见第 2 节）。**测试里必须恒为干跑**（`tests/conftest.py` 全局夹具强制，红线：单测绝不产生真实输入）。输入实现方式：**唯一保留「真实鼠标键盘」（`SendInput`，规则见第 2 节、背景见 `PROJECT_SPEC.md` §4.2.3）**；其余通道（窗口消息、合成指针、对齐窗口）已按用户要求删除；驱动级注入等其他方案须逐项授权（见 `PROJECT_SPEC.md` §4.1）。
7. **可观测**：所有关键动作写日志；异常必须记录完整堆栈；不允许 `pass` 掉异常或 `except Exception: continue` 式的吞错。
8. **最小依赖**：只允许使用 `requirements.txt` / `requirements-dev.txt` 中列出的包。需要新依赖时：先改 requirements 文件 → 在提交说明写明理由 → 才可 import。

## 2. 编码要求

- Python 3.11+，UTF-8，4 空格缩进；类型注解覆盖所有公共函数签名。
- 配置模型用 `dataclass`；JSON 读写必须原子化（临时文件 + `os.replace`）。
- 日志用标准库 `logging`：模块级 `logging.getLogger(__name__)`；禁止 `print` 替代日志（CLI 输出除外）。
- 所有文件/窗口/进程操作都要处理失败路径：找不到窗口、无权限、配置缺失、磁盘满等，给出可读错误并保持程序可用。
- 时间间隔类配置必须有上下限校验（例如 `click_interval_ms` 限 100–5000）。
- GUI：长任务一律放工作线程（QThread），禁止在主线程 sleep 或忙等；按钮防重复点击（启动后禁用启动钮）。
- GUI 布局：**所有页签必须继承 `gui.widgets.ScrollablePage`**（内容自动进 `QScrollArea` + 建议尺寸统一为 `PAGE_SIZE_HINT`；派生类用 `QVBoxLayout(self.content)`，布局不能建在 `self` 上）。原因（2026-09-19 实测）：`QTabWidget` 的高度同时取「所有页签的最大最小高度」与「最大建议高度」——其一是调试页把窗口最小高度 381 顶到 658，其二是它把页签区实际高度 284 顶到 316、日志面板压到 252、所有页签高度随之变化。主窗口里日志面板设最小高度、页签区 `stretch=1`，确保多余高度只影响页签区。改动页签后必须跑 `--measure-layout`（报告须为「挂载/卸载开发者调试页不改变任何高度」，或跑 `tests/test_gui_layout.py`）。
- 每次真实输入注入前检查 stop 事件；停止请求发出后 500ms 内必须停止动作序列。
- 输入注入实现方式（**只有一种**：真实鼠标键盘 `SendInput`；窗口消息/合成指针/对齐窗口三种实现已按用户要求删除）：`automation/real_input.py`（Phase 5.3）必须：**每次点击/按键前**校验游戏窗口是否在最顶层，不在则先 `HWND_TOPMOST` 置顶再 `SetForegroundWindow` 置前（失败用 `AttachThreadInput` 兜底）并回读复核；无法确保窗口在最前时**绝不输入**（抛可读错误）；最小化先 `SW_RESTORE`；输入结束取消本次由我们设置的置顶；点击后按 `restore_cursor_after_click` 还原真实光标；键盘支持单键/组合键（`key_combo("ctrl+s")`）/长按（`key_hold`），**长按必须切片检查急停并在任何退出路径释放按键（绝不卡键）**，组合键必须逆序释放修饰键；鼠标**滑动**（`drag`）必须：客户区起终点各经 `ClientToScreen` 换算、沿**缓出曲线**分帧移动（`build_drag_path` = `interpolate_points(..., easing=ease_out_quad)` 缓出采样 + 末尾静止帧，≈60Hz、最少 4 步、避免被识别为瞬移，**末尾在终点保持静止 `DRAG_TAIL_HOLD_STEPS` 帧后再松手**，防"甩动惯性"导致画面继续飘）、滑动前清理残留左键按下状态并校验置顶窗口、期间切片检查急停、松手后**复查 `VK_LBUTTON` 已抬起**（未抬起则补发，仍失败即报错）、**任何退出路径（含等待抛异常）都在 finally 释放左键**、滑动结束后**同样按 `restore_cursor_after_click` 还原光标**，但必须**先延迟 `DRAG_RESTORE_DELAY_SECONDS` 让引擎处理完抬起、再用 `restore_cursor_smooth` 分帧小步移回**（禁止一次 `SetCursorPos` 跳回：跳跃会被残留拖拽状态算成巨大位移而让画面乱飘；等待被中断时仍必须还原）；键名表与解析放 `utils/keys.py`（config 与 GUI 复用，配置校验与 GUI 会即时拒绝未知键名）；`SendInput`/`SetCursorPos` 只允许出现在 `real_input.py`；
- 点击越界硬规则（2026-09-19 用户要求）：**任何鼠标点击在发出前都必须校验坐标落在游戏窗口客户区内**（`input_sender.point_in_client_area`，客户区为 `[0,width)×[0,height)`）；越界或读不到客户区时**不点击**，只写 WARNING 日志（"点击坐标 (x, y) 不在游戏窗口内（客户区 WxH），已跳过本次点击"）。真实通道（`RealInputSender.click_at`）与干跑通道（`DryRunSender`）都要校验；客户区读取失败按越界处理（宁可不点击）。
- **点击时长硬规则（2026-09-20 用户要求）**：点击＝"按下 → 保持 `hold_seconds` → 抬起"，`InputSender.click/click_at` 必须接受 `hold_seconds: float | None`（`None`＝用引擎默认 `real_input.CLICK_HOLD_SECONDS`＝40 ms，`0`＝瞬时点击）。`real_input.send_left_click` 实现要求：按住期间按 `CLICK_SLICE_SECONDS`（50 ms）切片推进并检查 `stop_event`（**急停可在 500 ms 内打断长按**），且**无论正常结束、被中断还是 `sleep` 抛异常，都在 `finally` 里抬起左键**（绝不把左键卡在按下状态）；`RealInputSender.click_at` 必须把 `self._stop_event` 传下去。GUI 调试页「鼠标单点测试」的「点击时长」范围 `core.debug.CLICK_HOLD_RANGE_MS`＝(0, 5000) ms，默认 `DEFAULT_CLICK_HOLD_MS`＝40 ms（与引擎默认对齐），经 `run_single_click(..., hold_ms=...)` 校验后传秒；`hold_ms=None` 表示"不指定、用引擎默认"（与 `0` 语义不同，两者都有测试）。**单点与连点测试都已接入点击时长**（连点每次点击都用同一时长，间隔仍是"点击动作结束之后"的等待，不叠加）。
- **输入时间线（2026-09-20 用户实测"某页能点、另一页点不动"，日志已证明注入正确后的加固）**：真实点击必须按"看起来像人"的时间线发：① **光标分两步移动**（`_move_cursor_for_click`：先到起点与目标的中点、隔 `CLICK_MOVE_STEP_SECONDS`=30ms，再到目标）——一次绝对跳跃只产生一条移动事件，Unity 的 UI 模块按帧采样指针/hover，跳过去再立刻按下容易被忽略；② 目标到位后等 `INPUT_SETTLE_SECONDS`=80ms 再按下；③ 置顶/置前后等 `FRONT_SETTLE_SECONDS`=200ms 再发输入（游戏被唤醒后需要几帧才响应）；④ **松手后必须等 `CLICK_RESTORE_DELAY_SECONDS`（350ms），再用 `restore_cursor_smooth` 分帧小步把光标移回（禁止一次 `SetCursorPos` 跳回）**。**该条已由用户实测确认根因**：一次跳回（尤其跨显示器）会让游戏在处理这次点击的那一帧里看到"指针已不在窗口内"，于是这次点击被丢弃 —— 实测"关掉「把真实鼠标移回原位置」就立刻能点动"正是反证（与滑动路径的 `DRAG_RESTORE_DELAY_SECONDS` 同源经验）。这些常量不许为了"快一点"随意调小；调小前先想清楚上面每条的原因。
- **点击前必须核对事实（2026-09-20 用户实测：同一坐标"某页能点、另一页点不动"，日志两边都只写"完成"）**：`RealInputSender.click_at` 在按下左键前必须调用 `_verify_before_press`，把**可核对的事实**一次记进日志：客户区尺寸、目标客户区坐标 → 屏幕坐标、**实测光标位置与偏差**、光标处顶层窗口（`real_input.window_under_point` + `describe_window`）、是否前台、是否置顶、光标处是否就是本窗口。**实测光标与目标偏差 > `CLICK_CURSOR_TOLERANCE_PX`（4px）时必须跳过本次点击**并写 WARNING（`SendInput` 被接受不代表光标真的到位，用错误位置点击在游戏里可能误触别的按钮）；命中测试窗口不是本窗口时给 WARNING 但仍点击（可能是子窗口/别名 hwnd）；读取光标失败只记 WARNING 并继续（不因一次读数异常就停掉点击）。这条日志是区分"输入没送到"与"送到了游戏不认"的唯一依据，不要删。
- **滑动越界硬规则（2026-09-19 同日追加，用户要求）**：滑动（`drag`）的**起点与终点都必须**在窗口客户区内，任一端越界或读不到客户区就**整段跳过**并写 WARNING（"滑动起点 (x, y)、终点 (x, y) 不在游戏窗口内（…），已跳过本次滑动"）。判定共用 `check_points_in_bounds(points, check)`，点击传一个点、滑动传两个点，真实与干跑通道共用同一份逻辑。
- 开发者调试页（`gui/pages/debug.py` + `core/debug.py`）只允许复用正式输入通道（`build_channel`）做测试：干跑模式下测试只写日志、零真实输入；真实模式下每次输入前同样校验并置顶窗口；测试动作必须放后台线程、执行期间禁用按钮、可被停止请求中断（长按/滑动仍须释放按键）。**开发者调试未开启时该页所有选项一律不生效**（2026-09-19 用户要求）：整页禁用、干跑开关与还原光标开关（后者 2026-09-20 按用户要求从设置页移入本页）的改动不写配置并回滚勾选、主窗口 `_debug_actions_allowed()` 拒绝测试/诊断/布局测量请求，关闭开关时中断正在运行的调试线程。
- 图像识别（2026-09-19 引入，`automation/vision.py` + `core/vision.py`）：模板匹配必须用 `np.fromfile` + `cv2.imdecode` 读图（`cv2.imread`/`cv2.imwrite` 在 Windows 上**不支持中文路径**，实测算子必须用 imencode+tofile）；匹配结果坐标一律是**客户区坐标**（中心/左上/尺寸/匹配度），可直接喂给 `click_at`/`drag`；模板比截图大必须抛可读 `VisionError`；**纯色模板必须在 `load_template` 里就被拒绝**（`is_blank_frame`：实测一张纯色 260x260 在真实游戏画面上刷出 20 处"匹配度 1.000"——平坦区域对无纹理模板天然满分，绝不允许把这种假坐标给用户；校验要求在读取阶段，不是匹配阶段）；识别前必须校验窗口存在且未最小化；失败一律转成 `RecognizeResult`（不把异常抛给 GUI 线程）；**识别不产生任何输入**；`automation/vision.py` 不得 import PySide6。模板用「框选截图生成模板」（`gui/dialogs/crop_dialog.py`）产生并存到 `assets/anchors/`（`*.png` 已被 .gitignore 排除，不入库）；**「保存为模板」按钮必须走"裁剪 + 落盘"（`_on_save_clicked` → `save_selection`），只保存用户手动框选的那块区域，绝不允许把整屏截图当模板存下来**；没有有效选区（没拖、或小于 `MIN_SELECTION_SIZE`=8px、或保存失败）时**既不写文件也不关闭对话框**，只在提示行说明原因（历史缺陷：该按钮曾是 `connect(self.accept)`，点一下只关窗口、什么都不存，主窗口随后报"未选择有效区域"—— 2026-09-20 复现并修复，回归测试见 `tests/test_gui_crop.py` 与 `test_gui_run.py::test_crop_flow_writes_only_selected_region`）；选区面积 ≥ 整屏 95%（`NEAR_FULL_RATIO`）时提示"几乎等于整屏"；截图必须放后台线程（`_CaptureThread`），不得在 GUI 线程同步截图；框选坐标以**图像像素坐标**为准（Qt 的 `QRect(左上, 右下)` 右下角是包含式的，必须按「左上+宽高」构造，否则宽度会多 1 像素——实测踩到）。新增/更换识别算法依赖必须走 `requirements.txt` 并说明理由（当前为 numpy + opencv-python-headless）。
- **多模板与多区域（2026-09-20 用户要求）**：`recognize_in_window` 的 `image_path` 接受**单个路径或路径列表**，两种形态必须同时成立：① **多张模板打同一块区域**——按用户给的顺序逐张尝试，**第一张达到阈值的直接用它的结果**（`matched_template` 记下是哪张，消息里写明"第 k/N 张"），读不出/报错的图**跳过并继续**下一张，全部落空时逐张列出结果（未命中 / 读不了的原因）；**多张模板共用同一张截图**（只截一次，保证各模板看到同一帧）。② **一张模板匹配屏幕多个区域**——命中多处时**全部返回**（按匹配度降序，`matches[0]` 即"默认使用值"），消息里逐处编号并标出使用值，条数由 `max_results` 封顶（调试页「最多列出」/CLI `--max-results`），**触顶时必须提示"可能还有更多"**。GUI 侧模板用 `QListWidget` 管理（添加可多选 / 移除选中 / 清空；框选生成后追加进列表），列表为空时不发起识别、只给提示。实测（真实 1920x1052 画面，模板 476x447）：第 1 张不中、第 2 张命中 4.4s；第 1 张就中 1.6s；一张模板贴到 3 处 → 3+1 处全部列出且中心坐标零误差。
- **多尺度匹配（2026-09-19 用户实测 bug：画面放大/缩小就识别不到；同日按用户要求改为两档搜索 0.3x→4.0x）**：识别必须默认做缩放搜索（`locate_all_scaled`，`DEFAULT_SCALE_RANGE = (0.30, 4.00)`、`SCALE_FAST_MAX = 2.00`）。搜索**分两档**（`_scale_tiers`）：先搜 0.3x–2.0x，**没命中才**把范围扩到 0.3x–4.0x 继续搜；第二档**不得重复扫**第一档已扫过的档位（`scanned` 集合，且沿用第一档的最佳候选与峰值状态）。每档内部仍是：粗搜比例 → 在最佳比例附近精修（步长 0.02）→ 在该比例下取全部命中，`Match.scale` 记录所用比例。五条硬约束：① **阈值必须在精修之后再判断**（真实缩放常落在粗搜两档之间：实测 0.75x 在粗搜只有 0.83、精修到 0.74x 是 0.95）；② 精修阶段只接受**严格更好**的分数（不得再套"贴近 1.0x"的平局规则，否则会把 1.40x 掰成 1.38x）；③ 每档结束粗搜的条件必须是**"越过峰值后回落"**（当前分数比最佳候选低 `SCALE_PEAK_DROP`=0.02 以上），且该最佳候选本身既够强（分数 ≥ 阈值+`SCALE_STRONG_MARGIN`）又足够大（候选面积 ≥ 原模板的 `SCALE_STRONG_AREA_RATIO`=30%，过小的缩放会给出虚高分数：实测 9×4 像素匹配到 0.96）；④ **禁止"遇到第一个够强的候选就停"**——分数是朝真实缩放缓慢爬升的，实测真值 3.50x 在粗搜 3.30x 就有 0.9018（> 阈值+0.05），一旦就此停住，±0.06 的精修窗口够不到真值，会报成 3.36x（分数 0.933 而真值处是 1.000，框比目标小一圈）；⑤ 第一档失败后必须真的把范围扩到 4.0x（有测试用 monkeypatch 记录实际评估过的比例守卫：第一档命中时**不得**评估 2.0x 以上的档位，第一档落空时**必须**跑出 2.0x 以上）。CLI `--no-scale` 可退回只按原始尺寸匹配。实测耗时（1920x1052 画面）：快搜命中 1.0x≈1.9s、1.5x≈2.3s、2.0x≈2.8s；需要第二档时 2.5x≈3.9s、3.5x≈4.0–4.9s、4.0x≈4.4–5.2s；画面里没有目标（两档都要扫）≈3.8s（其中快搜≈1.8s）。
- **取景鲁棒性（同日实测）**：本作（GPU 渲染 + 管理员运行）**PrintWindow 会返回纯黑帧**（PW_RENDERFULLCONTENT/PW_CLIENTONLY/BitBlt(窗口 DC) 全黑），只有桌面屏幕 BitBlt 拿得到画面。`capture_client_bgr` 必须：检测纯色帧（`is_blank_frame`：像素数 ≥64 且标准差 <2）→ 依次回退 PW_CLIENTONLY → BitBlt(窗口 DC) → 屏幕 BitBlt（**仅窗口在前台时**，否则会抓到被遮挡窗口的内容）→ 全失败抛可读错误（提示以管理员身份运行 / 让窗口可见）；**绝不允许把黑帧当成"未识别到目标"**。已知限制：极小模板（<40px）+ 小缩放时缩放判断可能不准（信息量不足，模板匹配固有限制）；`automation.window.screenshot_client`（窗口诊断截图）用 PrintWindow(PW_RENDERFULLCONTENT) 整窗渲染后按客户区偏移裁出客户区（对同类黑帧游戏可能仍存成黑图）。
- **取景原点必须是客户区左上（2026-09-20 用户实测 bug：识别坐标整体偏下）**：**窗口 DC（`GetWindowDC`）与 PrintWindow 的原点都是"窗口左上角"（含标题栏与边框），不是客户区左上**。因此：① BitBlt(窗口 DC) 的**源点必须用客户区偏移**（`window.client_area_offset(hwnd)`，实测本作 (9, 37)），**禁止写 (0, 0)** —— 写 (0,0) 会抓到"标题栏 + 客户区上半部分"：画面顶部多出标题栏、底部缺"标题栏高度"一截，识别坐标随之**整体偏下标题栏高度**（实测偏 37px，用户报的"坐标总是偏下"正是此因）；② PrintWindow 画的是**整个窗口**，必须**按窗口尺寸渲染、再按客户区偏移裁出客户区**（`_render_client_bits_printwindow`，与 `screenshot_client` 同一套几何），不能按客户区尺寸直接渲染；③ 屏幕 BitBlt 用 `ClientToScreen(hwnd, (0,0))`，天然以客户区左上为原点，是"原点正确"的参照实现，无需再裁。客户区偏移只在 `window.client_area_offset` 一处计算，其他取景代码一律复用；无边框全屏窗口该值天然为 (0, 0)。回归测试：`tests/test_automation/test_vision.py`（假 GDI 校验 BitBlt 源点与裁剪像素）+ `test_window.py::test_client_area_offset_*`。实机验证方法：抓一张客户区图 + 一张整屏图做模板匹配，图像左上角在屏幕上的位置必须等于 `ClientToScreen(0,0)`（实测修复前偏 (-9, -37) → 修复后 (0, 0)），且"识别出的客户区中心"与"整屏定位换算出的客户区中心"偏差 ≤3px（实测 0px）。
- 新增或更换**任何依赖**都必须改 `requirements.txt` 并在提交信息里写明理由与体积代价（当前：`numpy` + `opencv-python-headless`，使打包体积 +60–70 MB）。
- 占位任务（`order_hold`/`feature_3`/`feature_4`）：**只允许**「进入日志（含"该功能尚未实现真实逻辑（规划中）"原文）+ 每轮一条心跳日志 + 响应停止」；禁止产生任何输入、禁止读 params、禁止写推测性业务逻辑（有测试守卫）。
- 文件长度控制：单个文件超过 400 行必须先考虑拆分；超过 600 行必须拆分（模板生成的 UI 文件除外）。
- **禁止用 PowerShell 文本命令改写仓库文件**（2026-09-19 实测事故）：`Get-Content -Raw | Set-Content` 在 Windows PowerShell 5.1 下会**按 ANSI(GBK) 读取无 BOM 的 UTF-8 文件**，中文被写成乱码（当时把 `PROJECT_SPEC.md` 679 行改坏、`config.example.json` 的中文关键字损坏，靠 `git checkout --` 恢复）。批量改写请用 Python 显式 `encoding="utf-8"`（写回不加 BOM），或用 `edit`/`write` 工具。

## 3. 禁止事项（红线）

1. 禁止读写游戏进程内存、禁止拦截/伪造/重放游戏网络封包——**连接口都不得预留**。（原「禁止 DLL 注入 / 驱动 / 过检测技巧」的限制已按用户要求取消，见 `PROJECT_SPEC.md` §4.1；内存与封包两条用户曾要求取消，工程负责人未执行并给出替代方案，见 §4.2。）
2. 禁止存储或传输账号/密码/token/设备指纹等凭证与个人敏感数据。联网功能不再全面禁止（2026-09-15 取消，见 `PROJECT_SPEC.md` §4.1），但任何联网行为须经用户逐项授权，且**不得上传日志/配置/截图等本地数据**。
3. 禁止在**测试**里进入真实输入模式：`dry_run` 生产默认已是 `false`，但单测必须恒走干跑（`tests/conftest.py` 的 autouse 夹具把 `AppConfig.default()` 的 `dry_run` 强制为 `True`；只有 `@pytest.mark.real_defaults` 标注的默认值断言测试可例外）。真实模式必须由用户显式触发（询问频率可配置，默认每次询问；原"禁止绕过确认"的绝对禁令已按用户要求改为可配置）。
4. 禁止静默修改/删除配置文件字段：schema 变更必须 `schema_version +1` + 迁移函数 + 单测。
5. 禁止吞异常：任何 `except` 必须记录日志并给出可解释的降级路径。
6. 禁止引入未批准的第三方包；禁止 `pip install` 后只在自己机器生效而不更新 requirements。
7. 禁止重写历史（force push）、禁止把 `user_data/config.json`、日志、截图、构建产物提交入库。
8. 禁止删除/破坏既有测试来让测试通过；测试失败必须修代码或（经用户同意后）修测试。
9. 禁止一次性生成超过一个阶段的代码；禁止跨阶段“顺手重构”。
10. 禁止在游戏窗口未找到、已最小化或不可见时执行输入注入（真实键鼠通道会在每次输入前置顶/置前并回读复核，无法确保时绝不输入）。

## 4. 测试要求

- 框架：pytest；测试目录 `tests/` 与 `src/luoluotool/` 同构。
- 覆盖率目标（整体 ≥ 70%）：config、core 模块 ≥ 90%。
- 必须覆盖的测试类型：
  - 配置：默认值、非法值校验、损坏文件恢复、schema 迁移、原子保存；
  - core：任务注册、顺序执行、循环间隔、失败计数、停止中断；
  - automation：用注入的假 `sender` 验证消息调用序列（**单测永不产生真实输入**）；
  - gui：`QT_QPA_PLATFORM=offscreen` 冒烟（窗口可创建、四页签存在、开关联动）。
- 运行命令（全绿才算通过）：
  - `python -m pytest -q`
  - `python -m luoluotool --validate-config`
  - `python -m luoluotool --smoke-gui`
  - `python -m luoluotool --measure-layout`（改动过页签/布局时必须跑，报告须为「不改变任何高度」）

## 5. 提交要求

- Conventional Commits，中文说明，范围前缀必带：
  - `feat(config): 新增 schema v2 迁移`
  - `fix(core): 修复停止事件未传递到子任务`
  - `test(automation): 补充真实键鼠调用序列断言`
- 一次提交只做一件事（一个阶段内可以多次提交，禁止“一锅端”大提交）。
- 提交前自检：全量测试通过；无未使用的 import；无调试 `print`；变更文件列表与阶段「本次只做什么」一致。

## 6. 小步推进工作流（AI 必须遵守）

执行任意阶段时，按以下节奏，每步都给出结果让用户确认：

1. **复述**：用 3–5 行说明本阶段要做什么、交付物是什么。
2. **列清单**：列出要新建/修改的文件清单（先列，再动手）。
3. **测试先行**：先写本阶段的失败测试。
4. **最小实现**：只写让测试通过的最少代码。
5. **自验收**：运行该阶段全部验收命令，输出结果。
6. **汇报**：总结改动、测试结果、遗留事项；**不自动开始下一阶段**。

文件修改策略：
- 新建文件一次一个；修改文件用精确补丁，不整文件重写；
- 每完成一个文件，先跑相关测试，再继续下一个；
- 若连续 3 次修复同一处，停下来向用户解释根因，不要反复猜测。

## 7. 避免“一次性生成不可维护代码”的硬规则

- 每个阶段的净增代码量上限：**300 行**（含测试）。超出的必须拆阶段或先与用户确认。
- 新增模块必须先定义公共接口（函数签名/类协议）并写进 `PROJECT_SPEC.md` 第 8 节表格，再实现。
- 占位功能（预留开关等）只允许「开关 + 空执行 + 日志说明」，不允许写推测性的大段逻辑。
- 任何“以后可能用到”的抽象，一律不写；等真实需求出现再由对应阶段引入。
- 阶段结束必须执行 `git diff --stat` 自查：若改动范围明显超出「本次只做什么」，视为违规，必须回退多余部分。
- **按需构建 exe（2026-09-19 用户要求）**：只有用户**明确要求打包**时才执行 `packaging\build.ps1`；
  日常改动一律**不要重新构建**（只跑 `pytest -q` + `--validate-config` + `--smoke-gui` + `--measure-layout`
  这几条廉价验收命令即可）。产物体积/启动耗时等只在构建任务里测量一次，不必每次改动复测。
- **构建产物一律不入库（2026-09-19 用户要求）**：`dist/`、`build/`、`*.exe`、`*.pyd`、`*.dll`、`*.zip`
  与 PyInstaller 中间产物都被 `.gitignore` 忽略；提交前不得 `-f` 强加它们。守卫测试：
  `tests/test_packaging.py::test_no_build_artifacts_are_tracked`（扫描 git 索引）。

## 8. 关键命令速查（在项目根目录执行）

```bash
# 环境（Phase 0 一次性）
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

# 日常
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --version
.venv\Scripts\python -m luoluotool --validate-config
.venv\Scripts\python -m luoluotool --smoke-gui
.venv\Scripts\python -m luoluotool --measure-layout
```
