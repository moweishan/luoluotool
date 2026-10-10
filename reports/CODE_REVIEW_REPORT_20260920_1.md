# CODE_REVIEW_REPORT_20260920_1.md — LuoLuoTool 代码审查报告（2026-09-20 第 1 份）

> **本次为只读审查，未修改任何代码。**
> 审查基线：`git HEAD = 7e56cc4`（2026-09-20），工作区当时干净（仓库中另有一份**并发会话**的未提交改动，见文末「未覆盖范围」）。
> 审查范围：`src/luoluotool/**` 全部 29 个文件 / 6167 行 + `tests/**` 6911 行。
> 对照规范：`AGENTS.md`、`PROJECT_SPEC.md`、`CHECKLIST.md`、`BUG_HUNT_GUIDE.md` 的不变量表。
> 审查方式：静态审查 + AST 分层自检 + 红线 grep + 只读复现实验（全部在系统临时目录，未触碰仓库文件）+ 全量测试。
>
> **结论：`REQUEST_CHANGES` ｜ P0 = 0，P1 = 3，P2 = 9，P3 = 10（共 22 项）。**
> 基础工程质量高（分层零违规、注入面收敛、异常处理规范、468 测试全绿），但有 3 个必须优先修的缺陷：
> 一个**启动崩溃**、一个**配置自毁**、一个**违反置顶清理硬规则的泄漏**。

---

## 0. 验收基线（本次实测）

| 命令 | 结果 |
|---|---|
| `python -m pytest -q` | **468 passed** |
| `python -m luoluotool --validate-config` | `OK` |
| `python -m luoluotool --smoke-gui` | exit 0（日志含「离屏冒烟完成」） |
| `python -m luoluotool --measure-layout` | 末行「挂载/卸载开发者调试页不改变任何高度 `[OK]`」 |
| 分层自检（AST） | `layer check violations = 0` |

---

## 1. P0 — Critical

无。

---

## 2. P1 — High（必须修）

### P1-1 `config/validation.py:238` — 迁移函数对畸形 `params` 抛异常，且不在任何 `try` 内 → **启动崩溃**

```python
params = dict(item.get("params") or {})      # params 是 list 等合法 JSON 时 → TypeError
```

`config/store.py:43` 的 `migrated_raw = migrate(raw)` 位于 `try` **之外**（那里的 `try` 只包住 JSON 解析），异常直接冒到 `gui/app.py` → 进程崩溃。

* **实测复现**：写入 `schema_version = 5` 且 `params = [1, 2]` 的配置 → `store.load(p)` 抛
  `TypeError: cannot convert dictionary update sequence element #0 to a sequence`。
* **建议**：`migrate()` 每一步迁移用 `try/except Exception` 包住，失败记 `logger.exception` 并 `return raw`，交由 `validate()` 报错走 `_recover()` 恢复路径；或把 `migrate` 调用移入 `store.load()` 的 `try`。

### P1-2 `gui/pages/daily.py` + `config/store.py:16-30` — GUI 能保存"自己读不回来"的配置，下次启动**整份配置被重置为默认**

写入路径不校验：`_on_keys_edited` → `parse_keys_text()` 无步数上限，`store.save()` 也从不调用 `validate()`；
读取路径 `config/validation.py:96` 却有 `MAX_KEY_STEPS = 20` 硬上限，超限即判"损坏" → `_recover()` 备份后**整体恢复出厂默认**。

* **实测复现**：输入 25 步按键 → 保存成功 → 再次 `store.load()` 后：
  `daily_tasks.enabled` 由 `True` 变 `False`、`keys` 由 25 步变 0，目录只剩 `config.json.bak-<时间戳>`（用户全部设置丢失，仅在日志里看到"配置损坏"）。
* **建议**：① `store.save()` 前调用 `validate()`，不合法就拒绝保存并给出可读提示；② 至少把 `parse_keys_text` / `parse_swipes_text` 的步数上限与 `validation.MAX_KEY_STEPS` 统一（GUI 即时拒绝超限输入）。

### P1-3 `automation/input_sender.py:274-282` — 置顶成功后无法置前时抛错，**永不取消置顶** → 游戏窗口长期浮在所有窗口之上

