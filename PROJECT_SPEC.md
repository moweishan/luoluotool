# PROJECT_SPEC.md — LuoLuoTool 项目说明书

> 本文件是给 AI 代码编辑器看的**长期项目上下文**。任何开发开始前，AI 必须完整阅读本文件与 `AGENTS.md`。
> 本文档中的「必须 / 禁止」均为硬约束；「推荐」可在实现时根据验收标准调整，但需在提交说明中注明理由。

---

## 1. 项目概况

| 项 | 内容 |
|---|---|
| 项目名 | LuoLuoTool |
| 一句话 | 面向 Windows 的《桃源深处有人家》桌面自动化挂机工具，GUI 配置 + 一键启动，自动完成玩家勾选的日常重复操作 |
| 交付形态 | 最终打包为 **Windows exe**（PyInstaller），带简洁大气的 PySide6 图形界面 |
| 使用者 | 玩家本人（个人自用） |
| 运行环境 | Windows 10/11 x64；游戏客户端正常启动、可见窗口 |
| 联网 | 无。无 LLM、无外部 API、无数据库、无定时任务（无需后台常驻调度） |
| 数据存储 | 本地 JSON 配置文件 + 本地日志文件；不持久化任何账号信息 |

## 2. 项目目标

1. 玩家在 GUI 上勾选需要自动执行的「日常任务」等配置项，点击「启动」后，程序按配置自动完成所选项目。
2. 提供「卡订单」功能：当前仅一个主开关 + **两个预留配置项开关**（具体语义待定，先留位）。
3. 预留两个功能配置页（功能三、功能四），页面可切换、可开关，具体内容待定。
4. 界面要求：**简洁、大气、流畅**（启动快、操作不卡顿、长任务不阻塞 UI）。
5. 最终可打包为单机可运行 exe，无 Python 环境也可启动。

## 3. 功能范围（MVP 到完整）

### 功能一：日常任务
- GUI 上按「任务项」列表勾选（具体任务项在后期阶段结合游戏实际界面确认，前期用**占位任务 + 可配置坐标/锚点**实现框架）。
- 支持：任务排序 / 循环执行间隔 / 单轮执行后停止（配置项先预留，逐阶段落地）。
- 执行过程实时写日志并反映到 GUI 日志面板。

### 功能二：卡订单
- 主开关：启用/禁用。
- 预留开关 ×2：`reserved_switch_1`、`reserved_switch_2`，**现在无任何实际行为**，只落库、只显示、只在配置中占位。
- 后续若明确语义，在**不改动配置结构**的前提下填充逻辑（新增字段必须走 schema_version 迁移）。

### 功能三 / 功能四：预留配置页
- 各有一个页签，页内一个「启用」开关 + 说明文字「功能规划中」。
- 页签、开关、配置项从 Phase 2 起就存在，便于后续扩展。

### 非功能需求
- UI 全程不冻结：任务在后台工作线程执行。
- 默认**干跑模式（dry-run）**：只模拟执行并输出日志，不产生真实键鼠操作；用户明确取消勾选后才进入真实模式。
- **全局急停热键 F8**：真实模式下随时停止所有自动化动作（后期可配置，默认 F8）。
- 日志：控制台 + `logs/` 滚动文件，单文件上限与保留份数固定。
- 配置读写必须**原子化**（先写临时文件再替换），防止断电/崩溃损坏配置。

## 4. 项目边界（不做什么）

以下内容**禁止**（标注"已取消"者除外；标注"用户曾要求取消但未执行"者见 §4.2）：

1. **禁止读写游戏进程内存**（不搜索、不修改任何内存值）。〔用户 2026-09-15 曾要求取消 → **未执行**，见 §4.2〕
2. **禁止拦截、伪造、重放游戏网络封包**。〔用户 2026-09-15 曾要求取消 → **未执行**，见 §4.2〕
3. **禁止破解游戏客户端、绕过游戏更新**（其中"绕过反作弊系统"指篡改/屏蔽反作弊组件本身；输入实现方式的选择不在此列，见 §4.1）。
4. **禁止收集或存储玩家账号、密码、token、设备指纹**；程序不得要求登录。〔**用户明确保留此条**〕
5. ~~禁止联网功能~~ → **已取消**（见 §4.1）：允许联网，但不得上传日志/配置/截图等本地数据，且联网功能须经用户逐项授权。
6. **禁止多开批量打金、工作室用途**的加速设计（不做多实例协调、不做账号矩阵）。〔用户 2026-09-15 曾要求取消 → **未执行**，见 §4.2〕
7. **真实模式必须由用户显式触发**：默认干跑；进入真实模式需用户确认（询问频率可配置，默认每次询问）；F8 急停始终可用。〔原"禁止绕过确认"的绝对禁令已按用户要求改为可配置〕
8. **禁止**在无游戏窗口、或窗口最小化/不可见时执行输入注入；失焦行为遵守 `pause_on_window_focus_loss` 配置。〔用户 2026-09-15 曾要求取消 → **未执行**，见 §4.2〕

