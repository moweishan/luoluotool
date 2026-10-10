# AGENTS.md — LuoLuoTool 长期开发规范

> 本文件面向 Codex / Cursor / Claude Code / Windsurf 等 AI 编程代理。
> **所有开发动作（包括规划、写码、修改文件、跑命令）都必须遵守本文件。**
> 与 `PROJECT_SPEC.md` 冲突时，以 `PROJECT_SPEC.md` 的边界条款为准。

---

## 1. 开发原则

1. **小步推进**：每次只完成一个可验证的增量（见第 6 节）。禁止一次性生成整个项目。
2. **范围服从用户任务**：只完成用户本次明确要求的增量；未要求的后续功能不得顺手实现，范围不清时先澄清。
3. **先测试后实现**：核心逻辑（config/core/automation 的纯逻辑部分）先写失败测试，再实现。
4. **分层单向依赖**：`gui → core → automation/utils`。`core` 不得 import PySide6/win32；`automation` 不得 import PySide6；任何反向 import 都视为缺陷。
5. **UI 与业务分离**：GUI 文件里不允许出现任务流程、输入注入、文件读写等逻辑；只允许出现事件绑定与展示。
6. **输入安全**：`automation.dry_run` 出厂默认 `false`；真实模式由用户显式启动，确认频率可配置，默认每次确认。真实输入必须支持 F8 急停和客户区越界校验。单测恒走干跑，不得产生真实输入。当前输入统一使用 `SendInput`，新增输入通道须遵守 `PROJECT_SPEC.md`「项目边界与安全」。
7. **可观测**：所有关键动作写日志；异常必须记录完整堆栈；不允许 `pass` 掉异常或 `except Exception: continue` 式的吞错。
8. **最小依赖**：只允许使用 `requirements.txt` / `requirements-dev.txt` 中列出的包。需要新依赖时：先改 requirements 文件 → 在提交说明写明理由 → 才可 import。

## 2. 编码要求

### 通用规则

- Python 3.11+，UTF-8，4 空格缩进；所有公共函数签名提供类型注解。
- 配置模型使用 `dataclass`；JSON 通过临时文件和 `os.replace` 原子写入。
- 日志使用标准库 `logging` 和模块级 `logging.getLogger(__name__)`；禁止用 `print` 替代日志，CLI 输出除外。
- 文件、窗口和进程操作必须处理失败路径，包括窗口不存在、权限不足、配置缺失和磁盘满；提供可读错误并保持程序可用。
- 时间间隔等配置必须校验上下限；界面与校验器共用 `config/models.py` 或 `core` 中的常量，不得各自重复定义。
- 模块级 import 不得被同名赋值遮蔽；共享常量、函数和测试夹具只保留一份定义，删除无用 import 与死常量。`PW_*` 取景标志集中在 `automation/vision.py`，GUI 测试共用 `tests/gui_helpers.py`。
- 跨模块共用的函数和类使用公共名称，不通过下划线私有名建立依赖。
- 新增或更换依赖先更新对应 requirements 文件，并在提交说明中写明理由与打包体积影响。
- 修改仓库文本使用精确补丁或 Python 显式 `encoding="utf-8"`，写回不加 BOM。禁止用 `Get-Content -Raw | Set-Content` 等 PowerShell 文本命令改写 UTF-8 仓库文件。

### 窗口与真实输入

