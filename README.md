# LuoLuoTool — 项目初始化文件夹

本文件夹是 **LuoLuoTool**（《桃源深处有人家》Windows 自动化挂机工具）的工程初始化包，
专为「AI 代码编辑器（Codex / Cursor / Claude Code / Windsurf）驱动开发」设计。

它不包含业务代码，只包含**给 AI 看的工程文档 + 目录骨架**。代码由 AI 按
`PHASE_PROMPTS.md` 中的阶段提示词逐步生成，人类只需复制粘贴提示词并验收。

---

## 1. 文件清单与用途

| 文件 | 作用 | 给谁看 | 什么时候看 |
|---|---|---|---|
| `README.md` | 本说明：文件怎么用、第一条 prompt 怎么写 | 人 + AI | 现在 |
| `PROJECT_SPEC.md` | 完整项目背景：目标、范围、边界、技术栈、数据结构、验收标准 | AI（长期上下文） | 每个新会话都要让 AI 读 |
| `AGENTS.md` | 长期开发规范：编码原则、禁止事项、测试/提交要求、小步推进方法 | AI（Codex/Cursor/Claude Code/Windsurf 自动识别） | 每个新会话自动加载 |
| `DATA_API_PREP.md` | 外部服务/API/密钥/本地资源准备清单 | 人 | 开始开发前先看完 |
| `PHASE_PROMPTS.md` | 分阶段提示词（一段一段复制给 AI） | 人 → 复制给 AI | 每完成一阶段后 |
| `CHECKLIST.md` | 遗漏项检查表（配置/日志/安全/合规等） | 人 + AI | 每个阶段收尾时逐项核对 |
| `BUG_HUNT_GUIDE.md` | 排查手册：架构/数据流/线程模型、三套坐标系、21 条可验证不变量、15 条历史 bug 档案（症状/根因/修法/回归测试）、已知薄弱点、测试注入缝、实机探针脚本 | 人 + 另一个排查会话 | **接手排查 bug / 交接给别人找 bug 时先读** |

## 2. 目录结构（已创建，空目录用 `.gitkeep` 占位）

```
LuoLuoTool/
├── README.md                 # 本文件
├── AGENTS.md                 # 长期开发规范
├── PROJECT_SPEC.md           # 项目完整说明书
├── DATA_API_PREP.md          # 外部服务/本地资源准备清单
├── PHASE_PROMPTS.md          # 分阶段提示词
├── CHECKLIST.md              # 遗漏项检查表
├── BUG_HUNT_GUIDE.md         # 排查手册（不变量/历史 bug 档案/实机探针）
├── .gitignore                # 忽略 venv/构建产物/本地配置/截图
├── requirements.txt          # 运行时依赖
├── requirements-dev.txt      # 开发/测试/打包依赖
├── src/
│   └── luoluotool/           # Python 包（代码由 Phase 0 起逐步生成）
│       ├── __init__.py       # 已创建（版本号占位）
│       ├── core/             # 任务调度/状态机（后续生成）
│       ├── gui/              # PySide6 界面（后续生成）
│       ├── automation/       # 窗口定位/输入模拟（后续生成）
│       ├── config/           # 配置模型/读写/校验（后续生成）
│       └── utils/            # 日志等工具（后续生成）
├── tests/                    # pytest 测试
├── assets/
│   ├── templates/            # 识别图片：我自己整理/命名的模板（入库）
│   ├── screenshots/          # 识别底图：用本工具自带截图功能截的画面（不入库）
│   ├── anchors/              # 开发者调试页「框选」生成的图（不入库）
│   └── icons/                # 窗口图标等静态资源（入库）
├── user_data/                # 运行时用户数据（不入库）
│   ├── debug/                # 诊断截图输出目录
│   └── config.example.json   # 配置样例（Phase 1 生成）
├── logs/                     # 运行日志（不入库）
└── packaging/                # PyInstaller spec / 图标 / 版本信息（Phase 7）
```

> 说明：现在只有文档和目录骨架，**没有任何业务代码**。这是故意的——所有代码
> 都必须按 `PHASE_PROMPTS.md` 一个阶段一个阶段地生成并验收。

## 3. 使用流程（总览）