`_ensure_front_or_raise()` 在 `not front.ok` 时直接 `raise` 并**丢弃 `FrontResult`**；四处调用点（`input_sender.py:149 / :196 / :239 / :250`）的 `try/finally` 都在它**之后**才进入，于是 `_release_topmost_if_needed()` 永远不会执行：

```python
front = self._ensure_front_or_raise("点击")      # 失败在这里抛，front 丢失
try: ...
finally: self._release_topmost_if_needed(front)   # 到不了
```

而 `automation/real_input.py:214-232` 明确存在 `FrontResult(ok=False, set_topmost=True)` 这种"已置顶但置前失败"的返回；
此后每次调用都读到 `is_topmost=True` → `set_topmost=False` → **再也不会有人释放**。
触发场景正是本项目文档记录的实况（游戏以管理员运行 / `SetForegroundWindow` 被拒、错误 5）。

* **并且测试把该行为固化成了期望**：`tests/test_automation/test_real_input.py:540` 的假 `ensure_front` 返回 `set_topmost=True`，
  却断言 `all(event[0] in ("ensure_front",)...)`（即不得出现 `release_topmost`）。
* **建议**：把 `front` 的清理提到统一出口——`_ensure_front_or_raise` 内部失败时先 `real_input.release_topmost(hwnd)` 再抛；
  同时把该测试的期望改为"失败也必须取消**本次由我们设置的**置顶"。
* **规范依据**：`PROJECT_SPEC.md §4.2.3`「输入后收拾现场：取消**本次由我们设置的**置顶（避免游戏窗口长期浮在最上层）」。

---

## 3. P2 — Medium

### P2-1 `config/store.py:43-45` + `config/validation.py:78` — 更高版本的配置文件被判"损坏"并清空

`elif version != SCHEMA_VERSION:` → 报错 → `_recover()`。
**实测**：`schema_version = 99` 的文件加载后生成 `.bak`，活动 `config.json` 变成 v9 默认值。
`BUG_HUNT_GUIDE.md` 不变量 #17 写的是"未知版本原样不动"，但那只被 `migrate()` 的纯函数单测覆盖，**文件级行为相反**
（用户若曾用更高版本运行过，降级启动会丢全部设置）。
**建议**：`version > SCHEMA_VERSION` 时记 WARNING 并**只读返回默认值、不改动文件**。

### P2-2 `utils/logging_setup.py:13-33` + `gui/app.py:46` — `logging.*` 三项配置从不生效

`setup_logging()` 永远以无参调用（`level = INFO`），滚动文件用硬编码 `LOG_FILE_MAX_MB = 2` / `LOG_BACKUP_COUNT = 3`；
`config.logging.level / max_file_mb / backup_count` 被定义、被校验、被持久化，却对运行期零影响（设置页也未暴露这三项）。
与 `CHECKLIST.md §2`「max_file_mb、backup_count 生效」直接矛盾。
**建议**：`setup_logging()` 接受 `AppConfig.logging`，或在 `app.run()` 里显式传参。

### P2-3 `core/debug.py:100,145` — 调试连点/连续按键的间隔用硬编码 `time.sleep`，停止请求最迟 5 秒才生效

`INTERVAL_RANGE_MS = (50, 5000)` 且 `time.sleep(interval_ms / 1000)` 不可中断 →
违反 `AGENTS.md §2`「停止请求发出后 **500ms** 内必须停止动作序列」。
项目自己的 `TaskContext.interruptible_sleep`（0.1s 切片）就是正确写法，这里没复用；该 sleep 也不可注入，测试只能靠小间隔绕开。

### P2-4 `gui/main_window.py:437-445` — 全新会话里，运行中的调试动作无法从界面停止

```python
if self._runner is None:      # _runner 只在首次「启动」后才有值，且从不重置
    self.statusBar().showMessage("当前没有运行中的任务"); return
```

