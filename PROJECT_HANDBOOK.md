# PROJECT_HANDBOOK.md — LuoLuoTool 工程手册

> **这个文件是什么**：**工程手册**，面向接手项目和维护代码的人，主要说明文档导航、开发约定与构建方式。

> **想了解"这个工具是什么、怎么装、怎么用"，请看 `README.md`**（用户视角）。

本仓库是 **LuoLuoTool**（《桃源深处有人家》Windows 自动化挂机工具）的工程包，
按小步增量方式维护：
本次工作范围由用户任务明确，项目文档提供边界、规范与验收依据。

---

## 1. 文件清单与用途

| 文件 | 作用 | 给谁看 | 什么时候看 |
|---|---|---|---|
| `README.md` | **用户视角的使用说明**：这是什么、装什么、怎么用、配置与 FAQ、风险声明 | 人（第一次拿到仓库的人） | 先看这个 |
| `PROJECT_HANDBOOK.md` | **本文件（工程手册）**：文档导航、新会话流程、关键决策速览、构建发布 | 人 + AI | 要动手改这个工程时 |
| `PROJECT_SPEC.md` | 完整项目背景：目标、范围、边界、技术栈、数据结构、验收标准 | AI（长期上下文） | 每个新会话都要让 AI 读 |
| `AGENTS.md` | 长期开发规范：编码原则、禁止事项、测试/提交要求、小步推进方法 | AI（Codex/Cursor/Claude Code/Windsurf 自动识别） | 每个新会话自动加载 |
| `DATA_API_PREP.md` | 外部服务/API/密钥/本地资源准备清单 | 人 | 开始开发前先看完 |
| `CHECKLIST.md` | 遗漏项检查表（配置/日志/安全/合规等） | 人 + AI | 每个阶段收尾时逐项核对 |
| `BUG_HUNT_GUIDE.md` | 排查手册：架构与数据流、坐标系、不变量、常见症状排查、当前限制、测试注入点和实机探针 | 人 + AI | 接手排查或维护相关模块时阅读 |

**文档冲突时的依据**：项目边界与配置结构以 `PROJECT_SPEC.md` 为准；开发流程以 `AGENTS.md` 为准；用户操作与功能状态以 `README.md` 为入口，并用源码核实；修改范围以用户任务为准。`CHECKLIST.md` 用于验收，`BUG_HUNT_GUIDE.md` 用于定位问题。

## 2. 目录结构

```
LuoLuoTool/
├── README.md                 # 用户视角的使用说明（先看这个）
├── PROJECT_HANDBOOK.md       # 本文件：工程手册
├── AGENTS.md                 # 长期开发规范
├── PROJECT_SPEC.md           # 项目完整说明书
├── DATA_API_PREP.md          # 外部服务/本地资源准备清单
├── CHECKLIST.md              # 遗漏项检查表
├── BUG_HUNT_GUIDE.md         # 排查手册（不变量/症状排查/实机探针）
├── .gitignore                # 忽略 venv/构建产物/本地配置/截图
├── requirements.txt          # 运行时依赖
├── requirements-dev.txt      # 开发/测试/打包依赖
├── src/
│   └── luoluotool/           # Python 包（GUI、配置、任务编排、自动化等）
│       ├── __init__.py       # 应用版本
│       ├── core/             # 任务调度、配置绑定与应用服务
│       ├── gui/              # PySide6 界面与工作线程
│       ├── automation/       # 窗口定位、截图、识别与真实输入
│       ├── config/           # 配置模型、迁移、校验与读写
│       └── utils/            # 路径、日志与键名等工具
├── tests/                    # pytest 测试
├── assets/
│   ├── templates/            # 识别图片：我自己整理/命名的模板（入库）
│   ├── screenshots/          # 识别底图：用本工具自带截图功能截的画面（不入库）
│   ├── anchors/              # 开发者调试页「框选」生成的图（不入库）
│   └── icons/                # 窗口图标等静态资源（入库）
├── user_data/                # 运行时用户数据（不入库）
│   ├── debug/                # 诊断截图输出目录
│   └── config.example.json   # 配置样例（随 schema 维护）
├── logs/                     # 运行日志（不入库）
└── packaging/                # PyInstaller spec / 图标 / 版本信息
```

> 目录树概览以当前仓库为准；功能状态见 `README.md`「功能现状」和 `PROJECT_SPEC.md`「当前功能」。

## 3. 使用流程（总览）

