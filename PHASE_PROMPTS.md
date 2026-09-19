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

> **注记（2026-09-16）**：本节提到的「窗口失焦时暂停」设置项已随输入实现方式收敛（只保留真实鼠标键盘）删除，见 Phase 5.3。

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

> **注记（2026-09-16）**：本阶段的窗口消息通道（含子窗口定位、失焦暂停）已随「只保留真实鼠标键盘实现」的指示整体删除；原文保留作为阶段记录，现行实现见 Phase 5.3。

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

## Phase 5.2 — 对齐窗口点击通道（点得准 + 不碰真实鼠标）

**背景（实测）**：目标游戏是 Unity 播放器（`UnityWndClass`、已注册触摸、以管理员运行、无子窗口），**忽略窗口消息里的坐标**。2026-09-15 用「提权后的输入判定矩阵」逐一实测（脚本 `game_input_matrix.py`）：

| 变体 | 结果 |
|---|---|
| 无害悬停 / 客户区坐标 `PostMessage` / 同步 `SendMessageTimeout` / 激活序列（ok-script、autoxkit 时序）/ 同步 `WM_POINTER` / 抢前台三件套（TOPMOST→前台→NOTOPMOST） | **全部无反应**（游戏不读消息坐标） |
| **对齐窗口 + 投递点击**（移动窗口把目标坐标搬到静止光标下方） | **目标点正确响应 ✓，真实光标移动=False、隐藏=False** |
| **对齐窗口 + 真实按键点击**（不发 MOVE） | 同上 ✓ |

同时确认：`PostMessage` 投递 `WM_POINTER*` 被系统拒绝（只能同步）、`WM_TOUCH` 句柄无法伪造、**UIPI 会拦截未提权进程的输入消息**（`WM_MOUSEMOVE` → 错误码 5，这正是 Phase 5 结论失真的原因）。做法参考 kotonebot 的 `windows_background` 通道（`send_message.py` 的 `_align_window`/`_wait_cursor_idle`，GPL-3.0，仅借鉴思路、代码自写），并补上它缺失的「还原窗口位置」。

**本次只做什么**：
1. `src/luoluotool/automation/window_align.py`（新）：`compute_window_origin()`（纯计算）、`get_cursor_pos()`、`window_rect()`、`client_origin()`、`is_maximized()`（用 `GetWindowPlacement`，pywin32 无 `IsZoomed`）、`wait_cursor_idle()`（0.05 s 采样、速度阈值 50 px/s）、`align_window()`（对齐 + 回读校验误差 ≤1px + 光标漂移则重新对齐，最多 2 次）、`restore_window()`、`ensure_alignment_supported()`。**源码中不得出现任何移动真实光标的 API**（有测试断言）。
2. `src/luoluotool/automation/input_sender.py`：`WindowAlignSender`（实现 `InputSender`）：窗口可用性检查 → 最大化拒绝 → 等光标静止 → 对齐 → 点击 → `finally` 还原窗口；`move_to`/`key_tap` 不对齐；`build_channel` 按 `automation.align_window_before_click` 选择通道。
3. `src/luoluotool/config/{models,validation}.py`：新增 `automation.align_window_before_click`（默认 `false`）→ **schema v3 + `_migrate_v2_to_v3` + 布尔校验**；`user_data/config.example.json` 同步。
4. `src/luoluotool/gui/pages/settings.py`：新增勾选框「点击前对齐游戏窗口（不移动真实鼠标）」+ 前置条件 tooltip。
5. 测试：对齐数学、误差/失败上报、光标漂移重新对齐、重试上限、还原窗口、静止门控（含超时与先快后停）、最大化拒绝、鼠标移动时取消点击、点击抛错也还原、日志、`build_channel` 分支、schema v2→v3 迁移与校验、设置页绑定；**全部注入假实现，零真实输入/零窗口移动**。
6. 文档：`PROJECT_SPEC.md`（§5 风险与前置条件、§6 技术栈、§7 目录、§8 接口、§9 schema v3 迁移记录）、`AGENTS.md` §2、`CHECKLIST.md`、`README.md`。