`stop_button` 初始 `setEnabled(False)`，只有 `_start()` 才启用 ——
于是"开发者调试 + 真实输入"（识别 1.6–5 s、长按可达 10 s）在**从未点过启动**的情况下：界面「停止」是灰的、`_on_stop_clicked` 也会早退；
调试页提示"…请先等待完成或点击「停止」"指向的按钮在该状态下无效。唯一退路是 F8，而 F8 注册失败在本机是常态
（本次冒烟日志即为 `ERROR 注册全局急停热键 F8 失败（可能被其他程序占用）`）。
**建议**：`_stop()` 与按钮可用性都按"runner 或 debug/capture 线程在跑"判定；`stop_button` 随任意长任务启用。

### P2-5 `gui/main_window.py:383-403` ↔ `:491-505` — 任务运行与调试测试互不互斥，可**并发注入真实输入**

`_start()` 只检查 `self._thread`，`_on_debug_test()` 只检查 `self._debug_thread`，两者都未检查对方；
调试页按钮在任务运行期间也未被 `set_busy` 禁用。两条 `RealInputSender` 会交错发送 `SendInput`，
并各自保存/还原真实光标（例如一边按住左键滑动、另一边插入点击），
本项目"每次输入前置顶 + 越界校验"的不变量无法覆盖这种交错。
**建议**：加一个共享的"输入忙"门闩（启动 / 调试 / 截图互斥）。

### P2-6 `gui/main_window.py:319-326` — `closeEvent` 不等待调试线程与截图线程；`wait()` 的返回值未检查

只 `wait` 了 `_diagnose_thread`；`_debug_thread` 仅 `request_stop()`（无 wait），`_capture_thread` 完全没处理，
两者都是无 parent 的 `QThread`（`main_window.py:123` / `:178`）。
运行中被销毁会触发 Qt 的 `QThread: Destroyed while thread is still running`（致命），
且进程退出会跳过 `finally` 里的左键/按键释放。`self._thread.wait(THREAD_WAIT_TIMEOUT_MS = 2000)` 超时也照常关闭。
*说明：此项为代码阅读结论，未实机复现（审查时无游戏窗口）。*

### P2-7 `automation/vision.py:393-417` — 取景兜底只覆盖"黑帧"，主取景**抛异常**时不再尝试其它方式

```python
width, height, bits = _render_client_bits(hwnd)   # 抛异常 → 直接向上冒
```

`_render_client_bgr_fallback`（含本作**唯一真正可用**的屏幕 BitBlt）只在 `is_blank_frame()` 为真时调用。
`GetWindowDC` / `CreateCompatibleBitmap` 失败（权限不足、窗口已关闭）会让整次识别以异常收场，而不是退到可用路径。
现有 `tests/test_automation/test_vision.py::test_capture_client_bgr_reports_render_failure` 把该行为固化为期望。
**建议**：主取景用 `try/except` 包住，失败也进兜底链，最后再抛可读错误。

### P2-8 `gui/dialogs/crop_dialog.py:260` — `mkdir` 在 `try` 之外，专门的失败提示成为死代码

```python
self._save_dir.mkdir(parents=True, exist_ok=True)   # OSError 直接冒进 Qt 槽
path = ...
try: self.saved_path = save_image(path, crop)
```

目录不可写时，`_on_save_clicked()` 里那句"保存失败：请检查模板目录是否可写（详情见日志）"永远走不到，
用户只会看到 Qt 打印的 traceback。**建议**：把 `mkdir` 移入 `try`。

### P2-9 `automation/window.py:106-160` — 窗口诊断截图没有黑帧检测，会把纯黑图当成功上报

`screenshot_client` 依次试 PrintWindow / 整窗 BitBlt 并 `SaveBitmapFile`，不判断结果是否纯色；
`diagnose_window` 随后报"窗口诊断完成… 截图 `<path>`"。
对同类 GPU 渲染窗口（视觉得到黑帧的那一类）会产出一张全黑 PNG 却宣称成功 ——
与视觉链路上"**绝不允许把黑帧当成正常结果**"的既定规则属同一类缺陷（`BUG_HUNT_GUIDE.md §⑥.5` 已列为已知但未修）。

---