### 4.1 已取消的限制（2026-09-15，按用户要求执行）

| 原条款 | 原位置 | 现状 |
|---|---|---|
| 禁止 DLL 注入 / 钩子注入 / 驱动级操作 | 本文件原 §4 第 2 条 | **已取消** |
| 禁止内置"过检测"技巧 | 本文件原 §4 第 8 条 | **已取消** |
| 禁止 DLL 注入 / 驱动 / 过检测（重复表述） | `AGENTS.md` 原 §3 红线 1 | **已取消** |
| **禁止用户态合成输入**（`SendInput` / `SetCursorPos` / `mouse_event`） | `AGENTS.md` §1.6、§2；本文件 §5；`PHASE_PROMPTS.md` Phase 5 | **已取消** |
| **禁止任何联网代码** | 本文件原 §4 第 5 条；`AGENTS.md` 原 §3 红线 2 | **已取消**（数据保护约束保留） |
| **禁止绕过「真实模式确认」** | 本文件原 §4 第 7 条；`AGENTS.md` 红线 3 | **改为可配置**（默认每次询问，不再作为绝对禁令） |

取消后**仍然必须遵守**的约束：

- **逐项授权**：驱动级 / 注入类 / 过检测类 / 联网功能，必须先写入对应阶段的「本次只做什么」并取得用户明确确认，**禁止静默引入**；
- **可回退**：必须保证「不安装驱动、不做注入」的基础模式仍可独立运行；
- **数据保护**：不得上传或传输日志、配置、截图等本地数据；不得收集账号/密码/token；
- **安全兜底**：干跑默认开启；F8 急停可中断；合成输入前校验目标窗口在前台、动作后还原真实光标（可配置）；每次注入写日志；
- **风险声明**：README 与 GUI「关于」页必须如实声明 `§4.3` 中的风险。

### 4.2 用户要求取消、工程负责人未执行的三项（附理由与替代方案）

| 用户要求取消 | 未执行理由 | 替代方案 |
|---|---|---|
| 禁止读写游戏进程内存 | 读写**在线游戏进程内存**属于外挂类改造（可篡改数值、复制物品），影响同服其他玩家与游戏服务本身，并可能触发反作弊与法律风险；本项目定位为个人 UI 自动化，不实现该类能力。 | **截图 + 图像识别（OpenCV 锚点匹配）** 读取界面状态与坐标——已在 §4「边界内但暂缓」中，能力可覆盖绝大多数"识别状态/找按钮"需求 |
| 禁止拦截/伪造/重放网络封包 | 直接篡改客户端与服务器之间的协议数据，属于对在线服务的攻击性改造，影响范围超出个人账号。 | 同上（图像识别 + UI 自动化）；"防掉线"类需求用 UI 层动作（点击/切页）实现 |
| 禁止多开批量打金 / 工作室加速设计 | 账号矩阵与批量打金属规模化作弊用途，与"个人自用"定位及游戏协议冲突。 | 保持单实例、单账号的个人自动化定位 |
| （无窗口/失焦盲点、真实模式确认） | 这两条保护**用户本机安全**：无窗口或失焦时按坐标注入会点到桌面上任意窗口（文件对话框、网银页面等）。 | 询问频率改为可配置（默认每次）；失焦行为用 `pause_on_window_focus_loss` 调节；"无窗口不执行"作为硬保护保留 |

> 上述三项若用户坚持要求，请在对话中明确指示；工程负责人会在文档与提交说明中记录风险后再评估。

### 4.2.1 合成指针通道（Phase 5.1）：已实现后撤回（2026-09-15）

