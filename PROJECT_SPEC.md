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

以下内容**永久禁止**，任何阶段不得实现、不得预留接口：

1. **禁止读写游戏进程内存**（不搜索、不修改任何内存值）。
2. **禁止 DLL 注入 / 钩子注入 / 驱动级操作**。
3. **禁止拦截、伪造、重放游戏网络封包**。
4. **禁止破解游戏客户端、绕过更新、绕过反作弊系统**。
5. **禁止收集或存储玩家账号、密码、token、设备指纹**；程序不得要求登录。
6. **禁止联网功能**：不自动更新、不上传日志、不调用任何远程服务。
7. **禁止多开批量打金、工作室用途**的加速设计（不做多实例协调、不做账号矩阵）。
8. **禁止内置任何会显著增加封号风险的“过检测”技巧**。
9. **禁止未经用户确认就在真实模式下执行**：启动真实自动化前必须有明确 UI 确认 + 干跑预演。
10. **禁止**在无游戏窗口时静默执行、以及游戏窗口失焦后继续盲点（可配置为“失焦即暂停”）。

### 边界内但暂缓（不在 MVP）
- 图像识别（OpenCV 锚点匹配）：只有坐标式自动化不足时才引入。
- 多显示器、多分辨率适配：MVP 只保证 100% 缩放、单显示器、窗口化游戏。
- 配置导入/导出、多套方案（profile）管理：后期可选。

## 5. 风险与安全边界（必须写进 GUI 和文档）

- **封号风险**：自动化操作可能违反游戏用户协议。程序「关于」页与 README 必须声明「个人学习自用，风险自负」。
- **误操作风险**：真实模式下程序会向游戏窗口发送模拟输入消息；虽然**不接管真实鼠标键盘**（不移动真实光标、不抢占键盘焦点），仍可能在游戏内产生非预期操作，必须有急停热键 + 状态栏醒目标识（如「运行中 · 真实模式」红色提示）。
- **不使用接管式输入**：永久禁止 `SendInput` / `SetCursorPos` / `mouse_event` 等会接管真实键鼠的接口；输入一律通过窗口消息实现（见 §6）。
- **输入方式限制（已知风险）**：若游戏以 `Raw Input`/`DirectInput` 独占方式读取输入，窗口消息可能不被游戏识别（现象为“日志正常但游戏无反应”）。遇到时先记录现象并与用户确认，不得擅自改用接管真实键鼠的方案。
- **合规**：本工具不针对未成年人防沉迷机制做任何规避；不得商业化分发。

## 6. 推荐技术栈（选定后不得随意更换）

| 领域 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+（推荐 3.11/3.12，x64） | Windows 生态成熟，开发速度快 |
| GUI | **PySide6**（Qt for Python） | 原生渲染快、QSS 可做出简洁大气的主题、QThread 成熟、LGPL 允许闭源分发（动态链接） |
| 配置 | 标准库 JSON + dataclass + 手写 schema 校验 | 无数据库需求；避免 pydantic 增大 exe 体积 |
| 日志 | 标准库 logging + RotatingFileHandler | 零依赖 |
| 输入模拟 | `ctypes` 调用 Windows `PostMessage` 向游戏窗口发送鼠标/键盘消息（后台输入） | **不接管真实键鼠**：不移动真实光标、不抢占键盘焦点，玩家可正常使用键鼠；无需前台焦点；零第三方依赖，不引入 pyautogui |
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
- `params` 为每任务私有参数，先在占位任务中使用 `{}`，后续阶段再定义。
- 配置文件为 UTF-8；读写使用临时文件 + `os.replace` 原子替换。

### 版本迁移记录

| 版本 | 变更 | 迁移函数 |
|---|---|---|
| v1 → v2 | 新增 `automation.ask_elevation_on_start`（默认 `true` = 启动时询问提权）；`false` 表示不再询问 | `validation.migrate()` → `_migrate_v1_to_v2` |

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
| Phase 5 | 真实输入可启停、日志完整、失焦暂停生效 |
| Phase 6 | 卡订单与预留页逻辑闭环，配置全项可持久化 |
| Phase 7 | exe 在干净 Windows 上冒烟通过 |

## 12. 变更管理

- 任何超出本文档范围的想法（新功能、新依赖、新交互）**先修改本文档并同步 PHASE_PROMPTS.md**，再写代码。
- schema 变更必须走版本迁移；禁止静默删除/重命名字段。
- 阶段之间代码不得回滚重写整包；只允许增量修改，发现问题先写失败测试再修。
