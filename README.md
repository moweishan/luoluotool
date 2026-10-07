# LuoLuoTool

LuoLuoTool 是一个面向 Windows 的《桃源深处有人家》桌面工具。它可以配置任务、识别游戏画面中的图片，并通过真实鼠标和键盘发送输入。

**它还没有实现自动完成种地、收菜或卡订单的完整游戏流程。** 当前有一个通用的占位任务，可按配置执行点击、拖动和按键；卡订单、功能三、功能四仍是占位功能。

> **运行前请了解：**真实模式会移动鼠标、操作键盘并把游戏窗口切到前台，可能误操作，也可能违反游戏规则。启动真实模式前会弹出确认框；运行中可按默认急停键 **F8** 或点击「停止」。请只在自己理解风险的情况下使用，并先小范围验证。

## 功能现状

| 已有功能 | 说明 |
|---|---|
| Windows 图形界面 | 设置、日常任务、卡订单、功能三、功能四、关于；开发者调试页可在设置中开启 |
| 通用任务执行 | 占位任务可按配置执行客户区坐标点击、鼠标拖动和按键；支持急停、单步调试和干跑 |
| 图像识别 | 在当前游戏窗口中按模板查找目标；支持多张模板、多处匹配和多尺度搜索。识别本身不会发送输入 |
| 日常任务配置 | 可设置循环、岛屿编号及参考图片；这些配置目前还没有接入自动找建筑和具体日常操作 |
| 本地配置 | JSON 配置、版本迁移、输入校验和原子保存；当前 schema 为 v11 |
| 打包 | 提供 PyInstaller one-dir 构建脚本，产物位于 `dist\LuoLuoTool\` |

**还没有实现：**按识别底图进行离线匹配、自动找鸡舍/土地/水产养殖、自动种地或收菜、卡订单与功能三/四的实际任务逻辑、远程配置更新。产物制造开关目前只保存设置，不会执行制造。

## 运行要求

- Windows 10 或 11，x64。
- 源码运行需要 Python 3.11 或更新版本。
- 实际操作时，游戏需处于窗口模式且不能最小化。项目目前按单显示器、Windows 缩放 100% 使用。
- 如果游戏以管理员权限运行，工具也需要相同权限才能可靠地激活窗口和发送输入。

## 从源码启动

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m luoluotool
```

首次启动会在 `user_data\config.json` 创建本地配置。源码运行日志写入 `logs\`。

### 使用前的输入模式

配置出厂默认 `automation.dry_run` 为 `false`，也就是真实模式。启动任务时，确认框会说明真实输入的影响；选「否」不会启动。

想先查看日志而不操作鼠标键盘：在「设置」中打开「开发者调试」，进入该页勾选「干跑模式」。干跑模式不产生真实输入。开发者调试页未开启时，其中的选项和测试按钮不会生效。

## 命令行

在项目目录运行以下命令：

```powershell
.\.venv\Scripts\python.exe -m luoluotool --version
.\.venv\Scripts\python.exe -m luoluotool --validate-config
# 离屏创建窗口后退出，不会打开可交互窗口
.\.venv\Scripts\python.exe -m luoluotool --smoke-gui
.\.venv\Scripts\python.exe -m luoluotool --measure-layout
```

识别命令会读取当前游戏窗口画面，不会点击或发送按键：

```powershell
.\.venv\Scripts\python.exe -m luoluotool --recognize .\assets\templates\鸡舍_白天.png --threshold 0.85 --max-results 20
```

可给 `--recognize` 传入多张图片。常用选项：

| 参数 | 用途 |
|---|---|
| `--config PATH` | 指定配置文件；用于配置校验、布局测量、识别或 GUI 启动 |
| `--threshold 0.85` | 设置识别阈值，范围大于 0 且不超过 1 |
| `--max-results 20` | 限制列出的匹配位置数量 |
| `--no-annotate` | 不保存识别结果的标注截图 |
| `--no-scale` | 关闭多尺度搜索，只按模板原始尺寸匹配 |

## 图片和数据放在哪里

| 路径 | 用途 |
|---|---|
| `user_data\config.json` | 当前配置；本地文件，不要提交到仓库 |
| `logs\` | 程序日志 |
| `assets\templates\` | 自行整理的识别图片；项目约定将这些图片纳入版本库 |
| `assets\anchors\` | 在工具中框选生成的模板；个人素材，不纳入版本库 |
| `assets\screenshots\` | 识别底图；用底图进行离线匹配尚未实现 |
| `user_data\debug\` | 诊断截图及识别标注截图 |

配置与日志保存在本机。当前版本没有网络请求代码；未来远程配置更新仍是计划项，尚未实现。程序不会上传配置、日志或截图，也没有通知或推送功能。

## 构建 Windows 目录版

项目提供一键构建脚本：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

默认会安装开发依赖、运行测试与配置/布局检查，再构建 one-dir 目录。构建完成后，运行 `dist\LuoLuoTool\LuoLuoTool.exe`；分发或复制时需要保留整个 `dist\LuoLuoTool\` 目录，不能只拿 exe。

## 项目文档

- [项目规格与边界](PROJECT_SPEC.md)
- [开发规范](AGENTS.md)
- [阶段提示词](PHASE_PROMPTS.md)
- [工程手册](PROJECT_HANDBOOK.md)
- [验收清单](CHECKLIST.md)
- [问题排查指南](BUG_HUNT_GUIDE.md)

## 风险与许可

模拟键鼠可能违反游戏服务条款，也可能因画面变化造成误操作。使用者应自行评估风险；工具不会读取或修改游戏内存，也不会拦截或伪造网络封包。

仓库没有附带 `LICENSE` 文件，因此不应把它当作可自由再发布的软件。第三方依赖及许可信息可在程序「关于」页查看。