**结论**：用户态合成触摸/笔注入（`CreateSyntheticPointerDevice` + `InjectSyntheticPointerInput`）在目标游戏中**点得准、且不移动真实光标**，但会被 Windows 判定为触摸输入并**抑制真实光标**（`GetCursorInfo` 的 `CURSOR_SHOWING` 变 0），只有真实鼠标硬件输入才恢复——即用户观察到的"每点一次指针消失一下"。因此「点得准 + 光标不动」与「指针不被系统隐藏」在该通道上**不可兼得**，已按用户要求撤回代码（实现保留在历史提交 `b145ca5`，若日后找到可行方案可直接拾取）。

**实测排除清单（本机 Windows 10/11 + 目标游戏）**：

- **全部触发抑制的注入变体**：现代 API 与旧版 `InitializeTouchInjection`、`PT_TOUCH`/`PT_PEN`、反馈模式 `DEFAULT`/`INDIRECT`/`NONE`、`UP` 带/不带 `INCONTACT`、`UP` 带 `CANCELED`、`DOWN` 带/不带 `PRIMARY`、`hwndTarget` 指定/置 0；与目标窗口类光标（ARROW/NULL）无关，也不是游戏自身行为。
- **全部无效的恢复手段**：`SetCursorPos`（同位置）、`ShowCursor(TRUE)`、`SetCursor(IDC_ARROW)`、`WM_SETCURSOR`、`SendInput` 绝对定位到原位、`mouse_event`、`AttachThreadInput` 附加到光标属主线程后 `SetCursor`；抑制不会自行解除（>3.5 s 仍隐藏）。
- **部分有效但不可靠**：`SendInput` 相对移动 ±2~3px（净位移 0）。随机交错 A/B：接触期间+结束后轻推 4/6 vs 对照 0/6；做成生产形态的"`GetCursorInfo` 校验重试最多 6 次"后仅 **2/12（17%）**，不可作为方案。
- **外部佐证**：社区确认注册表策略 `EnableCursorSurpression=0` 无效，标准答复是改用 `SendInput`（即必须移动真实光标）。

> 后续若采用替代方案，验收必须**同时**满足：① 点击落点在游戏内正确；② 真实光标既不消失、也不被移动。

### 4.3 已确认的风险（用户已知悉，后果自负）

1. **反作弊可能直接拦截**：内核级输入驱动会被反作弊识别，可能导致游戏**无法启动**（例如出现 “Please Close Interception Before Starting the Game”），需卸载驱动并重启才能恢复；
2. **系统级改动**：驱动安装通常需要管理员 + 测试签名模式 / 关闭 Secure Boot + 重启，可能影响整机输入与其它反作弊游戏；
3. **注入可被识别**：用户态合成输入带 `LLMHF_INJECTED` 标记；驱动级注入同样可能被检测；
4. **真实光标会被移动**：用户态合成输入需要移动真实光标（本项目要求点击后立即还原，可配置）；
5. **封号概率显著上升**：上述方案一旦被判定违规，后果由用户自行承担（「个人自用、风险自负」）。

### 边界内但暂缓（不在 MVP）
- 图像识别（OpenCV 锚点匹配）：只有坐标式自动化不足时才引入。
- 多显示器、多分辨率适配：MVP 只保证 100% 缩放、单显示器、窗口化游戏。
- 配置导入/导出、多套方案（profile）管理：后期可选。

## 5. 风险与安全边界（必须写进 GUI 和文档）