**不要做什么**：不移动真实光标（这是本阶段的硬指标）；不注入系统输入流（不用 `SendInput`/`mouse_event`/触摸注入）；不复用 kotonebot 代码（GPL-3.0，仅借鉴思路）；不引入任何驱动或新依赖；不改动窗口消息通道的既有行为（开关默认关闭）。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests/test_automation -q --cov=src/luoluotool/automation --cov-report=term-missing
.venv\Scripts\python -m luoluotool --validate-config
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 全量测试通过；`window_align.py` 覆盖率 ≥ 85%，且单测零真实输入、零窗口移动。
- [ ] `config.json` 自动迁移到 v3（补齐新字段并写回），`--validate-config` 输出 `OK`。
- [ ] 设置页可勾选「点击前对齐游戏窗口」；保存后 `config.json` 反映、重启保持。
- [ ] **手动验收**：游戏窗口化并前台 → 勾选该开关 → 真实模式启动 → 游戏在配置坐标处响应，**真实光标不动、不消失**、窗口点完立即回原位、F8 可急停、失焦暂停生效。
- [ ] 最大化窗口 / 鼠标持续移动 / 对齐失败三种情况下**都不点击**，且日志给出可读原因。

**复制给 AI 的提示词**：

```text
执行 PHASE_PROMPTS.md 的 Phase 5.2（对齐窗口点击通道）。
做法：点击前把目标客户区坐标对齐到静止的真实光标下方——移动游戏窗口而不是移动光标
（SetWindowPos + SWP_NOACTIVATE|SWP_NOZORDER|SWP_NOSIZE|SWP_NOREDRAW），再投递窗口消息点击，
点完立即还原窗口位置；前置检查（窗口可用、未最大化、光标静止 ≤50px/s），无法满足时不点击并报可读错误。
硬指标：绝不移动真实光标、绝不注入系统输入流、绝不使用触摸注入。
配置：automation.align_window_before_click（默认 false）→ schema v3 + 迁移函数 + 校验 + 设置页勾选框。
测试必须注入假实现，单测零真实输入。完成后运行验收命令并汇报覆盖率。
```

---

> **注记（2026-09-16）**：按用户指示，本阶段（对齐窗口点击通道）的实现与测试**已整体删除**：用户确定改用「真实鼠标键盘」方案，要求删除其它实现方式。相关文件 `automation/window_align.py`、`tests/test_automation/test_window_align.py`、`tests/test_automation/test_align_sender.py` 已移除，配置项 `align_window_before_click` / `input_mode` 随 schema v5 一并删除；实现保留在 git 历史（`90752fe`、`5cf6710`）。

---

## Phase 5.3 — 真实鼠标键盘输入通道（SendInput，输入前置顶校验）

**背景（用户指示，2026-09-16）**：用户明确改用「**直接移动真实鼠标 + 模拟真实键盘**」的方案，并提出硬规则：

> 「注意使用此方案时每次一次鼠标点击和键盘输入前都必须校验游戏窗口是否至于最顶层，不在最顶层时将窗口置于最顶层再输入或点击」

（背景：此前三档方案的代价分别是——触摸注入让系统隐藏指针、对齐窗口让游戏窗口短暂位移、窗口消息被游戏忽略；用户选择接受"抢前台 + 移动真实光标"这一档。）

**本次只做什么**：

1. `src/luoluotool/automation/real_input.py`（新）：**唯一允许调用输入注入 API 的模块**
   - `ensure_window_front(hwnd) -> FrontResult`：**每次输入前**执行——最小化先 `SW_RESTORE`；未置顶则 `SetWindowPos(HWND_TOPMOST, SWP_NOSIZE|SWP_NOMOVE|SWP_SHOWWINDOW|SWP_NOACTIVATE)`；不在前台则 `SetForegroundWindow`（前台锁定失败用 `AttachThreadInput` 兜底）并**回读 `GetForegroundWindow` 复核**；仍不行则返回 `ok=False`（调用方据此拒绝输入）；
   - `release_topmost(hwnd)`、`is_topmost()`、`is_foreground()`、`is_minimized()`、`client_to_screen()`；
   - 输入原语：`move_cursor_absolute()`（绝对移动、`VIRTUALDESK` 归一化）、`send_left_click()`、`send_key_tap()`（扫描码按下/抬起，保证不卡键）、`get_cursor_pos()`、`set_cursor_pos()`；
   - `normalize_absolute()` 纯函数（多显示器虚拟桌面归一化，有单测）。