- 真实输入统一使用 `SendInput`；`SendInput` 和 `SetCursorPos` 只允许出现在 `automation/real_input.py`。按键名称与解析集中在 `utils/keys.py`，配置校验与 GUI 即时拒绝未知键名。
- 每次点击、按键或滑动前检查停止事件，停止请求发出后 500 ms 内停止动作序列。长等待按切片推进，禁止用整段 `time.sleep(n)` 阻塞急停。
- 每次输入前确认游戏窗口位于最前：最小化时先 `SW_RESTORE`，再按需 `HWND_TOPMOST` 置顶、`SetForegroundWindow` 置前，失败时用 `AttachThreadInput` 兜底并回读复核。无法确认窗口在最前时抛可读错误，不发送输入。
- 置顶必须成对：输入结束或置前失败时，取消本次设置的置顶；只在本次确实置顶过时使用 `TOP_FLAGS` 取消，不能清除其他程序设置的置顶。
- 点击坐标必须在客户区 `[0,width)×[0,height)` 内；滑动的起点与终点都必须在客户区内。越界或读不到客户区时跳过整个动作并写 WARNING，包含坐标与客户区尺寸。真实和干跑通道共用 `check_points_in_bounds(points, check)` 与 `point_in_client_area`，点击检查一个点，滑动检查两个点。
- 点击接口接受 `hold_seconds: float | None`：`None` 使用 `CLICK_HOLD_SECONDS`＝40 ms，`0` 表示瞬时点击。`send_left_click` 按 `CLICK_SLICE_SECONDS`＝50 ms 切片检查停止事件；正常结束、中断或等待抛异常都在 `finally` 抬起左键，`RealInputSender.click_at` 必须传入自身停止事件。
- 点击时间线：置顶/置前后等待 `FRONT_SETTLE_SECONDS`＝200 ms；光标先到起点与目标的中点，间隔 `CLICK_MOVE_STEP_SECONDS`＝30 ms 后到目标；到位后等待 `INPUT_SETTLE_SECONDS`＝80 ms 再按下。松手后等待 `CLICK_RESTORE_DELAY_SECONDS`＝350 ms，再按 `restore_cursor_after_click` 使用 `restore_cursor_smooth` 分帧还原光标，禁止一次跳回。不得为提速随意调小这些常量，调整时须考虑游戏对输入和指针位置的帧采样。
- 按下左键前调用 `_verify_before_press`，一次记录客户区尺寸、客户区目标到屏幕坐标的换算、实测光标位置与偏差、光标处顶层窗口、前台与置顶状态、命中窗口是否为目标窗口。偏差超过 `CLICK_CURSOR_TOLERANCE_PX`＝4 px 时跳过点击并写 WARNING；命中其他窗口或读取光标失败时记录 WARNING，但继续本次点击。
- 键盘支持单键、组合键和长按；组合键逆序释放修饰键，长按切片检查急停，并在任何退出路径释放按键。`send_key_hold` 的切片下限为 0.01 秒。
- 滑动起终点经 `ClientToScreen` 换算，`build_drag_path` 使用 `interpolate_points(..., easing=ease_out_quad)`，约 60 Hz、至少 4 步；末尾保持 `DRAG_TAIL_HOLD_STEPS` 静止帧后松手。滑动前清理残留左键状态，每帧核对移动返回值并检查停止事件，失败时抛可读错误。
- 滑动在任何退出路径都通过 `finally` 释放左键；松手后复查 `VK_LBUTTON`，未抬起则补发，仍失败则报错。按 `restore_cursor_after_click` 还原光标时，先等待 `DRAG_RESTORE_DELAY_SECONDS`，再分帧平滑移回；等待被中断时仍须还原。

### GUI、调试与单步运行

