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
- 主开关：启用/禁用；开启后 `order_hold` 任务进入运行队列（Phase 6，当前任务内容仅为占位日志）。
- 预留开关 ×2：`reserved_switch_1`、`reserved_switch_2`，**现在无任何实际行为**，只落库、只显示、只在配置中占位。
- 后续若明确语义，在**不改动配置结构**的前提下填充逻辑（新增字段必须走 schema_version 迁移）。

### 功能三 / 功能四：预留配置页
- 各有一个页签，页内一个「启用」开关 + 说明文字「功能规划中」；开关开启后 `feature_3` / `feature_4` 任务进入运行队列（Phase 6，内容仅为占位日志）。
- 页签、开关、配置项从 Phase 2 起就存在，便于后续扩展。

### 任务编排规则（Phase 6，2026-09-19 定案）
运行队列由两个来源合并而成，**统一顺序执行、统一失败计数**：

1. **日常任务组**：`features.daily_tasks.tasks[id].enabled == true` 的任务入队，按 `order` 升序；
   同一 `order` 时按任务 ID 字典序（保证每次运行顺序完全一致）。
2. **单功能组**：功能主开关开启即入队，顺序固定为 **卡订单（`order_hold`）→ 功能三（`feature_3`）→ 功能四（`feature_4`）**。
3. 最终顺序 = 日常任务组（按上述排序）→ 单功能组（固定顺序）；启动时写一条
   `任务队列（N 个）：a → b → c` 的 INFO 日志便于核对。
4. 失败计数对整队列生效：任一任务失败累加、任一任务成功清零，连续失败达到
   `automation.max_consecutive_failures` 即自动停止。
5. 循环：`features.daily_tasks.loop` 对**整队列**生效（开关 + 间隔秒数）；队列为空时不执行任何任务并立即结束。
6. **不参与编排**的开关（保持「存/读/显示」语义）：`features.daily_tasks.enabled`（启用日常任务）与
   `order_hold.reserved_switch_1/2`（预留开关）——有测试断言它们不影响运行任务集合。

### 占位任务边界（Phase 6）
`order_hold` / `feature_3` / `feature_4` 三个任务**只允许**：进入时输出
「该功能尚未实现真实逻辑（规划中）」日志 + 每轮一条心跳日志 + 响应停止请求；
**不产生任何输入、不读取 params、不包含任何推测性业务逻辑**（有测试守卫：零输入且只写两条日志）。

### 非功能需求
- UI 全程不冻结：任务在后台工作线程执行。
- 默认**真实模式**（`dry_run: false`，2026-09-19 用户要求改为默认不开启干跑）：启动自动化前必须弹出确认框如实告知副作用；勾选「开发者调试」→ 调试页里的干跑开关可切回"只模拟、零输入"。
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
7. **真实模式必须由用户显式触发**：启动前需用户确认（询问频率可配置，默认每次询问）；F8 急停始终可用。〔原"禁止绕过确认"的绝对禁令已按用户要求改为可配置〕
   〔2026-09-19 更新：`dry_run` 出厂默认由 `true` 改为 `false`（用户要求），用户确认弹窗因此成为每次启动的固定兜底〕
8. **禁止**在无游戏窗口、或窗口最小化/不可见时执行输入注入（真实键鼠通道会在每次输入前自行置顶/置前，故原 `pause_on_window_focus_loss` 开关已随 v5 精简移除）。〔用户 2026-09-15 曾要求取消 → **未执行**，见 §4.2〕

### 4.1 已取消的限制（2026-09-15，按用户要求执行）

| 原条款 | 原位置 | 现状 |
|---|---|---|
| 禁止 DLL 注入 / 钩子注入 / 驱动级操作 | 本文件原 §4 第 2 条 | **已取消** |
| 禁止内置"过检测"技巧 | 本文件原 §4 第 8 条 | **已取消** |
| 禁止绕过 ACE 反作弊检测（过检测，实例级重申） | 本节 §4.1.1 ④（2026-09-15 当日新增的"未授权"写法） | **已取消**（用户 2026-09-15 明确指示「取消禁止过检测该限制」，据此撤销该写法，见 §4.1.1） |
| 禁止 DLL 注入 / 驱动 / 过检测（重复表述） | `AGENTS.md` 原 §3 红线 1 | **已取消** |
| **禁止用户态合成输入**（`SendInput` / `SetCursorPos` / `mouse_event`） | `AGENTS.md` §1.6、§2；本文件 §5；`PHASE_PROMPTS.md` Phase 5 | **已取消** |
| **禁止任何联网代码** | 本文件原 §4 第 5 条；`AGENTS.md` 原 §3 红线 2 | **已取消**（数据保护约束保留） |
| **禁止绕过「真实模式确认」** | 本文件原 §4 第 7 条；`AGENTS.md` 红线 3 | **改为可配置**（默认每次询问，不再作为绝对禁令） |

取消后**仍然必须遵守**的约束：

- **逐项授权**：驱动级 / 注入类 / 过检测类 / 联网功能，必须先写入对应阶段的「本次只做什么」并取得用户明确确认，**禁止静默引入**；
- **可回退**：必须保证「不安装驱动、不做注入」的基础模式仍可独立运行；
- **数据保护**：不得上传或传输日志、配置、截图等本地数据；不得收集账号/密码/token；
- **安全兜底**：F8 急停可中断；合成输入前校验目标窗口在前台、动作后还原真实光标（可配置）；**点击坐标必须落在游戏窗口客户区内，越界不点击**（2026-09-19）；每次注入写日志；
  （`dry_run` 自 2026-09-19 起出厂默认 `false`：首次启动即真实模式，但启动前有强制确认弹窗 + F8 急停兜底）
- **风险声明**：README 与 GUI「关于」页必须如实声明 `§4.3` 中的风险。

#### 4.1.1 用户逐项授权记录（2026-09-15）

针对目标游戏（Unity **IL2CPP** + 腾讯 **ACE** 反作弊 + WeGame 启动，安装于 `D:\WeGameApps\rail_apps\桃源深处有人家(2002519)`），用户明确授权如下（原文：「允许dll注入游戏进程 先进行dll注入 无法实现或者实现有困难的情况下 再修改游戏进程内存/代码 明确接受：游戏无法启动 / WeGame 账号封禁 / 与 ACE 对抗的后果」）：

| 项 | 授权状态 | 说明 |
|---|---|---|
| ① DLL 注入游戏进程 | **已授权** | 允许在游戏进程内加载 DLL，作为可行性实验与后续机制载体 |
| ② 修改游戏进程内存 / 代码 | **条件授权** | 仅在 ① 不可实现或实现明显困难时启用（例如在进程内挂钩 `GetCursorPos` 等 API） |
| ③ 接受后果 | **已确认** | 明确接受「游戏无法启动 / WeGame 账号封禁 / 与 ACE 反作弊对抗」的后果 |
| ④ 绕过 ACE 反作弊检测（"过检测"） | **已授权（限制已取消）** | 2026-09-15 用户明确指示「取消禁止过检测该限制」，据此撤销本节原先"按未授权处理"的写法；实施时仍须逐项授权 + 风险声明（见下） |

**据此产生的硬约束（工程负责人执行）**：

