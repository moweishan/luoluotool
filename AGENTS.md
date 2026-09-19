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
- **滑动越界硬规则（2026-09-19 同日追加，用户要求）**：滑动（`drag`）的**起点与终点都必须**在窗口客户区内，任一端越界或读不到客户区就**整段跳过**并写 WARNING（"滑动起点 (x, y)、终点 (x, y) 不在游戏窗口内（…），已跳过本次滑动"）。判定共用 `check_points_in_bounds(points, check)`，点击传一个点、滑动传两个点，真实与干跑通道共用同一份逻辑。
- 开发者调试页（`gui/pages/debug.py` + `core/debug.py`）只允许复用正式输入通道（`build_channel`）做测试：干跑模式下测试只写日志、零真实输入；真实模式下每次输入前同样校验并置顶窗口；测试动作必须放后台线程、执行期间禁用按钮、可被停止请求中断（长按/滑动仍须释放按键）。**开发者调试未开启时该页所有选项一律不生效**（2026-09-19 用户要求）：整页禁用、干跑开关改动不写配置并回滚勾选、主窗口 `_debug_actions_allowed()` 拒绝测试/诊断/布局测量请求，关闭开关时中断正在运行的调试线程。
- 图像识别（2026-09-19 引入，`automation/vision.py` + `core/vision.py`）：模板匹配必须用 `np.fromfile` + `cv2.imdecode` 读图（`cv2.imread`/`cv2.imwrite` 在 Windows 上**不支持中文路径**，实测算子必须用 imencode+tofile）；匹配结果坐标一律是**客户区坐标**（中心/左上/尺寸/匹配度），可直接喂给 `click_at`/`drag`；模板比截图大必须抛可读 `VisionError`；识别前必须校验窗口存在且未最小化；失败一律转成 `RecognizeResult`（不把异常抛给 GUI 线程）；**识别不产生任何输入**；`automation/vision.py` 不得 import PySide6。新增/更换识别算法依赖必须走 `requirements.txt` 并说明理由（当前为 numpy + opencv-python-headless）。
- 新增或更换**任何依赖**都必须改 `requirements.txt` 并在提交信息里写明理由与体积代价（当前：`numpy` + `opencv-python-headless`，使打包体积 +60–70 MB）。
- 占位任务（`order_hold`/`feature_3`/`feature_4`）：**只允许**「进入日志（含"该功能尚未实现真实逻辑（规划中）"原文）+ 每轮一条心跳日志 + 响应停止」；禁止产生任何输入、禁止读 params、禁止写推测性业务逻辑（有测试守卫）。
- 文件长度控制：单个文件超过 400 行必须先考虑拆分；超过 600 行必须拆分（模板生成的 UI 文件除外）。

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