- 长任务放在后台 `QThread`，GUI 主线程不 sleep 或忙等；运行期间禁用启动按钮和对应动作按钮，防止重复执行。
- 所有页签继承 `gui.widgets.ScrollablePage`，内容布局使用 `QVBoxLayout(self.content)`，不得建在 `self` 上；建议尺寸统一为 `PAGE_SIZE_HINT`。日志面板保留最小高度，页签区 `stretch=1`。改动页签或布局后检查挂载/卸载调试页不改变高度。
- 开发者调试复用正式输入通道 `build_channel`：干跑只写日志，真实模式遵守窗口、越界和急停规则。测试动作放后台线程，停止时释放按键。
- 未开启开发者调试时整页禁用，干跑与光标还原选项不写配置并回滚勾选；`_debug_actions_allowed()` 拒绝测试、诊断和布局测量请求，关闭开关时中断调试线程。
- 调试页单点与连点的点击时长共用 `core.debug.CLICK_HOLD_RANGE_MS`＝(0, 5000) ms，默认 `DEFAULT_CLICK_HOLD_MS`＝40 ms，经 `run_single_click(..., hold_ms=...)` 校验后传秒。`None` 与 `0` 语义不同；连点每次使用相同时长，点击结束后才等待间隔。
- 单步运行开关位于调试页顶部，仅本次运行有效、不存盘；主界面停止按钮右侧的「上一步 / 下一步」仅在开启单步时显示。一个点击、滑动或按键动作各算一步；上一步只回退指针并还原对应光标位置，不重放动作。
- `StepController` 线程安全，非单步时不记录状态；执行线程在动作前调用 `gate()`，界面请求下一步或上一步。重复的下一步请求被忽略并给出提示；关闭开关、急停和运行结束必须唤醒等待者。
- 单步光标记录 `_after[k]` 表示指针停在第 k 步时的位置，0 号位由 `begin_run(initial_cursor=...)` 保存；上一步使用回退后指针对应的位置。
- 单步状态通过 `StepModeBridge` 信号回 GUI；光标回位由任务线程通过 `InputSender.move_cursor()` 完成，干跑只记日志，真实模式只移动、不点击、不抢前台，失败写 WARNING。两个输入通道都提供 `cursor_position()` 和 `move_cursor(x, y)`。
- `TaskContext` 提供 `stepper`、`step_gate()` 和 `step_done()`；`Runner` 可接收或在启动前挂载 stepper，GUI runner 工厂保持只接收 config 的签名。占位任务 A 使用有序步骤表与单步门；初始化 `build_step_controls()` 必须先于 `_apply_developer_mode()`。

### 图像识别与截图

- `automation/vision.py` 不依赖 PySide6。识别前确认窗口存在且未最小化，失败转成 `RecognizeResult`，不把异常抛到 GUI 线程；识别只返回结果，不发送输入。
- 图像读取使用 `np.fromfile` + `cv2.imdecode`，写入使用 `cv2.imencode` + `tofile`，确保中文路径可用。`load_template` 在读取阶段拒绝纯色模板；模板大于截图时抛可读 `VisionError`。
- 匹配结果的中心、左上角和尺寸均为客户区坐标；多处命中按匹配度降序返回，`matches[0]` 为默认使用值。`max_results` 封顶时提示「可能还有更多」。
- `recognize_in_window` 接受单路径或路径列表；多模板共用一张截图，按给定顺序尝试，使用第一张达到阈值的结果，并记录 `matched_template` 与模板序号。读图失败记录原因并继续，全部失败时逐张说明结果；GUI 模板列表为空时只提示。
- 默认启用多尺度匹配，先搜 0.3x–2.0x，未命中再扩到 0.3x–4.0x；第二档不重复已扫描档位，并沿用最佳候选与峰值状态。每档粗搜后在最佳比例附近按 0.02 步长精修，再取全部命中，`Match.scale` 记录比例；CLI `--no-scale` 只按原始尺寸匹配。
- 多尺度阈值在精修后判断；精修只接受严格更好的分数。提前结束粗搜须越过峰值后回落至少 `SCALE_PEAK_DROP`＝0.02，且最佳候选分数达到阈值 + `SCALE_STRONG_MARGIN`、面积至少为原模板的 `SCALE_STRONG_AREA_RATIO`＝30%；不能遇到第一个强候选就停止。第一档失败后必须执行扩展搜索。
- `capture_client_bgr` 检测纯色或黑帧（`is_blank_frame`：像素数至少 64、标准差小于 2），依次回退 `PW_CLIENTONLY`、窗口 DC 的 BitBlt、屏幕 BitBlt；屏幕取景只在窗口位于前台时使用。主路径抛异常也继续回退，全部失败时给出含原因的可读错误，不能把黑帧报成未命中。
- 窗口诊断截图 `automation.window.screenshot_client` 复用 `capture_client_bgr`，生成真实 PNG 并进行黑帧检测。
- 取景原点统一为客户区左上：窗口 DC 的源点使用 `window.client_area_offset(hwnd)`；PrintWindow 按整个窗口尺寸渲染，再按客户区偏移裁剪；屏幕 BitBlt 使用 `ClientToScreen(hwnd, (0,0))`。偏移只计算一份，无边框窗口为 (0, 0)。
- 取景几何验证以 `ClientToScreen(0,0)` 为基准，识别中心与整屏定位换算后的中心偏差不超过 3 px。极小模板与小缩放可能缺少足够信息，不能承诺缩放判断准确。
- 使用识别底图作为匹配源的离线识别尚未实现，不得对外宣称可用；后续设计见 `BUG_HUNT_GUIDE.md` 对应待办。