1. **先读 `DATA_API_PREP.md`**，确认无需注册任何外部服务，准备好本地环境（Windows、Python、游戏窗口）。
2. **把 `PROJECT_SPEC.md` 和 `AGENTS.md` 喂给 AI**（大部分 AI 编辑器会自动读 `AGENTS.md`）。
3. **复制第一条 prompt（见第 4 节）发给 AI**，执行 Phase 0。
4. 每完成一个阶段，**按该阶段的「验收命令」逐条验证**，并对照 `CHECKLIST.md` 收尾。
5. 验收通过后，再复制下一个阶段的提示词。**不要跳阶段，不要一次让 AI 做完整项目。**

## 4. 第一步：丢给 AI 代码编辑器的第一条 prompt

把整个 `LuoLuoTool` 文件夹作为工作目录打开，然后把下面这段**原文复制**发给 AI：

````text
你是本项目的工程负责人。请先完整阅读以下文件，再开始任何编码：
1. PROJECT_SPEC.md —— 项目背景、范围、边界、技术栈、数据结构、验收标准；
2. AGENTS.md —— 必须遵守的开发规范；
3. DATA_API_PREP.md —— 无需外部 API，仅需本地资源（已确认）。

读完不要动手写代码，先复述三点给我确认：
A. 本项目要做什么、明确不做什么；
B. 你打算用的 GUI 框架和打包方案；
C. 你准备如何按小步推进方式执行。

确认后，只执行 PHASE_PROMPTS.md 中的 Phase 0，其余阶段一律不做。
````

AI 复述无误后，再追加一句：

```text
现在只执行 PHASE_PROMPTS.md 的 Phase 0。严格按照该阶段的“本次只做什么 / 不要做什么 / 验收命令 / 完成标准”执行，不要超出范围。
```

之后每个阶段都按同样的方式：**粘贴「通用上下文块」+ 该阶段提示词**（模板见 `PHASE_PROMPTS.md` 开头）。

## 5. 给新会话的通用上下文块（每次新开对话都要贴）

AI 编辑器的新会话不会记得之前的对话。每次新开会话时，先贴这一段：

```text
工作目录是 LuoLuoTool 项目根目录。请先阅读 AGENTS.md 和 PROJECT_SPEC.md，
并阅读 PHASE_PROMPTS.md 以了解当前进度阶段。你只被授权执行我接下来指定的
一个阶段，不得修改已有代码之外的范围，不得跳过测试，不得引入文档未批准的新依赖。
```

## 6. 关键决策速览（详见 PROJECT_SPEC.md）