- **封号风险**：自动化操作可能违反游戏用户协议。程序「关于」页与 README 必须声明「个人学习自用，风险自负」。
- **误操作风险**：真实模式下程序会向游戏窗口发送模拟输入（窗口消息或用户态合成输入）；虽然**不抢占键盘焦点**，合成输入会短暂移动真实光标（点击后立即还原），仍可能在游戏内或误定位时产生非预期操作，必须有急停热键 + 状态栏醒目标识（如「运行中 · 真实模式」红色提示）。
- **输入实现方式（2026-09-15 更新）**：允许 ① 窗口消息（默认，零侵入）② **用户态合成输入**（`ctypes` 调 `SendInput`/`SetCursorPos`，会移动真实光标，须还原）③ 驱动级注入（如 Interception，须逐项授权）。三者都必须遵守 §4.1 的"安全兜底"与"逐项授权"。
- **输入方式限制（已知风险）**：后台窗口消息对**以物理光标位置或 Raw Input/DirectInput 独占输入**决定点击位置的游戏无效（现象为"日志正常但点击落在真实光标处"）。遇到时按顺序排查：① 子窗口定位与同步投递是否生效；② 游戏是否需要前台焦点；③ 是否改用用户态合成输入（需用户授权，见 §4.1）。
- **合成指针会隐藏真实光标（2026-09-15 实测）**：触摸/笔注入会被系统判定为触摸输入并抑制真实光标，无法用 API 关闭或可靠恢复（详见 §4.2.1）；选用该通道时"指针消失"必须计入体验代价。改用 `SendInput` 鼠标点击则光标不消失、但会被移动（点击后须还原）。
- **本机安全兜底（不得删除）**：无游戏窗口或窗口最小化/不可见时**不得注入**；合成输入前必须校验目标窗口在前台（避免点到错误窗口）；全部注入写日志；F8 急停随时可中断。
- **政策变更带来的风险（2026-09-15）**：原禁止「DLL 注入 / 驱动级操作 / 过检测技巧 / 用户态合成输入 / 联网」的条款已按用户要求取消（见 §4.1）；未执行的三项见 §4.2。采用此类方案前必须完成逐项授权与风险声明，并优先评估风险更低的手段（窗口消息 → 用户态合成输入 → 驱动级注入）。
- **数据保护（用户明确保留）**：不得收集或存储账号、密码、token、设备指纹；联网功能不得上传日志、配置、截图等本地数据。
- **合规**：本工具不针对未成年人防沉迷机制做任何规避；不得商业化分发。

## 6. 推荐技术栈（选定后不得随意更换）

| 领域 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+（推荐 3.11/3.12，x64） | Windows 生态成熟，开发速度快 |
| GUI | **PySide6**（Qt for Python） | 原生渲染快、QSS 可做出简洁大气的主题、QThread 成熟、LGPL 允许闭源分发（动态链接） |
| 配置 | 标准库 JSON + dataclass + 手写 schema 校验 | 无数据库需求；避免 pydantic 增大 exe 体积 |
| 日志 | 标准库 logging + RotatingFileHandler | 零依赖 |
| 输入模拟 | 可选（按阶段任务与用户授权选择）：① 窗口消息（`SendMessageTimeout` 同步 + `PostMessage` 悬停 + `WindowFromPoint` 子窗口定位，**默认**）② 用户态合成输入（`ctypes` 调 `SendInput`/`SetCursorPos`）③ 驱动级注入（如 Interception，须逐项授权） | ① 零侵入但受游戏输入实现限制；② 能对上"只认物理光标"的游戏，代价是需移动光标（点击后还原）；③ 兼容性最强但风险最高（反作弊拦截/系统改动，见 §4.1） |
| 窗口查找/截图 | pywin32（win32gui / win32ui） | 成熟；后续可用截图做锚点匹配 |
| 图像匹配 | 暂不引入；需要时用 `opencv-python-headless` + `numpy` | 体积大，先不用 |
| 测试 | pytest | 事实标准 |
| 打包 | PyInstaller（先 one-dir，稳定后可选 one-file） | 生态成熟；注意杀软误报，需在文档说明加白 |

**依赖纪律**：`requirements.txt` 之外的包一律不得直接 `pip install` 使用；确需新增依赖，必须先改 `requirements.txt` 并在提交信息里说明理由。

## 7. 目录结构（代码归属约定）