### 图片目录与模板框选

- `assets/templates/` 保存用户整理的识别图片并入库，调试页「添加图片…」默认打开这里；`assets/screenshots/` 保存工具截图的识别底图；`assets/anchors/` 保存框选产物。三个目录用 `.gitkeep` 入库，后两个目录的运行时素材不入库。
- `.gitignore` 排除 `assets/anchors/*.png` 和 `assets/screenshots/*.{png,jpg,jpeg,bmp,webp}`，不排除 `assets/templates/`。`tests/test_paths.py` 约束模板图片已 `git add`，截图与框选目录除 `.gitkeep` 外没有跟踪文件。
- 框选截图放在后台 `_CaptureThread`；调试页产物命名为 `anchor_<时间戳>.png`，日常任务页为 `{建筑}_岛屿{N}_<时间戳>.png`。
- 「保存为模板」必须调用 `save_selection`，只裁剪并保存手动选区；没有选区、尺寸小于 `MIN_SELECTION_SIZE`＝8 px 或保存失败时不写文件、不关窗，只提示原因。选区面积达到整图 `NEAR_FULL_RATIO`＝95% 时提示「几乎等于整屏」。
- 选区以图像像素为准，`QRect` 用左上角和宽高构造；选区外拖拽重新框选，内部拖拽移动，四角与四边共八个 10 px 手柄调整大小。移动不得越界、缩放不得小于最小尺寸，悬停显示对应指针，保存使用修改后的选区。
- 框选图使用 `StrongFocus` 并在弹窗打开时取得焦点；方向键移动 1 个图像像素，Shift + 方向键移动 10 像素，Ctrl + 方向键将对应边向外移动 1 像素，Ctrl + Shift + 方向键向内移动 1 像素。无选区时不操作，微调仍受边界和最小尺寸约束。
- 选区外压暗，不改变选区内像素；拖拽时显示宽高与客户区左上坐标气泡，靠边翻转、松手消失。Esc 在拖拽中撤销本次拖拽，有选区时清空，无选区时交给对话框关闭；双击清空。
- Alt + 拖手柄围绕中心对称缩放，按下时或拖动中按住均生效；有选区时空格 + 左键或右键拖拽移动选区，无选区时空格 + 左键平移画面。
- 滚轮以鼠标处图像像素为锚点缩放，每格 `WHEEL_ZOOM_STEP`＝1.25，相对整图适配倍率限制在 0.5–8。中键拖拽平移，至少保留 `MIN_VISIBLE_PX`＝60 px 可见区域；图像居中按控件与图像尺寸差的一半计算，不用 `QRect.center()`。
- HUD 显示选区尺寸、缩放和鼠标客户区坐标；放大镜为 132 px、6 倍整数放大，标出当前像素与坐标，取样不越界、靠边翻转。鼠标移动时重绘，离开控件时隐藏；图像显示后即可使用，不依赖已有选区。
- 质量评估使用 `assess_region_quality` 的灰度标准差与 Canny 边缘占比，大图按步长抽样到 `QUALITY_SAMPLE_PX`＝128；抽样判为 `flat` 时用全分辨率复核，避免误拒细纹理。
- `flat` 拒绝保存，`low` 只提示，`ok` 正常保存；低辨识度阈值为 `QUALITY_LOW_STD`＝8.0、`QUALITY_LOW_EDGE_RATIO`＝0.01。信息行显示辨识度，保存按钮和 `save_selection()` 都校验，程序化保存也不能绕过。
- 保存侧拒绝 `flat`，读取侧 `load_template` 拒绝纯色；手工模板可能仍有误匹配风险。调整质量规则时同步读取、保存与文档，并确保真实模板仍可用。
- 「在本图试识别」调用 `probe_region_on_image`，将选区作为模板在同一截图上做 1:1 匹配；阈值使用调试页当前值，越界或太小抛 `VisionError`，`flat` 选区直接提示且不启动线程。
- 试识别结果排除自身命中后展示重复数；零重复只表述为「本图 1:1 匹配下只命中你框的这一处」，不能保证正式识别不误匹配。其他位置最多列出 `PROBE_MAX_LISTED`＝5 个中心坐标并画橙框与序号，触顶提示可能更多；包括自身在内仍零命中时提示异常、请反馈。
- 试识别通过 `gui/workers.start_probe_thread()` 执行，运行期间禁用按钮、结果经信号回 GUI。选区变化使结论与标记作废，收到结果时比较 `result.region` 与当前选区，丢弃不一致的结果。
- 试识别关窗调用 `request_stop()`，只断开本弹窗的槽，保留 `finished` 的清理槽；线程由 `ACTIVE_PROBES` 强引用至自然结束，GUI 不调用 `wait()` 阻塞。按钮按 `probe_in_flight()` 判定，完成槽须确认 `self.sender() is self._probe_thread` 才清空引用。
- 缩放滑条以 2 为底使用 1000 个对数刻度，相对适配范围 50%–800%；`zoom_slider_to_zoom` 与 `zoom_to_slider` 精确互逆，不经过整数百分比。
- 滑条使用 `NoFocus`，保留方向键微调；滑条通过 `set_zoom_relative()` 以选区中心为锚点，滚轮与重置同步回滑条和标签，同步时 `blockSignals`。双击滑条调用 `zoom_to_actual()` 进行 1:1 显示。
- 重置执行整图适配、平移归零、清空选区、作废试识别结论，并把焦点交回框选图。双击、Esc 和重置统一调用 `CropView.clear_selection()`。