## 4. P3 — Low

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| P3-1 | `core/state.py:11-24` + `core/runner.py:56-58,92-93` | 状态机无锁、check-then-act：`request_stop()` 先读 `state is RUNNING` 再 `transition(STOPPING)`，与 worker `finally` 置 `IDLE` 并发时可能命中非法的 `IDLE → STOPPING` → 异常在 GUI 线程抛出并使 `_stop()` 提前返回（跳过 `wait`）；`STOPPING → ERROR` 未允许，异常处理分支里的 `transition(ERROR)` 会二次抛出并掩盖原始异常 | 加锁 / `try_transition` |
| P3-2 | `gui/pages/daily.py:128-132,144-148` | `except ValueError:` 静默回退，不记日志（违反 `AGENTS.md §3.5`） | 补 `logger.warning`，说明输入被丢弃的原因 |
| P3-3 | `config/validation.py:180` | 要求 `params` 必须存在，而 `models.TaskConfig.from_dict` 容忍缺省（`data.get("params", {})`）→ 手写/精简配置省略 `params` 会被判损坏，走 P1-2 同一条"整份重置"路径 | 改为 `task.get("params", {})` |
| P3-4 | `core/runner.py:151` | 单功能组追加时不去重：`features.daily_tasks.tasks` 里若出现 `order_hold` 这类同名任务，会在队列里执行两次 | 对保留 ID 做校验或去重 |
| P3-5 | `config/validation.py:156` | `click_points` 没有长度上限（`keys` / `swipes` 都有 20 步上限） | 补上限 |
| P3-6 | `config/store.py:22-30` | `save()` 只捕获 `OSError`：`json.dump` 抛其它异常（如 `TypeError`）时 `config.json.tmp` 会残留（原子替换已做对，仅清理不全） | `except Exception` 里同样清理临时文件 |
| P3-7 | `utils/paths.py:11-38` | `mkdir(parents=True, exist_ok=True)` 无异常处理：权限/只读盘会以原始 traceback 冒泡 | 转成可读错误 + 降级 |
| P3-8 | `automation/real_input.py:468`、`:551-557` | `send_left_drag` 忽略 `move_cursor_absolute` 的返回值（移动失败仍可能报滑动成功）；`send_key_hold(slice_seconds <= 0)` 会因 `remaining -= 0` **死循环**（内部参数无防护） | 收集返回值 / 对 `slice_seconds` 取正下限 |
| P3-9 | `gui/main_window.py:358-367`、`automation/hotkey.py:47-55` | `_reload()` / `_reset()` 不调用 `_apply_hotkey_config()`，重载或恢复默认后配置里的新急停键要等下一次「保存」才生效；热键注册失败只写 ERROR 不阻断真实模式启动（与 P2-4 叠加） | 统一在应用配置时重注册热键；热键不可用时在状态栏显著提示 |
| P3-10 | `automation/vision.py`(642)、`gui/main_window.py`(695)；`real_input.py:54-55`；`core/vision.py:246`；`gui/pages/feature3.py` / `feature4.py` | 两个文件超 `AGENTS.md` 600 行硬线；`RELEASE_FLAGS` 与 `TOP_FLAGS` 取值完全相同（重复定义）；`format_matches_for_cli` 在 src/tests 中未见调用（疑似死代码）；功能三/四页面为逐行复制粘贴 | 见下方「Removal / Iteration Plan」 |

---

## 5. 已验证正确的部分（避免误伤）

* **分层**：AST 自检 `layer check violations = 0`（`core` 不引 PySide6/win32/ctypes，`automation` 不引 PySide6）。
* **注入面收敛**：`SendInput` / `SetCursorPos` 仅出现在 `automation/real_input.py`；无裸 `except`、无 `print`（CLI 除外）、无 TODO/FIXME、无任何网络调用。
* **任务编排**（`core/runner.py:141-160`）：日常组按 `(order, task_id)` 升序 → 单功能组固定 `order_hold → feature_3 → feature_4`；
  `daily_tasks.enabled` 与两个预留开关确实不参与编排；失败计数/循环对整队列生效、空队列立即结束 —— 与文档规则逐条一致。