- 只做**目标所需的最小动作**：注入阶段只加载 DLL、不挂钩、不改游戏代码；除注入本身必需的参数写入外不做任何内存/代码改动；
- **过检测类手段**：限制已按用户要求取消（`§4.1` 表格），但仍属"须逐项授权、须写风险声明、须可回退、禁止静默引入"的范畴；
- **工程负责人保留的风险说明（不构成拒绝执行的理由，但必须如实记录）**：过检测 = 主动对抗内核级反作弊（ACE），后果概率显著高于其它方案：游戏立刻退出/拒绝启动、WeGame 账号冻结或封禁、可能影响同机其它使用 ACE 的游戏；且属游戏用户协议明令禁止的行为。实施前须先完成逐项授权并把风险写入 `§4.3`；
- 每次实验前告知用户当前风险状态，实验后可回退（卸载 DLL / 重启游戏）；
- 因本路线**不解决新问题**（点击坐标问题已由 Phase 5.2 对齐窗口通道解决），任何进一步投入必须先说明收益，不得静默推进。

#### 4.1.2 注入路线实测结果（2026-09-15，用户启动游戏后当场实测）

按 §4.1.1 授权执行「最小动作」实验（注入一份微软签名 `version.dll` 副本；不挂钩、不改游戏代码、不做任何反检测；结果日志：`D:\deepSeekHarness\.tmp\inject_result.log`）：

| 检查项 | 结果 |
|---|---|
| ① `OpenProcess`（注入全套权限，提权后） | 成功（0x1D4） |
| ② `VirtualAllocEx`（远程分配） | **被拒，错误码 5（拒绝访问）** |
| ③ `CreateRemoteThread(LoadLibraryW)` | 未执行（②已失败；按"最小动作、不重复尝试"原则未重试） |
| 旁证 A：`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` | 成功，但 `EnumProcessModules` 失败、模块字节数 = 0（读权限被剥夺） |
| 旁证 B：`OpenProcess(PROCESS_VM_READ)` | **失败，错误码 5** |
| 对游戏的影响 | 实验后游戏进程存活、`Responding=True`；注入未成功，无残留模块 |
| 本机工具链 | **无原生编译器**（`cl`/`gcc`/`clang`/`zig` 均未安装） |

**结论（工程负责人判定）**：

1. ACE 通过内核回调实施「**授予句柄但剥夺敏感权限**」保护：`PROCESS_VM_READ` / `PROCESS_VM_OPERATION` 无法获得 → **经典 DLL 注入不可行**（在 `VirtualAllocEx` 即被拒）；
2. 授权中的第②项「修改游戏进程内存/代码」**同样不可行**——`WriteProcessMemory` / `VirtualProtectEx` 与 `VirtualAllocEx` 属同一权限面，而这是所有 hook 方案（IAT / inline hook）的必要条件；
3. 即使换用「由系统中介加载 DLL」的注入变体（如 `SetWindowsHookEx`），本机也没有原生编译器来构造导出 `GetMsgProc` 的 DLL；
4. 唯一能让该路线复活的手段是**绕过/对抗 ACE 反作弊检测（过检测）**——该限制已按用户 2026-09-15 指示**取消**（见 §4.1.1 ④），但启用前仍须逐项授权、写明风险，并补足下列前提：① 本机安装原生编译器（构造导出 `GetMsgProc`/hook 的 DLL）；② 定位 IL2CPP 目标（`global-metadata.dat` 解析 + `GameAssembly.dll`/`UnityPlayer.dll` 符号），这是数百万行级别原生码的逆向工作量，且每次游戏更新需重做；
5. 因此**本次注入路线终止**：判定依据是「**在不启用过检测的前提下**，ACE 的系统层保护已使注入与内存改写不可行，且该路线不解决任何未解决问题」。若用户日后明确授权启用过检测，本结论需重新评估（并重新执行 §4.1.1 的逐项授权流程）。点击坐标问题继续由 **Phase 5.2 对齐窗口通道**（实测达标：点准 + 真实光标不动 + 指针不消失 + 零注入）解决。

### 4.2 用户要求取消、工程负责人未执行的三项（附理由与替代方案）

| 用户要求取消 | 未执行理由 | 替代方案 |
|---|---|---|
| 禁止读写游戏进程内存 | 读写**在线游戏进程内存**属于外挂类改造（可篡改数值、复制物品），影响同服其他玩家与游戏服务本身，并可能触发反作弊与法律风险；本项目定位为个人 UI 自动化，不实现该类能力。 | **截图 + 图像识别（OpenCV 锚点匹配）** 读取界面状态与坐标——已在 §4「边界内但暂缓」中，能力可覆盖绝大多数"识别状态/找按钮"需求 |
| 禁止拦截/伪造/重放网络封包 | 直接篡改客户端与服务器之间的协议数据，属于对在线服务的攻击性改造，影响范围超出个人账号。 | 同上（图像识别 + UI 自动化）；"防掉线"类需求用 UI 层动作（点击/切页）实现 |
| 禁止多开批量打金 / 工作室加速设计 | 账号矩阵与批量打金属规模化作弊用途，与"个人自用"定位及游戏协议冲突。 | 保持单实例、单账号的个人自动化定位 |
| （无窗口/失焦盲点、真实模式确认） | 这两条保护**用户本机安全**：无窗口或失焦时按坐标注入会点到桌面上任意窗口（文件对话框、网银页面等）。 | 询问频率改为可配置（默认每次）；"无窗口/最小化不执行"作为硬保护保留；真实键鼠通道每次输入前会把窗口置顶/置前并回读复核 |

> 上述三项若用户坚持要求，请在对话中明确指示；工程负责人会在文档与提交说明中记录风险后再评估。

### 4.2.1 合成指针通道（Phase 5.1）：已实现后撤回（2026-09-15）

**结论**：用户态合成触摸/笔注入（`CreateSyntheticPointerDevice` + `InjectSyntheticPointerInput`）在目标游戏中**点得准、且不移动真实光标**，但会被 Windows 判定为触摸输入并**抑制真实光标**（`GetCursorInfo` 的 `CURSOR_SHOWING` 变 0），只有真实鼠标硬件输入才恢复——即用户观察到的"每点一次指针消失一下"。因此「点得准 + 光标不动」与「指针不被系统隐藏」在该通道上**不可兼得**，已按用户要求撤回代码（实现保留在历史提交 `b145ca5`，若日后找到可行方案可直接拾取）。

**实测排除清单（本机 Windows 10/11 + 目标游戏）**：

- **全部触发抑制的注入变体**：现代 API 与旧版 `InitializeTouchInjection`、`PT_TOUCH`/`PT_PEN`、反馈模式 `DEFAULT`/`INDIRECT`/`NONE`、`UP` 带/不带 `INCONTACT`、`UP` 带 `CANCELED`、`DOWN` 带/不带 `PRIMARY`、`hwndTarget` 指定/置 0；与目标窗口类光标（ARROW/NULL）无关，也不是游戏自身行为。
- **全部无效的恢复手段**：`SetCursorPos`（同位置）、`ShowCursor(TRUE)`、`SetCursor(IDC_ARROW)`、`WM_SETCURSOR`、`SendInput` 绝对定位到原位、`mouse_event`、`AttachThreadInput` 附加到光标属主线程后 `SetCursor`；抑制不会自行解除（>3.5 s 仍隐藏）。
- **部分有效但不可靠**：`SendInput` 相对移动 ±2~3px（净位移 0）。随机交错 A/B：接触期间+结束后轻推 4/6 vs 对照 0/6；做成生产形态的"`GetCursorInfo` 校验重试最多 6 次"后仅 **2/12（17%）**，不可作为方案。
- **外部佐证**：社区确认注册表策略 `EnableCursorSurpression=0` 无效，标准答复是改用 `SendInput`（即必须移动真实光标）。