### 日常任务页与参考图

- 控件 `objectName` 使用设计稿 id，由 `DESIGN_CONTROL_IDS` 核对，不能自行按前缀派生。HTML→Qt 的映射按 `gui/pages/daily.py` 文件头约定，设计稿与页面结构同步。
- 鸡舍、土地、水产养殖分组由 `BUILDINGS` 统一生成，不重复复制布局；文案使用「所在岛屿编号」和「自动识别存量最少的产物并优先制造」。
- 每组最后一行左侧为参考图路径与选择/截取按钮，中间为所选图片，右侧为示例图片；三列相邻且顶边对齐。`ImagePreview` 与占位框最小尺寸为 160×84，显示图片不得改变页签高度。
- 配置字段平铺在 `features.daily_tasks`，名称对应设计稿 `data-key`：`coop_island`、`land_island`、`aqua_island`、`coop_island_ref_image`、`land_ref_image`、`aqua_ref_image`、`auto_produce_least`。总开关复用 `enabled`，循环复用 `loop.enabled` 与 `loop.interval_seconds`。
- `set_config()` 只显示配置，使用 `_loading` 防止信号误写；只有用户改动才更新配置并置脏。总开关关闭时日常任务不入队，卡订单、功能三和功能四不受影响；被勾选但受总开关阻挡的任务通过 `blocked_daily_task_ids()` 写 WARNING 并提示。
- 循环间隔界面为 1–720 分钟，配置保存秒；共用 `LOOP_INTERVAL_MINUTES_RANGE` 与换算函数。非整数分钟按最近分钟显示并夹到范围，装载时不回写配置，用户修改数字框后才写回。
- `auto_produce_least` 由 `AUTO_PRODUCE_LEAST_READONLY` 控制只读，显示只读文案与 tooltip，使用 `NoFocus` 和 `eventFilter` 拦截点击，不通过禁用控件表示只读；程序仍可 `setChecked()`，配置字段保留且默认 False。
- 页面只发出选图、截图、预览、移除和清空信号；文件、截图、框选、读图与配置写入由 `DailyMediaController` 负责。主窗口将其 `request_stop()`、`worker_threads()` 接入急停、运行状态与关窗处理。
- 截取游戏画面前调用 `bring_to_front`，按 `gui/daily_workers.FRONT_SETTLE_SECONDS`＝0.4 秒切片等待后截图；停止时中断。使用 `TemplateCropDialog` 保存框选区域到 `assets/anchors/`，失败记录日志和状态栏提示，保持原有参考图，不发通知或弹错误窗口。
- 选图使用 `load_template` 与 `assess_region_quality` 校验，低辨识度只提示。解码放 `ReferenceImageLoader`，线程只解码，GUI 线程写配置；按用途代次丢弃迟到或作废结果，`PickBatch` 全批到齐后只写一次，合格图片正常采纳，被拒图片逐张说明。
- 配置图片路径使用 `to_config_path` / `resolve_config_path`，仓库内为相对仓库根的 POSIX 路径，仓库外为绝对路径。`resolve_config_path` 不作为安全边界；文件缺失或改名只提示并清缩略图，不静默改配置。
- 参考图使用 `list[str]`，每组最多 `MAX_REFERENCE_IMAGES`＝10 张；迁移与 `normalize_reference_paths` 兼容单路径、空值和畸形值，迁移测试断言最终结构并保留已有字段。配置加载时会规范化内容，未知字段可能被移除。
- 「选择图片…」多选并替换整批，超过 10 张只取前 10 张并提示，路径去重，超过 260 字符的路径当场拒绝；「截取游戏画面」追加并选中新图，不重复添加，满额时提示先移除。
- 缩略图横排、带序号与选中高亮，单击切换大图、双击打开工具内预览；单图路径完整显示，多图显示数量与文件名，tooltip 逐行列出完整路径。预览对话框不用 `exec()`。
- 缩略图 `×` 角标悬停红底白叉，提示移除序号；单击只移除对应图片、不改选中项，双击不触发放大。清空按钮在无图时禁用，右键保留移除/清空菜单；各入口共用控制器信号。
- 移除或清空先调用 `confirm_destructive`，默认取消，列出将删除的文件与相对路径；取消时配置、界面与磁盘均不变。
- 只删除 `managed_roots()` 中 `assets/templates/` 和 `assets/anchors/` 的文件；其他目录只移除列表引用。被其他建筑引用的文件不删除；先通过 `plan_deletions()` 规划，再 `delete_files()`，单个失败写 WARNING 并继续，状态栏说明删除数及未删除原因。
- 删除不是工具内可撤销操作：已入库模板可通过 Git 恢复，未入库的框选产物不能依赖 Git 恢复；确认提示须说明。
- 确认框测试使用 `_no_real_modal_dialogs` 防止真实模态窗口阻塞，替身必须打在实际调用命名空间，包括 `daily_deletion`。

