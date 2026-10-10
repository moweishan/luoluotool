# CODE_REVIEW_REPORT_20260922_1.md — LuoLuoTool 第五轮审查报告（日常任务页批 2 · schema v10，2026-09-22 第 1 份）

> **本次为只读审查，未修改任何代码。**
> 审查范围：`git HEAD = 4e8e58c`，即 **`c71597a..HEAD` 的 10 个提交**（43 文件 / +2747 −531 行）：日常任务页按设计稿重建并接配置、**schema v9→v10 迁移**、参考图三件事（选择图片 / 截取游戏画面 / 放大预览）、第四轮 14 项修复。
> 审查方式：区域分包静态审查 + **只读实测**（迁移往返实验、离屏交互复现、图片解码计时）+ 全部红线守卫复跑。
> 上一份：`reports/CODE_REVIEW_REPORT_20260921_1.md`。
>
> **结论：`APPROVE`（附 5 条 P2、6 条 P3）**
> 第四轮 14 项**全部修复并逐条验证**；schema v10 的迁移/校验/往返经实测无误；新功能的架构分层与守卫都到位。
> 本轮问题集中在**"新页面接上配置之后，有几处口径没跟着走"**：一个失效控件、一个急停盲点、两条与实现相反的文档、以及 GUI 线程里的大图解码。

---

## 1. 验收与守卫（实测）

| 检查 | 结果 |
|---|---|
| `pytest -q` | **672 passed**（上一轮 619 → +53，0 skipped） |
| `--validate-config` | OK |
| `--smoke-gui` | exit 0 |
| `--measure-layout` | `[OK]`（新增「日常任务页」控件与「选择的图片」预览区后，7 个页签仍「不改变任何高度」） |
| 分层自检（AST） | `layer check violations = 0` |
| 注入面 | `SendInput`/`SetCursorPos` 仍只在 `automation/real_input.py` |
| 联网 | **`src/` 无任何网络 import**；`requirements.txt` 无 HTTP 客户端 ✔（`PROJECT_SPEC` §4.4 只留文档缺口 + 7 条硬约束，代码里不预埋） |
| 文件长度 | 源码最大 599 行（`crop_view.py`）、测试最大 589 行，全部 ≤600 ✔ |
| 依赖 | 无新增第三方依赖 |
| 文档索引 | 「检查 **118** 条索引，漂移 0 条」 |

---

## 2. 第四轮 14 项修复：全部验证通过

| 编号 | 验证方式 | 结果 |
|---|---|---|
| **P2-1** 单击后拖拽丢框 | **重跑离屏复现**：单击 → 5 像素内按下 → 拖到 (100,100) | ✅ 单击后 `_image_selection=None`、`handle_rects()={}`；`_mode=create`，拖出 `(40,68,60,57)`（不再产出不可见的 8×8） |
| **P2-2** 试识别口径与文案 | 代码 + 文案 | ✅ 阈值改为 `debug_page.vision_threshold()`；结论改为「本图 1:1 匹配（阈值 …）下只命中你框的这一处」，docstring 明文禁止旧写法 |
| **P2-3** 旧结论残留 | 代码 | ✅ `_on_probe_finished` 比对 `result.region != self.selection()` 即丢弃并提示"已作废" |
| **P2-4** 线程身份竞态 / 关窗阻塞 | 代码 | ✅ `self.sender() is not self._probe_thread` 保护置空；`done()` 改 `_release_probe_thread()`（**不 wait**）；线程进 `ACTIVE_PROBES` 强引用，只断开本弹窗的槽 |
| **P2-5** `test_paths` 依赖 git 配置 | 代码 | ✅ `_git` 显式加 `-c core.quotePath=false` 并注明原因 |
| P3-1~P3-9 | 逐条 grep/读码 | ✅ 死常量删除、滑条 API 重写、`flat` 全分辨率复核、读路径口径写明、关于页隐私措辞/日志/tooltip 惰性化、误操作风险补进 About、`.gitignore` 五后缀、`hit_test` 只算一次手柄、三份 `_image()` 收敛为 `gui_helpers.crop_image()` |
| **P3-3** 滑条往返有损 | **重跑实测**：1001 个刻度 | ✅ 改用「滑条↔缩放倍数」新 API 后 **0/1001 不一致**（端点 0.5x/8.0x，100%＝刻度 250 精确） |

---

## 3. schema v10：迁移与校验实测（结论：正确）

