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
6. **默认安全**：一切自动化默认 dry-run；任何真实输入注入路径都必须经过显式用户确认 + 急停可中断。输入一律走窗口消息（`PostMessage`），**禁止使用 `SendInput`/`SetCursorPos`/`mouse_event` 等接管真实键鼠的接口**。
7. **可观测**：所有关键动作写日志；异常必须记录完整堆栈；不允许 `pass` 掉异常或 `except Exception: continue` 式的吞错。
8. **最小依赖**：只允许使用 `requirements.txt` / `requirements-dev.txt` 中列出的包。需要新依赖时：先改 requirements 文件 → 在提交说明写明理由 → 才可 import。

## 2. 编码要求

- Python 3.11+，UTF-8，4 空格缩进；类型注解覆盖所有公共函数签名。
- 配置模型用 `dataclass`；JSON 读写必须原子化（临时文件 + `os.replace`）。
- 日志用标准库 `logging`：模块级 `logging.getLogger(__name__)`；禁止 `print` 替代日志（CLI 输出除外）。
- 所有文件/窗口/进程操作都要处理失败路径：找不到窗口、无权限、配置缺失、磁盘满等，给出可读错误并保持程序可用。
- 时间间隔类配置必须有上下限校验（例如 `click_interval_ms` 限 100–5000）。
- GUI：长任务一律放工作线程（QThread），禁止在主线程 sleep 或忙等；按钮防重复点击（启动后禁用启动钮）。
- 每次真实输入注入前检查 stop 事件；停止请求发出后 500ms 内必须停止动作序列。
- 输入注入必须使用窗口消息（`PostMessage` / `SendMessageTimeout` 发到游戏窗口或其子窗口），不得移动真实光标或抢占键盘焦点。
- 文件长度控制：单个文件超过 400 行必须先考虑拆分；超过 600 行必须拆分（模板生成的 UI 文件除外）。

## 3. 禁止事项（红线）

1. 禁止读写游戏进程内存、禁止拦截/伪造/重放游戏网络封包——**连接口都不得预留**。（原「禁止 DLL 注入 / 驱动 / 过检测技巧」的限制已按用户要求取消，见 `PROJECT_SPEC.md` §4.1：此类方案须先取得用户逐项授权、保证存在可回退的基础模式，并如实声明风险。）
2. 禁止存储或传输账号/密码/token；禁止任何联网代码。
3. 禁止在 dry-run 为默认值时执行真实输入；禁止绕过「真实模式确认」。
4. 禁止静默修改/删除配置文件字段：schema 变更必须 `schema_version +1` + 迁移函数 + 单测。
5. 禁止吞异常：任何 `except` 必须记录日志并给出可解释的降级路径。
6. 禁止引入未批准的第三方包；禁止 `pip install` 后只在自己机器生效而不更新 requirements。
7. 禁止重写历史（force push）、禁止把 `user_data/config.json`、日志、截图、构建产物提交入库。
8. 禁止删除/破坏既有测试来让测试通过；测试失败必须修代码或（经用户同意后）修测试。
9. 禁止一次性生成超过一个阶段的代码；禁止跨阶段“顺手重构”。
10. 禁止在游戏窗口未找到、已最小化或不可见时执行输入注入；失焦行为必须遵守 `pause_on_window_focus_loss` 配置。

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

## 5. 提交要求

- Conventional Commits，中文说明，范围前缀必带：
  - `feat(config): 新增 schema v2 迁移`
  - `fix(core): 修复停止事件未传递到子任务`
  - `test(automation): 补充窗口消息调用序列断言`
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
```
