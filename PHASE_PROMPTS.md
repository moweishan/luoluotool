# PHASE_PROMPTS.md — LuoLuoTool 分阶段提示词

> 使用方法：**严格按顺序执行**，一个阶段验收通过后再进入下一个阶段。
> 每次把「通用开场白」+「该阶段的提示词」一起复制给你的 AI 代码编辑器（Codex/Cursor/Claude Code/Windsurf）。
> AI 每完成一个阶段，你必须**亲自运行该阶段的验收命令**，全部通过后才算完成。
> 任何阶段都**禁止跳步、禁止合并阶段、禁止顺手做下一阶段的事**。

---

## 通用开场白（每次新会话都先贴这一段）

```text
你正在 LuoLuoTool 项目根目录工作。这是一个 Windows 桌面自动化工具的增量开发项目。
请先阅读以下文件并严格遵守：
- AGENTS.md（开发规范，含红线与测试要求）
- PROJECT_SPEC.md（项目边界、技术栈、目录结构、数据结构、验收标准）
- DATA_API_PREP.md（无外部 API，仅本地资源）

你只能执行我下面指定的那一个阶段。禁止一次性生成完整项目，禁止超出该阶段的
“本次只做什么”，禁止引入 requirements 之外的依赖，禁止删除或破坏已有测试。
每个阶段完成后，运行该阶段的全部验收命令并汇报结果。
```

---

## Phase 0 — 环境与项目骨架（空窗口）

**阶段目标**：建立可运行的 Python 包骨架与 PySide6 空主窗口，验证工具链可用。

**本次只做什么**：
1. 创建 `pyproject.toml`：项目元信息（名称 `luoluotool`、版本 0.1.0）+ pytest 配置（`testpaths=["tests"]`）。
2. 完善 `src/luoluotool/__init__.py`：只放 `__version__ = "0.1.0"`。
3. 创建 `src/luoluotool/__main__.py`：解析 `--version` / `--config <path>` / `--validate-config` / `--smoke-gui` 四个参数并分发到 `gui.app`（`--validate-config` 本阶段先输出“尚未实现”并返回退出码 2）。
4. 创建 `src/luoluotool/utils/logging_setup.py` 与 `src/luoluotool/utils/paths.py`：日志初始化（控制台 + `logs/` 滚动文件）与 `user_data/`、`logs/` 路径解析。
5. 创建 `src/luoluotool/gui/app.py`：`run(argv)` 创建 QApplication、加载 `main_window.py`。
6. 创建 `src/luoluotool/gui/main_window.py`：QTabWidget 主窗口，含「日常任务 / 卡订单 / 功能三 / 功能四 / 设置」五个空页签 + 状态栏显示版本号；窗口标题 `LuoLuoTool`。
7. 写 `tests/test_cli.py` 与 `tests/test_gui_smoke.py`（GUI 测试用 `QT_QPA_PLATFORM=offscreen`）。

**不要做什么**：不写任何配置读写、任务逻辑、自动化代码；不做界面美化主题；不创建 `packaging/` 内容；不打包 exe。