* **占位任务边界**（`core/registry.py`）：三个占位任务只写"规划中 + 心跳"两行日志、不读 `params`、零输入、响应急停。
* **输入安全**：点击越界 `[0,w)×[0,h)`、滑动起终点双向校验、`drag` 任意退出路径释放左键并复查 `VK_LBUTTON`、
  缓出曲线 + 末尾静止帧、光标延迟分帧还原、`ensure_window_front` 每次输入前调用（均有对应测试）。
* **多尺度识别**：跨档携带 `best` 不会导致第二档被提前终止（`best[1] >= strong_score` 与"第一档已命中即 break"互斥），
  精修后判阈值、精修只接受严格更优、纯色模板在读取期拒绝 —— 逻辑自洽。
* 配置原子写、损坏恢复、迁移链（v1→v9）、数值上下限、GUI 页签 `ScrollablePage` 与开发者调试门禁均实现正确。
* `core/runner.py:164` 把 `get(task_id)` 放在 `try` 之外是**有意为之**（源码注释：「未注册任务仍走整体 ERROR（保持既有语义）」），不作为缺陷。

---

## 6. Removal / Iteration Plan

1. **拆 `automation/vision.py`**：把多尺度部分（`scale_candidates` / `_scale_tiers` / `_scan_coarse` / `_refine_scale` / `locate_all_scaled`，约 200 行）
   移到 `automation/multiscale.py`；**取景部分不要动**（刚做实机验证）。拆完重跑全量 + 一次实机交叉验证。
2. **拆 `gui/main_window.py`**：把 4 个 `QThread` 子类（`_RunnerThread` / `_DebugTestThread` / `_CaptureThread` / `_DiagnoseThread`，约 110 行）
   移到 `gui/workers.py` → 695 行降到约 585 行；顺带在 `workers.py` 里统一实现 P2-6 的"关闭时等待所有线程"。
3. **合并重复**：`RELEASE_FLAGS` 并入 `TOP_FLAGS`；`feature3/feature4` 抽成参数化的 `PlannedFeaturePage(title, attr)`；
   `format_matches_for_cli` 与 `runner.registered_ids()` 确认无调用后删除（后者目前仅测试使用，属公开 API，可保留但加注释）。
4. **修完 P1 后再动新功能**：工作区已有一份 +280 行的"点击时长"未提交改动，
   其中 `send_left_click` 重写恰好也走了"`finally` 必抬起 + 切片检查急停"的正确模式，可一并把 P2-3 的 `time.sleep` 换成同一套切片 sleep。

---

## 7. 未覆盖 / 未能验证

* 审查时**无游戏窗口**，所有真实输入路径仅做静态审查；P2-6（QThread 销毁）与 P3-1（状态机竞态）为代码阅读结论，未实机复现。
  建议修完后用"运行中关窗"与"F8 与任务同时结束"两个用例实测。
* 未审查未提交的工作区改动：审查期间**另一个会话**正在同一仓库修改
  `automation/input_sender.py`、`automation/real_input.py`、`core/debug.py`、`gui/main_window.py`、`gui/pages/debug.py` 及 5 个测试文件
  （"点击时长 / hold_ms"特性，+280 行），本报告结论仅对 `HEAD 7e56cc4` 负责。
* 未跑 PyInstaller 打包（Phase 7 产物）；未做性能与耗时实测。
* 多显示器、非 100% DPI、全屏独占模式未覆盖（项目已声明 MVP 不保证）。

---

## 8. 修复建议顺序

1. **P1-1**（启动崩溃）→ 2. **P1-2**（配置自毁）→ 3. **P1-3**（置顶泄漏，含改测试期望）
2. 再按 P2-3（急停延迟）→ P2-4 / P2-5（停止与互斥）→ P2-6（线程生命周期）→ P2-1 / P2-2 / P2-7 / P2-8 / P2-9
3. P3 随对应模块改动顺手处理；`vision.py` / `main_window.py` 的拆分单独成一个阶段（拆分前先补测试）。

> 修复时请遵守 `AGENTS.md §6` 小步推进：先写失败测试 → 最小实现 → 跑
> `pytest -q` + `--validate-config` + `--smoke-gui` + `--measure-layout`（改动页签时必须）→ `git diff --stat` 自查范围。