> 后续若采用替代方案，验收必须**同时**满足：① 点击落点在游戏内正确；② 真实光标既不消失、也不被移动。

> **后续进展（2026-09-15 同日）**：该验收条件曾由 **Phase 5.2「对齐窗口点击通道」** 满足（移动游戏窗口把目标坐标搬到静止光标下方再点击，实测「目标点正确响应、真实光标未移动、指针未消失」）。**2026-09-16 用户改用「真实鼠标键盘」方案并指示删除其它实现方式，该通道连同 `automation/window_align.py` 已整体删除**（实现保留在 git 历史 `90752fe`/`5cf6710`）。

### 4.2.2 工程负责人不执行：对抗/绕过 ACE 反作弊（"过检测"，2026-09-15）

**用户指示**：在逐项授权 DLL 注入、并取消「禁止过检测」限制之后，要求「继续推进过检测路线」。

**不执行的理由**（与 §4.2 三项同类：不属于"用户风险自负"即可覆盖的范畴）：

1. **性质不同**：这不是"自动化我自己的游戏操作"，而是**攻击/削弱正在保护本机的安全组件**——实测已确认 ACE 以内核回调剥夺我们进程句柄的 `PROCESS_VM_READ`/`PROCESS_VM_OPERATION`。一旦具备该能力，其用途不限于本项目目标，属于反作弊对抗工具的开发；
2. **现实路径全部是病毒级手法**：突破内核回调只剩 BYOVD（滥用有漏洞的签名驱动）、自签内核驱动、或 hypervisor 级对抗；这些会被 Windows 自身的**易受攻击驱动黑名单 / Defender** 拦截，可能损坏系统、破坏其它软件，并牵连同机其它使用 ACE 的游戏与账号；
3. **零收益**：ACE **并不拦我们真正需要的能力**——Phase 5.2 的对齐窗口点击与窗口消息点击，是在游戏**带着 ACE 运行**时实测通过的（判定矩阵 V6/V7 为 `y`）。"过检测"只服务于注入/hook 路线，而该路线**不带来任何新能力**；
4. **军备竞赛**：即使某次绕过成功，也会随 ACE 更新失效；对手是专业安全团队，而收益为零、代价外溢到整机与其它账号。

**替代方案（已可用或可继续推进，均不触碰反作弊）**：

- 最大化窗口支持（`ShowWindow(SW_RESTORE)` → 对齐 → 点击 → 恢复最大化）——待用户指定后实施；
- 截图 + 图像识别读懂界面状态（§4.2 已承诺的替代方案，零注入、零内存操作）；
- 键盘类交互由真实键鼠通道的 `key_tap`（SendInput 扫描码）承担；如需零侵入只能人工操作。

**边界**：用户在自己机器上以"理解原理"为目的的独立研究属其自由；工程负责人**不提供绕过步骤、不编写相关代码**，也不将该能力并入本项目。

### 4.2.3 真实鼠标键盘通道（Phase 5.3，2026-09-16 用户选定）

用户明确指示改用「直接移动真实鼠标 + 模拟真实键盘」的方案，并提出硬规则：**每一次鼠标点击与键盘输入之前都必须校验游戏窗口是否在最顶层，不在最顶层时将窗口置于最顶层再输入或点击**。

实现（`automation/real_input.py` + `RealInputSender`）：

| 要求 | 落实方式 |
|---|---|
| 每次输入前校验是否在最顶层 | `real_input.ensure_window_front()` 在**每一次** `click_at()`/`key_tap()` 前调用（有测试断言调用次数） |
| 不在最顶层则置顶 | `SetWindowPos(HWND_TOPMOST)`（`SWP_NOSIZE|SWP_NOMOVE|SWP_SHOWWINDOW|SWP_NOACTIVATE`） |
| 键盘必须落在游戏窗口 | 置顶之外再 `SetForegroundWindow`（前台锁定失败时用 `AttachThreadInput` 兜底），并**回读 `GetForegroundWindow` 复核** |
| 无法确保在最前 | **绝不输入**：返回 `FrontResult.ok=False` → 抛可读错误拒绝本次输入 |
| 点击/滑动必须在窗口内（2026-09-19） | 点击前用 `input_sender.point_in_client_area(hwnd, x, y)` 校验客户区 `[0,w)×[0,h)`；**滑动（drag）的起点与终点同样校验**（`check_points_in_bounds`，任一端越界整段跳过）。越界一律**不输入**，只写 WARNING「点击坐标 (x, y) 不在游戏窗口内（客户区 WxH），已跳过本次点击」／「滑动起点 (x, y)、终点 (x, y) 不在游戏窗口内（…），已跳过本次滑动」；读不到客户区（窗口已关闭/权限不足）同样按越界处理。干跑通道用 `DryRunSender(bounds=...)` 做同样校验（干跑时若查不到窗口则跳过校验并写 INFO） |
| 最小化窗口 | 上层直接**拒绝输入**（`is_window_ready` 判定最小化/不可见即抛错）；`ensure_window_front` 内部的 `ShowWindow(SW_RESTORE)` 仅作为兜底路径 |
| 输入后收拾现场 | 取消**本次由我们设置的**置顶（避免游戏窗口长期浮在最上层）；点击后按 `restore_cursor_after_click` 把真实光标移回原位，滑动结束**同样还原**但先延迟 `DRAG_RESTORE_DELAY_SECONDS` 再分帧小步移回（见下方修复记录） |
| 注入面收敛 | `SendInput`/`SetCursorPos` 只允许出现在 `real_input.py`（有跨模块守卫测试） |

**规格收敛（2026-09-16）**：用户确定**只保留这一种输入实现方式**，因此其它通道（窗口消息、合成指针、对齐窗口）与选择它们的 `automation.input_mode` 枚举、以及与本通道冲突的 `pause_on_window_focus_loss` 开关**已全部删除**（schema v5）。**代价（用户已知情并选择）**：输入期间会**抢前台**，因此运行时不宜同时操作其它软件。