| 检查 | 方法 | 结果 |
|---|---|---|
| 老字段一字不变 | 造 v9 配置（改过 `enabled`/`interval_seconds`/`order`/`window_title_keyword`/预留开关）→ `store.load` | ✅ 五项全部原样保留，写回 `schema_version=10` |
| 新字段补默认 | 同上 | ✅ `island=1/1/1`、三个 `*_ref_image=""`、`auto_produce_least=false`（与文档一致） |
| 幂等 | `migrate(已迁移)` | ✅ 返回原对象（不改动） |
| 畸形输入不崩 | v9 文件里 `coop_island="x"` | ✅ 判损坏 → 备份 + 默认值，**不崩溃**（走既有 `_recover`） |
| example 一致性 | `json.load(config.example.json) == AppConfig.default().to_dict()` | ✅ **True** |
| 边界与共享常量 | `validation.py` | ✅ 岛屿 1–10（`ISLAND_RANGE` 与 GUI 共用）、参考图路径 ≤260（`_OPTIONAL_STR_LIMITS`）、`auto_produce_least` 是 bool；`isinstance(v, bool)` 排除了"True 当 1" |
| 旧语义测试处理 | `git show` | ✅ 旧用例 `test_daily_group_switch_does_not_affect_queue` 被**替换**为 `test_daily_group_switch_gates_the_daily_queue`（不是删掉），AGENTS ⑩ 明文记录 |

---

## 4. Findings

### P0 — Critical
无。

### P1 — High
无。
（子代理提出的两条 P1 经复核下调：规范章节过期属**文档**缺陷、GUI 线程解码经计时为 **17–373 ms 量级**而非"长任务"，见 P2-4/P2-5。）

### P2 — Medium

**P2-1 `core/runner.py:148-153` + `config/validation.py:_migrate_v9_to_v10` + GUI — 总开关语义变更对老用户静默生效，没有任何提示**

`schema v9` 的老配置里 `features.daily_tasks.enabled` 出厂默认是 `false`（当年它"只存不读"），而 v10 起它是**真的总开关**：`daily_enabled` 为假时**日常任务组一个都不入队**。迁移只对**新字段** `setdefault`（`_migrate_v9_to_v10` 原文："已经填过的值一个都不动"），因此：
> 老用户升级后，**已勾选的日常任务会静默不再执行** —— runner 只在整队列为空时写「未选择任何任务，不执行」，GUI 与状态栏都没有"总开关关着、勾了也不会跑"的提示。

**建议**（一行日志 + 一条状态栏提示即可）：加载配置或启动任务时，若 `daily_tasks.enabled == false` 且存在 `tasks[*].enabled == true`，写一条 WARNING「日常任务总开关关闭，已勾选的 N 个任务不会执行」。不改字段、不改迁移（保持"老字段一字不变"的既有承诺）。

**P2-2 `gui/pages/daily.py:184-192` + `core/runner.py:126` — 循环间隔控件是**失效控件**，且重建时把「循环执行」开关丢了**

* 现在页面只有 `loop_interval_minutes`（写 `features.daily_tasks.loop.interval_seconds`）；
* 全仓 grep：**没有任何 GUI 代码写入 `loop.enabled`**（它默认 `False`，`models.py:66`），而 runner 不循环的条件正是 `not loop.enabled`（`runner.py:126`）；
* 重建前（`c71597a`）的页面本来有 `self.loop_box = QCheckBox("循环执行") ↔ daily.loop.enabled`（`_on_loop_toggled`），重建后连开关一起消失了；
* 控件 tooltip 却写着「仅在**执行方式**为「按固定间隔循环」时生效」，而页面上并没有"执行方式"控件。

即：用户把间隔改成 30 分钟，**什么都不会发生**（队列跑一轮就结束），而且默认值还相差 30 倍（见 P3-3）。
**建议**：二选一 —— ① 补回「执行方式 / 循环执行」开关（绑 `loop.enabled`）；② 若属于批 3，把该控件标注为"尚未生效（批 3）"并禁用，tooltip 不要指向不存在的控件。

**P2-3 `gui/main_window.py:382-389` — `_stop()` 不通知日常页截图线程：F8 / 「停止」按不动"截取游戏画面"**

```python
def _stop(self) -> None:
    if self._debug_thread is not None and self._debug_thread.isRunning():
        self._debug_thread.request_stop()
    if self._runner is not None:
        self._runner.request_stop()
    if self._thread is not None and self._thread.isRunning():
        self._thread.wait(THREAD_WAIT_TIMEOUT_MS)
```