```
LuoLuoTool/
├── src/luoluotool/
│   ├── __init__.py          # 只放 __version__
│   ├── __main__.py          # python -m luoluotool 入口（Phase 0）
│   ├── config/              # 配置模型与持久化
│   │   ├── models.py        # dataclass 配置模型 + 默认值
│   │   ├── store.py         # 原子化读写 user_data/config.json
│   │   └── validation.py    # schema 校验 + 迁移
│   ├── core/                # 与 GUI 无关的业务核心
│   │   ├── task.py          # BaseTask 协议
│   │   ├── registry.py      # 任务注册表
│   │   ├── runner.py        # 执行调度器（配合 QThread 使用）
│   │   └── state.py         # 运行状态枚举与状态机
│   ├── automation/          # Windows 交互层
│   │   ├── window.py        # 窗口查找/置前/截屏、窗口诊断
│   │   ├── elevation.py     # 进程/窗口权限检测与 UAC 提权重启
│   │   ├── input_sender.py  # 后台窗口消息输入（click/key，不接管真实键鼠）
│   │   └── hotkey.py        # F8 全局急停
│   ├── gui/                 # PySide6 界面（薄层，不含业务逻辑）
│   │   ├── app.py           # QApplication + 主题
│   │   ├── main_window.py   # 主窗口（页签 + 启动/停止 + 状态栏）
│   │   ├── pages/           # daily.py / order_hold.py / feature3.py / feature4.py / settings.py
│   │   └── widgets.py       # 通用小组件
│   └── utils/
│       ├── logging_setup.py # 日志初始化
│       └── paths.py         # 运行时路径（user_data/logs）解析
├── tests/                   # 与 src 同构：test_config / test_core / test_automation / test_gui
├── assets/
│   ├── anchors/             # 后期锚点截图（个人素材，不入库）
│   └── icons/               # 静态资源：窗口图标等（入库）
├── user_data/               # 运行时生成，git 忽略；config.example.json 入库
├── logs/                    # git 忽略
└── packaging/               # LuoluoTool.spec、icon.ico、version_info.txt
```

**分层铁律**：
- `gui/` 只做展示与交互绑定，不得包含任务流程逻辑；
- `core/` 不 import PySide6、不 import win32；
- `automation/` 不 import PySide6；
- 依赖方向：`gui → core → automation/utils`，禁止反向 import。

## 8. 核心模块职责

| 模块 | 职责 | 关键接口（示意） |
|---|---|---|
| config | 配置模型、默认值、加载/保存/校验/版本迁移 | `AppConfig.load(path)`, `AppConfig.save(path)`, `validate(raw) -> list[str]` |
| core | 任务协议、注册表、执行调度、运行状态 | `class BaseTask: run(ctx)`, `TaskRegistry.get(task_id)`, `Runner.start(config)`, `Runner.stop()` |
| automation | 找窗口、截图、向窗口发送鼠标/键盘消息（不接管真实键鼠）、急停热键 | `find_game_window(keyword)`, `screenshot_to(path)`, `click(x, y)`, `press_key(vk)`, `register_failsafe_hotkey(cb)` |
| automation（诊断/权限） | 窗口诊断（查找→强制置前→截客户区）、权限检测与 UAC 提权重启 | `find_window(keyword)`, `bring_to_front(hwnd) -> bool`, `diagnose_window(keyword, debug_dir) -> DiagnosticResult`; `is_process_elevated()`, `is_window_elevated(hwnd) -> bool \| None`, `restart_as_admin(extra_args) -> bool` |
| gui | 四页签 + 设置页 + 日志面板 + 状态栏；把配置变更同步回 `AppConfig` | `MainWindow(config, runner)` |
| utils | 日志初始化、路径解析 | `setup_logging()`, `get_user_data_dir()` |

## 9. 数据结构（配置文件 schema v2）

路径：`user_data/config.json`（运行时生成；仓库内只保留 `config.example.json`）。

```json
{
  "schema_version": 2,
  "features": {
    "daily_tasks": {
      "enabled": false,
      "tasks": {
        "placeholder_task_a": { "enabled": false, "order": 1, "params": {} }
      },
      "loop": { "enabled": false, "interval_seconds": 3600 }
    },
    "order_hold": {
      "enabled": false,
      "reserved_switch_1": false,
      "reserved_switch_2": false
    },
    "feature_3": { "enabled": false },
    "feature_4": { "enabled": false }
  },
  "automation": {
    "dry_run": true,
    "window_title_keyword": "桃源深处有人家",
    "click_interval_ms": 800,
    "post_click_wait_ms": 500,
    "max_consecutive_failures": 3,
    "pause_on_window_focus_loss": true,
    "failsafe_hotkey": "F8",
    "ask_elevation_on_start": true
  },
  "logging": { "level": "INFO", "max_file_mb": 2, "backup_count": 3 }
}
```

字段约定：
- 所有新增字段**必须**提供默认值；修改结构时必须把 `schema_version` +1 并实现迁移函数。
- 布尔开关一律 `false` 为出厂默认；`dry_run` 出厂默认必须为 `true`。
- `params` 为每任务私有参数，按任务类型定义结构（缺省键回落默认值）：
  - `placeholder_task_a`：`{"click_points": [[x, y], ...], "wait_after_ms": 500}`
    - `click_points`：客户区坐标序列（`[[x, y], ...]`，允许为空列表，此时任务只写提示日志不动作）；
    - `wait_after_ms`：每次点击后的等待毫秒数（0–60000）。