**验收命令**（全部通过才算完成）：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --version
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] `--version` 输出 `luoluotool 0.1.0`，退出码 0。
- [ ] `--smoke-gui` 退出码 0（离屏创建窗口成功）。
- [ ] 手动运行 `.venv\Scripts\python -m luoluotool` 能看到五页签窗口，UI 不崩溃。
- [ ] `logs/` 出现日志文件；`git diff --stat` 只涉及本阶段列出的文件。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 0（环境与项目骨架）。
先读 AGENTS.md 与 PROJECT_SPEC.md。严格按该阶段“本次只做什么”逐条实现，
不要做“不要做什么”里列出的任何事。测试先行，完成后运行验收命令并汇报。
代码净增量不得超过 300 行。
```

---

## Phase 1 — 配置模型与持久化

**阶段目标**：实现 schema v1 配置模型、校验、原子化读写与 `--validate-config`。

**本次只做什么**：
1. `src/luoluotool/config/models.py`：dataclass 实现 `PROJECT_SPEC.md` 第 9 节完整 schema（`AppConfig` 及子模型），全部布尔默认 `false`，`dry_run` 默认 `true`，含 `to_dict/from_dict`。
2. `src/luoluotool/config/validation.py`：字段级校验（类型、枚举、`click_interval_ms` 100–5000 等上下限），返回错误列表而不是抛异常。
3. `src/luoluotool/config/store.py`：`load(path)` / `save(config, path)`；原子写入（临时文件 + `os.replace`）；文件不存在时返回默认值并落盘；损坏文件备份为 `config.json.bak-<时间戳>` 后用默认值覆盖。
4. `user_data/config.example.json`：与默认值一致的样例文件。
5. `__main__.py`：实现 `--validate-config`（校验通过输出 `OK` 退出码 0，失败逐条打印错误退出码 1）。
6. 测试：默认值、合法读写往返、非法值、损坏恢复、原子性、迁移占位（schema_version 不支持时报错）。

**不要做什么**：不做 GUI 绑定；不做任务执行；不新增 schema 字段；不引入 pydantic。

**验收命令**：
```bash
.venv\Scripts\python -m pytest tests/test_config -q --cov=src/luoluotool/config --cov-report=term-missing
.venv\Scripts\python -m luoluotool --validate-config
```

**完成标准**：
- [ ] config 模块覆盖率 ≥ 90%，全绿。
- [ ] 手动把 `user_data/config.json` 改成非法 JSON 后启动程序，程序不崩溃并提示已恢复默认值。
- [ ] `--validate-config` 对合法文件输出 OK（退出码 0）、对非法文件打印具体错误（退出码 1）。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 1（配置模型与持久化）。
严格按 PROJECT_SPEC.md 第 9 节的 schema v1 实现，字段一个不多一个不少。
测试先行；不要做 GUI、不要做任务执行、不要引入新依赖。
完成后运行验收命令并汇报覆盖率与结果。
```

---

## Phase 2 — 配置 GUI（五页签绑定）

**阶段目标**：GUI 能完整展示并编辑配置，改动有脏标记，可保存/重新加载。

**本次只做什么**：
1. `src/luoluotool/gui/pages/`：`daily.py`（日常任务启用 + 占位任务 A 勾选 + 循环间隔）、`order_hold.py`（主开关 + 预留开关 1/2，带“规划中”说明）、`feature3.py`、`feature4.py`（启用开关 + “功能规划中”）、`settings.py`（dry_run、点击间隔、失败上限、失焦暂停、急停键只读显示）。
2. `main_window.py`：加载五页签；窗口底部「保存 / 重新加载 / 恢复默认」按钮 + 脏标记（标题加 `*`）。
3. 页面改动只更新内存中的 `AppConfig` 副本；点「保存」才落盘（原子写）。
4. 测试：offscreen 下开关联动与脏标记逻辑；保存/重载往返一致。