**滑动（拖拽）修复记录（2026-09-19，用户实测「滑动结束后游戏画面乱飘」）**：三处成因一并修复——① 轨迹由匀速改为**缓出曲线 + 末尾在终点保持静止数帧**（`build_drag_path`：`interpolate_points(..., easing=ease_out_quad)` 缓出采样 + `DRAG_TAIL_HOLD_STEPS` 帧静止），因为"匀速甩到底立刻松手"会被引擎判定为 flick（快速甩动），松手后画面带惯性继续飘；② 松手后**回读 `GetAsyncKeyState(VK_LBUTTON)` 复查左键是否真的抬起**，未抬起则补发抬起（并记 ERROR），仍失败则抛可读错误提示用户手动点击左键；③ **滑动结束后同样按 `restore_cursor_after_click` 还原光标，但方式改为"延迟 + 分帧小步"**：先等 `DRAG_RESTORE_DELAY_SECONDS`（0.25 s，让引擎处理完"抬起"），再用 `restore_cursor_smooth` 分 8 步小步移回（禁止一次 `SetCursorPos` 跳回——跳跃会被残留的拖拽状态算成巨大位移而让画面乱飘；等待被中断时仍要继续还原）。**该条为 2026-09-19 用户实测反馈后的二次修正**：首版修复曾把滑动完全排除在该设置之外，导致用户勾选「移回原位置」后滑动仍停在终点。附带加固：滑动前先清理可能残留的左键按下状态；松手动作放在 `finally` 且**对等待函数抛异常也生效**（"必定松手"是安全属性，有回归测试）。

### 4.3 已确认的风险（用户已知悉，后果自负）

1. **反作弊可能直接拦截**：内核级输入驱动会被反作弊识别，可能导致游戏**无法启动**（例如出现 “Please Close Interception Before Starting the Game”），需卸载驱动并重启才能恢复；
2. **系统级改动**：驱动安装通常需要管理员 + 测试签名模式 / 关闭 Secure Boot + 重启，可能影响整机输入与其它反作弊游戏；
3. **注入可被识别**：用户态合成输入带 `LLMHF_INJECTED` 标记；驱动级注入同样可能被检测；
4. **真实光标会被移动**：用户态合成输入需要移动真实光标（本项目要求点击后立即还原，可配置）；
5. **封号概率显著上升**：上述方案一旦被判定违规，后果由用户自行承担（「个人自用、风险自负」）。
6. **注入 ACE 保护进程（2026-09-15 起，用户已逐项授权，见 §4.1.1）**：目标游戏经腾讯 **ACE**（安装目录 `AntiCheatExpert`）加固并以管理员运行，注入/挂钩/内存改动正是 ACE 的核心检测目标；后果包括**游戏立刻退出或拒绝启动、WeGame 账号冻结/封禁**，且该游戏的反编译成本与维护成本极高（**IL2CPP**：`GameAssembly.dll` + `il2cpp_data/Metadata`，无托管程序集，只能汇编级逆向，每次更新需重新定位）。工程负责人评估结论：**该路线不解决任何未解决问题**（点击坐标已由 Phase 5.2 解决），属于纯风险投入。**实测后已终止**：ACE 剥夺 `PROCESS_VM_READ`/`PROCESS_VM_OPERATION`，注入与内存改写均被系统层拦截（详见 §4.1.2）。该终止判定以「**不启用过检测**」为前提；过检测限制已按用户要求取消（§4.1、§4.1.1 ④），若日后启用须重新评估并逐项授权。

### 边界内但暂缓（不在 MVP）
- ~~图像识别（OpenCV 锚点匹配）~~ → **已于 2026-09-19 引入**：给模板图，在当前游戏窗口客户区里做模板匹配，返回命中位置的**客户区坐标**（中心/左上/尺寸/匹配度）。实现见 `automation/vision.py`（匹配纯函数 + 截图转数组）与 `core/vision.py`（找窗口→校验→截图→匹配→结果），入口：调试页「图片识别匹配测试」与命令行 `--recognize`。**2026-09-20 扩展（用户要求）**：① **多张模板打同一块区域**——多张图按顺序尝试，第一张达到阈值的直接用它的结果（多张共用同一张截图，读不出的跳过）；② **一张图匹配屏幕多个区域**——同一张图命中多处时全部列出（`matches[0]` 为默认使用值），条数由 `max_results` 封顶。识别参数（模板列表/阈值）**暂不落配置**（保持 schema v9，模板由调试页每次选择），接入任务（按图点击）待用户确认后再做。
- 多显示器、多分辨率适配：MVP 只保证 100% 缩放、单显示器、窗口化游戏。
- 配置导入/导出、多套方案（profile）管理：后期可选。

## 5. 风险与安全边界（必须写进 GUI 和文档）

- **封号风险**：自动化操作可能违反游戏用户协议。程序「关于」页与 README 必须声明「个人学习自用，风险自负」。
- **误操作风险**：真实模式下程序用系统级输入注入（真实移动鼠标 + 模拟真实按键）操作游戏窗口，并在**每次输入前把游戏窗口置顶/置前**（会抢前台）；误定位或游戏状态变化时可能产生非预期操作，必须有急停热键 + 状态栏醒目标识（如「运行中 · 真实模式」红色提示）。
- **输入实现方式（2026-09-16 定案）**：**只有一种**——真实鼠标键盘（`SendInput`，见 §4.2.3）。窗口消息、合成指针、对齐窗口三种实现已按用户指示删除；驱动级注入等其他方案须逐项授权（见 §4.1）并遵守"安全兜底"。
- **输入方式限制（已知风险，历史记录）**：本作忽略窗口消息坐标（后台消息/同步投递/`WM_POINTER`/抢前台均实测无反应），只认真实光标位置——这正是改用真实键鼠的原因；相关排查结论见本要点与 §4.2.1。
- **合成指针会隐藏真实光标（2026-09-15 实测）**：触摸/笔注入会被系统判定为触摸输入并抑制真实光标，无法用 API 关闭或可靠恢复（详见 §4.2.1）；该通道已删除。真实键鼠通道不会隐藏指针，但会移动真实光标（点击后按配置还原）。
- **本作按真实光标位置取点（2026-09-15 实测，2026-09-16 定案）**：目标游戏（Unity 播放器）**忽略窗口消息里的坐标**（含 `WM_POINTER`），只按真实光标位置决定落点（`实测：客户区坐标消息/同步投递/WM_POINTER/抢前台全部无反应`）。因此用户选定「**真实移动鼠标 + 模拟真实键盘**」为唯一实现方式（见 §4.2.3）：点击时真实光标会移动到目标点、点击后按 `restore_cursor_after_click` 还原；**每次点击/按键前**校验并置顶/置前游戏窗口，无法确保时绝不输入。代价：输入期间抢前台、且会短暂占用真实鼠标。
- **本机安全兜底（不得删除）**：无游戏窗口或窗口最小化/不可见时**不得注入**；每次注入前必须校验并确保目标窗口在最顶层/前台，**无法确保时绝不输入**（避免点到/敲到别的窗口）；全部输入写日志；急停热键随时可中断；点击后按配置还原真实光标。
- **政策变更带来的风险（2026-09-15）**：原禁止「DLL 注入 / 驱动级操作 / 过检测技巧 / 用户态合成输入 / 联网」的条款已按用户要求取消（见 §4.1）；未执行的三项见 §4.2。采用此类方案前必须完成逐项授权与风险声明；当前实现的真实键鼠通道是风险最低的可行手段，驱动级方案风险更高，须逐项授权。
- **数据保护（用户明确保留）**：不得收集或存储账号、密码、token、设备指纹；联网功能不得上传日志、配置、截图等本地数据。
- **合规**：本工具不针对未成年人防沉迷机制做任何规避；不得商业化分发。

## 6. 推荐技术栈（选定后不得随意更换）