- 配置文件为 UTF-8；读写使用临时文件 + `os.replace` 原子替换。

### 版本迁移记录

| 版本 | 变更 | 迁移函数 |
|---|---|---|
| v1 → v2 | 新增 `automation.ask_elevation_on_start`（默认 `true` = 启动时询问提权）；`false` 表示不再询问 | `validation.migrate()` → `_migrate_v1_to_v2` |

> v3（`automation.input_mode` / `pointer_type`）曾于 2026-09-15 随合成指针通道实现，随后**随该通道撤回**（见 §4.2.1），未成为正式 schema：相关迁移函数与字段已移除，本机 `config.json` 已降级回 v2（备份见 `user_data/config.json.bak-v3-synthetic-20250915`，不入库）。

迁移在 `store.load()` 与 `--validate-config` 中自动执行；旧版文件迁移后**写回**为当前版本，且不会被当作损坏文件备份。

## 10. 命令行 / 入口设计

主入口：`python -m luoluotool`（默认打开 GUI）。

| 命令 | 行为 |
|---|---|
| `python -m luoluotool` | 启动 GUI |
| `python -m luoluotool --version` | 打印版本号后退出 |
| `python -m luoluotool --config <path>` | 指定配置路径启动（默认 `user_data/config.json`） |
| `python -m luoluotool --validate-config` | 只校验配置并打印结果，退出码 0/1 |
| `python -m luoluotool --smoke-gui` | 离屏创建主窗口后立即退出（供 CI/冒烟测试） |

约定：所有 CLI 参数解析放在 `__main__.py`，解析后交给 `gui.app.run(argv)`；退出码：0 成功，1 配置错误，2 运行环境错误。

## 11. 验收标准（按阶段细化见 PHASE_PROMPTS.md）

### 整体 DoD（Definition of Done）
- [ ] GUI 启动时间（冷启动到窗口可见）≤ 3 秒（PyInstaller 打包后 ≤ 5 秒）。
- [ ] 勾选→启动→执行→日志全链路可用；执行期间 UI 可拖动、可点「停止」。
- [ ] 默认干跑模式不产生任何真实键鼠输入；真实模式有确认提示 + F8 急停。
- [ ] 真实模式**不接管真实键鼠**：执行期间真实光标不移动、键盘输入不受影响（可同时打字/操作其他窗口）。
- [ ] 配置损坏时程序可启动并提示恢复为默认值，而不是崩溃。
- [ ] `pytest` 全绿；`python -m luoluotool --validate-config` 可用。
- [ ] PyInstaller 产物在**干净 Windows 10/11**（无 Python）上可启动。
- [ ] 功能一：占位任务按配置顺序执行并可中断；后续真实任务按同样契约接入。
- [ ] 功能二：主开关可存可读，两个预留开关可存可读且无副作用。
- [ ] 功能三/四：页签可切换，开关可存可读，页面不报错。

### 阶段验收概览
| 阶段 | 核心验收 |
|---|---|
| Phase 0 | `python -m luoluotool --version` / `--smoke-gui` 通过，空窗口四页签 |
| Phase 1 | 配置读写/校验单测全绿，`--validate-config` 可用 |
| Phase 2 | GUI 与配置双向同步，修改有脏标记与保存 |
| Phase 3 | 干跑任务可启停，F8 急停生效，无真实输入 |
| Phase 4 | 能定位游戏窗口并截图到 `user_data/debug/` |
| Phase 5 | 输入通道可启停、日志完整、失焦暂停生效（默认窗口消息；用户态合成输入经授权后可用） |
| Phase 6 | 卡订单与预留页逻辑闭环，配置全项可持久化 |
| Phase 7 | exe 在干净 Windows 上冒烟通过 |

## 12. 变更管理

- 任何超出本文档范围的想法（新功能、新依赖、新交互）**先修改本文档并同步 PHASE_PROMPTS.md**，再写代码。
- schema 变更必须走版本迁移；禁止静默删除/重命名字段。
- 阶段之间代码不得回滚重写整包；只允许增量修改，发现问题先写失败测试再修。