2. `src/luoluotool/automation/input_sender.py`：`RealInputSender` —— 每次 `click_at()`/`key_tap()` 前调 `ensure_window_front`，失败即抛可读错误且**不输入**；点击后按 `restore_cursor_after_click` 还原光标；`finally` 里取消本次由我们设置的置顶；`move_to()` 不移动真实光标（仅记 debug 日志）。
> **注记（2026-09-16）**：用户随后确定**只保留本阶段的「真实鼠标键盘」实现**，其它通道（窗口消息、合成指针、对齐窗口）与 `input_mode` 枚举、`pause_on_window_focus_loss` 开关均已删除（schema v5），`build_channel` 在真实模式下固定返回 `RealInputSender`。以下原文保留作为阶段记录。

3. `src/luoluotool/config/{models,validation}.py`：`automation.input_mode`（`window_message` / `window_align` / `real_input`）+ `automation.restore_cursor_after_click`（默认 `true`）→ **schema v4 + `_migrate_v3_to_v4`**（旧的 `align_window_before_click=true` 无损升级为 `input_mode=window_align`）+ 枚举与布尔校验；`config.example.json` 同步。
4. `gui/pages/settings.py`：「输入方式」下拉（三项，含代价说明）+「每次点击后把真实鼠标移回原位置」勾选。
5. `build_channel`：三档分流；`real_input` 档**强制关闭**「窗口失焦时暂停」（该通道自己抢前台，否则互相等待）并记日志。
6. 测试（全部注入假 user32 / 假 real_input，**单测零真实输入**）：置顶+置前顺序、已在前台且置顶时不打扰、最小化先恢复、`AttachThreadInput` 兜底、无法置前时拒绝输入、`_set_window_pos` 的 pywin32-None 语义回归、绝对坐标归一化（含多显示器）、点击按下/抬起、键盘扫描码、**每次输入都重新校验**、还原光标可配置、异常时也还原并取消置顶、`move_to` 不动光标、三档 `build_channel`、schema v3→v4 迁移与枚举校验、设置页绑定、**注入 API 只允许出现在 `real_input.py`** 的跨模块守卫。
7. 文档：`PROJECT_SPEC.md` §4.2.3（用户硬规则与落实方式表）、§5、§6、§7、§8、§9（schema v4 迁移记录）、`AGENTS.md` §2、`CHECKLIST.md`、`README.md`。

**不要做什么**：不实现绕过/对抗反作弊（见 §4.2.2，工程负责人不执行项）；不在无法确保窗口在最前时输入；不让游戏窗口长期保持 TOPMOST；不把注入 API 扩散到 `real_input.py` 以外；不改动窗口消息与对齐通道的既有行为。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests/test_automation -q --cov=src/luoluotool/automation --cov-report=term-missing
.venv\Scripts\python -m luoluotool --validate-config
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 全量测试通过；`real_input.py` 覆盖率 ≥ 80%，单测零真实输入。
- [ ] `config.json` 自动迁移到 v4；`--validate-config` 输出 `OK`。
- [ ] 设置页可切「输入方式」三档、可关「还原鼠标位置」；保存后配置反映、重启保持。
- [ ] **手动验收**：切到「真实鼠标键盘」→ 真实模式启动 → 游戏在配置坐标处响应；**每次点击/按键前**游戏窗口被置顶（若原本不在最顶层）；点击后鼠标回到原位置（开关打开时）；F8/F9 可急停；窗口最小化/无法置前时日志给出可读原因且**不产生输入**。

---

## Phase 5.4 — 键盘输入功能（组合键 + 长按）