`DailyCaptureThread.request_stop()` 全仓**没有生产调用方**（只有定义与测试）。而该线程自己的 docstring 明确写着等待是切片式的、"便于急停/关窗时尽快收手"，`_long_job_running()` 也已经把它算作长任务 —— 于是：
* 按 F8 / 「停止」时状态栏会说"已请求停止…"，但 0.4 s 后**框选窗口照样弹出来**；
* 只有关窗（`_wait_for_threads`）会等它。

**建议**：`_stop()` 里补 `self._daily_media.capture_thread().request_stop()`（`_on_stop_clicked` 的判定已经覆盖它，无需再改）。

**P2-4 `gui/daily_media.py:195,310,364` — 参考图解码在 GUI 线程里做（实测最大 ~1.1 s 冻结）**

`adopt_image_file`（选图）→ `load_template(path)`、`build_preview_dialog`（预览）→ `read_image_bgr(path)`、`refresh_previews()`（重载/恢复默认）→ 连读 3 张，全部在 GUI 槽里同步执行。**本机实测**：

| 图片 | `read_image_bgr` | `load_template`（含质量判据） |
|---|---|---|
| 799×478（典型锚点） | 20.7 ms | 17.1 ms |
| 1920×1052（整屏截图） | 41.0 ms | 94.3 ms |
| **3840×2160（4K）** | **117.9 ms** | **372.7 ms** |

单张 4K 就接近 0.4 s，`refresh_previews()` 三张最坏 ≈ **1.1 s** 界面冻结 —— 而 `assets/screenshots/` 的用途正是"拿工具截的整屏画面当识别底图"。
**建议**：把"路径 → QImage"这一步挪进线程（项目已有成熟模式：QThread + 信号回主线程），或至少缓存解码结果（同一路径不重复解码）。

**P2-5 文档与实现相反（规范章节 + README）**

| 位置 | 现文（已过期） | 与代码的冲突 |
|---|---|---|
| `PROJECT_SPEC.md:55-56`（§3 编排规则**第 6 条**）+ `:47`（第 1 条） | 「**不参与编排**的开关（保持「存/读/显示」语义）：`features.daily_tasks.enabled` … 有测试断言它们不影响运行任务集合」 | runner 现在**按它 gate 日常任务组**；同文件 §9:413 已改成新语义 → **规范章节内部自相矛盾** |
| `CHECKLIST.md:136` | 「`daily_tasks.enabled` 与两个预留开关不参与编排」 | 同上 |
| `README.md`（日常任务页行） | 「**当前只做界面**：控件不写配置、「选择图片…」「截取游戏画面」按钮暂不可用（第 2/3 批接入）」 | 批 2 已落地：双向绑定可用、按钮可用、截图/框选/预览全部接上 |

`PROJECT_SPEC` §3 是编排规则的**规范来源**，后续会话若照它行事，很可能把 runner 改回旧语义或写出与新行为相悖的测试。
**建议**：① §3 第 1/6 条改成"日常任务组需 **总开关 + 任务自身开关** 同时为真；两个预留开关仍不参与编排"；② CHECKLIST 拆成两行（预留开关仍惰性 / 总开关已生效）；③ README 那行改成实际状态（并说明循环间隔待批 3）。

### P3 — Low

1. **选图路径长度未在选中时校验**：`daily_media.py:201/263` 直接 `to_config_path(path)`；校验器限长 260（`validation.py:59-61`），仓库外/UNC 长路径会被接受，随后 `store.save` 抛 `ConfigSaveError` → **本次全部改动都不落盘**（有弹窗提示、磁盘配置不损坏）。建议选中即校验长度并给可读状态提示。
2. **`utils/paths.resolve_config_path` 不做归一化/包含性检查**：`"../../x.png"` 会解析到仓库外。绝对路径本来就是允许的（设计如此），所以这不是安全边界，但与"相对仓库根"的语义不一致；建议 `resolve()` + 显式注释说明。
3. **4 个死常量 + 1 处误导默认值**（全仓各只出现 1 次＝只有定义）：`daily.py:81 ISLAND_COUNT`、`daily.py:92 IMAGE_PENDING_NOTE`、`widgets.py:16 PREVIEW_TEXT_COLOR`、`models.py:24 LOOP_INTERVAL_MINUTES_DEFAULT = 30`。最后一条还与真实默认 `interval_seconds = 3600`（＝60 分钟）**不一致**，且正是 P2-2 那个控件的默认值来源，容易让人以为"默认 30 分钟"。
4. **测试覆盖缺口**：`tests/test_gui_run.py::test_close_event_waits_for_all_background_threads` 的替身列表只有 `_thread/_debug_thread/_capture_thread/_diagnose_thread`，**漏了日常页截图线程**（`_wait_for_threads` 里那一条实际没测到）；`tests/test_gui_daily_media.py:295` 只测"忙时拒绝再启动"，没测 `start()` → `_on_thread_finished` 的接线。
5. **框选产物命名漂移**：日常页传了 `file_stem="鸡舍_岛屿N"`，产物变成 `鸡舍_岛屿1_<时间戳>.png`；而 `BUG_HUNT_GUIDE.md:642`、`PROJECT_SPEC.md:267,323`、`AGENTS.md:37` 仍只写"anchors 里是 `anchor_<时间戳>.png`"。建议补一句"日常页用 `{建筑}_岛屿{N}_<时间戳>.png`"。
6. **迁移写回会丢未知字段**（既有行为）：`migrate()` 特意保留未知键，但 `store.load` 用 `AppConfig.from_dict(...).to_dict()` 重写文件，未知键消失。建议加一条测试记录该行为，或在文档写明"迁移会规范化文件"。