| 决策点 | 结论 |
|---|---|
| 语言 | Python 3.11+（Windows x64） |
| GUI | PySide6（Qt），QSS 主题，五页签 + 可选「开发者调试」页；**所有页签统一继承 `ScrollablePage`**（内容进滚动区 + 建议尺寸常量化），页签区高度不随页签挂载/卸载变化（可用 `python -m luoluotool --measure-layout` 自查） |
| 配置存储 | 本地 JSON（`user_data/config.json`），无数据库 |
| 自动化输入 | **真实鼠标键盘（`SendInput`，唯一实现方式）**：真实移动光标 + 模拟真实鼠标/键盘（支持点击、鼠标滑动拖拽、按键序列：组合键如 `ctrl+s`、长按如 `w*800`）；**每次点击/按键前都会校验并把游戏窗口置于最顶层**（不在最顶层则先置顶/置前，无法确保时绝不输入）；代价是会抢前台，点击与滑动后都按设置还原鼠标位置（滑动为**松手后延迟 + 分帧小步移回**，避免一次跳回被残留拖拽状态算成巨大位移；滑动轨迹带缓出与末尾静止、松手后复查左键已抬起，避免画面惯性乱飘） |
| 窗口/截图 | pywin32；图像锚点匹配后期可选引入 OpenCV |
| 打包 | PyInstaller one-dir（先目录后单文件） |
| 外部 API / LLM / 网络 | 全部不需要，程序离线运行 |
| 图像识别 | **OpenCV 模板匹配**（`opencv-python-headless` + `numpy`，2026-09-19 引入）：给模板图 → 在游戏窗口客户区里找 → 返回命中坐标（中心/左上/尺寸/匹配度/**缩放比例**）。**画面放大或缩小都能识别**（多尺度匹配默认开启：先搜 0.3x–2.0x，找不到再扩到 0.3x–4.0x；`--no-scale` 可关闭）；PrintWindow 取到黑帧时自动换其它取景方式。**多张模板**：一次可放多张图打同一块区域，按顺序尝试、第一张达到阈值的就直接用它的结果（读不出来的图自动跳过）；**一张图匹配多个区域**：同一张图在屏幕上出现多处时全部列出（第 1 处＝匹配度最高，作为默认使用值），「最多列出」/`--max-results` 控制条数。用法：调试页「图片识别匹配测试」的模板列表（「添加图片…」可多选，或点「框选截图生成模板」直接生成并加入列表；「识别成功时保存带框截图」为可选开关），或命令行 `python -m luoluotool --recognize 图片A.png [图片B.png ...] --threshold 0.85 --max-results 20`（退出码 0 命中 / 1 未命中）。模板存 `assets/anchors/`（不入库），带框截图存 `user_data/debug/vision_*.png` |
| 开发者调试 | 设置页可勾选「开发者调试」，顶部出现调试页：窗口诊断、布局测量、**图片识别匹配测试（放在页面最前：模板列表 + 阈值 + 最多列出 → 给出命中坐标）**、干跑开关、**还原光标开关（点击/滑动后是否把真实鼠标移回原位）**、鼠标单点/连点（都带「点击时长」）、屏幕滑动、键盘输入等带参数的测试按钮（复用同一输入通道与安全规则） |
| 安全底线 | **默认真实模式**（2026-09-19 起 `dry_run` 默认关闭）+ 启动前强制确认弹窗 + F8 全局急停 + 点击坐标必须在游戏窗口内（越界不点击）；干跑可在「开发者调试」页勾选；不上传日志/配置/截图；账号密码 token 永不收集 |
| 任务编排 | 队列 = **日常任务组**（任务勾选，按 `order` + 任务 ID 字典序）→ **单功能组**（功能主开关，固定 `order_hold` → `feature_3` → `feature_4`）；失败计数与循环对整队列统一；启动时日志打印 `任务队列（N 个）：a → b → c`（Phase 6，预留开关不参与编排） |

## 7. 构建与发布（Phase 7）

### 7.1 一键构建

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

脚本流程（任一环节失败即中止并返回非 0 退出码）：

1. 准备 `.venv` 虚拟环境（不存在则创建）；
2. 安装 `requirements-dev.txt`（离线时自动降级为"检查关键依赖是否已存在"）；
3. **构建前门禁**：`pytest -q` 全量测试 + `--validate-config` + `--measure-layout`；
4. 清理 `build\`、`dist\` 后执行 `PyInstaller --clean --noconfirm packaging\LuoLuoTool.spec`（one-dir）；
5. 打印产物体积（exe 大小 + 目录合计 + 文件数）；
6. exe 冒烟并输出启动耗时：`--version` → `--validate-config` → `--smoke-gui`。

可选参数：`-SkipInstall`（离线/已装好依赖）、`-SkipTests`（仅排错用，**正式打包不要跳过**）。

### 7.2 产物与分发

- 产物：`dist\LuoLuoTool\LuoLuoTool.exe`；**必须整个 `dist\LuoLuoTool\` 目录一起拷贝**（one-dir）。
- 目标机器**无需安装 Python**；首次运行会在产物目录下自动生成 `user_data\`（配置）与 `logs\`（日志）。
- **GUI 子系统（`console=False`）**：双击 exe **不会出现 cmd 黑窗口**（2026-09-19 用户要求）。
  代价：命令行参数看不到直接输出，需要**重定向**才能读取（GUI 程序在 PowerShell 里 `&` 调用也
  不会等待、读不到退出码）：

  ```powershell
  # 读 --version（.exe 换成你的路径）
  Start-Process .\dist\LuoLuoTool\LuoLuoTool.exe -ArgumentList '--version' -Wait -PassThru `
      -RedirectStandardOutput out.txt | Select-Object ExitCode; Get-Content out.txt
  ```

  日志不受影响：GUI 日志面板 + `logs\luoluotool.log` 照常记录（窗口化进程没有控制台，
  `sys.stdout/stderr` 由 `packaging/rthook_windowed_stdio.py` 接到空设备，避免日志处理器报错）。
- 版本号来源：`src/luoluotool/__init__.py` 的 `__version__`；`packaging\version_info.txt`
  必须同步（`tests/test_packaging.py` 有守卫测试，改版本号时两处一起改）。

### 7.3 杀软误报处理（必须先做）

PyInstaller 打包的 exe 常被 Windows Defender / 国产杀软误报为可疑程序（bootloader 特征），
**不是病毒**。处理方式（二选一）：

1. Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项 → 添加排除项 → **文件夹** →
   选择 `D:\...\LuoLuoTool\dist\LuoLuoTool`；
2. 或把整个 `dist\LuoLuoTool` 目录加入所用杀软的信任区，再运行。

若仍被隔离：把 exe 从隔离区恢复并加白，重新执行 7.1 构建。

### 7.4 干净机器验证步骤（无 Python 环境）

1. 在目标机器（Windows 10/11 x64）上创建目录，例如 `D:\LuoLuoTool\`；
2. 把整个 `dist\LuoLuoTool\` **目录**拷贝进去（不要只拷 exe）；
3. 加白名单（见 7.3）；
4. 打开 PowerShell 在该目录执行（GUI 子系统需重定向读取输出；`build.ps1` 已按同样方式冒烟）：
   ```powershell
   Start-Process .\LuoLuoTool.exe -ArgumentList '--version' -Wait -PassThru -RedirectStandardOutput v.txt | Select ExitCode; Get-Content v.txt   # 应输出 luoluotool 0.1.0
   Start-Process .\LuoLuoTool.exe -ArgumentList '--smoke-gui' -Wait -PassThru | Select ExitCode                                                       # 应输出 0
   ```
5. 双击 `LuoLuoTool.exe` 打开 GUI：检查五个页签可切换、日志面板有输出；
6. 改一个设置（例如勾选"开发者调试"）→ 点「保存」→ 关闭程序再启动，确认设置被记住
   （文件位置：`user_data\config.json`）；
7. 点「窗口诊断」应能查找游戏窗口并截图到 `user_data\debug\`（需游戏已启动且本工具已提权）。

> 已知限制：未做代码签名（首次运行可能有 SmartScreen 提示）；one-dir 首次启动比开发期慢
> （一次性解包 + Qt 初始化）；不做 one-file 与安装包（Phase 7 明确范围外）。

> 已知问题：无（`--measure-layout` 在 GBK 控制台的 `UnicodeEncodeError` 已于 2026-09-19 修复：
> 报告改用 GBK 可编码的 `[OK]`/`[NG]` 标记，并加了打印降级兜底 `__main__._print_safe`）。

### 7.5 实测数据（2026-09-19，本机 Windows 10 x64）

| 指标 | 数值 |
|---|---|
| PE 子系统 | **2 = IMAGE_SUBSYSTEM_WINDOWS_GUI**（双击无 cmd 窗口；`pefile` 实测校验） |
| exe 大小 | 2.18 MB（`LuoLuoTool.exe`，含图标与版本资源） |
| 产物目录 | 114.4 MB / 219 个文件（其中 `_internal` 约 111.6 MB、`assets` 0.6 MB） |
| `--version` 启动耗时 | 冷启动 3.28 s（首次运行）/ 热启动 **0.7–1.0 s**（重定向读取，含 GUI 子系统引导） |
| `--validate-config` 耗时 | **1.03 s** |
| `--smoke-gui` 耗时（含建窗 + 布局） | **2.04 s**（冷）/ ≈0.9 s（热） |
| 无重定向运行（模拟双击） | 退出码 0，`logs\luoluotool.log` 正常写入、无 "Logging error"（运行时钩子生效） |
| 无 Python 环境验证 | 拷贝到新目录 + 最小 PATH（`C:\Windows\system32;C:\Windows`）→ 三项命令退出码均 0，自动生成 `user_data\config.json` 与 `logs\` |

## 8. 风险声明（必须阅读）

本工具通过模拟键鼠操作自动化游戏日常，**可能违反游戏用户协议，存在封号风险**，
且坐标/图像自动化在不同分辨率、窗口位置下可能失效。本文件夹要求：

- 仅用于**个人学习与自用**，不发布、不售卖、不用于多开打金；
- 全程 **干跑模式（dry-run）** 优先，真实输入阶段必须保留急停热键；
- 不读取/修改游戏内存，不拦截网络封包（这两条用户曾要求取消，工程负责人未执行并给出替代方案，见 `PROJECT_SPEC.md` §4.2）；
- 不收集账号、密码、token、设备指纹；联网功能不得上传日志/配置/截图等本地数据；
- 驱动级 / 注入类 / 过检测类 / 用户态合成输入方案：必须**逐项授权**并声明风险（可能导致游戏无法启动、需改测试签名/Secure Boot、光标被短暂移动、封号概率上升），详见 `PROJECT_SPEC.md` §4.1。

以上红线同时写入 `PROJECT_SPEC.md` 与 `AGENTS.md`，AI 必须在所有阶段遵守。
（2026-09-15 按用户要求取消了「DLL 注入 / 驱动级操作 / 过检测技巧 / 用户态合成输入 / 联网」五类限制。）