**不要做什么**：不做「启动/停止」按钮与任务执行；不做日志面板；不做窗口查找/截图；不写自动化代码。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 手动打开 GUI：五个页签均可切换、控件状态与 `config.json` 一致。
- [ ] 修改任意开关后标题出现 `*`；保存后 `*` 消失且 `config.json` 内容变化；重新加载恢复文件值。
- [ ] 两个预留开关与功能三/四开关保存、重启后仍在，无任何副作用。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 2（配置 GUI 五页签绑定）。
UI 只做展示与绑定，禁止在 gui/ 里写任务逻辑或文件逻辑（调用 config 模块即可）。
不要做启动/停止、不要做日志面板、不要做任何自动化动作。
完成后运行验收命令并说明每个页签绑定了哪些配置字段。
```

---

## Phase 3 — 任务执行框架（仅干跑）

**阶段目标**：可启动/停止的干跑任务管线：任务注册、顺序执行、日志面板、F8 急停。

**本次只做什么**：
1. `src/luoluotool/core/task.py`：`BaseTask`（`run(ctx) -> TaskResult`）+ `TaskContext`（stop_event、dry_run、logger）。
2. `src/luoluotool/core/registry.py`：任务 ID → 类的注册表；先注册 `placeholder_task_a`。
3. `src/luoluotool/core/state.py`：运行状态枚举（IDLE/RUNNING/STOPPING/ERROR）+ 状态机。
4. `src/luoluotool/core/runner.py`：`Runner.start/stop/request_stop`；按配置顺序执行勾选任务；支持循环间隔；失败计数达到 `max_consecutive_failures` 自动停止；**每次“动作”前检查 stop_event**。
5. `gui`：主窗口增加「启动 / 停止」按钮（运行中启动钮禁用）+ 日志面板（QPlainTextEdit 接收 logging Handler）+ 状态栏运行状态（干跑模式显示“运行中 · 干跑”）。
6. `src/luoluotool/automation/hotkey.py`：`RegisterHotKey` 注册 F8，回调 `runner.request_stop()`；退出时注销。
7. 占位任务：干跑时每秒输出一条模拟步骤日志（如“模拟点击 (x,y)”），可被 stop 立即中断。
8. 测试：注册表、执行顺序、循环、失败停止、stop 中断（用虚拟时间，不真实 sleep）。

**不要做什么**：不做任何真实键鼠输入；不做窗口查找/截图；不做卡订单/功能三四的执行逻辑；不引入线程池之外的并发设施。

**验收命令**：
```bash
.venv\Scripts\python -m pytest tests/test_core -q --cov=src/luoluotool/core --cov-report=term-missing
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] core 覆盖率 ≥ 90%，全绿。
- [ ] 手动运行：勾选占位任务 → 启动 → 日志面板持续输出模拟步骤；点「停止」后 1 秒内停止；再次启动正常。
- [ ] 运行中按 F8 能停止（日志出现“急停触发”）。
- [ ] 全程未产生任何真实鼠标/键盘输入。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 3（任务执行框架，仅干跑）。
严格执行分层：core 不 import PySide6 与 win32；QThread 适配放在 gui 层。
禁止真实键鼠输入，禁止窗口/截图代码，禁止实现卡订单逻辑。
测试先行，完成后运行验收命令并汇报覆盖率。
```

---

## Phase 4 — 窗口定位与截图诊断工具

**阶段目标**：能按标题关键字找到游戏窗口、置前并截图保存，为真实自动化做准备。

**本次只做什么**：
1. `src/luoluotool/automation/window.py`：`find_window(keyword)`、`bring_to_front(hwnd)`、`get_client_rect(hwnd)`、`screenshot_client(hwnd, save_path)`（win32gui/win32ui；截图保存到 `user_data/debug/window_<时间戳>.png`）。
2. 设置页增加「窗口诊断」按钮：执行查找→置前→截图，把结果与图片路径写入日志面板与状态栏；找不到窗口时给出明确提示（如“未找到标题含‘桃源深处有人家’的窗口，请确认游戏已窗口化运行”）。
3. `utils/paths.py` 增加 `debug_dir()`。
4. 测试：窗口相关纯逻辑（路径生成、时间戳命名）单测；系统调用部分用“未找到窗口”分支做集成冒烟。

**不要做什么**：不做鼠标点击/键盘输入；不做图像匹配；不做任务接入；不在后台自动截图。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 游戏窗口化运行状态下，点「窗口诊断」：游戏窗口被置前，`user_data/debug/` 生成 PNG 截图，日志面板显示窗口句柄与尺寸。
- [ ] 游戏未运行时，点「窗口诊断」出现明确中文错误提示，程序不崩溃。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 4（窗口定位与截图诊断工具）。
只实现查找/置前/截图与设置页的诊断按钮；禁止任何点击与键盘动作，
禁止图像匹配，禁止自动循环截图。完成后运行验收命令。
```

---

## Phase 5 — 输入模拟 + 第一个真实日常任务

**阶段目标**：接通**后台窗口消息输入**通道（不接管真实键鼠），让占位任务 A 能按配置坐标完成一次真实点击序列。

> 输入方式约定（本阶段必须遵守）：默认通过 `PostMessage`/`SendMessageTimeout` 向游戏窗口（或其子窗口）发送鼠标/键盘消息。
> **2026-09-15 政策更新**：原「禁止 `SendInput`/`SetCursorPos`/`mouse_event`」的限制已按用户要求取消（见 `PROJECT_SPEC.md` §4.1）。
> 若窗口消息无法让游戏响应（例如游戏只认物理光标位置），**经用户逐项授权后**可改用用户态合成输入，
> 并必须遵守：注入前校验目标窗口在前台、动作后还原真实光标（可配置）、逐条记录日志、F8 急停随时可中断。