### 配置与运行状态

- `config/validation.migrate` 的每一步独立捕获异常，记录 WARNING 并回退原始 dict；`store.load` 对迁移异常走 `_recover`，备份坏文件并使用默认值。
- `store.save` 先校验后落盘，非法配置抛 `ConfigSaveError` 并保持磁盘原样，所有失败路径清理临时文件；GUI 捕获保存错误并弹窗与提示。界面超限时写 WARNING 并回滚输入，不静默截断。
- 磁盘 `schema_version` 高于程序时只读，加载不写盘，返回默认值并告警；覆盖保存前备份为 `config.json.bak-v<磁盘版本>-<时间戳>`。
- `setup_logging(level, max_file_mb, backup_count)` 幂等，重复调用不叠加 handler，参数变化时重建 `RotatingFileHandler`；GUI 加载配置后按 `config.logging.*` 应用日志设置。
- 「停止」对任务与调试线程都有效，任务运行和调试动作双向互斥；关窗处理任务、调试、截图与框选相关线程，对未退出线程记录 ERROR，试识别线程按其独立生命周期规则处理。
- `core/state.py` 状态读写加锁，迁移使用 `try_transition`，非法迁移返回 False；允许 `STOPPING → ERROR`，保留真实错误。
- 热键注册失败在日志、状态栏和设置页红字提示；保存、重载或恢复默认后重新注册热键。
- `order_hold`、`feature_3`、`feature_4` 占位任务只记录进入日志、每轮心跳并响应停止；进入日志包含「该功能尚未实现真实逻辑（规划中）」。不发送输入、不读取 params、不写推测性业务逻辑。
- 程序不实现通知、推送或上报，也不预留其开关、接口或依赖。远程加载/更新配置仍为未实现计划，按 `PROJECT_SPEC.md`「远程配置计划」约束，不提前埋入联网模块或空接口。