| 领域 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+（推荐 3.11/3.12，x64） | Windows 生态成熟，开发速度快 |
| GUI | **PySide6**（Qt for Python） | 原生渲染快、QSS 可做出简洁大气的主题、QThread 成熟、LGPL 允许闭源分发（动态链接） |
| 配置 | 标准库 JSON + dataclass + 手写 schema 校验 | 无数据库需求；避免 pydantic 增大 exe 体积 |
| 日志 | 标准库 logging + RotatingFileHandler | 零依赖 |
| 输入模拟 | **真实鼠标键盘（`SendInput`，唯一实现方式，Phase 5.3）**：`automation/real_input.py` 负责注入原语与「输入前置顶校验」（鼠标：移动、点击、**分帧滑动的拖拽**；键盘：单键、组合键、长按），`RealInputSender` 负责流程，`utils/keys.py` 提供键名表与组合键解析（config 与 GUI 共用）；干跑仍为 `DryRunSender`（零输入）。其它通道（窗口消息、合成指针、对齐窗口）已按用户指示删除 | ① 窗口消息零侵入，但本作忽略消息坐标；② **对齐窗口能在不移动真实光标、不隐藏指针的前提下点准本作**，代价是每次点击游戏窗口短暂位移（点完还原）且需窗口化；③ 合成输入需移动光标，触摸注入会隐藏指针（见 §4.2.1）；④ 驱动级风险最高（反作弊/系统改动） |
| 窗口查找/截图 | pywin32（win32gui / win32ui）；`automation/real_input.py` 负责置顶/置前与注入原语 | 成熟；后续可用截图做锚点匹配 |
| 图像识别 | **OpenCV 模板匹配（`opencv-python-headless` + `numpy`，2026-09-19 启用）**：`automation/vision.py` 负责「取景→匹配→客户区坐标」，`core/vision.py` 负责「找窗口→就绪校验→取景→匹配→结果」；入口＝调试页「图片识别匹配测试」（模板**列表**可放多张；「框选截图生成模板」生成后自动加入列表，**只保存手动框选的那块区域**（裁剪落盘；没框选就不写文件也不关窗口；选区 ≥95% 整屏时提示"几乎等于整屏"）；「最多列出」控制条数；「识别成功时保存带框截图」为该页开关，受 `automation.save_vision_annotations` 控制）与命令行 `--recognize <图片> [<图片> ...] [--threshold 0.85] [--max-results 20] [--no-annotate] [--no-scale]`；**多张模板**按顺序尝试、第一张达到阈值的直接用它的结果（多张共用同一张截图；读不出的图跳过继续）；**一张模板命中多处**时全部列出（按匹配度降序，`matches[0]` 为默认使用值），受 `max_results` 封顶并在触顶时提示；**纯色模板在 `load_template` 阶段被拒绝**（平坦区域会给纯色模板满分）；模板存 `assets/anchors/`（框选产物 `anchor_<时间戳>.png`，原始素材不入库）；**用户自己整理/命名的识别图片**放 `assets/templates/`（调试页「添加图片…」默认打开它，**按用户要求入库**）；`assets/screenshots/` 留给**识别底图**（用工具自带截图功能截的画面，功能待实现） | 坐标式自动化换分辨率/换界面就失效，需要"按图找点"；"同一目标多种外观"（多模板）与"同一图标多格出现"（多区域）是实际使用的两种基本形态；headless 版本不带 GUI 组件（比 opencv-python 小）。代价：打包体积 +60–70 MB |
| 识别的两项鲁棒性（2026-09-19 实测后补；同日按用户要求改为两档搜索 0.3x→4.0x） | ① **多尺度匹配**（默认开启，`DEFAULT_SCALE_RANGE = (0.30, 4.00)`、`SCALE_FAST_MAX = 2.00`）：**分两档**搜——先 0.3x–2.0x，没命中才扩到 0.3x–4.0x 继续搜（第二档不重复扫第一档档位）；每档内：粗搜缩放比例 → 在最佳比例附近精修 → 该比例下取全部命中；阈值在**精修之后**判断（真实缩放常落在粗搜两档之间，例如 0.75x）；**每档结束粗搜必须是"越过峰值后回落"**（禁止"遇到第一个够强的候选就停"：真值 3.50x 在粗搜 3.30x 就有 0.9018，提前停会报成 3.36x、框小一圈）。② **黑帧兜底**：取景顺序 PrintWindow(PW_RENDERFULLCONTENT) → PW_CLIENTONLY → BitBlt(窗口 DC) → 桌面屏幕 BitBlt（仅窗口在前台时），任一方式拿到纯色/黑帧就换下一种；全失败才报可读错误（提示以管理员身份运行 / 让窗口可见）。本作（GPU 渲染 + 管理员运行）实测 PrintWindow 返回纯黑帧。③ **取景原点必须是客户区左上**（2026-09-20 修正）：窗口 DC 与 PrintWindow 的原点都是"窗口左上角"（含标题栏/边框），所以 BitBlt(窗口DC) 必须以客户区偏移（`window.client_area_offset`，实测本作 (9, 37)）为源点、PrintWindow 必须整窗渲染再按该偏移裁出客户区；否则画面顶部多出标题栏、底部缺一截，识别坐标**整体偏下标题栏高度**（实测偏 37px，用户报告的 bug） | 没有 ① 时画面一放大/缩小就识别不到（用户实测）；没有 ② 时黑帧会被报告成"未识别到目标"，掩盖真实原因 |
| 测试 | pytest | 事实标准 |
| 打包 | PyInstaller one-dir（`packaging/build.ps1` + `LuoLuoTool.spec`，构建前强制全量测试；**GUI 子系统 console=False：双击无 cmd 窗口**，CLI 输出需重定向读取；不做 one-file 与安装包） | 生态成熟；注意杀软误报，需在文档说明加白 |

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
│   │   ├── registry.py      # 任务注册表：占位任务 A + order_hold/feature_3/feature_4 占位任务
│   │   ├── runner.py        # 执行调度器：多来源任务编排（日常组 + 单功能组）+ 失败计数 + 急停
│   │   ├── debug.py         # 开发者调试动作（单点/连点/滑动/键盘测试，复用输入通道）
│   │   ├── vision.py        # 图像识别编排：找窗口→就绪校验→截图→匹配→RecognizeResult
│   │   └── state.py         # 运行状态枚举与状态机
│   ├── automation/          # Windows 交互层
│   │   ├── window.py        # 窗口查找/置前/截屏、客户区几何、窗口诊断
│   │   ├── vision.py        # 取景/渲染（黑帧回退链、BitBlt/PrintWindow 几何）+ 匹配名字的对外门面
│   │   ├── template_match.py# 模板读取与匹配原语（读图/纯色拒绝/Match/locate_all）
│   │   ├── multiscale.py    # 多尺度（缩放）两档搜索（粗搜 + 精修 + 峰值回落）
│   │   ├── drag_path.py     # 滑动路径几何（缓出曲线 + 分帧插值，纯函数）
│   │   ├── elevation.py     # 进程/窗口权限检测与 UAC 提权重启
│   │   ├── input_sender.py  # 输入通道：DryRunSender（干跑）+ RealInputSender（真实键鼠）+ 窗口就绪守卫
│   │   ├── real_input.py    # 真实键鼠输入（SendInput）：唯一允许调用注入 API 的模块 + 输入前置顶校验
│   │   └── hotkey.py        # F8 全局急停
│   ├── gui/                 # PySide6 界面（薄层，不含业务逻辑）
│   │   ├── app.py           # QApplication + 主题
│   │   ├── main_window.py   # 主窗口（页签 + 启动/停止 + 状态栏 + 线程/状态编排）
│   │   ├── workers.py       # 后台线程：任务/调试测试/框选截图/窗口诊断 + run_debug_action 分发
│   │   ├── elevation_flow.py# 提权流程 mixin（检测/提示/以管理员身份重启）
│   │   ├── icons.py         # 窗口图标加载（魔数校验 + 降级）
│   │   ├── layout_measure.py# 布局测量：页签高度稳定规则的度量与报告（CLI 与调试页共用）
│   │   ├── dialogs/         # crop_dialog.py（弹窗外壳：提示/适配窗口/1:1 按钮/保存）
│   │   │                    #   crop_view.py（CropView：选区新建/移动/手柄缩放/键盘微调/绘制）
│   │   │                    #   crop_view_zoom.py（ZoomPanMixin：滚轮缩放/平移/放大镜）
│   │   │                    #   框选选区 → 存 assets/anchors/
│   │   ├── pages/           # daily.py / order_hold.py / feature3.py / feature4.py / settings.py / debug.py（开发者调试）/ about.py（关于）
│   │   └── widgets.py       # 通用小组件：LogPanelHandler + ScrollablePage（所有页签的基类）
│   └── utils/
│       ├── keys.py          # 键名表与组合键解析（config/automation 共用）
│       ├── logging_setup.py # 日志初始化
│       └── paths.py         # 运行时路径（user_data/logs）解析
├── tests/                   # 与 src 同构：test_config / test_core / test_automation / test_gui
├── assets/
│   ├── templates/           # 用户自己整理/命名的识别图片（**入库**；调试页「添加图片…」默认打开它）
│   ├── screenshots/         # 识别底图：用工具自带截图功能截的画面（原始素材，不入库）
│   ├── anchors/             # 开发者调试页「框选」产物（anchor_<时间戳>.png，原始素材，不入库）
│   └── icons/               # 静态资源：窗口图标等（入库）
├── user_data/               # 运行时生成，git 忽略；config.example.json 入库
├── logs/                    # git 忽略
├── reports/                 # 代码审查/复审报告（命名：CODE_REVIEW_REPORT_<年月日>_<第几份>.md，入库）
├── tools/                   # 开发期自检脚本（check_guide_index.py：BUG_HUNT_GUIDE 索引自检，不入打包产物）
└── packaging/               # 打包（Phase 7）：LuoLuoTool.spec、version_info.txt、build.ps1
                             # 产物 dist\LuoLuoTool\（one-dir，git 忽略）；资源与 exe 同级