**本次只做什么**：
1. `src/luoluotool/automation/input_sender.py`：封装**输入发送** `move_to/click/click_at/key_tap`，默认实现为**后台窗口消息**（`SendMessageTimeout` 同步投递 + `PostMessage` 悬停提示 + `WindowFromPoint` **子窗口定位**；`WM_MOUSEMOVE/WM_LBUTTONDOWN/WM_LBUTTONUP/WM_KEYDOWN/WM_KEYUP`；坐标为客户区坐标，子窗口场景自动换算）；每个动作前检查 stop_event；动作间隔取自配置。（2026-09-15 更新：窗口消息无效时，经用户逐项授权可新增**用户态合成输入**实现——`ctypes` 调 `SendInput`/`SetCursorPos`，须校验目标窗口在前台、点击后还原真实光标。）
2. `src/luoluotool/config/models.py`：给 `placeholder_task_a.params` 定义结构 `{"click_points": [[x,y], ...], "wait_after_ms": 500}`（不改 schema 版本，只填 params 内容）。
3. 干跑/真实分流：`TaskContext.dry_run == True` 时输入层被替换为“只写日志”；`False` 时向窗口发送真实消息。
4. 真实模式启动前弹出确认对话框：说明"将以【窗口消息 / 用户态合成输入，按实际实现】方式模拟点击、按 F8 可急停"，并提醒封号风险（合成输入会短暂移动光标）；用户确认后才进入真实模式（确认询问频率可配置，默认每次）。
5. 执行前检查：找到游戏窗口且窗口未最小化（后台消息输入**不需要**窗口获得焦点）；`pause_on_window_focus_loss=true` 时，窗口失焦即暂停并提示，重新聚焦后继续（该开关语义保持不变，作为保守安全策略）。
6. 设置页把急停键、点击间隔改为**可编辑**（保存后生效）。
7. 测试：注入假 sender 验证点击序列与间隔、失焦暂停逻辑；单测永不产生真实输入。

**不要做什么**：不做图像识别；不再新增第二个任务；不做卡订单真实逻辑；不读写游戏进程内存；不拦截/伪造网络封包；不绕过 UAC/权限；不使用**未获用户逐项授权**的注入类/驱动级输入方案（见 `PROJECT_SPEC.md` §4.1）。

**验收命令**：
```bash
.venv\Scripts\python -m pytest tests/test_automation -q --cov=src/luoluotool/automation --cov-report=term-missing
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] automation 模块测试全绿（fake sender 注入，零真实输入）。
- [ ] 干跑模式：日志显示完整点击序列，无真实动作。
- [ ] 真实模式（坐标先填游戏界面内一处安全位置验证）：确认框 → 消息点击序列按间隔执行 → 日志逐条记录 → F8 立即停止 → 游戏失焦时自动暂停。
- [ ] **执行期间真实鼠标光标不移动、真实键盘输入不受影响**（可同时用鼠标拖动窗口 / 在别处打字验证）。
- [ ] 状态栏在真实模式下有醒目提示（红色“真实模式”）。

**已知风险（需在交付说明中写明）**：
- 若游戏使用 `Raw Input`/`DirectInput` 独占方式读取输入，窗口消息可能**不被游戏识别**（表现为“日志正常但游戏无反应”）；届时先记录现象，**在获得用户明确同意后**再评估替代方案，不得擅自改为接管真实键鼠。
- 玩家在任务执行期间手动操作游戏窗口可能与自动化互相干扰，建议执行期间不要手动操作游戏窗口。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 5（输入模拟 + 第一个真实日常任务）。
输入方式：默认 PostMessage/SendMessageTimeout 向游戏窗口发送鼠标/键盘消息；若实测游戏不响应，
经用户逐项授权后可改用用户态合成输入（SendInput/SetCursorPos，须校验前台 + 点击后还原光标）。
严格安全要求：干跑默认开启、真实模式需确认对话框、F8 急停、失焦暂停、
每次输入注入前检查 stop_event。禁止图像识别、禁止新增第二个任务、
禁止读写游戏内存与封包操作。测试必须用注入的假 sender，绝不在单测里产生真实输入。
完成后运行验收命令并汇报覆盖率。
```

---

> **注记（2026-09-15）**：曾存在的「Phase 5.1 — 合成指针点击通道（不移动真实光标）」已实现并完成验收，随后**按用户要求整套撤回**：Windows 会把合成触摸/笔注入判定为触摸输入并**抑制真实光标**（每次点击后指针消失，直到真实移动鼠标），无法用 API 关闭，也无可靠的恢复手段。实测排除清单与结论见 `PROJECT_SPEC.md` §4.2.1；实现保留在历史提交 `b145ca5`。**该阶段不再执行**，如需重试请先读 §4.2.1。