### 模块拆分与维护

- 单文件超过 400 行先考虑拆分，超过 600 行必须拆分，模板生成的 UI 文件除外；测试文件同样适用。
- 拆分使用脚本按 AST 行区间原样搬运，函数体与同名定义保持不变，并通过 AST 逐定义比对留下证据；原模块再导出公共名称，保持调用兼容。
- 测试里的 `monkeypatch.setattr` 跟随实现调整到实际调用的模块，删除用例时将覆盖迁移到适当层，不丢失覆盖；清理搬运后无用的 import。
- 拆分完成后运行全量测试、GUI 冒烟与布局测量，并更新 `BUG_HUNT_GUIDE.md` 符号行号索引，`python tools/check_guide_index.py` 必须零漂移。
- 修改 `gui/dialogs/crop_view.py` 前，先将 `paintEvent`、`_paint_dim_mask` 和 `_paint_probe_rects` 原样拆为 `CropPaintMixin`。

## 3. 禁止事项（红线）

1. 禁止读写游戏进程内存、禁止拦截/伪造/重放游戏网络封包——**连接口都不得预留**。（见 `PROJECT_SPEC.md`「项目边界与安全」。）
2. 禁止存储或传输账号、密码、token、设备指纹等凭证与个人敏感数据。联网行为须经用户逐项授权，不上传日志、配置、截图等本地数据。程序不实现通知、推送或上报，也不预留接口；唯一计划中的联网用途为启动时加载/更新远程配置，按 `PROJECT_SPEC.md`「远程配置计划」执行，未实现前不得宣称可用。
3. 单测必须恒走干跑（`tests/conftest.py` 的 autouse 夹具强制 `AppConfig.default().dry_run=True`）；`@pytest.mark.real_defaults` 仅用于生产默认值断言，不得产生真实输入。真实模式由用户显式触发，确认频率可配置、默认每次确认。
4. 禁止静默修改/删除配置文件字段：schema 变更必须 `schema_version +1` + 迁移函数 + 单测。
5. 禁止吞异常：任何 `except` 必须记录日志并给出可解释的降级路径。
6. 禁止引入未批准的第三方包；禁止 `pip install` 后只在自己机器生效而不更新 requirements。
7. 禁止重写历史（force push），禁止将 `user_data/config.json`、日志、工具截图和构建产物入库。`assets/templates/` 中人工整理的识别图片入库，`assets/screenshots/` 的识别底图与 `assets/anchors/` 的框选产物不入库。
8. 禁止删除/破坏既有测试来让测试通过；测试失败必须修代码或（经用户同意后）修测试。
9. 禁止一次性生成超过一个阶段的代码；禁止跨阶段“顺手重构”。
10. 禁止在游戏窗口未找到、已最小化或不可见时执行输入注入（真实键鼠通道会在每次输入前置顶/置前并回读复核，无法确保时绝不输入）。