1. **先读 `DATA_API_PREP.md`**，确认当前开发无需外部 API 或账号，并准备本地环境（Windows、Python；实机验证时还需游戏窗口）。
2. **把 `PROJECT_SPEC.md` 和 `AGENTS.md` 喂给 AI**（大部分 AI 编辑器会自动读 `AGENTS.md`）。
3. 先阅读项目文档并核对当前状态；然后按用户本次任务明确的范围修改。
4. 只做本次要求的范围；只有包含代码修改的提交才执行测试与验收命令，仅文档、忽略规则等非代码修改不执行测试；对照 `CHECKLIST.md` 收尾。
5. 不扩展到未要求的功能；较大的工作拆成可独立检查的小步。

## 4. 新会话：先对齐状态与范围

在 AI 编辑器中打开项目根目录，复制下面的完整提示词，并填写「本次任务」。项目状态由 AI 读取仓库确认，无需手动填写版本号或完成进度。

```text
请协助维护 LuoLuoTool，工作目录为项目根目录。

本次任务：
<填写要修改的内容和期望结果；排查问题时补充现象与复现步骤>

开始前：
1. 阅读 AGENTS.md、PROJECT_SPEC.md 和 README.md，了解开发规范、项目边界和当前功能。按任务需要查阅 CHECKLIST.md、BUG_HUNT_GUIDE.md 或 DATA_API_PREP.md。
2. 查看 git status，并阅读任务相关的源码与测试，确认当前实现和已有未提交修改。文档与源码不一致时说明差异，不把计划功能当成已实现功能。
3. 简要说明本次任务的理解、准备修改的文件和验收方式，再按 AGENTS.md 的小步流程实施。只处理本次任务，保留已有修改；需求不清、文档冲突影响实施或关键方案无法判断时，先向我提问。

验收与交付：
- 只有源代码、测试代码或脚本发生新增、修改、删除时，才按 AGENTS.md 执行测试与验收命令。仅文档、忽略规则等非代码修改只核对内容和差异。
- 测试必须使用干跑模式，不产生真实鼠标或键盘输入。
- 完成后说明改了什么、执行了哪些检查、测试结果或跳过原因，以及仍需处理的问题。
- 提交、推送和打包按我的明确要求执行。

如果我还没有给出具体任务，只简要说明当前状态和需要澄清的问题，等待任务。
```

## 5. 给新会话的通用上下文块

需求明确时可用下面的简短版，替换「本次任务」后发送。它与第 4 节二选一，无需重复粘贴。

```text
请在 LuoLuoTool 项目根目录完成以下任务：
<填写本次任务和期望结果>

先阅读 AGENTS.md、PROJECT_SPEC.md 和 README.md，查看 git status 与相关源码，按需查阅其他项目文档。以仓库现状为依据，区分已实现功能和计划项，保留已有未提交修改。

简要说明修改范围后，按项目规范小步实施；拿不定主意或需求不清时问我。只有代码（含测试和脚本）改动才执行测试与验收命令，测试不得产生真实输入；仅文档等非代码修改只检查内容与差异。完成后说明改动、检查结果和遗留问题，提交、推送和打包按我的明确要求执行。
```

## 6. 关键决策速览（详见 PROJECT_SPEC.md）