---

## Phase 6 — 卡订单与预留功能页闭环

**阶段目标**：功能二/三/四在主流程中形成完整闭环（开关→运行→日志），无推测性逻辑。

**本次只做什么**：
1. 注册三个空执行任务：`order_hold`、`feature_3`、`feature_4`。运行内容仅为：进入时输出“该功能尚未实现真实逻辑（规划中）”，每轮循环输出一次心跳日志，尊重 stop_event 与循环间隔。
2. `runner.py` 支持多来源任务编排：日常任务组（勾选即加入队列）与单功能组（主开关开启即加入队列），统一顺序执行、统一失败计数。
3. 卡订单页的两个预留开关保持**纯配置占位**：可保存、可读取、不触发任何行为（测试断言“开关状态不影响运行任务集合”）。
4. 功能三/四页的启用开关与对应空任务联动（开启后运行期有日志）。
5. 测试：任务编排合并顺序、预留开关无副作用、三个占位任务可被 stop 中断。

**不要做什么**：不定义卡订单的真实业务含义；不给预留开关添加任何行为；不做图像识别；不新增配置字段。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 打开卡订单主开关 + 功能三开关，运行后日志中出现两个“规划中”任务的执行记录，点停止立即中断。
- [ ] 两个预留开关任意组合保存/重启后保持不变，且对运行行为零影响（有测试证明）。
- [ ] 日常任务组与单功能组同时勾选时，执行顺序符合编排规则（有测试证明）。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 6（卡订单与预留功能页闭环）。
预留开关只允许“存/读/显示”，禁止添加任何行为；三个新任务只允许
“进入日志 + 心跳日志 + 响应停止”，禁止写推测性业务逻辑。
完成后运行验收命令并给出任务编排规则说明。
```

---

## Phase 7 — 打包为 exe

**阶段目标**：产出可在无 Python 环境的 Windows 10/11 上运行的 exe。

**本次只做什么**：
1. `packaging/LuoLuoTool.spec`：PyInstaller one-dir 配置；只打包 `src/luoluotool` 实际 import 的模块；排除 tests。
2. `packaging/version_info.txt` 与可选 `packaging/icon.ico` 占位（无图标时用默认）。
3. 构建脚本 `packaging/build.ps1`（创建虚拟环境 → 安装依赖 → 运行测试 → `pyinstaller --clean`）。
4. 打包后 exe 冒烟：`dist\LuoLuoTool\LuoLuoTool.exe --version` 与 `--smoke-gui`。
5. `README.md` 追加「构建与发布」小节：杀软加白说明、干净机器验证步骤。
6. 更新 `.gitignore`（构建产物）。

**不要做什么**：不改任何业务代码（发现 bug 先记录，回退到对应阶段修复）；不做 one-file 压缩优化；不做自动更新；不做安装包（MSI/NSIS）。

**验收命令**：
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
.\dist\LuoLuoTool\LuoLuoTool.exe --version
.\dist\LuoLuoTool\LuoLuoTool.exe --smoke-gui
```

**完成标准**：
- [ ] exe 在本机可启动 GUI，`--version` 输出正确。
- [ ] 拷贝整个 `dist\LuoLuoTool\` 目录到干净 Windows（无 Python）后，GUI 正常打开、配置可保存。
- [ ] 杀软误报已按 README 说明处理（加白名单）。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 7（打包为 exe）。
只做打包相关文件与文档，禁止修改业务代码；构建前必须跑全量测试。
完成后运行验收命令并给出 exe 体积与启动耗时。
```

---

## 后续阶段（先不执行，仅占位）

当你有新的真实需求时（例如「收菜」「卡订单具体操作」），按下面模板新建阶段：

```text
## Phase N — <名称>
阶段目标 / 本次只做什么 / 不要做什么 / 验收命令 / 完成标准 / 复制给 AI 的提示词
```

规则不变：先更新 `PROJECT_SPEC.md` 的 schema 与模块接口，再写提示词，再让 AI 执行；
每阶段净增代码 ≤ 300 行；验收不过不回退重写，先补失败测试。