## 4. 测试要求

- 执行范围：只有包含代码修改（源代码、测试代码或脚本的新增、修改、删除）的提交才执行本节测试与验收命令；仅文档、`.gitignore` 等非代码修改不执行测试。
- 框架：pytest；测试目录 `tests/` 与 `src/luoluotool/` 同构。
- 覆盖率目标（整体 ≥ 70%）：config、core 模块 ≥ 90%。
- 必须覆盖的测试类型：
  - 配置：默认值、非法值校验、损坏文件恢复、schema 迁移、原子保存；
  - core：任务注册、顺序执行、循环间隔、失败计数、停止中断；
  - automation：用注入的假 `sender` 验证消息调用序列（**单测永不产生真实输入**）；
  - gui：`QT_QPA_PLATFORM=offscreen` 冒烟（主窗口与页签可创建、开关联动）。
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
- 提交前自检：包含代码修改时，全量测试通过，并检查无未使用的 import、无调试 `print`；所有提交都要核对变更文件列表与本次任务范围一致。

## 6. 小步推进工作流（AI 必须遵守）

执行任意阶段时，按以下节奏，每步都给出结果让用户确认：

1. **复述**：用 3–5 行说明本阶段要做什么、交付物是什么。
2. **列清单**：列出要新建/修改的文件清单（先列，再动手）。
3. **测试先行**：代码变更先写本阶段的失败测试；仅文档等非代码变更跳过。
4. **最小实现**：只写让测试通过的最少代码。
5. **自验收**：代码变更运行该阶段适用的测试与验收命令，输出结果；非代码变更只核对内容与差异。
6. **汇报**：总结改动、测试执行或跳过情况、遗留事项；**不自动开始下一阶段**。

文件修改策略：

- 新建文件一次一个；修改文件用精确补丁，不整文件重写；
- 每完成一个代码文件，先跑相关测试，再继续下一个；非代码文件只核对内容与差异；
- 若连续 3 次修复同一处，停下来向用户解释根因，不要反复猜测。

## 7. 避免“一次性生成不可维护代码”的硬规则

- 每个阶段的净增代码量上限：**300 行**（含测试）。超出的必须拆阶段或先与用户确认。
- 新增模块必须先定义公共接口（函数签名/类协议）并在 `PROJECT_SPEC.md` 中说明模块职责，再实现。
- 占位功能（预留开关等）只允许「开关 + 空执行 + 日志说明」，不允许写推测性的大段逻辑。
- 任何“以后可能用到”的抽象，一律不写；等真实需求出现再由对应阶段引入。
- 阶段结束必须执行 `git diff --stat` 自查：若改动范围明显超出「本次只做什么」，视为违规，必须回退多余部分。
- **按需构建 exe**：只有用户**明确要求打包**时才执行 `packaging\build.ps1`；
  日常改动一律**不要重新构建**；包含代码修改时按第 4 节执行测试与验收命令，非代码修改不执行测试。
  产物体积/启动耗时等只在构建任务里测量一次，不必每次改动复测。
- **构建产物一律不入库**：`dist/`、`build/`、`*.exe`、`*.pyd`、`*.dll`、`*.zip`
  与 PyInstaller 中间产物都被 `.gitignore` 忽略；提交前不得 `-f` 强加它们。守卫测试：
  `tests/test_packaging.py::test_no_build_artifacts_are_tracked`（扫描 git 索引）。

## 8. 关键命令速查（在项目根目录执行）

```bash
# 开发环境
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt

# 日常
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --version
.venv\Scripts\python -m luoluotool --validate-config
.venv\Scripts\python -m luoluotool --smoke-gui
.venv\Scripts\python -m luoluotool --measure-layout
```