| 决策点 | 结论 |
|---|---|
| 语言 | Python 3.11+（Windows x64） |
| GUI | PySide6（Qt），QSS 主题，六页签 + 可选「开发者调试」页（「关于」页集中放风险声明/第三方许可/运行环境）；**所有页签统一继承 `ScrollablePage`**（内容进滚动区 + 建议尺寸常量化），页签区高度不随页签挂载/卸载变化（可用 `python -m luoluotool --measure-layout` 自查） |
| 配置存储 | 本地 JSON（`user_data/config.json`），无数据库 |
| 自动化输入 | **真实鼠标键盘（`SendInput`，唯一实现方式）**：真实移动光标 + 模拟真实鼠标/键盘（支持点击、鼠标滑动拖拽、按键序列：组合键如 `ctrl+s`、长按如 `w*800`）；**每次点击/按键前都会校验并把游戏窗口置于最顶层**（不在最顶层则先置顶/置前，无法确保时绝不输入）；代价是会抢前台，点击与滑动后都按设置还原鼠标位置（滑动为**松手后延迟 + 分帧小步移回**，避免一次跳回被残留拖拽状态算成巨大位移；滑动轨迹带缓出与末尾静止、松手后复查左键已抬起，避免画面惯性乱飘） |
| 窗口/截图与识别 | pywin32；OpenCV + NumPy 模板匹配已实现 |
| 打包 | PyInstaller one-dir；one-file 与安装包未规划 |
| 外部 API / LLM / 网络 | 当前没有网络请求；启动时远程配置更新是尚未实现的唯一计划用途，见 `PROJECT_SPEC.md`「远程配置计划」 |
| 图像识别 | OpenCV + NumPy 模板匹配，结果为客户区坐标与匹配度、缩放比例。默认先搜 0.3x–2.0x，未命中再扩到 4.0x；`--no-scale` 只按原始尺寸匹配。多模板共用一张截图，按顺序采用第一张达标的结果；多处命中按匹配度排序。调试页与 `--recognize` 均可使用，识别本身不发送输入，带框截图可按设置保存到 `user_data/debug/` |
| 单步运行 | 调试页顶部的开关仅本次运行有效、不存盘。开启后主界面显示「上一步 / 下一步」；每次下一步执行一个动作，上一步只回退指针并还原光标位置，不重放动作 |
| 开发者调试 | 设置页可勾选「开发者调试」，顶部出现调试页：窗口诊断、布局测量、**图片识别匹配测试（放在页面最前：模板列表 + 阈值 + 最多列出 → 给出命中坐标）**、干跑开关、**还原光标开关（点击/滑动后是否把真实鼠标移回原位）**、鼠标单点/连点（都带「点击时长」）、屏幕滑动、键盘输入等带参数的测试按钮（复用同一输入通道与安全规则） |
| 安全底线 | `dry_run` 默认关闭；真实模式默认每次启动确认，支持 F8 急停，点击和滑动不得越出客户区。干跑可在开发者调试页启用；不上传本地数据，不收集账号、密码或 token |
| 日常任务页 | 总开关与循环设置、建筑岛屿编号、参考图和制造选项保存到配置；循环间隔界面为分钟、配置为秒，装载不回写。参考图每组最多 10 张，选择图片替换整批，框选截图追加；支持缩略图预览、移除和清空。移除前确认，仅删除工具管理目录中未被其他建筑引用的文件。制造选项只读；自动找建筑和真实日常操作尚未实现 |
| 任务编排 | 日常任务总开关与任务自身开关共同决定入队，按 `order` 与任务 ID 排序；之后依次执行启用的 `order_hold`、`feature_3`、`feature_4`。失败计数与循环作用于整队列，两个预留开关不参与编排；总开关关闭但有任务勾选时提示 |
| 框选弹窗 | 选区内拖动移动，八个手柄改大小，选区外重新框选；Alt 对称缩放，空格/右键移动，方向键按图像像素微调。滚轮和滑条缩放，中键平移，双击滑条 1:1 显示，重置恢复视图并清空选区与试识别结论。保存仅裁剪选区，纯色拒存、低辨识度只提示；「在本图试识别」按当前阈值做同图 1:1 匹配，展示除自身外的重复位置，不能保证正式识别不误匹配 |

## 7. 构建与发布

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
- **GUI 子系统（`console=False`）**：双击 exe **不会出现 cmd 黑窗口**。
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
5. 双击 `LuoLuoTool.exe` 打开 GUI：检查各页签可切换、日志面板有输出；
6. 改一个设置（例如勾选"开发者调试"）→ 点「保存」→ 关闭程序再启动，确认设置被记住
   （文件位置：`user_data\config.json`）；
7. 点「窗口诊断」应能查找游戏窗口并截图到 `user_data\debug\`（需游戏已启动且本工具已提权）。

> 构建产物未提供代码签名，首次运行可能出现 SmartScreen 提示；当前构建方式为 one-dir，分发时保留完整目录。

## 8. 风险声明（必须阅读）

本工具通过模拟键鼠操作自动化游戏日常，**可能违反游戏用户协议，存在封号风险**，
且坐标/图像自动化在不同分辨率、窗口位置下可能失效。本文件夹要求：

- 仅用于**个人学习与自用**，不发布、不售卖、不用于多开打金；
- 全程 **干跑模式（dry-run）** 优先，真实输入阶段必须保留急停热键；
- 不读取/修改游戏内存，不拦截网络封包（见 `PROJECT_SPEC.md`「项目边界与安全」）；
- 不收集账号、密码、token、设备指纹；联网功能不得上传日志/配置/截图等本地数据；
- 驱动级 / 注入类 / 过检测类 / 用户态合成输入方案：必须**逐项授权**并声明风险（可能导致游戏无法启动、需改测试签名/Secure Boot、光标被短暂移动、封号概率上升），详见 `PROJECT_SPEC.md`「项目边界与安全」。

以上红线同时写入 `PROJECT_SPEC.md` 与 `AGENTS.md`，AI 必须在所有阶段遵守。