**背景**：Phase 5.3 的真实键鼠通道已具备单键 `key_tap`，但游戏操作大量依赖按键（快捷键、方向键、长按移动），
需要把它扩展成**可配置的按键序列**，并遵守同一套安全规则。

**本次只做什么**：
1. `utils/keys.py`（新，叶子层）：`KEY_NAME_TO_VK`（a-z、0-9、f1-f24、enter/esc/tab/space/backspace/方向键/小键盘等）、
   `MODIFIER_KEYS`（ctrl/alt/shift/win）、`EXTENDED_VKS`、`parse_combo("ctrl+shift+a") -> (修饰键元组, 主键 vk)`；
   非法输入抛**可读** `ValueError`（空文本/空片段/重复修饰键/未知键名）。
2. `automation/real_input.py`：`send_key_down/up`、`send_key_combo`（按下修饰键 → 敲主键 → **逆序**释放修饰键，
   失败也在 `finally` 释放）、`send_key_hold(combo, seconds, sleep, stop_event)`（按 100ms 切片推进，
   可被急停打断；任何退出路径都释放按键）；扩展键自动带 `KEYEVENTF_EXTENDEDKEY`；扫描码路径 `wVk=0`（与真实硬件一致）。
3. `automation/input_sender.py`：协议新增 `key_combo` / `key_hold`；`RealInputSender` 每次按键前
   **同样校验并置顶窗口**，未知键名在注入前以可读错误拒绝；长按被急停中断时写 WARNING；`build_channel` 把
   `stop_event` 传给 sender；`DryRunSender` 只写日志（零输入）。
4. `config/models.py`：`KeyStepParams{combo, hold_ms, wait_after_ms}` + `parse_keys_text` / `format_keys_text`
   （文本语法 `ctrl+s, w*800, enter`；解析时即校验键名）；`PlaceholderTaskParams.keys`。
5. `config/validation.py`：`keys` 结构校验（数组、≤20 步、`combo` 非空且可解析、`hold_ms`/`wait_after_ms` 0–60000）
   → **schema v6 + `_migrate_v5_to_v6`**（`params.keys` 默认 `[]`）；`config.example.json` 同步。
6. `core/registry.py`：占位任务 A 现在按「先点击、后按键」执行，日志区分「点击/按键/长按」，
   步骤间响应停止请求；只有点击与按键都为空时才提示未配置。
7. `gui/pages/daily.py`：新增「按键序列」输入框（示例与 tooltip 说明语法），非法输入**回退显示**不写坏配置。
8. 测试：组合键解析（含字母键名小写回归）/修饰键重复/未知键名、注入顺序与逆序释放、失败也释放修饰键、
   扩展键标志、长按满时长/急停打断/异常释放、sender 层每次按键前校验与未知键名拒绝、
   任务编排顺序与停止、schema v5→v6 迁移与 keys 校验、GUI 绑定与非法输入回退；全部注入假实现（零真实输入）。

**不要做什么**：不发送鼠标以外的其他设备输入；不实现"按住不放直到程序退出"这类无法保证释放的模式；不绕过每次输入前的置顶校验；不修改 Phase 5.3 的鼠标行为。

**验收命令**：
```bash
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests/test_automation -q --cov=src/luoluotool/automation --cov-report=term-missing
.venv\Scripts\python -m luoluotool --validate-config
.venv\Scripts\python -m luoluotool --smoke-gui
```

**完成标准**：
- [ ] 全量测试通过；`real_input.py` 覆盖率 ≥ 80%。
- [ ] `config.json` 自动迁移到 v6（`params.keys` 补齐）；`--validate-config` 输出 `OK`。
- [ ] 日常任务页可编辑按键序列；非法输入即提示并回退，配置不被写坏。
- [ ] **手动验收**：配置 `{"keys": [{"combo": "ctrl+s"}, {"combo": "w", "hold_ms": 800}]}` → 真实模式启动 →
      游戏收到对应按键；长按期间按急停键，按键**立即释放**且日志出现「被停止请求中断」。
- [ ] 干跑模式下按键只写日志、零真实输入。

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