---

## 5. 已验证正确的关键点（避免误伤）

- **第四轮 14 项全部修复**，其中 12 项是"改对了 + 补了回归测试"，2 项（`NEAR_FULL_RATIO` 死副本、`zoom_to_actual` 死 API）选择了**删/复用**而非留注释 —— `zoom_to_actual` 还被接回真实入口（双击滑条＝1:1），比单纯删除更好。
- **UI/业务分离**：`daily.py` 只发三个信号（`pick_image_requested`/`capture_requested`/`preview_requested`），选文件/截图/框选/写配置/读图全在 `gui/daily_media.py`（372 行，新模块）—— 正合 `AGENTS §1.5`。
- **截图链路**：`DailyCaptureThread` 在后台线程里 `bring_to_front` → 可中断切片等待 0.4 s → `capture_window`，失败只提示不弹窗；`_wait_for_threads()` 已把它的线程纳入关窗等待。
- **选图即校验**：`load_template`（纯色拒收，与识别同一判据）+ `assess_region_quality`（低辨识度只提示）；框选产物同样走 `load_template` 复核。
- **配置路径**：存"相对仓库根"的 POSIX 路径（仓库外退化为绝对路径），文件被删/改名**只清缩略图 + 记日志，绝不改配置**；`--measure-layout` 证明加预览区后页签高度不变。
- **只读开关**用事件过滤器 + `NoFocus`（不是 `setEnabled(False)`），并留了 `AUTO_PRODUCE_LEAST_READONLY` 一行开关；`auto_produce_least` 仍入库。
- **通知/联网边界**：`PROJECT_SPEC §4 第 9 条 + §4.4 + AGENTS ⑨⑫` 把"通知不得做成软件功能"与"远程配置缺口（7 条硬约束）"写清楚了，且**代码里没有任何联网痕迹** —— 这一轮的红线守得很严。
- 双向绑定有 `_loading` 防回写；`set_config` 只显示不置脏；"配置里 90 秒"这类非整数分钟**显示取整但不回写**（有测试）。

---

## 6. 结论与建议顺序

| 维度 | 结论 |
|---|---|
| 第四轮修复 | 14/14 验证通过（含 2 项客观复现） |
| schema v10 | 迁移/校验/往返/示例文件全部实测正确，旧用例被替换而非删除 |
| 新功能 | 分层、线程、校验、守卫、文档同步都到位；672 passed、四条验收全绿 |
| 主要风险 | **P2-2（失效控件）与 P2-3（急停盲点）是用户能直接踩到的**；P2-1 是升级体验；P2-4 是大图卡顿；P2-5 是文档 |
| **总体** | **APPROVE** |

**建议顺序**：① P2-3（一行代码，急停相关优先）→ ② P2-2（补回循环开关或标注未生效）→ ③ P2-1（升级告警一行日志）→ ④ P2-5（三处文档）→ ⑤ P2-4（解码挪线程）→ P3 随手。

**未覆盖 / 未能验证**：
- 无游戏窗口，**未做实机验证**（截取游戏画面/框选的真实观感、切前台对游戏的影响、4K 参考图的实际卡顿）。
- 未跑 PyInstaller 打包（新模块 `gui/daily_media.py` 是否被 spec 收集，建议打包时确认一次）。
- `ACTIVE_PROBES` 在线程仍在跑时进程退出这一情形，未在真实 GUI 下复现（离屏难稳定触发 GC 时机）。
- 设计稿 HTML 本身（仓库外文件）未逐条对照，仅按代码里的 `DESIGN_CONTROL_IDS` 与测试反推。