```

**分层铁律**：
- `gui/` 只做展示与交互绑定，不得包含任务流程逻辑；
- `core/` 不 import PySide6、不 import win32；
- `automation/` 不 import PySide6；
- 依赖方向：`gui → core → automation/utils`，禁止反向 import。

## 8. 核心模块职责

| 模块 | 职责 | 关键接口（示意） |
|---|---|---|
| config | 配置模型、默认值、加载/保存/校验/版本迁移 | `AppConfig.load(path)`, `AppConfig.save(path)`, `validate(raw) -> list[str]`; `store.ConfigSaveError`（保存前校验失败时抛出，**磁盘文件保持原样**）, `store.save()`（先校验后落盘、覆盖更高版本前先备份） |
| core | 任务协议、注册表、执行调度、运行状态、开发者调试动作 | `class BaseTask: run(ctx)`, `TaskRegistry.get(task_id)`, `Runner.start(config)`, `Runner.stop()`; `debug.run_single_click/repeat_click/swipe/key(...)`（单点/连点支持 `hold_ms`，长等待切片可中断）; `state.try_transition(...)`（非法迁移返回 False，不抛异常；状态读写加锁） |
| automation | 找窗口、截图、真实键鼠输入（`SendInput`，输入前置顶校验）、急停热键 | `find_window(keyword)`, `screenshot_client(hwnd, path)`（窗口诊断截图：统一走 `capture_client_bgr` 回退链 → 真 PNG + 黑帧检测，不再自带 PrintWindow 实现）, `RealInputSender.click_at(x, y)` / `key_tap(vk)`, `build_channel(config, stop_event, sleep)`, `register_hotkey(...)` |
| automation（诊断/权限） | 窗口诊断（查找→强制置前→截客户区）、权限检测与 UAC 提权重启 | `find_window(keyword)`, `bring_to_front(hwnd) -> bool`, `diagnose_window(keyword, debug_dir) -> DiagnosticResult`; `is_process_elevated()`, `is_window_elevated(hwnd) -> bool \| None`, `restart_as_admin(extra_args) -> bool` |
| automation（真实键鼠，唯一实现方式） | 真实移动光标 + 模拟真实鼠标/键盘（点击、**滑动拖拽**、单键/组合键/长按）；**每次输入前**校验并确保游戏窗口在最顶层/前台，无法确保则不输入；点击支持**点击时长**（按下→按住 `hold_seconds`→抬起，默认 40 ms、0＝瞬时，按住期间可被急停打断且任何路径都会抬起左键） | `RealInputSender.click_at(x, y, hold_seconds=None)` / `drag(from_xy, to_xy, seconds)` / `key_tap(vk)` / `key_combo("ctrl+s")` / `key_hold("w", 0.8)`（真实模式下 `build_channel` 固定返回它）; `real_input.ensure_window_front(hwnd) -> FrontResult`, `real_input.move_cursor_absolute(x, y)`, `real_input.send_left_click(sleep, hold_seconds, stop_event)`, `real_input.send_key_tap(vk)`, `real_input.set_cursor_pos(x, y)`, `real_input.release_topmost(hwnd)`, `real_input.normalize_absolute(x, y, desktop)` |
| automation（匹配/几何，2026-09-20 拆分） | 模板读写与匹配原语、多尺度两档搜索、滑动路径几何、**模板区域质量评估**；`vision.py` 只留取景/渲染并**再导出**匹配名字（旧导入路径不变） | `template_match.load_template(path)` / `locate_all(...)` / `is_blank_frame(img)` / `prepare_for_match(img, grayscale)`（跨模块共用的预处理，原 `_prepare`）/ `assess_region_quality(img) -> RegionQuality`（可辨识度：对比度 + 边缘占比，`level` ∈ ok/low/flat，`flat` 拒绝当模板；2026-09-21）, `multiscale.locate_all_scaled(...)` / `scale_candidates(...)`, `drag_path.build_drag_path(start, end, steps, tail_hold_steps=...)`, `vision.capture_client_bgr(hwnd)` |
| gui（线程/提权/图标，2026-09-20 拆分） | 后台线程与调试动作分发、提权流程、窗口图标加载；`main_window` 只做展示与绑定 + 线程/状态编排 | `workers._RunnerThread` / `_DebugTestThread` / `_CaptureThread` / `_DiagnoseThread`, `workers.run_debug_action(config, kind, params, log, stop_event)`, `elevation_flow.ElevationFlowMixin`（`MainWindow` 继承）, `icons.load_window_icon() -> QIcon` |
| gui（框选弹窗，2026-09-21 拆分） | 框选截图生成模板：弹窗外壳 / 交互视图 / 显示变换三层，全部以**图像像素坐标**对外暴露选区（＝客户区坐标）；保存前做**可辨识度检查**（纯色区域拒绝保存） | `crop_dialog.TemplateCropDialog(image_bgr, window_size, save_dir)`；`.selection()` / `.selection_quality()`（`RegionQuality | None`）/ `.save_selection()`（**只存框选区域**，纯色区域返回 None）/ `.zoom_fit_button` / `.zoom_actual_button` / `.view_status_text()`; `crop_view.CropView(image_bgr)`：`.selection_in_image()` / `.set_selection_in_image(x, y, w, h)` / `.hit_test(point)` / `.drag_bubble_text()` / `.magnifier_rect()` / `.zoom_percent()` / `.cursor_position()` / `.zoom_to_fit()` / `.zoom_to_actual()`（后 5 个由 `crop_view_zoom.ZoomPanMixin` 提供，`CropView(ZoomPanMixin, QWidget)`）；信号 `selection_changed` / `view_changed` |
| gui | 六页签（设置/日常任务/卡订单/功能三/功能四/**关于**）+ 可选「开发者调试」页 + 日志面板 + 状态栏；**所有页签继承 `widgets.ScrollablePage`**（内容进 `QScrollArea` + 建议尺寸 `PAGE_SIZE_HINT`），页签高度不随挂载/卸载变化；「关于」页承担规范要求的风险/隐私声明与第三方许可说明 → `pages/about.py` | `MainWindow(config, runner)`; 调试页 `DebugPage.test_requested(kind, params)` / `diagnose_requested()` / `layout_measure_requested()`; `layout_measure.measure_layout(window)` / `format_measure_report(measure)`; 功能三/功能四公共基类 `pages.planned_feature.PlannedFeaturePage`; 急停热键不可用提示 `SettingsPage.show_hotkey_hint(text)` |
| utils | 日志初始化、路径解析 | `setup_logging(level, max_file_mb, backup_count)`（幂等，可重配置，参数变化时重建 handler）, `get_user_data_dir()` |

## 9. 数据结构（配置文件 schema v8）

路径：`user_data/config.json`（运行时生成；仓库内只保留 `config.example.json`）。

```json
{
  "schema_version": 9,
  "features": {
    "daily_tasks": {
      "enabled": false,
      "tasks": {
        "placeholder_task_a": {
          "enabled": false,
          "order": 1,
          "params": {
            "click_points": [],
            "swipes": [ { "from": [300, 300], "to": [700, 300], "duration_ms": 500, "wait_after_ms": 500 } ],
            "keys": [ { "combo": "ctrl+s", "hold_ms": 0, "wait_after_ms": 300 } ],
            "wait_after_ms": 500
          }
        }
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
    "dry_run": false,
    "window_title_keyword": "桃源深处有人家",
    "click_interval_ms": 800,
    "post_click_wait_ms": 500,
    "max_consecutive_failures": 3,
    "failsafe_hotkey": "F8",
    "ask_elevation_on_start": true,
    "restore_cursor_after_click": true,
    "developer_mode": false,
    "save_vision_annotations": true
  },
  "logging": { "level": "INFO", "max_file_mb": 2, "backup_count": 3 }
}
```

字段约定：
- 所有新增字段**必须**提供默认值；修改结构时必须把 `schema_version` +1 并实现迁移函数。
- 布尔开关一律 `false` 为出厂默认；**`dry_run` 出厂默认自 2026-09-19 起改为 `false`**（用户要求"干跑模式默认不开启"，首次启动即真实模式）——因此真实模式的兜底改为：启动前强制确认弹窗 + F8 急停 + 点击越界校验；**测试**里仍恒为干跑（`tests/conftest.py` 强制）。
- `params` 为每任务私有参数，按任务类型定义结构（缺省键回落默认值）：
  - `placeholder_task_a`：`{"click_points": [[x, y], ...], "wait_after_ms": 500}`
    - `click_points`：客户区坐标序列（`[[x, y], ...]`，允许为空列表，此时任务只写提示日志不动作）；
    - `keys`：按键步骤序列（`[{combo, hold_ms, wait_after_ms}, ...]`，最多 20 步）：`combo` 为组合键文本（如 `ctrl+s`，键名表见 `utils/keys.py`），`hold_ms` > 0 表示长按该毫秒数（0 = 单击）；长按期间可被急停打断并保证释放按键；每次按键前同样会校验并置顶游戏窗口。
    - `swipes`：鼠标滑动步骤序列（`[{from, to, duration_ms, wait_after_ms}, ...]`，最多 20 步）：从 `from` 按住左键沿**缓出曲线**（`build_drag_path`）分帧移动到 `to`，**末尾在终点保持静止数帧**（`DRAG_TAIL_HOLD_STEPS`）后再松开——匀速"甩到底即松手"会被引擎识别为 flick，松手后画面带惯性继续飘；`duration_ms` 50–10000（默认 400）；滑动前同样校验并置顶游戏窗口，并**先清理可能残留的左键按下状态**；滑动期间可按急停立即中断；松手后**复查 `VK_LBUTTON` 是否真的抬起**（未抬起则补发，仍失败即报可读错误并提示手动点击左键）；**任何退出路径（含等待异常）都释放左键**（绝不卡住鼠标）；滑动结束后**同样按 `restore_cursor_after_click` 还原光标**，但走"先延迟后分帧小步移回"的 `restore_cursor_smooth`（一次跳回会被残留拖拽状态算成巨大位移而让画面乱飘，详见 §4.2.3 修复记录）。
    - `wait_after_ms`：每个步骤后的等待毫秒数（0–60000）。
- 配置文件为 UTF-8；读写使用临时文件 + `os.replace` 原子替换。

### 版本迁移记录

| 版本 | 变更 | 迁移函数 |
|---|---|---|
| v1 → v2 | 新增 `automation.ask_elevation_on_start`（默认 `true` = 启动时询问提权）；`false` 表示不再询问 | `validation.migrate()` → `_migrate_v1_to_v2` |
| v2 → v3 | 新增 `automation.align_window_before_click`（默认 `false` = 不移动窗口；`true` = 点击前对齐游戏窗口，见 §5） | `validation.migrate()` → `_migrate_v2_to_v3` |
| v3 → v4 | 移除 `align_window_before_click`，新增 `automation.restore_cursor_after_click`（默认 `true`）。<br>（v4 曾一度把该布尔升级为 `input_mode` 枚举，随 v5 一并废除） | `validation.migrate()` → `_migrate_v3_to_v4` |
| v4 → v5 | 输入实现方式固定为「真实鼠标键盘」：移除 `automation.input_mode` 与 `automation.pause_on_window_focus_loss`（后者与该通道冲突，永不生效），保留 `restore_cursor_after_click` | `validation.migrate()` → `_migrate_v4_to_v5` |
| v5 → v6 | 任务参数新增**按键序列** `params.keys`（默认 `[]` = 不发送按键）：元素为 `{combo, hold_ms, wait_after_ms}`，支持组合键与长按 | `validation.migrate()` → `_migrate_v5_to_v6` |
| v6 → v7 | 任务参数新增**鼠标滑动序列** `params.swipes`（默认 `[]` = 不滑动）：元素为 `{from, to, duration_ms, wait_after_ms}`，按住左键分帧拖拽 | `validation.migrate()` → `_migrate_v6_to_v7` |
| v7 → v8 | 新增 `automation.developer_mode`（默认 `false` = 不显示「开发者调试」标签页） | `validation.migrate()` → `_migrate_v7_to_v8` |
| v8 → v9 | 新增 `automation.save_vision_annotations`（默认 `true` = 图像识别成功后仍存带框截图到 `user_data/debug/`；开发者调试页可关） | `validation.migrate()` → `_migrate_v8_to_v9` |

> 字段沿革：合成指针通道曾在 v3 引入 `automation.input_mode`（`window_message`/`synthetic_pointer`）与 `pointer_type`，**随该通道撤回**（见 §4.2.1）；v4 又把 `input_mode` 重新定义为三档实现方式选择，**2026-09-16 用户确定只保留真实鼠标键盘后随 v5 删除**。若某份旧配置仍残留这些字段，迁移链会把它们逐一移除（已有单测覆盖）。

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
| `python -m luoluotool --measure-layout` | 离屏测量各页签的布局占用并打印报告（页签高度稳定规则的回归检查；退出码 0/1） |

约定：所有 CLI 参数解析放在 `__main__.py`，解析后交给 `gui.app.run(argv)`；退出码：0 成功，1 配置错误，2 运行环境错误。

## 11. 验收标准（按阶段细化见 PHASE_PROMPTS.md）

### 整体 DoD（Definition of Done）
- [ ] GUI 启动时间（冷启动到窗口可见）≤ 3 秒（PyInstaller 打包后 ≤ 5 秒）。
- [ ] 勾选→启动→执行→日志全链路可用；执行期间 UI 可拖动、可点「停止」。
- [ ] 默认真实模式（`dry_run: false`）启动前有确认提示 + F8 急停；勾选干跑后零真实键鼠输入。
- [ ] 点击越界校验：坐标必须落在游戏窗口客户区 `[0,width)×[0,height)` 内，越界或读不到客户区时**不点击**并写 WARNING 日志（真实与干跑通道都要校验）；滑动（拖拽）的起点与终点同样校验。
- [ ] 图像识别：给定模板图能在当前游戏窗口客户区里返回命中坐标（客户区中心/左上/尺寸/匹配度）；**画面放大/缩小时仍能命中**（多尺度匹配，报告里给出缩放比例）；**多张模板**时第一张命中的直接用它的结果（消息里指出用的是第几张），读不出的图跳过并继续、全部落空时逐张列出结果；**一张模板命中多处**时全部列出、条数受「最多列出」/`--max-results` 限制并在触顶时提示；**纯色模板报可读错误**（不给满分假坐标）；窗口未找到或最小化时给出可读提示；模板比截图大或文件不可读时报可读错误；调试页与 `--recognize` 两个入口都可用；识别本身**不产生任何输入**。
- [ ] 取景鲁棒性：PrintWindow 取到纯色/黑帧时自动换其它取景方式（含桌面屏幕 BitBlt，仅前台时）；全部失败给出「以管理员身份运行 / 让窗口可见」的可读错误，**不得**把黑帧报告成"未识别到目标"。
- [ ] 框选生成模板：调试页「框选截图生成模板」→ 后台截图 → 弹窗拖拽框选 → 保存 `assets/anchors/anchor_<时间戳>.png` 并**自动回填图片路径**；**框选完还可在弹窗里改选区**（拖内部＝整体移动、拖四角/四边手柄＝改大小、选区外重拖＝重新框选；方向键＝整体微调 1 图像像素、`Shift+方向键`＝10 像素、`Ctrl+方向键`＝对应边向外 1 像素、`Ctrl+Shift+方向键`＝同一条边向内 1 像素；移动夹在图像内、改大小不小于 8px）；框选坐标即客户区坐标，用生成的模板识别必须命中同一坐标（有离线全流程验证）。
- [ ] 带框截图为可选项：关闭开发者调试页的「识别成功时保存带框截图」后，识别只给坐标、不写 `user_data/debug/vision_*.png`（配置 `automation.save_vision_annotations=false`，CLI 亦跟随该配置）。
- [ ] 真实模式的副作用已如实告知并可配置：确认弹窗写明「真实移动鼠标 + 抢前台 + 封号风险 + 急停键」；点击后按 `restore_cursor_after_click` 还原真实光标；干跑模式仍零输入。
- [ ] 配置损坏时程序可启动并提示恢复为默认值，而不是崩溃。
- [ ] `pytest` 全绿；`python -m luoluotool --validate-config` 可用。
- [ ] PyInstaller 产物在**干净 Windows 10/11**（无 Python）上可启动。
- [ ] 功能一：占位任务按配置顺序执行并可中断；后续真实任务按同样契约接入。
- [ ] 功能二：主开关可存可读，两个预留开关可存可读且无副作用；主开关开启即入队（Phase 6 已闭环：进入日志 + 心跳日志 + 响应停止）。
- [ ] 功能三/四：页签可切换，开关可存可读，页面不报错；开关开启即入队（Phase 6 同上）。
- [ ] 任务编排：日常任务组 + 单功能组按规则合并、顺序确定、失败计数统一（有测试证明）。

### 阶段验收概览
| 阶段 | 核心验收 |
|---|---|
| Phase 0 | `python -m luoluotool --version` / `--smoke-gui` 通过，空窗口四页签 |
| Phase 1 | 配置读写/校验单测全绿，`--validate-config` 可用 |
| Phase 2 | GUI 与配置双向同步，修改有脏标记与保存 |
| Phase 3 | 干跑任务可启停，F8 急停生效，无真实输入 |
| Phase 4 | 能定位游戏窗口并截图到 `user_data/debug/` |
| Phase 5 | 输入通道可启停、日志完整（当时的窗口消息通道与失焦暂停已于 2026-09-16 随 Phase 5.3 收敛删除） |
| Phase 6 | 卡订单与预留页逻辑闭环（开关 → 入队 → 日志 → 可急停），任务编排规则明确且可测，预留开关零行为 |
| Phase 7 | exe 在干净 Windows 上冒烟通过 |

### 已知问题（Phase 7 打包时发现）
1. ~~冻结 exe 的 `--measure-layout` 在 GBK 控制台崩溃~~ **已于 2026-09-19 修复**：报告里的 `✓ ✗` 换成
   GBK 可编码的 `[OK]` / `[NG]`，并由 `__main__._print_safe()` 兜底任何不可编码字符（先原样打印、失败后按当前编码替换；stdout 为 None 时静默跳过）。回归测试：`test_format_measure_report_is_cp936_printable`、`test_print_safe_degrades_on_gbk_console`、`test_print_safe_survives_missing_stdout`。实测冻结 exe 的 `--measure-layout` 现退出码 0。

## 12. 变更管理

- 任何超出本文档范围的想法（新功能、新依赖、新交互）**先修改本文档并同步 PHASE_PROMPTS.md**，再写代码。
- schema 变更必须走版本迁移；禁止静默删除/重命名字段。
- 阶段之间代码不得回滚重写整包；只允许增量修改，发现问题先写失败测试再修。
